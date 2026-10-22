"""Palier 9 : briefing en 60 secondes (9 cartes calculées dans core/vue_ensemble.py) et corrections de la roue
(libellés, thème neutre, raison Python de chaque couleur). Sans réseau, sans appel LLM."""
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from agents import agent_engrenages as ae  # noqa: E402
from core import vue_ensemble as ve  # noqa: E402
from tests.test_engrenages import DEVISES, brut, donnees, macro  # noqa: E402
from tests.test_engrenages_quota import CONFIG, EXTRAS_MATRICE, chaine, config_test  # noqa: E402


def rapport(sortie):
    return {"meta": {"date_rapport": "2026-10-22"}, "devises": DEVISES, "synthese_globale": {"engrenages": sortie}}


def avec_modele():
    s = ae.signaux(CONFIG, donnees(), macro(), DEVISES, "risk_off", EXTRAS_MATRICE, ae._Catalogue([]))
    sortie = ae.normaliser(brut(), s, ae.conflits_detectes(s), None, CONFIG)
    ae.imposer_signaux_mixtes(sortie)
    sortie.update({"statut": "ok", "redige_par": {"libelle": "Flash 3.5"}})
    return sortie


def quota_zero():
    llm, _, _ = chaine({"a": 20}, utilises=20)
    return ae.generer(config_test(), llm, donnees(), macro(), [], DEVISES, "risk_off", EXTRAS_MATRICE)


class NeufCartes(unittest.TestCase):
    def test_theme_puis_les_8_engrenages_textes_du_modele(self):
        v = ve.calculer({}, None, None, rapport(avec_modele()))
        b = v["briefing"]
        self.assertEqual([c["numero"] for c in b["cartes"]], list(range(9)))
        self.assertEqual(b["secondes_par_carte"], 8)
        theme = b["cartes"][0]
        self.assertEqual((theme["surtitre"], theme["titre"]), ("Thème du jour", v["theme"]["titre"]))
        self.assertEqual(theme["verdict"]["libelle"], v["theme"]["direction"]["libelle"])
        for c in b["cartes"][1:]:
            self.assertEqual(c["titre"], ve.TITRES[c["numero"]])
            self.assertEqual(c["chiffre"], v["cartes"][c["numero"] - 1]["chiffre"])     # mêmes champs que les cartes
            self.assertEqual(c["ligne"], v["cartes"][c["numero"] - 1]["ligne"])
            self.assertTrue(c["a_retenir"])
        self.assertEqual(b["cartes"][2]["a_retenir"], "Diagnostic 2.")                   # première phrase du modèle
        self.assertEqual(b["cartes"][2]["a_retenir_source"], "modèle")
        self.assertIsNone(b["cartes"][2]["texte_indisponible"])

    def test_a_retenir_sans_identifiants_de_source(self):
        self.assertEqual(ve._premiere_phrase("WTI à 101 $ (src_011, src_159). Suite."), "WTI à 101 $.")
        self.assertEqual(ve._premiere_phrase("Pressions (src_169) géopolitiques. Suite."), "Pressions géopolitiques.")

    def test_quota_a_zero_phrase_python_et_texte_indisponible(self):
        v = ve.calculer({}, None, None, rapport(quota_zero()))
        for c in v["briefing"]["cartes"]:
            self.assertEqual(c["a_retenir_source"], "calcul Python", c["numero"])
            self.assertTrue(c["a_retenir"], c["numero"])
            self.assertEqual(c["texte_indisponible"], ae.TEXTE_QUOTA, c["numero"])
            self.assertNotEqual(c["verdict"]["libelle"], "non déterminée", c["numero"])   # roue colorée, verdicts Python
        quatre = v["briefing"]["cartes"][4]
        self.assertTrue(quatre["a_retenir"].startswith("Dollar baissier. Règle Python : "), quatre["a_retenir"])
        self.assertIn("matrice d'impact", quatre["a_retenir"])

    def test_donnees_manquantes_raison_affichee_comme_les_tuiles(self):
        v = ve.calculer({}, None, None, rapport(quota_zero()))          # aucun historique : chiffres n/d
        deux = v["briefing"]["cartes"][2]
        self.assertIsNone(deux["chiffre"]["texte"])
        self.assertEqual(deux["chiffre"]["raison"], "série DGS2 indisponible")

    def test_sans_synthese_du_tout(self):
        v = ve.calculer({}, None, None, {"meta": {}, "devises": [], "synthese_globale": {}})
        cartes = v["briefing"]["cartes"]
        self.assertEqual(len(cartes), 9)
        self.assertEqual(cartes[0]["titre"], "Thème non déterminé")
        self.assertIsNone(cartes[0]["chiffre"]["texte"])
        self.assertTrue(cartes[0]["chiffre"]["raison"])
        self.assertTrue(all(c["texte_indisponible"] == ve.TEXTE_SANS_SYNTHESE for c in cartes))
        self.assertTrue(all("Hachures" in c["raison_couleur"] for c in cartes[1:]))


class Roue(unittest.TestCase):
    def test_libelles_en_toutes_lettres(self):
        d = ve._direction({"direction": {"dollar": "neutre", "risque": "neutre"}})
        self.assertEqual(d["libelle"], "Dollar neutre · Risque neutre")
        self.assertEqual(ve._direction({"direction": {"dollar": "haussier", "risque": "risk_off"}})["libelle"],
                         "Dollar haussier · Risk off")

    def test_theme_neutre_pas_d_alignement_a_mesurer(self):
        par_num = {1: {"direction": {"dollar": "neutre", "risque": "neutre"}},
                   2: {"direction": {"dollar": "haussier"}}, 5: {"direction": {"dollar": "neutre", "risque": "risk_off"}}}
        coh = ve.coherence(par_num)
        self.assertTrue(coh["theme_neutre"])
        self.assertEqual(coh["libelle"], "Thème neutre : pas d'alignement à mesurer")
        self.assertEqual((coh["evaluables"], coh["theme_fort"]), (0, False))
        self.assertIn("pas d'alignement à mesurer", ve.phrase_signaux_mixtes(coh, ve._direction(par_num[1])))

    def test_dollar_neutre_risque_tranche_mesure_sur_le_risque(self):
        par_num = {1: {"direction": {"dollar": "neutre", "risque": "risk_off"}},
                   5: {"direction": {"dollar": "haussier", "risque": "risk_off"}}, 7: {"direction": {"dollar": "baissier", "risque": "risk_on"}}}
        coh = ve.coherence(par_num)
        self.assertFalse(coh["theme_neutre"])
        self.assertEqual(coh["libelle"], "1 sur 2 évaluables")

    def test_raison_python_de_chaque_couleur(self):
        v = ve.calculer({}, None, None, rapport(quota_zero()))
        par = {c["numero"]: c["direction"]["raison_couleur"] for c in v["cartes"]}
        self.assertTrue(par[4].startswith("Rouge (Dollar baissier) : dollar : case USD de la matrice d'impact"), par[4])
        self.assertTrue(par[6].startswith("Rouge (Dollar haussier · Risk off)"), par[6])
        self.assertTrue(par[8].startswith("Gris (Dollar neutre)"), par[8])
        self.assertIn("Chiffre du jour : ", par[2])                       # 2 ans US : le chiffre déclencheur
        self.assertEqual(len(v["briefing"]["legende"]), 4)


if __name__ == "__main__":
    unittest.main()
