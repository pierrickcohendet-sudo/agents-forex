"""Synthèse hebdomadaire (dimanche) et mensuelle (le 1er) des conséquences par devise (palier « 7-texte »).

PYTHON calcule tout, à partir du tableau des conséquences déjà calculé (core/consequences.py : sensibilité sur
5 ans, médiane sur le mois qui suit un mouvement d'1 écart-type, borne basse de Wilson à 90 %) :
- les faits de chaque devise (une ligne par engrenage où elle figure, avec la pastille du jour) ;
- un bilan (soutiens, pressions, indices faibles, moteurs calmes, n/d) ;
- une phrase de repli 100 % Python, toujours présente (« Indice faible · N cas » inclus).
Le MODÈLE formule seulement : UN appel regroupé (9 devises) dans le passage hebdo ou mensuel existant, après la
synthèse des engrenages (réserve de quota, core/llm.py). Une phrase qui cite un nombre absent des faits ou un
ordre d'achat / de vente est retirée ; un texte vide ou un quota atteint laisse la phrase Python.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from agents.agent_dossier_hebdo import _valeurs, semaine_iso, verifier_chiffres
from agents.agent_synthese import _retirer_ordres
from core.llm import (MESSAGE_QUOTA_ATTEINT, FournisseurLLM, QuotaAtteint, attribution_modele, definir_etiquette,
                      extraire_json, repli_modele_suivant)
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
NOMS_ENGRENAGES = {1: "Thème", 2: "Monétaire", 3: "Données", 4: "Fiscale", 5: "Marchés", 6: "Géopolitique",
                   7: "Flux", 8: "Offre"}
TENTATIVES_MAX = 3
FICHIER = "consequences_synthese.json"
MENTION = "Corrélation n'est pas causalité ; aide à la décision, jamais un ordre d'achat ou de vente."


# ------------------------------------------------------------------ périodes
def periode(type_: str, jour: date | None = None) -> str:
    """hebdo : semaine ISO qui se termine (passage du dimanche) ; mensuel : mois qui vient de s'achever."""
    jour = jour or date.today()
    if type_ == "hebdo":
        return semaine_iso(jour)
    veille_du_mois = jour.replace(day=1) - timedelta(days=1)
    return veille_du_mois.strftime("%Y-%m")


def a_faire(contenu: dict | None, type_: str, jour: date | None = None) -> bool:
    """Vrai si la synthèse de la période en cours manque ou est à retenter (texte du modèle absent)."""
    jour = jour or date.today()
    if type_ == "mensuel" and jour.day > 7:          # le 1er, ou le premier passage du mois (week-end, run manqué)
        return False
    entree = (contenu or {}).get(type_) or {}
    if entree.get("periode") != periode(type_, jour):
        return True
    return entree.get("statut") != "ok" and int(entree.get("tentatives", 0)) < TENTATIVES_MAX


# ------------------------------------------------------------------- faits (Python)
def _fr(v: float | None, d: int = 2) -> str:
    return "n/d" if v is None else f"{v:+.{d}f}".replace(".", ",").replace("-", "−")


def faits_devise(dossiers: dict, devise: str) -> dict:
    """Une ligne par engrenage dont le tableau des conséquences contient la devise."""
    lignes = []
    for numero, e in sorted(((dossiers or {}).get("engrenages") or {}).items(), key=lambda kv: int(kv[0])):
        tableau = (e or {}).get("consequences") or {}
        moteur = tableau.get("moteur") or {}
        for l in tableau.get("lignes") or []:
            if l.get("actif") != devise:
                continue
            auj = l.get("aujourdhui") or {}
            fiab = l.get("fiabilite") or {}
            lignes.append({
                "engrenage": int(numero), "nom": NOMS_ENGRENAGES.get(int(numero)), "moteur": moteur.get("libelle"),
                "variation_moteur_1m": moteur.get("variation_1m"), "date": moteur.get("date"),
                "lecture": auj.get("lecture") or ("n/d" if l.get("raison") else None),
                "n": auj.get("n") or fiab.get("n"), "part_sens_attendu": fiab.get("part"),
                "borne_wilson_90": fiab.get("borne_wilson_90"), "sensibilite": l.get("sensibilite"),
                "mediane_si_hausse": (l.get("si_hausse") or {}).get("mediane"),
                "mediane_si_baisse": (l.get("si_baisse") or {}).get("mediane"),
                "raison": auj.get("raison") or l.get("raison"),
            })
    comptes = {k: sum(1 for x in lignes if x["lecture"] == k) for k in ("Soutien", "Pression", "Indice faible", "Neutre", "n/d")}
    bilan = ("soutenue" if comptes["Soutien"] > comptes["Pression"] else
             "sous pression" if comptes["Pression"] > comptes["Soutien"] else "sans direction établie")
    return {"devise": devise, "lignes": lignes, "comptes": comptes, "bilan": bilan}


def phrase_python(f: dict) -> str:
    """Repli 100 % Python : bilan, puis chaque soutien, pression et indice faible avec son nombre de cas."""
    if not f["lignes"]:
        return f"{f['devise']} : aucune ligne du tableau des conséquences ne la concerne cette période."
    morceaux = []
    for lecture in ("Soutien", "Pression", "Indice faible"):
        for x in f["lignes"]:
            if x["lecture"] != lecture:
                continue
            detail = f"{lecture} · {x['n']} cas" if x.get("n") else lecture
            if lecture != "Indice faible" and x.get("borne_wilson_90") is not None:
                detail += f", borne de Wilson {str(x['borne_wilson_90']).replace('.', ',')} %"
            morceaux.append(f"{x['engrenage']}. {x['nom']} ({x['moteur']}) : {detail}")
    c = f["comptes"]
    calmes = f"{c['Neutre']} moteur(s) calme(s)" + (f", {c['n/d']} n/d" if c["n/d"] else "")
    tete = f"{f['devise']} : bilan {f['bilan']} ({c['Soutien']} soutien(s), {c['Pression']} pression(s), " \
           f"{c['Indice faible']} indice(s) faible(s), {calmes})."
    return tete + (" " + " ; ".join(morceaux) + "." if morceaux else " Aucun moteur hors de sa zone calme.")


# ------------------------------------------------------------------- texte (modèle)
SCHEMA = '{"devises": {"USD": "2 phrases au plus", "EUR": "...", ...}}'


def _prompt(type_: str, per: str, faits: dict[str, dict]) -> str:
    allege = {d: {"bilan": f["bilan"], "comptes": f["comptes"],
                  "lignes": [{k: x[k] for k in ("engrenage", "nom", "moteur", "lecture", "n", "part_sens_attendu",
                                                 "borne_wilson_90", "mediane_si_hausse", "mediane_si_baisse")}
                             for x in f["lignes"] if x["lecture"] in ("Soutien", "Pression", "Indice faible")]}
              for d, f in faits.items()}
    return ("Rédige la synthèse " + ("hebdomadaire" if type_ == "hebdo" else "mensuelle") + f" ({per}) des conséquences "
            "par devise, en français, 2 phrases au plus par devise. Utilise UNIQUEMENT les chiffres fournis (cas, part du "
            "sens attendu, borne de Wilson, médianes). Un « Indice faible » doit être présenté comme une preuve insuffisante, "
            "jamais comme un signal. Aucune recommandation, aucun ordre d'achat ou de vente, aucun niveau de prix. "
            "Corrélation n'est pas causalité.\n"
            f"Réponds STRICTEMENT en JSON : {SCHEMA}\n\nFAITS CALCULÉS EN PYTHON (JSON) :\n"
            + json.dumps(allege, ensure_ascii=False))


def generer(type_: str, dossiers: dict, llm: FournisseurLLM | None, existant: dict | None = None,
            jour: date | None = None, tentatives_json: int = 2) -> dict:
    """Synthèse de la période. Ne lève jamais : statut ok (texte du modèle) ou indisponible (phrases Python)."""
    per = periode(type_, jour)
    precedentes = int(existant.get("tentatives", 0)) if (existant or {}).get("periode") == per else 0
    faits = {d: faits_devise(dossiers, d) for d in DEVISES}
    sortie = {"type": type_, "periode": per, "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "donnees_du": (dossiers or {}).get("genere_le"), "mention": MENTION,
              "devises": {d: {"faits": f, "phrase_python": phrase_python(f), "texte": None} for d, f in faits.items()},
              "statut": "indisponible", "tentatives": precedentes + 1, "controles": []}
    if llm is None:
        sortie["raison"] = "fournisseur LLM indisponible"
        return sortie
    autorises = _valeurs(faits, set())
    definir_etiquette(f"consequences:{type_}")   # passe par la réserve : refusé tant que les engrenages manquent
    derniere = None
    for _ in range(max(1, tentatives_json)):
        try:
            brut = extraire_json(llm.appeler_llm(_prompt(type_, per, faits)))
            textes = (brut or {}).get("devises") if isinstance(brut, dict) else None
            if not isinstance(textes, dict):
                raise ValueError("réponse sans « devises »")
            gardes = 0
            for d in DEVISES:
                t, ordres = _retirer_ordres(str(textes.get(d) or "")[:600])
                t, retirees = verifier_chiffres(t, autorises)
                if ordres or retirees:
                    sortie["controles"].append(f"{d} : {ordres + retirees} phrase(s) retirée(s) (ordre ou chiffre absent des faits)")
                if t:
                    sortie["devises"][d]["texte"] = t
                    gardes += 1
            if gardes == 0:
                raise ValueError("aucun texte exploitable")
            sortie.update({"statut": "ok", "redige_par": attribution_modele(), "raison": None})
            return sortie
        except QuotaAtteint as exc:
            sortie.update({"raison": MESSAGE_QUOTA_ATTEINT, "quota_atteint": True, "tentatives": precedentes,
                           "detail_quota": masquer_secrets(str(exc))[:200]})
            log.warning("Synthèse %s des conséquences : quota atteint — phrases Python publiées", type_)
            return sortie
        except Exception as exc:  # noqa: BLE001
            repli_modele_suivant(llm)
            derniere = exc
            log.warning("Synthèse %s des conséquences : essai en échec (%s)", type_, masquer_secrets(str(exc)))
    sortie["raison"] = f"réponse du modèle inexploitable : {masquer_secrets(str(derniere))[:150]}"
    return sortie


def executer(type_: str, racine: Path, config: dict, dossiers: dict | None, llm: FournisseurLLM | None,
             jour: date | None = None) -> dict | None:
    """Lit docs/data/consequences_synthese.json, produit la période si elle est à faire, écrit le fichier et
    l'archive data/hebdo/. Retourne la nouvelle entrée (None si rien à faire ou dossiers absents)."""
    docs_data = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
    chemin = docs_data / FICHIER
    try:
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        contenu = {}
    if not a_faire(contenu, type_, jour) or not dossiers:
        return None
    existant = contenu.get(type_)
    entree = generer(type_, dossiers, llm, existant, jour, int((config.get("llm") or {}).get("max_tentatives_json", 2)))
    contenu[type_] = entree
    chemin.write_text(json.dumps(contenu, ensure_ascii=False, indent=1), encoding="utf-8")
    archive = Path(racine) / config["chemins"]["donnees"] / "hebdo" / f"consequences_{type_}_{entree['periode']}.json"
    try:
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(json.dumps(entree, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        log.warning("Archive de la synthèse des conséquences non écrite : %s", exc)
    log.info("Synthèse %s des conséquences (%s) : %s", type_, entree["periode"], entree["statut"])
    return entree
