"""Palier 10 : repères annotés des graphiques (core/annotations.py) et impression / PDF du site. Sans réseau."""
import re
from datetime import date, timedelta
from pathlib import Path

from core import annotations as an, cours

RACINE = Path(__file__).resolve().parents[1]


def serie(n=200, debut=date(2026, 3, 1), f=lambda i: 1.10 + 0.0005 * i):
    return [[(debut + timedelta(days=i)).isoformat(), f(i)] for i in range(n)]


REGISTRE = {"cases": {
    "USD|cpi": {"actuel": {"date_pub": "2026-09-10", "valeur": "3.7%", "source": "ForexFactory", "origine": None},
                "historique": [{"date_pub": "2026-08-12", "valeur": "3.4%"}]},
    "USD|emploi": {"actuel": {"date_pub": "2026-09-05", "valeur": "29K", "source": "ForexFactory"}},
    "USD|taux_directeur": {"actuel": {"date_pub": "2026-09-01", "valeur": "3.88%", "origine": "taux_config"}},   # repli : pas un évènement
    "EUR|taux_directeur": {"actuel": {"date_pub": "2026-09-11", "valeur": "2.65%", "source": "ForexFactory"}},
    "EUR|emploi": {"actuel": {"date_pub": "2026-09-12", "valeur": "1%"}},                                      # NFP : USD seulement
}}


def test_haut_bas_dernier_et_evenement_sources_et_dates():
    pts = serie(f=lambda i: 1.10 + (0.02 if i == 150 else 0) - (0.03 if i == 170 else 0))
    r = an.reperes(pts, None, "Twelve Data", an.evenements_majeurs(REGISTRE, "EUR"), "EUR")["90"]
    types = [x["type"] for x in r]
    assert sorted(types) == ["bas", "dernier", "evenement", "haut"]
    haut = next(x for x in r if x["type"] == "haut")
    assert haut["date"] == pts[150][0] and "1,1200" in haut["texte"] and haut["source"] == "Twelve Data"
    ev = next(x for x in r if x["type"] == "evenement")
    assert ev["texte"] == "BCE 2,65%" and ev["date_evenement"] == "2026-09-11" and "ForexFactory" in ev["source"]
    assert all(x["detail"] and x["date"] for x in r)
    assert 2 <= len(r) <= 4


def test_pas_d_invention_sans_donnees_ni_evenement_de_repli():
    assert an.reperes([], None, "x") == {k: [] for k in an.PERIODES}
    assert an.reperes([["2026-10-01", 1.0]], None, "x")["30"] == []
    usd = an.evenements_majeurs(REGISTRE, "USD")
    assert [e["texte"] for e in usd] == ["CPI 3,4%", "NFP 29K", "CPI 3,7%"]      # taux de repli (origine) ignoré
    assert [e["texte"] for e in an.evenements_majeurs(REGISTRE, "EUR")] == ["BCE 2,65%"]   # pas de NFP hors USD
    assert an.evenements_majeurs(REGISTRE, "Brent") == []


def test_haut_sur_le_dernier_point_non_duplique():
    r = an.reperes(serie(), "%", "FRED")["30"]          # série croissante : le dernier point est le plus haut
    assert [x["type"] for x in r] == ["bas", "dernier"]
    assert "plus haut de la période" in r[-1]["detail"]


def test_graphique_des_dossiers_et_cours_annotes():
    g = {"type": "serie", "titre": "t", "unite": "pb", "source": "FRED", "courbes": [{"nom": "EUR", "points": serie(n=60)}]}
    an.annoter_graphique(g, REGISTRE)
    assert g["annotations"]["courbe"] == "EUR" and g["annotations"]["periodes"]["90"]
    assert an.annoter_graphique({"type": "barres", "barres": []}) == {"type": "barres", "barres": []}


def test_site_impression_a4_textures_et_bouton():
    css = (RACINE / "docs/site/cabinet.css").read_text(encoding="utf-8")
    assert re.search(r"@page\s*\{\s*size:\s*A4", css)
    impression = css[css.index("@media print"):]
    for regle in (".onglets", ".bouton", "break-after: page", "apercu-impression"):
        assert regle in impression, regle
    assert "url(#imp-up)" in css and "url(#imp-dn)" in css               # textures noir et blanc de la roue
    html = (RACINE / "docs/index.html").read_text(encoding="utf-8")
    assert 'id="bouton-imprimer"' in html and "Imprimer / PDF" in html
    js = (RACINE / "docs/site/impression.js").read_text(encoding="utf-8")
    assert "Aide à la décision, pas un conseil" in js and "fetch(" not in js and "http" not in js.replace("http://www.w3.org", "")
