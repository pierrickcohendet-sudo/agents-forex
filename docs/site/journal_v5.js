/* Lot V11 — Journal V5 : fonctions pures (sans DOM ni réseau), testées par tests/journal_v5.test.mjs.
   Statistiques de l'accueil, calendrier par semaines (5 jours ouvrés + week-end + total), courbe cumulée, groupes par
   semaine et recherche de la vue liste, photos (ordre, légendes, unités, couverture), migration V4 -> V5 qui reprend les
   images collées dans l'analyse V10 dans « Photos », sans doublon. Calculs sur les trades privés, sur l'appareil. */
import { migrerV4, texteBrut, minutesEntre } from "./journal_v4.js";
import { nombreFr } from "./journal_logique.js";

export const UNITES_PHOTO = ["M5", "M15", "M30", "H1", "H4", "D1", "W1"];
export const FAVORABLE = 4;          // contexte favorable : 4 moteurs ou plus dans le sens du trade
const arrondi = (v, d = 2) => v == null ? null : Math.round(v * 10 ** d) / 10 ** d;
export const jourDe = n => String(n?.entree_locale || n?.date_heure || n?.cree_le || "").slice(0, 10);
export const eurDe = n => nombreFr(n?.resultat?.pnl_eur);
export const rDe = n => nombreFr(n?.resultat?.r);
/* Une entrée sans résultat (ni € ni R) : « résultat à compléter ». */
export const aCompleter = n => eurDe(n) == null && rDe(n) == null;
/* Gagnant / perdant : en € si saisi, sinon en R. */
const signeResultat = n => { const e = eurDe(n); return e != null ? Math.sign(e) : rDe(n) != null ? Math.sign(rDe(n)) : null; };

/* ------------------------------------------------------------------ migration V4 -> V5 */
export function migrerV5(n0) {
  if (!n0) return n0;
  if (n0.version === 5) return n0;
  const n = migrerV4(n0);
  const photos = [], vus = new Set();
  for (const b of n.analyse?.blocs || []) {          // images de l'analyse V10 : légende et unité reprises
    if (b.type !== "image" || !b.capture || vus.has(b.capture)) continue;
    vus.add(b.capture); photos.push({ capture: b.capture, legende: b.legende || "", unite: UNITES_PHOTO.includes(b.unite) ? b.unite : uniteV2([b.unite]) });
  }
  for (const c of n.captures || []) {                // captures V2 / V3 (ou collées sans bloc) : à la suite
    if (vus.has(c.id)) continue;
    vus.add(c.id); photos.push({ capture: c.id, legende: c.legende || "", unite: uniteV2(c.unites) });
  }
  return { ...n, version: 5, photos, setup: n.setup || [], couverture: n.couverture || null };
}
function uniteV2(u) {
  const t = String((u || [])[0] || "").replace(/\s/g, "").toUpperCase();
  return { "30MIN": "M30", "4H": "H4", "1J": "D1", "1H": "H1", "M30": "M30", "H4": "H4", "D1": "D1", "H1": "H1" }[t] || null;
}

/* ------------------------------------------------------------------ photos */
/* Photos dont la capture existe encore, dans leur ordre. */
export function photosDe(n) {
  const ids = new Set((n?.captures || []).map(c => c.id));
  return (n?.photos || []).filter(p => ids.has(p.capture));
}
export function couvertureDe(n) {
  const ph = photosDe(n);
  return ph.find(p => p.capture === n?.couverture)?.capture || ph[0]?.capture || null;
}
export function deplacer(photos, de, vers) {
  const l = [...photos]; if (de < 0 || de >= l.length || vers < 0 || vers >= l.length) return l;
  const [x] = l.splice(de, 1); l.splice(vers, 0, x); return l;
}
export function legender(photos, capture, legende) { return photos.map(p => p.capture === capture ? { ...p, legende: String(legende ?? "") } : p); }
export function changerUnite(photos, capture, unite) { return photos.map(p => p.capture === capture ? { ...p, unite: UNITES_PHOTO.includes(unite) ? unite : null } : p); }
/* Ajoute des captures nouvelles (images collées dans l'analyse ou dans Photos) à la fin, sans doublon. */
export function synchroniser(photos, captures, blocs) {
  const l = [...(photos || [])], vus = new Set(l.map(p => p.capture));
  for (const b of blocs || []) if (b.type === "image" && b.capture && !vus.has(b.capture)) { vus.add(b.capture); l.push({ capture: b.capture, legende: b.legende || "", unite: b.unite || null }); }
  for (const c of captures || []) if (!vus.has(c.id)) { vus.add(c.id); l.push({ capture: c.id, legende: "", unite: null }); }
  const ids = new Set((captures || []).map(c => c.id));
  return l.filter(p => ids.has(p.capture));
}
/* Suppression d'une photo : la capture et les blocs image qui la montrent disparaissent aussi. */
export function supprimerPhoto(n, capture) {
  return { ...n, photos: (n.photos || []).filter(p => p.capture !== capture), captures: (n.captures || []).filter(c => c.id !== capture),
           couverture: n.couverture === capture ? null : n.couverture,
           analyse: { ...(n.analyse || {}), blocs: (n.analyse?.blocs || []).filter(b => !(b.type === "image" && b.capture === capture)) } };
}

/* ------------------------------------------------------------------ accueil : 6 indicateurs */
export function statsAccueil(notes, mois) {
  const l = (notes || []).filter(n => jourDe(n).startsWith(mois) && n.resultat?.statut === "cloturee" && !aCompleter(n));
  const eurs = l.map(eurDe).filter(v => v != null), rs = l.map(rDe).filter(v => v != null);
  const gains = eurs.filter(v => v > 0), pertes = eurs.filter(v => v < 0);
  const gagnants = l.filter(n => signeResultat(n) > 0).length;
  const reussite = a => { const s = a.map(signeResultat).filter(v => v != null); return s.length ? Math.round(100 * s.filter(v => v > 0).length / s.length) : null; };
  const lus = l.filter(n => Number.isFinite(n.lecture?.pour));
  const fav = lus.filter(n => n.lecture.pour >= FAVORABLE), autres = lus.filter(n => n.lecture.pour < FAVORABLE);
  const somme = a => a.reduce((x, y) => x + y, 0);
  return {
    n: l.length, gagnants, reussite: reussite(l),
    eur: eurs.length ? arrondi(somme(eurs)) : null, r: rs.length ? arrondi(somme(rs), 1) : null,
    facteur: pertes.length ? arrondi(somme(gains) / -somme(pertes)) : gains.length ? Infinity : null,
    gain_moyen: gains.length ? arrondi(somme(gains) / gains.length, 0) : null,
    perte_moyenne: pertes.length ? arrondi(somme(pertes) / pertes.length, 0) : null,
    favorable: { n: fav.length, reussite: reussite(fav) }, autres: { n: autres.length, reussite: reussite(autres) },
    a_completer: (notes || []).filter(n => jourDe(n).startsWith(mois) && aCompleter(n)).length,
  };
}

/* ------------------------------------------------------------------ calendrier compact : semaines du mois */
const iso = d => d.toISOString().slice(0, 10);
export function semainesMois(notes, mois) {
  const [y, m] = mois.split("-").map(Number);
  const premier = new Date(Date.UTC(y, m - 1, 1)), dernier = new Date(Date.UTC(y, m, 0));
  const debut = new Date(premier.getTime() - ((premier.getUTCDay() + 6) % 7) * 864e5);
  const parJour = {};
  for (const n of notes || []) { const j = jourDe(n); (parJour[j] = parJour[j] || []).push(n); }
  const semaines = [];
  for (let d = debut; d <= dernier; d = new Date(d.getTime() + 7 * 864e5)) {
    const jours = [];
    let total = 0, nb = 0, avec = 0;
    for (let i = 0; i < 7; i++) {
      const x = new Date(d.getTime() + i * 864e5), j = iso(x), ts = parJour[j] || [], dans = x.getUTCMonth() === m - 1;
      const eurs = ts.map(eurDe).filter(v => v != null), v = eurs.length ? arrondi(eurs.reduce((a, b) => a + b, 0)) : null;
      jours.push({ iso: j, jour: x.getUTCDate(), hors_mois: !dans, week_end: i > 4, n: ts.length, eur: v,
                   classe: !ts.length ? "" : v == null ? "neutre" : v > 0 ? "gain" : v < 0 ? "perte" : "neutre" });
      if (dans) { nb += ts.length; if (v != null) { total += v; avec++; } }
    }
    semaines.push({ lundi: iso(d), jours, total: { n: nb, eur: avec ? arrondi(total) : null } });
  }
  return semaines;
}

/* Courbe de résultat cumulé en € (trades du mois, dans l'ordre). */
export function courbeCumul(notes, mois) {
  const l = (notes || []).filter(n => jourDe(n).startsWith(mois) && eurDe(n) != null)
    .sort((a, b) => String(a.entree_utc || a.date_heure).localeCompare(String(b.entree_utc || b.date_heure)));
  let c = 0; return [0, ...l.map(n => arrondi(c += eurDe(n)))];
}

/* ------------------------------------------------------------------ vue liste */
export function rechercher(notes, q) {
  const t = String(q || "").trim().toLowerCase();
  if (!t) return [...(notes || [])];
  return (notes || []).filter(n => [n.paire, (n.setup || []).join(" "), texteBrut(n.analyse?.blocs), ...(n.photos || []).map(p => p.legende)]
    .join(" ").toLowerCase().includes(t));
}
export function groupesSemaine(notes) {
  const g = new Map();
  const tri = [...(notes || [])].sort((a, b) => String(b.entree_utc || b.date_heure || jourDe(b)).localeCompare(String(a.entree_utc || a.date_heure || jourDe(a))));
  for (const n of tri) {
    const d = new Date(jourDe(n) + "T12:00:00Z"); if (isNaN(d)) continue;
    const lundi = iso(new Date(d.getTime() - ((d.getUTCDay() + 6) % 7) * 864e5));
    if (!g.has(lundi)) g.set(lundi, []);
    g.get(lundi).push(n);
  }
  return [...g.entries()].map(([lundi, trades]) => { const e = trades.map(eurDe).filter(v => v != null);
    return { lundi, trades, total: e.length ? arrondi(e.reduce((a, b) => a + b, 0)) : null }; });
}
export function filtrerFil(notes, filtre) {
  if (!filtre || filtre === "Tous") return [...(notes || [])];
  if (filtre === "Gagnants") return (notes || []).filter(n => signeResultat(n) > 0);
  if (filtre === "Perdants") return (notes || []).filter(n => signeResultat(n) < 0);
  return (notes || []).filter(n => n.paire === filtre);
}
/* Résumé d'une entrée pour les cartes : premier paragraphe de l'analyse. */
export function resume(n, max = 180) {
  const b = (n?.analyse?.blocs || []).find(x => ["paragraphe", "puce", "citation", "encadre"].includes(x.type) && String(x.texte || "").replace(/<[^>]+>/g, "").trim());
  const t = b ? String(b.texte).replace(/<[^>]+>/g, "").trim() : String(n?.contexte || "").trim();
  return t.length > max ? t.slice(0, max - 1) + "…" : t;
}
export const dureeMin = n => minutesEntre(n?.entree_utc, n?.sortie_utc);
