"""Communiqués officiels des banques centrales (lot V9, A7) : Fed, BCE, BoE, BoJ, BNS, BoC, RBA, RBNZ.

Pris sur les flux RSS officiels de chaque banque, puis sur la page (ou le PDF) du communiqué : une requête par flux et
par jour, une par communiqué nouveau, archivés dans data/communiques_v9/. Un 403 n'est jamais contourné : la banque
reste « n/d » avec la raison. Extraits en Python, sans modèle :
- la répartition des votes (quand la banque la publie ; sinon la raison) ;
- les changements de vocabulaire par rapport au communiqué précédent archivé (phrases ajoutées et retirées, mots
  restrictifs et accommodants comptés) ;
- les projections citées (phrases avec un pourcentage, un horizon et « attendu / projeté / prévu »).
Le vote officiel corrige l'archive des publications (ex. BoE du 05/11 : « 9-0-0 » ForexFactory -> 8 contre 1).
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

RACINE = Path(__file__).resolve().parents[1]
BANQUES = {
    "USD": {"banque": "Fed", "flux": "https://www.federalreserve.gov/feeds/press_monetary.xml", "titre": r"FOMC statement", "votes": "fed"},
    "EUR": {"banque": "BCE", "flux": "https://www.ecb.europa.eu/rss/press.html", "titre": r"^Monetary policy decisions?$", "votes": None,
            "raison_votes": "la BCE ne publie pas la répartition des votes"},
    "GBP": {"banque": "BoE", "flux": "https://www.bankofengland.co.uk/rss/news", "titre": r"Monetary Policy Summary", "votes": "boe"},
    "JPY": {"banque": "BoJ", "flux": "https://www.boj.or.jp/en/rss/whatsnew.xml", "titre": r"^Statement on Monetary Policy", "votes": "boj"},
    "CHF": {"banque": "BNS", "flux": "https://www.snb.ch/public/en/rss/pressrel", "titre": r"Monetary policy assessment", "votes": None,
            "raison_votes": "la BNS ne publie pas de votes (décision de la Direction générale)"},
    "CAD": {"banque": "BoC", "flux": "https://www.bankofcanada.ca/content_type/press-releases/feed/",
            "titre": r"^Bank of Canada (raises|lowers|maintains|holds|cuts|increases|reduces|keeps)", "votes": None,
            "raison_votes": "la Banque du Canada ne publie pas de votes (décision par consensus)"},
    "AUD": {"banque": "RBA", "flux": "https://www.rba.gov.au/rss/rss-cb-media-releases.xml", "titre": r"Monetary Policy Decision", "votes": "generique"},
    "NZD": {"banque": "RBNZ", "flux": "https://www.rbnz.govt.nz/feeds/news", "titre": r"(Official Cash Rate|\bOCR\b|Monetary Policy (Statement|Review))",
            "votes": "generique"},
}
# Lot V9.4 : procès-verbaux et délibérations (options débattues, indication sur la suite, projections citées)
PV = {"USD": {"flux": "https://www.federalreserve.gov/feeds/press_monetary.xml", "titre": r"^Minutes of the Federal Open Market Committee"},
      "CAD": {"page": "https://www.bankofcanada.ca/publications/summary-governing-council-deliberations/",
              "lien": r"/\d{4}/\d{2}/summary-of-governing-council-deliberations"},
      "GBP": {"meme_document": "le procès-verbal de la BoE est publié avec le résumé de la décision (même document)"},
      "EUR": {"raison": "comptes rendus de la BCE : page de liste chargée en JavaScript, sans flux officiel : non lus"}}
RESTRICTIF = r"\b(restrictive|tighten\w*|upside risks?|elevated|persistent|higher for longer|further increases?|hawkish)\b"
ACCOMMODANT = r"\b(accommodative|eas(e|ing)|downside risks?|slack|weak\w*|cuts?|lower(ing)?|dovish|support)\b"


def _lire(chemin: Path) -> dict:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def phrases(texte: str) -> list[str]:
    """Découpe en phrases sans couper les nombres décimaux (« 0.25 percentage points »)."""
    t = re.sub(r"\s+", " ", texte or "").strip()
    t = re.sub(r"Related links(?: Related links)?.*?(?=At its meeting|$)", "", t, count=1)   # navigation de la page BoE
    # pas de coupure après une initiale (« Lisa D. Cook ») ni dans un nombre décimal
    morceaux = re.split(r"(?<=[.!?])(?<!\s[A-Z]\.)\s+(?=[A-Z“\"(])", t)
    return [p.strip() for p in morceaux if 25 < len(p.strip()) <= 400]


def _noms(liste: str) -> list[str]:
    return [n.strip() for n in re.split(r",\s*(?:and\s+)?|\s+and\s+", liste or "") if n.strip()]


def votes(texte: str, mode: str | None, raison: str | None = None) -> dict:
    """Répartition des votes d'après le texte officiel ; {texte, pour, contre, minorite, citation} ou {raison}."""
    if not mode:
        return {"texte": None, "raison": raison or "votes non publiés"}
    t = re.sub(r"\s+", " ", texte or "")
    if mode == "fed":
        # La page garde la phrase des votes contre ; la majorité se déduit des 12 votants de l'année (core/fomc_2026.py)
        from core.fomc_2026 import MEMBRES
        votants = sum(1 for m in MEMBRES.values() if m[2] in ("président", "votant"))
        pour = re.search(r"Voting for (?:the|this) (?:monetary policy )?action were:? (.+?)(?<!\s[A-Z])\.(?=\s+[A-Z]|$)", t)
        contre = re.search(r"Voting against (?:the|this) (?:monetary policy )?action (?:was|were):? (.+?)(?:, who (.+?))?(?<!\s[A-Z])\.(?=\s+[A-Z]|$)", t)
        nc = len(_noms(contre.group(1))) if contre else 0
        np_ = len(_noms(pour.group(1))) if pour else votants - nc
        if not pour and not contre:
            return {"texte": None, "raison": "phrases des votes absentes de la page du communiqué"}
        return {"texte": f"{np_} contre {nc}" if nc else f"unanimité ({np_} voix)", "pour": np_, "contre": nc,
                "minorite": contre.group(0)[:300] if contre else None,
                "citation": (contre or pour).group(0)[:300],
                "note": None if pour else f"majorité déduite des {votants} votants 2026 (federalreserve.gov)"}
    if mode == "boe":
        m = re.search(r"voted by a majority of (\d+)\s*[–-]\s*(\d+)", t)
        if m:
            cit = next((p for p in phrases(t) if m.group(0) in p), m.group(0))
            contre = next((p for p in phrases(t) if re.search(r"voted against the proposition|members? voted to", p)), None)
            return {"texte": f"{m.group(1)} contre {m.group(2)}", "pour": int(m.group(1)), "contre": int(m.group(2)),
                    "minorite": contre[:260] if contre else None, "citation": cit[:300]}
        if re.search(r"voted unanimously", t):
            return {"texte": "unanimité", "pour": None, "contre": 0, "minorite": None,
                    "citation": next((p for p in phrases(t) if "voted unanimously" in p), None)}
        return {"texte": None, "raison": "vote non trouvé dans le résumé officiel"}
    if mode == "boj":
        m = re.search(r"by an? (\d+)\s*[–-]\s*(\d+) majority vote", t)
        if m:
            return {"texte": f"{m.group(1)} contre {m.group(2)}", "pour": int(m.group(1)), "contre": int(m.group(2)),
                    "minorite": None, "citation": re.search(r"[^.]*" + re.escape(m.group(0)) + r"[^.]*\.", t).group(0)[:300]}
        if re.search(r"unanimous", t, re.I):
            return {"texte": "unanimité", "pour": None, "contre": 0, "minorite": None, "citation": None}
        return {"texte": None, "raison": "vote non trouvé dans le communiqué"}
    m = re.search(r"(?:vot\w+|decision)[^.]{0,80}?(\d+)\s*[–-]\s*(\d+)", t, re.I)
    if m:
        return {"texte": f"{m.group(1)} contre {m.group(2)}", "pour": int(m.group(1)), "contre": int(m.group(2)), "minorite": None,
                "citation": m.group(0)[:300]}
    if re.search(r"unanimous", t, re.I):
        return {"texte": "unanimité", "pour": None, "contre": 0, "minorite": None, "citation": None}
    return {"texte": None, "raison": "répartition des votes non indiquée dans le communiqué"}


def projections(texte: str, maximum: int = 3) -> list[str]:
    sortie = []
    for p in phrases(texte):
        if (re.search(r"\b(expected|projected|forecast\w*|projection|anticipated|likely to)\b", p, re.I)
                and re.search(r"\d+(?:\.\d+)?\s?(?:%|per ?cent|percentage points?)|around \d+%", p, re.I)
                and re.search(r"\b(20\d\d|next year|this year|quarter|Q[1-4]|middle of|mid-|by the end|over the coming)\b", p, re.I)):
            if len(p) <= 320 and not re.match(r"^\d+:", p):
                sortie.append(p)
        if len(sortie) >= maximum:
            break
    return sortie


def vocabulaire(actuel: str, precedent: str | None) -> dict:
    """Phrases ajoutées et retirées (comparaison tolérante : chiffres neutralisés), mots restrictifs et accommodants."""
    if not precedent:
        return {"raison": "communiqué précédent non archivé (comparaison à partir de la prochaine décision)"}
    norm = lambda p: re.sub(r"\d+(?:\.\d+)?", "#", p.lower())   # noqa: E731
    a, b = phrases(actuel), phrases(precedent)
    na, nb = [norm(x) for x in a], [norm(x) for x in b]

    def proche(x, liste):
        return max((difflib.SequenceMatcher(None, x, y).ratio() for y in liste), default=0) >= 0.8
    ajouts = [a[i] for i, x in enumerate(na) if not proche(x, nb)]
    retraits = [b[i] for i, x in enumerate(nb) if not proche(x, na)]
    compte = lambda t, m: len(re.findall(m, t or "", re.I))   # noqa: E731
    mots = {"restrictifs": [compte(precedent, RESTRICTIF), compte(actuel, RESTRICTIF)],
            "accommodants": [compte(precedent, ACCOMMODANT), compte(actuel, ACCOMMODANT)]}
    d = (mots["restrictifs"][1] - mots["restrictifs"][0]) - (mots["accommodants"][1] - mots["accommodants"][0])
    return {"ajouts": [x[:240] for x in ajouts[:3]], "retraits": [x[:240] for x in retraits[:3]], "n_ajouts": len(ajouts),
            "n_retraits": len(retraits), "mots": mots,
            "lecture": ("vocabulaire plus restrictif" if d > 0 else "vocabulaire plus accommodant" if d < 0 else "vocabulaire équilibré"),
            "methode": "mots restrictifs et accommodants comptés (anglais du communiqué), avant -> après ; phrases comparées chiffres neutralisés"}


def extraire_texte(contenu: bytes, url: str) -> str:
    if url.lower().endswith(".pdf") or contenu[:5] == b"%PDF-":
        import io
        from pypdf import PdfReader
        return re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(contenu)).pages[:6]))[:15000]
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(contenu, "lxml")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        t.decompose()
    zone = soup.find("main") or soup.find("article") or soup.body or soup
    paras = [p.get_text(" ", strip=True) for p in zone.find_all(["p", "li"])]
    return re.sub(r"[ \t]+", " ", "\n".join(p for p in paras if len(p) > 30))[:15000]


def _date_entree(e) -> str | None:
    import time
    brut = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
    if brut:
        return datetime.fromtimestamp(time.mktime(brut), tz=timezone.utc).date().isoformat()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", getattr(e, "title", "") or "")   # BNS : la date est dans le titre
    return m.group(1) if m else None


def decisions_du_jour(agenda: dict | None, aujourd: date) -> set[str]:
    """Devises dont la banque centrale décide aujourd'hui (Agenda) : leur flux est relu à chaque passage horaire."""
    return {e.get("devise") for j in (agenda or {}).get("jours") or [] for e in j.get("evenements") or []
            if e.get("type") == "Réunion BC" and e.get("date_paris") == aujourd.isoformat()}


def archiver(racine: Path | None = None, config: dict | None = None, session=None, aujourd: date | None = None,
             decisions: set[str] | None = None) -> dict:
    """Met à jour data/communiques_v9/ : chaque flux une fois par jour (à chaque passage le jour d'une décision de cette
    banque), une requête par communiqué nouveau. Ne lève jamais."""
    import feedparser
    import requests
    racine = Path(racine or RACINE)
    dossier = racine / "data" / "communiques_v9"
    dossier.mkdir(parents=True, exist_ok=True)
    index = _lire(dossier / "index.json") or {"banques": {}}
    aujourd = aujourd or datetime.now(timezone.utc).date()
    ua = {"User-Agent": ((config or {}).get("scraping") or {}).get("user_agent") or "agents-forex/1.0"}
    s = session or requests
    for dev, cfg in BANQUES.items():
        etat = index["banques"].setdefault(dev, {"communiques": []})
        if etat.get("flux_lu_le") == aujourd.isoformat() and not etat.get("erreur") and dev not in (decisions or set()):
            continue
        etat["flux_lu_le"] = aujourd.isoformat()
        try:
            rep = s.get(cfg["flux"], headers=ua, timeout=30)
            if rep.status_code == 403:
                etat["erreur"] = f"flux officiel refusé aux requêtes automatiques (403, {cfg['flux']}) : jamais contourné"
                continue
            rep.raise_for_status()
            entrees = [e for e in feedparser.parse(rep.content).entries if re.search(cfg["titre"], getattr(e, "title", ""), re.I)]
            etat["erreur"] = None if entrees else "aucun communiqué de décision dans le flux officiel (fenêtre du flux)"
            connus = {c["lien"] for c in etat["communiques"]}
            for e in sorted(entrees[:2], key=lambda x: _date_entree(x) or ""):
                lien = getattr(e, "link", None)
                if not lien or lien in connus:
                    continue
                r = s.get(lien, headers=ua, timeout=40)
                if r.status_code == 403:
                    etat["erreur"] = f"page du communiqué refusée (403) : jamais contournée"
                    continue
                r.raise_for_status()
                texte = extraire_texte(r.content, lien)
                jour = _date_entree(e) or aujourd.isoformat()
                fichier = f"{dev}_{jour}.json"
                (dossier / fichier).write_text(json.dumps({"devise": dev, "banque": cfg["banque"], "date": jour, "titre": e.title,
                                                          "lien": lien, "texte": texte, "archive_le": aujourd.isoformat()},
                                                         ensure_ascii=False), encoding="utf-8")
                etat["communiques"].append({"date": jour, "titre": e.title, "lien": lien, "fichier": fichier})
            etat["communiques"] = sorted(etat["communiques"], key=lambda c: c["date"])[-6:]
        except Exception as exc:  # noqa: BLE001 — une banque en échec n'affecte qu'elle
            etat["erreur"] = f"{type(exc).__name__} : {str(exc)[:160]}"
    (dossier / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return index


def options_debattues(texte: str, maximum: int = 3) -> list[str]:
    sortie = []
    for p in phrases(texte):
        if (re.search(r"\b(consider\w*|discuss\w*|debat\w*|weigh\w*|options?|case for|views? (?:differed|were))\b", p, re.I)
                and re.search(r"\b(hold\w*|maintain\w*|increas\w*|rais\w*|cut\w*|lower\w*|reduc\w*|unchanged|hike\w*)\b", p, re.I)):
            sortie.append(p)
        if len(sortie) >= maximum:
            break
    return sortie


def indication_suite(texte: str, maximum: int = 2) -> list[str]:
    sortie = []
    for p in phrases(texte):
        if re.search(r"\b(further|additional|next|future|coming (?:months|meetings)|again)\b", p, re.I) and re.search(
                r"\b(increase|hike|tighten\w*|cut|reduc\w*|adjust\w*|needed|necessary|appropriate)\b", p, re.I):
            sortie.append(p)
        if len(sortie) >= maximum:
            break
    return sortie


def archiver_pv(racine: Path, config: dict | None, session=None, aujourd: date | None = None) -> dict:
    """Procès-verbaux : flux de la Fed, page de liste de la Banque du Canada ; une requête par document nouveau."""
    import feedparser
    import requests
    dossier = Path(racine) / "data" / "communiques_v9"
    dossier.mkdir(parents=True, exist_ok=True)
    index = _lire(dossier / "index.json") or {"banques": {}}
    pvs = index.setdefault("pv", {})
    aujourd = aujourd or datetime.now(timezone.utc).date()
    ua = {"User-Agent": ((config or {}).get("scraping") or {}).get("user_agent") or "agents-forex/1.0"}
    s = session or requests
    for dev, cfg in PV.items():
        etat = pvs.setdefault(dev, {"documents": []})
        if "flux" not in cfg and "page" not in cfg:
            etat["raison"] = cfg.get("raison") or cfg.get("meme_document")
            continue
        if etat.get("lu_le") == aujourd.isoformat():
            continue
        etat["lu_le"] = aujourd.isoformat()
        try:
            if "flux" in cfg:
                rep = s.get(cfg["flux"], headers=ua, timeout=30)
                rep.raise_for_status()
                cands = [(e.title, e.link, _date_entree(e)) for e in feedparser.parse(rep.content).entries if re.search(cfg["titre"], e.title)][:1]
            else:
                from bs4 import BeautifulSoup
                rep = s.get(cfg["page"], headers=ua, timeout=30)
                rep.raise_for_status()
                soup = BeautifulSoup(rep.content, "lxml")
                a = next((a for a in soup.find_all("a", href=True) if re.search(cfg["lien"], a["href"])), None)
                m = re.search(r"/(\d{4})/(\d{2})/", a["href"]) if a else None
                cands = [(a.get_text(" ", strip=True), a["href"], f"{m.group(1)}-{m.group(2)}-01" if m else None)] if a else []
            connus = {d["lien"] for d in etat["documents"]}
            for titre, lien, jour in cands:
                if lien in connus:
                    continue
                r = s.get(lien, headers=ua, timeout=40)
                if r.status_code == 403:
                    etat["raison"] = "document refusé (403) : jamais contourné"
                    continue
                r.raise_for_status()
                fichier = f"PV_{dev}_{(jour or aujourd.isoformat())}.json"
                (dossier / fichier).write_text(json.dumps({"devise": dev, "titre": titre, "lien": lien, "date": jour,
                                                          "texte": extraire_texte(r.content, lien)}, ensure_ascii=False), encoding="utf-8")
                etat["documents"] = (etat["documents"] + [{"date": jour, "titre": titre, "lien": lien, "fichier": fichier}])[-4:]
            etat["raison"] = None if etat["documents"] else "aucun procès-verbal trouvé"
        except Exception as exc:  # noqa: BLE001
            etat["raison"] = f"{type(exc).__name__} : {str(exc)[:140]}"
    (dossier / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return index


def analyser_pv(racine: Path | None = None) -> dict:
    dossier = Path(racine or RACINE) / "data" / "communiques_v9"
    pvs = (_lire(dossier / "index.json") or {}).get("pv") or {}
    sortie = {}
    for dev, cfg in PV.items():
        etat = pvs.get(dev) or {}
        docs = etat.get("documents") or []
        if not docs:
            sortie[dev] = {"disponible": False, "raison": etat.get("raison") or cfg.get("raison") or cfg.get("meme_document") or "non lu"}
            continue
        d = _lire(dossier / docs[-1]["fichier"])
        t = d.get("texte", "")
        sortie[dev] = {"disponible": True, "titre": d.get("titre"), "lien": d.get("lien"), "date": d.get("date"),
                       "options": options_debattues(t), "suite": indication_suite(t), "projections": projections(t)}
    return sortie


def analyser(racine: Path | None = None) -> dict:
    """Faits par devise : dernier communiqué, votes, projections, vocabulaire (Python)."""
    racine = Path(racine or RACINE)
    dossier = racine / "data" / "communiques_v9"
    index = _lire(dossier / "index.json")
    sortie = {}
    for dev, cfg in BANQUES.items():
        etat = (index.get("banques") or {}).get(dev) or {}
        liste = etat.get("communiques") or []
        if not liste:
            sortie[dev] = {"banque": cfg["banque"], "disponible": False,
                           "raison": etat.get("erreur") or "aucun communiqué archivé (prochain run)"}
            continue
        dernier = _lire(dossier / liste[-1]["fichier"])
        prec = _lire(dossier / liste[-2]["fichier"]) if len(liste) > 1 else {}
        sortie[dev] = {"banque": cfg["banque"], "disponible": True, "date": dernier.get("date"), "titre": dernier.get("titre"),
                       "lien": dernier.get("lien"), "votes": votes(dernier.get("texte", ""), cfg.get("votes"), cfg.get("raison_votes")),
                       "projections": projections(dernier.get("texte", "")),
                       "vocabulaire": vocabulaire(dernier.get("texte", ""), prec.get("texte")),
                       "precedent": {"date": prec.get("date"), "lien": prec.get("lien")} if prec else None,
                       "source": f"communiqué officiel ({cfg['banque']}), {dernier.get('lien')}", "alerte": etat.get("erreur")}
    return sortie


def corriger_archive(analyse: dict, racine: Path | None = None) -> int:
    """Vote officiel -> archive des publications (champ votes_officiels de l'entrée « votes » du même jour)."""
    from core import publications_archive as pa
    racine = Path(racine or RACINE)
    chemin = racine / "data" / "cache" / "publications_archive.json"
    archive = pa.charger(chemin)
    n = 0
    for dev, a in analyse.items():
        v = (a.get("votes") or {})
        if not a.get("disponible") or not v.get("texte"):
            continue
        for p in (archive.get("publications") or {}).values():
            if p.get("devise") == dev and re.search(r"votes", p.get("evenement_en") or "", re.I) and abs(
                    (date.fromisoformat(p["date"]) - date.fromisoformat(a["date"])).days) <= 2:
                corr = {"texte": v["texte"], "minorite": v.get("minorite"), "source": a["source"], "lien": a["lien"]}
                if p.get("votes_officiels") != corr:
                    p["votes_officiels"] = corr
                    n += 1
    if n:
        chemin.write_text(json.dumps(archive, ensure_ascii=False, indent=0), encoding="utf-8")
    return n


def mettre_a_jour(racine: Path | None = None, config: dict | None = None) -> dict:
    """Archive, analyse et correction de l'archive des publications ; ne lève jamais."""
    try:
        racine = Path(racine or RACINE)
        docs = racine / ((config or {}).get("publication_web") or {}).get("dossier_docs", "docs") / "data"
        aujourd = datetime.now(timezone.utc).date()
        archiver(racine, config, aujourd=aujourd, decisions=decisions_du_jour(_lire(docs / "agenda.json"), aujourd))
        try:
            archiver_pv(racine, config, aujourd=aujourd)
        except Exception as exc:  # noqa: BLE001
            log.warning("procès-verbaux : %s", exc)
        a = analyser(racine)
        corriger_archive(a, racine)
        return a
    except Exception as exc:  # noqa: BLE001
        log.error("communiqués V9 : %s", exc)
        return {}
