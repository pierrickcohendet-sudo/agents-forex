# Pipeline FX — rapport d'analyse quotidien (9 devises)

Pipeline multi-agents Python qui produit chaque jour (et chaque semaine/mois) un
rapport d'analyse macro/technique pour AUD, EUR, CAD, USD, JPY, CHF, GBP, NZD et
CNY, publié automatiquement sur **Notion** (journal archivé) et sur un
**dashboard web GitHub Pages** (vitrine, design personnalisé). Chaque rapport
s'ouvre sur un « état du monde » (économie, politique monétaire/budgétaire,
géopolitique) construit depuis toutes les sources news, avant le détail par devise.

Cas particulier CNY : flottement dirigé (fixing quotidien PBoC, bande étroite) —
la technique classique y est sous-pondérée au profit du fixing et de la politique
PBoC (`ponderations_par_devise` dans config.yaml, méthodologie dans
`connaissances/cas_particuliers.md`). La paire suivie est l'offshore USD/CNH.

> **Contrainte absolue** : le système ne génère JAMAIS de signal d'achat/vente
> exécutable. Uniquement une aide à la décision : biais Risk On/Off, opportunités,
> menaces, classement des devises par score de confluence.

## Comment ça marche

```
collecte technique (Twelve Data)  ─┐
collecte macro (FRED)             ─┤   agent stratège      agent        agent
collecte news (RSS)               ─┼─▶ (Gemini Flash,  ─▶  critique ─▶  rédacteur ─▶ Notion
collecte calendrier (scraping     ─┘   1 appel/devise)     (LLM n°2)        │
  faible empreinte, séquentiel)              │                              └─▶ docs/ ─▶ GitHub Pages
                                             ▼
                              score de confluence, classement,
                              traçabilité, auto-évaluation :
                              CALCULÉS EN PYTHON (core/), pas par le LLM
```

Garanties codées en dur :
- **Score de confluence** : le LLM ne donne que le sens de chaque indicateur
  (+1/-1/0) ; le score `50 + 50·Σ(sens×poids)/Σ(poids)` est calculé dans
  `core/scoring.py` avec les pondérations de `config.yaml`.
- **Traçabilité** : chaque opportunité/menace doit citer un `source_id` du
  catalogue construit en Python à la collecte ; sinon elle est marquée « non
  sourcée » (ou rejetée, selon `tracabilite.mode`). Les sources du
  `detail_score` sont réassignées par le Python depuis un mapping
  indicateur→source construit à la collecte — le LLM ne peut ni les omettre ni
  en inventer. Le biais Risk On/Off affiché par devise est son **profil
  structurel** (`profil_risque` en config : risque/refuge/neutre), dérivé en
  Python — la direction du jour est portée par le score seul.
- **Relecture** : un second appel LLM challenge la synthèse ; « a_revoir »
  n'est jamais bloquant, il ajoute une mention ⚠️ visible.
- **Scraping faible empreinte** (`core/scraping.py`) : 1 requête/site/jour,
  robots.txt respecté, User-Agent de navigateur standard, un seul retry, délais
  aléatoires 5-90 s entre sites, jamais de parallèle, cache de la veille avec
  mention « non rafraîchi », arrêt définitif d'un site après 2 réponses 403.
- **Auto-évaluation hebdo** : chaque lundi, comparaison chiffrée (Python) de la
  prévision de J-7 aux clôtures réelles — taux de réussite affiché même mauvais.
- **Base hebdomadaire cumulative** (`data/hebdo/DEVISE_semaine_AAAA-WNN.json`) :
  chaque jour, upsert du score/biais/sens par devise dans le fichier de la
  semaine ISO. L'« analyse weekly » (rapport du lundi) juge la COHÉRENCE du
  biais sur toute la semaine (trajectoire, écart-type, indicateurs qui
  flip-floppent) — métriques en Python, commentaire seul au LLM.
- **Contrôle qualité à chaque run** (`core/controle_qualite.py`, Python pur) :
  complétude des indicateurs par devise (tableau + detail_score), respect du
  repli à 7 jours (toute valeur porte sa date d'origine, marquage « J-n »),
  rendu complet des 9 devises. Anomalies affichées en bandeau. La justesse des
  prédictions, elle, reste évaluée uniquement en hebdo/mensuel.
- **Suggestions de connaissances** : le relecteur peut proposer des ajouts à
  `connaissances/` (section dédiée du rapport) — jamais appliqués
  automatiquement, vous validez et écrivez à la main.
- **Cohérence biais/texte** : le biais macro global calculé en Python est
  injecté dans le prompt de l'« état du monde » (comme partout ailleurs dans
  le pipeline) et un détecteur mécanique compare le texte généré au biais —
  en cas de contradiction (ex. conclusion qui dit « Risk Off » alors que le
  biais calculé est Risk On), un nouvel essai corrigé est déclenché ; si ça
  persiste, le rapport part quand même avec une anomalie de contrôle qualité
  visible plutôt qu'une contradiction silencieuse.

## Tableau macro (base Notion « Tableau macro » + dashboard)

**Une ligne par couple (indicateur, devise)** — 9 devises (USD, EUR, GBP, JPY, CHF, CAD, AUD, NZD, CNY)
× 10 indicateurs (`config.yaml > tableau_macro.indicateurs`) + une ligne « Indice de surprise 30 j » par
devise — pour comparer **Actuel / Précédent / Prévision** (consensus) sur la même ligne, sans changer de vue.
Colonnes : `Indicateur`, `Actuel`, `Précédent`, `Prévision`, `Surprise` (▲ au-dessus du consensus,
▼ en dessous, = en ligne — calculée en Python, jamais devinée), `Variation`, `Devise`, `Date de publication`,
`Prochaine publication`, `Source`, `Dernière mise à jour`, `Ordre` (masquée). **Vues** : « Toutes les devises »
(groupée par devise) + une vue par devise (filtre `Devise`, lignes dans l'ordre de `config.yaml`), créées par
l'API ; « Default view » supprimée. Si l'API refusait : **+ Add view → Table**, **Filter → Devise = USD**,
**Sort → Ordre ascending**.

Un indicateur qui n'existe pas dans un pays affiche son équivalent local étiqueté (`[équiv. claimants]`,
`[m/m]`…) ou « non publié dans ce pays » / « non couvert par ForexFactory » (définitions :
`connaissances/tableau_macro_definitions.md`) — jamais une case vide muette. Quand le consensus n'existe pas
encore : « consensus à venir » (+ date en `Prochaine publication`) ou la **projection officielle** de la banque
centrale étiquetée « proj. BC » (Fed SEP via FRED).

**Sources.** Les exports officiels Fair Economy (JSON/XML/CSV/ICS, semaine en cours) n'ont **pas** de valeur
« réel » (vérifié le 2026-10-06) ; seule la page web `forexfactory.com/calendar?month=…` les expose (JSON
embarqué, `ebaseId` stable) — testée depuis GitHub Actions (`data/diagnostics/ff_actions.json`). Faible
empreinte : robots.txt, un 403 n'est jamais retenté, **plafond** `forexfactory.plafond_requetes_par_jour`
(6 : créneaux 05:15 et 19:15 UTC, mois suivants lus seulement si des dates manquent, mises à jour ciblées
≥ 15 min après une publication d'impact fort/moyen dont le « réel » manque). FRED : repli des valeurs US
absentes et contrôle croisé (divergence). Registre permanent `data/registre_macro.json` (historique par case,
indépendant de la fenêtre LLM de 7 jours) ; amorçage : `python scripts/initialiser_registre.py` (une fois).
Contrôles (`core/controles_macro.py`) : hors plage, divergence FF/FRED, publication manquée, événement
introuvable ; indice de surprise 30 j (moyenne pondérée des surprises normalisées, chômage inversé).

**Saisie manuelle dans Notion.** Modifiez une cellule `Actuel` / `Précédent` / `Prévision` : le pipeline compare
à la dernière valeur qu'il y a lui-même écrite ; si elle diffère, c'est une saisie — conservée, marquée `✍️`,
enregistrée dans `data/overrides/saisies_notion.json` et injectée dans l'analyse (`core/overrides.py`,
inchangé). Priorité : fichier manuel du jour `data/overrides/AAAA-MM-JJ.json` > saisie Notion > publication
officielle la plus récente — sauf si une publication officielle plus récente que la saisie arrive : elle la
remplace et la saisie passe dans l'historique du fichier.

**Migration (2026-10-08).** L'ancienne structure (une ligne par type, une colonne par devise) est archivée
(« Tableau macro — ancienne structure (archivée …) », conservée, `ancienne_database_id` dans `config.yaml`) ;
les saisies manuelles de l'ancienne base sont capturées avant archivage. Automatique si `database_id` pointe
encore vers l'ancienne structure.

**Rendements obligataires** (lignes « Rendement 2 ans », « Rendement 10 ans », « Spread 2 ans vs USD »).
Données de marché : pas de consensus (Prévision = « — (donnée de marché) »), colonnes Actuel, Précédent =
semaine précédente, Variation en points de base. Sources gratuites vérifiées sur les vraies données
(`config.yaml > tableau_macro.taux_obligataires`), une requête par source et par jour : USD FRED (quotidien) ;
EUR Bundesbank (Allemagne, quotidien) ; GBP Banque d'Angleterre (10 ans seulement) ; JPY ministère des
Finances (~1 semaine de retard) ; CAD Banque du Canada ; CHF / AUD / NZD OCDE via FRED, 10 ans **mensuel**
(étiqueté « mensuel ») ; CNY aucune source gratuite exploitable. Pas de 2 ans pour GBP, CHF (SNB : série
arrêtée en 07/2025), AUD (RBA, 403), NZD (RBNZ, 403) — donc spread 2 ans disponible pour EUR, JPY, CAD.
Le spread alimente la ligne « différentiel de taux » du score de confluence (pondérations inchangées).

**Dashboard web.** Mode « Matrice » (devises en colonnes, sélecteur Actuel/Précédent/Prévision, coloration
par surprise) et mode « Par devise » (mêmes colonnes que Notion), lisibles sur téléphone.

**Graphiques de marché** (`docs/data/marche.json`, FRED) : VIX, pétrole WTI + Brent, indice dollar large de
la Fed (le DXY n'est pas gratuit : jamais appelé « DXY »), période 1 mois / 3 mois / 1 an, dernière valeur et
variation sur 7 jours ; mêmes séries en miniatures dans la section « 📈 Marchés » du rapport Notion.

**Synthèse approfondie par devise** (`agents/agent_synthese.py`, config `synthese_approfondie`). Un appel LLM
dédié par devise, après l'analyse de base et l'état du monde : thèse, 4 moteurs fondamentaux, taux et flux,
géopolitique, lecture technique, 3 scénarios (probabilité qualitative), catalyseurs, invalidation,
opportunités/menaces détaillées. Plan imposé et éditable : `connaissances/synthese/plan_synthese.md` (sous-dossier,
donc jamais chargé dans les autres appels). Garde-fous Python : score/biais intacts, date et heure des catalyseurs
recopiées du registre macro, `source_id` validés, orientation vs score signalée, phrases d'ordre d'achat/vente
retirées. Un échec n'affecte que sa devise ; `--completer` retente la synthèse **seule** (jusqu'à
`tentatives_max`, puis « abandonnée »). Notion : toggle « 📘 Synthèse approfondie » (scénarios en callouts
vert/jaune/rouge) ; web : bloc repliable. Chaque appel est étiqueté dans `meta.appels_llm` (`synthese:EUR`…).

**Modèle LLM et disjoncteur** (`llm.disjoncteur`). Le modèle principal est un nom fixe (`gemini-3.5-flash`) : l'alias
`gemini-flash-latest` était saturé (503) et limité à 20 requêtes/jour (429). Après 3 échecs consécutifs du
principal pendant un run (ou dès un quota journalier épuisé), il est ignoré pour le reste du run ; le suivant le
retente. État dans `meta.disjoncteur` ; le modèle qui a réellement rédigé chaque analyse/synthèse est affiché
(`redige_par`) dans Notion et sur le web.

Tests : `python -m unittest discover -s tests -v` (données factices, sans réseau).

## Repli manuel généralisé (`data/overrides/`)

Le principe déjà utilisé pour les taux directeurs (source affichée « config
(repli manuel) ») s'étend à **n'importe quel indicateur**, pour une date
donnée. Créer `data/overrides/AAAA-MM-JJ.json` :

```json
{
  "USD": {
    "taux_directeur": {"valeur": "4.25 %", "note": "annonce Fed d'urgence, pas encore dans FRED"}
  },
  "CAD": {
    "petrole_contexte": {"valeur": 82.4, "precedent": 79.1, "date": "2026-08-15",
                          "note": "FRED en retard d'un jour"}
  }
}
```

`valeur` obligatoire ; `prevision` / `precedent` / `date` optionnels ; `note`
optionnelle (affichée à côté de « repli manuel »). La valeur prime
systématiquement sur la donnée automatique, dans le tableau **et** dans le
contexte transmis au LLM (le sens +1/-1/0 se base dessus). Le pipeline **ne
write jamais** dans ce dossier — vous l'écrivez vous-même, et un futur run ne
l'écrase jamais, silencieusement ou non.

## Fournisseur LLM de secours (actif : Gemini Flash-Lite, même clé)

Depuis le 2026-10-02, `llm.secours` pointe sur un **second modèle Gemini**
(`gemini-3.5-flash-lite`, même `GEMINI_API_KEY`, gratuit, contexte 1 M tokens —
testé avec un prompt de ~36 000 tokens), sollicité seulement si le modèle
principal échoue sur l'appel (après son retry 429/503). Les compléments
horaires (`--completer`) et `llm.pause_entre_devises_s` (config.yaml) étalent
la charge. Le mécanisme Groq décrit ci-dessous reste implémenté mais désactivé.

### Historique : secours Groq — désactivé

`core/llm.py` expose une seule interface `appeler_llm`, et `creer_fournisseur()`
peut retourner soit Gemini seul, soit un `FournisseurAvecSecours` qui essaie
Gemini d'abord et bascule sur Groq **uniquement si Gemini échoue sur cet appel
précis** — aucun appelant du pipeline (agent stratège, critique, commentaires)
n'a besoin de savoir qu'un repli existe. Le mécanisme est complet, testé et
fonctionnel — mais **`llm.secours.actif: false` par défaut** dans
`config.yaml` depuis le 2026-08-24.

**Pourquoi désactivé — verdict chiffré** : le tier gratuit Groq
(`openai/gpt-oss-20b`/`120b`) est plafonné à **8 000 TPM** (tokens/minute,
fenêtre GLISSANTE — vérifié sur console.groq.com/docs/rate-limits). Or, mesuré
réellement sur ce pipeline : le prompt par devise (mémoire 7 j + news +
catalogue de sources qui grossit toute la journée) fait **70-90 000
caractères ≈ 17 500-22 500 tokens**, et le prompt de l'agent critique (rapport
condensé entier) **88 000+ caractères ≈ 22 000 tokens** — plusieurs fois le
budget total, à eux seuls. Même avec la réduction générique implémentée
(`_reduire_systeme` + `_reduire_message` dans `core/llm.py`, qui tronque
listes et chaînes récursivement sans connaître les noms de champs), rentrer
sous 8 000 TPM exige une troncature si sévère (catalogue à quelques sources,
mémoire à 1 jour) que le résultat n'a plus la richesse d'une analyse tracée à
neuf devises. **Le tier gratuit Groq n'est structurellement pas dimensionné
pour les appels lourds de ce pipeline.** Gemini seul, avec sa dégradation
propre déjà en place (retries, `--completer` qui rattrape plus tard dans la
journée, statuts « analyse indisponible »/« non_evalue » jamais menteurs),
reste le filet de sécurité réel.

Pour réessayer (tier payant Groq, usage ponctuel, ou si le contexte envoyé
baisse structurellement) : `llm.secours.actif: true` + `GROQ_API_KEY` dans
`.env`. Détails techniques conservés si besoin :
- Modèle configurable (`llm.secours.modele`, défaut `openai/gpt-oss-20b` —
  `llama-3.3-70b-versatile` a été retiré des modèles Groq actifs, constaté le
  2026-08-23).
- Budgets exprimés en **tokens** (`budget_tokens_systeme`,
  `budget_tokens_message`, `budget_tokens_total_max` — ~5 000 tokens visés à
  eux deux, marge sous les 8 000 TPM réels). Un garde-fou refuse l'appel
  *avant* tout envoi réseau si encore trop gros après réduction.
- `connaissances_prioritaires` : ordre de priorité des fichiers
  `connaissances/` gardés **entiers** (jamais coupés en plein milieu) si le
  budget système oblige à en omettre.
- Chaque appel LLM (Gemini et Groq) loggue sa taille (caractères + tokens
  estimés à ~4 car./token) pour diagnostiquer un futur dépassement
  immédiatement plutôt que de le déduire d'un code d'erreur.
- Si Gemini **et** Groq échouent tous les deux sur un appel, l'exception
  finale mentionne les deux causes (utile dans `raison_indisponibilite` d'une
  devise marquée « analyse indisponible »).

## Remplissage progressif intra-journée (`--completer`)

```bash
python orchestrateur.py --type quotidien --completer
```

Pensé pour être relancé plusieurs fois par jour (run complet le matin, puis
quelques passages l'après-midi/soir) :
- ne relance **jamais** le scraping des 6 sites une 2ᵉ fois le même jour (déjà
  garanti par le cache 1 req/jour de `core/scraping.py`) ;
- ne re-collecte **jamais** Twelve Data / FRED / RSS non plus : même principe
  généralisé par `core/collecte_cache.py` (`data/cache/collecte_{technique,
  macro,news}.json`) — le run complet du matin collecte frais et écrit le
  cache, les passages `--completer` le réutilisent tel quel plutôt que de
  reconsommer du quota API pour des données qui n'ont probablement pas bougé
  entre deux passages du même jour. Si aucun cache du jour n'existe (ex.
  `--completer` lancé en tout premier), repli automatique sur une collecte
  fraîche ;
- charge le rapport déjà sauvegardé aujourd'hui (`data/rapports/AAAA-MM-JJ.json`)
  et ne rappelle le LLM (agent stratège + agent critique) que pour les
  devises/sections encore « analyse indisponible » — tout ce qui a réussi est
  réutilisé **verbatim**, jamais retraité ;
- upsert de l'entrée du jour (Notion et JSON) — jamais de doublon, c'est déjà
  le comportement par défaut de `agent_redacteur.publier()` et de la
  sauvegarde par date ;
- si rien à compléter, le run s'arrête immédiatement, sans republier ;
- `completer.heure_limite` dans `config.yaml` (défaut `21:00`) est
  **informatif seulement** : au-delà, une ligne de log signale « dernier
  passage de la journée », mais rien n'empêche un lancement manuel plus tard.

Le workflow GitHub Actions déclenche un run complet le matin (05:15 UTC) puis
un passage `--completer` toutes les heures de 06:15 à 21:15 UTC (jours ouvrés),
automatiquement, sans intervention manuelle — voir
`.github/workflows/rapport.yml`.

## Installation locale

```bash
git clone <votre-depot> && cd agents-forex
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # puis remplir les clés
python orchestrateur.py --type quotidien
```

Options : `--type quotidien|hebdomadaire|mensuel|auto` (auto = hebdo le lundi,
mensuel le 1ᵉʳ), `--completer` (passage de complément, voir plus bas),
`--sans-notion`, `--sans-web`.

Pour tester le mode hebdomadaire (auto-évaluation J-7 + analyse weekly) sans
attendre lundi : `python orchestrateur.py --type hebdomadaire`. Sans
`--completer`, `data/hebdo/` s'upserte quand même chaque jour quel que soit le
type — seule l'auto-évaluation/analyse weekly est réservée au hebdo/mensuel.

## Clés API (fichier `.env`, jamais commité)

| Variable | Où l'obtenir |
|---|---|
| `TWELVE_DATA_API_KEY` | twelvedata.com (tier gratuit, 8 crédits/min — le collecteur se limite tout seul) |
| `FRED_API_KEY` | fred.stlouisfed.org → My Account → API Keys (gratuit) |
| `GEMINI_API_KEY` | aistudio.google.com (tier gratuit, modèle famille Flash) |
| `GROQ_API_KEY` *(optionnel mais recommandé)* | console.groq.com (tier gratuit) — fournisseur de **secours**, repli automatique si Gemini échoue |
| `NOTION_API_KEY` | notion.so/my-integrations → nouvelle intégration interne |
| `SLACK_WEBHOOK_URL` *(optionnel)* | webhook entrant Slack pour les alertes d'échec |
| `SMTP_*`, `NOTIF_EMAIL_TO` *(optionnel)* | alertes par email |

### Côté Notion
1. Créer une intégration interne, copier la clé dans `NOTION_API_KEY`.
2. Créer une page parente, la **partager avec l'intégration** (menu ⋯ →
   Connexions), et mettre son URL ou ID dans `config.yaml → notion.page_parent_id`.
3. Au premier run, le pipeline crée une **base de données « Rapports FX »**
   sous cette page (une entrée par jour, propriétés Date / Semaine ISO / Type /
   Biais / Relecture) et écrit son ID dans `config.yaml → notion.database_id`
   (committé ensuite par le workflow — ne pas l'effacer).
4. Une seule action manuelle : ouvrir la base et créer la **vue Calendrier**
   (« + Add view → Calendar » sur la propriété Date).
5. Re-lancer le pipeline le même jour **met à jour** l'entrée du jour (upsert),
   et la section « 📝 Notes personnelles » en bas de chaque entrée n'est
   JAMAIS réécrite : vous pouvez y écrire sans risque. (Côté web, les notes
   sont stockées en localStorage du navigateur.)

⚠️ Avant la première exécution : vérifier les `taux_directeurs` de repli dans
`config.yaml` (valeurs d'exemple) — l'USD se rafraîchit seul via FRED.

## Enrichir la méthodologie (dossier `connaissances/`)

Le prompt système du stratège est la **concaténation de tous les `.md`** de
`connaissances/`, chargée à chaque exécution. Pour ajouter une notion (nouvel
indicateur, cas particulier, exemple annoté) : créer ou éditer un fichier
markdown dans ce dossier. **Aucun code à toucher.** Même logique pour :
- ajouter une **devise** : bloc dans `config.yaml → devises` (+ son taux de repli) ;
- changer une **pondération** ou un indicateur du score : `config.yaml → ponderations` ;
- changer de **modèle LLM** : `config.yaml → llm` (autre fournisseur = une
  classe dans `core/llm.py` derrière l'interface `appeler_llm`).

## Déploiement gratuit : GitHub Actions + GitHub Pages

1. Pousser le dépôt sur GitHub.
2. **Settings → Secrets and variables → Actions** : ajouter les clés
   (`TWELVE_DATA_API_KEY`, `FRED_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`,
   `NOTION_API_KEY`, `SLACK_WEBHOOK_URL` si utilisé).
3. **Settings → Pages** : Source = « Deploy from a branch », branche `main`,
   dossier `/docs`. C'est tout : le site est servi sur
   `https://<user>.github.io/<repo>/`.
4. Le workflow `.github/workflows/rapport.yml` tourne à 05:15 UTC (run complet)
   puis toutes les heures de 06:15 à 21:15 UTC (passages `--completer` automatiques, jours
   ouvrés, modifiable) — ces passages rattrapent seuls les devises encore
   « analyse indisponible » après le matin, aucune intervention manuelle
   requise. Le pipeline committe lui-même `docs/data/` (site), `data/rapports/`,
   `data/cache/` et `data/hebdo/` (mémoire entre runs). Lancement manuel
   possible : onglet Actions → Run workflow (case à cocher pour forcer
   `--completer`).

Note : `data/rapports/`, `data/cache/`, `data/hebdo/` et `data/overrides/`
sont **volontairement committés** — GitHub Actions est sans état, c'est la
mémoire du système (et `data/overrides/` est écrit par vous, jamais par le
pipeline).

### Alternative VPS (cron)

```bash
crontab -e
# 07:15 heure locale, jours ouvrés :
15 7 * * 1-5 cd /opt/agents-forex && .venv/bin/python orchestrateur.py >> data/logs/cron.log 2>&1
```

Le push GitHub Pages depuis un VPS : passer `publication_web.git_push: toujours`
dans `config.yaml` (le VPS doit avoir un remote git authentifié), ou `jamais`
pour un dashboard purement local.

## Dashboard web (`docs/`)

HTML/CSS/JS natif + Chart.js (CDN), zéro backend : `app.js` charge
`data/latest.json`, le sélecteur de date recharge `data/AAAA-MM-JJ.json`
(historique listé dans `data/index.json`). Thème sombre type terminal ; couleurs
Risk On (vert) / Risk Off (rouge) / Neutre (jaune) toujours doublées du libellé
texte. Notion reste généré en parallèle ; pour l'arrêter un jour :
`notion.actif: false` — le reste du pipeline est indépendant.

## Fenêtre glissante LLM (7 jours) — découplée de l'archive complète

`config.yaml → memoire.fenetre_jours` (7 par défaut) borne STRICTEMENT, en
jours calendaires, tout ce qui part dans le prompt envoyé au LLM : les
rapports précédents (`memoire_rapports_precedents`) ET les événements
calendrier (`calendrier_devise`, `catalogue_sources`). Cette fenêtre n'a
**aucun rapport** avec l'archive : `data/rapports/`, le dashboard web et la
base Notion conservent 100 % de l'historique sans aucune limite — la fenêtre
ne fait QUE réduire le contexte envoyé au modèle, jamais ce qui est stocké ou
affiché.

Avant le 2026-08-29, deux bugs faisaient fuiter bien plus de 7 jours dans le
prompt sans que rien ne le signale : `charger_memoire()` prenait les 7
**fichiers** les plus récents (pas les 7 derniers jours — avec des trous dans
l'historique de génération, ça pouvait remonter à 14 jours) ; et le magasin
calendrier (`core/collecte_calendrier.py`) alimentait le contexte LLM sans
second filtre, avec 10 jours de rétention. Les deux fenêtres sont maintenant
strictement bornées et indépendantes de l'archive — mesuré sur les données
réelles du projet, le fix a réduit le contexte LLM de 22,5 % (15 574 → 12 062
tokens estimés) le jour même du correctif. `assembler_contexte()` déduplique
aussi le catalogue de sources entre deux passages `--completer` du même jour
(sans ça, il doublait — confirmé 256 sources contre ~135 un jour normal).

## Structure du rapport JSON

Un seul schéma pour Notion, le site et l'historique : voir
`data/rapports/AAAA-MM-JJ.json` après une exécution (méta, synthèse globale +
classement, 8 volets devise avec `detail_score` pondéré, sources citées,
données non rafraîchies, critique, prix de clôture pour l'auto-évaluation).

## Dépannage

- **Rapport généré mais incomplet** : normal — toute source en échec est listée
  dans « Données non rafraîchies » et le reste continue.
- **Site 403 en boucle** : le site est blacklisté après 2 réponses 403
  (`data/cache/blacklist_403.json` ; supprimer le fichier pour réessayer).
- **Pas de page Notion** : vérifier que la page parente est bien partagée avec
  l'intégration et que `page_parent_id` est renseigné.
- **Base Notion en double ?** Impossible en pratique : le rédacteur lit d'abord
  `notion.database_id` dans config.yaml, puis, s'il est vide, cherche une base
  « Rapports FX » déjà existante sous la page parente avant d'en créer une
  (relance après plantage ou avant le commit GitHub Actions = réutilisation).
  Seule exception : renommer la base dans Notion alors que config.yaml est
  vide — dans ce cas, remettre son ID à la main dans `notion.database_id`.
- **Auto-évaluation absente le lundi** : il faut au moins un rapport vieux de
  ~7 jours dans `data/rapports/`.
