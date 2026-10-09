"""Agent d'auto-critique : second appel LLM, séparé du stratège, qui challenge
la synthèse avant publication.

Trois missions :
1. Incohérences entre indicateurs et conclusions.
2. Affirmations sans source précise.
3. Suggestions d'enrichissement de la base de connaissances (situations
   nouvelles non couvertes) — SUGGESTIONS uniquement, affichées dans le
   rapport : le pipeline ne modifie JAMAIS les fichiers connaissances/
   lui-même, l'utilisateur valide et écrit à la main.

Le contrôle qualité déterministe (complétude des indicateurs, repli 7 jours,
9 devises) est fait AVANT, en Python (core/controle_qualite.py) ; son résultat
est fourni au critique pour contexte. L'évaluation de la justesse des
prédictions reste strictement hebdomadaire/mensuelle (core/evaluation.py) et
n'est PAS du ressort du critique.

"a_revoir" ne bloque JAMAIS la publication : le rapport part avec une mention
visible "⚠️ Point de vigilance identifié par la relecture" — transparence
plutôt que blocage.

Trois statuts pour "validation", jamais deux : "ok" (relu, rien à signaler),
"a_revoir" (relu, incohérence(s) trouvée(s)), "non_evalue" (la relecture n'a
PAS pu avoir lieu — échec LLM ou réponse inexploitable). "non_evalue" ne doit
JAMAIS être confondu avec "ok" : une relecture qui n'a pas eu lieu n'est pas
une relecture qui n'a rien trouvé. Incident du 2026-08-20 : un 429 sur ce
même appel avait produit "ok" par défaut — corrigé ici.
"""
from __future__ import annotations

import copy
import json
import logging

from core.llm import FournisseurLLM, attribution_modele, definir_etiquette, extraire_json
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

PROMPT_CRITIQUE = """Tu es un relecteur de desk indépendant. Challenge la note d'analyse FX
ci-dessous AVANT publication. Trois missions, rien d'autre :
1. Les incohérences entre les indicateurs (detail_score, sens, poids) et la
   conclusion (score, synthese_une_phrase, classement, état du monde). Le champ
   controle_qualite (vérifications programmatiques : complétude des indicateurs,
   repli 7 jours, complétude des 9 devises) t'est fourni : reprends ses anomalies
   non triviales dans tes incohérences si elles affectent la fiabilité du rapport.
   Chaque devise peut porter une "synthese_approfondie" (version condensée ici) : vérifie
   que son "orientation" et ses scénarios sont cohérents avec le score_confluence calculé et
   le biais_macro_global (le score et le biais sont calculés par programme : tu ne les
   contestes pas, tu signales seulement une synthèse qui les contredit), que la thèse ne
   contredit pas ses propres scénarios ni son "invalidation", et que les contrôles Python
   déjà relevés ("controles") sont repris s'ils affectent la fiabilité.
2. Les affirmations sans donnée source précise : élément d'opportunité/menace
   déjà marqué "non_sourcee": true, ou affirmation chiffrée introuvable dans le
   catalogue de sources.
3. Les situations du jour que la méthodologie (base de connaissances) ne couvre
   visiblement pas : propose au plus 3 suggestions d'ajout, avec le fichier cible
   (en général cas_particuliers.md). Ce sont des SUGGESTIONS pour validation
   humaine — elles ne seront jamais appliquées automatiquement.

Hors périmètre — à ne JAMAIS faire :
- Évaluer la justesse des prédictions passées (biais vs réalité) : cette mesure
  est strictement hebdomadaire/mensuelle, un échantillon d'un jour n'a aucune
  valeur statistique.
- Réécrire l'analyse ou proposer une autre conclusion.

Conventions du rapport, à NE PAS signaler comme anomalies :
- "risk_on_off" d'une devise est son PROFIL STRUCTUREL (risque/refuge/neutre,
  ex. JPY toujours "off"), dérivé par programme : il est indépendant du score
  du jour. La direction du jour est portée par score_confluence seul.
- Dans detail_score et le tableau d'indicateurs, une valeur/source null avec la
  mention "aucune publication < 7 j" ou "indisponible" signifie "donnée
  réellement absente, vérifié par programme" : ce n'est pas une affirmation non
  sourcée.

Réponds STRICTEMENT en JSON :
{"incoherences": ["..."],
 "affirmations_non_sourcees": ["..."],
 "suggestions_connaissances": [{"theme": "...", "suggestion": "1-3 phrases prêtes à coller", "fichier_cible": "cas_particuliers.md"}],
 "validation": "ok"|"a_revoir"}
Règle : "a_revoir" dès qu'il existe au moins une incohérence réelle ou une
affirmation non sourcée significative ; "ok" sinon. Les suggestions de
connaissances seules ne justifient pas un "a_revoir".

RAPPORT À RELIRE :
"""


def _condenser(rapport: dict) -> dict:
    """Copie sans les séries de prix (inutiles à la relecture, coûteuses en tokens)."""
    condense = copy.deepcopy(rapport)
    condense.pop("graphiques", None)
    condense.pop("prix_cloture", None)
    condense.pop("graphiques_marche", None)
    # Synthèses approfondies : version condensée (thèse, orientation, scénarios, invalidation,
    # contrôles) — le texte complet coûterait ~700 tokens de plus par devise.
    for dev in condense.get("devises", []):
        syn = dev.get("synthese_approfondie")
        if isinstance(syn, dict) and syn.get("statut") == "ok":
            dev["synthese_approfondie"] = {
                "orientation": syn.get("orientation"),
                "these_centrale": (syn.get("these_centrale") or {}).get("texte"),
                "scenarios": [{"type": s.get("type"), "probabilite": s.get("probabilite"),
                               "declencheur": s.get("declencheur")} for s in syn.get("scenarios", [])],
                "invalidation": [i.get("signal") for i in syn.get("invalidation", [])],
                "nb_opportunites": len(syn.get("opportunites", [])), "nb_menaces": len(syn.get("menaces", [])),
                "controles_python": syn.get("controles", []),
                "affirmations_non_sourcees": [o.get("texte") for k in ("opportunites", "menaces")
                                              for o in syn.get(k, []) if o.get("non_sourcee")],
            }
        elif isinstance(syn, dict):
            dev["synthese_approfondie"] = {"statut": syn.get("statut"), "raison": syn.get("raison")}
    return condense


def critiquer(llm: FournisseurLLM, rapport: dict) -> dict:
    """Retourne le rapport enrichi d'une clé "critique". Ne lève jamais :
    si la relecture échoue, on publie avec la mention d'indisponibilité."""
    prompt = PROMPT_CRITIQUE + json.dumps(_condenser(rapport), ensure_ascii=False, default=str)
    definir_etiquette("critique")
    try:
        brut = extraire_json(llm.appeler_llm(prompt))
        modele_critique = attribution_modele()
        validation = str(brut.get("validation", "ok")).lower()
        suggestions = []
        for s in (brut.get("suggestions_connaissances") or [])[:3]:
            if isinstance(s, dict) and s.get("suggestion"):
                suggestions.append({
                    "theme": str(s.get("theme", ""))[:120],
                    "suggestion": str(s["suggestion"])[:600],
                    "fichier_cible": str(s.get("fichier_cible", "cas_particuliers.md"))[:60],
                })
        if validation not in ("ok", "a_revoir"):
            log.warning("Agent critique : réponse LLM avec validation inexploitable (%r) — "
                       "traitée comme non_evalue, jamais comme ok par défaut", validation)
            validation = "non_evalue"
        critique = {
            "incoherences": [str(x)[:300] for x in brut.get("incoherences", [])][:10],
            "affirmations_non_sourcees": [str(x)[:300] for x in brut.get("affirmations_non_sourcees", [])][:10],
            "suggestions_connaissances": suggestions,
            "validation": validation,
            "redige_par": modele_critique,
        }
        if validation == "non_evalue":
            critique["indisponible"] = True
            critique["note"] = "relecture non effectuée (réponse LLM inexploitable)"
    except Exception as exc:  # noqa: BLE001
        erreur = masquer_secrets(str(exc))
        log.warning("Agent critique indisponible : %s", erreur)
        # JAMAIS "ok" par défaut ici : une relecture qui n'a pas eu lieu n'est
        # pas une relecture qui n'a rien trouvé (incident du 2026-08-20).
        critique = {"incoherences": [], "affirmations_non_sourcees": [],
                    "suggestions_connaissances": [], "validation": "non_evalue",
                    "indisponible": True,
                    "note": f"relecture non effectuée ({erreur[:150]})"}
    if critique["validation"] == "a_revoir":
        log.warning("Relecture : point(s) de vigilance -> %s | %s",
                    critique["incoherences"], critique["affirmations_non_sourcees"])
    rapport["critique"] = critique
    return rapport
