# Guide : déclencher le rapport avec cron-job.org

Les crons de GitHub Actions peuvent partir avec plusieurs heures de retard, ou ne pas partir du tout aux heures chargées. Un service externe gratuit, **cron-job.org**, peut appeler GitHub à l'heure exacte pour lancer le workflow `rapport-fx`.

Les crons GitHub restent en place **en secours**. Le doublon est évité automatiquement : un passage automatique (cron GitHub ou cron-job.org) qui arrive **moins de 20 minutes** après un autre run réussi ou en cours ne fait rien. Il s'arrête en quelques secondes, sans appel au modèle ni requête de données. Un lancement manuel depuis GitHub n'est jamais bloqué.

Comptez 15 minutes en tout. Vous avez deux choses à faire : créer un jeton GitHub, puis créer trois tâches dans cron-job.org.

---

## Étape 1 : créer le jeton GitHub (5 minutes)

Le jeton est une clé qui permet seulement de **lancer le workflow** de ce dépôt. Il ne peut ni lire vos autres dépôts, ni modifier le code, ni voir les secrets.

1. Sur GitHub, cliquez sur votre photo (en haut à droite), puis **Settings**.
2. Tout en bas du menu de gauche, ouvrez **Developer settings**.
3. Choisissez **Personal access tokens**, puis **Fine-grained tokens**.
4. Cliquez sur **Generate new token**.
5. Remplissez le formulaire :
   - **Token name** : `cron-job.org rapport-fx` ;
   - **Expiration** : *Custom*, puis la date d'aujourd'hui **plus un an**. Notez cette date dans votre agenda : il faudra refaire un jeton à ce moment-là ;
   - **Resource owner** : `pierrickcohendet-sudo` ;
   - **Repository access** : **Only select repositories**, puis choisissez `agents-forex` (et rien d'autre).
6. Dans **Permissions**, partie **Repository permissions**, cherchez **Actions** et choisissez **Read and write**.
   - Ne touchez à rien d'autre. GitHub ajoute tout seul *Metadata : Read-only*, qui est obligatoire et sans risque.
7. Cliquez sur **Generate token**.
8. **Copiez le jeton tout de suite.** Il commence par `github_pat_`. GitHub ne le montrera plus jamais.
   - Ne le collez nulle part ailleurs que dans cron-job.org (étape 2) : ni dans le dépôt, ni dans le site, ni dans un e-mail.

> Si le jeton fuit : retournez dans *Fine-grained tokens*, ouvrez-le et cliquez sur **Revoke**. Il cesse aussitôt de fonctionner.

---

## Étape 2 : créer les trois tâches dans cron-job.org (10 minutes)

1. Créez un compte gratuit sur https://cron-job.org et connectez-vous.
2. Dans **Settings** (votre compte), réglez le **fuseau horaire sur UTC**. Les heures ci-dessous sont en UTC.
3. Créez une première tâche : **Cronjobs**, puis **Create cronjob**.

Les trois tâches ont **les mêmes réglages**, sauf le titre, l'horaire et un mot dans le corps de la requête.

### Réglages communs aux trois tâches

- **URL** (sur une seule ligne) :

  `https://api.github.com/repos/pierrickcohendet-sudo/agents-forex/actions/workflows/rapport.yml/dispatches`

- Dans l'onglet **Advanced** :
  - **Request method** : `POST`.
  - **Headers** : ajoutez ces quatre lignes. Pour la deuxième, remplacez `VOTRE_JETON` par le jeton copié à l'étape 1, et gardez le mot `Bearer` suivi d'une espace.

    | Clé | Valeur |
    |---|---|
    | `Accept` | `application/vnd.github+json` |
    | `Authorization` | `Bearer VOTRE_JETON` |
    | `X-GitHub-Api-Version` | `2022-11-28` |
    | `Content-Type` | `application/json` |

  - **Request body** : voir le tableau suivant. Copiez le texte exactement, guillemets compris.

### Ce qui change d'une tâche à l'autre

| Tâche (titre) | Horaire (UTC) | Corps de la requête (Request body) |
|---|---|---|
| `rapport-fx matin` | 08:15, du lundi au vendredi | `{"ref":"master","inputs":{"declencheur":"externe","creneau":"matin"}}` |
| `rapport-fx heures` | à la minute 15, de 9 h à 21 h, du lundi au vendredi | `{"ref":"master","inputs":{"declencheur":"externe","creneau":"heure"}}` |
| `rapport-fx dimanche` | 07:15, le dimanche | `{"ref":"master","inputs":{"declencheur":"externe","creneau":"dimanche"}}` |

Pour l'horaire, choisissez **Custom** dans cron-job.org, puis cochez :

- **matin** : minute 15 ; heure 8 ; jours lundi, mardi, mercredi, jeudi, vendredi ;
- **heures** : minute 15 ; heures 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20 et 21 ; jours du lundi au vendredi ;
- **dimanche** : minute 15 ; heure 7 ; jour dimanche.

### Vérifier

1. Dans chaque tâche, cliquez sur **Test run**. La réponse attendue est **204** (« No Content ») : c'est un succès, GitHub ne renvoie rien d'autre.
2. Sur GitHub, ouvrez l'onglet **Actions**, puis le workflow **rapport-fx** : un run vient de démarrer.
3. Dans ce run, ouvrez l'étape **Décider du mode** : elle écrit `mode : …` et la raison (complet, complément, hebdo, ou « rien » si un autre run tourne déjà).
4. Dans cron-job.org, activez **Notify me on failure** pour être prévenu par e-mail si GitHub refuse l'appel.

### Si la réponse n'est pas 204

| Code | Cause probable | Que faire |
|---|---|---|
| 401 | Jeton faux, expiré ou mal collé (le mot `Bearer` manque) | Recopiez l'en-tête `Authorization` |
| 403 | Le jeton n'a pas la permission Actions en écriture, ou pas ce dépôt | Refaites l'étape 1 (points 5 et 6) |
| 404 | URL mal recopiée, ou dépôt non choisi dans le jeton | Recopiez l'URL ; vérifiez *Repository access* |
| 422 | Corps de la requête mal recopié (guillemets, accolades) | Recopiez le corps depuis le tableau |

---

## Ce qui se passe ensuite

- **08:15 (cron-job.org)** : run complet du matin. Le cron GitHub de 08:15, s'il arrive dans les 20 minutes, ne fait rien. S'il arrive plus tard, il fait un complément.
- **08:45 (cron GitHub de secours)** : ne fait rien si le rapport du jour existe ; sinon il lance le run complet.
- **Chaque heure de 09:15 à 21:15** : complément (cours, valeurs publiées de l'agenda, analyses restées indisponibles). Sans rapport du jour, c'est un run complet de rattrapage.
- **Dimanche 07:15** : dossier hebdomadaire des engrenages.

Dans un an, à l'expiration du jeton, cron-job.org recevra une erreur 401 et vous préviendra. Refaites l'étape 1, puis remplacez le jeton dans l'en-tête `Authorization` des trois tâches. Les crons GitHub continuent de tourner pendant ce temps.
