"""Lot V9, livraison 1 : archive des publications, BLS, Trésor, Brent, mécanisme cross-asset, classement, contrôle des
textes, fournisseur de secours (simulé), secours Python, gabarits « lire le chiffre », rejeu du 09/11.
Aucun appel réel à un modèle ni au réseau (quota 0)."""
import gzip
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents import agent_synthese_v9 as agent
from core import bls, controle_texte as ct, publications_archive as pa, synthese_v9 as sv, tresor

DONNEES = Path(__file__).parent / "donnees"
REJEU = DONNEES / "rejeu_2026-11-09"
PHRASE_CREUSE = "Le dollar conserve un biais haussier modéré guidé par l'addition des signaux techniques et économiques."


@pytest.fixture(autouse=True)
def sans_cle_secours(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)   # jamais d'appel réel au secours


def _gz(chemin: Path):
    return json.loads(gzip.decompress(chemin.read_bytes()).decode("utf-8"))


def rejeu(tmp_path: Path) -> tuple[Path, Path]:
    """Dossiers docs/ et cache/ du 09/11 (données figées) + BLS simulé à partir d'une réponse réelle enregistrée."""
    docs, cache = tmp_path / "docs", tmp_path / "cache"
    for src in REJEU.rglob("*.gz"):
        rel = src.relative_to(REJEU)
        dst = tmp_path / rel.with_suffix("")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(_gz(src), ensure_ascii=False), encoding="utf-8")
    archive = pa.charger(cache / "publications_archive.json")
    rep = json.loads((DONNEES / "bls_reponse_2026-11.json").read_text(encoding="utf-8"))
    faits = bls.calculer(bls.series_depuis_reponse(rep), archive)
    (cache / "bls_emploi.json").write_text(json.dumps({"faits": faits}, ensure_ascii=False), encoding="utf-8")
    return docs, cache


MATIN_0911 = datetime(2026, 11, 9, 8, 30, tzinfo=timezone.utc)


# ------------------------------------------------------------------ archive des publications
def test_archive_lundi_contient_le_nfp_du_vendredi(tmp_path):
    docs, cache = rejeu(tmp_path)
    jour, pubs = pa.derniere_seance(pa.charger(cache / "publications_archive.json"), date(2026, 11, 9))
    assert jour == "2026-11-06"
    nfp = pubs[0]
    assert nfp["evenement_en"] == "Non-Farm Employment Change" and nfp["reel"] == "165K" and nfp["consensus"] == "65K"
    assert nfp["heure_paris"] == "14:30" and nfp["source"]
    assert pa.derniere_seance_ouvree(date(2026, 11, 9)) == date(2026, 11, 6)


def test_archive_garde_le_premier_publie_et_le_vendredi_quand_l_agenda_repart_du_lundi(tmp_path):
    vendredi = {"jours": [{"evenements": [{"date_paris": "2026-11-06", "heure_paris": "14:30", "devise": "USD", "evenement": "NFP",
                                            "evenement_en": "Non-Farm Employment Change", "type": "Chiffre", "impact": "fort",
                                            "publie": "165K", "consensus": "65K", "precedent": "29K"}]}]}
    a = pa.fusionner({}, pa.depuis_agenda(vendredi), date(2026, 11, 6))
    lundi = pa.fusionner(a, pa.depuis_agenda({"jours": []}), date(2026, 11, 9))   # flux hebdomadaire vide le lundi
    assert [p["reel"] for p in pa.publications_du(lundi, "2026-11-06")] == ["165K"]
    revise = pa.fusionner(lundi, [{**pa.depuis_agenda(vendredi)[0], "reel": "170K"}], date(2026, 11, 9))
    p = pa.publications_du(revise, "2026-11-06")[0]
    assert p["reel"] == "165K" and p["reel_revise"] == "170K"


def test_publie_hier_le_lundi_vient_de_l_archive(tmp_path, monkeypatch):
    docs, cache = rejeu(tmp_path)
    from core import rapport_jour
    monkeypatch.setattr(pa, "charger", lambda chemin=None: json.loads((cache / "publications_archive.json").read_text(encoding="utf-8")))
    v = rapport_jour.publications_veille({"jours": []}, None, None, date(2026, 11, 9))
    assert v["jour"] == "2026-11-06"
    assert any("NFP" in l["texte"] and "165K" in l["texte"] and "65K" in l["texte"] for l in v["publications"])


# ------------------------------------------------------------------ BLS, Trésor, Brent
def test_bls_revisions_et_detail():
    rep = json.loads((DONNEES / "bls_reponse_2026-11.json").read_text(encoding="utf-8"))
    archive = {"publications": {"x": {"devise": "USD", "evenement_en": "Non-Farm Employment Change", "date": "2026-10-02", "reel": "29K"},
                                "y": {"devise": "USD", "evenement_en": "Non-Farm Employment Change", "date": "2026-11-06", "reel": "165K",
                                      "consensus": "65K", "heure_paris": "14:30"}}}
    f = bls.calculer(bls.series_depuis_reponse(rep), archive)
    assert f["mois"] == "2026-10" and f["creations_k"] == 165 and f["consensus_k"] == 65
    sept = f["revisions"][0]
    assert sept["mois"] == "2026-09" and sept["premier_k"] == 29 and sept["revise_k"] == 60 and sept["ecart_k"] == 31
    assert f["chomage"]["valeur"] == 4.1 and f["u6"]["valeur"] == 7.9 and f["salaire_mm_pct"] == 0.4
    assert f["revisions"][1]["raison"]                                    # août : premier chiffre non archivé -> raison


def test_bls_le_jour_du_nfp_deuxieme_collecte_apres_la_publication():
    cache = {"collecte_le": "2026-11-06T08:20+00:00"}
    assert not bls.doit_collecter(cache, datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc))
    assert bls.doit_collecter(cache, datetime(2026, 11, 6, 13, 40, tzinfo=timezone.utc))
    assert not bls.doit_collecter({"collecte_le": "2026-11-06T13:40+00:00"}, datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc))


def test_tresor_courbe_quotidienne_complete_fred():
    csv = ('Date,"1 Mo","2 Yr","10 Yr","30 Yr"\n11/10/2026,4.05,4.73,4.98,5.35\n11/09/2026,4.04,4.56,4.88,5.26\n')
    pts = tresor.lire_csv(csv)
    assert pts["USD_2a"] == [["2026-11-09", 4.56], ["2026-11-10", 4.73]] and pts["USD_30a"][-1] == ["2026-11-10", 5.35]
    fusion = tresor.fusionner([("2026-11-06", 4.51), ("2026-11-09", 4.55)], pts["USD_2a"])
    assert fusion == [("2026-11-06", 4.51), ("2026-11-09", 4.56), ("2026-11-10", 4.73)]   # le Trésor prime, FRED complète


def test_brent_relais_quotidien_et_alerte_de_retard():
    e = SimpleNamespace(aujourd=date(2026, 11, 12),
                        serie=lambda c: {"brent": [("2026-11-02", 107.39), ("2026-11-03", 107.03)],
                                         "brent_bno": [("2026-11-03", 62.0), ("2026-11-04", 60.4), ("2026-11-11", 58.75)]}.get(c, []),
                        source=lambda c: c)
    b = sv.brent_quotidien(e)
    assert b["officiel"]["date"] == "2026-11-03" and b["retard_jours_ouvres"] == 7
    assert b["estimation"]["date"] == "2026-11-11" and b["estimation"]["valeur"] == round(107.03 * 58.75 / 62.0, 2)
    assert b["alerte"] and "7 jours ouvrés" in b["alerte"]


# ------------------------------------------------------------------ mécanisme, classement, gabarits
def _meca(d1, d5, a1, a5, v1, v5, t1, t5):
    return sv.mecanisme_cross_asset(None, {"dollar": (d1, d5, "%", "DXY"), "actions": (a1, a5, "%", "SPY"),
                                           "vix": (v1, v5, " pt", "VIX"), "taux": (t1, t5, " pb", "US 2 ans")})


def test_mecanisme_cross_asset():
    actifs = lambda m: [x["id"] for x in m["mecanismes"] if x["actif"]]   # noqa: E731
    assert actifs(_meca(0.2, 0.9, -0.8, -2.0, 1.2, 3.0, 0, 0)) == ["refuge"]
    assert actifs(_meca(0.0, 0.6, 0.0, 0.1, 0, 0, 2, 8.0)) == ["monetaire"]
    assert actifs(_meca(0.0, 0.6, 0.0, 1.2, 0, -0.2, 0, 0)) == ["rendement"]
    assert set(actifs(_meca(0.0, 0.6, 0.0, 1.2, 0, 0, 0, 5.0))) == {"monetaire", "rendement"}
    m = _meca(-0.1, -0.5, 0, 1, 0, 0, 0, 0)
    assert actifs(m) == [] and "Aucun des trois mécanismes" in m["phrase"]


def test_classement_des_devises_calcule_en_python():
    profil = {"date": "2026-11-09", "devises": [
        {"devise": d, "etat": {"valeur": {"USD": "Soutenue", "NZD": "Sous pression"}.get(d, "Sans direction")},
         "macro": {"surprise_30j": {"indice": {"USD": 1.5, "NZD": -1.5}.get(d, 0)}}} for d in sv.DEVISES]}
    force = {"devises": [{"devise": d, "j5": {"USD": 1.2, "NZD": -1.0}.get(d, 0.0), "date": "2026-11-09"} for d in sv.DEVISES]}
    e = SimpleNamespace(force=force, profil=profil, taux={}, aujourd=date(2026, 11, 9))
    c = sv.classement(e)
    rangs = [l["devise"] for l in c["devises"]]
    assert rangs[0] == "USD" and rangs[-1] == "NZD" and [l["rang"] for l in c["devises"]] == list(range(1, 10))
    assert c["devises"][0]["score"] == 3.0 and c["devises"][0]["biais"] == "Fort"
    assert c["devises"][-1]["biais"] == "Faible" and "profil" in c["devises"][-1]["moteur"]
    assert next(l for l in c["devises"] if l["devise"] == "EUR")["biais"] == "Neutre"


@pytest.mark.parametrize("nom, consensus, famille", [("Core CPI m/m", "0.2%", "inflation"), ("Non-Farm Employment Change", "65K", "emploi"),
                                                      ("GDP m/m", "0.0%", "pib"), ("ISM Services PMI", "54.8", "pmi"),
                                                      ("Official Bank Rate", "4.00%", "decision")])
def test_gabarits_lire_le_chiffre(nom, consensus, famille):
    g = sv.gabarit(nom, consensus)
    assert g["famille"] == famille and len(g["cas"]) == 4
    assert sv.valeur_fr(consensus) in g["cas"][0]["si"] and {c["classe"] for c in g["cas"]} <= {"up", "dn", "", "warn"}


# ------------------------------------------------------------------ contrôle des textes
def test_nombre_invente_rejete():
    ok = ct.nombres_autorises({"brent": {"valeur": 107.03, "date": "2026-11-03"}})
    assert ct.verifier("Le Brent officiel vaut 107,03 $ au 03/11.", ok) == []
    r = ct.verifier("Le Brent recule vers 98,35 $ le 09/11.", ok)
    assert any("98,35" in x for x in r)


def test_phrase_sans_chiffre_ni_cause_rejetee():
    r = ct.verifier(PHRASE_CREUSE, ct.nombres_autorises({"x": 1.26}))
    assert any("formule creuse" in x for x in r) and any("sans fait chiffré" in x for x in r)
    assert ct.verifier("Le contexte reste incertain pour le dollar.", set()) != []
    assert ct.verifier("Il faut acheter l'EUR/USD à 1,10.", ct.nombres_autorises({"c": 1.10})) != []


# ------------------------------------------------------------------ rédaction : modèle, secours, Python
class Modele:
    def __init__(self, reponse=None, erreur=None):
        self.reponse, self.erreur, self.appels = reponse, erreur, 0

    def appeler_llm(self, prompt, systeme=None):
        self.appels += 1
        if self.erreur:
            raise self.erreur
        import re
        ids = re.findall(r'"(s\d+)": \["paragraphe', prompt)
        return json.dumps({i: self.reponse(i) for i in ids}, ensure_ascii=False)


def test_secours_python_jamais_null_et_chaque_phrase_datee(tmp_path):
    docs, cache = rejeu(tmp_path)
    s = sv.calculer(docs, cache, date(2026, 11, 9), MATIN_0911)
    assert len(s["sections"]) == 13 and not s["erreurs"]
    for sec in s["sections"]:
        assert s["textes"][sec["id"]] and all(p.strip() for p in s["textes"][sec["id"]]), sec["id"]
        assert s["redaction"][sec["id"]]["libelle"] == "rédaction automatique"
    assert ct.verifier_textes(s["textes"], s["faits"]) == {}
    assert PHRASE_CREUSE not in json.dumps(s["textes"], ensure_ascii=False)


def test_fournisseur_de_secours_simule_quand_le_principal_est_en_panne(tmp_path):
    import requests
    docs, cache = rejeu(tmp_path)
    s = sv.calculer(docs, cache, date(2026, 11, 9), MATIN_0911)
    rep = requests.Response(); rep.status_code = 503
    principal = Modele(erreur=requests.exceptions.HTTPError("503 Service Unavailable", response=rep))
    p = s["faits"]["s3"]["principale"]
    valide = lambda sid: [f"Séance du {sv.ddm(s['faits']['s3']['jour'])} : {p['evenement']} à {p['reel']} contre {p['consensus']} attendu."]  # noqa: E731
    secours = agent.Secours({"quota_jour": 2}, tmp_path, fournisseur=Modele(reponse=valide))
    j = agent.rediger(s, principal, secours)
    assert principal.appels == 4 and secours.f.appels == 2                      # budget séparé : 2 appels au plus
    assert j["groupes"]["1"]["par"].startswith("secours") and "503" in j["groupes"]["1"]["erreur"]
    assert s["redaction"]["s3"]["par"] == "modele" and "secours" in s["redaction"]["s3"]["libelle"]
    assert s["redaction"]["s11"]["par"] == "automatique"                        # groupes 3 et 4 : budget du secours atteint
    invente = Modele(reponse=lambda sid: ["Le Brent recule vers 98,35 $ le 09/11."])
    s2 = sv.calculer(docs, cache, date(2026, 11, 9), MATIN_0911)
    j2 = agent.rediger(s2, invente, None)
    assert all(s2["redaction"][sid]["par"] == "automatique" for sid in s2["redaction"])
    assert any("98,35" in r for r in j2["groupes"]["2"]["rejetees"]["s5"])


def test_rejeu_du_09_11(tmp_path):
    """Section 3 : NFP +165K contre +65K attendu, chômage 4,1 %, U-6 7,9 % ; sections 1 à 13 toutes remplies."""
    docs, cache = rejeu(tmp_path)
    s = agent.executer(tmp_path, {"publication_web": {"dossier_docs": "docs"}}, None, MATIN_0911, docs=docs, cache=cache,
                       secours=agent.Secours({"actif": False}, tmp_path))
    assert s and s["date"] == "2026-11-09"
    f3 = s["faits"]["s3"]
    assert f3["jour"] == "2026-11-06" and f3["principale"]["reel"] == "165 K" and f3["principale"]["consensus"] == "65 K"
    em = f3["emploi"]
    assert em["creations"]["valeur"] == 165000 and em["consensus"]["valeur"] == 65000
    assert em["chomage"]["texte"] == "4,1 %" and em["u6"]["texte"] == "7,9 %"
    assert any("révisé à +60" in r["texte"] for r in em["revisions"])
    texte3 = " ".join(s["textes"]["s3"])
    assert "165 K" in texte3 and "65 K" in texte3 and "4,1 %" in texte3 and "7,9 %" in texte3
    assert f3["chaine"][0]["texte"].startswith("NFP 165 K contre 65 K")
    assert [sec["id"] for sec in s["sections"]] == [f"s{i}" for i in range(1, 14)]
    for sid in s["textes"]:
        assert s["textes"][sid] and all(p for p in s["textes"][sid])
    assert (docs / "synthese.json").exists() and (tmp_path / "data" / "archives" / "synthese" / "2026-11-09.json").exists()
    assert s["faits"]["s7"]["lundi"] == "2026-11-09" and len(s["faits"]["s7"]["jours"]) == 5
    assert len(s["faits"]["s8"]["devises"]) == 9 and s["faits"]["s9"]["paires"]
    assert s["faits"]["s1"]["fed"]["valeur"] is None and s["faits"]["s1"]["fed"]["raison"]   # livraison 2 : n/d avec raison


def test_synthese_publiee_du_jour_valide():
    chemin = Path(__file__).resolve().parents[1] / "docs" / "data" / "synthese.json"
    if not chemin.exists():
        pytest.skip("synthese.json pas encore publié")
    s = json.loads(chemin.read_text(encoding="utf-8"))
    assert len(s["sections"]) == 13 and all(s["textes"].get(f"s{i}") for i in range(1, 14))
    assert ct.verifier_textes(s["textes"], {**s["faits"], "textes_python": {}}) == {} or s.get("redige_par")
