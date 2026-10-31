"""Matrice « Impact sur chaque devise » (refonte V2, §8) : 9 devises × 8 engrenages, de −2 à +2.

Calcul Python uniquement : les règles sont dans config.yaml (matrice_impact), les signaux sont lus dans les
dossiers déjà calculés (mêmes chiffres que le reste du site). Chaque case garde la règle appliquée et le
chiffre qui la déclenche ; une case sans règle ou sans donnée vaut 0 avec la raison. Bilan = somme des 8
cases (soutenue ≥ +3, sous pression ≤ −3, sinon neutre). Aucune case n'est une recommandation.
"""
from __future__ import annotations

import operator

DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
OPERATEURS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt, "==": operator.eq}
SYMBOLES = {">=": "≥", "<=": "≤", ">": ">", "<": "<", "==": "="}


def _pts(n: int) -> str:
    return f"{n:+d}".replace("-", "−")


from core import couverture  # noqa: E402
from core.indicateurs import TEXTE_NEUTRALISE  # noqa: E402

LIBELLES = {2: "Soutien fort", 1: "Soutien", 0: "Neutre", -1: "Pression", -2: "Pression forte"}


def _tuile(e: dict, ident: str) -> dict:
    return next((t for t in (e or {}).get("tuiles") or [] if t.get("id") == ident), {})


def _instrument(e: dict, ident: str) -> dict:
    return next((i["cellule"] for i in (e or {}).get("instruments") or [] if i.get("id") == ident), {})


def _par_devise(e: dict, colonne: str, champ: str = "valeur") -> dict:
    sortie = {}
    for ligne in (e or {}).get("lignes") or []:
        c = (ligne.get("cellules") or {}).get(colonne) or {}
        if c.get(champ) is not None:
            sortie[ligne["devise"]] = (c[champ], c.get("source"), c.get("date"))
    return sortie


def signaux(engrenages: dict, vue: dict | None) -> dict:
    """{nom: (valeur, source, date)} ou {nom: {devise: (valeur, source, date)}} ; absent = pas de donnée."""
    g = {str(k): v for k, v in (engrenages or {}).items()}
    theme = ((vue or {}).get("theme") or {})
    d1 = theme.get("direction") or {}
    sortie: dict = {}
    if d1.get("risque"):
        sortie["theme_risque"] = (d1["risque"], "règles Python (thème global)", theme.get("date_rapport"))
    if d1.get("dollar"):
        sortie["theme_dollar"] = (d1["dollar"], "règles Python (thème global)", theme.get("date_rapport"))
    coh = theme.get("coherence") or {}
    sortie["_theme_fort"] = (bool(coh.get("theme_fort")), coh.get("libelle"), theme.get("date_rapport"))
    sortie["ecart_2a_us_var_4s"] = _par_devise(g.get("2"), "ecart_2a_us", "var_4s")
    usd2 = next((l["cellules"].get("taux_2a") or {} for l in (g.get("2") or {}).get("lignes") or [] if l["devise"] == "USD"), {})
    if usd2.get("var_4s") is not None:
        sortie["us2a_var_4s"] = (usd2["var_4s"], usd2.get("source"), usd2.get("date"))
    sortie["surprise_30j"] = _par_devise(g.get("3"), "indice_surprise")
    pt = next((l["cellules"].get("prime_terme") or {} for l in (g.get("4") or {}).get("lignes") or [] if l["devise"] == "USD"), {})
    if pt.get("var_4s") is not None:
        sortie["prime_terme_var_4s"] = (pt["var_4s"], pt.get("source"), pt.get("date"))
    bb = _tuile(g.get("4"), "btp_bund")
    if (bb.get("variation") or {}).get("valeur") is not None:
        sortie["btp_bund_var_3m"] = (bb["variation"]["valeur"], bb.get("source"), bb.get("date"))
    vix = _instrument(g.get("5"), "vix")
    if vix.get("valeur") is not None:
        sortie["vix"] = (vix["valeur"], vix.get("source"), vix.get("date"), vix.get("alerte"))
    sp = _instrument(g.get("5"), "sp500")
    if sp.get("var_4s") is not None:
        sortie["sp500_var_4s"] = (sp["var_4s"], sp.get("source"), sp.get("date"))
    for ident, nom in (("canal_refuge", "titres_refuge"), ("canal_énergi", "titres_energie")):
        t = _tuile(g.get("6"), ident)
        if t.get("valeur") is not None:
            sortie[nom] = (t["valeur"], t.get("source"), t.get("date"))
    sortie["ecart_mm200"] = _par_devise(g.get("7"), "ecart_mm200")
    sortie["cot_percentile_52s"] = _par_devise(g.get("7"), "cot", "percentile_52s")
    br = _instrument(g.get("8"), "brent")
    if br.get("var_4s") is not None:   # 4e élément : alerte « série heurtée » (le signal compte alors pour 0)
        sortie["brent_var_4s"] = (br["var_4s"], br.get("source"), br.get("date"), br.get("alerte"))
    st = _instrument(g.get("8"), "eia_stocks")
    if st.get("ecart_moyenne_5a_pct") is not None:
        sortie["stocks_ecart_pct"] = (st["ecart_moyenne_5a_pct"], st.get("source"), st.get("date"))
    return sortie


def _verifie(condition: list, valeur) -> bool:
    op, seuil = condition[0], condition[1]
    try:
        return OPERATEURS[op](valeur, seuil)
    except (KeyError, TypeError):
        return False


def _fmt(v, unite: str | None) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return str(v)
    if unite == "pb":
        t = f"{v:+.0f} pb"
    elif unite == "écarts":
        t = f"{v:+.2f}"
    elif unite == "%":
        t = f"{v:+.2f} %"
    else:
        t = f"{v:g}" + (f" {unite}" if unite else "")
    return t.replace(".", ",").replace("-", "−")


ETATS = ("active", "neutralise", "neutre", "nd", "sans_regle")
LIBELLES_ETAT = {"neutre": "Neutre", "nd": "n/d", "sans_regle": "Sans règle", "neutralise": "Neutralisé"}
# Indicateur de la couverture -> signal d'une règle existante sur le même indicateur (jamais compté deux fois)
SIGNAL_EXISTANT = {"vix": "vix", "sp500": "sp500_var_4s", "brent": "brent_var_4s"}


def _deja_couverte(liste: list, indicateur: str, devise: str) -> bool:
    signal = SIGNAL_EXISTANT.get(indicateur)
    for r in liste:
        if r.get("signal") != signal:
            continue
        if r.get("par_devise") or devise in {d for c in r.get("cas") or [] for d in (c.get("effets") or {})}:
            return True
    return False


def _case(devise: str, n: int, liste: list, sig: dict, theme_fort: bool, coh_libelle: str | None, couv: list) -> dict:
    """Une case de la matrice : valeur bornée à ±2, état (active / neutralise / neutre / nd / sans_regle) et raisons."""
    points, appliquees, neutralisees = 0, [], []
    evaluees, manquantes, non_confirmees = [], [], []
    for r in liste:
        nom, texte, unite = r.get("signal"), r.get("texte", r.get("signal")), r.get("unite")
        if r.get("exige_theme_fort") and not theme_fort:
            evaluees.append(f"{texte} : non appliqué, signaux mixtes ({coh_libelle or 'cohérence indisponible'})")
            continue
        valeur = sig.get(nom)
        if r.get("par_devise"):
            v = (valeur or {}).get(devise) if isinstance(valeur, dict) else None
            if v is None:
                manquantes.append(f"{texte} : pas de donnée pour {devise}")
                continue
            palier = next((p for p in r.get("paliers") or [] if _verifie(p, v[0])), None)
            if palier is None:
                evaluees.append(f"{texte} : {_fmt(v[0], unite)}, sous les seuils")
                continue
            points += palier[2]
            appliquees.append({"regle": f"{texte} {SYMBOLES.get(palier[0], palier[0])} {_fmt(palier[1], unite).lstrip('+')} → {_pts(palier[2])}",
                               "chiffre": _fmt(v[0], unite), "source": v[1], "date": v[2], "points": palier[2]})
            continue
        concernees = {d for c in r.get("cas") or [] for d in (c.get("effets") or {})}
        if devise not in concernees:
            continue
        if valeur is None or isinstance(valeur, dict):
            manquantes.append(f"{texte} : donnée indisponible")
            continue
        cas = next((c for c in r.get("cas") or [] if _verifie(c["si"], valeur[0])), None)
        if len(valeur) > 3 and valeur[3] and "heurt" in str(valeur[3]):
            if (cas or {}).get("effets", {}).get(devise):   # aurait déclenché : neutralisation visible
                neutralisees.append(f"{texte} : {_fmt(valeur[0], unite)}, {TEXTE_NEUTRALISE} ({valeur[3]})")
            else:
                evaluees.append(f"{texte} : {_fmt(valeur[0], unite)}, sous les seuils (série heurtée)")
            continue
        pts = (cas or {}).get("effets", {}).get(devise)
        if not pts:
            evaluees.append(f"{texte} : {_fmt(valeur[0], unite)}, aucun effet sur {devise}")
            continue
        points += pts
        appliquees.append({"regle": f"{texte} {SYMBOLES.get(cas['si'][0], cas['si'][0])} {_fmt(cas['si'][1], unite).lstrip('+')} → {_pts(pts)} pour {devise}",
                           "chiffre": _fmt(valeur[0], unite), "source": valeur[1], "date": valeur[2], "points": pts})
    # Couverture par devise (config.yaml, matrice_impact.couverture) : signe classique confirmé sur 5 ans
    for r in couv or []:
        d = (r.get("devises") or {}).get(devise)
        if d is None or _deja_couverte(liste, r.get("indicateur"), devise):
            continue
        texte, unite = r.get("texte"), r.get("unite")
        if r.get("raison"):
            manquantes.append(f"{texte} : {r['raison']}")
            continue
        if not d["haut"]["confirmee"] and not d["bas"]["confirmee"]:
            non_confirmees.append(f"{texte} : règle classique non confirmée sur 5 ans ({d['haut']['raison']})")
            continue
        direction = r.get("direction")
        seuils = f"seuils {couverture.fmt(r.get('seuil_bas'), unite)} / {couverture.fmt(r.get('seuil_haut'), unite)}"
        if direction is None:
            evaluees.append(f"{texte} : {couverture.fmt(r.get('valeur'), unite)}, dans le couloir ({seuils})")
            continue
        conf = d[direction]
        if not conf["confirmee"]:
            evaluees.append(f"{texte} : {couverture.fmt(r.get('valeur'), unite)}, seuil {('haut' if direction == 'haut' else 'bas')} "
                            f"franchi mais sens non confirmé ({conf['raison']})")
            continue
        if r.get("neutralise"):
            neutralisees.append(f"{texte} : {couverture.fmt(r.get('valeur'), unite)}, {TEXTE_NEUTRALISE} ({r.get('serie_heurtee')})")
            continue
        pts = d["signe_classique"] * (1 if direction == "haut" else -1)
        points += pts
        seuil = r.get("seuil_haut") if direction == "haut" else r.get("seuil_bas")
        appliquees.append({"regle": f"{texte} {'≥' if direction == 'haut' else '≤'} {couverture.fmt(seuil, unite).lstrip('+')} "
                                    f"({r.get('declencheur')}) → {_pts(pts)} pour {devise} ; {conf['raison']}",
                           "chiffre": couverture.fmt(r.get("valeur"), unite), "source": r.get("source"), "date": r.get("date"),
                           "points": pts, "couverture": True})
    borne = max(-2, min(2, points))
    if appliquees:
        etat, raison = "active", None
    elif neutralisees:
        etat, raison = "neutralise", "; ".join(neutralisees + evaluees)
    elif evaluees:
        etat, raison = "neutre", "; ".join(evaluees + manquantes)
    elif manquantes:
        etat, raison = "nd", "; ".join(manquantes)
    else:
        etat = "sans_regle"
        raison = "; ".join(non_confirmees) if non_confirmees else (
            "aucune règle définie pour cet engrenage (config.yaml)" if not liste and not couv else
            f"aucune règle de cet engrenage ne concerne {devise}")
    case = {"engrenage": n, "valeur": borne, "libelle": LIBELLES[borne] if etat == "active" else LIBELLES_ETAT[etat],
            "regles": appliquees, "raison": raison, "bornee": borne != points, "etat": etat}
    if etat == "neutralise":
        case["neutralisation"] = "; ".join(neutralisees)
    return case


def matrice(cfg: dict, sig: dict, couv: dict, theme_fort: bool, coh_libelle: str | None) -> dict:
    regles = cfg.get("regles") or {}
    seuils = cfg.get("bilan") or {"soutenue": 3, "pression": -3}
    lignes = []
    for devise in DEVISES:
        cases = [_case(devise, n, regles.get(str(n)) or [], sig, theme_fort, coh_libelle, (couv or {}).get(str(n)) or [])
                 for n in range(1, 9)]
        total = sum(c["valeur"] for c in cases)
        lignes.append({"devise": devise, "cases": cases, "bilan": total,
                       "lecture": "soutenue" if total >= seuils["soutenue"] else "sous pression" if total <= seuils["pression"] else "neutre",
                       "incompletes": sum(1 for c in cases if c["etat"] == "nd")})
    comptes = {e: sum(1 for l in lignes for c in l["cases"] if c["etat"] == e) for e in ETATS}
    return {"lignes": lignes, "comptes": comptes, "cases_actives": comptes["active"], "cases_total": len(lignes) * 8,
            "compte_libelle": f"{comptes['active']} actives, {comptes['nd']} n/d, {comptes['sans_regle']} sans règle"
                              + (f", {comptes['neutralise']} {'neutralisée' if comptes['neutralise'] < 2 else 'neutralisées'}" if comptes["neutralise"] else ""),
            "seuils_bilan": seuils}


def calculer(config: dict, engrenages: dict, vue: dict | None, historiques: dict | None = None,
             impact: dict | None = None) -> dict:
    cfg = (config or {}).get("matrice_impact") or {}
    sig = signaux(engrenages, vue)
    theme_fort, coh_libelle, _ = sig.get("_theme_fort", (False, None, None))
    couv = couverture.evaluer(config, historiques, impact) if historiques is not None else {}
    sortie = matrice(cfg, sig, couv, theme_fort, coh_libelle)
    sortie.update({"theme_fort": theme_fort, "couverture": couv, "signaux_valeurs": {k: v for k, v in sig.items() if not k.startswith("_")},
                   "legende": "▲▲ soutien fort (+2) · ▲ soutien (+1) · · neutre : règle évaluée, non déclenchée · hachures : n/d, donnée "
                              "absente · gris très clair : sans règle · ▼ pression (−1) · ▼▼ pression forte (−2). Chaque case applique une "
                              "règle écrite dans config.yaml au chiffre du jour ; bilan = somme des 8 cases "
                              f"(soutenue ≥ {(cfg.get('bilan') or {}).get('soutenue', 3)}, sous pression ≤ {(cfg.get('bilan') or {}).get('pression', -3)}). "
                              "Aide à la lecture, jamais une recommandation d'achat ou de vente."})
    return sortie
