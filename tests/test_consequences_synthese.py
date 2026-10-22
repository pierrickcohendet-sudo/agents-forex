"""Synthèse hebdomadaire et mensuelle des conséquences (agents/agent_consequences.py), modèle simulé (mocks)."""
import json
import tempfile
from datetime import date
from pathlib import Path

import yaml

from agents import agent_consequences as ac
from core import llm as L

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))

DOSSIERS = {"genere_le": "2026-10-25T07:20:00+00:00", "engrenages": {
    "5": {"consequences": {"moteur": {"libelle": "VIX", "variation_1m": 6.4, "date": "2026-10-23"}, "lignes": [
        {"actif": "USD", "sensibilite": 0.42, "fiabilite": {"part": 68, "n": 25, "borne_wilson_90": 52.3},
         "si_hausse": {"mediane": 0.8}, "si_baisse": {"mediane": -0.3}, "aujourdhui": {"lecture": "Soutien", "n": 25}},
        {"actif": "JPY", "sensibilite": 0.2, "fiabilite": {"part": 55, "n": 22, "borne_wilson_90": 37.1},
         "si_hausse": {"mediane": 0.4}, "si_baisse": {"mediane": -0.1}, "aujourdhui": {"lecture": "Indice faible", "n": 22}}]}},
    "2": {"consequences": {"moteur": {"libelle": "2 ans US", "variation_1m": 3.0}, "lignes": [
        {"actif": "USD", "sensibilite": 0.36, "fiabilite": {"part": 53, "n": 32, "borne_wilson_90": 38.9},
         "aujourdhui": {"lecture": "Neutre"}}]}}}}


class Faux(L.FournisseurLLM):
    def __init__(self, reponse, registre=None):
        self.reponse, self.appels, self.etiquettes, self.registre = reponse, 0, [], registre

    def appeler_llm(self, prompt, systeme=None):
        self.appels += 1
        self.etiquettes.append(L._ETIQUETTE_COURANTE[0])
        if self.registre:
            self.registre.compter("a")
        return json.dumps(self.reponse)


def chaine(utilises, reserve=8, reponse=None):
    registre = L.RegistreQuotas(Path(tempfile.mkdtemp()) / "q.json", {"a": 20})
    for _ in range(utilises):
        registre.compter("a")
    faux = Faux(reponse or {"devises": {"USD": "Le dollar reçoit un soutien du VIX dans 68 % des 25 cas."}}, registre)
    return L.FournisseurChaine([("a", faux)], registre, reserve_engrenages=reserve), faux, registre


def test_faits_et_phrase_python_avec_indice_faible_et_nombre_de_cas():
    usd, jpy = ac.faits_devise(DOSSIERS, "USD"), ac.faits_devise(DOSSIERS, "JPY")
    assert usd["comptes"]["Soutien"] == 1 and usd["comptes"]["Neutre"] == 1 and usd["bilan"] == "soutenue"
    assert "Soutien · 25 cas, borne de Wilson 52,3 %" in ac.phrase_python(usd)
    assert "Indice faible · 22 cas" in ac.phrase_python(jpy)
    assert "aucune ligne" in ac.phrase_python(ac.faits_devise(DOSSIERS, "CNY"))


def test_modele_formule_un_seul_appel_chiffres_et_ordres_controles():
    faux = Faux({"devises": {
        "USD": "Le dollar reçoit un soutien du VIX dans 68 % des 25 cas.",
        "JPY": "Indice faible sur 22 cas. Le yen montera de 4,7 % d'ici Noël.",      # 4,7 absent des faits : retiré
        "EUR": "Achetez l'euro maintenant."}})                                         # ordre : retiré
    s = ac.generer("hebdo", DOSSIERS, faux, jour=date(2026, 10, 25))
    assert faux.appels == 1 and faux.etiquettes == ["consequences:hebdo"]
    assert s["statut"] == "ok" and s["periode"] == "2026-W43"
    assert s["devises"]["USD"]["texte"].startswith("Le dollar reçoit un soutien")
    assert s["devises"]["JPY"]["texte"] == "Indice faible sur 22 cas."
    assert s["devises"]["EUR"]["texte"] is None                                       # le site affiche la phrase Python
    assert all(d["phrase_python"] for d in s["devises"].values())
    assert len(s["controles"]) == 2


def test_quota_a_zero_repli_python_sans_appel():
    llm, faux, _ = chaine(utilises=20)
    s = ac.generer("mensuel", DOSSIERS, llm, jour=date(2026, 11, 1))
    assert faux.appels == 0 and s["statut"] == "indisponible" and s["quota_atteint"]
    assert s["periode"] == "2026-10"
    assert "Indice faible · 22 cas" in s["devises"]["JPY"]["phrase_python"]


def test_reserve_apres_les_engrenages():
    llm, faux, registre = chaine(utilises=13)            # 7 restants : réservés aux engrenages tant qu'ils manquent
    s = ac.generer("hebdo", DOSSIERS, llm, jour=date(2026, 10, 25))
    assert faux.appels == 0 and s["statut"] == "indisponible" and "réservés à la synthèse des engrenages" in s["detail_quota"]
    registre.marquer_engrenages_faits()                  # engrenages faits : la réserve est libérée
    s = ac.generer("hebdo", DOSSIERS, llm, s, jour=date(2026, 10, 25))
    assert faux.appels == 1 and s["statut"] == "ok"


def test_periodes_et_a_faire():
    assert ac.periode("mensuel", date(2026, 11, 1)) == "2026-10"
    assert ac.a_faire({}, "mensuel", date(2026, 11, 1)) and not ac.a_faire({}, "mensuel", date(2026, 11, 8))
    fait = {"hebdo": {"periode": "2026-W43", "statut": "ok"}}
    assert not ac.a_faire(fait, "hebdo", date(2026, 10, 25)) and ac.a_faire(fait, "hebdo", date(2026, 11, 1))
    rate = {"hebdo": {"periode": "2026-W43", "statut": "indisponible", "tentatives": 3}}
    assert not ac.a_faire(rate, "hebdo", date(2026, 10, 25))                          # 3 essais : on s'arrête


def test_executer_ecrit_le_fichier_et_l_archive():
    racine = Path(tempfile.mkdtemp())
    (racine / "docs" / "data").mkdir(parents=True)
    cfg = {**CONFIG, "chemins": {**CONFIG["chemins"], "donnees": "data"}}
    entree = ac.executer("hebdo", racine, cfg, DOSSIERS, None, jour=date(2026, 10, 25))
    assert entree["statut"] == "indisponible" and entree["raison"] == "fournisseur LLM indisponible"
    contenu = json.loads((racine / "docs/data" / ac.FICHIER).read_text(encoding="utf-8"))
    assert contenu["hebdo"]["devises"]["USD"]["phrase_python"]
    assert (racine / "data/hebdo/consequences_hebdo_2026-W43.json").exists()
    assert ac.executer("mensuel", racine, cfg, DOSSIERS, None, jour=date(2026, 10, 25)) is None   # pas le début du mois
