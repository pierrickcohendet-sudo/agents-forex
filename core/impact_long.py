"""Simulateur d'impact, palier 11b : indicateurs publiés (CPI, CPI core, PIB, Fed) sur 15 à 20 ans, sans consensus.

Pas de surprise (le consensus ForexFactory n'existe que depuis 2026) : le choc est la VARIATION DE LA PUBLICATION,
c'est-à-dire l'écart entre le chiffre publié et le chiffre publié précédent, lu TEL QU'IL ÉTAIT CONNU le jour de la
publication (ALFRED, historique des révisions de FRED) :
- CPI et CPI core : variation mensuelle publiée (m/m, %) ; choc = m/m publié − m/m publié le mois précédent ;
- PIB : croissance trimestrielle annualisée publiée (estimation avancée) ; choc = écart avec la publication précédente ;
- Fed : variation de la cible décidée (pb), jours de décision (DFEDTAR puis borne haute DFEDTARU).
Réponse des devises : Fed H.10 sur 20 ans (USD = indice synthétique, même définition qu'ailleurs). Les publications
de 8 h 30 (CPI, PIB) précèdent le relevé de midi de la Fed H.10 : la base est la séance PRÉCÉDENTE et la première
réponse est celle du jour même ; décision Fed (14 h) : base le jour même, réponse le lendemain.
Seuil de choc : k × écart-type ROBUSTE des variations publiées (1,4826 × écart absolu médian).
Résultat sur toute la profondeur et, à part, sur 5 ans (« échantillon insuffisant » sous 20 cas). Calculé à la
collecte (une requête par série et par jour), écrit dans data/cache/impact_long.json (taille stable).
"""
from __future__ import annotations

import json
import logging
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from core import historique_5ans as h5m, impact

log = logging.getLogger(__name__)

RACINE = Path(__file__).resolve().parent.parent
CHEMIN = RACINE / "data" / "cache" / "impact_long.json"
DEBUT_PUBLICATIONS = "2004-01-01"
ANNEES_FX = 20
ESPACEMENT_JOURS = 20      # publications mensuelles : des événements naturellement distincts
SEUILS_FED_PB = {1: 25, 2: 50}   # ampleur 1 : toute décision de variation ; 2 : au moins 50 pb
CHANGES = {"EUR": "DEXUSEU", "GBP": "DEXUSUK", "JPY": "DEXJPUS", "CHF": "DEXSZUS", "CAD": "DEXCAUS", "AUD": "DEXUSAL",
           "NZD": "DEXUSNZ", "CNY": "DEXCHUS"}
PUBLICATIONS = {
    "cpi_us": {"serie": "CPIAUCSL", "libelle": "CPI US", "mesure": "variation mensuelle publiée (m/m, %)", "trimestriel": False},
    "cpi_core_us": {"serie": "CPILFESL", "libelle": "CPI core US", "mesure": "variation mensuelle publiée (m/m, %)", "trimestriel": False},
    "pib_us": {"serie": "GDPC1", "libelle": "PIB US", "mesure": "croissance trimestrielle annualisée publiée (%)", "trimestriel": True},
}
URL = "https://api.stlouisfed.org/fred/series/observations"


# ----------------------------------------------------------------- collecte
def _get(cle: str, **params) -> list[dict]:
    rep = requests.get(URL, params={"api_key": cle, "file_type": "json", "limit": 100000, **params}, timeout=120,
                       headers={"User-Agent": "agents-forex/1.0 (rapport FX personnel ; une requête par série et par jour)"})
    rep.raise_for_status()
    return rep.json().get("observations", [])


def telecharger(cle: str, aujourdhui: date) -> tuple[dict, list[str]]:
    debut_fx = (aujourdhui - timedelta(days=int(365.25 * ANNEES_FX))).isoformat()
    bruts, erreurs = {}, []
    for devise, sid in CHANGES.items():
        try:
            bruts[f"FX_{devise}"] = [(o["date"], float(o["value"])) for o in _get(cle, series_id=sid, observation_start=debut_fx)
                                     if o.get("value") not in (".", None)]
        except Exception as exc:  # noqa: BLE001
            erreurs.append(f"{sid} : {exc}"[:150])
    for ident, spec in PUBLICATIONS.items():
        try:
            bruts[ident] = _get(cle, series_id=spec["serie"], output_type=1, realtime_start=DEBUT_PUBLICATIONS,
                                realtime_end="9999-12-31", observation_start="2003-01-01")
        except Exception as exc:  # noqa: BLE001
            erreurs.append(f"{spec['serie']} (ALFRED) : {exc}"[:150])
    for sid in ("DFEDTAR", "DFEDTARU"):
        try:
            bruts[sid] = [(o["date"], float(o["value"])) for o in _get(cle, series_id=sid, observation_start=DEBUT_PUBLICATIONS)
                          if o.get("value") not in (".", None)]
        except Exception as exc:  # noqa: BLE001
            erreurs.append(f"{sid} : {exc}"[:150])
    return bruts, erreurs


# ----------------------------------------------------------------- publications
def tel_que_publie(lignes: list[dict], trimestriel: bool) -> list[tuple[str, str, float]]:
    """[(date de publication, période, variation publiée)] : la période et la précédente lues dans le MILLÉSIME
    du jour de publication (valeurs connues ce jour-là, avant toute révision ultérieure)."""
    par_periode: dict[str, list[tuple[str, str, float]]] = {}
    for o in lignes:
        if o.get("value") in (".", None):
            continue
        par_periode.setdefault(o["date"], []).append((o["realtime_start"], o["realtime_end"], float(o["value"])))
    periodes = sorted(par_periode)
    sortie = []
    for prec, per in zip(periodes, periodes[1:]):
        publication = min(r[0] for r in par_periode[per])
        if publication <= DEBUT_PUBLICATIONS:        # première publication antérieure à la fenêtre ALFRED demandée
            continue
        v = next((x for a, b, x in par_periode[per] if a <= publication <= b), None)
        v0 = next((x for a, b, x in par_periode[prec] if a <= publication <= b), None)
        if v is None or not v0:
            continue
        ratio = v / v0
        variation = (ratio ** 4 - 1) * 100 if trimestriel else (ratio - 1) * 100
        sortie.append((publication, per, round(variation, 3)))
    return sorted(sortie)


def sigma_robuste(valeurs: list[float]) -> float:
    """Écart-type robuste = 1,4826 × écart absolu médian : les publications extrêmes (PIB 2020 : −31 % puis +33 %
    annualisés) ne fixent pas à elles seules le seuil de « choc »."""
    m = statistics.median(valeurs)
    return 1.4826 * statistics.median(abs(v - m) for v in valeurs)


def decisions_fed(dfedtar: list, dfedtaru: list) -> list[tuple[str, float]]:
    """[(date, variation de la cible en pb)] aux jours de changement (cible unique jusqu'au 15/12/2008, puis borne haute)."""
    serie = [(d, v) for d, v in dfedtar if d <= "2008-12-15"] + [(d, v) for d, v in dfedtaru if d >= "2008-12-16"]
    serie.sort()
    return [(d, round((v - v0) * 100)) for (_, v0), (d, v) in zip(serie, serie[1:]) if abs(v - v0) > 1e-9]


def _seance_precedente(serie: impact.Serie, jour: str) -> str | None:
    import bisect
    i = bisect.bisect_left(serie.dates, jour)
    return serie.dates[i - 1] if i else None


def etude(chocs: list[tuple[str, float]], seuils: dict[int, float], devises: dict[str, impact.Serie], avant_midi: bool,
          debut: str | None = None) -> dict:
    """Scénarios par devise pour des chocs [(date, choc)] : hausse/baisse × ampleur × horizon (+ trajectoires)."""
    chocs = [(d, x) for d, x in chocs if not debut or d >= debut]
    sortie = {}
    for devise, cible in devises.items():
        bases = {}
        for d, _ in chocs:
            base = _seance_precedente(cible, d) if avant_midi else d
            if base:
                bases[d] = base
        # sens attendu : signe de la corrélation entre le choc et la première réponse, sur toutes les publications
        paires = [(x, impact.reponses(cible, bases[d])["demain"]) for d, x in chocs if d in bases]
        paires = [(x, r) for x, r in paires if r is not None]
        try:
            sens_r = round(statistics.correlation([p[0] for p in paires], [p[1] for p in paires]), 2) if len(paires) >= 12 else None
        except statistics.StatisticsError:
            sens_r = None
        couple = {"sensibilite": sens_r, "n_publications": len(paires), "scenarios": {},
                  # nuage : réponse à chaque horizon pour CHAQUE publication, alignée sur la liste « episodes »
                  "reponses_tous": [([None if v is None else round(v, 2) for v in impact.reponses(cible, bases[d]).values()]
                                     if d in bases else None) for d, x in chocs]}
        for k, seuil in seuils.items():
            retenus, dernier = [], None
            for d, x in chocs:
                if d in bases and abs(x) >= seuil and (dernier is None or d >= impact._plus(dernier, ESPACEMENT_JOURS)):
                    retenus.append((d, x))
                    dernier = d
            for sens, signe in (("hausse", 1), ("baisse", -1)):
                choisis = [(d, impact.reponses(cible, bases[d])) for d, x in retenus if x * signe > 0]
                attendu = None if sens_r is None or abs(sens_r) < impact.SEUIL_SENS else (1 if sens_r > 0 else -1) * signe
                sc = {hz: impact.resume_horizon([r[hz] for _, r in choisis if r[hz] is not None], attendu) for hz in impact.HORIZONS}
                sc["trajectoire"] = impact.trajectoire(cible, [bases[d] for d, _ in choisis])
                couple["scenarios"][f"{sens}|{k}"] = sc
        sortie[devise] = couple
    return sortie


def calculer(bruts: dict, aujourdhui: date | None = None) -> dict:
    aujourdhui = aujourdhui or date.today()
    debut_5a = (aujourdhui - timedelta(days=int(365.25 * 5))).isoformat()
    h = h5m.Historique.depuis_points({k: v for k, v in bruts.items() if k.startswith("FX_")})
    devises = {d: impact.Serie(h.force(d), "%", sans_week_end=True) for d in h5m.DEVISES}
    devises = {d: s for d, s in devises.items() if len(s.points) > 500}
    sortie = {"calcule_le": aujourdhui.isoformat(), "indicateurs": {}, "erreurs": []}
    sources = {}
    for ident, spec in PUBLICATIONS.items():
        pubs = tel_que_publie(bruts.get(ident) or [], spec["trimestriel"])
        chocs = [(d, round(x - x0, 3)) for (_, _, x0), (d, _, x) in zip(pubs, pubs[1:])]
        sources[ident] = (spec, pubs, chocs, False)
    fed = decisions_fed(bruts.get("DFEDTAR") or [], bruts.get("DFEDTARU") or [])
    sources["fed"] = ({"libelle": "Taux directeur Fed", "mesure": "variation de la cible décidée (pb)", "serie": "DFEDTAR/DFEDTARU"},
                      [(d, d, x) for d, x in fed], fed, True)
    for ident, (spec, pubs, chocs, est_fed) in sources.items():
        if len(chocs) < 12 or not devises:
            sortie["indicateurs"][ident] = {"raison": f"historique insuffisant ({len(chocs)} publication(s))" if devises
                                            else "séries de change sur 20 ans indisponibles"}
            continue
        sigma = None if est_fed else sigma_robuste([x for _, x in chocs])
        seuils = SEUILS_FED_PB if est_fed else {k: k * sigma for k in impact.AMPLEURS}
        avant_midi = not est_fed
        long = etude(chocs, seuils, devises, avant_midi)
        cinq = etude(chocs, seuils, devises, avant_midi, debut_5a)
        dernier = pubs[-1]
        sortie["indicateurs"][ident] = {
            "libelle": f"{spec['libelle']} — variation de la publication", "mesure": spec["mesure"],
            "source": f"FRED / ALFRED ({spec['serie']}), valeurs telles que publiées",
            "debut": chocs[0][0], "n_publications": len(chocs), "sigma": None if sigma is None else round(sigma, 4),
            "seuils": {str(k): round(v, 4) for k, v in seuils.items()},
            "derniere_publication": {"date": dernier[0], "periode": dernier[1], "valeur": dernier[2],
                                     "choc": chocs[-1][1]},
            "episodes": [{"date": d, "choc": x} for d, x in chocs],
            "couples": {dev: {"sensibilite": long[dev]["sensibilite"], "n_publications": long[dev]["n_publications"],
                              "scenarios": long[dev]["scenarios"], "scenarios_5ans": cinq[dev]["scenarios"],
                              "reponses_tous": long[dev]["reponses_tous"]} for dev in long},
        }
    return sortie


def collecter_et_ecrire(cle: str, aujourdhui: date | None = None, chemin: Path | str = CHEMIN) -> dict:
    """Une requête par série (13 au total), calcul, écriture du cache. Retourne un résumé (jamais d'exception)."""
    aujourdhui = aujourdhui or date.today()
    try:
        bruts, erreurs = telecharger(cle, aujourdhui)
        res = calculer(bruts, aujourdhui)
        res["erreurs"] = erreurs
        res["ecrit_le"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        Path(chemin).write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return {k: v.get("n_publications", v.get("raison")) for k, v in res["indicateurs"].items()}
    except Exception as exc:  # noqa: BLE001
        log.error("Simulateur, indicateurs publiés : %s", exc)
        return {"erreur": str(exc)[:150]}


def charger(chemin: Path | str = CHEMIN) -> dict:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
