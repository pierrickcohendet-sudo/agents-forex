"""Lot V13 : reconstitue les titres de la semaine (data/cache/titres_semaine.json) à partir de l'historique git du cache des
flux RSS (data/cache/collecte_news.json). Chaque commit contient les titres collectés à ce moment-là : ils sont classés par
moteur (core/dossiers_moteurs) et ajoutés à leur semaine ISO, sans doublon. Usage : python outils/rejouer_titres.py 2026-11-16
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from core import documentaire  # noqa: E402


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=RACINE, capture_output=True, check=True).stdout


def main(depuis: str) -> None:
    lignes = git("log", "--reverse", f"--since={depuis}T00:00:00Z", "--format=%H %cI", "--", "data/cache/collecte_news.json").decode().split()
    for h, quand in zip(lignes[0::2], lignes[1::2]):
        try:
            d = json.loads(git("show", f"{h}:data/cache/collecte_news.json"))
        except (subprocess.CalledProcessError, ValueError):
            continue
        articles = ((d.get("donnees") or {}).get("articles")) or []
        r = documentaire.accumuler_titres(RACINE, articles, datetime.fromisoformat(quand))
        print(quand, h[:7], len(articles), "articles ;", {k: len(v) for k, v in r["semaines"].items()})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-11-16")
