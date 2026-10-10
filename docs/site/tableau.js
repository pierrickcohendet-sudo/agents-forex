/* Onglet Tableau macro : docs/data/tableau_macro.json, regroupé par devise, tri et recherche. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, ouvrirDetail, listeDefinitions, DRAPEAUX } from "./commun.js";

const COLONNES = [
  { cle: "libelle", titre: "Indicateur" }, { cle: "Actuel", titre: "Actuel" }, { cle: "Précédent", titre: "Précédent" },
  { cle: "Prévision", titre: "Prévision" }, { cle: "surprise", titre: "Surprise" }, { cle: "date_pub", titre: "Publié le" },
  { cle: "prochaine", titre: "Prochaine" }, { cle: "source", titre: "Source" },
];
const normaliser = t => String(t ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
function nombre(t) {
  const m = String(t ?? "").replace(/\s/g, "").match(/[+-]?\d+(?:[.,]\d+)?/);
  return m ? Number(m[0].replace(",", ".")) : null;
}

export async function pageTableau() {
  const t = await chargerJson("data/tableau_macro.json");
  if (enErreur(t)) return [indisponible("Tableau macro", t?.__erreur || "tableau absent")];
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Tableau macro"));
  c.appendChild(el("p", "sous-titre", `Mis à jour ${dateHeure(t.maj)} · une ligne par indicateur et par devise · ✍ = saisie manuelle Notion. Touchez une ligne pour le détail.`));

  const outils = el("div", "outils");
  const recherche = el("input"); recherche.type = "search"; recherche.placeholder = "Rechercher (ex. CPI, chômage, JPY)…";
  recherche.setAttribute("aria-label", "Rechercher un indicateur ou une devise");
  const choix = el("select"); choix.setAttribute("aria-label", "Devise");
  choix.appendChild(new Option("Toutes les devises", ""));
  for (const d of t.devises || []) choix.appendChild(new Option(`${DRAPEAUX[d] || ""} ${d}`, d));
  outils.append(recherche, choix);
  c.appendChild(outils);

  const defile = el("div", "defile");
  const table = el("table", "dense macro");
  const tete = el("tr");
  let tri = { cle: null, sens: 1 };
  for (const col of COLONNES) {
    const th = el("th"); const b = el("button", null, col.titre);
    b.addEventListener("click", () => { tri = { cle: col.cle, sens: tri.cle === col.cle ? -tri.sens : 1 }; rendre(); });
    th.appendChild(b); tete.appendChild(th);
  }
  const thead = el("thead"); thead.appendChild(tete); table.appendChild(thead);
  const corps = el("tbody"); table.appendChild(corps);
  defile.appendChild(table);
  c.appendChild(defile);
  const compteur = el("p", "note"); c.appendChild(compteur);

  const lignes = t.lignes || [];
  function valeurTri(l, cle) {
    if (["Actuel", "Précédent", "Prévision"].includes(cle)) return l.etat?.[cle] === "valeur" ? nombre(l[cle]) : null;
    if (cle === "libelle") return l.ordre ?? 0;
    return l[cle] ?? null;
  }
  function rendre() {
    const q = normaliser(recherche.value.trim());
    const devise = choix.value;
    corps.replaceChildren();
    let n = 0;
    for (const d of t.devises || []) {
      if (devise && d !== devise) continue;
      let groupe = lignes.filter(l => l.devise === d && (!q || normaliser(`${l.libelle} ${l.devise} ${l.source}`).includes(q)));
      if (!groupe.length) continue;
      if (tri.cle) groupe = [...groupe].sort((a, b) => {
        const va = valeurTri(a, tri.cle), vb = valeurTri(b, tri.cle);
        if (va === null && vb === null) return 0; if (va === null) return 1; if (vb === null) return -1;
        return (typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb))) * tri.sens;
      });
      const trg = el("tr", "groupe"); const tdg = el("td", null, `${DRAPEAUX[d] || ""} ${d}`); tdg.colSpan = COLONNES.length;
      trg.appendChild(tdg); corps.appendChild(trg);
      for (const l of groupe) {
        n++;
        const tr = el("tr");
        for (const col of COLONNES) {
          let v = l[col.cle];
          if (col.cle === "date_pub") v = l.date_pub ? dateCourte(l.date_pub) : "—";
          if (col.cle === "prochaine") v = l.prochaine ? dateCourte(l.prochaine.slice(0, 10)) : "—";
          const td = el("td", col.cle === "source" ? "source-cellule" : null);
          if (["Actuel", "Précédent", "Prévision"].includes(col.cle) && l.etat?.[col.cle] !== "valeur") {
            td.appendChild(el("span", "nd", v || "n/d"));
          } else td.textContent = v ?? "—";
          if (l.manuel?.[col.cle]) td.appendChild(el("span", "manuel", "✍"));
          tr.appendChild(td);
        }
        tr.addEventListener("click", () => {
          const cel = t.cellules?.[l.indicateur]?.[l.devise] || {};
          ouvrirDetail(`${l.devise} — ${l.libelle}`, [listeDefinitions([
            ["Actuel", cel.Actuel?.texte ?? l.Actuel], ["Consensus de la publication", cel.Actuel?.consensus ?? undefined],
            ["Précédent", cel["Précédent"]?.texte ?? l["Précédent"]], ["Prévision", cel["Prévision"]?.texte ?? l["Prévision"]],
            ["Surprise", l.surprise ?? undefined], ["Variation", l.variation ?? undefined],
            ["Publié le", l.date_pub ? dateCourte(l.date_pub) : undefined], ["Prochaine publication", l.prochaine ? dateHeure(l.prochaine) : undefined],
            ["Source", l.source], ["Fréquence", l.frequence ?? undefined]])]);
        });
        corps.appendChild(tr);
      }
    }
    compteur.textContent = n ? `${n} ligne(s) affichée(s) sur ${lignes.length}.` : "Aucune ligne ne correspond à la recherche.";
  }
  recherche.addEventListener("input", rendre);
  choix.addEventListener("change", rendre);
  rendre();
  return [c];
}
