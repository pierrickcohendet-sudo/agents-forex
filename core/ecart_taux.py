"""Écart de taux entre les deux pays d'une paire (lot V8.2, carte « Écart de taux » de la page Paire).

1. Cache data/cache/historique_taux.json : rendements 2 ans et 10 ans quotidiens sur 1 an (13 mois gardés), complété
   chaque jour à partir de la collecte des historiques (mêmes sources que core/marche_taux.py, une requête par source
   et par jour : FRED pour l'USD, Bundesbank pour l'EUR, ministère des Finances pour le JPY, Banque du Canada pour le
   CAD, Banque d'Angleterre pour le GBP 10 ans). CHF, AUD et NZD : 10 ans MENSUEL de l'OCDE via FRED, étiqueté
   « mensuel ». CNY : n/d. Pas de 2 ans pour GBP, CHF, AUD et NZD (raison affichée, aucune source non licite).
2. Calculs (Python) pour chaque paire : écart base − cotation en pb, variations 1 semaine et 1 mois, corrélation sur
   60 séances des variations quotidiennes avec la paire, sensibilité (pips de la paire pour 10 pb d'écart, pente des
   moindres carrés), phrase de lecture. Rien n'est calculé dans le navigateur.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, timedelta
from pathlib import Path

from core.technique_avancee import taille_pip

log = logging.getLogger(__name__)

JOURS_GARDES = 400
SEANCES_CORR = 60
MIN_OBS_CORR = 30
MATURITES = ("2a", "10a")
LIB_MAT = {"2a": "2 ans", "10a": "10 ans"}
PAYS = {"USD": "américain", "EUR": "allemand (zone euro)", "GBP": "britannique", "JPY": "japonais", "CHF": "suisse",
        "CAD": "canadien", "AUD": "australien", "NZD": "néo-zélandais", "CNY": "chinois"}
CHEMIN = Path(__file__).resolve().parents[1] / "data" / "cache" / "historique_taux.json"


# ------------------------------------------------------------------ cache 1 an
def noms_series(config: dict) -> list[str]:
    sources = ((config.get("tableau_macro") or {}).get("taux_obligataires") or {}).get("sources") or {}
    return [f"{d}_{m}" for d, par in sources.items() for m, spec in (par or {}).items() if not (spec or {}).get("absent")]


def raisons_absence(config: dict) -> dict:
    sources = ((config.get("tableau_macro") or {}).get("taux_obligataires") or {}).get("sources") or {}
    return {f"{d}_{m}": spec["absent"] for d, par in sources.items() for m, spec in (par or {}).items() if (spec or {}).get("absent")}


def fusionner(ancien: dict, historiques: dict, noms: list[str], aujourdhui: date) -> dict:
    """Ajoute au cache les points du jour (bruts si disponibles, sinon compactés) ; garde 400 jours."""
    limite = (aujourdhui - timedelta(days=JOURS_GARDES)).isoformat()
    series = dict((ancien or {}).get("series") or {})
    bruts = (historiques or {}).get("taux_quotidiens") or {}
    compacts = (historiques or {}).get("series") or {}
    for nom in noms:
        neuf = bruts.get(nom) or compacts.get(nom)
        if not neuf or not neuf.get("points"):
            continue
        avant = series.get(nom) or {}
        pts = {d: v for d, v in avant.get("points") or []}
        pts.update({d: v for d, v in neuf["points"] if d >= limite and v is not None})
        series[nom] = {"source": neuf.get("source"), "frequence": neuf.get("frequence"),
                       "points": [[d, pts[d]] for d in sorted(pts) if d >= limite]}
    return {"maj": aujourdhui.isoformat(), "series": series}


def mettre_a_jour_cache(config: dict, historiques: dict, chemin: Path | None = None, aujourdhui: date | None = None) -> dict:
    chemin = Path(chemin or CHEMIN)
    try:
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ancien = {}
    cache = fusionner(ancien, historiques, noms_series(config), aujourdhui or date.today())
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except OSError as exc:
        log.warning("historique_taux.json non écrit : %s", exc)
    return cache


def charger(chemin: Path | None = None) -> dict:
    try:
        return json.loads(Path(chemin or CHEMIN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ calculs
def _valeur_au(points: list[list], jour: str):
    """Dernière observation à cette date ou avant (séries mensuelles : valeur du mois en cours de validité)."""
    v = None
    for d, x in points:
        if d <= jour:
            v = x
        else:
            break
    return v


def serie_ecart(pb: list[list], pc: list[list], mensuel_b: bool = False, mensuel_c: bool = False) -> list[list]:
    """Écart base − cotation (pb). Deux séries quotidiennes : dates communes. Une série mensuelle : aux dates de la
    série mensuelle, l'autre prise à sa dernière observation à cette date (jamais d'interpolation)."""
    if mensuel_b or mensuel_c:
        ref = pb if mensuel_b else pc
        sortie = []
        for d, _ in ref:
            a, b = _valeur_au(pb, d), _valeur_au(pc, d)
            if a is not None and b is not None:
                sortie.append([d, round((a - b) * 100, 1)])
        return sortie
    db, dc = dict(map(tuple, pb)), dict(map(tuple, pc))
    return [[d, round((db[d] - dc[d]) * 100, 1)] for d in sorted(set(db) & set(dc))]


def variation(serie: list[list], jours: int) -> float | None:
    if not serie:
        return None
    cible = (date.fromisoformat(serie[-1][0]) - timedelta(days=jours)).isoformat()
    avant = _valeur_au(serie, cible)
    return None if avant is None else round(serie[-1][1] - avant, 1)


def correlation(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx, syy = sum((a - mx) ** 2 for a in x), sum((b - my) ** 2 for b in y)
    return None if sxx == 0 or syy == 0 else round(sxy / math.sqrt(sxx * syy), 2)


def pente(x: list[float], y: list[float]) -> float | None:
    """Pente des moindres carrés de y sur x."""
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    return None if sxx == 0 else sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx


def lien(ecart: list[list], paire_pts: list[tuple[str, float]], paire: str) -> dict:
    """Corrélation (60 séances, variations quotidiennes) et sensibilité (pips pour 10 pb)."""
    px = dict(paire_pts)
    jours = [d for d, _ in ecart if d in px]
    ec = dict(map(tuple, ecart))
    jours = jours[-(SEANCES_CORR + 1):]
    if len(jours) < MIN_OBS_CORR + 1:
        return {"correlation": None, "sensibilite_pips_10pb": None, "observations": max(len(jours) - 1, 0),
                "raison": f"{max(len(jours) - 1, 0)} séances communes à l'écart et à la paire : il en faut {MIN_OBS_CORR} au moins"}
    dx = [ec[b] - ec[a] for a, b in zip(jours, jours[1:])]
    dy = [(px[b] - px[a]) / taille_pip(paire) for a, b in zip(jours, jours[1:])]
    s = pente(dx, dy)
    return {"correlation": correlation(dx, dy), "sensibilite_pips_10pb": None if s is None else round(s * 10, 1),
            "observations": len(dx), "du": jours[0], "au": jours[-1]}


def _fr(v, d=2, signe=True):
    if v is None:
        return "n/d"
    t = f"{v:+.{d}f}" if signe else f"{v:.{d}f}"
    return t.replace(".", ",").replace("-", "−")


def phrase(maturite: str, corr: float | None, sens_pips: float | None, raison: str | None = None) -> str:
    lib = LIB_MAT[maturite]
    if corr is None:
        return f"Lien entre la paire et l'écart {lib} non mesurable : {raison or 'données insuffisantes'}."
    if abs(corr) < 0.3:
        return f"La paire suit peu l'écart {lib} sur 60 séances (corrélation {_fr(corr)}) : lien faible, à ne pas surinterpréter."
    verbe = "suit" if corr > 0 else "évolue à l'inverse de"
    return (f"La paire {verbe} l'écart {lib} (corrélation {_fr(corr)}) : +10 pb d'écart ≈ "
            f"{_fr(sens_pips, 0)} pips en moyenne.")


def calculer_paire(paire: str, cache: dict, paire_pts: list[tuple[str, float]], absences: dict,
                   aujourdhui: date | None = None) -> dict:
    """Bloc « Écart de taux » d'une paire : pour chaque maturité, ce qui existe et la raison du reste."""
    base, cot = paire.split("/")
    series = (cache or {}).get("series") or {}
    debut = ((aujourdhui or date.today()) - timedelta(days=366)).isoformat()
    sortie = {"paire": paire, "maturites": {}, "defaut": None,
              "cloture_paire": [[d, round(v, 6)] for d, v in paire_pts if d >= debut],
              "source_paire": "croisé des séries uniques 5 ans (Twelve Data raccordé à la Fed H.10)"}
    for m in MATURITES:
        sb, sc = series.get(f"{base}_{m}"), series.get(f"{cot}_{m}")
        manque = [(d, s) for d, s in ((base, sb), (cot, sc)) if not s or not s.get("points")]
        if manque:
            d = manque[0][0]
            raison_src = absences.get(f"{d}_{m}") or ("aucune source gratuite exploitable" if d == "CNY" else "série non collectée")
            raison = f"pas de {LIB_MAT[m]} {PAYS.get(d, d)} gratuit ({raison_src})"
            sortie["maturites"][m] = {"disponible": False, "raison": raison}
            continue
        mb, mc = sb.get("frequence") == "mensuel", sc.get("frequence") == "mensuel"
        mensuel = mb or mc
        ec = [p for p in serie_ecart(sb["points"], sc["points"], mb, mc) if p[0] >= debut]
        if not ec:
            sortie["maturites"][m] = {"disponible": False, "raison": "aucune date commune aux deux séries"}
            continue
        bloc = {"disponible": True, "mensuel": mensuel, "ecart": ec, "actuel_pb": ec[-1][1], "date": ec[-1][0],
                "variation_1s_pb": None if mensuel else variation(ec, 7), "variation_1m_pb": variation(ec, 30),
                "sources": {base: sb.get("source"), cot: sc.get("source")},
                "frequence": "mensuel" if mensuel else "quotidien"}
        if mensuel:
            bloc.update({"correlation": None, "sensibilite_pips_10pb": None,
                         "raison_lien": "série mensuelle : corrélation des variations quotidiennes impossible",
                         "raison_1s": "série mensuelle"})
        else:
            l = lien(ec, paire_pts, paire)
            bloc.update({k: l.get(k) for k in ("correlation", "sensibilite_pips_10pb", "observations", "du", "au")})
            bloc["raison_lien"] = l.get("raison")
        bloc["phrase"] = phrase(m, bloc["correlation"], bloc["sensibilite_pips_10pb"], bloc.get("raison_lien"))
        sortie["maturites"][m] = bloc
    dispo = [m for m in MATURITES if sortie["maturites"][m].get("disponible")]
    sortie["defaut"] = dispo[0] if dispo else None
    if dispo and dispo[0] != "2a":
        sortie["note_defaut"] = f"{sortie['maturites']['2a']['raison']} : écart 10 ans utilisé"
    if not dispo:
        sortie["raison"] = sortie["maturites"]["2a"]["raison"] + " ; " + sortie["maturites"]["10a"]["raison"]
    return sortie
