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
        self.assertIn("non numérique", l["JPY"]["taux_directeur"]["raison"])            # « <1.25% » : jamais deviné
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
        self.assertEqual(set(d["engrenages"]), {"2", "3", "5"})
        self.assertIn("lignes", d["engrenages"]["2"])          # séries absentes : cases n/d, pas d'engrenage entier en échec
        usd = d["engrenages"]["2"]["lignes"][0]["cellules"]
        self.assertIsNone(usd["taux_directeur"]["valeur"])
        self.assertTrue(all("lignes" in d["engrenages"][n] or "instruments" in d["engrenages"][n]
                            or "indisponible" in d["engrenages"][n] for n in d["engrenages"]))


if __name__ == "__main__":
    unittest.main()
