"""Mises à jour en séance (lot Verrouillage, point 5) : à chaque passage horaire (--completer), sans LLM.

1. Cotations des 8 paires face au dollar : une requête Twelve Data /quote groupée (8 crédits, compteur partagé
   core/quota_twelve.py : jamais plus de 8 par minute ni au-delà du plafond du jour) -> docs/data/seance.json,
   avec l'heure de chaque cotation et sa source.
2. Agenda : valeurs publiées (« réel » dès la sortie du chiffre) relues dans la page « mois » ForexFactory que le
   tableau macro vient de rafraîchir (mise à jour ciblée après une publication importante), puis agenda.json.
3. Thermomètres concernés : dossiers.json recalculé sur les caches du jour et le registre à jour (surprises,
   écarts de taux, agenda), sans nouvelle collecte ; puis sources.json et accueil.json.
Chaque bloc échoue seul ; le résumé dit ce qui a été rafraîchi.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from core import quota_twelve
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

URL_QUOTE = "https://api.twelvedata.com/quote"
PAIRES = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD", "AUD/USD", "NZD/USD", "USD/CNY"]


def _nombre(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def lire_quotes(brut: dict, paires: list[str]) -> dict:
    """Réponse /quote (un ou plusieurs symboles) -> {paire: {prix, heure_utc, variation_pct, precedente, source}}."""
    if len(paires) == 1 and "symbol" in brut:
        brut = {paires[0]: brut}
    sortie = {}
    for p in paires:
        q = brut.get(p) or {}
        if q.get("status") == "error" or _nombre(q.get("close")) is None:
            sortie[p] = {"prix": None, "raison": q.get("message") or "cotation absente de la réponse"}
            continue
        ts = q.get("last_quote_at") or q.get("timestamp")
        heure = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat(timespec="minutes") if ts else None
        sortie[p] = {"prix": _nombre(q["close"]), "heure_utc": heure, "variation_pct": _nombre(q.get("percent_change")),
                     "precedente": _nombre(q.get("previous_close")), "marche_ouvert": q.get("is_market_open"),
                     "source": "Twelve Data (/quote)"}
    return sortie


def cotations(cle: str, paires: list[str] | None = None) -> dict:
    paires = paires or PAIRES
    maintenant = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not cle:
        return {"maj": maintenant, "cotations": {}, "raison": "TWELVE_DATA_API_KEY absente"}
    try:
        quota_twelve.consommer(len(paires), "seance")
        rep = requests.get(URL_QUOTE, params={"symbol": ",".join(paires), "apikey": cle}, timeout=30)
        rep.raise_for_status()
        return {"maj": maintenant, "cotations": lire_quotes(rep.json(), paires), "raison": None}
    except Exception as exc:  # noqa: BLE001 — quota, réseau, format : n/d avec la raison
        return {"maj": maintenant, "cotations": {}, "raison": masquer_secrets(str(exc))[:200]}


def _cache(racine: Path, nom: str) -> dict | None:
    try:
        return json.loads((racine / "data" / "cache" / f"collecte_{nom}.json").read_text(encoding="utf-8")).get("donnees")
    except (OSError, ValueError):
        return None


def rafraichir(racine: str | Path, config: dict, rapport: dict | None) -> dict:
    """Passage en séance : cotations, agenda (réel publié), thermomètres, santé et accueil. -> résumé."""
    from core import accueil, dossiers, registre_macro, sources
    racine = Path(racine)
    docs = racine / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
    resume: dict = {}
    try:
        s = cotations(os.environ.get("TWELVE_DATA_API_KEY", "").strip())
        (docs / "seance.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        resume["cotations"] = sum(1 for c in s["cotations"].values() if c.get("prix") is not None) if not s["raison"] else s["raison"]
    except Exception as exc:  # noqa: BLE001
        resume["cotations"] = f"échec : {exc}"[:200]
    try:
        registre = registre_macro.charger(racine / "data" / "registre_macro.json")
        technique = _cache(racine, "technique") or {}
        d = dossiers.ecrire(racine, _cache(racine, "historiques") or {}, registre, technique, config, rapport,
                            _cache(racine, "flux"), _cache(racine, "news"), racine / "data" / "rapports")
        # dossiers.ecrire recalcule aussi agenda.json, outils.json et paires.json (thermomètres et radar à jour)
        ag = json.loads((docs / "agenda.json").read_text(encoding="utf-8"))
        resume["agenda_publies"] = sum(1 for j in ag.get("jours") or [] for e in j.get("evenements") or [] if e.get("publie"))
        resume["thermometres"] = sum(1 for t in ((d or {}).get("cockpit") or {}).get("thermometres") or [] if t.get("valeur") is not None)
    except Exception as exc:  # noqa: BLE001
        log.exception("Séance : dossiers / agenda non rafraîchis")
        resume["dossiers"] = f"échec : {exc}"[:200]
    for nom, f in (("sources", lambda: sources.ecrire(racine, config, rapport)), ("accueil", lambda: accueil.ecrire(racine, config))):
        try:
            f()
        except Exception as exc:  # noqa: BLE001
            resume[nom] = f"échec : {exc}"[:200]
    log.info("Séance : %s", resume)
    return resume
