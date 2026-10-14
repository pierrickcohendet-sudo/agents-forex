"""Dossiers « économiste » des 8 engrenages — chiffres calculés en Python, chaque jour, sans LLM.

Palier 1 : engrenages 2 (politique monétaire), 3 (données économiques), 5 (interconnexions).
Chaque cellule : valeur, variation 1 et 4 semaines, percentile sur 5 ans (part des valeurs
hebdomadaires des 5 dernières années inférieures ou égales à la valeur actuelle), date, source.
Une valeur ou un percentile impossible à calculer honnêtement vaut None avec sa raison.
Sortie : docs/data/dossiers.json (lu par l'onglet « 8 engrenages » du site).
"""
from __future__ import annotations

import json
import logging
import math
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import archive_quotidienne, complements, consequences, controles_macro, historique_5ans, matrice_impact, registre_macro as rm, tuiles, vue_ensemble

log = logging.getLogger(__name__)

VERSION_SCHEMA = 1
ANNEES = 5
DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
FRAICHEUR_MENSUELLE_JOURS = 280   # série mensuelle plus vieille : percentile non calculé (série arrêtée)


# --------------------------------------------------------------------- calculs
def _serie(historiques: dict, nom: str) -> list[tuple[str, float]]:
    s = (historiques.get("series") or {}).get(nom) or {}
    return [(d, float(v)) for d, v in s.get("points", [])]


def _valeur_a(points: list[tuple[str, float]], jour: str) -> float | None:
    """Dernière valeur connue à la date `jour` (incluse)."""
    v = None
    for d, x in points:
        if d > jour:
            break
        v = x
    return v


def _hebdomadaire(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    semaines: dict = {}
    for d, v in points:
        semaines[date.fromisoformat(d).isocalendar()[:2]] = (d, v)
    return sorted(semaines.values())


def percentile(points: list[tuple[str, float]], valeur: float, fin: str, frequence: str = "quotidien") -> tuple[int | None, int, str | None]:
    """(percentile 0-100, nombre d'observations, raison si non calculé) sur les 5 ans précédant `fin`."""
    debut = (date.fromisoformat(fin) - timedelta(days=int(365.25 * ANNEES))).isoformat()
    base = points if frequence == "mensuel" else _hebdomadaire(points)
    fenetre = [v for d, v in base if debut <= d <= fin]
    minimum = 40 if frequence == "mensuel" else 200
    if len(fenetre) < minimum:
        return None, len(fenetre), f"historique insuffisant ({len(fenetre)} obs. sur 5 ans)"
    return round(100 * sum(1 for v in fenetre if v <= valeur) / len(fenetre)), len(fenetre), None


def stats(points: list[tuple[str, float]], unite: str, source: str, frequence: str = "quotidien",
          valeur: float | None = None, date_valeur: str | None = None) -> dict:
    """Cellule complète. Taux (unite « % » ou « pb ») : variations en points de base ; sinon en %."""
    if not points:
        return absent("série indisponible", source)
    d0, v0 = points[-1]
    if valeur is not None:
        v0, d0 = valeur, date_valeur or d0
    cellule = {"valeur": round(v0, 4), "unite": unite, "date": d0, "source": source, "frequence": frequence, "raison": None}
    if frequence == "mensuel" and (date.today() - date.fromisoformat(points[-1][0])).days > FRAICHEUR_MENSUELLE_JOURS:
        cellule.update({"percentile_5a": None, "n_5a": 0, "var_1s": None, "var_4s": None,
                        "raison_percentile": f"dernière donnée OCDE au {points[-1][0][:7]} : trop ancienne pour un percentile"})
        return cellule
    for cle, jours in (("var_1s", 7), ("var_4s", 28)):
        ref = _valeur_a(points, (date.fromisoformat(points[-1][0]) - timedelta(days=jours)).isoformat())
        if ref is None or frequence == "mensuel":
            cellule[cle] = None
        elif unite in ("%", "pb"):
            cellule[cle] = round((points[-1][1] - ref) * (100 if unite == "%" else 1), 1)   # en pb
        else:
            cellule[cle] = round((points[-1][1] / ref - 1) * 100, 2) if ref else None
    p, n, raison = percentile(points, v0, points[-1][0], frequence)
    cellule.update({"percentile_5a": p, "n_5a": n, "raison_percentile": raison})
    return cellule


def absent(raison: str, source: str | None = None) -> dict:
    return {"valeur": None, "raison": raison, "source": source, "percentile_5a": None, "var_1s": None, "var_4s": None}


def difference(a: list[tuple[str, float]], b: list[tuple[str, float]], facteur: float = 100) -> list[tuple[str, float]]:
    """Série a - b alignée sur les dates de a (dernière valeur connue de b), en pb par défaut."""
    sortie, i, vb = [], 0, None
    for d, va in a:
        while i < len(b) and b[i][0] <= d:
            vb = b[i][1]
            i += 1
        if vb is not None:
            sortie.append((d, round((va - vb) * facteur, 2)))
    return sortie


def glissement_annuel(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Indice mensuel -> glissement sur 12 mois, comparé par MOIS (jamais par position)."""
    par_mois = {d[:7]: v for d, v in points}
    sortie = []
    for d, v in points:
        a, m = int(d[:4]), int(d[5:7])
        base = par_mois.get(f"{a - 1:04d}-{m:02d}")
        if base:
            sortie.append((d, round((v / base - 1) * 100, 2)))
    return sortie


# ------------------------------------------------------------- engrenage 2
def _registre_valeur(case: dict) -> tuple[float | None, str | None]:
    actuel = (case or {}).get("actuel") or {}
    return rm.vers_nombre(str(actuel.get("valeur") or "").replace(" ", "")), actuel.get("date_pub")


def engrenage_2(historiques: dict, registre: dict, config: dict) -> dict:
    cases = registre.get("cases") or {}
    sources_taux = ((config.get("tableau_macro") or {}).get("taux_obligataires") or {}).get("sources") or {}
    us2 = _serie(historiques, "USD_2a")
    colonnes = [("taux_directeur", "Taux directeur", "%"), ("taux_2a", "Taux 2 ans", "%"),
                ("ecart_2a_directeur", "2 ans − directeur", "pb"), ("taux_reel", "Taux réel", "%"),
                ("pente_2_10", "Pente 10 − 2 ans", "pb"), ("ecart_2a_us", "Écart 2 ans vs US", "pb"),
                ("prochaine_reunion", "Prochaine réunion", None)]
    lignes = []
    for devise in DEVISES:
        c: dict = {}
        case = cases.get(f"{devise}|taux_directeur") or {}
        actuel = case.get("actuel") or {}
        # Taux directeur : USD et JPY = taux au jour le jour EFFECTIF officiel et quotidien (Fed DFF,
        # Banque du Japon) ; autres = registre (ForexFactory), percentile parmi une série de référence.
        effectif = {"USD": ("USD_taux_effectif", "FRED (DFF, taux effectif)",
                            f"fourchette cible : borne haute {actuel.get('valeur')} (ForexFactory)"),
                    "JPY": ("JPY_taux_effectif", "Banque du Japon (call rate non garanti au jour le jour)",
                            f"objectif publié « {actuel.get('valeur')} » (ForexFactory) : une borne, pas un taux"),
                    "EUR": ("EUR_taux_depot", "FRED (ECBDFR, taux de la facilité de dépôt de la BCE)",
                            f"ForexFactory publie le taux de refinancement principal ({actuel.get('valeur')}), "
                            "15 pb au-dessus du taux de dépôt qui pilote le marché")}
        if devise in effectif and (devise != "EUR" or _serie(historiques, "EUR_taux_depot")):   # EUR sans ECBDFR : registre (refinancement)
            nom_serie, source_eff, note = effectif[devise]
            serie_eff = _serie(historiques, nom_serie)
            c["taux_directeur"] = stats(serie_eff, "%", source_eff) if serie_eff else \
                absent("série officielle du taux effectif indisponible aujourd'hui", source_eff)
            c["taux_directeur"]["note"] = note if actuel.get("valeur") else None
            directeur, d_dir = (c["taux_directeur"].get("valeur"), c["taux_directeur"].get("date"))
        else:
            directeur, d_dir = _registre_valeur(case)
            if directeur is None:
                c["taux_directeur"] = absent(f"valeur du registre non numérique ({actuel.get('valeur') or 'absente'})",
                                             "registre macro (ForexFactory)")
            else:
                # GBP : SONIA quotidien (Banque d'Angleterre) ; sinon taux au jour le jour OCDE mensuel
                if devise == "GBP" and _serie(historiques, "GBP_taux_effectif"):
                    proxy, freq_proxy, libelle_proxy = _serie(historiques, "GBP_taux_effectif"), "quotidien", "SONIA quotidien (Banque d'Angleterre)"
                else:
                    proxy, freq_proxy, libelle_proxy = _serie(historiques, f"{devise}_taux_jj"), "mensuel", "taux au jour le jour OCDE (mensuel, proxy)"
                cel = stats(proxy, "%", "registre macro (ForexFactory)", freq_proxy, valeur=directeur, date_valeur=d_dir) \
                    if proxy else absent("pas de série longue", "registre macro (ForexFactory)") | {"valeur": directeur, "date": d_dir}
                prec = rm.vers_nombre(str((case.get("precedent") or {}).get("valeur") or "").replace(" ", ""))
                for cle, jours in (("var_1s", 7), ("var_4s", 28)):
                    recent = d_dir and (date.today() - date.fromisoformat(d_dir)).days <= jours
                    cel[cle] = round((directeur - prec) * 100, 1) if (recent and prec is not None) else 0.0
                cel["unite"] = "%"
                if proxy and cel.get("percentile_5a") is not None:
                    cel["note_percentile"] = f"percentile du taux du registre parmi le {libelle_proxy} sur 5 ans"
                lignes_src = cel["source"]
                cel["source"] = lignes_src
                c["taux_directeur"] = cel
        # Taux 2 ans
        s2 = us2 if devise == "USD" else _serie(historiques, f"{devise}_2a")
        spec2 = (sources_taux.get(devise) or {}).get("2a") or {}
        manuel = ((config.get("valeurs_manuelles") or {}).get("rendement_2a") or {}).get(devise) or {}
        if s2:
            c["taux_2a"] = stats(s2, "%", spec2.get("source") or "FRED (DGS2)")
        elif manuel.get("valeur") is not None and manuel.get("date"):
            age = (date.today() - date.fromisoformat(str(manuel["date"]))).days
            c["taux_2a"] = {**absent(None), "valeur": float(manuel["valeur"]), "unite": "%", "date": str(manuel["date"]),
                            "source": f"saisie manuelle (config.yaml) : {manuel.get('source')}",
                            "raison_percentile": "valeur manuelle ponctuelle (pas d'historique)",
                            "alerte": f"relevé ancien ({age} jours)" if age > 10 else None}
        else:
            c["taux_2a"] = absent((spec2.get("absent") or "pas de rendement 2 ans gratuit pour ce pays")
                                  + (" — valeur manuelle prévue dans config.yaml (valeurs_manuelles), non renseignée" if manuel else ""))
        # 2 ans − directeur (ce que le marché intègre de baisses / hausses)
        if s2 and directeur is not None:
            if devise == "USD":
                serie_ecart = difference(s2, _serie(historiques, "USD_taux_effectif"))
                c["ecart_2a_directeur"] = stats(serie_ecart, "pb", "calcul : DGS2 − DFF")
            else:
                c["ecart_2a_directeur"] = {**absent(None), "valeur": round((s2[-1][1] - directeur) * 100, 1), "unite": "pb",
                                           "date": s2[-1][0], "var_1s": c["taux_2a"].get("var_1s"),
                                           "var_4s": c["taux_2a"].get("var_4s"),
                                           "source": "calcul : taux 2 ans − taux directeur du registre",
                                           "raison_percentile": "pas d'historique quotidien du taux directeur"}
            c["ecart_2a_directeur"]["lecture"] = ("le marché intègre des baisses" if c["ecart_2a_directeur"]["valeur"] < -10
                                                  else "le marché intègre des hausses" if c["ecart_2a_directeur"]["valeur"] > 10
                                                  else "pas de mouvement intégré net")
        else:
            c["ecart_2a_directeur"] = absent("taux 2 ans ou taux directeur indisponible")
        # Taux réel = directeur − inflation core a/a. USD : série mensuelle 5 ans (DFF − CPILFESL a/a)
        core, d_core = _registre_valeur(cases.get(f"{devise}|cpi_core"))
        reel_us = taux_reel_us(historiques) if devise == "USD" else []
        if reel_us:
            c["taux_reel"] = stats([(d, v) for d, v in reel_us], "%",
                                   "calcul : DFF (moyenne du mois) − CPI core a/a (FRED CPILFESL)", "mensuel")
            c["taux_reel"].update({"serie_mensuelle": [[d, v] for d, v in reel_us[-13:]],
                                   "note": f"mois de référence de l'inflation : {reel_us[-1][0][:7]}"})
        elif directeur is not None and core is not None:
            c["taux_reel"] = {**absent(None), "valeur": round(directeur - core, 2), "unite": "%", "date": d_core,
                              "source": "calcul : taux directeur − CPI core a/a (registre)",
                              "raison_percentile": "historique de l'inflation core trop court dans le registre"}
        else:
            c["taux_reel"] = absent("inflation core ou taux directeur indisponible")
        # Pente 10 − 2 ans
        s10 = _serie(historiques, "USD_10a" if devise == "USD" else f"{devise}_10a")
        quotidien10 = ((historiques.get("series") or {}).get("USD_10a" if devise == "USD" else f"{devise}_10a") or {}).get("frequence") == "quotidien"
        if s2 and s10 and quotidien10:
            c["pente_2_10"] = stats(difference(s10, s2), "pb", "calcul : 10 ans − 2 ans")
        else:
            c["pente_2_10"] = absent("10 ans quotidien et 2 ans nécessaires")
        # Écart 2 ans vs US
        if devise == "USD":
            c["ecart_2a_us"] = absent("référence (États-Unis)")
        elif s2:
            serie = difference(s2, us2)
            c["ecart_2a_us"] = stats(serie, "pb", "calcul : 2 ans local − 2 ans US (DGS2)")
            limite = (date.fromisoformat(serie[-1][0]) - timedelta(days=366)).isoformat()
            c["ecart_2a_us"]["serie_1an"] = [[d, v] for d, v in serie if d >= limite]
        else:
            c["ecart_2a_us"] = absent("pas de rendement 2 ans pour ce pays")
        prev = case.get("prevision") or {}
        c["prochaine_reunion"] = {"valeur": None, "texte": prev.get("date_pub"), "source": "ForexFactory (calendrier)",
                                  "raison": None if prev.get("date_pub") else "date non publiée"}
        lignes.append({"devise": devise, "cellules": c})
    return {"numero": 2, "titre": "Politique monétaire", "colonnes": [{"id": i, "libelle": l, "unite": u} for i, l, u in colonnes],
            "lignes": lignes,
            "notes": ["USD : taux effectif quotidien de la Fed (DFF) ; ForexFactory publie la borne haute de la fourchette.",
                      "Percentile du taux directeur hors USD : calculé parmi les taux au jour le jour OCDE (mensuels, proxy).",
                      "2 ans − directeur négatif : le marché anticipe des baisses ; positif : des hausses."]}


def taux_reel_us(historiques: dict) -> list[tuple[str, float]]:
    """[(mois, DFF moyen du mois − CPI core a/a du même mois)] sur l'historique disponible (5 ans et plus)."""
    dff = _serie(historiques, "USD_taux_effectif")
    glissement = glissement_annuel(_serie(historiques, "USD_core_indice"))
    par_mois: dict[str, list[float]] = {}
    for d, v in dff:
        par_mois.setdefault(d[:7], []).append(v)
    return [(d, round(statistics.mean(par_mois[d[:7]]) - g, 2)) for d, g in glissement if par_mois.get(d[:7])]


# ------------------------------------------------------------- engrenage 3
def engrenage_3(historiques: dict, registre: dict, config: dict) -> dict:
    cfg_tm = config.get("tableau_macro") or {}
    cases = registre.get("cases") or {}
    indices = controles_macro.indice_surprise(registre, cfg_tm)
    plafond = float((cfg_tm.get("indice_surprise") or {}).get("plafond_surprise", 3))
    limite = (date.today() - timedelta(days=30)).isoformat()
    lignes = []
    for devise in DEVISES:
        c: dict = {}
        ind = indices.get(devise) or {}
        c["indice_surprise"] = ({**absent(None), "valeur": ind["indice"], "unite": "écarts", "date": date.today().isoformat(),
                                 "tendance": ind.get("tendance"), "n": ind.get("n"), "source": "calcul Python (registre macro, 30 j)",
                                 "raison_percentile": "indice calculé depuis 2026 seulement (pas 5 ans d'historique)"}
                                if ind.get("indice") is not None else absent("aucune publication avec consensus sur 30 jours"))
        surprises, publications = [], []
        for indicateur, cfg_ind in (cfg_tm.get("indicateurs") or {}).items():
            if cfg_ind.get("marche"):
                continue
            case = cases.get(f"{devise}|{indicateur}") or {}
            for d, s in controles_macro._surprises(case, cfg_ind, plafond):
                if d >= limite:
                    surprises.append(s)
                    actuel = case.get("actuel") or {}
                    if actuel.get("date_pub") == d:
                        publications.append({"indicateur": cfg_ind.get("libelle", indicateur), "date": d, "surprise": round(s, 2),
                                             "reel": actuel.get("valeur"), "consensus": actuel.get("consensus")})
        c["dispersion"] = ({**absent(None), "valeur": round(statistics.pstdev(surprises), 2), "unite": "écarts",
                            "n": len(surprises), "source": "calcul Python (écart-type des surprises 30 j)",
                            "raison_percentile": "historique trop court"} if len(surprises) >= 3
                           else absent(f"moins de 3 surprises sur 30 jours ({len(surprises)})"))
        top = sorted(publications, key=lambda p: -abs(p["surprise"]))[:3]
        c["publications"] = {"valeur": None, "liste": top, "source": "registre macro (ForexFactory)",
                             "raison": None if top else "aucune publication avec consensus sur 30 jours"}
        # Inflation core et chômage : valeur du registre, tendance 3 mois (historique du registre), percentile 5 ans
        for cle, indicateur, serie_longue in (("inflation_core", "cpi_core", "USD_core_indice" if devise == "USD" else None),
                                              ("chomage", "chomage", f"{devise}_chomage")):
            case = cases.get(f"{devise}|{indicateur}") or {}
            v, d = _registre_valeur(case)
            if v is None:
                c[cle] = absent("non publié ou non numérique dans le registre", "registre macro")
                continue
            cel = {**absent(None), "valeur": v, "unite": "%", "date": d, "source": f"registre macro ({(case.get('actuel') or {}).get('source') or 'ForexFactory'})"}
            anciens = [h for h in case.get("historique", []) if h.get("date_pub") and d and 60 <= (date.fromisoformat(d) - date.fromisoformat(h["date_pub"])).days <= 120]
            v3 = rm.vers_nombre(str(anciens[-1]["valeur"]).replace(" ", "")) if anciens else None
            cel["tendance_3m"] = None if v3 is None else round(v - v3, 2)
            cel["raison_tendance"] = None if v3 is not None else "pas de publication 2 à 4 mois plus tôt dans le registre"
            longue = _serie(historiques, serie_longue) if serie_longue else []
            if serie_longue == "USD_core_indice":
                longue = glissement_annuel(longue)
            if longue:
                p = stats(longue, "%", "", "mensuel")
                if p.get("raison_percentile") or p.get("percentile_5a") is None:
                    cel["raison_percentile"] = p.get("raison_percentile") or "série longue insuffisante"
                else:
                    pct, n, _ = percentile(longue, v, longue[-1][0], "mensuel")
                    cel.update({"percentile_5a": pct, "n_5a": n,
                                "note_percentile": f"parmi {((historiques.get('series') or {}).get(serie_longue) or {}).get('source')}"})
            else:
                cel["raison_percentile"] = "pas de série gratuite à jour sur 5 ans pour ce pays (séries OCDE arrêtées)"
            c[cle] = cel
        lignes.append({"devise": devise, "cellules": c})
    return {"numero": 3, "titre": "Données économiques",
            "colonnes": [{"id": "indice_surprise", "libelle": "Surprise 30 j", "unite": "écarts"},
                         {"id": "dispersion", "libelle": "Dispersion", "unite": "écarts"},
                         {"id": "inflation_core", "libelle": "Inflation core", "unite": "%"},
                         {"id": "chomage", "libelle": "Chômage", "unite": "%"},
                         {"id": "publications", "libelle": "Plus fortes surprises (30 j)", "unite": None}],
            "lignes": lignes,
            "notes": ["Surprise en « écarts habituels » : (réel − consensus) ÷ écart habituel de l'indicateur, chômage inversé.",
                      "Percentile 5 ans : seulement là où une série gratuite à jour existe (US : FRED ; chômage GBP, JPY, CAD, AUD : OCDE)."]}


# ------------------------------------------------------------- engrenage 5
SEUIL_SAUT = {"vix": 30.0}   # variation journalière « atypique » (en %) ; 8 % par défaut
INSTRUMENTS = [("vix", "VIX", "pts"), ("dollar_large", "Indice dollar large (Fed)", "indice"),
               ("indice_or", "Indice or (proxy)", "indice"), ("wti", "Pétrole WTI", "$/baril"),
               ("brent", "Pétrole Brent", "$/baril"), ("sp500", "S&P 500", "indice"),
               ("USD_10a", "Rendement 10 ans US", "%"), ("USD_2a", "Rendement 2 ans US", "%")]


def _rendements(points: list[tuple[str, float]], taux: bool) -> dict[str, float]:
    sortie = {}
    for (d0, v0), (d1, v1) in zip(points, points[1:]):
        if taux:
            sortie[d1] = v1 - v0
        elif v0:
            sortie[d1] = math.log(v1 / v0)
    return sortie


def _correlation(a: list[float], b: list[float]) -> float | None:
    if len(a) < 15:
        return None
    try:
        return round(statistics.correlation(a, b), 2)
    except statistics.StatisticsError:
        return None


def engrenage_5(historiques: dict, technique: dict) -> dict:
    lignes = []
    from agents.agent_engrenages import saut_atypique
    for nom, libelle, unite in INSTRUMENTS:
        s = (historiques.get("series") or {}).get(nom) or {}
        points = _serie(historiques, nom)
        cel = stats(points, unite if unite == "%" else "niveau", s.get("source") or nom) if points else absent("série indisponible")
        recents = [p for p in points if p[0] >= (date.today() - timedelta(days=30)).isoformat()]
        saut = saut_atypique({"dates": [d for d, _ in recents], "valeurs": [v for _, v in recents]},
                             SEUIL_SAUT.get(nom, 8.0)) if unite != "%" else None
        if saut:
            cel["alerte"] = f"série heurtée : {saut} en une séance (chiffres officiels)"
        lignes.append({"id": nom, "libelle": libelle, "unite_affichage": unite, "cellule": cel})
    # Corrélations 30 séances : devises (force) + marchés
    series_c: dict[str, dict[str, float]] = {}
    for devise, g in ((technique or {}).get("graphiques") or {}).items():
        series_c[devise] = _rendements(list(zip(g.get("dates", []), g.get("clotures", []))), False)
    for nom, libelle, unite in INSTRUMENTS[:7]:
        series_c[libelle] = _rendements([p for p in _serie(historiques, nom)
                                         if p[0] >= (date.today() - timedelta(days=140)).isoformat()], unite == "%")
    noms = [n for n in series_c if series_c[n]]
    matrice, matrice_prec, changements, fins = {}, {}, [], []
    for i, a in enumerate(noms):
        for b in noms[i + 1:]:
            communes = sorted(set(series_c[a]) & set(series_c[b]))
            fen, prec = communes[-30:], communes[-60:-30]
            if fen:
                fins.append(fen[-1])
            r = _correlation([series_c[a][d] for d in fen], [series_c[b][d] for d in fen])
            r0 = _correlation([series_c[a][d] for d in prec], [series_c[b][d] for d in prec])
            matrice.setdefault(a, {})[b] = r
            matrice.setdefault(b, {})[a] = r
            matrice_prec.setdefault(a, {})[b] = r0
            matrice_prec.setdefault(b, {})[a] = r0
            if r is not None and r0 is not None and abs(r) >= 0.3 and abs(r0) >= 0.3 and (r > 0) != (r0 > 0):
                changements.append({"paire": [a, b], "avant": r0, "maintenant": r})
    vix = next((l["cellule"] for l in lignes if l["id"] == "vix"), {})
    regime = None
    if vix.get("valeur") is not None and vix.get("percentile_5a") is not None:
        regime = ("tension (VIX au-dessus du 80e percentile 5 ans)" if vix["percentile_5a"] >= 80 else
                  "calme (VIX sous le 20e percentile 5 ans)" if vix["percentile_5a"] <= 20 else "intermédiaire")
    return {"numero": 5, "titre": "Interconnexions de marchés", "instruments": lignes,
            "correlations": {"noms": noms, "matrice": matrice, "matrice_precedente": matrice_prec, "seances": 30,
                             "derniere_seance": max(fins) if fins else None, "changements_de_signe": changements,
                             "source": "calcul Python : rendements quotidiens (log) des devises (force, Twelve Data) et des séries FRED ; "
                                       "variations en points pour les taux"},
            "regime_volatilite": regime,
            "notes": ["Indice or (proxy) : NASDAQ QGLDI, pas le cours spot (FRED n'a plus de cours de l'or gratuit).",
                      "Changement de signe : corrélation ≥ 0,3 en valeur absolue sur les deux fenêtres de 30 séances, de signe opposé."]}




# ----------------------------------------------------------------- graphiques
def _90j(points: list[tuple[str, float]], jours: int = 90) -> list[list]:
    if not points:
        return []
    limite = (date.fromisoformat(points[-1][0]) - timedelta(days=jours)).isoformat()
    return [[d, v] for d, v in points if d >= limite]


def graphique_serie(titre: str, unite: str, lignes: list[tuple[str, list]], source: str, base_100: bool = False) -> dict:
    """Série temporelle multi-courbes (jusqu'à 1 an : le site propose 30 j / 90 j / 1 an). base_100 : valeurs
    brutes, le site rebase chaque courbe à 100 au début de la période affichée."""
    sortie = [{"nom": nom, "points": points} for nom, points in lignes if len(points) >= 2]
    return {"type": "serie", "titre": titre, "unite": unite, "courbes": sortie, "source": source, "base_100": base_100,
            "raison": None if sortie else "séries indisponibles"}


def graphique_barres(titre: str, unite: str, valeurs: list[tuple[str, float | None]], source: str, note: str | None = None) -> dict:
    barres = [{"nom": n, "valeur": v} for n, v in valeurs if v is not None]
    return {"type": "barres", "titre": titre, "unite": unite, "barres": barres, "source": source, "note": note,
            "absentes": [n for n, v in valeurs if v is None], "raison": None if barres else "valeurs indisponibles"}


def graphiques_2(e: dict, historiques: dict) -> list[dict]:
    lignes = {l["devise"]: l["cellules"] for l in e["lignes"]}
    courbes = [(d, lignes[d]["ecart_2a_us"].get("serie_1an") or []) for d in DEVISES if d != "USD"]
    return [graphique_serie("Écart de taux 2 ans face aux États-Unis", "pb", courbes,
                            "calcul : 2 ans local − 2 ans US (DGS2)"),
            graphique_barres("Taux directeur par devise", "%",
                             [(d, lignes[d]["taux_directeur"].get("valeur")) for d in DEVISES],
                             "registre macro ; USD et JPY : taux effectifs officiels")]


def graphiques_3(registre: dict, config: dict, e: dict) -> list[dict]:
    cfg_tm = config.get("tableau_macro") or {}
    aujourdhui = date.today()
    historique: dict[str, list] = {d: [] for d in DEVISES}
    for k in range(13, -1, -1):   # un point par semaine sur ~90 jours
        jour = aujourdhui - timedelta(days=7 * k)
        for devise, v in controles_macro.indice_surprise(registre, cfg_tm, jour).items():
            if devise in historique and v.get("indice") is not None:
                historique[devise].append([jour.isoformat(), v["indice"]])
    lignes = {l["devise"]: l["cellules"] for l in e["lignes"]}
    actuels = {d: lignes[d]["indice_surprise"].get("valeur") for d in DEVISES}
    choix = ["USD"] + [d for d, _ in sorted(((d, abs(v)) for d, v in actuels.items() if v is not None and d != "USD"),
                                             key=lambda x: -x[1])[:3]]
    return [graphique_serie("Indice de surprise 30 j glissant (USD + 3 devises les plus surprenantes)", "écarts",
                            [(d, historique[d]) for d in choix], "calcul Python (registre macro)"),
            graphique_barres("Indice de surprise 30 j par devise", "écarts", [(d, actuels[d]) for d in DEVISES],
                             "calcul Python (registre macro)")]


def graphiques_5(e: dict, historiques: dict) -> list[dict]:
    courbes = [(lib, _90j(_serie(historiques, nom), 366)) for nom, lib in
               (("dollar_large", "Indice dollar large"), ("indice_or", "Indice or (proxy)"), ("wti", "WTI"), ("sp500", "S&P 500"))]
    matrice = (e.get("correlations") or {}).get("matrice") or {}
    c5 = (historiques.get("correlations_5a") or {}).get("paires") or {}
    valeurs = [(d, (c5.get(f"{d}|S&P 500") or {}).get("valeur")) for d in DEVISES] if c5 else \
              [(d, (matrice.get(d) or {}).get("S&P 500")) for d in DEVISES]
    return [graphique_serie("Marchés rebasés à 100", "base 100", courbes, "FRED", base_100=True),
            graphique_barres("Corrélation 30 séances de chaque devise avec le S&P 500", "corrélation", valeurs,
                             (historiques.get("correlations_5a") or {}).get("source") if c5 else "calcul Python (rendements quotidiens)",
                             "positif : la devise monte avec les actions (devise « risque »)")]


# ------------------------------------------------------------- engrenage 1
def engrenage_1(rapport: dict | None, dossier_rapports: Path | None, dossiers_calcules: dict) -> dict:
    if not rapport:
        return {"numero": 1, "titre": "Thème macro", "indisponible": "rapport du jour pas encore produit (thème calculé après l'analyse)"}
    sg = rapport.get("synthese_globale") or {}
    scores = {d["devise"]: d.get("score_confluence") for d in rapport.get("devises", [])}
    eng = (sg.get("engrenages") or {}).get("engrenages") or []
    theme = next((x for x in eng if x.get("numero") == 1), {})
    ref = (theme.get("direction") or {}).get("calculee") or {}
    accords = desaccords = 0
    for x in eng:
        if x.get("numero") in (1, 4, 6, 8):
            continue
        calc = (x.get("direction") or {}).get("calculee") or {}
        for cle, oppose in (("dollar", {"haussier": "baissier", "baissier": "haussier"}),
                            ("risque", {"risk_on": "risk_off", "risk_off": "risk_on"})):
            if ref.get(cle) in oppose:
                accords += int(calc.get(cle) == ref.get(cle))
                desaccords += int(calc.get(cle) == oppose[ref[cle]])
    coh = vue_ensemble.coherence({x["numero"]: x for x in eng if x.get("numero")}) if eng else None
    indices = [l["cellules"]["indice_surprise"]["valeur"] for l in (dossiers_calcules.get("3") or {}).get("lignes", [])
               if l["cellules"]["indice_surprise"].get("valeur") is not None]
    # Évolution sur 4 semaines : rapports archivés (un par semaine)
    evolution = []
    if dossier_rapports:
        fichiers = sorted(Path(dossier_rapports).glob("????-??-??.json"))
        for k in range(4, 0, -1):
            cible = (date.today() - timedelta(days=7 * k)).isoformat()
            f = next((x for x in reversed(fichiers) if x.stem <= cible), None)
            if f:
                try:
                    r = json.loads(f.read_text(encoding="utf-8"))
                    sc = {d["devise"]: d.get("score_confluence") for d in r.get("devises", [])}
                    evolution.append({"date": f.stem, "biais": (r.get("synthese_globale") or {}).get("biais_macro_global"),
                                      "score_usd": sc.get("USD"), "ecart": _ecart_regime(sc)})
                except (OSError, ValueError):
                    continue
    evolution.append({"date": (rapport.get("meta") or {}).get("date_rapport"), "biais": sg.get("biais_macro_global"),
                      "score_usd": scores.get("USD"), "ecart": _ecart_regime(scores)})
    vues, uniques = set(), []
    for x in evolution:   # un rapport manquant ferait apparaître deux fois le même fichier
        if x["date"] not in vues:
            vues.add(x["date"])
            uniques.append(x)
    evolution = uniques
    lignes = [
        {"libelle": "Régime de risque (biais calculé)", "texte": {"risk_on": "Risk On", "risk_off": "Risk Off", "neutre": "Neutre"}.get(sg.get("biais_macro_global"), "n/d"),
         "detail": f"écart de score risque − refuge : {_ecart_regime(scores)} pts", "source": "calcul Python (scores de confluence)"},
        {"libelle": "Cohérence des engrenages", "texte": coh["libelle"] if coh else "n/d",
         "detail": "règle unique de la page (voir « Qui suit le thème ? »)" if coh else "",
         "source": "règles Python des 8 engrenages", "raison": None if coh else "synthèse 8 engrenages absente de ce rapport"},
        {"libelle": "Indice de surprise global (moyenne 9 devises)", "texte": f"{statistics.mean(indices):+.2f}".replace(".", ",") if indices else "n/d",
         "detail": f"{len(indices)} devise(s) avec un indice", "source": "calcul Python (registre macro, 30 j)"},
        {"libelle": "Score de confluence USD", "texte": str(scores.get("USD")) if scores.get("USD") is not None else "n/d",
         "detail": "0-100, calcul Python", "source": "rapport du jour"},
    ]
    graphes = [graphique_serie("Écart de score risque − refuge, rapports des 4 dernières semaines", "pts",
                               [("Écart risque − refuge", [[x["date"], x["ecart"]] for x in evolution if x["ecart"] is not None])],
                               "rapports archivés (data/rapports)"),
               graphique_barres("Scores de confluence du jour", "0-100", [(d, scores.get(d)) for d in DEVISES], "calcul Python")]
    return {"numero": 1, "titre": "Thème macro", "indicateurs": lignes, "evolution": evolution, "graphiques": graphes,
            "notes": ["Le thème découle des 7 autres engrenages ; la cohérence compte les directions calculées en Python qui vont dans son sens."]}


def _ecart_regime(scores: dict) -> float | None:
    risque = [scores[d] for d in ("AUD", "NZD", "CAD") if scores.get(d) is not None]
    refuge = [scores[d] for d in ("JPY", "CHF", "USD") if scores.get(d) is not None]
    return round(statistics.mean(risque) - statistics.mean(refuge), 1) if risque and refuge else None


# ------------------------------------------------------------- engrenage 4
MOTS_BUDGET = ("budget", "deficit", "déficit", "debt", "dette", "fiscal", "austerity", "austérité", "stimulus", "relance",
               "bond auction", "adjudication", "treasury issuance", "spending bill", "shutdown", "debt ceiling", "tax cut", "gilt", "btp")


def _annuel(points: list[tuple[str, float]], source: str) -> dict:
    if not points:
        return absent("pas de donnée FMI/OCDE pour ce pays", source)
    d, v = points[-1]
    prec = points[-2][1] if len(points) > 1 else None
    return {**absent(None), "valeur": round(v, 1), "unite": "% PIB", "date": d[:4], "source": source,
            "variation_an": None if prec is None else round(v - prec, 1),
            "raison_percentile": "série annuelle : pas de percentile hebdomadaire",
            "alerte": f"dernière année disponible : {d[:4]}" if int(d[:4]) < date.today().year - 1 else None}


def engrenage_4(historiques: dict, news: dict | None) -> dict:
    series = historiques.get("series") or {}
    lignes = []
    for devise in DEVISES:
        c: dict = {}
        dette, solde = f"{devise}_dette_pib", f"{devise}_solde_pib"
        c["dette_pib"] = _annuel(_serie(historiques, dette), (series.get(dette) or {}).get("source", "FMI via FRED"))
        if devise == "USD" and _serie(historiques, dette):
            pts = _serie(historiques, dette)
            c["dette_pib"].update({"date": pts[-1][0][:7], "unite": "% PIB", "note": "dette fédérale, trimestrielle"})
        c["solde_pib"] = _annuel(_serie(historiques, solde), (series.get(solde) or {}).get("source", "FMI via FRED"))
        s10 = _serie(historiques, f"{devise}_10a")
        f10 = (series.get(f"{devise}_10a") or {}).get("frequence", "quotidien")
        c["taux_10a"] = stats(s10, "%", (series.get(f"{devise}_10a") or {}).get("source", ""), "mensuel" if f10 == "mensuel" else "quotidien") \
            if s10 else absent("pas de rendement 10 ans gratuit")
        if devise == "USD":
            tp = _serie(historiques, "USD_prime_terme")
            c["prime_terme"] = stats(tp, "%", (series.get("USD_prime_terme") or {}).get("source", "")) if tp else absent("série indisponible")
        else:
            c["prime_terme"] = absent("prime de terme publiée gratuitement pour les États-Unis seulement (FRED)")
        lignes.append({"devise": devise, "cellules": c})
    actus = []
    for a in (news or {}).get("articles", []) or []:
        titre = (a.get("titre") or "")
        if any(m in titre.lower() for m in MOTS_BUDGET):
            actus.append({"titre": titre, "source": a.get("source"), "date": (a.get("date") or "")[:10], "lien": a.get("lien")})
    graphes = [graphique_serie("Rendements 10 ans", "%",
                               [(d, _90j(_serie(historiques, f"{d}_10a"), 366)) for d in ("USD", "EUR", "GBP", "JPY", "CAD")
                                if (series.get(f"{d}_10a") or {}).get("frequence") == "quotidien"], "FRED, Bundesbank, BoE, MoF Japon, BoC"),
               graphique_barres("Dette publique / PIB (dernière année FMI)", "% PIB",
                                [(d, (next(l for l in lignes if l["devise"] == d)["cellules"]["dette_pib"]).get("valeur")) for d in DEVISES],
                                "FMI / FRED", "années différentes selon les pays (voir le tableau)")]
    return {"numero": 4, "titre": "Politique fiscale",
            "colonnes": [{"id": "dette_pib", "libelle": "Dette / PIB", "unite": "% PIB"},
                         {"id": "solde_pib", "libelle": "Solde / PIB", "unite": "% PIB"},
                         {"id": "taux_10a", "libelle": "Rendement 10 ans", "unite": "%"},
                         {"id": "prime_terme", "libelle": "Prime de terme 10 ans", "unite": "%"}],
            "lignes": lignes, "actualites": actus[:10], "graphiques": graphes,
            "actualites_maj": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "actualites_nb_titres_lus": len((news or {}).get("articles", []) or []),
            "notes": ["Dette et solde publics : FMI (annuel, avec 1 à 3 ans de retard) ; EUR = Allemagne. Pas de série gratuite pour CHF et NZD.",
                      "Prime de terme : modèle Kim-Wright (Fed, via FRED), États-Unis seulement.",
                      "Actualités budgétaires : titres des flux RSS contenant un mot-clé budgétaire (source et date)."]}


# ------------------------------------------------------------- engrenage 6
CANAUX = {
    "energie": (("oil", "crude", "opec", "pipeline", "refinery", "lng", "gas", "pétrole", "houthi", "hormuz", "tanker", "riyadh", "saudi"),
                "choc d'offre énergétique : prix du pétrole et du gaz, inflation importée",
                ["CAD", "NZD", "AUD", "JPY", "EUR"]),
    "commerce": (("tariff", "trade war", "trade deal", "export", "import ban", "droits de douane", "customs"),
                 "tensions commerciales : volumes d'échanges, chaînes d'approvisionnement",
                 ["CNY", "AUD", "CAD", "EUR"]),
    "sanctions": (("sanction", "embargo", "blacklist", "asset freeze"),
                  "sanctions : flux financiers et commerce bloqués", ["USD", "EUR", "CNY"]),
    "refuge": (("war", "attack", "missile", "strike", "invasion", "military", "troops", "guerre", "attaque", "conflict", "killed"),
               "conflit armé : fuite vers les valeurs refuges", ["USD", "JPY", "CHF"]),
    "budget": (("election", "élection", "government collapse", "coalition", "impeachment", "budget crisis", "shutdown"),
               "politique intérieure : prime de risque sur la dette et la devise", ["EUR", "GBP", "USD", "JPY"]),
}


def engrenage_6(news: dict | None) -> dict:
    evenements, comptes = [], {k: 0 for k in CANAUX}
    for a in (news or {}).get("articles", []) or []:
        titre = a.get("titre") or ""
        bas = titre.lower()
        canaux = [k for k, (mots, _, _) in CANAUX.items() if any(m in bas for m in mots)]
        if not canaux:
            continue   # pas de mécanisme identifiable : pas retenu
        principal = canaux[0]
        for k in canaux:
            comptes[k] += 1
        evenements.append({"titre": titre, "canal": principal, "canaux": canaux, "mecanisme": CANAUX[principal][1],
                           "devises": CANAUX[principal][2], "source": a.get("source"), "date": (a.get("date") or "")[:10],
                           "lien": a.get("lien")})
    libelles = {"energie": "Énergie", "commerce": "Commerce", "sanctions": "Sanctions", "refuge": "Refuge (conflits)", "budget": "Politique intérieure"}
    return {"numero": 6, "titre": "Géopolitique", "evenements": evenements[:15],
            "graphiques": [{"type": "serie", "titre": "Série temporelle", "raison": "pas de série chiffrée gratuite pour la géopolitique"},
                           graphique_barres("Titres du jour par canal de transmission", "titres",
                                            [(libelles[k], v) for k, v in comptes.items()], "flux RSS (classement par mots-clés)")],
            "notes": ["Classement par mots-clés en Python : un titre sans canal identifiable (énergie, commerce, sanctions, refuge, politique intérieure) n'est pas retenu.",
                      "Le mécanisme et les devises touchées sont ceux du canal, pas une analyse du titre : à lire comme une piste, pas un fait."]}


# ------------------------------------------------------------- engrenage 7
def engrenage_7(technique: dict, flux: dict | None) -> dict:
    cot = (flux or {}).get("cot") or {}
    techs = (technique or {}).get("devises") or {}
    graphes_series = (technique or {}).get("graphiques") or {}
    lignes = []
    for devise in DEVISES:
        t, c = techs.get(devise) or {}, {}
        if t.get("dernier") is not None:
            sens = (t.get("tendance_fond") or {}).get("sens")
            c["tendance"] = {**absent(None), "valeur": None, "texte": sens or "n/d", "source": "calcul local (Twelve Data, weekly Dow)"}
            rsi = t.get("rsi")
            c["rsi"] = {**absent(None), "valeur": rsi, "unite": "", "source": "calcul local (RSI 14, daily)",
                        "signal": "surachat" if rsi is not None and rsi >= 70 else "survente" if rsi is not None and rsi <= 30 else None,
                        "raison_percentile": "non calculé"}
            for cle, mm in (("ecart_mm100", "mm100"), ("ecart_mm200", "mm200")):
                # Les séries techniques sont déjà en FORCE de la devise (paires inversées converties à la collecte).
                ecart = None if not t.get(mm) else (t["dernier"] / t[mm] - 1) * 100
                c[cle] = ({**absent(None), "valeur": round(ecart, 2), "unite": "%", "source": f"calcul local ({mm.upper()}, force de la devise)",
                           "raison_percentile": "non calculé"} if ecart is not None else absent("moyenne indisponible (historique de prix trop court)"))
            g = graphes_series.get(devise) or {}
            closes = g.get("clotures") or []
            if len(closes) >= 45:
                rend = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a and b]
                vols = [statistics.pstdev(rend[i - 20:i]) * math.sqrt(252) * 100 for i in range(20, len(rend) + 1)]
                actuel = vols[-1]
                c["volatilite"] = {**absent(None), "valeur": round(actuel, 1), "unite": "% annualisé",
                                   "percentile_90j": round(100 * sum(1 for v in vols if v <= actuel) / len(vols)),
                                   "source": "calcul local : volatilité réalisée 20 séances",
                                   "raison_percentile": "percentile sur 90 jours seulement (historique de prix Twelve Data limité à 90 séances)"}
            else:
                c["volatilite"] = absent("historique de prix insuffisant")
            zones = t.get("zones_consolidation") or []
            c["niveau_cle"] = ({**absent(None), "texte": f"{zones[0]['type']} {zones[0]['niveau']} ({zones[0]['distance_pct']:+.2f} %)",
                                "source": "calcul local (zones de consolidation)"} if zones else absent("aucune zone détectée"))
        else:
            for cle in ("tendance", "rsi", "ecart_mm100", "ecart_mm200", "volatilite", "niveau_cle"):
                c[cle] = absent("données techniques indisponibles aujourd'hui")
        x = cot.get(devise)
        c["cot"] = ({**absent(None), "valeur": x["net"], "unite": "contrats", "date": x["date"], "var_1s": x.get("variation_semaine"),
                     "percentile_52s": x.get("percentile_52s"), "extreme": x.get("extreme"),
                     "source": "CFTC (COT legacy, positions nettes non commerciales)"}
                    if x else absent("non couvert par la CFTC" if devise == "CNY" else "COT indisponible aujourd'hui"))
        lignes.append({"devise": devise, "cellules": c})
    courbes = [(d, [[h[0], round(h[1] / 1000, 1)] for h in (cot.get(d) or {}).get("historique", [])]) for d in ("EUR", "JPY", "GBP", "AUD")]
    graphes = [graphique_serie("Positions nettes des spéculateurs (COT), 26 semaines", "milliers de contrats", courbes, "CFTC"),
               graphique_barres("Percentile 52 semaines du positionnement net (COT)", "percentile",
                                [(d, (cot.get(d) or {}).get("percentile_52s")) for d in DEVISES], "CFTC",
                                "≥ 90 ou ≤ 10 : positionnement extrême")]
    return {"numero": 7, "titre": "Price action et flux",
            "colonnes": [{"id": "tendance", "libelle": "Tendance", "unite": None}, {"id": "rsi", "libelle": "RSI", "unite": ""},
                         {"id": "ecart_mm100", "libelle": "Écart MM100", "unite": "%"}, {"id": "ecart_mm200", "libelle": "Écart MM200", "unite": "%"},
                         {"id": "volatilite", "libelle": "Volatilité 20 j", "unite": "%"}, {"id": "niveau_cle", "libelle": "Niveau clé", "unite": None},
                         {"id": "cot", "libelle": "COT net", "unite": "contrats"}],
            "lignes": lignes, "graphiques": graphes,
            "notes": ["Force de la devise (paires inversées pour USD/JPY, USD/CHF, USD/CAD, USD/CNH) ; USD = indice synthétique.",
                      "COT : positions des spéculateurs (non commerciaux) ; percentile sur 52 semaines, extrême ≥ 90 ou ≤ 10.",
                      "Volatilité : percentile sur 90 jours seulement (historique de prix gratuit limité)."]}


# ------------------------------------------------------------- engrenage 8
def engrenage_8(historiques: dict, registre: dict) -> dict:
    series = historiques.get("series") or {}
    stocks = _serie(historiques, "eia_stocks")
    instruments = []
    if stocks:
        d0, v0 = stocks[-1]
        semaine = date.fromisoformat(d0).isocalendar()[1]
        meme_semaine = [v for d, v in stocks if date.fromisoformat(d).isocalendar()[1] == semaine
                        and int(d[:4]) < int(d0[:4]) and int(d[:4]) >= int(d0[:4]) - 5]
        moy = statistics.mean(meme_semaine) if len(meme_semaine) >= 4 else None
        cel = stats(stocks, "niveau", (series.get("eia_stocks") or {}).get("source", "EIA"))
        cel.update({"valeur": round(v0 / 1000, 1), "unite": "M barils",
                    "ecart_moyenne_5a": None if moy is None else round((v0 - moy) / 1000, 1),
                    "ecart_moyenne_5a_pct": None if moy is None else round((v0 / moy - 1) * 100, 1),
                    "moyenne_5a": None if moy is None else round(moy / 1000, 1),
                    "note": f"moyenne des {len(meme_semaine)} mêmes semaines des 5 années précédentes" if moy else "moins de 4 années comparables"})
        instruments.append({"id": "eia_stocks", "libelle": "Stocks de brut US (hors réserve stratégique)", "cellule": cel})
    else:
        instruments.append({"id": "eia_stocks", "libelle": "Stocks de brut US", "cellule": absent("EIA indisponible aujourd'hui")})
    prod = _serie(historiques, "eia_production")
    instruments.append({"id": "eia_production", "libelle": "Production de brut US",
                        "cellule": (stats(prod, "niveau", (series.get("eia_production") or {}).get("source", "EIA")) | {"unite": "milliers b/j"})
                        if prod else absent("EIA indisponible aujourd'hui")})
    for nom, lib in (("wti", "Pétrole WTI"), ("brent", "Pétrole Brent"), ("indice_or", "Indice or (proxy)")):
        pts = _serie(historiques, nom)
        cel = stats(pts, "niveau", (series.get(nom) or {}).get("source", "FRED")) if pts else absent("série indisponible")
        from agents.agent_engrenages import saut_atypique
        recents = [p for p in pts if p[0] >= (date.today() - timedelta(days=30)).isoformat()]
        saut = saut_atypique({"dates": [d for d, _ in recents], "valeurs": [v for _, v in recents]})
        if saut:
            cel["alerte"] = f"série heurtée : {saut} en une séance (chiffres officiels)"
        instruments.append({"id": nom, "libelle": lib, "cellule": cel})
    balances = []
    for devise in DEVISES:
        actuel = ((registre.get("cases") or {}).get(f"{devise}|balance_commerciale") or {}).get("actuel") or {}
        balances.append({"devise": devise, "valeur": actuel.get("valeur"), "consensus": actuel.get("consensus"),
                         "date": actuel.get("date_pub") or actuel.get("periode"), "source": actuel.get("source") or "ForexFactory",
                         "raison": None if actuel.get("valeur") else "non publiée dans le registre"})
    graphe_stocks = []
    if stocks:
        recents = [p for p in stocks if p[0] >= (date.fromisoformat(stocks[-1][0]) - timedelta(days=182)).isoformat()]
        moyennes = []
        for d, _ in recents:
            sem, an = date.fromisoformat(d).isocalendar()[1], int(d[:4])
            vals = [v for dd, v in stocks if date.fromisoformat(dd).isocalendar()[1] == sem and an - 5 <= int(dd[:4]) < an]
            if len(vals) >= 4:
                moyennes.append([d, round(statistics.mean(vals) / 1000, 1)])
        graphe_stocks = [("Stocks", [[d, round(v / 1000, 1)] for d, v in recents]), ("Moyenne 5 ans (même semaine)", moyennes)]
    graphes = [graphique_serie("Stocks de brut US contre moyenne 5 ans, 26 semaines", "M barils", graphe_stocks, "EIA"),
               graphique_barres("Variation sur 4 semaines", "%",
                                [(i["libelle"], i["cellule"].get("var_4s")) for i in instruments if i["id"] != "eia_stocks"],
                                "EIA, FRED")]
    return {"numero": 8, "titre": "Offre et demande", "instruments": instruments, "balances": balances, "graphiques": graphes,
            "termes_echange": absent("pas de série gratuite des termes de l'échange (AUD, CAD, NZD) accessible automatiquement"),
            "notes": ["Stocks EIA : écart à la moyenne des 5 années précédentes pour la même semaine.",
                      "Balances commerciales : monnaies et unités propres à chaque pays (non comparables directement).",
                      "Indice or (proxy) : NASDAQ QGLDI, pas le cours spot."]}


# ------------------------------------------------------------------- sortie
def appliquer_historique_5ans(engrenages: dict, h5, technique: dict | None) -> None:
    """Dossiers 5 et 7 : matrice de corrélations et indicateurs techniques recalculés sur l'historique quotidien
    5 ans (module partagé core/historique_5ans.py), avec percentile 5 ans. Sans fichier : rien ne change."""
    if h5 is None or not h5.disponible:
        return
    e5 = engrenages.get("5")
    if e5 and not e5.get("indisponible"):
        m = historique_5ans.matrice(h5, technique)
        if m:
            e5["correlations"] = m
    e7 = engrenages.get("7")
    if e7 and not e7.get("indisponible"):
        for ligne in e7.get("lignes") or []:
            ind = historique_5ans.indicateurs_techniques(h5, ligne["devise"], technique)
            c = ligne["cellules"]
            source = historique_5ans.SOURCE_INDICATEURS
            for cle, unite, libelle in (("rsi", "", "RSI 14"), ("ecart_mm100", "%", "écart à la MM100"),
                                        ("ecart_mm200", "%", "écart à la MM200"), ("volatilite", "% annualisé", "volatilité 20 séances")):
                x = ind.get(cle) or {}
                if x.get("valeur") is None:
                    continue   # sans série 5 ans : la cellule Twelve Data (90 séances) reste, avec sa raison
                cel = {**absent(None), "valeur": x["valeur"], "unite": unite, "date": x["date"],
                       "explication_source": historique_5ans.EXPLICATION_RACCORD,
                       "percentile_5a": x["percentile_5a"], "n_5a": x["n_5a"], "raison_percentile": x["raison_percentile"],
                       "courbe_120j": x["courbe"], "source": f"calcul Python ({libelle}) : {source}"}
                if cle == "rsi":
                    cel["signal"] = "surachat" if x["valeur"] >= 70 else "survente" if x["valeur"] <= 30 else None
                c[cle] = cel
        e7.setdefault("notes", []).append("RSI, écarts aux moyennes mobiles et volatilité : série unique 5 ans, mêmes valeurs que "
                                          "l'onglet Devises. " + historique_5ans.EXPLICATION_RACCORD)


def construire(historiques: dict, registre: dict, technique: dict, config: dict, rapport: dict | None = None,
               flux: dict | None = None, news: dict | None = None, dossier_rapports: str | Path | None = None,
               h5=None) -> dict:
    if h5 is not None and h5.disponible:   # corrélations 5 ans calculées par le module partagé
        try:
            historiques = {**historiques, "correlations_5a": historique_5ans.correlations(h5, technique)}
        except Exception:  # noqa: BLE001
            log.exception("Corrélations 5 ans en échec")
    sortie = {"version_schema": VERSION_SCHEMA, "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "debut_historique": historiques.get("debut"), "erreurs_collecte": historiques.get("erreurs", []),
              "engrenages": {}}
    etapes = [("2", lambda: engrenage_2(historiques, registre, config), lambda e: graphiques_2(e, historiques)),
              ("3", lambda: engrenage_3(historiques, registre, config), lambda e: graphiques_3(registre, config, e)),
              ("4", lambda: engrenage_4(historiques, news), None),
              ("5", lambda: engrenage_5(historiques, technique), lambda e: graphiques_5(e, historiques)),
              ("6", lambda: engrenage_6(news), None),
              ("7", lambda: engrenage_7(technique, flux), None),
              ("8", lambda: engrenage_8(historiques, registre), None)]
    for numero, fonction, graphes in etapes:
        try:
            e = fonction()
            if graphes:
                try:
                    e["graphiques"] = graphes(e)
                except Exception as exc:  # noqa: BLE001 — un graphique en échec n'efface pas le tableau
                    log.exception("Graphiques engrenage %s en échec", numero)
                    e["graphiques"] = [{"type": "serie", "titre": "Graphiques", "raison": f"calcul en échec : {exc}"[:150]}]
            sortie["engrenages"][numero] = e
        except Exception as exc:  # noqa: BLE001 — un engrenage en échec n'affecte que lui
            log.exception("Dossier engrenage %s en échec", numero)
            sortie["engrenages"][numero] = {"numero": int(numero), "indisponible": f"calcul en échec : {exc}"[:200]}
    try:
        sortie["engrenages"]["1"] = engrenage_1(rapport, Path(dossier_rapports) if dossier_rapports else None, sortie["engrenages"])
    except Exception as exc:  # noqa: BLE001
        log.exception("Dossier engrenage 1 en échec")
        sortie["engrenages"]["1"] = {"numero": 1, "indisponible": f"calcul en échec : {exc}"[:200]}
    sortie["engrenages"] = dict(sorted(sortie["engrenages"].items(), key=lambda kv: int(kv[0])))
    try:   # tableau des conséquences (§9a) : corrélations et médianes sur 5 ans, sans LLM
        if h5 is not None and h5.disponible:
            for numero, tableau_c in consequences.calculer(h5, historiques, technique).items():
                if sortie["engrenages"].get(numero) and not sortie["engrenages"][numero].get("indisponible"):
                    sortie["engrenages"][numero]["consequences"] = tableau_c
    except Exception:  # noqa: BLE001
        log.exception("Tableau des conséquences en échec")
    try:
        appliquer_historique_5ans(sortie["engrenages"], h5, technique)
    except Exception:  # noqa: BLE001
        log.exception("Historique 5 ans : dossiers 5 et 7 non enrichis")
    # Tuiles de chiffres clés et carte de chaleur (refonte V2, palier 2) : une tuile en échec n'efface rien d'autre
    fabriques = {"2": lambda e: tuiles.tuiles_2(e, historiques),
                 "3": lambda e: tuiles.tuiles_3(e, historiques, registre, config),
                 "5": lambda e: tuiles.tuiles_5(e, historiques)}
    for numero, fabrique in fabriques.items():
        e = sortie["engrenages"].get(numero)
        if not e or e.get("indisponible"):
            continue
        try:
            e["tuiles"] = fabrique(e)
        except Exception as exc:  # noqa: BLE001
            log.exception("Tuiles engrenage %s en échec", numero)
            e["tuiles_indisponibles"] = f"calcul en échec : {exc}"[:150]
    # Palier 3 : dossiers 1, 4, 6, 7 et 8 (tuiles, graphiques et tableaux manquants)
    complements_par = {"1": lambda e: complements.complements_1(e, rapport, historiques, dossier_rapports, sortie["engrenages"]),
                       "4": lambda e: complements.complements_4(e, historiques),
                       "6": lambda e: complements.complements_6(e, historiques),
                       "7": lambda e: complements.complements_7(e, technique, flux, h5),
                       "8": lambda e: complements.complements_8(e, historiques, registre)}
    for numero, fabrique in complements_par.items():
        e = sortie["engrenages"].get(numero)
        if not e or e.get("indisponible"):
            continue
        try:
            fabrique(e)
        except Exception as exc:  # noqa: BLE001
            log.exception("Compléments engrenage %s en échec", numero)
            e["tuiles_indisponibles"] = f"calcul en échec : {exc}"[:150]
    try:
        if sortie["engrenages"].get("5") and not sortie["engrenages"]["5"].get("indisponible"):
            sortie["engrenages"]["5"]["matrice_chaleur"] = tuiles.matrice_chaleur(sortie["engrenages"]["5"], historiques)
    except Exception:  # noqa: BLE001
        log.exception("Carte de chaleur des corrélations en échec")
    try:   # bandeau du thème, 8 cartes et chaînes (refonte V2, palier 1) : calcul Python, sans LLM
        sortie["vue_ensemble"] = vue_ensemble.calculer(sortie["engrenages"], historiques, technique, rapport)
        try:   # matrice d'impact 9 devises × 8 engrenages (règles de config.yaml, calcul Python)
            sortie["matrice_impact"] = matrice_impact.calculer(config, sortie["engrenages"], sortie["vue_ensemble"])
        except Exception as exc:  # noqa: BLE001
            log.exception("Matrice d'impact en échec")
            sortie["matrice_impact"] = {"indisponible": f"calcul en échec : {exc}"[:200]}
    except Exception as exc:  # noqa: BLE001
        log.exception("Vue d'ensemble des engrenages en échec")
        sortie["vue_ensemble"] = {"indisponible": f"calcul en échec : {exc}"[:200]}
    return sortie


def ecrire(racine: str | Path, historiques: dict, registre: dict, technique: dict, config: dict, rapport: dict | None = None,
           flux: dict | None = None, news: dict | None = None, dossier_rapports: str | Path | None = None) -> dict | None:
    """Écrit docs/data/dossiers.json et retourne le contenu (None en cas d'échec, jamais d'exception)."""
    try:
        donnees = construire(historiques, registre, technique, config, rapport, flux, news, dossier_rapports,
                             historique_5ans.charger())
        try:   # archive quotidienne des valeurs non historisées, puis mini-courbes tirées de l'archive
            archive = archive_quotidienne.archiver(donnees["engrenages"])
            archive_quotidienne.completer_tuiles(donnees["engrenages"], archive)
        except Exception:  # noqa: BLE001
            log.exception("Archive quotidienne des indicateurs en échec")
        chemin = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data" / "dossiers.json"
        chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("dossiers.json non écrit : %s", exc)
        return None
