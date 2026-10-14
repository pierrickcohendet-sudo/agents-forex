"""Relais historique : les corrélations glissantes sont calculées par le module partagé core/historique_5ans.py."""
from __future__ import annotations

from datetime import date

from core.historique_5ans import ACTIFS_CORR as ACTIFS, SEANCES_CORR as SEANCES, SERIES, Historique, glissante  # noqa: F401
from core import historique_5ans

SERIES_NECESSAIRES = set(SERIES)


def calculer(bruts: dict[str, list], aujourdhui: date | None = None) -> dict:
    return historique_5ans.correlations(Historique.depuis_points(bruts), None, aujourdhui)
