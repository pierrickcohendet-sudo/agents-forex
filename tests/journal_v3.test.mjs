// Lot V8 : statistiques du Journal V3 (fonctions pures) et recherche rapide, sans DOM ni réseau.
import assert from "node:assert/strict";

globalThis.document = { querySelector: () => null, documentElement: { dataset: {} } };
const J = await import("../docs/site/journal_stats.js");
const R = await import("../docs/site/recherche.js");

// Séance déduite de l'heure UTC (mêmes heures que la technique Python)
assert.equal(J.seanceDe("2026-11-05T03:00:00Z"), "Asie");
assert.equal(J.seanceDe("2026-11-05T09:30:00Z"), "Londres");
assert.equal(J.seanceDe("2026-11-05T14:00:00Z"), "New York");

// Avec ou contre le thème : « Dollar haussier » = acheter le dollar
assert.equal(J.avecLeTheme("USD/JPY", "Achat", "Dollar haussier · Risque neutre"), true);
assert.equal(J.avecLeTheme("EUR/USD", "Achat", "Dollar haussier · Risque neutre"), false);
assert.equal(J.avecLeTheme("EUR/USD", "Vente", "Dollar baissier"), false);
assert.equal(J.avecLeTheme("EUR/GBP", "Achat", "Dollar haussier"), null);      // paire sans dollar : non classée
assert.equal(J.avecLeTheme("USD/JPY", "Pas encore décidé", "Dollar haussier"), null);

// Résultat en R : saisi, sinon converti depuis les € avec le risque prévu, sinon n/d
assert.equal(J.resultatR({ resultat: { r: "1,8" } }), 1.8);
assert.equal(J.resultatR({ resultat: { pnl_eur: "−45" }, plan: { risque_eur: "90" } }), -0.5);
assert.equal(J.resultatR({ resultat: { pnl_eur: "120" } }), null);

// Statistiques sur des exemples connus
const t = (d, r, o = {}) => ({ d, iso: d + "T10:00:00Z", p: o.p || "EUR/USD", sens: "Achat", sess: o.s || "Londres", conf: o.c ?? 2, theme: o.th ?? null, r, eur: null });
const S = J.statistiques([t("2026-11-02", 2), t("2026-11-03", -1), t("2026-11-04", -0.5), t("2026-11-05", 1.5)]);
assert.equal(S.n, 4); assert.equal(S.total_r, 2); assert.equal(S.reussite, 50); assert.equal(S.r_moyen, 0.5);
assert.equal(S.facteur_profit, 2.33);                     // 3,5 / 1,5
assert.deepEqual(S.serie, { n: 1, gagnante: true, dernier: "2026-11-05" });
assert.deepEqual(S.courbe.map(c => c.r), [2, 1, 0.5, 2]);
// En dessous de 5 trades dans un groupe : jamais de conclusion
for (const c of S.constats) assert.ok(c.chiffre === null && /Pas encore assez/.test(c.texte), c.titre);

// Constats : la phrase suit les chiffres (avec le thème : 4 gagnants sur 5 ; contre : 1 sur 5)
const avec = [1, 1, 1, 1, -1].map((r, i) => t(`2026-10-0${i + 1}`, r, { th: true, c: 4 }));
const contre = [1, -1, -1, -1, -1].map((r, i) => t(`2026-10-1${i + 1}`, r, { th: false, c: 0, s: "Asie" }));
const C = J.statistiques([...avec, ...contre]).constats;
assert.equal(C[0].titre, "Tu réussis mieux avec le thème du jour");
assert.equal(C[0].chiffre, "80 % contre 20 %");
assert.equal(C[1].chiffre, "80 % contre 20 %");
assert.match(C[2].texte, /^Londres est ta meilleure séance/);
assert.match(C[3].chiffre, /^0 perte réduite sur 5/);

// Calendrier en R et mode démonstration jamais mélangé (marqué « exemple »)
assert.deepEqual(J.calendrierR([t("2026-11-02", 1), t("2026-11-02", -0.5)], "2026-11"), { "2026-11-02": 0.5 });
const ex = J.exemples(new Date("2026-11-05T12:00:00Z"));
assert.ok(ex.length > 10 && ex.every(x => x.exemple === true));

// Recherche rapide : sans accents ni casse
assert.equal(R.normaliser("Réunion  BCE"), "reunion bce");
const idx = [{ type: "Paire", titre: "EUR/USD", detail: "", lien: "#paire/EUR-USD", extra: "EURUSD" }, { type: "Indicateur", titre: "Taux de chômage", detail: "Macro par devise", lien: "#tableau" },
             { type: "Publication", titre: "Décision de la BoE (Bank Rate)", detail: "05/11 13:00 · GBP · impact fort", lien: "#agenda/jour=2026-11-05" }]
  .map(x => ({ ...x, cle: R.normaliser(`${x.titre} ${x.detail} ${x.extra || ""} ${x.type}`) }));
assert.equal(R.chercher(idx, "chomage")[0].lien, "#tableau");
assert.equal(R.chercher(idx, "DECISION boe")[0].lien, "#agenda/jour=2026-11-05");
assert.equal(R.chercher(idx, "eurusd")[0].titre, "EUR/USD");
console.log("Journal V3 et recherche : OK");
