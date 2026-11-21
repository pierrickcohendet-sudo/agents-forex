"""Lot V12 : introductions des 8 dossiers de moteurs, rédigées par le modèle à partir des FAITS calculés en Python
(core/dossiers_moteurs.py), avec Groq en secours et un secours Python en phrases complètes. Un seul appel groupé par jour
(étiquette « moteurs:intros ») ; les textes acceptés sont gardés pour la journée (data/cache/moteurs_intros.json) et
reverifiés à chaque run horaire. Contrôle : chaque nombre doit venir des faits, vocabulaire d'ordre interdit, chaque
moteur cité par son nom (jamais « engrenage N » seul)."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

from core import controle_texte as ct
from core import dossiers_moteurs as dm
from core import noms_moteurs as nm

log = logging.getLogger(__name__)
CACHE = Path("data") / "cache" / "moteurs_intros.json"
REMISE_A_ZERO_UTC = "08:15"   # remise à zéro du quota gratuit Gemini (minuit heure du Pacifique) + marge, comme le run complet
ENGRENAGE_SEUL = re.compile(r"\bengrenages?\s*(n°\s*)?\d\b", re.I)


def faits(d: dict) -> dict:
    """Faits compacts par moteur, seuls autorisés dans le texte."""
    sortie = {}
    for k, m in d["moteurs"].items():
        e = m["etat"]
        sortie[k] = {"moteur": m["nom"], "question": m["question"], "etat": e["etat"], "thermometre": e.get("libelle"), "valeur": e.get("valeur"),
                     "date": e.get("date"), "direction": e.get("direction"), "seuil": e.get("note"), "incoherence": e.get("incoherence"),
                     "soutient": [x["devise"] for x in m["devises"] if x["effet"] == "soutien"],
                     "pese_sur": [x["devise"] for x in m["devises"] if x["effet"] == "pression"],
                     "pourquoi": {x["devise"]: x["pourquoi"][:220] for x in m["devises"] if x["effet"] in ("soutien", "pression")},
                     "chiffres_cles": [{"libelle": t["libelle"], "valeur": t["texte"], "variation": t["variation"], "date": t["date"]} for t in m["analyse"]["chiffres_cles"][:6]],
                     "titres_du_jour": [t["titre"] for t in m["actualites"][:4]],
                     "a_venir": [{"date": a["date"], "heure": a["heure"], "devise": a["devise"], "evenement": a["evenement"]} for a in m["agenda"] if not a["passe"]][:3]}
    return sortie


def prompt(f: dict) -> str:
    return ("Tu rédiges en français l'introduction de chacun des 8 dossiers de moteurs du marché des changes, à partir des FAITS "
            "ci-dessous (calculés en Python). Pour chaque moteur : un paragraphe de 3 à 5 phrases qui dit ce qui se passe, avec les "
            "chiffres et leurs dates, quelles devises sont soutenues ou sous pression et pourquoi, et ce qui arrive ensuite. "
            "Règles impératives (un texte qui les enfreint est rejeté) : AUCUN nombre absent des faits ; chaque phrase cite un chiffre "
            "ou une date ; cite le moteur par son nom ; jamais « engrenage » suivi d'un numéro ; aide à la décision seulement, jamais "
            "« entrée », « stop », « objectif », « LONG » ni « SHORT », aucun ordre d'achat ou de vente. "
            "Réponds STRICTEMENT en JSON : {\"1\": \"paragraphe\", …, \"8\": \"paragraphe\"}.\nFAITS :\n" + json.dumps(f, ensure_ascii=False))


def controler(textes: dict[str, str], f: dict) -> dict[str, list[str]]:
    rejets = ct.verifier_textes({k: [v] for k, v in textes.items() if v}, f)
    for k, v in textes.items():
        r = rejets.setdefault(k, []) if (not v or ENGRENAGE_SEUL.search(v) or nm.nom(int(k)).lower() not in v.lower()) else None
        if r is not None:
            if not v:
                r.append("texte vide")
            if v and ENGRENAGE_SEUL.search(v):
                r.append("« engrenage N » sans le nom du moteur")
            if v and nm.nom(int(k)).lower() not in v.lower():
                r.append(f"le moteur n'est pas cité par son nom ({nm.nom(int(k))})")
    return {k: v for k, v in rejets.items() if v}


def rediger(d: dict, llm=None, secours=None) -> tuple[dict, dict]:
    """-> ({n: (texte, par)} acceptés, journal)."""
    from core.llm import definir_etiquette, libelle_modele, dernier_modele, extraire_json
    f = faits(d)
    p = prompt(f)
    reponse, par, erreur = None, None, None
    if llm is not None:
        try:
            definir_etiquette("moteurs:intros")
            reponse, par = llm.appeler_llm(p), libelle_modele(dernier_modele()) or "modèle principal"
        except Exception as exc:  # noqa: BLE001 — 503, 429, quota : secours
            erreur = f"modèle principal : {type(exc).__name__} : {str(exc)[:160]}"
    if reponse is None and secours is not None and secours.disponible():
        try:
            reponse, par = secours.appeler(p), f"secours {secours.nom}"
        except Exception as exc:  # noqa: BLE001
            erreur = (erreur + " ; " if erreur else "") + f"secours : {type(exc).__name__} : {str(exc)[:160]}"
    journal = {"par": par, "erreur": erreur, "acceptes": [], "rejetes": {}}
    if reponse is None:
        return {}, journal
    try:
        brut = extraire_json(reponse)
        textes = {str(k): str((brut or {}).get(str(k)) or "").strip() for k in range(1, 9)}
    except Exception as exc:  # noqa: BLE001
        journal["erreur"] = f"réponse illisible : {str(exc)[:120]}"
        return {}, journal
    rejets = controler(textes, f)
    ok = {}
    for k, v in textes.items():
        if k in rejets:
            journal["rejetes"][k] = rejets[k][:3]
        else:
            ok[k] = (v, par)
            journal["acceptes"].append(k)
    return ok, journal


def doit_rediger(ancien: dict, jour: str, maintenant: datetime, n_intros: int, remise: str = REMISE_A_ZERO_UTC) -> tuple[bool, str]:
    """Fonction pure : faut-il solliciter le modèle (ou Groq) pour les introductions ? Une tentative par période : avant la
    remise à zéro du quota (00:00 -> 08:15 UTC) et après ; week-end compris. Jamais si les 8 introductions du jour existent."""
    if n_intros >= 8:
        return False, "8 introductions du jour déjà rédigées"
    tentatives = [t for t in (ancien.get("tentatives") or []) if str(t).startswith(jour)] if ancien.get("date") == jour else []
    if ancien.get("date") == jour and ancien.get("tente") == jour and not tentatives:
        tentatives = [f"{jour}T00:00:00+00:00"]          # ancien format (lot V12) : une tentative sans heure
    seuil = f"{jour}T{remise}:00+00:00"
    apres = maintenant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00") >= seuil
    if not tentatives:
        return True, "première tentative du jour"
    if apres and all(t < seuil for t in tentatives):
        return True, f"version du jour en rédaction Python : nouvelle tentative après la remise à zéro du quota ({remise} UTC)"
    return False, "déjà tentée sur cette période (" + ("après" if apres else "avant") + f" la remise à zéro de {remise} UTC)"


def bilan(intros: dict) -> dict:
    """{modele, groq, python} : numéros des moteurs selon le rédacteur de leur introduction."""
    groq = sorted(k for k, (_, par) in intros.items() if "groq" in str(par).lower() or str(par).startswith("secours"))
    modele = sorted(k for k in intros if k not in groq)
    return {"modele": modele, "groq": groq, "python": sorted(set(str(n) for n in range(1, 9)) - set(intros))}


def ligne_bilan(b: dict) -> str:
    return f"Moteurs : {len(b['modele'])} introduction{'s' if len(b['modele']) > 1 else ''} par le modèle, {len(b['groq'])} par Groq, {len(b['python'])} en Python"


def executer(racine: str | Path, config: dict, llm=None, maintenant: datetime | None = None, secours=None,
             fabrique=None) -> dict | None:
    """`fabrique()` -> (llm, secours) : crée le modèle et le secours seulement si une tentative est due (passages horaires)."""
    """Calcule les dossiers, reprend les textes du jour encore valides, appelle le modèle une fois par jour si besoin, écrit le JSON."""
    racine = Path(racine)
    maintenant = maintenant or datetime.now(timezone.utc)
    d = dm.calculer(racine / "docs" / "data", racine / "data" / "cache", None, maintenant)
    f = faits(d)
    cache = racine / CACHE
    try:
        ancien = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ancien = {}
    intros = {}
    if ancien.get("date") == d["date"]:     # textes du jour : gardés s'ils passent encore le contrôle avec les faits du run
        textes = {k: v["texte"] for k, v in (ancien.get("textes") or {}).items()}
        rejets = controler(textes, f)
        intros = {k: (v["texte"], v["par"]) for k, v in ancien["textes"].items() if k not in rejets}
    journal = None
    remise = ((config.get("llm") or {}).get("remise_a_zero_quota_utc")) or REMISE_A_ZERO_UTC
    faire, motif = doit_rediger(ancien, d["date"], maintenant, len(intros), remise)
    if faire and llm is None and secours is None and fabrique is not None:
        try:
            llm, secours = fabrique()
        except Exception as exc:  # noqa: BLE001
            log.warning("introductions des moteurs : modèle non initialisé (%s)", exc)
    if faire and (llm is not None or secours is not None):
        log.info("Introductions des moteurs : %s", motif)
        nouveaux, journal = rediger(d, llm, secours)
        journal["motif"] = motif
        intros.update({k: v for k, v in nouveaux.items() if k not in intros})
        tentatives = ([t for t in (ancien.get("tentatives") or []) if str(t).startswith(d["date"])] if ancien.get("date") == d["date"] else [])
        tentatives.append(maintenant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"date": d["date"], "tentatives": tentatives, "journal": journal,
                                         "textes": {k: {"texte": t, "par": p} for k, (t, p) in intros.items()}}, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as exc:
            log.warning("cache des introductions non écrit : %s", exc)
    sortie = dm.ecrire(racine, None, intros, maintenant)
    if sortie is not None:
        b = bilan(intros)
        sortie["redaction"] = {**b, "journal": journal or (ancien.get("journal") if ancien.get("date") == d["date"] else None), "ligne": ligne_bilan(b)}
        (racine / "docs" / "data" / "moteurs_dossiers.json").write_text(json.dumps(sortie, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        log.info("Dossiers des 8 moteurs : %s", ligne_bilan(b))
    return sortie
