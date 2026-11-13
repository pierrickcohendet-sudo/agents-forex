"""Synthèse V9.4 : la structure des rapports modèles du 09/11 et du 13/11 (docs/modele/).

Un tronc fixe (synthèse exécutive, vue d'ensemble des marchés) puis des SECTIONS PAYS DYNAMIQUES : chaque devise reçoit
un score d'actualité calculé en Python (publication forte la veille ou le jour même, décision ou procès-verbal de banque
centrale, seuil sensible proche, actualités du jour) ; les 2 à 5 plus élevées ont leur section, dans cet ordre, et les
autres sont regroupées dans une section commune. Puis énergie, actions et sentiment, calendrier (aujourd'hui et semaine
prochaine), classement des devises avec les divergences, paires, scénarios, méthode d'exécution, conclusion, sources.

Tout est calculé en Python (scores, rangs, biais, conditions remplies, qualificatifs, distances aux seuils) ; le modèle ne
fait que rédiger à partir de ces faits (contrôle des nombres). Jamais d'entrée, de stop ni d'objectif, jamais « long » ou
« short » : des scénarios haussiers ou baissiers, des conditions, des zones de repère et la gestion du risque en général.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import publications_archive as pa
from core import synthese_v9 as v9
from core.synthese_v9 import (BANQUES, DEVISES, NOMS_DEVISES, PAYS, ddm, fr, gabarit, jour_court, jour_long, surprise,
                              valeur_fr, variation, valeur_au)

log = logging.getLogger(__name__)

MENTION = ("Aide à la décision : biais conditionnels, zones de repère et conditions, jamais un ordre ni un niveau "
           "d'exécution ; la gestion du risque reste générale.")
PILOTEES = {"CNY": "change piloté par la Banque populaire de Chine (fixing quotidien) : classé à part"}
MIN_COMPOSANTES = 3
SEUIL_SECTION = 2.0
MAX_PAYS = 5
ADJECTIF_PAYS = {"USD": "américain", "EUR": "européen", "GBP": "britannique", "JPY": "japonais", "CHF": "suisse", "CAD": "canadien",
                 "AUD": "australien", "NZD": "néo-zélandais", "CNY": "chinois"}
MOTS_PAYS = {"USD": r"\b(fed|fomc|u\.?s\.?|united states|america\w*|treasur\w*|wall street|dollar)\b",
             "EUR": r"\b(ecb|euro ?zone|euro area|eurozone|lagarde|germany|german|france|french|italy|euro)\b",
             "GBP": r"\b(boe|bank of england|uk|britain|british|sterling|pound|bailey)\b",
             "JPY": r"\b(boj|bank of japan|japan\w*|yen|tokyo|ueda|takaichi)\b",
             "CHF": r"\b(snb|swiss|switzerland|franc)\b", "CAD": r"\b(boc|bank of canada|canada|canadian|loonie|macklem)\b",
             "AUD": r"\b(rba|australia\w*|aussie|bullock)\b", "NZD": r"\b(rbnz|new zealand|kiwi)\b",
             "CNY": r"\b(china|chinese|beijing|pboc|yuan|xi jinping)\b"}
# Mécanisme propre à chaque devise (texte fixe, chiffré ensuite par les faits du jour)
POURQUOI = {
    "USD": "Le dollar dépend d'abord des anticipations de taux de la Fed, lisibles sur le rendement à 2 ans.",
    "EUR": "L'euro dépend de l'écart de taux avec les États-Unis et de la facture énergétique de la zone.",
    "GBP": "La livre dépend de la vitesse de resserrement de la BoE comparée à celle de la Fed, et de la croissance britannique.",
    "JPY": "Le yen reste pénalisé par l'écart de rendement avec les États-Unis, qui nourrit le portage (carry trade).",
    "CHF": "Le franc suisse joue un rôle défensif : il profite du stress, mais perd de l'attrait quand les rendements américains montent.",
    "CAD": "Le dollar canadien dépend du pétrole, de la Banque du Canada et de la croissance américaine.",
    "AUD": "Le dollar australien dépend de la Chine, des matières premières et de l'appétit pour le risque.",
    "NZD": "Le dollar néo-zélandais est très sensible à l'appétit pour le risque et à la demande chinoise.",
    "CNY": "Le yuan est piloté par la Banque populaire de Chine ; ses publications pèsent surtout sur AUD et NZD.",
}
RETOURNEMENT = {
    "USD": "Une désinflation inattendue ou des membres de la Fed plus prudents peuvent corriger fortement les anticipations.",
    "EUR": "Des données européennes solides ou une détente des anticipations de la Fed soutiendraient l'euro.",
    "GBP": "Une croissance qui fléchit sous le poids des taux réduirait l'avantage de la livre.",
    "JPY": "Une intervention des autorités japonaises ou un débouclage du portage peuvent apprécier le yen très rapidement.",
    "CHF": "Un rebond durable des actions et des rendements américains plus élevés pèseraient sur le franc.",
    "CAD": "Un repli du pétrole ou un dollar américain plus fort peuvent peser sur le CAD malgré la Banque du Canada.",
    "AUD": "Un rebond des actions et des données chinoises solides soutiendraient l'AUD.",
    "NZD": "Une amélioration du sentiment de risque et de la demande chinoise soutiendrait le NZD.",
    "CNY": "Un changement du fixing de la PBoC modifierait la tendance du yuan.",
}
UNITES_TEMPS = [("Hebdomadaire", "Régime macro et structure générale"), ("Quotidien", "Biais directionnel et zones de liquidité"),
                ("4 heures", "Structure, cassures et changements de caractère"), ("1 heure", "Confirmation du mouvement"),
                ("30 minutes", "Confirmation fine de la structure avant toute décision")]
INDICATEURS_A_SUIVRE = [("US 2 ans", "Confirmation ou non du resserrement anticipé"),
                        ("Écart US 2 ans − Japon 2 ans", "Élargissement favorable au dollar, ou resserrement"),
                        ("Indice dollar (DXY, formule)", "Confirmation de la force générale du dollar"),
                        ("VIX", "Dégradation ou amélioration du sentiment de risque"),
                        ("Brent (EIA)", "Évolution du risque inflationniste énergétique")]
CHAINE_ACTIONS = ["Doutes sur les investissements dans l'IA", "baisse des actions technologiques", "moins d'appétit pour le risque",
                  "pression sur AUD, NZD et devises cycliques", "demande possible de CHF et JPY"]


def _lire(chemin: Path):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ entrées
class Entrees94(v9.Entrees):
    def __init__(self, docs: Path, cache: Path, aujourd: date, maintenant: datetime):
        super().__init__(docs, cache, aujourd, maintenant)
        b = _lire(self.cache / "bls_emploi.json")
        self.prix = b.get("prix") or {}
        self.officiels = _lire(self.cache / "officiels_v94.json")
        racine = self.cache.parent.parent
        try:
            from core import actualites, communiques_v9
            self.declarations = actualites.declarations(actualites.articles(_lire(self.cache / "collecte_news.json")))
            self.pv = communiques_v9.analyser_pv(racine)
            self.tous_articles = actualites.articles(_lire(self.cache / "collecte_news.json"))
        except Exception as exc:  # noqa: BLE001
            log.warning("V9.4 : déclarations ou procès-verbaux illisibles : %s", exc)
            self.declarations, self.pv, self.tous_articles = [], {}, []
        from core import seuils
        cours = {}
        for p in ("USD/JPY",):
            l = self.lignes.get(p)
            if l and l.get("niveau") is not None:
                cours[p] = l["niveau"]
        self.seuils = seuils.distances(cours)


# ------------------------------------------------------------------ qualificatifs de niveau (B6)
def semaines(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Dernière clôture de chaque semaine ISO."""
    par: dict[tuple, tuple[str, float]] = {}
    for d, v in points:
        a, s, _ = date.fromisoformat(d).isocalendar()
        par[(a, s)] = (d, v)
    return [par[k] for k in sorted(par)]


def qualificatif(points: list[tuple[str, float]]) -> str | None:
    """« plus haut de 6 mois », « plus bas d'un mois », « 2e semaine de baisse »… calculé sur les clôtures."""
    if len(points) < 10:
        return None
    d0, v0 = points[-1]
    fin = date.fromisoformat(d0)
    for mois, lib in ((6, "de 6 mois"), (3, "de 3 mois"), (1, "d'un mois")):
        debut = (fin - timedelta(days=int(30.5 * mois))).isoformat()
        fen = [v for d, v in points if debut <= d < d0]
        if len(fen) < 5:
            continue
        if v0 > max(fen):
            return f"plus haut {lib}"
        if v0 < min(fen):
            return f"plus bas {lib}"
    sem = semaines(points)
    if len(sem) >= 3:
        n, sens = 0, None
        for i in range(len(sem) - 1, 0, -1):
            s = 1 if sem[i][1] > sem[i - 1][1] else -1 if sem[i][1] < sem[i - 1][1] else 0
            if s == 0 or (sens is not None and s != sens):
                break
            sens, n = s, n + 1
        if n >= 2:
            return f"{n}e semaine de {'hausse' if sens > 0 else 'baisse'}"
        if n == 1:
            return "en hausse sur la semaine" if sens > 0 else "en baisse sur la semaine"
    return "stable sur la semaine"


# ------------------------------------------------------------------ 1. synthèse exécutive
def risque_majeur(e: Entrees94) -> dict:
    proche = [s for s in e.seuils if s.get("proche")]
    if proche:
        s = proche[0]
        return {"texte": s["texte"], "source": s["source"], "lien": s.get("lien"), "type": "seuil", "paire": s["paire"],
                "distance_pct": s["distance_pct"], "distance_pips": s["distance_pips"], "niveau": s["niveau"], "cours": s["cours"]}
    vix = e.lignes.get("VIX") or {}
    if (vix.get("niveau") or 0) >= 20:
        return {"texte": f"VIX à {fr(vix['niveau'], 2)} au {ddm(str(vix.get('heure'))[:10])} : volatilité élevée", "type": "volatilite"}
    pro = v9.prochain_evenement(e)
    if pro:
        return {"texte": f"publication de {pro['devise']} {pro['evenement']} le {ddm(pro['date'])} à {pro['heure']}", "type": "publication"}
    return {"texte": "aucun seuil sensible proche ni publication forte imminente", "type": "aucun"}


def section_exec(e: Entrees94, cl: dict, pays: list[dict], marches: dict) -> dict:
    tete = (cl.get("devises") or [{}])[0]
    meca = [m for m in (marches.get("mecanisme") or {}).get("mecanismes") or [] if m["actif"]]
    biais = (f"{NOMS_DEVISES.get(tete.get('devise'), tete.get('devise', '')).capitalize()} "
             + ("fortement soutenu" if tete.get("score", 0) >= 0.6 else "soutenu" if tete.get("score", 0) >= 0.3 else "légèrement en tête"))
    theme = e.rj.get("theme") or {}
    dominant = pays[0] if pays else None
    facteur = (f"{dominant['pays']} : {dominant['elements'][0]}" if dominant and dominant.get("elements") else theme.get("titre") or "n/d")
    elements = []
    for p in pays[:3]:
        elements.append({"titre": p["pays"], "texte": "; ".join(p.get("elements") or [])[:260] or p.get("pourquoi")})
    while len(elements) < 3:
        a = next((x for x in e.actualites if x["theme_libelle"] not in [el["titre"] for el in elements]), None)
        if not a:
            break
        elements.append({"titre": a["theme_libelle"], "texte": f"{a['titre']} ({a['source']}, {ddm(a['date'])})"})
    return {"biais": biais, "biais_classe": "up", "regime": (theme.get("titre") or "n/d") + (
                f" ; mécanisme actif : {meca[0]['lecture'].rstrip('.').lower()}" if meca else ""),
            "facteur_dominant": facteur, "risque_majeur": risque_majeur(e), "elements": elements[:3],
            "fed": v9.jauge_fed(e), "actualites": e.actualites, "declarations": e.declarations}


# ------------------------------------------------------------------ 2. vue d'ensemble des marchés
def _tuile(e, libelle, pts, unite, src, d=2, suffixe=""):
    if not pts:
        return {"libelle": libelle, "valeur": None, "texte": "n/d", "raison": "série absente"}
    return {"libelle": libelle, "valeur": pts[-1][1], "texte": fr(pts[-1][1], d) + suffixe, "date": pts[-1][0],
            "qualificatif": qualificatif(pts), "variation_5": variation(pts, 5, unite), "unite": unite, "source": src,
            "serie_30": [v for _, v in pts[-30:]]}


def _situation(v5, unite, seuil):
    if v5 is None:
        return "n/d"
    return "Hausse" if v5 > seuil else "Baisse" if v5 < -seuil else "Stable"


def section_marches(e: Entrees94, brent: dict) -> dict:
    base = v9.section_marches(e, brent)
    off = e.serie("brent")
    tuiles = [_tuile(e, "US 2 ans", e.serie("USD_2a"), "pb", e.source("USD_2a"), 2, " %"),
              _tuile(e, "US 10 ans", e.serie("USD_10a"), "pb", e.source("USD_10a"), 2, " %"),
              _tuile(e, "Brent (EIA, $/baril)", off, "%", "EIA, prix spot du Brent (via FRED DCOILBRENTEU)", 2, " $"),
              _tuile(e, "Or au comptant", e.serie("or_xau"), "%", e.source("or_xau"), 0, " $")]
    dxy, uj = e.lignes.get("Indice dollar (formule du DXY, non officiel)") or {}, e.lignes.get("USD/JPY") or {}
    us10, qqq, cu, bno = e.serie("USD_10a"), e.serie("nasdaq_qqq"), e.serie("cuivre_cper"), e.serie("brent_bno")
    classes = [
        ("Dollar (DXY, formule)", dxy.get("variation_5j"), "%", 0.2, {"Hausse": "Avantage de taux ou recherche de refuge (voir le mécanisme)",
                                                                       "Baisse": "Anticipations de la Fed en recul ou appétit pour le risque", "Stable": "Pas de signal net"}),
        ("Obligations US (10 ans)", variation(us10, 5, "pb"), "pb", 3, {"Hausse": "Rendements en hausse : réévaluation des taux et prime de terme",
                                                                          "Baisse": "Rendements en baisse : détente des anticipations", "Stable": "Peu de mouvement des taux longs"}),
        ("Yen (USD/JPY)", uj.get("variation_5j"), "%", 0.3, {"Hausse": "Yen faible : écart de taux, risque d'intervention près des seuils",
                                                             "Baisse": "Yen recherché : refuge ou débouclage du portage", "Stable": "Yen stable"}),
        ("Or", variation(e.serie("or_xau"), 5, "%"), "%", 0.5, {"Hausse": "Demande de protection ou dollar plus faible",
                                                                  "Baisse": "Pression des taux réels", "Stable": "Or sans direction"}),
        ("Pétrole (fonds BNO, 5 séances)", variation(bno, 5, "%") if bno else variation(off, 5, "%"), "%", 1.0,
         {"Hausse": "Prime de risque énergétique en hausse", "Baisse": "Détente géopolitique ou demande plus faible", "Stable": "Pétrole stable"}),
        ("Actions technologiques (ETF QQQ)", variation(qqq, 5, "%"), "%", 0.8, {"Hausse": "Appétit pour le risque", "Baisse": "Pression sur le secteur technologique",
                                                                               "Stable": "Sans direction"}),
        ("Cuivre (ETF CPER)", variation(cu, 5, "%"), "%", 0.8, {"Hausse": "Demande industrielle mieux orientée", "Baisse": "Doutes sur la demande industrielle",
                                                                  "Stable": "Sans direction"}),
    ]
    tableau = []
    for lib, v5, u, seuil, lectures in classes:
        sit = _situation(v5, u, seuil)
        tableau.append({"actif": lib, "situation": sit, "variation_5": v5, "unite": u,
                        "texte": "n/d" if v5 is None else f"{fr(v5, 2 if u == '%' else 1, True)}{' %' if u == '%' else ' pb'} sur 5 séances",
                        "interpretation": lectures.get(sit, "n/d") if v5 is not None else "série pas encore collectée",
                        "raison": None if v5 is not None else "série absente (prochain run complet)"})
    return {**base, "tuiles": tuiles, "classes": tableau}


# ------------------------------------------------------------------ 3. score d'actualité et sections pays
def score_actualite(e: Entrees94) -> dict[str, dict]:
    jour, _ = pa.derniere_seance(e.archive, e.aujourd)
    pubs = pa.publications_du(e.archive, jour, ("fort", "moyen", "faible"))
    du_jour = pa.publications_du(e.archive, e.aujourd.isoformat(), ("fort", "moyen", "faible"))
    scores = {d: {"score": 0.0, "raisons": []} for d in DEVISES}

    def ajouter(dev, pts, raison):
        if dev in scores:
            scores[dev]["score"] += pts
            scores[dev]["raisons"].append(raison)
    def poids(impact, nom_en):
        """Fort : 3. Agrégat clé de la zone (PIB, inflation, emploi, décision), même classé « moyen » ou « faible » par le
        calendrier (deuxième estimation du PIB, par exemple) : 2. Autre publication moyenne : 1. Indicateur national ou
        faible : 0."""
        cle = pa.famille(nom_en or "")[1] in ("decision", "emploi", "inflation", "pib")
        national = re.match(r"^(German|French|Italian|Spanish|Tokyo|Ivey)\b", nom_en or "")
        if impact == "fort":
            return 3
        if cle and not national:
            return 2
        return 1 if impact == "moyen" else 0
    for p in pubs + du_jour:
        w = poids(p.get("impact"), p.get("evenement_en"))
        if w:
            ajouter(p["devise"], w, f"{p.get('evenement') or p.get('evenement_en')} publié le {ddm(p['date'])}")
    lim = (e.aujourd - timedelta(days=8)).isoformat()
    for d in e.profil.get("devises") or []:
        bc = d.get("banque_centrale") or {}
        der, pro = bc.get("derniere") or {}, bc.get("prochaine") or {}
        if (der.get("date") or "") >= lim:
            ajouter(d["devise"], 3, f"décision de la {BANQUES.get(d['devise'])} le {ddm(der['date'])}")
        if pro.get("date") and e.aujourd.isoformat() <= pro["date"] <= (e.aujourd + timedelta(days=3)).isoformat():
            ajouter(d["devise"], 2, f"décision de la {BANQUES.get(d['devise'])} le {ddm(pro['date'])}")
    for dev, pv in (e.pv or {}).items():
        if pv.get("disponible") and (pv.get("date") or "") >= (e.aujourd - timedelta(days=14)).isoformat():
            ajouter(dev, 2, f"délibérations publiées ({ddm(pv.get('date'))})")
    for s in e.seuils:
        if s.get("proche"):
            for dev in s["paire"].split("/"):
                if dev != "USD":
                    ajouter(dev, 4, s["texte"])
    for x in e.evenements():
        if x.get("date_paris") == e.aujourd.isoformat() and not x.get("publie") and x.get("type") in ("Chiffre", "Réunion BC"):
            w = min(2, poids(x.get("impact"), x.get("evenement_en")))
            if w:
                ajouter(x["devise"], w, f"{x.get('evenement')} attendu aujourd'hui à {x.get('heure_paris')}")
    for dev, motif in MOTS_PAYS.items():
        n = sum(1 for a in e.tous_articles if re.search(motif, a.get("titre") or "", re.I))
        if n:
            ajouter(dev, min(3, n * 0.5), f"{n} titre{'s' if n > 1 else ''} d'actualité")
    for d in scores.values():
        d["score"] = round(d["score"], 1)
    return scores


def _publications_devise(e: Entrees94, dev: str) -> list[dict]:
    lim = (e.aujourd - timedelta(days=6)).isoformat()
    l = [p for p in (e.archive.get("publications") or {}).values() if p.get("devise") == dev and p.get("date", "") >= lim
         and p.get("impact") in ("fort", "moyen")]
    l.sort(key=lambda p: (pa.importance(p), [-ord(c) for c in p["date"]]))   # la plus importante d'abord, puis la plus récente
    sortie = []
    for p in l[:6]:
        s = surprise(p)
        nom = re.sub(r"\.(?=\s|$)", "", p.get("evenement") or p.get("evenement_en") or "")   # « prélim. » couperait la phrase
        sortie.append({"evenement": nom, "evenement_en": p.get("evenement_en"), "date": p["date"], "heure": p.get("heure_paris"), "reel": valeur_fr(p.get("reel")),
                       "consensus": valeur_fr(p["consensus"]) if p.get("consensus") else None,
                       "precedent": valeur_fr(p["precedent"]) if p.get("precedent") else None, "sens": s["sens"], "surprise": s["texte"],
                       "votes_officiels": (p.get("votes_officiels") or {}).get("texte"), "source": p.get("source"), "impact": p.get("impact")})
    return sortie


def _ecart_2a(e: Entrees94, a: str, b: str) -> dict:
    sa, sb = (e.taux.get(f"{a}_2a") or {}).get("points") or [], (e.taux.get(f"{b}_2a") or {}).get("points") or []
    if not sa or not sb:
        return {"valeur": None, "raison": f"rendement 2 ans {ADJECTIF_PAYS.get(b if not sb else a)} quotidien absent"}
    db = dict(map(tuple, sb))
    ec = [(d, round((v - db[d]) * 100, 1)) for d, v in sa if d in db]
    if not ec:
        return {"valeur": None, "raison": "aucune date commune"}
    return {"valeur": ec[-1][1], "date": ec[-1][0], "variation_1m": variation(ec, 20, "pts"), "serie": ec[-60:],
            "texte": f"{fr(ec[-1][1], 0, True)} pb au {ddm(ec[-1][0])}"}


def _biais_pays(cl: dict, dev: str) -> tuple[str, str]:
    ligne = next((l for l in cl.get("devises") or [] if l["devise"] == dev), None)
    if not ligne:
        return ("devise pilotée", "") if dev in PILOTEES else ("non classé", "")
    return {"Fort": ("très soutenu", "up"), "Positif": ("soutenu", "up"), "Neutre": ("neutre", ""), "Fragile": ("fragile", "warn"),
            "Faible": ("faible", "dn")}.get(ligne["biais"], (ligne["biais"].lower(), ""))


def section_pays(e: Entrees94, dev: str, score: dict, cl: dict, banques: dict) -> dict:
    """Gabarit commun : titre et biais, faits du jour, pourquoi, chaîne de causalité, risque de retournement, mon biais."""
    biais, classe = _biais_pays(cl, dev)
    pubs = _publications_devise(e, dev)
    bq = next((b for b in banques.get("banques") or [] if b["devise"] == dev), {})
    com = (e.communiques or {}).get(dev) or {}
    pv = (e.pv or {}).get(dev) or {}
    faits, elements = [], []
    if bq:
        faits.append(f"{bq['banque']} : taux à {bq['taux_texte']}" + (f", {bq['derniere_texte']}" if bq.get("derniere_texte") not in (None, "n/d") else "")
                     + (f" ; prochaine décision le {ddm(bq['prochaine'])}" if bq.get("prochaine") else ""))
    for p in pubs[:4]:
        t = f"{p['evenement']} ({ddm(p['date'])}) : {p['reel']}" + (f" contre {p['consensus']} attendu" if p.get("consensus") else "") + (
            f", précédent {p['precedent']}" if p.get("precedent") else "")
        faits.append(t)
        if p["impact"] == "fort":
            elements.append(t)
    off = (e.officiels or {}).get(dev) or {}
    detail_officiel = [dict(x, cle=k) for k, x in off.items() if isinstance(x, dict) and x.get("valeur") is not None]
    vo = (com.get("votes") or {}) if com.get("disponible") else {}
    if vo.get("texte"):
        faits.append(f"Vote du communiqué officiel du {ddm(com['date'])} : {vo['texte']}")
    seuil = next((s for s in e.seuils if dev in s["paire"].split("/") and dev != "USD"), None)
    if seuil:
        faits.append(f"{seuil['texte']} ({seuil['explication']})")
        elements.insert(0, seuil["texte"])
    ecart = _ecart_2a(e, "USD", dev) if dev != "USD" else _ecart_2a(e, "USD", "EUR")
    chaine = _chaine_pays(e, dev, pubs, ecart)
    pr = (cl.get("devises") or [])
    rang = next((l for l in pr if l["devise"] == dev), None)
    mon_biais = (f"Biais {biais} sur le {NOMS_DEVISES[dev]} : rang {rang['rang']} du classement ({rang['moteur']})." if rang else
                 f"Biais {biais} : {PILOTEES.get(dev, 'données insuffisantes pour classer la devise')}.")
    return {"devise": dev, "pays": PAYS[dev], "titre": f"{PAYS[dev]} : {_titre_pays(dev, pubs, seuil, bq)}", "biais": biais, "classe": classe,
            "score": score["score"], "raisons": score["raisons"], "faits": faits, "elements": elements[:2] or faits[:1],
            "publications": pubs, "officiels": detail_officiel, "pourquoi": POURQUOI[dev],
            "ecart_2a": ecart, "chaine": chaine, "retournement": RETOURNEMENT[dev], "seuil": seuil, "mon_biais": mon_biais,
            "communique": {"date": com.get("date"), "lien": com.get("lien"), "projections": com.get("projections") or [],
                           "vocabulaire": (com.get("vocabulaire") or {}).get("lecture"), "minorite": vo.get("minorite")} if com.get("disponible") else None,
            "deliberations": pv if pv.get("disponible") else None}


def _titre_pays(dev, pubs, seuil, bq) -> str:
    if seuil:
        return f"le risque majeur sur {seuil['paire']}"
    forte = next((p for p in pubs if p["impact"] == "fort"), None)
    if forte:
        return f"{forte['evenement']} {forte['surprise']}"
    if bq.get("derniere_date"):
        return f"{BANQUES[dev]}, {bq.get('derniere_texte')}"
    return "actualité du jour"


def _chaine_pays(e, dev, pubs, ecart) -> list[str]:
    forte = next((p for p in pubs if p["impact"] == "fort" and p.get("consensus")), None)
    ch = []
    if forte:
        ch.append(f"{forte['evenement']} {forte['reel']} contre {forte['consensus']}")
        fam = pa.famille(next((p.get("evenement_en") for p in (e.archive.get("publications") or {}).values()
                               if p.get("evenement") == forte["evenement"] and p.get("devise") == dev), ""))[1]
        ch.append(v9.LECTURES.get((fam, forte["sens"]), "Publication conforme" if forte["sens"] == 0 else forte["surprise"]))
        ch.append(v9.TAUX_LECTURE.get(forte["sens"], ""))
    if ecart.get("valeur") is not None and dev != "USD":
        ch.append(f"écart de taux 2 ans USD − {dev} {ecart['texte']}")
    ch.append({1: f"soutien au {NOMS_DEVISES[dev]}", -1: f"pression sur le {NOMS_DEVISES[dev]}"}.get(forte["sens"] if forte else 0,
                                                                                                    f"effet à confirmer sur le {NOMS_DEVISES[dev]}"))
    return [c for c in ch if c]


def details_usd(e: Entrees94, banques: dict) -> dict:
    """États-Unis : composantes des prix (BLS), emploi détaillé, Fed (décision, déclarations, probabilités), obligations
    (2 ans, 10 ans, pente 10 ans − 2 ans), « Ce que je veux voir » (conditions cochées en Python)."""
    us2, us10 = e.serie("USD_2a"), e.serie("USD_10a")
    pente = round((us10[-1][1] - us2[-1][1]), 2) if us2 and us10 and us2[-1][0] == us10[-1][0] else None
    dxy = (e.lignes.get("Indice dollar (formule du DXY, non officiel)") or {}).get("variation_5j")
    ec_de, ec_jp = _ecart_2a(e, "USD", "EUR"), _ecart_2a(e, "USD", "JPY")
    fed = v9.jauge_fed(e)
    voir = [{"texte": f"US 2 ans en progression sur 5 séances ({fr(variation(us2, 5, 'pb'), 1, True)} pb au {ddm(us2[-1][0]) if us2 else 'n/d'})",
             "remplie": (variation(us2, 5, "pb") or 0) > 0},
            {"texte": "Anticipations de hausse de la Fed en progression sur une semaine" + (
                f" ({fr(fed['valeur'], 0)} % contre {fr(fed['precedent'], 0)} %)" if fed.get("valeur") is not None and fed.get("precedent") is not None else " (n/d : aucune probabilité comparable citée)"),
             "remplie": bool(fed.get("valeur") is not None and fed.get("precedent") is not None and fed["valeur"] > fed["precedent"] and fed.get("sens") == "hausse"),
             "nd": not (fed.get("valeur") is not None and fed.get("precedent") is not None)},
            {"texte": f"Indice dollar qui confirme ({fr(dxy, 2, True)} % sur 5 séances)", "remplie": (dxy or 0) > 0.2},
            {"texte": f"Écart de taux favorable au dollar face à l'euro (2 ans US − Allemagne {ec_de.get('texte', 'n/d')}, {fr(ec_de.get('variation_1m'), 0, True)} pb sur un mois)",
             "remplie": (ec_de.get("variation_1m") or 0) > 0}]
    bq = next((b for b in banques.get("banques") or [] if b["devise"] == "USD"), {})
    com = (e.communiques or {}).get("USD") or {}
    return {"prix": e.prix or None, "emploi": e.bls if e.bls.get("disponible") else None,
            "fed": {"decision": bq.get("derniere_texte"), "taux": bq.get("taux_texte"), "prochaine": bq.get("prochaine"),
                    "votes": ((com.get("votes") or {}).get("texte") if com.get("disponible") else None),
                    "minorite": ((com.get("votes") or {}).get("minorite") if com.get("disponible") else None),
                    "probabilite": fed, "declarations": [d for d in e.declarations if d["devise"] == "USD"]},
            "obligations": {"us2": us2[-1] if us2 else None, "us10": us10[-1] if us10 else None, "pente": pente,
                            "source": e.source("USD_2a"), "ecart_jp": ec_jp, "ecart_de": ec_de},
            "ce_que_je_veux_voir": voir}


def section_commune(e: Entrees94, devs: list[str], cl: dict, banques: dict) -> dict:
    lignes = []
    for d in devs:
        biais, classe = _biais_pays(cl, d)
        bq = next((b for b in banques.get("banques") or [] if b["devise"] == d), {})
        pubs = _publications_devise(e, d)
        f = [f"{bq['banque']} à {bq['taux_texte']}" + (f", {bq['derniere_texte']}" if bq.get("derniere_texte") not in (None, "n/d") else "")] if bq else []
        f += [f"{p['evenement']} ({ddm(p['date'])}) : {p['reel']}" + (f" contre {p['consensus']}" if p.get("consensus") else "") for p in pubs[:2]]
        lignes.append({"devise": d, "pays": PAYS[d], "biais": biais, "classe": classe, "faits": f, "pourquoi": POURQUOI[d],
                       "retournement": RETOURNEMENT[d], "pilotee": PILOTEES.get(d)})
    return {"devises": lignes, "titre": ", ".join(PAYS[d] for d in devs[:-1]) + (" et " if len(devs) > 1 else "") + (PAYS[devs[-1]] if devs else "")}


# ------------------------------------------------------------------ énergie, actions, calendrier
def section_energie(e: Entrees94, brent: dict) -> dict:
    off, wti, bno, uso = e.serie("brent"), e.serie("wti"), e.serie("brent_bno"), e.serie("wti_uso")
    return {"brent": {"valeur": off[-1][1] if off else None, "date": off[-1][0] if off else None, "texte": fr(off[-1][1]) + " $" if off else "n/d",
                      "nature": "prix spot du Brent publié par l'EIA (repris par FRED DCOILBRENTEU), en dollars par baril",
                      "qualificatif": qualificatif(off), "retard_jours_ouvres": brent.get("retard_jours_ouvres"), "alerte": brent.get("alerte"),
                      "serie_6m": brent.get("serie_6m") or []},
            "wti": {"valeur": wti[-1][1] if wti else None, "date": wti[-1][0] if wti else None, "texte": fr(wti[-1][1]) + " $" if wti else "n/d",
                    "nature": "prix spot du WTI (EIA, FRED DCOILWTICO)"},
            "fonds": [{"libelle": "Fonds BNO (contrats Brent)", "variation_5": variation(bno, 5, "%"), "date": bno[-1][0] if bno else None,
                       "nature": "variation d'un fonds coté, jamais un prix au baril"},
                      {"libelle": "Fonds USO (contrats WTI)", "variation_5": variation(uso, 5, "%"), "date": uso[-1][0] if uso else None,
                       "nature": "variation d'un fonds coté, jamais un prix au baril"}],
            "actualites": [a for a in e.actualites if a["theme"] == "energie"][:3],
            "effets": [{"cas": a, "effet": b} for a, b in v9.CONSEQUENCES_PETROLE],
            "devises": [{"devises": a, "texte": b} for a, b in v9.SENSIBLES_PETROLE]}


def section_actions(e: Entrees94) -> dict:
    qqq, spy = e.serie("nasdaq_qqq"), e.serie("sp500_spy")
    ec = _ecart_2a(e, "USD", "JPY")
    return {"actualites": [a for a in e.actualites if a["theme"] in ("actions", "asie")][:4],
            "qqq_5": variation(qqq, 5, "%"), "qqq_date": qqq[-1][0] if qqq else None, "qualificatif_qqq": qualificatif(qqq),
            "spy_5": variation(spy, 5, "%"), "chaine": CHAINE_ACTIONS,
            "exception": (f"USD/JPY peut rester haussier si l'avantage de taux américain domine le débouclage du portage : écart 2 ans "
                          f"US − Japon {ec['texte']}, {fr(ec.get('variation_1m'), 0, True)} pb sur un mois.") if ec.get("valeur") is not None else
                         "USD/JPY peut rester haussier si l'avantage de taux américain domine le débouclage du portage."}


def section_calendrier(e: Entrees94) -> dict:
    auj = e.aujourd.isoformat()
    aujourdhui = [{"heure": x.get("heure_paris"), "devise": x["devise"], "evenement": x.get("evenement"), "impact": x.get("impact"),
                   "consensus": valeur_fr(x["consensus"]) if x.get("consensus") else None,
                   "precedent": valeur_fr(x["precedent"]) if x.get("precedent") else None,
                   "publie": valeur_fr(x["publie"]) if x.get("publie") else None}
                  for x in sorted(e.evenements(), key=lambda x: x.get("iso_utc") or "")
                  if x.get("date_paris") == auj and x.get("impact") in ("fort", "moyen") and x.get("type") in ("Chiffre", "Réunion BC")]
    lundi = e.aujourd - timedelta(days=e.aujourd.weekday()) + timedelta(days=7)
    prochaine = []
    for x in sorted(e.evenements(), key=lambda x: x.get("iso_utc") or ""):
        if lundi.isoformat() <= (x.get("date_paris") or "") <= (lundi + timedelta(days=4)).isoformat() and x.get("impact") == "fort" \
                and x.get("type") in ("Chiffre", "Réunion BC", "Discours"):
            prochaine.append({"jour": jour_court(x["date_paris"]), "date": x["date_paris"], "heure": x.get("heure_paris"),
                              "evenement": x.get("evenement"), "devise": x["devise"]})
    cle = v9.prochain_evenement(e, e.maintenant.replace(hour=0, minute=0))
    cle = cle if cle and cle["date"] == auj else None
    return {"aujourdhui": aujourdhui, "semaine_prochaine": prochaine[:12], "lundi_prochain": lundi.isoformat(), "cle": cle,
            "a_ne_pas_surinterpreter": v9.section_calendrier(e).get("a_ne_pas_surinterpreter"),
            "source": "Agenda (ForexFactory, calendriers officiels), heures de Paris"}


# ------------------------------------------------------------------ classement corrigé (C1)
def composante_bc(e: Entrees94, dev: str) -> dict:
    """Dynamique de la banque centrale : dernière décision (hausse +1, baisse −1, maintien 0, sur 120 jours), ton du
    communiqué comparé au précédent (± 0,5), indication sur la suite des délibérations (± 0,25)."""
    p = next((d for d in e.profil.get("devises") or [] if d["devise"] == dev), {})
    der = ((p.get("banque_centrale") or {}).get("derniere") or {})
    v, morceaux = 0.0, []
    if der.get("date") and der["date"] >= (e.aujourd - timedelta(days=120)).isoformat():
        dec = der.get("decision")
        v += {"hausse": 1.0, "baisse": -1.0}.get(dec, 0.0)
        morceaux.append(f"{dec} le {ddm(der['date'])}")
    com = (e.communiques or {}).get(dev) or {}
    lec = (com.get("vocabulaire") or {}).get("lecture") if com.get("disponible") else None
    if lec in ("vocabulaire plus restrictif", "vocabulaire plus accommodant"):
        v += 0.5 if "restrictif" in lec else -0.5
        morceaux.append(lec)
    pv = (e.pv or {}).get(dev) or {}
    if pv.get("disponible") and pv.get("suite"):
        txt = " ".join(pv["suite"]).lower()
        if re.search(r"increase|hike|tighten|raise", txt):
            v += 0.25
            morceaux.append("délibérations : hausse supplémentaire envisagée")
        elif re.search(r"cut|lower|ease|reduc", txt):
            v -= 0.25
            morceaux.append("délibérations : baisse envisagée")
    if not morceaux:
        return {"id": "bc", "libelle": "banque centrale", "valeur": 0.0, "nd": True, "texte": "dynamique de la banque centrale n/d"}
    return {"id": "bc", "libelle": "banque centrale", "valeur": max(-1.0, min(1.0, v)), "nd": False,
            "texte": f"{BANQUES[dev]} : " + ", ".join(morceaux)}


def classement(e: Entrees94) -> dict:
    """Moyenne des seules composantes disponibles (un n/d ne compte jamais pour 0), au moins 3 composantes pour être
    classée ; le CNY, devise pilotée, est classé à part."""
    base = v9.classement(e)
    forces = {f["devise"]: f for f in e.force.get("devises") or []}
    lignes, a_part = [], []
    for l in base["devises"]:
        dev = l["devise"]
        comps = []
        for c in l["composantes"]:
            c = dict(c)
            if c["id"] == "ecart" and "2 ans" not in c["texte"] and not c["nd"]:
                # écart de taux : rendement à 2 ans seulement (consigne) ; pas de substitut 10 ans
                c.update({"valeur": 0.0, "nd": True, "texte": "écart de taux 2 ans n/d (pas de rendement 2 ans quotidien gratuit)"})
            if c["id"] == "force":
                # force relative entre les 9 devises (rang sur 5 séances), pour ne pas compter deux fois le mouvement du dollar
                f = forces.get(dev) or {}
                rang = (f.get("rangs") or {}).get("j5")
                if rang is not None:
                    c.update({"valeur": round(max(-1.0, min(1.0, (5 - rang) / 4)), 2), "nd": False,
                              "texte": f"force sur 5 séances : rang {rang} sur 9 ({fr(f.get('j5'), 2, True)} % au {ddm(f.get('date'))})"})
            comps.append(c)
        comps.append(composante_bc(e, dev))
        dispo = [c for c in comps if not c["nd"]]
        if dev in PILOTEES:
            a_part.append({"devise": dev, "raison": PILOTEES[dev], "composantes": comps})
            continue
        if len(dispo) < MIN_COMPOSANTES:
            a_part.append({"devise": dev, "raison": f"{len(dispo)} composante(s) disponible(s) sur {len(comps)} : il en faut {MIN_COMPOSANTES}",
                           "composantes": comps})
            continue
        score = round(sum(c["valeur"] for c in dispo) / len(dispo), 2)
        moteur = max(dispo, key=lambda c: abs(c["valeur"]))
        lignes.append({"devise": dev, "score": score, "composantes": comps, "n_composantes": len(dispo), "j5": l.get("j5"),
                       "moteur": moteur["texte"] if abs(moteur["valeur"]) > 0.05 else "aucun facteur net"})
    lignes.sort(key=lambda x: (-x["score"], -(x["j5"] or 0)))
    for i, l in enumerate(lignes, 1):
        l["rang"] = i
        l["biais"], l["classe"] = next((b, c) for s, b, c in ((0.5, "Fort", "up"), (0.15, "Positif", "up"), (-0.15, "Neutre", ""),
                                                             (-0.5, "Fragile", "warn"), (-9, "Faible", "dn")) if l["score"] >= s)
    divergences = []
    for i, a in enumerate(lignes):
        for b in lignes[i + 1:]:
            divergences.append((round(a["score"] - b["score"], 2), a, b))
    divergences.sort(key=lambda x: -x[0])
    vues, div = set(), []
    for d, a, b in divergences:
        if (a["devise"], b["devise"]) in vues:
            continue
        vues.add((a["devise"], b["devise"]))
        div.append({"forte": a["devise"], "faible": b["devise"], "ecart": d,
                    "raison": f"{a['devise']} : {a['moteur']} ; {b['devise']} : {b['moteur']}"})
        if len(div) == 5:
            break
    return {"devises": lignes, "a_part": a_part, "divergences": div,
            "methode": ("Score = moyenne des composantes disponibles (état du profil, surprises sur 30 jours, rendement face aux autres "
                        "devises, force sur 5 séances, dynamique de la banque centrale), chacune bornée à ±1 ; au moins 3 composantes. "
                        "Biais : Fort ≥ 0,5 ; Positif ≥ 0,15 ; Neutre > −0,15 ; Fragile > −0,5 ; sinon Faible. Devise pilotée classée à part."),
            "mention": base.get("mention")}


# ------------------------------------------------------------------ méthode et conclusion
def section_methode(e: Entrees94, us: dict, risque: dict, cal: dict) -> dict:
    us2 = e.serie("USD_2a")
    dxy = (e.lignes.get("Indice dollar (formule du DXY, non officiel)") or {}).get("variation_5j")
    ec = us.get("obligations", {}).get("ecart_de") or {}
    v2 = variation(us2, 5, "pb")
    haussier = [{"texte": f"US 2 ans en progression ({fr(v2, 1, True)} pb sur 5 séances)", "remplie": (v2 or 0) > 0},
                {"texte": f"Écart de taux favorable au dollar ({fr(ec.get('variation_1m'), 0, True)} pb sur un mois face à l'Allemagne)", "remplie": (ec.get("variation_1m") or 0) > 0},
                {"texte": f"Indice dollar en hausse ({fr(dxy, 2, True)} % sur 5 séances)", "remplie": (dxy or 0) > 0.2},
                {"texte": "Cassure structurelle de la paire, puis confirmation en 30 minutes", "remplie": None}]
    baissier = [{"texte": f"US 2 ans en recul ({fr(v2, 1, True)} pb sur 5 séances)", "remplie": (v2 or 0) < 0},
                {"texte": "Anticipations de hausse de la Fed en recul", "remplie": None},
                {"texte": f"Indice dollar en baisse ({fr(dxy, 2, True)} % sur 5 séances)", "remplie": (dxy or 0) < -0.2},
                {"texte": "Cassure structurelle baissière, puis confirmation en 30 minutes", "remplie": None}]
    pub = next((x for x in cal.get("aujourdhui") or [] if x["impact"] == "fort" and not x.get("publie")), None)
    risques = [{"type": "Marché", "texte": "variation normale des cours : taille de position calculée avant, à partir du risque accepté"},
               {"type": "Publication", "texte": f"{pub['devise']} {pub['evenement']} à {pub['heure']} : éviter les minutes qui encadrent la publication" if pub
                else "aucune publication forte restant aujourd'hui"},
               {"type": "Écart d'ouverture", "texte": "week-end : risque d'écart à la réouverture" if e.aujourd.weekday() == 4 else "pas de week-end avant la prochaine séance"},
               {"type": "Intervention", "texte": risque["texte"] if risque.get("type") == "seuil" else "aucun seuil d'intervention proche"}]
    return {"unites": [{"unite": a, "role": b} for a, b in UNITES_TEMPS], "confirmations_haussier": haussier,
            "confirmations_baissier": baissier, "risques": risques,
            "mention": "Pas de niveau d'exécution : des conditions à vérifier et une gestion du risque générale."}


def indicateurs_a_suivre(e: Entrees94, us: dict) -> list[dict]:
    us2 = e.serie("USD_2a")
    ec = (us.get("obligations") or {}).get("ecart_jp") or {}
    dxy, vix = e.lignes.get("Indice dollar (formule du DXY, non officiel)") or {}, e.lignes.get("VIX") or {}
    off = e.serie("brent")
    vals = [(fr(us2[-1][1], 2) + " %", us2[-1][0]) if us2 else ("n/d", None),
            ((fr(ec["valeur"], 0, True) + " pb") if ec.get("valeur") is not None else "n/d", ec.get("date")),
            (fr(dxy.get("niveau"), 2), str(dxy.get("heure") or "")[:10]) if dxy.get("niveau") is not None else ("n/d", None),
            (fr(vix.get("niveau"), 2), str(vix.get("heure") or "")[:10]) if vix.get("niveau") is not None else ("n/d", None),
            (fr(off[-1][1]) + " $", off[-1][0]) if off else ("n/d", None)]
    return [{"indicateur": lib, "valeur": v, "date": d, "observer": obs} for (lib, obs), (v, d) in zip(INDICATEURS_A_SUIVRE, vals)]


# ------------------------------------------------------------------ assemblage
def calculer(docs: Path, cache: Path, aujourd: date | None = None, maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    aujourd = aujourd or maintenant.date()
    e = Entrees94(docs, cache, aujourd, maintenant)
    erreurs: dict[str, str] = {}

    def essayer(cle, fn, *a):
        try:
            return fn(*a)
        except Exception as exc:  # noqa: BLE001 — une section en panne ne casse pas les autres
            log.exception("synthèse V9.4, section %s", cle)
            erreurs[cle] = f"section indisponible : {type(exc).__name__} : {str(exc)[:160]}"
            return {"disponible": False, "raison": erreurs[cle]}
    brent = essayer("brent", v9.brent_quotidien, e)
    cl = essayer("classement", classement, e)
    banques = essayer("banques", v9.section_banques, e)
    marches = essayer("marches", section_marches, e, brent)
    scores = essayer("scores", score_actualite, e)
    ordre = sorted(DEVISES, key=lambda d: -(scores.get(d, {}).get("score") or 0)) if isinstance(scores, dict) and "disponible" not in scores else DEVISES
    retenus = [d for d in ordre if (scores[d]["score"] or 0) >= SEUIL_SECTION][:MAX_PAYS] if "disponible" not in scores else []
    if len(retenus) < 2:
        retenus = ordre[:2]
    autres = [d for d in DEVISES if d not in retenus]
    pays = [essayer(f"pays_{d}", section_pays, e, d, scores[d], cl, banques) for d in retenus]
    us = essayer("usd", details_usd, e, banques)
    for p in pays:
        if p.get("devise") == "USD":
            p["usd"] = us
    paires = essayer("paires", v9.section_paires, e, v9.classement(e))
    technique = essayer("technique", v9.section_technique, e, paires)
    cal = essayer("calendrier", section_calendrier, e)
    exec_ = essayer("exec", section_exec, e, cl, [p for p in pays if p.get("pays")], marches)
    faits = {"date": aujourd.isoformat(), "exec": exec_, "marches": marches, "scores": scores,
             "commune": essayer("commune", section_commune, e, autres, cl, banques),
             "energie": essayer("energie", section_energie, e, brent), "actions": essayer("actions", section_actions, e),
             "calendrier": cal, "classement": cl, "banques": banques,
             "paires": {**paires, "technique": technique} if isinstance(paires, dict) else paires,
             "scenarios": essayer("scenarios", v9.section_scenarios, e, paires), "prochain": essayer("prochain", v9.prochain_evenement, e)}
    for p in pays:
        faits[f"pays_{p.get('devise')}"] = p
    faits["methode"] = essayer("methode", section_methode, e, us if isinstance(us, dict) else {}, exec_.get("risque_majeur") or {}, cal)
    pp = (paires.get("paires") or []) if isinstance(paires, dict) else []
    for sc in faits["scenarios"].get("scenarios") or []:
        u = (sc.get("devises") or {}).get("USD", 0)
        sc["or"] = "or sous pression (dollar et taux en hausse)" if u > 0 else "or soutenu (dollar en baisse)" if u < 0 else "or recherché à moyen terme en cas de stress"
    faits["conclusion"] = {"biais": exec_.get("biais", "n/d"), "priorites": [f"{p['paire']} : {p['biais'].lower()} ; {p['catalyseur']}" for p in pp[:5]],
                           "indicateurs": essayer("indicateurs", indicateurs_a_suivre, e, us if isinstance(us, dict) else {}),
                           "prudence": ("Une zone n'est qu'un repère et une probabilité n'est pas une décision : attendre la publication, "
                                        "puis la réaction confirmée du marché, avant d'envisager quoi que ce soit."),
                           "sources": v9.sources(e)}
    # ordre des sections du jour
    sections = [("exec", "exec", "Synthèse exécutive", "Ce qu'il faut retenir en une minute", "Synthèse exécutive"),
                ("marches", "marches", "Vue d'ensemble des marchés financiers", "Tableau de bord macro et lecture par classe d'actifs", "Marchés")]
    for p in pays:
        dev = p.get("devise")
        if not dev:
            continue
        sections.append((f"pays_{dev}", "etats_unis" if dev == "USD" else "pays", p["titre"],
                         " · ".join(p["raisons"][:2]) or "actualité du jour", PAYS[dev]))
    if autres:
        sections.append(("commune", "commune", faits["commune"].get("titre", "Autres devises"), "Devises sans actualité forte aujourd'hui", "Autres devises"))
    sections += [("energie", "energie", "Énergie et géopolitique", "Brent et WTI datés, actualités, effets", "Énergie"),
                 ("actions", "actions", "Actions, technologie et sentiment de marché", "Transmission vers les devises", "Actions et sentiment"),
                 ("calendrier", "calendrier", "Calendrier économique", "Aujourd'hui et semaine prochaine · heures de Paris", "Calendrier"),
                 ("classement", "classement", "Classement des devises", "Force relative calculée en Python et divergences", "Classement"),
                 ("paires", "paires", "Les paires à surveiller", "Biais conditionnel, arguments, catalyseur et risque", "Paires"),
                 ("scenarios", "scenarios", "Scénarios pour les prochains jours", "Conditions vérifiées en Python à chaque run", "Scénarios"),
                 ("methode", "methode", "Méthode d'exécution", "Unités de temps, confirmations, types de risque", "Méthode"),
                 ("conclusion", "conclusion", "Conclusion : les priorités", "Biais général, paires, indicateurs à suivre", "Conclusion")]
    lundi, vendredi = v9.semaine(aujourd)
    s = {"genere_le": maintenant.isoformat(timespec="seconds"), "date": aujourd.isoformat(), "version": "quotidienne", "structure": "v9.4",
         "titre": "Rapport macroéconomique et Forex",
         "semaine": f"Semaine du {lundi.day} au {vendredi.day} {v9.MOIS[vendredi.month - 1]}",
         "jour": jour_long(aujourd.isoformat()).capitalize() + f" {aujourd.year}", "faits": faits, "erreurs": erreurs, "mention": MENTION,
         "sections": [{"id": sid, "type": t, "numero": i + 1, "titre": titre, "sous_titre": sous, "court": court, "erreur": erreurs.get(sid)}
                      for i, (sid, t, titre, sous, court) in enumerate(sections)]}
    from core import redaction_v94
    s["textes"] = redaction_v94.textes_python(s)
    redaction_v94.nettoyer(s)
    s["redaction"] = {sec["id"]: {"par": "automatique", "libelle": "rédaction automatique"} for sec in s["sections"]}
    return s
