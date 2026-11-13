"""Lot V9.4 : la Synthèse calquée sur les rapports modèles du 09/11 et du 13/11. Rejeu du 13/11 avec données figées et
sources simulées (BLS, ONS, Eurostat, communiqués) ; aucun appel réseau ni modèle."""
import gzip
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents import agent_synthese_v9 as agent
from core import bls, controle_texte as ct, redaction_v94, seuils, synthese_v94 as s4

DONNEES = Path(__file__).parent / "donnees"
MATIN_1311 = datetime(2026, 11, 13, 8, 50, tzinfo=timezone.utc)
INTERDITS = re.compile(r"\b(entrées?|stops?|objectifs?|[Ss]hort)\b|\bLONG\b|\bSHORT\b")


@pytest.fixture(autouse=True)
def sans_cle_secours(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


def rejeu_1311(tmp_path: Path) -> tuple[Path, Path]:
    src = DONNEES / "rejeu_2026-11-13"
    for f in src.rglob("*.gz"):
        rel = f.relative_to(src).with_suffix("")
        dst = tmp_path / ("data" if rel.parts[0] in ("cache", "communiques_v9") else "") / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(gzip.decompress(f.read_bytes()).decode("utf-8"), encoding="utf-8")
    return tmp_path / "docs", tmp_path / "data" / "cache"


@pytest.fixture(scope="module")
def synthese_1311(tmp_path_factory):
    t = tmp_path_factory.mktemp("rejeu1311")
    docs, cache = rejeu_1311(t)
    return s4.calculer(docs, cache, date(2026, 11, 13), MATIN_1311)


def test_rejeu_du_13_11_sections_pays(synthese_1311):
    s = synthese_1311
    ids = [x["id"] for x in s["sections"]]
    for d in ("USD", "JPY", "GBP", "EUR", "CAD"):
        assert f"pays_{d}" in ids, d
    assert {d["devise"] for d in s["faits"]["commune"]["devises"]} == {"AUD", "NZD", "CHF", "CNY"}
    assert ids[:2] == ["exec", "marches"] and ids[-1] == "conclusion" and not s["erreurs"]
    assert [x["numero"] for x in s["sections"]] == list(range(1, len(ids) + 1))


def test_rejeu_du_13_11_profondeur(synthese_1311):
    f = synthese_1311["faits"]
    us = f["pays_USD"]["usd"]
    assert us["obligations"]["pente"] is not None                                     # pente 10 ans − 2 ans
    assert us["prix"]["cpi"]["composantes"] == {"cpi": 0.4, "core": 0.3, "logement": 0.3, "energie": 0.7, "alimentation": 0.5}
    assert "non publiée par le BLS" in us["prix"]["cpi"]["annuel"]["raison"]
    pib = {o["cle"]: o for o in f["pays_GBP"]["officiels"]}
    assert pib["pib_tt"]["valeur"] == 0.7 and pib["pib_tt"]["periode"] == "2026 Q3" and pib["construction_tt"]["valeur"] == -0.7
    assert f["pays_JPY"]["seuil"]["niveau"] == 160 and f["pays_JPY"]["seuil"]["proche"]
    assert f["exec"]["risque_majeur"]["type"] == "seuil" and "160" in f["exec"]["risque_majeur"]["texte"]
    rangs = {l["devise"]: l["rang"] for l in f["classement"]["devises"]}
    assert rangs["GBP"] <= 3 and rangs["USD"] == 1 and "CNY" not in rangs                 # GBP dans le haut, CNY à part
    assert [a["devise"] for a in f["classement"]["a_part"]] == ["CNY"]
    assert len(f["classement"]["divergences"]) == 5
    assert len(f["conclusion"]["indicateurs"]) == 5 and f["calendrier"]["aujourdhui"]
    assert {t["libelle"].split(" (")[0] for t in f["marches"]["tuiles"]} == {"US 2 ans", "US 10 ans", "Brent", "Or au comptant"}


def test_textes_publies_sans_vocabulaire_interdit_et_controles(synthese_1311):
    s = synthese_1311
    tout = " ".join(p for v in s["textes"].values() for p in v)
    assert not INTERDITS.search(tout)
    assert ct.verifier_textes(s["textes"], s["faits"]) == {}
    assert len(tout.split()) >= 1500
    assert all(len(s["textes"][sec["id"]]) >= 1 for sec in s["sections"])


def test_score_d_actualite():
    e = SimpleNamespace(
        archive={"publications": {
            "a": {"date": "2026-11-12", "devise": "GBP", "evenement": "PIB", "evenement_en": "Prelim GDP q/q", "impact": "fort", "reel": "0.7%"},
            "b": {"date": "2026-11-12", "devise": "EUR", "evenement": "Prix de gros", "evenement_en": "German WPI m/m", "impact": "faible", "reel": "0.4%"}}},
        aujourd=date(2026, 11, 13), profil={"devises": []}, pv={}, seuils=[{"paire": "USD/JPY", "proche": True, "texte": "USD/JPY à 0,1 % de 160"}],
        evenements=lambda: [{"date_paris": "2026-11-13", "devise": "EUR", "evenement": "PIB T/T, flash", "evenement_en": "Flash GDP q/q",
                             "impact": "faible", "type": "Chiffre", "heure_paris": "11:00"}],
        tous_articles=[{"titre": "Yen slides toward 160 as Tokyo watches"}])
    sc = s4.score_actualite(e)
    assert sc["GBP"]["score"] == 3 and sc["JPY"]["score"] == 4.5
    assert sc["EUR"]["score"] == 2          # agrégat clé (PIB) attendu aujourd'hui : 2 ; indicateur national faible : 0
    assert sc["CHF"]["score"] == 0


def test_qualificatifs_de_niveau():
    jours = [date(2026, 5, 1).fromordinal(date(2026, 5, 1).toordinal() + i) for i in range(200)]
    pts = [(d.isoformat(), 4.0 + 0.001 * i) for i, d in enumerate(jours) if d.weekday() < 5]
    assert s4.qualificatif(pts) == "plus haut de 6 mois"
    baisse = pts[:-1] + [(pts[-1][0], 3.0)]
    assert s4.qualificatif(baisse) == "plus bas de 6 mois"
    sem = []
    v = 100.0
    for i, d in enumerate(jours):
        if d.weekday() < 5:
            v += 0.3 if i < 180 else -0.01
            sem.append((d.isoformat(), v))
    q = s4.qualificatif(sem)
    assert re.match(r"\d+e semaine de baisse", q), q


def test_seuils_sensibles_sources_et_distances():
    d = seuils.distances({"USD/JPY": 159.91})[0]
    assert d["distance_pct"] == 0.06 and d["distance_pips"] == 9 and d["proche"] and "mof.go.jp" in d["lien"]
    assert seuils.distances({"USD/JPY": 150.0})[0]["proche"] is False
    assert all(s["source"] and s["releve_le"] for s in seuils.SEUILS)


def test_classement_n_d_jamais_compte_pour_zero():
    comps = lambda vals: [{"id": f"c{i}", "valeur": v if v is not None else 0.0, "nd": v is None, "texte": f"c{i}"} for i, v in enumerate(vals)]   # noqa: E731
    base = {"devises": [{"devise": "AAA", "composantes": comps([0.6, 0.6, 0.6, None]), "j5": 0},
                        {"devise": "BBB", "composantes": comps([0.6, None, None, None]), "j5": 0}], "mention": ""}
    e = SimpleNamespace(force={"devises": []}, profil={"devises": []}, communiques={}, pv={}, aujourd=date(2026, 11, 13))
    orig = s4.v9.classement
    try:
        s4.v9.classement = lambda _e: base
        s4.composante_bc = (lambda f: (lambda e_, dev: {"id": "bc", "valeur": 0.0, "nd": True, "texte": "n/d"}))(s4.composante_bc)
        c = s4.classement(e)
    finally:
        s4.v9.classement = orig
        import importlib
        importlib.reload(s4)
    assert c["devises"][0]["devise"] == "AAA" and c["devises"][0]["score"] == 0.6      # moyenne des 3 disponibles, pas 0,45
    assert c["a_part"][0]["devise"] == "BBB" and "il en faut 3" in c["a_part"][0]["raison"]


def test_composantes_prix_bls():
    rep = json.loads((DONNEES / "bls_prix_2026-11.json").read_text(encoding="utf-8"))
    p = bls.calculer_prix(rep)
    assert p["cpi"]["mois"] == "2026-10" and p["cpi"]["composantes"]["energie"] == 0.7
    assert p["ppi"]["composantes"] == {"ppi": 1.3, "ppi_core": 0.7}
    assert p["cpi"]["annuel"]["valeur"] is None and "2025-10" in p["cpi"]["annuel"]["raison"]


def test_controle_vocabulaire_interdit_et_long_francais():
    ok = ct.nombres_autorises({"x": 5.1, "d": "2026-11-12"})
    assert ct.verifier("Les taux longs restent à 5,1 % à long terme au 12/11.", ok) == []
    assert any("vocabulaire interdit" in r for r in ct.verifier("Scénario LONG USD au 12/11.", ok))
    assert any("vocabulaire interdit" in r for r in ct.verifier("Un objectif à 5,1 % au 12/11.", ok))


def test_redaction_groupes_selon_la_taille(synthese_1311):
    groupes = agent.groupes_du_jour(synthese_1311)
    ids = [i for _, g in groupes for i in g]
    assert ids == [x["id"] for x in synthese_1311["sections"]] and all(1 <= len(g) <= 3 for _, g in groupes)
    for g, l in groupes:
        assert len(json.dumps(agent.faits_groupe(synthese_1311, g, l), ensure_ascii=False)) < 16000


def test_brent_jamais_un_fonds_presente_comme_prix_au_baril(synthese_1311):
    f = synthese_1311["faits"]
    b = next(l for l in f["marches"]["marches"] if l["libelle"].startswith("Brent"))
    assert b["statut"] == "confirmé" and "BNO" not in b["source"] and "spot EIA" in b["libelle"]
    assert f["energie"]["brent"]["nature"].startswith("prix spot du Brent publié par l'EIA")
    assert all("jamais un prix au baril" in x["nature"] for x in f["energie"]["fonds"])
    tuile = next(t for t in f["marches"]["tuiles"] if t["libelle"].startswith("Brent"))
    assert "EIA" in tuile["source"]
