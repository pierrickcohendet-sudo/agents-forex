"""Lot V14 : agenda façon ForexFactory (identifiants et liens, précédent révisé, historique, jours fériés et événements
« All », planning des lectures) et correctif V13.1 du documentaire (thermomètre du moteur 2, indicateurs clés, titres,
mise en forme, récits). Tout est simulé : aucune requête réseau, aucun appel au modèle."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from agents import agent_engrenages as ae
from agents import collecte_forexfactory_mois as ffm
from core import agenda as ag_mod
from core import documentaire as doc
from core import dossiers_moteurs as dm
from core import ff_historique as ffh
from core import ff_planning as plan
from core import indicateurs_cles, surprises
from outils import decider_mode

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))
MAINTENANT = datetime(2026, 11, 25, 21, 18, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def sans_cle(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp())


def ff(id_, devise, nom, iso, impact="low", reel=None, prev=None, precedent=None, revision=None, url=None):
    return {"id": id_, "ebase_id": id_ % 1000, "devise": devise, "nom": nom, "impact": impact, "dateline": ts(iso), "reel": reel,
            "prevision": prev, "precedent": precedent, "revision": revision, "url": url}


# ------------------------------------------------------------------ A1.1 identifiants et liens ForexFactory
def test_lien_ff_a_la_date_de_paris():
    # format vérifié sur une vraie page (26/11) : /calendar?day=oct2.2026#detail=146936 ; jour dans le fuseau du lecteur
    assert ag_mod.lien_ff(147679, ts("2026-11-23T08:15+00:00")) == "https://www.forexfactory.com/calendar?day=nov23.2026#detail=147679"
    # 00:30 UTC le 25/11 = 01:30 à Paris le 25/11 (le lien fourni à un runner GitHub portait nov24, date de New York)
    assert ag_mod.lien_ff(152602, ts("2026-11-25T00:30+00:00"), "/calendar?day=nov24.2026#detail=152602") == \
        "https://www.forexfactory.com/calendar?day=nov25.2026#detail=152602"
    assert ag_mod.lien_ff(None, None, "/calendar?day=oct14.2026#detail=148352").endswith("day=oct14.2026#detail=148352")
    assert ag_mod.lien_ff(None, None) is None


def _calculer(mois, registre=None, fred=None, tresor=None, grands=None):
    cfg = json.loads(json.dumps(CONFIG))
    if grands is not None:
        cfg.setdefault("agenda", {})["grands_rendez_vous"] = grands
    return ag_mod.calculer(None, [], registre or {}, cfg, MAINTENANT, mois=mois, fred=fred, tresor=tresor)


def test_rapprochement_des_quatre_lignes_sans_identifiant():
    mois = [ff(147679, "EUR", "French Flash Manufacturing PMI", "2026-11-23T08:15+00:00", "medium", "47.9", "49.8", "49.3", "49.5"),
            ff(149908, "JPY", "BOJ Core CPI y/y", "2026-11-25T05:00+00:00", "low"),
            ff(149583, "All", "OPEC-JMMC Meetings", "2026-11-29T10:15+00:00", "medium"),
            ff(149590, "All", "OPEC Meetings", "2026-11-29T11:15+00:00", "medium"),
            ff(146480, "USD", "Bank Holiday", "2026-11-26T13:00+00:00", "holiday")]
    registre = {"cases": {"JPY|cpi_core": {"devise": "JPY", "indicateur": "cpi_core", "actuel": {},
                                           "prevision": {"dateline": ts("2026-11-24T05:00+00:00"), "nom_ff": "BOJ Core CPI y/y", "impact": "low"}}}}
    fred = {"dates": [{"date": "2026-11-25", "release_name": "New Residential Construction"}], "erreurs": []}
    grands = [{"date": "2026-11-29", "titre": "Comité de suivi OPEP+ (JMMC) : offre de pétrole", "devises": ["CAD", "NOK"],
               "statut": "annoncé", "source": "TASS (04/10/2026)", "verifie_le": "2026-10-04"}]
    d = _calculer(mois, registre, fred, None, grands)
    ev = [e for j in d["jours"] for e in j["evenements"]]
    actions = {r["evenement"]: r["action"] for r in d["rapprochements_ff"]}
    # registre périmé (24/11) : doublon de la ligne ForexFactory du 25/11, retiré
    assert actions["JPY BOJ Core CPI y/y"] == "doublon retiré"
    assert [e["date_paris"] for e in ev if e["evenement_en"] == "BOJ Core CPI y/y"] == ["2026-11-25"]
    # grand rendez-vous de la configuration : rapproché de l'événement « All » de ForexFactory, à son heure
    opep = next(e for e in ev if "OPEP" in e["evenement"])
    assert opep["ff_id"] == 149583 and opep["heure_paris"] == "11:15"
    # événements « All » et jours fériés gardés, avec leur pastille
    disc = [x for j in d["jours"] for x in j["discrets"]]
    assert any(x["type"] == "Événement" and x["ff"][0]["ff_id"] == 149590 for x in disc)
    assert not any(x.get("ff") and x["ff"][0]["ff_id"] == 149583 for x in disc)      # déjà porté par la ligne OPEP+
    ferie = next(x for x in disc if x["type"] == "Férié")
    assert "Thanksgiving" in ferie["nom_ferie"] and ferie["ff"][0]["ff_id"] == 146480
    # toutes les lignes ForexFactory ont un identifiant et un lien
    pmi = next(e for e in ev if e["evenement_en"] == "French Flash Manufacturing PMI")
    assert pmi["ff_id"] == 147679 and pmi["ff_url"].endswith("#detail=147679")


def test_source_absente_de_forexfactory_raison_et_lien_officiel():
    fred = {"dates": [{"date": "2026-11-25", "release_name": "New Residential Construction"}], "erreurs": []}
    cfg_fred = (CONFIG.get("agenda") or {}).get("fred_publications") or {}
    d = _calculer([], None, fred)
    ev = [e for j in d["jours"] for e in j["evenements"] if "FRED" in str(e.get("source"))]
    if not cfg_fred or not ev:
        pytest.skip("publication FRED non suivie par la configuration")
    e = ev[0]
    assert e["ff_id"] is None and "absent du calendrier ForexFactory" in e["ff_raison"]
    assert e["lien_source"].startswith("https://fred.stlouisfed.org")


# ------------------------------------------------------------------ A1.2 précédent révisé
def test_sens_de_la_revision():
    # ForexFactory : « previous » = valeur publiée à l'origine, « revision » = valeur révisée
    assert ag_mod.texte_precedent("49.3", "49.5") == "précédent 49,3, révisé 49,5"
    assert ag_mod.texte_precedent("0.8%", None) == "précédent 0,8 %"
    assert ag_mod.texte_precedent("0.8%", "0.8%") == "précédent 0,8 %"
    assert ag_mod.texte_precedent(None, "1.0") is None
    d = _calculer([ff(147679, "EUR", "French Flash Manufacturing PMI", "2026-11-23T08:15+00:00", "medium", "47.9", "49.8", "49.3", "49.5")])
    e = d["jours"][0]["evenements"][0]
    assert (e["precedent"], e["revision"], e["precedent_texte"]) == ("49.3", "49.5", "précédent 49,3, révisé 49,5")


# ------------------------------------------------------------------ A1.3 historique
def test_historique_tri_six_points_rien_apres_la_publication():
    archive = {"publications": {f"2026-{m:02d}-15|USD|cpi": {"date": f"2026-{m:02d}-15", "devise": "USD", "evenement_en": "CPI y/y",
                                                           "reel": f"{m}.0%", "consensus": "x"} for m in (10, 11)}}
    d = {"series": {"USD|cpi y/y": {f"2026-{m:02d}-14": [f"{m}.1%", f"{m}.2%", 1] for m in range(2, 12)}}}
    h = ffh.historique("USD", "CPI y/y", "2026-11-14", archive, d)
    dates = [x[0] for x in h]
    assert len(h) == 6 and dates == sorted(dates) and all(x < "2026-11-14" for x in dates)
    assert dates[-1] == "2026-10-15"                  # l'archive du site l'emporte, et le 14/11 (jour même) est exclu
    assert ffh.historique("USD", "CPI y/y", "2026-01-01", archive, d) == []


def test_mois_a_reprendre_et_deux_pages_par_jour():
    assert ffh.mois_a_reprendre(date(2026, 11, 26))[:2] == ["oct.2026", "sep.2026"]
    assert ffh.mois_a_reprendre(date(2026, 11, 26))[-1] == "nov.2025"
    d = {"mois": {"oct.2026": {"statut": "lu"}}}
    assert ffh.a_tenter(d, date(2026, 11, 26)) == ["sep.2026", "aug.2026"]
    d["mois"]["sep.2026"] = {"statut": "lu", "tente_le": "2026-11-26T08:22:00+00:00"}
    assert ffh.a_tenter(d, date(2026, 11, 26)) == ["aug.2026"]          # une page déjà lue aujourd'hui


class ClientSimule:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def requete_directe(self, site, url):
        self.urls.append(url)
        mois = url.split("month=")[1]
        if mois not in self.pages:
            return {"statut": "indisponible", "contenu": None, "note": "HTTP 403"}
        jours = [{"events": [{"id": i, "ebaseId": 1, "currency": "USD", "name": "CPI y/y", "impactName": "high", "dateline": dl,
                              "actual": r, "forecast": "3.0%", "previous": "", "revision": "", "url": f"/calendar?day=x#detail={i}"}
                             for i, dl, r in self.pages[mois]]}]
        return {"statut": "frais", "contenu": "<script>window.calendarComponentStates[1] = {\ndays: " + json.dumps(jours) + ",\n}</script>", "note": ""}


def test_reprise_dans_le_plafond_et_arret_sur_refus(tmp_path):
    cfg = {"forexfactory": {**CONFIG["tableau_macro"]["forexfactory"], "plafond_requetes_par_jour": 6}}
    m = datetime(2026, 11, 26, 8, 22, tzinfo=timezone.utc)
    (tmp_path / "forexfactory_requetes.json").write_text(json.dumps({"date": "2026-11-26", "horodatages": ["2026-11-26T08:22:00+00:00"] * 5}))
    client = ClientSimule({"oct.2026": [(1, ts("2026-10-14T12:30+00:00"), "3.7%")], "sep.2026": []})
    b = ffh.reprendre(cfg, client, tmp_path, m)
    assert b["lus"] == ["oct.2026"] and "plafond" in b["echecs"]["sep.2026"]       # 6e requête du jour : la dernière
    assert len(client.urls) == 1
    assert ffh.lire(tmp_path)["series"]["USD|cpi y/y"]["2026-10-14"][0] == "3.7%"
    # le lendemain : un refus arrête la reprise sans insister
    m2 = m + timedelta(days=1)
    client2 = ClientSimule({})
    b2 = ffh.reprendre(cfg, client2, tmp_path, m2)
    assert b2["lus"] == [] and b2["echecs"]["sep.2026"] == "HTTP 403" and len(client2.urls) == 1
    assert ffh.etat(ffh.lire(tmp_path), m2.date())["n_lus"] == 1


def test_historique_repris_alimente_l_ecart_habituel():
    d = {"series": {"GBP|average earnings index 3m/y": {"2026-07-15": ["4.0%", "3.9%", 1], "2026-08-12": ["3.9%", "3.8%", 2],
                                                         "2026-09-16": ["3.8%", "3.9%", 3]}}}
    archive = ffh.fusionner_archives({"publications": {}}, d)
    z = surprises.z_publication("3.6%", "3.5%", "GBP", "Average Earnings Index 3m/y", surprises.ecarts_archives(archive), "2026-11-17")
    assert z["z"] is not None and "3 publications précédentes" in z["base"]


def test_memoriser_mois_garde_lien_type_et_heure_du_releve(tmp_path):
    e = ff(151570, "GBP", "GDP m/m", "2026-11-12T07:00+00:00", "high", "0.2%", "0.0%", "0.1%", "0.0%", "/calendar?day=nov12.2026#detail=151570")
    ag_mod.memoriser_mois([e], tmp_path, datetime(2026, 11, 12, 7, 20, tzinfo=timezone.utc))
    ag_mod.memoriser_mois([e], tmp_path, datetime(2026, 11, 12, 19, 15, tzinfo=timezone.utc))
    x = json.loads((tmp_path / "calendrier_mois.json").read_text(encoding="utf-8"))["evenements"][0]
    assert x["url"].endswith("#detail=151570") and x["ebase_id"] == 570
    assert x["reel_vu_le"] == "2026-11-12T07:20+00:00"        # première fois que le réel a été vu


# ------------------------------------------------------------------ A1.5 planning des lectures
def _agenda(evts):
    return {"jours": [{"date": "2026-11-26", "evenements": evts}]}


def _e(iso, impact="fort", dev="USD", nom="CPI y/y"):
    return {"iso_utc": iso, "impact": impact, "devise": dev, "evenement_en": nom, "heure_connue": True, "type": "Chiffre"}


def test_planning_sept_minutes_apres_les_publications_fortes():
    a = _agenda([_e("2026-11-26T13:30+00:00"), _e("2026-11-26T13:30+00:00", nom="Core CPI m/m"), _e("2026-11-26T13:35+00:00", nom="X"),
                 _e("2026-11-26T07:00+00:00", dev="GBP"), _e("2026-11-26T09:00+00:00", "moyen", "EUR"),
                 _e("2026-11-27T00:30+00:00", dev="AUD")])
    p = plan.planifier(a, date(2026, 11, 26))
    heures = [x["heure_utc"] for x in p["lectures"]]
    # V16.2 : 06:00 garantie ; 13:30 et 13:35 : une seule lecture, après la dernière
    assert heures == ["06:00", "07:07", "09:07", "13:42"]
    assert "forte" in p["lectures"][1]["motif"] and "moyenne" in p["lectures"][2]["motif"]


def test_planning_sous_le_plafond_avec_reserve_pour_l_historique():
    evts = [_e(f"2026-11-26T{h:02d}:00+00:00") for h in range(0, 22, 2)]   # 11 groupes forts
    evts += [_e("2026-11-26T14:00+00:00", nom=f"N{i}") for i in range(3)]    # le groupe de 14:00 compte 4 publications
    p = plan.planifier(_agenda(evts), date(2026, 11, 26), plafond=6, reserve=2)
    assert len(p["lectures"]) == 4 and "14:07" in [x["heure_utc"] for x in p["lectures"]]   # 06:00 garantie + 3 fortes
    assert len(plan.planifier(_agenda(evts), date(2026, 11, 26), plafond=6, reserve=0)["lectures"]) == 6
    assert [x["heure_utc"] for x in plan.planifier(_agenda([]), date(2026, 11, 28))["lectures"]] == ["06:00", "19:00"]


def test_plan_du_jour_fige_et_plan_de_demain(tmp_path):
    a1 = _agenda([_e("2026-11-26T13:30+00:00")])
    plan.mettre_a_jour(tmp_path, a1, datetime(2026, 11, 26, 8, 0, tzinfo=timezone.utc))
    a2 = {"jours": [{"date": "2026-11-26", "evenements": [_e("2026-11-26T15:00+00:00")]},
                    {"date": "2026-11-27", "evenements": [_e("2026-11-27T13:30+00:00")]}]}
    plan.mettre_a_jour(tmp_path, a2, datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc))
    assert plan.creneaux(tmp_path, date(2026, 11, 26)) == ["06:00", "13:37"]   # le plan du jour ne bouge plus
    assert plan.creneaux(tmp_path, date(2026, 11, 27)) == ["06:00", "13:37", "19:00"]
    assert plan.creneaux(tmp_path, date(2026, 11, 30)) is None


def test_collecte_suit_le_planning(tmp_path):
    plan.mettre_a_jour(tmp_path, _agenda([_e("2026-11-26T13:30+00:00")]), datetime(2026, 11, 26, 6, 0, tzinfo=timezone.utc))
    cfg = {"forexfactory": {**CONFIG["tableau_macro"]["forexfactory"]}}
    client = ClientSimule({"this": []})
    r = ffm.collecter(cfg, client, tmp_path, datetime(2026, 11, 26, 8, 15, tzinfo=timezone.utc))
    assert r["statut"] == "frais" and len(client.urls) == 1                     # V16.2 : la lecture de base de 06:00, rattrapée
    r = ffm.collecter(cfg, client, tmp_path, datetime(2026, 11, 26, 9, 15, tzinfo=timezone.utc))
    assert r["statut"] == "non_due" and len(client.urls) == 1
    r = ffm.collecter(cfg, client, tmp_path, datetime(2026, 11, 26, 13, 40, tzinfo=timezone.utc))
    assert r["statut"] == "frais" and r["declencheur"] == "planning" and len(client.urls) == 2
    r = ffm.collecter(cfg, client, tmp_path, datetime(2026, 11, 26, 14, 15, tzinfo=timezone.utc))
    assert r["statut"] == "non_due" and len(client.urls) == 2


def test_decider_lecture_planifiee():
    p = {"jours": {"2026-11-26": {"lectures": [{"heure_utc": "13:37", "motif": "2 publications fortes"}]}}}
    m = datetime(2026, 11, 26, 13, 37, 30, tzinfo=timezone.utc)
    ok, _ = decider_mode.lecture_due(p, {"date": "2026-11-26", "horodatages": []}, m)
    assert ok
    assert not decider_mode.lecture_due(p, {"date": "2026-11-26", "horodatages": ["2026-11-26T13:37:40+00:00"]},
                                        m + timedelta(minutes=1))[0]
    # V16.2 : la lecture garantie de 06:00 faite à 06:30, rien n'est dû à 13:07
    assert not decider_mode.lecture_due(p, {"date": "2026-11-26", "horodatages": ["2026-11-26T06:30:00+00:00"]},
                                        datetime(2026, 11, 26, 13, 7, tzinfo=timezone.utc))[0]
    assert not decider_mode.lecture_due(p, {"date": "2026-11-26", "horodatages": ["x"] * 6}, m)[0]
    assert decider_mode.decider("schedule", decider_mode.CRON_LECTURES, {}, True, [], None, m, (True, "due"))[0] == "lecture"
    assert decider_mode.decider("schedule", decider_mode.CRON_LECTURES, {}, False, [], None, m, (False, "rien"))[0] == "rien"
    wf = (RACINE / ".github" / "workflows" / "rapport.yml").read_text(encoding="utf-8")
    assert decider_mode.CRON_LECTURES in wf and 'lecture) ARGS="--lecture"' in wf


# ------------------------------------------------------------------ B1 thermomètre du moteur 2 (rejeu du 20/11)
def test_moteur_2_source_la_plus_recente_et_variation_par_date():
    serie = [("2026-11-12", 4.90), ("2026-11-13", 4.88), ("2026-11-16", 4.83), ("2026-11-17", 4.80), ("2026-11-18", 4.80),
             ("2026-11-19", 4.76), ("2026-11-20", 4.63)]
    registre = {"actuel": {"valeur": "4.80%", "valeur_num": 4.80, "date_pub": "2026-11-18", "source": "FRED (DGS2)"},
                "variation_pb": 7.0}
    m = ae.mesure_2ans(registre, serie)
    assert (m["valeur"], m["date"]) == (-25.0, "2026-11-20") and "série quotidienne" in m["source"]
    assert ae._dir(m["valeur"], ae.SEUILS["us2a_pb"], "haussier", "baissier") == "baissier"   # avant : +7 pb, neutre
    assert ae.mesure_2ans(registre, [])["valeur"] == 7.0                                       # repli : registre
    assert ae.variation_par_date([("2026-11-20", 4.63)]) is None


# ------------------------------------------------------------------ B2 indicateurs clés
def test_indicateurs_cles_releves_au_moins_a_moyen():
    assert indicateurs_cles.relever("CAD", "Retail Sales m/m", "faible")[0] == "moyen"
    assert indicateurs_cles.relever("CAD", "Core Retail Sales m/m", "faible")[0] == "moyen"
    assert indicateurs_cles.relever("JPY", "National Core CPI y/y", "faible")[0] == "moyen"
    imp, raison = indicateurs_cles.relever("GBP", "Public Sector Net Borrowing", "faible")
    assert imp == "moyen" and raison.startswith("importance relevée par le site")
    assert indicateurs_cles.relever("CAD", "Retail Sales m/m", "fort") == ("fort", None)          # jamais baissée
    assert indicateurs_cles.relever("USD", "Retail Sales m/m", "faible") == ("faible", None)
    assert dm.moteur_publication({"evenement_en": "Public Sector Net Borrowing"}) == 4
    d = _calculer([ff(1, "CAD", "Retail Sales m/m", "2026-11-23T13:30+00:00", "low", "0.8%", "0.7%")])
    e = d["jours"][0]["evenements"][0]
    assert e["impact"] == "moyen" and "importance relevée par le site" in e["impact_releve"]


# ------------------------------------------------------------------ B3 actualités : 20 titres réels
TITRES = [
    ("investingLive European news wrap: Risk sentiment remains negative", 1),
    ("investingLive Americas market news wrap: Chip stocks dump again", 1),
    ("investingLive Americas FX news wrap 24 Nov: It’s a Wrap. Chip stocks slide. Anthropic breaks IPO price. USD lower.", 1),
    ("Trump: Secured two new trade deals. 10 others coming very soon.", 8),
    ("Canada October CPI 3.1% vs +3.2% expected", 3),
    ("UK October CPI +3.6% vs +3.6% y/y expected", 3),
    ("US November Empire Manufacturing index +7.80 vs +18.00 expected", 3),
    ("Germany November ZEW economic sentiment 35.6 vs 28.8 expected", 3),
    ("Japan's economy unexpectedly contracts in third-quarter as elevated energy costs bite", 3),
    ("China house prices continue their downward spiral", 3),
    ("Fed’s Waller says central bank may need to ‘shock people’ with half-point rate hike", 2),
    ("The US Treasury auctions $16B of 20 year bonds at a high year at 5.459%", 4),
    ("Yemen's Houthis claim attacks on Saudi oil refinery as Trump warns of new strikes next year", 6),
    ("Yemen: list of designations and sanctions notices", 6),
    ("US Import prices 1.1% vs 0.7% est. Export prices 1.1% vs 0.5% est.", 8),
    ("Zscaler stock jumps 18% on report that CrowdStrike in talks to buy security vendor", None),
    ("SpaceX’s subsidiary Cursor tells lawmakers it's considering phasing out Chinese AI models", None),
    ("Nvidia shares fall over 3% in premarket after Huang comeback rally", None),
    ("Drugmaker Insmed shares rally 14% after Sanofi agrees to buy it in pharma’s biggest deal in three years", None),
    ("Dell earnings beat on AI strength, company authorizes $25 billion buyback", None),
]


@pytest.mark.parametrize("titre,attendu", TITRES)
def test_classement_de_20_titres_reels(titre, attendu):
    m = dm.reclasser({"titre": titre})
    assert (m[0] if m else None) == attendu, (titre, m)


def test_trump_trade_deals_seulement_moteur_8_et_crowdstrike_pas_une_attaque():
    assert dm.classer_titre("Trump: Secured two new trade deals. 10 others coming very soon.", "rates and the Fed") == [8]
    assert 6 not in dm.classer_titre("CrowdStrike results")


# ------------------------------------------------------------------ B4 mise en forme
def test_plus_bouge_et_faits_sans_titre_anglais():
    """V13.1 puis V15 : l'actualité est résumée par son sujet en français, avec la source et la date."""
    ch = {"numero": 8, "etat": {}, "indicateurs": [], "graphiques": [], "publications": [], "devises": [], "risques": {},
          "actualite": [{"titre": "European stocks fall as Trump turns back to tariffs. Italy leads the declines.", "source": "InvestingLive",
                         "date": "2026-11-24", "moteurs": [8]},
                        {"titre": "Brent crude slides as OPEC weighs output", "source": "CNBC", "date": "2026-11-23", "moteurs": [8]}]}
    texte = " ".join(f["texte"] for f in doc.rd.faits_chapitre(ch, {}, []))
    assert "European stocks fall" not in texte and "les droits de douane (InvestingLive)" in texte and "le pétrole (CNBC)" in texte
    assert doc.frtxt("0.7%") + " contre " + doc.frtxt("0.0%") == "0,7 % contre 0,0 %"


def test_salaires_britanniques_ont_un_ecart_habituel():
    arch = {"publications": {k: {"date": d, "devise": dv, "evenement_en": en, "reel": r, "consensus": c} for k, (d, dv, en, r, c) in enumerate([
        ("2026-10-02", "USD", "Average Hourly Earnings m/m", "0.1%", "0.3%"), ("2026-10-20", "GBP", "Average Earnings Index 3m/y", "3.7%", "3.8%"),
        ("2026-11-03", "NZD", "Labor Cost Index q/q", "0.4%", "0.5%"), ("2026-11-06", "JPY", "Average Cash Earnings y/y", "4.6%", "3.8%"),
        ("2026-11-18", "AUD", "Wage Price Index q/q", "1.1%", "1.0%")])}}
    z = surprises.z_publication("3.6%", "3.5%", "GBP", "Average Earnings Index 3m/y", surprises.ecarts_archives(arch), "2026-11-17")
    assert z["z"] is not None and "salaires, toutes devises" in z["base"]


# ------------------------------------------------------------------ B5 récits : le texte du matin n'est plus perdu
# ------------------------------------------------------------------ site
def test_site_agenda_v14():
    js = (RACINE / "docs" / "site" / "ecran_agenda.js").read_text(encoding="utf-8")
    for x in ("Afficher les publications passées", "Prochaine publication", "en attente", "Ouvrir sur ForexFactory ↗",
              "Voir dans le documentaire", "échantillon trop petit", "fxdesk-agenda-filtres", "localStorage", "e=(\\d+)", "FF ↗"):
        assert x in js, x
    assert "Source : ForexFactory, complétée par les instituts officiels." in js
    css = (RACINE / "docs" / "site" / "v14.css").read_text(encoding="utf-8")
    assert "JetBrains" not in css and "f-mono" not in css                 # DESIGN.md : jamais de monospace pour un chiffre
    sw = (RACINE / "docs" / "sw.js").read_text(encoding="utf-8")
    assert "site/v14.css" in sw
