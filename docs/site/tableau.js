/* Onglet Tableau macro : docs/data/tableau_macro.json, regroupé par devise, tri et recherche. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, ouvrirDetail, listeDefinitions, certifier, fraicheurLocale, essentiel, voirDetail, DRAPEAUX } from "./commun.js";

const COLONNES = [
  { cle: "libelle", titre: "Indicateur" }, { cle: "Actuel", titre: "Actuel" }, { cle: "Précédent", titre: "Précédent" },
  { cle: "surprise", titre: "Surprise · taux" },   // lot V6 : « Prévision » repliée (audit : 19 % remplie), dans le détail { cle: "date_pub", titre: "Publié le" },
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
  const prevues = (t.lignes || []).filter(l => l.etat?.["Prévision"] === "valeur").length;
  c.appendChild(el("p", "note", `Prévision : données insuffisantes pour une colonne (${prevues} ${prevues < 2 ? "ligne renseignée" : "lignes renseignées"} sur ${(t.lignes || []).length} : le consensus de la prochaine publication est rarement connu à l'avance). Elle reste dans le détail de chaque ligne.`));
  if (JSON.stringify(t.lignes || []).includes("taux de refinancement")) c.appendChild(el("p", "note",
    "EUR, « taux de refinancement » : taux principal publié par ForexFactory. Le site utilise le taux de dépôt de la BCE (ECBDFR, 15 pb plus bas) pour le portage et les dossiers des engrenages."));

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
          } else {
            td.textContent = v ?? "—";
            if (col.cle === "Actuel" && v && l.frequence) {   // lot V6 : valeur ancienne signalée (plus de 2 fois sa fréquence)
              const f = fraicheurLocale(l.date_pub, { frequence: "quotidienne (jours ouvrés)" }, l.frequence);
              if (f && f.etat !== "vert") { const a = el("span", `tag-ancien ${f.etat}`, "ancienne"); a.title = `Âge : ${f.texte}`; td.appendChild(a); }
            }
            if (col.cle === "Actuel" && v) certifier(td, { libelle: `${l.libelle} ${l.devise}`, valeur: v, source: l.source, date: l.date_pub, frequence: l.frequence,
                                                        sansAge: l.frequence ? undefined : "publication ponctuelle : âge selon le calendrier de l'indicateur" });
          }
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
    compteur.textContent = n ? `${n} ${n < 2 ? "ligne affichée" : "lignes affichées"} sur ${lignes.length}.` : "Aucune ligne ne correspond à la recherche.";
  }
  recherche.addEventListener("input", rendre);
  choix.addEventListener("change", rendre);
  rendre();
  return [c];
}


/* ------------------------------------------------------------------ lot V6 : onglet « Tableau de bord »
   L'essentiel, le point de marché (rapport du jour), une ligne de lecture par devise (profil des devises), puis le
   tableau macro complet. Tout est calculé en Python ; la page n'affiche que des fichiers publiés. */
const v2 = (v, d = 2) => v == null ? "n/d" : Number(v).toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: d });
const sg = (v, d = 2) => v == null ? "n/d" : `${v > 0 ? "+" : ""}${v2(v, d)}`.replace("-", "−");

function pointMarche(pm) {
  const c = el("section", "carte");
  c.appendChild(el("h3", null, "Point de marché"));
  const d = el("div", "defile"); const t = el("table", "dense td-pm");
  const tr = el("tr"); for (const h of ["Actif", "Niveau", "J-1", "5 séances", "Lecture", "Date"]) tr.appendChild(el("th", null, h));
  const th = el("thead"); th.appendChild(tr); t.appendChild(th);
  const tb = el("tbody");
  for (const l of pm.lignes || []) {
    const r = el("tr");
    const u = l.unite === "pb" ? " pb" : l.unite === "%" ? " %" : "";
    r.append(el("td", null, l.actif), el("td", "tabulaire", l.niveau == null ? `n/d` : `${v2(l.niveau, l.decimales ?? 2)}${l.suffixe || ""}`),
             el("td", "tabulaire", l.variation_j1 == null ? "n/d" : `${sg(l.variation_j1, l.unite === "pb" ? 0 : 2)}${u}`),
             el("td", "tabulaire", l.variation_5j == null ? "n/d" : `${sg(l.variation_5j, l.unite === "pb" ? 0 : 2)}${u}`),
             el("td", null, l.lecture || l.raison || "n/d"));
    const date = String(l.heure || "").slice(0, 10);
    const td = el("td", "tabulaire", date ? dateCourte(date) : "n/d");
    const f = date ? fraicheurLocale(date, { frequence: "quotidienne (jours ouvrés)", retard_jours: 1 }) : null;
    if (f && f.etat !== "vert") { const a = el("span", `tag-ancien ${f.etat}`, "ancienne"); a.title = `Âge : ${f.texte}`; td.appendChild(a); }
    r.appendChild(td);
    tb.appendChild(r);
  }
  t.appendChild(tb); d.appendChild(t); c.appendChild(d);
  c.appendChild(el("p", "note", "Source et date de chaque ligne au survol dans la Synthèse ; « ancienne » : valeur plus vieille que deux fois son rythme normal de publication."));
  return c;
}

function lecturesDevises(profil) {
  const c = el("section", "carte");
  c.appendChild(el("h3", null, "Lecture par devise"));
  const ul = el("ul", "td-lectures");
  for (const p of profil.devises || []) {
    const li = el("li");
    li.append(el("b", null, `${DRAPEAUX[p.devise] || ""} ${p.devise} · ${p.etat.valeur}`), document.createTextNode(` — ${p.macro.texte}. ${p.banque_centrale.texte}.`));
    ul.appendChild(li);
  }
  c.appendChild(ul);
  return c;
}

export async function pageTableauDeBord() {
  const [rj, profil] = await Promise.all([chargerJson("data/rapport_jour.json"), chargerJson("data/profil_devises.json")]);
  const tete = el("section", "carte");
  tete.appendChild(el("h2", null, "Tableau de bord"));
  const pm = enErreur(rj) ? null : rj.point_marche;
  const anciennes = (pm?.lignes || []).filter(l => { const d = String(l.heure || "").slice(0, 10); const f = d ? fraicheurLocale(d, { frequence: "quotidienne (jours ouvrés)", retard_jours: 1 }) : null; return f && f.etat !== "vert"; });
  tete.appendChild(essentiel([
    pm?.lecture ? `Marchés : ${pm.lecture}.` : "Point de marché n/d (rapport du jour absent).",
    enErreur(profil) ? "Profil des devises n/d." : `Surprises macro 30 jours les plus marquées : ${(profil.devises || []).filter(p => p.macro?.surprise_30j?.indice != null)
      .sort((a, b) => Math.abs(b.macro.surprise_30j.indice) - Math.abs(a.macro.surprise_30j.indice)).slice(0, 2)
      .map(p => `${p.devise} ${sg(p.macro.surprise_30j.indice, 1)}`).join(", ") || "n/d"}.`,
    anciennes.length ? `${anciennes.length} ${anciennes.length < 2 ? "valeur de marché ancienne signalée" : "valeurs de marché anciennes signalées"} (${anciennes.map(l => l.actif).slice(0, 3).join(", ")}).` : "Toutes les valeurs de marché sont à jour.",
  ]));
  const sortie = [tete];
  if (pm) sortie.push(pointMarche(pm));
  if (!enErreur(profil)) sortie.push(lecturesDevises(profil));
  sortie.push(...await pageTableau());
  return sortie;
}
