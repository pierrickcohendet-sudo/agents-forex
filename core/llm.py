"""Interface LLM abstraite : appeler_llm(prompt) -> str.

Gemini est le fournisseur PRINCIPAL. Groq est câblé comme fournisseur de
SECOURS derrière la MÊME interface FournisseurLLM (aucun appelant n'a besoin
de savoir qu'un repli existe), mais DÉSACTIVÉ PAR DÉFAUT depuis le 2026-08-24
— voir le verdict ci-dessous. Pour ajouter un 3e fournisseur : une nouvelle
classe FournisseurLLM enregistrée dans FOURNISSEURS, rien d'autre à toucher.

Historique de l'incident (2026-08-23/24) :
1. Repli Groq systématiquement en 413 dès la 2e devise. Cause confirmée par
   la doc officielle Groq (console.groq.com/docs/rate-limits) : tier gratuit
   openai/gpt-oss-20b/120b plafonné à 8 000 TPM, fenêtre GLISSANTE. Le seul
   prompt système (connaissances/, ~18 500 car. ≈ 4 600 tokens) consommait
   déjà plus de la moitié du budget. Fix : _reduire_systeme (fichiers entiers
   par priorité, jamais coupés en plein milieu).
2. Le 413 a PERSISTÉ malgré ce fix : le "message" (contexte par devise —
   mémoire 7 jours, news, catalogue de sources qui grossit toute la journée)
   fait à lui seul 70-90 000 caractères (~17 500-22 500 tokens estimés),
   plusieurs fois le budget total, indépendamment de tout ce qu'on fait sur
   le système. Le prompt de l'agent critique (rapport condensé entier, pas de
   système du tout par construction) atteint 88 000+ caractères à lui seul.
3. VERDICT après calcul : même avec une réduction générique agressive du
   message (_reduire_message ci-dessous), redescendre sous 8 000 TPM pour ces
   appels lourds exige de tronquer si fort (mémoire à 1 jour, catalogue à 1-2
   sources) que le contenu résultant n'a plus la richesse d'une analyse
   tracée. Le tier gratuit Groq n'est structurellement PAS dimensionné pour
   les appels lourds de ce pipeline (analyse par devise, état du monde,
   critique). Décision : llm.secours.actif = false par défaut dans
   config.yaml. Le mécanisme reste implémenté, testé et activable (tier payant
   Groq, usage ponctuel, ou si le volume de contexte baisse structurellement)
   — Gemini seul, avec sa dégradation propre existante (retries, --completer,
   statut "analyse indisponible"/"non_evalue" jamais menteur), reste le filet
   de sécurité réel.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

# Estimation grossière (pas de tokenizer réel installé) : ~4 caractères par
# token pour un mélange français/anglais/JSON — suffisant pour du diagnostic
# de dimensionnement, pas une garantie exacte. Tous les budgets ci-dessous
# sont exprimés en TOKENS (l'unité réellement limitée par les fournisseurs) ;
# la conversion en caractères ne sert qu'aux opérations de découpe de texte.
CARACTERES_PAR_TOKEN_ESTIME = 4


def _estimer_tokens(texte: str) -> int:
    return max(1, len(texte) // CARACTERES_PAR_TOKEN_ESTIME) if texte else 0


def _budget_car(budget_tokens: int) -> int:
    return budget_tokens * CARACTERES_PAR_TOKEN_ESTIME


# Journal LÉGER des appels LLM du run (taille estimée + modèle réellement
# utilisé), écrit dans rapport["meta"]["appels_llm"] par l'orchestrateur :
# permet de suivre d'un jour à l'autre si les prompts regrossissent, sans
# avoir à lire les logs GitHub Actions. Un échec est noté (ok=False) : ce sont
# souvent les plus gros prompts qui échouent.
_JOURNAL_APPELS: list[dict] = []
_ETIQUETTE_COURANTE: list[str] = [""]      # ex. « analyse:EUR », « synthese:EUR » (posée par l'appelant)
_DERNIER_MODELE_OK: list[str | None] = [None]


def reinitialiser_journal() -> None:
    _JOURNAL_APPELS.clear()
    _DERNIER_MODELE_OK[0] = None


def journal_appels() -> list[dict]:
    return [dict(e) for e in _JOURNAL_APPELS]


def definir_etiquette(etiquette: str) -> None:
    """Étiquette attachée aux prochaines entrées du journal (distingue analyse,
    synthèse, critique… dans meta.appels_llm)."""
    _ETIQUETTE_COURANTE[0] = etiquette


def dernier_modele() -> str | None:
    """Identifiant du modèle qui a réellement produit la dernière réponse réussie
    (principal ou secours) — à lire juste après l'appel."""
    return _DERNIER_MODELE_OK[0]


def libelle_modele(modele: str | None) -> str | None:
    """'gemini-3.5-flash-lite' -> 'Flash-Lite 3.5' ; 'gemini-3.5-flash' -> 'Flash 3.5'."""
    if not modele:
        return None
    m = re.match(r"gemini-?(\d+(?:\.\d+)?)?-?(flash-lite|flash|pro)?(?:-(latest|preview))?", modele)
    if not m or not m.group(2):
        return modele
    famille = {"flash-lite": "Flash-Lite", "flash": "Flash", "pro": "Pro"}[m.group(2)]
    return f"{famille} {m.group(1)}" if m.group(1) else famille


def attribution_modele() -> dict | None:
    """{'modele': id, 'libelle': 'Flash-Lite 3.5'} du dernier appel réussi, ou None."""
    modele = dernier_modele()
    return {"modele": modele, "libelle": libelle_modele(modele)} if modele else None


def _noter_appel(modele: str, systeme: str | None, prompt: str, ok: bool) -> None:
    tok_sys, tok_msg = _estimer_tokens(systeme or ""), _estimer_tokens(prompt)
    entree = {
        "heure": datetime.now(timezone.utc).strftime("%H:%M"), "modele": modele,
        "tokens_systeme": tok_sys, "tokens_message": tok_msg,
        "tokens_total": tok_sys + tok_msg, "ok": ok}
    if _ETIQUETTE_COURANTE[0]:
        entree["etiquette"] = _ETIQUETTE_COURANTE[0]
    _JOURNAL_APPELS.append(entree)
    if ok:
        _DERNIER_MODELE_OK[0] = modele


class QuotaJournalierEpuise(RuntimeError):
    """Quota gratuit PAR JOUR du modèle épuisé (429 « PerDay ») ou plafond local atteint :
    inutile de réessayer pendant des heures — le disjoncteur s'ouvre aussitôt."""


class QuotaAtteint(RuntimeError):
    """Tous les modèles de la chaîne sont indisponibles faute de quota du jour : les sections
    concernées sont marquées « indisponible : quota atteint » et retentées au passage suivant
    (sans appel réseau tant que les quotas ne sont pas remis à zéro)."""


MESSAGE_QUOTA_ATTEINT = "indisponible : quota atteint (retentée dès la remise à zéro du quota gratuit)"


def _delai_reprise_s(rep_texte: str) -> float | None:
    """Délai avant remise à zéro du quota, lu dans la réponse 429 (RetryInfo « 42460s » ou
    « Please retry in 11h47m40.5s »)."""
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', rep_texte)
    if m:
        return float(m.group(1))
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", rep_texte)
    if m and any(m.groups()):
        h, mn, sec = (float(x) if x else 0.0 for x in m.groups())
        return h * 3600 + mn * 60 + sec
    return None


class RegistreQuotas:
    """Compteur d'appels (requêtes HTTP envoyées) par modèle et par jour, persistant dans un
    fichier d'état (versionné avec data/cache : partagé entre les runs GitHub Actions).
    Remis à zéro au changement de jour UTC ; un 429 « PerDay » marque en plus le modèle épuisé
    jusqu'à l'heure de reprise donnée par l'API (source de vérité). Un plafond local atteint
    n'est JAMAIS dépassé : l'appel est refusé avant l'envoi."""

    def __init__(self, chemin, plafonds: dict[str, int]):
        from pathlib import Path as _P
        self.chemin = _P(chemin) if chemin else None
        self.plafonds = {m: int(q) for m, q in plafonds.items()}
        self.donnees: dict = {"date": "", "modeles": {}}
        self._charger()

    @staticmethod
    def _maintenant() -> datetime:
        return datetime.now(timezone.utc)

    def _charger(self) -> None:
        brut = {}
        if self.chemin and self.chemin.exists():
            try:
                brut = json.loads(self.chemin.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                brut = {}
        jour = self._maintenant().date().isoformat()
        modeles = brut.get("modeles", {}) if isinstance(brut, dict) else {}
        if brut.get("date") != jour:   # nouveau jour : compteurs à zéro, épuisements encore valides conservés
            modeles = {m: {"appels": 0, "epuise_jusqu_a": v.get("epuise_jusqu_a")} for m, v in modeles.items()}
        self.donnees = {"date": jour, "modeles": modeles}

    def _sauver(self) -> None:
        if not self.chemin:
            return
        try:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            self.chemin.write_text(json.dumps(self.donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as exc:
            log.warning("Fichier de quota LLM non écrit (%s) : compteur gardé en mémoire", exc)

    def _entree(self, modele: str) -> dict:
        return self.donnees["modeles"].setdefault(modele, {"appels": 0, "epuise_jusqu_a": None})

    def epuise(self, modele: str) -> bool:
        jusqu = self._entree(modele).get("epuise_jusqu_a")
        if jusqu:
            try:
                return self._maintenant() < datetime.fromisoformat(jusqu)
            except ValueError:
                return False
        return False

    def autoriser(self, modele: str) -> bool:
        if self.epuise(modele):
            return False
        plafond = self.plafonds.get(modele)
        return plafond is None or self._entree(modele)["appels"] < plafond

    def compter(self, modele: str) -> None:
        self._entree(modele)["appels"] += 1
        self._sauver()

    def marquer_epuise(self, modele: str, delai_s: float | None) -> None:
        e = self._entree(modele)
        delai = delai_s if delai_s else max(
            (datetime.combine(self._maintenant().date() + timedelta(days=1), datetime.min.time(),
                              tzinfo=timezone.utc) - self._maintenant()).total_seconds(), 60)
        e["epuise_jusqu_a"] = (self._maintenant() + timedelta(seconds=delai)).isoformat(timespec="seconds")
        plafond = self.plafonds.get(modele)
        if plafond:
            e["appels"] = max(e["appels"], plafond)
        self._sauver()

    def etat(self) -> dict:
        return {"date": self.donnees["date"],
                "modeles": {m: {"appels_aujourdhui": self._entree(m)["appels"], "plafond_jour": self.plafonds.get(m),
                                "epuise_jusqu_a": self._entree(m).get("epuise_jusqu_a")}
                            for m in self.plafonds}}


class FournisseurLLM(ABC):
    @abstractmethod
    def appeler_llm(self, prompt: str, systeme: str | None = None) -> str:
        """Envoie le prompt, retourne le texte brut de la réponse."""


class _FournisseurAvecCadence(FournisseurLLM):
    """Base partagée par les fournisseurs HTTP à tier gratuit limité en
    requêtes/minute : pause minimale entre deux appels + backoff réel sur 429
    (Retry-After de l'API si fourni, sinon la valeur configurée), jamais un
    retry quasi immédiat. Un seul nouvel essai après un 429."""

    def __init__(self, pause_min_s: float = 7.0, backoff_429_s: float = 30.0):
        self.pause_min_s = float(pause_min_s)
        self.backoff_429_s = float(backoff_429_s)
        self._dernier_appel = 0.0

    def _attendre_cadence(self) -> None:
        ecart = time.monotonic() - self._dernier_appel
        if ecart < self.pause_min_s:
            time.sleep(self.pause_min_s - ecart)
        self._dernier_appel = time.monotonic()

    def _delai_apres_429(self, rep: requests.Response) -> float:
        try:
            return max(float(rep.headers.get("Retry-After", 0)), self.backoff_429_s)
        except (TypeError, ValueError):
            return self.backoff_429_s

    def _loguer_taille(self, nom_fournisseur: str, systeme: str | None, prompt: str) -> None:
        tok_systeme, tok_prompt = _estimer_tokens(systeme or ""), _estimer_tokens(prompt)
        log.info("%s : prompt ≈ %d tokens estimés (système ≈ %d + message ≈ %d) — %d car. au total",
                 nom_fournisseur, tok_systeme + tok_prompt, tok_systeme, tok_prompt,
                 len(systeme or "") + len(prompt))


class FournisseurGemini(_FournisseurAvecCadence):
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent"

    def __init__(self, modele: str, temperature: float = 0.2, registre_quotas: "RegistreQuotas | None" = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.registre_quotas = registre_quotas
        self.cle = os.environ.get("GEMINI_API_KEY", "").strip()
        if not self.cle:
            raise RuntimeError("GEMINI_API_KEY absente de l'environnement (voir .env.example)")
        self.modele = modele
        self.temperature = temperature

    def _poster(self, corps: dict) -> requests.Response:
        if self.registre_quotas is not None:
            # Plafond gratuit JAMAIS dépassé : refus AVANT l'envoi (y compris pour le nouvel essai).
            if not self.registre_quotas.autoriser(self.modele):
                raise QuotaJournalierEpuise(f"plafond gratuit du jour atteint pour {self.modele} (compteur local)")
            self.registre_quotas.compter(self.modele)
        self._attendre_cadence()
        # Clé en HEADER, jamais en query string : les erreurs HTTP embarquent
        # l'URL dans leur message et finissent dans les logs.
        return requests.post(
            self.URL.format(modele=self.modele),
            headers={"x-goog-api-key": self.cle},
            json=corps,
            timeout=180,
        )

    def appeler_llm(self, prompt: str, systeme: str | None = None) -> str:
        try:
            texte = self._appeler(prompt, systeme)
        except Exception:
            _noter_appel(self.modele, systeme, prompt, False)
            raise
        _noter_appel(self.modele, systeme, prompt, True)
        return texte

    def _appeler(self, prompt: str, systeme: str | None) -> str:
        self._loguer_taille("Gemini", systeme, prompt)
        corps = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "responseMimeType": "application/json",
            },
        }
        if systeme:
            corps["system_instruction"] = {"parts": [{"text": systeme}]}
        rep = self._poster(corps)
        if rep.status_code == 429 and "PerDay" in rep.text:
            # Quota gratuit journalier (ex. 20 requêtes/jour/modèle) : le délai de
            # reprise se compte en heures, attendre 30 s n'aurait aucun sens.
            if self.registre_quotas is not None:
                self.registre_quotas.marquer_epuise(self.modele, _delai_reprise_s(rep.text))
            raise QuotaJournalierEpuise(
                f"quota gratuit journalier épuisé pour {self.modele} (HTTP 429, requêtes/jour)")
        if rep.status_code == 429:
            attente = self._delai_apres_429(rep)
            log.warning("Gemini 429 (limite de requêtes/minute) : attente de %.0f s "
                        "avant un unique nouvel essai", attente)
            time.sleep(attente)
            rep = self._poster(corps)
        elif rep.status_code == 503:
            # UNAVAILABLE (modèle surchargé côté Google, doc officielle : retry
            # conseillé) — même traitement que le 429 : un backoff réel, un
            # unique nouvel essai, jamais une boucle.
            log.warning("Gemini 503 (service temporairement indisponible) : attente de %.0f s "
                        "avant un unique nouvel essai", self.backoff_429_s)
            time.sleep(self.backoff_429_s)
            rep = self._poster(corps)
        rep.raise_for_status()
        donnees = rep.json()
        try:
            return donnees["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Réponse Gemini inattendue : {json.dumps(donnees)[:500]}") from exc


# Marqueur exact posé par agent_strategiste.charger_connaissances() entre
# deux fichiers concaténés — utilisé ici pour réduire le prompt système SANS
# jamais couper un fichier en plein milieu (uniquement des fichiers entiers,
# retirés/gardés par priorité).
_MARQUEUR_FICHIER = re.compile(r"\n\n# ===== (.+?) =====\n\n")

# Si connaissances_prioritaires n'est pas configuré : ordre par défaut, les
# fichiers les plus directement utiles au score/scénarios d'abord, les plus
# accessoires (exemples illustratifs, glossaire de définitions) en dernier —
# donc les premiers sacrifiés si le budget est dépassé.
PRIORITE_CONNAISSANCES_DEFAUT = [
    "banques_centrales.md", "indicateurs_fondamentaux.md",
    "indicateurs_techniques.md", "cas_particuliers.md",
    "exemples_annotes.md", "glossaire.md",
]


def _reduire_systeme(systeme: str, budget_car: int, priorite: list[str]) -> str:
    """Réduit le prompt système à budget_car caractères en gardant l'intro +
    les règles de sortie (texte avant le premier marqueur de fichier)
    intégralement, puis des fichiers connaissances/ ENTIERS un par un dans
    l'ordre de priorité donné, tant que ça tient dans le budget. Jamais de
    coupe en plein milieu d'un fichier (mieux vaut l'omettre que le tronquer
    à moitié, illisible pour le modèle)."""
    if len(systeme) <= budget_car:
        return systeme
    morceaux = _MARQUEUR_FICHIER.split(systeme)
    intro = morceaux[0]
    fichiers = dict(zip(morceaux[1::2], morceaux[2::2]))
    resultat = intro
    retenus, omis = [], []
    for nom in priorite:
        contenu = fichiers.get(nom)
        if contenu is None:
            continue
        bloc = f"\n\n# ===== {nom} =====\n\n{contenu}"
        if len(resultat) + len(bloc) <= budget_car:
            resultat += bloc
            retenus.append(nom)
        else:
            omis.append(nom)
    if omis:
        log.warning("Prompt système réduit pour le secours (budget %d car.) : "
                   "fichiers connaissances/ omis cette fois -> %s (gardés : %s)",
                   budget_car, ", ".join(omis), ", ".join(retenus) or "aucun")
    return resultat


# Marqueur générique : tous les prompts du pipeline suivent le motif
# "<instructions...>\n<bloc JSON final>" (agent_strategiste, agent_critique).
# ATTENTION : plusieurs prompts embarquent aussi un EXEMPLE de schéma JSON
# dans leurs instructions (ex. "Réponds selon ce schéma :\n{...}") — un
# marqueur naïf "premier :\n{ trouvé" s'y fait piéger. On essaie donc TOUS
# les candidats ":\n{" du texte, du DERNIER au premier, et on valide chacun
# par un vrai json.loads() jusqu'à la fin du texte : seul le bloc de
# données réel (toujours en toute fin de prompt) parse intégralement.
_MARQUEURS_JSON_CANDIDATS = re.compile(r":\s*\n(\{)")


def _retrecir_json(valeur, max_items: int, max_car: int, profondeur: int = 0):
    """Réduction récursive générique (ne connaît aucun nom de champ) : toute
    liste est tronquée à max_items éléments (avec une note du nombre omis),
    toute chaîne longue est coupée à max_car caractères. Produit toujours du
    JSON valide."""
    if profondeur > 6:
        return "…"
    if isinstance(valeur, dict):
        return {k: _retrecir_json(v, max_items, max_car, profondeur + 1) for k, v in valeur.items()}
    if isinstance(valeur, list):
        garde = valeur[:max_items]
        resultat = [_retrecir_json(v, max_items, max_car, profondeur + 1) for v in garde]
        if len(valeur) > max_items:
            resultat.append(f"…({len(valeur) - max_items} éléments omis pour tenir sous le budget Groq)")
        return resultat
    if isinstance(valeur, str) and len(valeur) > max_car:
        return valeur[:max_car] + "…"
    return valeur


# Paliers de réduction essayés dans l'ordre, du moins au plus agressif.
_PALIERS_REDUCTION_MESSAGE = ((8, 500), (4, 250), (2, 120), (1, 60))


def _reduire_message(prompt: str, budget_car: int) -> str:
    """Réduit le bloc JSON de données d'un prompt (mémoire, news, catalogue
    de sources...) pour tenir sous budget_car — GÉNÉRIQUE, ne connaît aucun
    nom de champ : fonctionne pour n'importe quel appelant (agent stratège,
    état du monde, agent critique) sans qu'aucun n'ait à savoir que Groq
    existe. Les instructions qui précèdent le JSON ne sont jamais touchées."""
    if len(prompt) <= budget_car:
        return prompt

    candidats = list(_MARQUEURS_JSON_CANDIDATS.finditer(prompt))
    for correspondance in reversed(candidats):  # le bloc réel est le DERNIER candidat du texte
        position = correspondance.start(1)
        try:
            donnees = json.loads(prompt[position:])
        except json.JSONDecodeError:
            continue  # un exemple de schéma dans les instructions, pas le vrai bloc — au suivant
        entete = prompt[:position]
        candidat = prompt
        for max_items, max_car in _PALIERS_REDUCTION_MESSAGE:
            retreci = _retrecir_json(donnees, max_items, max_car)
            candidat = entete + json.dumps(retreci, ensure_ascii=False)
            if len(candidat) <= budget_car:
                log.warning("Message réduit pour Groq (budget %d car.) : listes limitées à %d élément(s), "
                           "chaînes à %d car. -> %d car. final", budget_car, max_items, max_car, len(candidat))
                return candidat
        log.warning("Message réduit pour Groq au maximum (palier le plus agressif, encore %d car. > "
                   "budget %d) — envoyé quand même, le garde-fou total tranchera", len(candidat), budget_car)
        return candidat

    log.warning("Message réduit pour Groq : aucun bloc JSON de données détecté — coupe brute à %d car.",
               budget_car)
    return prompt[:budget_car] + "\n…(message tronqué pour tenir sous le budget Groq)"


class FournisseurGroq(_FournisseurAvecCadence):
    """Fournisseur de SECOURS (désactivé par défaut, voir le verdict en tête
    de module) — API compatible OpenAI (chat completions). Gratuit, clé sur
    console.groq.com. Tier gratuit confirmé (doc officielle, 2026-08-23) :
    8 000 TPM (tokens/minute, fenêtre glissante) pour openai/gpt-oss-20b et
    openai/gpt-oss-120b. Système ET message sont réduits (voir
    _reduire_systeme / _reduire_message) pour tenter de tenir sous ce
    budget — connaissances/ ET le contexte par devise dépassent chacun le
    budget total à eux seuls avant réduction."""

    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, modele: str, temperature: float = 0.2,
                 budget_tokens_systeme: int = 2000, budget_tokens_message: int = 3000,
                 budget_tokens_total_max: int = 5500,
                 connaissances_prioritaires: list[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.cle = os.environ.get("GROQ_API_KEY", "").strip()
        if not self.cle:
            raise RuntimeError("GROQ_API_KEY absente de l'environnement (voir .env.example)")
        self.modele = modele
        self.temperature = temperature
        self.budget_tokens_systeme = int(budget_tokens_systeme)
        self.budget_tokens_message = int(budget_tokens_message)
        self.budget_tokens_total_max = int(budget_tokens_total_max)
        self.connaissances_prioritaires = connaissances_prioritaires or PRIORITE_CONNAISSANCES_DEFAUT

    def _poster(self, corps: dict) -> requests.Response:
        self._attendre_cadence()
        return requests.post(
            self.URL,
            headers={"Authorization": f"Bearer {self.cle}"},
            json=corps,
            timeout=180,
        )

    def appeler_llm(self, prompt: str, systeme: str | None = None) -> str:
        systeme_reduit = (_reduire_systeme(systeme, _budget_car(self.budget_tokens_systeme),
                                           self.connaissances_prioritaires)
                          if systeme else systeme)
        prompt_reduit = _reduire_message(prompt, _budget_car(self.budget_tokens_message))
        self._loguer_taille("Groq", systeme_reduit, prompt_reduit)

        tokens_totaux = _estimer_tokens(systeme_reduit or "") + _estimer_tokens(prompt_reduit)
        if tokens_totaux > self.budget_tokens_total_max:
            # Refus AVANT envoi plutôt qu'un 413 opaque après coup : message
            # de diagnostic immédiat, aucun appel réseau gaspillé.
            raise RuntimeError(
                f"Prompt trop volumineux pour Groq même après réduction (≈ {tokens_totaux} tokens "
                f"estimés > budget {self.budget_tokens_total_max} tokens) — le contexte de cet appel "
                f"dépasse structurellement ce que le tier gratuit Groq peut absorber ce jour-là")

        messages = []
        if systeme_reduit:
            messages.append({"role": "system", "content": systeme_reduit})
        messages.append({"role": "user", "content": prompt_reduit})
        corps = {
            "model": self.modele,
            "messages": messages,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }
        rep = self._poster(corps)
        if rep.status_code == 429:
            attente = self._delai_apres_429(rep)
            log.warning("Groq 429 (limite de requêtes/minute) : attente de %.0f s "
                        "avant un unique nouvel essai", attente)
            time.sleep(attente)
            rep = self._poster(corps)
        rep.raise_for_status()
        donnees = rep.json()
        try:
            return donnees["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Réponse Groq inattendue : {json.dumps(donnees)[:500]}") from exc


class FournisseurAvecSecours(FournisseurLLM):
    """Enveloppe un fournisseur PRINCIPAL et un fournisseur de SECOURS
    derrière la MÊME interface appeler_llm : aucun appelant du pipeline n'a à
    savoir qu'un repli existe (ni que le secours réduit son propre prompt —
    ça reste interne à FournisseurGroq). Le principal est TOUJOURS tenté en
    premier ; le secours n'est sollicité QUE si le principal échoue sur cet
    appel précis (jamais l'inverse, jamais en parallèle)."""

    def __init__(self, principal: FournisseurLLM, secours: FournisseurLLM,
                nom_principal: str, nom_secours: str,
                disjoncteur_actif: bool = False, seuil_echecs: int = 3):
        self.principal = principal
        self.secours = secours
        self.nom_principal = nom_principal
        self.nom_secours = nom_secours
        # Disjoncteur : après `seuil_echecs` échecs CONSÉCUTIFS du principal (ou dès
        # un quota journalier épuisé), il est ignoré pour le reste du run — plus
        # d'attente de 30 s + retry sur un modèle qui ne répond pas. L'instance
        # vit le temps d'un run : au run suivant, le principal est retenté.
        self.disjoncteur_actif = bool(disjoncteur_actif)
        self.seuil_echecs = max(1, int(seuil_echecs))
        self.echecs_consecutifs = 0
        self.ouvert = False
        self.cause_ouverture: str | None = None
        self.appels_principal_ignores = 0
        self.appels_total = 0
        self.ouvert_a_l_appel: int | None = None

    def etat_disjoncteur(self) -> dict:
        """État loggé dans rapport['meta']['disjoncteur']."""
        return {"actif": self.disjoncteur_actif, "principal": self.nom_principal,
                "secours": self.nom_secours, "seuil_echecs": self.seuil_echecs,
                "ouvert": self.ouvert, "cause": self.cause_ouverture,
                "ouvert_a_l_appel": self.ouvert_a_l_appel,
                "echecs_consecutifs_fin_de_run": self.echecs_consecutifs,
                "appels_total": self.appels_total,
                "appels_principal_ignores": self.appels_principal_ignores}

    def _echec_principal(self, exc: Exception, msg: str) -> None:
        self.echecs_consecutifs += 1
        quota = isinstance(exc, QuotaJournalierEpuise)
        if self.disjoncteur_actif and not self.ouvert and (quota or self.echecs_consecutifs >= self.seuil_echecs):
            self.ouvert = True
            self.ouvert_a_l_appel = self.appels_total
            self.cause_ouverture = ("quota journalier épuisé" if quota else
                                    f"{self.echecs_consecutifs} échecs consécutifs") + f" — {msg[:120]}"
            log.warning("DISJONCTEUR OUVERT : %s ignoré pour le reste de ce run (%s) — appels "
                        "directs sur %s ; il sera retenté au prochain run",
                        self.nom_principal, self.cause_ouverture, self.nom_secours)

    def appeler_llm(self, prompt: str, systeme: str | None = None) -> str:
        self.appels_total += 1
        if self.ouvert:
            self.appels_principal_ignores += 1
            return self._appeler_secours(prompt, systeme, "disjoncteur ouvert")
        try:
            texte = self.principal.appeler_llm(prompt, systeme=systeme)
            self.echecs_consecutifs = 0
            return texte
        except Exception as exc_principal:  # noqa: BLE001
            msg_principal = masquer_secrets(str(exc_principal))
            self._echec_principal(exc_principal, msg_principal)
            log.warning("Fournisseur %s en échec (%s) — repli sur %s pour cet appel",
                       self.nom_principal, msg_principal, self.nom_secours)
            return self._appeler_secours(prompt, systeme, msg_principal)

    def _appeler_secours(self, prompt: str, systeme: str | None, msg_principal: str) -> str:
        try:
            return self.secours.appeler_llm(prompt, systeme=systeme)
        except Exception as exc_secours:  # noqa: BLE001
            msg_secours = masquer_secrets(str(exc_secours))
            log.error("Fournisseur de secours %s également en échec : %s",
                     self.nom_secours, msg_secours)
            raise RuntimeError(
                f"{self.nom_principal} et {self.nom_secours} (secours) en échec : "
                f"{msg_principal} | {msg_secours}") from exc_secours


class FournisseurChaine(FournisseurLLM):
    """Liste ORDONNÉE de modèles (config llm.modeles) : l'appel va au premier modèle disponible.
    Un modèle dont le quota du jour est atteint (compteur local ou 429 « PerDay ») ou dont le
    disjoncteur est ouvert (N échecs consécutifs pendant ce run) est SAUTÉ sans attente.
    Si aucun modèle n'est disponible : QuotaAtteint (quota) ou RuntimeError (autres échecs)."""

    def __init__(self, maillons: list[tuple[str, FournisseurLLM]], registre: RegistreQuotas | None,
                 disjoncteur_actif: bool = True, seuil_echecs: int = 3):
        self.maillons = [{"modele": nom, "fournisseur": f, "echecs": 0, "ouvert": False, "cause": None,
                          "ouvert_a_l_appel": None, "ignores": 0, "tentatives": 0, "reussites": 0}
                         for nom, f in maillons]
        self.registre = registre
        self.disjoncteur_actif = bool(disjoncteur_actif)
        self.seuil_echecs = max(1, int(seuil_echecs))
        self.appels_total = 0

    def _echec(self, m: dict, exc: Exception, msg: str) -> None:
        m["echecs"] += 1
        quota = isinstance(exc, QuotaJournalierEpuise)
        if self.disjoncteur_actif and not m["ouvert"] and (quota or m["echecs"] >= self.seuil_echecs):
            m["ouvert"], m["ouvert_a_l_appel"] = True, self.appels_total
            m["cause"] = ("quota journalier épuisé" if quota else f"{m['echecs']} échecs consécutifs") + f" — {msg[:120]}"
            log.warning("DISJONCTEUR OUVERT : %s ignoré pour le reste de ce run (%s)", m["modele"], m["cause"])

    def appeler_llm(self, prompt: str, systeme: str | None = None) -> str:
        self.appels_total += 1
        raisons: list[str] = []
        autre_echec = False
        for m in self.maillons:
            if m["ouvert"]:
                m["ignores"] += 1
                raisons.append(f"{m['modele']} : ignoré (disjoncteur)")
                autre_echec = autre_echec or "quota" not in (m["cause"] or "")
                continue
            if self.registre is not None and not self.registre.autoriser(m["modele"]):
                m["ignores"] += 1
                raisons.append(f"{m['modele']} : quota du jour atteint")
                continue
            m["tentatives"] += 1
            try:
                texte = m["fournisseur"].appeler_llm(prompt, systeme=systeme)
                m["echecs"] = 0
                m["reussites"] += 1
                if raisons:
                    log.warning("Appel servi par %s après : %s", m["modele"], " | ".join(raisons))
                return texte
            except Exception as exc:  # noqa: BLE001
                msg = masquer_secrets(str(exc))
                self._echec(m, exc, msg)
                raisons.append(f"{m['modele']} : {msg[:100]}")
                autre_echec = autre_echec or not isinstance(exc, QuotaJournalierEpuise)
                log.warning("Modèle %s en échec (%s) — essai du modèle suivant", m["modele"], msg[:150])
        if not autre_echec:
            raise QuotaAtteint(f"{MESSAGE_QUOTA_ATTEINT} — " + " | ".join(raisons))
        raise RuntimeError("tous les modèles de la chaîne en échec : " + " | ".join(raisons))

    def etat_disjoncteur(self) -> dict:
        return {"actif": self.disjoncteur_actif, "seuil_echecs": self.seuil_echecs,
                "ouvert": any(m["ouvert"] for m in self.maillons), "appels_total": self.appels_total,
                "modeles": [{"modele": m["modele"], "ouvert": m["ouvert"], "cause": m["cause"],
                             "ouvert_a_l_appel": m["ouvert_a_l_appel"], "echecs_consecutifs": m["echecs"],
                             "ignores": m["ignores"]} for m in self.maillons]}

    def etat_quota(self) -> dict:
        """meta.quota_llm : compteur du jour (fichier d'état) + appels de CE run, par modèle."""
        jour = self.registre.etat()["modeles"] if self.registre is not None else {}
        return {"date": (self.registre.etat()["date"] if self.registre is not None else None),
                "ordre": [m["modele"] for m in self.maillons],
                "modeles": {m["modele"]: {**jour.get(m["modele"], {}), "appels_ce_run": m["tentatives"],
                                          "reussites_ce_run": m["reussites"], "sauts_ce_run": m["ignores"]}
                            for m in self.maillons}}


FOURNISSEURS = {"gemini": FournisseurGemini, "groq": FournisseurGroq}

# Paramètres propres à certains fournisseurs (ex. budgets de réduction Groq) :
# transmis uniquement au fournisseur concerné, jamais aux autres (évite un
# TypeError sur un constructeur qui ne les attend pas).
_KWARGS_SPECIFIQUES = {
    "groq": ("budget_tokens_systeme", "budget_tokens_message", "budget_tokens_total_max",
            "connaissances_prioritaires"),
}


def _instancier(cfg: dict) -> FournisseurLLM:
    nom = cfg.get("fournisseur", "gemini")
    if nom not in FOURNISSEURS:
        raise ValueError(f"Fournisseur LLM inconnu : {nom} (disponibles : {list(FOURNISSEURS)})")
    kwargs = {
        "modele": cfg["modele"],
        "temperature": cfg.get("temperature", 0.2),
        "pause_min_s": cfg.get("pause_entre_appels_s", 7.0),
        "backoff_429_s": cfg.get("backoff_429_s", 30.0),
    }
    for cle in _KWARGS_SPECIFIQUES.get(nom, ()):
        if cle in cfg:
            kwargs[cle] = cfg[cle]
    return FOURNISSEURS[nom](**kwargs)


def _creer_chaine(config: dict) -> FournisseurChaine:
    cfg = config["llm"]
    entrees = cfg["modeles"]
    plafonds = {e["modele"]: int(e["quota_jour"]) for e in entrees if e.get("quota_jour") is not None}
    racine = Path(__file__).resolve().parent.parent
    chemin = racine / cfg.get("fichier_quota", "data/cache/quota_llm.json")
    registre = RegistreQuotas(chemin, plafonds)
    maillons = []
    for e in entrees:
        sous = {**cfg, "modele": e["modele"], **{k: v for k, v in e.items() if k not in ("quota_jour",)}}
        try:
            fournisseur = _instancier(sous)
        except (RuntimeError, ValueError) as exc:
            log.warning("Modèle %s non initialisé (%s) — ignoré dans la chaîne", e["modele"], exc)
            continue
        if isinstance(fournisseur, FournisseurGemini):
            fournisseur.registre_quotas = registre
        maillons.append((e["modele"], fournisseur))
    if not maillons:
        raise RuntimeError("llm.modeles : aucun modèle n'a pu être initialisé")
    disj = cfg.get("disjoncteur") or {}
    log.info("Chaîne de modèles : %s (quotas du jour : %s)", " -> ".join(m for m, _ in maillons),
             {m: registre.etat()["modeles"][m]["appels_aujourdhui"] for m in plafonds})
    return FournisseurChaine(maillons, registre, disjoncteur_actif=disj.get("actif", True),
                             seuil_echecs=disj.get("seuil_echecs_consecutifs", 3))


def creer_fournisseur(config: dict) -> FournisseurLLM:
    """Fournisseur principal (Gemini par défaut). Si llm.secours.actif est
    vrai dans config.yaml et que le fournisseur de secours s'initialise
    correctement (clé présente), retourne un FournisseurAvecSecours
    transparent ; sinon, retourne le principal seul (comportement inchangé).
    secours.actif = false par défaut depuis le 2026-08-24 (voir le verdict en
    tête de module) — Gemini seul est le filet de sécurité recommandé."""
    cfg = config["llm"]
    if cfg.get("modeles"):
        return _creer_chaine(config)
    principal = _instancier(cfg)

    cfg_secours = cfg.get("secours") or {}
    if not cfg_secours.get("actif", False):
        return principal
    try:
        secours = _instancier(cfg_secours)
    except (RuntimeError, ValueError) as exc:
        log.warning("Fournisseur de secours (%s) non initialisé (%s) — aucun repli disponible "
                   "aujourd'hui, %s seul sera utilisé",
                   cfg_secours.get("fournisseur", "?"), exc, cfg.get("fournisseur", "principal"))
        return principal
    nom_principal = f"{cfg.get('fournisseur', 'principal')}/{cfg.get('modele', '?')}"
    nom_secours = f"{cfg_secours.get('fournisseur', 'secours')}/{cfg_secours.get('modele', '?')}"
    log.info("Fournisseur de secours actif : %s -> repli sur %s en cas d'échec",
             nom_principal, nom_secours)
    cfg_disj = cfg.get("disjoncteur") or {}
    return FournisseurAvecSecours(principal, secours,
                                  nom_principal=nom_principal, nom_secours=nom_secours,
                                  disjoncteur_actif=cfg_disj.get("actif", False),
                                  seuil_echecs=cfg_disj.get("seuil_echecs_consecutifs", 3))


def extraire_json(texte: str) -> dict | list:
    """Parse le JSON d'une réponse LLM, en tolérant les clôtures ```json ... ```."""
    texte = texte.strip()
    texte = re.sub(r"^```(?:json)?\s*", "", texte)
    texte = re.sub(r"\s*```$", "", texte)
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        # Dernier recours : isoler le premier objet/tableau JSON complet.
        for ouvrant, fermant in (("{", "}"), ("[", "]")):
            debut = texte.find(ouvrant)
            fin = texte.rfind(fermant)
            if debut != -1 and fin > debut:
                return json.loads(texte[debut : fin + 1])
        raise
