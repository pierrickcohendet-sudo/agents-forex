"""Cockpit des 8 engrenages (lot V5, étapes 3 et 5A) : calcul Python publié dans dossiers.json → « cockpit ».

- En-tête du thème : alignés sur 7, titre (imposé ou non), dollar / risque / cases actives, paragraphe.
- Thermomètres : pour chaque engrenage, la mesure qui décide sa direction et SES seuils (règles Python :
  agent_engrenages.SEUILS et config.yaml matrice_impact) ; positions en % calculées ici, jamais dans le site.
- Signaux : tous les signaux évalués (thermomètres, signaux par devise de la matrice, couverture), avec leur
  distance au seuil le plus proche en unité réelle et en % du couloir neutre → « au bord du seuil » et radar.
- Fil des 15 dernières séances : direction de chaque engrenage reconstruite depuis les rapports archivés.
Aucune valeur inventée : une mesure absente est « n/d » avec la raison.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from core import vue_ensemble

PROCHE_PCT = 15.0          # à moins de 15 % du couloir neutre : « proche »
NB_SEANCES = 15
NOMS = vue_ensemble.TITRES
COURTS = {1: "Thème", 2: "Monétaire", 3: "Données", 4: "Fiscale", 5: "Marchés", 6: "Géopolitique", 7: "Flux", 8: "Offre"}


def _fr(v, unite: str | None = None, signe: bool = False) -> str:
    if v is None:
        return "n/d"
    dec = 0 if unite in ("pb", "titres", "alignés", "percentile") else 2
    t = (f"{v:+.{dec}f}" if signe else f"{v:.{dec}f}").replace(".", ",").replace("-", "−")
    return t + {"pb": " pb", "%": " %", "pts": "", "écarts": "", "titres": "", "alignés": "", "percentile": "e pct"}.get(unite or "", "")


def _seuils_config(config: dict, numero: str, signal: str) -> tuple[float | None, float | None]:
    """Seuils bas / haut d'une règle de la matrice (cas « si » ou paliers les plus proches de zéro)."""
    for r in (((config or {}).get("matrice_impact") or {}).get("regles") or {}).get(numero) or []:
        if r.get("signal") != signal:
            continue
        conditions = [c["si"] for c in r.get("cas") or []] + [p[:2] for p in r.get("paliers") or []]
        hauts = [c[1] for c in conditions if c[0] in (">=", ">") and isinstance(c[1], (int, float))]
        bas = [c[1] for c in conditions if c[0] in ("<=", "<") and isinstance(c[1], (int, float))]
        return (max(bas) if bas else None), (min(hauts) if hauts else None)
    return None, None


def distance(valeur, bas, haut) -> dict:
    """État (franchi / proche / non), distance au seuil le plus proche (unité réelle) et en % du couloir."""
    if valeur is None:
        return {"etat": "n/d", "distance": None, "distance_pct": None, "cote": None}
    if bas is None and haut is None:
        return {"etat": "sans seuil", "distance": None, "distance_pct": None, "cote": None}
    if haut is not None and valeur >= haut:
        return {"etat": "franchi", "distance": 0.0, "distance_pct": 0.0, "cote": "haut"}
    if bas is not None and valeur <= bas:
        return {"etat": "franchi", "distance": 0.0, "distance_pct": 0.0, "cote": "bas"}
    couloir = (haut - bas) if haut is not None and bas is not None else abs(haut if haut is not None else bas) or 1.0
    options = [(haut - valeur, "haut")] if haut is not None else []
    options += [(valeur - bas, "bas")] if bas is not None else []
    d, cote = min(options)
    pct = round(100 * d / couloir, 1) if couloir else None
    return {"etat": "proche" if pct is not None and pct <= PROCHE_PCT else "non", "distance": round(d, 4),
            "distance_pct": pct, "cote": cote}


def _plage(valeur, bas, haut, plage=None) -> tuple[float, float]:
    if plage:
        lo, hi = plage
    elif bas is None and haut is None:
        lo, hi = (valeur - 1, valeur + 1) if valeur is not None else (0.0, 1.0)
    elif bas is not None and haut is not None:
        w = haut - bas
        lo, hi = bas - 0.75 * w, haut + 0.75 * w
    else:
        s = abs(haut if haut is not None else bas)
        lo, hi = -2 * s, 2 * s
    if valeur is not None:
        lo, hi = min(lo, valeur), max(hi, valeur)
    return lo, hi


def _pos(x, lo, hi) -> float | None:
    return None if x is None else round(100 * (x - lo) / ((hi - lo) or 1), 1)


def classe_effet(effet: str | None) -> str:
    """Couleur d'une zone du thermomètre (même règle que la roue) : up = dollar haussier ou risk on, dn = l'inverse."""
    t = (effet or "").lower()
    if "risk off" in t or "baissier" in t or "pression usd" in t or "refuge" in t:
        return "dn"
    if "risk on" in t or "haussier" in t:
        return "up"
    return "nd"


def thermometre(numero: int, mesure: dict | None, direction: dict, note: str, plage=None, indicateur: str | None = None,
                neutralise: str | None = None) -> dict:
    m = mesure or {}
    v, bas, haut = m.get("valeur"), m.get("seuil_bas"), m.get("seuil_haut")
    lo, hi = _plage(v, bas, haut, plage)
    d = distance(v, bas, haut)
    return {"numero": numero, "titre": COURTS[numero], "nom": NOMS[numero], "libelle": m.get("libelle"), "valeur": v,
            "texte_valeur": _fr(v, m.get("unite"), signe=m.get("unite") in ("pb", "%", "écarts")), "unite": m.get("unite"),
            "date": m.get("date"), "source": m.get("source"), "raison": m.get("raison") if v is None else None,
            "seuil_bas": bas, "seuil_haut": haut, "pos": _pos(v, lo, hi), "pos_bas": _pos(bas, lo, hi), "pos_haut": _pos(haut, lo, hi),
            "si_haut": m.get("si_haut"), "si_bas": m.get("si_bas"),
            "classe_haut": classe_effet(m.get("si_haut")), "classe_bas": classe_effet(m.get("si_bas")), **d,
            "direction": {"libelle": direction.get("libelle"), "classe": direction.get("classe")},
            "neutralise": neutralise, "note": note, "indicateur": indicateur}


def _seuils_txt(bas, haut, unite) -> str:
    if bas is not None and haut is not None and bas == -haut:
        return f"seuils ±{_fr(haut, unite)}"
    morceaux = []
    if bas is not None:
        morceaux.append(f"bas {_fr(bas, unite)}")
    if haut is not None:
        morceaux.append(f"haut {_fr(haut, unite)}")
    return "seuils " + " / ".join(morceaux) if morceaux else "pas de seuil"


def thermometres(vue: dict, matrice: dict, rapport: dict | None, config: dict) -> list[dict]:
    cartes = {c["numero"]: c for c in (vue or {}).get("cartes") or []}
    theme = (vue or {}).get("theme") or {}
    coh = theme.get("coherence") or {}
    eng = {e.get("numero"): e for e in ((((rapport or {}).get("synthese_globale") or {}).get("engrenages") or {}).get("engrenages") or [])}
    sig = (matrice or {}).get("signaux_valeurs") or {}
    sortie = []
    # 1. Thème : engrenages alignés sur 7, seuil de thème établi
    seuil = vue_ensemble.SEUIL_THEME_FORT
    m1 = {"libelle": "engrenages alignés sur 7", "valeur": coh.get("alignes") if coh else None, "unite": "alignés",
          "seuil_bas": None, "seuil_haut": seuil, "date": theme.get("date_rapport"), "source": "règles Python des 8 engrenages",
          "si_haut": "Thème établi", "si_bas": None, "raison": "synthèse des engrenages absente"}
    note1 = (vue_ensemble.THEME_NEUTRE + "." if coh.get("theme_neutre") else
             f"Seuil de thème établi : {seuil} alignés." + (" Titre imposé « Signaux mixtes »." if theme.get("titre_impose") else ""))
    sortie.append(thermometre(1, m1, theme.get("direction") or {}, note1, plage=(0, 7)))
    for n, ind in ((2, None), (3, None), (5, "vix"), (7, None)):
        m = (eng.get(n) or {}).get("mesure")
        if not m:
            m = {"raison": "mesure absente du rapport (rapport antérieur au cockpit ou synthèse indisponible)"}
        note = f"{_seuils_txt(m.get('seuil_bas'), m.get('seuil_haut'), m.get('unite'))}. {cartes.get(n, {}).get('ligne') or ''}".strip()
        sortie.append(thermometre(n, m, (cartes.get(n) or {}).get("direction") or {}, note, indicateur=ind))
    # 4, 6, 8 : signaux de la matrice d'impact, seuils lus dans config.yaml
    for n, signal, libelle, unite, si_h, si_b, plage in (
            (4, "prime_terme_var_4s", "prime de terme 10 ans US, 4 sem.", "pb", "Pression USD (prime de risque budgétaire)", None, None),
            (6, "titres_refuge", "titres « refuge » du jour", "titres", "Soutien des refuges (USD, JPY, CHF)", None, (0, 6)),
            (8, "brent_var_4s", "Brent sur 4 semaines", "%", "Soutien CAD, pression JPY / EUR", "Pression CAD, soutien JPY", None)):
        bas, haut = _seuils_config(config, str(n), signal)
        v = sig.get(signal)
        m = {"libelle": libelle, "valeur": v[0] if v else None, "unite": unite, "seuil_bas": bas, "seuil_haut": haut,
             "date": v[2] if v else None, "source": v[1] if v else None, "si_haut": si_h, "si_bas": si_b,
             "raison": "signal absent des dossiers du jour"}
        neutralise = None
        if v and len(v) > 3 and v[3] and "heurt" in str(v[3]):
            d = distance(v[0], bas, haut)
            neutralise = f"au-delà du seuil mais neutralisé : {v[3]}" if d["etat"] == "franchi" else f"série heurtée : {v[3]}"
        note = f"{_seuils_txt(bas, haut, unite)}. {cartes.get(n, {}).get('ligne') or ''}".strip()
        sortie.append(thermometre(n, m, (cartes.get(n) or {}).get("direction") or {}, note, plage=plage, neutralise=neutralise))
    return sorted(sortie, key=lambda t: t["numero"])


def signaux(thermos: list[dict], matrice: dict, config: dict) -> list[dict]:
    """Tous les signaux évalués, classés par distance au seuil (en % du couloir neutre) — radar et « au bord du seuil »."""
    sortie = []
    for t in thermos:
        if t["valeur"] is None or (t["seuil_bas"] is None and t["seuil_haut"] is None):
            continue
        sortie.append({"id": f"thermometre-{t['numero']}", "engrenage": t["numero"], "devise": None,
                       "libelle": f"{t['libelle']}", "effet_haut": t.get("si_haut"), "effet_bas": t.get("si_bas"),
                       "valeur": t["valeur"], "texte_valeur": t["texte_valeur"], "unite": t["unite"], "date": t["date"],
                       "source": t["source"], "seuil_bas": t["seuil_bas"], "seuil_haut": t["seuil_haut"],
                       "neutralise": t.get("neutralise"),
                       **{k: t[k] for k in ("etat", "distance", "distance_pct", "cote")}})
    sig = (matrice or {}).get("signaux_valeurs") or {}
    for n, liste in (((config or {}).get("matrice_impact") or {}).get("regles") or {}).items():
        for r in liste or []:
            if not r.get("par_devise"):
                continue
            bas, haut = _seuils_config(config, n, r["signal"])
            for devise, v in (sig.get(r["signal"]) or {}).items():
                d = distance(v[0], bas, haut)
                sortie.append({"id": f"{r['signal']}-{devise}", "engrenage": int(n), "devise": devise,
                               "libelle": f"{r.get('texte')} — {devise}", "effet_haut": f"{devise} +1 (règle {n})",
                               "effet_bas": f"{devise} −1 (règle {n})", "valeur": v[0], "texte_valeur": _fr(v[0], r.get("unite"), r.get("unite") in ("pb", "%", "écarts")),
                               "unite": r.get("unite"), "date": v[2], "source": v[1], "seuil_bas": bas, "seuil_haut": haut, **d})
    for n, liste in ((matrice or {}).get("couverture") or {}).items():
        for r in liste or []:
            if r.get("valeur") is None:
                continue
            d = distance(r["valeur"], r.get("seuil_bas"), r.get("seuil_haut"))
            confirmees = sorted(dv for dv, x in (r.get("devises") or {}).items() if x["haut"]["confirmee"] or x["bas"]["confirmee"])
            sortie.append({"id": f"couverture-{r['indicateur']}", "engrenage": int(n), "devise": None, "libelle": r.get("texte"),
                           "effet_haut": "devises confirmées : " + (", ".join(confirmees) or "aucune"), "effet_bas": None,
                           "valeur": r["valeur"], "texte_valeur": _fr(r["valeur"], r.get("unite"), r.get("mesure") != "niveau"),
                           "unite": r.get("unite"), "date": r.get("date"), "source": r.get("source"),
                           "seuil_bas": r.get("seuil_bas"), "seuil_haut": r.get("seuil_haut"),
                           "declencheur": r.get("declencheur"), "neutralise": r.get("serie_heurtee") if r.get("neutralise") else None, **d})
    ordre = {"franchi": 0, "proche": 1, "non": 2, "n/d": 3}
    return sorted(sortie, key=lambda s: (ordre.get(s["etat"], 3), s["distance_pct"] if s["distance_pct"] is not None else 999))


def distance_texte(s: dict) -> str:
    if s["etat"] == "franchi":
        return "franchi"
    if s.get("distance") is None:
        return "n/d"
    return f"{round(s['distance'])} pts" if s["unite"] == "percentile" else _fr(s["distance"], s["unite"])


def phrase_distance(s: dict) -> str:
    if s["etat"] == "franchi":
        return f"{s['libelle']} : {s['texte_valeur']}, seuil {s['cote']} franchi" + (f" ({s['neutralise']})" if s.get("neutralise") else "")
    seuil = s["seuil_haut"] if s["cote"] == "haut" else s["seuil_bas"]
    d_txt = f"{round(s['distance'])} points" if s["unite"] == "percentile" else _fr(s["distance"], s["unite"])
    return (f"{s['libelle']} à {s['texte_valeur']} : {d_txt} du seuil {s['cote']} "
            f"({_fr(seuil, s['unite'], s['unite'] in ('pb', '%', 'écarts'))}), soit {str(s['distance_pct']).replace('.', ',')} % du couloir neutre")


def fil(dossier_rapports: Path | None, fin: str | None, n: int = NB_SEANCES) -> dict:
    """Direction de chaque engrenage par séance (rapports archivés) ; jour sans donnée : None (hachuré)."""
    try:
        jour = date.fromisoformat(fin) if fin else date.today()
    except ValueError:
        jour = date.today()
    jours = []
    while len(jours) < n:
        if jour.weekday() < 5:
            jours.append(jour.isoformat())
        jour -= timedelta(days=1)
    jours.reverse()
    par_jour = {}
    for d in jours:
        try:
            r = json.loads((Path(dossier_rapports) / f"{d}.json").read_text(encoding="utf-8")) if dossier_rapports else None
        except (OSError, ValueError):
            r = None
        eng = (((r or {}).get("synthese_globale") or {}).get("engrenages") or {}).get("engrenages") or []
        par_jour[d] = {e.get("numero"): vue_ensemble._direction(e) for e in eng if e.get("numero")}
    lignes = []
    for num in range(1, 9):
        cellules = []
        for d in jours:
            dr = par_jour[d].get(num)
            cellules.append({"date": d, "classe": dr["classe"] if dr and (dr["dollar"] or dr["risque"]) else None,
                             "libelle": dr["libelle"] if dr else "pas de rapport ce jour-là"})
        lignes.append({"numero": num, "titre": COURTS[num], "cellules": cellules})
    return {"jours": jours, "lignes": lignes, "source": "rapports quotidiens archivés (data/rapports)",
            "note": "Une bande qui change de couleur = un engrenage qui bascule. Hachures : pas de rapport ce jour-là."}


def entete(vue: dict, matrice: dict) -> dict:
    theme = (vue or {}).get("theme") or {}
    coh = theme.get("coherence") or {}
    d = theme.get("direction") or {}
    orientes = [f"{c['numero']}. {COURTS[c['numero']]} ({c['direction']['libelle']})" for c in (vue or {}).get("cartes") or []
                if c["numero"] != 1 and c.get("direction", {}).get("classe") in ("up", "dn")]
    explication = (("Engrenages orientés : " + " ; ".join(orientes) + ". Les autres restent dans leur couloir neutre.")
                   if orientes else "Aucun engrenage n'est sorti de son couloir neutre.")
    return {"alignes": coh.get("alignes"), "evaluables": coh.get("evaluables"), "sur": 7, "theme_neutre": coh.get("theme_neutre"),
            "titre": theme.get("titre") or theme.get("texte_indisponible") or "Thème non déterminé",
            "titre_impose": theme.get("titre_impose"), "dollar": d.get("dollar"), "risque": d.get("risque"),
            "direction": {"libelle": d.get("libelle"), "classe": d.get("classe")}, "conviction": d.get("conviction_niveau"),
            "cases_actives": (matrice or {}).get("cases_actives"), "cases_total": (matrice or {}).get("cases_total"),
            "compte_matrice": (matrice or {}).get("compte_libelle"), "explication": explication,
            "texte": theme.get("texte") or theme.get("texte_python"),
            "texte_source": "modèle" if theme.get("texte") else "calcul Python",
            "texte_indisponible": theme.get("texte_indisponible"), "date_rapport": theme.get("date_rapport")}


def calculer(vue: dict, matrice: dict, rapport: dict | None, config: dict, dossier_rapports: Path | None,
             agenda_donnees: dict | None = None) -> dict:
    from core import agenda
    thermos = thermometres(vue, matrice, rapport, config)
    tous = signaux(thermos, matrice, config)
    for s in tous:
        s["distance_texte"] = distance_texte(s)
    bord = [s for s in tous if s["etat"] in ("proche", "non")][:3]
    rdv = agenda.prochain_rendez_vous(agenda_donnees)
    return {"entete": entete(vue, matrice), "thermometres": thermos, "signaux": tous,
            "au_bord": [{**s, "phrase": phrase_distance(s), "distance_texte": distance_texte(s)} for s in bord],
            "franchis": [{**s, "phrase": phrase_distance(s)} for s in tous if s["etat"] == "franchi"],
            "rendez_vous": rdv, "fil": fil(dossier_rapports, ((vue or {}).get("theme") or {}).get("date_rapport")),
            "proche_pct": PROCHE_PCT,
            "methode": f"Distance au seuil le plus proche, en unité réelle et en % du couloir neutre (écart entre seuil bas et "
                       f"seuil haut) ; « proche » sous {PROCHE_PCT:.0f} %. Seuils : règles Python des engrenages et de config.yaml."}
