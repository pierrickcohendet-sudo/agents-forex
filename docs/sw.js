/* Service worker de Trading baby (lot V8, correctif « versions » du 11/11/2026).
   - Une version = un jeu complet de fichiers. À l'installation, le service worker met en cache TOUT le code de sa version
     (FICHIERS, liste écrite par core/version_site.py, adresses suffixées « ?v=<version> » comme dans l'importmap de la page).
     Une page ne reçoit donc jamais un mélange d'ancien et de nouveau code.
   - Pas d'activation en pleine session : la nouvelle version attend (« waiting »). La page affiche « Nouvelle version
     disponible : recharger » ; au chargement suivant (ou au clic), elle demande l'activation puis se recharge.
   - Données (data/*.json) : « réseau d'abord, cache en secours » ; si c'est le cache qui répond, la page reçoit la date
     de ces données (« données hors connexion du JJ/MM HH:MM »).
   Aucune clé, aucune donnée personnelle : le Journal reste dans IndexedDB, hors de ce cache. */
const VERSION = "caa2aa8";
const FICHIERS = ["site/accueil.js?v=caa2aa8", "site/agenda.js?v=caa2aa8", "site/app.js?v=caa2aa8", "site/archives.js?v=caa2aa8", "site/briefing.js?v=caa2aa8", "site/cabinet.css?v=caa2aa8", "site/cockpit.js?v=caa2aa8", "site/commun.js?v=caa2aa8", "site/consequences_synthese.js?v=caa2aa8", "site/devises.js?v=caa2aa8", "site/dossier_detail.js?v=caa2aa8", "site/dossiers.js?v=caa2aa8", "site/ecran_agenda.js?v=caa2aa8", "site/ecran_briefing.js?v=caa2aa8", "site/ecran_devises.js?v=caa2aa8", "site/ecran_engrenages.js?v=caa2aa8", "site/ecran_journal.js?v=caa2aa8", "site/ecran_paire.js?v=caa2aa8", "site/ecran_synthese.js?v=caa2aa8", "site/ecran_tableau.js?v=caa2aa8", "site/engrenages.js?v=caa2aa8", "site/hebdo.js?v=caa2aa8", "site/impression.js?v=caa2aa8", "site/journal.js?v=caa2aa8", "site/journal_logique.js?v=caa2aa8", "site/journal_stats.js?v=caa2aa8", "site/outils.js?v=caa2aa8", "site/paire_graphique.js?v=caa2aa8", "site/rapport.js?v=caa2aa8", "site/recherche.js?v=caa2aa8", "site/sante.js?v=caa2aa8", "site/scenarios.js?v=caa2aa8", "site/synthese.js?v=caa2aa8", "site/synthese_longue.js?v=caa2aa8", "site/synthese_suite.js?v=caa2aa8", "site/synthese_v9.js?v=caa2aa8", "site/tableau.js?v=caa2aa8", "site/tokens.css?v=caa2aa8", "site/v7.css?v=caa2aa8", "site/v7_commun.js?v=caa2aa8", "site/v8.css?v=caa2aa8", "site/v9.css?v=caa2aa8", "site/vue_ensemble.js?v=caa2aa8", "site/vendor/lightweight-charts.standalone.production.js?v=caa2aa8", "manifest.webmanifest", "icones/logo.svg", "icones/icone-192.png"];
const CODE = `tb-code-${VERSION}`, DONNEES = "tb-donnees";

self.addEventListener("install", e => {
  // Tout ou rien : si un fichier manque, l'installation échoue et l'ancienne version reste en place (nouvel essai au
  // prochain chargement). Jamais de skipWaiting ici : c'est la page qui décide du moment (rechargement).
  e.waitUntil(caches.open(CODE).then(c => c.addAll(["./", "./index.html", ...FICHIERS].map(u => new Request(u, { cache: "reload" })))));
});
self.addEventListener("message", e => {
  if (e.data?.type === "activer") self.skipWaiting();
  if (e.data?.type === "version") (e.ports?.[0] || e.source)?.postMessage({ type: "version", version: VERSION });
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

/* Code : servi depuis le cache de CETTE version. Une adresse d'une autre version (« ?v=autre ») n'est jamais mise en
   cache ici : elle vient du réseau, telle quelle. */
async function code(req) {
  const cache = await caches.open(CODE), enCache = await cache.match(req);
  if (enCache) return enCache;
  const rep = await fetch(req);
  const v = new URL(req.url).searchParams.get("v");
  if (rep.ok && rep.type !== "opaque" && (!v || v === VERSION)) cache.put(req, rep.clone());
  return rep;
}

/* Page : réseau d'abord (pour voir qu'une nouvelle version existe), cache de cette version en secours (hors connexion). */
async function page(req) {
  try { return await fetch(req); }
  catch (err) { const cache = await caches.open(CODE); return (await cache.match("./index.html")) || (await cache.match("./")) || Promise.reject(err); }
}

self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET") return;
  if (url.origin !== location.origin) return;   // polices et bibliothèques externes : navigateur seul
  if (req.mode === "navigate") { e.respondWith(page(req)); return; }
  if (url.pathname.includes("/data/") && url.pathname.endsWith(".json")) { e.respondWith(donnees(req, e.clientId)); return; }
  if (/\/(site|icones)\//.test(url.pathname) || url.pathname.endsWith("manifest.webmanifest")) e.respondWith(code(req));
});
