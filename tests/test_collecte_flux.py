"""Collecte COT / EIA / or et leur usage dans les engrenages 5, 7, 8 (réseau simulé)."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from agents import agent_engrenages as ae, collecte_flux as cf  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def reponse(json_):
    return mock.Mock(**{"json.return_value": json_, "raise_for_status.return_value": None})


def lignes_cot(code, nets):
    """nets[0] = semaine la plus récente."""
    d0 = date(2026, 10, 6)
    return [{"cftc_contract_market_code": code, "market_and_exchange_names": "EURO FX - CME",
             "report_date_as_yyyy_mm_dd": f"{(d0 - timedelta(weeks=i)).isoformat()}T00:00:00.000",
             "noncomm_positions_long_all": str(100000 + n), "noncomm_positions_short_all": "100000",
             "open_interest_all": "500000"} for i, n in enumerate(nets)]


class Cot(unittest.TestCase):
    def test_net_variation_percentile_et_extreme(self):
        nets = [-99000, -63000] + list(range(-50000, 50000, 2000))       # le plus bas sur 52 semaines
        with mock.patch("requests.get", return_value=reponse(lignes_cot("099741", nets))):
            r = cf._cot(date(2026, 10, 10))
        eur = r["EUR"]
        self.assertEqual((eur["net"], eur["variation_semaine"], eur["date"]), (-99000, -36000, "2026-10-06"))
        self.assertLessEqual(eur["percentile_52s"], 10)
        self.assertEqual(eur["extreme"], "short")

    def test_historique_trop_court_pas_de_percentile_invente(self):
        with mock.patch("requests.get", return_value=reponse(lignes_cot("097741", [5000, 4000]))):
            jpy = cf._cot(date(2026, 10, 10))["JPY"]
        self.assertIsNone(jpy["percentile_52s"])
        self.assertIsNone(jpy["extreme"])


class Collecte(unittest.TestCase):
    def test_une_source_en_echec_n_affecte_qu_elle(self):
        def faux_get(url, **kw):
            if "cftc" in url:
                raise ConnectionError("CFTC hors ligne")
            if "eia" in url:
                return reponse({"response": {"data": [{"period": "2026-10-02", "value": "424134"},
                                                      {"period": "2026-09-25", "value": "427320"}]}})
            return reponse({"observations": [{"date": "2026-10-09", "value": "2554.5"},
                                             {"date": "2026-10-01", "value": "2533.5"}]})
        with mock.patch.dict("os.environ", {"FRED_API_KEY": "k", "EIA_API_KEY": ""}), \
                mock.patch("requests.get", side_effect=faux_get):
            r = cf.collecter({})
        self.assertEqual(r["cot"], {})
        self.assertTrue(any("CFTC hors ligne" in e for e in r["erreurs"]))
        self.assertEqual((r["eia"]["valeur"], r["eia"]["variation_semaine"], r["eia"]["cle"]),
                         (424.1, -3.2, "démonstration (DEMO_KEY)"))
        self.assertIn("pas le cours spot", r["or"]["libelle"])
        self.assertEqual(r["or"]["variation_7j_pct"], 0.83)


FLUX = {"cot": {"EUR": {"date": "2026-10-06", "net": -99000, "variation_semaine": -36000, "percentile_52s": 2,
                        "extreme": "short"},
                "JPY": {"date": "2026-10-06", "net": 62000, "variation_semaine": 6800, "percentile_52s": 92,
                        "extreme": "long"}},
        "eia": {"date": "2026-10-02", "serie": "WCESTUS1", "libelle": "Stocks de brut US hors réserve stratégique",
                "valeur": 424.1, "variation_semaine": -3.2, "variation_4_semaines": 0.1},
        "or": {"date": "2026-10-09", "serie": "NASDAQQGLDI", "valeur": 2554.5, "variation_7j_pct": 0.8,
               "libelle": "Indice or NASDAQ QGLDI (proxy, pas le cours spot)"}, "erreurs": []}


def signaux(flux):
    donnees = {"macro": {"series": {}}, "technique": {}, "calendrier": [], "news": []}
    return ae.signaux(CONFIG, donnees, {"flux": flux}, [], "neutre", {}, ae._Catalogue([]))


class Engrenages(unittest.TestCase):
    def test_cot_eia_or_sources_et_extremes(self):
        s = signaux(FLUX)
        textes7 = " ".join(d["texte"] for d in s[7]["donnees"])
        self.assertIn("EUR (short extrême)", textes7)
        self.assertIn("Non couvert : CNY", textes7)
        self.assertTrue(all(d["source_id"] for d in s[7]["donnees"]))
        self.assertIn("-3.2 M sur la semaine", " ".join(d["texte"] for d in s[8]["donnees"]))
        self.assertIn("pas le cours spot", " ".join(d["texte"] for d in s[5]["donnees"]))
        self.assertEqual((s[5]["indisponibles"], s[7]["indisponibles"], s[8]["indisponibles"]), ([], [], []))

    def test_source_absente_signalee_indisponible_jamais_inventee(self):
        s = signaux({"cot": {}, "eia": None, "or": None, "erreurs": ["EIA : HTTP 403"]})
        self.assertTrue(s[7]["indisponibles"][0].startswith("positionnement CFTC"))
        self.assertIn("HTTP 403", s[8]["indisponibles"][0])
        self.assertFalse(any("COT" in d["texte"] for d in s[7]["donnees"]))


if __name__ == "__main__":
    unittest.main()
