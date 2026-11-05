"""Bougies Twelve Data de la page Paire (lot V8.2 ; lot V5 pour les 6 premières paires).

- Run complet du matin (« matin ») : 30 min, 4 h et 1 jour des paires suivies, puis 4 h et 1 jour des majeures, puis
  des croisées : les 36 paires une fois par jour.
- Passage horaire (« heure ») : 30 min des paires suivies (10 au plus, config.yaml > journal.mes_paires).
- Passage de 13:15 Paris (« midi ») : 4 h et 1 jour des 36 paires une seconde fois, si le budget le permet.

Budget (plan gratuit : 800 crédits par jour, 8 par minute ; 1 crédit par requête) : objectif de 500 crédits par jour
au plus (plan_journee() le calcule, testé). Chaque requête passe par core/quota_twelve.consommer (plafond du jour et
pause automatique au-delà de 8 crédits par minute). Avant chaque requête, on garde la réserve des passages horaires
restants (séance + 30 min) ; si le budget manque, les paires restantes gardent leurs bougies de la veille (le site
affiche « bougies du JJ/MM »). Une paire ou une unité en échec n'affecte qu'elle ; aucune valeur inventée.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from core import outils, paires
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

URL = "https://api.twelvedata.com/time_series"
UNITES = {"30min": ("30min", 150), "4h": ("4h", 180), "1j": ("1day", 260)}
OBJECTIF_JOUR = 500                 # crédits Twelve Data visés par jour (plafond du plan : 800)
HEURES_COMPLEMENTS = range(9, 22)   # passages horaires 09:15 -> 21:15 UTC (.github/workflows/rapport.yml)
SEANCE_PAR_PASSAGE = 8              # cotations /quote des 8 paires face au dollar (core/seance.py)
TECHNIQUE_JOUR = 16                 # agents/collecte_technique.py (8 paires × 2 unités, run complet)
HISTORIQUES_JOUR = 8                # agents/collecte_historiques.py (TLT + 7 symboles, run complet)
MAX_SUIVIES = 10


def groupes(config: dict) -> dict:
    """Paires suivies (config), puis majeures (avec l'USD), puis croisées : l'ordre de priorité du budget."""
    suivies = paires.mes_paires(config)[:MAX_SUIVIES]
    autres = [p for p in outils.paires() if p not in suivies]
    return {"suivies": suivies, "majeures": [p for p in autres if "USD" in p.split("/")],
            "croisees": [p for p in autres if "USD" not in p.split("/")]}


def plan_journee(config: dict) -> dict:
    """Coût d'une journée complète en crédits, par module (objectif : 500 au plus)."""
    g = groupes(config)
    n36, ns = sum(len(v) for v in g.values()), len(g["suivies"])
    passages = len(HEURES_COMPLEMENTS)
    modules = {"seance": SEANCE_PAR_PASSAGE * (passages + 1),          # passages horaires + run complet
               "chandeliers_matin": 2 * n36 + ns,                      # 4 h et 1 j des 36 paires + 30 min des suivies
               "chandeliers_30min_horaires": ns * passages,
               "chandeliers_midi": 2 * n36,                            # seconde collecte 4 h et 1 j (13:15 Paris)
               "technique": TECHNIQUE_JOUR, "historiques": HISTORIQUES_JOUR}
    return {"modules": modules, "total": sum(modules.values()), "objectif": OBJECTIF_JOUR, "plafond": 800}


def reserve_restante(config: dict, maintenant: datetime) -> int:
    """Crédits à garder pour les passages horaires encore à venir aujourd'hui (séance + 30 min des suivies)."""
    restants = sum(1 for h in HEURES_COMPLEMENTS if h > maintenant.hour)
    return restants * (SEANCE_PAR_PASSAGE + len(groupes(config)["suivies"]))


def taches(mode: str, config: dict) -> list[tuple[str, str]]:
    g = groupes(config)
    if mode == "heure":
        return [(p, "30min") for p in g["suivies"]]
    t = [(p, u) for p in g["suivies"] for u in (("30min", "4h", "1j") if mode == "matin" else ("4h", "1j"))]
    return t + [(p, u) for grp in ("majeures", "croisees") for p in g[grp] for u in ("4h", "1j")]


def heure_paris(maintenant: datetime) -> int:
    from core.agenda import fuseau
    return maintenant.astimezone(fuseau("Europe/Paris")).hour


def _bougies(paire: str, intervalle: str, taille: int, cle: str, consommer) -> list[list]:
    consommer(1, "chandeliers")
    rep = requests.get(URL, params={"symbol": paire, "interval": intervalle, "outputsize": taille, "apikey": cle,
                                    "timezone": "UTC"}, timeout=60)
    rep.raise_for_status()
    d = rep.json()
    if d.get("status") != "ok":
        raise RuntimeError(f"Twelve Data {paire} {intervalle} : {d.get('message', 'réponse invalide')}")
    sortie = []
    for v in reversed(d.get("values") or []):
        try:
            sortie.append([v["datetime"], float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"])])
        except (KeyError, TypeError, ValueError):
            continue
    return sortie


def _deja_fait(entree: dict | None, mode: str, unite: str, jour: str, maintenant: datetime, midi: bool) -> bool:
    """Une unité est à jour si elle a été collectée aujourd'hui (et, pour les 30 min horaires, dans l'heure UTC ;
    pour la collecte de midi, après 11:00 UTC)."""
    t = (entree or {}).get("collecte_le")
    if not t or not (entree or {}).get("bougies"):
        return False
    quand = datetime.fromisoformat(t)
    if quand.date().isoformat() != jour:
        return False
    if unite == "30min" and mode == "heure":
        return quand.hour == maintenant.hour
    if midi:
        return quand.hour >= 11
    return True


def collecter(config: dict, racine: str | Path, cle: str | None = None, mode: str = "matin",
              maintenant: datetime | None = None, consommer=None, etat_quota=None) -> dict:
    """mode : « matin » (run complet), « heure » (passage horaire ; ajoute la collecte de midi à 13 h Paris)."""
    from core import quota_twelve
    consommer = consommer or quota_twelve.consommer
    etat_quota = etat_quota or quota_twelve.etat
    maintenant = maintenant or datetime.now(timezone.utc)
    jour = maintenant.date().isoformat()
    chemin = Path(racine) / "data" / "cache" / "intraday.json"
    try:
        cache = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    cache.setdefault("paires", {})
    cache["source"] = "Twelve Data (time_series, heures UTC)"
    cle = cle if cle is not None else os.environ.get("TWELVE_DATA_API_KEY", "").strip()
    if not cle:
        cache["raison"] = "TWELVE_DATA_API_KEY absente : bougies non collectées"
        return cache
    cache.pop("raison", None)
    lots = [(mode, t, False) for t in taches(mode, config)]
    midi = mode == "heure" and heure_paris(maintenant) >= 13 and cache.get("midi") != jour
    if midi:
        lots += [("midi", t, True) for t in taches("midi", config)]
    reserve = reserve_restante(config, maintenant)
    faites, sautees, erreurs = 0, [], []
    for m, (p, u), est_midi in lots:
        entree = cache["paires"].get(p, {}).get(u)
        if _deja_fait(entree, m, u, jour, maintenant, est_midi):
            continue
        if etat_quota()["credits"] + 1 > OBJECTIF_JOUR - reserve:
            sautees.append(f"{p} {u}")
            continue
        intervalle, taille = UNITES[u]
        try:
            b = _bougies(p, intervalle, taille, cle, consommer)
            if not b:
                raise RuntimeError("aucune bougie dans la réponse")
            cache["paires"].setdefault(p, {})[u] = {"bougies": b, "source": cache["source"],
                                                    "collecte_le": maintenant.isoformat(timespec="seconds")}
            faites += 1
        except Exception as exc:  # noqa: BLE001 — une unité en échec n'affecte qu'elle (bougies précédentes gardées)
            if isinstance(exc, quota_twelve.QuotaTwelveAtteint):
                sautees.append(f"{p} {u}")
                continue
            raison = masquer_secrets(str(exc))[:160]
            garde = dict(entree or {"bougies": []})
            garde["echec"] = raison
            cache["paires"].setdefault(p, {})[u] = garde
            erreurs.append(f"{p} {u} : {raison}")
    if midi and not sautees:
        cache["midi"] = jour
    cache.update({"date": jour, "collecte_le": maintenant.isoformat(timespec="seconds"), "erreurs": erreurs,
                  "dernier_passage": {"mode": mode + (" + midi" if midi else ""), "requetes": faites,
                                      "sautees_budget": len(sautees), "reserve": reserve}})
    if sautees:
        cache["dernier_passage"]["detail_sautees"] = sautees[:12]
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except OSError as exc:
        log.warning("Cache des bougies non écrit : %s", exc)
    log.info("Bougies (%s) : %d requête(s), %d sautée(s) faute de budget, %d erreur(s)", mode, faites, len(sautees), len(erreurs))
    return cache
