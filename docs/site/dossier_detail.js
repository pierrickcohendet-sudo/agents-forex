/* Dossier détaillé d'un engrenage (lot V5, étape 4) : dossiers.json → cockpit.details[n] (calcul Python).
   Chiffres clés et rang sur 5 ans, courbe 6 mois avec zones de déclenchement et repères, règles évaluées, effet sur
   les 9 devises si une règle se déclenchait, ce que dit l'histoire (simulateur), lecture de l'économiste. */
import { el, dateCourte, dateHeure } from "./commun.js";
import { dessinerReperes } from "./dossiers.js";

const SVG = "http://www.w3.org/2000/svg";
const COURTS = { 1: "Thème", 2: "Monétaire", 3: "Données", 4: "Fiscale", 5: "Marchés", 6: "Géopolitique", 7: "Flux", 8: "Offre" };
function s(tag, attrs, texte) { const n = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v); if (texte != null) n.textContent = texte; return n; }
const fr = (v, d = 2) => v == null ? "n/d" : Number(v).toLocaleString("fr-FR", { maximumFractionDigits: d });
const signe = (v, d = 2) => v == null ? "n/d" : `${v > 0 ? "+" : ""}${fr(v, d)}`.replace("-", "−");

function courbe(c) {
  const fig = el("figure", "graphique dd-courbe");
  fig.appendChild(el("figcaption", null, `${c.libelle} · 6 mois et zones de déclenchement`));
  const pts = c.points || [];
  if (pts.length < 2) { fig.appendChild(el("p", "indisponible", "Pas assez de points.")); return fig; }
  const L = 520, H = 200, m = { g: 40, d: 16, h: 10, b: 20 };
  const vals = pts.map(p => p[1]).concat([c.seuil_bas, c.seuil_haut].filter(v => v != null));
  let min = Math.min(...vals), max = Math.max(...vals); const marge = (max - min) * 0.08 || 1; min -= marge; max += marge;
  const t0 = Date.parse(pts[0][0]), t1 = Date.parse(pts[pts.length - 1][0]);
  const x = t => m.g + (t - t0) / ((t1 - t0) || 1) * (L - m.g - m.d), y = v => m.h + (max - v) / (max - min) * (H - m.h - m.b);
  const svg = s("svg", { viewBox: `0 0 ${L} ${H}`, class: "graphique-svg", role: "img",
    "aria-label": `${c.libelle}, du ${dateCourte(pts[0][0])} au ${dateCourte(pts[pts.length - 1][0])}, seuils ${fr(c.seuil_bas)} et ${fr(c.seuil_haut)}` });
  if (c.seuil_haut != null) {
    svg.appendChild(s("rect", { x: m.g, y: m.h, width: L - m.g - m.d, height: Math.max(0, y(c.seuil_haut) - m.h), class: `dd-zone dir-${c.classe_haut || "nd"}` }));
    svg.appendChild(s("line", { x1: m.g, x2: L - m.d, y1: y(c.seuil_haut), y2: y(c.seuil_haut), class: "dd-seuil" }));
    svg.appendChild(s("text", { x: m.g + 4, y: y(c.seuil_haut) - 4, class: "axe" }, `seuil haut ${fr(c.seuil_haut)}`));
  }
  if (c.seuil_bas != null) {
    svg.appendChild(s("rect", { x: m.g, y: y(c.seuil_bas), width: L - m.g - m.d, height: Math.max(0, H - m.b - y(c.seuil_bas)), class: `dd-zone dir-${c.classe_bas || "nd"}` }));
    svg.appendChild(s("line", { x1: m.g, x2: L - m.d, y1: y(c.seuil_bas), y2: y(c.seuil_bas), class: "dd-seuil" }));
    svg.appendChild(s("text", { x: m.g + 4, y: y(c.seuil_bas) + 12, class: "axe" }, `seuil bas ${fr(c.seuil_bas)}`));
  }
  for (const v of [max - marge, min + marge]) svg.appendChild(s("text", { x: m.g - 4, y: y(v) + 3, "text-anchor": "end", class: "axe" }, fr(v, 1)));
  svg.appendChild(s("text", { x: m.g, y: H - 5, class: "axe" }, dateCourte(pts[0][0]).slice(0, 5)));
  svg.appendChild(s("text", { x: L - m.d, y: H - 5, "text-anchor": "end", class: "axe" }, dateCourte(pts[pts.length - 1][0]).slice(0, 5)));
  svg.appendChild(s("path", { d: pts.map((p, k) => `${k ? "L" : "M"}${x(Date.parse(p[0])).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" "),
                              fill: "none", stroke: "var(--texte)", "stroke-width": 1.6, "vector-effect": "non-scaling-stroke" }));
  const zone = el("div", "graphique-zone"); const bulle = el("div", "infobulle"); bulle.hidden = true;
  dessinerReperes(svg, c.annotations?.tout || [], { pts }, x, y, [m.g, L - m.d, m.h, H - m.b], bulle, zone);
  zone.append(svg, bulle);
  fig.append(zone, el("p", "note", `Source : ${c.source || "—"} · zones colorées : au-delà du seuil (couleur de la direction déclenchée) · repères : ▲ plus haut · ▼ plus bas · ● dernière valeur`));
  return fig;
}

function scenarios(liste) {
  const c = el("div", "carte dd-bloc");
  c.appendChild(el("h3", null, "Si la règle se déclenchait : effet sur les 9 devises"));
  if (!liste?.length) { c.appendChild(el("p", "note", "Aucune règle de la matrice d'impact pour cet engrenage (voir config.yaml).")); return c; }
  const choix = el("div", "sc-seg dd-seg"); choix.setAttribute("role", "group"); choix.setAttribute("aria-label", "Choisir un scénario");
  const zone = el("div");
  let actif = 0;
  const boutons = liste.map((sc, i) => { const b = el("button", null, sc.libelle); b.type = "button"; b.addEventListener("click", () => { actif = i; rendre(); }); choix.appendChild(b); return b; });
  function rendre() {
    boutons.forEach((b, i) => b.setAttribute("aria-pressed", String(i === actif)));
    const sc = liste[actif];
    const grille = el("div", "dd-effets");
    for (const b of sc.bilans) {
      const delta = b.apres - b.avant;
      const col = el("div", `dd-effet ${delta > 0 ? "pos" : delta < 0 ? "neg" : ""}`);
      const barre = el("span", "dd-barre"); const h = Math.min(40, Math.abs(delta) * 18);
      const plein = el("i"); plein.style.height = `${h}px`; plein.style[delta >= 0 ? "bottom" : "top"] = "50%";
      barre.appendChild(plein);
      col.append(barre, el("b", null, b.devise), el("span", "tabulaire", delta === 0 ? "0" : signe(delta, 0)),
                 el("span", "ck-petit", `bilan ${signe(b.avant, 0)} → ${signe(b.apres, 0)}`));
      grille.appendChild(col);
    }
    zone.replaceChildren(el("p", "dd-desc", `${sc.description}. Valeur actuelle : ${sc.valeur_actuelle == null ? "n/d" : fr(sc.valeur_actuelle)}.`), grille);
  }
  rendre();
  c.append(choix, zone, el("p", "note", "Matrice recalculée en Python avec le signal posé au seuil ; bilan = somme des 8 cases. Aide à la lecture, jamais un ordre."));
  return c;
}

function histoire(h) {
  const c = el("div", "carte dd-bloc");
  c.appendChild(el("h3", null, "Ce que dit l'histoire"));
  if (h.raison) { c.appendChild(el("p", "note", `n/d : ${h.raison}.`)); return c; }
  c.appendChild(el("p", "ck-petit", `${h.libelle} : ${h.scenario} (2021-2026). Force de chaque devise.`));
  const liste = el("div", "dd-hist");
  const maxi = Math.max(0.5, ...h.lignes.map(l => Math.abs(l.mediane || 0)));
  for (const l of h.lignes) {
    const ligne = el("div", "dd-hist-ligne");
    const barre = el("span", "dd-hbar"); const i = el("i", l.mediane > 0 ? "pos" : "neg");
    i.style.width = `${Math.min(50, Math.abs(l.mediane || 0) / maxi * 50)}%`; i.style[l.mediane > 0 ? "left" : "right"] = "50%";
    barre.appendChild(i);
    ligne.append(el("b", null, l.devise), barre, el("span", "tabulaire", l.mediane == null ? "n/d" : `${signe(l.mediane)} %`),
                 el("span", `ck-petit ${String(l.lecture).startsWith("confirmé") ? "" : "faible"}`, l.lecture));
    liste.appendChild(ligne);
  }
  const a = el("a", "ck-lien", "Ouvrir dans le simulateur →"); a.href = h.lien;
  c.append(liste, el("p", "note", `Même règle qu'ailleurs : « confirmé » si la borne basse de Wilson à 90 % dépasse 50 %, sinon « indice faible · N cas » ; sous 20 cas, « échantillon insuffisant ». Source : ${h.source}.`), a);
  return c;
}

export function detailEngrenage(det, n, decaler) {
  const c = el("div", "dd");
  if (!det) { c.appendChild(el("p", "note", "Dossier détaillé indisponible (prochain run).")); return c; }
  const t = det.thermometre || {};
  const tete = el("div", "dd-tete");
  const pastilles = el("div", "ck-pastilles");
  pastilles.appendChild(el("span", `ck-pastille dir-${t.direction?.classe || "nd"}`, t.direction?.libelle || "direction n/d"));
  if (t.etat) pastilles.appendChild(el("span", "ck-pastille", { franchi: "seuil franchi", proche: "proche du seuil", non: "dans le couloir neutre", "n/d": "mesure n/d" }[t.etat] || t.etat));
  const nav = el("nav", "dd-nav"); nav.setAttribute("aria-label", "Engrenage précédent ou suivant");
  const prec = el("button", "bouton", `← ${((n + 6) % 8) + 1} ${COURTS[((n + 6) % 8) + 1]}`); prec.type = "button"; prec.addEventListener("click", () => decaler(-1));
  const suiv = el("button", "bouton", `${(n % 8) + 1} ${COURTS[(n % 8) + 1]} →`); suiv.type = "button"; suiv.addEventListener("click", () => decaler(1));
  nav.append(prec, suiv);
  tete.append(pastilles, nav);
  c.appendChild(tete);
  const chiffres = el("div", "dd-chiffres");
  for (const ch of det.chiffres || []) {
    const b = el("div", "dd-chiffre");
    b.append(el("span", "ck-petit", `${ch.libelle}${ch.date ? ` · ${String(ch.date).length > 7 ? dateCourte(ch.date) : ch.date}` : ""}`),
             el("b", "tabulaire", ch.texte || "n/d"));
    if (ch.variation) b.appendChild(el("span", null, ch.variation));
    b.appendChild(el("span", `dd-rang${ch.percentile_5a == null ? " nd" : ""}`, `Rang sur 5 ans : ${ch.rang}`));
    b.appendChild(el("span", "source", ch.source ? `Source : ${ch.source}` : (ch.raison ? `n/d : ${ch.raison}` : "")));
    chiffres.appendChild(b);
  }
  c.appendChild(chiffres);
  const milieu = el("div", "dd-milieu");
  milieu.appendChild(det.courbe ? courbe(det.courbe) : el("p", "indisponible", `Courbe 6 mois n/d : ${det.raison_courbe}.`));
  const regles = el("div", "carte dd-bloc");
  regles.appendChild(el("h3", null, "Règles Python évaluées"));
  const ul = el("ul", "dd-regles");
  for (const r of det.regles || []) {
    const li = el("li");
    li.append(el("span", `dd-etat ${r.etat === "déclenchée" ? "on" : r.etat === "proche" ? "proche" : ""}`, r.etat),
              el("span", null, `${r.libelle} : ${r.valeur}${r.distance && r.distance !== "franchi" ? `, à ${r.distance} du seuil` : ""}${r.neutralise ? ` (${r.neutralise})` : ""}`));
    li.title = `Source : ${r.source || "—"}${r.date ? ` · ${dateCourte(r.date)}` : ""}`;
    ul.appendChild(li);
  }
  if (!(det.regles || []).length) ul.appendChild(el("li", "note", "Aucune règle chiffrée pour cet engrenage."));
  regles.appendChild(ul);
  milieu.appendChild(regles);
  c.appendChild(milieu);
  const bas = el("div", "dd-milieu");
  bas.append(scenarios(det.scenarios), histoire(det.histoire || {}));
  c.appendChild(bas);
  const lec = det.lecture || {};
  const l = el("div", "carte dd-bloc");
  const lt = el("div", "ck-section-tete");
  lt.append(el("h3", null, "Lecture de l'économiste"),
            el("span", "ck-petit", lec.texte ? `Rédigé par ${lec.redige_par || "le modèle"}${lec.redige_le ? ` le ${dateHeure(lec.redige_le)}` : ""} · directions et chiffres calculés en Python` : "calcul Python"));
  l.appendChild(lt);
  l.appendChild(el("p", "dd-lecture", lec.texte || lec.phrase_python));
  if (lec.texte && lec.redige_le) l.appendChild(el("p", "note", "Le texte décrit les chiffres de son heure de rédaction ; les chiffres ci-dessus sont ceux du dernier passage."));
  if (lec.redige_avant_recalcul) l.appendChild(el("p", "tag-alerte", "Direction recalculée depuis la rédaction du texte."));
  if (lec.texte_indisponible) l.appendChild(el("p", "indisponible", `${lec.texte_indisponible}.`));
  c.appendChild(l);
  return c;
}
