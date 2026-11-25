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
DEFINITIONS = [
    (r"^Score ", "Score de force de la devise (0 à 100) calculé chaque jour sur les 8 moteurs : au-dessus de 60 la devise est recherchée, sous 40 elle est délaissée."),
    (r"^Écart meilleur", "Distance entre la devise la plus forte et la plus faible : un marché tranché offre des paires aux tendances nettes."),
    (r"[Mm]oteurs alignés", "Nombre de moteurs qui pointent dans la même direction que le thème : à 3 ou plus, le thème est établi."),
    (r"Surprise globale", "Moyenne des surprises des 9 devises : sous 0, le monde publie des chiffres plus faibles que prévu."),
    (r"Régime actuel", "Durée du régime de risque en cours : plus il dure, plus il influence les positions de fond."),
    (r"^VIX", "Volatilité attendue sur le S&P 500 pour 30 jours, l'indice de la peur : sous 15 calme, au-dessus de 25 stress, au-dessus de 35 panique."),
    (r"Taux effectif Fed", "Taux auquel les banques se prêtent au jour le jour aux États-Unis, piloté par la Fed : le vrai prix de l'argent en dollar."),
    (r"Rendement 2 ans US", "Le taux de l'État américain à 2 ans résume ce que le marché attend de la Fed sur les 2 prochaines années : le meilleur thermomètre du dollar."),
    (r"2 ans US − taux effectif", "Si le 2 ans est au-dessus du taux directeur, le marché attend des hausses ; en dessous, des baisses."),
    (r"Taux réel", "Taux directeur moins inflation sous-jacente : au-dessus de 1 %, la politique monétaire freine réellement l'économie."),
    (r"Courbe 2-10", "Écart entre le 10 ans et le 2 ans : négatif (courbe inversée), le marché craint une récession."),
    (r"BCE", "Taux auquel la BCE rémunère les dépôts des banques : c'est le taux qui guide l'euro depuis 2022."),
    (r"2 ans allemand", "Ce que le marché attend de la BCE : l'écart avec le 2 ans américain guide EUR/USD."),
    (r"BoE", "Taux directeur de la Banque d'Angleterre, qui guide la livre."),
    (r"BoJ", "Taux au jour le jour au Japon : encore très bas, c'est ce qui finance le portage vendeur de yen."),
    (r"2 ans japonais", "Ce que le marché attend de la BoJ : sa hausse réduit l'écart avec les États-Unis et soutient le yen."),
    (r"RBA", "Taux directeur de la Banque de réserve d'Australie, qui guide l'AUD."),
    (r"^Surprise [A-Z]{3}", "Somme, sur 30 jours, des écarts entre chiffres publiés et consensus, en écarts habituels : au-dessus de 0, l'économie surprend en bien et soutient la devise."),
    (r"Inflation core US", "Inflation hors énergie et alimentation : c'est elle que la Fed regarde pour décider de ses taux."),
    (r"^Chômage", "Taux de chômage : sa hausse annonce une banque centrale moins restrictive."),
    (r"au-dessus du consensus", "Part des publications meilleures que prévu sur 30 jours, toutes devises confondues."),
    (r"Dette fédérale", "Poids de la dette fédérale américaine : un niveau élevé rend le pays sensible à toute hausse des taux longs."),
    (r"Solde fédéral", "Déficit public annuel : un déficit large doit être financé par de nouvelles émissions de dette."),
    (r"Prime de terme", "Supplément exigé pour prêter à 10 ans plutôt que de renouveler des prêts courts : il monte quand les investisseurs doutent des finances publiques."),
    (r"^10 ans", "Taux de l'État à 10 ans : il mélange attentes de croissance, d'inflation et prime de risque budgétaire."),
    (r"Italie − Allemagne", "Écart de taux à 10 ans entre l'Italie et l'Allemagne : son élargissement signale un risque de fragmentation de la zone euro."),
    (r"Indice dollar large", "Valeur du dollar contre un large panier de devises (Fed) : la tendance de fond du billet vert."),
    (r"S&P 500", "Principal indice d'actions américaines : sa baisse pèse sur les devises liées à la croissance (AUD, NZD, CAD)."),
    (r"Rendement 10 ans US", "Le taux de référence mondial : sa hausse renchérit le crédit partout et attire les capitaux vers le dollar."),
    (r"or \(proxy\)|Indice or", "Indice de l'or (proxy gratuit) : refuge contre les crises et l'inflation, il recule quand les taux réels montent."),
    (r"Brent − WTI", "Écart entre pétrole mondial et américain : il reflète les tensions d'offre hors des États-Unis."),
    (r"Brent", "Prix du pétrole de référence mondiale : sa hausse soutient le CAD et pèse sur le JPY et l'EUR."),
    (r"WTI", "Prix du pétrole américain : il guide la balance énergétique du Canada."),
    (r"Corrélation AUD", "Lien entre l'AUD et les actions sur 60 séances : positif, l'AUD suit l'appétit pour le risque."),
    (r"Corrélation JPY", "Lien entre la force du yen et le VIX : positif, le yen joue son rôle de refuge."),
    (r"^Titres", "Nombre de titres du jour classés dans cette famille de risques géopolitiques."),
    (r"^Réaction", "Mouvement de l'actif sur la dernière séance disponible : il dit si le marché réagit vraiment aux titres."),
    (r"RSI", "Indicateur de vitesse du prix sur 14 séances : au-dessus de 70 surachat, sous 30 survente."),
    (r"MM200", "Écart à la moyenne des 200 dernières séances : au-dessus, la tendance de fond est haussière."),
    (r"volatilité réalisée", "Amplitude réelle des mouvements sur 20 jours : très basse, elle précède souvent un réveil brutal."),
    (r"surachat|survente", "Nombre de devises dont le RSI est en zone extrême : beaucoup d'extrêmes annoncent des mouvements de rappel."),
    (r"^COT", "Positions nettes des spéculateurs sur les contrats à terme (CFTC, chaque vendredi) : un extrême rend la devise fragile à une surprise contraire."),
    (r"Stocks de brut US|Stocks : écart", "Stocks de pétrole brut aux États-Unis (EIA, chaque mercredi) : sous la moyenne de 5 ans, ils soutiennent le prix."),
    (r"Production de brut", "Production américaine de pétrole : record, elle limite la hausse des prix."),
    (r"Balance commerciale", "Exportations moins importations : un excédent crée une demande naturelle pour la devise."),
]


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
                       "lecture_niveau": (f"Au {p5}e percentile de ses 5 dernières années : {lecture_niveau(p5)}." if p5 is not None else None),
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


# ------------------------------------------------------------------ récit : faits, secours Python, contrôle
INTERDITS = re.compile(r"\b(entrées?|stops?|objectifs?|short)\b|\bLONG\b|\bSHORT\b", re.I)
ENGRENAGE_SEUL = re.compile(r"\bengrenages?\s*(n°\s*)?\d\b", re.I)
MOTS_MIN, MOTS_MAX = 450, 1150   # consigne 600 à 900 mots, tolérance du contrôle


def titre_citable(titre) -> bool:
    """Un titre de presse peut être cité dans un récit s'il ne contient ni mot interdit ni formulation d'ordre."""
    from core import controle_texte as ct
    t = str(titre or "")
    return bool(t) and not INTERDITS.search(t) and not any(re.search(m, t.lower()) for m in ct.ORDRES)


def faits_recit(ch: dict, sem: dict, theme_jours: list[dict]) -> dict:
    return {"moteur": ch["nom"], "question": ch["question"], "semaine": {"du": sem["du"], "au": sem["au"], "jours_couverts": sem["jours"], "statut": sem["statut"]},
            "etat": {k: ch["etat"].get(k) for k in ("libelle", "valeur", "date", "etat", "direction", "note")},
            "theme_jour_par_jour": theme_jours if ch["numero"] == 1 else None,
            "indicateurs": [{"libelle": i["libelle"], "valeur": i["texte"], "date": i["date"], "semaine": (i["variation_semaine"] or {}).get("texte"),
                             "quatre_semaines": i["variation_4s"], "niveau": i["lecture_niveau"]} for i in ch["indicateurs"][:10]],
            "graphiques": [{"serie": g["titre"], "derniere": g.get("derniere"), "semaine": (g.get("variation_semaine") or {}).get("texte")}
                           for g in ch["graphiques"] if g.get("derniere")],
            "publications": [{k: p.get(k) for k in ("date", "heure", "devise", "evenement", "reel", "consensus", "precedent", "pastille", "z")}
                             for p in ch["publications"][:20]],
            "surprises_par_devise": (ch.get("surprises") or {}).get("barres"),
            "titres": [{"date": t.get("date"), "titre": t["titre"], "source": t.get("source")} for t in ch["actualite"] if titre_citable(t.get("titre"))][:8],
            "decisions_et_discours": [{k: e.get(k) for k in ("date", "heure", "devise", "evenement")} for e in ch.get("discours", [])],
            "seuil": ch["risques"]["seuil"].get("texte"),
            "effets_devises": [{"devise": d["devise"], "effet": d["effet"], "pourquoi": str(d.get("pourquoi") or "")[:200],
                                "depuis_lundi": (d.get("changement") or {}).get("texte")} for d in ch["devises"] if d["effet"] in ("soutien", "pression")],
            "a_venir": [{k: e.get(k) for k in ("date", "heure", "devise", "evenement", "consensus")} for e in ch["risques"]["rendez_vous"][:5]],
            "scenario_si": ch["risques"]["scenario_si"]}


def recit_python(ch: dict, sem: dict, theme_jours: list[dict]) -> dict:
    """Secours Python : un vrai texte en phrases complètes, un paragraphe par fait marquant (gabarits), au moins 250 mots."""
    n, nom, e = ch["numero"], ch["nom"], ch["etat"]
    c = nm.COMPRENDRE.get(n, {})
    periode = f"du {jour_long(sem['du'])} au {jour_long(sem['jours'][-1] if sem['jours'] else sem['au'])}"
    P = []
    ouverture = (f"Sur la période {periode}, le moteur « {nom} » se lit d'abord dans son thermomètre : « {e.get('libelle') or 'n/d'} » "
                 f"est à {e.get('valeur') or 'n/d'} au {ddm(e.get('date'))}, soit {e.get('etat') or 'un état n/d'}"
                 + (f", avec une direction « {e['direction']} »" if e.get("direction") else "") + ".")
    if n == 1 and len(theme_jours) > 1:
        etapes = [f"{jour_long(t['date'])} « {t['titre']} » ({t['alignes']} moteurs alignés)" for t in theme_jours]
        ouverture += " Le récit du marché a évolué au fil des séances : " + ", puis ".join(etapes) + "."
    elif n == 1 and theme_jours:
        ouverture += f" Le thème du jour est « {theme_jours[-1]['titre']} »."
    if e.get("note"):
        ouverture += f" Pour situer ce chiffre : {e['note'].rstrip('.')}."
    P.append(ouverture)
    bouges = sorted([i for i in ch["indicateurs"] if (i["variation_semaine"] or {}).get("valeur") is not None], key=lambda i: -i["ampleur"])[:5]
    P.extend(paragraphes_indicateurs(bouges))
    for g in ch["graphiques"]:
        if g.get("derniere") and (g.get("variation_semaine") or {}).get("valeur") is not None and len(P) < 4:
            P.append(f"Sur six mois, la série « {g['titre']} » se termine à {fr(g['derniere'][1], g['decimales'])}{unite_graphique(g['titre'])} le {ddm(g['derniere'][0])}, "
                     f"soit {g['variation_semaine'].get('court') or g['variation_semaine']['texte']}. {g['legende']} : c'est l'une des deux courbes qui résument ce moteur.")
            break
    pubs = [p for p in ch["publications"] if p.get("consensus")]
    if pubs:
        npub = len(ch["publications"])
        groupes = {}
        for p in pubs:
            groupes.setdefault((p["date"], p["devise"]), []).append(p)
        etapes = []
        for (j, dev), l in sorted(groupes.items())[:7]:
            details = ", ".join(f"{x['evenement']} à {frtxt(x['reel'])} pour {frtxt(x['consensus'])} attendu ({x['pastille']})" for x in l[:3])
            etapes.append(f"{jour_long(j)}, {PAYS.get(dev, dev)} {'publient' if dev == 'USD' else 'publie'} {details}")
        P.append(f"La semaine a compté {npub} publication{'s' if npub > 1 else ''} reliée{'s' if npub > 1 else ''} à ce moteur. "
                 + ". ".join(e[0].upper() + e[1:] for e in etapes) + ".")
        nettes = sorted([p for p in pubs if p.get("z") is not None and p["pastille"] != "conforme"], key=lambda x: -abs(x["z"]))[:3]
        if nettes:
            phr = []
            for x in nettes:
                bon = x.get("favorable")
                pl = "s" if abs(x["z"]) >= 2 else ""
                phr.append(f"{x['evenement']} ({x['devise']}, {ddm(x['date'])}) s'écarte de {fr(abs(x['z']), 1)} écart{pl} habituel{pl} du consensus, "
                           + ("une bonne surprise pour " if bon else "une déception pour " if bon is False else "un écart neutre pour ") + devise(x["devise"]))
            P.append("Les surprises les plus nettes de la semaine sont les suivantes : " + " ; ".join(phr) + ".")
        barres = (ch.get("surprises") or {}).get("barres") or []
        if len(barres) > 1:
            haut, bas = barres[0], barres[-1]
            P.append(f"En solde, {devise(haut['devise'])} a la semaine la plus favorable ({sgn(haut['solde'], 1)} sur {haut['n']} publication{'s' if haut['n'] > 1 else ''}) "
                     f"et {devise(bas['devise'])} la plus décevante ({sgn(bas['solde'], 1)} sur {bas['n']}) : des chiffres au-dessus des attentes poussent une banque "
                     "centrale à rester restrictive, des déceptions l'incitent à la patience.")
    elif ch["publications"]:
        P.append(f"{len(ch['publications'])} publication{'s' if len(ch['publications']) > 1 else ''} de la semaine "
                 f"{'sont reliées' if len(ch['publications']) > 1 else 'est reliée'} à ce moteur, sans consensus publié pour en mesurer la surprise.")
    # titres cités dans le récit : jamais un titre qui contient un mot interdit (« stop », « short »…) ou un ordre
    t = [x for x in ch["actualite"] if titre_citable(x.get("titre"))][:8]
    if ch["actualite"] and t:
        P.append(paragraphe_actualite(ch["actualite"], t, n))
    sout = [d for d in ch["devises"] if d["effet"] == "soutien"]
    pres = [d for d in ch["devises"] if d["effet"] == "pression"]
    if sout or pres:
        p = "Sur les devises, ce moteur " + " et ".join(x for x in [
            ("soutient " + ", ".join(d["devise"] for d in sout)) if sout else "",
            ("pèse sur " + ", ".join(d["devise"] for d in pres)) if pres else ""] if x) + f" au {ddm(sem['fin_donnees'])}."
        exemple = (sout or pres)[0]
        p += f" Pour {devise(exemple['devise'])}, la règle appliquée est la suivante : {str(exemple.get('pourquoi') or '').split(' ; ')[0]}."
        chg = [d["changement"]["texte"] for d in ch["devises"] if (d.get("changement") or {}).get("change")]
        if chg:
            p += " Ce qui a changé depuis le début de la semaine : " + " ; ".join(chg[:4]) + "."
        P.append(p)
    else:
        P.append(f"Au {ddm(sem['fin_donnees'])}, ce moteur ne pousse aucune devise au-delà des seuils de la matrice : son effet reste en réserve.")
    rdv = ch["risques"]["rendez_vous"]
    cle = next((e for e in rdv if e.get("impact") == "fort"), rdv[0] if rdv else None)
    suite = "Pour la suite, " + (f"{len(rdv)} rendez-vous lié{'s' if len(rdv) > 1 else ''} {'sont' if len(rdv) > 1 else 'est'} au calendrier des 7 prochains jours ; le plus important : "
                                 f"{cle['evenement']} ({cle['devise']}, {jour_long(cle['date'])}{' à ' + cle['heure'] if cle.get('heure') else ''}). " if rdv else "aucun rendez-vous relié n'est au calendrier des 7 prochains jours. ")
    suite += ch["risques"]["scenario_si"]
    P.append(suite)
    P.append(f"Pour rappel, ce moteur agit ainsi : {nm.canal(n)} Le piège à éviter : {c.get('piege', '').rstrip('.')}.")
    texte = " ".join(P)
    if mots(texte) < 250:
        P.insert(1, f"Pourquoi ce moteur compte : {c.get('pourquoi', '')} Ses indicateurs principaux sont "
                    + ", ".join(x.split(' : ')[0] for x in c.get("indicateurs", [])) + ".")
    exergue = _exergue_python(ch)
    return {"paragraphes": P, "exergue": exergue, "redige_par": "python", "mots": mots(" ".join(P))}


LIAISONS = ["Dans le même temps,", "En parallèle,", "À côté de cela,"]


def _phrase_indicateur(i: dict) -> str:
    v = i["variation_semaine"]
    lecture = i.get("lecture_niveau")
    base = f"« {i['libelle']} » termine à {i['texte']} ({v.get('court') or v['texte']})"
    if lecture:
        base += f", {lecture[0].lower() + lecture[1:].rstrip('.')}"
    return base


def paragraphes_indicateurs(bouges: list[dict]) -> list[str]:
    """Lot V14 (V13.1) : les indicateurs qui ont le plus bougé, 2 ou 3 par paragraphe, reliés par une phrase de liaison
    (avant : une suite de phrases « « X » termine à… » sans lien)."""
    if not bouges:
        return []
    groupes = [bouges[:3], bouges[3:5]] if len(bouges) > 3 else [bouges]
    sortie = []
    for k, g in enumerate(groupes):
        if not g:
            continue
        tete = "Du côté des indicateurs, " if k == 0 else "Deux autres mesures complètent le tableau : "
        corps = _phrase_indicateur(g[0]) + "."
        for j, i in enumerate(g[1:]):
            corps += f" {LIAISONS[j % len(LIAISONS)]} {_phrase_indicateur(i)}."
        fin = (" Ces mouvements donnent la tonalité de la semaine pour ce moteur, au-delà du seul chiffre du jour." if k == 0
               else " Pris ensemble, ils confirment ou nuancent la lecture du thermomètre.")
        sortie.append(tete + corps + fin)
    return sortie


# Sujet en français d'un titre de presse (mot-clé reconnu), pour ne jamais citer un titre anglais tel quel
SUJETS = [(r"tariff|droits de douane", "les droits de douane"), (r"trade (deal|agreement|talks)|accord commercial", "les accords commerciaux"),
          (r"\boil\b|crude|brent|\bwti\b|petrole|opec|opep", "le pétrole"), (r"natural gas|\blng\b|\bgaz\b", "le gaz"),
          (r"export|import", "le commerce extérieur"), (r"sanction", "les sanctions"), (r"\bwar\b|guerre|missile|attack|strike|military", "les tensions militaires"),
          (r"ceasefire|cessez", "un cessez-le-feu"), (r"election|\bvote\b", "une élection"), (r"summit|sommet", "un sommet international"),
          (r"\bfed\b|fomc|powell|warsh|waller", "la Réserve fédérale"), (r"\becb\b|\bbce\b|lagarde", "la BCE"), (r"\bboe\b|bailey", "la Banque d'Angleterre"),
          (r"\bboj\b|ueda", "la Banque du Japon"), (r"\brba\b", "la Banque de réserve d'Australie"), (r"\bboc\b|macklem", "la Banque du Canada"),
          (r"rate (cut|hike)|interest rate", "les taux d'intérêt"), (r"\bcpi\b|inflation", "l'inflation"), (r"payroll|jobs|unemployment|jobless|chomage", "l'emploi"),
          (r"\bgdp\b|\bpib\b|economy (contracts|shrinks|grows)", "la croissance"), (r"\bpmi\b|manufacturing", "l'activité industrielle"),
          (r"retail sales|ventes au detail", "la consommation"), (r"house prices|housing", "l'immobilier"),
          (r"budget|deficit|\bdebt\b|dette|borrowing|fiscal|\bgilts?\b", "les finances publiques"), (r"auction|adjudication", "une adjudication de dette"),
          (r"wrap|risk sentiment|risk (on|off)|sell-?off|markets? (rebound|fall|tumble)", "l'humeur générale des marchés"),
          (r"\bstocks?\b|equities|nasdaq|s&p|wall street|\bdow\b", "les marchés d'actions"), (r"\bgold\b", "l'or"), (r"\bvix\b|volatility", "la volatilité"),
          (r"bitcoin|crypto", "les cryptomonnaies"), (r"\bchina\b|\bchine\b", "la Chine"), (r"\bjapan\b", "le Japon")]


def sujet_titre(titre: str) -> str | None:
    t = dm._sans_accent(titre)
    return next((lib for m, lib in SUJETS if re.search(m, t)), None)


def paragraphe_actualite(tous: list[dict], citables: list[dict], n: int) -> str:
    """Lot V14 (V13.1) : l'actualité racontée par ses sujets (en français), avec la source et la date ; les titres
    anglais ne sont plus recopiés tels quels."""
    vus, morceaux = set(), []
    for x in citables:
        suj = sujet_titre(x.get("titre") or "")
        if not suj or suj in vus:
            continue
        vus.add(suj)
        morceaux.append(f"{suj} ({x.get('source') or 'source n/d'}, {ddm(x.get('date'))})")
        if len(morceaux) == 3:
            break
    nb = len(tous)
    verbe = dm.POURQUOI_TITRE[n].split(' : ')[0]
    for a, b in (("touche", "touchent"), ("porte", "portent"), ("concerne", "concernent"), ("change", "changent"), ("signale", "signalent")):
        verbe = verbe.replace(a, b)
    tete = f"Dans l'actualité, {nb} titre{'s' if nb > 1 else ''} de la semaine {'relèvent' if nb > 1 else 'relève'} de ce moteur"
    if morceaux:
        tete += (", et les plus récents portent sur " + (", ".join(morceaux[:-1]) + " et " + morceaux[-1] if len(morceaux) > 1 else morceaux[0]))
    return tete + f". Ils comptent parce qu'ils {verbe} ; la liste complète, avec les liens vers les articles, suit ce récit."


def _exergue_python(ch: dict) -> str:
    pubs = [p for p in ch["publications"] if p.get("z") is not None and p.get("consensus")]
    if pubs:
        p = max(pubs, key=lambda x: abs(x["z"]))
        return f"{p['evenement']} ({p['devise']}) : {frtxt(p['reel'])} contre {frtxt(p['consensus'])} attendu, la surprise la plus nette de la semaine pour ce moteur."
    e = ch["etat"]
    return f"« {e.get('libelle') or ch['nom']} » à {e.get('valeur') or 'n/d'} au {ddm(e.get('date'))} : {e.get('etat') or 'état n/d'}."


def controler_recit(r: dict, faits: dict, nom: str) -> list[str]:
    """Raisons de rejet du récit du modèle (vide : accepté) : nombres absents des faits, vocabulaire interdit, « engrenage N »
    seul, longueur hors consigne, moteur non cité, exergue absente."""
    from core import controle_texte as ct
    raisons = []
    paras = [str(p) for p in (r.get("paragraphes") or []) if str(p).strip()]
    texte = " ".join(paras)
    ex = str(r.get("exergue") or "").strip()
    if not paras:
        return ["texte vide"]
    if not ex:
        raisons.append("exergue absente")
    n_mots = mots(texte)
    if not (MOTS_MIN <= n_mots <= MOTS_MAX):
        raisons.append(f"longueur hors consigne : {n_mots} mots (600 à 900 attendus)")
    if not (3 <= len(paras) <= 6):
        raisons.append(f"{len(paras)} paragraphes (3 à 5 attendus)")
    ok = ct.nombres_autorises(faits)
    for morceau in paras + [ex]:
        for t, v, d in ct.nombres_texte(morceau):
            if not ct.autorise(v, d, ok):
                raisons.append(f"nombre absent des faits « {t} »")
        m = INTERDITS.search(morceau)
        if m:
            raisons.append(f"vocabulaire interdit « {m.group()} »")
        for motif in ct.ORDRES:
            if re.search(motif, morceau.lower()):
                raisons.append(f"ordre de trading « {re.search(motif, morceau.lower()).group()} »")
        if ENGRENAGE_SEUL.search(morceau):
            raisons.append("« engrenage N » sans le nom du moteur")
    if nom.lower() not in texte.lower():
        raisons.append(f"le moteur n'est pas cité par son nom ({nom})")
    return raisons[:8]


def vocabulaire_interdit(r: dict) -> list[str]:
    """Mots interdits et formulations d'ordre dans un récit (sans le contrôle des nombres)."""
    from core import controle_texte as ct
    sortie = []
    for morceau in [str(p) for p in (r.get("paragraphes") or [])] + [str(r.get("exergue") or "")]:
        m = INTERDITS.search(morceau)
        if m:
            sortie.append(m.group())
        sortie += [re.search(x, morceau.lower()).group() for x in ct.ORDRES if re.search(x, morceau.lower())]
        if ENGRENAGE_SEUL.search(morceau):
            sortie.append("engrenage N")
    return sortie


def prompt_recit(faits: dict, nom: str) -> str:
    return ("Tu écris en français le chapitre « Le récit de la semaine » d'un documentaire hebdomadaire sur le marché des changes, "
            f"consacré au moteur « {nom} », à partir des FAITS ci-dessous (calculés en Python). Ton de journaliste économique : "
            "phrases complètes, la cause puis la conséquence, dans l'ordre chronologique quand c'est possible (« lundi… mercredi… "
            "vendredi… »). 600 à 900 mots en 3 à 5 paragraphes, plus une phrase forte mise en exergue. Règles impératives (un texte "
            "qui les enfreint est remplacé par le texte de secours) : AUCUN nombre absent des faits ; dates en JJ/MM ; chiffres avec "
            "leur unité ; cite le moteur par son nom, jamais « engrenage » suivi d'un numéro ; aide à la décision seulement, jamais "
            "« entrée », « stop », « objectif », « LONG » ni « SHORT », aucun ordre d'achat ou de vente, des conditions et des effets "
            "probables seulement. " + nm.CONSIGNE_MODELE + "\nRéponds STRICTEMENT en JSON : {\"paragraphes\": [\"…\", \"…\", \"…\"], "
            "\"exergue\": \"…\"}.\nFAITS :\n" + json.dumps(faits, ensure_ascii=False))


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


def rediger_recit(faits: dict, nom: str, llm=None, secours=None, etiquette: str = "documentaire") -> tuple[dict | None, dict]:
    """Modèle principal, puis Groq si le principal échoue (quota épuisé, 429, 503…). -> (récit accepté ou None, journal)."""
    from core.llm import definir_etiquette, libelle_modele, dernier_modele, extraire_json
    p = prompt_recit(faits, nom)
    essais, journal = [], {"tentatives": []}
    if llm is not None:
        essais.append(("modele", llm))
    if secours is not None and getattr(secours, "disponible", lambda: False)():
        essais.append(("groq", secours))
    for qui, f in essais:
        try:
            if qui == "modele":
                definir_etiquette(etiquette)
                brut, par = f.appeler_llm(p), libelle_modele(dernier_modele()) or "modèle principal"
            else:
                brut, par = f.appeler(p), f"secours {f.nom}"
            d = extraire_json(brut)
            r = {"paragraphes": [str(x).strip() for x in (d or {}).get("paragraphes") or [] if str(x).strip()], "exergue": str((d or {}).get("exergue") or "").strip()}
            rejets = controler_recit(r, faits, nom)
            journal["tentatives"].append({"par": par, "rejets": rejets})
            if not rejets:
                r.update({"redige_par": par, "mots": mots(" ".join(r["paragraphes"]))})
                return r, journal
        except Exception as exc:  # noqa: BLE001 — quota épuisé (BudgetEpuise), 429, 503 : le suivant
            journal["tentatives"].append({"par": qui, "erreur": f"{type(exc).__name__} : {str(exc)[:160]}"})
    return None, journal


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
            ch["recit"] = recit_python(ch, sem, theme_jours)
            ch["exergue_python"] = ch["recit"]["exergue"]
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
         "note": "Documentaire d'aide à la décision : des faits datés et sourcés, des conditions et des effets probables, jamais un ordre."}
    d["lecture_min"] = temps_lecture(d)
    return d


def temps_lecture(d: dict) -> int:
    total = 0
    for c in (d.get("chapitres") or {}).values():
        total += mots(" ".join((c.get("recit") or {}).get("paragraphes") or []))
        cp = c.get("comprendre") or {}
        total += mots(" ".join([cp.get("pourquoi", ""), cp.get("piege", ""), *cp.get("indicateurs", [])]))
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
def rediger(d: dict, racine: Path, maintenant: datetime, llm=None, secours=None, fabrique=None) -> dict:
    """Pour chaque moteur : texte du cache s'il est encore valable (contrôlé avec les faits du run), sinon rédaction si elle
    est due (une par jour, fait fort nouveau, samedi). -> bilan {modele, groq, python, journal}."""
    chemin = Path(racine) / CACHE_RECITS
    cache = _lire(chemin) or {}
    sem = d["semaine"]
    bilan = {"modele": [], "groq": [], "python": [], "journal": {}}
    fabrique_faite = False
    theme_jours = d["theme"]["jour_par_jour"]
    for k, ch in d["chapitres"].items():
        if ch.get("erreur"):
            bilan["python"].append(k)
            continue
        faits = faits_recit(ch, {"du": d["du"], "au": d["au"], "jours": d["jours_couverts"], "statut": d["statut"], "fin_donnees": d["fin_donnees"]}, theme_jours)
        entree = cache.get(k)
        forts = forts_du_moteur(ch)
        faire, motif = doit_rediger_recit(entree, sem, maintenant, forts)
        retenu = None
        if entree and entree.get("semaine") == sem and not faire and entree.get("paragraphes"):
            # Lot V14 (V13.1) : le texte a passé le contrôle des nombres à sa rédaction, sur les faits de ce moment-là ;
            # il n'est plus rejeté parce que les faits ont bougé depuis (avant : les récits Groq du matin retombaient en
            # Python au fil des runs). Seul le vocabulaire est revérifié ; il est daté (« rédigé le JJ/MM à HH:MM »).
            r = {"paragraphes": entree.get("paragraphes") or [], "exergue": entree.get("exergue") or ""}
            if not vocabulaire_interdit(r):
                retenu = {**r, "redige_par": entree.get("redige_par"), "mots": mots(" ".join(r["paragraphes"])),
                          "redige_le": entree.get("redige_le")}
        if faire:
            if llm is None and secours is None and fabrique is not None and not fabrique_faite:
                try:
                    llm, secours = fabrique()
                except Exception as exc:  # noqa: BLE001
                    log.warning("documentaire : modèle non initialisé (%s)", exc)
                fabrique_faite = True
            if llm is not None or secours is not None:
                r, journal = rediger_recit(faits, ch["nom"], llm, secours, etiquette=f"documentaire:c{k}")
                bilan["journal"][k] = {"motif": motif, **journal}
                u = maintenant.astimezone(timezone.utc)
                if r:
                    retenu = {**r, "redige_le": u.strftime("%Y-%m-%dT%H:%M+00:00")}
                    cache[k] = {"semaine": sem, "jour": u.date().isoformat(), "forts": forts, "paragraphes": r["paragraphes"],
                                "exergue": r["exergue"], "redige_par": r["redige_par"], "redige_le": retenu["redige_le"],
                                "complet": maintenant.astimezone(PARIS).weekday() >= 5}
                else:   # échec : on note la tentative du jour pour ne pas rappeler le modèle à chaque run
                    meme = bool(entree and entree.get("semaine") == sem)
                    cache[k] = {**(entree if meme else {"semaine": sem}), "jour": u.date().isoformat(), "forts": forts,
                                "complet": (meme and (entree or {}).get("complet", False)) or maintenant.astimezone(PARIS).weekday() >= 5,
                                "paragraphes": (entree or {}).get("paragraphes") if (entree or {}).get("semaine") == sem else None,
                                "exergue": (entree or {}).get("exergue") if (entree or {}).get("semaine") == sem else None,
                                "redige_par": (entree or {}).get("redige_par") if (entree or {}).get("semaine") == sem else None}
        if retenu and retenu.get("paragraphes"):
            ch["recit"] = {**retenu, "secours_python_mots": ch["recit"]["mots"]}
            (bilan["groq"] if "groq" in str(retenu.get("redige_par")).lower() else bilan["modele"]).append(k)
        else:
            bilan["python"].append(k)
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        log.warning("cache des récits non écrit : %s", exc)
    d["redaction"] = {**bilan, "ligne": f"Documentaire : {len(bilan['modele'])} récits par le modèle, {len(bilan['groq'])} par Groq, {len(bilan['python'])} en Python"}
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
