"""Indicateurs clés (lot V14, correctif V13.1) : publications que ForexFactory classe « faible » mais qui comptent pour
la devise (consensus suivi, réaction de marché habituelle). Leur importance est relevée au moins à « moyen », pour
l'agenda comme pour le documentaire, avec la mention « importance relevée par le site ».

Une ligne : (devise, motif sur le nom anglais ForexFactory, impact minimal, raison).
"""
from __future__ import annotations

import re

INDICATEURS_CLES = [
    ("CAD", r"^(core )?retail sales m/m$", "moyen",
     "ventes au détail canadiennes : principal indicateur de la consommation, suivi par la Banque du Canada"),
    ("JPY", r"^national core cpi y/y$", "moyen",
     "inflation sous-jacente nationale : la mesure que la Banque du Japon cite pour sa politique"),
    ("JPY", r"^tokyo core cpi y/y$", "moyen",
     "inflation sous-jacente de Tokyo : publiée trois semaines avant la mesure nationale"),
    ("GBP", r"^public sector net borrowing$", "moyen",
     "besoin net de financement public : dérive budgétaire britannique (moteur Budgets et dette publique)"),
]
MENTION = "importance relevée par le site"
_RANG = {"faible": 1, "moyen": 2, "fort": 3}


def relever(devise: str | None, evenement_en: str | None, impact: str | None) -> tuple[str | None, str | None]:
    """-> (impact retenu, raison si relevé). Ne baisse jamais une importance."""
    nom = str(evenement_en or "").strip().lower()
    for dev, motif, minimum, raison in INDICATEURS_CLES:
        if dev == devise and re.search(motif, nom) and _RANG.get(impact or "", 0) < _RANG[minimum]:
            return minimum, f"{MENTION} (ForexFactory : {impact or 'n/d'}) : {raison}"
    return impact, None
