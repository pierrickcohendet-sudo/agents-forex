"""Écart habituel au consensus d'une publication (lot V13, défauts D1 et D2).

Avant : l'écart en « écarts habituels » (z) divisait l'écart par une échelle du registre exprimée en points de pourcentage,
même pour des chiffres en milliers (inscriptions hebdomadaires au chômage US : 203K contre 198K -> z = 50), et restait vide
pour les indicateurs hors registre (indice de la Fed de Philadelphie, moral de l'université du Michigan).

Maintenant, quand l'échelle du registre manque ou ne correspond pas à l'unité publiée, on prend l'écart habituel des écarts
historiques au consensus, mesuré dans l'archive des publications du site (data/cache/publications_archive.json) :
1. la même publication (devise et nom ForexFactory), si elle compte au moins 3 écarts passés ;
2. sinon sa famille d'indicateurs de même unité (enquêtes régionales de la Fed, moral des ménages…), au moins 2 écarts ;
3. sinon z reste n/d, avec la raison.
L'écart habituel est la moyenne quadratique des écarts passés (réel − consensus) : la taille typique d'une surprise, même
quand elles vont toutes dans le même sens. La publication notée est exclue de son propre calcul.
"""
from __future__ import annotations

import re
import statistics

MIN_POINTS = 3            # même publication
MIN_POINTS_FAMILLE = 2    # famille d'indicateurs de même unité (plusieurs séries mises en commun)
Z_ABERRANT = 5.0          # au-delà, l'écart est jugé aberrant (erreur d'échelle probable) : il compte pour 1 dans un solde

FAMILLES = [
    ("enquetes_regionales_fed", "enquêtes régionales de la Fed",
     r"(philly|philadelphia|empire state|richmond|kansas city|dallas)\b.*(fed|manufacturing|index)|empire state manufacturing"),
    ("moral_menages", "moral des ménages", r"consumer (sentiment|confidence)"),
    ("inscriptions_chomage", "inscriptions au chômage", r"unemployment claims|jobless claims|continuing claims"),
    ("pmi", "indices PMI", r"\bpmi\b"),
]


def nombre(t) -> tuple[float | None, str]:
    """« −43.5K » -> (-43500.0, 'K') ; « 3.6% » -> (3.6, '%') ; illisible -> (None, '')."""
    s = str(t or "").strip().replace("−", "-").replace(",", ".")
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*([%KMBT]?)", s)
    if not m:
        return None, ""
    v, u = float(m.group(1)), m.group(2)
    return v * {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(u, 1), u


def famille(evenement_en: str) -> tuple[str, str] | None:
    t = str(evenement_en or "").lower()
    return next(((k, lib) for k, lib, m in FAMILLES if re.search(m, t)), None)


def ecarts_archives(archive: dict | None) -> dict:
    """{(devise, nom_en): [(écart, date, nom)]} et {(devise, famille): [...]} sur l'archive (unités homogènes par clé)."""
    par_nom, par_famille = {}, {}
    for p in ((archive or {}).get("publications") or {}).values():
        r, ur = nombre(p.get("reel"))
        c, uc = nombre(p.get("consensus"))
        if r is None or c is None or (ur == "%") != (uc == "%"):
            continue
        d = (r - c, str(p.get("date") or ""), str(p.get("evenement_en") or "").lower())
        par_nom.setdefault((p.get("devise"), d[2]), []).append(d)
        f = famille(p.get("evenement_en"))
        if f:
            par_famille.setdefault((p.get("devise"), f[0]), []).append(d)
    return {"nom": par_nom, "famille": par_famille}


def _habituel(ecarts: list[float], minimum: int = MIN_POINTS) -> float | None:
    if len(ecarts) < minimum:
        return None
    return (statistics.fmean(x * x for x in ecarts) ** 0.5) or None


def echelle_historique(index: dict, devise: str, evenement_en: str, exclure_date: str | None = None) -> dict:
    """-> {echelle, base, n, raison} : écart habituel des écarts au consensus, dans l'unité publiée (K converti en unités).
    La publication notée (même nom, même date) est exclue de son propre calcul."""
    nom = str(evenement_en or "").lower()
    garder = lambda l: [d for d, dt, en in l if not (exclure_date and dt == exclure_date and en == nom)]   # noqa: E731
    e = garder((index.get("nom") or {}).get((devise, nom)) or [])
    s = _habituel(e)
    if s:
        return {"echelle": s, "base": f"{len(e)} publications précédentes de cet indicateur", "n": len(e), "raison": None}
    f = famille(evenement_en)
    if f:
        ef = garder((index.get("famille") or {}).get((devise, f[0])) or [])
        s = _habituel(ef, MIN_POINTS_FAMILLE)
        if s:
            return {"echelle": s, "base": f"{len(ef)} publications de la famille « {f[1]} »", "n": len(ef), "raison": None}
        return {"echelle": None, "base": None, "n": len(ef),
                "raison": f"historique trop court ({len(ef)} écarts au consensus pour la famille « {f[1]} », il en faut {MIN_POINTS_FAMILLE})"}
    return {"echelle": None, "base": None, "n": len(e),
            "raison": f"historique trop court ({len(e)} écarts au consensus archivés, il en faut {MIN_POINTS})"}


def z_publication(reel, consensus, devise: str, evenement_en: str, index: dict, date: str | None = None) -> dict:
    """z = (réel − consensus) / écart habituel historique, dans les unités réelles (K, M convertis)."""
    r, _ = nombre(reel)
    c, _ = nombre(consensus)
    if r is None or c is None:
        return {"z": None, "raison": "réel ou consensus illisible"}
    h = echelle_historique(index, devise, evenement_en, date)
    if not h["echelle"]:
        return {"z": None, "raison": h["raison"]}
    return {"z": round((r - c) / h["echelle"], 2), "echelle": h["echelle"], "base": h["base"], "raison": None}


def poids_solde(z: float | None) -> tuple[float | None, bool]:
    """Poids d'une publication dans un solde de surprises : |z| ; un écart aberrant (|z| > 5) compte pour 1."""
    if z is None:
        return None, False
    if abs(z) > Z_ABERRANT:
        return 1.0, True
    return abs(z), False
