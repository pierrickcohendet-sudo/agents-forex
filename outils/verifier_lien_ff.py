"""Vérification du format des liens ForexFactory (lot V14, A1.1) : UNE requête, comptée dans le plafond du jour.

La page lue est le premier mois de la reprise de l'historique (oct.2026) : la requête sert aussi à la reprise. Le script
respecte robots.txt et le plafond (data/cache/forexfactory_requetes.json) ; il n'insiste jamais après un refus.
Il compare, pour chaque publication, le jour du lien fourni par ForexFactory (« url ») à la date de la publication dans
plusieurs fuseaux, et affiche 3 exemples de liens.
Usage : python outils/verifier_lien_ff.py [mois]   (mois par défaut : le premier mois restant de la reprise)
"""
from __future__ import annotations

import collections
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
MOIS_EN = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def main() -> int:
    import yaml
    from agents import collecte_forexfactory_mois as ffm
    from core import ff_historique as ffh
    from core.scraping import ClientScraping
    config = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
    cfg_tm = config["tableau_macro"]
    cache = RACINE / "data" / "cache"
    maintenant = datetime.now(timezone.utc)
    d = ffh.lire(cache)
    mois = sys.argv[1] if len(sys.argv) > 1 else (ffh.etat(d, maintenant.date())["restants"] or ["this"])[0]
    budget = ffm._lire_budget(cache / "forexfactory_requetes.json", maintenant.date().isoformat())
    plafond = int(cfg_tm["forexfactory"].get("plafond_requetes_par_jour", 6))
    if len(budget["horodatages"]) >= plafond:
        print(f"Plafond de {plafond} requêtes atteint aujourd'hui ({maintenant.date()}) : aucune requête.")
        return 1
    client = ClientScraping(config["scraping"], cache)
    res = ffm._requete(cfg_tm, client, mois, budget, cache / "forexfactory_requetes.json", maintenant.date().isoformat(), maintenant)
    print(f"Requête {len(budget['horodatages'])}/{plafond} du {maintenant.date()} : page « {mois} » -> {res['statut']} {res['note']}")
    if res["statut"] != "frais":
        return 1
    evs = res["evenements"]
    if mois != "this":   # la requête sert aussi à la reprise de l'historique
        x = d.setdefault("mois", {}).setdefault(mois, {})
        n = ffh.integrer(d, evs)
        x.update(statut="lu", lu_le=maintenant.isoformat(timespec="seconds"), tente_le=maintenant.isoformat(timespec="seconds"),
                 n=len(evs), points=n, note="lu par outils/verifier_lien_ff.py (vérification du format des liens)")
        d.setdefault("debut", maintenant.date().isoformat())
        ffh.ecrire(cache, d)
        print(f"Historique : {mois} intégré ({len(evs)} publications, {n} points)")
    formats, accords = collections.Counter(), collections.Counter()
    exemples = []
    for e in evs:
        u = str(e.get("url") or "")
        m = re.search(r"day=([a-z]{3})(\d+)\.(\d{4})#detail=(\d+)$", u)
        formats["/calendar?day=<mois><jour>.<année>#detail=<id>" if m else (u or "(vide)")[:60]] += 1
        if not m or not e.get("dateline"):
            continue
        jour = f"{m.group(3)}-{MOIS_EN.index(m.group(1)) + 1:02d}-{int(m.group(2)):02d}"
        t = datetime.fromtimestamp(int(e["dateline"]), tz=timezone.utc)
        for z in ("UTC", "America/New_York", "Europe/Paris"):
            accords[z] += t.astimezone(ZoneInfo(z)).date().isoformat() == jour
        if int(m.group(4)) != e.get("id"):
            accords["identifiant différent"] += 1
        if len(exemples) < 3 and e.get("impact") == "high":
            exemples.append((e.get("devise"), e.get("nom"), t.isoformat(timespec="minutes"), "https://www.forexfactory.com" + u))
    print("Formats :", dict(formats))
    print("Jour du lien = date de la publication dans le fuseau :", dict(accords), "sur", sum(1 for e in evs if e.get("url")))
    for x in exemples:
        print("Exemple :", *x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
