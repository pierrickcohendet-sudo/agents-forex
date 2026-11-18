"""Lot V10 : noms des 8 moteurs à la place de « engrenage N » (hors onglet dédié), archive du contexte pour la « Lecture du
site » du Journal. Données du 18/11 figées ; aucun appel réseau ni modèle."""
import gzip
import json
import re
from pathlib import Path

import pytest

from core import noms_moteurs as nm, rapport_jour

RACINE = Path(__file__).resolve().parents[1]
REJEU = Path(__file__).parent / "donnees" / "rejeu_2026-11-18"
MOT = re.compile(r"ngrenage", re.I)


@pytest.fixture(autouse=True)
def sans_cle_secours(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


def charger(nom):
    return json.loads(gzip.decompress((REJEU / f"{nom}.json.gz").read_bytes()).decode("utf-8"))


def textes_hors_onglet(obj):
    """Toutes les valeurs texte, sans le sous-arbre « engrenages » (contenu de l'onglet dédié) ni les clés."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in nm.SOUS_ARBRES_ONGLET and isinstance(v, dict):
                continue
            yield from textes_hors_onglet(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from textes_hors_onglet(v)
    elif isinstance(obj, str):
        yield obj


# ------------------------------------------------------------------ noms
def test_noms_des_moteurs():
    assert [nm.nom(n) for n in range(1, 9)] == ["Thème dominant", "Banques centrales et taux", "Chiffres économiques",
                                                "Budgets et dette publique", "Liens entre marchés", "Géopolitique",
                                                "Prix et positionnement", "Commerce et flux"]
    assert nm.nom(7, True) == "prix et positionnement" and "COT" in nm.explication(7)
    assert nm.avec_explication(3) == "chiffres économiques (publications au-dessus ou en dessous du consensus)"
    assert nm.liste_noms([2, 3, 5]) == "banques centrales et taux, chiffres économiques et liens entre marchés"
    assert not MOT.search(nm.CONSIGNE_MODELE.replace("« engrenage »", ""))   # la consigne ne cite le mot que pour l'interdire
    js = (RACINE / "docs" / "site" / "moteurs.js").read_text(encoding="utf-8")
    assert '"Prix et positionnement"' in js and "GÉNÉRÉ par core/noms_moteurs.py" in js


def test_decompte_pour_contre():
    contrib = [{"engrenage": 3, "contribution": 3}, {"engrenage": 7, "contribution": 1}, {"engrenage": 6, "contribution": -1},
               {"engrenage": 1, "contribution": 0}]
    d = nm.decompte(contrib)
    assert (d["pour"], d["contre"], d["neutres"]) == (2, 1, 1) and d["noms_contre"] == ["géopolitique"]
    assert nm.texte_decompte({"pour": 4, "contre": 0}) == "4 moteurs pour, 0 contre"


@pytest.mark.parametrize("avant,apres", [
    ("le solde des engrenages reste favorable à AUD (+4)", "le solde des moteurs reste favorable à AUD (+4)"),
    ("Pourquoi c'est important : GBP · engrenage 3 (données économiques).", "Pourquoi c'est important : GBP · chiffres économiques."),
    ("Engrenage 7", "Prix et positionnement"),
    ("Engrenages orientés : 2. Monétaire (Dollar haussier) ; 7. Flux (Dollar neutre)",
     "Moteurs orientés : Banques centrales et taux (Dollar haussier) ; Prix et positionnement (Dollar neutre)"),
    ("3 engrenages sur 7 suivent le thème", "3 moteurs sur 7 suivent le thème"),
])
def test_remplacement_automatique(avant, apres):
    t, n = nm.remplacer(avant)
    assert t == apres and n >= 1 and not MOT.search(t)


def test_identifiants_et_onglet_laisses_tels_quels():
    assert nm.remplacer("#engrenages/g=3") == ("#engrenages/g=3", 0)
    obj, n = nm.nettoyer({"engrenage": 3, "texte": "engrenage 5 : VIX", "synthese_globale": {"engrenages": {"regle": "engrenage 5"}}})
    assert obj["texte"] == "Liens entre marchés : VIX" and obj["synthese_globale"]["engrenages"]["regle"] == "engrenage 5" and n == 1


# ------------------------------------------------------------------ rejeu du 18/11
@pytest.mark.parametrize("fichier", ["synthese", "briefing", "rapport_jour", "accueil"])
def test_rejeu_du_18_11_sans_le_mot(fichier):
    brut = charger(fichier)
    assert any(MOT.search(t) for t in textes_hors_onglet(brut))          # le 18/11 publié contenait bien le mot
    propre, n = nm.nettoyer(brut)
    assert n > 0 and not [t for t in textes_hors_onglet(propre) if MOT.search(t)]


def test_conditions_des_scenarios_en_noms_de_moteurs():
    dec = charger("decompositions")["AUD/NZD"]["macro"]["decomposition"]
    h, b = rapport_jour.conditions_moteurs(dec, "AUD", "NZD")
    assert h == ["2 moteurs sur 8 vont dans le sens de l'AUD (chiffres économiques, prix et positionnement), 0 contre"]
    assert b[0].startswith("les moteurs se retournent en faveur du NZD") and not MOT.search(h[0] + b[0])


def test_filet_de_securite_sur_un_dossier(tmp_path):
    (tmp_path / "paires").mkdir()
    (tmp_path / "agenda.json").write_text(json.dumps({"pourquoi": "USD · engrenage 2 (politique monétaire)"}), encoding="utf-8")
    (tmp_path / "dossiers.json").write_text(json.dumps({"titre": "engrenage 2"}), encoding="utf-8")
    bilan = nm.nettoyer_publication(tmp_path)
    assert bilan == {"agenda.json": 1}
    assert json.loads((tmp_path / "agenda.json").read_text(encoding="utf-8"))["pourquoi"] == "USD · banques centrales et taux"
    assert json.loads((tmp_path / "dossiers.json").read_text(encoding="utf-8"))["titre"] == "engrenage 2"   # onglet dédié
    assert json.loads((tmp_path / "moteurs.json").read_text(encoding="utf-8"))["moteurs"]["8"]["nom"] == "Commerce et flux"


def test_site_sans_le_mot_hors_onglet():
    """Chaînes visibles des écrans hors onglet « 8 engrenages » : plus de « engrenage » (les identifiants restent)."""
    hors = ["accueil.js", "devises.js", "ecran_paire.js", "ecran_synthese.js", "ecran_tableau.js", "journal.js", "rapport.js"]
    for f in hors:
        s = (RACINE / "docs" / "site" / f).read_text(encoding="utf-8")
        lignes = [l for l in s.splitlines() if not l.lstrip().startswith(("/*", "*", "//"))]
        fautifs = [l.strip()[:120] for l in lignes if re.search(r"(?<![.\w#/_\"'])[Ee]ngrenages?(?![\w\"'\]./=:])", l)
                   and "Ouvrir le cockpit" not in l and "onglet « 8 engrenages »" not in l]
        assert not fautifs, (f, fautifs[:3])
