"""Lot V5, étape 7 : fiches des paires (paires.json), chandeliers Twelve Data (mocks), synthèse « Mes paires » (modèle
simulé), page Journal (IndexedDB, sans alert()). Sans réseau, sans LLM réel."""
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import yaml

from agents import agent_paires, collecte_intraday
from core import llm as L, paires

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def serie(n=260, v0=150.0):
    d0 = date(2026, 1, 1)
    return [((d0 + timedelta(days=i)).isoformat(), v0 * (1 + 0.001 * ((i % 17) - 8))) for i in range(n)]


DOSSIERS = {"genere_le": "2026-10-23T22:00:00+00:00",
            "vue_ensemble": {"theme": {"titre": "Signaux mixtes", "titre_impose": True, "date_rapport": "2026-10-23",
                                       "direction": {"libelle": "Dollar baissier"}}},
            "matrice_impact": {"lignes": [{"devise": d, "cases": [{"engrenage": n, "valeur": 0, "etat": "neutre"} for n in range(1, 9)]}
                                          for d in ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY")]},
            "engrenages": {"2": {"lignes": [{"devise": "USD", "cellules": {"taux_2a": {"valeur": 4.81, "date": "2026-10-21"}}},
                                            {"devise": "JPY", "cellules": {"taux_2a": {"valeur": 1.95, "date": "2026-09-30"}}}]}}}
REGISTRE = {"cases": {"USD|taux_directeur": {"actuel": {"valeur": "3.88%"}}, "JPY|taux_directeur": {"actuel": {"valeur": "<1.25%"}}}}


def test_fiches_36_paires_mes_paires_et_synthese_python(monkeypatch):
    monkeypatch.setattr(paires, "serie_paire", lambda h5, t, p: serie())
    p = paires.calculer(CONFIG, DOSSIERS, {"devises": [{"devise": "USD", "score_confluence": 68}]}, REGISTRE, None, None, None)
    assert len(p["fiches"]) == 36 and p["mes_paires"][:2] == ["USD/JPY", "EUR/USD"]
    f = p["fiches"]["USD/JPY"]
    assert len(f["synthese_python"]) == 3 and f["synthese_modele"] is None
    assert "≥ +263 pb" in f["synthese_python"][1]                                    # JPY « <1,25 % » lu comme une borne
    assert f["macro"]["portage"]["deux_ans_pb"] == 286
    t = f["technique"]
    assert t["rsi14"] is not None and t["ecart_mm200"] is not None and t["plus_haut_20j"] >= t["plus_bas_20j"]
    assert "raison" in f["chandeliers"]                                              # pas de collecte : raison, jamais d'invention
    assert "chandeliers" not in p["fiches"]["AUD/NZD"]                              # hors « Mes paires » : graphique 1 jour seul
    assert f["graphique_1j"]["annotations"]["periodes"]["90"]


def test_technique_insuffisante_nd():
    assert paires.technique_paire(serie(20))["raison"].startswith("historique quotidien insuffisant")


def test_reperes_intraday_horodates():
    b = [["2026-10-23 10:00:00", 1, 1.2, 0.9, 1.1], ["2026-10-23 10:30:00", 1.1, 1.5, 1.0, 1.4], ["2026-10-23 11:00:00", 1.4, 1.45, 0.8, 1.3]]
    r = paires.reperes_intraday(b, "Twelve Data", "EUR/USD")
    assert [x["type"] for x in r] == ["haut", "dernier"] or [x["type"] for x in r] == ["haut", "bas", "dernier"]
    assert all(x["date"].startswith("2026-10-23 ") and "UTC" in x["detail"] for x in r)


def reponse_ok():
    vals = [{"datetime": f"2026-10-23 1{i % 10}:00:00", "open": "1.1", "high": "1.2", "low": "1.0", "close": "1.15"} for i in range(5)]
    return mock.Mock(status_code=200, json=lambda: {"status": "ok", "values": vals}, raise_for_status=lambda: None)


def test_collecte_intraday_18_requetes_pause_et_cache_du_jour():
    racine = Path(tempfile.mkdtemp())
    with mock.patch.object(collecte_intraday.requests, "get", return_value=reponse_ok()) as get, \
         mock.patch.object(collecte_intraday.time, "sleep") as dort:
        r = collecte_intraday.collecter(CONFIG, racine, cle="cle-test", pause_s=8.0, aujourdhui=date(2026, 10, 24))
    assert get.call_count == 18 and dort.call_count == 17 and dort.call_args.args[0] >= 7.5   # < 8 requêtes par minute
    assert len(r["paires"]["USD/JPY"]["30min"]["bougies"]) == 5
    with mock.patch.object(collecte_intraday.requests, "get") as get2:
        collecte_intraday.collecter(CONFIG, racine, cle="cle-test", aujourdhui=date(2026, 10, 24))
    assert get2.call_count == 0                                                      # cache du jour : aucune requête
    sans = collecte_intraday.collecter(CONFIG, Path(tempfile.mkdtemp()), cle="", aujourdhui=date(2026, 10, 24))
    assert "absente" in sans["raison"]


class Faux(L.FournisseurLLM):
    def __init__(self, rep):
        self.rep, self.etiquettes = rep, []

    def appeler_llm(self, prompt, systeme=None):
        self.etiquettes.append(L._ETIQUETTE_COURANTE[0])
        if isinstance(self.rep, Exception):
            raise self.rep
        return json.dumps(self.rep)


def test_synthese_mes_paires_un_appel_chiffres_controles(monkeypatch):
    monkeypatch.setattr(paires, "serie_paire", lambda h5, t, p: serie())
    p = paires.calculer(CONFIG, DOSSIERS, None, REGISTRE, None, None, None)
    mes = {k: p["fiches"][k] for k in p["mes_paires"]}
    faux = Faux({"paires": {"USD/JPY": "Le portage reste favorable au dollar. La paire montera de 7,77 % demain.",
                            "EUR/USD": "Achetez l'euro."}})
    t = agent_paires.generer(faux, mes)
    assert faux.etiquettes == ["paires:synthese"]
    assert t["USD/JPY"]["texte"] == "Le portage reste favorable au dollar."           # chiffre inventé : phrase retirée
    assert "EUR/USD" not in t                                                         # ordre : retiré, la phrase Python reste
    assert agent_paires.generer(Faux(L.QuotaAtteint("quota")), mes) == {}
    assert agent_paires.generer(None, mes) == {}


def test_page_journal_indexeddb_sans_alert_ni_requete_externe():
    js = (RACINE / "docs/site/journal.js").read_text(encoding="utf-8")
    assert "indexedDB.open" in js and "alert(" not in js and "confirm(" not in js
    assert "http" not in js.replace("http://www.w3.org", "") and "data/paires.json" in js
    assert "image/webp" in js and "1600" in js and "QuotaExceededError" in js
    html = (RACINE / "docs/index.html").read_text(encoding="utf-8")
    assert 'data-onglet="journal"' in html
