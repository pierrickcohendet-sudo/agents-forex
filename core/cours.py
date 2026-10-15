"""Cours des 9 devises pour la page Devises (palier C) : 1 an de la série unique de chaque devise et sa moyenne
mobile 200 jours, calculées sur la MÊME série que le RSI et l'écart à la MM200 affichés partout (core/historique_5ans.py).
Force de la devise : dollars US par unité (USD : indice synthétique face aux 8 autres). Sans LLM.
Écrit docs/data/cours.json, chargé seulement par la page Devises."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import historique_5ans as h5m, impact

log = logging.getLogger(__name__)
JOURS = 366


def calculer(h: h5m.Historique, technique: dict | None = None, aujourdhui: date | None = None) -> dict:
    sortie = {"genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": h5m.SOURCE_INDICATEURS,
              "devises": {}}
    for devise in h5m.DEVISES:
        serie = impact.serie_devise(h, devise, technique).points
        if len(serie) < 200:
            sortie["devises"][devise] = {"raison": "historique quotidien insuffisant pour la moyenne mobile 200 jours"}
            continue
        mm = [(d, v) for d, v in h5m.moyenne_mobile(serie, 200)]
        limite = (date.fromisoformat(serie[-1][0]) - timedelta(days=JOURS)).isoformat()
        sortie["devises"][devise] = {
            "points": [[d, round(v, 6)] for d, v in serie if d >= limite],
            "mm200": [[d, round(v, 6)] for d, v in mm if d >= limite],
            "dernier": round(serie[-1][1], 6), "date": serie[-1][0],
            "libelle": "indice USD synthétique (face aux 8 autres devises)" if devise == "USD" else f"dollars US pour 1 {devise}"}
    return sortie


def ecrire(racine: str | Path, h: h5m.Historique, technique: dict | None, config: dict) -> dict | None:
    try:
        donnees = calculer(h, technique)
        chemin = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data" / "cours.json"
        chemin.write_text(json.dumps(donnees, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("cours.json non écrit : %s", exc)
        return None
