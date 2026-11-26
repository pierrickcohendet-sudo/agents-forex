"""Lot V12 : l'onglet « 8 engrenages » devient une analyse complète par moteur -> docs/data/moteurs_dossiers.json.

Pour chacun des 8 moteurs (noms, explications, questions et canaux : core/noms_moteurs.py) :
- état du thermomètre (calme, près du seuil, seuil franchi), direction, valeur datée ; si le seuil est franchi mais qu'aucune
  devise n'est touchée, la raison est écrite (aucune règle de la matrice ne relie ce signal aux devises aujourd'hui) ;
- analyse : introduction (secours Python en phrases complètes ici ; le modèle la reformule dans agents/agent_moteurs.py, avec
  contrôle des nombres), chiffres clés (tuiles des dossiers), « ce qu'il faut surveiller » ;
- actualités reliées : chaque titre collecté est classé sur 1 ou 2 moteurs par mots-clés français et anglais, avec la ligne
  « pourquoi ce titre compte » ; un titre ne compte qu'une fois par jour ;
- agenda relié (7 jours) : chaque publication rattachée à un moteur par une table de types, avec « ce qui pourrait changer » ;
- devises touchées : effet (soutien, pression, neutre, non mesuré avec sa raison), pourquoi (règle et chiffre), comment
  (canal adapté à la devise), réaction possible du pays structurée (acteur, levier, déclencheur, date, source), prochain
  rendez-vous ; pied de page des manques par moteur.
Tout est calculé en Python, sans réseau : on relit les JSON publiés (dossiers, agenda, synthèse, paires) et le cache des titres.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import noms_moteurs as nm
from core import seuils as seuils_mod
from core.actualites import SOURCES as SOURCES_MEDIAS

log = logging.getLogger(__name__)

DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
HORIZON_JOURS = 7
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def _lire(p: Path) -> dict:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sans_accent(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(c) != "Mn")


def ddm(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso and len(iso) >= 10 else "n/d"


def fr(v, d: int = 2) -> str:
    if v is None:
        return "n/d"
    s = f"{abs(v):,.{d}f}".replace(",", " ").replace(".", ",")
    return ("−" if v < 0 else "") + s


# ------------------------------------------------------------------ 1. classement des titres par mots-clés (FR + EN)
MOTS_CLES: dict[int, list[str]] = {
    1: [r"risk[- ]?(off|on)", r"appetit pour le risque", r"aversion au risque", r"safe[- ]haven", r"recession", r"stagflation",
        r"soft landing", r"atterrissage",
        # Lot V14 (V13.1) : synthèses de marché (« wrap ») et humeur générale du marché -> moteur 1
        r"\bwrap\b", r"market news", r"risk (appetite|sentiment|assets)", r"broad-based", r"short covering", r"sell-?off",
        r"markets? (rebound|tumble|slide|rally|rallies|fall|drop)", r"global markets", r"bilan des marches", r"tour des marches"],
    2: [r"\bfed\b", r"fomc", r"\becb\b", r"\bbce\b", r"\bboe\b", r"\bboj\b", r"\brba\b", r"\brbnz\b", r"\bboc\b", r"\bsnb\b", r"\bbns\b",
        r"\bpboc\b", r"central bank", r"banque centrale", r"rate (cut|hike|decision)s?", r"\b(cut|hike)s? rates?", r"interest rates?",
        r"taux directeur", r"baisse de taux", r"hausse de taux", r"powell", r"warsh", r"lagarde", r"bailey", r"ueda", r"macklem",
        r"bullock", r"schlegel", r"monetary policy", r"politique monetaire", r"\byields?\b.*\b2-year", r"treasury yields?"],
    3: [r"\bcpi\b", r"\bppi\b", r"\bpce\b", r"inflation", r"payrolls?", r"\bnfp\b", r"jobs report", r"unemployment", r"chomage", r"jobless",
        r"\bgdp\b", r"\bpib\b", r"\bpmi\b", r"retail sales", r"ventes au detail", r"consumer (confidence|sentiment)", r"industrial production",
        r"housing starts", r"durable goods", r"economic data", r"donnees economiques", r"beats? (expectations|forecasts?)",
        r"miss(es|ed)? (expectations|forecasts?)", r"consensus"],
    4: [r"budget", r"deficit", r"\bdebt\b", r"\bdette\b", r"treasury auction", r"adjudication", r"bond auction", r"fiscal",
        r"shutdown", r"debt ceiling", r"plafond de la dette", r"credit rating", r"downgrade", r"moody", r"fitch", r"s&p global ratings",
        r"\bgilts?\b", r"spending bill", r"tax (cut|bill|plan)", r"\bimpots?\b", r"term premium", r"prime de terme"],
    5: [r"\bstocks?\b", r"equities", r"\bactions?\b", r"s&p 500", r"nasdaq", r"\bdow\b", r"wall street", r"\bvix\b", r"volatility",
        r"\bgold\b", r"\bor\b(?= |,)", r"10-year", r"bond (market|yields?)", r"\bipo\b", r"earnings", r"resultats trimestriels",
        r"\bshares?\b", r"commodit", r"copper", r"cuivre", r"bitcoin", r"crypto"],
    6: [r"sanctions?", r"\bwar\b", r"\bguerre\b", r"conflict", r"conflit", r"missile", r"\bstrikes?\b(?! price)", r"attack", r"attaque",
        r"ceasefire", r"cessez-le-feu", r"election", r"\bvote\b", r"geopolit", r"\biran\b", r"israel", r"ukraine", r"russia", r"russie",
        r"taiwan", r"north korea", r"coree du nord", r"middle east", r"moyen-orient", r"tensions?", r"military", r"militaire"],
    7: [r"\bcot\b", r"commitments of traders", r"positioning", r"positionnement", r"speculat", r"net (long|short)s?",
        r"technical", r"technique", r"overbought", r"oversold", r"surachat", r"survente", r"moving average", r"moyenne mobile",
        r"breakout", r"cassure", r"resistance", r"support level", r"\brsi\b", r"momentum", r"trend"],
    8: [r"\boil\b", r"crude", r"\bbrent\b", r"\bwti\b", r"petrole", r"\bbrut\b", r"opec", r"\bopep\b", r"\beia\b", r"inventor(y|ies)",
        r"stocks de brut", r"tariffs?", r"droits de douane", r"trade (balance|deficit|surplus|war|deals?|talks|agreements?)", r"free trade", r"accord commercial", r"balance commerciale",
        r"exports?", r"imports?", r"exportations?", r"importations?", r"shipping", r"supply chain", r"\blng\b", r"natural gas", r"\bgaz\b",
        r"chips? (sales|exports)", r"semiconductor exports"],
}
_MOTIFS = {n: [re.compile(m) for m in ms] for n, ms in MOTS_CLES.items()}
# Indices régionaux de la Fed (Philly Fed, Empire State…) : des chiffres économiques, pas une décision de banque centrale
_INDICES_FED = re.compile(r"(philly|philadelphia|richmond|kansas city|dallas|new york|chicago) fed( manufacturing| business| index)?|empire state")
MOTS_CLES[3] += [r"manufacturing index", r"jobless claims", r"claims",
                 # lot V14 (V13.1)
                 r"economy (unexpectedly )?(contracts|shrinks|grows|expands)", r"economic sentiment", r"\bzew\b", r"\bifo\b",
                 r"house prices", r"\bpsi\b", r"\bvs\b.{0,20}\bexpected\b"]
MOTS_CLES[1] += [r"global economy", r"\bimf\b", r"\bfmi\b"]
MOTS_CLES[6] += [r"\bsummit\b", r"\bsommet\b"]
_MOTIFS[1] = [re.compile(m) for m in MOTS_CLES[1]]
_MOTIFS[6] = [re.compile(m) for m in MOTS_CLES[6]]
_MOTIFS[3] = [re.compile(m) for m in MOTS_CLES[3]]
POURQUOI_TITRE = {
    1: "change le récit du marché (peur ou confiance), donc la direction des capitaux entre devises de refuge et de risque",
    2: "touche aux décisions ou au ton des banques centrales, donc aux anticipations de taux et aux écarts de rendement",
    3: "porte sur un chiffre économique : une surprise déplace les anticipations de la banque centrale",
    4: "concerne les budgets, la dette ou les adjudications : la prime de risque du pays peut bouger",
    5: "concerne les actions, les taux longs, l'or ou la volatilité, qui se transmettent aux devises exposées",
    6: "signale un risque géopolitique : flux de refuge et prix de l'énergie peuvent réagir",
    7: "concerne la tendance des prix ou les positions des spéculateurs : risque de débouclage",
    8: "concerne le pétrole ou le commerce extérieur : demande de devise des exportateurs et des importateurs",
}


def classer_titre(titre: str, resume: str = "") -> list[int]:
    """1 ou 2 moteurs, du plus au moins cité (mots-clés FR et EN, accents ignorés) ; [] si aucun motif.
    Lot V14 (V13.1) : un moteur trouvé dans le titre l'emporte ; le résumé ne départage ou ne complète que si le titre
    ne contient aucun mot-clé (avant, « Trump: Secured two new trade deals » recevait aussi le moteur 2 par son résumé)."""
    t = _INDICES_FED.sub(" manufacturing index ", _sans_accent(f"{titre} {resume or ''}"))
    titre = _INDICES_FED.sub(" manufacturing index ", _sans_accent(titre))
    scores, dans_titre = [], set()
    for n, motifs in _MOTIFS.items():
        k = sum(1 for m in motifs if m.search(t))
        if k:
            if any(m.search(titre) for m in motifs):
                dans_titre.add(n)
            scores.append((-k - (2 if n in dans_titre else 0), n))
    if dans_titre:
        scores = [x for x in scores if x[1] in dans_titre]
    ordre = [n for _, n in sorted(scores)]
    if SYNTHESE.search(titre):   # synthèse de marché : le récit d'ensemble (moteur 1) d'abord
        ordre = [1] + [n for n in ordre if n != 1]
    return ordre[:2]


SYNTHESE = re.compile(r"\bwrap\b|market news|tour des marches|bilan des marches")


# Lot V14 (V13.1) : titre sur une entreprise isolée (action, rachat, introduction en Bourse, dirigeant) sans mot-clé macro
_ENTREPRISE = re.compile(r"\bshares?\b|\bstock (jumps|soars|surges|falls|drops|slides|plunges|rallies|rises|sinks)|\bto buy\b|"
                         r"\bacquir|\bacquisition|\bbuyback|\bceo\b|\bipo\b|\bsubsidiary\b|\bearnings\b|\bpremarket\b|"
                         r"\bstartup\b|\bchipmaker\b|\bdrugmaker\b|\boffering\b")
_MARCHE_LARGE = re.compile(r"\bmarkets?\b|\bindex|\bindices\b|s&p 500|nasdaq|\bdow\b|wall street|\bfutures\b|\bequities\b|"
                           r"\bstocks (fall|rise|rally|slide|drop|tumble)|sell-?off|\bsector\b|\bwrap\b")


def entreprise_isolee(titre: str) -> bool:
    """Vrai si le titre ne parle que d'une entreprise (Zscaler, SpaceX / Cursor…) : aucun mot-clé des moteurs macro
    (1 à 4, 6, 8) dans le titre et aucun marché d'ensemble (indice, Bourse, contrats à terme)."""
    t = _sans_accent(titre)
    if not _ENTREPRISE.search(t) or _MARCHE_LARGE.search(t):
        return False
    return not any(m.search(t) for n in (1, 2, 3, 4, 6, 8) for m in _MOTIFS[n])


def reclasser(t: dict) -> list[int]:
    """Moteurs d'un titre déjà collecté, avec les règles du jour (titre seul : le résumé n'est pas gardé en cache).
    Flux officiel spécialisé : son moteur reste en premier. [] : titre écarté."""
    titre = str(t.get("titre") or "")
    if SANS_PORTEE.search(titre) or entreprise_isolee(titre):
        return []
    m = classer_titre(titre, t.get("resume") or "") or [int(x) for x in (t.get("moteurs") or [])][:2]
    if t.get("officiel") and t.get("moteurs"):
        premier = int(t["moteurs"][0])
        m = [premier] + [x for x in m if x != premier][:1]
    return m


# Titres sans portée de marché (concours, prix, journées portes ouvertes, offres d'emploi, nominations de personnel)
SANS_PORTEE = re.compile(r"challenge winners|announces? (the )?winners|\bawards?\b|prize|competition|open day|job (opening|vacanc)|"
                         r"career|internship|scholarship|recrutement|concours|webinar|podcast|museum|exhibition", re.I)


def titres_classes(articles: list[dict], jour: str) -> list[dict]:
    """Titres du jour (ou de la veille au soir), sans doublon, classés sur 1 à 2 moteurs."""
    vus, sortie = set(), []
    for a in articles or []:
        titre = str(a.get("titre") or "").strip()
        if SANS_PORTEE.search(titre):
            continue
        cle = re.sub(r"\W+", " ", _sans_accent(titre)).strip()
        if not titre or cle in vus:
            continue
        vus.add(cle)
        if entreprise_isolee(titre):   # lot V14 (V13.1)
            continue
        moteurs = classer_titre(titre, a.get("resume") or "")
        mf = a.get("moteur_flux")
        if mf in MOTS_CLES and a.get("classement") == "flux":   # flux spécialisé : son moteur d'abord, les mots-clés peuvent en ajouter un second
            moteurs = [int(mf)] + [n for n in moteurs if n != int(mf)][:1]
        if not moteurs:
            continue
        sortie.append({"titre": titre, "lien": a.get("lien"), "source": a.get("source_nom") or SOURCES_MEDIAS.get(a.get("source"), a.get("source")), "date": a.get("date"),
                       "officiel": bool(a.get("officiel")), "licence": a.get("licence"),
                       "moteurs": moteurs, "pourquoi": {str(n): POURQUOI_TITRE[n] for n in moteurs}})
    return sortie


# ------------------------------------------------------------------ 2. agenda : table de types -> moteur
def moteur_publication(e: dict) -> int:
    """Décision, discours, procès-verbal -> banques centrales ; inflation, emploi, PIB, PMI -> chiffres économiques ;
    adjudication, budget -> dette ; stocks de pétrole, balance commerciale, OPEP -> commerce et flux."""
    t = _sans_accent(f"{e.get('evenement') or ''} {e.get('evenement_en') or ''}")
    typ = _sans_accent(e.get("type") or "")
    if re.search(r"opep|opec|crude|petrole|brut|balance commerciale|trade balance|current account|compte courant|exportations|importations|imports|exports", t):
        return 8
    if typ in ("adjudication",) or re.search(r"auction|adjudication|budget|deficit|dette|debt|fiscal|borrowing|emprunt|besoin de financement", t):
        return 4
    if typ in ("reunion bc", "discours", "proces-verbal") or re.search(
            r"rate decision|decision|speaks|discours|minutes|proces-verbal|deliberations|statement|press conference|conference de presse|"
            r"monetary policy|politique monetaire|\blpr\b|cash rate|bank rate|official bank rate|fomc|taux directeur", t):
        return 2
    return 3


def ce_qui_pourrait_changer(e: dict, n: int, banques: dict) -> str:
    dev = e.get("devise")
    bq = (banques.get(dev) or {}).get("banque") or "la banque centrale"
    if n == 2:
        if _sans_accent(e.get("type")) == "discours":
            return f"un ton plus restrictif ou plus accommodant que prévu déplacerait les anticipations de taux de {bq}"
        return f"une décision ou un communiqué différent du consensus changerait l'écart de taux de la {dev}"
    if n == 3:
        return f"une surprise face au consensus déplacerait les anticipations de {bq}"
    if n == 4:
        return "une demande faible ou un taux plus élevé que prévu ferait monter la prime de risque"
    if n == 8:
        return "une surprise sur l'offre de pétrole ou les échanges changerait la demande de devise des exportateurs"
    return "à surveiller pour ce moteur"


def agenda_relie(agenda: dict, aujourd: date, banques: dict, maintenant: datetime | None = None) -> list[dict]:
    fin = (aujourd + timedelta(days=HORIZON_JOURS)).isoformat()
    sortie = []
    for j in agenda.get("jours") or []:
        for e in j.get("evenements") or []:
            d = e.get("date_paris") or ""
            if not (aujourd.isoformat() <= d <= fin):
                continue
            utile = e.get("impact") in ("moyen", "fort") or e.get("type") in ("Réunion BC", "Adjudication", "Grand rendez-vous")
            if not utile or e.get("devise") not in DEVISES:
                continue
            n = moteur_publication(e)
            sortie.append({"date": d, "heure": e.get("heure_paris"), "iso_utc": e.get("iso_utc"), "devise": e.get("devise"),
                           "evenement": e.get("evenement"), "type": e.get("type"), "impact": e.get("impact"), "consensus": e.get("consensus"),
                           "precedent": e.get("precedent"), "publie": e.get("publie"), "moteur": n,
                           "ce_qui_pourrait_changer": ce_qui_pourrait_changer(e, n, banques), "source": e.get("source"),
                           "passe": bool(maintenant and e.get("iso_utc") and e["iso_utc"] < maintenant.strftime("%Y-%m-%dT%H:%M+00:00"))})
    return sorted(sortie, key=lambda x: (x["date"], x["heure"] or ""))


# ------------------------------------------------------------------ 3. réaction possible du pays (structurée)
def _seuil(paire: str) -> dict | None:
    return next((s for s in seuils_mod.SEUILS if s["paire"] == paire), None)


def reactions(devise: str, n: int, effet: int, banques: dict, agenda: list[dict], cours: dict) -> list[dict]:
    """Liste de {acteur, levier, declencheur, date, source, lien} ; chaque élément vient d'une source publique."""
    out = []
    b = banques.get(devise)
    if devise == "JPY" and (n in (1, 2, 5, 7) or effet < 0):
        s = _seuil("USD/JPY")
        if s:
            c = cours.get("USD/JPY")
            out.append({"acteur": "ministère des Finances du Japon", "levier": "intervention sur le change (achat de yens)",
                        "declencheur": f"USD/JPY au-dessus de {fr(s['niveau'], 0)}" + (f" (cours {fr(c, 2)})" if c else ""),
                        "date": "à tout moment, sans calendrier publié", "source": s["source"], "lien": s.get("lien")})
    if devise == "CNY":
        out.append({"acteur": "banque centrale de Chine (PBoC)", "levier": "fixing quotidien du yuan et taux LPR",
                    "declencheur": "si le yuan s'écarte de la trajectoire voulue par les autorités",
                    "date": "chaque jour ouvré (fixing)" + (f" ; LPR le {ddm(b.get('prochaine'))}" if b and b.get("prochaine") else ""),
                    "source": "PBoC (pbc.gov.cn), fixing publié chaque jour ouvré", "lien": "http://www.pbc.gov.cn/en/3688006/index.html"})
    if b and n in (1, 2, 3) and devise != "CNY":
        insp = b.get("inflation"), b.get("cible")
        decl = (f"si l'inflation reste au-dessus de la cible ({fr(insp[0], 1)} % pour {fr(insp[1], 1)} %)" if insp[0] is not None and insp[1] is not None and insp[0] > insp[1]
                else f"si l'inflation repasse au-dessus de la cible de {fr(insp[1], 1)} % (aujourd'hui {fr(insp[0], 1)} %)" if insp[0] is not None and insp[1] is not None
                else "selon les prochains chiffres d'inflation et d'emploi")
        out.append({"acteur": b.get("banque"), "levier": "taux directeur et ton du communiqué", "declencheur": decl,
                    "date": f"prochaine décision le {ddm(b.get('prochaine'))}" if b.get("prochaine") else "n/d : date de la prochaine réunion absente",
                    "source": b.get("source") or "n/d", "lien": b.get("communique_lien")})
    if n == 4:
        bud = next((e for e in agenda if e["devise"] == devise and e["moteur"] == 4), None)
        out.append({"acteur": "gouvernement et ministère des Finances", "levier": "budget, calendrier des émissions de dette",
                    "declencheur": "si la prime de risque ou les taux longs montent fortement",
                    "date": f"{bud['evenement']} le {ddm(bud['date'])}" if bud else "n/d : aucune publication budgétaire dans l'agenda des 7 jours",
                    "source": bud["source"] if bud else "agenda ForexFactory (7 jours)", "lien": None})
    return out


# ------------------------------------------------------------------ 4. cases de la matrice -> effets par devise
RAISON_NON_MESURE = {
    ("GBP", 2): "pas de rendement 2 ans britannique gratuit et quotidien",
    ("CHF", 2): "pas de rendement 2 ans suisse gratuit et quotidien",
    ("CNY", 2): "pas de rendement 2 ans chinois gratuit",
    ("NZD", 2): "pas de rendement 2 ans néo-zélandais gratuit et quotidien",
}


def _raison_claire(t: str) -> str:
    t = nm.remplacer(str(t or ""))[0]
    t = re.sub(r"→ \+(\d) pour ([A-Z]{3}) \([^)]*\)", r"(soutien de \2)", t)
    t = re.sub(r"→ −(\d) pour ([A-Z]{3}) \([^)]*\)", r"(pression sur \2)", t)
    return t.replace("→ +1", "→ soutien").replace("→ −1", "→ pression").replace("→ +2", "→ soutien fort").replace("→ −2", "→ pression forte")


def effet_case(devise: str, n: int, case: dict | None) -> dict:
    if not case:
        return {"effet": "non mesuré", "valeur": None, "pourquoi": "n/d : case absente de la matrice d'impact", "raison_non_mesure": "matrice d'impact absente"}
    etat, v = case.get("etat"), case.get("valeur") or 0
    regles = case.get("regles") or []
    pourquoi = " ; ".join(f"{r.get('regle')} ({r.get('chiffre')}, {ddm(r.get('date'))}, {r.get('source')})" for r in regles) if regles else (case.get("raison") or "")
    if etat in ("nd", "sans_regle") and not v:
        raison = RAISON_NON_MESURE.get((devise, n)) or (case.get("raison") if etat == "nd" else None) or "aucune règle de la matrice ne relie ce moteur à cette devise"
        return {"effet": "non mesuré", "valeur": None, "pourquoi": _raison_claire(pourquoi or raison), "raison_non_mesure": _raison_claire(raison)}
    eff = "soutien" if v > 0 else "pression" if v < 0 else "neutre"
    from core import phrases_devises   # lot V15 : la règle brute devient une phrase (la règle reste dans « Règle de calcul »)
    try:
        phrase = phrases_devises.phrases_case(devise, regles) if regles and eff != "neutre" else None
    except Exception:  # noqa: BLE001
        phrase = None
    return {"effet": eff, "valeur": v, "pourquoi": _raison_claire(pourquoi or "sous les seuils de la matrice"), "raison_non_mesure": None,
            "pourquoi_phrase": phrase, "date": max((r.get("date") for r in regles if r.get("date")), default=None)}


# ------------------------------------------------------------------ 5. état, incohérence, introduction de secours
ETATS = {"franchi": "seuil franchi", "proche": "près du seuil", "non": "calme"}


def etat_moteur(th: dict | None, touchees: int) -> dict:
    th = th or {}
    e = {"etat": ETATS.get(th.get("etat"), "n/d"), "code": th.get("etat") or "nd", "libelle": th.get("libelle"), "valeur": th.get("texte_valeur"),
         "date": th.get("date"), "source": th.get("source"), "direction": (th.get("direction") or {}).get("libelle"),
         "classe": (th.get("direction") or {}).get("classe"), "note": th.get("note") or th.get("phrase"), "raison": th.get("raison")}
    if th.get("etat") == "franchi" and touchees == 0:   # le cas du moteur 8 du 20/11
        e["incoherence"] = (f"Seuil franchi sur « {th.get('libelle')} » ({th.get('texte_valeur')}), mais aucune règle de la matrice d'impact "
                            "ne relie ce signal aux devises aujourd'hui : le thermomètre décrit le marché, la matrice ne le traduit en effet "
                            "sur une devise que lorsque sa propre règle est remplie.")
    return e


def intro_python(n: int, etat: dict, touchees: list[dict], entete: dict, titres: int, rdv: list[dict], jour: str = "") -> str:
    """Introduction de secours en phrases complètes, chiffres et dates repris des faits."""
    nom = nm.nom(n)
    if n == 1 and entete.get("titre"):
        p = [f"Le thème dominant du {ddm(etat.get('date'))} est « {entete['titre']} » : {entete.get('alignes', 'n/d')} moteurs sur {entete.get('evaluables', 'n/d')} vont dans son sens."]
    elif etat.get("valeur") is not None:
        p = [f"{nom} : le thermomètre « {etat.get('libelle')} » est à {etat.get('valeur')} au {ddm(etat.get('date'))}, soit {etat.get('etat')}"
             + (f", direction {etat['direction'].lower()}" if etat.get("direction") else "") + "."]
    else:
        p = [f"{nom} : thermomètre n/d ({etat.get('raison') or 'mesure absente'})."]
    sout = [t["devise"] for t in touchees if t["effet"] == "soutien"]
    pres = [t["devise"] for t in touchees if t["effet"] == "pression"]
    if sout or pres:
        p.append(f"Au {ddm(jour)}, ce moteur " + " et ".join(x for x in [f"soutient {', '.join(sout)}" if sout else "", f"pèse sur {', '.join(pres)}" if pres else ""] if x) + ".")
    elif etat.get("incoherence"):
        p.append(f"Le seuil est franchi, mais au {ddm(jour)} aucune devise n'est touchée par les règles de la matrice.")
    else:
        p.append(f"Au {ddm(jour)}, il ne pousse aucune devise au-delà de ses seuils.")
    if rdv:
        r = rdv[0]
        p.append(f"Prochain rendez-vous lié : {r['evenement']} ({r['devise']}, {ddm(r['date'])} à {r['heure'] or 'heure n/d'})"
                 + (f", {titres} titre{'s' if titres > 1 else ''} du jour classé{'s' if titres > 1 else ''} sur ce moteur." if titres else "."))
    elif titres:
        p.append(f"{titres} titre{'s' if titres > 1 else ''} du {ddm(jour)} {'sont classés' if titres > 1 else 'est classé'} sur ce moteur.")
    return " ".join(p)


def _prochain_lie(ag: list[dict]) -> str | None:
    if not ag:
        return None
    e = ag[0]
    return f"Prochain rendez-vous lié : {e['evenement']} ({e['devise']}, {JOURS[date.fromisoformat(e['date']).weekday()]} {ddm(e['date'])} {e['heure'] or ''})".strip()


def _tuile(t: dict) -> dict:
    pts = [v for _, v in ((t.get("courbe") or {}).get("points") or [])][-60:]
    return {"libelle": t.get("libelle"), "texte": t.get("texte") or ("n/d" if t.get("valeur") is None else str(t.get("valeur"))),
            "variation": (t.get("variation") or {}).get("texte"), "date": t.get("date"), "source": t.get("source"),
            "percentile_5a": t.get("percentile_5a"), "raison": t.get("raison"), "lecture": t.get("lecture"), "points": pts}


# ------------------------------------------------------------------ 6. calcul complet
def calculer(docs_data: Path, cache: Path, aujourd: date | None = None, maintenant: datetime | None = None) -> dict:
    docs_data, cache = Path(docs_data), Path(cache)
    dossiers, agenda = _lire(docs_data / "dossiers.json"), _lire(docs_data / "agenda.json")
    synthese, paires_j = _lire(docs_data / "synthese.json"), _lire(docs_data / "paires.json")
    news = _lire(cache / "collecte_news.json")
    aujourd = aujourd or date.fromisoformat((agenda.get("aujourdhui") or datetime.now(timezone.utc).date().isoformat())[:10])
    banques = {b["devise"]: b for b in (((synthese.get("faits") or {}).get("banques") or {}).get("banques") or [])}
    cours = {p: ((f.get("cours_jour") or {}).get("cours") or (f.get("technique") or {}).get("cours")) for p, f in (paires_j.get("fiches") or {}).items()}
    lignes = {l["devise"]: {c["engrenage"]: c for c in l.get("cases") or []} for l in ((dossiers.get("matrice_impact") or {}).get("lignes") or [])}
    cockpit = dossiers.get("cockpit") or {}
    thermos = {t["numero"]: t for t in cockpit.get("thermometres") or []}
    entete = cockpit.get("entete") or {}
    titres = titres_classes(((news.get("donnees") or {}).get("articles") or []), aujourd.isoformat())
    maintenant = maintenant or datetime.now(timezone.utc)
    rdv = agenda_relie(agenda, aujourd, banques, maintenant)
    a_venir = [e for e in rdv if not e["passe"]]
    prochain = {d: next((e for e in a_venir if e["devise"] == d), None) for d in DEVISES}

    moteurs, manques = {}, {}
    matrice = {"devises": DEVISES, "cases": {}, "solde": {}}
    for d in DEVISES:
        matrice["cases"][d] = []
        for n in range(1, 9):
            c = (lignes.get(d) or {}).get(n)
            e = effet_case(d, n, c)
            matrice["cases"][d].append({"v": e["valeur"], "effet": e["effet"], "pourquoi": e["pourquoi"]})
        matrice["solde"][d] = sum(x["v"] or 0 for x in matrice["cases"][d])
    for n in range(1, 9):
        devs = []
        for d in DEVISES:
            e = effet_case(d, n, (lignes.get(d) or {}).get(n))
            v = e["valeur"] or 0
            devs.append({"devise": d, **e, "comment": nm.canal(n, d), "reactions": reactions(d, n, v, banques, rdv, cours),
                         "prochain_rdv": prochain[d] and {k: prochain[d][k] for k in ("date", "heure", "evenement", "impact")}})
        ordre = {"soutien": 0, "pression": 0, "neutre": 1, "non mesuré": 2}
        devs.sort(key=lambda x: (ordre[x["effet"]], -abs(x["valeur"] or 0), DEVISES.index(x["devise"])))
        touchees = [x for x in devs if x["effet"] in ("soutien", "pression")]
        etat = etat_moteur(thermos.get(n), len(touchees))
        tit = [t for t in titres if n in t["moteurs"]]
        ag = [e for e in rdv if e["moteur"] == n or (n == 1 and e["impact"] == "fort")]
        dos = (dossiers.get("engrenages") or {}).get(str(n)) or {}
        surveiller = [x for x in [f"Seuil du thermomètre : {etat['note']}" if etat.get("note") else None,
                                  *[nm.remplacer(x)[0] for x in (dos.get("notes") or [])[:2]],
                                  _prochain_lie([e for e in ag if not e["passe"]])] if x]
        manques[str(n)] = [{"devise": x["devise"], "raison": x["raison_non_mesure"]} for x in devs if x["effet"] == "non mesuré"]
        moteurs[str(n)] = {
            "numero": n, "nom": nm.nom(n), "explication": nm.explication(n), "question": nm.QUESTIONS[n], "canal": nm.CANAUX[n],
            "etat": etat, "touchees": len(touchees),
            "analyse": {"introduction": intro_python(n, etat, touchees, entete, len(tit), [e for e in ag if not e["passe"]], aujourd.isoformat()), "redige_par": "python",
                        "chiffres_cles": [_tuile(t) for t in dos.get("tuiles") or []], "surveiller": surveiller},
            "actualites": tit, "agenda": ag, "devises": devs, "manques": manques[str(n)],
        }
    return {"date": aujourd.isoformat(), "genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "moteurs": moteurs, "matrice": matrice, "manques": manques, "theme": {k: entete.get(k) for k in ("titre", "alignes", "evaluables", "explication")},
            "sources": {"matrice": "matrice d'impact (dossiers.json, règles Python de config.yaml)", "thermometres": "cockpit des dossiers (dossiers.json)",
                        "actualites": "flux RSS collectés (data/cache/collecte_news.json), classés par mots-clés",
                        "agenda": "agenda.json (ForexFactory), 7 jours", "banques": "synthese.json (faits des banques centrales)",
                        "seuils": "core/seuils.py (sources officielles)"},
            "note": "Aide à la décision : effets mesurés par des règles Python ; « non mesuré » donne toujours sa raison."}


def ecrire(racine: Path, aujourd: date | None = None, intros: dict | None = None, maintenant: datetime | None = None) -> dict | None:
    """Écrit docs/data/moteurs_dossiers.json ; `intros` = introductions du modèle déjà contrôlées {n: (texte, par)}."""
    racine = Path(racine)
    d = calculer(racine / "docs" / "data", racine / "data" / "cache", aujourd, maintenant)
    for n, (texte, par) in (intros or {}).items():
        if str(n) in d["moteurs"] and texte:
            d["moteurs"][str(n)]["analyse"].update({"introduction": texte, "redige_par": par, "secours_python": d["moteurs"][str(n)]["analyse"]["introduction"]})
    (racine / "docs" / "data" / "moteurs_dossiers.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return d
