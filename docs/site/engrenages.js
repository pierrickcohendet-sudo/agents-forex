/* Onglet « 8 engrenages » : synthèse globale (rapport du jour, synthese_globale.engrenages). */
import { chargerJson, enErreur, el, indisponible, dateHeure } from "./commun.js";

const DOLLAR = { haussier: "Dollar ↑", baissier: "Dollar ↓", neutre: "Dollar =" };
const RISQUE = { risk_on: "Risk on", risk_off: "Risk off", neutre: "Risque neutre" };
const CONVICTION = { faible: "faible", moyen: "moyenne", eleve: "élevée" };

function sourceTexte(sources, ids) {
  return (ids || []).filter(i => sources.get(i)).map(i => {
    const s = sources.get(i); return `${s.source} · ${String(s.detail || "").slice(0, 60)} · ${s.date || "s.d."}`;
  }).join(" ; ");
}
export function directionCourte(d) {
  const t = [DOLLAR[d?.dollar], RISQUE[d?.risque]].filter(Boolean).join(" · ") || "non déterminée";
  const dev = d?.devises_concernees || [];
  return dev.length ? `${t} (${dev.join(", ")})` : t;
}
function classeDirection(d) {
  if (d?.risque === "risk_off" || d?.dollar === "baissier") return "neg";
  if (d?.risque === "risk_on" || d?.dollar === "haussier") return "pos";
  return "";
}
const phrase = t => { const p = String(t || "").split(". ")[0].trim(); return p ? (p.endsWith(".") ? p : `${p}.`) : "—"; };

function tableauRecap(eng) {
  const defile = el("div", "defile");
  const t = el("table", "dense compact");
  const tete = el("tr");
  for (const h of ["Engrenage", "Direction", "Conviction", "En une phrase"]) tete.appendChild(el("th", null, h));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  for (const e of eng.engrenages || []) {
    const tr = el("tr");
    tr.appendChild(el("td", null, `${e.numero}. ${e.nom}`));
    tr.appendChild(el("td", classeDirection(e.direction), directionCourte(e.direction)));
    tr.appendChild(el("td", null, CONVICTION[e.conviction?.niveau] || (e.donnees_insuffisantes ? "—" : "n/d")));
    tr.appendChild(el("td", "texte-long", phrase(e.diagnostic)));
    tr.addEventListener("click", () => {
      location.hash = "#engrenages";
      setTimeout(() => { const d = document.getElementById(`engrenage-${e.numero}`); if (d) { d.open = true; d.scrollIntoView(); } }, 300);
    });
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t);
  return defile;
}

function chaines(eng) {
  const blocs = [];
  for (const c of eng.chaines || []) {
    const b = el("div", "encadre bleu");
    b.appendChild(el("strong", null, `Chaîne de transmission — ${c.titre || "du jour"}`));
    const p = el("p", "texte");
    c.maillons.forEach((m, i) => {
      if (i) p.appendChild(el("span", "fleche", " → "));
      p.appendChild(document.createTextNode(`${m.texte} `));
      p.appendChild(el("span", "numero", `(${m.engrenage})`));
      if (m.non_sourcee) p.appendChild(el("span", "tag-alerte", " [non sourcé]"));
    });
    b.appendChild(p); blocs.push(b);
  }
  if ((eng.conflits || []).length) {
    const b = el("div", "encadre orange");
    b.appendChild(el("strong", null, "Engrenages en conflit"));
    const ul = el("ul");
    for (const c of eng.conflits) ul.appendChild(el("li", null, `(${c.engrenages[0]}) contre (${c.engrenages[1]}) : ${c.texte}`));
    b.appendChild(ul); blocs.push(b);
  }
  return blocs;
}

function concept(eng, sources) {
  const c = eng.concept;
  if (!c) return null;
  const b = el("div", "encadre violet");
  b.appendChild(el("strong", null, `🎓 Concept du jour — ${c.titre}`));
  b.appendChild(el("p", "texte", c.explication || c.definition || ""));
  if (c.exemple) { const p = el("p", "texte"); p.appendChild(el("strong", null, "Aujourd'hui : ")); p.appendChild(document.createTextNode(c.exemple)); b.appendChild(p); }
  const s = sourceTexte(sources, c.source_ids); if (s) b.appendChild(el("p", "source", s));
  return b;
}

function ficheEngrenage(e, sources) {
  const d = el("details", "carte fiche");
  d.id = `engrenage-${e.numero}`;
  const s = el("summary");
  s.appendChild(el("span", "fiche-nom", `${e.numero}. ${e.nom}`));
  s.appendChild(el("span", `note ${classeDirection(e.direction)}`, directionCourte(e.direction)));
  d.appendChild(s);
  const corps = el("div", "fiche-corps");
  const diag = el("p", "texte", e.diagnostic);
  if (e.non_source) diag.appendChild(el("span", "tag-alerte", " [non sourcé]"));
  else { const src = sourceTexte(sources, e.source_ids); if (src) diag.appendChild(el("span", "source", ` — ${src}`)); }
  corps.appendChild(diag);
  if (!e.donnees_insuffisantes) {
    const dir = el("p", "texte"); dir.appendChild(el("strong", null, "Direction : "));
    dir.appendChild(document.createTextNode(`${directionCourte(e.direction)}. ${e.direction?.texte || ""}`));
    corps.appendChild(dir);
    const regle = e.direction?.calculee;
    if (regle?.regle && (regle.dollar || regle.risque)) corps.appendChild(el("p", "note", `Règle Python : ${regle.regle}.`));
    if (e.comprendre) { const p = el("p", "texte"); p.appendChild(el("strong", null, "📘 Comprendre : ")); p.appendChild(document.createTextNode(e.comprendre)); corps.appendChild(p); }
    if (e.desk) { const p = el("p", "texte"); p.appendChild(el("strong", null, "🎯 Ce que regarde un desk : ")); p.appendChild(document.createTextNode(e.desk)); corps.appendChild(p); }
    if (e.conviction?.niveau) corps.appendChild(el("p", "note",
      `Conviction ${CONVICTION[e.conviction.niveau]} (${e.conviction.origine}) — ${e.conviction.justification || ""}`));
  }
  if ((e.donnees_calculees || []).length) {
    const det = el("details", "sous");
    det.appendChild(el("summary", null, `Données utilisées (${e.donnees_calculees.length})`));
    const ul = el("ul");
    for (const x of e.donnees_calculees) {
      const li = el("li", null, x.texte);
      const src = sourceTexte(sources, [x.source_id]); if (src) li.appendChild(el("span", "source", ` — ${src}`));
      ul.appendChild(li);
    }
    det.appendChild(ul); corps.appendChild(det);
  }
  d.appendChild(corps);
  return d;
}

/* Carte compacte pour l'onglet Synthèse (null si la synthèse n'existe pas encore). */
export function carteEngrenagesCompacte(rapport) {
  const eng = rapport?.synthese_globale?.engrenages;
  if (!eng) return null;
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Les 8 engrenages"));
  if (eng.statut !== "ok") {
    c.appendChild(el("p", "indisponible", `Indisponible : ${String(eng.raison || eng.statut).replace(/^indisponible\s*:\s*/i, "")}.`));
    return c;
  }
  c.appendChild(el("p", "sous-titre", "Direction et conviction calculées en Python quand les données le permettent. Touchez une ligne pour le détail."));
  c.appendChild(tableauRecap(eng));
  for (const b of chaines(eng)) c.appendChild(b);
  const sources = new Map((rapport.sources_citees || []).map(s => [s.id, s]));
  const cpt = concept(eng, sources); if (cpt) c.appendChild(cpt);
  return c;
}

export async function pageEngrenages() {
  const rapport = await chargerJson("data/latest.json");
  if (enErreur(rapport)) return [indisponible("8 engrenages", rapport?.__erreur)];
  const eng = rapport.synthese_globale?.engrenages;
  if (!eng) return [indisponible("8 engrenages", "synthèse non générée pour ce rapport (première version livrée le 10/10/2026)")];
  if (eng.statut !== "ok") return [indisponible("8 engrenages", String(eng.raison || eng.statut).replace(/^indisponible\s*:\s*/i, ""))];
  const sources = new Map((rapport.sources_citees || []).map(s => [s.id, s]));
  const tete = el("section", "carte");
  tete.appendChild(el("h2", null, "Les 8 engrenages"));
  tete.appendChild(el("p", "sous-titre", `Rapport du ${rapport.meta?.date_rapport} · rédigé par ${eng.redige_par?.libelle || "modèle inconnu"} le ${dateHeure(eng.genere_le)}. Les directions et convictions sont calculées en Python quand les données le permettent ; le modèle formule.`));
  tete.appendChild(tableauRecap(eng));
  for (const b of chaines(eng)) tete.appendChild(b);
  const fiches = (eng.engrenages || []).map(e => ficheEngrenage(e, sources));
  const fin = el("section", "carte");
  const cpt = concept(eng, sources);
  if (cpt) fin.appendChild(cpt);
  if ((eng.controles || []).length) fin.appendChild(el("p", "tag-alerte", `Points de vigilance : ${eng.controles.join(" · ")}`));
  fin.appendChild(el("p", "note", "Aide à la décision uniquement : aucun signal d'achat ou de vente."));
  return [tete, ...fiches, fin];
}
