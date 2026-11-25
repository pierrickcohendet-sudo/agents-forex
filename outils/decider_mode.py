"""Décide du mode d'un run « rapport-fx » : complet, completer, hebdo ou rien (étape « Décider du mode » du workflow).

Déclencheurs :
- crons GitHub (secours, parfois retardés de plusieurs heures) ;
- service externe (cron-job.org, docs/GUIDE_DECLENCHEUR.md) : workflow_dispatch avec declencheur=externe et
  creneau=matin | heure | dimanche ;
- lancement manuel (workflow_dispatch, cases « completer » / « hebdo ») : jamais bloqué par le garde-fou.

Règles :
- lot V14 : cron « 7,37 0-21 * * 1-5 » (ou créneau externe « lecture ») : lecture ForexFactory planifiée (mode lecture) si
  une lecture de data/cache/ff_planning.json est due, sinon rien ;
- dimanche (cron 07:15 ou créneau externe « dimanche ») : hebdo ;
- samedi et dimanche 08:15 UTC (cron « 15 8 * * 0,6 » ou créneau externe « moteurs ») : moteurs (dossiers des 8 moteurs seuls) ;
- sans rapport du jour (data/rapports/AAAA-MM-JJ.json, date UTC) : run complet (rattrapage) ;
- avec rapport du jour : complément (le secours de 08:45 ne fait rien) ;
- garde-fou anti-doublon : un déclenchement automatique (cron ou externe) arrivé moins de 20 minutes après un autre
  run « rapport-fx » réussi ou encore en cours ne fait rien (le cron GitHub et cron-job.org tombent au même quart d'heure).

Usage dans le workflow : python3 outils/decider_mode.py  (variables d'environnement EVT, CRON, IN_*, RUNS_JSON, RUN_ID)
Écrit « mode=… » dans $GITHUB_OUTPUT et la raison dans le journal. Python standard seulement (avant l'installation).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ECART_MIN = 20
ACTIFS = {"in_progress", "queued", "waiting", "requested", "pending"}


def _date(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def doublon(runs: list[dict], run_id: str | int | None, maintenant: datetime, ecart_min: int = ECART_MIN) -> dict | None:
    """Autre run réussi ou en cours, créé moins de `ecart_min` minutes avant maintenant (le run courant exclu)."""
    for r in runs or []:
        if str(r.get("databaseId") or r.get("id")) == str(run_id):
            continue
        cree = _date(r.get("createdAt") or r.get("created_at"))
        if cree is None or not timedelta(0) <= maintenant - cree < timedelta(minutes=ecart_min):
            continue
        statut, conclusion = r.get("status"), r.get("conclusion")
        if statut in ACTIFS or conclusion == "success":
            return r
    return None


CRON_MOTEURS = "15 8 * * 0,6"   # samedi et dimanche, après la remise à zéro du quota Gemini
CRON_LECTURES = "7,37 0-21 * * 1-5"   # lot V14 : lectures ForexFactory planifiées (ne fait rien si aucune n'est due)


def lecture_due(planning: dict | None, budget: dict | None, maintenant: datetime, plafond: int = 6) -> tuple[bool, str]:
    """Fonction pure (lot V14, A1.5). Une lecture planifiée est due si son heure est passée, qu'aucune requête
    ForexFactory n'a eu lieu depuis, et que le plafond du jour n'est pas atteint (même règle que
    agents/collecte_forexfactory_mois.collecte_due)."""
    jour = maintenant.date().isoformat()
    plan = ((planning or {}).get("jours") or {}).get(jour)
    if not plan or not plan.get("lectures"):
        return False, "aucune lecture ForexFactory planifiée aujourd'hui"
    faites = [x for x in ((budget or {}).get("horodatages") or [])] if (budget or {}).get("date") == jour else []
    if len(faites) >= plafond:
        return False, f"plafond de {plafond} lectures atteint"
    passees = []
    for x in plan["lectures"]:
        h, m = (int(v) for v in x["heure_utc"].split(":"))
        c = maintenant.replace(hour=h, minute=m, second=0, microsecond=0)
        if c <= maintenant:
            passees.append((c, x))
    if not passees:
        return False, "prochaine lecture planifiée : " + plan["lectures"][0]["heure_utc"] + " UTC"
    c, x = max(passees, key=lambda p: p[0])
    if any((_date(f) or datetime.min.replace(tzinfo=timezone.utc)) >= c for f in faites):
        return False, f"lecture de {x['heure_utc']} UTC déjà faite"
    return True, f"lecture planifiée de {x['heure_utc']} UTC ({x.get('motif')})"


def decider(evt: str, cron: str, entrees: dict, rapport_existe: bool, runs: list[dict] | None = None,
            run_id: str | None = None, maintenant: datetime | None = None, lecture: tuple[bool, str] | None = None) -> tuple[str, str]:
    maintenant = maintenant or datetime.now(timezone.utc)
    if (evt == "schedule" and cron == CRON_LECTURES) or (evt == "workflow_dispatch" and entrees.get("declencheur") == "externe"
                                                         and (entrees.get("creneau") or "") == "lecture"):
        ok, raison = lecture or (False, "planning des lectures non lu")
        return ("lecture", raison) if ok else ("rien", raison)
    vrai = lambda k: str(entrees.get(k, "")).lower() == "true"
    externe = evt == "workflow_dispatch" and entrees.get("declencheur") == "externe"
    creneau = entrees.get("creneau") or ""
    automatique = evt == "schedule" or externe
    if automatique:
        d = doublon(runs or [], run_id, maintenant)
        if d:
            return "rien", (f"garde-fou : un autre run rapport-fx ({d.get('event')}, {d.get('status')}"
                            f"{'/' + str(d.get('conclusion')) if d.get('conclusion') else ''}) a démarré à "
                            f"{d.get('createdAt') or d.get('created_at')}, moins de {ECART_MIN} min avant")
    if (evt == "schedule" and cron == "15 7 * * 0") or (externe and creneau == "dimanche") or (evt == "workflow_dispatch" and vrai("hebdo")):
        return "hebdo", "dossier hebdomadaire des engrenages"
    if (evt == "schedule" and cron == CRON_MOTEURS) or (externe and creneau == "moteurs"):
        return "moteurs", "week-end 08:15 UTC : dossiers des 8 moteurs après la remise à zéro du quota (si encore en Python)"
    if evt == "workflow_dispatch" and not externe:
        return ("completer", "lancement manuel : complément") if vrai("completer") else ("complet", "lancement manuel : run complet")
    if evt == "schedule" and cron == "45 8 * * 1-5" and rapport_existe:
        return "rien", "secours 08:45 : le rapport du jour existe déjà"
    if rapport_existe:   # jamais un second run complet le même jour : il consommerait le quota Gemini une seconde fois
        return "completer", "rapport du jour présent : complément"
    return "complet", "aucun rapport du jour : run complet" + (" (rattrapage)" if creneau == "heure" or cron.startswith("15 9-21") else "")


def main() -> int:
    env = os.environ
    maintenant = datetime.now(timezone.utc)
    rapport = Path("data/rapports") / f"{maintenant.date().isoformat()}.json"
    try:
        runs = json.loads(env.get("RUNS_JSON") or "[]")
    except ValueError:
        runs = []
        print("Liste des runs illisible : garde-fou anti-doublon inactif pour ce passage.")
    entrees = {k: env.get(f"IN_{k.upper()}", "") for k in ("completer", "hebdo", "declencheur", "creneau")}
    def lire(chemin):
        try:
            return json.loads(Path(chemin).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    lecture = lecture_due(lire("data/cache/ff_planning.json"), lire("data/cache/forexfactory_requetes.json"), maintenant)
    mode, raison = decider(env.get("EVT", ""), env.get("CRON", ""), entrees, rapport.exists(), runs, env.get("RUN_ID"), maintenant,
                           lecture)
    print(f"Événement : {env.get('EVT')} {env.get('CRON')} {entrees} -> mode : {mode} ({raison})")
    sortie = env.get("GITHUB_OUTPUT")
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            f.write(f"mode={mode}\n")
    resume = env.get("GITHUB_STEP_SUMMARY")
    if resume:
        with open(resume, "a", encoding="utf-8") as f:
            f.write(f"## Mode du run\n\n{mode} : {raison}\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
