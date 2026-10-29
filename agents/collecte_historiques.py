"""Historiques longs (5 ans) pour les dossiers « 8 engrenages » : percentiles et variations calculés
en Python, sans LLM. Une requête par série et par jour (cache collecte_cache « historiques »).

Stockage compact : les 140 derniers jours au pas quotidien + une valeur par semaine (dernière
observation de chaque semaine ISO) sur 5 ans et 2 mois ; séries mensuelles intégrales.

Sources (toutes gratuites, déjà utilisées ailleurs dans le pipeline) :
- FRED : taux US (DFF, DGS2, DGS10), VIX, indice dollar large, indice or (proxy), WTI, Brent,
  S&P 500, inflation core US (CPILFESL), chômage US (UNRATE) ; OCDE via FRED : taux au jour le jour
  (IRSTCI01, proxy du taux directeur), chômage (LRHUTTTT), rendement 10 ans mensuel (IRLTLT01).
- Rendements 2 / 10 ans non US : sources de config.yaml > tableau_macro.taux_obligataires
  (Bundesbank, ministère des Finances japonais, Banque du Canada, Banque d'Angleterre).
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
from datetime import date, timedelta

import requests

from core import historique_5ans
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

UA = {"User-Agent": "agents-forex/1.0 (rapport FX personnel ; une requête par série et par jour)", "Accept": "*/*"}
JOURS_QUOTIDIENS = 140
ANNEES = 5
PAYS_OCDE = {"USD": "US", "EUR": "EZ", "GBP": "GB", "JPY": "JP", "CHF": "CH", "CAD": "CA", "AUD": "AU", "NZD": "NZ", "CNY": "CN"}
MOIS_EN = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

# nom -> (type, identifiant, libellé source, unité, fréquence)
SERIES_FRED = {
    "USD_taux_effectif": ("DFF", "FRED (DFF, taux effectif des fed funds)", "%", "quotidien"),
    "USD_2a": ("DGS2", "FRED (DGS2)", "%", "quotidien"),
    "USD_10a": ("DGS10", "FRED (DGS10)", "%", "quotidien"),
    "vix": ("VIXCLS", "FRED (VIXCLS)", "pts", "quotidien"),
    "dollar_large": ("DTWEXBGS", "FRED (DTWEXBGS, indice dollar large de la Fed)", "indice", "quotidien"),
    "indice_or": ("NASDAQQGLDI", "FRED (NASDAQQGLDI) — indice or (proxy)", "indice", "quotidien"),
    "wti": ("DCOILWTICO", "FRED (DCOILWTICO)", "$/baril", "quotidien"),
    "brent": ("DCOILBRENTEU", "FRED (DCOILBRENTEU)", "$/baril", "quotidien"),
    "sp500": ("SP500", "FRED (SP500)", "indice", "quotidien"),
    "USD_core_indice": ("CPILFESL", "FRED (CPILFESL)", "indice", "mensuel"),
    "USD_chomage": ("UNRATE", "FRED (UNRATE)", "%", "mensuel"),
    # Taux de la facilité de dépôt de la BCE (quotidien) : le taux directeur effectif de la zone euro
    "EUR_taux_depot": ("ECBDFR", "FRED (ECBDFR, taux de la facilité de dépôt de la BCE)", "%", "quotidien"),
    # Écart Italie − Allemagne : rendements 10 ans OCDE mensuels (pas de série quotidienne gratuite)
    "ITA_10a_mensuel": ("IRLTLT01ITM156N", "OCDE via FRED (IRLTLT01ITM156N, 10 ans Italie, mensuel)", "%", "mensuel"),
    "DEU_10a_mensuel": ("IRLTLT01DEM156N", "OCDE via FRED (IRLTLT01DEM156N, 10 ans Allemagne, mensuel)", "%", "mensuel"),
}
for _dev, _c in PAYS_OCDE.items():
    if _dev != "USD":
        SERIES_FRED[f"{_dev}_taux_jj"] = (f"IRSTCI01{_c}M156N", f"OCDE via FRED (IRSTCI01{_c}M156N, taux au jour le jour)", "%", "mensuel")
for _dev in ("GBP", "JPY", "CAD", "AUD"):
    SERIES_FRED[f"{_dev}_chomage"] = (f"LRHUTTTT{PAYS_OCDE[_dev]}M156S", f"OCDE via FRED (LRHUTTTT{PAYS_OCDE[_dev]}M156S)", "%", "mensuel")
# Engrenage 4 (politique fiscale) : dette et solde publics en % du PIB, prime de terme 10 ans US
SERIES_FRED.update({
    "USD_dette_pib": ("GFDEGDQ188S", "FRED (GFDEGDQ188S, dette fédérale / PIB)", "%", "trimestriel"),
    "USD_solde_pib": ("FYFSGDA188S", "FRED (FYFSGDA188S, solde fédéral / PIB)", "%", "annuel"),
    "USD_prime_terme": ("THREEFYTP10", "FRED (THREEFYTP10, prime de terme 10 ans, Kim-Wright)", "%", "quotidien"),
})
# Taux de change quotidiens (Fed H.10) pour les précédents historiques : « ce qu'a fait la devise ensuite ».
# inverse = cotation en unités de devise pour 1 USD (la force de la devise est alors 1 / taux).
CHANGES_FRED = {"EUR": ("DEXUSEU", False), "GBP": ("DEXUSUK", False), "JPY": ("DEXJPUS", True), "CHF": ("DEXSZUS", True),
                "CAD": ("DEXCAUS", True), "AUD": ("DEXUSAL", False), "NZD": ("DEXUSNZ", False), "CNY": ("DEXCHUS", True)}
for _dev, (_sid, _inv) in CHANGES_FRED.items():
    SERIES_FRED[f"FX_{_dev}"] = (_sid, f"FRED ({_sid}, Fed H.10){' — inversé : force de la devise' if _inv else ''}", "niveau", "quotidien")
PAYS_FMI = {"EUR": ("DE", "Allemagne"), "GBP": ("GB", "Royaume-Uni"), "JPY": ("JP", "Japon"), "CAD": ("CA", "Canada"),
            "AUD": ("AU", "Australie"), "CNY": ("CN", "Chine")}
for _dev, (_c, _nom) in PAYS_FMI.items():
    SERIES_FRED[f"{_dev}_dette_pib"] = (f"GGGDTA{_c}A188N", f"FMI via FRED (GGGDTA{_c}A188N, dette publique brute / PIB, {_nom})", "%", "annuel")
    SERIES_FRED[f"{_dev}_solde_pib"] = (f"GGNLBA{_c}A188N", f"FMI via FRED (GGNLBA{_c}A188N, solde public / PIB, {_nom})", "%", "annuel")


def _get(url: str, **params) -> requests.Response:
    rep = requests.get(url, headers=UA, params=params, timeout=60)
    rep.raise_for_status()
    return rep


def _sonder(url: str) -> dict:
    """Vérification quotidienne d'une source non adoptée : statut HTTP daté, sans jamais contourner un refus."""
    jour = date.today().isoformat()
    try:
        rep = requests.get(url, headers=UA, timeout=30)
        texte = (rep.headers.get("content-type") or "").split(";")[0]
        return {"date": jour, "statut": rep.status_code, "type": texte, "url": url,
                "lecture": "accès automatisé refusé" if rep.status_code == 403 else
                           "service indisponible" if rep.status_code >= 500 else
                           "requête refusée (format ou série inconnue)" if rep.status_code >= 400 else
                           "répond : intégration possible après contrôle du format"}
    except Exception as exc:  # noqa: BLE001
        return {"date": jour, "statut": None, "url": url, "lecture": f"injoignable ({masquer_secrets(str(exc))[:80]})"}


def _fred(serie: str, cle: str, debut: date) -> list[tuple[str, float]]:
    rep = _get("https://api.stlouisfed.org/fred/series/observations", series_id=serie, api_key=cle,
               file_type="json", observation_start=debut.isoformat())
    return [(o["date"], float(o["value"])) for o in rep.json().get("observations", []) if o.get("value") not in (".", None)]


def _bundesbank(code: str, debut: date) -> list[tuple[str, float]]:
    rep = _get(f"https://api.statistiken.bundesbank.de/rest/data/{code}", startPeriod=debut.isoformat(), format="csv")
    points = []
    for ligne in rep.text.splitlines():
        m = re.match(r"^(\d{4}-\d{2}-\d{2});(-?\d+(?:,\d+)?);?", ligne.strip())
        if m:
            points.append((m.group(1), float(m.group(2).replace(",", "."))))
    return sorted(points)


def _mof(colonne: str, debut: date) -> list[tuple[str, float]]:
    """Historique (mis à jour une fois par mois) + fichier du mois en cours (cotations quotidiennes)."""
    from core.marche_taux import URL_MOF_HISTORIQUE, URL_MOF_MOIS, points_mof
    fusion = dict(points_mof(_get(URL_MOF_HISTORIQUE).content.decode("utf-8", "replace"), colonne))
    try:
        fusion.update(points_mof(_get(URL_MOF_MOIS).content.decode("utf-8", "replace"), colonne))
    except Exception as exc:  # noqa: BLE001
        log.warning("MoF Japon : fichier du mois en cours illisible (%s), historique seul", exc)
    return sorted((d, v) for d, v in fusion.items() if d >= debut.isoformat())


def _boc(serie: str, debut: date) -> list[tuple[str, float]]:
    rep = _get(f"https://www.bankofcanada.ca/valet/observations/{serie}/json", start_date=debut.isoformat())
    return sorted((o["d"], float(o[serie]["v"])) for o in rep.json().get("observations", [])
                  if o.get(serie, {}).get("v") not in (None, ""))


def _boe(code: str, debut: date) -> list[tuple[str, float]]:
    rep = _get("https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp", **{
        "csv.x": "yes", "SeriesCodes": code, "CSVF": "TN", "UsingCodes": "Y", "VPD": "Y", "VFD": "N",
        "Datefrom": f"{debut.day:02d}/{list(MOIS_EN)[debut.month - 1]}/{debut.year}", "Dateto": "now"})
    points = []
    for ligne in rep.text.splitlines():
        m = re.match(r"^(\d{1,2}) ([A-Z][a-z]{2}) (\d{4}),(-?[\d.]+)", ligne.strip())
        if m:
            points.append((f"{int(m.group(3)):04d}-{MOIS_EN[m.group(2)]:02d}-{int(m.group(1)):02d}", float(m.group(4))))
    return sorted(points)


def _boj(code: str, debut: date) -> list[tuple[str, float]]:
    """API statistique de la Banque du Japon (une requête, JSON)."""
    rep = _get("https://www.stat-search.boj.or.jp/api/v1/getDataCode",
               format="json", lang="en", db="FM01", code=code, startDate=f"{debut.year}{debut.month:02d}")
    valeurs = rep.json()["RESULTSET"][0]["VALUES"]
    return [(f"{str(d)[:4]}-{str(d)[4:6]}-{str(d)[6:8]}", float(v))
            for d, v in zip(valeurs["SURVEY_DATES"], valeurs["VALUES"]) if v is not None]


def _twelve(symbole: str, debut: date, cle: str) -> list[tuple[str, float]]:
    """Clôtures quotidiennes Twelve Data (une requête), ex. TLT : ETF d'obligations d'État US à long terme."""
    jours = (date.today() - debut).days
    from core import quota_twelve
    quota_twelve.consommer(1, "historiques")
    rep = _get("https://api.twelvedata.com/time_series", symbol=symbole, interval="1day",
               outputsize=min(5000, int(jours * 5 / 7) + 20), apikey=cle)
    donnees = rep.json()
    if donnees.get("status") != "ok":
        raise RuntimeError(f"Twelve Data {symbole} : {donnees.get('message', 'réponse invalide')}")
    return sorted((v["datetime"][:10], float(v["close"])) for v in donnees.get("values", []) if v.get("close"))


def _eia(series: list[str], cle: str) -> dict[str, list[tuple[str, float]]]:
    """Stocks / production hebdomadaires EIA sur 6 ans (une requête pour toutes les séries)."""
    rep = _get("https://api.eia.gov/v2/petroleum/sum/sndw/data/", api_key=cle, frequency="weekly", **{
        "data[0]": "value", "facets[series][]": series, "start": (date.today() - timedelta(days=6 * 366)).isoformat(),
        "sort[0][column]": "period", "sort[0][direction]": "asc", "length": 5000})
    sortie: dict[str, list] = {}
    for x in rep.json().get("response", {}).get("data", []):
        if x.get("value") not in (None, ""):
            sortie.setdefault(x["series"], []).append((x["period"], float(x["value"])))
    return sortie


def compacter(points: list[tuple[str, float]], frequence: str, aujourdhui: date) -> list[list]:
    """Quotidien : 140 derniers jours entiers + dernière valeur de chaque semaine ISO avant."""
    if frequence != "quotidien" or not points:
        return [[d, v] for d, v in points]
    limite = (date.fromisoformat(points[-1][0]) - timedelta(days=JOURS_QUOTIDIENS)).isoformat()
    hebdo: dict[tuple[int, int], tuple[str, float]] = {}
    recents = []
    for d, v in points:
        if d >= limite:
            recents.append([d, v])
        else:
            hebdo[date.fromisoformat(d).isocalendar()[:2]] = (d, v)
    return [[d, v] for d, v in sorted(hebdo.values())] + recents


def collecter(config: dict) -> dict:
    """{"series": {nom: {source, unite, frequence, points: [[date, valeur], ...]}}, "erreurs": [...]}."""
    aujourdhui = date.today()
    debut = aujourdhui - timedelta(days=int(365.25 * ANNEES) + 62)
    debut_mensuel = aujourdhui - timedelta(days=int(365.25 * (ANNEES + 1)) + 62)   # +1 an : glissement annuel
    cle = os.environ.get("FRED_API_KEY", "").strip()
    resultat: dict = {"series": {}, "erreurs": [], "debut": debut.isoformat()}
    bruts: dict[str, list] = {}   # séries quotidiennes COMPLÈTES gardées en mémoire pour les corrélations 5 ans

    def ajouter(nom, fonction, source, unite, frequence):
        try:
            points = fonction()
            if not points:
                raise RuntimeError("aucune observation")
            if nom in historique_5ans.SERIES:
                bruts[nom] = points
            resultat["series"][nom] = {"source": source, "unite": unite, "frequence": frequence,
                                       "points": compacter(points, frequence, aujourdhui)}
        except Exception as exc:  # noqa: BLE001 — une série en échec n'affecte qu'elle
            resultat["erreurs"].append(masquer_secrets(f"{nom} ({source}) : {exc}")[:200])

    if cle:
        for nom, (serie, source, unite, freq) in SERIES_FRED.items():
            # séries de l'historique quotidien 5 ans : 300 jours d'amorçage en plus (MM200 calculable sur 5 ans pleins)
            debut_serie = aujourdhui - timedelta(days=historique_5ans.FENETRE_JOURS) if nom in historique_5ans.SERIES else debut
            ajouter(nom, lambda s=serie, f=freq, d=debut_serie: _fred(s, cle, debut_mensuel if f in ("mensuel", "trimestriel") else
                                                                    aujourdhui - timedelta(days=12 * 366) if f == "annuel" else d),
                    source, unite, freq)
    else:
        resultat["erreurs"].append("FRED_API_KEY absente : séries FRED non collectées")

    # Taux au jour le jour OFFICIELS, quotidiens : Banque du Japon (call rate non garanti) et
    # Banque d'Angleterre (SONIA) — historique du taux directeur effectif, comme DFF pour l'USD.
    ajouter("JPY_taux_effectif", lambda: _boj("STRDCLUCON", debut),
            "Banque du Japon (STRDCLUCON, call rate non garanti au jour le jour)", "%", "quotidien")
    ajouter("GBP_taux_effectif", lambda: _boe("IUDSOIA", debut), "Banque d'Angleterre (IUDSOIA, SONIA)", "%", "quotidien")
    # Obligations d'État US à long terme (prix) : ETF TLT, Twelve Data (simulateur d'impact)
    cle_twelve = os.environ.get("TWELVE_DATA_API_KEY", "").strip()
    if cle_twelve:
        ajouter("oblig_us_tlt", lambda: _twelve("TLT", aujourdhui - timedelta(days=historique_5ans.FENETRE_JOURS), cle_twelve),
                "Twelve Data (TLT, ETF obligations d'État US 20 ans et plus)", "$", "quotidien")
    else:
        resultat["erreurs"].append("TWELVE_DATA_API_KEY absente : obligations US (TLT) non collectées")
    # Pétrole : stocks commerciaux de brut et production US, hebdomadaires sur 6 ans (moyenne 5 ans)
    cle_eia = os.environ.get("EIA_API_KEY", "").strip() or "DEMO_KEY"
    try:
        eia = _eia(["WCESTUS1", "WCRFPUS2"], cle_eia)
        for code, nom, libelle in (("WCESTUS1", "eia_stocks", "EIA (WCESTUS1, stocks de brut hors réserve stratégique)"),
                                   ("WCRFPUS2", "eia_production", "EIA (WCRFPUS2, production de brut US)")):
            if eia.get(code):
                resultat["series"][nom] = {"source": libelle, "unite": "milliers de barils" if code == "WCESTUS1" else "milliers de b/j",
                                           "frequence": "hebdomadaire", "points": [[d, v] for d, v in eia[code]]}
            else:
                resultat["erreurs"].append(f"{nom} ({libelle}) : aucune observation")
    except Exception as exc:  # noqa: BLE001
        resultat["erreurs"].append(masquer_secrets(f"EIA : {exc}")[:200])

    lecteurs = {"bundesbank": lambda s: _bundesbank(s["code"], debut), "mof": lambda s: _mof(s["colonne"], debut),
                "boc": lambda s: _boc(s["serie"], debut), "boe": lambda s: _boe(s["code"], debut),
                "fred_mensuel": lambda s: _fred(s["serie"], cle, debut) if cle else []}
    sources = ((config.get("tableau_macro") or {}).get("taux_obligataires") or {}).get("sources") or {}
    for devise, par_maturite in sources.items():
        if devise == "USD":
            continue   # FRED ci-dessus
        for maturite, spec in (par_maturite or {}).items():
            lecteur = lecteurs.get(spec.get("type"))
            if lecteur:
                ajouter(f"{devise}_{maturite}", lambda s=spec, l=lecteur: l(s), spec.get("source", spec.get("type")),
                        "%", "mensuel" if spec.get("type") == "fred_mensuel" else "quotidien")
            elif spec.get("verifier"):
                # Source absente : UNE requête par jour pour savoir si elle répond depuis le runner (jamais de
                # contournement d'un 403) ; le résultat daté complète la raison « n/d » affichée sur le site.
                resultat.setdefault("sondes_sources", {})[f"{devise}_{maturite}"] = _sonder(spec["verifier"])
    try:   # historique quotidien 5 ans (fenêtre glissante, taille stable) : RSI, volatilité, corrélations…
        resultat["historique_5ans"] = historique_5ans.enregistrer(bruts)
    except Exception as exc:  # noqa: BLE001 — n'affecte que les calculs longs
        resultat["erreurs"].append(masquer_secrets(f"historique quotidien 5 ans : {exc}")[:200])
    if cle:   # simulateur : indicateurs publiés sur 15 à 20 ans (13 requêtes FRED/ALFRED), cache à taille stable
        from core import impact_long
        resultat["impact_long"] = impact_long.collecter_et_ecrire(cle, aujourdhui)
    log.info("Historiques : %d série(s), %d erreur(s)", len(resultat["series"]), len(resultat["erreurs"]))
    return resultat
