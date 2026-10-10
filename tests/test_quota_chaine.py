"""Chaîne de modèles + compteur de quota journalier + taux directeurs depuis le registre (sans réseau)."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from agents import agent_strategiste as st, agent_synthese as sy  # noqa: E402
from core import llm as L, marche_taux  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


class Faux(L.FournisseurLLM):
    def __init__(self, modele, scenario=(), registre=None):
        self.modele, self.scenario, self.appels, self.registre = modele, list(scenario), 0, registre

    def appeler_llm(self, prompt, systeme=None):
        self.appels += 1
        if self.registre:
            self.registre.compter(self.modele)
        ok = self.scenario.pop(0) if self.scenario else True
        L._noter_appel(self.modele, systeme, prompt, ok is True)
        if ok is True:
            return json.dumps({"ok": True})
        if ok == "quota":
            raise L.QuotaJournalierEpuise("quota jour")
        raise RuntimeError("503")


def chaine(tmp, plafonds, scenarios=None, **kw):
    registre = L.RegistreQuotas(Path(tmp) / "quota.json", plafonds)
    faux = {m: Faux(m, (scenarios or {}).get(m, ()), registre) for m in plafonds}
    return L.FournisseurChaine([(m, f) for m, f in faux.items()], registre, **kw), faux, registre


class Chaine(unittest.TestCase):
    def setUp(self):
        L.reinitialiser_journal()
        self.tmp = tempfile.mkdtemp()

    def test_modele_au_plafond_saute_sans_attente_et_plafond_jamais_depasse(self):
        c, faux, reg = chaine(self.tmp, {"a": 2, "b": 5})
        with mock.patch("time.sleep") as dodo:
            for _ in range(4):
                c.appeler_llm("x")
        dodo.assert_not_called()
        self.assertEqual((faux["a"].appels, faux["b"].appels), (2, 2))     # a plafonné à 2, le reste sur b
        self.assertEqual(reg.etat()["modeles"]["a"]["appels_aujourdhui"], 2)

    def test_tous_epuises_leve_quota_atteint_sans_aucun_appel(self):
        c, faux, _ = chaine(self.tmp, {"a": 1, "b": 1})
        c.appeler_llm("x")
        c.appeler_llm("x")
        with self.assertRaises(L.QuotaAtteint) as ctx:
            c.appeler_llm("x")
        self.assertIn("quota atteint", str(ctx.exception))
        self.assertEqual((faux["a"].appels, faux["b"].appels), (1, 1))

    def test_echecs_consecutifs_ouvrent_le_disjoncteur_et_la_chaine_continue(self):
        c, faux, _ = chaine(self.tmp, {"a": 50, "b": 50}, {"a": [False] * 9},
                            disjoncteur_actif=True, seuil_echecs=3)
        for _ in range(6):
            c.appeler_llm("x")
        self.assertEqual(faux["a"].appels, 3)
        self.assertEqual(faux["b"].appels, 6)
        etat = c.etat_disjoncteur()
        self.assertTrue(etat["ouvert"])
        self.assertTrue(etat["modeles"][0]["ouvert"])

    def test_pas_quota_atteint_quand_un_modele_echoue_pour_une_autre_raison(self):
        c, _, _ = chaine(self.tmp, {"a": 1, "b": 50}, {"b": [False]}, disjoncteur_actif=False)
        c.appeler_llm("x")            # a (1/1)
        with self.assertRaises(RuntimeError) as ctx:
            c.appeler_llm("x")        # a plafonné, b en échec (503)
        self.assertNotIsInstance(ctx.exception, L.QuotaAtteint)

    def test_quota_journalier_429_marque_le_modele_epuise_pour_la_suite(self):
        c, faux, reg = chaine(self.tmp, {"a": 20, "b": 20}, {"a": ["quota"]})
        c.appeler_llm("x")
        reg.marquer_epuise("a", 3600)
        self.assertFalse(reg.autoriser("a"))
        c.appeler_llm("x")
        self.assertEqual(faux["a"].appels, 1)

    def test_etat_persiste_et_remise_a_zero_le_lendemain(self):
        chemin = Path(self.tmp) / "q.json"
        reg = L.RegistreQuotas(chemin, {"a": 3})
        reg.compter("a")
        reg.compter("a")
        self.assertEqual(L.RegistreQuotas(chemin, {"a": 3}).etat()["modeles"]["a"]["appels_aujourdhui"], 2)
        brut = json.loads(chemin.read_text(encoding="utf-8"))
        brut["date"] = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        chemin.write_text(json.dumps(brut), encoding="utf-8")
        self.assertEqual(L.RegistreQuotas(chemin, {"a": 3}).etat()["modeles"]["a"]["appels_aujourdhui"], 0)

    def test_epuisement_encore_valide_conserve_apres_minuit(self):
        chemin = Path(self.tmp) / "q.json"
        futur = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        chemin.write_text(json.dumps({"date": "2000-01-01", "modeles": {"a": {"appels": 20, "epuise_jusqu_a": futur}}}),
                          encoding="utf-8")
        reg = L.RegistreQuotas(chemin, {"a": 20})
        self.assertFalse(reg.autoriser("a"))

    def test_delai_de_reprise_lu_dans_la_reponse_429(self):
        self.assertEqual(L._delai_reprise_s('{"retryDelay": "42460s"}'), 42460.0)
        self.assertAlmostEqual(L._delai_reprise_s("Please retry in 11h47m40.5s."), 11 * 3600 + 47 * 60 + 40.5)
        self.assertIsNone(L._delai_reprise_s("rien"))

    def test_gemini_ne_poste_jamais_au_dela_du_plafond_local(self):
        reg = L.RegistreQuotas(Path(self.tmp) / "g.json", {"gemini-x": 1})
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}):
            g = L.FournisseurGemini("gemini-x", pause_min_s=0, registre_quotas=reg)
        ok = mock.Mock(status_code=200, text="", **{"json.return_value": {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}})
        with mock.patch("requests.post", return_value=ok) as post:
            g.appeler_llm("x")
            with self.assertRaises(L.QuotaJournalierEpuise):
                g.appeler_llm("x")
        self.assertEqual(post.call_count, 1)

    def test_gemini_429_perday_marque_epuise_avec_le_delai_de_l_api(self):
        reg = L.RegistreQuotas(Path(self.tmp) / "g.json", {"gemini-x": 20})
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}):
            g = L.FournisseurGemini("gemini-x", pause_min_s=0, registre_quotas=reg)
        rep = mock.Mock(status_code=429, text='{"quotaId":"...PerDay...","retryDelay":"3600s"}')
        with mock.patch("requests.post", return_value=rep):
            with self.assertRaises(L.QuotaJournalierEpuise):
                g.appeler_llm("x")
        self.assertTrue(reg.epuise("gemini-x"))

    def test_creer_fournisseur_construit_la_chaine_dans_l_ordre_de_la_config(self):
        cfg = copy.deepcopy(CONFIG)
        cfg["llm"]["fichier_quota"] = str(Path(self.tmp) / "cfg.json")
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}):
            f = L.creer_fournisseur(cfg)
        self.assertIsInstance(f, L.FournisseurChaine)
        self.assertEqual([m["modele"] for m in f.maillons], [e["modele"] for e in cfg["llm"]["modeles"]])


class QuotaEpuiseCoteRapport(unittest.TestCase):
    def llm_epuise(self):
        tmp = tempfile.mkdtemp()
        c, faux, _ = chaine(tmp, {"a": 0, "b": 0})
        return c

    def test_analyser_marque_les_devises_quota_atteint_sans_planter(self):
        cfg = copy.deepcopy(CONFIG)
        cfg["llm"]["pause_entre_devises_s"] = 0
        with tempfile.TemporaryDirectory() as tmp:
            rapport = st.analyser(cfg, self.llm_epuise(), {"devises": {}}, {"series": {}}, {"articles": []},
                                  {"evenements": [], "sites": {}, "non_rafraichies": []}, tmp)
        self.assertEqual(len(rapport["devises"]), 9)
        self.assertTrue(all(d.get("analyse_indisponible") for d in rapport["devises"]))
        self.assertTrue(all("quota atteint" in d["raison_indisponibilite"] for d in rapport["devises"]))

    def test_synthese_quota_atteint_stoppe_sans_compter_de_tentative(self):
        devises = [{"devise": d, "score_confluence": 50, "risk_on_off": "neutre", "detail_score": [],
                    "opportunites": [], "menaces": [], "indicateurs_tableau": [], "carry": {}}
                   for d in ("EUR", "GBP")]
        devises[0]["synthese_approfondie"] = {"statut": "indisponible", "tentatives": 2}
        appels = sy.synthetiser(CONFIG, self.llm_epuise(), devises,
                                {"macro": {"series": {}}, "technique": {}, "calendrier": [], "news": []}, [],
                                None, registre={"cases": {}}, extras={}, pause_s=0)
        self.assertEqual(appels, 1)                                     # arrêt au premier QuotaAtteint
        for d in devises:
            s = d["synthese_approfondie"]
            self.assertEqual((s["statut"], s["quota_atteint"]), ("indisponible", True))
            self.assertIn("quota atteint", s["raison"])
        self.assertEqual(devises[0]["synthese_approfondie"]["tentatives"], 2)     # inchangé : pas un échec
        self.assertTrue(sy.synthese_a_faire(devises[1], CONFIG["synthese_approfondie"]))   # retentée demain


class TauxDepuisRegistre(unittest.TestCase):
    def test_registre_remplace_la_config_et_recalcule_le_carry(self):
        macro = {"taux_directeurs": {"EUR": {"taux": 2.4, "date": "2026-01-15", "source": "config (repli manuel)"},
                                     "JPY": {"taux": 1.0, "date": "2026-01-15", "source": "config (repli manuel)"},
                                     "USD": {"taux": 3.75, "date": "2026-09-01", "source": "FRED (FEDFUNDS)"}}}
        registre = {"cases": {
            "EUR|taux_directeur": {"actuel": {"valeur": "2.65%", "valeur_num": 2.65, "date_pub": "2026-09-10"}},
            "JPY|taux_directeur": {"actuel": {"valeur": "<1.25%", "valeur_num": None, "date_pub": "2026-09-18"}},
            "USD|taux_directeur": {"actuel": {"valeur": "4.00%", "valeur_num": 4.0, "date_pub": "2026-09-16"}}}}
        modifs = marche_taux.appliquer_registre_taux(macro, registre, {"ordre_devises": ["USD", "EUR", "JPY"]})
        self.assertEqual({d: (m["avant"], m["apres"]) for d, m in modifs.items()}, {"USD": (3.75, 4.0), "EUR": (2.4, 2.65)})
        self.assertEqual(macro["taux_directeurs"]["JPY"]["source"], "config (repli manuel)")    # borne non numérique : repli
        self.assertEqual(macro["taux_directeurs"]["EUR"]["repli_precedent"]["taux"], 2.4)
        self.assertEqual(macro["carry"]["mediane_g8"], 2.65)
        self.assertEqual(macro["carry"]["differentiels"], {"EUR": 0.0, "JPY": -1.65, "USD": 1.35})


class BougiesEnDouble(unittest.TestCase):
    def test_ohlc_deduplique_les_dates(self):
        from unittest import mock as m
        from agents import collecte_technique as ct
        valeurs = [{"datetime": "2026-10-08", "open": "1", "high": "2", "low": "0.5", "close": "1.1"},
                   {"datetime": "2026-10-09", "open": "1", "high": "2", "low": "0.5", "close": "1.2"},
                   {"datetime": "2026-10-09", "open": "1", "high": "2", "low": "0.5", "close": "1.3"}]
        rep = m.Mock(status_code=200, **{"json.return_value": {"status": "ok", "values": valeurs},
                                         "raise_for_status.return_value": None})
        with m.patch("requests.get", return_value=rep):
            df = ct._ohlc("EUR/USD", "1day", 10, "k")
        self.assertFalse(df.index.has_duplicates)
        self.assertEqual(len(df), 2)


class JsonTolerant(unittest.TestCase):
    def test_virgules_finales_retirees_hors_chaines(self):
        brut = '{"a": [1, 2,], "b": {"t": "x, ]", "u": "y",},}'
        self.assertEqual(L.extraire_json(brut), {"a": [1, 2], "b": {"t": "x, ]", "u": "y"}})
        self.assertEqual(L.extraire_json('```json\n{"ok": true}\n```'), {"ok": True})


if __name__ == "__main__":
    unittest.main()
