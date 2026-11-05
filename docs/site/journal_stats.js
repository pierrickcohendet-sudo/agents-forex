/* Journal V3 (lot V8) : statistiques de progression, fonctions PURES (sans DOM ni stockage), testées par
   tests/journal_v3.test.mjs. Calculées sur l'appareil à partir des trades privés de l'utilisateur (exception prévue aux
   règles : rien de ceci n'est une donnée publiée). Les phrases suivent les chiffres ; aucune conclusion écrite d'avance. */
import { migrer, nombreFr } from "./journal_logique.js";

export const SEANCES = ["Asie", "Londres", "New York"];
export const MIN_GROUPE = 5;
const JOURS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];

/* Séance déduite de l'heure (UTC) de l'entrée : mêmes heures que la technique Python (Asie 00-08, Londres 07-16,
   New York 12-21 UTC) ; le chevauchement va à la séance qui ouvre (Londres dès 07:00, New York dès 12:00). */
export function seanceDe(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return null;
  const h = d.getUTCHours();
  return h >= 12 && h < 21 ? "New York" : h >= 7 && h < 12 ? "Londres" : "Asie";
}

/* Le trade va-t-il dans le sens du dollar du thème ? « Dollar haussier » : acheter USD (achat de USD/xxx, vente de xxx/USD). */
export function avecLeTheme(paire, sens, directionTheme) {
  const d = String(directionTheme || "");
  const dollar = /Dollar haussier/.test(d) ? 1 : /Dollar baissier/.test(d) ? -1 : 0;
  if (!dollar || !paire || !/^(Achat|Vente)$/.test(sens || "")) return null;
  const [base, cot] = paire.split("/");
  const achatUsd = (base === "USD" && sens === "Achat") || (cot === "USD" && sens === "Vente");
  const venteUsd = (base === "USD" && sens === "Vente") || (cot === "USD" && sens === "Achat");
  if (!achatUsd && !venteUsd) return null;   // paire sans dollar : non classée
  return dollar > 0 ? achatUsd : venteUsd;
}

/* Résultat en R : champ R saisi ; sinon conversion depuis les € quand le risque prévu (€) est connu ; sinon null (n/d). */
export function resultatR(n) {
  const r = nombreFr(n?.resultat?.r);
  if (r !== null) return r;
  const eur = nombreFr(n?.resultat?.pnl_eur), risque = nombreFr(n?.plan?.risque_eur ?? n?.stats?.risque_eur);
  return eur !== null && risque ? Math.round(eur / Math.abs(risque) * 100) / 100 : null;
}

/* Entrée -> trade normalisé (clôturé seulement). */
export function versTrade(n0) {
  const n = migrer(n0);
  if (!n || n.resultat?.statut !== "cloturee") return null;
  const iso = n.date_heure || n.cree_le, s = n.stats || {};
  return {
    id: n.id, d: String(iso).slice(0, 10), iso, p: n.paire, sens: s.sens || n.sens || null,
    sess: s.seance || seanceDe(iso), conf: s.confluences ?? n.compteur?.pour ?? null,
    theme: s.avec_theme ?? null, r: resultatR(n), eur: nombreFr(n.resultat?.pnl_eur),
  };
}

const moyenne = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
const arrondi = (v, d = 2) => v == null ? null : Math.round(v * 10 ** d) / 10 ** d;

export function groupe(trades) {
  const avecR = trades.filter(t => t.r !== null);
  return { n: avecR.length, reussite: avecR.length ? Math.round(100 * avecR.filter(t => t.r > 0).length / avecR.length) : null,
           moyenne: arrondi(moyenne(avecR.map(t => t.r))), total: arrondi(avecR.reduce((a, t) => a + t.r, 0), 1) };
}

/* Tous les chiffres de la page, triés par date. */
export function statistiques(trades0) {
  const trades = [...trades0].filter(Boolean).sort((a, b) => String(a.iso).localeCompare(String(b.iso)));
  const avecR = trades.filter(t => t.r !== null);
  const gains = avecR.filter(t => t.r > 0).reduce((a, t) => a + t.r, 0), pertes = -avecR.filter(t => t.r < 0).reduce((a, t) => a + t.r, 0);
  let serie = 0;
  const dernier = avecR[avecR.length - 1];
  for (let i = avecR.length - 1; i >= 0 && dernier && (avecR[i].r > 0) === (dernier.r > 0); i--) serie++;
  let cumul = 0;
  const courbe = avecR.map(t => ({ d: t.d, r: arrondi(cumul += t.r) }));
  const eur = trades.map(t => t.eur).filter(v => v !== null);
  const parPaire = {};
  for (const t of avecR) parPaire[t.p] = arrondi((parPaire[t.p] || 0) + t.r, 1);
  return {
    n: trades.length, n_r: avecR.length, sans_r: trades.length - avecR.length,
    total_r: arrondi(avecR.reduce((a, t) => a + t.r, 0), 1), total_eur: eur.length ? arrondi(eur.reduce((a, b) => a + b, 0)) : null,
    reussite: avecR.length ? Math.round(100 * avecR.filter(t => t.r > 0).length / avecR.length) : null,
    gagnants: avecR.filter(t => t.r > 0).length,
    r_moyen: arrondi(moyenne(avecR.map(t => t.r))),
    facteur_profit: pertes > 0 ? arrondi(gains / pertes) : gains > 0 ? Infinity : null,
    serie: dernier ? { n: serie, gagnante: dernier.r > 0, dernier: dernier.d } : null,
    courbe,
    par_paire: Object.entries(parPaire).sort((a, b) => b[1] - a[1]),
    par_seance: SEANCES.map(s => [s, groupe(avecR.filter(t => t.sess === s))]),
    par_jour: [1, 2, 3, 4, 5].map(j => [JOURS[j], groupe(avecR.filter(t => new Date(t.d + "T12:00:00Z").getUTCDay() === j))]),
    constats: constats(avecR),
  };
}

const pct = v => `${v} %`;
const r2 = v => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} R`;
const pasAssez = (a, b) => `Pas encore assez de trades (${a} et ${b} ; il en faut ${MIN_GROUPE} de chaque côté pour comparer).`;

/* 4 constats : thème, confluences, séance, discipline. Chaque phrase dit ce que montrent les chiffres, rien de plus. */
export function constats(avecR) {
  const avec = groupe(avecR.filter(t => t.theme === true)), contre = groupe(avecR.filter(t => t.theme === false));
  let theme;
  if (avec.n < MIN_GROUPE || contre.n < MIN_GROUPE) theme = { titre: "Avec ou contre le thème du jour", chiffre: null, texte: pasAssez(avec.n, contre.n), avec, contre };
  else {
    const ecart = avec.reussite - contre.reussite;
    theme = { titre: Math.abs(ecart) <= 5 ? "Le thème du jour ne change pas ta réussite" : ecart > 0 ? "Tu réussis mieux avec le thème du jour" : "Tu réussis mieux contre le thème du jour",
              chiffre: `${pct(avec.reussite)} contre ${pct(contre.reussite)}`, avec, contre,
              texte: `Avec le thème : ${pct(avec.reussite)} de réussite sur ${avec.n} trades (${r2(avec.moyenne)} en moyenne). Contre : ${pct(contre.reussite)} sur ${contre.n} trades (${r2(contre.moyenne)}).` };
  }
  const c4 = groupe(avecR.filter(t => t.conf !== null && t.conf >= 4)), c1 = groupe(avecR.filter(t => t.conf !== null && t.conf <= 1));
  const conf = c4.n < MIN_GROUPE || c1.n < MIN_GROUPE
    ? { titre: "Confluences", chiffre: null, texte: pasAssez(c4.n, c1.n) }
    : { titre: "Confluences", chiffre: `${pct(c4.reussite)} contre ${pct(c1.reussite)}`,
        texte: `Avec 4 confluences ou plus, ta réussite est de ${pct(c4.reussite)} (${c4.n} trades) ; avec 0 ou 1, elle est de ${pct(c1.reussite)} (${c1.n} trades).` };
  const ses = SEANCES.map(s => [s, groupe(avecR.filter(t => t.sess === s))]).filter(([, g]) => g.n >= MIN_GROUPE).sort((a, b) => b[1].moyenne - a[1].moyenne);
  const seance = ses.length < 2
    ? { titre: "Séance", chiffre: null, texte: `Pas encore assez de trades : il faut ${MIN_GROUPE} trades dans au moins deux séances.` }
    : { titre: "Séance", chiffre: `${r2(ses[0][1].moyenne)} contre ${r2(ses[ses.length - 1][1].moyenne)}`,
        texte: `${ses[0][0]} est ta meilleure séance en R moyen (${ses[0][1].n} trades) ; ${ses[ses.length - 1][0]} est la moins bonne (${ses[ses.length - 1][1].n} trades).` };
  const pertes = avecR.filter(t => t.r < 0), reduites = pertes.filter(t => t.r > -1), pleines = pertes.filter(t => t.r <= -1);
  const discipline = pertes.length < MIN_GROUPE
    ? { titre: "Discipline", chiffre: null, texte: `Pas encore assez de pertes pour juger (${pertes.length} ; il en faut ${MIN_GROUPE}).` }
    : { titre: "Discipline", chiffre: `${reduites.length} perte${reduites.length > 1 ? "s" : ""} réduite${reduites.length > 1 ? "s" : ""} sur ${pertes.length}`,
        texte: `${reduites.length} de tes ${pertes.length} pertes sont restées au-dessus de −1 R (sortie avant l'invalidation complète) ; `
             + `${pleines.length} ont atteint −1 R ou plus.` + (pleines.some(t => t.r < -1) ? " Certaines dépassent −1 R : le risque prévu n'a pas été tenu." : "") };
  return [theme, conf, seance, discipline];
}

/* Mois « AAAA-MM » : R net par jour. */
export function calendrierR(trades, mois) {
  const jours = {};
  for (const t of trades) if (t.r !== null && t.d.startsWith(mois)) jours[t.d] = arrondi((jours[t.d] || 0) + t.r, 1);
  return jours;
}

/* Trades d'exemple (mode démonstration seulement, jamais mélangés aux vrais) : générateur déterministe de la maquette. */
export function exemples(fin = new Date()) {
  let seed = 7; const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
  const P = ["USD/JPY", "EUR/USD", "GBP/USD", "AUD/USD", "USD/CAD", "USD/CHF"], o = [];
  const debut = new Date(fin.getTime() - 35 * 864e5);
  for (let d = new Date(debut); d <= fin; d = new Date(d.getTime() + 864e5)) {
    if (d.getUTCDay() === 0 || d.getUTCDay() === 6 || rnd() < .12) continue;
    const conf = Math.floor(rnd() * 6), theme = rnd() < .7, sess = SEANCES[rnd() < .2 ? 0 : rnd() < .6 ? 1 : 2];
    const pw = .22 + conf * .08 + (theme ? .2 : -.12) + (sess === "Asie" ? -.15 : sess === "Londres" ? .08 : 0);
    const win = rnd() < pw, r = win ? Math.round((1 + rnd() * 1.8) * 10) / 10 : -Math.round((rnd() < .8 ? 1 : .5) * 10) / 10;
    const iso = d.toISOString().slice(0, 10) + "T12:00:00Z";
    o.push({ id: "ex-" + o.length, d: iso.slice(0, 10), iso, p: P[Math.floor(rnd() * P.length)], sens: rnd() < .5 ? "Achat" : "Vente", sess, conf, theme, r, eur: Math.round(r * 100), exemple: true });
  }
  return o;
}
