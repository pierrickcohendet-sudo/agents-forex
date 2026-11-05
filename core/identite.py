"""Identité visuelle (lot V8) : monogramme original « trois barres montantes et un point », dessiné ici sans dépendance.

Produit les icônes de l'application (192 et 512 px, et 180 px pour l'iPhone), l'icône d'onglet SVG et l'aperçu de partage
(og:image, 1200 × 630). Rendu vectoriel maison : chaque forme est une distance signée, l'anticrénelage vient de la
couverture du pixel ; encodage PNG avec zlib (bibliothèque standard). Couleurs : tokens de docs/site/tokens.css.
Usage : python -m core.identite
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ENCRE = (13, 22, 38)          # --ink (clair)
FOND_SOMBRE = (6, 8, 12)      # --bg (sombre)
ACCENT = (138, 164, 255)      # --accent (sombre)
ACCENT_CLAIR = (47, 85, 212)  # --accent (clair)
BLANC = (232, 236, 244)       # --ink (sombre)
VERT = (67, 211, 158)         # --up (sombre)

# Monogramme dans un carré unité [0, 1] : fond arrondi, trois barres montantes, point (le « maintenant »).
BARRES = [(0.24, 0.62, 0.10), (0.42, 0.48, 0.10), (0.60, 0.32, 0.10)]   # (x gauche, haut, largeur) ; bas commun 0.76
BAS = 0.76
POINT = (0.78, 0.24, 0.065)


def _sd_rect_arrondi(px, py, x0, y0, x1, y1, r):
    cx, cy, hx, hy = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2 - r, (y1 - y0) / 2 - r
    dx, dy = abs(px - cx) - hx, abs(py - cy) - hy
    return math.hypot(max(dx, 0), max(dy, 0)) + min(max(dx, dy), 0) - r


def _sd_cercle(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) - r


class Toile:
    def __init__(self, l: int, h: int, fond=(0, 0, 0, 0)):
        self.l, self.h = l, h
        self.px = [list(fond) for _ in range(l * h)]

    def forme(self, sd, bbox, couleur, alpha=1.0):
        """Remplit la forme (distance signée en pixels) dans sa boîte englobante, couverture = anticrénelage."""
        x0, y0, x1, y1 = (max(0, int(bbox[0]) - 1), max(0, int(bbox[1]) - 1), min(self.l, int(bbox[2]) + 2), min(self.h, int(bbox[3]) + 2))
        for y in range(y0, y1):
            for x in range(x0, x1):
                c = min(1.0, max(0.0, 0.5 - sd(x + 0.5, y + 0.5))) * alpha
                if c <= 0:
                    continue
                p = self.px[y * self.l + x]
                a0 = p[3] / 255
                a = c + a0 * (1 - c)
                for i in range(3):
                    p[i] = round((couleur[i] * c + p[i] * a0 * (1 - c)) / a) if a else 0
                p[3] = round(a * 255)

    def png(self) -> bytes:
        brut = b"".join(b"\x00" + bytes(v for p in self.px[y * self.l:(y + 1) * self.l] for v in p) for y in range(self.h))
        bloc = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)   # noqa: E731
        return (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", self.l, self.h, 8, 6, 0, 0, 0))
                + bloc(b"IDAT", zlib.compress(brut, 9)) + bloc(b"IEND", b""))


def monogramme(t: Toile, ox: float, oy: float, taille: float, fond=True, marge=0.0):
    """Dessine le monogramme dans le carré (ox, oy, taille). marge : zone de sécurité (icônes « maskable »)."""
    if fond:
        r = 0.22 * taille
        t.forme(lambda x, y: _sd_rect_arrondi(x, y, ox, oy, ox + taille, oy + taille, r), (ox, oy, ox + taille, oy + taille), ENCRE)
    s = taille * (1 - 2 * marge)
    bx, by = ox + taille * marge, oy + taille * marge
    for i, (x, haut, l) in enumerate(BARRES):
        X0, Y0, X1, Y1 = bx + x * s, by + haut * s, bx + (x + l) * s, by + BAS * s
        coul = BLANC if i < 2 else ACCENT
        t.forme(lambda px, py, a=(X0, Y0, X1, Y1): _sd_rect_arrondi(px, py, *a, 0.03 * s), (X0, Y0, X1, Y1), coul)
    cx, cy, r = bx + POINT[0] * s, by + POINT[1] * s, POINT[2] * s
    t.forme(lambda px, py: _sd_cercle(px, py, cx, cy, r), (cx - r, cy - r, cx + r, cy + r), VERT)


def icone(taille: int, marge: float = 0.0) -> bytes:
    t = Toile(taille, taille, (*ENCRE, 255) if marge else (0, 0, 0, 0))
    monogramme(t, 0, 0, taille, fond=not marge, marge=marge)
    return t.png()


def apercu_partage() -> bytes:
    """og:image 1200 × 630 : fond sombre, grand monogramme, frise de bougies stylisée (sans texte, aucune police)."""
    L, H = 1200, 630
    t = Toile(L, H, (*FOND_SOMBRE, 255))
    monogramme(t, 110, 165, 300)
    import random
    alea = random.Random(11)
    prix = 0.12
    for i in range(16):
        x = 520 + i * 38
        ouv = prix
        prix = min(0.92, max(0.08, prix + 0.035 + alea.uniform(-0.07, 0.06)))   # tendance montante, bougies mêlées
        haut, bas = max(ouv, prix) + alea.uniform(0.02, 0.06), min(ouv, prix) - alea.uniform(0.02, 0.06)
        coul = VERT if prix > ouv else (255, 127, 115)
        y = lambda v: 480 - v * 330   # noqa: E731
        m0, m1 = y(haut), y(bas)
        t.forme(lambda px, py, a=(x + 11, m0, x + 13, m1): _sd_rect_arrondi(px, py, *a, 1), (x + 11, m0, x + 13, m1), coul, 0.8)
        y0, y1 = sorted((y(ouv), y(prix)))
        y1 = max(y1, y0 + 4)
        t.forme(lambda px, py, a=(x, y0, x + 24, y1): _sd_rect_arrondi(px, py, *a, 3), (x, y0, x + 24, y1), coul)
    t.forme(lambda px, py: _sd_rect_arrondi(px, py, 520, 520, 1130, 524, 2), (520, 520, 1130, 524), ACCENT, 0.6)
    return t.png()


SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="Trading baby">'
       '<rect width="100" height="100" rx="22" fill="#0D1626"/>'
       + "".join(f'<rect x="{x * 100:.1f}" y="{h * 100:.1f}" width="{l * 100:.1f}" height="{(BAS - h) * 100:.1f}" rx="3" '
                 f'fill="{"#E8ECF4" if i < 2 else "#8AA4FF"}"/>' for i, (x, h, l) in enumerate(BARRES))
       + f'<circle cx="{POINT[0] * 100:.1f}" cy="{POINT[1] * 100:.1f}" r="{POINT[2] * 100:.1f}" fill="#43D39E"/></svg>')


def ecrire(racine: str | Path) -> list[str]:
    docs = Path(racine) / "docs"
    (docs / "icones").mkdir(parents=True, exist_ok=True)
    fichiers = {"icones/icone-192.png": icone(192), "icones/icone-512.png": icone(512),
                "icones/icone-maskable-512.png": icone(512, marge=0.12), "icones/apple-touch-icon.png": icone(180, marge=0.08),
                "og-image.png": apercu_partage()}
    for nom, data in fichiers.items():
        (docs / nom).write_bytes(data)
    (docs / "icones" / "logo.svg").write_text(SVG, encoding="utf-8")
    return [*fichiers, "icones/logo.svg"]


if __name__ == "__main__":
    print(ecrire(Path(__file__).resolve().parent.parent))
