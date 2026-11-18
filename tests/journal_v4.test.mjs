// Lot V10 : Journal V4, fonctions pures (sans DOM ni réseau) : durée, orientation selon le sens du trade, sérialisation
// de l'éditeur par blocs, migration V2 et V3 vers V4, instantané le plus proche avant l'entrée, phrase de synthèse.
import assert from "node:assert/strict";

globalThis.document = { querySelector: () => null, documentElement: { dataset: {} } };
const J = await import("../docs/site/journal_v4.js");
const S = await import("../docs/site/journal_stats.js");

// ---- durée
assert.equal(J.minutesEntre("2026-11-17T13:40:00Z", "2026-11-17T15:55:00Z"), 135);
assert.equal(J.dureeTexte(135), "2 h 15");
assert.equal(J.dureeTexte(45), "45 min");
assert.equal(J.dureeTexte(180), "3 h");
assert.equal(J.dureeTexte(3 * 1440), "3 jours");
assert.equal(J.dureeTexte(1440 + 240), "1 jour 4 h");
assert.equal(J.minutesEntre("2026-11-17T15:00:00Z", "2026-11-17T14:00:00Z"), null);   // sortie avant l'entrée : n/d
assert.equal(J.categorieDuree(30), "moins d'1 h");
assert.equal(J.categorieDuree(600), "dans la journée");
assert.equal(J.ajouterMinutesLocal("2026-11-17T14:40", 135), "2026-11-17T16:55");
assert.equal(J.ajouterMinutesLocal("2026-11-30T22:00", 3 * 1440), "2026-12-03T22:00");

// ---- orientation selon le sens du trade
const M = { 1: { nom: "Thème dominant" }, 2: { nom: "Banques centrales et taux" }, 3: { nom: "Chiffres économiques" }, 4: { nom: "Budgets et dette publique" },
            5: { nom: "Liens entre marchés" }, 6: { nom: "Géopolitique" }, 7: { nom: "Prix et positionnement" }, 8: { nom: "Commerce et flux" } };
const mot = (r, d) => ({ v: 0, raison: r, date: d, source: "test" });
const inst = { moteurs: M, theme: { titre: "Dollar soutenu" },
  devises: { USD: { moteurs: Array.from({ length: 8 }, (_, i) => mot(`usd${i + 1}`, "2026-11-17")) }, JPY: { moteurs: Array.from({ length: 8 }, (_, i) => mot(`jpy${i + 1}`, "2026-11-16")) } },
  paires: { "USD/JPY": { c: [1, 1, 1, 0, 1, -1, 1, null], zones: { veille: [158.86, 159.61, "2026-11-16"], semaine: [157.67, 160.29, "2026-S46"], h4: "baissière" }, rsi_1j: 60.7 } },
  marche: { paires: { "USD/JPY": [159.35, 53.5] }, cours_du: "2026-11-17T13:18+00:00" } };
const achat = J.orienter(inst, "USD/JPY", "Achat");
assert.deepEqual([achat.pour, achat.contre, achat.neutres, achat.nd], [5, 1, 1, 1]);
assert.equal(achat.lignes[5].statut, "contre");
assert.equal(achat.lignes[0].raison, "USD : usd1 · JPY : jpy1");
assert.equal(achat.lignes[0].date, "2026-11-17");
const vente = J.orienter(inst, "USD/JPY", "Vente");
assert.deepEqual([vente.pour, vente.contre], [1, 5]);                    // une vente inverse le sens
assert.equal(J.orienter(inst, "EUR/USD", "Achat"), null);                 // paire absente de l'instantané : n/d
const phrase = J.phraseSynthese(achat, "2026-11-17T14:40", "USD/JPY", "Achat", inst.theme);
assert.equal(phrase, "Au moment de l'entrée (mardi 17/11, 14:40), 5 moteurs sur 8 allaient dans le sens de ton achat d'USD/JPY "
  + "(thème dominant, banques centrales et taux, chiffres économiques, liens entre marchés, prix et positionnement), 1 contre (géopolitique), "
  + "1 neutre, 1 non disponible. Thème du jour : Dollar soutenu.");
assert.equal(J.confrontation(achat, 120), "Contexte favorable, résultat positif.");
assert.equal(J.confrontation(achat, "−45"), "Contexte favorable, résultat négatif : regarde les publications pendant le trade.");
assert.match(J.positionPrix(inst, "USD/JPY").lignes[0], /^Veille : entre le plus bas et le plus haut/);

// ---- publications pendant le trade
const pubs = [{ USD: [{ h: "2026-11-17T13:30+00:00", ev: "Ventes au détail", publie: "0.4%", consensus: "0.3%" },
                      { h: "2026-11-17T19:00+00:00", ev: "Discours", publie: null, consensus: null }], JPY: [] }];
assert.deepEqual(J.publicationsPendant(pubs, "USD/JPY", "2026-11-17T13:40:00.000Z", "2026-11-17T15:55:00.000Z"), []);
assert.equal(J.publicationsPendant(pubs, "USD/JPY", "2026-11-17T13:00:00.000Z", "2026-11-17T15:55:00.000Z")[0].ev, "Ventes au détail");

// ---- instantané le plus proche AVANT l'entrée
const idx = { "2026-11-16": ["2026-11-16T08:51+00:00", "2026-11-16T20:15+00:00"], "2026-11-17": ["2026-11-17T08:52+00:00", "2026-11-17T13:15+00:00", "2026-11-17T14:15+00:00"] };
assert.deepEqual(J.instantaneAvant(idx, "2026-11-17T13:40+00:00"), { jour: "2026-11-17", rang: 1, heure: "2026-11-17T13:15+00:00" });
assert.deepEqual(J.instantaneAvant(idx, "2026-11-17T06:00+00:00"), { jour: "2026-11-16", rang: 1, heure: "2026-11-16T20:15+00:00" });   // veille
assert.equal(J.instantaneAvant(idx, "2026-11-01T10:00+00:00"), null);                                                            // non archivé
assert.equal(J.isoArchive("2026-11-17T13:40:00.000Z"), "2026-11-17T13:40+00:00");

// ---- éditeur par blocs : sérialisation
const blocs = [{ id: "a", type: "titre", texte: "Pourquoi <b>USD/JPY</b>" }, { id: "b", type: "paragraphe", texte: 'Le <strong>2 ans</strong> <script>x</script><a href="javascript:x">lien</a> <a href="https://exemple.org">ok</a>' },
               { id: "c", type: "case", texte: "Relire", coche: 1 }, { id: "d", type: "image", capture: "cap1", legende: "H4", unite: "H4" },
               { id: "e", type: "separateur" }, { id: "f", type: "inconnu", texte: "x" }];
const ser = J.serialiser(blocs);
assert.equal(ser.length, 5);
assert.equal(ser[1].texte, 'Le <b>2 ans</b> xlien <a href="https://exemple.org" target="_blank" rel="noopener">ok</a>');
assert.deepEqual(ser[2], { id: "c", type: "case", texte: "Relire", coche: true });
assert.deepEqual(ser[3], { id: "d", type: "image", capture: "cap1", legende: "H4", unite: "H4" });
assert.deepEqual(J.deserialiser(JSON.stringify(ser)), ser);                 // aller-retour sans perte
assert.deepEqual(J.deserialiser("{pas du json"), []);
assert.equal(J.texteBrut(ser), "Pourquoi USD/JPY\nLe 2 ans xlien ok\nRelire\nH4");
assert.equal(J.blocsDuModele().filter(b => b.type === "titre").length, 4);

// ---- migration V2 et V3 vers V4 : rien n'est perdu
const v2 = { version: 2, id: "n1", cree_le: "2026-11-05T09:00:00Z", date_heure: "2026-11-05T09:00:00Z", paire: "EUR/USD", contexte: "Biais haussier.\n\n- BCE\n- Fed",
             captures: [{ id: "cap1", unites: ["4 h"], largeur: 800 }], elements: [{ texte: "x" }], resultat: { statut: "cloturee", pnl_eur: "50", r: "1" } };
const v3 = { ...v2, id: "n2", stats: { sens: "Vente", theme: "Dollar soutenu", avec_theme: false } };
const m2 = J.migrerV4(v2), m3 = J.migrerV4(v3);
assert.equal(m2.version, 4); assert.equal(m2.migre_de, "V2"); assert.equal(m3.migre_de, "V3");
assert.deepEqual(m2.analyse.blocs.map(b => b.type), ["paragraphe", "puce", "puce", "image"]);
assert.equal(m2.analyse.blocs[3].capture, "cap1");
for (const k of Object.keys(v2)) if (k !== "version") assert.deepEqual(m2[k], v2[k], k);   // tous les champs V2 conservés
assert.deepEqual(m3.stats, v3.stats); assert.equal(m3.sens, "Vente");
assert.equal(J.migrerV4(m2), m2);                                             // idempotent
const v1 = { id: "n0", cree_le: "2026-10-01T08:00:00Z", texte: "ancienne note", images: [] };
assert.equal(J.migrerV4(v1).analyse.blocs[0].texte, "ancienne note");
assert.equal(S.versTrade(m3).sens, "Vente");                                  // les statistiques lisent toujours la note

// ---- calendrier et bilan du mois
const t1 = J.noteV4({ paire: "USD/JPY", sens: "Achat", entree_locale: "2026-11-17T14:40", entree_utc: "2026-11-17T13:40:00.000Z",
                      sortie_locale: "2026-11-17T16:55", sortie_utc: "2026-11-17T15:55:00.000Z", pnl_eur: "120", risque_eur: "60" });
const t2 = J.noteV4({ paire: "EUR/USD", sens: "Vente", entree_locale: "2026-11-17T09:00", entree_utc: "2026-11-17T08:00:00.000Z", pnl_eur: "−150" });
assert.equal(t1.resultat.r, 2); assert.equal(t2.resultat.r, null);
const g = J.grilleMoisV4([t1, t2, m2], "2026-11");
assert.equal(g["2026-11-17"].eur, -30); assert.equal(g["2026-11-17"].classe, "perte");
assert.deepEqual(g["2026-11-17"].trades.map(t => t.paire), ["EUR/USD", "USD/JPY"]);
assert.equal(g["2026-11-05"].classe, "gain");
assert.deepEqual(J.bilanMoisV4([t1, t2, m2], "2026-11"), { n: 3, eur: 20, reussite: 67, gagnants: 2 });
assert.deepEqual(J.caseDepart("2026-11"), { vides: 6, jours: 30 });          // 1er novembre 2026 : un dimanche
assert.equal(J.moisVoisin("2026-01", -1), "2025-12");
assert.equal(S.versTrade(t1).r, 2);

// ---- statistiques selon le contexte
const lu = (pour, eur) => ({ resultat: { statut: "cloturee", pnl_eur: eur }, lecture: { pour } });
const sc = J.statsContexte([lu(6, 10), lu(5, -5), lu(5, 8), lu(2, -3), lu(1, -4), lu(3, 9), { resultat: { statut: "cloturee", pnl_eur: 1 } }]);
assert.deepEqual(sc, { forts: { n: 3, reussite: 67 }, faibles: { n: 2, reussite: 0 }, lus: 6 });

console.log("journal V4 : OK");
