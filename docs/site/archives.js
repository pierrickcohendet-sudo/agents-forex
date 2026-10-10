/* Onglet Archives : liste des rapports (docs/data/index.json) et lecture d'un jour (#archives/AAAA-MM-JJ). */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, DRAPEAUX } from "./commun.js";

const REGIME = { risk_on: "Risk On", risk_off: "Risk Off", neutre: "Neutre" };
const RELECTURE = { ok: "relu", a_revoir: "points de vigilance", non_evalue: "non relu" };
const TYPES = { quotidien: "Quotidien", hebdomadaire: "Hebdomadaire", mensuel: "Mensuel" };

async function jour(date) {
  const r = await chargerJson(`data/${date}.json`);
  if (enErreur(r)) return [indisponible(`Rapport du ${dateCourte(date)}`, r?.__erreur)];
  const c = el("section", "carte");
  const retour = el("a", null, "← Toutes les archives"); retour.href = "#archives";
  c.appendChild(retour);
  c.appendChild(el("h2", null, `Rapport du ${dateCourte(date)}`));
  const sg = r.synthese_globale || {};
  c.appendChild(el("p", "sous-titre", `${TYPES[r.meta?.type_rapport] || r.meta?.type_rapport || ""} · régime ${REGIME[sg.biais_macro_global] || "n/d"} · relecture ${RELECTURE[r.critique?.validation] || "non relu"} · généré ${dateHeure(r.meta?.genere_le)}`));
  if (sg.commentaire) c.appendChild(el("p", "phrase", sg.commentaire));
  const defile = el("div", "defile");
  const t = el("table", "dense");
  const tete = el("tr"); for (const h of ["Devise", "Score", "Résumé du jour"]) tete.appendChild(el("th", null, h));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  for (const d of r.devises || []) {
    const tr = el("tr");
    tr.appendChild(el("td", null, `${DRAPEAUX[d.devise] || ""} ${d.devise}`));
    tr.appendChild(el("td", null, d.score_confluence ?? "n/d"));
    const td = el("td", "texte-long", d.score_confluence === null || d.score_confluence === undefined
      ? `Analyse indisponible : ${d.raison_indisponibilite || "raison inconnue"}` : d.synthese_une_phrase || "—");
    tr.appendChild(td);
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t); c.appendChild(defile);
  const brut = el("a", null, "Fichier JSON complet de ce rapport"); brut.href = `data/${date}.json`;
  const p = el("p", "note"); p.appendChild(brut); c.appendChild(p);
  return [c];
}

export async function pageArchives(parametre) {
  if (parametre && /^\d{4}-\d{2}-\d{2}$/.test(parametre)) return jour(parametre);
  const index = await chargerJson("data/index.json");
  if (enErreur(index) || !Array.isArray(index)) return [indisponible("Archives", index?.__erreur || "index.json illisible")];
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Archives"));
  c.appendChild(el("p", "sous-titre", `${index.length} rapport(s) disponible(s). Touchez un jour pour le lire.`));
  const ul = el("ul", "archives");
  for (const e of index) {
    const entree = typeof e === "string" ? { date: e } : e;
    const li = el("li"); const a = el("a"); a.href = `#archives/${entree.date}`;
    a.appendChild(el("span", "tabulaire", dateCourte(entree.date)));
    a.appendChild(el("span", "note", [TYPES[entree.type] || entree.type, REGIME[entree.biais], RELECTURE[entree.relecture]].filter(Boolean).join(" · ")));
    li.appendChild(a); ul.appendChild(li);
  }
  c.appendChild(ul);
  return [c];
}
