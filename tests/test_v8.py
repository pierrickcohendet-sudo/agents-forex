"""Lot V8 : correctif V7.1 (votes, budget, BCE, Notion), MM en Python, Briefing, fraîcheur, alertes ntfy (mock, aucun
envoi réel), découpage de la Synthèse, identité visuelle, application installable. Aucun appel réseau ni modèle."""
import json
import os
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from core import agenda, alertes_telephone as at, briefing, fraicheur_blocs as fb, identite, paires, rapport_jour as rj
from core import tableau_macro as tmac
import orchestrateur

RACINE = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ 0. correctif V7.1
def test_votes_jamais_un_badge_de_taux():
    assert agenda.badge_decision("7-0-2", "3-0-6") is None                     # le 05/11 : « hausse attendue · 400 pb »
    assert agenda.texte_votes("7-0-2", "3-0-6") == "votes attendus 7-0-2, précédent 3-0-6"
    assert agenda.badge_decision("4.00%", "3.75%") == {"sens": "hausse", "texte": "hausse attendue", "pb": 25}
    assert agenda.est_taux("<1.25%") and not agenda.est_taux("7-0-2") and not agenda.est_taux("4.00")


def test_badges_de_l_agenda_marquent_les_votes():
    class Ag:   # agenda minimal : une réunion BC avec une répartition de votes
        lignes = {1: {"type": "Réunion BC", "devise": "GBP", "consensus": "7-0-2", "precedent": "3-0-6"}}
    agenda.badges(Ag(), {})
    e = Ag.lignes[1]
    assert e["badge"] is None and e["votes"] == "votes attendus 7-0-2, précédent 3-0-6"


def test_ligne_budget_au_dela_du_plafond_des_pannes():
    b = {"pannes_jour": 32, "plafond_pannes": 20, "pannes_avant_correctif": 32}
    assert orchestrateur.texte_pannes(b) == "32 (dont 32 avant le correctif)"
    assert orchestrateur.texte_pannes({"pannes_jour": 12, "plafond_pannes": 20}) == "12/20"
    assert "au-delà du plafond" in orchestrateur.texte_pannes({"pannes_jour": 25, "plafond_pannes": 20})


def test_bce_pas_de_fleche_entre_taux_de_nature_differente():
    cel = {"taux_directeur": {"EUR": {"Actuel": {"surprise": "="}}}}
    macro = {"taux_directeurs": {"EUR": {"taux": 2.5, "type": "dépôt", "source": "FRED (ECBDFR)", "date": "2026-11-03"}}}
    tmac.harmoniser_taux_reference(cel, [], {"cases": {"EUR|taux_directeur": {"actuel": {"valeur": "2.65%"}}}}, macro)
    a = cel["taux_directeur"]["EUR"]["Actuel"]
    assert a["surprise"] is None and "refinancement" in a["surprise_raison"]


def test_ligne_notion_du_recapitulatif():
    assert orchestrateur.ligne_notion("https://app.notion.com/p/FX-2026-11-04-quotidien-40e65bc6466181c897bec305e70d14f5") == \
        "Notion : copié (40e65bc6466181c897bec305e70d14f5)"
    assert orchestrateur.ligne_notion(None, "400 · validation_error : x") == "Notion : échec (400 · validation_error : x)"


# ------------------------------------------------------------------ C. moyennes mobiles en Python
def test_moyennes_mobiles_calculees_en_python():
    b = [[f"2026-10-{i + 1:02d}", 0, 0, 0, float(i + 1)] for i in range(25)]
    mm20 = paires.moyenne_mobile(b, 20)
    assert mm20[18][1] is None and mm20[19][1] == 10.5 and mm20[24][1] == 15.5
    assert [x[0] for x in mm20] == [x[0] for x in b]


# ------------------------------------------------------------------ B. Briefing
RJ = {"theme": {"titre": "Signaux mixtes", "conviction": "moyen"}, "date": "2026-11-05",
      "banques": [{"devise": "GBP", "banque": "Banque d'Angleterre (BoE)", "court": "BoE", "date": "2026-11-05", "heure": "13:00",
                   "taux": "3.75%", "consensus": "4.00%", "badge": {"sens": "hausse", "texte": "hausse attendue", "pb": 25}}],
      "essentiel": {"lignes": ["Thème : Signaux mixtes.", "Le mieux confirmé à ce jour : « Choc » (4 conditions sur 6 remplies).",
                               "Soutenue : GBP · Sous pression : NZD.", "Aucune publication.", "Paire à suivre en premier : EUR/USD (priorité élevée)."]},
      "interpretation": [["Hausse, ton restrictif", "La devise peut monter."], ["Hausse, ton accommodant", "Réaction limitée."]]}


def test_titre_du_briefing():
    assert briefing.titre_du_jour(RJ, "2026-11-05")[0] == "Journée Banque d'Angleterre : hausse attendue de 25 pb à 13:00"
    assert briefing.titre_du_jour(RJ, "2026-11-06")[0] == "Signaux mixtes"                           # pas de décision : le thème
    l = briefing.lignes_contexte(RJ, {"alignes": 2, "evaluables": 7})
    assert l[0] == ["Contexte", "Signaux mixtes : 2 engrenages sur 7 suivent le thème, conviction moyenne."]
    assert l[2][1].startswith("EUR/USD (priorité élevée). Devises : Soutenue")


def test_jour_de_decision_et_cas_de_lecture():
    evts = [{"devise": "GBP", "type": "Réunion BC", "evenement": "Votes du MPC (BoE)", "evenement_en": "MPC Votes", "consensus": "7-0-2",
             "precedent": "3-0-6", "heure_paris": "13:00", "iso_utc": "2026-11-05T12:00+00:00"},
            {"devise": "GBP", "type": "Réunion BC", "evenement": "Décision de la BoE", "evenement_en": "Bank Rate", "heure_paris": "13:00",
             "iso_utc": "2026-11-05T12:00+00:00", "publie": None}]
    d = briefing.jour_de_decision(RJ["banques"][0], evts, RJ, None, {})
    assert [l["libelle"] for l in d["lignes"]] == ["Taux directeur", "Votes du comité", "Discours du gouverneur"]
    assert d["lignes"][1]["attendu"] == "7-0-2" and d["paire"] == "GBP/USD"
    assert [c["titre"] for c in d["cas"]] == ["Si hausse avec ton restrictif", "Si hausse avec ton accommodant"]


def test_sessions_a_l_heure_de_paris_avec_les_changements_d_heure():
    hiver = {s["nom"]: (s["debut"], s["fin"]) for s in briefing.sessions_paris(date(2026, 11, 5))}
    assert hiver == {"Asie": (1.0, 10.0), "Londres": (9.0, 18.0), "New York": (14.0, 23.0)}
    ecart = {s["nom"]: s["debut"] for s in briefing.sessions_paris(date(2026, 3, 16))}   # USA à l'heure d'été, Europe pas encore
    assert ecart["New York"] == 13.0 and ecart["Londres"] == 9.0


def test_reaction_apres_publication():
    fiche = {"chandeliers": {"30min": {"bougies": [["2026-11-05 11:30:00", 1, 1, 1, 1.3400], ["2026-11-05 12:00:00", 1, 1, 1, 1.3500]]}}}
    r = briefing.reaction("GBP/USD", "2026-11-05T12:00+00:00", fiche, {"GBP/USD": {"prix": 1.3467, "heure_utc": "2026-11-05T12:15+00:00"}})
    assert r["variation_pct"] == 0.5 and r["depuis"] == "2026-11-05 11:30:00"
    avant = briefing.reaction("GBP/USD", "2026-11-05T12:00+00:00", fiche, {"GBP/USD": {"prix": 1.35, "heure_utc": "2026-11-05T11:45+00:00"}})
    assert avant["variation_pct"] is None and avant["raison"]                       # lot V9 : n/d avec la raison


# ------------------------------------------------------------------ G1. fraîcheur
def test_regle_de_fraicheur():
    """V8.1 : chaque série jugée sur sa dernière observation et sa fréquence normale, pas sur l'heure du fichier."""
    m = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)
    auj = m.date()
    assert fb.etat_serie("EUR/USD", "2026-11-05", 1, auj)["etat"] == "vert"
    assert fb.etat_serie("EUR/USD", "2026-11-02", 1, auj)["etat"] == "orange"        # 3 jours ouvrés > 1
    assert fb.etat_serie("EUR/USD", "2026-10-20", 1, auj)["etat"] == "rouge"         # plus de 5 jours ouvrés au-delà
    assert fb.etat_serie("FX", "2026-10-30", 1, datetime(2026, 11, 2).date())["etat"] == "vert"   # vendredi -> lundi
    assert fb.etat_serie("X", None, 1, auj)["etat"] == "rouge"
    # Cas du Brent : fichier régénéré à l'instant, mais dernière valeur au 27/10 -> bloc en retard, série nommée
    rapport = {"genere_le": m.isoformat(), "point_marche": {"lignes": [
        {"actif": "EUR/USD", "categorie": "fx", "serie_30j": [["2026-11-05", 1.12]], "source": "Twelve Data"},
        {"actif": "US 10 ans", "categorie": "taux", "serie_30j": [["2026-11-03", 4.95]], "source": "FRED (DGS10)"},
        {"actif": "Brent", "categorie": "petrole", "serie_30j": [["2026-10-27", 120.1]], "source": "FRED (DCOILBRENTEU)"}]}}
    b = fb.calculer({"rapport_jour": rapport}, {}, m)["point_marche"]
    assert b["etat"] == "orange"                                                      # 7 jours ouvrés > 5 (normal EIA)
    assert b["texte"].startswith("Brent : dernière valeur 27/10, 7 jours ouvrés de retard"), b["texte"]
    assert [s["etat"] for s in b["series"]] == ["vert", "vert", "orange"]
    # Brent à jour (03/11) : tout est vert, l'infobulle nomme la série la plus ancienne
    rapport["point_marche"]["lignes"][2]["serie_30j"] = [["2026-11-03", 107.0]]
    b = fb.calculer({"rapport_jour": rapport}, {}, m)["point_marche"]
    assert b["etat"] == "vert" and "3 séries dans leur fréquence normale" in b["texte"]
    # Fichier ancien mais séries à jour : vert (l'heure de génération ne compte pas) ; fichier absent : rouge
    rapport["genere_le"] = "2026-10-20T06:00:00+00:00"
    assert fb.calculer({"rapport_jour": rapport}, {}, m)["point_marche"]["etat"] == "vert"
    assert fb.calculer({}, {}, m)["point_marche"]["etat"] == "rouge"
    # Source sans série lisible : état de sources.json, repris tel quel
    src = {"cftc": {"nom": "CFTC", "derniere_donnee": "2026-10-20", "fraicheur": {"etat": "orange", "texte": "16 jours (normal : 10 au plus)"}}}
    e = fb.calculer({"dossiers": {"genere_le": m.isoformat()}, "rapport_jour": rapport}, src, m)["engrenages"]
    assert e["etat"] == "orange" and e["texte"].startswith("CFTC : dernière donnée 20/10, 16 jours")


# ------------------------------------------------------------------ H. alertes ntfy (aucun envoi réel)
def _donnees(tmp):
    d = Path(tmp) / "docs" / "data"; d.mkdir(parents=True)
    (d / "dossiers.json").write_text(json.dumps({"cockpit": {"franchis": [{"id": "thermometre-3", "engrenage": 3, "phrase": "surprise USD 30 j franchie"}]}}), encoding="utf-8")
    (d / "agenda.json").write_text(json.dumps({"jours": [{"evenements": [
        {"impact": "fort", "devise": "GBP", "evenement": "Décision de la BoE", "iso_utc": "2026-11-05T12:00+00:00", "heure_paris": "13:00", "consensus": "4.00%"},
        {"impact": "fort", "devise": "USD", "evenement": "IPC", "iso_utc": "2026-11-05T08:30+00:00", "publie": "3.9%", "consensus": "3.5%",
         "ecart": {"z": 2.6, "texte": "au-dessus (+2,6 σ)"}},
        {"impact": "moyen", "devise": "USD", "evenement": "PMI", "iso_utc": "2026-11-05T12:30+00:00"}]}]}), encoding="utf-8")


def test_alertes_dedoublonnees_et_canal_jamais_affiche():
    with tempfile.TemporaryDirectory() as tmp:
        _donnees(tmp)
        envois = []
        def post(url, data=None, timeout=None, headers=None):
            envois.append((url, data.decode("utf-8"), headers["Title"].decode("utf-8")))
            return mock.Mock(status_code=200)
        m = datetime(2026, 11, 5, 11, 15, tzinfo=timezone.utc)
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": "canal-secret-xyz"}), mock.patch.object(at.requests, "post", post):
            r1 = at.executer(tmp, {}, m)
            r2 = at.executer(tmp, {}, m)                        # même run horaire rejoué : rien de nouveau
        assert r1["envoyes"] == 3 and r2["envoyes"] == 0 and len(envois) == 3
        titres = [e[2] for e in envois]
        assert any("dans 45 min" in t for t in titres) and any("surprise de +2,6 σ" in t for t in titres) and "Seuils franchis" in titres
        assert all(e[0] == "https://ntfy.sh/canal-secret-xyz" for e in envois)
        assert "canal-secret-xyz" not in json.dumps([r1, r2])
        assert "canal-secret-xyz" not in (Path(tmp) / "data" / "cache" / "ntfy_envoyes.json").read_text(encoding="utf-8")


def test_alertes_echec_sans_rougir_le_run_et_sans_secret():
    with tempfile.TemporaryDirectory() as tmp:
        _donnees(tmp)
        m = datetime(2026, 11, 5, 11, 15, tzinfo=timezone.utc)
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": "canal-secret-xyz"}), \
                mock.patch.object(at.requests, "post", side_effect=at.requests.ConnectionError("https://ntfy.sh/canal-secret-xyz down")):
            r = at.executer(tmp, {}, m)
        assert r["envoyes"] == 0 and r["echecs"] == 3 and "canal-secret-xyz" not in r["ligne"] and "réseau" in r["ligne"]
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": ""}):
            assert "secret NTFY_TOPIC absent" in at.executer(tmp, {}, m)["ligne"]   # rien n'est mémorisé : renvoyé plus tard


# ------------------------------------------------------------------ G3. Synthèse rédigée
def test_decoupage_de_la_synthese():
    t = ("Le thème reste mixte avec 2 engrenages alignés sur 7. La Banque d'Angleterre décide à 13:00, une hausse de 25 pb est "
         "attendue. Le scénario de choc géopolitique remplit 4 conditions sur 6. Les rendements américains reculent de 9 pb. Le dollar reste stable.")
    blocs = rj.decouper_synthese(t)
    assert [b["titre"] for b in blocs] == ["L'essentiel", "Banques centrales", "Scénarios", "Marchés"]
    assert blocs[3]["texte"] == "Les rendements américains reculent de 9 pb. Le dollar reste stable."
    assert " ".join(b["texte"] for b in blocs) == t                                   # aucun mot perdu ni ajouté
    assert rj.decouper_synthese(None) == []


# ------------------------------------------------------------------ G2, E. identité et application installable
def test_icones_png_et_apercu():
    png = identite.icone(192)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(png[16:20], "big") == 192
    og = identite.apercu_partage()
    assert (int.from_bytes(og[16:20], "big"), int.from_bytes(og[20:24], "big")) == (1200, 630)


def test_manifeste_et_service_worker():
    m = json.loads((RACINE / "docs" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["name"] == "Trading baby" and m["display"] == "standalone"
    assert {"192x192", "512x512"} <= {i["sizes"] for i in m["icons"]}
    for i in m["icons"]:
        assert (RACINE / "docs" / i["src"]).exists(), i["src"]
    sw = (RACINE / "docs" / "sw.js").read_text(encoding="utf-8")
    html = (RACINE / "docs" / "index.html").read_text(encoding="utf-8")
    version = html.split('name="fxdesk-version" content="')[1].split('"')[0]
    assert f'const VERSION = "{version}";' in sw                                      # cache vidé à chaque version
    assert 'rel="manifest"' in html and 'register("sw.js")' in html and "og-image.png" in html
    assert 'data-t="briefing"' in html and 'data-t="paire"' in html and 'id="searchBtn"' in html


def test_json_publies_valides():
    for f in sorted((RACINE / "docs" / "data").glob("*.json")):
        json.loads(f.read_text(encoding="utf-8"))


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
def test_journal_v3_et_recherche_node():
    r = subprocess.run(["node", str(RACINE / "tests" / "journal_v3.test.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=50)
    assert r.returncode == 0, r.stderr + r.stdout
