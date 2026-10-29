/* Page d'accueil « Aujourd'hui » (lot V5, étape 7-ter) : le tableau de bord du jour, à lire en 30 secondes.
   Ne charge que docs/data/accueil.json (quelques Ko) ; le globe (d3-geo, world-atlas) arrive après l'affichage.
   Notes : lues dans ce navigateur (IndexedDB du Journal), jamais envoyées. Jamais un ordre d'achat ou de vente. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, DRAPEAUX, certifier } from "./commun.js";

const DATE_LONGUE = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Paris" });
const HEURE = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Paris" });
const COURTS = { 1: "Thème", 2: "Monétaire", 3: "Données", 4: "Fiscale", 5: "Marchés", 6: "Géopolitique", 7: "Flux", 8: "Offre" };
const BIAIS = { haussier: "Haussier", neutre: "Neutre", baissier: "Baissier" };

function rebours(iso) {
  const s = Math.floor((Date.parse(iso) - Date.now()) / 1000);
  if (isNaN(s)) return "";
  if (s <= 0) return "en cours ou passé";
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  return h >= 1 ? `dans ${h} h ${String(m).padStart(2, "0")}` : `dans ${m} min ${String(s % 60).padStart(2, "0")} s`;
}

function horloge() {
  const p = el("p", "ac-horloge");
  const d = el("span", "ac-date"), h = el("b", "ac-heure tabulaire");
  p.append(d, h);
  const maj = () => { const n = new Date(); d.textContent = DATE_LONGUE.format(n); h.textContent = `${HEURE.format(n)} à Paris`; };
  maj();
  return [p, maj];
}

function blocTheme(a) {
  const c = el("section", "carte ac-theme apparait");
  const t = a.theme || {};
  const [hor, majHorloge] = horloge();
  c.appendChild(hor);
  const titre = el("h2", "ac-titre", t.titre || "Thème n/d");
  c.appendChild(titre);
  const ligne = el("div", "ac-ligne");
  ligne.appendChild(el("span", `ck-pastille dir-${t.direction?.classe || "nd"}`, t.direction?.libelle || "direction n/d"));
  ligne.appendChild(el("span", "ac-conviction", `Conviction ${{ faible: "faible", moyen: "moyenne", fort: "forte", forte: "forte" }[t.conviction] || t.conviction || "n/d"}`));
  if (t.alignes != null) ligne.appendChild(el("span", "note", `${t.alignes} engrenage(s) aligné(s) sur ${t.evaluables}`));
  c.appendChild(ligne);
  if (t.texte) {
    const p = el("p", "ac-texte", t.texte);
    p.appendChild(el("span", "source", t.texte_source === "modèle" ? " — formulé par le modèle à partir des chiffres Python" : " — calcul Python"));
    c.appendChild(p);
  }
  const lien = el("a", "ac-lien", "Ouvrir le cockpit des 8 engrenages →"); lien.href = "#engrenages";
  c.append(el("p", "note", `Rapport du ${dateCourte(a.date_rapport)} · ${t.compte_matrice || ""}`), lien);
  return [c, majHorloge];
}

function blocBord(a) {
  const c = el("section", "carte ac-bord apparait");
  c.appendChild(el("h2", null, "Au bord du seuil"));
  if (!(a.au_bord || []).length) { c.appendChild(el("p", "note", "Aucun signal proche de son seuil aujourd'hui.")); return c; }
  const ul = el("ul", "ac-liste");
  for (const s of a.au_bord) {
    const li = el("li");
    const val = el("b", "tabulaire", s.texte_valeur ?? "n/d");
    certifier(val, { libelle: s.libelle, valeur: s.texte_valeur, source: s.source, date: s.date });
    const lien = el("a", "ac-eng", `${s.engrenage} ${COURTS[s.engrenage] || ""}`); lien.href = `#g=${s.engrenage}`;
    li.append(lien, el("span", "ac-lib", s.libelle), val, el("span", "ac-dist tabulaire", `à ${s.distance_texte} du seuil`));
    ul.appendChild(li);
  }
  c.appendChild(ul);
  c.appendChild(el("p", "note", `${a.franchis || 0} seuil(s) déjà franchi(s) aujourd'hui · distances calculées en Python, en unité réelle.`));
  return c;
}

function blocEvenements(a) {
  const c = el("section", "carte ac-evts apparait");
  const tete = el("div", "ac-evts-tete");
  tete.appendChild(el("h2", null, "Les prochaines 24 heures"));
  const lien = el("a", "ac-lien", "Agenda complet →"); lien.href = "#agenda";
  tete.appendChild(lien);
  c.appendChild(tete);
  const corps = el("div", "ac-evts-corps");
  const ul = el("ul", "ac-agenda");
  const maintenant = Date.now();
  const liste = (a.evenements || []).filter(e => { const t = Date.parse(e.iso_utc); return t >= maintenant - 36e5 && t <= maintenant + 864e5; });
  for (const e of liste) {
    const li = el("li", `impact-${e.impact}`);
    const cr = el("span", "ac-rebours tabulaire", rebours(e.iso_utc)); cr.dataset.iso = e.iso_utc;
    const titre = el("span", "ac-evt-titre");
    titre.append(el("b", null, `${DRAPEAUX[e.devise] || ""} ${e.devise}`), document.createTextNode(` ${e.evenement} `), el("span", `ag-points ${e.impact}`, e.points || ""));
    if (e.badge && e.badge.sens !== "statu_quo") titre.appendChild(el("span", `ag-badge ${e.badge.sens}`, e.badge.texte));
    li.append(el("span", "ac-h tabulaire", e.heure_paris === "journée" ? "—" : e.heure_paris), titre, cr);
    if (e.consensus || e.publie) li.appendChild(el("span", "ac-valeurs tabulaire", `${e.consensus ? `cons. ${String(e.consensus).replace(".", ",")}` : ""}${e.publie ? ` · réel ${String(e.publie).replace(".", ",")}` : ""}`));
    ul.appendChild(li);
  }
  if (!liste.length) ul.appendChild(el("li", "note", a.raison_evenements || "Aucun évènement fort ou moyen, ni décision ou discours de banque centrale, dans les 24 heures."));
  const globe = el("div", "ac-globe");
  globe.appendChild(el("p", "note", "Globe des banques centrales…"));
  corps.append(ul, globe);
  c.appendChild(corps);
  // Globe chargé APRÈS l'affichage (bibliothèques externes) : la page reste interactive tout de suite
  const banques = (a.banques || []).filter(b => b.siege);
  const lancer = () => import("./agenda.js").then(m => m.dessinerGlobe(globe, banques, () => { location.hash = "#agenda"; }))
    .catch(() => { globe.replaceChildren(el("p", "note", "Globe indisponible : voir l'Agenda.")); });
  ("requestIdleCallback" in window) ? requestIdleCallback(lancer, { timeout: 1500 }) : setTimeout(lancer, 300);
  return c;
}

async function lireNotes() {
  if (!("indexedDB" in window)) return { raison: "IndexedDB indisponible" };
  return new Promise(ok => {
    let req;
    try { req = indexedDB.open("fxdesk-journal", 1); } catch (e) { ok({ raison: "stockage indisponible" }); return; }
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("notes")) db.createObjectStore("notes", { keyPath: "id" });
      if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta", { keyPath: "cle" });
    };
    req.onerror = () => ok({ raison: "stockage refusé (navigation privée ?)" });
    req.onsuccess = () => {
      try {
        const r = req.result.transaction("notes", "readonly").objectStore("notes").getAll();
        r.onsuccess = () => ok({ notes: (r.result || []).sort((x, y) => String(y.cree_le).localeCompare(String(x.cree_le))).slice(0, 3) });
        r.onerror = () => ok({ raison: "lecture impossible" });
      } catch (e) { ok({ raison: "lecture impossible" }); }
    };
  });
}

function blocNotes() {
  const c = el("section", "carte ac-notes apparait");
  const tete = el("div", "ac-evts-tete");
  tete.appendChild(el("h2", null, "Mes dernières notes"));
  const lien = el("a", "ac-lien", "Journal →"); lien.href = "#journal";
  tete.appendChild(lien);
  c.appendChild(tete);
  const ul = el("ul", "ac-liste");
  c.appendChild(ul);
  lireNotes().then(r => {
    if (r.raison) { ul.appendChild(el("li", "note", `Notes n/d : ${r.raison}.`)); return; }
    if (!r.notes.length) { ul.appendChild(el("li", "note", "Aucune note dans ce navigateur. Le Journal garde vos lectures avec l'instantané de l'analyse du jour.")); return; }
    for (const n of r.notes) {
      const li = el("li");
      li.append(el("b", null, n.paire), el("span", `jn-biais-puce ${n.biais}`, BIAIS[n.biais] || "—"),
                el("span", "ac-lib", String(n.texte || "").replace(/\s+/g, " ").slice(0, 110)), el("span", "note", dateCourte(n.cree_le)));
      ul.appendChild(li);
    }
  });
  return c;
}

function blocFraicheur(a) {
  const f = a.fraicheur || {};
  const c = el("section", "carte ac-frais apparait");
  const tete = el("div", "ac-evts-tete");
  tete.appendChild(el("h2", null, "Fraîcheur des données"));
  const lien = el("a", "ac-lien", "Santé des données →"); lien.href = "#sante";
  tete.appendChild(lien);
  c.appendChild(tete);
  c.appendChild(el("p", "ac-frais-ligne", `${f.vertes ?? "n/d"} source(s) à jour sur ${f.sources ?? "n/d"}`));
  if ((f.alertes || []).length) {
    const ul = el("ul", "ac-alertes");
    for (const x of f.alertes) ul.appendChild(el("li", null, `${x.nom || x.libelle} : ${x.texte}`));
    c.appendChild(ul);
  } else c.appendChild(el("p", "note", "Aucune donnée plus vieille que deux fois sa fréquence normale."));
  c.appendChild(el("p", "note", `Contrôle du ${dateHeure(f.calcule_le)}.`));
  return c;
}

export async function pageAccueil() {
  const a = await chargerJson("data/accueil.json");
  if (enErreur(a)) return [indisponible("Aujourd'hui", a?.__erreur || "accueil.json absent (prochain run)")];
  const [theme, majHorloge] = blocTheme(a);
  const grille = el("div", "ac-grille");
  const evts = blocEvenements(a);
  grille.append(blocBord(a), blocFraicheur(a), blocNotes());
  const minuterie = setInterval(() => {
    if (!document.body.contains(theme)) { clearInterval(minuterie); return; }
    majHorloge();
    evts.querySelectorAll(".ac-rebours").forEach(s => { s.textContent = rebours(s.dataset.iso); });
  }, 1000);
  const pied = el("p", "note ac-pied", a.note);
  return [theme, evts, grille, pied];
}
