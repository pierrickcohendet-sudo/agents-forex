/* Onglet Synthèse : bandeau de régime, indicateurs clés par devise, heatmap, classement, marchés. */
import { chargerJson, enErreur, el, indisponible, dateHeure, dateCourte, ageHeures, ouvrirDetail,
         listeDefinitions, rendreTriable, DRAPEAUX } from "./commun.js";

const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs) {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  return n;
}

/* ------------------------------------------------------- jauge demi-cercle */
const ECHELLE_JAUGE = 30;   // ± points d'écart risque − refuge représentés
function point(angleDeg, r) {
  const a = (angleDeg * Math.PI) / 180;
  return [100 + r * Math.cos(a), 100 - r * Math.sin(a)];
}
function arc(de, a, r) {
  const [x1, y1] = point(de, r), [x2, y2] = point(a, r);
  return `M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`;
}
const angleDe = v => 180 - ((Math.max(-ECHELLE_JAUGE, Math.min(ECHELLE_JAUGE, v)) + ECHELLE_JAUGE) / (2 * ECHELLE_JAUGE)) * 180;

function jauge(ecart, seuil) {
  const s = svg("svg", { viewBox: "0 0 200 140", class: "jauge", role: "img",
    "aria-label": ecart === null ? "Jauge de risque indisponible" : `Écart de score risque moins refuge : ${ecart} points` });
  const aSeuilNeg = angleDe(-seuil), aSeuilPos = angleDe(seuil);
  for (const [de, a, couleur] of [[180, aSeuilNeg, "var(--negatif)"], [aSeuilNeg, aSeuilPos, "var(--neutre)"], [aSeuilPos, 0, "var(--positif)"]]) {
    s.appendChild(svg("path", { d: arc(de, a, 80), fill: "none", stroke: couleur, "stroke-width": 14 }));
  }
  const t1 = svg("text", { x: 14, y: 116 }); t1.textContent = "Risk Off"; s.appendChild(t1);
  const t2 = svg("text", { x: 186, y: 116, "text-anchor": "end" }); t2.textContent = "Risk On"; s.appendChild(t2);
  if (ecart !== null && ecart !== undefined) {
    const [x, y] = point(angleDe(ecart), 66);
    s.appendChild(svg("line", { x1: 100, y1: 100, x2: x, y2: y, stroke: "var(--texte)", "stroke-width": 3, "stroke-linecap": "round" }));
    s.appendChild(svg("circle", { cx: 100, cy: 100, r: 5, fill: "var(--texte)" }));
    const v = svg("text", { x: 100, y: 134, "text-anchor": "middle", class: "valeur" });
    v.textContent = `${ecart > 0 ? "+" : ""}${String(ecart).replace(".", ",")} pts`;
    s.appendChild(v);
  }
  return s;
}

const LIBELLES_RELECTURE = { ok: "relu, rien à signaler", a_revoir: "relu, points de vigilance", non_evalue: "relecture non effectuée" };

function bandeauRegime(site) {
  const r = site.regime || {};
  const c = el("section", `carte regime ${r.biais || ""}`);
  if (!r.biais) {
    c.appendChild(el("h2", null, "Régime de risque"));
    c.appendChild(el("p", "indisponible", `Indisponible : ${r.raison || "biais du jour non calculé"}.`));
    return c;
  }
  const age = ageHeures(r.maj);
  if (age !== null && age > 36) {
    c.appendChild(el("p", "alerte", `Attention : données vieilles de ${Math.round(age)} h (dernière mise à jour ${dateHeure(r.maj)}). Le pipeline n'a pas tourné depuis.`));
  }
  const grille = el("div", "regime-grille");
  grille.appendChild(jauge(r.ecart_points, r.seuil_points || 5));
  const texte = el("div");
  const titre = el("h1", "regime-titre");
  titre.appendChild(el("span", "etiquette", `Régime du ${dateCourte(r.date_rapport)}`));
  titre.appendChild(document.createTextNode(r.libelle));
  texte.appendChild(titre);
  texte.appendChild(el("p", "driver", r.driver || "Driver du jour indisponible (commentaire non généré)."));
  const meta = el("div", "meta-ligne");
  const badge = el("span", `badge ${r.relecture || "non_evalue"}`, LIBELLES_RELECTURE[r.relecture] || r.relecture);
  meta.appendChild(badge);
  meta.appendChild(el("span", "tabulaire", `Mis à jour ${dateHeure(r.maj)}`));
  meta.appendChild(el("span", "tabulaire", `${r.nb_devises_disponibles}/${r.nb_devises} devises analysées`));
  texte.appendChild(meta);
  const exp = el("button", "bouton", "Comment est calculé ce régime ?");
  exp.style.marginTop = "10px";
  exp.addEventListener("click", () => ouvrirDetail("Régime de risque", [
    el("p", null, r.explication),
    listeDefinitions([["Écart risque − refuge", r.ecart_points === null ? "n/d" : `${r.ecart_points} pts`],
                      ["Seuil", `± ${r.seuil_points} pts`],
                      ["Devises « risque »", (r.devises_risque || []).join(", ")],
                      ["Devises « refuge »", (r.devises_refuge || []).join(", ")],
                      ["Source", "scores de confluence du rapport du jour (calcul Python)"]])]));
  texte.appendChild(exp);
  grille.appendChild(texte);
  c.appendChild(grille);
  return c;
}

/* -------------------------------------------------- indicateurs clés */
function detailCellule(libelle, cel) {
  const bloc = el("div");
  bloc.appendChild(el("h3", null, libelle));
  if (!cel || cel.etat !== "valeur") {
    bloc.appendChild(listeDefinitions([["Valeur", "n/d"], ["Raison", cel?.raison || "donnée absente"]]));
    return bloc;
  }
  bloc.appendChild(listeDefinitions([
    ["Réel", `${cel.texte}${cel.manuel ? " (saisie manuelle)" : ""}`],
    ["Consensus", cel.consensus ?? undefined], ["Précédent", cel.precedent ?? undefined],
    ["Date", cel.date ? dateCourte(cel.date) : undefined], ["Source", cel.source ?? undefined]]));
  return bloc;
}

function tableauIndicateursCles(site) {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Indicateurs clés par devise"));
  c.appendChild(el("p", "sous-titre", "Touchez une ligne pour le détail (réel, consensus, précédent, date, source). Touchez un en-tête pour trier."));
  const lignes = site.indicateurs_cles || [];
  if (!lignes.length) { c.appendChild(el("p", "indisponible", "Indisponible : aucune devise dans site.json.")); return c; }
  const colonnes = site.colonnes_cles || [];
  const defile = el("div", "defile");
  const table = el("table", "dense");
  const tete = el("tr");
  const thDev = el("th"); const bDev = el("button", null, "Devise"); thDev.appendChild(bDev); tete.appendChild(thDev);
  for (const col of colonnes) { const th = el("th"); th.appendChild(el("button", null, col.libelle)); tete.appendChild(th); }
  const thead = el("thead"); thead.appendChild(tete); table.appendChild(thead);
  const corps = el("tbody");
  for (const l of lignes) {
    const tr = el("tr");
    tr.dataset.devise = l.devise;
    tr.appendChild(el("td", null, `${l.drapeau || DRAPEAUX[l.devise] || ""} ${l.devise}`));
    for (const col of colonnes) {
      const cel = l.cellules[col.id] || { etat: "absent", texte: "n/d", raison: "colonne absente" };
      const td = el("td");
      td.dataset.valeur = cel.valeur_num ?? "";
      if (cel.etat !== "valeur") {
        td.appendChild(el("span", "nd", "n/d"));
        td.title = cel.raison || "";
      } else if (col.type === "score") {
        td.appendChild(document.createTextNode(cel.texte));
        const barre = el("span", "barre"); const rempli = el("span");
        rempli.style.width = `${Math.max(0, Math.min(100, cel.valeur_num))}%`;
        barre.appendChild(rempli); td.appendChild(barre);
      } else if (col.type === "biais") {
        td.appendChild(el("span", `biais ${cel.code}`, cel.texte));
      } else if (col.type === "indice") {
        td.appendChild(el("span", cel.valeur_num > 0.05 ? "pos" : cel.valeur_num < -0.05 ? "neg" : "", cel.texte));
      } else {
        td.appendChild(document.createTextNode(cel.texte));
        if (cel.manuel) td.appendChild(el("span", "manuel", "✍"));
      }
      tr.appendChild(td);
    }
    tr.addEventListener("click", () => {
      ouvrirDetail(`${l.drapeau || ""} ${l.devise} — indicateurs clés`,
                   colonnes.map(col => detailCellule(col.libelle, l.cellules[col.id])));
    });
    corps.appendChild(tr);
  }
  table.appendChild(corps);
  rendreTriable(table, (tr, i) => {
    if (i === 0) return tr.dataset.devise;
    const v = tr.cells[i].dataset.valeur;
    return v === "" ? null : Number(v);
  });
  defile.appendChild(table);
  c.appendChild(defile);
  c.appendChild(el("p", "note", "Biais du jour : dérivé du score de confluence (calcul Python). n/d : touchez la ligne pour la raison."));
  return c;
}

/* ------------------------------------------------------------------ page */
export async function pageSynthese() {
  const site = await chargerJson("data/site.json");
  if (enErreur(site)) return [indisponible("Synthèse", `site.json illisible (${site?.__erreur || "absent"})`)];
  const blocs = [bandeauRegime(site), tableauIndicateursCles(site)];
  try {
    const { blocsSuite } = await import("./synthese_suite.js");
    blocs.push(...(await blocsSuite(site)));
  } catch (e) {
    console.error(e);
    blocs.push(indisponible("Heatmap, classement et marchés", `erreur d'affichage (${e.message})`));
  }
  return blocs;
}
