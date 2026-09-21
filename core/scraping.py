"""Client de scraping "faible empreinte".

Garanties codées ici, non contournables par les agents :
- une seule requête réussie par site et par jour (cache journalier) ;
- un essai + un seul retry ; en cas d'échec, repli sur la donnée de la veille
  avec mention "non rafraîchi aujourd'hui" ;
- un 403 n'est JAMAIS retenté dans la même exécution ; après N réponses 403
  cumulées, le site est mis en blacklist persistante (les autres continuent) ;
- robots.txt respecté (si interdit : aucune requête envoyée) ;
- User-Agent de navigateur standard, jamais vide ;
- aucun appel parallèle : l'appelant itère séquentiellement et insère
  attendre_entre_sites() entre chaque site.
"""
from __future__ import annotations

import json
import logging
import random
import time
from datetime import date
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)


class ClientScraping:
    def __init__(self, config_scraping: dict, dossier_cache: str | Path):
        self.cfg = config_scraping
        self.dossier = Path(dossier_cache)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.ua = self.cfg["user_agent"]
        self.seuil_403 = int(self.cfg.get("seuil_blacklist_403", 2))
        self.delai_min = float(self.cfg.get("delai_min_s", 5))
        self.delai_max = float(self.cfg.get("delai_max_s", 90))
        self._fichier_403 = self.dossier / "blacklist_403.json"
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}

    # ------------------------------------------------------------------ délais
    def attendre_entre_sites(self) -> None:
        pause = random.uniform(self.delai_min, self.delai_max)
        log.info("Pause aléatoire de %.0f s avant le site suivant", pause)
        time.sleep(pause)

    # ------------------------------------------------------- blacklist 403
    def _compteurs_403(self) -> dict:
        try:
            return json.loads(self._fichier_403.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _incrementer_403(self, site: str) -> None:
        compteurs = self._compteurs_403()
        compteurs[site] = {
            "compteur": compteurs.get(site, {}).get("compteur", 0) + 1,
            "derniere": date.today().isoformat(),
        }
        self._fichier_403.write_text(json.dumps(compteurs, indent=2), encoding="utf-8")

    def site_bloque(self, site: str) -> bool:
        return self._compteurs_403().get(site, {}).get("compteur", 0) >= self.seuil_403

    # ------------------------------------------------------------- robots.txt
    def _robots_autorise(self, url: str) -> bool:
        origine = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if origine not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                rep = requests.get(
                    f"{origine}/robots.txt",
                    headers={"User-Agent": self.ua},
                    timeout=15,
                )
                if rep.status_code == 200:
                    rp.parse(rep.text.splitlines())
                    self._robots[origine] = rp
                else:
                    # robots.txt absent ou inaccessible : pas d'interdiction explicite.
                    self._robots[origine] = None
            except requests.RequestException:
                self._robots[origine] = None
        rp = self._robots[origine]
        return True if rp is None else rp.can_fetch(self.ua, url)

    # ------------------------------------------------------------------ cache
    def _chemin_cache(self, site: str) -> Path:
        return self.dossier / f"scrape_{site}.json"

    def _lire_cache(self, site: str) -> dict | None:
        try:
            return json.loads(self._chemin_cache(site).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _ecrire_cache(self, site: str, jour: str, contenu: str) -> None:
        self._chemin_cache(site).write_text(
            json.dumps({"date": jour, "contenu": contenu}), encoding="utf-8"
        )

    # -------------------------------------------------------------- requête
    def recuperer(self, site: str, url: str) -> dict:
        """Récupère la page du jour (ou le cache). Retour :
        {statut: frais|cache|indisponible, non_rafraichi, date_donnee, contenu, note}
        """
        auj = date.today().isoformat()
        cache = self._lire_cache(site)

        # Une seule requête par jour et par site : si déjà fait aujourd'hui, cache.
        if cache and cache.get("date") == auj:
            return {
                "statut": "frais", "non_rafraichi": False, "date_donnee": auj,
                "contenu": cache["contenu"], "note": "cache journalier (déjà récupéré aujourd'hui)",
            }
        if self.site_bloque(site):
            return self._repli(site, cache, f"blacklist après {self.seuil_403} réponses 403 — tentatives arrêtées sur ce site")
        if not self._robots_autorise(url):
            return self._repli(site, cache, "robots.txt interdit cette URL — aucune requête envoyée")

        derniere_erreur = "inconnue"
        for tentative in (1, 2):  # un essai + un seul retry, jamais plus
            try:
                rep = requests.get(
                    url,
                    headers={"User-Agent": self.ua, "Accept-Language": "en;q=0.9,fr;q=0.8"},
                    timeout=30,
                )
                if rep.status_code == 403:
                    self._incrementer_403(site)
                    derniere_erreur = "HTTP 403"
                    break  # ne jamais insister sur un 403
                rep.raise_for_status()
                self._ecrire_cache(site, auj, rep.text)
                log.info("Site %s récupéré (%d octets)", site, len(rep.text))
                return {
                    "statut": "frais", "non_rafraichi": False, "date_donnee": auj,
                    "contenu": rep.text, "note": "",
                }
            except requests.RequestException as exc:
                derniere_erreur = str(exc)[:200]
                if tentative == 1:
                    time.sleep(random.uniform(3, 8))
        return self._repli(site, cache, f"échec ({derniere_erreur})")

    def _repli(self, site: str, cache: dict | None, raison: str) -> dict:
        log.warning("Site %s non rafraîchi : %s", site, raison)
        if cache:
            return {
                "statut": "cache", "non_rafraichi": True, "date_donnee": cache.get("date"),
                "contenu": cache["contenu"], "note": raison,
            }
        return {
            "statut": "indisponible", "non_rafraichi": True, "date_donnee": None,
            "contenu": None, "note": raison,
        }
