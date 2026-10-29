"""Rapport du jour (niveau desk) : toutes les sections calculées en Python, sans LLM ni requête de plus.

Sections : point de marché (2), mécanismes et scénarios (3), synthèse exécutive (4), calendrier commenté (5), fiches des
banques centrales de la semaine (6), bilan de la semaine passée (7), watchlist classée des paires (8), technique
multi-unités (9, core/technique_niveaux.py), gestion du risque (10), plan d'action (11). Le modèle ne fait que
rédiger (agents/agent_rapport.py, 2 appels groupés au plus) ; chaque texte a sa phrase Python de repli.
Chaque chiffre porte sa source, sa date et son statut (confirmé / provisoire / révisé / estimation) ou « n/d » avec
la raison. Jamais une probabilité ni un ordre d'achat ou de vente.
Sortie : docs/data/rapport_jour.json ; archive data/archives/rapport_jour/AAAA-MM-JJ.json (historique des scénarios
sur 5 jours, « mises à jour depuis la veille »).
"""
from __future__ import annotations

import json
import logging
import math
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
MENTION_BIAIS = "Biais conditionnels, pas des signaux d'achat ou de vente."
MENTION_WATCHLIST = "Classe les opportunités à analyser, pas des ordres."
MAX_PAR_DEVISE = 2
MENTION = "Aide à la décision : faits datés et fréquences passées, jamais une prédiction certaine ni un ordre d'achat ou de vente."
OPS = {">": lambda a, b: a > b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}
POIDS_IMPACT = {"fort": 3, "moyen": 2, "faible": 1}
SECTIONS_COMPLETES = ["synthese", "point_marche", "lecture", "calendrier", "banques", "bilan", "watchlist", "technique",
                      "scenarios", "tableau_de_bord", "plan", "conclusion"]
SECTIONS_COURTES = ["point_marche", "depuis_veille", "evenements_jour", "scenarios", "plan"]
TITRES = {"synthese": "Synthèse exécutive", "point_marche": "Point de marché", "lecture": "Lecture institutionnelle",
          "calendrier": "Calendrier commenté", "banques": "Banques centrales de la semaine", "bilan": "Bilan de la semaine passée",
          "watchlist": "Watchlist des paires", "technique": "Technique multi-unités", "scenarios": "Scénarios de la semaine",
          "tableau_de_bord": "Tableau de bord", "plan": "Plan d'action du jour", "conclusion": "Conclusion",
          "depuis_veille": "Mises à jour depuis la veille", "evenements_jour": "Évènements du jour"}


# ------------------------------------------------------------------ séries et variables
def _points(historiques: dict | None, cle: str) -> list[tuple[str, float]]:
    return [(str(p[0])[:10], float(p[1])) for p in ((((historiques or {}).get("series") or {}).get(cle) or {}).get("points") or [])
            if p and p[1] is not None]


def _source(historiques: dict | None, cle: str) -> str | None:
    return ((((historiques or {}).get("series") or {}).get(cle)) or {}).get("source")


def variation(points: list[tuple[str, float]], seances: int, unite: str) -> float | None:
    """Dernier point contre celui d'il y a `seances` séances : pb (taux), % (prix) ou points."""
    if len(points) <= seances:
        return None
    a, b = points[-1 - seances][1], points[-1][1]
    if unite == "pb":
        return round((b - a) * 100, 1)
    if unite == "%":
        return round((b / a - 1) * 100, 2) if a else None
    return round(b - a, 2)


def _v(valeur, unite, date_, source, statut="confirmé", raison=None) -> dict:
    return {"valeur": valeur, "unite": unite, "date": date_, "source": source, "statut": statut if valeur is not None else None,
            "raison": raison if valeur is None else None}


def _fr(x: float | None, d: int = 2, signe: bool = True) -> str:
    if x is None:
        return "n/d"
    t = f"{x:+.{d}f}" if signe else f"{x:.{d}f}"
    return t.replace(".", ",").replace("-", "−")


def texte_variable(nom: str, v: dict) -> str:
    u = {"pb": " pb", "%": " %", "pts": " pts"}.get(v.get("unite") or "", "")
    return f"{LIBELLES_VARIABLES.get(nom, nom)} {_fr(v.get('valeur'), 1 if v.get('unite') == 'pb' else 2)}{u}"


LIBELLES_VARIABLES = {
    "us2a_5j": "US 2 ans sur 5 séances", "us10a_5j": "US 10 ans sur 5 séances", "us30a_5j": "US 30 ans sur 5 séances",
    "reel_10a_5j": "taux réel 10 ans sur 5 séances", "point_mort_10a_5j": "point mort 10 ans sur 5 séances",
    "spread_hy_5j": "crédit high yield sur 5 séances", "vix": "VIX", "vix_5j": "VIX sur 5 séances", "brent_5j": "Brent sur 5 séances",
    "or_5j": "or sur 5 séances", "nasdaq_5j": "Nasdaq 100 (ETF QQQ) sur 5 séances", "sp500_5j": "S&P 500 sur 5 séances",
    "dollar_5j": "indice dollar (Fed, large) sur 5 séances", "ecart_2a_us_de": "écart 2 ans US − Allemagne",
    "ecart_2a_us_de_5j": "écart 2 ans US − Allemagne sur 5 séances", "oat_bund": "écart OAT − Bund (mensuel)",
    "surprise_cpi_us": "surprise de l'IPC US (publié − consensus)", "surprise_pce_us": "surprise du PCE sous-jacent US",
    "surprise_30j_usd": "indice de surprise US 30 jours"}


def _surprise_agenda(agenda_donnees: dict | None, devise: str, motif: str) -> dict:
    """Dernière publication de l'agenda (publié − consensus) pour l'évènement qui correspond au motif."""
    for j in reversed((agenda_donnees or {}).get("jours") or []):
        for e in reversed(j.get("evenements") or []):
            if e.get("devise") == devise and re.search(motif, e.get("evenement_en", ""), re.I) and e.get("publie") and e.get("consensus"):
                p, c = _num(e["publie"]), _num(e["consensus"])
                if p is not None and c is not None:
                    return _v(round(p - c, 2), "pts", e["date_paris"], f"{e['source']} ; consensus ForexFactory",
                              (e.get("statuts") or {}).get("publie") or "confirmé")
    return _v(None, "pts", None, None, raison="pas de publication avec consensus dans l'agenda des deux semaines")


def _num(texte) -> float | None:
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(texte or "").replace("−", "-"))
    return float(m.group().replace(",", ".")) if m else None


def variables(historiques: dict | None, rapport: dict | None, agenda_donnees: dict | None) -> dict[str, dict]:
    v: dict[str, dict] = {}
    defs = [("us2a_5j", "USD_2a", "pb"), ("us10a_5j", "USD_10a", "pb"), ("us30a_5j", "USD_30a", "pb"),
            ("reel_10a_5j", "USD_reel_10a", "pb"), ("point_mort_10a_5j", "USD_point_mort_10a", "pb"),
            ("spread_hy_5j", "USD_spread_hy", "pb"), ("vix_5j", "vix", "pts"), ("brent_5j", "brent", "%"),
            ("or_5j", "or_xau", "%"), ("nasdaq_5j", "nasdaq_qqq", "%"), ("sp500_5j", "sp500", "%"), ("dollar_5j", "dollar_large", "%")]
    for nom, cle, unite in defs:
        pts = _points(historiques, cle)
        v[nom] = _v(variation(pts, 5, unite), unite, pts[-1][0] if pts else None, _source(historiques, cle),
                    raison=f"série {cle} absente ou trop courte (prochain run)")
    vix = _points(historiques, "vix")
    v["vix"] = _v(vix[-1][1] if vix else None, "pts", vix[-1][0] if vix else None, _source(historiques, "vix"), raison="VIX absent")
    us2, de2 = dict(_points(historiques, "USD_2a")), dict(_points(historiques, "EUR_2a"))
    communs = sorted(set(us2) & set(de2))
    if communs:
        ecart = [(d, us2[d] - de2[d]) for d in communs]
        v["ecart_2a_us_de"] = _v(round(ecart[-1][1] * 100, 1), "pb", ecart[-1][0], "calcul Python : FRED (DGS2) − Bundesbank (2 ans)")
        v["ecart_2a_us_de_5j"] = _v(variation(ecart, 5, "pb"), "pb", ecart[-1][0], "calcul Python : FRED (DGS2) − Bundesbank (2 ans)")
    else:
        for n in ("ecart_2a_us_de", "ecart_2a_us_de_5j"):
            v[n] = _v(None, "pb", None, None, raison="2 ans US ou allemand absent")
    fr, de = _points(historiques, "FRA_10a_mensuel"), dict(_points(historiques, "DEU_10a_mensuel"))
    commun = [d for d, _ in fr if d in de]
    v["oat_bund"] = (_v(round((dict(fr)[commun[-1]] - de[commun[-1]]) * 100, 1), "pb", commun[-1],
                        "OCDE via FRED (IRLTLT01FRM156N − IRLTLT01DEM156N), mensuel") if commun else
                     _v(None, "pb", None, None, raison="OAT 10 ans mensuelle absente (série ajoutée, prochain run) ; pas de source quotidienne licite gratuite"))
    v["surprise_cpi_us"] = _surprise_agenda(agenda_donnees, "USD", r"^CPI m/m|^CPI y/y")
    v["surprise_pce_us"] = _surprise_agenda(agenda_donnees, "USD", r"Core PCE")
    s30 = ((((rapport or {}).get("tableau_macro") or {}).get("indice_surprise_30j") or {}).get("USD") or {})
    v["surprise_30j_usd"] = _v(s30.get("indice"), "écarts", ((rapport or {}).get("meta") or {}).get("date_rapport"),
                               "calcul Python (registre macro, 30 jours)", raison="indice de surprise absent du rapport")
    return v


def evaluer(conditions: list, vars_: dict) -> list[dict]:
    """Chaque condition [variable, opérateur, seuil, (libellé)] -> {remplie: True/False/None, texte, chiffre}."""
    sortie = []
    for c in conditions:
        nom, op, seuil = c[0], c[1], float(c[2])
        x = (vars_.get(nom) or {}).get("valeur")
        sortie.append({"variable": nom, "libelle": c[3] if len(c) > 3 else f"{LIBELLES_VARIABLES.get(nom, nom)} {op} {seuil:g}",
                       "remplie": None if x is None else OPS[op](x, seuil),
                       "chiffre": texte_variable(nom, vars_.get(nom) or {}) if x is not None else f"{LIBELLES_VARIABLES.get(nom, nom)} : n/d",
                       "raison": None if x is not None else (vars_.get(nom) or {}).get("raison"), "source": (vars_.get(nom) or {}).get("source"),
                       "date": (vars_.get(nom) or {}).get("date")})
    return sortie


# ------------------------------------------------------------------ 2. point de marché
ACTIFS = [  # (libellé, clé historique ou paire, unité de variation, catégorie)
    ("Indice dollar (Fed, large)", "dollar_large", "%", "dollar"), ("EUR/USD", "EUR/USD", "%", "fx"), ("GBP/USD", "GBP/USD", "%", "fx"),
    ("USD/JPY", "USD/JPY", "%", "fx"), ("AUD/USD", "AUD/USD", "%", "fx"), ("USD/CAD", "USD/CAD", "%", "fx"),
    ("USD/CHF", "USD/CHF", "%", "fx"), ("NZD/USD", "NZD/USD", "%", "fx"), ("US 2 ans", "USD_2a", "pb", "taux"),
    ("US 10 ans", "USD_10a", "pb", "taux"), ("US 30 ans", "USD_30a", "pb", "taux"), ("Taux réel US 10 ans", "USD_reel_10a", "pb", "taux"),
    ("Brent", "brent", "%", "petrole"), ("Or (XAU/USD)", "or_xau", "%", "or"), ("VIX", "vix", "pts", "vix"),
    ("S&P 500", "sp500", "%", "actions"), ("Nasdaq 100 (ETF QQQ)", "nasdaq_qqq", "%", "actions"), ("Japon (ETF EWJ)", "japon_ewj", "%", "actions")]
LECTURES_ACTIF = {
    ("dollar", 1): "dollar plus fort face à ses partenaires", ("dollar", -1): "dollar plus faible face à ses partenaires",
    ("taux", 1): "rendement en hausse : conditions plus strictes", ("taux", -1): "rendement en baisse : détente des taux",
    ("petrole", 1): "pétrole en hausse : risque d'inflation, soutien du CAD", ("petrole", -1): "pétrole en baisse : inflation importée moindre",
    ("or", 1): "or recherché (refuge ou dollar faible)", ("or", -1): "or délaissé",
    ("vix", 1): "volatilité en hausse : aversion au risque", ("vix", -1): "volatilité en baisse : appétit pour le risque",
    ("actions", 1): "actions en hausse : appétit pour le risque", ("actions", -1): "actions en baisse : prudence"}
SEUILS_SENS = {"%": 0.3, "pb": 3, "pts": 1}


def _lecture_fx(paire: str, sens: int) -> str:
    base, cot = paire.split("/")
    if sens == 0:
        return "peu de mouvement"
    forte = base if sens > 0 else cot
    return f"{forte} plus fort sur 5 séances"


def point_marche(historiques, h5, technique, seance: dict | None, config: dict, vars_: dict) -> dict:
    from core import paires as pm
    lignes = []
    cot = (seance or {}).get("cotations") or {}
    for libelle, cle, unite, cat in ACTIFS:
        if cat == "fx":
            pts = pm.serie_paire(h5, technique, cle) if h5 is not None else []
            source = "série unique 5 ans (Twelve Data raccordé à la Fed H.10)"
        else:
            pts = _points(historiques, cle)
            source = _source(historiques, cle)
        q = cot.get(cle) or {}
        niveau = q.get("prix") if q.get("prix") is not None else (pts[-1][1] if pts else None)
        heure = q.get("heure_utc") if q.get("prix") is not None else (pts[-1][0] if pts else None)
        v5 = variation(pts, 5, unite)
        v1 = q.get("variation_pct") if q.get("variation_pct") is not None and unite == "%" else variation(pts, 1, unite)
        sens = 0 if v5 is None or abs(v5) < SEUILS_SENS[unite] else (1 if v5 > 0 else -1)
        lecture = _lecture_fx(cle, sens) if cat == "fx" else (LECTURES_ACTIF.get((cat, sens)) or "peu de mouvement")
        lignes.append({"actif": libelle, "niveau": niveau, "variation_j1": v1, "variation_5j": v5, "unite": unite,
                       "heure": heure, "source": (q.get("source") + " ; " + source) if q.get("prix") is not None else source,
                       "statut": "provisoire" if q.get("prix") is not None and q.get("marche_ouvert") else ("confirmé" if niveau is not None else None),
                       "lecture": lecture if niveau is not None else None,
                       "raison": None if niveau is not None else "série absente (ajoutée au lot Rapport du jour : prochain run)"})
    globale = next((r["texte"] for r in (config.get("rapport") or {}).get("lectures_marche") or []
                    if all(c["remplie"] for c in evaluer(r["si"], vars_))), "mouvement sans signal d'ensemble net")
    return {"lignes": lignes, "lecture": globale,
            "note": "Niveau : cotation de séance (Twelve Data) quand elle existe, sinon dernière clôture. Variations J-1 et 5 séances. "
                    "Lecture choisie dans une table de règles Python."}


# ------------------------------------------------------------------ 3. mécanismes et scénarios
def mecanismes(config: dict, vars_: dict) -> list[dict]:
    sortie = []
    for m in (config.get("rapport") or {}).get("mecanismes") or []:
        conds = evaluer(m["si"], vars_)
        etat = "detecte" if all(c["remplie"] for c in conds) else ("nd" if any(c["remplie"] is None for c in conds) else "absent")
        sortie.append({"id": m["id"], "libelle": m["libelle"], "lecture": m["lecture"], "etat": etat, "conditions": conds})
    return sortie


def scenarios(config: dict, vars_: dict, historique: dict[str, dict] | None = None, aujourdhui: str | None = None) -> dict:
    liste = []
    for s in (config.get("rapport") or {}).get("scenarios") or []:
        conds = evaluer(s["conditions"], vars_)
        inval = evaluer(s.get("invalidations") or [], vars_)
        x, n = sum(1 for c in conds if c["remplie"]), len(conds)
        liste.append({"id": s["id"], "titre": s["titre"], "conditions": conds, "remplies": x, "total": n,
                      "nd": sum(1 for c in conds if c["remplie"] is None), "statut": f"{x} condition(s) sur {n} remplie(s)",
                      "invalide": any(c["remplie"] for c in inval), "invalidations": inval, "consequences": s.get("consequences") or {}})
    candidats = [s for s in liste if not s["invalide"] and s["remplies"] > 0]
    meilleur = max(candidats, key=lambda s: (s["remplies"] / s["total"], s["remplies"]), default=None)
    for s in liste:
        s["mieux_confirme"] = bool(meilleur and s["id"] == meilleur["id"])
    hist = dict(historique or {})
    if aujourdhui:
        hist[aujourdhui] = {s["id"]: [s["remplies"], s["total"]] for s in liste}
    jours = sorted(hist)[-5:]
    return {"liste": liste, "mieux_confirme": meilleur["id"] if meilleur else None,
            "texte_mieux_confirme": f"Le mieux confirmé à ce jour : « {meilleur['titre']} » ({meilleur['statut']})." if meilleur
            else "Aucun scénario n'a de condition remplie à ce jour.",
            "historique": {"jours": jours, "valeurs": {d: hist[d] for d in jours}},
            "note": "Statut compté en Python ; jamais une probabilité. Une invalidation remplie écarte le scénario."}


# ------------------------------------------------------------------ 4. synthèse exécutive
def _evts(agenda_donnees, debut: str, fin: str, impacts=("fort",)) -> list[dict]:
    return [e for j in (agenda_donnees or {}).get("jours") or [] for e in j.get("evenements") or []
            if debut <= e.get("date_paris", "") <= fin and e.get("impact") in impacts]


def bilans_matrice(dossiers_donnees: dict | None) -> dict[str, int]:
    sortie = {}
    for l in (((dossiers_donnees or {}).get("matrice_impact") or {}).get("lignes") or []):
        sortie[l["devise"]] = sum(int(c.get("valeur") or 0) for c in l.get("cases") or [])
    return sortie


def synthese(agenda_donnees, dossiers_donnees, scen: dict, aujourd: date) -> dict:
    debut, fin = aujourd.isoformat(), (aujourd + timedelta(days=7)).isoformat()
    forts = _evts(agenda_donnees, debut, fin)
    forts.sort(key=lambda e: (e.get("type") != "Réunion BC", e.get("iso_utc", "")))
    catalyseurs = [{k: e.get(k) for k in ("date_paris", "heure_paris", "devise", "evenement", "type", "consensus", "badge")} for e in forts[:8]]
    bilans = bilans_matrice(dossiers_donnees)
    meilleur = next((s for s in scen["liste"] if s["mieux_confirme"]), None)
    biais = []
    for d in DEVISES:
        n_evts = sum(2 if e.get("type") == "Réunion BC" else 1 for e in forts if e["devise"] == d)
        bilan = bilans.get(d)
        sens_scen = (meilleur or {}).get("consequences", {}).get(d, 0) if meilleur else 0
        statut = ("volatilité attendue" if n_evts >= 2 else "à surveiller" if (bilan is not None and abs(bilan) >= 2) or sens_scen else "neutre")
        if bilan is None:
            orient = "n/d"
        else:
            score = (1 if bilan >= 2 else -1 if bilan <= -2 else 0) + sens_scen
            orient = "soutien conditionnel" if score > 0 else "pression conditionnelle" if score < 0 else "neutre"
        condition = (f"si le scénario « {meilleur['titre']} » se confirme" if meilleur and sens_scen else
                     "selon les publications de la semaine" if n_evts else "sans catalyseur majeur cette semaine")
        biais.append({"devise": d, "biais": orient, "condition": condition, "bilan_matrice": bilan, "evenements_forts": n_evts,
                      "sensibilite_scenario": sens_scen, "statut": statut})
    phrase = (f"Catalyseurs : {', '.join(f'{c['devise']} {c['evenement']} ({c['date_paris'][8:10]}/{c['date_paris'][5:7]})' for c in catalyseurs[:4])}. "
              if catalyseurs else "Aucun catalyseur à fort impact dans les 7 jours. ") + scen["texte_mieux_confirme"]
    return {"catalyseurs": catalyseurs, "biais": biais, "mention": MENTION_BIAIS, "phrase_python": phrase, "texte": None}


# ------------------------------------------------------------------ 5. calendrier commenté
RISQUES_ENG = {2: "politique monétaire", 3: "données économiques", 4: "budget et taux longs", 8: "matières premières"}


def calendrier_commente(agenda_donnees, aujourd: date) -> dict:
    debut, fin = aujourd.isoformat(), (aujourd + timedelta(days=6)).isoformat()
    jours, creneaux = [], {}
    for j in (agenda_donnees or {}).get("jours") or []:
        if not debut <= j["date"] <= fin:
            continue
        evts = [e for e in j.get("evenements") or [] if e.get("impact") in ("fort", "moyen") or e.get("type") in ("Réunion BC", "Discours", "Conférence")]
        n_forts = sum(1 for e in evts if e.get("impact") == "fort")
        titre = "Journée critique" if n_forts >= 2 else "Journée chargée" if len(evts) >= 5 else "Journée calme" if not evts else "Journée ordinaire"
        devises = sorted({e["devise"] for e in evts if e.get("impact") == "fort"} or {e["devise"] for e in evts})
        risques = sorted({RISQUES_ENG.get(e.get("engrenage")) or ("banque centrale" if e.get("type") == "Réunion BC" else "discours")
                          for e in evts if e.get("impact") == "fort" or e.get("type") == "Réunion BC"} - {None})
        lecture = (f"Devises exposées : {', '.join(devises)} ; risque dominant : {', '.join(risques) or 'données secondaires'}." if evts
                   else "Pas d'évènement notable : liquidité normale attendue.")
        jours.append({"date": j["date"], "titre": titre, "n_forts": n_forts, "lecture": lecture,
                      "evenements": [{k: e.get(k) for k in ("heure_paris", "devise", "evenement", "impact", "type", "consensus", "badge")} for e in evts],
                      "discrets": j.get("discrets") or []})
        for e in evts:
            if e.get("heure_paris") in (None, "journée"):
                continue
            cle = (j["date"], e["heure_paris"][:2])
            c = creneaux.setdefault(cle, {"date": j["date"], "heure": f"{e['heure_paris'][:2]}:00", "score": 0, "evenements": []})
            c["score"] += POIDS_IMPACT.get(e.get("impact"), 1) * (1.5 if e.get("type") == "Réunion BC" else 1)
            c["evenements"].append(f"{e['devise']} {e['evenement']}")
    fenetres = sorted(creneaux.values(), key=lambda c: -c["score"])[:3]
    for f in fenetres:
        f["score"] = round(f["score"], 1)
    avert = []
    disc = [x for j in jours for x in j["discrets"]]
    if any("heure" in x.get("texte", "").lower() for x in disc):
        avert.append("Semaine de changement d'heure : les heures de Paris des publications américaines et européennes se décalent.")
    for j in jours:
        d = date.fromisoformat(j["date"])
        if (d + timedelta(days=1)).month != d.month or ((d + timedelta(days=3)).month != d.month and d.weekday() == 4):
            avert.append(f"Fin de mois le {d:%d/%m} : rééquilibrages de portefeuilles et fixing de 16 h à Londres.")
            break
    for x in disc:
        if "férié" in x.get("texte", "").lower() and set(x.get("devises") or []) & {"USD", "EUR", "GBP", "JPY"}:
            avert.append(f"Jour férié ({', '.join(x['devises'])}) le {x['date_paris'][8:10]}/{x['date_paris'][5:7]} : liquidité réduite.")
    return {"jours": jours, "fenetres": fenetres, "avertissements": avert,
            "methode": "Fenêtres : score par heure = impact (fort 3, moyen 2, faible 1) × 1,5 pour une décision de banque centrale, additionné."}


# ------------------------------------------------------------------ 6. banques centrales de la semaine
SERIE_2A = {"USD": "USD_2a", "EUR": "EUR_2a", "JPY": "JPY_2a", "CAD": "CAD_2a"}


def _registre(registre, indicateur, devise) -> dict:
    from core import registre_macro as rm
    return (((registre or {}).get("cases") or {}).get(rm.cle(indicateur, devise)) or {})


def banques_semaine(agenda_donnees, registre, historiques, h5, technique, config: dict, aujourd: date,
                    communiques: dict | None = None, vars_: dict | None = None) -> list[dict]:
    from core import impact as impact_mod
    fin = (aujourd + timedelta(days=7)).isoformat()
    cfg = config.get("rapport") or {}
    sortie = []
    for b in (agenda_donnees or {}).get("banques_centrales") or []:
        if not b.get("prochaine") or not aujourd.isoformat() <= b["prochaine"] <= fin:
            continue
        d = b["devise"]
        serie = _points(historiques, SERIE_2A.get(d, ""))
        marche = None
        if serie and b.get("taux") is not None:
            sur4 = variation(serie, 20, "pb")
            marche = {"ecart_pb": round((serie[-1][1] - float(b["taux"])) * 100), "variation_4s_pb": sur4, "date": serie[-1][0],
                      "source": f"{_source(historiques, SERIE_2A[d])} − taux directeur", "libelle": "indication de marché",
                      "note": "Écart entre le rendement à 2 ans et le taux directeur : pas des contrats à terme, une indication."}
        cpi, cho = _registre(registre, "cpi", d).get("actuel") or {}, _registre(registre, "chomage", d)
        cpi_num = cpi.get("valeur_num")
        cible = (cfg.get("cibles_inflation") or {}).get(d)
        force = impact_mod.serie_devise(h5, d, technique).points if h5 is not None else []
        ctx = {"cpi_au_dessus_cible": (cpi_num - cible) if cpi_num is not None and cible is not None and "m/m" not in str(_registre(registre, "cpi", d).get("etiquette") or "") else None,
               "brent_5j": ((vars_ or {}).get("brent_5j") or {}).get("valeur"),
               "force_devise_5j": variation(force, 5, "%"),
               "chomage_variation": ((cho.get("actuel") or {}).get("valeur_num") - _num((cho.get("precedent") or {}).get("valeur")))
               if (cho.get("actuel") or {}).get("valeur_num") is not None and _num((cho.get("precedent") or {}).get("valeur")) is not None else None}
        themes = [t["texte"] for t in cfg.get("themes_a_surveiller") or []
                  if ctx.get(t["si"][0]) is not None and OPS[t["si"][1]](ctx[t["si"][0]], float(t["si"][2]))]
        com = (communiques or {}).get(d) or {}
        sortie.append({"devise": d, "banque": b["banque"], "court": b["court"], "date": b["prochaine"], "heure": b.get("heure_prochaine"),
                       "taux": b.get("taux_texte"), "type_taux": b.get("type_taux"), "consensus": b.get("consensus_prochaine"),
                       "badge": b.get("badge"), "marche": marche,
                       "raison_marche": None if marche else "rendement à 2 ans de cette devise non collecté (source refusée ou absente)",
                       "contexte": {"cpi": {"valeur": cpi.get("valeur"), "date": cpi.get("date_pub"), "source": cpi.get("source"),
                                            "cible": cible},
                                    "chomage": {"valeur": (cho.get("actuel") or {}).get("valeur"), "date": (cho.get("actuel") or {}).get("date_pub"),
                                                "source": (cho.get("actuel") or {}).get("source")}},
                       "a_surveiller": themes or ["aucun thème saillant dans les données"],
                       "communique": {k: com.get(k) for k in ("date", "titre", "url", "source", "ton", "citations", "raison")} if com else
                       {"raison": "communiqué archivé à la publication (sites officiels)"},
                       "reaction": com.get("reaction")})
    return sortie


# ------------------------------------------------------------------ 7. bilan de la semaine passée
def bilan_semaine(registre, config, h5, technique, historiques, agenda_donnees, dossiers_donnees, aujourd: date,
                  communiques: dict | None = None, textes: dict | None = None) -> dict:
    from core import controles_macro, impact as impact_mod, registre_macro as rm
    debut = (aujourd - timedelta(days=7)).isoformat()
    cfg_tm = config.get("tableau_macro") or {}
    plafond = float((cfg_tm.get("indice_surprise") or {}).get("plafond_surprise", 3))
    surprises = []
    for cle_case, case in ((registre or {}).get("cases") or {}).items():
        devise, indicateur = cle_case.split("|")[0], cle_case.split("|")[-1]
        cfg_ind = (cfg_tm.get("indicateurs") or {}).get(indicateur) or {}
        try:
            pts = controles_macro._surprises(case, cfg_ind, plafond)
        except Exception:  # noqa: BLE001
            continue
        for d, s in pts:
            if debut <= str(d)[:10] <= aujourd.isoformat():
                a = case.get("actuel") or {}
                surprises.append({"devise": devise, "indicateur": case.get("indicateur") or indicateur, "date": str(d)[:10],
                                  "surprise_ecarts": round(s, 2), "publie": a.get("valeur"), "consensus": a.get("consensus"),
                                  "source": a.get("source")})
    surprises.sort(key=lambda x: -abs(x["surprise_ecarts"]))
    forces = {}
    for d in DEVISES:
        pts = impact_mod.serie_devise(h5, d, technique).points if h5 is not None else []
        forces[d] = variation(pts, 5, "%")
    classees = sorted(((d, v) for d, v in forces.items() if v is not None), key=lambda x: -x[1])
    marches = []
    for lib, cle, unite in (("US 2 ans", "USD_2a", "pb"), ("US 10 ans", "USD_10a", "pb"), ("Brent", "brent", "%"),
                            ("Or (XAU/USD)", "or_xau", "%"), ("VIX", "vix", "pts")):
        pts = _points(historiques, cle)
        marches.append({"actif": lib, "variation_5j": variation(pts, 5, unite), "unite": unite, "date": pts[-1][0] if pts else None,
                        "source": _source(historiques, cle)})
    decisions = [{k: e.get(k) for k in ("date_paris", "devise", "evenement", "type", "publie", "consensus", "badge")}
                 for j in (agenda_donnees or {}).get("jours") or [] for e in j.get("evenements") or []
                 if debut <= e.get("date_paris", "") < aujourd.isoformat() and e.get("type") in ("Réunion BC", "Discours", "Conférence")
                 and (e.get("impact") in ("fort", "moyen") or e.get("type") == "Réunion BC")]
    from core import communiques as com_mod
    decisions_tons = []
    for d, c in (communiques or {}).items():
        if c.get("date") and debut <= c["date"] <= aujourd.isoformat() and c.get("fichier"):
            decisions_tons.append({"devise": d, "date": c["date"], "titre": c.get("titre"), "url": c.get("url"),
                                   "ton": ((textes or {}).get("communiques") or {}).get(d, {}).get("ton"),
                                   "citations": ((textes or {}).get("communiques") or {}).get(d, {}).get("citations"),
                                   "raison_ton": None if ((textes or {}).get("communiques") or {}).get(d, {}).get("ton") else
                                   ("pas de communiqué précédent archivé pour comparer" if not c.get("precedent") else
                                    "comparaison par le modèle indisponible aujourd'hui"),
                                   "reaction": com_mod.reaction(d, c["date"], h5, technique, historiques)})
    basculements = []
    fil = ((dossiers_donnees or {}).get("cockpit") or {}).get("fil") or {}
    for l in fil.get("lignes") or []:
        cel = [c for c in l.get("cellules") or [] if c.get("classe")][-6:]
        if len(cel) >= 2 and cel[-1]["classe"] != cel[0]["classe"]:
            basculements.append({"engrenage": l["numero"], "titre": l["titre"], "avant": cel[0]["libelle"], "apres": cel[-1]["libelle"],
                                 "depuis": cel[0]["date"]})
    return {"surprises": surprises[:5], "forces": [{"devise": d, "variation_5j": v} for d, v in classees],
            "plus_fortes": [d for d, _ in classees[:2]], "plus_faibles": [d for d, _ in classees[-2:]], "marches": marches,
            "decisions": decisions[:10], "communiques": decisions_tons, "basculements": basculements,
            "methode": "Surprises : (publié − consensus) en écarts habituels de l'indicateur (registre macro) ; forces : série unique 5 ans.",
            "phrase_python": (f"Devises les plus fortes sur 5 séances : {', '.join(f'{d} {_fr(v)} %' for d, v in classees[:2])} ; "
                              f"les plus faibles : {', '.join(f'{d} {_fr(v)} %' for d, v in classees[-2:])}." if classees else "Forces n/d.")
            + (f" Plus grosse surprise : {surprises[0]['devise']} {surprises[0]['indicateur']} ({_fr(surprises[0]['surprise_ecarts'])} écarts)." if surprises else ""),
            "texte": None}


# ------------------------------------------------------------------ 8. watchlist
def watchlist(paires_donnees: dict | None, agenda_donnees, historiques, scen: dict, config: dict, aujourd: date) -> dict:
    cfg = (config.get("rapport") or {}).get("watchlist") or {}
    poids = cfg.get("poids") or {}
    fin = (aujourd + timedelta(days=7)).isoformat()
    forts = _evts(agenda_donnees, aujourd.isoformat(), fin)
    vols = [((f.get("technique") or {}).get("volatilite_30j")) for f in ((paires_donnees or {}).get("fiches") or {}).values()]
    vols = [v for v in vols if v]
    vol_med = statistics.median(vols) if vols else None
    meilleur = next((s for s in scen["liste"] if s["mieux_confirme"]), None)
    lignes = []
    for p, f in ((paires_donnees or {}).get("fiches") or {}).items():
        base, cot = p.split("/")
        n_ev = sum(2 if e.get("type") == "Réunion BC" else 1 for e in forts if e["devise"] in (base, cot))
        sb, sc = _points(historiques, f"{base}_2a"), _points(historiques, f"{cot}_2a")
        diff = None
        if sb and sc:
            db, dc = dict(sb), dict(sc)
            com = sorted(set(db) & set(dc))
            if len(com) > 20:
                diff = abs(((db[com[-1]] - dc[com[-1]]) - (db[com[-21]] - dc[com[-21]])) * 100)
        solde = abs(((f.get("macro") or {}).get("decomposition") or {}).get("solde") or 0)
        vol = (f.get("technique") or {}).get("volatilite_30j")
        comp = {"evenements": min(n_ev, 4) * poids.get("evenements", 1),
                "differentiel": round(min((diff or 0) / 10, 3), 2) * poids.get("differentiel", 1),
                "solde": min(solde, 4) * poids.get("solde", 1),
                "volatilite": round(min(vol / vol_med, 3), 2) * poids.get("volatilite", 1) if vol and vol_med else 0}
        lignes.append({"paire": p, "score": round(sum(comp.values()), 2), "composantes": comp,
                       "differentiel_pb": round(diff, 1) if diff is not None else None,
                       "raison_differentiel": None if diff is not None else "rendement à 2 ans absent pour l'une des devises : composante à 0"})
    lignes.sort(key=lambda l: -l["score"])
    seuils = cfg.get("seuils_libelles") or {}
    # Diversité : au plus MAX_PAR_DEVISE paires d'une même devise dans le top 6 (sinon une semaine chargée pour une
    # devise remplit tout le classement de ses croisements)
    choisis, compte = [], {}
    for l in lignes:
        b, c = l["paire"].split("/")
        if compte.get(b, 0) < MAX_PAR_DEVISE and compte.get(c, 0) < MAX_PAR_DEVISE:
            choisis.append(l)
            compte[b], compte[c] = compte.get(b, 0) + 1, compte.get(c, 0) + 1
        if len(choisis) == 6:
            break
    top = []
    for l in choisis:
        base, cot = l["paire"].split("/")
        f = ((paires_donnees or {}).get("fiches") or {}).get(l["paire"]) or {}
        lib = ("Priorité élevée" if l["score"] >= seuils.get("priorite_elevee", 6) else
               "À confirmer" if l["score"] >= seuils.get("a_confirmer", 4) else "Confirmation inter-marchés")
        conseq = (meilleur or {}).get("consequences") or {}
        sens_scen = conseq.get(base, 0) - conseq.get(cot, 0)
        dec = ((f.get("macro") or {}).get("decomposition") or {})
        ev_paire = [e for e in forts if e["devise"] in (base, cot)][:3]
        haussier = [f"le solde des engrenages reste favorable à {base} ({_fr(dec.get('solde'), 0)})" if (dec.get("solde") or 0) > 0 else
                    f"le solde des engrenages ({_fr(dec.get('solde'), 0)}) se retourne en faveur de {base}"]
        baissier = [f"le solde des engrenages reste favorable à {cot} ({_fr(dec.get('solde'), 0)})" if (dec.get("solde") or 0) < 0 else
                    f"le solde des engrenages ({_fr(dec.get('solde'), 0)}) se retourne en faveur de {cot}"]
        if meilleur and sens_scen:
            (haussier if sens_scen > 0 else baissier).append(f"le scénario « {meilleur['titre']} » se confirme")
        for e in ev_paire:
            cible = haussier if e["devise"] == base else baissier
            cible.append(f"{e['devise']} {e['evenement']} ({e['date_paris'][8:10]}/{e['date_paris'][5:7]}) au-dessus du consensus"
                         if e.get("type") != "Réunion BC" else f"{e['devise']} : décision ({e['date_paris'][8:10]}/{e['date_paris'][5:7]}) plus restrictive qu'attendu")
        top.append({**l, "libelle": lib,
                    "scenario_haussier": {"conditions": haussier, "texte": None}, "scenario_baissier": {"conditions": baissier, "texte": None},
                    "confirmations": f"écart de taux à 2 ans {base} − {cot} ; " + ((cfg.get("confirmations") or {}).get(cot if cot != "USD" else base) or "indices liés"),
                    "risque": (cfg.get("risques") or {}).get(cot if cot in ("JPY", "NZD", "CHF", "CNY") else base) or (cfg.get("risques") or {}).get(cot)})
    return {"classement": lignes, "top": top, "mention": MENTION_WATCHLIST,
            "methode": "Score = évènements forts des deux devises (décision de banque centrale ×2, plafond 4) + variation sur 4 semaines "
                       "de l'écart de taux à 2 ans (pb / 10, plafond 3) + |solde des engrenages| (plafond 4) + volatilité 30 j / médiane (plafond 3). "
                       f"Top 6 : au plus {MAX_PAR_DEVISE} paires par devise."}


# ------------------------------------------------------------------ 10. gestion du risque
def pip(paire: str) -> float:
    return 0.01 if "JPY" in paire else 0.0001


def risque(paires_donnees, seance, h5, technique, agenda_donnees, notes_mes_paires: list[str], aujourd: date) -> dict:
    from core import paires as pm
    cot = (seance or {}).get("cotations") or {}
    prix = {}
    for p, f in ((paires_donnees or {}).get("fiches") or {}).items():
        q = (cot.get(p) or {}).get("prix")
        prix[p] = q if q is not None else (f.get("technique") or {}).get("cours")
    usd = {"USD": 1.0}
    for p, v in prix.items():   # valeur en USD d'une unité de chaque devise
        if not v:
            continue
        b, c = p.split("/")
        if c == "USD":
            usd[b] = v
        elif b == "USD":
            usd[c] = 1 / v
    valeurs_pip = {}
    for p, v in prix.items():
        b, c = p.split("/")
        if v and c in usd:
            valeurs_pip[p] = {"prix": v, "pip": pip(p), "valeur_pip_usd_lot": round(100000 * pip(p) * usd[c], 2)}
    series = {p: pm.serie_paire(h5, technique, p) for p in notes_mes_paires} if h5 is not None else {}
    rend = {}
    for p, pts in series.items():
        r = [math.log(pts[i][1] / pts[i - 1][1]) for i in range(max(1, len(pts) - 30), len(pts)) if pts[i - 1][1]]
        rend[p] = r
    corr = {}
    for a in rend:
        for b in rend:
            if a < b and len(rend[a]) == len(rend[b]) and len(rend[a]) > 10:
                try:
                    corr[f"{a}|{b}"] = round(statistics.correlation(rend[a], rend[b]), 2)
                except statistics.StatisticsError:
                    pass
    eviter = []
    for e in _evts(agenda_donnees, aujourd.isoformat(), aujourd.isoformat()):
        if e.get("heure_paris") not in (None, "journée"):
            h = datetime.strptime(e["heure_paris"], "%H:%M")
            eviter.append({"debut": (h - timedelta(minutes=15)).strftime("%H:%M"), "fin": (h + timedelta(minutes=15)).strftime("%H:%M"),
                           "devise": e["devise"], "evenement": e["evenement"]})
    return {"valeurs_pip": valeurs_pip, "devises_usd": {k: round(v, 6) for k, v in usd.items()}, "correlations_30j": corr,
            "seuil_correlation": 0.7, "publications_a_eviter": eviter,
            "note": "Calculateur : calcul local dans le navigateur, sur les cours du jour. Un outil, pas un conseil."}


# ------------------------------------------------------------------ 11. plan d'action
def plan(config: dict, agenda_donnees, cockpit: dict | None, scen: dict, aujourd: date) -> dict:
    cfg = (config.get("rapport") or {}).get("plan") or {}
    du_jour = sorted(_evts(agenda_donnees, aujourd.isoformat(), aujourd.isoformat(), ("fort", "moyen")), key=lambda e: e.get("iso_utc", ""))
    forts = [e for e in du_jour if e["impact"] == "fort"]
    bord = (cockpit or {}).get("au_bord") or []
    meilleur = next((s for s in scen["liste"] if s["mieux_confirme"]), None)
    avant = list(cfg.get("avant") or []) + [f"{e['heure_paris']} {e['devise']} {e['evenement']}" for e in forts[:4]]
    fenetres = list(dict.fromkeys(f"Fenêtre {e['heure_paris']} ± 15 min ({e['devise']})" for e in forts))
    pendant = list(cfg.get("pendant") or []) + fenetres[:3]
    cloture = list(cfg.get("cloture") or []) + [f"Seuil proche : {s.get('libelle')} à {s.get('distance_texte')} du seuil" for s in bord[:2]]
    if meilleur:
        cloture.append(f"Scénario à surveiller : « {meilleur['titre']} » ({meilleur['statut']})")
    return {"avant": avant, "pendant": pendant, "cloture": cloture, "texte": None,
            "note": "Éléments fixes (config.yaml) et éléments du jour (agenda, radar, scénarios) choisis en Python."}


# ------------------------------------------------------------------ assemblage
def _lire(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def depuis_veille(actuel: dict, veille: dict | None) -> list[str]:
    if not veille:
        return ["Pas de rapport archivé la veille : comparaison n/d."]
    lignes = []
    av = {s["id"]: s for s in ((veille.get("scenarios") or {}).get("liste") or [])}
    for s in (actuel.get("scenarios") or {}).get("liste") or []:
        p = av.get(s["id"])
        if p and (p["remplies"], p["total"]) != (s["remplies"], s["total"]):
            lignes.append(f"Scénario « {s['titre']} » : {p['remplies']}/{p['total']} → {s['remplies']}/{s['total']} conditions.")
    m0 = {m["id"] for m in ((veille.get("lecture") or {}).get("mecanismes") or []) if m["etat"] == "detecte"}
    m1 = {m["id"]: m for m in ((actuel.get("lecture") or {}).get("mecanismes") or []) if m["etat"] == "detecte"}
    lignes += [f"Nouveau mécanisme : {m['libelle']}." for i, m in m1.items() if i not in m0]
    lignes += [f"Mécanisme disparu : {i.replace('_', ' ')}." for i in m0 - set(m1)]
    if (veille.get("theme") or {}).get("titre") != (actuel.get("theme") or {}).get("titre"):
        lignes.append(f"Thème : « {(veille.get('theme') or {}).get('titre')} » → « {(actuel.get('theme') or {}).get('titre')} ».")
    return lignes or ["Pas de changement de scénario, de mécanisme ni de thème depuis la veille."]


def calculer(racine: str | Path, config: dict, maintenant: datetime | None = None) -> dict:
    from core import historique_5ans, registre_macro, technique_niveaux
    racine = Path(racine)
    maintenant = maintenant or datetime.now(timezone.utc)
    aujourd = maintenant.date()
    docs = racine / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
    cache = racine / "data" / "cache"
    historiques = ((_lire(cache / "collecte_historiques.json") or {}).get("donnees")) or {}
    technique = ((_lire(cache / "collecte_technique.json") or {}).get("donnees")) or {}
    h5 = historique_5ans.charger()
    rapport = _lire(docs / "latest.json") or {}
    agenda_donnees = _lire(docs / "agenda.json") or {}
    dossiers_donnees = _lire(docs / "dossiers.json") or {}
    paires_donnees = _lire(docs / "paires.json") or {}
    seance = _lire(docs / "seance.json") or {}
    registre = registre_macro.charger(racine / "data" / "registre_macro.json")
    archives = racine / "data" / "archives" / "rapport_jour"
    hist_scen = (_lire(racine / "data" / "archives" / "scenarios.json") or {}).get("jours") or {}
    communiques = (_lire(racine / "data" / "communiques" / "index.json") or {}).get("par_devise") or {}

    vars_ = variables(historiques, rapport, agenda_donnees)
    scen = scenarios(config, vars_, hist_scen, aujourd.isoformat())
    meca = mecanismes(config, vars_)
    cockpit = (dossiers_donnees.get("cockpit") or {})
    mes = paires_donnees.get("mes_paires") or []
    technique_mes = {}
    for p in mes:
        f = (paires_donnees.get("fiches") or {}).get(p) or {}
        from core import paires as pm
        technique_mes[p] = technique_niveaux.calculer(f.get("chandeliers"), pm.serie_paire(h5, technique, p))
    sortie = {
        "genere_le": maintenant.isoformat(timespec="seconds"), "date": aujourd.isoformat(),
        "version": "complète" if aujourd.weekday() == 0 else "courte",
        "date_rapport": (rapport.get("meta") or {}).get("date_rapport"),
        "theme": {k: (cockpit.get("entete") or {}).get(k) for k in ("titre", "direction", "conviction", "texte")},
        "point_marche": point_marche(historiques, h5, technique, seance, config, vars_),
        "lecture": {"mecanismes": meca, "detectes": [m for m in meca if m["etat"] == "detecte"]},
        "scenarios": scen,
        "synthese": synthese(agenda_donnees, dossiers_donnees, scen, aujourd),
        "calendrier": calendrier_commente(agenda_donnees, aujourd),
        "banques": banques_semaine(agenda_donnees, registre, historiques, h5, technique, config, aujourd, communiques, vars_),
        "interpretation": (config.get("rapport") or {}).get("interpretation") or [],
        "bilan": bilan_semaine(registre, config, h5, technique, historiques, agenda_donnees, dossiers_donnees, aujourd, communiques),
        "watchlist": watchlist(paires_donnees, agenda_donnees, historiques, scen, config, aujourd),
        "technique": {"paires": technique_mes, "definitions": technique_niveaux.DEFINITIONS, "mention": technique_niveaux.MENTION},
        "risque": risque(paires_donnees, seance, h5, technique, agenda_donnees, mes, aujourd),
        "tableau_de_bord": {"au_bord": cockpit.get("au_bord") or [], "franchis": len(cockpit.get("franchis") or []),
                            "thermometres": [{k: t.get(k) for k in ("numero", "titre", "texte_valeur", "etat", "direction")}
                                             for t in cockpit.get("thermometres") or []]},
        "plan": plan(config, agenda_donnees, cockpit, scen, aujourd),
        "variables": vars_, "mention": MENTION,
    }
    sortie["evenements_jour"] = [e for e in _evts(agenda_donnees, aujourd.isoformat(), aujourd.isoformat(), ("fort", "moyen", "faible"))
                                 if e.get("impact") != "faible" or e.get("type") in ("Réunion BC", "Discours")]
    veille = None
    for k in range(1, 5):   # dernier rapport archivé avant aujourd'hui (week-end compris)
        veille = _lire(archives / f"{(aujourd - timedelta(days=k)).isoformat()}.json")
        if veille:
            break
    sortie["depuis_veille"] = depuis_veille(sortie, veille)
    sortie["conclusion"] = {"phrase_python": f"{sortie['scenarios']['texte_mieux_confirme']} {sortie['point_marche']['lecture'].capitalize()}. "
                                             f"{MENTION_BIAIS}", "texte": None}
    sortie["sections"] = SECTIONS_COMPLETES if sortie["version"] == "complète" else SECTIONS_COURTES
    sortie["titres"] = TITRES
    return sortie


def ecrire(racine: str | Path, config: dict, maintenant: datetime | None = None, textes: dict | None = None) -> dict | None:
    """Calcule et écrit rapport_jour.json, l'archive du jour et l'historique des scénarios. `textes` : textes du modèle
    déjà validés (agents/agent_rapport.py) ; sinon ceux du rapport du jour déjà écrit sont repris."""
    try:
        racine = Path(racine)
        donnees = calculer(racine, config, maintenant)
        docs = racine / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
        ancien = _lire(docs / "rapport_jour.json") or {}
        textes = textes or (ancien.get("textes") if ancien.get("date") == donnees["date"] else None) or {}
        appliquer_textes(donnees, textes)
        (docs / "rapport_jour.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        arch = racine / "data" / "archives" / "rapport_jour"
        arch.mkdir(parents=True, exist_ok=True)
        leger = {k: donnees[k] for k in ("date", "theme", "scenarios", "lecture", "synthese")}
        (arch / f"{donnees['date']}.json").write_text(json.dumps(leger, ensure_ascii=False), encoding="utf-8")
        for vieux in sorted(arch.glob("*.json"))[:-30]:   # 30 jours d'archive
            vieux.unlink()
        chemin_s = racine / "data" / "archives" / "scenarios.json"
        hs = (_lire(chemin_s) or {}).get("jours") or {}
        hs[donnees["date"]] = {s["id"]: [s["remplies"], s["total"]] for s in donnees["scenarios"]["liste"]}
        chemin_s.write_text(json.dumps({"jours": {d: hs[d] for d in sorted(hs)[-30:]}}, ensure_ascii=False), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.exception("rapport_jour.json non écrit : %s", exc)
        return None


def appliquer_textes(donnees: dict, textes: dict) -> None:
    """Place les textes validés du modèle ; chaque section garde sa phrase Python de repli."""
    donnees["textes"] = textes or {}
    t = textes or {}
    for cle in ("synthese", "bilan", "conclusion"):
        if t.get(cle):
            donnees[cle]["texte"] = t[cle]
    if t.get("lecture_marche"):
        donnees["point_marche"]["lecture_modele"] = t["lecture_marche"]
    if t.get("plan"):
        donnees["plan"]["texte"] = t["plan"]
    for w in donnees["watchlist"]["top"]:
        tp = (t.get("watchlist") or {}).get(w["paire"]) or {}
        if tp.get("haussier"):
            w["scenario_haussier"]["texte"] = tp["haussier"]
        if tp.get("baissier"):
            w["scenario_baissier"]["texte"] = tp["baissier"]
    for b in donnees["banques"]:
        tb = (t.get("communiques") or {}).get(b["devise"]) or {}
        if tb.get("ton"):
            b["communique"]["ton"], b["communique"]["citations"] = tb["ton"], tb.get("citations")
    for c in donnees["bilan"].get("communiques") or []:
        tb = (t.get("communiques") or {}).get(c["devise"]) or {}
        if tb.get("ton"):
            c.update(ton=tb["ton"], citations=tb.get("citations"), raison_ton=None)
    donnees["redige_par"] = t.get("redige_par")
