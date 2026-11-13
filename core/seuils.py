"""Seuils sensibles (lot V9.4, B7) : niveaux qu'une source publique désigne comme sensibles pour une autorité, avec la
distance au cours en % et en pips. Table statique, sourcée et datée ; un seuil sans source publique n'y entre pas.

USD/JPY 160 : le ministère des Finances du Japon a publié ses interventions d'avril et mai 2024 (vente de dollars,
achat de yens) ; la première, le 29/04/2024, a suivi un passage de USD/JPY au-dessus de 160. Source : MoF,
« Foreign Exchange Intervention Operations » (mof.go.jp/english/policy/international_policy/reference/feio/).
"""
from __future__ import annotations

from core.technique_avancee import taille_pip

SEUILS = [
    {"paire": "USD/JPY", "niveau": 160.0, "sens": "hausse", "nature": "zone d'intervention du Japon",
     "explication": "le ministère des Finances du Japon est intervenu en avril 2024 après un passage au-dessus de 160",
     "source": "Ministère des Finances du Japon, Foreign Exchange Intervention Operations (interventions du 29/04 et du 01/05/2024)",
     "lien": "https://www.mof.go.jp/english/policy/international_policy/reference/feio/index.html", "releve_le": "2026-11-13"},
]


def distances(cours: dict[str, float]) -> list[dict]:
    """Pour chaque seuil dont la paire a un cours : distance en % et en pips (positive si le seuil est au-dessus)."""
    sortie = []
    for s in SEUILS:
        c = cours.get(s["paire"])
        if c is None:
            continue
        d_pct = round((s["niveau"] / c - 1) * 100, 2)
        d_pips = round((s["niveau"] - c) / taille_pip(s["paire"]), 0)
        proche = abs(d_pct) <= 0.5
        sortie.append({**s, "cours": c, "distance_pct": d_pct, "distance_pips": d_pips, "proche": proche,
                       "texte": (f"{s['paire']} à {abs(d_pct):.1f} % de {s['niveau']:g}".replace(".", ",")
                                 + f" ({abs(int(d_pips))} pips), {s['nature']}")})
    return sorted(sortie, key=lambda x: abs(x["distance_pct"]))
