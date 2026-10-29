"""Lot Verrouillage, point 7 : valeurs publiées par les instituts officiels (ONS, Statistique Canada, Eurostat)."""
from pathlib import Path
from unittest import mock

import yaml

from agents import collecte_officielles as co
from core import registre_macro as rm

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def _rep(j):
    return mock.Mock(json=mock.Mock(return_value=j), raise_for_status=mock.Mock())


def test_lecture_des_trois_api_sans_reseau():
    s = mock.Mock()
    s.get.side_effect = lambda url, **k: _rep(
        {"months": [{"year": "2026", "month": "SEP", "value": "3.5", "date": "2026 SEP"}],
         "description": {"releaseDate": "2026-10-20T23:00:00.000Z"}} if "ons.gov.uk" in url else
        {"value": {"1": 6.4}, "updated": "2026-10-21T11:00:00+0200",
         "dimension": {"time": {"category": {"index": {"2026-08": 0, "2026-09": 1, "2026-10": 2}}}}})
    s.post.return_value = _rep([{"object": {"vectorDataPoint": [{"refPer": "2026-08-01", "value": 169.4},
                                                                {"refPer": "2026-09-01", "value": 170.0, "releaseTime": "2026-10-19T08:30"}]}}])
    cfg = {"publications_officielles": {"series": [
        {"devise": "GBP", "indicateur": "cpi", "source": "ons", "chemin": "x", "libelle": "ONS (D7G7)"},
        {"devise": "CAD", "indicateur": "cpi", "source": "statcan", "vecteur": 41690973, "calcul": "mm", "libelle": "StatCan"},
        {"devise": "EUR", "indicateur": "chomage", "source": "eurostat", "jeu": "une_rt_m", "filtres": {"geo": "EA21"}, "libelle": "Eurostat"}]}}
    v = co.collecter(cfg, session=s)["valeurs"]
    assert v["GBP|cpi"] == {"valeur": 3.5, "periode": "2026-09", "publie_le": "2026-10-21", "source": "ONS (D7G7)", "unite": "%"}
    assert v["CAD|cpi"]["valeur"] == 0.4 and v["CAD|cpi"]["publie_le"] == "2026-10-19"      # 170,0 / 169,4 − 1
    assert v["EUR|chomage"]["valeur"] == 6.4 and v["EUR|chomage"]["periode"] == "2026-09"   # dernière période renseignée


def test_confirme_comble_ou_signale_un_ecart():
    reg = {"cases": {rm.cle("cpi", "GBP"): {"actuel": {"valeur": "3.5%", "valeur_num": 3.5, "date_pub": "2026-10-21"}},
                     rm.cle("chomage", "GBP"): {"actuel": {"valeur": "4.9%", "valeur_num": 4.9, "date_pub": "2026-10-20"}},
                     rm.cle("pib", "GBP"): {"statut": "a_initialiser"},
                     rm.cle("cpi", "CAD"): {"actuel": {"valeur": "0.2%", "valeur_num": 0.2, "date_pub": "2026-11-18"}}}}
    off = {"valeurs": {"GBP|cpi": {"valeur": 3.5, "periode": "2026-09", "publie_le": "2026-10-21", "source": "ONS (D7G7)"},
                       "GBP|chomage": {"valeur": 4.7, "periode": "2026-07", "publie_le": "2026-10-19", "source": "ONS (MGSX)"},
                       "GBP|pib": {"valeur": 0.5, "periode": "2026-Q2", "publie_le": "2026-09-29", "source": "ONS (IHYQ)"},
                       "CAD|cpi": {"valeur": 0.1, "periode": "2026-09", "publie_le": "2026-10-19", "source": "StatCan"}}}
    b = rm.integrer_officielles(reg, off)
    assert b["confirmees"] == 1 and b["comblees"] == 1 and len(b["ecarts"]) == 1 and "4.9%" in b["ecarts"][0]
    assert reg["cases"][rm.cle("cpi", "GBP")]["actuel"]["statut_valeur"] == "confirmé"
    assert "confirmé par ONS (D7G7)" in rm.source_cellule(reg["cases"][rm.cle("cpi", "GBP")])
    pib = reg["cases"][rm.cle("pib", "GBP")]["actuel"]
    assert pib["valeur"] == "0.5%" and pib["origine"] == "officielle" and pib["source"] == "ONS (IHYQ)"
    assert reg["cases"][rm.cle("cpi", "CAD")]["actuel"]["valeur"] == "0.2%"      # ForexFactory plus récent : inchangé


def test_config_licite_et_interrupteur():
    assert CONFIG["tableau_macro"]["forexfactory"]["page_mois"] is True
    sources = {s["source"] for s in CONFIG["publications_officielles"]["series"]}
    assert sources == {"ons", "statcan", "eurostat"}
    ids = {s["id"] for s in CONFIG["sources"]}
    assert "officielles" in ids and "ff_mois" in ids
