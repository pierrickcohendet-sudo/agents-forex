"""Constructeurs de blocs Notion + URLs de graphiques QuickChart.io.

Couleurs par biais : Risk On = vert, Risk Off = rouge, Neutre = jaune.
"""
from __future__ import annotations

import json
from urllib.parse import quote

COULEURS_HEX = {"on": "#22c55e", "off": "#ef4444", "neutre": "#eab308"}
COULEURS_CALLOUT = {"on": "green_background", "off": "red_background", "neutre": "yellow_background"}
COULEURS_TEXTE = {"on": "green", "off": "red", "neutre": "yellow"}
LIBELLES_BIAIS = {"on": "Risk On", "off": "Risk Off", "neutre": "Neutre"}


# --------------------------------------------------------------- rich text
def rt(texte: str, gras: bool = False, couleur: str = "default", italique: bool = False) -> dict:
    return {
        "type": "text",
        "text": {"content": str(texte)[:2000]},
        "annotations": {"bold": gras, "italic": italique, "color": couleur,
                        "strikethrough": False, "underline": False, "code": False},
    }


# ------------------------------------------------------------------- blocs
def paragraphe(fragments: list[dict]) -> dict:
    return {"type": "paragraph", "paragraph": {"rich_text": fragments}}


def paragraphe_gris(texte: str) -> dict:
    return paragraphe([rt(texte, couleur="gray", italique=True)])


def titre(niveau: int, texte: str) -> dict:
    cle = f"heading_{niveau}"
    return {"type": cle, cle: {"rich_text": [rt(texte, gras=True)]}}


def callout(fragments: list[dict], emoji: str, couleur: str) -> dict:
    return {"type": "callout", "callout": {
        "rich_text": fragments, "icon": {"type": "emoji", "emoji": emoji}, "color": couleur,
    }}


def toggle(fragments: list[dict], enfants: list[dict] | None = None) -> dict:
    bloc = {"type": "toggle", "toggle": {"rich_text": fragments}}
    if enfants:
        bloc["toggle"]["children"] = enfants
    return bloc


def puce(fragments: list[dict]) -> dict:
    return {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": fragments}}


def image_externe(url: str, legende: str = "") -> dict:
    bloc = {"type": "image", "image": {"type": "external", "external": {"url": url}}}
    if legende:
        bloc["image"]["caption"] = [rt(legende, couleur="gray")]
    return bloc


def tableau(entetes: list[str], lignes: list[list]) -> dict:
    """Tableau Notion natif (lignes passées à la création). Une cellule peut
    être une valeur simple OU une liste de fragments rich text (pour styler,
    ex. badge J-n en orange)."""
    largeur = len(entetes)
    rangees = [{"type": "table_row", "table_row": {"cells": [[rt(e, gras=True)] for e in entetes]}}]
    for ligne in lignes:
        cellules = [c if isinstance(c, list) else [rt(str(c) if c not in (None, "") else "—")]
                    for c in ligne[:largeur]]
        cellules += [[rt("—")]] * (largeur - len(cellules))
        rangees.append({"type": "table_row", "table_row": {"cells": cellules}})
    return {"type": "table", "table": {
        "table_width": largeur, "has_column_header": True,
        "has_row_header": False, "children": rangees,
    }}


# -------------------------------------------------------------- QuickChart
def _url_quickchart(config_chart: dict, largeur: int, hauteur: int) -> str:
    brut = json.dumps(config_chart, separators=(",", ":"))
    return (
        "https://quickchart.io/chart?version=3&backgroundColor=transparent"
        f"&width={largeur}&height={hauteur}&c={quote(brut)}"
    )


def url_jauge_confluence(score: int, biais: str) -> str:
    """Doughnut (cutout 75 %) : segment coloré = score, reste en gris sombre."""
    config_chart = {
        "type": "doughnut",
        "data": {"datasets": [{
            "data": [score, 100 - score],
            "backgroundColor": [COULEURS_HEX.get(biais, COULEURS_HEX["neutre"]), "#2d333f"],
            "borderWidth": 0,
        }]},
        "options": {
            "cutout": "75%", "rotation": -90,
            "plugins": {"legend": {"display": False},
                        "title": {"display": True, "text": f"Confluence {score}/100",
                                  "color": "#8b95a5"}},
        },
    }
    return _url_quickchart(config_chart, 220, 180)


LIMITE_URL_IMAGE_NOTION = 1900  # Notion rejette toute image externe > 2000 car. ; marge de sécurité


def url_graphique_prix(dates: list[str], clotures: list[float], libelle: str, biais: str) -> str:
    """Courbe de prix (série orientée force de la devise).

    La limite d'URL d'un bloc image externe Notion est stricte (2000
    caractères) : un dépassement fait échouer l'appel `blocks.children.append`
    pour TOUTE la devise (et, non catché plus haut, coupait net la publication
    des devises suivantes). On sous-échantillonne donc de façon adaptative —
    en dernier recours en réduisant aussi la précision décimale — jusqu'à
    garantir une URL sous la limite, quelle que soit la longueur de l'historique.
    """
    couleur = COULEURS_HEX.get(biais, COULEURS_HEX["neutre"])
    n_points = min(len(clotures), 40)
    decimales = 5
    while True:
        pas = max(1, len(clotures) // n_points) if n_points else max(1, len(clotures))
        dates_l = [d[5:] for d in dates[::pas]]  # MM-JJ suffit
        valeurs = [round(v, decimales) for v in clotures[::pas]]
        config_chart = {
            "type": "line",
            "data": {"labels": dates_l, "datasets": [{
                "data": valeurs, "borderColor": couleur,
                "borderWidth": 2, "pointRadius": 0, "fill": False, "tension": 0.2,
            }]},
            "options": {
                "plugins": {"legend": {"display": False},
                            "title": {"display": True, "text": libelle, "color": "#8b95a5"}},
                "scales": {
                    "x": {"ticks": {"maxTicksLimit": 8, "color": "#8b95a5"}},
                    "y": {"ticks": {"color": "#8b95a5"}},
                },
            },
        }
        url = _url_quickchart(config_chart, 640, 260)
        if len(url) <= LIMITE_URL_IMAGE_NOTION or (n_points <= 6 and decimales <= 2):
            return url
        if n_points > 6:
            n_points -= 6
        else:
            decimales -= 1


COULEUR_WTI = "#eab308"
COULEUR_BRENT = "#38bdf8"


def url_graphique_petrole(dates_wti: list[str], valeurs_wti: list[float],
                          dates_brent: list[str], valeurs_brent: list[float]) -> str:
    """Pétrole WTI + Brent (FRED — Twelve Data réserve les commodités au tier
    payant, vérifié) : même mécanisme QuickChart que url_graphique_prix, deux
    séries superposées. Légende affichée (contrairement aux autres graphiques)
    car deux courbes se distinguent mal sans elle."""
    reference = valeurs_wti or valeurs_brent
    if not reference:
        return ""
    n_points = min(len(reference), 40)
    decimales = 2
    while True:
        def echantillon(dates: list[str], valeurs: list[float]) -> tuple[list[str], list[float]]:
            if not valeurs:
                return [], []
            pas = max(1, len(valeurs) // n_points) if n_points else max(1, len(valeurs))
            return [d[5:] for d in dates[::pas]], [round(v, decimales) for v in valeurs[::pas]]

        labels_wti, data_wti = echantillon(dates_wti, valeurs_wti)
        labels_brent, data_brent = echantillon(dates_brent, valeurs_brent)
        labels = labels_wti or labels_brent
        datasets = []
        if data_wti:
            datasets.append({"label": "WTI", "data": data_wti, "borderColor": COULEUR_WTI,
                             "borderWidth": 2, "pointRadius": 0, "fill": False, "tension": 0.2})
        if data_brent:
            datasets.append({"label": "Brent", "data": data_brent, "borderColor": COULEUR_BRENT,
                             "borderWidth": 2, "pointRadius": 0, "fill": False, "tension": 0.2})
        config_chart = {
            "type": "line",
            "data": {"labels": labels, "datasets": datasets},
            "options": {
                "plugins": {
                    "legend": {"display": True, "labels": {"color": "#8b95a5", "boxWidth": 10}},
                    "title": {"display": True, "text": "Pétrole WTI / Brent ($/baril, FRED)",
                             "color": "#8b95a5"},
                },
                "scales": {
                    "x": {"ticks": {"maxTicksLimit": 8, "color": "#8b95a5"}},
                    "y": {"ticks": {"color": "#8b95a5"}},
                },
            },
        }
        url = _url_quickchart(config_chart, 640, 260)
        if len(url) <= LIMITE_URL_IMAGE_NOTION or (n_points <= 6 and decimales <= 1):
            return url
        if n_points > 6:
            n_points -= 6
        else:
            decimales -= 1
