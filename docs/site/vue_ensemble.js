/* Vue d'ensemble des 8 engrenages (refonte V2, palier 1) : bandeau du thème, 8 cartes avec
   mini-courbes, chaînes de transmission. Données : dossiers.json → vue_ensemble (calcul Python). */
import { el, dateCourte } from "./commun.js";

const SVG = "http://www.w3.org/2000/svg";
function s(tag, attrs) {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  return n;
}
const COULEUR = { up: "var(--positif)", dn: "var(--negatif)", nd: "var(--accent)" };
const CONVICTION = ["non déterminée", "faible", "moyenne", "élevée"];

function points(n) {
  const p = el("span", "eg-points");
  p.setAttribute("role", "img");
  p.setAttribute("aria-label", `conviction ${CONVICTION[n] || "non déterminée"}`);
  for (let i = 0; i < 3; i++) p.appendChild(el("i", i < n ? "plein" : null));
  return p;
}
function puce(direction) {
  return el("span", `eg-puce dir-${direction?.classe || "nd"}`, direction?.libelle || "non déterminée");
}

/* Mini-courbe SVG (viewBox étirée, trait non déformé) ; null si moins de deux points. */
function miniCourbe(courbe, classe, titre) {
  const pts = courbe?.points || [];
  if (pts.length < 2) return el("p", "eg-sans-courbe", courbe?.raison ? `Pas de courbe : ${courbe.raison}.` : "Pas de courbe.");
  const L = 120, H = 28, vals = pts.map(p => p[1]);
  let min = Math.min(...vals), max = Math.max(...vals);
  if (min === max) { min -= 1; max += 1; }
  const y = v => (H - 3 - (v - min) / (max - min) * (H - 6)).toFixed(1);
  const x = i => (i / (pts.length - 1) * L).toFixed(1);
  const svg = s("svg", { viewBox: `0 0 ${L} ${H}`, preserveAspectRatio: "none", class: "eg-courbe", role: "img",
                         "aria-label": `${titre} : ${courbe.periode}, du ${dateCourte(pts[0][0])} au ${dateCourte(pts[pts.length - 1][0])}` });
  const couleur = COULEUR[classe] || COULEUR.nd;
  svg.appendChild(s("polyline", { points: pts.map((p, i) => `${x(i)},${y(p[1])}`).join(" "), fill: "none", stroke: couleur,
                                  "stroke-width": 1.8, "vector-effect": "non-scaling-stroke" }));
  svg.appendChild(s("circle", { cx: L, cy: y(vals[vals.length - 1]), r: 2.5, fill: couleur }));
  return svg;
}

export function selecteurPeriode(active) {
  const c = el("div", "eg-tete");
  const titre = el("div");
  titre.appendChild(el("h1", "eg-titre", "Les 8 engrenages"));
  titre.appendChild(el("p", "eg-chapo", "Ce qui fait bouger le marché, du récit global jusqu'aux chiffres. Directions et convictions calculées en Python, texte formulé par le modèle."));
  const nav = el("nav", "eg-seg");
  nav.setAttribute("aria-label", "Période");
  for (const [id, lib] of [["", "Quotidien"], ["hebdo", "Hebdo"], ["mensuel", "Mensuel"]]) {
    if (id === "mensuel") {
      const b = el("span", "eg-seg-off", lib);
      b.setAttribute("aria-disabled", "true"); b.title = "Vue mensuelle : palier ultérieur de la refonte";
      nav.appendChild(b); continue;
    }
    const a = el("a", null, lib); a.href = `#engrenages${id ? "/" + id : ""}`;
    a.setAttribute("aria-pressed", String(active === id));
    if (active === id) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  }
  c.append(titre, nav);
  return c;
}

function bandeau(v) {
  const t = v.theme || {};
  const c = el("section", "carte eg-bandeau");
  c.appendChild(el("div", "eg-sur-titre", `THÈME DU JOUR${t.date_rapport ? ` · ${dateCourte(t.date_rapport)}` : ""}`));
  if (!t.titre) {
    c.appendChild(el("h2", "eg-theme", "Thème non déterminé"));
    c.appendChild(el("p", "indisponible", `Indisponible : ${t.raison || "synthèse absente"}.`));
    return c;
  }
  c.appendChild(el("h2", "eg-theme", t.titre));
  if (t.texte) {
    const p = el("p", "eg-theme-texte", t.texte);
    if (t.texte_redige_par) p.appendChild(el("span", "source", ` — formulé par ${t.texte_redige_par} à partir des chiffres Python`));
    c.appendChild(p);
  }
  const stats = el("div", "eg-stats");
  const d = t.direction || {};
  const boite = (libelle, ...enfants) => { const b = el("div", "eg-stat"); b.appendChild(el("b", null, libelle)); b.append(...enfants); return b; };
  const puces = el("div", "eg-puces");
  for (const [txt, cls] of [[{ haussier: "Dollar ↑", baissier: "Dollar ↓", neutre: "Dollar =" }[d.dollar], d.dollar === "haussier" ? "up" : d.dollar === "baissier" ? "dn" : "nd"],
                            [{ risk_on: "Risk on", risk_off: "Risk off", neutre: "Risque neutre" }[d.risque], d.risque === "risk_off" ? "dn" : d.risque === "risk_on" ? "up" : "nd"]])
    if (txt) puces.appendChild(el("span", `eg-puce dir-${cls}`, txt));
  stats.appendChild(boite("Direction", puces));
  const coh = t.coherence;
  const vCoh = el("span", "eg-gros tabulaire", coh ? `${coh.alignes}/${coh.sur}` : "n/d");
  vCoh.title = coh ? `${coh.regle} Alignés : ${coh.engrenages_alignes.join(", ") || "aucun"}.` : "";
  stats.appendChild(boite("Cohérence", vCoh, el("span", "eg-petit", coh ? (coh.engrenages_alignes.length ? `alignés : ${coh.engrenages_alignes.join(", ")}` : "aucun engrenage aligné") : "")));
  stats.appendChild(boite("Conviction", points(d.conviction || 0), el("span", "eg-petit", CONVICTION[d.conviction || 0])));
  c.appendChild(stats);
  if (coh) c.appendChild(el("p", "note", `Cohérence : ${coh.regle}`));
  return c;
}

function carte(c, actif, choisir) {
  const b = el("button", `eg-carte dir-${c.direction?.classe || "nd"}`);
  b.type = "button";
  b.setAttribute("aria-pressed", String(c.numero === actif));
  const ch = c.chiffre || {};
  b.setAttribute("aria-label", `Engrenage ${c.numero}, ${c.titre} : ${ch.libelle} ${ch.texte || "n/d"}, ${c.direction?.libelle || "direction non déterminée"}, conviction ${CONVICTION[c.direction?.conviction || 0]}. Ouvrir le dossier.`);
  b.appendChild(el("span", "eg-num", `ENGRENAGE ${c.numero}`));
  b.appendChild(el("span", "eg-nom", c.titre));
  const v = el("span", "eg-valeur tabulaire", ch.texte || "n/d");
  if (!ch.texte && ch.raison) v.title = ch.raison;
  b.appendChild(v);
  b.appendChild(el("span", "eg-libelle", `${ch.libelle}${ch.date ? ` · ${String(ch.date).length > 7 ? dateCourte(ch.date) : ch.date}` : ""}`));
  b.appendChild(el("span", "eg-ligne", c.ligne));
  b.appendChild(miniCourbe(c.courbe, c.direction?.classe, `${c.titre}, ${ch.libelle}`));
  const bas = el("span", "eg-bas");
  bas.append(puce(c.direction), points(c.direction?.conviction || 0));
  b.appendChild(bas);
  b.title = [ch.source && `Source : ${ch.source}`, c.courbe?.periode && `courbe : ${c.courbe.periode}`,
             c.direction?.origine && `direction : ${c.direction.origine}`].filter(Boolean).join(" · ");
  b.addEventListener("click", () => choisir(c.numero, true));
  return b;
}

function chaines(v) {
  const c = el("section", "carte");
  const liste = v.chaines || [];
  if (!liste.length) c.appendChild(el("p", "note", v.statut_texte === "ok" ? "Aucune chaîne de transmission retenue aujourd'hui." :
    "Chaînes indisponibles : la synthèse rédigée des engrenages manque pour ce rapport."));
  for (const ch of liste) {
    if (ch.titre) c.appendChild(el("h3", "eg-chaine-titre", ch.titre));
    const rang = el("ol", "eg-chaine");
    rang.setAttribute("aria-label", `Chaîne de transmission : ${ch.titre || ""}`);
    ch.maillons.forEach((m, i) => {
      if (i) { const f = el("li", "eg-fleche", "→"); f.setAttribute("aria-hidden", "true"); rang.appendChild(f); }
      const n = el("li", "eg-maillon");
      n.appendChild(el("b", null, String(m.engrenage)));
      n.appendChild(document.createTextNode(m.texte));
      if (m.non_sourcee) n.appendChild(el("span", "tag-alerte", " [non sourcé]"));
      rang.appendChild(n);
    });
    c.appendChild(rang);
  }
  if ((v.conflits || []).length) {
    const b = el("div", "encadre orange");
    b.appendChild(el("strong", null, "Engrenages en conflit. "));
    b.appendChild(document.createTextNode(v.conflits.map(x => `(${x.engrenages[0]}) contre (${x.engrenages[1]}) : ${x.texte}`).join(" ")));
    c.appendChild(b);
  }
  if (v.redige_par) c.appendChild(el("p", "source", `Maillons formulés par ${v.redige_par} ; numéros d'engrenage et sources vérifiés en Python.`));
  return c;
}

/* Retourne les nœuds de la vue d'ensemble ; `choisir(n, defiler)` ouvre le dossier n. */
export function vueEnsemble(v, actif, choisir) {
  if (!v || v.indisponible) {
    const c = el("section", "carte");
    c.appendChild(el("p", "indisponible", `Vue d'ensemble indisponible : ${v?.indisponible || "absente de dossiers.json"}.`));
    return { noeuds: [c], marquer: () => {} };
  }
  const grille = el("div", "eg-grille");
  const cartes = (v.cartes || []).map(c => carte(c, actif, choisir));
  grille.append(...cartes);
  const sec = (titre, sous) => { const d = el("div", "eg-section"); d.append(el("h2", null, titre), el("span", null, sous)); return d; };
  return {
    noeuds: [bandeau(v), sec("Vue d'ensemble", "un coup d'œil sur les 8 moteurs · touchez une carte pour ouvrir son dossier"), grille,
             sec("Chaînes de transmission", "comment les engrenages s'entraînent aujourd'hui"), chaines(v)],
    marquer: n => cartes.forEach((b, i) => b.setAttribute("aria-pressed", String(i + 1 === n))),
  };
}
