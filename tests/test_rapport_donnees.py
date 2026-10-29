"""Rapport du jour, étape 1 : nouvelles données (FRED, Twelve Data, TreasuryDirect, ALFRED), statuts des chiffres."""
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from agents import collecte_historiques as ch
from core import agenda

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
JEUDI = datetime(2026, 10, 29, 9, tzinfo=timezone.utc)


def test_nouvelles_series_declarees_et_etf_libelles():
    for nom, sid in (("USD_30a", "DGS30"), ("USD_reel_10a", "DFII10"), ("USD_point_mort_10a", "T10YIE"),
                     ("USD_spread_hy", "BAMLH0A0HYM2"), ("cuivre_mensuel", "PCOPPUSDM"), ("FRA_10a_mensuel", "IRLTLT01FRM156N")):
        assert ch.SERIES_FRED[nom][0] == sid
    assert ch.SERIES_FRED["cuivre_mensuel"][3] == "mensuel" and "mensuel" in ch.SERIES_FRED["FRA_10a_mensuel"][1]
    for nom in ("nasdaq_qqq", "japon_ewj", "allemagne_ewg"):
        assert "ETF" in ch.SERIES_TWELVE[nom][1] and "pas l'indice" in ch.SERIES_TWELVE[nom][1]
    assert ch.SERIES_TWELVE["or_xau"][0] == "XAU/USD"


def test_millesimes_alfred_derniere_et_avant_derniere():
    obs = [{"date": "2026-08-01", "realtime_start": "2026-09-05", "value": "159075"},
           {"date": "2026-08-01", "realtime_start": "2026-10-02", "value": "159015"},
           {"date": "2026-09-01", "realtime_start": "2026-10-02", "value": "159140"}]
    m = agenda.analyser_millesimes(obs)
    assert m["avant_derniere"]["revise"] and "159075 puis 159015" in m["avant_derniere"]["detail"]
    assert not m["derniere"]["revise"]


def test_statuts_estimation_provisoire_revise_confirme_et_adjudications():
    ff = json.dumps([{"title": "Advance GDP q/q", "country": "USD", "date": "2026-10-29T08:30:00-04:00", "impact": "High",
                      "forecast": "3.2%", "previous": "1.5%"},
                     {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-11-06T08:30:00-05:00", "impact": "High",
                      "forecast": "60K", "previous": "29K"}])
    mois = [{"devise": "USD", "nom": "Advance GDP q/q", "impact": "High", "reel": "2.9%", "prevision": "3.2%", "precedent": "1.5%",
             "dateline": int(datetime(2026, 10, 29, 12, 30, tzinfo=timezone.utc).timestamp())}]
    rev = {"series": {"GDP": {"avant_derniere": {"revise": True, "detail": "période 2026-04-01 : 1.4 puis 1.5 (ALFRED)"},
                              "derniere": {"revise": False}},
                      "PAYEMS": {"derniere": {"revise": False}, "avant_derniere": {"revise": True, "detail": "x"}}}}
    tresor = {"adjudications": [{"type": "Note", "duree": "10-Year", "date": "2026-11-03", "heure": "1:00 PM"},
                                {"type": "Bill", "duree": "13-Week", "date": "2026-11-02", "heure": "11:30 AM"}], "collecte_le": "2026-10-29"}
    a = agenda.calculer(ff, [], {}, CONFIG, JEUDI, mois=mois, revisions=rev, tresor=tresor)
    evts = {e["evenement_en"]: e for j in a["jours"] for e in j["evenements"]}
    pib = evts["Advance GDP q/q"]
    assert pib["statuts"] == {"consensus": "estimation", "publie": "provisoire", "precedent": "révisé"} and "ALFRED" in pib["revision_detail"]
    assert evts["Non-Farm Employment Change"]["statuts"]["precedent"] == "confirmé"   # à venir : dernière période, non révisée
    adj = [e for e in evts.values() if e["type"] == "Adjudication"]
    assert len(adj) == 1 and adj[0]["heure_paris"] == "19:00" and adj[0]["impact"] == "moyen" and "10 ans" in adj[0]["evenement"]
