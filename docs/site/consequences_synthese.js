/* Synthèse hebdomadaire et mensuelle des conséquences par devise (docs/data/consequences_synthese.json).
   Faits, bilan et phrase de repli : calcul Python (tableau des conséquences, borne de Wilson) ; texte : un appel
   regroupé du modèle, affiché seulement s'il existe. Affichée dans les onglets Hebdo et Mensuel des engrenages
   et sur la page Devises. Aucune requête externe. */
import { chargerJson, enErreur, el, dateHeure } from "./commun.js";

const TITRES = { hebdo: "Conséquences de la semaine, par devise", mensuel: "Conséquences du mois, par devise" };
const LECTURES = { Soutien: "pos", Pression: "neg" };
const virgule = v => v === null || v === undefined ? "—" : String(v).replace(".", ",").replace("-", "−");

function tableFaits(f) {
  const lignes = (f.lignes || []);
  if (!lignes.length) return null;
  const d = el("details", "sous");
  d.appendChild(el("summary", null, "Voir les faits calculés en Python"));
  const defile = el("div", "defile");
  const t = el("table", "dense compact");
  const tete = el("tr");
  for (const h of ["Engrenage (moteur)", "Lecture", "Cas", "Sens attendu", "Borne de Wilson 90 %"]) tete.appendChild(el("th", null, h));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  for (const x of lignes) {
    const tr = el("tr");
    tr.appendChild(el("td", null, `${x.engrenage}. ${x.nom} (${x.moteur || "—"})`));
    const lec = el("td", LECTURES[x.lecture] || "", x.lecture || "n/d");
    if (x.raison) lec.title = x.raison;
    tr.appendChild(lec);
    tr.appendChild(el("td", "tabulaire", x.n ?? "—"));
    tr.appendChild(el("td", "tabulaire", x.part_sens_attendu === null || x.part_sens_attendu === undefined ? "—" : `${x.part_sens_attendu} %`));
    tr.appendChild(el("td", "tabulaire", x.borne_wilson_90 === null || x.borne_wilson_90 === undefined ? "—" : `${virgule(x.borne_wilson_90)} %`));
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t); d.appendChild(defile);
  return d;
}

/* Section d'une période ; `devise` : n'afficher que cette devise (sinon les 9). */
export function sectionSynthese(entree, type, devise = null) {
  const c = el("section", "carte cs-section");
  c.appendChild(el("h2", null, `${TITRES[type]}${entree?.periode ? ` — ${entree.periode}` : ""}`));
  if (!entree) {
    c.appendChild(el("p", "indisponible", type === "hebdo"
      ? "Pas encore produite : première synthèse au passage hebdomadaire du dimanche."
      : "Pas encore produite : première synthèse au premier passage du mois (le 1er)."));
    return c;
  }
  const modele = entree.statut === "ok";
  c.appendChild(el("p", "sous-titre", `Faits calculés en Python le ${dateHeure(entree.genere_le)} (sensibilité sur 5 ans, médiane sur le mois qui suit un mouvement d'1 écart-type, borne de Wilson à 90 %). `
    + (modele ? `Texte formulé par ${entree.redige_par?.libelle || "le modèle"} ; toute phrase citant un chiffre absent des faits est retirée.`
              : "Texte du modèle indisponible : phrase 100 % Python ci-dessous.")));
  if (!modele) c.appendChild(el("p", "indisponible", `Texte indisponible : ${entree.quota_atteint ? "quota du jour" : String(entree.raison || "modèle indisponible").replace(/^indisponible\s*:\s*/i, "")}.`));
  // Synthèse d'ensemble : moteurs (nom, variation, zone), chiffres de la semaine, évènements de la semaine suivante
  if (!devise && entree.synthese) {
    const g = el("div", "cs-ensemble");
    g.appendChild(el("p", "texte", entree.synthese.texte || entree.synthese.phrase_python));
    g.appendChild(el("span", "source", entree.synthese.texte ? `formulé par ${entree.redige_par?.libelle || "le modèle"} à partir des faits Python` : "calcul Python"));
    c.appendChild(g);
  }
  const liste = el("div", "cs-liste");
  for (const [d, x] of Object.entries(entree.devises || {})) {
    if (devise && d !== devise) continue;
    const bloc = el("article", "cs-devise");
    const tete = el("div", "cs-tete");
    const bilan = x.faits?.bilan || "—";
    tete.append(el("b", "cs-code", d), el("span", `cs-bilan ${bilan === "soutenue" ? "pos" : bilan === "sous pression" ? "neg" : ""}`, bilan));
    bloc.appendChild(tete);
    if (x.texte) {
      bloc.appendChild(el("p", "texte", x.texte));
      bloc.appendChild(el("p", "note", `Repli Python : ${x.phrase_python}`));
    } else {
      bloc.appendChild(el("p", "texte", x.phrase_python));
      bloc.appendChild(el("span", "source", "calcul Python"));
    }
    const faits = tableFaits(x.faits || {}); if (faits) bloc.appendChild(faits);
    liste.appendChild(bloc);
  }
  c.appendChild(liste);
  if ((entree.controles || []).length) c.appendChild(el("p", "tag-alerte", `Contrôles : ${entree.controles.join(" · ")}`));
  c.appendChild(el("p", "note", entree.mention || "Corrélation n'est pas causalité ; aide à la décision, jamais un ordre d'achat ou de vente."));
  return c;
}

export async function chargerSyntheses() {
  const s = await chargerJson("data/consequences_synthese.json");
  return enErreur(s) ? {} : s;
}

/* Page Devises : sélecteur Hebdo / Mensuel au-dessus de la synthèse. */
export async function blocDevises() {
  const s = await chargerSyntheses();
  const enveloppe = el("div", "cs-devises");
  const nav = el("div", "sc-seg cs-seg");
  nav.setAttribute("role", "group"); nav.setAttribute("aria-label", "Période de la synthèse des conséquences");
  const zone = el("div");
  let actif = s.hebdo || !s.mensuel ? "hebdo" : "mensuel";
  const boutons = ["hebdo", "mensuel"].map(t => {
    const b = el("button", null, t === "hebdo" ? "Hebdo" : "Mensuel"); b.type = "button";
    b.addEventListener("click", () => { actif = t; rendre(); });
    nav.appendChild(b); return b;
  });
  function rendre() {
    boutons.forEach((b, i) => b.setAttribute("aria-pressed", String(["hebdo", "mensuel"][i] === actif)));
    zone.replaceChildren(sectionSynthese(s[actif], actif));
  }
  rendre();
  enveloppe.append(nav, zone);
  return enveloppe;
}
