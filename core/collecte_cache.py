"""Cache générique « 1 collecte par jour » pour les collecteurs à quota limité
(Twelve Data, FRED, RSS) — même principe que le cache par site de
core/scraping.py (déjà garanti là-bas), généralisé ici à un collecteur entier.

En mode --completer, un passage de complément réutilise le résultat déjà
collecté plus tôt dans la journée plutôt que de re-consommer du quota API
pour des données qui n'ont probablement pas bougé entre deux passages du même
jour. Un run complet (hors --completer) collecte toujours frais et
rafraîchit le cache pour les passages --completer suivants.

Ne remplace PAS le cache de core/scraping.py (par site, avec robots.txt,
retry unique et blacklist 403 — logique propre au scraping, pas généralisable
ici) : collecte_calendrier.py garde son propre mécanisme, inchangé.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


def _chemin(dossier: str | Path, nom: str) -> Path:
    return Path(dossier) / f"collecte_{nom}.json"


def _lire(dossier: str | Path, nom: str, jour: date) -> dict | None:
    try:
        brut = json.loads(_chemin(dossier, nom).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if brut.get("date") != jour.isoformat():
        return None
    return brut.get("donnees")


def _ecrire(dossier: str | Path, nom: str, jour: date, donnees: dict) -> None:
    Path(dossier).mkdir(parents=True, exist_ok=True)
    try:
        contenu = json.dumps({"date": jour.isoformat(), "donnees": donnees},
                             ensure_ascii=False, default=str)
    except TypeError as exc:
        log.warning("Cache collecte %s non écrit (données non sérialisables) : %s", nom, exc)
        return
    _chemin(dossier, nom).write_text(contenu, encoding="utf-8")


def avec_cache(nom: str, dossier: str | Path, jour: date, reutiliser: bool,
              fonction_collecte: Callable, *args, **kwargs) -> dict:
    """reutiliser=True (--completer) : tente le cache du jour d'abord, retombe
    sur une collecte fraîche si absent (ex. --completer lancé sans run complet
    avant ce jour-là). reutiliser=False : collecte toujours frais et écrit/
    rafraîchit le cache pour les passages --completer suivants."""
    if reutiliser:
        cache = _lire(dossier, nom, jour)
        if cache is not None:
            log.info("Collecte %s : cache du jour réutilisé (--completer, aucun nouvel appel API)", nom)
            return cache
        log.info("Collecte %s : --completer sans cache du jour — collecte fraîche effectuée", nom)
    resultat = fonction_collecte(*args, **kwargs)
    _ecrire(dossier, nom, jour, resultat)
    return resultat
