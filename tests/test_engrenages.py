"""Synthèse « 8 engrenages » : signaux Python, normalisation, concept du jour, échecs, rendu. Sans réseau."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from agents import agent_engrenages as ae, agent_redacteur as ar, agent_strategiste as st  # noqa: E402
from core import llm as L  # noqa: E402
from core.tracabilite import valider_rapport  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def donnees():
    return {"macro": {"series": {"vix": {"valeur": 31.0, "date": "2026-10-08", "source_id": "src_001"},
                                 "sp500": {"valeur": 7000, "date": "2026-10-09", "variation_pct": -2.1, "source_id": "src_002"}}},
            "technique": {"USD": {"variation_5j_pct": 0.9, "rsi": 70, "source_id": "src_003"},
                          "AUD": {"variation_5j_pct": -1.0, "source_id": "src_003"}, "NZD": {"variation_5j_pct": -0.8},
                          "CAD": {"variation_5j_pct": -0.4}, "JPY": {"variation_5j_pct": 0.6}, "CHF": {"variation_5j_pct": 0.5}},
            "calendrier": [], "news": [{"titre": "Oil jumps as OPEC cuts output", "source_id": "src_004"}]}


def macro():
    dates = ["2026-09-25", "2026-09-28", "2026-10-02"]
    return {"graphiques_marche": {"dollar_large": {"dates": dates, "valeurs": [120.0, 120.5, 121.5]},
                                  "vix": {"dates": dates, "valeurs": [20.0, 25.0, 31.0]},
                                  "wti": {"dates": dates, "valeurs": [80.0, 84.0, 88.0]}}}


DEVISES = [{"devise": "USD", "score_confluence": 80}, {"devise": "AUD", "score_confluence": 30},
           {"devise": "JPY", "score_confluence": 65}]
EXTRAS = {"indice_surprise": {"USD": {"indice": 0.8}, "AUD": {"indice": -0.4}},
          "registre": {"cases": {"USD|rendement_2a": {"actuel": {"valeur": "4.90%", "date_pub": "2026-10-09"},
                                                      "variation_pb": 15.0},
                                 "USD|taux_directeur": {"actuel": {"valeur": "4.00%", "date_pub": "2026-09-16"},
                                                        "precedent": {"valeur": "3.75%"}}}}}


def sig():
    return ae.signaux(CONFIG, donnees(), macro(), DEVISES, "risk_off", EXTRAS, ae._Catalogue([]))


def brut(**s):
    b = {"engrenages": [{"numero": n, "diagnostic": f"Diagnostic {n}. Suite.",
                         "direction": {"dollar": "baissier", "risque": "risk_on", "texte": "nuance"},
                         "comprendre": "c", "desk": "d", "conviction": {"niveau": "eleve", "justification": "j"},
                         "source_ids": ["src_001"]} for n in range(1, 9)],
         "chaines": [{"titre": "t", "maillons": [{"engrenage": 3, "texte": "CPI US fort", "source_id": "src_001"},
                                                 {"engrenage": 2, "texte": "2 ans en hausse", "source_id": "src_999"}]}],
         "conflits": [], "concept": {"explication": "e", "exemple": "x", "source_ids": ["src_001"]}}
    b.update(s)
    return b


class Signaux(unittest.TestCase):
    def test_directions_calculees_et_conviction(self):
        s = sig()
        self.assertEqual((s[2]["dollar"], s[3]["dollar"], s[5]["risque"], s[5]["dollar"]),
                         ("haussier", "haussier", "risk_off", "haussier"))      # 2 ans +15 pb, surprise +0,8, VIX 31
        self.assertEqual((s[7]["dollar"], s[7]["risque"]), ("haussier", "risk_off"))
        self.assertIsNone(s[4]["dollar"]); self.assertIsNone(s[4]["conviction"])   # fiscalité : pas de règle
        self.assertEqual(s[1]["risque"], "risk_off")                                # = biais global calculé
        self.assertEqual(s[1]["conviction"], "eleve")                               # 2, 3, 5, 7 d'accord avec le thème
        self.assertTrue(all(d["source_id"] for d in s[2]["donnees"]))

    def test_conflit_detecte_quand_deux_engrenages_s_opposent(self):
        s = sig()
        s[3]["dollar"] = "baissier"
        self.assertIn([1, 3], [c["engrenages"] for c in ae.conflits_detectes(s)])


class Normalisation(unittest.TestCase):
    def test_direction_python_conservee_et_desaccord_signale(self):
        n = ae.normaliser(brut(), sig(), [], None, CONFIG)
        e2 = n["engrenages"][1]
        self.assertEqual(e2["direction"]["dollar"], "haussier")                 # le modèle disait « baissier »
        self.assertTrue(any("engrenage 2" in c for c in n["controles"]))
        self.assertEqual(n["engrenages"][3]["direction"]["dollar"], "baissier")   # fiscalité : direction du modèle
        self.assertEqual(n["engrenages"][3]["conviction"]["niveau"], "moyen")     # « élevée » plafonnée
        self.assertIsNone(n["engrenages"][1]["direction"]["risque"])   # pas de règle risque en 2 : jamais deviné
        self.assertEqual(n["engrenages"][3]["direction"]["origine"]["dollar"], "modèle")

    def test_engrenage_absent_ou_sans_donnees_dit_donnees_insuffisantes(self):
        b = brut(engrenages=[e for e in brut()["engrenages"] if e["numero"] != 6])
        s = sig()
        s[8]["donnees"] = []
        n = ae.normaliser(b, s, [], None, CONFIG)
        self.assertEqual(n["engrenages"][5]["diagnostic"], ae.TEXTE_INSUFFISANT)
        self.assertEqual(n["engrenages"][7]["diagnostic"], ae.TEXTE_INSUFFISANT)
        self.assertIsNone(n["engrenages"][7]["conviction"]["niveau"])
        self.assertTrue(any("engrenage 6" in c for c in n["controles"]))

    def test_conflit_python_toujours_affiche_et_ordres_retires(self):
        b = brut()
        b["engrenages"][0]["diagnostic"] = "Le dollar domine. Achetez l'USD/JPY maintenant."
        n = ae.normaliser(b, sig(), [{"engrenages": [3, 5], "texte": "conflit calculé"}], None, CONFIG)
        self.assertEqual(n["conflits"][0]["origine"], "calcul Python")
        self.assertNotIn("Achetez", n["engrenages"][0]["diagnostic"])
        self.assertTrue(any("ordre" in c for c in n["controles"]))

    def test_maillon_sans_source_valide_marque_non_source(self):
        n = ae.normaliser(brut(), sig(), [], None, CONFIG)
        n["statut"] = "ok"
        rapport = {"sources_citees": [{"id": "src_001"}], "devises": [], "synthese_globale": {"engrenages": n}}
        valider_rapport(rapport, "marquer")
        maillons = n["chaines"][0]["maillons"]
        self.assertEqual([m["non_sourcee"] for m in maillons], [False, True])


class Concepts(unittest.TestCase):
    def setUp(self):
        self.concepts = ae.charger_concepts()
        self.etat = Path(tempfile.mkdtemp()) / "rotation.json"

    def test_fichier_de_20_concepts_et_hors_prompt_des_analyses(self):
        self.assertGreaterEqual(len(self.concepts), 20)
        self.assertTrue(all(c["definition"] and c["mots_cles"] for c in self.concepts))
        self.assertNotIn("Concepts de formation", st.charger_connaissances())

    def test_rotation_sans_repetition_puis_nouveau_cycle(self):
        vus = []
        for i in range(len(self.concepts)):
            vus.append(ae.choisir_concept(self.concepts, "", self.etat, date(2026, 1, 1 + i % 28) if i < 28 else None)["id"])
        self.assertEqual(len(set(vus)), len(self.concepts))
        suivant = ae.choisir_concept(self.concepts, "", self.etat, date(2026, 3, 1))
        self.assertEqual(suivant["cycle"], 2)

    def test_priorite_a_l_actualite_et_meme_concept_le_meme_jour(self):
        c = ae.choisir_concept(self.concepts, "vix vix volatilité peur stress", self.etat, date(2026, 10, 10))
        self.assertEqual(c["id"], "volatilite_implicite")
        self.assertEqual(ae.choisir_concept(self.concepts, "carry carry", self.etat, date(2026, 10, 10))["id"],
                         "volatilite_implicite")


class Faux(L.FournisseurLLM):
    def __init__(self, reponses):
        self.reponses, self.prompts = list(reponses), []

    def appeler_llm(self, prompt, systeme=None):
        self.prompts.append(prompt)
        r = self.reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Generer(unittest.TestCase):
    def config(self):
        c = copy.deepcopy(CONFIG)
        c["chemins"] = {**c["chemins"], "donnees": tempfile.mkdtemp()}
        return c

    def test_un_seul_appel_et_statut_ok(self):
        llm = Faux([json.dumps(brut())])
        r = ae.generer(self.config(), llm, donnees(), macro(), [], DEVISES, "risk_off", EXTRAS)
        self.assertEqual((r["statut"], len(llm.prompts), len(r["engrenages"])), ("ok", 1, 8))
        self.assertIsNotNone(r["concept"])

    def test_quota_atteint_marque_indisponible_sans_tentative(self):
        r = ae.generer(self.config(), Faux([L.QuotaAtteint("quota")]), donnees(), macro(), [], DEVISES,
                       "risk_off", EXTRAS, {"statut": "indisponible", "tentatives": 1})
        self.assertEqual((r["statut"], r["tentatives"], r.get("quota_atteint")), ("indisponible", 1, True))
        self.assertTrue(ae.a_faire({"engrenages": r}, {}))

    def test_json_invalide_indisponible_puis_abandon(self):
        r = ae.generer(self.config(), Faux(["x", "x"]), donnees(), macro(), [], DEVISES, "risk_off", EXTRAS,
                       {"tentatives": 3})
        self.assertEqual(r["statut"], "abandonnee")
        self.assertFalse(ae.a_faire({"engrenages": r}, {}))


class Reprise(unittest.TestCase):
    def test_completer_ne_rappelle_que_les_engrenages(self):
        cfg = copy.deepcopy(CONFIG)
        cfg["chemins"] = {**cfg["chemins"], "donnees": tempfile.mkdtemp()}
        devises = [{"devise": d, "risk_on_off": "neutre", "score_confluence": 50, "detail_score": [], "opportunites": [],
                    "menaces": [], "indicateurs_tableau": [], "carry": {},
                    "synthese_approfondie": {"statut": "ok", "tentatives": 1}} for d in cfg["devises"]]
        existant = {"devises": devises, "sources_citees": [],
                    "synthese_globale": {"etat_du_monde": {"conclusion": "x"}, "commentaire": "existant",
                                         "engrenages": {"statut": "indisponible", "tentatives": 1}}}
        llm = Faux([json.dumps(brut())])
        with tempfile.TemporaryDirectory() as tmp:
            r = st.analyser(cfg, llm, {"devises": {}}, {"series": {}}, {"articles": []},
                            {"evenements": [], "sites": {}, "non_rafraichies": []}, tmp, "quotidien", None, existant,
                            extras_synthese={"registre": {"cases": {}}, "indice_surprise": {}})
        self.assertEqual(len(llm.prompts), 1)
        self.assertIn("8 engrenages", llm.prompts[0])
        self.assertEqual(r["synthese_globale"]["engrenages"]["statut"], "ok")
        self.assertEqual(r["synthese_globale"]["engrenages"]["tentatives"], 2)


class RenduNotion(unittest.TestCase):
    def test_tableau_toggles_et_callouts_colores(self):
        n = ae.normaliser(brut(), sig(), [{"engrenages": [3, 5], "texte": "c"}],
                          {"id": "carry_trade", "titre": "Carry trade", "definition": "d"}, CONFIG)
        n.update({"statut": "ok", "redige_par": {"libelle": "Flash-Lite 3.5"}})
        blocs = ar._blocs_engrenages({"synthese_globale": {"engrenages": n}, "sources_citees": []})
        types = [b["type"] for b in blocs]
        self.assertEqual(types.count("toggle"), 8)
        self.assertIn("table", types)
        couleurs = [b["callout"]["color"] for b in blocs if b["type"] == "callout"]
        self.assertEqual(couleurs, ["blue_background", "orange_background", "purple_background"])
        self.assertEqual(len(blocs[1]["table"]["children"]), 9)                  # en-tête + 8 engrenages

    def test_indisponible_affiche_la_raison(self):
        blocs = ar._blocs_engrenages({"synthese_globale": {"engrenages": {"statut": "indisponible", "raison": "quota"}}})
        self.assertEqual(blocs[1]["type"], "callout")


if __name__ == "__main__":
    unittest.main()
