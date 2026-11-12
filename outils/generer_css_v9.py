# Usage : python outils/generer_css_v9.py (depuis la racine du dépôt) — régénère docs/site/v9.css depuis la maquette V9.
"""Extrait le CSS V9 de la maquette (bloc « V9 : la Synthèse en rapport éditorial ») et préfixe chaque sélecteur par .v9."""
import re
from pathlib import Path

src = Path("docs/design/maquette_v9_synthese.html").read_text(encoding="utf-8")
debut = src.index("/* ===== V9 : la Synthèse en rapport éditorial ===== */")
fin = src.index("</style>", debut)
css = src[debut:fin]


def prefixer(sel: str) -> str:
    out = []
    for s in sel.split(","):
        s = s.strip()
        if not s:
            continue
        if s.startswith("[data-origine"):
            s = s.replace('[data-origine="on"]', '.v9[data-sources="on"]')
            out.append(s)
        else:
            out.append(".v9 " + s)
    return ",".join(out)


def traiter(bloc: str) -> str:
    res, i = [], 0
    while i < len(bloc):
        if bloc.startswith("/*", i):
            j = bloc.index("*/", i) + 2
            res.append(bloc[i:j]); i = j; continue
        if bloc[i].isspace():
            res.append(bloc[i]); i += 1; continue
        if bloc.startswith("@media", i):
            ouv = bloc.index("{", i)
            prof, j = 1, ouv + 1
            while prof:
                if bloc[j] == "{":
                    prof += 1
                elif bloc[j] == "}":
                    prof -= 1
                j += 1
            res.append(bloc[i:ouv + 1] + traiter(bloc[ouv + 1:j - 1]) + "}")
            i = j; continue
        ouv = bloc.index("{", i)
        ferme = bloc.index("}", ouv)
        res.append(prefixer(bloc[i:ouv]) + bloc[ouv:ferme + 1])
        i = ferme + 1
    return "".join(res)


entete = ("/* Lot V9 — Synthèse en rapport éditorial (docs/design/maquette_v9_synthese.html), règles de la maquette préfixées par .v9.\n"
          "   « Origine des données » devient « Sources » : .v9[data-sources=\"on\"] montre les étiquettes de source. */\n")
complement = """
/* Compléments du site (hors maquette) */
.v9 .toc{top:calc(var(--haut-entete,124px) + 8px)}
.v9 .rs{scroll-margin-top:calc(var(--haut-entete,124px) + 24px)}
.v9 [data-src]{cursor:help}
.v9[data-sources="on"] [data-src]{text-decoration:underline dotted color-mix(in srgb,var(--accent) 60%,transparent);text-underline-offset:3px}
.v9 .redac{font-size:11.5px;color:var(--muted);display:inline-flex;gap:6px;align-items:center}
.v9 .redac.r-auto::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--warn)}
.v9 .redac.r-modele::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--up)}
.v9 .retard{height:22px}
.v9 .mech div .mc9{font-size:12px;color:var(--muted)}
.v9 .mech div .mc9.ok{color:var(--up)}
.v9 .chk li.ok::before{content:"●";color:var(--up)}
.v9 .alerte9{padding:12px 16px;border-radius:12px;background:var(--warn-soft);color:var(--ink);font-size:13.5px}
.v9 .nd9{color:var(--muted)}
.v9 .sec-err{padding:14px 16px;border-radius:12px;border:1px dashed var(--line-2);color:var(--muted);font-size:13.5px}
.v9 .bascule{display:inline-flex}
.v9 .wd .e .pub{font-weight:600}
.v9 .speak .chip{white-space:normal;height:auto;min-height:26px;padding:4px 10px;line-height:1.35;max-width:100%}
.v9 .scroll .tbl td.small{min-width:160px}
@media (max-width:1100px){.v9 .toc{top:var(--haut-entete,124px)}.v9 .rs{scroll-margin-top:calc(var(--haut-entete,124px) + 64px)}}
@media (max-width:640px){.v9 .hero9 h1{font-size:34px}.v9 .tbl td,.v9 .tbl th{padding:9px 8px}}
"""
Path("docs/site/v9.css").write_text(entete + traiter(css.split("\n", 1)[1]) + complement, encoding="utf-8")
print(len(Path("docs/site/v9.css").read_text(encoding="utf-8")))
