"""Introductions des 8 moteurs : bascule sur Groq quand Gemini est hors quota, nouvelle tentative après la remise à zéro du
quota (08:15 UTC, week-end compris) si la version du jour est en rédaction Python, ligne du récapitulatif, mode JSON de Groq
(incident json_validate_failed du 18 au 21/11). Tout est simulé : aucun appel réseau ni modèle."""
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agents import agent_moteurs
from core import dossiers_moteurs as dm
from core.llm import BudgetEpuise, FournisseurGroq
from outils import decider_mode

DONNEES = Path(__file__).parent / "donnees" / "rejeu_2026-11-20"
NUIT = datetime(2026, 11, 20, 0, 11, tzinfo=timezone.utc)      # avant la remise à zéro (comme le run du 21/11 à 00:11)
MATIN = datetime(2026, 11, 20, 8, 20, tzinfo=timezone.utc)     # premier passage après 08:15 UTC


@pytest.fixture(autouse=True)
def sans_cle(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.fixture
def racine(tmp_path):
    for f in DONNEES.rglob("*.gz"):
        dst = tmp_path / f.relative_to(DONNEES).with_suffix("")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(gzip.decompress(f.read_bytes()).decode("utf-8"), encoding="utf-8")
    return tmp_path


class GeminiHorsQuota:
    appels = 0

    def appeler_llm(self, prompt, systeme=None):
        GeminiHorsQuota.appels += 1
        raise BudgetEpuise("indisponible : quota atteint (retentée dès la remise à zéro du quota gratuit)")


class GroqSimule:
    """Secours simulé : répond avec les introductions Python (qui passent le contrôle des nombres)."""
    nom = "groq/openai/gpt-oss-120b"

    def __init__(self, racine):
        self.d = dm.calculer(racine / "docs" / "data", racine / "data" / "cache", None, MATIN)
        self.appels = 0

    def disponible(self):
        return True

    def appeler(self, prompt):
        self.appels += 1
        return json.dumps({k: m["analyse"]["introduction"] for k, m in self.d["moteurs"].items()}, ensure_ascii=False)


def test_quota_epuise_groq_utilise(racine):
    groq = GroqSimule(racine)
    d = agent_moteurs.executer(racine, {}, GeminiHorsQuota(), NUIT, secours=groq)
    r = d["redaction"]
    assert groq.appels == 1 and r["groq"] == [str(n) for n in range(1, 9)] and r["modele"] == [] and r["python"] == []
    assert r["ligne"] == "Moteurs : 0 introduction par le modèle, 8 par Groq, 0 en Python"
    assert "BudgetEpuise" in r["journal"]["erreur"] and r["journal"]["par"].startswith("secours groq")
    publie = json.loads((racine / "docs" / "data" / "moteurs_dossiers.json").read_text(encoding="utf-8"))
    assert publie["moteurs"]["2"]["analyse"]["redige_par"].startswith("secours groq")


def test_doit_rediger_une_tentative_par_periode():
    jour = "2026-11-21"
    t = lambda h: datetime.fromisoformat(f"{jour}T{h}:00+00:00")   # noqa: E731
    assert agent_moteurs.doit_rediger({}, jour, t("00:11"), 0)[0]                                       # première tentative
    nuit = {"date": jour, "tentatives": [f"{jour}T00:11:00+00:00"]}
    assert not agent_moteurs.doit_rediger(nuit, jour, t("03:15"), 0)[0]                                 # même période
    ok, motif = agent_moteurs.doit_rediger(nuit, jour, t("08:20"), 0)
    assert ok and "remise à zéro" in motif                                                               # après 08:15 UTC
    apres = {"date": jour, "tentatives": [f"{jour}T00:11:00+00:00", f"{jour}T08:20:00+00:00"]}
    assert not agent_moteurs.doit_rediger(apres, jour, t("09:15"), 3)[0]                                # une seule fois après
    assert not agent_moteurs.doit_rediger({}, jour, t("08:20"), 8)[0]                                   # 8 textes du jour : rien
    assert agent_moteurs.doit_rediger({"date": jour, "tente": jour}, jour, t("08:20"), 0)[0]           # ancien format du cache
    assert agent_moteurs.doit_rediger({"date": "2026-11-20", "tentatives": ["2026-11-20T08:20:00+00:00"]}, jour, t("00:30"), 0)[0]


def test_passage_horaire_apres_la_remise_a_zero_cree_le_modele_et_groq(racine):
    (racine / "data" / "cache" / "moteurs_intros.json").write_text(json.dumps(
        {"date": "2026-11-20", "tentatives": ["2026-11-20T00:11:00+00:00"], "textes": {}}), encoding="utf-8")
    groq, appels = GroqSimule(racine), []

    def fabrique():
        appels.append(1)
        return GeminiHorsQuota(), groq
    d = agent_moteurs.executer(racine, {}, None, MATIN, fabrique=fabrique)
    assert appels == [1] and groq.appels == 1 and len(d["redaction"]["groq"]) == 8
    cache = json.loads((racine / "data" / "cache" / "moteurs_intros.json").read_text(encoding="utf-8"))
    assert cache["tentatives"] == ["2026-11-20T00:11:00+00:00", "2026-11-20T08:20:00+00:00"]
    # passage suivant : les 8 textes de Groq sont repris, aucun nouvel appel
    d2 = agent_moteurs.executer(racine, {}, None, datetime(2026, 11, 20, 9, 15, tzinfo=timezone.utc), fabrique=fabrique)
    assert appels == [1] and d2["redaction"]["ligne"].endswith("8 par Groq, 0 en Python")


def test_avant_la_remise_a_zero_pas_de_nouvel_appel(racine):
    (racine / "data" / "cache" / "moteurs_intros.json").write_text(json.dumps(
        {"date": "2026-11-20", "tentatives": ["2026-11-20T00:11:00+00:00"], "textes": {}}), encoding="utf-8")
    appels = []
    d = agent_moteurs.executer(racine, {}, None, datetime(2026, 11, 20, 3, 15, tzinfo=timezone.utc), fabrique=lambda: appels.append(1))
    assert appels == [] and d["redaction"]["python"] == [str(n) for n in range(1, 9)]
    assert d["redaction"]["ligne"] == "Moteurs : 0 introduction par le modèle, 0 par Groq, 8 en Python"


def test_bilan_modele_groq_python():
    b = agent_moteurs.bilan({"1": ("t", "Flash 3.5"), "2": ("t", "secours groq/openai/gpt-oss-120b"), "3": ("t", "Flash-Lite 3.5")})
    assert b == {"modele": ["1", "3"], "groq": ["2"], "python": ["4", "5", "6", "7", "8"]}
    assert agent_moteurs.ligne_bilan(b) == "Moteurs : 2 introductions par le modèle, 1 par Groq, 5 en Python"


# ------------------------------------------------------------------ Groq : mode JSON
class Rep:
    def __init__(self, code, corps):
        self.status_code, self.text, self.headers = code, json.dumps(corps), {}
        self._c = corps

    def json(self):
        return self._c


def groq(monkeypatch, modele, reponses):
    monkeypatch.setenv("GROQ_API_KEY", "cle-de-test")
    f = FournisseurGroq(modele=modele, pause_min_s=0, backoff_429_s=0)
    envoyes = []

    def poster(corps):
        envoyes.append(json.loads(json.dumps(corps)))
        return reponses.pop(0)
    monkeypatch.setattr(f, "_poster", poster)
    return f, envoyes


OK = Rep(200, {"choices": [{"message": {"content": '{"1": "texte"}'}}]})
JSON_KO = Rep(400, {"error": {"message": "Failed to validate JSON.", "code": "json_validate_failed", "failed_generation": ""}})


def test_groq_gpt_oss_sans_mode_json_strict(monkeypatch):
    f, envoyes = groq(monkeypatch, "openai/gpt-oss-120b", [OK])
    assert f.appeler_llm("Réponds en JSON : {}") == '{"1": "texte"}'
    assert "response_format" not in envoyes[0] and envoyes[0]["reasoning_effort"] == "low"


def test_groq_json_validate_failed_un_essai_sans_mode_strict(monkeypatch):
    f, envoyes = groq(monkeypatch, "llama-3.3-70b-versatile", [JSON_KO, OK])
    assert f.appeler_llm("Réponds en JSON : {}") == '{"1": "texte"}'
    assert envoyes[0]["response_format"] == {"type": "json_object"} and "response_format" not in envoyes[1]


def test_groq_erreur_avec_sa_raison(monkeypatch):
    f, _ = groq(monkeypatch, "openai/gpt-oss-120b", [Rep(400, {"error": {"code": "model_decommissioned", "message": "retiré"}})])
    with pytest.raises(Exception) as e:
        f.appeler_llm("x")
    assert "model_decommissioned" in str(e.value) and "cle-de-test" not in str(e.value)


def test_cron_du_week_end_regenere_les_moteurs():
    m, raison = decider_mode.decider("schedule", "15 8 * * 0,6", {}, True, [], "1", datetime(2026, 11, 21, 8, 16, tzinfo=timezone.utc))
    assert m == "moteurs" and "remise à zéro" in raison
    assert decider_mode.decider("workflow_dispatch", "", {"declencheur": "externe", "creneau": "moteurs"}, False, [], "1")[0] == "moteurs"
