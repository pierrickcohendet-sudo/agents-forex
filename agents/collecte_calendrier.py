"""Collecte "faible empreinte" des sites complémentaires.

- ForexFactory : flux JSON hebdomadaire officiel (prévision / précédent / réel).
- TradingView, Mataf, FinancialJuice : pages publiques, extraction best-effort
  (beaucoup de contenu y est rendu en JavaScript ; si rien d'exploitable n'est
  extrait, on le dit explicitement — les corrélations utilisées par le rapport
  restent de toute façon celles calculées localement via Twelve Data).

Toutes les garanties (1 requête/jour, robots.txt, retry unique, blacklist 403,
délais aléatoires entre sites, jamais de parallèle) sont dans core/scraping.py.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from core.scraping import ClientScraping

log = logging.getLogger(__name__)

# Rétention du magasin de STOCKAGE (data/cache/evenements_glissants.json),
# volontairement un peu plus large que la fenêtre envoyée au LLM (marge pour
# le repli 7j de _tableau_indicateurs et pour absorber un jour de collecte
# manqué sans perdre un événement encore utile). Ceci ne garantit PAS à lui
# seul ce qui part dans le prompt LLM : agent_strategiste.assembler_contexte()
# applique son propre filtre STRICT et indépendant (fenetre_jours, 7 par
# défaut) sur les événements avant de les injecter au contexte — les deux
# fenêtres sont volontairement découplées (incident du 2026-08-29 : croire
# que cette seule constante suffisait avait laissé fuiter 10 jours au LLM).
RETENTION_JOURS = 10


def _fusionner_glissants(evenements_du_jour: list[dict], dossier_cache: Path) -> list[dict]:
    """Magasin cumulatif d'événements : le flux ForexFactory ne couvre que la
    semaine courante, on accumule donc jour après jour pour permettre la règle
    de repli à 7 jours (dernière valeur connue + date d'origine)."""
    chemin = dossier_cache / "evenements_glissants.json"
    try:
        anciens = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        anciens = []

    def cle(evt: dict) -> tuple:
        return (evt.get("devise"), evt.get("evenement"), evt.get("date"))

    fusion = {cle(e): e for e in anciens}
    fusion.update({cle(e): e for e in evenements_du_jour})  # le frais écrase l'ancien
    limite = (date.today() - timedelta(days=RETENTION_JOURS)).isoformat()
    gardes = sorted(
        (e for e in fusion.values() if e.get("date") and e["date"] >= limite),
        key=lambda e: e["date"], reverse=True,
    )
    chemin.write_text(json.dumps(gardes, ensure_ascii=False), encoding="utf-8")
    return gardes

PAYS_VERS_DEVISE = {
    "USD": "USD", "EUR": "EUR", "GBP": "GBP", "JPY": "JPY",
    "CHF": "CHF", "CAD": "CAD", "AUD": "AUD", "NZD": "NZD", "CNY": "CNY",
}


def _parser_forexfactory(brut: str, devises: set[str]) -> list[dict]:
    evenements = []
    for item in json.loads(brut):
        devise = PAYS_VERS_DEVISE.get(str(item.get("country", "")).upper())
        # La Chine (CNY) est conservée : AUD/NZD en sont des proxys (cf. connaissances).
        if devise is None or (devise not in devises and devise != "CNY"):
            continue
        date_brute = item.get("date")
        try:
            date_iso = datetime.fromisoformat(date_brute).date().isoformat() if date_brute else None
        except ValueError:
            date_iso = None
        evenements.append({
            "devise": devise,
            "evenement": str(item.get("title", ""))[:150],
            "impact": str(item.get("impact", "")),
            "date": date_iso,
            "prevision": item.get("forecast") or None,
            "precedent": item.get("previous") or None,
            "reel": item.get("actual") or None,
            "source": "ForexFactory",
        })
    return evenements


SELECTEURS_GENERIQUES = '[class*="headline"], [class*="news-item"], [class*="title"], h2, h3'


def _extraire_titres_html(brut: str, selecteurs: str | None = None) -> list[str]:
    soup = BeautifulSoup(brut, "lxml")
    candidats = soup.select(selecteurs) if selecteurs else []
    if not candidats:
        candidats = soup.select(SELECTEURS_GENERIQUES)
    titres, vus = [], set()
    for element in candidats:
        texte = element.get_text(" ", strip=True)
        if 25 <= len(texte) <= 220 and texte not in vus:
            vus.add(texte)
            titres.append(texte)
        if len(titres) >= 25:
            break
    return titres


def collecter(config: dict, client: ClientScraping) -> dict:
    resultat: dict = {"evenements": [], "sites": {}, "non_rafraichies": []}
    devises = set(config["devises"].keys())
    premier = True

    for nom, site in config["scraping"]["sites"].items():
        if not site.get("actif", True):
            continue
        if not premier:
            client.attendre_entre_sites()  # délai aléatoire imposé entre chaque site
        premier = False

        res = client.recuperer(nom, site["url"])
        info = {"statut": res["statut"], "date_donnee": res["date_donnee"],
                "note": res.get("note", "")}
        if res["non_rafraichi"]:
            resultat["non_rafraichies"].append({
                "source": nom,
                "derniere_donnee_du": res["date_donnee"],
                "raison": res.get("note", "non rafraîchi aujourd'hui"),
            })
        if res["contenu"] is None:
            resultat["sites"][nom] = info
            continue

        try:
            if site.get("type") == "json" and nom == "forexfactory":
                evenements = _parser_forexfactory(res["contenu"], devises)
                info["nb_evenements_frais"] = len(evenements)
                # Le rapport travaille sur le magasin GLISSANT (repli 7 jours),
                # pas seulement sur la semaine renvoyée aujourd'hui.
                resultat["evenements"] = _fusionner_glissants(evenements, client.dossier)
                info["nb_evenements_glissants"] = len(resultat["evenements"])
            else:
                titres = _extraire_titres_html(res["contenu"], site.get("selecteurs"))
                info["titres"] = titres
                if not titres:
                    info["note"] = (info["note"] + " | " if info["note"] else "") + \
                        "contenu dynamique non exploitable côté serveur"
        except (json.JSONDecodeError, ValueError) as exc:
            info["note"] = f"parsing en échec : {exc}"
            log.warning("Parsing %s en échec : %s", nom, exc)
        resultat["sites"][nom] = info

    if not resultat["evenements"]:
        # ForexFactory indisponible : on sert quand même le magasin glissant.
        resultat["evenements"] = _fusionner_glissants([], client.dossier)

    log.info("Collecte calendrier : %d événement(s), %d site(s) non rafraîchi(s)",
             len(resultat["evenements"]), len(resultat["non_rafraichies"]))
    return resultat
