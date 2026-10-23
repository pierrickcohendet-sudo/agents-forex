"""Une seule valeur par indicateur (lot V5, étape 1) : source canonique, série heurtée, contrôle de cohérence.

Source canonique : l'historique quotidien collecté pour 5 ans (collecte_historiques, FRED / EIA / Twelve Data),
lu par les dossiers, la matrice d'impact, les tuiles et le simulateur. Les séries de marché de la collecte macro
(VIX, S&P 500, pétrole, taux US) en sont des doublons : `unifier` les remplace par la valeur canonique AVANT tout
calcul (scores, engrenages, rapport). Ainsi chaque brique publie la même valeur, la même date et la même source.

`publiees` relève les valeurs structurées publiées par chaque module ; `incoherences` signale tout indicateur
publié avec deux valeurs différentes à la même date (test de non-régression et contrôle qualité).
"""
from __future__ import annotations

from datetime import date

# clé de la collecte macro -> clé de l'historique canonique
SERIES_MACRO = {"vix": "vix", "sp500": "sp500", "petrole_wti": "wti", "petrole_brent": "brent",
                "rendement_10y": "USD_10a", "rendement_2y": "USD_2a", "taux_fed": "USD_taux_effectif"}
# graphique de marché (collecte macro) -> clé de l'historique canonique
GRAPHIQUES = {"vix": "vix", "wti": "wti", "brent": "brent", "dollar_large": "dollar_large"}
# nom publié -> clé canonique (les modules publient sous ce nom)
NOMS = {"vix": "vix", "sp500": "sp500", "wti": "wti", "brent": "brent", "dollar_large": "dollar_large",
        "indice_or": "indice_or", "USD_10a": "USD_10a", "USD_2a": "USD_2a"}
SEUIL_HEURT_PCT = 8.0


def _points(historiques: dict | None, cle: str) -> list[list]:
    return [[str(p[0])[:10], float(p[1])] for p in (((historiques or {}).get("series") or {}).get(cle) or {}).get("points") or []
            if p and p[1] is not None]


def derniere(historiques: dict | None, cle: str) -> dict | None:
    """{valeur, date, source} canonique, ou None si la série manque."""
    pts = _points(historiques, cle)
    if not pts:
        return None
    return {"valeur": pts[-1][1], "date": pts[-1][0], "source": ((historiques.get("series") or {}).get(cle) or {}).get("source")}


def unifier(macro: dict, historiques: dict | None) -> list[str]:
    """Remplace dans `macro` les doublons de marché par la valeur canonique de l'historique. -> changements."""
    changes = []
    series = macro.setdefault("series", {})
    for cle_macro, cle in SERIES_MACRO.items():
        pts = _points(historiques, cle)
        if not pts:
            continue
        ancien = series.get(cle_macro) or {}
        nouveau = {**ancien, "valeur": pts[-1][1], "date": pts[-1][0],
                   "source": ((historiques["series"].get(cle) or {}).get("source")) or ancien.get("source"),
                   "source_canonique": cle}
        if cle_macro == "sp500" and len(pts) >= 2 and pts[-2][1]:
            nouveau["variation_pct"] = round((pts[-1][1] / pts[-2][1] - 1) * 100, 2)
        if (ancien.get("valeur"), ancien.get("date")) != (nouveau["valeur"], nouveau["date"]):
            changes.append(f"{cle_macro} : {ancien.get('valeur')} ({ancien.get('date')}) -> {nouveau['valeur']} ({nouveau['date']})")
        series[cle_macro] = nouveau
    graphes = macro.setdefault("graphiques_marche", {})
    for cle_g, cle in GRAPHIQUES.items():
        pts = _points(historiques, cle)
        if len(pts) < 2:
            continue
        n = max(len((graphes.get(cle_g) or {}).get("dates") or []), 130)
        graphes[cle_g] = {**(graphes.get(cle_g) or {}), "dates": [p[0] for p in pts[-n:]], "valeurs": [p[1] for p in pts[-n:]],
                          "source_canonique": cle}
    return changes


def serie_heurtee(points: list, seuil_pct: float = SEUIL_HEURT_PCT, n: int = 10) -> str | None:
    """« +8,7 % le 15/10 » si une variation d'une séance dépasse le seuil sur les n derniers points (sinon None)."""
    pts = [p for p in points or [] if p and p[1] is not None]
    pires = []
    v = pts[-n - 1:]
    for i in range(1, len(v)):
        if v[i - 1][1]:
            pct = (v[i][1] / v[i - 1][1] - 1) * 100
            if abs(pct) >= seuil_pct:
                d = str(v[i][0])
                pires.append((abs(pct), f"{pct:+.1f} % le {d[8:10]}/{d[5:7]}".replace(".", ",")))
    return ", ".join(t for _, t in sorted(pires, reverse=True)[:2]) or None


TEXTE_NEUTRALISE = "au-delà du seuil mais neutralisé : série heurtée"


# ------------------------------------------------------------ contrôle de cohérence
def publiees(rapport: dict | None, dossiers: dict | None) -> list[dict]:
    """Valeurs structurées publiées, par module : [{indicateur, date, valeur, module}]."""
    sortie = []
    for e in (((rapport or {}).get("synthese_globale") or {}).get("engrenages") or {}).get("engrenages") or []:
        for x in e.get("donnees_calculees") or []:
            if x.get("indicateur") in NOMS and x.get("valeur") is not None:
                sortie.append({"indicateur": NOMS[x["indicateur"]], "date": x.get("date"), "valeur": float(x["valeur"]),
                               "module": f"engrenage {e.get('numero')} (rapport)"})
    for numero, e in ((dossiers or {}).get("engrenages") or {}).items():
        for inst in (e or {}).get("instruments") or []:
            c = inst.get("cellule") or {}
            if inst.get("id") in NOMS and c.get("valeur") is not None:
                sortie.append({"indicateur": NOMS[inst["id"]], "date": c.get("date"), "valeur": float(c["valeur"]),
                               "module": f"dossier {numero}"})
    for c in ((dossiers or {}).get("vue_ensemble") or {}).get("cartes") or []:
        ch = c.get("chiffre") or {}
        if ch.get("indicateur") in NOMS and ch.get("valeur") is not None:
            sortie.append({"indicateur": NOMS[ch["indicateur"]], "date": ch.get("date"), "valeur": float(ch["valeur"]),
                           "module": f"carte {c.get('numero')} (vue d'ensemble)"})
    for th in ((dossiers or {}).get("cockpit") or {}).get("thermometres") or []:
        if th.get("indicateur") in NOMS and th.get("valeur") is not None:
            sortie.append({"indicateur": NOMS[th["indicateur"]], "date": th.get("date"), "valeur": float(th["valeur"]),
                           "module": f"thermomètre {th.get('numero')}"})
    return sortie


def incoherences(valeurs: list[dict], tolerance: float = 1e-6) -> list[str]:
    """Deux valeurs différentes pour le même indicateur, OU deux dates différentes (une brique en retard)."""
    par: dict[str, list[dict]] = {}
    for v in valeurs:
        par.setdefault(v["indicateur"], []).append(v)
    sortie = []
    for ind, liste in par.items():
        dates = {v["date"] for v in liste}
        if len(dates) > 1:
            sortie.append(f"{ind} : dates différentes selon les modules — " +
                          ", ".join(f"{v['module']} {v['valeur']:g} ({v['date']})" for v in liste))
            continue
        ref = liste[0]["valeur"]
        if any(abs(v["valeur"] - ref) > tolerance * max(1.0, abs(ref)) for v in liste):
            sortie.append(f"{ind} ({liste[0]['date']}) : valeurs différentes — " +
                          ", ".join(f"{v['module']} {v['valeur']:g}" for v in liste))
    return sortie


def age_jours(jour: str | None, aujourdhui: date | None = None) -> int | None:
    try:
        return ((aujourdhui or date.today()) - date.fromisoformat(str(jour)[:10])).days
    except (TypeError, ValueError):
        return None
