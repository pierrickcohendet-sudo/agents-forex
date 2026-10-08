"""Tableau macro : base Notion « Tableau macro » + matrice du dashboard web.

Lignes = (indicateur, type de valeur : Actuel / Précédent / Prévision),
colonnes = les 9 devises. Toutes les valeurs viennent du registre permanent
(core/registre_macro.py) ; ce module ne calcule que l'affichage et la
synchronisation. Code pur, aucun LLM.

Priorité d'une cellule : fichier manuel du jour (data/overrides/AAAA-MM-JJ.json)
> saisie faite dans Notion (core/saisies_manuelles.py) > publication officielle
la plus récente — SAUF si la publication officielle est plus récente que la
saisie (elle la remplace, la saisie passe dans l'historique).

Notion : le pipeline mémorise, par cellule, le dernier texte qu'il y a lui-même
écrit (registre, `ecrit_notion`). Une cellule Notion différente de cette mémoire
et de ce qu'il écrirait aujourd'hui est une SAISIE MANUELLE : jamais écrasée.
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
SOURCE_LIGNE = "ForexFactory (page mois) · taux : config/FRED · ✍️ = saisie manuelle"
CHAMP_OVERRIDE = {"Actuel": "valeur", "Précédent": "precedent", "Prévision": "prevision"}


# ------------------------------------------------------------ résolution
def resoudre_cellule(case: dict, indicateur: str, devise: str, type_valeur: str, unite: str,
                     saisies: dict, overrides_jour: dict, jour: date) -> dict:
    """Cellule affichée + origine. `a_archiver` = saisie supplantée par une
    publication officielle plus récente (à archiver par l'appelant)."""
    officiel = rm.texte_officiel(case, type_valeur, unite)
    ov = ((overrides_jour or {}).get(devise) or {}).get(indicateur) or {}
    valeur_ov = ov.get(CHAMP_OVERRIDE[type_valeur])
    if valeur_ov not in (None, ""):
        return {"texte": f"{rm._fr(str(valeur_ov), unite)} {sm.MARQUEUR}", "manuel": True,
                "origine": "fichier_manuel", "surprise": None}
    cle_s = sm.cle(devise, indicateur, type_valeur)
    saisie = saisies.get("saisies", {}).get(cle_s)
    if saisie:
        publication = (case.get("actuel") or {}).get("date_pub")
        if publication and publication > saisie["saisi_le"]:
            return {"texte": officiel, "manuel": False, "origine": "officiel",
                    "surprise": (case.get("actuel") or {}).get("surprise") if type_valeur == "Actuel" else None,
                    "a_archiver": cle_s}
        return {"texte": f"{saisie['texte']} {sm.MARQUEUR}", "manuel": True,
                "origine": "saisie_notion", "surprise": None}
    surprise = (case.get("actuel") or {}).get("surprise") if type_valeur == "Actuel" else None
    return {"texte": officiel, "manuel": False, "origine": "officiel", "surprise": surprise}


def _etat(case: dict, type_valeur: str, texte: str) -> str:
    """valeur | explique (absent / consensus à venir) | vide (à initialiser)."""
    if case.get("statut") == "non_applicable":
        return "explique"
    if texte.startswith("n/d") or texte == "prochaine pub. n/d":
        return "vide"
    if texte.startswith("prochaine pub.") or texte.startswith("proj. BC"):
        return "explique"  # consensus pas encore publié, date de la prochaine publication connue
    return "valeur"


def construire_matrice(registre: dict, saisies: dict, overrides_jour: dict,
                       cfg_tm: dict, jour: date) -> dict:
    devises = cfg_tm["ordre_devises"]
    cellules: dict[str, dict] = {}
    archives: list[str] = []
    compte = {t: {"valeur": 0, "explique": 0, "vide": 0} for t in rm.TYPES}
    for indicateur, cfg_ind in cfg_tm["indicateurs"].items():
        cellules[indicateur] = {}
        for devise in devises:
            case = registre["cases"].get(rm.cle(indicateur, devise)) or {"statut": "a_initialiser"}
            cellules[indicateur][devise] = {}
            for t in rm.TYPES:
                c = resoudre_cellule(case, indicateur, devise, t, cfg_ind.get("unite", ""),
                                     saisies, overrides_jour, jour)
                if c.pop("a_archiver", None):
                    archives.append(sm.cle(devise, indicateur, t))
                c["etat"] = _etat(case, t, c["texte"])
                compte[t][c["etat"]] += 1
                if t == "Actuel" and not c["manuel"]:
                    a = case.get("actuel") or {}
                    c.update(valeur=a.get("valeur"), date=a.get("date_pub"), source=a.get("source"),
                             consensus=a.get("consensus"))
                cellules[indicateur][devise][t] = c
    remplissage = {t: {**n, "total": sum(n.values()),
                       "taux_pct": round(100 * (n["valeur"] + n["explique"]) / max(1, sum(n.values())), 1)}
                   for t, n in compte.items()}
    return {
        "maj": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "devises": devises,
        "types": list(rm.TYPES),
        "indicateurs": [{"id": k, "libelle": v["libelle"], "sens": v.get("sens", "normal")}
                        for k, v in cfg_tm["indicateurs"].items()],
        "cellules": cellules, "remplissage": remplissage, "source": SOURCE_LIGNE,
        "_a_archiver": archives,
    }


def ecrire_web(matrice: dict, dossier_docs: str | Path) -> None:
    sortie = {k: v for k, v in matrice.items() if not k.startswith("_")}
    chemin = Path(dossier_docs) / "data" / "tableau_macro.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ Notion
def _rt(texte: str) -> list[dict]:
    return [{"type": "text", "text": {"content": texte[:2000]}}] if texte else []


def _texte_rt(prop: dict | None) -> str:
    if not prop:
        return ""
    return "".join(t.get("plain_text", "") for t in prop.get("rich_text", [])).strip()


def _schema(devises: list[str]) -> dict:
    return {
        "Type": {"select": {"options": [{"name": "Actuel", "color": "green"},
                                        {"name": "Précédent", "color": "gray"},
                                        {"name": "Prévision", "color": "blue"}]}},
        "Ordre": {"number": {}},
        **{d: {"rich_text": {}} for d in devises},
        "Dernière mise à jour": {"date": {}},
        "Source": {"rich_text": {}},
    }


def _persister_id(chemin_config: str | Path | None, database_id: str) -> None:
    """Écrit l'ID dans config.yaml, sous tableau_macro (distinct de notion.database_id)."""
    if not chemin_config:
        log.warning("Chemin config inconnu : reporter tableau_macro.database_id: \"%s\"", database_id)
        return
    chemin = Path(chemin_config)
    texte = chemin.read_text(encoding="utf-8")
    debut = texte.find("\ntableau_macro:")
    nouveau, n = re.subn(r'(database_id:\s*)""', rf'\g<1>"{database_id}"', texte[debut:], count=1) \
        if debut != -1 else (texte, 0)
    if n:
        chemin.write_text(texte[:debut] + nouveau, encoding="utf-8")
        log.info("tableau_macro.database_id écrit dans %s", chemin)
    else:
        log.warning("`database_id: \"\"` introuvable sous tableau_macro — ajouter : \"%s\"", database_id)


def obtenir_base(client, config: dict, chemin_config: str | Path | None) -> tuple[str, bool] | None:
    """(database_id, créée_maintenant). Ordre : ID de config.yaml > base du même
    titre sous la page parente (anti-doublon) > création."""
    from agents.agent_redacteur import _extraire_page_id
    cfg_tm = config["tableau_macro"]
    existant = _extraire_page_id(str(cfg_tm.get("database_id", "")))
    if existant:
        return existant, False
    parent = _extraire_page_id(str(config.get("notion", {}).get("page_parent_id", "")))
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
                _persister_id(chemin_config, trouve)
                return trouve, False
        if not page.get("has_more"):
            break
        curseur = page["next_cursor"]
    base = client.databases.create(
        parent={"type": "page_id", "page_id": parent},
        title=[{"type": "text", "text": {"content": TITRE_BASE}}],
        icon={"type": "emoji", "emoji": "🌐"},
        initial_data_source={"properties": {"Indicateur": {"title": {}},
                                            **_schema(cfg_tm["ordre_devises"])}},
    )
    database_id = base["id"].replace("-", "")
    log.info("Base Notion « %s » créée (%s)", TITRE_BASE, database_id)
    _persister_id(chemin_config, database_id)
    return database_id, True


def _data_source(client, database_id: str, devises: list[str]) -> str:
    base = client.databases.retrieve(database_id)
    sources = base.get("data_sources", [])
    if not sources:
        raise RuntimeError(f"Base Notion {database_id} sans data source")
    ds_id = sources[0]["id"]
    existantes = client.data_sources.retrieve(ds_id).get("properties", {})
    manquantes = {n: s for n, s in _schema(devises).items() if n not in existantes}
    titre = next((n for n, p in existantes.items() if p.get("type") == "title"), None)
    if titre and titre != "Indicateur":
        manquantes[titre] = {"name": "Indicateur"}
    if manquantes:
        client.data_sources.update(ds_id, properties=manquantes)
        log.info("Schéma « %s » complété : %s", TITRE_BASE, ", ".join(sorted(manquantes)))
    return ds_id


def _lire_lignes(client, ds_id: str) -> dict[tuple[str, str], dict]:
    lignes: dict[tuple[str, str], dict] = {}
    curseur = None
    while True:
        res = client.data_sources.query(ds_id, start_cursor=curseur, page_size=100) if curseur \
            else client.data_sources.query(ds_id, page_size=100)
        for page in res["results"]:
            p = page["properties"]
            titre = "".join(t.get("plain_text", "") for t in p.get("Indicateur", {}).get("title", []))
            type_valeur = (p.get("Type", {}).get("select") or {}).get("name", "")
            lignes[(titre.strip(), type_valeur)] = page
        if not res.get("has_more"):
            return lignes
        curseur = res["next_cursor"]


def creer_vues(client, database_id: str, ds_id: str) -> list[str]:
    """Une vue par type (filtre sur Type, tri sur Ordre). Idempotent. Retourne
    les vues créées ; lève si l'API refuse (l'appelant documente alors la création manuelle)."""
    # views.list ne renvoie que des identifiants : le nom se lit via retrieve.
    existantes = {v.get("name") or client.views.retrieve(v["id"]).get("name")
                  for v in client.views.list(database_id=database_id).get("results", [])
                  if isinstance(v, dict)}
    creees = []
    for t in rm.TYPES:
        if t in existantes:
            continue
        client.views.create(database_id=database_id, data_source_id=ds_id, name=t, type="table",
                            filter={"property": "Type", "select": {"equals": t}},
                            sorts=[{"property": "Ordre", "direction": "ascending"}])
        creees.append(t)
    return creees


def detecter_saisies(lignes: dict, registre: dict, saisies: dict, overrides_jour: dict,
                     cfg_tm: dict, jour: date) -> int:
    """Compare chaque cellule Notion à (mémoire du pipeline, texte qu'il écrirait)
    et enregistre les écarts comme saisies manuelles. Une cellule vide n'est pas
    une saisie."""
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


LIBELLE_INDICE = "Indice de surprise 30 j"


def _upsert_ligne(client, ds_id: str, page: dict | None, libelle: str, type_valeur: str,
                  voulu: dict[str, str], ordre: int, jour: date, stats: dict) -> None:
    if page is None:
        props = {"Indicateur": {"title": _rt(libelle)},
                 "Type": {"select": {"name": type_valeur}}, "Ordre": {"number": ordre},
                 "Dernière mise à jour": {"date": {"start": jour.isoformat()}},
                 "Source": {"rich_text": _rt(SOURCE_LIGNE)},
                 **{d: {"rich_text": _rt(txt)} for d, txt in voulu.items()}}
        client.pages.create(parent={"type": "data_source_id", "data_source_id": ds_id},
                            properties=props)
        stats["lignes_creees"] += 1
        stats["cellules_ecrites"] += len(voulu)
        return
    diff = {d: txt for d, txt in voulu.items() if _texte_rt(page["properties"].get(d)) != txt}
    if not diff:
        return
    props = {d: {"rich_text": _rt(txt)} for d, txt in diff.items()}
    props["Dernière mise à jour"] = {"date": {"start": jour.isoformat()}}
    props["Source"] = {"rich_text": _rt(SOURCE_LIGNE)}
    props["Ordre"] = {"number": ordre}
    client.pages.update(page["id"], properties=props)
    stats["lignes_modifiees"] += 1
    stats["cellules_ecrites"] += len(diff)


def synchroniser(client, ds_id: str, lignes: dict, matrice: dict, registre: dict,
                 cfg_tm: dict, jour: date) -> dict:
    """Écrit uniquement les cellules qui diffèrent ; jamais de doublon de ligne.
    Une ligne en échec ne bloque pas les suivantes."""
    stats = {"lignes_creees": 0, "lignes_modifiees": 0, "cellules_ecrites": 0, "erreurs": 0}
    devises = cfg_tm["ordre_devises"]
    ordre = 0
    for indicateur, cfg_ind in cfg_tm["indicateurs"].items():
        for t in rm.TYPES:
            ordre += 1
            voulu = {d: matrice["cellules"][indicateur][d][t]["texte"] for d in devises}
            try:
                _upsert_ligne(client, ds_id, lignes.get((cfg_ind["libelle"], t)), cfg_ind["libelle"],
                              t, voulu, ordre, jour, stats)
                _memoriser(registre, indicateur, t, voulu)
                time.sleep(PAUSE_ECRITURE_S)
            except Exception as exc:  # noqa: BLE001
                stats["erreurs"] += 1
                log.error("Tableau macro Notion : ligne %s / %s en échec : %s",
                          cfg_ind["libelle"], t, masquer_secrets(str(exc))[:200])
    # Indice de surprise (calculé, jamais saisi à la main) : ligne « Actuel » en fin de tableau.
    if matrice.get("indice_surprise"):
        try:
            voulu = {d: matrice["indice_surprise"][d]["texte"] for d in devises}
            _upsert_ligne(client, ds_id, lignes.get((LIBELLE_INDICE, "Actuel")), LIBELLE_INDICE,
                          "Actuel", voulu, 99, jour, stats)
        except Exception as exc:  # noqa: BLE001
            stats["erreurs"] += 1
            log.error("Tableau macro Notion : ligne indice de surprise en échec : %s",
                      masquer_secrets(str(exc))[:200])
    return stats


def _memoriser(registre: dict, indicateur: str, type_valeur: str, voulu: dict[str, str]) -> None:
    for devise, texte in voulu.items():
        case = registre["cases"].setdefault(rm.cle(indicateur, devise), {
            "indicateur": indicateur, "devise": devise, "statut": "a_initialiser",
            "actuel": None, "precedent": None, "prevision": None, "historique": [], "ecrit_notion": {}})
        case.setdefault("ecrit_notion", {})[type_valeur] = texte


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
    """Collecte ForexFactory si un créneau est dû, met à jour le registre, détecte
    les saisies manuelles Notion, publie Notion + web. Chaque sous-étape échoue
    isolément (les autres continuent). Retourne
    {modifie, saisies_overrides, remplissage, ff, notion}."""
    cfg_tm = config.get("tableau_macro") or {}
    if not cfg_tm.get("actif", True):
        return {"modifie": False, "saisies_overrides": {}}
    from agents import collecte_forexfactory_mois as ffm
    from core import overrides
    racine = Path(racine)
    donnees = racine / config["chemins"]["donnees"]
    chemin_reg, chemin_sai = donnees / "registre_macro.json", donnees / "overrides" / "saisies_notion.json"
    maintenant = maintenant or datetime.now(timezone.utc)
    jour = date.today()
    registre, saisies = rm.charger(chemin_reg), sm.charger(chemin_sai)
    avant = (json.dumps(registre, sort_keys=True), json.dumps(saisies, sort_keys=True))
    resultat: dict = {"ff": None, "notion": None}

    # 1. ForexFactory (page « mois ») si un créneau est dû
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

    # 3. Notion : lecture + détection des saisies manuelles
    import os
    from notion_client import Client
    cle = os.environ.get("NOTION_API_KEY", "").strip()
    notion_actif = avec_notion and config.get("notion", {}).get("actif", True) and (client_notion or cle)
    client, ds_id, lignes, cree = None, None, {}, False
    if notion_actif:
        try:
            client = client_notion or Client(auth=cle)
            base = obtenir_base(client, config, chemin_config)
            if base:
                database_id, cree = base
                ds_id = _data_source(client, database_id, cfg_tm["ordre_devises"])
                lignes = _lire_lignes(client, ds_id)
                nb = detecter_saisies(lignes, registre, saisies, overrides_jour, cfg_tm, jour)
                if nb:
                    resultat["saisies_detectees"] = nb
        except Exception as exc:  # noqa: BLE001
            client = None
            log.error("Tableau macro Notion (lecture) en échec : %s", masquer_secrets(str(exc))[:200])

    # 4. Contrôles de cohérence + indice de surprise (Python pur) puis matrice (priorités)
    from core import controles_macro
    controles = controles_macro.controler_registre(registre, cfg_tm, maintenant)
    indice = controles_macro.indice_surprise(registre, cfg_tm, jour)
    matrice = construire_matrice(registre, saisies, overrides_jour, cfg_tm, jour)
    matrice["indice_surprise"] = {d: {**v, "texte": controles_macro.texte_indice(v)}
                                  for d, v in indice.items()}
    matrice["anomalies"] = controles["anomalies"][:30]
    resultat["controles"], resultat["indice_surprise"] = controles, indice
    for cle_saisie in matrice.pop("_a_archiver", []):
        sm.archiver(saisies, cle_saisie, jour, "publication officielle plus récente")
    resultat["remplissage"] = matrice["remplissage"]

    # 5. Notion : écriture des seules cellules modifiées (+ vues à la création)
    if client and ds_id:
        try:
            resultat["notion"] = synchroniser(client, ds_id, lignes, matrice, registre, cfg_tm, jour)
            if cree:
                try:
                    creees = creer_vues(client, database_id, ds_id)
                    log.info("Vues « %s » créées : %s", TITRE_BASE, ", ".join(creees) or "aucune")
                except Exception as exc:  # noqa: BLE001
                    log.warning("Vues Notion non créées par l'API (%s) — voir README (2 clics par vue)",
                                masquer_secrets(str(exc))[:150])
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
