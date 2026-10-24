/* Espace Journal (lot V5, étape 7). Colonne gauche : fiche d'analyse de la paire (docs/data/paires.json, calcul Python)
   et graphiques. Colonne droite : mes notes, stockées dans le navigateur (IndexedDB), sans serveur ni clé ; export / import
   JSON (images intégrées) pour la sauvegarde et le transfert. Le biais personnel reste MA lecture, jamais un ordre. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, ouvrirDetail } from "./commun.js";
import { graphiqueSerie, dessinerReperes } from "./dossiers.js";

const SVG = "http://www.w3.org/2000/svg";
const UNITES = [["30min", "30 min"], ["4h", "4 h"], ["1j", "1 j"]];
const BIAIS = { haussier: "Haussier", neutre: "Neutre", baissier: "Baissier" };
const COURTS = { 1: "Thème", 2: "Monétaire", 3: "Données", 4: "Fiscale", 5: "Marchés", 6: "Géopolitique", 7: "Flux", 8: "Offre" };
const signe = (v, d = 2) => v == null ? "n/d" : `${v > 0 ? "+" : ""}${Number(v).toLocaleString("fr-FR", { maximumFractionDigits: d })}`.replace("-", "−");
const nombre = (v, d = 4) => v == null ? "n/d" : Number(v).toLocaleString("fr-FR", { maximumFractionDigits: d });
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
const lireNotes = () => tx("notes", "readonly", st => st.getAll());
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
           portage: { directeur_pb: m.portage?.directeur_pb, deux_ans_pb: m.portage?.deux_ans_pb }, scores: m.scores };
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
    c.appendChild(el("p", "note", mes.includes(f.paire) ? `30 min / 4 h : ${f.chandeliers?.raison || "non collectés"}.` : "30 min / 4 h : ajouter la paire à Mes paires (config.yaml, journal.mes_paires)."));
  }
  return c;
}

function tuile(libelle, valeur, detail, lien) {
  const t = el("div", "jn-tuile");
  t.append(el("span", "jn-t-lib", libelle), el("b", "jn-t-val tabulaire", valeur));
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
    t.raison ? t.raison : "série journalière, écart à la moyenne 200 j"));
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
  macro.appendChild(el("p", null, `Scores de confluence : ${f.base} ${m.scores?.[f.base] ?? "n/d"} · ${f.cotation} ${m.scores?.[f.cotation] ?? "n/d"}. `
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
function markdown(n) {
  const i = n.instantane || {};
  const lignes = [`## ${n.paire} — ${dateHeure(n.cree_le)}`, "",
    `**Biais personnel (ma lecture, pas un ordre) :** ${BIAIS[n.biais] || "—"}`,
    `**Unités de temps regardées :** ${(n.unites || []).map(u => UNITES.find(x => x[0] === u)?.[1]).join(", ") || "—"}`,
    `**Étiquettes :** ${(n.etiquettes || []).join(", ") || "—"}`, "", n.texte || "", "",
    `**Instantané de l'analyse (rapport du ${i.date_rapport || "n/d"}) :**`,
    `- Thème : ${i.theme || "n/d"}`, `- ${i.decomposition || "Décomposition n/d"}`,
    `- Technique : cours ${i.technique?.cours ?? "n/d"}, RSI ${i.technique?.rsi14 ?? "n/d"}, écart MM200 ${i.technique?.ecart_mm200 ?? "n/d"} %`,
    ...((i.synthese || []).map(l => `- ${l}`)), ""];
  if ((n.images || []).length) lignes.push(`_Images à joindre à la main : ${n.images.length} (${n.images.map(x => UNITES.find(u => u[0] === x.unite)?.[1] || x.unite).join(", ")})._`);
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
  tete.appendChild(el("p", "sous-titre", "À gauche, la fiche d'analyse de la paire (calcul Python à chaque run). À droite, mes notes : elles restent dans ce navigateur (IndexedDB) ; l'export sert de sauvegarde et de transfert. Mon biais est ma lecture, jamais un ordre."));
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
  const rendreFiche = () => { zoneFiche.replaceChildren(ficheAnalyse(paires.fiches[paireActive], mes)); champPaire.value = paireActive; };
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

  // ------------- formulaire de note
  const form = el("form", "carte jn-form");
  form.appendChild(el("h2", null, "Nouvelle note"));
  const erreur = el("p", "indisponible jn-erreur"); erreur.hidden = true;
  const champPaire = el("select", "ot-select"); champPaire.setAttribute("aria-label", "Paire de la note");
  for (const p of paires.paires || []) champPaire.appendChild(new Option(p, p));
  const unites = el("fieldset", "jn-unites"); unites.appendChild(el("legend", null, "Unités de temps regardées"));
  for (const [u, lib] of UNITES) { const l = el("label"); const c = el("input"); c.type = "checkbox"; c.value = u; l.append(c, document.createTextNode(` ${lib}`)); unites.appendChild(l); }
  const biais = el("fieldset", "jn-unites jn-biais"); biais.appendChild(el("legend", null, "Mon biais (ma lecture, pas un ordre)"));
  for (const [v, lib] of Object.entries(BIAIS)) { const l = el("label"); const r = el("input"); r.type = "radio"; r.name = "jn-biais"; r.value = v; if (v === "neutre") r.checked = true; l.append(r, document.createTextNode(` ${lib}`)); biais.appendChild(l); }
  const texte = el("textarea", "jn-zone"); texte.rows = 6; texte.placeholder = "Mon analyse… (mise en forme : **gras**, *italique*, lignes « - » pour une liste)";
  texte.setAttribute("aria-label", "Texte de la note");
  const etiquettes = el("input", "jn-etiquettes"); etiquettes.type = "text"; etiquettes.placeholder = "Étiquettes, séparées par des virgules";
  etiquettes.setAttribute("aria-label", "Étiquettes");
  const depot = el("div", "jn-depot"); depot.tabIndex = 0;
  depot.appendChild(el("p", "jn-depot-titre", "Coller (Ctrl+V) ou glisser mes captures"));
  depot.appendChild(el("p", null, "Chaque image reçoit son unité de temps (30 min · 4 h · 1 j) ; compression à 1600 px, rien n'est envoyé."));
  const fichier = el("input"); fichier.type = "file"; fichier.accept = "image/*"; fichier.multiple = true; fichier.setAttribute("aria-label", "Ajouter des images");
  const apercus = el("div", "jn-apercus");
  depot.append(fichier, apercus);
  const enregistrer = el("button", "bouton jn-principal", "Enregistrer · avec l'instantané de l'analyse du jour"); enregistrer.type = "submit";
  const annuler = el("button", "bouton", "Annuler la modification"); annuler.type = "button"; annuler.hidden = true;
  const actions = el("div", "jn-actions"); actions.append(enregistrer, annuler);
  form.append(erreur, el("label", "jn-lab", "Paire"), champPaire, unites, biais, texte, etiquettes, depot, actions,
              el("p", "note", "Date et heure ajoutées automatiquement ; un instantané de la fiche d'analyse du moment est gardé avec la note."));
  let images = [];       // {id, unite, blob, largeur, hauteur}
  let enEdition = null;
  const afficherErreur = m => { erreur.textContent = `Journal : ${m}.`; erreur.hidden = !m; };
  function rendreApercus() {
    apercus.replaceChildren(...images.map((im, k) => {
      const b = el("div", "jn-apercu");
      const img = el("img"); img.alt = `Capture ${k + 1}`; img.src = URL.createObjectURL(im.blob);
      const u = el("select"); u.setAttribute("aria-label", "Unité de temps de l'image");
      for (const [v, lib] of UNITES) u.appendChild(new Option(lib, v));
      u.value = im.unite; u.addEventListener("change", () => { im.unite = u.value; });
      const x = el("button", "bouton", "Retirer"); x.type = "button"; x.addEventListener("click", () => { images.splice(k, 1); rendreApercus(); });
      b.append(img, u, x);
      return b;
    }));
  }
  async function ajouterFichiers(liste) {
    for (const f of liste) {
      if (!f.type.startsWith("image/")) continue;
      try { const c = await compresser(f); images.push({ id: crypto.randomUUID(), unite: "4h", ...c }); }
      catch (e) { afficherErreur(`image illisible (${e.message || e})`); }
    }
    rendreApercus();
  }
  fichier.addEventListener("change", () => ajouterFichiers([...fichier.files]));
  depot.addEventListener("dragover", e => { e.preventDefault(); depot.classList.add("survol"); });
  depot.addEventListener("dragleave", () => depot.classList.remove("survol"));
  depot.addEventListener("drop", e => { e.preventDefault(); depot.classList.remove("survol"); ajouterFichiers([...(e.dataTransfer?.files || [])]); });
  const coller = e => {
    if (!document.body.contains(form)) { document.removeEventListener("paste", coller); return; }
    const fichiers = [...(e.clipboardData?.items || [])].filter(i => i.kind === "file" && i.type.startsWith("image/")).map(i => i.getAsFile());
    if (fichiers.length) { e.preventDefault(); ajouterFichiers(fichiers); }
  };
  document.addEventListener("paste", coller);
  function remplir(n) {
    enEdition = n; champPaire.value = n.paire; texte.value = n.texte || ""; etiquettes.value = (n.etiquettes || []).join(", ");
    unites.querySelectorAll("input").forEach(c => { c.checked = (n.unites || []).includes(c.value); });
    biais.querySelectorAll("input").forEach(r => { r.checked = r.value === n.biais; });
    images = (n.images || []).map(x => ({ ...x }));
    rendreApercus(); annuler.hidden = false; enregistrer.textContent = "Enregistrer les modifications";
    form.scrollIntoView({ block: "start" });
  }
  function vider() {
    enEdition = null; texte.value = ""; etiquettes.value = ""; images = []; rendreApercus();
    unites.querySelectorAll("input").forEach(c => { c.checked = false; });
    annuler.hidden = true; enregistrer.textContent = "Enregistrer la note";
  }
  annuler.addEventListener("click", vider);
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const maintenant = new Date().toISOString();
    const n = {
      id: enEdition?.id || crypto.randomUUID(), cree_le: enEdition?.cree_le || maintenant, modifie_le: maintenant,
      paire: champPaire.value, unites: [...unites.querySelectorAll("input:checked")].map(c => c.value),
      biais: biais.querySelector("input:checked")?.value || "neutre", texte: texte.value.trim(),
      etiquettes: etiquettes.value.split(",").map(x => x.trim()).filter(Boolean),
      images: images.map(({ id, unite, blob, largeur, hauteur }) => ({ id, unite, blob, largeur, hauteur })),
      instantane: enEdition?.instantane || instantane(paires.fiches[champPaire.value] || {}),
    };
    if (!n.texte && !n.images.length) { afficherErreur("note vide (texte ou image attendu)"); return; }
    try { await ecrireNote(n); afficherErreur(""); vider(); await rendreListe(); }
    catch (err) { afficherErreur(messageErreur(err)); }
  });

  // ------------- liste, filtres, sauvegarde
  const liste = el("section", "carte jn-liste");
  liste.appendChild(el("h2", null, "Mes notes"));
  const rappel = el("p", "jn-rappel"); rappel.hidden = true;
  const filtres = el("div", "outils jn-filtres");
  const fPaire = el("select"); fPaire.setAttribute("aria-label", "Filtrer par paire"); fPaire.appendChild(new Option("Toutes les paires", ""));
  for (const p of paires.paires || []) fPaire.appendChild(new Option(p, p));
  const fEtiq = el("select"); fEtiq.setAttribute("aria-label", "Filtrer par étiquette");
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
  droite.append(form, liste);

  let toutes = [];
  async function rendreListe() {
    try { toutes = (await lireNotes()).sort((a, b) => b.cree_le.localeCompare(a.cree_le)); }
    catch (err) { etat.textContent = `Notes indisponibles : ${messageErreur(err)}.`; zoneListe.replaceChildren(); return; }
    const etiqs = [...new Set(toutes.flatMap(n => n.etiquettes || []))].sort();
    const garde = fEtiq.value;
    fEtiq.replaceChildren(new Option("Toutes les étiquettes", ""), ...etiqs.map(t => new Option(t, t)));
    fEtiq.value = etiqs.includes(garde) ? garde : "";
    const limite = fPeriode.value ? Date.now() - Number(fPeriode.value) * 864e5 : 0;
    const vues = toutes.filter(n => (!fPaire.value || n.paire === fPaire.value) && (!fEtiq.value || (n.etiquettes || []).includes(fEtiq.value))
      && Date.parse(n.cree_le) >= limite);
    etat.textContent = `${vues.length} note(s) affichée(s) sur ${toutes.length}.`;
    zoneListe.replaceChildren(...vues.map(entree));
    try {
      const meta = await lireMeta("derniere_sauvegarde");
      const ref = meta?.valeur || (toutes.length ? toutes[toutes.length - 1].cree_le : null);
      const jours = ref ? Math.floor((Date.now() - Date.parse(ref)) / 864e5) : 0;
      rappel.hidden = !(toutes.length && jours > 7);
      rappel.textContent = meta?.valeur ? `Dernière sauvegarde il y a ${jours} jours : pensez à exporter vos notes.` : `Aucune sauvegarde depuis ${jours} jours : pensez à exporter vos notes.`;
    } catch (e) { rappel.hidden = true; }
  }
  function miniatures(n) {
    const z = el("div", "jn-miniatures");
    for (const im of n.images || []) {
      const b = el("button", "jn-mini"); b.type = "button"; b.setAttribute("aria-label", `Agrandir l'image ${UNITES.find(u => u[0] === im.unite)?.[1] || ""}`);
      const img = el("img"); img.alt = ""; img.src = URL.createObjectURL(im.blob); b.appendChild(img);
      b.appendChild(el("span", null, UNITES.find(u => u[0] === im.unite)?.[1] || im.unite));
      b.addEventListener("click", e => { e.stopPropagation(); pleinEcran(im); });
      z.appendChild(b);
    }
    return z;
  }
  function pleinEcran(im) {
    const d = el("dialog", "jn-plein"); d.setAttribute("aria-label", "Image en plein écran");
    const img = el("img"); img.alt = `Capture ${im.unite}`; img.src = URL.createObjectURL(im.blob);
    const f = el("button", "bouton", "Fermer"); f.type = "button";
    const fin = () => { d.close?.(); d.remove(); };
    f.addEventListener("click", fin); d.addEventListener("click", e => { if (e.target === d) fin(); });
    d.addEventListener("cancel", e => { e.preventDefault(); fin(); });
    d.append(f, img); document.body.appendChild(d); d.showModal?.();
  }
  function entree(n) {
    const li = el("li", "jn-entree");
    const t = el("div", "jn-entree-tete");
    t.append(el("b", null, n.paire), el("span", "ck-petit", dateHeure(n.cree_le)), el("span", `ck-pastille petite biais-${n.biais}`, BIAIS[n.biais] || "—"));
    for (const e of n.etiquettes || []) t.appendChild(el("span", "jn-etiq", e));
    li.appendChild(t);
    li.appendChild(el("p", "jn-extrait", (n.texte || "").slice(0, 180) + ((n.texte || "").length > 180 ? "…" : "")));
    if ((n.images || []).length) li.appendChild(miniatures(n));
    const sv = suivi(n, paires);
    if (sv && !sv.raison) li.appendChild(el("p", "jn-suivi", `Depuis la note (${nombre(sv.depuis[1])} le ${dateCourte(sv.depuis[0])}) : 1 j ${sv.j1 == null ? "n/d" : `${signe(sv.j1)} %`} · 1 sem. ${sv.s1 == null ? "n/d" : `${signe(sv.s1)} %`} · 1 mois ${sv.m1 == null ? "n/d" : `${signe(sv.m1)} %`} — un constat, pas un score.`));
    const ouvrir = el("button", "bouton", "Ouvrir"); ouvrir.type = "button";
    ouvrir.addEventListener("click", () => detail(n));
    li.appendChild(ouvrir);
    return li;
  }
  function detail(n) {
    const noeuds = [];
    const t = el("p", "ck-petit", `${dateHeure(n.cree_le)}${n.modifie_le !== n.cree_le ? ` · modifiée ${dateHeure(n.modifie_le)}` : ""} · unités : ${(n.unites || []).map(u => UNITES.find(x => x[0] === u)?.[1]).join(", ") || "—"} · biais : ${BIAIS[n.biais]} (ma lecture, pas un ordre)`);
    noeuds.push(t, texteMisEnForme(n.texte));
    if ((n.images || []).length) noeuds.push(miniatures(n));
    const i = n.instantane || {};
    const inst = el("div", "jn-instantane");
    inst.append(el("h3", null, `Ce que disait l'analyse (rapport du ${dateCourte(i.date_rapport)})`),
                el("p", null, `Thème : ${i.theme || "n/d"} · ${i.decomposition || "décomposition n/d"}`),
                el("p", null, `Cours ${nombre(i.technique?.cours)} · RSI ${i.technique?.rsi14 ?? "n/d"} · MM200 ${i.technique?.ecart_mm200 == null ? "n/d" : `${signe(i.technique.ecart_mm200)} %`}`),
                ...(i.synthese || []).map(l => el("p", "ck-petit", l)));
    noeuds.push(inst);
    const actions = el("div", "jn-actions");
    const modifier = el("button", "bouton", "Modifier"); modifier.type = "button";
    modifier.addEventListener("click", () => { document.getElementById("detail").close?.(); remplir(n); });
    const supprimer = el("button", "bouton", "Supprimer"); supprimer.type = "button";
    const confirmation = el("span", "jn-confirm"); confirmation.hidden = true;
    const oui = el("button", "bouton jn-danger", "Oui, supprimer définitivement"); oui.type = "button";
    const non = el("button", "bouton", "Annuler"); non.type = "button";
    confirmation.append(el("span", null, "Supprimer cette note ? "), oui, non);
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
    ouvrirDetail(`${n.paire} — note du ${dateCourte(n.cree_le)}`, noeuds);
  }
  for (const f of [fPaire, fEtiq, fPeriode]) f.addEventListener("change", rendreListe);
  exporter.addEventListener("click", async () => {
    try {
      const notes = await lireNotes();
      const sortie = { format: "fxdesk-journal", version: 1, exporte_le: new Date().toISOString(), notes: [] };
      for (const n of notes) sortie.notes.push({ ...n, images: await Promise.all((n.images || []).map(async im => ({ ...im, blob: undefined, donnees: await versDataURL(im.blob), type: im.blob.type }))) });
      const blob = new Blob([JSON.stringify(sortie)], { type: "application/json" });
      const a = el("a"); a.href = URL.createObjectURL(blob); a.download = `journal-fxdesk-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a); a.click(); a.remove();
      await ecrireMeta("derniere_sauvegarde", sortie.exporte_le);
      await rendreListe(); etat.textContent = `${notes.length} note(s) exportée(s) ; sauvegarde enregistrée.`;
    } catch (err) { afficherErreur(`export impossible : ${messageErreur(err)}`); }
  });
  importer.addEventListener("click", () => fImport.click());
  fImport.addEventListener("change", async () => {
    try {
      const doc = JSON.parse(await fImport.files[0].text());
      if (doc.format !== "fxdesk-journal") throw new Error("fichier qui n'est pas un export du journal");
      const existants = new Set((await lireNotes()).map(n => n.id));
      let ajoutees = 0, doublons = 0;
      for (const n of doc.notes || []) {
        if (existants.has(n.id)) { doublons++; continue; }
        const imgs = [];
        for (const im of n.images || []) imgs.push({ id: im.id, unite: im.unite, largeur: im.largeur, hauteur: im.hauteur, blob: await depuisDataURL(im.donnees) });
        await ecrireNote({ ...n, images: imgs }); ajoutees++;
      }
      await rendreListe();
      etat.textContent = `Import : ${ajoutees} note(s) ajoutée(s), ${doublons} doublon(s) ignoré(s).`;
    } catch (err) { afficherErreur(`import impossible : ${messageErreur(err)}`); }
    fImport.value = "";
  });

  rendreFiche();
  try { await ouvrirBase(); } catch (err) { afficherErreur(messageErreur(err)); enregistrer.disabled = true; }
  await rendreListe();
  return [tete, grille];
}
