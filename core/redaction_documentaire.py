"""Rédaction du documentaire par une IA (lot V15) : faits « pré-mâchés » en Python, consigne pour un lecteur non
économiste, contrôle tolérant des nombres avec un appel de correction, chaîne de secours.

Chaîne, par groupe de chapitres (0 à 4, puis 5 à 8 et le chapitre final) :
  1. gemini-3.5-flash, 2. gemini-3.5-flash-lite (un appel par groupe ; 2 appels par jour réservés au documentaire dans le
     budget Gemini, catégorie « documentaire », avant le rapport) ;
  3. Groq, chapitre par chapitre (le message Groq est limité à ~4 500 jetons) ;
  4. le dernier récit écrit par une IA cette semaine, avec la mention « Récit écrit le JJ/MM, mis à jour au prochain
     passage du modèle » ;
  5. sinon, l'encadré « Les faits de la semaine » (5 à 8 puces) : jamais de faux récit en Python.
Le contrôle accepte les arrondis, le format français, les signes, la différence de deux faits fournis (4,88 − 4,63 = 25 pb),
les dates de la semaine et les petits entiers. Les nombres introuvables déclenchent UN appel de correction ; le chapitre
n'est rejeté qu'ensuite. Longueur visée : 350 à 700 mots (aucun rejet sur la longueur au-delà de 120 mots).
Tout calcul est fait ici en Python ; le modèle ne fait que rédiger.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import noms_moteurs as nm

log = logging.getLogger(__name__)

GROUPES = {"g1": ["0", "1", "2", "3", "4"], "g2": ["5", "6", "7", "8", "final"]}
MOTS_MIN_ACCEPTE = 120
INTERDITS = re.compile(r"\b(entrées?|stops?|objectifs?)\b", re.I)
INTERDITS_MAJ = re.compile(r"\bLONG\b|\bSHORT\b|\b[Ss]hort\b")   # « long » en minuscules (« à long terme ») reste permis
# Ordres de trading (lot V15) : formes qui prescrivent une action ; décrire ce que font les investisseurs (« ils achètent des
# dollars ») reste permis, contrairement à la liste plus large de core/controle_texte.ORDRES
ORDRES_DOC = [r"\bachetez\b", r"\bvendez\b", r"\bachète[sz]? maintenant\b", r"\bprendre position\b", r"\bprenez position\b",
              r"\bpoint d'entrée\b", r"\bniveau d'entrée\b", r"\bstop[- ]loss\b", r"\btake[- ]profit\b", r"\bobjectif de cours\b",
              r"\bcible de prix\b", r"\bentrer (?:à|sur)\b", r"\bpositions? (?:longue|courte)s?\b", r"\bil faut (?:acheter|vendre)\b",
              r"\b(?:acheter|vendre) (?:maintenant|dès)\b"]
ENGRENAGE_SEUL = re.compile(r"\bengrenages?\s*(n°\s*)?\d\b", re.I)
PETITS_ENTIERS = set(range(0, 13)) | {15, 20, 24, 25, 30, 35, 50, 60, 70, 100, 200}

CONSIGNE = """Tu écris un chapitre du « documentaire de la semaine » d'un site d'aide à la décision sur le marché des changes.
Ton lecteur : un étudiant en gestion qui apprend le trading. Il est intelligent mais n'est pas économiste.
Il doit comprendre CE QUI S'EST PASSÉ, POURQUOI, et CE QUE ÇA CHANGE POUR LES DEVISES.

Style :
- Phrases courtes (20 mots en moyenne). Une idée par phrase. Voix active.
- Chaque terme technique est expliqué la première fois, entre parenthèses ou dans la phrase suivante
  (« le rendement à 2 ans, c'est-à-dire le taux auquel l'État américain emprunte sur 2 ans »).
  Pas d'anglicisme sans traduction : on écrit « la peur sur les marchés » plutôt que « risk off ».
- Raconte : commence par le fait le plus important de la semaine, puis remonte le fil (lundi, mardi…).
  Chaque paragraphe suit le schéma : ce qui s'est passé → pourquoi → ce que ça change pour la devise.
- Termine par « À surveiller » : 2 ou 3 rendez-vous de la semaine prochaine, et ce qu'un chiffre fort ou faible changerait.
- Pas de liste de chiffres. 3 à 6 chiffres par paragraphe au maximum, choisis parce qu'ils racontent quelque chose.
- Jamais de guillemets autour des noms d'indicateurs. Jamais de « percentile » : dis « au plus haut depuis… » ou « à un niveau rare ».
- Ne cite pas de titre de presse en anglais : résume l'information en français et donne la source entre parenthèses.
- Le moteur est cité par son nom, jamais « engrenage » suivi d'un numéro.
- Chaque fait porte un champ « sens » calculé à l'avance : respecte-le, ne déduis jamais un autre sens d'un chiffre.

Interdits : nombre absent des FAITS (les arrondis sont permis) ; ordre d'achat ou de vente ; les mots « entrée », « stop »,
« objectif », « LONG », « SHORT ». Tu donnes des conditions et des effets probables (« si…, le dollar devrait… »).

Longueur : 350 à 700 mots en 4 à 6 paragraphes pour CHAQUE chapitre de moteur (1 à 8), plus une phrase d'exergue simple et
frappante (moins de 25 mots). 350 mots est un minimum : un chapitre de moteur plus court est incomplet, même si tu en écris plusieurs.
Le chapitre « 0 » (la semaine en bref) et le chapitre « final » (ce qui peut bouger la semaine prochaine) font 150 à 350 mots.

Exemple de ton attendu (pour le style seulement, n'en reprends aucun chiffre) : voir EXEMPLE.
"""

EXEMPLE = """Le marché a cessé de croire à une Fed plus dure, et l'économie américaine lui donne tort.

Le fait de la semaine tient en un chiffre : le rendement à 2 ans des États-Unis, c'est-à-dire le taux auquel l'État américain emprunte sur deux ans, est resté à 4,63 %. C'est 25 points de base de moins qu'au 13/11, où il était à 4,88 %. Ce taux est le meilleur thermomètre de ce que le marché attend de la banque centrale américaine, la Fed. Quand il baisse, le marché parie sur une Fed moins sévère, et le dollar perd un peu de son attrait.

Pourquoi cette baisse ? La semaine dernière, la peur a gagné les marchés : les actions ont reculé et les investisseurs se sont réfugiés dans les obligations d'État. Quand on achète des obligations, leur rendement baisse. C'est ce que montre le seuil franchi par ce moteur : −20 pb sur sept jours, au-delà de la limite de 10 pb qui signale un vrai mouvement.

Mercredi 25/11, pourtant, les chiffres américains ont contredit ce scénario. La croissance du troisième trimestre ressort à 4,3 % en rythme annuel, bien au-dessus des 3,5 % attendus. L'inflation préférée de la Fed, le PCE sous-jacent, progresse de 0,3 % sur le mois, exactement comme prévu. Une économie qui tourne vite et une inflation qui ne ralentit pas : ce n'est pas le portrait d'un pays qui a besoin de taux plus bas.

Pour le yen, l'enjeu reste le même. L'écart entre les taux américains et japonais est encore très large, ce qui pousse les investisseurs à emprunter en yens pour placer en dollars. USD/JPY était à 158,76 le 20/11, tout près de 160, le niveau où le Japon est déjà intervenu pour soutenir sa monnaie.

À surveiller : la prochaine décision de la Fed, le 09/12. Si les chiffres de croissance et d'emploi restent forts d'ici là, le rendement à 2 ans devrait remonter et redonner de l'élan au dollar. S'ils faiblissent, la baisse de la semaine dernière pourrait n'être qu'un début."""

FORMAT = ('Réponds STRICTEMENT en JSON : {"chapitres": {"<numéro>": {"paragraphes": ["…"], "exergue": "…", '
          '"a_surveiller": ["…"]}, …}} avec une entrée pour CHAQUE chapitre demandé ; les clés de « chapitres » sont exactement '
          'les numéros demandés (par exemple "2" pour le chapitre 2, "final" pour le chapitre final).')


# ------------------------------------------------------------------ outils de mise en forme
def fr(v, d: int = 2) -> str:
    if v is None:
        return "n/d"
    if d and float(v) == int(v) and abs(v) >= 10:
        d = 0
    s = f"{abs(v):,.{d}f}".replace(",", " ").replace(".", ",")
    return ("−" if v < 0 else "") + s


def ddm(iso) -> str:
    s = str(iso or "")
    return f"{s[8:10]}/{s[5:7]}" if len(s) >= 10 else "n/d"


JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def jour_long(iso) -> str:
    try:
        return f"{JOURS[date.fromisoformat(str(iso)[:10]).weekday()]} {ddm(iso)}"
    except ValueError:
        return ddm(iso)


def frtxt(v) -> str:
    t = str(v if v is not None else "n/d")
    t = re.sub(r"(\d)\.(\d)", r"\1,\2", t)
    t = re.sub(r"(\d)%", r"\1 %", t)
    return re.sub(r"^-(?=\d)", "−", t)


DEVISES_NOMS = {"USD": "le dollar américain", "EUR": "l'euro", "GBP": "la livre sterling", "JPY": "le yen", "CHF": "le franc suisse",
                "CAD": "le dollar canadien", "AUD": "le dollar australien", "NZD": "le dollar néo-zélandais", "CNY": "le yuan"}
PAYS = {"USD": "aux États-Unis", "EUR": "en zone euro", "GBP": "au Royaume-Uni", "JPY": "au Japon", "CHF": "en Suisse",
        "CAD": "au Canada", "AUD": "en Australie", "NZD": "en Nouvelle-Zélande", "CNY": "en Chine"}


# ------------------------------------------------------------------ 1. sens des mouvements (calculé en Python)
# (motif sur le libellé, sens si hausse, explication si hausse, sens si baisse, explication si baisse)
SENS = [
    (r"^VIX|indice de la peur", "peur", "la peur monte sur les marchés", "calme", "la peur recule sur les marchés"),
    (r"S&P 500|Nasdaq|actions", "prise de risque", "les investisseurs reprennent du risque", "peur",
     "les investisseurs vendent les actions et cherchent la sécurité"),
    (r"[Rr]endement 2 ans US|^2 ans US|2 ans US \(", "taux en hausse", "le marché attend une Fed plus sévère, ce qui soutient le dollar",
     "taux en baisse", "le marché attend une Fed moins sévère, ce qui retire un soutien au dollar"),
    (r"2 ans", "taux en hausse", "le marché attend une banque centrale plus sévère", "taux en baisse",
     "le marché attend une banque centrale moins sévère"),
    (r"[Cc]ourbe", "courbe plus pentue", "l'écart entre taux longs et taux courts s'élargit : le marché craint moins un ralentissement",
     "courbe plus plate", "l'écart entre taux longs et taux courts se réduit : le marché craint davantage un ralentissement"),
    (r"[Pp]rime de terme", "doute sur les finances publiques", "les prêteurs exigent davantage pour prêter longtemps",
     "confiance", "les prêteurs exigent moins pour prêter longtemps"),
    (r"10 ans", "taux longs en hausse", "emprunter sur 10 ans coûte plus cher", "taux longs en baisse", "emprunter sur 10 ans coûte moins cher"),
    (r"[Ii]ndice dollar|dollar large|USD synthétique", "dollar soutenu", "le dollar se renforce face aux grandes devises",
     "dollar affaibli", "le dollar s'affaiblit face aux grandes devises"),
    (r"USD/JPY", "dollar soutenu face au yen", "le yen s'affaiblit face au dollar", "yen soutenu", "le yen se renforce face au dollar"),
    (r"EUR/USD", "euro soutenu", "l'euro se renforce face au dollar", "dollar soutenu", "le dollar se renforce face à l'euro"),
    (r"\bor\b|[Oo]r \(|[Ii]ndice or", "refuge", "les investisseurs cherchent une protection", "moins de besoin de refuge",
     "les investisseurs cherchent moins de protection"),
    (r"Brent − WTI", "tension sur l'offre mondiale", "le pétrole mondial se tend davantage que l'américain", "détente de l'offre",
     "l'écart entre pétrole mondial et américain se réduit"),
    (r"Brent|WTI|[Pp]étrole", "pétrole en hausse", "un pétrole plus cher soutient le dollar canadien et pèse sur le yen et l'euro",
     "pétrole en baisse", "un pétrole moins cher pèse sur le dollar canadien et soulage le Japon et la zone euro"),
    (r"^Score ([A-Z]{3})", "devise recherchée", "la devise gagne en force selon les 8 moteurs", "devise délaissée",
     "la devise perd de sa force selon les 8 moteurs"),
    (r"[Ss]urprise", "bonnes surprises", "les chiffres publiés battent davantage les prévisions", "déceptions",
     "les chiffres publiés déçoivent davantage les prévisions"),
    (r"COT", "spéculateurs plus acheteurs", "les spéculateurs parient davantage sur la hausse", "spéculateurs plus vendeurs",
     "les spéculateurs parient davantage sur la baisse"),
    (r"[Ss]tocks", "stocks en hausse", "plus de pétrole stocké, ce qui pèse sur le prix du baril", "stocks en baisse",
     "moins de pétrole stocké, ce qui soutient le prix du baril"),
]


# Libellés techniques -> libellés clairs dans les faits donnés au modèle (essai du 26/11 : « 2 ans US − taux effectif » lu
# comme un « taux réel » par les deux modèles Groq essayés)
LIBELLES_CLAIRS = [
    (r"^2 ans US − taux effectif.*", "L'écart entre le taux à 2 ans américain et le taux de la Fed"),
    (r"^Courbe 2-10 ans US.*", "L'écart entre les taux américains à 10 ans et à 2 ans"),
    (r"^Taux réel (.*)", r"Le taux réel \1 (taux directeur moins inflation)"),
    (r"^Taux effectif Fed.*", "Le taux de la Fed au jour le jour"),
    (r"^Rendement 2 ans (.*)", r"Le taux à 2 ans \1"),
    (r"^Rendement 10 ans (.*)", r"Le taux à 10 ans \1"),
    (r"^10 ans (.*)", r"Le taux à 10 ans \1"),
    (r"^Score ([A-Z]{3})", r"La note de force du \1 (0 à 100)"),
    (r"^Surprise ([A-Z]{3}).*", r"L'indice de surprise du \1 (30 jours)"),
    (r"^Surprise globale.*", "L'indice de surprise moyen des 9 devises"),
    (r"^Prime de terme.*", "La prime de terme américaine (supplément exigé pour prêter 10 ans)"),
    (r"^Écart Italie − Allemagne.*", "L'écart de taux à 10 ans entre l'Italie et l'Allemagne"),
    (r"^Indice dollar large.*", "Le dollar face à un large panier de devises"),
]


def libelle_clair(libelle: str) -> str:
    for m, r in LIBELLES_CLAIRS:
        if re.search(m, libelle or ""):
            return re.sub(m, r, libelle).replace("US", "américain").strip()
    return libelle


def sens_mouvement(libelle: str, hausse: bool) -> tuple[str, str]:
    """(sens, explication) d'une hausse ou d'une baisse d'un indicateur, d'après son libellé. Exemple : S&P 500 en hausse
    -> (« prise de risque », « les investisseurs reprennent du risque »)."""
    for m, sh, eh, sb, eb in SENS:
        if re.search(m, libelle or ""):
            return (sh, eh) if hausse else (sb, eb)
    return ("hausse", "l'indicateur monte") if hausse else ("baisse", "l'indicateur baisse")


def niveau_simple(p) -> str | None:
    """Niveau sur 5 ans sans le mot « percentile » (lot V15)."""
    if p is None:
        return None
    if p >= 95:
        return "un niveau rare, parmi les plus hauts de ces cinq dernières années"
    if p >= 80:
        return "un niveau élevé pour ces cinq dernières années"
    if p <= 5:
        return "un niveau rare, parmi les plus bas de ces cinq dernières années"
    if p <= 20:
        return "un niveau bas pour ces cinq dernières années"
    return None


# ------------------------------------------------------------------ 2. faits pré-mâchés
def _fait(texte: str, sens: str, poids: float, date_=None, source=None) -> dict:
    return {"texte": texte, "sens": sens, "poids": round(poids, 2), "date": date_, "source": source}


def _mouvement(libelle: str, v: dict, texte_fin: str | None, source=None) -> dict | None:
    if not v or v.get("valeur") is None:
        return None
    val, u = v["valeur"], (v.get("unite") or "").strip()
    hausse = val > 0
    sens, expl = sens_mouvement(libelle, hausse)
    if u == "%":
        verbe = "a gagné" if hausse else "a perdu"
        quantite = f"{fr(abs(val), 2)} %"
    elif u == "pb":
        verbe = "a monté" if hausse else "a baissé"
        quantite = f"{fr(abs(val), 0)} points de base (pb)"
    else:
        verbe = "a monté" if hausse else "a baissé"
        quantite = f"{fr(abs(val), 2)}{(' ' + u) if u else ''}"
    de_a = ""
    if v.get("debut") is not None and v.get("fin") is not None:
        de_a = f" (de {fr(v['debut'], 2)} à {fr(v['fin'], 2)})"
    t = f"{libelle_clair(libelle)} {verbe} {quantite} entre le {ddm(v.get('du'))} et le {ddm(v.get('au'))}{de_a} : {expl}."
    if texte_fin:
        t += f" {texte_fin}"
    if val == 0:
        sens, t = "stable", f"{libelle_clair(libelle)} est stable entre le {ddm(v.get('du'))} et le {ddm(v.get('au'))}."
    return _fait(t, sens, 1.0, v.get("au"), source)


def faits_chapitre(ch: dict, sem: dict, theme_jours: list[dict]) -> list[dict]:
    """Faits du chapitre d'un moteur, chacun en une phrase française avec son sens (calculé ici), du plus au moins important."""
    n, e = ch["numero"], ch.get("etat") or {}
    sortie = []
    if e.get("valeur") is not None:
        d = e.get("direction") or ""
        sens = ("dollar soutenu" if "haussier" in d.lower() else "dollar affaibli" if "baissier" in d.lower() else "") \
            + (" ; peur" if "risk off" in d.lower() else " ; prise de risque" if "risk on" in d.lower() else "")
        etat = {"seuil franchi": "le seuil d'alerte est franchi", "près du seuil": "il approche du seuil d'alerte", "calme": "il reste calme"}.get(
            e.get("etat"), e.get("etat") or "état n/d")
        dir_txt = (d.replace("Dollar haussier", "le dollar est poussé à la hausse").replace("Dollar baissier", "le dollar est poussé à la baisse")
                   .replace("Dollar neutre", "pas d'effet net sur le dollar").replace("Risk off", "peur sur les marchés")
                   .replace("Risk on", "prise de risque").replace("Risque neutre", "humeur neutre").replace(" · ", ", ")) if d else ""
        sortie.append(_fait(f"Le thermomètre de ce moteur ({e.get('libelle')}) est à {e.get('valeur')} au {ddm(e.get('date'))} : {etat}"
                            + (f" ; {dir_txt}" if dir_txt else "") + ".", sens.strip(" ;") or "état du moteur", 3.0, e.get("date"), e.get("source")))
    if n == 1 and len(theme_jours) > 1:
        etapes = "; ".join(f"{jour_long(t['date'])} : {t['titre']} ({t['alignes']} moteurs alignés)" for t in theme_jours if t.get("titre"))
        sortie.append(_fait(f"L'humeur du marché jour par jour : {etapes}.", "évolution du thème", 2.5))
    vus = set()

    def nouveau(libelle: str) -> bool:
        k = re.sub(r"\s*\([^)]*\)$", "", libelle or "").strip().lower()
        if k in vus:
            return False
        vus.add(k)
        return True

    for i in sorted(ch.get("indicateurs") or [], key=lambda x: -(x.get("ampleur") or 0))[:5]:
        if not nouveau(i["libelle"]):
            continue
        niveau = niveau_simple(i.get("percentile_5a"))
        f = _mouvement(i["libelle"], i.get("variation_semaine") or {}, f"C'est {niveau}." if niveau else None, i.get("source"))
        if f:
            f["poids"] = 1.0 + min(2.0, (i.get("ampleur") or 0) / 2)
            sortie.append(f)
    for g in ch.get("graphiques") or []:
        if g.get("derniere") and nouveau(g["titre"]):
            f = _mouvement(re.sub(r"\s*\([^)]*\)$", "", g["titre"]), g.get("variation_semaine") or {}, None, g.get("source"))
            if f:
                f["poids"] = 1.5
                sortie.append(f)
    vix = next((g for g in ch.get("graphiques") or [] if g.get("cle") == "vix"), None)
    spx = next((g for g in ch.get("graphiques") or [] if g.get("cle") == "sp500"), None)
    if vix and spx and (spx.get("variation_semaine") or {}).get("valeur") is not None and (vix.get("variation_semaine") or {}).get("valeur") is not None:
        vs, vv = spx["variation_semaine"], vix["variation_semaine"]
        if (vs["valeur"] > 0) != (vv["valeur"] > 0):   # le fait combiné remplace les deux faits séparés
            sortie = [f for f in sortie if not re.match(r"(S&P 500|VIX) ", f["texte"])]
        if vs["valeur"] > 0 and vv["valeur"] < 0:
            sortie.append(_fait(f"Le S&P 500 a gagné {fr(vs['valeur'], 2)} % entre le {ddm(vs['du'])} et le {ddm(vs['au'])} : les investisseurs "
                                f"reprennent du risque, la peur recule (VIX de {fr(vv['debut'], 2)} à {fr(vv['fin'], 2)}).", "prise de risque", 2.6, vs["au"]))
        elif vs["valeur"] < 0 and vv["valeur"] > 0:
            sortie.append(_fait(f"Le S&P 500 a perdu {fr(abs(vs['valeur']), 2)} % entre le {ddm(vs['du'])} et le {ddm(vs['au'])} : la peur monte "
                                f"(VIX de {fr(vv['debut'], 2)} à {fr(vv['fin'], 2)}) et les investisseurs cherchent la sécurité.", "peur", 2.6, vs["au"]))
    for p in ch.get("publications") or []:
        if not p.get("reel"):
            continue
        dev = p.get("devise")
        if p.get("consensus"):
            bon = p.get("favorable")
            sens = ("surprise favorable " if bon else "surprise défavorable " if bon is False else "conforme ") + str(dev)
            lecture = (f"une bonne surprise pour {DEVISES_NOMS.get(dev, dev)}" if bon else
                       f"une déception pour {DEVISES_NOMS.get(dev, dev)}" if bon is False else "conforme aux attentes")
            t = (f"{jour_long(p['date']).capitalize()}, {PAYS.get(dev, dev)} : {p['evenement']} à {frtxt(p['reel'])} contre "
                 f"{frtxt(p['consensus'])} attendu ; {lecture}.")
            poids = 1.2 + min(2.0, abs(p.get("z") or 0) / 1.5) + (0.5 if p.get("impact") == "fort" else 0)
        else:
            t, sens, poids = f"{jour_long(p['date']).capitalize()}, {PAYS.get(dev, dev)} : {p['evenement']} à {frtxt(p['reel'])} (pas de prévision publiée).", f"publication {dev}", 0.6
        sortie.append(_fait(t, sens, poids, p.get("date"), p.get("source")))
    barres = (ch.get("surprises") or {}).get("barres") or []
    if len(barres) > 1:
        h, b = barres[0], barres[-1]
        sortie.append(_fait(f"Sur la semaine, {DEVISES_NOMS.get(h['devise'], h['devise'])} a les meilleures surprises (solde {fr(h['solde'], 1)} sur "
                            f"{h['n']} publications) et {DEVISES_NOMS.get(b['devise'], b['devise'])} les pires (solde {fr(b['solde'], 1)} sur {b['n']}).",
                            f"surprises : {h['devise']} soutenu, {b['devise']} pénalisé", 2.2))
    for t in (ch.get("actualite") or [])[:6]:
        suj = sujet(t.get("titre"))
        if suj:
            sortie.append(_fait(f"Actualité du {ddm(t.get('date'))} sur {suj} ({t.get('source') or 'source n/d'}).", "actualité", 0.5, t.get("date"), t.get("source")))
    for d in ch.get("devises") or []:
        if d.get("effet") in ("soutien", "pression") and d.get("pourquoi_phrase"):
            sortie.append(_fait(d["pourquoi_phrase"], f"{d['devise']} {'soutenu' if d['effet'] == 'soutien' else 'sous pression'}", 1.4, d.get("date")))
    for r in ((ch.get("risques") or {}).get("rendez_vous") or [])[:4]:
        sortie.append(_fait(f"À venir : {jour_long(r.get('date'))} à {r.get('heure') or 'heure n/d'}, {r.get('evenement')} ({r.get('devise')})"
                            + (f", attendu {frtxt(r['consensus'])}" if r.get("consensus") else "") + ".", "à surveiller", 1.0, r.get("date")))
    s = (ch.get("risques") or {}).get("scenario_si")
    if s:
        sortie.append(_fait(s, "scénario conditionnel", 1.1))
    return sorted(sortie, key=lambda f: -f["poids"])


def faits_bref(d: dict) -> list[dict]:
    th = d.get("theme") or {}
    sortie = [_fait(f"Humeur du marché : {th.get('titre')} ({th.get('alignes')} moteurs alignés sur {th.get('evaluables')}).", "thème", 3)]
    if th.get("explication"):
        sortie.append(_fait(th["explication"], "thème", 2))
    for b in d.get("bref") or []:
        pb = b.get("plus_bouge") or {}
        sortie.append(_fait(f"{b['nom']} : {b.get('etat') or 'n/d'}" + (f" ({b.get('libelle')} à {b.get('valeur')})" if b.get("valeur") else "")
                            + (f" ; ce qui a le plus bougé : {pb.get('libelle')}, {pb.get('texte')} ({pb.get('variation')})" if pb else "") + ".",
                            "résumé du moteur", 1.5))
    return sortie


def faits_final(d: dict) -> list[dict]:
    f = d.get("final") or {}
    sortie = []
    rp = (f.get("risque_principal") or {}).get("texte")
    if rp:
        sortie.append(_fait(rp, "risque principal", 3))
    for c in f.get("calendrier") or []:
        if c.get("ferie"):
            sortie.append(_fait(f"{jour_long(c['date']).capitalize()} : {'; '.join(c['ferie'])}.", "jour férié", 1.5))
        for e in c.get("evenements") or []:
            if e.get("impact") == "fort":
                sortie.append(_fait(f"{jour_long(c['date']).capitalize()} à {e.get('heure') or 'heure n/d'} : {e.get('evenement')} ({e.get('devise')})"
                                    + (f", attendu {frtxt(e['consensus'])}" if e.get("consensus") else "")
                                    + (f", précédent {frtxt(e['precedent'])}" if e.get("precedent") else "") + ".", "rendez-vous fort", 2))
    return sortie


SUJETS = [(r"tariff|droits de douane", "les droits de douane"), (r"trade (deal|agreement|talks)|accord commercial", "les accords commerciaux"),
          (r"\boil\b|crude|brent|\bwti\b|petrole|opec|opep", "le pétrole"), (r"sanction", "les sanctions"),
          (r"\bwar\b|guerre|missile|attack|strikes?\b|military", "les tensions militaires"), (r"summit|sommet", "un sommet international"),
          (r"\bfed\b|fomc|powell|warsh|waller", "la Réserve fédérale"), (r"\becb\b|\bbce\b|lagarde", "la BCE"),
          (r"\bboe\b|bailey", "la Banque d'Angleterre"), (r"\bboj\b|ueda", "la Banque du Japon"),
          (r"\bcpi\b|inflation", "l'inflation"), (r"payroll|jobs|unemployment|jobless", "l'emploi"), (r"\bgdp\b|economy", "la croissance"),
          (r"retail sales", "la consommation"), (r"budget|deficit|\bdebt\b|borrowing|fiscal|\bgilts?\b", "les finances publiques"),
          (r"auction", "une adjudication de dette"), (r"wrap|risk sentiment|sell-?off|markets?", "l'humeur des marchés"),
          (r"\bstocks?\b|equities|nasdaq|s&p|wall street", "les marchés d'actions"), (r"\bgold\b", "l'or"), (r"\bchina\b", "la Chine")]


def sujet(titre: str | None) -> str | None:
    t = str(titre or "").lower()
    return next((lib for m, lib in SUJETS if re.search(m, t)), None)


# ------------------------------------------------------------------ 3. encadré « Les faits de la semaine »
def faits_semaine(faits: list[dict], n_min: int = 5, n_max: int = 8) -> list[str]:
    """5 à 8 puces courtes et claires (les faits les plus importants, sans doublon de sens « actualité »)."""
    sortie, actus = [], 0
    for f in faits:
        if f["sens"] == "actualité":
            actus += 1
            if actus > 2:
                continue
        sortie.append(f["texte"])
        if len(sortie) >= n_max:
            break
    return sortie if len(sortie) >= min(n_min, len(faits)) else sortie


# ------------------------------------------------------------------ 4. contrôle tolérant
def valeurs_faits(faits: list[dict]) -> list[tuple[float, int, bool]]:
    from core import controle_texte as ct
    sortie = []
    for f in faits:
        texte = str(f.get("texte") or "")
        for t, v, d in ct.nombres_texte(re.sub(r"\b\d{1,2}/\d{1,2}\b", " ", texte)):
            sortie.append((abs(v), d, "%" in texte[texte.find(t):texte.find(t) + len(t) + 3]))
    return sortie


def autorise_tolerant(v: float, d: int, faits_vals: list[tuple[float, int, bool]], dates: set[tuple[int, int]] | None = None) -> bool:
    """Arrondi (4,63 -> 4,6), signe, format, différence de deux faits (4,88 − 4,63 = 0,25 = 25 pb), milliers, petits entiers."""
    v = abs(v)
    if d == 0 and v in PETITS_ENTIERS:
        return True
    if d == 0 and 2015 <= v <= 2035:
        return True
    vals = [x for x, _, _ in faits_vals]
    pas = 10 ** -d / 2 + 1e-9
    for x in vals:
        if abs(round(x, d) - v) < pas or abs(x - v) < pas:
            return True
        if x >= 1000 and abs(x / 1000 - v) < pas * 10:
            return True
        if x < 1000 and abs(x * 1000 - v) < 1e-6:
            return True
    for i, a in enumerate(vals):
        for b in vals[i + 1:]:
            diff = abs(a - b)
            if abs(round(diff, d) - v) < pas or abs(round(diff * 100) - v) < 0.5 + 1e-9 and d == 0:
                return True
    return False


def nombres_introuvables(texte: str, faits: list[dict], dates_semaine: list[str] | None = None) -> list[str]:
    from core import controle_texte as ct
    vals = valeurs_faits(faits)
    dates = {(int(x[8:10]), int(x[5:7])) for x in dates_semaine or []}
    autorisees = set()
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})\b", texte):
        autorisees.add(m.group())
    textes_dates = " ".join(f["texte"] for f in faits)
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})\b", textes_dates):
        dates.add((int(m.group(1)), int(m.group(2))))
    hors = []
    sans_dates = texte
    for m in list(re.finditer(r"\b(\d{1,2})/(\d{1,2})\b", texte)):
        j, mo = int(m.group(1)), int(m.group(2))
        if (j, mo) not in dates and not (1 <= j <= 31 and 1 <= mo <= 12 and any(abs(j - a) <= 14 and mo == b for a, b in dates)):
            hors.append(m.group())
    sans_dates = re.sub(r"\b\d{1,2}/\d{1,2}\b", " ", sans_dates)
    # dates écrites en toutes lettres (« 26 novembre », « lundi 30 ») : acceptées si elles tombent à moins de 15 jours des faits
    mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    for m in list(re.finditer(r"\b(\d{1,2})(?:er)? (" + "|".join(mois) + r")\b", sans_dates)):
        j, mo = int(m.group(1)), mois.index(m.group(2)) + 1
        if not (1 <= j <= 31 and any(abs(j - a) <= 14 and mo == b or (mo - b) % 12 == 1 and j <= 15 for a, b in dates)):
            hors.append(m.group())
    sans_dates = re.sub(r"\b\d{1,2}(?:er)? (" + "|".join(mois) + r")\b", " ", sans_dates)
    sans_dates = re.sub(r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche) (\d{1,2})\b", r"\1", sans_dates)
    for t, v, d in ct.nombres_texte(sans_dates):
        if not autorise_tolerant(v, d, vals):
            hors.append(t)
    return list(dict.fromkeys(hors))


def controler(r: dict, faits: list[dict], dates_semaine: list[str] | None = None) -> dict:
    """-> {"nombres": [...], "vocabulaire": [...], "bloquant": bool}. Seuls l'absence de texte, le vocabulaire interdit,
    les ordres et les nombres introuvables comptent ; la longueur n'est plus une cause de rejet au-delà de 120 mots."""
    paras = [str(p) for p in (r.get("paragraphes") or []) if str(p).strip()]
    morceaux = paras + [str(r.get("exergue") or "")] + [str(x) for x in r.get("a_surveiller") or []]
    texte = " ".join(morceaux)
    voc = []
    for m in morceaux:
        for rx in (INTERDITS, INTERDITS_MAJ):
            x = rx.search(m)
            if x:
                voc.append(x.group())
        voc += [re.search(o, m.lower()).group() for o in ORDRES_DOC if re.search(o, m.lower())]
        if ENGRENAGE_SEUL.search(m):
            voc.append(ENGRENAGE_SEUL.search(m).group())
        if re.search(r"percentile", m, re.I):
            voc.append("percentile")
    nombres = nombres_introuvables(texte, faits, dates_semaine)
    vide = len(re.findall(r"\w+", " ".join(paras))) < (40 if r.get("_court") else MOTS_MIN_ACCEPTE)
    return {"nombres": nombres, "vocabulaire": list(dict.fromkeys(voc)), "vide": vide, "bloquant": bool(nombres or voc or vide)}


# ------------------------------------------------------------------ 5. consignes
def prompt_groupe(faits_par_ch: dict[str, dict]) -> str:
    """faits_par_ch : {numéro: {"nom": …, "question": …, "faits": [ {texte, sens}, … ]}}."""
    demandes = {k: {"moteur": v["nom"], "question": v.get("question"), "faits": [{"texte": f["texte"], "sens": f["sens"]} for f in v["faits"][:22]]}
                for k, v in faits_par_ch.items()}
    return (CONSIGNE + "\nEXEMPLE :\n" + EXEMPLE + "\n\n" + FORMAT + "\nCHAPITRES DEMANDÉS : " + ", ".join(faits_par_ch)
            + "\nFAITS :\n" + json.dumps(demandes, ensure_ascii=False))


def prompt_correction(textes: dict[str, dict], problemes: dict[str, dict]) -> str:
    lignes = []
    for k, p in problemes.items():
        if p["nombres"]:
            lignes.append(f"Chapitre {k} : ces nombres ne sont pas dans les faits : {', '.join(p['nombres'])} ; réécris les phrases concernées sans eux.")
        if p["vocabulaire"]:
            lignes.append(f"Chapitre {k} : retire ces mots ou tournures : {', '.join(p['vocabulaire'])}.")
    return ("Corrige ces chapitres du documentaire. Ne change rien d'autre que les phrases concernées.\n" + "\n".join(lignes)
            + "\n" + FORMAT + "\nTEXTES :\n" + json.dumps({k: textes[k] for k in problemes}, ensure_ascii=False))


def extraire(brut: str) -> dict:
    from core.llm import extraire_json
    d = extraire_json(brut) or {}
    ch = d.get("chapitres") if isinstance(d, dict) else None
    sortie = {}
    for k, v in (ch or {}).items():
        if isinstance(v, dict):
            sortie[str(k)] = {"paragraphes": [str(x).strip() for x in v.get("paragraphes") or [] if str(x).strip()],
                              "exergue": str(v.get("exergue") or "").strip(),
                              "a_surveiller": [str(x).strip() for x in v.get("a_surveiller") or [] if str(x).strip()]}
    return sortie


def aligner(textes: dict, demandes) -> dict:
    """Réponse rangée sous d'autres clés que celles demandées : un seul chapitre demandé et un seul rendu -> réaligné ;
    même nombre de chapitres -> dans l'ordre. Les chapitres déjà bien rangés ne bougent pas."""
    demandes = list(demandes)
    if set(textes) >= set(demandes):
        return textes
    if len(demandes) == 1 and len(textes) == 1:
        return {demandes[0]: next(iter(textes.values()))}
    if len(textes) == len(demandes) and not set(textes) & set(demandes):
        return dict(zip(demandes, textes.values()))
    return textes


def mots(texte: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ'’-]+\b", str(texte or "")))


# ------------------------------------------------------------------ 6. rédaction d'un groupe
def rediger_groupe(faits_par_ch: dict[str, dict], dates_semaine: list[str], gemini=None, groq=None, etiquette: str = "documentaire:g1",
                   correction: bool = True) -> tuple[dict, dict]:
    """Gemini (chaîne gemini-3.5-flash -> gemini-3.5-flash-lite) pour tout le groupe, avec un appel de correction ; puis
    Groq chapitre par chapitre pour ce qui manque. -> ({numéro: récit accepté}, journal)."""
    from core.llm import definir_etiquette, libelle_modele, dernier_modele
    acceptes, journal = {}, {"tentatives": []}
    restants = dict(faits_par_ch)

    def examiner(textes: dict, par: str) -> dict:
        problemes = {}
        for k in list(restants):
            r = textes.get(k)
            if not r:
                continue
            if k in ("0", "final"):
                r["_court"] = True
            c = controler(r, restants[k]["faits"], dates_semaine)
            r.pop("_court", None)
            if c["bloquant"]:
                problemes[k] = c
                journal.setdefault("rejetes", {})[k] = {**r, "par": par, "controle": {x: c[x] for x in ("nombres", "vocabulaire", "vide")}}
            else:
                acceptes[k] = {**r, "redige_par": par, "mots": mots(" ".join(r["paragraphes"]))}
                restants.pop(k)
        return problemes

    if gemini is not None and restants:
        try:
            definir_etiquette(etiquette)
            brut = gemini.appeler_llm(prompt_groupe(restants))
            par = libelle_modele(dernier_modele()) or "modèle principal"
            textes = aligner(extraire(brut), restants)
            problemes = examiner(textes, par)
            journal["tentatives"].append({"par": par, "chapitres": sorted(textes), "problemes": {k: {x: p[x] for x in ("nombres", "vocabulaire", "vide")} for k, p in problemes.items()}})
            corrigeables = {k: p for k, p in problemes.items() if not p["vide"] and k in textes} if correction else {}
            if corrigeables:
                definir_etiquette(etiquette + ":correction")
                brut2 = gemini.appeler_llm(prompt_correction(textes, corrigeables))
                textes2 = aligner(extraire(brut2), corrigeables)
                p2 = examiner(textes2, f"{par}, corrigé")
                journal["tentatives"].append({"par": f"{par} (correction)", "problemes": {k: {x: p[x] for x in ("nombres", "vocabulaire", "vide")} for k, p in p2.items()}})
        except Exception as exc:  # noqa: BLE001 — quota épuisé, panne : Groq
            journal["tentatives"].append({"par": "gemini", "erreur": f"{type(exc).__name__} : {str(exc)[:200]}"})
    if groq is not None and restants:
        for k in list(restants):
            if not getattr(groq, "disponible", lambda: True)():
                journal["tentatives"].append({"par": "groq", "erreur": "quota Groq du jour atteint"})
                break
            try:
                brut = groq.appeler(prompt_groupe({k: restants[k]}))
                textes = aligner(extraire(brut), [k])
                par = f"secours {getattr(groq, 'nom', 'groq')}"
                problemes = examiner(textes, par)
                if k in problemes and not problemes[k]["vide"] and groq.disponible():
                    textes2 = aligner(extraire(groq.appeler(prompt_correction(textes, {k: problemes[k]}))), [k])
                    problemes = examiner(textes2, f"{par}, corrigé")
                journal["tentatives"].append({"par": par, "chapitre": k, "problemes": {c: {x: p[x] for x in ("nombres", "vocabulaire", "vide")} for c, p in problemes.items()}})
            except Exception as exc:  # noqa: BLE001
                journal["tentatives"].append({"par": "groq", "chapitre": k, "erreur": f"{type(exc).__name__} : {str(exc)[:200]}"})
    journal["acceptes"] = sorted(acceptes)
    journal["manquants"] = sorted(restants)
    return acceptes, journal


# ------------------------------------------------------------------ 7. chaînes de modèles du documentaire
def chaine_gemini(config: dict, complet: bool = True):
    """gemini-3.5-flash puis gemini-3.5-flash-lite (ordre de config documentaire.modeles), budget « documentaire »."""
    from core.llm import creer_fournisseur
    cfg = json.loads(json.dumps(config))
    voulus = ((config.get("documentaire") or {}).get("modeles")) or ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
    par_nom = {m["modele"]: m for m in cfg["llm"].get("modeles") or []}
    cfg["llm"]["modeles"] = [par_nom.get(m, {"modele": m, "quota_jour": 20}) for m in voulus]
    llm = creer_fournisseur(cfg)
    if hasattr(llm, "configurer_budget") and cfg["llm"].get("budget"):
        llm.configurer_budget(cfg["llm"]["budget"], complet=complet, lundi=date.today().weekday() == 0)
    return llm


def secours_groq(config: dict, racine: Path):
    """Groq avec le modèle retenu pour le documentaire (config documentaire.groq_modele), quota commun du secours."""
    from agents import agent_synthese_v9
    cfg = dict(((config.get("synthese_v9") or {}).get("secours")) or {})
    m = (config.get("documentaire") or {}).get("groq_modele")
    if m:
        cfg["modele"] = m
    return agent_synthese_v9.Secours(cfg, racine)
