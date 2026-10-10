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
from core.llm import (MESSAGE_QUOTA_ATTEINT, FournisseurLLM, QuotaAtteint, attribution_modele,
                      definir_etiquette, extraire_json)
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
SANS_REGLE = (4, 6, 8)   # engrenages sans direction calculable en Python

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

    # 1. Thème macro : biais global (calcul Python) + score de l'USD
    id_scores = cat.src("Calcul Python", "scores de confluence et biais global du jour", aujourdhui)
    usd = scores.get("USD")
    classes = sorted([(s, d) for d, s in scores.items() if s is not None], reverse=True)
    resultat[1] = {
        "dollar": None if usd is None else ("haussier" if usd >= 60 else "baissier" if usd <= 40 else "neutre"),
        "risque": biais if biais in DIRECTIONS_RISQUE else None,
        "devises": list(dict.fromkeys([d for _, d in classes[:2]] + [d for _, d in classes[-2:]])),
        "regle": "risque = biais global calculé (scores risque vs refuge) ; dollar = score USD (≥ 60 / ≤ 40)",
        "donnees": [{"texte": f"Biais global {biais} ; classement : " +
                     ", ".join(f"{d} {s}" for s, d in classes), "source_id": id_scores}] if classes else [],
        "force": 2 if usd is not None and (usd >= 70 or usd <= 30) else 1,
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
    resultat[2] = {"dollar": _dir(var2, 10, "haussier", "baissier"), "risque": None,
                   "devises": [d for d, s in decisions if s in ("hausse", "baisse")],
                   "regle": "dollar : variation hebdomadaire du 2 ans US (≥ +10 pb haussier, ≤ -10 pb baissier)",
                   "donnees": donnees2, "force": _force(var2, 10)}

    # 3. Données économiques : indice de surprise 30 j
    indices = (extras or {}).get("indice_surprise") or {}
    id_ind = cat.src("Calcul Python (registre macro)", "indice de surprise macro 30 jours par devise", aujourdhui)
    vals = {d: v.get("indice") for d, v in indices.items() if isinstance(v, dict) and v.get("indice") is not None}
    i_usd = vals.get("USD")
    resultat[3] = {"dollar": _dir(i_usd, 0.3, "haussier", "baissier"), "risque": None,
                   "devises": [d for d, v in sorted(vals.items(), key=lambda kv: -abs(kv[1]))[:3]],
                   "regle": "dollar : indice de surprise 30 j de l'USD (≥ +0,3 haussier, ≤ -0,3 baissier)",
                   "donnees": [{"texte": "Indice de surprise 30 j : " + ", ".join(f"{d} {v:+.2f}" for d, v in vals.items()),
                                "source_id": id_ind}] if vals else [],
                   "force": _force(i_usd, 0.3)}

    # 4. Politique fiscale : actualité seulement (pas de série chiffrée gratuite fiable branchée)
    resultat[4] = {"dollar": None, "risque": None, "devises": [], "donnees": [], "force": 0,
                   "regle": "aucune règle chiffrée : lecture de l'actualité par le LLM (conviction plafonnée à « moyen »)"}

    # 5. Interconnexions : VIX (risque), indice dollar large (dollar), S&P 500
    donnees5 = []
    vix = series.get("vix") or {}
    v_vix = _variation(marche.get("vix"))
    if vix.get("valeur") is not None:
        donnees5.append({"texte": f"VIX {vix['valeur']} le {vix.get('date')}"
                         + (f" ({v_vix[1]:+.1f} % sur 7 j)" if v_vix else ""), "source_id": vix.get("source_id")})
    risque5 = None
    if vix.get("valeur") is not None:
        niveau = float(vix["valeur"])
        risque5 = "risk_off" if niveau >= 25 or (v_vix and v_vix[1] >= 25) else \
                  "risk_on" if niveau <= 14 and not (v_vix and v_vix[1] >= 10) else "neutre"
    v_dollar = _variation(marche.get("dollar_large"))
    if v_dollar:
        donnees5.append({"texte": f"Indice dollar large (Fed) {v_dollar[0]} le {v_dollar[2]} ({v_dollar[1]:+.2f} % sur 7 j)",
                         "source_id": cat.src("FRED", "indice dollar large (DTWEXBGS)", v_dollar[2])})
    sp = series.get("sp500") or {}
    if sp.get("valeur") is not None:
        donnees5.append({"texte": f"S&P 500 {sp['valeur']} le {sp.get('date')} ({sp.get('variation_pct'):+.2f} % sur la séance)"
                         if sp.get("variation_pct") is not None else f"S&P 500 {sp['valeur']} le {sp.get('date')}",
                         "source_id": sp.get("source_id")})
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
    resultat[5] = {"dollar": _dir(v_dollar[1] if v_dollar else None, 0.5, "haussier", "baissier"),
                   "risque": risque5, "devises": ["JPY", "CHF", "AUD"] if risque5 in ("risk_on", "risk_off") else [],
                   "regle": "risque : VIX (≥ 25 ou +25 % sur 7 j : risk off ; ≤ 14 sans hausse : risk on) ; "
                            "dollar : indice dollar large Fed sur 7 j (±0,5 %)",
                   "donnees": donnees5, "indisponibles": indisponibles5, "force": max(_force(v_dollar[1] if v_dollar else None, 0.5),
                                                     2 if risque5 == "risk_off" and vix.get("valeur", 0) >= 30 else 1 if risque5 else 0)}

    # 6. Géopolitique : actualité seulement
    resultat[6] = {"dollar": None, "risque": None, "devises": [], "donnees": [], "force": 0,
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
    resultat[7] = {"dollar": _dir(v_usd, 0.3, "haussier", "baissier"), "risque": _dir(ecart, 0.3, "risk_on", "risk_off"),
                   "devises": [d for d in RISQUE + REFUGE if abs((technique.get(d) or {}).get("variation_5j_pct") or 0) >= 0.5],
                   "regle": "dollar : indice USD synthétique sur 5 j (±0,3 %) ; risque : devises risque vs refuge sur 5 j (±0,3 pt) ; "
                            "COT : positionnement décrit, extrêmes signalés (pas de direction tirée du COT seul)",
                   "donnees": donnees7, "indisponibles": indisponibles7, "force": max(_force(v_usd, 0.3), _force(ecart, 0.3))}

    # 8. Offre et demande : pétrole (7 j) et balances commerciales
    donnees8 = []
    v_wti = _variation(marche.get("wti"))
    if v_wti:
        donnees8.append({"texte": f"WTI {v_wti[0]} $ le {v_wti[2]} ({v_wti[1]:+.1f} % sur 7 j)",
                         "source_id": (series.get("petrole_wti") or {}).get("source_id")})
    v_brent = _variation(marche.get("brent"))
    if v_brent:
        donnees8.append({"texte": f"Brent {v_brent[0]} $ le {v_brent[2]} ({v_brent[1]:+.1f} % sur 7 j)",
                         "source_id": (series.get("petrole_brent") or {}).get("source_id")})
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
                   "donnees": donnees8, "indisponibles": indisponibles8, "force": max(_force(v_wti[1] if v_wti else None, 3),
                                _force((eia or {}).get("variation_semaine"), 3))}

    for n, s in resultat.items():
        s["donnees"] = [d for d in s["donnees"] if d.get("texte")]
        defini = s["dollar"] not in (None, "neutre") or s["risque"] not in (None, "neutre")
        s["conviction"] = _conviction(len(s["donnees"]), defini, s.pop("force", 0)) if n not in (4, 6) else None

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
               config: dict) -> dict:
    controles: list[str] = []
    retraits = 0
    devises_ok = set(config.get("devises", {}))

    def propre(t, maximum=700):
        nonlocal retraits
        net, n = _retirer_ordres(_texte(t, maximum))
        retraits += n
        return net

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
        # Direction du modèle acceptée UNIQUEMENT pour les engrenages sans règle Python (4, 6, 8) ;
        # ailleurs, une dimension sans règle reste « non déterminée » plutôt que devinée.
        origine_dir = {"dollar": "calcul Python" if dollar else None, "risque": "calcul Python" if risque else None}
        if n in SANS_REGLE:
            if dollar is None and llm_dollar in DIRECTIONS_DOLLAR:
                dollar, origine_dir["dollar"] = llm_dollar, "modèle"
            if risque is None and llm_risque in DIRECTIONS_RISQUE:
                risque, origine_dir["risque"] = llm_risque, "modèle"
        diag = propre(e.get("diagnostic"), 700)
        insuffisant = (not diag) or diag.lower().startswith("données insuffisantes") or \
                      (n not in (1, 4, 6) and not s.get("donnees"))
        conv_llm = _norm((e.get("conviction") or {}).get("niveau")) if isinstance(e.get("conviction"), dict) else ""
        if s.get("conviction") is not None:
            niveau, origine = s["conviction"], "calcul Python"
        elif n in (4, 6) and conv_llm in CONVICTIONS and not insuffisant:
            niveau, origine = ("moyen" if conv_llm == "eleve" else conv_llm), "modèle (plafonnée à « moyen »)"
        else:
            niveau, origine = None, None
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
        })
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
    if not chaines:
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
            "simplement avec un exemple tiré de ces données.\n"
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
                sortie = normaliser(brut, sig, conflits_py, concept, config)
                sortie.update({"statut": "ok", "tentatives": precedentes + 1, "genere_le": horodatage,
                               "redige_par": attribution_modele(), "version": "quotidienne"})
                return sortie
            except QuotaAtteint:
                raise
            except Exception as exc:  # noqa: BLE001
                derniere = exc
                log.warning("8 engrenages, essai %d en échec : %s", essai, masquer_secrets(str(exc)))
        raise RuntimeError(masquer_secrets(str(derniere)))
    except QuotaAtteint:
        return {"statut": "indisponible", "raison": MESSAGE_QUOTA_ATTEINT, "quota_atteint": True,
                "tentatives": precedentes, "genere_le": horodatage}
    except Exception as exc:  # noqa: BLE001
        n = precedentes + 1
        statut = "abandonnee" if n >= int(cfg.get("tentatives_max", 4)) else "indisponible"
        log.error("8 engrenages %s (tentative %d) : %s", statut, n, masquer_secrets(str(exc)))
        return {"statut": statut, "raison": masquer_secrets(str(exc))[:200], "tentatives": n, "genere_le": horodatage}
