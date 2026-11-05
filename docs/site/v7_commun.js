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

/* ------------------------------------------------------------ Lot V8 : bougies (Paris), temps relatif, fraîcheur, mouvement */
export const tsBougie = s => Math.floor(Date.parse(String(s).replace(" ", "T") + (String(s).length <= 10 ? "T00:00:00Z" : "Z")) / 1000);
export const heureParis = (ts, avecJour = false) => new Date(ts * 1000).toLocaleString("fr-FR", { timeZone: "Europe/Paris", ...(avecJour ? { day: "2-digit", month: "2-digit" } : {}), hour: "2-digit", minute: "2-digit" });
/* bougies : [[horodatage UTC, o, h, b, c]] ; options : marqueurs [{ts, texte, couleur, position, forme}], lignes de prix
   [{prix, couleur, titre, style}], courbes [{points:[[horodatage, v]], couleur, titre}] (MM calculées en Python). */
export async function graphiqueBougies(boite, bougies, dec, { marqueurs = [], lignesPrix = [], courbes = [] } = {}) {
  const L = await chargerLWC();
  boite.innerHTML = "";
  if (!L || !boite.isConnected || !bougies?.length) {
    boite.innerHTML = bougies?.length ? spark(bougies.map(b => b[4]), 800, 300, "var(--accent)", true).replace("<svg", '<svg style="width:100%;height:100%"') : '<div class="empty">Bougies indisponibles.</div>';
    return null;
  }
  const fmt = t => typeof t === "number" ? heureParis(t, true) : t;
  const c = L.createChart(boite, { autoSize: true, ...optionsTheme(),
    localization: { locale: "fr-FR", timeFormatter: fmt, priceFormatter: v => v.toLocaleString("fr-FR", { minimumFractionDigits: dec, maximumFractionDigits: dec }) },
    timeScale: { borderVisible: false, timeVisible: true, tickMarkFormatter: t => typeof t === "number" ? new Date(t * 1000).toLocaleString("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(" ", " · ") : t } });
  const s = c.addCandlestickSeries({ upColor: css("--up"), downColor: css("--down"), borderVisible: false, wickUpColor: css("--up"), wickDownColor: css("--down"),
    priceFormat: { type: "price", precision: dec, minMove: Math.pow(10, -dec) } });
  const data = bougies.map(b => ({ time: tsBougie(b[0]), open: b[1], high: b[2], low: b[3], close: b[4] }));
  s.setData(data);
  for (const l of lignesPrix) if (l.prix != null) s.createPriceLine({ price: l.prix, color: css(l.couleur), lineWidth: 1, lineStyle: l.style ?? 2, axisLabelVisible: true, title: l.titre || "" });
  const t0 = data[0].time, tN = data[data.length - 1].time;
  const caler = ts => { let m = null; for (const d of data) { if (d.time <= ts) m = d.time; else break; } return m; };
  const mk = marqueurs.filter(m => m.ts >= t0 && m.ts <= tN + 3600).map(m => ({ time: caler(m.ts), position: m.position || "aboveBar", color: css(m.couleur || "--warn"), shape: m.forme || "circle", text: m.texte || "" }))
    .filter(m => m.time != null).sort((a, b) => a.time - b.time);
  s.setMarkers(mk);
  for (const k of courbes) {
    const ls = c.addLineSeries({ color: css(k.couleur), lineWidth: 2, title: k.titre || "", priceLineVisible: false, lastValueVisible: false });
    ls.setData(k.points.map(p => p[1] == null ? { time: tsBougie(p[0]) } : { time: tsBougie(p[0]), value: p[1] }));
  }
  c.timeScale().fitContent();
  const g = { c, objets: [], boite, bougies: s };
  graphiques.add(g);
  return g;
}
export function tempsRelatif(sec) {
  const a = Math.abs(sec), hh = Math.floor(a / 3600), m = Math.round(a % 3600 / 60);
  const t = hh ? `${hh} h ${String(m).padStart(2, "0")}` : `${m} min`;
  return sec >= 0 ? "dans " + t : "il y a " + t;
}
/* Point de fraîcheur d'un bloc (règle calculée en Python : docs/data/fraicheur.json). */
export async function pointFraicheur(cible, bloc) {
  const f = (await donnees("fraicheur"))?.blocs?.[bloc];
  if (!f || !cible) return;
  const p = h("span", `fr-dot ${f.etat}`);
  p.tabIndex = 0; p.setAttribute("role", "img");
  p.setAttribute("aria-label", `Fraîcheur ${f.etat} : ${f.texte}`); p.title = f.texte;
  (cible.querySelector("h2,h3") || cible).appendChild(p);
}
/* Chiffres qui défilent jusqu'à leur valeur (300 ms) à l'ouverture d'un onglet ; coupé avec prefers-reduced-motion. */
export function animerChiffres(racine) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  for (const e of racine.querySelectorAll(".anim-num")) {
    if (e.dataset.anime) continue;   // une seule fois par valeur affichée : jamais une cible intermédiaire
    e.dataset.anime = "1";
    const txt = e.textContent, m = txt.match(/^([^\d−-]*)([−-]?)([\d\s ]+(?:,\d+)?)(.*)$/);
    if (!m) continue;
    const cible = Number(m[3].replace(/[\s ]/g, "").replace(",", ".")), dec = (m[3].split(",")[1] || "").length;
    if (!isFinite(cible)) continue;
    const t0 = performance.now();
    const pas = t => { const k = Math.min(1, (t - t0) / 300), v = cible * (1 - Math.pow(1 - k, 3));
      e.textContent = m[1] + m[2] + v.toLocaleString("fr-FR", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + m[4];
      if (k < 1) requestAnimationFrame(pas); else e.textContent = txt; };
    requestAnimationFrame(pas);
  }
}
