"""Boîte à outils (lot V5, étapes 4 et 5) et dossier détaillé de chaque engrenage. Calcul Python, sans LLM.

A. Radar : tous les signaux du cockpit, classés par distance au seuil, avec les rendez-vous de l'agenda qui
   concernent leur engrenage.
B. « Et si… » : un scénario par seuil de chaque règle de config.yaml (matrice_impact.regles et couverture) ; la
   matrice est recalculée avec le signal posé juste au seuil, et le bilan des 9 devises comparé avant / après
   (même règle de bilan que la matrice).
C. Décomposer une paire : pour les 36 paires des 9 devises, contribution de chaque engrenage = case de la devise de
   base − case de la devise de cotation ; solde ; cases incomplètes (n/d) signalées.
D. Jours qui ressemblent à aujourd'hui : profil des engrenages qui ont une série sur 5 ans (2, 4, 5, 7, 8 ; position
   de la mesure dans son couloir, en demi-couloirs), distance euclidienne, 5 séances les plus proches depuis 2021
   (espacées d'au moins 15 jours, suivies d'un mois connu) ; variation des paires à 1 mois et médiane, toujours
   « indice faible » (5 cas < 20), jamais une probabilité.
"""
from __future__ import annotations

import bisect
import copy
import json
import logging
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

from core import cockpit as ck, impact as impact_mod, matrice_impact as mi

log = logging.getLogger(__name__)

DEVISES = mi.DEVISES
PRIORITE = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY", "CNY"]   # convention de marché : la base est à gauche
PAIRES_SIMILAIRES = ["EUR/USD", "USD/JPY", "GBP/USD", "AUD/USD", "USD/CAD", "USD/CHF"]
MIN_CAS = 20


def paires() -> list[str]:
    sortie = []
    for i, a in enumerate(PRIORITE):
        for b in PRIORITE[i + 1:]:
            sortie.append(f"{a}/{b}")
    return sortie


# ------------------------------------------------------------------- C. décomposer une paire
def decomposer(matrice: dict) -> dict[str, dict]:
    lignes = {l["devise"]: l for l in (matrice or {}).get("lignes") or []}
    sortie = {}
    for p in paires():
        base, cot = p.split("/")
        lb, lc = lignes.get(base), lignes.get(cot)
        if not lb or not lc:
            sortie[p] = {"raison": "matrice indisponible"}
            continue
        contributions, incompletes = [], []
        for cb, cc in zip(lb["cases"], lc["cases"]):
            v = cb["valeur"] - cc["valeur"]
            inc = [d for d, c in ((base, cb), (cot, cc)) if c["etat"] == "nd"]
            if inc:
                incompletes.append(f"engrenage {cb['engrenage']} : {', '.join(inc)} n/d")
            contributions.append({"engrenage": cb["engrenage"], "base": cb["valeur"], "cotation": cc["valeur"], "contribution": v,
                                  "etat_base": cb["etat"], "etat_cotation": cc["etat"], "incomplete": bool(inc)})
        solde = sum(c["contribution"] for c in contributions)
        lecture = ("soutien net de la base" if solde >= 3 else "soutien modéré de la base" if solde >= 1 else
                   "pression nette sur la base" if solde <= -3 else "pression modérée sur la base" if solde <= -1 else "équilibre")
        sortie[p] = {"base": base, "cotation": cot, "contributions": contributions, "solde": solde, "lecture": lecture,
                     "incompletes": incompletes,
                     "texte": f"Solde {p} : {solde:+d} · {lecture}".replace("-", "−") +
                              (f" · {len(incompletes)} case(s) incomplète(s)" if incompletes else "")}
    return sortie


# ------------------------------------------------------------------- B. « Et si… »
def _bilans(m: dict) -> dict[str, dict]:
    return {l["devise"]: {"bilan": l["bilan"], "lecture": l["lecture"], "cases": {c["engrenage"]: c["valeur"] for c in l["cases"]}}
            for l in m["lignes"]}


def scenarios(config: dict, matrice: dict) -> list[dict]:
    cfg = (config or {}).get("matrice_impact") or {}
    sig = copy.deepcopy((matrice or {}).get("signaux_valeurs") or {})
    couv = copy.deepcopy((matrice or {}).get("couverture") or {})
    theme_fort = bool((matrice or {}).get("theme_fort"))
    base = mi.matrice(cfg, sig, couv, theme_fort, None)
    avant = _bilans(base)
    sortie = []

    def ajouter(ident, n, libelle, description, sig_mod, couv_mod, valeur_actuelle, unite):
        apres_m = mi.matrice(cfg, sig_mod, couv_mod, theme_fort, None)
        apres = _bilans(apres_m)
        changees = [{"devise": d, "engrenage": n, "avant": avant[d]["cases"][n], "apres": apres[d]["cases"][n]}
                    for d in DEVISES if avant[d]["cases"][n] != apres[d]["cases"][n]]
        sortie.append({"id": ident, "engrenage": n, "libelle": libelle, "description": description,
                       "valeur_actuelle": valeur_actuelle, "unite": unite,
                       "bilans": [{"devise": d, "avant": avant[d]["bilan"], "apres": apres[d]["bilan"],
                                   "lecture_avant": avant[d]["lecture"], "lecture_apres": apres[d]["lecture"]} for d in DEVISES],
                       "cases_changees": changees,
                       "effets": ", ".join(f"{c['devise']} {c['apres'] - c['avant']:+d}".replace("-", "−") for c in changees) or
                                 "aucun effet (règle déjà déclenchée ou neutralisée)"})

    for n, liste in (cfg.get("regles") or {}).items():
        for r in liste or []:
            if r.get("par_devise") or r.get("exige_theme_fort"):
                continue
            actuel = sig.get(r["signal"])
            for c in r.get("cas") or []:
                op, seuil = c["si"][0], c["si"][1]
                if not isinstance(seuil, (int, float)):
                    continue
                s2 = copy.deepcopy(sig)
                ancien = list(actuel) if isinstance(actuel, (list, tuple)) else [None, "scénario", None]
                s2[r["signal"]] = (float(seuil), ancien[1] if len(ancien) > 1 else "scénario", ancien[2] if len(ancien) > 2 else None)
                sym = mi.SYMBOLES.get(op, op)
                ajouter(f"{r['signal']}-{op}{seuil}", int(n), f"{r.get('texte')} {sym} {mi._fmt(seuil, r.get('unite')).lstrip('+')}",
                        f"Engrenage {n} : " + ", ".join(f"{d} {v:+d}" for d, v in (c.get("effets") or {}).items()).replace("-", "−"),
                        s2, couv, actuel[0] if isinstance(actuel, (list, tuple)) else None, r.get("unite"))
    for n, liste in couv.items():
        for i, r in enumerate(liste or []):
            if r.get("raison"):
                continue
            for sens in ("haut", "bas"):
                seuil = r.get("seuil_haut" if sens == "haut" else "seuil_bas")
                if seuil is None:
                    continue
                c2 = copy.deepcopy(couv)
                c2[n][i].update({"direction": sens, "valeur": seuil, "neutralise": False, "declencheur": "scénario"})
                confirmees = [d for d, x in (r.get("devises") or {}).items() if x[sens]["confirmee"]]
                ajouter(f"couverture-{r['indicateur']}-{sens}", int(n),
                        f"{r.get('texte')} {'≥' if sens == 'haut' else '≤'} {ck._fr(seuil, r.get('unite'), r.get('mesure') != 'niveau')}",
                        f"Engrenage {n}, règle par devise confirmée sur 5 ans pour : {', '.join(confirmees) or 'aucune devise'}",
                        sig, c2, r.get("valeur"), r.get("unite"))
    return sortie


# ------------------------------------------------------------------- séries historiques des mesures
def _variation(points: list[tuple[str, float]], jours: int, unite: str) -> list[tuple[str, float]]:
    dates = [d for d, _ in points]
    sortie = []
    for d, v in points:
        cible = (date.fromisoformat(d) - timedelta(days=jours)).isoformat()
        j = bisect.bisect_right(dates, cible) - 1
        if j < 0:
            continue
        ref = points[j][1]
        if unite == "pb":
            sortie.append((d, round((v - ref) * 100, 4)))
        elif ref:
            sortie.append((d, round((v / ref - 1) * 100, 4)))
    return sortie


def series_mesures(h5, technique: dict | None) -> dict[int, dict]:
    """{engrenage: {points, libelle, unite, source}} pour les engrenages dont la mesure a une série sur 5 ans."""
    sortie = {}
    try:
        sortie[2] = {"points": _variation(h5.serie("USD_2a"), 7, "pb"), "libelle": "2 ans US, variation sur 7 jours", "unite": "pb",
                     "source": h5.source("USD_2a")}
        sortie[4] = {"points": _variation(h5.serie("USD_prime_terme"), 28, "pb"), "libelle": "prime de terme 10 ans US, variation sur 4 semaines",
                     "unite": "pb", "source": h5.source("USD_prime_terme")}
        sortie[5] = {"points": list(h5.serie("vix")), "libelle": "VIX", "unite": "pts", "source": h5.source("vix")}
        usd = impact_mod.serie_devise(h5, "USD", technique).points
        sortie[7] = {"points": _variation(usd, 7, "%"), "libelle": "indice USD synthétique, variation sur 5 séances", "unite": "%",
                     "source": "série unique 5 ans (indice USD synthétique)"}
        sortie[8] = {"points": _variation(h5.serie("brent"), 28, "%"), "libelle": "Brent, variation sur 4 semaines", "unite": "%",
                     "source": h5.source("brent")}
    except Exception as exc:  # noqa: BLE001
        log.warning("Séries des mesures incomplètes : %s", exc)
    return {k: v for k, v in sortie.items() if v.get("points")}


# ------------------------------------------------------------------- D. jours qui ressemblent à aujourd'hui
def _z(v, bas, haut) -> float | None:
    if v is None or haut is None:
        return None
    if bas is None:
        bas = -haut
    demi = (haut - bas) / 2 or 1.0
    return max(-3.0, min(3.0, (v - (haut + bas) / 2) / demi))


def _cours_paire(h5, technique, paire: str) -> list[tuple[str, float]] | None:
    base, cot = paire.split("/")
    serie = {}
    for d in (base, cot):
        if d == "USD":
            continue
        serie[d] = dict(impact_mod.serie_devise(h5, d, technique).points)
    dates = sorted(set.intersection(*(set(s) for s in serie.values()))) if serie else []
    out = []
    for j in dates:
        vb = 1.0 if base == "USD" else serie[base][j]
        vc = 1.0 if cot == "USD" else serie[cot][j]
        if vb and vc:
            out.append((j, vb / vc))
    return out


def jours_similaires(h5, technique: dict | None, thermos: list[dict], aujourdhui: str | None = None, n: int = 5) -> dict:
    seuils = {t["numero"]: (t.get("seuil_bas"), t.get("seuil_haut"), t.get("valeur")) for t in thermos}
    series = series_mesures(h5, technique)
    gears = [g for g in (2, 4, 5, 7, 8) if g in series and seuils.get(g, (None, None, None))[2] is not None]
    methode = ("Profil = position de la mesure de chaque engrenage dans son couloir neutre (en demi-couloirs, bornée à ±3) "
               f"pour les engrenages {', '.join(map(str, gears)) or 'aucun'} ; distance euclidienne ; 5 séances les plus proches depuis "
               "2021, espacées d'au moins 15 jours et suivies d'un mois connu. Engrenages 1, 3 et 6 exclus : pas de série sur 5 ans.")
    if len(gears) < 3:
        return {"raison": "moins de 3 engrenages avec une série sur 5 ans et une mesure du jour", "methode": methode}
    actuel = {g: _z(seuils[g][2], seuils[g][0], seuils[g][1]) for g in gears}
    par_date = {g: dict(series[g]["points"]) for g in gears}
    dates = sorted(set.intersection(*(set(par_date[g]) for g in gears)))
    fin = date.fromisoformat(aujourdhui) if aujourdhui else date.today()
    limite = (fin - timedelta(days=31)).isoformat()
    candidats = []
    for d in dates:
        if d < "2021-01-01" or d > limite:
            continue
        dist = math.sqrt(sum((_z(par_date[g][d], seuils[g][0], seuils[g][1]) - actuel[g]) ** 2 for g in gears))
        candidats.append((dist, d))
    choisis = []
    for dist, d in sorted(candidats):
        if all(abs((date.fromisoformat(d) - date.fromisoformat(c)).days) >= 15 for _, c in choisis):
            choisis.append((dist, d))
        if len(choisis) == n:
            break
    if not choisis:
        return {"raison": "historique trop court pour trouver des séances comparables", "methode": methode}
    cours = {p: _cours_paire(h5, technique, p) for p in PAIRES_SIMILAIRES}
    lignes = []
    for dist, d in choisis:
        var = {}
        for p, pts in cours.items():
            if not pts:
                var[p] = None
                continue
            dd = [x for x, _ in pts]
            i0 = bisect.bisect_right(dd, d) - 1
            i1 = bisect.bisect_right(dd, (date.fromisoformat(d) + timedelta(days=30)).isoformat()) - 1
            var[p] = round((pts[i1][1] / pts[i0][1] - 1) * 100, 2) if i0 >= 0 and i1 > i0 else None
        lignes.append({"date": d, "distance": round(dist, 2), "variations_1m": var,
                       "profil": {str(g): round(_z(par_date[g][d], seuils[g][0], seuils[g][1]), 2) for g in gears}})
    medianes = {p: (round(statistics.median([l["variations_1m"][p] for l in lignes if l["variations_1m"][p] is not None]), 2)
                    if [l for l in lignes if l["variations_1m"][p] is not None] else None) for p in PAIRES_SIMILAIRES}
    return {"seances": lignes, "medianes": medianes, "paires": PAIRES_SIMILAIRES, "n": len(lignes),
            "lecture": f"indice faible · {len(lignes)} cas (moins de {MIN_CAS}) : une médiane descriptive, jamais une probabilité",
            "profil_actuel": {str(g): round(actuel[g], 2) for g in gears}, "methode": methode,
            "source": "série unique 5 ans (Twelve Data raccordé à la Fed H.10), FRED"}


# ------------------------------------------------------------------- A. radar
def radar(cockpit_donnees: dict, agenda_donnees: dict | None) -> dict:
    rdv = {}
    for j in (agenda_donnees or {}).get("jours") or []:
        for e in j["evenements"]:
            if e.get("engrenage") and e["impact"] in ("fort", "moyen"):
                rdv.setdefault(e["engrenage"], []).append(e)
    signaux = []
    for s in (cockpit_donnees or {}).get("signaux") or []:
        signaux.append({**s, "phrase": ck.phrase_distance(s) if s["etat"] != "n/d" else f"{s['libelle']} : n/d",
                        "rendez_vous": [{k: e[k] for k in ("date_paris", "heure_paris", "devise", "evenement", "impact")}
                                        for e in rdv.get(s["engrenage"], [])[:3]]})
    tous_rdv = sorted([e for es in rdv.values() for e in es], key=lambda e: e["iso_utc"])
    return {"signaux": signaux, "rendez_vous": tous_rdv[:12], "methode": (cockpit_donnees or {}).get("methode")}


# ------------------------------------------------------------------- étape 4 : dossier détaillé
SIMULATEUR_ENGRENAGE = {2: "us2a", 3: "cpi_us", 4: "us10a", 5: "vix", 6: "or", 7: "dollar_large", 8: "brent"}


def _histoire(impact: dict | None, indicateur: str | None, sens: str = "hausse|1") -> dict:
    if not indicateur:
        return {"raison": "pas d'indicateur du simulateur pour cet engrenage (thème : synthèse des autres)"}
    ind = next((i for i in (impact or {}).get("indicateurs") or [] if i.get("id") == indicateur), None)
    if not ind:
        return {"raison": "étude d'impact absente pour cet indicateur"}
    lignes = []
    for d in DEVISES:
        c = ((impact or {}).get("couples") or {}).get(f"{indicateur}|{d}") or {}
        m = ((c.get("scenarios") or {}).get(sens) or {}).get("mois") or {}
        if not m:
            lignes.append({"devise": d, "mediane": None, "lecture": "n/d", "raison": "pas d'étude pour ce couple"})
            continue
        if m.get("n", 0) < MIN_CAS or m.get("insuffisant"):
            lecture = f"échantillon insuffisant · {m.get('n', 0)} cas"
        elif (m.get("borne_wilson_90") or 0) <= 50:
            lecture = f"indice faible · {m.get('n')} cas"
        else:
            lecture = f"confirmé · {m.get('n')} cas (Wilson {str(m.get('borne_wilson_90')).replace('.', ',')} %)"
        lignes.append({"devise": d, "mediane": m.get("mediane"), "n": m.get("n"), "borne_wilson_90": m.get("borne_wilson_90"),
                       "lecture": lecture, "conforme": (m.get("lecture_classique") or {}).get("conforme")})
    return {"indicateur": indicateur, "libelle": ind.get("libelle"), "scenario": "hausse d'1 écart-type, médiane à 1 mois",
            "lignes": lignes, "lien": f"#scenarios/i={indicateur}", "source": "simulateur d'impact (docs/data/impact.json), 5 ans"}


def details(dossiers_engrenages: dict, cockpit_donnees: dict, matrice: dict, rapport: dict | None, h5, technique: dict | None,
            impact: dict | None, scen: list[dict], historiques: dict | None = None) -> dict:
    from core import annotations
    thermos = {t["numero"]: t for t in (cockpit_donnees or {}).get("thermometres") or []}
    eng = {e.get("numero"): e for e in ((((rapport or {}).get("synthese_globale") or {}).get("engrenages") or {}).get("engrenages") or [])}
    texte_absent = (((rapport or {}).get("synthese_globale") or {}).get("engrenages") or {}).get("texte_indisponible")
    series = series_mesures(h5, technique) if h5 is not None else {}
    sortie = {}
    for n in range(1, 9):
        dos = (dossiers_engrenages or {}).get(str(n)) or {}
        t = thermos.get(n) or {}
        chiffres = []
        for tu in (dos.get("tuiles") or [])[:4]:
            chiffres.append({"libelle": tu.get("libelle"), "texte": tu.get("texte") or ("n/d" if tu.get("valeur") is None else str(tu.get("valeur"))),
                             "date": tu.get("date"), "source": tu.get("source"), "raison": tu.get("raison"),
                             "variation": (tu.get("variation") or {}).get("texte"), "percentile_5a": tu.get("percentile_5a"),
                             "rang": (f"{tu['percentile_5a']}e percentile sur 5 ans" if tu.get("percentile_5a") is not None
                                      else f"rang 5 ans n/d : {tu.get('raison_percentile') or 'pas d’historique de 5 ans'}")})
        courbe = None
        if n in series:
            fin = series[n]["points"][-1][0]
            debut = (date.fromisoformat(fin) - timedelta(days=183)).isoformat()
            pts = [[d, v] for d, v in series[n]["points"] if d >= debut]
            courbe = {"points": pts, "libelle": series[n]["libelle"], "unite": series[n]["unite"], "source": series[n]["source"],
                      "seuil_bas": t.get("seuil_bas"), "seuil_haut": t.get("seuil_haut"),
                      "classe_bas": t.get("classe_bas"), "classe_haut": t.get("classe_haut"),
                      "annotations": annotations.reperes(pts, series[n]["unite"], series[n]["source"])}
        regles = [{"libelle": s["libelle"], "etat": {"franchi": "déclenchée", "proche": "proche", "non": "non"}.get(s["etat"], s["etat"]),
                   "distance": s.get("distance_texte"), "valeur": s.get("texte_valeur"), "date": s.get("date"), "source": s.get("source"),
                   "neutralise": s.get("neutralise")}
                  for s in (cockpit_donnees or {}).get("signaux") or [] if s["engrenage"] == n][:14]
        e = eng.get(n) or {}
        diag = None if e.get("donnees_insuffisantes") or e.get("texte_indisponible") else e.get("diagnostic")
        sortie[str(n)] = {
            "numero": n, "nom": ck.NOMS[n], "thermometre": t, "chiffres": chiffres,
            "courbe": courbe, "raison_courbe": None if courbe else (
                "pas de série sur 5 ans pour cette mesure" if n in (3, 6) else "fil des 15 séances (thème) dans le cockpit" if n == 1
                else "série indisponible"),
            "regles": regles, "scenarios": [s for s in scen if s["engrenage"] == n],
            "histoire": _histoire(impact, SIMULATEUR_ENGRENAGE.get(n)),
            "lecture": {"texte": diag, "source": "modèle" if diag else "calcul Python",
                        "phrase_python": f"{t.get('direction', {}).get('libelle') or 'Direction n/d'}. {t.get('note') or ''}".strip(),
                        "texte_indisponible": None if diag else (e.get("texte_indisponible") or texte_absent or
                                                                 ("Données insuffisantes aujourd'hui." if e.get("donnees_insuffisantes") else
                                                                  "Texte indisponible : synthèse rédigée absente")),
                        "redige_par": ((((rapport or {}).get("synthese_globale") or {}).get("engrenages") or {}).get("redige_par") or {}).get("libelle"),
                        # le texte décrit les chiffres de SON heure de rédaction ; les chiffres affichés sont ceux du dernier passage
                        "redige_le": (((rapport or {}).get("synthese_globale") or {}).get("engrenages") or {}).get("genere_le") if diag else None,
                        "redige_avant_recalcul": bool(e.get("texte_redige_avant_recalcul"))},
        }
    return sortie


def calculer(config: dict, dossiers_donnees: dict, h5, technique: dict | None, agenda_donnees: dict | None) -> dict:
    matrice = dossiers_donnees.get("matrice_impact") or {}
    c = dossiers_donnees.get("cockpit") or {}
    sortie = {"genere_le": dossiers_donnees.get("genere_le"), "note": "Aide à la décision, jamais un ordre d'achat ou de vente."}
    for cle, f in (("radar", lambda: radar(c, agenda_donnees)), ("scenarios", lambda: scenarios(config, matrice)),
                   ("paires", lambda: decomposer(matrice)),
                   ("similaires", lambda: jours_similaires(h5, technique, c.get("thermometres") or [],
                                                           ((dossiers_donnees.get("vue_ensemble") or {}).get("theme") or {}).get("date_rapport")))):
        try:
            sortie[cle] = f()
        except Exception as exc:  # noqa: BLE001 — un outil en échec n'affecte que lui
            log.exception("Outil %s en échec", cle)
            sortie[cle] = {"indisponible": f"calcul en échec : {exc}"[:200]}
    return sortie


def ecrire(racine: str | Path, config: dict, dossiers_donnees: dict, h5, technique: dict | None, agenda_donnees: dict | None) -> dict | None:
    try:
        donnees = calculer(config, dossiers_donnees, h5, technique, agenda_donnees)
        chemin = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data" / "outils.json"
        chemin.write_text(json.dumps(donnees, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("outils.json non écrit : %s", exc)
        return None
