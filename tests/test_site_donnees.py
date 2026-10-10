"""JSON dérivé du site (docs/data/site.json) : régime, indicateurs clés, heatmap. Sans réseau."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from core import site_donnees as sd  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def cel(valeur, date="2026-10-02", consensus=None, precedent=None, etat="valeur", texte=None):
    actuel = {"texte": texte or valeur, "valeur": valeur, "etat": etat, "date": date, "source": "ForexFactory",
              "consensus": consensus, "manuel": False}
    return {"Actuel": actuel, "Précédent": {"valeur": precedent, "etat": "valeur" if precedent else "explique"}}


def projet(rapport=True, tableau=True):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "docs" / "data").mkdir(parents=True)
    (tmp / "data").mkdir()
    devises = ["USD", "EUR", "JPY", "AUD"]
    if rapport:
        (tmp / "docs" / "data" / "latest.json").write_text(json.dumps({
            "meta": {"date_rapport": "2026-10-10", "genere_le": "2026-10-10T05:30:00+00:00"},
            "synthese_globale": {"biais_macro_global": "risk_off", "commentaire": "USD en tête."},
            "critique": {"validation": "ok"},
            "devises": [{"devise": "USD", "score_confluence": 80, "risk_on_off": "off"},
                        {"devise": "EUR", "score_confluence": 26, "risk_on_off": "neutre"},
                        {"devise": "JPY", "score_confluence": None, "raison_indisponibilite": "quota atteint"},
                        {"devise": "AUD", "score_confluence": 50, "risk_on_off": "on"}]}), encoding="utf-8")
    if tableau:
        cellules = {"taux_directeur": {d: cel("4,00 %", consensus="4.00%", precedent="3,75 %") for d in devises},
                    "cpi": {d: cel("3,8 %", consensus="3.7%") for d in devises},
                    "chomage": {d: cel("4,4 %", consensus="4.2%") for d in devises},
                    "pmi_manufacturier": {d: cel("non publié dans ce pays", etat="explique", date=None) for d in devises},
                    "rendement_2a": {d: cel("3,08 %") for d in devises}}
        (tmp / "docs" / "data" / "tableau_macro.json").write_text(json.dumps({
            "maj": "2026-10-10T05:00:00+00:00", "devises": devises,
            "indicateurs": [{"id": i, "libelle": i, "sens": "inverse" if i == "chomage" else "normal",
                             "marche": i == "rendement_2a"} for i in cellules],
            "cellules": cellules, "indice_surprise": {"USD": {"indice": -0.03, "tendance": "baisse", "n": 4}}}),
            encoding="utf-8")
        (tmp / "data" / "registre_macro.json").write_text(json.dumps({"cases": {
            "EUR|chomage": {"actuel": {"valeur": "4.4%", "consensus": "4.2%", "date_pub": "2026-10-02"}},
            "EUR|cpi": {"actuel": {"valeur": "3.8%", "consensus": "3.7%", "date_pub": "2026-10-02"}}}}), encoding="utf-8")
    return tmp


class SiteDonnees(unittest.TestCase):
    def setUp(self):
        self.d = sd.construire(projet(), CONFIG)
        self.lignes = {l["devise"]: l["cellules"] for l in self.d["indicateurs_cles"]}

    def test_regime_ecart_risque_moins_refuge_et_driver(self):
        r = self.d["regime"]
        self.assertEqual((r["biais"], r["libelle"], r["driver"], r["relecture"]), ("risk_off", "Risk Off", "USD en tête.", "ok"))
        # risque disponible : AUD 50 ; refuge disponibles : USD 80 (JPY sans score) -> -30
        self.assertEqual(r["ecart_points"], -30.0)
        self.assertEqual((r["nb_devises"], r["nb_devises_disponibles"]), (4, 3))

    def test_valeur_absente_nd_avec_raison_jamais_vide(self):
        pmi = self.lignes["EUR"]["pmi_manufacturier"]
        self.assertEqual((pmi["texte"], pmi["raison"]), ("n/d", "non publié dans ce pays"))
        self.assertEqual(self.lignes["JPY"]["score"]["raison"], "quota atteint")
        self.assertEqual(self.lignes["EUR"]["indice_surprise"]["texte"], "n/d")
        self.assertEqual(self.lignes["USD"]["indice_surprise"]["texte"], "0,0")       # jamais « -0,0 »

    def test_indicateur_avec_details_et_consensus_au_format_francais(self):
        t = self.lignes["USD"]["taux_directeur"]
        self.assertEqual((t["texte"], t["valeur_num"], t["consensus"], t["precedent"]), ("4,00 %", 4.0, "4,00 %", "3,75 %"))

    def test_biais_du_jour_derive_du_score(self):
        self.assertEqual([self.lignes[d]["biais"].get("code") for d in ("USD", "EUR", "AUD")],
                         ["haussier", "baissier", "neutre"])

    def test_heatmap_chomage_inverse_et_marche_exclu(self):
        h = self.d["heatmap"]
        self.assertNotIn("rendement_2a", [i["id"] for i in h["indicateurs"]])
        eur = next(l for l in h["lignes"] if l["devise"] == "EUR")["cellules"]
        self.assertGreater(eur["cpi"]["z"], 0)          # inflation au-dessus du consensus : positif
        self.assertLess(eur["chomage"]["z"], 0)         # chômage au-dessus du consensus : négatif (inversé)
        usd = next(l for l in h["lignes"] if l["devise"] == "USD")["cellules"]
        self.assertIsNone(usd["cpi"]["z"])              # pas dans le registre : pas de couleur inventée

    def test_donnees_absentes_ne_plantent_pas(self):
        vide = sd.construire(projet(rapport=False, tableau=False), CONFIG)
        self.assertEqual(vide["regime"]["libelle"], "Indisponible")
        self.assertIsNone(vide["heatmap"])
        self.assertEqual(len(vide["indicateurs_cles"]), 9)        # les 9 devises de la config, en n/d
        self.assertTrue(all(c["texte"] == "n/d" for l in vide["indicateurs_cles"] for c in l["cellules"].values()))


if __name__ == "__main__":
    unittest.main()
