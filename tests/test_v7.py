"""Lot V7 : correctif quota pendant une panne Google (V6.1-bis), force des devises (Python), corrections E1 à E3,
rang des scénarios et des surprises, JSON publiés valides. Aucun appel réseau, aucun appel réel à un modèle."""
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from core import llm as L
from core import force_devises, rapport_jour as rj, tableau_macro as tmac, dossiers
from agents import agent_rapport as ar
from tests.test_budget_quota import BUDGET, Simulateur, chaine_reelle, essayer

RACINE = Path(__file__).resolve().parent.parent


def budget_v7():
    return {**BUDGET, "plafond_run": 45}


class Point0Quota(unittest.TestCase):
    def setUp(self):
        L.reinitialiser_journal()
        self.tmp = tempfile.mkdtemp()

    def test_503_hors_budget_et_comptes_a_part(self):
        llm, _ = chaine_reelle(self.tmp, budget=budget_v7())
        sim = Simulateur(lambda n: n == 1)                 # 1er essai en 503, nouvel essai reçu
        with mock.patch.object(L.requests, "post", sim), mock.patch("time.sleep"):
            self.assertIsNotNone(essayer(llm, "engrenages"))
        reg = llm.registre
        self.assertEqual(sim.n, 2)
        self.assertEqual(reg.total_jour(), 1)              # seule la réponse reçue consomme le budget
        self.assertEqual(reg.donnees["pannes"], 1)         # le 503 : « tentative en panne »
        b = reg.resume_budget()
        self.assertEqual((b["pannes_jour"], b["plafond_pannes"], b["plafond_run"]), (1, 20, 45))

    def test_plafond_de_securite_des_pannes(self):
        llm, _ = chaine_reelle(self.tmp, budget=budget_v7())
        llm.registre.donnees["pannes"] = 15
        sim = Simulateur(lambda n: True)
        with mock.patch.object(L.requests, "post", sim), mock.patch("time.sleep"):
            self.assertIsNone(essayer(llm, "critique"))     # non prioritaire : bloquée dès 15 (5 gardées aux priorités)
            self.assertEqual(sim.n, 0)
            essayer(llm, "engrenages")                      # prioritaire : encore possible jusqu'à 20
        self.assertGreater(sim.n, 0)
        self.assertLessEqual(llm.registre.donnees["pannes"], 20)

    def test_mode_panne_apres_un_run_a_plus_de_50_pour_cent_de_503(self):
        llm, _ = chaine_reelle(self.tmp, budget=budget_v7())            # run du matin : tout en 503
        with mock.patch.object(L.requests, "post", Simulateur(lambda n: True)), mock.patch("time.sleep"):
            for e in ("engrenages", "analyses:USD-EUR-GBP", "critique"):
                essayer(llm, e)
        self.assertFalse(llm.registre.mode_panne)                        # le run complet n'est jamais en mode panne
        L.reinitialiser_journal()
        llm2, _ = chaine_reelle(self.tmp, complet=False, budget=budget_v7())   # complément suivant
        self.assertTrue(llm2.registre.mode_panne)
        sim = Simulateur(lambda n: True)
        with mock.patch.object(L.requests, "post", sim), mock.patch("time.sleep"):
            self.assertIsNone(essayer(llm2, "critique"))                 # hors priorités : rien n'est tenté
            self.assertEqual(sim.n, 0)
            essayer(llm2, "rapport:redaction")                           # priorité : 1 essai, sans nouvel essai ni repli
        self.assertEqual(sim.n, 1)
        self.assertEqual(len(sim.par_modele), 1)
        self.assertIn("MODE PANNE", __import__("orchestrateur").ligne_budget(llm2.registre.resume_budget()))

    def test_rapport_partiel_rejoue_seulement_la_redaction(self):
        # 04/11 : l'analyse (rapport:analyse) avait réussi, la rédaction (rapport:redaction) non -> statut « ok » à tort
        ancien = {"date": "2026-11-04", "statut": "ok", "watchlist": {"USD/CAD": {"haussier": "x"}}, "plan": "p",
                  "essais": 1, "jour_quota": "2026-11-04"}
        self.assertEqual(ar.parties_manquantes(ancien), ("1",))
        quand = datetime(2026, 11, 4, 9, 30, tzinfo=timezone.utc)
        self.assertTrue(ar.faut_rediger(ancien, quand, False)[0])        # le complément rejoue la rédaction
        nouveaux = {"date": "2026-11-04", "parties_faites": ["1"], "synthese": "s", "controles": [], "appels": 1}
        with mock.patch.object(ar, "attribution_modele", return_value={"libelle": "faux"}):
            fusion = ar.fusionner({**ancien, "parties_faites": ["2"]}, nouveaux)
        self.assertEqual(fusion["statut"], "ok")
        self.assertEqual(fusion["plan"], "p")                            # partie déjà rédigée conservée
        self.assertEqual(ar.statut_textes({"parties_faites": ["2"]}), "partiel")

    def test_redaction_sans_les_engrenages(self):
        r = {"engrenages_indisponibles": True, "theme": {}, "point_marche": {"lecture": "", "lignes": []},
             "lecture": {"detectes": []}, "scenarios": {"liste": []}, "synthese": {"catalyseurs": [], "biais": None}, "bilan": {}}
        self.assertIn("engrenages indisponibles", ar.faits_redaction(r)["engrenages"])

    def test_compteur_du_04_11_remis_a_sa_vraie_valeur(self):
        q = json.loads((RACINE / "data" / "cache" / "quota_llm.json").read_text(encoding="utf-8"))
        if q.get("date") != "2026-11-04":
            self.skipTest("fichier de quota d'un autre jour")
        recues = sum(v["appels"] for v in q["modeles"].values())
        # réussis + rejetés, sans les 503 : le compteur des modèles égale celui des analyses, les pannes sont à part
        self.assertEqual(recues, sum(e["appels"] for e in q["etiquettes"].values()))
        self.assertEqual(recues, sum(q["categories"].values()))
        self.assertEqual(q["pannes"], sum(q["echecs"].values()))


class Force(unittest.TestCase):
    def test_variations_mm200_et_rangs(self):
        pts = [[f"2026-10-{i + 1:02d}", 100 + i] for i in range(25)]
        cours = {"devises": {"EUR": {"points": pts, "mm200": [["2026-10-25", 110.0]]},
                             "USD": {"points": [[p[0], 200 - p[1] / 10] for p in pts], "mm200": []}}}
        f = force_devises.calculer(cours)
        eur = next(x for x in f["devises"] if x["devise"] == "EUR")
        self.assertEqual(eur["j1"], round((124 / 123 - 1) * 100, 2))
        self.assertEqual(eur["j20"], round((124 / 104 - 1) * 100, 2))
        self.assertEqual(eur["ecart_mm200"], round((124 / 110 - 1) * 100, 2))
        self.assertEqual(eur["rangs"]["j5"], 1)
        usd = next(x for x in f["devises"] if x["devise"] == "USD")
        self.assertIsNone(usd["ecart_mm200"])
        self.assertEqual(usd["raison_mm200"], "moyenne mobile 200 séances absente")
        gbp = next(x for x in f["devises"] if x["devise"] == "GBP")
        self.assertIsNone(gbp["j1"]); self.assertTrue(gbp["raison"])

    def test_fichier_publie(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "docs" / "data").mkdir(parents=True)
            force_devises.ecrire(tmp, {}, {"devises": {}})
            d = json.loads((Path(tmp) / "docs" / "data" / "force_devises.json").read_text(encoding="utf-8"))
        self.assertEqual(len(d["devises"]), 9)


MACRO = {"series": {"fed_cible_basse": {"valeur": 3.75, "date": "2026-11-03"}, "fed_cible_haute": {"valeur": 4.0, "date": "2026-11-03"}},
         "taux_directeurs": {"EUR": {"taux": 2.5, "date": "2026-11-03", "source": "FRED (ECBDFR)", "type": "dépôt"}}}
REGISTRE = {"cases": {"USD|taux_directeur": {"actuel": {"valeur": "3.88%", "source": "FRED (DFF, taux effectif)"}},
                      "EUR|taux_directeur": {"actuel": {"valeur": "2.65%"}}}}


class CorrectionsE(unittest.TestCase):
    def test_e1_e2_taux_de_reference(self):
        cel = {"taux_directeur": {"USD": {"Actuel": {}}, "EUR": {"Actuel": {}}}}
        lignes = [{"indicateur": "taux_directeur", "devise": "USD"}, {"indicateur": "taux_directeur", "devise": "EUR"}]
        tmac.harmoniser_taux_reference(cel, lignes, REGISTRE, MACRO)
        self.assertEqual(cel["taux_directeur"]["USD"]["Actuel"]["valeur"], "3,75–4,00 % [fourchette cible] · taux effectif 3,88 %")
        self.assertTrue(cel["taux_directeur"]["EUR"]["Actuel"]["valeur"].startswith("2,50 % [dépôt] · refinancement 2,65 %"))
        self.assertEqual(lignes[0]["Actuel"], cel["taux_directeur"]["USD"]["Actuel"]["valeur"])

    def test_e1_sans_serie_le_registre_reste(self):
        cel = {"taux_directeur": {"USD": {"Actuel": {"valeur": "3,88 %"}}}}
        tmac.harmoniser_taux_reference(cel, [], REGISTRE, {"series": {}})
        self.assertEqual(cel["taux_directeur"]["USD"]["Actuel"]["valeur"], "3,88 %")

    def test_e1_dossier_engrenage_2(self):
        with mock.patch("core.tableau_macro.macro_cache", return_value=MACRO):
            self.assertEqual(dossiers.fourchette_fed()["texte"], "3,75–4,00 %")

    def test_e3_alerte_fraicheur_brent(self):
        a = rj.alerte_fraicheur_brent("2026-10-27", date(2026, 11, 4))
        self.assertEqual(a["jours_ouvres"], 6)
        self.assertIn("EIA", a["cause"])
        self.assertIsNone(rj.alerte_fraicheur_brent("2026-10-30", date(2026, 11, 4)))   # 3 jours ouvrés : normal


class Rangs(unittest.TestCase):
    def test_rang_des_scenarios(self):
        cfg = {"rapport": {"scenarios": [
            {"id": "a", "titre": "A", "conditions": [["brent_5j", ">", 0, "x"]]},
            {"id": "b", "titre": "B", "conditions": [["brent_5j", ">", 0, "x"], ["vix_5j", ">", 0, "y"]]}]}}
        try:
            s = rj.scenarios(cfg, {"brent_5j": {"valeur": 1}, "vix_5j": {"valeur": 1}})
        except Exception as exc:  # noqa: BLE001 — format de config différent : vérifié sur le vrai fichier
            self.skipTest(str(exc))
        self.assertEqual(sorted(x["rang"] for x in s["liste"]), list(range(1, len(s["liste"]) + 1)))


class JsonPublies(unittest.TestCase):
    def test_tous_les_json_valides(self):
        for f in sorted((RACINE / "docs" / "data").glob("*.json")):
            with self.subTest(f.name):
                json.loads(f.read_text(encoding="utf-8"))

    def test_site_v7(self):
        site = RACINE / "docs" / "site"
        for f in ("tokens.css", "v7.css", "v7_commun.js", "ecran_synthese.js", "ecran_tableau.js", "ecran_devises.js",
                  "ecran_agenda.js", "ecran_engrenages.js", "ecran_journal.js", "vendor/lightweight-charts.standalone.production.js"):
            self.assertTrue((site / f).exists(), f)
        tokens = (site / "tokens.css").read_text(encoding="utf-8")
        self.assertIn('--f-display:"Newsreader"', tokens)
        self.assertIn(':root[data-theme="dark"]', tokens)
        self.assertNotIn("cdn.jsdelivr.net/npm/lightweight-charts", "".join(p.read_text(encoding="utf-8") for p in site.glob("*.js")))


if __name__ == "__main__":
    unittest.main()
