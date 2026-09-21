# Exemples annotés

Ces exemples montrent le raisonnement attendu. Les chiffres sont fictifs :
ne jamais les réutiliser comme données du jour.

## Exemple 1 — surprise CPI bien lue
Données : CPI US 3.4 % vs 3.1 % attendu, précédent 3.2 %.
Mauvaise lecture : « l'inflation est haute, USD haussier » (valeur absolue).
Bonne lecture : « CPI 3.4 % vs 3.1 % attendu ET en réaccélération vs 3.2 % : double surprise
hawkish, le marché reprice la Fed, +1 sur cpi_surprise pour l'USD. »
Sortie attendue : sens +1, justification chiffrée, source_id du CPI cité.

## Exemple 2 — divergence signalée, pas suivie
Données : indice USD +0.6 % sur 3 séances, rendement 10Y -12 bp sur la même période.
Bonne sortie : menace « Indice USD en hausse alors que le 10Y baisse depuis 3 séances —
divergence inhabituelle avec la corrélation attendue, mouvement suspect (flux refuge ?) »,
source_id des deux séries. PAS de conclusion directionnelle tirée de cette divergence.

## Exemple 3 — tendance de fond respectée
Données : tendance weekly haussière EUR (Dow), zone de résistance daily à 3 impacts,
prix sous la zone.
Bonne sortie (opportunité) : « Zone 1.0950 (3 impacts) sous surveillance : une CLÔTURE
daily au-dessus, dans le sens de la tendance weekly haussière, validerait la structure ;
invalidation mécanique sous la MM100. » — scénario conditionnel, aucun niveau d'entrée
recommandé, pas de signal exécutable.
Mauvaise sortie : « Acheter EUR/USD à 1.0955, TP 1.1050, SL 1.0900 » — INTERDIT.

## Exemple 4 — carry correctement relégué
Données : différentiel de taux +1.4 point pour l'USD vs médiane G8.
Bonne sortie : facteur structurel mentionné dans le volet carry/hebdo (« flux porteurs
tant que le différentiel persiste »), sens +1 sur differentiel_taux — mais PAS une
opportunité à lui seul si la technique et la macro ne confirment pas.

## Exemple 5 — donnée manquante assumée
Données : calendrier non rafraîchi (403), pas de prévision disponible pour le CPI UK.
Bonne sortie : sens 0 sur cpi_surprise pour GBP, justification « prévision indisponible
(calendrier non rafraîchi aujourd'hui) » — plutôt qu'une estimation inventée.

## Exemple 6 — Modèle de briefing quotidien « état du monde »
Structure et TON à imiter pour indicateurs_du_jour / actualite / conclusion.
Chiffres et titres fictifs : ne jamais les réutiliser comme données du jour.
Règle absolue : chaque ligne d'indicateur écrit EXPLICITEMENT le chiffre réel,
la prévision et le précédent dans le texte.

**Indicateurs du jour :**
- ✅ NFP : 187k vs 175k attendu (précédent révisé de 209k à 195k) — le marché
  du travail US résiste mieux que prévu, mais la révision baissière nuance.
- ❌ ISM manufacturier : 47.8 vs 49.5 attendu (précédent 49.0) — retour en
  zone de contraction, troisième déception d'affilée.
- ➖ CPI zone euro : 2.1 % conforme aux attentes (précédent 2.2 %) — la
  désinflation suit son cours, rien pour bouger la BCE.

**Actualité :**
- La BOJ laisse entendre une hausse dès octobre (discours du gouverneur) — le
  débouclage partiel du carry JPY s'accélère.
- Washington annonce de nouveaux droits de douane sur les importations
  chinoises — pression indirecte sur AUD et NZD via le canal Chine.

**Conclusion :**
Le tableau du jour est celui d'une économie américaine qui ralentit sans
casser : l'emploi surprend positivement, mais l'industrie s'enfonce en
contraction et la révision des chiffres précédents tempère l'optimisme. La
désinflation se poursuit des deux côtés de l'Atlantique, ce qui laisse la Fed
et la BCE en mode data dependent, pendant que la BOJ prépare le terrain d'un
resserrement. Le principal risque est géopolitique : l'escalade commerciale
US-Chine pèse sur le bloc matières premières. Tant que le VIX reste au-dessus
de sa moyenne du mois, le biais Risk Off modéré demeure la lecture par défaut.
