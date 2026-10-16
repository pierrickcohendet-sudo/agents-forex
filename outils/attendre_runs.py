"""Attend qu'aucun run « rapport-fx » ne soit en cours ou en file avant un push manuel sur master.

Pourquoi : un push pendant un run rend le push du robot non fast-forward (incident du run #73, 15/10/2026).
Le robot sait maintenant se rebaser, mais on évite le cas à la source.
Usage : python outils/attendre_runs.py [--max-minutes 50]   (code 0 : la voie est libre ; 1 : délai dépassé)
API publique de GitHub, lecture seule, sans jeton.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

DEPOT = "pierrickcohendet-sudo/agents-forex"
WORKFLOW = "rapport-fx"


def runs_actifs() -> list[dict]:
    actifs = []
    for statut in ("in_progress", "queued", "waiting", "requested", "pending"):
        url = f"https://api.github.com/repos/{DEPOT}/actions/runs?status={statut}&per_page=20"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "agents-forex-outil"})
        with urllib.request.urlopen(req, timeout=30) as r:
            actifs += [x for x in json.load(r).get("workflow_runs", []) if x.get("name") == WORKFLOW]
    return actifs


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-minutes", type=float, default=50)
    p.add_argument("--pause", type=float, default=30)
    a = p.parse_args()
    fin = time.time() + a.max_minutes * 60
    while True:
        try:
            actifs = runs_actifs()
        except OSError as exc:   # réseau ou API indisponible : état inconnu, donc on attend (jamais « voie libre »)
            print(f"API GitHub injoignable ({exc}) : nouvel essai dans {a.pause:.0f} s.")
            if time.time() > fin:
                print("Délai dépassé : ne pas pousser maintenant.")
                return 1
            time.sleep(a.pause)
            continue
        if not actifs:
            print("Aucun run rapport-fx en cours ni en file : push possible.")
            return 0
        for r in actifs:
            print(f"Run {r['id']} ({r['event']}) {r['status']} depuis {r['created_at']}")
        if time.time() > fin:
            print("Délai dépassé : ne pas pousser maintenant.")
            return 1
        time.sleep(a.pause)


if __name__ == "__main__":
    sys.exit(main())
