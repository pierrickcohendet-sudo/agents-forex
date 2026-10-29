"""Technique multi-unités (Rapport du jour, étape 9) : NIVEAUX affichés sur les chandeliers, jamais des signaux.

Entrées : bougies Twelve Data déjà collectées pour « Mes paires » ([date UTC, ouverture, haut, bas, clôture]) en 30 min,
4 h et 1 jour, et la série journalière unique 5 ans pour les tendances. Calcul Python, sans requête ni LLM.

Définitions (affichées au survol sur le site) :
- veille / semaine précédente : plus haut et plus bas de la dernière journée UTC complète / de la semaine ISO précédente ;
- sessions (heures fixes UTC) : Asie 00:00-08:00, Londres 07:00-16:00, New York 12:00-21:00, sur la dernière journée
  qui a des bougies 30 min ;
- pivot (swing) : un plus haut (plus bas) plus haut (plus bas) que les PIVOT_N bougies de chaque côté ;
- BOS (cassure de structure) : clôture au-delà du dernier pivot dans le sens de la tendance en cours ;
- CHoCH (changement de caractère) : première clôture au-delà du dernier pivot opposé à la tendance en cours ;
- FVG (zone de déséquilibre, 3 bougies) : haussière si le bas de la 3e bougie dépasse le haut de la 1re (zone entre les
  deux), baissière à l'inverse ; « ouverte » tant qu'aucune bougie suivante ne l'a entièrement comblée ;
- tendance : position de la clôture face aux moyennes mobiles 50 et 200, pente de la MM50 sur 5 périodes.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

PIVOT_N = 2
SESSIONS = {"Asie": (0, 8), "Londres": (7, 16), "New York": (12, 21)}
DEFINITIONS = {
    "veille": "Plus haut et plus bas de la dernière journée UTC complète.",
    "semaine": "Plus haut et plus bas de la semaine ISO précédente.",
    "sessions": "Heures fixes UTC : Asie 00:00-08:00, Londres 07:00-16:00, New York 12:00-21:00.",
    "pivot": f"Pivot : plus haut (plus bas) qui dépasse les {PIVOT_N} bougies de chaque côté.",
    "bos": "BOS (cassure de structure) : clôture au-delà du dernier pivot, dans le sens de la tendance en cours.",
    "choch": "CHoCH (changement de caractère) : première clôture au-delà du dernier pivot opposé à la tendance.",
    "fvg": "FVG (zone de déséquilibre à 3 bougies) : écart entre la 1re et la 3e bougie ; ouverte tant qu'elle n'est pas comblée.",
    "tendance": "Clôture face aux moyennes mobiles 50 et 200, pente de la MM50 sur 5 périodes.",
}
MENTION = "Niveaux techniques affichés sur les chandeliers : des repères, pas des signaux d'achat ou de vente."


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "").replace(" ", "T")[:19])


def haut_bas(bougies: list[list]) -> dict | None:
    if not bougies:
        return None
    return {"haut": max(b[2] for b in bougies), "bas": min(b[3] for b in bougies),
            "du": str(bougies[0][0])[:16], "au": str(bougies[-1][0])[:16]}


def veille(bougies_30m: list[list], maintenant: datetime | None = None) -> dict | None:
    """Dernière journée UTC complète (avant la journée de la dernière bougie)."""
    if not bougies_30m:
        return None
    derniere = _dt(bougies_30m[-1][0]).date()
    jours = sorted({_dt(b[0]).date() for b in bougies_30m if _dt(b[0]).date() < derniere})
    if not jours:
        return None
    j = jours[-1]
    r = haut_bas([b for b in bougies_30m if _dt(b[0]).date() == j])
    return {**r, "jour": j.isoformat()} if r else None


def semaine_precedente(bougies_1j: list[list]) -> dict | None:
    if not bougies_1j:
        return None
    sem = _dt(bougies_1j[-1][0]).date().isocalendar()[:2]
    prec = sorted({_dt(b[0]).date().isocalendar()[:2] for b in bougies_1j if _dt(b[0]).date().isocalendar()[:2] < sem})
    if not prec:
        return None
    r = haut_bas([b for b in bougies_1j if _dt(b[0]).date().isocalendar()[:2] == prec[-1]])
    return {**r, "semaine": f"{prec[-1][0]}-S{prec[-1][1]:02d}"} if r else None


def sessions(bougies_30m: list[list]) -> dict:
    """Plus haut / plus bas de chaque session sur la dernière journée UTC qui a des bougies."""
    if not bougies_30m:
        return {}
    j = _dt(bougies_30m[-1][0]).date()
    sortie = {}
    for nom, (h0, h1) in SESSIONS.items():
        bs = [b for b in bougies_30m if _dt(b[0]).date() == j and h0 <= _dt(b[0]).hour < h1]
        r = haut_bas(bs)
        sortie[nom] = {**r, "jour": j.isoformat(), "complete": bool(bs) and _dt(bs[-1][0]).hour >= h1 - 1} if r else None
    return sortie


def pivots(bougies: list[list], n: int = PIVOT_N) -> list[dict]:
    sortie = []
    for i in range(n, len(bougies) - n):
        h, l = bougies[i][2], bougies[i][3]
        voisins = bougies[i - n:i] + bougies[i + 1:i + n + 1]
        if all(h > v[2] for v in voisins):
            sortie.append({"type": "haut", "i": i, "date": str(bougies[i][0])[:16], "niveau": h})
        if all(l < v[3] for v in voisins):
            sortie.append({"type": "bas", "i": i, "date": str(bougies[i][0])[:16], "niveau": l})
    return sortie


def structure(bougies: list[list], n: int = PIVOT_N) -> dict:
    """Suit la tendance de structure ; liste les BOS et CHoCH (date, niveau cassé). Un pivot n'est connu que n
    bougies après sa formation : il ne sert qu'à partir de là (pas de regard vers l'avenir)."""
    pv = pivots(bougies, n)
    tendance, evenements = None, []
    dernier_haut = dernier_bas = None
    for i, b in enumerate(bougies):
        for p in pv:
            if p["i"] + n == i:   # pivot confirmé à cette bougie
                if p["type"] == "haut":
                    dernier_haut = p
                else:
                    dernier_bas = p
        cloture = b[4]
        if dernier_haut and cloture > dernier_haut["niveau"]:
            evenements.append({"type": "BOS" if tendance in (None, "haussière") else "CHoCH", "sens": "haussier",
                               "date": str(b[0])[:16], "niveau": dernier_haut["niveau"], "pivot_du": dernier_haut["date"]})
            tendance, dernier_haut = "haussière", None
        elif dernier_bas and cloture < dernier_bas["niveau"]:
            evenements.append({"type": "BOS" if tendance in (None, "baissière") else "CHoCH", "sens": "baissier",
                               "date": str(b[0])[:16], "niveau": dernier_bas["niveau"], "pivot_du": dernier_bas["date"]})
            tendance, dernier_bas = "baissière", None
    hauts = [p for p in pv if p["type"] == "haut"][-2:]
    bas = [p for p in pv if p["type"] == "bas"][-2:]
    return {"tendance_structure": tendance, "evenements": evenements[-4:], "derniers_hauts": hauts, "derniers_bas": bas}


def fvg(bougies: list[list], max_n: int = 3) -> list[dict]:
    """Zones de déséquilibre ouvertes, les plus récentes d'abord."""
    ouvertes = []
    for i in range(2, len(bougies)):
        a, c = bougies[i - 2], bougies[i]
        if c[3] > a[2]:
            z = {"sens": "haussière", "bas": a[2], "haut": c[3], "date": str(bougies[i - 1][0])[:16]}
            comblee = any(x[3] <= z["bas"] for x in bougies[i + 1:])
        elif c[2] < a[3]:
            z = {"sens": "baissière", "bas": c[2], "haut": a[3], "date": str(bougies[i - 1][0])[:16]}
            comblee = any(x[2] >= z["haut"] for x in bougies[i + 1:])
        else:
            continue
        if not comblee:
            ouvertes.append(z)
    return list(reversed(ouvertes))[:max_n]


def _mm(valeurs: list[float], n: int) -> float | None:
    return sum(valeurs[-n:]) / n if len(valeurs) >= n else None


def tendance(closes: list[float], libelle: str) -> dict:
    """Clôture contre MM50 / MM200, pente de la MM50 sur 5 périodes."""
    if len(closes) < 55:
        return {"unite": libelle, "raison": f"{len(closes)} points : pas assez pour la MM50"}
    mm50, mm200 = _mm(closes, 50), _mm(closes, 200)
    pente = mm50 - _mm(closes[:-5], 50)
    dernier = closes[-1]
    if mm200 is not None:
        lecture = ("haussière" if dernier > mm50 > mm200 and pente > 0 else
                   "baissière" if dernier < mm50 < mm200 and pente < 0 else "sans tendance nette")
    else:
        lecture = "haussière" if dernier > mm50 and pente > 0 else "baissière" if dernier < mm50 and pente < 0 else "sans tendance nette"
    return {"unite": libelle, "cloture": dernier, "mm50": round(mm50, 6), "mm200": round(mm200, 6) if mm200 else None,
            "pente_mm50": "montante" if pente > 0 else "descendante" if pente < 0 else "plate", "lecture": lecture,
            "raison_mm200": None if mm200 else f"{len(closes)} points : MM200 non calculable"}


def hebdomadaires(points_jour: list[tuple[str, float]]) -> list[float]:
    """Dernière clôture de chaque semaine ISO."""
    sem = {}
    for d, v in points_jour:
        sem[date.fromisoformat(str(d)[:10]).isocalendar()[:2]] = v
    return [v for _, v in sorted(sem.items())]


def calculer(chandeliers: dict | None, points_jour: list[tuple[str, float]] | None) -> dict:
    """Niveaux d'une paire. chandeliers : {"30min": {"bougies": [...]}, "4h": {...}, "1j": {...}}."""
    ch = chandeliers or {}
    b30 = (ch.get("30min") or {}).get("bougies") or []
    b4h = (ch.get("4h") or {}).get("bougies") or []
    b1j = (ch.get("1j") or {}).get("bougies") or []
    closes = [v for _, v in (points_jour or [])]
    sortie = {"definitions": DEFINITIONS, "mention": MENTION,
              "veille": veille(b30) or (haut_bas(b1j[-2:-1]) if len(b1j) > 1 else None),
              "semaine_precedente": semaine_precedente(b1j), "sessions": sessions(b30),
              "structure_h4": structure(b4h) if len(b4h) > 2 * PIVOT_N + 1 else None,
              "fvg_h4": fvg(b4h), "fvg_m30": fvg(b30),
              "tendance_jour": tendance(closes, "1 j"), "tendance_semaine": tendance(hebdomadaires(points_jour or []), "1 sem.")}
    if not (b30 or b4h or b1j):
        sortie["raison"] = "chandeliers non collectés pour cette paire (réservés à « Mes paires »)"
    return sortie
