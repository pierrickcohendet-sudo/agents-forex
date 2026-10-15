"""Simulateur d'impact (refonte V2 §12, palier 11) : calcul seul, sans affichage et sans LLM.

Pour chaque couple indicateur × devise, étude d'événements sur 5 ans (core/historique_5ans.py) :
- épisodes : variation QUOTIDIENNE de l'indicateur d'au moins 1 (ou 2) écart(s)-type(s), épisodes espacés d'au
  moins 28 jours ; hausse et baisse séparées (réaction asymétrique) ;
- réponse de la devise (force, en %) le lendemain, à 1 semaine et à 1 mois : médiane, fourchette 25–75 %,
  trajectoire jour par jour, part des cas dans le sens attendu, nombre de cas ;
- sous 20 cas : « échantillon insuffisant pour conclure » (le chiffre existe mais n'est jamais mis en avant) ;
- surprises (CPI, CPI core, PIB, taux Fed) : publié − consensus ForexFactory en écarts habituels ; sans consensus,
  n/d avec la raison.
La sensibilité (corrélation des variations sur 1 mois, points mensuels) est LA MÊME fonction que celle du tableau
des conséquences (core/consequences.py) : une seule source de vérité.
Sortie : docs/data/impact.json (fichier séparé : site.json reste léger).
"""
from __future__ import annotations

import bisect
import json
import logging
import math
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import controles_macro, historique_5ans as h5m

log = logging.getLogger(__name__)

DEVISES = h5m.DEVISES
HORIZONS = {"demain": 1, "semaine": 7, "mois": 30}       # jours calendaires (demain : séance suivante)
AMPLEURS = (1, 2)
ESPACEMENT_JOURS = 28
MIN_CAS = 20
JOURS_TRAJECTOIRE = 30
JOURS_TRAJ = (0, 1, 2, 3, 4, 5, 7, 10, 14, 21, 30)   # resserré au début, là où la réaction se joue
MIN_PAIRES_SENSIBILITE = 12
SEUIL_SENS = 0.1
GROUPES = {"taux": "Taux, obligations, croissance, inflation", "marches": "Marchés"}
INDICATEURS = [
    {"id": "us2a", "libelle": "Rendement 2 ans US", "groupe": "taux", "type": "marche", "serie": "USD_2a", "unite": "pb"},
    {"id": "us10a", "libelle": "Rendement 10 ans US", "groupe": "taux", "type": "marche", "serie": "USD_10a", "unite": "pb"},
    {"id": "oblig_us", "libelle": "Obligations d'État US (ETF TLT, prix)", "groupe": "taux", "type": "marche", "serie": "oblig_us_tlt", "unite": "%"},
    # Indicateurs publiés : « variation de la publication » sur 15 à 20 ans (core/impact_long.py, palier 11b) ; le
    # consensus ForexFactory (depuis 2026 seulement) ne sert pas, faute de profondeur.
    {"id": "fed", "libelle": "Taux directeur Fed", "groupe": "taux", "type": "publication", "registre": "USD|taux_directeur"},
    {"id": "pib_us", "libelle": "PIB US", "groupe": "taux", "type": "publication", "registre": "USD|pib"},
    {"id": "cpi_core_us", "libelle": "CPI core US", "groupe": "taux", "type": "publication", "registre": "USD|cpi_core"},
    {"id": "cpi_us", "libelle": "CPI US", "groupe": "taux", "type": "publication", "registre": "USD|cpi"},
    {"id": "brent", "libelle": "Brent", "groupe": "marches", "type": "marche", "serie": "brent", "unite": "%"},
    {"id": "vix", "libelle": "VIX", "groupe": "marches", "type": "marche", "serie": "vix", "unite": "pts"},
    {"id": "dollar_large", "libelle": "Indice dollar large (Fed)", "groupe": "marches", "type": "marche", "serie": "dollar_large", "unite": "%"},
    {"id": "or", "libelle": "Indice or (proxy)", "groupe": "marches", "type": "marche", "serie": "indice_or", "unite": "%"},
    {"id": "sp500", "libelle": "S&P 500", "groupe": "marches", "type": "marche", "serie": "sp500", "unite": "%"},
]
NOTE = ("Moyennes passées sur 5 ans, pas une prévision : ce que la devise a fait, en médiane, après des mouvements comparables "
        "de l'indicateur. Corrélation n'est pas causalité. Aucune recommandation d'achat ou de vente.")


# ----------------------------------------------------------------- séries
class Serie:
    """Série datée ; lecture de la dernière valeur connue à une date (recherche dichotomique).
    unite « % » : variations logarithmiques en % ; « pb » : différences × 100 ; sinon différences brutes."""

    def __init__(self, points, unite: str, sans_week_end: bool = False):
        pts = sorted((str(d)[:10], float(v)) for d, v in points if v is not None)
        if sans_week_end:   # Twelve Data renvoie parfois le samedi avec la clôture du vendredi
            pts = [(d, v) for d, v in pts if date.fromisoformat(d).weekday() < 5]
        self.points, self.dates, self.unite = pts, [d for d, _ in pts], unite

    def a(self, jour: str) -> float | None:
        i = bisect.bisect_right(self.dates, jour)
        return self.points[i - 1][1] if i else None

    def apres(self, jour: str) -> tuple[str, float] | None:
        """Première observation STRICTEMENT après `jour` (la « séance suivante »)."""
        i = bisect.bisect_right(self.dates, jour)
        return self.points[i] if i < len(self.points) else None

    def ecart(self, a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        if self.unite == "%":
            return math.log(b / a) * 100 if a > 0 and b > 0 else None
        return (b - a) * (100 if self.unite == "pb" else 1)

    def variation(self, debut: str, fin: str) -> float | None:
        return self.ecart(self.a(debut), self.a(fin))


def serie_devise(h: h5m.Historique, devise: str, technique: dict | None = None) -> Serie:
    """Force de la devise (série unique 5 ans), jours ouvrés seulement : partagée avec le tableau des conséquences."""
    return Serie(h.force(devise, technique), "%", sans_week_end=True)


def _plus(jour: str, jours: int) -> str:
    return (date.fromisoformat(jour) + timedelta(days=jours)).isoformat()


def sensibilite(moteur: Serie, cible: Serie, debut: str, fin: str, horizon: int = 30) -> tuple[float | None, int]:
    """Corrélation des variations sur `horizon` jours, points non chevauchants : partagée par le simulateur et le
    tableau des conséquences (même chiffre des deux côtés)."""
    paires, j = [], date.fromisoformat(debut) + timedelta(days=horizon)
    while j.isoformat() <= fin:
        d = j.isoformat()
        dm, dc = moteur.variation(_plus(d, -horizon), d), cible.variation(_plus(d, -horizon), d)
        if dm is not None and dc is not None:
            paires.append((dm, dc))
        j += timedelta(days=horizon)
    if len(paires) < MIN_PAIRES_SENSIBILITE:
        return None, len(paires)
    try:
        return round(statistics.correlation([p[0] for p in paires], [p[1] for p in paires]), 2), len(paires)
    except statistics.StatisticsError:
        return None, len(paires)


def borne_basse_wilson(bons: int, n: int, z: float = 1.645) -> float | None:
    if not n:
        return None
    p = bons / n
    centre, marge = p + z * z / (2 * n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(100 * (centre - marge) / (1 + z * z / n), 1)


def _quantile(valeurs: list[float], q: float) -> float:
    v = sorted(valeurs)
    pos = (len(v) - 1) * q
    bas, haut = math.floor(pos), math.ceil(pos)
    return v[bas] + (v[haut] - v[bas]) * (pos - bas)


# ----------------------------------------------------------------- épisodes
def chocs_marche(serie: Serie, debut: str, fin: str) -> tuple[list[tuple[str, float]], float | None]:
    """Variations quotidiennes (date, Δ) de l'indicateur sur la fenêtre et leur écart-type."""
    deltas = []
    for (_, a), (d, b) in zip(serie.points, serie.points[1:]):
        if debut <= d <= fin:
            x = serie.ecart(a, b)
            if x is not None:
                deltas.append((d, x))
    return deltas, (statistics.pstdev([x for _, x in deltas]) if len(deltas) >= 60 else None)


def episodes(deltas: list[tuple[str, float]], sigma: float, k: int, espacement: int = ESPACEMENT_JOURS) -> list[tuple[str, float]]:
    """Chocs d'au moins k écarts-types, espacés d'au moins `espacement` jours (le premier de chaque grappe)."""
    retenus, dernier = [], None
    for d, x in deltas:
        if abs(x) >= k * sigma and (dernier is None or d >= _plus(dernier, espacement)):
            retenus.append((d, x))
            dernier = d
    return retenus


def reponses(devise: Serie, jour: str) -> dict[str, float | None]:
    """Réponse de la devise après le choc du jour `jour` : séance suivante, +7 j, +30 j (None si pas encore connue)."""
    base = devise.a(jour)
    suivante = devise.apres(jour)
    dernier = devise.dates[-1] if devise.dates else jour
    sortie = {"demain": devise.ecart(base, suivante[1]) if suivante else None}
    for nom, j in (("semaine", 7), ("mois", 30)):
        sortie[nom] = devise.ecart(base, devise.a(_plus(jour, j))) if _plus(jour, j) <= dernier else None
    return sortie


def trajectoire(devise: Serie, jours_chocs: list[str]) -> list[list]:
    """[[jour, médiane, q25, q75]] de la réponse cumulée de J0 à J+30 (jours calendaires échantillonnés)."""
    sortie = []
    for j in JOURS_TRAJ:
        vals = [devise.ecart(devise.a(d), devise.a(_plus(d, j))) for d in jours_chocs
                if _plus(d, j) <= (devise.dates[-1] if devise.dates else d)]
        vals = [v for v in vals if v is not None]
        if len(vals) >= 3:
            sortie.append([j, round(statistics.median(vals), 2), round(_quantile(vals, .25), 2), round(_quantile(vals, .75), 2)])
    return sortie


def resume_horizon(valeurs: list[float], signe_attendu: int | None) -> dict:
    n = len(valeurs)
    if not n:
        return {"n": 0, "insuffisant": True, "mediane": None,
                "raison": f"échantillon insuffisant pour conclure (0 cas avec un recul suffisant, minimum {MIN_CAS})"}
    sortie = {"n": n, "mediane": round(statistics.median(valeurs), 3), "q25": round(_quantile(valeurs, .25), 3),
              "q75": round(_quantile(valeurs, .75), 3), "insuffisant": n < MIN_CAS}
    if signe_attendu:
        bons = sum(1 for v in valeurs if v * signe_attendu > 0)
        sortie.update({"part_sens_attendu": round(100 * bons / n), "borne_wilson_90": borne_basse_wilson(bons, n)})
    else:
        sortie.update({"part_sens_attendu": None, "raison_sens": "pas de sens attendu (sensibilité nulle ou non calculable)"})
    if n < MIN_CAS:
        sortie["raison"] = f"échantillon insuffisant pour conclure ({n} cas, minimum {MIN_CAS})"
    return sortie


# ----------------------------------------------------------------- calcul
def _surprises(registre: dict, ind: dict, cfg_tm: dict) -> tuple[list[tuple[str, float]], str | None]:
    case = ((registre or {}).get("cases") or {}).get(ind["registre"]) or {}
    cfg_ind = (cfg_tm.get("indicateurs") or {}).get(ind["indicateur"]) or {}
    if not case:
        return [], "indicateur absent du registre ForexFactory"
    plafond = float((cfg_tm.get("indice_surprise") or {}).get("plafond_surprise", 3))
    pts = sorted(controles_macro._surprises(case, cfg_ind, plafond))
    if not pts:
        return [], "aucune publication avec consensus ForexFactory dans le registre"
    return pts, None


def _publication(ind: dict, long: dict, registre: dict | None, sortie: dict) -> dict:
    """Indicateur publié : résultats sur 15 à 20 ans + 5 ans, calculés à la collecte (data/cache/impact_long.json)."""
    meta = {k: ind[k] for k in ("id", "libelle", "groupe", "type")}
    meta["etiquette"] = "Variation de la publication"
    x = ((long or {}).get("indicateurs") or {}).get(ind["id"])
    from core import registre_macro
    prochaine = registre_macro.prochaine_publication(((registre or {}).get("cases") or {}).get(ind["registre"]) or {})
    meta["prochaine_publication"] = prochaine
    if not x or x.get("raison"):
        meta["raison"] = (x or {}).get("raison") or "résultats sur 15 à 20 ans indisponibles (collecte du jour en échec)"
        return meta
    dp = x["derniere_publication"]
    if prochaine and prochaine[:10] <= dp["date"]:   # le registre garde la date de l'événement déjà publié
        meta["prochaine_publication"] = None
    meta.update({"libelle": x["libelle"], "mesure": x["mesure"], "source": x["source"], "unite": "pb" if ind["id"] == "fed" else "pt",
                 "valeur_actuelle": dp["valeur"], "date": dp["date"], "periode": dp["periode"], "choc_actuel": dp["choc"],
                 "debut": x["debut"], "n_publications": x["n_publications"], "sigma": x["sigma"], "seuils": x["seuils"],
                 "profondeur": f"depuis {x['debut'][:4]}", "calcule_le": long.get("calcule_le")})
    sortie["episodes"][ind["id"]] = {"tous": x["episodes"]}
    for devise, c in x["couples"].items():
        sortie["couples"][f"{ind['id']}|{devise}"] = c
        sortie["nombre_de_cas"].setdefault(ind["id"], {})[devise] = {
            f"{s}|{k}": c["scenarios"][f"{s}|{k}"]["mois"]["n"] for s in ("hausse", "baisse") for k in AMPLEURS}
        for cle, sc in c["scenarios"].items():
            if sc["mois"]["insuffisant"]:
                s, k = cle.split("|")
                sortie["insuffisants"].append(f"{ind['id']}|{devise}|{s}|{k}σ ({sc['mois']['n']} cas à 1 mois, depuis {x['debut'][:4]})")
    return meta


def calculer(h: h5m.Historique, technique: dict | None = None, registre: dict | None = None, config: dict | None = None,
             aujourdhui: date | None = None, long: dict | None = None) -> dict:
    fin = (aujourdhui or date.today()).isoformat()
    debut = (date.fromisoformat(fin) - timedelta(days=int(365.25 * 5))).isoformat()
    cfg_tm = (config or {}).get("tableau_macro") or {}
    devises = {d: serie_devise(h, d, technique) for d in DEVISES}
    devises = {d: s for d, s in devises.items() if len(s.points) > 260}
    sortie = {"genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"), "debut": debut, "fin": fin,
              "horizons": HORIZONS, "ampleurs": list(AMPLEURS), "min_cas": MIN_CAS, "groupes": GROUPES, "note": NOTE,
              "methode": ("Marchés : variation quotidienne de l'indicateur d'au moins 1 (ou 2) écart(s)-type(s) sur 5 ans, "
                          "épisodes espacés d'au moins 28 jours. Indicateurs publiés (CPI, CPI core, PIB, Fed) : « variation "
                          "de la publication » (écart avec la publication précédente, valeurs telles que publiées, FRED/ALFRED) "
                          "sur 15 à 20 ans, seuil en écart-type robuste ; Fed : toute décision (1) ou au moins 50 pb (2) ; "
                          "résultat aussi sur 5 ans. "
                          "Réponse : variation de la force de la devise (en %) à la séance suivante, à 7 et à 30 jours. "
                          "Sens attendu : signe de la sensibilité (corrélation des variations sur 1 mois, la même que dans "
                          "le tableau des conséquences) multiplié par le sens du choc."),
              "indicateurs": [], "couples": {}, "episodes": {}, "nombre_de_cas": {}, "insuffisants": [],
              "devises_absentes": [d for d in DEVISES if d not in devises]}
    for ind in INDICATEURS:
        meta = {k: ind[k] for k in ("id", "libelle", "groupe", "type")}
        try:
            if ind["type"] == "publication":
                sortie["indicateurs"].append(_publication(ind, long, registre, sortie))
                continue
            if ind["type"] == "surprise":
                pts, raison = _surprises(registre, ind, cfg_tm)
                case = ((registre or {}).get("cases") or {}).get(ind["registre"]) or {}
                meta.update({"unite": "écarts", "source": "ForexFactory (registre macro) : publié − consensus",
                             "valeur_actuelle": (case.get("actuel") or {}).get("valeur"), "date": (case.get("actuel") or {}).get("date_pub"),
                             "consensus_actuel": (case.get("actuel") or {}).get("consensus"),
                             "prochaine_publication": (case.get("prevision") or {}).get("date_pub"), "n_publications": len(pts)})
                if raison:
                    meta["raison"] = raison
                    sortie["indicateurs"].append(meta)
                    continue
                deltas = [(d, s) for d, s in pts if debut <= d <= fin]
                sigma = statistics.pstdev([s for _, s in deltas]) if len(deltas) >= 3 else None
                moteur = None
                if sigma is None or sigma == 0:
                    meta["raison"] = f"{len(deltas)} publication(s) avec consensus depuis le début du registre : écart-type non calculable"
            else:
                pts = h.serie(ind["serie"])
                if not pts:
                    meta["raison"] = "série 5 ans indisponible"
                    sortie["indicateurs"].append(meta)
                    continue
                moteur = Serie(pts, ind["unite"])
                deltas, sigma = chocs_marche(moteur, debut, fin)
                meta.update({"unite": ind["unite"], "source": h.source(ind["serie"]), "valeur_actuelle": round(pts[-1][1], 4),
                             "date": pts[-1][0], "variation_jour": round(deltas[-1][1], 3) if deltas else None})
            meta["sigma"] = None if sigma is None else round(sigma, 4)
            sortie["indicateurs"].append(meta)
            if sigma is None or sigma == 0:
                continue
            listes = {k: episodes(deltas, sigma, k) for k in AMPLEURS}
            sortie["episodes"][ind["id"]] = {str(k): [{"date": d, "choc": round(x, 3), "en_sigma": round(x / sigma, 2)} for d, x in v]
                                             for k, v in listes.items()}
            for devise, cible in devises.items():
                sens_r, n_mois = sensibilite(moteur, cible, debut, fin) if moteur else (None, 0)
                couple = {"sensibilite": sens_r, "n_mois": n_mois, "scenarios": {}, "reponses": {}}
                for k, liste in listes.items():
                    reps = [reponses(cible, d) for d, _ in liste]
                    couple["reponses"][str(k)] = [[None if r[hz] is None else round(r[hz], 2) for hz in HORIZONS] for r in reps]
                    for sens, signe in (("hausse", 1), ("baisse", -1)):
                        choisis = [(d, r) for (d, x), r in zip(liste, reps) if x * signe > 0]
                        attendu = None if sens_r is None or abs(sens_r) < SEUIL_SENS else (1 if sens_r > 0 else -1) * signe
                        sc = {hz: resume_horizon([r[hz] for _, r in choisis if r[hz] is not None], attendu) for hz in HORIZONS}
                        sc["trajectoire"] = trajectoire(cible, [d for d, _ in choisis])
                        couple["scenarios"][f"{sens}|{k}"] = sc
                        if sc["mois"]["insuffisant"]:
                            sortie["insuffisants"].append(f"{ind['id']}|{devise}|{sens}|{k}σ ({sc['mois']['n']} cas à 1 mois)")
                sortie["couples"][f"{ind['id']}|{devise}"] = couple
                sortie["nombre_de_cas"].setdefault(ind["id"], {})[devise] = {
                    f"{s}|{k}": couple["scenarios"][f"{s}|{k}"]["mois"]["n"] for s in ("hausse", "baisse") for k in AMPLEURS}
        except Exception as exc:  # noqa: BLE001 — un indicateur en échec n'affecte que lui
            log.exception("Simulateur : indicateur %s en échec", ind["id"])
            meta["raison"] = f"calcul en échec : {exc}"[:150]
            if meta not in sortie["indicateurs"]:
                sortie["indicateurs"].append(meta)
    return sortie


def ecrire(racine: str | Path, h: h5m.Historique, technique: dict | None, registre: dict | None, config: dict) -> dict | None:
    """Écrit docs/data/impact.json ; None en cas d'échec (jamais d'exception)."""
    try:
        from core import impact_long
        donnees = calculer(h, technique, registre, config, long=impact_long.charger())
        chemin = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data" / "impact.json"
        chemin.write_text(json.dumps(donnees, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("impact.json non écrit : %s", exc)
        return None
