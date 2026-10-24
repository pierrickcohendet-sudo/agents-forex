"""Lot V5, complément : agenda macro complet (traduction, types, lignes discrètes, calendriers officiels, badges,
réaction passée, FRED). Sans réseau, sans LLM."""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from core import agenda

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
SAMEDI = datetime(2026, 10, 24, 10, tzinfo=timezone.utc)


def test_traduction_exacte_composee_discours_et_non_traduit():
    t = agenda.Traducteur(CONFIG["agenda"])
    assert t.traduire("Advance GDP q/q") == ("PIB T/T, 1re estimation", True)
    assert t.traduire("German Flash Manufacturing PMI") == ("Allemagne : PMI manufacturier, flash", True)
    assert t.traduire("Core CPI m/m") == ("IPC sous-jacent M/M", True)
    assert t.traduire("BOE Gov Bailey Speaks") == ("Discours de Bailey, gouverneur de la BoE", True)
    assert t.traduire("Gov Council Member Rogers Speaks")[0] == "Discours de Rogers, membre du conseil de direction (BoC)"
    assert t.traduire("Fed Chair Powell Testifies")[0].startswith("Audition de Powell")
    assert t.traduire("Zorglub Index") == ("Zorglub Index", False) and t.non_traduits == {"Zorglub Index"}


def test_types_et_impacts():
    assert agenda.type_evenement("Official Cash Rate") == "Réunion BC"
    assert agenda.type_evenement("FOMC Press Conference") == "Conférence"
    assert agenda.type_evenement("ECB President Lagarde Speaks") == "Discours"
    assert agenda.type_evenement("IMF Meetings") == "Grand rendez-vous"
    assert agenda.type_evenement("CPI y/y") == "Chiffre"


def test_lignes_sans_interet_de_marche_regroupees_en_une_ligne_discrete():
    ff = json.dumps([{"title": "Daylight Saving Time Shift", "country": c, "date": "2026-10-25T02:00:00+02:00", "impact": "Holiday"}
                     for c in ("EUR", "GBP", "CHF")] +
                    [{"title": "Bank Holiday", "country": "JPY", "date": "2026-11-03T00:00:00+09:00", "impact": "Holiday"}])
    a = agenda.calculer(ff, [], {}, CONFIG, SAMEDI)
    dim = next(j for j in a["jours"] if j["date"] == "2026-10-25")
    assert not dim["evenements"] and dim["discrets"][0]["texte"] == "Changement d'heure"
    assert sorted(dim["discrets"][0]["devises"]) == ["CHF", "EUR", "GBP"]
    assert all(e["evenement_en"] != "Daylight Saving Time Shift" for j in a["jours"] for e in j["evenements"])


def test_changement_d_heure_paris_avant_et_apres_le_25_octobre():
    ff = json.dumps([{"title": "CPI m/m", "country": "USD", "date": "2026-10-23T08:30:00-04:00", "impact": "High"},
                     {"title": "Retail Sales m/m", "country": "USD", "date": "2026-10-27T08:30:00-04:00", "impact": "High"}])
    a = agenda.calculer(ff, [], {}, CONFIG, SAMEDI)
    h = {e["evenement_en"]: e["heure_paris"] for j in a["jours"] for e in j["evenements"]}
    assert h["CPI m/m"] == "14:30" and h["Retail Sales m/m"] == "13:30"   # Paris passe à l'heure d'hiver le 25/10, New York le 01/11


def test_badges_hausse_baisse_statu_quo_et_borne():
    assert agenda.badge_decision("3.00%", "2.75%")["texte"] == "hausse attendue"
    assert agenda.badge_decision("2.50%", "2.75%") == {"sens": "baisse", "texte": "baisse attendue", "pb": -25}
    assert agenda.badge_decision("4.00%", "4.00%")["sens"] == "statu_quo"
    assert agenda.badge_decision("<1.25%", "<1.25%")["sens"] == "statu_quo"
    assert agenda.badge_decision("<1.50%", "<1.25%") is None and agenda.badge_decision(None, "2%") is None


def test_fed_comparee_a_la_borne_haute_de_la_fourchette_cible():
    reg = {"cases": {"USD|taux_directeur": {"devise": "USD", "actuel": {"valeur": "3.88%", "origine": "taux_config"},
                                            "prevision": {"dateline": int(datetime(2026, 10, 28, 18, tzinfo=timezone.utc).timestamp()),
                                                          "nom_ff": "Federal Funds Rate", "impact": "High", "valeur": "4.00%"}},
                     "NZD|taux_directeur": {"devise": "NZD", "actuel": {"valeur": "2.75%"},
                                            "prevision": {"dateline": int(datetime(2026, 10, 28, 1, tzinfo=timezone.utc).timestamp()),
                                                          "nom_ff": "Official Cash Rate", "impact": "High", "valeur": "3.00%"}}}}
    macro = {"series": {"fed_cible_haute": {"serie_id": "DFEDTARU", "valeur": 4.0, "date": "2026-10-23"}}}
    a = agenda.calculer(None, [], reg, CONFIG, SAMEDI, macro=macro)
    evts = {e["devise"]: e for j in a["jours"] for e in j["evenements"] if e["type"] == "Réunion BC"}
    assert evts["USD"]["badge"]["texte"] == "statu quo attendu" and "DFEDTARU" in evts["USD"]["badge"]["source_reference"]
    assert evts["NZD"]["badge"]["texte"] == "hausse attendue" and evts["NZD"]["badge"]["pb"] == 25
    nzd = next(b for b in a["banques_centrales"] if b["devise"] == "NZD")
    assert nzd["cette_semaine"] and nzd["calendrier"]["statut"] == "secondaire" and "403" in nzd["raison_reunions"]


def test_reunions_officielles_toutes_les_banques_et_lpr_le_20():
    a = agenda.calculer(None, [], {}, CONFIG, SAMEDI)
    bcs = {b["devise"]: b for b in a["banques_centrales"]}
    assert all(b["prochaine"] for b in bcs.values())                          # plus aucune « prochaine réunion » n/d
    assert all(len(b["reunions"]) == 3 for d, b in bcs.items() if d != "NZD")
    assert bcs["USD"]["reunions"][0]["date"] == "2026-10-28" and bcs["CHF"]["prochaine"] == "2026-12-10"
    assert [d.isoformat() for d in agenda.dates_reunions({"regle": "lpr_20"}, date(2026, 12, 1), date(2027, 2, 28))] == \
        ["2026-12-21", "2027-01-20", "2027-02-22"]                            # 20/12/2026 dimanche, 20/02/2027 samedi
    boc = next(e for j in a["jours"] for e in j["evenements"] if e["devise"] == "CAD" and e["type"] == "Réunion BC")
    assert boc["heure_paris"] == "14:45" and boc["officiel"]["statut"] == "officiel"   # 09:45 Ottawa, source officielle
    for devise, cfg in CONFIG["agenda"]["reunions"].items():
        assert cfg["source"] and cfg["verifie_le"] and cfg["statut"] in ("officiel", "secondaire", "regle"), devise


def test_fred_complete_sans_doublon_avec_forexfactory():
    ff = json.dumps([{"title": "Advance GDP q/q", "country": "USD", "date": "2026-10-29T08:30:00-04:00", "impact": "High",
                      "forecast": "3.2%", "previous": "2.2%"}])
    fred = {"dates": [{"date": "2026-10-29", "release_name": "Gross Domestic Product"},
                      {"date": "2026-10-30", "release_name": "Employment Cost Index"},
                      {"date": "2026-10-30", "release_name": "FOMC Press Release"}], "collecte_le": "2026-10-24"}
    a = agenda.calculer(ff, [], {}, CONFIG, SAMEDI, fred=fred)
    usd = [e for j in a["jours"] for e in j["evenements"] if e["devise"] == "USD" and e["type"] == "Chiffre"]
    pib = [e for e in usd if "PIB" in e["evenement"]]
    assert len(pib) == 1 and pib[0]["consensus"] == "3.2%" and pib[0]["confirme_par"]
    eci = next(e for e in usd if e["evenement_en"] == "Employment Cost Index")
    assert eci["heure_paris"] == "journée" and eci["raison_heure"] and eci["impact"] == "moyen"
    assert not any("FOMC Press Release" in e["evenement_en"] for e in usd)


def test_reaction_passee_simulateur_puis_archive_et_indice_faible():
    reg = {"cases": {"USD|taux_directeur": {"devise": "USD", "prevision": {
        "dateline": int(datetime(2026, 10, 28, 18, tzinfo=timezone.utc).timestamp()), "nom_ff": "Federal Funds Rate", "impact": "High"}}}}
    impact = {"couples": {"fed|USD": {"scenarios": {"hausse|1": {"demain": {"n": 21, "mediane": 0.13, "borne_wilson_90": 39.6}},
                                                     "baisse|1": {"demain": {"n": 19, "mediane": -0.02, "borne_wilson_90": 34.7}}}}}}
    ff = json.dumps([{"title": "CPI y/y", "country": "AUD", "date": "2026-10-27T20:30:00-04:00", "impact": "High"}])
    archive = {"publications": {"a": {"devise": "AUD", "nom": "CPI y/y", "date": "2026-07-29", "reel": "4.1%", "prevision": "3.9%"},
                                "b": {"devise": "AUD", "nom": "CPI y/y", "date": "2026-04-29", "reel": "3.5%", "prevision": "3.8%"}}}
    series = {"AUD/USD": [("2026-04-29", 0.70), ("2026-04-30", 0.69), ("2026-07-29", 0.66), ("2026-07-30", 0.67)]}
    a = agenda.calculer(ff, [], reg, CONFIG, SAMEDI, impact=impact, archive=archive, series=series)
    evts = {e["devise"]: e for j in a["jours"] for e in j["evenements"] if e["impact"] == "fort" and e["type"] != "Grand rendez-vous"}
    fed = evts["USD"]["reaction"]
    assert fed["cote"]["au_dessus"]["n"] == 21 and not fed["cote"]["au_dessus"]["faible"] and fed["cote"]["au_dessous"]["faible"]
    assert fed["lien"] == "#scenarios/i=fed"
    aud = evts["AUD"]["reaction"]
    assert aud["cote"]["au_dessus"]["n"] == 1 and aud["cote"]["au_dessus"]["mediane"] > 0 and aud["cote"]["au_dessus"]["faible"]
    assert aud["cote"]["au_dessous"]["mediane"] < 0


def test_page_mois_memorisee_sans_requete_et_publications_archivees(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    t = int(datetime(2026, 10, 28, 0, 30, tzinfo=timezone.utc).timestamp())
    evts = [{"id": 1, "devise": "AUD", "nom": "CPI y/y", "impact": "High", "dateline": t, "prevision": "4.2%", "precedent": "4.0%"},
            {"id": 2, "devise": "AUD", "nom": "CPI q/q", "impact": "High", "dateline": t - 86400 * 90, "reel": "1.0%"},
            {"id": 3, "devise": "USD", "nom": "Retail Sales m/m", "impact": "High",
             "dateline": int(datetime(2026, 10, 20, 12, 30, tzinfo=timezone.utc).timestamp()), "reel": "0.4%", "prevision": "0.2%"}]
    agenda.memoriser_mois(evts, cache, SAMEDI)
    m = json.loads((cache / "calendrier_mois.json").read_text(encoding="utf-8"))
    assert [e["id"] for e in m["evenements"]] == [3, 1]                     # -14 j à +60 j
    arch = json.loads((tmp_path / "archives" / "publications.json").read_text(encoding="utf-8"))
    assert len(arch["publications"]) == 2
    a = agenda.calculer(None, [], {}, CONFIG, SAMEDI, mois=m["evenements"])
    rs = next(e for j in a["jours"] for e in j["evenements"] if e["evenement_en"] == "Retail Sales m/m")
    assert rs["publie"] == "0.4%" and rs["evenement"] == "Ventes au détail M/M" and "page « mois »" in rs["source"]
    assert a["consensus"]["etat"] == "fonctionne"


def test_config_reunions_dans_l_ordre_et_dates_valides():
    for devise, cfg in CONFIG["agenda"]["reunions"].items():
        dates = [str(d) for d in cfg.get("dates") or []]
        assert dates == sorted(dates) and all(date.fromisoformat(d) for d in dates), devise
    for g in CONFIG["agenda"]["grands_rendez_vous"]:
        assert g["source"] and g["verifie_le"] and g["statut"] in ("officiel", "secondaire")
