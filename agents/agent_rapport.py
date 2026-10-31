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
from core.llm import MESSAGE_QUOTA_ATTEINT, QuotaAtteint, attribution_modele, definir_etiquette, extraire_json, repli_modele_suivant
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


def faits_redaction(r: dict) -> dict:
    return {"theme": r.get("theme"), "lecture_marche": r["point_marche"]["lecture"],
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


def rediger(r: dict, llm, textes_com: dict[str, tuple[str | None, str | None]] | None = None, tentatives: int = 2) -> dict:
    """Textes validés du jour. Ne lève jamais. -> {date, statut, synthese?, bilan?, conclusion?, lecture_marche?,
    watchlist?, communiques?, plan?, controles, appels}."""
    sortie = {"date": r.get("date"), "statut": "indisponible", "controles": [], "appels": 0,
              "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if llm is None:
        sortie["raison"] = "fournisseur LLM indisponible"
        return sortie
    textes_com = textes_com or {}
    f1 = faits_redaction(r)
    aut1 = _valeurs(f1, set())
    for etiquette, prompt, traiter in (("rapport:redaction", _prompt1(f1), "1"), ("rapport:analyse", None, "2")):
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
    return _finir(sortie)


def _finir(sortie: dict) -> dict:
    if any(sortie.get(k) for k in ("synthese", "bilan", "conclusion", "watchlist", "communiques", "plan")):
        sortie.update({"statut": "ok", "redige_par": attribution_modele()})
        sortie.pop("raison", None)
    elif not sortie.get("raison"):
        sortie["raison"] = "réponses du modèle inexploitables : phrases Python publiées"
    return sortie


HEURE_SEANCE_UTC = 7   # avant 07:00 UTC : passage hors séance, jamais d'appel au modèle pour le rapport


def faut_rediger(textes: dict | None, maintenant: datetime, complet: bool) -> tuple[bool, str | None]:
    """(rédiger ?, raison sinon). (a) un « quota atteint » noté avant la remise à zéro (minuit Pacifique) ne bloque
    jamais la journée de quota suivante ; (b) un run complet rédige toujours tant que les textes ne sont pas « ok » ;
    (c) un passage hors séance (avant 07:00 UTC) n'appelle jamais le modèle."""
    from core.llm import jour_quota_google
    if (textes or {}).get("statut") == "ok":
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
    rediger_, raison = faut_rediger(textes, instant, complet)
    if rediger_:
        textes_com = {d: communiques.textes_a_comparer(racine, index, d) for d in (index.get("par_devise") or {})}
        nouveaux = rediger(r, llm, textes_com)
        meme_jour = (textes or {}).get("jour_quota") == jour_quota_google(instant).isoformat()
        nouveaux["essais"] = (int((textes or {}).get("essais", 0)) if meme_jour else 0) + 1
        nouveaux["jour_quota"] = jour_quota_google(instant).isoformat()
        textes = nouveaux
    elif raison and (textes or {}).get("statut") != "ok":
        textes = {**(textes or {}), "statut": (textes or {}).get("statut") or "en_attente", "raison": raison,
                  "date": r["date"]}
    return rapport_jour.ecrire(racine, config, maintenant, textes)
