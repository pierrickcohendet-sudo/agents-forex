/* Espace Journal (lot V5, étape 7). Colonne gauche : fiche d'analyse de la paire (docs/data/paires.json, calcul Python)
   et graphiques. Colonne droite : mes notes, stockées dans le navigateur (IndexedDB), sans serveur ni clé ; export / import
   JSON (images intégrées) pour la sauvegarde et le transfert. Le biais personnel reste MA lecture, jamais un ordre. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, ouvrirDetail, certifier, pluriel } from "./commun.js";
import { UNITES_V2, STATUTS, migrer, compter, performance, bilanMensuel, grilleMois, peutToucher, ics, suggestions, finDeSemaine, nombreFr } from "./journal_logique.js";
import { graphiqueSerie, dessinerReperes } from "./dossiers.js";
import { seanceDe, avecLeTheme, resultatR } from "./journal_stats.js";

const SVG = "http://www.w3.org/2000/svg";
const UNITES = [["30min", "30 min"], ["4h", "4 h"], ["1j", "1 j"]];
const BIAIS = { haussier: "Haussier", neutre: "Neutre", baissier: "Baissier" };
// Checklist en 8 étapes (modèle du Rapport du jour) : cochée par moi, enregistrée avec la note
const CHECKLIST = [["biais", "Biais supérieur"], ["liquidite", "Liquidité"], ["structure", "Structure"], ["zone", "Zone d'intérêt"],
                   ["macro", "Confirmation macro"], ["declencheur", "Déclencheur M30"], ["invalidation", "Invalidation"], ["risque", "Risque"]];
const COURTS = { 1: "Thème", 2: "Monétaire", 3: "Données", 4: "Fiscale", 5: "Marchés", 6: "Géopolitique", 7: "Flux", 8: "Offre" };
const signe = (v, d = 2) => v == null ? "n/d" : `${v > 0 ? "+" : ""}${Number(v).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d })}`.replace("-", "−");
const nombre = (v, d = 4) => v == null ? "n/d" : Number(v).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
function s(tag, attrs, texte) { const n = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v); if (texte != null) n.textContent = texte; return n; }

/* ------------------------------------------------------------------ stockage (IndexedDB) */
const BASE = "fxdesk-journal";
let dbPromesse = null;
function ouvrirBase() {
  if (!dbPromesse) dbPromesse = new Promise((ok, ko) => {
    if (!("indexedDB" in window)) { ko(new Error("IndexedDB indisponible dans ce navigateur")); return; }
    let req;
    try { req = indexedDB.open(BASE, 1); } catch (e) { ko(e); return; }
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("notes")) db.createObjectStore("notes", { keyPath: "id" });
      if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta", { keyPath: "cle" });
    };
    req.onsuccess = () => ok(req.result);
    req.onerror = () => ko(req.error || new Error("ouverture refusée (navigation privée ?)"));
    req.onblocked = () => ko(new Error("base bloquée par un autre onglet"));
  });
  return dbPromesse;
}
async function tx(store, mode, action) {
  const db = await ouvrirBase();
  return new Promise((ok, ko) => {
    const t = db.transaction(store, mode);
    const r = action(t.objectStore(store));
    t.oncomplete = () => ok(r?.result);
    t.onerror = () => ko(t.error);
    t.onabort = () => ko(t.error || new Error("transaction annulée"));
  });
}
export const lireNotes = () => tx("notes", "readonly", st => st.getAll());
const ecrireNote = n => tx("notes", "readwrite", st => st.put(n));
const supprimerNote = id => tx("notes", "readwrite", st => st.delete(id));
const lireMeta = cle => tx("meta", "readonly", st => st.get(cle));
const ecrireMeta = (cle, valeur) => tx("meta", "readwrite", st => st.put({ cle, valeur }));
function messageErreur(e) {
  const n = String(e?.name || ""), m = String(e?.message || e);
  if (n === "QuotaExceededError" || /quota/i.test(m)) return "stockage du navigateur plein : exportez vos notes puis supprimez des images";
  if (/privée|private|refusée|security/i.test(m) || n === "SecurityError" || n === "InvalidStateError") return "stockage local indisponible (navigation privée ou données du site bloquées)";
  return m;
}

/* ------------------------------------------------------------------ images : compression dans le navigateur */
async function compresser(fichier) {
  const bitmap = await (window.createImageBitmap ? createImageBitmap(fichier) : new Promise((ok, ko) => {
    const img = new Image(); img.onload = () => ok(img); img.onerror = ko; img.src = URL.createObjectURL(fichier);
  }));
  const echelle = Math.min(1, 1600 / (bitmap.width || 1600));
  const c = document.createElement("canvas");
  c.width = Math.round(bitmap.width * echelle); c.height = Math.round(bitmap.height * echelle);
  c.getContext("2d").drawImage(bitmap, 0, 0, c.width, c.height);
  const essai = type => new Promise(ok => c.toBlob(b => ok(b), type, 0.8));
  let blob = await essai("image/webp");
  if (!blob || blob.type !== "image/webp") blob = await essai("image/jpeg");
  return { blob, largeur: c.width, hauteur: c.height };
}
const versDataURL = blob => new Promise((ok, ko) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = ko; r.readAsDataURL(blob); });
async function depuisDataURL(u) { return (await fetch(u)).blob(); }   // data: URI locale, aucune requête réseau

/* ------------------------------------------------------------------ texte libre : mise en forme simple, sans HTML */
function texteMisEnForme(texte) {
  const bloc = el("div", "jn-texte");
  let liste = null;
  for (const ligne of String(texte || "").split(/\r?\n/)) {
    const puce = /^\s*[-*]\s+(.*)$/.exec(ligne);
    const cible = puce ? (liste || (liste = el("ul"), bloc.appendChild(liste), liste)) : null;
    if (!puce) liste = null;
    const p = el(puce ? "li" : "p");
    for (const morceau of (puce ? puce[1] : ligne).split(/(\*\*[^*]+\*\*|\*[^*]+\*)/)) {
      if (/^\*\*[^*]+\*\*$/.test(morceau)) p.appendChild(el("strong", null, morceau.slice(2, -2)));
      else if (/^\*[^*]+\*$/.test(morceau)) p.appendChild(el("em", null, morceau.slice(1, -1)));
      else if (morceau) p.appendChild(document.createTextNode(morceau));
    }
    (cible || bloc).appendChild(p);
  }
  return bloc;
}

/* ------------------------------------------------------------------ fiche d'analyse (colonne gauche) */
function instantane(f) {
  const m = f.macro || {}, t = f.technique || {};
  return { date_rapport: f.date_rapport, theme: m.theme, direction_paire: m.direction_paire,
           decomposition: (m.decomposition || {}).texte, synthese: f.synthese_modele?.texte ? [f.synthese_modele.texte] : f.synthese_python,
           technique: { cours: t.cours, date: t.date, rsi14: t.rsi14, ecart_mm200: t.ecart_mm200, volatilite_30j: t.volatilite_30j },
           portage: { directeur_pb: m.portage?.directeur_pb, deux_ans_pb: m.portage?.deux_ans_pb }, etats: m.etats };
}

function chandeliers(serie, uniteLib, paire) {
  const b = serie?.bougies || [];
  const fig = el("figure", "graphique");
  fig.appendChild(el("figcaption", null, `${paire} · chandeliers ${uniteLib}`));
  if (b.length < 2) { fig.appendChild(el("p", "indisponible", `n/d : ${serie?.raison || "pas de bougies"}.`)); return fig; }
  const L = 520, H = 210, m = { g: 50, d: 12, h: 10, b: 20 };
  const lo = Math.min(...b.map(x => x[3])), hi = Math.max(...b.map(x => x[2])), marge = (hi - lo) * 0.06 || 1e-6;
  const t0 = Date.parse(b[0][0].replace(" ", "T") + "Z"), t1 = Date.parse(b[b.length - 1][0].replace(" ", "T") + "Z");
  const x = t => m.g + (t - t0) / ((t1 - t0) || 1) * (L - m.g - m.d), y = v => m.h + (hi + marge - v) / (hi - lo + 2 * marge) * (H - m.h - m.b);
  const svg = s("svg", { viewBox: `0 0 ${L} ${H}`, class: "graphique-svg jn-bougies", role: "img",
    "aria-label": `${paire}, ${b.length} bougies ${uniteLib}, dernière clôture ${nombre(b[b.length - 1][4])}` });
  const largeur = Math.max(1.2, (L - m.g - m.d) / b.length * 0.6);
  for (const v of [hi, (hi + lo) / 2, lo]) svg.appendChild(s("text", { x: m.g - 4, y: y(v) + 3, "text-anchor": "end", class: "axe" }, nombre(v)));
  for (const [t, o, h, l, c] of b) {
    const cx = x(Date.parse(t.replace(" ", "T") + "Z")), haussier = c >= o;
    const g = s("g", { class: `jn-bougie ${haussier ? "hausse" : "baisse"}` });
    g.appendChild(s("line", { x1: cx, x2: cx, y1: y(h), y2: y(l) }));
    g.appendChild(s("rect", { x: cx - largeur / 2, y: y(Math.max(o, c)), width: largeur, height: Math.max(0.8, Math.abs(y(o) - y(c))) }));
    g.appendChild(s("title", {}, `${t} UTC · O ${nombre(o)} · H ${nombre(h)} · B ${nombre(l)} · C ${nombre(c)}`));
    svg.appendChild(g);
  }
  const zone = el("div", "graphique-zone"); const bulle = el("div", "infobulle"); bulle.hidden = true;
  const iso = t => `${String(t).replace(" ", "T")}Z`;   // horodatage UTC sans ambiguïté pour tous les navigateurs
  const pts = b.map(x2 => [iso(x2[0]), x2[4]]);
  dessinerReperes(svg, (serie.annotations || []).map(r => ({ ...r, date: iso(r.date) })), { pts }, x, y,
                  [m.g, L - m.d, m.h, H - m.b], bulle, zone);
  zone.append(svg, bulle);
  fig.append(zone, el("p", "note", `Source : ${serie.source || "Twelve Data"} · heures UTC · repères : ▲ plus haut · ▼ plus bas · ● dernière clôture · survol pour l'OHLC`));
  return fig;
}

function graphiques(f, mes) {
  const c = el("div", "jn-graphiques");
  const estMienne = mes.includes(f.paire) && f.chandeliers && !f.chandeliers.raison;
  if (estMienne) {
    const nav = el("div", "sc-seg"); nav.setAttribute("role", "group"); nav.setAttribute("aria-label", "Unité de temps");
    const zone = el("div");
    let actif = "4h";
    const boutons = UNITES.map(([u, lib]) => { const b = el("button", null, lib); b.type = "button"; b.addEventListener("click", () => { actif = u; rendre(); }); nav.appendChild(b); return b; });
    function rendre() {
      boutons.forEach((b, i) => b.setAttribute("aria-pressed", String(UNITES[i][0] === actif)));
      zone.replaceChildren(chandeliers(f.chandeliers[actif], UNITES.find(u => u[0] === actif)[1], f.paire));
    }
    rendre();
    c.append(nav, zone);
  } else {
    const nav = el("div", "sc-seg"); nav.setAttribute("role", "group"); nav.setAttribute("aria-label", "Unité de temps");
    for (const [u, lib] of UNITES) {
      const b = el("button", null, lib); b.type = "button";
      if (u === "1j") b.setAttribute("aria-pressed", "true");
      else { b.disabled = true; b.title = mes.includes(f.paire) ? (f.chandeliers?.raison || "non collectés") : "réservé à Mes paires (config.yaml, journal.mes_paires)"; }
      nav.appendChild(b);
    }
    c.appendChild(nav);
    const g = f.graphique_1j || {};
    c.appendChild(graphiqueSerie({ titre: `${f.paire} · 1 jour (6 mois)`, unite: null, courbes: [{ nom: f.paire, points: g.points || [], couleur: "var(--accent)" }],
                                   source: g.source || "série unique 5 ans", annotations: g.annotations }));
    const a = el("a", null, `Bougies 30 min / 4 h / 1 jour, niveaux et RSI : page Paire (${f.paire})`); a.href = `#paire/${f.paire.replace("/", "-")}`;
    const n = el("p", "note"); n.appendChild(a); c.appendChild(n);
  }
  return c;
}

function tuile(libelle, valeur, detail, lien, cert) {
  const t = el("div", "jn-tuile");
  const b = el("b", "jn-t-val tabulaire", valeur);
  if (cert && valeur !== "n/d") certifier(b, { libelle, valeur, ...cert });
  t.append(el("span", "jn-t-lib", libelle), b);
  if (detail) t.appendChild(el("span", "jn-t-detail", detail));
  if (lien) { const a = el("a", "jn-t-lien", lien[0]); a.href = lien[1]; t.appendChild(a); }
  return t;
}

function tuiles(f) {
  const m = f.macro || {}, t = f.technique || {}, p = m.portage || {};
  const g = el("div", "jn-tuiles");
  const taux = x => x?.directeur == null ? "n/d" : `${x.borne === "<" ? "< " : ""}${String(x.directeur.toFixed(2)).replace(".", ",")} %`;
  g.appendChild(tuile("Écart de taux directeurs", p.directeur_pb == null ? "n/d" : `${signe(p.directeur_pb / 100, 2)} pt${p.borne ? " (borne)" : ""}`,
    `${f.base} ${taux(p.base)} · ${f.cotation} ${taux(p.cotation)}`));
  g.appendChild(tuile("Surprises macro 30 j", `${signe(m.surprises?.[f.base])} / ${signe(m.surprises?.[f.cotation])}`, `${f.base} / ${f.cotation}`));
  g.appendChild(tuile("RSI 14 · MM200", t.raison ? "n/d" : `${String(t.rsi14 ?? "n/d").replace(".", ",")} · ${t.ecart_mm200 == null ? "n/d" : `${signe(t.ecart_mm200)} %`}`,
    t.raison ? t.raison : "série journalière, écart à la moyenne 200 j", null, { source: t.source, date: t.date }));
  const evts = (m.evenements || []).slice(0, 2);
  g.appendChild(tuile("Prochains évènements", evts.length ? evts.map(e => `${e.devise} ${dateCourte(e.date_paris).slice(0, 5)}`).join(" · ") : "aucun",
    evts.length ? evts.map(e => e.evenement).join(" · ") : "rien de fort ou moyen au calendrier", ["voir l'Agenda", "#agenda"]));
  return g;
}

function contributions(f) {
  const dec = (f.macro || {}).decomposition || {};
  const box = el("div", "jn-contrib");
  box.appendChild(el("h3", null, `Contribution par engrenage (${f.base} − ${f.cotation})`));
  const g = el("div", "jn-contrib-grille");
  for (const x of dec.contributions || []) {
    const v = x.contribution;
    const c = el("div", `jn-c ${v >= 2 ? "p2" : v === 1 ? "p1" : v <= -2 ? "n2" : v === -1 ? "n1" : "zero"}${x.incomplete ? " incomplete" : ""}`);
    c.append(el("b", "tabulaire", v ? signe(v, 0) : "·"), el("span", null, String(x.engrenage)));
    c.title = `${x.engrenage} ${COURTS[x.engrenage]} : ${f.base} ${signe(x.base, 0)} (${x.etat_base}) − ${f.cotation} ${signe(x.cotation, 0)} (${x.etat_cotation})${x.incomplete ? " · incomplet" : ""}`;
    g.appendChild(c);
  }
  box.appendChild(g);
  if (!(dec.contributions || []).length) box.appendChild(el("p", "note", "Décomposition n/d."));
  return box;
}

function blocNiveaux(n) {
  const b = el("div", "jn-bloc");
  b.appendChild(el("h3", null, "Niveaux multi-unités"));
  if (n.raison) { b.appendChild(el("p", "note", `n/d : ${n.raison}.`)); return b; }
  const d = n.definitions || {}, ul = el("ul", "jn-niveaux");
  const ajouter = (texte, def) => { const li = el("li", null, texte); if (def) li.title = def; ul.appendChild(li); };
  const v = x => nombre(x, 5);
  if (n.veille) ajouter(`Veille (${dateCourte(n.veille.jour).slice(0, 5)}) : haut ${v(n.veille.haut)} · bas ${v(n.veille.bas)}`, d.veille);
  if (n.semaine_precedente) ajouter(`Semaine précédente : haut ${v(n.semaine_precedente.haut)} · bas ${v(n.semaine_precedente.bas)}`, d.semaine);
  for (const [s, x] of Object.entries(n.sessions || {})) if (x) ajouter(`Session ${s} : haut ${v(x.haut)} · bas ${v(x.bas)}${x.complete ? "" : " (en cours)"}`, d.sessions);
  for (const e of (n.structure_h4?.evenements || []).slice(-2)) ajouter(`${e.type} ${e.sens} (H4) le ${e.date.slice(8, 10)}/${e.date.slice(5, 7)} au-delà de ${v(e.niveau)}`, e.type === "BOS" ? d.bos : d.choch);
  for (const z of (n.fvg_h4 || []).slice(0, 2)) ajouter(`FVG H4 ${z.sens} ouverte : ${v(z.bas)} – ${v(z.haut)}`, d.fvg);
  for (const z of (n.fvg_m30 || []).slice(0, 2)) ajouter(`FVG M30 ${z.sens} ouverte : ${v(z.bas)} – ${v(z.haut)}`, d.fvg);
  for (const k of ["tendance_jour", "tendance_semaine"]) if (n[k]) ajouter(`Tendance ${n[k].unite} : ${n[k].lecture || n[k].raison}${n[k].pente_mm50 ? ` (MM50 ${n[k].pente_mm50})` : ""}`, d.tendance);
  b.append(ul, el("span", "source", n.mention || ""));
  return b;
}

function ficheAnalyse(f, mes) {
  const c = el("section", "carte jn-fiche");
  if (!f || f.raison) { c.appendChild(el("p", "indisponible", `Fiche n/d : ${f?.raison || "paire absente"}.`)); return c; }
  const m = f.macro || {}, t = f.technique || {};
  const dec0 = m.decomposition || {};
  const tete = el("div", "jn-fiche-tete");
  tete.appendChild(el("h2", null, `Analyse automatique · ${dateCourte(f.date_rapport)}`));
  if (dec0.solde != null) {
    const sol = el("span", `jn-solde ${dec0.solde > 0 ? "pos" : dec0.solde < 0 ? "neg" : ""}`, `Solde engrenages ${signe(dec0.solde, 0)} · ${dec0.lecture || ""}`);
    sol.title = dec0.texte || "";
    tete.appendChild(sol);
  }
  c.appendChild(tete);
  c.appendChild(el("p", "ck-petit", `Calcul Python à chaque run${mes.includes(f.paire) ? " · Mes paires" : ""}. Lecture de la paire, jamais un ordre.`));
  const syn = el("div", "jn-synthese");
  syn.appendChild(el("h3", null, "Synthèse en 3 lignes"));
  if (f.synthese_modele?.texte) {
    syn.appendChild(el("p", null, f.synthese_modele.texte));
    syn.appendChild(el("span", "source", `Formulé par ${f.synthese_modele.redige_par?.libelle || "le modèle"} à partir des chiffres Python`));
  } else {
    for (const l of f.synthese_python || []) syn.appendChild(el("p", null, l));
    syn.appendChild(el("span", "source", mes.includes(f.paire) ? "calcul Python (texte du modèle indisponible aujourd'hui)" : "calcul Python"));
  }
  c.appendChild(syn);
  c.appendChild(tuiles(f));
  c.appendChild(contributions(f));
  c.appendChild(graphiques(f, mes));
  const macro = el("div", "jn-bloc");
  macro.appendChild(el("h3", null, "Macro"));
  const dec = m.decomposition || {};
  macro.appendChild(el("p", null, `Thème : ${m.theme || "n/d"}${m.titre_impose ? " (titre imposé)" : ""} · ${m.direction_theme || ""}. ${dec.texte || "Décomposition n/d"}.`));
  if ((dec.contributions || []).length) {
    const ul = el("ul", "jn-dec");
    for (const x of dec.contributions) {
      const li = el("li", x.incomplete ? "incomplete" : "");
      li.append(el("span", null, `${x.engrenage} ${COURTS[x.engrenage]}`), el("b", `tabulaire ${x.contribution > 0 ? "pos" : x.contribution < 0 ? "neg" : ""}`, signe(x.contribution, 0)));
      ul.appendChild(li);
    }
    macro.appendChild(ul);
  }
  const p = m.portage || {};
  macro.appendChild(el("p", null, `États : ${f.base} ${m.etats?.[f.base] ?? "n/d"} · ${f.cotation} ${m.etats?.[f.cotation] ?? "n/d"}. `
    + `Portage : taux directeurs ${p.directeur_pb == null ? "n/d" : `${signe(p.directeur_pb, 0)} pb`}${p.borne ? " (borne)" : ""}, 2 ans ${p.deux_ans_pb == null ? `n/d (${p.raison_2a})` : `${signe(p.deux_ans_pb, 0)} pb`}. `
    + `Surprises 30 j : ${f.base} ${signe(m.surprises?.[f.base])} · ${f.cotation} ${signe(m.surprises?.[f.cotation])}.`));
  if ((m.evenements || []).length) macro.appendChild(el("p", "ck-petit", "Prochains évènements : " + m.evenements.map(e => `${dateCourte(e.date_paris).slice(0, 5)} ${e.heure_paris} ${e.devise} ${e.evenement} (${e.impact})`).join(" · ")));
  c.appendChild(macro);
  const tech = el("div", "jn-bloc");
  tech.appendChild(el("h3", null, "Technique"));
  tech.appendChild(t.raison ? el("p", "indisponible", `n/d : ${t.raison}.`) :
    el("p", null, `Cours ${nombre(t.cours)} (${dateCourte(t.date)}) · RSI 14 ${String(t.rsi14).replace(".", ",")} · écart MM50 ${signe(t.ecart_mm50)} % · MM200 ${t.ecart_mm200 == null ? `n/d (${t.raison_mm200})` : `${signe(t.ecart_mm200)} %`} · `
      + `plus haut 20 j ${nombre(t.plus_haut_20j)} · plus bas 20 j ${nombre(t.plus_bas_20j)} · volatilité 30 j ${String(t.volatilite_30j).replace(".", ",")} %.`));
  if (t.source) tech.appendChild(el("span", "source", `Source : ${t.source}`));
  c.appendChild(tech);
  if (f.niveaux) c.appendChild(blocNiveaux(f.niveaux));
  const cons = el("div", "jn-bloc");
  cons.appendChild(el("h3", null, "Conséquences (tableau des conséquences)"));
  cons.appendChild((f.consequences || []).length ? el("p", null, f.consequences.map(x => `${x.engrenage} ${COURTS[x.engrenage]} : ${f.base} ${x.base}, ${f.cotation} ${x.cotation}`).join(" · ")) : el("p", "note", "Aucune ligne pour cette paire."));
  c.appendChild(cons);
  return c;
}

/* ------------------------------------------------------------------ suivi : variation depuis la note */
function suivi(note, paires) {
  const pts = paires?.fiches?.[note.paire]?.graphique_1j?.points || [];
  const jour = note.cree_le.slice(0, 10);
  if ((Date.now() - Date.parse(note.cree_le)) < 864e5 || pts.length < 2) return null;
  const prix = d => { let v = null; for (const p of pts) { if (p[0] <= d) v = p; else break; } return v; };
  const p0 = prix(jour);
  if (!p0) return { raison: "note antérieure aux 6 mois de cours publiés" };
  const plus = j => new Date(Date.parse(`${jour}T12:00:00Z`) + j * 864e5).toISOString().slice(0, 10);
  const dernier = pts[pts.length - 1][0];
  const v = j => { const d = plus(j); if (d > dernier) return null; const p = prix(d); return p ? (p[1] / p0[1] - 1) * 100 : null; };
  return { depuis: p0, j1: v(1), s1: v(7), m1: v(30) };
}

/* ------------------------------------------------------------------ Markdown pour Notion */
function markdown(n0) {
  const n = migrer(n0), i = n.instantane || {}, c = compter(n.elements);
  const lignes = [`## ${n.paire} — ${dateHeure(n.date_heure || n.cree_le)}`, "",
    `**Statut :** ${STATUTS[n.resultat?.statut || "analyse"]}` + (n.resultat?.statut === "cloturee" ? ` · ${n.resultat.pnl_eur ?? "n/d"} € · ${n.resultat.pips ?? "n/d"} pips · ${n.resultat.r ?? "n/d"} R` : ""),
    `**Unités de temps :** ${[...new Set((n.captures || []).flatMap(x => x.unites || []))].join(", ") || "—"}`,
    `**Confluence (ma lecture, pas un ordre) :** ${c.pour} pour · ${c.contre} contre`, "", n.contexte || "", "",
    ...(n.elements || []).filter(x => x.avis).map(x => `- ${x.avis === "pour" ? "Pour" : "Contre"} · ${x.devise} : ${x.texte} (${x.source})`), "",
    `**Instantané des données (rapport du ${i.date_rapport || "n/d"}) :**`,
    `- Thème : ${i.theme || "n/d"}`, `- ${i.decomposition || "Décomposition n/d"}`,
    `- Technique : cours ${i.technique?.cours ?? "n/d"}, RSI ${i.technique?.rsi14 ?? "n/d"}, écart MM200 ${i.technique?.ecart_mm200 ?? "n/d"} %`,
    ...((i.synthese || []).map(l => `- ${l}`)), ""];
  if ((n.captures || []).length) lignes.push(`_Captures à joindre à la main : ${n.captures.length} (${n.captures.map(x => (x.unites || []).join("+") || "sans unité").join(", ")})._`);
  lignes.push("_Aide à la décision, pas un conseil._");
  return lignes.join("\n");
}
async function copier(texte, bouton) {
  try { await navigator.clipboard.writeText(texte); bouton.textContent = "Copié ✓"; }
  catch (e) {
    const zone = el("textarea", "jn-copie"); zone.value = texte; bouton.after(zone); zone.select();
    bouton.textContent = "Sélectionné : Ctrl+C";
  }
  setTimeout(() => { bouton.textContent = "Copier pour Notion"; }, 2500);
}

/* ------------------------------------------------------------------ page */
export async function pageJournal() {
  const paires = await chargerJson("data/paires.json");
  const tete = el("section", "carte");
  tete.appendChild(el("h2", null, "Journal"));
  tete.appendChild(el("p", "sous-titre", "À gauche, la fiche d'analyse de la paire (calcul Python à chaque run). À droite, mes entrées : elles restent dans ce navigateur (IndexedDB) ; l'export sert de sauvegarde et de transfert, captures comprises. Ma lecture, jamais un ordre."));
  if (enErreur(paires)) return [tete, indisponible("Fiches des paires", paires?.__erreur || "paires.json absent (prochain run)")];
  const mes = paires.mes_paires || [];
  const grille = el("div", "jn-grille");
  const gauche = el("div", "jn-col");
  const droite = el("div", "jn-col");
  grille.append(gauche, droite);

  // ------------- sélecteur de paire et fiche
  const choix = el("select", "ot-select jn-paire"); choix.setAttribute("aria-label", "Choisir une paire");
  const g1 = Object.assign(document.createElement("optgroup"), { label: "Mes paires" });
  for (const p of mes) g1.appendChild(new Option(p, p));
  const g2 = Object.assign(document.createElement("optgroup"), { label: "Toutes les paires (36)" });
  for (const p of paires.paires || []) if (!mes.includes(p)) g2.appendChild(new Option(p, p));
  choix.append(g1, g2);
  let paireActive = (() => { try { return localStorage.getItem("fxdesk-journal-paire") || mes[0]; } catch (e) { return mes[0]; } })();
  if (!(paires.fiches || {})[paireActive]) paireActive = mes[0] || (paires.paires || [])[0];
  choix.value = paireActive;
  const zoneFiche = el("div");
  const rendreFiche = () => { zoneFiche.replaceChildren(ficheAnalyse(paires.fiches[paireActive], mes)); };
  choix.addEventListener("change", () => { paireActive = choix.value; try { localStorage.setItem("fxdesk-journal-paire", paireActive); } catch (e) { /* préférence seulement */ } rendreFiche(); });
  const puces = el("div", "jn-puces"); puces.setAttribute("role", "group"); puces.setAttribute("aria-label", "Mes paires");
  const boutonsPuces = mes.map(p => {
    const b = el("button", "jn-puce", p); b.type = "button";
    b.addEventListener("click", () => { choix.value = p; choix.dispatchEvent(new Event("change")); });
    puces.appendChild(b); return b;
  });
  const marquerPuce = () => boutonsPuces.forEach(b => b.setAttribute("aria-pressed", String(b.textContent === paireActive)));
  choix.addEventListener("change", marquerPuce);
  const barre = el("div", "jn-barre"); barre.append(puces, choix);
  marquerPuce();
  gauche.append(barre, zoneFiche);

  // ------------- Journal V2 (lot V6) : nouvelle entrée en 7 étapes, calendrier des résultats, liste
  const [profil, rapportJour, agenda] = await Promise.all([chargerJson("data/profil_devises.json"), chargerJson("data/rapport_jour.json"), chargerJson("data/agenda.json")]);
  const donneesJour = { profil: enErreur(profil) ? null : profil, rapport: enErreur(rapportJour) ? null : rapportJour, agenda: enErreur(agenda) ? null : agenda };
  const vues = el("div", "sc-seg jn-vues"); vues.setAttribute("role", "group"); vues.setAttribute("aria-label", "Vue du journal");
  const form = el("form", "carte jn-form");
  const calendrier = el("section", "carte jn-calendrier"); calendrier.hidden = true;
  const boutonsVue = [["saisie", "Nouvelle entrée"], ["calendrier", "Calendrier"]].map(([v, lib]) => {
    const b = el("button", null, lib); b.type = "button";
    b.addEventListener("click", () => montrer(v));
    vues.appendChild(b); return [v, b];
  });
  function montrer(v) {
    form.hidden = v !== "saisie"; calendrier.hidden = v !== "calendrier";
    boutonsVue.forEach(([x, b]) => b.setAttribute("aria-pressed", String(x === v)));
    if (v === "calendrier") rendreCalendrier();
  }

  form.appendChild(el("h2", null, "Nouvelle entrée"));
  const erreur = el("p", "indisponible jn-erreur"); erreur.hidden = true;
  const etape = (n, titre, aide) => { const s = el("fieldset", "jn-etape"); const l = el("legend", null, `${n} · ${titre}`); s.appendChild(l); if (aide) s.appendChild(el("p", "note", aide)); return s; };

  // 1. Paire
  const e1 = etape(1, "Paire");
  const champPaire = el("select", "ot-select"); champPaire.setAttribute("aria-label", "Paire de l'entrée");
  for (const p of paires.paires || []) champPaire.appendChild(new Option(p, p));
  const pucesForm = el("div", "jn-puces"); pucesForm.setAttribute("role", "group"); pucesForm.setAttribute("aria-label", "Mes paires");
  const autre = el("button", "jn-puce", "Autre…"); autre.type = "button";
  const pucesP = mes.map(p => { const b = el("button", "jn-puce", p); b.type = "button"; b.addEventListener("click", () => choisirPaire(p)); pucesForm.appendChild(b); return b; });
  pucesForm.appendChild(autre);
  champPaire.hidden = true;
  autre.addEventListener("click", () => { champPaire.hidden = false; champPaire.focus(); autre.setAttribute("aria-pressed", "true"); pucesP.forEach(b => b.setAttribute("aria-pressed", "false")); });
  champPaire.addEventListener("change", () => choisirPaire(champPaire.value, true));
  const lSens = el("label", "jn-champ"); const champSens = el("select"); champSens.setAttribute("aria-label", "Sens envisagé");
  for (const v of ["Pas encore décidé", "Achat", "Vente"]) champSens.appendChild(new Option(v, v));
  lSens.append(el("span", null, "Sens envisagé"), champSens);
  e1.append(pucesForm, champPaire, lSens);

  // 2. Date et heure
  const e2 = etape(2, "Date et heure");
  const champDate = el("input"); champDate.type = "datetime-local"; champDate.setAttribute("aria-label", "Date et heure de l'entrée");
  const maintenantLocal = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
  champDate.value = maintenantLocal();
  e2.appendChild(champDate);

  // 3. Captures et unités de temps
  const e3 = etape(3, "Captures et unités de temps", "Coller (Ctrl+V), glisser ou choisir · une ou plusieurs unités par capture · compression à 1 600 px, rien n'est envoyé.");
  const depot = el("div", "jn-depot"); depot.tabIndex = 0;
  depot.appendChild(el("p", "jn-depot-titre", "+ Ajouter une capture"));
  const fichier = el("input"); fichier.type = "file"; fichier.accept = "image/*"; fichier.multiple = true; fichier.setAttribute("aria-label", "Ajouter des captures");
  const apercus = el("div", "jn-apercus");
  depot.appendChild(fichier);
  e3.append(apercus, depot);

  // 4. Contexte
  const e4 = etape(4, "Contexte");
  const texte = el("textarea", "jn-zone"); texte.rows = 4; texte.placeholder = "Range, niveaux, ce que j'attends… (**gras**, *italique*, lignes « - » pour une liste)";
  texte.setAttribute("aria-label", "Contexte");
  e4.appendChild(texte);

  // 5. Éléments confluents
  const e5 = etape(5, "Éléments confluents", "Proposés par le site à partir des données du jour · je marque ce qui va dans le sens de mon scénario, ou contre.");
  const colonnes = el("div", "jn-colonnes");
  const compteurC = el("p", "jn-compteur");
  e5.append(colonnes, compteurC, el("p", "note", "C'est ma lecture, enregistrée avec l'instantané des données du jour."));
  let elements = [];
  function rendreElements() {
    const [base, cot] = champPaire.value.split("/");
    colonnes.replaceChildren(...[[base, "devise de base"], [cot, "devise de cotation"]].map(([dev, role]) => {
      const col = el("div", "jn-colonne");
      const t = el("div", "jn-col-tete"); t.append(el("b", null, dev), el("span", "note", role)); col.appendChild(t);
      for (const it of elements.filter(x => x.devise === dev)) {
        const ligne = el("div", "jn-element");
        const txt = el("div", "jn-el-texte"); txt.append(el("span", null, it.texte), el("span", "note", it.perso ? "mon élément" : it.source));
        const g = el("div", "jn-avis"); g.setAttribute("role", "group"); g.setAttribute("aria-label", "Mon avis sur cet élément");
        for (const [v, lib] of [["pour", "Pour"], ["contre", "Contre"]]) {
          const b = el("button", `jn-avis-${v}`, lib); b.type = "button"; b.setAttribute("aria-pressed", String(it.avis === v));
          b.addEventListener("click", () => { it.avis = it.avis === v ? null : v; rendreElements(); rendreAgenda(); });
          g.appendChild(b);
        }
        ligne.append(txt, g); col.appendChild(ligne);
      }
      const ajout = el("div", "jn-ajout");
      const champ = el("input"); champ.type = "text"; champ.placeholder = "+ Ajouter mon propre élément"; champ.setAttribute("aria-label", `Ajouter un élément ${dev}`);
      const ok = el("button", "bouton", "Ajouter"); ok.type = "button";
      const ajouter = () => { const v = champ.value.trim(); if (!v) return; elements.push({ id: crypto.randomUUID(), devise: dev, texte: v, source: "mon élément", perso: true, avis: "pour", mots: v.split(/\s+/).filter(m => m.length > 3) }); rendreElements(); rendreAgenda(); };
      ok.addEventListener("click", ajouter); champ.addEventListener("keydown", ev => { if (ev.key === "Enter") { ev.preventDefault(); ajouter(); } });
      ajout.append(champ, ok); col.appendChild(ajout);
      return col;
    }));
    const c = compter(elements);
    compteurC.textContent = `Confluence de mon scénario : ${c.pour} pour · ${c.contre} contre`;
  }

  // 6. Ce qui peut toucher mon scénario
  const e6 = etape(6, "Ce qui peut toucher mon scénario");
  const horizonLigne = el("label", "jn-horizon"); const champHorizon = el("input"); champHorizon.type = "date";
  champHorizon.value = finDeSemaine().slice(0, 10);
  horizonLigne.append(document.createTextNode("Jusqu'au "), champHorizon);
  const listeAgenda = el("ul", "jn-agenda");
  const actionsAgenda = el("div", "jn-actions");
  const boutonIcs = el("button", "bouton", "Ajouter à mon agenda (.ics)"); boutonIcs.type = "button";
  const boutonNotif = el("button", "bouton", "Me prévenir 30 min avant"); boutonNotif.type = "button";
  const etatNotif = el("p", "note", "Rappel du navigateur 30 min avant chaque évènement marqué : il ne fonctionne que si le site reste ouvert. Le fichier .ics, lui, reste dans votre agenda.");
  actionsAgenda.append(boutonIcs, boutonNotif);
  e6.append(horizonLigne, listeAgenda, actionsAgenda, etatNotif);
  let evenementsTouchent = [];
  function rendreAgenda() {
    const horizon = `${champHorizon.value || finDeSemaine().slice(0, 10)}T22:00:00Z`;
    const evts = donneesJour.agenda ? peutToucher(donneesJour.agenda, champPaire.value, elements, horizon) : [];
    evenementsTouchent = evts.filter(x => x.touche);
    listeAgenda.replaceChildren(...(evts.length ? evts.map(x => {
      const li = el("li", "jn-agenda-ligne");
      li.append(el("span", "tabulaire", `${dateCourte(x.date_paris).slice(0, 5)} ${x.heure_paris || ""}`), el("b", null, x.devise), el("span", null, x.evenement),
                el("span", `jn-badge${x.touche ? " fort" : ""}`, x.touche ? "Peut toucher mon scénario" : "À surveiller"));
      if (x.raison) li.title = `Raison : ${x.raison}`;
      return li;
    }) : [el("li", "note", donneesJour.agenda ? "Aucun évènement de ces deux devises d'ici l'horizon." : "Agenda indisponible (prochain run).")]));
    boutonIcs.disabled = !evenementsTouchent.length;
  }
  champHorizon.addEventListener("change", rendreAgenda);
  boutonIcs.addEventListener("click", () => {
    const blob = new Blob([ics(evenementsTouchent, champPaire.value)], { type: "text/calendar;charset=utf-8" });
    const a = el("a"); a.href = URL.createObjectURL(blob); a.download = `fxdesk-${champPaire.value.replace("/", "")}-${new Date().toISOString().slice(0, 10)}.ics`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  });
  boutonNotif.addEventListener("click", async () => {
    if (!("Notification" in window)) { etatNotif.textContent = "Notifications indisponibles dans ce navigateur : utilisez le fichier .ics."; return; }
    const ok = Notification.permission === "granted" || (await Notification.requestPermission()) === "granted";
    if (!ok) { etatNotif.textContent = "Notifications refusées : utilisez le fichier .ics."; return; }
    let n = 0;
    for (const x of evenementsTouchent) {
      const delai = Date.parse(x.iso_utc) - 30 * 60000 - Date.now();
      if (delai > 0 && delai < 2 ** 31 - 1) { n++; setTimeout(() => new Notification(`${x.devise} ${x.evenement} dans 30 min`, { body: `Peut toucher mon scénario ${champPaire.value}.` }), delai); }
    }
    etatNotif.textContent = `${pluriel(n, "rappel programmé", "rappels programmés")}, tant que cette page reste ouverte.`;
  });

  // Plan et risque (lot V8)
  const ePlan = etape(7, "Plan et risque", "Le risque prévu (€) permet de convertir un résultat en € en R quand R n'est pas saisi.");
  const champP = (lib, ph) => { const l = el("label", "jn-champ"); const i = el("input"); i.type = "text"; i.inputMode = "decimal"; i.placeholder = ph; l.append(el("span", null, lib), i); return [l, i]; };
  const [lEntree, champEntree] = champP("Entrée", "niveau d'entrée");
  const [lInval, champInval] = champP("Invalidation", "niveau qui annule le scénario");
  const [lRisque, champRisque] = champP("Risque prévu (€)", "ex. 100");
  const grilleP = el("div", "jn-resultat"); grilleP.append(lEntree, lInval, lRisque); ePlan.appendChild(grilleP);

  // 7. Résultat
  const e7 = etape(8, "Résultat (à compléter à la clôture)");
  const grilleR = el("div", "jn-resultat");
  const statut = el("select"); statut.setAttribute("aria-label", "Statut");
  for (const [v, lib] of Object.entries(STATUTS)) statut.appendChild(new Option(lib, v));
  const champ = (lib, ph) => { const l = el("label", "jn-champ"); const i = el("input"); i.type = "text"; i.inputMode = "decimal"; i.placeholder = ph; l.append(el("span", null, lib), i); return [l, i]; };
  const [lPnl, pnl] = champ("Profit / perte (€)", "ex. +120 ou −45");
  const [lPips, pips] = champ("Pips", "ex. +35");
  const [lR, r] = champ("R", "ex. 1,8");
  const lStatut = el("label", "jn-champ"); lStatut.append(el("span", null, "Statut"), statut);
  grilleR.append(lStatut, lPnl, lPips, lR);
  e7.appendChild(grilleR);

  const enregistrer = el("button", "bouton jn-principal", "Enregistrer l'entrée"); enregistrer.type = "submit";
  const annuler = el("button", "bouton", "Annuler la modification"); annuler.type = "button"; annuler.hidden = true;
  const actions = el("div", "jn-actions"); actions.append(enregistrer, annuler);
  // Lot V8 : étapes du panneau latéral (paire et date, contexte, captures, confluences, événements, plan et risque, bilan)
  [[e1, 1], [e2, 1], [e4, 2], [e3, 3], [e5, 4], [e6, 5], [ePlan, 6], [e7, 7]].forEach(([f, k]) => { f.dataset.pas = k; });
  form.addEventListener("jn-paire", ev => { if (ev.detail) { champPaire.value = ev.detail; choisirPaire(ev.detail, true); } });
  form.append(erreur, e1, e2, e4, e3, e5, e6, ePlan, e7, actions, el("p", "note", "L'entrée garde un instantané des données du jour (fiche de la paire, états des devises)."));

  let captures = [];       // {id, unites[], blob, largeur, hauteur}
  let enEdition = null;
  const afficherErreur = m => { erreur.textContent = `Journal : ${m}.`; erreur.hidden = !m; };
  function choisirPaire(p, depuisListe) {
    champPaire.value = p;
    pucesP.forEach(b => b.setAttribute("aria-pressed", String(b.textContent === p)));
    if (!depuisListe) { champPaire.hidden = true; autre.setAttribute("aria-pressed", "false"); }
    const [b, c] = p.split("/");
    const perso = elements.filter(x => x.perso && [b, c].includes(x.devise));
    elements = [...suggestions(b, { ...donneesJour, paire: p }), ...suggestions(c, { ...donneesJour, paire: p }), ...perso];
    rendreElements(); rendreAgenda();
  }
  function rendreApercus() {
    apercus.replaceChildren(...captures.map((im, k) => {
      const b = el("div", "jn-apercu");
      const img = el("img"); img.alt = `Capture ${k + 1}`; img.src = URL.createObjectURL(im.blob);
      const ut = el("div", "jn-ut"); ut.setAttribute("role", "group"); ut.setAttribute("aria-label", `Unités de temps de la capture ${k + 1}`);
      for (const u of UNITES_V2) {
        const bt = el("button", "jn-ut-b", u); bt.type = "button"; bt.setAttribute("aria-pressed", String(im.unites.includes(u)));
        bt.addEventListener("click", () => { im.unites = im.unites.includes(u) ? im.unites.filter(x => x !== u) : [...im.unites, u]; bt.setAttribute("aria-pressed", String(im.unites.includes(u))); });
        ut.appendChild(bt);
      }
      const x = el("button", "bouton", "Retirer"); x.type = "button"; x.addEventListener("click", () => { captures.splice(k, 1); rendreApercus(); });
      b.append(img, ut, x);
      return b;
    }));
  }
  async function ajouterFichiers(liste) {
    for (const f of liste) {
      if (!f.type.startsWith("image/")) continue;
      try { const c = await compresser(f); captures.push({ id: crypto.randomUUID(), unites: [], ...c }); }
      catch (e) { afficherErreur(`image illisible (${e.message || e})`); }
    }
    rendreApercus();
  }
  fichier.addEventListener("change", () => ajouterFichiers([...fichier.files]));
  depot.addEventListener("click", ev => { if (ev.target !== fichier) fichier.click(); });
  depot.addEventListener("dragover", e => { e.preventDefault(); depot.classList.add("survol"); });
  depot.addEventListener("dragleave", () => depot.classList.remove("survol"));
  depot.addEventListener("drop", e => { e.preventDefault(); depot.classList.remove("survol"); ajouterFichiers([...(e.dataTransfer?.files || [])]); });
  const coller = e => {
    if (!document.body.contains(form)) { document.removeEventListener("paste", coller); return; }
    const fichiers = [...(e.clipboardData?.items || [])].filter(i => i.kind === "file" && i.type.startsWith("image/")).map(i => i.getAsFile());
    if (fichiers.length) { e.preventDefault(); ajouterFichiers(fichiers); }
  };
  document.addEventListener("paste", coller);
  function remplir(n0) {
    const n = migrer(n0);
    enEdition = n; montrer("saisie");
    choisirPaire(n.paire, !mes.includes(n.paire));
    texte.value = n.contexte || "";
    const d = new Date(n.date_heure || n.cree_le); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); champDate.value = d.toISOString().slice(0, 16);
    elements = (n.elements || []).map(x => ({ ...x }));
    captures = (n.captures || []).map(x => ({ ...x, unites: [...(x.unites || [])] }));
    statut.value = n.resultat?.statut || "analyse"; pnl.value = n.resultat?.pnl_eur ?? ""; pips.value = n.resultat?.pips ?? ""; r.value = n.resultat?.r ?? "";
    champSens.value = n.sens || n.stats?.sens || "Pas encore décidé";
    champEntree.value = n.plan?.entree ?? ""; champInval.value = n.plan?.invalidation ?? ""; champRisque.value = n.plan?.risque_eur ?? "";
    rendreApercus(); rendreElements(); rendreAgenda();
    annuler.hidden = false; enregistrer.textContent = "Enregistrer les modifications";
    form.dispatchEvent(new CustomEvent("jn-edition", { detail: n }));   // Journal V3 : ouvre le panneau latéral
    if (!form.closest(".drawer")) form.scrollIntoView({ block: "start" });
  }
  function vider() {
    enEdition = null; texte.value = ""; captures = []; rendreApercus(); champDate.value = maintenantLocal();
    statut.value = "analyse"; pnl.value = ""; pips.value = ""; r.value = "";
    champSens.value = "Pas encore décidé"; champEntree.value = ""; champInval.value = ""; champRisque.value = "";
    choisirPaire(champPaire.value || mes[0], !mes.includes(champPaire.value));
    annuler.hidden = true; enregistrer.textContent = "Enregistrer l'entrée";
  }
  annuler.addEventListener("click", vider);
  form.addEventListener("jn-vider", vider);   // Journal V3 : nouvelle entrée depuis le panneau
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const maintenant = new Date().toISOString();
    const n = {
      ...(enEdition || {}), version: 2,
      id: enEdition?.id || crypto.randomUUID(), cree_le: enEdition?.cree_le || maintenant, modifie_le: maintenant,
      date_heure: champDate.value ? new Date(champDate.value).toISOString() : maintenant,
      paire: champPaire.value, contexte: texte.value.trim(),
      captures: captures.map(({ id, unites, blob, largeur, hauteur }) => ({ id, unites, blob, largeur, hauteur })),
      elements: elements.filter(x => x.avis || x.perso), compteur: compter(elements),
      evenements_suivis: evenementsTouchent.map(({ id, iso_utc, devise, evenement, raison }) => ({ id, iso_utc, devise, evenement, raison })),
      horizon: champHorizon.value,
      resultat: { statut: statut.value, pnl_eur: pnl.value.trim() || null, pips: pips.value.trim() || null, r: r.value.trim() || null },
      sens: champSens.value,
      plan: { entree: champEntree.value.trim() || null, invalidation: champInval.value.trim() || null, risque_eur: champRisque.value.trim() || null },
      instantane: enEdition?.instantane || { ...instantane(paires.fiches[champPaire.value] || {}),
        etats: donneesJour.profil ? Object.fromEntries(donneesJour.profil.devises.map(p => [p.devise, p.etat.valeur])) : null },
    };
    n.performance = performance(n);   // onglet Performance (préparé, pas encore affiché)
    // Lot V8 : enregistré seul pour les statistiques (thème et direction du jour, solde des engrenages de la paire,
    // confluences cochées, séance déduite de l'heure, résultat en R) ; repris tel quel lors d'une modification.
    const th = donneesJour.rapport?.theme || {}, fi = paires.fiches[champPaire.value] || {};
    n.stats = {
      ...(enEdition?.stats || { theme: th.titre || null, direction: th.direction?.libelle || null, date_theme: donneesJour.rapport?.date || null,
                                 solde_engrenages: fi.macro?.decomposition?.solde ?? null }),
      sens: champSens.value, seance: seanceDe(n.date_heure), confluences: n.compteur.pour,
      avec_theme: avecLeTheme(n.paire, champSens.value, (enEdition?.stats || {}).direction ?? th.direction?.libelle),
      risque_eur: n.plan.risque_eur, r: resultatR(n),
    };
    if (!n.contexte && !n.captures.length && !n.elements.length) { afficherErreur("entrée vide (contexte, capture ou élément attendu)"); return; }
    try { await ecrireNote(n); afficherErreur(""); vider(); await rendreListe(); form.dispatchEvent(new CustomEvent("jn-enregistre", { detail: n })); }
    catch (err) { afficherErreur(messageErreur(err)); }
  });

  // ------------- calendrier du mois (écran 9)
  let moisCourant = new Date().toISOString().slice(0, 7), filtreCal = "";
  const eur = v => v === null || v === undefined ? "" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
  function rendreCalendrier() {
    const [a, m] = moisCourant.split("-").map(Number);
    const tete = el("div", "jn-cal-tete");
    const prec = el("button", "bouton", "‹"); prec.type = "button"; prec.setAttribute("aria-label", "Mois précédent");
    const suiv = el("button", "bouton", "›"); suiv.type = "button"; suiv.setAttribute("aria-label", "Mois suivant");
    const titre = el("h2", null, new Date(Date.UTC(a, m - 1, 15)).toLocaleDateString("fr-FR", { month: "long", year: "numeric" }).replace(/^./, c => c.toUpperCase()));
    const decaler = k => { const d = new Date(Date.UTC(a, m - 1 + k, 15)); moisCourant = d.toISOString().slice(0, 7); rendreCalendrier(); };
    prec.addEventListener("click", () => decaler(-1)); suiv.addEventListener("click", () => decaler(1));
    const nouvelle = el("button", "bouton jn-principal", "+ Nouvelle entrée"); nouvelle.type = "button"; nouvelle.addEventListener("click", () => { vider(); montrer("saisie"); });
    tete.append(prec, titre, suiv, nouvelle);
    const b = bilanMensuel(toutes, moisCourant, filtreCal);
    const bilan = el("div", "jn-bilan");
    for (const [lib, v, cls] of [["Résultat du mois", eur(b.total_eur) || "0 €", b.total_eur > 0 ? "pos" : b.total_eur < 0 ? "neg" : ""], ["Trades clôturés", String(b.clotures)],
                                 ["Gagnants", b.gagnants_pct == null ? "n/d" : `${b.gagnants_pct} %`], ["R moyen", b.r_moyen == null ? "n/d" : String(b.r_moyen).replace(".", ",").replace("-", "−")],
                                 ["Meilleure paire", b.meilleure ? `${b.meilleure.paire} ${eur(b.meilleure.eur)}` : "n/d"], ["Pire paire", b.pire ? `${b.pire.paire} ${eur(b.pire.eur)}` : "n/d"]]) {
      const t = el("div", "jn-bilan-t"); t.append(el("span", "note", lib), el("b", `tabulaire ${cls || ""}`, v)); bilan.appendChild(t);
    }
    const filtres = el("div", "jn-puces"); filtres.setAttribute("role", "group"); filtres.setAttribute("aria-label", "Filtrer par paire");
    for (const p of ["", ...new Set(toutes.map(n => n.paire))]) {
      const f = el("button", "jn-puce", p || "Toutes"); f.type = "button"; f.setAttribute("aria-pressed", String(p === filtreCal));
      f.addEventListener("click", () => { filtreCal = p; rendreCalendrier(); }); filtres.appendChild(f);
    }
    const defile = el("div", "defile");
    const grille = el("div", "jn-cal-grille");
    for (const h of ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim", "Semaine"]) grille.appendChild(el("span", "jn-cal-h", h));
    const detailJour = el("aside", "jn-cal-detail");
    const montrerJour = j => {
      detailJour.replaceChildren(el("h3", null, new Date(`${j.iso}T12:00:00Z`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })));
      if (!j.entrees.length) { detailJour.appendChild(el("p", "note", "Aucune entrée ce jour-là.")); return; }
      for (const n of j.entrees) {
        const art = el("article", "jn-cal-entree");
        const t = el("div", "jn-entree-tete"); t.append(el("b", null, n.paire), el("span", `tabulaire ${nombreFr(n.resultat?.pnl_eur) > 0 ? "pos" : nombreFr(n.resultat?.pnl_eur) < 0 ? "neg" : ""}`,
          n.resultat?.statut === "cloturee" ? eur(nombreFr(n.resultat.pnl_eur)) : STATUTS[n.resultat?.statut || "analyse"]));
        const c = compter(n.elements);
        art.append(t, el("p", null, n.contexte || "—"),
                   el("p", "note", `Unités : ${[...new Set((n.captures || []).flatMap(x => x.unites || []))].join(" · ") || "—"} · confluence : ${c.pour} pour · ${c.contre} contre`));
        if ((n.captures || []).length) art.appendChild(miniatures(n));
        const o = el("button", "bouton", "Ouvrir"); o.type = "button"; o.addEventListener("click", () => detail(n)); art.appendChild(o);
        detailJour.appendChild(art);
      }
    };
    for (const s of grilleMois(toutes, moisCourant, filtreCal)) {
      for (const j of s.jours) {
        if (!j) { grille.appendChild(el("span", "jn-cal-vide")); continue; }
        const c = el("button", `jn-cal-case${j.net > 0 ? " pos" : j.net < 0 ? " neg" : ""}`); c.type = "button";
        c.setAttribute("aria-label", `${j.jour} : ${j.entrees.length} ${j.entrees.length < 2 ? "entrée" : "entrées"}${j.net !== null ? `, ${eur(j.net)}` : ""}`);
        c.append(el("span", "jn-cal-num", String(j.jour)), ...[...new Set(j.entrees.map(n => n.paire))].slice(0, 3).map(p => el("span", "jn-cal-paire", p)));
        if (j.net !== null) c.appendChild(el("span", "jn-cal-net tabulaire", eur(j.net)));
        c.addEventListener("click", () => montrerJour(j));
        grille.appendChild(c);
      }
      grille.appendChild(el("span", `jn-cal-sem tabulaire${s.total > 0 ? " pos" : s.total < 0 ? " neg" : ""}`, s.total === null ? "—" : eur(s.total)));
    }
    defile.appendChild(grille);
    const corps = el("div", "jn-cal-corps"); corps.append(defile, detailJour);
    detailJour.appendChild(el("p", "note", "Touchez un jour pour voir ses entrées."));
    calendrier.replaceChildren(tete, bilan, filtres, corps, el("p", "note", "Résultat net des entrées clôturées, jour par jour et par semaine. Mes chiffres, saisis à la main : un constat, pas un conseil."));
  }

  // ------------- liste, filtres, sauvegarde
  const liste = el("section", "carte jn-liste");
  liste.appendChild(el("h2", null, "Mes entrées"));
  const rappel = el("p", "jn-rappel"); rappel.hidden = true;
  const filtres = el("div", "outils jn-filtres");
  const fPaire = el("select"); fPaire.setAttribute("aria-label", "Filtrer par paire"); fPaire.appendChild(new Option("Toutes les paires", ""));
  for (const p of paires.paires || []) fPaire.appendChild(new Option(p, p));
  const fEtiq = el("select"); fEtiq.setAttribute("aria-label", "Filtrer par statut");
  const fPeriode = el("select"); fPeriode.setAttribute("aria-label", "Filtrer par période");
  for (const [v, l] of [["", "Toute la période"], ["7", "7 derniers jours"], ["30", "30 derniers jours"], ["90", "90 derniers jours"]]) fPeriode.appendChild(new Option(l, v));
  filtres.append(fPaire, fEtiq, fPeriode);
  const exporter = el("button", "bouton", "Exporter (.json)"); exporter.type = "button";
  const importer = el("button", "bouton", "Importer"); importer.type = "button";
  const fImport = el("input"); fImport.type = "file"; fImport.accept = "application/json,.json"; fImport.hidden = true;
  const etat = el("p", "note");
  const sauvegarde = el("div", "jn-actions"); sauvegarde.append(exporter, importer, fImport);
  const zoneListe = el("ol", "jn-entrees");
  liste.append(rappel, filtres, sauvegarde, etat, zoneListe);
  droite.append(vues, form, calendrier, liste);

  let toutes = [];
  async function rendreListe() {
    try {
      const brutes = await lireNotes();
      toutes = [];
      for (const n of brutes) {   // migration V1 -> V2 sans perte, écrite une seule fois
        const m = migrer(n);
        if (m !== n) await ecrireNote(m);
        toutes.push(m);
      }
      toutes.sort((a, b) => String(b.date_heure || b.cree_le).localeCompare(String(a.date_heure || a.cree_le)));
    } catch (err) { etat.textContent = `Entrées indisponibles : ${messageErreur(err)}.`; zoneListe.replaceChildren(); return; }
    const garde = fEtiq.value;
    fEtiq.replaceChildren(new Option("Tous les statuts", ""), ...Object.entries(STATUTS).map(([v, l]) => new Option(l, v)));
    fEtiq.value = garde;
    const limite = fPeriode.value ? Date.now() - Number(fPeriode.value) * 864e5 : 0;
    const vuesL = toutes.filter(n => (!fPaire.value || n.paire === fPaire.value) && (!fEtiq.value || (n.resultat?.statut || "analyse") === fEtiq.value)
      && Date.parse(n.date_heure || n.cree_le) >= limite);
    etat.textContent = `${pluriel(vuesL.length, "entrée affichée", "entrées affichées")} sur ${toutes.length}.`;
    zoneListe.replaceChildren(...vuesL.map(entree));
    if (!calendrier.hidden) rendreCalendrier();
    try {
      const meta = await lireMeta("derniere_sauvegarde");
      const ref = meta?.valeur || (toutes.length ? toutes[toutes.length - 1].cree_le : null);
      const jours = ref ? Math.floor((Date.now() - Date.parse(ref)) / 864e5) : 0;
      rappel.hidden = !(toutes.length && jours > 7);
      rappel.textContent = meta?.valeur ? `Dernière sauvegarde il y a ${jours} jours : pensez à exporter vos entrées.` : `Aucune sauvegarde depuis ${jours} jours : pensez à exporter vos entrées.`;
    } catch (e) { rappel.hidden = true; }
  }
  function miniatures(n) {
    const z = el("div", "jn-miniatures");
    for (const im of n.captures || []) {
      const lib = (im.unites || []).join(" · ") || "sans unité";
      const b = el("button", "jn-mini"); b.type = "button"; b.setAttribute("aria-label", `Agrandir la capture ${lib}`);
      const img = el("img"); img.alt = ""; img.src = URL.createObjectURL(im.blob); b.appendChild(img);
      b.appendChild(el("span", null, lib));
      b.addEventListener("click", e => { e.stopPropagation(); pleinEcran(im); });
      z.appendChild(b);
    }
    return z;
  }
  function pleinEcran(im) {
    const d = el("dialog", "jn-plein"); d.setAttribute("aria-label", "Capture en plein écran");
    const img = el("img"); img.alt = `Capture ${(im.unites || []).join(", ")}`; img.src = URL.createObjectURL(im.blob);
    const f = el("button", "bouton", "Fermer"); f.type = "button";
    const fin = () => { d.close?.(); d.remove(); };
    f.addEventListener("click", fin); d.addEventListener("click", e => { if (e.target === d) fin(); });
    d.addEventListener("cancel", e => { e.preventDefault(); fin(); });
    d.append(f, img); document.body.appendChild(d); d.showModal?.();
  }
  function entree(n) {
    const li = el("li", "jn-entree");
    const t = el("div", "jn-entree-tete");
    const c = compter(n.elements);
    t.append(el("b", null, n.paire), el("span", "ck-petit", dateHeure(n.date_heure || n.cree_le)),
             el("span", "jn-etiq", STATUTS[n.resultat?.statut || "analyse"]), el("span", "ck-petit", `${c.pour} pour · ${c.contre} contre`));
    if (n.resultat?.statut === "cloturee" && nombreFr(n.resultat.pnl_eur) !== null) t.appendChild(el("b", `tabulaire ${nombreFr(n.resultat.pnl_eur) >= 0 ? "pos" : "neg"}`, eur(nombreFr(n.resultat.pnl_eur))));
    li.appendChild(t);
    li.appendChild(el("p", "jn-extrait", (n.contexte || "").slice(0, 180) + ((n.contexte || "").length > 180 ? "…" : "")));
    if ((n.captures || []).length) li.appendChild(miniatures(n));
    const sv = suivi(n, paires);
    if (sv && !sv.raison) li.appendChild(el("p", "jn-suivi", `Depuis l'entrée (${nombre(sv.depuis[1])} le ${dateCourte(sv.depuis[0])}) : 1 j ${sv.j1 == null ? "n/d" : `${signe(sv.j1)} %`} · 1 sem. ${sv.s1 == null ? "n/d" : `${signe(sv.s1)} %`} · 1 mois ${sv.m1 == null ? "n/d" : `${signe(sv.m1)} %`} — un constat, pas un score.`));
    const ouvrir = el("button", "bouton", "Ouvrir"); ouvrir.type = "button";
    ouvrir.addEventListener("click", () => detail(n));
    li.appendChild(ouvrir);
    return li;
  }
  function detail(n) {
    const noeuds = [];
    const c = compter(n.elements);
    noeuds.push(el("p", "ck-petit", `${dateHeure(n.date_heure || n.cree_le)}${n.modifie_le !== n.cree_le ? ` · modifiée ${dateHeure(n.modifie_le)}` : ""} · ${STATUTS[n.resultat?.statut || "analyse"]}`
      + (n.resultat?.statut === "cloturee" ? ` · ${n.resultat.pnl_eur ?? "n/d"} € · ${n.resultat.pips ?? "n/d"} pips · ${n.resultat.r ?? "n/d"} R` : "")), texteMisEnForme(n.contexte));
    if ((n.elements || []).length) {
      noeuds.push(el("h3", null, `Éléments confluents : ${c.pour} pour · ${c.contre} contre`));
      noeuds.push(el("ul", null)); for (const x of n.elements) noeuds[noeuds.length - 1].appendChild(el("li", null, `${x.avis === "pour" ? "✓ Pour" : x.avis === "contre" ? "✗ Contre" : "·"} ${x.devise} : ${x.texte} (${x.source})`));
    }
    if (n.biais) noeuds.push(el("p", "ck-petit", `Note V1 : biais ${BIAIS[n.biais] || n.biais} · étiquettes ${(n.etiquettes || []).join(", ") || "—"}`));
    if ((n.captures || []).length) noeuds.push(miniatures(n));
    if ((n.evenements_suivis || []).length) noeuds.push(el("p", "ck-petit", `Évènements suivis : ${n.evenements_suivis.map(x => `${x.devise} ${x.evenement}`).join(" · ")}`));
    const i = n.instantane || {};
    const inst = el("div", "jn-instantane");
    inst.append(el("h3", null, `Ce que disaient les données (rapport du ${dateCourte(i.date_rapport)})`),
                el("p", null, `Thème : ${i.theme || "n/d"} · ${i.decomposition || "décomposition n/d"}`),
                el("p", null, `Cours ${nombre(i.technique?.cours)} · RSI ${i.technique?.rsi14 ?? "n/d"} · MM200 ${i.technique?.ecart_mm200 == null ? "n/d" : `${signe(i.technique.ecart_mm200)} %`}`),
                ...(i.etats ? [el("p", "ck-petit", `États des devises : ${Object.entries(i.etats).map(([d, e]) => `${d} ${e}`).join(" · ")}`)] : []),
                ...(i.synthese || []).map(l => el("p", "ck-petit", l)));
    noeuds.push(inst);
    const actions = el("div", "jn-actions");
    const modifier = el("button", "bouton", "Modifier"); modifier.type = "button";
    modifier.addEventListener("click", () => { document.getElementById("detail").close?.(); remplir(n); });
    const supprimer = el("button", "bouton", "Supprimer"); supprimer.type = "button";
    const confirmation = el("span", "jn-confirm"); confirmation.hidden = true;
    const oui = el("button", "bouton jn-danger", "Oui, supprimer définitivement"); oui.type = "button";
    const non = el("button", "bouton", "Annuler"); non.type = "button";
    confirmation.append(el("span", null, "Supprimer cette entrée ? "), oui, non);
    supprimer.addEventListener("click", () => { confirmation.hidden = false; supprimer.hidden = true; oui.focus(); });
    non.addEventListener("click", () => { confirmation.hidden = true; supprimer.hidden = false; });
    oui.addEventListener("click", async () => {
      try { await supprimerNote(n.id); document.getElementById("detail").close?.(); await rendreListe(); }
      catch (err) { confirmation.replaceChildren(el("span", "indisponible", `Suppression impossible : ${messageErreur(err)}.`)); }
    });
    const notion = el("button", "bouton", "Copier pour Notion"); notion.type = "button";
    notion.addEventListener("click", () => copier(markdown(n), notion));
    actions.append(modifier, notion, supprimer, confirmation);
    noeuds.push(actions);
    ouvrirDetail(`${n.paire} — entrée du ${dateCourte(n.date_heure || n.cree_le)}`, noeuds);
  }
  for (const f of [fPaire, fEtiq, fPeriode]) f.addEventListener("change", rendreListe);
  exporter.addEventListener("click", async () => {
    try {
      const notes = (await lireNotes()).map(migrer);
      const sortie = { format: "fxdesk-journal", version: 2, exporte_le: new Date().toISOString(), notes: [] };
      const versDonnees = async im => ({ ...im, blob: undefined, donnees: await versDataURL(im.blob), type: im.blob.type });
      for (const n of notes) sortie.notes.push({ ...n, captures: await Promise.all((n.captures || []).map(versDonnees)),
                                                 images: await Promise.all((n.images || []).map(versDonnees)) });
      const blob = new Blob([JSON.stringify(sortie)], { type: "application/json" });
      const a = el("a"); a.href = URL.createObjectURL(blob); a.download = `journal-fxdesk-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a); a.click(); a.remove();
      await ecrireMeta("derniere_sauvegarde", sortie.exporte_le);
      await rendreListe(); etat.textContent = `${pluriel(notes.length, "entrée exportée", "entrées exportées")} avec leurs captures ; sauvegarde enregistrée.`;
    } catch (err) { afficherErreur(`export impossible : ${messageErreur(err)}`); }
  });
  importer.addEventListener("click", () => fImport.click());
  fImport.addEventListener("change", async () => {
    try {
      const doc = JSON.parse(await fImport.files[0].text());
      if (doc.format !== "fxdesk-journal") throw new Error("fichier qui n'est pas un export du journal");
      const existants = new Set((await lireNotes()).map(n => n.id));
      let ajoutees = 0, doublons = 0;
      const versBlob = async im => ({ ...im, donnees: undefined, type: undefined, blob: await depuisDataURL(im.donnees) });
      for (const n of doc.notes || []) {
        if (existants.has(n.id)) { doublons++; continue; }
        await ecrireNote(migrer({ ...n, images: await Promise.all((n.images || []).filter(x => x.donnees).map(versBlob)),
                                  ...(n.captures ? { captures: await Promise.all(n.captures.filter(x => x.donnees).map(versBlob)) } : {}) }));
        ajoutees++;
      }
      await rendreListe();
      etat.textContent = `Import : ${pluriel(ajoutees, "entrée ajoutée", "entrées ajoutées")}, ${pluriel(doublons, "doublon ignoré", "doublons ignorés")}.`;
    } catch (err) { afficherErreur(`import impossible : ${messageErreur(err)}`); }
    fImport.value = "";
  });

  rendreFiche();
  choisirPaire(paireActive, !mes.includes(paireActive));
  montrer("saisie");
  try { await ouvrirBase(); } catch (err) { afficherErreur(messageErreur(err)); enregistrer.disabled = true; }
  await rendreListe();
  return [tete, grille];
}
