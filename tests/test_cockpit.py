"""Lot V5, étapes 3 et 6 : cockpit (thermomètres, distances aux seuils, fil des séances) et agenda. Sans réseau, sans LLM."""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from core import agenda, cockpit

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def test_distance_etats_et_couloir():
    assert cockpit.distance(0.28, -0.3, 0.3) == {"etat": "proche", "distance": 0.02, "distance_pct": 3.3, "cote": "haut"}
    assert cockpit.distance(-0.58, -0.3, 0.3)["etat"] == "franchi"
    loin = cockpit.distance(19.03, 14, 25)
    assert loin["etat"] == "non" and loin["cote"] == "bas" and loin["distance_pct"] == 45.7
    assert cockpit.distance(None, 1, 2)["etat"] == "n/d"
    assert cockpit.distance(2, None, 3)["distance_pct"] == 33.3          # seuil d'un seul côté : % du seuil


def vue():
    cartes = [{"numero": n, "ligne": f"ligne {n}", "direction": {"libelle": "Dollar neutre", "classe": "nd"}} for n in range(1, 9)]
    cartes[6]["direction"] = {"libelle": "Dollar baissier · Risque neutre", "classe": "dn"}
    return {"cartes": cartes, "theme": {"titre": "Signaux mixtes", "titre_impose": True, "date_rapport": "2026-10-23",
                                        "direction": {"libelle": "Dollar baissier · Risque neutre", "classe": "dn", "dollar": "baissier",
                                                      "risque": "neutre", "conviction_niveau": "moyen"},
                                        "coherence": {"alignes": 1, "evaluables": 7, "theme_neutre": False}}}


def rapport():
    mesures = {2: {"libelle": "2 ans US sur 7 j", "valeur": -1.0, "unite": "pb", "seuil_bas": -10, "seuil_haut": 10,
                   "si_haut": "Dollar haussier", "si_bas": "Dollar baissier", "date": "2026-10-21", "source": "FRED"},
               5: {"libelle": "VIX", "valeur": 19.03, "unite": "pts", "seuil_bas": 14, "seuil_haut": 25,
                   "si_haut": "Risk off", "si_bas": "Risk on", "date": "2026-10-22", "source": "FRED (VIXCLS)"}}
    return {"synthese_globale": {"engrenages": {"engrenages": [{"numero": n, "mesure": mesures.get(n)} for n in range(1, 9)]}}}


MATRICE = {"signaux_valeurs": {"prime_terme_var_4s": (3.0, "FRED", "2026-10-16"), "titres_refuge": (2, "fil", "2026-10-24"),
                               "brent_var_4s": (12.0, "FRED", "2026-10-20", "série heurtée : +8,7 % le 15/10"),
                               "surprise_30j": {"CNY": (0.46, "registre", "2026-10-24")}},
           "couverture": {}, "cases_actives": 11, "cases_total": 72, "compte_libelle": "11 actives"}


def test_thermometres_positions_et_seuils_des_regles():
    th = {t["numero"]: t for t in cockpit.thermometres(vue(), MATRICE, rapport(), CONFIG)}
    assert len(th) == 8
    vix = th[5]
    assert (vix["seuil_bas"], vix["seuil_haut"]) == (14, 25) and 0 < vix["pos_bas"] < vix["pos"] < vix["pos_haut"] < 100
    assert (vix["classe_bas"], vix["classe_haut"]) == ("up", "dn")                       # risk on vert, risk off rouge
    assert th[4]["seuil_haut"] == 20 and th[6]["seuil_haut"] == 3                         # lus dans config.yaml
    assert (th[8]["seuil_bas"], th[8]["seuil_haut"]) == (-10, 10)
    assert th[8]["neutralise"].startswith("au-delà du seuil mais neutralisé")
    assert th[3]["valeur"] is None and "mesure absente" in th[3]["raison"]
    assert th[1]["valeur"] == 1 and th[1]["seuil_haut"] == 3 and "Titre imposé" in th[1]["note"]


def test_au_bord_du_seuil_et_signaux_classes():
    c = cockpit.calculer(vue(), MATRICE, rapport(), CONFIG, None, None)
    assert [s["etat"] for s in c["signaux"]][0] == "franchi"
    bord = c["au_bord"]
    assert len(bord) == 3 and bord[0]["id"] == "surprise_30j-CNY" and "du couloir neutre" in bord[0]["phrase"]
    assert all(b["etat"] in ("proche", "non") for b in bord)
    assert c["entete"]["titre_impose"] and c["entete"]["alignes"] == 1 and "7. Flux" in c["entete"]["explication"]


def test_fil_des_seances_jours_sans_rapport_hachures():
    d = Path(tempfile.mkdtemp())
    (d / "2026-10-23.json").write_text(json.dumps({"synthese_globale": {"engrenages": {"engrenages": [
        {"numero": 7, "direction": {"dollar": "baissier"}}, {"numero": 5, "direction": {"dollar": "neutre", "risque": "neutre"}}]}}}),
        encoding="utf-8")
    f = cockpit.fil(d, "2026-10-23")
    assert len(f["jours"]) == 15 and f["jours"][-1] == "2026-10-23" and all(date_semaine(j) for j in f["jours"])
    l7 = f["lignes"][6]["cellules"]
    assert l7[-1]["classe"] == "dn" and l7[0]["classe"] is None and l7[0]["libelle"] == "pas de rapport ce jour-là"
    assert f["lignes"][4]["cellules"][-1]["classe"] == "nd"


def date_semaine(j):
    return datetime.fromisoformat(j).weekday() < 5


FF = json.dumps([
    {"title": "Federal Funds Rate", "country": "USD", "date": "2026-10-28T14:00:00-04:00", "impact": "High", "forecast": "4.00%", "previous": "3.75%"},
    {"title": "CPI y/y", "country": "AUD", "date": "2026-10-27T20:30:00-04:00", "impact": "High", "forecast": "4.2%", "previous": "4.0%"},
    {"title": "German Ifo", "country": "EUR", "date": "2026-10-25T04:00:00-04:00", "impact": "Medium", "forecast": "", "previous": "88.1"},
    {"title": "Hors fenêtre", "country": "USD", "date": "2026-11-20T08:30:00-05:00", "impact": "High"}])


def test_agenda_heures_de_paris_impacts_publie_et_engrenage():
    gl = [{"devise": "EUR", "evenement": "German Ifo", "date": "2026-10-25", "reel": "89.0"}]
    reg = {"cases": {"GBP|taux_directeur": {"devise": "GBP", "indicateur": "taux_directeur", "actuel": {"valeur": "3.75%", "date_pub": "2026-09-17"},
                                            "precedent": {"valeur": "3.75%"},
                                            "prevision": {"dateline": int(datetime(2026, 10, 29, 12, tzinfo=timezone.utc).timestamp()),
                                                          "nom_ff": "Official Bank Rate", "impact": "High"}}}}
    a = agenda.calculer(FF, gl, reg, CONFIG, datetime(2026, 10, 24, 10, tzinfo=timezone.utc))
    evts = [e for j in a["jours"] for e in j["evenements"]]
    assert len(a["jours"]) == 7 and "Hors fenêtre" not in [e["evenement"] for e in evts]
    fed = next(e for e in evts if e["evenement"] == "Federal Funds Rate")
    assert fed["heure_paris"] == "19:00" and fed["impact"] == "fort" and fed["engrenage"] == 2 and fed["simulateur"] == "fed"
    assert next(e for e in evts if e["devise"] == "AUD")["date_paris"] == "2026-10-28"     # 20:30 New York = 01:30 Paris
    ifo = next(e for e in evts if e["evenement"] == "German Ifo")
    assert ifo["publie"] == "89.0" and ifo["impact"] == "moyen" and ifo["consensus"] is None and ifo["raison_consensus"]
    boe = next(e for e in evts if e["devise"] == "GBP")
    assert boe["source"].startswith("registre macro") and boe["engrenage"] == 2
    bc = next(b for b in a["banques_centrales"] if b["devise"] == "GBP")
    assert bc["prochaine"] == "2026-10-29" and bc["variation_pb"] == 0 and bc["raison_reunions"]
    assert agenda.prochain_rendez_vous(a)["evenement"] in ("CPI y/y", "Federal Funds Rate", "Official Bank Rate")
