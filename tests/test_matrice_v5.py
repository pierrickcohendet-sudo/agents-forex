"""Lot V5, étape 2 : matrice d'impact à trois états + couverture par devise confirmée sur 5 ans, colonne « taux » du
tableau macro, vérification quotidienne des sources de rendement 2 ans. Sans réseau, sans LLM."""
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import yaml

from agents import collecte_historiques as ch
from core import couverture, matrice_impact as mi, tableau_macro as tm

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def impact(sensi=-0.4, conforme=True, wilson=55.0, n=30):
    m = {"n": n, "mediane": -0.5, "insuffisant": n < 20, "part_sens_attendu": 64, "borne_wilson_90": wilson,
         "lecture_classique": {"conforme": conforme}}
    return {"couples": {"vix|AUD": {"sensibilite": sensi, "scenarios": {"hausse|1": {"mois": m}, "baisse|1": {"mois": m}}}}}


def test_confirmation_par_sens_borne_de_wilson():
    assert couverture.confirmation(impact(), "vix", "AUD", "haut", -1)["confirmee"]
    faible = couverture.confirmation(impact(wilson=47.9), "vix", "AUD", "haut", -1)
    assert not faible["confirmee"] and "indice faible · 30 cas" in faible["raison"]
    assert "signe contraire" in couverture.confirmation(impact(sensi=0.3), "vix", "AUD", "haut", -1)["raison"]
    assert "insuffisant" in couverture.confirmation(impact(n=11), "vix", "AUD", "bas", -1)["raison"]
    assert not couverture.confirmation({}, "vix", "AUD", "haut", -1)["confirmee"]


def serie(n, f):
    d0 = date(2021, 6, 1)
    return [[(d0 + timedelta(days=i)).isoformat(), f(i)] for i in range(n)]


def test_seuils_fixes_et_percentiles_sur_5_ans():
    cfg = {"matrice_impact": {"couverture": {"percentiles": [15, 85], "fenetre_jours": 28, "regles": {"5": [
        {"indicateur": "vix", "serie": "vix", "mesure": "niveau", "unite": "pts", "seuils": {"haut": 40, "bas": 5}, "texte": "VIX"}]}}},
           "simulateur": {"lecture_classique": {"vix": {"AUD": -1}}}}
    # VIX de 12 à 30 en dents de scie, dernière valeur 29 : sous le seuil fixe (40) mais au-delà du 85e percentile
    histo = {"series": {"vix": {"source": "FRED (VIXCLS)", "points": serie(1900, lambda i: 12 + (i * 7) % 19) + [["2026-09-01", 29.0]]}}}
    r = couverture.evaluer(cfg, histo, impact())["5"][0]
    assert r["direction"] == "haut" and r["declencheur"] == "85e percentile sur 5 ans"
    assert r["seuil_haut"] == r["percentiles"]["85"] < 40
    assert r["devises"]["AUD"]["haut"]["confirmee"]


def case(m, devise, n):
    return next(c for l in m["lignes"] if l["devise"] == devise for c in l["cases"] if c["engrenage"] == n)


def test_trois_etats_et_ligne_de_compte():
    cfg = CONFIG["matrice_impact"]
    sig = {"ecart_2a_us_var_4s": {"EUR": (-20.0, "Bundesbank", "2026-10-22")},       # GBP absent : n/d
           "surprise_30j": {d: (0.1, "registre", "2026-10-22") for d in mi.DEVISES}}  # partout sous les seuils : neutre
    couv = {"5": [{"indicateur": "vix", "texte": "niveau du VIX", "unite": "pts", "direction": "haut", "valeur": 31.0,
                   "seuil_haut": 25.0, "seuil_bas": 14.0, "declencheur": "seuil fixe", "source": "FRED", "date": "2026-10-22",
                   "devises": {"GBP": {"signe_classique": -1,
                                       "haut": couverture.confirmation(impact(), "vix", "AUD", "haut", -1),
                                       "bas": {"confirmee": False, "raison": "x"}},
                               "CNY": {"signe_classique": -1, "haut": {"confirmee": False, "raison": "indice faible · 12 cas"},
                                       "bas": {"confirmee": False, "raison": "y"}}}}]}
    m = mi.matrice(cfg, sig, couv, False, "0 sur 4")
    assert case(m, "EUR", 2)["etat"] == "active" and case(m, "EUR", 2)["valeur"] == -1
    assert case(m, "GBP", 2)["etat"] == "nd" and "pas de donnée pour GBP" in case(m, "GBP", 2)["raison"]
    assert case(m, "USD", 3)["etat"] == "neutre" and case(m, "USD", 3)["libelle"] == "Neutre"
    gbp5 = case(m, "GBP", 5)
    assert gbp5["etat"] == "active" and gbp5["valeur"] == -1 and gbp5["regles"][0]["couverture"]
    cny5 = case(m, "CNY", 5)
    assert cny5["etat"] == "sans_regle" and "non confirmée sur 5 ans" in cny5["raison"]
    assert m["compte_libelle"].startswith(f"{m['comptes']['active']} actives, {m['comptes']['nd']} n/d, "
                                          f"{m['comptes']['sans_regle']} sans règle")
    assert sum(m["comptes"].values()) == 72


def test_regle_existante_jamais_comptee_deux_fois():
    cfg = CONFIG["matrice_impact"]
    sig = {"vix": (31.0, "FRED", "2026-10-22", None)}
    couv = {"5": [{"indicateur": "vix", "texte": "VIX", "unite": "pts", "direction": "haut", "valeur": 31.0, "seuil_haut": 25,
                   "seuil_bas": 14, "declencheur": "seuil fixe",
                   "devises": {"AUD": {"signe_classique": -1, "haut": {"confirmee": True, "raison": "ok"}, "bas": {"confirmee": True, "raison": "ok"}}}}]}
    aud = case(mi.matrice(cfg, sig, couv, False, None), "AUD", 5)
    assert aud["valeur"] == -2 and not any(r.get("couverture") for r in aud["regles"])   # règle VIX existante seule


def test_colonne_taux_borne_jpy_et_taux_effectif_usd():
    registre = {"cases": {
        "USD|taux_directeur": {"actuel": {"valeur": "3.88%", "date_pub": "2026-10-21", "origine": "taux_config", "source": "FRED (DFF)"},
                               "precedent": {"valeur": "3.75%"}},
        "JPY|taux_directeur": {"actuel": {"valeur": "<1.25%", "date_pub": "2026-09-18"}, "precedent": {"valeur": "<1.00%"},
                               "prevision": {"date_pub": "2026-10-30"}},
        "EUR|taux_directeur": {"actuel": {"valeur": "2.65%", "date_pub": "2026-09-10"}, "precedent": {"valeur": "2.40%"}}}}
    with mock.patch.object(tm.rm, "prochaine_publication", side_effect=lambda c: (c.get("prevision") or {}).get("date_pub")):
        infos = tm.infos_taux(registre, ["USD", "EUR", "JPY", "GBP"])
    assert infos["USD"]["variation_pb"] is None and "non comparable" in infos["USD"]["texte"]
    assert infos["EUR"]["variation_pb"] == 25 and infos["EUR"]["ecart_us_pb"] == -123
    jpy = infos["JPY"]
    assert jpy["borne"] == "<" and "écart US ≤ −263 pb" in jpy["texte"] and "au plus 1,25 %" in jpy["texte"]
    assert "prochaine 30/10" in jpy["texte"]
    assert "n/d" in infos["GBP"]["texte"]
    assert tm.lire_taux("<1.25%") == (1.25, "<") and tm.lire_taux("3,88 %") == (3.88, None)


def test_sonde_quotidienne_403_jamais_contournee():
    rep = mock.Mock(status_code=403, headers={"content-type": "text/html"})
    with mock.patch.object(ch.requests, "get", return_value=rep) as get:
        s = ch._sonder("https://www.rba.gov.au/statistics/tables/csv/f2-data.csv")
    assert s["statut"] == 403 and s["lecture"] == "accès automatisé refusé" and get.call_count == 1
    assert get.call_args.kwargs["headers"] is ch.UA                                   # en-tête honnête, inchangé
