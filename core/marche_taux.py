"""Rendements obligataires souverains (2 ans, 10 ans) et spread 2 ans vs États-Unis.

Données de MARCHÉ : pas de consensus, pas de « réel » publié — colonnes Actuel,
semaine précédente, variation en points de base (pb) ; Prévision = « — (donnée
de marché) », jamais une valeur inventée. Code pur, aucun LLM.

Sources gratuites, vérifiées sur les vraies données le 2026-10-08 (config.yaml >
tableau_macro.taux_obligataires), une requête par source et par jour :
  USD  FRED DGS2 / DGS10 (quotidien)
  EUR  Bundesbank, courbe des taux allemande 2 ans / 10 ans (quotidien) — l'API
       de la BCE renvoyait des 500 ce jour-là
  GBP  Banque d'Angleterre IADB, par yield 10 ans IUDMNPY (quotidien) ; pas de 2 ans
  JPY  Ministère des Finances (JGB 2 ans / 10 ans, quotidien, ~1 semaine de retard)
  CAD  Banque du Canada, API Valet (quotidien)
  CHF, AUD, NZD  OCDE via FRED, 10 ans MENSUEL seulement (étiqueté « mensuel ») ;
       SNB (série arrêtée en 07/2025), RBA et RBNZ (accès automatisé refusé, 403) : pas de 2 ans
  CNY  aucune source gratuite exploitable
Une source en échec n'efface jamais la dernière valeur connue du registre.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, datetime, timedelta, timezone

import requests

from core import registre_macro as rm
from core.secrets import masquer_secrets

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")
MOIS_EN = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
INDICATEURS = ("rendement_2a", "rendement_10a", "spread_2a_usd")


# ----------------------------------------------------------------- lecteurs
def _get(url: str, **params) -> requests.Response:
    rep = requests.get(url, headers={"User-Agent": UA, "Accept": "*/*"}, params=params, timeout=40)
    rep.raise_for_status()
    return rep


def lire_fred(serie: str, cle: str) -> list[tuple[str, float]]:
    rep = _get("https://api.stlouisfed.org/fred/series/observations", series_id=serie, api_key=cle,
               file_type="json", sort_order="desc", limit=20)
    return [(o["date"], float(o["value"])) for o in rep.json().get("observations", [])
            if o.get("value") not in (".", None)]


def lire_bundesbank(code: str) -> list[tuple[str, float]]:
    rep = _get(f"https://api.statistiken.bundesbank.de/rest/data/{code}", lastNObservations=15, format="csv")
    points = []
    for ligne in rep.text.splitlines():
        m = re.match(r"^(\d{4}-\d{2}-\d{2});(-?\d+(?:,\d+)?);?", ligne.strip())  # « . » = jour sans cotation
        if m:
            points.append((m.group(1), float(m.group(2).replace(",", "."))))
    return sorted(points, reverse=True)


def lire_boe(code: str) -> list[tuple[str, float]]:
    debut = date.today() - timedelta(days=25)
    rep = _get("https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp", **{
        "csv.x": "yes", "SeriesCodes": code, "CSVF": "TN", "UsingCodes": "Y", "VPD": "Y", "VFD": "N",
        "Datefrom": f"{debut.day:02d}/{list(MOIS_EN)[debut.month - 1]}/{debut.year}", "Dateto": "now"})
    points = []
    for ligne in rep.text.splitlines():
        m = re.match(r"^(\d{1,2}) ([A-Z][a-z]{2}) (\d{4}),(-?[\d.]+)", ligne.strip())
        if m:
            points.append((f"{int(m.group(3)):04d}-{MOIS_EN[m.group(2)]:02d}-{int(m.group(1)):02d}",
                           float(m.group(4))))
    return sorted(points, reverse=True)


def lire_mof(colonne: str) -> list[tuple[str, float]]:
    rep = _get("https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv")
    lignes = list(csv.reader(io.StringIO(rep.content.decode("utf-8", "replace"))))
    entete_i = next(i for i, l in enumerate(lignes) if l and l[0].strip() == "Date")
    index = [c.strip() for c in lignes[entete_i]].index(colonne)
    points = []
    for l in lignes[-30:]:
        if len(l) > index and re.match(r"^\d{4}/\d{1,2}/\d{1,2}$", l[0].strip()):
            try:
                a, m, j = (int(x) for x in l[0].strip().split("/"))
                points.append((f"{a:04d}-{m:02d}-{j:02d}", float(l[index])))
            except ValueError:
                continue  # « - » : pas de cotation ce jour-là
    return sorted(points, reverse=True)


def lire_boc(serie: str) -> list[tuple[str, float]]:
    rep = _get(f"https://www.bankofcanada.ca/valet/observations/{serie}/json", recent=15)
    return sorted(((o["d"], float(o[serie]["v"])) for o in rep.json().get("observations", [])
                   if o.get(serie, {}).get("v") not in (None, "")), reverse=True)


def _derniere_et_precedente(points: list[tuple[str, float]], jours: int) -> dict | None:
    """Dernière observation et celle d'il y a ≥ `jours` jours (semaine précédente)."""
    if not points:
        return None
    d0, v0 = points[0]
    limite = (date.fromisoformat(d0) - timedelta(days=jours)).isoformat()
    avant = next(((d, v) for d, v in points[1:] if d <= limite), None)
    return {"date": d0, "valeur": v0, "date_prec": avant[0] if avant else None,
            "precedente": avant[1] if avant else None}


def _mensuel(points: list[tuple[str, float]]) -> dict | None:
    if not points:
        return None
    (d0, v0), suivant = points[0], (points[1] if len(points) > 1 else (None, None))
    return {"date": None, "periode": d0[:7], "valeur": v0, "date_prec": None,
            "periode_prec": suivant[0][:7] if suivant[0] else None, "precedente": suivant[1]}


def collecter(cfg_tm: dict, cle_fred: str) -> dict:
    """{"series": {"USD|rendement_2a": {...}}, "erreurs": [...]}. Une source en
    échec n'affecte que ses cases ; chaque source n'est appelée qu'une fois."""
    cfg = cfg_tm.get("taux_obligataires") or {}
    jours = int(cfg.get("jours_variation", 7))
    resultat: dict = {"series": {}, "erreurs": []}
    cache_mof: dict = {}
    for devise, par_maturite in (cfg.get("sources") or {}).items():
        for maturite, spec in par_maturite.items():
            if spec.get("absent"):
                continue
            try:
                t = spec["type"]
                if t == "fred":
                    points, mensuel = lire_fred(spec["serie"], cle_fred), False
                elif t == "fred_mensuel":
                    points, mensuel = lire_fred(spec["serie"], cle_fred), True
                elif t == "bundesbank":
                    points, mensuel = lire_bundesbank(spec["code"]), False
                elif t == "boe":
                    points, mensuel = lire_boe(spec["code"]), False
                elif t == "boc":
                    points, mensuel = lire_boc(spec["serie"]), False
                elif t == "mof":
                    points, mensuel = lire_mof(spec["colonne"]), False
                else:
                    raise ValueError(f"type de source inconnu : {t}")
                lecture = _mensuel(points) if mensuel else _derniere_et_precedente(points, jours)
                if lecture is None:
                    raise ValueError("aucune observation")
                resultat["series"][f"{devise}|{maturite}"] = {
                    **lecture, "frequence": "mensuel" if mensuel else "quotidien",
                    "source": spec["source"]}
            except Exception as exc:  # noqa: BLE001
                resultat["erreurs"].append(f"{devise}|{maturite} ({spec.get('source')}) : "
                                           f"{masquer_secrets(str(exc))[:120]}")
    log.info("Taux obligataires : %d série(s), %d erreur(s)", len(resultat["series"]), len(resultat["erreurs"]))
    return resultat


# ------------------------------------------------------------- registre
def _fmt_rendement(v: float) -> str:
    return f"{v:.2f}%"


def _fmt_pb(v: float) -> str:
    return f"{v:+.0f} pb"


def _case_marche(registre: dict, indicateur: str, devise: str) -> dict:
    case = rm._case(registre, indicateur, devise)
    case["marche"] = True
    return case


def integrer(registre: dict, resultat: dict, cfg_tm: dict) -> dict:
    """Rendements, semaine précédente, variation (pb), spread 2 ans vs USD.
    Retourne la couverture : {devise: {"2a": état, "10a": état, "spread": état}}."""
    cfg = cfg_tm.get("taux_obligataires") or {}
    series = resultat.get("series", {})
    couverture: dict = {}
    for devise in cfg_tm["ordre_devises"]:
        couverture[devise] = {}
        for maturite, indicateur in (("2a", "rendement_2a"), ("10a", "rendement_10a")):
            case = _case_marche(registre, indicateur, devise)
            spec = ((cfg.get("sources") or {}).get(devise) or {}).get(maturite) or {"absent": "non disponible"}
            lecture = series.get(f"{devise}|{maturite}")
            if spec.get("absent"):
                case.update(statut="non_applicable", absent=spec["absent"])
                couverture[devise][maturite] = "absent"
                continue
            case["statut"] = "ok" if case.get("statut") != "non_applicable" else "ok"
            case["absent"] = None
            if lecture is None:  # source en échec : on garde la dernière valeur connue du registre
                couverture[devise][maturite] = "dernière valeur connue" if case.get("actuel") else "indisponible"
                continue
            mensuel = lecture["frequence"] == "mensuel"
            case["frequence"] = lecture["frequence"]
            case["etiquette"] = "mensuel" if mensuel else None
            case["actuel"] = {"valeur": _fmt_rendement(lecture["valeur"]), "valeur_num": lecture["valeur"],
                              "date_pub": lecture["date"], "periode": lecture.get("periode"),
                              "dateline": None, "consensus": None, "surprise": None,
                              "source": lecture["source"], "origine": "marche"}
            case["precedent"] = ({"valeur": _fmt_rendement(lecture["precedente"]),
                                  "date": lecture["date_prec"], "periode": lecture.get("periode_prec"),
                                  "revise": False} if lecture["precedente"] is not None else None)
            case["variation_pb"] = (round((lecture["valeur"] - lecture["precedente"]) * 100, 1)
                                    if lecture["precedente"] is not None else None)
            couverture[devise][maturite] = lecture["frequence"]
    # Spread 2 ans vs USD (données quotidiennes des deux côtés uniquement)
    usd = registre["cases"].get(rm.cle("rendement_2a", "USD"), {})
    for devise in cfg_tm["ordre_devises"]:
        case = _case_marche(registre, "spread_2a_usd", devise)
        if devise == "USD":
            case.update(statut="non_applicable", absent="référence (États-Unis)")
            couverture[devise]["spread"] = "référence"
            continue
        local = registre["cases"].get(rm.cle("rendement_2a", devise), {})
        a_l, a_u = local.get("actuel") or {}, usd.get("actuel") or {}
        ok = (local.get("statut") != "non_applicable" and a_l.get("valeur_num") is not None
              and a_u.get("valeur_num") is not None and local.get("frequence") == "quotidien"
              and a_l.get("date_pub") and a_u.get("date_pub")
              and abs((date.fromisoformat(a_l["date_pub"]) - date.fromisoformat(a_u["date_pub"])).days) <= 7)
        if not ok:
            raison = (local.get("absent") or "rendement 2 ans indisponible") if local.get("statut") == "non_applicable" \
                else "rendement 2 ans indisponible"
            case.update(statut="non_applicable", absent=f"spread impossible : {raison}")
            couverture[devise]["spread"] = "absent"
            continue
        spread = (a_l["valeur_num"] - a_u["valeur_num"]) * 100
        p_l, p_u = local.get("precedent") or {}, usd.get("precedent") or {}
        pl = rm.vers_nombre(p_l.get("valeur")) if p_l else None
        pu = rm.vers_nombre(p_u.get("valeur")) if p_u else None
        spread_prec = (pl - pu) * 100 if pl is not None and pu is not None else None
        case.update(statut="ok", absent=None, frequence="quotidien", etiquette=None)
        case["actuel"] = {"valeur": _fmt_pb(spread), "valeur_num": spread,
                          "date_pub": min(a_l["date_pub"], a_u["date_pub"]), "dateline": None,
                          "consensus": None, "surprise": None, "origine": "marche",
                          "source": f"Calcul : {a_l.get('source', '?')} − {a_u.get('source', '?')}"}
        case["precedent"] = ({"valeur": _fmt_pb(spread_prec),
                              "date": p_l.get("date") or p_u.get("date"), "revise": False}
                             if spread_prec is not None else None)
        case["variation_pb"] = round(spread - spread_prec, 1) if spread_prec is not None else None
        couverture[devise]["spread"] = "quotidien"
    return couverture


def resume_pour_analyse(registre: dict, cfg_tm: dict) -> dict:
    """{devise: {y2, y10, spread_2a_pb, variation_semaine_pb, frequence, date}} — alimente la
    ligne « différentiel de taux » du score de confluence (sens décidé comme avant, pondérations
    inchangées) : le spread de marché intègre les anticipations de banque centrale."""
    resultat = {}
    for devise in cfg_tm["ordre_devises"]:
        def lire(ind):
            c = registre["cases"].get(rm.cle(ind, devise)) or {}
            return c if c.get("statut") != "non_applicable" and c.get("actuel") else None
        y2, y10, sp = lire("rendement_2a"), lire("rendement_10a"), lire("spread_2a_usd")
        if not (y2 or y10 or sp):
            continue
        resultat[devise] = {
            "rendement_2a_pct": y2["actuel"]["valeur_num"] if y2 else None,
            "rendement_10a_pct": y10["actuel"]["valeur_num"] if y10 else None,
            "spread_2a_vs_usd_pb": round(sp["actuel"]["valeur_num"]) if sp else None,
            "variation_spread_semaine_pb": sp.get("variation_pb") if sp else None,
            "frequence_10a": (y10 or {}).get("frequence"),
            "date": ((sp or y2 or y10)["actuel"].get("date_pub") or (y10 or {}).get("actuel", {}).get("periode")),
        }
    return resultat


def appliquer_registre_taux(macro: dict, registre: dict, cfg_tm: dict) -> dict:
    """Taux directeurs OFFICIELS du registre macro (dernière publication ForexFactory) à la place
    des valeurs de repli de config.yaml (et du FEDFUNDS mensuel pour l'USD) ; recalcule le carry
    (médiane G8 et différentiels). La config ne reste en repli que si le registre n'a pas de valeur
    NUMÉRIQUE pour la devise (ex. « <1.25% » du JPY : une borne, pas un taux). Retourne
    {devise: {avant, apres, source}} pour les devises modifiées ; macro est modifié en place."""
    taux = macro.get("taux_directeurs") or {}
    modifs = {}
    for devise in cfg_tm.get("ordre_devises", list(taux)):
        case = (registre.get("cases") or {}).get(rm.cle("taux_directeur", devise)) or {}
        actuel = case.get("actuel") or {}
        if case.get("statut") == "non_applicable" or actuel.get("valeur_num") is None:
            continue
        avant = taux.get(devise) or {}
        nouveau = {"taux": float(actuel["valeur_num"]), "date": str(actuel.get("date_pub") or ""),
                   "source": "registre macro (ForexFactory, publication officielle)"}
        if avant.get("taux") is not None:
            nouveau["repli_precedent"] = {"taux": avant["taux"], "date": avant.get("date"),
                                         "source": avant.get("source")}
        taux[devise] = nouveau
        if avant.get("taux") != nouveau["taux"]:
            modifs[devise] = {"avant": avant.get("taux"), "apres": nouveau["taux"], "source": nouveau["source"]}
    macro["taux_directeurs"] = taux
    valeurs = {d: v["taux"] for d, v in taux.items() if v.get("taux") is not None}
    if valeurs:
        import statistics
        mediane = statistics.median(valeurs.values())
        macro["carry"] = {"mediane_g8": round(mediane, 2),
                          "differentiels": {d: round(t - mediane, 2) for d, t in valeurs.items()}}
    return modifs
