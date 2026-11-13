"""Construit les données figées d'un rejeu de la Synthèse V9 depuis l'historique git (lot V9, partie F).

Usage : python outils/construire_rejeu.py <commit> <AAAA-MM-JJ>
  ex. python outils/construire_rejeu.py 479400e 2026-11-09   (run du matin du lundi 09/11)
Sortie : tests/donnees/rejeu_<date>/ (fichiers .json.gz) : les JSON publiés ce jour-là (docs/data), les caches utiles
(historiques réduits aux séries lues, rendements, page « mois »), l'archive des publications reconstruite comme le
pipeline l'aurait fait ce jour-là, et la réponse du BLS figée (simulée : aucun appel réseau dans les tests).
"""
from __future__ import annotations

import gzip
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
DOCS = ["rapport_jour.json", "agenda.json", "profil_devises.json", "force_devises.json", "accueil.json", "paires.json"]
SERIES = ["brent", "brent_bno", "wti", "wti_uso", "USD_2a", "USD_10a", "USD_30a", "vix", "sp500_spy", "japon_ewj", "or_xau", "nasdaq_qqq",
          "cuivre_cper", "taiwan_ewt", "chine_fxi"]
# Lot V9.4 : sources simulées (copiées telles qu'elles sont au moment de la construction : BLS avec composantes des prix,
# ONS et Eurostat, communiqués et procès-verbaux archivés, probabilités citées)
CACHES_SIMULES = ["bls_emploi.json", "officiels_v94.json", "proba_fed.json"]


def git_json(commit: str, chemin: str):
    r = subprocess.run(["git", "show", f"{commit}:{chemin}"], cwd=RACINE, capture_output=True)
    if r.returncode:
        return None
    return json.loads(r.stdout.decode("utf-8"))


def ecrire(dossier: Path, nom: str, donnees) -> None:
    (dossier / (nom + ".gz")).write_bytes(gzip.compress(json.dumps(donnees, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0))


def main(commit: str, jour: str) -> None:
    sortie = RACINE / "tests" / "donnees" / f"rejeu_{jour}"
    (sortie / "docs" / "paires").mkdir(parents=True, exist_ok=True)
    (sortie / "cache").mkdir(parents=True, exist_ok=True)
    for n in DOCS:
        ecrire(sortie / "docs", n, git_json(commit, f"docs/data/{n}"))
    rj = git_json(commit, "docs/data/rapport_jour.json")
    for w in ((rj.get("watchlist") or {}).get("top") or [])[:1]:
        f = w["paire"].replace("/", "-") + ".json"
        d = git_json(commit, f"docs/data/paires/{f}")
        if d:
            ecrire(sortie / "docs" / "paires", f, d)
    h = git_json(commit, "data/cache/collecte_historiques.json") or {}
    don = h.get("donnees") or {}
    ecrire(sortie / "cache", "collecte_historiques.json",
           {"date": h.get("date"), "donnees": {"series": {k: v for k, v in (don.get("series") or {}).items() if k in SERIES}}})
    ecrire(sortie / "cache", "historique_taux.json", git_json(commit, "data/cache/historique_taux.json"))
    news = git_json(commit, "data/cache/collecte_news.json")
    if news:
        ecrire(sortie / "cache", "collecte_news.json", news)
    for n in CACHES_SIMULES:
        f = RACINE / "data" / "cache" / n
        if f.exists():
            ecrire(sortie / "cache", n, json.loads(f.read_text(encoding="utf-8")))
    com = RACINE / "data" / "communiques_v9"
    if com.exists():
        (sortie / "communiques_v9").mkdir(exist_ok=True)
        for f in com.glob("*.json"):
            ecrire(sortie / "communiques_v9", f.name, json.loads(f.read_text(encoding="utf-8")))
    # Archive des publications telle que le pipeline l'aurait construite ce jour-là (Agenda + page « mois »)
    from core import publications_archive as pa
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "data" / "cache").mkdir(parents=True)
        (t / "data" / "archives").mkdir(parents=True)
        (t / "config.yaml").write_text((RACINE / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        for src, dst in (("data/cache/calendrier_mois.json", "data/cache/calendrier_mois.json"),
                         ("data/archives/publications.json", "data/archives/publications.json")):
            d = git_json(commit, src)
            if d:
                (t / dst).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        a = pa.mettre_a_jour(git_json(commit, "docs/data/agenda.json"), t, date.fromisoformat(jour),
                             datetime.fromisoformat(jour + "T08:30:00+00:00"))
    ecrire(sortie / "cache", "publications_archive.json", a)
    print(f"rejeu {jour} écrit dans {sortie}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
