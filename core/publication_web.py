"""Publication du dashboard web (GitHub Pages).

Écrit le rapport JSON dans docs/data/ (latest.json + YYYY-MM-DD.json +
index.json listant les dates disponibles), puis committe/pousse si le
pipeline tourne sous GitHub Actions (ou si git_push: toujours).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def ecrire_donnees(rapport: dict, dossier_docs: str | Path) -> Path:
    dossier = Path(dossier_docs) / "data"
    dossier.mkdir(parents=True, exist_ok=True)
    date_rapport = rapport["meta"]["date_rapport"]
    contenu = json.dumps(rapport, ensure_ascii=False, indent=1)
    (dossier / f"{date_rapport}.json").write_text(contenu, encoding="utf-8")
    (dossier / "latest.json").write_text(contenu, encoding="utf-8")

    # index.json : entrées enrichies {date, type, biais, relecture} pour la vue
    # calendrier du dashboard. Upsert (les anciennes entrées sont conservées) ;
    # les entrées de l'ancien format (simple chaîne date) sont converties.
    chemin_index = dossier / "index.json"
    try:
        # utf-8-sig : tolère un BOM laissé par un éditeur/outil Windows.
        anciens = json.loads(chemin_index.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        anciens = []
    entrees: dict[str, dict] = {}
    for e in anciens:
        if isinstance(e, str):
            entrees[e] = {"date": e}
        elif isinstance(e, dict) and e.get("date"):
            entrees[e["date"]] = e
    entrees[date_rapport] = {
        "date": date_rapport,
        "type": rapport["meta"]["type_rapport"],
        "biais": rapport["synthese_globale"]["biais_macro_global"],
        # Jamais "ok" par défaut : absence de "critique" = relecture non effectuée.
        "relecture": rapport.get("critique", {}).get("validation", "non_evalue"),
    }
    liste = sorted(entrees.values(), key=lambda e: e["date"], reverse=True)
    chemin_index.write_text(json.dumps(liste, ensure_ascii=False), encoding="utf-8")
    log.info("Dashboard web : %d rapport(s) disponibles, dernier %s", len(liste), date_rapport)
    return dossier


def _git(*args: str, racine: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=racine, capture_output=True, text=True, check=False
    )


def pousser_git(config_web: dict, racine_projet: str | Path = ".") -> bool:
    """Committe docs/data + data/rapports + data/cache. Retourne True si poussé."""
    mode = config_web.get("git_push", "auto")
    sous_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    if mode == "jamais" or (mode == "auto" and not sous_actions):
        log.info("git push ignoré (mode=%s, GitHub Actions=%s)", mode, sous_actions)
        return False

    racine = Path(racine_projet)
    if _git("rev-parse", "--is-inside-work-tree", racine=racine).returncode != 0:
        log.warning("Pas un dépôt git : publication web sans push")
        return False

    if sous_actions:
        _git("config", "user.name", "github-actions[bot]", racine=racine)
        _git("config", "user.email", "github-actions[bot]@users.noreply.github.com", racine=racine)

    # config.yaml : porte le database_id Notion écrit au premier run.
    _git("add", "docs/data", "data/rapports", "data/cache", "data/hebdo", "config.yaml",
         racine=racine)
    commit = _git("commit", "-m", "rapport quotidien : données du jour", racine=racine)
    if commit.returncode != 0:
        log.info("Rien à committer (%s)", commit.stdout.strip() or commit.stderr.strip())
        return False
    push = _git("push", racine=racine)
    if push.returncode != 0:
        log.error("git push en échec : %s", push.stderr.strip())
        return False
    log.info("Dashboard web poussé sur le dépôt")
    return True
