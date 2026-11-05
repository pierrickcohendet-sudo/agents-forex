"""Page Paire (lot V8.2) : RSI de Wilder, ATR, pivots (fractales), zones de supports et résistances, lignes de tendance
et divergences. Fonctions PURES (aucune requête, aucun modèle), testées dans tests/test_v82.py ; le site ne fait que
dessiner ce qui est publié ici. Bougies : [[horodatage UTC, ouverture, haut, bas, clôture], ...] dans l'ordre du temps.

Tout est un repère tracé automatiquement à partir des pivots, jamais un signal d'achat ou de vente.
"""
from __future__ import annotations

from datetime import datetime

PERIODE_RSI = 14
PERIODE_ATR = 14
FRACTALE = {"30min": 3, "4h": 3, "1j": 5}          # bougies de chaque côté d'un pivot
TOLERANCE_ZONE_ATR = 0.25                           # pivots regroupés en zone à moins de 0,25 × ATR
TOLERANCE_CONTACT_ATR = 0.2                         # contact d'une ligne de tendance à moins de 0,2 × ATR
ZONES_PAR_COTE = 3
DIVERGENCE_FENETRE = 60                             # écart maximal (bougies) entre les deux pivots comparés
DIVERGENCE_RECENTE = 40                             # le second pivot doit être parmi les 40 dernières bougies
CASSURE_VISIBLE = 5                                 # ligne cassée : affichée en pointillés moins de 5 bougies
MENTION = "Supports, résistances et lignes de tendance sont tracés automatiquement à partir des pivots : des repères, pas des signaux."
DEFINITIONS = {
    "rsi": "RSI 14 de Wilder : moyennes lissées des hausses et des baisses de clôture sur 14 bougies.",
    "pivot": "Pivot (fractale) : plus haut (plus bas) qui dépasse les 3 bougies de chaque côté en 4 h, 5 en 1 jour.",
    "zone": "Zone : pivots distants de moins de 0,25 × l'ATR 14 regroupés ; force 1 à 3 selon les contacts et la récence.",
    "ligne": "Ligne de tendance : par les deux derniers creux montants (support) ou sommets descendants (résistance) ; "
             "valide tant qu'aucune clôture ne l'a franchie depuis son second point.",
    "divergence": "Divergence : deux derniers pivots confirmés du prix et RSI aux mêmes bougies ; haussière si le prix fait "
                  "plus bas et le RSI plus haut, baissière à l'inverse.",
}


def _dt(s) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "").replace(" ", "T")[:19])


def jjmm(s) -> str:
    s = str(s)
    return f"{s[8:10]}/{s[5:7]}"


def taille_pip(paire: str) -> float:
    return 0.01 if paire.endswith("JPY") else 0.0001


# ------------------------------------------------------------------ RSI et ATR (Wilder)
def rsi_wilder(clotures: list[float], n: int = PERIODE_RSI) -> list[float | None]:
    """RSI aligné sur les clôtures (None tant que n variations manquent). Première moyenne : moyenne simple des n
    premières hausses et baisses ; ensuite lissage de Wilder : moy = (moy × (n − 1) + valeur) / n."""
    sortie: list[float | None] = [None] * len(clotures)
    if len(clotures) <= n:
        return sortie
    hausses = [max(b - a, 0.0) for a, b in zip(clotures, clotures[1:])]
    baisses = [max(a - b, 0.0) for a, b in zip(clotures, clotures[1:])]
    mh, mb = sum(hausses[:n]) / n, sum(baisses[:n]) / n
    for i in range(n, len(clotures)):
        if i > n:
            mh = (mh * (n - 1) + hausses[i - 1]) / n
            mb = (mb * (n - 1) + baisses[i - 1]) / n
        sortie[i] = round(100.0 if mb == 0 else 100 - 100 / (1 + mh / mb), 2)
    return sortie


def atr_wilder(bougies: list[list], n: int = PERIODE_ATR) -> float | None:
    """ATR 14 de Wilder à la dernière bougie (étendue vraie lissée)."""
    if len(bougies) <= n:
        return None
    tr = [max(b[2] - b[3], abs(b[2] - a[4]), abs(b[3] - a[4])) for a, b in zip(bougies, bougies[1:])]
    atr = sum(tr[:n]) / n
    for v in tr[n:]:
        atr = (atr * (n - 1) + v) / n
    return atr


# ------------------------------------------------------------------ pivots (fractales)
def pivots(bougies: list[list], n: int) -> list[dict]:
    """Pivots confirmés : n bougies de chaque côté (un pivot n'existe qu'une fois les n bougies suivantes connues)."""
    sortie = []
    for i in range(n, len(bougies) - n):
        h, l = bougies[i][2], bougies[i][3]
        voisins = bougies[i - n:i] + bougies[i + 1:i + n + 1]
        if all(h > v[2] for v in voisins):
            sortie.append({"type": "haut", "i": i, "date": str(bougies[i][0])[:16], "prix": h})
        if all(l < v[3] for v in voisins):
            sortie.append({"type": "bas", "i": i, "date": str(bougies[i][0])[:16], "prix": l})
    return sortie


# ------------------------------------------------------------------ zones de supports et résistances
def force_zone(contacts: int, rang_dernier: int, nb_bougies: int) -> int:
    """1 à 3 : nombre de contacts (1, 2, 3 et plus), moins 1 si le dernier contact date de la première moitié de la
    période observée (zone ancienne) ; jamais moins de 1."""
    f = min(contacts, 3)
    if nb_bougies and rang_dernier < nb_bougies / 2:
        f -= 1
    return max(1, f)


def zones(bougies: list[list], n: int, paire: str = "", atr: float | None = None) -> dict:
    """Regroupe les pivots proches en zones ; garde les 3 plus proches au-dessus (R1-R3) et en dessous (S1-S3)."""
    atr = atr if atr is not None else atr_wilder(bougies)
    if not bougies or not atr:
        return {"raison": "bougies insuffisantes pour l'ATR 14", "resistances": [], "supports": []}
    tol = TOLERANCE_ZONE_ATR * atr
    pv = sorted(pivots(bougies, n), key=lambda p: p["prix"])
    groupes: list[list[dict]] = []
    for p in pv:
        if groupes and p["prix"] - groupes[-1][-1]["prix"] < tol:
            groupes[-1].append(p)
        else:
            groupes.append([p])
    cours, pip = bougies[-1][4], taille_pip(paire)
    tout = []
    for g in groupes:
        dernier = max(g, key=lambda p: p["i"])
        z = {"haut": max(p["prix"] for p in g), "bas": min(p["prix"] for p in g), "contacts": len(g),
             "dernier_contact": dernier["date"], "force": force_zone(len(g), dernier["i"], len(bougies))}
        milieu = (z["haut"] + z["bas"]) / 2
        bord = z["bas"] if milieu > cours else z["haut"]
        z["distance_pips"] = round((bord - cours) / pip, 1)
        z["distance_pct"] = round((bord - cours) / cours * 100, 2)
        z["cote"] = "resistance" if milieu > cours else "support"
        tout.append(z)
    res = sorted((z for z in tout if z["cote"] == "resistance"), key=lambda z: z["bas"])[:ZONES_PAR_COTE]
    sup = sorted((z for z in tout if z["cote"] == "support"), key=lambda z: -z["haut"])[:ZONES_PAR_COTE]
    for i, z in enumerate(res, 1):
        z["nom"] = f"R{i}"
    for i, z in enumerate(sup, 1):
        z["nom"] = f"S{i}"
    for z in res + sup:
        z["etiquette"] = f"{z['nom']} · {z['contacts']} contact{'s' if z['contacts'] > 1 else ''}"
    return {"atr": round(atr, 6), "cours": cours, "resistances": res, "supports": sup, "pivots": len(pv)}


# ------------------------------------------------------------------ lignes de tendance
def _ligne(bougies: list[list], p1: dict, p2: dict, sens: str, atr: float, autres: list[dict], paire: str) -> dict:
    pente_barre = (p2["prix"] - p1["prix"]) / (p2["i"] - p1["i"])
    val = lambda i: p1["prix"] + pente_barre * (i - p1["i"])          # noqa: E731
    dernier = len(bougies) - 1
    cassure = None
    for i in range(p2["i"] + 1, len(bougies)):
        c = bougies[i][4]
        if (sens == "support" and c < val(i)) or (sens == "resistance" and c > val(i)):
            cassure = i
            break
    fin = cassure if cassure is not None else dernier
    tol = TOLERANCE_CONTACT_ATR * atr
    # Contacts supplémentaires : pivots alignés avant le second ancrage (prolongement compris), puis retours sur la ligne après le second point (mèche
    # à moins de 0,2 × ATR ; des bougies consécutives au contact ne comptent qu'une fois), jusqu'à la cassure.
    contacts = 2 + sum(1 for p in autres if p["i"] not in (p1["i"], p2["i"]) and p["i"] < p2["i"] and abs(p["prix"] - val(p["i"])) <= tol)
    au_contact = False
    for i in range(p2["i"] + 2, fin + 1 if cassure is None else fin):
        meche = bougies[i][3] if sens == "support" else bougies[i][2]
        touche = abs(meche - val(i)) <= tol
        if touche and not au_contact:
            contacts += 1
        au_contact = touche
    jours = max((_dt(p2["date"]) - _dt(p1["date"])).total_seconds() / 86400, 1 / 48)
    sortie = {"sens": sens, "p1": {"date": p1["date"], "prix": round(p1["prix"], 6)}, "p2": {"date": p2["date"], "prix": round(p2["prix"], 6)},
              "fin": {"date": str(bougies[dernier][0])[:16], "prix": round(val(dernier), 6)},
              "contacts": contacts, "pente_pips_jour": round((p2["prix"] - p1["prix"]) / taille_pip(paire) / jours, 1),
              "valeur_actuelle": round(val(dernier), 6)}
    if cassure is None:
        sortie.update({"etat": "valide", "texte": f"valide · {contacts} contacts"})
    else:
        prix = bougies[cassure][4]
        sortie.update({"etat": "cassée", "cassee_le": str(bougies[cassure][0])[:16], "prix_cassure": prix,
                       "bougies_depuis_cassure": dernier - cassure,
                       "texte": f"cassée le {jjmm(bougies[cassure][0])} à {prix:.{2 if paire.endswith('JPY') else 4}f}".replace(".", ",")})
    sortie["visible"] = cassure is None or dernier - cassure < CASSURE_VISIBLE
    return sortie


def lignes_tendance(bougies: list[list], n: int, paire: str = "", atr: float | None = None) -> dict:
    """Support haussier par les deux derniers creux montants ; résistance baissière par les deux derniers sommets descendants."""
    atr = atr if atr is not None else atr_wilder(bougies)
    if not bougies or not atr:
        return {"raison": "bougies insuffisantes pour l'ATR 14", "support": None, "resistance": None}
    pv = pivots(bougies, n)
    bas = [p for p in pv if p["type"] == "bas"]
    hauts = [p for p in pv if p["type"] == "haut"]
    sortie = {"support": None, "resistance": None}
    if len(bas) >= 2 and bas[-1]["prix"] > bas[-2]["prix"]:
        sortie["support"] = _ligne(bougies, bas[-2], bas[-1], "support", atr, bas, paire)
    else:
        sortie["raison_support"] = "les deux derniers creux ne montent pas : pas de ligne de support haussière"
    if len(hauts) >= 2 and hauts[-1]["prix"] < hauts[-2]["prix"]:
        sortie["resistance"] = _ligne(bougies, hauts[-2], hauts[-1], "resistance", atr, hauts, paire)
    else:
        sortie["raison_resistance"] = "les deux derniers sommets ne descendent pas : pas de ligne de résistance baissière"
    return sortie


# ------------------------------------------------------------------ divergences
def divergences(bougies: list[list], rsi: list[float | None], n: int) -> list[dict]:
    """Compare les deux derniers pivots confirmés (bas puis hauts) du prix et le RSI aux mêmes bougies."""
    pv = pivots(bougies, n)
    sortie = []
    dernier = len(bougies) - 1
    for type_, sens in (("bas", "haussière"), ("haut", "baissière")):
        ps = [p for p in pv if p["type"] == type_ and rsi[p["i"]] is not None]
        if len(ps) < 2:
            continue
        a, b = ps[-2], ps[-1]
        if b["i"] - a["i"] > DIVERGENCE_FENETRE or dernier - b["i"] > DIVERGENCE_RECENTE:
            continue
        ra, rb = rsi[a["i"]], rsi[b["i"]]
        if type_ == "bas" and b["prix"] < a["prix"] and rb > ra:
            texte = "divergence haussière : prix plus bas, RSI plus haut"
        elif type_ == "haut" and b["prix"] > a["prix"] and rb < ra:
            texte = "divergence baissière : prix plus haut, RSI plus bas"
        else:
            continue
        sortie.append({"sens": sens, "texte": f"{texte} ({jjmm(a['date'])} {a['date'][11:16]} → {jjmm(b['date'])} {b['date'][11:16]})".replace("  ", " ").replace(" 00:00", ""),
                       "p1": {"date": a["date"], "prix": a["prix"], "rsi": ra}, "p2": {"date": b["date"], "prix": b["prix"], "rsi": rb}})
    return sortie


# ------------------------------------------------------------------ assemblage d'une unité de temps
def analyser_unite(bougies: list[list], unite: str, paire: str) -> dict:
    """RSI (série alignée sur les bougies), zones, lignes de tendance et divergences d'une unité de temps."""
    n = FRACTALE.get(unite, 3)
    rsi = rsi_wilder([b[4] for b in bougies])
    atr = atr_wilder(bougies)
    sortie = {"rsi14": [[str(b[0])[:16], v] for b, v in zip(bougies, rsi)],
              "rsi_actuel": next((v for v in reversed(rsi) if v is not None), None),
              "divergences": divergences(bougies, rsi, n), "fractale": n,
              "atr14": round(atr, 6) if atr else None}
    if unite in ("4h", "1j"):
        sortie["zones"] = zones(bougies, n, paire, atr)
        sortie["lignes"] = lignes_tendance(bougies, n, paire, atr)
    return sortie
