"""Force des devises (lot V7) : variation sur 1, 5 et 20 séances et écart à la moyenne mobile 200 jours.

Calcul 100 % Python à partir de la série publiée dans docs/data/cours.json (même série unique 5 ans que le RSI et la
MM200 : Twelve Data raccordé à la Fed H.10 ; USD = indice synthétique face aux 8 autres devises). Le site ne fait
qu'afficher docs/data/force_devises.json : aucun recalcul dans le navigateur. Une devise sans série : « n/d » et raison.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
HORIZONS = {"j1": 1, "j5": 5, "j20": 20}
SOURCE = "calcul Python sur la série unique 5 ans (Twelve Data raccordé à la Fed H.10) ; USD : indice synthétique"


def variation(points: list, n: int) -> float | None:
    """Variation en % entre la dernière valeur et celle d'il y a n séances (None si la série est trop courte)."""
    if not points or len(points) <= n:
        return None
    a, b = points[-1 - n][1], points[-1][1]
    if not a or b is None:
        return None
    return round((b / a - 1) * 100, 2)


def calculer(cours: dict | None) -> dict:
    sortie = {"genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": SOURCE,
              "methode": ("Variation de la valeur de la devise en dollars (USD : indice face aux 8 autres) sur 1, 5 et "
                          "20 séances ; écart à la MM200 = dernière valeur / moyenne mobile 200 séances − 1."),
              "devises": []}
    par_devise = (cours or {}).get("devises") or {}
    for d in DEVISES:
        c = par_devise.get(d) or {}
        pts = [p for p in (c.get("points") or []) if p and p[1] is not None]
        mm = [p for p in (c.get("mm200") or []) if p and p[1] is not None]
        if not pts:
            sortie["devises"].append({"devise": d, **{k: None for k in HORIZONS}, "ecart_mm200": None, "dernier": None,
                                      "date": None, "raison": "série de cours absente de cours.json"})
            continue
        dernier, date_ = pts[-1][1], pts[-1][0]
        mm_dernier = mm[-1][1] if mm else None
        ligne = {"devise": d, **{k: variation(pts, n) for k, n in HORIZONS.items()},
                 "dernier": dernier, "date": date_, "mm200": mm_dernier,
                 "ecart_mm200": round((dernier / mm_dernier - 1) * 100, 2) if mm_dernier else None,
                 "libelle": c.get("libelle"), "raison": None}
        if ligne["ecart_mm200"] is None:
            ligne["raison_mm200"] = "moyenne mobile 200 séances absente"
        sortie["devises"].append(ligne)
    # Classements calculés ici (le site trie selon ces rangs, il ne compare rien lui-même)
    for k in [*HORIZONS]:
        tries = sorted((x for x in sortie["devises"] if x[k] is not None), key=lambda x: -x[k])
        for rang, x in enumerate(tries, 1):
            x.setdefault("rangs", {})[k] = rang
    return sortie


def ecrire(racine: str | Path, config: dict, cours: dict | None = None) -> dict | None:
    """Écrit docs/data/force_devises.json ; ne lève jamais (une panne n'affecte que ce bloc)."""
    try:
        docs = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
        if cours is None:
            cours = json.loads((docs / "cours.json").read_text(encoding="utf-8"))
        donnees = calculer(cours)
        (docs / "force_devises.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("force_devises.json non écrit : %s", exc)
        return None
