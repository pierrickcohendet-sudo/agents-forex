"""Historique des publications ForexFactory (lot V14, A1.3).

L'archive du site (data/cache/publications_archive.json) ne commence qu'au 01/10/2026 : 7 publications sur 170 ont au
moins 3 points. Reprise UNIQUE des 12 derniers mois : une page « mois » ForexFactory par requête (url_mois), au plus 2 par
jour, dans le plafond commun de 6 requêtes par jour (data/cache/forexfactory_requetes.json) ; reprise là où elle s'est
arrêtée au run suivant. Les points sont gardés dans data/cache/ff_historique.json :
  {"mois": {"oct.2026": {"lu_le", "statut", "n", "note"}}, "series": {"USD|cpi y/y": {"AAAA-MM-JJ": [réel, prévision, id]}}}
Une page refusée (403, défi Cloudflare, robots.txt) n'est jamais forcée : le mois est noté en échec et retenté au plus
une fois par jour ; le client de core/scraping.py met le site en liste noire après deux 403.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

CHEMIN = Path("data") / "cache" / "ff_historique.json"
MOIS_EN = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
N_MOIS = 12
MAX_PAR_JOUR = 2
N_POINTS = 6


def lire(racine_cache: Path) -> dict:
    try:
        d = json.loads((Path(racine_cache) / "ff_historique.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def ecrire(racine_cache: Path, d: dict) -> None:
    chemin = Path(racine_cache) / "ff_historique.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def mois_a_reprendre(aujourd: date, n: int = N_MOIS) -> list[str]:
    """Les n mois qui précèdent le mois en cours, du plus récent au plus ancien : ['oct.2026', …, 'nov.2025']."""
    sortie = []
    a, m = aujourd.year, aujourd.month
    for _ in range(n):
        m -= 1
        if m == 0:
            a, m = a - 1, 12
        sortie.append(f"{MOIS_EN[m - 1]}.{a}")
    return sortie


def etat(d: dict, aujourd: date) -> dict:
    """{lus, restants, termine, echecs} sur les 12 mois à reprendre."""
    cibles = mois_a_reprendre(aujourd)
    mois = d.get("mois") or {}
    lus = [m for m in cibles if (mois.get(m) or {}).get("statut") == "lu"]
    restants = [m for m in cibles if m not in lus]
    return {"lus": lus, "restants": restants, "termine": not restants, "n_lus": len(lus), "n_total": len(cibles),
            "echecs": {m: (mois.get(m) or {}).get("note") for m in restants if (mois.get(m) or {}).get("statut") == "echec"},
            "points": sum(len(v) for v in (d.get("series") or {}).values())}


def cle(devise: str | None, nom: str | None) -> str:
    nom_n = re.sub(r"\s+", " ", str(nom or "").strip().lower())
    return f"{str(devise or '').upper()}|{nom_n}"


def integrer(d: dict, evenements: list[dict]) -> int:
    """Ajoute les publications d'une page « mois » (réel connu) aux séries ; -> nombre de points ajoutés ou modifiés."""
    series = d.setdefault("series", {})
    n = 0
    for e in evenements or []:
        if not e.get("reel") or not e.get("dateline") or not e.get("nom"):
            continue
        jour = datetime.fromtimestamp(int(e["dateline"]), tz=timezone.utc).date().isoformat()
        point = [e.get("reel"), e.get("prevision"), e.get("id")]
        s = series.setdefault(cle(e.get("devise"), e.get("nom")), {})
        if s.get(jour) != point:
            s[jour] = point
            n += 1
    return n


def a_tenter(d: dict, aujourd: date, maximum: int = MAX_PAR_JOUR) -> list[str]:
    """Mois à lire aujourd'hui : non lus, jamais retentés le même jour après un échec ; au plus `maximum`."""
    mois = d.get("mois") or {}
    deja = sum(1 for x in mois.values() if str(x.get("tente_le") or "")[:10] == aujourd.isoformat())
    maximum = max(0, maximum - deja)   # au plus 2 pages par jour, tous passages confondus
    sortie = []
    if not maximum:
        return sortie
    for m in etat(d, aujourd)["restants"]:
        x = mois.get(m) or {}
        if x.get("statut") == "echec" and str(x.get("tente_le") or "")[:10] == aujourd.isoformat():
            continue
        sortie.append(m)
        if len(sortie) >= maximum:
            break
    return sortie


def reprendre(cfg_tm: dict, client, dossier_cache: str | Path, maintenant: datetime | None = None,
              maximum: int = MAX_PAR_JOUR) -> dict:
    """Lit au plus `maximum` pages « mois » manquantes, dans le plafond quotidien commun. Ne lève jamais.
    -> {lus: [...], echecs: {...}, etat: {...}}"""
    from agents import collecte_forexfactory_mois as ffm
    maintenant = maintenant or datetime.now(timezone.utc)
    dossier_cache = Path(dossier_cache)
    d = lire(dossier_cache)
    d.setdefault("debut", maintenant.date().isoformat())
    bilan = {"lus": [], "echecs": {}}
    try:
        cfg_ff = cfg_tm["forexfactory"]
        plafond = int(cfg_ff.get("plafond_requetes_par_jour", 6))
        chemin_budget = dossier_cache / "forexfactory_requetes.json"
        jour = maintenant.date().isoformat()
        for mois in a_tenter(d, maintenant.date(), maximum):
            budget = ffm._lire_budget(chemin_budget, jour)
            if len(budget["horodatages"]) >= plafond:
                bilan["echecs"][mois] = f"plafond de {plafond} requêtes/jour atteint : reprise au run suivant"
                break
            res = ffm._requete(cfg_tm, client, mois, budget, chemin_budget, jour, maintenant)
            x = d.setdefault("mois", {}).setdefault(mois, {})
            x["tente_le"] = maintenant.isoformat(timespec="seconds")
            if res["statut"] != "frais":
                x.update(statut="echec", note=res["note"])
                bilan["echecs"][mois] = res["note"]
                log.warning("Historique ForexFactory : %s non lu (%s) — pas d'insistance", mois, res["note"])
                break
            n = integrer(d, res["evenements"])
            x.update(statut="lu", lu_le=maintenant.isoformat(timespec="seconds"), n=len(res["evenements"]), points=n, note=None)
            bilan["lus"].append(mois)
            log.info("Historique ForexFactory : %s lu (%d publications, %d points)", mois, len(res["evenements"]), n)
    except Exception as exc:  # noqa: BLE001 — la reprise ne casse jamais le run
        log.warning("Historique ForexFactory : reprise interrompue (%s)", exc)
        bilan["echecs"]["exception"] = str(exc)[:200]
    ecrire(dossier_cache, d)
    bilan["etat"] = etat(d, maintenant.date())
    return bilan


def comme_archive(d: dict) -> dict:
    """Points repris, au format de publications_archive.json (pour l'écart habituel au consensus des surprises)."""
    pubs = {}
    for k, s in (d.get("series") or {}).items():
        devise, nom = k.split("|", 1)
        for jour, (reel, prev, _id) in s.items():
            pubs[f"{jour}|{devise}|{nom}"] = {"date": jour, "devise": devise, "evenement_en": nom, "reel": reel, "consensus": prev,
                                               "source": "ForexFactory, page « mois » (reprise de l'historique)"}
    return {"publications": pubs}


def fusionner_archives(archive: dict | None, d: dict | None) -> dict:
    """Archive du site + historique repris ; l'archive du site l'emporte pour une même publication (même jour, devise, nom)."""
    pubs = dict(comme_archive(d or {})["publications"])
    vus = {(p.get("date"), p.get("devise"), str(p.get("evenement_en") or "").lower()) for p in ((archive or {}).get("publications") or {}).values()}
    pubs = {k: p for k, p in pubs.items() if (p["date"], p["devise"], p["evenement_en"]) not in vus}
    return {"publications": {**pubs, **((archive or {}).get("publications") or {})}}


def historique(devise: str, nom_en: str, jour: str, archive: dict | None, d: dict | None, n: int = N_POINTS) -> list[list]:
    """Les n dernières valeurs publiées AVANT `jour` (date de la publication) : [[date, réel, prévision], …] du plus
    ancien au plus récent ; archive du site puis historique repris (même jour : l'archive l'emporte)."""
    k = cle(devise, nom_en)
    points = {}
    for date_, (reel, prev, _id) in ((d or {}).get("series") or {}).get(k, {}).items():
        if date_ < jour and reel:
            points[date_] = [date_, reel, prev]
    for p in ((archive or {}).get("publications") or {}).values():
        if p.get("devise") == devise and cle(devise, p.get("evenement_en")) == k and str(p.get("date")) < jour and p.get("reel"):
            points[str(p["date"])] = [str(p["date"]), p.get("reel"), p.get("consensus")]
    return [points[x] for x in sorted(points)][-n:]
