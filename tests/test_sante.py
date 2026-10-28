"""Lot V5, étape 7-bis : registre des sources, fraîcheur, certificats, résumé du run. Sans réseau, sans LLM."""
import json
from datetime import date
from pathlib import Path

import yaml

import orchestrateur
from core import sources

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
MERCREDI = date(2026, 10, 28)


def test_fraicheur_vert_orange_rouge_et_jours_ouvres():
    assert sources.jours_ouvres(date(2026, 10, 23), date(2026, 10, 26)) == 1          # vendredi -> lundi
    assert sources.fraicheur("2026-10-27", "quotidienne", 2, MERCREDI)["etat"] == "vert"
    assert sources.fraicheur("2026-10-20", "quotidienne", 0, MERCREDI)["etat"] == "rouge"   # 6 j ouvrés > 4 × 1
    assert sources.fraicheur("2026-10-26", "quotidienne", 0, MERCREDI)["etat"] == "vert"    # 2 j ouvrés = 2 × 1
    assert sources.fraicheur("2026-10-23", "quotidienne", 0, MERCREDI)["etat"] == "orange"  # 3 j ouvrés
    assert sources.fraicheur("2026-10-01", "hebdomadaire", 3, MERCREDI)["etat"] == "orange" # 27 j > 2 × 10
    assert sources.fraicheur(None, "mensuelle", 45, MERCREDI)["etat"] == "rouge"


def test_registre_statuts_extractions_retirees_et_a_remplacer(tmp_path):
    (tmp_path / "collecte_flux.json").write_text(json.dumps({"date": "2026-10-28", "donnees": {
        "cot": {"CAD": {"date": "2026-10-20"}, "EUR": {"date": "2026-10-13"}}}}), encoding="utf-8")
    hist = {"series": {"vix": {"source": "FRED (VIXCLS)", "points": [["2026-10-26", 18.0], ["2026-10-27", 17.52]]},
                       "dollar_large": {"source": "FRED (DTWEXBGS, indice dollar large de la Fed)", "points": [["2026-10-02", 120.0]]}}}
    d = sources.calculer(CONFIG, hist, tmp_path, {"controle_qualite": {"anomalies": []}}, MERCREDI)
    par = {s["id"]: s for s in d["sources"]}
    assert par["cftc"]["derniere_donnee"] == "2026-10-20" and par["cftc"]["fraicheur"]["etat"] == "vert"
    assert par["ff_mois"]["a_remplacer"] and par["ff_mois"]["statut"] == "extraction" and par["ff_mois"]["remplacement"]
    assert {s["id"] for s in d["retirees"]} == {"tradingview", "finviz", "financialjuice", "financialsource"}
    assert d["comptes"]["extraction"] == 1 and d["a_remplacer"] == 1
    vix = d["certificats"]["vix"]
    assert vix["valeur"] == 17.52 and vix["controle"] == "✓" and vix["statut"] == "Officielle" and vix["fraicheur"]["etat"] == "vert"
    dl = d["certificats"]["dollar_large"]                       # motif le plus précis : Fed H.10 (hebdomadaire), pas FRED quotidien
    assert dl["fraicheur"]["normal_jours"] == 10 and dl["fraicheur"]["etat"] == "orange"
    assert d["certificats"]["wti"]["raison"]                    # série absente : raison, jamais de valeur inventée
    assert [n["niveau"] for n in d["niveaux"]] == ["Mesuré", "Historique", "Ma lecture", "Jamais"]


def test_controle_croise_signale_un_indicateur_publie_deux_fois(tmp_path):
    hist = {"series": {"vix": {"source": "FRED (VIXCLS)", "points": [["2026-10-27", 17.52]]}}}
    rapport = {"controle_qualite": {"anomalies": ["indicateur publié deux fois : vix 19,03 / 16,68 (2026-10-22)"]}}
    d = sources.calculer(CONFIG, hist, tmp_path, rapport, MERCREDI)
    assert d["certificats"]["vix"]["controle"] == "⚠"


def test_extractions_html_desactivees_et_rss_officiels_ajoutes():
    sites = CONFIG["scraping"]["sites"]
    assert sites["forexfactory"]["actif"] and sites["forexfactory"]["type"] == "json"
    for s in ("tradingview", "finviz", "financialjuice", "financialsource", "mataf"):
        assert sites[s]["actif"] is False, s
    assert {"fed_communiques", "bce_communiques", "boe_actualites", "boc_communiques"} <= set(CONFIG["rss"])


def test_resume_du_run_noms_non_traduits_et_fraicheur(tmp_path):
    docs = tmp_path / "docs" / "data"
    docs.mkdir(parents=True)
    (docs / "agenda.json").write_text(json.dumps({"n_evenements": 3, "consensus": {"etat": "fonctionne"},
                                                  "non_traduits": ["Zorglub Index"]}), encoding="utf-8")
    (docs / "sources.json").write_text(json.dumps({"sources": [{"nom": "EIA", "fraicheur": {"etat": "orange", "texte": "30 j"}}]}),
                                       encoding="utf-8")
    lignes = orchestrateur.lignes_resume_donnees(tmp_path, {"publication_web": {"dossier_docs": "docs"}})
    assert "Zorglub Index" in lignes[0] and "EIA (30 j)" in lignes[1]


def test_page_sante_et_certificat_partage_branches():
    app = (RACINE / "docs/site/app.js").read_text(encoding="utf-8")
    assert 'sante: { titre: "Santé des données", module: "./sante.js"' in app and "initialiserCertificats();" in app
    commun = (RACINE / "docs/site/commun.js").read_text(encoding="utf-8")
    assert "export function certifier" in commun
    for page in ("cockpit", "dossiers", "tableau", "agenda", "journal", "sante"):
        assert "certifier(" in (RACINE / f"docs/site/{page}.js").read_text(encoding="utf-8"), page
