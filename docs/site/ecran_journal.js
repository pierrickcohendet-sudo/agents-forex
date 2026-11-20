/* Lot V11 — Journal selon docs/design/maquette_v11_journal.html.
   Accueil (option B) : 6 indicateurs, calendrier compact par semaines (5 jours ouvrés, week-end en petit, total de la
   semaine), courbe de résultat, panneau du jour. Page d'un trade (option A) : couverture, titre, propriétés, sous-onglets
   « Mon analyse » (éditeur par blocs du V10), « Photos » (galerie, légendes, unités, plein écran) et « Lecture du site »
   (archive Python contexte/). Vue liste (A) sur PC, fil de trades (C) par défaut sur téléphone.
   Le Journal est privé : IndexedDB sur l'appareil, rien n'est envoyé ; statistiques calculées sur l'appareil
   (journal_v5.js, fonctions pures). Stockage, export et import, migration V2 / V3 / V4 et démonstration conservés. */
import { $, h, sgn, nf, esc, MOIS, store, spark, blocDetaille, animerChiffres } from "./v7_commun.js";
import { chargerJson, enErreur } from "./commun.js";
import { exemples } from "./journal_stats.js";
import * as V4 from "./journal_v4.js";
import * as V5 from "./journal_v5.js";

const BROUILLON = "fxdesk-journal-brouillon-v5";
const VUE = "fxdesk-journal-vue";
const SETUPS = ["Retest de BOS", "Sweep + FVG", "Cassure de range", "Rejet de résistance", "Suite de tendance"];
const JL = V4.JOURS_SEM;
const telephone = () => matchMedia("(max-width: 700px)").matches;
const eur = v => v == null ? "n/d" : sgn(v, Number.isInteger(v) ? 0 : 2, " €");
const localMaintenant = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const versUtc = local => local ? new Date(local).toISOString() : null;      // heure de l'appareil -> UTC
const dateLongue = j => { const d = new Date(j + "T12:00:00Z"); return `${JL[d.getUTCDay()]} ${d.getUTCDate()} ${MOIS[d.getUTCMonth()]}`; };
const heure = n => String(n?.entree_locale || "").slice(11, 16);
const heureSortie = n => String(n?.sortie_locale || "").slice(11, 16);
const seance = n => { const hh = Number(String(n?.entree_utc || "").slice(11, 13)); return isNaN(hh) ? "" : hh < 7 ? "Asie" : hh < 12 ? "Londres" : hh < 21 ? "New York" : "Asie"; };
const titreTrade = n => `${/vente/i.test(n.sens) ? "Vente" : "Achat"} ${n.paire}`;
const fleche = n => /vente/i.test(n.sens) ? "▼" : "▲";
const resHtml = n => V5.aCompleter(n) ? '<span class="acompleter">résultat à compléter</span>'
  : V5.eurDe(n) != null ? `<span class="${V5.eurDe(n) >= 0 ? "pos" : "neg"}">${esc(eur(V5.eurDe(n)))}</span>` : `<span class="${V5.rDe(n) >= 0 ? "pos" : "neg"}">${esc(sgn(V5.rDe(n), 1, " R"))}</span>`;
const contexteTxt = n => Number.isFinite(n.lecture?.pour) ? `<b class="pos">${n.lecture.pour} pour</b> · <b class="neg">${n.lecture.contre} contre</b>` : '<span class="small">lecture du site à venir</span>';

let demo = false, mois = null, jourSel = null, vue = null, filtreFil = "Tous", rechercheL = "", selL = null, ongletPage = "analyse";
let toucheGlobale = null, collerGlobal = null;

/* Trades d'exemple (démonstration seulement, jamais enregistrés ni mélangés aux vrais). */
function notesDemo() {
  return exemples().map((t, i) => ({ version: 5, id: t.id, demo: true, paire: t.p, sens: t.sens,
    entree_locale: `${t.d}T${String(8 + (i * 5) % 9).padStart(2, "0")}:${i % 2 ? "30" : "05"}`, entree_utc: t.iso,
    sortie_locale: `${t.d}T${String(9 + (i * 5) % 9).padStart(2, "0")}:${i % 2 ? "10" : "45"}`, sortie_utc: new Date(Date.parse(t.iso) + (40 + i * 7 % 120) * 60000).toISOString(),
    resultat: { statut: "cloturee", pnl_eur: t.eur, r: t.r }, setup: [SETUPS[i % SETUPS.length]], lecture: { pour: Math.min(8, t.conf + 1), contre: Math.max(0, 3 - t.conf), neutres: 8 - Math.min(8, t.conf + 1) - Math.max(0, 3 - t.conf), nd: 0 },
    analyse: { blocs: [{ id: "d" + i, type: "paragraphe", texte: "Trade d'exemple : démonstration du Journal, rien n'est enregistré." }] }, captures: [], photos: [] }));
}

export async function ecranJournal(section, parametre) {
  section.classList.add("j5");
  section.innerHTML = `
    <div class="j5-tete"><div><span class="eyebrow">Mon journal</span><h2 style="font-size:32px">Mes trades</h2></div>
      <div class="act"><span class="note-ex" id="jDemoTxt" hidden>Trades d'exemple (démonstration)</span>
        <button class="switch" id="jDemo" type="button" aria-pressed="false"><i></i><span>Voir avec des exemples</span></button>
        <div class="seg" id="jVues" role="group" aria-label="Vue du journal"></div>
        <button class="btn pri" id="newBtn" type="button">+ Nouveau trade</button></div></div>
    <div id="jCorps" style="display:flex;flex-direction:column;gap:16px"></div>
    <div id="jV2" style="display:flex;flex-direction:column;gap:14px"></div>`;
  const q = s => $(s, section);
  const m = await import("./journal.js");
  const paires = await chargerJson("data/paires.json");
  const suivies = enErreur(paires) ? [] : (paires.mes_paires || []);
  const toutes = enErreur(paires) ? [] : [...suivies, ...(paires.paires || []).filter(p => !suivies.includes(p))];
  let notes = [];
  const urls = new Map();
  const urlCapture = (n, id) => { const c = (n?.captures || []).find(x => x.id === id); if (!c?.blob) return null;
    if (!urls.has(id)) urls.set(id, URL.createObjectURL(c.blob)); return urls.get(id); };
  const vignette = (n, cls = "", unite = null) => { const u = urlCapture(n, V5.couvertureDe(n));
    return `<span class="thumb ${cls}">${u ? `<img alt="" src="${u}">` : '<span class="vide">pas de photo</span>'}${unite ? `<span class="tf">${esc(unite)}</span>` : ""}</span>`; };

  async function charger() {
    if (demo) { notes = notesDemo(); return; }
    try {
      notes = [];
      for (const n of await m.lireNotes()) {      // migration V2, V3 et V4 -> V5 sans perte, écrite une seule fois
        const v = V5.migrerV5(n);
        if (v !== n) { try { await m.ecrireNote(v); } catch (e) { /* stockage en lecture seule : note migrée en mémoire */ } }
        notes.push(v);
      }
    } catch (e) { notes = []; q("#jCorps").innerHTML = `<div class="card pad muted">Journal indisponible sur cet appareil : ${esc(e.message || e)}</div>`; }
  }
  async function sauver(n) {
    if (n.demo) return;
    n.modifie_le = new Date().toISOString();
    await m.ecrireNote(n);
    const i = notes.findIndex(x => x.id === n.id); if (i >= 0) notes[i] = n; else notes.push(n);
  }
  /* Lecture du site calculée dès l'enregistrement (pour « N pour · M contre » et les statistiques). */
  async function lectureAuto(n) {
    if (n.demo) return;
    try {
      const { lire } = await import("./journal_lecture.js");
      const L = await lire(n);
      if (L?.o) { n.lecture = { pour: L.o.pour, contre: L.o.contre, neutres: L.o.neutres, nd: L.o.nd, instantane: L.inst.heure_utc }; await sauver(n); rendre(); }
    } catch (e) { /* archive indisponible : la lecture reste « à venir » */ }
  }

  // ------------------------------------------------------------------ éléments flottants : tiroir, saisie, visionneuse
  document.body.querySelectorAll(":scope > .j5-flottant").forEach(x => x.remove());
  const fond = h("div", "j5-dbg j5-flottant"), tiroir = h("aside", "j5-drw j5 j5-flottant"), modal = h("div", "j5-modal j5 j5-flottant"), lb = h("div", "j5-lb j5 j5-flottant");
  const fab = h("button", "j5-fab j5-flottant", "+ Nouveau trade"); fab.type = "button"; fab.hidden = true;
  tiroir.setAttribute("role", "dialog"); tiroir.setAttribute("aria-label", "Page du trade");
  tiroir.innerHTML = `<div class="bar"><span class="eyebrow" id="drwT"></span><button class="icn" id="drwX" type="button" aria-label="Fermer (Échap)">✕</button></div><div class="corps" id="drwB"></div>`;
  modal.setAttribute("role", "dialog"); modal.setAttribute("aria-modal", "true"); modal.setAttribute("aria-label", "Nouveau trade");
  lb.setAttribute("role", "dialog"); lb.setAttribute("aria-label", "Capture agrandie");
  document.body.append(fond, tiroir, modal, lb, fab);
  let editeurActif = null, tiroirPour = null;
  const fermerTout = () => { tiroir.classList.remove("open"); modal.classList.remove("open"); fond.classList.remove("open"); editeurActif?.detruire?.(); editeurActif = null; tiroirPour = null; rendre(); };
  $("#drwX", tiroir).onclick = fermerTout; fond.onclick = fermerTout;
  fab.onclick = () => ouvrirSaisie(localMaintenant().slice(0, 10));
  if (toucheGlobale) document.removeEventListener("keydown", toucheGlobale);
  toucheGlobale = e => {
    if (lb.classList.contains("open")) { if (e.key === "Escape") lb.classList.remove("open"); if (e.key === "ArrowRight") lb.suivante?.(1); if (e.key === "ArrowLeft") lb.suivante?.(-1); return; }
    if (e.key === "Escape" && !document.querySelector(".ed-menu:not([hidden])") && (modal.classList.contains("open") || tiroir.classList.contains("open"))) fermerTout();
  };
  document.addEventListener("keydown", toucheGlobale);

  // ------------------------------------------------------------------ saisie rapide (fenêtre « Nouveau trade »)
  function ouvrirSaisie(jour, note = null, paireInitiale = null) {
    if (demo) { demo = false; q("#jDemo").setAttribute("aria-pressed", "false"); q("#jDemoTxt").hidden = true; charger().then(rendre); }
    let b = null;
    if (!note) { try { b = JSON.parse(store.get(BROUILLON) || "null"); } catch (e) { b = null; } if (b && b.jour !== jour) b = null; }
    const v = note ? { paire: note.paire, sens: note.sens, entree: note.entree_locale, sortie: note.sortie_locale || "", res: V5.eurDe(note) ?? V5.rDe(note) ?? "", unite: V5.eurDe(note) == null && V5.rDe(note) != null ? "R" : "€", pips: note.resultat?.pips ?? "", risque: note.plan?.risque_eur ?? "" }
      : b || { paire: paireInitiale || suivies[0] || "", sens: "Achat", entree: `${jour}T${localMaintenant().slice(11, 16)}`, sortie: "", res: "", unite: "€", pips: "", risque: "" };
    let paire = v.paire, sens = v.sens || "Achat", unite = v.unite, multi = !!(v.sortie && v.sortie.slice(0, 10) !== String(v.entree).slice(0, 10));
    modal.innerHTML = `<header><div><span class="eyebrow">${esc(dateLongue(jour))} ${jour.slice(0, 4)}</span><h2>${note ? "Modifier le trade" : "Nouveau trade"}</h2></div><button class="icn" type="button" id="mX" aria-label="Fermer">✕</button></header>
      <form class="bd" novalidate>
        <div><span class="lbl">Paire</span><div class="pairs" id="mPairs"></div>
          <div class="autres" id="mAutres" hidden><input class="search" id="mCherche" type="search" placeholder="Rechercher une paire…" aria-label="Rechercher une paire"><ul id="mListe"></ul></div></div>
        <div><span class="lbl">Sens</span><div class="sens"><button type="button" class="a" data-s="Achat" aria-pressed="${sens === "Achat"}">▲ Achat</button><button type="button" class="v" data-s="Vente" aria-pressed="${sens === "Vente"}">▼ Vente</button></div></div>
        <div><span class="lbl">Durée</span><div class="times"><label><span class="small">Entrée</span><input id="tIn" type="time" value="${esc(String(v.entree || "").slice(11, 16))}"></label><span class="dur" id="dur">durée</span>
          <label><span class="small">Sortie</span><input id="tOut" type="time" value="${esc(String(v.sortie || "").slice(11, 16))}"></label></div>
          <label id="dOutL" ${multi ? "" : "hidden"} style="display:flex;flex-direction:column;gap:4px;margin-top:8px"><span class="small">Date de sortie</span><input id="dOut" type="date" value="${esc(String(v.sortie || "").slice(0, 10))}" style="height:44px;border-radius:12px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);padding:0 12px;font:inherit"></label>
          <div class="quick">${V4.RACCOURCIS.map(([l, mn]) => `<button type="button" class="chipb" data-q="${mn}">${l.replace(/^./, c => c.toUpperCase())}</button>`).join("")}</div></div>
        <div><span class="lbl">Résultat</span><div class="res-in"><input id="mRes" inputmode="decimal" placeholder="+110 ou −45" value="${esc(String(v.res ?? ""))}" aria-label="Résultat">
          <div class="seg" role="group" aria-label="Unité du résultat"><button type="button" data-u="€" aria-pressed="${unite === "€"}">€</button><button type="button" data-u="R" aria-pressed="${unite === "R"}">R</button></div></div>
          <details ${v.pips || v.risque ? "open" : ""}><summary class="small" style="cursor:pointer;margin-top:6px">Option : pips et risque prévu, pour calculer le R</summary>
            <div class="opts"><input id="mPips" inputmode="decimal" placeholder="Pips" aria-label="Pips" value="${esc(String(v.pips ?? ""))}"><input id="mRisque" inputmode="decimal" placeholder="Risque prévu en €" aria-label="Risque prévu en €" value="${esc(String(v.risque ?? ""))}"></div></details></div>
        <p class="err" id="mErr" role="alert"></p>
        <button class="btn pri" type="submit" style="height:48px;justify-content:center">${note ? "Enregistrer" : "Enregistrer et écrire mon analyse"}</button>
        ${note ? "" : '<span class="small muted" style="text-align:center">Brouillon gardé sur cet appareil si tu fermes sans enregistrer.</span>'}
      </form>`;
    const g = s => $(s, modal), f = modal.querySelector("form");
    const peindrePaires = () => {
      const base = suivies.length ? suivies : toutes.slice(0, 10);
      const liste = base.includes(paire) || !paire ? base : [...base, paire];
      g("#mPairs").innerHTML = liste.map(p => `<button type="button" class="chipb" data-p="${p}" aria-pressed="${p === paire}">${p}</button>`).join("")
        + `<button type="button" class="chipb" id="mPlus" aria-expanded="${!g("#mAutres").hidden}">+ ${Math.max(0, toutes.length - base.length)} autres…</button>`;
      g("#mPairs").querySelectorAll("[data-p]").forEach(x => x.onclick = () => { paire = x.dataset.p; peindrePaires(); brouillon(); });
      g("#mPlus").onclick = () => { g("#mAutres").hidden = !g("#mAutres").hidden; peindrePaires(); if (!g("#mAutres").hidden) { listeAutres(); g("#mCherche").focus(); } };
    };
    const listeAutres = () => {
      const t = g("#mCherche").value.toUpperCase().replace(/[^A-Z]/g, "");
      g("#mListe").innerHTML = toutes.filter(p => !suivies.includes(p) && (!t || p.replace("/", "").includes(t))).map(p => `<li><button type="button" class="chipb" data-o="${p}" aria-pressed="${p === paire}">${p}</button></li>`).join("") || '<li class="small muted">Aucune paire</li>';
      g("#mListe").querySelectorAll("[data-o]").forEach(x => x.onclick = () => { paire = x.dataset.o; g("#mAutres").hidden = true; peindrePaires(); brouillon(); });
    };
    g("#mCherche").addEventListener("input", listeAutres);
    g("#mCherche").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); const p = g("#mListe [data-o]"); if (p) p.click(); } });
    peindrePaires();
    modal.querySelectorAll("[data-s]").forEach(x => x.onclick = () => { sens = x.dataset.s; modal.querySelectorAll("[data-s]").forEach(y => y.setAttribute("aria-pressed", y.dataset.s === sens)); brouillon(); });
    modal.querySelectorAll("[data-u]").forEach(x => x.onclick = () => { unite = x.dataset.u; modal.querySelectorAll("[data-u]").forEach(y => y.setAttribute("aria-pressed", y.dataset.u === unite)); brouillon(); });
    const locaux = () => { const jIn = String(v.entree || `${jour}T00:00`).slice(0, 10) || jour;
      const ent = g("#tIn").value ? `${jour === jIn ? jIn : jour}T${g("#tIn").value}` : null;
      const jOut = multi && g("#dOut").value ? g("#dOut").value : (ent || jour).slice(0, 10);
      return { ent, sor: g("#tOut").value ? `${jOut}T${g("#tOut").value}` : null }; };
    const duree = () => { const { ent, sor } = locaux(); const mn = V4.minutesEntre(versUtc(ent), versUtc(sor)); g("#dur").textContent = mn == null ? "durée" : V4.dureeTexte(mn); };
    modal.querySelectorAll("[data-q]").forEach(x => x.onclick = () => {
      const { ent } = locaux(); if (!ent) return;
      const fin = V4.ajouterMinutesLocal(ent, Number(x.dataset.q));
      multi = fin.slice(0, 10) !== ent.slice(0, 10); g("#dOutL").hidden = !multi; g("#dOut").value = fin.slice(0, 10); g("#tOut").value = fin.slice(11, 16);
      duree(); brouillon(); });
    function brouillon() {
      if (note) return;
      const { ent, sor } = locaux();
      store.set(BROUILLON, JSON.stringify({ jour, paire, sens, entree: ent, sortie: sor, res: g("#mRes").value, unite, pips: g("#mPips").value, risque: g("#mRisque").value }));
    }
    f.addEventListener("input", () => { duree(); brouillon(); });
    duree();
    g("#mX").onclick = fermerTout;
    f.addEventListener("submit", async e => {
      e.preventDefault();
      const err = t => { g("#mErr").textContent = t; };
      if (!toutes.includes(paire)) return err("Choisis une paire.");
      const { ent, sor } = locaux();
      if (!ent) return err("Indique l'heure d'ouverture du trade.");
      if (sor && V4.minutesEntre(versUtc(ent), versUtc(sor)) == null) return err("La sortie doit venir après l'ouverture (pour un trade sur plusieurs jours, choisis « Plusieurs jours »).");
      const val = V4.nombreFrV4(g("#mRes").value), risque = V4.nombreFrV4(g("#mRisque").value);
      if (g("#mRes").value.trim() && val == null) return err("Résultat illisible (exemple : 110 ou −45,50).");
      const base = V4.noteV4({ id: note?.id, cree_le: note?.cree_le, paire, sens, entree_locale: ent, entree_utc: versUtc(ent), sortie_locale: sor, sortie_utc: versUtc(sor),
        pnl_eur: unite === "€" ? g("#mRes").value : (val != null && risque ? String(val * risque) : ""), pips: g("#mPips").value, risque_eur: g("#mRisque").value,
        captures: note?.captures, analyse: note?.analyse, lecture: null });
      if (unite === "R") base.resultat.r = val;
      const n = { ...(note || {}), ...base, version: 5, photos: note?.photos || [], setup: note?.setup || [], couverture: note?.couverture || null };
      try { await sauver(n); } catch (x) { return err(`Enregistrement impossible : ${x.message || x}`); }
      try { localStorage.removeItem(BROUILLON); } catch (x) { /* ignoré */ }
      modal.classList.remove("open");
      mois = n.entree_locale.slice(0, 7); jourSel = n.entree_locale.slice(0, 10);
      rendre();
      ouvrirPage(n, note ? ongletPage : "analyse");
      if (!note) setTimeout(() => document.querySelector(".j5-drw.open .ed-texte, #jPage .ed-texte")?.focus(), 250);   // écrire tout de suite
      lectureAuto(n);
    });
    modal.classList.add("open"); fond.classList.add("open");
    setTimeout(() => (modal.querySelector('.chipb[aria-pressed="true"]') || modal.querySelector(".chipb"))?.focus(), 80);
  }

  // ------------------------------------------------------------------ page d'un trade (option A)
  /* Ouvre la page : dans la vue liste sur PC (page complète), sinon dans le tiroir (plein écran sur téléphone). */
  function ouvrirPage(n, onglet = "analyse") {
    ongletPage = onglet;
    if (vue === "liste" && !telephone()) { selL = n.id; tiroir.classList.remove("open"); fond.classList.remove("open"); rendre(); return; }
    tiroirPour = n.id;
    $("#drwT", tiroir).textContent = `${dateLongue(V5.jourDe(n))} · ${n.paire}`;
    const corps = $("#drwB", tiroir); corps.replaceChildren(pageTrade(n));
    tiroir.classList.add("open"); fond.classList.add("open"); tiroir.scrollTop = 0;
  }
  function pageTrade(n) {
    editeurActif?.detruire?.(); editeurActif = null;
    const art = h("article", "card page");
    const cov = V5.couvertureDe(n), u = cov && urlCapture(n, cov), photos = V5.photosDe(n);
    const ph = photos.find(p => p.capture === cov);
    const d = V5.dureeMin(n);
    art.innerHTML = `${u ? `<div class="cover"><span class="thumb"><img alt="${esc(ph?.legende || "couverture")}" src="${u}">${ph?.unite ? `<span class="tf">${esc(ph.unite)}</span>` : ""}</span>${photos.length > 1 ? '<button type="button" class="btn sm chg">Changer la couverture</button>' : ""}</div>` : ""}
      <div class="pg">
        <div style="display:flex;flex-direction:column;gap:10px"><span class="eyebrow">${esc(dateLongue(V5.jourDe(n)))} · ${esc(seance(n) || "séance n/d")}${n.demo ? " · exemple" : ""}</span><h1>${esc(titreTrade(n))}</h1></div>
        <div class="props">
          <span>Résultat</span><span style="font-size:20px;font-weight:700">${V5.aCompleter(n) ? '<button type="button" class="btn sm" data-a="modifier">Résultat à compléter</button>' : `${resHtml(n)}${V5.rDe(n) != null && V5.eurDe(n) != null ? ` <span class="small">(${esc(sgn(V5.rDe(n), 1, " R"))})</span>` : V5.eurDe(n) != null ? ' <span class="small">(R n/d : risque prévu non saisi)</span>' : ""}`}</span>
          <span>Sens</span><span><span class="pill ${/vente/i.test(n.sens) ? "c" : "p"}">${fleche(n)} ${esc(/vente/i.test(n.sens) ? "Vente" : "Achat")}</span></span>
          <span>Durée</span><span>${esc(heure(n) || "n/d")} → ${esc(heureSortie(n) || "n/d")}${d != null ? ` · ${esc(V4.dureeTexte(d))}` : ""}</span>
          <span>Setup</span><span class="setup">${(n.setup || []).map((s, i) => `<span class="tag">${esc(s)}${n.demo ? "" : `<button type="button" data-rm="${i}" aria-label="Retirer ${esc(s)}">×</button>`}</span>`).join("")}${n.demo ? "" : '<input class="ajout" list="j5Setups" placeholder="+ ajouter un setup" aria-label="Ajouter un setup"><datalist id="j5Setups">' + SETUPS.map(s => `<option value="${esc(s)}">`).join("") + "</datalist>"}</span>
          <span>Contexte du site</span><span>${Number.isFinite(n.lecture?.pour) ? `<b class="pos">${n.lecture.pour} pour</b> · <b class="neg">${n.lecture.contre} contre</b> · ${n.lecture.neutres + (n.lecture.nd || 0)} neutres` : '<span class="small">calculé à l\'ouverture de « Lecture du site »</span>'}</span>
        </div>
        ${n.demo ? "" : '<div class="pg-actions"><button type="button" class="btn sm" data-a="modifier">Modifier le trade</button><button type="button" class="btn sm" data-a="supprimer">Supprimer</button><span class="small" data-conf hidden>Supprimer définitivement ce trade, son analyse et ses photos ? <button type="button" class="btn sm jn-danger" data-a="oui">Oui, supprimer</button> <button type="button" class="btn sm" data-a="non">Annuler</button></span></div>'}
        <div class="ptabs" role="tablist">${[["analyse", "Mon analyse", ""], ["photos", "Photos", photos.length], ["lecture", "Lecture du site", ""]].map(x => `<button type="button" role="tab" data-tab="${x[0]}" aria-selected="${ongletPage === x[0]}">${x[1]}${x[2] !== "" ? `<span class="cnt">${x[2]}</span>` : ""}</button>`).join("")}</div>
        <div class="pcorps"></div>
      </div>`;
    const corps = art.querySelector(".pcorps");
    art.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { ongletPage = b.dataset.tab; remplacer(n); });
    art.querySelector(".chg")?.addEventListener("click", async () => {
      const l = V5.photosDe(n), i = l.findIndex(p => p.capture === V5.couvertureDe(n));
      n.couverture = l[(i + 1) % l.length].capture; await sauver(n); remplacer(n); });
    art.querySelectorAll('[data-a="modifier"]').forEach(b => b.onclick = () => ouvrirSaisie(V5.jourDe(n), n));
    const conf = art.querySelector("[data-conf]");
    art.querySelector('[data-a="supprimer"]')?.addEventListener("click", () => { conf.hidden = false; conf.querySelector('[data-a="oui"]').focus(); });
    art.querySelector('[data-a="non"]')?.addEventListener("click", () => { conf.hidden = true; });
    art.querySelector('[data-a="oui"]')?.addEventListener("click", async () => {
      try { await m.supprimerNote(n.id); notes = notes.filter(x => x.id !== n.id); selL = null; fermerTout(); }
      catch (e) { conf.textContent = `Suppression impossible : ${e.message || e}`; } });
    art.querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => { n.setup.splice(+b.dataset.rm, 1); await sauver(n); remplacer(n); });
    const aj = art.querySelector("input.ajout");
    aj?.addEventListener("keydown", async e => { if (e.key === "Enter" && aj.value.trim()) { e.preventDefault(); n.setup = [...(n.setup || []), aj.value.trim()]; await sauver(n); remplacer(n, true); } });
    aj?.addEventListener("change", async () => { if (aj.value.trim() && SETUPS.includes(aj.value.trim())) { n.setup = [...(n.setup || []), aj.value.trim()]; await sauver(n); remplacer(n, true); } });
    if (ongletPage === "analyse") ongletAnalyse(n, corps);
    else if (ongletPage === "photos") ongletPhotos(n, corps);
    else ongletLecture(n, corps);
    return art;
  }
  function remplacer(n, focusSetup = false) {
    const ancien = tiroir.classList.contains("open") && tiroirPour === n.id ? $("#drwB", tiroir) : q("#jPage");
    if (!ancien) return;
    ancien.replaceChildren(pageTrade(n));
    if (focusSetup) ancien.querySelector("input.ajout")?.focus();
  }
  async function ongletAnalyse(n, corps) {
    const nb = V5.photosDe(n).length;
    if (nb) { const c = h("button", "callout"); c.type = "button"; c.innerHTML = `<span aria-hidden="true">🖼</span><span>${nb} capture${nb > 1 ? "s" : ""} avec légende dans l'onglet <b>Photos</b></span>`;
      c.onclick = () => { ongletPage = "photos"; remplacer(n); }; corps.appendChild(c); }
    const { editeur } = await import("./journal_editeur.js");
    editeurActif = editeur({
      blocs: n.analyse?.blocs || [], captures: n.captures || [], compresser: m.compresser,
      enregistrer: async (blocs, caps) => {
        if (n.demo) throw new Error("démonstration : rien n'est enregistré");
        n.analyse = { blocs }; n.captures = caps; n.photos = V5.synchroniser(n.photos, caps, blocs); n.contexte = V4.texteBrut(blocs);
        await sauver(n);
        const cnt = (tiroir.classList.contains("open") ? tiroir : section).querySelector('[data-tab="photos"] .cnt'); if (cnt) cnt.textContent = V5.photosDe(n).length;
      },
      modele: async () => { try { return (await m.lireMeta("modele_analyse"))?.valeur || null; } catch (e) { return null; } },
      enregistrerModele: async l => m.ecrireMeta("modele_analyse", l),
    });
    corps.appendChild(editeurActif);
  }
  function ongletPhotos(n, corps) {
    const l = V5.photosDe(n);
    corps.innerHTML = `<p class="small" style="margin:0 0 12px">Tes captures, chacune avec sa légende et son unité de temps. Glisse des images ici, colle-les (Ctrl+V) ou choisis des fichiers. Clic sur une image pour l'agrandir ; glisse ⋮⋮ pour réordonner.</p>
      <div class="gal">${l.map((p, i) => `<figure class="ph" draggable="${!n.demo}" data-i="${i}"><button type="button" class="img" data-zoom="${i}" aria-label="Agrandir la capture ${i + 1}"><img alt="${esc(p.legende || "capture " + (i + 1))}" src="${urlCapture(n, p.capture)}">${p.unite ? `<span class="tf">${esc(p.unite)}</span>` : ""}</button>
        <div class="meta"><span class="poignee" aria-hidden="true">⋮⋮</span><select data-u="${i}" aria-label="Unité de temps de la capture ${i + 1}"><option value="">Unité</option>${V5.UNITES_PHOTO.map(x => `<option ${x === p.unite ? "selected" : ""}>${x}</option>`).join("")}</select><button type="button" class="del" data-del="${i}">Supprimer</button></div>
        <textarea class="cap" data-cap="${i}" rows="3" placeholder="Ajoute une légende : ce que montre cette capture…" aria-label="Légende de la capture ${i + 1}">${esc(p.legende)}</textarea></figure>`).join("")}
        ${n.demo ? "" : '<label class="drop"><b>+ Ajouter des photos</b><span>Glisse, colle (Ctrl+V)<br>ou clique pour choisir</span><input type="file" accept="image/*" multiple hidden data-file></label>'}</div>
      <p class="small muted" id="phEtat" aria-live="polite"></p>`;
    const etat = $("#phEtat", corps);
    let minut = null;
    const sauverPlusTard = () => { etat.textContent = "Enregistrement…"; clearTimeout(minut); minut = setTimeout(async () => { await sauver(n); etat.textContent = "Enregistré"; }, 400); };
    corps.querySelectorAll("[data-cap]").forEach(t => t.addEventListener("input", () => {
      const p = l[+t.dataset.cap]; n.photos = V5.legender(n.photos, p.capture, t.value);
      for (const b of n.analyse?.blocs || []) if (b.type === "image" && b.capture === p.capture) b.legende = t.value;    // même légende dans l'analyse
      sauverPlusTard(); }));
    corps.querySelectorAll("[data-u]").forEach(s => s.onchange = async () => { const p = l[+s.dataset.u]; n.photos = V5.changerUnite(n.photos, p.capture, s.value);
      for (const b of n.analyse?.blocs || []) if (b.type === "image" && b.capture === p.capture && ["M30", "H1", "H4", "D1"].includes(s.value)) b.unite = s.value;
      await sauver(n); remplacer(n); });
    corps.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => { Object.assign(n, V5.supprimerPhoto(n, l[+b.dataset.del].capture)); await sauver(n); remplacer(n); });
    corps.querySelectorAll("[data-zoom]").forEach(b => b.onclick = () => visionneuse(n, +b.dataset.zoom));
    const inp = corps.querySelector("[data-file]"); if (inp) inp.onchange = () => ajouterPhotos(n, inp.files);
    const drop = corps.querySelector(".drop");
    if (drop) { drop.ondragover = e => { if (e.dataTransfer?.types?.includes("Files")) { e.preventDefault(); drop.classList.add("over"); } }; drop.ondragleave = () => drop.classList.remove("over");
      drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); ajouterPhotos(n, e.dataTransfer.files); }; }
    let glisse = null;   // réordonnancement par glisser
    corps.querySelectorAll(".ph").forEach(fig => {
      fig.addEventListener("dragstart", e => { if (e.target.closest("textarea, select")) { e.preventDefault(); return; } glisse = +fig.dataset.i; fig.classList.add("glisse"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(glisse)); });
      fig.addEventListener("dragover", e => { if (glisse != null) e.preventDefault(); });
      fig.addEventListener("drop", async e => { if (glisse == null) return; e.preventDefault(); const vers = +fig.dataset.i; const ordre = V5.deplacer(l, glisse, vers).map(p => p.capture);
        n.photos = ordre.map(c => n.photos.find(p => p.capture === c)); glisse = null; await sauver(n); remplacer(n); });
      fig.addEventListener("dragend", () => { glisse = null; fig.classList.remove("glisse"); });
    });
  }
  async function ajouterPhotos(n, fichiers) {
    if (n.demo) return;
    const imgs = [...(fichiers || [])].filter(f => f.type.startsWith("image/"));
    for (const f of imgs) {
      try { const c = await m.compresser(f); const cap = { id: crypto.randomUUID(), unites: [], ...c };
        n.captures = [...(n.captures || []), cap]; n.photos = [...(n.photos || []), { capture: cap.id, legende: "", unite: null }]; }
      catch (e) { /* image illisible : ignorée */ }
    }
    if (imgs.length) { await sauver(n); ongletPage = "photos"; remplacer(n); }
  }
  function visionneuse(n, i) {
    const l = V5.photosDe(n); if (!l.length) return;
    const k = (i + l.length) % l.length, p = l[k];
    lb.innerHTML = `<div class="fr"><img alt="${esc(p.legende || "capture")}" src="${urlCapture(n, p.capture)}"></div><p>${p.legende ? esc(p.legende) : '<span style="opacity:.6">Sans légende</span>'}</p>
      <div class="ctl"><button type="button" data-lb="-1" aria-label="Capture précédente">‹</button><span>${esc(p.unite || "unité n/d")} · ${k + 1} / ${l.length}</span><button type="button" data-lb="1" aria-label="Capture suivante">›</button><button type="button" data-lb="x" aria-label="Fermer (Échap)">✕</button></div>`;
    lb.suivante = d => visionneuse(n, k + d);
    lb.querySelectorAll("[data-lb]").forEach(b => b.onclick = e => { e.stopPropagation(); b.dataset.lb === "x" ? lb.classList.remove("open") : visionneuse(n, k + +b.dataset.lb); });
    lb.onclick = e => { if (e.target === lb) lb.classList.remove("open"); };
    lb.classList.add("open"); lb.querySelector('[data-lb="x"]').focus();
  }
  if (collerGlobal) document.removeEventListener("paste", collerGlobal);
  collerGlobal = e => {           // Ctrl+V quand l'onglet Photos est ouvert
    if (ongletPage !== "photos" || e.target.closest?.("textarea, input")) return;
    const id = tiroir.classList.contains("open") ? tiroirPour : (vue === "liste" ? selL : null);
    const n = notes.find(x => x.id === id); if (!n) return;
    const f = [...(e.clipboardData?.files || [])].filter(x => x.type.startsWith("image/"));
    if (f.length) { e.preventDefault(); ajouterPhotos(n, f); }
  };
  document.addEventListener("paste", collerGlobal);
  async function ongletLecture(n, corps) {
    const { ongletLecture: lecture } = await import("./journal_lecture.js");
    const { noeud, lecture: lu } = await lecture(n);
    corps.replaceChildren(noeud);
    if (lu && !n.demo && JSON.stringify(lu) !== JSON.stringify(n.lecture)) { n.lecture = lu; try { await sauver(n); } catch (e) { /* statistiques seulement */ } }
  }

  // ------------------------------------------------------------------ vues
  const rendreVues = () => {
    const l = telephone() ? [["fil", "Fil"], ["accueil", "Calendrier"]] : [["accueil", "Accueil"], ["liste", "Liste"]];
    if (!l.some(x => x[0] === vue)) vue = l[0][0];
    q("#jVues").innerHTML = l.map(([k, t]) => `<button type="button" data-v="${k}" aria-pressed="${k === vue}">${t}</button>`).join("");
    q("#jVues").querySelectorAll("[data-v]").forEach(b => b.onclick = () => { vue = b.dataset.v; store.set(VUE, vue); rendre(); });
    fab.hidden = vue !== "fil";
    q("#newBtn").hidden = vue === "fil";
  };
  function rendre() {
    mois = mois || localMaintenant().slice(0, 7);
    jourSel = jourSel || localMaintenant().slice(0, 10);
    rendreVues();
    const corps = q("#jCorps");
    if (vue === "liste") vueListe(corps); else if (vue === "fil") vueFil(corps); else vueAccueil(corps);
    animerChiffres(section);
  }
  function enteteMois(total = null) {
    const [y, mo] = mois.split("-").map(Number);
    return `<div class="sec-head"><h2>${MOIS[mo - 1].replace(/^./, c => c.toUpperCase())} ${y}${total != null ? ` <b class="${total >= 0 ? "pos" : "neg"}" style="font-size:16px">${esc(eur(total))}</b>` : ""}</h2>
      <div class="nav"><button type="button" class="icn" data-m="-1" aria-label="Mois précédent">‹</button><button type="button" class="btn sm" data-m="0">Aujourd'hui</button><button type="button" class="icn" data-m="1" aria-label="Mois suivant">›</button></div></div>`;
  }
  const brancherMois = racine => racine.querySelectorAll("[data-m]").forEach(b => b.onclick = () => {
    if (b.dataset.m === "0") { mois = localMaintenant().slice(0, 7); jourSel = localMaintenant().slice(0, 10); } else mois = V4.moisVoisin(mois, +b.dataset.m);
    rendre(); });
  const ouvrirDepuisListe = n => { if (V5.aCompleter(n) && !n.demo) ouvrirSaisie(V5.jourDe(n), n); else ouvrirPage(n, "analyse"); };

  /* ---- accueil (option B) */
  function vueAccueil(corps) {
    const S = V5.statsAccueil(notes, mois), W = V5.semainesMois(notes, mois), auj = localMaintenant().slice(0, 10);
    const moisNom = MOIS[Number(mois.slice(5, 7)) - 1];
    const kp = [["Résultat du mois", S.eur == null ? "—" : `<span class="${S.eur >= 0 ? "pos" : "neg"}">${esc(eur(S.eur))}</span>`, S.r == null ? "R n/d (risque prévu non saisi)" : sgn(S.r, 1, " R")],
      ["Trades", String(S.n), `en ${moisNom}${S.a_completer ? ` · ${S.a_completer} à compléter` : ""}`],
      ["Réussite", S.reussite == null ? "—" : `${S.reussite} %`, `${S.gagnants} gagnant${S.gagnants > 1 ? "s" : ""}`],
      ["Facteur de profit", S.facteur == null ? "—" : S.facteur === Infinity ? "∞" : nf(S.facteur, 2), "gains / pertes"],
      ["Gain moyen", S.gain_moyen == null ? "—" : esc(eur(S.gain_moyen)), `perte moy. ${S.perte_moyenne == null ? "—" : esc(eur(S.perte_moyenne))}`],
      ["Contexte favorable", S.favorable.reussite == null ? "—" : `${S.favorable.reussite} %`, `de réussite (${S.favorable.n} trade${S.favorable.n > 1 ? "s" : ""}, ${V5.FAVORABLE} moteurs ou plus) contre ${S.autres.reussite == null ? "—" : S.autres.reussite + " %"} pour les autres`]];
    let cal = ["Lun", "Mar", "Mer", "Jeu", "Ven"].map(x => `<span class="h">${x}</span>`).join("") + '<span class="h x">Sam</span><span class="h x">Dim</span><span class="h x">Semaine</span>';
    W.forEach((w, k) => {
      for (const j of w.jours) cal += `<button type="button" class="d ${j.week_end ? "we" : ""} ${j.hors_mois ? "out" : ""} ${j.classe} ${j.iso === auj ? "today" : ""}" data-d="${j.iso}" aria-pressed="${j.iso === jourSel}"
        aria-label="${esc(dateLongue(j.iso))}${j.n ? ` : ${j.n} trade${j.n > 1 ? "s" : ""}, ${j.eur == null ? "résultat à compléter" : eur(j.eur)}` : ""}"><span class="n">${j.jour}</span>${j.n ? `<span class="v ${j.eur > 0 ? "pos" : j.eur < 0 ? "neg" : ""}">${j.eur == null ? "à compléter" : esc(eur(j.eur))}</span><span class="c">${j.n} trade${j.n > 1 ? "s" : ""}</span>` : ""}</button>`;
      cal += `<div class="tot"><span>Sem. ${k + 1}</span><b class="${w.total.eur > 0 ? "pos" : w.total.eur < 0 ? "neg" : ""}">${w.total.n ? (w.total.eur == null ? "n/d" : esc(eur(w.total.eur))) : "—"}</b><span>${w.total.n} trade${w.total.n > 1 ? "s" : ""}</span></div>`;
    });
    const cum = V5.courbeCumul(notes, mois);
    const duJour = notes.filter(n => V5.jourDe(n) === jourSel).sort((a, b) => heure(a).localeCompare(heure(b)));
    corps.innerHTML = `<div class="kp">${kp.map(k => `<div class="card"><span>${k[0]}</span><b class="anim-num">${k[1]}</b><small>${k[2]}</small></div>`).join("")}</div>
      <div class="B"><div class="col">
        <div class="card pad" style="display:flex;flex-direction:column;gap:12px">${enteteMois()}<div class="cal" role="grid">${cal}</div></div>
        <div class="card pad" style="display:flex;flex-direction:column;gap:6px"><div class="sec-head"><h3>Courbe de résultat</h3><span class="small">cumul en € sur le mois</span></div>
          <div class="eq">${cum.length > 2 ? spark(cum, 800, 150, cum[cum.length - 1] >= 0 ? "var(--up)" : "var(--down)", true).replace("<svg", '<svg style="width:100%;height:100%"') : '<div class="empty">La courbe apparaît à partir de 2 trades avec un résultat en €.</div>'}</div></div>
      </div>
      <div class="dayp"><div class="card pad" style="display:flex;flex-direction:column;gap:10px"><div class="sec-head"><h3>${esc(dateLongue(jourSel).replace(/^./, c => c.toUpperCase()))}</h3>${demo ? "" : `<button type="button" class="btn sm" data-new="${jourSel}">+ Ajouter</button>`}</div>
        ${duJour.length ? duJour.map(n => `<button type="button" class="tcard" data-id="${esc(n.id)}">${vignette(n)}<span><b>${fleche(n)} ${esc(n.paire)} ${resHtml(n)}</b><small>${esc(heure(n))} → ${esc(heureSortie(n) || "n/d")}${(n.setup || []).length ? " · " + esc(n.setup.join(", ")) : ""}</small><small>${contexteTxt(n)} selon le site</small></span></button>`).join("")
          : `<div class="empty-day"><span>Aucun trade ce jour-là.</span>${demo ? "" : `<button type="button" class="btn pri sm" data-new="${jourSel}">+ Ajouter un trade</button>`}</div>`}
      </div></div></div>`;
    brancherMois(corps);
    corps.querySelectorAll(".d[data-d]").forEach(b => b.onclick = () => { jourSel = b.dataset.d; if (jourSel.slice(0, 7) !== mois) mois = jourSel.slice(0, 7); rendre(); });
    corps.querySelectorAll(".tcard").forEach(b => b.onclick = () => ouvrirDepuisListe(notes.find(n => n.id === b.dataset.id)));
    corps.querySelectorAll("[data-new]").forEach(b => b.onclick = () => ouvrirSaisie(b.dataset.new));
  }

  /* ---- vue liste (option A, PC) */
  function vueListe(corps) {
    const W = V5.semainesMois(notes, mois), auj = localMaintenant().slice(0, 10), S = V5.statsAccueil(notes, mois);
    let mini = ["L", "M", "M", "J", "V", "S", "D"].map(x => `<span class="h">${x}</span>`).join("");
    for (const w of W) for (const j of w.jours) mini += j.hors_mois ? '<span class="blank"></span>'
      : `<button type="button" class="${j.classe} ${j.iso === auj ? "today" : ""}" data-d="${j.iso}" title="${j.n ? `${j.n} trade${j.n > 1 ? "s" : ""} · ${j.eur == null ? "à compléter" : eur(j.eur)}` : "Aucun trade"}">${j.jour}</button>`;
    const trouves = V5.rechercher(notes, rechercheL);
    const groupes = V5.groupesSemaine(trouves);
    const sel = notes.find(n => n.id === selL) || groupes[0]?.trades[0] || null; selL = sel?.id || null;
    corps.innerHTML = `<div class="A"><div class="A-side">
        <div class="card pad" style="display:flex;flex-direction:column;gap:10px">${enteteMois(S.eur)}<div class="mini">${mini}</div><span class="small">Couleur : résultat du jour · clic : ouvre le premier trade du jour</span></div>
        <div class="card" style="padding:12px;display:flex;flex-direction:column;gap:8px"><input class="search" id="qL" type="search" placeholder="Rechercher une paire, un setup, une note, une légende…" value="${esc(rechercheL)}" aria-label="Rechercher dans le journal">
          <div class="list">${groupes.map(g => `<div class="wk"><span>Semaine du ${esc(dateLongue(g.lundi).replace(/^\S+ /, ""))}</span><span class="${g.total > 0 ? "pos" : g.total < 0 ? "neg" : ""}">${g.total == null ? "n/d" : esc(eur(g.total))}</span></div>`
            + g.trades.map(n => `<button type="button" class="item" data-id="${esc(n.id)}" aria-current="${n.id === selL}">${vignette(n)}<span><b>${fleche(n)} ${esc(n.paire)}</b><small>${esc(dateLongue(V5.jourDe(n)))}${(n.setup || []).length ? " · " + esc(n.setup[0]) : ""}</small></span><span class="r">${resHtml(n)}</span></button>`).join("")).join("")
            || `<p class="small muted" style="padding:8px">${rechercheL ? "Aucun trade ne correspond à la recherche." : "Aucun trade pour l'instant."}</p>`}</div>
          ${demo ? "" : '<button type="button" class="btn pri" style="justify-content:center" data-new="">+ Nouveau trade</button>'}</div></div>
      <div id="jPage">${sel ? "" : '<div class="card pad empty-day">Choisis un trade dans la liste, ou ajoute-en un.</div>'}</div></div>`;
    if (sel) $("#jPage", corps).replaceChildren(pageTrade(sel));
    brancherMois(corps);
    corps.querySelectorAll(".mini [data-d]").forEach(b => b.onclick = () => { const t = notes.filter(n => V5.jourDe(n) === b.dataset.d); if (t.length) { selL = t[0].id; rendre(); } else if (!demo) ouvrirSaisie(b.dataset.d); });
    corps.querySelectorAll(".item").forEach(b => b.onclick = () => { const n = notes.find(x => x.id === b.dataset.id); if (V5.aCompleter(n) && !n.demo) ouvrirSaisie(V5.jourDe(n), n); else { selL = n.id; ongletPage = "analyse"; rendre(); } });
    corps.querySelectorAll("[data-new]").forEach(b => b.onclick = () => ouvrirSaisie(b.dataset.new || localMaintenant().slice(0, 10)));
    const qL = $("#qL", corps);
    qL.oninput = () => { rechercheL = qL.value; const pos = qL.selectionStart; rendre(); const n2 = q("#qL"); n2?.focus(); n2?.setSelectionRange(pos, pos); };
  }

  /* ---- fil de trades (option C, téléphone) */
  function vueFil(corps) {
    const l = V5.filtrerFil(notes, filtreFil).sort((a, b) => String(b.entree_utc || V5.jourDe(b)).localeCompare(String(a.entree_utc || V5.jourDe(a))));
    const parJour = new Map(); for (const n of l) { const j = V5.jourDe(n); if (!parJour.has(j)) parJour.set(j, []); parJour.get(j).push(n); }
    const S = V5.statsAccueil(notes, mois), cum = V5.courbeCumul(notes, mois);
    const pr = [...new Set(notes.map(n => n.paire))];
    corps.innerHTML = `<div class="C"><div class="C-f">
        <div class="card pad" style="display:flex;flex-direction:column;gap:4px"><span class="small">${esc(MOIS[Number(mois.slice(5, 7)) - 1])}</span><b style="font-family:var(--f-display);font-size:30px;font-weight:500" class="${(S.eur || 0) >= 0 ? "pos" : "neg"}">${esc(eur(S.eur))}</b>
          <span class="small">${S.n} trade${S.n > 1 ? "s" : ""} · ${S.reussite == null ? "—" : S.reussite + " %"} gagnants</span>${cum.length > 2 ? spark(cum, 200, 40, cum[cum.length - 1] >= 0 ? "var(--up)" : "var(--down)", true).replace("<svg", '<svg style="width:100%;height:40px;margin-top:6px"') : ""}</div>
        <div><h3>Afficher</h3><div class="chips">${["Tous", "Gagnants", "Perdants"].map(x => `<button type="button" class="chipb" data-f="${x}" aria-pressed="${x === filtreFil}">${x}</button>`).join("")}</div></div>
        ${pr.length ? `<div><h3>Paire</h3><div class="chips">${pr.map(x => `<button type="button" class="chipb" data-f="${x}" aria-pressed="${x === filtreFil}">${x}</button>`).join("")}</div></div>` : ""}
      </div>
      <div class="feed">${[...parJour.entries()].map(([j, ts]) => { const e = ts.map(V5.eurDe).filter(v => v != null), t = e.length ? e.reduce((a, b) => a + b, 0) : null;
        return `<div class="fday"><header><b>${esc(dateLongue(j))}</b><b class="${t > 0 ? "pos" : t < 0 ? "neg" : ""}">${t == null ? "" : esc(eur(t))}</b></header>
        ${ts.map(n => `<article class="card fcard" data-id="${esc(n.id)}" tabindex="0" role="button" aria-label="${esc(titreTrade(n))}">${vignette(n, "", V5.photosDe(n).find(p => p.capture === V5.couvertureDe(n))?.unite)}<div class="bd"><div class="top"><div><span class="eyebrow">${esc(heure(n))} → ${esc(heureSortie(n) || "n/d")}${V5.dureeMin(n) != null ? " · " + esc(V4.dureeTexte(V5.dureeMin(n))) : ""}${seance(n) ? " · " + seance(n) : ""}</span><h3>${fleche(n)} ${esc(titreTrade(n))}</h3></div><span class="res">${resHtml(n)}</span></div>
          ${V5.resume(n) ? `<p>${esc(V5.resume(n))}</p>` : ""}
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">${(n.setup || []).map(s => `<span class="tag">${esc(s)}</span>`).join("")}${Number.isFinite(n.lecture?.pour) ? `<span class="small">Contexte :</span><div class="meter" style="width:120px;height:8px">${'<i class="p"></i>'.repeat(n.lecture.pour)}${'<i class="c"></i>'.repeat(n.lecture.contre)}${'<i class="n"></i>'.repeat(Math.max(0, 8 - n.lecture.pour - n.lecture.contre))}</div><span class="small">${contexteTxt(n)}</span>` : '<span class="small">lecture du site à venir</span>'}</div></div></article>`).join("")}</div>`; }).join("")
        || `<div class="empty-day">${notes.length ? "Aucun trade pour ce filtre." : "Aucun trade pour l'instant : touche « + Nouveau trade »."}</div>`}</div></div>`;
    corps.querySelectorAll("[data-f]").forEach(b => b.onclick = () => { filtreFil = b.dataset.f; rendre(); });
    corps.querySelectorAll(".fcard").forEach(c => { const go = () => ouvrirDepuisListe(notes.find(n => n.id === c.dataset.id)); c.onclick = go; c.onkeydown = e => { if (e.key === "Enter") go(); }; });
  }

  // ------------------------------------------------------------------ branchements
  q("#newBtn").onclick = () => ouvrirSaisie(vue === "accueil" ? jourSel || localMaintenant().slice(0, 10) : localMaintenant().slice(0, 10));
  q("#jDemo").onclick = async () => { demo = !demo; q("#jDemo").setAttribute("aria-pressed", demo); q("#jDemoTxt").hidden = !demo; selL = null; await charger(); rendre(); };
  const v2 = q("#jV2");
  v2.appendChild(blocDetaille("Sauvegarde : exporter et importer mes trades", "fichier .json, photos comprises", async () => {
    const blocs = await m.pageJournal(); const hote = h("div", "legacy journal-v7"); hote.append(...blocs);
    const liste = hote.querySelector(".jn-liste"); const c = h("div", "legacy journal-v7"); if (liste) c.appendChild(liste);
    return [c];
  }));
  v2.appendChild(blocDetaille("Fiche d'analyse de la paire", "calcul Python à chaque run, bougies et contributions", async () => {
    const blocs = await m.pageJournal(); const hote = h("div", "legacy journal-v7"); hote.append(...blocs);
    return [hote.querySelector(".jn-grille > .jn-col:first-child") || h("p", "muted", "Fiche indisponible")];
  }));
  vue = store.get(VUE) || null;
  if (telephone() && vue === "liste") vue = "fil";
  if (!vue) vue = telephone() ? "fil" : "accueil";
  await charger();
  rendre();
  // Passage PC <-> téléphone (rotation, fenêtre redimensionnée) : vue par défaut de chaque format
  const mq = matchMedia("(max-width: 700px)");
  mq.addEventListener?.("change", () => { vue = mq.matches ? "fil" : (store.get(VUE) === "liste" ? "liste" : "accueil"); rendre(); });
  const p = (parametre || "").match(/^nouvelle=([A-Z]{3}-[A-Z]{3})$/);
  if (p) { history.replaceState(null, "", "#journal"); ouvrirSaisie(localMaintenant().slice(0, 10), null, p[1].replace("-", "/")); }
  section.ouvrirNouvelle = paire => ouvrirSaisie(localMaintenant().slice(0, 10), null, paire);
}
