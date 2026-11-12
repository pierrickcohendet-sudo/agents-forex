"""Membres du FOMC en 2026 (lot V9, A8) : table statique, relevée sur le site de la Réserve fédérale.

Source : https://www.federalreserve.gov/monetarypolicy/fomc.htm, rubrique « 2026 Committee Members » (page mise à jour
le 28/10/2026, relevée le 12/11/2026). La composition change à la première réunion de chaque année : table à mettre à
jour en janvier (la Synthèse affiche l'année de la table à côté du statut).
Priorité d'écoute : président > votant > suppléant ou non votant.
"""
from __future__ import annotations

import re
import unicodedata

SOURCE = "Réserve fédérale, « 2026 Committee Members » (federalreserve.gov/monetarypolicy/fomc.htm, relevé le 12/11/2026)"
ANNEE = 2026
MEMBRES = {
    "warsh": ("Kevin Warsh", "président du FOMC (Conseil des gouverneurs)", "président"),
    "williams": ("John C. Williams", "Fed de New York, vice-président du FOMC", "votant"),
    "barr": ("Michael S. Barr", "Conseil des gouverneurs", "votant"),
    "bowman": ("Michelle W. Bowman", "Conseil des gouverneurs", "votant"),
    "cook": ("Lisa D. Cook", "Conseil des gouverneurs", "votant"),
    "hammack": ("Beth M. Hammack", "Fed de Cleveland", "votant"),
    "jefferson": ("Philip N. Jefferson", "Conseil des gouverneurs", "votant"),
    "kashkari": ("Neel Kashkari", "Fed de Minneapolis", "votant"),
    "logan": ("Lorie K. Logan", "Fed de Dallas", "votant"),
    "paulson": ("Anna Paulson", "Fed de Philadelphie", "votant"),
    "powell": ("Jerome H. Powell", "Conseil des gouverneurs", "votant"),
    "waller": ("Christopher J. Waller", "Conseil des gouverneurs", "votant"),
    "barkin": ("Thomas I. Barkin", "Fed de Richmond", "suppléant"),
    "daly": ("Mary C. Daly", "Fed de San Francisco", "suppléant"),
    "goolsbee": ("Austan D. Goolsbee", "Fed de Chicago", "suppléant"),
    "shukla": ("Sushmita Shukla", "Fed de New York (premier vice-président)", "suppléant"),
    "venable": ("Cheryl Venable", "Fed d'Atlanta (présidente par intérim)", "suppléant"),
}
PRIORITE = {"président": 0, "votant": 1, "suppléant": 2, "non votant": 3}
LIBELLES = {"président": "président du FOMC", "votant": "votant 2026", "suppléant": "suppléant 2026 (non votant)",
            "non votant": "non votant en 2026"}


def _cle(nom: str) -> str:
    t = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", t)


def statut(intervenant: str, devise: str = "USD") -> dict:
    """Statut d'un intervenant de la Fed ; hors table : non votant (présidents des autres Fed régionales)."""
    if devise != "USD":
        return {"statut": None, "libelle": None, "priorite": 3}
    mots = _cle(intervenant).split()
    for cle, (nom, role, st) in MEMBRES.items():
        if cle in mots:
            return {"statut": st, "libelle": LIBELLES[st], "nom": nom, "role": role, "priorite": PRIORITE[st], "source": SOURCE}
    return {"statut": "non votant", "libelle": LIBELLES["non votant"], "priorite": PRIORITE["non votant"], "source": SOURCE}
