"""Tuiles de chiffres clés des dossiers d'engrenages (refonte V2, palier 2 : dossiers 2, 3 et 5).

Une tuile = valeur, variation sur une période, mini-courbe, percentile 5 ans (ou sa raison), date, source,
âge de la donnée. Tout vient des cellules déjà calculées (core/dossiers.py) ou des séries datées ; une
valeur absente reste None avec sa raison, jamais inventée. Aucun LLM.
"""
from __future__ import annotations

from datetime import date, timedelta

from core import controles_macro

DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]


def _fr(v: float | None, d: int = 2) -> str:
    if v is None:
        return "n/d"
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",").replace("-", "−")


def _signe(v: float | None, d: int = 2) -> str:
    return "n/d" if v is None else ("+" if v > 0 else "") + _fr(v, d)


def _points(historiques: dict, cle: str) -> list[list]:
    return [[str(p[0])[:10], float(p[1])] for p in (((historiques or {}).get("series") or {}).get(cle) or {}).get("points") or []
            if p and p[1] is not None]


def _fenetre(points: list[list], jours: int) -> list[list]:
    if not points:
        return []
    limite = (date.fromisoformat(points[-1][0]) - timedelta(days=jours)).isoformat()
    return [[d, round(v, 4)] for d, v in points if d >= limite]


def _age(jour: str | None) -> int | None:
    try:
        return (date.today() - date.fromisoformat(str(jour))).days if jour and len(str(jour)) == 10 else None
    except ValueError:
        return None


def texte_valeur(v: float | None, unite: str | None) -> str | None:
    if v is None:
        return None
    if unite == "%":
        return f"{_fr(v, 2)} %"
    if unite == "pb":
        return f"{_signe(v, 0)} pb"
    if unite in ("écarts", "corrélation"):
        return _signe(v, 2)
    if unite == "part":
        return f"{_fr(v, 0)} %"
    if unite in ("nombre", "score", "semaines"):
        return _fr(v, 0)
    if unite == "M barils":
        return f"{_fr(v, 1)} M"
    if unite == "milliers b/j":
        return f"{_fr(v, 0)} k b/j"
    if unite == "contrats":
        return _signe(v, 0)
    if unite == "rsi":
        return _fr(v, 1)
    if unite in ("% annualisé", "% PIB"):
        return f"{_fr(v, 1)} %"
    if unite == "$":
        return f"{_fr(v, 2)} $"
    return _fr(v, 2 if abs(v) < 100 else 1 if abs(v) < 1000 else 0)


def tuile(ident: str, libelle: str, cel: dict | None, courbe: list[list] | None = None, periode: str = "30 jours",
          unite: str | None = None, raison_courbe: str | None = None, lecture: str | None = None) -> dict:
    """Tuile depuis une cellule de dossier ({valeur, unite, date, source, var_1s, var_4s, percentile_5a…})."""
    cel = cel or {}
    u = unite or cel.get("unite")
    v = cel.get("valeur")
    variation = cel.get("variation")   # variation explicite (période propre à la tuile) : prioritaire
    for cle, per in (("var_4s", "4 semaines"), ("var_1s", "1 semaine")):
        if variation is None and cel.get(cle) is not None:
            unite_var = "pb" if u in ("%", "pb") else "contrats" if u == "contrats" else "%"
            variation = {"valeur": cel[cle], "unite": unite_var, "periode": per,
                         "texte": f"{_signe(cel[cle], 0 if unite_var in ('pb', 'contrats') else 2)} {unite_var} sur {per}"}
    if variation is None and cel.get("tendance_3m") is not None:
        variation = {"valeur": cel["tendance_3m"], "unite": "pt", "periode": "3 mois",
                     "texte": f"{_signe(cel['tendance_3m'])} pt sur 3 mois"}
    courbe = courbe or []
    return {"id": ident, "libelle": libelle, "valeur": v, "texte": texte_valeur(v, u) if v is not None else None,
            "unite": u, "date": cel.get("date"), "frequence": cel.get("frequence"), "age_jours": _age(cel.get("date")), "source": cel.get("source"),
            "raison": None if v is not None else (cel.get("raison") or "donnée indisponible"),
            "variation": variation, "percentile_5a": cel.get("percentile_5a"), "n_5a": cel.get("n_5a"),
            "percentile_autre": ({"valeur": cel["percentile_52s"], "libelle": "52 semaines"} if cel.get("percentile_52s") is not None
                                 else {"valeur": cel["percentile_90j"], "libelle": "90 jours"} if cel.get("percentile_90j") is not None
                                 else None),
            "raison_percentile": None if cel.get("percentile_5a") is not None else
            (cel.get("raison_percentile") or ("pas de série longue" if v is not None else None)),
            "courbe": {"points": courbe, "periode": periode,
                       "raison": None if len(courbe) >= 2 else (raison_courbe or "pas d'historique pour une mini-courbe")},
            "lecture": lecture or cel.get("lecture") or cel.get("note")}


def _cellules(e: dict) -> dict:
    return {l["devise"]: l.get("cellules") or {} for l in (e or {}).get("lignes") or []}


def _difference(a: list[list], b: list[list], facteur: float = 100) -> list[list]:
    sortie, i, vb = [], 0, None
    for d, va in a:
        while i < len(b) and b[i][0] <= d:
            vb = b[i][1]
            i += 1
        if vb is not None:
            sortie.append([d, round((va - vb) * facteur, 2)])
    return sortie


def _avec_variation_mensuelle(cel: dict | None) -> dict | None:
    """Série mensuelle : variation sur 3 mois (en pb pour un taux) tirée de la série jointe à la cellule."""
    if not cel or not cel.get("serie_mensuelle") or len(cel["serie_mensuelle"]) < 4:
        return cel
    pts = cel["serie_mensuelle"]
    d = round((pts[-1][1] - pts[-4][1]) * 100)
    return {**cel, "variation": {"valeur": d, "unite": "pb", "periode": "3 mois", "texte": f"{_signe(d, 0)} pb sur 3 mois"}}


# ------------------------------------------------------------- engrenage 2
def tuiles_2(e: dict, historiques: dict) -> list[dict]:
    c = _cellules(e)
    usd, eur, jpy, aud, gbp = (c.get(d, {}) for d in ("USD", "EUR", "JPY", "AUD", "GBP"))
    us2, dff, us10 = _points(historiques, "USD_2a"), _points(historiques, "USD_taux_effectif"), _points(historiques, "USD_10a")
    decision = "taux fixé par décision : pas de série quotidienne pour une mini-courbe"
    return [
        tuile("fed", "Taux effectif Fed", usd.get("taux_directeur"), _fenetre(dff, 30)),
        tuile("us2a", "Rendement 2 ans US", usd.get("taux_2a"), _fenetre(us2, 30)),
        tuile("us2a_dir", "2 ans US − taux effectif", usd.get("ecart_2a_directeur"), _fenetre(_difference(us2, dff), 30)),
        tuile("taux_reel_us", "Taux réel US (directeur − core)", _avec_variation_mensuelle(usd.get("taux_reel")),
              (usd.get("taux_reel") or {}).get("serie_mensuelle"), "12 mois (mensuel)",
              raison_courbe="série mensuelle indisponible"),
        tuile("pente_us", "Courbe 2-10 ans US", usd.get("pente_2_10"), _fenetre(_difference(us10, us2), 30)),
        tuile("bce", "BCE, taux de dépôt" if "ECBDFR" in str((eur.get("taux_directeur") or {}).get("source"))
              else "BCE, taux de refinancement (registre)", eur.get("taux_directeur"), _fenetre(_points(historiques, "EUR_taux_depot"), 30),
              raison_courbe=decision),
        tuile("eur2a", "Rendement 2 ans allemand", eur.get("taux_2a"), _fenetre(_points(historiques, "EUR_2a"), 30)),
        tuile("boe", "BoE, taux directeur", gbp.get("taux_directeur"), _fenetre(_points(historiques, "GBP_taux_effectif"), 30),
              "30 jours (SONIA quotidien)"),
        tuile("boj", "BoJ, jour le jour", jpy.get("taux_directeur"), _fenetre(_points(historiques, "JPY_taux_effectif"), 30)),
        tuile("jp2a", "Rendement 2 ans japonais", jpy.get("taux_2a"), _fenetre(_points(historiques, "JPY_2a"), 30)),
        tuile("rba", "RBA, taux directeur", aud.get("taux_directeur"), None, raison_courbe=decision),
    ]


# ------------------------------------------------------------- engrenage 3
def _surprises_30j(registre: dict, cfg_tm: dict, jour: date) -> list[tuple[str, float]]:
    plafond = float((cfg_tm.get("indice_surprise") or {}).get("plafond_surprise", 3))
    limite = (jour - timedelta(days=30)).isoformat()
    cases = (registre or {}).get("cases") or {}
    sortie = []
    for devise in DEVISES:
        for indicateur, cfg_ind in (cfg_tm.get("indicateurs") or {}).items():
            if cfg_ind.get("marche"):
                continue
            for d, s in controles_macro._surprises(cases.get(f"{devise}|{indicateur}") or {}, cfg_ind, plafond):
                if limite <= d <= jour.isoformat():
                    sortie.append((devise, s))
    return sortie


def historique_surprise(registre: dict, cfg_tm: dict, semaines: int = 13) -> dict[str, list[list]]:
    aujourdhui = date.today()
    hist: dict[str, list[list]] = {d: [] for d in DEVISES}
    for k in range(semaines, -1, -1):
        jour = aujourdhui - timedelta(days=7 * k)
        for devise, v in controles_macro.indice_surprise(registre, cfg_tm, jour).items():
            if devise in hist and v.get("indice") is not None:
                hist[devise].append([jour.isoformat(), v["indice"]])
    return hist


def tuiles_3(e: dict, historiques: dict, registre: dict, config: dict) -> list[dict]:
    cfg_tm = config.get("tableau_macro") or {}
    c = _cellules(e)
    hist = historique_surprise(registre, cfg_tm)
    sortie = []
    for devise in ("USD", "GBP", "CAD", "AUD"):
        cel = dict((c.get(devise) or {}).get("indice_surprise") or {})
        h = hist.get(devise) or []
        if len(h) >= 5 and cel.get("valeur") is not None:
            d4 = round(cel["valeur"] - h[-5][1], 2)
            cel["variation"] = {"valeur": d4, "unite": "écarts", "periode": "4 semaines",
                                "texte": f"{_signe(d4)} sur 4 semaines"}
        sortie.append(tuile(f"surprise_{devise.lower()}", f"Surprise {devise} (30 j)", cel, h, "90 jours (hebdomadaire)"))
    core = _points(historiques, "USD_core_indice")
    glissement = []
    par_mois = {d[:7]: v for d, v in core}
    for d, v in core:
        base = par_mois.get(f"{int(d[:4]) - 1:04d}-{d[5:7]}")
        if base:
            glissement.append([d, round((v / base - 1) * 100, 2)])
    sortie.append(tuile("core_us", "Inflation core US (a/a)", (c.get("USD") or {}).get("inflation_core"),
                        glissement[-13:], "12 mois (mensuel)"))
    for devise in ("GBP", "AUD"):
        sortie.append(tuile(f"chomage_{devise.lower()}", f"Chômage {devise}", (c.get(devise) or {}).get("chomage"),
                            _points(historiques, f"{devise}_chomage")[-13:], "12 mois (mensuel, OCDE)"))
    surprises = _surprises_30j(registre, cfg_tm, date.today())
    if surprises:
        part = round(100 * sum(1 for _, s in surprises if s > 0) / len(surprises))
        cel = {"valeur": part, "date": date.today().isoformat(), "unite": "part",
               "source": f"calcul Python (registre macro, {len(surprises)} publications avec consensus sur 30 jours)",
               "raison_percentile": "registre tenu depuis 2026 seulement"}
    else:
        cel = {"valeur": None, "raison": "aucune publication avec consensus sur 30 jours"}
    sortie.append(tuile("part_positives", "Publications au-dessus du consensus", cel, None,
                        raison_courbe="part recalculée chaque jour, non historisée", unite="part",
                        lecture="au-dessus de 50 % : l'économie surprend plutôt en bien"))
    return sortie


# ------------------------------------------------------------- engrenage 5
COLONNES_CHALEUR = [("VIX", "VIX"), ("S&P 500", "S&P 500"), ("Pétrole Brent", "Brent"),
                    ("Indice or (proxy)", "Or (proxy)"), ("Rendement 10 ans US", "10 ans US")]
LECTURE_CORR = ("corrélation des rendements quotidiens de la force de chaque devise avec l'actif, sur 30 séances "
                "(+1 : bougent ensemble, −1 : en sens inverse). Corrélation n'est pas causalité.")


def matrice_chaleur(e: dict, historiques: dict | None = None) -> dict:
    """Devises × actifs. Source prioritaire : corrélations glissantes calculées sur 5 ans de prix (avec percentile) ;
    à défaut, la matrice du jour du dossier (prix Twelve Data, 90 séances, sans percentile), en le disant."""
    c5 = ((historiques or {}).get("correlations_5a") or {})
    if c5.get("paires"):
        lignes = []
        for devise in DEVISES:
            cases = [c5["paires"].get(f"{devise}|{col}") or {} for col, _ in COLONNES_CHALEUR]
            lignes.append({"devise": devise, "valeurs": [x.get("valeur") for x in cases],
                           "precedentes": [x.get("precedente") for x in cases],
                           "percentiles": [x.get("percentile_5a") for x in cases],
                           "raison": None if any(cases) else "série de change indisponible"})
        return {"colonnes": [lib for _, lib in COLONNES_CHALEUR], "lignes": lignes, "seances": c5.get("seances", 30),
                "derniere_seance": c5.get("derniere_seance"), "source": c5.get("source"), "percentile_5a": True,
                "lecture": LECTURE_CORR + " Percentile : rang de la corrélation du jour parmi toutes les fenêtres de 30 séances des 5 ans."}
    corr = (e or {}).get("correlations") or {}
    m, prec = corr.get("matrice") or {}, corr.get("matrice_precedente") or {}
    lignes = []
    for devise in DEVISES:
        valeurs = [(m.get(devise) or {}).get(col) for col, _ in COLONNES_CHALEUR]
        avant = [(prec.get(devise) or {}).get(col) for col, _ in COLONNES_CHALEUR]
        lignes.append({"devise": devise, "valeurs": valeurs, "precedentes": avant,
                       "raison": None if any(v is not None for v in valeurs) else "série de force indisponible"})
    return {"colonnes": [lib for _, lib in COLONNES_CHALEUR], "lignes": lignes, "seances": corr.get("seances", 30),
            "derniere_seance": corr.get("derniere_seance"), "source": corr.get("source"), "percentile_5a": False,
            "lecture": LECTURE_CORR + " Corrélations 5 ans indisponibles aujourd'hui : matrice du jour sans percentile."}


def _tuile_correlation(e: dict, historiques: dict | None, a: str, b: str, libelle: str, lecture: str) -> dict:
    x = (((historiques or {}).get("correlations_5a") or {}).get("paires") or {}).get(f"{a}|{b}")
    if x:
        cel = {"valeur": x["valeur"], "unite": "corrélation", "date": x["date"],
               "source": ((historiques or {}).get("correlations_5a") or {}).get("source"),
               "percentile_5a": x.get("percentile_5a"), "n_5a": x.get("n_5a"), "raison_percentile": x.get("raison_percentile")}
        r, r0, courbe, periode = x["valeur"], x.get("precedente"), x.get("courbe"), "120 jours (corrélation glissante)"
        lecture = f"{lecture} · extrêmes des 5 ans : {_fr(x.get('min_5a'))} à {_fr(x.get('max_5a'))}"
    else:
        corr = (e or {}).get("correlations") or {}
        r = ((corr.get("matrice") or {}).get(a) or {}).get(b)
        r0 = ((corr.get("matrice_precedente") or {}).get(a) or {}).get(b)
        cel = {"valeur": r, "unite": "corrélation", "date": corr.get("derniere_seance"), "source": corr.get("source"),
               "raison": None if r is not None else "moins de 15 séances communes",
               "raison_percentile": "corrélations 5 ans indisponibles aujourd'hui"}
        courbe, periode = None, "30 jours"
    if r is not None and r0 is not None:
        cel["variation"] = {"valeur": round(r - r0, 2), "unite": "corrélation", "periode": "30 séances précédentes",
                            "texte": f"{_signe(round(r - r0, 2))} vs 30 séances plus tôt (r = {_fr(r0)})"}
    return tuile(f"corr_{a}_{b}".lower().replace(" ", "_"), libelle, cel, courbe, periode,
                 raison_courbe="corrélations 5 ans indisponibles aujourd'hui", lecture=lecture)


def tuiles_5(e: dict, historiques: dict) -> list[dict]:
    cel = {l["id"]: l["cellule"] for l in (e or {}).get("instruments") or []}
    sortie = []
    for ident, lib in (("dollar_large", "Indice dollar large (Fed)"), ("vix", "VIX"), ("sp500", "S&P 500"),
                       ("USD_10a", "Rendement 10 ans US"), ("indice_or", "Indice or (proxy)"), ("brent", "Pétrole Brent"),
                       ("wti", "Pétrole WTI")):
        c = dict(cel.get(ident) or {})
        u = "%" if c.get("unite") == "%" else None
        sortie.append(tuile(ident, lib, c, _fenetre(_points(historiques, ident), 30), unite=u,
                            lecture=c.get("alerte")))
    sortie.append(_tuile_correlation(e, historiques, "AUD", "S&P 500", "Corrélation AUD / S&P 500",
                                     "positive : l'AUD se comporte en devise « risque »"))
    sortie.append(_tuile_correlation(e, historiques, "JPY", "VIX", "Corrélation JPY / VIX",
                                     "positive : le yen joue son rôle de refuge quand la volatilité monte"))
    return sortie
