/* Synthèse longue du lundi (lot V6, partie D) : 12 sections au format du rapport modèle, calculées en Python
   (core/rapport_long.py). Blocs génériques : paragraphe, liste, tableau, cartes, note ; le site affiche, ne calcule rien. */
import { el } from "./commun.js";

function bloc(b) {
  if (b.type === "paragraphe") return [el("p", "rp-texte", b.texte)];
  if (b.type === "note") return [el("p", "note", b.texte)];
  const sortie = b.titre ? [el("h4", null, b.titre)] : [];
  if (b.type === "liste") {
    const ul = el("ul", "rp-liste");
    for (const i of b.items || []) ul.appendChild(el("li", null, i));
    sortie.push(ul);
  } else if (b.type === "tableau") {
    const d = el("div", "defile"); const t = el("table", "dense texte");
    const tr = el("tr"); for (const h of b.entetes || []) tr.appendChild(el("th", null, h));
    const th = el("thead"); th.appendChild(tr); t.appendChild(th);
    const tb = el("tbody");
    for (const l of b.lignes || []) { const r = el("tr"); for (const c of l) r.appendChild(el("td", null, c ?? "n/d")); tb.appendChild(r); }
    if (!(b.lignes || []).length) { const r = el("tr"); const td = el("td", "note", "Aucune ligne."); td.colSpan = (b.entetes || []).length || 1; r.appendChild(td); tb.appendChild(r); }
    t.appendChild(tb); d.appendChild(t); sortie.push(d);
  } else if (b.type === "cartes") {
    const g = el("div", "rl-cartes");
    for (const c of b.items || []) {
      const a = el("article", "rl-carte");
      a.appendChild(el("b", null, c.titre));
      if (c.texte) a.appendChild(el("p", null, c.texte));
      if (c.note) a.appendChild(el("p", "note", c.note));
      g.appendChild(a);
    }
    sortie.push(g);
  }
  return sortie;
}

function rendreLongue(cle) {
  return r => {
    const s = r[cle];
    if (!s) return [el("p", "indisponible", "Section n/d (rapport du jour sans version longue).")];
    const sortie = [];
    if (s.texte) {
      const p = el("p", "rp-lecture", s.texte);
      p.appendChild(el("span", "source", " — formulé par le modèle à partir des faits Python"));
      sortie.push(p);
    }
    for (const b of s.blocs || []) sortie.push(...bloc(b));
    return sortie;
  };
}

export const RENDUS_LONGS = Object.fromEntries(["long_intro", "long_executive", "long_marches", "long_regime", "long_banques",
  "long_calendrier", "long_geopolitique", "long_devises", "long_paires", "long_scenarios", "long_technique", "long_plan"]
  .map(c => [c, rendreLongue(c)]));
