"""Noms affichés des 8 moteurs du marché (lot V10, A) : définis UNE fois ici, réutilisés partout (Python, modèle, site).

Le mot « engrenage » et la numérotation ne restent que dans l'onglet « 8 engrenages ». Ailleurs : « 4 moteurs sur 8
favorisent l'AUD : banques centrales et taux, chiffres économiques… », avec l'explication courte à la première mention.
Filet de sécurité : `nettoyer_publication()` remplace, dans les JSON publiés (hors fichiers de l'onglet dédié), toute
occurrence restante et renvoie le décompte pour le récapitulatif du run.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# n -> (nom affiché, explication courte). Explications 7 et 8 ajustées au contenu réel des dossiers (dossier 7 : tendance,
# RSI, moyennes mobiles, volatilité, COT ; dossier 8 « Offre et demande » : balances commerciales, stocks et production de
# pétrole EIA).
MOTEURS = {
    1: ("Thème dominant", "le grand récit du marché du moment (inflation, croissance, risque)"),
    2: ("Banques centrales et taux", "décisions, ton et anticipations de taux directeurs"),
    3: ("Chiffres économiques", "publications au-dessus ou en dessous du consensus"),
    4: ("Budgets et dette publique", "déficits, émissions de dette, risque souverain"),
    5: ("Liens entre marchés", "taux longs, actions, matières premières, volatilité"),
    6: ("Géopolitique", "conflits, sanctions, élections, chocs d'offre"),
    7: ("Prix et positionnement", "tendance des prix, positions des spéculateurs (COT)"),
    8: ("Commerce et flux", "balances commerciales, offre et demande de pétrole"),
}
# Lot V12 : la question à laquelle répond chaque moteur, et son canal de transmission général vers les devises.
QUESTIONS = {
    1: "Quel récit domine le marché, et les autres moteurs vont-ils dans son sens ?",
    2: "Qui monte ou baisse ses taux, et comment évolue l'écart de rendement entre pays ?",
    3: "Les chiffres publiés surprennent-ils au-dessus ou en dessous des attentes ?",
    4: "Les déficits et la dette publique inquiètent-ils les investisseurs ?",
    5: "Que disent les taux longs, les actions, l'or, le pétrole et la volatilité ?",
    6: "Quels conflits, sanctions ou élections peuvent provoquer un choc ?",
    7: "Où en sont la tendance des prix et les positions des spéculateurs ?",
    8: "Que disent le commerce extérieur et le marché du pétrole ?",
}
CANAUX = {
    1: "Le régime de risque déplace les capitaux : vers USD, JPY et CHF quand le marché a peur, vers AUD, NZD et CAD quand il a confiance.",
    2: "Un écart de taux qui s'élargit attire les capitaux de portage vers la devise la mieux rémunérée ; une banque centrale plus restrictive que prévu soutient sa devise.",
    3: "Une surprise change ce que le marché attend de la banque centrale, donc l'écart de taux et la devise.",
    4: "Un dérapage budgétaire fait monter la prime de risque du pays et peut faire fuir les investisseurs étrangers.",
    5: "Les mouvements des actions, des taux longs et des matières premières se transmettent aux devises qui y sont exposées.",
    6: "Un choc crée des flux de refuge et renchérit l'énergie des pays importateurs.",
    7: "Une tendance installée attire les suiveurs ; des positions extrêmes rendent la devise vulnérable à un débouclage brutal.",
    8: "Le pétrole et la balance commerciale changent la demande de devise des exportateurs et des importateurs.",
}
# Canal adapté à la devise (sinon le canal général du moteur)
CANAUX_DEVISE = {
    "JPY": {2: "Portage : quand l'écart de taux avec le Japon s'élargit, emprunter en yen pour placer ailleurs rapporte davantage, ce qui pèse sur le yen ; le ministère des Finances peut intervenir si la baisse devient brutale.",
            1: "Refuge : le yen est racheté quand le marché a peur (débouclage du portage).",
            5: "Le yen suit la volatilité des actions : une hausse du VIX déclenche des rachats de yen."},
    "CHF": {1: "Refuge : le franc est recherché quand le marché a peur ; la BNS peut intervenir pour freiner sa hausse.",
            6: "Refuge : un conflit attire les capitaux vers le franc."},
    "CAD": {8: "Pétrole : le Canada exporte du brut, un baril plus cher soutient le dollar canadien ; la balance commerciale suit.",
            5: "Pétrole et actions américaines : le CAD suit le Brent et l'appétit pour le risque."},
    "AUD": {5: "Matières premières et Chine : l'AUD suit les métaux, les actions et la croissance chinoise.",
            1: "Devise de risque : l'AUD baisse quand le marché a peur."},
    "NZD": {1: "Devise de risque : le NZD baisse quand le marché a peur.", 8: "Exportations agricoles : la balance commerciale pèse sur le NZD."},
    "NOK": {8: "Pétrole."},
    "USD": {1: "Monnaie de réserve : la demande de dollars monte avec le stress (financements, couvertures).",
            2: "Écart de taux : des taux américains plus hauts que ceux des autres attirent les capitaux vers le dollar.",
            4: "Prime de terme : un dérapage budgétaire américain peut faire monter les taux longs sans soutenir le dollar."},
    "EUR": {8: "Facture énergétique : la zone euro importe son énergie, un pétrole cher pèse sur sa balance et sur l'euro.",
            4: "Écarts de dette entre pays (Italie − Allemagne) : une tension souveraine pèse sur l'euro."},
    "GBP": {4: "Crédibilité budgétaire : un dérapage fait monter les gilts et peut faire baisser la livre (2022).",
            3: "La livre réagit fortement aux surprises d'inflation et d'emploi, qui déplacent les anticipations de la BoE."},
    "CNY": {2: "Change piloté : la PBoC oriente le yuan par le fixing quotidien ; les écarts de taux jouent moins qu'ailleurs.",
            8: "Excédent commercial : les exportations chinoises soutiennent la demande de yuan, les droits de douane la réduisent."},
}


# Lot V13 : « Comprendre ce moteur », texte PERMANENT écrit à la main (jamais généré), relu une fois par trimestre.
# importance pour le change (1 à 5 étoiles), pourquoi il compte, indicateurs principaux, chaîne de transmission (étapes ->
# devise), 3 confluences avec les marchés (signal, sens ▲ ▼ ou !, effet), piège à éviter.
COMPRENDRE = {
    1: {"importance": 5,
        "pourquoi": "C'est le chef d'orchestre : il dit quel récit domine (peur ou confiance, inflation ou croissance) et donc quelles "
                    "devises sont recherchées. Quand il est clair, les autres moteurs comptent moins et les paires bougent ensemble ; "
                    "quand il est flou, chaque paire suit ses propres chiffres.",
        "indicateurs": ["VIX : la peur sur les actions américaines (au-dessus de 25, régime de stress)",
                        "S&P 500 et Nasdaq : l'appétit pour le risque",
                        "Indice dollar large : la demande mondiale de dollars",
                        "Or : la recherche de protection contre l'inflation et les crises",
                        "Nombre de moteurs alignés : la solidité du thème (3 sur 7 = thème établi)"],
        "chaine": ["Choc ou bonne nouvelle", "Régime de risque", "Flux vers refuges ou devises cycliques", "USD, JPY, CHF ↔ AUD, NZD, CAD"],
        "confluences": [["VIX en hausse", "▲", "USD, JPY et CHF recherchés ; AUD, NZD et CAD vendus"],
                        ["Actions en hausse avec un dollar ferme", "=", "avantage de rendement américain, pas une fuite vers la sécurité"],
                        ["Or et dollar en hausse ensemble", "!", "stress profond : tout ce qui est perçu comme sûr est acheté"]],
        "piege": "Un thème peut se retourner en une publication. Le regarder chaque jour, sans le confondre avec une tendance de fond."},
    2: {"importance": 5,
        "pourquoi": "Les devises suivent d'abord l'argent : une devise mieux rémunérée attire les capitaux. Ce moteur mesure qui monte "
                    "ou baisse ses taux, et surtout ce que le marché anticipe, lu dans les taux à 2 ans.",
        "indicateurs": ["Taux directeurs (Fed, BCE, BoE, BoJ, BoC, RBA, RBNZ, BNS)",
                        "Rendement à 2 ans : ce que le marché attend des banques centrales sur 2 ans",
                        "Écart de taux à 2 ans entre deux pays : le moteur du portage",
                        "Taux réel (directeur − inflation sous-jacente) : le vrai niveau de restriction",
                        "Pente 10 ans − 2 ans : l'inquiétude sur la croissance",
                        "Probabilités de décision citées par la presse"],
        "chaine": ["Inflation ou emploi plus forts", "Banque centrale plus restrictive attendue", "Taux à 2 ans en hausse",
                   "Écart de taux favorable", "Devise soutenue"],
        "confluences": [["2 ans US en hausse", "▲", "USD/JPY monte souvent avec lui (lien fort depuis 2022)"],
                        ["Taux réels US en hausse", "▼", "l'or recule, les refuges sans rendement aussi"],
                        ["Pente 2-10 ans qui se creuse", "!", "le marché craint une récession : prudence sur les devises cycliques"]],
        "piege": "Le marché anticipe : une hausse de taux déjà attendue ne fait pas monter la devise. Ce sont la surprise et le ton "
                 "qui comptent (cas de l'AUD après la hausse de la RBA du 03/11)."},
    3: {"importance": 4,
        "pourquoi": "Les chiffres économiques changent les anticipations de taux. Une inflation ou un emploi au-dessus du consensus "
                    "rendent la banque centrale plus restrictive, ce qui soutient la devise ; une déception fait l'inverse.",
        "indicateurs": ["Inflation : IPC, IPC sous-jacent, PCE (la mesure préférée de la Fed)",
                        "Emploi : emplois non agricoles, chômage, salaires",
                        "Activité : PIB, PMI, ventes au détail, enquêtes régionales (Fed de Philadelphie)",
                        "Indice de surprise sur 30 jours : la somme des écarts au consensus, en écarts habituels"],
        "chaine": ["Publication au-dessus du consensus", "Anticipations de taux revues en hausse", "Taux à 2 ans en hausse", "Devise soutenue"],
        "confluences": [["Surprises USD positives", "▲", "rendement 2 ans US en hausse dans les heures qui suivent"],
                        ["Emploi australien faible", "▼", "AUD fragilisé, surtout si les actions baissent aussi"],
                        ["Inflation forte, activité faible", "!", "stagflation : réaction ambiguë, souvent négative pour la devise"]],
        "piege": "Les révisions des mois précédents comptent autant que le chiffre du mois, et les séries volatiles (inscriptions "
                 "hebdomadaires au chômage) ne se lisent qu'en tendance."},
    4: {"importance": 3,
        "pourquoi": "Lent mais puissant : quand les investisseurs doutent des finances d'un pays, ils exigent une prime pour lui prêter. "
                    "Les taux longs montent sans que la devise en profite, comme au Royaume-Uni en 2022.",
        "indicateurs": ["Déficit et dette publics en % du PIB (FMI, annuel)",
                        "Adjudications : taux obtenu et demande (taux de couverture)",
                        "Rendement à 10 ans et prime de terme",
                        "Écarts souverains : Italie − Allemagne, France − Allemagne"],
        "chaine": ["Dérapage budgétaire", "Prime de risque", "Taux longs en hausse", "Fuite des investisseurs étrangers", "Devise sous pression"],
        "confluences": [["10 ans en hausse et devise en baisse", "!", "signal budgétaire, l'inverse d'un signal monétaire"],
                        ["Écart Italie − Allemagne qui s'élargit", "▼", "l'euro souffre de la fragmentation"],
                        ["Adjudication mal couverte", "▼", "tension sur les taux longs du pays"]],
        "piege": "Les données de dette arrivent avec un ou deux ans de retard : ce sont les taux longs et les adjudications qui "
                 "donnent l'alerte en temps réel."},
    5: {"importance": 4,
        "pourquoi": "Les devises ne vivent pas seules : actions, taux longs, or et pétrole leur transmettent leurs mouvements. Ce "
                    "moteur repère les liens actifs entre marchés et mesure leur force.",
        "indicateurs": ["VIX et S&P 500", "Rendement à 10 ans US", "Or (taux réels et refuge)", "Pétrole Brent et WTI",
                        "Corrélations sur 60 séances : AUD avec les actions, JPY avec le VIX"],
        "chaine": ["Mouvement d'un grand marché", "Lien de corrélation actif", "Devise exposée entraînée"],
        "confluences": [["Actions en baisse", "▼", "AUD et NZD vendus (lien AUD / S&P 500)"],
                        ["Pétrole en hausse", "▲", "CAD soutenu, JPY et EUR pénalisés (importateurs d'énergie)"],
                        ["VIX en hausse", "▲", "JPY et CHF recherchés"]],
        "piege": "Les corrélations changent de régime : un lien fort sur 60 séances peut disparaître en une semaine. Toujours "
                 "vérifier sa force actuelle avant de s'y fier."},
    6: {"importance": 3,
        "pourquoi": "Rare mais violent : conflits, sanctions et élections créent des flux de refuge et des chocs sur l'énergie. Le "
                    "marché réagit vite, puis s'habitue si l'offre réelle n'est pas touchée.",
        "indicateurs": ["Titres classés : énergie, sanctions, commerce, refuge, politique intérieure",
                        "Réaction du Brent, de l'or, d'USD/JPY et du franc suisse sur la dernière séance", "VIX"],
        "chaine": ["Événement géopolitique", "Peur et choc d'offre", "Refuge et énergie plus chère", "USD, CHF, JPY ↑ · importateurs ↓"],
        "confluences": [["Tension au Moyen-Orient", "▲", "Brent en hausse, CAD soutenu, JPY et EUR pénalisés"],
                        ["Sanctions ou droits de douane", "▼", "CNY, AUD et NZD exposés au commerce chinois"],
                        ["Élection incertaine", "▼", "devise du pays concerné sous pression jusqu'au résultat"]],
        "piege": "Le premier choc est souvent excessif : la réaction s'efface si l'offre n'est pas réellement touchée."},
    7: {"importance": 3,
        "pourquoi": "Le prix et les positions disent ce que le marché a déjà fait. Une devise très achetée par les spéculateurs "
                    "devient fragile : la moindre déception peut déclencher des ventes en cascade.",
        "indicateurs": ["Tendance : écart à la moyenne mobile 200 jours, RSI 14", "Volatilité réalisée sur 20 jours",
                        "COT : positions nettes des spéculateurs et leur percentile sur 5 ans (CFTC, chaque vendredi)"],
        "chaine": ["Positions extrêmes", "Déception ou surprise contraire", "Débouclage", "Mouvement violent"],
        "confluences": [["COT extrême et surprise contraire", "!", "mouvement brutal dans le sens du débouclage"],
                        ["RSI au-dessus de 70 sur l'USD", "▼", "risque de pause du dollar à court terme"],
                        ["Volatilité basse qui remonte", "!", "fin de période calme"]],
        "piege": "Un extrême peut durer des semaines : c'est un facteur de fragilité, pas un signal de retournement à lui seul."},
    8: {"importance": 2,
        "pourquoi": "Structurel : les échanges et l'énergie modifient la demande de devises des exportateurs et des importateurs. "
                    "Effets lents mais durables, surtout pour CAD, AUD, NZD, JPY et EUR.",
        "indicateurs": ["Prix du pétrole (Brent, WTI) et écart Brent − WTI", "Stocks et production de brut américains (EIA, hebdomadaire)",
                        "Balances commerciales", "Droits de douane et accords commerciaux"],
        "chaine": ["Pétrole ou commerce qui bouge", "Termes de l'échange", "Demande de la devise des exportateurs",
                   "CAD, AUD ↑ · JPY, EUR ↓ (si le pétrole monte)"],
        "confluences": [["Brent en hausse", "▲", "CAD soutenu"], ["Stocks de brut sous la moyenne de 5 ans", "▲", "soutien au prix du pétrole"],
                        ["Nouveaux droits de douane", "▼", "devises des exportateurs visés"]],
        "piege": "Un pétrole qui chute parce que la demande mondiale s'effondre pèse aussi sur les devises cycliques : pas de "
                 "lecture mécanique."},
}


def canal(n: int, devise: str | None = None) -> str:
    return (CANAUX_DEVISE.get(devise or "", {}) or {}).get(int(n)) or CANAUX[int(n)]


CONSIGNE_MODELE = (
    "Les huit moteurs du marché se nomment : " + ", ".join(f"« {v[0][0].lower() + v[0][1:]} »" for k, v in MOTEURS.items())
    + ". Cite-les par leur nom (en minuscules dans la phrase). Jamais le mot « engrenage », ni « engrenage » suivi d'un "
    "numéro, ni un numéro de moteur : un contrôle automatique remplace et signale ces mots.")
# Anciens libellés courts utilisés dans les textes (« 2. Monétaire », « engrenage 3 (données économiques) »)
COURTS = {"thème": 1, "monétaire": 2, "données": 3, "fiscale": 4, "marchés": 5, "géopolitique": 6, "flux": 7, "offre": 8}
# Fichiers propres à l'onglet « 8 engrenages » : le mot y reste
FICHIERS_ONGLET = {"dossiers.json", "dossiers_hebdo.json", "moteurs.json", "moteurs_dossiers.json", "documentaire.json"}
SOUS_ARBRES_ONGLET = {"engrenages"}


def nom(n: int, minuscule: bool = False) -> str:
    t = MOTEURS[int(n)][0]
    return t[0].lower() + t[1:] if minuscule else t


def explication(n: int) -> str:
    return MOTEURS[int(n)][1]


def avec_explication(n: int, minuscule: bool = True) -> str:
    return f"{nom(n, minuscule)} ({explication(n)})"


def liste_noms(numeros, minuscule: bool = True) -> str:
    ns = [nom(n, minuscule) for n in numeros]
    if len(ns) <= 1:
        return "".join(ns)
    return ", ".join(ns[:-1]) + " et " + ns[-1]


def decompte(contributions: list[dict]) -> dict:
    """Contributions d'une paire (+ vers la hausse de la paire) -> {pour, contre, neutres, noms_pour, noms_contre}."""
    pour = [c["engrenage"] for c in contributions if (c.get("contribution") or 0) > 0]
    contre = [c["engrenage"] for c in contributions if (c.get("contribution") or 0) < 0]
    return {"pour": len(pour), "contre": len(contre), "neutres": len(contributions) - len(pour) - len(contre),
            "noms_pour": [nom(n, True) for n in pour], "noms_contre": [nom(n, True) for n in contre]}


def de(devise: str) -> str:
    """« de l'AUD », « du GBP »."""
    return f"de l'{devise}" if devise[:1] in "AEIOUY" else f"du {devise}"


def texte_decompte(d: dict, devise: str | None = None) -> str:
    """« 4 moteurs pour, 0 contre » (+ « en faveur de l'AUD » si la devise est donnée)."""
    t = f"{d['pour']} moteur{'s' if d['pour'] > 1 else ''} pour, {d['contre']} contre"
    return t + (f" en faveur de {devise}" if devise else "")


# ------------------------------------------------------------------ remplacement des anciennes formulations
_IDENT = re.compile(r"^[#/\w.\-=:]*$")


def _maj(t: str, debut: bool) -> str:
    return t[0].upper() + t[1:] if debut and t else t


def remplacer(texte: str) -> tuple[str, int]:
    """Anciennes formulations -> noms affichés. Renvoie (texte, nombre de remplacements). Les identifiants et liens
    (« #engrenages/g=3 », « engrenages ») sont laissés tels quels."""
    if not isinstance(texte, str) or "ngrenage" not in texte or _IDENT.match(texte) or texte.startswith(("http", "#")):
        return texte, 0
    n = 0

    def sub(motif, rempl, t, flags=re.I):
        nonlocal n
        t2, k = re.subn(motif, rempl, t, flags=flags)
        n += k
        return t2

    def num(m):
        debut = m.start() == 0 or m.string[max(0, m.start() - 2):m.start()].strip() in (".", ":", "")
        return _maj(nom(int(m.group(1)), True), debut and m.start() == 0)
    t = texte
    t = sub(r"engrenages (\d) et (\d)", lambda m: f"{nom(int(m.group(1)), True)} et {nom(int(m.group(2)), True)}", t)
    t = sub(r"(?:de |l')?(?:l'|le dossier de l')?engrenage (\d)(?: \([^)]*\))?", num, t)
    t = sub(r"\bEngrenages orientés\b", "Moteurs orientés", t, 0)
    t = sub(r"\b([1-8])\. (Thème|Monétaire|Données|Fiscale|Marchés|Géopolitique|Flux|Offre)\b",
            lambda m: nom(int(m.group(1))), t, 0)
    t = sub(r"solde des engrenages", "solde des moteurs", t)
    t = sub(r"cet engrenage", "ce moteur", t)
    t = sub(r"un engrenage", "un moteur", t)
    t = sub(r"(\d+) engrenages? sur (\d+)", r"\1 moteurs sur \2", t)
    t = sub(r"engrenages? alignés?", "moteurs alignés", t)
    t = sub(r"\b(les |des |aux )?8 engrenages\b", lambda m: f"{m.group(1) or ''}8 moteurs du marché", t)
    t = sub(r"\bEngrenages\b", "Moteurs", t, 0)
    t = sub(r"\bEngrenage\b", "Moteur", t, 0)
    t = sub(r"\bengrenages\b", "moteurs", t, 0)
    t = sub(r"\bengrenage\b", "moteur", t, 0)
    return t, n


def nettoyer(obj):
    """Remplace dans toutes les VALEURS texte (jamais les clés) ; renvoie (objet, nombre de remplacements)."""
    total = 0

    def walk(x):
        nonlocal total
        if isinstance(x, dict):   # sous-arbre « engrenages » d'un rapport = contenu de l'onglet dédié : laissé tel quel
            return {k: (v if k in SOUS_ARBRES_ONGLET and isinstance(v, dict) else walk(v)) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str):
            t, k = remplacer(x)
            total += k
            return t
        return x
    return walk(obj), total


def publier(docs_data: Path) -> None:
    """docs/data/moteurs.json : noms et explications pour le site (une seule définition, ici)."""
    (Path(docs_data) / "moteurs.json").write_text(json.dumps(
        {"moteurs": {str(k): {"nom": v[0], "explication": v[1], "question": QUESTIONS[k], "canal": CANAUX[k]} for k, v in MOTEURS.items()},
         "note": "Les 8 moteurs du marché ; numérotation et mot « engrenage » réservés à l'onglet « 8 engrenages »."},
        ensure_ascii=False, indent=1), encoding="utf-8")
    site = Path(docs_data).parent / "site"
    if site.is_dir():
        ecrire_js(site / "moteurs.js")


_JS = r'''/* GÉNÉRÉ par core/noms_moteurs.py (lot V10) : ne pas modifier à la main. Noms affichés des 8 moteurs du marché ;
   le mot « engrenage » et les numéros restent réservés à l'onglet « 8 engrenages ». */
export const MOTEURS = __TABLE__;
const echapper = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export function nomMoteur(n, minuscule = false) {
  const m = MOTEURS[String(n)]; if (!m) return "moteur n/d";
  return minuscule ? m.nom[0].toLowerCase() + m.nom.slice(1) : m.nom;
}
export function explicationMoteur(n) { return MOTEURS[String(n)]?.explication || ""; }
/* Nom avec l'explication courte en infobulle (HTML). */
export function moteurHtml(n, minuscule = false) {
  return `<span class="moteur-nom" title="${echapper(explicationMoteur(n))}">${echapper(nomMoteur(n, minuscule))}</span>`;
}
/* Contributions d'une paire (+ vers la hausse) -> « 4 moteurs pour, 0 contre ». */
export function decompteMoteurs(contributions) {
  const l = contributions || [];
  const pour = l.filter(c => (c.contribution || 0) > 0).length, contre = l.filter(c => (c.contribution || 0) < 0).length;
  return { pour, contre, neutres: l.length - pour - contre, texte: `${pour} moteur${pour > 1 ? "s" : ""} pour, ${contre} contre` };
}
'''


def ecrire_js(chemin: Path) -> None:
    """docs/site/moteurs.js : module généré depuis MOTEURS (le JavaScript affiche, il ne redéfinit rien)."""
    table = json.dumps({str(k): {"nom": v[0], "explication": v[1]} for k, v in MOTEURS.items()}, ensure_ascii=False)
    contenu = _JS.replace("__TABLE__", table)
    if not chemin.exists() or chemin.read_text(encoding="utf-8") != contenu:
        chemin.write_text(contenu, encoding="utf-8")


def nettoyer_publication(docs_data: Path) -> dict[str, int]:
    """Filet de sécurité avant publication : JSON de docs/data (et sous-dossiers paires/, synthese/, contexte/) hors
    fichiers de l'onglet dédié. Renvoie {fichier: remplacements} pour le récapitulatif. Ne lève jamais."""
    docs_data = Path(docs_data)
    bilan = {}
    try:
        publier(docs_data)
    except OSError as exc:
        log.warning("moteurs.json non écrit : %s", exc)
    fichiers = list(docs_data.glob("*.json")) + list(docs_data.glob("paires/*.json")) + list(docs_data.glob("synthese/*.json")) \
        + list(docs_data.glob("contexte/*.json"))
    for f in fichiers:
        if f.name in FICHIERS_ONGLET:
            continue   # onglet dédié
        try:
            brut = f.read_text(encoding="utf-8")
            if "ngrenage" not in brut:
                continue
            obj, n = nettoyer(json.loads(brut))
            if n:
                compact = "\n" not in brut[:200]
                f.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compact else
                             json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
                bilan[str(f.relative_to(docs_data))] = n
        except Exception as exc:  # noqa: BLE001
            log.warning("noms des moteurs : %s non traité (%s)", f.name, exc)
    return bilan
