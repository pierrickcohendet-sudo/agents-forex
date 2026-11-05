/* Lot V8 — Paires (maquette #paire) : paires.json (fiche, bougies, niveaux, MM20/MM50 calculées en Python), seance.json,
   tableau_macro.json (face-à-face), agenda.json (publications), rapport_jour.json (scénarios du top 3), Journal (IndexedDB). */
import { $, h, nf, sgn, esc, dfr, ddm, frTxt, nd, store, donnees, bloc, graphiqueBougies, retirerGraphique, tempsRelatif, pointFraicheur, animerChiffres } from "./v7_commun.js";

const ENG = ["Thème macro", "Politique monétaire", "Données économiques", "Politique fiscale", "Marchés", "Géopolitique", "Prix et flux", "Offre et demande"];
const CALQUES = { veille: [true, "Veille", "--c1"], semaine: [false, "Sem. précédente", "--c4"], asie: [false, "Session Asie", "--c2"], fvg: [true, "Zones FVG", "--c3"],
                  struct: [true, "BOS / CHoCH", "--ink"], events: [true, "Publications", "--down"], mm: [true, "MM20 / MM50", "--accent"] };
const FACE = ["taux_directeur", "rendement_2a", "cpi", "cpi_core", "chomage", "pib", "pmi_services"];
const CLE = "fxdesk-paire";
const dec = v => Math.abs(v) >= 20 ? 2 : 4;
const nettoyer = v => v ? String(v).replace(/\s*\[.*?\]/, "").replace(/ · .*$/, "") : null;

const SQUELETTE = `
<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between">
  <div class="seg" id="ppSel" role="group" aria-label="Mes paires"></div>
  <span class="small">Mes 6 paires · les 36 paires restent accessibles par la recherche (Ctrl+K)</span>
</div>
<div class="card pad pp-head">
  <div style="display:flex;flex-direction:column;gap:10px">
    <span class="eyebrow" id="ppEy"></span>
    <h1 id="ppT"></h1>
    <div style="display:flex;gap:8px;flex-wrap:wrap" id="ppChips"></div>
  </div>
  <div style="display:flex;flex-direction:column;gap:14px;align-items:flex-end">
    <div class="pp-px" id="ppPx"></div>
    <div class="pp-stats" id="ppStats"></div>
    <a class="btn pri pp-nouv" id="ppNouv" href="#journal">+ Nouvelle entrée</a>
  </div>
</div>
<div class="pp-grid">
  <div class="card pad" style="display:flex;flex-direction:column;gap:12px;min-width:0">
    <div class="sec-head"><div class="seg" id="tfSel" role="group" aria-label="Unité de temps"></div><div class="layers" id="layers" role="group" aria-label="Calques"></div></div>
    <div class="cc" id="cc"></div>
    <div class="src" id="ccSrc"></div>
  </div>
  <div style="display:flex;flex-direction:column;gap:14px">
    <div class="card pad" style="display:flex;flex-direction:column;gap:8px">
      <div class="sec-head"><h3>Contribution des engrenages</h3><span class="small" id="ccBC"></span></div>
      <div class="contrib" id="contrib"></div>
    </div>
    <div class="card pad" style="display:flex;flex-direction:column;gap:8px"><h3>Niveaux du jour</h3><div class="lv" id="lv"></div><span class="small" id="lvNote"></span></div>
  </div>
</div>
<div class="cols2">
  <div class="card"><div class="pad" style="padding-bottom:4px"><div class="sec-head"><h3>Face-à-face macro</h3><span class="small" id="ppPortage"></span></div></div><div class="scroll"><table class="tbl vs" id="vs"></table></div></div>
  <div class="card pad" style="display:flex;flex-direction:column;gap:12px"><h3>Lecture de la paire</h3><div id="ppRead" style="display:flex;flex-direction:column;gap:10px;font-size:14px"></div></div>
</div>
<div class="cols2">
  <div class="card" style="overflow:hidden"><div class="pad" style="padding-bottom:6px"><h3>Événements des deux devises, 7 jours</h3></div><div class="up-list" id="ppEv"></div></div>
  <div class="card" style="overflow:hidden"><div class="pad" style="padding-bottom:6px;display:flex;justify-content:space-between;align-items:baseline;gap:8px"><h3>Mes trades sur cette paire</h3><a class="small" href="#journal">Journal →</a></div><div id="ppJ"></div></div>
</div>`;

let unite = "4h", graphe = null;

export async function ecranPaire(section, parametre) {
  section.innerHTML = SQUELETTE;
  const q = s => $(s, section);
  const [P, seance, tm, agenda, rj] = await Promise.all([donnees("paires"), donnees("seance"), donnees("tableau_macro"), donnees("agenda"), donnees("rapport_jour")]);
  if (!P) { q("#ppT").textContent = "Paires indisponibles"; return; }
  const mes = P.mes_paires || [];
  const demandee = parametre && parametre.replace("-", "/").toUpperCase();
  let paire = (demandee && P.fiches?.[demandee]) ? demandee : store.get(CLE);
  if (!P.fiches?.[paire]) paire = mes[0];
  section.choisirPaire = p => { if (P.fiches?.[p]) { paire = p; rendre(); } };   // recherche rapide (Ctrl+K)

  function rendre() {
    store.set(CLE, paire);
    history.replaceState(null, "", `#paire/${paire.replace("/", "-")}`);
    const f = P.fiches[paire], m = f.macro || {}, t = f.technique || {}, base = f.base, cot = f.cotation, p = dec(t.cours || 1);
    q("#ppSel").innerHTML = [...mes, ...(mes.includes(paire) ? [] : [paire])].map(x => `<button type="button" data-p="${x}" aria-pressed="${x === paire}">${x}</button>`).join("");
    q("#ppSel").querySelectorAll("button").forEach(b => b.onclick = () => { paire = b.dataset.p; rendre(); });
    q("#ppNouv").href = `#journal/nouvelle=${paire.replace("/", "-")}`;
    bloc(q(".pp-head"), () => {
      q("#ppEy").textContent = `${base} contre ${cot} · cours du ${ddm(t.date)}`;
      q("#ppT").textContent = paire;
      const sol = m.decomposition?.solde;
      q("#ppChips").innerHTML = `<span class="chip ${sol > 0 ? "up" : sol < 0 ? "dn" : ""}"><span class="dot"></span>Solde des engrenages ${sol == null ? "n/d" : (sol > 0 ? "+" : sol < 0 ? "−" : "") + Math.abs(sol)} · ${esc(m.direction_paire || "")}</span>
        <span class="chip">${base} : ${esc(m.etats?.[base] || "n/d")}</span><span class="chip">${cot} : ${esc(m.etats?.[cot] || "n/d")}</span><span class="chip">Thème : ${esc(m.theme || "n/d")}</span>`;
      const qv = seance?.cotations?.[paire];
      q("#ppPx").innerHTML = `<b class="anim-num">${t.cours == null ? "n/d" : nf(qv?.prix ?? t.cours, p)}</b>${qv?.variation_pct != null ? `<span class="${qv.variation_pct > 0 ? "pos" : qv.variation_pct < 0 ? "neg" : "muted"}" style="font-weight:600" title="${esc(qv.source || "")} · ${esc(qv.heure_utc || "")}">${sgn(qv.variation_pct, 2, " %")} sur la séance</span>` : `<span class="muted" title="cotation de séance collectée pour les paires principales seulement">variation de séance ${nd("cotation de séance non collectée pour cette paire")}</span>`}`;
      q("#ppStats").innerHTML = [["RSI 14", t.rsi14 == null ? null : nf(t.rsi14, 1)], ["Écart MM200", t.ecart_mm200 == null ? null : sgn(t.ecart_mm200, 2, " %")],
        ["Volatilité 30 j", t.volatilite_30j == null ? null : nf(t.volatilite_30j, 1) + " %"], ["Range 20 j", t.plus_bas_20j == null ? null : nf(t.plus_bas_20j, p) + " – " + nf(t.plus_haut_20j, p)]]
        .map(x => `<div><span>${x[0]}</span><b>${x[1] ?? nd(t.raison_mm200 || "série de la paire insuffisante")}</b></div>`).join("");
    });
    dessinerGraphique(f);
    bloc(q("#contrib"), () => {
      const d = m.decomposition || {}, sol = d.solde, cc = v => v > 0 ? "p" : v < 0 ? "m" : "z", sg = v => v == null ? "n/d" : v > 0 ? "+" + v : v < 0 ? "−" + Math.abs(v) : "0";
      q("#ccBC").textContent = `${base} · ${cot} · effet`;
      q("#contrib").innerHTML = `<div class="r" style="font-size:11px;color:var(--muted);font-weight:700;letter-spacing:.06em"><span>ENGRENAGE</span><span style="text-align:center">${base}</span><span style="text-align:center">${cot}</span><span style="text-align:center">PAIRE</span></div>` +
        (d.contributions || []).map(c => `<div class="r"><span>${c.engrenage} · ${ENG[c.engrenage - 1]}</span><span class="c ${cc(c.base)}" title="${esc(c.etat_base || "")}">${sg(c.base)}</span><span class="c ${cc(c.cotation)}" title="${esc(c.etat_cotation || "")}">${sg(c.cotation)}</span><span class="c ${cc(c.contribution)}" style="font-size:13.5px">${sg(c.contribution)}</span></div>`).join("") +
        `<div class="r" style="border-top:2px solid var(--line-2)"><b>Solde</b><span></span><span></span><span class="c ${cc(sol)}" style="font-family:var(--f-display);font-size:18px;font-weight:500">${sg(sol)}</span></div>`;
    });
    bloc(q("#lv"), () => {
      const n = f.niveaux;
      if (!n || n.raison || !n.veille) { q("#lv").innerHTML = `<span>Niveaux</span><span>${nd(n?.raison || "niveaux calculés pour les 6 paires suivies (bougies du Journal)")}</span>`; q("#lvNote").textContent = ""; return; }
      const fx = v => v == null ? "—" : nf(v, p), ev = (n.structure_h4?.evenements || []).slice(-1)[0], fg = (n.fvg_h4 || [])[0];
      q("#lv").innerHTML = [["Veille haut", fx(n.veille.haut)], ["Veille bas", fx(n.veille.bas)], ["Semaine préc. haut", fx(n.semaine_precedente?.haut)], ["Semaine préc. bas", fx(n.semaine_precedente?.bas)],
        ["Asie haut – bas", n.sessions?.Asie ? fx(n.sessions.Asie.haut) + " – " + fx(n.sessions.Asie.bas) : "—"], ["Structure H4", n.structure_h4?.tendance_structure || "—"],
        ["Dernière cassure", ev ? `${ev.type} ${ev.sens} ${fx(ev.niveau)}` : "—"], ["FVG H4", fg ? `${fg.sens} ${fx(fg.bas)}–${fx(fg.haut)}` : "—"],
        ["Tendance jour", n.tendance_jour?.lecture || "—"], ["Tendance semaine", n.tendance_semaine?.lecture || "—"]].map(x => `<span>${x[0]}</span><span>${esc(x[1])}</span>`).join("");
      q("#lvNote").textContent = n.mention || "Repères, pas des signaux.";
    });
    bloc(q("#vs"), () => {
      const cel = (id, d) => tm?.cellules?.[id]?.[d]?.Actuel;
      const val = (id, d) => { const c = cel(id, d); const v = nettoyer(c?.valeur); return !c || !v || (c.etat && c.etat !== "valeur") ? nd(c?.valeur || "absent du registre") : esc(v); };
      const lib = id => (tm?.indicateurs || []).find(i => i.id === id)?.libelle || id;
      const ligne = (l, a, b) => `<tr><td>${l}</td><td><b>${a}</b></td><td><b>${b}</b></td></tr>`;
      const pt = m.portage || {}, s = m.surprises || {};
      q("#vs").innerHTML = `<thead><tr><th>Indicateur</th><th>${base}</th><th>${cot}</th></tr></thead><tbody>` +
        FACE.map(id => ligne(esc(lib(id)), val(id, base), val(id, cot))).join("") +
        ligne("Surprises 30 jours", s[base] == null ? nd("pas de publication avec consensus sur 30 jours") : sgn(s[base], 2, " σ"), s[cot] == null ? nd("pas de publication avec consensus sur 30 jours") : sgn(s[cot], 2, " σ")) +
        ligne("État", esc(m.etats?.[base] || "n/d"), esc(m.etats?.[cot] || "n/d")) +
        ligne("Prochaine réunion", pt.base?.prochaine ? dfr(pt.base.prochaine.slice(0, 10)) : nd("prochaine réunion non publiée"), pt.cotation?.prochaine ? dfr(pt.cotation.prochaine.slice(0, 10)) : nd("prochaine réunion non publiée")) + "</tbody>";
      q("#ppPortage").textContent = `Portage : écart des taux directeurs ${pt.borne === "<" ? "≥ " : pt.borne === ">" ? "≤ " : ""}${pt.directeur_pb == null ? "n/d" : sgn(pt.directeur_pb, 0, " pb")}, 2 ans ${pt.deux_ans_pb == null ? "n/d" : sgn(pt.deux_ans_pb, 0, " pb")}`;
    });
    bloc(q("#ppRead"), () => {
      const top = (rj?.watchlist_top3 || []).find(w => w.paire === paire), tw = rj?.textes?.watchlist?.[paire] || {};
      const haus = tw.haussier || top?.scenario_haussier?.texte, bais = tw.baissier || top?.scenario_baissier?.texte;
      q("#ppRead").innerHTML = (f.synthese_python || []).map(s => `<div style="display:flex;gap:8px"><span class="dot" style="color:var(--accent);margin-top:8px"></span><span>${esc(s)}</span></div>`).join("") +
        (f.synthese_modele?.texte ? `<p class="small" style="margin:0;color:var(--ink-2)">${esc(f.synthese_modele.texte)}</p>` : "") +
        (top && (haus || bais) ? `<div class="auto" style="background:var(--up-soft)"><b class="pos">Si la paire monte</b><span>${esc(haus || "")}</span></div><div class="auto" style="background:var(--down-soft)"><b class="neg">Si elle baisse</b><span>${esc(bais || "")}</span></div>` : '<span class="small">Scénarios détaillés rédigés pour les 3 paires prioritaires du jour.</span>') +
        `<div class="small">Conséquences : ${(f.consequences || []).map(c => `${c.engrenage} ${esc(c.moteur)} (${esc(c.base)})`).join(" · ") || "n/d"}</div>`;
    });
    bloc(q("#ppEv"), () => {
      const s = Date.now() / 1000, tous = [];
      for (const j of agenda?.jours || []) for (const e of j.evenements || []) if ((e.devise === base || e.devise === cot) && e.impact !== "faible" && e.iso_utc) tous.push({ ...e, d: j.date, ts: Date.parse(e.iso_utc) / 1000 });
      const fut = tous.filter(e => e.ts >= s - 6 * 3600 && e.ts <= s + 7 * 86400).sort((a, b) => a.ts - b.ts).slice(0, 9);
      q("#ppEv").innerHTML = fut.length ? fut.map(e => { const nb = { fort: 3, moyen: 2 }[e.impact] || 1;
        return `<div class="row ${e.ts < s ? "past" : ""}"><span style="font-weight:600"><span class="small" style="display:block">${ddm(e.d)}</span>${esc(e.heure_paris || "—")}</span><span class="cur">${esc(e.devise)}</span>
          <div style="display:flex;flex-direction:column;min-width:0"><b style="font-weight:600;font-size:14px">${esc(e.evenement)}</b><span class="small">${e.publie ? "Publié <b>" + esc(frTxt(e.publie)) + "</b> · " : ""}${e.votes ? esc(e.votes) : `${e.consensus ? "attendu " + esc(frTxt(e.consensus)) + " · " : ""}${e.precedent ? "précédent " + esc(frTxt(e.precedent)) : esc(e.type || "")}`}</span></div>
          <span class="when"><span class="imp ${e.impact}" style="justify-content:flex-end;margin-bottom:4px">${[1, 2, 3].map(i => `<i class="${i <= nb ? "on" : ""}" style="${i > nb ? "opacity:.35" : ""}"></i>`).join("")}</span><span>${tempsRelatif(e.ts - s)}</span></span></div>`; }).join("")
        : '<div class="empty">Rien de moyen ou fort sur 7 jours.</div>';
    });
    mesTrades();
    pointFraicheur(q(".pp-head .eyebrow"), "paires");
    animerChiffres(section);
  }

  async function mesTrades() {
    const zone = q("#ppJ");
    try {
      const [{ lireNotes }, { versTrade }] = await Promise.all([import("./journal.js"), import("./journal_stats.js")]);
      const tr = (await lireNotes()).map(versTrade).filter(t => t && t.p === paire).sort((a, b) => String(b.iso).localeCompare(String(a.iso))).slice(0, 6);
      zone.innerHTML = tr.length ? `<table class="tbl"><tbody>${tr.map(x => `<tr><td>${ddm(x.d)}</td><td>${esc(x.sens || "—")}</td><td class="small">${esc(x.sess || "")}${x.conf != null ? ` · ${x.conf} confluences` : ""}${x.theme === true ? " · avec le thème" : x.theme === false ? " · contre le thème" : ""}</td><td class="n ${x.r >= 0 ? "pos" : "neg"}"><b>${x.r == null ? nd("résultat en R absent et risque prévu inconnu") : sgn(x.r, 1, " R")}</b></td></tr>`).join("")}</tbody></table>`
        : `<div class="empty">Aucun trade clôturé sur ${paire}. <a href="#journal/nouvelle=${paire.replace("/", "-")}">Nouvelle entrée</a></div>`;
    } catch (e) { zone.innerHTML = `<div class="empty">Journal indisponible sur cet appareil (${esc(e.message)}).</div>`; }
  }

  function dessinerGraphique(f) {
    const ch = f.chandeliers, n = f.niveaux || {};
    q("#tfSel").innerHTML = [["30min", "30 min"], ["4h", "4 h"], ["1j", "1 jour"]].map(x => `<button type="button" data-t="${x[0]}" aria-pressed="${x[0] === unite}">${x[1]}</button>`).join("");
    q("#tfSel").querySelectorAll("button").forEach(b => b.onclick = () => { unite = b.dataset.t; dessinerGraphique(f); });
    q("#layers").innerHTML = Object.entries(CALQUES).filter(([k]) => k !== "mm" || unite === "1j").map(([k, v]) => `<button type="button" class="layer" data-k="${k}" aria-pressed="${v[0]}"><i style="background:var(${v[2]})"></i>${v[1]}</button>`).join("");
    q("#layers").querySelectorAll(".layer").forEach(b => b.onclick = () => { CALQUES[b.dataset.k][0] = !CALQUES[b.dataset.k][0]; dessinerGraphique(f); });
    retirerGraphique(graphe); graphe = null;
    const u = ch?.[unite], bg = u?.bougies;
    if (!bg?.length) { q("#cc").innerHTML = `<div class="empty">${esc(ch?.raison || "Bougies collectées pour les 6 paires suivies : choisis l'une d'elles pour le graphique en bougies.")}</div>`; q("#ccSrc").textContent = ""; return; }
    const p = dec(bg[0][4]), L = CALQUES, lignes = [], marqueurs = [];
    if (L.veille[0] && n.veille) lignes.push({ prix: n.veille.haut, couleur: "--c1", titre: "Veille H" }, { prix: n.veille.bas, couleur: "--c1", titre: "Veille B" });
    if (L.semaine[0] && n.semaine_precedente) lignes.push({ prix: n.semaine_precedente.haut, couleur: "--c4", titre: "Sem. H" }, { prix: n.semaine_precedente.bas, couleur: "--c4", titre: "Sem. B" });
    if (L.asie[0] && n.sessions?.Asie) lignes.push({ prix: n.sessions.Asie.haut, couleur: "--c2", titre: "Asie H", style: 3 }, { prix: n.sessions.Asie.bas, couleur: "--c2", titre: "Asie B", style: 3 });
    if (L.fvg[0]) for (const z of (unite === "30min" ? n.fvg_m30 : n.fvg_h4 || []) || [] ) { if (lignes.filter(l => /FVG/.test(l.titre)).length >= 2) break; lignes.push({ prix: z.haut, couleur: "--c3", titre: "FVG " + (z.sens?.[0] === "h" ? "▲" : "▼"), style: 1 }, { prix: z.bas, couleur: "--c3", titre: "", style: 1 }); }
    const ts = s => Math.floor(Date.parse(String(s).replace(" ", "T") + "Z") / 1000);
    if (L.struct[0] && unite !== "1j") for (const e of n.structure_h4?.evenements || []) marqueurs.push({ ts: ts(e.date), position: e.sens === "haussier" ? "belowBar" : "aboveBar", couleur: e.sens === "haussier" ? "--up" : "--down", forme: e.sens === "haussier" ? "arrowUp" : "arrowDown", texte: e.type });
    if (L.events[0] && unite !== "1j") for (const j of agenda?.jours || []) for (const e of j.evenements || []) if ((e.devise === f.base || e.devise === f.cotation) && e.impact === "fort" && e.iso_utc) marqueurs.push({ ts: Date.parse(e.iso_utc) / 1000, couleur: "--warn", texte: `${e.devise} ${e.heure_paris}` });
    const courbes = unite === "1j" && L.mm[0] ? [["mm20", "--c2", "MM20"], ["mm50", "--accent", "MM50"]].filter(([k]) => u[k]).map(([k, c, t]) => ({ points: u[k], couleur: c, titre: t })) : [];
    requestAnimationFrame(async () => { graphe = await graphiqueBougies(q("#cc"), bg, p, { marqueurs, lignesPrix: lignes, courbes }); });
    q("#ccSrc").textContent = `${u.source || "Bougies Twelve Data"}, heures de Paris · niveaux et moyennes mobiles calculés en Python à chaque run : des repères, pas des signaux.`;
  }
  rendre();
}
