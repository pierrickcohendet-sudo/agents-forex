"""Collecte technique via l'API Twelve Data.

- OHLC daily + weekly des 7 paires vs USD, cadence limitée (tier gratuit).
- Toutes les analyses se font sur une "série force" orientée devise :
  monter = la devise se renforce (inverse de la paire pour USD/JPY, USD/CHF,
  USD/CAD ; indice synthétique pour l'USD = force moyenne contre les 7 autres).
- Indicateurs : RSI (Wilder), MM 100/200, tendance de fond weekly (théorie de
  Dow sur pivots), zones de consolidation (>= 2 impacts).
- Corrélations : coefficient de Pearson calculé LOCALEMENT sur les rendements
  quotidiens — aucune heatmap externe n'est scrapée pour ce calcul.
"""
from __future__ import annotations

import logging
import os
import time

import pandas as pd
import requests

log = logging.getLogger(__name__)

URL_TWELVE = "https://api.twelvedata.com/time_series"


def _ohlc(paire: str, intervalle: str, taille: int, cle: str) -> pd.DataFrame:
    rep = requests.get(URL_TWELVE, params={
        "symbol": paire, "interval": intervalle, "outputsize": taille,
        "apikey": cle, "timezone": "UTC",
    }, timeout=30)
    rep.raise_for_status()
    donnees = rep.json()
    if donnees.get("status") != "ok" or "values" not in donnees:
        raise RuntimeError(f"Twelve Data {paire} {intervalle} : {donnees.get('message', donnees)}")
    df = pd.DataFrame(donnees["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    return df.sort_values("datetime").set_index("datetime")


def _calculer_rsi(serie: pd.Series, periode: int = 14) -> pd.Series:
    delta = serie.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / periode, adjust=False).mean()
    perte = (-delta.clip(upper=0)).ewm(alpha=1 / periode, adjust=False).mean()
    rs = gain / perte.replace(0, pd.NA)
    return (100 - 100 / (1 + rs)).fillna(50)


def _pivots(valeurs: list[float], k: int = 2) -> tuple[list[float], list[float]]:
    hauts, bas = [], []
    for i in range(k, len(valeurs) - k):
        fenetre = valeurs[i - k: i + k + 1]
        if valeurs[i] == max(fenetre):
            hauts.append(valeurs[i])
        if valeurs[i] == min(fenetre):
            bas.append(valeurs[i])
    return hauts, bas


def _tendance_dow(serie_hebdo: pd.Series) -> dict:
    """Hauts/bas successifs sur les pivots weekly : plus hauts = haussier,
    plus bas = baissier, sinon range."""
    valeurs = serie_hebdo.tolist()
    hauts, bas = _pivots(valeurs, k=2)
    if len(hauts) < 2 or len(bas) < 2:
        return {"unite_temps": "weekly", "sens": "range", "commentaire": "pivots insuffisants"}
    hh, hl = hauts[-1] > hauts[-2], bas[-1] > bas[-2]
    if hh and hl:
        sens, detail = "haussier", "hauts et bas successivement plus hauts"
    elif not hh and not hl:
        sens, detail = "baissier", "hauts et bas successivement plus bas"
    else:
        sens, detail = "range", "pivots non alignés (structure mixte)"
    return {"unite_temps": "weekly", "sens": sens, "commentaire": f"Dow : {detail}"}


def _zones_consolidation(serie: pd.Series, tolerance: float = 0.0035,
                         min_impacts: int = 2) -> list[dict]:
    """Regroupe les pivots daily proches (< tolérance relative) ; une zone est
    retenue à partir de `min_impacts` contacts. Max 3 zones, les plus proches
    du prix actuel."""
    valeurs = serie.tail(120).tolist()
    hauts, bas = _pivots(valeurs, k=2)
    prix = valeurs[-1]
    zones = []
    for niveaux in (hauts, bas):
        restants = sorted(niveaux)
        while restants:
            base = restants.pop(0)
            groupe = [base] + [n for n in restants if abs(n - base) / base < tolerance]
            restants = [n for n in restants if abs(n - base) / base >= tolerance]
            if len(groupe) >= min_impacts:
                niveau = sum(groupe) / len(groupe)
                zones.append({
                    "type": "resistance" if niveau > prix else "support",
                    "niveau": round(niveau, 5), "impacts": len(groupe),
                    "distance_pct": round((niveau - prix) / prix * 100, 2),
                })
    zones.sort(key=lambda z: abs(z["distance_pct"]))
    return zones[:3]


def collecter(config: dict) -> dict:
    cle = os.environ.get("TWELVE_DATA_API_KEY", "")
    resultat: dict = {"devises": {}, "graphiques": {}, "correlations": {},
                      "prix_cloture": {}, "erreurs": []}
    if not cle:
        resultat["erreurs"].append("TWELVE_DATA_API_KEY absente — collecte technique sautée")
        log.error(resultat["erreurs"][-1])
        return resultat

    cfg = config["technique"]
    pause = float(cfg.get("pause_entre_appels_s", 8.5))
    forces_daily, forces_weekly = {}, {}

    for devise, dc in config["devises"].items():
        paire = dc.get("paire")
        if not paire:
            continue  # USD : indice synthétique construit après la boucle
        try:
            df_d = _ohlc(paire, "1day", int(cfg["outputsize"]), cle)
            time.sleep(pause)
            df_w = _ohlc(paire, "1week", 120, cle)
            time.sleep(pause)
        except (requests.RequestException, RuntimeError) as exc:
            resultat["erreurs"].append(f"{devise} ({paire}) : {exc}")
            log.error("Collecte technique %s en échec : %s", devise, exc)
            continue
        # Série orientée force de la devise (inverse pour USD/XXX).
        forces_daily[devise] = (1.0 / df_d["close"]) if dc["inverse"] else df_d["close"]
        forces_weekly[devise] = (1.0 / df_w["close"]) if dc["inverse"] else df_w["close"]

    if not forces_daily:
        resultat["erreurs"].append("Aucune paire récupérée sur Twelve Data")
        return resultat

    # Indice USD synthétique : rendement = moyenne des rendements inverses des autres.
    rendements = pd.DataFrame({d: s.pct_change() for d, s in forces_daily.items()}).dropna(how="all")
    rendement_usd = -rendements.mean(axis=1)
    forces_daily["USD"] = 100 * (1 + rendement_usd.fillna(0)).cumprod()
    rendements_w = pd.DataFrame({d: s.pct_change() for d, s in forces_weekly.items()}).dropna(how="all")
    forces_weekly["USD"] = 100 * (1 + (-rendements_w.mean(axis=1).fillna(0))).cumprod()

    # Corrélations de Pearson (calcul local) sur la fenêtre configurée.
    fenetre = int(cfg.get("fenetre_correlation", 60))
    tous_rendements = pd.DataFrame({d: s.pct_change() for d, s in forces_daily.items()})
    matrice = tous_rendements.tail(fenetre).corr(method="pearson").round(2)
    resultat["correlations"] = {
        d: {a: (None if pd.isna(v) else float(v)) for a, v in ligne.items()}
        for d, ligne in matrice.to_dict().items()
    }

    periode_rsi = int(cfg.get("rsi_periode", 14))
    nb_points = int(cfg.get("graphique_nb_points", 90))
    for devise, serie in forces_daily.items():
        dc = config["devises"][devise]
        serie = serie.dropna()
        if len(serie) < 30:
            resultat["erreurs"].append(f"{devise} : série trop courte ({len(serie)} points)")
            continue
        rsi = _calculer_rsi(serie, periode_rsi)
        moyennes = {}
        for p in cfg.get("moyennes_mobiles", [100, 200]):
            if len(serie) >= p:
                moyennes[f"mm{p}"] = round(float(serie.rolling(p).mean().iloc[-1]), 5)
        dernier = float(serie.iloc[-1])
        rsi_actuel = round(float(rsi.iloc[-1]), 1)
        hebdo = forces_weekly.get(devise)
        tendance = _tendance_dow(hebdo.dropna()) if hebdo is not None and len(hebdo.dropna()) > 10 \
            else {"unite_temps": "weekly", "sens": "range", "commentaire": "données weekly indisponibles"}

        mm200 = moyennes.get("mm200")
        resultat["devises"][devise] = {
            "paire": dc.get("paire") or "indice USD synthétique (calcul local)",
            "inverse": bool(dc.get("inverse")),
            "dernier": round(dernier, 5),
            "variation_5j_pct": round(float(serie.pct_change(5).iloc[-1] * 100), 2),
            "rsi": rsi_actuel,
            "rsi_lecture": ("surachat" if rsi_actuel > 70 else "survente" if rsi_actuel < 30
                            else "momentum haussier" if rsi_actuel > 50 else "momentum baissier"),
            **moyennes,
            "prix_vs_mm200": (None if mm200 is None else
                              ("au-dessus" if dernier > mm200 else "en dessous")),
            "tendance_fond": tendance,
            "zones_consolidation": _zones_consolidation(serie),
            "ratio_rr_configure": dc.get("ratio_rr"),
        }
        resultat["graphiques"][devise] = {
            "libelle": f"Force {devise}" + (f" ({dc['paire']}" + (" inversée)" if dc.get("inverse") else ")")
                                            if dc.get("paire") else " (indice synthétique)"),
            "dates": [d.strftime("%Y-%m-%d") for d in serie.tail(nb_points).index],
            "clotures": [round(float(v), 5) for v in serie.tail(nb_points)],
        }
        resultat["prix_cloture"][devise] = round(dernier, 5)

    log.info("Collecte technique : %d devise(s), %d erreur(s)",
             len(resultat["devises"]), len(resultat["erreurs"]))
    return resultat
