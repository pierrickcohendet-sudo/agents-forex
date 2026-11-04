/* Trading baby — site V7 (refonte selon docs/design/maquette_v7.html). Lit uniquement docs/data/*.json (produits par le
   pipeline Python), aucune clé, aucun appel à un modèle. Chaque onglet se construit à sa première ouverture, une seule fois. */
import { chargerJson, enErreur, initialiserDetail, initialiserCertificats, appliquerGlossaire, VERSION, CLE_VUE } from "./commun.js";
import { $, h, esc, store, squelette, rethemer, recadrer } from "./v7_commun.js";

const ONGLETS = {
  synthese: { titre: "Synthèse", module: "./ecran_synthese.js", fonction: "ecranSynthese" },
  tableau: { titre: "Tableau de bord", module: "./ecran_tableau.js", fonction: "ecranTableau" },
  devises: { titre: "Devises", module: "./ecran_devises.js", fonction: "ecranDevises" },
  agenda: { titre: "Agenda", module: "./ecran_agenda.js", fonction: "ecranAgenda" },
  engrenages: { titre: "8 engrenages", module: "./ecran_engrenages.js", fonction: "ecranEngrenages" },
  journal: { titre: "Journal", module: "./ecran_journal.js", fonction: "ecranJournal" },
  // Menu « Plus » : anciens modules, restylés par les tokens V7
  scenarios: { titre: "Scénarios et simulateur", ancien: "./scenarios.js", fonction: "pageScenarios" },
  sante: { titre: "Santé des données", ancien: "./sante.js", fonction: "pageSante" },
  archives: { titre: "Archives", ancien: "./archives.js", fonction: "pageArchives" },
};
const PLUS = ["scenarios", "sante", "archives"];
/* Anciennes adresses (#…) : redirigées vers le bon onglet. */
const REDIRECTIONS = { rapport: "synthese", accueil: "synthese", hebdo: "synthese", mensuel: "synthese", apprendre: "synthese",
                       institutions: "engrenages", outils: "engrenages", "tableau-macro": "tableau" };
const construits = new Map();   // onglet -> section (construite une seule fois)

/* ------------------------------------------------------------------ en-tête : sessions de marché */
function sessions() {
  const now = new Date(), hr = now.getUTCHours() + now.getUTCMinutes() / 60;
  const S = [["Asie", 0, 8], ["Londres", 7, 16], ["New York", 12, 21]];   // heures UTC fixes (comme la technique Python)
  const bar = $("#sessBar"); bar.innerHTML = "";
  for (const [n, a, b] of S) {
    const on = hr >= a && hr < b, s = h("div", "sess" + (on ? " on" : ""), n);
    s.style.left = (a / 24 * 100) + "%"; s.style.width = ((b - a) / 24 * 100) + "%";
    s.style.background = on ? "var(--accent-soft)" : "transparent";
    bar.appendChild(s);
  }
  const nw = h("div", "sess-now"); nw.style.left = (hr / 24 * 100) + "%"; nw.title = "maintenant"; bar.appendChild(nw);
  const ouverts = S.filter(([, a, b]) => hr >= a && hr < b).map(s => s[0]);
  $("#sessTxt").textContent = ouverts.length ? ouverts.join(" + ") + " ouvert" + (ouverts.length > 1 ? "s" : "") : "Marchés calmes";
  $("#clock").textContent = "Paris " + now.toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit" });
}

/* ------------------------------------------------------------------ thème et vue */
function sombre() {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}
function changerTheme() {
  document.documentElement.dataset.theme = sombre() ? "light" : "dark";
  store.set("fxdesk-theme", document.documentElement.dataset.theme);
  rethemer();
}
function poserVue(v, memoriser = true) {
  document.documentElement.dataset.vue = v;
  const b = $("#vueBtn");
  b.setAttribute("aria-pressed", String(v === "complete"));
  b.lastElementChild.innerHTML = '<span class="lab-long">Vue </span>' + (v === "complete" ? "complète" : "essentielle");
  if (memoriser) store.set(CLE_VUE, v);
  requestAnimationFrame(deplacerSoulignement);
}

/* ------------------------------------------------------------------ onglets */
function deplacerSoulignement() {
  const b = document.querySelector('.tab[aria-selected="true"]'), ink = $("#ink");
  if (!b || !b.offsetWidth) { ink.style.width = "0"; return; }
  ink.style.left = b.offsetLeft + 14 + "px"; ink.style.width = Math.max(0, b.offsetWidth - 28) + "px";
}
function lireAdresse() {
  let hash = (location.hash || "#synthese").slice(1);
  const [base, ...reste] = hash.split("/");
  if (REDIRECTIONS[base]) {   // ancienne adresse : remplacée sans nouvelle entrée d'historique
    hash = [REDIRECTIONS[base], ...(base === "hebdo" ? [] : reste)].join("/");
    history.replaceState(null, "", `#${hash}`);
  }
  if (/^g=[1-8]$/.test(hash)) hash = `engrenages/${hash}`;   // lien direct vers un dossier d'engrenage
  const [id, parametre] = hash.split("/");
  return [ONGLETS[id] ? id : "synthese", parametre];
}
async function construire(id, parametre) {
  const conf = ONGLETS[id];
  const s = h("section", "screen"); s.id = "s-" + id; s.setAttribute("role", "tabpanel"); s.setAttribute("aria-label", conf.titre);
  s.innerHTML = squelette(3, 140);   // squelettes de chargement à la place des blocs vides
  $("#contenu").appendChild(s);
  construits.set(id, s);
  try {
    if (conf.ancien) {
      const m = await import(conf.ancien);
      const blocs = await m[conf.fonction](parametre);
      s.replaceChildren(h("div", "sec-head", `<h2>${esc(conf.titre)}</h2><p>Menu Plus</p>`), h("div", "legacy"));
      s.lastChild.append(...blocs);
      appliquerGlossaire(s);
    } else {
      const m = await import(conf.module);
      await m[conf.fonction](s, parametre);
    }
  } catch (e) {
    console.error(e);
    s.innerHTML = `<div class="card pad"><h2>${esc(conf.titre)}</h2><p class="muted">Affichage indisponible : ${esc(e.message)}</p></div>`;
  }
  return s;
}
async function afficher() {
  const [id, parametre] = lireAdresse();
  document.querySelectorAll(".tab[data-t]").forEach(a => {
    const actif = a.dataset.t === id;
    a.setAttribute("aria-selected", String(actif));
    if (actif) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  const plus = $("#menu-plus");
  plus.open = false;
  plus.querySelector("summary").setAttribute("aria-selected", String(PLUS.includes(id)));
  document.title = `${ONGLETS[id].titre} — Trading baby`;
  deplacerSoulignement();
  let s = construits.get(id);
  if (s && PLUS.includes(id) && parametre) { s.remove(); construits.delete(id); s = null; }   // archives/<date> : nouvelle page
  for (const [k, x] of construits) x.classList.toggle("on", k === id);
  if (!s) { s = await construire(id, parametre); }
  for (const [k, x] of construits) x.classList.toggle("on", k === id);
  requestAnimationFrame(() => recadrer(s));
  if (id === "engrenages" && parametre) { const b = s.querySelector(`#engSel button[data-n="${parametre.slice(2)}"]`); if (b && b.getAttribute("aria-pressed") !== "true") b.click(); }
  window.scrollTo(0, 0);
}

async function initialiser() {
  initialiserDetail();
  initialiserCertificats();
  sessions(); setInterval(sessions, 60000);
  poserVue(document.documentElement.dataset.vue === "essentielle" ? "essentielle" : "complete", false);
  $("#vueBtn").onclick = () => poserVue(document.documentElement.dataset.vue === "complete" ? "essentielle" : "complete");
  $("#themeBtn").onclick = changerTheme;
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => { if (!document.documentElement.dataset.theme) rethemer(); });
  document.addEventListener("click", ev => {   // menu « Plus » : se ferme au clic à l'extérieur
    const plus = $("#menu-plus");
    if (plus.open && !plus.contains(ev.target)) plus.open = false;
  });
  const imprimer = $("#bouton-imprimer");
  imprimer.addEventListener("click", async () => {
    try { (await import("./impression.js")).ouvrirApercu(imprimer); } catch (e) { console.error(e); window.print(); }
  });
  window.addEventListener("hashchange", afficher);
  window.addEventListener("resize", deplacerSoulignement);
  if (document.fonts) document.fonts.ready.then(deplacerSoulignement);
  const site = await chargerJson("data/site.json");
  if (!enErreur(site)) {
    const r = site.regime || {};
    const lien = $("#lien-notion");
    if (r.notion_url) { lien.href = r.notion_url; lien.hidden = false; lien.textContent = r.notion_page_du_jour ? "Ouvrir dans Notion" : "Ouvrir la base Notion"; }
    const g = site.genere_le ? new Date(site.genere_le) : null;
    const quand = g && !isNaN(g) ? `${g.toLocaleDateString("fr-FR", { timeZone: "Europe/Paris" })} ${g.toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit" })}` : "n/d";
    $("#pied-meta").textContent = `version ${VERSION} · généré le ${quand} · rapport du ${r.date_rapport || "—"}`;
  } else $("#pied-meta").textContent = `version ${VERSION}`;
  afficher();
}

initialiser();
