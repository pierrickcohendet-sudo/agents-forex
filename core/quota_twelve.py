"""Quota Twelve Data (plan gratuit : 800 crédits par jour, 8 par minute) — compteur partagé par tous les collecteurs.

Chaque requête passe par `consommer(n, module)` AVANT l'appel : refus si le plafond du jour (moins une marge) serait
dépassé, attente si la minute glissante compte déjà 8 crédits. Le compteur du jour (UTC) est gardé dans
data/cache/quota_twelve.json (committé : il survit d'un run à l'autre) ; le résumé du run affiche « N/800 ».
Une requête en lot (plusieurs symboles) coûte un crédit par symbole.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

PLAFOND_JOUR = 800
MARGE = 40            # jamais au ras du plafond : les relances et les autres outils gardent de la place
PAR_MINUTE = 8
CHEMIN = Path(__file__).resolve().parents[1] / "data" / "cache" / "quota_twelve.json"
_minute: deque = deque()


class QuotaTwelveAtteint(RuntimeError):
    pass


def _jour() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def etat(chemin: Path | None = None) -> dict:
    chemin = Path(chemin or CHEMIN)
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        brut = {}
    if brut.get("date") != _jour():
        brut = {"date": _jour(), "credits": 0, "par_module": {}}
    brut.setdefault("par_module", {})
    brut["plafond"] = PLAFOND_JOUR
    return brut


def consommer(n: int = 1, module: str = "autre", chemin: Path | None = None, horloge=time.monotonic, dormir=time.sleep) -> dict:
    """Réserve n crédits ; lève QuotaTwelveAtteint si le plafond du jour (moins la marge) serait dépassé."""
    chemin = Path(chemin or CHEMIN)
    e = etat(chemin)
    if e["credits"] + n > PLAFOND_JOUR - MARGE:
        raise QuotaTwelveAtteint(f"quota Twelve Data du jour presque atteint ({e['credits']}/{PLAFOND_JOUR}, marge {MARGE}) : "
                                 f"{n} crédit(s) refusé(s) pour {module}")
    if n > PAR_MINUTE:
        raise QuotaTwelveAtteint(f"{n} crédits en une requête : plus que la limite de {PAR_MINUTE} par minute")
    while True:   # minute glissante : au plus PAR_MINUTE crédits
        maintenant = horloge()
        while _minute and maintenant - _minute[0][0] >= 60:
            _minute.popleft()
        if sum(c for _, c in _minute) + n <= PAR_MINUTE:
            break
        attente = 60 - (maintenant - _minute[0][0]) + 0.5
        log.info("Twelve Data : %d crédit(s) déjà utilisés cette minute, pause de %.0f s", sum(c for _, c in _minute), attente)
        dormir(max(attente, 0.5))
    _minute.append((horloge(), n))
    e["credits"] += n
    e["par_module"][module] = e["par_module"].get(module, 0) + n
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps({k: e[k] for k in ("date", "credits", "par_module")}, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.warning("Compteur Twelve Data non écrit : %s", exc)
    return e


def ligne_resume(chemin: Path | None = None) -> str:
    e = etat(chemin)
    detail = ", ".join(f"{m} {c}" for m, c in sorted(e["par_module"].items(), key=lambda kv: -kv[1]))
    return f"Twelve Data : {e['credits']}/{PLAFOND_JOUR} crédits aujourd'hui (UTC){f' — {detail}' if detail else ''}"
