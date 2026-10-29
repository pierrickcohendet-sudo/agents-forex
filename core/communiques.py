"""Communiqués officiels des décisions de banques centrales (Rapport du jour, étape 6). Sources licites : flux RSS
officiels déjà déclarés (config.yaml > rss) et page officielle du communiqué. Lus seulement le jour d'une décision
prévue à l'agenda et le lendemain ; une requête par communiqué nouveau. Archive : data/communiques/.
Le ton (plus restrictif / inchangé / plus accommodant) est rendu par le modèle en comparant avec le communiqué
précédent, phrases citées à l'appui (agents/agent_rapport.py) ; sans modèle : n/d avec la raison.
La réaction mesurée après coup (devise et 2 ans à J+1) est calculée en Python.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# devise -> (flux RSS de config.yaml, motif du titre du communiqué de décision)
FLUX = {"USD": ("fed_communiques", r"issues FOMC statement"),
        "EUR": ("bce_communiques", r"^Monetary policy decisions$"),
        "GBP": ("boe_actualites", r"Bank Rate (maintained|increased|reduced|cut|raised|held)"),
        "CAD": ("boc_communiques", r"Bank of Canada (raises|lowers|maintains|holds|cuts|increases) the policy rate")}
SANS_FLUX = "pas de flux officiel configuré pour cette banque (BoJ, BNS, RBA, RBNZ, PBoC) : communiqué non archivé"
UA = {"User-Agent": "agents-forex/1.0 (archive de communiqués officiels ; une requête par communiqué)"}
TONS = ("plus restrictif", "inchangé", "plus accommodant")


def extraire_texte(html: str, limite: int = 12000) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        t.decompose()
    zone = soup.find("main") or soup.find("article") or soup.body or soup
    paras = [p.get_text(" ", strip=True) for p in zone.find_all(["p", "li"])]
    texte = "\n".join(p for p in paras if len(p) > 40)
    return re.sub(r"[ \t]+", " ", texte)[:limite]


def decisions_proches(agenda_donnees: dict | None, aujourd: date) -> set[str]:
    """Devises dont une décision est prévue aujourd'hui ou était prévue hier (agenda)."""
    jours = {aujourd.isoformat(), (aujourd - timedelta(days=1)).isoformat()}
    return {e["devise"] for j in (agenda_donnees or {}).get("jours") or [] for e in j.get("evenements") or []
            if e.get("type") == "Réunion BC" and e.get("date_paris") in jours}


def _date_entree(entree) -> str | None:
    import time
    brut = getattr(entree, "published_parsed", None) or getattr(entree, "updated_parsed", None)
    return datetime.fromtimestamp(time.mktime(brut), tz=timezone.utc).date().isoformat() if brut else None


def archiver(racine: str | Path, config: dict, agenda_donnees: dict | None, aujourd: date | None = None, session=None) -> dict:
    """Archive les communiqués de décision nouveaux. -> index {par_devise: {devise: entrée la plus récente}}."""
    import feedparser
    import requests
    session = session or requests
    aujourd = aujourd or datetime.now(timezone.utc).date()
    dossier = Path(racine) / "data" / "communiques"
    dossier.mkdir(parents=True, exist_ok=True)
    chemin_index = dossier / "index.json"
    try:
        index = json.loads(chemin_index.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {"par_devise": {}, "historique": {}}
    for devise in sorted(decisions_proches(agenda_donnees, aujourd)):
        if devise not in FLUX:
            index["par_devise"][devise] = {"raison": SANS_FLUX, "date": aujourd.isoformat()}
            continue
        nom_flux, motif = FLUX[devise]
        url_flux = (config.get("rss") or {}).get(nom_flux)
        if not url_flux:
            continue
        try:
            flux = feedparser.parse(session.get(url_flux, headers=UA, timeout=30).content)
        except Exception as exc:  # noqa: BLE001
            log.warning("Communiqués %s : flux illisible (%s)", devise, exc)
            continue
        for e in flux.entries[:15]:
            titre = str(getattr(e, "title", "")).strip()
            if not re.search(motif, titre, re.I):
                continue
            url = getattr(e, "link", "")
            deja = [h for h in index["historique"].get(devise, []) if h["url"] == url]
            if deja:
                break
            try:
                rep = session.get(url, headers=UA, timeout=30)
                rep.raise_for_status()
                texte = extraire_texte(rep.text)
            except Exception as exc:  # noqa: BLE001
                log.warning("Communiqué %s non lu (%s)", devise, exc)
                break
            jour = _date_entree(e) or aujourd.isoformat()
            entree = {"devise": devise, "date": jour, "titre": titre, "url": url, "source": f"{nom_flux} (site officiel)",
                      "fichier": f"{devise}_{jour}.json"}
            (dossier / entree["fichier"]).write_text(json.dumps({**entree, "texte": texte}, ensure_ascii=False, indent=1), encoding="utf-8")
            index["historique"].setdefault(devise, []).append(entree)
            index["historique"][devise] = index["historique"][devise][-12:]
            break
        hist = index["historique"].get(devise) or []
        if hist:
            index["par_devise"][devise] = {**hist[-1], "precedent": hist[-2] if len(hist) > 1 else None}
    chemin_index.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return index


def textes_a_comparer(racine: str | Path, index: dict, devise: str) -> tuple[str | None, str | None]:
    """(texte actuel, texte précédent) d'une devise, ou None."""
    e = (index.get("par_devise") or {}).get(devise) or {}
    lire = lambda f: (json.loads((Path(racine) / "data" / "communiques" / f).read_text(encoding="utf-8")).get("texte")
                      if f and (Path(racine) / "data" / "communiques" / f).exists() else None)
    return lire(e.get("fichier")), lire((e.get("precedent") or {}).get("fichier"))


def reaction(devise: str, jour: str, h5, technique, historiques: dict | None) -> dict | None:
    """Variation de la force de la devise et du 2 ans de la devise entre la veille et la séance qui suit la décision."""
    from core import impact as impact_mod
    from core.rapport_jour import SERIE_2A, _points
    force = impact_mod.serie_devise(h5, devise, technique) if h5 is not None else None
    sortie = {}
    if force is not None:
        veille = (date.fromisoformat(jour) - timedelta(days=1)).isoformat()
        avant, apres = force.a(veille), force.apres(jour)   # clôture d'avant la décision -> séance suivante (J+1)
        if avant and apres:
            sortie["devise_pct"] = round((apres[1] / avant - 1) * 100, 2)
            sortie["seance"] = apres[0]
    pts = _points(historiques, SERIE_2A.get(devise, ""))
    av = [v for d, v in pts if d < jour]
    ap = [(d, v) for d, v in pts if d > jour]
    if av and ap:
        sortie["deux_ans_pb"] = round((ap[0][1] - av[-1]) * 100, 1)
    return sortie or None
