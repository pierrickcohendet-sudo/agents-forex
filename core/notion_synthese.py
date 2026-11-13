"""Copie Notion de la Synthèse V9 (lot V9, D4) : même structure que le site (13 sections numérotées), dans les limites
de l'API Notion (2 000 caractères par texte : core/notion_blocks.decouper ; 100 blocs par ajout : lots ; tableaux de
100 lignes au plus). Graphiques remplacés par leurs chiffres (tableaux) ; liens vers les sources officielles.
"""
from __future__ import annotations

from core import notion_blocks as nb
from core.synthese_v9 import ddm, fr


def _texte(s: dict, sid: str) -> list[dict]:
    r = (s.get("redaction") or {}).get(sid) or {}
    blocs = [nb.paragraphe([nb.rt(p)]) for p in (s.get("textes") or {}).get(sid) or []]
    blocs.append(nb.paragraphe_gris(f"Rédaction : {r.get('libelle', 'rédaction automatique')}"))
    return blocs


def blocs_v94(s: dict) -> list[dict]:
    """Structure V9.4 : mêmes sections que le site (tronc, pays du jour, énergie, actions, calendrier, classement, paires,
    scénarios, méthode, conclusion), textes et tableaux principaux."""
    f = s.get("faits") or {}
    x = f.get("exec") or {}
    blocs = [nb.callout([nb.rt("Biais du jour : ", gras=True), nb.rt(f"{x.get('biais', 'n/d')}. "), nb.rt("Facteur dominant : ", gras=True),
                         nb.rt(f"{x.get('facteur_dominant', 'n/d')}. "), nb.rt("Risque majeur : ", gras=True),
                         nb.rt(f"{(x.get('risque_majeur') or {}).get('texte', 'n/d')}.")], "🧭", "gray_background"),
             nb.paragraphe_gris(f"{s.get('jour', '')} · {s.get('semaine', '')} · {s.get('mention', '')}")]
    for sec in s.get("sections") or []:
        sid, t = sec["id"], sec["type"]
        blocs.append(nb.titre(2, f"{sec['numero']}. {sec['titre']}"))
        blocs += _texte(s, sid)
        try:
            if t == "marches":
                blocs.append(nb.tableau(["Actif", "Situation", "Interprétation"],
                                        [[c["actif"], f"{c['situation']} ({c['texte']})", c["interpretation"]] for c in (f[sid].get("classes") or [])]))
            elif t in ("pays", "etats_unis"):
                p = f[sid]
                blocs += [nb.puce([nb.rt(x)]) for x in p.get("faits") or []]
                blocs.append(nb.paragraphe([nb.rt("Mon biais : ", gras=True), nb.rt(p.get("mon_biais", ""))]))
                for c in (p.get("usd") or {}).get("ce_que_je_veux_voir") or []:
                    blocs.append(nb.puce([nb.rt(("✓ " if c.get("remplie") else "○ ") + c["texte"])]))
            elif t == "calendrier":
                blocs.append(nb.tableau(["Heure", "Devise", "Publication", "Prévision", "Précédent"],
                                        [[e.get("heure") or "", e["devise"], e.get("evenement") or "", e.get("consensus") or "—", e.get("precedent") or "—"]
                                         for e in f[sid].get("aujourdhui") or []][:60] or [["—", "—", "Aucune publication", "—", "—"]]))
            elif t == "classement":
                blocs.append(nb.tableau(["Rang", "Devise", "Biais", "Score", "Moteur principal"],
                                        [[l["rang"], l["devise"], l["biais"], fr(l["score"], 2, True), l["moteur"]] for l in f[sid].get("devises") or []]))
            elif t == "conclusion":
                blocs.append(nb.tableau(["Indicateur", "Valeur", "Ce que je veux observer"],
                                        [[i["indicateur"], f"{i['valeur']} ({ddm(i.get('date'))})", i["observer"]] for i in f[sid].get("indicateurs") or []]))
                blocs += [nb.puce([nb.rt(f"{src['nom']} : ", gras=True), {"type": "text", "text": {"content": src["quoi"][:1900], "link": {"url": src["url"]}}}])
                          for src in f[sid].get("sources") or [] if src.get("url")]
        except Exception as exc:  # noqa: BLE001
            blocs.append(nb.paragraphe_gris(f"Détail indisponible : {exc}"))
    return blocs


def blocs_synthese(s: dict) -> list[dict]:
    if s.get("structure") == "v9.4":
        return blocs_v94(s)
    f = s.get("faits") or {}
    x1 = f.get("s1") or {}
    blocs = [nb.callout([nb.rt("Diagnostic du jour : ", gras=True), nb.rt(f"{x1.get('biais', 'n/d')}. "),
                         nb.rt("Régime : ", gras=True), nb.rt(f"{x1.get('regime', 'n/d')}. "),
                         nb.rt("Point déterminant : ", gras=True), nb.rt(f"{x1.get('point_determinant', 'n/d')}.")], "🧭", "gray_background"),
             nb.paragraphe_gris(f"{s.get('jour', '')} · {s.get('semaine', '')} · {s.get('mention', '')}")]
    for sec in s.get("sections") or []:
        sid = sec["id"]
        blocs.append(nb.titre(2, f"{sec['numero']}. {sec['titre']}"))
        blocs += _texte(s, sid)
        try:
            blocs += _specifique(sid, f)
        except Exception as exc:  # noqa: BLE001 — une section en panne ne casse pas les autres
            blocs.append(nb.paragraphe_gris(f"Détail indisponible : {exc}"))
    return blocs


def _specifique(sid: str, f: dict) -> list[dict]:
    if sid == "s1":
        fed = (f.get("s1") or {}).get("fed") or {}
        b = [nb.puce([nb.rt(f"{t['titre']} : ", gras=True), nb.rt(t["texte"])]) for t in (f.get("s1") or {}).get("themes") or []]
        b.append(nb.paragraphe([nb.rt(f"{fed.get('titre', 'Probabilité de la Fed')} : ", gras=True),
                                nb.rt(fed.get("texte", "n/d") + (f" ({fed.get('source')})" if fed.get("valeur") is not None else f" ({fed.get('raison')})"))]))
        for a in (f.get("s1") or {}).get("actualites") or []:
            b.append(nb.puce([nb.rt(f"{a['theme_libelle']} · ", gras=True), nb.rt(a["titre"]), nb.rt(f" — {a.get('source')}, {ddm(a.get('date'))}")]))
        return b
    if sid == "s2":
        lignes = [[m["libelle"], m.get("texte", "n/d"), ddm(m.get("date")) + (" (en retard)" if m.get("retard") else ""),
                   fr(m.get("variation_5"), 2, True) if m.get("variation_5") is not None else "n/d", m.get("lecture") or m.get("raison") or ""]
                  for m in (f.get("s2") or {}).get("marches") or []]
        return [nb.tableau(["Marché", "Dernière observation", "Date", "5 séances", "Lecture"], lignes),
                nb.paragraphe([nb.rt("Lecture cross-asset : ", gras=True), nb.rt(((f.get("s2") or {}).get("mecanisme") or {}).get("phrase", ""))])]
    if sid == "s3":
        x = f.get("s3") or {}
        b = [nb.paragraphe([nb.rt("Chaîne de causalité : ", gras=True), nb.rt(" → ".join(c["texte"] for c in x.get("chaine") or []))])]
        pro = f.get("prochain") or {}
        if pro:
            b.append(nb.paragraphe([nb.rt(f"Lire le chiffre clé ({pro.get('cle') or pro.get('evenement')}) :", gras=True)]))
            b += [nb.puce([nb.rt(f"{c['si']} : ", gras=True), nb.rt(c["lecture"])]) for c in (pro.get("lire") or {}).get("cas") or []]
        return b
    if sid == "s4":
        x = f.get("s4") or {}
        b = [nb.tableau(["Banque", "Taux", "Dernière décision", "Prochaine", "Lecture"],
                        [[l["banque"], l["taux_texte"], l["derniere_texte"], ddm(l.get("prochaine")), l["lecture"]] for l in x.get("banques") or []])]
        b += [nb.puce([nb.rt(f"{c['devise']} ({c['etat']}) : ", gras=True), nb.rt(c["texte"])]) for c in x.get("cartes") or []]
        return b
    if sid == "s5":
        br = (f.get("s5") or {}).get("brent") or {}
        return [nb.paragraphe([nb.rt(br.get("alerte") or "Brent : dernière valeur officielle à jour.")])] if br else []
    if sid == "s7":
        x = f.get("s7") or {}
        return [nb.tableau(["Jour", "Heure", "Devise", "Publication", "Consensus", "Précédent"],
                           [[ddm(j["date"]), e.get("heure") or "", e["devise"], e.get("evenement") or "", e.get("consensus") or "—", e.get("precedent") or "—"]
                            for j in x.get("jours") or [] for e in j.get("evenements") or []][:90])]
    if sid == "s8":
        return [nb.tableau(["Rang", "Devise", "Biais", "Score", "Moteur principal"],
                           [[l["rang"], l["devise"], l["biais"], fr(l["score"], 2, True), l["moteur"]] for l in (f.get("s8") or {}).get("devises") or []])]
    if sid == "s9":
        b = []
        for p in (f.get("s9") or {}).get("paires") or []:
            b.append(nb.titre(3, f"{p['paire']} · {p['biais']} · {p.get('priorite') or ''}"))
            b += [nb.puce([nb.rt(a)]) for a in p.get("arguments") or []]
            b.append(nb.paragraphe([nb.rt("Hausse si ", gras=True), nb.rt(p["hausse_si"]), nb.rt(" · Baisse si ", gras=True), nb.rt(p["baisse_si"])]))
        return b
    if sid == "s10":
        x = f.get("s10") or {}
        if not x.get("disponible"):
            return []
        return [nb.tableau(["Niveau", "Zone", "Contacts", "Distance (pips)"],
                           [[n["court"], n["texte"], n.get("contacts"), fr(n.get("distance_pips"), 0, True)] for n in x.get("niveaux") or []])]
    if sid == "s11":
        b = []
        for sc in (f.get("s11") or {}).get("scenarios") or []:
            b.append(nb.titre(3, f"{sc['lettre']} · {sc['titre']} ({sc['chip']}, {sc.get('remplies')}/{sc.get('total')})"))
            b += [nb.puce([nb.rt(("✓ " if c.get("remplie") else "○ ") + (c.get("texte") or ""))]) for c in sc.get("conditions") or []]
        return b
    if sid == "s12":
        return [nb.tableau(["Priorité", "Paire", "Biais", "Catalyseur"],
                           [[r["rang"], r["paire"], r["biais"], r["catalyseur"]] for r in (f.get("s12") or {}).get("priorites") or []])]
    if sid == "s13":
        x = f.get("s13") or {}
        b = [nb.puce([nb.rt(p)]) for p in x.get("priorites") or []]
        b.append(nb.paragraphe([nb.rt(x.get("prudence") or "")]))
        b += [nb.puce([nb.rt(f"{src['nom']} : ", gras=True), {"type": "text", "text": {"content": src["quoi"][:1900], "link": {"url": src["url"]}}}])
              for src in x.get("sources") or [] if src.get("url")]
        return b
    return []
