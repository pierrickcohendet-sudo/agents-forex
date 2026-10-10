/* FX Desk — site V1. Lit uniquement docs/data/*.json (produits par le pipeline), aucune clé, aucun appel externe. */
import { chargerJson, enErreur, el, indisponible, initialiserDetail, dateHeure } from "./commun.js";
import { pageSynthese } from "./synthese.js";

const ONGLETS = {
  synthese: { titre: "Synthèse", rendu: pageSynthese },
  engrenages: { titre: "8 engrenages", module: "./engrenages.js", fonction: "pageEngrenages" },
  devises: { titre: "Devises", module: "./devises.js", fonction: "pageDevises" },
  tableau: { titre: "Tableau macro", module: "./tableau.js", fonction: "pageTableau" },
  agenda: { titre: "Agenda", bientot: "L'agenda des publications et réunions de banques centrales arrive dans une prochaine version." },
  institutions: { titre: "Institutions", bientot: "Le positionnement des institutions (rapport COT de la CFTC) arrive dans une prochaine version." },
  archives: { titre: "Archives", module: "./archives.js", fonction: "pageArchives" },
  apprendre: { titre: "Apprendre", bientot: "Les fiches de formation (concept du jour, glossaire) arrivent dans une prochaine version." },
};

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
async function afficher() {
  const hash = (location.hash || "#synthese").slice(1);
  const [id, parametre] = hash.split("/");
  const onglet = ONGLETS[id] ? id : "synthese";
  document.querySelectorAll(".onglets a").forEach(a => {
    if (a.dataset.onglet === onglet) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
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
  if ((location.hash || "#synthese").slice(1) !== hash) return;   // l'utilisateur a changé d'onglet entre-temps
  main.replaceChildren(...blocs);
  if (parametre) document.getElementById(`fiche-${parametre}`)?.scrollIntoView();
  else window.scrollTo(0, 0);
}

async function initialiser() {
  initialiserDetail();
  document.querySelectorAll(".onglets a").forEach(a => {
    if (ONGLETS[a.dataset.onglet]?.bientot) { a.classList.add("bientot"); a.title = "Bientôt disponible"; }
  });
  appliquerTheme(themeCourant());
  document.getElementById("bouton-theme").addEventListener("click", () => {
    appliquerTheme(CYCLE_THEME[(CYCLE_THEME.indexOf(themeCourant()) + 1) % CYCLE_THEME.length]);
  });
  window.addEventListener("hashchange", afficher);
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
