"""Correctif du 11/11/2026 : jamais de mélange d'ancien et de nouveau code, adresses de détail, erreurs d'affichage."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import version_site

RACINE = Path(__file__).resolve().parents[1]
SITE = RACINE / "docs" / "site"


def _sw():
    return (RACINE / "docs" / "sw.js").read_text(encoding="utf-8")


def test_service_worker_precharge_toute_sa_version():
    html = (RACINE / "docs" / "index.html").read_text(encoding="utf-8")
    version = html.split('name="fxdesk-version" content="')[1].split('"')[0]
    sw = _sw()
    fichiers = json.loads(re.search(r"const FICHIERS = (\[.*?\]);", sw).group(1))
    assert fichiers == version_site.fichiers_code(RACINE / "docs", version)
    # chaque module de l'importmap est dans le pré-cache, avec la même adresse
    carte = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html).group(1))["imports"]
    assert {v.removeprefix("./") for v in carte.values()} <= set(fichiers)
    assert any(f.startswith("site/vendor/lightweight-charts") for f in fichiers)


def test_pas_d_activation_en_pleine_session():
    sw = _sw()
    install = sw.split('addEventListener("install"')[1].split("});")[0]
    assert "skipWaiting()" not in install                    # la nouvelle version attend le rechargement
    assert 'type === "activer"' in sw and "skipWaiting()" in sw
    html = (RACINE / "docs" / "index.html").read_text(encoding="utf-8")
    assert 'id="majDispo"' in html and "Nouvelle version disponible" in html and "controllerchange" in html
    assert 'id="erreurGlobale"' in html


def test_code_d_une_autre_version_jamais_mis_en_cache():
    sw = _sw()
    assert '(!v || v === VERSION)' in sw


def test_erreur_d_affichage_et_adresses_de_detail():
    app = (SITE / "app.js").read_text(encoding="utf-8")
    assert "carteErreur" in app and "data-recharger" in app and "unhandledrejection" in app and "s.allerA" in app
    dev = (SITE / "ecran_devises.js").read_text(encoding="utf-8")
    assert "section.allerA" in dev and "fiche-${code}" in dev
    eng = (SITE / "ecran_engrenages.js").read_text(encoding="utf-8")
    assert "section.allerA" in eng and '"hebdo"' in eng
    # plus aucun lien vers une adresse que le routeur ne sait pas ouvrir
    tout = "\n".join(f.read_text(encoding="utf-8") for f in SITE.glob("*.js"))
    assert 'href = "#outils"' not in tout and "lien: `#devises` }" not in tout


def test_graphique_retire_n_est_plus_rappele():
    v7 = (SITE / "v7_commun.js").read_text(encoding="utf-8")
    assert "x.c === g.c" in v7 and "g.mort" in v7
    pg = (SITE / "paire_graphique.js").read_text(encoding="utf-8")
    assert "unsubscribeCrosshairMove" in pg and "unsubscribeVisibleLogicalRangeChange" in pg
    assert "retirerGraphique({ c: r" not in pg               # ancien retrait qui laissait le RSI dans le registre


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
def test_syntaxe_des_modules():
    for f in sorted(SITE.glob("*.js")):
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert r.returncode == 0, f"{f.name} : {r.stderr}"
