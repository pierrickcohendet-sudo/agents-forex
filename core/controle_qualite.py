"""Contrôle qualité déterministe, exécuté à CHAQUE run (code pur, pas de LLM) :

- toutes les devises configurées sont présentes et complètes (jauge = score,
  graphique, tableau, toggles, synthèse) ;
- chaque devise a TOUS ses indicateurs configurés dans detail_score ET dans le
  tableau d'indicateurs ;
- la règle de repli à 7 jours est respectée : toute valeur affichée porte une
  date d'origine, les indicateurs calendrier ne remontent jamais au-delà de 7 j.

L'évaluation de la JUSTESSE des prédictions n'a rien à faire ici : elle reste
strictement hebdomadaire/mensuelle (core/evaluation.py) — un échantillon d'un
jour n'a aucune valeur statistique.
"""
from __future__ import annotations

import logging

from core import scoring

log = logging.getLogger(__name__)

INDICATEURS_CALENDRIER = {"cpi_surprise", "pmi_surprise", "fixing_pboc"}


def controler(rapport: dict, config: dict) -> dict:
    anomalies: list[str] = []

    presentes = {d["devise"] for d in rapport.get("devises", [])}
    manquantes = set(config["devises"]) - presentes
    if manquantes:
        anomalies.append(f"devises absentes du rapport : {', '.join(sorted(manquantes))}")

    for dev in rapport.get("devises", []):
        code = dev["devise"]
        if dev.get("analyse_indisponible"):
            # Une seule anomalie explicite, pas une cascade de sous-anomalies.
            anomalies.append(
                f"{code} : analyse indisponible aujourd'hui "
                f"({str(dev.get('raison_indisponibilite', ''))[:150]}) — exclue du classement")
            continue
        attendus = set(scoring.ponderations_devise(config, code))

        presents_score = {d.get("indicateur") for d in dev.get("detail_score", [])}
        oublies = attendus - presents_score
        if oublies:
            anomalies.append(f"{code} : detail_score incomplet ({', '.join(sorted(oublies))})")

        lignes = dev.get("indicateurs_tableau", [])
        presents_tableau = {l.get("indicateur") for l in lignes}
        oublies = attendus - presents_tableau
        if oublies:
            anomalies.append(f"{code} : tableau d'indicateurs incomplet ({', '.join(sorted(oublies))})")

        for ligne in lignes:
            a_valeur = ligne.get("valeur") not in (None, "", "—")
            if a_valeur and not ligne.get("date"):
                anomalies.append(f"{code} : « {ligne.get('nom')} » affiche une valeur sans date d'origine")
            anciennete = ligne.get("anciennete_jours")
            if (a_valeur and ligne.get("indicateur") in INDICATEURS_CALENDRIER
                    and anciennete is not None and anciennete > 7):
                anomalies.append(f"{code} : « {ligne.get('nom')} » dépasse le repli de 7 jours (J-{anciennete})")

        if not rapport.get("graphiques", {}).get(code):
            anomalies.append(f"{code} : graphique de prix manquant")
        if not str(dev.get("synthese_une_phrase", "")).strip():
            anomalies.append(f"{code} : synthèse absente")
        for cle in ("opportunites", "menaces"):
            if cle not in dev:
                anomalies.append(f"{code} : section {cle} absente")

        # Contexte géopolitique & décisions : la posture banque centrale
        # DOIT être expliquée (une phrase minimum) — en revanche une liste
        # d'événements vide est légitime certaines semaines, pas une anomalie.
        pourquoi = (dev.get("contexte_geopolitique") or {}).get("banque_centrale_pourquoi") or {}
        if not str(pourquoi.get("texte", "")).strip():
            anomalies.append(f"{code} : posture banque centrale non expliquée (contexte_geopolitique)")

    # Synthèses approfondies (chantier 3) : statut honnête + points relevés par les contrôles Python.
    if (config.get("synthese_approfondie") or {}).get("actif", True):
        for dev in rapport.get("devises", []):
            if dev.get("score_confluence") is None:
                continue
            syn = dev.get("synthese_approfondie")
            if not syn:
                anomalies.append(f"{dev['devise']} : synthèse approfondie absente")
            elif syn.get("statut") != "ok":
                anomalies.append(f"{dev['devise']} : synthèse approfondie {syn.get('statut')} "
                                 f"({str(syn.get('raison', ''))[:100]})")
            else:
                for point in syn.get("controles", [])[:3]:
                    anomalies.append(f"{dev['devise']} synthèse approfondie : {point}")

    if (config.get("engrenages") or {}).get("actif", True):
        eng = rapport.get("synthese_globale", {}).get("engrenages")
        if not eng:
            anomalies.append("8 engrenages : synthèse absente")
        elif eng.get("statut") != "ok":
            anomalies.append(f"8 engrenages : {eng.get('statut')} ({str(eng.get('raison', ''))[:100]})")
        else:
            anomalies.extend(f"8 engrenages : {c}" for c in eng.get("controles", [])[:3])

    etat_du_monde = rapport.get("synthese_globale", {}).get("etat_du_monde")
    if not etat_du_monde:
        anomalies.append("état du monde absent de la synthèse globale")
    elif etat_du_monde.get("incoherence_biais_detectee"):
        # Détecté par agent_strategiste.synthese_etat_du_monde (filet mécanique
        # + un nouvel essai déjà tentés) : persiste malgré la relance, publié
        # quand même (transparence plutôt que blocage) mais signalé ici pour
        # ne jamais rester silencieux.
        biais_libelle = {"risk_on": "Risk On", "risk_off": "Risk Off",
                         "neutre": "Neutre"}.get(rapport["synthese_globale"]["biais_macro_global"])
        anomalies.append(
            f"le texte de l'état du monde (conclusion/rubriques) semble contredire le biais "
            f"macro global calculé ({biais_libelle}) — incohérence persistante après relance")

    tableau = (rapport.get("tableau_macro") or {}).get("anomalies", [])
    anomalies.extend(tableau[:10])
    if len(tableau) > 10:
        anomalies.append(f"tableau macro : … +{len(tableau) - 10} autre(s) anomalie(s)")

    resultat = {"conforme": not anomalies, "nb_anomalies": len(anomalies),
                "anomalies": anomalies[:30]}
    if anomalies:
        log.warning("Contrôle qualité : %d anomalie(s) — %s", len(anomalies), anomalies[:5])
    else:
        log.info("Contrôle qualité : conforme")
    return resultat


SEUIL_PROMPT_TOKENS_DEFAUT = 18000
_PREFIXE_ALERTE_PROMPT = "prompt LLM volumineux"


def signaler_prompts_volumineux(rapport: dict, config: dict) -> None:
    """Ajoute au contrôle qualité UNE anomalie si un prompt LLM du jour
    (meta.appels_llm) dépasse controle_qualite.seuil_prompt_tokens — pour voir
    tout de suite si le contexte envoyé regrossit. Idempotent : remplace
    l'alerte précédente. Appelée après le dernier appel LLM du run."""
    controle = rapport.get("controle_qualite")
    if not isinstance(controle, dict):
        return
    seuil = int(config.get("controle_qualite", {}).get("seuil_prompt_tokens",
                                                       SEUIL_PROMPT_TOKENS_DEFAUT))
    anomalies = [a for a in controle.get("anomalies", []) if not a.startswith(_PREFIXE_ALERTE_PROMPT)]
    appels = rapport.get("meta", {}).get("appels_llm", [])
    plafond_synthese = int((config.get("synthese_approfondie") or {}).get("plafond_prompt_tokens", seuil))

    def depasse(appel: dict) -> bool:
        limite = plafond_synthese if str(appel.get("etiquette", "")).startswith("synthese:") else seuil
        return appel.get("tokens_total", 0) > limite
    gros = [a for a in appels if depasse(a)]
    if gros:
        pire = max(gros, key=lambda a: a["tokens_total"])
        anomalies.append(
            f"{_PREFIXE_ALERTE_PROMPT} : {len(gros)} appel(s) au-dessus du seuil ({seuil} tokens estimés, "
            f"{plafond_synthese} pour les synthèses) "
            f"(max {pire['tokens_total']} à {pire.get('heure', '?')} UTC, modèle {pire.get('modele', '?')}) "
            f"— le contexte envoyé au LLM a regrossi")
        log.warning("Contrôle qualité : %s", anomalies[-1])
    controle["anomalies"] = anomalies[:30]
    controle["nb_anomalies"] = len(anomalies)
    controle["conforme"] = not anomalies
