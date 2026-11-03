"""Synthèse longue du lundi (lot V6, partie D) : 12 sections Python sur les fichiers publiés du dépôt, rédaction en
4 appels groupés au plus (faux modèle), repli Python si un appel échoue, décimales à la française. Sans réseau."""
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import yaml

from agents import agent_rapport as ar
from core import llm as L, rapport_jour as rj, rapport_long as rl

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
LUNDI = datetime(2026, 11, 2, 8, 30, tzinfo=timezone.utc)


def test_douze_sections_dans_l_ordre_du_rapport_modele():
    r = rj.calculer(RACINE, CONFIG, LUNDI)
    assert r["version"] == "longue" and r["sections"] == rl.SECTIONS_LONGUES and len(r["sections"]) == 12
    for cle in rl.SECTIONS_LONGUES:
        s = r[cle]
        assert s["titre"] and s["phrase_python"] and not s["phrase_python"].startswith("Section indisponible"), cle
        texte = json.dumps(s, ensure_ascii=False)
        assert "probabilité de" not in texte and "% de chances" not in texte and "achetez" not in texte.lower(), cle
    assert r["long_executive"]["blocs"][0]["texte"].startswith("Régime de marché qualitatif")
    assert any("UK 2 ans − US 2 ans : n/d" in i for b in r["long_marches"]["blocs"] if b["type"] == "liste" for i in b["items"])
    mardi = rj.calculer(RACINE, CONFIG, datetime(2026, 11, 3, 8, 30, tzinfo=timezone.utc))
    assert mardi["version"] == "courte" and mardi["sections"][0] == "essentiel" and "devises" in mardi["sections"]


def test_lecture_des_surprises_et_regime():
    e = {"devise": "USD", "evenement_en": "Unemployment Rate", "evenement": "Taux de chômage", "consensus": "4.2%"}
    assert rl.lecture_surprise(e, CONFIG) == ["Au-dessus de 4,2 % : lecture classique défavorable au USD.",
                                              "En dessous de 4,2 % : lecture classique favorable au USD."]
    e = {"devise": "USD", "evenement_en": "CPI y/y", "evenement": "IPC", "consensus": "3.1%"}
    assert "EUR" in rl.lecture_surprise(e, CONFIG)[0] and "sous pression" in rl.lecture_surprise(e, CONFIG)[0]
    reg = rl.regime_marche({"vix": {"valeur": 25}}, lambda c: [], None, CONFIG["rapport_long"])
    assert reg["libelle"] == "Prudent" and reg["mesures"] == 1


def test_vocabulaire_des_communiques_et_votes_dissidents():
    avant = "Recent indicators suggest that economic activity has been expanding at a solid pace. Inflation remains elevated."
    apres = "Recent indicators suggest that economic activity has been expanding at a strong pace. Inflation remains elevated. " \
            "Voting against the action was Stephen Miran, who preferred to lower the target range."
    assert rl.changements_vocabulaire(apres, avant) == [("solid", "strong")]
    assert rl.votes_dissidents(apres).startswith("Voting against")


class Faux:
    def __init__(self, reponses):
        self.reponses, self.etiquettes = list(reponses), []

    def appeler_llm(self, prompt, systeme=None):
        self.etiquettes.append(L._ETIQUETTE_COURANTE[0])
        r = self.reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_lundi_quatre_appels_groupes_et_repli_python():
    r = rj.calculer(RACINE, CONFIG, LUNDI)
    faux = Faux([json.dumps({"synthese": "Les catalyseurs dominent la semaine."}),
                 json.dumps({"watchlist": {}, "communiques": {}, "plan": "Avant la séance, relire les seuils."}),
                 json.dumps({"sections": {"long_intro": "Une semaine chargée, le régime de marché passe en mode défensif.",
                                          "long_marches": "Le Nasdaq recule de 77.77 % sur octobre."}}),
                 RuntimeError("503"), RuntimeError("503")])
    with mock.patch.object(ar, "attribution_modele", return_value={"libelle": "faux"}):
        t = ar.rediger(r, faux)
    assert faux.etiquettes == ["rapport:redaction", "rapport:analyse", "rapport:long1", "rapport:long2", "rapport:long2"]
    assert t["long"] == {"long_intro": "Une semaine chargée, le régime de marché passe en mode défensif."}   # 77,77 % : absent des faits
    rj.appliquer_textes(r, t)
    assert r["long_intro"]["texte"] and r["long_plan"]["texte"] is None and r["long_plan"]["phrase_python"]   # repli Python


def test_textes_du_modele_a_la_francaise():
    brut = L.extraire_json('{"synthese": "Le pétrole progresse de 6.84 % et le 2 ans recule de -13 pb.", "citations": ["rate at 4.5 percent"]}')
    assert brut["synthese"] == "Le pétrole progresse de 6,84 % et le 2 ans recule de −13 pb."
    assert brut["citations"] == ["rate at 4.5 percent"]                     # citation mot pour mot intacte
