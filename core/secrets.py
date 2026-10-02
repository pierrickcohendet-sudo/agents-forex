"""Masquage systématique des secrets dans tout texte destiné au log, au
cache, à un rapport ou à une publication (Notion/web).

Incident du 2026-09-25 : une clé Twelve Data corrompue (retour à la ligne
final dans le secret GitHub Actions) a fait échouer les appels en 401, et le
message d'erreur `requests` (qui embarque l'URL complète, paramètres de
requête compris) a été stocké tel quel dans data/cache/collecte_technique.json
— un fichier committé automatiquement par le pipeline dans un dépôt
probablement public. Toute chaîne construite à partir d'une exception réseau
DOIT passer par masquer_secrets() avant de quitter la fonction qui l'a
attrapée (stockage ET log — data/logs/ est gitignored mais l'hygiène doit
être la même partout, pas seulement là où c'est committé)."""
from __future__ import annotations

import re

# Paramètres de type clé/jeton tels qu'on les trouve dans une URL de requête
# (Twelve Data : apikey=, FRED : api_key=) ou un message générique
# (key=, token=). Valeur remplacée jusqu'au prochain séparateur.
_MOTIF_SECRET = re.compile(r'(?i)\b(apikey|api_key|key|token)=[^&\s"\'\)]+')


def masquer_secrets(texte: str) -> str:
    """Remplace la valeur de tout paramètre apikey=/api_key=/key=/token=
    (insensible à la casse) par ***. Idempotent, sûr sur une chaîne vide ou
    sans secret."""
    if not texte:
        return texte
    return _MOTIF_SECRET.sub(lambda m: f"{m.group(1)}=***", texte)
