"""JSON dérivé du site web (docs/data/site.json) — calcul Python pur, sans collecte ni LLM.

Sources (déjà produites par le pipeline) : docs/data/latest.json (rapport du jour),
docs/data/tableau_macro.json (cellules affichées, saisies manuelles comprises),
data/registre_macro.json (valeurs numériques et consensus, pour la heatmap) et config.yaml.

Contenu : régime de risque (biais calculé + écart de score risque/refuge), tableau des
indicateurs clés par devise, heatmap des surprises (dernière publication de chaque
indicateur, normalisée comme l'indice de surprise 30 j). Une valeur absente est « n/d »
avec sa raison — jamais une valeur inventée.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from core import controles_macro, registre_macro as rm

log = logging.getLogger(__name__)

VERSION_SCHEMA = 1
ACTUEL, PRECEDENT = "Actuel", "Précédent"

# Colonnes du tableau des indicateurs clés (ordre d'affichage).
COLONNES_CLES = [
    {"id": "taux_directeur", "libelle": "Taux directeur", "type": "macro"},
    {"id": "cpi", "libelle": "CPI a/a", "type": "macro"},
    {"id": "chomage", "libelle": "Chômage", "type": "macro"},
    {"id": "pmi_manufacturier", "libelle": "PMI manuf.", "type": "macro"},
    {"id": "rendement_2a", "libelle": "Taux 2 ans", "type": "macro"},
    {"id": "indice_surprise", "libelle": "Surprise 30 j", "type": "indice"},
    {"id": "score", "libelle": "Confluence", "type": "score"},
    {"id": "biais", "libelle": "Biais du jour", "type": "biais"},
]
LIBELLES_REGIME = {"risk_on": "Risk On", "risk_off": "Risk Off", "neutre": "Neutre"}
LIBELLES_BIAIS = {"haussier": "Haussier", "baissier": "Baissier", "neutre": "Neutre"}
_NOMBRE = re.compile(r"[+-]?\d+(?:[.,]\d+)?")


def _lire(chemin: Path) -> dict | None:
    try:
        return json.loads(chemin.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _nombre(texte) -> float | None:
    """Valeur numérique pour le TRI uniquement (l'affichage garde le texte publié)."""
    if texte is None:
        return None
    exact = rm.vers_nombre(str(texte).replace(" %", "%").strip())
    if exact is not None:
        return exact
    m = _NOMBRE.search(str(texte))
    return float(m.group(0).replace(",", ".")) if m else None


def _fr(texte):
    """« 3.75% » (ForexFactory) -> « 3,75 % » ; autres formats inchangés."""
    if not texte:
        return texte
    t = re.sub(r"(\d)\.(\d)", r"\1,\2", str(texte))
    return re.sub(r"(\d)%", r"\1 %", t)


def _cellule(cellules: dict, indicateur: str, devise: str) -> dict:
    """Cellule « Actuel » du tableau macro -> {texte, valeur_num, date, source, consensus,
    precedent, etat, raison}. Pas de valeur : texte « n/d » + raison affichée."""
    par_type = ((cellules.get(indicateur) or {}).get(devise)) or {}
    actuel, precedent = par_type.get(ACTUEL) or {}, par_type.get(PRECEDENT) or {}
    if actuel.get("etat") == "valeur" and actuel.get("valeur"):
        return {"texte": actuel["valeur"], "valeur_num": _nombre(actuel["valeur"]),
                "date": actuel.get("date"), "source": actuel.get("source"),
                "consensus": _fr(actuel.get("consensus")), "surprise": actuel.get("surprise"),
                "precedent": precedent.get("valeur") if precedent.get("etat") == "valeur" else None,
                "manuel": bool(actuel.get("manuel")), "etat": "valeur", "raison": None}
    return {"texte": "n/d", "valeur_num": None, "date": None, "source": None, "consensus": None,
            "surprise": None, "precedent": None, "manuel": False, "etat": "absent",
            "raison": actuel.get("texte") or "aucune donnée dans le tableau macro"}


def _signe(x: float) -> str:
    """+0,4 / -1,2 / 0,0 (jamais « -0,0 »)."""
    x = round(float(x), 1)
    return "0,0" if x == 0 else f"{x:+.1f}".replace(".", ",")


def _biais_jour(score, cfg: dict) -> str | None:
    """Direction du jour dérivée du score de confluence (seuils de config, calcul Python)."""
    if score is None:
        return None
    if score >= cfg.get("orientation_haussier_min", 60):
        return "haussier"
    if score <= cfg.get("orientation_baissier_max", 40):
        return "baissier"
    return "neutre"


def _regime(rapport: dict, config: dict) -> dict:
    synthese = rapport.get("synthese_globale") or {}
    biais = synthese.get("biais_macro_global")
    cfg_b = config.get("biais_global") or {}
    scores = {d["devise"]: d["score_confluence"] for d in rapport.get("devises", [])
              if d.get("score_confluence") is not None}
    risque = [scores[d] for d in cfg_b.get("devises_risque", []) if d in scores]
    refuge = [scores[d] for d in cfg_b.get("devises_refuge", []) if d in scores]
    ecart = round(sum(risque) / len(risque) - sum(refuge) / len(refuge), 1) if risque and refuge else None
    meta = rapport.get("meta") or {}
    notion_id = str((config.get("notion") or {}).get("database_id") or "").replace("-", "")
    return {
        "biais": biais, "libelle": LIBELLES_REGIME.get(biais, "Indisponible"),
        "ecart_points": ecart, "seuil_points": float(cfg_b.get("seuil_points", 5)),
        "devises_risque": cfg_b.get("devises_risque", []), "devises_refuge": cfg_b.get("devises_refuge", []),
        "explication": ("Écart entre le score de confluence moyen des devises « risque » et celui des "
                        "devises « refuge » (calcul Python) : au-delà du seuil, Risk On ; en deçà de "
                        "son opposé, Risk Off ; sinon Neutre."),
        "driver": synthese.get("commentaire") or None,
        "relecture": (rapport.get("critique") or {}).get("validation", "non_evalue"),
        "date_rapport": meta.get("date_rapport"), "maj": meta.get("genere_le"),
        "type_rapport": meta.get("type_rapport"),
        "nb_devises": len(rapport.get("devises", [])),
        "nb_devises_disponibles": len(scores),
        "notion_url": meta.get("notion_url") or (f"https://www.notion.so/{notion_id}" if notion_id else None),
        "notion_page_du_jour": bool(meta.get("notion_url")),
    }


def _heatmap(tableau: dict, registre: dict | None, config: dict) -> dict:
    """Dernière publication de chaque indicateur (hors données de marché) : surprise
    normalisée signée, même calcul que l'indice 30 j (chômage inversé, plafonnée)."""
    cfg_tm = config.get("tableau_macro") or {}
    cfg_ind_tous = cfg_tm.get("indicateurs") or {}
    plafond = float((cfg_tm.get("indice_surprise") or {}).get("plafond_surprise", 3))
    indicateurs = [i for i in tableau.get("indicateurs", []) if not i.get("marche")]
    cellules = tableau.get("cellules") or {}
    lignes = []
    for devise in tableau.get("devises", []):
        ligne = {"devise": devise, "cellules": {}, "indice_30j": (tableau.get("indice_surprise") or {}).get(devise)}
        for ind in indicateurs:
            c = _cellule(cellules, ind["id"], devise)
            z = None
            case = ((registre or {}).get("cases") or {}).get(f"{devise}|{ind['id']}") or {}
            actuel = case.get("actuel") or {}
            if c["etat"] == "valeur" and actuel.get("date_pub") and cfg_ind_tous.get(ind["id"]):
                for date_pub, s in controles_macro._surprises({"actuel": actuel}, cfg_ind_tous[ind["id"]], plafond):
                    if date_pub == actuel["date_pub"]:
                        z = round(s, 2)
            if c["etat"] == "valeur" and z is None and not c.get("raison"):
                c["raison"] = "pas de consensus publié pour cette publication"
            c["z"] = z
            ligne["cellules"][ind["id"]] = c
        lignes.append(ligne)
    return {"indicateurs": [{"id": i["id"], "libelle": i["libelle"], "inverse": i.get("sens") == "inverse"}
                            for i in indicateurs],
            "plafond": plafond, "lignes": lignes,
            "explication": ("Surprise = (réel − consensus) ÷ écart habituel de l'indicateur, plafonnée à "
                            f"±{plafond:g} ; signe inversé pour le chômage (au-dessus = mauvais). "
                            "Gris : en ligne, pas de consensus ou pas de publication.")}


def construire(racine: str | Path, config: dict | None = None) -> dict:
    racine = Path(racine)
    config = config or yaml.safe_load((racine / "config.yaml").read_text(encoding="utf-8"))
    docs_data = racine / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
    rapport = _lire(docs_data / "latest.json") or {}
    tableau = _lire(docs_data / "tableau_macro.json") or {}
    registre = _lire(racine / config["chemins"]["donnees"] / "registre_macro.json")
    cfg_syn = config.get("synthese_approfondie") or {}
    par_devise = {d["devise"]: d for d in rapport.get("devises", [])}
    indices = tableau.get("indice_surprise") or {}
    cellules = tableau.get("cellules") or {}

    lignes = []
    for devise in tableau.get("devises") or list(config.get("devises", {})):
        entree = par_devise.get(devise) or {}
        score = entree.get("score_confluence")
        cases = {}
        for col in COLONNES_CLES:
            if col["type"] == "macro":
                cases[col["id"]] = _cellule(cellules, col["id"], devise)
            elif col["type"] == "indice":
                ind = indices.get(devise) or {}
                cases[col["id"]] = ({"texte": _signe(ind["indice"]), "valeur_num": ind["indice"],
                                     "tendance": ind.get("tendance"), "n": ind.get("n"), "etat": "valeur",
                                     "source": "calcul Python (registre macro, 30 j)", "date": (tableau.get("maj") or "")[:10],
                                     "raison": None}
                                    if ind.get("indice") is not None else
                                    {"texte": "n/d", "valeur_num": None, "etat": "absent",
                                     "raison": "aucune publication avec consensus sur 30 jours"})
            elif col["type"] == "score":
                cases[col["id"]] = ({"texte": str(score), "valeur_num": score, "etat": "valeur",
                                     "source": "score de confluence (calcul Python)", "date": (rapport.get("meta") or {}).get("date_rapport"),
                                     "raison": None}
                                    if score is not None else
                                    {"texte": "n/d", "valeur_num": None, "etat": "absent",
                                     "raison": entree.get("raison_indisponibilite") or "analyse du jour indisponible"})
            else:
                b = _biais_jour(score, cfg_syn)
                cases[col["id"]] = ({"texte": LIBELLES_BIAIS[b], "valeur_num": score, "code": b, "etat": "valeur",
                                     "profil": entree.get("risk_on_off"),
                                     "source": "dérivé du score (≥ "
                                               f"{cfg_syn.get('orientation_haussier_min', 60)} haussier, ≤ "
                                               f"{cfg_syn.get('orientation_baissier_max', 40)} baissier)",
                                     "raison": None}
                                    if b else {"texte": "n/d", "valeur_num": None, "etat": "absent",
                                               "raison": "score du jour indisponible"})
        lignes.append({"devise": devise, "drapeau": (config.get("devises", {}).get(devise) or {}).get("drapeau", ""),
                       "cellules": cases})

    return {
        "version_schema": VERSION_SCHEMA,
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {"rapport": (rapport.get("meta") or {}).get("genere_le"), "tableau_macro": tableau.get("maj")},
        "regime": _regime(rapport, config) if rapport else {"biais": None, "libelle": "Indisponible",
                                                            "raison": "rapport du jour absent"},
        "colonnes_cles": COLONNES_CLES,
        "indicateurs_cles": lignes,
        "heatmap": _heatmap(tableau, registre, config) if tableau else None,
    }


def ecrire(racine: str | Path, config: dict | None = None) -> Path | None:
    """Écrit docs/data/site.json. Ne lève jamais : le site garde alors la version précédente."""
    try:
        racine = Path(racine)
        config = config or yaml.safe_load((racine / "config.yaml").read_text(encoding="utf-8"))
        donnees = construire(racine, config)
        chemin = racine / config.get("publication_web", {}).get("dossier_docs", "docs") / "data" / "site.json"
        chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return chemin
    except Exception as exc:  # noqa: BLE001
        log.error("site.json non régénéré : %s", exc)
        return None
