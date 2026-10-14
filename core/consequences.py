"""Tableau des conséquences (refonte V2, §9a) : calcul Python sur 5 ans, sans LLM.

Pour chaque engrenage, un « moteur » (série chiffrée) et 6 à 8 actifs. Par actif :
- sensibilité : corrélation, sur 5 ans, entre la variation sur 1 mois du moteur et celle de l'actif
  (points mensuels non chevauchants) ;
- si le moteur monte / baisse : variation MÉDIANE de l'actif sur le mois qui suit une variation du
  moteur d'au moins 1 écart-type sur 1 mois (épisodes espacés d'au moins 30 jours) ;
- fiabilité : part des épisodes où l'actif a bougé dans le sens attendu (signe de la sensibilité),
  avec le nombre de cas ; sous 20 cas : « échantillon insuffisant » ;
- aujourd'hui : Soutien / Pression / Neutre selon la variation du moteur sur le dernier mois.
Séries : core/historique_5ans.py (série unique par devise) et historiques longs. Corrélation n'est pas
causalité ; un moteur ou un actif sans série longue affiche « n/d » avec la raison.
"""
from __future__ import annotations

import bisect
import math
import statistics
from datetime import date, timedelta

from core import historique_5ans as h5m

HORIZON_JOURS = 30
ESPACEMENT_JOURS = 30
MIN_CAS_FIABILITE = 20
MIN_CAS_MEDIANE = 5
SEUIL_FIABILITE = 55   # « Aujourd'hui » : Soutien ou Pression seulement si le sens attendu s'est vérifié ≥ 55 % du temps
NOTE = "Corrélation n'est pas causalité : ces chiffres décrivent le passé récent (5 ans), ils ne prévoient rien."

DEVISES = h5m.DEVISES
MARCHES = {"S&P 500": ("sp500", "%"), "Or (proxy)": ("indice_or", "%"), "Brent": ("brent", "%"), "10 ans US": ("USD_10a", "pb")}
ACTIFS = {2: ["USD", "EUR", "JPY", "GBP", "AUD", "S&P 500", "Or (proxy)", "10 ans US"],
          4: ["USD", "EUR", "JPY", "CHF", "S&P 500", "Or (proxy)", "10 ans US", "Écart Italie − Allemagne"],
          5: ["USD", "JPY", "CHF", "AUD", "NZD", "CAD", "S&P 500", "Or (proxy)"],
          6: ["CAD", "JPY", "EUR", "USD", "AUD", "S&P 500", "Or (proxy)", "10 ans US"],
          8: ["CAD", "USD", "JPY", "Brent", "S&P 500", "Or (proxy)"],
          1: ["USD", "EUR", "JPY", "AUD", "CAD", "S&P 500"], 3: ["USD", "EUR", "GBP", "JPY", "S&P 500", "10 ans US"],
          7: ["AUD", "EUR", "JPY", "GBP", "CAD", "CHF"]}
MOTEURS_ND = {1: ("score de confluence USD", "scores archivés depuis août 2026 seulement : pas 5 ans d'historique"),
              3: ("indice de surprise US 30 jours", "indice calculé depuis 2026 seulement : pas 5 ans d'historique"),
              7: ("positionnement COT (lecture contrarienne)", "historique COT de 26 semaines seulement : les 5 ans de la CFTC ne sont pas collectés")}


# ----------------------------------------------------------------- séries
class _Serie:
    """Série datée avec lecture de la dernière valeur connue à une date (recherche dichotomique)."""

    def __init__(self, points: list[tuple[str, float]], unite: str):
        self.points = sorted((str(d)[:10], float(v)) for d, v in points if v is not None)
        self.dates = [d for d, _ in self.points]
        self.unite = unite   # "%" : variation logarithmique en % ; "pb" ou "pts" : différence

    def a(self, jour: str) -> float | None:
        i = bisect.bisect_right(self.dates, jour)
        return self.points[i - 1][1] if i else None

    def variation(self, debut: str, fin: str) -> float | None:
        a, b = self.a(debut), self.a(fin)
        if a is None or b is None:
            return None
        if self.unite == "%":
            return math.log(b / a) * 100 if a > 0 and b > 0 else None
        return (b - a) * (100 if self.unite == "pb" else 1)


def _plus(jour: str, jours: int) -> str:
    return (date.fromisoformat(jour) + timedelta(days=jours)).isoformat()


def _difference(a: list, b: list) -> list[tuple[str, float]]:
    sb = _Serie(b, "pts")
    return [(d, v - sb.a(d)) for d, v in a if sb.a(d) is not None]


def _stocks_saisonniers(historiques: dict) -> list[tuple[str, float]]:
    """Écart (%) des stocks de brut US à la moyenne des mêmes semaines des 5 années précédentes (≥ 4 années)."""
    pts = [(d, float(v)) for d, v in (((historiques or {}).get("series") or {}).get("eia_stocks") or {}).get("points") or []]
    par_semaine: dict[tuple[int, int], float] = {}
    for d, v in pts:
        a, s, _ = date.fromisoformat(d).isocalendar()
        par_semaine[(a, s)] = v
    sortie = []
    for d, v in pts:
        a, s, _ = date.fromisoformat(d).isocalendar()
        ref = [par_semaine[(a - k, s)] for k in range(1, 6) if (a - k, s) in par_semaine]
        if len(ref) >= 4:
            sortie.append((d, (v / statistics.mean(ref) - 1) * 100))
    return sortie


def moteurs(h: h5m.Historique, historiques: dict) -> dict:
    """{numéro: (libellé, _Serie, source)} pour les moteurs à 5 ans ; les autres sont dans MOTEURS_ND."""
    sortie = {}
    us2, dff = h.serie("USD_2a"), h.serie("USD_taux_effectif")
    if us2 and dff:
        sortie[2] = ("écart 2 ans US − taux effectif Fed", _Serie(_difference(us2, dff), "pb"), "FRED (DGS2 − DFF)")
    if h.serie("USD_prime_terme"):
        sortie[4] = ("prime de terme 10 ans US", _Serie(h.serie("USD_prime_terme"), "pb"), "FRED (THREEFYTP10)")
    if h.serie("vix"):
        sortie[5] = ("VIX", _Serie(h.serie("vix"), "pts"), "FRED (VIXCLS)")
    if h.serie("brent"):
        sortie[6] = ("Brent", _Serie(h.serie("brent"), "%"), "FRED (DCOILBRENTEU)")
    stocks = _stocks_saisonniers(historiques)
    if stocks:
        sortie[8] = ("stocks de brut US contre la moyenne saisonnière 5 ans", _Serie(stocks, "pts"), "EIA (WCESTUS1), calcul Python")
    return sortie


def actif(h: h5m.Historique, historiques: dict, technique: dict | None, nom: str) -> tuple[_Serie | None, str | None]:
    if nom in DEVISES:
        pts = h.force(nom, technique)
        return (_Serie(pts, "%"), None) if pts else (None, "série de change 5 ans indisponible")
    if nom in MARCHES:
        cle, unite = MARCHES[nom]
        pts = h.serie(cle)
        return (_Serie(pts, unite), None) if pts else (None, "série 5 ans indisponible")
    if nom == "Écart Italie − Allemagne":
        s = (historiques or {}).get("series") or {}
        it = [(d, v) for d, v in (s.get("ITA_10a_mensuel") or {}).get("points") or []]
        de = [(d, v) for d, v in (s.get("DEU_10a_mensuel") or {}).get("points") or []]
        return (_Serie(_difference(it, de), "pb"), None) if it and de else (None, "séries OCDE mensuelles indisponibles")
    return None, "actif inconnu"


# ----------------------------------------------------------------- calcul
def _mensuels(debut: str, fin: str) -> list[str]:
    jours, d = [], date.fromisoformat(debut)
    while d.isoformat() <= fin:
        jours.append(d.isoformat())
        d += timedelta(days=HORIZON_JOURS)
    return jours


def ligne_actif(moteur: _Serie, cible: _Serie, debut: str, fin: str) -> dict:
    # Sensibilité : variations sur 1 mois, points non chevauchants
    paires = []
    for j in _mensuels(debut, fin)[1:]:
        dm, da = moteur.variation(_plus(j, -HORIZON_JOURS), j), cible.variation(_plus(j, -HORIZON_JOURS), j)
        if dm is not None and da is not None:
            paires.append((dm, da))
    try:
        sensibilite = round(statistics.correlation([p[0] for p in paires], [p[1] for p in paires]), 2) if len(paires) >= 12 else None
    except statistics.StatisticsError:
        sensibilite = None
    # Épisodes : variation du moteur sur 1 mois d'au moins 1 écart-type, espacés de 30 jours, suite connue
    variations = [(d, moteur.variation(_plus(d, -HORIZON_JOURS), d)) for d in moteur.dates if debut <= d <= fin]
    variations = [(d, v) for d, v in variations if v is not None]
    if len(variations) < 60:
        return {"raison": "historique du moteur trop court"}
    sigma = statistics.pstdev([v for _, v in variations])
    hausses, baisses, dernier = [], [], None
    for d, v in variations:
        if abs(v) < sigma or (dernier and d < _plus(dernier, ESPACEMENT_JOURS)) or _plus(d, HORIZON_JOURS) > fin:
            continue
        suite = cible.variation(d, _plus(d, HORIZON_JOURS))
        if suite is None:
            continue
        (hausses if v > 0 else baisses).append(suite)
        dernier = d
    n = len(hausses) + len(baisses)

    def mediane(cas):
        return {"mediane": round(statistics.median(cas), 2) if len(cas) >= MIN_CAS_MEDIANE else None, "n": len(cas),
                "raison": None if len(cas) >= MIN_CAS_MEDIANE else f"moins de {MIN_CAS_MEDIANE} cas ({len(cas)})"}

    if sensibilite is None or abs(sensibilite) < 0.1:
        fiab = {"part": None, "n": n, "raison": "pas de sens attendu (sensibilité nulle ou non calculable)"}
    elif n < MIN_CAS_FIABILITE:
        fiab = {"part": None, "n": n, "raison": f"échantillon insuffisant ({n} cas, minimum {MIN_CAS_FIABILITE})"}
    else:
        signe = 1 if sensibilite > 0 else -1
        bons = sum(1 for x in hausses if x * signe > 0) + sum(1 for x in baisses if x * signe < 0)
        fiab = {"part": round(100 * bons / n), "n": n, "raison": None}
    return {"sensibilite": sensibilite, "n_mois": len(paires), "si_hausse": mediane(hausses), "si_baisse": mediane(baisses),
            "fiabilite": fiab, "sigma_moteur": round(sigma, 2)}


def _aujourdhui(moteur: _Serie, sigma: float | None, ligne: dict, fin: str) -> dict:
    v = moteur.variation(_plus(fin, -HORIZON_JOURS), fin)
    if v is None or not sigma:
        return {"lecture": "n/d", "raison": "variation du moteur sur le dernier mois indisponible"}
    if abs(v) < sigma:
        return {"lecture": "Neutre", "raison": f"moteur dans ±1 écart-type sur 1 mois ({v:+.2f} contre ±{sigma:.2f})".replace(".", ",").replace("-", "−")}
    cote = ligne.get("si_hausse" if v > 0 else "si_baisse") or {}
    fiab = ligne.get("fiabilite") or {}
    if fiab.get("part") is None or cote.get("mediane") is None:
        return {"lecture": "n/d", "raison": fiab.get("raison") or cote.get("raison")}
    sens = "hausse" if v > 0 else "baisse"
    unite = ligne.get("unite", "%")
    mediane = f"{cote['mediane']:+.2f} {unite}".replace(".", ",").replace("-", "−")
    attendu = (1 if ligne["sensibilite"] > 0 else -1) * (1 if v > 0 else -1)
    if cote["mediane"] * attendu <= 0:
        return {"lecture": "Neutre", "raison": f"moteur en {sens} de plus d'1 écart-type, mais la médiane historique ({mediane}) "
                                               "contredit le sens de la sensibilité : lecture non tranchée"}
    if fiab["part"] < SEUIL_FIABILITE:
        return {"lecture": "Neutre", "raison": f"moteur en {sens} de plus d'1 écart-type, mais fiabilité de {fiab['part']} % "
                                               f"seulement (seuil {SEUIL_FIABILITE} %)"}
    return {"lecture": "Soutien" if cote["mediane"] > 0 else "Pression",
            "raison": f"moteur en {sens} de plus d'1 écart-type sur 1 mois ; médiane historique de l'actif {mediane}, "
                      f"sens vérifié dans {fiab['part']} % des {fiab['n']} cas"}


def calculer(h: h5m.Historique, historiques: dict, technique: dict | None = None, aujourdhui: date | None = None) -> dict:
    """{numéro d'engrenage (str): tableau}. Ne lève pas : un actif en échec n'affecte que sa ligne."""
    fin = (aujourdhui or date.today()).isoformat()
    debut = (date.fromisoformat(fin) - timedelta(days=int(365.25 * 5))).isoformat()
    mots = moteurs(h, historiques) if h.disponible else {}
    sortie = {}
    for n in range(1, 9):
        if n not in mots:
            libelle, raison = MOTEURS_ND.get(n, ("moteur", "historique 5 ans indisponible"))
            sortie[str(n)] = {"moteur": {"libelle": libelle, "raison": raison}, "lignes": [], "note": NOTE}
            continue
        libelle, moteur, source = mots[n]
        lignes = []
        for nom in ACTIFS[n]:
            cible, raison = actif(h, historiques, technique, nom)
            if cible is None:
                lignes.append({"actif": nom, "raison": raison})
                continue
            try:
                l = ligne_actif(moteur, cible, debut, fin)
            except Exception as exc:  # noqa: BLE001
                l = {"raison": f"calcul en échec : {exc}"[:120]}
            l["actif"] = nom
            l["unite"] = "pb" if cible.unite == "pb" else "%"
            if "raison" not in l or l.get("sensibilite") is not None:
                l["aujourdhui"] = _aujourdhui(moteur, l.get("sigma_moteur"), l, moteur.dates[-1] if moteur.dates else fin)
            lignes.append(l)
        v = moteur.variation(_plus(moteur.dates[-1], -HORIZON_JOURS), moteur.dates[-1]) if moteur.dates else None
        sortie[str(n)] = {"moteur": {"libelle": libelle, "source": source, "unite": moteur.unite, "date": moteur.dates[-1] if moteur.dates else None,
                                     "variation_1m": None if v is None else round(v, 2), "debut": debut},
                          "lignes": lignes, "note": NOTE,
                          "methode": ("Épisodes : variation du moteur sur 1 mois d'au moins 1 écart-type (calculé sur 5 ans), espacés "
                                      "d'au moins 30 jours ; mouvement médian de l'actif sur le mois suivant. Devises : force de la "
                                      "devise (hausse = la devise s'apprécie) ; marchés : hausse du prix ou du taux. Moins de "
                                      f"{MIN_CAS_FIABILITE} cas : échantillon insuffisant.")}
    return sortie
