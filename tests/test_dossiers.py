"""Dossiers chiffrés des engrenages (percentiles 5 ans, variations, corrélations). Sans réseau."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from agents import collecte_historiques as ch  # noqa: E402
from core import dossiers as ds  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
FIN = date.today()


def quotidien(valeurs_fn, jours=5 * 366):
    return [((FIN - timedelta(days=jours - i)).isoformat(), valeurs_fn(i)) for i in range(jours + 1)]


class Calculs(unittest.TestCase):
    def test_variations_en_points_de_base_pour_un_taux(self):
        pts = quotidien(lambda i: 3.0) [:-30] + [((FIN - timedelta(days=29 - k)).isoformat(), 3.0 + 0.01 * k) for k in range(30)]
        c = ds.stats(pts, "%", "FRED (test)")
        self.assertEqual(c["var_1s"], 7.0)            # +0,07 point sur 7 jours = +7 pb
        self.assertEqual(c["var_4s"], 28.0)

    def test_percentile_sur_5_ans_et_extremes(self):
        pts = quotidien(lambda i: float(i))           # série croissante : la dernière valeur est le maximum
        c = ds.stats(pts, "niveau", "test")
        self.assertEqual(c["percentile_5a"], 100)
        p, n, raison = ds.percentile(pts, -1.0, pts[-1][0])
        self.assertEqual((p, raison), (0, None))
        self.assertGreaterEqual(n, 250)                # échantillonnage hebdomadaire

    def test_historique_court_pas_de_percentile_invente(self):
        pts = quotidien(lambda i: 1.0, jours=200)
        c = ds.stats(pts, "%", "test")
        self.assertIsNone(c["percentile_5a"])
        self.assertIn("historique insuffisant", c["raison_percentile"])

    def test_serie_mensuelle_trop_ancienne(self):
        pts = [(f"{a}-{m:02d}-01", 1.0) for a in range(2019, 2024) for m in range(1, 13)]
        c = ds.stats(pts, "%", "OCDE", "mensuel")
        self.assertIsNone(c["percentile_5a"])
        self.assertIn("trop ancienne", c["raison_percentile"])

    def test_difference_alignee_et_glissement_par_mois(self):
        a = [("2026-10-01", 3.0), ("2026-10-02", 3.1), ("2026-10-05", 3.2)]
        b = [("2026-10-01", 4.0), ("2026-10-05", 4.5)]
        self.assertEqual(ds.difference(a, b), [("2026-10-01", -100.0), ("2026-10-02", -90.0), ("2026-10-05", -130.0)])
        idx = [("2025-08-01", 100.0), ("2025-10-01", 101.0), ("2026-08-01", 102.45), ("2026-10-01", 103.0)]
        self.assertEqual(ds.glissement_annuel(idx), [("2026-08-01", 2.45), ("2026-10-01", 1.98)])   # mois manquant ignoré

    def test_compactage_quotidien_recent_et_hebdomadaire_ancien(self):
        pts = quotidien(lambda i: float(i))
        comp = ch.compacter(pts, "quotidien", FIN)
        recents = [p for p in comp if p[0] >= (FIN - timedelta(days=ch.JOURS_QUOTIDIENS)).isoformat()]
        self.assertEqual(len(recents), ch.JOURS_QUOTIDIENS + 1)
        self.assertLess(len(comp), 600)
        self.assertEqual(comp[-1], [pts[-1][0], pts[-1][1]])


def historiques():
    taux = lambda base: quotidien(lambda i: base + (i % 50) / 100)
    return {"series": {
        "USD_taux_effectif": {"source": "FRED (DFF)", "frequence": "quotidien", "points": taux(3.5)},
        "USD_2a": {"source": "FRED (DGS2)", "frequence": "quotidien", "points": taux(4.0)},
        "USD_10a": {"source": "FRED (DGS10)", "frequence": "quotidien", "points": taux(4.5)},
        "EUR_2a": {"source": "Bundesbank", "frequence": "quotidien", "points": taux(2.5)},
        "EUR_10a": {"source": "Bundesbank", "frequence": "quotidien", "points": taux(3.0)},
        "vix": {"source": "FRED (VIXCLS)", "frequence": "quotidien", "points": quotidien(lambda i: 15 + (i % 30))},
    }, "erreurs": []}


REGISTRE = {"cases": {
    "USD|taux_directeur": {"actuel": {"valeur": "4.00%", "date_pub": "2026-09-16"}, "prevision": {"date_pub": "2026-10-28"}},
    "EUR|taux_directeur": {"actuel": {"valeur": "2.65%", "date_pub": "2026-09-10"}, "precedent": {"valeur": "2.40%"}},
    "EUR|cpi_core": {"actuel": {"valeur": "2.5%", "date_pub": "2026-10-02"}},
    "JPY|taux_directeur": {"actuel": {"valeur": "<1.25%", "date_pub": "2026-09-18"}}}}


class Engrenages(unittest.TestCase):
    def test_engrenage_2_cellules_et_raisons(self):
        e = ds.engrenage_2(historiques(), REGISTRE, CONFIG)
        l = {x["devise"]: x["cellules"] for x in e["lignes"]}
        self.assertEqual(l["EUR"]["taux_reel"]["valeur"], 0.15)                       # 2,65 − 2,5
        self.assertIsNotNone(l["EUR"]["ecart_2a_us"]["percentile_5a"])
        self.assertTrue(l["EUR"]["ecart_2a_us"]["serie_90j"])
        self.assertIn("indisponible", l["JPY"]["taux_directeur"]["raison"])          # sans série BoJ : n/d, jamais « <1.25% » deviné
        self.assertIn("pas de rendement 2 ans", l["GBP"]["ecart_2a_us"]["raison"])
        self.assertEqual(l["USD"]["prochaine_reunion"]["texte"], "2026-10-28")
        self.assertIn("borne haute", l["USD"]["taux_directeur"]["note"])

    def test_engrenage_5_instruments_et_correlations(self):
        technique = {"graphiques": {"EUR": {"dates": [d for d, _ in historiques()["series"]["vix"]["points"][-90:]],
                                            "clotures": [1 + (k % 7) / 100 for k in range(90)]}}}
        e = ds.engrenage_5(historiques(), technique)
        vix = next(x for x in e["instruments"] if x["id"] == "vix")["cellule"]
        self.assertIsNotNone(vix["percentile_5a"])
        self.assertEqual(next(x for x in e["instruments"] if x["id"] == "wti")["cellule"]["raison"], "série indisponible")
        self.assertIn("VIX", e["correlations"]["matrice"]["EUR"])
        self.assertIn("pas le cours spot", " ".join(e["notes"]))

    def test_construire_isole_un_engrenage_en_echec(self):
        d = ds.construire({"series": {}}, {"cases": {}}, {}, CONFIG)
        self.assertEqual(set(d["engrenages"]), {str(n) for n in range(1, 9)})
        self.assertIn("lignes", d["engrenages"]["2"])          # séries absentes : cases n/d, pas d'engrenage entier en échec
        usd = d["engrenages"]["2"]["lignes"][0]["cellules"]
        self.assertIsNone(usd["taux_directeur"]["valeur"])
        self.assertTrue(all(any(k in d["engrenages"][n] for k in ("lignes", "instruments", "evenements", "indicateurs"))
                            or "indisponible" in d["engrenages"][n] for n in d["engrenages"]))




class Palier2(unittest.TestCase):
    def test_jpy_taux_effectif_boj_et_2_ans_manuel(self):
        h = historiques()
        h["series"]["JPY_taux_effectif"] = {"source": "BoJ", "frequence": "quotidien", "points": quotidien(lambda i: 1.0 + i / 10000)}
        config = {**CONFIG, "valeurs_manuelles": {"rendement_2a": {
            "GBP": {"valeur": 4.1, "date": date.today().isoformat(), "source": "BoE yield curves"},
            "AUD": {"valeur": None, "date": None, "source": "RBA F2"}}}}
        l = {x["devise"]: x["cellules"] for x in ds.engrenage_2(h, REGISTRE, config)["lignes"]}
        self.assertIsNotNone(l["JPY"]["taux_directeur"]["valeur"])                  # BoJ, plus de « <1.25% » illisible
        self.assertIn("une borne", l["JPY"]["taux_directeur"]["note"])
        self.assertEqual(l["GBP"]["taux_2a"]["valeur"], 4.1)
        self.assertIn("saisie manuelle", l["GBP"]["taux_2a"]["source"])
        self.assertIn("non renseignée", l["AUD"]["taux_2a"]["raison"])                # jamais devinée

    def test_engrenages_4_6_7_8_et_1(self):
        h = historiques()
        h["series"]["eia_stocks"] = {"source": "EIA", "frequence": "hebdomadaire",
                                     "points": [((FIN - timedelta(weeks=k)).isoformat(), 420000.0 + (k % 52) * 100) for k in range(320, -1, -1)]}
        h["series"]["USD_dette_pib"] = {"source": "FRED", "frequence": "trimestriel", "points": [["2025-10-01", 120.0], ["2026-01-01", 122.6]]}
        news = {"articles": [{"titre": "Attack on oil tanker near Hormuz", "source": "rss", "date": "2026-10-10"},
                             {"titre": "Italy budget deficit widens", "source": "rss", "date": "2026-10-10"},
                             {"titre": "Celebrity wedding in Paris", "source": "rss", "date": "2026-10-10"}]}
        flux = {"cot": {"EUR": {"date": "2026-10-06", "net": -99000, "variation_semaine": -36000, "percentile_52s": 2,
                                "extreme": "short", "historique": [["2026-09-29", -63000], ["2026-10-06", -99000]]}}}
        d = ds.construire(h, REGISTRE, {}, CONFIG, None, flux, news, None)
        e4, e6, e7, e8 = (d["engrenages"][k] for k in ("4", "6", "7", "8"))
        self.assertEqual(e4["lignes"][0]["cellules"]["dette_pib"]["valeur"], 122.6)
        self.assertEqual([a["titre"] for a in e4["actualites"]], ["Italy budget deficit widens"])
        self.assertEqual([ev["canal"] for ev in e6["evenements"]], ["energie"])   # sans canal identifiable : non retenu
        self.assertEqual(e7["lignes"][1]["cellules"]["cot"]["percentile_52s"], 2)
        self.assertIn("non couvert", e7["lignes"][8]["cellules"]["cot"]["raison"])
        stocks = e8["instruments"][0]["cellule"]
        self.assertIsNotNone(stocks["ecart_moyenne_5a"])
        self.assertIn("termes de l'échange", e8["termes_echange"]["raison"])
        self.assertIn("indisponible", d["engrenages"]["1"])                          # thème : attend le rapport
        self.assertTrue(all(len(d["engrenages"][k]["graphiques"]) == 2 for k in ("2", "3", "4", "5", "7", "8")))


if __name__ == "__main__":
    unittest.main()
