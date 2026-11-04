# Design du site (lot V7)

Référence : `maquette_v7.html` (spécification : tokens, classes, structure) et ses captures dans `reference/`
(6 onglets × clair/sombre × 1280/390 px). Tokens : `docs/site/tokens.css` ; composants : `docs/site/v7.css`.

## Règles

- **Chiffres** en police normale (Instrument Sans) avec `font-variant-numeric: tabular-nums`, **jamais en monospace**.
  Le monospace (JetBrains Mono) est réservé aux codes techniques.
- **Un chiffre clé en gros, le contexte en petit.** Une carte plutôt qu'un tableau quand il y a moins de 4 colonnes.
- **Une seule couleur d'accent** (`--accent`). Vert (`--up`) et rouge (`--down`) réservés à hausse et baisse ;
  orange (`--warn`) réservé à « proche du seuil ».
- **Chaque graphique a sa source et sa date. Chaque « n/d » a sa raison au survol** (`nd(raison)` dans
  `v7_commun.js`), jamais la raison complète dans la cellule.
- **Transitions de 200 à 400 ms** (`--ease`), désactivées avec `prefers-reduced-motion`.
- Le JavaScript **affiche** seulement : scores, états, directions, couleurs de sens, rangs et force des devises
  viennent des JSON produits en Python. Seul le calculateur de taille de position calcule dans le navigateur (outil).
- Vue complète / essentielle : les blocs `.full` n'apparaissent qu'en vue complète. Une fonctionnalité absente de la
  maquette va en vue complète (bloc « version détaillée ») ou dans le menu « Plus », jamais supprimée.
- Graphiques : Lightweight Charts 4.2.0 en local (`docs/site/vendor/`, Apache 2.0, logo TradingView visible),
  initialisés à l'ouverture de leur onglet puis `fitContent()` ; micro-graphiques en SVG maison (`spark`).
- Aucun débordement horizontal à 390 px : les tableaux larges défilent dans leur cadre `.scroll`.

## Vérification obligatoire

**Toute modification visuelle est comparée aux captures de `docs/design/reference/`** avant de rendre un rapport :

```bash
node outils/captures.mjs "http://localhost:4173/" captures/<lot>
```

Le script capture les 6 onglets en clair et en sombre, à 1280 et 390 px, page entière, et signale tout débordement
horizontal. Comparer côte à côte avec `docs/design/reference/` et lister les écarts restants.
