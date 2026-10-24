"""Agenda (lot V5, étape 6) : 7 prochains jours d'évènements et banques centrales des 9 devises. Calcul Python, sans LLM.

Sources déjà collectées (aucune requête de plus) :
- calendrier ForexFactory de la semaine (data/cache/scrape_forexfactory.json : heure, impact, précédent, consensus) ;
- magasin glissant des évènements publiés (data/cache/evenements_glissants.json : valeur publiée) ;
- registre macro (prochaine publication connue de chaque indicateur, au-delà de la semaine ForexFactory ; taux actuels).
Chaque ligne porte sa source et sa date ; une valeur absente est « n/d » avec la raison. Heure de Paris.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import registre_macro as rm, tableau_macro

log = logging.getLogger(__name__)

DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
PAYS = {"USD": "USD", "EUR": "EUR", "GBP": "GBP", "JPY": "JPY", "CHF": "CHF", "CAD": "CAD", "AUD": "AUD", "NZD": "NZD", "CNY": "CNY"}
BANQUES = {"USD": "Réserve fédérale (Fed)", "EUR": "Banque centrale européenne (BCE)", "GBP": "Banque d'Angleterre (BoE)",
           "JPY": "Banque du Japon (BoJ)", "CHF": "Banque nationale suisse (BNS)", "CAD": "Banque du Canada (BoC)",
           "AUD": "Banque de réserve d'Australie (RBA)", "NZD": "Banque de réserve de Nouvelle-Zélande (RBNZ)",
           "CNY": "Banque populaire de Chine (PBoC)"}
IMPACTS = {"high": "fort", "medium": "moyen", "low": "faible", "holiday": "férié"}
# Évènement -> engrenage concerné (dossier) ; mots-clés en anglais (titres ForexFactory)
ENGRENAGES = [(2, r"rate|monetary policy|press conference|fomc|minutes|refinancing|lpr"),
              (3, r"cpi|ppi|employment|non-farm|unemployment|gdp|pmi|retail|claims|wage|earnings|sentiment|confidence|ism"),
              (8, r"trade balance|crude|oil|current account")]
# Évènement USD -> indicateur du simulateur d'impact (#scenarios/i=…)
SIMULATEUR = [(r"federal funds rate", "fed"), (r"core cpi", "cpi_core_us"), (r"\bcpi\b", "cpi_us"), (r"gdp", "pib_us")]


def fuseau_paris():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Paris")
    except Exception:  # noqa: BLE001 — base tz absente : approximation (heure d'hiver UTC+1)
        return timezone(timedelta(hours=1))


def engrenage(titre: str) -> int | None:
    t = titre.lower()
    return next((n for n, motif in ENGRENAGES if re.search(motif, t)), None)


def simulateur(devise: str, titre: str) -> str | None:
    if devise != "USD":
        return None
    t = titre.lower()
    return next((i for motif, i in SIMULATEUR if re.search(motif, t)), None)


def _publiees(glissants: list[dict]) -> dict[tuple, str]:
    return {(e.get("devise"), e.get("evenement"), e.get("date")): e.get("reel") for e in glissants or [] if e.get("reel")}


def evenements(ff_brut: str | None, glissants: list[dict] | None, registre: dict | None, maintenant: datetime,
               jours: int = 7) -> list[dict]:
    """Évènements du moment présent (début du jour, Paris) à +jours, triés par heure."""
    paris = fuseau_paris()
    debut = maintenant.astimezone(paris).replace(hour=0, minute=0, second=0, microsecond=0)
    fin = debut + timedelta(days=jours)
    publiees = _publiees(glissants or [])
    sortie, vus = [], set()
    try:
        items = json.loads(ff_brut) if ff_brut else []
    except ValueError:
        items = []
    for it in items:
        devise = PAYS.get(str(it.get("country", "")).upper())
        if devise is None or not it.get("date"):
            continue
        try:
            quand = datetime.fromisoformat(it["date"])
        except ValueError:
            continue
        if not debut <= quand.astimezone(paris) < fin:
            continue
        titre = str(it.get("title", ""))[:150]
        cle = (devise, titre, quand.date().isoformat())
        vus.add((devise, titre.lower(), quand.astimezone(paris).date().isoformat()))
        reel = it.get("actual") or publiees.get(cle)
        sortie.append(_ligne(devise, titre, quand, str(it.get("impact", "")), it.get("previous") or None,
                             it.get("forecast") or None, reel, "ForexFactory (calendrier de la semaine)", paris))
    # Au-delà de la semaine ForexFactory : prochaine publication connue du registre (souvent la prochaine réunion)
    for cle_case, case in ((registre or {}).get("cases") or {}).items():
        prev = case.get("prevision") or {}
        if not prev.get("dateline"):
            continue
        quand = datetime.fromtimestamp(int(prev["dateline"]), tz=timezone.utc)
        if not debut <= quand.astimezone(paris) < fin:
            continue
        devise = case.get("devise") or cle_case.split("|")[-1]
        titre = prev.get("nom_ff") or case.get("indicateur")
        if (devise, str(titre).lower(), quand.astimezone(paris).date().isoformat()) in vus:
            continue
        actuel = case.get("actuel") or {}
        ligne = _ligne(devise, str(titre), quand, str(prev.get("impact") or ""),
                       None if actuel.get("origine") else actuel.get("valeur"), prev.get("valeur"), None,
                       "registre macro (ForexFactory, prochaine publication)", paris)
        if actuel.get("origine"):   # ex. USD : taux effectif FRED, pas la dernière décision publiée
            ligne["raison_precedent"] = f"valeur du registre = {actuel.get('source') or 'valeur de repli'}, pas la dernière publication"
        sortie.append(ligne)
    return sorted(sortie, key=lambda e: e["iso_utc"])


def _ligne(devise, titre, quand: datetime, impact, precedent, consensus, publie, source, paris) -> dict:
    local = quand.astimezone(paris)
    return {"iso_utc": quand.astimezone(timezone.utc).isoformat(timespec="minutes"), "date_paris": local.date().isoformat(),
            "heure_paris": local.strftime("%H:%M") if (local.hour, local.minute) != (0, 0) else "journée",
            "devise": devise, "evenement": titre, "impact": IMPACTS.get(impact.lower(), "n/d"),
            "precedent": precedent, "consensus": consensus, "publie": publie,
            "raison_consensus": None if consensus else "pas de consensus publié",
            "source": source, "engrenage": engrenage(titre), "simulateur": simulateur(devise, titre)}


def banques_centrales(registre: dict | None, config: dict | None, evts: list[dict]) -> list[dict]:
    infos = tableau_macro.infos_taux(registre or {}, DEVISES)
    manuelles = ((config or {}).get("agenda") or {}).get("reunions") or {}
    sortie = []
    for devise in DEVISES:
        case = ((registre or {}).get("cases") or {}).get(rm.cle("taux_directeur", devise)) or {}
        actuel = case.get("actuel") or {}
        valeur, borne = tableau_macro.lire_taux(actuel.get("valeur"))
        i = infos.get(devise) or {}
        reunions = []
        if i.get("prochaine"):
            reunions.append({"date": i["prochaine"][:10], "source": "registre macro (ForexFactory)"})
        for d in sorted(manuelles.get(devise) or []):
            if str(d) > date.today().isoformat() and all(r["date"] != str(d) for r in reunions):
                reunions.append({"date": str(d), "source": "calendrier officiel saisi dans config.yaml (agenda.reunions)"})
        reunions = sorted(reunions, key=lambda r: r["date"])[:3]
        sortie.append({"devise": devise, "banque": BANQUES[devise], "taux": valeur, "borne": borne,
                       "taux_texte": actuel.get("valeur"), "date_taux": actuel.get("date_pub"), "source_taux": actuel.get("source"),
                       "variation_pb": i.get("variation_pb"), "date_variation": i.get("date_decision") if i.get("variation_pb") is not None else None,
                       "raison_variation": i.get("raison_variation"), "prochaine": reunions[0]["date"] if reunions else None,
                       "reunions": reunions,
                       "raison_reunions": None if len(reunions) >= 3 else
                       "réunions suivantes non collectées automatiquement (calendrier officiel à saisir dans config.yaml, agenda.reunions)"})
    return sortie


def calculer(ff_brut: str | None, glissants: list[dict] | None, registre: dict | None, config: dict | None,
             maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    evts = evenements(ff_brut, glissants, registre, maintenant)
    paris = fuseau_paris()
    debut = maintenant.astimezone(paris).date()
    jours = []
    for k in range(7):
        d = (debut + timedelta(days=k)).isoformat()
        jours.append({"date": d, "evenements": [e for e in evts if e["date_paris"] == d]})
    return {"genere_le": maintenant.isoformat(timespec="seconds"), "fuseau": "Europe/Paris", "jours": jours,
            "n_evenements": len(evts), "banques_centrales": banques_centrales(registre, config, evts),
            "raison_vide": None if evts else "calendrier ForexFactory de la semaine non collecté et aucune publication prévue au registre",
            "note": "Valeur publiée dès qu'elle existe dans les données collectées. Aide à la décision, jamais un ordre."}


def prochain_rendez_vous(agenda_donnees: dict | None, impacts=("fort",)) -> dict | None:
    """Premier évènement à fort impact rattaché à un engrenage (cockpit : « peut faire basculer »)."""
    for j in (agenda_donnees or {}).get("jours") or []:
        for e in j["evenements"]:
            if e["impact"] in impacts and e.get("engrenage") and not e.get("publie"):
                return e
    return None


def lire_caches(racine: Path) -> tuple[str | None, list[dict]]:
    cache = Path(racine) / "data" / "cache"
    try:
        ff = json.loads((cache / "scrape_forexfactory.json").read_text(encoding="utf-8")).get("contenu")
    except (OSError, ValueError):
        ff = None
    try:
        glissants = json.loads((cache / "evenements_glissants.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        glissants = []
    return ff, glissants if isinstance(glissants, list) else []


def ecrire(racine: str | Path, registre: dict | None, config: dict) -> dict | None:
    try:
        ff, glissants = lire_caches(Path(racine))
        donnees = calculer(ff, glissants, registre, config)
        chemin = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data" / "agenda.json"
        chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("agenda.json non écrit : %s", exc)
        return None
