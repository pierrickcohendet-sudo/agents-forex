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

from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

MAX_PAR_FLUX = 15
FENETRE_HEURES = 36


def _date_entree(entree) -> datetime | None:
    for champ in ("published_parsed", "updated_parsed"):
        brut = getattr(entree, champ, None)
        if brut:
            return datetime.fromtimestamp(time.mktime(brut), tz=timezone.utc)
    return None


def _texte(html: str) -> str:
    import html as html_mod
    import re
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def collecter(config: dict, user_agent: str) -> dict:
    resultat: dict = {"articles": [], "flux": {}, "erreurs": []}
    limite = datetime.now(timezone.utc) - timedelta(hours=FENETRE_HEURES)

    for nom, url in config.get("rss", {}).items():
        try:
            rep = requests.get(url, headers={"User-Agent": user_agent}, timeout=30)
            rep.raise_for_status()
            flux = feedparser.parse(rep.content)
        except requests.RequestException as exc:
            erreur = masquer_secrets(str(exc))
            resultat["erreurs"].append(f"RSS {nom} : {erreur}")
            log.warning("Flux %s en échec : %s", nom, erreur)
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
                # Lot V9 : résumé du flux (texte du flux RSS lui-même, balises retirées) pour les actualités du jour et
                # la probabilité de la Fed citée (vérifiée mot pour mot dans ce texte)
                "resume": _texte(getattr(entree, "summary", "") or getattr(entree, "description", ""))[:700] or None,
            })
            retenus += 1
            if retenus >= MAX_PAR_FLUX:
                break
        resultat["flux"][nom] = {"statut": "ok", "nb_articles": retenus}

    log.info("Collecte news : %d article(s) sur %d flux", len(resultat["articles"]),
             len(config.get("rss", {})))
    return resultat
