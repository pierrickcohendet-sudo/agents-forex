"""Rapport du jour : mécanismes, scénarios, watchlist, fenêtres, contrôle des textes, communiqués, Notion. Sans réseau, sans LLM réel."""
import json
from datetime import date
from pathlib import Path
from unittest import mock

import yaml

from agents import agent_rapport as ar
from core import communiques, rapport_jour as rj

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def V(**kw):
    return {k: {"valeur": v, "unite": "pb", "date": "2026-10-28", "source": "test"} for k, v in kw.items()}


def test_variation_pb_pourcent_points():
    pts = [("2026-10-2%d" % i, v) for i, v in enumerate([4.80, 4.78, 4.75, 4.74, 4.72, 4.70])]
    assert rj.variation(pts, 5, "pb") == -10.0 and rj.variation(pts, 1, "pb") == -2.0
    assert rj.variation([("a", 100.0), ("b", 102.0)], 1, "%") == 2.0 and rj.variation(pts, 9, "%") is None


def test_regles_des_mecanismes_et_chiffres_declencheurs():
    m = {x["id"]: x for x in rj.mecanismes(CONFIG, V(us10a_5j=-8, nasdaq_5j=-1.5, ecart_2a_us_de_5j=-6, brent_5j=1))}
    assert m["fuite_qualite"]["etat"] == "detecte" and "US 10 ans sur 5 séances −8,0 pb" in m["fuite_qualite"]["conditions"][0]["chiffre"]
    assert m["soutien_dollar_diminue"]["etat"] == "detecte" and m["inflation_attenuee"]["etat"] == "absent"
    assert m["tension_credit"]["etat"] == "nd"                                     # variable absente : non évaluable


def test_statut_des_scenarios_sans_probabilite_et_invalidation():
    vars_ = V(us2a_5j=-9, us10a_5j=-13, surprise_30j_usd=-0.2, brent_5j=-1, nasdaq_5j=-0.5, vix=17, vix_5j=0.2)
    s = rj.scenarios(CONFIG, vars_, {"2026-10-27": {"ralentissement": [3, 5]}}, "2026-10-28")
    r = {x["id"]: x for x in s["liste"]}
    assert r["ralentissement"]["statut"] == "5 conditions sur 5 remplies" and r["ralentissement"]["mieux_confirme"]
    assert "le mieux confirmé à ce jour" in s["texte_mieux_confirme"].lower() and "%" not in s["texte_mieux_confirme"]
    assert s["historique"]["jours"] == ["2026-10-27", "2026-10-28"]
    inv = rj.scenarios(CONFIG, V(us2a_5j=20, us10a_5j=-1), None, None)
    assert {x["id"]: x for x in inv["liste"]}["ralentissement"]["invalide"]


def test_score_watchlist_decomposition_et_diversite():
    fiches = {}
    for p in ("USD/JPY", "EUR/JPY", "GBP/JPY", "AUD/JPY", "EUR/USD", "GBP/USD", "AUD/NZD", "USD/CAD"):
        fiches[p] = {"macro": {"decomposition": {"solde": 2}}, "technique": {"volatilite_30j": 8 if "JPY" in p else 5}}
    agenda = {"jours": [{"date": "2026-10-29", "evenements": [
        {"date_paris": "2026-10-30", "devise": "JPY", "impact": "fort", "type": "Réunion BC", "evenement": "Décision de la BoJ", "iso_utc": "x"}]}]}
    scen = {"liste": [{"mieux_confirme": False, "consequences": {}}]}
    w = rj.watchlist({"fiches": fiches}, agenda, {}, scen, CONFIG, date(2026, 10, 29))
    top = w["top"]
    assert [l["paire"] for l in top].count("USD/JPY") == 1 and sum("JPY" in l["paire"] for l in top) <= rj.MAX_PAR_DEVISE
    assert set(top[0]["composantes"]) == {"evenements", "differentiel", "solde", "volatilite"} and top[0]["libelle"]
    assert w["mention"] == "Classe les opportunités à analyser, pas des ordres." and top[0]["risque"]


def test_fenetres_de_la_semaine_et_avertissements():
    agenda = {"jours": [
        {"date": "2026-10-29", "evenements": [
            {"date_paris": "2026-10-29", "heure_paris": "13:30", "devise": "USD", "impact": "fort", "type": "Chiffre", "engrenage": 3, "evenement": "PIB"},
            {"date_paris": "2026-10-29", "heure_paris": "13:30", "devise": "USD", "impact": "fort", "type": "Chiffre", "engrenage": 3, "evenement": "PCE"},
            {"date_paris": "2026-10-29", "heure_paris": "14:15", "devise": "EUR", "impact": "fort", "type": "Réunion BC", "engrenage": 2, "evenement": "BCE"}],
         "discrets": []},
        {"date": "2026-10-30", "evenements": [], "discrets": [{"date_paris": "2026-10-30", "texte": "Jour férié", "devises": ["JPY"]}]}]}
    c = rj.calendrier_commente(agenda, date(2026, 10, 29))
    assert c["jours"][0]["titre"] == "Journée critique" and "USD" in c["jours"][0]["lecture"]
    assert c["fenetres"][0]["heure"] == "13:00" and c["fenetres"][0]["score"] == 6 and c["fenetres"][1]["score"] == 4.5
    assert any("Fin de mois" in a for a in c["avertissements"]) and any("férié" in a for a in c["avertissements"])


class Faux:
    def __init__(self, reponses):
        self.reponses, self.prompts = list(reponses), []

    def appeler_llm(self, prompt, systeme=None):
        self.prompts.append(prompt)
        return json.dumps(self.reponses.pop(0))


def _rapport_min():
    r = rj.calculer(RACINE, CONFIG)
    return r


def test_controle_des_textes_chiffre_absent_ordre_et_citation():
    r = _rapport_min()
    paire = r["watchlist"]["top"][0]["paire"]
    actuel = "The Committee decided to maintain the target range. Inflation remains somewhat elevated and the Committee is attentive."
    faux = Faux([{"synthese": "Les catalyseurs dominent la semaine. Le dollar montera de 7,77 % d'ici vendredi.",
                  "bilan": "Achetez le yen maintenant.", "conclusion": "Prudence avant les décisions.", "lecture_marche": "Pas de signal net."},
                 {"watchlist": {paire: {"haussier": "Si les conditions haussières se confirment.", "baissier": "Vendez la paire."}},
                  "communiques": {"USD": {"ton": "plus restrictif", "citations": ["Inflation remains somewhat elevated"]},
                                  "EUR": {"ton": "plus restrictif", "citations": ["phrase inventée qui n'est pas dans le texte"]}},
                  "plan": "Avant la séance, relire les seuils."}])
    with mock.patch.object(ar, "definir_etiquette"), mock.patch.object(ar, "attribution_modele", return_value={"libelle": "faux"}):
        t = ar.rediger(r, faux, {"USD": (actuel, "previous text"), "EUR": ("autre texte officiel assez long pour test", "x")})
    assert len(faux.prompts) == 2                                                 # 2 appels groupés au plus
    assert t["synthese"] == "Les catalyseurs dominent la semaine." and "bilan" not in t     # chiffre absent, ordre : retirés
    assert t["watchlist"][paire] == {"haussier": "Si les conditions haussières se confirment."}          # « Vendez » : retiré
    assert t["communiques"] == {"USD": {"ton": "plus restrictif", "citations": ["Inflation remains somewhat elevated"]}}
    assert any("EUR" in c and "aucune citation" in c for c in t["controles"]) and t["statut"] == "ok"


def test_sans_modele_repli_python_et_textes_appliques():
    r = _rapport_min()
    t = ar.rediger(r, None)
    assert t["statut"] == "indisponible" and t["raison"]
    rj.appliquer_textes(r, {"synthese": "Texte validé.", "communiques": {}})
    assert r["synthese"]["texte"] == "Texte validé." and r["synthese"]["phrase_python"] and r["conclusion"]["phrase_python"]
    assert r["version"] in ("complète", "courte") and r["sections"]


def test_communique_extraction_et_detection_sans_reseau(tmp_path):
    html = "<html><nav>menu</nav><main><p>The Federal Open Market Committee decided to maintain the target range at 3-3/4 to 4 percent.</p>" \
           "<p>court</p></main></html>"
    assert communiques.extraire_texte(html).startswith("The Federal Open Market Committee decided")
    agenda = {"jours": [{"evenements": [{"type": "Réunion BC", "devise": "USD", "date_paris": "2026-10-28"},
                                        {"type": "Réunion BC", "devise": "JPY", "date_paris": "2026-10-28"}]}]}
    assert communiques.decisions_proches(agenda, date(2026, 10, 29)) == {"USD", "JPY"}
    flux = b"""<rss><channel><item><title>Federal Reserve issues FOMC statement</title>
<link>https://www.federalreserve.gov/x.htm</link><pubDate>Wed, 28 Oct 2026 18:00:00 GMT</pubDate></item></channel></rss>"""
    s = mock.Mock()
    s.get.side_effect = lambda url, **k: mock.Mock(content=flux, text=html, raise_for_status=mock.Mock())
    idx = communiques.archiver(tmp_path, CONFIG, agenda, date(2026, 10, 29), session=s)
    assert idx["par_devise"]["USD"]["date"] == "2026-10-28" and (tmp_path / "data/communiques/USD_2026-10-28.json").exists()
    assert "pas de flux officiel" in idx["par_devise"]["JPY"]["raison"]
    communiques.archiver(tmp_path, CONFIG, agenda, date(2026, 10, 29), session=s)
    assert s.get.call_count == 3                                                  # flux, page, flux : pas de seconde lecture


def test_notion_ecrit_puis_met_l_ancienne_version_a_la_corbeille():
    from agents import agent_redacteur as red
    r = _rapport_min()
    client = mock.Mock()
    client.data_sources.query.return_value = {"results": [{"id": "ancienne"}]}
    client.pages.create.return_value = {"id": "nouvelle", "url": "https://notion.so/nouvelle"}
    with mock.patch.object(red, "_obtenir_database", return_value="db"), mock.patch.object(red, "_obtenir_data_source", return_value="ds"):
        url = red.publier_rapport_jour(CONFIG, r, client=client)
    assert url == "https://notion.so/nouvelle"
    ordre = [c[0] for c in client.mock_calls if c[0] in ("pages.create", "blocks.children.append", "pages.update")]
    assert ordre[0] == "pages.create" and ordre[-1] == "pages.update"           # écriture d'abord, corbeille ensuite
    assert client.pages.update.call_args.kwargs == {"in_trash": True}


def test_site_page_rapport_par_defaut_le_matin_et_journal():
    app = (RACINE / "docs/site/app.js").read_text(encoding="utf-8")
    assert 'rapport: { titre: "Rapport", module: "./rapport.js"' in app and "h < 13" in app
    assert CONFIG["rapport"]["heure_bascule_accueil"] == "13:00"
    js = (RACINE / "docs/site/rapport.js").read_text(encoding="utf-8")
    for cle in rj.SECTIONS_COMPLETES + rj.SECTIONS_COURTES:
        assert f"  {cle}(r)" in js, cle
    assert "beforeprint" in js and "window.print()" in js and "Lecture :" in js
    jn = (RACINE / "docs/site/journal.js").read_text(encoding="utf-8")
    assert "Déclencheur M30" in jn and "checklist:" in jn and "blocNiveaux" in jn
