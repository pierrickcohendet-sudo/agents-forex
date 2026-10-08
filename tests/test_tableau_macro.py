"""Tests du Tableau macro (données factices, aucun accès réseau).
Lancer : python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import yaml
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from agents import collecte_forexfactory_mois as ffm  # noqa: E402
from core import registre_macro as rm  # noqa: E402
from core import saisies_manuelles as sm  # noqa: E402
from core import controles_macro as cm  # noqa: E402
from core import marche_taux as mt  # noqa: E402
from core import tableau_macro as tm  # noqa: E402

CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
CFG_TM = CONFIG["tableau_macro"]
tm.PAUSE_ECRITURE_S = 0
_COLLECTE_TAUX_REELLE = mt.collecter
mt.collecter = lambda cfg, cle: {"series": {}, "erreurs": []}
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


PROPRIETES_NOUVELLES = {"Indicateur": {"type": "title"}, "Devise": {}, "Actuel": {}, "Précédent": {},
                        "Prévision": {}, "Surprise": {}, "Variation": {}, "Date de publication": {},
                        "Prochaine publication": {}, "Source": {}, "Dernière mise à jour": {}, "Ordre": {}}
PROPRIETES_ANCIENNES = {"Indicateur": {"type": "title"}, "Type": {}, "Ordre": {}, "Source": {},
                        "Dernière mise à jour": {}, **{d: {} for d in CFG_TM["ordre_devises"]}}


class FauxNotion:
    """Imite juste ce que le Tableau macro utilise. Une ou deux bases (migration)."""

    def __init__(self, ancienne_structure: bool = False):
        self.bases = {}          # database_id -> {"ds": id, "props": {...}, "titre": str}
        self.lignes = {"ds_nouvelle": {}}
        self.vues: dict[str, dict] = {"ds_nouvelle": {"v0": {"name": "Default view"}}}
        self.titres_mis_a_jour: list[tuple[str, str]] = []
        self.bases_creees = 0
        self._n = 0
        self.ancienne_id = "a" * 32
        self.nouvelle_id = "b" * 32
        if ancienne_structure:
            self.bases[self.ancienne_id] = {"ds": "ds_ancienne", "props": PROPRIETES_ANCIENNES}
            self.lignes["ds_ancienne"] = {}
        else:
            self.bases[self.nouvelle_id] = {"ds": "ds_nouvelle", "props": PROPRIETES_NOUVELLES}
        self.blocks = _Ns(); self.blocks.children = _Ns()
        self.blocks.children.list = lambda *a, **k: {"results": [], "has_more": False}
        self.databases = _Ns()
        self.databases.create = self._creer_base
        self.databases.retrieve = lambda i: {"data_sources": [{"id": self.bases[i]["ds"]}]}
        self.databases.update = lambda i, **k: self.titres_mis_a_jour.append(
            (i, k["title"][0]["text"]["content"]))
        self.data_sources = _Ns()
        self.data_sources.retrieve = lambda ds: {"properties": {
            nom: {**p, "id": f"id_{nom}"}
            for nom, p in next(b["props"] for b in self.bases.values() if b["ds"] == ds).items()}}
        self.data_sources.update = lambda *a, **k: None
        self.data_sources.query = lambda ds, **k: {"results": list(self.lignes[ds].values()),
                                                   "has_more": False}
        self.pages = _Ns()
        self.pages.create = self._creer_ligne
        self.pages.update = self._maj_ligne
        self.views = _Ns()
        self.views.list = lambda **k: {"results": [{"id": i} for i in self.vues["ds_nouvelle"]]}
        self.views.retrieve = lambda i: self.vues["ds_nouvelle"][i]
        self.views.create = self._creer_vue
        self.views.delete = lambda i: self.vues["ds_nouvelle"].pop(i)

    def _creer_base(self, **k):
        self.bases_creees += 1
        self.bases[self.nouvelle_id] = {"ds": "ds_nouvelle", "props": PROPRIETES_NOUVELLES}
        return {"id": self.nouvelle_id}

    def _creer_vue(self, **k):
        self._n += 1
        self.vues["ds_nouvelle"][f"v{self._n}"] = k

    def _creer_ligne(self, parent, properties, **k):
        self._n += 1
        pid = f"p{self._n}"
        ds = parent["data_source_id"]
        self.lignes[ds][pid] = {"id": pid, "properties": _convertir(properties)}

    def _maj_ligne(self, pid, properties):
        for lignes in self.lignes.values():
            if pid in lignes:
                lignes[pid]["properties"].update(_convertir(properties))

    # -- aides de test (base de la nouvelle structure)
    def _ligne(self, libelle, devise):
        for p in self.lignes["ds_nouvelle"].values():
            titre = "".join(t["plain_text"] for t in p["properties"]["Indicateur"]["title"])
            if titre == libelle and p["properties"]["Devise"]["select"]["name"] == devise:
                return p
        raise KeyError((libelle, devise))

    def editer(self, libelle, devise, colonne, texte):
        self._ligne(libelle, devise)["properties"][colonne] = {"rich_text": [{"plain_text": texte}]}

    def lire(self, libelle, devise, colonne):
        prop = self._ligne(libelle, devise)["properties"][colonne]
        if "rich_text" in prop:
            return "".join(t["plain_text"] for t in prop["rich_text"])
        if "select" in prop:
            return (prop["select"] or {}).get("name")
        if "date" in prop:
            return (prop["date"] or {}).get("start")
        return prop.get("number")


class FauxScraping:
    def __init__(self, html):
        self.html, self.appels, self.mois = html, 0, []

    def requete_directe(self, site, url):
        self.appels += 1
        self.mois.append(url.split("month=")[-1])
        return {"statut": "frais", "contenu": self.html, "note": ""}


class BoutEnBout(unittest.TestCase):
    NB_LIGNES = 9 * 14  # 9 devises x (13 indicateurs dont 3 de marché + indice de surprise)

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
        os.environ.pop("FRED_API_KEY", None)  # aucun accès réseau dans les tests

    def passer(self, html=None, maintenant=None, notion=None):
        return tm.mettre_a_jour(self.config, self.tmp, None,
                                client_scraping=FauxScraping(html or self.html),
                                client_notion=notion or self.notion,
                                maintenant=maintenant or self.maintenant)

    def test_une_ligne_par_indicateur_et_devise_sans_doublon(self):
        self.passer()
        self.assertEqual(len(self.notion.lignes["ds_nouvelle"]), self.NB_LIGNES)
        self.assertEqual(self.notion.lire("CPI annuel", "USD", "Actuel"), "3,4 %")
        self.assertEqual(self.notion.lire("CPI annuel", "USD", "Précédent"), "3,2 %")
        self.assertEqual(self.notion.lire("CPI annuel", "USD", "Prévision"), "3,5 %")
        self.assertEqual(self.notion.lire("CPI annuel", "USD", "Surprise"), "▲")
        self.assertEqual(self.notion.lire("CPI annuel", "USD", "Date de publication"), "2026-09-11")
        self.assertEqual(self.notion.lire("CPI annuel", "USD", "Prochaine publication"), "2026-10-14T12:30+00:00")
        self.passer()
        self.assertEqual(len(self.notion.lignes["ds_nouvelle"]), self.NB_LIGNES)

    def test_vues_par_devise_et_groupee_sans_default_view(self):
        self.passer()
        noms = sorted(v["name"] for v in self.notion.vues["ds_nouvelle"].values())
        self.assertEqual(len(noms), 10)
        self.assertIn("Toutes les devises", noms)
        self.assertNotIn("Default view", noms)
        groupee = next(v for v in self.notion.vues["ds_nouvelle"].values() if v["name"] == "Toutes les devises")
        self.assertEqual(groupee["configuration"]["group_by"]["type"], "select")
        usd = next(v for v in self.notion.vues["ds_nouvelle"].values() if v["name"].endswith("USD"))
        self.assertEqual(usd["filter"], {"property": "Devise", "select": {"equals": "USD"}})
        self.assertEqual(usd["configuration"]["properties"][0]["property_id"], "title")
        self.assertEqual(groupee["configuration"]["group_by"]["property_id"], "id_Devise")
        self.assertEqual([c["property_id"] for c in usd["configuration"]["properties"][1:5]],
                         ["id_Actuel", "id_Précédent", "id_Prévision", "id_Surprise"])

    def test_saisie_manuelle_jamais_ecrasee_puis_remplacee_par_publication_plus_recente(self):
        self.passer()
        self.notion.editer("CPI annuel", "USD", "Actuel", "9,9 %")
        r = self.passer()
        self.assertEqual(self.notion.lire("CPI annuel", "USD", "Actuel"), "9,9 % ✍️")
        self.assertEqual(r["saisies_overrides"]["USD"]["cpi"]["valeur"], "9,9 %")
        self.passer()  # passage suivant : toujours là
        self.assertEqual(self.notion.lire("CPI annuel", "USD", "Actuel"), "9,9 % ✍️")
        saisies = sm.charger(self.tmp / "data" / "overrides" / "saisies_notion.json")
        self.assertIn("USD|cpi|Actuel", saisies["saisies"])
        # les autres cellules de la ligne (Précédent, Prévision) restent mises à jour par le pipeline
        self.assertEqual(self.notion.lire("CPI annuel", "USD", "Prévision"), "3,5 %")
        # nouvelle publication officielle, plus récente que la saisie : elle remplace
        nouvelle = page_html([ev("USD", 884, "CPI y/y", T1, "3.6%", "3.5%", "3.4%")])
        self.passer(html=nouvelle, maintenant=self.maintenant.replace(hour=20, day=15, month=10))
        saisies = sm.charger(self.tmp / "data" / "overrides" / "saisies_notion.json")
        self.assertNotIn("USD|cpi|Actuel", saisies["saisies"])
        self.assertEqual(saisies["historique"][-1]["texte"], "9,9 %")
        self.assertEqual(self.notion.lire("CPI annuel", "USD", "Actuel"), "3,6 %")

    def test_saisie_sur_precedent_ou_prevision_detectee_cellule_par_cellule(self):
        self.passer()
        self.notion.editer("Taux de chômage", "EUR", "Prévision", "6,6 %")
        self.passer()
        self.assertEqual(self.notion.lire("Taux de chômage", "EUR", "Prévision"), "6,6 % ✍️")
        self.assertEqual(self.notion.lire("Taux de chômage", "EUR", "Actuel"), "6,4 %")  # pas touché
        saisies = sm.charger(self.tmp / "data" / "overrides" / "saisies_notion.json")
        self.assertEqual(list(saisies["saisies"]), ["EUR|chomage|Prévision"])

    def test_collecte_ff_non_relancee_dans_le_meme_creneau(self):
        sc = FauxScraping(self.html)
        for heure in (10, 11):
            tm.mettre_a_jour(self.config, self.tmp, None, client_scraping=sc, client_notion=self.notion,
                             maintenant=self.maintenant.replace(hour=heure))
        # 1 page « mois en cours » + mois suivants lus UNE fois (cases sans date de prochaine publication)
        self.assertEqual(sc.appels, 3)
        self.assertEqual(sc.mois, ["this", "next", "dec.2026"])

    def test_echec_notion_ne_bloque_ni_le_registre_ni_le_web(self):
        casse = FauxNotion()
        casse.databases.retrieve = lambda i: (_ for _ in ()).throw(RuntimeError("503 apikey=SECRET"))
        r = self.passer(notion=casse)
        self.assertTrue((self.tmp / "docs" / "data" / "tableau_macro.json").exists())
        self.assertTrue((self.tmp / "data" / "registre_macro.json").exists())
        self.assertIsNone(r["notion"])

    def test_json_web_matrice_et_lignes_par_devise(self):
        self.passer()
        web = json.loads((self.tmp / "docs" / "data" / "tableau_macro.json").read_text(encoding="utf-8"))
        self.assertEqual(web["devises"][:4], ["USD", "EUR", "GBP", "JPY"])
        self.assertEqual(web["cellules"]["cpi"]["USD"]["Actuel"]["surprise"], "▲")
        self.assertEqual(len(web["lignes"]), self.NB_LIGNES)
        ligne = next(r for r in web["lignes"] if r["cle"] == "USD|cpi")
        self.assertEqual((ligne["Actuel"], ligne["Précédent"], ligne["Prévision"], ligne["surprise"]),
                         ("3,4 %", "3,2 %", "3,5 %", "▲"))


class Migration(unittest.TestCase):
    """Ancienne structure (Type x devises en colonnes) -> nouvelle (une ligne par couple)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "data" / "cache").mkdir(parents=True)
        (self.tmp / "docs").mkdir()
        os.environ.pop("FRED_API_KEY", None)
        self.config = json.loads(json.dumps(CONFIG))
        self.config["tableau_macro"]["database_id"] = "a" * 32
        self.maintenant = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)
        self.html = page_html([ev("USD", 884, "CPI y/y", T0, "3.4%", "3.3%", "3.2%"),
                               ev("EUR", 59, "Unemployment Rate", T0, "6.4%", "6.4%", "6.4%")])
        # registre déjà alimenté par l'ancien pipeline, avec la mémoire de l'ancienne structure
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, ffm.parser_page(self.html), CFG_TM)
        reg["cases"]["USD|cpi"]["ecrit_notion"] = {"Actuel": "3,4 % (11/09) ▲"}
        rm.sauver(reg, self.tmp / "data" / "registre_macro.json")
        sm.sauver({"saisies": {"EUR|chomage|Précédent": {"texte": "6,1 %", "saisi_le": "2026-10-01",
                                                          "origine": "x"}}, "historique": []},
                  self.tmp / "data" / "overrides" / "saisies_notion.json")
        self.notion = FauxNotion(ancienne_structure=True)
        # l'utilisateur a modifié une cellule de l'ancienne base juste avant la migration
        self.notion.lignes["ds_ancienne"]["x1"] = {"id": "x1", "properties": _convertir({
            "Indicateur": {"title": [{"text": {"content": "CPI annuel"}}]},
            "Type": {"select": {"name": "Actuel"}},
            "USD": {"rich_text": [{"text": {"content": "3,7 %"}}]}})}

    def test_migration_conserve_saisies_archive_l_ancienne_base_et_remplit_la_nouvelle(self):
        cfg_path = self.tmp / "config.yaml"
        cfg_path.write_text('tableau_macro:\n  actif: true\n  database_id: "' + "a" * 32 + '"\n',
                            encoding="utf-8")
        r = tm.mettre_a_jour(self.config, self.tmp, cfg_path, client_scraping=FauxScraping(self.html),
                             client_notion=self.notion, maintenant=self.maintenant)
        self.assertEqual(r["migration"]["saisies_capturees"], 1)
        # ancienne base archivée (renommée), jamais supprimée
        self.assertEqual(len(self.notion.titres_mis_a_jour), 1)
        self.assertIn("ancienne structure (archivée", self.notion.titres_mis_a_jour[0][1])
        self.assertEqual(self.notion.bases_creees, 1)
        self.assertIn("b" * 32, cfg_path.read_text(encoding="utf-8"))
        self.assertIn("ancienne_database_id", cfg_path.read_text(encoding="utf-8"))
        # les deux saisies (préexistante + celle capturée dans l'ancienne base) sont dans la nouvelle
        n = self.notion
        self.assertEqual(n.lire("Taux de chômage", "EUR", "Précédent"), "6,1 % ✍️")
        self.assertEqual(n.lire("CPI annuel", "USD", "Actuel"), "3,7 % ✍️")
        self.assertEqual(len(n.lignes["ds_nouvelle"]), 9 * 14)
        saisies = sm.charger(self.tmp / "data" / "overrides" / "saisies_notion.json")
        self.assertEqual(sorted(saisies["saisies"]), ["EUR|chomage|Précédent", "USD|cpi|Actuel"])
        # 2e passage : plus de migration, aucun doublon, saisies toujours là
        self.config["tableau_macro"]["database_id"] = "b" * 32
        r2 = tm.mettre_a_jour(self.config, self.tmp, cfg_path, client_scraping=FauxScraping(self.html),
                              client_notion=self.notion, maintenant=self.maintenant)
        self.assertNotIn("migration", r2)
        self.assertEqual(self.notion.bases_creees, 1)
        self.assertEqual(len(n.lignes["ds_nouvelle"]), 9 * 14)
        self.assertEqual(n.lire("CPI annuel", "USD", "Actuel"), "3,7 % ✍️")


class FredEtProjections(unittest.TestCase):
    def reg(self):
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, [], CFG_TM)
        return reg

    def test_fred_comble_une_case_vide_sans_ecraser_forexfactory(self):
        reg = self.reg()
        rm.integrer_evenements(reg, [ev("USD", 56, "Unemployment Rate", T0, "4.2%", "4.1%", "4.1%")], CFG_TM)
        fred = {"valeurs": {"USD|chomage": {"valeur": "9.9%", "periode": "2026-09", "precedente": "4.1%",
                                            "serie": "UNRATE", "usage": "repli_et_controle"},
                            "CHF|balance_commerciale": {"valeur": "5.4B", "periode": "2026-06",
                                                        "precedente": "6.8B", "serie": "XTEXVA01CHM667S",
                                                        "usage": "repli", "etiquette": "équiv. OCDE, USD"}}}
        self.assertEqual(rm.integrer_fred(reg, fred), 1)
        self.assertEqual(reg["cases"]["USD|chomage"]["actuel"]["valeur"], "4.2%")  # FF intact
        chf = reg["cases"]["CHF|balance_commerciale"]
        self.assertEqual(rm.texte_officiel(chf, "Actuel", ""), "5,4B [équiv. OCDE, USD] (pér. 06/26)")
        self.assertEqual(rm.valeur_cellule(chf, "Actuel", ""), "5,4B [équiv. OCDE, USD]")
        self.assertEqual(rm.source_cellule(chf), "FRED (XTEXVA01CHM667S) · pér. 06/26")
        self.assertEqual(chf["actuel"]["source"], "FRED (XTEXVA01CHM667S)")

    def test_projection_bc_etiquetee_quand_pas_de_consensus(self):
        reg = self.reg()
        rm.integrer_evenements(reg, [ev("USD", 56, "Unemployment Rate", T0, "4.2%", "4.1%", "4.1%"),
                                     ev("USD", 56, "Unemployment Rate", T1, None, None, "4.2%")], CFG_TM)
        rm.integrer_projections(reg, {"projections": {"USD|chomage": {
            "valeur": "4.1%", "horizon": "T4 2026", "date_pub": "2026-09-16", "serie": "UNRATEMD"}}})
        self.assertEqual(rm.texte_officiel(reg["cases"]["USD|chomage"], "Prévision", "%"),
                         "proj. BC 4,1 % (T4 2026) · pub. 14/10")
        # un consensus réel prend toujours le pas sur la projection
        rm.integrer_evenements(reg, [ev("USD", 56, "Unemployment Rate", T1, None, "4.3%", "4.2%")], CFG_TM)
        self.assertEqual(rm.texte_officiel(reg["cases"]["USD|chomage"], "Prévision", "%"), "4,3 % (14/10)")


class Controles(unittest.TestCase):
    NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    def reg(self, evenements):
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, evenements, CFG_TM)
        return reg

    def test_valeur_hors_plage(self):
        reg = self.reg([ev("USD", 56, "Unemployment Rate", T0, "74.0%", "4.1%", "4.1%")])
        a = cm.controler_registre(reg, CFG_TM, self.NOW)["anomalies"]
        self.assertTrue(any("USD/Taux de chômage" in x and "hors plage" in x for x in a))

    def test_divergence_ff_vs_fred_seulement_si_les_deux_valeurs_fred_s_ecartent(self):
        reg = self.reg([ev("USD", 56, "Unemployment Rate", T0, "4.2%", "4.1%", "4.1%")])
        reg["cases"]["USD|chomage"]["fred"] = {"valeur": "4.9%", "periode": "2026-08",
                                               "precedente": "4.8%", "serie": "UNRATE"}
        maintenant = datetime(2026, 9, 20, tzinfo=timezone.utc)
        a = cm.controler_registre(reg, CFG_TM, maintenant)["anomalies"]
        self.assertTrue(any("divergence de sources" in x for x in a))
        reg["cases"]["USD|chomage"]["fred"]["precedente"] = "4.2%"  # concorde avec la période précédente
        a = cm.controler_registre(reg, CFG_TM, maintenant)["anomalies"]
        self.assertFalse(any("divergence" in x for x in a))

    def test_publication_manquee(self):
        reg = self.reg([ev("USD", 56, "Unemployment Rate", T0, "4.2%", "4.1%", "4.1%"),
                        ev("USD", 56, "Unemployment Rate", T0 + 20 * 86400, None, "4.2%", "4.2%")])
        a = cm.controler_registre(reg, CFG_TM, self.NOW)["anomalies"]
        self.assertTrue(any("publication manquée" in x and "USD/Taux de chômage" in x for x in a))

    def test_case_non_applicable_expliquee_sans_anomalie(self):
        reg = self.reg([])
        r = cm.controler_registre(reg, CFG_TM, self.NOW)
        self.assertIn({"case": "JPY|emploi", "raison": "non publié dans ce pays"}, r["cases_sans_valeur"])
        self.assertFalse(any("JPY/Variation" in x for x in r["anomalies"]))


class IndiceSurprise(unittest.TestCase):
    AUJ = date(2026, 10, 6)

    def test_moyenne_ponderee_chomage_inverse_et_tendance(self):
        reg = rm.charger("inexistant.json")

        def d(j):
            return int(datetime(2026, 9, j, 12, tzinfo=timezone.utc).timestamp())
        # EUR : CPI +0,2 pt au-dessus du consensus (échelle 0,1 => +2), chômage +0,1 pt (inversé => -1)
        rm.integrer_evenements(reg, [ev("EUR", 168, "CPI Flash Estimate y/y", d(20), "3.8%", "3.6%", "3.3%"),
                                     ev("EUR", 59, "Unemployment Rate", d(25), "6.5%", "6.4%", "6.4%")], CFG_TM)
        i = cm.indice_surprise(reg, CFG_TM, self.AUJ)["EUR"]
        # poids CPI 3, chômage 2 : (3*2 + 2*(-1)) / 5 = 0.8
        self.assertEqual(i["indice"], 0.8)
        self.assertEqual(i["n"], 2)
        self.assertEqual(i["tendance"], "n/d")  # aucune publication dans la fenêtre précédente
        self.assertEqual(cm.texte_indice(i), "+0,8 (n=2)")

    def test_aucune_publication_avec_consensus(self):
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, [], CFG_TM)
        i = cm.indice_surprise(reg, CFG_TM, self.AUJ)["USD"]
        self.assertIsNone(i["indice"])
        self.assertTrue(cm.texte_indice(i).startswith("n/d"))


class CiblesEtMois(unittest.TestCase):
    def test_publication_recente_sans_reel_declenche_une_requete_ciblee_limitee(self):
        reg = rm.charger("inexistant.json")
        rm.integrer_evenements(reg, [ev("USD", 884, "CPI y/y", T0, "3.4%", "3.3%", "3.2%"),
                                     ev("USD", 884, "CPI y/y", T1, None, "3.5%", "3.4%")], CFG_TM)
        cfg_ff = CFG_TM["forexfactory"]
        trop_tot = datetime.fromtimestamp(T1 + 5 * 60, tz=timezone.utc)
        bon = datetime.fromtimestamp(T1 + 20 * 60, tz=timezone.utc)
        trop_tard = datetime.fromtimestamp(T1 + 13 * 3600, tz=timezone.utc)
        self.assertEqual(rm.publications_a_cibler(reg, cfg_ff, trop_tot, {}), [])
        cibles = rm.publications_a_cibler(reg, cfg_ff, bon, {})
        self.assertEqual(cibles, [f"USD|cpi@{T1}"])
        self.assertEqual(rm.publications_a_cibler(reg, cfg_ff, bon, {cibles[0]: 2}), [])  # max 2 tentatives
        self.assertEqual(rm.publications_a_cibler(reg, cfg_ff, trop_tard, {}), [])

    def test_collecte_ciblee_hors_creneau_puis_plafond(self):
        tmp = Path(tempfile.mkdtemp())
        sc = FauxScraping(page_html([]))
        cibles = [f"USD|cpi@{T1}"]
        t = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)
        ffm.collecter(CFG_TM, sc, tmp, t)                                    # créneau du matin
        r = ffm.collecter(CFG_TM, sc, tmp, t.replace(hour=14), cibles_fn=lambda deja: cibles)
        self.assertEqual((r["statut"], r["declencheur"]), ("frais", "ciblee"))
        cfg2 = json.loads(json.dumps(CFG_TM))
        cfg2["forexfactory"]["plafond_requetes_par_jour"] = 2
        r = ffm.collecter(cfg2, sc, tmp, t.replace(hour=15), cibles_fn=lambda deja: cibles)
        self.assertEqual(r["statut"], "non_due")                              # plafond atteint
        self.assertEqual(ffm.nom_mois(2, datetime(2026, 11, 5, tzinfo=timezone.utc)), "jan.2027")


class RendementsObligataires(unittest.TestCase):
    """Parseurs sur des échantillons réels (formats vérifiés le 2026-10-08) + intégration."""

    def test_parseur_bundesbank_virgule_decimale(self):
        texte = ("; | Einheit;Prozent; | Stand vom;08.10.2026 12:33:02 Uhr;\n"
                 "2026-10-03;.;\n2026-10-06;3,08;\n2026-10-07;3,07;\n2026-10-08;3,08;\n")
        with mock.patch.object(mt, "_get", return_value=mock.Mock(text=texte)):
            pts = mt.lire_bundesbank("X")
        self.assertEqual(pts[0], ("2026-10-08", 3.08))
        self.assertEqual(len(pts), 3)  # le « . » (jour sans cotation) est ignoré

    def test_parseur_boe_dates_anglaises(self):
        texte = "DATE,IUDMNPY\r\n05 Oct 2026,5.3634\r\n06 Oct 2026,5.3368\r\n"
        with mock.patch.object(mt, "_get", return_value=mock.Mock(text=texte)):
            pts = mt.lire_boe("IUDMNPY")
        self.assertEqual(pts[0], ("2026-10-06", 5.3368))

    def test_parseur_mof_colonnes_et_jours_sans_cotation(self):
        csv_txt = ("Interest Rate,(Unit : %)\nDate,1Y,2Y,10Y\n2026/9/29,1.5,1.9,3.0\n2026/9/30,-,1.952,3.057\n")
        with mock.patch.object(mt, "_get", return_value=mock.Mock(content=csv_txt.encode())):
            self.assertEqual(mt.lire_mof("2Y")[0], ("2026-09-30", 1.952))
            self.assertEqual(mt.lire_mof("10Y")[0], ("2026-09-30", 3.057))

    def test_parseur_boc_valet(self):
        js = {"observations": [{"d": "2026-10-02", "BD.CDN.2YR.DQ.YLD": {"v": "3.25"}},
                               {"d": "2026-10-05", "BD.CDN.2YR.DQ.YLD": {"v": "3.26"}}]}
        with mock.patch.object(mt, "_get", return_value=mock.Mock(json=lambda: js)):
            self.assertEqual(mt.lire_boc("BD.CDN.2YR.DQ.YLD")[0], ("2026-10-05", 3.26))

    def test_semaine_precedente_et_mensuel(self):
        pts = [("2026-10-06", 4.79), ("2026-10-05", 4.84), ("2026-09-29", 4.60), ("2026-09-28", 4.55)]
        r = mt._derniere_et_precedente(pts, 7)
        self.assertEqual((r["valeur"], r["precedente"], r["date_prec"]), (4.79, 4.60, "2026-09-29"))
        m = mt._mensuel([("2026-08-01", 0.47), ("2026-07-01", 0.48)])
        self.assertEqual((m["periode"], m["valeur"], m["precedente"], m["date"]), ("2026-08", 0.47, 0.48, None))

    def _registre(self):
        series = {
            "USD|2a": {"date": "2026-10-06", "valeur": 4.79, "date_prec": "2026-09-29", "precedente": 4.60,
                       "frequence": "quotidien", "source": "FRED (DGS2)"},
            "USD|10a": {"date": "2026-10-06", "valeur": 5.27, "date_prec": "2026-09-29", "precedente": 5.10,
                        "frequence": "quotidien", "source": "FRED (DGS10)"},
            "EUR|2a": {"date": "2026-10-08", "valeur": 3.08, "date_prec": "2026-10-01", "precedente": 3.20,
                       "frequence": "quotidien", "source": "Bundesbank"},
            "CHF|10a": {"date": None, "periode": "2026-08", "valeur": 0.47, "date_prec": None,
                        "periode_prec": "2026-07", "precedente": 0.48, "frequence": "mensuel", "source": "OCDE"},
        }
        reg = rm.charger("inexistant.json")
        couverture = mt.integrer(reg, {"series": series}, CFG_TM)
        return reg, couverture

    def test_spread_variation_et_couverture(self):
        reg, couv = self._registre()
        eur = reg["cases"]["EUR|spread_2a_usd"]
        self.assertEqual(eur["actuel"]["valeur"], "-171 pb")                    # (3,08 - 4,79) x 100
        self.assertEqual(eur["precedent"]["valeur"], "-140 pb")                 # (3,20 - 4,60) x 100
        self.assertEqual(eur["variation_pb"], -31.0)
        self.assertEqual(couv["EUR"]["spread"], "quotidien")
        self.assertEqual(couv["CHF"]["10a"], "mensuel")
        self.assertEqual(couv["CHF"]["spread"], "absent")                         # pas de 2 ans CHF
        self.assertEqual(couv["CNY"]["2a"], "absent")
        usd_spread = reg["cases"]["USD|spread_2a_usd"]
        self.assertEqual(usd_spread["absent"], "référence (États-Unis)")

    def test_affichage_donnee_de_marche_et_mensuel(self):
        reg, _ = self._registre()
        usd = reg["cases"]["USD|rendement_2a"]
        self.assertEqual(rm.valeur_cellule(usd, "Actuel", "%"), "4,79 %")
        self.assertEqual(rm.valeur_cellule(usd, "Précédent", "%"), "4,60 %")
        self.assertEqual(rm.valeur_cellule(usd, "Prévision", "%"), "— (donnée de marché)")
        chf = reg["cases"]["CHF|rendement_10a"]
        self.assertEqual(rm.valeur_cellule(chf, "Actuel", "%"), "0,47 % [mensuel]")
        self.assertEqual(rm.source_cellule(chf), "OCDE · pér. 08/26")
        self.assertEqual(rm.valeur_cellule(reg["cases"]["CNY|rendement_2a"], "Actuel", "%"),
                         "aucune source gratuite exploitable")

    def test_source_en_echec_conserve_la_derniere_valeur(self):
        reg, _ = self._registre()
        mt.integrer(reg, {"series": {}, "erreurs": ["EUR|2a : 500"]}, CFG_TM)
        self.assertEqual(reg["cases"]["EUR|rendement_2a"]["actuel"]["valeur"], "3.08%")

    def test_resume_pour_analyse(self):
        reg, _ = self._registre()
        r = mt.resume_pour_analyse(reg, CFG_TM)
        self.assertEqual(r["EUR"]["spread_2a_vs_usd_pb"], -171)
        self.assertEqual(r["EUR"]["variation_spread_semaine_pb"], -31.0)
        self.assertIsNone(r["CHF"]["spread_2a_vs_usd_pb"])
        self.assertEqual(r["CHF"]["frequence_10a"], "mensuel")
        self.assertNotIn("CNY", r)

    def test_ligne_notion_marche_surprise_et_variation(self):
        reg, _ = self._registre()
        m = tm.construire_matrice(reg, {"saisies": {}}, {}, CFG_TM, date(2026, 10, 8))
        ligne = next(r for r in m["lignes"] if r["cle"] == "USD|rendement_2a")
        self.assertEqual((ligne["Actuel"], ligne["surprise"], ligne["variation"]), ("4,79 %", "▲", "+19 pb"))
        self.assertEqual(ligne["Prévision"], "— (donnée de marché)")


class SpreadDansLeScore(unittest.TestCase):
    def _donnees(self, avec_spread: bool) -> dict:
        taux = {"source_id": "src_1", "valeurs": {"EUR": {"taux": 2.4, "source": "config", "date": "2026-01-15"}},
                "carry": {"differentiels": {"EUR": -1.2}}}
        if avec_spread:
            taux["spread_2a_vs_usd"] = {"source_id": "src_9",
                                        "valeurs": {"EUR": {"spread_2a_vs_usd_pb": -171}}}
        return {"macro": {"series": {}, "taux_directeurs": taux}, "technique": {}, "calendrier": []}

    def test_la_ligne_differentiel_de_taux_inclut_le_spread_2_ans(self):
        from agents import agent_strategiste as st
        ligne = next(l for l in st._tableau_indicateurs(CONFIG, "EUR", self._donnees(True))
                     if l["indicateur"] == "differentiel_taux")
        self.assertEqual(ligne["valeur"], "-1.20 pt · spread 2 ans vs US -171 pb")
        sans = next(l for l in st._tableau_indicateurs(CONFIG, "EUR", self._donnees(False))
                    if l["indicateur"] == "differentiel_taux")
        self.assertEqual(sans["valeur"], "-1.20 pt")  # sans spread : comportement inchangé

    def test_ponderations_inchangees(self):
        self.assertEqual(CONFIG["ponderations"]["differentiel_taux"], 8)
        self.assertEqual(CONFIG["ponderations_par_devise"]["CNY"]["differentiel_taux"], 8)


class GraphiquesDeMarche(unittest.TestCase):
    def test_resume_derniere_valeur_et_variation_semaine(self):
        from core import marche_series as ms
        points = [["2026-09-28", 100.0], ["2026-09-29", 101.0], ["2026-10-05", 108.0], ["2026-10-06", 110.0]]
        r = ms._resume(points)
        self.assertEqual((r["derniere"], r["date"], r["date_ref"]), (110.0, "2026-10-06", "2026-09-29"))
        self.assertEqual((r["variation"], r["variation_pct"]), (9.0, 8.91))

    def test_collecte_sans_cle_ne_plante_pas(self):
        from core import marche_series as ms
        r = ms.collecter(CFG_TM, "")
        self.assertEqual(r["graphiques"], {})
        self.assertTrue(r["erreurs"])

    def test_json_web_ecrit_une_fois_et_dollar_non_appele_dxy(self):
        from core import marche_series as ms
        tmp = Path(tempfile.mkdtemp())
        res = {"graphiques": {"dollar": {"titre": CFG_TM["graphiques_marche"]["dollar"]["titre"], "courbes": {}}}}
        self.assertTrue(ms.ecrire_web(res, tmp, "2026-10-08T10:00:00"))
        self.assertFalse(ms.ecrire_web(res, tmp, "2026-10-08T11:00:00"))   # contenu identique : pas de réécriture
        self.assertIn("pas le DXY", CFG_TM["graphiques_marche"]["dollar"]["titre"])
        self.assertNotIn("DXY (", CFG_TM["graphiques_marche"]["dollar"]["titre"])

    def test_miniatures_notion_sous_la_limite_d_url_et_en_colonnes(self):
        from agents import agent_redacteur as ar
        dates = [f"2026-{m:02d}-{j:02d}" for m in (7, 8, 9, 10) for j in range(1, 24)]
        serie = {"dates": dates, "valeurs": [100 + (i % 17) * 1.2345 for i in range(len(dates))]}
        blocs = ar._blocs_marches({"graphiques_marche": {"vix": serie, "wti": serie, "brent": serie,
                                                          "dollar_large": serie}})
        self.assertEqual([b["type"] for b in blocs], ["heading_2", "column_list"])
        images = [e for c in blocs[1]["column_list"]["children"] for e in c["column"]["children"]]
        self.assertEqual(len(images), 3)
        for image in images:
            self.assertLessEqual(len(image["image"]["external"]["url"]), 1900)  # limite Notion : 2000
        legendes = " ".join(i["image"]["caption"][0]["text"]["content"] for i in images)
        self.assertIn("pas le DXY", legendes)

    def test_aucune_miniature_si_aucune_donnee(self):
        from agents import agent_redacteur as ar
        self.assertEqual(ar._blocs_marches({"graphiques_marche": {}}), [])


if __name__ == "__main__":
    unittest.main()
