"""Palier 11 : calcul du simulateur d'impact (core/impact.py). Sans réseau, sans LLM."""
import math
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from core import consequences as cq, historique_5ans as h5, impact  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
FIN = date(2026, 10, 14)


def jours_ouvres(n, f):
    sortie, d, i = [], FIN - timedelta(days=n), 0
    while d <= FIN:
        if d.weekday() < 5:
            sortie.append((d.isoformat(), f(i)))
            i += 1
        d += timedelta(days=1)
    return sortie


def historique():
    """VIX avec des chocs réguliers ; le JPY monte de 1 % la séance après chaque choc à la hausse du VIX."""
    n = 5 * 365 + 40
    vix = jours_ouvres(n, lambda i: 20 + (8 if i % 40 == 0 and i else 0) - (8 if i % 40 == 1 and i > 1 else 0) + 0.3 * math.sin(i))
    choc = {d for k, (d, v) in enumerate(vix) if k and v - vix[k - 1][1] > 5}
    jpy, niveau = [], 150.0
    for d, _ in vix:
        jpy.append((d, niveau))
        if d in choc:
            niveau /= 1.01                     # JPY par USD en baisse : le yen se renforce de 1 % à la séance suivante
    return h5.Historique.depuis_points({"vix": vix, "FX_JPY": jpy})


class Episodes(unittest.TestCase):
    def test_seuil_espacement_et_signe(self):
        deltas = [("2026-01-01", 3.0), ("2026-01-05", 3.0), ("2026-02-10", -2.5), ("2026-02-12", 0.5)]
        self.assertEqual(impact.episodes(deltas, 1.0, 1), [("2026-01-01", 3.0), ("2026-02-10", -2.5)])   # 28 jours d'écart
        self.assertEqual(impact.episodes(deltas, 1.0, 3), [("2026-01-01", 3.0)])

    def test_serie_seance_suivante_et_week_end(self):
        s = impact.Serie([("2026-10-09", 1.0), ("2026-10-10", 1.0), ("2026-10-12", 1.1)], "%", sans_week_end=True)
        self.assertEqual(s.dates, ["2026-10-09", "2026-10-12"])                  # samedi retiré
        self.assertEqual(s.apres("2026-10-09"), ("2026-10-12", 1.1))
        r = impact.reponses(s, "2026-10-09")
        self.assertAlmostEqual(r["demain"], math.log(1.1) * 100, places=6)
        self.assertIsNone(r["mois"])                                             # pas encore connu : jamais extrapolé


class Calcul(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = impact.calculer(historique(), None, {"cases": {}}, CONFIG, FIN)

    def test_hausse_et_baisse_separees_avec_cas_et_quartiles(self):
        c = self.r["couples"]["vix|JPY"]
        hausse = c["scenarios"]["hausse|1"]
        self.assertGreaterEqual(hausse["demain"]["n"], 20)
        self.assertAlmostEqual(hausse["demain"]["mediane"], 1.0, delta=0.05)    # yen +1 % la séance suivante
        self.assertLessEqual(hausse["demain"]["q25"], hausse["demain"]["mediane"])
        self.assertGreaterEqual(hausse["demain"]["q75"], hausse["demain"]["mediane"])
        self.assertFalse(hausse["demain"]["insuffisant"])
        self.assertTrue(len(hausse["trajectoire"]) >= 20)
        self.assertIn("baisse|1", c["scenarios"])
        self.assertEqual(self.r["nombre_de_cas"]["vix"]["JPY"]["hausse|1"], hausse["mois"]["n"])

    def test_sous_vingt_cas_echantillon_insuffisant(self):
        sc = self.r["couples"]["vix|JPY"]["scenarios"]["baisse|2"]["mois"]
        if sc["n"] < 20:
            self.assertTrue(sc["insuffisant"])
            self.assertIn("échantillon insuffisant pour conclure", sc["raison"])
            self.assertTrue(any(x.startswith("vix|JPY|baisse|2σ") for x in self.r["insuffisants"]))
        r = impact.resume_horizon([0.5] * 5, 1)
        self.assertTrue(r["insuffisant"])
        self.assertEqual(r["part_sens_attendu"], 100)

    def test_indicateurs_absents_et_surprises_sans_consensus(self):
        par_id = {i["id"]: i for i in self.r["indicateurs"]}
        self.assertIn("série 5 ans indisponible", par_id["brent"]["raison"])
        self.assertIn("absent du registre", par_id["cpi_us"]["raison"])
        self.assertNotIn("brent|JPY", self.r["couples"])
        self.assertIn("USD", self.r["devises_absentes"])

    def test_surprises_avec_consensus_forexfactory(self):
        historique_cpi = [{"date_pub": f"2026-{m:02d}-12", "valeur": f"{3 + (m % 3) * 0.1:.1f}%", "consensus": "3.1%"} for m in range(1, 10)]
        registre = {"cases": {"USD|cpi": {"historique": historique_cpi[:-1], "actuel": historique_cpi[-1],
                                          "prevision": {"date_pub": "2026-11-13"}}}}
        r = impact.calculer(historique(), None, registre, CONFIG, FIN)
        cpi = next(i for i in r["indicateurs"] if i["id"] == "cpi_us")
        self.assertEqual(cpi["n_publications"], 9)
        self.assertIsNotNone(cpi["sigma"])
        self.assertEqual(cpi["prochaine_publication"], "2026-11-13")
        self.assertIn("cpi_us|JPY", r["couples"])
        self.assertTrue(r["couples"]["cpi_us|JPY"]["scenarios"]["hausse|1"]["mois"]["insuffisant"])   # 9 publications < 20


class SourceUnique(unittest.TestCase):
    def test_meme_sensibilite_que_le_tableau_des_consequences(self):
        n = 5 * 365 + 40
        vix = jours_ouvres(n, lambda i: 20 + 6 * math.sin(i / 15))
        aud = jours_ouvres(n, lambda i: 0.7 * math.exp(-0.03 * math.sin(i / 15) + 0.0001 * i))
        h = h5.Historique.depuis_points({"vix": vix, "FX_AUD": aud})
        r = impact.calculer(h, None, {"cases": {}}, CONFIG, FIN)
        c = cq.calculer(h, {"series": {}}, None, FIN)
        ligne = next(l for l in c["5"]["lignes"] if l["actif"] == "AUD")
        self.assertEqual(ligne["sensibilite"], r["couples"]["vix|AUD"]["sensibilite"])
        self.assertLess(ligne["sensibilite"], -0.9)


if __name__ == "__main__":
    unittest.main()
