"""Publications officielles détaillées (lot V9.4, B2 et B3) : API publiques sans clé, une collecte par jour.

- ONS (Royaume-Uni) : PIB trimestriel (T/T et sur un an), services et construction (première estimation, jeu PN2),
  PIB mensuel (jeu MGDP).
- Eurostat (zone euro, EA20) : PIB trimestriel (T/T et sur un an, estimation la plus récente), emploi (T/T).
Cache : data/cache/officiels_v94.json. Chaque valeur garde sa période, sa date de publication et sa source.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

RACINE = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "agents-forex/1.0 (donnees publiques)", "Accept": "application/json"}
ONS = {"pib_tt": ("ihyq", "pn2", "PIB trimestriel (T/T)"), "pib_aa": ("ihyr", "pn2", "PIB sur un an"),
       "services_tt": ("l3e2", "pn2", "Services (T/T)"), "construction_tt": ("l3dw", "pn2", "Construction (T/T)"),
       "pib_mm": ("ecyx", "mgdp", "PIB mensuel (M/M)")}
EUROSTAT = {"pib_tt": ("namq_10_gdp", "unit=CLV_PCH_PRE&s_adj=SCA&na_item=B1GQ", "PIB trimestriel (T/T)"),
            "pib_aa": ("namq_10_gdp", "unit=CLV_PCH_SM&s_adj=SCA&na_item=B1GQ", "PIB sur un an"),
            "emploi_tt": ("namq_10_pe", "unit=PCH_PRE_PER&s_adj=SCA&na_item=EMP_DC", "Emploi (T/T)")}


def _ons(code: str, jeu: str, session) -> dict:
    rep = session.get(f"https://www.ons.gov.uk/economy/grossdomesticproductgdp/timeseries/{code}/{jeu}/data", headers=UA, timeout=40)
    rep.raise_for_status()
    d = rep.json()
    pts = d.get("quarters") or d.get("months") or []
    if not pts:
        raise ValueError("série ONS vide")
    p, prec = pts[-1], (pts[-2] if len(pts) > 1 else None)
    return {"valeur": float(p["value"]), "periode": p["date"], "precedent": float(prec["value"]) if prec else None,
            "periode_precedente": prec["date"] if prec else None, "publie_le": str(d["description"].get("releaseDate") or "")[:10],
            "source": f"Office for National Statistics ({code.upper()}, {jeu.upper()})",
            "lien": f"https://www.ons.gov.uk/economy/grossdomesticproductgdp/timeseries/{code}/{jeu}"}


def _eurostat(jeu: str, filtre: str, session) -> dict:
    url = f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{jeu}?geo=EA20&{filtre}&lastTimePeriod=2"
    rep = session.get(url, headers=UA, timeout=40)
    rep.raise_for_status()
    d = rep.json()
    index = (d.get("dimension", {}).get("time", {}).get("category", {}) or {}).get("index") or {}
    vals = d.get("value") or {}
    periodes = sorted(index, key=index.get)
    obs = [(per, vals.get(str(index[per]))) for per in periodes if vals.get(str(index[per])) is not None]
    if not obs:
        raise ValueError("série Eurostat vide")
    return {"valeur": obs[-1][1], "periode": obs[-1][0], "precedent": obs[-2][1] if len(obs) > 1 else None,
            "periode_precedente": obs[-2][0] if len(obs) > 1 else None, "publie_le": str(d.get("updated") or "")[:10],
            "source": f"Eurostat ({jeu}, EA20)", "lien": f"https://ec.europa.eu/eurostat/databrowser/view/{jeu}/default/table"}


def collecter(racine: Path | None = None, maintenant: datetime | None = None, session=None, chemin: Path | None = None) -> dict:
    """Une collecte par jour ; une série en échec n'affecte qu'elle (n/d avec la raison). Ne lève jamais."""
    import requests
    racine = Path(racine or RACINE)
    chemin = Path(chemin or racine / "data" / "cache" / "officiels_v94.json")
    maintenant = maintenant or datetime.now(timezone.utc)
    try:
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ancien = {}
    dernier = ancien.get("collecte_le", "")
    if dernier[:10] == maintenant.date().isoformat() and (maintenant.hour < 12 or dernier[11:13] >= "12"):
        return ancien   # une collecte le matin, une seconde l'après-midi (publications de 08:00 à 11:00 heure de Paris)
    s = session or requests
    sortie = {"collecte_le": maintenant.isoformat(timespec="minutes"), "GBP": {}, "EUR": {}}
    for cle, (code, jeu, lib) in ONS.items():
        try:
            sortie["GBP"][cle] = {**_ons(code, jeu, s), "libelle": lib}
        except Exception as exc:  # noqa: BLE001
            sortie["GBP"][cle] = {"valeur": None, "libelle": lib, "raison": f"ONS indisponible : {str(exc)[:120]}"}
    for cle, (jeu, filtre, lib) in EUROSTAT.items():
        try:
            sortie["EUR"][cle] = {**_eurostat(jeu, filtre, s), "libelle": lib}
        except Exception as exc:  # noqa: BLE001
            sortie["EUR"][cle] = {"valeur": None, "libelle": lib, "raison": f"Eurostat indisponible : {str(exc)[:120]}"}
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        log.warning("officiels_v94.json non écrit : %s", exc)
    return sortie
