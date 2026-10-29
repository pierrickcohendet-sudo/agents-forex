"""Alertes de fin de run (lot Verrouillage, point 4), en Python, sans LLM et sans nouvelle clé dans le site.

Trois causes :
- run en échec : étape(s) du pipeline en échec, ou publication (git push) refusée ;
- fraîcheur : une source ou un indicateur plus vieux que deux fois sa fréquence normale (docs/data/sources.json) ;
- quota : la synthèse des 8 engrenages bloquée par le quota du modèle.
Sortie : docs/data/alertes.json (bandeau orange sur l'accueil tant qu'une alerte est active).
Notification (core/notifications.py) : UNE issue GitHub automatique (étiquette « alerte-pipeline »), ouverte à la
première alerte, commentée quand la liste change, fermée quand tout est rentré dans l'ordre ; plus Slack / e-mail si
ces canaux sont déjà configurés. Jeton : GITHUB_TOKEN du workflow (permission issues: write), jamais dans le site.
Le crash complet d'un run (Python arrêté) est signalé par l'étape « Alerte si le run échoue » du workflow.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def evaluer(echecs: list[str] | None, echec_push: list[str] | None, sources_donnees: dict | None, rapport: dict | None) -> list[dict]:
    alertes = []
    for e in echecs or []:
        alertes.append({"type": "echec", "texte": f"Étape en échec : {e}"})
    for r in echec_push or []:
        alertes.append({"type": "echec", "texte": f"Publication non poussée : {r}"})
    so = sources_donnees or {}
    for s in so.get("alertes") or []:
        alertes.append({"type": "fraicheur", "texte": f"{s.get('nom')} : {s.get('texte')}"})
    for s in so.get("alertes_indicateurs") or []:
        alertes.append({"type": "fraicheur", "texte": f"{s.get('libelle')} : {s.get('texte')}"})
    eng = (((rapport or {}).get("synthese_globale") or {}).get("engrenages")) or {}
    if eng.get("statut") != "ok" and eng.get("quota_atteint"):
        alertes.append({"type": "quota", "texte": "Synthèse des 8 engrenages bloquée par le quota du modèle "
                                                  "(directions et titre en calcul Python)"})
    return alertes


def empreinte(alertes: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sorted(a["texte"] for a in alertes), ensure_ascii=False).encode()).hexdigest()[:16]


def ecrire(docs: Path, alertes: list[dict], maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    chemin = Path(docs) / "alertes.json"
    try:
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ancien = {}
    e = empreinte(alertes)
    donnees = {"maj": maintenant.isoformat(timespec="seconds"), "actives": alertes, "empreinte": e,
               "depuis": ancien.get("depuis") if ancien.get("actives") and alertes else (maintenant.isoformat(timespec="seconds") if alertes else None),
               "change": e != ancien.get("empreinte"),
               "note": "Alertes calculées en Python à la fin de chaque run. Le bandeau disparaît quand tout est rentré dans l'ordre."}
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    return donnees


def corps_issue(alertes: list[dict], url_site: str | None = None) -> str:
    lignes = ["Alertes de fin de run du pipeline FX (calcul Python) :", ""]
    lignes += [f"- **{ {'echec': 'Échec', 'fraicheur': 'Fraîcheur', 'quota': 'Quota'}.get(a['type'], a['type']) }** — {a['texte']}" for a in alertes]
    if url_site:
        lignes += ["", f"Page Santé : {url_site}#sante"]
    lignes += ["", "_Issue tenue à jour automatiquement : commentée quand la liste change, fermée quand tout est rentré dans l'ordre._"]
    return "\n".join(lignes)
