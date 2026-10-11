"""Dossier hebdomadaire d'économiste : précédents (Python), vérification des chiffres, faux LLM. Sans réseau."""
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from agents import agent_dossier_hebdo as ah, agent_redacteur as ar  # noqa: E402
from core import llm as L, precedents as pr  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
FIN = date.today()


def quotidien(f, jours=5 * 366):
    return [[(FIN - timedelta(days=jours - i)).isoformat(), f(i)] for i in range(jours + 1)]


def historiques(cyclique=True):
    vix = (lambda i: 15 + 10 * ((i // 60) % 2)) if cyclique else (lambda i: 10 + i / 20)
    return {"series": {"vix": {"points": quotidien(vix), "frequence": "quotidien"},
                       "FX_AUD": {"points": quotidien(lambda i: 0.7 + (i % 90) / 1000), "frequence": "quotidien"},
                       "FX_JPY": {"points": quotidien(lambda i: 140 + (i % 90) / 10), "frequence": "quotidien"}}}


class Precedents(unittest.TestCase):
    def test_cas_comparables_medianes_et_reference(self):
        p = pr.calculer(historiques(), "VIX", ("brute", "vix"), "AUD")
        self.assertTrue(p["suffisant"])
        self.assertGreaterEqual(p["cas"]["1m"]["n"], 5)
        self.assertLessEqual(p["cas"]["6m"]["n"], p["cas"]["1m"]["n"])           # horizon non écoulé : cas exclus
        self.assertIn("reference_tous_episodes", p)
        self.assertIn("Tous épisodes confondus", p["texte"])

    def test_force_des_devises_cotees_par_dollar(self):
        h = {"series": {"FX_JPY": {"points": [["2026-01-01", 100.0], ["2026-02-01", 125.0]]}}}
        self.assertEqual(pr._force(h, "JPY")[-1][1], 1 / 125.0)                    # yen plus faible : force en baisse

    def test_sous_cinq_cas_precedents_insuffisants(self):
        p = pr.calculer(historiques(cyclique=False), "VIX", ("brute", "vix"), "AUD")   # série toujours croissante
        if not p["suffisant"]:
            self.assertIn("Précédents insuffisants", p["texte"])
        court = pr.calculer({"series": {}}, "VIX", ("brute", "vix"), "AUD")
        self.assertFalse(court["suffisant"])
        self.assertIn("insuffisants", pr.pour_engrenage({}, "6")[0]["texte"])


class Chiffres(unittest.TestCase):
    def test_seuls_les_chiffres_fournis_passent(self):
        aut = ah._valeurs({"x": 121.3848, "t": "p62, -167 pb", "y": [2.8]}, set())
        self.assertEqual(ah.verifier_chiffres("Indice à 121,38 (+2,8 %). Au 62e percentile, écart de -167 pb.", aut)[1], 0)
        texte, n = ah.verifier_chiffres("Le CAD a perdu 3,7 %. Semaine 2026-W41.", aut)
        self.assertEqual((texte, n), ("Semaine 2026-W41.", 1))


def contexte():
    return {"tableau": {"lignes": [{"devise": "EUR", "cellules": {"x": {"valeur": 3.08, "percentile_5a": 95}}}]},
            "precedents_calcules": [{"suffisant": True, "texte": "Depuis 2021, 47 épisodes : EUR médiane +0,19 % à 1 mois.",
                                     "cas": {"1m": {"n": 47}}}]}


class Normalisation(unittest.TestCase):
    def brut(self, **x):
        b = {"constat": "Le 2 ans allemand est à 3,08 %, au 95e percentile. Il a gagné 40 pb.",
             "mecanisme": "Un écart qui se resserre soutient l'euro.", "ce_qui_pourrait_tout_changer": "Une BCE accommodante.",
             "implications": [{"devise": "EUR", "texte": "Soutien."}, {"devise": "XXX", "texte": "?"}],
             "precedent": "47 épisodes : médiane +0,19 % à 1 mois.", "comprendre": "c", "desk": "d"}
        b.update(x)
        return b

    def test_phrase_au_chiffre_invente_retiree_et_precedent_conserve(self):
        s = ah.normaliser_engrenage(self.brut(), "2", contexte(), {})
        self.assertEqual(s["constat"], "Le 2 ans allemand est à 3,08 %, au 95e percentile.")
        self.assertTrue(any("chiffre absent" in c for c in s["controles"]))
        self.assertEqual([i["devise"] for i in s["implications"]], ["EUR"])
        self.assertNotIn("precedent_impose", s)

    def test_precedents_insuffisants_texte_python_impose(self):
        ctx = contexte()
        ctx["precedents_calcules"] = [{"suffisant": False, "texte": "Précédents insuffisants (3 cas comparables, minimum 5)."}]
        s = ah.normaliser_engrenage(self.brut(precedent="Historiquement le dollar monte de 2 %."), "2", ctx, {})
        self.assertEqual(s["precedent"], "Précédents insuffisants (3 cas comparables, minimum 5).")
        self.assertTrue(s["precedent_impose"])

    def test_vocabulaire_or_et_ordres(self):
        s = ah.normaliser_engrenage(self.brut(mecanisme="L'or s'envole. Achetez l'EUR/USD."), "2", contexte(), {})
        self.assertEqual(s["mecanisme"], "L'indice or (proxy) progresse.")


class Faux(L.FournisseurLLM):
    def __init__(self, panne_a=None):
        self.appels, self.panne_a = [], panne_a

    def appeler_llm(self, prompt, systeme=None):
        self.appels.append(prompt)
        if self.panne_a is not None and len(self.appels) > self.panne_a:
            raise L.QuotaAtteint("quota")
        if "synthèse finale" in prompt:
            return json.dumps({"theme_semaine": "Le dollar domine.", "chaines": [{"titre": "t", "maillons": [
                {"engrenage": 2, "texte": "Taux"}, {"engrenage": 5, "texte": "Dollar"}]}], "conflits": [],
                "ce_qui_pourrait_tout_changer": "Une surprise sur l'inflation."})
        return json.dumps({"constat": "Constat de la semaine.", "mecanisme": "m", "ce_qui_pourrait_tout_changer": "c",
                           "implications": [{"devise": "USD", "texte": "t"}], "precedent": "p", "comprendre": "c", "desk": "d"})


DOSSIERS = {"genere_le": "2026-10-11T07:00:00+00:00",
            "engrenages": {str(n): {"numero": n, "titre": "x", "lignes": []} for n in range(1, 9)}}
PRECEDENTS = {str(n): [{"suffisant": False, "texte": "Précédents insuffisants."}] for n in range(1, 9)}


class Generer(unittest.TestCase):
    def test_neuf_appels_huit_engrenages_et_synthese(self):
        llm = Faux()
        r = ah.generer(CONFIG, llm, DOSSIERS, PRECEDENTS, None)
        self.assertEqual(len(llm.appels), 9)
        self.assertTrue(all(e["statut"] == "ok" for e in r["engrenages"].values()))
        self.assertEqual(r["synthese"]["statut"], "ok")
        self.assertFalse(ah.a_faire(r))

    def test_quota_atteint_puis_reprise_ne_refait_que_le_manquant(self):
        llm = Faux(panne_a=3)
        r = ah.generer(CONFIG, llm, DOSSIERS, PRECEDENTS, None)
        self.assertEqual(len(llm.appels), 4)                                         # arrêt net au premier quota
        self.assertEqual(sum(e["statut"] == "ok" for e in r["engrenages"].values()), 3)
        self.assertIn("quota atteint", r["synthese"]["raison"])
        self.assertTrue(ah.a_faire(r))
        llm2 = Faux()
        r2 = ah.generer(CONFIG, llm2, DOSSIERS, PRECEDENTS, None, existant=r)
        self.assertEqual(len(llm2.appels), 6)                                        # 5 engrenages + synthèse
        self.assertFalse(ah.a_faire(r2))

    def test_synthese_seulement_avec_cinq_engrenages(self):
        llm = Faux(panne_a=4)
        r = ah.generer(CONFIG, llm, DOSSIERS, PRECEDENTS, None)
        self.assertEqual(r["synthese"]["statut"], "indisponible")


class RenduNotion(unittest.TestCase):
    def test_page_hebdo_toggles_et_callouts(self):
        r = ah.generer(CONFIG, Faux(), DOSSIERS, PRECEDENTS, None)
        blocs = ar._blocs_dossier_hebdo(r)
        self.assertEqual(sum(b["type"] == "toggle" for b in blocs), 8)
        self.assertIn("blue_background", [b["callout"]["color"] for b in blocs if b["type"] == "callout"])
        enfants = blocs[[b["type"] for b in blocs].index("toggle")]["toggle"]["children"]
        self.assertTrue(any("imposé" in "".join(f["text"]["content"] for f in b["paragraph"]["rich_text"])
                            for b in enfants if b["type"] == "paragraph"))


if __name__ == "__main__":
    unittest.main()
