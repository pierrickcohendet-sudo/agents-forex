"""Alertes sur le téléphone (lot V8) avec ntfy (service libre et gratuit, applications iPhone et Android).

Trois déclencheurs, chacun envoyé une seule fois (mémoire data/cache/ntfy_envoyes.json, 7 jours) :
- seuils franchis (cockpit des engrenages) : un message groupé pour les nouveaux franchissements du jour ;
- publication à fort impact qui s'écarte du consensus de plus de 2 σ (Agenda, écart calculé en Python) ;
- 15 minutes avant chaque événement à fort impact : envoyé au run horaire le plus proche qui précède l'événement.
Le nom du canal est le secret GitHub NTFY_TOPIC : il n'apparaît jamais dans le site ni dans les journaux du run.
Un envoi en échec ne fait jamais échouer le run : une ligne dans le récapitulatif.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

SERVEUR = "https://ntfy.sh"
SEUIL_Z = 2.0
FENETRE_AVANT_MIN = 75   # runs horaires : l'événement des 75 prochaines minutes est annoncé au run qui le précède
GARDE_JOURS = 7
MEMOIRE = Path("data") / "cache" / "ntfy_envoyes.json"


def _ts(iso) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(iso))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def messages(dossiers: dict | None, agenda: dict | None, maintenant: datetime) -> list[dict]:
    """Messages candidats {cle(s), titre, texte, priorite, tags} — fonction pure (testée), sans dédoublonnage."""
    sortie = []
    jour = maintenant.date().isoformat()
    franchis = ((dossiers or {}).get("cockpit") or {}).get("franchis") or []
    if franchis:
        sortie.append({"cles": [f"seuil:{jour}:{x.get('id')}" for x in franchis], "titre": "Seuils franchis",
                       "lignes": {f"seuil:{jour}:{x.get('id')}": f"Engrenage {x.get('engrenage')} · {x.get('phrase') or x.get('libelle')}"
                                  for x in franchis},
                       "priorite": "default", "tags": "chart_with_upwards_trend"})
    evts = [e for j in (agenda or {}).get("jours") or [] for e in j.get("evenements") or []]
    for e in evts:
        z = (e.get("ecart") or {}).get("z")
        if e.get("impact") == "fort" and e.get("publie") and z is not None and abs(z) > SEUIL_Z:
            cle = f"publication:{e.get('iso_utc')}:{e.get('devise')}:{e.get('evenement')}"
            sortie.append({"cles": [cle], "titre": f"{e.get('devise')} : surprise de {z:+.1f} σ".replace("-", "−").replace(".", ","),
                           "lignes": {cle: f"{e.get('evenement')} : publié {e.get('publie')} contre {e.get('consensus')} attendu "
                                           f"({(e.get('ecart') or {}).get('texte') or ''})"},
                           "priorite": "high", "tags": "warning"})
    a_venir = {}
    for e in evts:
        t = _ts(e.get("iso_utc"))
        if e.get("impact") == "fort" and e.get("heure_connue", True) and t and maintenant < t <= maintenant + timedelta(minutes=FENETRE_AVANT_MIN):
            a_venir.setdefault(e["iso_utc"], []).append(e)
    for iso, groupe in sorted(a_venir.items()):
        t = _ts(iso)
        minutes = round((t - maintenant).total_seconds() / 60)
        lignes = {f"avant:{iso}:{e.get('devise')}:{e.get('evenement')}": f"{e.get('devise')} · {e.get('evenement')}"
                  + (f" (attendu {e.get('consensus')})" if e.get("consensus") else "") for e in groupe}
        sortie.append({"cles": list(lignes), "titre": f"À {groupe[0].get('heure_paris')} (dans {minutes} min) : publication à fort impact",
                       "lignes": lignes, "priorite": "high", "tags": "alarm_clock"})
    return sortie


def a_envoyer(candidats: list[dict], deja: dict) -> list[dict]:
    """Ne garde que les lignes jamais envoyées ; un message sans ligne nouvelle disparaît (dédoublonnage)."""
    sortie = []
    for m in candidats:
        nouvelles = {c: t for c, t in m["lignes"].items() if c not in deja}
        if nouvelles:
            sortie.append({**m, "cles": list(nouvelles), "texte": "\n".join(nouvelles.values())})
    return sortie


def _lire_memoire(racine: Path) -> dict:
    try:
        return json.loads((racine / MEMOIRE).read_text(encoding="utf-8")).get("envoyes") or {}
    except (OSError, ValueError):
        return {}


def _sauver_memoire(racine: Path, envoyes: dict, maintenant: datetime) -> None:
    limite = (maintenant - timedelta(days=GARDE_JOURS)).isoformat()
    garde = {k: v for k, v in envoyes.items() if v >= limite}
    (racine / MEMOIRE).parent.mkdir(parents=True, exist_ok=True)
    (racine / MEMOIRE).write_text(json.dumps({"envoyes": garde}, ensure_ascii=False, indent=1), encoding="utf-8")


def envoyer(sujet: str, m: dict) -> None:
    """POST https://ntfy.sh/<canal>. Le canal n'entre dans aucun message d'erreur (exception neutre)."""
    try:
        rep = requests.post(f"{SERVEUR}/{sujet}", data=m["texte"].encode("utf-8"), timeout=20,
                            headers={"Title": m["titre"].encode("utf-8"), "Priority": m["priorite"], "Tags": m["tags"]})
    except requests.RequestException as exc:
        raise RuntimeError(f"réseau ({type(exc).__name__})") from None
    if rep.status_code >= 300:
        raise RuntimeError(f"HTTP {rep.status_code}")


def executer(racine: str | Path, config: dict, maintenant: datetime | None = None) -> dict:
    racine = Path(racine)
    maintenant = maintenant or datetime.now(timezone.utc)
    sujet = os.environ.get("NTFY_TOPIC", "").strip()
    docs = racine / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
    lire = lambda n: json.loads((docs / f"{n}.json").read_text(encoding="utf-8"))   # noqa: E731
    try:
        dossiers, agenda = lire("dossiers"), lire("agenda")
    except (OSError, ValueError) as exc:
        return {"envoyes": 0, "ligne": f"Alertes téléphone : données absentes ({type(exc).__name__})"}
    deja = _lire_memoire(racine)
    liste = a_envoyer(messages(dossiers, agenda, maintenant), deja)
    if not liste:
        return {"envoyes": 0, "ligne": None}
    if not sujet:
        return {"envoyes": 0, "ligne": f"Alertes téléphone : {len(liste)} message(s) non envoyé(s) — secret NTFY_TOPIC absent"}
    ok, erreurs = 0, []
    for m in liste:
        try:
            envoyer(sujet, m)
            ok += 1
            for c in m["cles"]:
                deja[c] = maintenant.isoformat(timespec="seconds")
        except RuntimeError as exc:
            erreurs.append(str(exc))
    _sauver_memoire(racine, deja, maintenant)
    ligne = f"Alertes téléphone : {ok} envoyée(s)" + (f", {len(erreurs)} en échec ({'; '.join(sorted(set(erreurs)))})" if erreurs else "")
    log.info(ligne)
    return {"envoyes": ok, "echecs": len(erreurs), "ligne": ligne}
