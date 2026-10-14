"""Refonte V2 des 8 engrenages, palier 1 + corrections §4 (sans réseau, sans LLM réel)."""
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from agents import agent_dossier_hebdo as ah, agent_engrenages as ae, agent_synthese as sy  # noqa: E402
from core import llm as L, marche_taux, vue_ensemble as ve  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


class Repondeur(L.FournisseurLLM):
    """Faux modèle : renvoie à tour de rôle les réponses de `reponses` (texte brut)."""

    def __init__(self, nom, reponses):
        self.nom, self.reponses, self.appels = nom, list(reponses), 0

    def appeler_llm(self, prompt, systeme=None):
        self.appels += 1
        L._noter_appel(self.nom, systeme, prompt, True)
        return self.reponses.pop(0) if self.reponses else '{"ok": true}'


class ReplisJson(unittest.TestCase):
    def setUp(self):
        L.reinitialiser_journal()

    def chaine(self, a, b):
        self.a, self.b = Repondeur("a", a), Repondeur("b", b)
        return L.FournisseurChaine([("a", self.a), ("b", self.b)], None)

    def test_json_invalide_redemande_au_modele_suivant(self):
        c = self.chaine(["pas du json du tout"], ['{"ok": 1}'])
        with self.assertRaises(ValueError):
            L.extraire_json(c.appeler_llm("x"))
        L.repli_modele_suivant(c)
        self.assertEqual(L.extraire_json(c.appeler_llm("x")), {"ok": 1})
        self.assertEqual((self.a.appels, self.b.appels), (1, 1))
        self.assertEqual(c.etat_disjoncteur()["replis_json_modele_suivant"], 1)
        c.appeler_llm("x")                                    # l'appel suivant repart du premier modèle
        self.assertEqual(self.a.appels, 2)

    def test_modele_fautif_reste_dernier_recours(self):
        c = self.chaine(["{cassé"], [])
        c.maillons[1]["ouvert"], c.maillons[1]["cause"] = True, "3 échecs consécutifs"
        c.appeler_llm("x")
        L.repli_modele_suivant(c)
        c.appeler_llm("x")                                    # b indisponible : a reprend la main
        self.assertEqual(self.a.appels, 2)

    def test_agent_reessaie_sur_le_modele_suivant(self):
        c = self.chaine(["Désolé, je ne peux pas répondre en JSON."], ['{"constat": "ok"}'])
        sortie = ah._appeler(c, "systeme", "prompt", 2, lambda brut: dict(brut))
        self.assertEqual(sortie["constat"], "ok")
        self.assertEqual((self.a.appels, self.b.appels), (1, 1))
        self.assertEqual(sortie["redige_par"]["modele"], "b")

    def test_parseur_tolerant(self):
        self.assertEqual(L.extraire_json('Voici : {"a": 1, "b": [1,2,],} merci'), {"a": 1, "b": [1, 2]})
        self.assertEqual(L.extraire_json('```json\n{constat: "x, y", n: 2}\n``` fin'), {"constat": "x, y", "n": 2})
        self.assertEqual(L.extraire_json('{“a”: “b, c”}'), {"a": "b, c"})
        with self.assertRaises(ValueError):                    # tronquée : jamais refermée en silence
            L.extraire_json('{"a": "tex\\"t", "b": [1, {"c": "coup')
        self.assertEqual(L.extraire_json('Texte {"a": {"b": "}"}} puis {"autre": 1}'), {"a": {"b": "}"}})
        with self.assertRaises(ValueError):
            L.extraire_json("aucun objet ici")


class QuotaHeurePacifique(unittest.TestCase):
    def test_jour_de_quota_suit_minuit_pacifique(self):
        avant_reset = datetime(2026, 10, 14, 0, 33, tzinfo=timezone.utc)      # 02:33 à Paris, 17:33 la veille en Californie
        self.assertEqual(L.jour_quota_google(avant_reset), date(2026, 10, 13))
        self.assertEqual(L.prochaine_remise_a_zero(avant_reset), datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc))
        hiver = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(L.prochaine_remise_a_zero(hiver), datetime(2026, 12, 2, 8, 0, tzinfo=timezone.utc))

    def test_compteurs_non_remis_a_zero_a_minuit_utc(self):
        chemin = Path(tempfile.mkdtemp()) / "q.json"
        chemin.write_text(json.dumps({"date": "2026-10-13", "modeles": {"flash": {"appels": 20, "epuise_jusqu_a": None}}}),
                          encoding="utf-8")
        with mock.patch.object(L.RegistreQuotas, "_maintenant",
                               staticmethod(lambda: datetime(2026, 10, 14, 0, 26, tzinfo=timezone.utc))):
            reg = L.RegistreQuotas(chemin, {"flash": 20})
            self.assertFalse(reg.autoriser("flash"))                         # encore le 13/10 chez Google
            reg.marquer_epuise("flash", None)
            self.assertEqual(reg.etat()["modeles"]["flash"]["epuise_jusqu_a"], "2026-10-14T07:00:00+00:00")
        with mock.patch.object(L.RegistreQuotas, "_maintenant",
                               staticmethod(lambda: datetime(2026, 10, 14, 7, 5, tzinfo=timezone.utc))):
            self.assertTrue(L.RegistreQuotas(chemin, {"flash": 20}).autoriser("flash"))   # remise à zéro réelle


class TauxYenBanqueDuJapon(unittest.TestCase):
    def test_borne_du_registre_remplacee_par_la_serie_boj(self):
        jour = (date.today() - timedelta(days=3)).isoformat()
        macro = {"taux_directeurs": {"JPY": {"taux": 1.0, "date": "2026-01-15", "source": "config (repli manuel)"},
                                     "EUR": {"taux": 2.4, "date": "2026-01-15", "source": "config (repli manuel)"}}}
        registre = {"cases": {"JPY|taux_directeur": {"actuel": {"valeur": "<1.25%", "valeur_num": None}}}}
        hist = {"series": {"JPY_taux_effectif": {"points": [[jour, 1.227]]}}}
        modifs = marche_taux.appliquer_registre_taux(macro, registre, {"ordre_devises": ["JPY", "EUR"]}, hist)
        jpy = macro["taux_directeurs"]["JPY"]
        self.assertEqual(jpy["taux"], 1.227)
        self.assertIn("Banque du Japon", jpy["source"])
        self.assertEqual(jpy["borne_registre"], "<1.25%")
        self.assertEqual(modifs["JPY"]["avant"], 1.0)
        self.assertEqual(macro["carry"]["differentiels"]["JPY"], round(1.227 - (1.227 + 2.4) / 2, 2))   # carry recalculé

    def test_serie_perimee_garde_le_repli(self):
        macro = {"taux_directeurs": {"JPY": {"taux": 1.0, "date": "2026-01-15", "source": "config (repli manuel)"}}}
        registre = {"cases": {"JPY|taux_directeur": {"actuel": {"valeur": "<1.25%", "valeur_num": None}}}}
        hist = {"series": {"JPY_taux_effectif": {"points": [["2020-01-01", 0.1]]}}}
        marche_taux.appliquer_registre_taux(macro, registre, {"ordre_devises": ["JPY"]}, hist)
        self.assertEqual(macro["taux_directeurs"]["JPY"]["taux"], 1.0)


DOSSIERS = {"engrenages": {
    "4": {"lignes": [{"devise": "USD", "cellules": {
        "taux_10a": {"valeur": 5.24, "var_4s": 28.0, "date": "2026-10-09", "source": "FRED (DGS10)"},
        "prime_terme": {"valeur": 1.0729}, "dette_pib": {"valeur": 122.6, "date": "2026-01"}}},
        {"devise": "CHF", "cellules": {"dette_pib": {"valeur": None, "raison": "pas de donnée"}}}]},
    "6": {"evenements": [{"titre": "Frappe sur un aéroport", "canal": "refuge", "devises": ["USD", "JPY"],
                          "source": "cnbc_world", "date": "2026-10-13", "lien": "https://exemple.org/a"}],
          "graphiques": [{"type": "barres", "barres": [{"nom": "Énergie", "valeur": 3}, {"nom": "Commerce", "valeur": 0}]}]}}}


class EngrenagesQuatreEtSix(unittest.TestCase):
    def test_donnees_python_fournies_au_modele(self):
        cat = sy._Catalogue([])
        f = ae._donnees_fiscales(DOSSIERS, cat)
        self.assertEqual(len(f), 1)
        self.assertIn("10 ans 5.24 % (+28 pb sur 4 semaines)", f[0]["texte"])
        self.assertIn("dette / PIB 122.6 %", f[0]["texte"])
        g = ae._donnees_geopolitiques(DOSSIERS, cat)
        self.assertIn("Énergie 3", g[0]["texte"])
        self.assertNotIn("Commerce", g[0]["texte"])
        self.assertIn("Frappe sur un aéroport", g[1]["texte"])
        self.assertTrue(all(x["source_id"].startswith("src_") for x in f + g))

    def test_dossier_vide_entree_vide_sans_planter(self):
        cat = sy._Catalogue([])
        self.assertEqual(ae._donnees_fiscales({}, cat), [])
        self.assertEqual(ae._donnees_geopolitiques(None, cat), [])


def serie(n, f, fin=date(2026, 10, 9)):
    return [[(fin - timedelta(days=n - i)).isoformat(), f(i)] for i in range(n + 1)]


def rapport(directions):
    eng = [{"numero": n, "diagnostic": f"Diagnostic {n}. Deuxième phrase. Troisième. Quatrième.", "donnees_insuffisantes": False,
            "direction": {"dollar": d, "risque": r, "origine": {"dollar": "calcul Python" if d else None, "risque": None}},
            "conviction": {"niveau": c}} for n, (d, r, c) in directions.items()]
    return {"meta": {"date_rapport": "2026-10-14"},
            "devises": [{"devise": "USD", "score_confluence": 84}, {"devise": "AUD", "score_confluence": 56},
                        {"devise": "CAD", "score_confluence": 16}],
            "synthese_globale": {"engrenages": {"statut": "ok", "redige_par": {"libelle": "Faux 1.0"}, "engrenages": eng,
                                                "chaines": [{"titre": "t", "maillons": [{"engrenage": 6, "texte": "a"},
                                                                                       {"engrenage": 8, "texte": "b"}]}],
                                                "conflits": [{"engrenages": [1, 5], "texte": "c"}]}}}


class VueEnsemble(unittest.TestCase):
    HIST = {"series": {"USD_2a": {"points": serie(60, lambda i: 4.5 + i / 100)}, "vix": {"points": serie(60, lambda i: 15)},
                       "USD_taux_effectif": {"points": serie(10, lambda i: 3.88)},
                       "dollar_large": {"points": serie(60, lambda i: 120 + i / 10)},
                       "eia_stocks": {"points": serie(200, lambda i: 430000 - i * 10)}}}

    def test_coherence_x_sur_7_selon_le_theme(self):
        r = rapport({1: ("haussier", "risk_off", "moyen"), 2: ("haussier", None, "faible"), 3: ("neutre", None, "faible"),
                     4: (None, "risk_off", None), 5: ("baissier", "neutre", "moyen"), 6: (None, None, None),
                     7: ("haussier", "risk_on", "moyen"), 8: (None, None, None)})
        v = ve.calculer({}, self.HIST, None, r)
        coh = v["theme"]["coherence"]
        self.assertEqual((coh["alignes"], coh["sur"]), (3, 7))                 # 2 et 7 (dollar), 4 (risque faute de dollar)
        self.assertEqual(coh["engrenages_alignes"], [2, 4, 7])
        self.assertEqual(v["theme"]["titre"], "Aversion au risque, dollar en tête")
        self.assertEqual(v["theme"]["texte"], "Diagnostic 1. Deuxième phrase. Troisième.")
        self.assertEqual(v["theme"]["direction"]["conviction"], 2)

    def test_huit_cartes_chiffres_dates_et_mini_courbes(self):
        v = ve.calculer({}, self.HIST, None, rapport({1: ("haussier", "risk_off", "faible")}))
        self.assertEqual([c["numero"] for c in v["cartes"]], list(range(1, 9)))
        c2 = v["cartes"][1]
        self.assertEqual(c2["chiffre"]["texte"], "5,10 %")
        self.assertEqual(c2["chiffre"]["date"], "2026-10-09")
        self.assertTrue(16 <= len(c2["courbe"]["points"]) <= 31)              # 30 derniers jours
        self.assertIn("+7 pb sur 7 jours", c2["ligne"])
        c8 = v["cartes"][7]
        self.assertEqual(c8["chiffre"]["texte"], "428,0 M")                    # milliers -> millions de barils
        self.assertEqual(v["cartes"][0]["direction"]["classe"], "dn")

    def test_sans_rapport_cartes_chiffrees_et_raisons(self):
        v = ve.calculer({}, self.HIST, None, None)
        self.assertIsNone(v["theme"]["titre"])
        self.assertIn("pas encore disponible", v["theme"]["raison"])
        c3 = v["cartes"][2]
        self.assertIsNone(c3["chiffre"]["valeur"])
        self.assertTrue(c3["chiffre"]["raison"])                              # n/d avec la raison, jamais inventé
        self.assertIsNotNone(v["cartes"][1]["chiffre"]["valeur"])             # les séries Python restent affichées
        self.assertEqual(v["cartes"][5]["courbe"]["points"], [])
        self.assertIn("géopolitique", v["cartes"][5]["courbe"]["raison"])

    def test_une_carte_en_echec_n_efface_pas_les_autres(self):
        with mock.patch.object(ve, "_carte_5", side_effect=ZeroDivisionError("x")):
            v = ve.calculer({}, self.HIST, None, None)
        self.assertIn("calcul en échec", v["cartes"][4]["chiffre"]["raison"])
        self.assertIsNotNone(v["cartes"][1]["chiffre"]["valeur"])


if __name__ == "__main__":
    unittest.main()
