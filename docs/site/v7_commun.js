/* Lot V7 : outils communs des écrans (repris de docs/design/maquette_v7.html). Le JavaScript AFFICHE seulement :
   scores, états, directions, couleurs de sens et classements viennent des JSON produits en Python. */
import { chargerJson, enErreur, VERSION } from "./commun.js";

export const $ = (s, r = document) => r.querySelector(s);
export const h = (t, c, html) => { const e = document.createElement(t); if (c) e.className = c; if (html != null) e.innerHTML = html; return e; };
export const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
export const nf = (v, d) => Math.abs(v).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
export const sgn = (v, d, u) => v == null || isNaN(v) ? "n/d" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf(v, d) + (u || "");
export const num = (v, d, u) => v == null || isNaN(v) ? "n/d" : (v < 0 ? "−" : "") + nf(v, d) + (u || "");
export const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const JOURS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
export const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
export const dfr = iso => { if (!iso) return ""; const d = new Date(String(iso).slice(0, 10) + "T12:00:00Z"); return d.getUTCDate() + " " + MOIS[d.getUTCMonth()]; };
export const ddm = iso => iso ? String(iso).slice(8, 10) + "/" + String(iso).slice(5, 7) : "";
export const jourSem = iso => JOURS[new Date(String(iso).slice(0, 10) + "T12:00:00Z").getUTCDay()];
export const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* stockage indisponible : préférence non mémorisée */ } },
};
/* Valeurs textuelles du pipeline (« 3.5% ») : virgule décimale et espace avant %, sans recalcul. */
export const frTxt = s => s == null ? "" : String(s).replace(/(\d)\.(\d)/g, "$1,$2").replace(/(\d)%/g, "$1 %").replace(/^-(?=\d)/, "−");
/* « n/d » : la raison au survol, jamais dans la cellule (règle DESIGN.md). */
export const nd = raison => `<span class="nd" tabindex="0" title="${esc(raison || "donnée indisponible")}">n/d</span>`;
export const UNI = { "%": " %", "% PIB": " % PIB", pb: " pb", pts: " pts", contrats: "" };
export function fv(v, u) {
  if (v == null || typeof v !== "number") return v == null ? "n/d" : String(v);
  const d = (u === "pb" || u === "contrats") ? 0 : Math.abs(v) >= 100 ? 1 : 2;
  return (v < 0 ? "−" : "") + nf(v, d) + (UNI[u] ?? (u && u !== "niveau" && u !== "indice" && u !== "score" ? " " + u : ""));
}
export const classeEtat = e => /Soutenue/.test(e || "") ? "up" : /pression/i.test(e || "") ? "dn" : /contredit/.test(e || "") ? "warn" : "";
export const classeDir = c => c === "up" ? "up" : c === "dn" ? "dn" : "";
export const classeSigne = v => v > 0 ? "pos" : v < 0 ? "neg" : "muted";

/* Micro-graphique SVG maison (fonction « spark » de la maquette) ; couleurs en variables CSS : suivent le thème. */
export function spark(vals, w, hgt, couleur = "var(--accent)", aire = false) {
  vals = (vals || []).filter(v => v != null && !isNaN(v));
  if (vals.length < 2) return `<svg viewBox="0 0 ${w} ${hgt}" aria-hidden="true"></svg>`;
  const mn = Math.min(...vals), mx = Math.max(...vals), r = (mx - mn) || 1, p = 3;
  const pts = vals.map((v, i) => [p + i * (w - 2 * p) / (vals.length - 1), p + (hgt - 2 * p) * (1 - (v - mn) / r)]);
  const d = pts.map((q, i) => (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1)).join("");
  const der = pts[pts.length - 1], id = "g" + Math.random().toString(36).slice(2, 8);
  return `<svg viewBox="0 0 ${w} ${hgt}" preserveAspectRatio="none" aria-hidden="true">
    ${aire ? `<defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:${couleur};stop-opacity:.22"/><stop offset="1" style="stop-color:${couleur};stop-opacity:0"/></linearGradient></defs><path d="${d}L${der[0]} ${hgt}L${p} ${hgt}Z" fill="url(#${id})"/>` : ""}
    <path d="${d}" style="fill:none;stroke:${couleur}" stroke-width="1.8" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
    <circle cx="${der[0]}" cy="${der[1]}" r="2.6" style="fill:${couleur}"/></svg>`;
}

/* Barre divergente (force, surprises) : valeur, échelle, texte, repère précédent. */
export function hbar(lab, v, echelle, txt, prec, cls, titre) {
  if (v == null) return `<div class="hbar"><span style="font-weight:600">${lab}</span><div class="tr"></div><span style="text-align:right">${nd(titre)}</span></div>`;
  const w = Math.min(Math.abs(v) / echelle, 1) * 50, col = v >= 0 ? "var(--up)" : "var(--down)";
  const pm = prec != null ? `<em style="left:${50 + Math.max(-1, Math.min(1, prec / echelle)) * 50}%"></em>` : "";
  return `<div class="hbar"${titre ? ` title="${esc(titre)}"` : ""}><span style="font-weight:600">${lab}</span><div class="tr"><i style="${v >= 0 ? "left:50%" : "right:50%"};width:${w}%;background:${col};opacity:.85"></i>${pm}</div><span style="text-align:right;font-weight:600" class="${cls || classeSigne(v)}">${txt}</span></div>`;
}

/* Données : chaque JSON est chargé une seule fois par visite (les onglets se chargent à leur ouverture). */
const cache = new Map();
export function donnees(nom) {
  if (!cache.has(nom)) cache.set(nom, chargerJson(`data/${nom}.json`).then(d => enErreur(d) ? null : d));
  return cache.get(nom);
}
export { enErreur };

/* Bloc en panne : n'empêche jamais le reste de l'écran (règle absolue). */
export function bloc(conteneur, fn) {
  try { fn(); } catch (e) {
    console.error(e);
    conteneur.innerHTML = `<div class="card pad muted">Bloc indisponible : ${esc(e.message)}</div>`;
  }
}
export const squelette = (n = 3, haut = 120) => Array.from({ length: n }, () => `<div class="card skel" style="height:${haut}px"></div>`).join("");

/* ------------------------------------------------------------ Lightweight Charts (local, chargé à la demande) */
let promesseLWC = null;
export function chargerLWC() {
  if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
  if (!promesseLWC) promesseLWC = new Promise(ok => {
    const s = document.createElement("script");
    s.src = `site/vendor/lightweight-charts.standalone.production.js?v=${VERSION}`;
    s.onload = () => ok(window.LightweightCharts || null);
    s.onerror = () => ok(null);   // repli : micro-graphique SVG
    document.head.appendChild(s);
  });
  return promesseLWC;
}
const graphiques = new Set();
export function optionsTheme() {
  return {
    layout: { background: { color: "transparent" }, textColor: css("--muted"), fontFamily: '"Instrument Sans", -apple-system, "Segoe UI", sans-serif', fontSize: 12, attributionLogo: true },
    grid: { vertLines: { visible: false }, horzLines: { color: css("--line") } },
    rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false },
    crosshair: { vertLine: { labelBackgroundColor: css("--ink") }, horzLine: { labelBackgroundColor: css("--ink") } },
  };
}
const fmtPrix = dec => v => v.toLocaleString("fr-FR", { minimumFractionDigits: dec, maximumFractionDigits: dec });
/* series : [{l, p:[[date, valeur]], couleur:"--c1"}] ; une seule série = aire. */
export async function graphique(boite, series, dec = 2, options = {}) {
  const L = await chargerLWC();
  boite.innerHTML = "";
  if (!L || !boite.isConnected) {
    const s = series[0];
    boite.innerHTML = spark((s?.p || []).map(q => q[1]), 800, 300, "var(--accent)", true).replace("<svg", '<svg style="width:100%;height:100%"');
    return null;
  }
  const c = L.createChart(boite, { autoSize: true, localization: { locale: "fr-FR", dateFormat: "dd/MM/yy", priceFormatter: fmtPrix(dec) }, ...optionsTheme(), ...options });
  const objets = series.map(s => {
    const col = css(s.couleur || "--accent");
    const ser = series.length === 1
      ? c.addAreaSeries({ lineColor: col, topColor: col + "44", bottomColor: col + "00", lineWidth: 2, title: s.l || "", priceFormat: { type: "price", precision: dec, minMove: Math.pow(10, -dec) } })
      : c.addLineSeries({ color: col, lineWidth: 2, title: s.l || "", priceFormat: { type: "price", precision: dec, minMove: Math.pow(10, -dec) } });
    ser.setData(s.p.filter(q => q[1] != null).map(q => ({ time: q[0].slice(0, 10), value: q[1] })));
    return [ser, s.couleur || "--accent", series.length === 1];
  });
  const g = { c, objets, boite };
  graphiques.add(g);
  c.timeScale().fitContent();
  requestAnimationFrame(() => { try { c.timeScale().fitContent(); } catch (e) { /* graphique retiré */ } });
  return g;
}
export function retirerGraphique(g) { if (g) { graphiques.delete(g); try { g.c.remove(); } catch (e) { /* déjà retiré */ } } }
/* Au changement de thème : couleurs réappliquées (axes, grille, séries). */
export function rethemer() {
  for (const g of [...graphiques]) {
    if (!g.boite.isConnected) { graphiques.delete(g); continue; }
    g.c.applyOptions(optionsTheme());
    for (const [ser, v, aire] of g.objets) {
      const col = css(v);
      ser.applyOptions(aire ? { lineColor: col, topColor: col + "44", bottomColor: col + "00" } : { color: col });
    }
  }
}
/* Écran devenu visible : recadrage (sinon graphique écrasé à droite, bug constaté dans la maquette). */
export function recadrer(racine) {
  for (const g of graphiques) if (racine.contains(g.boite)) { try { g.c.timeScale().fitContent(); } catch (e) { /* ignoré */ } }
}

/* Bloc « version détaillée » : rend un ancien module (fonctionnalités conservées) à la première ouverture. */
export function blocDetaille(titre, sousTitre, charger) {
  const d = h("details", "card detaille full");
  d.innerHTML = `<summary><span><b>${esc(titre)}</b><span class="small"> · ${esc(sousTitre)}</span></span></summary>`;
  const corps = h("div", "legacy"); d.appendChild(corps);
  let fait = false;
  d.addEventListener("toggle", async () => {
    if (!d.open || fait) return;
    fait = true;
    corps.innerHTML = squelette(2, 90);
    try { corps.replaceChildren(...(await charger())); }
    catch (e) { console.error(e); corps.innerHTML = `<p class="muted">Indisponible : ${esc(e.message)}</p>`; }
  });
  return d;
}
