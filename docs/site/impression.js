/* Impression et PDF (palier 10) : aperçu avant impression à l'écran, puis impression du navigateur (« Enregistrer
   en PDF »). Trois pages A4 : thème du jour, 8 engrenages, devises. Fond blanc, sans boutons ni navigation,
   lisible en noir et blanc (textures à la place des couleurs seules), date, sources et la mention « aide à la
   décision, pas un conseil » sur chaque page. Lit uniquement docs/data/*.json : aucune requête externe. */
import { chargerJson, enErreur, el, dateCourte, dateHeure } from "./commun.js";
import { vueEnsemble } from "./vue_ensemble.js";
import { carteDevise } from "./devises.js";

const SVG = "http://www.w3.org/2000/svg";
const DEVISES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"];
const MENTION = "Aide à la décision, pas un conseil en investissement : aucun ordre d'achat ou de vente.";

function svgEl(tag, attrs) { const n = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v); return n; }

/* Textures noir et blanc de la roue (référencées par cabinet.css, bloc #impression). */
function motifs() {
  const svg = svgEl("svg", { width: 0, height: 0, "aria-hidden": "true", class: "imp-motifs" });
  const defs = svgEl("defs");
  const points = svgEl("pattern", { id: "imp-up", width: 6, height: 6, patternUnits: "userSpaceOnUse" });
  points.append(svgEl("rect", { width: 6, height: 6, fill: "#fff" }), svgEl("circle", { cx: 3, cy: 3, r: 1.5, fill: "#000" }));
  const plein = svgEl("pattern", { id: "imp-dn", width: 6, height: 6, patternUnits: "userSpaceOnUse" });
  plein.append(svgEl("rect", { width: 6, height: 6, fill: "#222" }));
  defs.append(points, plein);
  svg.appendChild(defs);
  return svg;
}

function page(numero, titre, date, genere, contenu, sources) {
  const p = el("section", "imp-page");
  p.setAttribute("aria-label", `Page ${numero} : ${titre}`);
  const tete = el("header", "imp-tete");
  tete.append(el("span", "imp-marque", "FX Desk"), el("h1", "imp-titre", titre),
              el("span", "imp-date", `Rapport du ${dateCourte(date)} · données générées ${dateHeure(genere)} · page ${numero}/3`));
  const pied = el("footer", "imp-pied");
  pied.append(el("p", null, `Sources : ${sources}`), el("p", "imp-mention", MENTION));
  p.append(tete, ...contenu, pied);
  return p;
}

function legendeTextures() {
  const ul = el("ul", "imp-legende");
  for (const [cls, nom, sens] of [["up", "Points", "risk on, ou dollar haussier quand le risque n'est pas tranché"],
                                  ["dn", "Plein foncé", "risk off, ou dollar baissier quand le risque n'est pas tranché"],
                                  ["nd", "Gris clair", "neutre"], ["hachures", "Hachures", "aucune direction déterminée"]]) {
    const li = el("li");
    li.append(el("span", `imp-pastille ${cls}`), el("b", null, `${nom} : `), document.createTextNode(sens));
    ul.appendChild(li);
  }
  return ul;
}

export function construirePages(dos, cours, rapport, site) {
  const v = dos?.vue_ensemble;
  const date = rapport?.meta?.date_rapport || v?.theme?.date_rapport;
  const genere = dos?.genere_le;
  const pages = [];
  // Page 1 : thème du jour (roue + bandeau)
  if (v && !v.indisponible) {
    const vue = vueEnsemble(v, 0, () => {}, dos.matrice_impact);
    const hero = vue.noeuds[0];
    hero.querySelectorAll(".roue-legende, .roue-raison, .bouton-briefing").forEach(n => n.remove());
    // Identifiant propre au motif de hachures : celui de la page (masquée pendant l'aperçu) ne serait pas rendu.
    hero.querySelector("pattern#hachures-roue")?.setAttribute("id", "imp-hachures");
    hero.querySelectorAll('path[fill="url(#hachures-roue)"]').forEach(n => n.setAttribute("fill", "url(#imp-hachures)"));
    hero.querySelector(".roue-cadre")?.appendChild(legendeTextures());
    const chaines = vue.noeuds[4];   // chaînes de transmission et conflits du jour
    chaines.prepend(el("h2", "imp-sous-titre", "Chaînes de transmission"));
    pages.push(page(1, "Thème du jour", date, genere, [hero, chaines],
      "calcul Python des 8 engrenages (règles et matrice d'impact, config.yaml) ; texte formulé par le modèle quand il est disponible"));
    // Page 2 : les 8 engrenages, avec la source de chaque chiffre et « À retenir »
    const grille = vue.noeuds[2];
    const briefing = new Map((v.briefing?.cartes || []).map(c => [c.numero, c]));
    [...grille.children].forEach((b, i) => {
      const c = v.cartes[i];
      if (!c) return;
      if (c.chiffre?.source || c.chiffre?.raison) b.appendChild(el("span", "imp-source",
        c.chiffre?.texte ? `Source : ${c.chiffre.source}${c.chiffre.date ? ` (${dateCourte(c.chiffre.date)})` : ""}` : `n/d : ${c.chiffre?.raison}`));
      const bf = briefing.get(c.numero);
      if (bf?.a_retenir) b.appendChild(el("span", "imp-retenir", `À retenir : ${bf.a_retenir}${bf.texte_indisponible ? ` (${bf.texte_indisponible})` : ""}`));
    });
    pages.push(page(2, "Les 8 engrenages", date, genere, [grille],
      "séries FRED, EIA, CFTC, Twelve Data et registre macro (ForexFactory), sources détaillées sous chaque chiffre"));
  } else {
    pages.push(page(1, "Thème du jour", date, genere, [el("p", "indisponible", `Indisponible : ${v?.indisponible || "dossiers.json absent"}.`)], "—"));
  }
  // Page 3 : les 9 devises (cours rebasé, MM200, repères, indicateurs, moteurs)
  const cles = new Map((site?.indicateurs_cles || []).map(l => [l.devise, l]));
  const parDevise = new Map((rapport?.devises || []).map(d => [d.devise, d]));
  const grilleDev = el("div", "dc-grille");
  for (const d of DEVISES) grilleDev.appendChild(carteDevise(d, dos, cours?.devises?.[d], cles.get(d), parDevise.get(d)));
  const legendeDev = el("p", "imp-legende-reperes", "Courbe : force de la devise rebasée à 100 sur 90 jours ; pointillé : moyenne mobile 200 jours. "
    + "Repères : ▲ plus haut · ▼ plus bas · ● dernière valeur · ◆ évènement (banque centrale, CPI, NFP), source au survol sur le site.");
  pages.push(page(3, "Devises", date, genere, [legendeDev, grilleDev],
    "série unique 5 ans (Twelve Data raccordé à la Fed H.10), moyenne mobile 200 jours, dossier 7, matrice d'impact ; repères : registre macro (ForexFactory)"));
  return pages;
}

/* Aperçu avant impression : remplace l'affichage par les trois pages ; « Imprimer / PDF » ouvre la boîte du navigateur. */
export async function ouvrirApercu(retour = null) {
  const [dos, cours, rapport, site] = await Promise.all(["data/dossiers.json", "data/cours.json", "data/latest.json", "data/site.json"].map(chargerJson));
  document.getElementById("impression")?.remove();
  const conteneur = el("div", "impression");
  conteneur.id = "impression";
  conteneur.setAttribute("role", "region");
  conteneur.setAttribute("aria-label", "Aperçu avant impression");
  const barre = el("div", "imp-barre");
  const imprimer = el("button", "bouton imp-imprimer", "Imprimer / Enregistrer en PDF"); imprimer.type = "button";
  const fermer = el("button", "bouton", "Fermer l'aperçu"); fermer.type = "button";
  barre.append(el("p", null, "Aperçu avant impression · A4 portrait · 3 pages (thème, 8 engrenages, devises) · noir et blanc"), imprimer, fermer);
  conteneur.append(barre, motifs(), ...construirePages(enErreur(dos) ? null : dos, enErreur(cours) ? null : cours,
                                                      enErreur(rapport) ? null : rapport, enErreur(site) ? null : site));
  document.body.appendChild(conteneur);
  document.body.classList.add("apercu-impression");
  const fin = () => { conteneur.remove(); document.body.classList.remove("apercu-impression"); document.removeEventListener("keydown", echap); retour?.focus?.(); };
  const echap = e => { if (e.key === "Escape") fin(); };
  document.addEventListener("keydown", echap);
  fermer.addEventListener("click", fin);
  imprimer.addEventListener("click", () => window.print());
  window.scrollTo(0, 0);
  imprimer.focus();
  return conteneur;
}
