// Lot V6.1 : formats uniques des nombres (décimales fixes) et Vue complète / essentielle (mémorisation, défaut, sans stockage).
import assert from "node:assert/strict";

const stockage = new Map();
globalThis.localStorage = { getItem: k => stockage.get(k) ?? null, setItem: (k, v) => stockage.set(k, String(v)) };
globalThis.document = { documentElement: { dataset: {} }, querySelector: () => null };
const c = await import("../docs/site/commun.js");

// Décimales fixes : « 0,00 % » et non « 0 % », « 158,70 » et non « 158,7 »
assert.equal(c.FMT.pct(0), "0,00 %");
assert.equal(c.FMT.varPct(-0.5), "−0,50 %");
assert.equal(c.FMT.prix(158.7, "USD/JPY"), "158,70");
assert.equal(c.FMT.prix(1.12, "EUR/USD"), "1,1200");
assert.equal(c.FMT.taux(4.5), "4,50 %");
assert.equal(c.FMT.pb(-13), "−13 pb");
assert.equal(c.FMT.nombre(null), "n/d");

// Vue complète par défaut, mémorisée
assert.equal(c.vueCourante(), "complete");
c.enregistrerVue("essentielle");
assert.equal(stockage.get("fxdesk-vue"), "essentielle");
assert.equal(c.vueCourante(), "essentielle");
assert.equal(c.vueComplete(), false);
c.enregistrerVue("complete");
assert.equal(c.vueComplete(), true);

// Sans stockage (navigation privée, stockage bloqué) : vue complète, aucune exception
globalThis.localStorage = { getItem: () => { throw new Error("bloqué"); }, setItem: () => { throw new Error("bloqué"); } };
document.documentElement.dataset = {};
assert.equal(c.vueCourante(), "complete");
c.enregistrerVue("essentielle");
assert.equal(document.documentElement.dataset.vue, "essentielle");
console.log("V6.1 : formats et vue OK");
