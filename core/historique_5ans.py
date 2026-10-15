"""Historique quotidien sur 5 ans, partagé par tous les calculs longs des engrenages (sans LLM).

Un seul fichier, data/cache/historique_5ans.json : prix QUOTIDIENS complets d'une liste fermée de séries,
sur une fenêtre GLISSANTE (5 ans + 300 jours d'amorçage) — les points plus anciens sont supprimés à chaque
écriture, la taille du fichier reste donc stable. Écrit une fois par jour par la collecte des historiques.

Calculs fournis (toujours sur ces séries, jamais sur des valeurs saisies) :
- force d'une devise (dollars US par unité ; USD = indice dollar large de la Fed), prolongée par les
  clôtures Twelve Data postérieures à la dernière publication Fed H.10 (même grandeur) ;
- RSI 14 (Wilder), écart à une moyenne mobile, volatilité réalisée 20 séances, percentiles sur 5 ans ;
- corrélations glissantes à 30 séances (paires devise × actif, matrice complète du dossier 5).
Plus tard : matrice d'impact et simulateur s'appuieront sur les mêmes séries.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CHEMIN = RACINE / "data" / "cache" / "historique_5ans.json"
FENETRE_JOURS = int(365.25 * 5) + 300
ANNEES = 5
DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
INVERSEES = {"JPY", "CHF", "CAD", "CNY"}            # Fed H.10 : unités de devise pour 1 USD
SERIES = {**{f"FX_{d}": f"FRED (Fed H.10, {d})" for d in DEVISES if d != "USD"},
          "dollar_large": "FRED (DTWEXBGS, indice dollar large de la Fed)", "vix": "FRED (VIXCLS)",
          "sp500": "FRED (SP500)", "brent": "FRED (DCOILBRENTEU)", "wti": "FRED (DCOILWTICO)",
          "indice_or": "FRED (NASDAQQGLDI, indice or proxy)", "USD_10a": "FRED (DGS10)", "USD_2a": "FRED (DGS2)",
          "USD_taux_effectif": "FRED (DFF)", "USD_prime_terme": "FRED (THREEFYTP10, prime de terme 10 ans)",
          "oblig_us_tlt": "Twelve Data (TLT, ETF obligations d'État US 20 ans et plus)"}
EN_POINTS = {"USD_10a", "USD_2a", "USD_taux_effectif", "USD_prime_terme"}
SOURCE_INDICATEURS = ("Twelve Data pour les 230 dernières séances (cours du jour), raccordé à la Fed H.10 pour la "
                      "profondeur de 5 ans ; USD = indice synthétique (moyenne inverse des 8 autres devises), même définition "
                      "sur toute la période")
EXPLICATION_RACCORD = ("Deux sources existent : Twelve Data (cours de clôture du jour, 230 séances) et la Fed H.10 (taux de midi "
                       "à New York, 5 ans, publiés avec une semaine de retard). Retenu : Twelve Data partout où il existe, car "
                       "c'est le cours du jour ; la Fed H.10 ne sert qu'à prolonger l'historique vers le passé, remise à "
                       "l'échelle au point de raccord pour ne créer aucun saut. Un seul chiffre est affiché partout.")                     # taux : variations en points, pas en logarithme
SEANCES_CORR = 30
MIN_FENETRES = 200
JOURS_COURBE = 120
ACTIFS_CORR = {"VIX": "vix", "S&P 500": "sp500", "Pétrole Brent": "brent", "Indice or (proxy)": "indice_or",
               "Rendement 10 ans US": "USD_10a"}
SOURCE_CORR = ("calcul Python : corrélation glissante sur 30 séances communes des rendements quotidiens, 5 ans de prix "
               "(FRED : Fed H.10 pour les devises, DTWEXBGS pour l'USD, VIXCLS, SP500, DCOILBRENTEU, NASDAQQGLDI, DGS10)")


# ------------------------------------------------------------------ stockage
def enregistrer(bruts: dict[str, list], chemin: Path | str = CHEMIN, aujourdhui: date | None = None) -> dict:
    """Écrit la fenêtre glissante des séries de SERIES présentes dans `bruts` ({nom: [(date, valeur)]}).
    Format compact : dates en décalage de jours depuis `debut`. Retourne {nom: nb de points}."""
    aujourdhui = aujourdhui or date.today()
    limite = aujourdhui - timedelta(days=FENETRE_JOURS)
    sortie, comptes = {}, {}
    for nom, source in SERIES.items():
        pts = sorted((str(d)[:10], float(v)) for d, v in bruts.get(nom) or [] if v is not None and str(d)[:10] >= limite.isoformat())
        if not pts:
            continue
        d0 = date.fromisoformat(pts[0][0])
        sortie[nom] = {"source": source, "debut": pts[0][0],
                       "jours": [(date.fromisoformat(d) - d0).days for d, _ in pts], "valeurs": [round(v, 6) for _, v in pts]}
        comptes[nom] = len(pts)
    contenu = {"version": 1, "ecrit_le": aujourdhui.isoformat(), "fenetre_jours": FENETRE_JOURS, "series": sortie}
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    Path(chemin).write_text(json.dumps(contenu, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return comptes


class Historique:
    """Séries quotidiennes chargées depuis le fichier (vide si absent : chaque calcul renvoie alors une raison)."""

    def __init__(self, contenu: dict | None):
        self.contenu = contenu or {}
        self._cache: dict[str, list[tuple[str, float]]] = {}

    @classmethod
    def depuis_points(cls, bruts: dict[str, list]) -> "Historique":
        """Historique en mémoire depuis {nom: [(date, valeur)]} (tests, collecte), sans passer par le fichier."""
        h = cls({"series": {n: {"debut": "x"} for n in bruts}})
        h._cache = {n: sorted((str(d)[:10], float(v)) for d, v in pts if v is not None) for n, pts in bruts.items()}
        return h

    @property
    def disponible(self) -> bool:
        return bool((self.contenu.get("series") or {}))

    def serie(self, nom: str) -> list[tuple[str, float]]:
        if nom not in self._cache:
            s = (self.contenu.get("series") or {}).get(nom) or {}
            d0 = date.fromisoformat(s["debut"]) if s.get("debut") else None
            self._cache[nom] = [((d0 + timedelta(days=j)).isoformat(), v) for j, v in zip(s.get("jours", []), s.get("valeurs", []))] if d0 else []
        return self._cache[nom]

    def source(self, nom: str) -> str | None:
        return ((self.contenu.get("series") or {}).get(nom) or {}).get("source")

    def _fed(self, devise: str) -> list[tuple[str, float]]:
        """Force Fed H.10 seule (dollars US par unité de devise)."""
        return [(d, (1 / v if devise in INVERSEES else v)) for d, v in self.serie(f"FX_{devise}") if v]

    def _usd_synthetique_fed(self) -> list[tuple[str, float]]:
        """Indice USD synthétique sur l'historique Fed : rendement = − moyenne des rendements des 8 autres devises
        (même définition que la collecte technique), base 100 au premier jour."""
        rend: dict[str, list[float]] = {}
        for devise in DEVISES:
            if devise == "USD":
                continue
            pts = self._fed(devise)
            for (_, a), (d, b) in zip(pts, pts[1:]):
                if a:
                    rend.setdefault(d, []).append(b / a - 1)
        niveau, sortie = 100.0, []
        for d in sorted(rend):
            if len(rend[d]) >= 6:                 # au moins 6 devises publiées ce jour-là
                niveau *= 1 - statistics.mean(rend[d])
                sortie.append((d, niveau))
        return sortie

    @staticmethod
    def _twelve(devise: str, technique: dict | None) -> list[tuple[str, float]]:
        t = (technique or {}).get("historique", {}).get(devise) or (technique or {}).get("graphiques", {}).get(devise) or {}
        return [(str(d)[:10], float(v)) for d, v in zip(t.get("dates") or [], t.get("clotures") or []) if v]

    def force(self, devise: str, technique: dict | None = None) -> list[tuple[str, float]]:
        """Série unique de la devise (dollars US par unité ; USD = indice synthétique) : Twelve Data pour toutes
        ses séances, Fed H.10 avant la première séance Twelve Data, remise à l'échelle au point de raccord."""
        fed = self._usd_synthetique_fed() if devise == "USD" else self._fed(devise)
        twelve = self._twelve(devise, technique)
        if not twelve:
            return fed
        debut = twelve[0][0]
        avant = [p for p in fed if p[0] < debut]
        ref = [p for p in fed if p[0] <= debut]
        if not avant or not ref:
            return twelve
        facteur = twelve[0][1] / ref[-1][1]
        return [(d, v * facteur) for d, v in avant] + twelve


def charger(chemin: Path | str = CHEMIN) -> Historique:
    try:
        return Historique(json.loads(Path(chemin).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return Historique(None)


# ---------------------------------------------------------------- indicateurs
def rsi(points: list[tuple[str, float]], periode: int = 14) -> list[tuple[str, float]]:
    """RSI de Wilder à chaque séance à partir de la (periode + 1)-ième."""
    if len(points) <= periode:
        return []
    valeurs = [v for _, v in points]
    gains = [max(b - a, 0) for a, b in zip(valeurs, valeurs[1:])]
    pertes = [max(a - b, 0) for a, b in zip(valeurs, valeurs[1:])]
    mg, mp = sum(gains[:periode]) / periode, sum(pertes[:periode]) / periode
    sortie = []
    for i in range(periode, len(gains) + 1):
        if i > periode:
            mg = (mg * (periode - 1) + gains[i - 1]) / periode
            mp = (mp * (periode - 1) + pertes[i - 1]) / periode
        sortie.append((points[i][0], round(100.0 if mp == 0 else 100 - 100 / (1 + mg / mp), 2)))
    return sortie


def ecart_moyenne(points: list[tuple[str, float]], n: int) -> list[tuple[str, float]]:
    """Écart en % du prix à sa moyenne mobile simple de n séances."""
    sortie, somme = [], 0.0
    for i, (d, v) in enumerate(points):
        somme += v
        if i >= n:
            somme -= points[i - n][1]
        if i >= n - 1:
            moyenne = somme / n
            sortie.append((d, round((v / moyenne - 1) * 100, 3)))
    return sortie


def volatilite(points: list[tuple[str, float]], n: int = 20) -> list[tuple[str, float]]:
    """Volatilité réalisée annualisée (%) sur n rendements logarithmiques."""
    rend = [(d, math.log(b / a)) for (_, a), (d, b) in zip(points, points[1:]) if a > 0 and b > 0]
    return [(rend[i][0], round(statistics.pstdev([r for _, r in rend[i - n + 1:i + 1]]) * math.sqrt(252) * 100, 2))
            for i in range(n - 1, len(rend))]


def resume(serie: list[tuple[str, float]], valeur: float | None = None, aujourdhui: date | None = None,
           jours_courbe: int = JOURS_COURBE, decimales: int = 2) -> dict:
    """Valeur (la dernière ou celle fournie), percentile parmi les 5 dernières années de la série, courbe récente."""
    if not serie:
        return {"valeur": None, "raison": "série 5 ans indisponible"}
    aujourdhui = aujourdhui or date.today()
    debut = (aujourdhui - timedelta(days=int(365.25 * ANNEES))).isoformat()
    fen = [v for d, v in serie if d >= debut]
    v0 = serie[-1][1] if valeur is None else valeur
    pct = round(100 * sum(1 for v in fen if v <= v0) / len(fen)) if len(fen) >= MIN_FENETRES else None
    limite = (date.fromisoformat(serie[-1][0]) - timedelta(days=jours_courbe)).isoformat()
    return {"valeur": round(v0, decimales), "date": serie[-1][0], "percentile_5a": pct, "n_5a": len(fen),
            "raison_percentile": None if pct is not None else f"moins de {MIN_FENETRES} observations sur 5 ans ({len(fen)})",
            "debut_5a": fen and serie[-len(fen)][0], "courbe": [[d, round(v, 2)] for d, v in serie if d >= limite]}


# ---------------------------------------------------------------- corrélations
def rendements(points: list[tuple[str, float]], en_points: bool = False) -> dict[str, float]:
    sortie = {}
    for (_, a), (d, b) in zip(points, points[1:]):
        if en_points:
            sortie[d] = b - a
        elif a > 0 and b > 0:
            sortie[d] = math.log(b / a)
    return sortie


def _corr(a: list[float], b: list[float]) -> float | None:
    try:
        return statistics.correlation(a, b)
    except statistics.StatisticsError:
        return None


def glissante(ra: dict[str, float], rb: dict[str, float], seances: int = SEANCES_CORR) -> list[tuple[str, float]]:
    communes = sorted(set(ra) & set(rb))
    sortie = []
    for i in range(seances, len(communes) + 1):
        fen = communes[i - seances:i]
        r = _corr([ra[d] for d in fen], [rb[d] for d in fen])
        if r is not None:
            sortie.append((fen[-1], round(r, 3)))
    return sortie


def _rendements_nommes(h: Historique, technique: dict | None) -> tuple[dict, dict]:
    force = {d: rendements(h.force(d, technique)) for d in DEVISES if h.force(d, technique)}
    actifs = {lib: rendements(h.serie(nom), nom in EN_POINTS) for lib, nom in ACTIFS_CORR.items() if h.serie(nom)}
    return force, actifs


def correlations(h: Historique, technique: dict | None = None, aujourdhui: date | None = None) -> dict:
    """Paires devise × actif : valeur du jour, valeur 30 séances plus tôt, percentile 5 ans, courbe 120 jours."""
    aujourdhui = aujourdhui or date.today()
    force, actifs = _rendements_nommes(h, technique)
    debut_5a = (aujourdhui - timedelta(days=int(365.25 * ANNEES))).isoformat()
    paires, absentes, fins = {}, [], []
    for devise in DEVISES:
        for actif in ACTIFS_CORR:
            if devise not in force or actif not in actifs:
                absentes.append(f"{devise} / {actif} : série {'de change' if devise not in force else actif} indisponible")
                continue
            serie = [(d, r) for d, r in glissante(force[devise], actifs[actif]) if d >= debut_5a]
            if not serie:
                absentes.append(f"{devise} / {actif} : moins de {SEANCES_CORR} séances communes")
                continue
            res = resume(serie, aujourdhui=aujourdhui)
            paires[f"{devise}|{actif}"] = {
                "valeur": res["valeur"], "date": res["date"], "percentile_5a": res["percentile_5a"], "n_5a": res["n_5a"],
                "raison_percentile": res["raison_percentile"], "debut": serie[0][0], "courbe": res["courbe"],
                "precedente": round(serie[-1 - SEANCES_CORR][1], 2) if len(serie) > SEANCES_CORR else None,
                "min_5a": round(min(r for _, r in serie), 2), "max_5a": round(max(r for _, r in serie), 2)}
            fins.append(res["date"])
    return {"seances": SEANCES_CORR, "paires": paires, "absentes": absentes, "source": SOURCE_CORR,
            "derniere_seance": max(fins) if fins else None, "calcule_le": aujourdhui.isoformat()}


INSTRUMENTS_MATRICE = [("vix", "VIX"), ("dollar_large", "Indice dollar large (Fed)"), ("indice_or", "Indice or (proxy)"),
                       ("wti", "Pétrole WTI"), ("brent", "Pétrole Brent"), ("sp500", "S&P 500"), ("USD_10a", "Rendement 10 ans US")]


def matrice(h: Historique, technique: dict | None = None, seances: int = SEANCES_CORR) -> dict | None:
    """Matrice complète (9 devises + 7 marchés) sur les 30 dernières séances communes de chaque paire, la fenêtre
    précédente, et les changements de signe marqués (|r| ≥ 0,3 des deux côtés). None si le fichier est absent."""
    if not h.disponible:
        return None
    series = {d: rendements(h.force(d, technique)) for d in DEVISES}
    series.update({lib: rendements(h.serie(nom), nom in EN_POINTS) for nom, lib in INSTRUMENTS_MATRICE})
    noms = [n for n in series if series[n]]
    m, prec, changements, fins = {}, {}, [], []
    for i, a in enumerate(noms):
        for b in noms[i + 1:]:
            communes = sorted(set(series[a]) & set(series[b]))
            fen, avant = communes[-seances:], communes[-2 * seances:-seances]
            r = _corr([series[a][d] for d in fen], [series[b][d] for d in fen]) if len(fen) >= 15 else None
            r0 = _corr([series[a][d] for d in avant], [series[b][d] for d in avant]) if len(avant) >= 15 else None
            r, r0 = (None if r is None else round(r, 2)), (None if r0 is None else round(r0, 2))
            if fen:
                fins.append(fen[-1])
            m.setdefault(a, {})[b] = m.setdefault(b, {})[a] = r
            prec.setdefault(a, {})[b] = prec.setdefault(b, {})[a] = r0
            if r is not None and r0 is not None and abs(r) >= 0.3 and abs(r0) >= 0.3 and (r > 0) != (r0 > 0):
                changements.append({"paire": [a, b], "avant": r0, "maintenant": r})
    return {"noms": noms, "matrice": m, "matrice_precedente": prec, "seances": seances,
            "derniere_seance": max(fins) if fins else None, "changements_de_signe": changements,
            "source": "calcul Python sur l'historique quotidien 5 ans (Fed H.10 prolongée par Twelve Data pour les devises ; "
                      "USD = indice dollar large de la Fed ; FRED pour les marchés)"}


def indicateurs_techniques(h: Historique, devise: str, technique: dict | None = None) -> dict:
    """RSI 14, écarts aux MM100 et MM200, volatilité 20 j : valeur du jour ET percentile 5 ans, sur la série
    unique de la devise. C'est la SEULE source de ces indicateurs sur le site (onglet Devises, dossier 7)."""
    pts = h.force(devise, technique)
    if len(pts) < 260:
        raison = "historique quotidien 5 ans indisponible" if not pts else f"historique trop court ({len(pts)} séances)"
        return {k: {"valeur": None, "raison": raison} for k in ("rsi", "ecart_mm100", "ecart_mm200", "volatilite")}
    sortie = {"rsi": resume(rsi(pts), decimales=1), "ecart_mm100": resume(ecart_moyenne(pts, 100)),
              "ecart_mm200": resume(ecart_moyenne(pts, 200)), "volatilite": resume(volatilite(pts, 20), decimales=1)}
    for n in (100, 200):
        sortie[f"mm{n}"] = round(statistics.mean(v for _, v in pts[-n:]), 5)
    sortie["dernier"] = round(pts[-1][1], 5)
    sortie["date"] = pts[-1][0]
    return sortie


def harmoniser_technique(technique: dict, h: Historique) -> dict:
    """Remplace dans la collecte technique les indicateurs de chaque devise par ceux de la série unique 5 ans
    (même valeur ensuite pour les scores, l'analyse, l'onglet Devises et le dossier 7). Retourne
    {devise: {avant, apres}} pour le RSI quand il change (journal)."""
    changes = {}
    if not h.disponible:
        return changes
    for devise, t in ((technique or {}).get("devises") or {}).items():
        ind = indicateurs_techniques(h, devise, technique)
        if (ind.get("rsi") or {}).get("valeur") is None:
            t["indicateurs_source"] = {"source": "Twelve Data (230 séances)", "raison": ind["rsi"].get("raison"),
                                       "percentiles": None}
            continue
        r = ind["rsi"]["valeur"]
        if t.get("rsi") is not None and round(t["rsi"], 1) != r:
            changes[devise] = {"avant": t["rsi"], "apres": r}
        t.update({"rsi": r,
                  "rsi_lecture": ("surachat" if r > 70 else "survente" if r < 30 else
                                  "momentum haussier" if r > 50 else "momentum baissier"),
                  "mm100": ind["mm100"], "mm200": ind["mm200"],
                  "prix_vs_mm200": "au-dessus" if t.get("dernier", ind["dernier"]) > ind["mm200"] else "en dessous",
                  "ecart_mm100_pct": ind["ecart_mm100"]["valeur"], "ecart_mm200_pct": ind["ecart_mm200"]["valeur"],
                  "volatilite_20j": ind["volatilite"]["valeur"],
                  "indicateurs_source": {"source": SOURCE_INDICATEURS, "date": ind["date"], "explication": EXPLICATION_RACCORD,
                                         "percentiles": {k: ind[k]["percentile_5a"] for k in ("rsi", "ecart_mm100", "ecart_mm200", "volatilite")}}})
    return changes
