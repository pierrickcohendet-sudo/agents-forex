"""Registre permanent des valeurs macro (data/registre_macro.json, versionné).

Une entrée par couple (indicateur, devise) : dernière valeur publiée, valeur
précédente, consensus de la prochaine publication, dates, source, historique.
INDÉPENDANT de la fenêtre de 7 jours envoyée au LLM et de la rétention du
calendrier glissant : une case garde sa dernière valeur jusqu'à la publication
suivante. Code pur, aucun LLM — le surprise (▲▼=) est calculé ici.

Source des valeurs : page « mois » de ForexFactory (agents/collecte_forexfactory_mois.py)
et taux directeurs de repli (config.yaml / FRED). Chaque valeur garde son
origine ; rien n'est jamais estimé ni complété par un modèle.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

VERSION = 1
MAX_HISTORIQUE = 60
TYPES = ("Actuel", "Précédent", "Prévision")

_MOTIF_NOMBRE = re.compile(r"^([+-]?\d+(?:[.,]\d+)?)\s*([%KMBT]?)$")
_ECHELLE = {"": 1.0, "%": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def cle(indicateur: str, devise: str) -> str:
    return f"{devise}|{indicateur}"


def charger(chemin: str | Path) -> dict:
    try:
        brut = json.loads(Path(chemin).read_text(encoding="utf-8"))
        if isinstance(brut, dict) and isinstance(brut.get("cases"), dict):
            return brut
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Registre macro illisible (%s) — repart d'un registre vide", exc)
    return {"version": VERSION, "maj": None, "cases": {}}


def sauver(registre: dict, chemin: str | Path) -> None:
    registre["version"] = VERSION
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    Path(chemin).write_text(json.dumps(registre, ensure_ascii=False, indent=1, sort_keys=True),
                            encoding="utf-8")


def vers_nombre(texte: str | None) -> float | None:
    """« 2.4% » -> 2.4 ; « 29K » -> 29000 ; « -105.6B » -> -1.056e11. None si illisible."""
    if texte is None:
        return None
    m = _MOTIF_NOMBRE.match(str(texte).strip())
    if not m:
        return None
    return float(m.group(1).replace(",", ".")) * _ECHELLE[m.group(2)]


def symbole_surprise(reel: str | None, consensus: str | None) -> str | None:
    """▲ réel au-dessus du consensus, ▼ en dessous, = en ligne. None si l'un des
    deux est absent ou illisible (jamais de symbole deviné)."""
    a, b = vers_nombre(reel), vers_nombre(consensus)
    if a is None or b is None:
        return None
    if abs(a - b) <= 1e-9 * max(1.0, abs(b)):
        return "="
    return "▲" if a > b else "▼"


def _date_iso(dateline: int | None) -> str | None:
    if not dateline:
        return None
    return datetime.fromtimestamp(int(dateline), tz=timezone.utc).date().isoformat()


def _correspond(evenement: dict, devise: str, entree: dict) -> bool:
    if evenement.get("devise") != devise:
        return False
    if entree.get("id") is not None:
        return evenement.get("ebase_id") == entree["id"]
    return evenement.get("nom") == entree.get("nom")


def _case(registre: dict, indicateur: str, devise: str) -> dict:
    return registre["cases"].setdefault(cle(indicateur, devise), {
        "indicateur": indicateur, "devise": devise, "statut": "a_initialiser",
        "actuel": None, "precedent": None, "prevision": None,
        "historique": [], "ecrit_notion": {}})


def _archiver(case: dict, ancien: dict | None) -> None:
    if not ancien or ancien.get("origine") == "precedent_ff" and not ancien.get("date_pub"):
        return
    case["historique"].append({k: ancien.get(k) for k in
                               ("valeur", "date_pub", "consensus", "surprise", "source")})
    del case["historique"][:-MAX_HISTORIQUE]


def integrer_evenements(registre: dict, evenements: list[dict], cfg_tm: dict,
                        maintenant: datetime | None = None) -> dict:
    """Fusionne les événements ForexFactory dans le registre, case par case.
    Retourne {mises_a_jour, introuvables: [...], absents}. Un événement qui
    n'est plus trouvé n'efface JAMAIS la dernière valeur connue."""
    maintenant = maintenant or datetime.now(timezone.utc)
    bilan = {"mises_a_jour": 0, "introuvables": [], "absents": 0}
    for indicateur, par_devise in cfg_tm["correspondances"].items():
        for devise, mapping in par_devise.items():
            case = _case(registre, indicateur, devise)
            if mapping.get("absent"):
                case.update(statut="non_applicable", absent=mapping["absent"])
                bilan["absents"] += 1
                continue
            case["etiquette"] = mapping.get("etiquette")
            trouves = [e for e in evenements
                       if any(_correspond(e, devise, ent) for ent in mapping.get("ff", []))]
            if not trouves:
                if case["actuel"] is None:
                    bilan["introuvables"].append(cle(indicateur, devise))
                continue
            publies = [e for e in trouves if e["reel"]]
            derniere = max(publies, key=lambda e: e["dateline"]) if publies else None
            if derniere is not None:
                _integrer_publication(case, derniere)
            seuil = derniere["dateline"] if derniere else 0
            a_venir = [e for e in trouves if not e["reel"] and e["dateline"] > seuil]
            suivante = min(a_venir, key=lambda e: e["dateline"]) if a_venir else None
            if suivante is not None:
                case["prevision"] = {"valeur": suivante["prevision"],
                                     "date_pub": _date_iso(suivante["dateline"]),
                                     "dateline": suivante["dateline"], "nom_ff": suivante["nom"]}
                if case["actuel"] is None and suivante["precedent"]:
                    # Dernier chiffre publié connu via le « précédent » de la prochaine
                    # publication (réel, éventuellement révisé) — date inconnue, dite telle.
                    case["actuel"] = {"valeur": suivante["revision"] or suivante["precedent"],
                                      "date_pub": None, "dateline": None, "consensus": None,
                                      "surprise": None, "source": "ForexFactory (précédent)",
                                      "origine": "precedent_ff"}
            case["statut"] = "ok"
            case["maj"] = maintenant.isoformat(timespec="seconds")
            bilan["mises_a_jour"] += 1
    registre["maj"] = maintenant.isoformat(timespec="seconds")
    return bilan


def _integrer_publication(case: dict, e: dict) -> None:
    ancien = case["actuel"]
    if ancien and ancien.get("dateline") and e["dateline"] < ancien["dateline"]:
        return  # publication plus ancienne que celle déjà enregistrée : ignorée
    nouvelle = {"valeur": e["reel"], "valeur_num": vers_nombre(e["reel"]),
                "date_pub": _date_iso(e["dateline"]), "dateline": e["dateline"],
                "consensus": e["prevision"], "surprise": symbole_surprise(e["reel"], e["prevision"]),
                "source": "ForexFactory", "ebase_id": e["ebase_id"], "nom_ff": e["nom"],
                "url": e.get("url")}
    valeur_precedente = e["revision"] or e["precedent"]
    nouvelle_publication = not ancien or ancien.get("dateline") != e["dateline"]
    if nouvelle_publication:
        _archiver(case, ancien)
        date_prec = ancien.get("date_pub") if ancien else None
    else:
        date_prec = (case["precedent"] or {}).get("date")
    case["actuel"] = nouvelle
    case["precedent"] = ({"valeur": valeur_precedente, "date": date_prec,
                          "revise": bool(e["revision"])} if valeur_precedente else None)


def integrer_taux(registre: dict, taux: dict[str, dict]) -> None:
    """Taux directeurs de repli (config.yaml / FRED) : n'écrasent jamais une
    valeur ForexFactory plus récente (décision publiée un jour de réunion)."""
    for devise, t in taux.items():
        case = _case(registre, "taux_directeur", devise)
        if case.get("statut") == "non_applicable" or t.get("taux") is None:
            continue
        actuel = case["actuel"]
        if actuel and (actuel.get("date_pub") or "") >= str(t.get("date") or ""):
            continue
        valeur = f"{float(t['taux']):.2f}%"
        case["actuel"] = {"valeur": valeur, "valeur_num": float(t["taux"]),
                          "date_pub": str(t.get("date")), "dateline": None, "consensus": None,
                          "surprise": None, "source": t.get("source", "config"),
                          "origine": "taux_config"}
        if case["statut"] == "a_initialiser":
            case["statut"] = "ok"


# ---------------------------------------------------------------- formatage
def _fr(valeur: str, unite: str) -> str:
    v = str(valeur).strip().replace(".", ",")
    if v.endswith("%"):
        return v[:-1].strip() + " %"
    if unite == "%" and vers_nombre(valeur) is not None:
        return v + " %"
    return v


def _jj_mm(date_iso: str | None) -> str | None:
    return f"{date_iso[8:10]}/{date_iso[5:7]}" if date_iso and len(date_iso) >= 10 else None


def texte_officiel(case: dict, type_valeur: str, unite: str) -> str:
    """Texte de la cellule d'après le registre seul (hors saisies manuelles)."""
    if case.get("statut") == "non_applicable":
        return case.get("absent") or "non publié dans ce pays"
    etiquette = f" [{case['etiquette']}]" if case.get("etiquette") else ""
    if type_valeur == "Actuel":
        a = case.get("actuel")
        if not a or a.get("valeur") in (None, ""):
            return "n/d — historique à initialiser"
        d = _jj_mm(a.get("date_pub"))
        return f"{_fr(a['valeur'], unite)}{etiquette} ({d or 'date n/d'})" + \
               (f" {a['surprise']}" if a.get("surprise") else "")
    if type_valeur == "Précédent":
        p = case.get("precedent")
        if not p or not p.get("valeur"):
            return "n/d"
        d = _jj_mm(p.get("date"))
        return f"{_fr(p['valeur'], unite)}{etiquette}" + (f" ({d})" if d else "")
    p = case.get("prevision")
    if not p:
        return "prochaine pub. n/d"
    d = _jj_mm(p.get("date_pub"))
    if not p.get("valeur"):
        return f"prochaine pub. {d}" if d else "prochaine pub. n/d"
    return f"{_fr(p['valeur'], unite)}{etiquette}" + (f" ({d})" if d else "")
