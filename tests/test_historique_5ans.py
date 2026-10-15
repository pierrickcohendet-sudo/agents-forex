"""Module partagé historique_5ans, archive quotidienne, portage EUR au taux de dépôt (sans réseau)."""
import json
import math
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from core import archive_quotidienne as aq, historique_5ans as h5, marche_taux  # noqa: E402

AUJ = date(2026, 10, 14)


def quotidien(jours, f, fin=AUJ):
    return [((fin - timedelta(days=jours - i)).isoformat(), f(i)) for i in range(jours + 1)]


class Stockage(unittest.TestCase):
    def test_fenetre_glissante_taille_stable(self):
        chemin = Path(tempfile.mkdtemp()) / "h.json"
        bruts = {"vix": quotidien(4000, lambda i: 15 + i % 7), "inconnue": quotidien(10, lambda i: 1)}
        comptes = h5.enregistrer(bruts, chemin, AUJ)
        self.assertEqual(comptes, {"vix": h5.FENETRE_JOURS + 1})          # au-delà de la fenêtre : supprimé ; série hors liste ignorée
        taille = chemin.stat().st_size
        h5.enregistrer({"vix": quotidien(4001, lambda i: 15 + i % 7, AUJ + timedelta(days=1))}, chemin, AUJ + timedelta(days=1))
        self.assertLessEqual(abs(chemin.stat().st_size - taille), 50)        # un jour de plus : même taille, à quelques octets près
        h = h5.charger(chemin)
        self.assertEqual(h.serie("vix")[-1][0], (AUJ + timedelta(days=1)).isoformat())
        self.assertFalse(h5.charger(Path(tempfile.mkdtemp()) / "absent.json").disponible)

    def test_raccord_twelve_data_prioritaire_et_fed_remise_a_l_echelle(self):
        h = h5.Historique.depuis_points({"FX_JPY": [("2026-10-07", 150.0), ("2026-10-08", 150.0), ("2026-10-09", 160.0)],
                                         "dollar_large": [("2026-10-09", 120.0)]})
        technique = {"historique": {"JPY": {"dates": ["2026-10-08", "2026-10-12"], "clotures": [0.0070, 0.0064]}}}
        f = h.force("JPY", technique)
        self.assertEqual([d for d, _ in f], ["2026-10-07", "2026-10-08", "2026-10-12"])   # Twelve Data dès sa 1re séance
        self.assertAlmostEqual(f[0][1], 0.0070)                                           # Fed remise à l'échelle : pas de saut
        self.assertEqual(f[-1], ("2026-10-12", 0.0064))
        self.assertEqual(h.force("JPY")[0], ("2026-10-07", 1 / 150))                      # sans Twelve Data : Fed seule

    def test_usd_synthetique_meme_definition_que_la_collecte(self):
        pts = {f"FX_{d}": [("2026-10-01", 1.0), ("2026-10-02", 1.01)] for d in h5.DEVISES if d != "USD" and d not in h5.INVERSEES}
        pts.update({f"FX_{d}": [("2026-10-01", 1.0), ("2026-10-02", 1 / 1.01)] for d in h5.INVERSEES})
        usd = h5.Historique.depuis_points(pts).force("USD")
        self.assertAlmostEqual(usd[-1][1], 100 * (1 - 0.01), places=6)                    # toutes les devises +1 % : USD −1 %


class Harmonisation(unittest.TestCase):
    def test_une_seule_valeur_partout(self):
        n = 1500
        fed = [((date(2026, 10, 14) - timedelta(days=n - i)).isoformat(), 1.1 + 0.05 * math.sin(i / 25)) for i in range(n)]
        h = h5.Historique.depuis_points({"FX_EUR": fed})
        technique = {"devises": {"EUR": {"rsi": 99.0, "dernier": fed[-1][1]}}, "historique": {}}
        changes = h5.harmoniser_technique(technique, h)
        eur = technique["devises"]["EUR"]
        ind = h5.indicateurs_techniques(h, "EUR", technique)
        self.assertEqual(eur["rsi"], ind["rsi"]["valeur"])                               # même valeur que le dossier 7
        self.assertEqual(eur["ecart_mm200_pct"], ind["ecart_mm200"]["valeur"])
        self.assertEqual(eur["volatilite_20j"], ind["volatilite"]["valeur"])
        self.assertIn("EUR", changes)
        self.assertIn("Twelve Data", eur["indicateurs_source"]["source"])
        self.assertIn("Retenu", eur["indicateurs_source"]["explication"])
        self.assertEqual(h5.harmoniser_technique({"devises": {"EUR": {"rsi": 50}}}, h5.Historique(None)), {})


class Cours(unittest.TestCase):
    def test_graphique_et_indicateurs_meme_moyenne_mobile_sans_week_end(self):
        from core import cours
        n = 1500
        fed = [((date(2026, 10, 9) - timedelta(days=n - i)).isoformat(), 1.1 + 0.05 * math.sin(i / 25)) for i in range(n)]
        h = h5.Historique.depuis_points({"FX_EUR": fed})
        technique = {"devises": {"EUR": {"rsi": 50, "dernier": 1.1}},
                     "historique": {"EUR": {"dates": ["2026-10-09", "2026-10-10", "2026-10-12"], "clotures": [1.1, 1.1, 1.12]}}}
        self.assertNotIn("2026-10-10", [d for d, _ in h.force("EUR", technique)])        # samedi retiré à la source
        h5.harmoniser_technique(technique, h)
        c = cours.calculer(h, technique)["devises"]["EUR"]
        self.assertAlmostEqual(c["mm200"][-1][1], technique["devises"]["EUR"]["mm200"], places=5)
        self.assertLessEqual(len(c["points"]), 262)


class Indicateurs(unittest.TestCase):
    def test_rsi_moyenne_volatilite_et_percentile(self):
        pts = quotidien(2000, lambda i: 100 * math.exp(0.01 * math.sin(i / 5)))
        r = h5.rsi(pts)
        self.assertTrue(all(0 <= v <= 100 for _, v in r))
        self.assertEqual(len(h5.ecart_moyenne(pts, 200)), len(pts) - 199)
        self.assertEqual(h5.ecart_moyenne([("a", 1.0), ("b", 1.0), ("c", 4.0)], 3)[-1][1], 100.0)   # 4 / 2 − 1
        self.assertTrue(all(v >= 0 for _, v in h5.volatilite(pts)))
        res = h5.resume(r, aujourdhui=AUJ)
        self.assertIsNotNone(res["percentile_5a"])
        self.assertGreater(res["n_5a"], 1000)
        self.assertTrue(80 <= len(res["courbe"]) <= 121)

    def test_indicateurs_techniques_et_raison_sans_historique(self):
        h = h5.Historique.depuis_points({"FX_EUR": quotidien(1500, lambda i: 1.1 + 0.05 * math.sin(i / 30))})
        ind = h5.indicateurs_techniques(h, "EUR")
        self.assertIsNotNone(ind["rsi"]["percentile_5a"])
        self.assertIsNotNone(ind["ecart_mm200"]["valeur"])
        vide = h5.indicateurs_techniques(h5.Historique(None), "EUR")
        self.assertIn("indisponible", vide["rsi"]["raison"])

    def test_matrice_complete_et_changements_de_signe(self):
        n = 400
        ouvres = lambda pts: [(d, v) for d, v in pts if date.fromisoformat(d).weekday() < 5]   # format réel
        base = ouvres(quotidien(n, lambda i: 100 * math.exp(0.01 * math.sin(i * 1.3) + 0.002 * i)))
        h = h5.Historique.depuis_points({"FX_AUD": base, "sp500": base, "vix": ouvres(quotidien(n, lambda i: 20 + math.cos(i * 0.7)))})
        m = h5.matrice(h)
        self.assertEqual(m["matrice"]["AUD"]["S&P 500"], 1.0)
        self.assertIn("matrice_precedente", m)
        self.assertIsNone(h5.matrice(h5.Historique(None)))


class Archive(unittest.TestCase):
    def dossiers(self, canal=3, mm=1.85):
        return {"1": {"tuiles": [{"id": "coherence", "valeur": 0, "texte": "0 sur 4 évaluables"},
                                 {"id": "surprise_globale", "valeur": -0.04}]},
                "6": {"tuiles": [{"id": "canal_énergi", "libelle": "Titres : énergie", "valeur": canal}]},
                "7": {"lignes": [{"devise": "USD", "cellules": {"ecart_mm200": {"valeur": mm}, "volatilite": {"valeur": 4.0}}}]}}

    def test_une_entree_par_jour_purge_et_valeurs_conservees(self):
        chemin = Path(tempfile.mkdtemp()) / "a.json"
        aq.archiver(self.dossiers(), chemin, AUJ - timedelta(days=7 * 366))
        aq.archiver(self.dossiers(canal=2), chemin, AUJ)
        a = aq.archiver(self.dossiers(canal=5, mm=None), chemin, AUJ)            # second passage du jour
        self.assertEqual(list(a["jours"]), [AUJ.isoformat()])                    # plus de 6 ans : purgé
        jour = a["jours"][AUJ.isoformat()]
        self.assertEqual(jour["titres_par_canal"], {"énergie": 5})
        self.assertEqual(jour["usd_ecart_mm200"], 1.85)                          # None n'écrase pas la valeur connue
        self.assertEqual(jour["coherence_libelle"], "0 sur 4 évaluables")

    def test_courbes_des_tuiles_depuis_l_archive(self):
        archive = {"jours": {(date.today() - timedelta(days=k)).isoformat(): {"coherence_alignes": k, "surprise_globale": 0.1,
                                                                             "titres_par_canal": {"énergie": k}} for k in range(3)}}
        d = self.dossiers()
        aq.completer_tuiles(d, archive)
        self.assertEqual(len(d["1"]["tuiles"][0]["courbe"]["points"]), 3)
        self.assertEqual(d["6"]["tuiles"][0]["courbe"]["points"][-1][1], 0)
        aq.completer_tuiles(d, {"jours": {date.today().isoformat(): {"coherence_alignes": 1}}})
        self.assertIn("archive trop récente", d["1"]["tuiles"][0]["courbe"]["raison"])


class PortageEur(unittest.TestCase):
    def test_taux_de_depot_prime_sur_le_refinancement_du_registre(self):
        jour = (date.today() - timedelta(days=1)).isoformat()
        macro = {"taux_directeurs": {"EUR": {"taux": 2.4, "date": "2026-01-15", "source": "config"},
                                     "USD": {"taux": 3.75, "date": "2026-01-15", "source": "config"}}}
        registre = {"cases": {"EUR|taux_directeur": {"actuel": {"valeur": "2.65%", "valeur_num": 2.65, "date_pub": "2026-09-10"}}}}
        hist = {"series": {"EUR_taux_depot": {"points": [[jour, 2.5]]}}}
        marche_taux.appliquer_registre_taux(macro, registre, {"ordre_devises": ["EUR", "USD"]}, hist)
        eur = macro["taux_directeurs"]["EUR"]
        self.assertEqual(eur["taux"], 2.5)
        self.assertIn("ECBDFR", eur["source"])
        self.assertIn("refinancement", eur["registre"])
        sans = {"taux_directeurs": {"EUR": {"taux": 2.4, "date": "2026-01-15", "source": "config"}}}
        marche_taux.appliquer_registre_taux(sans, registre, {"ordre_devises": ["EUR"]}, {"series": {}})
        self.assertEqual(sans["taux_directeurs"]["EUR"]["taux"], 2.65)            # sans ECBDFR : registre, comme avant


if __name__ == "__main__":
    unittest.main()
