"""Lot V12 : l'onglet « 8 engrenages » devient une analyse complète par moteur. Rejeu du 20/11 avec données figées
(dossiers, agenda, banques centrales, cours, titres collectés) ; aucun appel réseau ni modèle."""
import gzip
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents import agent_moteurs
from core import dossiers_moteurs as dm
from core import noms_moteurs as nm

DONNEES = Path(__file__).parent / "donnees" / "rejeu_2026-11-20"
RACINE = Path(__file__).resolve().parents[1]
MATIN = datetime(2026, 11, 20, 7, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def sans_cle_secours(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.fixture(scope="module")
def racine_rejeu(tmp_path_factory):
    t = tmp_path_factory.mktemp("rejeu2011")
    for f in DONNEES.rglob("*.gz"):
        dst = t / f.relative_to(DONNEES).with_suffix("")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(gzip.decompress(f.read_bytes()).decode("utf-8"), encoding="utf-8")
    return t


@pytest.fixture(scope="module")
def d2011(racine_rejeu):
    return dm.calculer(racine_rejeu / "docs" / "data", racine_rejeu / "data" / "cache", date(2026, 11, 20), MATIN)


# ------------------------------------------------------------------ classement des titres et des publications
@pytest.mark.parametrize("titre,attendu", [
    ("Fed's Waller says a December rate cut is on the table", 2),
    ("ECB's Lagarde: inflation risks remain tilted to the upside", 2),
    ("US CPI rises 0.3% m/m, above expectations", 3),
    ("US November Philly Fed 6.3 vs 20.0 expected", 3),
    ("Treasury 10-year auction tails as deficit worries grow", 4),
    ("Moody's keeps US rating at Aa1", 4),
    ("Nasdaq futures slide as VIX jumps above 25", 5),
    ("New sanctions on Russia target oil exports", 6),
    ("CFTC data: speculators boost net yen shorts", 7),
    ("Oil falls as OPEC+ weighs higher output", 8),
    ("Trump threatens new tariffs on Chinese imports", 8),
])
def test_classement_des_titres(titre, attendu):
    assert dm.classer_titre(titre)[0] == attendu
    assert 1 <= len(dm.classer_titre(titre)) <= 2


def test_titre_compte_une_fois_par_jour_et_explique():
    arts = [{"titre": "Fed's Waller says cut possible", "lien": "a"}, {"titre": "FED’S WALLER SAYS CUT POSSIBLE", "lien": "b"},
            {"titre": "Sports results", "lien": "c"}]
    l = dm.titres_classes(arts, "2026-11-20")
    assert len(l) == 1 and l[0]["moteurs"] == [2] and "anticipations de taux" in l[0]["pourquoi"]["2"]


@pytest.mark.parametrize("ev,attendu", [
    ({"evenement": "Discours de Lagarde, présidente de la BCE", "evenement_en": "ECB President Lagarde Speaks", "type": "Discours"}, 2),
    ({"evenement": "Décision de la BoE", "evenement_en": "Official Bank Rate", "type": "Réunion BC"}, 2),
    ({"evenement": "Procès-verbal du FOMC", "evenement_en": "FOMC Meeting Minutes", "type": "Chiffre"}, 2),
    ({"evenement": "IPC A/A", "evenement_en": "CPI y/y", "type": "Chiffre"}, 3),
    ({"evenement": "Emplois non agricoles", "evenement_en": "Non-Farm Employment Change", "type": "Chiffre"}, 3),
    ({"evenement": "PMI manufacturier", "evenement_en": "Manufacturing PMI", "type": "Chiffre"}, 3),
    ({"evenement": "Adjudication du Trésor US : note 2 ans", "evenement_en": "2-y Note Auction", "type": "Adjudication"}, 4),
    ({"evenement": "Stocks de pétrole brut", "evenement_en": "Crude Oil Inventories", "type": "Chiffre"}, 8),
    ({"evenement": "Balance commerciale", "evenement_en": "Trade Balance", "type": "Chiffre"}, 8),
])
def test_classement_des_publications(ev, attendu):
    assert dm.moteur_publication(ev) == attendu


# ------------------------------------------------------------------ rejeu du 20/11
def test_rejeu_moteur_2_discours_de_lagarde_et_macklem(d2011):
    ag = d2011["moteurs"]["2"]["agenda"]
    assert any("Lagarde" in e["evenement"] and e["date"] == "2026-11-20" for e in ag)
    assert any("Macklem" in e["evenement"] and e["date"] == "2026-11-24" for e in ag)
    assert all(e["ce_qui_pourrait_changer"] for e in ag)


def test_rejeu_case_jpy_moteur_2(d2011):
    jpy = next(x for x in d2011["moteurs"]["2"]["devises"] if x["devise"] == "JPY")
    assert jpy["effet"] == "pression" and "−17 pb" in jpy["pourquoi"] and "4 semaines" in jpy["pourquoi"]
    mof = next(r for r in jpy["reactions"] if r["acteur"].startswith("ministère des Finances"))
    assert "intervention" in mof["levier"] and "au-dessus de 160" in mof["declencheur"] and "mof.go.jp" in mof["lien"]
    assert d2011["matrice"]["cases"]["JPY"][1]["effet"] == "pression"
    assert "Portage" in jpy["comment"]


def test_reaction_possible_structuree(d2011):
    for n, m in d2011["moteurs"].items():
        for x in m["devises"]:
            for r in x["reactions"]:
                assert set(r) >= {"acteur", "levier", "declencheur", "date", "source"}, (n, x["devise"], r)
                assert all(r[k] for k in ("acteur", "levier", "declencheur", "date", "source")), (n, x["devise"], r)


def test_non_mesure_a_toujours_sa_raison(d2011):
    for n, m in d2011["moteurs"].items():
        for x in m["devises"]:
            if x["effet"] == "non mesuré":
                assert x["raison_non_mesure"], (n, x["devise"])
        assert [y["devise"] for y in m["manques"]] == [x["devise"] for x in m["devises"] if x["effet"] == "non mesuré"]
    assert any("2 ans britannique" in y["raison"] for y in d2011["manques"]["2"] if y["devise"] == "GBP")


def test_coherence_etat_et_devises_touchees_moteur_8(d2011):
    m8 = d2011["moteurs"]["8"]
    assert m8["etat"]["code"] == "franchi" and m8["touchees"] == 0
    assert "aucune règle de la matrice" in m8["etat"]["incoherence"]
    for m in d2011["moteurs"].values():   # jamais d'incohérence silencieuse
        if m["etat"]["code"] == "franchi" and m["touchees"] == 0:
            assert m["etat"].get("incoherence")


def test_secours_de_redaction_sans_engrenage_seul(d2011):
    f = agent_moteurs.faits(d2011)
    for n, m in d2011["moteurs"].items():
        intro = m["analyse"]["introduction"]
        assert not re.search(r"\bengrenages?\s*\d", intro, re.I) and nm.nom(int(n)).lower() in intro.lower()
        assert len(intro.split(". ")) >= 2                          # phrases complètes
    assert agent_moteurs.controler({n: m["analyse"]["introduction"] for n, m in d2011["moteurs"].items()}, f) == {}
    assert "« engrenage N »" in " ".join(agent_moteurs.controler({"2": "L'engrenage 2 reste près du seuil au 18/11."}, f)["2"])


def test_redaction_par_le_modele_controlee(racine_rejeu, d2011):
    f = agent_moteurs.faits(d2011)
    bon = {k: d2011["moteurs"][k]["analyse"]["introduction"] for k in d2011["moteurs"]}
    bon["3"] = "Chiffres économiques : la surprise USD sur 30 jours est à +0,87 au 20/11, ce qui soutient USD."
    faux = dict(bon, **{"5": "Liens entre marchés : le VIX bondit à 99,9 au 20/11."})

    class Faux:
        def __init__(self, r): self.r = r
        def appeler_llm(self, p): return json.dumps(self.r, ensure_ascii=False)
    ok, journal = agent_moteurs.rediger(d2011, Faux(faux))
    assert "5" in journal["rejetes"] and "5" not in ok and ok["3"][0].startswith("Chiffres économiques")


def test_ecran_et_adresses():
    s = (RACINE / "docs" / "site" / "engrenages_tableau.js").read_text(encoding="utf-8")   # lot V13 : vue tableau
    for x in ("g=([1-8])(?:\\/(\\w+))?", "([A-Z]{3})-([1-8])", "Outils et historique", "Actualités et agenda", "Devises touchées"):
        assert x in s, x
    v = (RACINE / "outils" / "verifier_adresses.mjs").read_text(encoding="utf-8")
    assert "engrenages/g=2/devises" in v and "engrenages/USD-2" in v
