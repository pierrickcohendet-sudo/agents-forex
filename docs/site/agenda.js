/* Page Agenda (lot V5, complément) : docs/data/agenda.json, calcul Python sans LLM.
   Globe des 9 banques centrales (d3-geo + world-atlas, versions épinglées, repli en liste), horloges, onglets par jour,
   filtres par type, impact et devise, réaction passée, prises de parole et grands rendez-vous. Heures de Paris. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, ouvrirDetail, listeDefinitions, certifier, DRAPEAUX } from "./commun.js";

const CDN = {
  d3geo: "https://cdn.jsdelivr.net/npm/d3-geo@3.1.1/+esm",
  topojson: "https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/+esm",
  monde: "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json",
};
const COURTS = { 1: "Thème", 2: "Monétaire", 3: "Données", 4: "Fiscale", 5: "Marchés", 6: "Géopolitique", 7: "Flux", 8: "Offre" };
const FILTRES = [["tout", "Tout"], ["bc", "Réunions BC"], ["chiffre", "Chiffres"], ["discours", "Discours"], ["fort", "Impact fort"]];
const CLASSE_TYPE = { "Réunion BC": "bc", "Conférence": "discours", "Discours": "discours", "Grand rendez-vous": "grand", "Chiffre": "chiffre" };
const JOUR_COURT = new Intl.DateTimeFormat("fr-FR", { weekday: "short", timeZone: "UTC" });
const JOUR_LONG = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
const virgule = v => v == null || v === "" ? null : String(v).replace(/(\d)\.(\d)/g, "$1,$2");
const reduit = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function rebours(iso) {
  const ms = Date.parse(iso) - Date.now();
  if (isNaN(ms)) return "";
  if (ms <= 0) return "passé";
  const min = Math.floor(ms / 6e4), h = Math.floor(min / 60), j = Math.floor(h / 24);
  return j >= 1 ? `dans ${j} j ${h % 24} h` : h >= 1 ? `dans ${h} h ${min % 60} min` : `dans ${min} min`;
}

function horloges() {
  const p = el("p", "ag-horloges tabulaire");
  const villes = [["Paris", "Europe/Paris"], ["New York", "America/New_York"], ["Tokyo", "Asia/Tokyo"]];
  const maj = () => { p.textContent = villes.map(([v, tz]) =>
    `${v} ${new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: tz })}`).join(" · "); };
  maj();
  return [p, maj];
}

// Taux tel que publié (« 2.75% » -> « 2,75 % », « <1.25% » -> « < 1,25 % ») : jamais de zéro final perdu
const tauxTexte = b => b.taux_texte ? virgule(String(b.taux_texte).replace(/^([<>])\s*/, "$1 ").replace(/%$/, " %").replace(/(\d)\.(\d)/g, "$1,$2")) :
  b.taux == null ? "n/d" : `${virgule(b.taux.toFixed(2))} %`;
// Étiquettes du globe : BCE à gauche, BNS en dessous (sièges voisins de la BoE en Europe)
const DECALAGES = { EUR: [-9, 4, "end"], CHF: [9, 14, "start"], GBP: [9, -2, "start"] };

/* ------------------------------------------------------------------ fiche d'une banque centrale */
function ficheBanque(b) {
  const taux = tauxTexte(b);
  const variation = b.variation_pb == null ? `n/d (${b.raison_variation || "non disponible"})`
    : `${b.variation_pb === 0 ? "inchangé" : `${b.variation_pb > 0 ? "+" : "−"}${Math.abs(b.variation_pb)} pb`}${b.date_variation ? ` le ${dateCourte(b.date_variation)}` : ""}`;
  const cal = b.calendrier || {};
  ouvrirDetail(`${DRAPEAUX[b.devise] || ""} ${b.banque}`, [listeDefinitions([
    ["Taux actuel", `${taux}${b.type_taux ? ` · ${b.type_taux}` : ""} (${b.source_taux || "registre macro"}${b.date_taux ? `, ${dateCourte(b.date_taux)}` : ""})`],
    ["Information secondaire", b.taux_secondaire || b.raison_taux || undefined],
    ["Dernière variation", variation],
    ["Prochaine décision", b.prochaine ? `${dateCourte(b.prochaine)}${b.heure_prochaine && b.heure_prochaine !== "journée" ? ` à ${b.heure_prochaine} (Paris)` : ""}` : "n/d"],
    ["Consensus", b.consensus_prochaine ? `${virgule(b.consensus_prochaine)}${b.badge ? ` · ${b.badge.texte}` : ""}` : "n/d (publié par ForexFactory la semaine de la réunion)"],
    ["Réunions suivantes", (b.reunions || []).map(r => dateCourte(r.date)).join(" · ") || "n/d"],
    ["Calendrier", `${cal.source || "n/d"}${cal.verifie_le ? ` · vérifié le ${dateCourte(cal.verifie_le)}` : ""}${cal.statut && cal.statut !== "officiel" ? ` · ${cal.statut}` : ""}`],
    ["Remarque", cal.note || b.raison_reunions || undefined],
  ])]);
}

/* ------------------------------------------------------------------ globe */
function grilleBanques(banques) {
  const g = el("div", "ag-bc-grille");
  for (const b of banques) {
    const bouton = el("button", `ag-bc-case${b.cette_semaine ? " semaine" : ""}`);
    bouton.type = "button";
    bouton.append(el("b", null, `${DRAPEAUX[b.devise] || ""} ${b.court}`),
      certifier(el("span", "tabulaire", tauxTexte(b)), { libelle: `Taux directeur ${b.court}`, valeur: tauxTexte(b),
                                                        source: b.source_taux || "registre macro (ForexFactory)", date: b.date_taux, sansFocus: true,
                                                        sansAge: "taux en vigueur jusqu'à la prochaine décision" }),
      el("span", "note", b.prochaine ? `${b.cette_semaine ? "Cette semaine · " : "Prochaine : "}${dateCourte(b.prochaine).slice(0, 5)}` : "Prochaine : n/d"));
    if (b.type_taux && b.type_taux !== "taux directeur") bouton.insertBefore(el("span", "note", b.type_taux), bouton.children[2]);
    if (b.badge && b.badge.sens !== "statu_quo") bouton.appendChild(el("span", `ag-badge ${b.badge.sens}`, b.badge.texte));
    bouton.addEventListener("click", () => ficheBanque(b));
    g.appendChild(bouton);
  }
  return g;
}

export async function dessinerGlobe(zone, banques, choisir = ficheBanque) {
  const [geo, topo, monde] = await Promise.all([import(CDN.d3geo), import(CDN.topojson),
    fetch(CDN.monde).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })]);
  const pays = topo.feature(monde, monde.objects.countries);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 400 400");
  svg.setAttribute("class", "ag-globe-svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Globe des 9 banques centrales : orange si elles se réunissent cette semaine, bleu sinon");
  const proj = geo.geoOrthographic().scale(180).translate([200, 200]).clipAngle(90).rotate([-10, -25]);
  const chemin = geo.geoPath(proj);
  const mk = (tag, cls) => { const n = document.createElementNS(ns, tag); if (cls) n.setAttribute("class", cls); return n; };
  const ocean = mk("circle", "ag-ocean"); ocean.setAttribute("cx", 200); ocean.setAttribute("cy", 200); ocean.setAttribute("r", 180);
  const grille = mk("path", "ag-graticule"), terres = mk("path", "ag-terres");
  const graticule = geo.geoGraticule10();
  const points = mk("g");
  svg.append(ocean, grille, terres, points);
  const marques = banques.map(b => {
    const g = mk("g", `ag-pin${b.cette_semaine ? " semaine" : ""}`);
    g.setAttribute("tabindex", "0"); g.setAttribute("role", "button");
    g.setAttribute("aria-label", `${b.banque} : ${b.cette_semaine ? "réunion cette semaine" : "prochaine réunion"} ${b.prochaine ? dateCourte(b.prochaine) : "n/d"}`);
    const c = mk("circle"); c.setAttribute("r", 6);
    const t = mk("text"); t.textContent = b.court;
    const [dx, dy, ancre] = DECALAGES[b.devise] || [9, 4, "start"];
    t.setAttribute("x", dx); t.setAttribute("y", dy); t.setAttribute("text-anchor", ancre);
    g.append(c, t);
    g.addEventListener("click", () => choisir(b));
    g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choisir(b); } });
    points.appendChild(g);
    return [b, g];
  });
  function rendu() {
    grille.setAttribute("d", chemin(graticule));
    terres.setAttribute("d", chemin(pays));
    const centre = proj.invert([200, 200]);
    for (const [b, g] of marques) {
      const [lat, lon] = b.siege;
      const visible = geo.geoDistance([lon, lat], centre) < Math.PI / 2 - 0.05;
      g.style.display = visible ? "" : "none";
      if (visible) { const [x, y] = proj([lon, lat]); g.setAttribute("transform", `translate(${x.toFixed(1)},${y.toFixed(1)})`); }
    }
  }
  rendu();
  zone.replaceChildren(svg);
  // Rotation lente (6°/s, ~30 images/s), arrêtée si l'utilisateur préfère moins d'animations, hors écran ou en glissant
  let tourne = !reduit(), visible = true, glisse = null, dernier = 0;
  const io = "IntersectionObserver" in window ? new IntersectionObserver(es => { visible = es[0].isIntersecting; }) : null;
  io?.observe(svg);
  function boucle(t) {
    if (!document.body.contains(svg)) { io?.disconnect(); return; }
    if (tourne && visible && !glisse && t - dernier > 33) {
      const r = proj.rotate(); proj.rotate([r[0] + 6 * Math.min(t - dernier, 100) / 1000, r[1]]); rendu(); dernier = t;
    } else if (t - dernier > 33) dernier = t;
    requestAnimationFrame(boucle);
  }
  requestAnimationFrame(boucle);
  svg.addEventListener("pointerdown", e => { glisse = { x: e.clientX, y: e.clientY, r: proj.rotate() }; svg.setPointerCapture(e.pointerId); });
  svg.addEventListener("pointermove", e => {
    if (!glisse) return;
    const k = 400 / svg.getBoundingClientRect().width * 0.35;
    proj.rotate([glisse.r[0] + (e.clientX - glisse.x) * k, Math.max(-60, Math.min(60, glisse.r[1] - (e.clientY - glisse.y) * k))]);
    rendu();
  });
  const fin = () => { glisse = null; };
  svg.addEventListener("pointerup", fin); svg.addEventListener("pointercancel", fin);
  return () => { tourne = !tourne; return tourne; };
}

function blocGlobe(a) {
  const c = el("section", "carte ag-globe");
  const tete = el("div", "ag-globe-tete");
  const sem = a.semaine_reference || {};
  tete.appendChild(el("h2", null, "Banques centrales"));
  const [hor, majHor] = horloges();
  tete.appendChild(hor);
  c.appendChild(tete);
  c.appendChild(el("p", "sous-titre", `Orange : réunion la semaine du ${dateCourte(sem.debut).slice(0, 5)} au ${dateCourte(sem.fin).slice(0, 5)} ; bleu : plus tard. Cliquer une banque ouvre sa fiche.`));
  const zone = el("div", "ag-globe-zone");
  zone.appendChild(el("p", "note", "Chargement du globe…"));
  c.appendChild(zone);
  const banques = a.banques_centrales || [];
  c.appendChild(grilleBanques(banques));
  const commandes = el("p", "note ag-globe-note");
  c.appendChild(commandes);
  dessinerGlobe(zone, banques).then(basculer => {
    commandes.textContent = reduit() ? "Rotation désactivée (préférence « moins d'animations »). Glisser pour tourner le globe." : "Glisser pour tourner le globe. ";
    if (!reduit()) {
      const b = el("button", "bouton-texte", "Arrêter la rotation"); b.type = "button";
      b.addEventListener("click", () => { b.textContent = basculer() ? "Arrêter la rotation" : "Reprendre la rotation"; });
      commandes.appendChild(b);
    }
  }).catch(e => {
    console.warn("Globe indisponible", e);
    zone.replaceChildren(el("p", "indisponible", "Globe indisponible (bibliothèque ou carte non chargée) : la liste des 9 banques ci-dessous reste complète."));
  });
  return [c, majHor];
}

/* ------------------------------------------------------------------ une ligne d'évènement */
function barreReaction(e) {
  const box = el("div", "ag-reaction");
  if (!e.reaction) {
    box.appendChild(el("span", "note", e.raison_reaction ? "Réaction passée : n/d" : ""));
    if (e.raison_reaction) box.title = e.raison_reaction;
    return box;
  }
  const r = e.reaction;
  for (const [cle, libelle] of [["au_dessus", "Au-dessus"], ["au_dessous", "Au-dessous"]]) {
    const s = r.cote?.[cle] || {};
    const l = el("div", "ag-r-ligne");
    l.appendChild(el("span", "ag-r-lib", libelle));
    const piste = el("span", "ag-r-piste");
    const m = s.mediane;
    if (m != null) {
      const i = el("i", m >= 0 ? "pos" : "neg");
      i.style.width = `${Math.min(Math.abs(m) / 0.6 * 50, 50)}%`;
      if (m >= 0) i.style.left = "50%"; else i.style.right = "50%";
      piste.appendChild(i);
    }
    l.appendChild(piste);
    l.appendChild(el("span", "ag-r-val tabulaire", m == null ? "n/d" : `${m > 0 ? "+" : ""}${virgule(m.toFixed(2))} %`));
    l.appendChild(el("span", `ag-r-n${s.faible ? " faible" : ""}`, s.n ? `${s.n} cas${s.faible ? " · indice faible" : ""}` : "0 cas"));
    l.title = `${libelle} : médiane ${m == null ? "n/d" : m.toFixed(3) + " %"}, ${s.n || 0} cas, borne de Wilson ${s.wilson ?? "n/d"} %`;
    box.appendChild(l);
  }
  const lien = el("a", "ag-r-lien", "Simulateur"); lien.href = r.lien || "#scenarios";
  lien.title = `${r.mesure} · ${r.lecture} · ${r.source}`;
  box.appendChild(lien);
  return box;
}

function ligneEvenement(e) {
  const li = el("li", `ag-evt impact-${e.impact} type-${CLASSE_TYPE[e.type] || "chiffre"}`);
  li.dataset.type = CLASSE_TYPE[e.type] || "chiffre";
  li.dataset.devise = e.devise;
  li.dataset.impact = e.impact;
  const heure = el("span", "ag-heure tabulaire", e.heure_paris === "journée" ? "—" : e.heure_paris);
  if (e.heure_paris === "journée") heure.title = e.raison_heure || "heure non communiquée";
  const dev = el("span", "ag-dev", `${DRAPEAUX[e.devise] || ""} ${e.devise}`);
  const corps = el("div", "ag-corps");
  const t = el("div", "ag-titre");
  t.append(el("span", `ag-type ${CLASSE_TYPE[e.type] || "chiffre"}`, e.type), el("b", null, e.evenement),
           el("span", `ag-points ${e.impact}`, e.points || ""));
  t.lastChild.setAttribute("aria-label", `impact ${e.impact}`);
  if (e.badge && e.badge.sens) {
    const b = el("span", `ag-badge ${e.badge.sens}`, `${e.badge.texte}${e.badge.pb ? ` (${e.badge.pb > 0 ? "+" : ""}${e.badge.pb} pb)` : ""}`);
    b.title = `Consensus ${virgule(e.consensus)} contre ${virgule(e.badge.reference)} (${e.badge.source_reference})`;
    t.appendChild(b);
  }
  if (!e.traduit) t.appendChild(el("span", "note", " (nom d'origine, non traduit)"));
  const src = el("p", "ag-source note",
    `${e.officiel ? `Date : ${e.officiel.source}${e.officiel.statut && e.officiel.statut !== "officiel" ? ` (${e.officiel.statut})` : ""} · ` : ""}`
    + `Source : ${e.source}${e.verifie_le ? ` · vérifié le ${dateCourte(e.verifie_le)}` : ""}`);
  corps.append(t, src);
  const valeurs = el("div", "ag-valeurs tabulaire");
  const v = (lib, x, raison, cls, champ) => {
    const s = el("span", cls || null, `${lib} ${virgule(x) ?? "n/d"}`);
    if (x == null && raison) s.title = raison;
    else if (x != null) certifier(s, { libelle: `${e.evenement} (${e.devise}) · ${lib}`, valeur: virgule(x),
                                       source: e.sources_champs?.[champ] || e.source, date: e.date_paris,
                                       sansAge: "valeur d'une publication ponctuelle (date de l'évènement)" });
    return s;
  };
  valeurs.append(v("Préc.", e.precedent, e.raison_precedent, null, "precedent"), v("Cons.", e.consensus, e.raison_consensus, null, "consensus"),
                 v("Réel", e.publie, "pas encore publié", e.publie ? "ag-publie" : null, "publie"));
  const cr = el("span", "ag-rebours tabulaire", rebours(e.iso_utc)); cr.dataset.iso = e.iso_utc;
  const liens = el("div", "ag-liens");
  liens.appendChild(cr);
  if (e.engrenage) { const a = el("a", null, `Engrenage ${e.engrenage}`); a.href = `#g=${e.engrenage}`; a.title = COURTS[e.engrenage]; liens.appendChild(a); }
  li.append(heure, dev, corps, valeurs, barreReaction(e), liens);
  return li;
}

/* ------------------------------------------------------------------ jours, filtres */
function blocJours(a) {
  const c = el("section", "carte ag-calendrier");
  const tete = el("div", "ag-cal-tete");
  tete.appendChild(el("h2", null, "Calendrier"));
  tete.appendChild(el("p", "sous-titre", `Du ${dateCourte(a.debut)} au ${dateCourte(a.fin)} · heures de Paris (changements d'heure inclus) · ${a.n_evenements} évènement(s), dont ${a.n_forts} à fort impact.`));
  c.appendChild(tete);
  const jours = a.jours || [];
  const onglets = el("div", "ag-onglets"); onglets.setAttribute("role", "tablist"); onglets.setAttribute("aria-label", "Jours");
  const filtres = el("div", "ag-filtres"); filtres.setAttribute("role", "group"); filtres.setAttribute("aria-label", "Filtrer par type");
  const devise = el("select", "ag-devise"); devise.setAttribute("aria-label", "Filtrer par devise");
  devise.appendChild(new Option("Toutes les devises", ""));
  for (const d of ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]) devise.appendChild(new Option(`${DRAPEAUX[d] || ""} ${d}`, d));
  let filtre = "tout";
  const boutonsFiltre = FILTRES.map(([cle, lib]) => {
    const b = el("button", "ag-filtre", lib); b.type = "button"; b.setAttribute("aria-pressed", cle === filtre);
    b.addEventListener("click", () => { filtre = cle; boutonsFiltre.forEach(x => x.setAttribute("aria-pressed", x === b)); appliquer(); });
    filtres.appendChild(b); return b;
  });
  filtres.appendChild(devise);
  const panneaux = el("div", "ag-panneaux");
  const choix = jours.findIndex(j => j.date >= a.aujourdhui && j.evenements.length);
  let actif = choix >= 0 ? choix : 0;
  const boutonsJour = jours.map((j, i) => {
    const d = new Date(`${j.date}T12:00:00Z`);
    const b = el("button", "ag-onglet"); b.type = "button"; b.setAttribute("role", "tab");
    b.append(el("span", "ag-o-jour", JOUR_COURT.format(d).replace(".", "")), el("span", "ag-o-num", String(d.getUTCDate())),
             el("span", "ag-o-forts", j.n_forts ? "●".repeat(Math.min(j.n_forts, 5)) : "·"));
    b.title = `${JOUR_LONG.format(d)} : ${j.evenements.length} évènement(s), ${j.n_forts} à fort impact`;
    if (j.date === a.aujourdhui) b.classList.add("aujourdhui");
    if (j.date < a.aujourdhui) b.classList.add("passe");
    b.addEventListener("click", () => { actif = i; appliquer(); });
    onglets.appendChild(b);
    const p = el("div", "ag-panneau"); p.setAttribute("role", "tabpanel");
    p.appendChild(el("h3", null, JOUR_LONG.format(d)));
    for (const x of j.discrets || []) p.appendChild(el("p", "ag-discret note", `${x.texte} (${x.devises.join(", ")}) : sans effet de marché attendu.`));
    const ul = el("ul", "ag-liste");
    ul.append(...j.evenements.map(ligneEvenement));
    p.appendChild(ul);
    const vide = el("p", "note ag-vide", j.evenements.length ? "Aucun évènement pour ces filtres." : "Aucun évènement au calendrier collecté.");
    p.appendChild(vide);
    panneaux.appendChild(p);
    return b;
  });
  function appliquer() {
    boutonsJour.forEach((b, i) => { b.setAttribute("aria-selected", i === actif); b.tabIndex = i === actif ? 0 : -1; });
    [...panneaux.children].forEach((p, i) => {
      p.classList.toggle("inactif", i !== actif);
      let n = 0;
      p.querySelectorAll(".ag-evt").forEach(li => {
        const ok = (!devise.value || li.dataset.devise === devise.value) &&
          (filtre === "tout" || (filtre === "fort" ? li.dataset.impact === "fort" : li.dataset.type === filtre));
        li.hidden = !ok; n += ok ? 1 : 0;
      });
      p.querySelector(".ag-vide").hidden = n > 0;
    });
  }
  onglets.addEventListener("keydown", e => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    actif = (actif + (e.key === "ArrowRight" ? 1 : boutonsJour.length - 1)) % boutonsJour.length;
    appliquer(); boutonsJour[actif].focus();
  });
  devise.addEventListener("change", appliquer);
  appliquer();
  c.append(onglets, filtres, panneaux);
  c.appendChild(el("p", "note", `${a.consensus?.attribution || "Consensus : ForexFactory"}${a.consensus?.etat === "n/d" ? ` — n/d : ${a.consensus.raison}` : ""}. Réaction passée : médiane de la séance suivante après une publication au-dessus ou au-dessous (nombre de cas ; « indice faible » sous 20 cas). ${a.note}`));
  return c;
}

function blocParoles(a) {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Prises de parole à suivre"));
  const liste = (a.prises_de_parole || []).filter(e => e.iso_utc >= new Date(Date.now() - 864e5).toISOString());
  if (!liste.length) { c.appendChild(el("p", "note", "Aucun discours ni conférence de presse au calendrier collecté pour les jours à venir.")); return c; }
  const ul = el("ul", "ag-simple");
  for (const e of liste) {
    const li = el("li");
    li.append(el("span", "tabulaire ag-s-date", `${dateCourte(e.date_paris).slice(0, 5)} ${e.heure_paris === "journée" ? "" : e.heure_paris}`),
              el("span", null, `${DRAPEAUX[e.devise] || ""} ${e.evenement}`), el("span", `ag-points ${e.impact}`, e.points));
    ul.appendChild(li);
  }
  c.appendChild(ul);
  c.appendChild(el("p", "note", "Source : calendrier ForexFactory (discours annoncés). Les dates des réunions viennent des calendriers officiels."));
  return c;
}

function blocGrands(a) {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Grands rendez-vous à venir"));
  const ul = el("ul", "ag-simple");
  for (const g of a.grands_rendez_vous || []) {
    const li = el("li");
    li.append(el("span", "tabulaire ag-s-date", `${dateCourte(g.date).slice(0, 5)}${g.fin ? `–${dateCourte(g.fin).slice(0, 5)}` : ""}`),
              el("span", null, `${g.titre} (${(g.devises || []).join(", ")})`));
    const s = el("span", `ag-statut ${g.statut}`, g.statut === "officiel" ? "officiel" : "source secondaire");
    s.title = `${g.source} · vérifié le ${dateCourte(g.verifie_le)}`;
    li.appendChild(s);
    ul.appendChild(li);
  }
  c.appendChild(ul);
  if (a.grands_rendez_vous_absents) c.appendChild(el("p", "note", a.grands_rendez_vous_absents));
  return c;
}

export async function pageAgenda() {
  const a = await chargerJson("data/agenda.json");
  if (enErreur(a)) return [indisponible("Agenda", a?.__erreur || "agenda.json absent (prochain run)")];
  const tete = el("section", "carte ag-tete");
  tete.appendChild(el("p", "surtitre", `Agenda macro · ${dateCourte(a.debut).slice(0, 5)} au ${dateCourte(a.fin)}`));
  tete.appendChild(el("h2", "ag-h1", "Ce qui peut bouger les marchés"));
  tete.appendChild(el("p", "sous-titre", `Généré ${dateHeure(a.genere_le)} · dates des réunions : calendriers officiels des 9 banques centrales · ${a.consensus?.attribution || ""}`));
  if (a.raison_vide) tete.appendChild(el("p", "indisponible", `Indisponible : ${a.raison_vide}.`));
  const [globe, majHorloges] = blocGlobe(a);
  const cal = blocJours(a);
  const bas = el("div", "ag-bas");
  bas.append(blocParoles(a), blocGrands(a));
  const minuterie = setInterval(() => {
    if (!document.body.contains(cal)) { clearInterval(minuterie); return; }
    cal.querySelectorAll(".ag-rebours").forEach(s => { s.textContent = rebours(s.dataset.iso); });
    majHorloges();
  }, 30000);
  return [tete, globe, cal, bas];
}
