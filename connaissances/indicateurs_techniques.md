# Indicateurs techniques

## Filtre de tendance multi-temporalité (théorie de Dow)
- La tendance de fond se détermine sur une unité de temps HAUTE (weekly, à défaut daily) :
  hauts et bas successivement plus hauts = tendance haussière ; successivement plus bas = baissière.
- Ne signaler des opportunités techniques QUE dans le sens de cette tendance de fond.
- Repérer une zone de consolidation : support/résistance avec au moins 2-3 impacts.
- Un signal ne compte qu'à la CLÔTURE d'une bougie qui casse la zone — jamais en anticipation.
- Le stop loss se place de façon mécanique (ex. sous une moyenne mobile 100), jamais au jugé.
- Le take profit suit un ratio risque/récompense PROPRE À CHAQUE ACTIF (champ
  `ratio_rr_configure` dans les données techniques) — jamais un chiffre unique arbitraire.
- Rappel absolu : décrire le scénario (zone, condition de cassure, invalidation), ne JAMAIS
  formuler un signal d'achat/vente exécutable ni un niveau d'entrée recommandé.

## RSI
- Surachat > 70, survente < 30.
- Le niveau 50 est la ligne pivot du momentum : au-dessus = haussier, en dessous = baissier.
- Tracer aussi une trendline sur le RSI lui-même : sa cassure AVANT celle du prix est un
  signal précoce, à signaler comme tel.
- Confluence forte : prix au-dessus de la moyenne mobile 200 ET RSI qui repasse au-dessus de 50.

## Trendline
- Minimum 3 points de contact pour la valider.
- En tendance haussière elle sert de support ; en tendance baissière, de résistance.
- Plus la pente est verticale, moins la trendline est fiable.

## Lecture du sens des indicateurs techniques (pour detail_score)
- `rsi` : +1 si momentum haussier confirmé (RSI > 50, idéalement en confluence avec prix >
  MM200) ; -1 si momentum baissier ; 0 en zone ambiguë ou surachat/survente extrême non confirmé.
- `trendline` : +1 si structure validée (≥ 3 contacts) soutient la devise ; -1 si structure
  validée pèse contre ; 0 si aucune structure valide dans les données.
