"""Briefing du jour (lot V8) : page d'accueil « utile en séance », calculée en Python -> docs/data/briefing.json.

Titre du jour (décision de banque centrale aujourd'hui, sinon le thème), trois lignes Contexte / Scénario / Paire, tableau
« Jour de décision » (précédent / attendu / publié pour le taux, les votes et le discours, réaction de la paire principale
après publication), publications du jour (heures UTC exactes : le site n'y calcule que les comptes à rebours), bandes des
sessions à l'heure de Paris (heures locales des places : changements d'heure été/hiver compris), paires à regarder en
premier, seuils au bord, bandeau de 8 marchés. Réécrit à chaque run (les runs horaires remplissent « publié »).
Aide à la décision : aucun ordre d'achat ou de vente.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

PAIRE_PRINCIPALE = {"USD": "EUR/USD", "EUR": "EUR/USD", "GBP": "GBP/USD", "JPY": "USD/JPY", "CHF": "USD/CHF",
                    "CAD": "USD/CAD", "AUD": "AUD/USD", "NZD": "NZD/USD", "CNY": "USD/CNY"}
# Heures locales d'ouverture des places (convention de marché) : converties chaque jour à l'heure de Paris.
SESSIONS = [("Asie", "Asia/Tokyo", 9, 18), ("Londres", "Europe/London", 8, 17), ("New York", "America/New_York", 8, 17)]
MARCHES = ["Indice dollar (formule du DXY, non officiel)", "EUR/USD", "GBP/USD", "USD/JPY", "US 2 ans", "Or (XAU/USD)", "Brent", "VIX"]
CONVICTION = {"faible": "faible", "moyen": "moyenne", "fort": "forte"}
CAS_LECTURE = {"hausse": ("Hausse, ton restrictif", "Hausse, ton accommodant"),
               "baisse": ("Baisse, ton accommodant", "Baisse, ton restrictif"),
               "statu_quo": ("Maintien, ton restrictif", "Maintien, ton accommodant")}


def _zone(nom: str):
    from zoneinfo import ZoneInfo
    return ZoneInfo(nom)


def _lire(chemin: Path) -> dict | None:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def sessions_paris(jour: date) -> list[dict]:
    """Bandes des sessions en heures décimales de Paris (ex. Londres 9,0 → 18,0 en hiver), selon les heures locales."""
    paris = _zone("Europe/Paris")
    sortie = []
    for nom, tz, h1, h2 in SESSIONS:
        z = _zone(tz)
        debut = datetime.combine(jour, time(h1), z).astimezone(paris)
        fin = datetime.combine(jour, time(h2), z).astimezone(paris)
        d = debut.hour + debut.minute / 60 + (-24 if debut.date() < jour else 0)
        f = fin.hour + fin.minute / 60 + (-24 if fin.date() < jour else 24 if fin.date() > jour else 0)
        sortie.append({"nom": nom, "debut": round(d, 2), "fin": round(f, 2), "fuseau": tz,
                       "texte": f"{nom} : {h1:02d}:00–{h2:02d}:00 heure locale ({tz})"})
    return sortie


def _sans_prefixe(t: str, prefixe: str) -> str:
    return re.sub("^" + re.escape(prefixe), "", t or "").strip()


def titre_du_jour(rj: dict, aujourd: str) -> tuple[str, dict | None]:
    """« Journée Banque d'Angleterre : hausse attendue de 25 pb à 13:00 » s'il y a une décision aujourd'hui, sinon le thème."""
    bq = next((b for b in rj.get("banques") or [] if b.get("date") == aujourd), None)
    if bq:
        nom = re.sub(r"\s*\(.*\)", "", bq.get("banque") or bq.get("court") or "Banque centrale")
        b = bq.get("badge") or {}
        attente = (f"{b['texte']} de {abs(b['pb'])} pb" if b.get("pb") and b.get("sens") in ("hausse", "baisse")
                   else b.get("texte") or "décision")
        return f"Journée {nom} : {attente} à {bq.get('heure') or 'heure n/d'}", bq
    return (rj.get("theme") or {}).get("titre") or "Thème du jour n/d", None


def lignes_contexte(rj: dict, entete: dict) -> list[list[str]]:
    t, ess = rj.get("theme") or {}, (rj.get("essentiel") or {}).get("lignes") or []
    trouve = lambda p: next((x for x in ess if x.startswith(p)), None)   # noqa: E731
    scen = trouve("Le mieux confirmé à ce jour : ") or trouve("Aucun scénario")
    paire = trouve("Paire à suivre en premier : ")
    devises = next((x for x in ess if "Soutenue" in x or "Sous pression" in x or "sans direction" in x), None)
    contexte = (f"{t.get('titre', 'Thème n/d')} : {entete.get('alignes', 'n/d')} engrenages sur {entete.get('evaluables', 'n/d')} "
                f"suivent le thème, conviction {CONVICTION.get(t.get('conviction'), t.get('conviction') or 'n/d')}.")
    return [["Contexte", contexte],
            ["Scénario", _sans_prefixe(scen or "n/d : scénarios absents du rapport", "Le mieux confirmé à ce jour : ")],
            ["Paire", (_sans_prefixe(paire, "Paire à suivre en premier : ").rstrip(".") if paire else "n/d")
             + (f". Devises : {devises}" if devises else "")]]


def _ts(iso: str | None) -> float | None:
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return None


def reaction(paire: str, iso_decision: str, fiche: dict | None, cotations: dict) -> dict | None:
    """Variation de la paire depuis la dernière bougie 30 min close avant la décision, au cours de séance (Twelve Data)."""
    t0 = _ts(iso_decision)
    q = (cotations or {}).get(paire) or {}
    bougies = (((fiche or {}).get("chandeliers") or {}).get("30min") or {}).get("bougies") or []
    if t0 is None or q.get("prix") is None or not bougies:
        return None
    avant = [b for b in bougies if (_ts(str(b[0]).replace(" ", "T") + "+00:00") or 0) < t0]
    if not avant or _ts(q.get("heure_utc")) is None or _ts(q.get("heure_utc")) <= t0:
        return None
    ref = avant[-1][4]
    return {"paire": paire, "variation_pct": round((q["prix"] / ref - 1) * 100, 2), "depuis": avant[-1][0],
            "cours": q["prix"], "heure_utc": q.get("heure_utc"), "source": "Twelve Data (bougie 30 min avant la décision, cours de séance)"}


def jour_de_decision(bq: dict, evenements: list[dict], rj: dict, paires: dict | None, cotations: dict) -> dict:
    devise = bq.get("devise")
    du_jour = [e for e in evenements if e.get("devise") == devise]
    bc = [e for e in du_jour if e.get("type") == "Réunion BC"]
    votes = next((e for e in bc if re.search(r"vote", (e.get("evenement_en") or "") + (e.get("evenement") or ""), re.I)), None)
    taux = next((e for e in bc if e is not votes), None)
    discours = next((e for e in du_jour if e.get("type") == "Discours" and e.get("impact") == "fort"), None)
    ligne = lambda lib, e, prec, att: {"libelle": lib, "precedent": prec, "attendu": att,   # noqa: E731
                                       "publie": (e or {}).get("publie"), "heure": (e or {}).get("heure_paris") or bq.get("heure"),
                                       "iso_utc": (e or {}).get("iso_utc")}
    lignes = [ligne("Taux directeur", taux, bq.get("taux"), bq.get("consensus"))]
    if votes:
        lignes.append(ligne("Votes du comité", votes, votes.get("precedent"), votes.get("consensus")))
    lignes.append(ligne("Discours du gouverneur", discours, None, None) if discours else
                  {"libelle": "Discours du gouverneur", "precedent": None, "attendu": None, "publie": None, "heure": None,
                   "raison": "aucun discours à fort impact à l'Agenda aujourd'hui"})
    paire = PAIRE_PRINCIPALE.get(devise)
    fiche = ((paires or {}).get("fiches") or {}).get(paire)
    a_bougies = bool((((fiche or {}).get("chandeliers") or {}).get("30min") or {}).get("bougies"))
    sens = (bq.get("badge") or {}).get("sens") or "statu_quo"
    interp = {x[0].split(" (")[0]: x[1] for x in rj.get("interpretation") or [] if isinstance(x, list) and len(x) == 2}
    cas = [{"titre": "Si " + c[0].lower() + c[1:].replace(", ton", " avec ton"), "lecture": interp.get(c)}
           for c in CAS_LECTURE.get(sens, ()) if interp.get(c)]
    return {"banque": bq.get("banque"), "court": bq.get("court"), "devise": devise, "heure": bq.get("heure"),
            "badge": bq.get("badge"), "lignes": lignes, "cas": cas,
            "paire": paire, "paire_bougies": a_bougies,
            # bougies 30 min de la paire principale, copiées ici : la page d'accueil ne charge pas paires.json
            "bougies_30min": (((fiche or {}).get("chandeliers") or {}).get("30min") or {}).get("bougies") if a_bougies else None,
            "raison_bougies": None if a_bougies else "bougies 30 min collectées seulement pour les paires suivies (Journal)",
            "reaction": reaction(paire, (taux or {}).get("iso_utc"), fiche, cotations) if (taux or {}).get("publie") else None,
            "note": "Le tableau se remplit à la publication ; le run horaire suivant ajoute le résultat et la réaction."}


def calculer(rj: dict, dossiers: dict | None, agenda: dict | None, paires: dict | None, seance: dict | None,
             maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    aujourd = (agenda or {}).get("aujourdhui") or maintenant.astimezone(_zone("Europe/Paris")).date().isoformat()
    entete = ((dossiers or {}).get("cockpit") or {}).get("entete") or {}
    jour = next((j for j in (agenda or {}).get("jours") or [] if j.get("date") == aujourd), {}) or {}
    champs = ("iso_utc", "heure_paris", "heure_connue", "devise", "evenement", "type", "impact", "precedent", "consensus",
              "publie", "votes", "badge", "ecart")
    evenements = [{k: e.get(k) for k in champs} for e in jour.get("evenements") or [] if e.get("iso_utc")]
    titre, bq = titre_du_jour(rj, aujourd)
    top = rj.get("watchlist_top3") or []
    tw = (rj.get("textes") or {}).get("watchlist") or {}
    lignes_m = {l.get("actif"): l for l in (rj.get("point_marche") or {}).get("lignes") or []}
    return {
        "genere_le": maintenant.isoformat(timespec="seconds"), "date": aujourd, "rapport_genere_le": rj.get("genere_le"),
        "titre": titre, "titre_source": "décision de banque centrale du jour (Agenda)" if bq else "thème du jour (8 engrenages)",
        "lignes": lignes_contexte(rj, entete),
        "sessions": sessions_paris(date.fromisoformat(aujourd)),
        "evenements": evenements,
        "decision": jour_de_decision(bq, evenements, rj, paires, (seance or {}).get("cotations") or {}) if bq else None,
        "paires": [{"paire": w["paire"], "libelle": w.get("libelle"), "score": w.get("score"),
                    "texte": (tw.get(w["paire"]) or {}).get("haussier") or (w.get("scenario_haussier") or {}).get("texte")}
                   for w in top[:3]],
        "au_bord": ((dossiers or {}).get("cockpit") or {}).get("au_bord") or (rj.get("tableau_de_bord") or {}).get("au_bord") or [],
        "marches": [lignes_m[a] for a in MARCHES if a in lignes_m],
        "mention": "Aide à la décision : aucun ordre d'achat ou de vente.",
    }


def _paires_completes(docs: Path) -> dict:
    """paires.json léger + détail (bougies) des paires suivies et des paires principales des banques centrales."""
    from core import paires as pm
    leger = _lire(docs / "paires.json") or {}
    return pm.lire_complet(docs, sorted(set(leger.get("mes_paires") or []) | set(PAIRE_PRINCIPALE.values())))


def ecrire(racine: str | Path, config: dict, maintenant: datetime | None = None) -> dict | None:
    """Écrit docs/data/briefing.json à partir des JSON déjà publiés du run ; ne lève jamais."""
    try:
        docs = Path(racine) / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
        rj = _lire(docs / "rapport_jour.json")
        if not rj:
            return None
        donnees = calculer(rj, _lire(docs / "dossiers.json"), _lire(docs / "agenda.json"), _paires_completes(docs),
                           _lire(docs / "seance.json"), maintenant)
        (docs / "briefing.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("briefing.json non écrit : %s", exc)
        return None
