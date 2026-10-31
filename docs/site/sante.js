/* Page « Santé » (lot V5, étape 7-bis) : docs/data/sources.json, calcul Python sans LLM ni requête de plus.
   Registre des sources (statut légal, dernière donnée, fraîcheur), alertes, certificats des indicateurs,
   extractions de pages remplacées ou restantes, et ce que le site peut annoncer honnêtement. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, certifier, pluriel } from "./commun.js";

const NOMBRE = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });
const ETATS = { vert: "à jour", orange: "à surveiller", rouge: "trop ancienne", retiree: "retirée" };

function compteur(valeur, libelle, classe) {
  const d = el("div", `sa-compteur ${classe || ""}`);
  d.append(el("b", "tabulaire", String(valeur)), el("span", null, libelle));
  return d;
}

function entete(s) {
  const c = el("section", "carte sa-tete");
  c.appendChild(el("p", "surtitre", `Santé des données · contrôle du ${dateHeure(s.genere_le)}`));
  c.appendChild(el("h2", "ag-h1", "D'où viennent les chiffres"));
  const g = el("div", "sa-compteurs");
  g.append(compteur(s.comptes?.officielle ?? 0, "sources officielles", "officielle"), compteur(s.comptes?.api ?? 0, "API sous licence gratuite", "api"),
           compteur(s.comptes?.flux ?? 0, "flux publics", "flux"), compteur(s.a_remplacer ?? 0, "extraction de page à remplacer", "extraction"),
           compteur((s.retirees || []).length, "extractions retirées", "retiree"));
  c.appendChild(g);
  const alertes = [...(s.alertes || []), ...(s.alertes_indicateurs || [])];
  if (alertes.length) {
    const a = el("div", "alerte sa-alertes");
    a.appendChild(el("b", null, `Fraîcheur : ${pluriel(alertes.length, "donnée plus vieille", "données plus vieilles")} que deux fois la normale`));
    const ul = el("ul");
    for (const x of alertes) ul.appendChild(el("li", null, `${x.nom || x.libelle} : ${x.texte}`));
    a.appendChild(ul);
    c.appendChild(a);
  } else c.appendChild(el("p", "note", "Fraîcheur : aucune donnée plus vieille que deux fois sa fréquence normale."));
  c.appendChild(el("p", "note", s.regles || ""));
  return c;
}

function registre(s) {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Registre des sources"));
  c.appendChild(el("p", "sous-titre", "Date de la dernière donnée lue dans ce que le run a collecté ; aucune requête de plus."));
  const defile = el("div", "defile");
  const t = el("table", "dense sa-table");
  const tr0 = el("tr");
  for (const h of ["Source", "Ce qu'elle alimente", "Statut légal", "Fréquence", "Dernière donnée", "Fraîcheur"]) tr0.appendChild(el("th", null, h));
  const thead = el("thead"); thead.appendChild(tr0); t.appendChild(thead);
  const corps = el("tbody");
  for (const x of (s.sources || []).filter(x => !x.retiree)) {
    const tr = el("tr");
    const nom = el("td", "sa-nom");
    nom.appendChild(el("b", null, x.nom));
    if (x.a_remplacer) nom.appendChild(el("span", "sa-puce extraction", "à remplacer"));
    tr.appendChild(nom);
    tr.appendChild(el("td", "sa-alimente", x.alimente || "—"));
    const statut = el("td"); statut.appendChild(el("span", `sa-puce ${x.statut}`, x.statut_libelle)); tr.appendChild(statut);
    tr.appendChild(el("td", null, `${x.frequence}${x.retard_jours ? ` · délai ${x.retard_jours} j` : ""}`));
    tr.appendChild(el("td", "tabulaire", x.derniere_donnee ? dateCourte(x.derniere_donnee) : "n/d"));
    const f = el("td", `sa-frais ${x.fraicheur?.etat}`);
    f.append(el("b", null, ETATS[x.fraicheur?.etat] || "n/d"), el("span", "note", ` ${x.fraicheur?.texte || ""}`));
    tr.appendChild(f);
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t); c.appendChild(defile);
  return c;
}

function indicateurs(s) {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Le « certificat » de chaque chiffre"));
  c.appendChild(el("p", "sous-titre", "Survolez, touchez ou parcourez au clavier un chiffre souligné en pointillé, n'importe où sur le site : sa source, sa série, la date de la valeur, l'heure de récupération, le contrôle croisé et son âge s'affichent. En orange : plus vieux que deux fois la normale."));
  const exemple = s.certificats?.vix;
  if (exemple?.valeur != null) {
    const carte = el("div", "sa-exemple");
    carte.append(el("p", "surtitre", "Exemple réel"), el("p", "sa-ex-tete", `${exemple.libelle} ${NOMBRE.format(exemple.valeur)}`),
                 el("p", null, `Source : ${exemple.source}`),
                 el("p", null, `Valeur du ${dateCourte(exemple.date_valeur)} · récupérée le ${dateCourte(exemple.recupere_le)}`),
                 el("p", null, `Contrôle croisé : ${exemple.controle} ${exemple.controle === "✓" ? "même valeur dans tous les modules" : exemple.controle_detail}`),
                 el("p", `cert-age ${exemple.fraicheur?.etat}`, `Âge : ${exemple.fraicheur?.texte}`));
    c.appendChild(carte);
  }
  const defile = el("div", "defile");
  const t = el("table", "dense sa-table");
  const tr0 = el("tr");
  for (const h of ["Indicateur", "Valeur", "Date", "Contrôle", "Âge"]) tr0.appendChild(el("th", null, h));
  const thead = el("thead"); thead.appendChild(tr0); t.appendChild(thead);
  const corps = el("tbody");
  for (const [id, x] of Object.entries(s.certificats || {})) {
    const tr = el("tr");
    tr.appendChild(el("td", "sa-nom", x.libelle));
    const v = el("td", "tabulaire", x.valeur == null ? "n/d" : `${NOMBRE.format(x.valeur)} ${x.unite === "%" ? "%" : ""}`.trim());
    if (x.valeur != null) certifier(v, { libelle: x.libelle, valeur: v.textContent, source: x.source, date: x.date_valeur, indicateur: id });
    else v.title = x.raison || "";
    tr.appendChild(v);
    tr.appendChild(el("td", "tabulaire", x.date_valeur ? dateCourte(x.date_valeur) : "n/d"));
    tr.appendChild(el("td", null, x.controle || "n/d"));
    tr.appendChild(el("td", `sa-frais ${x.fraicheur?.etat || ""}`, x.fraicheur?.texte || x.raison || "n/d"));
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t); c.appendChild(defile);
  return c;
}

function extractions(s) {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Extractions de pages : remplacées et restantes"));
  const ul = el("ul", "sa-liste");
  for (const x of (s.sources || []).filter(x => x.statut === "extraction")) {
    const li = el("li");
    li.append(el("span", `sa-puce ${x.retiree ? "retiree" : "extraction"}`, x.retiree ? "retirée" : "gardée · à remplacer"),
              el("b", null, x.nom), el("p", null, `Apport : ${x.alimente}`), el("p", "note", x.remplacement || ""));
    ul.appendChild(li);
  }
  c.appendChild(ul);
  return c;
}

function honnetete(s) {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Ce que le site peut annoncer honnêtement"));
  const ul = el("ul", "sa-niveaux");
  for (const n of s.niveaux || []) {
    const li = el("li");
    li.append(el("span", `sa-niveau ${n.classe}`, n.niveau), el("span", null, n.texte));
    ul.appendChild(li);
  }
  c.appendChild(ul);
  return c;
}

export async function pageSante() {
  const s = await chargerJson("data/sources.json");
  if (enErreur(s)) return [indisponible("Santé des données", s?.__erreur || "sources.json absent (prochain run)")];
  const bas = el("div", "ag-bas");
  bas.append(extractions(s), honnetete(s));
  return [entete(s), registre(s), indicateurs(s), bas];
}
