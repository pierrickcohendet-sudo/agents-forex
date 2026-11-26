"""Noms affichés des 8 moteurs du marché (lot V10, A) : définis UNE fois ici, réutilisés partout (Python, modèle, site).

Le mot « engrenage » et la numérotation ne restent que dans l'onglet « 8 engrenages ». Ailleurs : « 4 moteurs sur 8
favorisent l'AUD : banques centrales et taux, chiffres économiques… », avec l'explication courte à la première mention.
Filet de sécurité : `nettoyer_publication()` remplace, dans les JSON publiés (hors fichiers de l'onglet dédié), toute
occurrence restante et renvoie le décompte pour le récapitulatif du run.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# n -> (nom affiché, explication courte). Explications 7 et 8 ajustées au contenu réel des dossiers (dossier 7 : tendance,
# RSI, moyennes mobiles, volatilité, COT ; dossier 8 « Offre et demande » : balances commerciales, stocks et production de
# pétrole EIA).
MOTEURS = {
    1: ("Thème dominant", "le grand récit du marché du moment (inflation, croissance, risque)"),
    2: ("Banques centrales et taux", "décisions, ton et anticipations de taux directeurs"),
    3: ("Chiffres économiques", "publications au-dessus ou en dessous du consensus"),
    4: ("Budgets et dette publique", "déficits, émissions de dette, risque souverain"),
    5: ("Liens entre marchés", "taux longs, actions, matières premières, volatilité"),
    6: ("Géopolitique", "conflits, sanctions, élections, chocs d'offre"),
    7: ("Prix et positionnement", "tendance des prix, positions des spéculateurs (COT)"),
    8: ("Commerce et flux", "balances commerciales, offre et demande de pétrole"),
}
# Lot V12 : la question à laquelle répond chaque moteur, et son canal de transmission général vers les devises.
QUESTIONS = {
    1: "Quel récit domine le marché, et les autres moteurs vont-ils dans son sens ?",
    2: "Qui monte ou baisse ses taux, et comment évolue l'écart de rendement entre pays ?",
    3: "Les chiffres publiés surprennent-ils au-dessus ou en dessous des attentes ?",
    4: "Les déficits et la dette publique inquiètent-ils les investisseurs ?",
    5: "Que disent les taux longs, les actions, l'or, le pétrole et la volatilité ?",
    6: "Quels conflits, sanctions ou élections peuvent provoquer un choc ?",
    7: "Où en sont la tendance des prix et les positions des spéculateurs ?",
    8: "Que disent le commerce extérieur et le marché du pétrole ?",
}
CANAUX = {
    1: "Le régime de risque déplace les capitaux : vers USD, JPY et CHF quand le marché a peur, vers AUD, NZD et CAD quand il a confiance.",
    2: "Un écart de taux qui s'élargit attire les capitaux de portage vers la devise la mieux rémunérée ; une banque centrale plus restrictive que prévu soutient sa devise.",
    3: "Une surprise change ce que le marché attend de la banque centrale, donc l'écart de taux et la devise.",
    4: "Un dérapage budgétaire fait monter la prime de risque du pays et peut faire fuir les investisseurs étrangers.",
    5: "Les mouvements des actions, des taux longs et des matières premières se transmettent aux devises qui y sont exposées.",
    6: "Un choc crée des flux de refuge et renchérit l'énergie des pays importateurs.",
    7: "Une tendance installée attire les suiveurs ; des positions extrêmes rendent la devise vulnérable à un débouclage brutal.",
    8: "Le pétrole et la balance commerciale changent la demande de devise des exportateurs et des importateurs.",
}
# Canal adapté à la devise (sinon le canal général du moteur)
CANAUX_DEVISE = {
    "JPY": {2: "Portage : quand l'écart de taux avec le Japon s'élargit, emprunter en yen pour placer ailleurs rapporte davantage, ce qui pèse sur le yen ; le ministère des Finances peut intervenir si la baisse devient brutale.",
            1: "Refuge : le yen est racheté quand le marché a peur (débouclage du portage).",
            5: "Le yen suit la volatilité des actions : une hausse du VIX déclenche des rachats de yen."},
    "CHF": {1: "Refuge : le franc est recherché quand le marché a peur ; la BNS peut intervenir pour freiner sa hausse.",
            6: "Refuge : un conflit attire les capitaux vers le franc."},
    "CAD": {8: "Pétrole : le Canada exporte du brut, un baril plus cher soutient le dollar canadien ; la balance commerciale suit.",
            5: "Pétrole et actions américaines : le CAD suit le Brent et l'appétit pour le risque."},
    "AUD": {5: "Matières premières et Chine : l'AUD suit les métaux, les actions et la croissance chinoise.",
            1: "Devise de risque : l'AUD baisse quand le marché a peur."},
    "NZD": {1: "Devise de risque : le NZD baisse quand le marché a peur.", 8: "Exportations agricoles : la balance commerciale pèse sur le NZD."},
    "NOK": {8: "Pétrole."},
    "USD": {1: "Monnaie de réserve : la demande de dollars monte avec le stress (financements, couvertures).",
            2: "Écart de taux : des taux américains plus hauts que ceux des autres attirent les capitaux vers le dollar.",
            4: "Prime de terme : un dérapage budgétaire américain peut faire monter les taux longs sans soutenir le dollar."},
    "EUR": {8: "Facture énergétique : la zone euro importe son énergie, un pétrole cher pèse sur sa balance et sur l'euro.",
            4: "Écarts de dette entre pays (Italie − Allemagne) : une tension souveraine pèse sur l'euro."},
    "GBP": {4: "Crédibilité budgétaire : un dérapage fait monter les gilts et peut faire baisser la livre (2022).",
            3: "La livre réagit fortement aux surprises d'inflation et d'emploi, qui déplacent les anticipations de la BoE."},
    "CNY": {2: "Change piloté : la PBoC oriente le yuan par le fixing quotidien ; les écarts de taux jouent moins qu'ailleurs.",
            8: "Excédent commercial : les exportations chinoises soutiennent la demande de yuan, les droits de douane la réduisent."},
}


# Lot V13 : « Comprendre ce moteur », texte PERMANENT écrit à la main (jamais généré), relu une fois par trimestre.
# importance pour le change (1 à 5 étoiles), pourquoi il compte, indicateurs principaux, chaîne de transmission (étapes ->
# devise), 3 confluences avec les marchés (signal, sens ▲ ▼ ou !, effet), piège à éviter.
# Lot V15 : textes permanents « Comprendre ce moteur » réécrits par l'utilisateur (6 rubriques).
COMPRENDRE = {
    1: {"importance": 5,
        "une_phrase": "L'humeur générale du marché. Est-ce qu'on a peur, ou est-ce qu'on a envie de prendre des risques ?",
        "comment": "Comme dans une salle de classe avant un contrôle, l'ambiance compte autant que les cours. Quand les investisseurs ont "
                   "peur (une crise, une guerre, une chute de la Bourse), ils vendent ce qui est risqué et achètent ce qui est sûr. Quand ils "
                   "sont confiants, ils font l'inverse. Le thème dominant résume cette humeur et dit quelles devises en profitent. Quand il "
                   "est net, il écrase les autres moteurs : une bonne statistique australienne ne sauve pas l'AUD un jour de panique.",
        "regarde": ["le VIX, l'« indice de la peur » : sous 15 c'est le calme, au-dessus de 25 c'est la tension, au-dessus de 35 c'est la panique",
                    "la Bourse américaine (S&P 500) : si elle monte, on prend du risque",
                    "l'or : on l'achète quand on a peur",
                    "le nombre de moteurs qui vont dans le même sens : à 3 ou plus, l'humeur est installée"],
        "exemple": "Le 20/11/2026, le VIX est monté à 35,89 et le S&P 500 a perdu plus de 3 % en une séance. Le dollar, le yen et le franc "
                   "suisse ont été recherchés ; les dollars australien et néo-zélandais ont été vendus.",
        "effets": "Quand la peur domine, le dollar américain, le yen et le franc suisse montent, car ce sont les « valeurs refuges ». Quand la "
                  "confiance domine, ce sont les devises des pays qui vivent des matières premières et du commerce mondial qui montent : "
                  "dollars australien, néo-zélandais et canadien.",
        "piege": "L'humeur peut changer en une journée. Un thème dit « où souffle le vent aujourd'hui », pas « où il soufflera dans un mois »."},
    2: {"importance": 5,
        "une_phrase": "L'argent va là où il est le mieux rémunéré ; les banques centrales fixent cette rémunération.",
        "comment": "Chaque pays a une banque centrale (la Fed aux États-Unis, la BCE en zone euro…) qui fixe un taux directeur, le prix de "
                   "l'argent dans le pays. Si les États-Unis rémunèrent l'argent à 4 % et le Japon à 1 %, les investisseurs ont intérêt à "
                   "placer en dollars plutôt qu'en yens : ils achètent des dollars, qui montent. Mais le marché vit dans le futur : ce qui "
                   "compte, c'est ce que la banque centrale va faire. C'est pourquoi on regarde surtout le taux à 2 ans, qui résume ce que le "
                   "marché attend pour les deux prochaines années.",
        "regarde": ["les taux directeurs et les dates des réunions",
                    "le rendement à 2 ans de chaque pays",
                    "l'écart de rendement à 2 ans entre deux pays (pour une paire comme USD/JPY, c'est le chiffre clé)",
                    "le taux réel (taux directeur moins inflation), qui dit si la politique freine vraiment l'économie",
                    "les discours des banquiers centraux"],
        "exemple": "Entre le 13/11 et le 20/11/2026, le rendement à 2 ans américain est passé de 4,88 % à 4,63 %. Le marché a revu à la "
                   "baisse ses attentes de hausse de taux de la Fed.",
        "effets": "Une banque centrale plus sévère que prévu (des taux plus hauts, ou un discours plus dur) fait monter sa devise. Une "
                  "banque centrale plus douce que prévu la fait baisser.",
        "piege": "Une hausse de taux déjà attendue ne fait pas monter la devise, car elle est « dans les prix ». Exemple : la hausse de la "
                 "banque centrale australienne du 03/11/2026 n'a pas soutenu l'AUD. Ce qui fait bouger, c'est la surprise."},
    3: {"importance": 4,
        "une_phrase": "Les statistiques (inflation, emploi, croissance) qui disent si l'économie va mieux ou moins bien que prévu.",
        "comment": "Chaque statistique a une prévision, ce que les économistes attendaient. Le marché ne réagit pas au chiffre lui-même, mais "
                   "à l'écart entre le chiffre et la prévision. Une inflation plus forte que prévu, c'est une banque centrale qui risque de "
                   "monter ses taux, donc une devise qui monte. Un emploi plus faible que prévu, c'est l'inverse.",
        "regarde": ["l'inflation (IPC, et le PCE aux États-Unis, la mesure préférée de la Fed)",
                    "l'emploi (créations d'emplois, chômage, salaires)",
                    "la croissance (PIB)",
                    "les enquêtes auprès des entreprises (PMI : au-dessus de 50, l'activité progresse ; en dessous, elle recule)",
                    "l'indice de surprise du site, qui additionne les bonnes et mauvaises surprises de chaque devise sur 30 jours"],
        "exemple": "Le 19/11/2026, l'emploi australien a reculé de 43 500 postes alors qu'on attendait 25 500 créations. L'AUD a perdu un "
                   "argument : la banque centrale australienne aura plus de mal à monter ses taux.",
        "effets": "Une série de bonnes surprises soutient la devise pendant des semaines ; une série de déceptions l'affaiblit.",
        "piege": "Regarder aussi la révision du mois précédent. Un bon chiffre accompagné d'une forte révision à la baisse du mois d'avant "
                 "n'est pas une si bonne nouvelle."},
    4: {"importance": 3,
        "une_phrase": "La santé des finances de l'État, qui joue lentement mais peut tout faire basculer.",
        "comment": "Un État qui dépense plus qu'il ne gagne emprunte. Tant que les prêteurs ont confiance, tout va bien. S'ils commencent à "
                   "douter, ils demandent un taux plus élevé pour prêter : les taux longs (10 ans) montent. Normalement, des taux plus hauts "
                   "attirent les capitaux et font monter la devise. Mais quand ils montent parce qu'on a peur pour les finances du pays, les "
                   "investisseurs fuient, et la devise baisse en même temps que les taux montent. C'est le signal d'alarme.",
        "regarde": ["le déficit et la dette (en % du PIB)",
                    "les adjudications, c'est-à-dire les ventes de dette de l'État : les prêteurs se bousculent-ils ?",
                    "le rendement à 10 ans",
                    "la « prime de terme », le supplément exigé pour prêter longtemps",
                    "l'écart Italie − Allemagne pour la zone euro"],
        "exemple": "En septembre 2022, le Royaume-Uni a annoncé des baisses d'impôts non financées. Les taux britanniques ont bondi et la "
                   "livre a touché son plus bas historique face au dollar.",
        "effets": "Des taux longs qui montent avec une devise qui baisse signalent une crise de confiance. C'est mauvais pour la devise tant "
                  "que le gouvernement n'a pas rassuré.",
        "piege": "Les chiffres de dette arrivent avec des mois de retard. En temps réel, ce sont les taux à 10 ans et les adjudications qui "
                 "donnent l'alerte."},
    5: {"importance": 4,
        "une_phrase": "Les devises sont reliées aux actions, au pétrole, à l'or et aux taux, et elles suivent souvent leurs mouvements.",
        "comment": "Certaines devises ont des « cousins » sur d'autres marchés. Le dollar canadien suit souvent le pétrole, parce que le "
                   "Canada en exporte beaucoup. Le dollar australien suit souvent la Bourse et les matières premières. Le yen monte souvent "
                   "quand la peur monte. Ce moteur repère quels liens sont actifs en ce moment, et avec quelle force.",
        "regarde": ["le VIX et la Bourse américaine",
                    "le rendement à 10 ans américain",
                    "l'or",
                    "le pétrole (Brent et WTI)",
                    "les corrélations sur 60 séances, c'est-à-dire à quel point deux marchés ont bougé ensemble ces trois derniers mois"],
        "exemple": "En novembre 2026, le Brent a baissé quatre semaines de suite. Le dollar canadien en a souffert, tandis que le Japon et "
                   "la zone euro, qui importent leur énergie, en ont profité.",
        "effets": ["pétrole en hausse : CAD soutenu, JPY et EUR pénalisés",
                   "Bourse en baisse : AUD et NZD vendus",
                   "peur en hausse : JPY et CHF recherchés"],
        "piege": "Un lien peut se casser du jour au lendemain. Toujours vérifier qu'il est encore actif avant de s'en servir."},
    6: {"importance": 3,
        "une_phrase": "Guerres, sanctions, élections et tensions entre pays, qui créent des peurs soudaines.",
        "comment": "Un événement géopolitique agit par deux canaux. Le premier est la peur : les investisseurs se réfugient dans le dollar, "
                   "le franc suisse, le yen et l'or. Le second est l'énergie : une tension au Moyen-Orient fait monter le pétrole, ce qui "
                   "aide les pays exportateurs (Canada, Norvège) et pénalise les importateurs (Japon, zone euro).",
        "regarde": ["les titres du jour classés par type (énergie, sanctions, commerce, élections)",
                    "la réaction du pétrole, de l'or, du franc suisse et de USD/JPY",
                    "le VIX"],
        "exemple": "Quand une menace pèse sur le détroit d'Ormuz, par où passe une grande partie du pétrole mondial, le Brent monte en "
                   "quelques heures, le CAD se renforce et le yen recule.",
        "effets": "À court terme, la peur profite au dollar et au franc suisse. Si le pétrole s'en mêle, le CAD monte et l'EUR et le JPY "
                  "baissent.",
        "piege": "Le marché s'habitue vite. Le premier choc est souvent exagéré, et il s'efface si l'approvisionnement n'est pas vraiment "
                 "touché."},
    7: {"importance": 3,
        "une_phrase": "Ce que le marché a déjà fait, et qui est déjà « à fond » dans un sens.",
        "comment": "Imagine une salle de concert : si tout le monde s'est déjà rué vers la même sortie, il n'y a plus personne pour pousser, "
                   "et au moindre bruit inattendu, la foule repart dans l'autre sens. C'est pareil sur les devises. Quand presque tous les "
                   "spéculateurs ont parié sur la hausse d'une devise, il reste peu d'acheteurs. Une mauvaise surprise suffit alors à "
                   "déclencher des ventes en cascade.",
        "regarde": ["la tendance (le prix est-il au-dessus de sa moyenne des 200 derniers jours ?)",
                    "le RSI, qui dit si la hausse ou la baisse a été trop rapide (au-dessus de 70 : surachat ; sous 30 : survente)",
                    "la volatilité, c'est-à-dire l'ampleur des mouvements récents",
                    "le rapport COT, publié chaque vendredi aux États-Unis, qui montre les paris des spéculateurs"],
        "exemple": "À l'été 2024, les spéculateurs avaient massivement parié contre le yen. Quand la Banque du Japon a monté ses taux fin "
                   "juillet, ils ont dû racheter des yens en urgence, et USD/JPY est passé d'environ 162 début juillet à environ 142 début "
                   "août.",
        "effets": "Une devise très achetée devient fragile ; une devise très vendue peut rebondir fort au moindre bon chiffre.",
        "piege": "Un excès peut durer longtemps. C'est un facteur de fragilité, pas un signal de retournement à lui seul."},
    8: {"importance": 2,
        "une_phrase": "Les échanges de marchandises et l'énergie, qui créent une demande de fond pour certaines devises.",
        "comment": "Quand le Canada vend du pétrole, ses clients doivent acheter des dollars canadiens pour le payer. Plus le pétrole est "
                   "cher, plus cette demande est forte. Pareil pour l'Australie avec le minerai de fer. À l'inverse, le Japon et la zone "
                   "euro achètent leur énergie à l'étranger : un pétrole cher les appauvrit. Les droits de douane et les accords commerciaux "
                   "modifient aussi ces flux.",
        "regarde": ["le prix du pétrole (Brent pour le monde, WTI pour les États-Unis)",
                    "les stocks de pétrole américains (chaque mercredi)",
                    "les balances commerciales (exportations moins importations)",
                    "les annonces de droits de douane"],
        "exemple": "Des stocks de pétrole américains plus bas que d'habitude soutiennent le prix du baril, donc le dollar canadien.",
        "effets": "Un pétrole cher soutient le CAD et pèse sur le JPY et l'EUR. Les nouveaux droits de douane pèsent sur les devises des "
                  "pays visés.",
        "piege": "Si le pétrole baisse parce que l'économie mondiale ralentit, toutes les devises liées à la croissance souffrent, pas "
                 "seulement le CAD."},
}

# « Ce que c'est » sous chaque indicateur (lot V15) : une phrase simple, sans jargon ni « percentile ». Rédigées une fois
# (Claude, relues) puis figées ici ; le premier motif qui correspond au libellé de la tuile l'emporte.
DEFINITIONS = [
    (r"^Score ", "Une note de 0 à 100 que le site calcule chaque jour à partir des 8 moteurs : au-dessus de 60, la devise est recherchée ; sous 40, elle est délaissée."),
    (r"^Écart meilleur", "La distance entre la devise la plus forte et la plus faible du jour : plus elle est grande, plus le marché fait des choix tranchés."),
    (r"[Mm]oteurs alignés", "Le nombre de moteurs qui poussent dans le même sens que l'humeur du marché : à partir de 3, cette humeur est bien installée."),
    (r"Surprise globale", "La moyenne des bonnes et mauvaises surprises économiques des 9 devises : sous 0, le monde publie des chiffres plus faibles que prévu."),
    (r"Régime actuel", "Depuis combien de temps le marché est dans la même humeur (peur ou confiance) : plus ça dure, plus les positions s'y sont adaptées."),
    (r"^VIX", "L'« indice de la peur » de la Bourse américaine : sous 15, c'est le calme ; au-dessus de 25, la tension ; au-dessus de 35, la panique."),
    (r"Taux effectif Fed", "Le taux auquel les banques américaines se prêtent de l'argent pour une nuit : c'est le vrai prix de l'argent en dollars, piloté par la Fed."),
    (r"Rendement 2 ans US", "Le taux auquel l'État américain emprunte sur 2 ans : il résume ce que le marché attend de la Fed, c'est le meilleur thermomètre du dollar."),
    (r"2 ans US − taux effectif", "Si le taux à 2 ans est au-dessus du taux de la Fed, le marché attend des hausses de taux ; en dessous, il attend des baisses."),
    (r"Taux réel", "Le taux directeur moins l'inflation : s'il dépasse 1 %, la banque centrale freine vraiment l'économie."),
    (r"Courbe 2-10", "L'écart entre le taux à 10 ans et le taux à 2 ans : quand il est négatif, le marché craint un ralentissement de l'économie."),
    (r"BCE", "Le taux que la BCE verse aux banques sur leurs dépôts : c'est lui qui guide l'euro."),
    (r"2 ans allemand", "Le taux auquel l'Allemagne emprunte sur 2 ans : il dit ce que le marché attend de la BCE ; son écart avec le taux américain guide EUR/USD."),
    (r"BoE", "Le taux directeur de la Banque d'Angleterre, qui guide la livre."),
    (r"BoJ", "Le taux de l'argent au jour le jour au Japon : très bas, il pousse les investisseurs à emprunter en yens pour placer ailleurs."),
    (r"2 ans japonais", "Le taux auquel le Japon emprunte sur 2 ans : quand il monte, l'écart avec les États-Unis se réduit et le yen est soutenu."),
    (r"RBA", "Le taux directeur de la banque centrale australienne, qui guide le dollar australien."),
    (r"^Surprise [A-Z]{3}", "La somme, sur 30 jours, des écarts entre les chiffres publiés et les prévisions : au-dessus de 0, l'économie surprend en bien, ce qui soutient la devise."),
    (r"Inflation core US", "L'inflation américaine sans l'énergie ni l'alimentation, qui varient beaucoup : c'est elle que la Fed surveille pour décider de ses taux."),
    (r"^Chômage", "La part des actifs sans emploi : quand elle monte, la banque centrale devient plus prudente et baisse plus volontiers ses taux."),
    (r"au-dessus du consensus", "La part des chiffres publiés meilleurs que prévu sur 30 jours, toutes devises confondues."),
    (r"Dette fédérale", "La dette de l'État américain rapportée à sa richesse annuelle : plus elle est lourde, plus une hausse des taux coûte cher."),
    (r"Solde fédéral", "Le déficit de l'État américain sur un an : il faut le financer en empruntant davantage."),
    (r"Prime de terme", "Le supplément que les prêteurs exigent pour prêter 10 ans d'un coup : il monte quand ils doutent des finances de l'État."),
    (r"^10 ans", "Le taux auquel l'État emprunte sur 10 ans : il mêle les attentes de croissance, d'inflation et la confiance dans les finances publiques."),
    (r"Italie − Allemagne", "L'écart de taux à 10 ans entre l'Italie et l'Allemagne : quand il s'élargit, les investisseurs doutent de l'Italie, et l'euro peut en souffrir."),
    (r"Indice dollar large", "La valeur du dollar face à un large panier de devises, calculée par la Fed : elle montre la tendance de fond du dollar."),
    (r"S&P 500", "Le grand indice de la Bourse américaine : quand il baisse, les devises liées à la croissance (AUD, NZD, CAD) souffrent."),
    (r"Rendement 10 ans US", "Le taux auquel l'État américain emprunte sur 10 ans, la référence mondiale : quand il monte, il attire les capitaux vers le dollar."),
    (r"or \(proxy\)|Indice or", "Un indice qui suit le prix de l'or : on achète de l'or quand on a peur ou qu'on craint l'inflation."),
    (r"Brent − WTI", "L'écart de prix entre le pétrole mondial (Brent) et le pétrole américain (WTI) : il grandit quand l'offre se tend hors des États-Unis."),
    (r"Brent", "Le prix du pétrole de référence dans le monde : quand il monte, le dollar canadien est soutenu, le yen et l'euro souffrent."),
    (r"WTI", "Le prix du pétrole américain : il pèse sur les revenus du Canada, grand exportateur de pétrole vers les États-Unis."),
    (r"Corrélation AUD", "À quel point le dollar australien et la Bourse ont bougé ensemble sur 3 mois : si c'est le cas, l'AUD suit l'humeur du marché."),
    (r"Corrélation JPY", "À quel point le yen et l'indice de la peur ont bougé ensemble sur 3 mois : si c'est le cas, le yen joue son rôle de refuge."),
    (r"^Titres", "Le nombre de titres de presse du jour qui parlent de ce type de risque (énergie, sanctions, conflits…)."),
    (r"^Réaction", "Le mouvement de ce marché lors de la dernière séance : il dit si l'actualité fait vraiment réagir les prix."),
    (r"RSI", "Un indicateur de vitesse du prix sur 14 séances : au-dessus de 70, la hausse a été trop rapide ; sous 30, la baisse."),
    (r"MM200", "L'écart entre le prix et sa moyenne des 200 dernières séances : au-dessus, la tendance de fond monte ; en dessous, elle baisse."),
    (r"volatilité réalisée", "L'ampleur des mouvements des 20 dernières séances : quand elle est très basse, un réveil brutal arrive souvent."),
    (r"surachat|survente", "Le nombre de devises qui ont bougé trop vite dans un sens : beaucoup d'excès annoncent souvent des retours en arrière."),
    (r"^COT", "Les paris des spéculateurs sur les marchés à terme américains, publiés chaque vendredi : quand ils sont tous du même côté, la devise devient fragile."),
    (r"Stocks de brut US|Stocks : écart", "Le pétrole stocké aux États-Unis, publié chaque mercredi : des stocks plus bas que d'habitude soutiennent le prix du baril."),
    (r"Production de brut", "La quantité de pétrole produite aux États-Unis : une production record limite la hausse des prix."),
    (r"Balance commerciale", "Les exportations moins les importations : un pays qui vend plus qu'il n'achète crée une demande pour sa devise."),
]

# Glossaire de l'onglet (lot V15) : mots soulignés en pointillé dans les textes, bulle au survol ou au toucher
GLOSSAIRE = {
    "VIX": "L'« indice de la peur » : il mesure les variations attendues de la Bourse américaine. Sous 15, calme ; au-dessus de 25, tension ; au-dessus de 35, panique.",
    "rendement": "Le taux d'intérêt que rapporte une obligation, c'est-à-dire un prêt à un État ou une entreprise. Quand le prix de l'obligation monte, son rendement baisse.",
    "point de base": "Un centième de point de pourcentage : passer de 4,88 % à 4,63 %, c'est une baisse de 25 points de base (pb).",
    "écart de taux": "La différence de rendement entre deux pays pour la même durée : l'argent va plutôt vers le pays qui rapporte le plus.",
    "portage": "Emprunter dans une devise qui rapporte peu (le yen) pour placer dans une devise qui rapporte plus (le dollar) et toucher la différence.",
    "valeur refuge": "Un placement recherché quand on a peur : le dollar américain, le yen, le franc suisse et l'or.",
    "PMI": "Une enquête auprès des directeurs d'achat des entreprises : au-dessus de 50, l'activité progresse ; en dessous, elle recule.",
    "consensus": "La prévision moyenne des économistes pour un chiffre à venir : c'est la référence à laquelle le marché compare le chiffre publié.",
    "surprise": "L'écart entre un chiffre publié et sa prévision : c'est lui, et non le chiffre seul, qui fait bouger les devises.",
    "COT": "Le rapport hebdomadaire de l'autorité américaine des marchés à terme (CFTC) qui montre les paris des spéculateurs sur chaque devise.",
    "RSI": "Un indicateur de vitesse du prix sur 14 séances : au-dessus de 70, la hausse a été trop rapide (surachat) ; sous 30, la baisse (survente).",
    "prime de terme": "Le supplément de rendement exigé pour prêter longtemps plutôt que de renouveler des prêts courts : il monte quand la confiance baisse.",
}


def canal(n: int, devise: str | None = None) -> str:
    return (CANAUX_DEVISE.get(devise or "", {}) or {}).get(int(n)) or CANAUX[int(n)]


CONSIGNE_MODELE = (
    "Les huit moteurs du marché se nomment : " + ", ".join(f"« {v[0][0].lower() + v[0][1:]} »" for k, v in MOTEURS.items())
    + ". Cite-les par leur nom (en minuscules dans la phrase). Jamais le mot « engrenage », ni « engrenage » suivi d'un "
    "numéro, ni un numéro de moteur : un contrôle automatique remplace et signale ces mots.")
# Anciens libellés courts utilisés dans les textes (« 2. Monétaire », « engrenage 3 (données économiques) »)
COURTS = {"thème": 1, "monétaire": 2, "données": 3, "fiscale": 4, "marchés": 5, "géopolitique": 6, "flux": 7, "offre": 8}
# Fichiers propres à l'onglet « 8 engrenages » : le mot y reste
FICHIERS_ONGLET = {"dossiers.json", "dossiers_hebdo.json", "moteurs.json", "moteurs_dossiers.json", "documentaire.json"}
SOUS_ARBRES_ONGLET = {"engrenages"}


def nom(n: int, minuscule: bool = False) -> str:
    t = MOTEURS[int(n)][0]
    return t[0].lower() + t[1:] if minuscule else t


def explication(n: int) -> str:
    return MOTEURS[int(n)][1]


def avec_explication(n: int, minuscule: bool = True) -> str:
    return f"{nom(n, minuscule)} ({explication(n)})"


def liste_noms(numeros, minuscule: bool = True) -> str:
    ns = [nom(n, minuscule) for n in numeros]
    if len(ns) <= 1:
        return "".join(ns)
    return ", ".join(ns[:-1]) + " et " + ns[-1]


def decompte(contributions: list[dict]) -> dict:
    """Contributions d'une paire (+ vers la hausse de la paire) -> {pour, contre, neutres, noms_pour, noms_contre}."""
    pour = [c["engrenage"] for c in contributions if (c.get("contribution") or 0) > 0]
    contre = [c["engrenage"] for c in contributions if (c.get("contribution") or 0) < 0]
    return {"pour": len(pour), "contre": len(contre), "neutres": len(contributions) - len(pour) - len(contre),
            "noms_pour": [nom(n, True) for n in pour], "noms_contre": [nom(n, True) for n in contre]}


def de(devise: str) -> str:
    """« de l'AUD », « du GBP »."""
    return f"de l'{devise}" if devise[:1] in "AEIOUY" else f"du {devise}"


def texte_decompte(d: dict, devise: str | None = None) -> str:
    """« 4 moteurs pour, 0 contre » (+ « en faveur de l'AUD » si la devise est donnée)."""
    t = f"{d['pour']} moteur{'s' if d['pour'] > 1 else ''} pour, {d['contre']} contre"
    return t + (f" en faveur de {devise}" if devise else "")


# ------------------------------------------------------------------ remplacement des anciennes formulations
_IDENT = re.compile(r"^[#/\w.\-=:]*$")


def _maj(t: str, debut: bool) -> str:
    return t[0].upper() + t[1:] if debut and t else t


def remplacer(texte: str) -> tuple[str, int]:
    """Anciennes formulations -> noms affichés. Renvoie (texte, nombre de remplacements). Les identifiants et liens
    (« #engrenages/g=3 », « engrenages ») sont laissés tels quels."""
    if not isinstance(texte, str) or "ngrenage" not in texte or _IDENT.match(texte) or texte.startswith(("http", "#")):
        return texte, 0
    n = 0

    def sub(motif, rempl, t, flags=re.I):
        nonlocal n
        t2, k = re.subn(motif, rempl, t, flags=flags)
        n += k
        return t2

    def num(m):
        debut = m.start() == 0 or m.string[max(0, m.start() - 2):m.start()].strip() in (".", ":", "")
        return _maj(nom(int(m.group(1)), True), debut and m.start() == 0)
    t = texte
    t = sub(r"engrenages (\d) et (\d)", lambda m: f"{nom(int(m.group(1)), True)} et {nom(int(m.group(2)), True)}", t)
    t = sub(r"(?:de |l')?(?:l'|le dossier de l')?engrenage (\d)(?: \([^)]*\))?", num, t)
    t = sub(r"\bEngrenages orientés\b", "Moteurs orientés", t, 0)
    t = sub(r"\b([1-8])\. (Thème|Monétaire|Données|Fiscale|Marchés|Géopolitique|Flux|Offre)\b",
            lambda m: nom(int(m.group(1))), t, 0)
    t = sub(r"solde des engrenages", "solde des moteurs", t)
    t = sub(r"cet engrenage", "ce moteur", t)
    t = sub(r"un engrenage", "un moteur", t)
    t = sub(r"(\d+) engrenages? sur (\d+)", r"\1 moteurs sur \2", t)
    t = sub(r"engrenages? alignés?", "moteurs alignés", t)
    t = sub(r"\b(les |des |aux )?8 engrenages\b", lambda m: f"{m.group(1) or ''}8 moteurs du marché", t)
    t = sub(r"\bEngrenages\b", "Moteurs", t, 0)
    t = sub(r"\bEngrenage\b", "Moteur", t, 0)
    t = sub(r"\bengrenages\b", "moteurs", t, 0)
    t = sub(r"\bengrenage\b", "moteur", t, 0)
    return t, n


def nettoyer(obj):
    """Remplace dans toutes les VALEURS texte (jamais les clés) ; renvoie (objet, nombre de remplacements)."""
    total = 0

    def walk(x):
        nonlocal total
        if isinstance(x, dict):   # sous-arbre « engrenages » d'un rapport = contenu de l'onglet dédié : laissé tel quel
            return {k: (v if k in SOUS_ARBRES_ONGLET and isinstance(v, dict) else walk(v)) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str):
            t, k = remplacer(x)
            total += k
            return t
        return x
    return walk(obj), total


def publier(docs_data: Path) -> None:
    """docs/data/moteurs.json : noms et explications pour le site (une seule définition, ici)."""
    (Path(docs_data) / "moteurs.json").write_text(json.dumps(
        {"moteurs": {str(k): {"nom": v[0], "explication": v[1], "question": QUESTIONS[k], "canal": CANAUX[k]} for k, v in MOTEURS.items()},
         "note": "Les 8 moteurs du marché ; numérotation et mot « engrenage » réservés à l'onglet « 8 engrenages »."},
        ensure_ascii=False, indent=1), encoding="utf-8")
    site = Path(docs_data).parent / "site"
    if site.is_dir():
        ecrire_js(site / "moteurs.js")


_JS = r'''/* GÉNÉRÉ par core/noms_moteurs.py (lot V10) : ne pas modifier à la main. Noms affichés des 8 moteurs du marché ;
   le mot « engrenage » et les numéros restent réservés à l'onglet « 8 engrenages ». */
export const MOTEURS = __TABLE__;
const echapper = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export function nomMoteur(n, minuscule = false) {
  const m = MOTEURS[String(n)]; if (!m) return "moteur n/d";
  return minuscule ? m.nom[0].toLowerCase() + m.nom.slice(1) : m.nom;
}
export function explicationMoteur(n) { return MOTEURS[String(n)]?.explication || ""; }
/* Nom avec l'explication courte en infobulle (HTML). */
export function moteurHtml(n, minuscule = false) {
  return `<span class="moteur-nom" title="${echapper(explicationMoteur(n))}">${echapper(nomMoteur(n, minuscule))}</span>`;
}
/* Contributions d'une paire (+ vers la hausse) -> « 4 moteurs pour, 0 contre ». */
export function decompteMoteurs(contributions) {
  const l = contributions || [];
  const pour = l.filter(c => (c.contribution || 0) > 0).length, contre = l.filter(c => (c.contribution || 0) < 0).length;
  return { pour, contre, neutres: l.length - pour - contre, texte: `${pour} moteur${pour > 1 ? "s" : ""} pour, ${contre} contre` };
}
'''


def ecrire_js(chemin: Path) -> None:
    """docs/site/moteurs.js : module généré depuis MOTEURS (le JavaScript affiche, il ne redéfinit rien)."""
    table = json.dumps({str(k): {"nom": v[0], "explication": v[1]} for k, v in MOTEURS.items()}, ensure_ascii=False)
    contenu = _JS.replace("__TABLE__", table)
    if not chemin.exists() or chemin.read_text(encoding="utf-8") != contenu:
        chemin.write_text(contenu, encoding="utf-8")


def nettoyer_publication(docs_data: Path) -> dict[str, int]:
    """Filet de sécurité avant publication : JSON de docs/data (et sous-dossiers paires/, synthese/, contexte/) hors
    fichiers de l'onglet dédié. Renvoie {fichier: remplacements} pour le récapitulatif. Ne lève jamais."""
    docs_data = Path(docs_data)
    bilan = {}
    try:
        publier(docs_data)
    except OSError as exc:
        log.warning("moteurs.json non écrit : %s", exc)
    fichiers = list(docs_data.glob("*.json")) + list(docs_data.glob("paires/*.json")) + list(docs_data.glob("synthese/*.json")) \
        + list(docs_data.glob("contexte/*.json"))
    for f in fichiers:
        if f.name in FICHIERS_ONGLET:
            continue   # onglet dédié
        try:
            brut = f.read_text(encoding="utf-8")
            if "ngrenage" not in brut:
                continue
            obj, n = nettoyer(json.loads(brut))
            if n:
                compact = "\n" not in brut[:200]
                f.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compact else
                             json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
                bilan[str(f.relative_to(docs_data))] = n
        except Exception as exc:  # noqa: BLE001
            log.warning("noms des moteurs : %s non traité (%s)", f.name, exc)
    return bilan
