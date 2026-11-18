// Lot V10 : parcours complet du Journal V4, rejouable (Edge sans interface, protocole DevTools, sans dépendance).
// Usage : node outils/parcours_journal.mjs <url de base> <dossier de sortie>
// À 1280 et 390 px : clic sur le 17/11 -> trade USD/JPY achat 14:40 -> 16:55, +120 € -> « Mon analyse » (titre, paragraphe,
// liste, image collée) -> « Lecture du site » -> calendrier -> suppression de l'entrée de test. Captures PNG à chaque étape ;
// texte de la « Lecture du site » écrit dans lecture_du_site-<largeur>.txt. Le profil Edge est temporaire (aucune donnée gardée).
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const [base, sortie] = process.argv.slice(2);
const EDGE = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe"].find(existsSync);
const PORT = 9800 + Math.floor(Math.random() * 150);
mkdirSync(sortie, { recursive: true });
const profil = join(tmpdir(), "parcours-v10-" + PORT);
const edge = spawn(EDGE, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profil}`, "--hide-scrollbars", "--no-first-run", "--lang=fr-FR", "about:blank"],
  { stdio: "ignore", env: { ...process.env, TZ: "Europe/Paris" } });
const pause = ms => new Promise(r => setTimeout(r, ms));
let cible;
for (let i = 0; i < 40 && !cible; i++) { await pause(250); try { cible = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find(t => t.type === "page"); } catch (e) { /* Edge démarre */ } }
const ws = new WebSocket(cible.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let n = 0; const attente = new Map();
ws.addEventListener("message", ev => { const m = JSON.parse(ev.data); if (m.id && attente.has(m.id)) { attente.get(m.id)(m); attente.delete(m.id); } });
const cdp = (method, params = {}, delai = 30000) => new Promise(r => { const id = ++n; const t = setTimeout(() => { attente.delete(id); r({ delai: true }); }, delai);
  attente.set(id, m => { clearTimeout(t); r(m); }); ws.send(JSON.stringify({ id, method, params })); });
const evaluer = async expr => { const r = await cdp("Runtime.evaluate", { expression: `(async () => { ${expr} })()`, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || "erreur JS"); return r.result?.result?.value; };
const touche = async (key, text) => { await cdp("Input.dispatchKeyEvent", { type: "keyDown", key, text, code: key === "Enter" ? "Enter" : undefined, windowsVirtualKeyCode: key === "Enter" ? 13 : key === "Escape" ? 27 : undefined });
  await cdp("Input.dispatchKeyEvent", { type: "keyUp", key, windowsVirtualKeyCode: key === "Enter" ? 13 : key === "Escape" ? 27 : undefined }); };
const taper = async t => { await cdp("Input.insertText", { text: t }); await pause(120); };
const attendre = ms => evaluer(`await new Promise(r => setTimeout(r, ${ms})); return 1;`);
const capture = async (nom, largeur) => { await pause(500); const img = await cdp("Page.captureScreenshot", { format: "png" }, 60000);
  if (img.result) writeFileSync(join(sortie, `${nom}-${largeur}.png`), Buffer.from(img.result.data, "base64")); console.log(nom, largeur, img.result ? "ok" : "échec"); };

await cdp("Page.enable"); await cdp("Runtime.enable");
await cdp("Emulation.setTimezoneOverride", { timezoneId: "Europe/Paris" });
const bilan = [];
for (const largeur of [1280, 390]) {
  await cdp("Emulation.setDeviceMetricsOverride", { width: largeur, height: largeur > 700 ? 860 : 844, deviceScaleFactor: 1, mobile: false });
  await cdp("Page.navigate", { url: `${base}#journal` });
  await pause(1500);
  await attendre(3000);
  // 1. clic sur le 17/11 (PC : panneau ; téléphone : liste du jour puis « + Ajouter un trade »)
  await evaluer(`document.querySelector('.j4-case[data-j="2026-11-17"]').scrollIntoView({ block: "center" }); document.querySelector('.j4-case[data-j="2026-11-17"]').click(); return 1;`);
  await attendre(700);
  if (largeur < 700) { await capture("1-jour-17-11", largeur); await evaluer(`document.querySelector('#jJour .btn.pri').click(); return 1;`); await attendre(700); }
  // 2. saisie rapide
  await evaluer(`document.querySelector('#sPaire').focus(); return 1;`);
  await taper("usdjpy"); await touche("Enter");
  await evaluer(`document.querySelector('[data-s="Achat"]').click();
    const s = (q, v) => { const e = document.querySelector(q); e.value = v; e.dispatchEvent(new Event("input", { bubbles: true })); };
    s('#sEntree', '2026-11-17T14:40'); s('#sSortie', '2026-11-17T16:55'); document.querySelector('#sPnl').focus(); return 1;`);
  await taper("+120");
  await capture("2-saisie-rapide", largeur);
  await evaluer(`document.querySelector('.j4-saisie button[type=submit]').click(); return 1;`);
  await attendre(1200);
  // 3. Mon analyse : titre (menu « / »), paragraphe, liste, image collée
  await evaluer(`document.querySelector('.ed-texte').focus(); return 1;`);
  await taper("/"); await attendre(300);
  await evaluer(`document.querySelector('.ed-menu [data-t="titre"]').click(); return 1;`); await attendre(300);
  await taper("Pourquoi je suis entré"); await touche("Enter"); await attendre(200);
  await taper("Le dollar restait soutenu par le 2 ans US et le yen ne trouvait pas d'acheteurs."); await touche("Enter"); await attendre(200);
  await taper("/"); await attendre(300);
  await evaluer(`document.querySelector('.ed-menu [data-t="puce"]').click(); return 1;`); await attendre(300);
  await taper("RSI 4 h autour de 53, sans excès"); await touche("Enter"); await attendre(200);
  await taper("Ventes au détail US à surveiller");
  await evaluer(`const c = document.createElement("canvas"); c.width = 640; c.height = 300; const g = c.getContext("2d"); g.fillStyle = "#0d1119"; g.fillRect(0, 0, 640, 300);
    g.strokeStyle = "#43D39E"; g.lineWidth = 4; g.beginPath(); [[0,250],[90,220],[170,235],[250,170],[330,190],[410,110],[490,130],[570,70],[640,55]].forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); g.stroke();
    g.fillStyle = "#E8ECF4"; g.font = "22px sans-serif"; g.fillText("USD/JPY H4 (capture de test)", 18, 36);
    const blob = await new Promise(r => c.toBlob(r, "image/png")); const dt = new DataTransfer(); dt.items.add(new File([blob], "capture.png", { type: "image/png" }));
    document.activeElement.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
    await new Promise(r => setTimeout(r, 1500)); [...document.querySelectorAll(".ed-unites button")].find(b => b.textContent === "H4")?.click();
    const l = document.querySelector(".ed-legende"); l.focus(); return 1;`);
  await taper("Structure H4 (capture collée)"); await attendre(1200);
  const blocs = await evaluer(`return [...document.querySelectorAll(".ed-bloc")].map(b => b.dataset.type).join(", ") + " · " + document.querySelector("#edEtat").textContent;`);
  await evaluer(`document.querySelector('#pCorps').scrollTop = 0; return 1;`);
  await capture("3-mon-analyse", largeur);
  // 4. Lecture du site
  await evaluer(`document.querySelector('[data-o="lecture"]').click(); return 1;`); await attendre(2500);
  await capture("4-lecture-du-site", largeur);
  await evaluer(`document.querySelector('#pCorps').scrollTop = 99999; return 1;`);
  await capture("4b-lecture-du-site-suite", largeur);
  const texte = await evaluer(`return document.querySelector(".jl").innerText;`);
  writeFileSync(join(sortie, `lecture_du_site-${largeur}.txt`), texte, "utf-8");
  // 5. le trade dans le calendrier
  await touche("Escape"); await attendre(700);
  const cal = await evaluer(`const c = document.querySelector('.j4-case[data-j="2026-11-17"]'); c.scrollIntoView({ block: "center" }); return c.getAttribute("aria-label");`);
  await capture("5-calendrier", largeur);
  // 6. suppression de l'entrée de test
  await evaluer(`document.querySelector('#jTab tr[data-id]').click(); await new Promise(r => setTimeout(r, 900)); document.querySelector('[data-o="trade"]').click(); await new Promise(r => setTimeout(r, 400));
    document.querySelector('#tSuppr').click(); document.querySelector('#tOui').click(); await new Promise(r => setTimeout(r, 900)); return 1;`);
  const reste = await evaluer(`const m = await import(document.querySelector('script[src*="app.js"]').src.replace("app.js", "journal.js")); return (await m.lireNotes()).length;`);
  const debord = await evaluer(`return document.documentElement.scrollWidth > innerWidth + 1;`);
  bilan.push({ largeur, blocs, calendrier: cal, entrees_restantes: reste, debordement: debord });
}
console.log(JSON.stringify(bilan, null, 1));
writeFileSync(join(sortie, "parcours.json"), JSON.stringify(bilan, null, 1), "utf-8");
ws.close(); edge.kill();
await pause(500);
try { rmSync(profil, { recursive: true, force: true }); } catch (e) { /* profil encore verrouillé : supprimé au prochain nettoyage */ }
