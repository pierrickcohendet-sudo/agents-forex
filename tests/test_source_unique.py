"""Lot V5, étape 1 : une seule valeur par indicateur (même valeur, même date, même source) sur toutes les briques,
et la série heurtée rendue visible (« au-delà du seuil mais neutralisé »). Sans réseau, sans LLM."""
import copy
from datetime import date, timedelta

import yaml
from pathlib import Path

from agents import agent_engrenages as ae
from core import dossiers, indicateurs, matrice_impact, vue_ensemble

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def serie(debut, n, f):
    return [[(debut + timedelta(days=i)).isoformat(), f(i)] for i in range(n)]


D0 = date(2026, 4, 1)
HISTO = {"series": {
    "vix": {"source": "FRED (VIXCLS)", "points": serie(D0, 205, lambda i: 18 + (i % 7) * 0.1 + (1.03 if i == 204 else 0))},
    "dollar_large": {"source": "FRED (DTWEXBGS)", "points": serie(D0, 199, lambda i: 120 + i * 0.01)},
    "sp500": {"source": "FRED (SP500)", "points": serie(D0, 204, lambda i: 7000 + i)},
    "wti": {"source": "FRED (DCOILWTICO)", "points": serie(D0, 203, lambda i: 95 if i < 197 else 104 if i < 202 else 107.89)},
    "brent": {"source": "FRED (DCOILBRENTEU)", "points": serie(D0, 203, lambda i: 110)},
    "indice_or": {"source": "FRED (NASDAQQGLDI)", "points": serie(D0, 205, lambda i: 2400 + i)},
    "USD_10a": {"source": "FRED (DGS10)", "points": serie(D0, 204, lambda i: 5.0)},
    "USD_2a": {"source": "FRED (DGS2)", "points": serie(D0, 204, lambda i: 4.8)},
}}


def macro_du_matin():
    """Collecte macro faite plus tôt : VIX d'un jour plus ancien (cas réel du 23/10 : 16,68 contre 19,03)."""
    vix = HISTO["series"]["vix"]["points"]
    return {"series": {"vix": {"valeur": 16.68, "date": vix[-2][0], "source": "FRED"},
                       "sp500": {"valeur": 6000.0, "date": "2026-10-01", "source": "FRED", "variation_pct": 0.5}},
            "graphiques_marche": {"vix": {"dates": [p[0] for p in vix[-30:-1]], "valeurs": [16.68] * 29}}}


def publication(macro):
    """Rapport (signaux des engrenages) et dossiers (instruments de l'engrenage 5) publiés par les vrais modules."""
    cat = ae._Catalogue([])
    donnees = {"macro": {"series": macro["series"]}, "technique": {}}
    sig = ae.signaux(CONFIG, donnees, macro, [], None, {}, cat)
    rapport = {"synthese_globale": {"engrenages": {"engrenages": [
        {"numero": n, "donnees_calculees": s["donnees"]} for n, s in sig.items()]}}}
    dos = {"engrenages": {"5": dossiers.engrenage_5(HISTO, {})}}
    return rapport, dos


def test_sans_source_unique_deux_vix_differents_sont_detectes():
    rapport, dos = publication(macro_du_matin())
    erreurs = indicateurs.incoherences(indicateurs.publiees(rapport, dos))
    assert any(e.startswith("vix") for e in erreurs), erreurs          # le test échoue bien sur le cas du 23/10


def test_source_unique_meme_valeur_meme_date_partout():
    macro = macro_du_matin()
    changes = indicateurs.unifier(macro, HISTO)
    assert any(c.startswith("vix : 16.68") for c in changes)
    rapport, dos = publication(macro)
    valeurs = indicateurs.publiees(rapport, dos)
    assert {v["indicateur"] for v in valeurs} >= {"vix", "sp500", "dollar_large"}
    assert indicateurs.incoherences(valeurs) == []
    vix = [v for v in valeurs if v["indicateur"] == "vix"]
    dernier = HISTO["series"]["vix"]["points"][-1]
    assert len(vix) >= 2 and all(abs(v["valeur"] - dernier[1]) < 1e-9 and v["date"] == dernier[0] for v in vix)
    assert macro["series"]["vix"]["source"] == "FRED (VIXCLS)"


def test_incoherence_meme_date_valeur_differente():
    vals = [{"indicateur": "vix", "date": "2026-10-22", "valeur": 19.03, "module": "a"},
            {"indicateur": "vix", "date": "2026-10-22", "valeur": 16.68, "module": "b"}]
    assert indicateurs.incoherences(vals) and not indicateurs.incoherences(vals[:1])


def test_serie_heurtee_neutralisee_visible_carte_et_matrice():
    pts = HISTO["series"]["wti"]["points"]
    assert indicateurs.serie_heurtee(pts) == "+9,5 % le 15/10"
    carte = vue_ensemble._carte_8(HISTO)
    assert indicateurs.TEXTE_NEUTRALISE in carte[1]
    # matrice : un Brent à +12 % sur 4 semaines aurait déclenché, mais la série est heurtée
    regles = {"matrice_impact": copy.deepcopy(CONFIG["matrice_impact"])}
    engrenages = {"8": {"instruments": [{"id": "brent", "cellule": {"var_4s": 12.0, "source": "FRED", "date": "2026-10-20",
                                                                     "alerte": "série heurtée : +8,7 % le 15/10 en une séance"}}]}}
    m = matrice_impact.calculer(regles, engrenages, None)
    cad = next(c for l in m["lignes"] if l["devise"] == "CAD" for c in l["cases"] if c["engrenage"] == 8)
    assert cad["valeur"] == 0 and cad["etat"] == "neutralise" and indicateurs.TEXTE_NEUTRALISE in cad["raison"]


def test_signal_petrole_heurte_dit_neutralise():
    macro = {"series": {}, "graphiques_marche": {"wti": {"dates": [p[0] for p in HISTO["series"]["wti"]["points"][-20:]],
                                                           "valeurs": [p[1] for p in HISTO["series"]["wti"]["points"][-20:]]}}}
    sig = ae.signaux(CONFIG, {"macro": {"series": {}}, "technique": {}}, macro, [], None, {}, ae._Catalogue([]))
    wti = next(d for d in sig[8]["donnees"] if d.get("indicateur") == "wti")
    assert wti["neutralise"] and indicateurs.TEXTE_NEUTRALISE in wti["texte"]
