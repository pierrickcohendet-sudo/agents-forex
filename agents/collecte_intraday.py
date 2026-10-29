"""Chandeliers 30 min, 4 h et 1 jour des « Mes paires » (lot V5, étape 7, Journal). Twelve Data, run complet seulement.

Quota : 6 paires × 3 unités = 18 requêtes au plus par jour, une pause de 8 s entre deux appels (moins de 8 par minute,
limite du plan gratuit), cache du jour (data/cache/intraday.json) : un second run le même jour ne refait aucune requête.
Une paire ou une unité en échec n'affecte qu'elle (raison enregistrée) ; aucune valeur inventée.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from core import paires
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

URL = "https://api.twelvedata.com/time_series"
UNITES = {"30min": ("30min", 96), "4h": ("4h", 90), "1j": ("1day", 120)}
PAUSE_S = 8.0


def _bougies(paire: str, intervalle: str, taille: int, cle: str) -> list[list]:
    from core import quota_twelve
    quota_twelve.consommer(1, "chandeliers")
    rep = requests.get(URL, params={"symbol": paire, "interval": intervalle, "outputsize": taille, "apikey": cle,
                                    "timezone": "UTC"}, timeout=60)
    rep.raise_for_status()
    d = rep.json()
    if d.get("status") != "ok":
        raise RuntimeError(f"Twelve Data {paire} {intervalle} : {d.get('message', 'réponse invalide')}")
    sortie = []
    for v in reversed(d.get("values") or []):
        try:
            sortie.append([v["datetime"], float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"])])
        except (KeyError, TypeError, ValueError):
            continue
    return sortie


def collecter(config: dict, racine: str | Path, cle: str | None = None, pause_s: float = PAUSE_S,
              aujourdhui: date | None = None) -> dict:
    chemin = Path(racine) / "data" / "cache" / "intraday.json"
    jour = (aujourdhui or date.today()).isoformat()
    try:
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ancien = {}
    mes = paires.mes_paires(config)
    if ancien.get("date") == jour and all(u in ((ancien.get("paires") or {}).get(p) or {}) for p in mes for u in UNITES):
        log.info("Chandeliers du jour déjà collectés : aucune requête")
        return ancien
    cle = cle if cle is not None else os.environ.get("TWELVE_DATA_API_KEY", "").strip()
    sortie = {"date": jour, "collecte_le": datetime.now(timezone.utc).isoformat(timespec="seconds"), "paires": {}, "erreurs": [],
              "source": "Twelve Data (time_series, heures UTC)"}
    if not cle:
        sortie["raison"] = "TWELVE_DATA_API_KEY absente : chandeliers non collectés"
        return sortie
    premiere = True
    for p in mes:
        sortie["paires"][p] = {}
        for unite, (intervalle, taille) in UNITES.items():
            deja = ((ancien.get("paires") or {}).get(p) or {}).get(unite) if ancien.get("date") == jour else None
            if deja and deja.get("bougies"):
                sortie["paires"][p][unite] = deja
                continue
            if not premiere:
                time.sleep(pause_s)          # < 8 requêtes par minute (plan gratuit Twelve Data)
            premiere = False
            try:
                sortie["paires"][p][unite] = {"bougies": _bougies(p, intervalle, taille, cle), "source": sortie["source"]}
            except Exception as exc:  # noqa: BLE001 — une unité en échec n'affecte qu'elle
                raison = masquer_secrets(str(exc))[:160]
                sortie["paires"][p][unite] = {"bougies": [], "raison": raison}
                sortie["erreurs"].append(f"{p} {unite} : {raison}")
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(sortie, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except OSError as exc:
        log.warning("Cache des chandeliers non écrit : %s", exc)
    log.info("Chandeliers : %d paire(s), %d erreur(s)", len(sortie["paires"]), len(sortie["erreurs"]))
    return sortie
