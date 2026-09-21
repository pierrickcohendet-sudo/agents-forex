# Indicateurs fondamentaux

## Lecture event-driven — règle n°1
Une donnée macro (CPI, PIB, PMI...) se lit TOUJOURS par rapport à ce que le marché attendait,
jamais en valeur absolue. Comparer au chiffre PRÉVU et au chiffre PRÉCÉDENT pour juger la
trajectoire (pas seulement le niveau).

## Yield curve US (spread 10Y-2Y)
- Pentification positive = croissance/inflation attendues.
- Bear steepening (spread ↑ tiré par le 10Y) = inflation/croissance anticipées.
- Courbe inversée (10Y < 2Y) = signal avancé de risque de récession.
- Bull steepening (spread ↑ par baisse du 2Y) = marché anticipant un assouplissement monétaire.

## Différentiels de taux bilatéraux
- Comparer US 2Y/10Y vs Allemagne / Japon / UK / Canada / Australie.
- Un spread US qui se creuse favorise généralement l'USD contre la devise en question.

## Grille de lecture combinée
- 2Y ↑ + DXY ↑ = USD favorable.
- 10Y ↑ + actions ↓ = hausse de taux jugée problématique par le marché.
- VIX ↑ + DXY ↑ + JPY ↑ = Risk Off marqué.
- VIX ↓ + actions ↑ + DXY ↓ = Risk On.

## Pétrole (Brent / WTI)
- Distinguer hausse par demande forte (positif, cyclique) vs hausse par choc d'offre
  géopolitique (négatif). NE JAMAIS conclure automatiquement sans croiser avec le contexte
  géopolitique du jour (news).
- Très corrélé au CAD (devise exportatrice de pétrole) et à l'inflation globale.
- Données de graphique : WTI et Brent via FRED (DCOILWTICO / DCOILBRENTEU), pas Twelve
  Data — les commodités y sont réservées aux plans payants sur ce projet (vérifié). Le
  rendu QuickChart reste le même mécanisme que les autres graphiques du pipeline.

## VIX — baromètre Risk On/Off n°1
VIX ↑ → AUD ↓, NZD ↓, CAD ↓ (nuancé par le pétrole), CHF ↑, DXY ↑,
USD/JPY ↓, EUR/JPY ↓, GBP/JPY ↓, AUD/JPY ↓.

## DXY — baromètre Risk On/Off n°2
À utiliser en CONFLUENCE avec le VIX, jamais seul. Dans ce pipeline, le DXY est approché
par un indice USD synthétique calculé localement (force moyenne de l'USD contre les 8 autres,
Twelve Data). Le graphique DXY affiché pour chaque devise réutilise cette même série (aucune
double collecte) ; sur la carte USD, le graphique de prix sert directement de référence DXY.

## Corrélations et divergences
Croiser tout mouvement de devise avec les corrélations attendues (ex. DXY vs rendements
obligataires US). Une divergence inhabituelle se SIGNALE comme suspecte (menace), elle ne se
suit pas aveuglément.

## Carry trade — signal SECONDAIRE
- Comparer les taux directeurs des 8 devises entre elles.
- Une position dans le sens du différentiel (devise à taux haut contre taux bas) génère un
  swap positif si tenue plusieurs jours : facteur STRUCTUREL de flux à signaler dans les
  rapports hebdo/mensuels — JAMAIS une raison d'entrée isolée, jamais un déclencheur seul.

## Lecture du sens des indicateurs fondamentaux (pour detail_score)
- `taux_directeur` : +1 si taux nettement au-dessus de la médiane G8 avec banque centrale non
  dovish ; -1 si nettement en dessous ; 0 sinon.
- `cpi_surprise` / `pmi_surprise` : +1 si surprise dans le sens qui soutient la devise
  (ex. CPI au-dessus des attentes → banque centrale plus hawkish) ; -1 à l'inverse ;
  0 si pas de publication ou surprise négligeable.
- `yield_curve` : sens selon l'effet du régime actuel SUR la devise analysée (ex. bear
  steepening US = +1 USD, souvent -1 JPY).
- `vix` / `dxy` : sens selon la sensibilité Risk On/Off de la devise (grilles ci-dessus).
- `differentiel_taux` : +1 si le carry attire structurellement des flux VERS la devise ;
  -1 s'il en éloigne ; 0 si différentiel proche de zéro.
