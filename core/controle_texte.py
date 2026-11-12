"""Contrôle Python des textes rédigés (lot V9, partie C) : un texte est rejeté en entier si une seule phrase
- cite un nombre absent des faits fournis au modèle (chiffre inventé ou mal recopié) ;
- ne cite aucun fait chiffré ou daté (« guidé par l'addition des signaux techniques et économiques » : interdit) ;
- emploie une formule creuse de la liste FORMULES_CREUSES ;
- donne un ordre ou un niveau d'entrée, de stop ou d'objectif.
Le texte de secours Python passe le même contrôle (tests).
"""
from __future__ import annotations

import json
import re

# Nombres de vocabulaire (2 ans, 5 séances, RSI 14, seuil 50…) : autorisés, mais ne comptent pas comme un fait.
STRUCTURELS = {0, 1, 2, 3, 4, 5, 6, 9, 10, 13, 14, 20, 30, 50, 60, 70, 100}
FORMULES_CREUSES = [
    r"addition des signaux", r"signaux techniques et (?:économiques|macro)", r"guidée? par l'ensemble", r"dans un contexte (?:incertain|complexe|mitigé)",
    r"reste(?:nt)? à surveiller de près", r"il convient de rester (?:prudent|vigilant)", r"de nombreux facteurs", r"divers facteurs",
    r"une combinaison de facteurs", r"faisceau d'indices", r"conjonction de facteurs", r"climat d'incertitude",
]
ORDRES = [r"\bach[eè]te[rz]?\b", r"\bvend(?:re|ez|s)\b", r"\bprendre position\b", r"\bpoint d'entrée\b", r"\bniveau d'entrée\b",
          r"\bstop[- ]loss\b", r"\bstop\b", r"\btake[- ]profit\b", r"\bobjectif de cours\b", r"\bcible de prix\b", r"\bentrer (?:à|sur)\b",
          r"\bpositions? (?:longue|courte)s?\b"]
RE_NOMBRE = re.compile(r"(?<![\w/])[+−-]?\d{1,3}(?:[   ]\d{3})+(?:,\d+)?(?![\d])|(?<![\w])[+−-]?\d+(?:[.,]\d+)?")
RE_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")
RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _decimales(t: str) -> int:
    t = t.replace(" ", "").replace(" ", "").replace(" ", "")
    return len(t.split(",")[1]) if "," in t else len(t.split(".")[1]) if "." in t else 0


def _valeur(t: str) -> float:
    return abs(float(t.replace(" ", "").replace(" ", "").replace(" ", "").replace("−", "-").replace(",", ".")))


def nombres_texte(texte: str) -> list[tuple[str, float, int]]:
    """Nombres d'un texte (les dates JJ/MM comptent pour deux nombres)."""
    sortie = []
    for m in RE_NOMBRE.finditer(texte or ""):
        t = m.group()
        try:
            sortie.append((t, _valeur(t), _decimales(t)))
        except ValueError:
            continue
    return sortie


def nombres_autorises(faits) -> set[float]:
    """Toutes les valeurs numériques des faits (nombres, et nombres écrits dans les textes des faits), avec leurs
    variantes : milliers (165 K = 165 000), jours et mois des dates."""
    ok: set[float] = set(float(x) for x in STRUCTURELS)

    def ajouter(v: float):
        v = abs(v)
        ok.add(v)
        if v >= 1000:
            ok.add(v / 1000)
        else:
            ok.add(v * 1000)

    def parcourir(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            ajouter(float(x))
        elif isinstance(x, str):
            for a, m, j in RE_ISO.findall(x):
                ok.update({float(a), float(int(m)), float(int(j))})
            for t, v, _ in nombres_texte(RE_ISO.sub(" ", x)):
                ajouter(v)
        elif isinstance(x, dict):
            for k, v in x.items():
                parcourir(k) if isinstance(k, str) and RE_ISO.search(k) else None
                parcourir(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                parcourir(v)
    parcourir(faits)
    return ok


def autorise(v: float, d: int, ok: set[float]) -> bool:
    if v in ok:
        return True
    return any(round(a, d) == round(v, d) for a in ok)


def phrases(texte: str) -> list[str]:
    t = re.sub(r"\s+", " ", texte or "").strip()
    morceaux = re.split(r"(?<=[.!?])\s+(?=[A-ZÀÂÉÈÊÎÔÛÇ«(\d])", t)
    return [m.strip() for m in morceaux if m.strip()]


def verifier(texte: str, autorises: set[float]) -> list[str]:
    """Liste des raisons de rejet (vide : texte accepté)."""
    raisons = []
    for ph in phrases(texte):
        bas = ph.lower()
        for motif in FORMULES_CREUSES:
            if re.search(motif, bas):
                raisons.append(f"formule creuse « {re.search(motif, bas).group()} » : {ph[:90]}")
        for motif in ORDRES:
            if re.search(motif, bas):
                raisons.append(f"ordre ou niveau de trading « {re.search(motif, bas).group()} » : {ph[:90]}")
        ns = nombres_texte(ph)
        faits = [n for n in ns if n[1] not in STRUCTURELS or n[2] > 0]
        if not faits and not RE_DATE.search(ph):
            raisons.append(f"phrase sans fait chiffré ni date : {ph[:90]}")
        for t, v, d in ns:
            if not autorise(v, d, autorises):
                raisons.append(f"nombre absent des faits « {t} » : {ph[:90]}")
    return raisons


def verifier_textes(textes: dict[str, list[str]], faits) -> dict[str, list[str]]:
    """{section: raisons de rejet} pour chaque section dont un paragraphe est rejeté."""
    ok = nombres_autorises(faits)
    sortie = {}
    for sid, paragraphes in (textes or {}).items():
        r = []
        if not paragraphes or not any(str(p).strip() for p in paragraphes):
            r.append("texte vide")
        for p in paragraphes or []:
            r += verifier(str(p), ok)
        if r:
            sortie[sid] = r
    return sortie


def compacter(faits, max_liste: int = 12, max_txt: int = 400):
    """Faits envoyés au modèle : sans séries (bougies, points), listes courtes, textes tronqués."""
    if isinstance(faits, dict):
        return {k: compacter(v, max_liste, max_txt) for k, v in faits.items()
                if k not in ("bougies", "points", "serie_30", "serie_6m", "zones", "lignes", "seuils", "source_force")}
    if isinstance(faits, list):
        if faits and all(isinstance(x, (int, float)) for x in faits):
            return None
        return [compacter(x, max_liste, max_txt) for x in faits[:max_liste]]
    if isinstance(faits, str):
        return faits[:max_txt]
    return faits


def taille(faits) -> int:
    return len(json.dumps(faits, ensure_ascii=False))
