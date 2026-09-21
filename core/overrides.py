"""Repli manuel généralisé — data/overrides/{date}.json.

Étend le principe déjà en place pour les taux directeurs (config.yaml, source
"config (repli manuel)") à N'IMPORTE QUEL indicateur du tableau, pour une
date donnée. Priorité SYSTÉMATIQUE sur la donnée automatique.

Le pipeline ne WRIT JAMAIS dans ce dossier — lecture seule par construction
(aucune fonction d'écriture dans ce module). L'utilisateur écrit ces fichiers
lui-même (localement ou via un commit) ; un futur run ne les touche ni ne les
écrase jamais, silencieusement ou non.

Format de data/overrides/AAAA-MM-JJ.json :
{
  "USD": {
    "taux_directeur": {"valeur": "4.25 %", "note": "annonce Fed d'urgence, pas encore dans FRED"}
  },
  "CAD": {
    "petrole_contexte": {"valeur": 82.4, "precedent": 79.1, "date": "2026-08-15",
                          "note": "FRED en retard d'un jour"}
  }
}
Par override : "valeur" obligatoire ; "prevision" / "precedent" / "date"
optionnels (date = origine de la valeur, "aujourd'hui" si omise) ; "note"
optionnelle, affichée à côté de la source "repli manuel".
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

SOURCE_REPLI_MANUEL = "repli manuel"


def charger(dossier: str | Path, jour: date) -> dict[str, dict[str, dict]]:
    """Charge data/overrides/{jour}.json — {} si absent ou invalide, ne bloque
    jamais le pipeline. Devise -> indicateur -> {valeur, prevision, precedent, date, note}."""
    chemin = Path(dossier) / f"{jour.isoformat()}.json"
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("data/overrides/%s.json illisible, ignoré (%s)", jour.isoformat(), exc)
        return {}
    if not isinstance(brut, dict):
        log.warning("data/overrides/%s.json : racine non-objet, ignoré", jour.isoformat())
        return {}
    if brut:
        log.info("Repli manuel actif aujourd'hui : %s",
                 ", ".join(f"{d} ({len(v)})" for d, v in brut.items()))
    return brut


def appliquer_au_tableau(lignes: list[dict], overrides_devise: dict[str, dict] | None,
                         jour: date) -> list[dict]:
    """Dernière étape après la construction normale du tableau : remplace
    valeur/prévision/précédent/date pour chaque indicateur repris à la main,
    force la source à "repli manuel". Fonctionne pour N'IMPORTE QUEL
    indicateur — ajoute une ligne si celui-ci n'existait pas déjà."""
    if not overrides_devise:
        return lignes
    par_indicateur = {l["indicateur"]: l for l in lignes}
    for indicateur, o in overrides_devise.items():
        cible = par_indicateur.get(indicateur)
        if cible is None:
            cible = {"indicateur": indicateur, "nom": indicateur.replace("_", " ").capitalize()}
            lignes.append(cible)
            par_indicateur[indicateur] = cible
        cible["valeur"] = o.get("valeur")
        if "prevision" in o:
            cible["prevision"] = o["prevision"]
        if "precedent" in o:
            cible["precedent"] = o["precedent"]
        cible["date"] = str(o.get("date") or jour.isoformat())
        cible["source"] = SOURCE_REPLI_MANUEL
        cible["note"] = str(o.get("note") or "valeur saisie manuellement (data/overrides/)")
        try:
            cible["anciennete_jours"] = (jour - date.fromisoformat(cible["date"][:10])).days
        except ValueError:
            cible["anciennete_jours"] = None
    return lignes
