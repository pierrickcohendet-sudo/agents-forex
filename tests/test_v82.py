"""Lot V8.2 : page Paire enrichie. RSI de Wilder (valeurs calculées à la main), pivots et zones, lignes de tendance,
divergences, écart de taux (corrélation, sensibilité), budget Twelve Data simulé sur une journée complète.
Sans réseau, sans modèle (quota 0)."""
import json
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from agents import collecte_intraday as ci
from core import ecart_taux as et, paires, quota_twelve, technique_avancee as ta

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def bougies_de(clotures, demi=0.0002, pas_h=4):
    t0 = datetime(2026, 9, 1)
    return [[(t0 + timedelta(hours=pas_h * i)).strftime("%Y-%m-%d %H:%M:%S"), c, c + demi, c - demi, c] for i, c in enumerate(clotures)]


def chemin(*sommets, pas=4):
    """Prix interpolés entre des sommets (pas bougies par jambe)."""
    out = [sommets[0]]
    for a, b in zip(sommets, sommets[1:]):
        out += [a + (b - a) * k / pas for k in range(1, pas + 1)]
    return out


# ------------------------------------------------------------------ B. RSI de Wilder
def test_rsi_wilder_valeurs_calculees_a_la_main():
    # 1, 2, 3, 2, 4 sur 3 périodes : hausses 1, 1, 0 / baisses 0, 0, 1 -> moyennes 2/3 et 1/3, RS 2, RSI 66,67 ;
    # puis hausse 2 : (2/3 × 2 + 2) / 3 = 1,111 ; baisses (1/3 × 2) / 3 = 0,222 ; RS 5, RSI 83,33
    assert ta.rsi_wilder([1, 2, 3, 2, 4], 3) == [None, None, None, 66.67, 83.33]
    # Série de référence de Wilder (14 périodes) : hausses 3,34 / 14 et baisses 1,40 / 14 -> RSI 70,46 ;
    # puis baisse de 0,28 : (0,238571 × 13) / 14 = 0,221531 et (0,1 × 13 + 0,28) / 14 = 0,112857 -> RSI 66,25
    c = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
    r = ta.rsi_wilder(c)
    assert r[:14] == [None] * 14 and r[14] == 70.46 and r[15] == 66.25
    assert ta.rsi_wilder([1, 2, 3, 4, 5, 6], 3)[-1] == 100.0                        # aucune baisse : 100


# ------------------------------------------------------------------ C. pivots, zones et force
def test_pivots_zones_et_force():
    c = chemin(1.095, 1.090, 1.100, 1.090, 1.100, 1.090, 1.100, 1.095, pas=6)
    b = bougies_de(c)
    pv = ta.pivots(b, 3)
    assert [p["type"] for p in pv].count("haut") == 3 and [p["type"] for p in pv].count("bas") == 3
    z = ta.zones(b, 3, "EUR/USD")
    r1, s1 = z["resistances"][0], z["supports"][0]
    assert (r1["nom"], r1["contacts"], r1["force"]) == ("R1", 3, 3) and r1["etiquette"] == "R1 · 3 contacts"
    assert abs(r1["haut"] - 1.1002) < 1e-9 and r1["distance_pips"] == pytest.approx(52.0, abs=0.2)   # (1,1002 − 1,0950) / 0,0001
    assert (s1["nom"], s1["contacts"]) == ("S1", 3) and s1["distance_pips"] < 0 and s1["distance_pct"] < 0
    # force : 1 à 3 selon les contacts, moins 1 si le dernier contact est ancien (première moitié de la période)
    assert ta.force_zone(5, 90, 100) == 3 and ta.force_zone(3, 10, 100) == 2 and ta.force_zone(1, 10, 100) == 1
    # pivots distants de plus de 0,25 × ATR : deux zones distinctes
    b2 = bougies_de(chemin(1.095, 1.090, 1.100, 1.090, 1.110, 1.095, pas=6))
    assert len(ta.zones(b2, 3, "EUR/USD")["resistances"]) == 2
    assert ta.zones(b[:5], 3)["raison"]                                             # trop court : raison, pas d'invention


# ------------------------------------------------------------------ D. lignes de tendance
def test_lignes_de_tendance_valide_cassee_contacts():
    base = chemin(1.05, 1.00, 1.06, 1.02, 1.08, 1.07, pas=4)        # creux montants 1,00 puis 1,02
    l = ta.lignes_tendance(bougies_de(base), 3, "EUR/USD")["support"]
    assert l["etat"] == "valide" and l["contacts"] == 2 and l["visible"]
    assert l["p1"]["prix"] == pytest.approx(0.9998) and l["p2"]["prix"] == pytest.approx(1.0198)
    assert l["pente_pips_jour"] == pytest.approx(150.0, abs=0.5)    # 200 pips en 8 bougies de 4 h = 1,33 jour
    # retour sur la ligne après le second point : contact supplémentaire
    touche = chemin(1.05, 1.00, 1.06, 1.02, 1.08, 1.0402, 1.07, pas=4)
    assert ta.lignes_tendance(bougies_de(touche), 3, "EUR/USD")["support"]["contacts"] == 3
    # clôture sous la ligne : cassée, datée ; masquée au-delà de 5 bougies
    casse = base + [0.98, 0.975, 0.97]
    lc = ta.lignes_tendance(bougies_de(casse), 3, "EUR/USD")["support"]
    assert lc["etat"] == "cassée" and lc["texte"].startswith("cassée le ") and "0,98" in lc["texte"] and lc["visible"]
    assert ta.lignes_tendance(bougies_de(casse + [0.97] * 6), 3, "EUR/USD")["support"]["visible"] is False
    # sommets montants : pas de résistance baissière, avec la raison
    assert "ne descendent pas" in ta.lignes_tendance(bougies_de(base), 3, "EUR/USD")["raison_resistance"]


# ------------------------------------------------------------------ B2. divergences
def test_divergences_confirmees_seulement():
    c = chemin(1.00, 1.05, 1.02, 1.06, 1.03, pas=6)                 # sommets 1,05 puis 1,06 (plus haut)
    b = bougies_de(c)
    rsi = [50.0] * len(c)
    rsi[6], rsi[18] = 72.0, 64.0                                    # RSI plus bas au second sommet
    d = ta.divergences(b, rsi, 3)
    assert len(d) == 1 and d[0]["sens"] == "baissière" and d[0]["texte"].startswith("divergence baissière : prix plus haut, RSI plus bas (")
    rsi[18] = 75.0                                                  # RSI plus haut aussi : pas de divergence
    assert ta.divergences(b, rsi, 3) == []
    # second sommet pas encore confirmé (moins de 3 bougies après) : rien
    assert ta.divergences(b[:20], [50.0] * 20, 3) == []


# ------------------------------------------------------------------ E. écart, corrélation, sensibilité
def test_ecart_correlation_sensibilite():
    jours = [(date(2026, 6, 1) + timedelta(days=i)).isoformat() for i in range(90)]
    ecart_pb = [100 + (i % 7) * 3 - (i % 5) * 2 + i * 0.1 for i in range(90)]
    us = [[d, 4.0] for d in jours]
    jp = [[d, round(4.0 - e / 100, 6)] for d, e in zip(jours, ecart_pb)]
    ec = et.serie_ecart(us, jp)
    assert ec[0] == [jours[0], 100.0] and len(ec) == 90
    # la paire bouge de 4 pips (0,04 yen) par pb d'écart : corrélation 1, +10 pb ≈ +40 pips
    px = [(d, 150 + 0.04 * e) for d, e in zip(jours, ecart_pb)]
    l = et.lien(ec, px, "USD/JPY")
    assert l["correlation"] == 1.0 and l["sensibilite_pips_10pb"] == pytest.approx(40.0, abs=0.1) and l["observations"] == 60
    assert et.phrase("2a", 0.62, 38) == "La paire suit l'écart 2 ans (corrélation +0,62) : +10 pb d'écart ≈ +38 pips en moyenne."
    assert "lien faible" in et.phrase("10a", 0.1, 5)
    assert et.variation([["2026-10-01", 100.0], ["2026-10-24", 110.0], ["2026-10-31", 112.5]], 7) == 2.5
    # série mensuelle : valeurs prises aux dates de la série mensuelle, sans interpolation
    assert et.serie_ecart([["2026-09-01", 5.0], ["2026-10-01", 5.2]], [["2026-09-30", 4.0], ["2026-10-01", 4.1]], True, False) == [["2026-10-01", 110.0]]
    assert et.lien(ec[:10], px, "USD/JPY")["correlation"] is None                     # trop peu de séances : n/d avec raison


def test_ecart_gbp_2_ans_absent_10_ans_utilise():
    jours = [(date(2026, 8, 1) + timedelta(days=i)).isoformat() for i in range(80)]
    cache = {"series": {"GBP_10a": {"frequence": "quotidien", "source": "BoE", "points": [[d, 4.5] for d in jours]},
                        "USD_10a": {"frequence": "quotidien", "source": "FRED", "points": [[d, 4.0] for d in jours]},
                        "USD_2a": {"frequence": "quotidien", "source": "FRED", "points": [[d, 3.6] for d in jours]}}}
    b = et.calculer_paire("GBP/USD", cache, [(d, 1.3) for d in jours], et.raisons_absence(CONFIG), date(2026, 10, 20))
    assert b["maturites"]["2a"]["disponible"] is False and b["maturites"]["2a"]["raison"].startswith("pas de 2 ans britannique gratuit")
    assert b["defaut"] == "10a" and b["note_defaut"].endswith(": écart 10 ans utilisé") and b["maturites"]["10a"]["actuel_pb"] == 50.0
    c = et.calculer_paire("USD/CNY", cache, [], et.raisons_absence(CONFIG), date(2026, 10, 20))
    assert c["defaut"] is None and "chinois" in c["raison"]
    # cache : points du jour ajoutés, 400 jours gardés
    f = et.fusionner({"series": {"USD_2a": {"points": [["2024-01-01", 1.0], ["2026-10-01", 3.5]]}}},
                     {"taux_quotidiens": {"USD_2a": {"source": "FRED", "frequence": "quotidien", "points": [["2026-10-02", 3.6]]}}},
                     ["USD_2a"], date(2026, 10, 3))
    assert f["series"]["USD_2a"]["points"] == [["2026-10-01", 3.5], ["2026-10-02", 3.6]]


# ------------------------------------------------------------------ A. budget Twelve Data simulé sur une journée
def test_budget_twelve_data_journee_complete(tmp_path, monkeypatch):
    plan = ci.plan_journee(CONFIG)
    assert plan["total"] <= 500 and len(ci.groupes(CONFIG)["suivies"]) == 10
    assert ci.groupes(CONFIG)["suivies"][6:] == ["EUR/JPY", "GBP/JPY", "EUR/GBP", "AUD/JPY"]
    # Journée simulée : toutes les requêtes passent par le compteur partagé (horloge simulée, 2 s par requête)
    horloge = {"t": 0.0}
    journal = []
    q = tmp_path / "q.json"
    monkeypatch.setattr(quota_twelve, "_minute", deque())
    monkeypatch.setattr(quota_twelve, "PAR_MINUTE", 8)            # conftest la désactive ; ici elle est vérifiée
    monkeypatch.setattr(quota_twelve, "_jour", lambda: "2026-11-05")

    def dormir(s):
        horloge["t"] += s

    def consommer(n, module):
        horloge["t"] += 2
        quota_twelve.consommer(n, module, chemin=q, horloge=lambda: horloge["t"], dormir=dormir)
        journal.append((horloge["t"], n))

    etat = lambda: quota_twelve.etat(q)   # noqa: E731

    class Rep:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"status": "ok", "values": [{"datetime": "2026-11-05 08:00:00", "open": "1", "high": "1.1", "low": "0.9", "close": "1"}]}

    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: Rep())
    racine = tmp_path
    j = datetime(2026, 11, 5, tzinfo=timezone.utc)
    consommer(ci.TECHNIQUE_JOUR // 2, "technique"); consommer(ci.TECHNIQUE_JOUR // 2, "technique")
    consommer(ci.HISTORIQUES_JOUR, "historiques")
    ci.collecter(CONFIG, racine, cle="x", mode="matin", maintenant=j.replace(hour=8, minute=20), consommer=consommer, etat_quota=etat)
    consommer(ci.SEANCE_PAR_PASSAGE, "seance")
    for h in ci.HEURES_COMPLEMENTS:
        consommer(ci.SEANCE_PAR_PASSAGE, "seance")
        ci.collecter(CONFIG, racine, cle="x", mode="heure", maintenant=j.replace(hour=h, minute=16), consommer=consommer, etat_quota=etat)
    total = quota_twelve.etat(q)["credits"]
    assert total == plan["total"] and total <= 500                                   # 420 prévus, 420 consommés
    cache = json.loads((racine / "data" / "cache" / "intraday.json").read_text(encoding="utf-8"))
    assert cache["midi"] == "2026-11-05"                                              # seconde collecte faite à 13 h Paris
    # jamais plus de 8 crédits dans une minute glissante
    for t, _ in journal:
        assert sum(n for u, n in journal if t - 60 < u <= t) <= 8, [x for x in journal if t - 60 < x[0] <= t]


def test_budget_insuffisant_bougies_de_la_veille(tmp_path):
    hier = {"bougies": [["2026-11-04 08:00:00", 1, 1.1, 0.9, 1]], "collecte_le": "2026-11-04T08:20:00+00:00", "source": "Twelve Data"}
    (tmp_path / "data" / "cache").mkdir(parents=True)
    (tmp_path / "data" / "cache" / "intraday.json").write_text(json.dumps({"paires": {"EUR/NZD": {"4h": hier, "1j": hier}}}), encoding="utf-8")
    plein = lambda: {"credits": 499}   # noqa: E731
    r = ci.collecter(CONFIG, tmp_path, cle="x", mode="matin", maintenant=datetime(2026, 11, 5, 8, 20, tzinfo=timezone.utc),
                     consommer=lambda n, m: None, etat_quota=plein)
    assert r["dernier_passage"]["requetes"] == 0 and r["dernier_passage"]["sautees_budget"] > 0
    ch = paires.preparer_chandeliers(r["paires"]["EUR/NZD"], "EUR/NZD", False, "2026-11-05")
    assert ch["4h"]["mention"] == "bougies du 04/11" and "30min" not in ch


# ------------------------------------------------------------------ publication
def test_paires_scindees_et_json_valides():
    d = RACINE / "docs" / "data"
    leger = json.loads((d / "paires.json").read_text(encoding="utf-8"))
    assert (d / "paires.json").stat().st_size < 1_500_000
    assert set(leger["groupes"]) == {"suivies", "majeures", "croisees"} and sum(len(v) for v in leger["groupes"].values()) == 36
    for p, f in leger["fiches"].items():
        assert "chandeliers" not in f and f["detail"] == "paires/" + p.replace("/", "-") + ".json"
        det = json.loads((d / f["detail"]).read_text(encoding="utf-8"))
        assert {"chandeliers", "niveaux", "ecart_taux"} <= set(det)
        assert "cours_jour" in f
