"""Collecte des news via flux RSS natifs (CNBC World, InvestingLive/ForexLive).

RSS uniquement — aucun scraping HTML ici. Échec d'un flux = mention explicite,
le pipeline continue.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests

log = logging.getLogger(__name__)

MAX_PAR_FLUX = 15
FENETRE_HEURES = 36


def _date_entree(entree) -> datetime | None:
    for champ in ("published_parsed", "updated_parsed"):
        brut = getattr(entree, champ, None)
        if brut:
            return datetime.fromtimestamp(time.mktime(brut), tz=timezone.utc)
    return None


def collecter(config: dict, user_agent: str) -> dict:
    resultat: dict = {"articles": [], "flux": {}, "erreurs": []}
    limite = datetime.now(timezone.utc) - timedelta(hours=FENETRE_HEURES)

    for nom, url in config.get("rss", {}).items():
        try:
            rep = requests.get(url, headers={"User-Agent": user_agent}, timeout=30)
            rep.raise_for_status()
            flux = feedparser.parse(rep.content)
        except requests.RequestException as exc:
            resultat["erreurs"].append(f"RSS {nom} : {exc}")
            log.warning("Flux %s en échec : %s", nom, exc)
            resultat["flux"][nom] = {"statut": "indisponible"}
            continue

        retenus = 0
        for entree in flux.entries[: MAX_PAR_FLUX * 3]:
            date_pub = _date_entree(entree)
            if date_pub and date_pub < limite:
                continue
            resultat["articles"].append({
                "source": nom,
                "titre": getattr(entree, "title", "(sans titre)").strip()[:300],
                "lien": getattr(entree, "link", None),
                "date": date_pub.isoformat() if date_pub else None,
            })
            retenus += 1
            if retenus >= MAX_PAR_FLUX:
                break
        resultat["flux"][nom] = {"statut": "ok", "nb_articles": retenus}

    log.info("Collecte news : %d article(s) sur %d flux", len(resultat["articles"]),
             len(config.get("rss", {})))
    return resultat
