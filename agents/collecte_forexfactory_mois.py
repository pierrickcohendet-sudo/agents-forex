"""Lecture de la page « mois » de ForexFactory (https://www.forexfactory.com/calendar?month=this).

Les exports officiels Fair Economy (JSON/XML/CSV/ICS, semaine en cours
seulement) n'ont PAS de valeur « réel » (vérifié le 2026-10-06 : champs title,
country, date, impact, forecast, previous). Seule la page web les expose : le
calendrier y est embarqué en JSON dans `window.calendarComponentStates[1]`
(champs actual / forecast / previous / revision + un `ebaseId` stable par type
d'événement). Ce module ne fait QUE parser ce JSON ; la requête HTTP passe par
core/scraping.py (robots.txt, pauses, cache, pas d'insistance après un 403).
"""
from __future__ import annotations

import json
import re

_MARQUEUR = "window.calendarComponentStates[1]"
_DEBUT_JOURS = re.compile(r"days:\s*")


def parser_page(html: str) -> list[dict]:
    """Retourne les événements de la page, normalisés. Lève ValueError si la
    structure attendue est introuvable (page de défi Cloudflare, refonte du
    site) — jamais une liste vide silencieuse."""
    debut = html.find(_MARQUEUR)
    if debut == -1:
        raise ValueError("calendarComponentStates introuvable dans la page "
                         "(blocage Cloudflare ou refonte du site ?)")
    corresp = _DEBUT_JOURS.search(html, debut)
    if not corresp:
        raise ValueError("liste « days » introuvable dans calendarComponentStates")
    try:
        jours, _ = json.JSONDecoder().raw_decode(html[corresp.end():])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON du calendrier illisible ({exc.msg})") from exc

    evenements = []
    for jour in jours:
        for e in jour.get("events", []):
            evenements.append({
                "id": e.get("id"),
                "ebase_id": e.get("ebaseId"),
                "devise": e.get("currency"),
                "nom": e.get("name"),
                "impact": e.get("impactName"),
                "dateline": e.get("dateline"),
                "reel": (e.get("actual") or "").strip() or None,
                "prevision": (e.get("forecast") or "").strip() or None,
                "precedent": (e.get("previous") or "").strip() or None,
                "revision": (e.get("revision") or "").strip() or None,
                "url": e.get("url"),
            })
    return evenements
