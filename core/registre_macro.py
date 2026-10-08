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
            publies = sorted((e for e in trouves if e["reel"]), key=lambda e: e["dateline"])
            derniere = publies[-1] if publies else None
            # Chronologique : plusieurs mois fournis d'un coup (amorçage) construisent
            # l'historique ; une publication plus ancienne que le registre est ignorée.
            for e in publies:
                _integrer_publication(case, e)
            seuil = derniere["dateline"] if derniere else 0
            a_venir = [e for e in trouves if not e["reel"] and e["dateline"] > seuil]
            suivante = min(a_venir, key=lambda e: e["dateline"]) if a_venir else None
            existante = case.get("prevision") or {}
            garder = bool(existante.get("dateline") and suivante is not None
                          and existante["dateline"] < suivante["dateline"]
                          and ((case["actuel"] or {}).get("dateline") or 0) < existante["dateline"])
            if suivante is not None and not garder:
                case["prevision"] = {"valeur": suivante["prevision"],
                                     "date_pub": _date_iso(suivante["dateline"]),
                                     "dateline": suivante["dateline"], "nom_ff": suivante["nom"],
                                     "impact": suivante.get("impact")}
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


def _periode_fr(periode: str | None) -> str | None:
    return f"pér. {periode[5:7]}/{periode[2:4]}" if periode and len(periode) >= 7 else None


def _etiquette(case: dict) -> str:
    return f" [{case['etiquette']}]" if case.get("etiquette") else ""


def valeur_cellule(case: dict, type_valeur: str, unite: str) -> str:
    """Texte d'UNE cellule (valeur seule, sans date ni symbole de surprise —
    ceux-ci ont leur propre colonne). Toujours une valeur réelle sourcée OU une
    explication explicite, jamais une case vide ni une valeur estimée."""
    if case.get("statut") == "non_applicable":
        return case.get("absent") or "non publié dans ce pays"
    etiquette = _etiquette(case)
    if type_valeur == "Actuel":
        a = case.get("actuel")
        if not a or a.get("valeur") in (None, ""):
            return "n/d — historique à initialiser"
        return f"{_fr(a['valeur'], unite)}{etiquette}"
    if type_valeur == "Précédent":
        p = case.get("precedent")
        if not p or not p.get("valeur"):
            return "n/d"
        return f"{_fr(p['valeur'], unite)}{etiquette}" + (" (révisé)" if p.get("revise") else "")
    if case.get("marche"):
        return "— (donnée de marché)"
    p = case.get("prevision")
    if p and p.get("valeur"):
        return f"{_fr(p['valeur'], unite)}{etiquette}"
    projection = case.get("projection")
    if projection:
        return f"proj. BC {_fr(projection['valeur'], unite)} ({projection['horizon']})"
    return "consensus à venir" if p else "n/d"


def date_publication(case: dict) -> str | None:
    """Date ISO de la dernière publication (None si inconnue ou FRED : période seulement)."""
    return (case.get("actuel") or {}).get("date_pub")


def prochaine_publication(case: dict) -> str | None:
    """Date-heure ISO (UTC) de la prochaine publication connue."""
    dateline = (case.get("prevision") or {}).get("dateline")
    if not dateline:
        return None
    return datetime.fromtimestamp(int(dateline), tz=timezone.utc).isoformat(timespec="minutes")


def surprise_cellule(case: dict) -> str | None:
    return (case.get("actuel") or {}).get("surprise")


def source_cellule(case: dict) -> str:
    if case.get("statut") == "non_applicable":
        return "—"
    a = case.get("actuel") or {}
    morceaux = [a.get("source") or ("n/d" if a.get("valeur") is None else "")]
    if a.get("periode") and not a.get("date_pub"):
        morceaux.append(_periode_fr(a["periode"]))
    if not (case.get("prevision") or {}).get("valeur") and case.get("projection"):
        pr = case["projection"]
        morceaux.append(f"proj. BC : {pr.get('source', 'banque centrale')} ({pr.get('serie', '')})")
    return " · ".join(m for m in morceaux if m)


def texte_officiel(case: dict, type_valeur: str, unite: str) -> str:
    """Texte COMPLET d'une cellule (valeur + date + surprise) : matrice du
    dashboard web. Les colonnes Notion utilisent les fonctions ci-dessus."""
    base = valeur_cellule(case, type_valeur, unite)
    if case.get("statut") == "non_applicable":
        return base
    if type_valeur == "Actuel":
        a = case.get("actuel") or {}
        if a.get("valeur") in (None, ""):
            return base
        d = _jj_mm(a.get("date_pub")) or _periode_fr(a.get("periode")) or "date n/d"
        return f"{base} ({d})" + (f" {a['surprise']}" if a.get("surprise") else "")
    if type_valeur == "Précédent":
        d = _jj_mm((case.get("precedent") or {}).get("date")) or _periode_fr((case.get("precedent") or {}).get("periode"))
        return base + (f" ({d})" if d and not base.startswith("n/d") else "")
    d = _jj_mm((case.get("prevision") or {}).get("date_pub"))
    if base == "consensus à venir":
        return f"prochaine pub. {d}" if d else "prochaine pub. n/d"
    if base.startswith("proj. BC") and d:
        return f"{base} · pub. {d}"
    if d and not base.startswith(("n/d", "—")):
        return f"{base} ({d})"
    return "prochaine pub. n/d" if base == "n/d" else base


def _texte_projection(projection: dict, unite: str, jj_mm: str | None) -> str:
    """Consensus pas encore publié : projection OFFICIELLE de la banque centrale,
    étiquetée « proj. BC » avec son horizon (jamais présentée comme un consensus)."""
    texte = f"proj. BC {_fr(projection['valeur'], unite)} ({projection['horizon']})"
    return texte + (f" · pub. {jj_mm}" if jj_mm else "")


# --------------------------------------------------------- FRED / projections
def integrer_fred(registre: dict, resultat_fred: dict) -> int:
    """Repli et contrôle croisé. Une valeur FRED ne REMPLACE jamais une valeur
    ForexFactory datée : elle ne comble que les cases sans publication connue
    (ou reconstruites depuis le « précédent »), et sert au contrôle de divergence."""
    comblees = 0
    for cle_case, v in resultat_fred.get("valeurs", {}).items():
        devise, indicateur = cle_case.split("|")
        case = registre["cases"].get(cle(indicateur, devise))
        if case is None:
            continue
        case["fred"] = {k: v.get(k) for k in ("valeur", "periode", "precedente", "serie")}
        if v.get("usage") not in ("repli", "repli_et_controle"):
            continue
        a = case.get("actuel")
        if a is None or a.get("origine") == "precedent_ff":
            case["actuel"] = {"valeur": v["valeur"], "valeur_num": vers_nombre(v["valeur"]),
                              "date_pub": None, "dateline": None, "periode": v["periode"],
                              "consensus": None, "surprise": None,
                              "source": f"FRED ({v['serie']})", "origine": "fred"}
            if v.get("precedente"):
                case["precedent"] = {"valeur": v["precedente"], "date": None, "revise": False}
            if v.get("etiquette"):
                case["etiquette"] = v["etiquette"]
            if case.get("statut") in ("a_initialiser", None):
                case["statut"] = "ok"
            comblees += 1
    return comblees


def integrer_projections(registre: dict, resultat_fred: dict) -> None:
    for cle_case, p in resultat_fred.get("projections", {}).items():
        devise, indicateur = cle_case.split("|")
        case = registre["cases"].get(cle(indicateur, devise))
        if case is not None:
            case["projection"] = p


def cases_sans_date_suivante(registre: dict, cfg_tm: dict) -> list[str]:
    """Cases (hors « non applicable ») dont la prochaine publication n'est pas connue."""
    return [k for k, c in registre["cases"].items()
            if c.get("statut") != "non_applicable" and not c.get("prevision")]


def publications_a_cibler(registre: dict, cfg_ff: dict, maintenant: datetime,
                          deja_tentees: dict[str, int]) -> list[str]:
    """Clés « {case}@{dateline} » des publications d'impact fort/moyen dont l'heure
    est passée depuis au moins delai_apres_publication_min minutes (et moins de
    12 h) et dont le « réel » manque encore dans le registre."""
    delai = int(cfg_ff.get("delai_apres_publication_min", 15)) * 60
    impacts = set(cfg_ff.get("impacts_cibles", ["high", "medium"]))
    maxi = int(cfg_ff.get("tentatives_ciblees_max", 2))
    cibles = []
    now = int(maintenant.timestamp())
    for k, c in registre["cases"].items():
        p = c.get("prevision")
        if not p or not p.get("dateline") or p.get("impact") not in impacts:
            continue
        ecoule = now - int(p["dateline"])
        if not (delai <= ecoule <= 12 * 3600):
            continue
        a = c.get("actuel") or {}
        if a.get("dateline") and a["dateline"] >= p["dateline"]:
            continue
        cle_cible = f"{k}@{p['dateline']}"
        if deja_tentees.get(cle_cible, 0) < maxi:
            cibles.append(cle_cible)
    return cibles
