"""Séries de marché du dashboard web : VIX, pétrole (WTI + Brent), indice dollar.

Source unique : FRED (gratuit, quotidien). Un an d'historique (période réglable
1 mois / 3 mois / 1 an côté navigateur), dernière valeur et variation sur la
semaine précalculées ici (Python), écrites dans docs/data/marche.json.

Indice dollar : le DXY (ICE) n'est pas gratuit. On affiche l'« indice dollar
large » de la Fed (DTWEXBGS, pondéré par les échanges commerciaux, ~4 jours de
retard) et on l'étiquette clairement — jamais « DXY ». L'indice USD synthétique
calculé sur Twelve Data (technique.USD) reste utilisé ailleurs dans le rapport.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from core.fred_macro import _observations
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

PERIODES_JOURS = {"1M": 31, "3M": 92, "1A": 366}


def _resume(points: list[list], jours: int = 7) -> dict:
    """Dernière valeur et variation vs il y a >= `jours` jours (points croissants)."""
    d0, v0 = points[-1]
    limite = (date.fromisoformat(d0) - timedelta(days=jours)).isoformat()
    avant = next(((d, v) for d, v in reversed(points[:-1]) if d <= limite), None)
    resume = {"derniere": v0, "date": d0, "variation": None, "variation_pct": None, "date_ref": None}
    if avant:
        resume.update(variation=round(v0 - avant[1], 4),
                      variation_pct=round((v0 / avant[1] - 1) * 100, 2) if avant[1] else None,
                      date_ref=avant[0])
    return resume


def collecter(cfg_tm: dict, cle: str) -> dict:
    """{"graphiques": {"vix": {...}, "petrole": {...}, "dollar": {...}}, "erreurs": [...]}."""
    cfg = cfg_tm.get("graphiques_marche") or {}
    resultat: dict = {"graphiques": {}, "erreurs": []}
    if not cle:
        resultat["erreurs"].append("FRED_API_KEY absente — graphiques de marché sautés")
        return resultat
    debut = (date.today() - timedelta(days=PERIODES_JOURS["1A"] + 10)).isoformat()
    for identifiant, spec in cfg.items():
        courbes = {}
        for nom, serie in spec["series"].items():
            try:
                obs = _observations(serie["serie"], cle, nb=420, observation_start=debut)
                points = sorted([o["date"], round(float(o["value"]), spec.get("decimales", 2))] for o in obs)
                if points:
                    courbes[nom] = {"libelle": serie["libelle"], "serie_id": serie["serie"],
                                    "couleur": serie.get("couleur"), "points": points, **_resume(points)}
            except Exception as exc:  # noqa: BLE001
                resultat["erreurs"].append(f"{identifiant}/{nom} ({serie['serie']}) : "
                                           f"{masquer_secrets(str(exc))[:120]}")
        if courbes:
            resultat["graphiques"][identifiant] = {
                "titre": spec["titre"], "unite": spec.get("unite", ""), "source": spec["source"],
                "note": spec.get("note"), "decimales": spec.get("decimales", 2), "courbes": courbes}
    log.info("Séries de marché : %d graphique(s), %d erreur(s)", len(resultat["graphiques"]),
             len(resultat["erreurs"]))
    return resultat


def ecrire_web(resultat: dict, dossier_docs: str | Path, maj: str) -> bool:
    """docs/data/marche.json ; retourne True si le contenu a changé."""
    chemin = Path(dossier_docs) / "data" / "marche.json"
    contenu = {"maj": maj, "periodes": PERIODES_JOURS, "graphiques": resultat.get("graphiques", {})}
    try:
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
        if {**ancien, "maj": None} == {**contenu, "maj": None}:
            return False
    except (OSError, json.JSONDecodeError):
        pass
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(contenu, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return True
