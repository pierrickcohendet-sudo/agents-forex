"""Lot V10 (B4) : reconstitue l'archive `docs/data/contexte/` à partir de l'historique git des données publiées.

Chaque commit qui a modifié `docs/data/paires.json` contient l'état exact du site à cette heure-là : on extrait les fichiers
utiles dans un dossier temporaire et on archive l'instantané à l'heure du commit (jamais une donnée recalculée après coup).
Usage : python outils/rejouer_contexte.py 2026-11-02
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from core import contexte  # noqa: E402

FICHIERS = ["dossiers.json", "profil_devises.json", "rapport_jour.json", "paires.json", "agenda.json"]


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=RACINE, capture_output=True, check=True).stdout


def main(depuis: str) -> None:
    lignes = git("log", "--reverse", f"--since={depuis}T00:00:00Z", "--format=%H %cI", "--", "docs/data/paires.json").decode().split()
    commits = list(zip(lignes[0::2], lignes[1::2]))
    sortie = RACINE / "docs" / "data" / "contexte"
    for h, quand in commits:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "paires").mkdir()
            try:
                pj = json.loads(git("show", f"{h}:docs/data/paires.json"))
            except (subprocess.CalledProcessError, ValueError):
                pj = {}
            noms = FICHIERS + [f"paires/{p.replace('/', '-')}.json" for p in contexte.paires(pj)]
            for f in noms:
                try:
                    (d / f).write_bytes(git("show", f"{h}:docs/data/{f}"))
                except subprocess.CalledProcessError:
                    pass
            r = contexte.archiver(d, datetime.fromisoformat(quand), dossier_sortie=sortie)
            print(quand, h[:7], r)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-11-02")
