"""Tests du Tableau macro (données factices, aucun accès réseau).
Lancer : python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from agents import collecte_forexfactory_mois as ffm  # noqa: E402
from core import registre_macro as rm  # noqa: E402
from core import saisies_manuelles as sm  # noqa: E402
from core import tableau_macro as tm  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
CFG_TM = CONFIG["tableau_macro"]
tm.PAUSE_ECRITURE_S = 0
T0 = int(datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc).timestamp())
T1 = int(datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc).timestamp())


def ev(devise, ebase_id, nom, dateline, reel=None, prevision=None, precedent=None, revision=None):
    return {"id": 1, "ebase_id": ebase_id, "devise": devise, "nom": nom, "impact": "high",
            "dateline": dateline, "reel": reel, "prevision": prevision, "precedent": precedent,
            "revision": revision, "url": None}


def page_html(evenements_ff: list[dict]) -> str:
    jours = [{"events": [{"id": 1, "ebaseId": e["ebase_id"], "currency": e["devise"], "name": e["nom"],
                          "impactName": "high", "dateline": e["dateline"], "actual": e["reel"] or "",
                          "forecast": e["prevision"] or "", "previous": e["precedent"] or "",
                          "revision": e["revision"] or "", "url": "/x"} for e in evenements_ff]}]
    return "<script>window.calendarComponentStates[1] = {\ndays: " + json.dumps(jours) + ",\n}</script>"


class Parseur(unittest.TestCase):
    def test_page_valide(self):
        e = ffm.parser_page(page_html([ev("USD", 884, "CPI y/y", T0, "3.4%", "3.3%", "3.2%")]))
        self.assertEqual((e[0]["devise"], e[0]["reel"], e[0]["prevision"]), ("USD", "3.4%", "3.3%"))

    def test_page_de_defi_cloudflare_leve_une_erreur_explicite(self):
        with self.assertRaises(ValueError):
            ffm.parser_page("<html>Just a moment...</html>")


class Nombres(unittest.TestCase):
    def test_conversions_et_surprise(self):
        self.assertEqual(rm.vers_nombre("2.4%"), 2.4)
        self.assertEqual(rm.vers_nombre("29K"), 29000)
        self.assertEqual(rm.vers_nombre("-105.6B"), -105.6e9)
        self.assertIsNone(rm.vers_nombre("<1.25%"))
        self.assertEqual(rm.symbole_surprise("3.4%", "3.3%"), "▲")
        self.assertEqual(rm.symbole_surprise("3.2%", "3.3%"), "▼")
        self.assertEqual(rm.symbole_surprise("3.3%", "3.3%"), "=")
        self.assertIsNone(rm.symbole_surprise("3.3%", None))  # jamais deviné
        self.assertIsNone(rm.symbole_surprise("<1.25%", "1.0%"))


class Registre(unittest.TestCase):
    def test_nouvelle_publication_archive_l_ancienne_et_date_le_precedent(self):
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, [ev("USD", 884, "CPI y/y", T0, "3.4%", "3.3%", "3.2%")], CFG_TM)
        c = reg["cases"]["USD|cpi"]
        self.assertEqual(c["actuel"]["valeur"], "3.4%")
        self.assertEqual(c["actuel"]["surprise"], "▲")
        rm.integrer_evenements(reg, [ev("USD", 884, "CPI y/y", T1, "3.6%", "3.5%", "3.4%")], CFG_TM)
        c = reg["cases"]["USD|cpi"]
        self.assertEqual(c["actuel"]["valeur"], "3.6%")
        self.assertEqual(c["precedent"], {"valeur": "3.4%", "date": "2026-09-11", "revise": False})
        self.assertEqual(c["historique"][-1]["valeur"], "3.4%")

    def test_une_publication_plus_ancienne_n_ecrase_pas(self):
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, [ev("USD", 884, "CPI y/y", T1, "3.6%", "3.5%", "3.4%")], CFG_TM)
        rm.integrer_evenements(reg, [ev("USD", 884, "CPI y/y", T0, "3.4%", "3.3%", "3.2%")], CFG_TM)
        self.assertEqual(reg["cases"]["USD|cpi"]["actuel"]["valeur"], "3.6%")

    def test_evenement_disparu_ne_vide_jamais_la_case(self):
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, [ev("USD", 884, "CPI y/y", T0, "3.4%", "3.3%", "3.2%")], CFG_TM)
        bilan = rm.integrer_evenements(reg, [], CFG_TM)
        self.assertEqual(reg["cases"]["USD|cpi"]["actuel"]["valeur"], "3.4%")
        self.assertNotIn("USD|cpi", bilan["introuvables"])

    def test_revision_du_precedent_est_prise_en_compte(self):
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, [ev("USD", 66, "Non-Farm Employment Change", T0, "29K", "89K",
                                        "162K", "133K")], CFG_TM)
        self.assertEqual(reg["cases"]["USD|emploi"]["precedent"]["valeur"], "133K")
        self.assertTrue(reg["cases"]["USD|emploi"]["precedent"]["revise"])

    def test_prochaine_publication_et_consensus(self):
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, [ev("USD", 884, "CPI y/y", T0, "3.4%", "3.3%", "3.2%"),
                                     ev("USD", 884, "CPI y/y", T1, None, "3.5%", "3.4%")], CFG_TM)
        self.assertEqual(reg["cases"]["USD|cpi"]["prevision"]["valeur"], "3.5%")
        self.assertEqual(reg["cases"]["USD|cpi"]["prevision"]["date_pub"], "2026-10-14")

    def test_taux_de_repli_ne_remplace_pas_une_decision_plus_recente(self):
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, [ev("USD", 1, "Federal Funds Rate", T0, "4.00%", "4.00%", "3.75%")], CFG_TM)
        rm.integrer_taux(reg, {"USD": {"taux": 3.75, "date": "2026-01-15", "source": "config"}})
        self.assertEqual(reg["cases"]["USD|taux_directeur"]["actuel"]["valeur"], "4.00%")
        rm.integrer_taux(reg, {"JPY": {"taux": 1.0, "date": "2026-01-15", "source": "config"}})
        self.assertEqual(reg["cases"]["JPY|taux_directeur"]["actuel"]["valeur"], "1.00%")

    def test_cases_sans_equivalent_sont_expliquees(self):
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, [], CFG_TM)
        txt = rm.texte_officiel(reg["cases"]["JPY|emploi"], "Actuel", "")
        self.assertEqual(txt, "non publié dans ce pays")
        self.assertTrue(rm.texte_officiel(reg["cases"]["USD|cpi"], "Actuel", "%").startswith("n/d"))


class Cellules(unittest.TestCase):
    def setUp(self):
        self.reg = rm.charger("inexistant.json")
        rm.integrer_evenements(self.reg, [ev("USD", 884, "CPI y/y", T0, "3.4%", "3.3%", "3.2%")], CFG_TM)
        self.case = self.reg["cases"]["USD|cpi"]

    def test_format_valeur_date_surprise(self):
        t = rm.texte_officiel(self.case, "Actuel", "%")
        self.assertEqual(t, "3,4 % (11/09) ▲")

    def test_priorite_fichier_manuel_sur_saisie_notion(self):
        saisies = {"saisies": {"USD|cpi|Actuel": {"texte": "9,9 %", "saisi_le": "2026-10-01"}}}
        ov = {"USD": {"cpi": {"valeur": "7.7"}}}
        c = tm.resoudre_cellule(self.case, "cpi", "USD", "Actuel", "%", saisies, ov, date(2026, 10, 2))
        self.assertEqual(c["texte"], "7,7 % ✍️")
        self.assertEqual(c["origine"], "fichier_manuel")

    def test_saisie_notion_prioritaire_tant_qu_aucune_publication_plus_recente(self):
        saisies = {"saisies": {"USD|cpi|Actuel": {"texte": "9,9 %", "saisi_le": "2026-09-20"}}}
        c = tm.resoudre_cellule(self.case, "cpi", "USD", "Actuel", "%", saisies, {}, date(2026, 9, 21))
        self.assertEqual((c["texte"], c["origine"]), ("9,9 % ✍️", "saisie_notion"))

    def test_publication_officielle_plus_recente_remplace_la_saisie(self):
        saisies = {"saisies": {"USD|cpi|Actuel": {"texte": "9,9 %", "saisi_le": "2026-09-05"}}}
        c = tm.resoudre_cellule(self.case, "cpi", "USD", "Actuel", "%", saisies, {}, date(2026, 9, 21))
        self.assertEqual(c["origine"], "officiel")
        self.assertEqual(c["a_archiver"], "USD|cpi|Actuel")

    def test_saisie_partielle_vers_overrides_reprend_la_valeur_officielle(self):
        saisies = {"saisies": {"USD|cpi|Prévision": {"texte": "3,6 %", "saisi_le": "2026-09-20"}}}
        o = sm.vers_overrides(saisies, self.reg)
        self.assertEqual(o["USD"]["cpi"]["prevision"], "3,6 %")
        self.assertEqual(o["USD"]["cpi"]["valeur"], "3.4%")

    def test_fichier_manuel_du_jour_garde_la_priorite_a_la_fusion(self):
        fus = sm.fusionner_overrides({"USD": {"cpi": {"valeur": "A"}}},
                                     {"USD": {"cpi": {"valeur": "B"}, "pib": {"valeur": "C"}}})
        self.assertEqual((fus["USD"]["cpi"]["valeur"], fus["USD"]["pib"]["valeur"]), ("A", "C"))


class Creneaux(unittest.TestCase):
    CFG = {"plafond_requetes_par_jour": 2, "creneaux_utc": ["05:15", "19:15"]}

    def t(self, h, m=0):
        return datetime(2026, 10, 6, h, m, tzinfo=timezone.utc)

    def test_avant_premier_creneau(self):
        self.assertFalse(ffm.collecte_due([], self.CFG, self.t(4, 0))[0])

    def test_matin_puis_cache_jusqu_au_soir(self):
        self.assertTrue(ffm.collecte_due([], self.CFG, self.t(5, 20))[0])
        matin = [self.t(5, 20).isoformat()]
        self.assertFalse(ffm.collecte_due(matin, self.CFG, self.t(12, 15))[0])
        self.assertTrue(ffm.collecte_due(matin, self.CFG, self.t(19, 15))[0])

    def test_cron_du_soir_manque_rattrape_au_passage_suivant(self):
        matin = [self.t(5, 20).isoformat()]
        self.assertTrue(ffm.collecte_due(matin, self.CFG, self.t(21, 15))[0])

    def test_plafond_reglable(self):
        deux = [self.t(5, 20).isoformat(), self.t(19, 20).isoformat()]
        self.assertFalse(ffm.collecte_due(deux, self.CFG, self.t(21, 15))[0])
        cfg6 = {**self.CFG, "plafond_requetes_par_jour": 6, "creneaux_utc": ["05:15", "13:15", "19:15"]}
        self.assertTrue(ffm.collecte_due(deux[:1], cfg6, self.t(13, 20))[0])


# ------------------------------------------------------------ faux Notion
class _Ns:
    pass


def _convertir(props: dict) -> dict:
    sortie = {}
    for nom, v in props.items():
        if "title" in v:
            sortie[nom] = {"title": [{"plain_text": t["text"]["content"]} for t in v["title"]]}
        elif "rich_text" in v:
            sortie[nom] = {"rich_text": [{"plain_text": t["text"]["content"]} for t in v["rich_text"]]}
        else:
            sortie[nom] = v
    return sortie


class FauxNotion:
    """Imite juste ce que le Tableau macro utilise ; les lignes sont dans self.lignes."""

    def __init__(self):
        self.lignes: dict[str, dict] = {}
        self.vues: list[str] = []
        self.bases_creees = 0
        self._n = 0
        self.blocks = _Ns(); self.blocks.children = _Ns()
        self.blocks.children.list = lambda *a, **k: {"results": [], "has_more": False}
        self.databases = _Ns()
        self.databases.create = self._creer_base
        self.databases.retrieve = lambda i: {"data_sources": [{"id": "ds1"}]}
        self.data_sources = _Ns()
        self.data_sources.retrieve = lambda i: {"properties": {
            "Indicateur": {"type": "title"}, "Type": {}, "Ordre": {}, "Source": {},
            "Dernière mise à jour": {}, **{d: {} for d in CFG_TM["ordre_devises"]}}}
        self.data_sources.update = lambda *a, **k: None
        self.data_sources.query = lambda ds, **k: {"results": list(self.lignes.values()), "has_more": False}
        self.pages = _Ns()
        self.pages.create = self._creer_ligne
        self.pages.update = self._maj_ligne
        self.views = _Ns()
        self.views.list = lambda **k: {"results": []}
        self.views.create = lambda **k: self.vues.append(k["name"])

    def _creer_base(self, **k):
        self.bases_creees += 1
        return {"id": "abcdefabcdefabcdefabcdefabcdefab"}

    def _creer_ligne(self, parent, properties, **k):
        self._n += 1
        pid = f"p{self._n}"
        self.lignes[pid] = {"id": pid, "properties": _convertir(properties)}

    def _maj_ligne(self, pid, properties):
        self.lignes[pid]["properties"].update(_convertir(properties))

    def _ligne(self, libelle, type_valeur):
        for p in self.lignes.values():
            titre = "".join(t["plain_text"] for t in p["properties"]["Indicateur"]["title"])
            if titre == libelle and p["properties"]["Type"]["select"]["name"] == type_valeur:
                return p
        raise KeyError((libelle, type_valeur))

    def editer(self, libelle, type_valeur, devise, texte):
        self._ligne(libelle, type_valeur)["properties"][devise] = {"rich_text": [{"plain_text": texte}]}

    def lire(self, libelle, type_valeur, devise):
        rt = self._ligne(libelle, type_valeur)["properties"][devise]["rich_text"]
        return "".join(t["plain_text"] for t in rt)


class FauxScraping:
    def __init__(self, html):
        self.html, self.appels = html, 0

    def requete_directe(self, site, url):
        self.appels += 1
        return {"statut": "frais", "contenu": self.html, "note": ""}


class BoutEnBout(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "data" / "cache").mkdir(parents=True)
        (self.tmp / "docs").mkdir()
        self.config = json.loads(json.dumps(CONFIG))
        self.config["tableau_macro"]["database_id"] = ""
        self.html = page_html([
            ev("USD", 884, "CPI y/y", T0, "3.4%", "3.3%", "3.2%"),
            ev("USD", 884, "CPI y/y", T1, None, "3.5%", "3.4%"),
            ev("EUR", 59, "Unemployment Rate", T0, "6.4%", "6.4%", "6.4%"),
        ])
        self.notion = FauxNotion()
        self.maintenant = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)

    def passer(self, html=None, maintenant=None, notion=None):
        return tm.mettre_a_jour(self.config, self.tmp, None,
                                client_scraping=FauxScraping(html or self.html),
                                client_notion=notion or self.notion,
                                maintenant=maintenant or self.maintenant)

    def test_creation_unique_et_aucun_doublon_de_ligne(self):
        self.passer()
        self.assertEqual(len(self.notion.lignes), 30)  # 10 indicateurs x 3 types
        self.assertEqual(self.notion.lire("CPI annuel", "Actuel", "USD"), "3,4 % (11/09) ▲")
        self.assertEqual(self.notion.lire("CPI annuel", "Prévision", "USD"), "3,5 % (14/10)")
        self.passer()
        self.assertEqual(len(self.notion.lignes), 30)

    def test_saisie_manuelle_jamais_ecrasee_puis_remplacee_par_publication_plus_recente(self):
        self.passer()
        self.notion.editer("CPI annuel", "Actuel", "USD", "9,9 %")
        r = self.passer()
        self.assertEqual(self.notion.lire("CPI annuel", "Actuel", "USD"), "9,9 % ✍️")
        self.assertEqual(r["saisies_overrides"]["USD"]["cpi"]["valeur"], "9,9 %")
        self.passer()  # passage suivant : toujours là
        self.assertEqual(self.notion.lire("CPI annuel", "Actuel", "USD"), "9,9 % ✍️")
        saisies = sm.charger(self.tmp / "data" / "overrides" / "saisies_notion.json")
        self.assertIn("USD|cpi|Actuel", saisies["saisies"])
        # nouvelle publication officielle, plus récente que la saisie : elle remplace
        nouvelle = page_html([ev("USD", 884, "CPI y/y", T1, "3.6%", "3.5%", "3.4%")])
        self.passer(html=nouvelle, maintenant=self.maintenant.replace(hour=20, day=15, month=10))
        saisies = sm.charger(self.tmp / "data" / "overrides" / "saisies_notion.json")
        self.assertNotIn("USD|cpi|Actuel", saisies["saisies"])
        self.assertEqual(saisies["historique"][-1]["texte"], "9,9 %")
        self.assertTrue(self.notion.lire("CPI annuel", "Actuel", "USD").startswith("3,6 %"))

    def test_collecte_ff_non_relancee_dans_le_meme_creneau(self):
        sc = FauxScraping(self.html)
        for heure in (10, 11):
            tm.mettre_a_jour(self.config, self.tmp, None, client_scraping=sc, client_notion=self.notion,
                             maintenant=self.maintenant.replace(hour=heure))
        self.assertEqual(sc.appels, 1)

    def test_echec_notion_ne_bloque_ni_le_registre_ni_le_web(self):
        casse = FauxNotion()
        casse.databases.retrieve = lambda i: (_ for _ in ()).throw(RuntimeError("503 apikey=SECRET"))
        r = self.passer(notion=casse)
        self.assertTrue((self.tmp / "docs" / "data" / "tableau_macro.json").exists())
        self.assertTrue((self.tmp / "data" / "registre_macro.json").exists())
        self.assertIsNone(r["notion"])

    def test_json_web_contient_la_matrice(self):
        self.passer()
        web = json.loads((self.tmp / "docs" / "data" / "tableau_macro.json").read_text(encoding="utf-8"))
        self.assertEqual(web["devises"][:4], ["USD", "EUR", "GBP", "JPY"])
        self.assertEqual(web["cellules"]["cpi"]["USD"]["Actuel"]["surprise"], "▲")
        self.assertIn("Actuel", web["remplissage"])


if __name__ == "__main__":
    unittest.main()
