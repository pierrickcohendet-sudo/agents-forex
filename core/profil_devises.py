"""Profil des devises (lot V6, partie A) : ancrage structurel, moteur du moment, posture de la banque centrale,
dynamique macro, importance de la semaine et état. Remplace les notes de confluence en % et le risk on / risk off
par devise. 100 % Python, sans appel au modèle ; chaque chiffre a sa source et sa date, sinon « n/d » et la raison.

Moteur du moment : corrélation des variations quotidiennes de l'indice de force de la devise (série unique 5 ans,
Twelve Data raccordé à la Fed H.10) avec chaque moteur candidat de config.profil_devises, sur 60 puis 20 séances
communes. Dominant : plus forte corrélation en valeur absolue sur 60 séances, si elle atteint le seuil (0,30) et
garde le même signe sur 20 séances. C'est une corrélation, jamais une cause.

État (règle documentée dans config.yaml, profil_devises) :
1. « Ancrage contredit » quand un ancrage mesurable est corrélé au-delà du seuil, de façon stable, dans le sens
   opposé au sens attendu ;
2. sinon somme de trois signaux (banque centrale, surprises macro 30 j, tendance 20 séances) : ≥ 2 « Soutenue »,
   ≤ −2 « Sous pression », sinon « Sans direction ».
"""
from __future__ import annotations

import json
import logging
import math
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

ETATS = ("Soutenue", "Sous pression", "Sans direction", "Ancrage contredit")
SOURCE_FORCE = "indice de force de la devise (Twelve Data raccordé à la Fed H.10, calcul Python)"


def fr(v: float | None, d: int = 2, signe: bool = False) -> str:
    """Nombre à la française : virgule décimale, vrai signe moins."""
    if v is None:
        return "n/d"
    t = f"{v:+.{d}f}" if signe else f"{v:.{d}f}"
    return t.replace(".", ",").replace("-", "−")


def _jj_mm(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso and len(iso) >= 10 else "n/d"


def _num(v) -> float | None:
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v or "").replace("−", "-"))
    return float(m.group(0).replace(",", ".")) if m else None


# ------------------------------------------------------------- corrélations
def _rendements(points: list[tuple[str, float]], en_points: bool) -> dict[str, float]:
    sortie = {}
    for (_, a), (d, b) in zip(points, points[1:]):
        if en_points:
            sortie[d] = b - a
        elif a and b and a > 0 and b > 0:
            sortie[d] = math.log(b / a)
    return sortie


def correlation(force: dict[str, float], moteur: dict[str, float], seances: int) -> dict | None:
    """Corrélation sur les `seances` dernières séances communes -> {r, n, du, au} (None si trop peu de points)."""
    communes = sorted(set(force) & set(moteur))[-seances:]
    if len(communes) < max(10, int(seances * 0.75)):
        return None
    try:
        r = statistics.correlation([force[d] for d in communes], [moteur[d] for d in communes])
    except statistics.StatisticsError:
        return None
    return {"r": round(r, 2), "n": len(communes), "du": communes[0], "au": communes[-1]}


def serie_moteur(m: dict, h5, historiques: dict | None, veille: str | None) -> tuple[list, str | None]:
    """Série d'un moteur jusqu'à la veille : Twelve Data (cours du jour, `serie_twelve`) quand elle existe, sinon la
    série 5 ans FRED. -> (points, source)."""
    pts, source = [], None
    if m.get("serie_twelve"):
        s = ((historiques or {}).get("series") or {}).get(m["serie_twelve"]) or {}
        pts = [(str(p[0])[:10], float(p[1])) for p in s.get("points") or [] if p and p[1] is not None]
        source = s.get("source")
    if len(pts) < 70 and m.get("serie") and h5 is not None:
        pts, source = h5.serie(m["serie"]), h5.source(m["serie"]) or m["serie"]
    if veille:
        pts = [p for p in pts if p[0] <= veille]
    return pts, source


def moteurs_du_moment(h5, technique: dict | None, devise: str, cfg: dict, historiques: dict | None = None,
                      aujourd: date | None = None) -> dict:
    """Corrélations 60 / 20 séances de la devise avec ses moteurs candidats ; dominant ou « aucun moteur dominant ».
    Calcul jusqu'à la veille (séance du jour incomplète), Twelve Data quand FRED est en retard (or, actions)."""
    defs = cfg.get("moteurs") or {}
    seuil = float(cfg.get("seuil_correlation", 0.30))
    longues, courtes = int(cfg.get("seances_longues", 60)), int(cfg.get("seances_courtes", 20))
    veille = (aujourd - timedelta(days=1)).isoformat() if aujourd else None
    pts = h5.force(devise, technique) if h5 is not None else []
    if veille:
        pts = [p for p in pts if p[0] <= veille]
    force = _rendements(pts, False)
    mesures, non_testes = [], []
    for cle in ((cfg.get("devises") or {}).get(devise) or {}).get("candidats") or []:
        m = defs.get(cle) or {}
        if not m.get("serie") and not m.get("serie_twelve"):
            non_testes.append({"moteur": cle, "libelle": m.get("libelle", cle), "raison": m.get("raison") or "série absente"})
            continue
        serie, source = serie_moteur(m, h5, historiques, veille)
        if not serie or not force:
            non_testes.append({"moteur": cle, "libelle": m.get("libelle", cle),
                               "raison": "série absente de l'historique 5 ans" if force else "indice de force indisponible"})
            continue
        rm = _rendements(serie, str(m.get("serie") or "").startswith("USD_") and not m.get("serie_twelve"))
        c60, c20 = correlation(force, rm, longues), correlation(force, rm, courtes)
        if c60 is None:
            non_testes.append({"moteur": cle, "libelle": m.get("libelle", cle), "raison": f"moins de {longues} séances communes"})
            continue
        mesures.append({"moteur": cle, "libelle": m["libelle"], "nom": m.get("nom") or m["libelle"], "source": source,
                        "derniere_observation": serie[-1][0] if serie else None,
                        "r60": c60["r"], "r20": c20["r"] if c20 else None, "n60": c60["n"], "du": c60["du"], "au": c60["au"],
                        "stable": bool(c20 and c20["r"] * c60["r"] > 0)})
    mesures.sort(key=lambda x: -abs(x["r60"]))
    dominant = next((x for x in mesures if abs(x["r60"]) >= seuil and x["stable"]), None)
    if dominant:
        texte = (f"{dominant['libelle']} : corrélation {fr(dominant['r60'], signe=True)} sur {dominant['n60']} séances "
                 f"({_jj_mm(dominant['du'])} → {_jj_mm(dominant['au'])}), {fr(dominant['r20'], signe=True)} sur {courtes} séances ; "
                 f"dernière observation commune : {_jj_mm(dominant['au'])}")
    elif mesures:
        p = mesures[0]
        motif = ("sous le seuil de " + fr(seuil)) if abs(p["r60"]) < seuil else f"signe différent sur {courtes} séances"
        texte = f"Aucun moteur dominant (le plus corrélé : {p['libelle']}, {fr(p['r60'], signe=True)} sur {p['n60']} séances, {motif})"
    else:
        texte = "Aucun moteur dominant : aucune corrélation mesurable (séries absentes)"
    return {"dominant": dominant, "texte": texte, "mesures": mesures, "non_testes": non_testes, "seuil": seuil,
            "seances": [longues, courtes], "jusqu_au": veille,
            "source": f"{SOURCE_FORCE} ; moteurs : Twelve Data pour l'or (XAU/USD) et les actions (SPY), sinon FRED",
            "avertissement": "Corrélation des variations quotidiennes : elle décrit ce qui bouge ensemble, pas une cause."}


def ancrages(devise: str, cfg: dict, moteurs: dict) -> list[dict]:
    """Ancrages de la devise, chacun confronté à la corrélation de son moteur (confirmé / contredit / non mesurable)."""
    seuil = float(cfg.get("seuil_correlation", 0.30))
    par_moteur = {m["moteur"]: m for m in moteurs["mesures"]}
    absents = {m["moteur"]: m["raison"] for m in moteurs["non_testes"]}
    sortie = []
    for a in ((cfg.get("devises") or {}).get(devise) or {}).get("ancrages") or []:
        m = par_moteur.get(a.get("moteur"))
        verdict, texte = "non mesurable", None
        if not a.get("moteur") or not a.get("sens"):
            texte = "pas de moteur quotidien mesurable"
        elif m is None:
            texte = absents.get(a["moteur"]) or "moteur non mesuré"
        elif abs(m["r60"]) < seuil or not m["stable"]:
            verdict, texte = "faible", f"corrélation {fr(m['r60'], signe=True)} avec {m['libelle']} sur {m['n60']} séances : peu marquée"
        elif m["r60"] * a["sens"] > 0:
            verdict, texte = "confirmé", f"corrélation {fr(m['r60'], signe=True)} avec {m['libelle']} sur {m['n60']} séances, dans le sens attendu"
        else:
            verdict, texte = "contredit", (f"corrélation {fr(m['r60'], signe=True)} avec {m['libelle']} sur {m['n60']} séances, "
                                           f"{'positive' if a['sens'] < 0 else 'négative'} alors que l'ancrage attend l'inverse")
        sortie.append({"libelle": a["libelle"], "texte": a.get("texte"), "moteur": a.get("moteur"), "sens": a.get("sens"),
                       "verdict": verdict, "mesure": texte, "r60": m["r60"] if m else None})
    return sortie


# ------------------------------------------------------- banque centrale, macro
def derniere_decision(devise: str, cfg: dict, publications: dict | None, agenda: dict | None, aujourd: date) -> dict | None:
    """Dernière décision de taux connue (archive des publications puis Agenda) contre consensus, surprise en pb."""
    noms = set((cfg.get("decisions") or {}).get(devise) or [])
    vues = []
    for p in ((publications or {}).get("publications") or {}).values():
        if p.get("devise") == devise and p.get("nom") in noms and p.get("reel") and p.get("date", "") <= aujourd.isoformat():
            vues.append({"date": p["date"], "publie": p["reel"], "consensus": p.get("prevision"), "precedent": p.get("precedent"),
                         "source": "ForexFactory (archive des publications)"})
    for j in (agenda or {}).get("jours") or []:
        for e in (j.get("evenements") or []) + (j.get("discrets") or []):
            if (e.get("devise") == devise and e.get("type") == "Réunion BC" and e.get("publie")
                    and (e.get("evenement_en") in noms or not noms) and e.get("date_paris", "") <= aujourd.isoformat()):
                vues.append({"date": e["date_paris"], "publie": e["publie"], "consensus": e.get("consensus"),
                             "precedent": e.get("precedent"), "source": e.get("source") or "ForexFactory"})
    if not vues:
        return None
    d = max(vues, key=lambda v: v["date"])
    p, c, prec = _num(d["publie"]), _num(d["consensus"]), _num(d["precedent"])
    decision = ("maintien" if p is not None and prec is not None and p == prec else
                "hausse" if p is not None and prec is not None and p > prec else
                "baisse" if p is not None and prec is not None else "décision")
    surprise = round((p - c) * 100) if p is not None and c is not None else None
    taux = str(d["publie"]).replace(".", ",").replace("%", " %")
    attendu = ("" if surprise is None else ", conforme au consensus" if surprise == 0 else
               f", {str(d['consensus']).replace('.', ',').replace('%', ' %')} attendu ({fr(surprise, 0, True)} pb)")
    return {**d, "decision": decision, "surprise_pb": surprise,
            "texte": f"{decision} à {taux} le {_jj_mm(d['date'])}{attendu}"}


def ton_communique(racine: Path, devise: str) -> dict:
    """Ton du dernier communiqué comparé au précédent (rapports du jour archivés, le plus récent d'abord)."""
    dossier = racine / "data" / "archives" / "rapport_jour"
    for f in sorted(dossier.glob("*.json"), reverse=True)[:30]:
        try:
            com = (((json.loads(f.read_text(encoding="utf-8")).get("textes") or {}).get("communiques")) or {}).get(devise)
        except (OSError, ValueError):
            continue
        if com and com.get("ton"):
            return {"valeur": com["ton"], "date": f.stem, "citations": com.get("citations") or [],
                    "source": "communiqué officiel archivé, ton relu et cité mot pour mot"}
    return {"valeur": None, "raison": "aucun communiqué comparé à son précédent dans les 30 derniers rapports"}


def macro(devise: str, config: dict, registre: dict | None, tableau: dict | None, agenda: dict | None, aujourd: date) -> dict:
    from core import registre_macro as rm
    case = (((registre or {}).get("cases") or {}).get(rm.cle("cpi", devise)) or {})
    actuel = case.get("actuel") or {}
    cible = ((config.get("rapport") or {}).get("cibles_inflation") or {}).get(devise)
    v = actuel.get("valeur_num")
    mensuel = any(m in str(case.get("etiquette") or "").lower() for m in ("m/m", "q/q", "t/t"))
    inflation = {"valeur": v, "texte": actuel.get("valeur"), "cible": cible, "date": actuel.get("date_pub") or actuel.get("periode"),
                 "source": actuel.get("source"),
                 "ecart": round(v - cible, 1) if v is not None and cible is not None and not mensuel else None,
                 "raison": None if v is not None else "inflation absente du registre"}
    if mensuel:
        inflation["raison"] = "inflation publiée en variation mensuelle ou trimestrielle : non comparable à la cible annuelle"
    isu = ((tableau or {}).get("indice_surprise") or {}).get(devise) or {}
    surprise = {"indice": isu.get("indice"), "n": isu.get("n"), "tendance": isu.get("tendance"),
                "source": "indice de surprise 30 jours (tableau macro, calcul Python)",
                "raison": None if isu.get("indice") is not None else "moins de publications comparables sur 30 jours"}
    debut = (aujourd - timedelta(days=21)).isoformat()
    marq = None
    for j in (agenda or {}).get("jours") or []:
        for e in j.get("evenements") or []:
            z = (e.get("ecart") or {}).get("z")
            if (e.get("devise") == devise and e.get("publie") and z is not None and abs(z) >= 0.5
                    and debut <= e.get("date_paris", "") <= aujourd.isoformat()):
                if marq is None or abs(z) > abs(marq["z"]):
                    marq = {"z": z, "date": e["date_paris"], "evenement": e.get("evenement"), "texte": e["ecart"].get("texte")}
    return {"inflation": inflation, "surprise_30j": surprise, "marquante": marq}


def semaine(devise: str, agenda: dict | None, aujourd: date) -> dict:
    """Importance cette semaine (1 à 3) : décision de sa banque centrale et publications fortes dans l'Agenda."""
    lundi = aujourd - timedelta(days=aujourd.weekday())
    dim = (lundi + timedelta(days=6)).isoformat()
    forts, bc = [], None
    for j in (agenda or {}).get("jours") or []:
        if not lundi.isoformat() <= j.get("date", "") <= dim:
            continue
        for e in j.get("evenements") or []:
            if e.get("devise") != devise:
                continue
            if e.get("type") == "Réunion BC" and e.get("impact") == "fort":
                bc = bc or {"date": e["date_paris"], "evenement": e.get("evenement")}
            elif e.get("impact") == "fort":
                forts.append({"date": e["date_paris"], "evenement": e.get("evenement")})
    rdv = [g for g in (agenda or {}).get("grands_rendez_vous") or []
           if devise in (g.get("devises") or []) and lundi.isoformat() <= g.get("date", "") <= dim]
    score = 3 if bc or len(forts) >= 3 else 2 if forts or rdv else 1
    morceaux = ([f"décision de la banque centrale ({_jj_mm(bc['date'])})"] if bc else []) + \
               [f"{g['titre']} ({_jj_mm(g['date'])})" for g in rdv[:1]] + \
               ([f"{len(forts)} publication{'s' if len(forts) > 1 else ''} forte{'s' if len(forts) > 1 else ''}"] if forts else [])
    return {"score": score, "texte": " · ".join(morceaux) if morceaux else "pas de catalyseur majeur dans l'Agenda",
            "banque_centrale": bc, "forts": forts[:6], "rendez_vous": rdv[:3], "source": "Agenda de la semaine"}


# ----------------------------------------------------------------------- état
def tendance(h5, technique, devise: str, seances: int = 20) -> dict | None:
    pts = h5.force(devise, technique) if h5 is not None else []
    if len(pts) <= seances:
        return None
    a, b = pts[-seances - 1], pts[-1]
    return {"pct": round((b[1] / a[1] - 1) * 100, 2), "du": a[0], "au": b[0], "source": SOURCE_FORCE}


def etat(devise: str, cfg: dict, anc: list[dict], bc: dict | None, ton: dict, mac: dict, tend: dict | None,
         aujourd: date) -> dict:
    s = cfg.get("seuils_etat") or {}
    contredit = next((a for a in anc if a["verdict"] == "contredit"), None)
    if contredit:
        return {"valeur": "Ancrage contredit", "raison": f"Ancrage « {contredit['libelle']} » : {contredit['mesure']}.",
                "signaux": None}
    signaux = []
    if bc and bc.get("surprise_pb") is not None and abs(bc["surprise_pb"]) >= float(s.get("surprise_bc_pb", 10)) and \
            (aujourd - date.fromisoformat(bc["date"])).days <= int(s.get("jours_decision", 45)):
        signaux.append((1 if bc["surprise_pb"] > 0 else -1, f"banque centrale : {bc['texte']}"))
    elif ton.get("valeur") in ("plus restrictif", "plus accommodant"):
        signaux.append((1 if ton["valeur"] == "plus restrictif" else -1, f"communiqué {ton['valeur']} ({_jj_mm(ton['date'])})"))
    i = (mac.get("surprise_30j") or {}).get("indice")
    if i is not None and abs(i) >= float(s.get("indice_surprise", 0.3)):
        signaux.append((1 if i > 0 else -1, f"surprises macro 30 j {fr(i, 1, True)}"))
    if tend and abs(tend["pct"]) >= float(s.get("tendance_pct", 1.0)):
        signaux.append((1 if tend["pct"] > 0 else -1, f"force {fr(tend['pct'], 1, True)} % sur 20 séances"))
    total = sum(v for v, _ in signaux)
    seuil = int(s.get("total", 2))
    valeur = "Soutenue" if total >= seuil else "Sous pression" if total <= -seuil else "Sans direction"
    if signaux:
        raison = ("Signaux " + ("favorables" if total > 0 else "défavorables" if total < 0 else "partagés") + " : "
                  + " ; ".join(t for _, t in signaux) + ".")
    else:
        raison = "Aucun signal net : ni surprise de la banque centrale, ni surprises macro marquées, ni tendance sur 20 séances."
    if valeur == "Sans direction" and signaux and abs(total) < seuil:
        raison += f" Total {fr(total, 0, True) if total else '0'} : il faut {seuil} signaux concordants."
    return {"valeur": valeur, "raison": raison, "signaux": [{"sens": v, "texte": t} for v, t in signaux], "total": total}


def lecture(devise: str, nom: str, moteurs: dict, et: dict, sem: dict) -> str:
    """Phrase Python de la carte : moteur, état, semaine (le modèle ne peut que la reformuler)."""
    d = moteurs["dominant"]
    m = (f"{d['nom'][0].upper()}{d['nom'][1:]} est en ce moment le moteur le plus corrélé à la devise "
         f"({fr(d['r60'], signe=True)} sur {d['n60']} séances)" if d else "Aucun moteur ne domine en ce moment")
    return f"{m}. {et['raison']} Cette semaine : {sem['texte']}."


# ---------------------------------------------------------------- assemblage
def calculer(config: dict, h5, technique: dict | None, registre: dict | None, agenda: dict | None,
             publications: dict | None, tableau: dict | None, racine: Path, aujourd: date | None = None,
             historiques: dict | None = None) -> dict:
    aujourd = aujourd or date.today()
    cfg = config.get("profil_devises") or {}
    banques = {b.get("devise"): b for b in (agenda or {}).get("banques_centrales") or []}
    sortie = []
    for devise, dcfg in (cfg.get("devises") or {}).items():
        mot = moteurs_du_moment(h5, technique, devise, cfg, historiques, aujourd)
        anc = ancrages(devise, cfg, mot)
        bc = derniere_decision(devise, cfg, publications, agenda, aujourd)
        ton = ton_communique(racine, devise)
        mac = macro(devise, config, registre, tableau, agenda, aujourd)
        sem = semaine(devise, agenda, aujourd)
        tend = tendance(h5, technique, devise, int(cfg.get("seances_courtes", 20)))
        et = etat(devise, cfg, anc, bc, ton, mac, tend, aujourd)
        b = banques.get(devise) or {}
        prochaine = {"date": b.get("prochaine"), "taux": b.get("taux_texte"), "banque": b.get("court") or b.get("banque"),
                     "raison": None if b.get("prochaine") else "prochaine réunion non publiée dans l'Agenda"}
        bc_txt = (f"{prochaine['banque'] or 'Banque centrale'} : " + (bc["texte"] if bc else "dernière décision n/d (absente de l'archive)")
                  + (f" · prochaine {_jj_mm(prochaine['date'])}" if prochaine["date"] else ""))
        inf = mac["inflation"]
        macro_txt = " · ".join(t for t in (
            (f"inflation {fr(inf['valeur'], 1)} % (cible {fr(inf['cible'], 1)} %)" if inf.get("valeur") is not None and inf.get("ecart") is not None else None),
            (f"surprises 30 j {fr(mac['surprise_30j']['indice'], 1, True)}" if mac["surprise_30j"]["indice"] is not None else None),
            (f"{mac['marquante']['evenement']} {mac['marquante']['texte']}" if mac.get("marquante") and mac["marquante"].get("texte") else None)) if t) \
            or "n/d : aucune publication comparable récente"
        sortie.append({"devise": devise, "nom": dcfg.get("nom", devise), "ancrages": anc, "moteur": mot,
                       "banque_centrale": {"derniere": bc, "prochaine": prochaine, "ton": ton, "texte": bc_txt},
                       "macro": {**mac, "texte": macro_txt}, "semaine": sem, "tendance_20s": tend, "etat": et,
                       "lecture": lecture(devise, dcfg.get("nom", devise), mot, et, sem)})
    return {"genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"), "date": aujourd.isoformat(),
            "devises": sortie, "seuil_correlation": cfg.get("seuil_correlation", 0.30),
            "regle_etat": ("« Ancrage contredit » si un ancrage mesurable est corrélé, de façon stable, à l'inverse du sens "
                           "attendu ; sinon somme de trois signaux (banque centrale, surprises macro 30 j, tendance 20 séances) : "
                           "2 ou plus « Soutenue », −2 ou moins « Sous pression », sinon « Sans direction »."),
            "note": "Corrélations des variations quotidiennes : elles décrivent ce qui bouge ensemble, jamais une cause."}


def compact(profil: dict) -> dict:
    """{devise: {etat, raison, moteur, r60}} : copie archivée dans le rapport du jour."""
    return {d["devise"]: {"etat": d["etat"]["valeur"], "raison": d["etat"]["raison"],
                          "moteur": (d["moteur"]["dominant"] or {}).get("libelle"),
                          "r60": (d["moteur"]["dominant"] or {}).get("r60")} for d in profil.get("devises") or []}


def _lire(chemin: Path) -> dict | None:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ecrire(racine: str | Path, config: dict, h5=None, technique: dict | None = None, aujourd: date | None = None) -> dict:
    """Calcule et écrit docs/data/profil_devises.json à partir des fichiers publiés du jour."""
    from core import historique_5ans, registre_macro
    racine = Path(racine)
    docs = racine / (config.get("publication_web") or {}).get("dossier_docs", "docs") / "data"
    h5 = h5 if h5 is not None else historique_5ans.charger()
    if technique is None:
        technique = (_lire(racine / "data" / "cache" / "collecte_technique.json") or {}).get("donnees")
    profil = calculer(config, h5, technique, registre_macro.charger(racine / "data" / "registre_macro.json"),
                      _lire(docs / "agenda.json"), _lire(racine / "data" / "archives" / "publications.json"),
                      _lire(docs / "tableau_macro.json"), racine, aujourd,
                      (_lire(racine / "data" / "cache" / "collecte_historiques.json") or {}).get("donnees"))
    (docs / "profil_devises.json").write_text(json.dumps(profil, ensure_ascii=False, indent=1), encoding="utf-8")
    return profil
