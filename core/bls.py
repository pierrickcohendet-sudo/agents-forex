"""Rapport sur l'emploi américain détaillé (lot V9, A2) : API publique du Bureau of Labor Statistics (v1, sans clé,
25 requêtes par jour ; une requête pour les 5 séries).

Séries : CES0000000001 (emplois non agricoles, milliers, CVS), LNS14000000 (taux de chômage), LNS13327709 (U-6,
sous-emploi), CES0500000003 (salaire horaire moyen, privé, $), LNS11300000 (taux de participation).
Créations d'emplois = niveau du mois − niveau du mois précédent (millésime du jour). Révisions des deux mois précédents :
chiffre du millésime du jour contre le premier chiffre publié (archive des publications ForexFactory, puis nos propres
millésimes gardés dans data/cache/bls_emploi.json). Le jour même : nouvelle requête après 14:35 Paris le jour du NFP.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

RACINE = Path(__file__).resolve().parents[1]
CHEMIN = RACINE / "data" / "cache" / "bls_emploi.json"
URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
SERIES = {"emplois": "CES0000000001", "chomage": "LNS14000000", "u6": "LNS13327709", "salaire": "CES0500000003",
          "participation": "LNS11300000"}
SOURCE = "Bureau of Labor Statistics, API publique (séries CES0000000001, LNS14000000, LNS13327709, CES0500000003, LNS11300000)"
LIEN = "https://www.bls.gov/news.release/empsit.nr0.htm"
UA = {"User-Agent": "agents-forex/1.0 (donnees publiques)", "Content-Type": "application/json"}


def _lire(chemin: Path) -> dict:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _mois(p: dict) -> str | None:
    m = re.match(r"M(\d{2})$", p.get("period") or "")
    return f"{p['year']}-{m.group(1)}" if m and m.group(1) != "13" else None


def series_depuis_reponse(rep: dict) -> dict[str, list[tuple[str, float, bool]]]:
    """Réponse BLS -> {nom: [(AAAA-MM, valeur, provisoire)] du plus ancien au plus récent}."""
    if rep.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS : {rep.get('status')} {' '.join(rep.get('message') or [])[:200]}")
    inverse = {v: k for k, v in SERIES.items()}
    sortie = {}
    for s in (rep.get("Results") or {}).get("series") or []:
        nom = inverse.get(s.get("seriesID"))
        pts = []
        for p in s.get("data") or []:
            m = _mois(p)
            try:
                v = float(p["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if m:
                pts.append((m, v, any((f or {}).get("code") == "P" for f in p.get("footnotes") or [])))
        if nom:
            sortie[nom] = sorted(pts)
    return sortie


def _k(texte) -> float | None:
    """« 165K » -> 165.0 ; « -4.7K » -> -4.7 (milliers)."""
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*K\s*$", str(texte or ""), re.I)
    return float(m.group(1)) if m else None


def premiers_chiffres(archive: dict | None) -> dict[str, dict]:
    """Premier NFP publié pour chaque mois de référence (le mois qui précède la publication), depuis l'archive."""
    sortie = {}
    for p in ((archive or {}).get("publications") or {}).values():
        if p.get("devise") == "USD" and str(p.get("evenement_en", "")).lower() == "non-farm employment change" and _k(p.get("reel")) is not None:
            d = date.fromisoformat(p["date"])
            a, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
            sortie[f"{a}-{m:02d}"] = {"premier_k": _k(p["reel"]), "consensus_k": _k(p.get("consensus")), "publie_le": p["date"],
                                      "heure_paris": p.get("heure_paris"), "source": p.get("source")}
    return sortie


def calculer(series: dict, archive: dict | None, millesimes: dict | None = None) -> dict:
    """Faits du dernier rapport : créations, révisions des 2 mois précédents, chômage, U-6, salaire, participation."""
    emp = series.get("emplois") or []
    if len(emp) < 4:
        return {"disponible": False, "raison": "série des emplois BLS trop courte"}
    variations = {emp[i][0]: round(emp[i][1] - emp[i - 1][1]) for i in range(1, len(emp))}
    mois = emp[-1][0]
    premiers = {**{m: {"premier_k": v} for m, v in ((millesimes or {}).get("premiers") or {}).items()}, **premiers_chiffres(archive)}
    revisions = []
    for m in [emp[-2][0], emp[-3][0]]:
        pr = (premiers.get(m) or {}).get("premier_k")
        revisions.append({"mois": m, "revise_k": variations.get(m), "premier_k": pr,
                          "ecart_k": None if pr is None else round(variations[m] - pr),
                          "raison": None if pr is not None else "premier chiffre publié non archivé"})

    def dernier(nom, d=1):
        s = series.get(nom) or []
        return ({"valeur": round(s[-1][1], d), "precedent": round(s[-2][1], d) if len(s) > 1 else None, "mois": s[-1][0]} if s
                else {"valeur": None, "raison": f"série {SERIES[nom]} absente de la réponse BLS"})
    sal = series.get("salaire") or []
    info = premiers.get(mois) or {}
    return {"disponible": True, "mois": mois, "creations_k": variations[mois], "provisoire": emp[-1][2],
            "consensus_k": info.get("consensus_k"), "publie_le": info.get("publie_le"), "heure_paris": info.get("heure_paris"),
            "revisions": revisions, "revision_nette_k": (None if any(r["ecart_k"] is None for r in revisions)
                                                        else sum(r["ecart_k"] for r in revisions)),
            "chomage": dernier("chomage"), "u6": dernier("u6"), "participation": dernier("participation"),
            "salaire_horaire": dernier("salaire", 2),
            "salaire_mm_pct": round((sal[-1][1] / sal[-2][1] - 1) * 100, 1) if len(sal) > 1 else None,
            "salaire_aa_pct": round((sal[-1][1] / sal[-13][1] - 1) * 100, 1) if len(sal) > 12 else None,
            "source": SOURCE, "lien": LIEN}


def doit_collecter(cache: dict, maintenant: datetime, archive: dict | None = None) -> bool:
    """Une fois par jour, et une seconde fois le jour d'un NFP après sa publication (14:30 Paris, + 5 min)."""
    dernier = cache.get("collecte_le")
    if not dernier or dernier[:10] != maintenant.date().isoformat():
        return True
    jour = maintenant.date().isoformat()
    nfp = next((p for p in ((archive or {}).get("publications") or {}).values()
                if p.get("date") == jour and str(p.get("evenement_en", "")).lower() == "non-farm employment change"), None)
    vendredi = maintenant.weekday() == 4
    apres = maintenant.astimezone(timezone.utc).strftime("%H:%M") >= "13:35"
    return (vendredi or nfp is not None) and apres and dernier[11:16] < "13:35"


def collecter(racine: Path | None = None, maintenant: datetime | None = None, session=None, chemin: Path | None = None) -> dict:
    """Met à jour data/cache/bls_emploi.json (faits + premiers chiffres gardés) ; ne lève jamais."""
    import requests
    from core import publications_archive as pa
    racine = Path(racine or RACINE)
    chemin = Path(chemin or racine / "data" / "cache" / "bls_emploi.json")
    maintenant = maintenant or datetime.now(timezone.utc)
    cache = _lire(chemin)
    archive = pa.charger(racine / "data" / "cache" / "publications_archive.json")
    if not doit_collecter(cache, maintenant, archive):
        return cache
    try:
        rep = (session or requests).post(URL, json={"seriesid": list(SERIES.values())}, headers=UA, timeout=40)
        rep.raise_for_status()
        series = series_depuis_reponse(rep.json())
        millesimes = cache.get("millesimes") or {}
        faits = calculer(series, archive, millesimes)
        # chaque mois vu pour la première fois : son chiffre devient le « premier chiffre » de référence
        prem = dict(millesimes.get("premiers") or {})
        if faits.get("disponible") and faits["mois"] not in prem:
            prem[faits["mois"]] = faits["creations_k"]
        cache = {"collecte_le": maintenant.isoformat(timespec="minutes"), "faits": faits, "millesimes": {"premiers": prem},
                 "series": {k: v[-14:] for k, v in series.items()}}
    except Exception as exc:  # noqa: BLE001
        log.warning("BLS non collecté : %s", exc)
        cache = {**cache, "erreur": str(exc)[:200], "erreur_le": maintenant.isoformat(timespec="minutes")}
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        log.warning("bls_emploi.json non écrit : %s", exc)
    return cache


def charger(chemin: Path | None = None) -> dict:
    return _lire(Path(chemin or CHEMIN))
