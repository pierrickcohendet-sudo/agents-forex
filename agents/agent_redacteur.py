"""Agent rédacteur : publie le rapport dans une BASE DE DONNÉES Notion.

- Une entrée par jour, propriétés Date / Semaine ISO / Type / Biais global /
  Relecture -> la vue Calendrier native de Notion s'applique (à créer une fois
  à la main : « + Add view -> Calendar » sur la propriété Date).
- La base est créée automatiquement au premier run sous la page parente, et son
  ID est écrit dans config.yaml (persisté par le commit du workflow).
- UPSERT par date : re-lancer le pipeline le même jour met à jour l'entrée
  existante au lieu d'en créer une deuxième.
- Zone « 📝 Notes personnelles » : créée vide UNE seule fois en bas de chaque
  entrée ; les régénérations ne touchent que les blocs entre l'ancre du haut et
  ce heading — tout ce que l'utilisateur écrit dedans est préservé.

Écrit pour notion-client >= 3 (API Notion 2025-09-03) : une base contient des
« data sources » ; les requêtes passent par client.data_sources.query, la
création de base par initial_data_source, et le parent d'une page est le
data_source_id. Un garde-fou au démarrage (_garantir_proprietes) ajoute les
propriétés manquantes au schéma — il répare aussi une base créée par une
ancienne version du pipeline.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path

from notion_client import Client

from core import hebdo
from core import notion_blocks as nb

log = logging.getLogger(__name__)

LIBELLE_BIAIS_GLOBAL = {"risk_on": "Risk On", "risk_off": "Risk Off", "neutre": "Neutre"}
EMOJI_BIAIS = {"on": "🟢", "off": "🔴", "neutre": "🟡"}
ANCRE_TEXTE = "⚙️ Zone générée automatiquement — vos notes en bas de page sont préservées à chaque run."
NOTES_TITRE = "📝 Notes personnelles"
RUBRIQUES_ETAT = (
    ("situation_economique", "Économie"),
    ("politique_monetaire_budgetaire", "Politique monétaire & budgétaire"),
    ("geopolitique", "Géopolitique"),
)


# ------------------------------------------------------------ base de données
def _extraire_page_id(brut: str) -> str | None:
    """Accepte un ID nu (32 hex), un UUID avec tirets ou une URL Notion complète."""
    correspondances = re.findall(r"[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                                 brut.lower())
    return correspondances[-1].replace("-", "") if correspondances else None


def _persister_database_id(chemin_config: str | Path | None, database_id: str) -> None:
    """Écrit l'ID de la base dans config.yaml (ligne `database_id: ""`).
    Committé ensuite par le workflow : GitHub Actions étant sans état, c'est le
    dépôt qui porte cette persistance."""
    if not chemin_config:
        log.warning("Chemin config inconnu : reporter database_id: \"%s\" dans config.yaml", database_id)
        return
    chemin = Path(chemin_config)
    texte = chemin.read_text(encoding="utf-8")
    nouveau, remplacements = re.subn(r'database_id:\s*""', f'database_id: "{database_id}"', texte, count=1)
    if remplacements:
        chemin.write_text(nouveau, encoding="utf-8")
        log.info("database_id écrit dans %s", chemin)
    else:
        log.warning("Ligne `database_id: \"\"` introuvable dans config.yaml — "
                    "ajouter manuellement : database_id: \"%s\"", database_id)


def _chercher_base_existante(client: Client, parent_id: str) -> str | None:
    """Cherche une base « Rapports FX » déjà présente sous la page parente.
    Rend la création idempotente : si un run précédent a créé la base mais que
    config.yaml n'a pas été mis à jour/committé (plantage en cours de route,
    relance avant le push GitHub Actions), on la RÉUTILISE au lieu d'en créer
    une deuxième."""
    curseur = None
    while True:
        page = client.blocks.children.list(parent_id, start_cursor=curseur, page_size=100) \
            if curseur else client.blocks.children.list(parent_id, page_size=100)
        for bloc in page["results"]:
            if (bloc.get("type") == "child_database"
                    and bloc.get("child_database", {}).get("title") == "Rapports FX"):
                return bloc["id"].replace("-", "")
        if not page.get("has_more"):
            return None
        curseur = page["next_cursor"]


def _obtenir_database(client: Client, cfg_notion: dict,
                      chemin_config: str | Path | None) -> str | None:
    # 1. Priorité absolue : l'ID déjà renseigné dans config.yaml.
    database_id = _extraire_page_id(str(cfg_notion.get("database_id", "")))
    if database_id:
        return database_id
    parent = _extraire_page_id(str(cfg_notion.get("page_parent_id", "")))
    if not parent:
        log.warning("Ni database_id ni page_parent_id exploitable : publication Notion sautée")
        return None
    # 2. Filet anti-doublon : une base « Rapports FX » existe-t-elle déjà sous
    #    la page parente ? (config.yaml vide ne prouve pas qu'elle n'existe pas)
    database_id = _chercher_base_existante(client, parent)
    if database_id:
        log.info("Base « Rapports FX » existante retrouvée sous la page parente (%s) : "
                 "réutilisée, aucune création", database_id)
        _persister_database_id(chemin_config, database_id)
        return database_id
    # 3. Sinon seulement : création (API 2025-09-03 : le schéma passe par
    #    initial_data_source — un `properties` racine serait ignoré en silence).
    base = client.databases.create(
        parent={"type": "page_id", "page_id": parent},
        title=[{"type": "text", "text": {"content": "Rapports FX"}}],
        icon={"type": "emoji", "emoji": "📊"},
        initial_data_source={"properties": {"Nom": {"title": {}}, **PROPRIETES_SCHEMA}},
    )
    database_id = base["id"].replace("-", "")
    log.info("Base Notion « Rapports FX » créée (%s). Vue Calendrier à créer à la "
             "main : + Add view -> Calendar sur la propriété Date.", database_id)
    _persister_database_id(chemin_config, database_id)
    return database_id


PROPRIETES_SCHEMA = {
    "Date": {"date": {}},
    "Semaine": {"rich_text": {}},
    "Type": {"select": {"options": [
        {"name": "quotidien", "color": "blue"},
        {"name": "hebdomadaire", "color": "purple"},
        {"name": "mensuel", "color": "pink"}]}},
    "Biais global": {"select": {"options": [
        {"name": "Risk On", "color": "green"},
        {"name": "Risk Off", "color": "red"},
        {"name": "Neutre", "color": "yellow"}]}},
    "Relecture": {"select": {"options": [
        {"name": "ok", "color": "green"},
        {"name": "a_revoir", "color": "orange"},
        {"name": "non_evalue", "color": "gray"}]}},
}


def _garantir_proprietes(client: Client, data_source_id: str) -> None:
    """Ajoute au schéma les propriétés manquantes et renomme la propriété titre
    en « Nom ». Auto-réparation : couvre notamment une base créée par une
    version du pipeline dont le `properties` racine avait été ignoré par l'API."""
    source = client.data_sources.retrieve(data_source_id)
    existantes = source.get("properties", {})
    correctifs = {nom: schema for nom, schema in PROPRIETES_SCHEMA.items()
                  if nom not in existantes}
    titre = next((nom for nom, p in existantes.items() if p.get("type") == "title"), None)
    if titre and titre != "Nom":
        correctifs[titre] = {"name": "Nom"}
    if correctifs:
        client.data_sources.update(data_source_id, properties=correctifs)
        log.info("Schéma de la base réparé/complété : %s", ", ".join(sorted(correctifs)))


def _obtenir_data_source(client: Client, database_id: str) -> str:
    """Une base (API 2025-09-03) contient une ou plusieurs data sources ; tout
    (requêtes, parent des pages) passe par l'ID de la première."""
    base = client.databases.retrieve(database_id)
    sources = base.get("data_sources", [])
    if not sources:
        raise RuntimeError(f"Base Notion {database_id} sans data source — inattendu")
    data_source_id = sources[0]["id"]
    _garantir_proprietes(client, data_source_id)
    return data_source_id


def _trouver_entree(client: Client, data_source_id: str, date_rapport: str) -> dict | None:
    resultat = client.data_sources.query(
        data_source_id,
        filter={"property": "Date", "date": {"equals": date_rapport}},
        page_size=1,
    )
    return resultat["results"][0] if resultat.get("results") else None


def _proprietes(rapport: dict) -> dict:
    meta = rapport["meta"]
    biais = rapport["synthese_globale"]["biais_macro_global"]
    # Jamais "ok" par défaut : si la clé "critique" est absente (ne devrait pas
    # arriver, critiquer() la pose toujours), c'est que la relecture n'a pas
    # eu lieu — "non_evalue", pas "ok" par défaut.
    validation = rapport.get("critique", {}).get("validation", "non_evalue")
    jour = date.fromisoformat(meta["date_rapport"])
    return {
        "Nom": {"title": [{"type": "text", "text": {
            "content": f"FX — {meta['date_rapport']} ({meta['type_rapport']})"}}]},
        "Date": {"date": {"start": meta["date_rapport"]}},
        "Semaine": {"rich_text": [{"type": "text", "text": {"content": hebdo.semaine_iso(jour)}}]},
        "Type": {"select": {"name": meta["type_rapport"]}},
        "Biais global": {"select": {"name": LIBELLE_BIAIS_GLOBAL[biais]}},
        "Relecture": {"select": {"name": validation}},
    }


# --------------------------------------------------------------- blocs corps
def _fragments_titre_toggle(devise: dict, drapeau: str) -> list[dict]:
    biais = devise["risk_on_off"]
    if devise.get("score_confluence") is None:
        return [
            nb.rt(f"{drapeau} {devise['devise']}  ", gras=True),
            nb.rt("⏸ analyse indisponible aujourd'hui", couleur="gray", italique=True),
        ]
    return [
        nb.rt(f"{drapeau} {devise['devise']}  ", gras=True),
        nb.rt(f"{EMOJI_BIAIS[biais]} {nb.LIBELLES_BIAIS[biais]}", gras=True,
              couleur=nb.COULEURS_TEXTE[biais]),
        nb.rt(f"  ·  confluence {devise['score_confluence']} %", couleur="gray"),
    ]


def _source_lisible(source_id: str | None, catalogue: dict[str, dict]) -> str:
    if not source_id or source_id not in catalogue:
        return "non sourcée"
    entree = catalogue[source_id]
    return f"{entree['source']} · {str(entree.get('detail', ''))[:60]} · {entree.get('date') or 's.d.'}"


def _puces_sourcees(elements: list[dict], catalogue: dict[str, dict]) -> list[dict]:
    puces = []
    for item in elements:
        fragments = [nb.rt(item.get("texte", ""))]
        if item.get("non_sourcee"):
            fragments.append(nb.rt("  [⚠ affirmation non sourcée]", couleur="orange", italique=True))
        else:
            fragments.append(nb.rt(f"  — {_source_lisible(item.get('source_id'), catalogue)}",
                                   couleur="gray", italique=True))
        puces.append(nb.puce(fragments))
    return puces or [nb.puce([nb.rt("Rien à signaler aujourd'hui.", couleur="gray")])]


def _cellule_date(ligne: dict) -> list[dict]:
    """Date d'origine + badge J-n en orange (aligné sur le rendu web) ; tiret
    si aucune donnée — la mention « aucune publication < 7 j » vit dans la
    colonne Valeur, pas ici."""
    if not ligne.get("date"):
        return [nb.rt("—")]
    fragments = [nb.rt(ligne["date"])]
    anciennete = ligne.get("anciennete_jours")
    if anciennete:
        fragments.append(nb.rt(f" (J-{anciennete})", couleur="orange"))
    return fragments


def _blocs_synthese(rapport: dict) -> list[dict]:
    synthese = rapport["synthese_globale"]
    critique = rapport.get("critique", {})
    controle = rapport.get("controle_qualite", {})
    blocs = []

    if critique.get("validation") == "a_revoir":
        points = critique.get("incoherences", []) + critique.get("affirmations_non_sourcees", [])
        texte = " · ".join(points[:4]) or "voir détail dans le JSON du rapport"
        blocs.append(nb.callout(
            [nb.rt("⚠️ Point de vigilance identifié par la relecture : ", gras=True), nb.rt(texte)],
            "⚠️", "orange_background"))
    elif critique.get("validation") == "non_evalue":
        # Distinct de "a_revoir" : ici on ne sait PAS si le rapport est propre,
        # la relecture elle-même n'a pas pu avoir lieu — jamais affiché "ok".
        blocs.append(nb.callout(
            [nb.rt("🔍 Relecture non effectuée aujourd'hui — ", gras=True),
             nb.rt(str(critique.get("note", "cause inconnue"))),
             nb.rt("  Ce rapport n'a PAS été validé par l'agent critique.", couleur="gray")],
            "🔍", "gray_background"))

    if controle and not controle.get("conforme", True):
        blocs.append(nb.callout(
            [nb.rt(f"Contrôle qualité : {controle.get('nb_anomalies', '?')} anomalie(s) — ", gras=True),
             nb.rt(" · ".join(controle.get("anomalies", [])[:5]))],
            "🧪", "orange_background"))

    if rapport.get("donnees_non_rafraichies"):
        details = " · ".join(
            f"{d['source']} ({str(d.get('raison', 'non rafraîchi'))[:80]})"
            for d in rapport["donnees_non_rafraichies"][:6]
        )
        blocs.append(nb.callout(
            [nb.rt("Données non rafraîchies aujourd'hui : ", gras=True),
             nb.rt(details, couleur="gray")],
            "🕐", "gray_background"))

    biais = synthese["biais_macro_global"]
    couleur = {"risk_on": "green_background", "risk_off": "red_background",
               "neutre": "yellow_background"}[biais]
    blocs.append(nb.titre(1, "Synthèse globale"))
    blocs.append(nb.callout(
        [nb.rt(f"Biais macro : {LIBELLE_BIAIS_GLOBAL[biais]} — ", gras=True),
         nb.rt(synthese.get("commentaire", ""))],
        "🧭", couleur))

    etat = synthese.get("etat_du_monde") or {}
    if any((etat.get(cle) or {}).get("texte") for cle, _ in RUBRIQUES_ETAT) \
            or etat.get("indicateurs_du_jour") or etat.get("conclusion"):
        blocs.append(nb.titre(2, "🌍 État du monde"))
        for cle, libelle in RUBRIQUES_ETAT:
            rubrique = etat.get(cle) or {}
            if not rubrique.get("texte"):
                continue
            fragments = [nb.rt(f"{libelle} — ", gras=True), nb.rt(rubrique["texte"])]
            if rubrique.get("non_source"):
                fragments.append(nb.rt("  [non sourcé]", couleur="orange", italique=True))
            elif rubrique.get("source_ids"):
                fragments.append(nb.rt(f"  ({', '.join(rubrique['source_ids'])})",
                                       couleur="gray", italique=True))
            blocs.append(nb.paragraphe(fragments))

        # Briefing d'analyste : indicateurs ✅/❌ (réel vs prévision vs précédent
        # écrits dans le texte), actualité en puces, conclusion narrative.
        def _puce_briefing(item: dict, prefixe: str = "") -> dict:
            fragments = ([nb.rt(prefixe, gras=True)] if prefixe else []) + [nb.rt(item.get("texte", ""))]
            if item.get("non_sourcee"):
                fragments.append(nb.rt("  [non sourcé]", couleur="orange", italique=True))
            elif item.get("source_id"):
                fragments.append(nb.rt(f"  ({item['source_id']})", couleur="gray", italique=True))
            return nb.puce(fragments)

        if etat.get("indicateurs_du_jour"):
            blocs.append(nb.titre(3, "Indicateurs du jour"))
            for item in etat["indicateurs_du_jour"]:
                blocs.append(_puce_briefing(item, f"{item.get('symbole', '➖')} "))
        if etat.get("actualite"):
            blocs.append(nb.titre(3, "Actualité"))
            for item in etat["actualite"]:
                blocs.append(_puce_briefing(item))
        if etat.get("conclusion"):
            blocs.append(nb.titre(3, "Conclusion"))
            blocs.append(nb.callout([nb.rt(etat["conclusion"])], "🖋", "gray_background"))

    blocs.append(nb.tableau(
        ["Rang", "Devise", "Biais", "Confluence"],
        [[c["rang"], c["devise"], nb.LIBELLES_BIAIS[c["risk_on_off"]],
          f"{c['score_confluence']} %"] for c in synthese["classement_devises"]],
    ))
    if synthese.get("devises_indisponibles"):
        blocs.append(nb.paragraphe_gris(
            "⏸ Analyses indisponibles aujourd'hui (exclues du classement) : "
            + ", ".join(synthese["devises_indisponibles"])))

    evaluation = rapport.get("auto_evaluation")
    if evaluation:
        blocs.append(nb.titre(2, "Auto-évaluation de la semaine précédente"))
        blocs.append(nb.callout(
            [nb.rt(f"Taux de réussite du biais : {evaluation['taux_reussite_biais_pct']} % · "
                   f"corrélation de classement (Spearman) : "
                   f"{evaluation.get('correlation_classement_spearman', 'n/a')}. ", gras=True),
             nb.rt(evaluation.get("commentaire_llm") or "")],
            "📏", "blue_background"))
        blocs.append(nb.tableau(
            ["Devise", "Prévu", "Variation réelle", "Correct"],
            [[e["devise"], e["prevu"], f"{e['variation_reelle_pct']} %",
              "✔" if e["correct"] else "✘"] for e in evaluation["par_devise"]],
        ))

    # L'analyse weekly est rendue PAR devise (dans chaque toggle), comme sur
    # le dashboard web — pas de section globale dupliquée.
    blocs.append(nb.titre(1, "Détail par devise"))
    return blocs


def _blocs_devise(devise: dict, rapport: dict,
                  catalogue: dict[str, dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """(blocs principaux, puces opportunités, puces menaces)."""
    biais = devise["risk_on_off"]
    code = devise["devise"]
    graphique = rapport.get("graphiques", {}).get(code)

    blocs = []
    if devise.get("score_confluence") is None:
        blocs.append(nb.callout(
            [nb.rt("Analyse indisponible aujourd'hui — ", gras=True),
             nb.rt(str(devise.get("raison_indisponibilite", ""))[:200]),
             nb.rt("  Les données collectées ci-dessous restent valables ; la devise "
                   "est exclue du classement du jour.", couleur="gray")],
            "⏸", "gray_background"))
    else:
        blocs.append(nb.image_externe(
            nb.url_jauge_confluence(devise["score_confluence"], biais),
            f"Score de confluence : {devise['score_confluence']}/100",
        ))
        blocs.append(nb.callout(
            [nb.rt(devise.get("synthese_une_phrase", ""), gras=True)],
            EMOJI_BIAIS[biais], nb.COULEURS_CALLOUT[biais]))

    tendance = devise.get("tendance_fond") or {}
    carry = devise.get("carry") or {}
    blocs.append(nb.paragraphe([
        nb.rt("Tendance de fond (weekly, Dow) : ", gras=True),
        nb.rt(f"{tendance.get('sens', '?')} — {tendance.get('commentaire', '')}  ·  "),
        nb.rt("Banque centrale : ", gras=True),
        nb.rt(f"{devise.get('biais_banque_centrale', '?')}  ·  "),
        nb.rt("Taux directeur : ", gras=True),
        nb.rt(f"{carry.get('taux_directeur', '?')} % "
              f"(diff. vs médiane G8 : {carry.get('differentiel_vs_mediane_g8', '?')})"),
    ]))

    # Contexte géopolitique & décisions — distinct de l'état du monde global
    # (thématique/cross-devises) et du tableau d'indicateurs (chiffré) :
    # posture de banque centrale expliquée + événements datés propres à la devise.
    contexte_geo = devise.get("contexte_geopolitique") or {}
    pourquoi = contexte_geo.get("banque_centrale_pourquoi") or {}
    evenements_geo = contexte_geo.get("evenements") or []
    if pourquoi.get("texte") or evenements_geo:
        blocs.append(nb.titre(3, "🌐 Contexte géopolitique & décisions"))
        if pourquoi.get("texte"):
            fragments = [nb.rt(pourquoi["texte"])]
            if pourquoi.get("source_id") and pourquoi["source_id"] in catalogue:
                fragments.append(nb.rt(f"  ({pourquoi['source_id']})", couleur="gray", italique=True))
            blocs.append(nb.paragraphe(fragments))
        if evenements_geo:
            blocs.append(nb.toggle([nb.rt("Événements de la semaine", couleur="gray")],
                                   _puces_sourcees(evenements_geo, catalogue)))

    if graphique:
        legende_prix = ("Sert aussi de référence DXY (baromètre Risk On/Off) — "
                        "voir la ligne « Indice USD » du tableau ci-dessous." if code == "USD" else "")
        blocs.append(nb.image_externe(
            nb.url_graphique_prix(graphique["dates"], graphique["clotures"],
                                  graphique["libelle"], biais), legende_prix))

    # Tableau : UNE ligne par indicateur configuré (complétude vérifiée par le
    # contrôle qualité), date d'origine toujours visible, J-n si donnée de repli.
    lignes = [[l.get("nom"),
               l.get("valeur") if l.get("valeur") not in (None, "") else (l.get("note") or "—"),
               l.get("prevision"), l.get("precedent"), l.get("source"),
               _cellule_date(l)] for l in devise.get("indicateurs_tableau", [])]
    blocs.append(nb.titre(3, "Indicateurs du jour"))
    if lignes:
        blocs.append(nb.tableau(["Indicateur", "Valeur", "Prévision", "Précédent",
                                 "Source", "Date"], lignes))
    else:
        blocs.append(nb.paragraphe_gris("Tableau d'indicateurs indisponible (voir contrôle qualité)."))

    # DXY et Pétrole : graphiques QuickChart adjacents au tableau (Notion ne
    # permet pas d'image DANS une cellule) — DXY réutilise l'indice USD
    # synthétique déjà calculé (aucune double collecte) ; Pétrole via FRED,
    # seule source réelle disponible sur le tier gratuit (Twelve Data réserve
    # les commodités aux plans payants, vérifié).
    indicateurs_presents = {l.get("indicateur") for l in devise.get("indicateurs_tableau", [])}
    if "dxy" in indicateurs_presents and code != "USD":
        usd_graph = rapport.get("graphiques", {}).get("USD")
        if usd_graph:
            blocs.append(nb.image_externe(
                nb.url_graphique_prix(usd_graph["dates"], usd_graph["clotures"],
                                      "DXY (indice USD synthétique)", "neutre"),
                "Indicateur visuel pour la ligne « Indice USD » ci-dessus — donnée partagée, "
                "identique pour toutes les devises."))
    if code == "CAD":
        marche = rapport.get("graphiques_marche") or {}
        wti, brent = marche.get("wti"), marche.get("brent")
        if wti or brent:
            url = nb.url_graphique_petrole(
                (wti or {}).get("dates", []), (wti or {}).get("valeurs", []),
                (brent or {}).get("dates", []), (brent or {}).get("valeurs", []))
            if url:
                blocs.append(nb.image_externe(
                    url, "Indicateur visuel pour la ligne « Pétrole WTI » ci-dessus (FRED)."))

    detail = [nb.puce([
        nb.rt(f"{d['indicateur']}  {'+1' if d['sens'] > 0 else d['sens']}  ×{d['poids']}", gras=True,
              couleur="green" if d["sens"] > 0 else "red" if d["sens"] < 0 else "gray"),
        nb.rt(f" — {d['justification']}", couleur="gray"),
    ]) for d in devise.get("detail_score", [])]
    if detail:
        blocs.append(nb.toggle([nb.rt("Détail du score de confluence", couleur="gray")], detail))

    # Analyse weekly PAR devise — même emplacement que sur le dashboard web.
    weekly = (rapport.get("analyse_weekly") or {}).get(code)
    if weekly:
        metriques = weekly.get("metriques", {})
        blocs.append(nb.toggle(
            [nb.rt(f"📅 Analyse weekly ({weekly.get('semaine_iso', '')})", couleur="gray")],
            [nb.paragraphe([nb.rt(
                f"Score {metriques.get('score_debut')} → {metriques.get('score_fin')} sur "
                f"{metriques.get('nb_jours')} jour(s) · σ {metriques.get('ecart_type_score')} · "
                f"cohérence directionnelle {metriques.get('coherence_directionnelle_pct')} %")]),
             nb.paragraphe([nb.rt(weekly.get("commentaire", ""), couleur="gray")])]))

    opportunites = _puces_sourcees(devise.get("opportunites", []), catalogue)
    menaces = _puces_sourcees(devise.get("menaces", []), catalogue)
    return blocs, opportunites, menaces


def _blocs_suggestions(critique: dict) -> list[dict]:
    suggestions = critique.get("suggestions_connaissances") or []
    if not suggestions:
        return []
    blocs = [
        nb.titre(2, "💡 Suggestions pour la base de connaissances"),
        nb.paragraphe_gris("Propositions du relecteur, à valider et écrire À LA MAIN "
                           "dans connaissances/ — jamais appliquées automatiquement."),
    ]
    for s in suggestions:
        blocs.append(nb.puce([
            nb.rt(f"[{s.get('fichier_cible', 'cas_particuliers.md')}] ", gras=True, couleur="blue"),
            nb.rt(f"{s.get('theme', '')} — {s.get('suggestion', '')}"),
        ]))
    return blocs


# ----------------------------------------------------- génération / upsert
def _lister_enfants(client: Client, bloc_id: str) -> list[dict]:
    enfants, curseur = [], None
    while True:
        page = client.blocks.children.list(bloc_id, start_cursor=curseur, page_size=100) \
            if curseur else client.blocks.children.list(bloc_id, page_size=100)
        enfants.extend(page["results"])
        if not page.get("has_more"):
            return enfants
        curseur = page["next_cursor"]


def _texte_bloc(bloc: dict) -> str:
    contenu = bloc.get(bloc.get("type"), {})
    riches = contenu.get("rich_text", [])
    return riches[0].get("plain_text") or riches[0].get("text", {}).get("content", "") if riches else ""


def _generer_contenu(client: Client, page_id: str, rapport: dict, config: dict,
                     apres_id: str | None = None) -> None:
    """Écrit la zone générée. Si apres_id est fourni, chaque lot est inséré à la
    suite (paramètre `after` de l'API) pour rester AVANT la zone de notes."""
    dernier = apres_id

    def poser(blocs: list[dict]) -> str | None:
        nonlocal dernier
        if not blocs:
            return None
        parametres = {"children": blocs}
        if dernier:
            parametres["after"] = dernier
        resultat = client.blocks.children.append(page_id, **parametres)
        dernier = resultat["results"][-1]["id"]
        return resultat["results"][0]["id"]

    catalogue = {s["id"]: s for s in rapport.get("sources_citees", [])}
    poser(_blocs_synthese(rapport))

    for devise in rapport["devises"]:
        drapeau = config["devises"].get(devise["devise"], {}).get("drapeau", "")
        poser([nb.toggle(_fragments_titre_toggle(devise, drapeau))])
        toggle_id = dernier
        blocs, opportunites, menaces = _blocs_devise(devise, rapport, catalogue)
        blocs.append(nb.toggle([nb.rt("🟢 Opportunités", gras=True)], opportunites))
        blocs.append(nb.toggle([nb.rt("🔴 Menaces", gras=True)], menaces))
        blocs.append(nb.paragraphe_gris(
            f"Sources : Twelve Data, FRED, ForexFactory, RSS, sites news · généré le "
            f"{rapport['meta']['genere_le']} · aide à la décision — aucun signal d'achat/vente."))
        try:
            client.blocks.children.append(toggle_id, children=blocs)
        except Exception as exc:  # noqa: BLE001
            # Un échec Notion (ex. contrainte API dépassée sur UN bloc) ne doit
            # coûter que cette devise — jamais couper la publication des
            # suivantes (c'est exactement ce qui a coupé le run du 2026-08-14 :
            # une image trop longue sur une devise a stoppé tout le reste).
            log.error("Contenu de %s en échec (toggle laissé avec ce message) : %s",
                     devise["devise"], exc)
            try:
                client.blocks.children.append(toggle_id, children=[nb.callout(
                    [nb.rt("⚠️ Rendu de cette devise en échec côté Notion — ", gras=True),
                     nb.rt(f"{type(exc).__name__}: {str(exc)[:200]}. "
                           "Le rapport complet reste disponible sur le dashboard web.",
                           couleur="gray")],
                    "⚠️", "orange_background")])
            except Exception:  # noqa: BLE001
                pass  # même le message de repli échoue : on continue quand même

    poser(_blocs_suggestions(rapport.get("critique", {})))


def _regenerer_corps(client: Client, page_id: str, rapport: dict, config: dict) -> None:
    """Re-run du même jour : remplace les blocs entre l'ancre et le heading
    « Notes personnelles ». Les notes de l'utilisateur ne sont JAMAIS touchées.

    Ordre STRICT, non négociable (incident du 2026-08-21 : une coupure réseau
    en cours de reconstruction avait laissé la page à moitié détruite, après
    que l'ancien contenu avait déjà été supprimé) :
      1. Construire le NOUVEAU contenu, posé à la suite de l'ancien (jamais à
         sa place) — l'ancien contenu reste visible et intact pendant ce temps.
      2. Seulement si l'étape 1 se termine SANS exception : supprimer l'ancien
         contenu.
    Si l'étape 1 échoue en cours de route, aucune suppression n'a lieu :
    l'ancien contenu (stale mais complet) reste en place, avec éventuellement
    un reliquat de nouveau contenu partiel à côté — jamais de page vidée. Le
    prochain run réussi nettoie tout (l'ancien ET le reliquat sont alors
    "l'ancien contenu" à supprimer une fois le run suivant confirmé)."""
    enfants = _lister_enfants(client, page_id)
    idx_ancre = next((i for i, b in enumerate(enfants)
                      if b.get("type") == "paragraph" and _texte_bloc(b).startswith("⚙️")), None)
    idx_notes = next((i for i, b in enumerate(enfants)
                      if b.get("type") == "heading_2" and _texte_bloc(b).startswith("📝")), None)

    if idx_ancre is None:
        log.warning("Ancre de zone générée introuvable : contenu ajouté en fin de page, notes intactes")
        client.blocks.children.append(page_id, children=[nb.paragraphe_gris(ANCRE_TEXTE)])
        _generer_contenu(client, page_id, rapport, config)
        return

    fin = idx_notes if idx_notes is not None else len(enfants)
    anciens_blocs = enfants[idx_ancre + 1: fin]
    point_insertion = anciens_blocs[-1]["id"] if anciens_blocs else enfants[idx_ancre]["id"]

    # 1. Nouveau contenu D'ABORD, à la suite de l'ancien — rien supprimé encore.
    #    Une exception ici (réseau, API) remonte telle quelle : le bloc 2
    #    (suppression) n'est alors jamais atteint.
    _generer_contenu(client, page_id, rapport, config, apres_id=point_insertion)

    # 2. Seulement après un succès complet de l'étape 1 : purge de l'ancien contenu.
    for bloc in anciens_blocs:
        client.blocks.delete(bloc["id"])

    if idx_notes is None:
        client.blocks.children.append(page_id, children=[
            nb.titre(2, NOTES_TITRE), {"type": "paragraph", "paragraph": {"rich_text": []}}])


def publier(config: dict, rapport: dict, chemin_config: str | Path | None = None) -> str | None:
    """Upsert de l'entrée du jour dans la base Notion. Retourne son URL."""
    cfg = config.get("notion", {})
    if not cfg.get("actif", True):
        log.info("Publication Notion désactivée (config)")
        return None
    cle = os.environ.get("NOTION_API_KEY", "")
    if not cle:
        log.warning("Publication Notion sautée : NOTION_API_KEY manquante")
        return None

    client = Client(auth=cle)
    if not hasattr(client, "data_sources"):
        log.error("notion-client trop ancien (data_sources absent) : "
                  "pip install 'notion-client>=3.1,<4'")
        return None
    database_id = _obtenir_database(client, cfg, chemin_config)
    if not database_id:
        return None
    data_source_id = _obtenir_data_source(client, database_id)

    date_rapport = rapport["meta"]["date_rapport"]
    existante = _trouver_entree(client, data_source_id, date_rapport)
    proprietes = _proprietes(rapport)

    if existante:
        client.pages.update(existante["id"], properties=proprietes)
        _regenerer_corps(client, existante["id"], rapport, config)
        log.info("Entrée Notion du %s mise à jour (notes préservées) : %s",
                 date_rapport, existante.get("url"))
        return existante.get("url")

    page = client.pages.create(
        parent={"type": "data_source_id", "data_source_id": data_source_id},
        icon={"type": "emoji", "emoji": "📊"},
        properties=proprietes,
    )
    client.blocks.children.append(page["id"], children=[nb.paragraphe_gris(ANCRE_TEXTE)])
    _generer_contenu(client, page["id"], rapport, config)
    client.blocks.children.append(page["id"], children=[
        nb.titre(2, NOTES_TITRE), {"type": "paragraph", "paragraph": {"rich_text": []}}])
    log.info("Entrée Notion du %s créée : %s", date_rapport, page.get("url"))
    return page.get("url")
