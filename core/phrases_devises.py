"""« Pourquoi » des cartes de devises en phrases (lot V15, E2).

La matrice d'impact explique chaque effet par une règle brute (« Brent, variation sur 4 semaines ≤ −10,00 % → +1 pour
JPY »). Ici, chaque règle devient une phrase compréhensible sans être économiste : le fait, puis ce qu'il change pour la
devise. La règle brute reste disponible à l'écran dans le détail repliable « Règle de calcul ».
Tout est calculé en Python à partir du texte de la règle et de son chiffre (aucun modèle).
"""
from __future__ import annotations

import re

NOMS = {"USD": "le dollar américain", "EUR": "l'euro", "GBP": "la livre sterling", "JPY": "le yen", "CHF": "le franc suisse",
        "CAD": "le dollar canadien", "AUD": "le dollar australien", "NZD": "le dollar néo-zélandais", "CNY": "le yuan"}
PAYS = {"USD": "les États-Unis", "EUR": "la zone euro", "GBP": "le Royaume-Uni", "JPY": "le Japon", "CHF": "la Suisse",
        "CAD": "le Canada", "AUD": "l'Australie", "NZD": "la Nouvelle-Zélande", "CNY": "la Chine"}
IMPORTATEURS = {"JPY", "EUR", "CHF", "CNY"}


def _num(chiffre) -> float | None:
    m = re.search(r"[+−-]?\d+(?:[.,]\d+)?", str(chiffre or "").replace(" ", "").replace(" ", ""))
    if not m:
        return None
    return float(m.group().replace("−", "-").replace(",", "."))


def _f(v: float | None, d: int = 2) -> str:
    if v is None:
        return "n/d"
    t = f"{abs(v):.{d}f}".replace(".", ",")
    return t


def _effet(regle: str, devise: str) -> int:
    m = re.search(r"→\s*([+−-]\d)", regle or "")
    return int(m.group(1).replace("−", "-")) if m else 0


def phrase(devise: str, regle: str, chiffre, effet: int | None = None) -> str:
    """Une règle de la matrice -> une phrase. effet : +1/+2 soutien, −1/−2 pression (lu dans la règle si absent)."""
    d, nom = devise, NOMS.get(devise, devise)
    e = effet if effet is not None else _effet(regle, devise)
    soutien = e > 0
    v = _num(chiffre)
    r = (regle or "").lower()
    va = abs(v) if v is not None else None
    if "régime de risque" in r:
        peur = "risk_off" in str(chiffre)
        if peur:
            return (f"La peur domine les marchés : les investisseurs cherchent les valeurs refuges, ce qui soutient {nom}." if soutien else
                    f"La peur domine les marchés : les investisseurs vendent les devises jugées risquées, dont {nom}.")
        return (f"Les investisseurs reprennent confiance et prennent du risque, ce qui profite à {nom}." if soutien else
                f"Les investisseurs reprennent confiance et délaissent les valeurs refuges, dont {nom}.")
    if "direction du dollar dans le thème" in r:
        return (f"La plupart des moteurs poussent le dollar à la hausse cette semaine : l'humeur générale le soutient." if d == "USD" and soutien else
                f"La plupart des moteurs poussent le dollar à la hausse cette semaine, ce qui pèse sur {nom}." if not soutien else
                f"Le thème général de la semaine profite à {nom}.")
    if "écart de taux 2 ans face aux états-unis" in r:
        sens = "s'est élargi" if v is not None and v > 0 else "s'est réduit"
        return (f"L'écart de taux à 2 ans entre {PAYS.get(d, d)} et les États-Unis {sens} de {_f(va, 0)} pb en 4 semaines : "
                + (f"placer en {nom.split(' ', 1)[-1]} rapporte un peu plus par rapport au dollar, ce qui le soutient." if soutien else
                   f"placer en {nom.split(' ', 1)[-1]} rapporte un peu moins par rapport au dollar, ce qui lui retire un soutien."))
    if "rendement 2 ans us" in r:
        sens = "monté" if v is not None and v > 0 else "baissé"
        return (f"Le taux à 2 ans américain a {sens} de {_f(va, 0)} pb en 4 semaines : le marché attend une Fed "
                + ("plus sévère, ce qui rend le dollar plus attractif" if v and v > 0 else "moins sévère, ce qui rend le dollar moins attractif")
                + (f", et soutient {nom}." if soutien else f", et pèse sur {nom}."))
    if "surprise macro" in r:
        return (f"Sur 30 jours, les chiffres économiques {'battent' if v and v > 0 else 'déçoivent'} les prévisions (indice "
                f"{'+' if v and v > 0 else '−'}{_f(va, 2)}) : la banque centrale a {'moins' if v and v > 0 else 'plus'} de raisons de baisser ses taux, "
                f"ce qui {'soutient' if soutien else 'pèse sur'} {nom}.")
    if "prime de terme" in r:
        return (f"Les prêteurs exigent {'davantage' if v and v > 0 else 'moins'} pour prêter 10 ans à l'État américain ({_f(va, 0)} pb en 4 semaines) : "
                + ("le doute sur les finances publiques " if v and v > 0 else "la confiance dans les finances publiques ")
                + ("soutient " if soutien else "pèse sur ") + nom + ".")
    if "italie − allemagne" in r or "italie - allemagne" in r:
        return (f"L'écart de taux entre l'Italie et l'Allemagne s'est {'creusé' if v and v > 0 else 'réduit'} de {_f(va, 0)} pb en 3 mois : "
                + ("les investisseurs doutent davantage des finances italiennes, ce qui pèse sur l'euro." if not soutien else
                   "la confiance dans la zone euro s'améliore, ce qui soutient l'euro."))
    if "niveau du vix" in r:
        return (f"La peur sur la Bourse américaine est forte (VIX à {_f(va, 2)}, au-dessus de 25) : les investisseurs se réfugient dans {nom}." if soutien else
                f"La peur sur la Bourse américaine est forte (VIX à {_f(va, 2)}) : les investisseurs vendent {nom}, jugé plus risqué.")
    if "s&p 500" in r:
        baisse = v is not None and v < 0
        return (f"La Bourse américaine a {'perdu' if baisse else 'gagné'} {_f(va, 2)} % en 4 semaines : "
                + (f"quand les actions baissent, les investisseurs se replient vers {nom}." if baisse and soutien else
                   f"quand les actions baissent, les devises liées à la croissance comme {nom} sont vendues." if baisse else
                   f"quand les actions montent, les investisseurs reprennent du risque, ce qui {'profite à' if soutien else 'pèse sur'} {nom}."))
    if "refuge (conflits)" in r:
        return (f"{_f(va, 0)} titres du jour parlent de conflits : ce climat pousse vers les valeurs refuges, ce qui "
                f"{'soutient' if soutien else 'pèse sur'} {nom}.")
    if "« énergie »" in r:
        return (f"{_f(va, 0)} titres du jour parlent d'énergie : le risque sur le pétrole {'soutient' if soutien else 'pèse sur'} {nom}.")
    if "moyenne mobile 200" in r:
        dessus = v is not None and v > 0
        return (f"{nom[0].upper() + nom[1:]} évolue {_f(va, 2)} % {'au-dessus' if dessus else 'en dessous'} de sa moyenne des 200 derniers jours : "
                f"la tendance de fond est {'haussière' if dessus else 'baissière'}.")
    if "cot" in r:
        acheteurs = v is not None and v >= 50
        return ((f"Les spéculateurs ont presque tous parié sur la hausse de {nom} : il reste peu d'acheteurs, et une mauvaise surprise "
                 f"pourrait déclencher des ventes en cascade.") if acheteurs else
                (f"Les spéculateurs ont presque tous parié contre {nom} : au moindre bon chiffre, ils pourraient devoir racheter, "
                 f"ce qui le soutiendrait."))
    if "brent" in r:
        baisse = v is not None and v < 0
        if d == "CAD":
            return (f"Le Brent a {'perdu' if baisse else 'gagné'} {_f(va, 2)} % en 4 semaines : le Canada, exportateur de pétrole, "
                    f"{'gagne moins' if baisse else 'gagne davantage'}, ce qui {'pèse sur' if not soutien else 'soutient'} le dollar canadien.")
        if d in IMPORTATEURS:
            return (f"Le Brent a {'perdu' if baisse else 'gagné'} {_f(va, 2)} % en 4 semaines : {PAYS.get(d, d)}, qui importe son énergie, "
                    f"paie {'moins' if baisse else 'plus'} cher son pétrole, ce qui {'soutient' if soutien else 'pèse sur'} {nom}.")
        return f"Le Brent a {'perdu' if baisse else 'gagné'} {_f(va, 2)} % en 4 semaines, ce qui {'soutient' if soutien else 'pèse sur'} {nom}."
    if "stocks de brut" in r:
        return (f"Les stocks de pétrole américains sont {_f(va, 1)} % {'au-dessus' if v and v > 0 else 'en dessous'} de leur moyenne de 5 ans : "
                f"cela {'pèse sur' if v and v > 0 else 'soutient'} le prix du baril, ce qui {'soutient' if soutien else 'pèse sur'} {nom}.")
    if "10 ans us" in r:
        return (f"Le taux à 10 ans américain a {'monté' if v and v > 0 else 'baissé'} en 4 semaines ({_f(va, 0)} pb), ce qui "
                f"{'soutient' if soutien else 'pèse sur'} {nom}.")
    if "indice dollar large" in r:
        return (f"Le dollar a {'gagné' if v and v > 0 else 'perdu'} {_f(va, 2)} % en 4 semaines face aux grandes devises : "
                + ("sa force pèse sur " + nom + "." if not soutien else ("il est porté par cette tendance." if d == "USD" else "cela profite à " + nom + ".")))
    if "indice or" in r:
        return (f"L'or a {'gagné' if v and v > 0 else 'perdu'} {_f(va, 2)} % en 4 semaines : "
                + ("la recherche de protection " if v and v > 0 else "le moindre besoin de protection ")
                + ("soutient " if soutien else "pèse sur ") + nom + ".")
    # règle inconnue : une phrase générique, la règle brute restant dans « Règle de calcul »
    sujet = re.split(r"\s*[≤≥=]", regle or "")[0].strip()
    return f"{sujet[:1].upper() + sujet[1:]} ({chiffre}) : {'un soutien' if soutien else 'une pression'} pour {nom}."


def _contracter(t: str) -> str:
    return t.replace(" de le ", " du ").replace(" de les ", " des ").replace(" à le ", " au ").replace(" à les ", " aux ")


def phrases_case(devise: str, regles: list[dict]) -> str | None:
    """Toutes les règles d'une case de la matrice -> une ou deux phrases (les règles les plus fortes d'abord)."""
    if not regles:
        return None
    rs = sorted(regles, key=lambda r: -abs(_effet(r.get("regle"), devise)))[:2]
    return _contracter(" ".join(phrase(devise, r.get("regle") or "", r.get("chiffre")) for r in rs))
