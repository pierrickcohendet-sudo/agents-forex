/* FX Desk — site V1. Lit uniquement docs/data/*.json (produits par le pipeline), aucune clé, aucun appel externe. */
import { chargerJson, enErreur, el, indisponible, initialiserDetail, initialiserCertificats, dateHeure, appliquerGlossaire } from "./commun.js";

/* Lot V6 : 6 onglets principaux, le reste dans le menu « Plus ». */
const ONGLETS = {
  synthese: { titre: "Synthèse", module: "./rapport.js", fonction: "pageRapport" },   // fusion Accueil + Rapport + Hebdo + Mensuel
  tableau: { titre: "Tableau de bord", module: "./tableau.js", fonction: "pageTableauDeBord" },   // tableau macro + point de marché
  devises: { titre: "Devises", module: "./devises.js", fonction: "pageDevises" },
  agenda: { titre: "Agenda", module: "./agenda.js", fonction: "pageAgenda" },
  engrenages: { titre: "8 engrenages", module: "./engrenages.js", fonction: "pageEngrenages" },   // cockpit, dossiers, outils
  journal: { titre: "Journal", module: "./journal.js", fonction: "pageJournal" },
  // Menu « Plus »
  scenarios: { titre: "Scénarios et simulateur", module: "./scenarios.js", fonction: "pageScenarios" },
  sante: { titre: "Santé des données", module: "./sante.js", fonction: "pageSante" },
  archives: { titre: "Archives", module: "./archives.js", fonction: "pageArchives" },
};
/* Anciennes adresses (#…) : redirigées vers le bon onglet. */
const REDIRECTIONS = { rapport: "synthese", accueil: "synthese", hebdo: "synthese", mensuel: "synthese", apprendre: "synthese",
                       institutions: "engrenages", outils: "engrenages", "tableau-macro": "tableau" };

/* ------------------------------------------------------------------ thème */
const CYCLE_THEME = ["auto", "clair", "noir"];
function themeCourant() {
  const t = document.documentElement.getAttribute("data-theme");
  return t === "clair" || t === "noir" ? t : "auto";
}
function appliquerTheme(t) {
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  try { if (t === "auto") localStorage.removeItem("fxdesk-theme"); else localStorage.setItem("fxdesk-theme", t); }
  catch (e) { /* stockage indisponible : le choix vaut pour cette visite */ }
  document.getElementById("bouton-theme").textContent = `Thème : ${t}`;
}

/* ---------------------------------------------------------------- routage */
// Page par défaut : le Rapport du jour le matin (avant 13:00 à Paris, comme rapport.heure_bascule_accueil dans
// config.yaml), le tableau de bord « Aujourd'hui » ensuite.
function pageParDefaut() { return "synthese"; }
async function afficher() {
  let hash = (location.hash || `#${pageParDefaut()}`).slice(1);
  const [base, ...reste] = hash.split("/");
  if (REDIRECTIONS[base]) {   // ancienne adresse : remplacée sans nouvelle entrée d'historique
    hash = [REDIRECTIONS[base], ...(base === "outils" ? ["outils"] : base === "hebdo" ? [] : reste)].join("/");
    history.replaceState(null, "", `#${hash}`);
  }
  // Lien direct vers un dossier d'engrenage : #g=N (équivaut à #engrenages/g=N)
  const [id, parametre] = /^g=[1-8]$/.test(hash) ? ["engrenages", hash] : hash.split("/");
  const onglet = ONGLETS[id] ? id : pageParDefaut();
  document.querySelectorAll(".onglets a[data-onglet]").forEach(a => {
    if (a.dataset.onglet === onglet) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  const plus = document.getElementById("menu-plus");
  if (plus) { plus.open = false; plus.classList.toggle("actif", ["scenarios", "sante", "archives"].includes(onglet)); }
  const conf = ONGLETS[onglet];
  document.title = `${conf.titre} — FX Desk`;
  const main = document.getElementById("contenu");
  main.replaceChildren(el("p", "chargement", "Chargement…"));
  let blocs;
  try {
    if (conf.bientot) {
      const c = el("section", "carte");
      c.appendChild(el("h2", null, conf.titre));
      c.appendChild(el("p", "indisponible", `Bientôt disponible. ${conf.bientot}`));
      blocs = [c];
    } else if (conf.rendu) {
      blocs = await conf.rendu(parametre);
    } else {
      const module = await import(conf.module);
      blocs = await module[conf.fonction](parametre);
    }
  } catch (e) {
    console.error(e);
    blocs = [indisponible(conf.titre, `erreur d'affichage (${e.message})`)];
  }
  if ((location.hash || `#${pageParDefaut()}`).slice(1) !== hash) return;   // l'utilisateur a changé d'onglet entre-temps
  main.replaceChildren(...blocs);
  appliquerGlossaire(main);   // glossaire unique au survol (lot V6)
  if (parametre === "outils") { const o = [...main.querySelectorAll("details.voir-detail")].find(d => /Outils/.test(d.textContent)); if (o) { o.open = true; o.scrollIntoView(); } }
  else if (parametre && !parametre.startsWith("g=")) document.getElementById(`fiche-${parametre}`)?.scrollIntoView();
  else window.scrollTo(0, 0);
}

async function initialiser() {
  initialiserDetail();
  initialiserCertificats();
  document.addEventListener("click", ev => {   // menu « Plus » : se ferme au clic à l'extérieur
    const plus = document.getElementById("menu-plus");
    if (plus?.open && !plus.contains(ev.target)) plus.open = false;
  });
  appliquerTheme(themeCourant());
  document.getElementById("bouton-theme").addEventListener("click", () => {
    appliquerTheme(CYCLE_THEME[(CYCLE_THEME.indexOf(themeCourant()) + 1) % CYCLE_THEME.length]);
  });
  // Impression / PDF : aperçu avant impression (3 pages A4), module chargé au premier clic seulement
  const boutonImprimer = document.getElementById("bouton-imprimer");
  boutonImprimer.addEventListener("click", async () => {
    try { (await import("./impression.js")).ouvrirApercu(boutonImprimer); }
    catch (e) { console.error(e); window.print(); }
  });
  // #g=N mis à jour par le sélecteur via history.replaceState : pas d'événement hashchange, pas de rechargement
  window.addEventListener("hashchange", afficher);
  const entete = document.querySelector(".entete");
  const hauteur = () => document.documentElement.style.setProperty("--entete-h",
    `${entete && getComputedStyle(entete).position === "sticky" ? entete.offsetHeight : 0}px`);
  hauteur(); window.addEventListener("resize", hauteur);
  const site = await chargerJson("data/site.json");
  if (!enErreur(site)) {
    const r = site.regime || {};
    const lien = document.getElementById("lien-notion");
    if (r.notion_url) {
      lien.href = r.notion_url;
      lien.hidden = false;
      lien.textContent = r.notion_page_du_jour ? "Ouvrir dans Notion" : "Ouvrir la base Notion";
    }
    document.getElementById("pied-meta").textContent =
      `Rapport du ${r.date_rapport || "—"} · site.json généré ${dateHeure(site.genere_le)}`;
  }
  afficher();
}

initialiser();
