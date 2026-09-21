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

import requests

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

    def __init__(self, modele: str, temperature: float = 0.2, **kwargs):
        super().__init__(**kwargs)
        self.cle = os.environ.get("GEMINI_API_KEY", "")
        if not self.cle:
            raise RuntimeError("GEMINI_API_KEY absente de l'environnement (voir .env.example)")
        self.modele = modele
        self.temperature = temperature

    def _poster(self, corps: dict) -> requests.Response:
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
        if rep.status_code == 429:
            attente = self._delai_apres_429(rep)
            log.warning("Gemini 429 (limite de requêtes/minute) : attente de %.0f s "
                        "avant un unique nouvel essai", attente)
            time.sleep(attente)
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
        self.cle = os.environ.get("GROQ_API_KEY", "")
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
                nom_principal: str, nom_secours: str):
        self.principal = principal
        self.secours = secours
        self.nom_principal = nom_principal
        self.nom_secours = nom_secours

    def appeler_llm(self, prompt: str, systeme: str | None = None) -> str:
        try:
            return self.principal.appeler_llm(prompt, systeme=systeme)
        except Exception as exc_principal:  # noqa: BLE001
            log.warning("Fournisseur %s en échec (%s) — repli sur %s pour cet appel",
                       self.nom_principal, exc_principal, self.nom_secours)
            try:
                return self.secours.appeler_llm(prompt, systeme=systeme)
            except Exception as exc_secours:  # noqa: BLE001
                log.error("Fournisseur de secours %s également en échec : %s",
                         self.nom_secours, exc_secours)
                raise RuntimeError(
                    f"{self.nom_principal} et {self.nom_secours} (secours) en échec : "
                    f"{exc_principal} | {exc_secours}") from exc_secours


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


def creer_fournisseur(config: dict) -> FournisseurLLM:
    """Fournisseur principal (Gemini par défaut). Si llm.secours.actif est
    vrai dans config.yaml et que le fournisseur de secours s'initialise
    correctement (clé présente), retourne un FournisseurAvecSecours
    transparent ; sinon, retourne le principal seul (comportement inchangé).
    secours.actif = false par défaut depuis le 2026-08-24 (voir le verdict en
    tête de module) — Gemini seul est le filet de sécurité recommandé."""
    cfg = config["llm"]
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
    log.info("Fournisseur de secours actif : %s -> repli sur %s en cas d'échec",
             cfg.get("fournisseur"), cfg_secours.get("fournisseur"))
    return FournisseurAvecSecours(principal, secours,
                                  nom_principal=cfg.get("fournisseur", "principal"),
                                  nom_secours=cfg_secours.get("fournisseur", "secours"))


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
