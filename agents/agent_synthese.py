"""Synthèse approfondie par devise (chantier 3).

Un appel LLM DÉDIÉ par devise, distinct de l'analyse de base : il reçoit l'analyse du
jour (score et biais déjà calculés en Python), les indicateurs publiés, les rendements, la
technique, les titres d'actualité pertinents, des catalyseurs à venir tirés du registre
macro, et produit une note d'analyste structurée (thèse, moteurs, taux/flux, géopolitique,
technique, 3 scénarios, catalyseurs, invalidation, opportunités/menaces).

Règles tenues par PROGRAMME, jamais confiées au modèle :
- le score, le biais et le classement restent ceux de l'analyse de base ;
- date et heure des catalyseurs sont recopiées du registre (le modèle ne cite qu'une référence) ;
- chaque source_id est validé contre le catalogue (traçabilité, core/tracabilite.py) ;
- orientation contraire au score, scénarios manquants, plusieurs probabilités « élevées »,
  moteur manquant, langage d'ordre d'achat/vente : détectés et signalés (jamais corrigés en silence) ;
- un échec n'affecte que cette synthèse : l'analyse de base est publiée, --completer retente
  la synthèse seule (jusqu'à `tentatives_max`, puis « abandonnée »).
"""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core.llm import (MESSAGE_QUOTA_ATTEINT, FournisseurLLM, QuotaAtteint, attribution_modele,
                      definir_etiquette, extraire_json)
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

DOSSIER_RACINE = Path(__file__).resolve().parent.parent
DOSSIER_SYNTHESE = DOSSIER_RACINE / "connaissances" / "synthese"

MOTEURS = ("croissance", "inflation", "emploi", "banque_centrale")
LIBELLES_MOTEURS = {"croissance": "Croissance", "inflation": "Inflation", "emploi": "Emploi",
                    "banque_centrale": "Banque centrale"}
TYPES_SCENARIO = ("haussier", "central", "baissier")
PROBABILITES = ("faible", "moyenne", "elevee")

SCHEMA_SYNTHESE = """{
  "orientation": "haussier" | "baissier" | "neutre",
  "these_centrale": {"texte": "2 à 3 phrases", "source_ids": ["src_NNN"]},
  "moteurs": [{"moteur": "croissance" | "inflation" | "emploi" | "banque_centrale",
               "donnee": "valeur chiffrée + date",
               "trajectoire": "précédent / tendance / surprise vs consensus",
               "implication": "ce que cela implique pour la devise",
               "source_id": "src_NNN ou null"}],
  "taux_et_flux": {"texte": "...", "source_ids": ["src_NNN"]},
  "geopolitique": {"texte": "... (vide si rien de spécifique)", "source_ids": ["src_NNN"]},
  "lecture_technique": {"texte": "...", "coherence": "alignee" | "divergente" | "mixte",
                         "source_ids": ["src_NNN"]},
  "scenarios": [{"type": "haussier" | "central" | "baissier", "declencheur": "fait observable",
                 "probabilite": "faible" | "moyenne" | "elevee", "justification": "...",
                 "source_ids": ["src_NNN"]}],
  "catalyseurs": [{"ref": "C1", "pourquoi": "pourquoi cet événement compte"}],
  "invalidation": [{"signal": "signal précis et observable", "source_id": "src_NNN ou null"}],
  "opportunites": [{"texte": "...", "mecanisme": "cause -> effet sur la devise", "source_id": "src_NNN"}],
  "menaces": [{"texte": "...", "mecanisme": "cause -> effet sur la devise", "source_id": "src_NNN"}]
}"""

# Formulations d'ordre ou de niveau d'exécution : une phrase qui en contient est RETIRÉE.
_RE_ORDRE = re.compile(
    r"\b(achetez|vendez|shortez|entrez\s+(?:en|à|a)|prenez\s+(?:une\s+)?position|"
    r"acheter\s+(?:le|la|l['’]|à|a|les)\b|vendre\s+(?:le|la|l['’]|à|a|les)\b|"
    r"stop[\s-]?loss|take[\s-]?profit|buy\s+(?:the|at|now)|sell\s+(?:the|at|now))",
    re.IGNORECASE)


# ----------------------------------------------------------------- utilitaires
def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(texte)) if unicodedata.category(c) != "Mn")


def _norm(texte) -> str:
    return _sans_accents(str(texte or "")).strip().lower().replace(" ", "_")


def _texte(valeur, maximum: int = 700) -> str:
    return re.sub(r"\s+", " ", str(valeur or "")).strip()[:maximum]


def _ids(valeur) -> list[str]:
    """source_ids : accepte une liste, une chaîne, ou rien."""
    if isinstance(valeur, str):
        valeur = [valeur]
    return [str(v).strip() for v in (valeur or []) if str(v or "").strip().startswith("src_")][:4]


def _retirer_ordres(texte: str) -> tuple[str, int]:
    """Retire les phrases contenant un ordre d'achat/vente ou un niveau d'exécution."""
    if not texte or not _RE_ORDRE.search(texte):
        return texte, 0
    phrases = re.split(r"(?<=[.!?])\s+", texte)
    gardees = [p for p in phrases if not _RE_ORDRE.search(p)]
    return " ".join(gardees).strip(), len(phrases) - len(gardees)


def synthese_a_faire(entree: dict, cfg: dict) -> bool:
    """Vrai si cette devise (analyse de base réussie) doit encore recevoir sa synthèse."""
    if not cfg.get("actif", True) or entree.get("score_confluence") is None:
        return False
    s = entree.get("synthese_approfondie") or {}
    return s.get("statut") not in ("ok", "abandonnee")


def charger_systeme(cfg: dict) -> str:
    morceaux = ["Tu es un analyste de desk FX senior. Tu rédiges une SYNTHÈSE APPROFONDIE "
                "sur UNE devise. Tu ne produis jamais de signal d'achat ou de vente, jamais de "
                "niveau d'entrée, de stop ou d'objectif. Réponds UNIQUEMENT avec le JSON demandé."]
    for fichier in sorted(DOSSIER_SYNTHESE.glob("*.md")):
        morceaux.append(f"\n\n# ===== {fichier.name} =====\n\n" + fichier.read_text(encoding="utf-8"))
    for nom in cfg.get("fichiers_connaissances_racine", []):
        chemin = DOSSIER_RACINE / "connaissances" / nom
        if chemin.exists():
            morceaux.append(f"\n\n# ===== {nom} =====\n\n" + chemin.read_text(encoding="utf-8"))
    return "".join(morceaux)


class _Catalogue:
    """Ajoute des sources au catalogue existant (mêmes règles de dédoublonnage que
    agent_strategiste.assembler_contexte) : les ids déjà attribués sont réutilisés."""

    def __init__(self, catalogue: list[dict]):
        self.catalogue = catalogue
        self.index = {(s.get("source"), s.get("detail"), s.get("date")): s["id"] for s in catalogue}

    def src(self, source: str, detail: str, date_donnee: str | None, url: str | None = None) -> str:
        cle = (source, detail, date_donnee)
        if cle in self.index:
            return self.index[cle]
        identifiant = f"src_{len(self.catalogue) + 1:03d}"
        self.catalogue.append({"id": identifiant, "source": source, "detail": detail,
                               "date": date_donnee, "url": url})
        self.index[cle] = identifiant
        return identifiant


# ------------------------------------------------------------------- contexte
def _catalyseurs(registre: dict | None, devise: str, aujourdhui: date, cfg: dict,
                 cat: _Catalogue) -> list[dict]:
    """Publications à venir de la devise (registre macro) : date et heure UTC viennent
    du registre. {ref, date, heure_utc, evenement, impact, devise, source_id}."""
    if not registre:
        return []
    horizon = aujourdhui + timedelta(days=int(cfg.get("jours_catalyseurs", 14)))
    ordre_impact = {"high": 0, "medium": 1, "low": 2}
    trouves = []
    for cle, case in (registre.get("cases") or {}).items():
        if not cle.startswith(f"{devise}|"):
            continue
        prev = case.get("prevision") or {}
        jour = prev.get("date_pub")
        if not jour or not (aujourdhui.isoformat() <= jour <= horizon.isoformat()):
            continue
        impact = str(prev.get("impact") or "low").lower()
        heure = None
        if prev.get("dateline"):
            heure = datetime.fromtimestamp(int(prev["dateline"]), timezone.utc).strftime("%H:%M")
        trouves.append({"date": jour, "heure_utc": heure, "evenement": prev.get("nom_ff") or cle,
                        "impact": impact, "devise": devise,
                        "consensus": prev.get("valeur"), "indicateur": cle.split("|", 1)[1]})
    trouves.sort(key=lambda c: (c["date"], c["heure_utc"] or "", ordre_impact.get(c["impact"], 3)))
    # Impact moyen/élevé d'abord ; les publications à faible impact ne complètent que s'il en
    # faut au moins 4 (sinon une devise calme n'aurait aucun catalyseur à citer).
    importants = [c for c in trouves if c["impact"] != "low"]
    faibles = [c for c in trouves if c["impact"] == "low"]
    trouves = sorted(importants + faibles[: max(0, 4 - len(importants))],
                     key=lambda c: (c["date"], c["heure_utc"] or ""))[: int(cfg.get("catalyseurs_max", 12))]
    for i, c in enumerate(trouves, 1):
        c["ref"] = f"C{i}"
        c["source_id"] = cat.src("ForexFactory (calendrier)", f"{devise} — {c['evenement']}", c["date"])
    return trouves


def _tableau_registre(registre: dict | None, cfg_tm: dict, devise: str, cat: _Catalogue) -> dict:
    """Valeurs publiées (actuel / précédent / consensus / surprise / date) — brut du registre,
    chaque indicateur avec SON source_id (source et date de publication précises)."""
    resultat = {}
    if not registre:
        return resultat
    for indicateur, spec in (cfg_tm.get("indicateurs") or {}).items():
        if indicateur.startswith(("rendement_", "spread_")):
            continue
        case = (registre.get("cases") or {}).get(f"{devise}|{indicateur}") or {}
        actuel = case.get("actuel")
        if not actuel or case.get("statut") == "non_applicable":
            continue
        prev = case.get("prevision") or {}
        origine = actuel.get("source") or "ForexFactory"
        resultat[spec.get("libelle", indicateur)] = {
            "source_id": cat.src(f"{origine} (registre macro)", f"{devise} — {spec.get('libelle', indicateur)}",
                                 actuel.get("date_pub") or actuel.get("periode")),
            "actuel": actuel.get("valeur"), "publie_le": actuel.get("date_pub") or actuel.get("periode"),
            "consensus_de_cette_publication": actuel.get("consensus"), "surprise": actuel.get("surprise"),
            "precedent": (case.get("precedent") or {}).get("valeur"),
            "prochaine_publication": prev.get("date_pub")}
    return resultat


def _actualites(donnees: dict, devise: str, cfg: dict) -> list[dict]:
    """Titres pertinents d'abord (mots-clés de la devise), puis les plus récents."""
    mots = [m.lower() for m in (cfg.get("mots_cles_news") or {}).get(devise, [])]
    maximum = int(cfg.get("articles_max", 15))
    articles = list(donnees.get("news") or [])
    pertinents = [a for a in articles if any(m in (a.get("titre") or "").lower() for m in mots)]
    autres = [a for a in articles if a not in pertinents]
    choisis = (pertinents + autres)[:maximum]
    return [{"titre": a["titre"], "source": a.get("source"), "date": (a.get("date") or "")[:10],
             "source_id": a.get("source_id"), "lie_a_la_devise": a in pertinents} for a in choisis]


def _memoire(dossier_rapports: Path | None, devise: str, aujourdhui: date, cfg: dict) -> list[dict]:
    """Thèses (synthèse approfondie) des derniers rapports antérieurs à aujourd'hui."""
    if not dossier_rapports:
        return []
    resultat = []
    n = int(cfg.get("jours_memoire", 2))
    for fichier in sorted(Path(dossier_rapports).glob("????-??-??.json"), reverse=True):
        if fichier.stem >= aujourdhui.isoformat():
            continue
        try:
            rapport = json.loads(fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entree = next((d for d in rapport.get("devises", []) if d.get("devise") == devise), None)
        syn = (entree or {}).get("synthese_approfondie") or {}
        if syn.get("statut") == "ok":
            resultat.append({"date": fichier.stem, "score": entree.get("score_confluence"),
                             "orientation": syn.get("orientation"),
                             "these": (syn.get("these_centrale") or {}).get("texte")})
        if len(resultat) >= n:
            break
    return resultat


def _note_paire(config: dict, devise: str) -> str:
    """Évite la confusion de sens des paires inversées (USD/JPY, USD/CHF, USD/CAD)."""
    d = config["devises"][devise]
    if devise == "USD":
        return "L'USD est mesuré par l'indice dollar synthétique (calculé sur les paires suivies) : indice qui monte = USD plus fort."
    paire = d.get("paire")
    if d.get("inverse"):
        return (f"Les données techniques portent sur la paire {paire} : une hausse de la paire = {devise} "
                f"qui BAISSE (la devise analysée est au dénominateur). Raisonne toujours dans le sens de "
                f"la DEVISE {devise}, et nomme la paire {paire} sans l'inverser.")
    return (f"Les données techniques portent sur la paire {paire} : une hausse de la paire = {devise} "
            f"qui monte (la devise analysée est au numérateur).")


def construire_contexte(config: dict, devise: str, entree: dict, donnees: dict, catalogue: list[dict],
                        cat: _Catalogue, registre: dict | None, dossier_rapports: Path | None,
                        extras: dict, aujourdhui: date | None = None) -> tuple[dict, list[dict]]:
    """(contexte envoyé au modèle, catalyseurs candidats). Sous-ensemble ciblé de ce que
    reçoit l'analyse de base : ni sites scrapés, ni mémoire complète, ni catalogue entier."""
    cfg = config.get("synthese_approfondie") or {}
    aujourdhui = aujourdhui or date.today()
    cfg_tm = config.get("tableau_macro") or {}
    candidats = _catalyseurs(registre, devise, aujourdhui, cfg, cat)
    macro = donnees.get("macro") or {}
    taux = (macro.get("taux_directeurs") or {})
    spread = taux.get("spread_2a_vs_usd") or {}
    contexte = {
        "devise_analysee": devise,
        "banque_centrale": config["devises"][devise]["banque_centrale"],
        "date_du_jour": aujourdhui.isoformat(),
        "analyse_de_base_du_jour": {
            "score_confluence_0_100": entree.get("score_confluence"),
            "biais_structurel_risk_on_off": entree.get("risk_on_off"),
            "biais_banque_centrale": entree.get("biais_banque_centrale"),
            "tendance_fond": entree.get("tendance_fond"),
            "synthese_une_phrase": entree.get("synthese_une_phrase"),
            "detail_score": [{k: d.get(k) for k in ("indicateur", "sens", "poids", "justification", "source_id")}
                             for d in entree.get("detail_score", [])],
            "opportunites": entree.get("opportunites", []),
            "menaces": entree.get("menaces", []),
            "contexte_geopolitique": entree.get("contexte_geopolitique"),
            "carry": entree.get("carry"),
        },
        "note_sources": ("taux_directeur_et_carry peut provenir d'une valeur de repli de la configuration "
                         "(date indiquée) ; publications_registre_macro est la dernière publication OFFICIELLE "
                         "(ForexFactory/FRED). En cas d'écart sur un taux directeur, privilégie le registre "
                         "et signale l'écart au lieu de choisir en silence."),
        "note_score": ("Le score et le biais sont calculés par programme : ne les contredis pas "
                       "et ne les recalcule pas ; ton orientation doit leur rester cohérente."),
        "indicateurs_du_jour": [{k: l.get(k) for k in ("nom", "valeur", "prevision", "precedent", "date", "source")}
                                for l in entree.get("indicateurs_tableau", [])],
        "publications_registre_macro": _tableau_registre(registre, cfg_tm, devise, cat),
        "indice_surprise_30j": extras.get("indice_surprise", {}).get(devise),
        "rendements_et_taux": {
            "source_id": spread.get("source_id") or taux.get("source_id"),
            "taux_directeur_et_carry": (taux.get("valeurs") or {}).get(devise),
            "differentiel_carry": ((taux.get("carry") or {}).get("differentiels") or {}).get(devise),
            "rendements_souverains": (spread.get("valeurs") or {}).get(devise),
            "rendements_souverains_usd": (spread.get("valeurs") or {}).get("USD")},
        "note_paire": _note_paire(config, devise),
        "technique": {"devise": donnees.get("technique", {}).get(devise),
                      "usd_reference": donnees.get("technique", {}).get("USD") if devise != "USD" else None,
                      "correlations": ((donnees.get("correlations") or {}).get("matrice") or {}).get(devise),
                      "source_id_correlations": (donnees.get("correlations") or {}).get("source_id")},
        "marches": {"series": {k: {c: v.get(c) for c in ("valeur", "precedent", "variation_pct", "date", "source_id") if c in v}
                               for k, v in (macro.get("series") or {}).items()},
                    "yield_curve_us": macro.get("yield_curve")},
        # Événements sans aucune valeur et à faible impact (ex. « ECOFIN Meetings ») : du bruit,
        # que le modèle sur-interprète — non envoyés.
        "calendrier_recent_devise": [
            e for e in donnees.get("calendrier", [])
            if e.get("devise") in ({devise} | ({"CNY"} if devise in ("AUD", "NZD") else set()))
            and not (str(e.get("impact", "")).lower() == "low"
                     and all(e.get(c) is None for c in ("prevision", "precedent", "reel")))],
        "catalyseurs_a_venir": [{k: c[k] for k in ("ref", "date", "heure_utc", "evenement", "impact", "consensus")}
                                for c in candidats],
        "actualites": _actualites(donnees, devise, cfg),
        "theses_precedentes": _memoire(dossier_rapports, devise, aujourdhui, cfg),
    }
    # Catalogue restreint aux seuls identifiants réellement présents dans ce contexte.
    present = set(re.findall(r"src_\d{3,}", json.dumps(contexte, ensure_ascii=False, default=str)))
    present |= {c["source_id"] for c in candidats}
    contexte["catalogue_sources"] = [{"id": s["id"], "source": s["source"], "detail": str(s.get("detail"))[:90],
                                      "date": s.get("date")} for s in catalogue if s["id"] in present]
    return contexte, candidats


# ---------------------------------------------------------------- normalisation
def normaliser(brut: dict, candidats: list[dict], entree: dict, cfg: dict) -> dict:
    """Schéma strict + contrôles Python. Lève ValueError si la synthèse est inexploitable
    (thèse absente ou moins de 3 scénarios distincts)."""
    controles: list[str] = []
    retraits = 0

    def propre(texte, maximum=700):
        nonlocal retraits
        net, n = _retirer_ordres(_texte(texte, maximum))
        retraits += n
        return net

    these = brut.get("these_centrale") or {}
    if isinstance(these, str):
        these = {"texte": these}
    these_texte = propre(these.get("texte"), 900)
    if not these_texte:
        raise ValueError("thèse centrale absente")

    scenarios = {}
    for s in brut.get("scenarios") or []:
        if not isinstance(s, dict):
            continue
        t = _norm(s.get("type"))
        if t in TYPES_SCENARIO and t not in scenarios:
            p = _norm(s.get("probabilite"))
            scenarios[t] = {"type": t, "declencheur": propre(s.get("declencheur"), 400),
                            "probabilite": p if p in PROBABILITES else None,
                            "justification": propre(s.get("justification"), 500),
                            "source_ids": _ids(s.get("source_ids") or s.get("source_id"))}
    if len(scenarios) < 3:
        raise ValueError(f"scénarios incomplets ({', '.join(sorted(scenarios)) or 'aucun'})")
    if any(s["probabilite"] is None for s in scenarios.values()):
        controles.append("probabilité de scénario non qualitative (faible / moyenne / élevée attendu)")
    if sum(1 for s in scenarios.values() if s["probabilite"] == "elevee") > 1:
        controles.append("plusieurs scénarios jugés à probabilité élevée")

    moteurs = {}
    for m in brut.get("moteurs") or []:
        if not isinstance(m, dict):
            continue
        nom = _norm(m.get("moteur"))
        if nom in MOTEURS and nom not in moteurs:
            moteurs[nom] = {"moteur": nom, "donnee": propre(m.get("donnee"), 300),
                            "trajectoire": propre(m.get("trajectoire"), 400),
                            "implication": propre(m.get("implication"), 400),
                            "source_id": (_ids(m.get("source_id")) or [None])[0]}
    manquants = [LIBELLES_MOTEURS[n] for n in MOTEURS if n not in moteurs]
    if manquants:
        controles.append(f"moteur(s) fondamental(aux) absent(s) : {', '.join(manquants)}")

    candidats_par_ref = {c["ref"]: c for c in candidats}
    catalyseurs, vus = [], set()
    for c in brut.get("catalyseurs") or []:
        ref = str(c.get("ref") if isinstance(c, dict) else c).strip().upper()
        cand = candidats_par_ref.get(ref)
        if cand and ref not in vus:   # une référence inconnue (événement inventé) est ignorée
            vus.add(ref)
            catalyseurs.append({"date": cand["date"], "heure_utc": cand["heure_utc"],
                                "evenement": cand["evenement"], "impact": cand["impact"],
                                "consensus": cand.get("consensus"), "source_id": cand["source_id"],
                                "pourquoi": propre(c.get("pourquoi") if isinstance(c, dict) else "", 300)})
    ignores = len([c for c in (brut.get("catalyseurs") or [])]) - len(catalyseurs)
    if ignores > 0 and candidats:
        controles.append(f"{ignores} catalyseur(s) ignoré(s) (référence absente du calendrier)")
    if not catalyseurs:
        controles.append("aucun catalyseur à venir identifié dans le calendrier")
    catalyseurs.sort(key=lambda c: (c["date"], c["heure_utc"] or ""))

    def puces(liste, nom):
        sortie = []
        for p in liste or []:
            if isinstance(p, dict) and _texte(p.get("texte")):
                sortie.append({"texte": propre(p.get("texte"), 400), "mecanisme": propre(p.get("mecanisme"), 500),
                               "source_id": (_ids(p.get("source_id")) or [None])[0]})
        if len(sortie) < 3:
            controles.append(f"moins de 3 {nom} ({len(sortie)})")
        return sortie[:6]

    tech = brut.get("lecture_technique") or {}
    coherence = _norm(tech.get("coherence")) if isinstance(tech, dict) else ""
    orientation = _norm(brut.get("orientation"))
    if orientation not in ("haussier", "baissier", "neutre"):
        controles.append("orientation absente ou non reconnue")
        orientation = None
    score = entree.get("score_confluence")
    if orientation and score is not None:
        haut, bas = cfg.get("orientation_haussier_min", 60), cfg.get("orientation_baissier_max", 40)
        if (orientation == "haussier" and score <= bas) or (orientation == "baissier" and score >= haut) \
                or (orientation == "neutre" and (score >= 75 or score <= 25)):
            controles.append(f"orientation « {orientation} » en tension avec le score de confluence calculé "
                             f"({score}/100)")

    def bloc(valeur, maximum=800):
        if isinstance(valeur, str):
            valeur = {"texte": valeur}
        valeur = valeur if isinstance(valeur, dict) else {}
        return {"texte": propre(valeur.get("texte"), maximum),
                "source_ids": _ids(valeur.get("source_ids") or valeur.get("source_id"))}

    if retraits:
        controles.append(f"{retraits} phrase(s) retirée(s) : formulation d'ordre d'achat/vente")

    return {
        "orientation": orientation,
        "these_centrale": {"texte": these_texte, "source_ids": _ids(these.get("source_ids") or these.get("source_id"))},
        "moteurs": [moteurs[n] for n in MOTEURS if n in moteurs],
        "taux_et_flux": bloc(brut.get("taux_et_flux")),
        "geopolitique": bloc(brut.get("geopolitique")),
        "lecture_technique": {**bloc(tech if isinstance(tech, dict) else {"texte": tech}),
                              "coherence": coherence if coherence in ("alignee", "divergente", "mixte") else None},
        "scenarios": [scenarios[t] for t in TYPES_SCENARIO],
        "catalyseurs": catalyseurs,
        "invalidation": [{"signal": propre(i.get("signal"), 300), "source_id": (_ids(i.get("source_id")) or [None])[0]}
                         for i in (brut.get("invalidation") or []) if isinstance(i, dict) and _texte(i.get("signal"))][:5],
        "opportunites": puces(brut.get("opportunites"), "opportunités"),
        "menaces": puces(brut.get("menaces"), "menaces"),
        "controles": controles,
    }


# --------------------------------------------------------------------- appels
def _synthetiser_devise(llm: FournisseurLLM, systeme: str, config: dict, devise: str, entree: dict,
                        donnees: dict, catalogue: list[dict], cat: _Catalogue, registre: dict | None,
                        dossier_rapports: Path | None, extras: dict) -> dict:
    cfg = config.get("synthese_approfondie") or {}
    contexte, candidats = construire_contexte(config, devise, entree, donnees, catalogue, cat, registre,
                                              dossier_rapports, extras)
    ids_valides = ", ".join(s["id"] for s in contexte["catalogue_sources"])
    prompt = (
        f"Rédige la synthèse approfondie de la devise {devise} selon le plan imposé.\n"
        f"Réponds STRICTEMENT selon ce schéma JSON :\n{SCHEMA_SYNTHESE}\n\n"
        f"SEULS ces source_id existent : [{ids_valides}]. Tout autre identifiant sera invalidé : "
        "mets null plutôt que d'inventer. Pour les catalyseurs, cite uniquement les références "
        "(C1, C2…) de catalyseurs_a_venir.\n"
        "Si thèses_precedentes existe, dis en une phrase si la thèse a évolué.\n\n"
        "DONNÉES DU JOUR (JSON) :\n" + json.dumps(contexte, ensure_ascii=False, default=str))
    tentatives = int(config["llm"].get("max_tentatives_json", 2))
    derniere: Exception | None = None
    for essai in range(1, tentatives + 1):
        try:
            brut = extraire_json(llm.appeler_llm(prompt, systeme=systeme))
            modele = attribution_modele()
            if not isinstance(brut, dict):
                raise ValueError("réponse JSON non conforme (objet attendu)")
            synthese = normaliser(brut, candidats, entree, cfg)
            synthese["redige_par"] = modele
            return synthese
        except QuotaAtteint:
            raise   # plus aucun modèle disponible aujourd'hui : inutile de retenter
        except Exception as exc:  # noqa: BLE001 — JSON invalide, schéma incomplet ou erreur API : on retente
            derniere = exc
            log.warning("Synthèse %s, essai %d/%d en échec : %s", devise, essai, tentatives,
                        masquer_secrets(str(exc)))
    raise RuntimeError(masquer_secrets(str(derniere)))


def synthetiser(config: dict, llm: FournisseurLLM, devises: list[dict], donnees: dict, catalogue: list[dict],
                dossier_rapports: str | Path | None = None, registre: dict | None = None,
                extras: dict | None = None, pause_s: float | None = None) -> int:
    """Ajoute `synthese_approfondie` à chaque devise qui en a besoin (mutation en place).
    Retourne le nombre d'appels effectués. Un échec n'affecte que sa devise."""
    cfg = config.get("synthese_approfondie") or {}
    if not cfg.get("actif", True):
        return 0
    a_faire = [d for d in devises if synthese_a_faire(d, cfg)]
    if not a_faire:
        return 0
    systeme = charger_systeme(cfg)
    cat = _Catalogue(catalogue)
    pause = float(config["llm"].get("pause_entre_devises_s", 0)) if pause_s is None else pause_s
    dossier = Path(dossier_rapports) if dossier_rapports else None
    maximum = int(cfg.get("tentatives_max", 4))
    appels = 0
    quota_atteint = False
    for entree in a_faire:
        devise = entree["devise"]
        if quota_atteint:
            # Plus aucun modèle disponible : pas d'appel, pas de tentative comptée (ce n'est pas un
            # échec de la synthèse) — elle sera retentée par --completer après la remise à zéro du quota.
            entree["synthese_approfondie"] = {
                "statut": "indisponible", "raison": MESSAGE_QUOTA_ATTEINT, "quota_atteint": True,
                "tentatives": int((entree.get("synthese_approfondie") or {}).get("tentatives", 0)),
                "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            continue
        if appels and pause > 0:
            time.sleep(pause)   # même cadence que les analyses : jamais de rafale de gros prompts
        appels += 1
        precedentes = int((entree.get("synthese_approfondie") or {}).get("tentatives", 0))
        definir_etiquette(f"synthese:{devise}")
        try:
            synthese = _synthetiser_devise(llm, systeme, config, devise, entree, donnees, catalogue, cat,
                                           registre, dossier, extras or {})
            synthese.update({"statut": "ok", "tentatives": precedentes + 1,
                             "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            entree["synthese_approfondie"] = synthese
        except QuotaAtteint:
            quota_atteint = True
            entree["synthese_approfondie"] = {
                "statut": "indisponible", "raison": MESSAGE_QUOTA_ATTEINT, "quota_atteint": True,
                "tentatives": precedentes, "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            log.warning("Synthèses approfondies : quota atteint sur tous les modèles — arrêt (retentées au "
                        "prochain passage après remise à zéro)")
        except Exception as exc:  # noqa: BLE001
            n = precedentes + 1
            raison = masquer_secrets(str(exc))[:200]
            statut = "abandonnee" if n >= maximum else "indisponible"
            log.error("Synthèse approfondie %s %s (tentative %d/%d) : %s", devise, statut, n, maximum, raison)
            entree["synthese_approfondie"] = {"statut": statut, "raison": raison, "tentatives": n,
                                              "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return appels
