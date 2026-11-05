/* Lot V7 — Synthèse (maquette #synthese) : rapport_jour.json, dossiers.json (cockpit), profil_devises.json, tableau_macro.json. */
import { $, h, nf, sgn, esc, dfr, ddm, jourSem, store, frTxt, nd, UNI, classeEtat, classeDir, hbar, donnees, bloc, blocDetaille } from "./v7_commun.js";

const SQUELETTE = `
<div class="card hero">
  <div class="hero-main">
    <div class="eyebrow" id="heroDate" data-fraicheur="rapport"></div>
    <h1 id="heroTitre"></h1>
    <div style="display:flex;gap:8px;flex-wrap:wrap" id="heroChips"></div>
    <p id="heroTxt"></p>
    <div id="devStrip" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px"></div>
  </div>
  <div class="hero-side">
    <div class="ring" id="ring"></div>
    <div style="display:flex;flex-direction:column;gap:6px">
      <span class="eyebrow">Conviction</span>
      <div style="display:flex;gap:10px;align-items:center"><div class="meter" id="meter"></div><b id="convTxt" style="font-weight:600"></b></div>
    </div>
    <div style="display:flex;flex-direction:column;gap:6px">
      <span class="eyebrow">Depuis hier</span>
      <div id="depuis" style="display:flex;flex-direction:column;gap:4px;font-size:13.5px;color:var(--ink-2)"></div>
    </div>
  </div>
</div>
<div class="ess" id="ess"></div>
<div class="card pad full" id="redige" hidden></div>
<div class="sec-head" data-fraicheur="agenda"><h2>Banques centrales de la semaine</h2><p>Décisions à venir et ce qui est attendu</p></div>
<div id="bcw" style="display:flex;flex-direction:column;gap:14px"></div>
<div class="two">
  <div class="card">
    <div class="pad" style="padding-bottom:6px"><div class="sec-head"><h2>Scénarios</h2><p>Conditions remplies, calculées en Python</p></div></div>
    <div id="scens"></div>
  </div>
  <div class="card">
    <div class="pad" style="padding-bottom:10px;display:flex;flex-direction:column;gap:10px">
      <div class="sec-head"><h2>Paires à suivre</h2><p>Score de priorité, clic pour le détail</p></div>
      <div class="legend" id="wlLegend"></div>
    </div>
    <div id="wl"></div>
  </div>
</div>
<div class="sec-head"><h2>Lecture institutionnelle</h2><p>Mécanismes de marché et conditions vérifiées</p></div>
<div class="cols3" id="mecas"></div>
<div class="cols2" style="grid-template-columns:minmax(0,1.55fr) minmax(0,1fr)">
  <div class="card">
    <div class="pad" style="padding-bottom:4px"><div class="sec-head"><h2>Publié hier</h2><p id="veilleJour"></p></div></div>
    <div class="scroll"><table class="tbl" id="veille"></table></div>
  </div>
  <div class="card pad" style="display:flex;flex-direction:column;gap:6px">
    <div class="sec-head"><h2>Plus fortes surprises</h2><p>30 derniers jours, en écarts-types</p></div>
    <div id="bilan"></div>
  </div>
</div>
<div class="sec-head full"><h2>Variables clés sur 5 séances</h2><p>Ce que les scénarios lisent</p></div>
<div class="grid vars full" id="vars"></div>
<div class="card full">
  <div class="pad" style="padding-bottom:4px"><div class="sec-head"><h2>Technique multi-unités</h2><p>Repères de prix, pas des signaux</p></div></div>
  <div class="scroll"><table class="tbl" id="tech" style="min-width:980px"></table></div>
</div>
<div class="cols2">
  <div class="card pad" style="display:flex;flex-direction:column;gap:6px">
    <div class="sec-head"><h2>Calendrier commenté</h2><p>Deux semaines</p></div>
    <div id="calj"></div>
  </div>
  <div class="card pad" style="display:flex;flex-direction:column;gap:14px">
    <div class="sec-head"><h2>Plan du jour</h2><p>Coche au fil de la séance</p></div>
    <div class="cols3" id="plan" style="gap:18px"></div>
  </div>
</div>
<div class="card pad" style="display:flex;flex-direction:column;gap:10px">
  <span class="eyebrow">En une phrase</span>
  <p class="conclu" id="conclu"></p>
</div>
<div id="detaille"></div>`;

const dec = v => Math.abs(v) >= 20 ? 2 : 4;
const COMPOSANTES = [["evenements", "Événements", "--c1"], ["differentiel", "Écart de taux", "--c2"], ["solde", "Solde engrenages", "--c3"], ["volatilite", "Volatilité", "--c4"]];
const VARIABLES = { us2a_5j: "US 2 ans", us10a_5j: "US 10 ans", us30a_5j: "US 30 ans", reel_10a_5j: "Taux réel 10 ans", point_mort_10a_5j: "Point mort d'inflation", spread_hy_5j: "Crédit high yield", vix_5j: "VIX", brent_5j: "Brent", or_5j: "Or", nasdaq_5j: "Nasdaq 100 (QQQ)", sp500_5j: "S&P 500 (SPY)", dollar_5j: "Dollar", ecart_2a_us_de_5j: "Écart 2 ans US − All.", oat_bund: "Écart OAT − Bund", surprise_30j_usd: "Surprise USD 30 j" };
const symbole = r => r === true ? "✓" : r === false ? "×" : "–";
const classeCond = r => r === true ? "pos" : r === false ? "neg" : "muted";

export async function ecranSynthese(section) {
  section.innerHTML = SQUELETTE;
  const [rj, dos, profil, tm] = await Promise.all([donnees("rapport_jour"), donnees("dossiers"), donnees("profil_devises"), donnees("tableau_macro")]);
  if (!rj) { $("#heroTitre", section).textContent = "Rapport du jour indisponible"; $("#heroTxt", section).textContent = "rapport_jour.json absent : il sera publié au prochain run."; return; }
  const q = s => $(s, section);
  const t = rj.theme || {}, tx = rj.textes || {};

  bloc(q(".hero"), () => {
    const g = rj.genere_le || "";
    q("#heroDate").textContent = `${jourSem(rj.date)} ${dfr(rj.date)} ${rj.date.slice(0, 4)} · rapport de ${g.slice(11, 16)} UTC`;
    q("#heroTitre").textContent = t.titre || "Thème n/d";
    const dir = t.direction || {};
    q("#heroChips").innerHTML = `<span class="chip ${classeDir(dir.classe)}"><span class="dot"></span>${esc(dir.libelle || "direction n/d")}</span><span class="chip">Calcul Python, pas d'avis du modèle</span>`
      + (tx.mention_engrenages ? `<span class="chip warn" title="La synthèse des engrenages par le modèle n'est pas faite aujourd'hui : thème et directions calculés en Python">${esc(tx.mention_engrenages)}</span>` : "");
    q("#heroTxt").textContent = t.texte || "";
    q("#devStrip").innerHTML = (profil?.devises || []).map(d => `<span class="chip ${classeEtat(d.etat?.valeur)}" title="${esc((d.etat?.valeur || "n/d") + " · " + (d.etat?.raison || ""))}">${d.devise}</span>`).join("");
    const en = dos?.cockpit?.entete || {}, a = en.alignes, n = en.evaluables;
    const seuil = (dos?.cockpit?.thermometres || []).find(x => x.numero === 1)?.seuil_haut ?? 3;
    if (a != null && n) {
      const R = 46, C = 2 * Math.PI * R;
      q("#ring").innerHTML = `<svg viewBox="0 0 116 116" role="img" aria-label="${a} engrenages alignés sur ${n}"><circle cx="58" cy="58" r="${R}" style="fill:none;stroke:var(--line)" stroke-width="9"/>
        <circle cx="58" cy="58" r="${R}" style="fill:none;stroke:var(--accent)" stroke-width="9" stroke-linecap="round" stroke-dasharray="${C * a / n} ${C}" transform="rotate(-90 58 58)"/>
        <line x1="58" y1="6" x2="58" y2="18" style="stroke:var(--ink)" stroke-width="2" transform="rotate(${seuil / n * 360} 58 58)"/>
        <text x="58" y="64" text-anchor="middle" font-family="Newsreader, Georgia, serif" font-size="26" style="fill:var(--ink)">${a}/${n}</text></svg>
        <div><b>${a} sur ${n}</b><div class="muted" style="font-size:13.5px">engrenages alignés sur le thème. Il en faut ${seuil} pour un thème établi (le repère sur l'anneau).</div></div>`;
    } else q("#ring").innerHTML = `<div class="muted">Cohérence des engrenages ${nd("dossiers des engrenages absents")}</div>`;
    const conv = { faible: 1, moyen: 2, fort: 3 }[t.conviction] || 0;
    q("#meter").innerHTML = [1, 2, 3].map(i => `<i class="${i <= conv ? "on" : ""}"></i>`).join("");
    q("#convTxt").textContent = { faible: "Faible", moyen: "Moyenne", fort: "Forte" }[t.conviction] || "n/d";
    q("#depuis").innerHTML = (rj.depuis_veille || []).map(x => `<div style="display:flex;gap:8px"><span class="dot" style="color:var(--accent);margin-top:7px"></span><span>${esc(x)}</span></div>`).join("") || '<span class="muted">Rien de nouveau depuis le rapport précédent.</span>';
  });

  bloc(q("#ess"), () => {
    const labs = ["Thème", "Scénario", "Devises", "Agenda", "Priorité"];
    q("#ess").innerHTML = (rj.essentiel?.lignes || []).map((l, i) => `<div><span>${labs[i] || ""}</span><p>${esc(l.replace(/^Thème : /, "").replace(/^Paire à suivre en premier : /, ""))}</p></div>`).join("");
  });

  bloc(q("#redige"), () => {   // texte rédigé par le modèle (fonctionnalité conservée, vue complète)
    if (!tx.synthese && !tx.bilan) return;
    const r = q("#redige"); r.hidden = false;
    r.innerHTML = `<div class="sec-head"><h3>Synthèse rédigée</h3><span class="src">${esc(tx.redige_par?.libelle ? "Rédigé par " + tx.redige_par.libelle + " à partir des chiffres Python" : "")}</span></div>
      ${tx.synthese_blocs?.length ? `<div class="redige">${tx.synthese_blocs.map(x => `${x.titre ? `<h4>${esc(x.titre)}</h4>` : ""}<p>${esc(x.texte)}</p>`).join("")}</div>`
        : tx.synthese ? `<p style="margin:8px 0 0">${esc(tx.synthese)}</p>` : ""}${tx.bilan ? `<p class="muted" style="margin:8px 0 0">${esc(tx.bilan)}</p>` : ""}`;
  });

  bloc(q("#bcw"), () => {
    const banques = rj.banques || [];
    q("#bcw").innerHTML = banques.length ? banques.map(b => {
      const cpi = b.contexte?.cpi, ch = b.contexte?.chomage;
      const cv = cpi ? parseFloat(String(cpi.valeur).replace(",", ".")) : null, cb = cpi ? cpi.cible : null, sc = cv != null ? Math.max(cv, cb || 0) * 1.5 : 1;
      const badge = b.badge ? `<span class="chip ${b.badge.sens === "hausse" ? "up" : b.badge.sens === "baisse" ? "dn" : ""}"><span class="dot"></span>${esc(b.badge.texte)}${b.badge.pb ? " · " + b.badge.pb + " pb" : ""}</span>` : "";
      return `<div class="card bcw"><div class="bcw-main">
        <div class="eyebrow">${jourSem(b.date)} ${dfr(b.date)} · ${esc(b.heure || "")} Paris · ${b.devise}</div>
        <div style="display:flex;gap:12px;align-items:baseline;flex-wrap:wrap"><h2>${esc(b.banque)}</h2>${badge}</div>
        <div class="big-rate"><div><span>Taux actuel</span><b>${b.taux ? esc(frTxt(b.taux)) : nd("taux actuel absent du registre")}</b></div><span class="arrow">→</span><div><span>Consensus</span><b style="color:var(--accent)">${b.consensus ? esc(frTxt(b.consensus)) : nd("consensus non publié")}</b></div></div>
        ${cpi && cv != null ? `<div style="display:flex;flex-direction:column;gap:6px;max-width:420px"><div style="display:flex;justify-content:space-between;font-size:13px"><span>Inflation <b>${esc(frTxt(cpi.valeur))}</b> <span class="muted">(${ddm(cpi.date)})</span></span><span class="muted">cible ${cb != null ? nf(cb, 1) + " %" : "n/d"}</span></div>
          <div class="cible"><i style="left:0;width:${cv / sc * 100}%"></i>${cb != null ? `<em style="left:${cb / sc * 100}%"></em>` : ""}</div></div>` : ""}
        ${ch ? `<div style="font-size:13px">Chômage <b>${esc(frTxt(ch.valeur))}</b> <span class="muted">(${ddm(ch.date)})</span></div>` : ""}
        ${b.a_surveiller?.length ? `<div><div class="eyebrow" style="margin-bottom:6px">À surveiller</div><ul class="watch">${b.a_surveiller.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
        ${b.raison_marche ? `<div class="small">Lecture marché : ${esc(b.raison_marche)}</div>` : ""}
      </div>
      <div class="bcw-side full"><div class="eyebrow">Comment lire la décision</div>
        ${(rj.interpretation || []).map(x => `<div style="font-size:13px;display:flex;flex-direction:column;gap:2px;padding:6px 0;border-top:1px solid var(--line)"><b>${esc(x[0] ?? x.cas)}</b><span class="muted">${esc(x[1] ?? x.lecture)}</span></div>`).join("")}
      </div></div>`;
    }).join("") : '<div class="card pad muted">Aucune décision de banque centrale cette semaine.</div>';
  });

  bloc(q("#scens"), () => {
    const liste = rj.scenarios?.liste || [];
    const ordre = liste.some(s => s.rang) ? [...liste].sort((a, b) => (a.rang ?? 99) - (b.rang ?? 99))   // rang calculé en Python
      : [...liste.filter(s => s.mieux_confirme), ...liste.filter(s => !s.mieux_confirme)];
    const sc = q("#scens");
    ordre.forEach((s, k) => {
      const conds = s.conditions || [];
      const box = h("div", "scen" + (k === 0 ? " open" : ""), `<div class="scen-top"><b>${esc(s.titre)}</b><span>${s.remplies}<small class="muted" style="font-size:14px">/${s.total}</small></span></div>
        <div class="segs">${conds.map(c => `<i class="${c.remplie === true ? "ok" : c.remplie === null ? "nd" : ""}" title="${esc(c.libelle)}"></i>`).join("")}</div>
        <ul class="conds">${conds.map(c => `<li><em class="${classeCond(c.remplie)}">${symbole(c.remplie)}</em><span>${esc(c.chiffre || c.libelle)}${c.remplie === null && c.raison ? ` <span class="small">(${esc(c.raison)})</span>` : ""}</span></li>`).join("")}</ul>
        <button class="more" type="button" aria-expanded="${k === 0}">${k === 0 ? "Masquer" : "Voir les conditions"}</button>`);
      const b = box.querySelector(".more");
      b.onclick = () => { const o = box.classList.toggle("open"); b.textContent = o ? "Masquer" : "Voir les conditions"; b.setAttribute("aria-expanded", o); };
      sc.appendChild(box);
    });
    if (!ordre.length) sc.innerHTML = '<div class="pad muted">Aucun scénario évalué aujourd\'hui.</div>';
  });

  bloc(q("#wl"), () => {
    q("#wlLegend").innerHTML = COMPOSANTES.map(c => `<span><i style="background:var(${c[2]})"></i>${c[1]}</span>`).join("");
    const cl = rj.watchlist?.classement || [], top = Object.fromEntries((rj.watchlist_top3 || []).map(w => [w.paire, w]));
    const mx = Math.max(...cl.map(w => w.score), 1), wl = q("#wl");
    const AFFICHEES = 6;   // les 6 premières du classement Python ; les autres en vue complète
    cl.forEach((w, i) => {
      const barre = COMPOSANTES.map(c => (w.composantes?.[c[0]] || 0) > 0 ? `<i style="width:${w.composantes[c[0]] / mx * 100}%;background:var(${c[2]})" title="${c[1]} ${nf(w.composantes[c[0]], 2)}"></i>` : "").join("");
      const row = h("div", "wl-row", `<span class="rk">${i + 1}</span><b>${w.paire}</b><div class="stack">${barre}</div><span style="text-align:right;font-weight:600">${nf(w.score, 1)}</span>`);
      row.tabIndex = 0; row.setAttribute("role", "button");
      const t3 = top[w.paire], m = tx.watchlist?.[w.paire] || {}, te = rj.technique?.paires?.[w.paire];
      const haus = m.haussier || t3?.scenario_haussier?.texte, bais = m.baissier || t3?.scenario_baissier?.texte;
      const fmt = v => v == null ? "—" : nf(v, dec(v));
      const det = h("div", "wl-detail" + (i === 0 ? " open" : ""),
        (t3 ? `<span class="chip acc" style="align-self:flex-start">${esc(t3.libelle)}</span>` : "") +
        (haus ? `<div><b class="pos">Si la paire monte · </b>${esc(haus)}</div>` : "") + (bais ? `<div><b class="neg">Si elle baisse · </b>${esc(bais)}</div>` : "") +
        (te ? `<div class="small">Veille ${fmt(te.veille?.bas)} – ${fmt(te.veille?.haut)} · structure H4 ${esc(te.structure_h4?.tendance_structure || "n/d")} · tendance jour : ${esc(te.tendance_jour?.lecture || "n/d")}</div>` : "") +
        `<div class="small">Composantes : ${COMPOSANTES.map(c => c[1].toLowerCase() + " " + nf(w.composantes?.[c[0]] || 0, 1)).join(" · ")}${w.raison_differentiel ? " · " + esc(w.raison_differentiel) : ""}</div>`);
      const basculer = () => det.classList.toggle("open");
      row.onclick = basculer; row.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); basculer(); } };
      if (i >= AFFICHEES) { row.classList.add("wl-plus"); det.classList.add("wl-plus"); }
      wl.append(row, det);
    });
    if (cl.length > AFFICHEES) {
      const b = h("button", "more full wl-voir", `Voir les ${cl.length - AFFICHEES} autres paires`); b.type = "button";
      b.onclick = () => { const o = wl.classList.toggle("toutes"); b.textContent = o ? "Masquer les autres paires" : `Voir les ${cl.length - AFFICHEES} autres paires`; };
      wl.after(b);
    }
  });

  bloc(q("#mecas"), () => {
    q("#mecas").innerHTML = (rj.lecture?.mecanismes || []).map(m => {
      const ok = m.conditions.filter(c => c.remplie === true).length, on = m.etat === "detecte";
      return `<div class="card mc ${on ? "on" : ""}"><div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><h3>${esc(m.libelle)}</h3><span class="chip ${on ? "acc" : ""}">${on ? "Détecté" : m.etat === "nd" ? "n/d" : "Non détecté"}</span></div>
        <p style="margin:0;font-size:13.5px;color:var(--ink-2)">${esc(m.lecture)}</p>
        <div class="segs">${m.conditions.map(c => `<i class="${c.remplie === true ? "ok" : c.remplie === null ? "nd" : ""}"></i>`).join("")}</div>
        <ul class="full">${m.conditions.map(c => `<li><em class="${classeCond(c.remplie)}" style="font-style:normal;font-weight:700">${symbole(c.remplie)}</em><span>${esc(c.chiffre || c.libelle)}</span></li>`).join("")}</ul>
        <span class="small">${ok} condition${ok > 1 ? "s" : ""} sur ${m.conditions.length}</span></div>`;
    }).join("");
  });

  bloc(q("#veille"), () => {
    const pv = rj.publications_veille || {};
    q("#veilleJour").textContent = pv.jour ? `${jourSem(pv.jour)} ${dfr(pv.jour)} · réaction de la devise sur la séance` : "";
    const pubs = pv.publications || [];
    q("#veille").innerHTML = pubs.length ? `<thead><tr><th>Heure</th><th>Devise</th><th>Publication</th><th class="n">Publié</th><th class="n">Consensus</th><th>Écart</th><th class="n">Réaction</th></tr></thead><tbody>` +
      pubs.map(v => {
        const zz = v.ecart?.z, z = zz == null ? 0 : Math.max(-5, Math.min(5, zz)), w = Math.abs(z) / 5 * 50;
        const re = v.reaction?.variation_pct;
        return `<tr><td>${esc(v.heure || "")}</td><td><span class="cur" style="padding:0 6px">${v.devise}</span></td><td style="min-width:150px">${esc(v.evenement)}</td><td class="n"><b>${v.publie ? esc(frTxt(v.publie)) : nd("non publié")}</b></td><td class="n muted">${esc(frTxt(v.consensus) || "—")}</td>
        <td title="${esc(v.ecart?.texte || "")}"><div class="zbar"><i style="${z >= 0 ? "left:50%" : "right:50%"};width:${w}%;background:${z > 0 ? "var(--up)" : z < 0 ? "var(--down)" : "var(--muted)"}"></i></div></td>
        <td class="n ${re > 0 ? "pos" : re < 0 ? "neg" : "muted"}">${re == null ? nd(v.raison_reaction) : sgn(re, 2, " %")}</td></tr>`;
      }).join("") + "</tbody>" : `<tbody><tr><td class="muted">${esc(pv.note || "Aucune publication suivie hier.")}</td></tr></tbody>`;
  });

  bloc(q("#bilan"), () => {
    const lib = id => (tm?.indicateurs || []).find(i => i.id === id)?.libelle || String(id).replace(/_/g, " ");
    q("#bilan").innerHTML = (rj.bilan?.surprises || []).map(b => hbar(`${b.devise} <span class="muted" style="font-weight:500">${esc(lib(b.indicateur))}</span>`, b.surprise_ecarts, 3, sgn(b.surprise_ecarts, 1, " σ"), null, null, `${b.devise} · ${lib(b.indicateur)} : publié ${frTxt(b.publie)} contre ${frTxt(b.consensus)} attendu (${ddm(b.date)}, ${b.source})`)).join("") || '<p class="muted">Aucune surprise marquée sur 30 jours.</p>';
    section.querySelectorAll("#bilan .hbar").forEach(x => x.style.gridTemplateColumns = "minmax(0,1.2fr) minmax(0,1fr) 60px");
  });

  bloc(q("#vars"), () => {
    const V = rj.variables || {};
    q("#vars").innerHTML = Object.entries(VARIABLES).filter(([k]) => V[k]).map(([k, l]) => {
      const v = V[k], x = v.valeur;
      return `<div class="card var" title="${esc((v.source || "") + (v.date ? " · " + ddm(v.date) : ""))}"><span>${l}</span><b class="${x > 0 ? "pos" : x < 0 ? "neg" : "muted"}">${x == null ? nd(v.raison) : sgn(x, v.unite === "pb" ? 0 : 2, UNI[v.unite] ?? "")}</b><small>${v.date ? ddm(v.date) : esc(v.raison || "")}${/5j/.test(k) ? " · 5 séances" : ""}</small></div>`;
    }).join("");
  });

  bloc(q("#tech"), () => {
    const T = rj.technique?.paires || {}, f = v => v == null ? "—" : nf(v, dec(v));
    q("#tech").innerHTML = `<thead><tr><th>Paire</th><th class="n">Veille bas – haut</th><th class="n">Sem. préc. bas – haut</th><th class="n">Asie bas – haut</th><th>Structure H4</th><th>Dernière cassure</th><th>Zone FVG H4</th><th>Tendance jour · semaine</th></tr></thead><tbody>` +
      Object.entries(T).map(([p, t]) => {
        const evs = t.structure_h4?.evenements || [], ev = evs[evs.length - 1], fg = (Array.isArray(t.fvg_h4) ? t.fvg_h4 : [])[0] || null, as = t.sessions?.Asie;
        const st = t.structure_h4?.tendance_structure || "n/d";
        return `<tr><td><b>${p}</b></td><td class="n">${f(t.veille?.bas)} – ${f(t.veille?.haut)}</td><td class="n">${f(t.semaine_precedente?.bas)} – ${f(t.semaine_precedente?.haut)}</td><td class="n">${as ? f(as.bas) + " – " + f(as.haut) : "—"}</td>
        <td><span class="chip ${/hauss/.test(st) ? "up" : /baiss/.test(st) ? "dn" : ""}">${esc(st)}</span></td>
        <td>${ev ? `<b>${ev.type}</b> ${esc(ev.sens)} à ${f(ev.niveau)} <span class="small">${ddm(ev.date.slice(0, 10))} ${ev.date.slice(11)}</span>` : "—"}</td>
        <td>${fg ? `${esc(fg.sens || "")} ${f(fg.bas)} – ${f(fg.haut)}` : "—"}</td><td class="small" style="color:var(--ink-2)">${esc(t.tendance_jour?.lecture || "n/d")} · ${esc(t.tendance_semaine?.lecture || "n/d")}</td></tr>`;
      }).join("") + "</tbody>";
  });

  bloc(q("#calj"), () => {
    q("#calj").innerHTML = (rj.calendrier?.jours || []).map(j => {
      const n = (j.evenements || []).length, nfo = j.n_forts || 0;
      return `<div class="calj"><span style="font-weight:600;text-transform:capitalize">${jourSem(j.date).slice(0, 3)}. ${Number(j.date.slice(8, 10))}</span><div><b>${esc(j.titre)}</b><div class="small" style="color:var(--ink-2)">${esc(j.lecture)}</div></div><span class="chip ${nfo ? "dn" : ""}">${nfo} fort${nfo > 1 ? "s" : ""} · ${n}</span></div>`;
    }).join("");
  });

  bloc(q("#plan"), () => {
    const PL = [["avant", "Avant"], ["pendant", "Pendant"], ["cloture", "À la clôture"]], cle = "fxdesk-plan-" + rj.date;
    let fait = {}; try { fait = JSON.parse(store.get(cle) || "{}"); } catch (e) { fait = {}; }
    q("#plan").innerHTML = PL.map(([k, l]) => `<div class="plan"><span class="eyebrow">${l}</span>${(rj.plan?.[k] || []).map((x, i) => `<label for="pl-${k}-${i}"><input type="checkbox" id="pl-${k}-${i}" ${fait[k + i] ? "checked" : ""}><span>${esc(x)}</span></label>`).join("")}</div>`).join("");
    q("#plan").querySelectorAll("input").forEach(c => c.onchange = () => { const m = c.id.match(/pl-(\w+)-(\d+)/); fait[m[1] + m[2]] = c.checked; store.set(cle, JSON.stringify(fait)); });
    if (tx.plan) q("#plan").insertAdjacentHTML("afterend", `<p class="small full" style="margin:0">${esc(tx.plan)}</p>`);
  });
  q("#conclu").textContent = tx.conclusion || rj.conclusion?.phrase_python || "";

  q("#detaille").appendChild(blocDetaille("Rapport détaillé", "hebdomadaire, mensuel, version longue du lundi, communiqués, toutes les sections", async () => {
    const m = await import("./rapport.js"); return m.pageRapport();
  }));
}
