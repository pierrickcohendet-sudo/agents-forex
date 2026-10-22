"""Repères annotés des graphiques (palier 10) : calcul Python, jamais d'invention.

Pour chaque graphique de cours ou de série, et pour chaque période proposée par le site (30 j, 90 j, 1 an, tout),
2 à 4 repères sur la courbe principale :
- plus haut et plus bas de la période (omis s'ils tombent sur le dernier point : celui-ci les signale) ;
- dernière valeur avec sa date ;
- l'évènement majeur le plus récent de la période (décision de banque centrale, CPI, NFP) quand il existe
  dans le registre macro (publications datées, ForexFactory), pour la devise de la courbe seulement.
Chaque repère porte son texte court, sa date, sa source et un détail lu au survol ou au toucher.
Pas de repère quand la donnée manque (moins de 2 points) ; un évènement sans date publiée est ignoré.
"""
from __future__ import annotations

from datetime import date, timedelta

PERIODES = {"30": 30, "90": 90, "366": 366, "tout": None}
DEVISES = ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY")
BANQUES = {"USD": "Fed", "EUR": "BCE", "GBP": "BoE", "JPY": "BoJ", "CHF": "BNS", "CAD": "BoC", "AUD": "RBA",
           "NZD": "RBNZ", "CNY": "PBoC"}
# indicateur du registre -> libellé de l'évènement ; « emploi » n'est le NFP que pour l'USD
EVENEMENTS = {"taux_directeur": "décision", "cpi": "CPI", "emploi": "NFP"}
MAX_REPERES = 4
UNITES_AFFICHEES = ("%", "pb", "M barils", "$", "écarts", "pts")   # les autres (0-100, RSI, base 100) sont implicites


def _fr(v: float, unite: str | None) -> str:
    absolu = abs(v)
    if unite in ("%", "pb", "écarts", "pts", "0-100", "RSI"):
        dec = {"pb": 0, "0-100": 0, "RSI": 1}.get(unite, 2)
    else:   # cours de change (1,0823), indices (121,4), stocks (415 600)
        dec = 6 if 0 < absolu < 0.1 else 4 if absolu < 2 else 2 if absolu < 1000 else 0
    texte = f"{v:,.{dec}f}".replace(",", " ").replace(".", ",").replace("-", "−")
    return texte + (f" {unite}" if unite in UNITES_AFFICHEES else "")


def _jj_mm(d: str) -> str:
    return f"{d[8:10]}/{d[5:7]}"


def _jj_mm_aaaa(d: str) -> str:
    return f"{d[8:10]}/{d[5:7]}/{d[:4]}"


def evenements_majeurs(registre: dict | None, devise: str) -> list[dict]:
    """Publications datées (registre macro) : banque centrale, CPI, NFP (USD). [{date, texte, detail, source}] triées."""
    if devise not in DEVISES:
        return []
    cases = (registre or {}).get("cases") or {}
    sortie, vus = [], set()
    for indicateur, nature in EVENEMENTS.items():
        if indicateur == "emploi" and devise != "USD":
            continue
        case = cases.get(f"{devise}|{indicateur}") or {}
        actuel = case.get("actuel") or {}
        publications = []
        if actuel.get("date_pub") and not actuel.get("origine"):        # origine renseignée = valeur de repli, pas une publication
            publications.append((actuel["date_pub"], actuel.get("valeur"), actuel.get("source") or "ForexFactory"))
        for h in case.get("historique") or []:
            if h.get("date_pub"):
                publications.append((h["date_pub"], h.get("valeur"), h.get("source") or "ForexFactory"))
        for jour, valeur, source in publications:
            if (indicateur, jour) in vus or not valeur:
                continue
            vus.add((indicateur, jour))
            valeur = str(valeur).replace(".", ",")
            if indicateur == "taux_directeur":
                court = f"{BANQUES[devise]} {valeur}"
                detail = f"Décision {BANQUES[devise]} : taux directeur {valeur}, publiée le {_jj_mm_aaaa(jour)}"
            else:
                nom = "NFP (emplois non agricoles)" if indicateur == "emploi" else f"CPI {devise}"
                court = f"{'NFP' if indicateur == 'emploi' else 'CPI'} {valeur}"
                detail = f"{nom} : {valeur}, publié le {_jj_mm_aaaa(jour)}"
            sortie.append({"date": jour, "texte": court, "detail": detail, "source": f"{source} (registre macro)"})
    return sorted(sortie, key=lambda e: e["date"])


def reperes(points: list, unite: str | None, source: str | None, evenements: list[dict] | None = None,
            nom: str | None = None) -> dict:
    """{période: [repère]} ; repère = {type, date, valeur, texte, detail, source}. Période vide si < 2 points."""
    pts = [(str(p[0])[:10], float(p[1])) for p in points or [] if p and p[1] is not None]
    sortie: dict[str, list] = {}
    if len(pts) < 2:
        return {k: [] for k in PERIODES}
    fin = date.fromisoformat(pts[-1][0])
    qui = f"{nom} : " if nom else ""
    for cle, jours in PERIODES.items():
        borne = (fin - timedelta(days=jours)).isoformat() if jours else ""
        vue = [p for p in pts if p[0] >= borne]
        if len(vue) < 2:
            sortie[cle] = []
            continue
        libelle_periode = f"{jours} j" if jours and jours < 366 else "1 an" if jours else "la série"
        dernier = vue[-1]
        haut = max(vue, key=lambda p: p[1])
        bas = min(vue, key=lambda p: p[1])
        liste = []
        for type_, p, mot in (("haut", haut, "Plus haut"), ("bas", bas, "Plus bas")):
            if p[0] == dernier[0]:
                continue
            liste.append({"type": type_, "date": p[0], "valeur": round(p[1], 6),
                          "texte": f"{mot} {_fr(p[1], unite)}",
                          "detail": f"{qui}{mot.lower()} sur {libelle_periode} : {_fr(p[1], unite)} le {_jj_mm_aaaa(p[0])}",
                          "source": source})
        precision = " (plus haut de la période)" if haut[0] == dernier[0] else " (plus bas de la période)" if bas[0] == dernier[0] else ""
        liste.append({"type": "dernier", "date": dernier[0], "valeur": round(dernier[1], 6),
                      "texte": f"{_fr(dernier[1], unite)} au {_jj_mm(dernier[0])}",
                      "detail": f"{qui}dernière valeur {_fr(dernier[1], unite)} le {_jj_mm_aaaa(dernier[0])}{precision}",
                      "source": source})
        dans = [e for e in evenements or [] if vue[0][0] <= e["date"] <= dernier[0]]
        if dans and len(liste) < MAX_REPERES:
            e = dans[-1]
            point = max((p for p in vue if p[0] <= e["date"]), key=lambda p: p[0])   # cours du jour de publication
            liste.append({"type": "evenement", "date": point[0], "valeur": round(point[1], 6), "texte": e["texte"],
                          "detail": f"{e['detail']} ; cours ce jour-là : {_fr(point[1], unite)}", "source": e["source"],
                          "date_evenement": e["date"]})
        sortie[cle] = sorted(liste, key=lambda r: r["date"])[:MAX_REPERES]
    return sortie


def annoter_graphique(g: dict, registre: dict | None = None) -> dict:
    """Ajoute g['annotations'] (courbe principale = la première) à un graphique « serie » des dossiers."""
    if g.get("type") != "serie" or not g.get("courbes"):
        return g
    c = g["courbes"][0]
    g["annotations"] = {"courbe": c.get("nom"),
                        "periodes": reperes(c.get("points"), g.get("unite"), g.get("source"),
                                            evenements_majeurs(registre, c.get("nom")), c.get("nom"))}
    return g
