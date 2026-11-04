// Captures pleine page (lot V7) : Edge sans interface piloté par le protocole DevTools, sans dépendance.
// Usage : node outils/captures.mjs <url de base> <dossier de sortie> [onglets séparés par des virgules]
// Pour chaque onglet : clair et sombre (document.documentElement.dataset.theme), 1280 et 390 px, page entière.
// Fichiers : <onglet>-<light|dark>-<1280|390>.png. Comparer ensuite à docs/design/reference/ (règle de DESIGN.md).
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const [base, sortie, liste] = process.argv.slice(2);
const ONGLETS = (liste || "synthese,tableau,devises,agenda,engrenages,journal").split(",");
const EDGE = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe"].find(existsSync);
const PORT = 9300 + Math.floor(Math.random() * 500);
mkdirSync(sortie, { recursive: true });
const profil = join(tmpdir(), "cap-v7-" + PORT);
const edge = spawn(EDGE, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profil}`, "--hide-scrollbars", "--no-first-run", "about:blank"], { stdio: "ignore" });
const pause = ms => new Promise(r => setTimeout(r, ms));

let cible;
for (let i = 0; i < 40 && !cible; i++) {
  await pause(250);
  try { cible = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find(t => t.type === "page"); } catch (e) { /* Edge démarre */ }
}
const ws = new WebSocket(cible.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let n = 0; const attente = new Map();
ws.addEventListener("message", ev => { const m = JSON.parse(ev.data); if (m.id && attente.has(m.id)) { attente.get(m.id)(m); attente.delete(m.id); } });
const cdp = (method, params = {}) => new Promise(r => { const id = ++n; attente.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
const evaluer = async expr => (await cdp("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;

await cdp("Page.enable"); await cdp("Runtime.enable");
for (const largeur of [1280, 390]) {
  await cdp("Emulation.setDeviceMetricsOverride", { width: largeur, height: 900, deviceScaleFactor: 1, mobile: false });
  for (const theme of ["light", "dark"]) {
    await cdp("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: theme }] });
    for (const onglet of ONGLETS) {
      const sep = base.includes("?") ? "&" : "?";
      await cdp("Page.navigate", { url: `${base}${sep}theme=${theme}#${onglet}` });
      await pause(800);
      await evaluer(`(async () => { document.documentElement.dataset.theme = ${JSON.stringify(theme)}; location.hash = ${JSON.stringify(onglet)}; await new Promise(r => setTimeout(r, 4500)); if (document.fonts) await document.fonts.ready; return 1; })()`);
      const haut = await evaluer("Math.ceil(Math.max(document.documentElement.scrollHeight, document.body.scrollHeight))");
      await cdp("Emulation.setDeviceMetricsOverride", { width: largeur, height: Math.min(haut || 900, 16000), deviceScaleFactor: 1, mobile: false });
      await pause(900);
      const img = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
      const nom = `${onglet}-${theme}-${largeur}.png`;
      writeFileSync(join(sortie, nom), Buffer.from(img.result.data, "base64"));
      const debord = await evaluer("document.documentElement.scrollWidth > window.innerWidth + 1");
      console.log(nom, haut + " px", debord ? "DÉBORDEMENT HORIZONTAL" : "");
      await cdp("Emulation.setDeviceMetricsOverride", { width: largeur, height: 900, deviceScaleFactor: 1, mobile: false });
    }
  }
}
ws.close(); edge.kill();
