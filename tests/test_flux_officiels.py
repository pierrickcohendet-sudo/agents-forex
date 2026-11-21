"""Flux RSS/Atom officiels (21/11/2026) : configuration (licence vérifiée, moteur), collecte robuste (un flux en échec est
ignoré, un 403 n'est jamais contourné), source et lien gardés, classement par moteur. Aucun appel réseau : session simulée."""
from pathlib import Path

import yaml

from agents import collecte_news
from core import dossiers_moteurs as dm

RACINE = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
<entry><title>Public sector finances bulletin: October 2026</title><link href="https://www.gov.uk/x"/><updated>2099-01-01T10:00:00Z</updated></entry></feed>"""
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Council adopts new sanctions against Russia</title><link>https://www.consilium.europa.eu/y</link><pubDate>Fri, 01 Jan 2099 10:00:00 GMT</pubDate></item>
<item><title>Meeting of the working party on statistics</title><link>https://www.consilium.europa.eu/z</link><pubDate>Fri, 01 Jan 2099 10:00:00 GMT</pubDate></item>
</channel></rss>"""


class Rep:
    def __init__(self, code, contenu=b""):
        self.status_code, self.content = code, contenu

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}")


class Session:
    def __init__(self, table):
        self.table, self.appels = table, []

    def get(self, url, headers=None, timeout=None):
        self.appels.append((url, headers))
        r = self.table.get(url)
        if isinstance(r, Exception):
            raise r
        return r or Rep(404)


def cfg(**officiels):
    return {"rss": {}, "rss_officiels": officiels}


def test_configuration_des_flux_officiels():
    o = CONFIG["rss_officiels"]
    attendus = {"bns_actualites": 2, "boj_nouveautes": 2, "tresor_adjudications": 4, "commission_ue": 4, "hm_treasury": 4, "mof_japon": 4,
                "onu_paix": 6, "fcdo": 6, "conseil_ue": 6, "eia_energie": 8}
    for k, n in attendus.items():
        assert o[k]["moteur"] == n and o[k]["url"].startswith("https://") and o[k]["licence"] and o[k]["nom"], k
    assert o["tresor_adjudications"]["accept"] == "application/rss+xml"        # le serveur répond 406 sinon
    assert "fmi" not in o and "opep" not in o and "departement_etat" not in o   # 403 au robot : écartés, jamais contournés
    assert all(isinstance(u, str) for u in CONFIG["rss"].values())             # core/communiques.py lit encore des URL simples


def test_flux_en_echec_ignore_sans_casser_le_run():
    s = Session({"https://a/ok": Rep(200, ATOM), "https://a/403": Rep(403), "https://a/x": ConnectionError("réseau"), "https://a/vide": Rep(200, b"pas du xml")})
    r = collecte_news.collecter(cfg(ok={"url": "https://a/ok", "nom": "HM Treasury (GOV.UK)", "moteur": 4, "licence": "OGL", "classement": "flux"},
                                    interdit={"url": "https://a/403", "nom": "X", "moteur": 6}, coupe={"url": "https://a/x", "nom": "Y", "moteur": 6},
                                    vide={"url": "https://a/vide", "nom": "Z", "moteur": 8}), "UA", session=s)
    assert r["flux"]["ok"]["statut"] == "ok" and r["flux"]["ok"]["nb_articles"] == 1
    assert r["flux"]["interdit"]["statut"] == "indisponible" and "jamais contourné" in r["flux"]["interdit"]["raison"]
    assert r["flux"]["coupe"]["statut"] == "indisponible" and r["flux"]["vide"]["statut"] == "indisponible"
    assert sum(1 for u, _ in s.appels if u == "https://a/403") == 1              # un seul essai, aucun contournement
    a = r["articles"][0]
    assert a["lien"] == "https://www.gov.uk/x" and a["source_nom"] == "HM Treasury (GOV.UK)" and a["moteur_flux"] == 4 and a["officiel"]
    assert "agents-forex" in s.appels[0][1]["User-Agent"]                        # client identifié, aucune donnée personnelle


def test_classement_flux_specialise_et_flux_generaliste():
    s = Session({"https://t/atom": Rep(200, ATOM), "https://c/rss": Rep(200, RSS)})
    r = collecte_news.collecter(cfg(hm={"url": "https://t/atom", "nom": "HM Treasury (GOV.UK)", "moteur": 4, "classement": "flux"},
                                    conseil={"url": "https://c/rss", "nom": "Conseil de l'UE", "moteur": 6}), "UA", session=s)
    l = dm.titres_classes(r["articles"], "2099-01-01")
    titres = {t["titre"]: t for t in l}
    assert titres["Public sector finances bulletin: October 2026"]["moteurs"][0] == 4          # flux spécialisé : son moteur d'abord
    assert titres["Council adopts new sanctions against Russia"]["moteurs"][0] == 6            # flux généraliste : mots-clés
    assert "Meeting of the working party on statistics" not in titres                          # sans mot-clé : écarté
    assert titres["Council adopts new sanctions against Russia"]["source"] == "Conseil de l'UE"
    assert titres["Council adopts new sanctions against Russia"]["lien"].startswith("https://www.consilium.europa.eu")
