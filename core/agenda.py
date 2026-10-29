"""Agenda macro (lot V5, complément) : semaine en cours + semaine suivante, 9 devises. Calcul Python, sans LLM.

Sources, par ordre de préférence (chaque ligne garde la sienne, avec sa date de vérification) :
- calendriers officiels des 9 banques centrales (config.yaml, agenda.reunions : source, URL, date de vérification) ;
- page « mois » ForexFactory déjà lue pour le tableau macro (data/cache/calendrier_mois.json : heure, impact,
  précédent, consensus, réel — aucune requête de plus) ;
- flux public JSON ForexFactory de la semaine (data/cache/scrape_forexfactory.json : consensus) ;
- FRED releases/dates (dates des publications US, une requête par jour, data/cache/collecte_agenda_fred.json) ;
- magasin glissant des évènements publiés et registre macro (prochaine publication, taux actuels).
Une valeur absente est « n/d » avec la raison ; un nom non traduit garde l'anglais (liste dans le résumé du run).
Heure de Paris : zoneinfo gère les changements d'heure (Europe le 25/10, États-Unis le 01/11).
"""
from __future__ import annotations

import json
import logging
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import registre_macro as rm, tableau_macro

log = logging.getLogger(__name__)

DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]
BANQUES = {"USD": "Réserve fédérale (Fed)", "EUR": "Banque centrale européenne (BCE)", "GBP": "Banque d'Angleterre (BoE)",
           "JPY": "Banque du Japon (BoJ)", "CHF": "Banque nationale suisse (BNS)", "CAD": "Banque du Canada (BoC)",
           "AUD": "Banque de réserve d'Australie (RBA)", "NZD": "Banque de réserve de Nouvelle-Zélande (RBNZ)",
           "CNY": "Banque populaire de Chine (PBoC)"}
COURTS = {"USD": "Fed", "EUR": "BCE", "GBP": "BoE", "JPY": "BoJ", "CHF": "BNS", "CAD": "BoC", "AUD": "RBA", "NZD": "RBNZ",
          "CNY": "PBoC"}
# Siège de chaque banque (globe de la page Agenda) : latitude, longitude
SIEGES = {"USD": (38.89, -77.05), "EUR": (50.11, 8.70), "GBP": (51.51, -0.09), "JPY": (35.69, 139.77),
          "CHF": (46.95, 7.44), "CAD": (45.42, -75.70), "AUD": (-33.87, 151.21), "NZD": (-41.29, 174.78),
          "CNY": (39.91, 116.36)}
# Paire principale de chaque devise (réaction passée) ; USD : EUR/USD lu à l'envers
PAIRE_PRINCIPALE = {"USD": ("EUR/USD", -1), "EUR": ("EUR/USD", 1), "GBP": ("GBP/USD", 1), "JPY": ("USD/JPY", -1),
                    "CHF": ("USD/CHF", -1), "CAD": ("USD/CAD", -1), "AUD": ("AUD/USD", 1), "NZD": ("NZD/USD", 1),
                    "CNY": ("USD/CNY", -1)}
IMPACTS = {"high": "fort", "medium": "moyen", "low": "faible", "holiday": "férié", "non-economic": "faible"}
POINTS = {"fort": "●●●", "moyen": "●●○", "faible": "●○○"}
TYPES = ("Réunion BC", "Conférence", "Discours", "Grand rendez-vous", "Chiffre")
DECISION = re.compile(r"federal funds rate|main refinancing rate|deposit facility rate|official bank rate|overnight rate"
                      r"|^cash rate|official cash rate|boj policy rate|snb policy rate|loan prime rate", re.I)
CONFERENCE = re.compile(r"press conference", re.I)
DISCOURS = re.compile(r"\b(speaks|testifies|testimony)\b", re.I)
GRAND = re.compile(r"imf meetings|\bg7\b|\bg20\b|opec|jackson hole|forum on central banking|economic summit|election", re.I)
# Évènement -> engrenage concerné (dossier) ; mots-clés en anglais (titres ForexFactory)
ENGRENAGES = [(2, r"rate|monetary policy|press conference|fomc|minutes|refinancing|lpr|speaks|testifies"),
              (3, r"cpi|ppi|employment|non-farm|unemployment|gdp|pmi|retail|claims|wage|earnings|sentiment|confidence|ism"),
              (8, r"trade balance|crude|oil|current account|opec")]
# Évènement USD -> indicateur du simulateur d'impact (#scenarios/i=…)
SIMULATEUR = [(r"federal funds rate", "fed"), (r"core cpi", "cpi_core_us"), (r"\bcpi\b", "cpi_us"), (r"gdp", "pib_us")]
MIN_CAS = 20
SOURCE_MOIS = "ForexFactory, page « mois » (extraction de page, déjà lue pour le tableau macro)"
SOURCE_SEMAINE = "ForexFactory, flux public JSON de la semaine"
SOURCE_REGISTRE = "registre macro (ForexFactory, prochaine publication)"


def fuseau(nom: str = "Europe/Paris"):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(nom)
    except Exception:  # noqa: BLE001 — base tz absente : approximation (heure d'hiver)
        return timezone(timedelta(hours=1 if nom.startswith("Europe") else 0))


def fuseau_paris():
    return fuseau("Europe/Paris")


def engrenage(titre: str) -> int | None:
    t = titre.lower()
    return next((n for n, motif in ENGRENAGES if re.search(motif, t)), None)


def simulateur(devise: str, titre: str) -> str | None:
    if devise != "USD":
        return None
    t = titre.lower()
    return next((i for motif, i in SIMULATEUR if re.search(motif, t)), None)


def type_evenement(titre: str) -> str:
    if DECISION.search(titre):
        return "Réunion BC"
    if CONFERENCE.search(titre):
        return "Conférence"
    if DISCOURS.search(titre):
        return "Discours"
    if GRAND.search(titre):
        return "Grand rendez-vous"
    return "Chiffre"


# ------------------------------------------------------------------ traduction
class Traducteur:
    """Nom exact, sinon pays + qualificatif + base + unité, sinon discours « <fonction> <Nom> Speaks ». Garde l'anglais
    et le note quand rien ne correspond (résumé du run)."""

    def __init__(self, cfg: dict | None):
        cfg = cfg or {}
        self.exact = cfg.get("traductions") or {}
        self.bases = {**(cfg.get("bases") or {})}
        self.prefixes = sorted((cfg.get("prefixes") or {}).items(), key=lambda kv: -len(kv[0]))
        self.qualifs = sorted((cfg.get("qualificatifs") or {}).items(), key=lambda kv: -len(kv[0]))
        self.suffixes = sorted((cfg.get("suffixes") or {}).items(), key=lambda kv: -len(kv[0]))
        self.orateurs = sorted((cfg.get("orateurs") or {}).items(), key=lambda kv: -len(kv[0]))
        self.non_traduits: set[str] = set()

    def _base(self, texte: str) -> str | None:
        return self.bases.get(texte) or self.exact.get(texte)

    def _discours(self, titre: str) -> str | None:
        m = re.match(r"^(?P<avant>.+?)\s+(?P<verbe>Speaks|Testifies)$", titre)
        if not m:
            return None
        avant, verbe = m["avant"], ("Discours" if m["verbe"] == "Speaks" else "Audition")
        for role, fr in self.orateurs:
            if avant == role:
                return f"{verbe} : {fr}"
            if avant.startswith(role + " "):
                return f"{verbe} de {avant[len(role) + 1:]}, {fr}"
        return None

    def traduire(self, titre: str) -> tuple[str, bool]:
        titre = (titre or "").strip()
        if titre in self.exact:
            return self.exact[titre], True
        discours = self._discours(titre)
        if discours:
            return discours, True
        reste, pays, qualif, suffixe = titre, "", "", ""
        for en, fr in self.prefixes:
            if reste.startswith(en):
                reste, pays = reste[len(en):], fr
                break
        for en, fr in self.qualifs:
            if reste.startswith(en):
                reste, qualif = reste[len(en):], fr
                break
        for en, fr in self.suffixes:
            if reste.endswith(en):
                reste, suffixe = reste[: -len(en)], fr
                break
        base = self._base(reste)
        if base:
            texte = f"{pays}{base}{suffixe}" + (f", {qualif}" if qualif else "")
            return texte[0].upper() + texte[1:], True
        self.non_traduits.add(titre)
        return titre, False


# ------------------------------------------------------------------ lecture des valeurs
def nombre(v) -> tuple[float | None, str | None]:
    """'4.00%' -> (4.0, None) ; '<1.25%' -> (1.25, '<') ; illisible -> (None, None)."""
    return tableau_macro.lire_taux(v)


def badge_decision(consensus, reference) -> dict | None:
    """Décision de banque centrale : « hausse / baisse / statu quo attendu » si le consensus diffère du taux actuel."""
    c, bc = nombre(consensus)
    r, br = nombre(reference)
    if c is None or r is None:
        return None
    if bc or br:   # taux publié comme une borne (BoJ « <1,25 % ») : comparaison seulement si les deux sont identiques
        return {"sens": "statu_quo", "texte": "statu quo attendu", "pb": 0} if (c, bc) == (r, br) else None
    pb = round((c - r) * 100)
    if pb > 0:
        return {"sens": "hausse", "texte": "hausse attendue", "pb": pb}
    if pb < 0:
        return {"sens": "baisse", "texte": "baisse attendue", "pb": pb}
    return {"sens": "statu_quo", "texte": "statu quo attendu", "pb": 0}


# ------------------------------------------------------------------ fenêtre et semaine de référence
def fenetre(maintenant: datetime) -> tuple[datetime, datetime]:
    """Du lundi de la semaine en cours (00:00, Paris) au dimanche de la semaine suivante inclus."""
    paris = fuseau_paris()
    jour = maintenant.astimezone(paris).date()
    lundi = jour - timedelta(days=jour.weekday())
    debut = datetime(lundi.year, lundi.month, lundi.day, tzinfo=paris)
    return debut, debut + timedelta(days=14)


def semaine_reference(maintenant: datetime) -> tuple[str, str]:
    """Semaine « cette semaine » du globe : la semaine en cours, ou la suivante le week-end."""
    jour = maintenant.astimezone(fuseau_paris()).date()
    lundi = jour - timedelta(days=jour.weekday()) + (timedelta(days=7) if jour.weekday() >= 5 else timedelta(0))
    return lundi.isoformat(), (lundi + timedelta(days=6)).isoformat()


# ------------------------------------------------------------------ construction des lignes
class Agenda:
    def __init__(self, config: dict | None, maintenant: datetime):
        self.cfg = (config or {}).get("agenda") or {}
        self.trad = Traducteur(self.cfg)
        self.non_marche = set(self.cfg.get("non_marche") or [])
        self.maintenant = maintenant
        self.paris = fuseau_paris()
        self.debut, self.fin = fenetre(maintenant)
        self.lignes: dict[tuple, dict] = {}
        self.discrets: dict[tuple, dict] = {}

    def dans_fenetre(self, quand: datetime) -> bool:
        return self.debut <= quand.astimezone(self.paris) < self.fin

    def ajouter(self, devise: str, titre_en: str, quand: datetime, impact: str, precedent=None, consensus=None, publie=None,
                source: str = "", heure_connue: bool = True, verifie_le: str | None = None, titre_fr: str | None = None,
                type_force: str | None = None, extra: dict | None = None) -> dict | None:
        if devise not in DEVISES or not self.dans_fenetre(quand):
            return None
        local = quand.astimezone(self.paris)
        jour = local.date().isoformat()
        impact_fr = IMPACTS.get(str(impact or "").lower(), "n/d")
        if titre_en in self.non_marche or impact_fr == "férié":
            texte, _ = self.trad.traduire(titre_en)
            d = self.discrets.setdefault((jour, texte), {"date_paris": jour, "texte": texte, "devises": [], "source": source})
            if devise not in d["devises"]:
                d["devises"].append(devise)
            return None
        cle = (devise, jour, titre_en.lower())
        if cle in self.lignes:   # même évènement vu par une autre source : on complète sans écraser
            e = self.lignes[cle]
            for champ, v in (("precedent", precedent), ("consensus", consensus), ("publie", publie)):
                if e.get(champ) in (None, "") and v not in (None, ""):
                    e[champ] = v
                    e["sources_champs"][champ] = source
            if source not in e["sources"]:
                e["sources"].append(source)
            return e
        fr, ok = (titre_fr, True) if titre_fr else self.trad.traduire(titre_en)
        typ = type_force or type_evenement(titre_en)
        sans_heure = not heure_connue or (local.hour, local.minute) == (0, 0)
        e = {"iso_utc": quand.astimezone(timezone.utc).isoformat(timespec="minutes"), "date_paris": jour,
             "heure_paris": "journée" if sans_heure else local.strftime("%H:%M"), "heure_connue": not sans_heure,
             "devise": devise, "evenement": fr, "evenement_en": titre_en, "traduit": ok, "type": typ,
             "impact": impact_fr, "points": POINTS.get(impact_fr, "○○○"),
             "precedent": precedent or None, "consensus": consensus or None, "publie": publie or None,
             "source": source, "sources": [source], "sources_champs": {}, "verifie_le": verifie_le,
             "engrenage": engrenage(titre_en), "simulateur": simulateur(devise, titre_en)}
        e["sources_champs"] = {c: source for c in ("precedent", "consensus", "publie") if e[c]}
        if extra:
            e.update(extra)
        self.lignes[cle] = e
        return e

    def chercher(self, devise: str, jour: str, motif: re.Pattern | str) -> dict | None:
        motif = re.compile(motif, re.I) if isinstance(motif, str) else motif
        return next((e for (d, j, t), e in self.lignes.items() if d == devise and j == jour and motif.search(t)), None)


def _quand_ff(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def _depuis_mois(ag: Agenda, mois: list[dict] | None, verifie_le: str | None) -> None:
    for it in mois or []:
        if not it.get("dateline") or not it.get("nom"):
            continue
        quand = datetime.fromtimestamp(int(it["dateline"]), tz=timezone.utc)
        ag.ajouter(str(it.get("devise") or "").upper(), str(it["nom"])[:150], quand, it.get("impact") or "",
                   it.get("precedent"), it.get("prevision"), it.get("reel"), SOURCE_MOIS, verifie_le=verifie_le)


def _depuis_semaine(ag: Agenda, ff_brut: str | None, verifie_le: str | None) -> None:
    try:
        items = json.loads(ff_brut) if ff_brut else []
    except ValueError:
        items = []
    for it in items:
        quand = _quand_ff(it.get("date"))
        if quand is None:
            continue
        ag.ajouter(str(it.get("country", "")).upper(), str(it.get("title", ""))[:150], quand, str(it.get("impact", "")),
                   it.get("previous") or None, it.get("forecast") or None, it.get("actual") or None, SOURCE_SEMAINE,
                   verifie_le=verifie_le)


def _depuis_glissants(ag: Agenda, glissants: list[dict] | None) -> None:
    for g in glissants or []:
        if not g.get("reel"):
            continue
        for (d, j, t), e in ag.lignes.items():
            if d == g.get("devise") and t == str(g.get("evenement", "")).lower() and j == g.get("date") and not e["publie"]:
                e["publie"] = g["reel"]
                e["sources_champs"]["publie"] = "magasin glissant des publications (ForexFactory)"


def _depuis_registre(ag: Agenda, registre: dict | None) -> None:
    for cle_case, case in ((registre or {}).get("cases") or {}).items():
        prev = case.get("prevision") or {}
        if not prev.get("dateline"):
            continue
        quand = datetime.fromtimestamp(int(prev["dateline"]), tz=timezone.utc)
        devise = case.get("devise") or cle_case.split("|")[0]
        titre = str(prev.get("nom_ff") or case.get("indicateur"))
        actuel = case.get("actuel") or {}
        e = ag.ajouter(devise, titre, quand, str(prev.get("impact") or ""),
                       None if actuel.get("origine") else actuel.get("valeur"), prev.get("valeur"), None, SOURCE_REGISTRE)
        if e is not None and actuel.get("origine") and e.get("precedent") is None:   # USD : taux effectif FRED (DFF)
            e["raison_precedent"] = f"valeur du registre = {actuel.get('source') or 'valeur de repli'}, pas la dernière publication"


def dates_reunions(cfg_bc: dict | None, debut: date, fin: date) -> list[date]:
    """Dates officielles (config) entre debut et fin inclus ; PBoC : le 20 du mois, reporté au lundi si week-end."""
    cfg_bc = cfg_bc or {}
    if cfg_bc.get("regle") == "lpr_20":
        sortie, a, m = [], debut.year, debut.month
        while date(a, m, 1) <= fin:
            d = date(a, m, 20)
            d += timedelta(days=(7 - d.weekday()) % 7 if d.weekday() >= 5 else 0)
            if debut <= d <= fin:
                sortie.append(d)
            a, m = (a + 1, 1) if m == 12 else (a, m + 1)
        return sortie
    return [date.fromisoformat(str(d)) for d in cfg_bc.get("dates") or [] if debut <= date.fromisoformat(str(d)) <= fin]


def _depuis_officiels(ag: Agenda, reunions: dict) -> None:
    """Chaque réunion officielle de la fenêtre : confirme la ligne ForexFactory du jour, ou crée la ligne."""
    for devise, cfg_bc in (reunions or {}).items():
        for d in dates_reunions(cfg_bc, ag.debut.date(), (ag.fin - timedelta(days=1)).date()):
            jour = d.isoformat()
            officiel = {"source": cfg_bc.get("source"), "url": cfg_bc.get("url"), "verifie_le": cfg_bc.get("verifie_le"),
                        "statut": cfg_bc.get("statut"), "note": cfg_bc.get("note")}
            existante = ag.chercher(devise, jour, DECISION)
            if existante:
                existante["officiel"] = officiel
                continue
            heure, connue = (cfg_bc.get("heure") or "12:00"), bool(cfg_bc.get("heure"))
            quand = datetime.fromisoformat(f"{jour}T{heure}").replace(tzinfo=fuseau(cfg_bc.get("fuseau") or "UTC"))
            nom = "LPR 1 an (PBoC)" if cfg_bc.get("regle") == "lpr_20" else f"Décision de politique monétaire ({COURTS[devise]})"
            e = ag.ajouter(devise, f"{COURTS[devise]} policy decision", quand, "high", source=cfg_bc.get("source") or "",
                           heure_connue=connue, verifie_le=cfg_bc.get("verifie_le"), titre_fr=nom, type_force="Réunion BC",
                           extra={"officiel": officiel, "engrenage": 2})
            if e is not None and not connue:
                e["raison_heure"] = "heure donnée par ForexFactory la semaine de la réunion"


def _depuis_fred(ag: Agenda, fred: dict | None, cfg_fred: dict | None) -> None:
    for r in (fred or {}).get("dates") or []:
        conf = (cfg_fred or {}).get(r.get("release_name"))
        if not conf:
            continue
        nom, impact, motif = conf[0], conf[1], conf[2] if len(conf) > 2 else conf[0]
        jour = r.get("date")
        existante = ag.chercher("USD", jour, motif)
        if existante:
            existante.setdefault("confirme_par", []).append(f"FRED releases/dates : {r['release_name']}")
            continue
        quand = datetime.fromisoformat(f"{jour}T00:00").replace(tzinfo=fuseau("America/New_York"))
        e = ag.ajouter("USD", r["release_name"], quand, {"fort": "high", "moyen": "medium"}.get(impact, "low"),
                       source="FRED releases/dates (calendrier des publications)", heure_connue=False,
                       verifie_le=(fred or {}).get("collecte_le"), titre_fr=nom, type_force="Chiffre")
        if e is not None:
            e["raison_heure"] = "FRED donne la date, pas l'heure (ForexFactory la donne la semaine de la publication)"
            e["raison_consensus"] = "consensus publié par ForexFactory la semaine de la publication"


def _depuis_grands(ag: Agenda, grands: list[dict] | None) -> list[dict]:
    """Grands rendez-vous : dans l'agenda s'ils tombent dans la fenêtre ; tous ceux à venir dans la liste à part."""
    a_venir = []
    aujourd = ag.maintenant.astimezone(ag.paris).date().isoformat()
    for g in grands or []:
        if str(g.get("fin") or g["date"]) < aujourd:
            continue
        a_venir.append({k: g.get(k) for k in ("date", "fin", "titre", "devises", "statut", "source", "verifie_le")})
        quand = datetime.fromisoformat(f"{g['date']}T00:00").replace(tzinfo=ag.paris)
        for devise in (g.get("devises") or ["USD"])[:1]:
            deja = ag.chercher(devise, g["date"], GRAND)   # même rendez-vous déjà vu par ForexFactory : on le complète
            if deja:
                deja.update({"evenement": g["titre"], "statut_source": g.get("statut"), "devises_concernees": g.get("devises"),
                             "officiel": {"source": g.get("source"), "verifie_le": g.get("verifie_le"), "statut": g.get("statut")}})
                continue
            ag.ajouter(devise, g["titre"], quand, "high", source=g.get("source") or "", heure_connue=False,
                       verifie_le=g.get("verifie_le"), titre_fr=g["titre"], type_force="Grand rendez-vous",
                       extra={"statut_source": g.get("statut"), "devises_concernees": g.get("devises")})
    return sorted(a_venir, key=lambda g: g["date"])


# ------------------------------------------------------------------ réaction passée
def _reaction_simulateur(e: dict, impact: dict | None) -> dict | None:
    couple = ((impact or {}).get("couples") or {}).get(f"{e['simulateur']}|USD") if e.get("simulateur") else None
    sc = (couple or {}).get("scenarios") or {}
    if not sc.get("hausse|1") or not sc.get("baisse|1"):
        return None
    cote = {}
    for nom, s in (("au_dessus", sc["hausse|1"].get("demain") or {}), ("au_dessous", sc["baisse|1"].get("demain") or {})):
        cote[nom] = {"n": s.get("n"), "mediane": s.get("mediane"), "wilson": s.get("borne_wilson_90"),
                     "faible": (s.get("n") or 0) < MIN_CAS}
    return {"mesure": "force de l'USD (panier), séance suivante, en %", "cote": cote,
            "source": "simulateur d'impact : publications ALFRED sur 15-20 ans et cours sur 5 ans",
            "lien": f"#scenarios/i={e['simulateur']}",
            "lecture": "au-dessus / au-dessous de la publication précédente (variation de la publication)"}


def _reaction_archive(e: dict, archive: dict | None, series: dict) -> dict | None:
    paire, sens = PAIRE_PRINCIPALE[e["devise"]]
    pts = series.get(paire) or []
    if not pts:
        return None
    dates = [d for d, _ in pts]
    valeurs = dict(pts)
    cas = {"au_dessus": [], "au_dessous": []}
    for p in ((archive or {}).get("publications") or {}).values():
        if p.get("devise") != e["devise"] or str(p.get("nom", "")).lower() != e["evenement_en"].lower():
            continue
        r, _ = nombre(p.get("reel"))
        ref, _ = nombre(p.get("prevision") or p.get("precedent"))
        if r is None or ref is None or r == ref:
            continue
        j = p.get("date")
        avant = [d for d in dates if d <= j]
        apres = [d for d in dates if d > j]
        if not avant or not apres:
            continue
        var = sens * (valeurs[apres[0]] / valeurs[avant[-1]] - 1) * 100
        cas["au_dessus" if r > ref else "au_dessous"].append(var)
    if not cas["au_dessus"] and not cas["au_dessous"]:
        return None
    from core.impact import borne_basse_wilson
    cote = {}
    for nom, vs in cas.items():
        attendu = 1 if nom == "au_dessus" else -1
        cote[nom] = {"n": len(vs), "mediane": round(statistics.median(vs), 3) if vs else None,
                     "wilson": borne_basse_wilson(sum(1 for v in vs if v * attendu > 0), len(vs)) if vs else None,
                     "faible": len(vs) < MIN_CAS}
    return {"mesure": f"force de la devise lue sur {paire}, séance suivante, en %", "cote": cote,
            "source": "archive des publications du site (depuis le 24/10/2026) et cours sur 5 ans",
            "lien": "#scenarios", "lecture": "réel au-dessus / au-dessous du consensus (ou du précédent sans consensus)"}


def reactions(ag: Agenda, impact: dict | None, archive: dict | None, series: dict) -> None:
    for e in ag.lignes.values():
        if e["impact"] != "fort" or e["type"] not in ("Chiffre", "Réunion BC"):
            continue
        r = _reaction_simulateur(e, impact) or _reaction_archive(e, archive, series)
        e["reaction"] = r
        if r is None:
            e["raison_reaction"] = ("pas d'historique des publications passées pour cet évènement (ALFRED ne couvre que "
                                    "les États-Unis ; archive du site commencée le 24/10/2026)")


# ------------------------------------------------------------------ banques centrales
def _references_taux(registre: dict | None, macro: dict | None) -> dict[str, dict]:
    """Taux actuel servant de référence au badge : registre ; USD : borne haute de la fourchette cible (FRED DFEDTARU),
    car ForexFactory publie la décision de la Fed comme une borne haute."""
    refs = {}
    for devise in DEVISES:
        actuel = (((registre or {}).get("cases") or {}).get(rm.cle("taux_directeur", devise)) or {}).get("actuel") or {}
        if actuel.get("valeur") and not actuel.get("origine"):
            refs[devise] = {"valeur": actuel["valeur"], "source": f"registre macro ({actuel.get('source') or 'ForexFactory'})",
                            "date": actuel.get("date_pub")}
    haute = (((macro or {}).get("series") or {}).get("fed_cible_haute")) or {}
    if haute.get("valeur") is not None:
        refs["USD"] = {"valeur": f"{float(haute['valeur']):.2f}%", "source": "FRED (DFEDTARU, borne haute de la fourchette cible)",
                       "date": haute.get("date")}
    return refs


def badges(ag: Agenda, refs: dict[str, dict]) -> None:
    for e in ag.lignes.values():
        if e["type"] != "Réunion BC":
            continue
        ref = e.get("precedent") or (refs.get(e["devise"]) or {}).get("valeur")
        b = badge_decision(e.get("consensus"), ref)
        if b:
            b["reference"] = ref
            b["source_reference"] = "précédent publié" if e.get("precedent") else (refs.get(e["devise"]) or {}).get("source")
        e["badge"] = b
        if b is None:
            e["raison_badge"] = ("consensus non publié" if not e.get("consensus") else
                                 "taux publié comme une borne : pas de comparaison chiffrée" if "<" in str(e.get("consensus")) + str(ref)
                                 else "taux actuel n/d")


def taux_principal(devise: str, actuel: dict, macro: dict | None) -> dict:
    """Taux affiché et son type. Fed : fourchette cible (FRED DFEDTARL / DFEDTARU) ; BCE : taux de dépôt automatique
    (FRED ECBDFR ou API de la BCE), le refinancement du registre en information secondaire ; sinon le registre."""
    series = (macro or {}).get("series") or {}
    if devise == "USD":
        bas, haut = series.get("fed_cible_basse") or {}, series.get("fed_cible_haute") or {}
        if bas.get("valeur") is not None and haut.get("valeur") is not None:
            return {"texte": f"{bas['valeur']:.2f}–{haut['valeur']:.2f}%", "valeur": haut["valeur"], "type": "fourchette cible",
                    "source": "FRED (DFEDTARL / DFEDTARU)", "date": haut.get("date"),
                    "secondaire": f"taux effectif {actuel.get('valeur')}" if actuel.get("valeur") else None}
    if devise == "EUR":
        dep = ((macro or {}).get("taux_directeurs") or {}).get("EUR") or {}
        if dep.get("type") == "dépôt" and dep.get("taux") is not None:
            return {"texte": f"{dep['taux']:.2f}%", "valeur": dep["taux"], "type": "dépôt", "source": dep.get("source"),
                    "date": dep.get("date"),
                    "secondaire": f"refinancement {actuel.get('valeur')} (registre macro)" if actuel.get("valeur") else None}
        return {"texte": actuel.get("valeur"), "valeur": None, "type": "refinancement",
                "source": actuel.get("source"), "date": actuel.get("date_pub"),
                "secondaire": None, "raison": "taux de dépôt n/d (ECBDFR et API BCE indisponibles) : refinancement affiché"}
    return {"texte": actuel.get("valeur"), "valeur": None, "type": "taux directeur", "source": actuel.get("source"),
            "date": actuel.get("date_pub"), "secondaire": None}


def banques_centrales(registre: dict | None, config: dict | None, ag: Agenda, refs: dict[str, dict],
                      macro: dict | None = None) -> list[dict]:
    infos = tableau_macro.infos_taux(registre or {}, DEVISES)
    officiels = ((config or {}).get("agenda") or {}).get("reunions") or {}
    aujourd = ag.maintenant.astimezone(ag.paris).date()
    sem_debut, sem_fin = semaine_reference(ag.maintenant)
    sortie = []
    for devise in DEVISES:
        case = ((registre or {}).get("cases") or {}).get(rm.cle("taux_directeur", devise)) or {}
        actuel = case.get("actuel") or {}
        valeur, borne = tableau_macro.lire_taux(actuel.get("valeur"))
        i = infos.get(devise) or {}
        cfg_bc = officiels.get(devise) or {}
        reunions = [{"date": d.isoformat(), "source": cfg_bc.get("source"), "statut": cfg_bc.get("statut")}
                    for d in dates_reunions(cfg_bc, aujourd, aujourd + timedelta(days=400))]
        if not reunions and i.get("prochaine") and all(r["date"] != i["prochaine"][:10] for r in reunions) and i["prochaine"][:10] >= aujourd.isoformat():
            reunions.append({"date": i["prochaine"][:10], "source": "registre macro (ForexFactory)", "statut": "secondaire"})
        reunions = sorted(reunions, key=lambda r: r["date"])[:3]
        prochaine = reunions[0]["date"] if reunions else None
        ligne = next((e for e in ag.lignes.values() if e["devise"] == devise and e["type"] == "Réunion BC"
                      and e["date_paris"] == prochaine), None)
        tp = taux_principal(devise, actuel, macro)
        if tp.get("valeur") is not None:
            valeur, borne = tp["valeur"], None
        sortie.append({
            "devise": devise, "banque": BANQUES[devise], "court": COURTS[devise], "siege": SIEGES[devise],
            "taux": valeur, "borne": borne, "taux_texte": tp.get("texte") or actuel.get("valeur"), "type_taux": tp["type"],
            "taux_secondaire": tp.get("secondaire"), "raison_taux": tp.get("raison"),
            "date_taux": tp.get("date") or actuel.get("date_pub"),
            "source_taux": tp.get("source") or actuel.get("source"), "reference_badge": refs.get(devise),
            "variation_pb": i.get("variation_pb"),
            "date_variation": i.get("date_decision") if i.get("variation_pb") is not None else None,
            "raison_variation": i.get("raison_variation"), "prochaine": prochaine,
            "heure_prochaine": (ligne or {}).get("heure_paris"),
            "cette_semaine": bool(prochaine and sem_debut <= prochaine <= sem_fin),
            "consensus_prochaine": (ligne or {}).get("consensus"), "badge": (ligne or {}).get("badge"),
            "reunions": reunions, "calendrier": {k: cfg_bc.get(k) for k in ("source", "url", "verifie_le", "statut", "note")},
            "raison_reunions": None if len(reunions) >= 3 else
            (cfg_bc.get("note") or "calendrier officiel au-delà non publié") + " : réunions suivantes n/d"})
    return sortie


# ------------------------------------------------------------------ calcul d'ensemble
def calculer(ff_brut: str | None, glissants: list[dict] | None, registre: dict | None, config: dict | None,
             maintenant: datetime | None = None, mois: list[dict] | None = None, fred: dict | None = None,
             impact: dict | None = None, archive: dict | None = None, series: dict | None = None,
             macro: dict | None = None, verifs: dict | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    ag = Agenda(config, maintenant)
    cfg = ag.cfg
    verifs = verifs or {}
    _depuis_mois(ag, mois, verifs.get("mois"))
    _depuis_semaine(ag, ff_brut, verifs.get("semaine"))
    _depuis_glissants(ag, glissants)
    _depuis_registre(ag, registre)
    _depuis_officiels(ag, cfg.get("reunions") or {})
    _depuis_fred(ag, fred, cfg.get("fred_publications") or {})
    grands = _depuis_grands(ag, cfg.get("grands_rendez_vous"))
    refs = _references_taux(registre, macro)
    badges(ag, refs)
    reactions(ag, impact, archive, series or {})
    for e in ag.lignes.values():
        if not e.get("consensus"):
            e.setdefault("raison_consensus", "pas de consensus publié" if e["type"] in ("Chiffre", "Réunion BC") else
                         "sans objet (pas un chiffre)")
        e["sources_champs"] = e.get("sources_champs") or {}
    evts = sorted(ag.lignes.values(), key=lambda e: e["iso_utc"])
    jours = []
    for k in range(14):
        d = (ag.debut.date() + timedelta(days=k)).isoformat()
        du_jour = [e for e in evts if e["date_paris"] == d]
        disc = [v for (j, _), v in ag.discrets.items() if j == d]
        if du_jour or disc or (ag.debut.date() + timedelta(days=k)).weekday() < 5:
            jours.append({"date": d, "evenements": du_jour, "discrets": disc,
                          "n_forts": sum(1 for e in du_jour if e["impact"] == "fort")})
    comptes = {t: sum(1 for e in evts if e["type"] == t) for t in TYPES}
    sem_debut, sem_fin = semaine_reference(maintenant)
    consensus_ok = bool(ff_brut) or bool(mois)
    return {"genere_le": maintenant.isoformat(timespec="seconds"), "fuseau": "Europe/Paris",
            "debut": ag.debut.date().isoformat(), "fin": (ag.fin - timedelta(days=1)).date().isoformat(),
            "semaine_reference": {"debut": sem_debut, "fin": sem_fin},
            "aujourdhui": maintenant.astimezone(ag.paris).date().isoformat(),
            "jours": jours, "n_evenements": len(evts), "comptes": comptes,
            "n_forts": sum(1 for e in evts if e["impact"] == "fort"),
            "banques_centrales": banques_centrales(registre, config, ag, refs, macro),
            "grands_rendez_vous": grands, "grands_rendez_vous_absents": cfg.get("grands_rendez_vous_absents"),
            "prises_de_parole": [e for e in evts if e["type"] in ("Discours", "Conférence")],
            "non_traduits": sorted(ag.trad.non_traduits),
            "consensus": {"source": "ForexFactory", "etat": "fonctionne" if consensus_ok else "n/d",
                          "raison": None if consensus_ok else "flux ForexFactory non collecté (ni semaine ni page « mois »)",
                          "attribution": "Consensus : ForexFactory (flux public JSON de la semaine et page « mois »)"},
            "sources": {"mois": {"evenements": len(mois or []), "verifie_le": verifs.get("mois")},
                        "semaine": {"present": bool(ff_brut), "verifie_le": verifs.get("semaine")},
                        "fred": {"dates": len((fred or {}).get("dates") or []), "erreurs": (fred or {}).get("erreurs") or [],
                                 "verifie_le": (fred or {}).get("collecte_le")},
                        "officiels": {d: {k: c.get(k) for k in ("source", "verifie_le", "statut")}
                                      for d, c in (cfg.get("reunions") or {}).items()}},
            "raison_vide": None if evts else "aucune source de calendrier disponible",
            "note": "Valeur publiée dès qu'elle existe dans les données collectées. Aide à la décision, jamais un ordre."}


def prochain_rendez_vous(agenda_donnees: dict | None, impacts=("fort",)) -> dict | None:
    """Premier évènement à fort impact, à venir, rattaché à un engrenage (cockpit : « peut faire basculer »)."""
    maintenant = datetime.now(timezone.utc).isoformat(timespec="minutes")
    a_venir = (agenda_donnees or {}).get("aujourdhui") is not None
    for j in (agenda_donnees or {}).get("jours") or []:
        for e in j["evenements"]:
            if e["impact"] in impacts and e.get("engrenage") and not e.get("publie") and (not a_venir or e["iso_utc"] >= maintenant):
                return e
    return None


# ------------------------------------------------------------------ caches et collectes
def lire_caches(racine: Path) -> tuple[str | None, list[dict]]:
    cache = Path(racine) / "data" / "cache"
    try:
        ff = json.loads((cache / "scrape_forexfactory.json").read_text(encoding="utf-8")).get("contenu")
    except (OSError, ValueError):
        ff = None
    try:
        glissants = json.loads((cache / "evenements_glissants.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        glissants = []
    return ff, glissants if isinstance(glissants, list) else []


def _lire_json(chemin: Path) -> dict | list | None:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def memoriser_mois(evenements: list[dict], dossier_cache: str | Path, maintenant: datetime | None = None) -> None:
    """Page « mois » ForexFactory déjà lue (tableau macro) : garde les évènements de -14 j à +60 j pour l'agenda, sans
    requête de plus ; archive les publications (réel) pour la réaction passée."""
    maintenant = maintenant or datetime.now(timezone.utc)
    chemin = Path(dossier_cache) / "calendrier_mois.json"
    ancien = _lire_json(chemin) or {}
    bas, haut = (maintenant - timedelta(days=14)).timestamp(), (maintenant + timedelta(days=60)).timestamp()
    garde = {str(e.get("id") or (e.get("devise"), e.get("nom"), e.get("dateline"))): e for e in ancien.get("evenements") or []}
    for e in evenements or []:
        if e.get("dateline"):
            garde[str(e.get("id") or (e.get("devise"), e.get("nom"), e.get("dateline")))] = {
                k: e.get(k) for k in ("id", "devise", "nom", "impact", "dateline", "reel", "prevision", "precedent")}
    liste = sorted((e for e in garde.values() if bas <= int(e["dateline"]) <= haut), key=lambda e: int(e["dateline"]))
    chemin.write_text(json.dumps({"maj": maintenant.isoformat(timespec="seconds"), "evenements": liste}, ensure_ascii=False),
                      encoding="utf-8")
    archiver_publications(evenements, Path(dossier_cache).parent / "archives" / "publications.json")


def archiver_publications(evenements: list[dict], chemin: Path) -> None:
    archive = _lire_json(chemin) or {}
    pubs = archive.get("publications") or {}
    for e in evenements or []:
        if not e.get("reel") or not e.get("dateline") or str(e.get("impact", "")).lower() not in ("high", "medium"):
            continue
        jour = datetime.fromtimestamp(int(e["dateline"]), tz=timezone.utc).date().isoformat()
        pubs[f"{e.get('devise')}|{e.get('nom')}|{jour}"] = {"devise": e.get("devise"), "nom": e.get("nom"), "date": jour,
                                                           "reel": e.get("reel"), "prevision": e.get("prevision"),
                                                           "precedent": e.get("precedent")}
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"debut": archive.get("debut") or date.today().isoformat(), "publications": pubs},
                                 ensure_ascii=False, indent=0), encoding="utf-8")


def collecter_fred(cle: str, aujourdhui: date, jours: int = 15) -> dict:
    """FRED releases/dates : UNE requête (dates des publications US à venir, sans heure)."""
    import requests
    from core.secrets import masquer_secrets
    if not cle:
        return {"dates": [], "erreurs": ["FRED_API_KEY absente"], "collecte_le": aujourdhui.isoformat()}
    try:
        rep = requests.get("https://api.stlouisfed.org/fred/releases/dates",
                           params={"api_key": cle, "file_type": "json", "realtime_start": aujourdhui.isoformat(),
                                   "realtime_end": (aujourdhui + timedelta(days=jours)).isoformat(),
                                   "include_release_dates_with_no_data": "true", "sort_order": "asc", "limit": 1000},
                           timeout=30)
        rep.raise_for_status()
        dates = [{"date": d["date"], "release_name": d["release_name"]} for d in rep.json().get("release_dates", [])]
        return {"dates": dates, "erreurs": [], "collecte_le": aujourdhui.isoformat()}
    except Exception as exc:  # noqa: BLE001
        return {"dates": [], "erreurs": [masquer_secrets(str(exc))[:200]], "collecte_le": aujourdhui.isoformat()}


def _series_principales(h5, technique) -> dict:
    from core import paires
    sortie = {}
    for paire, _ in set(PAIRE_PRINCIPALE.values()):
        try:
            sortie[paire] = paires.serie_paire(h5, technique, paire)
        except Exception:  # noqa: BLE001
            sortie[paire] = []
    return sortie


def ecrire(racine: str | Path, registre: dict | None, config: dict, h5=None, technique: dict | None = None) -> dict | None:
    try:
        import os
        from core import collecte_cache
        racine = Path(racine)
        cache = racine / "data" / "cache"
        ff, glissants = lire_caches(racine)
        mois = _lire_json(cache / "calendrier_mois.json") or {}
        semaine = _lire_json(cache / "scrape_forexfactory.json") or {}
        aujourd = datetime.now(timezone.utc).date()
        try:
            fred = collecte_cache.avec_cache("agenda_fred", cache, aujourd, True, collecter_fred,
                                             os.environ.get("FRED_API_KEY", "").strip(), aujourd)
        except Exception as exc:  # noqa: BLE001
            fred = {"dates": [], "erreurs": [str(exc)[:200]]}
        docs = racine / config.get("publication_web", {}).get("dossier_docs", "docs") / "data"
        macro = (_lire_json(cache / "collecte_macro.json") or {}).get("donnees")
        donnees = calculer(ff, glissants, registre, config, mois=mois.get("evenements"), fred=fred,
                           impact=_lire_json(docs / "impact.json"),
                           archive=_lire_json(racine / "data" / "archives" / "publications.json"),
                           series=_series_principales(h5, technique) if h5 is not None else {}, macro=macro,
                           verifs={"mois": (mois.get("maj") or "")[:16] or None, "semaine": semaine.get("date")})
        (docs / "agenda.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return donnees
    except Exception as exc:  # noqa: BLE001
        log.error("agenda.json non écrit : %s", exc)
        return None
