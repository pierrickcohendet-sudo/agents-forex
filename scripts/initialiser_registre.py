"""Remplissage INITIAL du registre macro (à lancer à la main, une seule fois).

Lit plusieurs pages « mois » de ForexFactory (par défaut : les 4 mois passés +
le mois en cours + le mois suivant) et les intègre ENSEMBLE dans le registre :
les publications sont rejouées chronologiquement, ce qui construit l'historique
(dates des « précédent », base de l'indice de surprise) et fournit les
publications trimestrielles (PIB, CPI/emploi néo-zélandais…) absentes du seul
mois en cours.

Faible empreinte : une requête par mois, 15-30 s entre deux, robots.txt, pas de
retry sur 403, chaque requête comptée dans le budget quotidien
(data/cache/forexfactory_requetes.json). Sans danger à relancer : l'intégration
est idempotente.

    python scripts/initialiser_registre.py                  # réseau (6 requêtes)
    python scripts/initialiser_registre.py --mois jul.2026 aug.2026 last this next
    python scripts/initialiser_registre.py --fichiers a.html b.html   # hors ligne
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from agents.collecte_forexfactory_mois import parser_page  # noqa: E402
from core import registre_macro as rm  # noqa: E402
from core.scraping import ClientScraping  # noqa: E402

MOIS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def mois_par_defaut(n_passes: int = 4) -> list[str]:
    auj = date.today()
    liste = []
    for k in range(n_passes, 0, -1):
        m = auj.month - k
        a = auj.year + (m - 1) // 12
        liste.append(f"{MOIS[(m - 1) % 12]}.{a}")
    return liste + ["this", "next"]


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parseur.add_argument("--mois", nargs="+", help="ex. jul.2026 aug.2026 last this next")
    parseur.add_argument("--fichiers", nargs="+", help="pages HTML déjà enregistrées (hors ligne)")
    parseur.add_argument("--requetes-deja-faites", type=int, default=0,
                         help="requêtes manuelles à ajouter au budget du jour")
    args = parseur.parse_args()
    load_dotenv(RACINE / ".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("init-registre")
    config = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
    cfg_tm = config["tableau_macro"]
    donnees = RACINE / config["chemins"]["donnees"]
    chemin_budget = donnees / "cache" / "forexfactory_requetes.json"
    maintenant = datetime.now(timezone.utc)

    pages: list[str] = []
    horodatages: list[str] = []
    if args.fichiers:
        pages = [Path(f).read_text(encoding="utf-8") for f in args.fichiers]
    else:
        client = ClientScraping(config["scraping"], donnees / "cache")
        for i, mois in enumerate(args.mois or mois_par_defaut()):
            if i:
                time.sleep(random.uniform(15, 30))
            url = f"https://www.forexfactory.com/calendar?month={mois}"
            res = client.requete_directe("forexfactory_mois", url)
            horodatages.append(datetime.now(timezone.utc).isoformat(timespec="seconds"))
            if res["contenu"] is None:
                log.error("Mois %s indisponible (%s) — arrêt, pas d'insistance", mois, res["note"])
                break
            pages.append(res["contenu"])
            log.info("Mois %s récupéré", mois)

    horodatages += [maintenant.isoformat(timespec="seconds")] * args.requetes_deja_faites
    if horodatages:
        try:
            budget = json.loads(chemin_budget.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            budget = {}
        existants = budget.get("horodatages", []) if budget.get("date") == maintenant.date().isoformat() else []
        chemin_budget.write_text(json.dumps({"date": maintenant.date().isoformat(),
                                             "horodatages": existants + horodatages}, indent=1),
                                 encoding="utf-8")

    evenements = [e for html in pages for e in parser_page(html)]
    registre = rm.charger(RACINE / config["chemins"]["donnees"] / "registre_macro.json")
    bilan = rm.integrer_evenements(registre, evenements, cfg_tm, maintenant)
    rm.sauver(registre, RACINE / config["chemins"]["donnees"] / "registre_macro.json")
    log.info("Registre : %d case(s) mises à jour, %d introuvable(s) : %s", bilan["mises_a_jour"],
             len(bilan["introuvables"]), ", ".join(bilan["introuvables"]) or "aucune")
    return 0


if __name__ == "__main__":
    sys.exit(main())
