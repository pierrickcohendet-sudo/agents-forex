"""Taux US du jour (lot V9, A3) : courbe des taux du Trésor américain (fichier quotidien de treasury.gov, CSV public).

FRED (DGS2, DGS10, DGS30) reprend ces mêmes taux avec un jour de retard ; le Trésor publie le soir même (vers 18:00
heure de New York). Les points du Trésor complètent donc la série FRED (mêmes valeurs aux mêmes dates) ; FRED reste
en secours si le fichier du Trésor ne répond pas. Une requête par run complet (année en cours, et l'année
précédente en janvier).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime

log = logging.getLogger(__name__)

URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{annee}/all"
       "?type=daily_treasury_yield_curve&field_tdr_date_value={annee}&page&_format=csv")
SOURCE = "Trésor américain (courbe des taux quotidienne, treasury.gov)"
COLONNES = {"USD_2a": "2 Yr", "USD_10a": "10 Yr", "USD_30a": "30 Yr"}
UA = {"User-Agent": "agents-forex/1.0 (donnees publiques)"}


def lire_csv(texte: str) -> dict[str, list[list]]:
    """CSV du Trésor -> {USD_2a: [[AAAA-MM-JJ, taux], ...]} du plus ancien au plus récent."""
    sortie: dict[str, list[list]] = {k: [] for k in COLONNES}
    for ligne in csv.DictReader(io.StringIO(texte.lstrip("﻿"))):
        try:
            jour = datetime.strptime(ligne["Date"].strip(), "%m/%d/%Y").date().isoformat()
        except (KeyError, ValueError):
            continue
        for nom, col in COLONNES.items():
            try:
                sortie[nom].append([jour, float(ligne[col])])
            except (KeyError, TypeError, ValueError):
                pass
    return {k: sorted(v) for k, v in sortie.items()}


def collecter(aujourd: date | None = None, session=None) -> dict:
    """{"points": {USD_2a: [...]}, "source", "dernier", "erreur"} ; ne lève jamais."""
    import requests
    aujourd = aujourd or date.today()
    annees = [aujourd.year - 1, aujourd.year] if aujourd.month == 1 else [aujourd.year]
    points: dict[str, list] = {k: [] for k in COLONNES}
    try:
        for a in annees:
            rep = (session or requests).get(URL.format(annee=a), headers=UA, timeout=40)
            rep.raise_for_status()
            for k, v in lire_csv(rep.text).items():
                points[k] += v
        points = {k: sorted(v) for k, v in points.items()}
        dernier = max((v[-1][0] for v in points.values() if v), default=None)
        if not dernier:
            raise RuntimeError("fichier du Trésor sans observation")
        return {"points": points, "source": SOURCE, "dernier": dernier, "erreur": None}
    except Exception as exc:  # noqa: BLE001
        log.warning("Courbe du Trésor non collectée : %s", exc)
        return {"points": {}, "source": SOURCE, "dernier": None, "erreur": str(exc)[:200]}


def fusionner(points_fred: list | None, points_tresor: list | None) -> list[tuple[str, float]]:
    """Série FRED complétée par le Trésor : à date égale, la valeur du Trésor (publication d'origine)."""
    d = {str(x[0])[:10]: x[1] for x in points_fred or []}
    d.update({str(x[0])[:10]: x[1] for x in points_tresor or []})
    return sorted(d.items())
