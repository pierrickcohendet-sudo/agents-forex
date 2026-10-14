"""Corrélations glissantes à 30 séances calculées sur 5 ans de prix QUOTIDIENS (sans LLM).

Appelé pendant la collecte des historiques, quand les séries quotidiennes complètes sont en mémoire
(le cache, lui, ne garde que 140 jours au pas quotidien) : on ne stocke que le résultat par paire
devise × actif — valeur du jour, valeur 30 séances plus tôt, percentile parmi toutes les corrélations
glissantes des 5 ans, et la courbe des 120 derniers jours.

Force d'une devise = dollars US pour une unité de devise (Fed H.10, cotations inversées si besoin) ;
USD = indice dollar large de la Fed. Rendements logarithmiques, sauf le 10 ans US (variation en points).
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

SEANCES = 30
JOURS_COURBE = 120
MIN_FENETRES = 200   # en dessous : percentile non calculé
DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
INVERSEES = {"JPY", "CHF", "CAD", "CNY"}   # cotées en unités de devise pour 1 USD
ACTIFS = {"VIX": ("vix", False), "S&P 500": ("sp500", False), "Pétrole Brent": ("brent", False),
          "Indice or (proxy)": ("indice_or", False), "Rendement 10 ans US": ("USD_10a", True)}
SERIES_NECESSAIRES = {"dollar_large", *(f"FX_{d}" for d in DEVISES if d != "USD"), *(n for n, _ in ACTIFS.values())}
SOURCE = ("calcul Python : corrélation glissante sur 30 séances communes des rendements quotidiens, 5 ans de prix "
          "(FRED : Fed H.10 pour les devises, DTWEXBGS pour l'USD, VIXCLS, SP500, DCOILBRENTEU, NASDAQQGLDI, DGS10)")


def _rendements(points: list[tuple[str, float]], en_points: bool, inverse: bool = False) -> dict[str, float]:
    sortie = {}
    for (_, a), (d, b) in zip(points, points[1:]):
        if en_points:
            sortie[d] = b - a
        elif a > 0 and b > 0:
            sortie[d] = math.log(a / b) if inverse else math.log(b / a)
    return sortie


def _corr(a: list[float], b: list[float]) -> float | None:
    try:
        return statistics.correlation(a, b)
    except statistics.StatisticsError:   # série constante sur la fenêtre
        return None


def glissante(ra: dict[str, float], rb: dict[str, float], seances: int = SEANCES) -> list[tuple[str, float]]:
    """[(date de fin de fenêtre, corrélation)] sur les dates communes, fenêtre de `seances` séances."""
    communes = sorted(set(ra) & set(rb))
    sortie = []
    for i in range(seances, len(communes) + 1):
        fen = communes[i - seances:i]
        r = _corr([ra[d] for d in fen], [rb[d] for d in fen])
        if r is not None:
            sortie.append((fen[-1], round(r, 3)))
    return sortie


def calculer(bruts: dict[str, list[tuple[str, float]]], aujourdhui: date | None = None) -> dict:
    """bruts : {nom de série: [(date, valeur)] quotidiens complets}. Une paire sans données n'a pas d'entrée,
    la raison est listée dans « absentes »."""
    aujourdhui = aujourdhui or date.today()
    force = {}
    for devise in DEVISES:
        nom = "dollar_large" if devise == "USD" else f"FX_{devise}"
        if bruts.get(nom):
            force[devise] = _rendements(bruts[nom], False, devise in INVERSEES)
    actifs = {lib: _rendements(bruts[nom], en_points) for lib, (nom, en_points) in ACTIFS.items() if bruts.get(nom)}
    debut_5a = (aujourdhui - timedelta(days=int(365.25 * 5))).isoformat()
    paires, absentes, fins = {}, [], []
    for devise in DEVISES:
        for actif in ACTIFS:
            if devise not in force or actif not in actifs:
                absentes.append(f"{devise} / {actif} : série {'de change' if devise not in force else actif} indisponible")
                continue
            serie = [(d, r) for d, r in glissante(force[devise], actifs[actif]) if d >= debut_5a]
            if not serie:
                absentes.append(f"{devise} / {actif} : moins de {SEANCES} séances communes")
                continue
            d0, r0 = serie[-1]
            valeurs = [r for _, r in serie]
            pct = round(100 * sum(1 for v in valeurs if v <= r0) / len(valeurs)) if len(valeurs) >= MIN_FENETRES else None
            limite = (date.fromisoformat(d0) - timedelta(days=JOURS_COURBE)).isoformat()
            paires[f"{devise}|{actif}"] = {
                "valeur": round(r0, 2), "date": d0,
                "precedente": round(serie[-1 - SEANCES][1], 2) if len(serie) > SEANCES else None,
                "percentile_5a": pct, "n_5a": len(valeurs), "debut": serie[0][0],
                "raison_percentile": None if pct is not None else f"moins de {MIN_FENETRES} fenêtres sur 5 ans ({len(valeurs)})",
                "min_5a": round(min(valeurs), 2), "max_5a": round(max(valeurs), 2),
                "courbe": [[d, round(r, 2)] for d, r in serie if d >= limite]}
            fins.append(d0)
    return {"seances": SEANCES, "paires": paires, "absentes": absentes, "source": SOURCE,
            "derniere_seance": max(fins) if fins else None, "calcule_le": aujourdhui.isoformat()}
