"""Texte hebdomadaire d'économiste des 8 engrenages (dossier économiste, palier 3) — mode --hebdo.

Un appel LLM par engrenage (5 blocs : le constat, le mécanisme, ce qui pourrait tout changer, les
implications par devise, un précédent utile ; plus 📘 Comprendre et 🎯 Ce que regarde un desk), puis
une synthèse finale (thème de la semaine, chaînes de transmission, ce qui pourrait tout changer la
semaine prochaine). Une fois par semaine (dimanche).

Le modèle ne reçoit QUE les chiffres déjà calculés (docs/data/dossiers.json + précédents Python) et
ne calcule rien. Contrôles Python : tout nombre cité doit exister dans les données fournies (sinon la
phrase est retirée et signalée) ; précédent sous 5 cas : texte Python imposé « précédents
insuffisants » ; « record » / « s'envole » contrôlés ; « indice or (proxy) » ; aucun ordre.
Chaque engrenage échoue isolément ; une relance ne refait que ce qui manque.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

from agents.agent_engrenages import (NOMS, justifications, moderer_vocabulaire, nommer_or)
from agents.agent_synthese import _retirer_ordres, _texte
from core.llm import (MESSAGE_QUOTA_ATTEINT, FournisseurLLM, QuotaAtteint, attribution_modele,
                      definir_etiquette, extraire_json)
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

RACINE = Path(__file__).resolve().parent.parent
FICHIER_CADRE = RACINE / "connaissances" / "engrenages" / "cadre_engrenages.md"
DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
BLOCS = ("constat", "mecanisme", "ce_qui_pourrait_tout_changer", "precedent", "comprendre", "desk")
# Petits entiers et horizons usuels (« 5 ans », « 52 semaines », dates « 02/10 ») tolérés sans source.
ENTIERS_LIBRES = set(range(0, 32)) | {52, 90, 100, 200}

SCHEMA_ENGRENAGE = """{
  "constat": "3-4 phrases : la situation, chiffres des tableaux uniquement",
  "mecanisme": "2-3 phrases : comment cet engrenage agit sur les devises",
  "ce_qui_pourrait_tout_changer": "2-3 phrases : le signal précis qui retournerait la lecture",
  "implications": [{"devise": "XXX", "texte": "1-2 phrases"}],
  "precedent": "raconte le précédent fourni SANS changer ses chiffres, ou recopie « Précédents insuffisants… »",
  "comprendre": "2-3 phrases pédagogiques",
  "desk": "le signal précis qu'un desk surveille et pourquoi"
}"""
SCHEMA_SYNTHESE = """{
  "theme_semaine": "3-4 phrases : le récit dominant de la semaine",
  "chaines": [{"titre": "...", "maillons": [{"engrenage": 1-8, "texte": "..."}]}],
  "conflits": [{"engrenages": [n, m], "texte": "..."}],
  "ce_qui_pourrait_tout_changer": "2-3 phrases : la semaine prochaine"
}"""


# ----------------------------------------------------------------- contexte
_CLES_INUTILES = {"serie_90j", "points", "courbes", "barres", "historique", "lien"}


def _alleger(valeur):
    """Copie sans les séries de points (graphiques) : le modèle n'a besoin que des chiffres affichés."""
    if isinstance(valeur, dict):
        return {k: _alleger(v) for k, v in valeur.items() if k not in _CLES_INUTILES and v is not None}
    if isinstance(valeur, list):
        return [_alleger(v) for v in valeur]
    return valeur


def contexte_engrenage(numero: str, dossiers: dict, precedents: list[dict], rapport: dict | None) -> dict:
    e = _alleger(copy.deepcopy((dossiers.get("engrenages") or {}).get(numero) or {}))
    for g in e.get("graphiques", []) or []:
        g.pop("source", None)
    quotidien = {}
    for x in (((rapport or {}).get("synthese_globale") or {}).get("engrenages") or {}).get("engrenages", []):
        if str(x.get("numero")) == numero:
            quotidien = {"direction_calculee": (x.get("direction") or {}).get("calculee"),
                         "conviction": (x.get("conviction") or {}).get("niveau")}
    return {"engrenage": int(numero), "nom": NOMS[int(numero)], "date_des_donnees": dossiers.get("genere_le"),
            "tableau": e, "precedents_calcules": precedents, "lecture_quotidienne": quotidien}


# ------------------------------------------------------- vérification des chiffres
_NOMBRE = re.compile(r"(?<![\d.,WQTSH])[+\-−]?\d+(?:[  ]\d{3})*(?:[.,]\d+)?")   # « p62 », « 62e » : 62 lu


def _valeurs(objet, sortie: set[float]) -> set[float]:
    """Tous les nombres présents dans les données fournies (y compris dans les textes)."""
    if isinstance(objet, bool):
        return sortie
    if isinstance(objet, (int, float)):
        sortie.add(abs(float(objet)))
    elif isinstance(objet, str):
        for m in _NOMBRE.findall(objet):
            try:
                sortie.add(abs(float(m.replace("−", "-").replace(" ", "").replace(" ", "").replace(",", "."))))
            except ValueError:
                pass
    elif isinstance(objet, dict):
        for v in objet.values():
            _valeurs(v, sortie)
    elif isinstance(objet, list):
        for v in objet:
            _valeurs(v, sortie)
    return sortie


def _connu(x: float, autorises: set[float]) -> bool:
    x = abs(x)
    if x == int(x) and int(x) in ENTIERS_LIBRES or 2000 <= x <= 2035:
        return True
    for a in autorises:
        if abs(x - a) <= 1e-9 or any(round(a, d) == round(x, d) == x for d in (0, 1, 2)):
            return True
        if a and abs(x - a) / abs(a) <= 0.005:          # arrondi de présentation (ex. 121,38 pour 121,3848)
            return True
    return False


def verifier_chiffres(texte: str, autorises: set[float]) -> tuple[str, int]:
    """Retire chaque phrase qui cite un nombre absent des données. (texte, nb de phrases retirées)."""
    if not texte:
        return texte, 0
    phrases = re.split(r"(?<=[.!?])\s+", texte)
    gardees, retirees = [], 0
    for p in phrases:
        nombres = []
        for m in _NOMBRE.findall(p):
            try:
                nombres.append(float(m.replace("−", "-").replace(" ", "").replace(" ", "").replace(",", ".")))
            except ValueError:
                pass
        if all(_connu(n, autorises) for n in nombres):
            gardees.append(p)
        else:
            retirees += 1
    return " ".join(gardees).strip(), retirees


# ------------------------------------------------------------------- normalisation
def normaliser_engrenage(brut: dict, numero: str, contexte: dict, permis: dict) -> dict:
    autorises = _valeurs(contexte, set())
    controles, retraits_chiffres, retraits_ordres, moderes = [], 0, 0, 0

    def propre(t, maximum=900):
        nonlocal retraits_chiffres, retraits_ordres, moderes
        net, n = _retirer_ordres(_texte(t, maximum))
        retraits_ordres += n
        net, n = verifier_chiffres(net, autorises)
        retraits_chiffres += n
        net, n = moderer_vocabulaire(nommer_or(net), permis)
        moderes += n
        return net

    sortie = {cle: propre(brut.get(cle)) for cle in BLOCS}
    sortie["implications"] = [{"devise": i["devise"].upper(), "texte": propre(i.get("texte"), 400)}
                              for i in (brut.get("implications") or [])
                              if isinstance(i, dict) and str(i.get("devise", "")).upper() in DEVISES and _texte(i.get("texte"))][:6]
    precedents = contexte.get("precedents_calcules") or []
    if not any(p.get("suffisant") for p in precedents):
        # Moins de 5 cas (ou pas d'indicateur) : le texte est celui de Python, jamais une histoire inventée.
        sortie["precedent"] = " ".join(p["texte"] for p in precedents) or "Précédents insuffisants."
        sortie["precedent_impose"] = True
    elif not sortie["precedent"]:
        sortie["precedent"] = " ".join(p["texte"] for p in precedents if p.get("suffisant"))
        sortie["precedent_impose"] = True
        controles.append("précédent absent ou non vérifiable dans la réponse : texte Python repris")
    vides = [cle for cle in ("constat", "mecanisme", "ce_qui_pourrait_tout_changer") if not sortie[cle]]
    if vides:
        controles.append(f"bloc(s) vide(s) après contrôle : {', '.join(vides)}")
    if retraits_chiffres:
        controles.append(f"{retraits_chiffres} phrase(s) retirée(s) : chiffre absent des tableaux fournis")
    if retraits_ordres:
        controles.append(f"{retraits_ordres} phrase(s) retirée(s) : formulation d'ordre d'achat/vente")
    if moderes:
        controles.append(f"{moderes} mot(s) « record » / « s'envole » remplacé(s)")
    sortie["controles"] = controles
    sortie["precedents"] = precedents
    if not sortie["constat"]:
        raise ValueError("constat vide après contrôle des chiffres")
    return sortie


def normaliser_synthese(brut: dict, autorises: set[float], permis: dict) -> dict:
    controles, retraits = [], 0

    def propre(t, maximum=900):
        nonlocal retraits
        net, _ = _retirer_ordres(_texte(t, maximum))
        net, n = verifier_chiffres(net, autorises)
        retraits += n
        return moderer_vocabulaire(nommer_or(net), permis)[0]

    chaines = []
    for c in (brut.get("chaines") or [])[:3]:
        maillons = [{"engrenage": int(m["engrenage"]), "texte": propre(m.get("texte"), 300)}
                    for m in (c.get("maillons") or []) if isinstance(m, dict) and str(m.get("engrenage", "")).isdigit()
                    and 1 <= int(m["engrenage"]) <= 8 and _texte(m.get("texte"))]
        maillons = [m for m in maillons if m["texte"]]
        if len(maillons) >= 2:
            chaines.append({"titre": propre(c.get("titre"), 160), "maillons": maillons})
    conflits = [{"engrenages": [int(x) for x in c.get("engrenages", [])][:2], "texte": propre(c.get("texte"), 400)}
                for c in (brut.get("conflits") or []) if isinstance(c, dict) and len(c.get("engrenages") or []) >= 2]
    sortie = {"theme_semaine": propre(brut.get("theme_semaine")), "chaines": chaines,
              "conflits": [c for c in conflits if c["texte"]],
              "ce_qui_pourrait_tout_changer": propre(brut.get("ce_qui_pourrait_tout_changer"))}
    if retraits:
        controles.append(f"{retraits} phrase(s) retirée(s) : chiffre absent des tableaux fournis")
    if not sortie["theme_semaine"]:
        raise ValueError("thème de la semaine vide après contrôle")
    sortie["controles"] = controles
    return sortie


# --------------------------------------------------------------------- appels
def _appeler(llm: FournisseurLLM, systeme: str, prompt: str, tentatives: int, normaliser) -> dict:
    derniere = None
    for _ in range(tentatives):
        try:
            brut = extraire_json(llm.appeler_llm(prompt, systeme=systeme))
            if not isinstance(brut, dict):
                raise ValueError("réponse JSON non conforme")
            sortie = normaliser(brut)
            sortie["redige_par"] = attribution_modele()
            return sortie
        except QuotaAtteint:
            raise
        except Exception as exc:  # noqa: BLE001
            derniere = exc
            log.warning("Dossier hebdo : essai en échec (%s)", masquer_secrets(str(exc)))
    raise RuntimeError(masquer_secrets(str(derniere)))


def semaine_iso(jour: date | None = None) -> str:
    a, s, _ = (jour or date.today()).isocalendar()
    return f"{a}-W{s:02d}"


def generer(config: dict, llm: FournisseurLLM, dossiers: dict, precedents: dict[str, list], rapport: dict | None,
            existant: dict | None = None) -> dict:
    """{semaine, genere_le, engrenages: {n: {...}}, synthese: {...}}. Reprise : ce qui est déjà « ok »
    pour la même semaine n'est pas rappelé. Ne lève jamais."""
    semaine = semaine_iso()
    existant = existant if (existant or {}).get("semaine") == semaine else {}
    sortie = {"semaine": semaine, "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "donnees_du": dossiers.get("genere_le"), "engrenages": dict((existant or {}).get("engrenages") or {}),
              "synthese": (existant or {}).get("synthese")}
    systeme = (FICHIER_CADRE.read_text(encoding="utf-8") if FICHIER_CADRE.exists() else "") + """

## Mode hebdomadaire : dossier d'économiste
- Tu ne CALCULES rien. Tu n'utilises QUE les chiffres présents dans les données fournies, tels quels
  (arrondis de présentation acceptés). Tout autre chiffre fera retirer la phrase.
- Le précédent historique est calculé par programme : raconte-le sans changer ses chiffres. S'il
  est « insuffisant », recopie la phrase fournie.
- Une donnée « n/d » reste « n/d » : explique pourquoi elle manque (raison fournie), n'invente rien."""
    justif = justifications(dossiers)
    tentatives = int(config["llm"].get("max_tentatives_json", 2))
    quota = False
    for numero in [str(n) for n in range(1, 9)]:
        deja = sortie["engrenages"].get(numero) or {}
        if deja.get("statut") == "ok":
            continue
        if quota:
            sortie["engrenages"][numero] = {"statut": "indisponible", "raison": MESSAGE_QUOTA_ATTEINT, "quota_atteint": True}
            continue
        contexte = contexte_engrenage(numero, dossiers, precedents.get(numero, []), rapport)
        prompt = (f"Rédige le dossier hebdomadaire de l'engrenage {numero} ({NOMS[int(numero)]}) en 5 blocs, "
                  "plus 📘 Comprendre et 🎯 Ce que regarde un desk. Implications : les devises les plus concernées, "
                  f"une phrase chacune. Réponds STRICTEMENT selon ce schéma JSON :\n{SCHEMA_ENGRENAGE}\n\n"
                  "DONNÉES (JSON) :\n" + json.dumps(contexte, ensure_ascii=False, default=str))
        definir_etiquette(f"hebdo:{numero}")
        try:
            r = _appeler(llm, systeme, prompt, tentatives,
                         lambda b, n=numero, c=contexte: normaliser_engrenage(b, n, c, justif.get(int(n), {})))
            r.update({"statut": "ok", "numero": int(numero), "nom": NOMS[int(numero)]})
            sortie["engrenages"][numero] = r
        except QuotaAtteint:
            quota = True
            sortie["engrenages"][numero] = {"statut": "indisponible", "raison": MESSAGE_QUOTA_ATTEINT, "quota_atteint": True}
        except Exception as exc:  # noqa: BLE001 — un engrenage en échec n'affecte que lui
            sortie["engrenages"][numero] = {"statut": "indisponible", "raison": masquer_secrets(str(exc))[:200],
                                            "precedents": precedents.get(numero, [])}
    # Synthèse finale : seulement si au moins 5 engrenages sont rédigés
    reussis = {n: e for n, e in sortie["engrenages"].items() if e.get("statut") == "ok"}
    if (sortie.get("synthese") or {}).get("statut") != "ok":
        if quota:
            sortie["synthese"] = {"statut": "indisponible", "raison": MESSAGE_QUOTA_ATTEINT, "quota_atteint": True}
        elif len(reussis) < 5:
            sortie["synthese"] = {"statut": "indisponible", "raison": f"{len(reussis)} engrenage(s) rédigé(s) sur 8 (minimum 5)"}
        else:
            contexte = {"engrenages": {n: {"nom": e["nom"], "constat": e["constat"], "ce_qui_pourrait_tout_changer":
                                           e["ce_qui_pourrait_tout_changer"], "implications": e["implications"]}
                                       for n, e in sorted(reussis.items())},
                        "theme_calcule": _alleger((dossiers.get("engrenages") or {}).get("1") or {})}
            autorises = _valeurs(contexte, set())
            for n in reussis:
                autorises |= _valeurs(contexte_engrenage(n, dossiers, precedents.get(n, []), rapport), set())
            permis = {"record": any(v.get("record") for v in justif.values()), "envol": any(v.get("envol") for v in justif.values())}
            prompt = ("Rédige la synthèse finale de la semaine à partir des dossiers des engrenages ci-dessous : le thème "
                      "macro de la semaine, une à trois chaînes de transmission (chaque maillon rattaché à un engrenage), "
                      "les engrenages en conflit et ce qui pourrait tout changer la semaine prochaine. Réponds STRICTEMENT "
                      f"selon ce schéma JSON :\n{SCHEMA_SYNTHESE}\n\nDONNÉES (JSON) :\n"
                      + json.dumps(contexte, ensure_ascii=False, default=str))
            definir_etiquette("hebdo:synthese")
            try:
                r = _appeler(llm, systeme, prompt, tentatives, lambda b: normaliser_synthese(b, autorises, permis))
                r["statut"] = "ok"
                sortie["synthese"] = r
            except QuotaAtteint:
                sortie["synthese"] = {"statut": "indisponible", "raison": MESSAGE_QUOTA_ATTEINT, "quota_atteint": True}
            except Exception as exc:  # noqa: BLE001
                sortie["synthese"] = {"statut": "indisponible", "raison": masquer_secrets(str(exc))[:200]}
    return sortie


def a_faire(contenu: dict | None) -> bool:
    if (contenu or {}).get("semaine") != semaine_iso():
        return True
    return any((e or {}).get("statut") != "ok" for e in (contenu.get("engrenages") or {}).values()) \
        or len(contenu.get("engrenages") or {}) < 8 or (contenu.get("synthese") or {}).get("statut") != "ok"
