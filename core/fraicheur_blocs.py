"""Points de fraîcheur des blocs du site (lot V8, règle corrigée en V8.1) -> docs/data/fraicheur.json.
Règle calculée ici, le site affiche le point et l'infobulle.

Chaque SÉRIE est jugée sur la date de sa dernière observation et sa fréquence normale (en jours ouvrés), jamais sur
l'heure de génération du fichier : un fichier régénéré à l'instant peut porter une valeur vieille d'une semaine.
  vert   : retard <= fréquence normale de la série ;
  orange : au-delà de la fréquence normale ;
  rouge  : plus de 5 jours ouvrés au-delà de la fréquence normale (ou date inconnue).
Un bloc prend la couleur de sa série la plus en retard, et l'infobulle la nomme
(« Brent : dernière valeur 27/10, 7 jours ouvrés de retard »). Les sources sans série lisible dans les fichiers publiés
(calendrier, macro, COT…) sont jugées par l'état déjà calculé dans sources.json (même principe : dernière donnée et
fréquence normale de la source).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SEUIL_ROUGE_JOURS_OUVRES = 5          # au-delà de la fréquence normale
RANG = {"vert": 0, "orange": 1, "rouge": 2}

# Fréquence normale (jours ouvrés entre la date de la dernière observation et aujourd'hui)
NORMAL_PAR_CATEGORIE = {"fx": 1, "or": 1, "actions": 2, "dollar": 2, "taux": 3, "vix": 3, "petrole": 5}
NORMAL_PAR_SERIE = {"DCOILBRENTEU": 5, "DCOILWTICO": 5,      # EIA : prix spot publiés une fois par semaine, repris par FRED
                    "DTWEXBGS": 7,                            # Fed H.10 : publication hebdomadaire (lundi, semaine écoulée)
                    "VIXCLS": 3}
NORMAL_COTATION = 1                                           # cotation de séance (Twelve Data /quote)
NORMAL_COURS = 1                                              # cours de clôture quotidiens (Twelve Data)

# Bloc du site -> (fichier et champ d'horodatage (information seulement), extracteurs de séries, sources de sources.json)
BLOCS = {
    "briefing": ("briefing", "genere_le", ["point_marche", "seance"], ["ff_mois"]),
    "rapport": ("rapport_jour", "genere_le", ["point_marche"], ["fred", "ff_mois"]),
    "point_marche": ("rapport_jour", "genere_le", ["point_marche"], []),
    "agenda": ("agenda", "genere_le", [], ["ff_mois", "ff_flux"]),
    "tableau_macro": ("tableau_macro", "maj", [], ["ff_mois", "fred", "officielles"]),
    "profil": ("profil_devises", "genere_le", ["cours"], ["fred"]),
    "engrenages": ("dossiers", "genere_le", ["point_marche"], ["fred", "cftc", "eia"]),
    "cours": ("cours", "genere_le", ["cours"], ["fed_h10"]),
    "force": ("force_devises", "genere_le", ["cours"], []),
    "paires": ("paires", "genere_le", ["cours"], []),
    "seance": ("seance", "maj", ["seance"], []),
    "marche": ("marche", "maj", ["marche"], []),
}


def jours_ouvres(debut: date, fin: date) -> int:
    n, d = 0, debut
    while d < fin:
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


def _jour(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def etat_serie(nom: str, derniere, normal: int, aujourd: date) -> dict:
    """Une série : {nom, derniere, retard, normal, etat, texte} (fonction pure, testée)."""
    d = _jour(derniere)
    if d is None:
        return {"nom": nom, "derniere": None, "retard": None, "normal": normal, "etat": "rouge",
                "texte": f"{nom} : date de la dernière valeur inconnue"}
    retard = jours_ouvres(d, aujourd)
    etat = "vert" if retard <= normal else "rouge" if retard > normal + SEUIL_ROUGE_JOURS_OUVRES else "orange"
    jo = f"{retard} jour{'s' if retard > 1 else ''} ouvré{'s' if retard > 1 else ''}"
    texte = (f"{nom} : dernière valeur {d:%d/%m} ({jo}, normal : {normal} au plus)" if etat == "vert"
             else f"{nom} : dernière valeur {d:%d/%m}, {jo} de retard (normal : {normal} au plus)")
    return {"nom": nom, "derniere": d.isoformat(), "retard": retard, "normal": normal, "etat": etat, "texte": texte}


def etat_source(s: dict) -> dict:
    """Source de sources.json (sans série lisible) : état déjà calculé là-bas sur sa dernière donnée."""
    f = s.get("fraicheur") or {}
    etat = f.get("etat") if f.get("etat") in RANG else "rouge"
    d = _jour(s.get("derniere_donnee"))
    texte = f"{s.get('nom')} : dernière donnée {d:%d/%m}" if d else f"{s.get('nom')} : dernière donnée inconnue"
    if f.get("texte"):
        texte += f", {f['texte']}"
    return {"nom": s.get("nom"), "derniere": d.isoformat() if d else None, "retard": f.get("age_jours"),
            "normal": f.get("normal_jours"), "etat": etat, "texte": texte}


def etat_bloc(series: list[dict], maj: datetime | None = None) -> dict:
    """Couleur de la série la plus en retard ; l'infobulle la nomme (fonction pure, testée)."""
    quand = f" · fichier généré le {maj.astimezone(timezone.utc):%d/%m %H:%M} UTC" if maj else ""
    if not series:
        return {"etat": "rouge", "texte": "aucune série datée pour ce bloc" + quand, "series": []}
    pire = max(series, key=lambda s: (RANG[s["etat"]], s["retard"] if isinstance(s.get("retard"), (int, float)) else 10 ** 6))
    if pire["etat"] == "vert":
        texte = f"{len(series)} série{'s' if len(series) > 1 else ''} dans leur fréquence normale · la plus ancienne : {pire['texte']}"
    else:
        autres = [s for s in series if s is not pire and s["etat"] != "vert"]
        texte = pire["texte"] + (f" ; {len(autres)} autre{'s' if len(autres) > 1 else ''} série{'s' if len(autres) > 1 else ''} en retard" if autres else "")
    return {"etat": pire["etat"], "texte": texte + quand, "series": series}


# ------------------------------------------------------------------ extracteurs (fichiers publiés -> séries)
def _point_marche(docs: dict, aujourd: date) -> list[dict]:
    lignes = ((docs.get("rapport_jour") or {}).get("point_marche") or {}).get("lignes") or []
    sortie = []
    for l in lignes:
        serie = l.get("serie_30j") or []
        derniere = serie[-1][0] if serie else l.get("heure")
        code = next((c for c in NORMAL_PAR_SERIE if c in str(l.get("source") or "")), None)
        normal = NORMAL_PAR_SERIE[code] if code else NORMAL_PAR_CATEGORIE.get(l.get("categorie"), 2)
        sortie.append(etat_serie(l.get("actif") or "série", derniere, normal, aujourd))
    return sortie


def _seance(docs: dict, aujourd: date) -> list[dict]:
    cot = (docs.get("seance") or {}).get("cotations") or {}
    return [etat_serie(f"{p} (cotation)", c.get("heure_utc"), NORMAL_COTATION, aujourd) for p, c in cot.items()]


def _cours(docs: dict, aujourd: date) -> list[dict]:
    dev = (docs.get("cours") or {}).get("devises") or {}
    return [etat_serie(f"cours {c}", v.get("date"), NORMAL_COURS, aujourd) for c, v in dev.items()]


def _marche(docs: dict, aujourd: date) -> list[dict]:
    sortie = []
    for g in ((docs.get("marche") or {}).get("graphiques") or {}).values():
        for c in (g.get("courbes") or {}).values():
            pts = c.get("points") or []
            sortie.append(etat_serie(c.get("libelle") or "série", c.get("date") or (pts[-1][0] if pts else None),
                                     NORMAL_PAR_SERIE.get(c.get("serie_id"), 3), aujourd))
    return sortie


EXTRACTEURS = {"point_marche": _point_marche, "seance": _seance, "cours": _cours, "marche": _marche}
FICHIERS = {"point_marche": "rapport_jour", "seance": "seance", "cours": "cours", "marche": "marche"}


def _horodatage(v) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def calculer(docs: dict, sources: dict, maintenant: datetime) -> dict:
    """docs : {nom de fichier: contenu} ; sources : {id: source}. Pur : testé sans disque."""
    aujourd = maintenant.date()
    blocs = {}
    for bloc, (fichier, champ, extracteurs, ids) in BLOCS.items():
        if fichier not in docs:
            blocs[bloc] = {"etat": "rouge", "texte": f"{fichier}.json absent", "maj": None, "series": []}
            continue
        series = []
        for e in extracteurs:
            if FICHIERS[e] in docs:
                series += EXTRACTEURS[e](docs, aujourd)
            else:
                series.append({"nom": f"{FICHIERS[e]}.json", "derniere": None, "retard": None, "normal": None,
                               "etat": "rouge", "texte": f"{FICHIERS[e]}.json absent"})
        series += [etat_source(sources[i]) for i in ids if i in sources]
        maj = _horodatage(docs[fichier].get(champ))
        blocs[bloc] = {**etat_bloc(series, maj), "maj": maj.isoformat() if maj else None}
    return blocs


def ecrire(racine: str | Path, config: dict, maintenant: datetime | None = None) -> dict | None:
    try:
        maintenant = maintenant or datetime.now(timezone.utc)
        dossier = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
        docs = {}
        for nom in {f for f, *_ in BLOCS.values()} | set(FICHIERS.values()):
            try:
                docs[nom] = json.loads((dossier / f"{nom}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        sources = {s["id"]: s for s in (docs.get("sources") or {}).get("sources") or [] if not s.get("retiree")}
        if not sources:
            try:
                sources = {s["id"]: s for s in json.loads((dossier / "sources.json").read_text(encoding="utf-8")).get("sources") or []
                           if not s.get("retiree")}
            except (OSError, ValueError):
                sources = {}
        donnees = {"genere_le": maintenant.isoformat(timespec="seconds"), "blocs": calculer(docs, sources, maintenant),
                   "regle": "chaque série est jugée sur la date de sa dernière observation et sa fréquence normale (jours "
                            "ouvrés) ; vert : dans la fréquence ; orange : au-delà ; rouge : plus de 5 jours ouvrés au-delà. "
                            "Un bloc prend la couleur de sa série la plus en retard."}
        (dossier / "fraicheur.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("fraicheur.json non écrit : %s", exc)
        return None
