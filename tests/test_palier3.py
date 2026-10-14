"""Corrections avant le palier 3 (taux réel, BCE, corrélations 5 ans) et palier 3 (dossiers 1, 4, 6, 7, 8). Sans réseau."""
import json
import math
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from core import complements as co, correlations as cr, dossiers, tuiles as tu  # noqa: E402

FIN = date.today() - timedelta(days=1)


def jours(n, f):
    return [((FIN - timedelta(days=n - i)).isoformat(), f(i)) for i in range(n + 1)]


class CorrelationsCinqAns(unittest.TestCase):
    def setUp(self):
        n = 5 * 365 + 40
        bruit = [math.sin(i * 1.7) + math.cos(i * 0.31) for i in range(n + 1)]
        prix = [100.0]
        for b in bruit[1:]:
            prix.append(prix[-1] * (1 + b / 200))
        self.bruts = {"sp500": jours(n, lambda i: prix[i]),
                      "FX_AUD": jours(n, lambda i: prix[i] / 150),            # bouge exactement avec le S&P
                      "FX_JPY": jours(n, lambda i: 15000 / prix[i]),          # coté en JPY par USD : force = 1/x
                      "vix": jours(n, lambda i: 20 + bruit[i])}

    def test_correlation_glissante_valeur_percentile_et_courbe(self):
        c = cr.calculer(self.bruts, date.today())
        aud = c["paires"]["AUD|S&P 500"]
        self.assertEqual(aud["valeur"], 1.0)
        self.assertEqual(c["paires"]["JPY|S&P 500"]["valeur"], 1.0)        # inversion de la cotation appliquée
        self.assertGreater(aud["n_5a"], 1000)
        self.assertIsNotNone(aud["percentile_5a"])
        self.assertTrue(80 <= len(aud["courbe"]) <= 121)
        self.assertIsNotNone(aud["precedente"])
        self.assertIn("EUR / S&P 500 : série de change indisponible", c["absentes"])

    def test_historique_trop_court_percentile_non_calcule(self):
        court = {k: v[-80:] for k, v in self.bruts.items()}
        aud = cr.calculer(court, date.today())["paires"]["AUD|S&P 500"]
        self.assertIsNone(aud["percentile_5a"])
        self.assertIn("moins de", aud["raison_percentile"])

    def test_tuile_et_matrice_utilisent_les_correlations_5_ans(self):
        h = {"correlations_5a": cr.calculer(self.bruts, date.today())}
        t = tu._tuile_correlation({}, h, "AUD", "S&P 500", "Corr", "lecture")
        self.assertEqual(t["texte"], "+1,00")
        self.assertIsNotNone(t["percentile_5a"])
        self.assertGreater(len(t["courbe"]["points"]), 50)
        m = tu.matrice_chaleur({}, h)
        self.assertTrue(m["percentile_5a"])
        aud = next(l for l in m["lignes"] if l["devise"] == "AUD")
        self.assertEqual(aud["valeurs"][1], 1.0)
        self.assertIsNotNone(aud["percentiles"][1])
        self.assertFalse(tu.matrice_chaleur({}, {})["percentile_5a"])         # repli dit explicitement


class TauxReelEtBce(unittest.TestCase):
    def test_taux_reel_us_mensuel_sur_cinq_ans(self):
        cpi = [(f"{2020 + m // 12}-{m % 12 + 1:02d}-01", 100 * 1.03 ** (m / 12)) for m in range(76)]
        dff = jours(6 * 365, lambda i: 4.0)
        h = {"series": {"USD_core_indice": {"points": cpi}, "USD_taux_effectif": {"points": dff}}}
        r = dossiers.taux_reel_us(h)
        self.assertGreater(len(r), 50)
        self.assertAlmostEqual(r[-1][1], 1.0, places=1)                       # 4 % − 3 % d'inflation

    def test_bce_taux_de_depot_ecbdfr(self):
        h = {"series": {"EUR_taux_depot": {"points": jours(6 * 365, lambda i: 2.5 if i > 100 else 4.0), "frequence": "quotidien"}}}
        registre = {"cases": {"EUR|taux_directeur": {"actuel": {"valeur": "2.65%", "date_pub": "2026-09-10"}}}}
        e = dossiers.engrenage_2(h, registre, {"tableau_macro": {}})
        eur = next(l for l in e["lignes"] if l["devise"] == "EUR")["cellules"]["taux_directeur"]
        self.assertEqual(eur["valeur"], 2.5)
        self.assertIn("ECBDFR", eur["source"])
        self.assertIn("refinancement", eur["note"])
        self.assertIsNotNone(eur["percentile_5a"])


class Theme(unittest.TestCase):
    def test_duree_du_theme_et_variation_sur_archives_trouees(self):
        archives = [{"date": "2026-09-21", "biais": "risk_on", "scores": {"USD": 50}},
                    {"date": "2026-09-30", "biais": "risk_off", "scores": {"USD": 60}},
                    {"date": "2026-10-14", "biais": "risk_off", "scores": {"USD": 84}}]
        self.assertEqual(co.duree_theme_semaines(archives, "risk_off"), (2, "2026-09-30"))
        self.assertEqual(co.duree_theme_semaines(archives, None), (None, None))
        v = co._variation_points([[a["date"], a["scores"]["USD"]] for a in archives], 28, "pts")
        self.assertEqual(v["valeur"], 34)
        self.assertIn("23 jours (depuis le 21/09)", v["texte"])               # période réelle dite
        self.assertIsNone(co._variation_points([["2026-10-10", 1], ["2026-10-14", 2]], 28, "pts"))

    def test_archives_et_complements_du_dossier_1(self):
        dossier = Path(tempfile.mkdtemp())
        for k, (usd, cad) in enumerate(((70, 30), (75, 25), (80, 20))):
            jour = (date.today() - timedelta(days=21 - 7 * k)).isoformat()
            (dossier / f"{jour}.json").write_text(json.dumps({"devises": [{"devise": "USD", "score_confluence": usd},
                                                                         {"devise": "CAD", "score_confluence": cad}],
                                                              "synthese_globale": {"biais_macro_global": "risk_off"}}), encoding="utf-8")
        rapport = {"meta": {"date_rapport": date.today().isoformat()},
                   "devises": [{"devise": "USD", "score_confluence": 84}, {"devise": "CAD", "score_confluence": 16},
                               {"devise": "AUD", "score_confluence": 56}],
                   "synthese_globale": {"biais_macro_global": "risk_off", "engrenages": {"engrenages": [
                       {"numero": 1, "direction": {"dollar": "haussier", "risque": "risk_off"}},
                       {"numero": 2, "direction": {"dollar": "haussier"}, "conviction": {"niveau": "faible"}}]}}}
        e = {"numero": 1}
        co.complements_1(e, rapport, {"series": {}}, dossier, {})
        t = {x["id"]: x for x in e["tuiles"]}
        self.assertEqual(t["score_usd"]["texte"], "84")
        self.assertEqual(len(t["score_usd"]["courbe"]["points"]), 4)
        self.assertEqual(t["ecart_max"]["valeur"], 68)
        self.assertEqual(t["coherence"]["texte"], "1 sur 1 évaluable")
        self.assertEqual(t["duree_theme"]["texte"], "3 sem.")
        self.assertIsNone(t["vix"]["texte"])                                   # série absente : n/d avec raison
        self.assertEqual(e["suivi_theme"]["lignes"][0]["accord"], "oui")
        self.assertEqual(e["graphiques"][1]["barres"][0], {"nom": "USD", "valeur": 84})


class AutresDossiers(unittest.TestCase):
    def test_rsi_de_wilder(self):
        clotures = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        r = co.rsi_serie([f"d{i}" for i in range(len(clotures))], clotures)
        self.assertEqual(len(r), 1)
        self.assertAlmostEqual(r[0][1], 70.5, delta=0.6)                       # exemple classique de Wilder

    def test_balances_converties_en_usd_sauf_cny(self):
        h = {"series": {"FX_JPY": {"points": [["2026-10-09", 150.0]]}, "FX_EUR": {"points": [["2026-10-09", 1.10]]}}}
        self.assertEqual(co.balance_en_milliards_usd("JPY", "-0.84T", h), (-5.6, None))
        self.assertEqual(co.balance_en_milliards_usd("EUR", "5.0B", h), (5.5, None))
        self.assertEqual(co.balance_en_milliards_usd("USD", "-105.6B", h), (-105.6, None))
        v, r = co.balance_en_milliards_usd("CNY", "906B", h)
        self.assertIsNone(v)
        self.assertIn("non précisée", r)
        self.assertIn("indisponible", co.balance_en_milliards_usd("CAD", "4.2B", h)[1])

    def test_dossier_budgetaire_pays_et_mecanisme(self):
        lignes = co.dossier_budgetaire([{"titre": "Japan JGB auction draws weak demand", "source": "x", "date": "2026-10-14"},
                                        {"titre": "Budget talks stall", "source": "y", "date": "2026-10-14"}])
        self.assertEqual(lignes[0]["pays"], "JPY")
        self.assertIn("offre de titres", lignes[0]["mecanisme"])
        self.assertEqual(lignes[1]["pays"], "non identifié")
        self.assertIn("déficit", lignes[1]["mecanisme"])

    def test_ecart_italie_allemagne_mensuel(self):
        mois = [f"2025-{m:02d}-01" for m in range(1, 13)] + [f"2026-{m:02d}-01" for m in range(1, 9)]
        h = {"series": {"ITA_10a_mensuel": {"points": [[d, 4.0] for d in mois]},
                        "DEU_10a_mensuel": {"points": [[d, 3.2] for d in mois]}}}
        e = {"lignes": []}
        co.complements_4(e, h)
        t = next(x for x in e["tuiles"] if x["id"] == "btp_bund")
        self.assertEqual(t["texte"], "+80 pb")
        self.assertEqual(t["variation"]["texte"], "0 pb sur 3 mois")
        self.assertEqual(len(t["courbe"]["points"]), 13)

    def test_reaction_geopolitique_sur_la_derniere_seance(self):
        h = {"series": {"brent": {"points": [["2026-10-05", 100.0], ["2026-10-06", 102.0]]}}}
        e = {"graphiques": [{"type": "serie"}, {"type": "barres", "barres": [{"nom": "Énergie", "valeur": 3}], "absentes": []}]}
        co.complements_6(e, h)
        t = {x["id"]: x for x in e["tuiles"]}
        self.assertEqual(t["canal_énergi"]["texte"], "3")
        self.assertIn("+2,00 % sur la dernière séance", t["reaction_brent"]["variation"]["texte"])
        self.assertIsNone(t["reaction_fx_jpy"]["texte"])


if __name__ == "__main__":
    unittest.main()
