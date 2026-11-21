"""Collecte des news via flux RSS et Atom natifs : médias (CNBC World, InvestingLive) et, depuis le 21/11/2026, flux
officiels classés par moteur (`rss_officiels` de config.yaml : banques centrales, Trésors, Commission et Conseil de l'UE,
ONU, Foreign Office, EIA).

RSS uniquement — aucun scraping HTML ici. Échec d'un flux (réseau, 403, flux illisible) = mention explicite, le flux est
ignoré et le pipeline continue ; un 403 n'est jamais contourné. Chaque titre garde sa source et son lien.
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
MAX_PAR_FLUX_OFFICIEL = 10
FENETRE_HEURES = 36
# Client identifié honnêtement pour les sites publics (aucune donnée personnelle)
UA_OFFICIEL = "agents-forex/1.0 (outil personnel d'aide a la decision ; lecture de flux RSS publics)"
ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5"


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


def flux_configures(config: dict, user_agent: str) -> list[dict]:
    """Médias (`rss`, URL simple) puis flux officiels (`rss_officiels`, avec nom, moteur, licence, en-tête Accept)."""
    l = [{"id": nom, "url": url, "ua": user_agent, "accept": ACCEPT, "max": MAX_PAR_FLUX} for nom, url in (config.get("rss") or {}).items()]
    for nom, f in (config.get("rss_officiels") or {}).items():
        if isinstance(f, dict) and f.get("url") and f.get("actif", True):
            l.append({"id": nom, "url": f["url"], "ua": UA_OFFICIEL, "accept": f.get("accept") or ACCEPT, "max": MAX_PAR_FLUX_OFFICIEL,
                      "nom": f.get("nom"), "moteur": f.get("moteur"), "licence": f.get("licence"), "officiel": True,
                      "classement": f.get("classement") or "mots_cles"})
    return l


def collecter(config: dict, user_agent: str, session=None) -> dict:
    resultat: dict = {"articles": [], "flux": {}, "erreurs": []}
    limite = datetime.now(timezone.utc) - timedelta(hours=FENETRE_HEURES)
    http = session or requests
    flux_l = flux_configures(config, user_agent)
    for fx in flux_l:
        nom = fx["id"]
        try:
            rep = http.get(fx["url"], headers={"User-Agent": fx["ua"], "Accept": fx["accept"]}, timeout=30)
            if rep.status_code == 403:
                raise requests.HTTPError("403 : accès refusé au robot (jamais contourné)")
            rep.raise_for_status()
            flux = feedparser.parse(rep.content)
            if not flux.entries and getattr(flux, "bozo", False):
                raise ValueError(f"flux illisible ({type(getattr(flux, 'bozo_exception', None)).__name__})")
        except Exception as exc:  # noqa: BLE001 — un flux en échec est ignoré, le run continue
            erreur = masquer_secrets(str(exc))[:200]
            resultat["erreurs"].append(f"RSS {nom} : {erreur}")
            log.warning("Flux %s en échec : %s", nom, erreur)
            resultat["flux"][nom] = {"statut": "indisponible", "raison": erreur}
            continue

        retenus = 0
        for entree in flux.entries[: fx["max"] * 3]:
            date_pub = _date_entree(entree)
            if date_pub and date_pub < limite:
                continue
            article = {
                "source": nom,
                "titre": getattr(entree, "title", "(sans titre)").strip()[:300],
                "lien": getattr(entree, "link", None),
                "date": date_pub.isoformat() if date_pub else None,
                # Lot V9 : résumé du flux (texte du flux RSS lui-même, balises retirées) pour les actualités du jour et
                # la probabilité de la Fed citée (vérifiée mot pour mot dans ce texte)
                "resume": _texte(getattr(entree, "summary", "") or getattr(entree, "description", ""))[:700] or None,
            }
            if fx.get("officiel"):
                article.update({"source_nom": fx.get("nom") or nom, "moteur_flux": fx.get("moteur"), "officiel": True, "licence": fx.get("licence"),
                                "classement": fx.get("classement")})
            resultat["articles"].append(article)
            retenus += 1
            if retenus >= fx["max"]:
                break
        resultat["flux"][nom] = {"statut": "ok", "nb_articles": retenus, **({"officiel": True, "moteur": fx.get("moteur")} if fx.get("officiel") else {})}

    log.info("Collecte news : %d article(s) sur %d flux (%d en échec)", len(resultat["articles"]), len(flux_l), len(resultat["erreurs"]))
    return resultat
