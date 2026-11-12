"""Identifiant de version du site (lot V6.1) : plus de page ancienne servie par le cache du navigateur après une
publication. L'identifiant est l'empreinte (SHA-1, 7 caractères) du code du site (docs/site/*.js, *.css) : il ne
change que si le code change, donc index.html n'est réécrit qu'à ce moment-là.

docs/index.html reçoit : la feuille de style et app.js suffixés « ?v=<id> », une importmap qui suffixe chaque module
importé (imports internes compris) et une balise meta lue par le site pour versionner les JSON de données et
l'afficher dans le pied de page (« version abc1234 · généré le JJ/MM/AAAA HH:MM »)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

DEBUT, FIN = "<!-- version-site:debut -->", "<!-- version-site:fin -->"
# Lot V7 : anciens composants (cabinet.css, restylés par les tokens), tokens de la maquette, composants V7 — dans cet ordre.
FEUILLES = ("cabinet.css", "tokens.css", "v7.css", "v8.css", "v9.css")


def empreinte(dossier_site: Path) -> str:
    h = hashlib.sha1()
    for f in sorted(Path(dossier_site).glob("*")):
        if f.suffix in (".js", ".css"):
            h.update(f.name.encode())
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:7]


def fichiers_code(docs: Path, version: str) -> list[str]:
    """Adresses du code d'une version, exactement comme la page les demande (importmap, feuilles, bibliothèque)."""
    site = Path(docs) / "site"
    code = [f"site/{f.name}?v={version}" for f in sorted(site.glob("*")) if f.suffix in (".js", ".css")]
    vendor = [f"site/vendor/{f.name}?v={version}" for f in sorted((site / "vendor").glob("*.js"))]
    autres = ["manifest.webmanifest", "icones/logo.svg", "icones/icone-192.png"]
    return code + vendor + [a for a in autres if (Path(docs) / a).exists()]


def bloc_tete(version: str, modules: list[str]) -> str:
    carte = {"imports": {f"./site/{m}": f"./site/{m}?v={version}" for m in modules}}
    return (f"{DEBUT}\n  <meta name=\"fxdesk-version\" content=\"{version}\">\n"
            f"  <script type=\"importmap\">{json.dumps(carte, ensure_ascii=False)}</script>\n"
            + "".join(f"  <link rel=\"stylesheet\" href=\"site/{f}?v={version}\">\n" for f in FEUILLES) + f"  {FIN}")


def appliquer(racine: str | Path) -> dict:
    """Met index.html à jour avec la version courante. -> {version, modifie}."""
    racine = Path(racine)
    site = racine / "docs" / "site"
    index = racine / "docs" / "index.html"
    version = empreinte(site)
    modules = sorted(f.name for f in site.glob("*.js"))
    html = index.read_text(encoding="utf-8")
    bloc = bloc_tete(version, modules)
    if DEBUT in html:
        nouveau = re.sub(re.escape(DEBUT) + r".*?" + re.escape(FIN), lambda _: bloc, html, flags=re.S)
    else:
        nouveau = re.sub(r'  <link rel="stylesheet" href="site/cabinet\.css[^"]*">', lambda _: "  " + bloc, html, count=1)
    nouveau = re.sub(r'<script type="module" src="site/app\.js[^"]*"></script>',
                     f'<script type="module" src="site/app.js?v={version}"></script>', nouveau)
    if nouveau != html:
        index.write_text(nouveau, encoding="utf-8")
    sw = racine / "docs" / "sw.js"   # lot V8 : le cache du code est vidé à chaque nouvelle version
    if sw.exists():
        t = sw.read_text(encoding="utf-8")
        t2 = re.sub(r'const VERSION = "[^"]*";', f'const VERSION = "{version}";', t, count=1)
        # Correctif du 11/11 : le service worker met en cache TOUT le code de sa version à l'installation
        t2 = re.sub(r'const FICHIERS = \[[^\]]*\];', lambda _: f"const FICHIERS = {json.dumps(fichiers_code(racine / 'docs', version))};", t2, count=1)
        if t2 != t:
            sw.write_text(t2, encoding="utf-8")
    return {"version": version, "modifie": nouveau != html}


if __name__ == "__main__":
    print(appliquer(Path(__file__).resolve().parent.parent))
