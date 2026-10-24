"""Fiches d'analyse des 36 paires (lot V5, étape 7, Journal) → docs/data/paires.json. Calcul Python à chaque run.

Pour chaque paire (convention de marché, core/outils.paires) :
- macro : thème du jour, décomposition par engrenage (outil C), scores de confluence, écart des taux directeurs et
  des taux 2 ans (portage), surprises macro, prochains évènements des deux devises (agenda) ;
- technique : cours, RSI 14, écart aux MM50 et MM200, plus haut / plus bas sur 20 séances, volatilité 30 j, calculés
  sur le croisé des séries uniques 5 ans (force de chaque devise en dollars US ; USD = 1) ;
- conséquences : lecture du jour du tableau des conséquences pour chacune des deux devises, engrenage par engrenage ;
- synthèse en 3 lignes : phrase Python ; remplacée par le texte du modèle seulement pour « Mes paires »
  (agents/agent_paires.py, un appel groupé, réserve de quota) ;
- graphique 1 jour (toutes les paires, repères du palier 10) et chandeliers 30 min / 4 h / 1 j pour « Mes paires »
  (Twelve Data, agents/collecte_intraday.py).
Aucune valeur inventée : « n/d » avec la raison.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from core import annotations, historique_5ans as h5m, impact as impact_mod, outils, tableau_macro

log = logging.getLogger(__name__)

MES_PAIRES_DEFAUT = ["USD/JPY", "EUR/USD", "GBP/USD", "AUD/USD", "USD/CAD", "USD/CHF"]
JOURS_GRAPHIQUE = 183


def mes_paires(config: dict) -> list[str]:
    liste = (((config or {}).get("journal") or {}).get("mes_paires")) or MES_PAIRES_DEFAUT
    valides = set(outils.paires())
    return [p for p in liste if p in valides] or MES_PAIRES_DEFAUT


def serie_paire(h5, technique, paire: str) -> list[tuple[str, float]]:
    base, cot = paire.split("/")
    series = {d: dict(impact_mod.serie_devise(h5, d, technique).points) for d in (base, cot) if d != "USD"}
    if not series:
        return []
    jours = sorted(set.intersection(*(set(s) for s in series.values())))
    out = []
    for j in jours:
        vb = 1.0 if base == "USD" else series[base][j]
        vc = 1.0 if cot == "USD" else series[cot][j]
        if vb and vc:
            out.append((j, vb / vc))
    return out


def _dernier(points):
    return points[-1][1] if points else None


def _fmt(v, d=4):
    if v is None:
        return "n/d"
    d = 6 if abs(v) < 0.1 else 4 if abs(v) < 10 else 2
    return f"{v:.{d}f}".replace(".", ",")


def technique_paire(pts: list[tuple[str, float]]) -> dict:
    if len(pts) < 30:
        return {"raison": "historique quotidien insuffisant pour cette paire"}
    r = h5m.rsi(pts, 14)
    mm50, mm200 = h5m.ecart_moyenne(pts, 50), h5m.ecart_moyenne(pts, 200)
    vol = h5m.volatilite(pts, 30)
    der20 = pts[-20:]
    return {"cours": round(pts[-1][1], 6), "date": pts[-1][0], "texte_cours": _fmt(pts[-1][1]),
            "rsi14": round(_dernier(r), 1) if r else None, "ecart_mm50": round(_dernier(mm50), 2) if mm50 else None,
            "ecart_mm200": round(_dernier(mm200), 2) if mm200 else None,
            "raison_mm200": None if mm200 else "moins de 200 séances",
            "plus_haut_20j": round(max(v for _, v in der20), 6), "plus_bas_20j": round(min(v for _, v in der20), 6),
            "volatilite_30j": _dernier(vol), "source": "croisé des séries uniques 5 ans (Twelve Data raccordé à la Fed H.10)"}


def _taux(registre, dossiers_eng, devise):
    rates = tableau_macro.infos_taux(registre or {}, [devise]).get(devise) or {}
    case = ((registre or {}).get("cases") or {}).get(f"{devise}|taux_directeur") or {}
    valeur, borne = tableau_macro.lire_taux((case.get("actuel") or {}).get("valeur"))
    deux = next((((l.get("cellules") or {}).get("taux_2a") or {}) for l in ((dossiers_eng or {}).get("2") or {}).get("lignes") or []
                 if l.get("devise") == devise), {})
    return {"directeur": valeur, "borne": borne, "date_directeur": (case.get("actuel") or {}).get("date_pub"),
            "deux_ans": deux.get("valeur"), "date_2a": deux.get("date"), "raison_2a": deux.get("raison"), "prochaine": rates.get("prochaine")}


def _ecart(a, b, unite="pb"):
    if a is None or b is None:
        return None
    return round((a - b) * 100) if unite == "pb" else round(a - b, 2)


def fiche(paire: str, dossiers_donnees: dict, rapport: dict | None, registre: dict | None, agenda_donnees: dict | None,
          decompositions: dict, pts: list[tuple[str, float]]) -> dict:
    base, cot = paire.split("/")
    vue = dossiers_donnees.get("vue_ensemble") or {}
    theme = vue.get("theme") or {}
    dec = decompositions.get(paire) or {}
    scores = {d.get("devise"): d.get("score_confluence") for d in (rapport or {}).get("devises") or []}
    surprises = ((rapport or {}).get("tableau_macro") or {}).get("indice_surprise_30j") or {}
    tb, tc = _taux(registre, dossiers_donnees.get("engrenages"), base), _taux(registre, dossiers_donnees.get("engrenages"), cot)
    portage = {"directeur_pb": _ecart(tb["directeur"], tc["directeur"]), "deux_ans_pb": _ecart(tb["deux_ans"], tc["deux_ans"]),
               "borne": tb["borne"] or tc["borne"], "base": tb, "cotation": tc,
               "raison_2a": None if tb["deux_ans"] is not None and tc["deux_ans"] is not None else
               f"taux 2 ans n/d : {tb['raison_2a'] or tc['raison_2a'] or 'source absente'}"}
    evts = [e for j in (agenda_donnees or {}).get("jours") or [] for e in j["evenements"]
            if e["devise"] in (base, cot) and e["impact"] in ("fort", "moyen")][:6]
    tech = technique_paire(pts)
    consequences = []
    for n, e in sorted(((dossiers_donnees.get("engrenages") or {}).items()), key=lambda kv: int(kv[0])):
        lignes = {l.get("actif"): l for l in ((e or {}).get("consequences") or {}).get("lignes") or []}
        if base in lignes or cot in lignes:
            lect = lambda d: ((lignes.get(d) or {}).get("aujourdhui") or {}).get("lecture") or ("n/d" if d in lignes else "hors tableau")
            consequences.append({"engrenage": int(n), "moteur": (((e or {}).get("consequences") or {}).get("moteur") or {}).get("libelle"),
                                 "base": lect(base), "cotation": lect(cot)})
    s_b, s_c = scores.get(base), scores.get(cot)
    i_b, i_c = (surprises.get(base) or {}).get("indice"), (surprises.get(cot) or {}).get("indice")
    l1 = (f"Thème : {theme.get('titre') or 'n/d'}. {dec.get('texte') or 'Décomposition n/d'}.")
    l2 = ("Portage : écart des taux directeurs " + ("n/d" if portage["directeur_pb"] is None else
          f"{'≤ ' if tb['borne'] == '<' or tc['borne'] == '>' else '≥ ' if tc['borne'] == '<' or tb['borne'] == '>' else ''}"
          f"{portage['directeur_pb']:+d} pb".replace("-", "−"))
          + ", taux 2 ans " + ("n/d" if portage["deux_ans_pb"] is None else f"{portage['deux_ans_pb']:+d} pb".replace("-", "−"))
          + f" ; scores de confluence {base} {s_b if s_b is not None else 'n/d'} / {cot} {s_c if s_c is not None else 'n/d'}.")
    if tech.get("raison"):
        l3 = f"Technique : n/d ({tech['raison']})."
    else:
        mm200 = "n/d" if tech["ecart_mm200"] is None else f"{tech['ecart_mm200']:+.2f} %".replace(".", ",").replace("-", "−")
        l3 = (f"Technique : {_fmt(tech['cours'])} au {tech['date'][8:10]}/{tech['date'][5:7]}, RSI {str(tech['rsi14']).replace('.', ',')}, "
              f"écart MM200 {mm200}, volatilité 30 j {str(tech['volatilite_30j']).replace('.', ',')} %.")
    debut = (date.fromisoformat(pts[-1][0]) - timedelta(days=JOURS_GRAPHIQUE)).isoformat() if pts else None
    graph = [[d, round(v, 6)] for d, v in pts if debut and d >= debut]
    return {"paire": paire, "base": base, "cotation": cot,
            "macro": {"theme": theme.get("titre"), "titre_impose": theme.get("titre_impose"),
                      "direction_theme": (theme.get("direction") or {}).get("libelle"),
                      "direction_paire": dec.get("lecture"), "decomposition": dec,
                      "scores": {base: s_b, cot: s_c}, "surprises": {base: i_b, cot: i_c}, "portage": portage, "evenements": evts},
            "technique": tech, "consequences": consequences,
            "synthese_python": [l1, l2, l3], "synthese_modele": None,
            "graphique_1j": {"points": graph, "source": tech.get("source"),
                             "annotations": {"courbe": paire, "periodes": annotations.reperes(graph, None, tech.get("source"), [], paire)}},
            "date_rapport": theme.get("date_rapport")}


def reperes_intraday(bougies: list[list], source: str, paire: str) -> list[dict]:
    """Plus haut, plus bas (mèches) et dernière clôture, horodatés (UTC) : mêmes types que les repères du palier 10."""
    if len(bougies) < 2:
        return []
    haut = max(bougies, key=lambda b: b[2])
    bas = min(bougies, key=lambda b: b[3])
    der = bougies[-1]
    h = lambda t: f"{t[8:10]}/{t[5:7]} {t[11:16]} UTC"
    sortie = []
    if haut[0] != der[0]:
        sortie.append({"type": "haut", "date": haut[0], "valeur": haut[2], "texte": f"Plus haut {_fmt(haut[2])}",
                       "detail": f"{paire} : plus haut {_fmt(haut[2])} ({h(haut[0])})", "source": source})
    if bas[0] != der[0]:
        sortie.append({"type": "bas", "date": bas[0], "valeur": bas[3], "texte": f"Plus bas {_fmt(bas[3])}",
                       "detail": f"{paire} : plus bas {_fmt(bas[3])} ({h(bas[0])})", "source": source})
    sortie.append({"type": "dernier", "date": der[0], "valeur": der[4], "texte": f"{_fmt(der[4])}",
                   "detail": f"{paire} : dernière clôture {_fmt(der[4])} ({h(der[0])})", "source": source})
    return sorted(sortie, key=lambda r: r["date"])


def calculer(config: dict, dossiers_donnees: dict, rapport: dict | None, registre: dict | None, agenda_donnees: dict | None,
             h5, technique: dict | None, intraday: dict | None = None, textes: dict | None = None) -> dict:
    decs = outils.decomposer(dossiers_donnees.get("matrice_impact") or {})
    mes = mes_paires(config)
    fiches = {}
    for p in outils.paires():
        try:
            fiches[p] = fiche(p, dossiers_donnees, rapport, registre, agenda_donnees, decs, serie_paire(h5, technique, p))
        except Exception as exc:  # noqa: BLE001 — une paire en échec n'affecte qu'elle
            log.exception("Fiche %s en échec", p)
            fiches[p] = {"paire": p, "raison": f"calcul en échec : {exc}"[:150]}
        if p in mes:
            ch = (intraday or {}).get("paires", {}).get(p)
            if ch:   # repères du palier 10 sur les clôtures de chaque unité de temps (plus haut, plus bas, dernière)
                ch = {u: {**v, "annotations": reperes_intraday(v.get("bougies") or [], v.get("source") or "Twelve Data", p)}
                      for u, v in ch.items()}
            fiches[p]["chandeliers"] = ch or {
                "raison": (intraday or {}).get("raison") or "chandeliers non collectés (collecte au run complet, Twelve Data)"}
        t = (textes or {}).get(p)
        if p in mes and t and t.get("texte"):
            fiches[p]["synthese_modele"] = t
    return {"genere_le": dossiers_donnees.get("genere_le"), "mes_paires": mes, "paires": outils.paires(), "fiches": fiches,
            "intraday_collecte_le": (intraday or {}).get("collecte_le"),
            "note": "Fiches calculées en Python à chaque run ; synthèse du modèle pour « Mes paires » seulement. Aide à la décision, jamais un ordre."}


def textes_du_jour(racine: Path) -> dict:
    try:
        t = json.loads((Path(racine) / "data" / "cache" / "paires_textes.json").read_text(encoding="utf-8"))
        return t.get("textes") or {} if t.get("date") == date.today().isoformat() else {}
    except (OSError, ValueError):
        return {}


def intraday_du_jour(racine: Path) -> dict | None:
    try:
        return json.loads((Path(racine) / "data" / "cache" / "intraday.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ecrire(racine: str | Path, config: dict, dossiers_donnees: dict, rapport: dict | None, registre: dict | None,
           agenda_donnees: dict | None, h5, technique: dict | None) -> dict | None:
    try:
        donnees = calculer(config, dossiers_donnees, rapport, registre, agenda_donnees, h5, technique,
                           intraday_du_jour(Path(racine)), textes_du_jour(Path(racine)))
        chemin = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data" / "paires.json"
        chemin.write_text(json.dumps(donnees, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("paires.json non écrit : %s", exc)
        return None
