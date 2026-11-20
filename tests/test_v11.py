"""Lot V11 : Journal selon la maquette (accueil option B, page d'un trade option A, Photos, liste et fil). Les fonctions pures
sont testées en JavaScript (tests/journal_v5.test.mjs) ; ici : lancement du test, archive du contexte sous les noms de marché
(EUR/USD et non USD/EUR), vocabulaire des textes générés par le Journal. Aucun appel réseau ni modèle."""
import json
import re
import subprocess
from pathlib import Path

from core import contexte

RACINE = Path(__file__).resolve().parents[1]
SITE = RACINE / "docs" / "site"


def test_journal_v5_fonctions_pures_js():
    r = subprocess.run(["node", str(RACINE / "tests" / "journal_v5.test.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "journal V5 : OK" in r.stdout


def test_archive_contexte_sous_les_noms_de_marche():
    pj = json.loads((RACINE / "docs" / "data" / "paires.json").read_text(encoding="utf-8"))
    l = contexte.paires(pj)
    assert len(l) == 36 and "EUR/USD" in l and "USD/EUR" not in l and "USD/JPY" in l
    assert "EUR/USD" in contexte.paires() and "USD/EUR" not in contexte.paires()     # convention de repli
    idx = json.loads((RACINE / "docs" / "data" / "contexte" / "index.json").read_text(encoding="utf-8"))
    dernier = sorted(idx["jours"])[-1]
    f = json.loads((RACINE / "docs" / "data" / "contexte" / f"{dernier}.json").read_text(encoding="utf-8"))
    i = contexte.reconstituer(f, len(f["instantanes"]) - 1)
    assert "EUR/USD" in i["paires"] and "GBP/USD" in i["paires"] and "USD/EUR" not in i["paires"]


def test_textes_generes_par_le_journal_sans_vocabulaire_interdit():
    """Phrases produites par le site (lecture, confrontation) : jamais « entrée », « stop », « objectif » ni « il fallait entrer »."""
    interdit = re.compile(r"\b(entrée|entrer|stop|objectif)s?\b", re.I)
    for f in ("journal_lecture.js",):
        s = (SITE / f).read_text(encoding="utf-8")
        gabarits = re.findall(r"`[^`]*`|\"[^\"\n]*\"", s)
        fautifs = [g for g in gabarits if interdit.search(g) and "data/" not in g]
        assert not fautifs, fautifs[:3]
    s = (SITE / "journal_v4.js").read_text(encoding="utf-8")
    phrase = s[s.index("export function phraseSynthese"):s.index("export function confrontation")]
    conf = s[s.index("export function confrontation"):s.index("export function publicationsPendant")]
    for bloc in (phrase, conf):
        assert not re.search(r"`[^`]*\b(entrée|entrer|stop|objectif)\b[^`]*`", bloc, re.I)


def test_ecran_journal_v11_branche():
    s = (SITE / "ecran_journal.js").read_text(encoding="utf-8")
    for attendu in ("statsAccueil", "semainesMois", "Enregistrer et écrire mon analyse", "résultat à compléter", "Changer la couverture",
                    "+ Ajouter des photos", "Lecture du site", "vueFil", "vueListe"):
        assert attendu in s, attendu
    assert "v11.css" in (RACINE / "docs" / "index.html").read_text(encoding="utf-8")
