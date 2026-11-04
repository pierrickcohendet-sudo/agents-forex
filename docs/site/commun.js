/* Utilitaires partagés : DOM, chargement des JSON, formats, fenêtre de détail. */

export function el(tag, classe, texte) {
  const n = document.createElement(tag);
  if (classe) n.className = classe;
  if (texte !== undefined && texte !== null) n.textContent = texte;
  return n;
}

/* Données : chaque fichier est chargé une fois ; un échec renvoie {erreur} (jamais d'exception). */
const cache = new Map();
/* Version du site (meta posée par core/version_site.py) : ajoutée à chaque fichier de données chargé. */
export const VERSION = (typeof document !== "undefined" && document.querySelector('meta[name="fxdesk-version"]')?.content) || "dev";
export function chargerJson(chemin) {
  if (!cache.has(chemin)) {
    cache.set(chemin, fetch(`${chemin}${chemin.includes("?") ? "&" : "?"}v=${VERSION}`, { cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .catch(e => ({ __erreur: `${chemin} : ${e.message}` })));
  }
  return cache.get(chemin);
}
export const enErreur = d => !d || d.__erreur !== undefined;

/* Bloc « indisponible » avec raison et heure de la tentative — n'interrompt jamais le reste. */
export function indisponible(titre, raison) {
  const c = el("section", "carte");
  if (titre) c.appendChild(el("h2", null, titre));
  const p = el("p", "indisponible",
    `Indisponible : ${raison || "raison inconnue"} (tentative de chargement à ${new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}).`);
  c.appendChild(p);
  return c;
}

export function dateCourte(iso) {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00Z` : iso);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
}
export function dateHeure(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
}
export function ageHeures(iso) {
  const d = new Date(iso);
  return isNaN(d) ? null : (Date.now() - d.getTime()) / 3.6e6;
}

export const DRAPEAUX = { USD: "🇺🇸", EUR: "🇪🇺", GBP: "🇬🇧", JPY: "🇯🇵", CHF: "🇨🇭", CAD: "🇨🇦", AUD: "🇦🇺", NZD: "🇳🇿", CNY: "🇨🇳" };

/* Fenêtre de détail (élément <dialog>). `lignes` : [[libellé, valeur], …] ou nœuds DOM. */
export function ouvrirDetail(titre, contenu) {
  const d = document.getElementById("detail");
  document.getElementById("detail-titre").textContent = titre;
  const corps = document.getElementById("detail-corps");
  corps.replaceChildren(...(Array.isArray(contenu) ? contenu : [contenu]));
  if (typeof d.showModal === "function") { if (!d.open) d.showModal(); } else d.setAttribute("open", "");
}
export function listeDefinitions(paires) {
  const dl = el("dl");
  for (const [k, v] of paires) {
    if (v === undefined) continue;
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, v === null || v === "" ? "—" : String(v)));
  }
  return dl;
}
export function initialiserDetail() {
  const d = document.getElementById("detail");
  d.querySelector("[data-fermer]").addEventListener("click", () => d.close ? d.close() : d.removeAttribute("open"));
  d.addEventListener("click", e => { if (e.target === d && d.close) d.close(); });   // clic sur le fond
}

/* Tri d'un tableau au clic sur l'en-tête : valeurs numériques, absents toujours en bas. */
export function rendreTriable(table, valeurDe) {
  let col = null, sens = -1;
  table.querySelectorAll("thead th").forEach((th, i) => {
    const bouton = th.querySelector("button");
    if (!bouton) return;
    bouton.addEventListener("click", () => {
      sens = col === i ? -sens : (i === 0 ? 1 : -1);
      col = i;
      table.querySelectorAll("thead th").forEach(t => t.removeAttribute("aria-sort"));
      th.setAttribute("aria-sort", sens > 0 ? "ascending" : "descending");
      const corps = table.tBodies[0];
      const lignes = [...corps.rows];
      lignes.sort((a, b) => {
        const va = valeurDe(a, i), vb = valeurDe(b, i);
        if (va === null && vb === null) return 0;
        if (va === null) return 1;
        if (vb === null) return -1;
        return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * sens;
      });
      corps.append(...lignes);
    });
  });
}

/* « En bref » : première phrase d'un texte rédigé, visible sur un accordéon replié. */
export function enBref(texte) {
  const t = String(texte || "").trim();
  if (!t) return null;
  const m = t.match(/^(.+?[.!?])(\s|$)/);
  const phrase = (m ? m[1] : t).slice(0, 220);
  const n = el("span", "en-bref");
  n.appendChild(el("strong", null, "En bref : "));
  n.appendChild(document.createTextNode(phrase));
  return n;
}

/* ------------------------------------------------------------------ certificat d'un chiffre (lot V5, page Santé)
   Composant unique : `certifier(noeud, {libelle, valeur, source, serie, date, indicateur})` rend le chiffre focalisable ;
   au survol, au focus ou au toucher, une bulle donne la source et la série, la date de la valeur, l'heure de
   récupération, le contrôle croisé (✓ / ⚠) et l'âge par rapport au calendrier normal (docs/data/sources.json, chargé
   au premier besoin). Une donnée plus vieille que deux fois sa fréquence normale passe en orange. */
const CERTS = new WeakMap();
const FREQ_JOURS = { "quotidienne (jours ouvrés)": 1, hebdomadaire: 7, mensuelle: 31, trimestrielle: 92, annuelle: 366, "à chaque run": 1 };
let bulle = null, sourcesPromesse = null;
const sourcesJson = () => (sourcesPromesse ??= chargerJson("data/sources.json"));

function joursOuvres(debut, fin) {
  let n = 0; const j = new Date(debut);
  while (j < fin) { j.setUTCDate(j.getUTCDate() + 1); if (j <= fin && j.getUTCDay() % 6 !== 0) n++; }
  return n;
}
/* Même règle que core/sources.py : vert jusqu'à 2 fois la normale, orange au-delà, rouge au-delà de 4 fois. */
const FREQ_CHIFFRE = { quotidien: "quotidienne (jours ouvrés)", hebdomadaire: "hebdomadaire", mensuel: "mensuelle", trimestriel: "trimestrielle" };
export function fraicheurLocale(date, regle, frequence) {
  if (!date || !regle) return null;
  if (frequence && FREQ_CHIFFRE[frequence]) regle = { frequence: FREQ_CHIFFRE[frequence], retard_jours: frequence === "mensuel" ? 45 : frequence === "trimestriel" ? 60 : 2 };
  const d = new Date(`${String(date).slice(0, 10)}T00:00:00Z`);
  if (isNaN(d)) return null;
  const quotidien = /jours ouvrés|chaque run/.test(regle.frequence || "");
  const normal = (FREQ_JOURS[regle.frequence] || 1) + (regle.retard_jours || 0);
  const aujourd = new Date(new Date().toISOString().slice(0, 10) + "T00:00:00Z");
  const age = quotidien ? joursOuvres(d, aujourd) : Math.round((aujourd - d) / 864e5);
  const etat = age <= 2 * normal ? "vert" : age <= 4 * normal ? "orange" : "rouge";
  return { etat, age_jours: age, normal_jours: normal, texte: `${age} ${quotidien ? (age < 2 ? "jour ouvré" : "jours ouvrés") : (age < 2 ? "jour" : "jours")} (normal : ${normal} au plus)` };
}

function regleDe(src, sources) {
  const s = String(src || "").toLowerCase();
  let meilleur = null, long = 0;
  for (const r of sources?.sources || []) for (const m of r.motifs || []) if (m && s.includes(m.toLowerCase()) && m.length > long) { meilleur = r; long = m.length; }
  return meilleur;
}

function remplirBulle(c, sources) {
  const cert = c.indicateur ? sources?.certificats?.[c.indicateur] : null;
  const regle = regleDe(c.source || cert?.source, sources);
  const fr = c.sansAge ? null : cert?.fraicheur || fraicheurLocale(c.date || cert?.date_valeur, regle, c.frequence);
  const lignes = [];
  const tete = el("div", "cert-tete");
  tete.append(el("b", null, `${c.libelle || cert?.libelle || "Chiffre"}${c.valeur != null ? ` ${c.valeur}` : ""}`));
  if (regle?.statut_libelle || cert?.statut) tete.appendChild(el("span", `cert-statut ${regle?.statut || ""}`, regle?.statut_libelle || cert.statut));
  lignes.push(tete);
  lignes.push(el("p", null, `Source : ${c.source || cert?.source || "n/d"}${c.serie ? ` · série ${c.serie}` : ""}`));
  const date = c.date || cert?.date_valeur;
  const recup = cert?.recupere_le || regle?.recupere_le;
  lignes.push(el("p", null, `Valeur du ${date ? dateCourte(date) : "n/d"}${recup ? ` · récupérée le ${String(recup).length > 10 ? dateHeure(recup) : dateCourte(recup)}` : ""}`));
  lignes.push(el("p", null, cert ? `Contrôle croisé : ${cert.controle} ${cert.controle === "✓" ? "même valeur dans tous les modules" : cert.controle_detail || ""}`
    : "Contrôle croisé : sans objet (valeur calculée ou propre à ce module)"));
  if (cert?.calendrier) lignes.push(el("p", "cert-calendrier", `Calendrier de publication : ${cert.calendrier}`));
  if (c.sansAge) lignes.push(el("p", "cert-age", `Âge : ${c.sansAge}`));
  else if (fr) lignes.push(el("p", `cert-age ${fr.etat}`, `Âge : ${fr.texte}`));
  else lignes.push(el("p", "cert-age", "Âge : n/d (source hors registre)"));
  bulle.replaceChildren(...lignes);
}

function placer(cible) {
  const r = cible.getBoundingClientRect();
  bulle.hidden = false;
  const l = Math.max(8, Math.min(window.innerWidth - bulle.offsetWidth - 8, r.left));
  const haut = r.bottom + 8 + bulle.offsetHeight > window.innerHeight ? r.top - bulle.offsetHeight - 8 : r.bottom + 8;
  bulle.style.left = `${l + window.scrollX}px`;
  bulle.style.top = `${Math.max(8, haut) + window.scrollY}px`;
}

async function montrer(cible) {
  const c = CERTS.get(cible);
  if (!c) return;
  bulle.replaceChildren(el("p", null, "Certificat…"));
  placer(cible);
  const sources = await sourcesJson();
  if (bulle.dataset.pour !== String(c.id)) return;
  remplirBulle(c, enErreur(sources) ? null : sources);
  placer(cible);
}
function cacher() { if (bulle) { bulle.hidden = true; bulle.dataset.pour = ""; } }

let compteur = 0;
export function certifier(noeud, c) {
  if (!noeud || !c) return noeud;
  c.id = ++compteur;
  CERTS.set(noeud, c);
  noeud.classList.add("cert");
  if (!c.sansFocus && !noeud.hasAttribute("tabindex") && !/^(BUTTON|A|INPUT|SELECT)$/.test(noeud.tagName)) noeud.tabIndex = 0;
  noeud.setAttribute("aria-describedby", "certificat");
  // Fraîcheur : orange / rouge visibles sans survol (sources.json chargé au premier chiffre certifié)
  sourcesJson().then(sources => {
    if (enErreur(sources)) return;
    const cert = c.indicateur ? sources.certificats?.[c.indicateur] : null;
    if (c.sansAge) return;
    const fr = cert?.fraicheur || fraicheurLocale(c.date || cert?.date_valeur, regleDe(c.source || cert?.source, sources), c.frequence);
    if (fr && fr.etat !== "vert") noeud.classList.add(`cert-${fr.etat}`);
  });
  return noeud;
}

export function initialiserCertificats() {
  bulle = el("div", "cert-bulle");
  bulle.id = "certificat"; bulle.setAttribute("role", "tooltip"); bulle.hidden = true;
  document.body.appendChild(bulle);
  const trouver = e => e.target?.closest?.(".cert");
  const ouvrir = e => { const t = trouver(e); if (!t) return; const c = CERTS.get(t); if (!c) return; bulle.dataset.pour = String(c.id); montrer(t); };
  document.addEventListener("mouseover", ouvrir);
  document.addEventListener("focusin", ouvrir);
  document.addEventListener("mouseout", e => { if (trouver(e) && !(e.relatedTarget && e.relatedTarget.closest?.(".cert") === trouver(e))) cacher(); });
  document.addEventListener("focusout", e => { if (trouver(e)) cacher(); });
  // Toucher : l'appui sur un chiffre montre son certificat ; un appui ailleurs le ferme
  document.addEventListener("touchstart", e => { const t = trouver(e); if (t) ouvrir(e); else cacher(); }, { passive: true });
  document.addEventListener("keydown", e => { if (e.key === "Escape") cacher(); });
  window.addEventListener("hashchange", cacher);
  window.addEventListener("scroll", cacher, { passive: true });
}

/* Accords : « 1 source », « 2 sources » (jamais « source(s) »). `pl` : forme plurielle si irrégulière. */
export function pluriel(n, sg, pl) { return `${n} ${Math.abs(Number(n)) < 2 ? sg : (pl || `${sg}s`)}`; }

/* Badge « au-dessus / en dessous / conforme » d'une publication (écart calculé en Python, sens du registre) :
   vert si favorable à la devise, rouge sinon ; mis en valeur si |écart| ≥ 0,5 point ou ≥ 1 σ. */
export function badgeEcart(ec) {
  if (!ec) return null;
  const cls = ec.sens === "conforme" ? "conforme" : ec.favorable ? "favorable" : "defavorable";
  const b = el("span", `badge-ecart ${cls}${ec.marque ? " marque" : ""}`, ec.texte);
  b.title = `${ec.sens === "conforme" ? "Publié égal au consensus" : `Écart ${ec.ecart > 0 ? "+" : ""}${String(ec.ecart).replace(".", ",")}`}`
    + `${ec.z != null ? ` · ${String(ec.z).replace(".", ",")} écarts habituels (σ) de l'indicateur` : ""}`
    + `${ec.inverse ? " · variable lue à l'inverse (une baisse soutient la devise)" : ""}`
    + `${ec.marque ? " · écart marqué (≥ 0,5 point ou ≥ 1 σ)" : ""}`;
  return b;
}

/* ------------------------------------------------------------------ lot V6 : règles communes aux 6 onglets
   « L'essentiel » : 3 lignes au plus, calculées en Python (ou dans la page à partir des données publiées). */
export function essentiel(lignes, titre = "L'essentiel") {
  const b = el("section", "essentiel");
  b.appendChild(el("h3", null, titre));
  const ul = el("ul");
  for (const l of (lignes || []).filter(Boolean).slice(0, 5)) ul.appendChild(el("li", null, l));
  b.appendChild(ul);
  return b;
}

/* « Voir le détail » : tout ce qui dépasse un écran. */
export function voirDetail(titre, ...noeuds) {
  const d = el("details", "voir-detail");
  d.open = vueComplete();   // vue complète : tout est déplié sans clic (lot V6.1)
  d.appendChild(el("summary", null, titre || "Voir le détail"));
  d.append(...noeuds.filter(Boolean));
  return d;
}

/* Glossaire UNIQUE du site : une seule définition par terme, au survol (ou au focus) de sa première occurrence
   dans chaque onglet. */
export const GLOSSAIRE = {
  "σ": "Écart habituel (écart-type) de l'indicateur : +1 σ = une surprise d'une taille habituelle, +2 σ = rare.",
  "percentile": "Rang de la valeur du jour sur 5 ans : percentile 90 = plus haut que 90 % des jours observés.",
  "BOS": "Cassure de structure (break of structure) : le cours dépasse le dernier sommet ou creux marquant.",
  "FVG": "Zone de déséquilibre (fair value gap) : intervalle de prix traversé si vite qu'aucun échange n'y a eu lieu.",
  "portage": "Gain ou coût de détention lié à l'écart de taux entre les deux devises d'une paire (carry).",
  "carry": "Portage : on emprunte la devise à taux bas pour placer dans celle à taux haut.",
  "corrélation": "Mesure de −1 à +1 du lien entre deux séries : elle dit ce qui bouge ensemble, jamais ce qui cause quoi.",
  "consensus": "Prévision médiane des économistes publiée avant le chiffre.",
  "pb": "Point de base : 0,01 point de pourcentage (25 pb = 0,25 %).",
  "RSI": "Indice de force relative (0 à 100) : au-dessus de 70, hausse rapide ; en dessous de 30, baisse rapide.",
  "MM200": "Moyenne mobile des 200 dernières séances : tendance de fond.",
  "VIX": "Volatilité attendue des actions américaines : une hausse traduit plus de stress.",
  "COT": "Positions des spéculateurs sur les contrats à terme (CFTC, chaque vendredi pour le mardi).",
  "risk-off": "Phase d'aversion au risque : les investisseurs vendent les actifs risqués et cherchent les refuges.",
  "risk-on": "Phase d'appétit pour le risque : actions et devises cycliques sont recherchées.",
  "invalidation": "Niveau ou évènement qui annule le scénario : s'il se produit, on abandonne la lecture.",
};

export function appliquerGlossaire(racine) {
  if (!racine) return;
  const vus = new Set();
  const termes = Object.keys(GLOSSAIRE).sort((a, b) => b.length - a.length);
  const echapper = t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const motif = new RegExp("(^|[^\\p{L}])(" + termes.map(echapper).join("|") + ")(?![\\p{L}])", "u");
  const marcheur = document.createTreeWalker(racine, NodeFilter.SHOW_TEXT, {
    acceptNode: n => (n.parentElement && !n.parentElement.closest("script, style, summary, .gloss, input, textarea, select, button, th, svg"))
      ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
  const noeuds = [];
  while (marcheur.nextNode()) noeuds.push(marcheur.currentNode);
  for (const n of noeuds) {
    const m = n.nodeValue.match(motif);
    if (!m || vus.has(m[2])) continue;
    vus.add(m[2]);
    const debut = m.index + m[1].length;
    const apres = n.splitText(debut);
    apres.nodeValue = apres.nodeValue.slice(m[2].length);
    const g = el("span", "gloss", m[2]);
    g.tabIndex = 0;
    g.title = GLOSSAIRE[m[2]];
    g.setAttribute("aria-label", `${m[2]} : ${GLOSSAIRE[m[2]]}`);
    n.parentNode.insertBefore(g, apres);
  }
}

/* ------------------------------------------------------------------ lot V6.1 : formats uniques des nombres
   Décimales FIXES par type de donnée, appliquées partout : « 0,00 % » et jamais « 0 % », « 158,70 » et jamais « 158,7 ». */
const nf = (v, d) => Number(v).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d }).replace("-", "−");
export const FMT = {
  nombre: (v, d = 2) => v == null || !isFinite(v) ? "n/d" : nf(v, d),
  signe: (v, d = 2) => v == null || !isFinite(v) ? "n/d" : `${v > 0 ? "+" : ""}${nf(v, d)}`,
  pct: (v, d = 2) => v == null || !isFinite(v) ? "n/d" : `${nf(v, d)} %`,
  varPct: (v, d = 2) => v == null || !isFinite(v) ? "n/d" : `${v > 0 ? "+" : ""}${nf(v, d)} %`,
  taux: v => v == null || !isFinite(v) ? "n/d" : `${nf(v, 2)} %`,
  pb: v => v == null || !isFinite(v) ? "n/d" : `${v > 0 ? "+" : ""}${nf(v, 0)} pb`,
  /* Prix d'une paire : décimales usuelles (4, ou 2 si le yen est en jeu) ; indices et matières premières : 2. */
  prix: (v, paire = "") => v == null || !isFinite(v) ? "n/d" : nf(v, /JPY/.test(paire) ? 2 : /\//.test(paire) ? 4 : 2),
};

/* Cellules numériques des tableaux : chasse fixe, alignées à droite (le texte reste en police normale). */
const NUMERIQUE = /^[+−\-–]?\s?(\d[\d\s\u202f\u00a0]*([.,]\d+)?|n\/d|—)\s*(%|pb|pts?|€|\$|K|M|Md|B|σ|R|pips|séances?|ans?)?$/;
export function marquerNombres(racine) {
  for (const td of (racine || document).querySelectorAll("table.dense td:not(.num)")) {
    const t = td.textContent.trim();
    if (t.length <= 22 && NUMERIQUE.test(t)) td.classList.add("num");
  }
}

/* Micro-graphique SVG (30 jours) : JavaScript et SVG purs, sans bibliothèque. */
export function miniCourbe(points, titre) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 88 22"); svg.setAttribute("class", "mini-courbe"); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", titre || "évolution sur 30 jours");
  const v = (points || []).map(p => Number(p[1])).filter(isFinite);
  if (v.length < 2) return svg;
  const min = Math.min(...v), max = Math.max(...v), et = max - min || 1;
  const xy = v.map((y, i) => [2 + (84 * i) / (v.length - 1), 20 - (18 * (y - min)) / et]);
  const path = document.createElementNS(NS, "path");
  path.setAttribute("d", xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(""));
  const c = document.createElementNS(NS, "circle");
  c.setAttribute("cx", xy[xy.length - 1][0].toFixed(1)); c.setAttribute("cy", xy[xy.length - 1][1].toFixed(1)); c.setAttribute("r", "1.8");
  const t = document.createElementNS(NS, "title"); t.textContent = titre || "";
  svg.append(t, path, c);
  return svg;
}

/* ------------------------------------------------------------------ lot V6.1 : Vue complète / Vue essentielle
   Mémorisée dans le navigateur (try/catch : sans stockage, la vue complète s'applique). Vue complète par défaut. */
export const CLE_VUE = "fxdesk-vue";
export function vueCourante() {
  const q = typeof location !== "undefined" ? new URLSearchParams(location.search).get("vue") : null;   // forçage ponctuel
  if (q === "essentielle" || q === "complete") return q;
  try { return localStorage.getItem(CLE_VUE) === "essentielle" ? "essentielle" : "complete"; }
  catch (e) { return "complete"; }
}
export function enregistrerVue(v) {
  try { localStorage.setItem(CLE_VUE, v === "essentielle" ? "essentielle" : "complete"); } catch (e) { /* sans stockage : pour cette visite */ }
  document.documentElement.dataset.vue = v === "essentielle" ? "essentielle" : "complete";
}
export const vueComplete = () => (document.documentElement.dataset.vue || vueCourante()) !== "essentielle";
