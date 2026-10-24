"""Lot V5, étapes 4 et 5 : « Et si », décomposition des 36 paires, jours similaires, ce que dit l'histoire. Sans réseau."""
from datetime import date, timedelta
from pathlib import Path

import yaml

from core import matrice_impact as mi, outils

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def test_36_paires_convention_de_marche():
    p = outils.paires()
    assert len(p) == 36 and len(set(p)) == 36
    for x in ("EUR/USD", "USD/JPY", "GBP/USD", "AUD/USD", "USD/CAD", "USD/CHF", "AUD/NZD", "EUR/GBP"):
        assert x in p


def matrice(sig=None):
    m = mi.matrice(CONFIG["matrice_impact"], sig or {"vix": (19.0, "FRED", "2026-10-22", None)}, {}, False, None)
    m.update({"signaux_valeurs": sig or {"vix": (19.0, "FRED", "2026-10-22", None)}, "couverture": {}, "theme_fort": False})
    return m


def test_decomposer_base_moins_cotation_et_cases_incompletes():
    sig = {"vix": (31.0, "FRED", "2026-10-22", None), "ecart_2a_us_var_4s": {"JPY": (-35.0, "MoF", "2026-10-22")}}
    d = outils.decomposer(matrice(sig))
    aj = d["AUD/JPY"]
    c5 = next(c for c in aj["contributions"] if c["engrenage"] == 5)
    assert (c5["base"], c5["cotation"], c5["contribution"]) == (-2, 2, -4)          # VIX ≥ 30 : AUD −2, JPY +2
    assert aj["solde"] == sum(c["contribution"] for c in aj["contributions"])
    assert any("AUD n/d" in x for x in aj["incompletes"])                           # écart 2 ans AUD absent
    assert "case(s) incomplète(s)" in aj["texte"]


def test_et_si_bilan_avant_apres_par_seuil_de_config():
    sc = {s["id"]: s for s in outils.scenarios(CONFIG, matrice())}
    vix25 = sc["vix->=25"]
    aud = next(b for b in vix25["bilans"] if b["devise"] == "AUD")
    assert aud["apres"] - aud["avant"] == -1 and "AUD −1" in vix25["effets"]
    assert all(b["devise"] in mi.DEVISES for b in vix25["bilans"]) and len(vix25["bilans"]) == 9
    assert not any(s["id"].startswith("theme_") for s in sc.values())              # règles du thème : jamais en scénario


class FauxH5:
    def __init__(self):
        self.series = {}

    def serie(self, nom):
        return self.series.get(nom, [])

    def source(self, nom):
        return "FRED"


def test_jours_similaires_espaces_et_indice_faible(monkeypatch):
    d0 = date(2021, 1, 4)
    jours = [(d0 + timedelta(days=i)).isoformat() for i in range(1500)]
    # profil identique à aujourd'hui tous les 40 jours, différent ailleurs
    def serie(v_proche, v_loin):
        return {"points": [(j, v_proche if i % 40 == 0 else v_loin) for i, j in enumerate(jours)], "libelle": "x", "unite": "pb", "source": "FRED"}
    monkeypatch.setattr(outils, "series_mesures", lambda h5, t: {2: serie(1.0, 30.0), 5: serie(19.0, 40.0), 8: serie(0.3, 25.0)})
    monkeypatch.setattr(outils, "_cours_paire", lambda h5, t, p: [(j, 1.0 + i * 0.001) for i, j in enumerate(jours)])
    thermos = [{"numero": 2, "seuil_bas": -10, "seuil_haut": 10, "valeur": 1.0}, {"numero": 5, "seuil_bas": 14, "seuil_haut": 25, "valeur": 19.0},
               {"numero": 8, "seuil_bas": -10, "seuil_haut": 10, "valeur": 0.3}]
    r = outils.jours_similaires(FauxH5(), None, thermos, "2026-10-23")
    assert r["n"] == 5 and all(s["distance"] == 0 for s in r["seances"])
    ds = sorted(date.fromisoformat(s["date"]) for s in r["seances"])
    assert all((b - a).days >= 15 for a, b in zip(ds, ds[1:]))
    assert r["lecture"].startswith("indice faible · 5 cas") and "probabilité" in r["lecture"]
    assert r["medianes"]["EUR/USD"] is not None
    assert "Engrenages 1, 3 et 6 exclus" in r["methode"]


def test_jours_similaires_sans_historique_nd(monkeypatch):
    monkeypatch.setattr(outils, "series_mesures", lambda h5, t: {})
    r = outils.jours_similaires(FauxH5(), None, [], "2026-10-23")
    assert r["raison"].startswith("moins de 3 engrenages")


def test_histoire_regles_wilson_et_echantillon():
    def couple(n, wilson):
        return {"scenarios": {"hausse|1": {"mois": {"n": n, "mediane": 0.4, "borne_wilson_90": wilson, "insuffisant": n < 20,
                                                    "lecture_classique": {"conforme": True}}}}}
    impact = {"indicateurs": [{"id": "vix", "libelle": "VIX"}],
              "couples": {"vix|USD": couple(33, 52.4), "vix|EUR": couple(33, 37.6), "vix|JPY": couple(11, 60.0)}}
    h = {l["devise"]: l["lecture"] for l in outils._histoire(impact, "vix")["lignes"]}
    assert h["USD"].startswith("confirmé · 33 cas") and h["EUR"] == "indice faible · 33 cas"
    assert h["JPY"] == "échantillon insuffisant · 11 cas" and h["CNY"] == "n/d"
    assert outils._histoire(impact, None)["raison"]


def test_onglet_outils_branche_sur_outils_json():
    html = (RACINE / "docs/index.html").read_text(encoding="utf-8")
    app = (RACINE / "docs/site/app.js").read_text(encoding="utf-8")
    js = (RACINE / "docs/site/outils.js").read_text(encoding="utf-8")
    assert 'data-onglet="outils"' in html and "pageOutils" in app
    assert "data/outils.json" in js and "fetch(" not in js
