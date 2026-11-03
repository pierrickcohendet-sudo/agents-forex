/* Journal V2 (lot V6) : logique pure, sans DOM ni stockage (testée par tests/journal_v2.test.mjs).
   Migration des notes V1, bilan mensuel, sélection des évènements « peut toucher mon scénario », fichier .ics,
   éléments confluents proposés à partir des données du jour. Jamais un ordre d'achat ou de vente. */

export const UNITES_V2 = ["1M", "5M", "15M", "30M", "1H", "4H", "1D", "1W"];
const UNITE_V1 = { "30min": "30M", "4h": "4H", "1j": "1D" };
export const STATUTS = { analyse: "Analyse seulement", ouverte: "Position ouverte", cloturee: "Clôturée" };

/* V1 -> V2 sans perte : tous les champs V1 restent ; les images deviennent des captures à unités multiples. */
export function migrer(n) {
  if (!n || n.version === 2) return n;
  const captures = (n.images || []).map(im => ({ ...im, unites: im.unites || (im.unite ? [UNITE_V1[im.unite] || im.unite] : []) }));
  return {
    ...n, version: 2, migre_de: 1,
    date_heure: n.date_heure || n.cree_le,
    contexte: n.contexte ?? n.texte ?? "",
    captures,
    elements: n.elements || [],
    compteur: n.compteur || { pour: 0, contre: 0 },
    evenements_suivis: n.evenements_suivis || [],
    resultat: n.resultat || { statut: "analyse", pnl_eur: null, pips: null, r: null },
  };
}

export function compter(elements) {
  const c = { pour: 0, contre: 0 };
  for (const e of elements || []) if (e.avis === "pour" || e.avis === "contre") c[e.avis]++;
  return c;
}

/* Préparation de l'onglet Performance : pour / contre et résultat de chaque entrée clôturée. */
export function performance(n) {
  if (n?.resultat?.statut !== "cloturee") return null;
  const c = compter(n.elements);
  return { pour: c.pour, contre: c.contre, pnl_eur: n.resultat.pnl_eur ?? null, r: n.resultat.r ?? null, paire: n.paire,
           date: String(n.date_heure || n.cree_le).slice(0, 10) };
}

export const nombreFr = t => { if (t === null || t === undefined || t === "") return null; const v = Number(String(t).replace(/\s/g, "").replace("−", "-").replace(",", ".")); return Number.isFinite(v) ? v : null; };
const jourDe = n => String(n.date_heure || n.cree_le || "").slice(0, 10);

/* Bilan d'un mois (« AAAA-MM ») : entrées clôturées seulement ; filtre de paire facultatif. */
export function bilanMensuel(entrees, mois, paire = "") {
  const cl = (entrees || []).map(migrer).filter(n => jourDe(n).startsWith(mois) && n.resultat?.statut === "cloturee" && (!paire || n.paire === paire));
  const pnl = cl.map(n => nombreFr(n.resultat.pnl_eur)).filter(v => v !== null);
  const rs = cl.map(n => nombreFr(n.resultat.r)).filter(v => v !== null);
  const parPaire = {};
  for (const n of cl) { const v = nombreFr(n.resultat.pnl_eur); if (v !== null) parPaire[n.paire] = (parPaire[n.paire] || 0) + v; }
  const tri = Object.entries(parPaire).sort((a, b) => b[1] - a[1]);
  return {
    total_eur: pnl.length ? Math.round(pnl.reduce((a, b) => a + b, 0) * 100) / 100 : 0,
    clotures: cl.length,
    gagnants_pct: pnl.length ? Math.round(100 * pnl.filter(v => v > 0).length / pnl.length) : null,
    r_moyen: rs.length ? Math.round(100 * rs.reduce((a, b) => a + b, 0) / rs.length) / 100 : null,
    meilleure: tri.length ? { paire: tri[0][0], eur: tri[0][1] } : null,
    pire: tri.length ? { paire: tri[tri.length - 1][0], eur: tri[tri.length - 1][1] } : null,
  };
}

/* Grille du mois : semaines (lundi -> dimanche), chaque jour avec ses entrées et son résultat net, total par semaine. */
export function grilleMois(entrees, mois, paire = "") {
  const [a, m] = mois.split("-").map(Number);
  const premier = new Date(Date.UTC(a, m - 1, 1));
  const decal = (premier.getUTCDay() + 6) % 7;
  const nbJours = new Date(Date.UTC(a, m, 0)).getUTCDate();
  const parJour = {};
  for (const n of (entrees || []).map(migrer)) {
    if (paire && n.paire !== paire) continue;
    const j = jourDe(n);
    if (j.startsWith(mois)) (parJour[j] = parJour[j] || []).push(n);
  }
  const semaines = [];
  let sem = [];
  for (let k = 0; k < decal; k++) sem.push(null);
  for (let d = 1; d <= nbJours; d++) {
    const iso = `${mois}-${String(d).padStart(2, "0")}`;
    const ns = parJour[iso] || [];
    const vals = ns.filter(n => n.resultat?.statut === "cloturee").map(n => nombreFr(n.resultat.pnl_eur)).filter(v => v !== null);
    sem.push({ jour: d, iso, entrees: ns, net: vals.length ? Math.round(vals.reduce((x, y) => x + y, 0) * 100) / 100 : null });
    if (sem.length === 7) { semaines.push(sem); sem = []; }
  }
  if (sem.length) { while (sem.length < 7) sem.push(null); semaines.push(sem); }
  return semaines.map(s => ({ jours: s, total: (() => { const v = s.filter(j => j && j.net !== null).map(j => j.net); return v.length ? Math.round(v.reduce((x, y) => x + y, 0) * 100) / 100 : null; })() }));
}

/* Horizon par défaut : vendredi de la semaine (23:59 heure de Paris ~ 22:00 UTC). */
export function finDeSemaine(maintenant = new Date()) {
  const d = new Date(maintenant);
  const ajout = (5 - d.getUTCDay() + 7) % 7;
  d.setUTCDate(d.getUTCDate() + ajout);
  return `${d.toISOString().slice(0, 10)}T22:00:00Z`;
}

const BANQUES = { USD: /fed|fomc|powell/i, EUR: /bce|ecb|lagarde/i, GBP: /boe|bailey|mpc/i, JPY: /boj|ueda/i, CHF: /bns|snb/i,
                  CAD: /boc|macklem/i, AUD: /rba|bullock/i, NZD: /rbnz|orr/i, CNY: /pboc|lpr/i };

/* Évènements de l'Agenda entre maintenant et l'horizon, pour les deux devises de la paire ; badge « Peut toucher mon
   scénario » : décision ou discours de leur banque centrale, publication d'impact fort, ou lien avec un élément coché. */
export function peutToucher(agenda, paire, elements, horizon, maintenant = new Date()) {
  const [b, c] = String(paire || "").split("/");
  const coches = (elements || []).filter(e => e.avis === "pour" || e.avis === "contre");
  const mots = coches.flatMap(e => e.mots || []).map(m => String(m).toLowerCase()).filter(m => m.length > 2);
  const debut = maintenant.toISOString();
  const sortie = [];
  for (const j of agenda?.jours || []) for (const e of j.evenements || []) {
    if (![b, c].includes(e.devise) || !e.iso_utc || e.iso_utc < debut || e.iso_utc > horizon) continue;
    const bc = e.type === "Réunion BC" || (e.type === "Discours" && BANQUES[e.devise]?.test(`${e.evenement} ${e.evenement_en || ""}`));
    const lie = mots.some(m => String(e.evenement).toLowerCase().includes(m) || String(e.evenement_en || "").toLowerCase().includes(m));
    const raison = bc ? "banque centrale" : e.impact === "fort" ? "impact fort" : lie ? "lié à un élément coché" : null;
    sortie.push({ id: `${e.iso_utc}|${e.devise}|${e.evenement}`, iso_utc: e.iso_utc, date_paris: e.date_paris, heure_paris: e.heure_paris,
                  devise: e.devise, evenement: e.evenement, impact: e.impact, touche: !!raison, raison });
  }
  return sortie.sort((x, y) => x.iso_utc.localeCompare(y.iso_utc));
}

/* Fichier .ics (RFC 5545) généré dans le navigateur : un VEVENT de 30 min par évènement, rappel 30 min avant. */
export function ics(evenements, paire, maintenant = new Date()) {
  const f = iso => iso.replace(/[-:]/g, "").replace(/\.\d{3}/, "").replace(/(\d{8}T\d{4})Z$/, "$100Z");
  const echap = t => String(t).replace(/\\/g, "\\\\").replace(/[,;]/g, m => `\\${m}`).replace(/\n/g, "\\n");
  const stamp = f(maintenant.toISOString());
  const lignes = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FX Desk//Journal V2//FR", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"];
  for (const e of evenements) {
    const debut = new Date(e.iso_utc);
    const fin = new Date(debut.getTime() + 30 * 60000);
    lignes.push("BEGIN:VEVENT", `UID:${echap(e.id).replace(/[^\w|.-]/g, "")}@fxdesk`, `DTSTAMP:${stamp}`,
                `DTSTART:${f(debut.toISOString())}`, `DTEND:${f(fin.toISOString())}`,
                `SUMMARY:${echap(`${e.devise} ${e.evenement}`)}`,
                `DESCRIPTION:${echap(`Peut toucher mon scénario ${paire || ""} (${e.raison || "à surveiller"}). Aide à la décision, pas un ordre.`)}`,
                "BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY", `DESCRIPTION:${echap(`${e.devise} ${e.evenement} dans 30 min`)}`, "END:VALARM",
                "END:VEVENT");
  }
  lignes.push("END:VCALENDAR");
  return lignes.join("\r\n") + "\r\n";
}

/* Éléments confluents proposés (5 au plus par devise), chacun avec sa source : état et moteur (profil des devises),
   dernière décision de la banque centrale, publications avec surprise, mécanismes détectés, niveaux techniques. */
export function suggestions(devise, { profil, rapport, agenda, paire } = {}) {
  const s = [];
  const p = (profil?.devises || []).find(x => x.devise === devise);
  if (p) {
    s.push({ texte: `État : ${p.etat.valeur}. ${p.etat.raison}`, source: "Page Devises (profil, calcul Python)" });
    const d = p.moteur?.dominant;
    if (d) s.push({ texte: `Moteur du moment : ${d.libelle} (corrélation ${String(d.r60).replace(".", ",").replace("-", "−")} sur ${d.n60} séances)`,
                    source: "Page Devises (corrélation 60 séances)", mots: [] });
    const bc = p.banque_centrale?.derniere;
    if (bc) s.push({ texte: `Banque centrale : ${bc.texte}`, source: `Décision du ${bc.date.slice(8, 10)}/${bc.date.slice(5, 7)}`, mots: ["décision", "taux"] });
  }
  for (const j of agenda?.jours || []) for (const e of j.evenements || []) {
    if (e.devise === devise && e.ecart && e.ecart.sens !== "conforme" && s.length < 5)
      s.push({ texte: `${e.evenement} ${e.ecart.texte}`, source: `Agenda · ${String(e.date_paris).slice(8, 10)}/${String(e.date_paris).slice(5, 7)}`,
               mots: [String(e.evenement).split(" ")[0]] });
  }
  for (const m of rapport?.lecture?.detectes || []) {
    if (s.length >= 5) break;
    if (new RegExp(`\\b${devise}\\b`).test(`${m.libelle} ${m.lecture || ""}`)) s.push({ texte: m.libelle, source: "Mécanisme détecté (rapport du jour)" });
  }
  const niv = rapport?.technique?.paires?.[paire];
  if (niv && s.length < 5) {
    const n = niv.niveaux || niv;
    const sup = n.support ?? n.supports?.[0]?.niveau, res = n.resistance ?? n.resistances?.[0]?.niveau;
    if (sup != null || res != null) s.push({ texte: `Niveaux techniques ${paire} : support ${sup ?? "n/d"}, résistance ${res ?? "n/d"}`.replace(/(\d)\.(\d)/g, "$1,$2"),
                                             source: "Technique de la paire (calcul Python)" });
  }
  return s.slice(0, 5).map((x, k) => ({ id: `${devise}-${k}`, devise, avis: null, perso: false, mots: x.mots || [], ...x }));
}
