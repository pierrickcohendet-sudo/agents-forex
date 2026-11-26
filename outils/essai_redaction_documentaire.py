"""Essai manuel de rédaction du documentaire (lot V15), HORS des tests : de vrais appels à un modèle.

Usage :
  python outils/essai_redaction_documentaire.py groq <chapitre> <modèle groq>   (un appel Groq sur un chapitre)
  python outils/essai_redaction_documentaire.py gemini                          (2 appels Gemini : chapitres 0 à 4, puis 5 à 8 et final)
Données : celles du site (semaine en cours), « maintenant » = argument --le AAAA-MM-JJTHH:MM (UTC) si donné.
Écrit le résultat dans captures/v15/essai_<type>.json (récits, contrôle, journal). N'écrit pas le documentaire du site.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))


def main() -> int:
    import yaml
    from dotenv import load_dotenv
    from core import documentaire as doc, redaction_documentaire as rd
    load_dotenv(RACINE / ".env")
    config = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    le = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--le=")), None)
    maintenant = datetime.fromisoformat(le).replace(tzinfo=timezone.utc) if le else datetime.now(timezone.utc)
    d = doc.calculer(RACINE, maintenant, None, config)
    sortie = RACINE / "captures" / "v15"
    sortie.mkdir(parents=True, exist_ok=True)
    if args and args[0] == "groq":
        k, modele = args[1], args[2]
        from core.llm import FournisseurGroq
        f = doc._faits_du_chapitre(d, k)
        g = FournisseurGroq(modele=modele, temperature=0.2, pause_min_s=1, backoff_429_s=30, budget_tokens_systeme=200,
                            budget_tokens_message=7000, budget_tokens_total_max=9000)
        brut = g.appeler_llm(rd.prompt_groupe({k: f}))
        print("BRUT", len(brut), repr(brut[:600]))
        textes = rd.aligner(rd.extraire(brut), [k])
        r = textes.get(k) or {}
        c = rd.controler({**r, "_court": k in ("0", "final")}, f["faits"], d.get("jours_couverts"))
        res = {"modele": modele, "chapitre": k, "mots": rd.mots(" ".join(r.get("paragraphes") or [])), "controle": c, "recit": r}
        (sortie / f"essai_groq_{modele.replace('/', '_')}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({x: res[x] for x in ("modele", "mots", "controle")}, ensure_ascii=False))
        return 0
    gemini = rd.chaine_gemini(config, complet=False)
    resultats, journal = {}, {}
    seuls = [a for a in args[1:] if a in rd.GROUPES]   # « gemini g1 » : un seul groupe
    for g, ids in rd.GROUPES.items():
        if seuls and g not in seuls:
            continue
        faits = {k: f for k in ids if (f := doc._faits_du_chapitre(d, k))}
        # essai autorisé : 2 appels Gemini exactement (pas d'appel de correction ; le contrôle est noté dans le journal)
        acceptes, j = rd.rediger_groupe(faits, d.get("jours_couverts") or [], gemini, None, etiquette=f"documentaire:{g}", correction=False)
        j["textes_bruts"] = getattr(gemini, "_dernier_brut", None)
        resultats.update(acceptes)
        journal[g] = j
    (sortie / f"essai_gemini{'_' + '_'.join(seuls) if seuls else ''}.json").write_text(json.dumps({"semaine": d["semaine"], "recits": resultats, "journal": journal},
                                                          ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(journal, ensure_ascii=False)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
