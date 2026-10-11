/* Dossiers chiffrés des 8 engrenages (docs/data/dossiers.json) : calcul Python quotidien, sans LLM. */
import { chargerJson, enErreur, el, dateCourte, dateHeure, ouvrirDetail, listeDefinitions, DRAPEAUX } from "./commun.js";

const nombre = (v, dec = 2) => v === null || v === undefined ? "—" :
  Number(v).toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: dec });
const signe = (v, dec = 1) => v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${nombre(v, dec)}`;

function texteValeur(c, unite) {
  if (!c || c.valeur === null || c.valeur === undefined) return null;
  const u = c.unite || unite;
  if (u === "%") return `${nombre(c.valeur)} %`;
  if (u === "pb") return `${signe(c.valeur, 0)} pb`;
  if (u === "écarts") return signe(c.valeur, 2);
  return nombre(c.valeur);
}
function texteVariation(c) {
  if (!c) return "";
  const u = c.unite;
  const suffixe = (u === "%" || u === "pb") ? " pb" : " %";
  const morceaux = [];
  if (c.var_1s !== null && c.var_1s !== undefined) morceaux.push(`1 s ${signe(c.var_1s, u === "%" || u === "pb" ? 0 : 2)}${suffixe}`);
  if (c.var_4s !== null && c.var_4s !== undefined) morceaux.push(`4 s ${signe(c.var_4s, u === "%" || u === "pb" ? 0 : 2)}${suffixe}`);
  return morceaux.join(" · ");
}

function pastillePercentile(p) {
  const b = el("span", "pct");
  if (p === null || p === undefined) { b.textContent = "p —"; b.classList.add("vide"); return b; }
  b.textContent = `p${p}`;
  b.title = `${p}e percentile sur 5 ans`;
  const barre = el("span", "pct-barre"); const r = el("span"); r.style.width = `${p}%`; barre.appendChild(r);
  b.appendChild(barre);
  if (p >= 90 || p <= 10) b.classList.add("extreme");
  return b;
}

function detailCellule(titre, c, unite) {
  if (!c) return;
  const paires = c.valeur === null || c.valeur === undefined
    ? [["Valeur", "n/d"], ["Raison", c.raison || "—"], ["Source", c.source || undefined]]
    : [["Valeur", texteValeur(c, unite)], ["Variation 1 semaine", c.var_1s ?? "—"], ["Variation 4 semaines", c.var_4s ?? "—"],
       ["Unité des variations", (c.unite === "%" || c.unite === "pb") ? "points de base" : "%"],
       ["Percentile 5 ans", c.percentile_5a !== null && c.percentile_5a !== undefined ? `${c.percentile_5a} (sur ${c.n_5a} obs.)` : `— (${c.raison_percentile || "non calculé"})`],
       ["Date", c.date ? dateCourte(c.date) : "—"], ["Source", c.source], ["Fréquence", c.frequence ?? undefined],
       ["Note", c.note || c.note_percentile || c.lecture || undefined], ["Tendance 3 mois", c.tendance_3m ?? (c.raison_tendance ? `— (${c.raison_tendance})` : undefined)],
       ["Alerte", c.alerte ?? undefined]];
  ouvrirDetail(titre, [listeDefinitions(paires)]);
}

function cellule(td, c, unite, titre) {
  const v = texteValeur(c, unite);
  if (v === null) {
    td.appendChild(el("span", "nd", "n/d"));
    td.title = c?.raison || "";
  } else {
    td.appendChild(el("div", "dv-valeur tabulaire", v));
    const varTxt = texteVariation(c);
    if (varTxt) td.appendChild(el("div", "dv-var tabulaire", varTxt));
    td.appendChild(pastillePercentile(c.percentile_5a));
  }
  td.addEventListener("click", ev => { ev.stopPropagation(); detailCellule(titre, c, unite); });
}

function tableauDevises(e) {
  const defile = el("div", "defile");
  const t = el("table", "dense dossier");
  const tete = el("tr");
  tete.appendChild(el("th", null, "Devise"));
  for (const col of e.colonnes) tete.appendChild(el("th", null, col.libelle));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  for (const l of e.lignes) {
    const tr = el("tr");
    tr.appendChild(el("td", null, `${DRAPEAUX[l.devise] || ""} ${l.devise}`));
    for (const col of e.colonnes) {
      const c = l.cellules[col.id];
      const td = el("td");
      if (col.id === "prochaine_reunion") {
        td.textContent = c?.texte ? dateCourte(c.texte) : "—";
      } else if (col.id === "publications") {
        td.className = "texte-long";
        const liste = c?.liste || [];
        if (!liste.length) td.appendChild(el("span", "nd", "n/d"));
        for (const p of liste) td.appendChild(el("div", p.surprise > 0 ? "pos" : p.surprise < 0 ? "neg" : "",
          `${p.indicateur} : ${p.reel} vs ${p.consensus} (${signe(p.surprise, 2)})`));
      } else {
        cellule(td, c, col.unite, `${l.devise} — ${col.libelle}`);
      }
      tr.appendChild(td);
    }
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t);
  return defile;
}

const COLONNES_CORREL = ["VIX", "Indice dollar large (Fed)", "Indice or (proxy)", "Pétrole WTI", "S&P 500", "Rendement 10 ans US"];
const COURTS = { "Indice dollar large (Fed)": "Dollar", "Indice or (proxy)": "Or (proxy)", "Pétrole WTI": "WTI", "Rendement 10 ans US": "10 ans US" };

function tableauInstruments(e) {
  const defile = el("div", "defile");
  const t = el("table", "dense dossier");
  const tete = el("tr");
  for (const h of ["Instrument", "Valeur", "1 sem.", "4 sem.", "Percentile 5 ans", "Date"]) tete.appendChild(el("th", null, h));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  for (const l of e.instruments) {
    const c = l.cellule; const tr = el("tr");
    const nom = el("td", null, l.libelle);
    if (c.alerte) nom.appendChild(el("div", "tag-alerte", "série heurtée"));
    tr.appendChild(nom);
    const taux = l.unite_affichage === "%";
    const suf = taux ? " pb" : " %";
    tr.appendChild(el("td", "tabulaire", c.valeur === null ? "n/d" : `${nombre(c.valeur)}${taux ? " %" : ""}`));
    tr.appendChild(el("td", `tabulaire ${c.var_1s > 0 ? "pos" : c.var_1s < 0 ? "neg" : ""}`, c.var_1s === null ? "—" : `${signe(c.var_1s, taux ? 0 : 2)}${suf}`));
    tr.appendChild(el("td", `tabulaire ${c.var_4s > 0 ? "pos" : c.var_4s < 0 ? "neg" : ""}`, c.var_4s === null ? "—" : `${signe(c.var_4s, taux ? 0 : 2)}${suf}`));
    const tdp = el("td"); tdp.appendChild(pastillePercentile(c.percentile_5a)); tr.appendChild(tdp);
    tr.appendChild(el("td", "tabulaire", c.date ? dateCourte(c.date) : "—"));
    tr.addEventListener("click", () => detailCellule(l.libelle, { ...c, unite: taux ? "%" : "niveau" }, null));
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t);
  return defile;
}

function matriceCorrelations(c) {
  const defile = el("div", "defile");
  const t = el("table", "dense heatmap");
  const tete = el("tr"); tete.appendChild(el("th", null, "Devise"));
  for (const n of COLONNES_CORREL) tete.appendChild(el("th", null, COURTS[n] || n));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  for (const dev of Object.keys(DRAPEAUX)) {
    if (!c.matrice[dev]) continue;
    const tr = el("tr"); tr.appendChild(el("td", null, `${DRAPEAUX[dev]} ${dev}`));
    for (const n of COLONNES_CORREL) {
      const r = c.matrice[dev][n];
      const td = el("td", "case", r === null || r === undefined ? "—" : signe(r, 2));
      if (r !== null && r !== undefined && Math.abs(r) >= 0.1) {
        td.style.background = `color-mix(in srgb, var(${r > 0 ? "--positif" : "--negatif"}) ${Math.round(15 + 60 * Math.min(1, Math.abs(r)))}%, var(--carte))`;
      }
      tr.appendChild(td);
    }
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t);
  return defile;
}

function contenuEngrenage(e) {
  const bloc = el("div", "dossier-contenu");
  if (!e) { bloc.appendChild(el("p", "indisponible", "Dossier chiffré prévu au palier suivant (graphiques et précédents historiques).")); return bloc; }
  if (e.indisponible) { bloc.appendChild(el("p", "indisponible", `Indisponible : ${e.indisponible}.`)); return bloc; }
  if (e.lignes) bloc.appendChild(tableauDevises(e));
  if (e.instruments) {
    if (e.regime_volatilite) bloc.appendChild(el("p", "note", `Volatilité implicite (VIX) : régime ${e.regime_volatilite}.`));
    bloc.appendChild(tableauInstruments(e));
    const c = e.correlations;
    if (c) {
      bloc.appendChild(el("h3", null, `Corrélations sur ${c.seances} séances (jusqu'au ${dateCourte(c.derniere_seance)})`));
      bloc.appendChild(el("p", "note", "Rendements quotidiens de la force de chaque devise contre ceux des marchés. Vert : évoluent ensemble ; rouge : en sens inverse."));
      bloc.appendChild(matriceCorrelations(c));
      bloc.appendChild(el("p", "note", c.changements_de_signe?.length
        ? `Corrélations qui ont changé de signe : ${c.changements_de_signe.map(x => `${x.paire.join(" / ")} (${signe(x.avant, 2)} → ${signe(x.maintenant, 2)})`).join(" ; ")}.`
        : "Aucune corrélation marquée (≥ 0,3) n'a changé de signe par rapport aux 30 séances précédentes."));
    }
  }
  const notes = el("ul", "notes");
  for (const n of e.notes || []) notes.appendChild(el("li", null, n));
  bloc.appendChild(notes);
  return bloc;
}

const NOMS = { 1: "Thème macro", 2: "Politique monétaire", 3: "Données économiques", 4: "Politique fiscale",
               5: "Interconnexions", 6: "Géopolitique", 7: "Price action et flux", 8: "Offre et demande" };

export async function carteDossiers() {
  const d = await chargerJson("data/dossiers.json");
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Dossiers chiffrés"));
  if (enErreur(d)) { c.appendChild(el("p", "indisponible", `Indisponible : ${d?.__erreur || "dossiers.json absent"}.`)); return c; }
  c.appendChild(el("p", "sous-titre", `Calcul Python quotidien, sans LLM · généré ${dateHeure(d.genere_le)} · percentile = position de la valeur actuelle parmi les 5 dernières années (p90 : plus haut que 90 % du temps). Touchez une case pour le détail.`));
  const selecteur = el("div", "selecteur-engrenages");
  const zone = el("div");
  let actif = Number(new URLSearchParams(location.hash.split("?")[1] || "").get("e")) || 2;
  const boutons = [];
  for (let n = 1; n <= 8; n++) {
    const b = el("button", "bouton", String(n));
    b.type = "button"; b.title = NOMS[n];
    if (!d.engrenages?.[n]) b.classList.add("bientot");
    b.addEventListener("click", () => { actif = n; rendre(); });
    boutons.push(b); selecteur.appendChild(b);
  }
  function rendre() {
    boutons.forEach((b, i) => b.setAttribute("aria-pressed", String(i + 1 === actif)));
    zone.replaceChildren(el("h3", "dossier-titre", `${actif}. ${NOMS[actif]}`), contenuEngrenage(d.engrenages?.[actif]));
  }
  c.appendChild(selecteur); c.appendChild(zone);
  if ((d.erreurs_collecte || []).length) c.appendChild(el("p", "tag-alerte", `Séries indisponibles aujourd'hui : ${d.erreurs_collecte.join(" ; ")}`));
  rendre();
  return c;
}
