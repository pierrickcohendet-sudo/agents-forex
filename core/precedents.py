"""Précédents historiques calculés en Python (dossier économiste, palier 3).

Pour un indicateur clé d'un engrenage : périodes passées où il était au même niveau qu'aujourd'hui
(± 1 écart-type de sa distribution sur 5 ans), puis ce qu'a fait la devise ensuite (variation de sa
force à 1, 3 et 6 mois : médiane et nombre de cas). Les épisodes sont espacés d'au moins 4 semaines
(une même période n'est pas comptée plusieurs fois) et les 8 dernières semaines sont exclues (la
situation actuelle n'est pas son propre précédent). Une référence « tous épisodes confondus » est
donnée pour comparaison : un précédent n'est utile que s'il s'en écarte. Sous 5 cas : « précédents
insuffisants ». Le modèle raconte ces chiffres, il ne les calcule ni ne les modifie.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from core.dossiers import _hebdomadaire, _serie, difference, glissement_annuel

HORIZONS = {"1m": 30, "3m": 91, "6m": 182}
MINIMUM_CAS = 5
ESPACEMENT_JOURS = 28
EXCLUSION_RECENTE_JOURS = 56
INVERSES = {"JPY", "CHF", "CAD", "CNY"}   # cotés en devise pour 1 USD : force = 1 / taux

# engrenage -> [(libellé de l'indicateur, construction de la série, devise suivie)]
DEFINITIONS = {
    "2": [("Écart de taux 2 ans EUR − US (pb)", ("diff", "EUR_2a", "USD_2a"), "EUR"),
          ("Écart de taux 2 ans JPY − US (pb)", ("diff", "JPY_2a", "USD_2a"), "JPY"),
          ("Écart de taux 2 ans CAD − US (pb)", ("diff", "CAD_2a", "USD_2a"), "CAD")],
    "3": [("Inflation core US sur un an (%)", ("yoy", "USD_core_indice"), "USD")],
    "4": [("Rendement 10 ans US (%)", ("brute", "USD_10a"), "USD")],
    "5": [("VIX", ("brute", "vix"), "AUD"), ("VIX", ("brute", "vix"), "JPY")],
    "7": [("Variation sur 4 semaines de l'indice dollar large (%)", ("var4s", "dollar_large"), "USD")],
    "8": [("Pétrole WTI ($/baril)", ("brute", "wti"), "CAD")],
}
SANS_PRECEDENT = {"1": "le thème est la synthèse des autres engrenages : pas d'indicateur unique à comparer",
                  "6": "pas de série chiffrée de la géopolitique"}


def _indicateur(historiques: dict, construction: tuple) -> list[tuple[str, float]]:
    genre = construction[0]
    if genre == "brute":
        return _hebdomadaire(_serie(historiques, construction[1]))
    if genre == "diff":
        return _hebdomadaire(difference(_serie(historiques, construction[1]), _serie(historiques, construction[2])))
    if genre == "yoy":
        return glissement_annuel(_serie(historiques, construction[1]))
    if genre == "var4s":
        hebdo = _hebdomadaire(_serie(historiques, construction[1]))
        return [(d, round((v / hebdo[i - 4][1] - 1) * 100, 2)) for i, (d, v) in enumerate(hebdo) if i >= 4 and hebdo[i - 4][1]]
    return []


def _force(historiques: dict, devise: str) -> list[tuple[str, float]]:
    """Force de la devise : indice dollar large pour l'USD, taux de change orienté sinon."""
    if devise == "USD":
        return _serie(historiques, "dollar_large")
    points = _serie(historiques, f"FX_{devise}")
    return [(d, 1 / v) for d, v in points if v] if devise in INVERSES else points


def _valeur_a(points: list[tuple[str, float]], jour: str) -> float | None:
    v = None
    for d, x in points:
        if d > jour:
            break
        v = x
    return v


def _rendements(force: list[tuple[str, float]], dates: list[str], jours: int) -> list[float]:
    fin = force[-1][0] if force else ""
    sortie = []
    for d in dates:
        cible = (date.fromisoformat(d) + timedelta(days=jours)).isoformat()
        if cible > fin:
            continue   # horizon pas encore écoulé : cas non comptable
        v0, v1 = _valeur_a(force, d), _valeur_a(force, cible)
        if v0 and v1:
            sortie.append((v1 / v0 - 1) * 100)
    return sortie


def _espacer(dates: list[str]) -> list[str]:
    retenues = []
    for d in dates:
        if not retenues or (date.fromisoformat(d) - date.fromisoformat(retenues[-1])).days >= ESPACEMENT_JOURS:
            retenues.append(d)
    return retenues


def calculer(historiques: dict, libelle: str, construction: tuple, devise: str) -> dict:
    serie = _indicateur(historiques, construction)
    force = _force(historiques, devise)
    base = {"indicateur": libelle, "devise": devise, "minimum_cas": MINIMUM_CAS,
            "source": "calcul Python : séries des dossiers (FRED, Bundesbank, MoF Japon, BoC) et taux de change Fed H.10 / indice dollar large"}
    if len(serie) < 30 or len(force) < 30:
        return {**base, "suffisant": False, "texte": "Précédents insuffisants : historique trop court."}
    d0, x0 = serie[-1]
    sigma = statistics.pstdev([v for _, v in serie])
    limite = (date.fromisoformat(d0) - timedelta(days=EXCLUSION_RECENTE_JOURS)).isoformat()
    passes = [d for d, v in serie if d <= limite]
    proches = _espacer([d for d, v in serie if d <= limite and abs(v - x0) <= sigma])
    tous = _espacer(passes)
    cas, reference = {}, {}
    for h, jours in HORIZONS.items():
        r = _rendements(force, proches, jours)
        cas[h] = {"n": len(r), "mediane_pct": round(statistics.median(r), 2) if r else None,
                  "hausses": sum(1 for x in r if x > 0)}
        r0 = _rendements(force, tous, jours)
        reference[h] = {"n": len(r0), "mediane_pct": round(statistics.median(r0), 2) if r0 else None}
    suffisant = cas["1m"]["n"] >= MINIMUM_CAS
    sortie = {**base, "valeur_actuelle": round(x0, 2), "date": d0, "ecart_type": round(sigma, 2),
              "fenetre": [round(x0 - sigma, 2), round(x0 + sigma, 2)], "cas": cas, "reference_tous_episodes": reference,
              "suffisant": suffisant}
    if not suffisant:
        sortie["texte"] = f"Précédents insuffisants ({cas['1m']['n']} cas comparables, minimum {MINIMUM_CAS})."
    else:
        h, fr = cas, (lambda v, dec=2: f"{v:+.{dec}f}".replace(".", ","))
        bornes = f"{sortie['fenetre'][0]:.2f} et {sortie['fenetre'][1]:.2f}".replace(".", ",")
        morceaux = [f"{devise} médiane {fr(h['1m']['mediane_pct'])} % à 1 mois ({h['1m']['n']} cas)"]
        for cle, lib in (("3m", "3 mois"), ("6m", "6 mois")):
            if h[cle]["mediane_pct"] is not None:
                morceaux.append(f"{fr(h[cle]['mediane_pct'])} % à {lib} ({h[cle]['n']} cas)")
        sortie["texte"] = (f"Depuis {serie[0][0][:4]}, {h['1m']['n']} épisodes où « {libelle} » était entre {bornes} "
                           f"(aujourd'hui {sortie['valeur_actuelle']:.2f}".replace(".", ",") + ") : "
                           + ", ".join(morceaux)
                           + f". Tous épisodes confondus : {fr(reference['1m']['mediane_pct'])} % à 1 mois.")
    return sortie


def pour_engrenage(historiques: dict, numero: str) -> list[dict]:
    if numero in SANS_PRECEDENT:
        return [{"indicateur": None, "suffisant": False, "texte": f"Précédents insuffisants : {SANS_PRECEDENT[numero]}."}]
    return [calculer(historiques, lib, construction, devise) for lib, construction, devise in DEFINITIONS.get(numero, [])]
