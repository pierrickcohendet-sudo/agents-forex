"""Lot V15 : textes du documentaire écrits par une IA (réservation du quota, ordre de secours, récit repris, encadré des
faits, contrôle tolérant, appel de correction, faits pré-mâchés avec leur sens), textes permanents et phrases des cartes de
devises. Tout est simulé : aucun appel réel à un modèle."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from core import documentaire as doc
from core import historique_5ans
from core import llm as llm_mod
from core import noms_moteurs as nm
from core import phrases_devises
from core import redaction_documentaire as rd
from core.llm import BudgetEpuise

RACINE = Path(__file__).resolve().parents[1]
REJEU = Path(__file__).parent / "donnees" / "rejeu_2026-11-21"
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
SAMEDI = datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def sans_cle(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def _h5():
    brut = json.loads((REJEU / "historique_graphiques.json").read_text(encoding="utf-8"))
    return historique_5ans.Historique.depuis_points({k: [tuple(p) for p in v] for k, v in brut.items()})


@pytest.fixture
def racine(tmp_path):
    shutil.copytree(REJEU, tmp_path, dirs_exist_ok=True)
    return tmp_path


def _texte_ok(faits: dict[str, dict], extra: str = "") -> str:
    """Réponse simulée d'un modèle : chaque chapitre reprend ses faits (donc ses nombres) en paragraphes."""
    ch = {}
    for k, v in faits.items():
        f = [x["texte"] for x in v["faits"]] or ["Rien de notable."]
        base = " ".join(f)
        paras = [base] * (2 if k in ("0", "final") else 5)
        paras[0] = paras[0] + extra
        ch[k] = {"paragraphes": paras, "exergue": "Une semaine à lire simplement.", "a_surveiller": ["La prochaine décision de la Fed."]}
    return json.dumps({"chapitres": ch}, ensure_ascii=False)


class Gemini:
    def __init__(self, reponses=None, erreur=None):
        self.reponses, self.erreur, self.prompts = list(reponses or []), erreur, []

    def appeler_llm(self, prompt, systeme=None):
        self.prompts.append(prompt)
        if self.erreur:
            raise self.erreur
        r = self.reponses.pop(0)
        return r(prompt) if callable(r) else r


class Groq:
    nom = "groq/llama-3.3-70b-versatile"

    def __init__(self, reponse=None):
        self.reponse, self.appels = reponse, 0

    def disponible(self):
        return True

    def appeler(self, prompt):
        self.appels += 1
        return self.reponse(prompt) if callable(self.reponse) else self.reponse


def _faits_depuis_prompt(prompt: str) -> dict:
    d = json.loads(prompt.split("FAITS :\n", 1)[1])
    return {k: {"faits": v["faits"]} for k, v in d.items()}


# ------------------------------------------------------------------ réservation du quota
def test_reservation_de_deux_appels_pour_le_documentaire(tmp_path):
    assert llm_mod.categorie_budget("documentaire:g1") == "documentaire"
    assert llm_mod.categorie_budget("documentaire:g2:correction") == "documentaire"
    assert llm_mod.analyse_prioritaire_panne("documentaire:g1")
    reg = llm_mod.RegistreQuotas(tmp_path / "q.json", {"gemini-3.5-flash": 20, "gemini-3.5-flash-lite": 20, "gemini-3.8-flash": 20})
    reg.configurer_budget(CONFIG["llm"]["budget"], complet=True)
    assert list(reg.prevu())[0] == "documentaire" and reg.reserve("documentaire") == 2
    reserves = sum(reg.reserve(c) for c in reg.prevu())
    reg._entree("gemini-3.5-flash")["appels"] = reg.plafond_run() - reserves
    with pytest.raises(BudgetEpuise):
        reg.verifier_budget("etat_du_monde")            # le reste n'entame pas la réserve du documentaire
    reg.verifier_budget("documentaire:g1")               # le documentaire, si
    reg.marquer_fait("documentaire")
    assert reg.reserve("documentaire") == 0             # réserve rendue une fois les tentatives du jour faites


# ------------------------------------------------------------------ faits pré-mâchés
def test_faits_pre_maches_avec_leur_sens():
    assert rd.sens_mouvement("S&P 500", True)[0] == "prise de risque"
    assert rd.sens_mouvement("S&P 500", False)[0] == "peur"
    assert rd.sens_mouvement("VIX", True)[0] == "peur"
    assert rd.sens_mouvement("Rendement 2 ans US (%)", False)[0] == "taux en baisse"
    assert rd.sens_mouvement("Indice dollar large (Fed)", True)[0] == "dollar soutenu"
    ch = {"numero": 1, "etat": {}, "indicateurs": [], "publications": [], "actualite": [], "devises": [], "risques": {},
          "graphiques": [{"cle": "vix", "titre": "VIX", "derniere": ["2026-11-23", 26.62],
                          "variation_semaine": {"valeur": -9.27, "unite": "pts", "du": "2026-11-20", "au": "2026-11-23", "debut": 35.89, "fin": 26.62}},
                         {"cle": "sp500", "titre": "S&P 500", "derniere": ["2026-11-23", 7000.0],
                          "variation_semaine": {"valeur": 4.73, "unite": "%", "du": "2026-11-20", "au": "2026-11-23", "debut": 6683.0, "fin": 7000.0}}]}
    f = rd.faits_chapitre(ch, {}, [])
    assert f[0]["sens"] == "prise de risque"
    assert f[0]["texte"] == ("Le S&P 500 a gagné 4,73 % entre le 20/11 et le 23/11 : les investisseurs reprennent du risque, "
                             "la peur recule (VIX de 35,89 à 26,62).")
    assert all("percentile" not in x["texte"] for x in f)


def test_niveau_sans_le_mot_percentile():
    assert "percentile" not in (rd.niveau_simple(97) or "") and "rare" in rd.niveau_simple(97)
    assert rd.niveau_simple(50) is None
    assert not any("percentile" in t for _, t in nm.DEFINITIONS)


# ------------------------------------------------------------------ contrôle tolérant
FAITS = [{"texte": "Le rendement à 2 ans est passé de 4,88 % le 13/11 à 4,63 % le 20/11.", "sens": "taux en baisse"},
         {"texte": "Le PIB progresse de 4,3 % contre 3,5 % attendu (mercredi 25/11).", "sens": "surprise favorable USD"}]


def test_controle_tolerant_arrondi_difference_format():
    ok = {"paragraphes": ["Le taux à 2 ans est tombé à 4,6 %, soit 25 pb de moins qu'au 13/11. La croissance atteint 4,3 %, "
                          "contre 3,5 % attendu, et l'écart de 0,8 point surprend. " + "Mot " * 130], "exergue": "Le dollar tient.", "a_surveiller": []}
    c = rd.controler(ok, FAITS, ["2026-11-23", "2026-11-24", "2026-11-25"])
    assert c["nombres"] == [] and not c["bloquant"]
    faux = {"paragraphes": ["Le taux a chuté de 12,34 % le 30/04. " + "Mot " * 130], "exergue": "x", "a_surveiller": []}
    c = rd.controler(faux, FAITS, ["2026-11-23"])
    assert "12,34" in c["nombres"] and "30/04" in c["nombres"] and c["bloquant"]
    assert rd.controler({"paragraphes": ["Placez un stop. " + "Mot " * 130], "exergue": "x"}, FAITS)["vocabulaire"]
    assert rd.controler({"paragraphes": ["Court."], "exergue": "x"}, FAITS)["vide"]


def test_appel_de_correction_puis_acceptation():
    faits = {"2": {"nom": "Banques centrales et taux", "faits": FAITS}}
    mauvais = json.dumps({"chapitres": {"2": {"paragraphes": ["Le taux à 2 ans perd 12,34 % au 20/11. " + "Mot " * 130], "exergue": "x"}}})
    bon = json.dumps({"chapitres": {"2": {"paragraphes": ["Le taux à 2 ans recule à 4,63 % au 20/11. " + "Mot " * 130], "exergue": "x"}}})
    g = Gemini([mauvais, bon])
    acceptes, j = rd.rediger_groupe(faits, ["2026-11-20"], g, None)
    assert "2" in acceptes and "corrigé" in acceptes["2"]["redige_par"]
    assert len(g.prompts) == 2 and "ces nombres ne sont pas dans les faits : 12,34" in g.prompts[1]


# ------------------------------------------------------------------ ordre de secours
def test_gemini_hors_quota_puis_groq_chapitre_par_chapitre():
    faits = {"1": {"nom": "Thème dominant", "faits": FAITS}, "2": {"nom": "Banques centrales et taux", "faits": FAITS}}
    gemini = Gemini(erreur=BudgetEpuise("quota atteint"))
    groq = Groq(lambda p: _texte_ok(_faits_depuis_prompt(p)))
    acceptes, j = rd.rediger_groupe(faits, [], gemini, groq)
    assert sorted(acceptes) == ["1", "2"] and groq.appels == 2
    assert all(a["redige_par"].startswith("secours groq") for a in acceptes.values())
    # Gemini répond : Groq n'est pas appelé
    groq2 = Groq(lambda p: _texte_ok(_faits_depuis_prompt(p)))
    acceptes, _ = rd.rediger_groupe(faits, [], Gemini([lambda p: _texte_ok(_faits_depuis_prompt(p))]), groq2)
    assert sorted(acceptes) == ["1", "2"] and groq2.appels == 0


def test_consigne_et_exemple():
    p = rd.prompt_groupe({"2": {"nom": "Banques centrales et taux", "question": "q", "faits": FAITS}})
    assert "un étudiant en gestion" in p and "Le marché a cessé de croire à une Fed plus dure" in p
    assert '"sens": "taux en baisse"' in p and "350 à 700 mots" in p and "« percentile »" in p


# ------------------------------------------------------------------ rédaction du jour : récit repris, encadré des faits
def _doc(racine):
    return doc.calculer(racine, SAMEDI, _h5(), CONFIG)


def test_aucun_texte_d_ia_encadre_des_faits(racine):
    d = doc.rediger(_doc(racine), racine, SAMEDI)
    assert d["redaction"]["ligne"] == "Documentaire : 0 par le modèle, 0 par Groq, 0 récits repris, 10 encadrés de faits"
    ch = d["chapitres"]["2"]
    assert ch["recit"] is None and 5 <= len(ch["faits_semaine"]) <= 8
    assert d["bref_recit"] is None and d["bref_faits_semaine"]


def test_recit_ecrit_par_le_modele_puis_repris_le_lendemain(racine):
    gemini = Gemini([lambda p: _texte_ok(_faits_depuis_prompt(p)), lambda p: _texte_ok(_faits_depuis_prompt(p))])
    d = doc.rediger(_doc(racine), racine, SAMEDI, gemini, None)
    assert d["redaction"]["ligne"].startswith("Documentaire : 10 par le modèle")
    assert d["chapitres"]["3"]["recit"]["a_surveiller"] and len(gemini.prompts) == 2       # deux appels groupés
    # lendemain avant la remise à zéro du quota : pas d'appel, le récit d'hier est repris avec sa mention
    dimanche = datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc)
    g2 = Gemini(erreur=AssertionError("aucun appel attendu"))
    d2 = doc.rediger(doc.calculer(racine, dimanche, _h5(), CONFIG), racine, dimanche, g2, None)
    r = d2["chapitres"]["3"]["recit"]
    assert r["repris"] and r["mention"] == "Récit écrit le 21/11, mis à jour au prochain passage du modèle."
    assert "10 récits repris" in d2["redaction"]["ligne"]


# ------------------------------------------------------------------ textes permanents et phrases
def test_comprendre_six_rubriques():
    for n in range(1, 9):
        c = nm.COMPRENDRE[n]
        assert all(c.get(k) for k in ("une_phrase", "comment", "regarde", "exemple", "effets", "piege")), n
    assert nm.COMPRENDRE[1]["une_phrase"].startswith("L'humeur générale du marché")
    assert "VIX" in nm.GLOSSAIRE and "prime de terme" in nm.GLOSSAIRE and len(nm.GLOSSAIRE) == 12


def test_pourquoi_des_cartes_en_phrases():
    p = phrases_devises.phrases_case("JPY", [{"regle": "Brent, variation sur 4 semaines ≤ −10,00 % → +1 pour JPY", "chiffre": "−25,43 %"}])
    assert p == "Le Brent a perdu 25,43 % en 4 semaines : le Japon, qui importe son énergie, paie moins cher son pétrole, ce qui soutient le yen."
    p = phrases_devises.phrases_case("JPY", [{"regle": "écart de taux 2 ans face aux États-Unis, variation sur 4 semaines ≤ −15 pb → −1", "chiffre": "−17 pb"}])
    assert "s'est réduit de 17 pb en 4 semaines" in p and "lui retire un soutien" in p
    p = phrases_devises.phrases_case("CHF", [{"regle": "positionnement spéculatif COT, lecture contrarienne (extrêmes) ≥ 90 percentile → −1", "chiffre": "96 percentile"}])
    assert "la hausse du franc suisse" in p


def test_site_v15():
    js = (RACINE / "docs" / "site" / "documentaire.js").read_text(encoding="utf-8")
    for x in ("Les faits de la semaine", "Le récit sera écrit au prochain passage du modèle", "À surveiller", "Règle de calcul",
              "En une phrase", "Comment ça marche", "Glossaire", 'class="gl"'):
        assert x in js, x
