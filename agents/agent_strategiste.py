"""Agent stratège.

- Prompt système construit dynamiquement : concaténation de TOUS les fichiers
  .md du dossier connaissances/ (la méthodologie s'enrichit en éditant un
  fichier texte, jamais le code) + règles de sortie strictes.
- Un appel LLM par devise : le LLM ne produit que le SENS des indicateurs
  (+1/-1/0), les opportunités/menaces sourcées et les textes courts.
- Le score de confluence, le classement, le carry et le catalogue de sources
  sont calculés/injectés en Python (core/scoring.py) — jamais par le LLM.
- Contexte : données du jour + les N derniers rapports (mémoire).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import overrides, scoring
from core.llm import FournisseurLLM, extraire_json

log = logging.getLogger(__name__)

REGLES_SORTIE = """
## RÈGLES DE SORTIE — NON NÉGOCIABLES

1. Tu ne produis JAMAIS de signal d'achat/vente exécutable, ni de niveau
   d'entrée recommandé. Uniquement : biais Risk On/Off, scénarios argumentés,
   opportunités et menaces.
2. Tu ne choisis JAMAIS de score de conviction. Pour chaque indicateur demandé,
   tu donnes seulement un sens : +1 (haussier pour la devise), -1 (baissier),
   0 (neutre ou donnée manquante). Le score final est calculé par programme.
   Le biais Risk On/Off structurel de la devise est lui aussi dérivé par
   programme depuis son profil configuré : tu ne le fournis pas.
3. Toute affirmation dans "opportunites", "menaces", "detail_score",
   "tendance_fond" ou "contexte_geopolitique" doit citer un source_id EXISTANT
   dans le catalogue fourni (format src_NNN, listé dans catalogue_sources).
   Tout identifiant hors catalogue est automatiquement invalidé et
   l'affirmation marquée « non sourcée » dans le rapport publié : sans source
   réelle, mets null, n'invente JAMAIS un identifiant.
4. Une donnée macro se lit par rapport aux attentes (prévision) ET au
   précédent, jamais en valeur absolue.
5. Une divergence inhabituelle entre corrélations attendues et mouvement
   observé se signale comme suspecte (menace), elle ne se suit pas aveuglément.
6. Style note de desk : phrases courtes, donnée d'abord puis interprétation,
   aucune formule de remplissage ("il est important de noter", "dans
   l'ensemble"...). Français.
7. Réponds UNIQUEMENT avec le JSON demandé, sans texte autour.
"""

SCHEMA_DEVISE = """{
  "devise": "XXX",
  "biais_banque_centrale": "hawkish" | "dovish" | "data_dependent",
  "tendance_fond": {"unite_temps": "weekly", "sens": "haussier"|"baissier"|"range",
                     "commentaire": "...", "source_id": "src_NNN ou null"},
  "detail_score": [{"indicateur": "<nom exact de la liste fournie>", "sens": 1|-1|0,
                     "justification": "donnée chiffrée puis lecture, 1 phrase",
                     "source_id": "src_NNN ou null"}],
  "opportunites": [{"texte": "...", "source_id": "src_NNN"}],
  "menaces": [{"texte": "...", "source_id": "src_NNN"}],
  "synthese_une_phrase": "...",
  "contexte_geopolitique": {
    "banque_centrale_pourquoi": {"texte": "1-2 phrases : la posture ACTUELLE et POURQUOI, pas juste le mot-clé",
                                  "source_id": "src_NNN ou null"},
    "evenements": [{"texte": "décision politique ou événement géopolitique concernant CETTE devise cette semaine",
                     "source_id": "src_NNN"}]
  }
}"""


DOSSIER_CONNAISSANCES = Path(__file__).resolve().parent.parent / "connaissances"


# ------------------------------------------------------------- connaissances
def charger_connaissances(dossier: str | Path | None = None) -> str:
    """Concatène tous les .md du dossier, par ordre alphabétique."""
    dossier = Path(dossier) if dossier else DOSSIER_CONNAISSANCES
    morceaux = []
    for fichier in sorted(dossier.glob("*.md")):
        morceaux.append(f"\n\n# ===== {fichier.name} =====\n\n" + fichier.read_text(encoding="utf-8"))
    if not morceaux:
        log.warning("Dossier connaissances/ vide : prompt système réduit aux règles de sortie")
    return "".join(morceaux)


def construire_prompt_systeme(dossier_connaissances: str | Path | None = None) -> str:
    return (
        "Tu es un analyste de desk FX senior. Tu produis une aide à la décision "
        "macro/technique sur 8 devises, jamais des signaux exécutables.\n"
        + REGLES_SORTIE
        + "\n## MÉTHODOLOGIE DE RÉFÉRENCE (base de connaissances)\n"
        + charger_connaissances(dossier_connaissances)
    )


# ------------------------------------------------------------------ mémoire
def charger_memoire(dossier_rapports: str | Path, jours: int = 7) -> list[dict]:
    """Condensé des rapports des `jours` derniers JOURS GLISSANTS — fenêtre
    strictement bornée dans le temps, jamais plus, quels que soient les trous
    dans l'historique de génération. AVANT ce fix (incident du 2026-08-29) :
    prenait les N fichiers les plus récents, pas les N derniers jours — avec
    des trous (ex. pas de run 3 jours de suite), ça pouvait injecter au LLM
    des données vieilles de 14 jours en croyant se limiter à 7. L'archive
    COMPLÈTE, elle, n'est ni filtrée ni limitée ici : data/rapports/ et Notion
    conservent 100 % de l'historique sans aucun rapport avec cette fenêtre —
    cette fonction ne fait QUE construire le contexte envoyé au LLM."""
    dossier = Path(dossier_rapports)
    limite = (date.today() - timedelta(days=jours - 1)).isoformat()
    memoire = []
    for fichier in sorted(dossier.glob("????-??-??.json"), reverse=True):
        if fichier.stem < limite:
            break  # noms de fichiers triés par date -> tout le reste est plus vieux encore
        try:
            rapport = json.loads(fichier.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        memoire.append({
            "date": rapport.get("meta", {}).get("date_rapport", fichier.stem),
            "biais_macro_global": rapport.get("synthese_globale", {}).get("biais_macro_global"),
            "classement": [
                f"{c['rang']}. {c['devise']} ({c['score_confluence']})"
                for c in rapport.get("synthese_globale", {}).get("classement_devises", [])
            ],
            "syntheses": {
                d["devise"]: d.get("synthese_une_phrase")
                for d in rapport.get("devises", [])
            },
        })
    return memoire


# ------------------------------------------- catalogue de sources (Python)
def assembler_contexte(config: dict, technique: dict, macro: dict,
                       news: dict, calendrier: dict, fenetre_jours: int = 7,
                       catalogue_existant: list[dict] | None = None) -> tuple[dict, list[dict]]:
    """Attribue un src_NNN à chaque donnée collectée et retourne
    (données annotées, catalogue sources_citees).

    fenetre_jours : plafond STRICT et explicite sur les événements calendrier
    injectés dans le contexte LLM (calendrier_devise), indépendant de la
    rétention du magasin glissant (core/collecte_calendrier.py — peut évoluer
    pour d'autres besoins sans jamais élargir silencieusement ce qui part au
    LLM). Incident du 2026-08-29 : le magasin retenait 10 jours, tout partait
    au LLM sans second filtre.

    catalogue_existant (mode --completer) : sources_citees d'un rapport déjà
    sauvegardé le même jour. On les CONSERVE telles quelles (mêmes ids) et on
    numérote la suite après — sinon les devises déjà réussies et réutilisées
    verbatim référenceraient des src_NNN qui n'existeraient plus dans le
    catalogue reconstruit, et la traçabilité les marquerait à tort "non
    sourcées". DÉDUPLIQUÉ par (source, detail, date) : sans ça, chaque
    passage --completer supplémentaire re-cataloguait les MÊMES données sous
    de nouveaux id, faisant doubler le catalogue au lieu de le réutiliser
    (confirmé : 256 sources le 2026-08-23 contre ~135 un jour à passage
    unique)."""
    catalogue: list[dict] = list(catalogue_existant or [])
    index_existant = {(s.get("source"), s.get("detail"), s.get("date")): s["id"] for s in catalogue}
    compteur = len(catalogue)

    def src(source: str, detail: str, date_donnee: str | None, url: str | None = None) -> str:
        nonlocal compteur
        cle = (source, detail, date_donnee)
        if cle in index_existant:
            return index_existant[cle]
        compteur += 1
        identifiant = f"src_{compteur:03d}"
        catalogue.append({"id": identifiant, "source": source, "detail": detail,
                          "date": date_donnee, "url": url})
        index_existant[cle] = identifiant
        return identifiant

    limite_calendrier = (date.today() - timedelta(days=fenetre_jours - 1)).isoformat()

    donnees: dict = {"macro": {"series": {}}, "technique": {}, "calendrier": [],
                     "news": [], "sites_scrapes": {}}

    for nom, serie in macro.get("series", {}).items():
        entree = dict(serie)
        entree["source_id"] = src("FRED", f"{nom} ({serie['serie_id']})", serie["date"],
                                  f"https://fred.stlouisfed.org/series/{serie['serie_id']}")
        donnees["macro"]["series"][nom] = entree

    if macro.get("yield_curve", {}).get("disponible"):
        yc = dict(macro["yield_curve"])
        yc["source_id"] = src("FRED", "yield curve US 10Y-2Y (DGS10/DGS2)", yc.get("date"))
        donnees["macro"]["yield_curve"] = yc

    if macro.get("taux_directeurs"):
        id_taux = src("FRED + config", "taux directeurs des 8 devises",
                      date.today().isoformat())
        donnees["macro"]["taux_directeurs"] = {
            "source_id": id_taux, "valeurs": macro["taux_directeurs"],
            "carry": macro.get("carry"),
        }

    for devise, indicateurs in technique.get("devises", {}).items():
        entree = dict(indicateurs)
        entree["source_id"] = src("Twelve Data (calculs locaux)",
                                  f"technique {devise} — {indicateurs['paire']}",
                                  date.today().isoformat())
        donnees["technique"][devise] = entree

    if technique.get("correlations"):
        donnees["correlations"] = {
            "source_id": src("Calcul local (Pearson, rendements Twelve Data)",
                             "matrice de corrélations 8 devises", date.today().isoformat()),
            "matrice": technique["correlations"],
        }

    evenements_recents = [
        e for e in calendrier.get("evenements", [])
        if e.get("date") and e["date"] >= limite_calendrier
    ]
    if len(evenements_recents) < len(calendrier.get("evenements", [])):
        log.info("Calendrier : %d événement(s) au-delà de %d jours écartés du contexte LLM "
                 "(magasin glissant conservé intact, %d retenus)",
                 len(calendrier.get("evenements", [])) - len(evenements_recents),
                 fenetre_jours, len(evenements_recents))
    for evenement in evenements_recents[:80]:
        entree = dict(evenement)
        entree["source_id"] = src("ForexFactory", evenement["evenement"], evenement.get("date"))
        donnees["calendrier"].append(entree)

    for article in news.get("articles", [])[:30]:
        entree = dict(article)
        entree["source_id"] = src(f"RSS {article['source']}", article["titre"][:120],
                                  article.get("date"), article.get("lien"))
        donnees["news"].append(entree)

    for site, info in calendrier.get("sites", {}).items():
        if info.get("titres"):
            donnees["sites_scrapes"][site] = {
                "source_id": src(site, "titres extraits (page publique)", info.get("date_donnee")),
                "titres": info["titres"][:15],
                "note": info.get("note", ""),
            }

    donnees["_sources_indicateurs"] = _sources_par_indicateur(config, donnees)
    return donnees, catalogue


def _sources_par_indicateur(config: dict, donnees: dict) -> dict[str, dict[str, str | None]]:
    """Mapping devise -> indicateur -> source_id, construit en Python à la
    collecte. C'est LUI qui fait foi pour le detail_score : les source_id
    renvoyés par le LLM y sont réalignés (fin des null quand la donnée existe
    et des identifiants inventés)."""
    series = donnees["macro"]["series"]
    id_vix = (series.get("vix") or {}).get("source_id")
    id_yc = (donnees["macro"].get("yield_curve") or {}).get("source_id")
    id_taux = (donnees["macro"].get("taux_directeurs") or {}).get("source_id")
    id_dxy = (donnees["technique"].get("USD") or {}).get("source_id")

    mapping: dict[str, dict[str, str | None]] = {}
    for devise in config["devises"]:
        cibles = {devise} | ({"CNY"} if devise in ("AUD", "NZD") else set())
        evenements = [e for e in donnees["calendrier"] if e["devise"] in cibles]

        def evenement_id(*mots: str) -> str | None:
            for evt in evenements:
                titre = evt["evenement"].lower()
                if any(mot in titre for mot in mots):
                    return evt["source_id"]
            return None

        mapping[devise] = {
            "taux_directeur": id_taux,
            "differentiel_taux": id_taux,
            "yield_curve": id_yc,
            "vix": id_vix,
            "dxy": id_dxy,
            "rsi": (donnees["technique"].get(devise) or {}).get("source_id"),
            "trendline": (donnees["technique"].get(devise) or {}).get("source_id"),
            "cpi_surprise": evenement_id("cpi", "inflation", "pce"),
            "pmi_surprise": evenement_id("pmi", "ism"),
            "fixing_pboc": evenement_id("fix", "reference rate", "lpr", "pboc", "mlf"),
        }
    return mapping


# ------------------------------------------------------- tableau indicateurs
LIBELLES_INDICATEURS = {
    "taux_directeur": "Taux directeur",
    "differentiel_taux": "Différentiel vs médiane G8",
    "yield_curve": "Yield curve US (10Y-2Y)",
    "vix": "VIX",
    "dxy": "Indice USD (5 j)",
    "cpi_surprise": "Inflation (CPI)",
    "pmi_surprise": "PMI",
    "fixing_pboc": "Fixing / politique PBoC",
    "rsi": "RSI (daily)",
    "trendline": "Structure de tendance",
}


def _evenement_recent(evenements: list[dict], mots: tuple[str, ...]) -> dict | None:
    """Événement calendrier le plus récent portant une valeur, dans la limite du
    repli à 7 jours (jamais un événement futur, jamais au-delà de 7 j)."""
    auj = date.today()
    candidats = []
    for evt in evenements:
        if not evt.get("date") or not any(m in evt["evenement"].lower() for m in mots):
            continue
        try:
            anciennete = (auj - date.fromisoformat(evt["date"])).days
        except ValueError:
            continue
        if 0 <= anciennete <= 7 and (evt.get("reel") or evt.get("prevision")):
            candidats.append((anciennete, evt))
    # key= obligatoire : à ancienneté égale (deux publications le même jour),
    # min() sans key comparerait les dicts eux-mêmes -> TypeError.
    return min(candidats, key=lambda c: c[0])[1] if candidats else None


def _tableau_indicateurs(config: dict, devise: str, donnees: dict,
                         overrides_devise: dict | None = None) -> list[dict]:
    """UNE ligne par indicateur configuré pour la devise (pondérations
    effectives), même neutre ou sans publication — avec la date d'ORIGINE de
    chaque valeur (règle : jamais confondre une donnée J-3 avec une du jour).
    overrides_devise (data/overrides/, repli manuel) est appliqué en DERNIER
    et prime systématiquement sur toute donnée automatique."""
    auj = date.today()
    series = donnees["macro"]["series"]
    technique = donnees["technique"].get(devise) or {}
    bloc_taux = donnees["macro"].get("taux_directeurs") or {}
    taux = (bloc_taux.get("valeurs") or {}).get(devise) or {}
    differentiel = ((bloc_taux.get("carry") or {}).get("differentiels") or {}).get(devise)
    yield_curve = donnees["macro"].get("yield_curve") or {}
    cibles = {devise} | ({"CNY"} if devise in ("AUD", "NZD") else set())
    evenements = [e for e in donnees.get("calendrier", []) if e["devise"] in cibles]

    lignes: list[dict] = []

    def ligne(indicateur: str, nom: str, valeur, prevision=None, precedent=None,
              source: str = "—", date_donnee: str | None = None, note: str = "") -> None:
        anciennete = None
        if date_donnee:
            try:
                anciennete = (auj - date.fromisoformat(str(date_donnee)[:10])).days
            except ValueError:
                anciennete = None
        lignes.append({
            "indicateur": indicateur, "nom": nom, "valeur": valeur,
            "prevision": prevision, "precedent": precedent, "source": source,
            "date": date_donnee, "anciennete_jours": anciennete, "note": note,
        })

    mots_evenements = {
        "cpi_surprise": ("cpi", "inflation", "pce"),
        "pmi_surprise": ("pmi", "ism"),
        "fixing_pboc": ("fix", "reference rate", "lpr", "pboc", "mlf"),
    }

    for indicateur in scoring.ponderations_devise(config, devise):
        nom = LIBELLES_INDICATEURS.get(indicateur, indicateur)
        if indicateur == "taux_directeur":
            ligne(indicateur, nom, f"{taux.get('taux', '—')} %",
                  source=taux.get("source", "config"), date_donnee=taux.get("date"))
        elif indicateur == "differentiel_taux":
            ligne(indicateur, nom,
                  None if differentiel is None else f"{differentiel:+.2f} pt",
                  source="calcul (FRED + config)", date_donnee=auj.isoformat())
        elif indicateur == "yield_curve":
            if yield_curve.get("disponible"):
                ligne(indicateur, nom, f"{yield_curve['spread_10y_2y']} ({yield_curve['regime']})",
                      precedent=None, source="FRED (DGS10/DGS2)", date_donnee=yield_curve.get("date"))
            else:
                ligne(indicateur, nom, None, source="FRED", note="série indisponible")
        elif indicateur == "vix":
            serie = series.get("vix")
            if serie:
                ligne(indicateur, nom, serie["valeur"], precedent=serie["precedent"],
                      source="FRED (VIXCLS)", date_donnee=serie["date"])
            else:
                ligne(indicateur, nom, None, source="FRED", note="série indisponible")
        elif indicateur == "dxy":
            usd = donnees["technique"].get("USD") or {}
            variation = usd.get("variation_5j_pct")
            ligne(indicateur, nom, None if variation is None else f"{variation:+.2f} %",
                  source="calcul local (Twelve Data)", date_donnee=auj.isoformat())
        elif indicateur == "rsi":
            if technique.get("rsi") is not None:
                ligne(indicateur, nom, f"{technique['rsi']} ({technique.get('rsi_lecture', '')})",
                      source="calcul local (Twelve Data)", date_donnee=auj.isoformat())
            else:
                ligne(indicateur, nom, None, source="Twelve Data", note="données techniques indisponibles")
        elif indicateur == "trendline":
            tendance = technique.get("tendance_fond") or {}
            zones = technique.get("zones_consolidation") or []
            if tendance:
                ligne(indicateur, nom,
                      f"{tendance.get('sens', '—')} weekly, {len(zones)} zone(s)",
                      source="calcul local (Twelve Data)", date_donnee=auj.isoformat())
            else:
                ligne(indicateur, nom, None, source="Twelve Data", note="données techniques indisponibles")
        elif indicateur in mots_evenements:
            evenement = _evenement_recent(evenements, mots_evenements[indicateur])
            if evenement:
                ligne(indicateur, f"{nom} — {evenement['evenement'][:60]}",
                      evenement.get("reel"), evenement.get("prevision"),
                      evenement.get("precedent"), "ForexFactory", evenement.get("date"))
            else:
                ligne(indicateur, nom, None, source="ForexFactory",
                      note="aucune publication < 7 j")
        else:
            ligne(indicateur, nom, None, note="indicateur sans source câblée")

    # Contexte pétrole pour le CAD (devise pétrolière), hors score.
    if devise == "CAD":
        wti = series.get("petrole_wti")
        if wti:
            ligne("petrole_contexte", "Pétrole WTI (contexte)", wti["valeur"],
                  precedent=wti["precedent"], source="FRED", date_donnee=wti["date"])

    return overrides.appliquer_au_tableau(lignes, overrides_devise, auj)


# ------------------------------------------------------------ appels LLM
def _analyser_devise(llm: FournisseurLLM, systeme: str, config: dict, devise: str,
                     donnees: dict, catalogue: list[dict], memoire: list[dict],
                     overrides_devise: dict | None = None) -> dict:
    indicateurs = list(scoring.ponderations_devise(config, devise).keys())
    contexte = {
        "devise_analysee": devise,
        "banque_centrale": config["devises"][devise]["banque_centrale"],
        "indicateurs_a_evaluer": indicateurs,
        "reprises_manuelles_du_jour": overrides_devise or {},
        "note_reprises_manuelles": (
            "Si reprises_manuelles_du_jour contient un indicateur, sa valeur PRIME "
            "systématiquement sur toute donnée automatique du contexte ci-dessous pour "
            "ce même indicateur (donnée automatique erronée ou manquante, corrigée à la "
            "main) — base ton sens et ta justification dessus, pas sur la donnée brute."
        ) if overrides_devise else None,
        "note_indicateurs": (
            "cpi_surprise / pmi_surprise : surprise vs prévision du calendrier pour CETTE devise. "
            "yield_curve et vix : lire l'effet SUR cette devise (contexte risk on/off). "
            "dxy : indice USD synthétique fourni dans technique.USD. "
            "differentiel_taux : carry fourni dans macro.taux_directeurs.carry. "
            "rsi / trendline : données technique de la devise. "
            "fixing_pboc (CNY uniquement) : direction du fixing quotidien PBoC et des "
            "décisions de politique (LPR, MLF, RRR) d'après le calendrier et les news ; "
            "0 si aucune information de fixing aujourd'hui."
        ),
        "note_contexte_geopolitique": (
            "Pour contexte_geopolitique.banque_centrale_pourquoi : explique la posture "
            "ACTUELLE de la banque centrale de cette devise EN UNE À DEUX PHRASES "
            "(quel mandat elle poursuit là maintenant et pourquoi, ex. 'combat une "
            "inflation encore au-dessus de la cible' ou 'attend confirmation avant de "
            "bouger, prochaine réunion dans N semaines') — jamais juste le mot-clé "
            "hawkish/dovish/data_dependent seul. "
            "Pour contexte_geopolitique.evenements : décisions ou événements "
            "géopolitiques de la semaine qui concernent SPÉCIFIQUEMENT cette devise "
            "(pas les généralités déjà couvertes ailleurs) — liste vide si rien de "
            "spécifique cette semaine, ne force jamais un événement générique."
        ),
        "technique_devise": donnees["technique"].get(devise),
        "technique_usd_reference": donnees["technique"].get("USD"),
        "correlations_devise": (donnees.get("correlations", {}).get("matrice", {}) or {}).get(devise),
        "macro": donnees["macro"],
        "calendrier_devise": [e for e in donnees["calendrier"]
                              if e["devise"] in ({devise} | ({"CNY"} if devise in ("AUD", "NZD") else set()))],
        "news": donnees["news"],
        "sites_scrapes": donnees["sites_scrapes"],
        "memoire_rapports_precedents": memoire,
        "catalogue_sources": catalogue,
    }
    ids_valides = ", ".join(s["id"] for s in catalogue)
    prompt = (
        f"Analyse la devise {devise} avec les données du jour ci-dessous.\n"
        f"Réponds STRICTEMENT selon ce schéma JSON :\n{SCHEMA_DEVISE}\n\n"
        "Le champ detail_score doit contenir UNE entrée par indicateur de "
        "indicateurs_a_evaluer, avec son nom exact.\n"
        f"SEULS ces source_id existent : [{ids_valides}]. Tout autre identifiant "
        "sera invalidé et l'affirmation publiée comme « non sourcée » — mets null "
        "plutôt que d'inventer.\n\n"
        "DONNÉES DU JOUR (JSON) :\n" + json.dumps(contexte, ensure_ascii=False, default=str)
    )

    tentatives = int(config["llm"].get("max_tentatives_json", 2))
    derniere_erreur: Exception | None = None
    for essai in range(1, tentatives + 1):
        try:
            return extraire_json(llm.appeler_llm(prompt, systeme=systeme))
        except Exception as exc:  # noqa: BLE001 — parsing JSON ou erreur API : on retente
            derniere_erreur = exc
            log.warning("Analyse %s, essai %d/%d en échec : %s", devise, essai, tentatives, exc)
    raise RuntimeError(f"Analyse {devise} impossible : {derniere_erreur}")


def _devise_indisponible(devise: str, raison: str, biais: str = "neutre") -> dict:
    """Entrée de repli : la devise reste dans le rapport avec un statut
    explicite, un score None (exclue du classement), et ne fait JAMAIS planter
    le reste — un échec sur une devise ne coûte que cette devise."""
    return {
        "devise": devise, "risk_on_off": biais,
        "score_confluence": None,
        "analyse_indisponible": True,
        "raison_indisponibilite": raison,
        "biais_banque_centrale": "data_dependent",
        "tendance_fond": {"unite_temps": "weekly", "sens": "range",
                          "commentaire": f"analyse indisponible ({raison})", "source_id": None},
        "detail_score": [], "opportunites": [], "menaces": [],
        "synthese_une_phrase": f"Analyse indisponible aujourd'hui : {raison}.",
        "indicateurs_tableau": [],
        "contexte_geopolitique": {
            "banque_centrale_pourquoi": {"texte": "", "source_id": None}, "evenements": [],
        },
    }


def _normaliser_contexte_geopolitique(brut: dict) -> dict:
    """Contexte géopolitique & décisions par devise, distinct de l'état du
    monde global et du tableau d'indicateurs : posture de banque centrale
    EXPLIQUÉE (pas juste le mot-clé) + événements datés spécifiques à la devise."""
    contexte = brut.get("contexte_geopolitique") or {}
    pourquoi = contexte.get("banque_centrale_pourquoi") or {}
    if isinstance(pourquoi, str):  # tolérance si le LLM renvoie une chaîne nue
        pourquoi = {"texte": pourquoi, "source_id": None}
    evenements = [
        {"texte": str(e.get("texte", ""))[:300], "source_id": e.get("source_id")}
        for e in (contexte.get("evenements") or [])[:6]
        if isinstance(e, dict) and e.get("texte")
    ]
    return {
        "banque_centrale_pourquoi": {
            "texte": str(pourquoi.get("texte", ""))[:500], "source_id": pourquoi.get("source_id"),
        },
        "evenements": evenements,
    }


SCHEMA_ETAT_DU_MONDE = """{
  "situation_economique": {"texte": "2-4 phrases", "source_ids": ["src_NNN"]},
  "politique_monetaire_budgetaire": {"texte": "2-4 phrases", "source_ids": ["src_NNN"]},
  "geopolitique": {"texte": "2-4 phrases", "source_ids": ["src_NNN"]},
  "indicateurs_du_jour": [{"symbole": "✅"|"❌"|"➖",
      "texte": "Nom : <réel> vs <prévision> attendu (précédent <précédent>) — lecture en quelques mots",
      "source_id": "src_NNN"}],
  "actualite": [{"texte": "titre réel de la news + contexte en une phrase", "source_id": "src_NNN"}],
  "conclusion": "paragraphe de 3 à 5 phrases, ton analyste professionnel"
}"""

SYMBOLES_BRIEFING = {"✅", "❌", "➖"}
LIBELLES_BIAIS_TEXTE = {"risk_on": "Risk On", "risk_off": "Risk Off", "neutre": "Neutre"}
TENTATIVES_COHERENCE_BIAIS = 2


def _detecter_incoherence_biais(etat: dict, biais_attendu: str) -> bool:
    """Détecteur mécanique, best-effort : le vocabulaire du projet utilise
    TOUJOURS les termes anglais 'Risk On'/'Risk Off' tels quels (jamais
    traduits ni paraphrasés — convention déjà en place dans tout le rapport).
    Un texte narratif qui emploie le terme OPPOSÉ au biais_macro_global
    calculé par programme est une contradiction manifeste et détectable sans
    ambiguïté. Ne détecte pas les paraphrases ('la prudence domine' seul, sans
    le terme explicite) : c'est un filet mécanique, pas une analyse
    sémantique — l'agent critique reste le filet pour les cas plus subtils.
    Un texte qui mentionne les deux termes (ex. transition « de Risk On à
    Risk Off ») n'est pas signalé : ambigu, potentiellement légitime."""
    texte = " ".join([
        etat.get(cle, {}).get("texte", "") if isinstance(etat.get(cle), dict) else ""
        for cle in ("situation_economique", "politique_monetaire_budgetaire", "geopolitique")
    ] + [etat.get("conclusion", "")]).lower()
    dit_on, dit_off = "risk on" in texte, "risk off" in texte
    if biais_attendu == "risk_on" and dit_off and not dit_on:
        return True
    if biais_attendu == "risk_off" and dit_on and not dit_off:
        return True
    return False


def synthese_etat_du_monde(llm: FournisseurLLM, donnees: dict, catalogue: list[dict],
                           systeme: str | None = None,
                           devises_finales: list[dict] | None = None,
                           biais_macro_global: str | None = None) -> dict | None:
    """« État du monde » quotidien : les trois rubriques + un briefing
    d'analyste (indicateurs ✅/❌ avec réel/prévision/précédent écrits dans le
    texte, actualité en puces, conclusion narrative) — construit depuis TOUTES
    les sources news (RSS + sites scrapés) et le calendrier, AVANT toute
    lecture par devise. Le prompt système transmis inclut la base de
    connaissances, donc le modèle de briefing d'exemples_annotes.md.

    devises_finales (déjà analysées) est transmis pour que les rubriques
    politique_monetaire_budgetaire/geopolitique restent CROSS-DEVISES et
    n'écrasent pas le détail déjà produit par devise dans
    contexte_geopolitique — enrichissement sans duplication.

    biais_macro_global (calculé en Python, core/scoring.py) est transmis
    comme donnée de vérité au LLM : c'est le champ structuré qui fait foi
    dans tout le reste du rapport, le texte narratif ne doit jamais le
    contredire. Un désaccord détecté déclenche un nouvel essai corrigé ; s'il
    persiste, le rapport part quand même (transparence plutôt que blocage,
    comme le reste du pipeline) mais avec une anomalie de contrôle qualité
    visible plutôt qu'une contradiction silencieuse."""
    deja_couvert = [
        {"devise": d["devise"], "banque_centrale_pourquoi":
            (d.get("contexte_geopolitique") or {}).get("banque_centrale_pourquoi", {}).get("texte", ""),
         "evenements": [e["texte"] for e in (d.get("contexte_geopolitique") or {}).get("evenements", [])]}
        for d in (devises_finales or []) if d.get("contexte_geopolitique")
    ]
    contexte = {
        "news_rss": donnees["news"],
        "sites_news_geopolitique": donnees["sites_scrapes"],
        "calendrier_impact_eleve": [
            e for e in donnees["calendrier"]
            if str(e.get("impact", "")).lower() in ("high", "holiday")
            and str(e.get("date", "")) >= (date.today() - timedelta(days=1)).isoformat()
        ][:25],
        "macro_us": donnees["macro"],
        "deja_couvert_par_devise": deja_couvert,
        "catalogue_sources": catalogue,
    }
    ids_valides = ", ".join(s["id"] for s in catalogue)
    libelle_biais = LIBELLES_BIAIS_TEXTE.get(biais_macro_global, biais_macro_global or "non calculé")
    prompt = (
        f"Le biais macro global de ce rapport est **{libelle_biais}** — calculé par "
        "programme à partir des scores de confluence des 9 devises, NON négociable et "
        "déjà publié tel quel ailleurs dans le rapport. Ta conclusion et tes rubriques "
        "DOIVENT rester cohérentes avec ce biais : n'affirme jamais le biais opposé "
        f"(si le biais calculé est {libelle_biais}, n'écris jamais le terme opposé "
        "dans ton texte). Tu peux nuancer (ex. 'Risk On fragile', 'Risk Off qui se "
        "dissipe') mais jamais le contredire frontalement.\n\n"
        "Rédige l'« état du monde » du jour : un résumé global AVANT toute analyse "
        "par devise. D'abord trois rubriques : situation économique générale ; "
        "décisions de politique monétaire ou budgétaire notables ; contexte "
        "géopolitique. IMPORTANT — deja_couvert_par_devise liste ce qui est DÉJÀ "
        "détaillé devise par devise (banque centrale + événements spécifiques, "
        "affiché ailleurs dans le rapport) : ne le répète pas ici. Les rubriques "
        "politique_monetaire_budgetaire et geopolitique restent CROSS-DEVISES et "
        "THÉMATIQUES (tendances communes à plusieurs devises, contexte général) — "
        "renvoie au détail par devise plutôt que de le reformuler.\n"
        "Puis le BRIEFING D'ANALYSTE, en suivant le modèle « briefing "
        "quotidien » de la base de connaissances (exemples annotés) pour le ton et "
        "la structure :\n"
        "- indicateurs_du_jour : les publications d'aujourd'hui/hier dont la "
        "prévision est connue. Chaque ligne écrit EXPLICITEMENT le chiffre réel, la "
        "prévision ET le précédent dans le texte (jamais seulement un renvoi au "
        "tableau). Symbole : ✅ meilleur qu'attendu, ❌ moins bon qu'attendu, "
        "➖ conforme. Pas de publication exploitable = liste vide.\n"
        "- actualite : les titres RÉELS des news fournies (RSS + sites), une puce "
        "par titre avec son contexte en une phrase — ne jamais inventer un titre.\n"
        "- conclusion : 3 à 5 phrases d'analyste professionnel qui relient macro, "
        "marché du travail, inflation, banques centrales et risques géopolitiques.\n"
        "Uniquement à partir des données fournies — si une rubrique est creuse "
        "aujourd'hui, dis-le en une phrase plutôt que de broder. Style note de "
        "desk : phrases courtes, donnée d'abord, zéro remplissage. Français.\n"
        f"Réponds STRICTEMENT selon ce schéma JSON :\n{SCHEMA_ETAT_DU_MONDE}\n"
        f"SEULS ces source_id existent : [{ids_valides}] — n'en invente aucun.\n\n"
        "DONNÉES (JSON) :\n" + json.dumps(contexte, ensure_ascii=False, default=str)
    )
    prompt_courant = prompt
    for tentative in range(1, TENTATIVES_COHERENCE_BIAIS + 1):
        try:
            brut = extraire_json(llm.appeler_llm(prompt_courant, systeme=systeme))
            etat = {}
            for cle in ("situation_economique", "politique_monetaire_budgetaire", "geopolitique"):
                rubrique = brut.get(cle) or {}
                etat[cle] = {
                    "texte": str(rubrique.get("texte", ""))[:900],
                    "source_ids": [str(i) for i in rubrique.get("source_ids", [])][:8],
                }
            etat["indicateurs_du_jour"] = [
                {"symbole": item.get("symbole") if item.get("symbole") in SYMBOLES_BRIEFING else "➖",
                 "texte": str(item.get("texte", ""))[:300],
                 "source_id": item.get("source_id")}
                for item in (brut.get("indicateurs_du_jour") or [])[:10]
                if isinstance(item, dict) and item.get("texte")
            ]
            etat["actualite"] = [
                {"texte": str(item.get("texte", ""))[:300], "source_id": item.get("source_id")}
                for item in (brut.get("actualite") or [])[:8]
                if isinstance(item, dict) and item.get("texte")
            ]
            etat["conclusion"] = str(brut.get("conclusion", ""))[:1500]
        except Exception as exc:  # noqa: BLE001
            log.warning("État du monde indisponible : %s", exc)
            return None

        if not biais_macro_global or not _detecter_incoherence_biais(etat, biais_macro_global):
            etat["incoherence_biais_detectee"] = False
            return etat

        log.warning("État du monde : conclusion/rubrique contredit le biais calculé (%s) — "
                   "essai %d/%d", libelle_biais, tentative, TENTATIVES_COHERENCE_BIAIS)
        prompt_courant = prompt + (
            f"\n\nCORRECTION REQUISE : ta réponse précédente contredisait le biais "
            f"{libelle_biais} calculé par programme (elle employait le terme opposé). "
            f"Réécris en restant STRICTEMENT cohérente avec {libelle_biais}, sans "
            "jamais utiliser le terme opposé nulle part dans le texte.")

    # Persistant après relance : publié quand même (transparence plutôt que
    # blocage, comme le reste du pipeline) mais signalé — jamais silencieux.
    etat["incoherence_biais_detectee"] = True
    log.warning("État du monde : incohérence biais/conclusion persistante après %d essais — "
               "signalée en contrôle qualité, rapport publié quand même",
               TENTATIVES_COHERENCE_BIAIS)
    return etat


def commenter_synthese_globale(llm: FournisseurLLM, classement: list[dict],
                               biais: str, memoire: list[dict]) -> str:
    prompt = (
        "En UNE phrase style note de desk (donnée d'abord, pas de remplissage), "
        "commente ce classement de devises et ce biais macro global. "
        f"Biais : {biais}. Classement : {json.dumps(classement, ensure_ascii=False)}. "
        f"Contexte des jours précédents : {json.dumps(memoire[:2], ensure_ascii=False)}. "
        'Réponds en JSON : {"commentaire": "..."}'
    )
    try:
        return str(extraire_json(llm.appeler_llm(prompt)).get("commentaire", ""))[:400]
    except Exception as exc:  # noqa: BLE001
        log.warning("Commentaire global indisponible : %s", exc)
        libelle = {"risk_on": "Risk On", "risk_off": "Risk Off", "neutre": "neutre"}[biais]
        tete = classement[0]["devise"] if classement else "?"
        return f"Biais {libelle} ; {tete} en tête du classement de confluence."


def commenter_analyse_weekly(llm: FournisseurLLM, devise: str, metriques: dict) -> str:
    """Formule le commentaire de cohérence hebdo — les métriques (trajectoire,
    écart-type, flip-flops) sont calculées en Python, jamais par le LLM."""
    prompt = (
        f"En 2-3 phrases style note de desk, commente la COHÉRENCE du biais {devise} "
        "sur la semaine écoulée à partir de ces métriques calculées par programme "
        "(trajectoire du score lundi→vendredi, stabilité, indicateurs ayant changé "
        "de camp). Ne modifie aucun chiffre, ne prédis rien : juge seulement si le "
        f"biais a été stable ou erratique et pourquoi : {json.dumps(metriques, ensure_ascii=False)}. "
        'Réponds en JSON : {"commentaire": "..."}'
    )
    try:
        return str(extraire_json(llm.appeler_llm(prompt)).get("commentaire", ""))[:500]
    except Exception as exc:  # noqa: BLE001
        log.warning("Commentaire weekly %s indisponible : %s", devise, exc)
        return (f"Score {metriques.get('score_debut')} → {metriques.get('score_fin')} "
                f"sur {metriques.get('nb_jours')} jour(s) ; cohérence directionnelle : "
                f"{metriques.get('coherence_directionnelle_pct')} %.")


def commenter_auto_evaluation(llm: FournisseurLLM, evaluation: dict) -> str:
    prompt = (
        "En 2 phrases max, style note de desk, commente honnêtement cette "
        "auto-évaluation (y compris si elle est mauvaise). Les chiffres sont "
        f"calculés par programme, ne les modifie pas : {json.dumps(evaluation, ensure_ascii=False)}. "
        'Réponds en JSON : {"commentaire": "..."}'
    )
    try:
        return str(extraire_json(llm.appeler_llm(prompt)).get("commentaire", ""))[:500]
    except Exception as exc:  # noqa: BLE001
        log.warning("Commentaire auto-évaluation indisponible : %s", exc)
        return (f"Taux de réussite : {evaluation.get('taux_reussite_biais_pct')} % ; "
                f"corrélation de classement : {evaluation.get('correlation_classement_spearman')}.")


# ------------------------------------------------------------------ pipeline
def analyser(config: dict, llm: FournisseurLLM, technique: dict, macro: dict,
             news: dict, calendrier: dict, dossier_rapports: str | Path,
             type_rapport: str = "quotidien",
             overrides_du_jour: dict | None = None,
             rapport_existant: dict | None = None) -> dict:
    """rapport_existant (mode --completer) : rapport déjà sauvegardé plus tôt
    dans la journée. Toute devise qui y a déjà un score_confluence est
    RÉUTILISÉE VERBATIM — jamais rappelée au LLM, jamais retraitée. Seules les
    devises encore en échec (et l'état du monde s'il avait échoué) sont
    retentées. overrides_du_jour (data/overrides/, repli manuel) prime
    systématiquement sur toute donnée automatique, pour n'importe quel
    indicateur."""
    systeme = construire_prompt_systeme()
    # UNE seule fenêtre (jours), partagée par la mémoire ET le calendrier
    # injectés au LLM — jamais plus, indépendamment de l'archive complète
    # (data/rapports/, Notion) qui n'est ni filtrée ni limitée par cette
    # valeur. Incident du 2026-08-29 : deux fenêtres divergentes (mémoire
    # "7 fichiers" ≠ 7 jours réels ; calendrier retenu 10 jours) faisaient
    # fuiter des données bien plus vieilles que 7 jours dans le prompt.
    fenetre_jours_llm = int(config.get("memoire", {}).get("fenetre_jours", 7))
    donnees, catalogue = assembler_contexte(
        config, technique, macro, news, calendrier, fenetre_jours_llm,
        catalogue_existant=(rapport_existant or {}).get("sources_citees"))
    memoire = charger_memoire(dossier_rapports, fenetre_jours_llm)
    overrides_du_jour = overrides_du_jour or {}

    devises_deja_ok = {
        d["devise"]: d for d in (rapport_existant or {}).get("devises", [])
        if d.get("score_confluence") is not None
    }

    carry = macro.get("carry", {})
    taux = macro.get("taux_directeurs", {})
    ids_catalogue = {s["id"] for s in catalogue}
    devises_finales = []
    for devise in config["devises"]:
        if devise in devises_deja_ok:
            # --completer : déjà réussie plus tôt aujourd'hui — jamais retraitée.
            devises_finales.append(devises_deja_ok[devise])
            continue
        overrides_devise = overrides_du_jour.get(devise)
        # Biais Risk On/Off structurel : dérivé du profil configuré, pas du LLM.
        biais = scoring.biais_structurel(config["devises"][devise].get("profil_risque", "neutre"))
        try:
            brut = _analyser_devise(llm, systeme, config, devise, donnees, catalogue, memoire,
                                    overrides_devise)
        except RuntimeError as exc:
            entree = _devise_indisponible(devise, str(exc)[:150], biais)
            # Les données collectées ne dépendent pas du LLM : le tableau
            # d'indicateurs et le carry restent affichables même sans analyse.
            entree["indicateurs_tableau"] = _tableau_indicateurs(config, devise, donnees, overrides_devise)
            entree["carry"] = {
                "taux_directeur": taux.get(devise, {}).get("taux"),
                "differentiel_vs_mediane_g8": carry.get("differentiels", {}).get(devise),
                "commentaire": "Facteur structurel de flux (swap) — jamais un déclencheur seul.",
            }
            devises_finales.append(entree)
            continue
        score, detail = scoring.calculer_score(
            brut.get("detail_score"), scoring.ponderations_devise(config, devise))
        # Les sources du detail_score font foi côté Python : tout id absent du
        # catalogue (null ou inventé) est réaligné sur le mapping de la collecte.
        sources_indicateurs = donnees["_sources_indicateurs"].get(devise, {})
        for item in detail:
            if item["source_id"] not in ids_catalogue:
                item["source_id"] = sources_indicateurs.get(item["indicateur"])
        devises_finales.append({
            "devise": devise,
            "risk_on_off": biais,
            "score_confluence": score,
            "detail_score": detail,
            "biais_banque_centrale": brut.get("biais_banque_centrale", "data_dependent"),
            "tendance_fond": brut.get("tendance_fond")
                or donnees["technique"].get(devise, {}).get("tendance_fond"),
            "carry": {
                "taux_directeur": taux.get(devise, {}).get("taux"),
                "differentiel_vs_mediane_g8": carry.get("differentiels", {}).get(devise),
                "commentaire": "Facteur structurel de flux (swap) — jamais un déclencheur seul.",
            },
            "opportunites": brut.get("opportunites", [])[:5],
            "menaces": brut.get("menaces", [])[:5],
            "synthese_une_phrase": str(brut.get("synthese_une_phrase", ""))[:400],
            "indicateurs_tableau": _tableau_indicateurs(config, devise, donnees, overrides_devise),
            "contexte_geopolitique": _normaliser_contexte_geopolitique(brut),
        })

    classement = scoring.classer(devises_finales)
    biais = scoring.biais_macro_global(devises_finales, config.get("biais_global", {}))
    # État du monde déjà réussi plus tôt aujourd'hui (--completer) : réutilisé
    # verbatim, jamais rappelé au LLM. Sinon (première fois, ou échec précédent
    # à retenter) : généré maintenant, APRÈS la boucle devise, pour voir le
    # détail par devise ET le biais calculé (ne doit jamais le contredire).
    etat_existant = (rapport_existant or {}).get("synthese_globale", {}).get("etat_du_monde")
    etat_du_monde = etat_existant or synthese_etat_du_monde(
        llm, donnees, catalogue, systeme, devises_finales, biais)

    non_rafraichies = list(calendrier.get("non_rafraichies", []))
    for source, erreurs in (("Twelve Data", technique.get("erreurs", [])),
                            ("FRED", macro.get("erreurs", [])),
                            ("RSS", news.get("erreurs", []))):
        for erreur in erreurs:
            non_rafraichies.append({"source": source, "derniere_donnee_du": None,
                                    "raison": str(erreur)[:200]})

    return {
        "meta": {
            "date_rapport": date.today().isoformat(),
            "type_rapport": type_rapport,
            "version_schema": "1.0",
            "modele_llm": config["llm"]["modele"],
            "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "synthese_globale": {
            "biais_macro_global": biais,
            "commentaire": commenter_synthese_globale(llm, classement, biais, memoire),
            "etat_du_monde": etat_du_monde,
            "classement_devises": classement,
            "devises_indisponibles": [d["devise"] for d in devises_finales
                                      if d.get("score_confluence") is None],
        },
        "devises": devises_finales,
        "sources_citees": catalogue,
        "donnees_non_rafraichies": non_rafraichies,
        "graphiques": technique.get("graphiques", {}),
        "graphiques_marche": macro.get("graphiques_marche", {}),
        "prix_cloture": technique.get("prix_cloture", {}),
    }
