"""Fige le rejeu du documentaire (lot V13) : semaine du 16 au 20/11/2026, vue du samedi 21/11.

Recopie dans tests/donnees/rejeu_2026-11-21/ les seules données lues par core/documentaire.py, réduites :
dossiers (tuiles des moteurs, thermomètres, en-tête), agenda (16 au 27/11), dossiers des moteurs (état, devises, agenda),
cours des paires, contexte (dernier instantané de chaque jour : thème et devises), archive des publications (réel et
consensus), titres de la semaine 2026-S47 et séries 5 ans des graphiques (depuis le 01/05/2026).
Usage : python outils/figer_rejeu_v13.py  (à relancer seulement pour refaire le rejeu)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
from core import contexte as ctx_mod  # noqa: E402
from core.documentaire import GRAPHIQUES  # noqa: E402

DEST = RACINE / "tests" / "donnees" / "rejeu_2026-11-21"
JOURS = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]


def lire(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def ecrire(rel: str, d) -> None:
    p = DEST / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    docs, cache = RACINE / "docs" / "data", RACINE / "data" / "cache"
    dos = lire(docs / "dossiers.json")
    tuiles = {k: {"tuiles": [{c: t.get(c) for c in ("libelle", "texte", "date", "source", "raison", "variation", "percentile_5a",
                                                     "lecture", "note", "unite", "courbe")} for t in (e.get("tuiles") or [])]}
              for k, e in (dos.get("engrenages") or {}).items()}
    for e in tuiles.values():
        for t in e["tuiles"]:
            if t.get("courbe"):
                t["courbe"] = {"points": [p for p in (t["courbe"].get("points") or []) if str(p[0]) >= "2026-05-01"]}
    ck = dos.get("cockpit") or {}
    ecrire("docs/data/dossiers.json", {"engrenages": tuiles, "cockpit": {"entete": ck.get("entete"), "thermometres": ck.get("thermometres")}})

    ag = lire(docs / "agenda.json")
    ecrire("docs/data/agenda.json", {"fin": ag.get("fin"), "jours": [
        {**{k: v for k, v in j.items() if k != "evenements"},
         "evenements": [e for e in (j.get("evenements") or []) if e.get("impact") in ("moyen", "fort") or e.get("type") in ("Discours", "Réunion BC")]}
        for j in (ag.get("jours") or []) if "2026-11-16" <= str(j.get("date") or (j.get("evenements") or [{}])[0].get("date_paris") or "") <= "2026-11-27"]})

    md = lire(docs / "moteurs_dossiers.json")
    ecrire("docs/data/moteurs_dossiers.json", {"moteurs": {k: {c: m.get(c) for c in ("etat", "devises", "agenda")} for k, m in (md.get("moteurs") or {}).items()}})

    pj = lire(docs / "paires.json")
    ecrire("docs/data/paires.json", {"fiches": {p: {"cours_jour": f.get("cours_jour")} for p, f in (pj.get("fiches") or {}).items()}})

    for j in JOURS:
        f = lire(docs / "contexte" / f"{j}.json")
        inst = ctx_mod.reconstituer(f, len(f["instantanes"]) - 1)
        refs = {"theme": "t", "devises": "d"}
        ecrire(f"docs/data/contexte/{j}.json", {"version": f.get("version"), "date": j, "blocs": {"t": inst.get("theme"), "d": inst.get("devises")},
                                                "instantanes": [{"heure_utc": inst["heure_utc"], "rapport_du": inst.get("rapport_du"), "refs": refs}]})

    arch = lire(cache / "publications_archive.json")
    ecrire("data/cache/publications_archive.json", {"publications": {k: {c: p.get(c) for c in (
        "date", "heure_paris", "devise", "evenement", "evenement_en", "type", "impact", "reel", "consensus", "precedent", "source")}
        for k, p in (arch.get("publications") or {}).items() if p.get("reel") or str(p.get("date")) >= "2026-11-16"}})

    ts = lire(cache / "titres_semaine.json")
    ecrire("data/cache/titres_semaine.json", {"semaines": {"2026-S47": (ts.get("semaines") or {}).get("2026-S47") or {}}})

    h5 = lire(cache / "historique_5ans.json")
    from core import historique_5ans
    h = historique_5ans.Historique(h5)
    cles = sorted({c for l in GRAPHIQUES.values() for c, *_ in l})
    ecrire("historique_graphiques.json", {c: [[d, v] for d, v in h.serie(c) if "2026-05-01" <= d <= "2026-11-20"] for c in cles})
    print("rejeu figé :", sum(p.stat().st_size for p in DEST.rglob("*.json")) // 1024, "Ko")


if __name__ == "__main__":
    main()
