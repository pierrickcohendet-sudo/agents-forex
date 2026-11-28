"""Lot V16.2 : lectures ForexFactory garanties chaque jour, créneau rattrapé par le premier run qui suit (veille comprise),
réserve d'historique consommée chaque jour, alerte de fraîcheur des prévisions. Tout est simulé : aucune requête réseau."""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from agents import collecte_forexfactory_mois as ffm
from core import agenda as ag_mod
from core import alertes_telephone
from core import ff_historique as ffh
from core import ff_planning as plan
from outils import decider_mode

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
CFG = {"forexfactory": {**CONFIG["tableau_macro"]["forexfactory"]}}


def _e(iso, impact="fort", dev="USD", nom="CPI y/y"):
    return {"iso_utc": iso, "impact": impact, "devise": dev, "evenement_en": nom, "heure_connue": True, "type": "Chiffre"}


def test_jour_sans_publication_forte_au_moins_une_lecture():
    p = plan.planifier({"jours": []}, date(2026, 11, 27))            # vendredi après Thanksgiving : rien de fort
    heures = [x["heure_utc"] for x in p["lectures"]]
    assert "06:00" in heures and len(heures) >= 1
    assert all(x.get("garantie") for x in p["lectures"])


def test_samedi_lecture_du_soir_pour_la_semaine_suivante():
    p = plan.planifier({"jours": []}, date(2026, 11, 28))
    assert [x["heure_utc"] for x in p["lectures"]] == ["06:00", "19:00"]
    assert "semaine suivante" in p["lectures"][1]["motif"]
    p = plan.planifier({"jours": []}, date(2026, 11, 25))            # mercredi : pas de lecture du soir garantie
    assert [x["heure_utc"] for x in p["lectures"]] == ["06:00"]


def test_lectures_fortes_ajoutees_dans_le_plafond():
    a = {"jours": [{"evenements": [_e(f"2026-11-26T{h:02d}:30+00:00") for h in range(8, 22)]}]}
    p = plan.planifier(a, date(2026, 11, 26), plafond=6, reserve=2)
    assert len(p["lectures"]) == 4 and p["lectures"][0]["heure_utc"] == "06:00"   # 1 garantie + 3 fortes + 2 historique = 6
    a27 = {"jours": [{"evenements": [_e(f"2026-11-27T{h:02d}:30+00:00") for h in range(8, 22)]}]}
    p = plan.planifier(a27, date(2026, 11, 27), plafond=6, reserve=2)          # vendredi : 2 garanties + 2 fortes + 2 historique
    assert len(p["lectures"]) == 4 and {"06:00", "19:00"} <= {x["heure_utc"] for x in p["lectures"]}


def test_creneau_rattrape_par_le_run_suivant_meme_le_lendemain():
    veille = {"lectures": [{"heure_utc": "23:37", "date_utc": "2026-11-26", "motif": "Tokyo"}]}
    jour = {"lectures": [{"heure_utc": "06:00", "date_utc": "2026-11-27", "motif": "base"}]}
    # 02:08 le 27/11 : le créneau de 23:37 la veille n'a pas été couvert -> dû
    ok, raison = plan.lecture_due(jour, veille, [], ["2026-11-26T08:16:01+00:00"], datetime(2026, 11, 27, 2, 8, tzinfo=timezone.utc))
    assert ok and "23:37" in raison and "26/11" in raison
    # couvert par une lecture faite après 23:37 : rien jusqu'au créneau de 06:00
    ok, _ = plan.lecture_due(jour, veille, ["2026-11-27T02:08:00+00:00"], [], datetime(2026, 11, 27, 4, 0, tzinfo=timezone.utc))
    assert not ok
    # le run de 08:19 honore la lecture de 06:00 (pas de fenêtre exacte)
    ok, raison = plan.lecture_due(jour, veille, ["2026-11-27T02:08:00+00:00"], [], datetime(2026, 11, 27, 8, 19, tzinfo=timezone.utc))
    assert ok and "06:00" in raison and "139 min" in raison
    # plafond atteint : jamais
    assert not plan.lecture_due(jour, veille, ["x"] * 6, [], datetime(2026, 11, 27, 8, 19, tzinfo=timezone.utc))[0]


def test_decideur_et_collecte_suivent_la_meme_regle(tmp_path):
    d = {"jours": {"2026-11-26": {"lectures": [{"heure_utc": "23:37", "date_utc": "2026-11-26"}]},
                   "2026-11-27": {"lectures": [{"heure_utc": "06:00", "date_utc": "2026-11-27", "garantie": True}]}}}
    (tmp_path / "ff_planning.json").write_text(json.dumps(d), encoding="utf-8")
    (tmp_path / "forexfactory_requetes.json").write_text(json.dumps({"date": "2026-11-26", "horodatages": ["2026-11-26T08:16:01+00:00"]}))
    m = datetime(2026, 11, 27, 2, 8, tzinfo=timezone.utc)
    assert decider_mode.lecture_due(d, json.loads((tmp_path / "forexfactory_requetes.json").read_text()), m)[0]
    assert decider_mode.decider("schedule", decider_mode.CRON_LECTURES, {}, False, [], None, m, decider_mode.lecture_due(d, {}, m))[0] == "lecture"

    class Client:
        urls = []

        def requete_directe(self, site, url):
            self.urls.append(url)
            return {"statut": "frais", "contenu": "<script>window.calendarComponentStates[1] = {\ndays: [],\n}</script>", "note": ""}
    r = ffm.collecter(CFG, Client(), tmp_path, m)
    assert r["statut"] == "frais" and r["declencheur"] == "planning"
    b = json.loads((tmp_path / "forexfactory_requetes.json").read_text())
    assert b["date"] == "2026-11-27" and b["veille"]["date"] == "2026-11-26" and len(b["horodatages"]) == 1
    assert ffm.collecter(CFG, Client(), tmp_path, datetime(2026, 11, 27, 4, 0, tzinfo=timezone.utc))["statut"] == "non_due"


def test_plan_du_jour_sans_lecture_garantie_recalcule(tmp_path):
    (tmp_path / "ff_planning.json").write_text(json.dumps({"jours": {"2026-11-28": {"lectures": []}}}), encoding="utf-8")
    plan.mettre_a_jour(tmp_path, {"jours": []}, datetime(2026, 11, 28, 7, 0, tzinfo=timezone.utc))
    assert plan.creneaux(tmp_path, date(2026, 11, 28)) == ["06:00", "19:00"]


def test_reserve_d_historique_consommee_chaque_jour(tmp_path):
    class Client:
        def __init__(self):
            self.urls = []

        def requete_directe(self, site, url):
            self.urls.append(url)
            jours = [{"events": [{"id": 1, "currency": "USD", "name": "CPI y/y", "impactName": "high", "dateline": 1791981000,
                                  "actual": "3.7%", "forecast": "3.6%", "previous": "", "revision": "", "url": ""}]}]
            return {"statut": "frais", "contenu": "<script>window.calendarComponentStates[1] = {\ndays: " + json.dumps(jours) + ",\n}</script>", "note": ""}
    for k, jour in enumerate((27, 28)):
        c = Client()
        b = ffh.reprendre(CFG, c, tmp_path, datetime(2026, 11, jour, 6, 5, tzinfo=timezone.utc))
        assert len(b["lus"]) == 2 and len(c.urls) == 2                       # 2 pages par jour, sans planning
        assert ffh.reprendre(CFG, Client(), tmp_path, datetime(2026, 11, jour, 9, 0, tzinfo=timezone.utc))["lus"] == []
    assert ffh.etat(ffh.lire(tmp_path), date(2026, 11, 28))["n_lus"] == 4
    assert CONFIG["tableau_macro"]["forexfactory"].get("reprise_historique", True)


def test_fraicheur_des_previsions_et_alerte():
    m = datetime(2026, 11, 28, 7, 0, tzinfo=timezone.utc)
    f = ag_mod.fraicheur_previsions("2026-11-26T08:16:01+00:00", m)
    assert f["alerte"] and f["retard_h"] > 24 and f["texte"].startswith("Prévisions mises à jour le 26/11 à 09:16")
    assert not ag_mod.fraicheur_previsions("2026-11-28T06:05:00+00:00", m)["alerte"]
    msgs = alertes_telephone.messages({}, {"jours": [], "previsions": f}, m)
    assert any(x["titre"].startswith("Agenda : prévisions ForexFactory") for x in msgs)
    d = ag_mod.calculer(None, [], {}, CONFIG, m, mois=[], verifs={"mois": "2026-11-26T08:16:01+00:00"})
    assert d["previsions"]["alerte"]


def test_cron_des_lectures_tous_les_jours():
    assert decider_mode.CRON_LECTURES == "7,37 * * * *"
    assert '"7,37 * * * *"' in (RACINE / ".github" / "workflows" / "rapport.yml").read_text(encoding="utf-8")
