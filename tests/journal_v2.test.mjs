// Journal V2 (lot V6) : migration V1, bilan mensuel, sélection « peut toucher mon scénario », .ics. Lancé par
// tests/test_journal_v2.py (node), sans navigateur ni réseau.
import assert from "node:assert/strict";
import { migrer, bilanMensuel, grilleMois, peutToucher, ics, compter, performance, finDeSemaine, suggestions } from "../docs/site/journal_logique.js";

// --- migration des notes V1 sans perte
const v1 = { id: "a", cree_le: "2026-10-06T09:00:00Z", modifie_le: "2026-10-06T09:00:00Z", paire: "EUR/USD", unites: ["4h"],
             biais: "haussier", texte: "Rebond sur support", etiquettes: ["range"], checklist: ["biais"],
             images: [{ id: "i1", unite: "4h", largeur: 800, hauteur: 600, blob: "B" }, { id: "i2", unite: "30min", blob: "C" }],
             instantane: { theme: "x" } };
const m = migrer(v1);
assert.equal(m.version, 2);
assert.equal(m.contexte, "Rebond sur support");
assert.deepEqual(m.captures.map(c => c.unites), [["4H"], ["30M"]]);
assert.equal(m.captures[0].blob, "B");
for (const k of Object.keys(v1)) assert.deepEqual(m[k], v1[k], `champ V1 perdu : ${k}`);
assert.equal(m.resultat.statut, "analyse");
assert.strictEqual(migrer(m), m);                                         // idempotente

// --- bilan mensuel (entrées clôturées seulement, filtre de paire)
const e = (paire, jour, pnl, r, statut = "cloturee") => ({ version: 2, id: `${paire}${jour}`, paire, date_heure: `2026-10-${jour}T10:00:00Z`,
  resultat: { statut, pnl_eur: pnl, pips: null, r }, elements: [{ avis: "pour" }, { avis: "pour" }, { avis: "contre" }, { avis: null }] });
const entrees = [e("EUR/USD", "06", "85", "1,7"), e("USD/JPY", "08", "−40", "-0.8"), e("EUR/USD", "22", "-35", "-1"),
                 e("AUD/USD", "22", "48", "1.2"), e("NZD/USD", "28", "95", "2"), e("GBP/USD", "14", "500", "3", "ouverte"), v1];
const b = bilanMensuel(entrees, "2026-10");
assert.equal(b.total_eur, 153);
assert.equal(b.clotures, 5);
assert.equal(b.gagnants_pct, 60);
assert.equal(b.r_moyen, 0.62);
assert.deepEqual(b.meilleure, { paire: "NZD/USD", eur: 95 });
assert.deepEqual(b.pire, { paire: "USD/JPY", eur: -40 });
assert.equal(bilanMensuel(entrees, "2026-10", "EUR/USD").total_eur, 50);
assert.equal(bilanMensuel(entrees, "2026-11").clotures, 0);
const g = grilleMois(entrees, "2026-10");
assert.equal(g[0].jours.filter(j => j === null).length, 3);                // octobre 2026 commence un jeudi
const j22 = g.flatMap(s => s.jours).find(j => j && j.iso === "2026-10-22");
assert.equal(j22.net, 13);
assert.equal(g.find(s => s.jours.some(j => j && j.iso === "2026-10-06")).total, 85 - 40);

// --- compteur et préparation de l'onglet Performance
assert.deepEqual(compter(entrees[0].elements), { pour: 2, contre: 1 });
assert.deepEqual(performance(entrees[0]), { pour: 2, contre: 1, pnl_eur: "85", r: "1,7", paire: "EUR/USD", date: "2026-10-06" });
assert.equal(performance(entrees[5]), null);

// --- « peut toucher mon scénario »
const agenda = { jours: [{ evenements: [
  { iso_utc: "2026-11-03T13:00:00Z", devise: "USD", evenement: "ISM des services", impact: "moyen", type: "Chiffre", evenement_en: "ISM Services PMI" },
  { iso_utc: "2026-11-04T14:00:00Z", devise: "EUR", evenement: "Discours de Lagarde (BCE)", impact: "moyen", type: "Discours" },
  { iso_utc: "2026-11-05T13:30:00Z", devise: "USD", evenement: "Inscriptions au chômage", impact: "moyen", type: "Chiffre" },
  { iso_utc: "2026-11-06T13:30:00Z", devise: "USD", evenement: "Emploi américain (NFP)", impact: "fort", type: "Chiffre" },
  { iso_utc: "2026-11-06T13:30:00Z", devise: "JPY", evenement: "Salaires", impact: "fort", type: "Chiffre" },
  { iso_utc: "2026-11-10T13:30:00Z", devise: "USD", evenement: "CPI", impact: "fort", type: "Chiffre" },
  { iso_utc: "2026-11-02T08:00:00Z", devise: "EUR", evenement: "PMI passé", impact: "fort", type: "Chiffre" }] }] };
const maintenant = new Date("2026-11-02T10:40:00Z");
const horizon = finDeSemaine(maintenant);
assert.equal(horizon, "2026-11-06T22:00:00Z");
const els = [{ avis: "pour", mots: ["chômage"] }, { avis: null, mots: ["ISM"] }];
const t = peutToucher(agenda, "EUR/USD", els, horizon, maintenant);
assert.deepEqual(t.map(x => x.evenement), ["ISM des services", "Discours de Lagarde (BCE)", "Inscriptions au chômage", "Emploi américain (NFP)"]);
assert.deepEqual(t.map(x => x.touche), [false, true, true, true]);          // ISM : élément non coché -> à surveiller
assert.deepEqual(t.map(x => x.raison), [null, "banque centrale", "lié à un élément coché", "impact fort"]);

// --- .ics
const fichier = ics(t.filter(x => x.touche), "EUR/USD", maintenant);
assert.ok(fichier.startsWith("BEGIN:VCALENDAR\r\nVERSION:2.0"));
assert.equal((fichier.match(/BEGIN:VEVENT/g) || []).length, 3);
assert.ok(fichier.includes("DTSTART:20261106T133000Z") && fichier.includes("DTEND:20261106T140000Z"));
assert.ok(fichier.includes("TRIGGER:-PT30M") && fichier.endsWith("END:VCALENDAR\r\n"));

// --- suggestions : 5 au plus, chacune avec sa source
const profil = { devises: [{ devise: "EUR", etat: { valeur: "Sans direction", raison: "Aucun signal net." },
  moteur: { dominant: { libelle: "Indice dollar large (Fed)", r60: -0.73, n60: 60 } },
  banque_centrale: { derniere: { texte: "maintien à 2,65 %", date: "2026-10-29" } } }] };
const sg = suggestions("EUR", { profil, agenda: { jours: Array(5).fill({ evenements: [{ devise: "EUR", evenement: "PMI", date_paris: "2026-11-02", ecart: { sens: "au-dessus", texte: "au-dessus (+0,5)" } }] }) } });
assert.equal(sg.length, 5);
assert.ok(sg.every(x => x.source && x.texte && x.avis === null));
console.log("journal V2 : tous les tests passent");
