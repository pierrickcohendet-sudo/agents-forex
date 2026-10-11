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

from core import controles_macro, registre_macro as rm

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
        # Taux directeur : USD = taux effectif quotidien (DFF) + fourchette ; autres = registre
        if devise == "USD":
            dff = _serie(historiques, "USD_taux_effectif")
            c["taux_directeur"] = stats(dff, "%", "FRED (DFF, taux effectif)")
            c["taux_directeur"]["note"] = (f"fourchette cible : borne haute {actuel.get('valeur')} (ForexFactory)"
                                           if actuel.get("valeur") else None)
            directeur, d_dir = (c["taux_directeur"].get("valeur"), c["taux_directeur"].get("date"))
        else:
            directeur, d_dir = _registre_valeur(case)
            if directeur is None:
                c["taux_directeur"] = absent(f"valeur du registre non numérique ({actuel.get('valeur') or 'absente'})",
                                             "registre macro (ForexFactory)")
            else:
                proxy = _serie(historiques, f"{devise}_taux_jj")
                cel = stats(proxy, "%", "registre macro (ForexFactory)", "mensuel", valeur=directeur, date_valeur=d_dir) \
                    if proxy else absent("pas de série longue", "registre macro (ForexFactory)") | {"valeur": directeur, "date": d_dir}
                prec = rm.vers_nombre(str((case.get("precedent") or {}).get("valeur") or "").replace(" ", ""))
                for cle, jours in (("var_1s", 7), ("var_4s", 28)):
                    recent = d_dir and (date.today() - date.fromisoformat(d_dir)).days <= jours
                    cel[cle] = round((directeur - prec) * 100, 1) if (recent and prec is not None) else 0.0
                cel["unite"] = "%"
                if proxy and cel.get("percentile_5a") is not None:
                    cel["note_percentile"] = "percentile du taux du registre parmi les taux au jour le jour OCDE (mensuel, proxy) sur 5 ans"
                lignes_src = cel["source"]
                cel["source"] = lignes_src
                c["taux_directeur"] = cel
        # Taux 2 ans
        s2 = us2 if devise == "USD" else _serie(historiques, f"{devise}_2a")
        spec2 = (sources_taux.get(devise) or {}).get("2a") or {}
        c["taux_2a"] = stats(s2, "%", spec2.get("source") or "FRED (DGS2)") if s2 else \
            absent(spec2.get("absent") or "pas de rendement 2 ans gratuit pour ce pays")
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
        # Taux réel = directeur − inflation core a/a (registre)
        core, d_core = _registre_valeur(cases.get(f"{devise}|cpi_core"))
        if directeur is not None and core is not None:
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
            limite = (date.fromisoformat(serie[-1][0]) - timedelta(days=90)).isoformat()
            c["ecart_2a_us"]["serie_90j"] = [[d, v] for d, v in serie if d >= limite]
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
    matrice, changements, fins = {}, [], []
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
            if r is not None and r0 is not None and abs(r) >= 0.3 and abs(r0) >= 0.3 and (r > 0) != (r0 > 0):
                changements.append({"paire": [a, b], "avant": r0, "maintenant": r})
    vix = next((l["cellule"] for l in lignes if l["id"] == "vix"), {})
    regime = None
    if vix.get("valeur") is not None and vix.get("percentile_5a") is not None:
        regime = ("tension (VIX au-dessus du 80e percentile 5 ans)" if vix["percentile_5a"] >= 80 else
                  "calme (VIX sous le 20e percentile 5 ans)" if vix["percentile_5a"] <= 20 else "intermédiaire")
    return {"numero": 5, "titre": "Interconnexions de marchés", "instruments": lignes,
            "correlations": {"noms": noms, "matrice": matrice, "seances": 30,
                             "derniere_seance": max(fins) if fins else None, "changements_de_signe": changements,
                             "source": "calcul Python : rendements quotidiens (log) des devises (force, Twelve Data) et des séries FRED ; "
                                       "variations en points pour les taux"},
            "regime_volatilite": regime,
            "notes": ["Indice or (proxy) : NASDAQ QGLDI, pas le cours spot (FRED n'a plus de cours de l'or gratuit).",
                      "Changement de signe : corrélation ≥ 0,3 en valeur absolue sur les deux fenêtres de 30 séances, de signe opposé."]}


# ------------------------------------------------------------------- sortie
def construire(historiques: dict, registre: dict, technique: dict, config: dict) -> dict:
    sortie = {"version_schema": VERSION_SCHEMA, "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "debut_historique": historiques.get("debut"), "erreurs_collecte": historiques.get("erreurs", []),
              "engrenages": {}}
    for numero, fonction in (("2", lambda: engrenage_2(historiques, registre, config)),
                             ("3", lambda: engrenage_3(historiques, registre, config)),
                             ("5", lambda: engrenage_5(historiques, technique))):
        try:
            sortie["engrenages"][numero] = fonction()
        except Exception as exc:  # noqa: BLE001 — un engrenage en échec n'affecte que lui
            log.exception("Dossier engrenage %s en échec", numero)
            sortie["engrenages"][numero] = {"numero": int(numero), "indisponible": f"calcul en échec : {exc}"[:200]}
    return sortie


def ecrire(racine: str | Path, historiques: dict, registre: dict, technique: dict, config: dict) -> Path | None:
    try:
        donnees = construire(historiques, registre, technique, config)
        chemin = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data" / "dossiers.json"
        chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return chemin
    except Exception as exc:  # noqa: BLE001
        log.error("dossiers.json non écrit : %s", exc)
        return None
