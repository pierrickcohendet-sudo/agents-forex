/* Lot V10 (B3) — « Mon analyse » : page libre par blocs, façon Notion. C'est l'utilisateur qui écrit, le site ne remplit
   rien. Blocs : titre, sous-titre, paragraphe, puces, liste numérotée, case à cocher, citation, encadré, séparateur, image.
   Menu « / », glisser-déposer, Entrée crée un bloc, Retour arrière sur un bloc vide le supprime, Ctrl+B / Ctrl+I / Ctrl+K.
   Images : coller, glisser ou choisir un fichier ; compressées sur l'appareil (WebP) ; légende ; zoom ; unité M30 à D1.
   Enregistrement automatique (« Enregistré »). Sérialisation : journal_v4.js (fonctions pures testées). */
import { h, esc } from "./v7_commun.js";
import { bloc, serialiser, nettoyerHtml, blocsDuModele, MODELE_DEFAUT } from "./journal_v4.js";

const LIBELLES = { titre: "Titre", "sous-titre": "Sous-titre", paragraphe: "Paragraphe", puce: "Liste à puces", numero: "Liste numérotée",
  case: "Case à cocher", citation: "Citation", encadre: "Encadré", separateur: "Séparateur", image: "Image" };
const SUITE = { puce: "puce", numero: "numero", case: "case" };   // Entrée dans une liste : même type
const UNITES = ["M30", "H1", "H4", "D1"];
const TEXTE = t => !["separateur", "image"].includes(t);

/* options : { blocs, captures, enregistrer(blocs, captures), compresser(fichier), modele() / enregistrerModele(blocs) } */
export function editeur(options) {
  let blocs = (options.blocs || []).map(b => ({ ...b }));
  if (!blocs.length) blocs = [bloc("paragraphe")];   // page vierge : on peut écrire tout de suite
  let captures = [...(options.captures || [])];
  const urls = new Map();
  const racine = h("div", "ed");
  racine.innerHTML = `<div class="ed-barre"><span class="small" id="edEtat" aria-live="polite"></span>
    <span class="ed-actions"><button type="button" class="btn" data-a="modele">Utiliser mon modèle</button><button type="button" class="btn" data-a="defaut">Enregistrer comme modèle</button>
    <button type="button" class="btn" data-a="image">+ Image</button></span></div>
    <div class="ed-page" role="textbox" aria-multiline="true" aria-label="Mon analyse"></div>
    <p class="small ed-aide">Tape « / » pour choisir un bloc · Entrée : nouveau bloc · Ctrl+B gras · Ctrl+I italique · Ctrl+K lien · colle ou glisse une image.</p>
    <input type="file" accept="image/*" multiple hidden>`;
  const page = racine.querySelector(".ed-page"), etat = racine.querySelector("#edEtat"), fichier = racine.querySelector("input[type=file]");
  let minuterie = null, cibleImage = null;

  const urlDe = id => {
    const c = captures.find(x => x.id === id);
    if (!c?.blob) return c?.dataURL || null;
    if (!urls.has(id)) urls.set(id, URL.createObjectURL(c.blob));
    return urls.get(id);
  };
  function lireDom() {
    for (const ligne of page.querySelectorAll(".ed-bloc")) {
      const b = blocs.find(x => x.id === ligne.dataset.id);
      if (!b) continue;
      const t = ligne.querySelector(".ed-texte");
      if (t) b.texte = nettoyerHtml(t.innerHTML);
      const c = ligne.querySelector("input[type=checkbox]");
      if (c) b.coche = c.checked;
      const l = ligne.querySelector(".ed-legende");
      if (l) b.legende = l.textContent.trim();
    }
    blocs = [...page.querySelectorAll(".ed-bloc")].map(l => blocs.find(x => x.id === l.dataset.id)).filter(Boolean);
  }
  function sauver() {
    etat.textContent = "Enregistrement…";
    clearTimeout(minuterie);
    minuterie = setTimeout(async () => {
      lireDom();
      // toutes les captures restent : celles de l'onglet Photos ne sont pas forcément dans l'analyse
      try { await options.enregistrer(serialiser(blocs), captures); etat.textContent = "Enregistré"; }
      catch (e) { etat.textContent = `Non enregistré : ${e.message || e}`; }
    }, 500);
  }
  function numeroter() {
    let n = 0;
    for (const l of page.querySelectorAll(".ed-bloc")) { if (l.dataset.type === "numero") l.querySelector(".ed-num").textContent = `${++n}.`; else n = 0; }
  }
  function ligneDe(b) {
    const l = h("div", `ed-bloc ed-${b.type}`); l.dataset.id = b.id; l.dataset.type = b.type;
    const poignee = h("span", "ed-poignee", "⋮⋮"); poignee.draggable = true; poignee.title = "Glisser pour déplacer"; poignee.setAttribute("aria-hidden", "true");
    l.appendChild(poignee);
    if (b.type === "separateur") { l.appendChild(h("hr")); l.tabIndex = 0; }
    else if (b.type === "image") {
      const f = h("figure", "ed-figure"), src = urlDe(b.capture);
      f.innerHTML = src ? `<img alt="${esc(b.legende || "capture")}" src="${src}">` : `<div class="empty">Image introuvable sur cet appareil</div>`;
      const leg = h("figcaption", "ed-legende"); leg.contentEditable = "true"; leg.dataset.ph = "Légende"; leg.textContent = b.legende || "";
      const u = h("div", "seg ed-unites"); u.setAttribute("role", "group"); u.setAttribute("aria-label", "Unité de temps");
      u.innerHTML = UNITES.map(x => `<button type="button" aria-pressed="${b.unite === x}">${x}</button>`).join("");
      u.querySelectorAll("button").forEach(bt => bt.onclick = () => { b.unite = b.unite === bt.textContent ? null : bt.textContent; u.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", b.unite === x.textContent)); sauver(); });
      f.querySelector("img")?.addEventListener("click", () => zoom(src, b.legende));
      f.append(leg, u); l.appendChild(f); l.tabIndex = 0;
    } else {
      if (b.type === "case") { const c = h("input"); c.type = "checkbox"; c.checked = !!b.coche; c.onchange = sauver; c.setAttribute("aria-label", "Fait"); l.appendChild(c); }
      if (b.type === "puce") l.appendChild(h("span", "ed-puce", "•"));
      if (b.type === "numero") l.appendChild(h("span", "ed-num", "1."));
      const t = h("div", "ed-texte"); t.contentEditable = "true"; t.innerHTML = nettoyerHtml(b.texte || "");
      t.dataset.ph = b.type === "paragraphe" ? "Écris, ou tape « / » pour choisir un bloc" : LIBELLES[b.type];
      l.appendChild(t);
    }
    return l;
  }
  function rendre(focusId, fin = true) {
    page.replaceChildren(...blocs.map(ligneDe));
    if (!blocs.length) page.appendChild(h("p", "ed-vide muted", "Page vide. Écris ton analyse, ou « Utiliser mon modèle »."));
    numeroter();
    if (focusId) focus(focusId, fin);
  }
  function focus(id, fin = true) {
    const l = page.querySelector(`.ed-bloc[data-id="${id}"]`); if (!l) return;
    const t = l.querySelector(".ed-texte") || l;
    t.focus();
    if (t.isContentEditable) { const r = document.createRange(); r.selectNodeContents(t); r.collapse(!fin); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
  }
  function inserer(apresId, nouveau) {
    lireDom();
    const i = apresId ? blocs.findIndex(b => b.id === apresId) : blocs.length - 1;
    blocs.splice(i + 1, 0, nouveau);
    rendre(nouveau.id, false); sauver();
  }
  function changerType(id, type) {
    lireDom();
    const b = blocs.find(x => x.id === id); if (!b) return;
    if (type === "image") { cibleImage = id; fichier.click(); return; }
    b.type = type; if (!TEXTE(type)) delete b.texte;
    rendre(id); sauver();
    if (type === "separateur") inserer(id, bloc("paragraphe"));
  }

  // ---- menu « / »
  const menu = h("div", "ed-menu card"); menu.hidden = true; menu.setAttribute("role", "listbox");
  menu.innerHTML = Object.entries(LIBELLES).map(([k, v]) => `<button type="button" role="option" data-t="${k}">${v}</button>`).join("");
  racine.appendChild(menu);
  let menuPour = null;
  function ouvrirMenu(ligne) {
    menuPour = ligne.dataset.id; menu.hidden = false;
    const r = ligne.getBoundingClientRect(), rr = racine.getBoundingClientRect();
    menu.style.top = `${r.bottom - rr.top + 4}px`; menu.style.left = "28px";
    menu.querySelector("button").focus();
  }
  menu.addEventListener("click", e => { const t = e.target.closest("button")?.dataset.t; if (!t) return; menu.hidden = true;
    const l = page.querySelector(`.ed-bloc[data-id="${menuPour}"] .ed-texte`); if (l) l.textContent = l.textContent.replace(/^\/\S*/, "");
    changerType(menuPour, t); });
  menu.addEventListener("keydown", e => {
    const bs = [...menu.querySelectorAll("button")], i = bs.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); bs[(i + 1) % bs.length].focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); bs[(i - 1 + bs.length) % bs.length].focus(); }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); menu.hidden = true; focus(menuPour); }
  });

  // ---- lien (Ctrl+K) : petite saisie, http(s) seulement
  function lien() {
    const sel = getSelection(); if (!sel.rangeCount || sel.isCollapsed) { etat.textContent = "Sélectionne d'abord le texte du lien"; return; }
    const plage = sel.getRangeAt(0);
    const p = h("div", "ed-lien card"); p.innerHTML = `<input type="url" placeholder="https://…" aria-label="Adresse du lien"><button type="button" class="btn pri">OK</button>`;
    racine.appendChild(p); const inp = p.querySelector("input"); inp.focus();
    const valider = () => { const u = inp.value.trim(); p.remove();
      if (/^https?:\/\//i.test(u)) { const s = getSelection(); s.removeAllRanges(); s.addRange(plage); document.execCommand("createLink", false, u); sauver(); }
      else if (u) etat.textContent = "Lien refusé : adresse http(s) attendue"; };
    p.querySelector("button").onclick = valider;
    inp.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); valider(); } if (e.key === "Escape") { e.stopPropagation(); p.remove(); } });
  }

  // ---- clavier
  page.addEventListener("keydown", e => {
    const ligne = e.target.closest(".ed-bloc"); if (!ligne) return;
    const id = ligne.dataset.id, type = ligne.dataset.type, t = ligne.querySelector(".ed-texte");
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "b") { e.preventDefault(); document.execCommand("bold"); sauver(); return; }
    if (mod && e.key.toLowerCase() === "i") { e.preventDefault(); document.execCommand("italic"); sauver(); return; }
    if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); lien(); return; }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const vide = t && !t.textContent.trim();
      if (vide && SUITE[type]) { changerType(id, "paragraphe"); return; }      // Entrée sur une puce vide : fin de liste
      inserer(id, bloc(SUITE[type] || "paragraphe"));
      return;
    }
    if (e.key === "Backspace" && (!t || !t.textContent.trim()) && (!t || !t.querySelector("img"))) {
      if (t && type !== "paragraphe") { e.preventDefault(); changerType(id, "paragraphe"); return; }
      e.preventDefault(); lireDom();
      const i = blocs.findIndex(b => b.id === id); if (i < 0) return;
      blocs.splice(i, 1); const prec = blocs[Math.max(0, i - 1)];
      rendre(prec?.id); sauver();
    }
  });
  page.addEventListener("input", e => {
    const t = e.target.closest(".ed-texte");
    if (t && t.textContent === "/" && menu.hidden) ouvrirMenu(t.closest(".ed-bloc"));   // « / » saisi au clavier, collé ou dicté
    if (e.target.closest(".ed-texte, .ed-legende")) sauver();
  });

  // ---- glisser-déposer : réordonner les blocs, ou déposer des images
  let glisse = null;
  page.addEventListener("dragstart", e => { const l = e.target.closest(".ed-bloc"); if (!l || !e.target.classList.contains("ed-poignee")) return; glisse = l; l.classList.add("ed-glisse"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", l.dataset.id); });
  page.addEventListener("dragover", e => { e.preventDefault(); const l = e.target.closest(".ed-bloc"); if (!glisse || !l || l === glisse) return;
    const r = l.getBoundingClientRect(); l.parentNode.insertBefore(glisse, e.clientY > r.top + r.height / 2 ? l.nextSibling : l); });
  page.addEventListener("drop", async e => {
    e.preventDefault();
    if (glisse) { glisse.classList.remove("ed-glisse"); glisse = null; lireDom(); numeroter(); sauver(); return; }
    const imgs = [...(e.dataTransfer?.files || [])].filter(f => f.type.startsWith("image/"));
    if (imgs.length) await ajouterImages(imgs, e.target.closest(".ed-bloc")?.dataset.id);
  });
  page.addEventListener("dragend", () => { if (glisse) { glisse.classList.remove("ed-glisse"); glisse = null; lireDom(); numeroter(); sauver(); } });
  page.addEventListener("paste", async e => {
    const imgs = [...(e.clipboardData?.files || [])].filter(f => f.type.startsWith("image/"));
    if (imgs.length) { e.preventDefault(); await ajouterImages(imgs, e.target.closest(".ed-bloc")?.dataset.id); return; }
    if (e.target.closest(".ed-texte")) {   // texte collé : sans mise en forme étrangère
      e.preventDefault(); document.execCommand("insertText", false, e.clipboardData.getData("text/plain"));
    }
  });
  async function ajouterImages(fichiers, apresId) {
    etat.textContent = "Compression de l'image…";
    lireDom();
    let ref = apresId;
    if (cibleImage) {   // « / » puis Image : le bloc vide devient l'image
      const i = blocs.findIndex(b => b.id === cibleImage); if (i >= 0 && !blocs[i].texte) { blocs.splice(i, 1); ref = blocs[i - 1]?.id || null; }
      cibleImage = null;
    }
    for (const f of fichiers) {
      try {
        const c = await options.compresser(f);
        const cap = { id: crypto.randomUUID(), unites: [], ...c };
        captures.push(cap);
        const b = { ...bloc("image"), capture: cap.id, legende: "", unite: null };
        const i = ref ? blocs.findIndex(x => x.id === ref) : blocs.length - 1;
        blocs.splice(i + 1, 0, b); ref = b.id;
      } catch (err) { etat.textContent = `Image illisible (${err.message || err})`; }
    }
    if (!blocs.length || blocs[blocs.length - 1].type === "image") blocs.push(bloc("paragraphe"));
    rendre(); sauver();
  }
  fichier.addEventListener("change", async () => { await ajouterImages([...fichier.files]); fichier.value = ""; });

  // ---- zoom
  function zoom(src, legende) {
    const z = h("div", "ed-zoom"); z.setAttribute("role", "dialog"); z.setAttribute("aria-label", "Image agrandie"); z.tabIndex = -1;
    z.innerHTML = `<img alt="${esc(legende || "capture")}" src="${src}"><button type="button" class="iconbtn" aria-label="Fermer">✕</button>`;
    const fermer = () => z.remove();
    z.onclick = fermer; z.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); fermer(); } });
    document.body.appendChild(z); z.focus();
  }

  // ---- barre : modèle, image
  racine.querySelector(".ed-barre").addEventListener("click", async e => {
    const a = e.target.closest("button")?.dataset.a; if (!a) return;
    if (a === "image") { cibleImage = null; fichier.click(); }
    if (a === "modele") {
      lireDom();
      const m = (await options.modele?.()) || MODELE_DEFAUT;
      const neufs = blocsDuModele(m);
      blocs = blocs.filter(b => b.type === "image" || (b.texte || "").replace(/<[^>]+>/g, "").trim()).concat(neufs);
      rendre(neufs[1]?.id || neufs[0]?.id); sauver();
    }
    if (a === "defaut") {
      lireDom();
      const m = blocs.filter(b => TEXTE(b.type)).map(b => [b.type, b.type === "titre" || b.type === "sous-titre" ? b.texte.replace(/<[^>]+>/g, "") : ""]);
      if (!m.length) { etat.textContent = "Écris d'abord quelques titres pour en faire ton modèle"; return; }
      await options.enregistrerModele?.(m); etat.textContent = "Modèle enregistré : il servira par défaut";
    }
  });
  page.addEventListener("click", e => { if (e.target === page && blocs.length === 0) inserer(null, bloc("paragraphe")); });
  page.addEventListener("focusin", () => { menu.hidden = true; });

  rendre();
  racine.detruire = () => { for (const u of urls.values()) URL.revokeObjectURL(u); urls.clear(); clearTimeout(minuterie); };
  racine.enCours = () => { lireDom(); return serialiser(blocs); };
  racine.ajouterImages = ajouterImages;
  return racine;
}
