"""Lot V13 : documentaire hebdomadaire des 8 moteurs (core/documentaire.py), défauts D1 à D4 (core/surprises.py,
core/agenda.py, core/complements.py) et rejeu de la semaine du 16 au 20/11/2026 vue le samedi 21/11.
Tout est simulé : aucun appel réseau ni modèle (le modèle et Groq sont des doublures)."""
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from core import agenda as ag_mod
from core import complements, documentaire as doc, historique_5ans, surprises
from core.llm import BudgetEpuise

RACINE = Path(__file__).resolve().parents[1]
REJEU = Path(__file__).parent / "donnees" / "rejeu_2026-11-21"
SAMEDI = datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)        # après la remise à zéro du quota (08:15 UTC)
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


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


@pytest.fixture(scope="module")
def semaine():
    """Documentaire calculé une fois sur le rejeu (lecture seule dans les tests qui l'utilisent)."""
    import tempfile
    t = Path(tempfile.mkdtemp())
    shutil.copytree(REJEU, t, dirs_exist_ok=True)
    return doc.calculer(t, SAMEDI, _h5(), CONFIG)


def _sem(d):
    return {"du": d["du"], "au": d["au"], "jours": d["jours_couverts"], "statut": d["statut"], "fin_donnees": d["fin_donnees"]}


# ------------------------------------------------------------------ variation de la semaine
def test_variation_vendredi_contre_vendredi():
    pts = [["2026-11-12", 4.90], ["2026-11-13", 4.88], ["2026-11-16", 4.80], ["2026-11-19", 4.70], ["2026-11-20", 4.63]]
    v = doc.variation_semaine(pts, "2026-11-16", "2026-11-20", "pb")
    assert v["valeur"] == -25 and v["unite"] == "pb" and v["du"] == "2026-11-13" and v["au"] == "2026-11-20"
    assert v["texte"].startswith("−25 pb sur la semaine") and "ven. 13/11" in v["texte"]


def test_variation_jour_ferie_prend_la_seance_precedente():
    # vendredi 13/11 férié (pas de point) : le jeudi 12/11 sert de référence ; vendredi 20/11 férié : le jeudi 19/11
    pts = [["2026-11-12", 100.0], ["2026-11-16", 101.0], ["2026-11-19", 102.0]]
    v = doc.variation_semaine(pts, "2026-11-16", "2026-11-20", "%")
    assert v["du"] == "2026-11-12" and v["au"] == "2026-11-19" and v["valeur"] == 2.0


def test_variation_serie_courte_nd_avec_raison():
    v = doc.variation_semaine([["2026-11-17", 1.0], ["2026-11-20", 2.0]], "2026-11-16", "2026-11-20", "%")
    assert v["valeur"] is None and "série trop courte" in v["raison"]
    v = doc.variation_semaine([["2026-11-05", 1.0], ["2026-11-10", 2.0]], "2026-11-16", "2026-11-20", "%")
    assert v["valeur"] is None and "pas de donnée cette semaine" in v["raison"]
    assert doc.variation_semaine([], "2026-11-16", "2026-11-20", "%")["raison"] == "aucune donnée dans la semaine"


def test_variation_tuile_deja_en_pb_jamais_multipliee():
    # une tuile déjà exprimée en points de base varie en différence simple (pas de −2 500 pb)
    t = {"unite": "pb", "variation": {"unite": "pb"}}
    assert doc._mesure_tuile(t) == "abs:pb"
    v = doc.variation_semaine([["2026-11-13", 40.0], ["2026-11-20", 15.0]], "2026-11-16", "2026-11-20", doc._mesure_tuile(t))
    assert v["valeur"] == -25 and v["unite"] == "pb"


# ------------------------------------------------------------------ solde des surprises
def test_solde_sens_favorable_et_ecart_aberrant(caplog):
    pubs = [
        {"devise": "AUD", "evenement": "Variation de l'emploi", "date": "2026-11-19", "z": -1.15, "favorable": False},
        {"devise": "AUD", "evenement": "Taux de chômage", "date": "2026-11-19", "z": 2.0, "favorable": False},   # chômage plus haut : négatif
        {"devise": "USD", "evenement": "Inscriptions au chômage", "date": "2026-11-19", "z": 50.0, "favorable": True},
        {"devise": "CAD", "evenement": "Ventes au détail", "date": "2026-11-20", "z": None, "favorable": None},
    ]
    s = doc.solde_surprises(pubs)
    par = {b["devise"]: b for b in s["barres"]}
    assert par["AUD"]["solde"] == -3.15 and par["AUD"]["n"] == 2
    assert par["USD"]["solde"] == 1.0                     # écart aberrant : compte pour 1
    assert "CAD" not in par                               # sans z : hors solde
    assert len(s["aberrants"]) == 1 and "compté pour 1" in s["aberrants"][0]
    assert "aberrante" in caplog.text


# ------------------------------------------------------------------ D1, D2 : écart habituel historique
def _archive(lignes):
    return {"publications": {f"{d}|{dev}|{en}": {"date": d, "devise": dev, "evenement_en": en, "reel": r, "consensus": c}
                             for d, dev, en, r, c in lignes}}


def test_d1_inscriptions_chomage_en_milliers():
    arch = _archive([("2026-10-08", "USD", "Unemployment Claims", "219K", "223K"), ("2026-10-15", "USD", "Unemployment Claims", "226K", "221K"),
                     ("2026-10-22", "USD", "Unemployment Claims", "215K", "220K"), ("2026-11-19", "USD", "Unemployment Claims", "203K", "198K")])
    idx = surprises.ecarts_archives(arch)
    z = surprises.z_publication("203K", "198K", "USD", "Unemployment Claims", idx, "2026-11-19")
    assert z["z"] is not None and abs(z["z"]) < 5      # avant : 50
    assert "3 publications précédentes" in z["base"]   # la publication notée est exclue de son échelle


def test_d2_philly_par_sa_famille_et_raison_si_trop_court():
    arch = _archive([("2026-10-16", "USD", "Empire State Manufacturing Index", "10.7", "1.0"),
                     ("2026-10-17", "USD", "Philly Fed Manufacturing Index", "-12.8", "1.4"),
                     ("2026-11-20", "USD", "Philly Fed Manufacturing Index", "6.3", "20.6")])
    idx = surprises.ecarts_archives(arch)
    z = surprises.z_publication("6.3", "20.6", "USD", "Philly Fed Manufacturing Index", idx, "2026-11-20")
    assert z["z"] is not None and z["z"] < 0 and "famille" in z["base"]
    rien = surprises.z_publication("51.0", "50.4", "USD", "Prelim UoM Consumer Sentiment", surprises.ecarts_archives({}), "2026-11-14")
    assert rien["z"] is None and "historique trop court" in rien["raison"]


def test_d1_agenda_ecart_utilise_l_echelle_historique():
    arch = _archive([("2026-10-08", "USD", "Unemployment Claims", "219K", "223K"), ("2026-10-15", "USD", "Unemployment Claims", "226K", "221K"),
                     ("2026-10-22", "USD", "Unemployment Claims", "215K", "220K")])
    e = ag_mod.ecart("203K", "198K", None, {}, "Emploi", surprises.ecarts_archives(arch), "USD", "Unemployment Claims", "2026-11-19")
    assert e["z"] is not None and abs(e["z"]) < 5 and e["base_z"]


def test_poids_solde():
    assert surprises.poids_solde(-1.5) == (1.5, False)
    assert surprises.poids_solde(50) == (1.0, True)
    assert surprises.poids_solde(None) == (None, False)


# ------------------------------------------------------------------ D3, D4 : réactions de séance en retard
def test_d3_d4_reaction_en_retard_nd_avec_raison():
    jours = ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17"]
    hist = {"series": {"brent": {"source": "FRED", "points": [[j, 80 + i] for i, j in enumerate(jours)]},
                       "indice_or": {"source": "FRED", "points": [[j, 2000 + i] for i, j in enumerate(jours + ["2026-11-19", "2026-11-20"])]},
                       "FX_JPY": {"source": "FRED", "points": [[j, 150 + i] for i, j in enumerate(jours)]},
                       "FX_CHF": {"source": "FRED", "points": [[j, 0.8] for j in jours]}}}
    e = {"graphiques": [{"type": "serie"}], "tuiles": []}
    complements.complements_6(e, hist, aujourd=date(2026, 11, 21))
    t = {x["libelle"]: x for x in e["tuiles"]}
    brent = t["Réaction du Brent"]
    assert brent.get("valeur") is None and "en retard depuis le 17/11" in (brent.get("raison") or "")
    assert t["Réaction de l'or (proxy)"].get("valeur") is not None          # série à jour : réaction calculée
    assert "en retard" in (t["Réaction USD/JPY"].get("raison") or "")


# ------------------------------------------------------------------ semaine présentée
def test_bornes_semaine_samedi_et_mercredi():
    b = doc.bornes_semaine(SAMEDI)
    assert (b["id"], b["du"], b["au"], b["statut"], b["suivante_du"]) == ("2026-S47", "2026-11-16", "2026-11-20", "complète", "2026-11-23")
    assert len(b["jours"]) == 5
    m = doc.bornes_semaine(datetime(2026, 11, 18, 12, tzinfo=timezone.utc))
    assert m["statut"] == "en cours" and m["fin_donnees"] == "2026-11-18" and len(m["jours"]) == 3


def test_jours_feries_thanksgiving():
    assert "Thanksgiving" in doc.jours_feries(2026)["2026-11-26"][0]


# ------------------------------------------------------------------ rejeu du 16 au 20/11
def test_rejeu_moteur_3_publications_et_surprises(semaine):
    c3 = semaine["chapitres"]["3"]
    # 17 publications moyennes et fortes, + 3 relevées par le site au lot V14 (ventes au détail CAD et sous-jacentes,
    # IPC sous-jacent national JPY ; le besoin de financement public GBP va au moteur 4)
    assert len(c3["publications"]) == 20 and all(p["moteur"] == 3 for p in c3["publications"])
    assert sum(1 for p in c3["publications"] if p.get("impact_releve")) == 3
    aud = next(p for p in c3["publications"] if p["devise"] == "AUD" and p["evenement_en"] == "Employment Change")
    assert (aud["reel"], aud["consensus"], aud["favorable"]) == ("-43.5K", "25.5K", False)
    philly = next(p for p in c3["publications"] if "Philly" in p["evenement_en"])
    assert (philly["reel"], philly["consensus"]) == ("6.3", "20.6") and philly["z"] is not None and philly["z"] < 0
    assert c3["surprises"]["barres"] and not c3["graphiques"]          # moteur 3 : barres du solde, pas de courbe
    assert c3["plus_bouge"] and "attendu" in c3["plus_bouge"]["texte"]


def test_rejeu_moteur_2_rendement_2_ans(semaine):
    g = semaine["chapitres"]["2"]["graphiques"][0]
    assert g["cle"] == "USD_2a" and g["derniere"] == ["2026-11-20", 4.63]
    assert g["variation_semaine"]["valeur"] == -25 and g["variation_semaine"]["unite"] == "pb"


def test_rejeu_moteur_1_vix(semaine):
    g = semaine["chapitres"]["1"]["graphiques"][0]
    assert g["cle"] == "vix" and g["derniere"][1] == 28.44


def test_rejeu_chapitre_final(semaine):
    f = semaine["final"]
    assert [c["date"] for c in f["calendrier"]] == ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27"]
    mer = next(c for c in f["calendrier"] if c["date"] == "2026-11-25")
    forts = [e["evenement"] for e in mer["evenements"] if e["impact"] == "fort"]
    assert any("PCE" in e for e in forts) and any("PIB" in e for e in forts)
    assert "Thanksgiving" in next(c for c in f["calendrier"] if c["date"] == "2026-11-26")["ferie"][0]
    r = f["risque_principal"]
    assert r["seuil"] and r["rendez_vous"] and "PCE" in r["texte"] and r["redige_par"] == "python"


def test_rejeu_attribution_titres_sans_doublon(semaine):
    for k, ch in semaine["chapitres"].items():
        titres = [t["titre"] for t in ch["actualite"]]
        assert len(titres) == len(set(titres)) and len(titres) <= 15
        assert all(int(k) in t["moteurs"] for t in ch["actualite"])
        assert all(t.get("pourquoi") or t.get("source") for t in ch["actualite"])
    assert sum(len(c["actualite"]) for c in semaine["chapitres"].values()) > 0


def test_rejeu_en_tete_et_temps_de_lecture(semaine):
    assert semaine["semaine"] == "2026-S47" and semaine["statut"] == "complète" and not semaine["erreurs"]
    assert len(semaine["bref"]) == 8 and all(b["nom"] for b in semaine["bref"])
    assert semaine["lecture_min"] == doc.temps_lecture(semaine) and semaine["lecture_min"] >= 10


def test_recit_python_au_moins_250_mots_pour_chaque_moteur(semaine):
    for k, ch in semaine["chapitres"].items():
        r = ch["recit"]
        assert r["redige_par"] == "python" and r["mots"] >= 250, (k, r["mots"])
        assert 3 <= len(r["paragraphes"]) and r["exergue"]
        texte = " ".join(r["paragraphes"] + [r["exergue"]])
        assert not doc.INTERDITS.search(texte), (k, doc.INTERDITS.search(texte).group())
        assert not doc.ENGRENAGE_SEUL.search(texte)
        assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", texte)          # dates en JJ/MM


def test_aucun_mot_interdit_dans_les_textes_python(semaine):
    """Tout le texte écrit par Python (hors titres de presse cités tels quels dans la liste « actualité »)."""
    d = json.loads(json.dumps(semaine))
    for ch in d["chapitres"].values():
        ch.pop("actualite", None)
    textes = []

    def parcourir(x):
        if isinstance(x, dict):
            for v in x.values():
                parcourir(v)
        elif isinstance(x, list):
            for v in x:
                parcourir(v)
        elif isinstance(x, str):
            textes.append(x)
    parcourir(d)
    trouves = [t for t in textes if re.search(r"\b(LONG|SHORT)\b", t) or re.search(r"\b(entrée|stop|objectif)\b", t, re.I)]
    assert not trouves, trouves[:3]


def test_titre_citable():
    assert not doc.titre_citable("Trump vows to stop U.S. companies")
    assert doc.titre_citable("UK October retail sales +0.7% vs +0.0% m/m expected")


# ------------------------------------------------------------------ rédaction : contrôle, bascule, cache
class ModeleRenvoie:
    def __init__(self, texte=None, erreur=None):
        self.texte, self.erreur, self.appels = texte, erreur, 0

    def appeler_llm(self, prompt, systeme=None):
        self.appels += 1
        if self.erreur:
            raise self.erreur
        return self.texte


class GroqRenvoie:
    nom = "groq/openai/gpt-oss-120b"

    def __init__(self, texte):
        self.texte, self.appels = texte, 0

    def disponible(self):
        return True

    def appeler(self, prompt):
        self.appels += 1
        return self.texte


def _regroupe(ch):
    """Le récit Python du moteur 7, regroupé en 5 paragraphes au plus, passe le contrôle du modèle (longueur, paragraphes,
    nombres, vocabulaire) : il sert de réponse simulée."""
    p = ch["recit"]["paragraphes"]
    return {"paragraphes": p[:4] + [" ".join(p[4:])] if len(p) > 5 else p, "exergue": ch["recit"]["exergue"]}


def _texte_valide(ch):
    return json.dumps(_regroupe(ch), ensure_ascii=False)


def test_controle_recit_rejette_un_nombre_invente(semaine):
    ch = semaine["chapitres"]["7"]
    faits = doc.faits_recit(ch, _sem(semaine), semaine["theme"]["jour_par_jour"])
    assert doc.controler_recit(_regroupe(ch), faits, ch["nom"]) == []
    faux = {"paragraphes": ch["recit"]["paragraphes"][:-1] + [ch["recit"]["paragraphes"][-1] + " Le dollar a pris 12,34 % en une séance."],
            "exergue": ch["recit"]["exergue"]}
    assert any("12,34" in r for r in doc.controler_recit(faux, faits, ch["nom"]))
    ordre = {"paragraphes": ch["recit"]["paragraphes"] + ["Placer un stop sous le plus bas."], "exergue": "x"}
    assert any("interdit" in r or "ordre" in r for r in doc.controler_recit(ordre, faits, ch["nom"]))


def test_texte_du_modele_rejete_repli_python(semaine):
    ch = semaine["chapitres"]["7"]
    faits = doc.faits_recit(ch, _sem(semaine), semaine["theme"]["jour_par_jour"])
    mauvais = json.dumps({"paragraphes": ["Le dollar a pris 12,34 %."] * 4, "exergue": "x"})
    r, journal = doc.rediger_recit(faits, ch["nom"], ModeleRenvoie(mauvais), None)
    assert r is None and journal["tentatives"][0]["rejets"]


def test_quota_epuise_bascule_sur_groq(semaine):
    ch = semaine["chapitres"]["7"]
    faits = doc.faits_recit(ch, _sem(semaine), semaine["theme"]["jour_par_jour"])
    gemini = ModeleRenvoie(erreur=BudgetEpuise("quota atteint (429)"))
    groq = GroqRenvoie(_texte_valide(ch))
    r, journal = doc.rediger_recit(faits, ch["nom"], gemini, groq)
    assert gemini.appels == 1 and groq.appels == 1
    assert r and "groq" in r["redige_par"] and r["mots"] >= 450
    assert "BudgetEpuise" in journal["tentatives"][0]["erreur"]


def test_doit_rediger_recit_un_appel_par_jour():
    forts = ["2026-11-19|AUD|employment change"]
    nuit = datetime(2026, 11, 19, 6, 0, tzinfo=timezone.utc)
    matin = datetime(2026, 11, 19, 8, 20, tzinfo=timezone.utc)
    soir = datetime(2026, 11, 19, 20, 0, tzinfo=timezone.utc)
    assert doc.doit_rediger_recit(None, "2026-S47", nuit, forts)[0] is False          # avant la remise à zéro
    assert doc.doit_rediger_recit(None, "2026-S47", matin, forts)[0] is True
    entree = {"semaine": "2026-S47", "jour": "2026-11-19", "forts": forts}
    assert doc.doit_rediger_recit(entree, "2026-S47", soir, forts) == (False, "déjà rédigé aujourd'hui, aucun fait fort nouveau")
    faire, motif = doc.doit_rediger_recit(entree, "2026-S47", soir, forts + ["2026-11-19|USD|philly fed manufacturing index"])
    assert faire and "fait fort nouveau" in motif
    lendemain = datetime(2026, 11, 20, 8, 30, tzinfo=timezone.utc)
    assert doc.doit_rediger_recit(entree, "2026-S47", lendemain, forts)[0] is True
    assert doc.doit_rediger_recit(entree, "2026-S47", datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc), forts)[0] is False
    faire, motif = doc.doit_rediger_recit({**entree, "jour": "2026-11-21"}, "2026-S47", SAMEDI, forts)
    assert faire and "samedi" in motif                                                    # version « semaine complète »
    assert doc.doit_rediger_recit({**entree, "jour": "2026-11-21", "complet": True}, "2026-S47", SAMEDI, forts)[0] is False


def test_rediger_cache_un_appel_par_jour_et_bilan(racine):
    d = doc.calculer(racine, SAMEDI, _h5(), CONFIG)
    groq = GroqRenvoie(_texte_valide(d["chapitres"]["7"]))
    gemini = ModeleRenvoie(erreur=BudgetEpuise("quota atteint"))
    d = doc.rediger(d, racine, SAMEDI, gemini, groq)
    assert gemini.appels == 8 and groq.appels == 8                          # une tentative par moteur
    assert d["redaction"]["groq"] == ["7"] and len(d["redaction"]["python"]) == 7
    assert d["redaction"]["ligne"] == "Documentaire : 0 récits par le modèle, 1 par Groq, 7 en Python"
    assert d["chapitres"]["7"]["recit"]["redige_par"].startswith("secours groq")
    # deuxième run du même jour : aucun appel, le récit Groq est repris du cache
    d2 = doc.rediger(doc.calculer(racine, SAMEDI.replace(hour=11), _h5(), CONFIG), racine, SAMEDI.replace(hour=11), gemini, groq)
    assert gemini.appels == 8 and groq.appels == 8
    assert d2["redaction"]["groq"] == ["7"]


def test_rediger_sans_modele_tout_en_python(racine):
    d = doc.rediger(doc.calculer(racine, SAMEDI, _h5(), CONFIG), racine, SAMEDI)
    assert d["redaction"]["ligne"] == "Documentaire : 0 récits par le modèle, 0 par Groq, 8 en Python"


# ------------------------------------------------------------------ mode dégradé
def test_source_absente_chapitre_degrade(racine):
    (racine / "data" / "cache" / "publications_archive.json").unlink()
    (racine / "docs" / "data" / "dossiers.json").unlink()
    d = doc.calculer(racine, SAMEDI, historique_5ans.Historique({}), CONFIG)
    assert len(d["chapitres"]) == 8
    c3 = d["chapitres"]["3"]
    assert c3["publications"] == [] and c3["recit"]["mots"] >= 250 and c3["indicateurs"] == []
    g = d["chapitres"]["2"]["graphiques"][0]
    assert g["raison"] == "série absente du cache 5 ans"
    assert d["final"]["calendrier"]


def test_section_en_echec_ne_casse_pas_les_autres(racine, monkeypatch):
    vrai = doc.graphiques_moteur

    def casse(h5, n, sem, technique=None):
        if n == 5:
            raise RuntimeError("série illisible")
        return vrai(h5, n, sem, technique)
    monkeypatch.setattr(doc, "graphiques_moteur", casse)
    d = doc.calculer(racine, SAMEDI, _h5(), CONFIG)
    assert d["chapitres"]["5"]["graphiques"] == [] and "série illisible" in d["chapitres"]["5"]["erreurs"][0]
    assert d["chapitres"]["5"]["recit"]["mots"] >= 250
    assert d["chapitres"]["2"]["graphiques"]

    monkeypatch.setattr(doc, "recit_python", lambda *a: (_ for _ in ()).throw(RuntimeError("panne")))
    d = doc.calculer(racine, SAMEDI, _h5(), CONFIG)
    assert all("erreur" in c for c in d["chapitres"].values())
    assert d["final"]["calendrier"]                                         # le chapitre final reste


# ------------------------------------------------------------------ écriture et archive
def test_ecrire_semaine_alias_et_index(racine):
    dossier = racine / "docs" / "data" / "documentaire"
    dossier.mkdir(parents=True)
    for s in range(30, 46):    # 16 anciennes semaines : il n'en reste que 12 au total
        (dossier / f"2026-S{s:02d}.json").write_text(json.dumps({"du": "x", "au": "y", "titre_semaine": f"S{s}", "statut": "complète"}), encoding="utf-8")
    d = doc.ecrire(racine, CONFIG, SAMEDI, h5=_h5())
    assert d and (dossier / "2026-S47.json").exists() and (racine / "docs" / "data" / "documentaire.json").exists()
    assert len(list(dossier.glob("????-S??.json"))) == 12
    index = json.loads((dossier / "index.json").read_text(encoding="utf-8"))
    assert index["semaines"][0]["id"] == "2026-S47" and len(index["semaines"]) == 12


def test_ecrire_ne_leve_jamais(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "calculer", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("panne")))
    assert doc.ecrire(tmp_path, CONFIG, SAMEDI) is None


# ------------------------------------------------------------------ site
def test_site_documentaire():
    js = (RACINE / "docs" / "site" / "documentaire.js").read_text(encoding="utf-8")
    assert "attributionLogo: false" in js or "attributionLogo:false" in js
    assert "Reprendre là où j'en étais" in js and "fxdesk-doc-position-" in js
    ecran = (RACINE / "docs" / "site" / "ecran_engrenages.js").read_text(encoding="utf-8")
    for adresse in ("tableau", "s=", "c("):
        assert adresse in ecran
    sw = (RACINE / "docs" / "sw.js").read_text(encoding="utf-8")
    assert "data/documentaire.json" in sw and "site/documentaire.js" in sw and "site/v13.css" in sw
    css = (RACINE / "docs" / "site" / "v7.css").read_text(encoding="utf-8")
    assert "overflow-x:clip" in css                                         # garde position:sticky (sommaire)
