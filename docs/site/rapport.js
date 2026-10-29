/* Page « Rapport » (lot Rapport du jour) : docs/data/rapport_jour.json, sections calculées en Python, textes du modèle
   validés (ou phrases Python). Lundi : version complète (12 sections) ; mardi à vendredi : version courte, avec un bouton
   pour tout afficher. Sommaire cliquable, temps de lecture, impression A4, sections dépliables sur mobile.
   Calculateur de taille de position : calcul local dans le navigateur. Jamais un ordre d'achat ou de vente. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, certifier, DRAPEAUX } from "./commun.js";

const virgule = (v, d = 2) => v == null ? "n/d" : Number(v).toLocaleString("fr-FR", { maximumFractionDigits: d, minimumFractionDigits: 0 });
const signe = (v, d = 2) => v == null ? "n/d" : `${v > 0 ? "+" : ""}${virgule(v, d)}`.replace("-", "−");
const unite = u => ({ pb: " pb", "%": " %", pts: " pts" }[u] || "");
const jj = iso => iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : "n/d";

function texteSection(x) {
  const p = el("p", "rp-texte", x?.texte || x?.phrase_python || "n/d");
  p.appendChild(el("span", "source", x?.texte ? " — formulé par le modèle à partir des faits Python" : " — calcul Python"));
  return p;
}
function liste(items, cls) { const ul = el("ul", cls || "rp-liste"); for (const i of items) ul.appendChild(typeof i === "string" ? el("li", null, i) : i); return ul; }
function tableau(entetes, lignes, cls) {
  const d = el("div", "defile"); const t = el("table", `dense ${cls || ""}`);
  const tr = el("tr"); for (const h of entetes) tr.appendChild(el("th", null, h));
  const th = el("thead"); th.appendChild(tr); t.appendChild(th);
  const tb = el("tbody");
  for (const l of lignes) { const r = el("tr"); for (const c of l) r.appendChild(c instanceof Node ? (() => { const td = el("td"); td.appendChild(c); return td; })() : el("td", null, c ?? "n/d")); tb.appendChild(r); }
  t.appendChild(tb); d.appendChild(t); return d;
}

/* ------------------------------------------------------------------ sections */
const RENDUS = {
  synthese(r) {
    const s = r.synthese || {}, b = [texteSection(s)];
    if ((s.catalyseurs || []).length) {
      b.push(el("h4", null, "Catalyseurs majeurs de la semaine"));
      b.push(liste(s.catalyseurs.map(c => `${jj(c.date_paris)} ${c.heure_paris || ""} · ${DRAPEAUX[c.devise] || ""} ${c.devise} · ${c.evenement}${c.badge && c.badge.sens !== "statu_quo" ? ` (${c.badge.texte})` : ""}`)));
    }
    b.push(el("h4", null, "Biais de travail conditionnel par devise"));
    b.push(tableau(["Devise", "Biais", "Condition", "Bilan matrice", "Évènements forts", "Statut"],
      (s.biais || []).map(x => [`${DRAPEAUX[x.devise] || ""} ${x.devise}`, x.biais, x.condition, x.bilan_matrice == null ? "n/d" : signe(x.bilan_matrice, 0), String(x.evenements_forts), x.statut]), "rp-biais"));
    b.push(el("p", "note rp-mention", s.mention || ""));
    return b;
  },
  point_marche(r) {
    const pm = r.point_marche || {};
    const b = [el("p", "rp-lecture", pm.lecture_modele || pm.lecture)];
    b.push(tableau(["Actif", "Niveau", "J-1", "5 séances", "Lecture", "Heure · source"], (pm.lignes || []).map(l => {
      const n = el("span", "tabulaire", l.niveau == null ? "n/d" : virgule(l.niveau, l.unite === "pb" ? 2 : 4));
      if (l.niveau != null) certifier(n, { libelle: l.actif, valeur: n.textContent, source: l.source, date: l.heure, sansAge: l.statut === "provisoire" ? "cotation de séance (provisoire)" : undefined });
      else n.title = l.raison || "";
      return [l.actif, n, `${signe(l.variation_j1)}${unite(l.unite)}`, `${signe(l.variation_5j)}${unite(l.unite)}`, l.lecture || l.raison || "", `${l.heure ? (l.heure.length > 10 ? dateHeure(l.heure) : dateCourte(l.heure)) : ""} · ${l.source || ""}`];
    }), "rp-marche"));
    b.push(el("p", "note", pm.note || ""));
    return b;
  },
  lecture(r) {
    const det = r.lecture?.detectes || [];
    const b = [el("h4", null, "Mécanismes détectés")];
    if (!det.length) b.push(el("p", "note", "Aucun mécanisme détecté aujourd'hui (règles de config.yaml)."));
    for (const m of det) {
      const d = el("div", "rp-meca");
      d.append(el("b", null, m.libelle), el("p", null, m.lecture), el("p", "note tabulaire", m.conditions.map(c => c.chiffre).join(" · ")));
      b.push(d);
    }
    const nd = (r.lecture?.mecanismes || []).filter(m => m.etat === "nd");
    if (nd.length) b.push(el("p", "note", `Non évaluables faute de donnée : ${nd.map(m => m.libelle).join(", ")}.`));
    return b.concat(RENDUS.scenarios(r));
  },
  scenarios(r) {
    const s = r.scenarios || {}, b = [el("p", "rp-lecture", s.texte_mieux_confirme)];
    for (const x of s.liste || []) {
      const d = el("details", `rp-scen${x.mieux_confirme ? " mieux" : ""}${x.invalide ? " invalide" : ""}`);
      const sm = el("summary");
      sm.append(el("b", null, x.titre), el("span", "rp-statut tabulaire", `${x.statut}${x.invalide ? " · invalidé" : ""}${x.mieux_confirme ? " · le mieux confirmé à ce jour" : ""}`));
      d.appendChild(sm);
      d.appendChild(liste(x.conditions.map(c => `${c.remplie === true ? "✓" : c.remplie === false ? "✗" : "n/d"} ${c.libelle} — ${c.chiffre}`)));
      const cons = Object.entries(x.consequences || {}).filter(([, v]) => v).map(([dv, v]) => `${dv} ${v > 0 ? "soutenu" : "sous pression"}`);
      d.appendChild(el("p", "note", `Conséquences attendues (lecture classique) : ${cons.join(", ") || "aucune"}.`));
      d.appendChild(el("p", "note", `Invalidations : ${x.invalidations.map(c => `${c.remplie ? "⚠ " : ""}${c.libelle}`).join(" ; ") || "—"}`));
      b.push(d);
    }
    const h = s.historique || {};
    if ((h.jours || []).length > 1) {
      b.push(tableau(["Scénario", ...h.jours.map(jj)], (s.liste || []).map(x => [x.titre, ...h.jours.map(j => { const v = h.valeurs[j]?.[x.id]; return v ? `${v[0]}/${v[1]}` : "—"; })])));
    }
    b.push(el("p", "note", s.note || ""));
    return b;
  },
  calendrier(r) {
    const c = r.calendrier || {}, b = [];
    if ((c.avertissements || []).length) b.push(el("div", "alerte", c.avertissements.join(" ")));
    if ((c.fenetres || []).length) {
      b.push(el("h4", null, "Les trois fenêtres à ne pas manquer"));
      b.push(liste(c.fenetres.map(f => `${jj(f.date)} ${f.heure} (score ${virgule(f.score, 1)}) — ${f.evenements.slice(0, 4).join(" · ")}`)));
    }
    for (const j of c.jours || []) {
      const d = el("details", `rp-jour${j.n_forts >= 2 ? " critique" : ""}`);
      const sm = el("summary"); sm.append(el("b", null, `${new Date(`${j.date}T12:00:00Z`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })} — ${j.titre}`));
      d.append(sm, el("p", null, j.lecture));
      if (j.evenements.length) d.appendChild(liste(j.evenements.map(e => `${e.heure_paris} ${e.devise} ${e.evenement}${e.consensus ? ` (cons. ${String(e.consensus).replace(".", ",")})` : ""}`)));
      b.push(d);
    }
    b.push(el("p", "note", c.methode || ""));
    return b;
  },
  banques(r) {
    const b = [];
    if (!(r.banques || []).length) b.push(el("p", "note", "Aucune banque centrale ne se réunit dans les 7 jours."));
    for (const x of r.banques || []) {
      const d = el("article", "rp-bc");
      d.appendChild(el("h4", null, `${DRAPEAUX[x.devise] || ""} ${x.banque} — ${dateCourte(x.date)}${x.heure && x.heure !== "journée" ? ` à ${x.heure}` : ""}`));
      const m = x.marche;
      d.appendChild(liste([
        `Taux actuel : ${x.taux || "n/d"}${x.type_taux ? ` (${x.type_taux})` : ""} · consensus ${x.consensus || "n/d"}${x.badge ? ` · ${x.badge.texte}` : ""}`,
        m ? `Ce que le marché intègre (indication de marché) : 2 ans − taux directeur ${signe(m.ecart_pb, 0)} pb, ${signe(m.variation_4s_pb, 0)} pb sur 4 semaines (${m.source})` : `Indication de marché : n/d (${x.raison_marche})`,
        `Contexte : IPC ${x.contexte?.cpi?.valeur || "n/d"} (cible ${x.contexte?.cpi?.cible ?? "n/d"} %) · chômage ${x.contexte?.chomage?.valeur || "n/d"}`,
        `À surveiller : ${(x.a_surveiller || []).join(", ")}`,
        x.communique?.ton ? `Communiqué : ton ${x.communique.ton} — « ${(x.communique.citations || []).join(" » ; « ")} »` : `Communiqué : ${x.communique?.raison || "n/d"}`]));
      b.push(d);
    }
    const t = r.interpretation || [];
    if (t.length) { b.push(el("h4", null, "Comment interpréter une décision")); b.push(tableau(["Décision", "Lecture habituelle"], t)); }
    return b;
  },
  bilan(r) {
    const x = r.bilan || {}, b = [texteSection(x)];
    if ((x.surprises || []).length) b.push(tableau(["Devise", "Indicateur", "Date", "Publié", "Consensus", "Surprise (écarts)"],
      x.surprises.map(s => [s.devise, s.indicateur, jj(s.date), s.publie, s.consensus, signe(s.surprise_ecarts)])));
    b.push(el("p", null, `Forces sur 5 séances : ${(x.forces || []).map(f => `${f.devise} ${signe(f.variation_5j)} %`).join(" · ")}`));
    b.push(el("p", "note", `Marchés : ${(x.marches || []).map(m => `${m.actif} ${signe(m.variation_5j)}${unite(m.unite)}`).join(" · ")}`));
    for (const c of x.communiques || []) b.push(el("p", null, `${c.devise} ${jj(c.date)} : ${c.ton ? `ton ${c.ton}` : `ton n/d (${c.raison_ton})`}${c.reaction ? ` · réaction J+1 : devise ${signe(c.reaction.devise_pct)} %, 2 ans ${signe(c.reaction.deux_ans_pb, 1)} pb` : ""}`));
    if ((x.basculements || []).length) b.push(el("p", null, `Engrenages qui ont basculé : ${x.basculements.map(z => `${z.engrenage} ${z.titre} (${z.avant} → ${z.apres})`).join(" ; ")}`));
    return b;
  },
  watchlist(r) {
    const w = r.watchlist || {}, b = [el("p", "note rp-mention", w.mention)];
    for (const x of w.top || []) {
      const d = el("article", "rp-paire");
      const t = el("div", "rp-paire-tete"); t.append(el("b", null, x.paire), el("span", "rp-libelle", x.libelle), el("span", "tabulaire note", `score ${virgule(x.score)}`));
      t.title = Object.entries(x.composantes).map(([k, v]) => `${k} ${virgule(v)}`).join(" · ");
      d.appendChild(t);
      d.appendChild(liste([`Scénario haussier : ${x.scenario_haussier.texte || x.scenario_haussier.conditions.join(" ; ")}`,
                           `Scénario baissier : ${x.scenario_baissier.texte || x.scenario_baissier.conditions.join(" ; ")}`,
                           `Confirmations : ${x.confirmations}`, `Risque principal : ${x.risque || "n/d"}`]));
      b.push(d);
    }
    b.push(el("p", "note", w.methode || ""));
    return b;
  },
  technique(r) {
    const t = r.technique || {}, b = [el("p", "note rp-mention", t.mention)];
    for (const [p, n] of Object.entries(t.paires || {})) {
      const d = el("details", "rp-tech"); const sm = el("summary", null, p); d.appendChild(sm);
      if (n.raison) { d.appendChild(el("p", "note", n.raison)); b.push(d); continue; }
      const L = [];
      if (n.veille) L.push(`Veille (${jj(n.veille.jour)}) : haut ${virgule(n.veille.haut, 5)} · bas ${virgule(n.veille.bas, 5)}`);
      if (n.semaine_precedente) L.push(`Semaine précédente (${n.semaine_precedente.semaine}) : haut ${virgule(n.semaine_precedente.haut, 5)} · bas ${virgule(n.semaine_precedente.bas, 5)}`);
      for (const [s, v] of Object.entries(n.sessions || {})) if (v) L.push(`Session ${s} : haut ${virgule(v.haut, 5)} · bas ${virgule(v.bas, 5)}${v.complete ? "" : " (en cours)"}`);
      for (const e of n.structure_h4?.evenements || []) L.push(`${e.type} ${e.sens} H4 le ${e.date} au-delà de ${virgule(e.niveau, 5)}`);
      for (const z of [...(n.fvg_h4 || []).map(z => ["H4", z]), ...(n.fvg_m30 || []).map(z => ["M30", z])]) L.push(`FVG ${z[0]} ${z[1].sens} ouverte : ${virgule(z[1].bas, 5)} – ${virgule(z[1].haut, 5)}`);
      for (const k of ["tendance_jour", "tendance_semaine"]) if (n[k]) L.push(`Tendance ${n[k].unite} : ${n[k].lecture || n[k].raison}${n[k].pente_mm50 ? ` (MM50 ${n[k].pente_mm50})` : ""}`);
      const ul = liste(L);
      ul.title = Object.values(t.definitions || {}).join("\n");
      d.appendChild(ul);
      b.push(d);
    }
    return b;
  },
  tableau_de_bord(r) {
    const t = r.tableau_de_bord || {}, b = [];
    b.push(tableau(["Engrenage", "Mesure", "État", "Direction"], (t.thermometres || []).map(x => [`${x.numero} ${x.titre}`, x.texte_valeur, x.etat, x.direction?.libelle || "n/d"])));
    if ((t.au_bord || []).length) b.push(liste(t.au_bord.map(s => `Au bord du seuil : ${s.libelle} (${s.texte_valeur}, à ${s.distance_texte})`)));
    return b;
  },
  plan(r) {
    const p = r.plan || {}, b = [];
    if (p.texte) b.push(texteSection({ texte: p.texte }));
    for (const [titre, cle] of [["Avant la session", "avant"], ["Pendant la session", "pendant"], ["Avant la clôture", "cloture"]]) {
      b.push(el("h4", null, titre)); b.push(liste(p[cle] || []));
    }
    b.push(el("p", "note", p.note || ""));
    b.push(risqueBloc(r));   // gestion du risque : dans le plan, versions complète et courte
    return b;
  },
  conclusion(r) { return [texteSection(r.conclusion), el("p", "note rp-mention", r.mention)]; },
  depuis_veille(r) { return [liste(r.depuis_veille || [])]; },
  evenements_jour(r) {
    const e = r.evenements_jour || [];
    return [e.length ? liste(e.map(x => `${x.heure_paris} ${DRAPEAUX[x.devise] || ""} ${x.devise} ${x.evenement} ${x.points || ""}${x.consensus ? ` · cons. ${String(x.consensus).replace(".", ",")}` : ""}${x.publie ? ` · réel ${String(x.publie).replace(".", ",")}` : ""}`))
      : el("p", "note", "Aucun évènement notable aujourd'hui.")];
  },
};

/* ------------------------------------------------------------------ gestion du risque (outil local) */
function lireNotesOuvertes() {
  return new Promise(ok => {
    try {
      const req = indexedDB.open("fxdesk-journal", 1);
      req.onupgradeneeded = () => { const db = req.result; if (!db.objectStoreNames.contains("notes")) db.createObjectStore("notes", { keyPath: "id" }); if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta", { keyPath: "cle" }); };
      req.onerror = () => ok([]);
      req.onsuccess = () => { try { const g = req.result.transaction("notes", "readonly").objectStore("notes").getAll(); g.onsuccess = () => ok(g.result || []); g.onerror = () => ok([]); } catch (e) { ok([]); } };
    } catch (e) { ok([]); }
  });
}

function risqueBloc(r) {
  const k = r.risque || {}, c = el("section", "rp-risque");
  c.appendChild(el("h4", null, "Gestion du risque (outil, pas un conseil)"));
  const form = el("div", "rp-calc");
  const champ = (lib, type, val) => { const l = el("label", null, lib); const i = el("input"); i.type = type; i.value = val; i.step = "any"; l.appendChild(i); form.appendChild(l); return i; };
  const capital = champ("Capital", "number", "10000");
  const devise = el("select"); for (const d of ["EUR", "USD", "GBP", "CHF", "JPY", "CAD", "AUD"]) devise.appendChild(new Option(d, d));
  const ld = el("label", null, "Devise du compte"); ld.appendChild(devise); form.appendChild(ld);
  const pct = champ("Risque (%)", "number", "1");
  const stop = champ("Stop (pips)", "number", "30");
  const paire = el("select"); for (const p of Object.keys(k.valeurs_pip || {}).sort()) paire.appendChild(new Option(p, p));
  const lp = el("label", null, "Paire"); lp.appendChild(paire); form.appendChild(lp);
  const res = el("p", "rp-calc-res tabulaire");
  const calc = () => {
    const v = k.valeurs_pip?.[paire.value], usd = k.devises_usd?.[devise.value];
    const cap = parseFloat(capital.value), rk = parseFloat(pct.value), sp = parseFloat(stop.value);
    if (!v || !usd || !(cap > 0) || !(rk > 0) || !(sp > 0)) { res.textContent = "Renseigner capital, risque, stop et paire (cours du jour nécessaires)."; return; }
    const risqueUsd = cap * usd * rk / 100, lots = risqueUsd / (sp * v.valeur_pip_usd_lot);
    res.textContent = `Taille : ${virgule(lots, 2)} lot(s) standard (${virgule(lots * 100000, 0)} unités) · risque ${virgule(cap * rk / 100, 2)} ${devise.value} · valeur du pip ${virgule(v.valeur_pip_usd_lot, 2)} USD par lot (cours ${virgule(v.prix, 5)}).`;
  };
  for (const i of [capital, devise, pct, stop, paire]) i.addEventListener("input", calc);
  calc();
  c.append(form, res);
  const corr = Object.entries(k.correlations_30j || {});
  if (corr.length) c.appendChild(el("p", "note tabulaire", `Corrélations 30 j (Mes paires) : ${corr.map(([p, v]) => `${p.replace("|", " / ")} ${virgule(v)}`).join(" · ")}`));
  const alerte = el("p", "alerte"); alerte.hidden = true; c.appendChild(alerte);
  lireNotesOuvertes().then(notes => {   // notes des 7 derniers jours = « ouvertes » (le Journal n'a pas de clôture)
    const recentes = notes.filter(n => Date.now() - Date.parse(n.cree_le) < 7 * 864e5 && n.biais !== "neutre");
    const dir = n => n.biais === "haussier" ? 1 : -1, msgs = [];
    for (let i = 0; i < recentes.length; i++) for (let j = i + 1; j < recentes.length; j++) {
      const a = recentes[i], b = recentes[j], cle = [a.paire, b.paire].sort().join("|"), v = k.correlations_30j?.[cle];
      if (v != null && Math.abs(v) > (k.seuil_correlation || 0.7) && dir(a) * dir(b) * Math.sign(v) > 0) msgs.push(`${a.paire} et ${b.paire} (corrélation ${virgule(v)})`);
    }
    if (msgs.length) { alerte.hidden = false; alerte.textContent = `Exposition corrélée : notes récentes dans le même sens sur ${[...new Set(msgs)].join(" ; ")}.`; }
  });
  if ((k.publications_a_eviter || []).length) c.appendChild(el("p", null, `Publications à éviter aujourd'hui : ${k.publications_a_eviter.map(e => `${e.debut}–${e.fin} ${e.devise} ${e.evenement}`).join(" · ")}`));
  c.appendChild(el("p", "note", k.note || ""));
  return c;
}

/* ------------------------------------------------------------------ page */
export async function pageRapport() {
  const r = await chargerJson("data/rapport_jour.json");
  if (enErreur(r)) return [indisponible("Rapport du jour", r?.__erreur || "rapport_jour.json absent (prochain run)")];
  const tete = el("section", "carte rp-tete");
  tete.appendChild(el("p", "surtitre", `Rapport du jour · ${new Date(`${r.date}T12:00:00Z`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" })} · version ${r.version}`));
  tete.appendChild(el("h2", "ag-h1", r.theme?.titre || "Rapport FX"));
  tete.appendChild(el("p", "sous-titre", `Généré ${dateHeure(r.genere_le)} · ${r.redige_par?.libelle ? `textes formulés par ${r.redige_par.libelle}, chiffres et décisions en Python` : "textes et chiffres calculés en Python"} · ${r.mention}`));
  const sommaire = el("nav", "rp-sommaire"); sommaire.setAttribute("aria-label", "Sommaire du rapport");
  const actions = el("div", "rp-actions");
  const toutes = el("button", "bouton", r.version === "courte" ? "Afficher la version complète" : "Version complète affichée"); toutes.type = "button";
  const imprimer = el("button", "bouton", "Imprimer / PDF"); imprimer.type = "button"; imprimer.addEventListener("click", () => window.print());
  const temps = el("span", "note tabulaire");
  actions.append(temps, toutes, imprimer);
  tete.append(actions, sommaire);
  const corps = el("div", "rp-corps");
  const ouvert = window.innerWidth > 720;
  function rendre(cles) {
    corps.replaceChildren(); sommaire.replaceChildren();
    cles.forEach((cle, i) => {
      const s = el("details", "carte rp-section"); s.id = `rp-${cle}`; s.open = ouvert || i === 0;
      const sm = el("summary"); sm.appendChild(el("h3", null, `${i + 1}. ${r.titres?.[cle] || cle}`)); s.appendChild(sm);
      try { for (const n of (RENDUS[cle] ? RENDUS[cle](r) : [])) if (n) s.appendChild(n); }
      catch (e) { console.error(e); s.appendChild(el("p", "indisponible", `Section indisponible (${e.message}).`)); }
      corps.appendChild(s);
      const a = el("a", null, r.titres?.[cle] || cle); a.href = `#rapport`; a.addEventListener("click", ev => { ev.preventDefault(); s.open = true; s.scrollIntoView({ behavior: "smooth" }); });
      sommaire.appendChild(a);
    });
    const mots = corps.innerText.split(/\s+/).length;
    temps.textContent = `Lecture : ${Math.max(1, Math.round(mots / 220))} min`;
  }
  rendre(r.sections || []);
  // Impression : un <details> fermé reste caché quelle que soit la feuille de style ; on ouvre tout le temps d'imprimer
  let fermes = [];
  const avant = () => { fermes = [...document.querySelectorAll("#contenu details:not([open])")]; fermes.forEach(d => { d.open = true; }); };
  const apres = () => { fermes.forEach(d => { d.open = false; }); fermes = []; };
  window.addEventListener("beforeprint", avant); window.addEventListener("afterprint", apres);
  window.addEventListener("hashchange", () => { window.removeEventListener("beforeprint", avant); window.removeEventListener("afterprint", apres); }, { once: true });
  toutes.addEventListener("click", () => {
    rendre(["synthese", "point_marche", "depuis_veille", "evenements_jour", "lecture", "calendrier", "banques", "bilan", "watchlist", "technique", "tableau_de_bord", "plan", "conclusion"]);
    toutes.disabled = true; toutes.textContent = "Version complète affichée";
  });
  return [tete, corps];
}
