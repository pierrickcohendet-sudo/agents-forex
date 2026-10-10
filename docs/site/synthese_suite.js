/* Synthèse, suite : heatmap des surprises, classement des devises, tuiles marchés (palier 2). */
import { chargerJson, enErreur, el, indisponible, dateCourte, ouvrirDetail, listeDefinitions, DRAPEAUX } from "./commun.js";
import { carteEngrenagesCompacte } from "./engrenages.js";

const COURTS = {
  taux_directeur: "Taux", cpi: "CPI", cpi_core: "CPI core", pib: "PIB", pmi_manufacturier: "PMI man.",
  pmi_services: "PMI serv.", chomage: "Chômage", emploi: "Emploi", ventes_detail: "Ventes", balance_commerciale: "Balance",
};

/* Couleur d'une case : mélange de la couleur du thème avec le fond de carte, intensité ∝ |surprise|. */
function couleurSurprise(z, plafond) {
  if (z === null || z === undefined || Math.abs(z) < 0.1) return null;
  const pct = Math.round(18 + 62 * Math.min(1, Math.abs(z) / Math.min(plafond || 3, 2)));
  return `color-mix(in srgb, var(${z > 0 ? "--positif" : "--negatif"}) ${pct}%, var(--carte))`;
}
const formatZ = z => (z === null || z === undefined ? "—" : `${z > 0 ? "+" : ""}${z.toFixed(1).replace(".", ",")}`);

function heatmap(site) {
  const h = site.heatmap;
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Heatmap des surprises macro"));
  if (!h || !(h.lignes || []).length) {
    c.appendChild(el("p", "indisponible", "Indisponible : tableau macro absent de site.json."));
    return c;
  }
  c.appendChild(el("p", "sous-titre", "Dernière publication de chaque indicateur vs consensus. Vert : au-dessus, rouge : en dessous (chômage inversé), gris : en ligne ou sans consensus. Touchez une case."));
  const defile = el("div", "defile");
  const table = el("table", "dense heatmap");
  const tete = el("tr");
  tete.appendChild(el("th", null, "Devise"));
  for (const ind of h.indicateurs) { const th = el("th", null, COURTS[ind.id] || ind.libelle); th.title = ind.libelle; tete.appendChild(th); }
  tete.appendChild(el("th", null, "Indice 30 j"));
  const thead = el("thead"); thead.appendChild(tete); table.appendChild(thead);
  const corps = el("tbody");
  for (const ligne of h.lignes) {
    const tr = el("tr");
    tr.appendChild(el("td", null, `${DRAPEAUX[ligne.devise] || ""} ${ligne.devise}`));
    for (const ind of h.indicateurs) {
      const cel = ligne.cellules[ind.id] || {};
      const td = el("td", "case");
      if (cel.etat !== "valeur") td.appendChild(el("span", "nd", "n/d"));
      else td.textContent = formatZ(cel.z);
      const fond = couleurSurprise(cel.z, h.plafond);
      if (fond) td.style.background = fond;
      td.addEventListener("click", ev => {
        ev.stopPropagation();
        const paires = cel.etat === "valeur"
          ? [["Réel", cel.texte], ["Consensus", cel.consensus], ["Précédent", cel.precedent],
             ["Date", dateCourte(cel.date)], ["Source", cel.source],
             ["Surprise normalisée", cel.z === null ? `— (${cel.raison || "pas de consensus"})` : formatZ(cel.z)]]
          : [["Valeur", "n/d"], ["Raison", cel.raison]];
        ouvrirDetail(`${ligne.devise} — ${ind.libelle}`, [listeDefinitions(paires), el("p", "note", h.explication)]);
      });
      tr.appendChild(td);
    }
    const i30 = ligne.indice_30j;
    const td = el("td", "case");
    if (i30 && i30.indice !== null && i30.indice !== undefined) {
      td.textContent = formatZ(i30.indice);
      const fond = couleurSurprise(i30.indice, 2); if (fond) td.style.background = fond;
      td.addEventListener("click", () => ouvrirDetail(`${ligne.devise} — indice de surprise 30 j`, [listeDefinitions([
        ["Indice", formatZ(i30.indice)], ["Fenêtre précédente", i30.precedent === null ? "n/d" : formatZ(i30.precedent)],
        ["Tendance", i30.tendance], ["Publications", i30.n], ["Source", "calcul Python sur le registre macro"]])]));
    } else td.appendChild(el("span", "nd", "n/d"));
    tr.appendChild(td);
    corps.appendChild(tr);
  }
  table.appendChild(corps);
  defile.appendChild(table);
  c.appendChild(defile);
  return c;
}

const LIBELLES_PROFIL = { on: "Risk On", off: "Risk Off", neutre: "Neutre" };
function classement(rapport) {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Classement des devises"));
  const liste = rapport?.synthese_globale?.classement_devises || [];
  if (!liste.length) { c.appendChild(el("p", "indisponible", "Indisponible : classement absent du rapport du jour.")); return c; }
  c.appendChild(el("p", "sous-titre", "Score de confluence 0-100 (calcul Python). Touchez une devise pour sa fiche."));
  const ol = el("ol", "classement");
  for (const d of liste) {
    const li = el("li");
    const lien = el("a", null);
    lien.href = `#devises/${d.devise}`;
    lien.appendChild(el("span", "rang tabulaire", String(d.rang)));
    lien.appendChild(el("span", "nom", `${DRAPEAUX[d.devise] || ""} ${d.devise}`));
    const barre = el("span", "barre large"); const rempli = el("span");
    rempli.style.width = `${d.score_confluence}%`; barre.appendChild(rempli);
    lien.appendChild(barre);
    lien.appendChild(el("span", "score tabulaire", String(d.score_confluence)));
    lien.appendChild(el("span", "profil", LIBELLES_PROFIL[d.risk_on_off] || ""));
    li.appendChild(lien);
    ol.appendChild(li);
  }
  c.appendChild(ol);
  const absentes = rapport.synthese_globale.devises_indisponibles || [];
  if (absentes.length) c.appendChild(el("p", "note", `Exclues aujourd'hui (analyse indisponible) : ${absentes.join(", ")}.`));
  c.appendChild(el("p", "note", "Profil Risk On / Off : profil structurel de la devise, pas une direction du jour."));
  return c;
}

/* ------------------------------------------------------------- marchés */
const SVG = "http://www.w3.org/2000/svg";
function sparkline(points, couleur) {
  const s = document.createElementNS(SVG, "svg");
  s.setAttribute("viewBox", "0 0 120 36"); s.setAttribute("class", "sparkline"); s.setAttribute("aria-hidden", "true");
  s.setAttribute("preserveAspectRatio", "none");
  const v = points.map(p => p[1]);
  const min = Math.min(...v), max = Math.max(...v), et = max - min || 1;
  const d = points.map((p, i) => `${i ? "L" : "M"} ${(i / (points.length - 1 || 1)) * 120} ${33 - ((p[1] - min) / et) * 30}`).join(" ");
  const path = document.createElementNS(SVG, "path");
  path.setAttribute("d", d); path.setAttribute("fill", "none"); path.setAttribute("stroke", couleur);
  path.setAttribute("stroke-width", "1.6"); path.setAttribute("vector-effect", "non-scaling-stroke");
  s.appendChild(path);
  return s;
}

const TUILES = [["vix", "vix", "VIX"], ["petrole", "wti", "Pétrole WTI"], ["dollar", "dollar", "Indice dollar large (Fed)"]];
function marches(marche) {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Marchés"));
  if (enErreur(marche)) { c.appendChild(el("p", "indisponible", `Indisponible : ${marche?.__erreur || "marche.json absent"}.`)); return c; }
  c.appendChild(el("p", "sous-titre", "Trois mois, FRED. L'indice dollar est l'indice large de la Fed, pas le DXY (payant)."));
  const grille = el("div", "tuiles");
  for (const [graphique, courbe, libelle] of TUILES) {
    const g = (marche.graphiques || {})[graphique];
    const k = g?.courbes?.[courbe];
    const tuile = el("button", "tuile");
    tuile.type = "button";
    tuile.appendChild(el("span", "tuile-titre", libelle));
    if (!k || !(k.points || []).length) {
      tuile.appendChild(el("span", "indisponible", "Indisponible : série absente de marche.json"));
      grille.appendChild(tuile);
      continue;
    }
    const dec = g.decimales ?? 2;
    tuile.appendChild(el("span", "tuile-valeur tabulaire", k.derniere.toLocaleString("fr-FR", { minimumFractionDigits: dec, maximumFractionDigits: dec })));
    const variation = k.variation ?? null;
    const sens = variation === null ? "" : variation > 0 ? "pos" : variation < 0 ? "neg" : "";
    tuile.appendChild(el("span", `tuile-variation tabulaire ${sens}`,
      variation === null ? "variation 7 j n/d" :
      `${variation > 0 ? "+" : ""}${variation.toLocaleString("fr-FR", { maximumFractionDigits: dec })} (${k.variation_pct > 0 ? "+" : ""}${String(k.variation_pct).replace(".", ",")} %) sur 7 j`));
    const limite = new Date(k.date); limite.setDate(limite.getDate() - 92);
    const pts = k.points.filter(p => new Date(p[0]) >= limite);
    tuile.appendChild(sparkline(pts.length > 1 ? pts : k.points, "var(--accent)"));
    tuile.appendChild(el("span", "note", `${dateCourte(k.date)} · ${g.source}`));
    tuile.addEventListener("click", () => ouvrirDetail(libelle, [listeDefinitions([
      ["Dernière valeur", `${k.derniere} ${g.unite || ""}`], ["Date", dateCourte(k.date)],
      ["Variation 7 j", variation === null ? "n/d" : `${variation} (${k.variation_pct} %) depuis le ${dateCourte(k.date_ref)}`],
      ["Source", g.source], ["Note", g.note ?? undefined]])]));
    grille.appendChild(tuile);
  }
  c.appendChild(grille);
  return c;
}

export async function blocsSuite(site) {
  const [rapport, marche] = await Promise.all([chargerJson("data/latest.json"), chargerJson("data/marche.json")]);
  const engrenages = enErreur(rapport) ? null : carteEngrenagesCompacte(rapport);
  return [
    ...(engrenages ? [engrenages] : []),
    heatmap(site),
    enErreur(rapport) ? indisponible("Classement des devises", rapport?.__erreur) : classement(rapport),
    marches(marche),
  ];
}
