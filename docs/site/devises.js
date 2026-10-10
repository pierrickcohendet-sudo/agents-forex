/* Onglet Devises : une fiche par devise (9), analyse du jour, indicateurs, synthèse approfondie. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, DRAPEAUX } from "./commun.js";

const BIAIS = { haussier: "Haussier", baissier: "Baissier", neutre: "Neutre" };
const PROFIL = { on: "Risk On", off: "Risk Off", neutre: "Neutre" };
const PROBA = { faible: "faible", moyenne: "moyenne", elevee: "élevée" };
const ORIENTATION = { haussier: "haussière", baissier: "baissière", neutre: "neutre" };
const MOTEURS = { croissance: "Croissance", inflation: "Inflation", emploi: "Emploi", banque_centrale: "Banque centrale" };
const IMPACT = { high: "élevé", medium: "moyen", low: "faible" };

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
    tr.appendChild(el("td", "source-cellule", l.source || (v ? "—" : l.note || "—")));
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
  bloc.appendChild(titre);
  if (!syn) { bloc.appendChild(el("p", "indisponible", "Synthèse indisponible : non générée pour ce rapport.")); return bloc; }
  if (syn.statut !== "ok") {
    bloc.appendChild(el("p", "indisponible", `Synthèse indisponible : ${syn.raison || syn.statut}.` +
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
  if (d.score_confluence === null || d.score_confluence === undefined) s.appendChild(el("span", "note", "analyse indisponible"));
  else {
    s.appendChild(el("span", "tabulaire fiche-score", `${d.score_confluence}/100`));
    if (biais?.code) s.appendChild(el("span", `biais ${biais.code}`, BIAIS[biais.code]));
  }
  f.appendChild(s);
  const corps = el("div", "fiche-corps");
  if (d.score_confluence === null || d.score_confluence === undefined) {
    corps.appendChild(el("p", "indisponible", `Analyse indisponible aujourd'hui : ${d.raison_indisponibilite || "raison inconnue"}. Les données collectées restent affichées.`));
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

export async function pageDevises(parametre) {
  const [rapport, site] = await Promise.all([chargerJson("data/latest.json"), chargerJson("data/site.json")]);
  if (enErreur(rapport)) return [indisponible("Devises", rapport?.__erreur || "rapport du jour absent")];
  const sources = new Map((rapport.sources_citees || []).map(s => [s.id, s]));
  const cles = new Map(((enErreur(site) ? {} : site).indicateurs_cles || []).map(l => [l.devise, l]));
  const tete = el("section", "carte");
  tete.appendChild(el("h2", null, `Devises — rapport du ${dateCourte(rapport.meta?.date_rapport)}`));
  tete.appendChild(el("p", "sous-titre", "Neuf devises, yuan inclus. Touchez une devise pour ouvrir sa fiche."));
  const nav = el("nav", "puces-devises");
  for (const d of rapport.devises || []) { const a = el("a", null, `${DRAPEAUX[d.devise] || ""} ${d.devise}`); a.href = `#devises/${d.devise}`; nav.appendChild(a); }
  tete.appendChild(nav);
  return [tete, ...(rapport.devises || []).map(d => fiche(d, cles.get(d.devise), sources, d.devise === parametre))];
}
