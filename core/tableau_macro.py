"""Tableau macro : base Notion « Tableau macro » + dashboard web.

Structure Notion (depuis 2026-10-08) : UNE LIGNE par couple (indicateur, devise),
pour comparer Actuel / Précédent / Prévision sur la même ligne. Propriétés :
Indicateur (titre), Actuel, Précédent, Prévision, Surprise (▲ ▼ =), Variation,
Devise, Date de publication, Prochaine publication, Source, Dernière mise à jour,
Ordre. Une vue par devise + une vue « Toutes les devises » groupée par devise.

Toutes les valeurs viennent du registre permanent (core/registre_macro.py) ; ce
module ne fait que l'affichage et la synchronisation. Code pur, aucun LLM.

Priorité d'une cellule : fichier manuel du jour (data/overrides/AAAA-MM-JJ.json)
> saisie faite dans Notion (core/saisies_manuelles.py) > publication officielle
la plus récente — SAUF si la publication officielle est plus récente que la
saisie (elle la remplace, la saisie passe dans l'historique).

Saisie manuelle : le pipeline mémorise, par cellule (registre, `ecrit_cellules`),
le dernier texte qu'il y a lui-même écrit. Une cellule Notion différente de cette
mémoire et de ce qu'il écrirait aujourd'hui est une SAISIE : jamais écrasée.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

from core import registre_macro as rm
from core import saisies_manuelles as sm
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

TITRE_BASE = "Tableau macro"
PAUSE_ECRITURE_S = 0.35  # limite Notion ~3 requêtes/s
LIBELLE_INDICE = "Indice de surprise 30 j"
ORDRE_INDICE = 90
CHAMP_OVERRIDE = {"Actuel": "valeur", "Précédent": "precedent", "Prévision": "prevision"}
COULEURS_DEVISE = {"USD": "green", "EUR": "blue", "GBP": "red", "JPY": "pink", "CHF": "orange",
                   "CAD": "yellow", "AUD": "purple", "NZD": "brown", "CNY": "gray"}
# Ordre d'affichage des colonnes dans les vues (demandé : Indicateur, Actuel, Précédent,
# Prévision, Surprise, puis le reste).
COLONNES_VUE = ["Indicateur", "Actuel", "Précédent", "Prévision", "Surprise", "Variation",
                "Devise", "Date de publication", "Prochaine publication", "Source",
                "Dernière mise à jour", "Ordre"]
LARGEURS = {"Indicateur": 190, "Actuel": 120, "Précédent": 120, "Prévision": 170, "Surprise": 80,
            "Variation": 90, "Devise": 80, "Date de publication": 130, "Prochaine publication": 150,
            "Source": 220, "Dernière mise à jour": 130, "Ordre": 60}
ANCIENS_NOMS_VUES = {"Default view", "Actuel", "Précédent", "Prévision", "Table"}


# ------------------------------------------------------------ résolution
def resoudre_cellule(case: dict, indicateur: str, devise: str, type_valeur: str, unite: str,
                     saisies: dict, overrides_jour: dict, jour: date) -> dict:
    """Cellule affichée + origine. `texte` = forme complète (valeur + date + surprise,
    matrice web), `valeur` = valeur seule (colonne Notion). `a_archiver` = saisie
    supplantée par une publication officielle plus récente (à archiver par l'appelant)."""
    officiel_texte = rm.texte_officiel(case, type_valeur, unite)
    officiel_valeur = rm.valeur_cellule(case, type_valeur, unite)
    surprise = rm.surprise_cellule(case) if type_valeur == "Actuel" else None
    ov = ((overrides_jour or {}).get(devise) or {}).get(indicateur) or {}
    valeur_ov = ov.get(CHAMP_OVERRIDE[type_valeur])
    if valeur_ov not in (None, ""):
        t = f"{rm._fr(str(valeur_ov), unite)} {sm.MARQUEUR}"
        return {"texte": t, "valeur": t, "manuel": True, "origine": "fichier_manuel", "surprise": None}
    cle_s = sm.cle(devise, indicateur, type_valeur)
    saisie = saisies.get("saisies", {}).get(cle_s)
    if saisie:
        publication = (case.get("actuel") or {}).get("date_pub")
        if publication and publication > saisie["saisi_le"]:
            return {"texte": officiel_texte, "valeur": officiel_valeur, "manuel": False,
                    "origine": "officiel", "surprise": surprise, "a_archiver": cle_s}
        t = f"{saisie['texte']} {sm.MARQUEUR}"
        return {"texte": t, "valeur": t, "manuel": True, "origine": "saisie_notion", "surprise": None}
    return {"texte": officiel_texte, "valeur": officiel_valeur, "manuel": False,
            "origine": "officiel", "surprise": surprise}


def _etat(case: dict, valeur: str) -> str:
    """valeur | explique (absent, consensus à venir, projection, donnée de marché) | vide."""
    if case.get("statut") == "non_applicable":
        return "explique"
    if valeur.startswith("n/d"):
        return "vide"
    if valeur.startswith(("consensus à venir", "proj. BC", "—")):
        return "explique"
    return "valeur"


def _symbole_variation(case: dict) -> str | None:
    v = case.get("variation_pb")
    if v is None:
        return None
    return "=" if abs(v) < 0.5 else ("▲" if v > 0 else "▼")


def construire_matrice(registre: dict, saisies: dict, overrides_jour: dict,
                       cfg_tm: dict, jour: date, indice: dict | None = None) -> dict:
    """Matrice (indicateur × devise × type, forme complète pour le web) ET lignes
    (une par couple indicateur × devise, colonnes Notion)."""
    from core import controles_macro
    devises = cfg_tm["ordre_devises"]
    cellules: dict[str, dict] = {}
    lignes: list[dict] = []
    archives: list[str] = []
    compte = {t: {"valeur": 0, "explique": 0, "vide": 0} for t in rm.TYPES}
    for ordre, (indicateur, cfg_ind) in enumerate(cfg_tm["indicateurs"].items(), 1):
        cellules[indicateur] = {}
        for devise in devises:
            case = registre["cases"].get(rm.cle(indicateur, devise)) or {"statut": "a_initialiser"}
            cellules[indicateur][devise] = {}
            ligne = {"cle": rm.cle(indicateur, devise), "indicateur": indicateur,
                     "libelle": cfg_ind["libelle"], "devise": devise, "ordre": ordre,
                     "manuel": {}, "etat": {}, "marche": bool(case.get("marche")),
                     "frequence": case.get("frequence")}
            for t in rm.TYPES:
                c = resoudre_cellule(case, indicateur, devise, t, cfg_ind.get("unite", ""),
                                     saisies, overrides_jour, jour)
                if c.pop("a_archiver", None):
                    archives.append(sm.cle(devise, indicateur, t))
                c["etat"] = _etat(case, c["valeur"])
                compte[t][c["etat"]] += 1
                if t == "Actuel" and not c["manuel"]:
                    a = case.get("actuel") or {}
                    c.update(date=a.get("date_pub"), source=a.get("source"), consensus=a.get("consensus"))
                cellules[indicateur][devise][t] = c
                ligne[t] = c["valeur"]
                ligne["manuel"][t] = c["manuel"]
                ligne["etat"][t] = c["etat"]
            actuel_manuel = ligne["manuel"]["Actuel"]
            ligne["surprise"] = None if actuel_manuel else (
                _symbole_variation(case) if case.get("marche") else rm.surprise_cellule(case))
            ligne["variation"] = (f"{case['variation_pb']:+.0f} pb"
                                  if case.get("variation_pb") is not None else None)
            ligne["date_pub"] = rm.date_publication(case)
            ligne["prochaine"] = rm.prochaine_publication(case)
            ligne["source"] = rm.source_cellule(case)
            lignes.append(ligne)
    # Indice de surprise 30 j : une ligne par devise (calculé en Python, jamais saisi).
    indice_txt = {}
    if indice:
        for devise in devises:
            i = indice.get(devise, {})
            fleche = {"hausse": "▲", "baisse": "▼", "stable": "="}.get(i.get("tendance"))
            precedent = "—" if i.get("precedent") is None else f"{i['precedent']:+.1f}".replace(".", ",")
            actuel = "n/d" if i.get("indice") is None else f"{i['indice']:+.1f}".replace(".", ",")
            indice_txt[devise] = {**i, "texte": controles_macro.texte_indice(i)}
            lignes.append({"cle": f"{devise}|indice_surprise", "indicateur": "indice_surprise",
                           "libelle": LIBELLE_INDICE, "devise": devise, "ordre": ORDRE_INDICE,
                           "Actuel": actuel, "Précédent": precedent,
                           "Prévision": "— (indicateur calculé)", "manuel": {}, "etat": {},
                           "surprise": fleche, "variation": (f"n={i['n']}" if i.get("n") else None),
                           "date_pub": None, "prochaine": None, "marche": False, "frequence": None,
                           "source": "Calcul Python : surprises vs consensus, fenêtre 30 j"})
    remplissage = {t: {**n, "total": sum(n.values()),
                       "taux_pct": round(100 * (n["valeur"] + n["explique"]) / max(1, sum(n.values())), 1)}
                   for t, n in compte.items()}
    return {
        "maj": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "devises": devises, "types": list(rm.TYPES),
        "indicateurs": [{"id": k, "libelle": v["libelle"], "sens": v.get("sens", "normal"),
                         "marche": bool(v.get("marche"))} for k, v in cfg_tm["indicateurs"].items()],
        "cellules": cellules, "lignes": lignes, "indice_surprise": indice_txt,
        "remplissage": remplissage, "_a_archiver": archives,
    }


def ecrire_web(matrice: dict, dossier_docs: str | Path) -> None:
    sortie = {k: v for k, v in matrice.items() if not k.startswith("_")}
    chemin = Path(dossier_docs) / "data" / "tableau_macro.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ Notion
def _rt(texte: str | None) -> list[dict]:
    return [{"type": "text", "text": {"content": str(texte)[:2000]}}] if texte else []


def _texte_rt(prop: dict | None) -> str:
    if not prop:
        return ""
    return "".join(t.get("plain_text", "") for t in prop.get("rich_text", [])).strip()


def _select(prop: dict | None) -> str | None:
    return ((prop or {}).get("select") or {}).get("name")


def _date_notion(prop: dict | None) -> str | None:
    d = ((prop or {}).get("date") or {}).get("start")
    if not d:
        return None
    try:
        dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
    except ValueError:
        return d
    if len(d) <= 10:
        return d
    return dt.astimezone(timezone.utc).isoformat(timespec="minutes")


def _schema(devises: list[str]) -> dict:
    return {
        "Actuel": {"rich_text": {}}, "Précédent": {"rich_text": {}}, "Prévision": {"rich_text": {}},
        "Surprise": {"select": {"options": [{"name": "▲", "color": "blue"}, {"name": "▼", "color": "orange"},
                                            {"name": "=", "color": "gray"}]}},
        "Variation": {"rich_text": {}},
        "Devise": {"select": {"options": [{"name": d, "color": COULEURS_DEVISE.get(d, "default")}
                                          for d in devises]}},
        "Date de publication": {"date": {}}, "Prochaine publication": {"date": {}},
        "Source": {"rich_text": {}}, "Dernière mise à jour": {"date": {}}, "Ordre": {"number": {}},
    }


def _persister_ids(chemin_config: str | Path | None, database_id: str,
                   ancienne: str | None = None) -> None:
    """Écrit l'ID dans config.yaml, sous tableau_macro (distinct de notion.database_id)."""
    if not chemin_config:
        log.warning("Chemin config inconnu : reporter tableau_macro.database_id: \"%s\"", database_id)
        return
    chemin = Path(chemin_config)
    texte = chemin.read_text(encoding="utf-8")
    trouve = re.search(r"(?m)^tableau_macro:", texte)
    debut = trouve.start() if trouve else -1
    if debut == -1:
        log.warning("Section tableau_macro introuvable dans config.yaml — ID à reporter : %s", database_id)
        return
    tete, bloc = texte[:debut], texte[debut:]
    bloc, n = re.subn(r'(\n  database_id:\s*)"[0-9a-f]*"', rf'\g<1>"{database_id}"', bloc, count=1)
    if ancienne and n:
        if "ancienne_database_id:" in bloc:
            bloc = re.sub(r'(ancienne_database_id:\s*)"[0-9a-f]*"', rf'\g<1>"{ancienne}"', bloc, count=1)
        else:
            bloc = bloc.replace(f'database_id: "{database_id}"',
                                f'database_id: "{database_id}"\n  # Ancienne base (structure Type x 9 colonnes devises), '
                                f'archivée le {date.today().isoformat()} : conservée, plus alimentée.\n'
                                f'  ancienne_database_id: "{ancienne}"', 1)
    if n:
        chemin.write_text(tete + bloc, encoding="utf-8")
        log.info("tableau_macro.database_id écrit dans %s", chemin)
    else:
        log.warning("`database_id` introuvable sous tableau_macro — ajouter : \"%s\"", database_id)


def _parent_page(config: dict) -> str | None:
    from agents.agent_redacteur import _extraire_page_id
    return _extraire_page_id(str(config.get("notion", {}).get("page_parent_id", "")))


def _creer_base(client, config: dict) -> str:
    cfg_tm = config["tableau_macro"]
    parent = _parent_page(config)
    base = client.databases.create(
        parent={"type": "page_id", "page_id": parent},
        title=[{"type": "text", "text": {"content": TITRE_BASE}}],
        icon={"type": "emoji", "emoji": "🌐"},
        initial_data_source={"properties": {"Indicateur": {"title": {}}, **_schema(cfg_tm["ordre_devises"])}},
    )
    database_id = base["id"].replace("-", "")
    log.info("Base Notion « %s » créée (%s)", TITRE_BASE, database_id)
    return database_id


def obtenir_base(client, config: dict, chemin_config: str | Path | None) -> tuple[str, bool] | None:
    """(database_id, créée_maintenant). Ordre : ID de config.yaml > base du même
    titre sous la page parente (anti-doublon) > création."""
    from agents.agent_redacteur import _extraire_page_id
    cfg_tm = config["tableau_macro"]
    existant = _extraire_page_id(str(cfg_tm.get("database_id", "")))
    if existant:
        return existant, False
    parent = _parent_page(config)
    if not parent:
        log.warning("Tableau macro : page parente Notion inconnue — publication Notion sautée")
        return None
    curseur = None
    while True:
        page = client.blocks.children.list(parent, start_cursor=curseur, page_size=100) \
            if curseur else client.blocks.children.list(parent, page_size=100)
        for bloc in page["results"]:
            if (bloc.get("type") == "child_database"
                    and bloc.get("child_database", {}).get("title") == TITRE_BASE):
                trouve = bloc["id"].replace("-", "")
                log.info("Base « %s » retrouvée sous la page parente (%s) : réutilisée", TITRE_BASE, trouve)
                _persister_ids(chemin_config, trouve)
                return trouve, False
        if not page.get("has_more"):
            break
        curseur = page["next_cursor"]
    nouveau = _creer_base(client, config)
    _persister_ids(chemin_config, nouveau)
    return nouveau, True


def _infos_source(client, database_id: str) -> tuple[str, dict]:
    base = client.databases.retrieve(database_id)
    sources = base.get("data_sources", [])
    if not sources:
        raise RuntimeError(f"Base Notion {database_id} sans data source")
    ds_id = sources[0]["id"]
    return ds_id, client.data_sources.retrieve(ds_id).get("properties", {})


def _ancienne_structure(proprietes: dict) -> bool:
    """Structure 2026-10-07 : une ligne par (indicateur, TYPE), une colonne par devise."""
    return "Type" in proprietes and "Devise" not in proprietes


def _completer_schema(client, ds_id: str, proprietes: dict, devises: list[str]) -> None:
    manquantes = {n: s for n, s in _schema(devises).items() if n not in proprietes}
    titre = next((n for n, p in proprietes.items() if p.get("type") == "title"), None)
    if titre and titre != "Indicateur":
        manquantes[titre] = {"name": "Indicateur"}
    if manquantes:
        client.data_sources.update(ds_id, properties=manquantes)
        log.info("Schéma « %s » complété : %s", TITRE_BASE, ", ".join(sorted(manquantes)))


def _lire_lignes(client, ds_id: str) -> dict[tuple[str, str], dict]:
    """Lignes de la base, clé (libellé de l'indicateur, devise)."""
    lignes: dict[tuple[str, str], dict] = {}
    curseur = None
    while True:
        res = client.data_sources.query(ds_id, start_cursor=curseur, page_size=100) if curseur \
            else client.data_sources.query(ds_id, page_size=100)
        for page in res["results"]:
            p = page["properties"]
            titre = "".join(t.get("plain_text", "") for t in p.get("Indicateur", {}).get("title", []))
            lignes[(titre.strip(), _select(p.get("Devise")) or "")] = page
        if not res.get("has_more"):
            return lignes
        curseur = res["next_cursor"]


# ---- vues -------------------------------------------------------------
def _configuration_colonnes(avec_devise: bool, ids: dict[str, str]) -> list[dict]:
    colonnes = []
    for nom in COLONNES_VUE:
        visible = not (nom == "Ordre" or (nom == "Devise" and not avec_devise))
        colonnes.append({"property_id": "title" if nom == "Indicateur" else ids.get(nom, nom),
                         "visible": visible, "width": LARGEURS[nom]})
    return colonnes


def creer_vues(client, database_id: str, ds_id: str, cfg_tm: dict, drapeaux: dict[str, str]) -> dict:
    """Une vue par devise (filtre sur Devise, tri sur Ordre = ordre des indicateurs de
    config.yaml) + « Toutes les devises » groupée par devise ; supprime « Default view »
    et les vues de l'ancienne structure. Idempotent (une vue existante n'est pas recréée)."""
    ids = {nom: p.get("id", nom) for nom, p in client.data_sources.retrieve(ds_id).get("properties", {}).items()}
    existantes = {}
    for v in client.views.list(database_id=database_id).get("results", []):
        if isinstance(v, dict):
            existantes[client.views.retrieve(v["id"]).get("name")] = v["id"]
    voulues = [("Toutes les devises", None)] + [(f"{drapeaux.get(d, '')} {d}".strip(), d)
                                                for d in cfg_tm["ordre_devises"]]
    bilan = {"creees": [], "supprimees": []}
    for nom, devise in voulues:
        if nom in existantes:
            continue
        corps = {"database_id": database_id, "data_source_id": ds_id, "name": nom, "type": "table",
                 "sorts": [{"property": "Ordre", "direction": "ascending"}],
                 "configuration": {"type": "table", "properties": _configuration_colonnes(devise is None, ids),
                                   "frozen_column_index": 0}}
        if devise:
            corps["filter"] = {"property": "Devise", "select": {"equals": devise}}
        else:
            corps["configuration"]["group_by"] = {"type": "select", "property_id": ids.get("Devise", "Devise"),
                                                    "sort": {"type": "manual"}}
        client.views.create(**corps)
        bilan["creees"].append(nom)
        time.sleep(PAUSE_ECRITURE_S)
    voulus = {nom for nom, _ in voulues}
    for nom, vid in existantes.items():
        if nom in ANCIENS_NOMS_VUES and nom not in voulus:
            client.views.delete(vid)
            bilan["supprimees"].append(nom)
    return bilan


# ---- détection des saisies / synchronisation -----------------------------
def detecter_saisies(lignes: dict, registre: dict, saisies: dict, overrides_jour: dict,
                     cfg_tm: dict, jour: date) -> int:
    """Compare chaque cellule Actuel / Précédent / Prévision à (mémoire du pipeline,
    texte qu'il écrirait) et enregistre les écarts comme saisies manuelles. Une
    cellule vide n'est pas une saisie ; les lignes calculées (indice) non plus."""
    detectees = 0
    for indicateur, cfg_ind in cfg_tm["indicateurs"].items():
        for devise in cfg_tm["ordre_devises"]:
            page = lignes.get((cfg_ind["libelle"], devise))
            if not page:
                continue
            case = registre["cases"].get(rm.cle(indicateur, devise)) or {"statut": "a_initialiser"}
            for t in rm.TYPES:
                actuel = _texte_rt(page["properties"].get(t))
                if not actuel:
                    continue
                memoire = (case.get("ecrit_cellules") or {}).get(t)
                voulu = resoudre_cellule(case, indicateur, devise, t, cfg_ind.get("unite", ""),
                                         saisies, overrides_jour, jour)["valeur"]
                if actuel == memoire or actuel == voulu:
                    continue
                sm.enregistrer(saisies, devise, indicateur, t, actuel, jour)
                detectees += 1
    return detectees


def _proprietes_ligne(ligne: dict, jour: date) -> dict:
    return {
        "Actuel": {"rich_text": _rt(ligne.get("Actuel"))},
        "Précédent": {"rich_text": _rt(ligne.get("Précédent"))},
        "Prévision": {"rich_text": _rt(ligne.get("Prévision"))},
        "Surprise": {"select": {"name": ligne["surprise"]} if ligne.get("surprise") else None},
        "Variation": {"rich_text": _rt(ligne.get("variation"))},
        "Date de publication": {"date": {"start": ligne["date_pub"]} if ligne.get("date_pub") else None},
        "Prochaine publication": {"date": {"start": ligne["prochaine"]} if ligne.get("prochaine") else None},
        "Source": {"rich_text": _rt(ligne.get("source"))},
        "Ordre": {"number": ligne["ordre"]},
    }


def _diff(page: dict, ligne: dict) -> list[str]:
    p = page["properties"]
    ecarts = []
    for t in rm.TYPES + ("Variation", "Source"):
        voulu = ligne.get(t.lower() if t in ("Variation", "Source") else t) or ""
        if _texte_rt(p.get(t)) != voulu:
            ecarts.append(t)
    if _select(p.get("Surprise")) != ligne.get("surprise"):
        ecarts.append("Surprise")
    if _date_notion(p.get("Date de publication")) != ligne.get("date_pub"):
        ecarts.append("Date de publication")
    if _date_notion(p.get("Prochaine publication")) != ligne.get("prochaine"):
        ecarts.append("Prochaine publication")
    if (p.get("Ordre") or {}).get("number") != ligne["ordre"]:
        ecarts.append("Ordre")
    return ecarts


def synchroniser(client, ds_id: str, lignes_notion: dict, matrice: dict, registre: dict,
                 jour: date) -> dict:
    """Une ligne par (indicateur, devise) : upsert, jamais de doublon, seules les
    propriétés qui diffèrent sont écrites. Une ligne en échec ne bloque pas les autres."""
    stats = {"lignes_creees": 0, "lignes_modifiees": 0, "cellules_ecrites": 0, "erreurs": 0}
    ordre_devise = {d: i for i, d in enumerate(matrice["devises"])}
    for ligne in sorted(matrice["lignes"], key=lambda r: (ordre_devise[r["devise"]], r["ordre"])):
        page = lignes_notion.get((ligne["libelle"], ligne["devise"]))
        try:
            if page is None:
                props = {"Indicateur": {"title": _rt(ligne["libelle"])},
                         "Devise": {"select": {"name": ligne["devise"]}},
                         "Dernière mise à jour": {"date": {"start": jour.isoformat()}},
                         **{k: v for k, v in _proprietes_ligne(ligne, jour).items()
                            if v not in ({"select": None}, {"date": None}, {"rich_text": []})}}
                client.pages.create(parent={"type": "data_source_id", "data_source_id": ds_id},
                                    properties=props)
                stats["lignes_creees"] += 1
                stats["cellules_ecrites"] += len(props)
            else:
                ecarts = _diff(page, ligne)
                if ecarts:
                    props = {k: v for k, v in _proprietes_ligne(ligne, jour).items() if k in ecarts}
                    props["Dernière mise à jour"] = {"date": {"start": jour.isoformat()}}
                    client.pages.update(page["id"], properties=props)
                    stats["lignes_modifiees"] += 1
                    stats["cellules_ecrites"] += len(ecarts)
            if ligne["indicateur"] != "indice_surprise":
                _memoriser(registre, ligne)
            time.sleep(PAUSE_ECRITURE_S)
        except Exception as exc:  # noqa: BLE001
            stats["erreurs"] += 1
            log.error("Tableau macro Notion : ligne %s / %s en échec : %s", ligne["libelle"],
                      ligne["devise"], masquer_secrets(str(exc))[:200])
    return stats


def _memoriser(registre: dict, ligne: dict) -> None:
    case = registre["cases"].setdefault(ligne["cle"], {
        "indicateur": ligne["indicateur"], "devise": ligne["devise"], "statut": "a_initialiser",
        "actuel": None, "precedent": None, "prevision": None, "historique": [], "ecrit_notion": {}})
    case.setdefault("ecrit_cellules", {}).update({t: ligne[t] for t in rm.TYPES})


# ---- migration de l'ancienne structure -------------------------------------
def _lire_lignes_ancienne(client, ds_id: str) -> dict[tuple[str, str], dict]:
    lignes: dict[tuple[str, str], dict] = {}
    curseur = None
    while True:
        res = client.data_sources.query(ds_id, start_cursor=curseur, page_size=100) if curseur \
            else client.data_sources.query(ds_id, page_size=100)
        for page in res["results"]:
            p = page["properties"]
            titre = "".join(t.get("plain_text", "") for t in p.get("Indicateur", {}).get("title", []))
            lignes[(titre.strip(), _select(p.get("Type")) or "")] = page
        if not res.get("has_more"):
            return lignes
        curseur = res["next_cursor"]


def _detecter_saisies_ancienne(lignes: dict, registre: dict, saisies: dict, overrides_jour: dict,
                               cfg_tm: dict, jour: date) -> int:
    """Dernière lecture de l'ancienne base : toute cellule modifiée à la main depuis
    la dernière écriture du pipeline est enregistrée AVANT la migration (rien n'est perdu)."""
    detectees = 0
    for indicateur, cfg_ind in cfg_tm["indicateurs"].items():
        for t in rm.TYPES:
            page = lignes.get((cfg_ind["libelle"], t))
            if not page:
                continue
            for devise in cfg_tm["ordre_devises"]:
                actuel = _texte_rt(page["properties"].get(devise))
                if not actuel:
                    continue
                case = registre["cases"].get(rm.cle(indicateur, devise)) or {"statut": "a_initialiser"}
                memoire = (case.get("ecrit_notion") or {}).get(t)
                voulu = resoudre_cellule(case, indicateur, devise, t, cfg_ind.get("unite", ""),
                                         saisies, overrides_jour, jour)["texte"]
                if actuel == memoire or actuel == voulu:
                    continue
                sm.enregistrer(saisies, devise, indicateur, t, actuel, jour)
                detectees += 1
    return detectees


def migrer_ancienne_base(client, config: dict, chemin_config: str | Path | None, ancien_id: str,
                         ancien_ds: str, registre: dict, saisies: dict, overrides_jour: dict,
                         jour: date) -> tuple[str, str, dict]:
    """Ancienne base (une colonne par devise) -> nouvelle base (une ligne par couple).
    1. dernière lecture de l'ancienne base : les saisies manuelles sont capturées ;
    2. l'ancienne base est ARCHIVÉE (renommée, conservée) — jamais supprimée ;
    3. la nouvelle base est créée ; registre et saisies (inchangés) la rempliront."""
    cfg_tm = config["tableau_macro"]
    lignes = _lire_lignes_ancienne(client, ancien_ds)
    n = _detecter_saisies_ancienne(lignes, registre, saisies, overrides_jour, cfg_tm, jour)
    log.info("Migration Tableau macro : %d saisie(s) manuelle(s) capturée(s) dans l'ancienne base", n)
    client.databases.update(
        ancien_id, icon={"type": "emoji", "emoji": "📦"},
        title=[{"type": "text", "text": {"content":
                f"{TITRE_BASE} — ancienne structure (archivée {jour.isoformat()})"}}])
    nouvel_id = _creer_base(client, config)
    _persister_ids(chemin_config, nouvel_id, ancienne=ancien_id)
    for case in registre["cases"].values():  # mémoire de l'ancienne structure : obsolète
        case.pop("ecrit_notion", None)
        case.pop("ecrit_cellules", None)
    ds_id, _ = _infos_source(client, nouvel_id)
    return nouvel_id, ds_id, {"saisies_capturees": n, "ancienne": ancien_id}


# ------------------------------------------------------------ orchestration
def _taux_directeurs(config: dict, dossier_cache: Path) -> dict[str, dict]:
    """Taux de repli du config.yaml, remplacés par ceux de la dernière collecte
    macro (FRED pour l'USD) quand ils sont plus récents."""
    taux = {d: {"taux": v.get("taux"), "date": str(v.get("date")), "source": "config (repli manuel)"}
            for d, v in config.get("taux_directeurs", {}).items()}
    try:
        cache = json.loads((dossier_cache / "collecte_macro.json").read_text(encoding="utf-8"))
        for d, t in cache.get("donnees", {}).get("taux_directeurs", {}).items():
            if d in taux and str(t.get("date")) > taux[d]["date"]:
                taux[d] = {"taux": t.get("taux"), "date": str(t["date"]), "source": t.get("source", "FRED")}
    except (OSError, json.JSONDecodeError):
        pass
    return taux


def _web_inchange(matrice: dict, chemin: Path) -> bool:
    try:
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    nouveau = {k: v for k, v in matrice.items() if not k.startswith("_")}
    return {**ancien, "maj": None} == {**nouveau, "maj": None}


def mettre_a_jour(config: dict, racine: str | Path, chemin_config: str | Path | None = None,
                  client_scraping=None, client_notion=None, maintenant: datetime | None = None,
                  avec_notion: bool = True) -> dict:
    """Collecte ForexFactory si un créneau est dû (ou après une publication
    importante), met à jour le registre, détecte les saisies manuelles Notion,
    publie Notion + web. Chaque sous-étape échoue isolément. Retourne
    {modifie, saisies_overrides, remplissage, controles, indice_surprise, ff, fred, notion}."""
    cfg_tm = config.get("tableau_macro") or {}
    if not cfg_tm.get("actif", True):
        return {"modifie": False, "saisies_overrides": {}}
    from agents import collecte_forexfactory_mois as ffm
    from core import controles_macro, overrides
    racine = Path(racine)
    donnees = racine / config["chemins"]["donnees"]
    chemin_reg, chemin_sai = donnees / "registre_macro.json", donnees / "overrides" / "saisies_notion.json"
    maintenant = maintenant or datetime.now(timezone.utc)
    jour = date.today()
    registre, saisies = rm.charger(chemin_reg), sm.charger(chemin_sai)
    avant = (json.dumps(registre, sort_keys=True), json.dumps(saisies, sort_keys=True))
    resultat: dict = {"ff": None, "notion": None}

    # 1. ForexFactory (page « mois ») : créneau dû ou mise à jour ciblée
    try:
        if client_scraping is None:
            from core.scraping import ClientScraping
            client_scraping = ClientScraping(config["scraping"], donnees / "cache")
        ff = ffm.collecter(
            cfg_tm, client_scraping, donnees / "cache", maintenant,
            cibles_fn=lambda deja: rm.publications_a_cibler(registre, cfg_tm["forexfactory"],
                                                            maintenant, deja))
        resultat["ff"] = {"statut": ff["statut"], "note": ff["note"], "nb": len(ff["evenements"]),
                          "declencheur": ff.get("declencheur")}
        if ff["statut"] == "frais":
            bilan = rm.integrer_evenements(registre, ff["evenements"], cfg_tm, maintenant)
            resultat["ff"].update(bilan)
            log.info("Tableau macro : %d case(s) mises à jour, %d introuvable(s) à initialiser",
                     bilan["mises_a_jour"], len(bilan["introuvables"]))
            # Premier créneau du jour : mois suivants SEULEMENT si des cases n'ont pas
            # de date de prochaine publication (jamais plus, jamais sans besoin).
            if ff.get("premier_du_jour"):
                for decalage, _ in enumerate(cfg_tm["forexfactory"].get("mois_suivants_si_necessaire", []), 1):
                    if not rm.cases_sans_date_suivante(registre, cfg_tm):
                        break
                    suite = ffm.collecter_mois_suivant(cfg_tm, client_scraping, donnees / "cache",
                                                       decalage, maintenant)
                    if suite["statut"] != "frais":
                        log.warning("Tableau macro : mois +%d non lu (%s)", decalage, suite["note"])
                        break
                    rm.integrer_evenements(registre, suite["evenements"], cfg_tm, maintenant)
        elif ff["statut"] == "indisponible":
            log.warning("Tableau macro : ForexFactory indisponible (%s) — registre inchangé", ff["note"])
    except Exception as exc:  # noqa: BLE001
        log.error("Tableau macro : collecte ForexFactory en échec : %s", masquer_secrets(str(exc))[:200])

    # 2. Taux directeurs + cases manquantes (jamais de cellule absente du registre)
    rm.integrer_taux(registre, _taux_directeurs(config, donnees / "cache"))
    for indicateur, par_devise in cfg_tm["correspondances"].items():
        for devise, mapping in par_devise.items():
            case = rm._case(registre, indicateur, devise)
            if mapping.get("absent"):
                case.update(statut="non_applicable", absent=mapping["absent"])
            case["etiquette"] = mapping.get("etiquette")

    # 2 bis. FRED : repli des valeurs absentes, contrôle croisé, projections Fed (cache du jour)
    try:
        import os as _os
        from core import collecte_cache, fred_macro
        fred = collecte_cache.avec_cache(
            "tableau_fred", donnees / "cache", jour, True, fred_macro.collecter, cfg_tm,
            _os.environ.get("FRED_API_KEY", "").strip())
        resultat["fred"] = {"valeurs": len(fred.get("valeurs", {})), "erreurs": fred.get("erreurs", [])}
        resultat["fred"]["comblees"] = rm.integrer_fred(registre, fred)
        rm.integrer_projections(registre, fred)
    except Exception as exc:  # noqa: BLE001
        log.error("Tableau macro : FRED en échec : %s", masquer_secrets(str(exc))[:200])

    overrides_jour = overrides.charger(donnees / "overrides", jour)

    # 3. Notion : lecture, migration éventuelle de l'ancienne structure, saisies manuelles
    import os
    from notion_client import Client
    cle = os.environ.get("NOTION_API_KEY", "").strip()
    notion_actif = avec_notion and config.get("notion", {}).get("actif", True) and (client_notion or cle)
    client, ds_id, database_id, lignes_notion, cree = None, None, None, {}, False
    drapeaux = {d: v.get("drapeau", "") for d, v in config.get("devises", {}).items()}
    if notion_actif:
        try:
            client = client_notion or Client(auth=cle)
            base = obtenir_base(client, config, chemin_config)
            if base:
                database_id, cree = base
                ds_id, proprietes = _infos_source(client, database_id)
                if _ancienne_structure(proprietes):
                    database_id, ds_id, resultat["migration"] = migrer_ancienne_base(
                        client, config, chemin_config, database_id, ds_id, registre, saisies,
                        overrides_jour, jour)
                    cree = True
                else:
                    _completer_schema(client, ds_id, proprietes, cfg_tm["ordre_devises"])
                if cree:
                    config["tableau_macro"]["database_id"] = database_id
                lignes_notion = _lire_lignes(client, ds_id)
                nb = detecter_saisies(lignes_notion, registre, saisies, overrides_jour, cfg_tm, jour)
                if nb:
                    resultat["saisies_detectees"] = nb
        except Exception as exc:  # noqa: BLE001
            client = None
            log.error("Tableau macro Notion (lecture) en échec : %s", masquer_secrets(str(exc))[:200])

    # 4. Contrôles + indice de surprise (Python pur), matrice et lignes (priorités)
    controles = controles_macro.controler_registre(registre, cfg_tm, maintenant)
    indice = controles_macro.indice_surprise(registre, cfg_tm, jour)
    matrice = construire_matrice(registre, saisies, overrides_jour, cfg_tm, jour, indice)
    matrice["anomalies"] = controles["anomalies"][:30]
    for cle_saisie in matrice.pop("_a_archiver", []):
        sm.archiver(saisies, cle_saisie, jour, "publication officielle plus récente")
    resultat["controles"], resultat["indice_surprise"] = controles, indice
    resultat["remplissage"] = matrice["remplissage"]

    # 5. Notion : écriture des seules propriétés modifiées (+ vues à la création)
    if client and ds_id:
        try:
            resultat["notion"] = synchroniser(client, ds_id, lignes_notion, matrice, registre, jour)
            etat_vues = registre.setdefault("notion", {})
            if cree or etat_vues.get("vues_ok_pour") != database_id:
                try:
                    resultat["vues"] = creer_vues(client, database_id, ds_id, cfg_tm, drapeaux)
                    etat_vues["vues_ok_pour"] = database_id  # idempotent : pas de GET inutile ensuite
                    log.info("Vues « %s » : créées %s, supprimées %s", TITRE_BASE,
                             resultat["vues"]["creees"], resultat["vues"]["supprimees"])
                except Exception as exc:  # noqa: BLE001
                    log.warning("Vues Notion non créées par l'API (%s) — voir README",
                                masquer_secrets(str(exc))[:200])
        except Exception as exc:  # noqa: BLE001
            log.error("Tableau macro Notion (écriture) en échec : %s", masquer_secrets(str(exc))[:200])

    # 6. Web + persistance
    chemin_web = racine / config["publication_web"]["dossier_docs"] / "data" / "tableau_macro.json"
    web_modifie = not _web_inchange(matrice, chemin_web)
    if web_modifie:
        ecrire_web(matrice, racine / config["publication_web"]["dossier_docs"])
    rm.sauver(registre, chemin_reg)
    sm.sauver(saisies, chemin_sai)
    apres = (json.dumps(registre, sort_keys=True), json.dumps(saisies, sort_keys=True))
    resultat["modifie"] = web_modifie or avant != apres or (resultat.get("ff") or {}).get("statut") in ("frais", "indisponible")
    resultat["saisies_overrides"] = sm.vers_overrides(saisies, registre)
    r = resultat["remplissage"]
    log.info("Tableau macro : remplissage Actuel %.0f %% · Précédent %.0f %% · Prévision %.0f %%",
             r["Actuel"]["taux_pct"], r["Précédent"]["taux_pct"], r["Prévision"]["taux_pct"])
    return resultat
