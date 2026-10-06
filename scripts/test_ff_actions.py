"""Diagnostic ponctuel : la page « mois » de ForexFactory répond-elle depuis
un runner GitHub Actions (et pas seulement depuis un PC) ? Écrit le résultat
dans data/diagnostics/ff_actions.json (committé par le workflow test_ff.yml)
pour pouvoir le lire sans accès aux logs Actions. Une seule requête sur la
page, une sur l'export officiel — jamais de retry."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.collecte_forexfactory_mois import parser_page  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def tester(url: str) -> dict:
    debut = time.monotonic()
    try:
        rep = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=40)
    except requests.RequestException as exc:
        return {"url": url, "erreur": type(exc).__name__}
    res = {
        "url": url, "http": rep.status_code, "octets": len(rep.content),
        "duree_s": round(time.monotonic() - debut, 1),
        "serveur": rep.headers.get("server"),
        "cf_mitigated": rep.headers.get("cf-mitigated"),
        "page_defi_cloudflare": "Just a moment" in rep.text[:5000],
    }
    if "calendar?month" in url and rep.status_code == 200:
        try:
            ev = parser_page(rep.text)
            res.update(parse_ok=True, nb_evenements=len(ev),
                       nb_avec_reel=sum(1 for e in ev if e["reel"]),
                       nb_avec_prevision=sum(1 for e in ev if e["prevision"]))
        except ValueError as exc:
            res.update(parse_ok=False, parse_erreur=str(exc))
    return res


def main() -> int:
    sortie = {
        "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "github_actions": os.environ.get("GITHUB_ACTIONS") == "true",
        "page_mois": tester("https://www.forexfactory.com/calendar?month=this"),
    }
    time.sleep(10)
    sortie["export_officiel_json"] = tester("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    chemin = Path(__file__).resolve().parents[1] / "data" / "diagnostics" / "ff_actions.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(sortie, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
