"""Planning des lectures de la page « mois » ForexFactory (lot V14, A1.5).

Les 6 lectures quotidiennes (plafond commun) ne sont plus à heures fixes : elles sont placées 5 à 10 minutes (7 par
défaut) après les publications FORTES du jour, heures prises dans l'agenda de la veille. Publications fortes à moins de
10 minutes d'écart : une seule lecture, après la dernière. S'il y a plus de groupes que de lectures, on garde ceux qui
comptent le plus de publications fortes ; s'il en reste, les publications moyennes complètent. Tant que la reprise de
l'historique (core/ff_historique.py) n'est pas finie, 2 requêtes sont réservées pour elle.

Fichier : data/cache/ff_planning.json {"jours": {"AAAA-MM-JJ": {"lectures": [{"heure_utc", "motif", "publications"}],
"calcule_le", "depuis_agenda_du", "reserve_historique"}}}. Le plan d'un jour n'est plus modifié une fois ce jour commencé.
Lu par agents/collecte_forexfactory_mois.py (créneaux du jour) et par outils/decider_mode.py (déclenchement des runs).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DECALAGE_MIN = 7          # minutes après la publication (fenêtre demandée : 5 à 10)
FUSION_MIN = 10           # publications à moins de 10 minutes d'écart : une seule lecture
PLAFOND = 6
RESERVE_HISTORIQUE = 2


def _groupes(evts: list[dict]) -> list[dict]:
    """Publications triées par heure -> groupes (écart < FUSION_MIN) : {debut, fin, evts}."""
    sortie = []
    for e in sorted(evts, key=lambda x: x["iso_utc"]):
        t = datetime.fromisoformat(e["iso_utc"])
        if sortie and (t - sortie[-1]["fin"]) < timedelta(minutes=FUSION_MIN):
            sortie[-1]["fin"] = t
            sortie[-1]["evts"].append(e)
        else:
            sortie.append({"debut": t, "fin": t, "evts": [e]})
    return sortie


def planifier(agenda: dict | None, jour: date, plafond: int = PLAFOND, reserve: int = 0,
              decalage: int = DECALAGE_MIN) -> dict:
    """Fonction pure. Lectures du jour `jour` (UTC) : au plus plafond − reserve, chacune `decalage` minutes après un
    groupe de publications fortes (puis moyennes s'il reste des lectures)."""
    evts = [e for j in (agenda or {}).get("jours") or [] for e in j.get("evenements") or []
            if str(e.get("iso_utc") or "")[:10] == jour.isoformat() and e.get("heure_connue", True)
            and e.get("type") not in ("Discours",)]
    n = max(0, plafond - reserve)
    choisis = []
    for impact in ("fort", "moyen"):
        place = n - len(choisis)
        if place <= 0:
            break
        gs = _groupes([e for e in evts if e.get("impact") == impact])
        # chevauchement avec un groupe déjà retenu : la lecture existante couvre ces publications
        gs = [g for g in gs if not any(abs((g["fin"] - c["fin"]).total_seconds()) < FUSION_MIN * 60 for c in choisis)]
        gs = sorted(gs, key=lambda g: (-len(g["evts"]), g["debut"]))[:place]
        for g in gs:
            g["impact"] = impact
        choisis += gs
    lectures = []
    for g in sorted(choisis, key=lambda g: g["fin"]):
        h = g["fin"] + timedelta(minutes=decalage)
        noms = [f"{e.get('devise')} {e.get('evenement_en') or e.get('evenement')}" for e in g["evts"]]
        lectures.append({"heure_utc": h.strftime("%H:%M"), "date_utc": h.date().isoformat(),
                         "motif": f"{len(g['evts'])} publication{'s' if len(g['evts']) > 1 else ''} "
                                  f"{'forte' if g['impact'] == 'fort' else 'moyenne'}{'s' if len(g['evts']) > 1 else ''} à "
                                  f"{g['fin'].strftime('%H:%M')} UTC + {decalage} min",
                         "publications": noms[:6]})
    return {"jour": jour.isoformat(), "lectures": lectures, "reserve_historique": reserve, "plafond": plafond,
            "regle": f"{decalage} min après les publications fortes du jour (puis moyennes), {plafond} requêtes par jour au plus"}


def lire(dossier_cache: Path) -> dict:
    try:
        d = json.loads((Path(dossier_cache) / "ff_planning.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def creneaux(dossier_cache: Path, jour: date) -> list[str] | None:
    """Heures (UTC, « HH:MM ») des lectures prévues pour `jour` ; None si aucun plan (repli sur config.yaml)."""
    p = (lire(dossier_cache).get("jours") or {}).get(jour.isoformat())
    if p is None:
        return None
    return [x["heure_utc"] for x in p.get("lectures") or [] if x.get("date_utc", jour.isoformat()) == jour.isoformat()]


def mettre_a_jour(dossier_cache: Path, agenda: dict | None, maintenant: datetime | None = None, plafond: int = PLAFOND,
                  reserve: int = 0) -> dict:
    """Plan de demain (UTC) recalculé depuis l'agenda du jour ; plan d'aujourd'hui créé s'il manque (jamais modifié
    ensuite). Garde 7 jours. Ne lève jamais."""
    maintenant = maintenant or datetime.now(timezone.utc)
    d = lire(dossier_cache)
    jours = d.setdefault("jours", {})
    auj, dem = maintenant.date(), maintenant.date() + timedelta(days=1)
    try:
        if auj.isoformat() not in jours:
            jours[auj.isoformat()] = {**planifier(agenda, auj, plafond, reserve), "calcule_le": maintenant.isoformat(timespec="seconds"),
                                      "depuis_agenda_du": (agenda or {}).get("genere_le"), "note": "plan créé le jour même (pas de plan la veille)"}
        jours[dem.isoformat()] = {**planifier(agenda, dem, plafond, reserve), "calcule_le": maintenant.isoformat(timespec="seconds"),
                                  "depuis_agenda_du": (agenda or {}).get("genere_le")}
        for k in sorted(jours)[:-7]:
            jours.pop(k, None)
        (Path(dossier_cache) / "ff_planning.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return d
