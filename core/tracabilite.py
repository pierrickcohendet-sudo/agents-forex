"""Traçabilité stricte : chaque opportunité/menace doit référencer un
source_id présent dans sources_citees. Une affirmation non traçable est
rejetée ou marquée "non sourcée" (selon config), jamais publiée comme vérifiée.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _filtrer_liste_sourcee(items: list[dict], ids_valides: set, mode: str,
                           libelle: str, devise_code: str) -> tuple[list[dict], int, int]:
    """Filtre une liste à puces sourcée (opportunites/menaces/evenements) :
    retourne (conservés, delta_marquees, delta_rejetees)."""
    conserves, marquees, rejetees = [], 0, 0
    for item in items:
        if item.get("source_id") in ids_valides:
            item["non_sourcee"] = False
            conserves.append(item)
        elif mode == "rejeter":
            rejetees += 1
            log.warning("[%s] %s rejetée (source_id invalide) : %s",
                        devise_code, libelle, str(item.get("texte"))[:120])
        else:
            marquees += 1
            item["non_sourcee"] = True
            item["source_id"] = None
            conserves.append(item)
    return conserves, marquees, rejetees


def _valider_synthese(syn: dict, ids_valides: set, mode: str, code: str) -> tuple[int, int]:
    """Synthèse approfondie d'une devise : mêmes règles que le reste du rapport. Les blocs
    de texte sans aucune source valide sont marqués « non_source » ; les listes à puces
    sourcées (opportunités / menaces) suivent le mode marquer / rejeter ; un identifiant
    inventé ailleurs est simplement annulé."""
    marquees = rejetees = 0
    for cle in ("these_centrale", "taux_et_flux", "geopolitique", "lecture_technique"):
        bloc = syn.get(cle)
        if not isinstance(bloc, dict):
            continue
        valides = [i for i in bloc.get("source_ids", []) if i in ids_valides]
        bloc["non_source"] = bool(bloc.get("texte") and not valides)
        marquees += int(bloc["non_source"])
        bloc["source_ids"] = valides
    for scenario in syn.get("scenarios", []):
        scenario["source_ids"] = [i for i in scenario.get("source_ids", []) if i in ids_valides]
    for cle in ("moteurs", "invalidation", "catalyseurs"):
        for item in syn.get(cle, []):
            if item.get("source_id") not in ids_valides:
                item["source_id"] = None
    for cle in ("opportunites", "menaces"):
        conserves, m, r = _filtrer_liste_sourcee(syn.get(cle, []), ids_valides, mode,
                                                 f"synthese.{cle}", code)
        syn[cle] = conserves
        marquees += m
        rejetees += r
    return marquees, rejetees


def valider_rapport(rapport: dict, mode: str = "marquer") -> dict:
    ids_valides = {s.get("id") for s in rapport.get("sources_citees", [])}
    marquees = rejetees = 0

    for devise in rapport.get("devises", []):
        code = devise.get("devise")
        for cle in ("opportunites", "menaces"):
            conserves, d_marquees, d_rejetees = _filtrer_liste_sourcee(
                devise.get(cle, []), ids_valides, mode, cle, code)
            devise[cle] = conserves
            marquees += d_marquees
            rejetees += d_rejetees

        # detail_score et tendance_fond : un source_id inventé est simplement annulé.
        for item in devise.get("detail_score", []):
            if item.get("source_id") not in ids_valides:
                item["source_id"] = None
        tendance = devise.get("tendance_fond") or {}
        if tendance.get("source_id") not in ids_valides:
            tendance["source_id"] = None

        syn = devise.get("synthese_approfondie")
        if isinstance(syn, dict) and syn.get("statut") == "ok":
            m, r = _valider_synthese(syn, ids_valides, mode, code)
            marquees += m
            rejetees += r

        # Contexte géopolitique & décisions (par devise) : même traitement que
        # opportunites/menaces pour les événements ; la phrase de posture
        # banque centrale est annulée (pas comptée "non sourcée") comme
        # tendance_fond, car c'est une synthèse interprétative, pas un fait isolé.
        contexte = devise.get("contexte_geopolitique") or {}
        if contexte:
            pourquoi = contexte.get("banque_centrale_pourquoi") or {}
            if pourquoi.get("source_id") not in ids_valides:
                pourquoi["source_id"] = None
            conserves, d_marquees, d_rejetees = _filtrer_liste_sourcee(
                contexte.get("evenements", []), ids_valides, mode,
                "contexte_geopolitique.evenements", code)
            contexte["evenements"] = conserves
            marquees += d_marquees
            rejetees += d_rejetees

    # 8 engrenages : ids inventés retirés ; maillon de chaîne sans source valide marqué non sourcé.
    eng = (rapport.get("synthese_globale") or {}).get("engrenages") or {}
    if eng.get("statut") == "ok":
        for e in eng.get("engrenages", []):
            e["source_ids"] = [i for i in e.get("source_ids", []) if i in ids_valides]
            for d in e.get("donnees_calculees", []):
                if d.get("source_id") not in ids_valides:
                    d["source_id"] = None
            e["non_source"] = bool(not e.get("donnees_insuffisantes") and not e["source_ids"])
            marquees += int(e["non_source"])
        for c in eng.get("chaines", []):
            for m in c.get("maillons", []):
                m["non_sourcee"] = m.get("source_id") not in ids_valides
                if m["non_sourcee"]:
                    m["source_id"] = None
                    marquees += 1
        for c in eng.get("conflits", []):
            c["source_ids"] = [i for i in c.get("source_ids", []) if i in ids_valides]
        if eng.get("concept"):
            eng["concept"]["source_ids"] = [i for i in eng["concept"].get("source_ids", []) if i in ids_valides]

    # État du monde : rubriques (source_ids multiples), listes du briefing
    # (source_id unitaire par item) ; la conclusion est une synthèse, sans
    # exigence de source propre.
    etat = (rapport.get("synthese_globale") or {}).get("etat_du_monde") or {}
    for valeur in etat.values():
        if isinstance(valeur, dict) and "source_ids" in valeur:
            valides = [i for i in valeur.get("source_ids", []) if i in ids_valides]
            if valeur.get("texte") and not valides:
                marquees += 1
                valeur["non_source"] = True
            else:
                valeur["non_source"] = False
            valeur["source_ids"] = valides
        elif isinstance(valeur, list):
            for item in valeur:
                if not isinstance(item, dict):
                    continue
                if item.get("source_id") in ids_valides:
                    item["non_sourcee"] = False
                else:
                    marquees += 1
                    item["non_sourcee"] = True
                    item["source_id"] = None

    rapport["tracabilite"] = {"mode": mode, "marquees": marquees, "rejetees": rejetees}
    if marquees or rejetees:
        log.info("Traçabilité : %d marquée(s) non sourcée(s), %d rejetée(s)", marquees, rejetees)
    return rapport
