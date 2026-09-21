/* Dashboard FX — rendu 100 % client à partir de docs/data/*.json.
   Aucun backend : GitHub Pages sert les fichiers, ce script les dessine.
   Navigation par vue calendrier (grille mensuelle, semaines ISO visibles). */
"use strict";

const BIAIS = {
  on:     { libelle: "RISK ON",  couleur: "#22c55e" },
  off:    { libelle: "RISK OFF", couleur: "#ef4444" },
  neutre: { libelle: "NEUTRE",   couleur: "#eab308" },
};
const BIAIS_GLOBAL = { risk_on: "on", risk_off: "off", neutre: "neutre" };
const DRAPEAUX = { USD: "🇺🇸", EUR: "🇪🇺", GBP: "🇬🇧", JPY: "🇯🇵",
                   CHF: "🇨🇭", CAD: "🇨🇦", AUD: "🇦🇺", NZD: "🇳🇿", CNY: "🇨🇳" };
const RUBRIQUES_ETAT = [
  ["situation_economique", "Économie"],
  ["politique_monetaire_budgetaire", "Politique monétaire & budgétaire"],
  ["geopolitique", "Géopolitique"],
];
const GRILLE = "#1c2330";
const ENCRE_2 = "#8b95a5";

const graphiquesActifs = [];
let INDEX = [];            // [{date, type, biais, relecture}]
let dateCourante = null;   // "YYYY-MM-DD" du rapport affiché
let moisAffiche = null;    // Date, 1er jour du mois montré par le calendrier

/* ------------------------------------------------------------ utilitaires */
function el(tag, classe, texte) {
  const noeud = document.createElement(tag);
  if (classe) noeud.className = classe;
  if (texte !== undefined) noeud.textContent = texte;
  return noeud;
}
const texteOuTiret = (v) => (v === null || v === undefined || v === "" ? "—" : String(v));

function detruireGraphiques() {
  while (graphiquesActifs.length) graphiquesActifs.pop().destroy();
}

async function chargerJson(chemin) {
  const rep = await fetch(chemin, { cache: "no-store" });
  if (!rep.ok) throw new Error(`${chemin} : HTTP ${rep.status}`);
  return rep.json();
}

/* -------------------------------------------------------------- calendrier */
function numeroSemaineISO(d) {
  const copie = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const jour = copie.getUTCDay() || 7;
  copie.setUTCDate(copie.getUTCDate() + 4 - jour);
  const debutAnnee = new Date(Date.UTC(copie.getUTCFullYear(), 0, 1));
  return Math.ceil(((copie - debutAnnee) / 86400000 + 1) / 7);
}
const cleDate = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function dessinerCalendrier() {
  const panneau = document.getElementById("panneau-calendrier");
  panneau.innerHTML = "";
  if (!moisAffiche) {
    moisAffiche = dateCourante ? new Date(dateCourante + "T12:00:00") : new Date();
  }
  moisAffiche = new Date(moisAffiche.getFullYear(), moisAffiche.getMonth(), 1);
  const finMois = new Date(moisAffiche.getFullYear(), moisAffiche.getMonth() + 1, 0);

  const entete = el("div", "cal-entete");
  const precedent = el("button", "cal-nav", "‹");
  precedent.addEventListener("click", (e) => {
    e.stopPropagation();
    moisAffiche = new Date(moisAffiche.getFullYear(), moisAffiche.getMonth() - 1, 1);
    dessinerCalendrier();
  });
  const suivant = el("button", "cal-nav", "›");
  suivant.addEventListener("click", (e) => {
    e.stopPropagation();
    moisAffiche = new Date(moisAffiche.getFullYear(), moisAffiche.getMonth() + 1, 1);
    dessinerCalendrier();
  });
  const libelle = new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric" })
    .format(moisAffiche);
  entete.append(precedent, el("span", "cal-mois", libelle), suivant);
  panneau.appendChild(entete);

  const grille = el("div", "cal-grille");
  for (const titre of ["Sem.", "L", "M", "M", "J", "V", "S", "D"]) {
    grille.appendChild(el("div", "cal-jour-entete", titre));
  }

  const parDate = new Map(INDEX.map((e) => [e.date, e]));
  const curseur = new Date(moisAffiche);
  curseur.setDate(1 - ((moisAffiche.getDay() + 6) % 7)); // recule au lundi

  for (let ligne = 0; ligne < 6; ligne++) {
    if (ligne > 0 && curseur > finMois) break;
    grille.appendChild(el("div", "cal-semaine",
      "W" + String(numeroSemaineISO(curseur)).padStart(2, "0")));
    for (let j = 0; j < 7; j++) {
      const cle = cleDate(curseur);
      const entree = parDate.get(cle);
      let classe = "cal-jour";
      if (curseur.getMonth() !== moisAffiche.getMonth()) classe += " cal-hors-mois";
      if (cle === dateCourante) classe += " cal-actif";
      const cellule = el(entree ? "button" : "div", classe, String(curseur.getDate()));
      if (entree) {
        const pastille = el("span", "cal-pastille");
        pastille.style.background = BIAIS[BIAIS_GLOBAL[entree.biais] || "neutre"].couleur;
        cellule.appendChild(pastille);
        cellule.title = `${entree.date} · ${entree.type || "rapport"} · ${entree.biais || ""}`;
        cellule.addEventListener("click", () => {
          fermerCalendrier();
          chargerRapport(`data/${entree.date}.json`);
        });
      }
      grille.appendChild(cellule);
      curseur.setDate(curseur.getDate() + 1);
    }
  }
  panneau.appendChild(grille);
}

function fermerCalendrier() {
  document.getElementById("panneau-calendrier").hidden = true;
  document.getElementById("btn-calendrier").setAttribute("aria-expanded", "false");
}

/* ------------------------------------------------------------- chargement */
async function initialiser() {
  try {
    const brut = await chargerJson("data/index.json");
    INDEX = (brut || [])
      .map((e) => (typeof e === "string" ? { date: e } : e))
      .filter((e) => e && e.date);
  } catch { /* premier run : pas encore d'index */ }

  const bouton = document.getElementById("btn-calendrier");
  bouton.addEventListener("click", (e) => {
    e.stopPropagation();
    const panneau = document.getElementById("panneau-calendrier");
    panneau.hidden = !panneau.hidden;
    bouton.setAttribute("aria-expanded", String(!panneau.hidden));
    if (!panneau.hidden) dessinerCalendrier();
  });
  document.addEventListener("click", (e) => {
    if (!document.querySelector(".calendrier-conteneur").contains(e.target)) fermerCalendrier();
  });

  await chargerRapport("data/latest.json");
}

async function chargerRapport(chemin) {
  const contenu = document.getElementById("contenu");
  try {
    const rapport = await chargerJson(chemin);
    dateCourante = rapport.meta.date_rapport;
    moisAffiche = new Date(dateCourante + "T12:00:00");
    document.getElementById("btn-calendrier").textContent = `📅 ${dateCourante}`;
    rendre(rapport);
  } catch (erreur) {
    contenu.innerHTML = "";
    contenu.appendChild(el("p", "erreur-chargement",
      "Aucun rapport disponible pour le moment (" + erreur.message + "). " +
      "Le premier rapport apparaîtra après la première exécution du pipeline."));
  }
}

/* ------------------------------------------------------------------ rendu */
function rendre(rapport) {
  detruireGraphiques();
  const contenu = document.getElementById("contenu");
  contenu.innerHTML = "";

  document.getElementById("badge-type").textContent = rapport.meta.type_rapport;
  document.getElementById("pied-meta").textContent =
    `généré le ${rapport.meta.genere_le} · modèle ${rapport.meta.modele_llm} · schéma v${rapport.meta.version_schema}`;

  const critique = rapport.critique || {};
  if (critique.validation === "a_revoir") {
    const points = [...(critique.incoherences || []), ...(critique.affirmations_non_sourcees || [])];
    const bandeau = el("div", "bandeau bandeau-vigilance");
    bandeau.appendChild(el("strong", null, "⚠️ Point de vigilance identifié par la relecture : "));
    bandeau.appendChild(document.createTextNode(points.slice(0, 4).join(" · ") || "voir le rapport JSON"));
    contenu.appendChild(bandeau);
  } else if (critique.validation === "non_evalue") {
    // Distinct de "a_revoir" : on ne sait PAS si le rapport est propre, la
    // relecture elle-même n'a pas pu avoir lieu — jamais affiché comme "ok".
    const bandeau = el("div", "bandeau bandeau-donnees");
    bandeau.appendChild(el("strong", null, "🔍 Relecture non effectuée aujourd'hui — "));
    bandeau.appendChild(document.createTextNode(
      (critique.note || "cause inconnue") + ". Ce rapport n'a PAS été validé par l'agent critique."));
    contenu.appendChild(bandeau);
  }
  const controle = rapport.controle_qualite || {};
  if (controle.conforme === false) {
    const bandeau = el("div", "bandeau bandeau-vigilance");
    bandeau.appendChild(el("strong", null,
      `🧪 Contrôle qualité : ${controle.nb_anomalies ?? "?"} anomalie(s) — `));
    bandeau.appendChild(document.createTextNode((controle.anomalies || []).slice(0, 4).join(" · ")));
    contenu.appendChild(bandeau);
  }
  if ((rapport.donnees_non_rafraichies || []).length) {
    const bandeau = el("div", "bandeau bandeau-donnees");
    bandeau.appendChild(el("strong", null, "🕐 Données non rafraîchies aujourd'hui : "));
    bandeau.appendChild(document.createTextNode(
      rapport.donnees_non_rafraichies.map(d => `${d.source} (${(d.raison || "").slice(0, 70)})`).join(" · ")));
    contenu.appendChild(bandeau);
  }

  if ((rapport.devises || []).length) contenu.appendChild(mosaiqueDevises(rapport));
  contenu.appendChild(carteSynthese(rapport));
  if (rapport.auto_evaluation) contenu.appendChild(carteEvaluation(rapport.auto_evaluation));

  const sources = new Map((rapport.sources_citees || []).map(s => [s.id, s]));
  for (const devise of rapport.devises || []) {
    contenu.appendChild(carteDevise(devise, rapport, sources));
  }

  const suggestions = critique.suggestions_connaissances || [];
  if (suggestions.length) contenu.appendChild(carteSuggestions(suggestions));
  contenu.appendChild(sectionNotes(rapport.meta.date_rapport));
}

/* --------------------------------------------------------------- mosaïque */
function sparklineSVG(points, couleur) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "tuile-sparkline");
  svg.setAttribute("viewBox", "0 0 100 26");
  svg.setAttribute("preserveAspectRatio", "none");
  const scores = (points || []).map(p => p.score);
  if (scores.length < 2) return svg;
  const min = Math.min(...scores), max = Math.max(...scores), etendue = (max - min) || 1;
  const coords = scores.map((s, i) => {
    const x = (i / (scores.length - 1)) * 100;
    const y = 24 - ((s - min) / etendue) * 22;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const ligne = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  ligne.setAttribute("points", coords);
  ligne.setAttribute("fill", "none");
  ligne.setAttribute("stroke", couleur);
  ligne.setAttribute("stroke-width", "2");
  ligne.setAttribute("stroke-linecap", "round");
  ligne.setAttribute("stroke-linejoin", "round");
  svg.appendChild(ligne);
  return svg;
}

function mosaiqueDevises(rapport) {
  const section = el("section", "mosaique-devises");
  section.appendChild(el("div", "titre-section", "Vue d'ensemble — 9 devises"));
  const grille = el("div", "mosaique-grille");
  for (const devise of rapport.devises || []) {
    const indisponible = devise.score_confluence === null || devise.score_confluence === undefined;
    const biais = BIAIS[devise.risk_on_off] || BIAIS.neutre;
    const tuile = el("button", "tuile-devise" + (indisponible ? " tuile-indisponible" : ""));
    tuile.type = "button";
    tuile.style.setProperty("--couleur-biais", biais.couleur);
    tuile.appendChild(el("span", "tuile-drapeau", DRAPEAUX[devise.devise] || ""));
    tuile.appendChild(el("span", "tuile-code", devise.devise));
    if (indisponible) {
      tuile.appendChild(el("span", "tuile-statut", "⏸ indispo."));
    } else {
      tuile.appendChild(el("span", "tuile-score", String(devise.score_confluence)));
      tuile.appendChild(sparklineSVG(devise.historique_score_7j, biais.couleur));
    }
    tuile.title = indisponible
      ? `${devise.devise} — analyse indisponible aujourd'hui`
      : `${devise.devise} — ${biais.libelle} — confluence ${devise.score_confluence} %`;
    tuile.addEventListener("click", () => {
      const cible = document.getElementById(`devise-${devise.devise}`);
      if (cible) { cible.open = true; cible.scrollIntoView({ behavior: "smooth", block: "start" }); }
    });
    grille.appendChild(tuile);
  }
  section.appendChild(grille);
  return section;
}

/* --------------------------------------------------------------- synthèse */
function carteSynthese(rapport) {
  const synthese = rapport.synthese_globale;
  const cle = BIAIS_GLOBAL[synthese.biais_macro_global] || "neutre";
  const carte = el("section", "carte-synthese");
  carte.appendChild(el("h2", null, "Synthèse globale"));

  const ligne = el("div", "ligne-biais");
  const puce = el("span", "puce-biais", BIAIS[cle].libelle);
  puce.style.background = BIAIS[cle].couleur;
  ligne.appendChild(puce);
  ligne.appendChild(el("span", "commentaire-global", synthese.commentaire || ""));
  carte.appendChild(ligne);

  const etat = synthese.etat_du_monde || {};
  const briefingPresent = (etat.indicateurs_du_jour || []).length ||
    (etat.actualite || []).length || etat.conclusion;
  if (RUBRIQUES_ETAT.some(([k]) => (etat[k] || {}).texte) || briefingPresent) {
    const bloc = el("div", "etat-du-monde");
    bloc.appendChild(el("div", "titre-section", "🌍 État du monde"));
    for (const [k, libelle] of RUBRIQUES_ETAT) {
      const rubrique = etat[k] || {};
      if (!rubrique.texte) continue;
      const p = el("p", "rubrique-etat");
      p.appendChild(el("b", null, `${libelle} — `));
      p.appendChild(document.createTextNode(rubrique.texte + " "));
      p.appendChild(el("span", rubrique.non_source ? "tag-non-source" : "ref-source",
        rubrique.non_source ? "[non sourcé]" : `(${(rubrique.source_ids || []).join(", ")})`));
      bloc.appendChild(p);
    }

    // Briefing d'analyste : indicateurs ✅/❌, actualité, conclusion.
    const puceBriefing = (item, prefixe) => {
      const li = el("li", "puce-briefing");
      if (prefixe) li.appendChild(el("b", null, prefixe + " "));
      li.appendChild(document.createTextNode((item.texte || "") + " "));
      li.appendChild(el("span", item.non_sourcee ? "tag-non-source" : "ref-source",
        item.non_sourcee ? "[non sourcé]" : `(${item.source_id || ""})`));
      return li;
    };
    if ((etat.indicateurs_du_jour || []).length) {
      bloc.appendChild(el("div", "titre-section", "Indicateurs du jour"));
      const liste = el("ul", "liste-briefing");
      for (const item of etat.indicateurs_du_jour) liste.appendChild(puceBriefing(item, item.symbole || "➖"));
      bloc.appendChild(liste);
    }
    if ((etat.actualite || []).length) {
      bloc.appendChild(el("div", "titre-section", "Actualité"));
      const liste = el("ul", "liste-briefing");
      for (const item of etat.actualite) liste.appendChild(puceBriefing(item));
      bloc.appendChild(liste);
    }
    if (etat.conclusion) {
      bloc.appendChild(el("div", "titre-section", "Conclusion"));
      bloc.appendChild(el("p", "conclusion-briefing", etat.conclusion));
    }
    carte.appendChild(bloc);
  }

  const table = el("table", "classement");
  table.innerHTML = "<thead><tr><th>#</th><th>Devise</th><th>Biais</th><th>Confluence</th><th></th></tr></thead>";
  const corps = el("tbody");
  for (const c of synthese.classement_devises || []) {
    const rang = el("tr");
    rang.appendChild(el("td", null, String(c.rang)));
    rang.appendChild(el("td", null, `${DRAPEAUX[c.devise] || ""} ${c.devise}`));
    const cellule = el("td");
    const biais = BIAIS[c.risk_on_off] || BIAIS.neutre;
    const badge = el("span", "badge-biais", biais.libelle);
    badge.style.background = biais.couleur;
    cellule.appendChild(badge);
    rang.appendChild(cellule);
    rang.appendChild(el("td", null, `${c.score_confluence} %`));
    const celluleBarre = el("td");
    const barre = el("span", "barre-score");
    barre.style.width = `${c.score_confluence}px`;
    barre.style.background = biais.couleur;
    celluleBarre.appendChild(barre);
    rang.appendChild(celluleBarre);
    rang.addEventListener("click", () => {
      const cible = document.getElementById(`devise-${c.devise}`);
      if (cible) { cible.open = true; cible.scrollIntoView({ behavior: "smooth" }); }
    });
    corps.appendChild(rang);
  }
  table.appendChild(corps);
  carte.appendChild(table);
  if ((synthese.devises_indisponibles || []).length) {
    carte.appendChild(el("p", "ref-source",
      "⏸ Analyses indisponibles aujourd'hui (exclues du classement) : " +
      synthese.devises_indisponibles.join(", ")));
  }
  return carte;
}

/* -------------------------------------------------------- auto-évaluation */
function carteEvaluation(evaluation) {
  const carte = el("section", "carte-synthese carte-eval");
  carte.appendChild(el("h2", null,
    `Auto-évaluation — semaine du ${evaluation.periode?.du || "?"} au ${evaluation.periode?.au || "?"}`));
  const ligne = el("div", "ligne-biais");
  ligne.appendChild(el("span", "chiffre-eval", `${evaluation.taux_reussite_biais_pct} %`));
  ligne.appendChild(el("span", "commentaire-global",
    `de biais corrects · corrélation de classement (Spearman) : ${texteOuTiret(evaluation.correlation_classement_spearman)}`));
  carte.appendChild(ligne);
  if (evaluation.commentaire_llm) carte.appendChild(el("p", "commentaire-global", evaluation.commentaire_llm));

  const table = el("table", "donnees");
  table.innerHTML = "<thead><tr><th>Devise</th><th>Prévu</th><th>Variation réelle</th><th>Correct</th></tr></thead>";
  const corps = el("tbody");
  for (const e of evaluation.par_devise || []) {
    const rang = el("tr");
    rang.appendChild(el("td", null, e.devise));
    rang.appendChild(el("td", null, e.prevu));
    rang.appendChild(el("td", null, `${e.variation_reelle_pct} %`));
    rang.appendChild(el("td", null, e.correct ? "✔" : "✘"));
    corps.appendChild(rang);
  }
  table.appendChild(corps);
  carte.appendChild(table);
  return carte;
}

/* ----------------------------------------------------------- carte devise */
function carteDevise(devise, rapport, sources) {
  const indisponible = devise.score_confluence === null || devise.score_confluence === undefined;
  const biais = BIAIS[devise.risk_on_off] || BIAIS.neutre;
  const carte = el("details", "carte-devise");
  carte.id = `devise-${devise.devise}`;

  const resume = el("summary");
  resume.appendChild(el("span", "chevron", "▶"));
  resume.appendChild(el("span", "drapeau", DRAPEAUX[devise.devise] || ""));
  resume.appendChild(el("span", "code-devise", devise.devise));
  if (indisponible) {
    resume.appendChild(el("span", "ref-source", "⏸ analyse indisponible aujourd'hui"));
  } else {
    const badge = el("span", "badge-biais", biais.libelle);
    badge.style.background = biais.couleur;
    resume.appendChild(badge);
    const score = el("span", "score-resume");
    score.appendChild(el("span", null, `confluence ${devise.score_confluence} %`));
    const barre = el("span", "barre-score");
    barre.style.width = `${devise.score_confluence * 0.8}px`;
    barre.style.background = biais.couleur;
    score.appendChild(barre);
    resume.appendChild(score);
  }
  carte.appendChild(resume);

  const corps = el("div", "corps-devise");

  let canevasJauge = null;
  if (indisponible) {
    const bandeau = el("div", "bandeau bandeau-donnees");
    bandeau.appendChild(el("strong", null, "⏸ Analyse indisponible aujourd'hui — "));
    bandeau.appendChild(document.createTextNode(
      (devise.raison_indisponibilite || "voir le log") +
      ". Les données collectées ci-dessous restent valables ; devise exclue du classement du jour."));
    corps.appendChild(bandeau);
  } else {
    const haut = el("div", "rangee-haut");
    const blocJauge = el("div", "bloc-jauge");
    canevasJauge = el("canvas");
    blocJauge.appendChild(canevasJauge);
    const centre = el("div", "jauge-centre");
    const valeur = el("div", "jauge-valeur", `${devise.score_confluence}`);
    valeur.style.color = biais.couleur;
    centre.appendChild(valeur);
    centre.appendChild(el("div", "jauge-libelle", "confluence / 100"));
    blocJauge.appendChild(centre);
    haut.appendChild(blocJauge);

    const callout = el("div", "callout", devise.synthese_une_phrase || "");
    callout.style.borderColor = biais.couleur;
    haut.appendChild(callout);
    corps.appendChild(haut);
  }

  const tendance = devise.tendance_fond || {};
  const carry = devise.carry || {};
  const meta = el("p", "meta-devise");
  meta.innerHTML =
    `<b>Tendance weekly (Dow)</b> : ${texteOuTiret(tendance.sens)} — ${texteOuTiret(tendance.commentaire)}` +
    ` &nbsp;·&nbsp; <b>Banque centrale</b> : ${texteOuTiret(devise.biais_banque_centrale)}` +
    ` &nbsp;·&nbsp; <b>Taux</b> : ${texteOuTiret(carry.taux_directeur)} %` +
    ` (diff. médiane G8 : ${texteOuTiret(carry.differentiel_vs_mediane_g8)})`;
  corps.appendChild(meta);

  // Contexte géopolitique & décisions — distinct de l'état du monde global
  // et du tableau d'indicateurs : posture banque centrale expliquée +
  // événements datés propres à la devise.
  const contexteGeo = devise.contexte_geopolitique || {};
  const pourquoi = contexteGeo.banque_centrale_pourquoi || {};
  const evenementsGeo = contexteGeo.evenements || [];
  if (pourquoi.texte || evenementsGeo.length) {
    const bloc = el("div", "contexte-geo");
    bloc.appendChild(el("div", "titre-section", "🌐 Contexte géopolitique & décisions"));
    if (pourquoi.texte) {
      const p = el("p", "rubrique-etat", pourquoi.texte + " ");
      if (pourquoi.source_id) p.appendChild(el("span", "ref-source", `(${pourquoi.source_id})`));
      bloc.appendChild(p);
    }
    if (evenementsGeo.length) {
      const toggle = el("details", "sous-toggle");
      toggle.appendChild(el("summary", null, "Événements de la semaine"));
      const liste = el("ul");
      for (const item of evenementsGeo) {
        const puce = el("li", null, item.texte + " ");
        const source = sources.get(item.source_id);
        puce.appendChild(el("span", item.non_sourcee ? "tag-non-source" : "ref-source",
          item.non_sourcee ? "[⚠ affirmation non sourcée]"
            : source ? `— ${source.source} · ${(source.detail || "").slice(0, 60)} · ${source.date || "s.d."}`
                     : `— ${item.source_id || "?"}`));
        liste.appendChild(puce);
      }
      toggle.appendChild(liste);
      bloc.appendChild(toggle);
    }
    corps.appendChild(bloc);
  }

  // Tableau : une ligne par indicateur configuré, date d'origine + J-n visible.
  const sectionIndicateurs = el("div");
  sectionIndicateurs.appendChild(el("div", "titre-section", "Indicateurs du jour"));
  const lignes = devise.indicateurs_tableau || [];
  if (lignes.length) {
    const enveloppe = el("div", "enveloppe-table");
    const table = el("table", "donnees");
    table.innerHTML =
      "<thead><tr><th>Indicateur</th><th>Valeur</th><th>Prévision</th><th>Précédent</th><th>Source</th><th>Date</th></tr></thead>";
    const corpsTable = el("tbody");
    for (const i of lignes) {
      const rang = el("tr");
      rang.appendChild(el("td", null, texteOuTiret(i.nom)));
      rang.appendChild(el("td", null,
        i.valeur === null || i.valeur === undefined || i.valeur === ""
          ? (i.note || "—") : String(i.valeur)));
      rang.appendChild(el("td", null, texteOuTiret(i.prevision)));
      rang.appendChild(el("td", null, texteOuTiret(i.precedent)));
      rang.appendChild(el("td", null, texteOuTiret(i.source)));
      const celluleDate = el("td", null, i.date
        ? i.date + (i.anciennete_jours ? ` (J-${i.anciennete_jours})` : "")
        : "—");
      if (i.anciennete_jours) celluleDate.classList.add("date-ancienne");
      rang.appendChild(celluleDate);
      corpsTable.appendChild(rang);
    }
    table.appendChild(corpsTable);
    enveloppe.appendChild(table);
    sectionIndicateurs.appendChild(enveloppe);
  } else {
    sectionIndicateurs.appendChild(el("p", "meta-devise", "Tableau indisponible (voir contrôle qualité)."));
  }
  corps.appendChild(sectionIndicateurs);

  // DXY et Pétrole : indicateurs visuels rattachés aux lignes correspondantes
  // du tableau. DXY réutilise la donnée USD déjà chargée (même série, aucune
  // nouvelle collecte) ; Pétrole vient de rapport.graphiques_marche (FRED —
  // Twelve Data réserve les commodités au tier payant, vérifié).
  const indicateursPresents = new Set(lignes.map(l => l.indicateur));
  let canevasDxy = null;
  if (indicateursPresents.has("dxy") && devise.devise !== "USD" && (rapport.graphiques || {}).USD) {
    const bloc = el("div", "bloc-graphique bloc-graphique-marche");
    bloc.appendChild(el("div", "titre-section", "DXY (indice USD synthétique) — indicateur partagé"));
    canevasDxy = el("canvas");
    bloc.appendChild(canevasDxy);
    corps.appendChild(bloc);
  }
  let canevasPetrole = null;
  const marche = rapport.graphiques_marche || {};
  if (devise.devise === "CAD" && (marche.wti || marche.brent)) {
    const bloc = el("div", "bloc-graphique bloc-graphique-marche");
    bloc.appendChild(el("div", "titre-section", "Pétrole WTI / Brent (FRED) — indicateur partagé"));
    canevasPetrole = el("canvas");
    bloc.appendChild(canevasPetrole);
    corps.appendChild(bloc);
  }

  corps.appendChild(listeSourcee("🟢 Opportunités", devise.opportunites, sources));
  corps.appendChild(listeSourcee("🔴 Menaces", devise.menaces, sources));
  corps.appendChild(detailScore(devise.detail_score));

  const weekly = (rapport.analyse_weekly || {})[devise.devise];
  if (weekly) corps.appendChild(blocWeekly(weekly));

  const graphique = (rapport.graphiques || {})[devise.devise];
  let canevasPrix = null;
  if (graphique) {
    const bloc = el("div", "bloc-graphique");
    bloc.appendChild(el("div", "titre-section", graphique.libelle));
    canevasPrix = el("canvas");
    bloc.appendChild(canevasPrix);
    corps.appendChild(bloc);
    if (devise.devise === "USD") {
      bloc.appendChild(el("p", "ref-source",
        "Sert aussi de référence DXY (baromètre Risk On/Off) — voir la ligne « Indice USD » du tableau ci-dessus."));
    }
  }

  corps.appendChild(el("p", "pied-carte",
    "Sources : Twelve Data, FRED, ForexFactory, RSS, sites news · " +
    `généré le ${rapport.meta.genere_le} · aide à la décision — aucun signal d'achat/vente.`));
  carte.appendChild(corps);

  let dessine = false;
  carte.addEventListener("toggle", () => {
    if (!carte.open || dessine) return;
    dessine = true;
    if (canevasJauge) dessinerJauge(canevasJauge, devise.score_confluence, biais.couleur);
    if (canevasPrix) dessinerPrix(canevasPrix, graphique, biais.couleur);
    if (canevasDxy) {
      const g = rapport.graphiques.USD;
      dessinerSerieMarche(canevasDxy, [{ label: "DXY", data: g.clotures, couleur: "#38bdf8" }],
        g.dates.map(d => d.slice(5)));
    }
    if (canevasPetrole) {
      const datasets = [];
      if (marche.wti) datasets.push({ label: "WTI", data: marche.wti.valeurs, couleur: "#eab308" });
      if (marche.brent) datasets.push({ label: "Brent", data: marche.brent.valeurs, couleur: "#38bdf8" });
      const source = marche.wti || marche.brent;
      dessinerSerieMarche(canevasPetrole, datasets, source.dates.map(d => d.slice(5)));
    }
  });
  return carte;
}

function blocWeekly(analyse) {
  const toggle = el("details", "sous-toggle");
  toggle.appendChild(el("summary", null, `📅 Analyse weekly (${analyse.semaine_iso || ""})`));
  const m = analyse.metriques || {};
  const contenu = el("div", "contenu-weekly");
  contenu.appendChild(el("p", "meta-devise",
    `Score ${texteOuTiret(m.score_debut)} → ${texteOuTiret(m.score_fin)} sur ${m.nb_jours || 0} jour(s) · ` +
    `σ ${texteOuTiret(m.ecart_type_score)} · cohérence directionnelle ${texteOuTiret(m.coherence_directionnelle_pct)} %`));
  const instables = Object.entries(m.indicateurs_instables || {});
  if (instables.length) {
    contenu.appendChild(el("p", "meta-devise",
      "Indicateurs instables : " + instables.map(([i, n]) => `${i} (${n} flip)`).join(", ")));
  }
  if (analyse.commentaire) contenu.appendChild(el("p", "rubrique-etat", analyse.commentaire));
  toggle.appendChild(contenu);
  return toggle;
}

function carteSuggestions(suggestions) {
  const carte = el("section", "carte-synthese carte-suggestions");
  carte.appendChild(el("h2", null, "💡 Suggestions pour la base de connaissances"));
  carte.appendChild(el("p", "ref-source",
    "Propositions du relecteur — à valider et écrire à la main dans connaissances/, jamais appliquées automatiquement."));
  const liste = el("ul", "liste-suggestions");
  for (const s of suggestions) {
    const item = el("li");
    item.appendChild(el("b", null, `[${s.fichier_cible || "cas_particuliers.md"}] `));
    item.appendChild(document.createTextNode(`${s.theme || ""} — ${s.suggestion || ""}`));
    liste.appendChild(item);
  }
  carte.appendChild(liste);
  return carte;
}

function sectionNotes(dateRapport) {
  const carte = el("section", "carte-synthese carte-notes");
  carte.appendChild(el("h2", null, "📝 Notes personnelles"));
  carte.appendChild(el("p", "ref-source",
    "Stockées localement dans ce navigateur (localStorage), jamais écrasées par le pipeline. " +
    "Les notes partagées entre appareils vivent dans l'entrée Notion du jour."));
  const zone = el("textarea", "zone-notes");
  const cle = `notes-fx-${dateRapport}`;
  zone.value = localStorage.getItem(cle) || "";
  zone.placeholder = "Vos notes du jour…";
  zone.addEventListener("input", () => localStorage.setItem(cle, zone.value));
  carte.appendChild(zone);
  return carte;
}

function listeSourcee(titre, elements, sources) {
  const toggle = el("details", "sous-toggle"); // replié par défaut
  toggle.appendChild(el("summary", null, titre));
  const liste = el("ul");
  for (const item of elements || []) {
    const puce = el("li", null, item.texte + " ");
    if (item.non_sourcee) {
      puce.appendChild(el("span", "tag-non-source", "[⚠ affirmation non sourcée]"));
    } else {
      const source = sources.get(item.source_id);
      puce.appendChild(el("span", "ref-source", source
        ? `— ${source.source} · ${(source.detail || "").slice(0, 60)} · ${source.date || "s.d."}`
        : `— ${item.source_id || "?"}`));
    }
    liste.appendChild(puce);
  }
  if (!liste.children.length) liste.appendChild(el("li", "ref-source", "Rien à signaler aujourd'hui."));
  toggle.appendChild(liste);
  return toggle;
}

function detailScore(detail) {
  const toggle = el("details", "sous-toggle");
  toggle.appendChild(el("summary", null, "Σ Détail du score de confluence"));
  const table = el("table", "donnees");
  table.innerHTML = "<thead><tr><th>Indicateur</th><th>Sens</th><th>Poids</th><th>Justification</th></tr></thead>";
  const corps = el("tbody");
  for (const d of detail || []) {
    const rang = el("tr");
    rang.appendChild(el("td", null, d.indicateur));
    const cellule = el("td");
    cellule.appendChild(el("span",
      d.sens > 0 ? "sens-plus" : d.sens < 0 ? "sens-moins" : "sens-zero",
      d.sens > 0 ? "+1" : String(d.sens)));
    rang.appendChild(cellule);
    rang.appendChild(el("td", null, `×${d.poids}`));
    rang.appendChild(el("td", null, d.justification || ""));
    corps.appendChild(rang);
  }
  table.appendChild(corps);
  const enveloppe = el("div");
  enveloppe.style.padding = "0 12px 12px";
  enveloppe.style.overflowX = "auto";
  enveloppe.appendChild(table);
  toggle.appendChild(enveloppe);
  return toggle;
}

/* ------------------------------------------------------------- graphiques */
function dessinerJauge(canevas, score, couleur) {
  graphiquesActifs.push(new Chart(canevas, {
    type: "doughnut",
    data: { datasets: [{
      data: [score, 100 - score],
      backgroundColor: [couleur, "#232a36"],
      borderWidth: 0,
    }] },
    options: {
      cutout: "75%", rotation: -90, animation: { duration: 300 },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
    },
  }));
}

function dessinerPrix(canevas, graphique, couleur) {
  graphiquesActifs.push(new Chart(canevas, {
    type: "line",
    data: {
      labels: graphique.dates,
      datasets: [{
        data: graphique.clotures, borderColor: couleur, borderWidth: 2,
        pointRadius: 0, pointHitRadius: 12, fill: false, tension: 0.15,
      }],
    },
    options: {
      maintainAspectRatio: false, animation: { duration: 300 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#161b25", borderColor: GRILLE, borderWidth: 1,
          titleColor: ENCRE_2, bodyColor: "#dbe2ec", displayColors: false,
        },
      },
      scales: {
        x: { ticks: { color: ENCRE_2, maxTicksLimit: 8, font: { size: 11 } },
             grid: { color: GRILLE } },
        y: { ticks: { color: ENCRE_2, font: { size: 11 } }, grid: { color: GRILLE } },
      },
    },
  }));
  canevas.parentElement.style.height = "260px";
}

/* Graphiques de marché partagés (DXY, Pétrole WTI/Brent) : une ou deux séries
   superposées — même mécanisme que dessinerPrix, réutilisé pour ces
   indicateurs communs à plusieurs devises plutôt que dupliqué. */
function dessinerSerieMarche(canevas, datasets, labels) {
  graphiquesActifs.push(new Chart(canevas, {
    type: "line",
    data: {
      labels,
      datasets: datasets.map(d => ({
        label: d.label, data: d.data, borderColor: d.couleur, borderWidth: 2,
        pointRadius: 0, pointHitRadius: 12, fill: false, tension: 0.15,
      })),
    },
    options: {
      maintainAspectRatio: false, animation: { duration: 300 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: datasets.length > 1,
                  labels: { color: ENCRE_2, boxWidth: 10, font: { size: 10 } } },
        tooltip: {
          backgroundColor: "#161b25", borderColor: GRILLE, borderWidth: 1,
          titleColor: ENCRE_2, bodyColor: "#dbe2ec", displayColors: datasets.length > 1,
        },
      },
      scales: {
        x: { ticks: { color: ENCRE_2, maxTicksLimit: 8, font: { size: 11 } },
             grid: { color: GRILLE } },
        y: { ticks: { color: ENCRE_2, font: { size: 11 } }, grid: { color: GRILLE } },
      },
    },
  }));
  canevas.parentElement.style.height = "220px";
}

initialiser();
