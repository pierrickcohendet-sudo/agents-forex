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

## Lot V8

- Références supplémentaires : `maquette_v8.html` et `reference/v8/` (Briefing, Paires, Journal ; clair et sombre, 1280 et 390 px).
  Composants : `docs/site/v8.css`. Capturer les 8 onglets :
  `node outils/captures.mjs "http://localhost:4173/" captures/<lot> briefing,synthese,tableau,paire,devises,agenda,engrenages,journal`.
- Seules exceptions au « tout en Python » : l'heure (comptes à rebours, ligne « maintenant », temps relatifs) et les
  statistiques du Journal, calculées sur l'appareil à partir des trades privés (`journal_stats.js`, fonctions pures testées).
- Point de fraîcheur sur les blocs de données : règle calculée en Python (`fraicheur.json`), infobulle « mis à jour le … ».
- Mouvement : chiffres qui défilent (300 ms, une seule fois par valeur), courbes qui se dessinent, panneau qui glisse ;
  tout est coupé avec `prefers-reduced-motion`.

### V8.1

- Fraîcheur : chaque série jugée sur sa dernière observation et sa fréquence normale ; le point prend la couleur de la série la plus en retard, l'infobulle la nomme.
- Journal sans trade : état d'accueil centré (`.j-accueil`), « Ton premier trade apparaîtra ici », boutons « + Nouvelle entrée » et « Voir avec des exemples » ; les blocs de statistiques sont masqués (`#jStats`).

### V8.2 — page Paire enrichie

- Sélecteur : menu en 3 groupes (Mes paires, Majeures, Croisées), cours et variation du jour calculés en Python.
- Graphique : calques dans l'ordre Veille, Semaine précédente, Session Asie, Supports et résistances, Lignes de tendance,
  Zones FVG, BOS et CHoCH, Publications, Moyennes mobiles, RSI ; choix mémorisés (`fxdesk-calques`).
- Panneau RSI 14 de 120 px (100 px à 390 px) synchronisé (défilement, curseur), lignes 70/50/30, zones teintées.
- Zones S/R : bandes de deux lignes, opacité et épaisseur selon la force ; étiquettes limitées à R1, R2, S1, S2.
- Lignes de tendance : pleines si valides, pointillées et estompées si cassées depuis moins de 5 bougies.
- Carte « Écart de taux » : deux graphiques empilés et synchronisés (paire, écart en pb), jamais deux axes sur un graphique.
- Données : `paires.json` léger + `paires/XXX-YYY.json` chargé à l'ouverture de la paire (`paire_graphique.js` dessine).

### Correctif du 11/11 — versions, adresses, erreurs

- Service worker : une version = un jeu complet de fichiers pré-chargé à l'installation (`FICHIERS`, écrit par
  `core/version_site.py`). Pas d'activation en pleine session : bandeau « Nouvelle version disponible : Recharger »,
  activation automatique seulement juste après un chargement. Jamais d'ancien et de nouveau code mélangés.
- Toute adresse de détail ouvre quelque chose : `#devises/EUR` (carte mise en avant, fiche détaillée ouverte),
  `#paire/USD-JPY`, `#engrenages/g=3`, `#engrenages/hebdo|mensuel|quotidien|outils`. Un écran expose `section.allerA(param)`.
- Erreur d'affichage : message exact, bouton « Recharger », le reste du site reste utilisable (écran reconstruit à la visite suivante).
- Un graphique retiré sort du registre (`retirerGraphique`) et ses abonnements de synchronisation sont coupés.
- Vérification : `node outils/verifier_adresses.mjs <url> [--mobile]` (onglets, 9 devises, 36 paires, 8 engrenages ; en local et en ligne).

## Lot V9 — la Synthèse en rapport quotidien (livraison 1)

- Référence : `maquette_v9_synthese.html` et ses captures `reference/v9/` (clair et sombre, 1280 et 390 px). Composants :
  `docs/site/v9.css` (règles de la maquette préfixées par `.v9`, générées depuis la maquette), écran `synthese_v9.js`.
- Données : `synthese.json` (13 sections, `core/synthese_v9.py`). En semaine, la Synthèse affiche la V9 ; le week-end, ou si
  `synthese.json` a plus de 4 jours, la version précédente reste. Le rapport détaillé V8 reste dans « Rapport détaillé ».
- Sommaire collant avec barre de progression ; sur téléphone (< 1100 px), barre horizontale qui défile et suit la lecture.
- Bouton « Sources » (ancien « Origine des données ») : chiffres soulignés, source et date au survol ; choix mémorisé.
- Chaque section indique sa rédaction : point vert « texte du modèle » (nombres vérifiés en Python) ou point orange
  « rédaction automatique » (texte Python). Une section en erreur affiche sa raison, les autres restent.
- Graphiques : Brent 6 mois (prix EIA en trait plein, estimation par l'ETF BNO en orange), bougies quotidiennes de la paire
  n° 1 avec zones et lignes du V8.2, écart de taux en dessous ; micro-graphiques SVG pour les marchés et les paires.
- Captures : `node outils/captures.mjs "http://localhost:4173/" captures/<lot> synthese`, comparées à `reference/v9/`.

### V9, livraison 2

- Section 1 : jauge de la Fed alimentée par une probabilité citée dans une actualité (citation et lien au survol, repère
  d'une semaine plus tôt), bloc « À la une » (5 à 8 titres d'origine, classés par thème en Python, source et heure).
- Section 3 : discours avec le statut FOMC 2026 (votants en gras, table sourcée `core/fomc_2026.py`).
- Section 4 : cartes enrichies du communiqué officiel (vote, minorité citée, projection citée, vocabulaire comparé au
  communiqué précédent, lien) ; une banque refusée (403) affiche « n/d » avec la raison, jamais de contournement.
- Section 6 : ETF EWJ, EWT, FXI ; titres « Actions, IA et Asie ».
- Archives : chaque Synthèse publiée dans `data/synthese/AAAA-MM-JJ.json`, lisible à `#archives/synthese=AAAA-MM-JJ`.
- Fiche devise : sur téléphone, une ligne d'indicateur = un bloc (nom, puis valeur, prévision, précédent, date ; cellules
  vides masquées) ; codes du modèle traduits ; décimales françaises fixes.
