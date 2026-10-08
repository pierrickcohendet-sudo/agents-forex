"""Lecture de la page « mois » de ForexFactory (https://www.forexfactory.com/calendar?month=this).

Les exports officiels Fair Economy (JSON/XML/CSV/ICS, semaine en cours
seulement) n'ont PAS de valeur « réel » (vérifié le 2026-10-06 : champs title,
country, date, impact, forecast, previous). Seule la page web les expose : le
calendrier y est embarqué en JSON dans `window.calendarComponentStates[1]`
(champs actual / forecast / previous / revision + un `ebaseId` stable par type
d'événement). Ce module ne fait QUE parser ce JSON ; la requête HTTP passe par
core/scraping.py (robots.txt, pauses, cache, pas d'insistance après un 403).
"""
from __future__ import annotations

import json
import re

_MARQUEUR = "window.calendarComponentStates[1]"
_DEBUT_JOURS = re.compile(r"days:\s*")


def parser_page(html: str) -> list[dict]:
    """Retourne les événements de la page, normalisés. Lève ValueError si la
    structure attendue est introuvable (page de défi Cloudflare, refonte du
    site) — jamais une liste vide silencieuse."""
    debut = html.find(_MARQUEUR)
    if debut == -1:
        raise ValueError("calendarComponentStates introuvable dans la page "
                         "(blocage Cloudflare ou refonte du site ?)")
    corresp = _DEBUT_JOURS.search(html, debut)
    if not corresp:
        raise ValueError("liste « days » introuvable dans calendarComponentStates")
    try:
        jours, _ = json.JSONDecoder().raw_decode(html[corresp.end():])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON du calendrier illisible ({exc.msg})") from exc

    evenements = []
    for jour in jours:
        for e in jour.get("events", []):
            evenements.append({
                "id": e.get("id"),
                "ebase_id": e.get("ebaseId"),
                "devise": e.get("currency"),
                "nom": e.get("name"),
                "impact": e.get("impactName"),
                "dateline": e.get("dateline"),
                "reel": (e.get("actual") or "").strip() or None,
                "prevision": (e.get("forecast") or "").strip() or None,
                "precedent": (e.get("previous") or "").strip() or None,
                "revision": (e.get("revision") or "").strip() or None,
                "url": e.get("url"),
            })
    return evenements


# ----------------------------------------------------------------- collecte
import logging  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

log = logging.getLogger(__name__)

SITE = "forexfactory_mois"
_MOIS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def nom_mois(decalage: int, maintenant: datetime) -> str:
    """'this' / 'next' ou le nom explicite (ex. 'dec.2026') du mois courant + décalage."""
    if decalage == 0:
        return "this"
    if decalage == 1:
        return "next"
    m = maintenant.month - 1 + decalage
    return f"{_MOIS[m % 12]}.{maintenant.year + m // 12}"


def _lire_budget(chemin: Path, jour: str) -> dict:
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
        if brut.get("date") == jour:
            return {"horodatages": list(brut.get("horodatages", [])),
                    "ciblees": dict(brut.get("ciblees", {}))}
    except (OSError, json.JSONDecodeError):
        pass
    return {"horodatages": [], "ciblees": {}}


def _ecrire_budget(chemin: Path, jour: str, budget: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"date": jour, **budget}, indent=1), encoding="utf-8")


def collecte_due(horodatages: list[str], cfg_ff: dict, maintenant: datetime) -> tuple[bool, str]:
    """(due, raison). Un créneau (config : creneaux_utc) est dû dès que son
    heure est passée et qu'AUCUNE requête n'a eu lieu depuis ; jamais au-delà
    du plafond quotidien. Les passages horaires --completer l'évaluent donc à
    chaque fois : un cron manqué est rattrapé au passage suivant."""
    plafond = int(cfg_ff.get("plafond_requetes_par_jour", 2))
    if len(horodatages) >= plafond:
        return False, f"plafond de {plafond} requête(s)/jour atteint"
    passes = []
    for hhmm in cfg_ff.get("creneaux_utc", ["05:15"]):
        h, m = (int(x) for x in hhmm.split(":"))
        creneau = maintenant.replace(hour=h, minute=m, second=0, microsecond=0)
        if creneau <= maintenant:
            passes.append(creneau)
    if not passes:
        return False, "aucun créneau atteint aujourd'hui"
    dernier = max(passes)
    if any(datetime.fromisoformat(t) >= dernier for t in horodatages):
        return False, f"créneau {dernier:%H:%M} UTC déjà couvert"
    return True, f"créneau {dernier:%H:%M} UTC dû"


def _requete(cfg_tm: dict, client, mois: str, budget: dict, chemin: Path, jour: str,
             maintenant: datetime) -> dict:
    cfg_ff = cfg_tm["forexfactory"]
    url = cfg_ff["url"] if mois == "this" else cfg_ff["url_mois"].format(mois=mois)
    res = client.requete_directe(SITE, url)
    # La requête compte dans le budget même si elle échoue : pas d'insistance.
    budget["horodatages"].append(maintenant.isoformat(timespec="seconds"))
    _ecrire_budget(chemin, jour, budget)
    if res["contenu"] is None:
        return {"statut": "indisponible", "evenements": [], "note": res["note"]}
    try:
        return {"statut": "frais", "evenements": parser_page(res["contenu"]), "note": ""}
    except ValueError as exc:
        return {"statut": "indisponible", "evenements": [], "note": str(exc)}


def collecter(cfg_tm: dict, client, dossier_cache: str | Path, maintenant: datetime | None = None,
              cibles_fn=None) -> dict:
    """Page « mois en cours » si un créneau est dû OU si une publication
    importante vient de sortir (`cibles_fn(deja_tentees) -> [clés]`, mise à jour
    ciblée). Retourne {statut, evenements, note, declencheur, premier_du_jour}.
    statut : frais | non_due | indisponible. Budget : data/cache/forexfactory_requetes.json
    (committé pour survivre entre runs)."""
    maintenant = maintenant or datetime.now(timezone.utc)
    cfg_ff = cfg_tm["forexfactory"]
    chemin = Path(dossier_cache) / "forexfactory_requetes.json"
    jour = maintenant.date().isoformat()
    budget = _lire_budget(chemin, jour)
    plafond = int(cfg_ff.get("plafond_requetes_par_jour", 2))
    premier = not budget["horodatages"]
    due, raison = collecte_due(budget["horodatages"], cfg_ff, maintenant)
    declencheur = "creneau"
    if not due and len(budget["horodatages"]) < plafond and cibles_fn is not None:
        cibles = cibles_fn(budget["ciblees"])
        if cibles:
            due, declencheur = True, "ciblee"
            raison = f"mise à jour ciblée ({len(cibles)} publication(s) : {', '.join(c.split('@')[0] for c in cibles[:4])})"
            for c in cibles:
                budget["ciblees"][c] = budget["ciblees"].get(c, 0) + 1
    if not due:
        log.info("Tableau macro : page « mois » ForexFactory non interrogée (%s)", raison)
        return {"statut": "non_due", "evenements": [], "note": raison, "declencheur": None,
                "premier_du_jour": False}
    log.info("Tableau macro : requête page « mois » ForexFactory (%s ; %d/%d aujourd'hui)",
             raison, len(budget["horodatages"]) + 1, plafond)
    res = _requete(cfg_tm, client, "this", budget, chemin, jour, maintenant)
    return {**res, "declencheur": declencheur, "premier_du_jour": premier}


def collecter_mois_suivant(cfg_tm: dict, client, dossier_cache: str | Path, decalage: int,
                           maintenant: datetime | None = None) -> dict:
    """Mois suivant (decalage=1) ou d'après (2) : une requête, dans la limite du
    plafond quotidien commun."""
    maintenant = maintenant or datetime.now(timezone.utc)
    chemin = Path(dossier_cache) / "forexfactory_requetes.json"
    jour = maintenant.date().isoformat()
    budget = _lire_budget(chemin, jour)
    plafond = int(cfg_tm["forexfactory"].get("plafond_requetes_par_jour", 2))
    if len(budget["horodatages"]) >= plafond:
        return {"statut": "non_due", "evenements": [],
                "note": f"plafond de {plafond} requête(s)/jour atteint"}
    mois = nom_mois(decalage, maintenant)
    log.info("Tableau macro : requête page « %s » ForexFactory (%d/%d aujourd'hui)", mois,
             len(budget["horodatages"]) + 1, plafond)
    return _requete(cfg_tm, client, mois, budget, chemin, jour, maintenant)
