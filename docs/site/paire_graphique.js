/* Lot V8.2 — graphiques de la page Paire : bougies + panneau RSI synchronisés, zones de supports et résistances,
   lignes de tendance, divergences ; carte « Écart de taux » (clôture de la paire en haut, écart en pb en bas, jamais
   deux axes sur un même graphique). Tout est calculé en Python (paires/XXX-YYY.json) : ce module ne fait que dessiner. */
import { css, chargerLWC, optionsTheme, tsBougie, heureParis, suivreGraphique, retirerGraphique, nf } from "./v7_commun.js";

const LARGEUR_AXE = 82;
const alpha = (couleur, a) => /^#[0-9a-f]{6}$/i.test(couleur) ? couleur + a : couleur;
const OPACITE = { 1: "40", 2: "70", 3: "a8" };   // force 1, 2, 3 (opacité)
const EPAISSEUR = { 1: 1, 2: 1, 3: 2 };
const ETIQUETEES = new Set(["R1", "R2", "S1", "S2"]);   // étiquettes limitées aux 2 zones les plus proches de chaque côté

/* Synchronise deux graphiques : même défilement (plage logique) et même curseur. */
function synchroniser(a, b, sa, sb, valeurs) {
  let verrou = false;
  const relier = (x, y) => x.timeScale().subscribeVisibleLogicalRangeChange(r => {
    if (!r || verrou) return; verrou = true; try { y.timeScale().setVisibleLogicalRange(r); } finally { verrou = false; } });
  relier(a, b); relier(b, a);
  const curseur = (x, y, sy, carte) => x.subscribeCrosshairMove(p => {
    if (!p || p.time == null || !p.point) { y.clearCrosshairPosition(); return; }
    const v = carte.get(p.time);
    if (v == null) y.clearCrosshairPosition(); else y.setCrosshairPosition(v, p.time, sy);
  });
  curseur(a, b, sb, valeurs.b); curseur(b, a, sa, valeurs.a);
}

const fmtTemps = t => typeof t === "number" ? heureParis(t, true) : t;
const repere = t => typeof t === "number" ? new Date(t * 1000).toLocaleString("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(" ", " · ") : t;

/* opts : {unite, dec, lignesPrix, marqueurs, courbes, zones:[{haut, bas, force, etiquette, cote}], lignes:[{p1, fin, etat}],
   rsi:[[t, v]] ou null, divergences:[{sens, p1, p2, texte}], hauteurRsi} -> {retirer()} */
export async function graphiquePaire(boite, boiteRsi, bougies, opts) {
  const L = await chargerLWC();
  boite.innerHTML = ""; boiteRsi.innerHTML = "";
  if (!L || !boite.isConnected) { boite.innerHTML = '<div class="empty">Bibliothèque de graphiques indisponible.</div>'; return null; }
  const dec = opts.dec, avecRsi = !!(opts.rsi && opts.rsi.length);
  const loc = { locale: "fr-FR", timeFormatter: fmtTemps, priceFormatter: v => v.toLocaleString("fr-FR", { minimumFractionDigits: dec, maximumFractionDigits: dec }) };
  const c = L.createChart(boite, { autoSize: true, ...optionsTheme(), localization: loc,
    rightPriceScale: { borderVisible: false, minimumWidth: LARGEUR_AXE },
    timeScale: { borderVisible: false, timeVisible: true, visible: !avecRsi, tickMarkFormatter: repere } });
  const s = c.addCandlestickSeries({ upColor: css("--up"), downColor: css("--down"), borderVisible: false, wickUpColor: css("--up"), wickDownColor: css("--down"),
    priceFormat: { type: "price", precision: dec, minMove: Math.pow(10, -dec) } });
  const data = bougies.map(b => ({ time: tsBougie(b[0]), open: b[1], high: b[2], low: b[3], close: b[4] }));
  s.setData(data);
  const t0 = data[0].time, tN = data[data.length - 1].time;
  const caler = ts => { let m = null; for (const d of data) { if (d.time <= ts) m = d.time; else break; } return m; };
  for (const l of opts.lignesPrix || []) if (l.prix != null) s.createPriceLine({ price: l.prix, color: css(l.couleur), lineWidth: 1, lineStyle: l.style ?? 2, axisLabelVisible: true, title: l.titre || "" });
  // Supports et résistances : bande entre le haut et le bas de la zone ; épaisseur et opacité selon la force
  for (const z of opts.zones || []) {
    const col = alpha(css(z.cote === "resistance" ? "--down" : "--up"), OPACITE[z.force] || "8c");
    const ep = EPAISSEUR[z.force] || 1, etiq = ETIQUETEES.has(z.nom);
    const bord = z.cote === "resistance" ? z.bas : z.haut;   // étiquette sur le bord le plus proche du cours
    s.createPriceLine({ price: bord, color: col, lineWidth: ep, lineStyle: 0, axisLabelVisible: etiq, axisLabelColor: col, title: etiq ? z.etiquette : "" });
    const autre = bord === z.haut ? z.bas : z.haut;
    if (Math.abs(z.haut - z.bas) > Math.pow(10, -dec)) s.createPriceLine({ price: autre, color: col, lineWidth: ep, lineStyle: 0, axisLabelVisible: false, title: "" });
  }
  // Lignes de tendance : pleines si valides, pointillées et estompées si cassées depuis peu (masquées au-delà, Python)
  for (const l of opts.lignes || []) {
    const a = caler(tsBougie(l.p1.date)), b = caler(tsBougie(l.fin.date));
    if (a == null || b == null || a >= b) continue;
    const cassee = l.etat !== "valide", col = css(l.sens === "support" ? "--up" : "--down");
    const ls = c.addLineSeries({ color: cassee ? alpha(col, "80") : col, lineWidth: 2, lineStyle: cassee ? 2 : 0, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      title: `${l.sens === "support" ? "Support" : "Résistance"} ${cassee ? "(cassée)" : ""}`.trim() });
    ls.setData([{ time: a, value: l.p1.prix }, { time: b, value: l.fin.prix }]);
  }
  for (const k of opts.courbes || []) {
    const ls = c.addLineSeries({ color: css(k.couleur), lineWidth: 2, title: k.titre || "", priceLineVisible: false, lastValueVisible: false });
    ls.setData(k.points.map(p => p[1] == null ? { time: tsBougie(p[0]) } : { time: tsBougie(p[0]), value: p[1] }));
  }
  const mk = (opts.marqueurs || []).filter(m => m.ts >= t0 && m.ts <= tN + 3600).map(m => ({ time: caler(m.ts), position: m.position || "aboveBar", color: css(m.couleur || "--warn"), shape: m.forme || "circle", text: m.texte || "" }));
  const mkRsi = [];
  for (const d of opts.divergences || []) {
    const haut = d.sens === "baissière", col = css(haut ? "--down" : "--up");
    for (const p of [d.p1, d.p2]) {
      const t = caler(tsBougie(p.date));
      if (t == null) continue;
      mk.push({ time: t, position: haut ? "aboveBar" : "belowBar", color: col, shape: haut ? "arrowDown" : "arrowUp", text: p === d.p2 ? "Div." : "" });
      mkRsi.push({ time: t, position: haut ? "aboveBar" : "belowBar", color: col, shape: "circle", text: p === d.p2 ? "Div." : "" });
    }
  }
  s.setMarkers(mk.filter(m => m.time != null).sort((a, b) => a.time - b.time));
  c.timeScale().fitContent();
  const g = { c, objets: [], boite };
  suivreGraphique(g);
  let r = null;
  if (avecRsi) {
    r = L.createChart(boiteRsi, { autoSize: true, ...optionsTheme(), localization: { locale: "fr-FR", timeFormatter: fmtTemps, priceFormatter: v => nf(v, 0) },
      rightPriceScale: { borderVisible: false, minimumWidth: LARGEUR_AXE, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderVisible: false, timeVisible: true, tickMarkFormatter: repere }, handleScale: { axisPressedMouseMove: { price: false } } });
    const pts = opts.rsi.map(([t, v]) => v == null ? { time: tsBougie(t) } : { time: tsBougie(t), value: v });
    const teinte = (base, haut) => r.addBaselineSeries({ baseValue: { type: "price", price: base }, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      topLineColor: "transparent", bottomLineColor: "transparent", topFillColor1: haut ? alpha(css("--down"), "40") : "transparent", topFillColor2: haut ? alpha(css("--down"), "40") : "transparent",
      bottomFillColor1: haut ? "transparent" : alpha(css("--up"), "40"), bottomFillColor2: haut ? "transparent" : alpha(css("--up"), "40"), autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });
    teinte(70, true).setData(pts); teinte(30, false).setData(pts);
    const sr = r.addLineSeries({ color: css("--accent"), lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: "RSI 14",
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });
    sr.setData(pts);
    for (const [v, st] of [[70, 2], [50, 3], [30, 2]]) sr.createPriceLine({ price: v, color: css("--muted"), lineWidth: 1, lineStyle: st, axisLabelVisible: v !== 50, title: "" });
    sr.setMarkers(mkRsi.filter(m => m.time != null).sort((a, b) => a.time - b.time));
    r.timeScale().fitContent();
    const vRsi = new Map(pts.filter(p => p.value != null).map(p => [p.time, p.value])), vPrix = new Map(data.map(d => [d.time, d.close]));
    synchroniser(c, r, s, sr, { a: vPrix, b: vRsi });
    requestAnimationFrame(() => { try { r.timeScale().setVisibleLogicalRange(c.timeScale().getVisibleLogicalRange()); } catch (e) { /* retiré */ } });
    suivreGraphique({ c: r, objets: [], boite: boiteRsi });
  }
  return { retirer() { retirerGraphique(g); if (r) retirerGraphique({ c: r, boite: boiteRsi }); } };
}

/* Carte « Écart de taux » : paire en haut, écart (pb) en bas, synchronisés par dates. */
export async function graphiqueEcart(haut, bas, cloture, ecart, dec, mensuel) {
  const L = await chargerLWC();
  haut.innerHTML = ""; bas.innerHTML = "";
  if (!L || !haut.isConnected) { haut.innerHTML = '<div class="empty">Bibliothèque de graphiques indisponible.</div>'; return null; }
  const base = { autoSize: true, ...optionsTheme(), rightPriceScale: { borderVisible: false, minimumWidth: LARGEUR_AXE } };
  const a = L.createChart(haut, { ...base, localization: { locale: "fr-FR", dateFormat: "dd/MM/yy", priceFormatter: v => nf(v, dec) }, timeScale: { borderVisible: false, visible: false } });
  const b = L.createChart(bas, { ...base, localization: { locale: "fr-FR", dateFormat: "dd/MM/yy", priceFormatter: v => (v < 0 ? "−" : "") + nf(v, 0) + " pb" }, timeScale: { borderVisible: false } });
  const sa = a.addLineSeries({ color: css("--ink"), lineWidth: 2, priceLineVisible: false, title: "Clôture" });
  const pa = cloture.map(([d, v]) => ({ time: d.slice(0, 10), value: v }));
  sa.setData(pa);
  const col = css("--accent");
  const sb = b.addAreaSeries({ lineColor: col, topColor: alpha(col, "44"), bottomColor: alpha(col, "00"), lineWidth: 2, priceLineVisible: false, title: mensuel ? "Écart (mensuel)" : "Écart",
    lineType: mensuel ? 1 : 0, pointMarkersVisible: !!mensuel });
  const pb = ecart.map(([d, v]) => ({ time: d.slice(0, 10), value: v }));
  sb.setData(pb);
  sb.createPriceLine({ price: 0, color: css("--muted"), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
  let verrou = false;
  const relier = (x, y) => x.timeScale().subscribeVisibleTimeRangeChange(r => {
    if (!r || verrou) return; verrou = true; try { y.timeScale().setVisibleRange(r); } catch (e) { /* hors plage */ } finally { verrou = false; } });
  relier(a, b); relier(b, a);
  const va = new Map(pa.map(p => [p.time, p.value])), vb = new Map(pb.map(p => [p.time, p.value]));
  a.subscribeCrosshairMove(p => { const v = p?.time && vb.get(p.time); if (v == null) b.clearCrosshairPosition(); else b.setCrosshairPosition(v, p.time, sb); });
  b.subscribeCrosshairMove(p => { const v = p?.time && va.get(p.time); if (v == null) a.clearCrosshairPosition(); else a.setCrosshairPosition(v, p.time, sa); });
  a.timeScale().fitContent(); b.timeScale().fitContent();
  const ga = { c: a, objets: [], boite: haut }, gb = { c: b, objets: [], boite: bas };
  suivreGraphique(ga); suivreGraphique(gb);
  return { retirer() { retirerGraphique(ga); retirerGraphique(gb); } };
}
