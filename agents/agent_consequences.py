"""Synthèse hebdomadaire (dimanche) et mensuelle (le 1er) des conséquences par devise (palier « 7-texte »).

PYTHON calcule tout, à partir du tableau des conséquences déjà calculé (core/consequences.py : sensibilité sur
5 ans, médiane sur le mois qui suit un mouvement d'1 écart-type, borne basse de Wilson à 90 %) :
- les faits de chaque devise (une ligne par engrenage où elle figure, avec la pastille du jour) ;
- un bilan (soutiens, pressions, indices faibles, moteurs calmes, n/d) ;
- une phrase de repli 100 % Python, toujours présente (« Indice faible · N cas » inclus).
Le MODÈLE formule seulement : UN appel regroupé (9 devises + une synthèse d'ensemble) dans le passage hebdo ou
mensuel existant, après la synthèse des engrenages (réserve de quota, core/llm.py). Une phrase qui cite un nombre
absent des faits ou un ordre d'achat / de vente est retirée ; un texte vide ou un quota atteint laisse la phrase Python.
Lot Verrouillage : le texte cite les MOTEURS (nom, variation, zone), les chiffres marquants de la semaine et les
évènements de la semaine suivante ; un texte qui ne cite aucun moteur, ou qui répète des compteurs (« 4 cas
neutres »), est rejeté en Python et la phrase Python (qui cite les moteurs) est publiée à sa place.
"""
from __future__ import annotations

import json
import logging
import re
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
# Compteurs interdits dans le texte du modèle (« 4 cas neutres », « 3 moteur(s) calme(s) », « 1 cas non disponible »)
COMPTEUR = re.compile(r"\b\d+\s+(?:cas|moteurs?(?:\(s\))?|lignes?)\s+(?:neutres?|calmes?(?:\(s\))?|non\s+disponibles?|n/d)", re.I)
# Mots qui désignent un moteur dans un texte libre (en plus de son libellé complet)
ALIAS_MOTEURS = {"VIX": ["vix", "volatilité"], "Brent": ["brent", "pétrole"], "écart 2 ans": ["écart 2 ans", "2 ans"],
                 "prime de terme": ["prime de terme"], "stocks de brut": ["stocks de brut", "stocks"],
                 "surprise": ["surprise"], "score de confluence": ["confluence"], "COT": ["cot", "positionnement"]}
SERIES_SEMAINE = [("dollar_large", "Indice dollar large (Fed)", "%"), ("USD_2a", "Rendement 2 ans US", "pb"),
                  ("USD_10a", "Rendement 10 ans US", "pb"), ("vix", "VIX", "pts"), ("brent", "Brent", "%"),
                  ("sp500", "S&P 500", "%"), ("indice_or", "Indice or (proxy)", "%")]


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
            sigma, var = l.get("sigma_moteur"), moteur.get("variation_1m")
            lignes.append({
                "engrenage": int(numero), "nom": NOMS_ENGRENAGES.get(int(numero)), "moteur": moteur.get("libelle"),
                "variation_moteur_1m": var, "unite": moteur.get("unite"), "date": moteur.get("date"),
                "sigma_moteur": sigma, "zone": zone(var, sigma),
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


def zone(variation: float | None, sigma: float | None) -> str:
    """Zone du moteur sur 1 mois : calme (dans ±1 écart-type), haute ou basse, n/d."""
    if variation is None or not sigma:
        return "n/d"
    return "calme" if abs(variation) < sigma else ("haute" if variation > 0 else "basse")


def _unite(u: str | None) -> str:
    return {"pb": " pb", "%": " %", "pts": " pts"}.get(u or "", "")


def texte_moteur(x: dict) -> str:
    """« VIX +0,84 pts sur 1 mois (zone calme, ±5,13) » : nom, variation, zone."""
    if x.get("variation_moteur_1m") is None:
        return f"{x['moteur']} (n/d)"
    z = {"calme": "zone calme", "haute": "au-dessus de +1 écart-type", "basse": "au-dessous de −1 écart-type"}.get(x["zone"], "zone n/d")
    sig = f", ±{_fr(x['sigma_moteur']).lstrip('+')}" if x.get("sigma_moteur") else ""
    return f"{x['moteur']} {_fr(x['variation_moteur_1m'])}{_unite(x.get('unite'))} sur 1 mois ({z}{sig})"


def _actifs(lignes: list[dict], n: int = 3) -> list[dict]:
    """Moteurs les plus éloignés de leur zone calme (|variation| / écart-type), sans doublon."""
    vus, sortie = set(), []
    for x in sorted(lignes, key=lambda x: -(abs(x.get("variation_moteur_1m") or 0) / (x.get("sigma_moteur") or 1e9))):
        if x.get("moteur") and x["moteur"] not in vus and x.get("variation_moteur_1m") is not None:
            vus.add(x["moteur"])
            sortie.append(x)
    return sortie[:n]


def phrase_python(f: dict) -> str:
    """Repli 100 % Python : bilan, moteurs (nom, variation, zone), puis soutiens, pressions et indices faibles avec
    leur nombre de cas. Jamais de compteur de cas neutres."""
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
    moteurs = _actifs(f["lignes"], 2)
    tete = f"{f['devise']} : bilan {f['bilan']}."
    if moteurs:
        tete += " Moteurs : " + " ; ".join(texte_moteur(x) for x in moteurs) + "."
    return tete + (" " + " ; ".join(morceaux) + "." if morceaux else " Aucun moteur hors de sa zone calme.")


# ------------------------------------------------------------------- contexte de la période (Python)
def chiffres_semaine(h5) -> list[dict]:
    """Variation sur 5 séances des séries canoniques (historique 5 ans), classées par ampleur."""
    sortie = []
    for cle, libelle, unite in SERIES_SEMAINE:
        try:
            pts = [p for p in (h5.serie(cle) if h5 is not None else []) if p[1] is not None]
        except Exception:  # noqa: BLE001
            pts = []
        if len(pts) < 6:
            continue
        (d0, v0), (d1, v1) = pts[-6], pts[-1]
        var = (v1 - v0) * 100 if unite == "pb" else (v1 - v0 if unite == "pts" else (v1 / v0 - 1) * 100 if v0 else None)
        if var is not None:
            sortie.append({"libelle": libelle, "variation_5s": round(var, 2), "unite": unite, "du": str(d0)[:10], "au": str(d1)[:10],
                           "niveau": round(v1, 2)})
    return sorted(sortie, key=lambda x: -abs(x["variation_5s"]) / {"pb": 10, "pts": 1, "%": 1}[x["unite"]])


def semaine_suivante(agenda_donnees: dict | None, jour: date | None = None, n: int = 8) -> list[dict]:
    """Évènements à fort impact des 7 jours qui suivent, décisions de banques centrales d'abord (agenda.json)."""
    debut = (jour or date.today()).isoformat()
    fin = ((jour or date.today()) + timedelta(days=8)).isoformat()
    evts = [e for j in (agenda_donnees or {}).get("jours") or [] for e in j.get("evenements") or []
            if e.get("impact") == "fort" and debut <= e.get("date_paris", "") <= fin]
    evts.sort(key=lambda e: (e.get("type") != "Réunion BC", e.get("iso_utc", "")))
    return [{"date": e["date_paris"], "devise": e["devise"], "evenement": e["evenement"], "type": e.get("type"),
             "consensus": e.get("consensus")} for e in evts[:n]]


def synthese_python(faits: dict[str, dict], contexte: dict) -> str:
    tous = [x for f in faits.values() for x in f["lignes"]]
    morceaux = []
    act = _actifs(tous, 3)
    if act:
        morceaux.append("Moteurs les plus actifs : " + " ; ".join(texte_moteur(x) for x in act) + ".")
    ch = (contexte or {}).get("chiffres_semaine") or []
    if ch:
        morceaux.append("Chiffres de la semaine : " + " ; ".join(
            f"{c['libelle']} {_fr(c['variation_5s'])}{_unite(c['unite'])} sur 5 séances" for c in ch[:3]) + ".")
    ev = (contexte or {}).get("semaine_suivante") or []
    morceaux.append(("Semaine suivante : " + " ; ".join(f"{e['devise']} {e['evenement']} ({e['date'][8:10]}/{e['date'][5:7]})" for e in ev[:5]) + ".")
                    if ev else "Semaine suivante : aucun évènement à fort impact au calendrier collecté.")
    return " ".join(morceaux)


def cite_un_moteur(texte: str, lignes: list[dict]) -> bool:
    t = (texte or "").lower()
    for x in lignes:
        m = str(x.get("moteur") or "")
        if m and m.lower() in t:
            return True
        for cle, alias in ALIAS_MOTEURS.items():
            if cle.lower() in m.lower() and any(a in t for a in alias):
                return True
    return False


def controler_texte(texte: str, lignes: list[dict]) -> str | None:
    """Raison du rejet, ou None si le texte est acceptable (cite un moteur, aucun compteur répété)."""
    if not texte:
        return None
    if COMPTEUR.search(texte):
        return "compteur répété (« X cas neutres »)"
    if lignes and not cite_un_moteur(texte, lignes):
        return "aucun moteur cité"
    return None


# ------------------------------------------------------------------- texte (modèle)
SCHEMA = '{"synthese": "3 phrases au plus", "devises": {"USD": "2 phrases au plus", "EUR": "...", ...}}'


def _prompt(type_: str, per: str, faits: dict[str, dict], contexte: dict | None = None) -> str:
    allege = {d: {"bilan": f["bilan"],
                  "moteurs": [{"engrenage": x["engrenage"], "moteur": x["moteur"], "variation_1m": x["variation_moteur_1m"],
                               "unite": x.get("unite"), "zone": x["zone"], "ecart_type": x.get("sigma_moteur")}
                              for x in _actifs(f["lignes"], 3)],
                  "lignes": [{k: x[k] for k in ("engrenage", "nom", "moteur", "lecture", "n", "part_sens_attendu",
                                                 "borne_wilson_90", "mediane_si_hausse", "mediane_si_baisse")}
                             for x in f["lignes"] if x["lecture"] in ("Soutien", "Pression", "Indice faible")]}
              for d, f in faits.items()}
    ctx = {"chiffres_de_la_semaine": (contexte or {}).get("chiffres_semaine") or [],
           "evenements_semaine_suivante": (contexte or {}).get("semaine_suivante") or []}
    return ("Rédige la synthèse " + ("hebdomadaire" if type_ == "hebdo" else "mensuelle") + f" ({per}) des conséquences, "
            "en français. « synthese » : 3 phrases au plus qui citent les moteurs les plus actifs (nom, variation sur 1 mois, "
            "zone : calme ou au-delà d'un écart-type), les chiffres les plus marquants de la semaine et les évènements de la "
            "semaine suivante. Pour chaque devise, 2 phrases au plus qui citent AU MOINS UN moteur par son nom avec sa "
            "variation et sa zone, puis les soutiens, pressions ou indices faibles. INTERDIT : les compteurs du type "
            "« 4 cas neutres », « 3 moteurs calmes » ou « 1 cas non disponible » ; un texte qui ne cite aucun moteur est rejeté. "
            "Utilise UNIQUEMENT les chiffres fournis. Un « Indice faible » est une preuve insuffisante, jamais un signal. "
            "Aucune recommandation, aucun ordre d'achat ou de vente, aucun niveau de prix. Corrélation n'est pas causalité.\n"
            f"Réponds STRICTEMENT en JSON : {SCHEMA}\n\nFAITS CALCULÉS EN PYTHON (JSON) :\n"
            + json.dumps({"devises": allege, "contexte": ctx}, ensure_ascii=False))


def generer(type_: str, dossiers: dict, llm: FournisseurLLM | None, existant: dict | None = None,
            jour: date | None = None, tentatives_json: int = 2, contexte: dict | None = None) -> dict:
    """Synthèse de la période. Ne lève jamais : statut ok (texte du modèle) ou indisponible (phrases Python)."""
    per = periode(type_, jour)
    precedentes = int(existant.get("tentatives", 0)) if (existant or {}).get("periode") == per else 0
    faits = {d: faits_devise(dossiers, d) for d in DEVISES}
    contexte = contexte or {}
    sortie = {"type": type_, "periode": per, "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "donnees_du": (dossiers or {}).get("genere_le"), "mention": MENTION, "contexte": contexte,
              "synthese": {"phrase_python": synthese_python(faits, contexte), "texte": None},
              "devises": {d: {"faits": f, "phrase_python": phrase_python(f), "texte": None} for d, f in faits.items()},
              "statut": "indisponible", "tentatives": precedentes + 1, "controles": []}
    if llm is None:
        sortie["raison"] = "fournisseur LLM indisponible"
        return sortie
    autorises = _valeurs(faits, set()) | _valeurs(contexte, set())
    definir_etiquette(f"consequences:{type_}")   # passe par la réserve : refusé tant que les engrenages manquent
    derniere = None
    for _ in range(max(1, tentatives_json)):
        try:
            brut = extraire_json(llm.appeler_llm(_prompt(type_, per, faits, contexte)))
            textes = (brut or {}).get("devises") if isinstance(brut, dict) else None
            if not isinstance(textes, dict):
                raise ValueError("réponse sans « devises »")
            gardes = 0
            for d in DEVISES:
                t, ordres = _retirer_ordres(str(textes.get(d) or "")[:600])
                t, retirees = verifier_chiffres(t, autorises)
                if ordres or retirees:
                    sortie["controles"].append(f"{d} : {ordres + retirees} {'phrase retirée' if ordres + retirees < 2 else 'phrases retirées'} (ordre ou chiffre absent des faits)")
                rejet = controler_texte(t, faits[d]["lignes"])
                if rejet:
                    sortie["controles"].append(f"{d} : texte rejeté ({rejet}) : phrase Python publiée")
                    t = ""
                if t:
                    sortie["devises"][d]["texte"] = t
                    gardes += 1
            g, ordres = _retirer_ordres(str(brut.get("synthese") or "")[:900])
            g, retirees = verifier_chiffres(g, autorises)
            rejet = controler_texte(g, [x for f in faits.values() for x in f["lignes"]]) if g else None
            if rejet:
                sortie["controles"].append(f"synthèse : texte rejeté ({rejet}) : phrase Python publiée")
            elif g:
                sortie["synthese"]["texte"] = g
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
    contexte = {}
    try:   # chiffres de la semaine (historique 5 ans) et évènements de la semaine suivante (agenda.json)
        from core import historique_5ans
        contexte["chiffres_semaine"] = chiffres_semaine(historique_5ans.charger())
    except Exception as exc:  # noqa: BLE001
        contexte["raison_chiffres"] = f"historique indisponible ({exc})"[:150]
    try:
        contexte["semaine_suivante"] = semaine_suivante(json.loads((docs_data / "agenda.json").read_text(encoding="utf-8")), jour)
    except (OSError, ValueError) as exc:
        contexte["raison_semaine"] = f"agenda.json indisponible ({exc})"[:150]
    entree = generer(type_, dossiers, llm, existant, jour, int((config.get("llm") or {}).get("max_tentatives_json", 2)), contexte)
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
