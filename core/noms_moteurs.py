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
CONSIGNE_MODELE = (
    "Les huit moteurs du marché se nomment : " + ", ".join(f"« {v[0][0].lower() + v[0][1:]} »" for k, v in MOTEURS.items())
    + ". Cite-les par leur nom (en minuscules dans la phrase). Jamais le mot « engrenage », ni « engrenage » suivi d'un "
    "numéro, ni un numéro de moteur : un contrôle automatique remplace et signale ces mots.")
# Anciens libellés courts utilisés dans les textes (« 2. Monétaire », « engrenage 3 (données économiques) »)
COURTS = {"thème": 1, "monétaire": 2, "données": 3, "fiscale": 4, "marchés": 5, "géopolitique": 6, "flux": 7, "offre": 8}
# Fichiers propres à l'onglet « 8 engrenages » : le mot y reste
FICHIERS_ONGLET = {"dossiers.json", "dossiers_hebdo.json", "moteurs.json"}
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
        {"moteurs": {str(k): {"nom": v[0], "explication": v[1]} for k, v in MOTEURS.items()},
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
