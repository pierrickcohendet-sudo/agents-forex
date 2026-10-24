"""Attend qu'aucun run « rapport-fx » ne soit en cours ou en file avant un push manuel sur master.

Pourquoi : un push pendant un run rend le push du robot non fast-forward (incident du run #73, 15/10/2026).
Le robot sait maintenant se rebaser, mais on évite le cas à la source.
Usage : python outils/attendre_runs.py [--max-minutes 50]   (code 0 : la voie est libre ; 1 : délai dépassé)
API publique de GitHub, lecture seule, sans jeton : UNE requête par vérification (limite de 60 requêtes par heure
sans jeton) ; quand GitHub annonce la limite atteinte, on attend sa remise à zéro au lieu de conclure « voie libre ».
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEPOT = "pierrickcohendet-sudo/agents-forex"
WORKFLOW = "rapport-fx"
ACTIFS = {"in_progress", "queued", "waiting", "requested", "pending"}


class LimiteAPI(Exception):
    def __init__(self, reprise: float | None):
        super().__init__("limite de l'API GitHub atteinte")
        self.reprise = reprise


def runs_actifs() -> list[dict]:
    url = f"https://api.github.com/repos/{DEPOT}/actions/runs?per_page=30"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "agents-forex-outil"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            runs = json.load(r).get("workflow_runs", [])
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429) and exc.headers.get("X-RateLimit-Remaining") == "0":
            reset = exc.headers.get("X-RateLimit-Reset")
            raise LimiteAPI(float(reset) if reset else None) from exc
        raise
    return [x for x in runs if x.get("name") == WORKFLOW and x.get("status") in ACTIFS]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-minutes", type=float, default=50)
    p.add_argument("--pause", type=float, default=60)
    a = p.parse_args()
    fin = time.time() + a.max_minutes * 60
    while True:
        try:
            actifs = runs_actifs()
        except LimiteAPI as exc:   # état inconnu : on attend la remise à zéro annoncée par GitHub
            attente = max(a.pause, (exc.reprise or time.time() + a.pause) - time.time() + 5)
            print(f"Limite de l'API GitHub atteinte : reprise dans {attente / 60:.0f} min.")
            if time.time() + attente > fin:
                print("Délai dépassé : ne pas pousser maintenant.")
                return 1
            time.sleep(attente)
            continue
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
