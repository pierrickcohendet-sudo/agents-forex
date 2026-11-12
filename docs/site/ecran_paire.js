/* Lot V8 / V8.2 — Paires (maquette #paire) : paires.json (sélecteur, fiche), paires/XXX-YYY.json (bougies, RSI, zones,
   lignes de tendance, divergences, niveaux, écart de taux : tout calculé en Python), seance.json, tableau_macro.json
   (face-à-face), agenda.json (publications), rapport_jour.json (scénarios du top 3), Journal (IndexedDB). */
import { $, h, nf, sgn, esc, dfr, ddm, frTxt, nd, store, donnees, bloc, tempsRelatif, pointFraicheur, animerChiffres } from "./v7_commun.js";
import { graphiquePaire, graphiqueEcart } from "./paire_graphique.js";

const ENG = ["Thème macro", "Politique monétaire", "Données économiques", "Politique fiscale", "Marchés", "Géopolitique", "Prix et flux", "Offre et demande"];
/* Calques, dans l'ordre de la page (lot V8.2) : [actif par défaut, libellé, couleur] ; choix mémorisés dans le navigateur */
const CALQUES = { veille: [true, "Veille", "--c1"], semaine: [false, "Semaine précédente", "--c4"], asie: [false, "Session Asie", "--c2"],
                  sr: [true, "Supports et résistances", "--down"], tendance: [true, "Lignes de tendance", "--up"], fvg: [false, "Zones FVG", "--c3"],
                  struct: [true, "BOS et CHoCH", "--ink"], events: [true, "Publications", "--warn"], mm: [true, "Moyennes mobiles", "--accent"], rsi: [true, "RSI", "--accent"] };
const CLE_CALQUES = "fxdesk-calques";
try { const m = JSON.parse(store.get(CLE_CALQUES) || "{}"); for (const k in m) if (CALQUES[k]) CALQUES[k][0] = !!m[k]; } catch (e) { /* préférence illisible : défauts */ }
const memoriserCalques = () => store.set(CLE_CALQUES, JSON.stringify(Object.fromEntries(Object.entries(CALQUES).map(([k, v]) => [k, v[0]]))));
const FACE = ["taux_directeur", "rendement_2a", "cpi", "cpi_core", "chomage", "pib", "pmi_services"];
const CLE = "fxdesk-paire";
const dec = v => Math.abs(v) >= 20 ? 2 : 4;
const nettoyer = v => v ? String(v).replace(/\s*\[.*?\]/, "").replace(/ · .*$/, "") : null;
const UNITES = [["30min", "30 min"], ["4h", "4 h"], ["1j", "1 jour"]];
const PERIODES = [["3m", "3 mois", 92], ["6m", "6 mois", 183], ["1a", "1 an", 366]];

const SQUELETTE = `
<div class="pp-sel">
  <label class="small" for="ppSel">Paire</label>
  <select id="ppSel" class="pp-menu" aria-label="Choisir une paire (cours et variation du jour)"></select>
  <span class="small">ou Ctrl+K · bougies 4 h et 1 jour pour les 36 paires, 30 min pour les paires suivies</span>
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
<div class="card pad pp-graph">
  <div class="sec-head"><div class="seg" id="tfSel" role="group" aria-label="Unité de temps"></div><span class="small" id="ccMention"></span></div>
  <div class="layers" id="layers" role="group" aria-label="Calques"></div>
  <div class="cc" id="cc"></div>
  <div class="cc-rsi" id="ccRsi" aria-label="RSI 14 synchronisé avec le graphique"></div>
  <div class="pp-legende small" id="ccLeg"></div>
  <div class="src" id="ccSrc"></div>
</div>
<div class="card pad pp-ecart" id="ecart">
  <div class="sec-head"><div><h3>Écart de taux</h3><span class="small" id="ecSous"></span></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap"><div class="seg" id="ecMat" role="group" aria-label="Maturité"></div><div class="seg" id="ecPer" role="group" aria-label="Période"></div></div></div>
  <div class="ec-kpi" id="ecKpi"></div>
  <p class="ec-phrase" id="ecPhrase"></p>
  <div class="ec-haut" id="ecHaut"></div><div class="ec-bas" id="ecBas"></div>
  <div class="src" id="ecSrc"></div>
</div>
<div class="cols2">
  <div class="card pad" style="display:flex;flex-direction:column;gap:8px">
    <div class="sec-head"><h3>Contribution des engrenages</h3><span class="small" id="ccBC"></span></div>
    <div class="contrib" id="contrib"></div>
  </div>
  <div class="card pad" style="display:flex;flex-direction:column;gap:8px"><h3>Niveaux du jour</h3><div class="lv" id="lv"></div><div class="lv lv-zones" id="lvZ"></div><span class="small" id="lvNote"></span></div>
</div>
<div class="cols2">
  <div class="card"><div class="pad" style="padding-bottom:4px"><div class="sec-head"><h3>Face-à-face macro</h3><span class="small" id="ppPortage"></span></div></div><div class="scroll"><table class="tbl vs" id="vs"></table></div></div>
  <div class="card pad" style="display:flex;flex-direction:column;gap:12px"><h3>Lecture de la paire</h3><div id="ppRead" style="display:flex;flex-direction:column;gap:10px;font-size:14px"></div></div>
</div>
<div class="cols2">
  <div class="card" style="overflow:hidden"><div class="pad" style="padding-bottom:6px"><h3>Événements des deux devises, 7 jours</h3></div><div class="up-list" id="ppEv"></div></div>
  <div class="card" style="overflow:hidden"><div class="pad" style="padding-bottom:6px;display:flex;justify-content:space-between;align-items:baseline;gap:8px"><h3>Mes trades sur cette paire</h3><a class="small" href="#journal">Journal →</a></div><div id="ppJ"></div></div>
</div>`;

let unite = "4h", graphe = null, grEcart = null, tourGraphe = 0, tourEcart = 0, maturite = null, periode = "6m";

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
  const G = P.groupes || { suivies: mes, majeures: [], croisees: (P.paires || []).filter(x => !mes.includes(x)) };
  const etiquette = x => { const c = P.fiches[x]?.cours_jour || {}; return c.cours == null ? `${x} · n/d` : `${x} · ${nf(c.cours, dec(c.cours))}${c.variation_pct == null ? "" : " · " + sgn(c.variation_pct, 2, " %")}`; };
  q("#ppSel").innerHTML = [["Mes paires", G.suivies], ["Majeures", G.majeures], ["Croisées", G.croisees]].filter(([, l]) => l?.length)
    .map(([t, l]) => `<optgroup label="${t}">${l.map(x => `<option value="${x}">${esc(etiquette(x))}</option>`).join("")}</optgroup>`).join("");
  q("#ppSel").onchange = e => { paire = e.target.value; rendre(); };

  async function rendre() {
    store.set(CLE, paire);
    history.replaceState(null, "", `#paire/${paire.replace("/", "-")}`);
    q("#ppSel").value = paire;
    const leger = P.fiches[paire];
    const detail = await donnees(leger.detail ? leger.detail.replace(/\.json$/, "") : "paires/" + paire.replace("/", "-"));
    if (paire !== leger.paire) return;
    const f = { ...leger, ...(detail || {}), raison_detail: detail ? null : "détail de la paire indisponible (fichier absent)" };
    const m = f.macro || {}, t = f.technique || {}, base = f.base, cot = f.cotation, p = dec(t.cours || f.cours_jour?.cours || 1);
    q("#ppNouv").href = `#journal/nouvelle=${paire.replace("/", "-")}`;
    bloc(q(".pp-head"), () => {
      q("#ppEy").textContent = `${base} contre ${cot} · cours du ${ddm(t.date)}`;
      q("#ppT").textContent = paire;
      const sol = m.decomposition?.solde;
      q("#ppChips").innerHTML = `<span class="chip ${sol > 0 ? "up" : sol < 0 ? "dn" : ""}"><span class="dot"></span>Solde des engrenages ${sol == null ? "n/d" : (sol > 0 ? "+" : sol < 0 ? "−" : "") + Math.abs(sol)} · ${esc(m.direction_paire || "")}</span>
        <span class="chip">${base} : ${esc(m.etats?.[base] || "n/d")}</span><span class="chip">${cot} : ${esc(m.etats?.[cot] || "n/d")}</span><span class="chip">Thème : ${esc(m.theme || "n/d")}</span>`;
      const cj = f.cours_jour || {}, prix = cj.cours ?? t.cours;
      q("#ppPx").innerHTML = `<b class="anim-num">${prix == null ? "n/d" : nf(prix, p)}</b>${cj.variation_pct != null ? `<span class="${cj.variation_pct > 0 ? "pos" : cj.variation_pct < 0 ? "neg" : "muted"}" style="font-weight:600" title="${esc(cj.source || "")} · ${esc(cj.heure || "")}">${sgn(cj.variation_pct, 2, " %")} sur le jour</span>` : `<span class="muted">variation du jour ${nd(cj.raison || "cotation absente")}</span>`}`;
      const r = f.rsi || {};
      q("#ppStats").innerHTML = [["RSI 14 · 4 h", r["4h"] == null ? null : nf(r["4h"], 1)], ["RSI 14 · 1 j", r["1j"] == null ? (t.rsi14 == null ? null : nf(t.rsi14, 1)) : nf(r["1j"], 1)], ["Écart MM200", t.ecart_mm200 == null ? null : sgn(t.ecart_mm200, 2, " %")],
        ["Volatilité 30 j", t.volatilite_30j == null ? null : nf(t.volatilite_30j, 1) + " %"], ["Range 20 j", t.plus_bas_20j == null ? null : nf(t.plus_bas_20j, p) + " – " + nf(t.plus_haut_20j, p)]]
        .map(x => `<div><span>${x[0]}</span><b>${x[1] ?? nd(/RSI/.test(x[0]) ? "bougies de cette unité non collectées" : t.raison_mm200 || "série de la paire insuffisante")}</b></div>`).join("");
    });
    dessinerGraphique(f);
    bloc(q("#ecart"), () => dessinerEcart(f));
    bloc(q("#contrib"), () => {
      const d = m.decomposition || {}, sol = d.solde, cc = v => v > 0 ? "p" : v < 0 ? "m" : "z", sg = v => v == null ? "n/d" : v > 0 ? "+" + v : v < 0 ? "−" + Math.abs(v) : "0";
      q("#ccBC").textContent = `${base} · ${cot} · effet`;
      q("#contrib").innerHTML = `<div class="r" style="font-size:11px;color:var(--muted);font-weight:700;letter-spacing:.06em"><span>ENGRENAGE</span><span style="text-align:center">${base}</span><span style="text-align:center">${cot}</span><span style="text-align:center">PAIRE</span></div>` +
        (d.contributions || []).map(c => `<div class="r"><span>${c.engrenage} · ${ENG[c.engrenage - 1]}</span><span class="c ${cc(c.base)}" title="${esc(c.etat_base || "")}">${sg(c.base)}</span><span class="c ${cc(c.cotation)}" title="${esc(c.etat_cotation || "")}">${sg(c.cotation)}</span><span class="c ${cc(c.contribution)}" style="font-size:13.5px">${sg(c.contribution)}</span></div>`).join("") +
        `<div class="r" style="border-top:2px solid var(--line-2)"><b>Solde</b><span></span><span></span><span class="c ${cc(sol)}" style="font-family:var(--f-display);font-size:18px;font-weight:500">${sg(sol)}</span></div>`;
    });
    bloc(q("#lv"), () => {
      const n = f.niveaux || {}, fx = v => v == null ? "—" : nf(v, p);
      if (!n.veille && !n.semaine_precedente) { q("#lv").innerHTML = `<span>Niveaux</span><span>${nd(n.raison || f.raison_detail || "bougies non collectées pour cette paire")}</span>`; }
      else {
        const ev = (n.structure_h4?.evenements || []).slice(-1)[0], fg = (n.fvg_h4 || [])[0];
        q("#lv").innerHTML = [["Veille haut", fx(n.veille?.haut)], ["Veille bas", fx(n.veille?.bas)], ["Semaine préc. haut", fx(n.semaine_precedente?.haut)], ["Semaine préc. bas", fx(n.semaine_precedente?.bas)],
          ["Asie haut – bas", n.sessions?.Asie ? fx(n.sessions.Asie.haut) + " – " + fx(n.sessions.Asie.bas) : "—"], ["Structure H4", n.structure_h4?.tendance_structure || "—"],
          ["Dernière cassure", ev ? `${ev.type} ${ev.sens} ${fx(ev.niveau)}` : "—"], ["FVG H4", fg ? `${fg.sens} ${fx(fg.bas)}–${fx(fg.haut)}` : "—"],
          ["Tendance jour", n.tendance_jour?.lecture || "—"], ["Tendance semaine", n.tendance_semaine?.lecture || "—"]].map(x => `<span>${x[0]}</span><span>${esc(x[1])}</span>`).join("");
      }
      // Lot V8.2 : zones de supports et résistances (4 h et 1 jour), distance au cours en pips et en %
      const lignes = [];
      for (const [u, lib] of [["4h", "4 h"], ["1j", "1 j"]]) {
        const z = f.chandeliers?.[u]?.analyse?.zones;
        if (!z || z.raison) continue;
        for (const x of [...[...z.resistances].reverse(), ...z.supports])
          lignes.push(`<span><b class="${x.cote === "resistance" ? "neg" : "pos"}">${x.nom}</b> ${lib} · ${x.contacts} contact${x.contacts > 1 ? "s" : ""}</span><span title="dernier contact ${esc(ddm(x.dernier_contact))} · force ${x.force}/3">${fx(x.bas)}${x.haut !== x.bas ? "–" + fx(x.haut) : ""} · ${sgn(x.distance_pips, 0, " pips")} (${sgn(x.distance_pct, 2, " %")})</span>`);
      }
      q("#lvZ").innerHTML = lignes.length ? `<span class="lv-titre">Supports et résistances</span><span></span>${lignes.join("")}` : "";
      q("#lvNote").textContent = (P.mention_reperes || n.mention || "Repères, pas des signaux.");
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
    const ch = f.chandeliers || {}, n = f.niveaux || {};
    const dispo = u => !!ch[u]?.bougies?.length;
    if (!dispo(unite)) unite = ["4h", "1j", "30min"].find(dispo) || unite;
    q("#tfSel").innerHTML = UNITES.map(x => `<button type="button" data-t="${x[0]}" aria-pressed="${x[0] === unite}" ${dispo(x[0]) ? "" : `disabled title="${esc(x[0] === "30min" && !f.suivie ? "30 min : réservées aux paires suivies (config.yaml, journal.mes_paires)" : ch[x[0]]?.raison || ch.raison || "non collectées")}"`}>${x[1]}</button>`).join("");
    q("#tfSel").querySelectorAll("button:not([disabled])").forEach(b => b.onclick = () => { unite = b.dataset.t; dessinerGraphique(f); });
    q("#layers").innerHTML = Object.entries(CALQUES).map(([k, v]) => `<button type="button" class="layer" data-k="${k}" aria-pressed="${v[0]}"><i style="background:var(${v[2]})"></i>${v[1]}</button>`).join("");
    q("#layers").querySelectorAll(".layer").forEach(b => b.onclick = () => { CALQUES[b.dataset.k][0] = !CALQUES[b.dataset.k][0]; memoriserCalques(); dessinerGraphique(f); });
    graphe?.retirer(); graphe = null; tourGraphe++;
    const u = ch[unite], bg = u?.bougies;
    q("#ccRsi").hidden = true; q("#ccLeg").innerHTML = ""; q("#cc").classList.toggle("vide", !bg?.length);
    if (!bg?.length) { q("#cc").innerHTML = `<div class="empty">${esc(ch.raison || f.raison_detail || "Bougies non collectées pour cette paire.")}</div>`; q("#ccSrc").textContent = ""; q("#ccMention").textContent = ""; return; }
    const p = dec(bg[0][4]), L = CALQUES, lignes = [], marqueurs = [], an = u.analyse || {};
    if (L.veille[0] && n.veille) lignes.push({ prix: n.veille.haut, couleur: "--c1", titre: "Veille H" }, { prix: n.veille.bas, couleur: "--c1", titre: "Veille B" });
    if (L.semaine[0] && n.semaine_precedente) lignes.push({ prix: n.semaine_precedente.haut, couleur: "--c4", titre: "Sem. H" }, { prix: n.semaine_precedente.bas, couleur: "--c4", titre: "Sem. B" });
    if (L.asie[0] && n.sessions?.Asie) lignes.push({ prix: n.sessions.Asie.haut, couleur: "--c2", titre: "Asie H", style: 3 }, { prix: n.sessions.Asie.bas, couleur: "--c2", titre: "Asie B", style: 3 });
    if (L.fvg[0]) for (const z of (unite === "30min" ? n.fvg_m30 : n.fvg_h4) || []) { if (lignes.filter(l => /FVG/.test(l.titre)).length >= 2) break; lignes.push({ prix: z.haut, couleur: "--c3", titre: "FVG " + (z.sens?.[0] === "h" ? "▲" : "▼"), style: 1 }, { prix: z.bas, couleur: "--c3", titre: "", style: 1 }); }
    const ts = s => Math.floor(Date.parse(String(s).replace(" ", "T") + "Z") / 1000);
    if (L.struct[0] && unite !== "1j") for (const e of n.structure_h4?.evenements || []) marqueurs.push({ ts: ts(e.date), position: e.sens === "haussier" ? "belowBar" : "aboveBar", couleur: e.sens === "haussier" ? "--up" : "--down", forme: e.sens === "haussier" ? "arrowUp" : "arrowDown", texte: e.type });
    if (L.events[0] && unite !== "1j") for (const j of agenda?.jours || []) for (const e of j.evenements || []) if ((e.devise === f.base || e.devise === f.cotation) && e.impact === "fort" && e.iso_utc) marqueurs.push({ ts: Date.parse(e.iso_utc) / 1000, couleur: "--warn", texte: `${e.devise} ${e.heure_paris}` });
    const courbes = L.mm[0] ? [["mm20", "--c2", "MM20"], ["mm50", "--accent", "MM50"]].filter(([k]) => u[k]).map(([k, c, t]) => ({ points: u[k], couleur: c, titre: t })) : [];
    // Zones : celles de l'unité (4 h, 1 jour) ; en 30 min, celles du 4 h
    const zs = (unite === "30min" ? ch["4h"]?.analyse?.zones : an.zones);
    const zones = L.sr[0] && zs && !zs.raison ? [...zs.resistances, ...zs.supports] : [];
    const lt = an.lignes || {}, tendances = L.tendance[0] ? [lt.support, lt.resistance].filter(l => l && l.visible) : [];
    const rsi = L.rsi[0] ? u.rsi14 : null;
    q("#ccRsi").hidden = !rsi;
    q("#ccMention").textContent = u.mention ? `${u.mention} (budget Twelve Data ou échec de collecte)` : "";
    const leg = [];
    if (L.tendance[0]) for (const [l, nom, raison] of [[lt.support, "Support haussier", lt.raison_support], [lt.resistance, "Résistance baissière", lt.raison_resistance]])
      if (unite !== "30min") leg.push(l ? `<span><b class="${l.sens === "support" ? "pos" : "neg"}">${nom}</b> : ${esc(l.texte)}, ${sgn(l.pente_pips_jour, 1, " pips/jour")}${l.visible ? "" : " (masquée : cassée depuis plus de 5 bougies)"}</span>` : `<span class="muted" title="${esc(raison || "")}">${nom} : aucune</span>`);
    if (L.rsi[0]) {
      leg.push(`<span>RSI 14 : <b>${an.rsi_actuel == null ? "n/d" : nf(an.rsi_actuel, 1)}</b></span>`);
      for (const d of an.divergences || []) leg.push(`<span class="${d.sens === "baissière" ? "neg" : "pos"}" title="${esc(d.texte)}">${esc(d.texte)}</span>`);
      if (!(an.divergences || []).length) leg.push('<span class="muted">aucune divergence confirmée</span>');
    }
    q("#ccLeg").innerHTML = leg.join("");
    const jeton = ++tourGraphe;   // deux rendus rapprochés (changement de paire) : seul le dernier garde son graphique
    requestAnimationFrame(async () => {
      if (jeton !== tourGraphe) return;
      const g = await graphiquePaire(q("#cc"), q("#ccRsi"), bg, { dec: p, lignesPrix: lignes, marqueurs, courbes, zones, lignes: tendances, rsi, divergences: L.rsi[0] ? an.divergences : [] });
      if (jeton !== tourGraphe) { g?.retirer(); return; }
      graphe = g;
    });
    q("#ccSrc").textContent = `${u.source || "Bougies Twelve Data"}, heures de Paris · ${P.mention_reperes || "repères calculés en Python, pas des signaux"}`;
  }

  function dessinerEcart(f) {
    const e = f.ecart_taux || {}, M = e.maturites || {};
    grEcart?.retirer(); grEcart = null; tourEcart++;
    if (!maturite || !M[maturite]?.disponible) maturite = e.defaut;
    q("#ecSous").textContent = `${f.base} − ${f.cotation}, rendements d'État · ${e.note_defaut || "calcul Python, sources officielles"}`;
    q("#ecMat").innerHTML = [["2a", "2 ans"], ["10a", "10 ans"]].map(([k, lib]) => `<button type="button" data-m="${k}" aria-pressed="${k === maturite}" ${M[k]?.disponible ? "" : `disabled title="${esc(M[k]?.raison || "indisponible")}"`}>${lib}</button>`).join("");
    q("#ecMat").querySelectorAll("button:not([disabled])").forEach(b => b.onclick = () => { maturite = b.dataset.m; dessinerEcart(f); });
    q("#ecPer").innerHTML = PERIODES.map(([k, lib]) => `<button type="button" data-p="${k}" aria-pressed="${k === periode}">${lib}</button>`).join("");
    q("#ecPer").querySelectorAll("button").forEach(b => b.onclick = () => { periode = b.dataset.p; dessinerEcart(f); });
    const x = M[maturite];
    if (!x) {
      q("#ecKpi").innerHTML = ""; q("#ecHaut").innerHTML = `<div class="empty">${esc(e.raison || "Écart de taux indisponible pour cette paire.")}</div>`; q("#ecBas").innerHTML = ""; q("#ecPhrase").textContent = ""; q("#ecSrc").textContent = ""; return;
    }
    const kp = [["Écart actuel", sgn(x.actuel_pb, 0, " pb"), `au ${ddm(x.date)}${x.mensuel ? " · mensuel" : ""}`],
                ["Sur 1 mois", x.variation_1m_pb == null ? nd("historique insuffisant") : sgn(x.variation_1m_pb, 0, " pb"), x.variation_1s_pb == null ? (x.raison_1s ? "1 semaine : n/d (" + esc(x.raison_1s) + ")" : "") : `1 semaine : ${sgn(x.variation_1s_pb, 0, " pb")}`],
                ["Corrélation 60 séances", x.correlation == null ? nd(x.raison_lien || "non mesurable") : sgn(x.correlation, 2), "variations quotidiennes"],
                ["Sensibilité", x.sensibilite_pips_10pb == null ? nd(x.raison_lien || "non mesurable") : sgn(x.sensibilite_pips_10pb, 0, " pips"), "pour +10 pb d'écart"]];
    q("#ecKpi").innerHTML = kp.map(k => `<div><span>${k[0]}</span><b>${k[1]}</b><span class="small">${k[2]}</span></div>`).join("");
    q("#ecPhrase").textContent = x.phrase || "";
    const jours = PERIODES.find(z => z[0] === periode)[2], depuis = new Date(Date.parse(x.date) - jours * 864e5).toISOString().slice(0, 10);
    const cl = (e.cloture_paire || []).filter(z => z[0] >= depuis), ec = (x.ecart || []).filter(z => z[0] >= depuis);
    const pp = dec((cl[cl.length - 1] || [0, 1])[1]);
    const jeton = ++tourEcart;
    requestAnimationFrame(async () => {
      if (jeton !== tourEcart) return;
      const g = await graphiqueEcart(q("#ecHaut"), q("#ecBas"), cl, ec, pp, x.mensuel);
      if (jeton !== tourEcart) { g?.retirer(); return; }
      grEcart = g;
    });
    q("#ecSrc").textContent = `Paire : ${e.source_paire || "série unique 5 ans"} · ${f.base} : ${x.sources?.[f.base] || "n/d"} · ${f.cotation} : ${x.sources?.[f.cotation] || "n/d"}` +
      (M["2a"] && !M["2a"].disponible && maturite !== "2a" ? ` · 2 ans : ${M["2a"].raison}` : "");
  }
  rendre();
}
