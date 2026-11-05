/* Service worker de Trading baby (lot V8).
   - Code du site (site/, icônes, page) : « cache d'abord », cache vidé à chaque nouvelle version (VERSION, écrite par
     core/version_site.py) ; la page elle-même passe par le réseau d'abord pour voir les nouvelles versions.
   - Données (data/*.json) : « réseau d'abord, cache en secours » ; si c'est le cache qui répond, la page reçoit la date
     de ces données (« données hors connexion du JJ/MM HH:MM »).
   Aucune clé, aucune donnée personnelle : le Journal reste dans IndexedDB, hors de ce cache. */
const VERSION = "8c61f8a";
const CODE = `tb-code-${VERSION}`, DONNEES = "tb-donnees";

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CODE).then(c => c.addAll(["./", "./index.html", "./manifest.webmanifest", "./icones/logo.svg", "./icones/icone-192.png"]))
    .catch(() => undefined).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(cles => Promise.all(cles.filter(k => k.startsWith("tb-code-") && k !== CODE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const dateFr = ms => { const d = new Date(ms); return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };

async function donnees(req, clientId) {
  const cache = await caches.open(DONNEES), cle = req.url.split("?")[0];
  try {
    const rep = await fetch(req);
    if (rep.ok) {
      const corps = await rep.clone().blob();
      await cache.put(cle, new Response(corps, { headers: { "Content-Type": rep.headers.get("Content-Type") || "application/json", "X-Mis-en-cache": String(Date.now()) } }));
    }
    return rep;
  } catch (err) {
    const enCache = await cache.match(cle);
    if (!enCache) throw err;
    const client = clientId && await self.clients.get(clientId);
    client?.postMessage({ type: "hors-connexion", date: dateFr(Number(enCache.headers.get("X-Mis-en-cache")) || Date.now()) });
    return enCache;
  }
}

async function code(req) {
  const cache = await caches.open(CODE), enCache = await cache.match(req);
  if (enCache) return enCache;
  const rep = await fetch(req);
  if (rep.ok && rep.type !== "opaque") cache.put(req, rep.clone());
  return rep;
}

async function page(req) {
  const cache = await caches.open(CODE);
  try { const rep = await fetch(req); if (rep.ok) cache.put("./index.html", rep.clone()); return rep; }
  catch (err) { return (await cache.match("./index.html")) || (await cache.match("./")) || Promise.reject(err); }
}

self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET") return;
  if (url.origin !== location.origin) return;   // polices et bibliothèques externes : navigateur seul
  if (req.mode === "navigate") { e.respondWith(page(req)); return; }
  if (url.pathname.includes("/data/") && url.pathname.endsWith(".json")) { e.respondWith(donnees(req, e.clientId)); return; }
  if (/\/(site|icones)\//.test(url.pathname) || url.pathname.endsWith("manifest.webmanifest")) e.respondWith(code(req));
});
