"""Disjoncteur du modèle principal, attribution du modèle, quota journalier (sans réseau)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import llm  # noqa: E402


class Faux(llm.FournisseurLLM):
    """Fournisseur factice : échoue selon un script, note ses appels comme les vrais."""

    def __init__(self, modele, scenario):
        self.modele, self.scenario, self.appels = modele, list(scenario), 0

    def appeler_llm(self, prompt, systeme=None):
        self.appels += 1
        ok = self.scenario.pop(0) if self.scenario else True
        llm._noter_appel(self.modele, systeme, prompt, ok is True)
        if ok is True:
            return "{}"
        if ok == "quota":
            raise llm.QuotaJournalierEpuise("quota jour")
        raise RuntimeError("503")


def enveloppe(principal, secours, **kw):
    return llm.FournisseurAvecSecours(principal, secours, "g/principal", "g/secours", **kw)


class Disjoncteur(unittest.TestCase):
    def setUp(self):
        llm.reinitialiser_journal()

    def test_ouvre_apres_trois_echecs_consecutifs_puis_ignore_le_principal(self):
        p, s = Faux("gemini-3.5-flash", [False] * 10), Faux("gemini-3.5-flash-lite", [])
        f = enveloppe(p, s, disjoncteur_actif=True, seuil_echecs=3)
        for _ in range(6):
            f.appeler_llm("x")
        self.assertEqual(p.appels, 3)            # plus aucun appel au principal après l'ouverture
        self.assertEqual(s.appels, 6)
        etat = f.etat_disjoncteur()
        self.assertTrue(etat["ouvert"])
        self.assertEqual(etat["appels_principal_ignores"], 3)
        self.assertEqual(etat["ouvert_a_l_appel"], 3)
        self.assertIn("3 échecs consécutifs", etat["cause"])

    def test_un_succes_remet_le_compteur_a_zero(self):
        p, s = Faux("a", [False, False, True, False, False, True]), Faux("b", [])
        f = enveloppe(p, s, disjoncteur_actif=True, seuil_echecs=3)
        for _ in range(6):
            f.appeler_llm("x")
        self.assertFalse(f.etat_disjoncteur()["ouvert"])
        self.assertEqual(p.appels, 6)

    def test_quota_journalier_ouvre_immediatement(self):
        p, s = Faux("a", ["quota"]), Faux("b", [])
        f = enveloppe(p, s, disjoncteur_actif=True, seuil_echecs=3)
        f.appeler_llm("x")
        f.appeler_llm("x")
        self.assertTrue(f.etat_disjoncteur()["ouvert"])
        self.assertEqual((p.appels, s.appels), (1, 2))
        self.assertIn("quota", f.etat_disjoncteur()["cause"])

    def test_disjoncteur_desactive_comportement_inchange(self):
        p, s = Faux("a", [False] * 5), Faux("b", [])
        f = enveloppe(p, s)
        for _ in range(5):
            f.appeler_llm("x")
        self.assertEqual(p.appels, 5)
        self.assertFalse(f.etat_disjoncteur()["ouvert"])

    def test_nouveau_run_nouvelle_instance_le_principal_est_retente(self):
        p1, s = Faux("a", [False] * 3), Faux("b", [])
        enveloppe(p1, s, disjoncteur_actif=True, seuil_echecs=3)
        f2 = enveloppe(Faux("a", []), s, disjoncteur_actif=True, seuil_echecs=3)
        f2.appeler_llm("x")
        self.assertEqual(llm.dernier_modele(), "a")

    def test_les_deux_en_echec_leve_runtimeerror_sans_casser_le_compteur(self):
        f = enveloppe(Faux("a", [False]), Faux("b", [False]), disjoncteur_actif=True)
        with self.assertRaises(RuntimeError):
            f.appeler_llm("x")


class Attribution(unittest.TestCase):
    def setUp(self):
        llm.reinitialiser_journal()

    def test_modele_reel_apres_repli_et_etiquette_dans_le_journal(self):
        f = enveloppe(Faux("gemini-3.5-flash", [False]), Faux("gemini-3.5-flash-lite", []),
                      disjoncteur_actif=True)
        llm.definir_etiquette("analyse:EUR")
        f.appeler_llm("x")
        self.assertEqual(llm.attribution_modele(),
                         {"modele": "gemini-3.5-flash-lite", "libelle": "Flash-Lite 3.5"})
        j = llm.journal_appels()
        self.assertEqual([(e["modele"], e["ok"], e["etiquette"]) for e in j],
                         [("gemini-3.5-flash", False, "analyse:EUR"),
                          ("gemini-3.5-flash-lite", True, "analyse:EUR")])

    def test_libelles(self):
        self.assertEqual(llm.libelle_modele("gemini-3.5-flash"), "Flash 3.5")
        self.assertEqual(llm.libelle_modele("gemini-flash-latest"), "Flash")
        self.assertEqual(llm.libelle_modele("gemini-3.1-flash-lite"), "Flash-Lite 3.1")
        self.assertIsNone(llm.libelle_modele(None))

    def test_gemini_429_par_jour_ne_dort_pas(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}):
            g = llm.FournisseurGemini("gemini-3.8-flash", pause_min_s=0, backoff_429_s=30)
        rep = mock.Mock(status_code=429, text='{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}')
        with mock.patch.object(g, "_poster", return_value=rep), mock.patch("time.sleep") as dodo:
            with self.assertRaises(llm.QuotaJournalierEpuise):
                g.appeler_llm("x")
        dodo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
