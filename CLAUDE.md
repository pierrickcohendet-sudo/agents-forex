# agents-forex

Aide à la décision FX (9 devises) : pipeline Python (`orchestrateur.py`, `core/`, `agents/`) qui publie `docs/data/*.json`,
site statique `docs/` (GitHub Pages). Jamais d'ordre d'achat ou de vente ; tout calcul en Python ; chaque chiffre sourcé et
daté, sinon « n/d » avec sa raison. Tests : `.venv/Scripts/python.exe -m pytest -q`. Avant tout push :
`python outils/attendre_runs.py` (jamais pendant un run « rapport-fx »).

## Design

- **Lire `docs/design/DESIGN.md` avant toute modification visuelle** du site.
- **Comparer ses captures à la référence** (`docs/design/reference/`, produites depuis `docs/design/maquette_v7.html`)
  avant de rendre un rapport : `node outils/captures.mjs "http://localhost:4173/" captures/<lot>`, puis lister les écarts.
