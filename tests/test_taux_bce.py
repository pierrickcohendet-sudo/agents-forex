"""Lot Verrouillage, point 3 : taux de dépôt BCE automatique (FRED ECBDFR, sinon API BCE), plus de saisie manuelle."""
from pathlib import Path
from unittest import mock

import yaml

from agents import collecte_macro
from core import agenda

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def test_plus_de_saisie_manuelle_pour_l_euro():
    assert "EUR" not in CONFIG["taux_directeurs"] and CONFIG["fred"]["series"]["bce_depot"] == "ECBDFR"


def test_fred_d_abord_puis_api_bce_puis_nd():
    t = collecte_macro.taux_depot_bce({"valeur": 2.5, "date": "2026-10-28"})
    assert t == {"taux": 2.5, "date": "2026-10-28", "source": "FRED (ECBDFR, taux de la facilité de dépôt de la BCE)", "type": "dépôt"}
    rep = mock.Mock()
    rep.json.return_value = {"dataSets": [{"series": {"0:0": {"observations": {"0": [2.25, 0], "1": [2.5, 0]}}}}],
                             "structure": {"dimensions": {"observation": [{"values": [{"id": "2026-10-27"}, {"id": "2026-10-28"}]}]}}}
    with mock.patch.object(collecte_macro.requests, "get", return_value=rep) as get:
        t = collecte_macro.taux_depot_bce(None)
    assert t["taux"] == 2.5 and t["date"] == "2026-10-28" and "API de données de la BCE" in t["source"]
    assert "data-api.ecb.europa.eu" in get.call_args[0][0]
    with mock.patch.object(collecte_macro.requests, "get", side_effect=OSError("hors ligne")):
        t = collecte_macro.taux_depot_bce(None)
    assert t["taux"] is None and "API BCE en échec" in t["raison"]


def test_agenda_depot_principal_refinancement_secondaire_et_fourchette_fed():
    macro = {"series": {"fed_cible_basse": {"valeur": 3.75, "date": "2026-10-28"}, "fed_cible_haute": {"valeur": 4.0, "date": "2026-10-28"}},
             "taux_directeurs": {"EUR": {"taux": 2.5, "date": "2026-10-28", "source": "FRED (ECBDFR)", "type": "dépôt"}}}
    eur = agenda.taux_principal("EUR", {"valeur": "2.65%"}, macro)
    assert eur["texte"] == "2.50%" and eur["type"] == "dépôt" and "refinancement 2.65%" in eur["secondaire"]
    usd = agenda.taux_principal("USD", {"valeur": "3.88%"}, macro)
    assert usd["type"] == "fourchette cible" and usd["texte"] == "3.75–4.00%"
    assert agenda.taux_principal("EUR", {"valeur": "2.65%"}, {})["raison"]          # dépôt n/d : raison affichée
