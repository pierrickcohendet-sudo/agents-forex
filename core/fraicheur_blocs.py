"""Points de fraîcheur des blocs du site (lot V8) -> docs/data/fraicheur.json. Règle calculée ici, le site affiche le point.

Vert : bloc mis à jour il y a moins de 2 h, ou données dans la fréquence normale de leur série (sources.json) ;
orange : en retard sur cette fréquence ; rouge : plus de 5 jours ouvrés depuis la dernière mise à jour ou donnée.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SEUIL_HEURES = 2
SEUIL_ROUGE_JOURS_OUVRES = 5
# Bloc du site -> (fichier, champ d'horodatage, sources de sources.json dont dépend la fraîcheur des données)
BLOCS = {
    "briefing": ("briefing", "genere_le", ["twelve_data", "ff_mois"]),
    "rapport": ("rapport_jour", "genere_le", ["fred", "twelve_data", "ff_mois"]),
    "point_marche": ("rapport_jour", "genere_le", ["fred", "twelve_data"]),
    "agenda": ("agenda", "genere_le", ["ff_mois", "ff_flux"]),
    "tableau_macro": ("tableau_macro", "maj", ["ff_mois", "fred"]),
    "profil": ("profil_devises", "genere_le", ["twelve_data", "fred"]),
    "engrenages": ("dossiers", "genere_le", ["fred", "cftc", "eia"]),
    "cours": ("cours", "genere_le", ["twelve_data", "fed_h10"]),
    "force": ("force_devises", "genere_le", ["twelve_data"]),
    "paires": ("paires", "genere_le", ["twelve_data"]),
    "seance": ("seance", "maj", ["twelve_data"]),
    "marche": ("marche", "maj", ["fred"]),
}


def jours_ouvres(debut: date, fin: date) -> int:
    n, d = 0, debut
    while d < fin:
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


def etat_bloc(maj: datetime | None, sources: list[dict], maintenant: datetime) -> dict:
    """{etat, texte} selon la règle du module (fonction pure, testée)."""
    if maj is None:
        return {"etat": "rouge", "texte": "date de mise à jour inconnue"}
    age_h = (maintenant - maj).total_seconds() / 3600
    retard = [s for s in sources if (s.get("fraicheur") or {}).get("etat") in ("orange", "rouge")]
    ouvres = jours_ouvres(maj.date(), maintenant.date())
    vieilles = [s for s in sources if s.get("derniere_donnee")
                and jours_ouvres(date.fromisoformat(s["derniere_donnee"][:10]), maintenant.date()) > SEUIL_ROUGE_JOURS_OUVRES
                and (s.get("fraicheur") or {}).get("etat") in ("orange", "rouge")]
    quand = maj.astimezone(timezone.utc).strftime("%d/%m %H:%M UTC")
    if ouvres > SEUIL_ROUGE_JOURS_OUVRES or vieilles:
        return {"etat": "rouge", "texte": f"mis à jour le {quand} : plus de {SEUIL_ROUGE_JOURS_OUVRES} jours ouvrés de retard"
                + (f" ({', '.join(s['nom'] for s in vieilles)})" if vieilles else "")}
    if age_h < SEUIL_HEURES or not retard:
        return {"etat": "vert", "texte": f"mis à jour le {quand}" + ("" if age_h < SEUIL_HEURES else " · données dans leur fréquence normale")}
    return {"etat": "orange", "texte": f"mis à jour le {quand} · en retard : "
            + ", ".join(f"{s['nom']} ({(s.get('fraicheur') or {}).get('texte')})" for s in retard)}


def _horodatage(v) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def ecrire(racine: str | Path, config: dict, maintenant: datetime | None = None) -> dict | None:
    try:
        maintenant = maintenant or datetime.now(timezone.utc)
        docs = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
        lire = lambda n: json.loads((docs / f"{n}.json").read_text(encoding="utf-8"))   # noqa: E731
        try:
            sources = {s["id"]: s for s in lire("sources").get("sources") or [] if not s.get("retiree")}
        except (OSError, ValueError):
            sources = {}
        blocs = {}
        for bloc, (fichier, champ, ids) in BLOCS.items():
            try:
                maj = _horodatage(lire(fichier).get(champ))
            except (OSError, ValueError):
                blocs[bloc] = {"etat": "rouge", "texte": f"{fichier}.json absent", "maj": None}
                continue
            blocs[bloc] = {**etat_bloc(maj, [sources[i] for i in ids if i in sources], maintenant),
                           "maj": maj.isoformat() if maj else None}
        donnees = {"genere_le": maintenant.isoformat(timespec="seconds"), "blocs": blocs,
                   "regle": "vert : moins de 2 h ou dans la fréquence normale de la série ; orange : en retard ; "
                            "rouge : plus de 5 jours ouvrés (fréquences de sources.json)"}
        (docs / "fraicheur.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("fraicheur.json non écrit : %s", exc)
        return None
