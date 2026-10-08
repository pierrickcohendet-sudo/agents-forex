# Tableau macro — définitions des indicateurs non standards

Le Tableau macro affiche, pour chaque devise, la valeur publiée la plus récente. Quand un pays ne publie pas
l'indicateur de référence, l'équivalent local est étiqueté `[…]` : ne jamais le comparer tel quel à un autre pays.

- **JPY — CPI annuel** = « National Core CPI » (Bureau des statistiques) : hors **alimentation fraîche** seulement
  (énergie incluse), publié vers le 3e vendredi du mois suivant. **JPY — CPI core** = « BoJ Core CPI » : hors
  **alimentation, énergie et facteurs institutionnels** (mesure sous-jacente de la BoJ, plus proche du « core » US/UE),
  publié vers le dernier vendredi du mois. Le « Tokyo Core CPI » (avance de ~1 mois, Tokyo seul) n'est pas affiché.
- **CHF, CAD — CPI** : publiés en variation **mensuelle** (m/m) ; **CAD — core** = CPI **médian** annuel (mesure préférée
  de la BoC). **AUD — core** = moyenne tronquée m/m ; **AUD — ventes au détail** = indicateur de dépenses des ménages
  (l'ABS a remplacé la série « Retail Sales »). **NZD** : CPI, chômage, emploi, ventes au détail sont **trimestriels** (t/t).
- **GBP — emploi** = variation du nombre de demandeurs d'emploi (claimant count) ; **CAD — PMI services** = Ivey PMI (mixte).
- **CNY — PMI** = officiel NBS (manufacturier et non manufacturier), pas le privé RatingDog (ex-Caixin).
- **CHF — balance commerciale** : équivalent OCDE (exports − imports, en USD, ~3 mois de retard) via FRED.
- **Surprise** = réel − consensus ForexFactory, normalisée par un écart habituel configuré ; chômage inversé dans
  l'indice de surprise 30 j. **« proj. BC »** = projection officielle de banque centrale (Fed SEP), jamais un consensus.
