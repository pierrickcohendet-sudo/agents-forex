"""Couverture de la matrice d'impact (lot V5, étape 2) : règles par devise pour les engrenages 4, 5, 6 et 8.

Pour chaque indicateur de `matrice_impact.couverture` (config.yaml) :
- mesure du jour (niveau, ou variation sur 4 semaines) sur la série canonique 5 ans (core/indicateurs.py) ;
- seuils FIXES (config) et seuils par PERCENTILE sur 5 ans (85e et 15e de la même mesure) : franchir l'un
  ou l'autre déclenche (« haut » ou « bas ») ; la distance à chaque seuil est publiée (cockpit, radar) ;
- effet sur chaque devise = signe de la lecture classique (simulateur.lecture_classique) × sens du
  franchissement, MAIS seulement si le signe mesuré sur 5 ans le confirme pour CE sens : sensibilité du même
  signe, médiane conforme et borne basse de Wilson à 90 % > 50 % (docs/data/impact.json, horizon 1 mois),
  comme le tableau des conséquences. Sinon : règle « non confirmée » (raison affichée), jamais appliquée.
Une série heurtée (saut d'une séance) neutralise le déclenchement (« au-delà du seuil mais neutralisé »).
"""
from __future__ import annotations

import bisect
from datetime import date, timedelta

from core import indicateurs

WILSON_MIN = 50.0
SCENARIOS = {"haut": "hausse|1", "bas": "baisse|1"}


def _points(historiques: dict | None, cle: str) -> list[tuple[str, float]]:
    return [(d, v) for d, v in indicateurs._points(historiques, cle)]


def _mesures(points: list[tuple[str, float]], mesure: str, unite: str, jours: int) -> list[tuple[str, float]]:
    if mesure == "niveau":
        return points
    dates = [d for d, _ in points]
    sortie = []
    for i, (d, v) in enumerate(points):
        cible = (date.fromisoformat(d) - timedelta(days=jours)).isoformat()
        j = bisect.bisect_right(dates, cible) - 1
        if j < 0:
            continue
        ref = points[j][1]
        if unite == "pb":
            sortie.append((d, (v - ref) * 100))
        elif ref:
            sortie.append((d, (v / ref - 1) * 100))
    return sortie


def _percentile(valeurs: list[float], q: float) -> float | None:
    if len(valeurs) < 60:
        return None
    v = sorted(valeurs)
    k = (len(v) - 1) * q / 100
    i = int(k)
    return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (k - i)


def confirmation(impact: dict | None, indicateur: str, devise: str, sens: str, signe_classique: int) -> dict:
    """{confirmee, raison, n, borne_wilson_90, mediane} pour un sens (« haut » / « bas »)."""
    couple = ((impact or {}).get("couples") or {}).get(f"{indicateur}|{devise}") or {}
    if not couple:
        return {"confirmee": False, "raison": "étude d'impact absente pour ce couple"}
    m = ((couple.get("scenarios") or {}).get(SCENARIOS[sens]) or {}).get("mois") or {}
    sens_txt = "hausse" if sens == "haut" else "baisse"
    base = {"n": m.get("n"), "borne_wilson_90": m.get("borne_wilson_90"), "mediane": m.get("mediane")}
    sensi = couple.get("sensibilite")
    if sensi is None or (sensi > 0) != (signe_classique > 0):
        return {**base, "confirmee": False,
                "raison": f"sensibilité mesurée sur 5 ans ({sensi}) de signe contraire à la lecture classique"}
    if m.get("insuffisant") or not m.get("n"):
        return {**base, "confirmee": False, "raison": f"échantillon insuffisant après une {sens_txt} ({m.get('n') or 0} cas)"}
    if (m.get("lecture_classique") or {}).get("conforme") is not True:
        return {**base, "confirmee": False, "raison": f"médiane à 1 mois après une {sens_txt} contraire à la lecture classique"}
    if (m.get("borne_wilson_90") or 0) <= WILSON_MIN:
        return {**base, "confirmee": False,
                "raison": f"indice faible · {m.get('n')} cas (borne de Wilson {m.get('borne_wilson_90')} % ≤ 50 %)".replace(".", ",")}
    return {**base, "confirmee": True,
            "raison": f"confirmé sur 5 ans : {m.get('part_sens_attendu')} % des {m.get('n')} cas, borne de Wilson {m.get('borne_wilson_90')} %".replace(".", ",")}


def evaluer(config: dict, historiques: dict | None, impact: dict | None) -> dict:
    """{numéro d'engrenage (str): [règle évaluée]} ; jamais d'exception pour une règle (raison à la place)."""
    cfg = ((config or {}).get("matrice_impact") or {}).get("couverture") or {}
    lectures = (((config or {}).get("simulateur") or {}).get("lecture_classique")) or {}
    bas_q, haut_q = cfg.get("percentiles", [15, 85])
    jours = int(cfg.get("fenetre_jours", 28))
    sortie: dict[str, list] = {}
    for numero, liste in (cfg.get("regles") or {}).items():
        sortie[str(numero)] = []
        for spec in liste or []:
            r = {k: spec.get(k) for k in ("indicateur", "serie", "mesure", "unite", "texte", "pedagogie")}
            r["seuils_fixes"] = spec.get("seuils") or {}
            try:
                pts = _points(historiques, spec["serie"])
                if not pts:
                    r["raison"] = "série indisponible"
                    sortie[str(numero)].append(r)
                    continue
                mesures = _mesures(pts, spec.get("mesure", "variation"), spec.get("unite", "%"), jours)
                fin = date.fromisoformat(pts[-1][0])
                cinq_ans = (fin - timedelta(days=int(365.25 * 5))).isoformat()
                fenetre = [v for d, v in mesures if d >= cinq_ans]
                if not mesures:
                    r["raison"] = "historique trop court pour la mesure"
                    sortie[str(numero)].append(r)
                    continue
                valeur = mesures[-1][1]
                p_bas, p_haut = _percentile(fenetre, bas_q), _percentile(fenetre, haut_q)
                haut, bas = r["seuils_fixes"].get("haut"), r["seuils_fixes"].get("bas")
                seuil_haut = min(x for x in (haut, p_haut) if x is not None) if (haut is not None or p_haut is not None) else None
                seuil_bas = max(x for x in (bas, p_bas) if x is not None) if (bas is not None or p_bas is not None) else None
                direction = "haut" if seuil_haut is not None and valeur >= seuil_haut else \
                            "bas" if seuil_bas is not None and valeur <= seuil_bas else None
                declencheur = None
                if direction == "haut":
                    declencheur = "seuil fixe" if haut is not None and valeur >= haut else f"{haut_q}e percentile sur 5 ans"
                elif direction == "bas":
                    declencheur = "seuil fixe" if bas is not None and valeur <= bas else f"{bas_q}e percentile sur 5 ans"
                saut = indicateurs.serie_heurtee(pts) if spec.get("mesure") != "niveau" else None
                r.update({"valeur": round(valeur, 4), "date": pts[-1][0],
                          "source": ((historiques.get("series") or {}).get(spec["serie"]) or {}).get("source"),
                          "percentiles": {str(bas_q): None if p_bas is None else round(p_bas, 4),
                                          str(haut_q): None if p_haut is None else round(p_haut, 4)},
                          "seuil_haut": None if seuil_haut is None else round(seuil_haut, 4),
                          "seuil_bas": None if seuil_bas is None else round(seuil_bas, 4),
                          "direction": direction, "declencheur": declencheur,
                          "neutralise": bool(direction and saut), "serie_heurtee": saut,
                          "n_5a": len(fenetre)})
                devises = {}
                for devise, signe in (lectures.get(spec["indicateur"]) or {}).items():
                    devises[devise] = {"signe_classique": signe,
                                       "haut": confirmation(impact, spec["indicateur"], devise, "haut", signe),
                                       "bas": confirmation(impact, spec["indicateur"], devise, "bas", signe)}
                r["devises"] = devises
            except Exception as exc:  # noqa: BLE001 — une règle en échec n'affecte qu'elle
                r["raison"] = f"calcul en échec : {exc}"[:150]
            sortie[str(numero)].append(r)
    return sortie


def fmt(v: float | None, unite: str | None) -> str:
    if v is None:
        return "n/d"
    if unite == "pb":
        t = f"{v:+.0f} pb"
    elif unite == "%":
        t = f"{v:+.2f} %"
    else:
        t = f"{v:.2f}"
    return t.replace(".", ",").replace("-", "−")
