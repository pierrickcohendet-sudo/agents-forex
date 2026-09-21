"""Base hebdomadaire cumulative par devise — code pur, aucun LLM.

Un fichier par devise et par semaine ISO (data/hebdo/EUR_semaine_2026-W33.json),
mis à jour chaque jour par UPSERT (l'entrée du jour remplace celle du même jour,
les autres jours sont préservés — jamais de recréation du fichier).

L'analyse weekly s'appuie sur toute la progression lundi→vendredi (cohérence du
biais dans le temps), pas seulement sur la comparaison J-7 → J de
l'auto-évaluation. Les métriques sont calculées ici ; le LLM ne fait que
formuler le commentaire (agents/agent_strategiste.commenter_analyse_weekly).
"""
from __future__ import annotations

import json
import logging
import statistics
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


def semaine_iso(jour: date) -> str:
    annee, semaine, _ = jour.isocalendar()
    return f"{annee}-W{semaine:02d}"


def chemin_semaine(dossier: str | Path, devise: str, jour: date) -> Path:
    return Path(dossier) / f"{devise}_semaine_{semaine_iso(jour)}.json"


def charger_semaine(dossier: str | Path, devise: str, jour: date) -> dict | None:
    try:
        return json.loads(chemin_semaine(dossier, devise, jour).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _direction(score: int) -> str:
    return "+" if score > 55 else "-" if score < 45 else "0"


def _valeur_tableau(devise_rapport: dict, indicateur: str):
    for ligne in devise_rapport.get("indicateurs_tableau", []):
        if ligne.get("indicateur") == indicateur:
            return ligne.get("valeur")
    return None


def upsert_jour(dossier: str | Path, rapport: dict) -> None:
    """Insère/remplace l'entrée du jour dans le fichier de semaine de chaque devise."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    jour = date.fromisoformat(rapport["meta"]["date_rapport"])

    for dev in rapport.get("devises", []):
        if dev.get("score_confluence") is None:
            # Analyse indisponible : pas de faux point dans la série de la semaine.
            log.info("Base hebdo : %s sauté (analyse indisponible aujourd'hui)", dev["devise"])
            continue
        fichier = chemin_semaine(dossier, dev["devise"], jour)
        contenu = charger_semaine(dossier, dev["devise"], jour) or {
            "devise": dev["devise"], "semaine_iso": semaine_iso(jour),
            "jours": [], "analyse_weekly": None,
        }
        entree = {
            "date": jour.isoformat(),
            "score_confluence": dev["score_confluence"],
            "sens_majoritaire": _direction(dev["score_confluence"]),
            "detail_sens": {d["indicateur"]: d["sens"] for d in dev.get("detail_score", [])},
            "indicateurs_cles": {
                "taux_directeur": (dev.get("carry") or {}).get("taux_directeur"),
                "rsi": _valeur_tableau(dev, "rsi"),
                "vix": _valeur_tableau(dev, "vix"),
            },
            "synthese": dev.get("synthese_une_phrase", ""),
        }
        contenu["jours"] = sorted(
            [j for j in contenu["jours"] if j["date"] != entree["date"]] + [entree],
            key=lambda j: j["date"],
        )
        fichier.write_text(json.dumps(contenu, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Base hebdo : %d devise(s) mises à jour pour la semaine %s",
             len(rapport.get("devises", [])), semaine_iso(jour))


def historique_recent(dossier: str | Path, devise: str, jour: date, jours: int = 7) -> list[dict]:
    """Points {date, score} des `jours` derniers jours pour la devise — sert la
    sparkline du dashboard web. Aucune nouvelle collecte : relit uniquement les
    fichiers de semaine déjà écrits par upsert_jour(). Une fenêtre de 7 jours
    calendaires chevauche au plus 2 semaines ISO : on lit donc le fichier de la
    semaine courante et, si besoin, celui d'il y a 7 jours."""
    limite = (jour - timedelta(days=jours - 1)).isoformat()
    points: dict[str, int] = {}
    for decalage in (0, 7):
        contenu = charger_semaine(dossier, devise, jour - timedelta(days=decalage))
        if not contenu:
            continue
        for j in contenu.get("jours", []):
            if j["date"] >= limite:
                points[j["date"]] = j["score_confluence"]
    return [{"date": d, "score": points[d]} for d in sorted(points)]


def metriques_semaine(contenu: dict) -> dict:
    """Cohérence du biais sur la semaine : trajectoire du score, stabilité,
    indicateurs qui ont changé de camp."""
    jours = contenu.get("jours", [])
    scores = [j["score_confluence"] for j in jours]
    directions = [j["sens_majoritaire"] for j in jours if j["sens_majoritaire"] != "0"]
    coherence = (round(100 * max(directions.count("+"), directions.count("-")) / len(directions), 1)
                 if directions else None)

    # Flip-flops : transitions +1 <-> -1 d'un même indicateur d'un jour à l'autre.
    instables: dict[str, int] = {}
    for indicateur in {i for j in jours for i in j.get("detail_sens", {})}:
        serie = [j["detail_sens"].get(indicateur) for j in jours]
        serie = [s for s in serie if s in (1, -1)]
        flips = sum(1 for a, b in zip(serie, serie[1:]) if a != b)
        if flips:
            instables[indicateur] = flips

    return {
        "nb_jours": len(jours),
        "trajectoire": [{"date": j["date"], "score": j["score_confluence"]} for j in jours],
        "score_debut": scores[0] if scores else None,
        "score_fin": scores[-1] if scores else None,
        "variation_score": (scores[-1] - scores[0]) if len(scores) > 1 else 0,
        "ecart_type_score": round(statistics.pstdev(scores), 1) if len(scores) > 1 else 0.0,
        "coherence_directionnelle_pct": coherence,
        "indicateurs_instables": dict(sorted(instables.items(), key=lambda x: -x[1])[:4]),
    }


def enregistrer_analyse(dossier: str | Path, devise: str, jour: date, analyse: dict) -> None:
    contenu = charger_semaine(dossier, devise, jour)
    if contenu is None:
        return
    contenu["analyse_weekly"] = analyse
    chemin_semaine(dossier, devise, jour).write_text(
        json.dumps(contenu, ensure_ascii=False, indent=1), encoding="utf-8")
