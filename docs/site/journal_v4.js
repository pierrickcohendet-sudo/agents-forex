/* Lot V10 — Journal V4 : fonctions pures (sans DOM ni réseau), testées par tests/journal_v4.test.mjs.
   Durée d'un trade, calendrier du mois, migration des notes V2 et V3 vers V4, sérialisation de l'éditeur par blocs,
   instantané du contexte le plus proche avant l'entrée, orientation des 8 moteurs selon le sens du trade, phrase de
   synthèse et statistiques selon le contexte. Seule exception au « tout en Python » : ces calculs portent sur les trades
   privés de l'utilisateur, sur son appareil. */
import { nombreFr } from "./journal_logique.js";

export const JOURS_SEM = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
const fr = (v, d = 2) => v == null ? "n/d" : (v < 0 ? "−" : "") + Math.abs(v).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });

/* ------------------------------------------------------------------ durée */
/* Minutes entre deux instants ISO (UTC), ou null. */
export function minutesEntre(debut, fin) {
  const a = Date.parse(debut), b = Date.parse(fin);
  return Number.isFinite(a) && Number.isFinite(b) && b >= a ? Math.round((b - a) / 60000) : null;
}
/* « 45 min », « 2 h 15 », « 3 h », « 1 jour », « 3 jours 4 h ». */
export function dureeTexte(minutes) {
  if (minutes == null) return "n/d";
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 24 * 60) { const h = Math.floor(minutes / 60), m = minutes % 60; return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`; }
  const j = Math.floor(minutes / 1440), h = Math.round((minutes % 1440) / 60);
  return `${j} jour${j > 1 ? "s" : ""}` + (h && h < 24 ? ` ${h} h` : "");
}
export function categorieDuree(minutes) {
  return minutes == null ? null : minutes < 60 ? "moins d'1 h" : minutes < 1440 ? "dans la journée" : "plusieurs jours";
}
/* Raccourcis de durée : la sortie proposée à partir de l'entrée (heure locale « AAAA-MM-JJTHH:MM »). */
export const RACCOURCIS = [["moins d'1 h", 30], ["dans la journée", 240], ["plusieurs jours", 3 * 1440]];
export function ajouterMinutesLocal(local, minutes) {
  const [d, t] = String(local).split("T"); const [y, mo, j] = d.split("-").map(Number); const [hh, mm] = (t || "00:00").split(":").map(Number);
  const x = new Date(Date.UTC(y, mo - 1, j, hh, mm + minutes));
  return x.toISOString().slice(0, 16);
}

/* ------------------------------------------------------------------ notes V4 */
const jourLocal = n => String(n.entree_locale || n.date_heure || n.cree_le || "").slice(0, 10);
export const estV4 = n => n?.version === 4;

/* V2 (lot V5) et V3 (lot V8 : même version 2 avec « stats ») -> V4, sans rien perdre : tous les anciens champs restent,
   le texte libre devient des paragraphes et les captures des blocs image. */
export function migrerV4(n) {
  if (!n || n.version === 4) return n;
  const base = n.version === 2 ? n : { ...n, version: 2, contexte: n.contexte ?? n.texte ?? "", captures: n.captures || n.images || [] };
  const blocs = [];
  for (const p of String(base.contexte || "").split(/\n{2,}/).map(x => x.trim()).filter(Boolean)) {
    const puces = p.split(/\n/).every(l => /^\s*[-*]\s+/.test(l));
    if (puces) for (const l of p.split(/\n/)) blocs.push(bloc("puce", l.replace(/^\s*[-*]\s+/, "")));
    else blocs.push(bloc("paragraphe", p.replace(/\n/g, " ")));
  }
  for (const c of base.captures || []) blocs.push({ ...bloc("image", ""), capture: c.id, legende: c.legende || "", unite: (c.unites || [])[0] || null });
  const iso = base.date_heure || base.cree_le || null;
  return {
    ...base, version: 4, migre_de: base.migre_de ? `${base.migre_de}→2` : (base.stats ? "V3" : "V2"),
    entree_utc: iso, entree_locale: base.entree_locale || (iso ? String(iso).slice(0, 16) : null), sortie_utc: null, sortie_locale: null,
    sens: base.sens || base.stats?.sens || null,
    analyse: { blocs },
  };
}

/* Nouvelle note V4 à partir du formulaire de saisie rapide (heures locales + leur équivalent UTC fourni par l'appelant). */
export function noteV4(champs, maintenant = new Date().toISOString()) {
  const eur = nombreFr(champs.pnl_eur), pips = nombreFr(champs.pips), risque = nombreFr(champs.risque_eur);
  return {
    version: 4, id: champs.id || `j-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
    cree_le: champs.cree_le || maintenant, modifie_le: maintenant,
    paire: champs.paire, sens: champs.sens,
    entree_locale: champs.entree_locale, entree_utc: champs.entree_utc, sortie_locale: champs.sortie_locale || null, sortie_utc: champs.sortie_utc || null,
    date_heure: champs.entree_utc,
    resultat: { statut: "cloturee", pnl_eur: eur, pips, r: risque ? Math.round(100 * eur / risque) / 100 : null },
    plan: { risque_eur: risque },
    captures: champs.captures || [], analyse: champs.analyse || { blocs: [] },
    lecture: champs.lecture || null,
  };
}

/* ------------------------------------------------------------------ calendrier */
export function grilleMoisV4(notes, mois) {
  const jours = {};
  for (const n of notes || []) {
    const d = jourLocal(n);
    if (!d.startsWith(mois)) continue;
    const j = jours[d] || (jours[d] = { trades: [], eur: 0, avec_eur: 0 });
    const eur = nombreFr(n.resultat?.pnl_eur);
    j.trades.push({ id: n.id, paire: n.paire, sens: n.sens, eur, heure: String(n.entree_locale || "").slice(11, 16) });
    if (eur != null) { j.eur += eur; j.avec_eur++; }
  }
  for (const j of Object.values(jours)) {
    j.trades.sort((a, b) => a.heure.localeCompare(b.heure));
    j.classe = !j.avec_eur ? "neutre" : j.eur > 0 ? "gain" : j.eur < 0 ? "perte" : "neutre";
    j.eur = j.avec_eur ? Math.round(j.eur * 100) / 100 : null;
  }
  return jours;
}
export function bilanMoisV4(notes, mois) {
  const l = (notes || []).filter(n => jourLocal(n).startsWith(mois) && n.resultat?.statut === "cloturee");
  const eurs = l.map(n => nombreFr(n.resultat?.pnl_eur)).filter(v => v != null);
  const gagnants = eurs.filter(v => v > 0).length;
  return { n: l.length, eur: eurs.length ? Math.round(eurs.reduce((a, b) => a + b, 0) * 100) / 100 : null,
           reussite: eurs.length ? Math.round(100 * gagnants / eurs.length) : null, gagnants };
}
/* Lundi en premier : nombre de cases vides avant le 1er, nombre de jours. */
export function caseDepart(mois) {
  const [y, m] = mois.split("-").map(Number);
  return { vides: (new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 6) % 7, jours: new Date(Date.UTC(y, m, 0)).getUTCDate() };
}
export function moisVoisin(mois, delta) {
  const [y, m] = mois.split("-").map(Number); const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return d.toISOString().slice(0, 7);
}

/* ------------------------------------------------------------------ éditeur par blocs (sérialisation) */
export const TYPES_BLOCS = ["titre", "sous-titre", "paragraphe", "puce", "numero", "case", "citation", "encadre", "separateur", "image"];
let compteur = 0;
export function bloc(type, texte = "") { compteur++; return { id: `b${Date.now().toString(36)}${compteur}`, type, texte }; }

/* Seules balises gardées dans le texte d'un bloc : gras, italique, lien http(s), retour à la ligne. */
export function nettoyerHtml(html) {
  let liens = 0;
  return String(html || "").replace(/<[^>]*>?/g, tag => {
    if (/^<(b|strong)(\s[^>]*)?>$/i.test(tag)) return "<b>";
    if (/^<\/(b|strong)\s*>$/i.test(tag)) return "</b>";
    if (/^<(i|em)(\s[^>]*)?>$/i.test(tag)) return "<i>";
    if (/^<\/(i|em)\s*>$/i.test(tag)) return "</i>";
    if (/^<br\s*\/?>$/i.test(tag)) return "<br>";
    const a = /^<a\s[^>]*href="(https?:\/\/[^"<>\s]*)"[^>]*>$/i.exec(tag);
    if (a) { liens++; return `<a href="${a[1]}" target="_blank" rel="noopener">`; }
    if (/^<\/a\s*>$/i.test(tag) && liens > 0) { liens--; return "</a>"; }
    return "";                                   // toute autre balise (script, style, lien non http…) est retirée
  }).replace(/&nbsp;/g, " ");
}
export function serialiser(blocs) {
  return (blocs || []).filter(b => TYPES_BLOCS.includes(b.type)).map(b => {
    const o = { id: String(b.id || bloc(b.type).id), type: b.type };
    if (b.type !== "separateur" && b.type !== "image") o.texte = nettoyerHtml(b.texte);
    if (b.type === "case") o.coche = !!b.coche;
    if (b.type === "image") { o.capture = b.capture || null; o.legende = String(b.legende || ""); o.unite = ["M30", "H1", "H4", "D1"].includes(b.unite) ? b.unite : null; }
    return o;
  });
}
export function deserialiser(json) {
  let l = json;
  if (typeof json === "string") { try { l = JSON.parse(json); } catch (e) { return []; } }
  return Array.isArray(l) ? serialiser(l) : [];
}
export function texteBrut(blocs) {
  return (blocs || []).map(b => String(b.texte || b.legende || "").replace(/<[^>]+>/g, "")).filter(Boolean).join("\n");
}
export const MODELE_DEFAUT = [["titre", "Pourquoi je suis entré"], ["paragraphe", ""], ["titre", "Ce que je voyais sur les graphiques"], ["paragraphe", ""],
  ["titre", "Ce qui pouvait invalider"], ["paragraphe", ""], ["titre", "Ce que j'ai appris"], ["paragraphe", ""]];
export const blocsDuModele = modele => (modele || MODELE_DEFAUT).map(([t, x]) => bloc(t, x));

/* ------------------------------------------------------------------ contexte archivé (Lecture du site) */
/* Même règle que core/contexte.instantane_avant : (jour, rang) de l'instantané le plus proche AVANT l'instant UTC. */
export function instantaneAvant(indexJours, momentUtc) {
  let meilleur = null;
  for (const jour of Object.keys(indexJours || {}).sort()) {
    if (jour > String(momentUtc).slice(0, 10)) break;
    (indexJours[jour] || []).forEach((h, i) => { if (h <= momentUtc && (!meilleur || h >= meilleur[2])) meilleur = [jour, i, h]; });
  }
  return meilleur ? { jour: meilleur[0], rang: meilleur[1], heure: meilleur[2] } : null;
}
/* Comparaison d'heures ISO : le site écrit « …+00:00 », le navigateur « …Z » ; on ramène tout à « AAAA-MM-JJTHH:MM+00:00 ». */
export const isoArchive = iso => new Date(iso).toISOString().slice(0, 16) + "+00:00";

export function reconstituer(fichier, rang) {
  const i = fichier?.instantanes?.[rang];
  if (!i) return null;
  const o = { heure_utc: i.heure_utc, rapport_du: i.rapport_du };
  for (const [k, h] of Object.entries(i.refs || {})) o[k] = fichier.blocs?.[h];
  o.moteurs = fichier.moteurs;
  return o;
}

/* Orientation selon le sens du trade : contribution +1 (vers la hausse de la paire) = « dans le sens » d'un achat. */
export function orienter(inst, paire, sens) {
  const p = inst?.paires?.[paire];
  if (!p) return null;
  const [base, cot] = paire.split("/"), s = /vente/i.test(sens) ? -1 : 1;
  const lignes = [];
  for (let n = 1; n <= 8; n++) {
    const c = p.c?.[n - 1], rb = inst.devises?.[base]?.moteurs?.[n - 1] || {}, rc = inst.devises?.[cot]?.moteurs?.[n - 1] || {};
    const statut = c == null ? "nd" : c * s > 0 ? "pour" : c * s < 0 ? "contre" : "neutre";
    const dates = [rb.date, rc.date].filter(Boolean).sort();
    lignes.push({ n, nom: inst.moteurs?.[String(n)]?.nom || `moteur ${n}`, explication: inst.moteurs?.[String(n)]?.explication || "",
                  statut, raison: `${base} : ${rb.raison || "n/d"} · ${cot} : ${rc.raison || "n/d"}`,
                  date: dates[dates.length - 1] || null, source: [...new Set([rb.source, rc.source].filter(Boolean))].join(" ; ") || null });
  }
  const compte = k => lignes.filter(l => l.statut === k);
  return { lignes, pour: compte("pour").length, contre: compte("contre").length, neutres: compte("neutre").length, nd: compte("nd").length,
           noms_pour: compte("pour").map(l => l.nom.toLowerCase()), noms_contre: compte("contre").map(l => l.nom.toLowerCase()) };
}

/* « À l'ouverture du trade (mardi 17/11, 14:40), 5 moteurs sur 8 allaient dans le sens de ton achat d'USD/JPY (…), 1 contre (…), 2 neutres. Thème du jour : … » */
export function phraseSynthese(o, entreeLocale, paire, sens, theme) {
  if (!o) return null;
  const d = new Date(String(entreeLocale).slice(0, 10) + "T12:00:00Z");
  const quand = `${JOURS_SEM[d.getUTCDay()]} ${String(entreeLocale).slice(8, 10)}/${String(entreeLocale).slice(5, 7)}, ${String(entreeLocale).slice(11, 16)}`;
  const art = /^[AEIOUY]/.test(paire) ? "d'" : "de ";
  const action = /vente/i.test(sens) ? "ta vente" : "ton achat";
  const liste = l => l.length ? ` (${l.join(", ")})` : "";
  let t = `À l'ouverture du trade (${quand}), ${o.pour} moteur${o.pour > 1 ? "s" : ""} sur 8 ${o.pour > 1 ? "allaient" : "allait"} dans le sens de ${action} ${art}${paire}${liste(o.noms_pour)}, `
    + `${o.contre} contre${liste(o.noms_contre)}, ${o.neutres} neutre${o.neutres > 1 ? "s" : ""}`;
  if (o.nd) t += `, ${o.nd} non disponible${o.nd > 1 ? "s" : ""}`;
  return t + "." + (theme?.titre && theme.titre !== "n/d" ? ` Thème du jour : ${theme.titre}.` : "");
}

export function confrontation(o, pnlEur) {
  if (!o) return null;
  const ctx = o.pour > o.contre ? "favorable" : o.contre > o.pour ? "défavorable" : "partagé";
  const v = nombreFr(pnlEur);
  if (v == null) return `Contexte ${ctx}, résultat non renseigné.`;
  const res = v > 0 ? "positif" : v < 0 ? "négatif" : "nul";
  const pistes = (ctx === "favorable" && v < 0) || (ctx === "défavorable" && v > 0) ? " : regarde les publications pendant le trade" : "";
  return `Contexte ${ctx}, résultat ${res}${pistes}.`;
}

/* Publications des deux devises entre l'entrée et la sortie (sinon jusqu'à la fin de la journée de l'entrée). */
export function publicationsPendant(publicationsParJour, paire, debutUtc, finUtc) {
  const devs = paire.split("/"), fin = finUtc || (String(debutUtc).slice(0, 10) + "T23:59+00:00");
  const sortie = [];
  for (const pubs of publicationsParJour || []) for (const d of devs) for (const e of pubs?.[d] || []) {
    const h = e.h ? isoArchive(e.h) : null;
    if (h && h >= isoArchive(debutUtc) && h <= isoArchive(fin)) sortie.push({ ...e, devise: d, h });
  }
  const vus = new Set();
  return sortie.sort((a, b) => a.h.localeCompare(b.h)).filter(e => { const k = e.h + e.devise + e.ev; if (vus.has(k)) return false; vus.add(k); return true; });
}

/* Position du prix à l'entrée : zones de la veille et de la semaine précédente, RSI, structure H4. */
export function positionPrix(inst, paire) {
  const p = inst?.paires?.[paire], m = inst?.marche?.paires?.[paire];
  if (!p) return null;
  const cours = m?.[0] ?? null, dec = /JPY/.test(paire) ? 2 : 4, z = p.zones || {};
  const situer = (zone, nomZone) => {
    if (!zone || zone[0] == null || cours == null) return `${nomZone} : n/d`;
    const [bas, haut] = zone;
    const pos = cours > haut ? "au-dessus du plus haut" : cours < bas ? "sous le plus bas" : "entre le plus bas et le plus haut";
    return `${nomZone} : ${pos} (${fr(bas, dec)} – ${fr(haut, dec)})`;
  };
  return { cours: cours == null ? "n/d" : fr(cours, dec), cours_du: inst.marche?.cours_du || null,
           lignes: [situer(z.veille, "Veille"), situer(z.semaine, "Semaine précédente"),
                    `RSI 4 h : ${m?.[1] == null ? "n/d" : fr(m[1], 1)} · RSI 1 j : ${p.rsi_1j == null ? "n/d" : fr(p.rsi_1j, 1)}`,
                    `Structure H4 : ${z.h4 || "n/d"}${z.h4_dernier ? ` (dernier ${z.h4_dernier.type} ${z.h4_dernier.sens} le ${String(z.h4_dernier.date).slice(8, 10)}/${String(z.h4_dernier.date).slice(5, 7)})` : ""} · tendance 1 j : ${z.tendance_jour || "n/d"}`] };
}

/* Statistiques selon le contexte : trades avec 5 moteurs ou plus dans leur sens, contre 2 ou moins. */
export function statsContexte(notes) {
  const g = l => { const v = l.map(n => nombreFr(n.resultat?.pnl_eur)).filter(x => x != null);
    return { n: l.length, reussite: v.length ? Math.round(100 * v.filter(x => x > 0).length / v.length) : null }; };
  const lus = (notes || []).filter(n => n.resultat?.statut === "cloturee" && n.lecture && Number.isFinite(n.lecture.pour));
  return { forts: g(lus.filter(n => n.lecture.pour >= 5)), faibles: g(lus.filter(n => n.lecture.pour <= 2)), lus: lus.length };
}
export { nombreFr as nombreFrV4 };
