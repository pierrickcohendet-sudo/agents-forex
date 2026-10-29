"""Valeurs publiées par les instituts officiels (lot Verrouillage, point 7 « licéité ») : API publiques sans clé.

Remplace progressivement l'extraction de la page « mois » de ForexFactory pour la VALEUR PUBLIÉE des indicateurs
phares : ONS (Royaume-Uni), Statistique Canada (WDS), Eurostat (zone euro). Une requête par série et par jour.
Chaque valeur garde sa source, sa période et sa date de publication. Configuration : config.yaml >
publications_officielles. Les séries des autres devises restent sur ForexFactory, avec la raison (page Santé).
"""
from __future__ import annotations

import logging
from datetime import date

import requests

from core.secrets import masquer_secrets

log = logging.getLogger(__name__)
UA = {"User-Agent": "agents-forex/1.0 (donnees publiques)", "Accept": "application/json"}
MOIS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def _ons(serie: dict, session) -> dict:
    rep = session.get(f"https://www.ons.gov.uk/{serie['chemin']}/data", headers=UA, timeout=40)
    rep.raise_for_status()
    d = rep.json()
    points = d.get("months") or d.get("quarters") or []
    if not points:
        raise ValueError("série ONS sans points mensuels ni trimestriels")
    p = points[-1]
    if p.get("month"):
        periode = f"{p['year']}-{MOIS[p['month'][:3].upper()]:02d}"
    else:
        periode = f"{p['year']}-{p.get('quarter') or p['date'][-2:]}"
    return {"valeur": float(p["value"]), "periode": periode, "publie_le": _date_londres((d.get("description") or {}).get("releaseDate"))}


def _date_londres(iso: str | None) -> str | None:
    """L'ONS code la date de publication à minuit heure de Londres (« 2026-10-20T23:00:00.000Z » = 21/10)."""
    if not iso:
        return None
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/London")).date().isoformat()
    except Exception:  # noqa: BLE001
        return str(iso)[:10]


def _statcan(serie: dict, session) -> dict:
    rep = session.post("https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
                       json=[{"vectorId": int(serie["vecteur"]), "latestN": 2}], headers=UA, timeout=40)
    rep.raise_for_status()
    pts = rep.json()[0]["object"]["vectorDataPoint"]
    dernier = pts[-1]
    valeur = float(dernier["value"])
    if serie.get("calcul") == "mm":   # variation mensuelle en % à partir du niveau (IPC, PIB mensuel)
        valeur = round((valeur / float(pts[-2]["value"]) - 1) * 100, 1)
    return {"valeur": valeur, "periode": dernier["refPer"][:7], "publie_le": str(dernier.get("releaseTime") or "")[:10] or None}


def _eurostat(serie: dict, session) -> dict:
    rep = session.get(f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{serie['jeu']}",
                      params={**serie.get("filtres", {}), "lastTimePeriod": 3}, headers=UA, timeout=40)
    rep.raise_for_status()
    d = rep.json()
    if not d.get("value"):
        raise ValueError("Eurostat : aucune valeur pour ces filtres")
    temps = list(d["dimension"]["time"]["category"]["index"])
    i = max(int(k) for k in d["value"])          # période la plus récente renseignée (la dernière peut être vide)
    return {"valeur": float(d["value"][str(i)]), "periode": temps[i], "publie_le": str(d.get("updated") or "")[:10] or None}


SOURCES = {"ons": _ons, "statcan": _statcan, "eurostat": _eurostat}


def collecter(config: dict, session=requests) -> dict:
    cfg = config.get("publications_officielles") or {}
    sortie = {"valeurs": {}, "erreurs": [], "collecte_le": date.today().isoformat()}
    if not cfg.get("actif", True):
        return sortie
    for s in cfg.get("series") or []:
        cle = f"{s['devise']}|{s['indicateur']}"
        try:
            v = SOURCES[s["source"]](s, session)
            sortie["valeurs"][cle] = {**v, "source": s["libelle"], "unite": s.get("unite", "%")}
        except Exception as exc:  # noqa: BLE001 — une série en échec n'affecte qu'elle
            sortie["erreurs"].append(f"{cle} ({s['source']}) : {masquer_secrets(str(exc))[:150]}")
    log.info("Publications officielles : %d valeur(s), %d erreur(s)", len(sortie["valeurs"]), len(sortie["erreurs"]))
    return sortie
