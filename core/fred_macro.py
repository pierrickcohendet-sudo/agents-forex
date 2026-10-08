"""Valeurs FRED pour le Tableau macro : repli (valeur absente de ForexFactory),
contrôle croisé (divergence entre sources) et projections officielles des
banques centrales (Fed SEP publié sur FRED).

Code pur, aucun LLM. Configuration : config.yaml > tableau_macro.fred.
Chaque valeur garde son identifiant de série et sa période d'observation :
FRED donne la période (ex. 2026-08 pour le CPI d'août), pas la date de
publication — l'affichage le dit (« pér. 08/26 »), jamais une date inventée.
"""
from __future__ import annotations

import logging
from datetime import date

import requests

from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

URL_FRED = "https://api.stlouisfed.org/fred/series/observations"


def _observations(serie: str, cle: str, nb: int = 16, **extra) -> list[dict]:
    rep = requests.get(URL_FRED, params={"series_id": serie, "api_key": cle, "file_type": "json",
                                         "sort_order": "desc", "limit": nb, **extra}, timeout=30)
    rep.raise_for_status()
    return [o for o in rep.json().get("observations", []) if o.get("value") not in (".", None)]


def _derniere_vintage(serie: str, cle: str) -> str | None:
    """Date de la dernière révision de la série = date de publication de la
    projection (ex. réunion de septembre du FOMC pour le SEP)."""
    rep = requests.get("https://api.stlouisfed.org/fred/series/vintagedates",
                       params={"series_id": serie, "api_key": cle, "file_type": "json",
                               "sort_order": "desc", "limit": 1}, timeout=30)
    rep.raise_for_status()
    dates = rep.json().get("vintage_dates", [])
    return dates[0] if dates else None


def _formater(valeur: float, unite: str) -> str:
    if unite == "K":
        return f"{valeur:.0f}K"
    if unite == "B":
        return f"{valeur:.1f}B"
    return f"{valeur:.1f}%"


def _valeur(obs: list[dict], decalage: int, calcul: str, unite: str) -> tuple[str, str] | None:
    """(valeur formatée, période AAAA-MM) pour l'observation `decalage` (0 = la plus récente)."""
    try:
        if calcul == "yoy":
            v = (float(obs[decalage]["value"]) / float(obs[decalage + 12]["value"]) - 1) * 100
        elif calcul == "pct_m":
            v = (float(obs[decalage]["value"]) / float(obs[decalage + 1]["value"]) - 1) * 100
        elif calcul == "diff":
            v = float(obs[decalage]["value"]) - float(obs[decalage + 1]["value"])
        elif calcul == "milliards":
            v = float(obs[decalage]["value"]) / 1000.0
        elif calcul == "unites_milliards":
            v = float(obs[decalage]["value"]) / 1e9
        else:  # niveau
            v = float(obs[decalage]["value"])
    except (IndexError, ValueError, ZeroDivisionError):
        return None
    return _formater(v, unite), obs[decalage]["date"][:7]


def collecter(cfg_tm: dict, cle: str) -> dict:
    """{"valeurs": {"USD|cpi": {...}}, "projections": {"USD|chomage": {...}}, "erreurs": [...]}.
    Chaque série en échec n'affecte que sa case."""
    cfg = cfg_tm.get("fred") or {}
    resultat: dict = {"valeurs": {}, "projections": {}, "erreurs": []}
    if not cle:
        resultat["erreurs"].append("FRED_API_KEY absente — repli et contrôles FRED sautés")
        return resultat
    for indicateur, par_devise in (cfg.get("series") or {}).items():
        for devise, spec in par_devise.items():
            try:
                obs = _observations(spec["serie"], cle)
                if spec.get("serie_moins"):  # solde = série A - série B (ex. exports - imports)
                    autre = {o["date"]: float(o["value"]) for o in _observations(spec["serie_moins"], cle)}
                    obs = [{"date": o["date"], "value": float(o["value"]) - autre[o["date"]]}
                           for o in obs if o["date"] in autre]
                unite = spec.get("unite", "%")
                actuelle = _valeur(obs, 0, spec.get("calcul", "niveau"), unite)
                precedente = _valeur(obs, 1, spec.get("calcul", "niveau"), unite)
                if actuelle:
                    resultat["valeurs"][f"{devise}|{indicateur}"] = {
                        "valeur": actuelle[0], "periode": actuelle[1],
                        "precedente": precedente[0] if precedente else None,
                        "serie": spec["serie"], "usage": spec.get("usage", "controle"),
                        "etiquette": spec.get("etiquette")}
            except Exception as exc:  # noqa: BLE001
                resultat["erreurs"].append(f"{devise}|{indicateur} ({spec.get('serie')}) : "
                                           f"{masquer_secrets(str(exc))[:120]}")
    annee = date.today().year
    for devise, par_indic in (cfg.get("projections") or {}).items():
        for indicateur, spec in par_indic.items():
            try:
                obs = _observations(spec["serie"], cle, nb=1, observation_start=f"{annee}-01-01",
                                    observation_end=f"{annee}-12-31", sort_order="asc")
                if not obs:
                    continue
                o = obs[0]
                resultat["projections"][f"{devise}|{indicateur}"] = {
                    "valeur": _formater(float(o["value"]), spec.get("unite", "%")),
                    "horizon": spec["horizon"].format(annee=annee),
                    "date_pub": _derniere_vintage(spec["serie"], cle), "serie": spec["serie"],
                    "source": spec.get("source", "projection officielle"),
                }
            except Exception as exc:  # noqa: BLE001
                resultat["erreurs"].append(f"projection {devise}|{indicateur} : "
                                           f"{masquer_secrets(str(exc))[:120]}")
    log.info("FRED tableau macro : %d valeur(s), %d projection(s), %d erreur(s)",
             len(resultat["valeurs"]), len(resultat["projections"]), len(resultat["erreurs"]))
    return resultat
