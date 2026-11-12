"""Actualités du jour et probabilité citée de la prochaine décision de la Fed (lot V9, A6 et A9).

1. Actualités : 5 à 8 titres des flux RSS déjà collectés (agents/collecte_news.py : CNBC, InvestingLive, flux officiels),
   classés par thème en Python (Fed et taux, énergie et géopolitique, Chine et Asie, actions et IA), avec la source,
   l'heure et le lien. Uniquement des flux RSS : aucune page extraite.
2. Probabilité de la Fed : pas de données de futures gratuites et licites. Un chiffre est retenu seulement s'il figure
   mot pour mot dans le titre ou le résumé d'une actualité collectée, à côté d'un mot de probabilité et d'une mention de
   la Fed ou d'une décision de taux ; sinon « n/d ». Historique : data/cache/proba_fed.json (« 79 % contre 71 % il y a
   une semaine »).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

RACINE = Path(__file__).resolve().parents[1]
THEMES = [
    ("fed", "Fed et taux", r"\b(fed|fomc|powell|warsh|treasur(y|ies)|yields?|rate (cut|hike|decision)s?|inflation|cpi|ppi|payrolls?|jobs report|"
                           r"ecb|boe|boj|central bank|bank of (england|japan|canada)|rba|rbnz|snb)\b"),
    ("energie", "Énergie et géopolitique", r"\b(oil|crude|brent|wti|opec|iran|israel|russia|ukraine|natural gas|hormuz|sanctions?|war|tariffs?|geopolit\w*)\b"),
    ("asie", "Chine et Asie", r"\b(china|chinese|beijing|pboc|yuan|japan(ese)?|nikkei|asia\w*|taiwan|korea\w*|hong kong|india)\b"),
    ("actions", "Actions et IA", r"\b(stocks?|s&p|nasdaq|dow|equit(y|ies)|nvidia|ai|artificial intelligence|earnings|chips?|semiconductors?|tech)\b"),
]
SOURCES = {"cnbc_world": "CNBC", "investinglive": "InvestingLive", "fed_communiques": "Réserve fédérale", "bce_communiques": "BCE",
           "boe_actualites": "Banque d'Angleterre", "boc_communiques": "Banque du Canada"}
RE_PROBA = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)\s?(?:%|per ?cent)\s*(?:chance|probability|odds|likelihood|implied|priced|pricing)"
                      r"|(?:chance|probability|odds|likelihood|pricing|priced)[^.%]{0,40}?(\d{1,3}(?:\.\d{1,2})?)\s?(?:%|per ?cent)", re.I)
RE_FED = re.compile(r"\b(fed|fomc|federal reserve|fed funds|rate (cut|hike))\b", re.I)


def _lire(chemin: Path) -> dict | list:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def articles(cache_news: dict | None) -> list[dict]:
    d = (cache_news or {}).get("donnees") or cache_news or {}
    return [a for a in d.get("articles") or [] if a.get("titre")]


def theme(article: dict) -> str | None:
    t = f"{article.get('titre', '')} {article.get('resume') or ''}"
    for cle, _, motif in THEMES:
        if re.search(motif, t, re.I):
            return cle
    return None


def du_jour(arts: list[dict], maximum: int = 8, par_theme: int = 2) -> list[dict]:
    """5 à 8 titres, au plus 2 par thème, les plus récents d'abord, classés dans l'ordre des thèmes."""
    tries = sorted(arts, key=lambda a: a.get("date") or "", reverse=True)
    choisis: dict[str, list] = {c: [] for c, _, _ in THEMES}
    vus = set()
    for a in tries:
        c = theme(a)
        cle = re.sub(r"\W+", " ", a["titre"].lower())[:60]
        if c and len(choisis[c]) < par_theme and cle not in vus:
            vus.add(cle)
            choisis[c].append(a)
    sortie = []
    for c, lib, _ in THEMES:
        for a in choisis[c]:
            sortie.append({"theme": c, "theme_libelle": lib, "titre": a["titre"], "lien": a.get("lien"), "date": a.get("date"),
                           "source": SOURCES.get(a.get("source"), a.get("source"))})
    return sortie[:maximum]


def extraire_proba(article: dict) -> dict | None:
    """Probabilité citée pour la Fed dans une actualité ; le nombre doit figurer tel quel dans le texte source."""
    contexte_fed = bool(RE_FED.search(article.get("titre") or ""))   # un résumé dont le titre parle de la Fed
    for champ in ("titre", "resume"):
        texte = article.get(champ) or ""
        for phrase in re.split(r"(?<=[.!?])\s+", texte):
            if not RE_FED.search(phrase) and not (champ == "resume" and contexte_fed):
                continue
            m = RE_PROBA.search(phrase)
            if not m:
                continue
            brut = m.group(1) or m.group(2)
            v = float(brut)
            if not 0 < v <= 100 or brut not in texte:
                continue
            bas = phrase.lower()
            sens = ("baisse" if re.search(r"\bcut|lower|ease|easing\b", bas) else "hausse" if re.search(r"\bhike|raise|increase|tighten", bas)
                    else "maintien" if re.search(r"\bhold|pause|unchanged|steady\b", bas) else None)
            if sens is None:
                continue
            return {"valeur": v, "sens": sens, "citation": phrase.strip()[:280], "champ": champ, "titre": article.get("titre"),
                    "lien": article.get("lien"), "date": (article.get("date") or "")[:10], "heure_utc": (article.get("date") or "")[11:16],
                    "source": SOURCES.get(article.get("source"), article.get("source"))}
    return None


def mettre_a_jour_proba(arts: list[dict], chemin: Path | None = None, aujourd: date | None = None) -> dict:
    """Ajoute à l'historique les probabilités citées des actualités ; renvoie {dernier, reference, historique}."""
    chemin = Path(chemin or RACINE / "data" / "cache" / "proba_fed.json")
    aujourd = aujourd or datetime.now(timezone.utc).date()
    hist = _lire(chemin)
    hist = hist if isinstance(hist, list) else []
    connus = {(h.get("lien"), h.get("valeur"), h.get("sens")) for h in hist}
    for a in arts:
        p = extraire_proba(a)
        if p and (p["lien"], p["valeur"], p["sens"]) not in connus:
            hist.append(p)
            connus.add((p["lien"], p["valeur"], p["sens"]))
    hist = sorted((h for h in hist if h.get("date", "") >= (aujourd - timedelta(days=60)).isoformat()), key=lambda h: (h["date"], h.get("heure_utc") or ""))
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(hist, ensure_ascii=False, indent=0), encoding="utf-8")
    except OSError as exc:
        log.warning("proba_fed.json non écrit : %s", exc)
    return lecture_proba(hist, aujourd)


def lecture_proba(hist: list[dict], aujourd: date) -> dict:
    recents = [h for h in hist if h.get("date", "") >= (aujourd - timedelta(days=3)).isoformat()]
    if not recents:
        dernier_vu = hist[-1]["date"] if hist else None
        return {"valeur": None, "raison": ("aucune probabilité chiffrée de la Fed dans les actualités collectées depuis 3 jours"
                                           + (f" (dernière le {dernier_vu[8:10]}/{dernier_vu[5:7]})" if dernier_vu else ""))}
    d = recents[-1]
    cible = (date.fromisoformat(d["date"]) - timedelta(days=7)).isoformat()
    refs = [h for h in hist if h["sens"] == d["sens"] and (date.fromisoformat(d["date"]) - timedelta(days=10)).isoformat() <= h["date"]
            <= (date.fromisoformat(d["date"]) - timedelta(days=5)).isoformat()]
    ref = min(refs, key=lambda h: abs((date.fromisoformat(h["date"]) - date.fromisoformat(cible)).days)) if refs else None
    return {**d, "reference": ref, "raison_reference": None if ref else "aucune probabilité comparable citée 5 à 10 jours plus tôt"}


def calculer(racine: Path | None = None, aujourd: date | None = None) -> dict:
    racine = Path(racine or RACINE)
    arts = articles(_lire(racine / "data" / "cache" / "collecte_news.json"))
    return {"actualites": du_jour(arts), "proba_fed": mettre_a_jour_proba(arts, racine / "data" / "cache" / "proba_fed.json", aujourd),
            "n_articles": len(arts)}
