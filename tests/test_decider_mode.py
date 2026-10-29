"""Lot Verrouillage, point 2 : déclencheur externe (cron-job.org), crons GitHub en secours, garde-fou des 20 minutes."""
import sys
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "outils"))
import decider_mode as dm  # noqa: E402

T = datetime(2026, 10, 29, 9, 16, tzinfo=timezone.utc)
EXT = lambda c: {"declencheur": "externe", "creneau": c}


def test_externe_matin_heure_dimanche():
    assert dm.decider("workflow_dispatch", "", EXT("matin"), False, [], "1", T)[0] == "complet"
    assert dm.decider("workflow_dispatch", "", EXT("heure"), True, [], "1", T)[0] == "completer"
    assert dm.decider("workflow_dispatch", "", EXT("heure"), False, [], "1", T) == ("complet", "aucun rapport du jour : run complet (rattrapage)")
    assert dm.decider("workflow_dispatch", "", EXT("dimanche"), False, [], "1", T)[0] == "hebdo"
    assert dm.decider("workflow_dispatch", "", EXT("matin"), True, [], "1", T)[0] == "completer"   # jamais deux runs complets


def test_crons_github_en_secours_inchanges():
    assert dm.decider("schedule", "15 8 * * 1-5", {}, False, [], "1", T)[0] == "complet"
    assert dm.decider("schedule", "45 8 * * 1-5", {}, True, [], "1", T)[0] == "rien"
    assert dm.decider("schedule", "45 8 * * 1-5", {}, False, [], "1", T)[0] == "complet"
    assert dm.decider("schedule", "15 9-21 * * 1-5", {}, True, [], "1", T)[0] == "completer"
    assert dm.decider("schedule", "15 9-21 * * 1-5", {}, False, [], "1", T)[0] == "complet"
    assert dm.decider("schedule", "15 7 * * 0", {}, False, [], "1", T)[0] == "hebdo"


def test_garde_fou_20_minutes():
    recent = [{"databaseId": 7, "createdAt": "2026-10-29T09:15:02Z", "status": "in_progress", "conclusion": None, "event": "workflow_dispatch"},
              {"databaseId": 8, "createdAt": "2026-10-29T09:16:00Z", "status": "in_progress", "event": "schedule"}]
    mode, raison = dm.decider("schedule", "15 9-21 * * 1-5", {}, True, recent, "8", T)
    assert mode == "rien" and "moins de 20 min" in raison                  # le cron GitHub arrive après cron-job.org
    assert dm.decider("workflow_dispatch", "", EXT("heure"), True, recent, "9", T)[0] == "rien"
    echec = [{"databaseId": 7, "createdAt": "2026-10-29T09:10:00Z", "status": "completed", "conclusion": "failure"}]
    assert dm.decider("schedule", "15 9-21 * * 1-5", {}, True, echec, "8", T)[0] == "completer"   # un run en échec ne bloque pas
    ancien = [{"databaseId": 7, "createdAt": "2026-10-29T08:50:00Z", "status": "completed", "conclusion": "success"}]
    assert dm.decider("schedule", "15 9-21 * * 1-5", {}, True, ancien, "8", T)[0] == "completer"  # 26 min : pas un doublon
    # un lancement manuel n'est jamais bloqué
    assert dm.decider("workflow_dispatch", "", {"completer": "true"}, True, recent, "9", T)[0] == "completer"
    assert dm.decider("workflow_dispatch", "", {"completer": "false"}, True, recent, "9", T)[0] == "complet"


def test_workflow_branche_sur_le_script_et_crons_gardes():
    wf = (RACINE / ".github/workflows/rapport.yml").read_text(encoding="utf-8")
    assert "python3 outils/decider_mode.py" in wf and "actions: read" in wf
    for cron in ('"15 8 * * 1-5"', '"45 8 * * 1-5"', '"15 9-21 * * 1-5"', '"15 7 * * 0"'):
        assert cron in wf
    assert "declencheur:" in wf and "creneau:" in wf
    guide = (RACINE / "docs/GUIDE_DECLENCHEUR.md").read_text(encoding="utf-8")
    assert "cron-job.org" in guide and "Actions" in guide and "rapport.yml/dispatches" in guide
