"""Lot V6.1 : erreurs transitoires et rattrapage (rejeu du 04/11, 16 × 503), copie Notion (lots de 100 blocs, 2000
caractères coupés sur une fin de phrase, erreur exacte), profil des devises (sans indice dollar large, Twelve Data
jusqu'à la veille), fraîcheur de la prime de terme, décimales françaises, version du site. Sans réseau, sans modèle."""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pytest
import yaml

from agents import agent_engrenages as ae, agent_rapport as ar, agent_redacteur as red, agent_strategiste as st
from core import historique_5ans as h5m, llm as L, notion_blocks as nb, profil_devises as pd, rapport_jour as rj, sources, \
    tableau_macro, version_site
from tests.test_budget_quota import CONFIG, EXTRAS_MATRICE, Simulateur, chaine_reelle, config_analyse
import orchestrateur

RACINE = Path(__file__).resolve().parents[1]


def analyser(llm, cfg, existant=None):
    with tempfile.TemporaryDirectory() as tmp:
        return st.analyser(config_analyse(cfg), llm, {"devises": {}}, {"series": {}}, {"articles": []},
                           {"evenements": [], "sites": {}, "non_rafraichies": []}, tmp, rapport_existant=existant,
                           extras_synthese=EXTRAS_MATRICE)


class Rejeu0411(unittest.TestCase):
    """04/11 08:15 : 16 erreurs 503, engrenages, devises et rapport du jour vides. Le complément suivant rattrape."""

    def setUp(self):
        L.reinitialiser_journal()
        self.tmp = tempfile.mkdtemp()

    def test_503_transitoires_puis_rattrapage_au_complement(self):
        llm, cfg = chaine_reelle(self.tmp, complet=True, lundi=False)
        with mock.patch.object(L.requests, "post", Simulateur(lambda n: True)), mock.patch("time.sleep"):
            matin = analyser(llm, cfg)
            r = rj.calculer(RACINE, CONFIG)
            with mock.patch.object(ar, "attribution_modele", return_value={"libelle": "faux"}):
                textes = ar.rediger(r, llm)
        reg = llm.registre
        statuts = reg.statut_analyses()
        self.assertEqual(matin["synthese_globale"]["engrenages"]["statut"], "indisponible")
        self.assertEqual(matin["synthese_globale"]["engrenages"]["tentatives"], 0)          # 503 : pas une tentative
        self.assertEqual(len(matin["synthese_globale"]["devises_indisponibles"]), 9)
        self.assertNotEqual(textes["statut"], "ok")
        self.assertTrue(all(v["statut"] == "à rejouer" and v["echec"] in ("503", "budget") for v in statuts.values()), statuts)
        self.assertEqual(reg.resume_budget()["abandonnees"], [])
        ligne = orchestrateur.ligne_budget(reg.resume_budget())
        self.assertIn("engrenages à rejouer (503)", ligne)

        # Complément horaire suivant (même fichier de quota, nouveau run) : Google répond de nouveau
        L.reinitialiser_journal()
        llm2, cfg2 = chaine_reelle(self.tmp, complet=False, lundi=False)
        with mock.patch.object(L.requests, "post", Simulateur(lambda n: False)), mock.patch("time.sleep"):
            apres = analyser(llm2, cfg2, existant=matin)
            with mock.patch.object(ar, "attribution_modele", return_value={"libelle": "faux"}):
                textes2 = ar.rediger(rj.calculer(RACINE, CONFIG), llm2)
        self.assertEqual(apres["synthese_globale"]["engrenages"]["statut"], "ok")
        self.assertEqual(apres["synthese_globale"]["devises_indisponibles"], [])
        # V6.1-bis : complément en MODE PANNE (run précédent 100 % en 503) : priorités seulement, rapport:analyse attendra
        self.assertTrue(llm2.registre.mode_panne)
        self.assertIn(textes2["statut"], ("ok", "partiel"))
        self.assertIn("1", textes2["parties_faites"])
        s2 = llm2.registre.statut_analyses()
        for cle in ("engrenages", "analyses:USD-EUR-GBP", "analyses:JPY-CHF-CAD", "analyses:AUD-NZD-CNY", "rapport:redaction"):
            self.assertEqual(s2[cle]["statut"], "faite", cle)

    def test_echec_de_format_bloque_la_journee(self):
        llm, _ = chaine_reelle(self.tmp, complet=True)
        reg = llm.registre
        L.definir_etiquette("critique")
        for run in range(2):   # deux runs avec une réponse rejetée par les contrôles
            reg.run_id = f"run{run}"
            reg.noter_echec("critique", "json_invalide")
        self.assertEqual(reg.statut_analyses()["critique"]["statut"], "bloquée")
        reg.noter_echec("synthese:EUR", "503")
        reg.run_id = "run9"
        reg.noter_echec("synthese:EUR", "503")
        self.assertEqual(reg.statut_analyses()["synthese:EUR"]["statut"], "à rejouer")
        self.assertTrue(L.echec_transitoire(llm, "synthese:EUR"))
        self.assertFalse(L.echec_transitoire(llm, "critique"))


class CopieNotion(unittest.TestCase):
    def test_decoupe_sur_fin_de_phrase_sans_perte(self):
        texte = " ".join(f"Phrase numéro {i} sur le marché des changes." for i in range(120))
        morceaux = nb.decouper(texte)
        self.assertTrue(all(len(m) <= 2000 for m in morceaux) and len(morceaux) >= 3)
        self.assertTrue(all(m.endswith(".") for m in morceaux))
        self.assertEqual(" ".join(morceaux), texte)
        bloc = nb.paragraphe([nb.rt(texte, gras=True)])
        frag = bloc["paragraph"]["rich_text"]
        self.assertEqual(len(frag), len(morceaux))
        self.assertTrue(all(f["annotations"]["bold"] for f in frag))

    def test_lots_de_100_blocs_et_erreur_exacte(self):
        r = json.loads((RACINE / "docs/data/rapport_jour.json").read_text(encoding="utf-8"))   # rapport du 04/11
        client = mock.MagicMock()
        client.pages.create.return_value = {"id": "p", "url": "u"}
        client.data_sources.query.return_value = {"results": []}
        blocs = [nb.paragraphe([nb.rt(f"bloc {i}")]) for i in range(230)]
        with mock.patch.object(red, "_obtenir_database", return_value="db"), mock.patch.object(red, "_obtenir_data_source", return_value="ds"), \
                mock.patch.object(red, "blocs_rapport_jour", return_value=blocs),                 mock.patch.object(red, "blocs_synthese_v9_du_jour", return_value=[]):   # lot V9 : testé à part
            self.assertEqual(red.publier_rapport_jour(CONFIG, r, client=client), "u")
        tailles = [len(c.kwargs["children"]) for c in client.blocks.children.append.call_args_list]
        self.assertEqual(tailles, [100, 100, 30])
        props = client.pages.create.call_args.kwargs["properties"]
        self.assertEqual(props["Type"]["select"]["name"], "quotidien")            # option existante de la base
        self.assertTrue(props["Nom"]["title"][0]["text"]["content"].startswith("Rapport du jour — "))

        class ErreurApi(Exception):
            status, code = 400, "validation_error"
        client.blocks.children.append.side_effect = ErreurApi("body.children[3].paragraph.rich_text[0].text.content.length should be ≤ 2000")
        with mock.patch.object(red, "_obtenir_database", return_value="db"), mock.patch.object(red, "_obtenir_data_source", return_value="ds"), \
                mock.patch.object(red, "blocs_rapport_jour", return_value=blocs),                 mock.patch.object(red, "blocs_synthese_v9_du_jour", return_value=[]), self.assertRaises(RuntimeError) as ctx:
            red.publier_rapport_jour(CONFIG, r, client=client)
        self.assertIn("lot 1/3 (100 blocs, premier : paragraph) : 400 · validation_error : body.children[3]", str(ctx.exception))

    def test_option_select_sans_virgule(self):
        self.assertNotIn(",", tableau_macro.option_select("inchangé le 30/10 · au plus 1,25 %"))


class Profil(unittest.TestCase):
    def test_indice_dollar_large_n_est_plus_candidat(self):
        for d, v in CONFIG["profil_devises"]["devises"].items():
            self.assertNotIn("dollar_large", v["candidats"], d)
            self.assertTrue(all(a.get("moteur") != "dollar_large" for a in v["ancrages"]), d)

    def test_twelve_data_jusqu_a_la_veille(self):
        jours = [d for d in (date(2026, 7, 1).fromordinal(date(2026, 7, 1).toordinal() + k) for k in range(130)) if d.weekday() < 5]
        import math
        fx = [(d.isoformat(), 1.1 * math.exp(0.002 * math.sin(i))) for i, d in enumerate(jours)]
        h5 = h5m.Historique.depuis_points({"FX_EUR": fx, "indice_or": [(d, 1.0 + i * 0.001) for i, (d, _) in enumerate(fx[:-10])]})
        historiques = {"series": {"or_xau": {"source": "Twelve Data (XAU/USD, or au comptant)",
                                             "points": [[d, 3000 * (v / 1.1) ** 3] for d, v in fx]}}}
        auj = jours[-1]
        m = pd.moteurs_du_moment(h5, None, "EUR", CONFIG["profil_devises"], historiques, auj)
        orr = next(x for x in m["mesures"] if x["moteur"] == "or")
        self.assertEqual(orr["source"], "Twelve Data (XAU/USD, or au comptant)")
        self.assertLess(orr["au"], auj.isoformat())                               # jusqu'à la veille
        self.assertEqual(orr["derniere_observation"], jours[-2].isoformat())
        self.assertIn("dernière observation commune", m["texte"])


def test_prime_de_terme_hebdomadaire_sans_fausse_alerte():
    hist = {"series": {"USD_prime_terme": {"source": "FRED (THREEFYTP10, prime de terme 10 ans, Kim-Wright)",
                                           "points": [["2026-10-28", 0.9]]}}}
    c = sources.certificats(hist, [], CONFIG, None, date(2026, 11, 4))["USD_prime_terme"]
    assert c["fraicheur"]["normal_jours"] == 7 and c["fraicheur"]["etat"] == "vert"


def test_decimales_francaises_dans_les_textes_du_modele():
    brut = L.extraire_json('{"synthese": "Le pétrole progresse de 6.84 % ; le dollar −0.5 %.", "plan": ["Seuil 1.1250."], '
                           '"source_id": "src_001", "citations": ["at 4.5 percent"]}')
    assert brut["synthese"] == "Le pétrole progresse de 6,84 % ; le dollar −0,5 %."
    assert brut["plan"] == ["Seuil 1,1250."] and brut["citations"] == ["at 4.5 percent"] and brut["source_id"] == "src_001"
    assert L.chiffres_fr("le 2026-11-04 à 08:30, gemini-3.5") == "le 2026-11-04 à 08:30, gemini-3.5"


def test_version_du_site_dans_index_et_stable(tmp_path):
    racine = tmp_path
    (racine / "docs" / "site").mkdir(parents=True)
    shutil.copy(RACINE / "docs" / "index.html", racine / "docs" / "index.html")
    for f in ("app.js", "commun.js", "cabinet.css"):
        shutil.copy(RACINE / "docs" / "site" / f, racine / "docs" / "site" / f)
    v1 = version_site.appliquer(racine)
    assert version_site.appliquer(racine) == {"version": v1["version"], "modifie": False}        # stable
    html = (racine / "docs" / "index.html").read_text(encoding="utf-8")
    assert f'site/cabinet.css?v={v1["version"]}' in html and f'site/app.js?v={v1["version"]}' in html
    assert f'"./site/commun.js": "./site/commun.js?v={v1["version"]}"' in html and 'name="fxdesk-version"' in html
    (racine / "docs" / "site" / "app.js").write_text("// changement", encoding="utf-8")
    assert version_site.appliquer(racine)["version"] != v1["version"]
    publie = (RACINE / "docs" / "index.html").read_text(encoding="utf-8")
    assert f'?v={version_site.empreinte(RACINE / "docs" / "site")}' in publie                   # index du dépôt à jour


def test_json_publies_valides():
    for f in (RACINE / "docs" / "data").glob("*.json"):
        json.loads(f.read_text(encoding="utf-8"))


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
def test_formats_et_vue_dans_le_navigateur():
    r = subprocess.run(["node", str(RACINE / "tests" / "v61.test.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=50)
    assert r.returncode == 0, r.stderr or r.stdout
