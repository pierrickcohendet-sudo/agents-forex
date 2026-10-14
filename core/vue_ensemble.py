"""Vue d'ensemble des 8 engrenages (refonte V2, palier 1) : bandeau du thème, 8 cartes, chaînes.

Tout est calculé ici en Python, sans LLM :
- chiffre vedette, ligne de contexte et mini-courbe 30 jours de chaque engrenage (séries datées
  des historiques, de la technique ou des dossiers déjà calculés) ;
- direction et conviction reprises du rapport (règles Python de agent_engrenages ; le modèle ne
  propose une direction que pour 4, 6 et 8, et c'est alors indiqué) ;
- cohérence X/7 : nombre d'engrenages 2 à 8 dont la direction est alignée sur celle du thème.
Le texte du bandeau reprend le diagnostic déjà rédigé de l'engrenage 1 (aucun appel en plus).
Une valeur absente vaut None avec sa raison, jamais une valeur inventée.
"""
from __future__ import annotations

from datetime import date, timedelta

TITRES = {1: "Thème macro", 2: "Politique monétaire", 3: "Données économiques", 4: "Politique fiscale",
          5: "Interconnexions de marchés", 6: "Géopolitique", 7: "Price action et flux", 8: "Offre et demande"}
DOLLAR = {"haussier": "Dollar ↑", "baissier": "Dollar ↓", "neutre": "Dollar ="}
RISQUE = {"risk_on": "Risk on", "risk_off": "Risk off", "neutre": "Risque neutre"}
POINTS_CONVICTION = {"faible": 1, "moyen": 2, "eleve": 3}
JOURS_COURBE = 30
SEUIL_THEME_FORT = 3   # moins de 3 engrenages alignés : « Signaux mixtes », jamais un thème fort
TITRE_SIGNAUX_MIXTES = "Signaux mixtes"
# Vocabulaire d'un thème « fort » : retiré du texte du modèle quand la cohérence est sous le seuil.
import re as _re
_THEME_FORT = _re.compile(
    r"\b(?:th[èe]me (?:fort|dominant|clair|net|bien [ée]tabli|install[ée])|domin\w*|marqu[ée]e?s?|"
    r"nette(?:ment)?|net|clairement|franc(?:he)?(?:ment)?|solide(?:ment)?|consolid\w*|sans ambigu[ïi]t[ée]|"
    r"s'impose\w*|unanim\w*|tous les engrenages)\b", _re.IGNORECASE)
REGLE_COHERENCE = ("engrenage 2 à 8 aligné si sa direction dollar est celle du thème ; à défaut de direction "
                   "dollar, si sa direction risque est celle du thème. Évaluable = engrenage qui a une direction "
                   "comparable à celle du thème. Moins de 3 alignés : « Signaux mixtes ».")


def _fr(v: float | None, d: int = 2) -> str:
    if v is None:
        return "n/d"
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",").replace("-", "−")


def _signe(v: float | None, d: int = 2) -> str:
    return "n/d" if v is None else ("+" if v > 0 else "") + _fr(v, d)


def _points(historiques: dict, cle: str) -> list[list]:
    return [[str(p[0])[:10], float(p[1])] for p in (((historiques or {}).get("series") or {}).get(cle) or {}).get("points") or []
            if p and p[1] is not None]


def _derniers_jours(points: list[list], jours: int = JOURS_COURBE) -> list[list]:
    if not points:
        return []
    limite = (date.fromisoformat(points[-1][0]) - timedelta(days=jours)).isoformat()
    return [p for p in points if p[0] >= limite]


def _variation(points: list[list], jours: int) -> float | None:
    """Variation entre la dernière valeur et la valeur d'il y a `jours` jours calendaires (ou juste avant)."""
    if len(points) < 2:
        return None
    cible = (date.fromisoformat(points[-1][0]) - timedelta(days=jours)).isoformat()
    avant = [p for p in points if p[0] <= cible]
    return None if not avant else points[-1][1] - avant[-1][1]


def _pct(points: list[list], jours: int) -> float | None:
    d = _variation(points, jours)
    if d is None:
        return None
    base = points[-1][1] - d
    return None if not base else d / base * 100


def _chiffre(libelle: str, valeur: float | None, unite: str, date_: str | None, source: str | None,
             texte: str | None = None, raison: str | None = None) -> dict:
    return {"libelle": libelle, "valeur": valeur, "texte": texte if texte is not None else
            (None if valeur is None else _fr(valeur) + (f" {unite}" if unite else "")),
            "unite": unite, "date": date_, "source": source, "raison": None if valeur is not None or texte else raison}


def _courbe(points: list[list], source: str | None, periode: str = "30 jours", raison: str | None = None) -> dict:
    pts = [[d, round(v, 4)] for d, v in points]
    return {"points": pts, "periode": periode, "source": source,
            "raison": None if len(pts) >= 2 else (raison or "historique insuffisant pour une mini-courbe")}


def _courbe_graphique(e: dict, titre_contient: str, nom: str) -> list[list]:
    for g in (e or {}).get("graphiques") or []:
        if titre_contient in str(g.get("titre", "")):
            for c in g.get("courbes") or []:
                if c.get("nom") == nom:
                    return [[str(p[0])[:10], float(p[1])] for p in c.get("points") or [] if p[1] is not None]
    return []


def _cellule(e: dict, devise: str, colonne: str) -> dict:
    for ligne in (e or {}).get("lignes") or []:
        if ligne.get("devise") == devise:
            return (ligne.get("cellules") or {}).get(colonne) or {}
    return {}


# ------------------------------------------------------------------ cartes
def _carte_1(rapport: dict | None, dossiers: dict) -> tuple[dict, str, dict]:
    scores = sorted([(d.get("score_confluence"), d["devise"]) for d in (rapport or {}).get("devises") or []
                     if d.get("score_confluence") is not None], reverse=True)
    usd = next((s for s, d in scores if d == "USD"), None)
    jour = ((rapport or {}).get("meta") or {}).get("date_rapport")
    ligne = (", ".join(f"{d} {s:.0f}" for s, d in (scores[:2] + scores[-1:])) +
             f" : écart de {scores[0][0] - scores[-1][0]:.0f} points entre extrêmes.") if len(scores) >= 3 else \
        "Scores de confluence indisponibles."
    pts = _courbe_graphique(dossiers.get("1"), "Écart de score", "Écart risque − refuge")
    return (_chiffre("Score USD", usd, "", jour, "calcul Python (scores de confluence)",
                     texte=None if usd is None else f"{usd:.0f}", raison="rapport du jour indisponible"),
            ligne, _courbe(pts, "rapports quotidiens (écart de score risque − refuge)", "4 semaines"))


def _carte_2(historiques: dict) -> tuple[dict, str, dict]:
    us2, dff = _points(historiques, "USD_2a"), _points(historiques, "USD_taux_effectif")
    v2 = us2[-1] if us2 else None
    var = _variation(us2, 7)
    ligne = ((f"Fed à {_fr(dff[-1][1])} % effectif, " if dff else "") +
             (f"2 ans {_signe(var * 100 if var is not None else None, 0)} pb sur 7 jours." if var is not None
              else "variation du 2 ans indisponible."))
    return (_chiffre("Rendement 2 ans US", v2[1] if v2 else None, "%", v2[0] if v2 else None, "FRED (DGS2)",
                     raison="série DGS2 indisponible"),
            ligne[0].upper() + ligne[1:], _courbe(_derniers_jours(us2), "FRED (DGS2)"))


def _carte_3(dossiers: dict) -> tuple[dict, str, dict]:
    e = dossiers.get("3") or {}
    c = _cellule(e, "USD", "indice_surprise")
    autres = sorted([(abs((_cellule(e, d.get("devise"), "indice_surprise") or {}).get("valeur") or 0),
                      d.get("devise"), (_cellule(e, d.get("devise"), "indice_surprise") or {}).get("valeur"))
                     for d in e.get("lignes") or [] if d.get("devise") != "USD"], reverse=True)
    autres = [(dev, v) for _, dev, v in autres if v is not None][:2]
    ligne = ("Plus fortes surprises ailleurs : " + ", ".join(f"{d} {_signe(v)}" for d, v in autres) + "."
             if autres else "Surprises des autres devises indisponibles.")
    pts = _courbe_graphique(e, "Indice de surprise", "USD")
    return (_chiffre("Surprise USD (30 j)", c.get("valeur"), "", c.get("date"), c.get("source"),
                     texte=None if c.get("valeur") is None else _signe(c["valeur"]),
                     raison=c.get("raison") or "indice de surprise indisponible"),
            ligne, _courbe(_derniers_jours(pts), c.get("source")))


def _carte_4(historiques: dict, dossiers: dict) -> tuple[dict, str, dict]:
    pt, us10 = _points(historiques, "USD_prime_terme"), _points(historiques, "USD_10a")
    dette = _cellule(dossiers.get("4"), "USD", "dette_pib")
    morceaux = []
    if us10:
        morceaux.append(f"10 ans US {_fr(us10[-1][1])} %")
    if dette.get("valeur") is not None:
        morceaux.append(f"dette fédérale / PIB {_fr(dette['valeur'], 1)} % ({dette.get('date')})")
    return (_chiffre("Prime de terme 10 ans US", pt[-1][1] if pt else None, "%", pt[-1][0] if pt else None,
                     "FRED (THREEFYTP10, Kim-Wright)", raison="série de prime de terme indisponible"),
            (", ".join(morceaux) + ".") if morceaux else "Rendements et dette indisponibles.",
            _courbe(_derniers_jours(pt), "FRED (THREEFYTP10)"))


def _carte_5(historiques: dict) -> tuple[dict, str, dict]:
    dl, vix = _points(historiques, "dollar_large"), _points(historiques, "vix")
    var = _pct(dl, 7)
    ligne = (f"Indice dollar {_signe(var)} % sur 7 jours" if var is not None else "Variation du dollar indisponible") + \
            (f", VIX à {_fr(vix[-1][1], 1)}." if vix else ".")
    return (_chiffre("Indice dollar large (Fed)", dl[-1][1] if dl else None, "", dl[-1][0] if dl else None,
                     "FRED (DTWEXBGS)", texte=None if not dl else _fr(dl[-1][1], 1),
                     raison="indice dollar large indisponible"),
            ligne, _courbe(_derniers_jours(dl), "FRED (DTWEXBGS)"))


def _carte_6(dossiers: dict) -> tuple[dict, str, dict]:
    e = dossiers.get("6") or {}
    ev = e.get("evenements") or []
    comptes = []
    for g in e.get("graphiques") or []:
        if g.get("type") == "barres":
            comptes = [(b["nom"], b["valeur"]) for b in g.get("barres") or [] if b.get("valeur")]
    ligne = ("Canaux : " + ", ".join(f"{n.lower()} {v}" for n, v in sorted(comptes, key=lambda x: -x[1])) + "."
             if comptes else "Aucun titre classé par canal aujourd'hui.")
    jour = max((x.get("date") or "" for x in ev), default=None) or None
    return (_chiffre("Événements retenus", float(len(ev)), "", jour, "fil d'actualité classé par canal (calcul Python)",
                     texte=str(len(ev))),
            ligne, _courbe([], None, raison="pas de série chiffrée gratuite pour la géopolitique"))


def _carte_7(technique: dict, dossiers: dict) -> tuple[dict, str, dict]:
    t = ((technique or {}).get("devises") or {}).get("USD") or {}
    g = ((technique or {}).get("graphiques") or {}).get("USD") or {}
    pts = [[str(d)[:10], float(v)] for d, v in zip(g.get("dates") or [], g.get("clotures") or []) if v is not None]
    extremes = []
    for ligne in (dossiers.get("7") or {}).get("lignes") or []:
        cot = (ligne.get("cellules") or {}).get("cot") or {}
        if cot.get("extreme"):
            extremes.append(f"{ligne.get('devise')} ({'acheteur' if cot['extreme'] == 'long' else 'vendeur'})")
    morceaux = []
    if t.get("rsi") is not None:
        morceaux.append(f"RSI USD {_fr(t['rsi'], 1)}")
    if t.get("variation_5j_pct") is not None:
        morceaux.append(f"{_signe(t['variation_5j_pct'])} % sur 5 jours")
    texte = ", ".join(morceaux) + "." if morceaux else "Technique USD indisponible."
    if extremes:
        texte = texte[:-1] + f" ; COT extrême : {', '.join(extremes[:3])}" +             (f" et {len(extremes) - 3} autre(s)" if len(extremes) > 3 else "") + "."
    return (_chiffre("Indice USD synthétique", t.get("dernier"), "", pts[-1][0] if pts else None,
                     "calcul local (Twelve Data)", texte=None if t.get("dernier") is None else _fr(t["dernier"], 2),
                     raison="technique USD indisponible"),
            texte, _courbe(_derniers_jours(pts), "calcul local (Twelve Data)"))


def _carte_8(historiques: dict) -> tuple[dict, str, dict]:
    st = [[d, v / 1000] for d, v in _points(historiques, "eia_stocks")]   # milliers -> millions de barils
    brent = _points(historiques, "brent")
    var = (st[-1][1] - st[-2][1]) if len(st) >= 2 else None
    morceaux = []
    if var is not None:
        morceaux.append(f"stocks {_signe(var, 1)} M de barils sur la semaine")
    if brent:
        morceaux.append(f"Brent à {_fr(brent[-1][1])} $")
    ligne = ", ".join(morceaux) + "." if morceaux else "Pétrole indisponible."
    return (_chiffre("Stocks de brut US", st[-1][1] if st else None, "M barils", st[-1][0] if st else None,
                     "EIA (WCESTUS1, hors réserve stratégique)", texte=None if not st else f"{_fr(st[-1][1], 1)} M",
                     raison="stocks EIA indisponibles"),
            ligne[0].upper() + ligne[1:], _courbe(_derniers_jours(st, 182), "EIA (WCESTUS1)", "26 semaines"))


# ------------------------------------------------------------- directions
def _engrenages_rapport(rapport: dict | None) -> tuple[dict, dict]:
    eng = (((rapport or {}).get("synthese_globale") or {}).get("engrenages")) or {}
    return eng, {int(e["numero"]): e for e in eng.get("engrenages") or [] if e.get("numero")}


def _direction(e: dict | None) -> dict:
    d = (e or {}).get("direction") or {}
    dollar, risque = d.get("dollar"), d.get("risque")
    libelle = " · ".join(x for x in (DOLLAR.get(dollar), RISQUE.get(risque)) if x) or "non déterminée"
    if risque == "risk_off" or (dollar == "baissier" and risque != "risk_on"):
        classe = "dn"
    elif risque == "risk_on" or dollar == "haussier":
        classe = "up"
    else:
        classe = "nd"
    origine = d.get("origine") or {}
    par_modele = "modèle" in (origine.get("dollar") or "") or "modèle" in (origine.get("risque") or "")
    conv = ((e or {}).get("conviction") or {}).get("niveau")
    return {"dollar": dollar, "risque": risque, "libelle": libelle, "classe": classe,
            "origine": "modèle (engrenage sans règle Python)" if par_modele else ("calcul Python" if dollar or risque else None),
            "conviction": POINTS_CONVICTION.get(conv, 0), "conviction_niveau": conv}


def coherence(par_num: dict) -> dict:
    theme = _direction(par_num.get(1))
    alignes, details = [], []
    for n in range(2, 9):
        d = _direction(par_num.get(n))
        if theme["dollar"] and d["dollar"]:
            ok = d["dollar"] == theme["dollar"] and theme["dollar"] != "neutre"
            critere = "dollar"
        elif theme["risque"] and d["risque"]:
            ok = d["risque"] == theme["risque"] and theme["risque"] != "neutre"
            critere = "risque"
        else:
            ok, critere = False, None
        details.append({"numero": n, "aligne": ok, "critere": critere, "direction": d["libelle"]})
        if ok:
            alignes.append(n)
    evaluables = [x["numero"] for x in details if x["critere"]]
    return {"alignes": len(alignes), "evaluables": len(evaluables), "sur": 7, "engrenages_alignes": alignes,
            "engrenages_evaluables": evaluables, "theme_fort": len(alignes) >= SEUIL_THEME_FORT,
            "libelle": f"{len(alignes)} sur {len(evaluables)} évaluable{'s' if len(evaluables) > 1 else ''}",
            "detail": details, "regle": REGLE_COHERENCE}


def moderer_theme_fort(texte: str | None) -> tuple[str | None, int]:
    """Retire les phrases qui annoncent un thème fort (cohérence sous le seuil). -> (texte, nb retirées)."""
    if not texte:
        return texte, 0
    phrases = _re.split(r"(?<=[.!?])\s+", str(texte).strip())
    gardees = [x for x in phrases if not _THEME_FORT.search(x)]
    return (" ".join(gardees) or None), len(phrases) - len(gardees)


def phrase_signaux_mixtes(coh: dict, theme_dir: dict) -> str:
    sens = theme_dir.get("libelle") or "non déterminé"
    if not coh["evaluables"]:
        return f"Aucun autre engrenage n'a de direction comparable à celle du thème calculé ({sens}) : pas de thème confirmé."
    return (f"Les engrenages ne s'accordent pas : {coh['libelle']} vont dans le sens du thème calculé ({sens}), "
            f"sous le seuil de {SEUIL_THEME_FORT} pour parler d'un thème établi.")


def _titre_theme(theme: dict, rapport: dict | None) -> str:
    scores = sorted([(d.get("score_confluence"), d["devise"]) for d in (rapport or {}).get("devises") or []
                     if d.get("score_confluence") is not None], reverse=True)
    premier = scores[0][1] if scores else None
    regime = {"risk_off": "Aversion au risque", "risk_on": "Appétit pour le risque"}.get(theme["risque"],
                                                                                         "Pas de régime de risque net")
    dollar = {"haussier": "dollar en tête" if premier == "USD" else "dollar soutenu",
              "baissier": "dollar sous pression", "neutre": "dollar neutre"}.get(theme["dollar"])
    return f"{regime}, {dollar}" if dollar else regime


def _phrases(texte: str | None, n: int = 3) -> str | None:
    if not texte:
        return None
    morceaux = [m.strip() for m in str(texte).replace("\n", " ").split(". ") if m.strip()]
    sortie = ". ".join(morceaux[:n]).replace("risk_off", "risk off").replace("risk_on", "risk on")
    return sortie if sortie.endswith((".", "!", "?")) else sortie + "."


# --------------------------------------------------------------- assemblage
def calculer(dossiers_engrenages: dict, historiques: dict | None, technique: dict | None, rapport: dict | None) -> dict:
    dos = dossiers_engrenages or {}
    eng, par_num = _engrenages_rapport(rapport)
    fabriques = {1: lambda: _carte_1(rapport, dos), 2: lambda: _carte_2(historiques),
                 3: lambda: _carte_3(dos), 4: lambda: _carte_4(historiques, dos), 5: lambda: _carte_5(historiques),
                 6: lambda: _carte_6(dos), 7: lambda: _carte_7(technique, dos), 8: lambda: _carte_8(historiques)}
    cartes = []
    for n in range(1, 9):
        try:
            chiffre, ligne, courbe = fabriques[n]()
        except Exception as exc:  # noqa: BLE001 — une carte en échec n'affecte qu'elle
            chiffre, ligne, courbe = _chiffre("Chiffre clé", None, "", None, None, raison=f"calcul en échec : {exc}"[:120]), \
                "Données indisponibles.", _courbe([], None, raison="calcul en échec")
        direction = _direction(par_num.get(n))
        if not par_num:
            direction["raison"] = "synthèse des engrenages pas encore disponible pour ce rapport"
        cartes.append({"numero": n, "titre": TITRES[n], "chiffre": chiffre, "ligne": ligne, "courbe": courbe,
                       "direction": direction})
    theme_dir = _direction(par_num.get(1))
    diag1 = (par_num.get(1) or {}).get("diagnostic")
    texte = None if (par_num.get(1) or {}).get("donnees_insuffisantes") else _phrases(diag1)
    coh = coherence(par_num) if par_num else None
    titre, texte_python, retirees = (_titre_theme(theme_dir, rapport) if par_num else None), None, 0
    if coh and not coh["theme_fort"]:          # règle Python : le modèle ne peut pas annoncer un thème fort
        titre = TITRE_SIGNAUX_MIXTES
        texte, retirees = moderer_theme_fort(texte)
        texte_python = phrase_signaux_mixtes(coh, theme_dir)
    theme = {"titre": titre, "titre_impose": bool(coh and not coh["theme_fort"]), "texte_python": texte_python,
             "phrases_retirees": retirees,
             "texte": texte, "texte_redige_par": (eng.get("redige_par") or {}).get("libelle") if texte else None,
             "direction": theme_dir, "coherence": coh,
             "raison": None if par_num else "synthèse des engrenages pas encore disponible pour ce rapport",
             "date_rapport": ((rapport or {}).get("meta") or {}).get("date_rapport")}
    return {"theme": theme, "cartes": cartes,
            "chaines": [{"titre": c.get("titre"), "maillons": [{"engrenage": m.get("engrenage"), "texte": m.get("texte"),
                                                                 "non_sourcee": bool(m.get("non_sourcee"))}
                                                                for m in c.get("maillons") or []]}
                        for c in eng.get("chaines") or []],
            "conflits": [{"engrenages": c.get("engrenages"), "texte": c.get("texte"), "origine": c.get("origine")}
                         for c in eng.get("conflits") or []],
            "statut_texte": eng.get("statut"), "redige_par": (eng.get("redige_par") or {}).get("libelle")}
