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
import time
from pathlib import Path

log = logging.getLogger(__name__)

ESSAIS_PUSH = 4
PAUSE_PUSH_S = 5.0
# Fichiers produits par le robot : en cas de conflit au rebase, NOTRE version (celle du run) est gardée.
DONNEES_ROBOT = ("docs/data/", "data/")
# Raison du dernier échec de publication (None si aucun) : l'orchestrateur sort alors en erreur (run rouge).
ECHEC_PUSH: list[str] = []


class PushEchoue(RuntimeError):
    """Le commit du run n'a pas pu être poussé après tous les essais."""


class ConflitCode(PushEchoue):
    """Conflit sur un fichier hors données du robot : jamais résolu automatiquement, pas de nouvel essai."""


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
    # JSON dérivé du site (régime, indicateurs clés, heatmap) : calcul Python, jamais bloquant.
    from core import site_donnees
    site_donnees.ecrire(Path(dossier_docs).resolve().parent)
    return dossier


def _git(*args: str, racine: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=racine, capture_output=True, text=True, check=False
    )


def pousser_git(config_web: dict, racine_projet: str | Path = ".",
                message: str = "rapport quotidien : données du jour") -> bool:
    """Committe docs/data + data/rapports + data/cache + registre macro. Retourne True si poussé."""
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

    # config.yaml : porte le database_id Notion écrit au premier run. Chemins ajoutés UN PAR UN :
    # « git add » échoue en bloc si l'un d'eux n'existe pas encore (rien ne serait alors committé).
    for chemin in ("docs/data", "data/rapports", "data/cache", "data/hebdo", "config.yaml",
                   "data/registre_macro.json", "data/overrides/saisies_notion.json", "data/archives"):
        if (racine / chemin).exists():
            _git("add", chemin, racine=racine)
    commit = _git("commit", "-m", message, racine=racine)
    if commit.returncode != 0:
        log.info("Rien à committer (%s)", commit.stdout.strip() or commit.stderr.strip())
        return False
    branche = _branche(racine)
    derniere, classe = "", PushEchoue
    for essai in range(1, ESSAIS_PUSH + 1):
        try:
            _rebaser(racine, branche)
        except ConflitCode as exc:
            derniere, classe = str(exc), ConflitCode
            break   # conflit hors données du robot : pas de nouvel essai qui écraserait du code
        except PushEchoue as exc:   # pull en échec (réseau, dépôt injoignable) : nouvel essai après la pause
            derniere = str(exc)
            log.warning("git pull --rebase en échec (essai %d/%d) : %s", essai, ESSAIS_PUSH, derniere)
            if essai < ESSAIS_PUSH:
                time.sleep(PAUSE_PUSH_S)
            continue
        push = _git("push", "origin", f"HEAD:{branche}", racine=racine)
        if push.returncode == 0:
            log.info("Dashboard web poussé sur le dépôt (essai %d/%d)", essai, ESSAIS_PUSH)
            return True
        derniere = push.stderr.strip()[:300]
        log.warning("git push en échec (essai %d/%d) : %s", essai, ESSAIS_PUSH, derniere)
        if essai < ESSAIS_PUSH:
            time.sleep(PAUSE_PUSH_S)
    raison = f"git push impossible après {essai} essai(s) sur {ESSAIS_PUSH} vers {branche} : {derniere}"
    ECHEC_PUSH.append(raison)
    log.error(raison)
    raise classe(raison)


def _branche(racine: Path) -> str:
    nom = _git("rev-parse", "--abbrev-ref", "HEAD", racine=racine).stdout.strip()
    if nom and nom != "HEAD":
        return nom
    return os.environ.get("GITHUB_REF_NAME") or "master"


def _rebaser(racine: Path, branche: str) -> None:
    """git pull --rebase --autostash : rejoue le commit du run au-dessus des commits arrivés entre-temps.
    Conflit sur docs/data ou data/ : notre version (le commit rejoué) est gardée. Conflit ailleurs : abandon."""
    pull = _git("pull", "--rebase", "--autostash", "origin", branche, racine=racine)
    tours = 0
    while pull.returncode != 0 and tours < 20:
        tours += 1
        conflits = [l for l in _git("diff", "--name-only", "--diff-filter=U", racine=racine).stdout.splitlines() if l.strip()]
        if not conflits:
            _git("rebase", "--abort", racine=racine)
            raise PushEchoue(f"git pull --rebase en échec : {(pull.stderr or pull.stdout).strip()[:300]}")
        hors_donnees = [c for c in conflits if not c.startswith(DONNEES_ROBOT)]
        if hors_donnees:
            _git("rebase", "--abort", racine=racine)
            raise ConflitCode(f"conflit hors données du robot, rebase abandonné : {', '.join(hors_donnees)}")
        for c in conflits:   # pendant un rebase, « theirs » = le commit rejoué, c'est-à-dire NOTRE version
            _git("checkout", "--theirs", "--", c, racine=racine)
            _git("add", "--", c, racine=racine)
        log.warning("Conflit résolu en gardant la version du run : %s", ", ".join(conflits))
        pull = subprocess.run(["git", "-c", "core.editor=true", "rebase", "--continue"], cwd=racine,
                              capture_output=True, text=True, check=False)
    if pull.returncode != 0:
        _git("rebase", "--abort", racine=racine)
        raise PushEchoue("rebase interrompu : trop de conflits successifs")
