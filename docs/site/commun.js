/* Utilitaires partagés : DOM, chargement des JSON, formats, fenêtre de détail. */

export function el(tag, classe, texte) {
  const n = document.createElement(tag);
  if (classe) n.className = classe;
  if (texte !== undefined && texte !== null) n.textContent = texte;
  return n;
}

/* Données : chaque fichier est chargé une fois ; un échec renvoie {erreur} (jamais d'exception). */
const cache = new Map();
export function chargerJson(chemin) {
  if (!cache.has(chemin)) {
    cache.set(chemin, fetch(chemin, { cache: "no-store" })
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
