"""Collecte macro via l'API FRED (séries US + baromètres globaux).

Fournit valeur actuelle + précédente + date pour chaque série (la lecture
"vs attentes" utilise les prévisions du calendrier économique, collectées
séparément), la lecture de la yield curve (10Y-2Y et son régime), le VIX,
le pétrole, et les taux directeurs des 8 devises (repli config + FEDFUNDS
rafraîchi automatiquement pour l'USD).
"""
from __future__ import annotations

import logging
import os
import statistics

import requests

log = logging.getLogger(__name__)

URL_FRED = "https://api.stlouisfed.org/fred/series/observations"


def _serie_fred(serie_id: str, cle: str, nb: int = 30) -> list[tuple[str, float]]:
    """Observations les plus récentes, ordonnées de la plus récente à la plus ancienne."""
    rep = requests.get(URL_FRED, params={
        "series_id": serie_id, "api_key": cle, "file_type": "json",
        "sort_order": "desc", "limit": nb,
    }, timeout=30)
    rep.raise_for_status()
    observations = rep.json().get("observations", [])
    return [(o["date"], float(o["value"])) for o in observations if o.get("value") not in (".", None)]


def _lecture_yield_curve(obs_10y: list, obs_2y: list) -> dict:
    """Spread 10Y-2Y + régime : inversée / bear steepening / bull steepening /
    flattening, selon l'évolution du spread et du 10Y sur ~1 mois."""
    if not obs_10y or not obs_2y:
        return {"disponible": False}
    dix, deux = obs_10y[0][1], obs_2y[0][1]
    spread = round(dix - deux, 2)
    recul = min(20, len(obs_10y) - 1, len(obs_2y) - 1)
    spread_avant = obs_10y[recul][1] - obs_2y[recul][1]
    delta_spread = spread - spread_avant
    delta_10y = dix - obs_10y[recul][1]
    if spread < 0:
        regime = "courbe inversée"
        lecture = "signal avancé de risque de récession"
    elif delta_spread > 0.05 and delta_10y > 0:
        regime = "bear steepening"
        lecture = "marché anticipant inflation/croissance (hausse tirée par le long)"
    elif delta_spread > 0.05:
        regime = "bull steepening"
        lecture = "marché anticipant un assouplissement monétaire (baisse du court)"
    elif delta_spread < -0.05:
        regime = "aplatissement"
        lecture = "compression du spread — momentum de cycle en question"
    else:
        regime = "stable"
        lecture = "pas de changement notable sur un mois"
    return {
        "disponible": True, "spread_10y_2y": spread, "date": obs_10y[0][0],
        "rendement_10y": dix, "rendement_2y": deux,
        "delta_spread_1m": round(delta_spread, 2), "regime": regime, "lecture": lecture,
    }


SERIES_GRAPHIQUE_MARCHE = {"wti": "DCOILWTICO", "brent": "DCOILBRENTEU"}


def _graphiques_marche(cle: str, nb_points: int) -> dict:
    """Historique pétrole (WTI, Brent) pour graphique — via FRED, pas Twelve
    Data : le tier gratuit Twelve Data réserve les commodités (WTI/USD,
    BRENT/USD, XBR/USD...) aux plans payants (vérifié : HTTP 404 "available
    starting with the Grow or Venture plan"). FRED est déjà une source du
    pipeline (réelle, officielle) ; seul le mécanisme de rendu QuickChart est
    partagé avec les graphiques de prix Twelve Data."""
    graphiques = {}
    for nom, serie_id in SERIES_GRAPHIQUE_MARCHE.items():
        try:
            obs = _serie_fred(serie_id, cle, nb=nb_points)
        except (requests.RequestException, ValueError) as exc:
            log.warning("FRED %s (graphique pétrole) en échec : %s", serie_id, exc)
            continue
        if obs:
            graphiques[nom] = {
                "dates": [d for d, _ in reversed(obs)],
                "valeurs": [v for _, v in reversed(obs)],
            }
    return graphiques


def collecter(config: dict) -> dict:
    resultat: dict = {"series": {}, "yield_curve": {"disponible": False},
                      "taux_directeurs": {}, "graphiques_marche": {}, "erreurs": []}
    cle = os.environ.get("FRED_API_KEY", "")

    observations: dict[str, list] = {}
    if not cle:
        resultat["erreurs"].append("FRED_API_KEY absente — collecte macro limitée aux taux de repli")
        log.error(resultat["erreurs"][-1])
    else:
        for nom, serie_id in config["fred"]["series"].items():
            try:
                obs = _serie_fred(serie_id, cle)
            except (requests.RequestException, ValueError) as exc:
                resultat["erreurs"].append(f"FRED {serie_id} : {exc}")
                log.warning("FRED %s en échec : %s", serie_id, exc)
                continue
            if not obs:
                resultat["erreurs"].append(f"FRED {serie_id} : aucune observation")
                continue
            observations[nom] = obs
            (date_actuelle, valeur) = obs[0]
            precedent = obs[1] if len(obs) > 1 else (None, None)
            variation = (round((valeur - precedent[1]) / abs(precedent[1]) * 100, 2)
                         if precedent[1] not in (None, 0) else None)
            resultat["series"][nom] = {
                "serie_id": serie_id, "source": "FRED",
                "valeur": valeur, "date": date_actuelle,
                "precedent": precedent[1], "date_precedent": precedent[0],
                "variation_pct": variation,
            }
        nb_points = int(config.get("technique", {}).get("graphique_nb_points", 90))
        resultat["graphiques_marche"] = _graphiques_marche(cle, nb_points)

    resultat["yield_curve"] = _lecture_yield_curve(
        observations.get("rendement_10y", []), observations.get("rendement_2y", [])
    )

    # Taux directeurs : repli configuré à la main, USD écrasé par FEDFUNDS si dispo.
    for devise, info in config.get("taux_directeurs", {}).items():
        resultat["taux_directeurs"][devise] = {
            "taux": float(info["taux"]), "date": str(info["date"]),
            "source": "config (repli manuel)",
        }
    fedfunds = resultat["series"].get("taux_fed")
    if fedfunds:
        resultat["taux_directeurs"]["USD"] = {
            "taux": fedfunds["valeur"], "date": fedfunds["date"], "source": "FRED (FEDFUNDS)",
        }

    # Différentiels de carry précalculés (signal secondaire, jamais déclencheur seul).
    taux = {d: v["taux"] for d, v in resultat["taux_directeurs"].items()}
    if taux:
        mediane = statistics.median(taux.values())
        resultat["carry"] = {
            "mediane_g8": round(mediane, 2),
            "differentiels": {d: round(t - mediane, 2) for d, t in taux.items()},
        }

    log.info("Collecte macro : %d série(s), %d erreur(s)",
             len(resultat["series"]), len(resultat["erreurs"]))
    return resultat
