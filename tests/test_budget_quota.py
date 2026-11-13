"""Correctif quota du 02/11/2026 : budget du jour par catégorie, 2 appels au plus par analyse, 503 = un nouvel essai
sur le même modèle, échecs typés, devises en 3 appels groupés, rejeu du 02/11 avec 50 % d'échecs simulés.
Sans réseau : requests.post est remplacé, aucun appel LLM réel."""
import copy
import json
import os
import random
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests
import yaml

from agents import agent_rapport as ar, agent_strategiste as st
from core import evaluation, llm as L, rapport_jour as rj
from tests.test_engrenages import brut as brut_engrenages
from tests.test_engrenages_quota import EXTRAS_MATRICE
import orchestrateur

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
BUDGET = CONFIG["llm"]["budget"]
MODELES = [e["modele"] for e in CONFIG["llm"]["modeles"]]


class Rep:
    """Réponse HTTP simulée de l'API Gemini."""

    def __init__(self, code, texte=""):
        self.status_code, self.text, self.headers = code, json.dumps({"error": code}) if code != 200 else "", {}
        self._corps = {"candidates": [{"content": {"parts": [{"text": texte}]}}]}

    def json(self):
        return self._corps

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Server Error", response=self)


def repondre(prompt: str) -> str:
    """Réponse valide selon l'étiquette de l'appel en cours."""
    etiquette = L._ETIQUETTE_COURANTE[0]
    if etiquette == "engrenages":
        return json.dumps(brut_engrenages())
    if etiquette.startswith("analyses:"):
        devises = re.search(r"chacune de ces devises : ([A-Z, ]+), avec", prompt).group(1).split(", ")
        return json.dumps({"analyses": {d: {"devise": d, "detail_score": [], "synthese_une_phrase": f"{d} stable."}
                                        for d in devises}})
    if etiquette == "rapport:redaction":
        return json.dumps({"synthese": "Les catalyseurs dominent la semaine.", "conclusion": "Prudence avant les décisions."})
    if etiquette == "rapport:analyse":
        return json.dumps({"watchlist": {}, "communiques": {}, "plan": "Avant la séance, relire les seuils."})
    return json.dumps({"commentaire": "Texte.", "validation": "ok"})


class Simulateur:
    """requests.post simulé : `echoue(n)` dit si la n-ième requête HTTP renvoie un 503."""

    def __init__(self, echoue):
        self.echoue, self.n, self.par_modele, self.suite = echoue, 0, {}, []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.n += 1
        modele = re.search(r"models/([^:]+):", url).group(1)
        self.par_modele[modele] = self.par_modele.get(modele, 0) + 1
        echec = self.echoue(self.n)
        self.suite.append((L._ETIQUETTE_COURANTE[0], modele, 503 if echec else 200))
        if echec:
            return Rep(503)
        return Rep(200, repondre(json["contents"][0]["parts"][0]["text"]))


def chaine_reelle(tmp, complet=True, lundi=True, budget=BUDGET):
    """Vraie chaîne de 3 FournisseurGemini (pause et backoff à 0), vrai registre dans un dossier temporaire."""
    cfg = copy.deepcopy(CONFIG)
    cfg["llm"]["fichier_quota"] = str(Path(tmp) / "quota_llm.json")
    cfg["llm"]["budget"] = budget
    for e in cfg["llm"]["modeles"]:
        e.update({"pause_min_s": 0, "backoff_429_s": 0})
    with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "cle-de-test"}), \
            mock.patch.object(L, "Path", side_effect=lambda *a: Path(*a)):
        c = L._creer_chaine(cfg)
    c.configurer_budget(budget, complet=complet, lundi=lundi)
    return c, cfg


def config_analyse(cfg):
    cfg = copy.deepcopy(cfg)
    cfg["llm"]["pause_entre_devises_s"] = 0
    cfg["llm"]["pause_entre_appels_s"] = 0
    cfg["chemins"] = {**cfg["chemins"], "donnees": tempfile.mkdtemp()}
    cfg["synthese_approfondie"] = {**(cfg.get("synthese_approfondie") or {}), "actif": False}
    return cfg


def essayer(llm, etiquette, tentatives=2):
    """Boucle d'un agent ordinaire : nouvel essai sur échec, repli Python au bout (jamais d'exception)."""
    L.definir_etiquette(etiquette)
    for _ in range(tentatives):
        try:
            return llm.appeler_llm("x")
        except L.QuotaAtteint:
            return None
        except Exception:  # noqa: BLE001
            L.repli_modele_suivant(llm)
    return None


def run_du_matin(llm, cfg):
    """Ordre des appels du run complet du 02/11 : engrenages et devises (stratège), le reste, puis le rapport du jour."""
    with tempfile.TemporaryDirectory() as tmp:
        rapport = st.analyser(config_analyse(cfg), llm, {"devises": {}}, {"series": {}}, {"articles": []},
                              {"evenements": [], "sites": {}, "non_rafraichies": []}, tmp,
                              extras_synthese=EXTRAS_MATRICE)
    for d in CONFIG["devises"]:                       # synthèses approfondies par devise
        essayer(llm, f"synthese:{d}")
    for etiquette in ("critique", "consequences:mensuel", "paires:synthese"):
        essayer(llm, etiquette)
    for d in CONFIG["devises"]:                       # commentaires weekly (lundi)
        essayer(llm, f"weekly:{d}", tentatives=1)
    r = rj.calculer(RACINE, CONFIG)
    with mock.patch.object(ar, "attribution_modele", return_value={"libelle": "faux"}):
        textes = ar.rediger(r, llm)
    return rapport, textes


class Rejeu0211(unittest.TestCase):
    def setUp(self):
        L.reinitialiser_journal()
        self.tmp = tempfile.mkdtemp()

    def _rejouer(self, echoue):
        llm, cfg = chaine_reelle(self.tmp)
        sim = Simulateur(echoue)
        with mock.patch.object(L.requests, "post", sim), mock.patch("time.sleep"):
            rapport, textes = run_du_matin(llm, cfg)
        return llm, sim, rapport, textes

    def test_une_requete_sur_deux_en_echec(self):
        llm, sim, rapport, textes = self._rejouer(lambda n: n % 2 == 1)          # 50 % d'échecs, le premier aussi
        reg = llm.registre
        self.assertLessEqual(reg.total_jour(), 45)                                # plafond du run du matin
        # V6.1-bis : réponses reçues dans le budget, 503 à part ; chaque requête HTTP comptée une fois
        self.assertEqual(reg.total_jour() + reg.donnees["pannes"], sim.n)
        # rédaction du rapport faite ; l'analyse peut attendre si le plafond de sécurité des pannes (20) est atteint
        self.assertIn(textes["statut"], ("ok", "partiel"))
        self.assertIn("1", textes["parties_faites"])
        self.assertTrue(textes.get("synthese"))
        self.assertEqual(rapport["synthese_globale"]["engrenages"]["statut"], "ok")
        self.assertEqual(rapport["synthese_globale"]["devises_indisponibles"], [])
        self.assertTrue(all(n <= 2 for n in reg.run_etiquettes.values()), reg.run_etiquettes)
        # 503 au premier essai : le nouvel essai va au MÊME modèle, pour la même analyse
        premiers = [i for i, (e, m, c) in enumerate(sim.suite)
                    if c == 503 and not (i and sim.suite[i - 1] == (e, m, 503))]
        self.assertTrue(premiers)
        for i in premiers:          # sauf refus du budget (le « reste » s'arrête avant les réserves) : aucune suite
            if i + 1 < len(sim.suite) and sim.suite[i + 1][0] == sim.suite[i][0]:
                self.assertEqual(sim.suite[i + 1][1], sim.suite[i][1], i)
        self.assertGreater(sum(1 for i in premiers if i + 1 < len(sim.suite) and sim.suite[i + 1][0] == sim.suite[i][0]),
                           len(premiers) // 2)
        self.assertGreater(reg.run_echecs.get("503", 0), 0)

    def test_cinquante_pour_cent_aleatoire_plafond_et_reserve_du_rapport(self):
        for graine in range(12):
            L.reinitialiser_journal()
            self.tmp = tempfile.mkdtemp()
            alea = random.Random(graine)
            llm, sim, rapport, textes = self._rejouer(lambda n: alea.random() < 0.5)
            reg = llm.registre
            self.assertLessEqual(reg.total_jour(), 45, graine)
            self.assertTrue(all(n <= 2 for n in reg.run_etiquettes.values()), (graine, reg.run_etiquettes))
            # la réserve du rapport n'a jamais été prise par une autre section : il a eu ses requêtes
            # V6.1-bis : le budget ne compte que les réponses reçues ; le rapport a bien eu ses essais (envois)
            attendu = 1 if reg.donnees["pannes"] >= L.PLAFOND_PANNES_JOUR - 5 else 2   # plafond de sécurité atteint : 1 essai
            self.assertGreaterEqual(sum(n for k, n in reg.run_etiquettes.items() if k.startswith("rapport:")), attendu, graine)
            if textes.get("quota_atteint"):   # seul refus admis : le plafond de sécurité des tentatives en panne
                self.assertIn("tentatives en panne", textes["detail_quota"], graine)
            self.assertIn(textes["statut"], ("ok", "partiel", "indisponible"))
            b = reg.resume_budget()
            self.assertEqual(sum(b["consomme_run"].values()), reg.total_jour())


class Budget(unittest.TestCase):
    def setUp(self):
        L.reinitialiser_journal()
        self.tmp = tempfile.mkdtemp()

    def test_503_puis_plafond_de_deux_appels_sans_modele_suivant(self):
        llm, _ = chaine_reelle(self.tmp)
        sim = Simulateur(lambda n: True)
        with mock.patch.object(L.requests, "post", sim), mock.patch("time.sleep"):
            self.assertIsNone(essayer(llm, "critique"))
        self.assertEqual(sim.n, 2)                                     # 1 essai + 1 nouvel essai, puis repli Python
        self.assertEqual(sim.par_modele, {MODELES[0]: 2})
        self.assertEqual(llm.registre.run_echecs.get("503"), 2)

    def test_complement_ne_rejoue_pas_une_analyse_deja_en_echec_deux_fois(self):
        # Lot V6.1 : seuls les échecs de FORMAT ou de contrôle comptent (un 503 est transitoire, voir test_v61.py)
        def post(url, headers=None, json=None, timeout=None):
            return Rep(200, "réponse sans JSON")
        for complet in (True, False):                                   # matin puis complément : 2 runs en échec
            llm, _ = chaine_reelle(self.tmp, complet=complet)
            L.definir_etiquette("analyses:JPY-CHF-CAD")
            with mock.patch.object(L.requests, "post", post), mock.patch("time.sleep"):
                for _ in range(2):
                    try:
                        L.extraire_json(llm.appeler_llm("x"))
                    except L.PlafondAnalyse:
                        break
                    except ValueError:
                        L.repli_modele_suivant(llm)
        llm, _ = chaine_reelle(self.tmp, complet=False)
        sim = Simulateur(lambda n: False)
        L.definir_etiquette("analyses:JPY-CHF-CAD")
        with mock.patch.object(L.requests, "post", sim), self.assertRaises(L.PlafondAnalyse) as ctx:
            llm.appeler_llm("x")
        self.assertEqual(sim.n, 0)
        self.assertIn("déjà en échec 2 fois", str(ctx.exception))
        self.assertIn("analyses:JPY-CHF-CAD", llm.registre.resume_budget()["abandonnees"])

    def test_reserves_prioritaires_et_plafond_du_matin(self):
        llm, _ = chaine_reelle(self.tmp, lundi=True)
        reg = llm.registre
        self.assertEqual(reg.prevu(), {"engrenages": 1, "rapport": 10, "devises": 3})  # lot V9.4 : appels groupés de la Synthèse
        self.assertEqual(reg.plafond_run(), 45)
        L.definir_etiquette("synthese:EUR")
        sim = Simulateur(lambda n: False)
        with mock.patch.object(L.requests, "post", sim), mock.patch("time.sleep"):
            for i in range(60):
                L.definir_etiquette(f"synthese:{i}")
                try:
                    llm.appeler_llm("x")
                except L.BudgetEpuise:
                    break
        self.assertEqual(sim.n, 45 - 2 - 20 - 6)                        # le reste s'arrête avant les réserves
        L.definir_etiquette("rapport:redaction")
        with mock.patch.object(L.requests, "post", sim), mock.patch("time.sleep"):
            llm.appeler_llm("x")                                       # le rapport passe : sa réserve est intacte
        self.assertEqual(reg.run_categories["rapport"], 1)
        llm2, _ = chaine_reelle(self.tmp, complet=False)                # complément : quota gratuit entier (60)
        self.assertEqual(llm2.registre.plafond_run(), 60)

    def test_types_d_echec(self):
        self.assertEqual(L.type_echec(requests.exceptions.ReadTimeout()), "delai")
        self.assertEqual(L.type_echec(requests.exceptions.HTTPError(response=Rep(503))), "503")
        self.assertEqual(L.type_echec(L.QuotaJournalierEpuise("x")), "429")
        self.assertEqual(L.type_echec(json.JSONDecodeError("x", "", 0)), "json_invalide")
        self.assertEqual(L.type_echec(AttributeError("'list' object has no attribute 'get'")), "rejet_controle")
        self.assertEqual(L.categorie_budget("analyses:USD-EUR-GBP"), "devises")
        self.assertEqual(L.categorie_budget("rapport:analyse"), "rapport")
        self.assertEqual(L.categorie_budget("weekly:USD"), "reste")

    def test_reponse_json_invalide_typee(self):
        llm, _ = chaine_reelle(self.tmp)

        def post(url, headers=None, json=None, timeout=None):
            return Rep(200, "[1, 2]")
        with mock.patch.object(L.requests, "post", post), mock.patch("time.sleep"):
            L.definir_etiquette("paires:synthese")
            try:
                st.valider_analyse(L.extraire_json(llm.appeler_llm("x")), "USD")
            except ValueError:
                L.repli_modele_suivant(llm)
        self.assertEqual(llm.registre.run_echecs, {"json_invalide": 1})

    def test_resume_du_run_budget_prevu_et_consomme(self):
        llm, _ = chaine_reelle(self.tmp, lundi=True)
        with mock.patch.object(L.requests, "post", Simulateur(lambda n: n == 1)), mock.patch("time.sleep"):
            essayer(llm, "engrenages")
        ligne = orchestrateur.ligne_quota(llm.etat_quota(), {"statut": "ok"})
        self.assertIn("Budget (run complet, lundi, plafond 45)", ligne)
        self.assertIn("prévu engrenages 1 analyse (≤ 2 requêtes); rapport du jour 10 analyses (≤ 20 requêtes)", ligne)
        self.assertIn("consommé ce run : engrenages 1, rapport du jour 0, devises 0, reste 0", ligne)   # le 503 : hors budget
        self.assertIn("tentatives en panne (hors budget) : 1 ce run, 1/20 aujourd'hui", ligne)
        self.assertIn("échecs ce run : 503 × 1", ligne)


class AnalyseDevises(unittest.TestCase):
    def setUp(self):
        L.reinitialiser_journal()

    def test_liste_json_ne_fait_plus_planter_le_run(self):
        """02/11 08:15 : le modèle répond une liste JSON -> AttributeError, run entier perdu. Désormais : repli Python."""
        class Liste(L.FournisseurLLM):
            def appeler_llm(self, prompt, systeme=None):
                return json.dumps(brut_engrenages()) if L._ETIQUETTE_COURANTE[0] == "engrenages" else "[]"
        cfg = config_analyse(CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            rapport = st.analyser(cfg, Liste(), {"devises": {}}, {"series": {}}, {"articles": []},
                                  {"evenements": [], "sites": {}, "non_rafraichies": []}, tmp,
                                  extras_synthese=EXTRAS_MATRICE)
        self.assertEqual(len(rapport["devises"]), 9)
        self.assertTrue(all(d.get("texte_automatique") for d in rapport["devises"]))

    def test_catalogue_limite_aux_sources_citees(self):
        catalogue = [{"id": f"src_{i:03d}", "source": "x"} for i in range(1, 6)]
        self.assertEqual([c["id"] for c in st.catalogue_utile(catalogue, {"a": "src_002"}, [{"b": "src_004"}])],
                         ["src_002", "src_004"])

    def test_groupes_fixes_de_trois(self):
        self.assertEqual(st.groupes_devises(CONFIG), [["USD", "EUR", "GBP"], ["JPY", "CHF", "CAD"], ["AUD", "NZD", "CNY"]])


def test_auto_evaluation_sans_scipy():
    precedent = {"meta": {"date_rapport": "2026-10-26"},
                 "synthese_globale": {"classement_devises": [{"devise": d, "score_confluence": s}
                                                             for d, s in (("USD", 70), ("EUR", 40), ("JPY", 50))]},
                 "prix_cloture": {"USD": 100.0, "EUR": 1.10, "JPY": 150.0}}
    with mock.patch.dict("sys.modules", {"scipy": None}):
        r = evaluation.evaluer(precedent, {"USD": 101.0, "EUR": 1.09, "JPY": 150.1}, 0.15)
    assert r is not None and isinstance(r["correlation_classement_spearman"], float)
