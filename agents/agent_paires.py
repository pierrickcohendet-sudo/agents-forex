"""Synthèse en 3 lignes des « Mes paires » par le modèle (lot V5, étape 7). UN appel groupé par jour, après les
engrenages et les devises, dans la réserve de quota (étiquette « paires:synthese »). Le modèle ne fait que rédiger à
partir des faits Python de chaque fiche ; une phrase qui cite un chiffre absent des faits ou un ordre est retirée ;
en cas d'échec ou de quota atteint, la phrase Python reste (le site l'affiche seule).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from agents.agent_dossier_hebdo import _valeurs, verifier_chiffres
from agents.agent_synthese import _retirer_ordres
from core.llm import (FournisseurLLM, QuotaAtteint, attribution_modele, definir_etiquette, extraire_json,
                      repli_modele_suivant)
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)
SCHEMA = '{"paires": {"USD/JPY": "3 lignes au plus", "...": "..."}}'


def faits(fiche: dict) -> dict:
    m, t = fiche.get("macro") or {}, fiche.get("technique") or {}
    return {"theme": m.get("theme"), "direction_paire": m.get("direction_paire"),
            "solde_engrenages": (m.get("decomposition") or {}).get("solde"), "scores": m.get("scores"), "surprises": m.get("surprises"),
            "portage_pb": {k: (m.get("portage") or {}).get(k) for k in ("directeur_pb", "deux_ans_pb")},
            "technique": {k: t.get(k) for k in ("cours", "rsi14", "ecart_mm50", "ecart_mm200", "volatilite_30j")},
            "synthese_python": fiche.get("synthese_python")}


def generer(llm: FournisseurLLM | None, fiches: dict[str, dict], tentatives: int = 2) -> dict:
    """{paire: {texte, redige_par}} ; {} si le modèle manque (la phrase Python reste)."""
    if llm is None or not fiches:
        return {}
    donnees = {p: faits(f) for p, f in fiches.items() if not f.get("raison")}
    autorises = _valeurs(donnees, set())
    prompt = ("Pour chaque paire, rédige une synthèse de 3 lignes au plus, en français, à partir des SEULS faits fournis "
              "(calculés en Python). Aucune recommandation, aucun ordre d'achat ou de vente, aucun niveau de prix cible. "
              f"Réponds STRICTEMENT en JSON : {SCHEMA}\n\nFAITS (JSON) :\n" + json.dumps(donnees, ensure_ascii=False))
    definir_etiquette("paires:synthese")
    for _ in range(max(1, tentatives)):
        try:
            brut = extraire_json(llm.appeler_llm(prompt))
            textes = (brut or {}).get("paires") if isinstance(brut, dict) else None
            if not isinstance(textes, dict):
                raise ValueError("réponse sans « paires »")
            sortie, auteur = {}, attribution_modele()
            for p in donnees:
                t, _ = _retirer_ordres(str(textes.get(p) or "")[:600])
                t, _ = verifier_chiffres(t, autorises)
                if t:
                    sortie[p] = {"texte": t, "redige_par": auteur, "le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            return sortie
        except QuotaAtteint:
            log.warning("Synthèse des paires : quota atteint — phrases Python conservées")
            return {}
        except Exception as exc:  # noqa: BLE001
            repli_modele_suivant(llm)
            log.warning("Synthèse des paires : essai en échec (%s)", masquer_secrets(str(exc)))
    return {}


def executer(racine: str | Path, config: dict, llm: FournisseurLLM | None) -> dict:
    """Une fois par jour : texte du modèle pour « Mes paires », écrit dans le cache du jour et dans paires.json."""
    racine = Path(racine)
    cache = racine / "data" / "cache" / "paires_textes.json"
    jour = date.today().isoformat()
    try:
        ancien = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ancien = {}
    if ancien.get("date") == jour and ancien.get("textes"):
        return ancien["textes"]
    chemin = racine / config.get("publication_web", {}).get("dossier_docs", "docs") / "data" / "paires.json"
    try:
        p = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    mes = {k: p["fiches"][k] for k in p.get("mes_paires") or [] if k in (p.get("fiches") or {})}
    textes = generer(llm, mes, int((config.get("llm") or {}).get("max_tentatives_json", 2)))
    if not textes:
        return {}
    cache.write_text(json.dumps({"date": jour, "textes": textes}, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, t in textes.items():
        p["fiches"][k]["synthese_modele"] = t
    chemin.write_text(json.dumps(p, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return textes
