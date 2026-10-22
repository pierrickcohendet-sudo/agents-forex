/* Onglet Devises : une fiche par devise (9), analyse du jour, indicateurs, synthèse approfondie. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, DRAPEAUX , enBref } from "./commun.js";
import { graphiqueSerie } from "./dossiers.js";

const BIAIS = { haussier: "Haussier", baissier: "Baissier", neutre: "Neutre" };
const PROFIL = { on: "Risk On", off: "Risk Off", neutre: "Neutre" };
const PROBA = { faible: "faible", moyenne: "moyenne", elevee: "élevée" };
const ORIENTATION = { haussier: "haussière", baissier: "baissière", neutre: "neutre" };
const MOTEURS = { croissance: "Croissance", inflation: "Inflation", emploi: "Emploi", banque_centrale: "Banque centrale" };
const IMPACT = { high: "élevé", medium: "moyen", low: "faible" };

const raison = t => String(t || "raison inconnue").replace(/^indisponible\s*:\s*/i, "");

function sourceTexte(sources, ids) {
  const liste = (Array.isArray(ids) ? ids : [ids]).filter(i => i && sources.get(i));
  return liste.map(i => { const s = sources.get(i); return `${s.source} · ${String(s.detail || "").slice(0, 60)} · ${s.date || "s.d."}`; }).join(" ; ");
}
function avecSource(texte, sources, ids, nonSource) {
  const p = el("p", "texte", texte);
  if (nonSource) p.appendChild(el("span", "tag-alerte", " [non sourcée]"));
  else { const s = sourceTexte(sources, ids); if (s) p.appendChild(el("span", "source", ` — ${s}`)); }
  return p;
}
function listeSourcee(titre, items, sources) {
  const bloc = el("div", "bloc");
  bloc.appendChild(el("h3", null, titre));
  if (!(items || []).length) { bloc.appendChild(el("p", "note", "Rien à signaler aujourd'hui.")); return bloc; }
  const ul = el("ul");
  for (const it of items) {
    const li = el("li", null, it.texte);
    if (it.mecanisme) li.appendChild(el("span", null, ` — ${it.mecanisme}`));
    if (it.non_sourcee) li.appendChild(el("span", "tag-alerte", " [non sourcée]"));
    else { const s = sourceTexte(sources, it.source_id); if (s) li.appendChild(el("span", "source", ` — ${s}`)); }
    ul.appendChild(li);
  }
  bloc.appendChild(ul);
  return bloc;
}

function tableauIndicateurs(lignes) {
  const defile = el("div", "defile");
  const t = el("table", "dense compact");
  const tete = el("tr");
  for (const h of ["Indicateur", "Valeur", "Prévision", "Précédent", "Date", "Source"]) tete.appendChild(el("th", null, h));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  for (const l of lignes) {
    const tr = el("tr");
    tr.appendChild(el("td", null, l.nom));
    const v = l.valeur !== null && l.valeur !== undefined && l.valeur !== "";
    const tdv = el("td"); if (v) tdv.textContent = l.valeur; else { tdv.appendChild(el("span", "nd", "n/d")); tdv.title = l.note || ""; }
    tr.appendChild(tdv);
    tr.appendChild(el("td", null, l.prevision ?? "—"));
    tr.appendChild(el("td", null, l.precedent ?? "—"));
    tr.appendChild(el("td", null, l.date ? `${dateCourte(l.date)}${l.anciennete_jours > 7 ? ` (J-${l.anciennete_jours})` : ""}` : "—"));
    const tds = el("td", "source-cellule", l.source || (v ? "—" : l.note || "—"));
    if (v && l.note) {   // choix de la source expliqué (ex. série unique 5 ans pour le RSI)
      const pourquoi = el("details", "pourquoi-source");
      pourquoi.append(el("summary", null, "pourquoi cette source"), el("p", null, l.note));
      tds.appendChild(pourquoi);
    }
    tr.appendChild(tds);
    corps.appendChild(tr);
  }
  t.appendChild(corps);
  defile.appendChild(t);
  return defile;
}

function syntheseApprofondie(syn, sources) {
  const bloc = el("details", "synthese");
  const modele = syn?.redige_par?.libelle;
  const titre = el("summary", null, "Synthèse approfondie");
  if (syn?.statut === "ok" && modele) titre.appendChild(el("span", "note", ` · rédigée par ${modele}`));
  if (syn?.statut === "ok") { const b = enBref(syn.these_centrale?.texte); if (b) titre.appendChild(b); }
  bloc.appendChild(titre);
  if (!syn) { bloc.appendChild(el("p", "indisponible", "Synthèse indisponible : non générée pour ce rapport.")); return bloc; }
  if (syn.statut !== "ok") {
    bloc.appendChild(el("p", "indisponible", `Synthèse indisponible : ${raison(syn.raison || syn.statut)}.` +
      (syn.statut === "abandonnee" ? " Abandonnée pour la journée après plusieurs tentatives." : " Elle sera retentée au prochain passage.")));
    return bloc;
  }
  const these = syn.these_centrale || {};
  const cadre = el("div", "these");
  cadre.appendChild(el("h3", null, `Thèse centrale — orientation ${ORIENTATION[syn.orientation] || "non précisée"}`));
  cadre.appendChild(avecSource(these.texte, sources, these.source_ids, these.non_source));
  bloc.appendChild(cadre);
  if ((syn.moteurs || []).length) {
    const b = el("div", "bloc"); b.appendChild(el("h3", null, "Moteurs fondamentaux"));
    const ul = el("ul");
    for (const m of syn.moteurs) {
      const li = el("li"); li.appendChild(el("strong", null, `${MOTEURS[m.moteur] || m.moteur} : `));
      li.appendChild(document.createTextNode(`${m.donnee}. ${m.trajectoire} → ${m.implication}`));
      const s = sourceTexte(sources, m.source_id); if (s) li.appendChild(el("span", "source", ` — ${s}`));
      ul.appendChild(li);
    }
    b.appendChild(ul); bloc.appendChild(b);
  }
  for (const [cle, t] of [["taux_et_flux", "Taux et flux"], ["geopolitique", "Contexte géopolitique et politique"]]) {
    const x = syn[cle] || {};
    if (!x.texte) continue;
    const b = el("div", "bloc"); b.appendChild(el("h3", null, t)); b.appendChild(avecSource(x.texte, sources, x.source_ids, x.non_source));
    bloc.appendChild(b);
  }
  const tech = syn.lecture_technique || {};
  if (tech.texte) {
    const coh = { alignee: "alignée avec le fondamental", divergente: "en divergence avec le fondamental", mixte: "signaux mixtes" }[tech.coherence];
    const b = el("div", "bloc"); b.appendChild(el("h3", null, `Lecture technique${coh ? ` — ${coh}` : ""}`));
    b.appendChild(avecSource(tech.texte, sources, tech.source_ids, tech.non_source)); bloc.appendChild(b);
  }
  const bs = el("div", "bloc"); bs.appendChild(el("h3", null, "Scénarios"));
  for (const sc of syn.scenarios || []) {
    const c = el("div", `scenario ${sc.type}`);
    c.appendChild(el("strong", null, `Scénario ${sc.type} — probabilité ${PROBA[sc.probabilite] || "non précisée"}`));
    const p = el("p", "texte"); p.appendChild(el("strong", null, "Déclencheur : ")); p.appendChild(document.createTextNode(`${sc.declencheur} ${sc.justification}`));
    const s = sourceTexte(sources, sc.source_ids); if (s) p.appendChild(el("span", "source", ` — ${s}`));
    c.appendChild(p); bs.appendChild(c);
  }
  bloc.appendChild(bs);
  if ((syn.catalyseurs || []).length) {
    const b = el("div", "bloc"); b.appendChild(el("h3", null, "Catalyseurs à venir"));
    const ul = el("ul");
    for (const c of syn.catalyseurs) ul.appendChild(el("li", null,
      `${dateCourte(c.date)}${c.heure_utc ? ` ${c.heure_utc} UTC` : ""} — ${c.evenement} (impact ${IMPACT[c.impact] || c.impact}) : ${c.pourquoi || ""}`));
    b.appendChild(ul); bloc.appendChild(b);
  }
  if ((syn.invalidation || []).length) {
    bloc.appendChild(listeSourcee("Ce qui invaliderait la thèse", syn.invalidation.map(i => ({ texte: i.signal, source_id: i.source_id })), sources));
  }
  bloc.appendChild(listeSourcee("Opportunités (détaillées)", syn.opportunites, sources));
  bloc.appendChild(listeSourcee("Menaces (détaillées)", syn.menaces, sources));
  if ((syn.controles || []).length) bloc.appendChild(el("p", "tag-alerte", `Points de vigilance : ${syn.controles.join(" · ")}`));
  bloc.appendChild(el("p", "note", `Rédigée par ${modele || "modèle inconnu"} le ${dateHeure(syn.genere_le)} · aide à la décision, aucun signal d'achat ou de vente.`));
  return bloc;
}

function fiche(d, cles, sources, ouverte) {
  const f = el("details", "carte fiche");
  f.id = `fiche-${d.devise}`;
  if (ouverte) f.open = true;
  const s = el("summary");
  s.appendChild(el("span", "fiche-nom", `${DRAPEAUX[d.devise] || ""} ${d.devise}`));
  const biais = cles?.cellules?.biais;
  if ((d.score_confluence === null || d.score_confluence === undefined) && d.texte_automatique) s.appendChild(el("span", "note", "score n/d · texte automatique"));
  else if (d.score_confluence === null || d.score_confluence === undefined) s.appendChild(el("span", "note", "analyse indisponible"));
  else {
    s.appendChild(el("span", "tabulaire fiche-score", `${d.score_confluence}/100`));
    if (biais?.code) s.appendChild(el("span", `biais ${biais.code}`, BIAIS[biais.code]));
  }
  { const b = enBref(d.synthese_une_phrase); if (b) s.appendChild(b); }
  f.appendChild(s);
  const corps = el("div", "fiche-corps");
  if ((d.score_confluence === null || d.score_confluence === undefined) && d.texte_automatique) {
    const p = el("p", "phrase");
    p.append(el("span", "etiquette-auto", "Texte automatique, sans modèle"), document.createTextNode(` ${d.synthese_une_phrase}`));
    corps.appendChild(p);
    corps.appendChild(el("p", "note", `Sources : ${(d.texte_automatique_sources || []).join(" · ") || "—"}. Analyse du modèle indisponible : ${raison(d.raison_indisponibilite)} ; nouvel essai au prochain passage.`));
  } else if (d.score_confluence === null || d.score_confluence === undefined) {
    corps.appendChild(el("p", "indisponible", `Analyse indisponible aujourd'hui : ${raison(d.raison_indisponibilite)}. Les données collectées restent affichées.`));
  } else {
    corps.appendChild(el("p", "phrase", d.synthese_une_phrase || ""));
  }
  const meta = el("p", "note");
  meta.textContent = [
    d.redige_par?.libelle ? `Analyse rédigée par ${d.redige_par.libelle}` : null,
    `Profil structurel : ${PROFIL[d.risk_on_off] || d.risk_on_off}`,
    d.biais_banque_centrale ? `Banque centrale : ${d.biais_banque_centrale}` : null,
    d.carry?.taux_directeur !== undefined ? `Taux directeur ${String(d.carry.taux_directeur).replace(".", ",")} % (écart médiane G8 ${d.carry.differentiel_vs_mediane_g8 > 0 ? "+" : ""}${String(d.carry.differentiel_vs_mediane_g8).replace(".", ",")})` : null,
  ].filter(Boolean).join(" · ");
  corps.appendChild(meta);
  const pourquoi = d.contexte_geopolitique?.banque_centrale_pourquoi;
  if (pourquoi?.texte) { const b = el("div", "bloc"); b.appendChild(el("h3", null, "Banque centrale")); b.appendChild(avecSource(pourquoi.texte, sources, pourquoi.source_id)); corps.appendChild(b); }
  const ind = el("div", "bloc"); ind.appendChild(el("h3", null, "Indicateurs du jour"));
  ind.appendChild((d.indicateurs_tableau || []).length ? tableauIndicateurs(d.indicateurs_tableau) : el("p", "indisponible", "Tableau d'indicateurs indisponible."));
  corps.appendChild(ind);
  corps.appendChild(listeSourcee("Opportunités", d.opportunites, sources));
  corps.appendChild(listeSourcee("Menaces", d.menaces, sources));
  const evts = d.contexte_geopolitique?.evenements || [];
  if (evts.length) corps.appendChild(listeSourcee("Événements de la semaine", evts, sources));
  corps.appendChild(syntheseApprofondie(d.synthese_approfondie, sources));
  f.appendChild(corps);
  return f;
}

/* UNE valeur par indicateur sur tout le site : les indicateurs techniques de chaque devise (RSI, écarts aux
   moyennes mobiles, volatilité) viennent de la série unique 5 ans (core/historique_5ans.py), publiée dans
   dossiers.json (dossier 7) ; la même cellule alimente le dossier 7 et cet onglet. */
function techniqueUnique(dossiers, devise) {
  const ligne = (dossiers?.engrenages?.["7"]?.lignes || []).find(l => l.devise === devise);
  return ligne?.cellules || null;
}
const FMT_TECH = {
  rsi: c => `${String(c.valeur).replace(".", ",")}${c.signal ? ` (${c.signal})` : ""}`,
  ecart_mm200: c => `${c.valeur > 0 ? "+" : ""}${String(c.valeur).replace(".", ",")} %`,
  ecart_mm100: c => `${c.valeur > 0 ? "+" : ""}${String(c.valeur).replace(".", ",")} %`,
  volatilite: c => `${String(c.valeur).replace(".", ",")} % annualisée`,
};
function lignesTechniques(cellules, lignesRapport) {
  if (!cellules) return lignesRapport;
  const sortie = lignesRapport.filter(l => l.indicateur !== "rsi");
  const ajout = [["rsi", "RSI 14 (quotidien)"], ["ecart_mm200", "Écart à la moyenne mobile 200 jours"],
                 ["ecart_mm100", "Écart à la moyenne mobile 100 jours"], ["volatilite", "Volatilité réalisée 20 j"]];
  for (const [cle, nom] of ajout) {
    const c = cellules[cle];
    if (!c || c.valeur === null || c.valeur === undefined) continue;
    sortie.push({ indicateur: cle, nom, valeur: `${FMT_TECH[cle](c)}${c.percentile_5a !== null && c.percentile_5a !== undefined ? ` · percentile 5 ans ${c.percentile_5a}` : ""}`,
                  prevision: null, precedent: null, date: c.date, anciennete_jours: null,
                  source: "série unique 5 ans (Twelve Data raccordé à la Fed H.10) — même valeur que le dossier 7",
                  note: c.explication_source || "" });
  }
  return sortie;
}

/* ------------------------------------------------ cartes graphiques (palier C) */
const NOMS = { USD: "Dollar US", EUR: "Euro", GBP: "Livre sterling", JPY: "Yen", CHF: "Franc suisse", CAD: "Dollar canadien",
               AUD: "Dollar australien", NZD: "Dollar néo-zélandais", CNY: "Yuan" };
const COURT_ENG = { 1: "Thème", 2: "Monétaire", 3: "Données", 4: "Fiscale", 5: "Marchés", 6: "Géopolitique", 7: "Flux", 8: "Offre" };
const virgule = (v, d = 1) => String(Number(v).toFixed(d)).replace(".", ",").replace("-", "−");
function cellule(dos, n, devise, cle) {
  return ((dos?.engrenages?.[String(n)]?.lignes || []).find(l => l.devise === devise)?.cellules || {})[cle] || null;
}
function indicateurCarte(libelle, texte, detail) {
  const d = el("div", "dc-ind");
  d.append(el("span", null, libelle), el("b", "tabulaire", texte ?? "n/d"));
  if (detail) d.title = detail;
  return d;
}
/* Les deux moteurs du jour : cases non nulles de la matrice d'impact, les plus fortes d'abord. */
function moteurs(dos, devise) {
  const ligne = (dos?.matrice_impact?.lignes || []).find(l => l.devise === devise);
  if (!ligne) return [];
  return ligne.cases.filter(c => c.valeur !== 0).sort((a, b) => Math.abs(b.valeur) - Math.abs(a.valeur)).slice(0, 2);
}
export function carteDevise(d, dos, coursDev, cles, rapportDev) {
  const c = el("article", "dc-carte");
  const tete = el("div", "dc-tete");
  tete.append(el("span", "dc-code", d), el("span", "dc-nom", NOMS[d]));
  const score = rapportDev?.score_confluence;
  tete.appendChild(el("span", "dc-score tabulaire", score === null || score === undefined ? "score n/d" : `${score}/100`));
  const biais = cles?.cellules?.biais?.code;
  if (biais) tete.appendChild(el("span", `dc-pastille ${biais === "haussier" ? "pos" : biais === "baissier" ? "neg" : ""}`, BIAIS[biais] || biais));
  c.appendChild(tete);
  if (coursDev?.points?.length) {
    c.appendChild(graphiqueSerie({ titre: "Force de la devise, base 100", unite: null, base_100: true, base_commune: true,
      annotations: coursDev.annotations || null,
      courbes: [{ nom: d, points: coursDev.points, couleur: "var(--accent)" },
                { nom: "MM200", points: coursDev.mm200 || [], couleur: "var(--texte-2)", pointille: true }],
      source: `${coursDev.libelle} — ${coursDev.source || "série unique 5 ans"} ; moyenne mobile 200 jours en pointillé` }));
  } else c.appendChild(el("p", "indisponible", `Graphique n/d : ${coursDev?.raison || "cours.json indisponible"}.`));
  const ind = el("div", "dc-inds");
  const rsi = cellule(dos, 7, d, "rsi"), mm = cellule(dos, 7, d, "ecart_mm200"), vol = cellule(dos, 7, d, "volatilite"),
        cot = cellule(dos, 7, d, "cot"), taux = cellule(dos, 2, d, "taux_directeur");
  ind.append(
    indicateurCarte("RSI 14", rsi?.valeur !== undefined && rsi?.valeur !== null ? `${virgule(rsi.valeur)}${rsi.percentile_5a !== null && rsi.percentile_5a !== undefined ? ` · p${rsi.percentile_5a}` : ""}` : null, rsi?.source),
    indicateurCarte("Écart MM200", mm?.valeur !== undefined && mm?.valeur !== null ? `${mm.valeur > 0 ? "+" : ""}${virgule(mm.valeur, 2)} %` : null, mm?.source),
    indicateurCarte("Volatilité 20 j", vol?.valeur !== undefined && vol?.valeur !== null ? `${virgule(vol.valeur)} % · p${vol.percentile_5a ?? "—"}` : null, vol?.source),
    indicateurCarte("COT", cot?.valeur !== undefined && cot?.valeur !== null ? `${cot.valeur > 0 ? "+" : ""}${Number(cot.valeur).toLocaleString("fr-FR")} · p52 ${cot.percentile_52s ?? "—"}` : (cot?.raison ? "n/d" : null),
                    cot?.raison || (cot?.date ? `CFTC, au ${dateCourte(cot.date)}` : null)),
    indicateurCarte("Taux directeur", taux?.valeur !== undefined && taux?.valeur !== null ? `${virgule(taux.valeur, 2)} %` : null, taux?.source));
  c.appendChild(ind);
  const mots = moteurs(dos, d);
  const bloc = el("div", "dc-moteurs");
  bloc.appendChild(el("span", "dc-lab", "Moteurs du jour"));
  if (!mots.length) bloc.appendChild(el("p", "note", "Aucune case active dans la matrice d'impact aujourd'hui."));
  for (const m of mots) {
    const r = m.regles?.[0];
    bloc.appendChild(el("p", `dc-moteur ${m.valeur > 0 ? "pos" : "neg"}`,
      `${m.valeur > 0 ? "▲" : "▼"} ${m.engrenage}. ${COURT_ENG[m.engrenage]} : ${r ? `${r.regle.split(" ≥")[0].split(" ≤")[0]} (${r.chiffre})` : m.libelle}`));
  }
  c.appendChild(bloc);
  const ouvrir = el("a", "dc-ouvrir", "Ouvrir l'analyse et les points de vigilance");
  ouvrir.href = `#devises/${d}`;
  c.appendChild(ouvrir);
  return c;
}

export async function pageDevises(parametre) {
  const [rapport, site, dossiers] = await Promise.all([chargerJson("data/latest.json"), chargerJson("data/site.json"), chargerJson("data/dossiers.json")]);
  if (enErreur(rapport)) return [indisponible("Devises", rapport?.__erreur || "rapport du jour absent")];
  const sources = new Map((rapport.sources_citees || []).map(s => [s.id, s]));
  const cles = new Map(((enErreur(site) ? {} : site).indicateurs_cles || []).map(l => [l.devise, l]));
  const tete = el("section", "carte");
  tete.appendChild(el("h2", null, `Devises — rapport du ${dateCourte(rapport.meta?.date_rapport)}`));
  tete.appendChild(el("p", "sous-titre", "Neuf devises, yuan inclus. Touchez une devise pour ouvrir sa fiche."));
  const nav = el("nav", "puces-devises");
  for (const d of rapport.devises || []) { const a = el("a", null, `${DRAPEAUX[d.devise] || ""} ${d.devise}`); a.href = `#devises/${d.devise}`; nav.appendChild(a); }
  tete.appendChild(nav);
  const dos = enErreur(dossiers) ? null : dossiers;
  const cours = await chargerJson("data/cours.json");   // chargé par cette page seulement
  const grille = el("div", "dc-grille");
  const parDevise = new Map((rapport.devises || []).map(d => [d.devise, d]));
  for (const d of Object.keys(NOMS)) grille.appendChild(carteDevise(d, dos, enErreur(cours) ? null : cours.devises?.[d], cles.get(d), parDevise.get(d)));
  const note = el("p", "note", "Indicateurs : série unique 5 ans (mêmes valeurs que le dossier 7 et le tableau de chaque fiche), survol pour la source. Moteurs : cases les plus fortes de la matrice d'impact. Aide à la décision, jamais un ordre.");
  return [tete, grille, note, ...(rapport.devises || []).map(d => fiche({ ...d, indicateurs_tableau: lignesTechniques(techniqueUnique(dos, d.devise), d.indicateurs_tableau || []) },
                                                           cles.get(d.devise), sources, d.devise === parametre))];
}
