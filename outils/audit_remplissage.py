"""Audit de remplissage du site (lot V6, partie B) : pour chaque bloc des 6 onglets, part des valeurs réelles et des
« n/d » dans les fichiers publiés du jour (docs/data). Règle : ≥ 50 % gardé ; < 50 % replié en une ligne « Données
insuffisantes : raison » ou fusionné ; vide depuis plus de 7 jours (rapports archivés) : retiré.
Usage : python outils/audit_remplissage.py [--markdown]"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOCS = RACINE / "docs" / "data"
ND = re.compile(r"(^|\W)n/d(\W|$)|^—$|^$")


def lire(nom):
    try:
        return json.loads((DOCS / nom).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def compter(x, cles=None) -> tuple[int, int]:
    """(réelles, n/d) sur les feuilles d'un sous-arbre ; `cles` limite les clés comptées dans les dictionnaires."""
    if x is None:
        return 0, 1
    if isinstance(x, bool):
        return 1, 0
    if isinstance(x, (int, float)):
        return 1, 0
    if isinstance(x, str):
        return (0, 1) if ND.search(x.strip()) else (1, 0)
    if isinstance(x, list):
        r = n = 0
        for v in x:
            a, b = compter(v, cles)
            r, n = r + a, n + b
        return (r, n) if x else (0, 1)
    if isinstance(x, dict):
        r = n = 0
        for k, v in x.items():
            if cles and k not in cles:
                continue
            a, b = compter(v, cles)
            r, n = r + a, n + b
        return r, n
    return 1, 0


def blocs() -> list[tuple[str, str, object, set | None]]:
    rj, prof, ag, tm, dos, pai, cs = (lire(n) for n in ("rapport_jour.json", "profil_devises.json", "agenda.json",
                                                         "tableau_macro.json", "dossiers.json", "paires.json", "consequences_synthese.json"))
    hb = lire("dossiers_hebdo.json")
    rj, prof, ag, tm, dos, pai = rj or {}, prof or {}, ag or {}, tm or {}, dos or {}, pai or {}
    forts = [e for j in ag.get("jours") or [] for e in j.get("evenements") or [] if e.get("impact") == "fort"]
    return [
        ("Synthèse", "L'essentiel", (rj.get("essentiel") or {}).get("lignes"), None),
        ("Synthèse", "Depuis hier", [rj.get("depuis_veille"), (rj.get("publications_veille") or {}).get("publications")], {"texte", "reaction"}),
        ("Synthèse", "Aujourd'hui (Agenda 24 h)", rj.get("evenements_jour"), {"heure_paris", "evenement", "consensus", "precedent"}),
        ("Synthèse", "Tableau des devises", (rj.get("devises") or {}).get("lignes"), None),
        ("Synthèse", "Scénarios (conditions)", [c for s in (rj.get("scenarios") or {}).get("liste") or [] for c in s["conditions"]], {"remplie"}),
        ("Synthèse", "Watchlist top 3", rj.get("watchlist_top3"), {"paire", "differentiel_pb", "confirmations"}),
        ("Synthèse", "Plan du jour", rj.get("plan"), {"avant", "pendant", "cloture"}),
        ("Synthèse", "Synthèse hebdomadaire", (hb or {}).get("synthese"), {"theme_semaine", "ce_qui_pourrait_tout_changer"}),
        ("Synthèse", "Synthèse mensuelle", (cs or {}).get("mensuel"), {"texte", "devises"}),
        ("Tableau de bord", "Point de marché", (rj.get("point_marche") or {}).get("lignes"), {"niveau", "variation_j1", "variation_5j", "lecture"}),
        ("Tableau de bord", "Lecture par devise", [d.get("macro", {}).get("texte") for d in prof.get("devises") or []], None),
        ("Tableau de bord", "Tableau macro (Actuel)", [l.get("Actuel") if (l.get("etat") or {}).get("Actuel") == "valeur" else None for l in tm.get("lignes") or []], None),
        ("Tableau de bord", "Tableau macro (Prévision)", [l.get("Prévision") if (l.get("etat") or {}).get("Prévision") == "valeur" else None for l in tm.get("lignes") or []], None),
        ("Devises", "Moteur du moment", [(d.get("moteur") or {}).get("dominant") and "ok" or "n/d" for d in prof.get("devises") or []], None),
        ("Devises", "Banque centrale (dernière décision)", [((d.get("banque_centrale") or {}).get("derniere") or {}).get("texte") for d in prof.get("devises") or []], None),
        ("Devises", "Ton du dernier communiqué", [((d.get("banque_centrale") or {}).get("ton") or {}).get("valeur") for d in prof.get("devises") or []], None),
        ("Devises", "Inflation contre cible", [((d.get("macro") or {}).get("inflation") or {}).get("ecart") for d in prof.get("devises") or []], None),
        ("Devises", "Surprises 30 jours", [((d.get("macro") or {}).get("surprise_30j") or {}).get("indice") for d in prof.get("devises") or []], None),
        ("Agenda", "Consensus des évènements forts", [e.get("consensus") for e in forts if e.get("type") == "Chiffre"], None),
        ("Agenda", "Banques centrales (taux, prochaine réunion)", ag.get("banques_centrales"), {"taux_texte", "prochaine"}),
        ("Agenda", "Prises de parole", ag.get("prises_de_parole") or [], {"evenement"}),
        ("8 engrenages", "Thermomètres", (dos.get("cockpit") or {}).get("thermometres"), {"valeur"}),
        ("8 engrenages", "Matrice d'impact (cases mesurées)", [c.get("etat") != "nd" and "ok" or "n/d" for l in (dos.get("matrice_impact") or {}).get("lignes") or [] for c in l.get("cases") or []], None),
        ("8 engrenages", "Indicateurs des dossiers", [i.get("texte") for e in (dos.get("engrenages") or {}).values() for i in (e or {}).get("indicateurs") or []], None),
        ("8 engrenages", "Fil des séances", [c.get("classe") for l in ((dos.get("cockpit") or {}).get("fil") or {}).get("lignes") or [] for c in l.get("cellules") or []], None),
        ("Journal", "Fiches des paires (technique)", [(f.get("technique") or {}).get("rsi14") for f in (pai.get("fiches") or {}).values()], None),
        ("Journal", "Fiches des paires (portage 2 ans)", [((f.get("macro") or {}).get("portage") or {}).get("deux_ans_pb") for f in (pai.get("fiches") or {}).values()], None),
    ]


def vides_7_jours(nom_bloc: str) -> bool | None:
    """Bloc vide dans chacun des 7 derniers rapports archivés (blocs issus du rapport archivé seulement)."""
    cle = {"Ton du dernier communiqué": "communiques"}.get(nom_bloc)
    if not cle:
        return None
    fichiers = sorted((RACINE / "data" / "archives" / "rapport_jour").glob("*.json"))[-7:]
    if len(fichiers) < 7:
        return None
    return all(not ((json.loads(f.read_text(encoding="utf-8")).get("textes") or {}).get(cle)) for f in fichiers)


def audit() -> list[dict]:
    sortie = []
    for onglet, bloc, x, cles in blocs():
        r, n = compter(x, cles)
        pct = round(100 * r / (r + n)) if r + n else 0
        vide7 = vides_7_jours(bloc) if pct == 0 else None
        decision = "gardé" if pct >= 50 else ("retiré (vide depuis plus de 7 jours)" if vide7 else "replié : « Données insuffisantes : raison »")
        sortie.append({"onglet": onglet, "bloc": bloc, "reelles": r, "nd": n, "pct": pct, "decision": decision})
    return sortie


if __name__ == "__main__":
    lignes = audit()
    if "--markdown" in sys.argv:
        print("| Onglet | Bloc | Réelles | n/d | Rempli | Décision |\n|---|---|---|---|---|---|")
        for l in lignes:
            print(f"| {l['onglet']} | {l['bloc']} | {l['reelles']} | {l['nd']} | {l['pct']} % | {l['decision']} |")
    else:
        print(json.dumps(lignes, ensure_ascii=False, indent=1))
