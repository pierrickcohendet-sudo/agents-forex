/* Lot V10 — Journal V4 (calendrier façon Notion). Vue principale : le calendrier du mois (bilan du mois au-dessus,
   statistiques plus bas). Clic sur un jour : panneau (latéral sur PC, plein écran sur téléphone) avec les trades du jour
   et la saisie rapide ; chaque entrée a deux onglets : « Mon analyse » (page libre par blocs, écrite par l'utilisateur)
   et « Lecture du site » (contexte archivé en Python, orienté selon le sens du trade). Stockage IndexedDB, export et
   import, statistiques et migration V2 / V3 conservés (journal.js, journal_stats.js). Démonstration jamais mélangée. */
import { $, h, sgn, nf, esc, ddm, MOIS, store, spark, hbar, blocDetaille, animerChiffres } from "./v7_commun.js";
import { chargerJson, enErreur } from "./commun.js";
import { statistiques, versTrade, exemples } from "./journal_stats.js";
import * as V4 from "./journal_v4.js";

const BROUILLON = "fxdesk-journal-brouillon-v4";
const ONGLETS = [["analyse", "Mon analyse"], ["lecture", "Lecture du site"], ["trade", "Le trade"]];
const telephone = () => matchMedia("(max-width: 700px)").matches;
const eur = v => v == null ? "n/d" : sgn(v, Number.isInteger(v) ? 0 : 2, " €");
const localMaintenant = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const versUtc = local => local ? new Date(local).toISOString() : null;     // heure de l'appareil -> UTC
const dateLongue = iso => { const d = new Date(iso + "T12:00:00Z"); return `${V4.JOURS_SEM[d.getUTCDay()]} ${d.getUTCDate()} ${MOIS[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };

const SQUELETTE = `
<div class="sec-head"><div><span class="eyebrow">Mon journal</span><h2 style="font-size:32px">Mes trades, jour par jour</h2></div>
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><span class="note-ex" id="jDemoTxt" hidden>Trades d'exemple (démonstration)</span>
    <button class="switch" id="jDemo" type="button" aria-pressed="false"><i></i><span>Voir avec des exemples</span></button>
    <button class="btn pri" id="newBtn" type="button">+ Ajouter un trade</button></div></div>
<div class="grid j4-bilan" id="jBilan"></div>
<div class="card pad j4-cal">
  <div class="j4-cal-tete"><button class="iconbtn" id="mPrev" type="button" aria-label="Mois précédent">‹</button><h3 id="mTitre" aria-live="polite"></h3>
    <button class="iconbtn" id="mNext" type="button" aria-label="Mois suivant">›</button><button class="btn" id="mAuj" type="button">Aujourd'hui</button></div>
  <div class="j4-grille" id="cal4" role="grid"></div>
</div>
<div class="card pad j4-jour" id="jJour" hidden></div>
<div id="jStats" class="j-stats">
<div class="sec-head" style="margin-top:6px"><h2 style="font-size:24px">Statistiques</h2><span class="small">sur les trades clôturés, calculées sur cet appareil</span></div>
<div class="grid jk" id="jk"></div>
<div class="cols2" style="grid-template-columns:minmax(0,1.5fr) minmax(0,1fr)">
  <div class="card pad" style="display:flex;flex-direction:column;gap:8px"><div class="sec-head"><h3>Courbe de résultat cumulé</h3><span class="small">en R (1 R = le risque prévu du trade)</span></div><div class="eq" id="eq"></div></div>
  <div class="card insight" id="ins1"></div>
</div>
<div class="cols3" id="ins"></div>
<div class="card insight" id="insCtx"></div>
<div class="cols2">
  <div class="card pad" style="display:flex;flex-direction:column;gap:6px"><div class="sec-head"><h3>Par paire</h3><span class="small">R total</span></div><div id="byPair"></div></div>
  <div class="card pad" style="display:flex;flex-direction:column;gap:6px"><div class="sec-head"><h3>Par séance et par jour</h3><span class="small">R moyen · nombre de trades</span></div><div id="bySess"></div></div>
</div>
<div class="card" style="overflow:hidden"><div class="pad" style="padding-bottom:4px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center"><h3>Tous les trades</h3><div class="seg" id="jFilt" role="group" aria-label="Filtrer par paire"></div></div><div class="scroll"><table class="tbl" id="jTab" style="min-width:620px"></table></div></div>
</div>
<div id="jV2" style="display:flex;flex-direction:column;gap:14px"></div>`;

let demo = false, mois = null, jourSel = null, filtre = "Toutes";

/* Trades d'exemple au format V4 (démonstration seulement, jamais enregistrés). */
function notesDemo() {
  return exemples().map((t, i) => ({ version: 4, id: t.id, demo: true, paire: t.p, sens: t.sens,
    entree_locale: `${t.d}T${String(8 + (i * 5) % 9).padStart(2, "0")}:${i % 2 ? "30" : "05"}`, entree_utc: t.iso, sortie_utc: null,
    resultat: { statut: "cloturee", pnl_eur: t.eur, r: t.r }, stats: { seance: t.sess, confluences: t.conf, avec_theme: t.theme, sens: t.sens },
    analyse: { blocs: [] }, captures: [] }));
}

export async function ecranJournal(section, parametre) {
  section.innerHTML = SQUELETTE;
  const q = s => $(s, section);
  const m = await import("./journal.js");
  const paires = await chargerJson("data/paires.json");
  const suivies = enErreur(paires) ? [] : (paires.mes_paires || []);
  const toutes = enErreur(paires) ? [] : [...suivies, ...(paires.paires || []).filter(p => !suivies.includes(p))];
  let notes = [];

  async function charger() {
    if (demo) { notes = notesDemo(); return; }
    try {
      const brutes = await m.lireNotes();
      notes = [];
      for (const n of brutes) {   // migration V2 et V3 -> V4, sans perte, écrite une seule fois
        const v = V4.migrerV4(n);
        if (v !== n) { try { await m.ecrireNote(v); } catch (e) { /* lecture seule : la note migrée reste en mémoire */ } }
        notes.push(v);
      }
    } catch (e) { notes = []; q("#jBilan").innerHTML = `<div class="card pad muted">Journal indisponible : ${esc(e.message || e)}</div>`; }
  }

  // ------------------------------------------------------------------ panneau (latéral sur PC, plein écran sur téléphone)
  document.body.querySelectorAll(":scope > .drawer, :scope > .drawer-bg").forEach(x => x.remove());
  const fond = h("div", "drawer-bg"), tiroir = h("aside", "drawer j4-panneau");
  tiroir.setAttribute("role", "dialog"); tiroir.setAttribute("aria-modal", "true"); tiroir.setAttribute("aria-label", "Journal du jour");
  tiroir.innerHTML = `<header><div><span class="eyebrow" id="pSur"></span><h3 style="font-size:18px" id="pTitre"></h3></div><button class="iconbtn" id="pFermer" type="button" aria-label="Fermer (Échap)">✕</button></header><div class="body" id="pCorps"></div>`;
  document.body.append(fond, tiroir);
  const corps = $("#pCorps", tiroir);
  let ouvert = false, editeurActif = null, retourJour = null;
  function ouvrirPanneau() { ouvert = true; tiroir.classList.add("open"); fond.classList.add("open"); setTimeout(() => tiroir.querySelector("#pCorps button, #pCorps input")?.focus(), 60); }
  function fermer() {
    ouvert = false; tiroir.classList.remove("open"); fond.classList.remove("open");
    editeurActif?.detruire?.(); editeurActif = null; rendre();
  }
  $("#pFermer", tiroir).onclick = fermer; fond.onclick = fermer;
  const surTouche = e => { if (e.key === "Escape" && ouvert && !document.querySelector(".ed-zoom")) fermer(); };
  document.addEventListener("keydown", surTouche);
  const titre = (sur, t) => { $("#pSur", tiroir).textContent = sur; $("#pTitre", tiroir).textContent = t; };

  // ---- vue « jour » : les trades du jour et « + Ajouter un trade »
  function vueJour(jour) {
    editeurActif?.detruire?.(); editeurActif = null; retourJour = jour;
    const duJour = notes.filter(n => String(n.entree_locale || n.date_heure || "").startsWith(jour)).sort((a, b) => String(a.entree_locale).localeCompare(String(b.entree_locale)));
    if (!duJour.length && !demo) { vueSaisie(jour); return; }
    titre(dateLongue(jour), duJour.length ? `${duJour.length} trade${duJour.length > 1 ? "s" : ""}` : "Aucun trade");
    corps.replaceChildren(listeJour(duJour, jour));
  }
  function listeJour(duJour, jour) {
    const z = h("div", "j4-liste");
    for (const n of duJour) {
      const v = n.resultat?.pnl_eur ?? null, d = V4.minutesEntre(n.entree_utc, n.sortie_utc);
      const b = h("button", `j4-trade ${v > 0 ? "gain" : v < 0 ? "perte" : ""}`); b.type = "button";
      b.innerHTML = `<b>${esc(n.paire)}</b><span class="chip ${/vente/i.test(n.sens) ? "dn" : "up"}" style="height:22px">${esc(n.sens || "sens n/d")}</span>
        <span class="small">${esc(String(n.entree_locale || "").slice(11, 16))}${n.sortie_locale ? ` → ${esc(n.sortie_locale.slice(11, 16))} · ${esc(V4.dureeTexte(d))}` : ""}</span>
        <b class="tabulaire ${v > 0 ? "pos" : v < 0 ? "neg" : ""}">${esc(eur(v))}</b>`;
      b.onclick = () => vueEntree(n, "analyse");
      z.appendChild(b);
    }
    if (demo) z.appendChild(h("p", "small muted", "Démonstration : ces trades d'exemple ne sont jamais enregistrés. Désactive « Voir avec des exemples » pour ajouter les tiens."));
    else { const a = h("button", "btn pri", "+ Ajouter un trade"); a.type = "button"; a.onclick = () => vueSaisie(jour); z.appendChild(a); }
    return z;
  }

  // ---- vue « saisie rapide » : paire, sens, durée, résultat, en un seul écran
  function vueSaisie(jour, note = null, paireInitiale = null) {
    editeurActif?.detruire?.(); editeurActif = null;
    let b = null;
    if (!note) { try { b = JSON.parse(store.get(BROUILLON) || "null"); } catch (e) { b = null; } if (b && b.jour !== jour) b = null; }
    const v = note ? { paire: note.paire, sens: note.sens, entree: note.entree_locale, sortie: note.sortie_locale, pnl: note.resultat?.pnl_eur ?? "", pips: note.resultat?.pips ?? "", risque: note.plan?.risque_eur ?? "" }
      : b || { paire: paireInitiale || "", sens: "", entree: `${jour}T${localMaintenant().slice(11, 16)}`, sortie: "", pnl: "", pips: "", risque: "" };
    titre(dateLongue(jour), note ? `Modifier · ${note.paire}` : "Ajouter un trade");
    const f = h("form", "j4-saisie"); f.noValidate = true;
    f.innerHTML = `
      <label class="j4-champ"><span>Paire</span><div class="j4-combo"><input id="sPaire" type="search" autocomplete="off" placeholder="Rechercher : USD/JPY, eur…" value="${esc(v.paire)}" role="combobox" aria-expanded="false" aria-controls="sPaires" aria-autocomplete="list"><ul id="sPaires" role="listbox" hidden></ul></div></label>
      <div class="j4-champ"><span>Sens</span><div class="seg" role="group" aria-label="Sens"><button type="button" data-s="Achat" aria-pressed="${v.sens === "Achat"}">Achat</button><button type="button" data-s="Vente" aria-pressed="${v.sens === "Vente"}">Vente</button></div></div>
      <div class="j4-duo"><label class="j4-champ"><span>Entrée</span><input id="sEntree" type="datetime-local" value="${esc(v.entree || "")}"></label>
        <label class="j4-champ"><span>Sortie</span><input id="sSortie" type="datetime-local" value="${esc(v.sortie || "")}"></label></div>
      <div class="j4-duree"><span class="small">Durée : <b id="sDuree">n/d</b></span><span class="seg" role="group" aria-label="Raccourcis de durée">${V4.RACCOURCIS.map(([l, mn]) => `<button type="button" data-m="${mn}">${l}</button>`).join("")}</span></div>
      <label class="j4-champ"><span>Résultat en €</span><input id="sPnl" inputmode="decimal" placeholder="+120 ou −45" value="${esc(String(v.pnl ?? ""))}"></label>
      <details class="j4-options" ${v.pips || v.risque ? "open" : ""}><summary>Pips et risque prévu (pour le R)</summary>
        <div class="j4-duo"><label class="j4-champ"><span>Pips</span><input id="sPips" inputmode="decimal" value="${esc(String(v.pips ?? ""))}"></label>
        <label class="j4-champ"><span>Risque prévu en €</span><input id="sRisque" inputmode="decimal" value="${esc(String(v.risque ?? ""))}"></label></div></details>
      <p class="j4-erreur" id="sErreur" role="alert"></p>
      <div class="j4-actions"><button type="button" class="btn" id="sRetour">Retour</button><span class="small muted" id="sBrouillon">${note ? "" : "Brouillon gardé sur cet appareil"}</span><button type="submit" class="btn pri">Enregistrer</button></div>`;
    corps.replaceChildren(f);
    const g = s => $(s, f);
    let sens = v.sens || "";
    // Paire : 36 paires, recherche au clavier, les 10 suivies en premier
    const champ = g("#sPaire"), ul = g("#sPaires");
    let actif = -1;
    const options = () => { const t = champ.value.trim().toUpperCase().replace(/[^A-Z]/g, ""); return toutes.filter(p => !t || p.replace("/", "").includes(t)); };
    function liste() {
      const o = options(); actif = Math.min(actif, o.length - 1);
      ul.innerHTML = o.map((p, i) => `${i === 0 && suivies.includes(p) ? '<li class="j4-grp" role="presentation">Paires suivies</li>' : ""}${i > 0 && suivies.includes(o[i - 1]) && !suivies.includes(p) ? '<li class="j4-grp" role="presentation">Autres paires</li>' : ""}<li role="option" data-p="${p}" aria-selected="${i === actif}">${p}</li>`).join("");
      ul.hidden = !o.length || document.activeElement !== champ; champ.setAttribute("aria-expanded", String(!ul.hidden));
    }
    champ.addEventListener("focus", liste); champ.addEventListener("input", () => { actif = 0; liste(); brouillon(); });
    champ.addEventListener("blur", () => setTimeout(() => { ul.hidden = true; champ.setAttribute("aria-expanded", "false"); }, 150));
    champ.addEventListener("keydown", e => {
      const o = options();
      if (e.key === "ArrowDown") { e.preventDefault(); actif = Math.min(o.length - 1, actif + 1); liste(); }
      if (e.key === "ArrowUp") { e.preventDefault(); actif = Math.max(0, actif - 1); liste(); }
      if (e.key === "Enter" && !ul.hidden && o[Math.max(0, actif)]) { e.preventDefault(); champ.value = o[Math.max(0, actif)]; ul.hidden = true; brouillon(); }
    });
    ul.addEventListener("mousedown", e => { const p = e.target.closest("[data-p]")?.dataset.p; if (p) { e.preventDefault(); champ.value = p; ul.hidden = true; brouillon(); } });
    f.querySelectorAll("[data-s]").forEach(bt => bt.onclick = () => { sens = bt.dataset.s; f.querySelectorAll("[data-s]").forEach(x => x.setAttribute("aria-pressed", x.dataset.s === sens)); brouillon(); });
    const duree = () => { g("#sDuree").textContent = V4.dureeTexte(V4.minutesEntre(versUtc(g("#sEntree").value), versUtc(g("#sSortie").value))); };
    f.querySelectorAll("[data-m]").forEach(bt => bt.onclick = () => { if (g("#sEntree").value) { g("#sSortie").value = V4.ajouterMinutesLocal(g("#sEntree").value, Number(bt.dataset.m)); duree(); brouillon(); } });
    function brouillon() {
      if (note) return;
      store.set(BROUILLON, JSON.stringify({ jour, paire: champ.value, sens, entree: g("#sEntree").value, sortie: g("#sSortie").value, pnl: g("#sPnl").value, pips: g("#sPips").value, risque: g("#sRisque").value }));
    }
    f.addEventListener("input", () => { duree(); brouillon(); });
    duree();
    g("#sRetour").onclick = () => { if (notes.some(n => String(n.entree_locale || "").startsWith(jour))) vueJour(jour); else fermer(); };
    f.addEventListener("submit", async e => {
      e.preventDefault();
      const err = t => { g("#sErreur").textContent = t; };
      const paire = champ.value.trim().toUpperCase();
      if (!toutes.includes(paire)) return err("Choisis une paire dans la liste des 36 paires.");
      if (!sens) return err("Choisis le sens : achat ou vente.");
      const entree = g("#sEntree").value, sortie = g("#sSortie").value;
      if (!entree) return err("Indique l'heure d'entrée.");
      if (sortie && V4.minutesEntre(versUtc(entree), versUtc(sortie)) == null) return err("La sortie doit venir après l'entrée.");
      if (g("#sPnl").value.trim() && V4.nombreFrV4(g("#sPnl").value) == null) return err("Résultat en € illisible (exemple : 120 ou −45,50).");
      const n = V4.noteV4({ id: note?.id, cree_le: note?.cree_le, paire, sens, entree_locale: entree, entree_utc: versUtc(entree), sortie_locale: sortie || null, sortie_utc: versUtc(sortie),
        pnl_eur: g("#sPnl").value, pips: g("#sPips").value, risque_eur: g("#sRisque").value, captures: note?.captures, analyse: note?.analyse, lecture: null });
      if (note) for (const k of Object.keys(note)) if (!(k in n)) n[k] = note[k];     // champs V2 / V3 conservés
      try { await m.ecrireNote(n); } catch (x) { return err(`Enregistrement impossible : ${x.message || x}`); }
      try { localStorage.removeItem(BROUILLON); } catch (x) { /* ignoré */ }
      await charger(); mois = n.entree_locale.slice(0, 7); jourSel = n.entree_locale.slice(0, 10); rendre();
      vueEntree(notes.find(x => x.id === n.id) || n, "analyse");
    });
    if (!ouvert) ouvrirPanneau();
    setTimeout(() => (champ.value ? g("[data-s]") : champ).focus(), 80);
  }

  // ---- vue « entrée » : Mon analyse, Lecture du site, Le trade
  async function vueEntree(note, onglet = "analyse") {
    editeurActif?.detruire?.(); editeurActif = null;
    const jour = String(note.entree_locale || note.date_heure || "").slice(0, 10);
    const v = note.resultat?.pnl_eur ?? null;
    titre(`${dateLongue(jour)} · ${String(note.entree_locale || "").slice(11, 16)}`, `${note.paire} · ${note.sens || "sens n/d"} · ${eur(v)}`);
    const z = h("div", "j4-entree");
    z.innerHTML = `<div class="j4-entree-tete"><button type="button" class="btn" id="eRetour">← ${esc(ddm(jour))}</button>
      <div class="seg j4-onglets" role="tablist">${ONGLETS.map(([k, l]) => `<button type="button" role="tab" data-o="${k}" aria-selected="${k === onglet}" aria-pressed="${k === onglet}">${l}</button>`).join("")}</div></div><div id="eCorps"></div>`;
    corps.replaceChildren(z);
    $("#eRetour", z).onclick = () => vueJour(jour);
    z.querySelectorAll("[data-o]").forEach(b => b.onclick = () => vueEntree(notes.find(x => x.id === note.id) || note, b.dataset.o));
    const cible = $("#eCorps", z);
    if (onglet === "analyse") {
      const { editeur } = await import("./journal_editeur.js");
      editeurActif = editeur({
        blocs: note.analyse?.blocs || [], captures: note.captures || [], compresser: m.compresser,
        enregistrer: async (blocs, caps) => {
          if (note.demo) throw new Error("démonstration : rien n'est enregistré");
          note.analyse = { blocs }; note.captures = caps; note.contexte = V4.texteBrut(blocs); note.modifie_le = new Date().toISOString();
          await m.ecrireNote(note);
        },
        modele: async () => { try { return (await m.lireMeta("modele_analyse"))?.valeur || null; } catch (e) { return null; } },
        enregistrerModele: async l => m.ecrireMeta("modele_analyse", l),
      });
      cible.replaceChildren(editeurActif);
      setTimeout(() => editeurActif?.querySelector(".ed-texte")?.focus(), 80);
    } else if (onglet === "lecture") {
      const { ongletLecture } = await import("./journal_lecture.js");
      const { noeud, lecture } = await ongletLecture(note);
      cible.replaceChildren(noeud);
      if (lecture && !note.demo && JSON.stringify(lecture) !== JSON.stringify(note.lecture)) { note.lecture = lecture; try { await m.ecrireNote(note); } catch (e) { /* statistiques seulement */ } }
    } else {
      const d = V4.minutesEntre(note.entree_utc, note.sortie_utc);
      cible.innerHTML = `<dl class="j4-resume"><dt>Paire</dt><dd>${esc(note.paire)}</dd><dt>Sens</dt><dd>${esc(note.sens || "n/d")}</dd>
        <dt>Entrée</dt><dd>${esc(String(note.entree_locale || "n/d").replace("T", " à "))}</dd><dt>Sortie</dt><dd>${esc(note.sortie_locale ? note.sortie_locale.replace("T", " à ") : "n/d")}</dd>
        <dt>Durée</dt><dd>${esc(V4.dureeTexte(d))}${d != null ? ` (${esc(V4.categorieDuree(d))})` : ""}</dd><dt>Résultat</dt><dd class="${v > 0 ? "pos" : v < 0 ? "neg" : ""}">${esc(eur(v))}</dd>
        <dt>Pips</dt><dd>${esc(note.resultat?.pips ?? "n/d")}</dd><dt>R</dt><dd>${note.resultat?.r == null ? "n/d (risque prévu non saisi)" : esc(sgn(Number(note.resultat.r), 2, " R"))}</dd>
        ${note.migre_de ? `<dt>Origine</dt><dd>entrée ${esc(note.migre_de)} migrée sans perte</dd>` : ""}</dl>
        ${note.demo ? '<p class="small muted">Démonstration : trade d\'exemple, ni modifiable ni supprimable.</p>' : `<div class="j4-actions"><button type="button" class="btn" id="tModif">Modifier</button>
        <span id="tConf" hidden><span class="small">Supprimer définitivement ce trade et son analyse ? </span><button type="button" class="btn jn-danger" id="tOui">Oui, supprimer</button><button type="button" class="btn" id="tNon">Annuler</button></span>
        <button type="button" class="btn" id="tSuppr">Supprimer</button></div>`}`;
      if (!note.demo) {
        $("#tModif", cible).onclick = () => vueSaisie(jour, note);
        $("#tSuppr", cible).onclick = () => { $("#tConf", cible).hidden = false; $("#tSuppr", cible).hidden = true; $("#tOui", cible).focus(); };
        $("#tNon", cible).onclick = () => { $("#tConf", cible).hidden = true; $("#tSuppr", cible).hidden = false; };
        $("#tOui", cible).onclick = async () => { try { await m.supprimerNote(note.id); await charger(); rendre(); if (notes.some(x => String(x.entree_locale || "").startsWith(jour))) vueJour(jour); else fermer(); } catch (e) { cible.appendChild(h("p", "j4-erreur", `Suppression impossible : ${esc(e.message || e)}`)); } };
      }
    }
    if (!ouvert) ouvrirPanneau();
  }

  // ------------------------------------------------------------------ rendu de la page
  q("#newBtn").onclick = () => { if (demo) basculerDemo(); const j = localMaintenant().slice(0, 10); jourSel = j; vueSaisie(j); };
  const basculerDemo = async () => { demo = !demo; q("#jDemo").setAttribute("aria-pressed", demo); q("#jDemoTxt").hidden = !demo; await charger(); rendre(); };
  q("#jDemo").onclick = basculerDemo;
  q("#mPrev").onclick = () => { mois = V4.moisVoisin(mois, -1); rendre(); };
  q("#mNext").onclick = () => { mois = V4.moisVoisin(mois, 1); rendre(); };
  q("#mAuj").onclick = () => { mois = localMaintenant().slice(0, 7); jourSel = localMaintenant().slice(0, 10); rendre(); };

  function rendreCalendrier() {
    const auj = localMaintenant().slice(0, 10);
    mois = mois || auj.slice(0, 7);
    const [y, mo] = mois.split("-").map(Number);
    q("#mTitre").textContent = MOIS[mo - 1].replace(/^./, c => c.toUpperCase()) + " " + y;
    const grille = V4.grilleMoisV4(notes, mois), { vides, jours } = V4.caseDepart(mois);
    const B = V4.bilanMoisV4(notes, mois);
    q("#jBilan").innerHTML = [["Résultat du mois", `<span class="${B.eur > 0 ? "pos" : B.eur < 0 ? "neg" : ""}">${esc(eur(B.eur))}</span>`, B.eur == null ? "aucun résultat saisi" : "somme des résultats en €"],
      ["Trades", String(B.n), B.n ? `${B.gagnants} gagnant${B.gagnants > 1 ? "s" : ""}` : "clique sur un jour pour en ajouter"],
      ["Réussite", B.reussite == null ? "—" : `${B.reussite} %`, "trades gagnants / trades avec résultat"]]
      .map(k => `<div class="card kpi"><span>${k[0]}</span><b class="anim-num">${k[1]}</b><span class="small">${k[2]}</span></div>`).join("");
    let html = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map(x => `<span class="hd" role="columnheader">${x}</span>`).join("") + '<span class="j4-case vide"></span>'.repeat(vides);
    for (let d = 1; d <= jours; d++) {
      const iso = `${mois}-${String(d).padStart(2, "0")}`, j = grille[iso];
      const lignes = j ? j.trades.slice(0, 3).map(t => `<span class="j4-t"><b>${esc(t.paire)}</b> <span class="${t.eur > 0 ? "pos" : t.eur < 0 ? "neg" : ""}">${t.eur == null ? "n/d" : esc(eur(t.eur))}</span></span>`).join("") + (j.trades.length > 3 ? `<span class="small">+ ${j.trades.length - 3} autre${j.trades.length > 4 ? "s" : ""}</span>` : "") : "";
      html += `<button type="button" class="j4-case ${j ? j.classe : ""} ${iso === auj ? "auj" : ""}" data-j="${iso}" aria-pressed="${iso === jourSel}" aria-label="${esc(dateLongue(iso))}${j ? ` : ${j.trades.length} trade${j.trades.length > 1 ? "s" : ""}, ${j.eur == null ? "résultat n/d" : eur(j.eur)}` : ""}">
        <span class="n">${d}</span>${j ? `<span class="j4-pastille" aria-hidden="true"></span>${lignes}${j.eur != null ? `<span class="j4-net tabulaire">${esc(eur(j.eur))}</span>` : ""}` : ""}</button>`;
    }
    q("#cal4").innerHTML = html;
    q("#cal4").querySelectorAll("[data-j]").forEach(b => b.onclick = () => {
      jourSel = b.dataset.j;
      q("#cal4").querySelectorAll("[data-j]").forEach(x => x.setAttribute("aria-pressed", x.dataset.j === jourSel));
      if (telephone()) rendreJourMobile(); else vueJour(jourSel);
    });
    rendreJourMobile();
  }
  function rendreJourMobile() {
    const z = q("#jJour");
    z.hidden = !telephone() || !jourSel || !jourSel.startsWith(mois);
    if (z.hidden) return;
    const duJour = notes.filter(n => String(n.entree_locale || "").startsWith(jourSel)).sort((a, b) => String(a.entree_locale).localeCompare(String(b.entree_locale)));
    z.innerHTML = `<h3>${esc(dateLongue(jourSel))}</h3>`;
    if (!duJour.length) z.appendChild(h("p", "small muted", "Aucun trade ce jour-là."));
    const l = listeJour(duJour, jourSel);
    l.querySelectorAll(".j4-trade").forEach((b, i) => b.onclick = () => { vueEntree(duJour[i], "analyse"); });
    l.querySelector(".btn.pri")?.addEventListener("click", () => { if (!ouvert) ouvrirPanneau(); });
    z.appendChild(l);
  }

  function rendreStats() {
    const tr = notes.map(versTrade).filter(Boolean), S = statistiques(tr), vide = !S.n;
    if (S.n && S.sans_r === S.n) {   // aucun risque prévu saisi : résultat et réussite en € plutôt qu'un « 0 R » trompeur
      const e = tr.map(t => t.eur).filter(v => v != null), tot = e.reduce((a, b) => a + b, 0);
      S.total_r = null; S.r_moyen = null;
      S.reussite = e.length ? Math.round(100 * e.filter(v => v > 0).length / e.length) : null; S.gagnants = e.filter(v => v > 0).length;
      S.total_eur = e.length ? tot : null;
    }
    q("#jk").innerHTML = (vide ? [["Résultat", "—", "aucun trade clôturé"], ["Trades", "0", "ajoute un trade depuis le calendrier"], ["Réussite", "—", ""], ["R moyen", "—", ""], ["Facteur de profit", "—", ""], ["Série en cours", "—", ""]]
      : [S.total_r == null ? ["Résultat", `<span class="${S.total_eur >= 0 ? "pos" : "neg"}">${esc(eur(S.total_eur))}</span>`, "en € · R n/d : risque prévu non saisi"]
         : ["Résultat", `<span class="${S.total_r >= 0 ? "pos" : "neg"}">${sgn(S.total_r, 1, " R")}</span>`, S.total_eur != null ? `soit ${sgn(S.total_eur, 0, " €")}` : "montant en € n/d"],
         ["Trades", String(S.n), S.sans_r ? `${S.sans_r} sans résultat en R` : `depuis le ${ddm(tr.map(t => t.d).sort()[0])}`],
         ["Réussite", S.reussite == null ? "n/d" : S.reussite + " %", `${S.gagnants} gagnant${S.gagnants > 1 ? "s" : ""}`],
         ["R moyen", sgn(S.r_moyen, 2), "par trade"], ["Facteur de profit", S.facteur_profit == null ? "n/d" : S.facteur_profit === Infinity ? "∞" : nf(S.facteur_profit, 2), "gains / pertes"],
         ["Série en cours", S.serie ? `${S.serie.n} ${S.serie.gagnante ? "gagnant" : "perdant"}${S.serie.n > 1 ? "s" : ""}` : "—", S.serie ? "dernier trade " + ddm(S.serie.dernier) : ""]])
      .map(k => `<div class="card kpi"><span>${k[0]}</span><b class="anim-num">${k[1]}</b><span class="small">${k[2]}</span></div>`).join("");
    const cum = S.courbe.map(c => c.r);
    q("#eq").innerHTML = cum.length > 1 ? spark([0, ...cum], 800, 220, S.total_r >= 0 ? "var(--up)" : "var(--down)", true).replace("<svg", '<svg class="trace" style="width:100%;height:100%"')
      : '<div class="empty">La courbe apparaît à partir de 2 trades clôturés avec un résultat en R (risque prévu saisi).</div>';
    const [th, ...autres] = S.constats;
    q("#ins1").innerHTML = `<span class="eyebrow">Ce que tes trades disent</span><h3 style="font-family:var(--f-display);font-size:22px;font-weight:500">${esc(th.titre)}</h3>
      ${th.chiffre ? `<div class="vsrow"><div><span>Avec le thème</span><b class="${th.avec.reussite >= th.contre.reussite ? "pos" : "neg"}">${th.avec.reussite} %</b><span>${th.avec.n} trades · ${sgn(th.avec.moyenne, 2, " R")} en moyenne</span></div><div><span>Contre le thème</span><b class="${th.contre.reussite > th.avec.reussite ? "pos" : "neg"}">${th.contre.reussite} %</b><span>${th.contre.n} trades · ${sgn(th.contre.moyenne, 2, " R")} en moyenne</span></div></div>` : ""}
      <p>${esc(th.texte)}</p>`;
    q("#ins").innerHTML = autres.map(x => `<div class="card insight"><span class="eyebrow">${esc(x.titre)}</span><b style="font-size:24px;font-weight:600">${esc(x.chiffre || "—")}</b><p>${esc(x.texte)}</p></div>`).join("");
    const C = V4.statsContexte(notes);
    q("#insCtx").innerHTML = `<span class="eyebrow">Selon le contexte du site au moment de l'entrée</span>
      <div class="vsrow"><div><span>5 moteurs ou plus dans le sens du trade</span><b>${C.forts.reussite == null ? "—" : C.forts.reussite + " %"}</b><span>${C.forts.n} trade${C.forts.n > 1 ? "s" : ""}</span></div>
      <div><span>2 moteurs ou moins dans le sens du trade</span><b>${C.faibles.reussite == null ? "—" : C.faibles.reussite + " %"}</b><span>${C.faibles.n} trade${C.faibles.n > 1 ? "s" : ""}</span></div></div>
      <p>Réussite (trades gagnants en €) selon la « Lecture du site » de chaque trade : ${C.lus} trade${C.lus > 1 ? "s" : ""} lu${C.lus > 1 ? "s" : ""}. Un constat sur tes trades, pas une règle ; ouvre l'onglet « Lecture du site » d'un trade pour l'ajouter.</p>`;
    const mx = Math.max(...S.par_paire.map(x => Math.abs(x[1])), 0.5) * 1.1;
    q("#byPair").innerHTML = S.par_paire.map(([k, v]) => hbar(k, v, mx, sgn(v, 1, " R"))).join("") || '<p class="muted">Aucun trade avec un résultat en R.</p>';
    const m2 = Math.max(...[...S.par_seance, ...S.par_jour].map(x => Math.abs(x[1].moyenne || 0)), 0.5) * 1.1;
    const ligne = ([k, g]) => hbar(`${k} <span class="small">${g.n}</span>`, g.moyenne, m2, g.moyenne == null ? "n/d" : sgn(g.moyenne, 2, " R"));
    q("#bySess").innerHTML = S.par_seance.map(ligne).join("") + '<div style="height:8px"></div>' + S.par_jour.map(ligne).join("");
    section.querySelectorAll("#byPair .hbar, #bySess .hbar").forEach(x => x.style.gridTemplateColumns = "110px minmax(0,1fr) 64px");
    const pr = ["Toutes", ...new Set(notes.map(n => n.paire))];
    if (!pr.includes(filtre)) filtre = "Toutes";
    q("#jFilt").innerHTML = pr.map(p => `<button type="button" data-p="${p}" aria-pressed="${p === filtre}">${p}</button>`).join("");
    q("#jFilt").querySelectorAll("button").forEach(b => b.onclick = () => { filtre = b.dataset.p; rendreStats(); });
    const lignes = notes.filter(n => filtre === "Toutes" || n.paire === filtre).sort((a, b) => String(b.entree_utc || b.date_heure).localeCompare(String(a.entree_utc || a.date_heure)));
    q("#jTab").innerHTML = `<thead><tr><th>Date</th><th>Paire</th><th>Sens</th><th>Durée</th><th class="n">Moteurs pour</th><th class="n">Résultat</th><th class="n">R</th></tr></thead><tbody>` +
      (lignes.map(n => { const v = n.resultat?.pnl_eur ?? null, r = n.resultat?.r ?? versTrade(n)?.r ?? null;
        return `<tr data-id="${esc(n.id)}" tabindex="0" style="cursor:pointer"><td>${ddm(String(n.entree_locale || n.date_heure || "").slice(0, 10))}</td><td><b>${esc(n.paire)}</b></td><td>${esc(n.sens || "—")}</td>
          <td>${esc(V4.dureeTexte(V4.minutesEntre(n.entree_utc, n.sortie_utc)))}</td><td class="n">${n.lecture ? `${n.lecture.pour} / 8` : '<span class="small">non lu</span>'}</td>
          <td class="n ${v > 0 ? "pos" : v < 0 ? "neg" : ""}"><b>${esc(eur(v))}</b></td><td class="n">${r == null ? "n/d" : esc(sgn(Number(r), 1, " R"))}</td></tr>`; }).join("")
       || `<tr><td colspan="7" class="muted">Aucun trade. Clique sur un jour du calendrier pour en ajouter un.</td></tr>`) + "</tbody>";
    q("#jTab").querySelectorAll("tr[data-id]").forEach(tr => { const ouvrir = () => { const n = notes.find(x => x.id === tr.dataset.id); if (n) vueEntree(n, "analyse"); };
      tr.onclick = ouvrir; tr.onkeydown = e => { if (e.key === "Enter") ouvrir(); }; });
  }

  function rendre() { rendreCalendrier(); rendreStats(); animerChiffres(section); }

  // Mes entrées (liste V2 : export, import, sauvegarde) et fiche d'analyse : vue complète
  const v2 = q("#jV2");
  v2.appendChild(blocDetaille("Sauvegarde : exporter et importer mes entrées", "fichier .json, captures comprises", async () => {
    const blocs = await m.pageJournal(); const hote = h("div", "legacy journal-v7"); hote.append(...blocs);
    const liste = hote.querySelector(".jn-liste"); const c = h("div", "legacy journal-v7"); if (liste) c.appendChild(liste);
    return [c];
  }));
  v2.appendChild(blocDetaille("Fiche d'analyse de la paire", "calcul Python à chaque run, bougies et contributions", async () => {
    const blocs = await m.pageJournal(); const hote = h("div", "legacy journal-v7"); hote.append(...blocs);
    return [hote.querySelector(".jn-grille > .jn-col:first-child") || h("p", "muted", "Fiche indisponible")];
  }));

  await charger();
  rendre();
  const p = (parametre || "").match(/^nouvelle=([A-Z]{3}-[A-Z]{3})$/);
  if (p) { history.replaceState(null, "", "#journal"); const j = localMaintenant().slice(0, 10); vueSaisie(j, null, p[1].replace("-", "/")); }
  section.ouvrirNouvelle = paire => vueSaisie(localMaintenant().slice(0, 10), null, paire);
  section.addEventListener("ecran-quitte", () => document.removeEventListener("keydown", surTouche), { once: true });
}
