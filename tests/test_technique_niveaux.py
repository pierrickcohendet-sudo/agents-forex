"""Rapport du jour, étape 9 : niveaux techniques sur des cas construits à la main (BOS, CHoCH, FVG, sessions)."""
from pytest import approx

from core import technique_niveaux as tn


def b(t, o, h, l, c):
    return [t, o, h, l, c]


def test_fvg_haussiere_ouverte_puis_comblee():
    bougies = [b("2026-10-26 00:00", 1.00, 1.01, 0.99, 1.005), b("2026-10-26 04:00", 1.006, 1.03, 1.005, 1.028),
               b("2026-10-26 08:00", 1.028, 1.04, 1.02, 1.035)]          # bas de la 3e (1,02) > haut de la 1re (1,01)
    z = tn.fvg(bougies)
    assert z == [{"sens": "haussière", "bas": 1.01, "haut": 1.02, "date": "2026-10-26 04:00"}]
    assert tn.fvg(bougies + [b("2026-10-26 12:00", 1.03, 1.031, 1.009, 1.012)]) == []      # comblée


def test_fvg_baissiere():
    bougies = [b("t1", 1.05, 1.06, 1.04, 1.045), b("t2", 1.044, 1.045, 1.02, 1.022), b("t3", 1.022, 1.03, 1.01, 1.015)]
    assert tn.fvg(bougies)[0] == {"sens": "baissière", "bas": 1.03, "haut": 1.04, "date": "t2"}


def _serie(valeurs):
    """Bougies dont haut = clôture + 0,001 et bas = clôture − 0,001."""
    return [b(f"2026-10-{i + 1:02d} 00:00", v, v + 0.001, v - 0.001, v) for i, v in enumerate(valeurs)]


def test_bos_haussier_puis_choch_baissier():
    #            pivot haut (1,05) en i=3, pivot bas (1,00) en i=7, cassure du haut en i=10 (BOS), puis du bas en i=15 (CHoCH)
    vals = [1.01, 1.02, 1.03, 1.05, 1.03, 1.02, 1.01, 1.00, 1.02, 1.04, 1.06, 1.07, 1.06, 1.04, 1.02, 0.99, 0.98]
    s = tn.structure(_serie(vals))
    types = [(e["type"], e["sens"]) for e in s["evenements"]]
    assert types[0] == ("BOS", "haussier") and s["evenements"][0]["niveau"] == 1.051
    assert ("CHoCH", "baissier") in types and s["tendance_structure"] == "baissière"


def test_veille_semaine_et_sessions():
    b30 = []
    for jour, base in (("2026-10-27", 1.10), ("2026-10-28", 1.20)):
        for h in range(24):
            v = base + h / 1000
            b30.append(b(f"{jour} {h:02d}:00:00", v, v + 0.0005, v - 0.0005, v))
    assert tn.veille(b30)["jour"] == "2026-10-27" and tn.veille(b30)["haut"] == approx(1.1235)
    s = tn.sessions(b30)
    assert s["Asie"]["bas"] == approx(1.1995) and s["Asie"]["haut"] == approx(1.2075)            # 00:00-07:30
    assert s["New York"]["haut"] == approx(1.2205)                                         # 12:00-20:30
    jours = [b(f"2026-10-{d:02d}", 1, 1 + d / 100, 1 - d / 100, 1) for d in (19, 20, 21, 22, 23, 26, 27)]
    assert tn.semaine_precedente(jours)["haut"] == approx(1.23) and tn.semaine_precedente(jours)["semaine"] == "2026-S43"


def test_tendance_mm50_mm200_et_hebdo():
    montee = [1 + i / 1000 for i in range(260)]
    t = tn.tendance(montee, "1 j")
    assert t["lecture"] == "haussière" and t["pente_mm50"] == "montante" and t["mm200"]
    assert tn.tendance(montee[:40], "1 j")["raison"]
    pts = [(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", 1 + i / 100) for i in range(300)]
    assert len(tn.hebdomadaires(pts)) < 60
    c = tn.calculer({}, [])
    assert c["raison"] and c["mention"].startswith("Niveaux techniques")
