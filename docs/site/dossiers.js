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

function graphiqueSerie(g) {
  const cadre = el("figure", "graphique");
  cadre.appendChild(el("figcaption", null, `${g.titre}${g.unite ? ` (${g.unite})` : ""}`));
  if (!g.courbes?.length) { cadre.appendChild(el("p", "indisponible", `Indisponible : ${g.raison || "pas de données"}.`)); return cadre; }
  const L = 320, H = 150, m = { g: 38, d: 8, h: 8, b: 20 };
  const tous = g.courbes.flatMap(c => c.points);
  const dates = tous.map(p => p[0]).sort();
  const t0 = Date.parse(dates[0]), t1 = Date.parse(dates[dates.length - 1]) || t0 + 1;
  const vals = tous.map(p => p[1]); let min = Math.min(...vals), max = Math.max(...vals);
  if (min === max) { min -= 1; max += 1; }
  const x = d => m.g + (Date.parse(d) - t0) / (t1 - t0 || 1) * (L - m.g - m.d);
  const y = v => m.h + (max - v) / (max - min) * (H - m.h - m.b);
  const svg = s("svg", { viewBox: `0 0 ${L} ${H}`, class: "graphique-svg", role: "img", "aria-label": g.titre });
  for (const v of [max, (max + min) / 2, min]) {
    svg.appendChild(s("line", { x1: m.g, x2: L - m.d, y1: y(v), y2: y(v), class: "grille" }));
    svg.appendChild(s("text", { x: m.g - 4, y: y(v) + 3, "text-anchor": "end", class: "axe" }, nombre(v, Math.abs(max - min) < 5 ? 2 : 0)));
  }
  if (min < 0 && max > 0) svg.appendChild(s("line", { x1: m.g, x2: L - m.d, y1: y(0), y2: y(0), class: "zero" }));
  svg.appendChild(s("text", { x: m.g, y: H - 5, class: "axe" }, dateCourte(dates[0]).slice(0, 5)));
  svg.appendChild(s("text", { x: L - m.d, y: H - 5, "text-anchor": "end", class: "axe" }, dateCourte(dates[dates.length - 1]).slice(0, 5)));
  g.courbes.forEach((c, i) => {
    const d = c.points.map((p, k) => `${k ? "L" : "M"}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" ");
    svg.appendChild(s("path", { d, fill: "none", stroke: COULEURS[i % COULEURS.length], "stroke-width": 1.8, "vector-effect": "non-scaling-stroke" }));
  });
  cadre.appendChild(svg);
  const legende = el("div", "legende");
  g.courbes.forEach((c, i) => {
    const derniere = c.points[c.points.length - 1];
    const item = el("span"); const pastil = el("i"); pastil.style.background = COULEURS[i % COULEURS.length];
    item.append(pastil, document.createTextNode(` ${c.nom} ${nombre(derniere[1], 2)}`));
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
                                fill: b.valeur < 0 ? "var(--negatif)" : "var(--accent)" }));
    svg.appendChild(s("text", { x: b.valeur < 0 ? x0 - 3 : x0 + largeur + 3, y: yb + 12, "text-anchor": b.valeur < 0 ? "end" : "start", class: "axe" },
                      nombre(b.valeur, Math.abs(b.valeur) < 10 ? 2 : 0)));
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

/* -------------------------------------------------------- contenus spécifiques */
function contenuTheme(e) {
  const bloc = [];
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
  bloc.push(el("h3", null, "Actualités budgétaires du jour"));
  if (!e.actualites?.length) bloc.push(el("p", "note", "Aucun titre budgétaire dans les flux du jour."));
  else {
    const ul = el("ul", "liste-actus");
    for (const a of e.actualites) {
      const li = el("li"); const lien = el("a", null, a.titre); lien.href = a.lien || "#"; lien.target = "_blank"; lien.rel = "noopener";
      li.append(lien, el("span", "source", ` — ${a.source}, ${dateCourte(a.date)}`)); ul.appendChild(li);
    }
    bloc.push(ul);
  }
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
  const parties = n === 1 ? contenuTheme(e) : n === 4 ? contenuFiscal(e) : n === 6 ? contenuGeopolitique(e) : n === 8 ? contenuOffre(e) : [];
  if (n === 2 || n === 3 || n === 7) parties.push(tableauDevises(e));
  if (n === 5) {
    if (e.regime_volatilite) parties.push(el("p", "note", `Volatilité implicite (VIX) : régime ${e.regime_volatilite}.`));
    parties.push(tableauInstruments(e.instruments));
  }
  for (const p of parties) bloc.appendChild(p);
  bloc.appendChild(graphiques(e));
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
