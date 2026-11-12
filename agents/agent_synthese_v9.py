"""Rédaction de la Synthèse V9 (lot V9, partie C) : 4 appels groupés (sections 1–3, 4–7, 8–10, 11–13).

1. Le modèle principal (chaîne Gemini, core/llm.py, budget « rapport ») reformule, dans le ton du rapport modèle
   (docs/modele/rapport_2026-11-09.md), les faits calculés en Python (core/synthese_v9.py) et rien d'autre.
2. S'il est en panne (503, 429, quota, délai) : fournisseur de secours gratuit pour le texte seulement (Groq, clé
   GROQ_API_KEY, secret GitHub), même contrôle, budget séparé (data/cache/quota_secours_texte.json).
3. Contrôle Python (core/controle_texte.py) : un nombre absent des faits, une phrase sans fait chiffré ou daté, une
   formule creuse ou un ordre -> le texte de la section est rejeté et le texte Python (« rédaction automatique »)
   reste. Jamais de « texte: null ».
Sortie : docs/data/synthese.json et l'archive data/archives/synthese/AAAA-MM-JJ.json (onglet Archives).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

from core import controle_texte as ct
from core import synthese_v9 as sv

log = logging.getLogger(__name__)

GROUPES = [("1", ["s1", "s2", "s3"]), ("2", ["s4", "s5", "s6", "s7"]), ("3", ["s8", "s9", "s10"]), ("4", ["s11", "s12", "s13"])]
FAITS_GROUPE = {"1": ["s1", "s2", "s3", "prochain"], "2": ["s4", "s5", "s6", "s7"], "3": ["s8", "s9", "s10"], "4": ["s11", "s12", "s13", "s1"]}
TON = ("Ton du rapport modèle : phrases nettes de desk institutionnel, une idée par phrase, la cause puis la conséquence "
       "(publication -> taux -> devise), des conditions plutôt que des prédictions.")


def _lire(chemin: Path) -> dict:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def faits_groupe(s: dict, g: str) -> dict:
    f = s["faits"]
    sortie = {"date": s["date"]}
    for cle in FAITS_GROUPE[g]:
        x = f.get(cle)
        if cle == "s8" and isinstance(x, dict):
            x = {"devises": [{k: d.get(k) for k in ("rang", "devise", "score", "biais", "moteur", "j5")} for d in x.get("devises") or []]}
        if cle == "s1" and g == "4" and isinstance(x, dict):
            x = {k: x.get(k) for k in ("biais", "point_determinant")}
        sortie[cle] = ct.compacter(x, max_liste=9, max_txt=300)
    return sortie


def prompt(s: dict, g: str, ids: list[str]) -> str:
    faits = faits_groupe(s, g)
    ref = {sid: s["textes"].get(sid) for sid in ids}
    titres = {sec["id"]: sec["titre"] for sec in s["sections"]}
    return ("Tu rédiges en français une partie du rapport FX du jour, à partir des FAITS ci-dessous (calculés en Python). "
            f"{TON}\nRéponds STRICTEMENT en JSON : {{" + ", ".join(f'"{sid}": ["paragraphe", "paragraphe facultatif"]' for sid in ids) + "}.\n"
            "Sections : " + " ; ".join(f"{sid} = {titres.get(sid)}" for sid in ids) + ".\n"
            "Règles impératives (un texte qui les enfreint est rejeté par un contrôle automatique) :\n"
            "- 2 à 4 phrases par section ; CHAQUE phrase cite au moins un chiffre ou une date tirés des FAITS ;\n"
            "- AUCUN nombre absent des FAITS (pas de calcul nouveau, pas d'arrondi inventé, pas de probabilité) ;\n"
            "- aucune formule creuse (« addition des signaux », « dans un contexte incertain », « divers facteurs ») ;\n"
            "- jamais d'ordre d'achat ou de vente, de niveau d'entrée, de stop ni d'objectif : des conditions et des zones de repère ;\n"
            "- nombres à la française (virgule décimale, « % » précédé d'une espace).\n"
            "TEXTE DE RÉFÉRENCE (exact, à reformuler et enrichir avec les FAITS) :\n" + json.dumps(ref, ensure_ascii=False)
            + "\nFAITS :\n" + json.dumps(faits, ensure_ascii=False))


# ------------------------------------------------------------------ fournisseur de secours (texte seulement)
class Secours:
    """Groq, offre gratuite : texte seulement, budget séparé (quota_jour appels par jour UTC)."""

    def __init__(self, cfg: dict, racine: Path, fournisseur=None):
        self.cfg = cfg or {}
        self.chemin = Path(racine) / "data" / "cache" / "quota_secours_texte.json"
        self.quota = int(self.cfg.get("quota_jour", 8))
        self.raison = None
        self.f = fournisseur
        if self.f is None and self.cfg.get("actif", True):
            if not os.environ.get("GROQ_API_KEY", "").strip():
                self.raison = "clé GROQ_API_KEY absente (secret GitHub à créer pour activer le secours)"
            else:
                try:
                    from core.llm import FournisseurGroq
                    self.f = FournisseurGroq(modele=self.cfg.get("modele", "openai/gpt-oss-120b"), temperature=0.2,
                                             pause_min_s=float(self.cfg.get("pause_entre_appels_s", 30)), backoff_429_s=30.0,
                                             budget_tokens_systeme=200, budget_tokens_message=int(self.cfg.get("budget_tokens_message", 5000)),
                                             budget_tokens_total_max=int(self.cfg.get("budget_tokens_total_max", 6500)))
                except Exception as exc:  # noqa: BLE001
                    self.raison = f"secours non initialisé : {exc}"
        elif not self.cfg.get("actif", True):
            self.raison = "secours désactivé (config.yaml > synthese_v9.secours.actif)"
        self.nom = f"{self.cfg.get('fournisseur', 'groq')}/{self.cfg.get('modele', 'openai/gpt-oss-120b')}"

    def _compteur(self) -> dict:
        d = _lire(self.chemin)
        jour = datetime.now(timezone.utc).date().isoformat()
        return d if d.get("jour") == jour else {"jour": jour, "appels": 0}

    def disponible(self) -> bool:
        return self.f is not None and self._compteur()["appels"] < self.quota

    def appeler(self, texte: str) -> str:
        c = self._compteur()
        if c["appels"] >= self.quota:
            raise RuntimeError(f"budget du secours atteint ({c['appels']}/{self.quota} appels aujourd'hui)")
        c["appels"] += 1
        try:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            self.chemin.write_text(json.dumps(c), encoding="utf-8")
        except OSError:
            pass
        return self.f.appeler_llm(texte)


def _json(texte: str) -> dict:
    from core.llm import extraire_json
    d = extraire_json(texte)
    if not isinstance(d, dict):
        raise ValueError("réponse JSON attendue sous forme d'objet")
    return d


def _paragraphes(v) -> list[str]:
    if isinstance(v, str):
        v = [v]
    return [str(p).strip() for p in (v or []) if str(p).strip()][:3]


def rediger(s: dict, llm=None, secours: Secours | None = None, groupes=GROUPES, pause_s: float = 0.0) -> dict:
    """Remplace les textes Python par ceux du modèle quand ils passent le contrôle. -> journal de rédaction."""
    from core.llm import definir_etiquette, libelle_modele, dernier_modele
    journal = {"groupes": {}, "secours": {"nom": secours.nom if secours else None,
                                          "raison": None if secours and secours.f else (secours.raison if secours else "non configuré")}}
    for g, ids in groupes:
        p = prompt(s, g, ids)
        reponse, par, erreur = None, None, None
        if llm is not None:
            try:
                definir_etiquette(f"rapport:synthese_{g}")
                reponse, par = llm.appeler_llm(p), libelle_modele(dernier_modele()) or "modèle principal"
            except Exception as exc:  # noqa: BLE001 — 503, 429, quota, délai : secours
                erreur = f"modèle principal : {type(exc).__name__} : {str(exc)[:160]}"
        if reponse is None and secours is not None and secours.disponible():
            try:
                reponse, par = secours.appeler(p), f"secours {secours.nom}"
            except Exception as exc:  # noqa: BLE001
                erreur = (erreur + " ; " if erreur else "") + f"secours : {type(exc).__name__} : {str(exc)[:160]}"
        entree = {"par": par, "erreur": erreur, "acceptees": [], "rejetees": {}}
        if reponse is not None:
            try:
                d = _json(reponse)
                textes = {sid: _paragraphes(d.get(sid)) for sid in ids}
                rejets = ct.verifier_textes(textes, faits_groupe(s, g) | {"textes_python": {sid: s["textes"].get(sid) for sid in ids}})
                for sid in ids:
                    if sid in rejets:
                        entree["rejetees"][sid] = rejets[sid][:4]
                        continue
                    s["textes"][sid] = textes[sid]
                    s["redaction"][sid] = {"par": "modele", "libelle": par}
                    entree["acceptees"].append(sid)
            except Exception as exc:  # noqa: BLE001
                entree["erreur"] = (entree["erreur"] + " ; " if entree["erreur"] else "") + f"réponse illisible : {str(exc)[:120]}"
        journal["groupes"][g] = entree
        if pause_s and g != groupes[-1][0]:
            time.sleep(pause_s)
    return journal


def _textes_du_jour(ancien: dict, s: dict) -> int:
    """Reprend les textes du modèle déjà acceptés aujourd'hui s'ils passent encore le contrôle avec les faits du run."""
    if not ancien or ancien.get("date") != s["date"]:
        return 0
    n = 0
    for sid, r in (ancien.get("redaction") or {}).items():
        if r.get("par") != "modele" or sid not in s["textes"]:
            continue
        g = next(k for k, ids in GROUPES if sid in ids)
        textes = (ancien.get("textes") or {}).get(sid)
        if textes and not ct.verifier_textes({sid: textes}, faits_groupe(s, g) | {"textes_python": {sid: s["textes"].get(sid)}}):
            s["textes"][sid], s["redaction"][sid] = textes, r
            n += 1
    return n


def executer(racine: str | Path, config: dict, llm=None, maintenant: datetime | None = None, secours: Secours | None = None,
             docs: Path | None = None, cache: Path | None = None, ecrire: bool = True) -> dict | None:
    """Faits Python + rédaction ; écrit synthese.json et l'archive du jour. Ne lève jamais."""
    racine = Path(racine)
    maintenant = maintenant or datetime.now(timezone.utc)
    docs = Path(docs or racine / (config.get("publication_web") or {}).get("dossier_docs", "docs") / "data")
    cache = Path(cache or racine / "data" / "cache")
    try:
        from zoneinfo import ZoneInfo
        aujourd = maintenant.astimezone(ZoneInfo("Europe/Paris")).date()
        s = sv.calculer(docs, cache, aujourd, maintenant)
        repris = _textes_du_jour(_lire(docs / "synthese.json"), s)
        manquantes = [g for g, ids in GROUPES if any(s["redaction"][sid]["par"] != "modele" for sid in ids)]
        cfg = config.get("synthese_v9") or {}
        if secours is None:
            secours = Secours(cfg.get("secours") or {}, racine)
        journal = {"groupes": {}, "repris": repris}
        if manquantes and (llm is not None or secours is not None):
            journal.update(rediger(s, llm, secours, [(g, ids) for g, ids in GROUPES if g in manquantes],
                                   pause_s=float(cfg.get("pause_entre_groupes_s", 0))))
            journal["repris"] = repris
        s["journal_redaction"] = journal
        par = {r["libelle"] for r in s["redaction"].values() if r["par"] == "modele"}
        s["redige_par"] = sorted(par)
        s["redaction_automatique"] = [sid for sid, r in s["redaction"].items() if r["par"] != "modele"]
        if ecrire:
            docs.mkdir(parents=True, exist_ok=True)
            (docs / "synthese.json").write_text(json.dumps(s, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            arch = racine / "data" / "archives" / "synthese"
            arch.mkdir(parents=True, exist_ok=True)
            (arch / f"{s['date']}.json").write_text(json.dumps(s, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if s["redige_par"] and hasattr(llm, "marquer_fait") and not s["redaction_automatique"]:
            llm.marquer_fait("rapport")
        return s
    except Exception as exc:  # noqa: BLE001
        log.exception("synthèse V9 non écrite : %s", exc)
        return None
