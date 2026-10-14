"""Palier 2 de la refonte : tuiles des dossiers 2, 3 et 5 et carte de chaleur des corrélations (sans réseau)."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

import yaml  # noqa: E402

from core import dossiers, tuiles as tu  # noqa: E402

FIN = date.today() - timedelta(days=1)


def serie(jours, f):
    return [[(FIN - timedelta(days=jours - i)).isoformat(), f(i)] for i in range(jours + 1)]


HIST = {"series": {k: {"points": serie(6 * 365, f), "frequence": "quotidien"} for k, f in {
    "USD_2a": lambda i: 3 + i / 1000, "USD_taux_effectif": lambda i: 3.5, "USD_10a": lambda i: 4 + i / 2000,
    "EUR_2a": lambda i: 2 + (i % 50) / 100, "JPY_taux_effectif": lambda i: 0.5, "JPY_2a": lambda i: 1,
    "GBP_taux_effectif": lambda i: 3.7, "vix": lambda i: 15 + (i % 30) / 3, "sp500": lambda i: 4000 + i,
    "dollar_large": lambda i: 120, "indice_or": lambda i: 2000 + i / 3, "brent": lambda i: 80, "wti": lambda i: 75}.items()}}


class Tuile(unittest.TestCase):
    def test_tuile_complete_depuis_une_cellule(self):
        points = [(d, v) for d, v in HIST["series"]["USD_2a"]["points"]]
        cel = dossiers.stats(points, "%", "FRED (DGS2)")
        t = tu.tuile("us2a", "2 ans US", cel, tu._fenetre(HIST["series"]["USD_2a"]["points"], 30))
        self.assertEqual(t["texte"], tu.texte_valeur(cel["valeur"], "%"))
        self.assertEqual(t["variation"]["unite"], "pb")                     # taux : variation en points de base
        self.assertEqual(t["variation"]["periode"], "4 semaines")
        self.assertEqual(t["percentile_5a"], 100)
        self.assertEqual(len(t["courbe"]["points"]), 31)
        self.assertEqual(t["age_jours"], 1)

    def test_valeur_absente_nd_avec_raison_jamais_inventee(self):
        t = tu.tuile("x", "X", {"valeur": None, "raison": "pas de rendement 2 ans gratuit"})
        self.assertIsNone(t["texte"])
        self.assertEqual(t["raison"], "pas de rendement 2 ans gratuit")
        self.assertIsNone(t["variation"])
        self.assertIn("historique", t["courbe"]["raison"])

    def test_tendance_3_mois_sert_de_variation(self):
        t = tu.tuile("c", "Chômage", {"valeur": 4.9, "unite": "%", "tendance_3m": 0.2})
        self.assertEqual(t["variation"]["texte"], "+0,20 pt sur 3 mois")

    def test_dossier_2_tuiles_et_decisions_sans_courbe(self):
        registre = {"cases": {"EUR|taux_directeur": {"actuel": {"valeur": "2.65%", "date_pub": "2026-09-10"}},
                              "AUD|taux_directeur": {"actuel": {"valeur": "4.60%", "date_pub": "2026-09-29"}}}}
        e = dossiers.engrenage_2(HIST, registre, {"tableau_macro": {}})
        t = {x["id"]: x for x in tu.tuiles_2(e, HIST)}
        self.assertTrue(8 <= len(t) <= 12)
        self.assertEqual(t["us2a_dir"]["unite"], "pb")
        self.assertGreater(len(t["us2a_dir"]["courbe"]["points"]), 20)
        self.assertEqual(t["bce"]["texte"], "2,65 %")
        self.assertIn("décision", t["bce"]["courbe"]["raison"])

    def test_dossier_5_tuiles_et_correlations_avec_variation(self):
        e = {"instruments": [{"id": "vix", "cellule": {"valeur": 15.2, "unite": "niveau", "var_4s": -11.0, "date": FIN.isoformat()}}],
             "correlations": {"matrice": {"AUD": {"S&P 500": 0.64, "VIX": -0.6}, "JPY": {"VIX": -0.44}},
                              "matrice_precedente": {"AUD": {"S&P 500": 0.48}, "JPY": {"VIX": None}},
                              "seances": 30, "derniere_seance": FIN.isoformat(), "source": "calcul"}}
        t = {x["id"]: x for x in tu.tuiles_5(e, HIST)}
        self.assertEqual(t["vix"]["variation"]["texte"], "−11,00 % sur 4 semaines")
        self.assertEqual(t["corr_aud_s&p_500"]["texte"], "+0,64")
        self.assertEqual(t["corr_aud_s&p_500"]["variation"]["valeur"], 0.16)
        self.assertIsNone(t["corr_jpy_vix"]["variation"])                    # pas de fenêtre précédente : pas de variation
        self.assertIsNone(t["brent"]["texte"])                               # instrument absent du dossier : n/d
        m = tu.matrice_chaleur(e)
        self.assertEqual(m["colonnes"], ["VIX", "S&P 500", "Brent", "Or (proxy)", "10 ans US"])
        aud = next(l for l in m["lignes"] if l["devise"] == "AUD")
        self.assertEqual(aud["valeurs"][:2], [-0.6, 0.64])
        cny = next(l for l in m["lignes"] if l["devise"] == "CNY")
        self.assertEqual(cny["raison"], "série de force indisponible")


class Construire(unittest.TestCase):
    def test_tuiles_et_chaleur_dans_dossiers_json_sans_casser_le_reste(self):
        config = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
        sortie = dossiers.construire(HIST, {"cases": {}}, {}, config)
        for n in ("2", "3", "5"):
            self.assertIn("tuiles", sortie["engrenages"][n], n)
        self.assertIn("matrice_chaleur", sortie["engrenages"]["5"])
        self.assertIn("lignes", sortie["engrenages"]["2"])                    # tableaux du palier précédent intacts
        self.assertIn("graphiques", sortie["engrenages"]["5"])


if __name__ == "__main__":
    unittest.main()
