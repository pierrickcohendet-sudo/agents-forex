"""Auto-évaluation hebdomadaire chiffrée — calcul 100 % Python.

Compare la prévision de J-7 (score de confluence + classement) aux variations
réelles observées sur les "prix de clôture orientés force" stockés dans chaque
rapport (série où monter = la devise se renforce, y compris pour les paires
inversées et l'indice USD synthétique).

Convention directionnelle : score > 55 = biais haussier attendu ;
score < 45 = baissier ; entre les deux = neutre (correct si |variation| est
sous le seuil configuré). Le LLM ne fournit que le commentaire d'accompagnement.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)


def charger_rapport_precedent(dossier_rapports: str | Path, jours: int = 7) -> dict | None:
    """Rapport daté d'il y a ~7 jours (tolérance ±2 jours, le plus proche)."""
    dossier = Path(dossier_rapports)
    cible = date.today() - timedelta(days=jours)
    candidats = []
    for fichier in dossier.glob("*.json"):
        try:
            d = date.fromisoformat(fichier.stem)
        except ValueError:
            continue
        if abs((d - cible).days) <= 2:
            candidats.append((abs((d - cible).days), fichier))
    if not candidats:
        return None
    fichier = min(candidats, key=lambda c: c[0])[1]
    try:
        return json.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def evaluer(rapport_precedent: dict, prix_actuels: dict[str, float],
            seuil_neutre_pct: float = 0.15) -> dict | None:
    prix_avant = rapport_precedent.get("prix_cloture") or {}
    classement_prevu = rapport_precedent.get("synthese_globale", {}).get("classement_devises", [])
    if not prix_avant or not classement_prevu:
        log.warning("Rapport précédent sans prix_cloture/classement : auto-évaluation impossible")
        return None

    par_devise, variations, scores = [], {}, {}
    for entree in classement_prevu:
        devise = entree["devise"]
        avant, apres = prix_avant.get(devise), prix_actuels.get(devise)
        if not avant or not apres:
            continue
        variation = (apres - avant) / avant * 100
        score = entree["score_confluence"]
        prevu = "hausse" if score > 55 else "baisse" if score < 45 else "neutre"
        correct = (
            (prevu == "hausse" and variation > 0)
            or (prevu == "baisse" and variation < 0)
            or (prevu == "neutre" and abs(variation) <= seuil_neutre_pct)
        )
        variations[devise] = variation
        scores[devise] = score
        par_devise.append({
            "devise": devise, "score_prevu": score, "prevu": prevu,
            "variation_reelle_pct": round(variation, 2), "correct": correct,
        })

    if not par_devise:
        return None
    taux = round(100 * sum(d["correct"] for d in par_devise) / len(par_devise), 1)
    spearman = None
    if len(variations) >= 3:
        s = pd.Series(scores).loc[list(variations)]
        v = pd.Series(variations)
        spearman = round(float(s.corr(v, method="spearman")), 2)

    return {
        "periode": {
            "du": rapport_precedent.get("meta", {}).get("date_rapport"),
            "au": date.today().isoformat(),
        },
        "par_devise": par_devise,
        "taux_reussite_biais_pct": taux,
        "correlation_classement_spearman": spearman,
        "commentaire_llm": None,  # rempli ensuite par le stratège (formulation seulement)
    }
