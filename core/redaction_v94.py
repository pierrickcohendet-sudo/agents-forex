"""Textes de secours de la Synthèse V9.4 (rédaction automatique) : paragraphes complets construits en Python à partir des
faits, dans le ton des rapports modèles (« Ma lecture », « Mon biais » conditionnel, nuances). Chaque phrase cite un
fait chiffré ou daté ; le texte passe le même contrôle que celui du modèle (core/controle_texte.py) : une phrase qui
échoue est retirée. Vocabulaire interdit : entrée, stop, objectif, long, short (test).
"""
from __future__ import annotations

from core.synthese_v9 import NOMS_DEVISES, ddm, fr

# « long » reste permis en français (« à long terme ») ; LONG et SHORT en capitales, « short » et les niveaux d'exécution, jamais
INTERDITS = r"\b(entrées?|stops?|objectifs?|[Ss]hort|LONG|SHORT)\b"


def _p(*phrases) -> str:
    return " ".join(x.strip() for x in phrases if x and x.strip())


def _nom(dev: str) -> str:
    return NOMS_DEVISES.get(dev, dev)


def t_exec(f: dict, date_: str) -> list[str]:
    x = f["exec"]
    rm = x.get("risque_majeur") or {}
    el = x.get("elements") or []
    fed = x.get("fed") or {}
    paras = [_p(f"Biais du jour au {ddm(date_)} : {x.get('biais', 'n/d').lower()}.",
                f"Régime de marché : {x.get('regime', 'n/d')} (au {ddm(date_)}).",
                f"Facteur dominant au {ddm(date_)} : {x.get('facteur_dominant', 'n/d')}.",
                f"Risque majeur : {rm.get('texte', 'n/d')}." if rm.get("type") in ("seuil", "volatilite", "publication") else "")]
    if el:
        paras.append("Trois éléments dominent au " + ddm(date_) + " : " + " ; ".join(f"{i + 1}. {e['titre']} : {e['texte']}" for i, e in enumerate(el)) + ".")
    if fed.get("valeur") is not None:
        paras.append(f"{fed['source'].split(',')[0]} cite le {ddm(fed['date'])} une probabilité de {fed['texte']} pour la prochaine décision de la Fed"
                     + (f", contre {fr(fed['precedent'], 0)} % le {ddm(fed['precedent_date'])}." if fed.get("precedent") is not None else "."))
    cl = f.get("classement") or {}
    d = cl.get("devises") or []
    if d:
        paras.append(_p(f"Ma lecture : au {ddm(date_)}, le classement place le {_nom(d[0]['devise'])} en tête (score {fr(d[0]['score'], 2, True)}, {d[0]['moteur']})"
                        f" et le {_nom(d[-1]['devise'])} en dernier (score {fr(d[-1]['score'], 2, True)}).",
                        "Une hausse des rendements ne se lit pas automatiquement comme un signal de bonne santé : elle peut aussi traduire "
                        f"une prime de risque, ce qu'il faudra vérifier avec le VIX et les actions au {ddm(date_)}."))
    return paras


def t_marches(f: dict, date_: str) -> list[str]:
    m = f["marches"]
    tu = [t for t in m.get("tuiles") or [] if t.get("valeur") is not None]
    paras = []
    if tu:
        paras.append("Tableau de bord : " + " ; ".join(f"{t['libelle']} {t['texte']} au {ddm(t['date'])}" + (f", {t['qualificatif']}" if t.get("qualificatif") else "")
                                                       for t in tu) + ".")
    cls = [c for c in m.get("classes") or [] if c.get("variation_5") is not None]
    if cls:
        paras.append("Par classe d'actifs au " + ddm(date_) + " : " + " ; ".join(f"{c['actif']} {c['texte']} ({c['interpretation'].lower()})" for c in cls[:5]) + ".")
    paras.append((m.get("mecanisme") or {}).get("phrase", ""))
    return [p for p in paras if p]


def t_pays(p: dict, date_: str) -> list[str]:
    # la carte affiche déjà tous les faits : le texte n'en reprend que le plus important
    paras = [_p(f"Biais au {ddm(date_)} : {p['biais']}.", f"Fait marquant : {(p.get('elements') or p.get('faits') or [''])[0]}." if (p.get("elements") or p.get("faits")) else "")]
    off = p.get("officiels") or []
    if off:
        paras.append("Publications officielles : " + " ; ".join(f"{o['libelle']} {fr(o['valeur'], 1, True)} % ({o['periode']}, précédent "
                                                                   f"{fr(o.get('precedent'), 1, True)} %, {o['source'].split(' (')[0]}, publié le {ddm(o.get('publie_le'))})"
                                                                   for o in off[:5]) + ".")
    ec = p.get("ecart_2a") or {}
    paras.append(_p(f"Pourquoi : {p['pourquoi']}", f"Écart de taux 2 ans USD − {p['devise']} : {ec['texte']}." if ec.get("valeur") is not None and p["devise"] != "USD" else ""))
    if p.get("chaine"):
        paras.append("Chaîne de causalité : " + " → ".join(p["chaine"]) + f" (au {ddm(date_)}).")
    dl = p.get("deliberations") or {}
    if dl.get("options"):
        paras.append(f"Délibérations publiées le {ddm(dl.get('date'))} : « {dl['options'][-1]} »" + (f" Sur la suite : « {dl['suite'][-1]} »" if dl.get("suite") else ""))
    paras.append(_p(f"Risque de retournement : {p['retournement']}", f"Le seuil suivi : {p['seuil']['texte']} au {ddm(date_)}." if p.get("seuil") else ""))
    paras.append(f"Mon biais au {ddm(date_)} : {p['mon_biais']} Ce biais reste conditionnel aux prochaines publications.")
    u = p.get("usd")
    if u:
        pr = (u.get("prix") or {}).get("cpi") or {}
        co = pr.get("composantes") or {}
        if co:
            paras.append(_p(f"Inflation américaine ({pr.get('mois')}, BLS) : CPI {fr(co.get('cpi'), 1, True)} % sur le mois, core {fr(co.get('core'), 1, True)} %,"
                            f" logement {fr(co.get('logement'), 1, True)} %, énergie {fr(co.get('energie'), 1, True)} %, alimentation {fr(co.get('alimentation'), 1, True)} %.",
                            f"Variation annuelle : {(pr.get('annuel') or {}).get('raison')}." if (pr.get("annuel") or {}).get("raison") else ""))
        ob = u.get("obligations") or {}
        if ob.get("us2") and ob.get("us10"):
            paras.append(f"Obligations au {ddm(ob['us2'][0])} : 2 ans à {fr(ob['us2'][1], 2)} %, 10 ans à {fr(ob['us10'][1], 2)} %, pente 10 ans − 2 ans de "
                         f"{fr(ob.get('pente'), 2, True)} point.")
        fe = u.get("fed") or {}
        if fe.get("decision"):
            paras.append(_p(f"Fed : fourchette {fe.get('taux')}, {fe.get('decision')}" + (f", vote {fe['votes']}" if fe.get("votes") else "") +
                            (f", prochaine décision le {ddm(fe.get('prochaine'))}." if fe.get("prochaine") else "."),
                            " ".join(f"{d['personne']} ({d['fonction']}) le {ddm(d['date'])} : « {d['citation']} » ; c'est une opinion personnelle, pas une décision du FOMC."
                                     for d in fe.get("declarations") or [])))
    return [x for x in paras if x]


def t_commune(c: dict, date_: str) -> list[str]:
    return [_p(f"{d['pays']} ({d['devise']}) : biais {d['biais']} au {ddm(date_)}.", " ".join(f"{x}." for x in d["faits"][:2]), d["pourquoi"],
               d["pilotee"] + "." if d.get("pilotee") else "") for d in c.get("devises") or []]


def t_energie(x: dict, date_: str) -> list[str]:
    b, w = x["brent"], x["wti"]
    paras = [_p(f"Le Brent vaut {b['texte']} le {ddm(b['date'])} ({b['nature']})" + (f", {b['qualificatif']}." if b.get("qualificatif") else "."),
                f"Le WTI vaut {w['texte']} le {ddm(w['date'])}." if w.get("valeur") is not None else "", f"{b['alerte']}" if b.get("alerte") else "")]
    fo = [f"{f['libelle']} {fr(f['variation_5'], 1, True)} % sur 5 séances au {ddm(f['date'])}" for f in x["fonds"] if f.get("variation_5") is not None]
    if fo:
        paras.append("Mouvement récent, mesuré par des fonds cotés et jamais présenté comme un prix au baril : " + " ; ".join(fo) + ".")
    for a in x.get("actualites") or []:
        paras.append(f"Actualité du {ddm(a['date'])} ({a['source']}) : « {a['titre']} ».")
    return [p for p in paras if p]


def t_actions(x: dict, date_: str) -> list[str]:
    paras = []
    if x.get("qqq_5") is not None:
        paras.append(f"Le Nasdaq 100 (ETF QQQ) varie de {fr(x['qqq_5'], 2, True)} % sur 5 séances au {ddm(x.get('qqq_date'))}"
                     + (f", {x['qualificatif_qqq']}." if x.get("qualificatif_qqq") else "."))
    for a in x.get("actualites") or []:
        paras.append(f"Actualité du {ddm(a['date'])} ({a['source']}) : « {a['titre']} ».")
    paras.append(x.get("exception", ""))
    return [p for p in paras if p]


def t_calendrier(x: dict, date_: str) -> list[str]:
    a = x.get("aujourdhui") or []
    paras = [f"Aujourd'hui ({ddm(date_)}) : " + " ; ".join(f"{e['heure']} {e['devise']} {e['evenement']}" + (f", prévision {e['consensus']}" if e.get("consensus") else "")
                                                            + (f", publié {e['publie']}" if e.get("publie") else "") for e in a[:8]) + "." if a else
             f"Aucune publication forte ou moyenne aujourd'hui ({ddm(date_)})."]
    sp = x.get("semaine_prochaine") or []
    if sp:
        paras.append(f"Semaine prochaine (à partir du {ddm(x.get('lundi_prochain'))}) : " + " ; ".join(f"{e['jour']} {e['devise']} {e['evenement']}" for e in sp[:8]) + ".")
    return paras


def t_classement(x: dict, date_: str) -> list[str]:
    d = x.get("devises") or []
    paras = []
    if d:
        paras.append(f"Classement au {ddm(date_)} : " + ", ".join(f"{l['rang']}. {l['devise']} ({fr(l['score'], 2, True)}, {l['biais'].lower()})" for l in d) + ".")
    for a in x.get("a_part") or []:
        paras.append(f"{a['devise']} classé à part au {ddm(date_)} : {a['raison']}.")
    for v in (x.get("divergences") or [])[:5]:
        paras.append(f"Divergence {v['forte']} contre {v['faible']} (écart de score {fr(v['ecart'], 2, True)} au {ddm(date_)}) : {v['raison']}.")
    return paras


def t_paires(x: dict, date_: str) -> list[str]:
    return [_p(f"{p['paire']} ({p['priorite'] or 'priorité n/d'}, au {ddm(date_)}) : {p['biais'].lower()}.",
               " ".join(f"{a}." for a in p["arguments"][:3])) for p in (x.get("paires") or [])[:7]]


def t_scenarios(x: dict, date_: str) -> list[str]:
    return [_p(f"Scénario {s['lettre']} ({s['titre']}, {s['chip']}) : {s['remplies']} condition{'s' if (s['remplies'] or 0) > 1 else ''} sur {s['total']} remplie{'s' if (s['remplies'] or 0) > 1 else ''} au {ddm(date_)}.",
               ("Conséquences : " + ", ".join(s["consequences"]) + f", {s['or']}.") if s.get("consequences") else "")
            for s in x.get("scenarios") or []]


def t_methode(x: dict, date_: str) -> list[str]:
    h = [c for c in x.get("confirmations_haussier") or [] if c.get("remplie") is not None]
    ok = sum(1 for c in h if c["remplie"])
    paras = [f"Au {ddm(date_)}, {ok} des {len(h)} confirmations mesurables d'un scénario haussier du dollar sont réunies : "
             + " ; ".join(f"{c['texte']} ({'oui' if c['remplie'] else 'non'})" for c in h) + "."]
    paras += [f"Risque de {r['type'].lower()} au {ddm(date_)} : {r['texte']}." for r in x.get("risques") or []]
    return paras


def t_conclusion(x: dict, date_: str) -> list[str]:
    paras = [f"Mon biais général au {ddm(date_)} : {x.get('biais', 'n/d').lower()}."]
    ind = [i for i in x.get("indicateurs") or [] if i.get("valeur") not in (None, "n/d")]
    if ind:
        paras.append("Les indicateurs à suivre : " + " ; ".join(f"{i['indicateur']} {i['valeur']} au {ddm(i['date'])}" for i in ind) + ".")
    paras.append(f"Mon analyse finale au {ddm(date_)} : les taux donnent le biais macro, la structure quotidienne et 4 heures donne la direction, "
                 f"et la réaction confirmée du marché après publication passe avant toute anticipation. {x.get('prudence', '')}")
    return paras


RENDUS = {"exec": t_exec, "marches": t_marches, "commune": t_commune, "energie": t_energie, "actions": t_actions, "calendrier": t_calendrier,
          "classement": t_classement, "paires": t_paires, "scenarios": t_scenarios, "methode": t_methode, "conclusion": t_conclusion}


def textes_python(s: dict) -> dict[str, list[str]]:
    f, d = s["faits"], s["date"]
    sortie = {}
    for sec in s["sections"]:
        sid, t = sec["id"], sec["type"]
        try:
            if t in ("pays", "etats_unis"):
                sortie[sid] = t_pays(f[sid], d)
            elif sid == "exec":
                sortie[sid] = t_exec(f, d)
            elif sid == "marches":
                sortie[sid] = t_marches(f, d)
            else:
                sortie[sid] = RENDUS[sid](f[sid], d)
        except Exception as exc:  # noqa: BLE001
            sortie[sid] = [f"Texte indisponible au {ddm(d)} : {type(exc).__name__}."]
    return sortie


def nettoyer(s: dict) -> None:
    """Même contrôle que pour le modèle : une phrase qui échoue est retirée ; jamais de section vide ; aucun mot interdit."""
    import re
    from core import controle_texte as ct
    autorises = ct.nombres_autorises(s["faits"])
    for sid, paras in list(s["textes"].items()):
        propres = []
        for para in paras:
            gardees = [ph for ph in ct.phrases(para) if not ct.verifier(ph, autorises) and not re.search(INTERDITS, ph)]
            if gardees:
                propres.append(" ".join(gardees))
        s["textes"][sid] = propres or [f"Données de la section au {ddm(s['date'])} : voir les tableaux ci-dessous."]
