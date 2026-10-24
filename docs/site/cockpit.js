/* Cockpit des 8 engrenages (lot V5, étape 3) : vue par défaut de l'onglet. Tout vient de dossiers.json → cockpit
   (calcul Python) : positions, seuils et couleurs des thermomètres ne sont jamais calculés ici. */
import { el, dateCourte } from "./commun.js";
import { ouvrirBriefing } from "./briefing.js";
import { symboleCase } from "./vue_ensemble.js";

const SVG = "http://www.w3.org/2000/svg";
const CONVICTION = { faible: "faible", moyen: "moyenne", eleve: "élevée" };
function s(tag, attrs) { const n = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v); return n; }
const virgule = v => String(v).replace(".", ",");

function anneau(e) {
  const r = 62, C = 2 * Math.PI * r, part = e.alignes == null ? 0 : Math.min(1, e.alignes / (e.sur || 7));
  const svg = s("svg", { viewBox: "0 0 160 160", class: "ck-anneau", role: "img",
    "aria-label": e.alignes == null ? "Alignement des engrenages : n/d" : `${e.alignes} engrenages alignés sur ${e.sur || 7}` });
  svg.append(s("circle", { cx: 80, cy: 80, r, class: "ck-anneau-fond" }),
             s("circle", { cx: 80, cy: 80, r, class: `ck-anneau-arc dir-${e.direction?.classe || "nd"}`, "stroke-dasharray": `${(C * part).toFixed(1)} ${C.toFixed(1)}`,
                           transform: "rotate(-90 80 80)" }));
  const t = s("text", { x: 80, y: 82, "text-anchor": "middle", class: "ck-anneau-val" }); t.textContent = e.alignes == null ? "n/d" : String(e.alignes);
  const t2 = s("text", { x: 80, y: 104, "text-anchor": "middle", class: "ck-anneau-sous" }); t2.textContent = `sur ${e.sur || 7} alignés`;
  svg.append(t, t2);
  return svg;
}

function pastille(texte, classe = "nd") { return el("span", `ck-pastille dir-${classe}`, texte); }

function entete(c, vue) {
  const e = c.entete || {};
  const sec = el("section", "ck-hero");
  const g = el("div", "carte ck-theme");
  const gauche = el("div", "ck-anneau-bloc");
  gauche.append(anneau(e), el("span", "ck-petit", `Conviction : ${CONVICTION[e.conviction] || "non déterminée"}`));
  const droite = el("div", "ck-theme-texte");
  droite.appendChild(el("p", `ck-surtitre${e.titre_impose ? " impose" : ""}`,
    `Thème du jour${e.date_rapport ? ` · ${dateCourte(e.date_rapport)}` : ""}${e.titre_impose ? " · titre imposé (moins de 3 alignés)" : ""}`));
  droite.appendChild(el("h2", `ck-titre${e.titre_impose ? " impose" : ""}`, e.titre));
  const pastilles = el("div", "ck-pastilles");
  const [dl, rl] = String(e.direction?.libelle || "").split(" · ");
  if (dl) pastilles.appendChild(pastille(dl, e.dollar === "haussier" ? "up" : e.dollar === "baissier" ? "dn" : "nd"));
  if (rl) pastilles.appendChild(pastille(rl, e.risque === "risk_on" ? "up" : e.risque === "risk_off" ? "dn" : "nd"));
  if (e.cases_total) pastilles.appendChild(pastille(`${e.cases_actives} cases actives sur ${e.cases_total}`));
  droite.appendChild(pastilles);
  if (e.texte) { const p = el("p", "ck-paragraphe", e.texte); p.appendChild(el("span", "source", e.texte_source === "modèle" ? " — formulé par le modèle" : " — calcul Python")); droite.appendChild(p); }
  if (e.texte_indisponible) droite.appendChild(el("p", "indisponible", `${e.texte_indisponible}.`));
  droite.appendChild(el("p", "ck-explication", e.explication));
  if (vue?.briefing?.cartes?.length) {
    const b = el("button", "bouton ck-briefing", "▶ Briefing 60 s"); b.type = "button";
    b.addEventListener("click", () => ouvrirBriefing(vue.briefing, vue.theme?.date_rapport, b));
    droite.appendChild(b);
  }
  g.append(gauche, droite);
  const aside = el("aside", "carte ck-bord");
  aside.appendChild(el("h3", "ck-h3", "Au bord du seuil"));
  const liste = el("ul", "ck-bord-liste");
  for (const x of c.au_bord || []) {
    const li = el("li");
    li.append(el("span", `ck-dist ${x.etat === "proche" ? "chaud" : ""}`, x.distance_texte), el("span", null, `${x.phrase}.`));
    li.title = `Engrenage ${x.engrenage} · source : ${x.source || "—"} · ${x.date ? dateCourte(x.date) : "date n/d"}`;
    liste.appendChild(li);
  }
  if (!(c.au_bord || []).length) liste.appendChild(el("li", "note", "Aucun signal évalué dans son couloir neutre."));
  const r = c.rendez_vous;
  if (r) {
    const li = el("li");
    li.append(el("span", "ck-dist rdv", dateCourte(r.date_paris).slice(0, 5)),
              el("span", null, `${r.devise} · ${r.evenement} à ${r.heure_paris} (heure de Paris) : peut faire basculer l'engrenage ${r.engrenage}.`));
    li.title = `Source : ${r.source}`;
    liste.appendChild(li);
  }
  aside.appendChild(liste);
  const lien = el("a", "ck-lien", "Ouvrir le radar des déclencheurs →"); lien.href = "#outils";
  const lien2 = el("a", "ck-lien", "Voir l'agenda des 7 prochains jours →"); lien2.href = "#agenda";
  aside.append(lien, lien2);
  sec.append(g, aside);
  return sec;
}

function thermometre(t, choisir) {
  const b = el("button", `ck-thermo dir-${t.direction?.classe || "nd"}`); b.type = "button";
  b.setAttribute("aria-label", `Engrenage ${t.numero}, ${t.nom} : ${t.libelle || "mesure"} ${t.texte_valeur}, ${t.direction?.libelle || ""}. Ouvrir le dossier.`);
  const tete = el("span", "ck-thermo-tete");
  tete.append(el("span", "ck-num", String(t.numero)), el("span", "ck-thermo-titre", t.titre),
              el("span", `ck-pastille petite dir-${t.direction?.classe || "nd"}`, t.direction?.libelle || "non déterminée"));
  const val = el("span", "ck-thermo-val");
  val.append(el("b", "tabulaire", t.texte_valeur), el("span", "ck-petit", `${t.libelle || ""}${t.date ? ` · ${dateCourte(t.date).slice(0, 5)}` : ""}`));
  const piste = el("span", `ck-piste${t.valeur == null ? " vide" : ""}`);
  piste.setAttribute("aria-hidden", "true");
  piste.appendChild(el("i", "ck-rail"));
  const zone = (cls, gauche, largeur) => { const z = el("i", `ck-zone dir-${cls}`); z.style.left = `${gauche}%`; z.style.width = `${largeur}%`; return z; };
  if (t.pos_bas != null) piste.append(zone(t.classe_bas, 0, t.pos_bas), Object.assign(el("i", "ck-seuil"), { style: `left:${t.pos_bas}%` }));
  if (t.pos_haut != null) piste.append(zone(t.classe_haut, t.pos_haut, 100 - t.pos_haut), Object.assign(el("i", "ck-seuil"), { style: `left:${t.pos_haut}%` }));
  if (t.pos != null) { const p = el("i", `ck-point dir-${t.direction?.classe || "nd"}`); p.style.left = `${t.pos}%`; piste.appendChild(p); }
  b.append(tete, val, piste);
  if (t.raison) b.appendChild(el("span", "ck-note nd", `n/d : ${t.raison}.`));
  if (t.neutralise) b.appendChild(el("span", "ck-note alerte", t.neutralise));
  b.appendChild(el("span", "ck-note", t.note || ""));
  b.title = `Source : ${t.source || "—"}${t.date ? ` · ${dateCourte(t.date)}` : ""}`;
  b.addEventListener("click", () => choisir(t.numero, true));
  return b;
}

function filSeances(f) {
  const c = el("section", "carte ck-fil");
  const tete = el("div", "ck-section-tete");
  tete.append(el("h2", null, "Fil des 15 dernières séances"), el("span", "ck-petit", f.source || ""));
  c.appendChild(tete);
  const defile = el("div", "defile");
  const grille = el("div", "ck-fil-grille");
  grille.style.setProperty("--n", (f.jours || []).length || 15);
  for (const l of f.lignes || []) {
    grille.appendChild(el("span", "ck-fil-nom", `${l.numero} ${l.titre}`));
    for (const x of l.cellules) {
      const cel = el("span", `ck-fil-cel ${x.classe ? `dir-${x.classe}` : "vide"}`);
      cel.title = `${dateCourte(x.date)} · engrenage ${l.numero} : ${x.libelle}`;
      grille.appendChild(cel);
    }
  }
  defile.appendChild(grille);
  c.appendChild(defile);
  const j = f.jours || [];
  if (j.length) { const axe = el("div", "ck-fil-axe"); axe.append(el("span", null, dateCourte(j[0]).slice(0, 5)), el("span", null, dateCourte(j[j.length - 1]).slice(0, 5))); c.appendChild(axe); }
  c.appendChild(el("p", "note", f.note || ""));
  return c;
}

function matriceCompacte(m) {
  const c = el("section", "carte ck-matrice");
  c.appendChild(el("h2", null, "Matrice compacte · bilan par devise"));
  if (!m || m.indisponible) { c.appendChild(el("p", "indisponible", `Matrice indisponible : ${m?.indisponible || "absente"}.`)); return c; }
  const defile = el("div", "defile");
  const t = el("table", "ck-mat");
  const tete = el("tr"); tete.appendChild(el("th"));
  for (let n = 1; n <= 8; n++) tete.appendChild(el("th", null, String(n)));
  tete.appendChild(el("th", null, "Bilan"));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  for (const l of m.lignes) {
    const tr = el("tr");
    tr.appendChild(el("th", null, l.devise));
    for (const x of l.cases) {
      const td = el("td", `ck-mc v${x.valeur} etat-${x.etat}`, symboleCase(x));
      td.title = `${l.devise} × engrenage ${x.engrenage} : ${x.libelle}${x.raison ? ` — ${x.raison}` : ""}`;
      tr.appendChild(td);
    }
    tr.appendChild(el("td", `ck-bilan ${l.bilan > 0 ? "pos" : l.bilan < 0 ? "neg" : ""}`, `${l.bilan > 0 ? "+" : ""}${String(l.bilan).replace("-", "−")}`));
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t); c.appendChild(defile);
  c.appendChild(el("p", "note", `${m.compte_libelle || ""}. Hachures : n/d (donnée absente) ; gris très clair : sans règle ; « · » : règle évaluée non déclenchée.`));
  return c;
}

/* Nœuds du cockpit ; `choisir(n, defiler)` ouvre le dossier n. */
export function cockpit(c, vue, matrice, choisir) {
  if (!c || c.indisponible) {
    const x = el("section", "carte");
    x.appendChild(el("p", "indisponible", `Cockpit indisponible : ${c?.indisponible || "absent de dossiers.json (prochain run)"}.`));
    return [x];
  }
  const th = el("section", "ck-thermos");
  const tete = el("div", "ck-section-tete");
  tete.append(el("h2", null, "Thermomètres : où en est chaque engrenage par rapport à ses seuils"));
  const leg = el("p", "ck-legende");
  for (const [cls, txt] of [["up", "risk on / dollar haussier"], ["dn", "risk off / dollar baissier"], ["nd", "neutre"]]) {
    const sp = el("span"); sp.append(el("i", `ck-pt dir-${cls}`), document.createTextNode(txt)); leg.appendChild(sp);
  }
  const sp = el("span"); sp.append(el("i", "ck-pt seuil"), document.createTextNode("seuil")); leg.appendChild(sp);
  tete.appendChild(leg);
  const grille = el("div", "ck-thermos-grille");
  grille.append(...(c.thermometres || []).map(t => thermometre(t, choisir)));
  th.append(tete, grille, el("p", "note", c.methode || ""));
  const bas = el("div", "ck-bas");
  bas.append(filSeances(c.fil || {}), matriceCompacte(matrice));
  return [entete(c, vue), th, bas];
}
