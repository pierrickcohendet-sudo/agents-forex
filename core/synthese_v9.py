"""Synthèse du jour V9 : les 13 sections du rapport modèle, en faits structurés calculés en Python (lot V9, partie B).

Chaque section porte ses faits (valeur, texte affiché, source, date ; « n/d » avec la raison), et un texte de secours
rédigé en Python (phrases complètes, chacune citant au moins un fait daté). Le modèle ne fait que reformuler ces textes
à partir des mêmes faits (agents/agent_synthese_v9.py, contrôle des nombres). Scores, rangs, biais, mécanismes actifs
et conditions remplies : Python seulement. Jamais de niveau d'entrée, de stop ni d'objectif : des zones de repère et des
conditions. Une section en panne ne casse pas les autres (section « indisponible » avec la raison).

Entrées : JSON déjà publiés du run (docs/data : rapport_jour, agenda, profil_devises, force_devises, accueil, paires),
caches (publications_archive, bls_emploi, collecte_historiques, historique_taux). Sortie : docs/data/synthese.json.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import publications_archive as pa

log = logging.getLogger(__name__)

DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
NOMS_DEVISES = {"USD": "dollar", "EUR": "euro", "GBP": "livre", "JPY": "yen", "CHF": "franc suisse", "CAD": "dollar canadien",
                "AUD": "dollar australien", "NZD": "dollar néo-zélandais", "CNY": "yuan"}
PAYS = {"USD": "États-Unis", "EUR": "Zone euro", "GBP": "Royaume-Uni", "JPY": "Japon", "CHF": "Suisse", "CAD": "Canada",
        "AUD": "Australie", "NZD": "Nouvelle-Zélande", "CNY": "Chine"}
BANQUES = {"USD": "Fed", "EUR": "BCE", "GBP": "BoE", "JPY": "BoJ", "CHF": "BNS", "CAD": "BoC", "AUD": "RBA", "NZD": "RBNZ", "CNY": "PBoC"}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
MENTION = "Aide à la décision : biais conditionnels et zones de repère, jamais un ordre, un niveau d'entrée, un stop ni un objectif."
NON_DISPONIBLE_L2 = "donnée prévue à la livraison 2 du lot V9 (extraction des actualités, vérifiée en Python)"
TITRES = [
    ("s1", "Synthèse exécutive", "Ce qu'il faut retenir en une minute", "Synthèse exécutive"),
    ("s2", "État des marchés internationaux", "Dernières observations, avec leur date", "État des marchés"),
    ("s3", "Focus", "Dernière séance, chaîne de causalité, prochain rendez-vous", "Focus"),
    ("s4", "Banques centrales : comparaison internationale", "Taux, dernier mouvement, prochaine réunion", "Banques centrales"),
    ("s5", "Énergie, géopolitique et inflation", "Brent et WTI, conséquences pour les devises", "Énergie"),
    ("s6", "Chine et environnement asiatique", "Prix chinois, marchés asiatiques, devises exposées", "Chine et Asie"),
    ("s7", "Calendrier de la semaine", "Publications fortes et moyennes · heures de Paris", "Calendrier"),
    ("s8", "Classement des devises", "Rang calculé en Python : profil, surprises, écart de taux, force", "Force des devises"),
    ("s9", "Paires à surveiller", "Là où les facteurs des deux devises divergent le plus", "Paires à surveiller"),
    ("s10", "Technique de la paire n° 1", "Quotidien, zones et écart de taux calculés par le pipeline", "Technique"),
    ("s11", "Scénarios de la semaine", "Conditions vérifiées en Python à chaque run", "Scénarios"),
    ("s12", "Plan : les priorités", "Peu de paires, là où macro et technique convergent", "Plan"),
    ("s13", "Conclusion", "Biais central, priorités, rendez-vous déterminant", "Conclusion"),
]
METHODE = [("Hebdomadaire · quotidien", "Régime et zones de liquidité"), ("Macro", "La devise au meilleur avantage relatif"),
           ("Obligations", "Taux 2 ans et écart entre les pays"), ("4 heures", "Structure cohérente avec le biais"),
           ("30 minutes", "Confirmation de la structure avant toute décision"),
           ("Gestion", "Risque calculé avant, rien pendant les publications")]
CONSEQUENCES_PETROLE = [("Hausse durable", "Inflation énergétique : banques centrales plus restrictives"),
                        ("Baisse durable", "Soulagement pour les importateurs d'énergie (zone euro, Japon)"),
                        ("Choc d'offre", "Risque de stagflation : croissance plus faible, inflation plus forte"),
                        ("Détente géopolitique", "Prime de risque énergétique en recul")]
SENSIBLES_PETROLE = [("CAD", "pétrole, mais aussi croissance mondiale"), ("JPY, EUR", "facture énergétique des importateurs"),
                     ("USD", "taux d'abord, géopolitique ensuite")]


# ------------------------------------------------------------------ formats
def fr(x, d: int = 2, signe: bool = False, unite: str = "") -> str:
    """1234.5 -> « 1 234,50 » ; signe=True -> « +1,26 » / « −0,40 » ; None -> « n/d »."""
    if x is None:
        return "n/d"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    t = f"{abs(x):,.{d}f}".replace(",", " ").replace(".", ",")
    s = ("+" if x > 0 else "−" if x < 0 else "") if signe else ("−" if x < 0 else "")
    return f"{s}{t}{unite}"


def ddm(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso and len(str(iso)) >= 10 else "n/d"


def jour_long(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"


def jour_court(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{JOURS[d.weekday()][:3]}. {ddm(iso)}"


def num(texte) -> float | None:
    """« 0.3% » -> 0.3 ; « 165K » -> 165 ; « <1.25% » -> 1.25 ; « -4.7K » -> -4.7."""
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(texte or "").replace("−", "-"))
    return float(m.group().replace(",", ".")) if m else None


def valeur_fr(texte) -> str:
    """« 0.3% » -> « 0,3 % » ; « 165K » -> « 165 K » ; « 9-0-0 » inchangé."""
    t = str(texte or "n/d")
    t = re.sub(r"(\d)\.(\d)", r"\1,\2", t)
    t = re.sub(r"(\d)%", r"\1 %", t)
    return re.sub(r"(\d)([KMB])$", r"\1 \2", t).replace("-", "−") if not re.match(r"^\d+-\d+", t) else t


def fait(valeur, texte: str, source: str | None, date_: str | None, raison: str | None = None, **extra) -> dict:
    return {"valeur": valeur, "texte": texte if valeur is not None else "n/d", "source": source, "date": date_,
            "raison": None if valeur is not None else (raison or "donnée absente"), **extra}


def _lire(chemin: Path) -> dict:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def jour_ouvre_precedent(j: date) -> date:
    return pa.derniere_seance_ouvree(j)


def retard_jours_ouvres(iso: str | None, aujourd: date) -> int | None:
    if not iso:
        return None
    d = date.fromisoformat(str(iso)[:10])
    n, x = 0, d
    while x < aujourd:
        x += timedelta(days=1)
        if x.weekday() < 5:
            n += 1
    return n


# ------------------------------------------------------------------ entrées
class Entrees:
    """Toutes les sources d'un jour, lues une fois (le rejeu passe un dossier de données figées)."""

    def __init__(self, docs: Path, cache: Path, aujourd: date, maintenant: datetime):
        self.docs, self.cache, self.aujourd, self.maintenant = Path(docs), Path(cache), aujourd, maintenant
        self.rj = _lire(self.docs / "rapport_jour.json")
        self.agenda = _lire(self.docs / "agenda.json")
        self.profil = _lire(self.docs / "profil_devises.json")
        self.force = _lire(self.docs / "force_devises.json")
        self.accueil = _lire(self.docs / "accueil.json")
        self.paires = _lire(self.docs / "paires.json")
        self.archive = pa.charger(self.cache / "publications_archive.json")
        self.bls = (_lire(self.cache / "bls_emploi.json") or {}).get("faits") or {}
        h = _lire(self.cache / "collecte_historiques.json")
        self.hist = ((h.get("donnees") or h).get("series") or {}) if h else {}
        self.taux = (_lire(self.cache / "historique_taux.json") or {}).get("series") or {}
        self.lignes = {l.get("actif"): l for l in ((self.rj.get("point_marche") or {}).get("lignes") or [])}
        # Lot V9, livraison 2 : actualités du jour, probabilité citée de la Fed, communiqués officiels (Python)
        racine = self.cache.parent.parent
        try:
            from core import actualites
            arts = actualites.articles(_lire(self.cache / "collecte_news.json"))
            self.actualites = actualites.du_jour(arts)
            hist = _lire(self.cache / "proba_fed.json")
            self.proba = actualites.lecture_proba(hist if isinstance(hist, list) else [], aujourd)
        except Exception as exc:  # noqa: BLE001
            log.warning("actualités V9 : %s", exc)
            self.actualites, self.proba = [], {"valeur": None, "raison": f"actualités illisibles : {exc}"}
        try:
            from core import communiques_v9
            self.communiques = communiques_v9.analyser(racine)
        except Exception as exc:  # noqa: BLE001
            log.warning("communiqués V9 : %s", exc)
            self.communiques = {}

    def serie(self, cle: str) -> list[tuple[str, float]]:
        return [(str(p[0])[:10], float(p[1])) for p in ((self.hist.get(cle) or {}).get("points") or []) if p and p[1] is not None]

    def source(self, cle: str) -> str | None:
        return (self.hist.get(cle) or {}).get("source")

    def detail_paire(self, paire: str) -> dict:
        return _lire(self.docs / "paires" / f"{paire.replace('/', '-')}.json")

    def evenements(self) -> list[dict]:
        return [e for j in self.agenda.get("jours") or [] for e in j.get("evenements") or []]


def variation(points: list[tuple[str, float]], seances: int, unite: str) -> float | None:
    if len(points) <= seances:
        return None
    a, b = points[-1 - seances][1], points[-1][1]
    if unite == "pb":
        return round((b - a) * 100, 1)
    if unite == "%":
        return round((b / a - 1) * 100, 2) if a else None
    return round(b - a, 2)


def valeur_au(points: list[tuple[str, float]], jour: str) -> tuple[str, float] | None:
    m = None
    for d, v in points:
        if d <= jour:
            m = (d, v)
        else:
            break
    return m


# ------------------------------------------------------------------ section 2 : marchés et mécanisme cross-asset
def brent_quotidien(e: Entrees) -> dict:
    """Brent : dernier prix spot officiel (EIA, repris par FRED, publié une fois par semaine) et relais quotidien par
    l'ETF BNO (contrats à terme Brent) : estimation = dernier Brent EIA × variation de BNO depuis cette date."""
    off, bno = e.serie("brent"), e.serie("brent_bno")
    if not off:
        return {"disponible": False, "raison": "Brent EIA absent de la collecte"}
    d0, v0 = off[-1]
    retard = retard_jours_ouvres(d0, e.aujourd)
    sortie = {"disponible": True, "officiel": {"valeur": v0, "date": d0, "source": e.source("brent") or "FRED (DCOILBRENTEU, prix spot EIA)"},
              "retard_jours_ouvres": retard, "serie_6m": [[d, v] for d, v in off if d >= (date.fromisoformat(d0) - timedelta(days=183)).isoformat()],
              "estimation": None, "alerte": None}
    ref = valeur_au(bno, d0)
    if bno and ref and bno[-1][0] > d0:
        ext = [[d, round(v0 * v / ref[1], 2)] for d, v in bno if d > d0]
        sortie["estimation"] = {"valeur": ext[-1][1], "date": ext[-1][0], "points": ext,
                                "methode": f"Brent EIA du {ddm(d0)} ({fr(v0)} $) × variation de l'ETF BNO depuis le {ddm(d0)}",
                                "source": e.source("brent_bno") or "Twelve Data (ETF BNO)", "statut": "estimation"}
    if retard is not None and retard > 3:
        sortie["alerte"] = (f"Brent officiel (EIA) au {ddm(d0)} : {retard} jours ouvrés de retard (publication hebdomadaire). "
                            + ("Relais quotidien : ETF BNO." if sortie["estimation"] else "Aucun relais quotidien disponible."))
    sortie["semaine_pct"] = variation(bno, 5, "%") if bno else variation(off, 5, "%")
    sortie["semaine_source"] = "ETF BNO (Twelve Data), 5 séances" if bno else "Brent EIA, 5 séances"
    sortie["semaine_date"] = (bno or off)[-1][0]
    return sortie


def _ligne(e: Entrees, actif: str, libelle: str, lecture: str | None = None) -> dict:
    l = e.lignes.get(actif)
    if not l or l.get("niveau") is None:
        return {"libelle": libelle, "valeur": None, "texte": "n/d", "raison": (l or {}).get("raison") or "absent du point de marché"}
    d = str(l.get("heure") or "")[:10]
    retard = retard_jours_ouvres(d, e.aujourd)
    attendu = jour_ouvre_precedent(e.aujourd).isoformat()
    return {"libelle": libelle, "actif": actif, "valeur": l["niveau"], "decimales": l.get("decimales", 2), "unite": l.get("unite"),
            "texte": fr(l["niveau"], l.get("decimales", 2)) + (" %" if l.get("unite") == "pb" else ""),
            "date": d, "retard": bool(d and d < attendu), "retard_jours_ouvres": retard,
            "variation_1": l.get("variation_j1"), "variation_5": l.get("variation_5j"),
            "serie_30": [p[1] for p in l.get("serie_30j") or []], "source": l.get("source"),
            "lecture": lecture or l.get("lecture"), "statut": l.get("statut")}


def section_marches(e: Entrees, brent: dict) -> dict:
    lignes = [_ligne(e, "Indice dollar (formule du DXY, non officiel)", "Indice dollar (DXY, formule)")]
    b = {"libelle": "Brent ($/baril)", "valeur": None, "texte": "n/d", "raison": brent.get("raison")}
    if brent.get("disponible"):
        est, off = brent.get("estimation"), brent["officiel"]
        src = est or off
        b = {"libelle": "Brent ($/baril)", "valeur": src["valeur"], "decimales": 2, "unite": "%", "texte": fr(src["valeur"]),
             "date": src["date"], "retard": not est and (brent.get("retard_jours_ouvres") or 0) > 1,
             "retard_jours_ouvres": 0 if est else brent.get("retard_jours_ouvres"),
             "variation_1": None, "variation_5": brent.get("semaine_pct"),
             "serie_30": [p[1] for p in (brent["serie_6m"][-22:] + ((est or {}).get("points") or []))][-30:],
             "source": (f"{est['methode']} ; {est['source']}" if est else off["source"]), "statut": "estimation" if est else "confirmé",
             "lecture": f"Officiel EIA {fr(off['valeur'])} $ au {ddm(off['date'])}" + (f", estimation ETF BNO au {ddm(est['date'])}" if est else "")}
    lignes.append(b)
    lignes += [_ligne(e, "US 2 ans", "Rendement US 2 ans"), _ligne(e, "US 10 ans", "Rendement US 10 ans"),
               _ligne(e, "USD/JPY", "USD/JPY"), _ligne(e, "EUR/USD", "EUR/USD"),
               _ligne(e, "Japon (ETF EWJ)", "Japon (ETF EWJ)"), _ligne(e, "VIX", "VIX")]
    return {"marches": lignes, "mecanisme": mecanisme_cross_asset(e)}


def _v(e: Entrees, actif: str, k: str):
    return (e.lignes.get(actif) or {}).get(k)


SEUILS = {"dollar": (0.1, 0.2), "actions": (0.3, 0.5), "vix": (0.3, 0.5), "taux": (1.0, 3.0)}


def mecanisme_cross_asset(e: Entrees, mesures: dict | None = None) -> dict:
    """Lequel des 3 mécanismes explique le dollar : refuge (dollar ↑, actions ↓, VIX ↑), soutien monétaire (dollar ↑,
    taux courts US ↑), avantage de rendement (dollar ↑, actions ↑). Mesures sur 1 et 5 séances ; actif si toutes ses
    conditions sont remplies sur 5 séances, ou sur 1 séance (« depuis la veille »)."""
    m = mesures or {
        "dollar": (_v(e, "Indice dollar (formule du DXY, non officiel)", "variation_j1"), _v(e, "Indice dollar (formule du DXY, non officiel)", "variation_5j"), "%", "DXY (formule)"),
        "actions": (_v(e, "S&P 500 (ETF SPY)", "variation_j1"), _v(e, "S&P 500 (ETF SPY)", "variation_5j"), "%", "S&P 500 (ETF SPY)"),
        "vix": (_v(e, "VIX", "variation_j1"), _v(e, "VIX", "variation_5j"), " pt", "VIX"),
        "taux": (_v(e, "US 2 ans", "variation_j1"), _v(e, "US 2 ans", "variation_5j"), " pb", "US 2 ans")}

    def sens(nom, h):
        v = m[nom][h]
        if v is None:
            return None
        s = SEUILS[nom][h]
        return 1 if v > s else -1 if v < -s else 0

    def cond(nom, voulu):
        v1, v5, u, lib = m[nom]
        ok5, ok1 = sens(nom, 1) == voulu, sens(nom, 0) == voulu
        chiffre = f"{lib} {fr(v5, 2 if u == '%' else 1, True)}{' %' if u == '%' else u} sur 5 séances, {fr(v1, 2 if u == '%' else 1, True)}{' %' if u == '%' else u} sur 1 séance"
        return {"texte": f"{lib} {'en hausse' if voulu > 0 else 'en baisse'}", "remplie_5": ok5, "remplie_1": ok1,
                "chiffre": chiffre, "nd": v5 is None and v1 is None}
    defs = [("refuge", "Dollar fort, actions en baisse, volatilité en hausse", "Demande de refuge.", [("dollar", 1), ("actions", -1), ("vix", 1)]),
            ("monetaire", "Dollar fort, taux courts US en hausse", "Soutien monétaire.", [("dollar", 1), ("taux", 1)]),
            ("rendement", "Dollar fort, actions en hausse", "Avantage de rendement et confiance dans l'économie américaine.", [("dollar", 1), ("actions", 1)])]
    sortie = []
    for i, lib, lect, cs in defs:
        c = [cond(n, s) for n, s in cs]
        a5, a1 = all(x["remplie_5"] for x in c), all(x["remplie_1"] for x in c)
        sortie.append({"id": i, "libelle": lib, "lecture": lect, "actif": a5 or a1, "horizon": "5 séances" if a5 else "1 séance" if a1 else None,
                       "conditions": c})
    actifs = [s for s in sortie if s["actif"]]
    d5 = m["dollar"][1]
    if actifs:
        phrase = ("Mécanisme actif : " + " ; ".join(f"{s['lecture'].rstrip('.').lower()} (sur {s['horizon']})" for s in actifs)
                  + f". Le dollar (DXY) varie de {fr(d5, 2, True)} % sur 5 séances.")
    else:
        a5, v5, t5 = m["actions"][1], m["vix"][1], m["taux"][1]
        if (d5 or 0) > SEUILS["dollar"][1]:
            phrase = (f"Le dollar (DXY) progresse de {fr(d5, 2, True)} % sur 5 séances sans qu'aucun des trois mécanismes ne soit complet : "
                      f"actions {fr(a5, 2, True)} %, VIX {fr(v5, 2, True)} point, US 2 ans {fr(t5, 1, True)} pb sur la même période.")
        else:
            phrase = (f"Aucun des trois mécanismes n'est actif : le dollar (DXY) varie de {fr(d5, 2, True)} % sur 5 séances, "
                      f"sous le seuil de +{fr(SEUILS['dollar'][1], 1)} %.")
    return {"mecanismes": sortie, "phrase": phrase, "seuils": "dollar ±0,2 % (5 séances) / ±0,1 % (1 séance), actions ±0,5 % / ±0,3 %, "
                                                             "VIX ±0,5 / ±0,3 point, US 2 ans ±3 / ±1 pb",
            "date": str(_v(e, "Indice dollar (formule du DXY, non officiel)", "heure") or "")[:10] if e is not None else None}


# ------------------------------------------------------------------ section 3 : focus, chaîne de causalité, lire le chiffre
GABARITS = {
    "inflation": [("up", "Supérieur à {c}", "Scénario restrictif renforcé : soutien probable à la devise"),
                  ("", "Conforme à {c}", "Réaction selon les détails et le glissement annuel"),
                  ("dn", "Inférieur à {c}", "Anticipations de resserrement en recul"),
                  ("warn", "Global fort, sous-jacent faible", "Signal mitigé : effet de l'énergie")],
    "emploi": [("up", "Supérieur à {c}", "Marché du travail solide : moins de raisons de baisser les taux"),
               ("", "Conforme à {c}", "Lecture par le chômage et les salaires"),
               ("dn", "Inférieur à {c}", "Ralentissement : baisses de taux plus probables"),
               ("warn", "Créations fortes, chômage en hausse", "Signal mitigé : regarder les révisions")],
    "pib": [("up", "Supérieur à {c}", "Croissance solide : la banque centrale peut rester ferme"),
            ("", "Conforme à {c}", "Peu d'effet, sauf révision du trimestre précédent"),
            ("dn", "Inférieur à {c}", "Croissance fragile : devise exposée"),
            ("warn", "Révision forte du précédent", "Lire la tendance plutôt que le chiffre isolé")],
    "pmi": [("up", "Supérieur à {c}", "Activité plus forte que prévu"),
            ("", "Conforme à {c}", "Réaction faible"),
            ("dn", "Inférieur à {c}", "Activité plus faible que prévu"),
            ("warn", "Sous 50 mais au-dessus de {c}", "Contraction qui ralentit : signal ambigu")],
    "decision": [("up", "Plus restrictive que {c}", "Surprise : la devise peut monter nettement"),
                 ("", "Conforme à {c}, ton ferme", "Soutien si la suite reste restrictive"),
                 ("warn", "Conforme à {c}, ton prudent", "Réaction limitée, voire baisse : la suite compte"),
                 ("dn", "Plus accommodante que {c}", "Surprise : la devise peut baisser nettement")],
    "autre": [("up", "Supérieur à {c}", "Soutien modéré à la devise"), ("", "Conforme à {c}", "Peu d'effet attendu"),
              ("dn", "Inférieur à {c}", "Pression modérée sur la devise"), ("warn", "Révision du précédent", "Lire la révision avant le chiffre")],
}
LECTURES = {
    ("emploi", 1): "Marché du travail plus solide que prévu", ("emploi", -1): "Marché du travail plus faible que prévu",
    ("inflation", 1): "Inflation plus forte que prévu", ("inflation", -1): "Inflation plus faible que prévu",
    ("pib", 1): "Croissance plus forte que prévu", ("pib", -1): "Croissance plus faible que prévu",
    ("pmi", 1): "Activité plus forte que prévu", ("pmi", -1): "Activité plus faible que prévu",
    ("decision", 1): "Décision plus restrictive que prévu", ("decision", -1): "Décision plus accommodante que prévu"}
TAUX_LECTURE = {1: "Moins de raisons de baisser les taux", -1: "Baisses de taux plus probables", 0: "Pas de changement d'anticipations"}
# Indicateurs dont la hausse est une mauvaise nouvelle pour la devise (chômage, inscriptions)
INVERSES = re.compile(r"unemployment|claimant|jobless|claims", re.I)


def gabarit(nom_en: str, consensus) -> dict:
    fam = pa.famille(nom_en)[1]
    fam = fam if fam in GABARITS else ("emploi" if fam == "emploi" else "autre")
    c = valeur_fr(consensus) if consensus else "consensus"
    return {"famille": fam, "cas": [{"classe": k, "si": si.format(c=c), "lecture": l} for k, si, l in GABARITS[fam]]}


def surprise(p: dict) -> dict:
    r, c = num(p.get("reel")), num(p.get("consensus"))
    if r is None or c is None:
        return {"sens": 0, "ecart": None, "texte": "sans consensus"}
    ec = round(r - c, 3)
    sens = 0 if abs(ec) < 1e-9 else (1 if ec > 0 else -1)
    if INVERSES.search(p.get("evenement_en") or ""):
        sens = -sens
    return {"sens": sens, "ecart": ec, "texte": "conforme au consensus" if sens == 0 and abs(ec) < 1e-9 else
            ("au-dessus du consensus" if ec > 0 else "en dessous du consensus")}


def _variation_jour(points: list[tuple[str, float]], jour: str, unite: str) -> tuple[float | None, str | None]:
    """Variation entre la dernière observation avant `jour` et celle de `jour` (ou la première après)."""
    avant = [x for x in points if x[0] < jour]
    apres = [x for x in points if x[0] >= jour]
    if not avant or not apres:
        return None, None
    a, b = avant[-1][1], apres[0][1]
    return (round((b - a) * 100, 1) if unite == "pb" else round((b / a - 1) * 100, 2)), apres[0][0]


def section_focus(e: Entrees) -> dict:
    jour, pubs = pa.derniere_seance(e.archive, e.aujourd)
    out = {"jour": jour, "jour_texte": jour_long(jour), "publications": [], "principale": None, "chaine": [], "emploi": None}
    for p in pubs[:8]:
        s = surprise(p)
        out["publications"].append({"devise": p["devise"], "evenement": p.get("evenement"), "heure": p.get("heure_paris"),
                                    "reel": valeur_fr(p.get("reel")), "consensus": valeur_fr(p.get("consensus")) if p.get("consensus") else None,
                                    "precedent": valeur_fr(p.get("precedent")) if p.get("precedent") else None,
                                    "revision": valeur_fr(p.get("revision")) if p.get("revision") else None,
                                    "impact": p.get("impact"), "sens": s["sens"], "surprise": s["texte"], "source": p.get("source"), "date": p["date"]})
    if not pubs:
        out["raison"] = f"aucune publication forte ou moyenne archivée pour la séance du {ddm(jour)}"
        return out
    p = pubs[0]
    s = surprise(p)
    fam = pa.famille(p.get("evenement_en"))[1]
    princ = {**out["publications"][0], "famille": fam, "pays": PAYS.get(p["devise"], p["devise"]),
             "titre": f"{p.get('evenement')} ({PAYS.get(p['devise'], p['devise'])})"}
    # Emploi américain : détail du BLS (révisions, U-6, salaires)
    if p["devise"] == "USD" and str(p.get("evenement_en", "")).lower() == "non-farm employment change" and e.bls.get("disponible"):
        b = e.bls
        princ["detail_bls"] = b
        out["emploi"] = {"creations": fait(b["creations_k"] * 1000, fr(b["creations_k"] * 1000, 0, True), b["source"], b.get("publie_le") or jour),
                         "consensus": fait(None if b.get("consensus_k") is None else b["consensus_k"] * 1000,
                                           fr((b.get("consensus_k") or 0) * 1000, 0, True), "ForexFactory (consensus)", jour, "consensus non archivé"),
                         "chomage": fait(b["chomage"].get("valeur"), fr(b["chomage"].get("valeur"), 1) + " %", b["source"], b.get("publie_le") or jour),
                         "chomage_precedent": b["chomage"].get("precedent"),
                         "u6": fait(b["u6"].get("valeur"), fr(b["u6"].get("valeur"), 1) + " %", b["source"], b.get("publie_le") or jour),
                         "u6_precedent": b["u6"].get("precedent"),
                         "salaire_mm": fait(b.get("salaire_mm_pct"), fr(b.get("salaire_mm_pct"), 1, True) + " %", b["source"], b.get("publie_le") or jour),
                         "salaire_aa": b.get("salaire_aa_pct"),
                         "participation": fait(b["participation"].get("valeur"), fr(b["participation"].get("valeur"), 1) + " %", b["source"], b.get("publie_le") or jour),
                         "revisions": [{**r, "texte": (f"{_mois_txt(r['mois'])} révisé à {fr(r['revise_k'] * 1000, 0, True)} au lieu de {fr(r['premier_k'] * 1000, 0, True)}"
                                                       if r.get("premier_k") is not None else f"{_mois_txt(r['mois'])} : {fr(r['revise_k'] * 1000, 0, True)} (premier chiffre non archivé)")}
                                       for r in b.get("revisions") or []],
                         "mois": b["mois"], "lien": b.get("lien")}
    out["principale"] = princ
    # Chaîne de causalité : publication -> lecture -> taux -> banque centrale -> devise (chaque maillon chiffré et daté)
    dev = p["devise"]
    chaine = [{"texte": f"{_court(p)} {valeur_fr(p.get('reel'))}" + (f" contre {valeur_fr(p.get('consensus'))}" if p.get("consensus") else ""), "date": jour}]
    chaine.append({"texte": LECTURES.get((fam, s["sens"]), "Publication conforme au consensus" if s["sens"] == 0 else s["texte"].capitalize()), "date": jour})
    taux_cle = {"USD": "USD_2a", "EUR": "EUR_2a", "JPY": "JPY_2a", "CAD": "CAD_2a"}.get(dev)
    pts = [(str(x[0])[:10], float(x[1])) for x in (e.taux.get(taux_cle) or {}).get("points") or []] if taux_cle else []
    if not pts and dev == "USD":
        pts = e.serie("USD_2a")
    dv, dj = _variation_jour(pts, jour, "pb") if pts else (None, None)
    chaine.append({"texte": (f"{TAUX_LECTURE.get(s['sens'], '')} : 2 ans {PAYS.get(dev, dev).lower() if dev != 'USD' else 'US'} "
                             f"{fr(dv, 1, True)} pb le {ddm(dj)}") if dv is not None else f"{TAUX_LECTURE.get(s['sens'], '')} (2 ans : n/d)",
                   "date": dj, "raison": None if dv is not None else "rendement 2 ans quotidien absent pour cette devise"})
    bc = next((d for d in (e.profil.get("devises") or []) if d.get("devise") == dev), {}).get("banque_centrale") or {}
    pro = bc.get("prochaine") or {}
    pf = e.proba or {}
    if dev == "USD" and pf.get("valeur") is not None:
        chaine.append({"texte": f"Probabilité {SENS_FED.get(pf['sens'], '')} le {ddm(pro.get('date'))} : {fr(pf['valeur'], 0)} %",
                       "date": pf.get("date"), "note": f"cité par {pf.get('source')} le {ddm(pf.get('date'))} : {pf.get('citation')}"})
    else:
        chaine.append({"texte": (f"{BANQUES.get(dev, 'Banque centrale')} : prochaine décision le {ddm(pro.get('date'))}" if pro.get("date")
                                 else f"{BANQUES.get(dev, 'Banque centrale')} : prochaine décision n/d"), "date": pro.get("date"),
                       "note": "probabilité de marché : " + (pf.get("raison") or "n/d") if dev == "USD" else None})
    ligne_dev = _ligne_devise(e, dev)
    if ligne_dev:
        dv2, dj2 = _variation_jour([(a, b) for a, b in ligne_dev["points"]], jour, "%")
        if dv2 is not None and ligne_dev["inverse"]:
            dv2 = -dv2
        txt = (f"{NOMS_DEVISES.get(dev, dev).capitalize()} ({ligne_dev['libelle']}) {fr(dv2, 2, True)} % le {ddm(dj2)}" if dv2 is not None
               else f"{NOMS_DEVISES.get(dev, dev).capitalize()} : réaction n/d")
        chaine.append({"texte": txt, "date": dj2, "classe": "up" if (dv2 or 0) > 0 else "dn" if (dv2 or 0) < 0 else "", "fin": True})
    out["chaine"] = chaine
    out["avertissement"] = "Une probabilité de marché n'est pas une décision : elle peut changer fortement après les publications suivantes."
    return out


def _mois_txt(m: str) -> str:
    a, mm = m.split("-")
    return MOIS[int(mm) - 1].capitalize()


def _court(p: dict) -> str:
    en = str(p.get("evenement_en") or "").lower()
    if en == "non-farm employment change":
        return "NFP"
    return re.sub(r"\s*\(.*\)$", "", p.get("evenement") or "")


def _ligne_devise(e: Entrees, dev: str) -> dict | None:
    """Série de la devise contre le dollar (USD : indice DXY formule) depuis le point de marché (30 jours)."""
    choix = {"USD": ("Indice dollar (formule du DXY, non officiel)", False, "DXY"), "EUR": ("EUR/USD", False, "EUR/USD"),
             "GBP": ("GBP/USD", False, "GBP/USD"), "JPY": ("USD/JPY", True, "USD/JPY"), "CHF": ("USD/CHF", True, "USD/CHF"),
             "CAD": ("USD/CAD", True, "USD/CAD"), "AUD": ("AUD/USD", False, "AUD/USD"), "NZD": ("NZD/USD", False, "NZD/USD")}.get(dev)
    if not choix or not e.lignes.get(choix[0]):
        return None
    return {"points": [(p[0][:10], p[1]) for p in e.lignes[choix[0]].get("serie_30j") or []], "inverse": choix[1], "libelle": choix[2]}


def prochain_evenement(e: Entrees, apres: datetime | None = None) -> dict | None:
    apres = (apres or e.maintenant).isoformat(timespec="minutes")
    cands = [x for x in e.evenements() if x.get("impact") == "fort" and x.get("type") in ("Chiffre", "Réunion BC")
             and not x.get("publie") and (x.get("iso_utc") or "") >= apres[:16]]
    cands.sort(key=lambda x: (x.get("iso_utc") or "", pa.famille(x.get("evenement_en"))[0], x.get("devise") != "USD"))
    if not cands:
        return None
    x = cands[0]
    groupe = [y for y in e.evenements() if y.get("iso_utc") == x.get("iso_utc") and y.get("devise") == x.get("devise")
              and y.get("type") in ("Chiffre", "Réunion BC")]
    groupe.sort(key=lambda y: pa.famille(y.get("evenement_en"))[0])
    cle = next((y for y in groupe if re.search(r"core", y.get("evenement_en") or "", re.I) and y.get("consensus")), None) or x
    return {"date": x["date_paris"], "heure": x.get("heure_paris"), "iso_utc": x.get("iso_utc"), "devise": x["devise"],
            "evenement": x.get("evenement"), "evenement_en": x.get("evenement_en"),
            "titre": f"{x.get('evenement')} · {jour_long(x['date_paris'])} {x.get('heure_paris') or ''}".strip(),
            "lignes": [{"evenement": y.get("evenement"), "consensus": valeur_fr(y["consensus"]) if y.get("consensus") else None,
                        "precedent": valeur_fr(y["precedent"]) if y.get("precedent") else None, "source": y.get("source")} for y in groupe],
            "cle": cle.get("evenement"), "lire": gabarit(cle.get("evenement_en"), cle.get("consensus")),
            "source": x.get("source"), "consensus": cle.get("consensus"), "precedent": cle.get("precedent")}


def discours_semaine(e: Entrees, lundi: date) -> list[dict]:
    fin = (lundi + timedelta(days=4)).isoformat()
    par: dict[str, dict] = {}
    for x in e.evenements():
        if x.get("type") != "Discours" or not (lundi.isoformat() <= (x.get("date_paris") or "") <= fin):
            continue
        m = re.match(r"^(?:Discours|Audition)(?: de| :)?\s*(.+?)(?:,\s*(.+))?$", x.get("evenement") or "")
        qui = (m.group(1) if m else x.get("evenement") or "").strip()
        role = (m.group(2) if m and m.group(2) else "").strip()
        from core import fomc_2026
        st = fomc_2026.statut(qui, x["devise"])
        prio = (st["statut"] if x["devise"] == "USD" else
                "président" if re.search(r"gouverneur|président|governor|president", role, re.I) else "membre")
        d = par.setdefault(f"{x['devise']}|{qui}", {"devise": x["devise"], "intervenant": qui, "role": role, "passages": [],
                                                    "statut": st.get("libelle"), "priorite": prio, "rang": st["priorite"] if x["devise"] == "USD" else (0 if prio == "président" else 2),
                                                    "source_statut": st.get("source")})
        d["passages"].append(f"{jour_court(x['date_paris'])} {x.get('heure_paris') or ''}".strip())
    l = sorted(par.values(), key=lambda d: (d["devise"] != "USD", d["rang"], d["intervenant"]))
    return l[:14]


# ------------------------------------------------------------------ section 4 : banques centrales
def taux_haut(texte) -> float | None:
    t = str(texte or "").replace("<", "").replace(",", ".")
    nums = re.findall(r"-?\d+(?:\.\d+)?", t)
    return float(nums[-1]) if nums else None


def section_banques(e: Entrees) -> dict:
    taux_txt = {b.get("devise"): b.get("taux_texte") for b in e.accueil.get("banques") or []}
    lignes = []
    for d in e.profil.get("devises") or []:
        dev = d.get("devise")
        bc = d.get("banque_centrale") or {}
        der, pro = bc.get("derniere") or {}, bc.get("prochaine") or {}
        t = taux_txt.get(dev) or pro.get("taux") or der.get("publie")
        p, prec = num(der.get("publie")), num(der.get("precedent"))
        pb = round((p - prec) * 100) if p is not None and prec is not None else None
        infl = ((d.get("macro") or {}).get("inflation") or {})
        lecture = (f"Inflation {fr(infl.get('valeur'), 1)} % au {ddm(infl.get('date'))} pour une cible de {fr(infl.get('cible'), 1)} %"
                   if infl.get("valeur") is not None and infl.get("cible") is not None else "Inflation : n/d")
        com = (e.communiques or {}).get(dev) or {}
        lignes.append({"devise": dev, "banque": BANQUES.get(dev, dev), "taux_texte": valeur_fr(t) if t else "n/d", "taux": taux_haut(t),
                       "vocabulaire": ((com.get("vocabulaire") or {}).get("lecture") if com.get("disponible") else None),
                       "communique_lien": com.get("lien") if com.get("disponible") else None,
                       "derniere_date": der.get("date"), "decision": der.get("decision"), "variation_pb": pb,
                       "derniere_texte": ((f"{der.get('decision', 'décision')} de {abs(pb)} pb le {ddm(der.get('date'))}" if pb else
                                           f"{der.get('decision', 'décision')} le {ddm(der.get('date'))}") if der.get("date") else "n/d"),
                       "prochaine": pro.get("date"), "lecture": lecture, "inflation": infl.get("valeur"), "cible": infl.get("cible"),
                       "source": der.get("source") or "registre macro", "texte_profil": bc.get("texte")})
    lignes.sort(key=lambda x: -(x["taux"] if x["taux"] is not None else -9))
    # Cartes : banques qui ont bougé ou décidé récemment, ou qui décident sous 14 jours
    lim_av = (e.aujourd - timedelta(days=21)).isoformat()
    lim_ap = (e.aujourd + timedelta(days=14)).isoformat()
    cartes = []
    votes = _votes_recents(e)
    for l in lignes:
        recente = (l["derniere_date"] or "") >= lim_av
        proche = l["prochaine"] and l["prochaine"] <= lim_ap
        if not (recente or proche or l["variation_pb"]):
            continue
        etat = ("Biais restrictif" if (l["variation_pb"] or 0) > 0 else "Biais accommodant" if (l["variation_pb"] or 0) < 0 else "Statu quo")
        classe = "up" if (l["variation_pb"] or 0) > 0 else "dn" if (l["variation_pb"] or 0) < 0 else ""
        phrases = [f"{l['banque']} : {l['derniere_texte']}, taux à {l['taux_texte']}." if l["derniere_texte"] != "n/d"
                   else f"{l['banque']} : taux à {l['taux_texte']} (dernière décision non archivée)."]
        com = (e.communiques or {}).get(l["devise"]) or {}
        vo = (com.get("votes") or {}) if com.get("disponible") else {}
        v = votes.get(l["devise"])
        if vo.get("texte"):
            phrases.append(f"Vote du communiqué officiel du {ddm(com['date'])} : {vo['texte']}.")
        elif v:
            phrases.append(f"Votes du {ddm(v['date'])} : {v['reel']} (format {v['source_court']} hausse-maintien-baisse ; communiqué officiel non lu).")
        if l["inflation"] is not None:
            phrases.append(f"{l['lecture']}.")
        if l["prochaine"]:
            phrases.append(f"Prochaine décision le {ddm(l['prochaine'])}.")
        voc = com.get("vocabulaire") or {}
        cartes.append({"devise": l["devise"], "etat": etat, "classe": classe, "texte": " ".join(phrases),
                       "communique": {"date": com.get("date"), "lien": com.get("lien"), "titre": com.get("titre"),
                                      "votes": vo or None, "minorite": vo.get("minorite"), "projections": com.get("projections") or [],
                                      "vocabulaire": voc, "raison": None if com.get("disponible") else com.get("raison")} if com else None})
    return {"banques": lignes, "cartes": cartes[:6],
            "communiques_nd": {d: c.get("raison") for d, c in (e.communiques or {}).items() if not c.get("disponible")},
            "note": "Taux : registre macro et calendriers officiels ; dernier mouvement : archive des publications. Votes, projections et "
                    "changements de vocabulaire : communiqués officiels archivés (data/communiques_v9), lus en Python ; un 403 n'est jamais contourné."}


def _votes_recents(e: Entrees) -> dict:
    sortie = {}
    for p in (e.archive.get("publications") or {}).values():
        if re.search(r"votes", p.get("evenement_en") or "", re.I) and p.get("date", "") >= (e.aujourd - timedelta(days=45)).isoformat():
            if p["devise"] not in sortie or p["date"] > sortie[p["devise"]]["date"]:
                sortie[p["devise"]] = {**p, "source_court": "ForexFactory"}
    return sortie


# ------------------------------------------------------------------ section 5 et 6
def section_energie(e: Entrees, brent: dict) -> dict:
    wti, uso = e.serie("wti"), e.serie("wti_uso")
    return {"brent": brent,
            "wti": {"valeur": wti[-1][1] if wti else None, "date": wti[-1][0] if wti else None, "source": e.source("wti"),
                    "semaine_pct": variation(uso, 5, "%") if uso else variation(wti, 5, "%"),
                    "semaine_source": "ETF USO (Twelve Data), 5 séances" if uso else "WTI EIA, 5 séances",
                    "semaine_date": (uso or wti or [[None]])[-1][0]},
            "consequences": [{"cas": a, "consequence": b} for a, b in CONSEQUENCES_PETROLE],
            "sensibles": [{"devises": a, "texte": b} for a, b in SENSIBLES_PETROLE],
            "avertissement": "Pas de lecture mécanique : un pétrole qui baisse sur une demande mondiale en berne pèse aussi sur les devises cycliques."}


def section_asie(e: Entrees) -> dict:
    prix = []
    for motif, lib in (("cpi y/y", "Inflation à la consommation (IPC, sur un an)"), ("ppi y/y", "Prix à la production (IPP, sur un an)")):
        l = sorted((p for p in (e.archive.get("publications") or {}).values()
                    if p.get("devise") == "CNY" and str(p.get("evenement_en", "")).lower() == motif), key=lambda p: p["date"])
        if l:
            p = l[-1]
            prix.append({"libelle": lib, "reel": valeur_fr(p.get("reel")), "consensus": valeur_fr(p.get("consensus")) if p.get("consensus") else None,
                         "precedent": valeur_fr(p.get("precedent")) if p.get("precedent") else None, "date": p["date"], "source": p.get("source"),
                         "sens": surprise(p)["sens"]})
        else:
            prix.append({"libelle": lib, "reel": None, "raison": "publication chinoise non archivée (calendrier)"})
    marches = [_ligne(e, "Japon (ETF EWJ)", "Japon (ETF EWJ)")]
    for cle, lib in (("taiwan_ewt", "Taïwan (ETF EWT)"), ("chine_fxi", "Chine (ETF FXI)")):
        pts = e.serie(cle)
        marches.append({"libelle": lib, "valeur": pts[-1][1], "texte": fr(pts[-1][1], 2), "date": pts[-1][0], "variation_1": variation(pts, 1, "%"),
                        "variation_5": variation(pts, 5, "%"), "source": e.source(cle), "serie_30": [v for _, v in pts[-30:]]} if pts else
                       {"libelle": lib, "valeur": None, "texte": "n/d", "raison": f"ETF {lib[-4:-1]} pas encore collecté (Twelve Data, run complet suivant)"})
    forces = {f["devise"]: f for f in e.force.get("devises") or []}
    devs = [{"devise": d, "j5": (forces.get(d) or {}).get("j5"), "date": (forces.get(d) or {}).get("date"),
             "lien": {"AUD": "croissance chinoise et matières premières", "NZD": "croissance chinoise et appétit pour le risque",
                      "JPY": "flux régionaux et aversion au risque"}[d]} for d in ("AUD", "NZD", "JPY")]
    tech = [a for a in e.actualites if a["theme"] in ("actions", "asie")][:3]
    return {"prix": prix, "marches": marches, "devises": devs, "source_force": e.force.get("source"), "actualites": tech}


# ------------------------------------------------------------------ section 7 : calendrier
def semaine(aujourd: date) -> tuple[date, date]:
    lundi = aujourd - timedelta(days=aujourd.weekday())
    if aujourd.weekday() >= 5:
        lundi += timedelta(days=7)
    return lundi, lundi + timedelta(days=4)


def section_calendrier(e: Entrees) -> dict:
    lundi, vendredi = semaine(e.aujourd)
    jours = []
    for i in range(5):
        j = (lundi + timedelta(days=i)).isoformat()
        evs = [x for x in e.evenements() if x.get("date_paris") == j and x.get("impact") in ("fort", "moyen")
               and x.get("type") in ("Chiffre", "Réunion BC")]
        evs.sort(key=lambda x: (x.get("heure_paris") or "99", x.get("impact") != "fort"))
        jours.append({"date": j, "jour": JOURS[i], "cle": any(x.get("impact") == "fort" for x in evs),
                      "evenements": [{"heure": x.get("heure_paris"), "devise": x["devise"], "evenement": x.get("evenement"),
                                      "impact": x.get("impact"), "consensus": valeur_fr(x["consensus"]) if x.get("consensus") else None,
                                      "precedent": valeur_fr(x["precedent"]) if x.get("precedent") else None,
                                      "publie": valeur_fr(x["publie"]) if x.get("publie") else None} for x in evs[:9]]})
    forts = [x for x in e.evenements() if lundi.isoformat() <= (x.get("date_paris") or "") <= vendredi.isoformat()
             and x.get("impact") == "fort" and x.get("type") in ("Chiffre", "Réunion BC")]
    forts.sort(key=lambda x: (pa.famille(x.get("evenement_en"))[0], x.get("devise") != "USD", x.get("iso_utc") or ""))
    cles, vus = [], set()
    for x in forts:
        k = (x["devise"], pa.famille(x.get("evenement_en"))[1], x.get("date_paris"))
        if k in vus:
            continue
        vus.add(k)
        g = gabarit(x.get("evenement_en"), x.get("consensus"))
        cles.append({"date": x["date_paris"], "jour": jour_court(x["date_paris"]), "heure": x.get("heure_paris"), "devise": x["devise"],
                     "evenement": x.get("evenement"), "consensus": valeur_fr(x["consensus"]) if x.get("consensus") else None,
                     "precedent": valeur_fr(x["precedent"]) if x.get("precedent") else None, "publie": valeur_fr(x["publie"]) if x.get("publie") else None,
                     "lire": g})
        if len(cles) == 3:
            break
    cles.sort(key=lambda c: (c["date"], c["heure"] or ""))
    n_disc = sum(1 for x in e.evenements() if x.get("type") == "Discours" and lundi.isoformat() <= (x.get("date_paris") or "") <= vendredi.isoformat())
    return {"lundi": lundi.isoformat(), "vendredi": vendredi.isoformat(), "jours": jours, "cles": cles, "n_forts": len(forts),
            "n_discours": n_disc,
            "a_ne_pas_surinterpreter": (f"À ne pas surinterpréter : {n_disc} prises de parole cette semaine, dont celles de membres non votants, "
                                        "ou quelques milliers d'inscriptions au chômage de plus ou de moins : il faut une tendance sur plusieurs semaines."),
            "source": "Agenda (ForexFactory, calendriers officiels), heures de Paris"}


# ------------------------------------------------------------------ section 8 : classement des devises
ETAT_SCORE = {"Soutenue": 1.0, "Sous pression": -1.0, "Sans direction": 0.0, "Ancrage contredit": -0.5}
BIAIS = [(1.5, "Fort", "up"), (0.5, "Positif", "up"), (-0.5, "Neutre", ""), (-1.5, "Fragile", "warn"), (-99, "Faible", "dn")]


def _borne(x: float) -> float:
    return max(-1.0, min(1.0, x))


def ecart_2a_relatif(taux: dict, aujourd: date, jours: int = 30) -> dict[str, dict]:
    """Variation du rendement 2 ans de chaque devise sur 30 jours, moins la moyenne des autres (pb). Sans 2 ans
    quotidien : 10 ans quotidien, sinon n/d avec la raison."""
    var = {}
    for d in DEVISES:
        for m in ("2a", "10a"):
            s = taux.get(f"{d}_{m}") or {}
            if s.get("frequence") == "mensuel":
                continue
            pts = [(str(x[0])[:10], float(x[1])) for x in s.get("points") or []]
            if len(pts) < 10:
                continue
            fin = pts[-1]
            deb = valeur_au(pts, (date.fromisoformat(fin[0]) - timedelta(days=jours)).isoformat())
            if deb:
                var[d] = {"pb": round((fin[1] - deb[1]) * 100, 1), "maturite": m, "date": fin[0]}
                break
    sortie = {}
    for d in DEVISES:
        if d not in var:
            sortie[d] = {"relatif_pb": None, "raison": "pas de rendement quotidien gratuit pour cette devise"}
            continue
        autres = [v["pb"] for k, v in var.items() if k != d]
        moy = sum(autres) / len(autres) if autres else 0
        sortie[d] = {**var[d], "relatif_pb": round(var[d]["pb"] - moy, 1)}
    return sortie


def classement(e: Entrees) -> dict:
    forces = {f["devise"]: f for f in e.force.get("devises") or []}
    profils = {p["devise"]: p for p in e.profil.get("devises") or []}
    ecarts = ecart_2a_relatif(e.taux, e.aujourd)
    lignes = []
    for d in DEVISES:
        p, f = profils.get(d) or {}, forces.get(d) or {}
        etat = (p.get("etat") or {}).get("valeur")
        sur = ((p.get("macro") or {}).get("surprise_30j") or {}).get("indice")
        ec = ecarts.get(d) or {}
        comps = [
            {"id": "profil", "libelle": f"état « {etat or 'n/d'} »", "valeur": ETAT_SCORE.get(etat, 0.0) if etat else 0.0, "nd": etat is None,
             "texte": f"profil « {etat} » ({ddm(e.profil.get('date'))})" if etat else "profil n/d"},
            {"id": "surprises", "libelle": "surprises 30 jours", "valeur": _borne((sur or 0) / 1.5), "nd": sur is None,
             "texte": f"surprises 30 jours {fr(sur, 1, True)}" if sur is not None else "surprises n/d"},
            {"id": "ecart", "libelle": "écart de taux", "valeur": _borne((ec.get("relatif_pb") or 0) / 20), "nd": ec.get("relatif_pb") is None,
             "texte": (f"rendement {ec['maturite'].replace('a', ' ans')} {fr(ec['relatif_pb'], 1, True)} pb face aux autres sur 30 jours (au {ddm(ec['date'])})"
                       if ec.get("relatif_pb") is not None else f"écart de taux n/d ({ec.get('raison')})")},
            {"id": "force", "libelle": "force 5 séances", "valeur": _borne((f.get("j5") or 0) / 1.0), "nd": f.get("j5") is None,
             "texte": f"force {fr(f.get('j5'), 2, True)} % sur 5 séances (au {ddm(f.get('date'))})" if f.get("j5") is not None else "force n/d"},
        ]
        score = round(sum(c["valeur"] for c in comps), 2)
        moteur = max((c for c in comps if not c["nd"]), key=lambda c: abs(c["valeur"]), default=None)
        lignes.append({"devise": d, "score": score, "composantes": comps, "j5": f.get("j5"), "date_force": f.get("date"),
                       "moteur": moteur["texte"] if moteur and abs(moteur["valeur"]) > 0.05 else "aucun facteur net"})
    lignes.sort(key=lambda x: (-x["score"], -(x["j5"] or 0)))
    for i, l in enumerate(lignes, 1):
        l["rang"] = i
        l["biais"], l["classe"] = next((b, c) for s, b, c in BIAIS if l["score"] >= s)
    return {"devises": lignes, "methode": ("Score = état du profil (±1) + surprises 30 jours (indice ÷ 1,5, borné à ±1) + variation du "
                                           "rendement 2 ans face aux autres devises sur 30 jours (÷ 20 pb, borné à ±1) + force sur 5 séances "
                                           "(÷ 1 %, borné à ±1). Biais : Fort ≥ 1,5 ; Positif ≥ 0,5 ; Neutre > −0,5 ; Fragile > −1,5 ; sinon Faible."),
            "mention": "Pas un signal de trading : un classement des facteurs du moment."}


# ------------------------------------------------------------------ sections 9 et 10 : paires et technique
def _prochain_fort(e: Entrees, devises: set[str]) -> dict | None:
    maintenant = e.maintenant.isoformat(timespec="minutes")[:16]
    l = [x for x in e.evenements() if x.get("devise") in devises and x.get("impact") == "fort" and not x.get("publie")
         and x.get("type") in ("Chiffre", "Réunion BC") and (x.get("iso_utc") or "") >= maintenant]
    l.sort(key=lambda x: (x.get("iso_utc") or "", pa.famille(x.get("evenement_en"))[0]))
    return l[0] if l else None


def section_paires(e: Entrees, cl: dict) -> dict:
    rangs = {l["devise"]: l for l in cl["devises"]}
    top = ((e.rj.get("watchlist") or {}).get("top") or [])[:6]
    sortie = []
    for w in top:
        paire = w["paire"]
        b, c = paire.split("/")
        rb, rc = rangs.get(b) or {}, rangs.get(c) or {}
        diff = round((rb.get("score") or 0) - (rc.get("score") or 0), 2)
        biais, classe = (("Haussier conditionnel", "up") if diff > 1 else ("Baissier conditionnel", "dn") if diff < -1 else ("À confirmer", ""))
        args = [f"{b} {rb.get('rang', 'n/d')}e du classement ({rb.get('moteur', 'n/d')}) contre {c} {rc.get('rang', 'n/d')}e ({rc.get('moteur', 'n/d')})"]
        det = e.detail_paire(paire)
        et = (det.get("ecart_taux") or {})
        m = (et.get("maturites") or {}).get(et.get("defaut") or "") or {}
        if m.get("disponible"):
            args.append(f"Écart {m.get('frequence') == 'mensuel' and '10 ans mensuel' or ('2 ans' if et.get('defaut') == '2a' else '10 ans')} "
                        f"{b} − {c} : {fr(m.get('actuel_pb'), 0, True)} pb au {ddm(m.get('date'))}, {fr(m.get('variation_1m_pb'), 0, True)} pb sur 1 mois")
        else:
            args.append(f"Écart de taux {b} − {c} : n/d ({et.get('raison') or (et.get('maturites') or {}).get('2a', {}).get('raison') or 'indisponible'})")
        pf = _prochain_fort(e, {b, c})
        args.append(f"Catalyseur : {pf['devise']} {pf.get('evenement')} le {ddm(pf['date_paris'])} à {pf.get('heure_paris')}" if pf
                    else f"Risque : {w.get('risque') or 'aucune publication forte des deux devises cette semaine'}")
        fiche = (e.paires.get("fiches") or {}).get(paire) or {}
        pts = ((fiche.get("graphique_1j") or {}).get("points") or [])[-30:]
        v30 = round((pts[-1][1] / pts[0][1] - 1) * 100, 2) if len(pts) > 1 and pts[0][1] else None
        sortie.append({"paire": paire, "priorite": w.get("libelle"), "score_watchlist": w.get("score"), "biais": biais, "classe": biais and classe,
                       "ecart_scores": diff, "arguments": args,
                       "hausse_si": "; ".join((w.get("scenario_haussier") or {}).get("conditions") or []) or "n/d",
                       "baisse_si": "; ".join((w.get("scenario_baissier") or {}).get("conditions") or []) or "n/d",
                       "serie_30": [p[1] for p in pts], "dernier": pts[-1][1] if pts else None, "date": pts[-1][0] if pts else None,
                       "variation_30": v30, "catalyseur": (f"{pf['devise']} {pf.get('evenement')} ({ddm(pf['date_paris'])})" if pf else (w.get("risque") or "n/d"))})
    return {"paires": sortie, "methode": (e.rj.get("watchlist") or {}).get("methode"),
            "mention": "Biais conditionnel : écart des scores du classement (base − cotation) ; au-delà de ±1, haussier ou baissier conditionnel."}


def section_technique(e: Entrees, paires: dict) -> dict:
    if not paires.get("paires"):
        return {"disponible": False, "raison": "aucune paire dans la watchlist du jour"}
    p9 = paires["paires"][0]
    paire = p9["paire"]
    det = e.detail_paire(paire)
    j = ((det.get("chandeliers") or {}).get("1j") or {})
    h4 = ((det.get("chandeliers") or {}).get("4h") or {})
    if not j.get("bougies"):
        return {"disponible": False, "paire": paire, "raison": f"bougies quotidiennes de {paire} non collectées"}
    an = j.get("analyse") or {}
    zones = an.get("zones") or {}
    res, sup = list(zones.get("resistances") or []), list(zones.get("supports") or [])
    cours = j["bougies"][-1][4]
    dec = 3 if cours > 20 else 5
    niveaux = []
    for i, z in enumerate(sorted(res, key=lambda z: -z["haut"])):
        nom = "Zone d'extension" if i == 0 and len(res) > 1 else z["nom"]
        niveaux.append({"nom": nom, "court": "Ext." if nom == "Zone d'extension" else z["nom"], "cote": "resistance",
                        "texte": f"{fr(z['bas'], dec)}–{fr(z['haut'], dec)}" if abs(z["haut"] - z["bas"]) > 1e-9 else fr(z["haut"], dec),
                        "contacts": z.get("contacts"), "distance_pips": z.get("distance_pips"), "haut": z["haut"], "bas": z["bas"]})
    for z in sup:
        niveaux.append({"nom": z["nom"], "court": z["nom"], "cote": "support",
                        "texte": f"{fr(z['bas'], dec)}–{fr(z['haut'], dec)}" if abs(z["haut"] - z["bas"]) > 1e-9 else fr(z["haut"], dec),
                        "contacts": z.get("contacts"), "distance_pips": z.get("distance_pips"), "haut": z["haut"], "bas": z["bas"]})
    r1 = next((z for z in res if z["nom"] == "R1"), None)
    s1 = next((z for z in sup if z["nom"] == "S1"), None)
    rsi = an.get("rsi_actuel")
    et = det.get("ecart_taux") or {}
    mat = (et.get("maturites") or {}).get(et.get("defaut") or "") or {}
    w = next((x for x in (e.rj.get("watchlist") or {}).get("top") or [] if x["paire"] == paire), {})
    lt = an.get("lignes") or {}
    jour = j["bougies"][-1][0][:10]
    tech_h = [{"texte": f"Clôture quotidienne au-dessus de R1 ({fr(r1['bas'], dec)}–{fr(r1['haut'], dec)})", "remplie": cours > r1["haut"]} if r1 else None,
              {"texte": f"RSI 14 quotidien au-dessus de 50 (actuel {fr(rsi, 1)} au {ddm(jour)})", "remplie": (rsi or 0) > 50} if rsi is not None else None,
              {"texte": f"Écart de taux {paire.replace('/', ' − ')} en hausse sur 1 mois ({fr(mat.get('variation_1m_pb'), 0, True)} pb au {ddm(mat.get('date'))})",
               "remplie": (mat.get("variation_1m_pb") or 0) > 0} if mat.get("disponible") else None]
    tech_b = [{"texte": f"Clôture quotidienne sous S1 ({fr(s1['bas'], dec)}–{fr(s1['haut'], dec)})", "remplie": cours < s1["bas"]} if s1 else None,
              {"texte": f"RSI 14 quotidien sous 50 (actuel {fr(rsi, 1)})", "remplie": (rsi or 100) < 50} if rsi is not None else None,
              {"texte": f"Cassure de la ligne de support ({fr(lt['support']['valeur_actuelle'], dec)} au {ddm(lt['support']['fin']['date'])})",
               "remplie": lt["support"].get("etat") != "valide"} if lt.get("support") else None]
    bougies = j["bougies"][-130:]
    return {"disponible": True, "paire": paire, "cours": cours, "date": jour, "decimales": dec, "bougies": bougies,
            "zones": res + sup, "lignes": [x for x in (lt.get("support"), lt.get("resistance")) if x],
            "niveaux": niveaux, "rsi_1j": rsi, "rsi_4h": (h4.get("analyse") or {}).get("rsi_actuel"),
            "divergences": an.get("divergences") or [],
            "ecart": {"maturite": et.get("defaut"), "points": (mat.get("ecart") or [])[-130:], "actuel_pb": mat.get("actuel_pb"),
                      "date": mat.get("date"), "sources": mat.get("sources"), "phrase": mat.get("phrase"),
                      "raison": None if mat.get("disponible") else (et.get("raison") or "écart indisponible")},
            "macro_haussier": (w.get("scenario_haussier") or {}).get("conditions") or [],
            "macro_baissier": (w.get("scenario_baissier") or {}).get("conditions") or [],
            "technique_haussier": [x for x in tech_h if x], "technique_baissier": [x for x in tech_b if x],
            "vigilance": (f"Point de vigilance : {w.get('risque')}. Une zone n'est qu'un repère : la décision attend la confirmation "
                          "des conditions macro et techniques." if w.get("risque") else
                          "Point de vigilance : une zone n'est qu'un repère ; la décision attend la confirmation des conditions."),
            "source": f"{j.get('source') or 'Twelve Data'} ; zones, lignes et RSI calculés en Python (lot V8.2)"}


# ------------------------------------------------------------------ sections 11 à 13
def section_scenarios(e: Entrees, paires: dict) -> dict:
    sortie = []
    lettres = "ABC"
    for i, s in enumerate(((e.rj.get("scenarios") or {}).get("liste") or [])[:3]):
        cons = s.get("consequences") or {}
        u = cons.get("USD", 0)
        chip, classe = ("USD haussier", "up") if u > 0 else ("USD baissier", "dn") if u < 0 else ("Volatilité", "warn")
        effets = []
        for p in paires.get("paires") or []:
            b, c = p["paire"].split("/")
            sgn = (cons.get(b, 0) or 0) - (cons.get(c, 0) or 0)
            if sgn:
                effets.append(f"{p['paire']} en {'hausse' if sgn > 0 else 'baisse'}")
        sortie.append({"lettre": lettres[i], "id": s.get("id"), "titre": s.get("titre"), "chip": chip, "classe": classe,
                       "remplies": s.get("remplies"), "total": s.get("total"), "statut": s.get("statut"),
                       "conditions": [{"texte": c.get("libelle"), "remplie": c.get("remplie"), "chiffre": c.get("chiffre"), "date": c.get("date")}
                                      for c in s.get("conditions") or []],
                       "consequences": effets[:4] or ["aucune paire de la watchlist directement exposée"],
                       "devises": {k: v for k, v in cons.items() if v}})
    return {"scenarios": sortie, "texte_mieux_confirme": (e.rj.get("scenarios") or {}).get("texte_mieux_confirme"),
            "note": (e.rj.get("scenarios") or {}).get("note")}


def section_plan(e: Entrees, paires: dict) -> dict:
    return {"priorites": [{"rang": i + 1, "paire": p["paire"], "biais": p["biais"], "catalyseur": p["catalyseur"]}
                          for i, p in enumerate(paires.get("paires") or [])],
            "methode": [{"titre": a, "texte": b} for a, b in METHODE],
            "avant": ((e.rj.get("plan") or {}).get("avant") or [])[:3], "pendant": ((e.rj.get("plan") or {}).get("pendant") or [])[:3]}


SOURCES_OFFICIELLES = [
    ("Bureau of Labor Statistics", "Rapport sur l'emploi", "https://www.bls.gov/news.release/empsit.nr0.htm", "bls"),
    ("Trésor américain", "Courbe des taux quotidienne", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates", "tresor"),
    ("Réserve fédérale", "Communiqués", "https://www.federalreserve.gov/newsevents/pressreleases.htm", "toujours"),
    ("Banque d'Angleterre", "Décisions et procès-verbaux", "https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes", "toujours"),
    ("BCE", "Décisions de politique monétaire", "https://www.ecb.europa.eu/press/pr/html/index.en.html", "toujours"),
    ("Banque du Japon", "Politique monétaire", "https://www.boj.or.jp/en/mopo/index.htm", "toujours"),
    ("EIA", "Prix spot du pétrole (Brent)", "https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm", "toujours"),
    ("Twelve Data", "Cours, bougies, ETF (BNO, EWJ, SPY)", "https://twelvedata.com", "toujours"),
    ("ForexFactory", "Calendrier : consensus et publié", "https://www.forexfactory.com/calendar", "toujours"),
]


def sources(e: Entrees) -> list[dict]:
    sortie = []
    for nom, quoi, url, cond in SOURCES_OFFICIELLES:
        if cond == "bls" and not e.bls.get("disponible"):
            continue
        quand = (e.bls.get("publie_le") if cond == "bls" else e.serie("USD_2a")[-1][0] if cond == "tresor" and e.serie("USD_2a") else None)
        sortie.append({"nom": nom, "quoi": quoi + (f", {ddm(quand)}" if quand else ""), "url": url})
    for dev, c in (e.communiques or {}).items():
        if c.get("disponible") and c.get("lien"):
            sortie.append({"nom": f"Communiqué {c['banque']}", "quoi": f"{(c.get('titre') or '')[:70]}, {ddm(c.get('date'))}", "url": c["lien"]})
    p = e.proba or {}
    if p.get("lien"):
        sortie.append({"nom": p.get("source") or "Actualité", "quoi": f"Probabilité de la Fed citée, {ddm(p.get('date'))}", "url": p["lien"]})
    for a in e.actualites[:6]:
        if a.get("lien"):
            sortie.append({"nom": a.get("source") or "Actualité", "quoi": f"{a['titre'][:80]}, {ddm(a.get('date'))}", "url": a["lien"]})
    return sortie


# ------------------------------------------------------------------ section 1
def section_executive(e: Entrees, cl: dict, focus: dict, marches: dict, brent: dict, prochain: dict | None) -> dict:
    tete, queue = cl["devises"][0], cl["devises"][-1]
    biais = (f"{tete['devise']} soutenu" if tete["score"] >= 0.5 else "Pas de devise dominante")
    theme = e.rj.get("theme") or {}
    meca = [m for m in marches["mecanisme"]["mecanismes"] if m["actif"]]
    regime = (f"{theme.get('titre') or 'Thème n/d'}" + (f" ; mécanisme actif : {meca[0]['lecture'].rstrip('.').lower()}" if meca else " ; aucun mécanisme cross-asset net"))
    point = (f"{prochain['devise']} {prochain['evenement']}, {jour_long(prochain['date'])} à {prochain['heure']}"
             + (f" (consensus {valeur_fr(prochain['consensus'])})" if prochain.get("consensus") else "")) if prochain else "aucune publication forte à venir cette semaine"
    themes = []
    pr = focus.get("principale")
    if pr:
        themes.append({"titre": pr["pays"], "texte": f"{pr['evenement']} : {pr['reel']}" + (f" contre {pr['consensus']} attendu" if pr.get("consensus") else "")
                       + f" le {ddm(pr['date'])}" + (f" ; prochain rendez-vous : {prochain['evenement']} le {ddm(prochain['date'])}." if prochain else ".")})
    if brent.get("disponible"):
        sp = brent.get("semaine_pct")
        themes.append({"titre": "Énergie et géopolitique",
                       "texte": f"Pétrole {fr(sp, 1, True)} % sur 5 séances ({brent.get('semaine_source')}, au {ddm(brent.get('semaine_date'))}) ; "
                                f"Brent officiel {fr(brent['officiel']['valeur'])} $ au {ddm(brent['officiel']['date'])}."})
    spy, vix = e.lignes.get("S&P 500 (ETF SPY)") or {}, e.lignes.get("VIX") or {}
    themes.append({"titre": "Actions et risque",
                   "texte": f"S&P 500 (ETF SPY) {fr(spy.get('variation_5j'), 2, True)} % sur 5 séances au {ddm(str(spy.get('heure') or '')[:10])}, "
                            f"VIX {fr(vix.get('niveau'), 2)} au {ddm(str(vix.get('heure') or '')[:10])}."})
    return {"biais": biais, "biais_classe": tete["classe"], "regime": regime, "point_determinant": point,
            "themes": themes[:3], "tete": {k: tete[k] for k in ("devise", "score", "biais", "moteur")},
            "queue": {k: queue[k] for k in ("devise", "score", "biais", "moteur")},
            "fed": jauge_fed(e), "actualites": e.actualites}


SENS_FED = {"hausse": "d'une hausse", "baisse": "d'une baisse", "maintien": "d'un maintien"}


def jauge_fed(e: Entrees) -> dict:
    """Probabilité citée dans une actualité (nombre vérifié dans le texte source), avec le repère d'une semaine plus tôt."""
    p = e.proba or {}
    pro = next((d for d in (e.profil.get("devises") or []) if d.get("devise") == "USD"), {}).get("banque_centrale", {}).get("prochaine") or {}
    titre = f"Probabilité de la prochaine décision de la Fed{(' (' + ddm(pro.get('date')) + ')') if pro.get('date') else ''}"
    if p.get("valeur") is None:
        return {"valeur": None, "texte": "n/d", "raison": p.get("raison") or "aucune probabilité citée", "titre": titre}
    ref = p.get("reference") or {}
    return {"valeur": p["valeur"], "texte": fr(p["valeur"], 0) + " %", "sens": p["sens"],
            "titre": f"Probabilité {SENS_FED.get(p['sens'], '')} de la Fed{(' le ' + ddm(pro.get('date'))) if pro.get('date') else ''}",
            "precedent": ref.get("valeur"), "precedent_date": ref.get("date"), "raison_precedent": p.get("raison_reference"),
            "citation": p.get("citation"), "lien": p.get("lien"), "source": f"{p.get('source')}, {ddm(p.get('date'))}", "date": p.get("date"),
            "methode": "chiffre cité dans une actualité collectée (titre ou résumé du flux RSS), retrouvé mot pour mot en Python ; "
                       "pas de données de futures gratuites et licites"}


# ------------------------------------------------------------------ textes de secours (Python, phrases complètes)
def textes_python(s: dict) -> dict[str, list[str]]:
    """Un ou deux paragraphes par section ; chaque phrase cite au moins un fait chiffré et daté des faits."""
    f = s["faits"]
    t: dict[str, list[str]] = {}
    ex, cl, fo = f["s1"], f["s8"], f["s3"]
    tete = ex["tete"]
    t["s1"] = [f"Le classement du jour place le {NOMS_DEVISES.get(tete['devise'], tete['devise'])} en tête avec un score de {fr(tete['score'], 2, True)}, "
               f"porté par {tete['moteur']}. Le {NOMS_DEVISES.get(ex['queue']['devise'], ex['queue']['devise'])} ferme la marche ({fr(ex['queue']['score'], 2, True)}) : "
               f"{ex['queue']['moteur']}. Le rendez-vous déterminant est {ex['point_determinant']}."]
    fed = ex.get("fed") or {}
    if fed.get("valeur") is not None:
        t["s1"].append(f"{fed['source'].split(',')[0]} cite le {ddm(fed['date'])} une probabilité {SENS_FED.get(fed['sens'], '')} de la Fed de {fed['texte']}"
                       + (f", contre {fr(fed['precedent'], 0)} % le {ddm(fed['precedent_date'])}." if fed.get("precedent") is not None else "."))
    m = f["s2"]["mecanisme"]
    lig = {l["libelle"]: l for l in f["s2"]["marches"]}
    dxy = lig.get("Indice dollar (DXY, formule)") or {}
    us2 = lig.get("Rendement US 2 ans") or {}
    t["s2"] = [f"L'indice dollar (formule du DXY) s'établit à {dxy.get('texte', 'n/d')} au {ddm(dxy.get('date'))}, "
               f"soit {fr(dxy.get('variation_5'), 2, True)} % sur 5 séances, et le rendement américain à 2 ans à {us2.get('texte', 'n/d')} au {ddm(us2.get('date'))}. "
               + m["phrase"]]
    if fo.get("principale"):
        p = fo["principale"]
        ph = (f"Publication la plus importante de la séance du {ddm(fo['jour'])} : {p['evenement']} ({p['pays']}) à {p['reel']}"
              + (f" contre {p['consensus']} attendu" if p.get("consensus") else "") + (f", précédent révisé à {p['revision']}" if p.get("revision") else "") + ".")
        em = fo.get("emploi")
        if em:
            ph += (f" Le chômage est à {em['chomage']['texte']} (précédent {fr(em['chomage_precedent'], 1)} %), le sous-emploi U-6 à {em['u6']['texte']} "
                   f"(précédent {fr(em['u6_precedent'], 1)} %) et le salaire horaire progresse de {em['salaire_mm']['texte']} sur le mois, selon le BLS ({ddm(p['date'])}).")
            rv = [r for r in em["revisions"] if r.get("premier_k") is not None]
            if rv:
                ph += f" Révision : {rv[0]['texte']}."
        t["s3"] = [ph]
        maill = [c["texte"] for c in fo["chaine"] if c.get("texte")]
        if len(maill) >= 3:
            t["s3"].append(f"Chaîne de lecture : {maill[0]}, puis {maill[2][0].lower() + maill[2][1:]}" + (f", et {maill[-1][0].lower() + maill[-1][1:]}." if len(maill) > 3 else "."))
    else:
        t["s3"] = [f"Aucune publication forte n'est archivée pour la séance du {ddm(fo['jour'])} : la lecture repose sur les marchés et le calendrier."]
    pro = f.get("prochain")
    if pro:
        t["s3"].append(f"Prochain rendez-vous clé : {pro['evenement']} ({pro['devise']}) le {ddm(pro['date'])} à {pro['heure']}"
                       + (f", consensus {valeur_fr(pro['consensus'])}" if pro.get("consensus") else "") + (f", précédent {valeur_fr(pro['precedent'])}." if pro.get("precedent") else "."))
    bq = f["s4"]["banques"]
    haut = bq[0] if bq else None
    bouge = [b for b in bq if b.get("variation_pb")]
    t["s4"] = [(f"Le taux directeur le plus élevé des 9 banques est celui de la {haut['banque']}, à {haut['taux_texte']} après une {haut['derniere_texte']}. " if haut else "")
               + (" ".join(f"La {b['banque']} a {'relevé' if b['variation_pb'] > 0 else 'abaissé'} son taux de {abs(b['variation_pb'])} pb le {ddm(b['derniere_date'])}, à {b['taux_texte']}."
                           for b in bouge[:3])
                  or f"Aucune des 9 banques n'a modifié son taux lors de sa dernière réunion (au {ddm(f['date'])}).")]
    en = f["s5"]
    br = en["brent"]
    if br.get("disponible"):
        ph = (f"Le Brent officiel (EIA) vaut {fr(br['officiel']['valeur'])} $ au {ddm(br['officiel']['date'])}"
              + (f" ; le relais quotidien par l'ETF BNO l'estime à {fr(br['estimation']['valeur'])} $ au {ddm(br['estimation']['date'])}" if br.get("estimation") else "")
              + f", soit {fr(br.get('semaine_pct'), 1, True)} % sur 5 séances ({br.get('semaine_source')}).")
        if en["wti"].get("semaine_pct") is not None:
            ph += f" Le WTI suit avec {fr(en['wti']['semaine_pct'], 1, True)} % sur 5 séances ({en['wti']['semaine_source']}, au {ddm(en['wti']['semaine_date'])})."
        t["s5"] = [ph]
    else:
        t["s5"] = [f"Le Brent n'est pas disponible au {ddm(f['date'])} : {br.get('raison')}."]
    asie = f["s6"]
    ps = [p for p in asie["prix"] if p.get("reel")]
    ph = " ".join(f"En Chine, {p['libelle'].split(' (')[0].lower()} : {p['reel']} au {ddm(p['date'])}" + (f" contre {p['consensus']} attendu." if p.get("consensus") else ".") for p in ps)
    devs = "; ".join(f"{d['devise']} {fr(d['j5'], 2, True)} %" for d in asie["devises"] if d.get("j5") is not None)
    t["s6"] = [((ph + " ") if ph else "") + (f"Sur 5 séances au {ddm(asie['devises'][0].get('date'))}, les devises exposées à l'Asie varient ainsi : {devs}." if devs else
                                           f"Force des devises asiatiques n/d au {ddm(f['date'])}.")]
    ca = f["s7"]
    cles = ca["cles"]
    t["s7"] = [f"La semaine du {ddm(ca['lundi'])} au {ddm(ca['vendredi'])} compte {ca['n_forts']} publications fortes" +
               (" ; les trois à suivre : " + ", ".join(f"{c['devise']} {c['evenement']} ({c['jour']} {c['heure']})" for c in cles) + "." if cles else ".")]
    rk = cl["devises"]
    t["s8"] = [f"Classement au {ddm(f['date'])} : {rk[0]['devise']} ({fr(rk[0]['score'], 2, True)}), {rk[1]['devise']} ({fr(rk[1]['score'], 2, True)}) et "
               f"{rk[2]['devise']} ({fr(rk[2]['score'], 2, True)}) en tête ; {rk[-1]['devise']} ({fr(rk[-1]['score'], 2, True)}) ferme la marche, avec {rk[-1]['moteur']}."]
    pp = f["s9"]["paires"]
    if pp:
        t["s9"] = [f"{len(pp)} paires retenues au {ddm(f['date'])}, en tête {pp[0]['paire']} ({pp[0]['priorite'].lower() if pp[0].get('priorite') else 'priorité n/d'}, "
                   f"écart des scores {fr(pp[0]['ecart_scores'], 2, True)}) : {pp[0]['biais'].lower()}."]
    else:
        t["s9"] = [f"Aucune paire retenue au {ddm(f['date'])} : watchlist absente du rapport du jour."]
    te = f["s10"]
    if te.get("disponible"):
        nv = {n["court"]: n for n in te["niveaux"]}
        t["s10"] = [f"{te['paire']} clôture à {fr(te['cours'], te['decimales'])} au {ddm(te['date'])}, avec un RSI 14 quotidien de {fr(te['rsi_1j'], 1)}"
                    + (f", entre la résistance R1 ({nv['R1']['texte']}) et le support S1 ({nv['S1']['texte']})." if nv.get("R1") and nv.get("S1") else
                       f", sous la résistance R1 ({nv['R1']['texte']})." if nv.get("R1") else
                       f", au-dessus du support S1 ({nv['S1']['texte']})." if nv.get("S1") else ".")
                    + (f" {te['ecart']['phrase']}" if te['ecart'].get("phrase") and "corrélation" in te['ecart']['phrase'] else "")]
    else:
        t["s10"] = [f"Technique indisponible au {ddm(f['date'])} : {te.get('raison')}."]
    sc = f["s11"]["scenarios"]
    t["s11"] = [" ".join(f"Scénario {x['lettre']} ({x['titre']}) : {x['remplies']} condition{'s' if (x['remplies'] or 0) > 1 else ''} sur {x['total']} remplie{'s' if (x['remplies'] or 0) > 1 else ''} au {ddm(f['date'])}."
                         for x in sc) or f"Aucun scénario évalué au {ddm(f['date'])}."]
    pl = f["s12"]["priorites"]
    t["s12"] = [f"Priorité 1 au {ddm(f['date'])} : {pl[0]['paire']} ({pl[0]['biais'].lower()}), catalyseur {pl[0]['catalyseur']}." if pl
                else f"Aucune priorité au {ddm(f['date'])}."]
    co = f["s13"]
    t["s13"] = [f"Biais central au {ddm(f['date'])} : {co['biais']}. Rendez-vous déterminant : {co['rendez_vous']}."]
    return t


# ------------------------------------------------------------------ assemblage
def calculer(docs: Path, cache: Path, aujourd: date | None = None, maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    aujourd = aujourd or maintenant.date()
    e = Entrees(docs, cache, aujourd, maintenant)
    faits: dict = {"date": aujourd.isoformat()}
    erreurs: dict[str, str] = {}

    def essayer(cle, fn, *a):
        try:
            return fn(*a)
        except Exception as exc:  # noqa: BLE001 — une section en panne ne casse pas les autres
            log.exception("synthèse V9, section %s", cle)
            erreurs[cle] = f"section indisponible : {type(exc).__name__} : {str(exc)[:160]}"
            return {"disponible": False, "raison": erreurs[cle]}
    brent = essayer("brent", brent_quotidien, e)
    faits["s2"] = essayer("s2", section_marches, e, brent if isinstance(brent, dict) else {})
    faits["s3"] = essayer("s3", section_focus, e)
    faits["prochain"] = essayer("prochain", prochain_evenement, e)
    faits["s4"] = essayer("s4", section_banques, e)
    faits["s5"] = essayer("s5", section_energie, e, brent)
    faits["s6"] = essayer("s6", section_asie, e)
    faits["s7"] = essayer("s7", section_calendrier, e)
    faits["s8"] = essayer("s8", classement, e)
    faits["s9"] = essayer("s9", section_paires, e, faits["s8"])
    faits["s10"] = essayer("s10", section_technique, e, faits["s9"])
    faits["s11"] = essayer("s11", section_scenarios, e, faits["s9"])
    faits["s12"] = essayer("s12", section_plan, e, faits["s9"])
    lundi, _ = semaine(aujourd)
    faits["discours"] = essayer("discours", discours_semaine, e, lundi)
    faits["s1"] = essayer("s1", section_executive, e, faits["s8"], faits["s3"], faits["s2"], brent, faits["prochain"])
    pp = (faits["s9"].get("paires") or []) if isinstance(faits["s9"], dict) else []
    faits["s13"] = {"biais": faits["s1"].get("biais", "n/d"), "rendez_vous": faits["s1"].get("point_determinant", "n/d"),
                    "priorites": [f"{p['paire']} : {p['biais'].lower()} ; hausse si {p['hausse_si']}" for p in pp[:3]],
                    "prudence": ("Une zone n'est qu'un repère et une probabilité n'est pas une décision : attendre la publication, puis "
                                 "la confirmation de la structure, avant d'envisager quoi que ce soit."),
                    "sources": sources(e)}
    lundi_, vendredi_ = semaine(aujourd)
    s = {"genere_le": maintenant.isoformat(timespec="seconds"), "date": aujourd.isoformat(), "version": "quotidienne",
         "titre": "Rapport macroéconomique et Forex",
         "semaine": f"Semaine du {lundi_.day} au {vendredi_.day} {MOIS[vendredi_.month - 1]}" if lundi_.month == vendredi_.month
                    else f"Semaine du {lundi_.day} {MOIS[lundi_.month - 1]} au {vendredi_.day} {MOIS[vendredi_.month - 1]}",
         "jour": jour_long(aujourd.isoformat()).capitalize() + f" {aujourd.year}",
         "faits": faits, "erreurs": erreurs, "mention": MENTION}
    # titre de la section 3 : le pays de la publication principale
    pr = (faits["s3"] or {}).get("principale") if isinstance(faits["s3"], dict) else None
    s["sections"] = []
    for sid, titre, sous, court in TITRES:
        if sid == "s3" and pr:
            titre, court = f"{pr['pays']} : {pr['evenement']}", pr["pays"]
        if sid == "s10" and isinstance(faits["s10"], dict) and faits["s10"].get("paire"):
            titre, court = f"{faits['s10']['paire']} : la technique au service du scénario", f"{faits['s10']['paire']} technique"
        s["sections"].append({"id": sid, "numero": int(sid[1:]), "titre": titre, "sous_titre": sous, "court": court,
                              "erreur": erreurs.get(sid)})
    try:
        s["textes"] = textes_python(s)
    except Exception as exc:  # noqa: BLE001
        log.exception("textes Python de la synthèse V9")
        s["textes"] = {}
        erreurs["textes"] = str(exc)[:200]
    # Le texte Python passe le même contrôle que celui du modèle : une phrase qui échoue est retirée (jamais de phrase
    # sans fait chiffré ni de nombre absent des faits, même en rédaction automatique)
    from core import controle_texte as ct
    autorises = ct.nombres_autorises(faits)
    for sid, paras in list(s["textes"].items()):
        propres = []
        for para in paras:
            gardees = [ph for ph in ct.phrases(para) if not ct.verifier(ph, autorises)]
            if gardees:
                propres.append(" ".join(gardees))
        s["textes"][sid] = propres
    for sid, *_ in TITRES:   # jamais de texte vide : phrase datée de repli
        if not s["textes"].get(sid):
            s["textes"][sid] = [f"Section indisponible au {ddm(aujourd.isoformat())} : {erreurs.get(sid, 'données absentes')}."]
    s["redaction"] = {sid: {"par": "automatique", "libelle": "rédaction automatique"} for sid, *_ in TITRES}
    return s
