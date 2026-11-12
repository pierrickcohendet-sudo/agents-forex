/* Lot V8 — Briefing (page d'accueil, maquette #briefing) : briefing.json (titre, lignes, décision, sessions, publications,
   paires, seuils et marchés : Python), paires.json (bougies 30 min). Le navigateur ne calcule que l'heure : compte à
   rebours, ligne « maintenant », temps relatifs. */
import { $, h, nf, sgn, esc, dfr, ddm, jourSem, frTxt, nd, spark, donnees, bloc, graphiqueBougies, tempsRelatif, heureParis,
         pointFraicheur, animerChiffres } from "./v7_commun.js";

const SQUELETTE = `
<div class="bf-hero">
  <div class="card bf-title">
    <div class="eyebrow" id="bfDate"></div>
    <h1 id="bfTitre"></h1>
    <ul class="know" id="know"></ul>
  </div>
  <div class="card cd" id="cd" aria-live="off"></div>
</div>
<div class="card pad" style="display:flex;flex-direction:column;gap:10px">
  <div class="sec-head"><h2>Ta journée</h2><div class="legend"><span><i style="background:var(--down);border-radius:50%"></i>Fort</span><span><i style="background:var(--warn);border-radius:50%"></i>Moyen</span><span><i style="background:var(--line-2);border-radius:50%"></i>Faible</span><span>Heure de Paris</span></div></div>
  <div class="tl" id="tl"></div>
  <p class="src" id="tlSrc"></p>
</div>
<div id="decBloc"><div class="sec-head"><h2>Jour de décision</h2><p id="decSub"></p></div><div id="dec" style="margin-top:22px"></div></div>
<div class="two">
  <div class="card" style="overflow:hidden">
    <div class="pad" style="padding-bottom:8px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap"><h2>À venir aujourd'hui</h2><button class="switch" id="allBtn" type="button" aria-pressed="false"><i></i><span>Afficher les faibles</span></button></div>
    <div class="up-list" id="up"></div>
  </div>
  <div style="display:flex;flex-direction:column;gap:14px">
    <div class="card pad" style="display:flex;flex-direction:column;gap:10px"><h3>Paires à regarder en premier</h3><div id="bfWatch" style="display:flex;flex-direction:column;gap:10px"></div></div>
    <div class="card pad" style="display:flex;flex-direction:column;gap:10px"><h3>Au bord d'un seuil</h3><div id="bfBord" style="display:flex;flex-direction:column;gap:8px;font-size:13.5px"></div></div>
  </div>
</div>
<div class="sec-head" id="mkHead"><h2>Marchés ce matin</h2><p id="bfMk"></p></div>
<div class="grid strip" id="strip"></div>`;

const tsIso = iso => Date.parse(iso) / 1000;
const heurePDec = ts => { const p = new Date(ts * 1000).toLocaleString("en-GB", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit", hour12: false }).split(":"); return Number(p[0]) + Number(p[1]) / 60; };
let minuteries = [];

export async function ecranBriefing(section) {
  minuteries.forEach(clearInterval); minuteries = [];
  section.innerHTML = SQUELETTE;
  const q = s => $(s, section);
  const b = await donnees("briefing");
  if (!b) { q("#bfTitre").textContent = "Briefing indisponible"; q("#know").innerHTML = "<li><b>Raison</b><span>briefing.json absent : il sera publié au prochain run.</span></li>"; return; }
  const evts = (b.evenements || []).map(e => ({ ...e, ts: tsIso(e.iso_utc) })).filter(e => !isNaN(e.ts)).sort((a, x) => a.ts - x.ts);
  const maintenant = () => Date.now() / 1000;

  bloc(q(".bf-title"), () => {
    q("#bfDate").textContent = `Briefing · ${jourSem(b.date)} ${dfr(b.date)} ${b.date.slice(0, 4)} · rapport de ${String(b.rapport_genere_le || "").slice(11, 16)} UTC`;
    q("#bfTitre").textContent = b.titre;
    q("#bfTitre").title = `Titre calculé en Python : ${b.titre_source}`;
    q("#know").innerHTML = (b.lignes || []).map(k => `<li><b>${esc(k[0])}</b><span>${esc(k[1])}</span></li>`).join("");
  });

  // Compte à rebours vers le prochain événement à fort impact (heure réelle de l'appareil, en secondes)
  const cd = q("#cd");
  function tic() {
    const s = maintenant(), forts = evts.filter(e => e.impact === "fort" && e.heure_connue !== false && e.ts > s);
    const nx = forts[0];
    if (!nx) { cd.innerHTML = `<span class="eyebrow">Prochain rendez-vous majeur</span><div class="big" style="font-size:38px">Plus rien de fort aujourd'hui</div><p>La suite dans l'<a href="#agenda" style="color:inherit">Agenda</a>.</p>`; return; }
    const reste = nx.ts - s, hh = Math.floor(reste / 3600), m = Math.floor(reste % 3600 / 60), sc = Math.floor(reste % 60);
    const memes = forts.filter(e => e.ts === nx.ts), ensuite = forts.filter(e => e.ts > nx.ts);
    const pct = Math.max(0, Math.min(100, 100 - reste / (6 * 3600) * 100));
    cd.innerHTML = `<span class="eyebrow">Prochain rendez-vous majeur</span>
      <div class="big" role="timer" aria-label="dans ${hh} heures ${m} minutes">${hh}<small>h</small>${String(m).padStart(2, "0")}<small>min</small>${String(sc).padStart(2, "0")}<small>s</small></div>
      <p><b>${esc(nx.heure_paris)} · ${esc(nx.devise)}</b> · ${memes.map(e => esc(e.evenement)).join(" · ")}</p>
      <div class="bar"><i style="width:${pct}%"></i></div>
      <p style="font-size:13px;opacity:.7">Puis : ${ensuite.slice(0, 2).map(e => esc(e.heure_paris + " " + e.evenement)).join(" · ") || "rien d'autre de fort aujourd'hui"}</p>`;
  }
  tic(); minuteries.push(setInterval(() => { if (section.isConnected && section.classList.contains("on")) tic(); }, 1000));

  // « Ta journée » : frise 0 h – 24 h, sessions (heures locales des places converties en heure de Paris), publications
  const tl = q("#tl");
  function frise() {
    const s = maintenant(), X = hp => Math.max(0, Math.min(100, hp / 24 * 100));
    let html = (b.sessions || []).map((x, i) => `<div class="band" style="left:${X(x.debut)}%;width:${X(Math.min(24, x.fin)) - X(x.debut)}%;top:${i * 24}px" title="${esc(x.texte)}">${esc(x.nom)}</div>`).join("");
    const voies = {};
    for (const e of evts) {
      if (e.heure_connue === false) continue;
      const hp = heurePDec(e.ts), k = Math.round(hp * 2); voies[k] = (voies[k] || 0) + 1; const v = voies[k] - 1;
      html += `<button type="button" class="ev ${e.impact} ${e.ts < s ? "past" : ""}" style="left:${X(hp)}%;top:${80 + Math.min(v, 3) * 13}px" aria-label="${esc(`${e.heure_paris} ${e.devise} ${e.evenement}`)}" data-t="${esc(`${e.heure_paris} · ${e.devise} · ${e.evenement}${e.consensus ? " · attendu " + frTxt(e.consensus) : ""}${e.publie ? " · publié " + frTxt(e.publie) : ""}`)}"></button>`;
    }
    html += `<div class="ax">${[0, 3, 6, 9, 12, 15, 18, 21, 24].map(x => `<span style="left:${x / 24 * 100}%">${String(x).padStart(2, "0")}h</span>`).join("")}</div>`;
    const jour = new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Paris" });
    if (jour === b.date) html += `<div class="now" style="left:${X(heurePDec(s))}%"><span>${heureParis(s)}</span></div>`;
    tl.innerHTML = html;
    tl.querySelectorAll(".ev").forEach(bt => {
      const montrer = () => { tl.querySelectorAll(".tip").forEach(t => t.remove()); const t = h("div", "tip", esc(bt.dataset.t)); t.style.left = Math.max(12, Math.min(88, parseFloat(bt.style.left))) + "%"; tl.appendChild(t); };
      const cacher = () => tl.querySelectorAll(".tip").forEach(t => t.remove());
      bt.onmouseenter = montrer; bt.onfocus = montrer; bt.onclick = montrer; bt.onmouseleave = cacher; bt.onblur = cacher;
    });
    q("#tlSrc").textContent = `Sessions : heures locales des places (${(b.sessions || []).map(x => x.nom).join(", ")}), heure d'été et d'hiver comprises · publications : Agenda (ForexFactory et sites officiels)`;
  }
  frise();

  // Jour de décision
  bloc(q("#dec"), () => {
    const d = b.decision;
    if (!d) { q("#decBloc").classList.add("full"); q("#decSub").textContent = ""; q("#dec").innerHTML = '<div class="card pad muted">Aucune décision de banque centrale aujourd\'hui.</div>'; return; }
    q("#decSub").textContent = `${d.banque} · ${d.heure} Paris · le tableau se remplit à la publication`;
    const cellPub = l => l.publie ? `<b>${esc(frTxt(l.publie))}</b>` : l.heure ? `<span class="pending"><i></i>${esc(l.heure)}</span>` : nd(l.raison);
    const reac = d.reaction;
    q("#dec").innerHTML = `<div class="card dec"><div class="dec-l">
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><h2>${esc(d.banque)}</h2>${d.badge ? `<span class="chip ${d.badge.sens === "hausse" ? "up" : d.badge.sens === "baisse" ? "dn" : ""}"><span class="dot"></span>${esc(d.badge.texte)}${d.badge.pb ? " · " + Math.abs(d.badge.pb) + " pb" : ""}</span>` : ""}</div>
      <table class="dtab"><thead><tr><th></th><th>Précédent</th><th>Attendu</th><th>Publié</th></tr></thead><tbody>
      ${d.lignes.map(l => `<tr><td>${esc(l.libelle)}</td><td>${l.precedent ? esc(frTxt(l.precedent)) : "—"}</td><td>${l.attendu ? `<b>${esc(frTxt(l.attendu))}</b>` : "—"}</td><td>${cellPub(l)}</td></tr>`).join("")}
      </tbody></table>
      ${reac && reac.variation_pct == null ? `<div class="auto"><b>Réaction de ${esc(reac.paire)}</b><span>${nd(reac.raison)}</span></div>` : ""}
      ${reac && reac.variation_pct != null ? `<div class="auto"><b>Réaction de ${esc(reac.paire)}</b><span class="${reac.variation_pct > 0 ? "pos" : reac.variation_pct < 0 ? "neg" : ""}" style="font-weight:600">${sgn(reac.variation_pct, 2, " %")} depuis la clôture de la bougie de ${heureParis(Date.parse(reac.depuis.replace(" ", "T") + "Z") / 1000)}</span><span class="src">${esc(reac.source)}</span></div>` : ""}
      <div class="cols2" style="gap:10px">${(d.cas || []).map((c, i) => `<div class="auto" style="background:var(${i ? "--down-soft" : "--up-soft"})"><b>${esc(c.titre)}</b><span>${esc(c.lecture)}</span></div>`).join("")}</div>
      <span class="small">Lecture complète des 6 cas dans la <a href="#synthese">Synthèse</a>. ${esc(d.note)}</span>
    </div>
    <div class="dec-r"><div class="sec-head"><h3>${esc(d.paire)} en 30 min</h3><span class="small">repère : publication ${esc(d.heure)}</span></div><div id="decChart" style="height:260px">${d.paire_bougies ? "" : `<div class="empty">${esc(d.raison_bougies)}</div>`}</div><span class="src">Twelve Data · heures de Paris</span></div></div>`;
    const bg = d.bougies_30min;   // copiées dans briefing.json (Python) : paires.json n'est pas chargé ici
    const lt = d.lignes.find(l => l.iso_utc);
    if (bg?.length) requestAnimationFrame(() => graphiqueBougies(q("#decChart"), bg, bg[0][4] > 20 ? 2 : 4,
      { marqueurs: lt ? [{ ts: tsIso(lt.iso_utc), texte: `${d.court} ${d.heure}`, couleur: "--down", forme: "arrowDown" }] : [] }));
  });

  // À venir aujourd'hui (forts et moyens par défaut), séparateur « Maintenant », temps relatif mis à jour chaque minute
  let faibles = false;
  function aVenir() {
    const s = maintenant(), liste = evts.filter(e => faibles || e.impact !== "faible");
    let html = "", pose = false;
    for (const e of liste) {
      if (!pose && e.ts >= s) { html += '<div class="nowline">Maintenant</div>'; pose = true; }
      const nb = { fort: 3, moyen: 2, faible: 1 }[e.impact] || 0;
      html += `<div class="row ${e.ts < s ? "past" : ""}"><span style="font-weight:600">${esc(e.heure_paris || "—")}</span><span class="cur">${esc(e.devise)}</span>
        <div style="display:flex;flex-direction:column;min-width:0"><b style="font-weight:600;font-size:14px">${esc(e.evenement)}</b><span class="small">${e.publie ? "Publié <b>" + esc(frTxt(e.publie)) + "</b> · " : ""}${e.votes ? esc(e.votes) : `${e.consensus ? "attendu " + esc(frTxt(e.consensus)) + " · " : ""}${e.precedent ? "précédent " + esc(frTxt(e.precedent)) : esc(e.type || "")}`}</span></div>
        <span class="when"><span class="imp ${e.impact}" style="justify-content:flex-end;margin-bottom:4px">${[1, 2, 3].map(i => `<i class="${i <= nb ? "on" : ""}" style="${i > nb ? "opacity:.35" : ""}"></i>`).join("")}</span><span class="${e.ts >= s ? "" : "muted"}">${e.heure_connue === false ? "heure n/d" : tempsRelatif(e.ts - s)}</span></span></div>`;
    }
    if (!pose) html += '<div class="nowline">Maintenant</div>';
    q("#up").innerHTML = html || '<div class="empty">Aucune publication aujourd\'hui.</div>';
  }
  q("#allBtn").onclick = () => { faibles = !faibles; q("#allBtn").setAttribute("aria-pressed", faibles); aVenir(); };
  aVenir();
  minuteries.push(setInterval(() => { if (section.isConnected) { frise(); aVenir(); } }, 60000));

  bloc(q("#bfWatch"), () => {
    q("#bfWatch").innerHTML = (b.paires || []).map((w, i) => `<a class="card watch-lien" href="#paire/${w.paire.replace("/", "-")}"><div style="display:flex;justify-content:space-between;gap:8px"><b>${i + 1}. ${w.paire}</b><span class="chip acc" style="height:22px">${esc(w.libelle || "score " + nf(w.score, 1))}</span></div>${w.texte ? `<span class="small" style="color:var(--ink-2)">${esc(w.texte.length > 150 ? w.texte.slice(0, 147) + "…" : w.texte)}</span>` : ""}<span class="small" style="color:var(--accent);font-weight:600">Ouvrir la page de la paire →</span></a>`).join("") || '<span class="muted">Classement indisponible.</span>';
  });
  bloc(q("#bfBord"), () => {
    q("#bfBord").innerHTML = (b.au_bord || []).map(x => `<div style="display:flex;gap:10px"><span class="chip warn" style="height:22px">${x.engrenage}</span><span>${esc(x.phrase || x.libelle)}</span></div>`).join("") || '<span class="muted">Aucun seuil proche.</span>';
  });
  bloc(q("#strip"), () => {
    q("#bfMk").textContent = `Clôtures et cours de ${String(b.rapport_genere_le || "").slice(11, 16)} UTC · 30 séances`;
    q("#strip").innerHTML = (b.marches || []).map(l => {
      const dc = l.decimales ?? (l.niveau > 50 ? 2 : 4), u = l.unite === "pb" ? " pb" : l.unite === "pts" ? " pts" : " %", du = l.unite === "pb" ? 0 : 2;
      const coul = l.variation_j1 > 0 ? "var(--up)" : l.variation_j1 < 0 ? "var(--down)" : "var(--muted)";
      return `<div class="card mt" title="${esc((l.source || "") + (l.heure ? " · " + ddm(String(l.heure).slice(0, 10)) : ""))}"><span>${esc(l.actif.replace(" (formule du DXY, non officiel)", " DXY"))}</span><b class="anim-num">${l.niveau == null ? "n/d" : nf(l.niveau, dc) + esc(l.suffixe || "")}</b><span class="${l.variation_j1 > 0 ? "pos" : l.variation_j1 < 0 ? "neg" : "muted"}" style="font-weight:600">${sgn(l.variation_j1, du, u)}</span>${spark((l.serie_30j || []).map(p => p[1]), 150, 28, coul, true)}</div>`;
    }).join("");
  });
  pointFraicheur(q("#bfDate"), "briefing");
  pointFraicheur(q("#mkHead"), "point_marche");
  animerChiffres(section);
}
