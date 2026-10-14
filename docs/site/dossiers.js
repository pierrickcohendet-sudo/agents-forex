/* Dossiers chiffrés des 8 engrenages (docs/data/dossiers.json) : calcul Python quotidien, sans LLM.
   Tableaux + deux graphiques SVG par engrenage (série 90 jours, comparaison en barres), sans bibliothèque. */
import { chargerJson, enErreur, el, dateCourte, dateHeure, ouvrirDetail, listeDefinitions, DRAPEAUX } from "./commun.js";

const nombre = (v, dec = 2) => v === null || v === undefined ? "—" :
  Number(v).toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: dec });
const signe = (v, dec = 1) => v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${nombre(v, dec)}`;
const estTaux = u => u === "%" || u === "pb";

function texteValeur(c, unite) {
  if (!c) return null;
  if ((c.valeur === null || c.valeur === undefined) && c.texte) return c.texte;
  if (c.valeur === null || c.valeur === undefined) return null;
  const u = c.unite || unite;
  if (u === "%") return `${nombre(c.valeur)} %`;
  if (u === "% PIB") return `${nombre(c.valeur, 1)} %`;
  if (u === "pb") return `${signe(c.valeur, 0)} pb`;
  if (u === "écarts") return signe(c.valeur, 2);
  if (u === "contrats") return signe(c.valeur, 0);
  if (u === "% annualisé") return `${nombre(c.valeur, 1)} %`;
  return nombre(c.valeur);
}
function texteVariation(c) {
  if (!c) return "";
  const taux = estTaux(c.unite), suf = taux ? " pb" : c.unite === "contrats" ? "" : " %";
  const m = [];
  if (c.var_1s !== null && c.var_1s !== undefined) m.push(`1 s ${signe(c.var_1s, taux || c.unite === "contrats" ? 0 : 2)}${suf}`);
  if (c.var_4s !== null && c.var_4s !== undefined) m.push(`4 s ${signe(c.var_4s, taux ? 0 : 2)}${suf}`);
  if (c.variation_an !== null && c.variation_an !== undefined) m.push(`1 an ${signe(c.variation_an, 1)} pt`);
  if (c.signal) m.push(c.signal);
  return m.join(" · ");
}

function pastille(p, prefixe = "p", titre = "percentile sur 5 ans") {
  const b = el("span", "pct");
  if (p === null || p === undefined) { b.textContent = `${prefixe} —`; return b; }
  b.textContent = `${prefixe}${p}`;
  b.title = `${p}e ${titre}`;
  const barre = el("span", "pct-barre"); const r = el("span"); r.style.width = `${p}%`; barre.appendChild(r);
  b.appendChild(barre);
  if (p >= 90 || p <= 10) b.classList.add("extreme");
  return b;
}
function pastilleCellule(c) {
  if (c?.percentile_52s !== undefined && c?.percentile_52s !== null) return pastille(c.percentile_52s, "p52 s ", "percentile sur 52 semaines");
  if (c?.percentile_90j !== undefined && c?.percentile_90j !== null) return pastille(c.percentile_90j, "p90 j ", "percentile sur 90 jours");
  if (c && (c.valeur !== null && c.valeur !== undefined) && !c.texte) return pastille(c.percentile_5a);
  return null;
}

function detailCellule(titre, c, unite) {
  if (!c) return;
  const vide = (c.valeur === null || c.valeur === undefined) && !c.texte;
  const paires = vide
    ? [["Valeur", "n/d"], ["Raison", c.raison || "—"], ["Source", c.source || undefined]]
    : [["Valeur", texteValeur(c, unite)], ["Variation 1 semaine", c.var_1s ?? undefined], ["Variation 4 semaines", c.var_4s ?? undefined],
       ["Variation sur un an", c.variation_an ?? undefined],
       ["Unité des variations", c.var_1s !== undefined && c.var_1s !== null ? (estTaux(c.unite) ? "points de base" : c.unite === "contrats" ? "contrats" : "%") : undefined],
       ["Percentile 5 ans", c.percentile_5a !== null && c.percentile_5a !== undefined ? `${c.percentile_5a} (sur ${c.n_5a} obs.)` : (c.raison_percentile ? `— (${c.raison_percentile})` : undefined)],
       ["Percentile 52 semaines", c.percentile_52s ?? undefined], ["Percentile 90 jours", c.percentile_90j ?? undefined],
       ["Écart à la moyenne 5 ans", c.ecart_moyenne_5a !== undefined && c.ecart_moyenne_5a !== null ? `${signe(c.ecart_moyenne_5a, 1)} M barils (${signe(c.ecart_moyenne_5a_pct, 1)} %)` : undefined],
       ["Date", c.date ? (String(c.date).length > 7 ? dateCourte(c.date) : c.date) : undefined], ["Source", c.source],
       ["Note", c.note || c.note_percentile || c.lecture || undefined],
       ["Tendance 3 mois", c.tendance_3m ?? (c.raison_tendance ? `— (${c.raison_tendance})` : undefined)],
       ["Alerte", c.alerte ?? undefined]];
  ouvrirDetail(titre, [listeDefinitions(paires)]);
}

function remplirCellule(td, c, unite, titre) {
  const v = texteValeur(c, unite);
  if (v === null) { td.appendChild(el("span", "nd", "n/d")); td.title = c?.raison || ""; }
  else {
    td.appendChild(el("div", "dv-valeur tabulaire", v));
    const varTxt = texteVariation(c);
    if (varTxt) td.appendChild(el("div", "dv-var tabulaire", varTxt));
    const p = pastilleCellule(c); if (p) td.appendChild(p);
    if (c.alerte) td.appendChild(el("div", "tag-alerte", c.alerte));
  }
  td.addEventListener("click", ev => { ev.stopPropagation(); detailCellule(titre, c, unite); });
}

function tableau(entetes, lignes) {
  const defile = el("div", "defile");
  const t = el("table", "dense dossier");
  const tete = el("tr"); for (const h of entetes) tete.appendChild(el("th", null, h));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody"); for (const tr of lignes) corps.appendChild(tr); t.appendChild(corps);
  defile.appendChild(t);
  return defile;
}

const CHALEUR_7 = {
  rsi: c => c?.valeur == null ? null : Math.max(-1, Math.min(1, (c.valeur - 50) / 25)),
  ecart_mm100: c => c?.valeur == null ? null : Math.max(-1, Math.min(1, c.valeur / 4)),
  ecart_mm200: c => c?.valeur == null ? null : Math.max(-1, Math.min(1, c.valeur / 6)),
  cot: c => c?.percentile_52s == null ? null : (c.percentile_52s - 50) / 50,
};
function colorer(td, intensite) {
  if (intensite === null || intensite === undefined) return;
  const force = Math.abs(intensite) * 45;
  td.style.background = `color-mix(in srgb, ${intensite >= 0 ? "var(--positif)" : "var(--negatif)"} ${force.toFixed(0)}%, var(--carte))`;
}

function tableauDevises(e) {
  const lignes = e.lignes.map(l => {
    const tr = el("tr");
    tr.appendChild(el("td", null, `${DRAPEAUX[l.devise] || ""} ${l.devise}`));
    for (const col of e.colonnes) {
      const c = l.cellules[col.id]; const td = el("td");
      if (col.id === "prochaine_reunion") td.textContent = c?.texte ? dateCourte(c.texte) : "—";
      else if (col.id === "publications") {
        td.className = "texte-long";
        const liste = c?.liste || [];
        if (!liste.length) td.appendChild(el("span", "nd", "n/d"));
        for (const p of liste) td.appendChild(el("div", p.surprise > 0 ? "pos" : p.surprise < 0 ? "neg" : "",
          `${p.indicateur} : ${p.reel} vs ${p.consensus} (${signe(p.surprise, 2)})`));
      } else remplirCellule(td, c, col.unite, `${l.devise} — ${col.libelle}`);
      if (e.numero === 7 && CHALEUR_7[col.id]) colorer(td, CHALEUR_7[col.id](c));
      tr.appendChild(td);
    }
    return tr;
  });
  return tableau(["Devise", ...e.colonnes.map(c => c.libelle)], lignes);
}

function tableauInstruments(instruments) {
  const lignes = instruments.map(i => {
    const c = i.cellule; const tr = el("tr");
    tr.appendChild(el("td", null, i.libelle));
    const td = el("td"); remplirCellule(td, c, i.unite_affichage === "%" ? "%" : c.unite, i.libelle); tr.appendChild(td);
    tr.appendChild(el("td", "tabulaire", c.date ? dateCourte(c.date) : "—"));
    tr.appendChild(el("td", "source-cellule", c.source || "—"));
    return tr;
  });
  return tableau(["Instrument", "Valeur, variations, percentile", "Date", "Source"], lignes);
}

/* ------------------------------------------------------------- graphiques SVG */
const SVG = "http://www.w3.org/2000/svg";
const COULEURS = ["var(--accent)", "var(--alerte)", "var(--positif)", "var(--negatif)", "var(--texte-2)"];
function s(tag, attrs, texte) {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  if (texte !== undefined) n.textContent = texte;
  return n;
}

/* Couleur FIXE par entité (une devise garde sa couleur d'un graphique à l'autre). */
const COULEUR_ENTITE = { USD: "var(--accent)", EUR: "#7C3AED", GBP: "#0F9488", JPY: "#C2410C", CHF: "#BE123C",
  CAD: "#DB2777", AUD: "#15803D", NZD: "#0284C7", CNY: "#A16207" };
const couleur = (nom, i) => COULEUR_ENTITE[nom] || COULEURS[i % COULEURS.length];

/* Étiquettes en bout de ligne : positions verticales écartées d'au moins `ecart` px, dans le cadre. */
function etiquettesSansChevauchement(ys, ecart, haut, bas) {
  const ordre = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  for (let k = 1; k < ordre.length; k++) if (ordre[k].y - ordre[k - 1].y < ecart) ordre[k].y = ordre[k - 1].y + ecart;
  const depasse = ordre.length ? ordre[ordre.length - 1].y - bas : 0;
  if (depasse > 0) ordre.forEach(o => { o.y = Math.max(haut, o.y - depasse); });
  const sortie = []; ordre.forEach(o => { sortie[o.i] = o.y; });
  return sortie;
}

function graphiqueSerie(g) {
  const cadre = el("figure", "graphique");
  cadre.appendChild(el("figcaption", null, `${g.titre}${g.unite ? ` (${g.unite})` : ""}`));
  if (!g.courbes?.length) { cadre.appendChild(el("p", "indisponible", `Indisponible : ${g.raison || "pas de données"}.`)); return cadre; }
  const L = 360, H = 170, m = { g: 38, d: 52, h: 10, b: 20 };
  const tous = g.courbes.flatMap(c => c.points);
  const dates = tous.map(p => p[0]).sort();
  const t0 = Date.parse(dates[0]), t1 = Date.parse(dates[dates.length - 1]) || t0 + 1;
  const vals = tous.map(p => p[1]); let min = Math.min(...vals), max = Math.max(...vals);
  if (min === max) { min -= 1; max += 1; }
  const marge = (max - min) * 0.06; min -= marge; max += marge;
  const x = d => m.g + (Date.parse(d) - t0) / (t1 - t0 || 1) * (L - m.g - m.d);
  const y = v => m.h + (max - v) / (max - min) * (H - m.h - m.b);
  const derniers = g.courbes.map(c => c.points[c.points.length - 1]);
  const svg = s("svg", { viewBox: `0 0 ${L} ${H}`, class: "graphique-svg", role: "img",
    "aria-label": `${g.titre}. Dernières valeurs : ${g.courbes.map((c, i) => `${c.nom} ${nombre(derniers[i][1], 2)}`).join(", ")}.` });
  for (const v of [max - marge, (max + min) / 2, min + marge]) {
    svg.appendChild(s("line", { x1: m.g, x2: L - m.d, y1: y(v), y2: y(v), class: "grille" }));
    svg.appendChild(s("text", { x: m.g - 4, y: y(v) + 3, "text-anchor": "end", class: "axe" }, nombre(v, Math.abs(max - min) < 5 ? 2 : 0)));
  }
  if (min < 0 && max > 0) svg.appendChild(s("line", { x1: m.g, x2: L - m.d, y1: y(0), y2: y(0), class: "zero" }));
  svg.appendChild(s("text", { x: m.g, y: H - 5, class: "axe" }, dateCourte(dates[0]).slice(0, 5)));
  svg.appendChild(s("text", { x: L - m.d, y: H - 5, "text-anchor": "end", class: "axe" }, dateCourte(dates[dates.length - 1]).slice(0, 5)));
  g.courbes.forEach((c, i) => {
    const d = c.points.map((p, k) => `${k ? "L" : "M"}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" ");
    svg.appendChild(s("path", { d, fill: "none", stroke: couleur(c.nom, i), "stroke-width": 1.8, "vector-effect": "non-scaling-stroke" }));
    svg.appendChild(s("circle", { cx: x(derniers[i][0]), cy: y(derniers[i][1]), r: 2.6, fill: couleur(c.nom, i) }));
  });
  const ys = etiquettesSansChevauchement(derniers.map(p => y(p[1])), 11, m.h + 4, H - m.b);
  g.courbes.forEach((c, i) => {
    const t = s("text", { x: L - m.d + 5, y: ys[i] + 3.5, class: "etiquette-fin" }, String(c.nom).slice(0, 9));
    t.setAttribute("fill", couleur(c.nom, i));
    svg.appendChild(t);
  });
  cadre.appendChild(svg);
  const legende = el("div", "legende");
  g.courbes.forEach((c, i) => {
    const item = el("span"); const pastil = el("i"); pastil.style.background = couleur(c.nom, i);
    item.append(pastil, document.createTextNode(` ${c.nom} ${nombre(derniers[i][1], 2)}`));
    legende.appendChild(item);
  });
  cadre.appendChild(legende);
  cadre.appendChild(el("p", "note", `Source : ${g.source}`));
  return cadre;
}

function graphiqueBarres(g) {
  const cadre = el("figure", "graphique");
  cadre.appendChild(el("figcaption", null, `${g.titre}${g.unite ? ` (${g.unite})` : ""}`));
  if (!g.barres?.length) { cadre.appendChild(el("p", "indisponible", `Indisponible : ${g.raison || "pas de données"}.`)); return cadre; }
  const hauteurBarre = 18, L = 320, gauche = 92, droite = 44;
  const H = g.barres.length * hauteurBarre + 6;
  const vals = g.barres.map(b => b.valeur);
  const min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  const x = v => gauche + (v - min) / ((max - min) || 1) * (L - gauche - droite);
  const svg = s("svg", { viewBox: `0 0 ${L} ${H}`, class: "graphique-svg", role: "img", "aria-label": g.titre });
  svg.appendChild(s("line", { x1: x(0), x2: x(0), y1: 0, y2: H, class: "zero" }));
  g.barres.forEach((b, i) => {
    const yb = 3 + i * hauteurBarre;
    svg.appendChild(s("text", { x: gauche - 6, y: yb + 12, "text-anchor": "end", class: "axe" }, `${DRAPEAUX[b.nom] ? DRAPEAUX[b.nom] + " " : ""}${b.nom}`.slice(0, 22)));
    const x0 = Math.min(x(0), x(b.valeur)), largeur = Math.max(1, Math.abs(x(b.valeur) - x(0)));
    svg.appendChild(s("rect", { x: x0, y: yb + 2, width: largeur, height: hauteurBarre - 6, rx: 2,
                                fill: b.valeur < 0 ? "var(--negatif)" : (COULEUR_ENTITE[b.nom] || "var(--accent)") }));
    svg.appendChild(s("text", { x: b.valeur < 0 ? x0 - 3 : x0 + largeur + 3, y: yb + 12, "text-anchor": b.valeur < 0 ? "end" : "start", class: "axe" },
                      `${b.valeur > 0 && vals.some(v => v < 0) ? "+" : ""}${nombre(b.valeur, Math.abs(b.valeur) < 10 ? 2 : 0)}`));
  });
  cadre.appendChild(svg);
  if (g.absentes?.length) cadre.appendChild(el("p", "note", `Sans donnée : ${g.absentes.join(", ")}.`));
  cadre.appendChild(el("p", "note", `Source : ${g.source}${g.note ? ` · ${g.note}` : ""}`));
  return cadre;
}

function graphiques(e) {
  const zone = el("div", "graphiques");
  for (const g of e.graphiques || []) zone.appendChild(g.type === "barres" ? graphiqueBarres(g) : graphiqueSerie(g));
  return zone;
}

/* ------------------------------------------------------------ tuiles (palier 2) */
function miniCourbe(courbe, libelle) {
  const pts = courbe?.points || [];
  if (pts.length < 2) return el("p", "tk-sans", courbe?.raison ? `Pas de courbe : ${courbe.raison}.` : "Pas de courbe.");
  const L = 120, H = 26, v = pts.map(p => p[1]);
  let mn = Math.min(...v), mx = Math.max(...v); if (mn === mx) { mn -= 1; mx += 1; }
  const yy = a => (H - 3 - (a - mn) / (mx - mn) * (H - 6)).toFixed(1);
  const svg = s("svg", { viewBox: `0 0 ${L} ${H}`, preserveAspectRatio: "none", class: "tk-courbe", role: "img",
    "aria-label": `${libelle} : ${courbe.periode}, de ${nombre(v[0], 2)} à ${nombre(v[v.length - 1], 2)}` });
  svg.appendChild(s("polyline", { points: pts.map((p, i) => `${(i / (pts.length - 1) * L).toFixed(1)},${yy(p[1])}`).join(" "),
    fill: "none", stroke: "var(--accent)", "stroke-width": 1.7, "vector-effect": "non-scaling-stroke" }));
  svg.appendChild(s("circle", { cx: L, cy: yy(v[v.length - 1]), r: 2.4, fill: "var(--accent)" }));
  return svg;
}

function tuileChiffre(t) {
  const c = el("div", "tk");
  const tete = el("div", "tk-tete");
  tete.appendChild(el("span", "tk-libelle", t.libelle));
  const info = el("button", "tk-info", "i"); info.type = "button";
  info.setAttribute("aria-label", `Source et date : ${t.libelle}`); info.setAttribute("aria-expanded", "false");
  tete.appendChild(info); c.appendChild(tete);
  const v = el("div", "tk-valeur tabulaire", t.texte ?? "n/d");
  if (t.texte === null || t.texte === undefined) v.classList.add("tk-nd");
  c.appendChild(v);
  if (t.raison) c.appendChild(el("div", "tk-raison", t.raison));
  if (t.variation) {
    const val = t.variation.valeur;
    c.appendChild(el("div", `tk-var tabulaire ${val > 0 ? "pos" : val < 0 ? "neg" : ""}`, t.variation.texte));
  }
  c.appendChild(miniCourbe(t.courbe, t.libelle));
  if (t.percentile_5a !== null && t.percentile_5a !== undefined) {
    const p = t.percentile_5a, extreme = p >= 85 || p <= 15;
    const rail = el("div", `tk-rail${extreme ? " extreme" : ""}`);
    rail.setAttribute("role", "img"); rail.setAttribute("aria-label", `percentile 5 ans : ${p}`);
    const r = el("i"); r.style.width = `${p}%`; rail.append(r, el("u"));
    c.appendChild(rail);
    const lig = el("div", "tk-pct tabulaire", `percentile 5 ans : ${p}`);
    if (extreme) lig.appendChild(el("span", "tk-extreme", "extrême"));
    c.appendChild(lig);
  } else if (t.percentile_autre) {
    const p = t.percentile_autre.valeur, extreme = p >= 90 || p <= 10;
    const rail = el("div", `tk-rail${extreme ? " extreme" : ""}`);
    rail.setAttribute("role", "img"); rail.setAttribute("aria-label", `percentile ${t.percentile_autre.libelle} : ${p}`);
    const r = el("i"); r.style.width = `${p}%`; rail.append(r, el("u"));
    c.appendChild(rail);
    const lig = el("div", "tk-pct tabulaire", `percentile ${t.percentile_autre.libelle} : ${p} (pas de série sur 5 ans)`);
    if (extreme) lig.appendChild(el("span", "tk-extreme", "extrême"));
    c.appendChild(lig);
  } else if (t.valeur !== null && t.valeur !== undefined) {
    c.appendChild(el("div", "tk-pct", `percentile n/d${t.raison_percentile ? ` — ${t.raison_percentile}` : ""}`));
  }
  const detail = el("div", "tk-detail");
  detail.hidden = true;
  detail.textContent = [t.source && `Source : ${t.source}`, t.date && `donnée du ${String(t.date).length > 7 ? dateCourte(t.date) : t.date}`,
    t.n_5a && `percentile sur ${t.n_5a} observations`, t.courbe?.periode && t.courbe.points?.length > 1 && `courbe : ${t.courbe.periode}`,
    t.lecture].filter(Boolean).join(" · ");
  c.appendChild(detail);
  if (t.date) c.appendChild(el("div", "tk-date", `au ${String(t.date).length > 7 ? dateCourte(t.date) : t.date}`));
  info.addEventListener("click", () => { detail.hidden = !detail.hidden; info.setAttribute("aria-expanded", String(!detail.hidden)); });
  return c;
}

function grilleTuiles(e) {
  if (e.tuiles_indisponibles) return el("p", "indisponible", `Chiffres clés indisponibles : ${e.tuiles_indisponibles}.`);
  if (!e.tuiles?.length) return null;
  const g = el("div", "tk-grille");
  g.setAttribute("aria-label", "Chiffres clés");
  for (const t of e.tuiles) g.appendChild(tuileChiffre(t));
  return g;
}

/* Carte de chaleur : couleur ET valeur signée (la couleur ne porte jamais seule le sens). */
function carteChaleur(mc) {
  if (!mc) return null;
  const bloc = el("div", "chaleur");
  bloc.appendChild(el("h3", null, `Matrice de corrélations, ${mc.seances} séances`));
  const lignes = mc.lignes.map(l => {
    const tr = el("tr");
    tr.appendChild(el("td", null, `${DRAPEAUX[l.devise] || ""} ${l.devise}`));
    l.valeurs.forEach((v, i) => {
      const td = el("td", "chaleur-case tabulaire");
      if (v === null || v === undefined) { td.appendChild(el("span", "nd", "n/d")); td.title = l.raison || "moins de 15 séances communes"; }
      else {
        td.textContent = `${v > 0 ? "+" : ""}${nombre(v, 2)}`;
        const pc = l.percentiles?.[i];
        if (pc !== null && pc !== undefined) td.appendChild(el("span", "chaleur-pct", `p${pc}`));
        const force = Math.min(1, Math.abs(v)) * 55;
        td.style.background = `color-mix(in srgb, ${v >= 0 ? "var(--positif)" : "var(--negatif)"} ${force.toFixed(0)}%, var(--carte))`;
        const avant = l.precedentes?.[i];
        td.title = `${l.devise} / ${mc.colonnes[i]} : ${nombre(v, 2)}${avant !== null && avant !== undefined ? ` (30 séances plus tôt : ${nombre(avant, 2)})` : ""}${pc !== null && pc !== undefined ? ` · percentile 5 ans : ${pc}` : ""}`;
      }
      td.setAttribute("data-label", mc.colonnes[i]);
      tr.appendChild(td);
    });
    return tr;
  });
  bloc.appendChild(tableau(["Devise", ...mc.colonnes], lignes));
  bloc.appendChild(el("p", "note", `${mc.lecture} Dernière séance : ${dateCourte(mc.derniere_seance)}. Source : ${mc.source}`));
  return bloc;
}

/* -------------------------------------------------------- contenus spécifiques */
const ACCORD = { oui: "pos", non: "neg" };
const CONV = { faible: "faible", moyen: "moyenne", eleve: "élevée" };
function tableauSuivi(s) {
  if (!s) return [];
  const bloc = [el("h3", null, `Qui suit le thème ? (${s.theme || "thème non déterminé"})`)];
  if (s.raison) { bloc.push(el("p", "indisponible", `Indisponible : ${s.raison}.`)); return bloc; }
  bloc.push(tableau(["Engrenage", "Direction", "Accord avec le thème", "Critère", "Conviction"], s.lignes.map(x => {
    const tr = el("tr");
    tr.appendChild(el("td", null, `${x.numero}. ${x.nom}`));
    tr.appendChild(el("td", null, x.direction));
    tr.appendChild(el("td", ACCORD[x.accord] || "", x.accord));
    tr.appendChild(el("td", null, x.critere || "—"));
    tr.appendChild(el("td", null, CONV[x.conviction] || "—"));
    return tr;
  })));
  if (s.regle) bloc.push(el("p", "note", s.regle));
  return bloc;
}

function contenuTheme(e) {
  const bloc = [...tableauSuivi(e.suivi_theme), el("h3", null, "Indicateurs du thème")];
  bloc.push(tableau(["Indicateur", "Valeur", "Détail", "Source"], e.indicateurs.map(i => {
    const tr = el("tr");
    tr.appendChild(el("td", null, i.libelle));
    tr.appendChild(el("td", "dv-valeur", i.texte));
    tr.appendChild(el("td", "texte-long", i.raison ? `${i.detail} — ${i.raison}` : i.detail));
    tr.appendChild(el("td", "source-cellule", i.source));
    return tr;
  })));
  bloc.push(el("h3", null, "Évolution du thème (rapports archivés)"));
  const regime = { risk_on: "Risk On", risk_off: "Risk Off", neutre: "Neutre" };
  bloc.push(tableau(["Rapport", "Régime", "Écart risque − refuge", "Score USD"], e.evolution.map(x => {
    const tr = el("tr");
    for (const v of [dateCourte(x.date), regime[x.biais] || "n/d", x.ecart === null ? "n/d" : `${signe(x.ecart, 1)} pts`, x.score_usd ?? "n/d"])
      tr.appendChild(el("td", "tabulaire", String(v)));
    return tr;
  })));
  return bloc;
}

function contenuFiscal(e) {
  const bloc = [tableauDevises(e)];
  bloc.push(el("h3", null, "Dossier budgétaire du jour"));
  const db = e.dossier_budgetaire || [];
  if (!db.length) bloc.push(el("p", "note", "Aucun titre budgétaire dans les flux du jour (recherche par mots-clés : budget, déficit, dette, adjudication, relance…)."));
  else bloc.push(tableau(["Pays", "Sujet", "Mécanisme", "Devises", "Source"], db.map(a => {
    const tr = el("tr");
    tr.appendChild(el("td", null, a.pays));
    const td = el("td", "texte-long"); const lien = el("a", null, a.sujet); lien.href = a.lien || "#"; lien.target = "_blank"; lien.rel = "noopener";
    td.appendChild(lien); tr.appendChild(td);
    tr.appendChild(el("td", "texte-long", a.mecanisme));
    tr.appendChild(el("td", null, (a.devises || []).join(", ") || "—"));
    tr.appendChild(el("td", "source-cellule", `${a.source || "—"}, ${dateCourte(a.date)}`));
    return tr;
  })));
  return bloc;
}

const CANAUX = { energie: "Énergie", commerce: "Commerce", sanctions: "Sanctions", refuge: "Refuge (conflits)", budget: "Politique intérieure" };
function contenuGeopolitique(e) {
  if (!e.evenements?.length) return [el("p", "indisponible", "Données insuffisantes aujourd'hui : aucun titre avec un canal de transmission identifiable.")];
  return [tableau(["Canal", "Événement", "Mécanisme", "Devises", "Source"], e.evenements.map(ev => {
    const tr = el("tr");
    tr.appendChild(el("td", null, CANAUX[ev.canal] || ev.canal));
    const td = el("td", "texte-long"); const lien = el("a", null, ev.titre); lien.href = ev.lien || "#"; lien.target = "_blank"; lien.rel = "noopener";
    td.appendChild(lien); tr.appendChild(td);
    tr.appendChild(el("td", "texte-long", ev.mecanisme));
    tr.appendChild(el("td", null, ev.devises.join(", ")));
    tr.appendChild(el("td", "source-cellule", `${ev.source}, ${dateCourte(ev.date)}`));
    return tr;
  }))];
}

function contenuOffre(e) {
  const bloc = [tableauInstruments(e.instruments)];
  bloc.push(el("h3", null, "Balances commerciales (dernière publication)"));
  bloc.push(tableau(["Devise", "Balance", "Consensus", "Date", "Source"], e.balances.map(b => {
    const tr = el("tr");
    tr.appendChild(el("td", null, `${DRAPEAUX[b.devise] || ""} ${b.devise}`));
    const td = el("td", "tabulaire"); if (b.valeur) td.textContent = b.valeur; else { td.appendChild(el("span", "nd", "n/d")); td.title = b.raison || ""; }
    tr.appendChild(td);
    tr.appendChild(el("td", "tabulaire", b.consensus || "—"));
    tr.appendChild(el("td", "tabulaire", b.date || "—"));
    tr.appendChild(el("td", "source-cellule", b.source || "—"));
    return tr;
  })));
  if (e.termes_echange?.raison) bloc.push(el("p", "note", `Termes de l'échange : n/d — ${e.termes_echange.raison}.`));
  return bloc;
}

function contenuEngrenage(n, e) {
  const bloc = el("div", "dossier-contenu");
  if (!e) { bloc.appendChild(el("p", "indisponible", "Dossier non calculé aujourd'hui.")); return bloc; }
  if (e.indisponible) { bloc.appendChild(el("p", "indisponible", `Indisponible : ${e.indisponible}.`)); return bloc; }
  const riche = Boolean(e.tuiles?.length || e.tuiles_indisponibles);   // tuiles, deux graphiques, tableau(x)
  const parties = n === 1 ? contenuTheme(e) : n === 4 ? contenuFiscal(e) : n === 6 ? contenuGeopolitique(e) : n === 8 ? contenuOffre(e) : [];
  if (riche) {
    const t = grilleTuiles(e); if (t) bloc.appendChild(t);
    if (n === 5 && e.regime_volatilite) bloc.appendChild(el("p", "note", `Volatilité implicite (VIX) : régime ${e.regime_volatilite}.`));
    bloc.appendChild(graphiques(e));
    const titres = { 2: "Grille des banques centrales", 3: "Données par devise", 4: "Finances publiques par pays", 5: "Marchés suivis",
                     6: "Événements retenus", 7: "Tableau technique par devise (carte de chaleur)", 8: "Matières premières suivies" };
    if (titres[n]) bloc.appendChild(el("h3", null, titres[n]));
  }
  if (n === 2 || n === 3 || n === 7) parties.push(tableauDevises(e));
  if (n === 5) parties.push(tableauInstruments(e.instruments));
  for (const p of parties) bloc.appendChild(p);
  if (n === 5) { const h = carteChaleur(e.matrice_chaleur); if (h) bloc.appendChild(h); }
  if (!riche) bloc.appendChild(graphiques(e));
  if (n === 5 && e.correlations) {
    const c = e.correlations;
    bloc.appendChild(el("p", "note", c.changements_de_signe?.length
      ? `Corrélations qui ont changé de signe : ${c.changements_de_signe.map(x => `${x.paire.join(" / ")} (${signe(x.avant, 2)} → ${signe(x.maintenant, 2)})`).join(" ; ")}.`
      : `Aucune corrélation marquée (≥ 0,3) n'a changé de signe sur 30 séances (jusqu'au ${dateCourte(c.derniere_seance)}).`));
  }
  const notes = el("ul", "notes");
  for (const t of e.notes || []) notes.appendChild(el("li", null, t));
  bloc.appendChild(notes);
  return bloc;
}

const NOMS = { 1: "Thème macro", 2: "Politique monétaire", 3: "Données économiques", 4: "Politique fiscale",
               5: "Interconnexions de marchés", 6: "Géopolitique", 7: "Price action et flux", 8: "Offre et demande" };

const COURTS = { 1: "Thème", 2: "Monétaire", 3: "Données", 4: "Fiscale", 5: "Marchés", 6: "Géopolitique", 7: "Flux", 8: "Offre" };

/* `options.actif` : engrenage ouvert au départ ; `options.surChoix(n)` : appelé à chaque changement.
   La carte expose `choisir(n)` pour être pilotée depuis la vue d'ensemble. */
export async function carteDossiers(options = {}) {
  const d = await chargerJson("data/dossiers.json");
  const c = el("section", "carte");
  c.id = "dossier-engrenage";
  c.choisir = () => {};
  c.appendChild(el("h2", null, "Dossier de l'engrenage"));
  if (enErreur(d)) { c.appendChild(el("p", "indisponible", `Indisponible : ${d?.__erreur || "dossiers.json absent"}.`)); return c; }
  c.appendChild(el("p", "sous-titre", `Calcul Python quotidien, sans LLM · généré ${dateHeure(d.genere_le)} · percentile = position de la valeur actuelle parmi les 5 dernières années (p90 : plus haut que 90 % du temps). Touchez une case pour le détail.`));
  const selecteur = el("div", "selecteur-engrenages");
  const zone = el("div");
  selecteur.setAttribute("role", "group");
  selecteur.setAttribute("aria-label", "Choisir l'engrenage");
  let actif = options.actif || 1;
  const boutons = [];
  for (let n = 1; n <= 8; n++) {
    const b = el("button", "bouton", `${n} ${COURTS[n]}`);
    b.type = "button"; b.title = NOMS[n];
    b.setAttribute("aria-label", `Engrenage ${n} : ${NOMS[n]}`);
    if (!d.engrenages?.[n] || d.engrenages[n].indisponible) b.classList.add("bientot");
    b.addEventListener("click", () => { actif = n; rendre(); options.surChoix?.(n); });
    boutons.push(b); selecteur.appendChild(b);
  }
  c.choisir = n => { actif = n; rendre(); };
  function rendre() {
    boutons.forEach((b, i) => b.setAttribute("aria-pressed", String(i + 1 === actif)));
    zone.replaceChildren(el("h3", "dossier-titre", `${actif}. ${NOMS[actif]}`), contenuEngrenage(actif, d.engrenages?.[actif]));
  }
  c.appendChild(selecteur); c.appendChild(zone);
  if ((d.erreurs_collecte || []).length) c.appendChild(el("p", "tag-alerte", `Séries indisponibles aujourd'hui : ${d.erreurs_collecte.join(" ; ")}`));
  rendre();
  return c;
}
