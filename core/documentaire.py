"""Lot V13 : l'onglet « 8 engrenages » devient un documentaire hebdomadaire -> docs/data/documentaire/AAAA-Sxx.json.

Un long rapport à lire dans la journée : ce qui s'est passé sur les marchés cette semaine, moteur par moteur, avec la
pédagogie (texte permanent de core/noms_moteurs.COMPRENDRE), les indicateurs à jour expliqués (variation sur la semaine,
percentile, « ce que c'est »), deux graphiques de 6 mois par moteur (historique_5ans), le récit de la semaine (rédigé par le
modèle à partir des faits ci-dessous, Groq en secours, secours Python en phrases complètes, contrôle des nombres), les
publications et l'actualité de la semaine, les effets sur les devises (et ce qui a changé depuis lundi), les risques de la
semaine suivante, puis un chapitre final (calendrier de 5 jours, jours fériés, risque principal).

Le documentaire se construit au fil de la semaine (lundi soir : lundi ; vendredi soir : toute la semaine) ; le week-end, il
présente la semaine écoulée et la suivante. Archive des 12 dernières semaines. Tout calcul est fait ici (Python) ; une
section qui échoue ne casse jamais les autres (« erreur » dans le chapitre, le reste est publié).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core import contexte as ctx_mod
from core import dossiers_moteurs as dm
from core import noms_moteurs as nm
from core import seuils as seuils_mod
from core import indicateurs_cles
from core import redaction_documentaire as rd
from core import surprises

log = logging.getLogger(__name__)
PARIS = ZoneInfo("Europe/Paris")
DEVISES = dm.DEVISES
MOTS_PAR_MINUTE = 230
SEMAINES_ARCHIVE = 12
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
JOURS_COURTS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

# Graphiques par moteur (jamais deux axes : un graphique par série) : (série historique_5ans, titre, décimales, légende, mesure)
# mesure : « pb » (taux en %, variation en points de base), « % » (variation relative), « pts » (variation absolue)
GRAPHIQUES = {
    1: [("vix", "VIX", 2, "La peur sur les actions américaines", "pts"), ("sp500", "S&P 500", 0, "L'appétit pour le risque", "%")],
    2: [("USD_2a", "Rendement 2 ans US (%)", 2, "Ce que le marché attend de la Fed", "pb"),
        ("FX_JPY", "USD/JPY", 2, "La paire la plus sensible à l'écart de taux", "%")],
    3: [],
    4: [("USD_10a", "Rendement 10 ans US (%)", 2, "Taux longs : croissance, inflation et prime de risque", "pb"),
        ("USD_prime_terme", "Prime de terme 10 ans US (%)", 2, "Ce que les investisseurs exigent pour prêter longtemps", "pb")],
    5: [("indice_or", "Or (indice proxy)", 0, "Refuge et taux réels", "%"), ("brent", "Brent ($/baril)", 2, "L'énergie", "%")],
    6: [("brent", "Brent ($/baril)", 2, "Le premier canal des chocs géopolitiques", "%"), ("vix", "VIX", 2, "La peur", "pts")],
    7: [("dollar_large", "Indice dollar large (Fed)", 2, "La tendance du dollar", "%"), ("FX_EUR", "EUR/USD", 4, "La première paire mondiale", "%")],
    8: [("brent", "Brent ($/baril)", 2, "Prix mondial du pétrole", "%"), ("wti", "WTI ($/baril)", 2, "Prix américain du pétrole", "%")],
}

# « Ce que c'est » : texte fixe par indicateur (motif sur le libellé de la tuile, premier qui correspond)
DEFINITIONS = nm.DEFINITIONS   # lot V15 : figées dans core/noms_moteurs.py


# ------------------------------------------------------------------ outils
def _lire(p: Path) -> dict:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fr(v, d: int = 2) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/d"
    s = f"{abs(v):,.{d}f}".replace(",", " ").replace(".", ",")
    return ("−" if v < 0 else "") + s


def sgn(v, d: int = 2, u: str = "") -> str:
    if v is None:
        return "n/d"
    return ("+" if v > 0 else "") + fr(v, d) + u


def ddm(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso and len(str(iso)) >= 10 else "n/d"


NOMS_DEVISES = {"USD": "le dollar américain", "EUR": "l'euro", "GBP": "la livre sterling", "JPY": "le yen", "CHF": "le franc suisse",
                "CAD": "le dollar canadien", "AUD": "le dollar australien", "NZD": "le dollar néo-zélandais", "CNY": "le yuan"}
PAYS = {"USD": "les États-Unis", "EUR": "la zone euro", "GBP": "le Royaume-Uni", "JPY": "le Japon", "CHF": "la Suisse", "CAD": "le Canada",
        "AUD": "l'Australie", "NZD": "la Nouvelle-Zélande", "CNY": "la Chine"}


def devise(dev: str, majuscule: bool = False) -> str:
    """« le yen (JPY) » ; majuscule : « Le yen (JPY) »."""
    t = f"{NOMS_DEVISES.get(dev, dev)} ({dev})"
    return t[0].upper() + t[1:] if majuscule else t


def frtxt(v) -> str:
    """« 2.5% » -> « 2,5 % » ; « -43.5K » -> « −43,5K » (valeurs publiées telles quelles, au format français)."""
    t = str(v if v is not None else "n/d")
    t = re.sub(r"(\d)\.(\d)", r"\1,\2", t)
    t = re.sub(r"(\d)%", r"\1 %", t)
    return re.sub(r"^-(?=\d)", "−", t)


def jour_court(iso: str) -> str:
    return f"{JOURS_COURTS[date.fromisoformat(iso[:10]).weekday()]} {ddm(iso)}"


def jour_long(iso: str) -> str:
    return f"{JOURS[date.fromisoformat(iso[:10]).weekday()]} {ddm(iso)}"


def mots(texte: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ'’-]+\b", str(texte or "")))


def semaine_iso(d: date) -> str:
    a, s, _ = d.isocalendar()
    return f"{a}-S{s:02d}"


# ------------------------------------------------------------------ semaine couverte
def bornes_semaine(maintenant: datetime) -> dict:
    """Semaine présentée : en semaine, la semaine en cours (du lundi au jour même) ; le week-end, la semaine écoulée
    (complète) et la suivante. -> {id, du, au, fin_donnees, statut, suivante_du, suivante_au}"""
    j = maintenant.astimezone(PARIS).date()
    if j.weekday() >= 5:
        lundi = j - timedelta(days=j.weekday())
        vendredi = lundi + timedelta(days=4)
        fin, statut = vendredi, "complète"
    else:
        lundi = j - timedelta(days=j.weekday())
        vendredi = lundi + timedelta(days=4)
        fin, statut = j, "complète" if j.weekday() == 4 and maintenant.astimezone(PARIS).hour >= 22 else "en cours"
    sl = lundi + timedelta(days=7)
    return {"id": semaine_iso(lundi), "du": lundi.isoformat(), "au": vendredi.isoformat(), "fin_donnees": fin.isoformat(),
            "statut": statut, "suivante_du": sl.isoformat(), "suivante_au": (sl + timedelta(days=4)).isoformat(),
            "jours": [(lundi + timedelta(days=i)).isoformat() for i in range(min(5, (fin - lundi).days + 1))]}


def _dernier_avant(points: list, jour: str):
    """Dernier point dont la date est <= jour (jour férié : la séance précédente)."""
    r = None
    for p in points:
        if str(p[0])[:10] <= jour:
            r = p
        else:
            break
    return r


def variation_semaine(points: list, du: str, fin: str, mesure: str) -> dict:
    """Vendredi contre vendredi précédent, calculée sur les points (jour férié : dernière séance disponible avant ; série
    courte : n/d avec la raison). mesure : « pb » (série en %, résultat en points de base), « % » (relative), autre (absolue)."""
    pts = sorted([[str(d)[:10], v] for d, v in points if v is not None], key=lambda p: p[0])
    vendredi_prec = (date.fromisoformat(du) - timedelta(days=3)).isoformat()
    a, b = _dernier_avant(pts, vendredi_prec), _dernier_avant(pts, fin)
    if not b:
        return {"valeur": None, "raison": "aucune donnée dans la semaine"}
    if not a:
        return {"valeur": None, "raison": f"série trop courte : aucun point avant le {ddm(vendredi_prec)}"}
    if b[0] < du:
        return {"valeur": None, "raison": f"pas de donnée cette semaine (dernière le {ddm(b[0])})", "derniere": b}
    if mesure == "pb":
        v, u, dec = round((b[1] - a[1]) * 100), " pb", 0
    elif mesure == "%":
        if not a[1]:
            return {"valeur": None, "raison": "valeur de départ nulle"}
        v, u, dec = round((b[1] / a[1] - 1) * 100, 2), " %", 2
    else:
        unite = mesure[4:] if mesure.startswith("abs:") else mesure
        v, dec = round(b[1] - a[1], 2), (0 if unite == "pb" else 2)
        u = f" {unite}" if unite and unite not in ("niveau", "nombre", "score", "rsi") else ""
    return {"valeur": v, "unite": u.strip(), "du": a[0], "au": b[0], "debut": a[1], "fin": b[1],
            "texte": f"{sgn(v, dec, u)} sur la semaine ({jour_court(a[0])} → {jour_court(b[0])})",
            "court": f"{sgn(v, dec, u)} sur la semaine", "raison": None}


def unite_graphique(titre: str) -> str:
    """« Rendement 2 ans US (%) » -> « % » ; « Brent ($/baril) » -> « $ » (unité affichée après la valeur)."""
    m = re.search(r"\(([^)]*)\)\s*$", titre or "")
    if not m:
        return ""
    u = m.group(1)
    return " %" if u == "%" else " $" if u.startswith("$") else ""


def lecture_niveau(p) -> str | None:
    if p is None:
        return None
    return ("niveau exceptionnellement haut" if p >= 90 else "niveau élevé" if p >= 70 else "niveau exceptionnellement bas" if p <= 10
            else "niveau bas" if p <= 30 else "niveau dans la norme")


def definition(libelle: str) -> str:
    return next((t for m, t in DEFINITIONS if re.search(m, libelle or "")), "")


def _mesure_tuile(t: dict) -> str:
    """« pb » : valeurs en %, variation en points de base ; « % » : variation relative ; « abs:<unité> » : différence simple."""
    vu, u = (t.get("variation") or {}).get("unite"), t.get("unite")
    if u == "%" and vu in ("pb", None):
        return "pb"
    if vu == "%":
        return "%"
    return f"abs:{vu or u or ''}"


def _ampleur(points: list, v_semaine, mesure: str) -> float:
    """Variation de la semaine rapportée à la variation habituelle sur 5 séances, dans la même mesure (points de base,
    variation relative ou absolue) : sert à choisir « le chiffre qui a le plus bougé »."""
    vals = [v for _, v in points if v is not None]
    if v_semaine is None or len(vals) < 12:
        return 0.0
    if mesure == "pb":
        diffs = [(vals[i] - vals[i - 5]) * 100 for i in range(5, len(vals))]
    elif mesure == "%":
        diffs = [(vals[i] / vals[i - 5] - 1) * 100 for i in range(5, len(vals)) if vals[i - 5]]
    else:   # différence simple (pb, points, contrats…)
        diffs = [vals[i] - vals[i - 5] for i in range(5, len(vals))]
    s = statistics.pstdev(diffs) if len(diffs) > 2 else 0
    return abs(v_semaine) / s if s else 0.0


# ------------------------------------------------------------------ titres de la semaine (accumulés à chaque run)
CACHE_TITRES = Path("data") / "cache" / "titres_semaine.json"


def accumuler_titres(racine: Path, articles: list[dict], maintenant: datetime) -> dict:
    """Ajoute les titres classés du run à la semaine ISO en cours (sans doublon) ; garde 3 semaines."""
    chemin = Path(racine) / CACHE_TITRES
    d = _lire(chemin) or {"semaines": {}}
    sem = semaine_iso(maintenant.astimezone(PARIS).date())
    stock = d["semaines"].setdefault(sem, {})
    resumes = {str(a.get("titre") or "").strip(): str(a.get("resume") or "")[:300] for a in articles or []}
    for t in dm.titres_classes(articles, maintenant.date().isoformat()):
        cle = re.sub(r"\W+", " ", dm._sans_accent(t["titre"])).strip()[:120]
        if cle not in stock:   # lot V14 : le résumé est gardé pour reclasser plus tard avec les règles du jour
            stock[cle] = {**t, "resume": resumes.get(t["titre"]) or None,
                          "vu_le": maintenant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M+00:00")}
    for s in sorted(d["semaines"])[:-3]:
        d["semaines"].pop(s, None)
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except OSError as exc:
        log.warning("titres de la semaine non écrits : %s", exc)
    return d


def titres_semaine(racine: Path, sem: str) -> list[dict]:
    """Titres accumulés de la semaine, reclassés avec les règles du jour (lot V14 : synthèses de marché au moteur 1,
    entreprise isolée écartée)."""
    d = _lire(Path(racine) / CACHE_TITRES)
    sortie = []
    for t in (d.get("semaines") or {}).get(sem, {}).values():
        m = dm.reclasser(t)
        if m:
            sortie.append({**t, "moteurs": m, "pourquoi": {str(n): dm.POURQUOI_TITRE[n] for n in m}})
    return sorted(sortie, key=lambda t: str(t.get("date") or t.get("vu_le") or ""), reverse=True)


# ------------------------------------------------------------------ publications de la semaine
def publications_semaine(archive: dict, cfg_tm: dict, du: str, fin: str) -> list[dict]:
    """Publications moyennes et fortes des 9 devises entre du et fin (archive du site), avec réel, consensus, précédent,
    sens de la surprise, écart en écarts habituels et moteur rattaché (table de types de core/dossiers_moteurs)."""
    from core import agenda as ag_mod
    index = surprises.ecarts_archives(archive)
    sortie = []
    for p in ((archive or {}).get("publications") or {}).values():
        impact, releve = indicateurs_cles.relever(p.get("devise"), p.get("evenement_en"), p.get("impact"))   # lot V14 (V13.1)
        if not (du <= str(p.get("date")) <= fin) or p.get("devise") not in DEVISES or impact not in ("moyen", "fort"):
            continue
        e = {"evenement": p.get("evenement"), "evenement_en": p.get("evenement_en"), "type": p.get("type"), "devise": p.get("devise")}
        ec = None
        if p.get("reel") and p.get("consensus"):
            ec = ag_mod.ecart(p["reel"], p["consensus"], ag_mod._indicateur(e, cfg_tm), cfg_tm, p.get("type"), index, p.get("devise"),
                              p.get("evenement_en"), p.get("date"))
        pastille = "sans consensus" if not ec else ec["sens"]
        sortie.append({"id": f"{p.get('date')}|{p.get('devise')}|{str(p.get('evenement_en') or '').lower()}", "date": p.get("date"),
                       "heure": p.get("heure_paris"), "devise": p.get("devise"), "evenement": p.get("evenement"),
                       "evenement_en": p.get("evenement_en"), "type": p.get("type"), "impact": impact, "impact_releve": releve,
                       "reel": p.get("reel"), "consensus": p.get("consensus"), "precedent": p.get("precedent"), "pastille": pastille,
                       "z": (ec or {}).get("z"), "favorable": (ec or {}).get("favorable"), "base_z": (ec or {}).get("base_z"),
                       "raison_z": (ec or {}).get("raison_z"), "moteur": dm.moteur_publication(e),
                       "source": p.get("source") or "ForexFactory (archive des publications du site)"})
    return sorted(sortie, key=lambda x: (x["date"], x.get("heure") or "", x["devise"]))


def solde_surprises(pubs: list[dict]) -> dict:
    """Solde des surprises par devise : chaque publication compte pour |z|, dans le sens favorable à la devise ; un écart
    aberrant (|z| > 5) compte pour 1 et le problème est consigné dans les logs."""
    par, aberrants = {}, []
    for p in pubs:
        if p.get("favorable") is None or p.get("z") is None:
            continue
        poids, aberrant = surprises.poids_solde(p["z"])
        if aberrant:
            aberrants.append(f"{p['devise']} {p['evenement']} ({ddm(p['date'])}) : z = {p['z']}, compté pour 1")
            log.warning("surprise aberrante (erreur d'échelle probable) : %s %s %s z=%s", p["date"], p["devise"], p["evenement"], p["z"])
        x = par.setdefault(p["devise"], {"devise": p["devise"], "solde": 0.0, "n": 0})
        x["solde"] = round(x["solde"] + (poids if p["favorable"] else -poids), 2)
        x["n"] += 1
    return {"barres": sorted(par.values(), key=lambda x: -x["solde"]), "aberrants": aberrants,
            "methode": "chaque publication compte pour son écart au consensus en écarts habituels, dans le sens favorable à la "
                       "devise (un chômage plus haut que prévu compte en négatif) ; un écart aberrant compte pour 1",
            "source": "ForexFactory, archive des publications du site"}


# ------------------------------------------------------------------ contexte jour par jour (archive contexte/)
def contexte_jours(docs_data: Path, jours: list[str]) -> dict:
    """{jour: dernier instantané du jour} pour les jours de la semaine (archive contexte/)."""
    sortie = {}
    for j in jours:
        f = _lire(Path(docs_data) / "contexte" / f"{j}.json")
        if f.get("instantanes"):
            try:
                sortie[j] = ctx_mod.reconstituer(f, len(f["instantanes"]) - 1)
            except Exception as exc:  # noqa: BLE001
                log.warning("contexte du %s illisible : %s", j, exc)
    return sortie


def _effet(v) -> str:
    return "non mesuré" if v is None else "soutien" if v > 0 else "pression" if v < 0 else "neutre"


def changements_devises(ctx: dict, n: int) -> dict:
    """{devise: {debut, fin, jour_debut, jour_fin, texte}} : effet du moteur n au premier jour archivé de la semaine et au
    dernier (« JPY : neutre lundi → pression vendredi »)."""
    jours = sorted(ctx)
    if not jours:
        return {}
    a, b = ctx[jours[0]], ctx[jours[-1]]
    sortie = {}
    for d in DEVISES:
        va = ((a.get("devises") or {}).get(d, {}).get("moteurs") or [{}] * 8)[n - 1].get("v")
        vb = ((b.get("devises") or {}).get(d, {}).get("moteurs") or [{}] * 8)[n - 1].get("v")
        ea, eb = _effet(va), _effet(vb)
        ja, jb = JOURS[date.fromisoformat(jours[0]).weekday()], JOURS[date.fromisoformat(jours[-1]).weekday()]
        texte = (f"{d} : {ea} {ja} → {eb} {jb}" if ea != eb else f"{d} : {eb}, inchangé depuis {ja}") if len(jours) > 1 else f"{d} : {eb} ({ja})"
        sortie[d] = {"debut": ea, "fin": eb, "jour_debut": jours[0], "jour_fin": jours[-1], "change": ea != eb, "texte": texte}
    return sortie


# ------------------------------------------------------------------ jours fériés (principaux marchés)
def _paques(a: int) -> date:
    g, c = a % 19, a // 100
    h = (c - c // 4 - (8 * c + 13) // 25 + 19 * g + 15) % 30
    i = h - (h // 28) * (1 - (h // 28) * (29 // (h + 1)) * ((21 - g) // 11))
    j = (a + a // 4 + i + 2 - c + c // 4) % 7
    m = 3 + (i - j + 40) // 44
    return date(a, m, i - j + 28 - 31 * (m // 4))


def jours_feries(a: int) -> dict[str, list[str]]:
    """{date ISO: [« États-Unis : Thanksgiving », …]} : jours fériés qui ferment ou allègent les marchés principaux."""
    f: dict[str, list[str]] = {}
    ajoute = lambda d, t: f.setdefault(d.isoformat(), []).append(t)   # noqa: E731
    nov1 = date(a, 11, 1)
    thanks = nov1 + timedelta(days=(3 - nov1.weekday()) % 7 + 21)
    ajoute(thanks, "États-Unis : Thanksgiving (marchés fermés, séance courte le lendemain)")
    ajoute(date(a, 7, 4), "États-Unis : fête nationale")
    ajoute(date(a, 12, 25), "Noël (la plupart des marchés fermés)")
    ajoute(date(a, 12, 26), "Royaume-Uni, zone euro : lendemain de Noël")
    ajoute(date(a, 1, 1), "Nouvel an (la plupart des marchés fermés)")
    p = _paques(a)
    ajoute(p - timedelta(days=2), "Vendredi saint (marchés européens fermés)")
    ajoute(p + timedelta(days=1), "Lundi de Pâques (Europe)")
    may1 = date(a, 5, 1)
    ajoute(may1 + timedelta(days=(0 - may1.weekday()) % 7), "Royaume-Uni : jour férié de mai")
    sep1 = date(a, 9, 1)
    ajoute(sep1 + timedelta(days=(0 - sep1.weekday()) % 7), "États-Unis et Canada : Labor Day")
    jan1 = date(a, 1, 1)
    ajoute(jan1 + timedelta(days=(0 - jan1.weekday()) % 7 + 14), "États-Unis : Martin Luther King Day")
    return f


# ------------------------------------------------------------------ indicateurs, graphiques, risques
def indicateurs_moteur(dos: dict, n: int, sem: dict) -> list[dict]:
    sortie = []
    for t in ((dos.get("engrenages") or {}).get(str(n)) or {}).get("tuiles") or []:
        pts = [p for p in ((t.get("courbe") or {}).get("points") or []) if isinstance(p, (list, tuple)) and len(p) == 2]
        vs = variation_semaine(pts, sem["du"], sem["fin_donnees"], _mesure_tuile(t)) if len(pts) > 1 else {"valeur": None, "raison": "pas de série quotidienne"}
        p5 = t.get("percentile_5a")
        sortie.append({"libelle": t.get("libelle"), "texte": t.get("texte") or "n/d", "date": t.get("date"), "source": t.get("source"),
                       "raison": t.get("raison"), "variation_4s": (t.get("variation") or {}).get("texte"), "variation_semaine": vs,
                       "percentile_5a": p5, "points": [v for _, v in pts][-60:], "ce_que_cest": definition(t.get("libelle")),
                       "lecture_niveau": (lambda t: (t[0].upper() + t[1:] + ".") if t else None)(rd.niveau_simple(p5)),
                       "lecture_jour": t.get("lecture") or t.get("note"), "ampleur": round(_ampleur(pts, vs.get("valeur"), _mesure_tuile(t)), 2)})
    return sortie


def serie_fraiche(h5, cle: str, technique: dict | None = None) -> tuple[list, str | None]:
    """Série du cache 5 ans ; pour les paires (FX_JPY, FX_EUR…), la série unique Twelve Data raccordée à la Fed H.10 quand
    elle est plus récente (la Fed publie H.10 avec une semaine de retard)."""
    serie = list(h5.serie(cle)) if h5 is not None else []
    source = h5.source(cle) if h5 is not None and hasattr(h5, "source") else None
    if h5 is not None and cle.startswith("FX_") and technique:
        try:
            force = h5.force(cle[3:], technique)   # dollars par unité de devise
            alt = [(d, (1 / v if cle in ("FX_JPY", "FX_CHF", "FX_CAD", "FX_CNY") else v)) for d, v in force if v]
            if alt and (not serie or alt[-1][0] > serie[-1][0]):
                serie, source = alt, "séries uniques 5 ans (Twelve Data raccordé à la Fed H.10)"
        except Exception:  # noqa: BLE001
            pass
    return serie, source


def graphiques_moteur(h5, n: int, sem: dict, technique: dict | None = None) -> list[dict]:
    sortie = []
    for cle, titre, dec, legende, mesure in GRAPHIQUES.get(n, []):
        try:
            serie, src0 = serie_fraiche(h5, cle, technique)
        except Exception:  # noqa: BLE001
            serie, src0 = [], None
        if not serie:
            sortie.append({"cle": cle, "titre": titre, "raison": "série absente du cache 5 ans"})
            continue
        fin = sem["fin_donnees"]
        debut6m = (date.fromisoformat(fin) - timedelta(days=183)).isoformat()
        pts = [[d, v] for d, v in serie if debut6m <= d <= fin]
        if not pts:
            sortie.append({"cle": cle, "titre": titre, "raison": "aucun point sur 6 mois"})
            continue
        pts = [[d, round(v, 6)] for d, v in pts]
        vs = variation_semaine(pts, sem["du"], fin, mesure)
        sortie.append({"cle": cle, "titre": titre, "decimales": dec, "legende": legende, "points": pts, "derniere": pts[-1],
                       "variation_semaine": vs, "source": src0 or "FRED", "raison": None})
    return sortie


def seuil_texte(th: dict | None) -> dict:
    th = th or {}
    if not th:
        return {"texte": "n/d : thermomètre absent", "distance": None}
    u = th.get("unite") or ""
    unite = f" {u}" if u and u not in ("nombre", "alignés", "niveau") else ""
    if th.get("etat") == "franchi":
        dist = "seuil franchi"
    elif th.get("distance") is not None:
        cote = th.get("cote")
        seuil = th.get("seuil_haut") if cote == "haut" else th.get("seuil_bas")
        dist = f"à {fr(abs(th['distance']), 2 if abs(th['distance']) < 10 else 0)}{unite} du seuil {cote or ''} ({fr(seuil, 2 if seuil is not None and abs(seuil) < 10 else 0)}{unite}), soit {fr(th.get('distance_pct'), 0)} % du couloir neutre"
    else:
        dist = "distance au seuil n/d"
    return {"libelle": th.get("libelle"), "valeur": th.get("texte_valeur"), "date": th.get("date"), "etat": th.get("etat"),
            "note": th.get("note"), "distance": th.get("distance_pct"), "distance_texte": dist,
            "texte": f"{th.get('libelle')} : {th.get('texte_valeur') or 'n/d'} au {ddm(th.get('date'))}, {dist}. {th.get('note') or ''}".strip()}


def _premier_avec_consensus(rdv: list[dict], devises: tuple | None = None) -> dict | None:
    l = [e for e in rdv if e.get("consensus") and (not devises or e["devise"] in devises)]
    return next((e for e in l if e.get("impact") == "fort"), l[0] if l else None)


def scenario_si(n: int, ind: list[dict], graph: list[dict], rdv: list[dict], rdv_tous: list[dict] | None = None) -> str:
    """Scénario conditionnel rédigé en Python : des conditions et des effets probables, jamais un ordre."""
    def g(cle):
        return next((x for x in graph if x.get("cle") == cle and x.get("derniere")), None)
    e = _premier_avec_consensus(rdv, ("USD",)) or _premier_avec_consensus(rdv)
    if n == 2 and not e:
        e = _premier_avec_consensus([x for x in (rdv_tous or []) if x.get("impact") == "fort"], ("USD",))
    if n == 1 and g("vix"):
        v = g("vix")["derniere"]
        return (f"Si le VIX (à {fr(v[1], 2)} le {ddm(v[0])}) repasse sous 20, la peur reculerait et les devises cycliques (AUD, NZD, CAD) "
                f"seraient moins pénalisées ; s'il dépasse 35, le refuge (USD, JPY, CHF) serait encore plus recherché.")
    if n == 2 and e:
        r = g("USD_2a")
        deux = f"le 2 ans US (à {fr(r['derniere'][1], 2)} % le {ddm(r['derniere'][0])})" if r and e["devise"] == "USD" else f"les taux à 2 ans de {PAYS.get(e['devise'], e['devise'])}"
        return (f"Si {e['evenement']} ({e['devise']}, {jour_long(e['date'])}) ressort au-dessus de {frtxt(e['consensus'])}, {deux} devrait remonter "
                f"et soutenir {devise(e['devise'])} ; un chiffre en dessous ferait l'inverse.")
    if n == 3 and e:
        inv = bool(re.search(r"chômage|unemployment|claims", (e.get("evenement") or "") + " " + (e.get("evenement_en") or ""), re.I))
        return (f"Si {e['evenement']} ({e['devise']}, {jour_long(e['date'])}) ressort {'en dessous' if inv else 'au-dessus'} de {frtxt(e['consensus'])}, "
                f"les anticipations de la banque centrale se durciraient et {devise(e['devise'])} serait soutenu ; dans l'autre sens, il serait fragilisé.")
    if n == 4:
        r = g("USD_10a")
        return ((f"Si le 10 ans US (à {fr(r['derniere'][1], 2)} % le {ddm(r['derniere'][0])}) monte sans que le dollar suive, " if r else
                 "Si les taux longs montent sans que la devise suive, ")
                + "le signal deviendrait budgétaire : la prime de risque pèserait sur la devise au lieu de la soutenir.")
    if n == 5 and g("sp500"):
        s = g("sp500")
        return (f"Si le S&P 500 ({sgn((s['variation_semaine'] or {}).get('valeur'), 2, ' %')} sur la semaine) poursuit sa baisse, AUD et NZD "
                f"resteraient sous pression et le yen recherché ; un rebond net desserrerait cette contrainte.")
    if n == 6:
        b = g("brent")
        return ("Si les titres de conflit se multiplient et que le Brent "
                + (f"(à {fr(b['derniere'][1], 2)} $ le {ddm(b['derniere'][0])}) " if b else "")
                + "rebondit nettement, le refuge (USD, CHF, JPY) serait soutenu et les importateurs d'énergie pénalisés.")
    if n == 7:
        d = g("dollar_large")
        return ("Si l'indice dollar large " + (f"(à {fr(d['derniere'][1], 2)} le {ddm(d['derniere'][0])}) " if d else "")
                + "décroche alors que les positions spéculatives restent tendues, un débouclage pourrait accélérer la baisse du dollar ; "
                  "une nouvelle hausse confirmerait la tendance de fond.")
    if n == 8:
        b = g("brent")
        return ("Si le Brent " + (f"(à {fr(b['derniere'][1], 2)} $ le {ddm(b['derniere'][0])}) " if b else "")
                + "rebondit, le CAD serait soutenu et le JPY comme l'EUR pénalisés ; s'il poursuit sa baisse, l'inverse.")
    return "Aucun rendez-vous avec consensus relié à ce moteur dans les 7 prochains jours : pas de scénario conditionnel chiffré."


# ------------------------------------------------------------------ récit (lot V15 : core/redaction_documentaire.py)
INTERDITS = rd.INTERDITS
ENGRENAGE_SEUL = rd.ENGRENAGE_SEUL


def titre_citable(titre) -> bool:
    """Un titre de presse peut être cité s'il ne contient ni mot interdit ni formulation d'ordre."""
    from core import controle_texte as ct
    t = str(titre or "")
    return bool(t) and not INTERDITS.search(t) and not any(re.search(m, t.lower()) for m in ct.ORDRES)


def vocabulaire_interdit(r: dict) -> list[str]:
    """Mots interdits et formulations d'ordre dans un récit (sans le contrôle des nombres)."""
    from core import controle_texte as ct
    sortie = []
    for morceau in [str(x) for x in (r.get("paragraphes") or [])] + [str(r.get("exergue") or "")] + [str(x) for x in r.get("a_surveiller") or []]:
        m = INTERDITS.search(morceau)
        if m:
            sortie.append(m.group())
        sortie += [re.search(x, morceau.lower()).group() for x in ct.ORDRES if re.search(x, morceau.lower())]
        if ENGRENAGE_SEUL.search(morceau):
            sortie.append("engrenage N")
    return sortie


# ------------------------------------------------------------------ cache des récits (un appel par jour et par moteur)
CACHE_RECITS = Path("data") / "cache" / "documentaire_recits.json"
REMISE_A_ZERO_UTC = "08:15"


def forts_du_moteur(ch: dict) -> list[str]:
    """Faits de niveau fort : publications d'impact fort de la semaine, seuil franchi."""
    l = [p["id"] for p in ch["publications"] if p.get("impact") == "fort"]
    if ch["etat"].get("code") == "franchi":
        l.append(f"seuil:{ch['etat'].get('libelle')}")
    return sorted(l)


def doit_rediger_recit(entree: dict | None, semaine: str, maintenant: datetime, forts: list[str], remise: str = REMISE_A_ZERO_UTC) -> tuple[bool, str]:
    """Fonction pure. Une rédaction par jour et par moteur, au premier run après la remise à zéro du quota (08:15 UTC) ;
    nouvelle rédaction le même jour seulement si un fait fort nouveau est arrivé ; le samedi, une version « semaine complète »."""
    u = maintenant.astimezone(timezone.utc)
    jour, apres = u.date().isoformat(), u.strftime("%H:%M") >= remise
    if not entree or entree.get("semaine") != semaine:
        return (True, "première rédaction de la semaine") if apres else (False, f"avant la remise à zéro du quota ({remise} UTC)")
    if maintenant.astimezone(PARIS).weekday() == 5 and not entree.get("complet") and apres:
        return True, "samedi : version « semaine complète »"
    if entree.get("jour") != jour:
        return (True, "première rédaction du jour") if apres else (False, f"avant la remise à zéro du quota ({remise} UTC) : texte d'hier repris")
    nouveaux = sorted(set(forts) - set(entree.get("forts") or []))
    if nouveaux:
        return True, f"fait fort nouveau : {nouveaux[0]}"
    return False, "déjà rédigé aujourd'hui, aucun fait fort nouveau"


# ------------------------------------------------------------------ calcul complet
def calculer(racine: Path, maintenant: datetime | None = None, h5=None, config: dict | None = None) -> dict:
    racine = Path(racine)
    docs, cache = racine / "docs" / "data", racine / "data" / "cache"
    maintenant = maintenant or datetime.now(timezone.utc)
    config = config or {}
    sem = bornes_semaine(maintenant)
    dos, agenda = _lire(docs / "dossiers.json"), _lire(docs / "agenda.json")
    md = _lire(docs / "moteurs_dossiers.json")
    if not md.get("moteurs"):
        try:
            md = dm.calculer(docs, cache, None, maintenant)
        except Exception as exc:  # noqa: BLE001
            log.warning("dossiers des moteurs indisponibles : %s", exc)
            md = {"moteurs": {}}
    if h5 is None:
        try:
            from core import historique_5ans
            h5 = historique_5ans.charger(cache / "historique_5ans.json")
        except Exception as exc:  # noqa: BLE001
            log.warning("historique 5 ans indisponible : %s", exc)
    archive = _lire(cache / "publications_archive.json")
    technique = (_lire(cache / "collecte_technique.json") or {}).get("donnees") or {}
    cfg_tm = config.get("tableau_macro") or {}
    erreurs = []
    try:
        pubs = publications_semaine(archive, cfg_tm, sem["du"], sem["fin_donnees"])
    except Exception as exc:  # noqa: BLE001
        pubs, _ = [], erreurs.append(f"publications de la semaine : {exc}")
    ctx = contexte_jours(docs, sem["jours"])
    theme_jours = [{"date": j, "titre": (c.get("theme") or {}).get("titre"), "alignes": (c.get("theme") or {}).get("alignes"),
                    "direction": (c.get("theme") or {}).get("direction")} for j, c in sorted(ctx.items())]
    titres = titres_semaine(racine, sem["id"])
    thermos = {t["numero"]: t for t in ((dos.get("cockpit") or {}).get("thermometres") or [])}
    discours = []
    for j in agenda.get("jours") or []:
        for e in j.get("evenements") or []:
            if sem["du"] <= str(e.get("date_paris")) <= sem["fin_donnees"] and e.get("type") in ("Discours", "Réunion BC") and e.get("devise") in DEVISES:
                discours.append({"date": e["date_paris"], "heure": e.get("heure_paris"), "devise": e["devise"], "evenement": e.get("evenement"),
                                 "publie": e.get("publie"), "impact": e.get("impact")})
    chapitres = {}
    for n in range(1, 9):
        try:
            m = (md.get("moteurs") or {}).get(str(n)) or {}
            ch = {"numero": n, "nom": nm.nom(n), "explication": nm.explication(n), "question": nm.QUESTIONS[n], "canal": nm.CANAUX[n],
                  "comprendre": nm.COMPRENDRE[n], "etat": m.get("etat") or {"etat": "n/d", "code": "nd", "raison": "dossiers des moteurs absents"},
                  "erreurs": []}
            for cle, fn in (("indicateurs", lambda: indicateurs_moteur(dos, n, sem)), ("graphiques", lambda: graphiques_moteur(h5, n, sem, technique))):
                try:
                    ch[cle] = fn()
                except Exception as exc:  # noqa: BLE001 — section en mode dégradé
                    ch[cle], _ = [], ch["erreurs"].append(f"{cle} : {str(exc)[:160]}")
            ch["publications"] = [p for p in pubs if p["moteur"] == n]
            if n == 3:
                ch["surprises"] = solde_surprises(ch["publications"])
            ch["discours"] = [d for d in discours if n == 2]
            ch["actualite"] = [t for t in titres if n in (t.get("moteurs") or [])][:15]
            chg = changements_devises(ctx, n)
            ch["devises"] = [{**d, "changement": chg.get(d["devise"])} for d in (m.get("devises") or [])]
            rdv = [e for e in (m.get("agenda") or []) if not e.get("passe")]
            rdv_tous = [e for x in (md.get("moteurs") or {}).values() for e in (x.get("agenda") or []) if not e.get("passe")]
            ch["risques"] = {"seuil": seuil_texte(thermos.get(n)), "rendez_vous": rdv,
                             "scenario_si": scenario_si(n, ch["indicateurs"], ch["graphiques"], rdv, sorted(rdv_tous, key=lambda e: (e["date"], e.get("heure") or "")))}
            ch["recit"] = None   # lot V15 : seulement un texte d'IA (jamais de faux récit en Python)
            ch["faits"] = rd.faits_chapitre(ch, sem, theme_jours)
            ch["faits_semaine"] = rd.faits_semaine(ch["faits"])
            bouges = sorted([i for i in ch["indicateurs"] if (i["variation_semaine"] or {}).get("valeur") is not None], key=lambda i: -i["ampleur"])
            ch["plus_bouge"] = ({"libelle": bouges[0]["libelle"], "texte": bouges[0]["texte"], "variation": bouges[0]["variation_semaine"]["texte"]} if bouges else None)
            zs = [p for p in ch["publications"] if p.get("z") is not None]
            if n == 3 and zs:   # chiffres économiques : la surprise la plus nette de la semaine
                p = max(zs, key=lambda x: abs(x["z"]))
                ch["plus_bouge"] = {"libelle": f"{p['evenement']} ({p['devise']})", "texte": f"{frtxt(p['reel'])} contre {frtxt(p['consensus'])} attendu",
                                    "variation": f"{sgn(p['z'], 1)} écart habituel, {jour_court(p['date'])}"}
            chapitres[str(n)] = ch
        except Exception as exc:  # noqa: BLE001 — un chapitre qui échoue ne casse jamais les autres
            log.exception("chapitre %d du documentaire en échec", n)
            chapitres[str(n)] = {"numero": n, "nom": nm.nom(n), "erreur": f"chapitre indisponible : {str(exc)[:200]}",
                                 "comprendre": nm.COMPRENDRE[n], "etat": {"etat": "n/d", "code": "nd"}}
    try:
        final = chapitre_final(agenda, dos, sem, chapitres, docs)
    except Exception as exc:  # noqa: BLE001
        log.exception("chapitre final du documentaire en échec")
        final = {"erreur": f"chapitre indisponible : {str(exc)[:200]}"}
    theme = (dos.get("cockpit") or {}).get("entete") or {}
    d = {"version": 1, "semaine": sem["id"], "du": sem["du"], "au": sem["au"], "fin_donnees": sem["fin_donnees"], "statut": sem["statut"],
         "jours_couverts": sem["jours"], "suivante": {"du": sem["suivante_du"], "au": sem["suivante_au"]},
         "genere_le": maintenant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
         "titre_semaine": f"Semaine du {int(sem['du'][8:10])} au {int(sem['au'][8:10])} {MOIS[int(sem['au'][5:7]) - 1]} {sem['au'][:4]}",
         "theme": {"titre": theme.get("titre"), "alignes": theme.get("alignes"), "evaluables": theme.get("evaluables"),
                   "explication": nm.remplacer(theme.get("explication") or "")[0], "jour_par_jour": theme_jours},
         "bref": [{"numero": int(k), "nom": c["nom"], "importance": c["comprendre"]["importance"], "etat": (c.get("etat") or {}).get("etat"),
                   "code": (c.get("etat") or {}).get("code"), "libelle": (c.get("etat") or {}).get("libelle"), "valeur": (c.get("etat") or {}).get("valeur"),
                   "plus_bouge": c.get("plus_bouge")} for k, c in chapitres.items()],
         "chapitres": chapitres, "final": final, "erreurs": erreurs,
         "sources": {"indicateurs": "dossiers.json (tuiles des 8 moteurs)", "graphiques": "historique_5ans.json (FRED et séries uniques)",
                     "publications": "archive des publications du site (ForexFactory)", "titres": "flux RSS collectés à chaque run, classés par moteur",
                     "theme_par_jour": "archive contexte/ du site", "effets": "matrice d'impact (règles Python)"},
         "note": "Documentaire d'aide à la décision : des faits datés et sourcés, des conditions et des effets probables, jamais un ordre.",
         "glossaire": nm.GLOSSAIRE}
    try:   # lot V15 : faits pré-mâchés de la semaine en bref (chapitre 0) et du chapitre final
        d["bref_faits"] = rd.faits_bref(d)
        d["bref_faits_semaine"] = rd.faits_semaine(d["bref_faits"])
        if not final.get("erreur"):
            final["faits"] = rd.faits_final(d)
            final["faits_semaine"] = rd.faits_semaine(final["faits"])
    except Exception as exc:  # noqa: BLE001
        log.warning("faits du chapitre 0 ou final : %s", exc)
    d["bref_recit"], final["recit"] = None, None
    d["lecture_min"] = temps_lecture(d)
    return d


def temps_lecture(d: dict) -> int:
    total = mots(" ".join((d.get("bref_recit") or {}).get("paragraphes") or []))
    total += mots(" ".join(((d.get("final") or {}).get("recit") or {}).get("paragraphes") or []))
    for c in (d.get("chapitres") or {}).values():
        r = c.get("recit") or {}
        total += mots(" ".join(r.get("paragraphes") or [])) if r else mots(" ".join(c.get("faits_semaine") or []))
        cp = c.get("comprendre") or {}
        total += mots(" ".join([cp.get("une_phrase", ""), cp.get("comment", ""), cp.get("piege", "")]))
        total += sum(mots(i.get("ce_que_cest") or "") + mots(i.get("lecture_niveau") or "") for i in c.get("indicateurs") or [])
        total += mots((c.get("risques") or {}).get("scenario_si") or "")
    total += mots(((d.get("final") or {}).get("risque_principal") or {}).get("texte") or "")
    return max(1, round(total / MOTS_PAR_MINUTE))


def chapitre_final(agenda: dict, dos: dict, sem: dict, chapitres: dict, docs: Path | None = None) -> dict:
    """Ce qui peut bouger la semaine prochaine : 5 jours ouvrés, publications moyennes et fortes à l'heure de Paris, jours
    fériés, risque principal (seuil le plus proche d'être franchi + rendez-vous fort le plus proche)."""
    jours = [(date.fromisoformat(sem["suivante_du"]) + timedelta(days=i)).isoformat() for i in range(5)]
    feries = jours_feries(int(jours[0][:4]))
    feries.update({k: v for k, v in jours_feries(int(jours[-1][:4])).items() if k not in feries})
    evs = {j: [] for j in jours}
    for j in agenda.get("jours") or []:
        for e in j.get("evenements") or []:
            if e.get("date_paris") in evs and e.get("impact") in ("moyen", "fort") and e.get("devise") in DEVISES:
                evs[e["date_paris"]].append({"heure": e.get("heure_paris"), "devise": e["devise"], "evenement": e.get("evenement"),
                                             "impact": e["impact"], "consensus": e.get("consensus"), "precedent": e.get("precedent"),
                                             "moteur": dm.moteur_publication(e)})
    calendrier = [{"date": j, "jour": jour_court(j), "ferie": feries.get(j), "evenements": sorted(evs[j], key=lambda x: x["heure"] or "")} for j in jours]
    couvert = (agenda.get("fin") or "") >= jours[-1]
    # risque principal : seuil le plus proche (thermomètres non franchis + seuils officiels) et rendez-vous fort le plus proche
    cands = []
    for t in (dos.get("cockpit") or {}).get("thermometres") or []:
        if t.get("etat") != "franchi" and t.get("distance_pct") is not None:
            cands.append({"pct": float(t["distance_pct"]), "texte": seuil_texte(t)["texte"], "moteur": t["numero"]})
    cours = {}
    try:
        pj = _lire(Path(docs or "docs/data") / "paires.json")
        cours = {p: (f.get("cours_jour") or {}).get("cours") for p, f in (pj.get("fiches") or {}).items()}
    except Exception:  # noqa: BLE001
        pass
    for s in seuils_mod.distances({k: v for k, v in cours.items() if v}):
        cands.append({"pct": abs(s["distance_pct"]) * 10, "texte": f"{s['paire']} à {fr(s['distance_pct'], 2)} % de {fr(s['niveau'], 0)} ({s['nature']}) : "
                                                                    f"{s['explication']}", "moteur": 2, "officiel": True, "source": s["source"]})
    seuil = min(cands, key=lambda c: c["pct"]) if cands else None
    forts = [dict(e, date=c["date"]) for c in calendrier for e in c["evenements"] if e["impact"] == "fort"]
    lies = []
    if seuil:   # de préférence un rendez-vous fort d'une devise concernée par le seuil (USD/JPY -> USD ou JPY)
        devs = set(re.findall(r"\b(USD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|CNY)\b", seuil["texte"]))
        lies = [e for e in forts if e["devise"] in devs] if devs else []
    rdv = (lies or forts or [None])[0]
    texte = ((f"{seuil['texte'].rstrip('.')}. " if seuil else "Aucun seuil n'est proche d'être franchi. ")
             + (f"Le rendez-vous fort le plus proche : {rdv['evenement']} ({rdv['devise']}), {jour_long(rdv['date'])} à {rdv['heure'] or 'heure n/d'}"
                + (f", attendu {frtxt(rdv['consensus'])}" if rdv.get("consensus") else "") + "." if rdv else "Aucun rendez-vous fort au calendrier de la semaine prochaine."))
    return {"du": jours[0], "au": jours[-1], "calendrier": calendrier, "agenda_couvre": couvert,
            "raison_agenda": None if couvert else f"agenda ForexFactory publié jusqu'au {ddm(agenda.get('fin'))} seulement",
            "risque_principal": {"seuil": seuil, "rendez_vous": rdv, "texte": texte, "redige_par": "python", "secours_python": texte}}


# ------------------------------------------------------------------ rédaction, écriture et archive
def _faits_du_chapitre(d: dict, k: str) -> dict | None:
    if k == "0":
        return {"nom": "La semaine en bref", "question": "Quelle humeur a dominé la semaine, et que dit chaque moteur ?", "faits": d.get("bref_faits") or []}
    if k == "final":
        return {"nom": "Ce qui peut bouger la semaine prochaine", "question": "Quels rendez-vous et quels risques la semaine prochaine ?",
                "faits": (d.get("final") or {}).get("faits") or []}
    ch = (d.get("chapitres") or {}).get(k) or {}
    if ch.get("erreur") or not ch.get("faits"):
        return None
    return {"nom": ch["nom"], "question": ch.get("question"), "faits": ch["faits"]}


def _forts(d: dict, k: str) -> list[str]:
    ch = (d.get("chapitres") or {}).get(k)
    return forts_du_moteur(ch) if ch and not ch.get("erreur") else []


def _poser(d: dict, k: str, recit: dict | None) -> None:
    if k == "0":
        d["bref_recit"] = recit
    elif k == "final":
        d.setdefault("final", {})["recit"] = recit
    else:
        d["chapitres"][k]["recit"] = recit


def rediger(d: dict, racine: Path, maintenant: datetime, llm=None, secours=None, fabrique=None) -> dict:
    """Lot V15. Deux groupes (chapitres 0 à 4 ; 5 à 8 et final), rédigés une fois par jour après 08:15 UTC (nouvelle
    tentative si un fait fort nouveau arrive ; version « semaine complète » le samedi) : Gemini (gemini-3.5-flash puis
    gemini-3.5-flash-lite, un appel par groupe + un appel de correction), puis Groq chapitre par chapitre. Sinon : le dernier
    récit d'IA de la semaine (repris, daté), ou l'encadré « Les faits de la semaine ».
    -> bilan {modele, groq, repris, faits, journal} et ligne « Documentaire : N par le modèle, M par Groq, K récits repris,
    L encadrés de faits »."""
    chemin = Path(racine) / CACHE_RECITS
    cache = _lire(chemin) or {}
    if "ia" not in cache:   # ancien format (lot V13) : récits par moteur -> derniers récits d'IA de la semaine
        cache = {"ia": {k: {**v, "a_surveiller": v.get("a_surveiller") or []} for k, v in cache.items()
                        if isinstance(v, dict) and v.get("paragraphes") and v.get("redige_par") and v.get("redige_par") != "python"},
                 "groupes": {}}
    sem = d["semaine"]
    u = maintenant.astimezone(timezone.utc)
    journal = {}
    gemini, groq, cree = llm, secours, False
    for g, ids in rd.GROUPES.items():
        entree = (cache.get("groupes") or {}).get(g)
        forts = sorted(x for k in ids for x in _forts(d, k))
        faire, motif = doit_rediger_recit(entree, sem, maintenant, forts)
        if not faire:
            journal[g] = {"motif": motif}
            continue
        if gemini is None and groq is None and fabrique is not None and not cree:
            try:
                gemini, groq = fabrique()
            except Exception as exc:  # noqa: BLE001
                log.warning("documentaire : modèles non initialisés (%s)", exc)
            cree = True
        faits = {k: f for k in ids if (f := _faits_du_chapitre(d, k))}
        if not faits or (gemini is None and groq is None):
            journal[g] = {"motif": motif, "erreur": "aucun modèle disponible"}
            continue
        acceptes, j = rd.rediger_groupe(faits, d.get("jours_couverts") or [], gemini, groq, etiquette=f"documentaire:{g}")
        journal[g] = {"motif": motif, **j}
        for k, r in acceptes.items():
            cache.setdefault("ia", {})[k] = {**r, "semaine": sem, "redige_le": u.strftime("%Y-%m-%dT%H:%M+00:00")}
        meme = bool(entree and entree.get("semaine") == sem)
        cache.setdefault("groupes", {})[g] = {"semaine": sem, "jour": u.date().isoformat(), "forts": forts,
                                              "complet": (meme and entree.get("complet", False)) or maintenant.astimezone(PARIS).weekday() >= 5}
    try:   # le quota réservé au documentaire est rendu aux autres tâches une fois les tentatives du jour faites
        reg = getattr(gemini, "registre", None)
        if reg is not None and all((cache.get("groupes") or {}).get(g, {}).get("jour") == u.date().isoformat() for g in rd.GROUPES):
            reg.marquer_fait("documentaire")
    except Exception:  # noqa: BLE001
        pass
    bilan = {"modele": [], "groq": [], "repris": [], "faits": [], "journal": journal}
    for k in [x for ids in rd.GROUPES.values() for x in ids]:
        if k not in ("0", "final") and ((d["chapitres"].get(k) or {}).get("erreur")):
            bilan["faits"].append(k)
            continue
        ia = (cache.get("ia") or {}).get(k)
        if ia and ia.get("semaine") == sem and ia.get("paragraphes") and not vocabulaire_interdit(ia):
            repris = str(ia.get("redige_le") or "")[:10] != u.date().isoformat()
            r = {"paragraphes": ia["paragraphes"], "exergue": ia.get("exergue") or "", "a_surveiller": ia.get("a_surveiller") or [],
                 "redige_par": ia.get("redige_par"), "redige_le": ia.get("redige_le"), "mots": rd.mots(" ".join(ia["paragraphes"])),
                 "repris": repris}
            if repris:
                r["mention"] = f"Récit écrit le {ddm(ia.get('redige_le'))}, mis à jour au prochain passage du modèle."
            _poser(d, k, r)
            (bilan["repris"] if repris else bilan["groq"] if "groq" in str(ia.get("redige_par")).lower() else bilan["modele"]).append(k)
        else:
            _poser(d, k, None)
            bilan["faits"].append(k)
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        log.warning("cache des récits non écrit : %s", exc)
    d["redaction"] = {**bilan, "ligne": f"Documentaire : {len(bilan['modele'])} par le modèle, {len(bilan['groq'])} par Groq, "
                                        f"{len(bilan['repris'])} récits repris, {len(bilan['faits'])} encadrés de faits"}
    d["lecture_min"] = temps_lecture(d)
    return d


def ecrire(racine: Path, config: dict | None = None, maintenant: datetime | None = None, llm=None, secours=None, fabrique=None,
           articles: list[dict] | None = None, h5=None) -> dict | None:
    """Calcule, rédige (si dû), écrit docs/data/documentaire/AAAA-Sxx.json, l'alias docs/data/documentaire.json et l'index des
    12 dernières semaines. Ne lève jamais."""
    racine = Path(racine)
    maintenant = maintenant or datetime.now(timezone.utc)
    try:
        if articles:
            accumuler_titres(racine, articles, maintenant)
        d = calculer(racine, maintenant, h5, config)
        d = rediger(d, racine, maintenant, llm, secours, fabrique)
        dossier = racine / "docs" / "data" / "documentaire"
        dossier.mkdir(parents=True, exist_ok=True)
        brut = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
        (dossier / f"{d['semaine']}.json").write_text(brut, encoding="utf-8")
        (racine / "docs" / "data" / "documentaire.json").write_text(brut, encoding="utf-8")
        fichiers = sorted(dossier.glob("????-S??.json"))
        for f in fichiers[:-SEMAINES_ARCHIVE]:
            f.unlink()
        index = []
        for f in sorted(dossier.glob("????-S??.json"), reverse=True):
            x = _lire(f)
            index.append({"id": f.stem, "du": x.get("du"), "au": x.get("au"), "titre": x.get("titre_semaine"), "statut": x.get("statut")})
        (dossier / "index.json").write_text(json.dumps({"semaines": index, "note": f"{SEMAINES_ARCHIVE} dernières semaines"}, ensure_ascii=False), encoding="utf-8")
        log.info("Documentaire %s : %s ; lecture %d min", d["semaine"], d["redaction"]["ligne"], d["lecture_min"])
        return d
    except Exception as exc:  # noqa: BLE001
        log.exception("documentaire non écrit : %s", exc)
        return None


def empreinte(d: dict) -> str:
    return hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:10]
