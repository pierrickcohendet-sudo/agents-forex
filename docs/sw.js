/* Service worker de Trading baby (lot V8, correctif « versions » du 11/11/2026).
   - Une version = un jeu complet de fichiers. À l'installation, le service worker met en cache TOUT le code de sa version
     (FICHIERS, liste écrite par core/version_site.py, adresses suffixées « ?v=<version> » comme dans l'importmap de la page).
     Une page ne reçoit donc jamais un mélange d'ancien et de nouveau code.
   - Pas d'activation en pleine session : la nouvelle version attend (« waiting »). La page affiche « Nouvelle version
     disponible : recharger » ; au chargement suivant (ou au clic), elle demande l'activation puis se recharge.
   - Données (data/*.json) : « réseau d'abord, cache en secours » ; si c'est le cache qui répond, la page reçoit la date
     de ces données (« données hors connexion du JJ/MM HH:MM »).
   Aucune clé, aucune donnée personnelle : le Journal reste dans IndexedDB, hors de ce cache. */
const VERSION = "c583787";
const FICHIERS = ["site/accueil.js?v=c583787", "site/agenda.js?v=c583787", "site/app.js?v=c583787", "site/archives.js?v=c583787", "site/briefing.js?v=c583787", "site/cabinet.css?v=c583787", "site/cockpit.js?v=c583787", "site/commun.js?v=c583787", "site/consequences_synthese.js?v=c583787", "site/devises.js?v=c583787", "site/dossier_detail.js?v=c583787", "site/dossiers.js?v=c583787", "site/ecran_agenda.js?v=c583787", "site/ecran_briefing.js?v=c583787", "site/ecran_devises.js?v=c583787", "site/ecran_engrenages.js?v=c583787", "site/ecran_journal.js?v=c583787", "site/ecran_paire.js?v=c583787", "site/ecran_synthese.js?v=c583787", "site/ecran_tableau.js?v=c583787", "site/engrenages.js?v=c583787", "site/hebdo.js?v=c583787", "site/impression.js?v=c583787", "site/journal.js?v=c583787", "site/journal_logique.js?v=c583787", "site/journal_stats.js?v=c583787", "site/outils.js?v=c583787", "site/paire_graphique.js?v=c583787", "site/rapport.js?v=c583787", "site/recherche.js?v=c583787", "site/sante.js?v=c583787", "site/scenarios.js?v=c583787", "site/synthese.js?v=c583787", "site/synthese_longue.js?v=c583787", "site/synthese_suite.js?v=c583787", "site/tableau.js?v=c583787", "site/tokens.css?v=c583787", "site/v7.css?v=c583787", "site/v7_commun.js?v=c583787", "site/v8.css?v=c583787", "site/vue_ensemble.js?v=c583787", "site/vendor/lightweight-charts.standalone.production.js?v=c583787", "manifest.webmanifest", "icones/logo.svg", "icones/icone-192.png"];
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
