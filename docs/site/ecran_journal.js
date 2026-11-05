/* Lot V8 — Journal V3 (maquette #journal) : un outil de progression. Toute la logique du V2 est conservée (journal.js :
   IndexedDB, captures compressées, export et import, migration) ; la saisie passe dans un panneau latéral en 7 étapes.
   Statistiques calculées sur l'appareil (journal_stats.js, fonctions pures) à partir des trades privés de l'utilisateur.
   Trades d'exemple : mode démonstration seulement, jamais mélangés aux vrais. */
import { $, h, nf, sgn, esc, ddm, MOIS, JOURS, store, spark, hbar, blocDetaille, animerChiffres } from "./v7_commun.js";
import { statistiques, versTrade, calendrierR, exemples } from "./journal_stats.js";

const ETAPES = ["Paire et date", "Contexte du jour", "Captures", "Confluences", "Événements à risque", "Plan et risque", "Bilan"];
const BROUILLON = "fxdesk-journal-brouillon";

const SQUELETTE = `
<div class="sec-head"><div><span class="eyebrow">Mon journal</span><h2 style="font-size:32px">Ce que mes trades m'apprennent</h2></div>
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><span class="note-ex" id="jDemoTxt" hidden>Trades d'exemple (démonstration)</span>
    <button class="switch" id="jDemo" type="button" aria-pressed="false"><i></i><span>Voir avec des exemples</span></button>
    <button class="btn pri" id="newBtn" type="button">+ Nouvelle entrée</button></div></div>
<div class="card j-accueil" id="jAccueil" hidden></div>
<div id="jStats" class="j-stats">
<div class="grid jk" id="jk"></div>
<div class="cols2" style="grid-template-columns:minmax(0,1.5fr) minmax(0,1fr)">
  <div class="card pad" style="display:flex;flex-direction:column;gap:8px"><div class="sec-head"><h3>Courbe de résultat cumulé</h3><span class="small">en R (1 R = le risque prévu du trade)</span></div><div class="eq" id="eq"></div></div>
  <div class="card insight" id="ins1"></div>
</div>
<div class="cols3" id="ins"></div>
<div class="cols2">
  <div class="card pad" style="display:flex;flex-direction:column;gap:6px"><div class="sec-head"><h3>Par paire</h3><span class="small">R total</span></div><div id="byPair"></div></div>
  <div class="card pad" style="display:flex;flex-direction:column;gap:6px"><div class="sec-head"><h3>Par séance et par jour</h3><span class="small">R moyen · nombre de trades</span></div><div id="bySess"></div></div>
</div>
<div class="cols2" style="grid-template-columns:minmax(0,1fr) minmax(0,1.3fr)">
  <div class="card pad" style="display:flex;flex-direction:column;gap:10px"><div class="sec-head"><h3 id="calT"></h3><div class="seg" id="calSel" role="group" aria-label="Mois"></div></div><div class="cal" id="cal"></div></div>
  <div class="card" style="overflow:hidden"><div class="pad" style="padding-bottom:4px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center"><h3>Tous les trades</h3><div class="seg" id="jFilt" role="group" aria-label="Filtrer par paire"></div></div><div class="scroll"><table class="tbl" id="jTab" style="min-width:620px"></table></div></div>
</div>
</div>
<div id="jV2" style="display:flex;flex-direction:column;gap:14px"></div>`;

let demo = false, moisCal = null, filtre = "Toutes";

export async function ecranJournal(section, parametre) {
  section.innerHTML = SQUELETTE;
  const q = s => $(s, section);
  // V2 : formulaire, liste (export et import), fiche d'analyse — construits une fois, puis réorganisés
  const m = await import("./journal.js");
  const blocs = await m.pageJournal();
  const hote = h("div", "legacy journal-v7"); hote.append(...blocs);
  const form = hote.querySelector(".jn-form"), liste = hote.querySelector(".jn-liste");
  const fiche = hote.querySelector(".jn-grille > .jn-col:first-child");
  hote.querySelector(".jn-calendrier")?.remove(); hote.querySelector(".jn-vues")?.remove();
  hote.querySelector(":scope > .carte")?.remove();

  // ------------------------------------------------------------- panneau latéral « Nouvelle entrée » (7 étapes)
  const fond = h("div", "drawer-bg"), tiroir = h("aside", "drawer");
  tiroir.setAttribute("aria-label", "Nouvelle entrée"); tiroir.setAttribute("role", "dialog"); tiroir.setAttribute("aria-modal", "true");
  tiroir.innerHTML = `<header><div><span class="eyebrow" id="dStepTxt"></span><h3 style="font-size:18px" id="dStepT"></h3></div><button class="iconbtn" id="dClose" type="button" aria-label="Fermer (Échap)">✕</button></header>
    <div style="padding:0 22px"><div class="prog" id="dProg" style="margin-top:12px"></div></div><div class="body" id="dBody"></div>
    <footer><button class="btn" id="dPrev" type="button">Retour</button><span id="dSave">Brouillon gardé sur cet appareil</span><button class="btn pri" id="dNext" type="button">Continuer</button></footer>`;
  document.body.querySelectorAll(":scope > .drawer, :scope > .drawer-bg").forEach(x => x.remove());
  document.body.append(fond, tiroir);
  const corps = $("#dBody", tiroir);
  if (form) {
    corps.appendChild(form); form.classList.add("jn-panneau");
    form.querySelectorAll("fieldset > legend").forEach(l => { l.textContent = l.textContent.replace(/^\d+\s*·\s*/, ""); });   // l'étape est dans l'en-tête
  }
  let pas = 1, ouvert = false;
  const champs = () => form ? [...form.querySelectorAll("input:not([type=file]):not([type=checkbox]), select, textarea")] : [];
  function afficherPas() {
    $("#dStepTxt", tiroir).textContent = `Étape ${pas} sur 7`; $("#dStepT", tiroir).textContent = ETAPES[pas - 1];
    $("#dProg", tiroir).innerHTML = ETAPES.map((_, i) => `<i class="${i < pas ? "on" : ""}"></i>`).join("");
    form?.querySelectorAll("fieldset[data-pas]").forEach(f => { f.hidden = Number(f.dataset.pas) !== pas; });
    $("#dPrev", tiroir).disabled = pas === 1; $("#dNext", tiroir).textContent = pas === 7 ? "Enregistrer" : "Continuer";
    corps.scrollTop = 0;
  }
  function ouvrir(nouvelle = true, paire = null) {
    if (nouvelle) {
      form?.dispatchEvent(new CustomEvent("jn-vider"));
      if (paire) form?.dispatchEvent(new CustomEvent("jn-paire", { detail: paire }));
      try { const b = JSON.parse(store.get(BROUILLON) || "null"); if (b && !paire) champs().forEach((c, i) => { if (b[i] != null && c.value !== b[i]) { c.value = b[i]; } }); } catch (e) { /* brouillon illisible : ignoré */ }
    }
    pas = 1; afficherPas(); ouvert = true;
    tiroir.classList.add("open"); fond.classList.add("open");
    setTimeout(() => tiroir.querySelector("button, select, input")?.focus(), 50);
  }
  function fermer() { ouvert = false; tiroir.classList.remove("open"); fond.classList.remove("open"); }
  $("#dClose", tiroir).onclick = fermer; fond.onclick = fermer;
  $("#dPrev", tiroir).onclick = () => { if (pas > 1) { pas--; afficherPas(); } };
  $("#dNext", tiroir).onclick = () => { if (pas < 7) { pas++; afficherPas(); } else form?.requestSubmit(); };
  document.addEventListener("keydown", e => { if (e.key === "Escape" && ouvert) fermer(); });
  form?.addEventListener("input", () => { if (!form.querySelector(".jn-actions button[type=button]:not([hidden])")) store.set(BROUILLON, JSON.stringify(champs().map(c => c.value))); });
  form?.addEventListener("jn-edition", () => ouvrir(false));
  form?.addEventListener("jn-enregistre", () => { try { localStorage.removeItem(BROUILLON); } catch (e) { /* ignoré */ } fermer(); rendre(); });
  q("#newBtn").onclick = () => ouvrir(true);
  const basculerDemo = () => { demo = !demo; q("#jDemo").setAttribute("aria-pressed", demo); q("#jDemoTxt").hidden = !demo; rendre(); };
  q("#jDemo").onclick = basculerDemo;

  // Mes entrées (liste V2 : modifier, supprimer, exporter, importer) et fiche d'analyse : vue complète
  const v2 = q("#jV2");
  if (liste) { const c = h("div", "legacy journal-v7"); c.appendChild(liste); v2.appendChild(c); }
  if (fiche) v2.appendChild(blocDetaille("Fiche d'analyse de la paire", "calcul Python à chaque run, bougies et contributions", async () => [fiche]));

  async function trades() {
    if (demo) return exemples();
    try { return (await m.lireNotes()).map(versTrade).filter(Boolean); } catch (e) { return []; }
  }

  async function rendre() {
    const tr = await trades(), S = statistiques(tr);
    const vide = !S.n;
    // État d'accueil : aucun trade clôturé (hors démonstration) -> pas de page vide, deux actions bien visibles
    const accueil = vide && !demo;
    q("#jAccueil").hidden = !accueil; q("#jStats").hidden = accueil;
    if (accueil) {
      let ouvertes = 0;
      try { ouvertes = (await m.lireNotes()).length; } catch (e) { /* stockage indisponible */ }
      q("#jAccueil").innerHTML = `<svg class="j-acc-art" viewBox="0 0 320 120" aria-hidden="true"><path d="M8 100 L60 84 L104 92 L150 60 L196 70 L244 34 L312 20" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="6 9"/><circle cx="312" cy="20" r="7" fill="var(--up)"/></svg>
        <span class="eyebrow">Journal de progression</span>
        <h3>Ton premier trade apparaîtra ici</h3>
        <p>Note une entrée, clôture-la avec son résultat : le Journal calcule seul ta courbe en R, ta réussite par séance et par paire, et ce que tes trades disent du thème du jour. Tout reste sur cet appareil.</p>
        ${ouvertes ? `<p class="small">${ouvertes} entrée${ouvertes > 1 ? "s" : ""} enregistrée${ouvertes > 1 ? "s" : ""}, aucune clôturée avec un résultat : elles comptent dès leur clôture.</p>` : ""}
        <div class="j-acc-actions"><button class="btn pri" id="jAccNew" type="button">+ Nouvelle entrée</button><button class="btn" id="jAccDemo" type="button">Voir avec des exemples</button></div>`;
      q("#jAccNew").onclick = () => ouvrir(true);
      q("#jAccDemo").onclick = basculerDemo;
      return;
    }
    q("#jk").innerHTML = (vide ? [["Résultat", "—", "aucun trade clôturé"], ["Trades", "0", "clôture une entrée pour la compter"], ["Réussite", "—", ""], ["R moyen", "—", ""], ["Facteur de profit", "—", ""], ["Série en cours", "—", ""]]
      : [["Résultat", `<span class="${S.total_r >= 0 ? "pos" : "neg"}">${sgn(S.total_r, 1, " R")}</span>`, S.total_eur != null ? `soit ${sgn(S.total_eur, 0, " €")}` : "montant en € n/d"],
         ["Trades", String(S.n), S.sans_r ? `${S.sans_r} sans résultat en R` : `depuis le ${ddm(tr.map(t => t.d).sort()[0])}`],
         ["Réussite", S.reussite == null ? "n/d" : S.reussite + " %", `${S.gagnants} gagnant${S.gagnants > 1 ? "s" : ""}`],
         ["R moyen", sgn(S.r_moyen, 2), "par trade"], ["Facteur de profit", S.facteur_profit == null ? "n/d" : S.facteur_profit === Infinity ? "∞" : nf(S.facteur_profit, 2), "gains / pertes"],
         ["Série en cours", S.serie ? `${S.serie.n} ${S.serie.gagnante ? "gagnant" : "perdant"}${S.serie.n > 1 ? "s" : ""}` : "—", S.serie ? "dernier trade " + ddm(S.serie.dernier) : ""]])
      .map(k => `<div class="card kpi"><span>${k[0]}</span><b class="anim-num">${k[1]}</b><span class="small">${k[2]}</span></div>`).join("");
    const cum = S.courbe.map(c => c.r);
    q("#eq").innerHTML = cum.length > 1 ? spark([0, ...cum], 800, 220, S.total_r >= 0 ? "var(--up)" : "var(--down)", true).replace("<svg", '<svg class="trace" style="width:100%;height:100%"')
      : '<div class="empty">La courbe apparaît à partir de 2 trades clôturés avec un résultat en R.</div>';
    const [th, ...autres] = S.constats;
    q("#ins1").innerHTML = `<span class="eyebrow">Ce que tes trades disent</span><h3 style="font-family:var(--f-display);font-size:22px;font-weight:500">${esc(th.titre)}</h3>
      ${th.chiffre ? `<div class="vsrow"><div><span>Avec le thème</span><b class="${th.avec.reussite >= th.contre.reussite ? "pos" : "neg"}">${th.avec.reussite} %</b><span>${th.avec.n} trades · ${sgn(th.avec.moyenne, 2, " R")} en moyenne</span></div><div><span>Contre le thème</span><b class="${th.contre.reussite > th.avec.reussite ? "pos" : "neg"}">${th.contre.reussite} %</b><span>${th.contre.n} trades · ${sgn(th.contre.moyenne, 2, " R")} en moyenne</span></div></div>` : ""}
      <p>${esc(th.texte)} Le thème vient de la Synthèse au moment de l'entrée : le Journal l'enregistre seul.</p>`;
    q("#ins").innerHTML = autres.map(x => `<div class="card insight"><span class="eyebrow">${esc(x.titre)}</span><b style="font-size:24px;font-weight:600">${esc(x.chiffre || "—")}</b><p>${esc(x.texte)}</p></div>`).join("");
    const mx = Math.max(...S.par_paire.map(x => Math.abs(x[1])), 0.5) * 1.1;
    q("#byPair").innerHTML = S.par_paire.map(([k, v]) => hbar(k, v, mx, sgn(v, 1, " R"))).join("") || '<p class="muted">Aucun trade.</p>';
    const m2 = Math.max(...[...S.par_seance, ...S.par_jour].map(x => Math.abs(x[1].moyenne || 0)), 0.5) * 1.1;
    const ligne = ([k, g]) => hbar(`${k} <span class="small">${g.n}</span>`, g.moyenne, m2, g.moyenne == null ? "n/d" : sgn(g.moyenne, 2, " R"));
    q("#bySess").innerHTML = S.par_seance.map(ligne).join("") + '<div style="height:8px"></div>' + S.par_jour.map(ligne).join("");
    section.querySelectorAll("#byPair .hbar, #bySess .hbar").forEach(x => x.style.gridTemplateColumns = "110px minmax(0,1fr) 64px");
    // Calendrier mensuel en R
    const moisDispo = [...new Set([new Date().toISOString().slice(0, 7), ...tr.map(t => t.d.slice(0, 7))])].sort().slice(-3);
    if (!moisCal || !moisDispo.includes(moisCal)) moisCal = moisDispo[moisDispo.length - 1];
    const [y, mo] = moisCal.split("-").map(Number);
    q("#calT").textContent = MOIS[mo - 1].replace(/^./, c => c.toUpperCase()) + " " + y;
    q("#calSel").innerHTML = moisDispo.map(x => `<button type="button" data-m="${x}" aria-pressed="${x === moisCal}">${new Date(x + "-15T12:00:00Z").toLocaleString("fr-FR", { month: "short", timeZone: "UTC" })}</button>`).join("");
    q("#calSel").querySelectorAll("button").forEach(b => b.onclick = () => { moisCal = b.dataset.m; rendre(); });
    const jours = calendrierR(tr, moisCal), premier = (new Date(Date.UTC(y, mo - 1, 1)).getUTCDay() + 6) % 7, nbj = new Date(Date.UTC(y, mo, 0)).getUTCDate();
    let html = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map(x => `<span class="hd">${x}</span>`).join("") + '<span class="cell blank"></span>'.repeat(premier);
    for (let d = 1; d <= nbj; d++) { const iso = `${moisCal}-${String(d).padStart(2, "0")}`, v = jours[iso];
      html += `<div class="cell ${v == null ? "" : v >= 0 ? "w" : "l"}" style="min-height:58px;cursor:default"><span class="n">${d}</span>${v == null ? "" : `<span class="r ${v >= 0 ? "pos" : "neg"}">${sgn(v, 1, " R")}</span>`}</div>`; }
    q("#cal").innerHTML = html;
    // Tous les trades, filtrables par paire
    const pr = ["Toutes", ...new Set(tr.map(t => t.p))];
    if (!pr.includes(filtre)) filtre = "Toutes";
    q("#jFilt").innerHTML = pr.map(p => `<button type="button" data-p="${p}" aria-pressed="${p === filtre}">${p}</button>`).join("");
    q("#jFilt").querySelectorAll("button").forEach(b => b.onclick = () => { filtre = b.dataset.p; rendre(); });
    const lignes = tr.filter(t => filtre === "Toutes" || t.p === filtre).sort((a, b) => String(b.iso).localeCompare(String(a.iso)));
    q("#jTab").innerHTML = `<thead><tr><th>Date</th><th>Paire</th><th>Sens</th><th>Séance</th><th class="n">Confluences</th><th>Thème</th><th class="n">Résultat</th></tr></thead><tbody>` +
      (lignes.map(t => `<tr><td>${ddm(t.d)}</td><td><b>${t.p}</b></td><td>${esc(t.sens || "—")}</td><td>${esc(t.sess || "—")}</td><td class="n">${t.conf ?? "—"}</td><td>${t.theme == null ? '<span class="small">n/d</span>' : `<span class="chip ${t.theme ? "acc" : ""}" style="height:22px">${t.theme ? "avec" : "contre"}</span>`}</td><td class="n ${t.r >= 0 ? "pos" : "neg"}"><b>${t.r == null ? "n/d" : sgn(t.r, 1, " R")}</b></td></tr>`).join("")
       || `<tr><td colspan="7" class="muted">Aucun trade clôturé. Les entrées « Analyse seulement » ou « Position ouverte » n'entrent pas dans les statistiques.</td></tr>`) + "</tbody>";
    animerChiffres(section);
  }
  await rendre();
  const p = (parametre || "").match(/^nouvelle=([A-Z]{3}-[A-Z]{3})$/);
  if (p) { history.replaceState(null, "", "#journal"); ouvrir(true, p[1].replace("-", "/")); }
  section.ouvrirNouvelle = paire => ouvrir(true, paire);
}
