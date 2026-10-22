"""Palier 3 de la refonte : tuiles, graphiques et tableaux manquants des dossiers 1, 4, 6, 7 et 8.

Tout est calculé en Python à partir de séries datées (historiques, technique, COT, registre, rapports
archivés) ; une valeur absente reste « n/d » avec sa raison. Aucun LLM.
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import date, timedelta
from pathlib import Path

from core import registre_macro as rm, vue_ensemble
from core.tuiles import DEVISES, _fenetre, _fr, _points, _signe, tuile

DIRECTION = {"haussier": "Dollar haussier", "baissier": "Dollar baissier", "neutre": "Dollar neutre"}


def _graphique_serie(titre, unite, lignes, source, base_100=False):
    from core.dossiers import graphique_serie
    return graphique_serie(titre, unite, lignes, source, base_100)


def _graphique_barres(titre, unite, valeurs, source, note=None):
    from core.dossiers import graphique_barres
    return graphique_barres(titre, unite, valeurs, source, note)


def _stats(points, unite, source, frequence="quotidien", **kw):
    from core.dossiers import stats
    return stats([(d, v) for d, v in points], unite, source, frequence, **kw)


def _variation_points(pts: list[list], jours: int, unite: str, decimales: int = 0) -> dict | None:
    """Écart entre la dernière valeur et celle d'il y a `jours` jours ; à défaut (archives plus courtes ou
    trouées), avec la plus ancienne valeur de la série si elle a au moins 14 jours — la période réelle est dite."""
    if len(pts) < 2:
        return None
    fin = date.fromisoformat(pts[-1][0])
    avant = [p for p in pts if p[0] <= (fin - timedelta(days=jours)).isoformat()]
    ref = avant[-1] if avant else pts[0]
    ecart_j = (fin - date.fromisoformat(ref[0])).days
    if ecart_j < 14:
        return None
    d = round(pts[-1][1] - ref[1], decimales)
    per = f"{jours // 7} semaines" if avant and jours % 7 == 0 else f"{ecart_j} jours (depuis le {ref[0][8:10]}/{ref[0][5:7]})"
    return {"valeur": d, "unite": unite, "periode": per, "texte": f"{_signe(d, decimales)} {unite} sur {per}"}


# ------------------------------------------------------------- engrenage 1
def archives_scores(dossier_rapports: str | Path | None, jours: int = 35) -> list[dict]:
    """[{date, scores, biais}] des rapports archivés des `jours` derniers jours (un par jour de rapport)."""
    if not dossier_rapports:
        return []
    limite = (date.today() - timedelta(days=jours)).isoformat()
    sortie = []
    for f in sorted(Path(dossier_rapports).glob("????-??-??.json")):
        if f.stem < limite:
            continue
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sc = {d["devise"]: d.get("score_confluence") for d in r.get("devises") or [] if d.get("devise")}
        sortie.append({"date": f.stem, "scores": sc, "biais": (r.get("synthese_globale") or {}).get("biais_macro_global")})
    return sortie


def duree_theme_semaines(archives: list[dict], biais: str | None) -> tuple[int | None, str | None]:
    """Semaines consécutives (en remontant depuis aujourd'hui) où le biais archivé est resté le même."""
    if not biais or not archives:
        return None, None
    debut = None
    for a in reversed(archives):
        if a["biais"] != biais:
            break
        debut = a["date"]
    if debut is None:
        return None, None
    jours = (date.fromisoformat(archives[-1]["date"]) - date.fromisoformat(debut)).days
    return jours // 7, debut


def complements_1(e: dict, rapport: dict | None, historiques: dict, dossier_rapports, dossiers: dict) -> None:
    if not rapport or e.get("indisponible"):
        return
    archives = archives_scores(dossier_rapports)
    scores = {d["devise"]: d.get("score_confluence") for d in rapport.get("devises") or []}
    jour = (rapport.get("meta") or {}).get("date_rapport")
    if not archives or archives[-1]["date"] != jour:
        archives.append({"date": jour, "scores": scores, "biais": (rapport.get("synthese_globale") or {}).get("biais_macro_global")})

    def historique(devise):
        return [[a["date"], a["scores"].get(devise)] for a in archives if a["scores"].get(devise) is not None][-31:]

    tuiles = []
    for devise in ("USD", "CAD", "AUD"):
        h = historique(devise)
        cel = {"valeur": scores.get(devise), "unite": "score", "date": jour, "source": "calcul Python (score de confluence 0-100)",
               "raison_percentile": "scores archivés depuis août 2026 seulement", "variation": _variation_points(h, 28, "pts")}
        tuiles.append(tuile(f"score_{devise.lower()}", f"Score {devise}", cel, h, "30 jours (rapports archivés)"))
    valides = sorted([(s, d) for d, s in scores.items() if s is not None], reverse=True)
    ecarts = [[a["date"], max(v for v in a["scores"].values() if v is not None) - min(v for v in a["scores"].values() if v is not None)]
              for a in archives if any(v is not None for v in a["scores"].values())][-31:]
    tuiles.append(tuile("ecart_max", "Écart meilleur − moins bon score",
                        {"valeur": valides[0][0] - valides[-1][0] if valides else None, "unite": "score", "date": jour,
                         "source": f"calcul Python ({valides[0][1]} − {valides[-1][1]})" if valides else None,
                         "raison": None if valides else "scores indisponibles", "variation": _variation_points(ecarts, 28, "pts"),
                         "raison_percentile": "scores archivés depuis août 2026 seulement"},
                        ecarts, "30 jours (rapports archivés)", lecture="plus l'écart est grand, plus le marché est tranché"))
    eng = (((rapport.get("synthese_globale") or {}).get("engrenages")) or {})
    par_num = {x["numero"]: x for x in eng.get("engrenages") or [] if x.get("numero")}
    coh = vue_ensemble.coherence(par_num) if par_num else None
    tuiles.append(tuile("coherence", "Engrenages alignés sur le thème",
                        {"valeur": coh["alignes"] if coh else None, "unite": "nombre", "date": jour,
                         "source": "règles Python des 8 engrenages", "raison": None if coh else "synthèse des engrenages absente",
                         "raison_percentile": "non historisé"},
                        None, raison_courbe="cohérence non historisée", lecture=(coh or {}).get("libelle")))
    if coh:
        tuiles[-1]["texte"] = coh["libelle"]
    indices = [l["cellules"]["indice_surprise"]["valeur"] for l in (dossiers.get("3") or {}).get("lignes", [])
               if (l["cellules"].get("indice_surprise") or {}).get("valeur") is not None]
    tuiles.append(tuile("surprise_globale", "Surprise globale (moyenne 9 devises)",
                        {"valeur": round(statistics.mean(indices), 2) if indices else None, "unite": "écarts", "date": jour,
                         "source": "calcul Python (registre macro, 30 j)", "raison": None if indices else "aucun indice de surprise",
                         "raison_percentile": "indice calculé depuis 2026 seulement"}, None,
                        raison_courbe="moyenne non historisée"))
    biais = (rapport.get("synthese_globale") or {}).get("biais_macro_global")
    semaines, debut = duree_theme_semaines(archives, biais)
    tuiles.append(tuile("duree_theme", "Régime actuel depuis",
                        {"valeur": semaines, "unite": "semaines", "date": jour, "source": "rapports archivés (biais calculé)",
                         "raison": None if semaines is not None else "biais du jour indisponible",
                         "raison_percentile": "non applicable"}, None, raison_courbe="non applicable",
                        lecture=f"régime {biais} sans interruption depuis le rapport du {debut}" if debut else None))
    if semaines is not None:
        tuiles[-1]["texte"] = f"{semaines} sem." if semaines else "< 1 sem."
    vix = _points(historiques, "vix")
    tuiles.append(tuile("vix", "VIX", _stats(vix, "niveau", "FRED (VIXCLS)") if vix else {"valeur": None, "raison": "série indisponible"},
                        _fenetre(vix, 30)))
    e["tuiles"] = tuiles
    # Graphique 1 : scores sur 30 jours (USD, meilleur et moins bon hors USD, EUR) ; graphique 2 : classement trié
    hors_usd = [d for _, d in valides if d != "USD"]
    choix = list(dict.fromkeys(["USD"] + hors_usd[:1] + hors_usd[-1:] + ["EUR"]))[:4]
    e["graphiques"] = [
        _graphique_serie("Scores de confluence, 30 jours", "0-100", [(d, historique(d)) for d in choix], "rapports archivés (data/rapports)"),
        _graphique_barres("Classement des 9 devises aujourd'hui", "0-100", [(d, s) for s, d in valides] +
                          [(d, None) for d in DEVISES if scores.get(d) is None], "calcul Python (scores de confluence)")]
    # Tableau « qui suit le thème »
    theme = vue_ensemble._direction(par_num.get(1)) if par_num else {}
    suivi = []
    for x in (coh or {}).get("detail", []):
        e_n = par_num.get(x["numero"]) or {}
        suivi.append({"numero": x["numero"], "nom": e_n.get("nom") or vue_ensemble.TITRES[x["numero"]],
                      "direction": x["direction"], "critere": x["critere"],
                      "accord": "oui" if x["aligne"] else ("non évaluable" if not x["critere"] else "non"),
                      "conviction": ((e_n.get("conviction") or {}).get("niveau"))})
    e["suivi_theme"] = {"theme": theme.get("libelle"), "lignes": suivi, "regle": (coh or {}).get("regle"),
                        "raison": None if coh else "synthèse des engrenages absente de ce rapport"}


# ------------------------------------------------------------- engrenage 4
PAYS_BUDGET = {"USD": ("u.s.", "us ", "america", "treasury", "congress", "white house", "senate", "fed "),
               "EUR": ("euro", "germany", "german", "france", "french", "italy", "italian", "spain", "ecb", "bund", "btp", "eu "),
               "GBP": ("uk ", "u.k.", "britain", "british", "gilt", "reeves", "starmer", "england"),
               "JPY": ("japan", "japanese", "jgb", "tokyo", "takaichi"),
               "CAD": ("canada", "canadian"), "AUD": ("australia",), "NZD": ("new zealand",), "CHF": ("swiss", "switzerland"),
               "CNY": ("china", "chinese", "beijing")}
MECANISMES_BUDGET = [
    (("debt ceiling", "shutdown", "default"), "incertitude budgétaire : prime de risque sur la dette et la devise"),
    (("bond auction", "adjudication", "issuance", "gilt", "btp", "bund", "jgb"), "offre de titres publics : pression sur les rendements longs (prime de terme)"),
    (("stimulus", "relance", "spending", "tax cut"), "relance budgétaire : croissance et inflation attendues plus hautes, taux en hausse"),
    (("austerity", "austérité"), "consolidation budgétaire : croissance freinée, taux longs détendus"),
    (("deficit", "déficit", "debt", "dette", "budget", "fiscal"), "déficit et dette : offre de titres et prime de risque"),
]


def dossier_budgetaire(actualites: list[dict]) -> list[dict]:
    lignes = []
    for a in actualites:
        bas = f" {(a.get('titre') or '').lower()} "
        pays = [d for d, mots in PAYS_BUDGET.items() if any(m in bas for m in mots)]
        mot, meca = next(((m, t) for mots, t in MECANISMES_BUDGET for m in mots if m in bas), (None, None))
        lignes.append({"pays": ", ".join(pays) or "non identifié", "sujet": a.get("titre"), "mot_cle": mot,
                       "mecanisme": meca or "non identifié", "devises": pays, "source": a.get("source"),
                       "date": a.get("date"), "lien": a.get("lien")})
    return lignes


def complements_4(e: dict, historiques: dict) -> None:
    c = {l["devise"]: l.get("cellules") or {} for l in e.get("lignes") or []}
    usd = c.get("USD") or {}
    dette = _points(historiques, "USD_dette_pib")
    solde = _points(historiques, "USD_solde_pib")
    tuiles = [
        tuile("dette_us", "Dette fédérale / PIB (US)", {**(usd.get("dette_pib") or {}), "unite": "% PIB",
              "raison_percentile": "série trimestrielle : 20 points sur 5 ans, percentile non calculé"},
              [[d, round(v, 1)] for d, v in dette[-12:]], "3 ans (trimestriel)"),
        tuile("solde_us", "Solde fédéral / PIB (US)", {**(usd.get("solde_pib") or {}), "unite": "% PIB"},
              [[d, round(v, 1)] for d, v in solde[-10:]], "10 ans (annuel)"),
    ]
    for devise, lib in (("USD", "10 ans US"), ("EUR", "10 ans Allemagne"), ("GBP", "10 ans Royaume-Uni"), ("JPY", "10 ans Japon")):
        tuiles.append(tuile(f"dix_{devise.lower()}", lib, (c.get(devise) or {}).get("taux_10a"),
                            _fenetre(_points(historiques, f"{devise}_10a"), 30)))
    tuiles.append(tuile("prime_terme", "Prime de terme 10 ans US", usd.get("prime_terme"),
                        _fenetre(_points(historiques, "USD_prime_terme"), 30)))
    it, de = _points(historiques, "ITA_10a_mensuel"), _points(historiques, "DEU_10a_mensuel")
    par_mois = {d[:7]: v for d, v in de}
    ecart = [[d, round((v - par_mois[d[:7]]) * 100, 1)] for d, v in it if d[:7] in par_mois]
    if ecart:
        cel = _stats(ecart, "pb", "calcul : 10 ans Italie − 10 ans Allemagne (OCDE via FRED, mensuels)", "mensuel")
        if len(ecart) >= 4:
            d3 = round(ecart[-1][1] - ecart[-4][1])
            cel["variation"] = {"valeur": d3, "unite": "pb", "periode": "3 mois", "texte": f"{_signe(d3, 0)} pb sur 3 mois"}
        cel["note"] = "moyennes mensuelles OCDE : pas de série quotidienne gratuite de l'écart BTP − Bund"
    else:
        cel = {"valeur": None, "raison": "séries OCDE Italie ou Allemagne indisponibles"}
    tuiles.append(tuile("btp_bund", "Écart Italie − Allemagne 10 ans", cel, ecart[-13:], "12 mois (mensuel)"))
    e["tuiles"] = tuiles
    e["dossier_budgetaire"] = dossier_budgetaire(e.get("actualites") or [])


# ------------------------------------------------------------- engrenage 6
def complements_6(e: dict, historiques: dict) -> None:
    comptes = {}
    for g in e.get("graphiques") or []:
        if g.get("type") == "barres":
            comptes = {b["nom"]: b["valeur"] for b in g.get("barres") or []}
            comptes.update({n: 0 for n in g.get("absentes") or []})
    jour = date.today().isoformat()
    tuiles = []
    for nom in ("Énergie", "Commerce", "Sanctions", "Refuge (conflits)", "Politique intérieure"):
        tuiles.append(tuile(f"canal_{nom[:6].lower()}", f"Titres : {nom.lower()}",
                            {"valeur": comptes.get(nom, 0), "unite": "nombre", "date": jour,
                             "source": "flux RSS du jour, classement par mots-clés (Python)", "raison_percentile": "non historisé"},
                            None, raison_courbe="décompte du jour, non historisé"))
    for nom, lib, inverse in (("brent", "Réaction du Brent", False), ("indice_or", "Réaction de l'or (proxy)", False),
                              ("FX_JPY", "Réaction USD/JPY", False), ("FX_CHF", "Réaction du CHF (force)", True)):
        pts = _points(historiques, nom)
        if inverse:
            pts = [[d, round(1 / v, 5)] for d, v in pts if v]
        if len(pts) >= 2:
            var = round((pts[-1][1] / pts[-2][1] - 1) * 100, 2)
            cel = _stats(pts, "niveau", ((historiques.get("series") or {}).get(nom) or {}).get("source", "FRED"))
            cel["variation"] = {"valeur": var, "unite": "%", "periode": "dernière séance",
                                "texte": f"{_signe(var)} % sur la dernière séance ({pts[-2][0]} → {pts[-1][0]})"}
        else:
            cel = {"valeur": None, "raison": "série indisponible"}
        tuiles.append(tuile(f"reaction_{nom.lower()}", lib, cel, _fenetre(pts, 30)))
    e["tuiles"] = tuiles
    brent, orr = _points(historiques, "brent"), _points(historiques, "indice_or")
    e["graphiques"][0] = _graphique_serie("Brent et indice or (proxy) rebasés à 100", "base 100",
                                          [("Brent", _fenetre(brent, 366)), ("Or (proxy)", _fenetre(orr, 366))],
                                          "FRED (DCOILBRENTEU, NASDAQQGLDI)", base_100=True)


# ------------------------------------------------------------- engrenage 7
def rsi_serie(dates: list[str], clotures: list[float], periode: int = 14) -> list[list]:
    """RSI de Wilder sur chaque séance à partir de la (periode + 1)-ième clôture."""
    if len(clotures) <= periode:
        return []
    gains = [max(b - a, 0) for a, b in zip(clotures, clotures[1:])]
    pertes = [max(a - b, 0) for a, b in zip(clotures, clotures[1:])]
    mg, mp = sum(gains[:periode]) / periode, sum(pertes[:periode]) / periode
    sortie = []
    for i in range(periode, len(gains) + 1):
        if i > periode:
            mg = (mg * (periode - 1) + gains[i - 1]) / periode
            mp = (mp * (periode - 1) + pertes[i - 1]) / periode
        rsi = 100.0 if mp == 0 else 100 - 100 / (1 + mg / mp)
        sortie.append([str(dates[i])[:10], round(rsi, 1)])
    return sortie


def complements_7(e: dict, technique: dict, flux: dict | None, h5=None) -> None:
    c = {l["devise"]: l.get("cellules") or {} for l in e.get("lignes") or []}
    graphes = (technique or {}).get("graphiques") or {}
    rsi = {d: rsi_serie(g.get("dates") or [], g.get("clotures") or []) for d, g in graphes.items()}
    source_rsi = ("calcul local (Twelve Data, force de la devise) ; RSI recalculé sur les 90 clôtures disponibles : "
                  "amorçage plus court que le RSI du tableau, écart possible d'un à deux points")
    if h5 is not None and h5.disponible:   # RSI sur 1 an depuis l'historique 5 ans (même calcul que le tableau)
        from core import historique_5ans
        limite = (date.today() - timedelta(days=366)).isoformat()
        long = {d: [[x, v] for x, v in historique_5ans.rsi(h5.force(d, technique)) if x >= limite] for d in DEVISES}
        if any(long.values()):
            rsi = {d: v for d, v in long.items() if v}
            source_rsi = "calcul Python : RSI 14 sur 5 ans de cours quotidiens (Fed H.10 prolongée par Twelve Data ; USD = indice dollar large)"
    usd = c.get("USD") or {}
    jour_tech = ((graphes.get("USD") or {}).get("dates") or [None])[-1]
    r_usd = rsi.get("USD", [])
    rsi_cel = usd.get("rsi") or {}
    courbe_rsi = rsi_cel.get("courbe_120j") or r_usd[-31:]
    tuiles = [tuile("rsi_usd", "RSI 14 de l'USD", {"date": jour_tech, "raison_percentile": "historique de prix de 90 séances",
                                                   **rsi_cel, "unite": "rsi",
                                                   "variation": _variation_points(courbe_rsi, 28, "pts", 1)},
                    courbe_rsi, "120 jours" if rsi_cel.get("courbe_120j") else "30 séances"),
              tuile("mm200_usd", "USD : écart à la MM200", {"date": jour_tech, **(usd.get("ecart_mm200") or {})},
                    (usd.get("ecart_mm200") or {}).get("courbe_120j"), "120 jours",
                    raison_courbe="historique quotidien 5 ans indisponible"),
              tuile("vol_usd", "USD : volatilité réalisée 20 j", {"date": jour_tech, **(usd.get("volatilite") or {})},
                    (usd.get("volatilite") or {}).get("courbe_120j"), "120 jours",
                    raison_courbe="historique quotidien 5 ans indisponible")]
    sur = [d for d in DEVISES if ((c.get(d) or {}).get("rsi") or {}).get("valeur") is not None and c[d]["rsi"]["valeur"] >= 70]
    sous = [d for d in DEVISES if ((c.get(d) or {}).get("rsi") or {}).get("valeur") is not None and c[d]["rsi"]["valeur"] <= 30]
    n_rsi = sum(1 for d in DEVISES if ((c.get(d) or {}).get("rsi") or {}).get("valeur") is not None)
    t = tuile("extremes_rsi", "Devises en surachat / survente (RSI)",
              {"valeur": len(sur) + len(sous), "unite": "nombre", "date": date.today().isoformat(),
               "source": f"calcul local (RSI 14 de {n_rsi} devise(s))", "raison_percentile": "non applicable"},
              None, raison_courbe="non historisé",
              lecture=f"surachat (≥ 70) : {', '.join(sur) or 'aucune'} ; survente (≤ 30) : {', '.join(sous) or 'aucune'}")
    t["texte"] = f"{len(sur)} / {len(sous)}"
    if h5 is not None and h5.disponible:   # historisé : décompte quotidien sur le RSI 5 ans des 9 devises
        from core import historique_5ans
        par_jour: dict[str, int] = {}
        for d in DEVISES:
            for jour, v in historique_5ans.rsi(h5.force(d, technique)):
                par_jour[jour] = par_jour.get(jour, 0) + int(v >= 70 or v <= 30)
        serie = sorted(par_jour.items())
        if serie:
            res = historique_5ans.resume(serie, valeur=len(sur) + len(sous))
            t.update({"percentile_5a": res["percentile_5a"], "n_5a": res["n_5a"], "raison_percentile": res["raison_percentile"],
                      "courbe": {"points": res["courbe"], "periode": "120 jours (RSI 5 ans)", "raison": None}})
    tuiles.append(t)
    cot = (flux or {}).get("cot") or {}
    for devise in ("AUD", "EUR", "JPY"):
        x = cot.get(devise) or {}
        cel = (c.get(devise) or {}).get("cot") or {"valeur": None, "raison": "COT indisponible"}
        cel = {**cel, "percentile_5a": None,
               "raison_percentile": f"percentile 52 semaines : {x.get('percentile_52s')}" if x.get("percentile_52s") is not None else None}
        tt = tuile(f"cot_{devise.lower()}", f"COT {devise} (net spéculatif)", cel,
                   [[h[0], h[1]] for h in x.get("historique") or []], "26 semaines")
        tt["percentile_52s"] = x.get("percentile_52s")
        tuiles.append(tt)
    e["tuiles"] = tuiles
    extremes = sorted((d for d in rsi if rsi[d] and d != "USD"), key=lambda d: -abs(rsi[d][-1][1] - 50))[:2]
    e["graphiques"][0] = _graphique_serie("RSI 14 (USD et les 2 devises les plus éloignées de 50)", "RSI",
                                          [(d, rsi[d]) for d in ["USD"] + extremes if rsi.get(d)], source_rsi)


# ------------------------------------------------------------- engrenage 8
UNITES_BALANCE = {"T": 1000.0, "B": 1.0, "M": 0.001}
INVERSEES = {"JPY", "CHF", "CAD", "CNY"}


def balance_en_milliards_usd(devise: str, valeur: str | None, historiques: dict) -> tuple[float | None, str | None]:
    """Balance publiée (ex. « -0.84T », monnaie locale) -> milliards d'USD au dernier cours Fed H.10."""
    if not valeur:
        return None, "non publiée dans le registre"
    m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)\s*([TBM])\s*$", str(valeur))
    if not m:
        return None, f"format non reconnu ({valeur})"
    montant = float(m.group(1)) * UNITES_BALANCE[m.group(2)]
    if devise == "USD":
        return round(montant, 1), None
    if devise == "CNY":
        return None, "monnaie de la publication ForexFactory non précisée (CNY ou USD) : pas de conversion"
    fx = _points(historiques, f"FX_{devise}")
    if not fx:
        return None, "taux de change Fed H.10 indisponible"
    usd_par_unite = 1 / fx[-1][1] if devise in INVERSEES else fx[-1][1]
    return round(montant * usd_par_unite, 1), None


def complements_8(e: dict, historiques: dict, registre: dict) -> None:
    inst = {i["id"]: i["cellule"] for i in e.get("instruments") or []}
    stocks = [[d, round(v / 1000, 1)] for d, v in _points(historiques, "eia_stocks")]
    s = inst.get("eia_stocks") or {}
    tuiles = [tuile("stocks", "Stocks de brut US", {**s, "unite": "M barils"}, stocks[-27:], "26 semaines")]
    ec = {"valeur": s.get("ecart_moyenne_5a"), "unite": "M barils", "date": s.get("date"), "source": s.get("source"),
          "raison": None if s.get("ecart_moyenne_5a") is not None else "moins de 4 années comparables",
          "raison_percentile": "écart à la moyenne saisonnière : pas de percentile"}
    t = tuile("ecart_stocks", "Stocks : écart à la moyenne 5 ans", ec, None, raison_courbe="voir le graphique",
              lecture=f"{_signe(s.get('ecart_moyenne_5a_pct'), 1)} % par rapport à la moyenne des mêmes semaines"
              if s.get("ecart_moyenne_5a_pct") is not None else None)
    if ec["valeur"] is not None:
        t["texte"] = f"{_signe(ec['valeur'], 1)} M"
    tuiles.append(t)
    prod = _points(historiques, "eia_production")
    tuiles.append(tuile("production", "Production de brut US", {**(inst.get("eia_production") or {}), "unite": "milliers b/j"},
                        prod[-27:], "26 semaines"))
    for ident, lib in (("wti", "Pétrole WTI"), ("brent", "Pétrole Brent"), ("indice_or", "Indice or (proxy)")):
        tuiles.append(tuile(ident, lib, inst.get(ident), _fenetre(_points(historiques, ident), 30), lecture=(inst.get(ident) or {}).get("alerte")))
    brent, wti = _points(historiques, "brent"), _points(historiques, "wti")
    par_jour = dict(wti)
    ecart = [[d, round(v - par_jour[d], 2)] for d, v in brent if d in par_jour]
    cel = _stats(ecart, "niveau", "calcul : Brent − WTI (FRED, mêmes séances)") if ecart else {"valeur": None, "raison": "séries indisponibles"}
    if ecart:
        cel.update({"unite": "$", "variation": _variation_points(ecart, 28, "$", 2)})   # un écart varie en $, pas en %
    tuiles.append(tuile("brent_wti", "Écart Brent − WTI ($/baril)", cel, _fenetre(ecart, 30)))
    case = ((registre or {}).get("cases") or {}).get("CAD|balance_commerciale") or {}
    actuel = case.get("actuel") or {}
    v_cad = rm.vers_nombre(str(actuel.get("valeur") or "").rstrip("BMT")) if actuel.get("valeur") else None
    t = tuile("balance_cad", "Balance commerciale du Canada", {"valeur": v_cad, "unite": "Md CAD", "date": actuel.get("date_pub"),
              "source": f"registre macro ({actuel.get('source') or 'ForexFactory'})", "raison": None if v_cad is not None else "non publiée",
              "raison_percentile": "registre tenu depuis 2026 seulement"}, None, raison_courbe="publication mensuelle, historique court",
              lecture=f"consensus : {actuel.get('consensus')}" if actuel.get("consensus") else None)
    if v_cad is not None:
        t["texte"] = f"{_signe(v_cad, 1)} Md CAD"
    tuiles.append(t)
    e["tuiles"] = tuiles
    # Graphique 1 : 52 semaines ; graphique 2 : balances en milliards d'USD (conversion Fed H.10, jamais pour le CNY)
    sem = [p for p in _points(historiques, "eia_stocks")]
    if sem:
        limite = (date.fromisoformat(sem[-1][0]) - timedelta(days=364)).isoformat()
        recents = [p for p in sem if p[0] >= limite]
        moyennes = []
        for d, _ in recents:
            sw, an = date.fromisoformat(d).isocalendar()[1], int(d[:4])
            vals = [v for dd, v in sem if date.fromisoformat(dd).isocalendar()[1] == sw and an - 5 <= int(dd[:4]) < an]
            if len(vals) >= 4:
                moyennes.append([d, round(statistics.mean(vals) / 1000, 1)])
        e["graphiques"][0] = _graphique_serie("Stocks de brut US contre moyenne 5 ans, 52 semaines", "M barils",
                                              [("Stocks", [[d, round(v / 1000, 1)] for d, v in recents]),
                                               ("Moyenne 5 ans (même semaine)", moyennes)], "EIA (WCESTUS1)")
    valeurs, raisons = [], []
    for b in e.get("balances") or []:
        v, r = balance_en_milliards_usd(b["devise"], b.get("valeur"), historiques)
        valeurs.append((b["devise"], v))
        if r:
            raisons.append(f"{b['devise']} : {r}")
    e["graphiques"][1] = _graphique_barres("Balances commerciales, dernière publication (milliards d'USD)", "Md USD", valeurs,
                                           "registre macro (ForexFactory), converti au dernier cours Fed H.10",
                                           "périodes de publication différentes (voir le tableau) ; " + " ; ".join(raisons)
                                           if raisons else "périodes de publication différentes (voir le tableau)")
