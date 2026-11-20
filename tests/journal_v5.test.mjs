// Lot V11 : Journal V5, fonctions pures (sans DOM ni réseau) : statistiques de l'accueil, total par semaine, ordre et
// légendes des photos, sérialisation, migration avec reprise des images du V10 dans « Photos ».
import assert from "node:assert/strict";

globalThis.document = { querySelector: () => null, documentElement: { dataset: {} } };
const V5 = await import("../docs/site/journal_v5.js");
const V4 = await import("../docs/site/journal_v4.js");

const trade = (jour, eur, o = {}) => ({ version: 5, id: o.id || `t${jour}${eur}`, paire: o.p || "EUR/USD", sens: "Achat", entree_locale: `${jour}T${o.h || "09:00"}`,
  entree_utc: `${jour}T${o.h || "08:00"}:00.000Z`, resultat: { statut: "cloturee", pnl_eur: eur, r: o.r ?? null }, lecture: o.pour == null ? null : { pour: o.pour },
  photos: [], captures: [], setup: o.setup || [], analyse: { blocs: o.blocs || [] } });

// ---- statistiques de l'accueil (6 indicateurs)
const T = [trade("2026-11-02", 200, { pour: 5, r: 2 }), trade("2026-11-03", -100, { pour: 2, r: -1 }), trade("2026-11-04", 110, { pour: 4 }),
           trade("2026-11-05", -50, { pour: 1 }), trade("2026-11-20", null), trade("2026-10-30", 999)];
const S = V5.statsAccueil(T, "2026-11");
assert.equal(S.n, 4); assert.equal(S.eur, 160); assert.equal(S.r, 1); assert.equal(S.reussite, 50);
assert.equal(S.facteur, 2.07);                       // 310 / 150
assert.equal(S.gain_moyen, 155); assert.equal(S.perte_moyenne, -75);
assert.deepEqual(S.favorable, { n: 2, reussite: 100 }); assert.deepEqual(S.autres, { n: 2, reussite: 0 });
assert.equal(S.a_completer, 1);                      // l'entrée sans résultat ne compte pas, elle est signalée
assert.equal(V5.aCompleter(T[4]), true);
assert.equal(V5.aCompleter({ resultat: { statut: "cloturee", pnl_eur: null, r: 1.5 } }), false);   // résultat saisi en R

// ---- calendrier compact : semaines et total par semaine
const W = V5.semainesMois([...T, trade("2026-11-03", 30)], "2026-11");
assert.equal(W[0].lundi, "2026-10-26"); assert.equal(W.length, 6);            // du lundi 26/10 au dimanche 06/12
assert.equal(W[0].jours[0].hors_mois, true); assert.equal(W[0].jours[6].iso, "2026-11-01");
assert.equal(W[0].total.n, 0);                                                 // le 30/10 (hors du mois) n'entre pas dans le total
assert.deepEqual(W[1].total, { n: 5, eur: 190 });                              // semaine du 02/11 : 200 − 100 + 30 + 110 − 50
assert.equal(W[1].jours[1].eur, -70); assert.equal(W[1].jours[1].classe, "perte"); assert.equal(W[1].jours[1].n, 2);
assert.equal(W[1].jours[5].week_end, true);
assert.equal(W[3].jours[4].classe, "neutre");                                  // le 20/11 : un trade, résultat à compléter
assert.deepEqual(V5.courbeCumul(T, "2026-11"), [0, 200, 100, 210, 160]);

// ---- vue liste : groupes par semaine, recherche, fil
const G = V5.groupesSemaine(T.slice(0, 5));
assert.deepEqual(G.map(g => [g.lundi, g.trades.length, g.total]), [["2026-11-16", 1, null], ["2026-11-02", 4, 160]]);
const avecTexte = trade("2026-11-06", 40, { setup: ["Sweep + FVG"], blocs: [{ id: "a", type: "paragraphe", texte: "Retest du <b>FVG</b> en M30" }] });
avecTexte.photos = [{ capture: "c1", legende: "Structure H4 haussière", unite: "H4" }];
assert.equal(V5.rechercher([avecTexte, T[0]], "sweep").length, 1);
assert.equal(V5.rechercher([avecTexte, T[0]], "fvg").length, 1);              // texte de l'analyse
assert.equal(V5.rechercher([avecTexte, T[0]], "structure h4").length, 1);     // légende d'une photo
assert.equal(V5.rechercher([avecTexte, T[0]], "").length, 2);
assert.equal(V5.filtrerFil(T, "Gagnants").length, 3); assert.equal(V5.filtrerFil(T, "Perdants").length, 2);
assert.equal(V5.resume(avecTexte), "Retest du FVG en M30");

// ---- photos : ordre, légendes, unités, couverture, suppression
let n = { captures: [{ id: "a" }, { id: "b" }, { id: "c" }], photos: [{ capture: "a", legende: "", unite: null }, { capture: "b", legende: "", unite: null }, { capture: "c", legende: "", unite: null }],
          analyse: { blocs: [{ id: "x", type: "image", capture: "b" }, { id: "y", type: "paragraphe", texte: "ok" }] } };
assert.deepEqual(V5.deplacer(n.photos, 2, 0).map(p => p.capture), ["c", "a", "b"]);
assert.deepEqual(V5.deplacer(n.photos, 0, 9).map(p => p.capture), ["a", "b", "c"]);    // hors bornes : inchangé
n.photos = V5.legender(n.photos, "b", "Retest M30");
n.photos = V5.changerUnite(V5.changerUnite(n.photos, "b", "M30"), "a", "X9");
assert.deepEqual(n.photos[1], { capture: "b", legende: "Retest M30", unite: "M30" }); assert.equal(n.photos[0].unite, null);
assert.equal(V5.couvertureDe(n), "a"); assert.equal(V5.couvertureDe({ ...n, couverture: "c" }), "c");
const n2 = V5.supprimerPhoto({ ...n, couverture: "b" }, "b");
assert.deepEqual(n2.photos.map(p => p.capture), ["a", "c"]); assert.equal(n2.captures.length, 2);
assert.equal(n2.couverture, null); assert.deepEqual(n2.analyse.blocs.map(b => b.id), ["y"]);   // le bloc image disparaît aussi
assert.deepEqual(V5.synchroniser([{ capture: "a" }], [{ id: "a" }, { id: "d" }], [{ type: "image", capture: "d", legende: "collée", unite: "H1" }]),
  [{ capture: "a" }, { capture: "d", legende: "collée", unite: "H1" }]);                         // image collée dans l'analyse -> Photos

// ---- migration : V2, V3 et V4 vers V5, images du V10 reprises dans Photos sans doublon
const v4 = { version: 4, id: "n4", paire: "USD/JPY", entree_locale: "2026-11-17T14:40", captures: [{ id: "k1" }, { id: "k2" }],
             analyse: { blocs: [{ id: "i", type: "image", capture: "k2", legende: "H4 avant", unite: "H4" }, { id: "j", type: "image", capture: "k2", legende: "doublon" }] },
             resultat: { statut: "cloturee", pnl_eur: 120 } };
const m4 = V5.migrerV5(v4);
assert.equal(m4.version, 5);
assert.deepEqual(m4.photos, [{ capture: "k2", legende: "H4 avant", unite: "H4" }, { capture: "k1", legende: "", unite: null }]);
assert.deepEqual(m4.analyse, v4.analyse); assert.equal(m4.paire, "USD/JPY");                  // rien n'est perdu
assert.equal(V5.migrerV5(m4), m4);                                                            // idempotent
const v2 = { version: 2, id: "n2", date_heure: "2026-11-05T09:00:00Z", paire: "EUR/USD", contexte: "Biais haussier.", captures: [{ id: "c1", unites: ["4 h"] }],
             elements: [{ texte: "x" }], resultat: { statut: "cloturee", pnl_eur: "50" } };
const m2 = V5.migrerV5(v2);
assert.equal(m2.version, 5); assert.equal(m2.migre_de, "V2"); assert.deepEqual(m2.elements, v2.elements);
assert.deepEqual(m2.photos, [{ capture: "c1", legende: "", unite: "H4" }]);                   // unité V2 « 4 h » -> H4, sans doublon du bloc image
assert.equal(m2.analyse.blocs.filter(b => b.type === "image").length, 1);
const m3 = V5.migrerV5({ ...v2, id: "n3", stats: { sens: "Vente" } });
assert.equal(m3.migre_de, "V3"); assert.equal(m3.sens, "Vente");

// ---- sérialisation : la note V5 passe par JSON (export) sans perte
assert.deepEqual(JSON.parse(JSON.stringify(m4)), m4);
assert.deepEqual(V4.deserialiser(JSON.stringify(V4.serialiser(m4.analyse.blocs))), V4.serialiser(m4.analyse.blocs));

console.log("journal V5 : OK");
