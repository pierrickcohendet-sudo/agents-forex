// Lot V11 : parcours complet du Journal (maquette_v11_journal.html), rejouable (Edge sans interface, protocole DevTools).
// Usage : node outils/parcours_journal.mjs <url de base> <dossier de sortie>
// À 1280 et 390 px : accueil -> clic sur le 20/11 -> « + Ajouter » -> EUR/USD achat 08:40 -> 09:34, +110 € -> « Mon analyse »
// (titre et liste) -> Photos (une collée, une choisie, deux légendes, unités M30 et H4, plein écran, suppression d'une) ->
// « Lecture du site » -> retour à l'accueil (jour vert +110 €) -> suppression de l'entrée de test. Captures à chaque étape,
// texte de la « Lecture du site » dans lecture_du_site-<largeur>.txt, bilan dans parcours.json. Profil Edge temporaire.
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const [base, sortie] = process.argv.slice(2);
const JOUR = process.env.JOUR || "2026-11-20";
const EDGE = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe"].find(existsSync);
const PORT = 9800 + Math.floor(Math.random() * 150);
mkdirSync(sortie, { recursive: true });
const profil = join(tmpdir(), "parcours-journal-" + PORT);
const edge = spawn(EDGE, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profil}`, "--hide-scrollbars", "--no-first-run", "--lang=fr-FR", "about:blank"], { stdio: "ignore" });
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
const CODES = { Enter: 13, Escape: 27, ArrowRight: 39, ArrowLeft: 37 };
const touche = async key => { await cdp("Input.dispatchKeyEvent", { type: "keyDown", key, code: key, windowsVirtualKeyCode: CODES[key] }); await cdp("Input.dispatchKeyEvent", { type: "keyUp", key, code: key, windowsVirtualKeyCode: CODES[key] }); };
const taper = async t => { await cdp("Input.insertText", { text: t }); await pause(150); };
const attendre = ms => evaluer(`await new Promise(r => setTimeout(r, ${ms})); return 1;`);
const capture = async (nom, largeur) => { await pause(500); const img = await cdp("Page.captureScreenshot", { format: "png" }, 60000);
  if (img.result) writeFileSync(join(sortie, `${nom}-${largeur}.png`), Buffer.from(img.result.data, "base64")); console.log(nom, largeur, img.result ? "ok" : "échec"); };
const IMAGE = (texte, couleur) => `const c = document.createElement("canvas"); c.width = 800; c.height = 450; const g = c.getContext("2d"); g.fillStyle = "#0d1119"; g.fillRect(0, 0, 800, 450);
  g.strokeStyle = "${couleur}"; g.lineWidth = 5; g.beginPath(); for (let i = 0; i <= 16; i++) g[i ? "lineTo" : "moveTo"](i * 50, 380 - i * 14 + (i % 3) * 30); g.stroke();
  g.fillStyle = "#E8ECF4"; g.font = "28px sans-serif"; g.fillText("${texte}", 24, 48);
  const dt = new DataTransfer(); dt.items.add(new File([await new Promise(r => c.toBlob(r, "image/png"))], "capture.png", { type: "image/png" }));`;

await cdp("Page.enable"); await cdp("Runtime.enable");
await cdp("Emulation.setTimezoneOverride", { timezoneId: "Europe/Paris" });
const bilan = [];
for (const largeur of [1280, 390]) {
  await cdp("Emulation.setDeviceMetricsOverride", { width: largeur, height: largeur > 700 ? 860 : 844, deviceScaleFactor: 1, mobile: false });
  await cdp("Page.navigate", { url: `${base}#journal` });
  await pause(1500); await attendre(3000);
  // 1. accueil (téléphone : vue « Calendrier »), clic sur le jour, « + Ajouter »
  if (largeur < 700) { await capture("0-fil-vide", largeur); await evaluer(`document.querySelector('#jVues [data-v="accueil"]').click(); return 1;`); await attendre(600); }
  await capture("1-accueil", largeur);
  await evaluer(`const d = document.querySelector('.j5 .cal .d[data-d="${JOUR}"]'); d.scrollIntoView({ block: "center" }); d.click(); return 1;`); await attendre(500);
  await evaluer(`const b = document.querySelector('.dayp [data-new]'); b.scrollIntoView({ block: "center" }); b.click(); return 1;`); await attendre(600);
  // 2. saisie rapide
  await evaluer(`const M = document.querySelector('.j5-modal'); M.querySelector('[data-p="EUR/USD"]').click(); M.querySelector('[data-s="Achat"]').click();
    const s = (q, v) => { const e = M.querySelector(q); e.value = v; e.dispatchEvent(new Event("input", { bubbles: true })); }; s('#tIn', '08:40'); s('#tOut', '09:34'); M.querySelector('#mRes').focus(); return 1;`);
  await taper("+110");
  await capture("2-nouveau-trade", largeur);
  await evaluer(`document.querySelector('.j5-modal button[type=submit]').click(); return 1;`); await attendre(1500);
  // 3. Mon analyse : un titre et une liste
  await evaluer(`document.querySelector('.j5-drw .ed-texte').focus(); return 1;`);
  await taper("/"); await attendre(300); await evaluer(`document.querySelector('.ed-menu [data-t="titre"]').click(); return 1;`); await attendre(300);
  await taper("Pourquoi ce trade"); await touche("Enter"); await attendre(200);
  await taper("/"); await attendre(300); await evaluer(`document.querySelector('.ed-menu [data-t="puce"]').click(); return 1;`); await attendre(300);
  await taper("Sweep du plus bas d'Asie puis retest"); await touche("Enter"); await attendre(200);
  await taper("Biais H4 haussier"); await attendre(1200);
  const analyse = await evaluer(`return [...document.querySelectorAll('.j5-drw .ed-bloc')].map(b => b.dataset.type).join(", ") + " · " + document.querySelector('#edEtat').textContent;`);
  await capture("3-mon-analyse", largeur);
  // 4. Photos : une collée, une choisie, deux légendes, unités M30 et H4, plein écran, suppression d'une image
  await evaluer(`document.querySelector('.j5-drw [data-tab="photos"]').click(); await new Promise(r => setTimeout(r, 400));
    ${IMAGE("EUR/USD M30 (collée)", "#43D39E")} document.querySelector('.j5-drw .gal').dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
    await new Promise(r => setTimeout(r, 1500)); return 1;`);
  await evaluer(`${IMAGE("EUR/USD H4 (choisie)", "#8AA4FF")} const i = document.querySelector('.j5-drw [data-file]'); i.files = dt.files; i.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise(r => setTimeout(r, 1500)); document.querySelector('.j5-drw [data-cap="0"]').focus(); return 1;`);
  await taper("Retest du FVG en M30 après le sweep");
  await evaluer(`document.querySelector('.j5-drw [data-cap="1"]').focus(); return 1;`);
  await taper("Structure H4 haussière"); await attendre(900);
  await evaluer(`for (const [i, u] of [[0, "M30"], [1, "H4"]]) { const s = document.querySelector('.j5-drw [data-u="' + i + '"]'); s.value = u; s.dispatchEvent(new Event("change", { bubbles: true })); await new Promise(r => setTimeout(r, 700)); } return 1;`);
  const photos = await evaluer(`return [...document.querySelectorAll('.j5-drw .ph')].map(f => f.querySelector('.tf')?.textContent + " · " + f.querySelector('.cap').value);`);
  await capture("4-photos", largeur);
  await evaluer(`document.querySelector('.j5-drw [data-zoom="0"]').click(); return 1;`); await attendre(400);
  await capture("4b-plein-ecran", largeur);
  await touche("ArrowRight"); await attendre(300);
  const suivante = await evaluer(`return document.querySelector('.j5-lb .ctl span').textContent;`);
  await touche("Escape"); await attendre(300);
  await evaluer(`document.querySelector('.j5-drw [data-del="1"]').click(); return 1;`); await attendre(800);
  const apres = await evaluer(`return document.querySelector('.j5-drw [data-tab="photos"]').textContent;`);
  // 5. Lecture du site
  await evaluer(`document.querySelector('.j5-drw [data-tab="lecture"]').click(); return 1;`); await attendre(2500);
  await evaluer(`const d = document.querySelector('.j5-drw'); d.scrollTop = d.querySelector('.ptabs').offsetTop; return 1;`);
  await capture("5-lecture-du-site", largeur);
  writeFileSync(join(sortie, `lecture_du_site-${largeur}.txt`), await evaluer(`return document.querySelector('.j5-drw .jl')?.innerText || "absente";`), "utf-8");
  const contexte = await evaluer(`return document.querySelector('.j5-drw .props').innerText.split("\\n").slice(-1)[0];`);
  // 6. retour à l'accueil : le jour en vert avec +110 €
  await touche("Escape"); await attendre(800);
  const jour = await evaluer(`const d = document.querySelector('.j5 .cal .d[data-d="${JOUR}"]'); d.scrollIntoView({ block: "center" }); return d.className.replace(/\\s+/g, " ").trim() + " · " + d.innerText.replace(/\\n/g, " ");`);
  await capture("6-accueil-apres", largeur);
  if (largeur < 700) { await evaluer(`document.querySelector('#jVues [data-v="fil"]').click(); window.scrollTo(0, 0); return 1;`); await attendre(500); await capture("6b-fil", largeur); await evaluer(`document.querySelector('#jVues [data-v="accueil"]').click(); return 1;`); await attendre(300); }
  else { await evaluer(`document.querySelector('#jVues [data-v="liste"]').click(); window.scrollTo(0, 0); return 1;`); await attendre(900); await capture("6b-liste", largeur); await evaluer(`document.querySelector('#jVues [data-v="accueil"]').click(); return 1;`); await attendre(300); }
  // 7. suppression de l'entrée de test
  await evaluer(`document.querySelector('.dayp .tcard').click(); await new Promise(r => setTimeout(r, 900)); document.querySelector('.j5-drw [data-a="supprimer"]').click(); await new Promise(r => setTimeout(r, 200));
    document.querySelector('.j5-drw [data-a="oui"]').click(); await new Promise(r => setTimeout(r, 900)); return 1;`);
  const reste = await evaluer(`const v = document.querySelector('script[src*="app.js"]').src.split("v=")[1]; const m = await import("./site/journal.js?v=" + v); return (await m.lireNotes()).length;`);
  const debord = await evaluer(`return document.documentElement.scrollWidth > innerWidth + 1;`);
  bilan.push({ largeur, analyse, photos, plein_ecran_suivante: suivante, photos_apres_suppression: apres, contexte, jour, entrees_restantes: reste, debordement: debord });
}
console.log(JSON.stringify(bilan, null, 1));
writeFileSync(join(sortie, "parcours.json"), JSON.stringify(bilan, null, 1), "utf-8");
ws.close(); edge.kill();
await pause(500);
try { rmSync(profil, { recursive: true, force: true }); } catch (e) { /* profil encore verrouillé */ }
