"""Fiabilité des données (lot V5, page « Santé ») : registre des sources, fraîcheur, certificats des chiffres.

Registre : config.yaml > sources (nom, ce qu'elle alimente, statut légal, fréquence normale, délai normal de publication).
Pour chaque source, la date de la dernière donnée est lue dans ce que le run a déjà collecté (historique 5 ans,
caches de collecte, registre macro, config) : aucune requête de plus, aucun LLM.
Fraîcheur : verte jusqu'à 2 fois la normale (fréquence + délai), orange au-delà, rouge au-delà de 4 fois ou sans date.
Certificats : pour chaque indicateur canonique (lot V5, étape 1), source, série, date de la valeur, heure de récupération,
contrôle croisé (une seule valeur publiée par tous les modules : ✓, sinon ⚠) et âge par rapport au calendrier normal.
Sortie : docs/data/sources.json.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

STATUTS = {"officielle": "Officielle", "api": "API sous licence gratuite", "flux": "Flux public", "extraction": "Extraction de page"}
FREQUENCES = {"quotidienne": 1, "hebdomadaire": 7, "mensuelle": 31, "trimestrielle": 92, "annuelle": 366, "collecte": 1}
LIBELLES_FREQ = {"quotidienne": "quotidienne (jours ouvrés)", "hebdomadaire": "hebdomadaire", "mensuelle": "mensuelle",
                 "trimestrielle": "trimestrielle", "annuelle": "annuelle", "collecte": "à chaque run"}
# Indicateurs certifiés : clé de l'historique canonique -> libellé, unité
CERTIFIES = {"vix": ("VIX", "pts"), "sp500": ("S&P 500", "pts"), "wti": ("Pétrole WTI", "$"), "brent": ("Pétrole Brent", "$"),
             "dollar_large": ("Indice dollar large (Fed)", "pts"), "indice_or": ("Indice or (proxy)", "pts"),
             "USD_2a": ("Rendement 2 ans US", "%"), "USD_10a": ("Rendement 10 ans US", "%"),
             "USD_taux_effectif": ("Taux effectif des fed funds", "%"), "USD_prime_terme": ("Prime de terme 10 ans US", "%"),
             "EUR_2a": ("Rendement 2 ans Allemagne", "%"), "EUR_10a": ("Rendement 10 ans Allemagne", "%"),
             "GBP_10a": ("Rendement 10 ans Royaume-Uni", "%"), "JPY_2a": ("Rendement 2 ans Japon", "%"),
             "JPY_10a": ("Rendement 10 ans Japon", "%"), "CAD_2a": ("Rendement 2 ans Canada", "%"),
             "CAD_10a": ("Rendement 10 ans Canada", "%"), "eia_stocks": ("Stocks de brut US (EIA)", "milliers de barils")}


# Calendrier réel de publication (certificat) : explique l'âge normal d'une valeur
CALENDRIERS = {
    "USD_2a": "Trésor US (H.15) via FRED : la valeur du jour J paraît le lendemain vers 20 h UTC ; le run de 08:15 voit J-2, "
              "les compléments horaires du soir rattrapent J-1.",
    "USD_10a": "Trésor US (H.15) via FRED : la valeur du jour J paraît le lendemain vers 20 h UTC ; le run de 08:15 voit J-2, "
               "les compléments horaires du soir rattrapent J-1.",
    "USD_taux_effectif": "Fed de New York via FRED : taux du jour J publié le lendemain matin (heure de New York).",
    "brent": "EIA via FRED : prix au comptant publié avec 1 à 2 jours ouvrés de retard (mise à jour FRED vers 17 h UTC).",
    "wti": "EIA via FRED : prix au comptant publié avec 1 à 2 jours ouvrés de retard (mise à jour FRED vers 17 h UTC).",
    "vix": "CBOE via FRED : la clôture du jour J paraît le soir même ou le lendemain matin.",
    "sp500": "S&P Dow Jones via FRED : la clôture du jour J paraît le lendemain matin.",
    "dollar_large": "Fed (H.10) via FRED : publication hebdomadaire, le lundi, des valeurs de la semaine précédente.",
    "USD_prime_terme": "Fed (Kim-Wright) via FRED : mise à jour hebdomadaire.",
    "eia_stocks": "EIA : rapport hebdomadaire le mercredi (semaine close le vendredi précédent).",
    "JPY_2a": "Ministère des Finances du Japon : fichier du mois en cours, mis à jour chaque jour ouvré de Tokyo.",
    "JPY_10a": "Ministère des Finances du Japon : fichier du mois en cours, mis à jour chaque jour ouvré de Tokyo.",
}


def _lire(chemin: Path):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def jours_ouvres(debut: date, fin: date) -> int:
    """Nombre de jours ouvrés (lundi-vendredi) écoulés de debut (exclu) à fin (inclus)."""
    if fin <= debut:
        return 0
    n, j = 0, debut
    while j < fin:
        j += timedelta(days=1)
        n += j.weekday() < 5
    return n


def fraicheur(derniere: str | None, frequence: str, retard: int, aujourdhui: date) -> dict:
    """{etat: vert|orange|rouge, age_jours, normal_jours, texte}. Quotidien : âge en jours ouvrés."""
    normal = FREQUENCES.get(frequence, 1) + int(retard or 0)
    if not derniere:
        return {"etat": "rouge", "age_jours": None, "normal_jours": normal, "texte": "aucune date de donnée"}
    try:
        d = date.fromisoformat(str(derniere)[:10])
    except ValueError:
        return {"etat": "rouge", "age_jours": None, "normal_jours": normal, "texte": f"date illisible ({derniere})"}
    ouvre = frequence in ("quotidienne", "collecte")
    age = jours_ouvres(d, aujourdhui) if ouvre else (aujourdhui - d).days
    unite = "j ouvré(s)" if ouvre else "j"
    etat = "vert" if age <= 2 * normal else "orange" if age <= 4 * normal else "rouge"
    texte = f"{age} {unite} (normal : {normal} {unite} au plus)" + ("" if etat == "vert" else
                                                                    " — plus de deux fois la normale" if etat == "orange" else
                                                                    " — plus de quatre fois la normale")
    return {"etat": etat, "age_jours": age, "normal_jours": normal, "texte": texte}


def _derniere_historique(historiques: dict, cles: list[str]) -> str | None:
    dates = []
    for c in cles:
        pts = (((historiques or {}).get("series") or {}).get(c) or {}).get("points") or []
        if pts:
            dates.append(str(pts[-1][0])[:10])
    return max(dates) if dates else None


def derniere_donnee(mesure: dict, ctx: dict) -> tuple[str | None, str | None]:
    """(date de la dernière donnée, heure de récupération) selon la règle `mesure` du registre."""
    cache = ctx["cache"]
    recup = None
    if mesure.get("historique"):
        d = _derniere_historique(ctx["historiques"], mesure["historique"])
        recup = (_lire(cache / "collecte_historiques.json") or {}).get("date")
        if d:
            return d, recup
    if mesure.get("cache"):
        brut = _lire(cache / f"collecte_{mesure['cache']}.json") or {}
        return brut.get("date"), brut.get("date")
    if mesure.get("cache_scrape"):
        brut = _lire(cache / f"scrape_{mesure['cache_scrape']}.json") or {}
        return brut.get("date"), brut.get("date")
    if mesure.get("flux"):
        brut = _lire(cache / "collecte_flux.json") or {}
        bloc = ((brut.get("donnees") or {}).get(mesure["flux"])) or {}
        dates = [v.get("date") for v in bloc.values() if isinstance(v, dict) and v.get("date")] if isinstance(bloc, dict) else []
        if isinstance(bloc, dict) and bloc.get("date"):
            dates.append(bloc["date"])
        return (max(dates) if dates else None), brut.get("date")
    if mesure.get("config_reunions"):
        verifs = [c.get("verifie_le") for c in ((ctx["config"].get("agenda") or {}).get("reunions") or {}).values() if c.get("verifie_le")]
        return (min(verifs) if verifs else None), (min(verifs) if verifs else None)
    if mesure.get("quota"):
        brut = _lire(cache / "quota_llm.json") or {}
        return brut.get("date"), brut.get("date")
    if mesure.get("news"):
        brut = _lire(cache / "collecte_news.json") or {}
        arts = [a.get("date") for a in (brut.get("donnees") or {}).get("articles") or [] if a.get("date")]
        return (max(arts)[:10] if arts else None), brut.get("date")
    if mesure.get("budget_ff"):
        brut = _lire(cache / "forexfactory_requetes.json") or {}
        h = brut.get("horodatages") or []
        return (h[-1][:10] if h else brut.get("date")), (h[-1] if h else None)
    return None, recup


def registre(config: dict, ctx: dict, aujourdhui: date) -> list[dict]:
    sortie = []
    for s in config.get("sources") or []:
        derniere, recup = derniere_donnee(s.get("mesure") or {}, ctx)
        f = fraicheur(derniere, s.get("frequence", "quotidienne"), s.get("retard_jours", 0), aujourdhui)
        if s.get("retiree"):
            f = {"etat": "retiree", "age_jours": None, "normal_jours": None, "texte": "retirée le 24/10/2026"}
        sortie.append({"id": s["id"], "nom": s["nom"], "alimente": s.get("alimente"), "statut": s.get("statut"),
                       "statut_libelle": STATUTS.get(s.get("statut"), s.get("statut")),
                       "frequence": LIBELLES_FREQ.get(s.get("frequence"), s.get("frequence")), "retard_jours": s.get("retard_jours", 0),
                       "derniere_donnee": derniere, "recupere_le": recup, "fraicheur": f, "motifs": s.get("motifs") or [],
                       "a_remplacer": bool(s.get("a_remplacer")), "retiree": bool(s.get("retiree")),
                       "remplacement": s.get("remplacement")})
    return sortie


def _controle(cle: str, rapport: dict | None) -> tuple[str, str]:
    anomalies = (((rapport or {}).get("controle_qualite") or {}).get("anomalies")) or []
    touchees = [a for a in anomalies if "indicateur publié deux fois" in str(a) and cle in str(a)]
    if touchees:
        return "⚠", touchees[0]
    if rapport is None:
        return "n/d", "rapport du jour absent : contrôle non lu"
    return "✓", "même valeur dans tous les modules (source canonique unique, contrôle du run)"


def certificats(historiques: dict, registre_sources: list[dict], config: dict, rapport: dict | None, aujourdhui: date) -> dict:
    regles = {s["id"]: s for s in config.get("sources") or []}
    sortie = {}
    for cle, (libelle, unite) in CERTIFIES.items():
        serie = ((historiques or {}).get("series") or {}).get(cle) or {}
        pts = serie.get("points") or []
        if not pts:
            sortie[cle] = {"libelle": libelle, "raison": "série absente de l'historique collecté"}
            continue
        source = serie.get("source") or "n/d"
        # motif le plus précis d'abord (« H.10 » avant « FRED » pour l'indice dollar large)
        trouves = sorted(((len(m), r) for r in registre_sources for m in r["motifs"] if m and m.lower() in source.lower()),
                         key=lambda x: -x[0])
        src = trouves[0][1] if trouves else None
        conf = regles.get(src["id"]) if src else {}
        frq = (conf or {}).get("frequence", "quotidienne")
        if "mensuel" in source.lower():
            frq = "mensuelle"
        ctrl, detail = _controle(cle, rapport)
        sortie[cle] = {"libelle": libelle, "valeur": pts[-1][1], "unite": unite, "source": source, "serie": cle,
                       "calendrier": CALENDRIERS.get(cle),
                       "date_valeur": str(pts[-1][0])[:10], "recupere_le": (src or {}).get("recupere_le"),
                       "statut": (src or {}).get("statut_libelle"), "controle": ctrl, "controle_detail": detail,
                       "fraicheur": fraicheur(pts[-1][0], frq, (conf or {}).get("retard_jours", 1), aujourdhui)}
    return sortie


def calculer(config: dict, historiques: dict | None, cache: Path, rapport: dict | None, aujourdhui: date | None = None,
             genere_le: str | None = None) -> dict:
    aujourdhui = aujourdhui or datetime.now(timezone.utc).date()
    ctx = {"cache": Path(cache), "historiques": historiques or {}, "config": config}
    reg = registre(config, ctx, aujourdhui)
    actives = [s for s in reg if not s["retiree"]]
    comptes = {k: sum(1 for s in actives if s["statut"] == k) for k in STATUTS}
    alertes = [s for s in actives if s["fraicheur"]["etat"] in ("orange", "rouge")]
    certs = certificats(historiques, reg, config, rapport, aujourdhui)
    return {"genere_le": genere_le or datetime.now(timezone.utc).isoformat(timespec="seconds"), "aujourdhui": aujourdhui.isoformat(),
            "sources": reg, "comptes": comptes, "a_remplacer": sum(1 for s in actives if s["a_remplacer"]),
            "retirees": [s for s in reg if s["retiree"]], "alertes": [{"id": s["id"], "nom": s["nom"], "texte": s["fraicheur"]["texte"]}
                                                                    for s in alertes],
            "certificats": certs,
            "alertes_indicateurs": [{"id": k, "libelle": c["libelle"], "texte": c["fraicheur"]["texte"]}
                                    for k, c in certs.items() if (c.get("fraicheur") or {}).get("etat") in ("orange", "rouge")],
            "regles": "Fraîcheur verte jusqu'à 2 fois la normale (fréquence + délai de publication), orange au-delà, rouge au-delà "
                      "de 4 fois ou sans date. Quotidien : âge en jours ouvrés.",
            "niveaux": [
                {"niveau": "Mesuré", "classe": "mesure", "texte": "L'état des 8 engrenages, les distances aux seuils, les écarts de taux : des faits datés et sourcés."},
                {"niveau": "Historique", "classe": "historique", "texte": "« Après un CPI au-dessus du précédent, l'USD a monté 56 % du temps (39 cas) » : une fréquence passée, avec sa borne de Wilson, jamais une promesse."},
                {"niveau": "Ma lecture", "classe": "lecture", "texte": "Le scénario que je retiens, noté au Journal avec l'instantané de l'analyse, puis comparé à ce qui s'est passé."},
                {"niveau": "Jamais", "classe": "jamais", "texte": "« EUR/USD va monter » ou un ordre d'achat ou de vente : aucune donnée ne le certifie."}]}


def ecrire(racine: str | Path, config: dict, rapport: dict | None = None) -> dict | None:
    try:
        racine = Path(racine)
        cache = racine / "data" / "cache"
        hist = (_lire(cache / "collecte_historiques.json") or {}).get("donnees")
        docs = racine / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
        rapport = rapport if rapport is not None else _lire(docs / "latest.json")
        donnees = calculer(config, hist, cache, rapport)
        (docs / "sources.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("sources.json non écrit : %s", exc)
        return None
