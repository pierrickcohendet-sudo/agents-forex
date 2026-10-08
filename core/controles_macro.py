"""Contrôles de cohérence du Tableau macro + indice de surprise par devise.

Code pur, déterministe, aucun LLM :
- hors plage plausible (bornes par indicateur, config.yaml) ;
- divergence ForexFactory vs FRED au-delà d'un seuil ;
- publication manquée / valeur périmée (périodicité + marge) ;
- événement introuvable (pas de case vide silencieuse) ;
- taux de remplissage par vue + liste des cases sans valeur et leur raison ;
- indice de surprise sur 30 jours glissants (moyenne pondérée des surprises
  normalisées, chômage inversé) et sa tendance.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from core import registre_macro as rm

PREFIXE = "tableau macro : "


def _jj_mm(d: str | None) -> str:
    return f"{d[8:10]}/{d[5:7]}" if d else "?"


def _periodicite(cfg_tm: dict, indicateur: str, devise: str) -> int:
    mapping = cfg_tm["correspondances"].get(indicateur, {}).get(devise, {})
    return int(mapping.get("periodicite_jours", cfg_tm["indicateurs"][indicateur]["periodicite_jours"]))


def controler_registre(registre: dict, cfg_tm: dict, maintenant: datetime | None = None) -> dict:
    """{anomalies: [...], cases_sans_valeur: [{case, raison}]}"""
    maintenant = maintenant or datetime.now(timezone.utc)
    aujourdhui = maintenant.date()
    marge = int(cfg_tm.get("marge_peremption_jours", 20))
    anomalies: list[str] = []
    sans_valeur: list[dict] = []
    for indicateur, cfg_ind in cfg_tm["indicateurs"].items():
        for devise in cfg_tm["ordre_devises"]:
            cle = rm.cle(indicateur, devise)
            case = registre["cases"].get(cle)
            nom = f"{devise}/{cfg_ind['libelle']}"
            if case is None or case.get("statut") == "non_applicable":
                if case is not None:
                    sans_valeur.append({"case": cle, "raison": case.get("absent") or "inexistant dans ce pays"})
                continue
            actuel = case.get("actuel")
            if not actuel or actuel.get("valeur") in (None, ""):
                anomalies.append(f"{PREFIXE}{nom} : événement ForexFactory introuvable "
                                 f"et aucun repli — historique à initialiser")
                sans_valeur.append({"case": cle, "raison": "échec de source / à initialiser"})
                continue
            prevision = case.get("prevision")
            if prevision and not prevision.get("valeur"):
                sans_valeur.append({"case": f"{cle}|Prévision", "raison": "consensus à venir"})

            # 1. hors plage plausible
            bornes = cfg_ind.get("bornes")
            if bornes:
                for libelle, valeur in (("actuel", actuel.get("valeur")),
                                        ("précédent", (case.get("precedent") or {}).get("valeur"))):
                    x = rm.vers_nombre(valeur)
                    if x is not None and not (bornes[0] <= x <= bornes[1]):
                        anomalies.append(f"{PREFIXE}{nom} : valeur {libelle} hors plage plausible ({valeur})")

            # 2. divergence ForexFactory vs FRED (période FRED compatible uniquement)
            fred = case.get("fred")
            if fred and actuel.get("origine") is None and actuel.get("date_pub") and fred.get("periode"):
                ecart_jours = (date.fromisoformat(actuel["date_pub"])
                               - date.fromisoformat(fred["periode"] + "-01")).days
                if 0 <= ecart_jours <= 100:
                    ff = rm.vers_nombre(actuel["valeur"])
                    candidats = [rm.vers_nombre(fred.get("valeur")), rm.vers_nombre(fred.get("precedente"))]
                    absolu = str(actuel["valeur"])[-1:] in ("K", "M", "B", "T")
                    tol = cfg_ind.get("tolerance_absolue" if absolu else "tolerance")
                    if ff is not None and tol is not None and all(c is not None for c in candidats) \
                            and all(abs(ff - c) > tol for c in candidats):
                        anomalies.append(
                            f"{PREFIXE}{nom} : divergence de sources — ForexFactory {actuel['valeur']} "
                            f"vs FRED {fred['valeur']} (pér. {fred['periode']}, {fred['serie']})")

            # 3. publication manquée / valeur périmée
            if prevision and prevision.get("dateline"):
                retard = maintenant.timestamp() - prevision["dateline"]
                a_dateline = (actuel.get("dateline") or 0)
                if retard > 36 * 3600 and a_dateline < prevision["dateline"]:
                    anomalies.append(f"{PREFIXE}{nom} : publication manquée (prévue le "
                                     f"{_jj_mm(prevision.get('date_pub'))}, aucun « réel » reçu)")
                    continue
            if actuel.get("date_pub"):
                age = (aujourdhui - date.fromisoformat(actuel["date_pub"])).days
                limite = _periodicite(cfg_tm, indicateur, devise) + marge
                if age > limite:
                    anomalies.append(f"{PREFIXE}{nom} : valeur périmée ({age} j, limite {limite} j) — "
                                     "publication manquée probable")
    return {"anomalies": anomalies, "cases_sans_valeur": sans_valeur}


# --------------------------------------------------------- indice de surprise
def _echelle(cfg_ind: dict, valeur: str) -> float:
    if str(valeur)[-1:] in "KMBT" and cfg_ind.get("echelle_surprise_absolue"):
        return float(cfg_ind["echelle_surprise_absolue"])
    return float(cfg_ind["echelle_surprise"])


def _surprises(case: dict, cfg_ind: dict, plafond: float) -> list[tuple[str, float]]:
    """[(date_pub, surprise normalisée signée)] pour les publications avec consensus."""
    publications = list(case.get("historique", []))
    if case.get("actuel"):
        publications.append(case["actuel"])
    resultat = []
    for p in publications:
        if not p.get("date_pub") or not p.get("consensus"):
            continue
        reel, consensus = rm.vers_nombre(p.get("valeur")), rm.vers_nombre(p["consensus"])
        if reel is None or consensus is None:
            continue
        s = (reel - consensus) / _echelle(cfg_ind, p["valeur"])
        s = max(-plafond, min(plafond, s))
        resultat.append((p["date_pub"], -s if cfg_ind.get("sens") == "inverse" else s))
    return resultat


def indice_surprise(registre: dict, cfg_tm: dict, aujourdhui: date | None = None) -> dict:
    """{devise: {indice, precedent, tendance, n}} — indice = moyenne pondérée des
    surprises normalisées (en « écarts habituels ») sur fenetre_jours ; `precedent`
    = même calcul sur la fenêtre d'avant (tendance). None si aucune publication."""
    aujourdhui = aujourdhui or date.today()
    cfg = cfg_tm.get("indice_surprise", {})
    fenetre = int(cfg.get("fenetre_jours", 30))
    plafond = float(cfg.get("plafond_surprise", 3))
    seuil = float(cfg.get("seuil_tendance", 0.15))
    debut1 = (aujourdhui - timedelta(days=fenetre)).isoformat()
    debut0 = (aujourdhui - timedelta(days=2 * fenetre)).isoformat()
    fin = aujourdhui.isoformat()
    resultat = {}
    for devise in cfg_tm["ordre_devises"]:
        fenetres = {"actuelle": [], "precedente": []}
        for indicateur, cfg_ind in cfg_tm["indicateurs"].items():
            case = registre["cases"].get(rm.cle(indicateur, devise))
            if not case or case.get("statut") == "non_applicable":
                continue
            poids = float(cfg_ind.get("poids_surprise", 1))
            for d, s in _surprises(case, cfg_ind, plafond):
                if debut1 < d <= fin:
                    fenetres["actuelle"].append((poids, s))
                elif debut0 < d <= debut1:
                    fenetres["precedente"].append((poids, s))

        def moyenne(lst):
            total = sum(p for p, _ in lst)
            return round(sum(p * s for p, s in lst) / total, 2) if total else None

        indice, avant = moyenne(fenetres["actuelle"]), moyenne(fenetres["precedente"])
        if indice is None or avant is None:
            tendance = "n/d"
        elif indice - avant > seuil:
            tendance = "hausse"
        elif indice - avant < -seuil:
            tendance = "baisse"
        else:
            tendance = "stable"
        resultat[devise] = {"indice": indice, "precedent": avant, "tendance": tendance,
                            "n": len(fenetres["actuelle"])}
    return resultat


def texte_indice(i: dict) -> str:
    if i.get("indice") is None:
        return "n/d (aucune publication avec consensus sur 30 j)"
    fleche = {"hausse": "▲", "baisse": "▼", "stable": "=", "n/d": ""}[i["tendance"]]
    return f"{i['indice']:+.1f}".replace(".", ",") + (f" {fleche}" if fleche else "") + f" (n={i['n']})"
