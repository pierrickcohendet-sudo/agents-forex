"""Orchestrateur du pipeline FX.

Chaîne quotidienne : collecte (technique -> macro -> news -> calendrier,
séquentielle) -> stratège -> traçabilité -> [lundi : auto-évaluation J-7]
-> critique -> sauvegarde -> Notion -> dashboard web (GitHub Pages).

Chaque étape est isolée : un échec de collecte dégrade le rapport (mention
"donnée non rafraîchie") sans l'empêcher ; un échec de publication notifie
(Slack/email) sans perdre le rapport. Seul un échec du stratège est fatal.

Mode --completer (remplissage progressif intra-journée) : relancé plusieurs
fois dans la journée, il réutilise le cache de scraping (jamais une 2e requête
sur les 6 sites le même jour — déjà garanti par core/scraping.py) et ne
retente QUE les devises/sections encore "analyse indisponible" du rapport déjà
sauvegardé aujourd'hui — tout ce qui a réussi reste intact. Upsert de l'entrée
du jour (Notion + JSON), jamais de doublon. S'il n'y a rien à compléter, le
run s'arrête immédiatement sans rien republier.

Usage :
    python orchestrateur.py                        # auto : hebdo le lundi, mensuel le 1er
    python orchestrateur.py --type quotidien
    python orchestrateur.py --type quotidien --completer   # passage de complément
    python orchestrateur.py --type hebdomadaire     # forcer le mode hebdo sans attendre lundi
    python orchestrateur.py --sans-notion --sans-web
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from agents import (agent_critique, agent_redacteur, agent_strategiste,
                    collecte_calendrier, collecte_macro, collecte_news,
                    collecte_technique)
from core import collecte_cache, controle_qualite, evaluation, hebdo, overrides, publication_web
from core.llm import creer_fournisseur
from core.notifications import notifier_echec
from core.scraping import ClientScraping
from core.tracabilite import valider_rapport

RACINE = Path(__file__).resolve().parent
log = logging.getLogger("orchestrateur")


def initialiser_logs(dossier: Path) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s : %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(dossier / f"{date.today().isoformat()}.log", encoding="utf-8"),
        ],
    )


def etape(nom: str, fonction, *args, fatal: bool = False, defaut=None, **kwargs):
    """Exécute une étape ; loggue et notifie l'échec. fatal=True arrête le pipeline."""
    try:
        resultat = fonction(*args, **kwargs)
        log.info("Étape « %s » : OK", nom)
        return resultat
    except Exception as exc:  # noqa: BLE001
        # Trace COMPLÈTE (fichier + ligne) dans data/logs/ ; la notification
        # Slack/email ne reçoit que le résumé.
        log.exception("Étape « %s » en échec", nom)
        notifier_echec(nom, f"{type(exc).__name__}: {exc}")
        if fatal:
            raise
        return defaut


def type_de_rapport(force: str | None) -> str:
    if force and force != "auto":
        return force
    auj = date.today()
    if auj.day == 1:
        return "mensuel"
    if auj.weekday() == 0:  # lundi
        return "hebdomadaire"
    return "quotidien"


def _charger_rapport_existant(dossier_rapports: Path) -> dict | None:
    chemin = dossier_rapports / f"{date.today().isoformat()}.json"
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    parseur = argparse.ArgumentParser(description="Pipeline de rapport FX quotidien")
    parseur.add_argument("--type", choices=["auto", "quotidien", "hebdomadaire", "mensuel"],
                         default="auto")
    parseur.add_argument("--completer", action="store_true",
                         help="Passage de complément intra-journée : ne retente que les "
                              "devises/sections en échec du rapport déjà sauvegardé aujourd'hui, "
                              "réutilise le cache de scraping, upsert (jamais de doublon).")
    parseur.add_argument("--sans-notion", action="store_true")
    parseur.add_argument("--sans-web", action="store_true")
    arguments = parseur.parse_args()

    load_dotenv(RACINE / ".env")
    config = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
    donnees_dir = RACINE / config["chemins"]["donnees"]
    initialiser_logs(donnees_dir / "logs")
    dossier_rapports = donnees_dir / "rapports"
    dossier_rapports.mkdir(parents=True, exist_ok=True)

    type_rapport = type_de_rapport(arguments.type)
    log.info("=== Pipeline FX — rapport %s du %s%s ===", type_rapport, date.today().isoformat(),
             " (complément)" if arguments.completer else "")

    # ------------------------------------------------------- mode --completer
    rapport_existant = None
    if arguments.completer:
        rapport_existant = _charger_rapport_existant(dossier_rapports)
        if rapport_existant is None:
            log.info("--completer sans rapport existant aujourd'hui : passage complet effectué à la place")
        else:
            a_completer = [d["devise"] for d in rapport_existant.get("devises", [])
                          if d.get("score_confluence") is None]
            etat_manquant = not rapport_existant.get("synthese_globale", {}).get("etat_du_monde")
            if not a_completer and not etat_manquant:
                log.info("--completer : rien à compléter aujourd'hui (rapport déjà complet) — run ignoré")
                return 0
            log.info("--completer : %d devise(s) à retenter (%s)%s", len(a_completer),
                     ", ".join(a_completer) or "—", " + état du monde" if etat_manquant else "")
        heure_limite = str(config.get("completer", {}).get("heure_limite", "")).strip()
        if heure_limite:
            try:
                if datetime.now().time() >= datetime.strptime(heure_limite, "%H:%M").time():
                    log.info("--completer : après l'heure limite configurée (%s) — dernier passage "
                             "de la journée, le rapport sera finalisé tel quel", heure_limite)
            except ValueError:
                log.warning("completer.heure_limite mal formée dans config.yaml (%r attendu HH:MM)",
                           heure_limite)

    # Repli manuel (data/overrides/{date}.json) : priorité systématique sur la
    # donnée automatique, pour n'importe quel indicateur. Lecture seule — le
    # pipeline n'écrit jamais dans ce dossier.
    overrides_du_jour = overrides.charger(donnees_dir / "overrides", date.today())

    # ---------------------------------------------------------------- collecte
    # Séquentielle par construction : jamais d'appels parallèles sur les sites.
    # Twelve Data / FRED / RSS : en mode --completer, cache "1 collecte/jour"
    # (core/collecte_cache.py) — réutilise le résultat du run complet du
    # matin plutôt que de reconsommer du quota API pour des données qui n'ont
    # probablement pas bougé entre deux passages du même jour. Le scraping des
    # 6 sites a déjà sa propre protection équivalente (core/scraping.py).
    dossier_cache = donnees_dir / "cache"

    def _collecter(nom: str, fonction, *args):
        return collecte_cache.avec_cache(nom, dossier_cache, date.today(),
                                         arguments.completer, fonction, *args)

    vide = {"erreurs": ["étape en échec"]}
    technique = etape("collecte technique (Twelve Data)",
                      _collecter, "technique", collecte_technique.collecter, config,
                      defaut={**vide, "devises": {}, "graphiques": {}, "prix_cloture": {},
                              "correlations": {}})
    macro = etape("collecte macro (FRED)",
                  _collecter, "macro", collecte_macro.collecter, config,
                  defaut={**vide, "series": {}, "yield_curve": {"disponible": False},
                          "taux_directeurs": {}})
    news = etape("collecte news (RSS)",
                 _collecter, "news", collecte_news.collecter, config, config["scraping"]["user_agent"],
                 defaut={**vide, "articles": [], "flux": {}})
    client_scraping = ClientScraping(config["scraping"], donnees_dir / "cache")
    calendrier = etape("collecte calendrier (scraping faible empreinte)",
                       collecte_calendrier.collecter, config, client_scraping,
                       defaut={**vide, "evenements": [], "sites": {}, "non_rafraichies": []})

    if not technique["devises"] and not macro["series"]:
        notifier_echec("collecte", "aucune donnée technique NI macro — rapport annulé")
        return 1

    # ---------------------------------------------------------------- analyse
    try:
        llm = creer_fournisseur(config)
        rapport = etape("agent stratège", agent_strategiste.analyser,
                        config, llm, technique, macro, news, calendrier,
                        dossier_rapports, type_rapport, overrides_du_jour, rapport_existant,
                        fatal=True)
    except Exception:  # noqa: BLE001
        return 1

    rapport = valider_rapport(rapport, config.get("tracabilite", {}).get("mode", "marquer"))

    # ------------------------------------------- contrôle qualité (chaque run)
    rapport["controle_qualite"] = etape(
        "contrôle qualité", controle_qualite.controler, rapport, config,
        defaut={"conforme": False, "nb_anomalies": 1,
                "anomalies": ["contrôle qualité en échec"]})

    # -------------------------------- base hebdomadaire cumulative (chaque jour)
    dossier_hebdo = donnees_dir / "hebdo"
    etape("base hebdomadaire cumulative", hebdo.upsert_jour, dossier_hebdo, rapport)

    # Sparkline 7 jours (dashboard web) : relit la base qu'on vient d'écrire,
    # aucune nouvelle collecte. Un échec ne prive que du mini-graphique.
    def _injecter_historique() -> None:
        for dev in rapport.get("devises", []):
            dev["historique_score_7j"] = hebdo.historique_recent(
                dossier_hebdo, dev["devise"], date.today(), jours=7)
    etape("historique 7 jours (sparklines)", _injecter_historique)

    # ------------------------- auto-évaluation + analyse weekly (hebdo/mensuel)
    if type_rapport in ("hebdomadaire", "mensuel"):
        precedent = evaluation.charger_rapport_precedent(dossier_rapports, jours=7)
        if precedent:
            resultat = etape("auto-évaluation hebdomadaire", evaluation.evaluer,
                             precedent, rapport.get("prix_cloture", {}),
                             float(config.get("evaluation", {}).get("seuil_neutre_pct", 0.15)))
            if resultat:
                resultat["commentaire_llm"] = agent_strategiste.commenter_auto_evaluation(
                    llm, resultat)
                rapport["auto_evaluation"] = resultat
        else:
            log.info("Pas de rapport J-7 : auto-évaluation sautée (normal au démarrage)")

        def _analyse_weekly() -> dict:
            analyses = {}
            for devise in config["devises"]:
                contenu = hebdo.charger_semaine(dossier_hebdo, devise, date.today())
                if not contenu or not contenu.get("jours"):
                    continue
                metriques = hebdo.metriques_semaine(contenu)
                analyse = {
                    "semaine_iso": contenu["semaine_iso"],
                    "metriques": metriques,
                    "commentaire": agent_strategiste.commenter_analyse_weekly(
                        llm, devise, metriques),
                }
                hebdo.enregistrer_analyse(dossier_hebdo, devise, date.today(), analyse)
                analyses[devise] = analyse
            return analyses

        analyses = etape("analyse weekly (base cumulative)", _analyse_weekly, defaut={})
        if analyses:
            rapport["analyse_weekly"] = analyses

    # --------------------------------------------------------------- critique
    rapport = etape("agent critique", agent_critique.critiquer, llm, rapport,
                    defaut=rapport)

    # ------------------------------------------------------------- sauvegarde
    chemin = dossier_rapports / f"{rapport['meta']['date_rapport']}.json"
    chemin.write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Rapport sauvegardé : %s", chemin)

    # ------------------------------------------------------------ publication
    if not arguments.sans_notion:
        etape("publication Notion (base de données)", agent_redacteur.publier,
              config, rapport, RACINE / "config.yaml")
    if not arguments.sans_web and config.get("publication_web", {}).get("actif", True):
        etape("publication web (docs/)", publication_web.ecrire_donnees,
              rapport, RACINE / config["publication_web"]["dossier_docs"])
        etape("git push (GitHub Pages)", publication_web.pousser_git,
              config["publication_web"], RACINE)

    critique = rapport.get("critique", {})
    log.info("=== Terminé : biais %s, relecture %s, %d donnée(s) non rafraîchie(s) ===",
             rapport["synthese_globale"]["biais_macro_global"],
             critique.get("validation", "?"), len(rapport.get("donnees_non_rafraichies", [])))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Sans ceci, un Ctrl+C pendant une pause de scraping ne laisse AUCUNE
        # trace dans le log — le run semble s'être évaporé.
        logging.getLogger("orchestrateur").warning("Interrompu manuellement (Ctrl+C)")
        sys.exit(130)
