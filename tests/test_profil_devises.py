"""Profil des devises (lot V6, partie A) : moteur du moment (corrélations 60 / 20 séances), ancrage confirmé ou
contredit, posture de la banque centrale, importance de la semaine, état. Données synthétiques, sans réseau."""
import math
import random
from datetime import date, timedelta
from pathlib import Path

import yaml

from core import historique_5ans as h5m, profil_devises as pd

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
CFG = CONFIG["profil_devises"]


def jours(n, fin=date(2026, 10, 30)):
    d, sortie = fin, []
    while len(sortie) < n:
        if d.weekday() < 5:
            sortie.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(sortie)


def historique(sens_vix=1.0, bruit=0.2, graine=1, n=90):
    """JPY dont la force suit le VIX (sens_vix) avec du bruit ; S&P 500 indépendant."""
    alea = random.Random(graine)
    dates = jours(n)
    vix, usdjpy, spx = [20.0], [150.0], [5000.0]
    for _ in dates[1:]:
        dv = alea.gauss(0, 0.03)
        vix.append(vix[-1] * math.exp(dv))
        force = sens_vix * dv * 0.3 + alea.gauss(0, 0.009 * bruit)
        usdjpy.append(usdjpy[-1] * math.exp(-force))       # FX_JPY en yens par dollar : force = inverse
        spx.append(spx[-1] * math.exp(alea.gauss(0, 0.01)))
    return h5m.Historique.depuis_points({"FX_JPY": list(zip(dates, usdjpy)), "vix": list(zip(dates, vix)),
                                         "sp500": list(zip(dates, spx))})


def test_moteur_dominant_stable_et_ancrage_refuge_confirme():
    m = pd.moteurs_du_moment(historique(1.0), None, "JPY", CFG)
    assert m["dominant"]["moteur"] == "vix" and m["dominant"]["r60"] > 0.3 and m["dominant"]["stable"]
    assert "corrélation +0," in m["texte"] and "60 séances" in m["texte"] and "cause" not in m["texte"]
    assert {x["moteur"] for x in m["non_testes"]} >= {"surprises_bc"}            # n/d avec sa raison
    anc = {a["libelle"]: a for a in pd.ancrages("JPY", CFG, m)}
    assert anc["Refuge"]["verdict"] == "confirmé"


def test_ancrage_contredit_jpy_qui_baisse_quand_le_vix_monte():
    m = pd.moteurs_du_moment(historique(-1.0), None, "JPY", CFG)
    anc = pd.ancrages("JPY", CFG, m)
    et = pd.etat("JPY", CFG, anc, None, {"valeur": None}, {"surprise_30j": {"indice": None}}, None, date(2026, 11, 3))
    assert et["valeur"] == "Ancrage contredit"
    assert "Refuge" in et["raison"] and "négative" in et["raison"]


def test_aucun_moteur_dominant_sous_le_seuil():
    m = pd.moteurs_du_moment(historique(0.0, bruit=1.0), None, "JPY", CFG)
    assert m["dominant"] is None and m["texte"].startswith("Aucun moteur dominant")


def test_etats_soutenue_sous_pression_sans_direction():
    auj = date(2026, 11, 3)
    bc_dovish = {"date": "2026-10-28", "surprise_pb": -25, "texte": "maintien à 2,75 % le 28/10, 3,00 % attendu (−25 pb)"}
    mac = lambda i: {"surprise_30j": {"indice": i}}
    assert pd.etat("NZD", CFG, [], bc_dovish, {}, mac(-0.9), None, auj)["valeur"] == "Sous pression"
    assert pd.etat("CHF", CFG, [], None, {}, mac(0.5), {"pct": 1.4}, auj)["valeur"] == "Soutenue"
    neutre = pd.etat("CAD", CFG, [], None, {}, mac(-0.7), {"pct": 1.6}, auj)
    assert neutre["valeur"] == "Sans direction" and "Total 0" in neutre["raison"]
    vieux = {**bc_dovish, "date": "2026-08-01"}                                   # décision trop ancienne : ignorée
    assert pd.etat("NZD", CFG, [], vieux, {}, mac(-0.9), None, auj)["valeur"] == "Sans direction"


def test_derniere_decision_et_importance_de_la_semaine():
    pubs = {"publications": {"k": {"devise": "NZD", "nom": "Official Cash Rate", "date": "2026-10-28",
                                   "reel": "2.75%", "prevision": "3.00%", "precedent": "2.75%"}}}
    d = pd.derniere_decision("NZD", CFG, pubs, None, date(2026, 11, 3))
    assert (d["decision"], d["surprise_pb"]) == ("maintien", -25) and d["texte"] == "maintien à 2,75 % le 28/10, 3,00 % attendu (−25 pb)"
    agenda = {"jours": [{"date": "2026-11-05", "evenements": [
        {"devise": "GBP", "type": "Réunion BC", "impact": "fort", "date_paris": "2026-11-05", "evenement": "Décision BoE"},
        {"devise": "GBP", "type": "Chiffre", "impact": "fort", "date_paris": "2026-11-05", "evenement": "PMI"}]}]}
    s = pd.semaine("GBP", agenda, date(2026, 11, 3))
    assert s["score"] == 3 and s["texte"].startswith("décision de la banque centrale (05/11)")
    assert pd.semaine("CHF", agenda, date(2026, 11, 3))["score"] == 1


def test_profil_reel_sans_pourcentage_de_confluence():
    """Sur les fichiers publiés du dépôt : 9 devises, un état parmi les 4, aucun score en %, jamais « cause »."""
    prof = pd.calculer(CONFIG, h5m.charger(), None, None, None, None, None, RACINE, date(2026, 11, 3))
    assert [d["devise"] for d in prof["devises"]] == list(CONFIG["devises"])
    for d in prof["devises"]:
        assert d["etat"]["valeur"] in pd.ETATS and d["etat"]["raison"]
        texte = d["lecture"] + d["moteur"]["texte"]
        assert "confluence" not in texte and " cause" not in texte
        assert not any(c.isdigit() and "." in texte[i:i + 2] for i, c in enumerate(texte))   # virgule décimale
