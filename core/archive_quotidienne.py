"""Archive quotidienne des valeurs que les sources ne gardent pas (calculées chaque jour, sans LLM).

data/archives/indicateurs_quotidiens.json : une entrée par jour (remplacée si le pipeline repasse dans la
journée), purge au-delà de 6 ans : environ 300 octets par jour, au plus ~650 Ko.
Valeurs : cohérence des engrenages, surprise globale, titres par canal géopolitique, écart de l'USD à sa
MM200 et volatilité 20 j de l'USD. Elles alimentent les mini-courbes, puis les percentiles quand l'archive
aura assez de profondeur.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

RACINE = Path(__file__).resolve().parent.parent
CHEMIN = RACINE / "data" / "archives" / "indicateurs_quotidiens.json"
CONSERVATION_JOURS = 6 * 366


def _tuile(dossiers: dict, numero: str, ident: str) -> dict:
    return next((t for t in (dossiers.get(numero) or {}).get("tuiles") or [] if t.get("id") == ident), {})


def extraire(engrenages: dict) -> dict:
    """Valeurs du jour à archiver, lues dans les dossiers déjà calculés (None si absentes)."""
    coh = _tuile(engrenages, "1", "coherence")
    canaux = {t["libelle"].replace("Titres : ", ""): t.get("valeur") for t in (engrenages.get("6") or {}).get("tuiles") or []
              if str(t.get("id", "")).startswith("canal_")}
    usd7 = next((l["cellules"] for l in (engrenages.get("7") or {}).get("lignes") or [] if l.get("devise") == "USD"), {})
    return {"coherence_alignes": coh.get("valeur"),
            "coherence_libelle": coh.get("texte"),
            "surprise_globale": _tuile(engrenages, "1", "surprise_globale").get("valeur"),
            "titres_par_canal": canaux or None,
            "usd_ecart_mm200": (usd7.get("ecart_mm200") or {}).get("valeur"),
            "usd_volatilite_20j": (usd7.get("volatilite") or {}).get("valeur")}


def charger(chemin: Path | str = CHEMIN) -> dict:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "jours": {}}


def archiver(engrenages: dict, chemin: Path | str = CHEMIN, jour: date | None = None) -> dict:
    """Ajoute ou remplace l'entrée du jour (les valeurs None d'un passage n'écrasent pas une valeur déjà connue)."""
    jour = jour or date.today()
    archive = charger(chemin)
    jours = archive.setdefault("jours", {})
    nouvelles = extraire(engrenages)
    ancienne = jours.get(jour.isoformat()) or {}
    jours[jour.isoformat()] = {k: (v if v is not None else ancienne.get(k)) for k, v in nouvelles.items()}
    limite = (jour - timedelta(days=CONSERVATION_JOURS)).isoformat()
    archive["jours"] = {d: v for d, v in sorted(jours.items()) if d >= limite}
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    Path(chemin).write_text(json.dumps(archive, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    return archive


def serie(archive: dict, cle: str, sous_cle: str | None = None, jours: int = 120) -> list[list]:
    limite = (date.today() - timedelta(days=jours)).isoformat()
    sortie = []
    for d, v in sorted((archive.get("jours") or {}).items()):
        x = (v or {}).get(cle)
        if sous_cle is not None:
            x = (x or {}).get(sous_cle)
        if d >= limite and isinstance(x, (int, float)):
            sortie.append([d, x])
    return sortie


def completer_tuiles(engrenages: dict, archive: dict) -> None:
    """Mini-courbes des tuiles jusque-là « non historisées », depuis l'archive (avec sa profondeur réelle)."""
    debut = min((archive.get("jours") or {}), default=None)
    note = f"archivé chaque jour depuis le {debut[8:10]}/{debut[5:7]}/{debut[:4]}" if debut else None
    cibles = [("1", "coherence", serie(archive, "coherence_alignes")),
              ("1", "surprise_globale", serie(archive, "surprise_globale"))]
    for t in (engrenages.get("6") or {}).get("tuiles") or []:
        if str(t.get("id", "")).startswith("canal_"):
            cibles.append(("6", t["id"], serie(archive, "titres_par_canal", t["libelle"].replace("Titres : ", ""))))
    for numero, ident, points in cibles:
        t = _tuile(engrenages, numero, ident)
        if not t:
            continue
        t["courbe"] = {"points": points, "periode": "depuis le début de l'archive quotidienne",
                       "raison": None if len(points) >= 2 else f"archive trop récente ({len(points)} {'jour' if len(points) < 2 else 'jours'}) : {note}"}
        if t.get("percentile_5a") is None:
            t["raison_percentile"] = f"archive quotidienne trop courte pour un percentile ({len(points)} {'jour' if len(points) < 2 else 'jours'})"
