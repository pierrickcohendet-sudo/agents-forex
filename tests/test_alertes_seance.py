"""Lot Verrouillage, points 4 et 5 : alertes de fin de run (issue GitHub, bandeau), mises à jour en séance, quota Twelve Data."""
import json
from pathlib import Path
from unittest import mock

import pytest

from core import alertes, notifications, quota_twelve, seance

RACINE = Path(__file__).resolve().parents[1]


def test_evaluer_trois_causes():
    so = {"alertes": [{"nom": "EIA", "texte": "30 j"}], "alertes_indicateurs": [{"libelle": "Rendement 2 ans Japon", "texte": "20 j ouvrés"}]}
    rapport = {"synthese_globale": {"engrenages": {"statut": "indisponible", "quota_atteint": True}}}
    a = alertes.evaluer(["collecte macro (FRED) (HTTPError)"], ["git push impossible"], so, rapport)
    assert [x["type"] for x in a] == ["echec", "echec", "fraicheur", "fraicheur", "quota"]
    assert alertes.evaluer([], [], {}, {"synthese_globale": {"engrenages": {"statut": "ok"}}}) == []


def test_ecrire_bandeau_et_changement(tmp_path):
    d1 = alertes.ecrire(tmp_path, [{"type": "quota", "texte": "x"}])
    assert d1["change"] and d1["depuis"] and d1["actives"]
    d2 = alertes.ecrire(tmp_path, [{"type": "quota", "texte": "x"}])
    assert not d2["change"] and d2["depuis"] == d1["depuis"]          # même liste : pas de nouvelle notification
    d3 = alertes.ecrire(tmp_path, [])
    assert d3["change"] and d3["depuis"] is None and d3["actives"] == []


def _session(ouvertes):
    s = mock.Mock()
    s.get.return_value = mock.Mock(json=mock.Mock(return_value=ouvertes), raise_for_status=mock.Mock())
    s.post.return_value = mock.Mock(raise_for_status=mock.Mock())
    s.patch.return_value = mock.Mock(raise_for_status=mock.Mock())
    return s


def test_issue_ouverte_commentee_fermee(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "jeton-de-test")
    monkeypatch.setenv("GITHUB_REPOSITORY", "moi/depot")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    al = [{"type": "fraicheur", "texte": "EIA : 30 j"}]
    s = _session([])
    assert notifications.notifier_alertes(al, True, "corps", session=s) == "issue ouverte"
    assert s.post.call_args_list[-1].kwargs["json"]["labels"] == ["alerte-pipeline"]
    s = _session([{"number": 12}])
    assert notifications.notifier_alertes(al, True, "corps", session=s) == "issue #12 commentée"
    assert notifications.notifier_alertes(al, False, "corps", session=_session([{"number": 12}])) == "issue inchangée"
    s = _session([{"number": 12}])
    assert notifications.notifier_alertes([], True, "", session=s) == "issue #12 fermée"
    assert s.patch.call_args.kwargs["json"] == {"state": "closed"}


def test_sans_jeton_rien_n_est_envoye_a_github(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    s = _session([])
    assert "non gérée" in notifications.notifier_alertes([{"type": "quota", "texte": "x"}], True, "c", session=s)
    s.get.assert_not_called()


def test_quota_twelve_plafond_et_minute(tmp_path, monkeypatch):
    monkeypatch.setattr(quota_twelve, "PAR_MINUTE", 8)
    t = [0.0]
    pauses = []
    horloge = lambda: t[0]
    def dormir(s):
        pauses.append(s)
        t[0] += s
    for _ in range(8):
        quota_twelve.consommer(1, "technique", tmp_path / "q.json", horloge, dormir)
    assert not pauses
    quota_twelve.consommer(1, "seance", tmp_path / "q.json", horloge, dormir)   # 9e crédit dans la minute : pause
    assert pauses and pauses[0] >= 60
    e = quota_twelve.etat(tmp_path / "q.json")
    assert e["credits"] == 9 and e["par_module"] == {"technique": 8, "seance": 1}
    (tmp_path / "q.json").write_text(json.dumps({"date": e["date"], "credits": 758, "par_module": {}}), encoding="utf-8")
    with pytest.raises(quota_twelve.QuotaTwelveAtteint):
        quota_twelve.consommer(8, "seance", tmp_path / "q.json", horloge, dormir)   # 766 > 800 − 40
    assert "/800" in quota_twelve.ligne_resume(tmp_path / "q.json")


def test_cotations_groupees_huit_credits_heure_et_variation():
    brut = {p: {"symbol": p, "close": "1.1234", "percent_change": "-0.21", "previous_close": "1.1258", "last_quote_at": 1793270000,
                "is_market_open": True} for p in seance.PAIRES}
    brut["USD/CNY"] = {"status": "error", "message": "symbole indisponible"}
    rep = mock.Mock(json=mock.Mock(return_value=brut), raise_for_status=mock.Mock())
    with mock.patch.object(seance.requests, "get", return_value=rep) as get:
        s = seance.cotations("cle")
    assert get.call_count == 1 and get.call_args.kwargs["params"]["symbol"].count(",") == 7
    eur = s["cotations"]["EUR/USD"]
    assert eur["prix"] == 1.1234 and eur["variation_pct"] == -0.21 and eur["heure_utc"].startswith("2026-")
    assert s["cotations"]["USD/CNY"]["prix"] is None and s["cotations"]["USD/CNY"]["raison"] == "symbole indisponible"
    assert quota_twelve.etat()["par_module"] == {"seance": 8}
    assert seance.cotations("")["raison"] == "TWELVE_DATA_API_KEY absente"


def test_orchestrateur_seance_avant_rien_a_completer_et_alertes():
    o = (RACINE / "orchestrateur.py").read_text(encoding="utf-8")
    i_seance, i_rien = o.index('etape("mises à jour en séance"'), o.index("rien à compléter aujourd'hui")
    assert i_seance < i_rien and 'etape("git push (séance)"' in o and o.count('etape("alertes de fin de run"') == 2
    wf = (RACINE / ".github/workflows/rapport.yml").read_text(encoding="utf-8")
    assert "if: failure()" in wf and "issues: write" in wf and "GITHUB_TOKEN: ${{ github.token }}" in wf
    js = (RACINE / "docs/site/accueil.js").read_text(encoding="utf-8")
    assert "data/alertes.json" in js and "ac-bandeau" in js
