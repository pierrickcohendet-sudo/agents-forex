"""Lot V10 (B4) : archive du contexte du site pour la « Lecture du site » du Journal.

À chaque run (complet et horaire), un instantané léger est ajouté à `docs/data/contexte/AAAA-MM-JJ.json` s'il diffère du
précédent du jour : 9 devises x 8 moteurs (valeur de la matrice d'impact, raison chiffrée et datée, source), état de chaque
devise, 36 paires (contribution de chaque moteur +1 / 0 / −1 vers la hausse de la paire, cours, zones de la veille et de la
semaine précédente, RSI, structure H4, tendance), thème, scénarios, publications du jour (réel et consensus). Les raisons
sont stockées une fois par devise (pas par paire) : fichier léger, conservé 2 ans. Tout est calculé ici ; le site oriente
seulement selon le sens du trade (statistique privée de l'utilisateur, calculée sur l'appareil).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import noms_moteurs as nm

log = logging.getLogger(__name__)

DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
CONSERVATION_JOURS = 731
VERSION = 1


def paires() -> list[str]:
    return [f"{a}/{b}" for i, a in enumerate(DEVISES) for b in DEVISES[i + 1:]]


def _lire(chemin: Path) -> dict:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _signe(v) -> int:
    return 1 if (v or 0) > 0 else -1 if (v or 0) < 0 else 0


def raison_case(case: dict, date_matrice: str | None = None) -> dict:
    """Case de la matrice (devise x moteur) -> {v, raison, date, source} ; « n/d » avec la raison si la case manque."""
    regles = case.get("regles") or []
    if case.get("etat") == "nd":
        return {"v": None, "raison": f"n/d : {case.get('raison') or 'donnée manquante'}", "date": None, "source": None}
    if regles:
        txt = " ; ".join(f"{r.get('regle')} ({r.get('chiffre')})" for r in regles)
        dates = sorted(r.get("date") for r in regles if r.get("date"))
        sources = list(dict.fromkeys(r.get("source") for r in regles if r.get("source")))
        return {"v": case.get("valeur", 0), "raison": txt, "date": dates[-1] if dates else None, "source": " ; ".join(sources) or None}
    raison = case.get("raison") or ("pas de règle pour ce moteur" if case.get("etat") == "sans_regle" else "sous les seuils")
    return {"v": case.get("valeur", 0), "raison": nm.remplacer(raison)[0], "date": date_matrice,
            "source": "matrice d'impact (règles Python de config.yaml)"}


def _devises(dossiers: dict, profil: dict) -> dict:
    date_matrice = (dossiers.get("genere_le") or "")[:10] or None
    lignes = {l["devise"]: l for l in ((dossiers.get("matrice_impact") or {}).get("lignes") or [])}
    etats = {d["devise"]: (d.get("etat") or {}) for d in profil.get("devises") or []}
    sortie = {}
    for dev in DEVISES:
        cases = {c["engrenage"]: c for c in (lignes.get(dev) or {}).get("cases") or []}
        sortie[dev] = {
            "moteurs": [raison_case(cases[n], date_matrice) if n in cases else {"v": None, "raison": "n/d : matrice d'impact absente", "date": None, "source": None}
                        for n in range(1, 9)],
            "etat": etats.get(dev, {}).get("valeur") or "n/d",
            "etat_raison": etats.get(dev, {}).get("raison") or ("profil des devises absent" if not etats else None)}
    return sortie


def _zones(niveaux: dict) -> dict:
    v, s = niveaux.get("veille") or {}, niveaux.get("semaine_precedente") or {}
    h4 = niveaux.get("structure_h4") or {}
    dernier = (h4.get("evenements") or [None])[-1]
    return {"veille": [v.get("bas"), v.get("haut"), v.get("jour")] if v else None,
            "semaine": [s.get("bas"), s.get("haut"), s.get("semaine")] if s else None,
            "h4": h4.get("tendance_structure") or None,
            "h4_dernier": ({"type": dernier.get("type"), "sens": dernier.get("sens"), "date": dernier.get("date"), "niveau": dernier.get("niveau")}
                           if dernier else None),
            "tendance_jour": (niveaux.get("tendance_jour") or {}).get("lecture")}


def _paires(docs_data: Path, paires_json: dict, scenarios: list[dict]) -> dict:
    fiches = paires_json.get("fiches") or {}
    sortie = {}
    for p in paires():
        f = fiches.get(p) or {}
        base, cot = p.split("/")
        contrib = {c["engrenage"]: c for c in ((f.get("macro") or {}).get("decomposition") or {}).get("contributions") or []}
        detail = _lire(docs_data / "paires" / f"{p.replace('/', '-')}.json")
        t = f.get("technique") or {}
        sortie[p] = {
            "c": [(_signe(contrib[n]["contribution"]) if not contrib[n].get("incomplete") else None) if n in contrib else None
                  for n in range(1, 9)],
            "rsi_1j": (f.get("rsi") or {}).get("1j"), "rsi_14j": t.get("rsi14"),
            "zones": _zones(detail.get("niveaux") or {}),
            "scen": [[s["id"], _signe((s.get("consequences") or {}).get(base, 0) - (s.get("consequences") or {}).get(cot, 0))]
                     for s in scenarios if (s.get("consequences") or {}).get(base, 0) != (s.get("consequences") or {}).get(cot, 0)]}
        if not f:
            sortie[p]["raison"] = "fiche de paire absente de paires.json"
    return sortie


def _marche(paires_json: dict) -> dict:
    """Partie qui change à chaque heure : cours (Twelve Data) et RSI 4 h, par paire."""
    fiches = paires_json.get("fiches") or {}
    sortie, heures = {}, []
    for p in paires():
        f = fiches.get(p) or {}
        cj, t = f.get("cours_jour") or {}, f.get("technique") or {}
        cours = cj.get("cours") if cj.get("cours") is not None else t.get("cours")
        sortie[p] = [cours, (f.get("rsi") or {}).get("4h")]
        if cj.get("heure") or t.get("date"):
            heures.append(cj.get("heure") or t.get("date"))
    return {"paires": sortie, "cours_du": max(heures) if heures else None,
            "source": "Twelve Data (/quote) ; RSI 4 h sur bougies Twelve Data"}


def _publications(agenda: dict, jour: str) -> dict:
    sortie = {d: [] for d in DEVISES}
    for j in agenda.get("jours") or []:
        for e in j.get("evenements") or []:
            if e.get("date_paris") != jour or e.get("devise") not in sortie or e.get("impact") not in ("moyen", "fort"):
                continue
            sortie[e["devise"]].append({"h": e.get("iso_utc"), "heure_paris": e.get("heure_paris"), "ev": e.get("evenement"),
                                        "impact": e.get("impact"), "publie": e.get("publie"), "consensus": e.get("consensus"),
                                        "precedent": e.get("precedent")})
    return sortie


def calculer(docs_data: Path, maintenant: datetime) -> dict:
    """Instantané du contexte publié à l'instant `maintenant` (UTC)."""
    docs_data = Path(docs_data)
    dossiers, profil = _lire(docs_data / "dossiers.json"), _lire(docs_data / "profil_devises.json")
    rj, pj, agenda = _lire(docs_data / "rapport_jour.json"), _lire(docs_data / "paires.json"), _lire(docs_data / "agenda.json")
    coh = (((dossiers.get("vue_ensemble") or {}).get("theme") or {}).get("coherence")) or {}
    th = rj.get("theme") or {}
    scen = (rj.get("scenarios") or {}).get("liste") or []
    jour = maintenant.astimezone(timezone.utc).date().isoformat()
    return {
        "heure_utc": maintenant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M+00:00"),
        "rapport_du": rj.get("date"),
        "theme": {"titre": th.get("titre") or "n/d", "direction": (th.get("direction") or {}).get("libelle") or "n/d",
                  "alignes": coh.get("alignes"), "evaluables": coh.get("evaluables"),
                  "moteurs_alignes": [nm.nom(n, True) for n in coh.get("engrenages_alignes") or []],
                  "raison": None if th else "rapport du jour absent"},
        "devises": _devises(dossiers, profil),
        "paires": _paires(docs_data, pj, scen),
        "marche": _marche(pj),
        "scenarios": [{"id": s["id"], "titre": s.get("titre"), "remplies": s.get("remplies"), "total": s.get("total"),
                       "statut": s.get("statut"), "invalide": bool(s.get("invalide"))} for s in scen],
        "publications": _publications(agenda, jour),
        "sources": {"moteurs": "matrice d'impact (dossiers.json, règles Python de config.yaml)",
                    "paires": "paires.json et paires/*.json (Twelve Data, séries uniques 5 ans)",
                    "publications": "agenda.json (ForexFactory)", "etats": "profil_devises.json"}}


SECTIONS = ("theme", "devises", "paires", "marche", "scenarios", "publications", "sources")


def _empreinte(x) -> str:
    return hashlib.sha1(json.dumps(x, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def archiver(docs_data: Path, maintenant: datetime | None = None, dossier_sortie: Path | None = None) -> dict:
    """Ajoute l'instantané au fichier du jour s'il diffère du dernier ; met à jour index.json ; purge au-delà de 2 ans.
    Fichier léger : chaque section (thème, devises, paires, marché…) est stockée une fois dans « blocs » et l'instantané n'en
    garde que l'empreinte. Ne lève jamais : renvoie {ajoute, fichier, n, raison}."""
    maintenant = maintenant or datetime.now(timezone.utc)
    dossier = Path(dossier_sortie) if dossier_sortie else Path(docs_data) / "contexte"
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        inst = calculer(docs_data, maintenant)
        jour = maintenant.astimezone(timezone.utc).date().isoformat()
        chemin = dossier / f"{jour}.json"
        fichier = _lire(chemin) or {"version": VERSION, "date": jour,
                                     "moteurs": {str(k): {"nom": v[0], "explication": v[1]} for k, v in nm.MOTEURS.items()},
                                     "blocs": {}, "instantanes": []}
        refs = {}
        for sec in SECTIONS:
            h = _empreinte(inst[sec])
            fichier["blocs"].setdefault(h, inst[sec])
            refs[sec] = h
        dernier = fichier["instantanes"][-1] if fichier["instantanes"] else None
        ajoute = dernier is None or dernier.get("refs") != refs
        if ajoute:
            fichier["instantanes"].append({"heure_utc": inst["heure_utc"], "rapport_du": inst["rapport_du"], "refs": refs})
            utilises = {h for i in fichier["instantanes"] for h in i["refs"].values()}
            fichier["blocs"] = {h: b for h, b in fichier["blocs"].items() if h in utilises}
            chemin.write_text(json.dumps(fichier, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        limite = (maintenant.date() - timedelta(days=CONSERVATION_JOURS)).isoformat()
        for f in dossier.glob("????-??-??.json"):
            if f.stem < limite:
                f.unlink()
        index = {"version": VERSION, "jours": {}, "note": "Instantanés du contexte publié (heures UTC), conservés 2 ans."}
        for f in sorted(dossier.glob("????-??-??.json")):
            index["jours"][f.stem] = [i["heure_utc"] for i in _lire(f).get("instantanes") or []]
        index["premier"] = next(iter(index["jours"]), None)
        (dossier / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return {"ajoute": ajoute, "fichier": chemin.name, "n": len(fichier["instantanes"])}
    except Exception as exc:  # noqa: BLE001
        log.warning("archive du contexte non écrite : %s", exc)
        return {"ajoute": False, "raison": str(exc)}


def reconstituer(fichier: dict, rang: int) -> dict:
    """Instantané complet (sections recopiées depuis « blocs »)."""
    i = fichier["instantanes"][rang]
    return {"heure_utc": i["heure_utc"], "rapport_du": i.get("rapport_du"), **{k: fichier["blocs"][h] for k, h in i["refs"].items()}}


def instantane_avant(index_jours: dict[str, list[str]], moment_utc: str) -> tuple[str, int] | None:
    """Fonction pure : (jour, rang) de l'instantané le plus proche AVANT `moment_utc` (ISO UTC), ou None.
    Même règle que docs/site/journal_contexte.js."""
    meilleur = None
    for jour in sorted(index_jours):
        if jour > moment_utc[:10]:
            break
        for i, h in enumerate(index_jours[jour]):
            if h <= moment_utc and (meilleur is None or h >= meilleur[2]):
                meilleur = (jour, i, h)
    return (meilleur[0], meilleur[1]) if meilleur else None
