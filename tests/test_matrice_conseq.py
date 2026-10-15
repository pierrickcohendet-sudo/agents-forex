"""Palier 6 (matrice d'impact) et calcul du palier 7 (tableau des conséquences). Sans réseau, sans LLM."""
import math
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from core import consequences as cq, historique_5ans as h5, matrice_impact as mi  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def dossiers(vix=31.0, surprise_eur=0.6, mm_aud=-2.5, cot_jpy=92):
    return {"2": {"lignes": [{"devise": "EUR", "cellules": {"ecart_2a_us": {"var_4s": 20, "source": "s", "date": "2026-10-09"}}},
                             {"devise": "USD", "cellules": {"taux_2a": {"var_4s": -5, "source": "FRED", "date": "2026-10-09"}}}]},
            "3": {"lignes": [{"devise": "EUR", "cellules": {"indice_surprise": {"valeur": surprise_eur}}}]},
            "5": {"instruments": [{"id": "vix", "cellule": {"valeur": vix, "source": "FRED (VIXCLS)", "date": "2026-10-13"}}]},
            "7": {"lignes": [{"devise": "AUD", "cellules": {"ecart_mm200": {"valeur": mm_aud}}},
                             {"devise": "JPY", "cellules": {"cot": {"percentile_52s": cot_jpy}}}]}}


def vue(theme_fort=True):
    return {"theme": {"direction": {"risque": "risk_off", "dollar": "haussier"}, "date_rapport": "2026-10-14",
                      "coherence": {"theme_fort": theme_fort, "libelle": "4 sur 5 évaluables" if theme_fort else "0 sur 4 évaluables"}}}


class Matrice(unittest.TestCase):
    def cases(self, m, devise):
        return {c["engrenage"]: c for c in next(l for l in m["lignes"] if l["devise"] == devise)["cases"]}

    def test_regles_cases_bornees_et_bilan(self):
        m = mi.calculer(CONFIG, dossiers(), vue())
        jpy, aud, eur = self.cases(m, "JPY"), self.cases(m, "AUD"), self.cases(m, "EUR")
        self.assertEqual(jpy[5]["valeur"], 2)                                   # VIX ≥ 30
        self.assertEqual(jpy[5]["regles"][0]["chiffre"], "31 pts")
        self.assertIn("≥ 30", jpy[5]["regles"][0]["regle"])
        self.assertEqual(jpy[7]["valeur"], -1)                                  # COT extrême acheteur : lecture contrarienne
        self.assertEqual(aud[5]["valeur"], -2)
        self.assertEqual(aud[7]["valeur"], -1)                                  # sous la MM200 de plus de 2 %
        self.assertEqual(eur[2]["valeur"], 1)                                   # écart 2 ans +20 pb sur 4 semaines
        self.assertEqual(eur[3]["valeur"], 1)
        self.assertEqual(jpy[1]["valeur"], 1)                                   # thème risk off appliqué (thème fort)
        ligne_jpy = next(l for l in m["lignes"] if l["devise"] == "JPY")
        self.assertEqual(ligne_jpy["bilan"], sum(c["valeur"] for c in ligne_jpy["cases"]))
        self.assertEqual(ligne_jpy["lecture"], "neutre" if ligne_jpy["bilan"] < 3 else "soutenue")

    def test_zero_avec_raison_sans_donnee_ou_signaux_mixtes(self):
        m = mi.calculer(CONFIG, dossiers(), vue(theme_fort=False))
        jpy = self.cases(m, "JPY")
        self.assertEqual(jpy[1]["valeur"], 0)
        self.assertIn("signaux mixtes", jpy[1]["raison"])
        gbp = self.cases(m, "GBP")
        self.assertEqual(gbp[3]["valeur"], 0)
        self.assertIn("pas de donnée pour GBP", gbp[3]["raison"])
        self.assertIn("aucune règle", self.cases(m, "CNY")[4]["raison"])
        m2 = mi.calculer(CONFIG, {}, None)
        self.assertTrue(all(c["valeur"] == 0 and c["raison"] for l in m2["lignes"] for c in l["cases"]))


def jours(n, f, fin=date.today()):
    return [((fin - timedelta(days=n - i)).isoformat(), f(i)) for i in range(n + 1)]


class Consequences(unittest.TestCase):
    def test_moteur_actif_medianes_fiabilite_et_echantillon(self):
        n = 5 * 365
        vix = jours(n, lambda i: 20 + 8 * math.sin(i / 20))
        sp = jours(n, lambda i: 4000 * math.exp(-0.05 * math.sin((i + 0) / 20)))     # baisse quand le VIX monte
        h = h5.Historique.depuis_points({"vix": vix, "sp500": sp})
        moteur = cq._Serie(vix, "pts")
        cible = cq._Serie(sp, "%")
        debut = (date.today() - timedelta(days=n)).isoformat()
        l = cq.ligne_actif(moteur, cible, debut, date.today().isoformat())
        self.assertLess(l["sensibilite"], -0.9)
        self.assertGreaterEqual(l["fiabilite"]["n"], 20)
        self.assertIsNotNone(l["fiabilite"]["part"])                          # sens vérifié sur le mois SUIVANT : valeur libre
        r = cq.calculer(h, {"series": {}})
        self.assertEqual(r["5"]["lignes"][6]["actif"], "S&P 500")
        self.assertIn("raison", r["5"]["lignes"][0])                           # devise absente : n/d avec la raison
        self.assertIn("pas 5 ans", r["1"]["moteur"]["raison"])
        self.assertIn("Corrélation n'est pas causalité", r["2"]["note"])

    def test_sous_vingt_cas_echantillon_insuffisant(self):
        n = 400
        m = cq._Serie(jours(n, lambda i: 20 + 8 * math.sin(i / 20)), "pts")
        c = cq._Serie(jours(n, lambda i: 100 + math.cos(i / 9)), "%")
        l = cq.ligne_actif(m, c, (date.today() - timedelta(days=n)).isoformat(), date.today().isoformat())
        if l.get("fiabilite", {}).get("raison", "").startswith("échantillon"):
            self.assertIsNone(l["fiabilite"]["part"])
        self.assertLess(l["fiabilite"]["n"], 20)

    def test_lecture_du_jour_regle_de_wilson(self):
        moteur = cq._Serie([("2026-09-10", 10.0), ("2026-10-10", 30.0)], "pts")
        fort = {"part": 80, "n": 30, "bons": 24, "borne_wilson_90": cq.borne_basse_wilson(24, 30)}
        base = {"sensibilite": -0.5, "unite": "%", "fiabilite": fort, "si_hausse": {"mediane": -1.2}}
        self.assertEqual(cq._aujourdhui(moteur, 5.0, base, "2026-10-10")["lecture"], "Pression")
        faible = {"part": 60, "n": 20, "bons": 12, "borne_wilson_90": cq.borne_basse_wilson(12, 20)}
        l = cq._aujourdhui(moteur, 5.0, {**base, "fiabilite": faible}, "2026-10-10")
        self.assertEqual((l["lecture"], l["n"]), ("Indice faible", 20))                  # 60 % de 20 cas : preuve insuffisante
        self.assertIn("Wilson", l["raison"])
        self.assertEqual(cq._aujourdhui(moteur, 5.0, {**base, "si_hausse": {"mediane": 0.8}}, "2026-10-10")["lecture"], "Indice faible")
        self.assertEqual(cq._aujourdhui(moteur, 50.0, base, "2026-10-10")["lecture"], "Neutre")   # moteur calme

    def test_borne_basse_de_wilson(self):
        self.assertLess(cq.borne_basse_wilson(12, 20), 50)
        self.assertGreater(cq.borne_basse_wilson(24, 33), 50)
        self.assertIsNone(cq.borne_basse_wilson(0, 0))


class MatriceCorrections(unittest.TestCase):
    def test_serie_heurtee_comptee_zero_et_densite(self):
        d = dossiers()
        d["8"] = {"instruments": [{"id": "brent", "cellule": {"var_4s": 18.2, "source": "FRED", "date": "2026-10-06",
                                                              "alerte": "série heurtée : +18,0 % le 02/10 en une séance"}}]}
        m = mi.calculer(CONFIG, d, vue())
        cad = {c["engrenage"]: c for c in next(l for l in m["lignes"] if l["devise"] == "CAD")["cases"]}
        self.assertEqual(cad[8]["valeur"], 0)
        self.assertIn("série heurtée", cad[8]["raison"])
        self.assertEqual(m["cases_total"], 72)
        self.assertEqual(m["cases_actives"], sum(1 for l in m["lignes"] for c in l["cases"] if c["valeur"]))


class TexteAutomatique(unittest.TestCase):
    def test_texte_python_sans_modele(self):
        from agents import agent_strategiste as st
        technique = {"devises": {"JPY": {"rsi": 36.5, "rsi_lecture": "momentum baissier", "ecart_mm200_pct": 0.17,
                                         "indicateurs_source": {"date": "2026-10-14", "percentiles": {"rsi": 23}}}}}
        macro = {"flux": {"cot": {"JPY": {"net": 62325, "percentile_52s": 92, "extreme": "long", "date": "2026-10-06"}}},
                 "taux_obligataires": {"JPY": {"spread_2a_vs_usd_pb": -293}}}
        r = st.texte_automatique("JPY", technique, macro, {"JPY": {"taux": 1.227, "source": "BoJ", "date": "2026-10-09"}},
                                 {"differentiels": {"JPY": -1.52}})
        for morceau in ("RSI 14 à 36,5", "percentile 5 ans 23", "+62 325 contrats", "extrême acheteur", "1,23 %", "−293 pb",
                        "Score de confluence n/d"):
            self.assertIn(morceau, r["texte"])
        self.assertEqual(len(r["sources"]), 3)
        vide = st.texte_automatique("CNY", {}, {}, {}, {})
        self.assertIn("Aucune donnée", vide["texte"])


if __name__ == "__main__":
    unittest.main()
