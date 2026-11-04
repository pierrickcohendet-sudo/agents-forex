"""Synthèse longue du lundi (lot V6, partie D) : plan du rapport modèle en 12 sections, 100 % Python.

Chaque section : {titre, phrase_python, texte (reformulation validée du modèle, sinon None), blocs}. Les blocs sont
génériques (paragraphe, liste, tableau, cartes, note) : le site les affiche sans calcul. Chaque chiffre a sa source et
sa date, sinon « n/d » et la raison ; aucune probabilité, aucun ordre d'achat ou de vente. Une section dont le calcul
échoue garde son titre et la raison, sans faire tomber les autres.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date, timedelta

log = logging.getLogger(__name__)

SECTIONS_LONGUES = ["long_intro", "long_executive", "long_marches", "long_regime", "long_banques", "long_calendrier",
                    "long_geopolitique", "long_devises", "long_paires", "long_scenarios", "long_technique", "long_plan"]
TITRES_LONGS = {
    "long_intro": "Introduction : les trois grands facteurs de la semaine",
    "long_executive": "Synthèse exécutive",
    "long_marches": "Analyse des marchés",
    "long_regime": "Régime macro mondial",
    "long_banques": "Banques centrales de la semaine",
    "long_calendrier": "Calendrier complet de la semaine",
    "long_geopolitique": "Géopolitique, politique et évènements non économiques",
    "long_devises": "Analyse relative des devises",
    "long_paires": "Paires prioritaires",
    "long_scenarios": "Scénarios de la semaine",
    "long_technique": "Technique et exécution",
    "long_plan": "Plan opérationnel et conclusion",
}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
OPS = {">": lambda a, b: a > b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}
DXY_POIDS = {"EUR": -0.576, "JPY": 0.136, "GBP": -0.119, "CAD": 0.091, "SEK": 0.042, "CHF": 0.036}   # formule publique ICE
DXY_CONSTANTE = 50.14348112
SIM = {("USD", "pib"): "pib_us", ("USD", "cpi"): "cpi_us", ("USD", "cpi_core"): "cpi_core_us"}


def fr(v, d: int = 2, signe: bool = False) -> str:
    if v is None:
        return "n/d"
    t = f"{v:+.{d}f}" if signe else f"{v:.{d}f}"
    return t.replace(".", ",").replace("-", "−")


def jj(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso else "n/d"


def P(texte):
    return {"type": "paragraphe", "texte": texte}


def L(items, titre=None):
    return {"type": "liste", "titre": titre, "items": [i for i in items if i]}


def T(entetes, lignes, titre=None):
    return {"type": "tableau", "titre": titre, "entetes": entetes, "lignes": lignes}


def N(texte):
    return {"type": "note", "texte": texte}


def section(cle, phrase, blocs):
    return {"titre": TITRES_LONGS[cle], "phrase_python": phrase, "texte": None, "blocs": [b for b in blocs if b]}


def _regle(si, vars_):
    x = (vars_.get(si[0]) or {}).get("valeur")
    return None if x is None else OPS[si[1]](x, float(si[2])), x


def _chiffre_var(nom, vars_):
    v = vars_.get(nom) or {}
    x, u = v.get("valeur"), v.get("unite")
    if x is None:
        return f"n/d ({v.get('raison') or 'absent'})"
    d = 0 if u == "pb" else 2
    return f"{fr(x, d, nom.endswith('_5j'))} {u if u not in (None, 'écarts') else ''}".strip() + (f" au {jj(v.get('date'))}" if v.get("date") else "")


# ------------------------------------------------------------------ séries
def performance_mois(points: list[tuple[str, float]], aujourd: date) -> dict:
    """Performance du mois calendaire écoulé : dernière clôture du mois contre celle du mois précédent."""
    fin = aujourd.replace(day=1) - timedelta(days=1)
    debut = fin.replace(day=1) - timedelta(days=1)
    a = [p for p in points if p[0] <= debut.isoformat()]
    b = [p for p in points if p[0] <= fin.isoformat()]
    if not a or not b or b[-1][0] <= debut.isoformat():
        return {"pct": None, "mois": MOIS[fin.month - 1], "raison": "série trop courte pour le mois écoulé"}
    return {"pct": round((b[-1][1] / a[-1][1] - 1) * 100, 2), "mois": MOIS[fin.month - 1], "du": a[-1][0], "au": b[-1][0]}


def variation_mois_pb(points, aujourd: date) -> dict:
    fin = aujourd.replace(day=1) - timedelta(days=1)
    debut = fin.replace(day=1) - timedelta(days=1)
    a = [p for p in points if p[0] <= debut.isoformat()]
    b = [p for p in points if p[0] <= fin.isoformat()]
    if not a or not b:
        return {"pb": None, "mois": MOIS[fin.month - 1], "raison": "série trop courte"}
    return {"pb": round((b[-1][1] - a[-1][1]) * 100), "mois": MOIS[fin.month - 1], "du": a[-1][0], "au": b[-1][0]}


def serie_dxy(h5, technique, usdsek: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Indice dollar calculé selon la formule publique du DXY (moyenne géométrique pondérée de 6 devises), non officiel,
    sur les dates communes aux 6 cours : série unique Twelve Data (EUR, JPY, GBP, CAD, CHF) et USD/SEK (Twelve Data)."""
    if not usdsek or h5 is None:
        return []
    forces = {d: dict(h5.force(d, technique)) for d in ("EUR", "JPY", "GBP", "CAD", "CHF")}
    sek = dict(usdsek)
    dates = sorted(set(sek).intersection(*[set(v) for v in forces.values()]))

    def niveau(d):
        cours = {"EUR": forces["EUR"][d], "GBP": forces["GBP"][d], "JPY": 1 / forces["JPY"][d], "CAD": 1 / forces["CAD"][d],
                 "CHF": 1 / forces["CHF"][d], "SEK": sek[d]}   # EUR/USD, GBP/USD, puis USD/JPY, USD/CAD, USD/CHF, USD/SEK
        return DXY_CONSTANTE * math.prod(cours[k] ** p for k, p in DXY_POIDS.items())
    return [(d, round(niveau(d), 4)) for d in dates]


def indice_dxy(h5, technique, usdsek: list[tuple[str, float]]) -> dict:
    if not usdsek:
        return {"valeur": None, "raison": "USD/SEK absent de la collecte Twelve Data (historiques)"}
    pts = serie_dxy(h5, technique, usdsek)
    if not pts:
        return {"valeur": None, "raison": "aucune date commune aux 6 cours"}
    v, v5 = pts[-1][1], (pts[-6][1] if len(pts) > 5 else None)
    return {"valeur": round(v, 2), "date": pts[-1][0], "variation_5j": round((v / v5 - 1) * 100, 2) if v5 else None,
            "libelle": "indice dollar calculé selon la formule du DXY (non officiel)",
            "source": "calcul Python, formule publique ICE : Twelve Data (EUR, JPY, GBP, CAD, CHF, SEK contre USD)"}


# ------------------------------------------------------------------ sections
def _semaine(aujourd: date) -> tuple[str, str]:
    lundi = aujourd - timedelta(days=aujourd.weekday())
    return lundi.isoformat(), (lundi + timedelta(days=4)).isoformat()


def _evts_semaine(agenda, aujourd, impacts=("fort",)):
    debut, fin = _semaine(aujourd)
    return [e for j in (agenda or {}).get("jours") or [] for e in j.get("evenements") or []
            if debut <= e.get("date_paris", "") <= fin and e.get("impact") in impacts]


def score_evenement(e: dict) -> int:
    """Score d'impact de l'Agenda : impact fort 3, moyen 2 ; décision de banque centrale +3 ; USD +1."""
    return {"fort": 3, "moyen": 2, "faible": 1}.get(e.get("impact"), 0) + (3 if e.get("type") == "Réunion BC" else 0) + \
        (1 if e.get("devise") == "USD" else 0)


def regime_marche(vars_, historiques_pts, aujourd, cfg) -> dict:
    """Régime qualitatif : nombre de signaux défensifs parmi VIX, actions 1 mois, crédit 1 mois, or 1 mois."""
    from core.rapport_jour import variation
    r = cfg.get("regime") or {}
    vix = (vars_.get("vix") or {}).get("valeur")
    spy = historiques_pts("sp500_spy") or historiques_pts("sp500")
    act = variation(spy, 21, "%")
    cred = variation(historiques_pts("USD_spread_hy"), 21, "pb")
    orr = variation(historiques_pts("or_xau"), 21, "%")
    signaux = [
        ("VIX", vix, vix is not None and vix > r.get("vix_haut", 20), f"VIX {fr(vix)} (seuil {r.get('vix_haut', 20)})"),
        ("Actions 1 mois", act, act is not None and act < r.get("actions_1m_pct", 0), f"actions US {fr(act, 2, True)} % sur 21 séances"),
        ("Crédit 1 mois", cred, cred is not None and cred > r.get("credit_1m_pb", 25), f"écart high yield {fr(cred, 0, True)} pb sur 21 séances"),
        ("Refuges 1 mois", orr, orr is not None and orr > r.get("or_1m_pct", 3), f"or {fr(orr, 2, True)} % sur 21 séances"),
    ]
    mesures = [s for s in signaux if s[1] is not None]
    n = sum(1 for s in mesures if s[2])
    libelles = r.get("libelles") or ["Confiant", "Prudent", "Prudent / fragile", "Défensif", "Défensif"]
    return {"libelle": libelles[min(n, len(libelles) - 1)] if mesures else "n/d", "defensifs": n, "mesures": len(mesures),
            "signaux": [{"nom": s[0], "defensif": s[2], "texte": s[3]} for s in signaux],
            "regle": (f"{len(libelles)} niveaux selon le nombre de signaux défensifs : VIX > {r.get('vix_haut', 20)}, actions US "
                      f"négatives sur 1 mois, écart high yield en hausse de plus de {r.get('credit_1m_pb', 25)} pb, or en hausse "
                      f"de plus de {r.get('or_1m_pct', 3)} % sur 1 mois")}


def calculer(base: dict, config: dict, agenda: dict | None, profil: dict | None, historiques: dict | None, h5, technique,
             aujourd: date, racine=".") -> dict:
    """Les 12 sections de la synthèse longue. `base` : rapport du jour déjà calculé (rapport_jour.calculer)."""
    from core.rapport_jour import _points, _source
    cfg = config.get("rapport_long") or {}
    vars_ = base.get("variables") or {}
    pts = lambda cle: _points(historiques, cle)
    profils = {p["devise"]: p for p in (profil or {}).get("devises") or []}
    sortie: dict[str, dict] = {}
    contexte = {"cfg": cfg, "vars": vars_, "pts": pts, "src": lambda c: _source(historiques, c), "profils": profils,
                "agenda": agenda or {}, "base": base, "config": config, "aujourd": aujourd, "h5": h5, "technique": technique,
                "racine": racine}
    contexte["regime"] = regime_marche(vars_, pts, aujourd, cfg)
    for cle in SECTIONS_LONGUES:
        try:
            sortie[cle] = globals()[f"_{cle}"](contexte)
        except Exception as exc:  # noqa: BLE001 — une section en échec ne fait pas tomber les autres
            log.exception("Synthèse longue, section %s : %s", cle, exc)
            sortie[cle] = section(cle, f"Section indisponible : calcul en échec ({exc}).", [])
    return sortie


def _long_intro(c):
    agenda, au = c["agenda"], c["aujourd"]
    debut, fin = _semaine(au)
    bcs = [b for b in agenda.get("banques_centrales") or [] if b.get("prochaine") and debut <= b["prochaine"] <= fin]
    us = [e for e in _evts_semaine(agenda, au) if e["devise"] == "USD"]
    rdv = [g for g in agenda.get("grands_rendez_vous") or [] if debut <= g.get("date", "") <= fin and "USD" in (g.get("devises") or [])]
    reg = c["regime"]
    facteurs = [
        ("Banques centrales", (", ".join(f"{b.get('court') or b['banque']} le {jj(b['prochaine'])}" for b in bcs) or "aucune réunion cette semaine")),
        ("États-Unis", " ; ".join(t for t in ([f"{g['titre']} ({jj(g['date'])})" for g in rdv[:2]] +
                                              [f"{len(us)} publication{'s' if len(us) > 1 else ''} à fort impact"]) if t)),
        ("Régime de risque", f"{reg['libelle']} ({reg['defensifs']} {'signaux défensifs' if reg['defensifs'] > 1 else 'signal défensif'} sur {reg['mesures']})"),
    ]
    diag = (f"Semaine {'chargée' if len(bcs) >= 2 or len(us) >= 4 else 'ordinaire'} : "
            f"{len(bcs)} décision{'s' if len(bcs) > 1 else ''} de banque centrale, régime de marché « {reg['libelle'].lower()} ».")
    return section("long_intro", diag, [T(["Facteur", "Cette semaine"], [[f, t] for f, t in facteurs]), P(diag)])


def _long_executive(c):
    reg, agenda, au = c["regime"], c["agenda"], c["aujourd"]
    evts = _evts_semaine(agenda, au, ("fort", "moyen"))
    top = max(evts, key=lambda e: (score_evenement(e), -ord(e["date_paris"][-1])), default=None)
    cartes = [{"titre": f"{p['devise']} · {p['etat']['valeur']}",
               "texte": (f"Facteur dominant : {p['moteur']['dominant']['libelle']} ({fr(p['moteur']['dominant']['r60'], 2, True)} sur "
                         f"{p['moteur']['dominant']['n60']} séances)" if p["moteur"]["dominant"] else "Aucun facteur dominant"),
               "note": p["etat"]["raison"]} for p in c["profils"].values()]
    phrase = (f"Régime de marché : {reg['libelle']}. " +
              (f"Évènement le plus important : {top['devise']} {top['evenement']} ({JOURS[date.fromisoformat(top['date_paris']).weekday()]} "
               f"{jj(top['date_paris'])} {top.get('heure_paris') or ''})." if top else "Aucun évènement fort cette semaine."))
    return section("long_executive", phrase, [
        P(f"Régime de marché qualitatif : « {reg['libelle']} »."),
        L([f"{'⚠ ' if s['defensif'] else '· '}{s['texte']}" for s in reg["signaux"]], "Signaux de la règle"),
        N(f"Règle : {reg['regle']}."),
        {"type": "cartes", "titre": "Les devises et leur facteur dominant", "items": cartes},
        P(f"Évènement le plus important de la semaine (score d'impact de l'Agenda) : {top['devise']} {top['evenement']}, "
          f"{JOURS[date.fromisoformat(top['date_paris']).weekday()]} {jj(top['date_paris'])} à {top.get('heure_paris') or 'heure n/d'}."
          if top else "Aucun évènement fort ou moyen dans l'Agenda de la semaine."),
        N("Score d'impact : fort 3, moyen 2 ; décision de banque centrale +3 ; publication américaine +1."),
    ])


def _transmission(c, cle):
    sortie = []
    for r in (c["cfg"].get("transmission") or {}).get(cle) or []:
        ok, x = _regle(r["si"], c["vars"])
        if ok:
            sortie.append(f"{r['texte']} ({_chiffre_var(r['si'][0], c['vars'])})")
    return sortie or ["Aucune règle de transmission déclenchée aujourd'hui."]


def _long_marches(c):
    base, au, pts = c["base"], c["aujourd"], c["pts"]
    lignes = [[l["actif"], (fr(l["niveau"], l.get("decimales", 2)) if l.get("niveau") is not None else f"n/d ({l.get('raison')})"),
               l.get("lecture") or "n/d"] for l in (base.get("point_marche") or {}).get("lignes") or []]
    spy = pts("sp500_spy")
    if spy:
        lignes.insert(0, ["S&P 500 (ETF SPY, Twelve Data)", f"{fr(spy[-1][1])} $ au {jj(spy[-1][0])}", "cours du jour, plus frais que FRED SP500"])
    dxy = indice_dxy(c["h5"], c["technique"], pts("usdsek"))
    lignes.insert(0, ["Indice dollar calculé selon la formule du DXY (non officiel)",
                      f"{fr(dxy['valeur'])} au {jj(dxy['date'])}" if dxy.get("valeur") is not None else f"n/d ({dxy['raison']})",
                      (f"{fr(dxy['variation_5j'], 2, True)} % sur 5 séances ; indice large de la Fed en secondaire" if dxy.get("variation_5j") is not None
                       else "indice large de la Fed en secondaire")])
    brent = pts("brent")
    us2, de2, jp2 = dict(pts("USD_2a")), dict(pts("EUR_2a")), dict(pts("JPY_2a"))

    def ecart(a, b, lib):
        com = sorted(set(a) & set(b))
        return f"{lib} : {fr((a[com[-1]] - b[com[-1]]) * 100, 0, True)} pb au {jj(com[-1])}" if com else f"{lib} : n/d (série absente)"
    ecarts = [ecart(us2, de2, "US 2 ans − Allemagne 2 ans"), ecart(us2, jp2, "US 2 ans − Japon 2 ans"),
              "UK 2 ans − US 2 ans : n/d (rendement britannique à 2 ans non collecté : la Banque d'Angleterre ne publie que le 10 ans dans la série utilisée)"]
    p_qqq, p_or, p_brent = performance_mois(pts("nasdaq_qqq"), au), performance_mois(pts("or_xau"), au), performance_mois(brent, au)
    p_spy = performance_mois(spy or pts("sp500"), au)
    v10 = variation_mois_pb(pts("USD_10a"), au)
    perf = lambda p, lib: (f"{lib} sur {p['mois']} : {fr(p['pct'], 2, True)} % (clôtures du {jj(p['du'])} et du {jj(p['au'])})"
                           if p.get("pct") is not None else f"{lib} sur {p['mois']} : n/d ({p['raison']})")
    sous = [
        ("Obligations", [f"Rendement US 10 ans sur {v10['mois']} : {fr(v10['pb'], 0, True)} pb" if v10.get("pb") is not None else "Rendement US 10 ans : n/d"] + ecarts, "obligations"),
        ("Actions", [perf(p_qqq, "Nasdaq (ETF QQQ)"), perf(p_spy, "S&P 500" + (" (ETF SPY)" if spy else " (FRED, 2 jours de retard)"))], "actions"),
        ("Pétrole", [perf(p_brent, "Brent") + (f" ; dernière valeur : clôture EIA du {jj(brent[-1][0])} ({fr(brent[-1][1], 1)} $)" if brent else ""),
                     "Cotation du jour non disponible gratuitement (Twelve Data : symbole Brent réservé aux plans payants)"], "petrole"),
        ("Or", [perf(p_or, "Or (XAU/USD)")], "or"),
    ]
    blocs = [T(["Actif", "Niveau", "Lecture"], lignes, "Tableau des actifs")]
    for titre, chiffres, cle in sous:
        blocs.append(L(chiffres, titre))
        blocs.append(L(_transmission(c, cle), "Transmission Forex"))
    blocs.append(N("Anticipations de banque centrale : écart entre le rendement à 2 ans et le taux directeur, indication de marché, "
                   "pas une probabilité (les probabilités tirées des contrats à terme ne sont pas disponibles gratuitement)."))
    phrase = perf(p_qqq, "Nasdaq") + " ; " + perf(p_or, "or") + " ; " + perf(p_brent, "Brent") + "."
    return section("long_marches", phrase, blocs)


def _long_regime(c):
    thermos = {t["numero"]: t for t in (c["base"].get("tableau_de_bord") or {}).get("thermometres") or []}
    lignes = []
    for f in c["cfg"].get("forces") or []:
        ts = [thermos.get(n) for n in f["engrenages"] if thermos.get(n)]
        dirs = [t["direction"]["classe"] for t in ts if t.get("direction")]
        sens = "haussier" if dirs.count("up") > dirs.count("dn") else "baissier" if dirs.count("dn") > dirs.count("up") else "neutre"
        lecture = {"haussier": "en accélération", "baissier": "en ralentissement", "neutre": "sans direction nette"}[sens]
        if f["force"] == "Appétit pour le risque":
            lecture = {"haussier": "appétit pour le risque", "baissier": "aversion au risque", "neutre": "sans direction nette"}[sens]
        lignes.append([f["force"], lecture, f["consequence"][sens],
                       " · ".join(f"engrenage {t['numero']} {t['titre']} : {t['texte_valeur']} ({t['direction']['libelle']})" for t in ts) or "n/d"])
    defe = [f"{r['texte']} ({_chiffre_var(r['si'][0], c['vars'])})" for r in c["cfg"].get("elements_defensifs") or [] if _regle(r["si"], c["vars"])[0]]
    stab = [f"{r['texte']} ({_chiffre_var(r['si'][0], c['vars'])})" for r in c["cfg"].get("elements_stabilisation") or [] if _regle(r["si"], c["vars"])[0]]
    diag = ("Risk-off dominant" if len(defe) >= len(stab) + 2 else "Risk-on dominant" if len(stab) >= len(defe) + 2 else
            "Régime mixte, sans domination nette") + f" : {len(defe)} élément{'s' if len(defe) > 1 else ''} défensif{'s' if len(defe) > 1 else ''}, {len(stab)} de stabilisation."
    return section("long_regime", diag, [
        T(["Force", "Lecture actuelle", "Conséquence potentielle", "Chiffres (engrenages)"], lignes, "Les 4 forces"),
        L(defe or ["Aucun élément défensif déclenché."], "Risk-on ou risk-off ? Éléments défensifs"),
        L(stab or ["Aucun élément de stabilisation déclenché."], "Éléments de stabilisation"),
        P(diag)])


def _long_banques(c):
    base, au, cfg = c["base"], c["aujourd"], c["cfg"]
    cond = cfg.get("conditions_bc") or {}
    blocs = []
    for b in base.get("banques") or []:
        badge = (b.get("badge") or {}).get("texte") or "n/d"
        blocs.append({"type": "cartes", "items": [{
            "titre": f"{b['devise']} · {b['banque']} · {jj(b['date'])}{(' à ' + b['heure']) if b.get('heure') and b['heure'] != 'journée' else ''}",
            "texte": f"Taux actuel {str(b.get('taux') or 'n/d').replace('.', ',')} → consensus {str(b.get('consensus') or 'n/d').replace('.', ',')} · {badge}",
            "note": "Enjeu : " + ", ".join(b.get("a_surveiller") or []) +
                    f". {b['devise']} haussier si : {', '.join(cond.get('haussiere') or [])}. {b['devise']} baissier si : {', '.join(cond.get('baissiere') or [])}."}]})
    passees = []
    for d, p in c["profils"].items():
        dern = (p.get("banque_centrale") or {}).get("derniere")
        if dern and (au - date.fromisoformat(dern["date"])).days <= 7:
            actuel, precedent = textes_communique(c["racine"], d)
            vocab = changements_vocabulaire(actuel, precedent) if actuel and precedent else []
            diss = votes_dissidents(actuel) if actuel else None
            passees.append(f"{d} · {p['banque_centrale']['prochaine'].get('banque') or ''} : {dern['texte']}"
                           + (" ; vocabulaire : " + " ; ".join(f"« {a} » devient « {b} »" for a, b in vocab) if vocab else
                              " ; changement de vocabulaire : n/d (" + ("aucun mot changé dans les phrases comparables" if actuel and precedent
                                                                        else "communiqué ou précédent non archivé") + ")")
                           + (f" ; vote dissident : « {diss} »" if diss else
                              " ; votes dissidents : " + ("aucun mentionné dans le communiqué" if actuel else "n/d (communiqué non archivé)")))
    blocs.append(L(passees or ["Aucune décision dans les 7 derniers jours."], "Banques déjà passées"))
    hors = [e for j in c["agenda"].get("jours") or [] for e in j.get("evenements") or []
            if re.search(r"riksbank|norges", str(e.get("evenement_en") or e.get("evenement")), re.I)]
    blocs.append(N("Riksbank, Norges Bank : " + (", ".join(f"{e['evenement']} ({jj(e['date_paris'])})" for e in hors)
                                                 if hors else "hors du flux de l'Agenda (9 devises suivies) cette semaine.")))
    phrase = (f"{len(base.get('banques') or [])} banque{'s' if len(base.get('banques') or []) > 1 else ''} centrale{'s' if len(base.get('banques') or []) > 1 else ''} cette semaine"
              + (f" ; déjà passées : {', '.join(x.split(' ·')[0] for x in passees)}." if passees else "."))
    return section("long_banques", phrase, blocs)


def textes_communique(racine, devise: str) -> tuple[str | None, str | None]:
    import json
    from pathlib import Path
    from core import communiques
    try:
        index = json.loads((Path(racine) / "data" / "communiques" / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    return communiques.textes_a_comparer(racine, index, devise)


def _phrases(texte: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.;])\s+", texte or "") if len(p.strip()) > 30]


def changements_vocabulaire(actuel: str, precedent: str, maximum: int = 3) -> list[tuple[str, str]]:
    """Mots remplacés entre deux phrases quasi identiques des deux communiqués (cités mot pour mot), ex. Fed
    « solid » -> « strong ». Calcul Python (difflib), aucun modèle."""
    import difflib
    sortie = []
    anciennes = _phrases(precedent)
    for ph in _phrases(actuel):
        meilleure = max(anciennes, key=lambda a: difflib.SequenceMatcher(None, a, ph).ratio(), default=None)
        if not meilleure:
            continue
        r = difflib.SequenceMatcher(None, meilleure, ph).ratio()
        if not 0.8 <= r < 1:
            continue
        a, b = meilleure.split(), ph.split()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
            if op == "replace" and i2 - i1 <= 3 and j2 - j1 <= 3:
                sortie.append((" ".join(a[i1:i2]).strip(",.;"), " ".join(b[j1:j2]).strip(",.;")))
        if len(sortie) >= maximum:
            break
    return sortie[:maximum]


def votes_dissidents(texte: str) -> str | None:
    """Phrase du communiqué qui mentionne un vote contre (citée telle quelle), sinon None."""
    for ph in _phrases(texte):
        if re.search(r"voting against|voted against|dissent|preferred to (?:lower|raise|maintain)|vote contre|dissident", ph, re.I):
            return ph[:300]
    return None


def lecture_surprise(e: dict, config: dict) -> list[str] | None:
    """« Au-dessus de X : … / En dessous de X : … » : sens de l'indicateur (registre) et lecture classique (simulateur)."""
    from core import agenda as ag
    cfg_tm = config.get("tableau_macro") or {}
    ind = ag._indicateur(e, cfg_tm)
    if not ind or e.get("consensus") in (None, ""):
        return None
    sens = ((cfg_tm.get("indicateurs") or {}).get(ind) or {}).get("sens", "normal")
    d, x = e["devise"], re.sub(r"(\d)%$", r"\1 %", str(e["consensus"]).replace(".", ","))
    favorable_haut = sens != "inverse"
    lc = ((config.get("simulateur") or {}).get("lecture_classique") or {}).get(SIM.get((d, ind)) or "", {})
    autres_contre = [k for k, v in lc.items() if k != d and v < 0]
    eff = lambda haut: (f"lecture classique {'favorable' if haut == favorable_haut else 'défavorable'} au {d}" if d != "EUR" else
                        f"lecture classique {'favorable' if haut == favorable_haut else 'défavorable'} à l'EUR") + \
        (f" ; {', '.join(autres_contre)} {'sous pression' if haut == favorable_haut else 'soutenus'}" if autres_contre else "")
    return [f"Au-dessus de {x} : {eff(True)}.", f"En dessous de {x} : {eff(False)}."]


def _long_calendrier(c):
    au, config = c["aujourd"], c["config"]
    evts = _evts_semaine(c["agenda"], au, ("fort", "moyen"))
    lignes = [[f"{JOURS[date.fromisoformat(e['date_paris']).weekday()]} {jj(e['date_paris'])}", e.get("heure_paris") or "—",
               f"{e['devise']} {e['evenement']}", e.get("points") or e.get("impact")] for e in evts]
    forts = [e for e in evts if e.get("impact") == "fort" and e.get("type") == "Chiffre" and e.get("consensus") not in (None, "")]
    donnees = [[f"{e['devise']} {e['evenement']} ({jj(e['date_paris'])})", str(e.get("consensus") or "n/d").replace(".", ","),
                str(e.get("precedent") or "n/d").replace(".", ",")] for e in forts]
    surprises = []
    for e in forts:
        l = lecture_surprise(e, config)
        if l:
            surprises.append(f"{e['devise']} {e['evenement']} : " + " ".join(l))
    phrase = f"{len(evts)} évènement{'s' if len(evts) > 1 else ''} fort{'s' if len(evts) > 1 else ''} ou moyen{'s' if len(evts) > 1 else ''} du lundi au vendredi, dont {len(forts)} publication{'s' if len(forts) > 1 else ''} forte{'s' if len(forts) > 1 else ''}."
    return section("long_calendrier", phrase, [
        T(["Jour", "Heure (Paris)", "Évènement", "Importance"], lignes, "Calendrier"),
        T(["Donnée", "Consensus", "Précédent"], donnees, "Les données les plus importantes"),
        L(surprises or ["Aucune publication forte avec consensus cette semaine."], "Comment lire les surprises"),
        N("Seuil X = le consensus ; sens : registre des indicateurs (chômage : inverse) et lecture classique du simulateur.")])


def _long_geopolitique(c):
    au, cfg = c["aujourd"], c["cfg"]
    debut, fin = _semaine(au)
    rdv = [g for g in c["agenda"].get("grands_rendez_vous") or [] if debut <= g.get("date", "") <= (date.fromisoformat(fin) + timedelta(days=9)).isoformat()]
    blocs = [L([f"{jj(g['date'])} · {g['titre']} ({', '.join(g.get('devises') or [])}) — source : {g.get('source')}" for g in rdv] or
               ["Aucun grand rendez-vous politique dans l'Agenda."], "Grands rendez-vous")]
    for g in rdv:
        t = next((x for x in cfg.get("issues_politiques") or [] if any(m in g["titre"].lower() for m in x["mots"])), None)
        if t:
            blocs.append(T(["Résultat possible", "Conséquence potentielle"], t["issues"], g["titre"]))
    e6 = (((c["base"].get("tableau_de_bord") or {}).get("thermometres") or [{}] * 6)[5:6] or [{}])[0]
    blocs.append(P(f"Engrenage 6 (géopolitique) : {e6.get('texte_valeur', 'n/d')} titre{'s' if str(e6.get('texte_valeur')) not in ('0', '1') else ''} "
                   f"officiel{'s' if str(e6.get('texte_valeur')) not in ('0', '1') else ''} classé{'s' if str(e6.get('texte_valeur')) not in ('0', '1') else ''} ; "
                   f"lecture : {(e6.get('direction') or {}).get('libelle', 'n/d')}."))
    blocs.append(N(f"Résultats d'entreprises majeures (Apple, Nvidia, Microsoft…) : n/d — {(cfg.get('resultats_entreprises') or {}).get('raison')}."))
    return section("long_geopolitique", f"{len(rdv)} grand{'s' if len(rdv) > 1 else ''} rendez-vous politique{'s' if len(rdv) > 1 else ''} à l'horizon.", blocs)


def _long_devises(c):
    lignes, blocs = [], []
    forts = _evts_semaine(c["agenda"], c["aujourd"])
    for d, p in c["profils"].items():
        dom = p["moteur"]["dominant"]
        lignes.append([d, p["etat"]["valeur"], f"{dom['libelle']} ({fr(dom['r60'], 2, True)})" if dom else "aucun facteur dominant"])
        renf, aff = [], []
        if dom:
            sens = "hausse" if dom["r60"] > 0 else "baisse"
            nom = dom.get("nom") or dom["libelle"]
            renf.append(f"une {sens} de {nom} (corrélation {fr(dom['r60'], 2, True)})")
            aff.append(f"une {'baisse' if sens == 'hausse' else 'hausse'} de {nom}")
        for e in [x for x in forts if x["devise"] == d][:2]:
            if e.get("type") == "Réunion BC":
                renf.append(f"une décision plus restrictive qu'attendu ({jj(e['date_paris'])})")
                aff.append(f"une décision plus accommodante qu'attendu ({jj(e['date_paris'])})")
            elif e.get("consensus"):
                renf.append(f"{e['evenement']} au-dessus du consensus ({str(e['consensus']).replace('.', ',')})")
                aff.append(f"{e['evenement']} en dessous du consensus")
        blocs.append(L([f"Ce qui la renforcerait : {', '.join(renf) or 'n/d (aucun moteur ni évènement fort)'}.",
                        f"Ce qui l'affaiblirait : {', '.join(aff) or 'n/d'}."], f"{d} · {p['nom']}"))
    return section("long_devises", "Biais de travail par devise : état du profil (partie A) et facteur dominant du moment.",
                   [T(["Devise", "Biais de travail", "Facteur dominant"], lignes)] + blocs)


def _long_paires(c):
    top = ((c["base"].get("watchlist") or {}).get("top") or [])[:6]
    cartes = []
    for w in top:
        cata = [x for x in w["scenario_haussier"]["conditions"] + w["scenario_baissier"]["conditions"] if "(" in x and "/" in x][:2]
        inval = (w["scenario_baissier"]["conditions"] or ["n/d"])[0]
        cartes.append({"titre": f"{w['paire']} · {w['libelle']}",
                       "texte": f"Catalyseur : {', '.join(cata) or 'aucun évènement fort cette semaine'}.",
                       "note": (f"Haussier si : {', '.join(w['scenario_haussier']['conditions'])}. Baissier si : {', '.join(w['scenario_baissier']['conditions'])}. "
                                f"Confirmation : {w.get('confirmations')}. Invalidation du scénario haussier : {inval}.")})
    return section("long_paires", f"{len(top)} paire{'s' if len(top) > 1 else ''} prioritaire{'s' if len(top) > 1 else ''} (watchlist, score Python).",
                   [{"type": "cartes", "items": cartes}, N((c["base"].get("watchlist") or {}).get("methode") or "")])


def _long_scenarios(c):
    s = c["base"].get("scenarios") or {}
    blocs = []
    for lettre, x in zip("ABC", s.get("liste") or []):
        remplies = [k["libelle"] for k in x["conditions"] if k.get("remplie")]
        blocs.append(L([f"{x['statut']}{' · invalidé' if x.get('invalide') else ''}",
                        f"Conditions remplies : {', '.join(remplies) or 'aucune'}."], f"Scénario {lettre} · {x['titre']}"))
    meilleur = next((x for x in s.get("liste") or [] if x.get("mieux_confirme")), None)
    inval = [k["libelle"] for k in (meilleur or {}).get("invalidations") or []]
    blocs.append(L(inval or ["n/d (aucun scénario mieux confirmé)"], "Ce qui invaliderait le diagnostic"))
    return section("long_scenarios", s.get("texte_mieux_confirme") or "Scénarios n/d.", blocs)


def _long_technique(c):
    au, agenda = c["aujourd"], c["agenda"]
    bc = list({(e["devise"], e["date_paris"], e.get("heure_paris")): e for e in _evts_semaine(agenda, au)
               if e.get("type") == "Réunion BC" and not re.search(r"vote", e.get("evenement_en") or "", re.I)}.values())
    regles = [
        "Éviter les créneaux des décisions : " + (", ".join(f"{e['devise']} {JOURS[date.fromisoformat(e['date_paris']).weekday()]} {jj(e['date_paris'])} "
                                                         f"{e.get('heure_paris') or ''} (± 30 min)" for e in bc) or "aucune décision cette semaine") + ".",
        "Ne pas confondre la première réaction avec le mouvement : attendre la clôture de la bougie H1 qui suit une publication forte "
        f"({len(_evts_semaine(agenda, au))} cette semaine).",
    ]
    top = ((c["base"].get("watchlist") or {}).get("top") or [])[:6]
    devs = {}
    for w in top:
        for d in w["paire"].split("/"):
            devs[d] = devs.get(d, 0) + 1
    corr = [d for d, n in devs.items() if n >= 2]
    regles.append("Alerte d'exposition corrélée : " + (f"{', '.join(corr)} apparai{'ssent' if len(corr) > 1 else 't'} dans plusieurs paires prioritaires, "
                                                       "ne pas cumuler des positions dans le même sens." if corr else "aucune devise répétée dans les paires prioritaires."))
    return section("long_technique", "Trois règles de la semaine, calculées à partir de l'Agenda et de la watchlist.",
                   [T(["Unité de temps", "Rôle", "Ce qu'on y cherche"], c["cfg"].get("unites_de_temps") or [], "Unités de temps"),
                    L(regles, "Les trois règles de la semaine")])


def _long_plan(c):
    au, agenda = c["aujourd"], c["agenda"]
    debut, _ = _semaine(au)
    jours = []
    for k in range(5):
        d = (date.fromisoformat(debut) + timedelta(days=k)).isoformat()
        ev = [e for j in agenda.get("jours") or [] if j["date"] == d for e in j.get("evenements") or [] if e.get("impact") == "fort"]
        jours.append([f"{JOURS[k]} {jj(d)}", " · ".join(f"{e.get('heure_paris') or ''} {e['devise']} {e['evenement']}" for e in ev[:4]) or "aucun évènement fort",
                      "journée à risque : réduire l'exposition avant les publications" if len(ev) >= 3 else "suivre les paires prioritaires" if ev else "journée calme : préparer les scénarios"])
    reg = c["regime"]
    uniques = {}
    for e in sorted(_evts_semaine(agenda, au), key=score_evenement, reverse=True):
        uniques.setdefault((e["devise"], e["date_paris"]), e)   # une priorité par devise et par jour
    prios = [f"Surveiller {e['devise']} {e['evenement']} ({jj(e['date_paris'])})" for e in list(uniques.values())[:3]]
    prios += [f"Paire prioritaire : {w['paire']}" for w in ((c["base"].get("watchlist") or {}).get("top") or [])[:2]]
    meilleur = next((x for x in (c["base"].get("scenarios") or {}).get("liste") or [] if x.get("mieux_confirme")), None)
    lecture = (f"Lecture institutionnelle : régime « {reg['libelle'].lower()} »"
               + (f", scénario le mieux confirmé « {meilleur['titre']} » ({meilleur['statut']})" if meilleur else ", aucun scénario confirmé")
               + " ; biais conditionnels, jamais des ordres.")
    return section("long_plan", lecture, [T(["Jour", "Évènements forts", "Plan"], jours, "Plan jour par jour"),
                                          L(prios[:5], "Conclusion : les 5 priorités"), P(lecture)])
