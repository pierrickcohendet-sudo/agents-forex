"""Saisies manuelles faites DIRECTEMENT dans le Tableau macro Notion.

Fichier : data/overrides/saisies_notion.json — écrit par CE module (le pipeline
l'alimente quand il détecte qu'une cellule Notion diffère de la dernière valeur
qu'il y a lui-même écrite). Distinct des fichiers data/overrides/AAAA-MM-JJ.json
que vous écrivez à la main : core/overrides.py reste en lecture seule et inchangé.

Ordre de priorité d'une case (dans core/tableau_macro.py) :
  1. fichier manuel du jour  data/overrides/AAAA-MM-JJ.json
  2. saisie Notion (ce fichier), tant qu'aucune publication officielle PLUS
     RÉCENTE que la saisie n'est arrivée
  3. publication officielle la plus récente (registre ForexFactory)
Une saisie supplantée par une publication officielle passe dans `historique`.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

MARQUEUR = "✍️"
MAX_HISTORIQUE = 200


def cle(devise: str, indicateur: str, type_valeur: str) -> str:
    return f"{devise}|{indicateur}|{type_valeur}"


def charger(chemin: str | Path) -> dict:
    try:
        brut = json.loads(Path(chemin).read_text(encoding="utf-8"))
        if isinstance(brut, dict):
            brut.setdefault("saisies", {})
            brut.setdefault("historique", [])
            return brut
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("saisies_notion.json illisible (%s) — ignoré", exc)
    return {"saisies": {}, "historique": []}


def sauver(saisies: dict, chemin: str | Path) -> None:
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    Path(chemin).write_text(json.dumps(saisies, ensure_ascii=False, indent=1, sort_keys=True),
                            encoding="utf-8")


def nettoyer_texte(texte: str) -> str:
    """Texte saisi sans le marqueur ✍️ (ajouté par le pipeline)."""
    return texte.replace(MARQUEUR, "").replace("✍", "").strip()


def enregistrer(saisies: dict, devise: str, indicateur: str, type_valeur: str,
                texte_notion: str, jour: date) -> None:
    saisies["saisies"][cle(devise, indicateur, type_valeur)] = {
        "texte": nettoyer_texte(texte_notion), "saisi_le": jour.isoformat(),
        "origine": "cellule Notion modifiée à la main"}
    log.info("Saisie manuelle détectée dans Notion : %s %s %s = %r",
             devise, indicateur, type_valeur, nettoyer_texte(texte_notion))


def archiver(saisies: dict, cle_saisie: str, jour: date, raison: str) -> None:
    saisie = saisies["saisies"].pop(cle_saisie, None)
    if saisie is None:
        return
    saisies["historique"].append({**saisie, "cle": cle_saisie,
                                  "remplacee_le": jour.isoformat(), "raison": raison})
    del saisies["historique"][:-MAX_HISTORIQUE]


def vers_overrides(saisies: dict, registre: dict) -> dict[str, dict[str, dict]]:
    """Saisies actives -> format de core/overrides.py (devise -> indicateur ->
    {valeur, prevision, precedent, date, note}), pour qu'elles servent aussi aux
    rapports et à l'analyse. `valeur` est obligatoire dans ce format : une saisie
    portant seulement sur Précédent/Prévision reprend la valeur officielle."""
    resultat: dict[str, dict[str, dict]] = {}
    for cle_saisie, s in saisies.get("saisies", {}).items():
        devise, indicateur, type_valeur = cle_saisie.split("|")
        o = resultat.setdefault(devise, {}).setdefault(indicateur, {"note": "saisie manuelle (Tableau macro Notion)"})
        o["date"] = s["saisi_le"]
        champ = {"Actuel": "valeur", "Précédent": "precedent", "Prévision": "prevision"}[type_valeur]
        o[champ] = s["texte"]
    for devise, par_indic in resultat.items():
        for indicateur, o in par_indic.items():
            if "valeur" not in o:
                actuel = (registre.get("cases", {}).get(f"{devise}|{indicateur}") or {}).get("actuel") or {}
                o["valeur"] = actuel.get("valeur")
    return resultat


def fusionner_overrides(base: dict, saisies_ov: dict) -> dict:
    """Le fichier manuel du jour (base) garde la priorité sur la saisie Notion."""
    resultat = {d: dict(v) for d, v in saisies_ov.items()}
    for devise, par_indic in base.items():
        resultat.setdefault(devise, {}).update(par_indic)
    return resultat
