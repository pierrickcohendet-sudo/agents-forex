"""Rédaction du Rapport du jour par le modèle : 2 appels groupés au plus, après les engrenages (réserve de quota).

Appel 1 (« rapport:redaction ») : synthèse exécutive, bilan de la semaine passée, conclusion, reformulation de la lecture
du point de marché. Appel 2 (« rapport:analyse ») : scénarios haussier / baissier des 6 paires de la watchlist, ton
des communiqués de banques centrales (comparé au précédent, phrases citées), plan d'action lissé.
Le modèle ne reçoit que des faits calculés en Python. Contrôles Python : une phrase qui cite un chiffre absent des faits
ou un ordre d'achat / de vente est retirée ; un ton hors des 3 valeurs ou sans citation trouvée mot pour mot dans le
communiqué est rejeté. Sans modèle ou sans quota : les phrases Python restent (rien n'est inventé).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from agents.agent_dossier_hebdo import _valeurs, verifier_chiffres
from agents.agent_synthese import _retirer_ordres
from core.llm import (MESSAGE_QUOTA_ATTEINT, QuotaAtteint, attribution_modele, definir_etiquette, echec_transitoire, extraire_json,
                      repli_modele_suivant)
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)
TONS = ("plus restrictif", "inchangé", "plus accommodant")


def _propre(texte, autorises, limite=1500) -> tuple[str, list[str]]:
    t, ordres = _retirer_ordres(str(texte or "")[:limite])
    t, retirees = verifier_chiffres(t, autorises)
    notes = []
    if ordres or retirees:
        notes.append(f"{ordres + retirees} {'phrase retirée' if ordres + retirees < 2 else 'phrases retirées'} (ordre ou chiffre absent des faits)")
    return t.strip(), notes


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


MENTION_ENGRENAGES = "engrenages indisponibles"
CLES_PARTIE = {"1": ("synthese", "bilan", "conclusion", "lecture_marche"), "2": ("watchlist", "communiques", "plan")}


def faits_redaction(r: dict) -> dict:
    extra = {"engrenages": f"{MENTION_ENGRENAGES} (synthèse du modèle non faite aujourd'hui : thème et directions calculés "
                           "en Python seulement)"} if r.get("engrenages_indisponibles") else {}
    return {**extra, "theme": r.get("theme"), "lecture_marche": r["point_marche"]["lecture"],
            "point_marche": [{k: l[k] for k in ("actif", "variation_5j", "unite", "lecture")} for l in r["point_marche"]["lignes"] if l.get("niveau") is not None],
            "mecanismes": [{"libelle": m["libelle"], "chiffres": [c["chiffre"] for c in m["conditions"]]} for m in r["lecture"]["detectes"]],
            "scenarios": [{"titre": s["titre"], "statut": s["statut"], "mieux_confirme": s["mieux_confirme"]} for s in r["scenarios"]["liste"]],
            "catalyseurs": r["synthese"]["catalyseurs"], "biais": r["synthese"]["biais"],
            "bilan": {k: r["bilan"].get(k) for k in ("surprises", "forces", "marches", "basculements")}}


def faits_analyse(r: dict, textes_com: dict[str, tuple[str | None, str | None]]) -> dict:
    return {"watchlist": [{"paire": w["paire"], "libelle": w["libelle"], "haussier": w["scenario_haussier"]["conditions"],
                           "baissier": w["scenario_baissier"]["conditions"], "risque": w.get("risque")} for w in r["watchlist"]["top"]],
            "communiques": {d: {"actuel": (a or "")[:3000], "precedent": (p or "")[:3000]} for d, (a, p) in textes_com.items() if a and p},
            "plan": {k: r["plan"][k] for k in ("avant", "pendant", "cloture")}}


def _prompt1(faits: dict) -> str:
    return ("Tu rédiges le rapport FX du jour en français, ton de desk institutionnel, à partir des FAITS (calculés en Python). "
            "Réponds STRICTEMENT en JSON : {\"synthese\": \"3 à 5 phrases\", \"bilan\": \"4 phrases au plus\", "
            "\"conclusion\": \"2 phrases\", \"lecture_marche\": \"1 phrase qui reformule lecture_marche\"}. "
            "Utilise UNIQUEMENT les chiffres présents dans les faits. Les biais sont conditionnels : jamais une prédiction certaine, "
            "jamais une probabilité, jamais un ordre d'achat ou de vente, aucun niveau de prix cible.\nFAITS :\n"
            + json.dumps(faits, ensure_ascii=False))


def _prompt2(faits: dict) -> str:
    return ("Analyse en français, à partir des FAITS. Réponds STRICTEMENT en JSON : {\"watchlist\": {\"PAIRE\": {\"haussier\": "
            "\"1 phrase qui reformule les conditions haussières\", \"baissier\": \"1 phrase\"}}, \"communiques\": {\"DEVISE\": "
            "{\"ton\": \"plus restrictif | inchangé | plus accommodant\", \"citations\": [\"phrase copiée MOT POUR MOT du "
            "communiqué actuel\", \"...\"]}}, \"plan\": \"3 phrases qui lissent le plan (avant, pendant, clôture)\"}. Pour chaque "
            "communiqué, compare le texte actuel au précédent : plus inquiet de l'inflation ? de l'emploi ? fonction de réaction "
            "changée ? Cite 1 à 3 phrases exactes du communiqué actuel. Aucun chiffre absent des faits, aucune probabilité, "
            "aucun ordre d'achat ou de vente.\nFAITS :\n" + json.dumps(faits, ensure_ascii=False))


def rediger(r: dict, llm, textes_com: dict[str, tuple[str | None, str | None]] | None = None, tentatives: int = 2,
            parties: tuple[str, ...] = ("1", "2")) -> dict:
    """Textes validés du jour. Ne lève jamais. -> {date, statut, synthese?, bilan?, conclusion?, lecture_marche?,
    watchlist?, communiques?, plan?, controles, appels, parties_faites}.
    `parties` : « 1 » = rédaction (rapport:redaction), « 2 » = analyse (rapport:analyse) ; un complément ne rejoue que
    la partie manquante (V6.1-bis : le 04/11, l'analyse réussie faisait passer le rapport pour rédigé)."""
    sortie = {"date": r.get("date"), "statut": "indisponible", "controles": [], "appels": 0, "parties_faites": [],
              "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if r.get("engrenages_indisponibles"):
        sortie["mention_engrenages"] = MENTION_ENGRENAGES
    if llm is None:
        sortie["raison"] = "fournisseur LLM indisponible"
        return sortie
    textes_com = textes_com or {}
    f1 = faits_redaction(r)
    aut1 = _valeurs(f1, set())
    for etiquette, prompt, traiter in (("rapport:redaction", _prompt1(f1), "1"), ("rapport:analyse", None, "2")):
        if traiter not in parties:
            continue
        f2 = faits_analyse(r, textes_com) if traiter == "2" else None
        if traiter == "2":
            prompt = _prompt2(f2)
            aut = _valeurs(f2, set()) | aut1
        definir_etiquette(etiquette)
        brut = None
        for _ in range(max(1, tentatives)):
            try:
                sortie["appels"] += 1
                brut = extraire_json(llm.appeler_llm(prompt))
                if not isinstance(brut, dict):
                    raise ValueError("réponse non JSON")
                break
            except QuotaAtteint as exc:
                sortie.update({"raison": MESSAGE_QUOTA_ATTEINT, "quota_atteint": True, "detail_quota": masquer_secrets(str(exc))[:200]})
                return _finir(sortie)
            except Exception as exc:  # noqa: BLE001
                repli_modele_suivant(llm)
                brut = None
                sortie["controles"].append(f"{etiquette} : essai en échec ({masquer_secrets(str(exc))[:100]})")
        if not brut:
            continue
        sortie["parties_faites"].append(traiter)
        if traiter == "1":
            for cle in ("synthese", "bilan", "conclusion", "lecture_marche"):
                t, notes = _propre(brut.get(cle), aut1)
                sortie["controles"] += [f"{cle} : {n}" for n in notes]
                if t:
                    sortie[cle] = t
        else:
            wl = {}
            for p, v in (brut.get("watchlist") or {}).items():
                if p not in {w["paire"] for w in r["watchlist"]["top"]} or not isinstance(v, dict):
                    continue
                for sens in ("haussier", "baissier"):
                    t, notes = _propre(v.get(sens), aut, 400)
                    sortie["controles"] += [f"{p} {sens} : {n}" for n in notes]
                    if t:
                        wl.setdefault(p, {})[sens] = t
            sortie["watchlist"] = wl
            com = {}
            for d, v in (brut.get("communiques") or {}).items():
                actuel = (textes_com.get(d) or (None, None))[0]
                if not actuel or not isinstance(v, dict):
                    continue
                ton = str(v.get("ton") or "").strip().lower()
                cits = [c for c in (v.get("citations") or [])[:3] if isinstance(c, str) and len(c) > 15 and _norm(c) in _norm(actuel)]
                if ton not in TONS or not cits:
                    sortie["controles"].append(f"communiqué {d} : ton rejeté ({'ton hors des 3 valeurs' if ton not in TONS else 'aucune citation trouvée mot pour mot'})")
                    continue
                com[d] = {"ton": ton, "citations": cits}
            sortie["communiques"] = com
            t, notes = _propre(brut.get("plan"), aut, 900)
            sortie["controles"] += [f"plan : {n}" for n in notes]
            if t:
                sortie["plan"] = t
    if r.get("version") == "longue" and "1" in parties:   # lundi : 2 appels groupés de plus pour les 12 sections
        _rediger_long(r, llm, sortie, tentatives)
    return _finir(sortie)


def faits_long(r: dict, cles: list[str]) -> dict:
    """Phrase Python et contenu des blocs de chaque section longue : seuls faits que le modèle peut citer."""
    faits = {}
    for cle in cles:
        s = r.get(cle) or {}
        contenu = []
        for b in s.get("blocs") or []:
            contenu += [b.get("texte")] if b.get("texte") else []
            contenu += b.get("items") or [] if b.get("type") == "liste" else []
            contenu += [" | ".join(str(x) for x in l) for l in b.get("lignes") or []] if b.get("type") == "tableau" else []
            contenu += [f"{i.get('titre')} : {i.get('texte') or ''}" for i in b.get("items") or []] if b.get("type") == "cartes" else []
        faits[cle] = {"titre": s.get("titre"), "phrase": s.get("phrase_python"), "faits": [c for c in contenu if c][:30]}
    return faits


def _rediger_long(r: dict, llm, sortie: dict, tentatives: int) -> None:
    from core.rapport_long import SECTIONS_LONGUES
    sortie.setdefault("long", {})
    for etiquette, cles in (("rapport:long1", SECTIONS_LONGUES[:6]), ("rapport:long2", SECTIONS_LONGUES[6:])):
        faits = faits_long(r, cles)
        autorises = _valeurs(faits, set())
        prompt = ("Reformule en français, ton de desk institutionnel, la phrase de chaque section à partir de ses FAITS (calculés en "
                  "Python). Réponds STRICTEMENT en JSON : {\"sections\": {\"<clé>\": \"2 ou 3 phrases\"}}. Aucun chiffre absent des faits, "
                  "aucune probabilité, aucun ordre d'achat ou de vente, jamais « cause » pour une corrélation.\nFAITS :\n"
                  + json.dumps(faits, ensure_ascii=False))
        definir_etiquette(etiquette)
        brut = None
        for _ in range(max(1, tentatives)):
            try:
                sortie["appels"] += 1
                brut = extraire_json(llm.appeler_llm(prompt))
                if not isinstance(brut, dict) or not isinstance(brut.get("sections"), dict):
                    raise ValueError("réponse sans « sections »")
                break
            except QuotaAtteint:
                sortie["controles"].append(f"{etiquette} : quota atteint, phrases Python publiées")
                return
            except Exception as exc:  # noqa: BLE001
                repli_modele_suivant(llm)
                brut = None
                sortie["controles"].append(f"{etiquette} : essai en échec ({masquer_secrets(str(exc))[:100]})")
        for cle in cles:
            t, notes = _propre(((brut or {}).get("sections") or {}).get(cle), autorises, 700)
            sortie["controles"] += [f"{cle} : {n}" for n in notes]
            if t:
                sortie["long"][cle] = t


def statut_textes(sortie: dict) -> str:
    """ok : rédaction ET analyse reçues ; partiel : une seule des deux ; indisponible : aucune."""
    faites = set(sortie.get("parties_faites") or [])
    if {"1", "2"} <= faites:
        return "ok"
    return "partiel" if faites else "indisponible"


def parties_manquantes(textes: dict | None) -> tuple[str, ...]:
    faites = set((textes or {}).get("parties_faites") or [])
    if not faites and (textes or {}).get("statut") == "ok":   # textes écrits avant le lot V7 : déduits de leurs clés
        faites = {k for k, cles in CLES_PARTIE.items() if any((textes or {}).get(c) for c in cles)} or {"1", "2"}
    return tuple(p for p in ("1", "2") if p not in faites)


def fusionner(ancien: dict | None, nouveaux: dict) -> dict:
    """Garde la partie déjà rédigée (complément qui ne rejoue que la partie manquante)."""
    if not ancien:
        return nouveaux
    sortie = dict(nouveaux)
    for p in set(ancien.get("parties_faites") or []) - set(nouveaux.get("parties_faites") or []):
        for c in CLES_PARTIE[p]:
            if ancien.get(c) is not None:
                sortie[c] = ancien[c]
    sortie["parties_faites"] = sorted(set(ancien.get("parties_faites") or []) | set(nouveaux.get("parties_faites") or []))
    sortie["controles"] = (ancien.get("controles") or []) + (nouveaux.get("controles") or [])
    sortie["appels"] = int(ancien.get("appels", 0)) + int(nouveaux.get("appels", 0))
    if not nouveaux.get("redige_par") and ancien.get("redige_par"):
        sortie["redige_par"] = ancien["redige_par"]
    return _finir(sortie)


def _finir(sortie: dict) -> dict:
    statut = statut_textes(sortie)
    sortie["statut"] = statut
    if statut != "indisponible":
        sortie["redige_par"] = sortie.get("redige_par") or attribution_modele()
        if statut == "ok":
            sortie.pop("raison", None)
        else:
            sortie["raison"] = ("rédaction du rapport non faite (texte Python) : rejouée au complément suivant"
                                if "1" not in sortie["parties_faites"] else
                                "analyse (watchlist, plan) non faite : rejouée au complément suivant")
    elif not sortie.get("raison"):
        sortie["raison"] = "réponses du modèle inexploitables : phrases Python publiées"
    return sortie


HEURE_SEANCE_UTC = 7   # avant 07:00 UTC : passage hors séance, jamais d'appel au modèle pour le rapport


def engrenages_faits(docs: Path) -> bool:
    """Synthèse des 8 engrenages faite aujourd'hui par le modèle ? La rédaction du rapport ne l'attend jamais."""
    try:
        sg = json.loads((Path(docs) / "latest.json").read_text(encoding="utf-8")).get("synthese_globale") or {}
    except (OSError, ValueError):
        return False
    return ((sg.get("engrenages") or {}).get("statut")) == "ok"


def faut_rediger(textes: dict | None, maintenant: datetime, complet: bool) -> tuple[bool, str | None]:
    """(rédiger ?, raison sinon). (a) un « quota atteint » noté avant la remise à zéro (minuit Pacifique) ne bloque
    jamais la journée de quota suivante ; (b) un run complet rédige toujours tant que les textes ne sont pas « ok » ;
    (c) un passage hors séance (avant 07:00 UTC) n'appelle jamais le modèle."""
    from core.llm import jour_quota_google
    if (textes or {}).get("statut") == "ok" and not parties_manquantes(textes):
        return False, None
    if maintenant.hour < HEURE_SEANCE_UTC:
        return False, f"passage hors séance (avant {HEURE_SEANCE_UTC:02d}:00 UTC) : rédaction au run du matin"
    if complet:
        return True, None
    t = textes or {}
    if t.get("quota_atteint") and t.get("jour_quota") == jour_quota_google(maintenant).isoformat():
        return False, "quota du modèle atteint aujourd'hui (journée de quota en cours)"
    if int(t.get("essais", 0)) >= 3 and t.get("jour_quota") == jour_quota_google(maintenant).isoformat():
        return False, "3 essais déjà faits dans la journée de quota"
    return True, None


def executer(racine: str | Path, config: dict, llm, maintenant: datetime | None = None, complet: bool = False) -> dict | None:
    """Calcule le rapport (Python), archive les communiqués, rédige au plus une fois par jour (2 appels), écrit le fichier.
    complet=True : run complet (après les engrenages et les devises), qui retente toujours des textes manquants."""
    from core.llm import jour_quota_google
    from core import communiques, rapport_jour
    racine = Path(racine)
    docs = racine / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
    try:
        agenda_donnees = json.loads((docs / "agenda.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        agenda_donnees = None
    try:
        index = communiques.archiver(racine, config, agenda_donnees)
    except Exception as exc:  # noqa: BLE001
        log.warning("Communiqués non archivés : %s", exc)
        index = {}
    r = rapport_jour.calculer(racine, config, maintenant)
    try:
        ancien = json.loads((docs / "rapport_jour.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ancien = {}
    textes = ancien.get("textes") if ancien.get("date") == r["date"] else None
    instant = maintenant or datetime.now(timezone.utc)
    r["engrenages_indisponibles"] = not engrenages_faits(docs)
    rediger_, raison = faut_rediger(textes, instant, complet)
    if rediger_:
        textes_com = {d: communiques.textes_a_comparer(racine, index, d) for d in (index.get("par_devise") or {})}
        partiel = (textes or {}).get("statut") in ("ok", "partiel") and bool(parties_manquantes(textes))
        nouveaux = rediger(r, llm, textes_com, parties=parties_manquantes(textes) if partiel else ("1", "2"))
        if partiel:
            nouveaux = fusionner(textes, nouveaux)
        meme_jour = (textes or {}).get("jour_quota") == jour_quota_google(instant).isoformat()
        # Un échec seulement transitoire (503, 429, délai) ne compte pas comme un essai : rejoué au complément suivant
        transitoire = nouveaux.get("statut") != "ok" and all(echec_transitoire(llm, e) for e in ("rapport:redaction", "rapport:analyse"))
        nouveaux["essais"] = (int((textes or {}).get("essais", 0)) if meme_jour else 0) + (0 if transitoire else 1)
        nouveaux["echec_transitoire"] = transitoire
        nouveaux["jour_quota"] = jour_quota_google(instant).isoformat()
        textes = nouveaux
    if (textes or {}).get("statut") == "ok" and hasattr(llm, "marquer_fait"):
        llm.marquer_fait("rapport")   # réserve du rapport du jour libérée pour le reste (budget, core/llm.py)
    if not rediger_ and raison and (textes or {}).get("statut") != "ok":
        textes = {**(textes or {}), "statut": (textes or {}).get("statut") or "en_attente", "raison": raison,
                  "date": r["date"]}
    return rapport_jour.ecrire(racine, config, maintenant, textes)
