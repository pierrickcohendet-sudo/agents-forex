"""Collecte « flux et offre/demande » pour les engrenages 5, 7 et 8 (palier 2).

- CFTC, rapport Commitments of Traders (legacy, futures only), API publique Socrata sans clé :
  positions NON COMMERCIALES (spéculateurs) sur les contrats de change du CME et l'indice dollar
  ICE. Net = long - short ; un net positif = paris à la hausse de la devise. Percentile du net sur
  52 semaines (positionnement extrême = ≥ 90 ou ≤ 10). Hebdomadaire (positions du mardi,
  publiées le vendredi). Pas de contrat yuan : « non couvert par la CFTC ».
- EIA, stocks hebdomadaires de brut américain hors réserve stratégique (WCESTUS1), API v2 :
  clé EIA_API_KEY si présente, sinon la clé publique de démonstration DEMO_KEY (quota faible,
  suffisant pour une requête par jour).
- Or : FRED n'a plus de cours spot gratuit (séries LBMA retirées) ; indice proxy NASDAQ QGLDI
  (Credit Suisse NASDAQ Gold FLOWS103), jamais présenté comme le cours de l'or.

Une requête par source ; une source en échec n'affecte qu'elle (erreurs listées, jamais inventé).
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import requests

from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

UA = {"User-Agent": "agents-forex/1.0 (rapport FX personnel ; une requête par jour)"}
URL_COT = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
URL_EIA = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
URL_FRED = "https://api.stlouisfed.org/fred/series/observations"

CONTRATS_COT = {   # code CFTC -> devise ; USD = indice dollar ICE
    "099741": "EUR", "096742": "GBP", "097741": "JPY", "092741": "CHF", "090741": "CAD",
    "232741": "AUD", "112741": "NZD", "098662": "USD",
}
SERIE_EIA = "WCESTUS1"
SERIE_OR = "NASDAQQGLDI"


def _cot(aujourdhui: date) -> dict:
    debut = (aujourdhui - timedelta(days=380)).isoformat()
    codes = ", ".join(f"'{c}'" for c in CONTRATS_COT)
    rep = requests.get(URL_COT, headers=UA, timeout=40, params={
        "$select": "cftc_contract_market_code, market_and_exchange_names, report_date_as_yyyy_mm_dd, "
                   "noncomm_positions_long_all, noncomm_positions_short_all, open_interest_all",
        "$where": f"cftc_contract_market_code in ({codes}) AND report_date_as_yyyy_mm_dd > '{debut}'",
        "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 1000})
    rep.raise_for_status()
    par_devise: dict[str, list] = {}
    for x in rep.json():
        devise = CONTRATS_COT.get(x.get("cftc_contract_market_code"))
        try:
            net = int(float(x["noncomm_positions_long_all"])) - int(float(x["noncomm_positions_short_all"]))
            oi = int(float(x.get("open_interest_all") or 0))
        except (KeyError, TypeError, ValueError):
            continue
        if devise:
            par_devise.setdefault(devise, []).append((x["report_date_as_yyyy_mm_dd"][:10], net, oi,
                                                      x.get("market_and_exchange_names")))
    resultat = {}
    for devise, lignes in par_devise.items():
        lignes.sort(reverse=True)
        d, net, oi, nom = lignes[0]
        prec = lignes[1][1] if len(lignes) > 1 else None
        historique = [l[1] for l in lignes[:52]]
        percentile = round(100 * sum(1 for v in historique if v <= net) / len(historique)) if len(historique) >= 20 else None
        resultat[devise] = {
            "date": d, "contrat": nom, "net": net, "variation_semaine": None if prec is None else net - prec,
            "net_pct_oi": round(100 * net / oi, 1) if oi else None, "percentile_52s": percentile,
            "semaines": len(historique),
            "extreme": None if percentile is None else ("long" if percentile >= 90 else "short" if percentile <= 10 else None),
        }
    return resultat


def _eia() -> dict:
    cle = os.environ.get("EIA_API_KEY", "").strip()
    rep = requests.get(URL_EIA, headers=UA, timeout=40, params={
        "api_key": cle or "DEMO_KEY", "frequency": "weekly", "data[0]": "value", "facets[series][]": SERIE_EIA,
        "sort[0][column]": "period", "sort[0][direction]": "desc", "offset": 0, "length": 6})
    rep.raise_for_status()
    lignes = [(x["period"], float(x["value"])) for x in rep.json().get("response", {}).get("data", [])
              if x.get("value") not in (None, "")]
    if len(lignes) < 2:
        raise RuntimeError("EIA : moins de deux semaines de données")
    (d, v), (_, v1) = lignes[0], lignes[1]
    v4 = lignes[4][1] if len(lignes) > 4 else None
    return {"date": d, "serie": SERIE_EIA, "libelle": "Stocks de brut US hors réserve stratégique",
            "unite": "millions de barils", "valeur": round(v / 1000, 1),
            "variation_semaine": round((v - v1) / 1000, 1),
            "variation_4_semaines": None if v4 is None else round((v - v4) / 1000, 1),
            "cle": "personnelle" if cle else "démonstration (DEMO_KEY)"}


def _or(cle_fred: str) -> dict:
    rep = requests.get(URL_FRED, timeout=30, params={"series_id": SERIE_OR, "api_key": cle_fred, "file_type": "json",
                                                     "sort_order": "desc", "limit": 15})
    rep.raise_for_status()
    obs = [(o["date"], float(o["value"])) for o in rep.json().get("observations", []) if o.get("value") not in (".", None)]
    if not obs:
        raise RuntimeError("FRED NASDAQQGLDI : aucune observation")
    d, v = obs[0]
    fin = date.fromisoformat(d)
    ref = next(((dd, vv) for dd, vv in obs if (fin - date.fromisoformat(dd)).days >= 7), None)
    return {"date": d, "serie": SERIE_OR, "valeur": v,
            "libelle": "Indice or NASDAQ QGLDI (proxy, pas le cours spot)",
            "variation_7j_pct": None if not ref else round((v / ref[1] - 1) * 100, 2)}


def collecter(config: dict) -> dict:
    """{"cot": {devise: {...}}, "eia": {...}|None, "or": {...}|None, "erreurs": [...]}."""
    resultat: dict = {"cot": {}, "eia": None, "or": None, "erreurs": [], "non_couvert": {"cot": ["CNY"]}}
    for nom, fonction in (("cot", lambda: _cot(date.today())), ("eia", _eia),
                          ("or", lambda: _or(os.environ.get("FRED_API_KEY", "").strip()))):
        try:
            if nom == "or" and not os.environ.get("FRED_API_KEY", "").strip():
                raise RuntimeError("FRED_API_KEY absente")
            resultat[nom] = fonction()
        except Exception as exc:  # noqa: BLE001 — une source en échec n'affecte qu'elle
            erreur = masquer_secrets(f"{nom.upper()} : {exc}")[:200]
            resultat["erreurs"].append(erreur)
            log.warning("Collecte flux — %s", erreur)
    log.info("Collecte flux : COT %d contrat(s), EIA %s, or %s, %d erreur(s)", len(resultat["cot"]),
             "ok" if resultat["eia"] else "absent", "ok" if resultat["or"] else "absent", len(resultat["erreurs"]))
    return resultat
