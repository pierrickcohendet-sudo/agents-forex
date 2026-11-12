// Vérifie que chaque onglet et chaque adresse de détail s'ouvre sans erreur (correctif du 11/11/2026).
// Usage : node outils/verifier_adresses.mjs <url de base> [--mobile] [--filtre=devises]
//   ex. node outils/verifier_adresses.mjs "http://localhost:4173/"
//       node outils/verifier_adresses.mjs "https://pierrickcohendet-sudo.github.io/agents-forex/"
// Edge sans interface piloté par le protocole DevTools, sans dépendance. Deux passes :
//   1. chargement complet de chaque adresse (premier passage : sans service worker, puis avec le service worker en cache) ;
//   2. changement d'adresse dans une page déjà ouverte (écran déjà construit : liens entre onglets, recherche rapide).
// Échec si : erreur console ou exception, écran en erreur, ou cible absente (fiche de la devise, paire choisie, dossier N).
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const base = process.argv[2] || "http://localhost:4173/";
const mobile = process.argv.includes("--mobile");
const filtre = (process.argv.find(a => a.startsWith("--filtre=")) || "").slice(9);   // ex. --filtre=devises (vérification ciblée)
const EDGE = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe"].find(existsSync);
const PORT = 9800 + Math.floor(Math.random() * 150);
const profil = join(tmpdir(), "verif-adresses-" + PORT);
const edge = spawn(EDGE, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profil}`, "--no-first-run", "about:blank"], { stdio: "ignore" });
const pause = ms => new Promise(r => setTimeout(r, ms));

let cible;
for (let i = 0; i < 40 && !cible; i++) {
  await pause(250);
  try { cible = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find(t => t.type === "page"); } catch (e) { /* Edge démarre */ }
}
const ws = new WebSocket(cible.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let n = 0; const attente = new Map(); let erreurs = [];
ws.addEventListener("message", ev => {
  const m = JSON.parse(ev.data);
  if (m.id && attente.has(m.id)) { attente.get(m.id)(m); attente.delete(m.id); return; }
  if (m.method === "Runtime.exceptionThrown") erreurs.push(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text);
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") erreurs.push(m.params.args.map(a => a.value ?? a.description).join(" "));
  if (m.method === "Log.entryAdded" && m.params.entry.level === "error" && !/favicon/.test(m.params.entry.url || "")) erreurs.push(`${m.params.entry.text} ${m.params.entry.url || ""}`);
});
// Délai maximal de 20 s par commande : une page rechargée pendant une évaluation ne bloque pas le test.
const cdp = (method, params = {}) => new Promise(r => { const id = ++n; const t = setTimeout(() => { attente.delete(id); r({ delai: true }); }, 20000);
  attente.set(id, m => { clearTimeout(t); r(m); }); ws.send(JSON.stringify({ id, method, params })); });
const evaluer = async expr => (await cdp("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;
await cdp("Page.enable"); await cdp("Runtime.enable"); await cdp("Log.enable");
await cdp("Emulation.setDeviceMetricsOverride", mobile ? { width: 390, height: 844, deviceScaleFactor: 1, mobile: false } : { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

const sansSlash = base.replace(/#.*$/, "");
const donnees = await (await fetch(new URL("data/paires.json", sansSlash))).json();
const PAIRES = donnees.paires || [];
const DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"];
const ONGLETS = ["briefing", "synthese", "tableau", "paire", "devises", "agenda", "engrenages", "journal", "scenarios", "sante", "archives"];
const adresses = [
  ...ONGLETS.map(o => [o, `typeof document.querySelector("#s-${o}") === "object" && !!document.querySelector("#s-${o}.on")`]),
  ...DEVISES.map(d => [`devises/${d}`, `!!document.querySelector('#s-devises.on .dv.cible[data-devise="${d}"]') && !!document.querySelector("#fiche-${d}")?.open && Math.abs(document.querySelector("#fiche-${d}").getBoundingClientRect().top) < innerHeight`]),
  ...PAIRES.map(p => [`paire/${p.replace("/", "-")}`, `document.querySelector("#s-paire.on #ppSel")?.value === "${p}"`]),
  ...Array.from({ length: 8 }, (_, i) => [`engrenages/g=${i + 1}`, `document.querySelector('#s-engrenages.on #engSel button[data-n="${i + 1}"]')?.getAttribute("aria-pressed") === "true"`]),
  ["engrenages/hebdo", `!!document.querySelector("#s-engrenages.on details.detaille[open]")`],
];

if (filtre) adresses.splice(0, adresses.length, ...adresses.filter(([a]) => a.includes(filtre)));

// Attend la fin de construction de l'écran (plus de squelette de chargement), au plus 12 s.
const pret = `(async () => { for (let i = 0; i < 60; i++) { await new Promise(r => setTimeout(r, 200));
  const s = document.querySelector(".screen.on"); if (s && !s.querySelector(".skel")) { await new Promise(r => setTimeout(r, 400)); return 1; } } return 0; })()`;
const verdict = cond => `(() => { const s = document.querySelector(".screen.on");
  return { ecran: s?.id || null, erreur: s?.dataset.erreur === "1" ? s.textContent.slice(0, 200) : null,
           bandeau: document.querySelector("#erreurGlobale:not([hidden])")?.textContent || null, cible: (() => { try { return ${cond}; } catch (e) { return false; } })(),
           debord: document.documentElement.scrollWidth > innerWidth + 1, sw: !!navigator.serviceWorker?.controller }; })()`;

let echecs = 0;
function noter(mode, adr, v) {
  const pb = [];
  if (!v) pb.push("page non évaluée");
  else {
    if (v.erreur) pb.push(`écran en erreur : ${v.erreur}`);
    if (v.bandeau) pb.push(`bandeau d'erreur : ${v.bandeau}`);
    if (!v.cible) pb.push("cible non ouverte");
    if (v.debord) pb.push("débordement horizontal");
  }
  if (erreurs.length) pb.push(`console : ${erreurs.slice(0, 3).join(" | ")}`);
  if (pb.length) echecs++;
  console.log(`${pb.length ? "ÉCHEC" : "ok   "} ${mode.padEnd(10)} #${adr}${v?.sw ? " (service worker)" : ""}${pb.length ? " — " + pb.join(" ; ") : ""}`);
}

// Passe 1 : chargement complet de chaque adresse
for (const [adr, cond] of adresses) {
  await cdp("Page.navigate", { url: "about:blank" }); await pause(150);
  erreurs = [];
  await cdp("Page.navigate", { url: `${sansSlash}#${adr}` });
  await pause(600);
  await evaluer(pret);
  noter("chargement", adr, await evaluer(verdict(cond)));
}
// Passe 2 : même page, changement d'adresse (écrans déjà construits)
await cdp("Page.navigate", { url: `${sansSlash}#briefing` }); await pause(600); await evaluer(pret);
for (const [adr, cond] of adresses) {
  erreurs = [];
  await evaluer(`document.querySelector("#erreurGlobale")?.setAttribute("hidden", ""); location.hash = ${JSON.stringify("#" + adr)}`);
  await pause(300);
  await evaluer(pret);
  noter("navigation", adr, await evaluer(verdict(cond)));
}
console.log(`${adresses.length * 2} vérifications, ${echecs} échec(s) — ${base}${mobile ? " (téléphone 390 px)" : " (PC 1280 px)"}`);
ws.close(); edge.kill();
process.exit(echecs ? 1 : 0);
