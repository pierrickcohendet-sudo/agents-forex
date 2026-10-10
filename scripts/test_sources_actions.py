"""Diagnostic ponctuel (8 engrenages, palier 2) : CFTC, EIA et FRED (or) répondent-ils depuis un runner
GitHub Actions ? Utilise le VRAI collecteur (agents/collecte_flux.py) et écrit un résumé sans secret
dans data/diagnostics/sources_palier2.json."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
from agents import collecte_flux  # noqa: E402

r = collecte_flux.collecter({})
resume = {
    "execute_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "cot": {d: {k: v[k] for k in ("date", "net", "variation_semaine", "percentile_52s")} for d, v in r["cot"].items()},
    "eia": r["eia"], "or": r["or"], "erreurs": r["erreurs"],
}
sortie = RACINE / "data" / "diagnostics" / "sources_palier2.json"
sortie.parent.mkdir(parents=True, exist_ok=True)
sortie.write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(resume, ensure_ascii=False, indent=1))
