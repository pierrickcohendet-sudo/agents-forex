"""Score de confluence pondéré — calcul en code pur, jamais par le LLM.

Le LLM ne fournit que le sens de chaque indicateur (+1 / -1 / 0) et sa
justification. Ici : score = 50 + 50 * somme(sens*poids) / somme(poids),
borné 0-100 (50 = neutre). Le classement et le biais global en découlent.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _normaliser_sens(valeur) -> int:
    """Accepte 1, -1, 0, '+1', '-1', '0' ; tout le reste vaut 0."""
    try:
        sens = int(str(valeur).replace("+", ""))
    except (TypeError, ValueError):
        return 0
    return max(-1, min(1, sens))


def calculer_score(detail_llm: list[dict], ponderations: dict[str, int]) -> tuple[int, list[dict]]:
    """Retourne (score 0-100, detail_score complet avec poids injectés).

    Tout indicateur configuré absent de la réponse LLM est compté neutre et
    marqué comme tel ; les indicateurs hors configuration sont ignorés.
    """
    par_nom = { (d.get("indicateur") or "").strip(): d for d in (detail_llm or []) }
    total = sum(ponderations.values())
    somme = 0
    detail_final = []
    for nom, poids in ponderations.items():
        item = par_nom.get(nom)
        if item is None:
            sens, justification, source_id = 0, "non évalué (absent de la réponse LLM)", None
        else:
            sens = _normaliser_sens(item.get("sens"))
            justification = str(item.get("justification", ""))[:400]
            source_id = item.get("source_id")
        somme += sens * poids
        detail_final.append({
            "indicateur": nom, "sens": sens, "poids": poids,
            "justification": justification, "source_id": source_id,
        })
    score = round(50 + 50 * somme / total) if total else 50
    return max(0, min(100, score)), detail_final


PROFIL_VERS_BIAIS = {"risque": "on", "refuge": "off", "neutre": "neutre"}


def biais_structurel(profil_risque: str) -> str:
    """Biais Risk On/Off STRUCTUREL d'une devise, dérivé de son profil configuré
    (grille des banques centrales) — jamais choisi par le LLM. La direction du
    jour est portée par le score de confluence, pas par ce champ."""
    return PROFIL_VERS_BIAIS.get(str(profil_risque).lower(), "neutre")


def ponderations_devise(config: dict, devise: str) -> dict[str, int]:
    """Pondérations effectives : bloc spécifique `ponderations_par_devise` s'il
    existe pour cette devise, sinon le bloc global."""
    specifiques = (config.get("ponderations_par_devise") or {}).get(devise)
    return dict(specifiques) if specifiques else dict(config["ponderations"])


def classer(devises: list[dict]) -> list[dict]:
    """Classement par score décroissant -> [{rang, devise, score_confluence, risk_on_off}].

    Les devises sans score (analyse indisponible : score_confluence None ou
    absent) sont EXCLUES du classement — jamais un plantage : un échec sur une
    devise ne coûte que cette devise."""
    notees = [d for d in devises if d.get("score_confluence") is not None]
    exclues = [d["devise"] for d in devises if d.get("score_confluence") is None]
    if exclues:
        log.warning("Classement : %d devise(s) exclue(s), analyse indisponible : %s",
                    len(exclues), ", ".join(exclues))
    ordre = sorted(notees, key=lambda d: d["score_confluence"], reverse=True)
    return [
        {"rang": i + 1, "devise": d["devise"],
         "score_confluence": d["score_confluence"], "risk_on_off": d["risk_on_off"]}
        for i, d in enumerate(ordre)
    ]


def biais_macro_global(devises: list[dict], config_biais: dict) -> str:
    """risk_on si le bloc risque (AUD/NZD/CAD...) surperforme le bloc refuge
    (JPY/CHF/USD...) d'au moins `seuil_points` de score moyen ; risk_off à
    l'inverse ; neutre sinon."""
    scores = {d["devise"]: d["score_confluence"] for d in devises
              if d.get("score_confluence") is not None}
    risque = [scores[d] for d in config_biais.get("devises_risque", []) if d in scores]
    refuge = [scores[d] for d in config_biais.get("devises_refuge", []) if d in scores]
    if not risque or not refuge:
        return "neutre"
    ecart = sum(risque) / len(risque) - sum(refuge) / len(refuge)
    seuil = float(config_biais.get("seuil_points", 5))
    if ecart >= seuil:
        return "risk_on"
    if ecart <= -seuil:
        return "risk_off"
    return "neutre"
