/* Service worker de Trading baby (lot V8, correctif « versions » du 11/11/2026).
   - Une version = un jeu complet de fichiers. À l'installation, le service worker met en cache TOUT le code de sa version
     (FICHIERS, liste écrite par core/version_site.py, adresses suffixées « ?v=<version> » comme dans l'importmap de la page).
     Une page ne reçoit donc jamais un mélange d'ancien et de nouveau code.
   - Pas d'activation en pleine session : la nouvelle version attend (« waiting »). La page affiche « Nouvelle version
     disponible : recharger » ; au chargement suivant (ou au clic), elle demande l'activation puis se recharge.
   - Données (data/*.json) : « réseau d'abord, cache en secours » ; si c'est le cache qui répond, la page reçoit la date
     de ces données (« données hors connexion du JJ/MM HH:MM »).
   Aucune clé, aucune donnée personnelle : le Journal reste dans IndexedDB, hors de ce cache. */
const VERSION = "3d04ccf";
const FICHIERS = ["site/accueil.js?v=3d04ccf", "site/agenda.js?v=3d04ccf", "site/app.js?v=3d04ccf", "site/archives.js?v=3d04ccf", "site/briefing.js?v=3d04ccf", "site/cabinet.css?v=3d04ccf", "site/cockpit.js?v=3d04ccf", "site/commun.js?v=3d04ccf", "site/consequences_synthese.js?v=3d04ccf", "site/devises.js?v=3d04ccf", "site/documentaire.js?v=3d04ccf", "site/dossier_detail.js?v=3d04ccf", "site/dossiers.js?v=3d04ccf", "site/ecran_agenda.js?v=3d04ccf", "site/ecran_briefing.js?v=3d04ccf", "site/ecran_devises.js?v=3d04ccf", "site/ecran_engrenages.js?v=3d04ccf", "site/ecran_journal.js?v=3d04ccf", "site/ecran_paire.js?v=3d04ccf", "site/ecran_synthese.js?v=3d04ccf", "site/ecran_tableau.js?v=3d04ccf", "site/engrenages.js?v=3d04ccf", "site/engrenages_tableau.js?v=3d04ccf", "site/engrenages_v7.js?v=3d04ccf", "site/hebdo.js?v=3d04ccf", "site/impression.js?v=3d04ccf", "site/journal.js?v=3d04ccf", "site/journal_editeur.js?v=3d04ccf", "site/journal_lecture.js?v=3d04ccf", "site/journal_logique.js?v=3d04ccf", "site/journal_stats.js?v=3d04ccf", "site/journal_v4.js?v=3d04ccf", "site/journal_v5.js?v=3d04ccf", "site/moteurs.js?v=3d04ccf", "site/outils.js?v=3d04ccf", "site/paire_graphique.js?v=3d04ccf", "site/rapport.js?v=3d04ccf", "site/recherche.js?v=3d04ccf", "site/sante.js?v=3d04ccf", "site/scenarios.js?v=3d04ccf", "site/synthese.js?v=3d04ccf", "site/synthese_longue.js?v=3d04ccf", "site/synthese_suite.js?v=3d04ccf", "site/synthese_v9.js?v=3d04ccf", "site/tableau.js?v=3d04ccf", "site/tokens.css?v=3d04ccf", "site/v10.css?v=3d04ccf", "site/v11.css?v=3d04ccf", "site/v12.css?v=3d04ccf", "site/v13.css?v=3d04ccf", "site/v14.css?v=3d04ccf", "site/v7.css?v=3d04ccf", "site/v7_commun.js?v=3d04ccf", "site/v8.css?v=3d04ccf", "site/v9.css?v=3d04ccf", "site/vue_ensemble.js?v=3d04ccf", "site/vendor/lightweight-charts.standalone.production.js?v=3d04ccf", "manifest.webmanifest", "icones/logo.svg", "icones/icone-192.png"];
const CODE = `tb-code-${VERSION}`, DONNEES = "tb-donnees";

self.addEventListener("install", e => {
  // Tout ou rien : si un fichier manque, l'installation échoue et l'ancienne version reste en place (nouvel essai au
  // prochain chargement). Jamais de skipWaiting ici : c'est la page qui décide du moment (rechargement).
  e.waitUntil(Promise.all([
    caches.open(CODE).then(c => c.addAll(["./", "./index.html", ...FICHIERS].map(u => new Request(u, { cache: "reload" })))),
    // Lot V13 : le documentaire de la semaine est lisible hors connexion même si l'onglet n'a jamais été ouvert (sans bloquer)
    caches.open(DONNEES).then(c => c.add(new Request("data/documentaire.json", { cache: "reload" }))).catch(() => {}),
  ]));
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
