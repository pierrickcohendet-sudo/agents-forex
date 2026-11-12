"""Archive des publications (lot V9, A1) : chaque « publié » est gardé dès sa sortie, avec le réel, le consensus, le
précédent, la révision, l'heure et la source -> data/cache/publications_archive.json.

Pourquoi : le flux hebdomadaire de ForexFactory ne contient pas le réel et repart du lundi ; le 09/11, le NFP du vendredi
06/11 (+165K contre +65K attendu) n'apparaissait donc nulle part. Sources fusionnées, sans requête de plus :
1. l'Agenda du run (docs/data/agenda.json) : heures exactes, noms français, statuts ;
2. l'archive de la page « mois » de ForexFactory (data/archives/publications.json), déjà lue pour le tableau macro ;
3. le BLS (rapport sur l'emploi détaillé, core/bls.py) pour les révisions du NFP.
« Publié hier » devient « dernière séance ouvrée » : le vendredi quand on est lundi.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

RACINE = Path(__file__).resolve().parents[1]
CHEMIN = RACINE / "data" / "cache" / "publications_archive.json"
JOURS_GARDES = 120
IMPACTS = {"high": "fort", "medium": "moyen", "low": "faible", "fort": "fort", "moyen": "moyen", "faible": "faible"}
MOTIF_DECISION = (r"(funds|bank|cash|policy|refinancing|overnight|interest|deposit) rate|rate (statement|decision)|deposit facility|"
                  r"rate votes|monetary policy statement")
RE_BC = re.compile(MOTIF_DECISION, re.I)


def derniere_seance_ouvree(aujourd: date) -> date:
    """Jour ouvré précédent : lundi -> vendredi, mardi -> lundi (week-ends sautés)."""
    j = aujourd - timedelta(days=1)
    while j.weekday() >= 5:
        j -= timedelta(days=1)
    return j


def _lire(chemin: Path) -> dict:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cle(jour: str, devise: str, nom_en: str) -> str:
    return f"{jour}|{devise}|{(nom_en or '').strip().lower()}"


def depuis_agenda(agenda: dict | None) -> list[dict]:
    """Évènements publiés de l'Agenda (heure exacte, nom français, source du champ « publié »)."""
    sortie = []
    for j in (agenda or {}).get("jours") or []:
        for e in j.get("evenements") or []:
            if not e.get("publie") or not e.get("date_paris"):
                continue
            sortie.append({"date": e["date_paris"], "heure_paris": e.get("heure_paris"), "iso_utc": e.get("iso_utc"),
                           "devise": e.get("devise"), "evenement": e.get("evenement"), "evenement_en": e.get("evenement_en") or e.get("evenement"),
                           "type": e.get("type"), "impact": IMPACTS.get(str(e.get("impact") or "").lower(), e.get("impact")),
                           "reel": e.get("publie"), "consensus": e.get("consensus"), "precedent": e.get("precedent"),
                           "revision": e.get("revision"), "ecart": e.get("ecart"), "statut": (e.get("statuts") or {}).get("publie"),
                           "source": (e.get("sources_champs") or {}).get("publie") or e.get("source") or "Agenda (ForexFactory)"})
    return sortie


def _paris(ts: int) -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(ZoneInfo("Europe/Paris"))


def depuis_calendrier_mois(mois: dict | None, traduire=None) -> list[dict]:
    """Page « mois » de ForexFactory déjà lue (cache de -14 à +60 jours) : réel, prévision, précédent, révision, impact
    et heure exacte (dateline). Aucune requête de plus."""
    sortie = []
    for e in (mois or {}).get("evenements") or []:
        if not e.get("reel") or not e.get("dateline"):
            continue
        quand, nom = _paris(e["dateline"]), e.get("nom") or ""
        sortie.append({"date": quand.date().isoformat(), "heure_paris": quand.strftime("%H:%M"),
                       "iso_utc": datetime.fromtimestamp(int(e["dateline"]), tz=timezone.utc).isoformat(timespec="minutes"),
                       "devise": e.get("devise"), "evenement": traduire(nom)[0] if traduire else nom, "evenement_en": nom,
                       "type": "Réunion BC" if RE_BC.search(nom) else "Chiffre", "impact": IMPACTS.get(str(e.get("impact") or "").lower()),
                       "reel": e.get("reel"), "consensus": e.get("prevision"), "precedent": e.get("precedent"),
                       "revision": e.get("revision"), "ecart": None, "statut": "confirmé",
                       "source": "ForexFactory, page « mois » (extraction de page déjà lue pour le tableau macro)"})
    return sortie


def depuis_ff_mois(archive_ff: dict | None, traduire=None, impacts_connus: dict | None = None) -> list[dict]:
    """Archive longue de la page « mois » (réel, prévision, précédent ; sans heure). L'impact vient du cache du mois
    (même nom d'indicateur), sinon « moyen » : l'archive ne garde que les impacts forts et moyens."""
    sortie = []
    for p in ((archive_ff or {}).get("publications") or {}).values():
        if not p.get("reel") or not p.get("date"):
            continue
        nom = p.get("nom") or ""
        impact = IMPACTS.get(str(p.get("impact") or "").lower()) or (impacts_connus or {}).get((p.get("devise"), nom)) or "moyen"
        sortie.append({"date": p["date"], "heure_paris": None, "iso_utc": None, "devise": p.get("devise"),
                       "evenement": traduire(nom)[0] if traduire else nom, "evenement_en": nom,
                       "type": "Réunion BC" if RE_BC.search(nom) else "Chiffre", "impact": impact, "reel": p.get("reel"),
                       "consensus": p.get("prevision"), "precedent": p.get("precedent"), "revision": p.get("revision"),
                       "ecart": None, "statut": "confirmé", "source": "ForexFactory, page « mois » (archive des publications)"})
    return sortie


def fusionner(ancien: dict | None, entrees: list[dict], aujourd: date, maintenant: datetime | None = None) -> dict:
    """Ajoute les nouvelles publications ; une entrée déjà archivée garde son réel (premier publié), complète ses champs
    vides (heure, consensus, nom français) et note une révision si la source en donne une. Garde 120 jours."""
    maintenant = maintenant or datetime.now(timezone.utc)
    pubs = dict((ancien or {}).get("publications") or {})
    limite = (aujourd - timedelta(days=JOURS_GARDES)).isoformat()
    for e in entrees:
        if not e.get("devise") or not e.get("date"):
            continue
        k = cle(e["date"], e["devise"], e.get("evenement_en"))
        a = pubs.get(k)
        if a is None:
            pubs[k] = {**{x: v for x, v in e.items() if v is not None}, "archive_le": maintenant.isoformat(timespec="minutes")}
            continue
        meilleure = e.get("rang", 9) <= a.get("rang", 9)   # Agenda (0) > page « mois » récente (1) > archive longue (2)
        for champ, v in e.items():
            if v is None or champ == "reel":
                continue
            if a.get(champ) in (None, "") or (meilleure and champ in ("impact", "heure_paris", "iso_utc", "evenement", "type", "ecart", "statut", "rang")):
                a[champ] = v
        # le réel gardé est le premier publié ; une valeur différente ensuite est une révision de la source
        if e.get("reel") and a.get("reel") and str(e["reel"]) != str(a["reel"]) and not a.get("reel_revise"):
            a["reel_revise"], a["revise_le"] = e["reel"], maintenant.date().isoformat()
    pubs = {k: v for k, v in pubs.items() if v.get("date", "") >= limite}
    return {"maj": maintenant.isoformat(timespec="minutes"), "note": __doc__.split("\n\n")[0].replace("\n", " "),
            "publications": dict(sorted(pubs.items()))}


def mettre_a_jour(agenda: dict | None, racine: Path | None = None, aujourd: date | None = None,
                  maintenant: datetime | None = None, chemin: Path | None = None) -> dict:
    """Appelé après chaque écriture de l'Agenda (run complet et passages horaires). Ne lève jamais."""
    racine = Path(racine or RACINE)
    chemin = Path(chemin or racine / "data" / "cache" / "publications_archive.json")
    aujourd = aujourd or datetime.now(timezone.utc).date()
    try:
        traduire = None
        try:
            import yaml
            from core.agenda import Traducteur
            cfg = yaml.safe_load((racine / "config.yaml").read_text(encoding="utf-8")) or {}
            traduire = Traducteur(cfg.get("agenda") or {}).traduire
        except Exception:  # noqa: BLE001
            traduire = None
        mois = _lire(racine / "data" / "cache" / "calendrier_mois.json")
        connus = {(e.get("devise"), e.get("nom")): IMPACTS.get(str(e.get("impact") or "").lower()) for e in mois.get("evenements") or []}
        entrees = ([{**e, "rang": 0} for e in depuis_agenda(agenda)] + [{**e, "rang": 1} for e in depuis_calendrier_mois(mois, traduire)]
                   + [{**e, "rang": 2} for e in depuis_ff_mois(_lire(racine / "data" / "archives" / "publications.json"), traduire, connus)])
        archive = fusionner(_lire(chemin), entrees, aujourd, maintenant)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(archive, ensure_ascii=False, indent=0), encoding="utf-8")
        return archive
    except Exception as exc:  # noqa: BLE001
        log.error("publications_archive.json non écrit : %s", exc)
        return _lire(chemin)


def charger(chemin: Path | None = None) -> dict:
    return _lire(Path(chemin or CHEMIN))


POIDS = {"fort": 3, "moyen": 2, "faible": 1}
# Familles d'indicateurs, de la plus suivie par le marché des changes à la moins suivie (ordre des publications du jour)
FAMILLES = [("decision", MOTIF_DECISION), ("emploi", r"non-farm|nonfarm|employment change"),
            ("inflation", r"\bcpi\b|pce|consumer price|inflation"), ("pib", r"\bgdp\b"), ("emploi", r"unemployment|claimant|earnings|wage"),
            ("pmi", r"pmi|ism"), ("ventes", r"retail sales"), ("autre", r".")]


def famille(nom_en: str) -> tuple[int, str]:
    for i, (f, motif) in enumerate(FAMILLES):
        if re.search(motif, nom_en or "", re.I):
            return i, f
    return len(FAMILLES), "autre"


def importance(p: dict) -> tuple:
    return (-POIDS.get(p.get("impact"), 0), famille(p.get("evenement_en"))[0], p.get("devise") != "USD", p.get("heure_paris") or "99")


def publications_du(archive: dict | None, jour: str, impacts=("fort", "moyen")) -> list[dict]:
    """Publications d'un jour, les plus importantes d'abord : impact, famille (décision, NFP, inflation, PIB…), USD."""
    l = [p for p in ((archive or {}).get("publications") or {}).values() if p.get("date") == jour and p.get("impact") in impacts]
    return sorted(l, key=importance)


def derniere_seance(archive: dict | None, aujourd: date) -> tuple[str, list[dict]]:
    """(jour, publications) de la dernière séance ouvrée ; si elle est vide, la séance ouvrée d'avant (jusqu'à 5)."""
    j = derniere_seance_ouvree(aujourd)
    for _ in range(5):
        l = publications_du(archive, j.isoformat())
        if l:
            return j.isoformat(), l
        j = derniere_seance_ouvree(j)
    return derniere_seance_ouvree(aujourd).isoformat(), []
