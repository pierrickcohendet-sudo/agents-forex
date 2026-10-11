/* Vue « Hebdo » de l'onglet 8 engrenages : dossier d'économiste (docs/data/dossiers_hebdo.json). */
import { chargerJson, enErreur, el, indisponible, dateHeure } from "./commun.js";

const BLOCS = [["constat", "Le constat"], ["mecanisme", "Le mécanisme"], ["ce_qui_pourrait_tout_changer", "Ce qui pourrait tout changer"]];
const raison = t => String(t || "raison inconnue").replace(/^indisponible\s*:\s*/i, "");
const pct = v => v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${String(v).replace(".", ",")} %`;

function tableauPrecedents(liste) {
  const utiles = (liste || []).filter(p => p.cas);
  if (!utiles.length) return null;
  const defile = el("div", "defile");
  const t = el("table", "dense compact");
  const tete = el("tr");
  for (const h of ["Indicateur → devise", "Cas", "1 mois", "3 mois", "6 mois", "Tous épisodes (1 mois)"]) tete.appendChild(el("th", null, h));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  for (const p of utiles) {
    const tr = el("tr");
    tr.appendChild(el("td", null, `${p.indicateur} → ${p.devise}`));
    tr.appendChild(el("td", "tabulaire", String(p.cas["1m"].n)));
    for (const h of ["1m", "3m", "6m"]) tr.appendChild(el("td", `tabulaire ${p.cas[h].mediane_pct > 0 ? "pos" : p.cas[h].mediane_pct < 0 ? "neg" : ""}`, pct(p.cas[h].mediane_pct)));
    tr.appendChild(el("td", "tabulaire", pct(p.reference_tous_episodes?.["1m"]?.mediane_pct)));
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t);
  return defile;
}

function ficheHebdo(n, e) {
  const d = el("details", "carte fiche");
  const s = el("summary"); s.appendChild(el("span", "fiche-nom", `${n}. ${e.nom || ""}`));
  if (e.statut !== "ok") s.appendChild(el("span", "note", "indisponible"));
  d.appendChild(s);
  const corps = el("div", "fiche-corps");
  if (e.statut !== "ok") {
    corps.appendChild(el("p", "indisponible", `Dossier indisponible cette semaine : ${raison(e.raison)}.`));
  } else {
    for (const [cle, titre] of BLOCS) {
      const p = el("p", "texte"); p.appendChild(el("strong", null, `${titre} : `)); p.appendChild(document.createTextNode(e[cle] || "—"));
      corps.appendChild(p);
    }
    if ((e.implications || []).length) {
      const b = el("div", "bloc"); b.appendChild(el("h3", null, "Implications par devise"));
      const ul = el("ul");
      for (const i of e.implications) { const li = el("li"); li.appendChild(el("strong", null, `${i.devise} : `)); li.appendChild(document.createTextNode(i.texte)); ul.appendChild(li); }
      b.appendChild(ul); corps.appendChild(b);
    }
    const b = el("div", "bloc"); b.appendChild(el("h3", null, "Un précédent utile"));
    b.appendChild(el("p", "texte", e.precedent || "—"));
    if (e.precedent_impose) b.appendChild(el("p", "note", "Texte calculé par programme (le modèle n'a pas pu le raconter ou les cas sont insuffisants)."));
    const tab = tableauPrecedents(e.precedents); if (tab) b.appendChild(tab);
    corps.appendChild(b);
    for (const [cle, titre] of [["comprendre", "📘 Comprendre : "], ["desk", "🎯 Ce que regarde un desk : "]]) {
      if (!e[cle]) continue;
      const p = el("p", "texte"); p.appendChild(el("strong", null, titre)); p.appendChild(document.createTextNode(e[cle])); corps.appendChild(p);
    }
    if ((e.controles || []).length) corps.appendChild(el("p", "tag-alerte", `Contrôles : ${e.controles.join(" · ")}`));
    corps.appendChild(el("p", "note", `Rédigé par ${e.redige_par?.libelle || "modèle inconnu"} à partir des seuls chiffres des dossiers (calcul Python).`));
  }
  d.appendChild(corps);
  return d;
}

export async function vueHebdo() {
  const h = await chargerJson("data/dossiers_hebdo.json");
  if (enErreur(h)) return [indisponible("Dossier hebdomadaire", "pas encore produit (premier dossier : le dimanche, après le passage --hebdo)")];
  const tete = el("section", "carte");
  tete.appendChild(el("h2", null, `Dossier d'économiste — semaine ${h.semaine}`));
  tete.appendChild(el("p", "sous-titre", `Rédigé le ${dateHeure(h.genere_le)} à partir des chiffres du ${dateHeure(h.donnees_du)}. Le modèle ne reçoit que les tableaux calculés en Python ; toute phrase citant un chiffre absent est retirée.`));
  const syn = h.synthese || {};
  if (syn.statut === "ok") {
    const c = el("div", "encadre bleu"); c.appendChild(el("strong", null, "Thème de la semaine")); c.appendChild(el("p", "texte", syn.theme_semaine)); tete.appendChild(c);
    for (const ch of syn.chaines || []) {
      const b = el("div", "encadre bleu"); b.appendChild(el("strong", null, `Chaîne de transmission — ${ch.titre || ""}`));
      b.appendChild(el("p", "texte", ch.maillons.map(m => `${m.texte} (${m.engrenage})`).join(" → "))); tete.appendChild(b);
    }
    if ((syn.conflits || []).length) {
      const b = el("div", "encadre orange"); b.appendChild(el("strong", null, "Engrenages en conflit"));
      const ul = el("ul"); for (const c2 of syn.conflits) ul.appendChild(el("li", null, `(${c2.engrenages.join(") contre (")}) : ${c2.texte}`));
      b.appendChild(ul); tete.appendChild(b);
    }
    const f = el("div", "encadre violet"); f.appendChild(el("strong", null, "Ce qui pourrait tout changer la semaine prochaine"));
    f.appendChild(el("p", "texte", syn.ce_qui_pourrait_tout_changer)); tete.appendChild(f);
    if ((syn.controles || []).length) tete.appendChild(el("p", "tag-alerte", `Contrôles : ${syn.controles.join(" · ")}`));
  } else {
    tete.appendChild(el("p", "indisponible", `Synthèse de la semaine indisponible : ${raison(syn.raison)}.`));
  }
  const fiches = Object.keys(h.engrenages || {}).sort((a, b) => a - b).map(n => ficheHebdo(n, h.engrenages[n]));
  return [tete, ...fiches];
}

export function selecteurVue(active) {
  const c = el("section", "carte vue-selecteur");
  const nav = el("div", "selecteur-engrenages");
  for (const [id, lib] of [["", "Quotidien"], ["hebdo", "Hebdo (dossier d'économiste)"]]) {
    const a = el("a", "bouton", lib); a.href = `#engrenages${id ? "/" + id : ""}`;
    a.setAttribute("aria-pressed", String(active === id));
    nav.appendChild(a);
  }
  c.appendChild(nav);
  return c;
}
