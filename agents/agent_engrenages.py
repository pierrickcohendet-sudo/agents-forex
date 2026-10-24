"""Synthèse globale « 8 engrenages » — version quotidienne compacte (UN appel LLM).

Répartition des rôles (règles du projet) :
- PYTHON calcule, quand les données le permettent, la direction de chaque engrenage (dollar,
  risque global) et son niveau de conviction, détecte les engrenages en conflit et choisit le
  concept du jour (rotation sans répétition sur un cycle complet, priorité à l'actualité) ;
- le LLM formule : diagnostic, nuance de la direction, 📘 Comprendre, 🎯 Ce que regarde un desk,
  chaînes de transmission, description des conflits, concept du jour illustré par les données.
Une direction calculée n'est jamais remplacée par celle du LLM (un désaccord est signalé).
Un engrenage sans donnée : « Données insuffisantes aujourd'hui. », jamais de texte générique.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

from agents.agent_synthese import _Catalogue, _ids, _norm, _retirer_ordres, _texte
from core import indicateurs, vue_ensemble
from core.llm import (MESSAGE_QUOTA_ATTEINT, FournisseurLLM, QuotaAtteint, attribution_modele,
                      definir_etiquette, extraire_json, repli_modele_suivant)
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

RACINE = Path(__file__).resolve().parent.parent
FICHIER_CADRE = RACINE / "connaissances" / "engrenages" / "cadre_engrenages.md"
FICHIER_CONCEPTS = RACINE / "connaissances" / "concepts_formation.md"

ENGRENAGES = [
    (1, "theme", "Thème macro"), (2, "politique_monetaire", "Politique monétaire"),
    (3, "donnees", "Données économiques"), (4, "fiscale", "Politique fiscale"),
    (5, "interconnexions", "Interconnexions de marchés"), (6, "geopolitique", "Géopolitique"),
    (7, "price_action", "Price action et flux"), (8, "offre_demande", "Offre et demande"),
]
NOMS = {n: nom for n, _, nom in ENGRENAGES}
DIRECTIONS_DOLLAR = ("haussier", "baissier", "neutre")
DIRECTIONS_RISQUE = ("risk_on", "risk_off", "neutre")
CONVICTIONS = ("faible", "moyen", "eleve")
TEXTE_INSUFFISANT = "Données insuffisantes aujourd'hui."
RISQUE, REFUGE = ("AUD", "NZD", "CAD"), ("JPY", "CHF")
SANS_REGLE = (4, 6, 8)   # engrenages dont la direction dollar vient de la case USD de la matrice d'impact
MATRICE_RISQUE = (6,)    # risque tiré de la matrice : canal « refuge » de la géopolitique seulement
TEXTE_QUOTA = "Texte indisponible : quota du jour atteint"
TEXTE_ECHEC = "Texte indisponible : réponse du modèle inexploitable"
MIN_ENGRENAGES_REPONSE = 6
# Seuils des règles de direction (une seule définition : signaux, cockpit, radar et « Et si »).
SEUILS = {"us2a_pb": 10, "surprise": 0.3, "vix_risk_off": 25, "vix_risk_on": 14, "dollar_large_pct": 0.5,
          "usd_5j_pct": 0.3, "risque_refuge_pt": 0.3}


def _mesure(libelle: str, valeur, unite: str, bas, haut, date_: str | None, source: str | None,
            dir_haut: str, dir_bas: str, raison: str | None = None) -> dict:
    """Mesure qui décide la direction d'un engrenage, avec ses seuils (thermomètre du cockpit)."""
    return {"libelle": libelle, "valeur": valeur, "unite": unite, "seuil_bas": bas, "seuil_haut": haut, "date": date_,
            "source": source, "si_haut": dir_haut, "si_bas": dir_bas,
            "raison": None if valeur is not None else (raison or "donnée indisponible")}   # en dessous : réponse jugée incomplète, redemandée au modèle suivant

SCHEMA = """{
  "engrenages": [{"numero": 1-8,
                  "diagnostic": "2-3 phrases chiffrées, ou « Données insuffisantes aujourd'hui. »",
                  "direction": {"dollar": "haussier"|"baissier"|"neutre"|null,
                                "risque": "risk_on"|"risk_off"|"neutre"|null,
                                "devises_concernees": ["XXX"], "texte": "1 phrase"},
                  "comprendre": "2-3 phrases pédagogiques", "desk": "le signal précis et pourquoi",
                  "conviction": {"niveau": "faible"|"moyen"|"eleve", "justification": "1 phrase"},
                  "source_ids": ["src_NNN"]}],
  "chaines": [{"titre": "...", "maillons": [{"engrenage": 1-8, "texte": "...", "source_id": "src_NNN"}]}],
  "conflits": [{"engrenages": [n, m], "texte": "...", "source_ids": ["src_NNN"]}],
  "concept": {"explication": "2-3 phrases simples", "exemple": "exemple tiré des données du jour",
              "source_ids": ["src_NNN"]}
}"""


# ----------------------------------------------------------------- utilitaires
_RE_OR = re.compile(r"\b(?:le cours de l'or|le prix de l'or|du cours de l'or|du prix de l'or|l'or)\b(?! \(proxy\))",
                    re.IGNORECASE)


_RE_RECORD = re.compile(r"\b(records?)\b", re.IGNORECASE)
_REMPLACEMENTS_ENVOL = [
    (re.compile(r"\bs['’]est envol[ée]e?s?\b", re.IGNORECASE), "a progressé"),
    (re.compile(r"\bs['’]envolent\b", re.IGNORECASE), "progressent"),
    (re.compile(r"\bs['’]envol(?:e|ait|era)\b", re.IGNORECASE), "progresse"),
    (re.compile(r"\bl['’]envolée\b"), "la hausse"),
    (re.compile(r"\bL['’]envolée\b"), "La hausse"),
    (re.compile(r"\bune envolée\b", re.IGNORECASE), "une hausse"),
    (re.compile(r"\benvolées?\b", re.IGNORECASE), "hausse"),
]


def justifications(dossiers: dict | None) -> dict[int, dict[str, bool]]:
    """Par engrenage : « record » justifié si un indicateur est à un extrême sur 5 ans (percentile 0 ou
    100, ou 0/100 sur 52 semaines pour le COT) ; « s'envole » si une hausse d'au moins 10 % sur
    4 semaines existe sur une série non heurtée. Calcul sur les dossiers chiffrés (Python)."""
    resultat = {}
    for n, e in ((dossiers or {}).get("engrenages") or {}).items():
        cellules = [c for l in e.get("lignes", []) for c in (l.get("cellules") or {}).values() if isinstance(c, dict)]
        cellules += [i.get("cellule") or {} for i in e.get("instruments", [])]
        record = any(c.get("percentile_5a") in (0, 100) or c.get("percentile_52s") in (0, 100) for c in cellules)
        envol = any(c.get("var_4s") is not None and c.get("unite") not in ("%", "pb") and c["var_4s"] >= 10 and not c.get("alerte")
                    for c in cellules)
        resultat[int(n)] = {"record": record, "envol": envol}
    return resultat


def moderer_vocabulaire(texte: str, permis: dict[str, bool]) -> tuple[str, int]:
    """Remplace « record » et « s'envole » quand les chiffres ne le justifient pas. (texte, nb de remplacements)."""
    if not texte:
        return texte, 0
    n = 0
    if not permis.get("record"):
        texte, k = _RE_RECORD.subn(lambda m: "extrêmes" if m.group(1).lower().endswith("s") else "extrême", texte)
        n += k
    if not permis.get("envol"):
        for motif, rempl in _REMPLACEMENTS_ENVOL:
            texte, k = motif.subn(rempl, texte)
            n += k
    return texte, n


def nommer_or(texte: str) -> str:
    """Nous n'avons qu'un indice or : jamais « l'or » ni « le cours de l'or » dans un texte publié."""
    if not texte:
        return texte

    def remplacer(m):
        debut = m.start() == 0 or texte[:m.start()].rstrip()[-1:] in ".!?"
        return "L'indice or (proxy)" if debut else "l'indice or (proxy)"
    return _RE_OR.sub(remplacer, texte)
def _variation(serie: dict | None, jours: int = 7) -> tuple[float, float, str] | None:
    """(dernière valeur, variation en %, date) sur `jours` jours calendaires, depuis une série
    {dates, valeurs} (graphiques_marche)."""
    if not serie or len(serie.get("valeurs") or []) < 2:
        return None
    dates, valeurs = serie["dates"], serie["valeurs"]
    fin = date.fromisoformat(dates[-1])
    ref = None
    for d, v in zip(dates, valeurs):
        if (fin - date.fromisoformat(d)).days >= jours:
            ref = v
    if ref in (None, 0):
        return None
    return valeurs[-1], round((valeurs[-1] / ref - 1) * 100, 2), dates[-1]


def saut_atypique(serie: dict | None, seuil_pct: float = 8.0, n: int = 10) -> str | None:
    """« +18,0 % le 02/10 » si une variation journalière dépasse le seuil sur les n derniers points."""
    if not serie or len(serie.get("valeurs") or []) < 2:
        return None
    pires = []
    v, d = serie["valeurs"][-n - 1:], serie["dates"][-n - 1:]
    for i in range(1, len(v)):
        if v[i - 1]:
            pct = (v[i] / v[i - 1] - 1) * 100
            if abs(pct) >= seuil_pct:
                pires.append((abs(pct), f"{pct:+.1f} % le {d[i][8:10]}/{d[i][5:7]}".replace(".", ",")))
    return ", ".join(t for _, t in sorted(pires, reverse=True)[:2]) or None


def _dir(valeur: float | None, seuil: float, haut: str, bas: str) -> str | None:
    if valeur is None:
        return None
    return haut if valeur >= seuil else bas if valeur <= -seuil else "neutre"


def _force(valeur: float | None, seuil: float) -> int:
    """0 = sous le seuil, 1 = au-delà, 2 = au-delà du double."""
    if valeur is None:
        return 0
    return 2 if abs(valeur) >= 2 * seuil else 1 if abs(valeur) >= seuil else 0


def _nombre(texte) -> float | None:
    m = re.search(r"[+-]?\d+(?:[.,]\d+)?", str(texte or ""))
    return float(m.group(0).replace(",", ".")) if m else None


def _conviction(n_donnees: int, direction_definie: bool, force: int) -> str | None:
    """Niveau calculé : quantité de données + netteté du signal. None = données insuffisantes."""
    if n_donnees == 0:
        return None
    if n_donnees >= 3 and direction_definie and force >= 2:
        return "eleve"
    if n_donnees >= 2 and (direction_definie or force >= 1):
        return "moyen"
    return "faible"


# ------------------------------------------------------------ signaux Python

def _donnees_fiscales(dossiers: dict, cat: "_Catalogue") -> list[dict]:
    """Engrenage 4 : 10 ans (variation 4 semaines), prime de terme US et dette / PIB, repris du dossier."""
    e = ((dossiers or {}).get("engrenages") or {}).get("4") or {}
    sortie = []
    for ligne in e.get("lignes") or []:
        dev, cel = ligne.get("devise"), ligne.get("cellules") or {}
        morceaux, src, date_ = [], None, None
        t = cel.get("taux_10a") or {}
        if t.get("valeur") is not None:
            morceaux.append(f"10 ans {t['valeur']:.2f} %" + (f" ({t['var_4s']:+.0f} pb sur 4 semaines)"
                                                         if t.get("var_4s") is not None else ""))
            src, date_ = t.get("source"), t.get("date")
        pt = cel.get("prime_terme") or {}
        if pt.get("valeur") is not None:
            morceaux.append(f"prime de terme 10 ans {pt['valeur']:.2f} %")
        dp = cel.get("dette_pib") or {}
        if dp.get("valeur") is not None:
            morceaux.append(f"dette / PIB {dp['valeur']} % ({dp.get('date')})")
            src, date_ = src or dp.get("source"), date_ or dp.get("date")
        if morceaux:
            sortie.append({"texte": f"{dev} : " + ", ".join(morceaux),
                           "source_id": cat.src(src or "dossier des engrenages", f"{dev} — politique fiscale", date_)})
    return sortie


def _donnees_geopolitiques(dossiers: dict, cat: "_Catalogue") -> list[dict]:
    """Engrenage 6 : décompte des titres du jour par canal et 3 titres datés (dossier, sans LLM)."""
    e = ((dossiers or {}).get("engrenages") or {}).get("6") or {}
    sortie = []
    for g in e.get("graphiques") or []:
        if g.get("type") == "barres" and g.get("barres"):
            comptes = ", ".join(f"{b['nom']} {b['valeur']}" for b in g["barres"] if b.get("valeur"))
            if comptes:
                sortie.append({"texte": "Titres du jour par canal de transmission : " + comptes,
                               "source_id": cat.src("Calcul Python (fil d'actualité)", "titres classés par canal",
                                                    date.today().isoformat())})
    for ev in (e.get("evenements") or [])[:3]:
        sortie.append({"texte": f"{ev.get('titre')} — canal {ev.get('canal')} ({', '.join(ev.get('devises') or [])})",
                       "source_id": cat.src(ev.get("source") or "actualité", str(ev.get("titre"))[:80], ev.get("date"),
                                            ev.get("lien"))})
    return sortie


def imposer_signaux_mixtes(sortie: dict) -> None:
    """Cohérence calculée sous le seuil : titre « Signaux mixtes » imposé au thème global. Le filtre du
    vocabulaire de thème fort ne s'applique qu'au paragraphe du thème global (bandeau, core/vue_ensemble.py) :
    les analyses par engrenage, y compris celle de l'engrenage 1, restent telles que rédigées."""
    par_num = {e["numero"]: e for e in sortie.get("engrenages") or []}
    coh = vue_ensemble.coherence(par_num)
    sortie["coherence"] = {k: v for k, v in coh.items() if k != "detail"}
    if not coh["theme_fort"]:
        sortie["titre_theme_impose"] = vue_ensemble.TITRE_SIGNAUX_MIXTES


def signaux(config: dict, donnees: dict, macro: dict, devises: list[dict], biais: str | None,
            extras: dict, cat: _Catalogue) -> dict[int, dict]:
    """{numéro: {dollar, risque, devises, regle, donnees: [{texte, source_id}], conviction}}.
    dollar/risque = None quand aucune règle Python ne s'applique (le LLM propose alors)."""
    aujourdhui = date.today().isoformat()
    cfg_tm = config.get("tableau_macro") or {}
    libelles = {k: v.get("libelle", k) for k, v in (cfg_tm.get("indicateurs") or {}).items()}
    registre = (extras or {}).get("registre") or {}
    cases = registre.get("cases") or {}
    series = (donnees.get("macro") or {}).get("series") or {}
    technique = donnees.get("technique") or {}
    marche = (macro or {}).get("graphiques_marche") or {}
    flux = (macro or {}).get("flux") or {}
    erreurs_flux = " ; ".join(flux.get("erreurs") or [])
    scores = {d["devise"]: d.get("score_confluence") for d in devises}
    resultat: dict[int, dict] = {}

    def src_registre(devise: str, indicateur: str, actuel: dict) -> str:
        return cat.src(f"{actuel.get('source') or 'ForexFactory'} (registre macro)",
                       f"{devise} — {libelles.get(indicateur, indicateur)}",
                       actuel.get("date_pub") or actuel.get("periode"))

    # 1. Thème macro : résultante des engrenages 2 à 8 (complétée plus bas, voir _theme_python). Les scores de
    # confluence (rédigés avec le modèle) ne décident plus de la direction : ils restent une donnée affichée.
    id_scores = cat.src("Calcul Python", "scores de confluence et biais global du jour", aujourdhui)
    classes = sorted([(s, d) for d, s in scores.items() if s is not None], reverse=True)
    resultat[1] = {
        "dollar": None, "risque": None,
        "devises": list(dict.fromkeys([d for _, d in classes[:2]] + [d for _, d in classes[-2:]])),
        "regle": "",
        "donnees": [{"texte": f"Biais global {biais} ; classement : " +
                     ", ".join(f"{d} {s}" for s, d in classes), "source_id": id_scores}] if classes else [],
        "force": 0,
    }

    # 2. Politique monétaire : dernières décisions + taux 2 ans US (anticipations)
    donnees2, decisions = [], []
    for devise in config.get("devises", {}):
        case = cases.get(f"{devise}|taux_directeur") or {}
        actuel, prec = case.get("actuel") or {}, case.get("precedent") or {}
        a, p = _nombre(actuel.get("valeur")), _nombre(prec.get("valeur"))
        if a is None:
            continue
        sens = None if p is None else ("hausse" if a > p else "baisse" if a < p else "statu quo")
        decisions.append((devise, sens))
        donnees2.append({"texte": f"{devise} taux directeur {actuel.get('valeur')} le {actuel.get('date_pub')}"
                                  + (f" ({sens}, précédent {prec.get('valeur')})" if sens else ""),
                         "source_id": src_registre(devise, "taux_directeur", actuel)})
    us2 = cases.get("USD|rendement_2a") or {}
    var2 = us2.get("variation_pb")
    if var2 is not None and (us2.get("actuel") or {}).get("valeur"):
        donnees2.append({"texte": f"Rendement US 2 ans {us2['actuel']['valeur']} ({var2:+.0f} pb sur une semaine)",
                         "source_id": src_registre("USD", "rendement_2a", us2["actuel"])})
    k2 = SEUILS["us2a_pb"]
    resultat[2] = {"dollar": _dir(var2, k2, "haussier", "baissier"), "risque": None,
                   "devises": [d for d, s in decisions if s in ("hausse", "baisse")],
                   "regle": f"dollar : variation hebdomadaire du 2 ans US (≥ +{k2} pb haussier, ≤ -{k2} pb baissier)",
                   "donnees": donnees2, "force": _force(var2, k2),
                   "mesure": _mesure("2 ans US sur 7 j", var2, "pb", -k2, k2, (us2.get("actuel") or {}).get("date_pub"),
                                     (us2.get("actuel") or {}).get("source") or "registre macro", "Dollar haussier", "Dollar baissier",
                                     "variation du 2 ans US absente du registre")}

    # 3. Données économiques : indice de surprise 30 j
    indices = (extras or {}).get("indice_surprise") or {}
    id_ind = cat.src("Calcul Python (registre macro)", "indice de surprise macro 30 jours par devise", aujourdhui)
    vals = {d: v.get("indice") for d, v in indices.items() if isinstance(v, dict) and v.get("indice") is not None}
    i_usd = vals.get("USD")
    k3 = SEUILS["surprise"]
    resultat[3] = {"dollar": _dir(i_usd, k3, "haussier", "baissier"), "risque": None,
                   "devises": [d for d, v in sorted(vals.items(), key=lambda kv: -abs(kv[1]))[:3]],
                   "regle": f"dollar : indice de surprise 30 j de l'USD (≥ +{k3} haussier, ≤ -{k3} baissier)".replace(".", ","),
                   "donnees": [{"texte": "Indice de surprise 30 j : " + ", ".join(f"{d} {v:+.2f}" for d, v in vals.items()),
                                "source_id": id_ind}] if vals else [],
                   "force": _force(i_usd, k3),
                   "mesure": _mesure("surprise USD 30 j", i_usd, "écarts", -k3, k3, aujourdhui, "calcul Python (registre macro)",
                                     "Dollar haussier", "Dollar baissier", "indice de surprise USD indisponible")}

    # 4. Politique fiscale : pas de règle de direction, mais les chiffres du dossier (10 ans, prime de
    # terme, dette / PIB) sont fournis au modèle — jamais une entrée vide quand le dossier en a.
    dossiers = (extras or {}).get("dossiers") or {}
    resultat[4] = {"dollar": None, "risque": None, "devises": [], "donnees": _donnees_fiscales(dossiers, cat),
                   "force": 0,
                   "regle": "aucune règle chiffrée : lecture de l'actualité par le LLM (conviction plafonnée à « moyen »)"}

    # 5. Interconnexions : VIX (risque), indice dollar large (dollar), S&P 500
    donnees5 = []
    vix = series.get("vix") or {}
    v_vix = _variation(marche.get("vix"))
    if vix.get("valeur") is not None:
        donnees5.append({"texte": f"VIX {vix['valeur']} le {vix.get('date')}"
                         + (f" ({v_vix[1]:+.1f} % sur 7 j)" if v_vix else ""), "source_id": vix.get("source_id"),
                         "indicateur": "vix", "valeur": vix["valeur"], "date": vix.get("date")})
    risque5 = None
    if vix.get("valeur") is not None:
        niveau = float(vix["valeur"])
        risque5 = "risk_off" if niveau >= SEUILS["vix_risk_off"] or (v_vix and v_vix[1] >= 25) else \
                  "risk_on" if niveau <= SEUILS["vix_risk_on"] and not (v_vix and v_vix[1] >= 10) else "neutre"
    v_dollar = _variation(marche.get("dollar_large"))
    if v_dollar:
        donnees5.append({"texte": f"Indice dollar large (Fed) {v_dollar[0]} le {v_dollar[2]} ({v_dollar[1]:+.2f} % sur 7 j)",
                         "source_id": cat.src("FRED", "indice dollar large (DTWEXBGS)", v_dollar[2]),
                         "indicateur": "dollar_large", "valeur": v_dollar[0], "date": v_dollar[2]})
    sp = series.get("sp500") or {}
    if sp.get("valeur") is not None:
        donnees5.append({"texte": f"S&P 500 {sp['valeur']} le {sp.get('date')} ({sp.get('variation_pct'):+.2f} % sur la séance)"
                         if sp.get("variation_pct") is not None else f"S&P 500 {sp['valeur']} le {sp.get('date')}",
                         "source_id": sp.get("source_id"), "indicateur": "sp500", "valeur": sp["valeur"], "date": sp.get("date")})
    indisponibles5 = []
    or_ = flux.get("or")
    if or_:
        donnees5.append({"texte": f"{or_['libelle']} : {or_['valeur']} le {or_['date']}"
                                  + (f" ({or_['variation_7j_pct']:+.2f} % sur 7 j)" if or_.get("variation_7j_pct") is not None else ""),
                         "source_id": cat.src("FRED", f"{or_['libelle']} ({or_['serie']})", or_["date"])})
    else:
        indisponibles5.append("indice or (FRED) : " + (erreurs_flux or "non collecté aujourd'hui"))
    yc = (donnees.get("macro") or {}).get("yield_curve") or {}
    if yc.get("disponible") and yc.get("spread_10y_2y") is not None:
        donnees5.append({"texte": f"Courbe US 10 ans - 2 ans : {yc['spread_10y_2y']:+.2f} pt le {yc.get('date')} "
                                  f"({yc.get('regime', '')} : {yc.get('lecture', '')})",
                         "source_id": yc.get("source_id")})
    resultat[5] = {"dollar": _dir(v_dollar[1] if v_dollar else None, SEUILS["dollar_large_pct"], "haussier", "baissier"),
                   "mesure": _mesure("VIX", vix.get("valeur"), "pts", SEUILS["vix_risk_on"], SEUILS["vix_risk_off"], vix.get("date"),
                                     vix.get("source") or "FRED (VIXCLS)", "Risk off", "Risk on", "VIX indisponible"),
                   "risque": risque5, "devises": ["JPY", "CHF", "AUD"] if risque5 in ("risk_on", "risk_off") else [],
                   "regle": "risque : VIX (≥ 25 ou +25 % sur 7 j : risk off ; ≤ 14 sans hausse : risk on) ; "
                            "dollar : indice dollar large Fed sur 7 j (±0,5 %)",
                   "donnees": donnees5, "indisponibles": indisponibles5, "force": max(_force(v_dollar[1] if v_dollar else None, 0.5),
                                                     2 if risque5 == "risk_off" and vix.get("valeur", 0) >= 30 else 1 if risque5 else 0)}

    # 6. Géopolitique : titres datés classés par canal de transmission (dossier, calcul Python)
    resultat[6] = {"dollar": None, "risque": None, "devises": [], "donnees": _donnees_geopolitiques(dossiers, cat),
                   "force": 0,
                   "regle": "aucune règle chiffrée : actualité avec mécanisme économique (conviction plafonnée à « moyen »)"}

    # 7. Price action : indice USD synthétique (5 j) et devises risque vs refuge
    donnees7 = []
    t_usd = technique.get("USD") or {}
    v_usd = t_usd.get("variation_5j_pct")
    if v_usd is not None:
        donnees7.append({"texte": f"Indice USD synthétique {v_usd:+.2f} % sur 5 j, RSI {t_usd.get('rsi')}, "
                                  f"tendance de fond {(t_usd.get('tendance_fond') or {}).get('sens')}",
                         "source_id": t_usd.get("source_id")})
    v_r = [technique[d]["variation_5j_pct"] for d in RISQUE if (technique.get(d) or {}).get("variation_5j_pct") is not None]
    v_f = [technique[d]["variation_5j_pct"] for d in REFUGE if (technique.get(d) or {}).get("variation_5j_pct") is not None]
    ecart = round(sum(v_r) / len(v_r) - sum(v_f) / len(v_f), 2) if v_r and v_f else None
    if ecart is not None:
        donnees7.append({"texte": "Variation 5 j (force de la devise) : " + ", ".join(
            f"{d} {technique[d]['variation_5j_pct']:+.2f} %" for d in RISQUE + REFUGE if (technique.get(d) or {}).get("variation_5j_pct") is not None)
            + f" ; écart risque - refuge {ecart:+.2f} pt",
            "source_id": (technique.get("AUD") or technique.get("JPY") or {}).get("source_id")})
    cot = flux.get("cot") or {}
    indisponibles7 = [] if cot else ["positionnement CFTC (COT) : " + (erreurs_flux or "non collecté aujourd'hui")]
    extremes = []
    if cot:
        id_cot = cat.src("CFTC (Commitments of Traders, legacy futures only)",
                         "positions nettes non commerciales (spéculateurs)", max(v["date"] for v in cot.values()))
        lignes = []
        for d, v in cot.items():
            lignes.append(f"{d} net {v['net']:+,} ({v['variation_semaine']:+,} sur la semaine)".replace(",", " ")
                          + (f", percentile 52 s {v['percentile_52s']}" if v.get("percentile_52s") is not None else ""))
            if v.get("extreme"):
                extremes.append(f"{d} ({'long' if v['extreme'] == 'long' else 'short'} extrême)")
        donnees7.append({"texte": "COT CFTC, spéculateurs (positions du " + max(v["date"] for v in cot.values()) + ") : "
                                  + " ; ".join(lignes) + ". Non couvert : CNY.", "source_id": id_cot})
        if extremes:
            donnees7.append({"texte": "Positionnement extrême (≥ 90e ou ≤ 10e percentile sur 52 semaines) : "
                                      + ", ".join(extremes) + " — risque de retournement si le flux s'inverse.",
                             "source_id": id_cot})
    k7 = SEUILS["usd_5j_pct"]
    resultat[7] = {"dollar": _dir(v_usd, k7, "haussier", "baissier"), "risque": _dir(ecart, SEUILS["risque_refuge_pt"], "risk_on", "risk_off"),
                   "mesure": _mesure("indice USD synthétique, 5 j", v_usd, "%", -k7, k7, t_usd.get("date") or aujourdhui,
                                     "calcul local (Twelve Data, série unique)", "Dollar haussier", "Dollar baissier",
                                     "variation 5 j de l'indice USD indisponible"),
                   "devises": [d for d in RISQUE + REFUGE if abs((technique.get(d) or {}).get("variation_5j_pct") or 0) >= 0.5],
                   "regle": "dollar : indice USD synthétique sur 5 j (±0,3 %) ; risque : devises risque vs refuge sur 5 j (±0,3 pt) ; "
                            "COT : positionnement décrit, extrêmes signalés (pas de direction tirée du COT seul)",
                   "donnees": donnees7, "indisponibles": indisponibles7, "force": max(_force(v_usd, 0.3), _force(ecart, 0.3))}

    # 8. Offre et demande : pétrole (7 j) et balances commerciales
    donnees8 = []
    v_wti = _variation(marche.get("wti"))
    if v_wti:
        saut = saut_atypique(marche.get("wti"))
        neutralise = bool(saut) and abs(v_wti[1]) >= 3
        donnees8.append({"texte": f"WTI {v_wti[0]} $ le {v_wti[2]} ({v_wti[1]:+.1f} % sur 7 j)"
                                  + (f" — {indicateurs.TEXTE_NEUTRALISE} ({saut} en une séance)" if neutralise else
                                     f" — série heurtée ({saut} en une séance)" if saut else ""),
                         "source_id": (series.get("petrole_wti") or {}).get("source_id"),
                         "indicateur": "wti", "valeur": v_wti[0], "date": v_wti[2], "neutralise": neutralise})
    v_brent = _variation(marche.get("brent"))
    if v_brent:
        saut = saut_atypique(marche.get("brent"))
        neutralise_b = bool(saut) and abs(v_brent[1]) >= 3
        donnees8.append({"texte": f"Brent {v_brent[0]} $ le {v_brent[2]} ({v_brent[1]:+.1f} % sur 7 j)"
                                  + (f" — {indicateurs.TEXTE_NEUTRALISE} ({saut} en une séance, chiffres EIA/FRED officiels)"
                                     if neutralise_b else
                                     f" — série heurtée ({saut} en une séance, chiffres EIA/FRED officiels) : "
                                     "variation sur 7 j à lire avec prudence" if saut else ""),
                         "source_id": (series.get("petrole_brent") or {}).get("source_id"),
                         "indicateur": "brent", "valeur": v_brent[0], "date": v_brent[2], "neutralise": neutralise_b})
    indisponibles8 = []
    eia = flux.get("eia")
    if eia:
        donnees8.append({"texte": f"{eia['libelle']} : {eia['valeur']} M barils au {eia['date']} "
                                  f"({eia['variation_semaine']:+.1f} M sur la semaine"
                                  + (f", {eia['variation_4_semaines']:+.1f} M sur 4 semaines)" if eia.get("variation_4_semaines") is not None else ")"),
                         "source_id": cat.src("EIA (Weekly Petroleum Status Report)", f"{eia['libelle']} ({eia['serie']})", eia["date"])})
    else:
        indisponibles8.append("stocks de pétrole EIA : " + (erreurs_flux or "non collectés aujourd'hui"))
    for devise in config.get("devises", {}):
        actuel = (cases.get(f"{devise}|balance_commerciale") or {}).get("actuel") or {}
        if actuel.get("valeur"):
            donnees8.append({"texte": f"{devise} balance commerciale {actuel['valeur']} ({actuel.get('date_pub') or actuel.get('periode')})",
                             "source_id": src_registre(devise, "balance_commerciale", actuel)})
    resultat[8] = {"dollar": None, "risque": None,
                   "devises": ["CAD"] + (["NZD", "AUD"] if v_wti and abs(v_wti[1]) >= 3 else []),
                   "regle": "aucune direction dollar/risque calculée : pétrole (CAD), stocks EIA et balances commerciales décrits",
                   "donnees": donnees8, "indisponibles": indisponibles8,
                   "force": max(_force(v_wti[1] if v_wti and not any(d.get("neutralise") for d in donnees8 if d.get("indicateur") == "wti") else None, 3),
                                _force((eia or {}).get("variation_semaine"), 3))}

    _directions_matrice(resultat, dossiers)
    _theme_python(resultat, cat, aujourdhui)
    for n, s in resultat.items():
        s["donnees"] = [d for d in s["donnees"] if d.get("texte")]
        defini = s["dollar"] not in (None, "neutre") or s["risque"] not in (None, "neutre")
        s["conviction"] = _conviction(len(s["donnees"]), defini, s.pop("force", 0))
        if n in (4, 6) and s["conviction"] == "eleve":   # actualité et fiscalité : conviction plafonnée
            s["conviction"] = "moyen"

    # Thème : conviction = accord des autres engrenages avec la direction du thème (dollar et risque).
    theme = resultat[1]
    accords = desaccords = 0
    for n in (2, 3, 5, 7):
        for cle, oppose in (("dollar", {"haussier": "baissier", "baissier": "haussier"}),
                            ("risque", {"risk_on": "risk_off", "risk_off": "risk_on"})):
            ref, val = theme.get(cle), resultat[n].get(cle)
            if ref in oppose and val == ref:
                accords += 1
            elif ref in oppose and val == oppose[ref]:
                desaccords += 1
    theme["accord"] = {"accords": accords, "desaccords": desaccords}
    theme["conviction"] = None if not theme["donnees"] else (
        "eleve" if accords >= 3 and desaccords == 0 else "moyen" if accords > desaccords else "faible")
    theme["regle"] += (f" ; conviction = accord des engrenages 2, 3, 5, 7 avec le thème "
                       f"({accords} accord(s), {desaccords} désaccord(s))")
    return resultat


def _directions_matrice(resultat: dict[int, dict], dossiers: dict) -> None:
    """Direction dollar des engrenages 4, 6 et 8 (et des autres quand leur règle manque de données) : case USD
    de la matrice d'impact (core/matrice_impact.py, règles de config.yaml). Engrenage 6 : risque tiré des cases
    refuge (JPY, CHF) contre risque (AUD, NZD, CAD). Une case sans règle appliquée mais avec des données du
    jour vaut « neutre » pour 4, 6 et 8 ; sans matrice, la direction reste non déterminée (jamais devinée)."""
    mat = (dossiers or {}).get("matrice_impact") or {}
    cases = {l["devise"]: {c["engrenage"]: c for c in l.get("cases") or []} for l in mat.get("lignes") or []}
    usd = cases.get("USD")
    for n in range(2, 9):
        s = resultat[n]
        if not usd:
            if n in SANS_REGLE:
                s["regle"] = "matrice d'impact indisponible aujourd'hui : direction non calculée"
            continue
        case = usd.get(n) or {}
        if s["dollar"] is None:
            v = case.get("valeur") or 0
            if case.get("regles"):
                s["dollar"] = "haussier" if v > 0 else "baissier" if v < 0 else "neutre"
            elif n in SANS_REGLE and s["donnees"]:
                s["dollar"] = "neutre"
            if s["dollar"] is not None:
                detail = "; ".join(r["regle"] for r in case.get("regles") or []) or case.get("raison") or "aucune règle déclenchée"
                s["force"] = max(s.get("force", 0), min(abs(v), 2))
                s["regle"] = (s["regle"] + " ; " if n not in SANS_REGLE else "") + \
                    f"dollar : case USD de la matrice d'impact ({case.get('libelle', 'Neutre')} : {detail})"
        if n in MATRICE_RISQUE and s["risque"] is None:
            ecart = sum(((cases.get(d) or {}).get(n) or {}).get("valeur") or 0 for d in RISQUE) - \
                sum(((cases.get(d) or {}).get(n) or {}).get("valeur") or 0 for d in REFUGE)
            if ecart:
                s["risque"] = "risk_on" if ecart > 0 else "risk_off"
                s["regle"] += f" ; risque : matrice d'impact, devises risque − refuge = {ecart:+d}"
        if n in SANS_REGLE:
            s["devises"] = s["devises"] or [d for d, c in cases.items() if ((c.get(n) or {}).get("valeur") or 0)][:4]


def _theme_python(resultat: dict[int, dict], cat: _Catalogue, aujourdhui: str) -> None:
    """Thème (engrenage 1), 100 % Python : dollar = majorité des directions dollar des engrenages 2 à 8
    (égalité : neutre) ; risque = celui de l'engrenage 5 (VIX), à défaut de l'engrenage 7 (flux risque - refuge)."""
    t = resultat[1]
    dollars = [resultat[n]["dollar"] for n in range(2, 9) if resultat[n]["dollar"]]
    h, b = dollars.count("haussier"), dollars.count("baissier")
    if dollars:
        t["dollar"] = "haussier" if h > b else "baissier" if b > h else "neutre"
        t["force"] = 2 if abs(h - b) >= 3 else 1 if h != b else 0
    source_risque = next((n for n in (5, 7) if resultat[n]["risque"]), None)
    if source_risque:
        t["risque"] = resultat[source_risque]["risque"]
    if dollars or source_risque:
        t["donnees"].append({"texte": f"Directions dollar des engrenages 2 à 8 : {h} haussière(s), {b} baissière(s), "
                                      f"{len(dollars) - h - b} neutre(s)"
                                      + (f" ; risque de l'engrenage {source_risque} : {t['risque']}" if source_risque else ""),
                             "source_id": cat.src("Calcul Python", "directions des engrenages 2 à 8 (règles Python et matrice d'impact)",
                                                  aujourdhui)})
    t["regle"] = ("dollar : majorité des directions dollar des engrenages 2 à 8 (égalité : neutre) ; "
                  "risque : engrenage 5 (VIX), à défaut engrenage 7 (devises risque contre refuge)")


def conflits_detectes(sig: dict[int, dict]) -> list[dict]:
    """Paires d'engrenages dont les directions calculées s'opposent (dollar ou risque)."""
    resultat = []
    nums = sorted(sig)
    for i, a in enumerate(nums):
        for b in nums[i + 1:]:
            for cle, oppose in (("dollar", ("haussier", "baissier")), ("risque", ("risk_on", "risk_off"))):
                va, vb = sig[a].get(cle), sig[b].get(cle)
                if {va, vb} == set(oppose):
                    resultat.append({"engrenages": [a, b], "sur": cle,
                                     "texte": f"{NOMS[a]} ({va}) contre {NOMS[b]} ({vb}) sur le {('dollar' if cle == 'dollar' else 'risque global')}"})
    return resultat


# ------------------------------------------------------------- concept du jour
def charger_concepts(chemin: Path = FICHIER_CONCEPTS) -> list[dict]:
    concepts = []
    if not chemin.exists():
        return concepts
    courant = None
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+([a-z0-9_]+)\s+[—-]\s+(.+?)\s*$", ligne)
        if m:
            courant = {"id": m.group(1), "titre": m.group(2), "mots_cles": [], "definition": ""}
            concepts.append(courant)
        elif courant and ligne.lower().startswith("mots-clés"):
            courant["mots_cles"] = [m.strip().lower() for m in ligne.split(":", 1)[1].split(",") if m.strip()]
        elif courant and ligne.lower().startswith("définition"):
            courant["definition"] = ligne.split(":", 1)[1].strip()
    return concepts


def choisir_concept(concepts: list[dict], texte_du_jour: str, chemin_etat: Path,
                    aujourdhui: date | None = None) -> dict | None:
    """Rotation sans répétition sur un cycle complet ; parmi les concepts restants, le plus lié
    à l'actualité (nombre de mots-clés présents dans les données du jour). Même concept si
    l'appel est rejoué le même jour."""
    if not concepts:
        return None
    jour = (aujourdhui or date.today()).isoformat()
    try:
        etat = json.loads(chemin_etat.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        etat = {}
    etat.setdefault("cycle", 1)
    etat.setdefault("utilises", [])
    etat.setdefault("historique", [])
    ids = {c["id"] for c in concepts}
    if etat["historique"] and etat["historique"][-1].get("date") == jour and etat["historique"][-1].get("id") in ids:
        return next(c for c in concepts if c["id"] == etat["historique"][-1]["id"])
    restants = [c for c in concepts if c["id"] not in etat["utilises"]]
    if not restants:
        etat["cycle"] += 1
        etat["utilises"] = []
        restants = list(concepts)
    texte = texte_du_jour.lower()
    pertinence = {c["id"]: sum(texte.count(m) for m in c["mots_cles"]) for c in restants}
    choisi = max(restants, key=lambda c: pertinence[c["id"]])   # égalité : ordre du fichier
    etat["utilises"].append(choisi["id"])
    etat["historique"] = (etat["historique"] + [{"date": jour, "id": choisi["id"],
                                                 "pertinence": pertinence[choisi["id"]]}])[-60:]
    try:
        chemin_etat.parent.mkdir(parents=True, exist_ok=True)
        chemin_etat.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        log.warning("État de rotation des concepts non écrit : %s", exc)
    return {**choisi, "pertinence": pertinence[choisi["id"]], "cycle": etat["cycle"]}


# ------------------------------------------------------------------ normalisation
def normaliser(brut: dict, sig: dict[int, dict], conflits_py: list[dict], concept: dict | None,
               config: dict, justif: dict[int, dict[str, bool]] | None = None, texte_absent: str | None = None) -> dict:
    """texte_absent (repli sans modèle) : directions et convictions Python seules, chaque texte remplacé par ce message."""
    controles: list[str] = []
    retraits = 0
    devises_ok = set(config.get("devises", {}))

    def propre(t, maximum=700):
        nonlocal retraits
        net, n = _retirer_ordres(_texte(t, maximum))
        retraits += n
        return nommer_or(net)

    par_num = {}
    for e in brut.get("engrenages") or []:
        if isinstance(e, dict):
            try:
                par_num.setdefault(int(e.get("numero")), e)
            except (TypeError, ValueError):
                continue
    engrenages = []
    for n, cle, nom in ENGRENAGES:
        e, s = par_num.get(n) or {}, sig.get(n) or {}
        d = e.get("direction") if isinstance(e.get("direction"), dict) else {}
        llm_dollar, llm_risque = _norm(d.get("dollar")) or None, _norm(d.get("risque")) or None
        dollar, risque = s.get("dollar"), s.get("risque")
        for valeur_py, valeur_llm, libelle in ((dollar, llm_dollar, "dollar"), (risque, llm_risque, "risque")):
            if valeur_py and valeur_llm and valeur_llm != valeur_py:
                controles.append(f"engrenage {n} ({nom}) : le modèle proposait « {valeur_llm} » pour le {libelle}, "
                                 f"la règle Python donne « {valeur_py} » (conservée)")
        # Directions : TOUJOURS Python (règles et matrice d'impact) ; celle du modèle n'est jamais reprise,
        # une dimension sans règle reste « non déterminée » plutôt que devinée.
        origine_dir = {"dollar": "calcul Python" if dollar else None, "risque": "calcul Python" if risque else None}
        diag = propre(e.get("diagnostic"), 700)
        insuffisant = (not s.get("donnees")) if texte_absent else (
            (not diag) or diag.lower().startswith("données insuffisantes") or (n not in (1, 4, 6) and not s.get("donnees")))
        conv_llm = _norm((e.get("conviction") or {}).get("niveau")) if isinstance(e.get("conviction"), dict) else ""
        if s.get("conviction") is not None:
            niveau, origine = s["conviction"], "calcul Python"
        elif n in (4, 6) and conv_llm in CONVICTIONS and not insuffisant:
            niveau, origine = ("moyen" if conv_llm == "eleve" else conv_llm), "modèle (plafonnée à « moyen »)"
        else:
            niveau, origine = None, None
        if insuffisant and texte_absent and n in (1, 4, 6):   # thème, fiscalité, géopolitique : pas de « données insuffisantes »
            insuffisant = False                                 # sur la seule absence du texte rédigé
        if insuffisant:
            diag = TEXTE_INSUFFISANT
            dollar = dollar if s.get("donnees") else None
            risque = risque if s.get("donnees") else None
            niveau = None
        engrenages.append({
            "numero": n, "cle": cle, "nom": nom, "diagnostic": diag, "donnees_insuffisantes": insuffisant,
            "direction": {"dollar": dollar, "risque": risque,
                          "calculee": {"dollar": s.get("dollar"), "risque": s.get("risque"), "regle": s.get("regle")},
                          "origine": origine_dir,
                          "devises_concernees": [x for x in (d.get("devises_concernees") or s.get("devises") or [])
                                                 if isinstance(x, str) and x.upper() in devises_ok][:4],
                          "texte": propre(d.get("texte"), 300)},
            "comprendre": propre(e.get("comprendre"), 600), "desk": propre(e.get("desk"), 400),
            "conviction": {"niveau": niveau, "origine": origine,
                           "justification": propre((e.get("conviction") or {}).get("justification")
                                                   if isinstance(e.get("conviction"), dict) else "", 300)},
            "source_ids": _ids(e.get("source_ids")) or [x["source_id"] for x in s.get("donnees", []) if x.get("source_id")][:4],
            "donnees_calculees": s.get("donnees", []),
            "sources_indisponibles": s.get("indisponibles", []),
            "mesure": s.get("mesure"),
        })
        if texte_absent:
            engrenages[-1]["texte_indisponible"] = texte_absent
            continue
        if n not in par_num:
            controles.append(f"engrenage {n} ({nom}) absent de la réponse du modèle")

    chaines = []
    for c in (brut.get("chaines") or [])[:3]:
        maillons = []
        for m in (c.get("maillons") or [])[:8] if isinstance(c, dict) else []:
            try:
                num = int(m.get("engrenage"))
            except (TypeError, ValueError, AttributeError):
                continue
            if 1 <= num <= 8 and _texte(m.get("texte")):
                maillons.append({"engrenage": num, "texte": propre(m.get("texte"), 250),
                                 "source_id": (_ids(m.get("source_id")) or [None])[0]})
        if len(maillons) >= 2:
            chaines.append({"titre": propre(c.get("titre"), 150), "maillons": maillons})
    if not chaines and not texte_absent:
        controles.append("aucune chaîne de transmission exploitable")

    conflits, vus = [], set()
    for c in brut.get("conflits") or []:
        if not isinstance(c, dict):
            continue
        paire = tuple(sorted(int(x) for x in (c.get("engrenages") or []) if str(x).isdigit() and 1 <= int(x) <= 8))[:2]
        if len(paire) == 2 and _texte(c.get("texte")):
            vus.add(paire)
            conflits.append({"engrenages": list(paire), "texte": propre(c.get("texte"), 400),
                             "source_ids": _ids(c.get("source_ids")), "origine": "modèle"})
    for c in conflits_py:   # tout conflit calculé apparaît, même si le modèle l'a oublié
        paire = tuple(c["engrenages"])
        if paire not in vus:
            vus.add(paire)
            conflits.append({"engrenages": list(paire), "texte": c["texte"], "source_ids": [], "origine": "calcul Python"})

    concept_sortie = None
    if concept:
        bc = brut.get("concept") if isinstance(brut.get("concept"), dict) else {}
        concept_sortie = {"id": concept["id"], "titre": concept["titre"], "definition": concept.get("definition"),
                          "explication": propre(bc.get("explication"), 600) or concept.get("definition"),
                          "exemple": propre(bc.get("exemple"), 500), "source_ids": _ids(bc.get("source_ids")),
                          "cycle": concept.get("cycle"), "pertinence": concept.get("pertinence")}
    if retraits:
        controles.append(f"{retraits} phrase(s) retirée(s) : formulation d'ordre d'achat/vente")
    # Vocabulaire : « record » / « s'envole » seulement si les dossiers chiffrés le justifient.
    justif = justif or {}
    tout = {"record": any(v.get("record") for v in justif.values()), "envol": any(v.get("envol") for v in justif.values())}
    moderes = 0
    for e in engrenages:
        permis = justif.get(e["numero"], {})
        for cle in ("diagnostic", "comprendre", "desk"):
            e[cle], k = moderer_vocabulaire(e[cle], permis)
            moderes += k
        e["direction"]["texte"], k = moderer_vocabulaire(e["direction"]["texte"], permis)
        moderes += k
        e["conviction"]["justification"], k = moderer_vocabulaire(e["conviction"]["justification"], permis)
        moderes += k
    for c in chaines:
        for m in c["maillons"]:
            m["texte"], k = moderer_vocabulaire(m["texte"], justif.get(m["engrenage"], tout))
            moderes += k
    for c in conflits:
        c["texte"], k = moderer_vocabulaire(c["texte"], tout)
        moderes += k
    if concept_sortie:
        for cle in ("explication", "exemple"):
            concept_sortie[cle], k = moderer_vocabulaire(concept_sortie[cle], tout)
            moderes += k
    if moderes:
        controles.append(f"{moderes} mot(s) « record » / « s'envole » remplacé(s) : non justifiés par les percentiles ou les variations")
    return {"engrenages": engrenages, "chaines": chaines, "conflits": conflits, "concept": concept_sortie,
            "controles": controles}


# ------------------------------------------------------------------------ appel
def a_faire(sg: dict | None, cfg: dict) -> bool:
    if not cfg.get("actif", True):
        return False
    e = (sg or {}).get("engrenages") or {}
    return e.get("statut") not in ("ok", "abandonnee")


def generer(config: dict, llm: FournisseurLLM, donnees: dict, macro: dict, catalogue: list[dict],
            devises: list[dict], biais: str | None, extras: dict | None = None,
            existant: dict | None = None) -> dict:
    """Synthèse 8 engrenages du jour. Ne lève jamais : statut ok / indisponible / abandonnee."""
    cfg = config.get("engrenages") or {}
    precedentes = int((existant or {}).get("tentatives", 0))
    horodatage = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        cat = _Catalogue(catalogue)
        sig = signaux(config, donnees, macro, devises, biais, extras or {}, cat)
        conflits_py = conflits_detectes(sig)
        texte_jour = json.dumps({"s": sig, "n": [a.get("titre") for a in donnees.get("news", [])]},
                                ensure_ascii=False, default=str)
        concept = choisir_concept(charger_concepts(), texte_jour,
                                  RACINE / config["chemins"]["donnees"] / "cache" / "concepts_rotation.json")
        coh_avant = vue_ensemble.coherence({n: {"direction": {"dollar": s.get("dollar"), "risque": s.get("risque")}}
                                            for n, s in sig.items()})
        contexte = {
            "date": date.today().isoformat(),
            "biais_global_calcule": biais,
            "classement_scores": {d["devise"]: d.get("score_confluence") for d in devises},
            "engrenages_signaux_calcules": {
                str(n): {"nom": NOMS[n], "direction_calculee": {"dollar": s["dollar"], "risque": s["risque"]},
                         "regle": s["regle"], "conviction_calculee": s["conviction"], "donnees": s["donnees"],
                         "sources_indisponibles": s.get("indisponibles", []),
                         "devises": s["devises"]} for n, s in sig.items()},
            "conflits_detectes": conflits_py,
            "actualites": [{"titre": a.get("titre"), "date": (a.get("date") or "")[:10], "source_id": a.get("source_id")}
                           for a in (donnees.get("news") or [])[: int(cfg.get("articles_max", 25))]],
            "calendrier_impact_eleve": [
                {k: e.get(k) for k in ("date", "devise", "evenement", "reel", "prevision", "precedent", "source_id")}
                for e in donnees.get("calendrier", []) if str(e.get("impact", "")).lower() == "high"][:20],
            "concept_du_jour": ({k: concept[k] for k in ("id", "titre", "definition")} if concept else None),
            "coherence_calculee": {k: coh_avant[k] for k in ("alignes", "evaluables", "theme_fort", "libelle")},
        }
        present = set(re.findall(r"src_\d{3,}", json.dumps(contexte, ensure_ascii=False, default=str)))
        contexte["catalogue_sources"] = [{"id": s["id"], "source": s["source"], "detail": str(s.get("detail"))[:80],
                                          "date": s.get("date")} for s in catalogue if s["id"] in present]
        systeme = FICHIER_CADRE.read_text(encoding="utf-8") if FICHIER_CADRE.exists() else ""
        prompt = (
            "Produis la synthèse « 8 engrenages » du jour (version quotidienne compacte : diagnostic court, "
            "2 phrases max par champ). Reprends chaque direction_calculee telle quelle quand elle n'est pas "
            "null. Une à trois chaînes de transmission, chaque maillon rattaché à un engrenage et à un "
            "source_id. Décris les conflits_detectes et ajoute ceux que tu vois. Explique le concept_du_jour "
            "simplement avec un exemple tiré de ces données. Si coherence_calculee.theme_fort est false, le "
            "diagnostic de l'engrenage 1 (thème global) n'annonce AUCUN thème fort, dominant ou net : il dit que "
            "les signaux sont mixtes. Les autres engrenages décrivent librement leurs propres données.\n"
            f"Réponds STRICTEMENT selon ce schéma JSON :\n{SCHEMA}\n"
            "SEULS les source_id de catalogue_sources existent : null plutôt qu'inventer.\n\n"
            "DONNÉES DU JOUR (JSON) :\n" + json.dumps(contexte, ensure_ascii=False, default=str))
        definir_etiquette("engrenages")
        derniere = None
        for essai in range(1, int(config["llm"].get("max_tentatives_json", 2)) + 1):
            try:
                brut = extraire_json(llm.appeler_llm(prompt, systeme=systeme))
                if not isinstance(brut, dict) or not brut.get("engrenages"):
                    raise ValueError("réponse sans engrenages")
                if len([e for e in brut["engrenages"] if isinstance(e, dict)]) < MIN_ENGRENAGES_REPONSE:
                    raise ValueError(f"réponse incomplète ({len(brut['engrenages'])} engrenage(s) sur 8)")
                sortie = normaliser(brut, sig, conflits_py, concept, config,
                                    justifications((extras or {}).get("dossiers")))
                imposer_signaux_mixtes(sortie)
                sortie.update({"statut": "ok", "tentatives": precedentes + 1, "genere_le": horodatage,
                               "redige_par": attribution_modele(), "version": "quotidienne"})
                _liberer_reserve(llm)
                return sortie
            except QuotaAtteint:
                raise
            except Exception as exc:  # noqa: BLE001
                repli_modele_suivant(llm)   # JSON ou schéma invalide : nouvel essai sur le modèle suivant
                derniere = exc
                log.warning("8 engrenages, essai %d en échec : %s", essai, masquer_secrets(str(exc)))
        raise RuntimeError(masquer_secrets(str(derniere)))
    except QuotaAtteint:
        log.warning("8 engrenages : quota du jour atteint — directions et titre calculés en Python, texte en attente")
        return {"statut": "indisponible", "raison": MESSAGE_QUOTA_ATTEINT, "quota_atteint": True,
                "tentatives": precedentes, "genere_le": horodatage,
                **repli_python(config, donnees, macro, catalogue, devises, biais, extras, TEXTE_QUOTA)}
    except Exception as exc:  # noqa: BLE001
        n = precedentes + 1
        statut = "abandonnee" if n >= int(cfg.get("tentatives_max", 4)) else "indisponible"
        log.error("8 engrenages %s (tentative %d) : %s", statut, n, masquer_secrets(str(exc)))
        if statut == "abandonnee":
            _liberer_reserve(llm)
        return {"statut": statut, "raison": masquer_secrets(str(exc))[:200], "tentatives": n, "genere_le": horodatage,
                **repli_python(config, donnees, macro, catalogue, devises, biais, extras, TEXTE_ECHEC)}


def rafraichir(sortie: dict | None, config: dict, donnees: dict, macro: dict, catalogue: list[dict],
               devises: list[dict], biais: str | None, extras: dict | None) -> dict | None:
    """À chaque passage (lot V5) : directions, convictions, chiffres calculés, conflits Python et titre imposé
    recalculés sur les données du passage ; seuls les textes du modèle sont gardés. Évite qu'une synthèse du
    matin affiche un VIX différent de la matrice recalculée à 18 h. Ne lève jamais."""
    if not sortie or not sortie.get("engrenages"):
        return sortie
    try:
        cat = _Catalogue(catalogue)
        sig = signaux(config, donnees, macro, devises, biais, extras or {}, cat)
    except Exception as exc:  # noqa: BLE001
        log.error("8 engrenages : rafraîchissement Python en échec (%s)", masquer_secrets(str(exc)))
        return sortie
    changes = []
    for e in sortie["engrenages"]:
        s = sig.get(e.get("numero")) or {}
        d = e.setdefault("direction", {})
        avant = (d.get("dollar"), d.get("risque"))
        donnees_ok = bool(s.get("donnees"))
        d["dollar"], d["risque"] = (s.get("dollar"), s.get("risque")) if donnees_ok or e["numero"] in (1, 4, 6) else (None, None)
        d["calculee"] = {"dollar": s.get("dollar"), "risque": s.get("risque"), "regle": s.get("regle")}
        d["origine"] = {"dollar": "calcul Python" if d["dollar"] else None, "risque": "calcul Python" if d["risque"] else None}
        if s.get("conviction") is not None:
            e.setdefault("conviction", {}).update({"niveau": s["conviction"], "origine": "calcul Python"})
        e["donnees_calculees"] = s.get("donnees", [])
        e["sources_indisponibles"] = s.get("indisponibles", [])
        e["mesure"] = s.get("mesure")
        if avant != (d["dollar"], d["risque"]) and (e.get("diagnostic") and not e.get("texte_indisponible")):
            e["texte_redige_avant_recalcul"] = True
            changes.append(e["numero"])
    py = [c for c in sortie.get("conflits") or [] if c.get("origine") != "calcul Python"]
    vus = {tuple(c["engrenages"]) for c in py}
    for c in conflits_detectes(sig):
        if tuple(c["engrenages"]) not in vus:
            py.append({"engrenages": c["engrenages"], "texte": c["texte"], "source_ids": [], "origine": "calcul Python"})
    sortie["conflits"] = py
    sortie.pop("titre_theme_impose", None)
    imposer_signaux_mixtes(sortie)
    sortie["rafraichi_le"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if changes:
        sortie.setdefault("controles", []).append(
            "direction recalculée après le texte du modèle pour l'engrenage " + ", ".join(map(str, changes)) +
            " : le texte décrit les chiffres du moment de sa rédaction")
    return sortie


def _liberer_reserve(llm: FournisseurLLM) -> None:
    """Synthèse réussie (ou abandonnée) aujourd'hui : la réserve d'appels du jour n'a plus d'objet."""
    marquer = getattr(llm, "marquer_engrenages_faits", None)
    if callable(marquer):
        marquer()


def repli_python(config: dict, donnees: dict, macro: dict, catalogue: list[dict], devises: list[dict],
                 biais: str | None, extras: dict | None, message: str) -> dict:
    """Sans texte du modèle : les 8 directions, les convictions, les conflits et le titre du thème restent
    calculés (Python) ; chaque texte est remplacé par `message`. Jamais d'exception (vide en dernier recours)."""
    try:
        cat = _Catalogue(catalogue)
        sig = signaux(config, donnees, macro, devises, biais, extras or {}, cat)
        sortie = normaliser({}, sig, conflits_detectes(sig), None, config, texte_absent=message)
        imposer_signaux_mixtes(sortie)
        sortie.update({"repli_python": True, "texte_indisponible": message})
        return sortie
    except Exception as exc:  # noqa: BLE001
        log.error("8 engrenages : repli Python en échec (%s)", masquer_secrets(str(exc)))
        return {"repli_python": False, "texte_indisponible": message}
