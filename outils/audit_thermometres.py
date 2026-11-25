"""Audit des 8 thermomètres du cockpit (lot V14, correctif V13.1) : date de la mesure affichée comparée à la date du
dernier point disponible dans la série quotidienne correspondante.

Usage : python outils/audit_thermometres.py [docs/data/dossiers.json]
Une ligne par thermomètre : valeur, date de la mesure, source, dernier point disponible (série et date), retard en jours.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

# Thermomètre -> série quotidienne qui le mesure (cache 5 ans) ; None : mesure du jour (titres, thème, calcul local)
SERIES = {2: "USD_2a", 4: "USD_prime_terme", 5: "vix", 8: "brent"}


def auditer(dossiers: dict, h5, technique: dict | None = None, aujourd: date | None = None) -> list[dict]:
    aujourd = aujourd or date.today()
    sortie = []
    for t in ((dossiers.get("cockpit") or {}).get("thermometres") or []):
        n = t["numero"]
        cle = SERIES.get(n)
        dernier = None
        if cle and h5 is not None:
            s = h5.serie(cle)
            dernier = s[-1][0] if s else None
        if n == 3:
            dernier = t.get("date")
        d_mesure = str(t.get("date") or "")[:10] or None
        retard = (date.fromisoformat(dernier) - date.fromisoformat(d_mesure)).days if dernier and d_mesure else None
        sortie.append({"numero": n, "libelle": t.get("libelle"), "valeur": t.get("valeur"), "texte": t.get("texte_valeur"),
                       "date": d_mesure, "source": t.get("source"), "etat": t.get("etat"),
                       "direction": (t.get("direction") or {}).get("libelle"), "serie": cle, "dernier_point": dernier,
                       "retard_jours": retard,
                       "verdict": ("série plus récente que la mesure" if retard and retard > 0 else
                                   "à jour" if retard is not None else "mesure du jour (pas de série quotidienne)")})
    return sortie


def main() -> None:
    from core import historique_5ans
    chemin = Path(sys.argv[1]) if len(sys.argv) > 1 else RACINE / "docs" / "data" / "dossiers.json"
    d = json.loads(chemin.read_text(encoding="utf-8"))
    for l in auditer(d, historique_5ans.charger()):
        print(f"{l['numero']} | {l['libelle']} | {l['texte']} au {l['date']} | {l['etat']} | {l['direction']} | "
              f"série {l['serie'] or '—'} jusqu'au {l['dernier_point'] or '—'} | {l['verdict']}")
    e = (d.get("cockpit") or {}).get("entete") or {}
    print(f"Thème : {e.get('titre')} ; moteurs alignés : {e.get('alignes')} sur {e.get('evaluables')}")


if __name__ == "__main__":
    main()
