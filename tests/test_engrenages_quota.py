"""Quota Gemini et 8 engrenages (incident du 16/10/2026 : roue entièrement hachurée, quota épuisé avant la
synthèse) : réserve des derniers appels, ordre des appels, repli 100 % Python de la roue. Sans réseau."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from agents import agent_engrenages as ae, agent_strategiste as st  # noqa: E402
from core import llm as L, vue_ensemble  # noqa: E402
from tests.test_engrenages import DEVISES, EXTRAS, brut, donnees, macro  # noqa: E402
import orchestrateur  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def case(n, valeur, regle=True):
    return {"engrenage": n, "valeur": valeur, "libelle": {1: "Soutien", 0: "Neutre", -1: "Pression"}[valeur],
            "regles": [{"regle": f"règle {n}", "points": valeur}] if regle else [], "raison": None if regle else "sous les seuils"}


# Matrice d'impact du jour : 4 = prime de terme en hausse (USD −1), 6 = canal refuge (USD, JPY, CHF +1),
# 8 = aucune règle sur l'USD (pétrole décrit) -> « neutre ».
MATRICE = {"lignes": [
    {"devise": "USD", "cases": [case(1, 0, False), case(2, 0, False), case(3, 0, False), case(4, -1),
                                case(5, 0, False), case(6, 1), case(7, 0, False), case(8, 0, False)]},
    {"devise": "JPY", "cases": [case(6, 1)]}, {"devise": "CHF", "cases": [case(6, 1)]},
    {"devise": "AUD", "cases": [case(6, 0, False)]}]}
EXTRAS_MATRICE = {**EXTRAS, "dossiers": {"matrice_impact": MATRICE}}


class Faux(L.FournisseurLLM):
    """Répond une synthèse des engrenages valide, {} ailleurs ; note l'étiquette de chaque appel servi."""

    def __init__(self, modele, registre, journal):
        self.modele, self.registre, self.journal = modele, registre, journal

    def appeler_llm(self, prompt, systeme=None):
        self.registre.compter(self.modele)
        self.journal.append(L._ETIQUETTE_COURANTE[0])
        return json.dumps(brut() if L._ETIQUETTE_COURANTE[0] == "engrenages" else {})


def chaine(plafonds, utilises=0, reserve=0):
    tmp = Path(tempfile.mkdtemp())
    registre = L.RegistreQuotas(tmp / "quota.json", plafonds)
    for m in plafonds:
        for _ in range(utilises):
            registre.compter(m)
    journal = []
    c = L.FournisseurChaine([(m, Faux(m, registre, journal)) for m in plafonds], registre, reserve_engrenages=reserve)
    return c, journal, registre


def config_test():
    cfg = copy.deepcopy(CONFIG)
    cfg["llm"]["pause_entre_devises_s"] = 0
    cfg["llm"]["pause_entre_appels_s"] = 0
    cfg["chemins"] = {**cfg["chemins"], "donnees": tempfile.mkdtemp()}   # jamais l'état réel (rotation des concepts)
    cfg["synthese_approfondie"] = {**(cfg.get("synthese_approfondie") or {}), "actif": False}
    return cfg


def analyser(cfg, llm):
    with tempfile.TemporaryDirectory() as tmp:
        return st.analyser(cfg, llm, {"devises": {}}, {"series": {}}, {"articles": []},
                           {"evenements": [], "sites": {}, "non_rafraichies": []}, tmp,
                           extras_synthese=EXTRAS_MATRICE)


class QuotaAZero(unittest.TestCase):
    def setUp(self):
        L.reinitialiser_journal()
        self.cfg = config_test()
        self.llm, self.journal, _ = chaine({"a": 20, "b": 20}, utilises=20)

    def test_roue_coloree_sans_aucun_appel(self):
        sortie = ae.generer(self.cfg, self.llm, donnees(), macro(), [], DEVISES, "risk_off", EXTRAS_MATRICE)
        self.assertEqual(self.journal, [])                                       # aucun appel envoyé
        self.assertEqual((sortie["statut"], sortie["quota_atteint"], sortie["repli_python"]), ("indisponible", True, True))
        self.assertEqual(len(sortie["engrenages"]), 8)
        rapport = {"meta": {"date_rapport": "2026-10-16"}, "devises": DEVISES, "synthese_globale": {"engrenages": sortie}}
        v = vue_ensemble.calculer({}, None, None, rapport)
        for c in v["cartes"]:                                                    # aucun secteur hachuré
            self.assertTrue(c["direction"]["dollar"] or c["direction"]["risque"], c["numero"])
        par = {c["numero"]: c["direction"] for c in v["cartes"]}
        self.assertEqual((par[4]["dollar"], par[6]["dollar"], par[6]["risque"], par[8]["dollar"]),
                         ("baissier", "haussier", "risk_off", "neutre"))         # matrice d'impact
        self.assertEqual(par[1]["dollar"], "haussier")                           # majorité des engrenages 2 à 8
        self.assertTrue(v["theme"]["titre"])                                     # titre Python, jamais « non déterminé »
        self.assertEqual(v["theme"]["texte_indisponible"], ae.TEXTE_QUOTA)
        self.assertIsNone(v["theme"]["texte"])
        self.assertTrue(all(e["texte_indisponible"] == ae.TEXTE_QUOTA and not e["diagnostic"] for e in sortie["engrenages"]
                            if not e["donnees_insuffisantes"]))

    def test_titre_theme_sans_modele(self):
        sortie = ae.generer(self.cfg, self.llm, donnees(), macro(), [], DEVISES, "risk_off", EXTRAS_MATRICE)
        v = vue_ensemble.calculer({}, None, None, {"devises": DEVISES, "synthese_globale": {"engrenages": sortie}})
        attendu = vue_ensemble.TITRE_SIGNAUX_MIXTES if not v["theme"]["coherence"]["theme_fort"] else \
            vue_ensemble._titre_theme(v["theme"]["direction"], {"devises": DEVISES})
        self.assertEqual(v["theme"]["titre"], attendu)
        self.assertEqual(v["theme"]["titre"], "Aversion au risque, dollar en tête")   # 2, 3, 5, 6, 7 haussiers ; VIX 31

    def test_resume_du_run(self):
        sortie = ae.generer(self.cfg, self.llm, donnees(), macro(), [], DEVISES, "risk_off", EXTRAS_MATRICE)
        ligne = orchestrateur.ligne_quota(self.llm.etat_quota(), sortie)
        self.assertTrue(ligne.startswith("Gemini : 40/40, engrenages : en attente"), ligne)
        self.assertEqual(orchestrateur.ligne_quota({"appels_aujourdhui": 17, "plafond_jour": 60}, {"statut": "ok"}),
                         "Gemini : 17/60, engrenages : fait")


class QuotaPartiel(unittest.TestCase):
    def setUp(self):
        L.reinitialiser_journal()
        self.cfg = config_test()

    def test_engrenages_avant_les_devises(self):
        llm, journal, _ = chaine({"a": 1})                    # un seul appel possible aujourd'hui
        rapport = analyser(self.cfg, llm)
        self.assertEqual(journal, ["engrenages"])
        self.assertEqual(rapport["synthese_globale"]["engrenages"]["statut"], "ok")
        self.assertTrue(all(d.get("analyse_indisponible") for d in rapport["devises"]))

    def test_reserve_jamais_consommee_par_autre_chose(self):
        llm, journal, registre = chaine({"a": 20, "b": 20}, utilises=16, reserve=8)   # 8 restants = la réserve
        L.definir_etiquette("analyse:EUR")
        with self.assertRaises(L.QuotaAtteint):
            llm.appeler_llm("x")
        self.assertEqual(journal, [])                                                  # refus avant tout envoi
        L.definir_etiquette("engrenages")
        llm.appeler_llm("x")
        self.assertEqual(journal, ["engrenages"])
        self.assertFalse(registre.engrenages_faits)

    def test_reserve_liberee_apres_la_synthese_du_jour(self):
        llm, journal, registre = chaine({"a": 20}, utilises=14, reserve=8)            # 6 restants, tous réservés
        rapport = analyser(self.cfg, llm)
        self.assertEqual(journal[0], "engrenages")
        self.assertTrue(registre.engrenages_faits)
        self.assertEqual(len(journal), 6)                                              # puis les devises
        self.assertTrue(all(e.startswith("analyse:") for e in journal[1:]))
        self.assertEqual(rapport["synthese_globale"]["engrenages"]["statut"], "ok")
        self.assertTrue(L.RegistreQuotas(registre.chemin, {"a": 20}).engrenages_faits)  # persisté pour les compléments

    def test_complement_horaire_bloque_tant_que_les_engrenages_manquent(self):
        llm, journal, _ = chaine({"a": 20}, utilises=13, reserve=8)                   # 7 restants
        L.definir_etiquette("synthese:EUR")
        with self.assertRaises(L.QuotaAtteint) as ctx:
            llm.appeler_llm("x")
        self.assertIn("réservés à la synthèse des engrenages", str(ctx.exception))
        self.assertEqual(llm.etat_quota()["refus_reserve_ce_run"], 1)


if __name__ == "__main__":
    unittest.main()
