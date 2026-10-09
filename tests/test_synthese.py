"""Synthèse approfondie par devise : normalisation, garde-fous Python, isolation des échecs,
reprise --completer (synthèse seule), rendu Notion. Sans réseau."""
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

from agents import agent_redacteur as ar, agent_strategiste as st, agent_synthese as sy  # noqa: E402
from core import llm as L  # noqa: E402
from core.tracabilite import valider_rapport  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
CFG = CONFIG["synthese_approfondie"]
AUJ = date.today().isoformat()


def registre():
    return {"cases": {
        "EUR|taux_directeur": {"actuel": {"valeur": "2.65%", "date_pub": "2026-09-10", "source": "ForexFactory"},
                               "prevision": {"date_pub": AUJ, "dateline": 1793279700, "impact": "high",
                                             "nom_ff": "Main Refinancing Rate", "valeur": None}},
        "EUR|cpi": {"actuel": {"valeur": "3.8%", "date_pub": "2026-10-02", "consensus": "3.7%", "surprise": "▲"},
                    "precedent": {"valeur": "3.2%"},
                    "prevision": {"date_pub": AUJ, "dateline": 1792141200, "impact": "low", "nom_ff": "Final CPI y/y"}},
        "GBP|cpi": {"prevision": {"date_pub": AUJ, "dateline": 1792141200, "impact": "high", "nom_ff": "CPI y/y"}},
    }}


def brut_valide(**surcharges):
    brut = {
        "orientation": "baissier",
        "these_centrale": {"texte": "L'euro est sous pression.", "source_ids": ["src_001"]},
        "moteurs": [{"moteur": m, "donnee": "d", "trajectoire": "t", "implication": "i", "source_id": "src_001"}
                    for m in sy.MOTEURS],
        "taux_et_flux": {"texte": "Spread -169 pb.", "source_ids": ["src_001"]},
        "geopolitique": {"texte": "", "source_ids": []},
        "lecture_technique": {"texte": "Sous les MM.", "coherence": "mixte", "source_ids": ["src_001"]},
        "scenarios": [
            {"type": "haussier", "declencheur": "x", "probabilite": "faible", "justification": "j", "source_ids": ["src_001"]},
            {"type": "central", "declencheur": "x", "probabilite": "élevée", "justification": "j", "source_ids": []},
            {"type": "baissier", "declencheur": "x", "probabilite": "moyenne", "justification": "j", "source_ids": []}],
        "catalyseurs": [{"ref": "C1", "pourquoi": "p"}],
        "invalidation": [{"signal": "Cassure de 1.13", "source_id": "src_001"}],
        "opportunites": [{"texte": f"o{i}", "mecanisme": "m", "source_id": "src_001"} for i in range(3)],
        "menaces": [{"texte": f"m{i}", "mecanisme": "m", "source_id": "src_001"} for i in range(3)],
    }
    brut.update(surcharges)
    return brut


CANDIDATS = [{"ref": "C1", "date": "2026-10-29", "heure_utc": "13:15", "evenement": "Main Refinancing Rate",
              "impact": "high", "consensus": None, "source_id": "src_009", "devise": "EUR", "indicateur": "taux_directeur"}]
ENTREE = {"devise": "EUR", "score_confluence": 16}


class Normalisation(unittest.TestCase):
    def test_synthese_complete_sans_controle(self):
        s = sy.normaliser(brut_valide(), CANDIDATS, ENTREE, CFG)
        self.assertEqual(s["controles"], [])
        self.assertEqual([x["type"] for x in s["scenarios"]], ["haussier", "central", "baissier"])
        self.assertEqual(s["scenarios"][1]["probabilite"], "elevee")        # « élevée » normalisée
        self.assertEqual([m["moteur"] for m in s["moteurs"]], list(sy.MOTEURS))

    def test_date_et_heure_des_catalyseurs_viennent_du_registre_pas_du_modele(self):
        brut = brut_valide(catalyseurs=[{"ref": "C1", "pourquoi": "p", "date": "2099-01-01", "heure": "03:00"},
                                        {"ref": "C7", "pourquoi": "événement inventé"}])
        s = sy.normaliser(brut, CANDIDATS, ENTREE, CFG)
        self.assertEqual([(c["date"], c["heure_utc"], c["source_id"]) for c in s["catalyseurs"]],
                         [("2026-10-29", "13:15", "src_009")])
        self.assertTrue(any("ignoré" in c for c in s["controles"]))

    def test_scenario_manquant_ou_these_absente_levent_une_erreur(self):
        with self.assertRaises(ValueError):
            sy.normaliser(brut_valide(scenarios=brut_valide()["scenarios"][:2]), CANDIDATS, ENTREE, CFG)
        with self.assertRaises(ValueError):
            sy.normaliser(brut_valide(these_centrale={"texte": "  "}), CANDIDATS, ENTREE, CFG)

    def test_phrases_d_ordre_achat_vente_retirees_et_signalees(self):
        brut = brut_valide(these_centrale={"texte": "L'euro baisse. Achetez l'EUR/USD sous 1.12. Le spread pèse.",
                                           "source_ids": []})
        s = sy.normaliser(brut, CANDIDATS, ENTREE, CFG)
        self.assertNotIn("Achetez", s["these_centrale"]["texte"])
        self.assertIn("L'euro baisse.", s["these_centrale"]["texte"])
        self.assertTrue(any("ordre" in c for c in s["controles"]))
        self.assertEqual(sy._retirer_ordres("Placez un stop-loss à 1.10.")[1], 1)
        self.assertEqual(sy._retirer_ordres("Les positions longues ont été réduites.")[1], 0)   # pas un ordre

    def test_orientation_contraire_au_score_signalee_sans_correction(self):
        s = sy.normaliser(brut_valide(orientation="haussier"), CANDIDATS, ENTREE, CFG)    # score 16
        self.assertEqual(s["orientation"], "haussier")                                    # jamais corrigée
        self.assertTrue(any("tension avec le score" in c for c in s["controles"]))
        ok = sy.normaliser(brut_valide(orientation="baissier"), CANDIDATS, ENTREE, CFG)
        self.assertFalse(any("tension" in c for c in ok["controles"]))

    def test_plusieurs_probabilites_elevees_moteur_absent_et_listes_courtes_signales(self):
        sc = brut_valide()["scenarios"]
        sc[0]["probabilite"] = "elevee"
        brut = brut_valide(scenarios=sc, moteurs=brut_valide()["moteurs"][:3], opportunites=[])
        c = " | ".join(sy.normaliser(brut, CANDIDATS, ENTREE, CFG)["controles"])
        self.assertIn("plusieurs scénarios", c)
        self.assertIn("Banque centrale", c)
        self.assertIn("moins de 3 opportunités", c)


class Tracabilite(unittest.TestCase):
    def test_identifiants_inventes_annules_et_marques_non_sources(self):
        syn = sy.normaliser(brut_valide(
            these_centrale={"texte": "T", "source_ids": ["src_999"]},
            opportunites=[{"texte": "o", "mecanisme": "m", "source_id": "src_999"}] * 3), CANDIDATS, ENTREE, CFG)
        syn["statut"] = "ok"
        rapport = {"sources_citees": [{"id": "src_001"}, {"id": "src_009"}],
                   "devises": [{"devise": "EUR", "synthese_approfondie": syn}], "synthese_globale": {}}
        valider_rapport(rapport, "marquer")
        self.assertTrue(syn["these_centrale"]["non_source"])
        self.assertEqual(syn["these_centrale"]["source_ids"], [])
        self.assertTrue(all(o["non_sourcee"] and o["source_id"] is None for o in syn["opportunites"]))
        self.assertEqual(syn["moteurs"][0]["source_id"], "src_001")             # id valide conservé


class FauxLLM(L.FournisseurLLM):
    def __init__(self, reponses):
        self.reponses, self.prompts = list(reponses), []

    def appeler_llm(self, prompt, systeme=None):
        self.prompts.append(prompt)
        r = self.reponses.pop(0) if self.reponses else json.dumps(brut_valide())
        if isinstance(r, Exception):
            raise r
        return r


def donnees_minimales():
    return {"macro": {"series": {}}, "technique": {}, "calendrier": [], "news": [], "sites_scrapes": {}}


def devises_test(n=2):
    return [{"devise": d, "score_confluence": 40 + i, "risk_on_off": "neutre", "detail_score": [],
             "opportunites": [], "menaces": [], "indicateurs_tableau": [], "carry": {}}
            for i, d in enumerate(["EUR", "GBP", "USD"][:n])]


class Boucle(unittest.TestCase):
    def lancer(self, llm, devises, catalogue=None):
        cfg = copy.deepcopy(CONFIG)
        return sy.synthetiser(cfg, llm, devises, donnees_minimales(), catalogue if catalogue is not None else [],
                              None, registre=registre(), extras={}, pause_s=0)

    def test_succes_ajoute_la_synthese_avec_modele_et_statut(self):
        devises = devises_test(1)
        L.reinitialiser_journal()
        L._noter_appel("gemini-3.5-flash-lite", "", "x", True)
        self.lancer(FauxLLM([]), devises)
        s = devises[0]["synthese_approfondie"]
        self.assertEqual((s["statut"], s["tentatives"]), ("ok", 1))
        self.assertEqual(s["redige_par"]["libelle"], "Flash-Lite 3.5")

    def test_echec_isole_une_devise_les_autres_continuent(self):
        devises = devises_test(2)
        # EUR : 2 essais JSON invalides (max_tentatives_json = 2) ; GBP : réponse valide
        self.lancer(FauxLLM(["pas du json", "pas du json"]), devises)
        self.assertEqual(devises[0]["synthese_approfondie"]["statut"], "indisponible")
        self.assertEqual(devises[1]["synthese_approfondie"]["statut"], "ok")

    def test_abandon_apres_tentatives_max_et_plus_de_nouvel_appel(self):
        devises = devises_test(1)
        devises[0]["synthese_approfondie"] = {"statut": "indisponible", "tentatives": CFG["tentatives_max"] - 1}
        self.lancer(FauxLLM(["x", "x"]), devises)
        self.assertEqual(devises[0]["synthese_approfondie"]["statut"], "abandonnee")
        self.assertFalse(sy.synthese_a_faire(devises[0], CFG))
        llm = FauxLLM([])
        self.assertEqual(self.lancer(llm, devises), 0)
        self.assertEqual(llm.prompts, [])

    def test_synthese_deja_ok_jamais_rappelee_et_ids_catalogue_stables(self):
        devises, catalogue = devises_test(2), []
        llm = FauxLLM([])
        self.lancer(llm, devises, catalogue)
        n_catalogue, n_appels = len(catalogue), len(llm.prompts)
        devises[1]["synthese_approfondie"] = {"statut": "indisponible", "tentatives": 1}    # une seule à refaire
        self.lancer(llm, devises, catalogue)
        self.assertEqual(len(llm.prompts), n_appels + 1)
        self.assertEqual(len(catalogue), n_catalogue)                  # sources dédoublonnées, pas de doublons

    def test_prompt_ne_contient_que_le_necessaire(self):
        devises, llm = devises_test(1), FauxLLM([])
        self.lancer(llm, devises)
        prompt = llm.prompts[0]
        self.assertIn("catalyseurs_a_venir", prompt)
        self.assertIn('"ref": "C1"', prompt)
        self.assertNotIn("sites_scrapes", prompt)
        self.assertNotIn("memoire_rapports_precedents", prompt)

    def test_systeme_dedie_et_chargeur_racine_inchange(self):
        systeme = sy.charger_systeme(CFG)
        self.assertIn("Thèse centrale", systeme)
        racine = st.charger_connaissances()
        self.assertNotIn("Synthèse approfondie par devise — plan imposé", racine)
        self.assertNotIn("plan_synthese.md", racine)


class ReprisePartielle(unittest.TestCase):
    """--completer : l'analyse de base réussie n'est JAMAIS rappelée, seule la synthèse l'est."""

    def test_analyser_ne_rappelle_que_la_synthese_manquante(self):
        existant_devises = []
        for d in CONFIG["devises"]:
            e = {"devise": d, "risk_on_off": "neutre", "score_confluence": 50, "detail_score": [],
                 "opportunites": [], "menaces": [], "indicateurs_tableau": [], "carry": {},
                 "synthese_approfondie": {"statut": "ok", "tentatives": 1}}
            existant_devises.append(e)
        next(d for d in existant_devises if d["devise"] == "GBP")["synthese_approfondie"] = {
            "statut": "indisponible", "tentatives": 1}
        existant = {"devises": existant_devises, "sources_citees": [],
                    "synthese_globale": {"etat_du_monde": {"conclusion": "déjà là"},
                                         "commentaire": "commentaire existant"}}
        llm = FauxLLM([])
        cfg = copy.deepcopy(CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            rapport = st.analyser(cfg, llm, {"devises": {}}, {"series": {}}, {"articles": []},
                                  {"evenements": [], "sites": {}, "non_rafraichies": []}, tmp,
                                  "quotidien", None, existant,
                                  extras_synthese={"registre": registre(), "indice_surprise": {}})
        self.assertEqual(len(llm.prompts), 1)                                   # UN seul appel : la synthèse GBP
        self.assertIn("devise GBP", llm.prompts[0])
        self.assertEqual(rapport["synthese_globale"]["commentaire"], "commentaire existant")   # pas rappelé
        gbp = next(d for d in rapport["devises"] if d["devise"] == "GBP")
        self.assertEqual(gbp["synthese_approfondie"]["statut"], "ok")
        self.assertEqual(gbp["synthese_approfondie"]["tentatives"], 2)


class RenduNotion(unittest.TestCase):
    def test_blocs_structure_et_profondeur(self):
        syn = sy.normaliser(brut_valide(), CANDIDATS, ENTREE, CFG)
        syn.update({"statut": "ok", "genere_le": "2026-10-09T05:30:00+00:00",
                    "redige_par": {"modele": "gemini-3.5-flash-lite", "libelle": "Flash-Lite 3.5"}})
        devise = {"devise": "EUR", "synthese_approfondie": syn}
        catalogue = {"src_001": {"id": "src_001", "source": "FRED", "detail": "x", "date": "2026-10-09"}}
        blocs = ar._blocs_synthese_approfondie(devise, catalogue)
        couleurs = [b["callout"]["color"] for b in blocs if b["type"] == "callout"]
        self.assertEqual(couleurs, ["blue_background", "green_background", "yellow_background", "red_background"])
        self.assertTrue(any(b["type"] == "table" for b in blocs))
        # aucun callout/puce ne porte d'enfants (limite d'imbrication de l'API en un appel)
        for b in blocs:
            if b["type"] in ("callout", "bulleted_list_item"):
                self.assertNotIn("children", b[b["type"]])
        titre = ar._titre_synthese_approfondie(devise)
        self.assertIn("Flash-Lite 3.5", "".join(f["text"]["content"] for f in titre))
        pied = blocs[-1]["paragraph"]["rich_text"][0]["text"]["content"]
        self.assertIn("rédigée par Flash-Lite 3.5", pied)

    def test_synthese_indisponible_affiche_la_raison_sans_inventer(self):
        blocs = ar._blocs_synthese_approfondie(
            {"devise": "EUR", "synthese_approfondie": {"statut": "indisponible", "raison": "503"}}, {})
        self.assertEqual(len(blocs), 1)
        self.assertIn("indisponible", blocs[0]["callout"]["rich_text"][0]["text"]["content"])


if __name__ == "__main__":
    unittest.main()
