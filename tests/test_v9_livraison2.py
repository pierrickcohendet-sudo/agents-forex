"""Lot V9, livraison 2 : probabilité de la Fed citée, actualités par thème, communiqués officiels (votes, projections,
vocabulaire, correction de l'archive), statut des intervenants du FOMC, jour de décision (précédent figé, réaction depuis
la bougie 30 min qui précède), copie Notion, archive de la Synthèse, fiche devise. Aucun appel réseau ni modèle."""
import json
from datetime import date
from pathlib import Path

from core import actualites, briefing, communiques_v9 as cv, fomc_2026, notion_blocks as nb, notion_synthese

RACINE = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ probabilité de la Fed
def art(titre, resume=None, jour="2026-11-09", source="investinglive"):
    return {"titre": titre, "resume": resume, "lien": f"https://exemple.org/{abs(hash(titre))}", "date": f"{jour}T07:30:00+00:00", "source": source}


def test_probabilite_fed_citee_et_verifiee_dans_le_texte():
    p = actualites.extraire_proba(art("Fed funds futures now price a 79% chance of a December hike after payrolls"))
    assert p["valeur"] == 79 and p["sens"] == "hausse" and "79%" in p["citation"] and p["source"] == "InvestingLive"
    assert actualites.extraire_proba(art("Stocks rally as 79% of S&P firms beat earnings")) is None          # pas la Fed
    assert actualites.extraire_proba(art("Fed's Waller says policy is in a good place")) is None             # pas de chiffre
    p2 = actualites.extraire_proba(art("Markets see the Fed holding rates", "Traders put the odds of a cut at 35% for December."))
    assert p2["valeur"] == 35 and p2["sens"] == "baisse"


def test_probabilite_fed_historique_une_semaine(tmp_path):
    arts = [art("Futures price a 71% chance of a Fed hike in December", jour="2026-11-02"),
            art("Fed funds futures price a 79% chance of a December hike", jour="2026-11-09")]
    lec = actualites.mettre_a_jour_proba(arts, tmp_path / "proba.json", date(2026, 11, 9))
    assert lec["valeur"] == 79 and lec["reference"]["valeur"] == 71 and lec["reference"]["date"] == "2026-11-02"
    vide = actualites.mettre_a_jour_proba([], tmp_path / "vide.json", date(2026, 11, 9))
    assert vide["valeur"] is None and "aucune probabilité" in vide["raison"]


def test_actualites_du_jour_par_theme():
    arts = [art(t, jour="2026-11-12") for t in [
        "Treasury yields edge higher before CPI", "Fed's Logan warns on inflation", "Fed minutes show debate",
        "Oil falls as Iran talks resume", "China exports beat forecasts", "Nvidia earnings lift Nasdaq futures",
        "Sports results of the day"]]
    l = actualites.du_jour(arts)
    assert 5 <= len(l) <= 8 and sum(1 for a in l if a["theme"] == "fed") == 2
    assert [a["theme"] for a in l] == sorted([a["theme"] for a in l], key=["fed", "energie", "asie", "actions"].index)
    assert all(a["lien"] and a["source"] for a in l) and not any("Sports" in a["titre"] for a in l)


# ------------------------------------------------------------------ communiqués officiels
BOE = ("At its meeting ending on 4 November 2026, the Monetary Policy Committee (MPC) voted by a majority of 8–1 to increase Bank Rate "
       "by 0.25 percentage points, to 4%. One member voted to increase Bank Rate by 0.5 percentage points, to 4.25%. CPI inflation "
       "is now expected to rise to around 5% by the middle of next year. Global energy prices have continued to rise.")
FED = ("The Committee decided to maintain the target range. Voting against the monetary policy action were Lisa D. Cook and "
       "Beth M. Hammack, who preferred to raise the target range for the federal funds rate by 1/4 percentage point at this meeting. "
       "For media inquiries, please email the Board.")


def test_votes_officiels():
    b = cv.votes(BOE, "boe")
    assert b["texte"] == "8 contre 1" and "0.5 percentage points" in b["minorite"] and b["citation"].startswith("At its meeting")
    f = cv.votes(FED, "fed")
    assert f["contre"] == 2 and f["pour"] == 10 and "Hammack" in f["minorite"]
    assert cv.votes("The Policy Board decided, by an 8-1 majority vote, to keep the rate.", "boj")["texte"] == "8 contre 1"
    assert cv.votes("text", None, "la BCE ne publie pas la répartition des votes")["raison"].startswith("la BCE")


def test_projections_et_vocabulaire():
    assert cv.projections(BOE) == ["CPI inflation is now expected to rise to around 5% by the middle of next year."]
    avant = "The Committee judged that inflation risks were balanced. Policy will remain accommodative for some time. Energy prices are high."
    apres = "The Committee judged that upside inflation risks have increased. Policy will need to remain restrictive. Energy prices are high."
    v = cv.vocabulaire(apres, avant)
    assert v["lecture"] == "vocabulaire plus restrictif" and v["n_ajouts"] >= 1 and v["n_retraits"] >= 1
    assert "restrictive" in " ".join(v["ajouts"]) and "accommodative" in " ".join(v["retraits"])
    assert cv.vocabulaire(apres, None)["raison"]
    assert cv.phrases("Voting against were Lisa D. Cook and Beth M. Hammack, who preferred a hike. Next sentence here please.")[0].endswith("hike.")


def test_vote_boe_du_05_11_corrige_dans_l_archive(tmp_path):
    (tmp_path / "data" / "cache").mkdir(parents=True)
    archive = {"publications": {"2026-11-05|GBP|mpc official bank rate votes": {
        "date": "2026-11-05", "devise": "GBP", "evenement_en": "MPC Official Bank Rate Votes", "reel": "9-0-0", "impact": "fort"}}}
    (tmp_path / "data" / "cache" / "publications_archive.json").write_text(json.dumps(archive), encoding="utf-8")
    analyse = {"GBP": {"disponible": True, "date": "2026-11-05", "votes": cv.votes(BOE, "boe"), "source": "communiqué officiel (BoE)",
                       "lien": "https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes/2026/november-2026"}}
    assert cv.corriger_archive(analyse, tmp_path) == 1
    p = json.loads((tmp_path / "data" / "cache" / "publications_archive.json").read_text(encoding="utf-8"))["publications"]
    e = next(iter(p.values()))
    assert e["reel"] == "9-0-0" and e["votes_officiels"]["texte"] == "8 contre 1"   # le publié ForexFactory reste, le vote officiel s'ajoute


def test_403_jamais_contourne(tmp_path):
    class Rep:
        status_code, content = 403, b""
    class Session:
        def get(self, url, headers=None, timeout=None):
            self.ua = headers
            return Rep()
    idx = cv.archiver(tmp_path, {"scraping": {"user_agent": "UA"}}, session=Session(), aujourd=date(2026, 11, 12))
    assert all("403" in b["erreur"] and "jamais contourné" in b["erreur"] for b in idx["banques"].values())
    a = cv.analyser(tmp_path)
    assert a["AUD"]["disponible"] is False and "403" in a["AUD"]["raison"]


# ------------------------------------------------------------------ discours : statut FOMC 2026
def test_statut_des_intervenants_du_fomc():
    assert fomc_2026.statut("Warsh")["statut"] == "président"
    assert fomc_2026.statut("Beth Hammack")["statut"] == "votant" and fomc_2026.statut("Logan")["libelle"] == "votant 2026"
    assert fomc_2026.statut("Goolsbee")["statut"] == "suppléant"
    assert fomc_2026.statut("Musalem")["statut"] == "non votant"
    assert fomc_2026.statut("Bailey", "GBP")["statut"] is None
    assert "federalreserve.gov" in fomc_2026.SOURCE and sum(1 for m in fomc_2026.MEMBRES.values() if m[2] != "suppléant") == 12


# ------------------------------------------------------------------ jour de décision (0.5, 0.6)
def test_precedent_fige_apres_la_publication():
    bq = {"devise": "GBP", "banque": "Banque d'Angleterre (BoE)", "court": "BoE", "heure": "13:00", "taux": "4.00%", "consensus": "4.00%",
          "badge": {"sens": "hausse"}}
    evenements = [{"devise": "GBP", "type": "Réunion BC", "evenement_en": "Official Bank Rate", "evenement": "Décision de la BoE",
                   "precedent": "3.75%", "consensus": "4.00%", "publie": "4.00%", "heure_paris": "13:00", "iso_utc": "2026-11-05T12:00+00:00"}]
    d = briefing.jour_de_decision(bq, evenements, {}, {}, {})
    assert d["lignes"][0]["precedent"] == "3.75%" and d["lignes"][0]["publie"] == "4.00%"


def test_reaction_depuis_la_bougie_qui_precede_la_publication():
    q = {"GBP/USD": {"prix": 1.3467, "heure_utc": "2026-11-05T12:20+00:00"}}
    matin = {"chandeliers": {"30min": {"bougies": [["2026-11-05 07:00:00", 1, 1, 1, 1.3300]]}}}
    r = briefing.reaction("GBP/USD", "2026-11-05T12:00+00:00", matin, q)
    assert r["variation_pct"] is None and "12:30" in r["raison"]                       # jamais depuis 08:00
    complet = {"chandeliers": {"30min": {"bougies": [["2026-11-05 07:00:00", 1, 1, 1, 1.3300], ["2026-11-05 11:30:00", 1, 1, 1, 1.3400]]}}}
    r = briefing.reaction("GBP/USD", "2026-11-05T12:00+00:00", complet, q)
    assert r["variation_pct"] == 0.5 and r["depuis"] == "2026-11-05 11:30:00" and r["depuis_paris"] == "12:30"


# ------------------------------------------------------------------ Notion, archive, fiche devise
def test_copie_notion_dans_les_limites():
    chemin = RACINE / "docs" / "data" / "synthese.json"
    s = json.loads(chemin.read_text(encoding="utf-8"))
    blocs = notion_synthese.blocs_synthese(s)
    titres = [b for b in blocs if b["type"] == "heading_2"]
    assert len(titres) == len(s["sections"]) and titres[0]["heading_2"]["rich_text"][0]["text"]["content"].startswith("1. ")
    for b in blocs:
        for cle in ("paragraph", "bulleted_list_item", "callout", "heading_2", "heading_3"):
            for f in (b.get(cle) or {}).get("rich_text") or []:
                assert len(f["text"]["content"]) <= 2000
        if b["type"] == "table":
            assert len(b["table"]["children"]) <= 100
    assert all(len(l) <= 100 for l in nb.lots(blocs))


def test_synthese_archivee_pour_l_onglet_archives():
    idx = json.loads((RACINE / "docs" / "data" / "synthese" / "index.json").read_text(encoding="utf-8"))
    assert idx["jours"] and (RACINE / "docs" / "data" / "synthese" / f"{idx['jours'][0]}.json").exists()
    js = (RACINE / "docs" / "site" / "archives.js").read_text(encoding="utf-8")
    assert "synthese=" in js and "ecranSyntheseV9" in js


def test_fiche_devise_codes_traduits_et_decimales_fixes():
    js = (RACINE / "docs" / "site" / "devises.js").read_text(encoding="utf-8")
    assert 'data_dependent: "dépendante des données"' in js and "traduireCode(d.biais_banque_centrale)" in js
    assert "fr2d(d.carry.taux_directeur)" in js and "String(d.carry.taux_directeur).replace" not in js
    css = (RACINE / "docs" / "site" / "v8.css").read_text(encoding="utf-8")
    assert ".fiche table.compact td.source-cellule{display:none}" in css
