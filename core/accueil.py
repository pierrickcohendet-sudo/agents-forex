"""Page d'accueil « Aujourd'hui » (lot V5, étape 7-ter) : tableau de bord du jour, à lire en 30 secondes.

Fichier léger docs/data/accueil.json (quelques Ko) tiré de ce que le run a déjà calculé : en-tête du cockpit (thème,
direction, conviction), 3 signaux « au bord du seuil », évènements des 48 prochaines heures (le site garde les 24 h à
venir à l'heure de lecture), banques centrales pour le petit globe, fraîcheur des données. Calcul Python, sans LLM.
La page d'accueil ne charge ainsi ni dossiers.json (1 Mo) ni agenda.json.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

CHAMPS_EVT = ("iso_utc", "date_paris", "heure_paris", "devise", "evenement", "type", "impact", "points", "precedent",
              "consensus", "publie", "badge", "engrenage")


def calculer(dossiers_donnees: dict | None, agenda_donnees: dict | None, sources_donnees: dict | None,
             maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    cockpit = (dossiers_donnees or {}).get("cockpit") or {}
    entete = cockpit.get("entete") or {}
    limite = (maintenant + timedelta(hours=48)).isoformat(timespec="minutes")
    debut = (maintenant - timedelta(hours=2)).isoformat(timespec="minutes")
    evts = [{k: e.get(k) for k in CHAMPS_EVT}
            for j in (agenda_donnees or {}).get("jours") or [] for e in j.get("evenements") or []
            if debut <= e.get("iso_utc", "") <= limite and (e.get("impact") in ("fort", "moyen") or e.get("type") in ("Réunion BC", "Discours", "Conférence"))]
    so = sources_donnees or {}
    alertes = [*(so.get("alertes") or []), *(so.get("alertes_indicateurs") or [])]
    return {
        "genere_le": maintenant.isoformat(timespec="seconds"),
        "date_rapport": entete.get("date_rapport"),
        "theme": {k: entete.get(k) for k in ("titre", "titre_impose", "direction", "conviction", "alignes", "evaluables",
                                               "compte_matrice", "explication", "texte", "texte_source")},
        "au_bord": [{k: s.get(k) for k in ("id", "engrenage", "devise", "libelle", "texte_valeur", "distance_texte", "phrase",
                                            "etat", "date", "source")} for s in (cockpit.get("au_bord") or [])[:3]],
        "franchis": len(cockpit.get("franchis") or []),
        "evenements": sorted(evts, key=lambda e: e["iso_utc"]),
        "raison_evenements": None if agenda_donnees else "agenda.json non calculé",
        "banques": [{k: b.get(k) for k in ("devise", "court", "siege", "cette_semaine", "prochaine", "taux_texte", "badge")}
                    for b in (agenda_donnees or {}).get("banques_centrales") or []],
        "fraicheur": {"sources": len([s for s in so.get("sources") or [] if not s.get("retiree")]),
                      "vertes": sum(1 for s in so.get("sources") or [] if (s.get("fraicheur") or {}).get("etat") == "vert"),
                      "alertes": alertes[:6], "calcule_le": so.get("genere_le")},
        "note": "Tableau de bord du jour : faits datés et lectures historiques, jamais un ordre d'achat ou de vente."}


def ecrire(racine: str | Path, config: dict) -> dict | None:
    try:
        docs = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
        lire = lambda nom: json.loads((docs / nom).read_text(encoding="utf-8")) if (docs / nom).exists() else None
        donnees = calculer(lire("dossiers.json"), lire("agenda.json"), lire("sources.json"))
        (docs / "accueil.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("accueil.json non écrit : %s", exc)
        return None
