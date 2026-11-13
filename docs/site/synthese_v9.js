/* Lot V9 — Synthèse du jour en 13 sections (maquette docs/design/maquette_v9_synthese.html), lue dans synthese.json.
   Tout est calculé en Python (core/synthese_v9.py) : scores, rangs, biais, mécanismes, conditions remplies, textes de
   secours ; le JavaScript ne fait que dessiner. Bouton « Sources » : source et date de chaque chiffre (survol). */
import { $, h, nf, sgn, esc, ddm, nd, spark, css, graphique, blocDetaille, store } from "./v7_commun.js";

const CLE_SOURCES = "fxdesk-sources";
const JOURS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const at = (source, date) => source || date ? ` data-src title="${esc([source, date ? "au " + ddm(date) : ""].filter(Boolean).join(" · "))}"` : "";
const val = (f, cls = "") => f && f.valeur != null ? `<span class="${cls}"${at(f.source, f.date)}>${esc(f.texte)}</span>` : nd(f?.raison);
const chipSens = s => s > 0 ? "up" : s < 0 ? "dn" : "";
const premiere = t => (String(t || "").match(/^.+?[.!?](?=\s|$)/) || [t || ""])[0];

function prose(S, sid) {
  const r = S.redaction?.[sid] || {}, t = S.textes?.[sid] || [];
  return `<div class="prose">${t.map(p => `<p>${esc(p)}</p>`).join("")}</div>`;
}
function entete(S, sec) {
  const r = S.redaction?.[sec.id] || {};
  return `<div class="rs-h"><span class="no">${sec.numero}</span><div><h2>${esc(sec.titre)}</h2><p>${esc(sec.sous_titre)} · <span class="redac ${r.par === "modele" ? "r-modele" : "r-auto"}" title="${r.par === "modele" ? "texte du modèle, chaque nombre vérifié en Python contre les faits" : "texte construit en Python à partir des faits (modèle indisponible ou texte rejeté)"}">${esc(r.libelle || "rédaction automatique")}</span></p></div></div>`;
}
const erreur = (sec) => sec.erreur ? `<div class="sec-err">Section indisponible : ${esc(sec.erreur)}</div>` : "";

/* ------------------------------------------------------------------ sections */
const THEMES_ACTU = { fed: "Fed et taux", energie: "Énergie et géopolitique", asie: "Chine et Asie", actions: "Actions et IA" };
const heureActu = iso => iso ? new Date(iso).toLocaleString("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
function actualites(liste) {
  if (!liste?.length) return "";
  return `<div class="card pad" style="display:flex;flex-direction:column;gap:6px"><div class="sec-head"><h3>À la une</h3><span class="cite">flux RSS officiels et de presse · titres d'origine, classés par thème en Python</span></div>
    <div class="news">${liste.map(a => `<a href="${esc(a.lien || "#")}" target="_blank" rel="noopener"><span class="eyebrow">${esc(THEMES_ACTU[a.theme] || a.theme)}</span><b>${esc(a.titre)}</b><span class="small">${esc(a.source || "")} · ${heureActu(a.date)}</span></a>`).join("")}</div></div>`;
}
function s1(S, F) {
  const x = F.s1 || {}, fed = x.fed || {};
  const ref = fed.precedent != null ? ` · repère : ${nf(fed.precedent, 0)} % le ${ddm(fed.precedent_date)}` : (fed.valeur != null && fed.raison_precedent ? ` · repère ${nd(fed.raison_precedent)}` : "");
  return `<div class="card pad gauge" style="max-width:640px">
      <div class="sec-head"><h3>${esc(fed.titre || "Probabilité de la prochaine décision de la Fed")}</h3><span class="cite">${fed.valeur == null ? nd(fed.raison) : `<a href="${esc(fed.lien || "#")}" target="_blank" rel="noopener" title="${esc(fed.citation || "")}">${esc(fed.source || "")}</a>`}</span></div>
      <div class="tr">${fed.valeur == null ? "" : `<i style="width:${fed.valeur}%"></i>${fed.precedent != null ? `<em style="left:${fed.precedent}%"></em>` : ""}`}</div>
      <div class="lab"><span>0 %</span><span>${fed.valeur == null ? "n/d : aucune probabilité chiffrée citée récemment" : `<b style="color:var(--ink)"${at(fed.source, fed.date)}>${nf(fed.valeur, 0)} %</b> aujourd'hui${ref}`}</span><span>100 %</span></div>
      ${fed.valeur != null ? `<span class="cite" title="${esc(fed.methode || "")}">« ${esc(fed.citation || "")} »</span>` : ""}
    </div>
    <div class="themes">${(x.themes || []).map((t, i) => `<div class="card"><span class="k">${i + 1}</span><b>${esc(t.titre)}</b><p>${esc(t.texte)}</p></div>`).join("")}</div>
    ${actualites(x.actualites)}`;
}

function s2(S, F) {
  const x = F.s2 || {}, m = x.mecanisme || {};
  const lignes = (x.marches || []).map(l => {
    if (l.valeur == null) return `<tr><td><b>${esc(l.libelle)}</b></td><td class="n">${nd(l.raison)}</td><td></td><td></td><td></td></tr>`;
    const col = (l.variation_5 ?? 0) > 0 ? "var(--up)" : (l.variation_5 ?? 0) < 0 ? "var(--down)" : "var(--muted)";
    const u = l.unite === "pb" ? " pb" : l.unite === "pts" ? " pt" : " %";
    return `<tr><td><b>${esc(l.libelle)}</b>${l.statut === "estimation" ? ' <span class="chip warn" style="height:20px" title="estimation : voir la source">estimation</span>' : ""}</td>
      <td class="n"><b${at(l.source, l.date)}>${esc(l.texte)}</b><small class="small" style="display:block">${l.variation_5 == null ? "" : sgn(l.variation_5, l.unite === "pb" ? 1 : 2, u) + " sur 5 séances"}</small></td>
      <td><span class="${l.retard ? "chip warn retard" : "small"}" title="${l.retard ? esc(`dernière observation ${l.retard_jours_ouvres} jour(s) ouvré(s) avant aujourd'hui`) : ""}">${ddm(l.date)}${l.retard ? " · en retard" : ""}</span></td>
      <td style="width:120px">${spark(l.serie_30 || [], 120, 30, col, true).replace("<svg", '<svg style="width:120px;height:30px"')}</td>
      <td class="small" style="color:var(--ink-2)">${esc(l.lecture || "")}</td></tr>`;
  }).join("");
  return `<div class="card scroll"><table class="tbl" style="min-width:640px"><thead><tr><th>Marché</th><th class="n">Dernière observation</th><th>Date</th><th>30 séances</th><th>Lecture</th></tr></thead><tbody>${lignes}</tbody></table></div>
    ${prose(S, "s2")}
    <div class="card pad" style="display:flex;flex-direction:column;gap:12px">
      <div class="sec-head"><h3>Lecture cross-asset : d'où vient la force du dollar ?</h3><span class="cite" title="${esc(m.seuils || "")}">mécanisme actif encadré · seuils au survol</span></div>
      <div class="mech">${(m.mecanismes || []).map(k => `<div class="${k.actif ? "on" : ""}"><b>${esc(k.libelle)}</b><span class="${k.actif ? "" : "muted"}">${esc(k.lecture)}${k.actif ? ` Actif sur ${esc(k.horizon)}.` : ""}</span>
        ${(k.conditions || []).map(c => `<span class="mc9 ${c.remplie_5 || c.remplie_1 ? "ok" : ""}" title="${esc(c.chiffre)}">${c.remplie_5 || c.remplie_1 ? "✓" : "○"} ${esc(c.texte)}</span>`).join("")}</div>`).join("")}</div>
      <p style="margin:0;font-size:14px;color:var(--ink-2)">${esc(m.phrase || "")}</p>
    </div>`;
}

function barres(items, max) {
  return items.map(([l, v, c, t]) => `<div style="display:grid;grid-template-columns:120px minmax(0,1fr) 84px;gap:10px;align-items:center;padding:6px 0;font-size:13.5px"><span>${esc(l)}</span><div style="height:16px;border-radius:4px;background:var(--surface)"><i style="display:block;height:100%;width:${v == null ? 0 : Math.max(2, Math.abs(v) / max * 100)}%;background:${c};border-radius:4px"></i></div><b style="text-align:right">${t}</b></div>`).join("");
}

function s3(S, F) {
  const x = F.s3 || {}, p = x.principale, em = x.emploi, pro = F.prochain;
  let html = "";
  if (p) {
    const chip = `<span class="chip ${chipSens(p.sens)}">${esc(p.surprise === "sans consensus" ? "sans consensus" : p.surprise.replace(/^./, c => c.toUpperCase()))}</span>`;
    let kn, bars;
    if (em) {
      const rv = (em.revisions || [])[0];
      kn = `<div><span>Créations d'emplois</span><b class="${em.creations.valeur > 0 ? "pos" : "neg"}">${val(em.creations)}</b><small>consensus ${val(em.consensus)}</small></div>
        <div><span>Chômage</span><b>${val(em.chomage)}</b><small>précédent ${em.chomage_precedent == null ? "n/d" : nf(em.chomage_precedent, 1) + " %"}</small></div>
        <div><span>${rv ? esc(rv.texte.split(" ")[0]) + " révisé" : "Révision"}</span><b>${rv?.revise_k != null ? sgn(rv.revise_k * 1000, 0) : nd("révision n/d")}</b><small>${rv?.premier_k != null ? "au lieu de " + sgn(rv.premier_k * 1000, 0) : esc(rv?.raison || "")}</small></div>
        <div><span>Sous-emploi U-6</span><b class="${(em.u6.valeur ?? 0) > (em.u6_precedent ?? 99) ? "neg" : ""}">${val(em.u6)}</b><small>précédent ${em.u6_precedent == null ? "n/d" : nf(em.u6_precedent, 1) + " %"}</small></div>`;
      const max = Math.max(...[em.consensus.valeur, em.creations.valeur, (rv?.revise_k || 0) * 1000].map(v => Math.abs(v || 0)), 1) * 1.1;
      bars = barres([["Consensus", em.consensus.valeur, "var(--line-2)", sgn((em.consensus.valeur || 0) / 1000, 0, " k")],
                     ["Publié", em.creations.valeur, "var(--up)", sgn(em.creations.valeur / 1000, 0, " k")],
                     ...(rv?.revise_k != null ? [[`${rv.texte.split(" ")[0]} révisé`, rv.revise_k * 1000, "var(--c1)", sgn(rv.revise_k, 0, " k")]] : [])], max);
      bars += `<p class="small" style="margin:6px 0 0">Salaire horaire ${val(em.salaire_mm)} sur le mois · participation ${val(em.participation)} · <a href="${esc(em.lien)}" target="_blank" rel="noopener">BLS</a></p>`;
    } else {
      kn = `<div><span>Publié</span><b class="${p.sens > 0 ? "pos" : p.sens < 0 ? "neg" : ""}"${at(p.source, p.date)}>${esc(p.reel)}</b><small>${esc(p.heure || "")}</small></div>
        <div><span>Consensus</span><b>${p.consensus ? esc(p.consensus) : nd("consensus non archivé")}</b><small>ForexFactory</small></div>
        <div><span>Précédent</span><b>${p.precedent ? esc(p.precedent) : nd("précédent non archivé")}</b><small>${p.revision ? "révisé à " + esc(p.revision) : ""}</small></div>
        <div><span>Pays</span><b style="font-size:24px">${esc(p.pays)}</b><small>${esc(p.devise)}</small></div>`;
      bars = `<div class="small">Publications de la séance du ${ddm(x.jour)} :</div>` + (x.publications || []).slice(0, 5).map(q => `<div class="small" style="padding:4px 0;border-top:1px solid var(--line)"><b>${esc(q.devise)} ${esc(q.evenement)}</b> : ${esc(q.reel)}${q.consensus ? " contre " + esc(q.consensus) : ""} <span class="${q.sens > 0 ? "pos" : q.sens < 0 ? "neg" : "muted"}">(${esc(q.surprise)})</span></div>`).join("");
    }
    html += `<div class="card nfp">
      <div class="nfp-l"><div class="sec-head"><h3>${esc(p.titre)} · ${ddm(p.date)}${p.heure ? " " + esc(p.heure) : ""}</h3>${chip}</div><div class="kn">${kn}</div>
        <span class="cite">Source : ${esc(em ? (em.creations.source || "BLS") : p.source || "")}, ${ddm(p.date)}</span></div>
      <div class="nfp-r"><h3>Publié contre attendu</h3><div>${bars}</div></div></div>`;
    html += prose(S, "s3");
    html += `<div class="card pad" style="display:flex;flex-direction:column;gap:10px"><h3>La chaîne de causalité</h3>
      <div class="chain">${(x.chaine || []).map((c, i) => `${i ? "<i>→</i>" : ""}<span class="${c.fin ? "end " + (c.classe === "dn" ? "dnx" : "") : ""}"${c.fin && c.classe === "dn" ? ' style="background:var(--down-soft);color:var(--down)"' : ""} title="${esc(c.note || c.raison || (c.date ? "au " + ddm(c.date) : ""))}">${esc(c.texte)}</span>`).join("")}</div>
      <p style="margin:0;font-size:13.5px;color:var(--muted)">${esc(x.avertissement || "")}</p></div>`;
  } else html += `<div class="sec-err">${esc(x.raison || "Aucune publication archivée pour la dernière séance.")}</div>` + prose(S, "s3");
  if (pro) {
    html += `<div class="cols2" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)">
      <div class="card"><div class="pad" style="padding-bottom:4px"><div class="sec-head"><h3>${esc(pro.titre)}</h3><span class="cite">consensus du calendrier</span></div></div>
        <table class="tbl"><thead><tr><th>Indicateur</th><th class="n">Consensus</th><th class="n">Précédent</th></tr></thead><tbody>
        ${(pro.lignes || []).map(l => `<tr><td>${esc(l.evenement)}</td><td class="n"><b>${l.consensus ? esc(l.consensus) : nd("consensus non publié")}</b></td><td class="n">${l.precedent ? esc(l.precedent) : "n/d"}</td></tr>`).join("")}</tbody></table></div>
      <div class="card pad" style="display:flex;flex-direction:column;gap:10px"><h3>Lire le chiffre clé : ${esc(pro.cle || pro.evenement)}</h3>
        <div class="grid4">${(pro.lire?.cas || []).map(c => `<div style="background:var(--${c.classe === "up" ? "up-soft" : c.classe === "dn" ? "down-soft" : c.classe === "warn" ? "warn-soft" : "surface-2"})"><b>${esc(c.si)}</b><span>${esc(c.lecture)}</span></div>`).join("")}</div></div></div>`;
  }
  const disc = F.discours || [];
  html += `<div class="card pad" style="display:flex;flex-direction:column;gap:10px"><div class="sec-head"><h3>Discours de la semaine</h3><span class="cite">regroupés par intervenant · votants FOMC 2026 en gras (federalreserve.gov)</span></div>
    <div class="speak">${disc.length ? disc.map(d => `<span class="chip ${d.priorite === "président" ? "acc" : ""}" title="${esc([d.role, d.statut, d.source_statut].filter(Boolean).join(" · "))}">${esc(d.devise)} · ${d.priorite === "votant" || d.priorite === "président" ? `<b>${esc(d.intervenant)}</b>` : esc(d.intervenant)}${d.statut ? ` (${esc(d.statut)})` : ""} · ${esc(d.passages.join(", "))}</span>`).join("") : '<span class="muted">Aucun discours à l\'Agenda cette semaine.</span>'}</div></div>`;
  return html;
}

function s4(S, F) {
  const x = F.s4 || {}, b = x.banques || [];
  const max = Math.max(...b.map(l => l.taux || 0), 1) * 1.05;
  return `<div class="cols2" style="grid-template-columns:minmax(0,1fr) minmax(0,1.1fr)">
      <div class="card pad" style="display:flex;flex-direction:column;gap:4px"><div class="sec-head"><h3>Taux directeurs</h3><span class="cite">dernier mouvement</span></div>
        ${b.map(l => `<div class="bcbar"><b>${esc(l.banque)}</b><div class="tr"><i style="width:${(l.taux || 0) / max * 100}%"></i></div><span style="text-align:right"><b${at(l.source, l.derniere_date)}>${esc(l.taux_texte)}</b> <span class="mv ${l.variation_pb > 0 ? "pos" : l.variation_pb < 0 ? "neg" : "muted"}">${l.variation_pb > 0 ? "▲" + l.variation_pb : l.variation_pb < 0 ? "▼" + Math.abs(l.variation_pb) : "="}</span></span></div>`).join("")}
        <span class="cite">▲ ▼ dernier mouvement en pb · Fed : borne haute de la fourchette</span></div>
      <div class="card scroll"><table class="tbl" style="min-width:560px"><thead><tr><th>Banque</th><th>Dernière décision</th><th>Prochaine</th><th>Lecture</th></tr></thead><tbody>
        ${b.map(l => `<tr><td><b>${esc(l.banque)}</b></td><td>${esc(l.taux_texte)}${l.derniere_texte && l.derniere_texte !== "n/d" ? ", " + esc(l.derniere_texte) : ` ${nd("dernière décision non archivée")}`}</td><td>${l.prochaine ? ddm(l.prochaine) : "n/d"}</td><td class="small" style="color:var(--ink-2)">${esc(l.lecture)}${l.vocabulaire ? ` · ${l.communique_lien ? `<a href="${esc(l.communique_lien)}" target="_blank" rel="noopener">${esc(l.vocabulaire)}</a>` : esc(l.vocabulaire)}` : ""}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="cc9">${(x.cartes || []).map(c => `<div class="card"><h3>${esc(c.devise)} <span class="chip ${c.classe}">${esc(c.etat)}</span></h3><p>${esc(c.texte)}</p>${communique(c.communique)}</div>`).join("")}</div>
    ${prose(S, "s4")}<p class="cite">${esc(x.note || "")}${Object.keys(x.communiques_nd || {}).length ? " · Communiqués non lus : " + Object.entries(x.communiques_nd).map(([d, r]) => `${esc(d)} ${nd(r)}`).join(", ") : ""}</p>`;
}
function communique(c) {
  if (!c) return "";
  if (c.raison) return `<span class="cite">Communiqué ${nd(c.raison)}</span>`;
  const v = c.vocabulaire || {};
  return `<div style="display:flex;flex-direction:column;gap:6px;font-size:12.5px;color:var(--ink-2)">
    ${c.minorite ? `<span class="cite">Minorité : « ${esc(c.minorite)} »</span>` : ""}
    ${(c.projections || []).slice(0, 2).map(p => `<span class="cite">Projection citée : « ${esc(p)} »</span>`).join("")}
    ${v.lecture ? `<span title="${esc(v.methode || "")}"><b>Vocabulaire :</b> ${esc(v.lecture)} (${v.n_ajouts} phrase${v.n_ajouts > 1 ? "s" : ""} nouvelle${v.n_ajouts > 1 ? "s" : ""}, ${v.n_retraits} retirée${v.n_retraits > 1 ? "s" : ""})${v.ajouts?.[0] ? ` · nouveau : « ${esc(v.ajouts[0])} »` : ""}</span>` : `<span class="cite">Vocabulaire ${nd(v.raison)}</span>`}
    <a class="cite" href="${esc(c.lien)}" target="_blank" rel="noopener">Communiqué officiel du ${ddm(c.date)}</a></div>`;
}

function s5(S, F) {
  const x = F.s5 || {}, b = x.brent || {};
  const note = b.disponible ? `EIA ${nf(b.officiel.valeur, 2)} $ au ${ddm(b.officiel.date)}${b.estimation ? ` · estimation ETF BNO ${nf(b.estimation.valeur, 2)} $ au ${ddm(b.estimation.date)}` : ""}` : "";
  return `<div class="card pad" style="display:flex;flex-direction:column;gap:8px">
      <div class="sec-head"><h3>Brent, 6 mois ($/baril)</h3><span class="cite" title="${esc(b.estimation?.methode || "")}">${esc(note)}</span></div>
      ${b.alerte ? `<div class="alerte9">${esc(b.alerte)}</div>` : ""}
      <div class="ch" id="v9Brent" role="img" aria-label="Brent sur 6 mois"></div>
      <span class="cite">${b.disponible ? `Trait plein : prix spot officiel (${esc(b.officiel.source)}) · trait orange : estimation par l'ETF BNO (${esc(b.estimation?.source || "n/d")}), jamais un prix au comptant` : nd(b.raison)}</span></div>
    ${prose(S, "s5")}
    <div class="cols2">
      <div class="card scroll"><table class="tbl"><thead><tr><th>Pétrole</th><th>Conséquence</th></tr></thead><tbody>${(x.consequences || []).map(c => `<tr><td><b>${esc(c.cas)}</b></td><td>${esc(c.consequence)}</td></tr>`).join("")}</tbody></table></div>
      <div class="card pad" style="display:flex;flex-direction:column;gap:8px"><h3>Devises sensibles</h3>
        <ul class="chk" style="gap:8px">${(x.sensibles || []).map(c => `<li><span><b>${esc(c.devises)}</b> : ${esc(c.texte)}</span></li>`).join("")}</ul>
        <p style="margin:0;font-size:13px;color:var(--muted)">${esc(x.avertissement || "")}</p>
        <p class="small" style="margin:0">WTI ${x.wti?.semaine_pct == null ? "n/d" : sgn(x.wti.semaine_pct, 1, " %")} sur 5 séances (${esc(x.wti?.semaine_source || "")}, au ${ddm(x.wti?.semaine_date)})</p></div></div>`;
}

function s6(S, F) {
  const x = F.s6 || {};
  return `<div class="cc9">
      <div class="card"><h3>Prix chinois</h3>${(x.prix || []).map(p => `<p>${esc(p.libelle)} : ${p.reel ? `<b class="${p.sens > 0 ? "pos" : p.sens < 0 ? "neg" : ""}"${at(p.source, p.date)}>${esc(p.reel)}</b> au ${ddm(p.date)}${p.consensus ? ` (attendu ${esc(p.consensus)})` : ""}` : nd(p.raison)}</p>`).join("")}</div>
      <div class="card"><h3>Marchés asiatiques</h3>${(x.marches || []).map(m => `<p>${esc(m.libelle)} : ${m.valeur == null ? nd(m.raison) : `<b${at(m.source, m.date)}>${esc(m.texte)}</b> au ${ddm(m.date)}${m.variation_1 != null ? ", " + sgn(m.variation_1, 2, " %") + " sur la séance" : ""}, ${sgn(m.variation_5, 2, " %")} sur 5 séances <span class="chip" style="height:20px">ETF</span>`}</p>`).join("")}</div>
      <div class="card"><h3>Actions, IA et Asie</h3>${(x.actualites || []).length ? (x.actualites || []).map(a => `<p><a href="${esc(a.lien || "#")}" target="_blank" rel="noopener">${esc(a.titre)}</a> <span class="small">${esc(a.source || "")}, ${heureActu(a.date)}</span></p>`).join("") : `<p>${nd("aucun titre de ces thèmes dans les flux collectés")}</p>`}</div>
      <div class="card"><h3>Conséquences Forex</h3>${(x.devises || []).map(d => `<p><b>${esc(d.devise)}</b> ${d.j5 == null ? nd("force n/d") : `<span class="${d.j5 > 0 ? "pos" : d.j5 < 0 ? "neg" : ""}"${at(x.source_force, d.date)}>${sgn(d.j5, 2, " %")}</span> sur 5 séances`} : ${esc(d.lien)}.</p>`).join("")}</div></div>
    ${prose(S, "s6")}`;
}

function s7(S, F) {
  const x = F.s7 || {};
  return `<div class="week">${(x.jours || []).map(j => { const d = new Date(j.date + "T12:00:00Z");
      return `<div class="wd ${j.cle ? "key" : ""}"><header><span class="eyebrow">${JOURS[d.getUTCDay()]}</span><b>${d.getUTCDate()}</b></header>${j.evenements.length ? j.evenements.map(e => `<div class="e ${e.impact}"><span class="small">${esc(e.heure || "")} · ${esc(e.devise)}</span><b>${esc(e.evenement)}</b>${e.publie ? `<span class="small pub">publié ${esc(e.publie)}${e.consensus ? " · attendu " + esc(e.consensus) : ""}</span>` : (e.consensus || e.precedent) ? `<span class="small">${e.consensus ? "attendu " + esc(e.consensus) : ""}${e.consensus && e.precedent ? " · " : ""}${e.precedent ? "préc. " + esc(e.precedent) : ""}</span>` : ""}</div>`).join("") : '<div class="e"><span class="muted">Rien de majeur</span></div>'}</div>`; }).join("")}</div>
    <div class="cc9">${(x.cles || []).map(c => `<div class="card"><h3>${esc(c.jour)} · ${esc(c.devise)} ${esc(c.evenement)} <span class="chip dn">Clé</span></h3>
      <p>${c.publie ? `Publié ${esc(c.publie)}${c.consensus ? " contre " + esc(c.consensus) + " attendu" : ""}.` : `${c.consensus ? "Consensus " + esc(c.consensus) : "Consensus n/d"}${c.precedent ? ", précédent " + esc(c.precedent) : ""}.`}</p>
      ${(c.lire?.cas || []).slice(0, 3).map(k => `<p class="small" style="margin:0"><b class="${k.classe === "up" ? "pos" : k.classe === "dn" ? "neg" : ""}">${esc(k.si)}</b> : ${esc(k.lecture)}</p>`).join("")}</div>`).join("")}</div>
    ${prose(S, "s7")}<p class="cite">${esc(x.a_ne_pas_surinterpreter || "")}</p>`;
}

function s8(S, F) {
  const x = F.s8 || {}, d = x.devises || [];
  const mx = Math.max(...d.map(l => Math.abs(l.score)), 1);
  return `<div class="card pad"><div class="rank">${d.map(l => `<div class="rw"><span class="n">${l.rang}</span><b class="c">${esc(l.devise)}</b><span class="chip ${l.classe}" style="justify-self:start">${esc(l.biais)}</span>
      <span style="color:var(--ink-2);font-size:13.5px" title="${esc(l.composantes.map(c => c.texte + " (" + sgn(c.valeur, 2) + ")").join(" · "))}">${esc(l.moteur)}</span>
      <div style="display:flex;flex-direction:column;gap:3px"><div class="bar"><i style="${l.score >= 0 ? "left:50%" : "right:50%"};width:${Math.abs(l.score) / mx * 50}%;background:${l.score >= 0 ? "var(--up)" : "var(--down)"}"></i></div><span class="small" style="text-align:right">score ${sgn(l.score, 2)}</span></div></div>`).join("")}</div></div>
    ${prose(S, "s8")}<p class="cite">${esc(x.methode || "")} ${esc(x.mention || "")}</p>`;
}

function s9(S, F) {
  const x = F.s9 || {};
  return `<div class="pairs9">${(x.paires || []).map(p => { const col = (p.variation_30 ?? 0) >= 0 ? css("--up") : css("--down");
      return `<div class="card p9"><div class="top"><div><span class="eyebrow">${esc(p.priorite || "")}</span><h3><a href="#paire/${p.paire.replace("/", "-")}" style="color:inherit;text-decoration:none">${esc(p.paire)}</a></h3></div><span class="chip ${p.classe}">${esc(p.biais)}</span></div>
      ${spark(p.serie_30 || [], 300, 52, col, true)}<span class="small">${p.dernier != null ? nf(p.dernier, p.dernier > 20 ? 2 : 4) + " au " + ddm(p.date) + " · " + sgn(p.variation_30, 2, " %") + " sur 30 séances" : "cours n/d"}</span>
      <ul>${(p.arguments || []).map(a => `<li>${esc(a)}</li>`).join("")}</ul>
      <div class="sc"><div style="background:var(--up-soft)"><b class="pos">Hausse si</b> ${esc(p.hausse_si)}</div><div style="background:var(--down-soft)"><b class="neg">Baisse si</b> ${esc(p.baisse_si)}</div></div></div>`; }).join("")}</div>
    ${prose(S, "s9")}<p class="cite">${esc(x.mention || "")}</p>`;
}

function s10(S, F) {
  const x = F.s10 || {};
  if (!x.disponible) return `<div class="sec-err">${esc(x.raison || "Technique indisponible.")}</div>${prose(S, "s10")}`;
  const coul = n => n.cote === "resistance" ? "background:var(--down-soft);color:var(--down)" : "background:var(--up-soft);color:var(--up)";
  const liste = l => `<ul class="chk">${l.map(c => typeof c === "string" ? `<li>${esc(c)}</li>` : `<li class="${c.remplie ? "ok" : ""}" title="${c.remplie ? "condition remplie (Python)" : "condition non remplie"}">${esc(c.texte)}</li>`).join("")}</ul>`;
  const ec = x.ecart || {};
  return `<div class="tech">
      <div class="card pad" style="display:flex;flex-direction:column;gap:8px;min-width:0"><div class="sec-head"><h3>${esc(x.paire)}, 1 jour</h3><span class="cite">${esc(x.source)} · zones : repères, pas des signaux</span></div>
        <div class="ch" id="v9Tech" style="height:340px"></div><div id="v9TechRsi" hidden></div>
        <div class="sec-head"><h3>Écart de taux ${ec.maturite === "10a" ? "10" : "2"} ans ${esc(x.paire.replace("/", " − "))} (pb)</h3><span class="cite">${ec.actuel_pb != null ? `dernier ${sgn(ec.actuel_pb, 0)} pb au ${ddm(ec.date)}` : nd(ec.raison)}</span></div>
        <div class="ch" id="v9Ecart" style="height:130px"></div>${ec.phrase ? `<span class="cite">${esc(ec.phrase)}</span>` : ""}</div>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div class="card pad"><h3 style="margin-bottom:6px">Niveaux</h3><div class="lvl">${(x.niveaux || []).map(n => `<div><i style="${coul(n)}">${esc(n.court)}</i><span>${esc(n.nom === "Zone d'extension" ? "Zone d'extension" : n.cote === "resistance" ? "Résistance" : "Support")} · ${n.contacts} contact${n.contacts > 1 ? "s" : ""}${n.distance_pips != null ? ` · ${sgn(n.distance_pips, 0)} pips` : ""}</span><b>${esc(n.texte)}</b></div>`).join("")}</div>
          <p class="small" style="margin:8px 0 0">RSI 14 : ${x.rsi_1j == null ? "n/d" : nf(x.rsi_1j, 1)} (1 jour) · ${x.rsi_4h == null ? "n/d" : nf(x.rsi_4h, 1)} (4 h)${(x.divergences || []).length ? " · " + esc(x.divergences.map(d => d.texte).join(" ; ")) : " · aucune divergence confirmée"}</p></div>
        <div class="card pad" style="display:flex;flex-direction:column;gap:8px"><h3>Scénario haussier conditionnel</h3><span class="eyebrow">Macro</span>${liste(x.macro_haussier || [])}<span class="eyebrow">Technique</span>${liste(x.technique_haussier || [])}</div>
        <div class="card pad" style="display:flex;flex-direction:column;gap:8px"><h3>Scénario baissier alternatif</h3><span class="eyebrow">Macro</span>${liste(x.macro_baissier || [])}<span class="eyebrow">Technique</span>${liste(x.technique_baissier || [])}</div>
      </div></div>
    ${prose(S, "s10")}
    <div class="card pad" style="background:var(--warn-soft);border-color:transparent">${esc(x.vigilance || "")}</div>`;
}

function s11(S, F) {
  const x = F.s11 || {};
  return `<div class="scen3">${(x.scenarios || []).map((sc, i) => `<div class="card ${"abc"[i]}"><span class="chip ${sc.classe}" style="align-self:flex-start">${esc(sc.chip)}</span><h3>${esc(sc.lettre)} · ${esc(sc.titre)}</h3>
      <span class="lab">Conditions · ${sc.remplies ?? "n/d"} sur ${sc.total ?? "n/d"}</span><ul class="chk">${(sc.conditions || []).map(c => `<li class="${c.remplie ? "ok" : ""}" title="${esc((c.chiffre || "") + (c.date ? " · au " + ddm(c.date) : ""))}">${esc(c.texte)}</li>`).join("")}</ul>
      <span class="lab">Conséquences</span><ul>${(sc.consequences || []).map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>`).join("")}</div>
    ${prose(S, "s11")}<p class="cite">${esc(x.texte_mieux_confirme || "")} ${esc(x.note || "")}</p>`;
}

function s12(S, F) {
  const x = F.s12 || {};
  return `<div class="card scroll"><table class="tbl" style="min-width:520px"><thead><tr><th>Priorité</th><th>Paire</th><th>Biais de départ</th><th>Catalyseur</th></tr></thead><tbody>
      ${(x.priorites || []).map(r => `<tr><td><span style="font-family:var(--f-display);font-size:20px">${r.rang}</span></td><td><b>${esc(r.paire)}</b></td><td>${esc(r.biais)}</td><td class="muted">${esc(r.catalyseur)}</td></tr>`).join("")}</tbody></table></div>
    <div class="method">${(x.methode || []).map(m => `<div><b>${esc(m.titre)}</b><span class="muted">${esc(m.texte)}</span></div>`).join("")}</div>
    ${prose(S, "s12")}`;
}

function s13(S, F) {
  const x = F.s13 || {};
  return `<div class="card concl"><span class="eyebrow">13 · Conclusion</span><h2>Biais central : ${esc(x.biais || "n/d")}</h2>
      <ol>${(x.priorites || []).map(p => `<li>${esc(p)}</li>`).join("")}</ol>
      <div class="adv">Le rendez-vous déterminant : <b>${esc(x.rendez_vous || "n/d")}</b>. ${esc(x.prudence || "")}</div>
      ${(S.textes?.s13 || []).map(p => `<p style="margin:0;opacity:.85">${esc(p)}</p>`).join("")}</div>
    <div class="sec-head"><h3>Sources</h3><span class="cite">liens vers les publications officielles et les données utilisées</span></div>
    <div class="srcs">${(x.sources || []).map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener"><b>${esc(s.nom)}</b><small>${esc(s.quoi)}</small></a>`).join("")}</div>`;
}

const RENDUS = { s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13 };

/* ------------------------------------------------------------------ Lot V9.4 : structure des rapports modèles (13/11) */
const liste = (l, cls = "chk") => `<ul class="${cls}">${(l || []).map(c => typeof c === "string" ? `<li>${esc(c)}</li>` :
  `<li class="${c.remplie ? "ok" : ""}" title="${c.remplie == null ? "à vérifier sur le graphique" : c.remplie ? "condition remplie (Python)" : "condition non remplie (Python)"}">${esc(c.texte)}${c.remplie == null ? ' <span class="small">· à vérifier</span>' : ""}</li>`).join("")}</ul>`;

function e94(S, F) {
  const x = F.exec || {}, fed = x.fed || {}, rm = x.risque_majeur || {};
  return `<div class="cols2" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)">
      <div class="card pad" style="display:flex;flex-direction:column;gap:8px"><span class="eyebrow">Facteur dominant</span><p style="margin:0">${esc(x.facteur_dominant || "n/d")}</p>
        <span class="eyebrow" style="margin-top:6px">Risque majeur</span><p style="margin:0">${rm.type === "seuil" ? `<b${at(rm.source, null)}>${esc(rm.texte)}</b>` : esc(rm.texte || "n/d")}</p>${rm.lien ? `<a class="cite" href="${esc(rm.lien)}" target="_blank" rel="noopener">Source du seuil</a>` : ""}</div>
      <div class="card pad gauge"><div class="sec-head"><h3>${esc(fed.titre || "Probabilité de la Fed")}</h3><span class="cite">${fed.valeur == null ? nd(fed.raison) : `<a href="${esc(fed.lien || "#")}" target="_blank" rel="noopener" title="${esc(fed.citation || "")}">${esc(fed.source || "")}</a>`}</span></div>
        <div class="tr">${fed.valeur == null ? "" : `<i style="width:${fed.valeur}%"></i>${fed.precedent != null ? `<em style="left:${fed.precedent}%"></em>` : ""}`}</div>
        <div class="lab"><span>0 %</span><span>${fed.valeur == null ? "n/d : aucune probabilité chiffrée citée récemment" : `<b style="color:var(--ink)">${nf(fed.valeur, 0)} %</b>${fed.precedent != null ? ` · ${nf(fed.precedent, 0)} % le ${ddm(fed.precedent_date)}` : ""}`}</span><span>100 %</span></div></div></div>
    <div class="themes">${(x.elements || []).map((t, i) => `<div class="card"><span class="k">${i + 1}</span><b>${esc(t.titre)}</b><p>${esc(t.texte)}</p></div>`).join("")}</div>
    ${actualites(x.actualites)}`;
}

function m94(S, F) {
  const x = F.marches || {}, m = x.mecanisme || {};
  return `<div class="tuiles">${(x.tuiles || []).map(t => t.valeur == null ? `<div class="card tuile"><span class="eyebrow">${esc(t.libelle)}</span><b>n/d</b><span class="q">${nd(t.raison)}</span></div>` :
      `<div class="card tuile"><span class="eyebrow">${esc(t.libelle)}</span><b${at(t.source, t.date)}>${esc(t.texte)}</b><span class="q">${esc(t.qualificatif || "")}</span><span class="small">au ${ddm(t.date)}${t.variation_5 != null ? ` · ${sgn(t.variation_5, t.unite === "pb" ? 1 : 2, t.unite === "pb" ? " pb" : " %")} sur 5 séances` : ""}</span>${spark(t.serie_30 || [], 200, 34, (t.variation_5 ?? 0) >= 0 ? css("--up") : css("--down"), true)}</div>`).join("")}</div>
    <div class="card scroll"><table class="tbl" style="min-width:560px"><thead><tr><th>Actif</th><th>Situation</th><th>Interprétation</th></tr></thead><tbody>
      ${(x.classes || []).map(c => `<tr><td><b>${esc(c.actif)}</b></td><td><span class="chip ${c.situation === "Hausse" ? "up" : c.situation === "Baisse" ? "dn" : ""}" style="height:22px">${esc(c.situation)}</span> <span class="small">${c.variation_5 == null ? nd(c.raison) : esc(c.texte)}</span></td><td class="small" style="color:var(--ink-2)">${esc(c.interpretation)}</td></tr>`).join("")}</tbody></table></div>
    ${prose(S, "marches")}
    <div class="card pad" style="display:flex;flex-direction:column;gap:12px">
      <div class="sec-head"><h3>Ce que nous apprend le comportement des actifs</h3><span class="cite" title="${esc(m.seuils || "")}">mécanisme actif encadré</span></div>
      <div class="mech">${(m.mecanismes || []).map(k => `<div class="${k.actif ? "on" : ""}"><b>${esc(k.libelle)}</b><span class="${k.actif ? "" : "muted"}">${esc(k.lecture)}</span>
        ${(k.conditions || []).map(c => `<span class="mc9 ${c.remplie_5 || c.remplie_1 ? "ok" : ""}" title="${esc(c.chiffre)}">${c.remplie_5 || c.remplie_1 ? "✓" : "○"} ${esc(c.texte)}</span>`).join("")}</div>`).join("")}</div>
      <p style="margin:0;font-size:14px;color:var(--ink-2)">${esc(m.phrase || "")}</p></div>
    <details class="card"><summary class="pad" style="cursor:pointer">Tableau détaillé des marchés (30 séances)</summary>${s2(S, { s2: x }).split('<div class="prose">')[0]}</details>`;
}

function blocPays(p) {
  return `<div class="card pays9">
    <div class="pays9-l"><div class="sec-head"><h3>Faits du jour</h3><span class="chip ${p.classe}">${esc(p.biais)}</span></div>
      ${liste(p.faits)}
      ${(p.officiels || []).length ? `<div class="kn">${p.officiels.slice(0, 4).map(o => `<div><span>${esc(o.libelle)}</span><b${at(o.source, o.publie_le)}>${sgn(o.valeur, 1, " %")}</b><small>${esc(o.periode)}${o.precedent != null ? ` · précédent ${sgn(o.precedent, 1, " %")}` : ""}</small></div>`).join("")}</div>
        <span class="cite">Source : ${esc((p.officiels[0] || {}).source || "")}, publié le ${ddm((p.officiels[0] || {}).publie_le)}</span>` : ""}
      ${p.deliberations?.options?.length ? `<div class="cite">Délibérations du ${ddm(p.deliberations.date)} : « ${esc(p.deliberations.options.slice(-1)[0])} »${p.deliberations.suite?.length ? ` · « ${esc(p.deliberations.suite.slice(-1)[0])} »` : ""} <a href="${esc(p.deliberations.lien)}" target="_blank" rel="noopener">document officiel</a></div>` : ""}
      ${p.communique?.projections?.length ? `<div class="cite">Projection citée : « ${esc(p.communique.projections[0])} »</div>` : ""}
    </div>
    <div class="pays9-r"><span class="eyebrow">Pourquoi</span><p>${esc(p.pourquoi)}${p.ecart_2a?.valeur != null && p.devise !== "USD" ? ` Écart 2 ans USD − ${esc(p.devise)} : <b${at("calcul Python sur les rendements officiels", p.ecart_2a.date)}>${esc(p.ecart_2a.texte)}</b>.` : ""}</p>
      <span class="eyebrow">Chaîne de causalité</span><div class="chain">${(p.chaine || []).map((c, i) => `${i ? "<i>→</i>" : ""}<span${i === p.chaine.length - 1 ? ' class="end"' : ""}>${esc(c)}</span>`).join("")}</div>
      <span class="eyebrow">Risque de retournement</span><p>${esc(p.retournement)}${p.seuil ? ` <b>${esc(p.seuil.texte)}</b>.` : ""}</p>
      <div class="monbiais"><b>Mon biais :</b> ${esc(p.mon_biais)}</div></div></div>`;
}

function us94(p) {
  const u = p.usd || {}, pr = u.prix?.cpi || {}, co = pr.composantes || {}, ppi = u.prix?.ppi || {}, ob = u.obligations || {}, fe = u.fed || {};
  const L = u.prix?.libelles || {};
  return `<div class="cols2" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)">
      <div class="card"><div class="pad" style="padding-bottom:4px"><div class="sec-head"><h3>Inflation américaine · ${esc(pr.mois || "n/d")}</h3><a class="cite" href="${esc(u.prix?.lien_cpi || "#")}" target="_blank" rel="noopener">BLS</a></div></div>
        <table class="tbl"><thead><tr><th>Composante</th><th class="n">Sur le mois</th></tr></thead><tbody>
        ${["cpi", "core", "logement", "energie", "alimentation"].map(k => `<tr><td>${esc(L[k] || k)}</td><td class="n"><b${at(u.prix?.source, null)}>${co[k] == null ? "n/d" : sgn(co[k], 1, " %")}</b></td></tr>`).join("")}
        <tr><td>CPI sur un an</td><td class="n">${pr.annuel?.valeur != null ? sgn(pr.annuel.valeur, 1, " %") : nd(pr.annuel?.raison)}</td></tr>
        ${ppi.mois ? `<tr><td>PPI (${esc(ppi.mois)}, dernier publié)</td><td class="n">${sgn(ppi.composantes?.ppi, 1, " %")} · hors alimentation et énergie ${sgn(ppi.composantes?.ppi_core, 1, " %")}</td></tr>` : ""}</tbody></table>
        ${pr.annuel?.raison ? `<p class="cite pad" style="margin:0">Note : ${esc(pr.annuel.raison)}.</p>` : ""}</div>
      <div class="card"><div class="pad" style="padding-bottom:4px"><h3>Obligations américaines</h3></div>
        <table class="tbl"><thead><tr><th>Indicateur</th><th class="n">Niveau</th><th>Importance</th></tr></thead><tbody>
        <tr><td>US 2 ans</td><td class="n"><b${at(ob.source, ob.us2?.[0])}>${ob.us2 ? nf(ob.us2[1], 2) + " %" : "n/d"}</b></td><td class="small">Anticipations de politique monétaire</td></tr>
        <tr><td>US 10 ans</td><td class="n"><b${at(ob.source, ob.us10?.[0])}>${ob.us10 ? nf(ob.us10[1], 2) + " %" : "n/d"}</b></td><td class="small">Taux longs, croissance, prime de terme</td></tr>
        <tr><td>Pente 10 ans − 2 ans</td><td class="n"><b>${ob.pente == null ? nd("dates différentes") : sgn(ob.pente, 2, " pt")}</b></td><td class="small">Pente de la courbe (calcul Python)</td></tr></tbody></table>
        <p class="cite pad" style="margin:0">Au ${ddm(ob.us2?.[0])} · ${esc(ob.source || "")}</p></div></div>
    <div class="card pad" style="display:flex;flex-direction:column;gap:8px"><div class="sec-head"><h3>Fed</h3><span class="cite">${esc(fe.taux || "")} · ${esc(fe.decision || "")}${fe.votes ? " · vote " + esc(fe.votes) : ""} · prochaine décision ${ddm(fe.prochaine)}</span></div>
      ${fe.minorite ? `<p class="cite" style="margin:0">« ${esc(fe.minorite)} »</p>` : ""}
      ${(fe.declarations || []).length ? fe.declarations.map(d => `<p style="margin:0;font-size:13.5px"><b>${esc(d.personne)}</b> (${esc(d.fonction)}${d.statut ? ", " + esc(d.statut) : ""}), ${ddm(d.date)} : « ${esc(d.citation)} » <a class="cite" href="${esc(d.lien)}" target="_blank" rel="noopener">${esc(d.source)}</a> <span class="small">· ${esc(d.avertissement)}</span></p>`).join("") : '<p class="small" style="margin:0">Aucune déclaration de membre de la Fed dans les titres collectés aujourd\'hui.</p>'}
      <span class="eyebrow">Ce que je veux voir pour confirmer la force du dollar</span>${liste(u.ce_que_je_veux_voir)}</div>`;
}

function p94(S, F, sec) {
  const p = F[sec.id] || {};
  return (p.devise === "USD" ? us94(p) : "") + blocPays(p) + prose(S, sec.id);
}

function c94(S, F) {
  const x = F.commune || {};
  return `<div class="cc9">${(x.devises || []).map(d => `<div class="card"><h3>${esc(d.pays)} · ${esc(d.devise)} <span class="chip ${d.classe}">${esc(d.biais)}</span></h3>${(d.faits || []).map(f => `<p>${esc(f)}</p>`).join("")}<p class="small">${esc(d.pourquoi)}</p></div>`).join("")}</div>${prose(S, "commune")}`;
}

function en94(S, F) {
  const x = F.energie || {}, b = x.brent || {};
  return `<div class="tuiles" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="card tuile"><span class="eyebrow">Brent (prix spot EIA)</span><b${at(b.nature, b.date)}>${esc(b.texte || "n/d")}</b><span class="q">${esc(b.qualificatif || "")}</span><span class="small">au ${ddm(b.date)} · dollars par baril</span></div>
      <div class="card tuile"><span class="eyebrow">WTI (prix spot EIA)</span><b${at(x.wti?.nature, x.wti?.date)}>${esc(x.wti?.texte || "n/d")}</b><span class="small">au ${ddm(x.wti?.date)} · dollars par baril</span></div></div>
    ${b.alerte ? `<div class="alerte9">${esc(b.alerte)}</div>` : ""}
    <div class="card pad" style="display:flex;flex-direction:column;gap:8px"><div class="sec-head"><h3>Brent, 6 mois ($/baril)</h3><span class="cite">EIA, prix spot</span></div><div class="ch" id="v9Brent"></div>
      <span class="cite">${(x.fonds || []).map(f => `${esc(f.libelle)} : ${f.variation_5 == null ? "n/d" : sgn(f.variation_5, 1, " %")} sur 5 séances au ${ddm(f.date)} (${esc(f.nature)})`).join(" · ")}</span></div>
    ${prose(S, "energie")}
    <div class="cols2"><div class="card scroll"><table class="tbl"><thead><tr><th>Évolution du pétrole</th><th>Effet possible</th></tr></thead><tbody>${(x.effets || []).map(c => `<tr><td><b>${esc(c.cas)}</b></td><td>${esc(c.effet)}</td></tr>`).join("")}</tbody></table></div>
      <div class="card pad"><h3>Devises à surveiller</h3><ul class="chk" style="gap:8px">${(x.devises || []).map(c => `<li><span><b>${esc(c.devises)}</b> : ${esc(c.texte)}</span></li>`).join("")}</ul>
        ${(x.actualites || []).map(a => `<p class="small" style="margin:6px 0 0"><a href="${esc(a.lien || "#")}" target="_blank" rel="noopener">${esc(a.titre)}</a> · ${esc(a.source)}, ${heureActu(a.date)}</p>`).join("")}</div></div>`;
}

function a94(S, F) {
  const x = F.actions || {};
  return `<div class="card pad" style="display:flex;flex-direction:column;gap:10px"><div class="sec-head"><h3>Transmission possible</h3><span class="cite">Nasdaq 100 (ETF QQQ) ${x.qqq_5 == null ? "n/d" : sgn(x.qqq_5, 2, " %")} sur 5 séances au ${ddm(x.qqq_date)}${x.qualificatif_qqq ? " · " + esc(x.qualificatif_qqq) : ""}</span></div>
      <div class="chain">${(x.chaine || []).map((c, i) => `${i ? "<i>→</i>" : ""}<span${i === x.chaine.length - 1 ? ' class="end"' : ""}>${esc(c)}</span>`).join("")}</div>
      <p style="margin:0;font-size:13.5px;color:var(--ink-2)"><b>Attention :</b> ${esc(x.exception || "")}</p></div>
    ${(x.actualites || []).length ? `<div class="card pad news">${x.actualites.map(a => `<a href="${esc(a.lien || "#")}" target="_blank" rel="noopener"><span class="eyebrow">${esc(a.theme_libelle || "")}</span><b>${esc(a.titre)}</b><span class="small">${esc(a.source || "")} · ${heureActu(a.date)}</span></a>`).join("")}</div>` : ""}
    ${prose(S, "actions")}`;
}

function cal94(S, F) {
  const x = F.calendrier || {}, cle = x.cle;
  return `<div class="card scroll"><div class="pad" style="padding-bottom:4px"><h3>Aujourd'hui</h3></div><table class="tbl" style="min-width:560px"><thead><tr><th>Heure (Paris)</th><th>Publication</th><th class="n">Prévision</th><th class="n">Précédent</th><th class="n">Publié</th><th>Devise</th></tr></thead><tbody>
      ${(x.aujourdhui || []).length ? x.aujourdhui.map(e => `<tr><td>${esc(e.heure || "")}</td><td><b>${esc(e.evenement)}</b>${e.impact === "fort" ? ' <span class="chip dn" style="height:20px">fort</span>' : ""}</td><td class="n">${esc(e.consensus || "—")}</td><td class="n">${esc(e.precedent || "—")}</td><td class="n"><b>${esc(e.publie || "—")}</b></td><td>${esc(e.devise)}</td></tr>`).join("") : '<tr><td colspan="6" class="muted">Aucune publication forte ou moyenne aujourd\'hui.</td></tr>'}</tbody></table></div>
    ${cle ? `<div class="card pad" style="display:flex;flex-direction:column;gap:10px"><h3>Interprétation : ${esc(cle.cle || cle.evenement)}</h3><div class="grid4">${(cle.lire?.cas || []).map(c => `<div style="background:var(--${c.classe === "up" ? "up-soft" : c.classe === "dn" ? "down-soft" : c.classe === "warn" ? "warn-soft" : "surface-2"})"><b>${esc(c.si)}</b><span>${esc(c.lecture)}</span></div>`).join("")}</div></div>` : ""}
    <div class="card scroll"><div class="pad" style="padding-bottom:4px"><h3>Semaine prochaine · à partir du ${ddm(x.lundi_prochain)}</h3></div><table class="tbl" style="min-width:460px"><thead><tr><th>Jour</th><th>Événement</th><th>Devise</th></tr></thead><tbody>
      ${(x.semaine_prochaine || []).length ? x.semaine_prochaine.map(e => `<tr><td>${esc(e.jour)} ${esc(e.heure || "")}</td><td>${esc(e.evenement)}</td><td>${esc(e.devise)}</td></tr>`).join("") : '<tr><td colspan="3" class="muted">Agenda de la semaine prochaine pas encore publié.</td></tr>'}</tbody></table></div>
    ${prose(S, "calendrier")}<p class="cite">${esc(x.a_ne_pas_surinterpreter || "")}</p>`;
}

function cl94(S, F) {
  const x = F.classement || {}, d = x.devises || [];
  const mx = Math.max(...d.map(l => Math.abs(l.score)), 0.5);
  return `<div class="card pad"><div class="rank">${d.map(l => `<div class="rw"><span class="n">${l.rang}</span><b class="c">${esc(l.devise)}</b><span class="chip ${l.classe}" style="justify-self:start">${esc(l.biais)}</span>
      <span style="color:var(--ink-2);font-size:13.5px" title="${esc(l.composantes.filter(c => !c.nd).map(c => c.texte + " (" + sgn(c.valeur, 2) + ")").join(" · "))}">${esc(l.moteur)}</span>
      <div style="display:flex;flex-direction:column;gap:3px"><div class="bar"><i style="${l.score >= 0 ? "left:50%" : "right:50%"};width:${Math.abs(l.score) / mx * 50}%;background:${l.score >= 0 ? "var(--up)" : "var(--down)"}"></i></div><span class="small" style="text-align:right">score ${sgn(l.score, 2)} · ${l.n_composantes} composantes</span></div></div>`).join("")}</div>
      ${(x.a_part || []).map(a => `<p class="small" style="margin:8px 0 0"><b>${esc(a.devise)}</b> classé à part : ${esc(a.raison)}.</p>`).join("")}</div>
    <div class="card pad"><h3 style="margin-bottom:6px">Les divergences les plus intéressantes</h3><ul class="chk">${(x.divergences || []).map(v => `<li><span><b>${esc(v.forte)} contre ${esc(v.faible)}</b> (écart de score ${sgn(v.ecart, 2)}) : ${esc(v.raison)}</span></li>`).join("")}</ul></div>
    ${prose(S, "classement")}<p class="cite">${esc(x.methode || "")} ${esc(x.mention || "")}</p>`;
}

function pa94(S, F) {
  const x = F.paires || {}, t = x.technique || {};
  return s9(S, { s9: x }).replace(prose(S, "s9"), "") + (t.disponible ? s10(S, { s10: t }).replace(prose(S, "s10"), "") : "") + prose(S, "paires");
}

function sc94(S, F) {
  const x = F.scenarios || {};
  return `<div class="scen3">${(x.scenarios || []).map((sc, i) => `<div class="card ${"abc"[i]}"><span class="chip ${sc.classe}" style="align-self:flex-start">${esc(sc.chip)}</span><h3>${esc(sc.lettre)} · ${esc(sc.titre)}</h3>
      <span class="lab">Conditions · ${sc.remplies ?? "n/d"} sur ${sc.total ?? "n/d"}</span>${liste((sc.conditions || []).map(c => ({ texte: c.texte, remplie: !!c.remplie })))}
      <span class="lab">Conséquences</span><ul>${(sc.consequences || []).map(c => `<li>${esc(c)}</li>`).join("")}<li>${esc(sc.or || "")}</li></ul></div>`).join("")}</div>
    ${prose(S, "scenarios")}`;
}

function me94(S, F) {
  const x = F.methode || {};
  return `<div class="card scroll"><table class="tbl" style="min-width:420px"><thead><tr><th>Unité de temps</th><th>Rôle</th></tr></thead><tbody>${(x.unites || []).map(u => `<tr><td><b>${esc(u.unite)}</b></td><td>${esc(u.role)}</td></tr>`).join("")}</tbody></table></div>
    <div class="cols2" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)">
      <div class="card pad"><h3>Confirmations pour un scénario haussier du dollar</h3>${liste(x.confirmations_haussier)}</div>
      <div class="card pad"><h3>Confirmations pour un scénario baissier du dollar</h3>${liste(x.confirmations_baissier)}</div></div>
    <div class="card pad"><h3 style="margin-bottom:6px">Types de risque</h3><ul class="chk">${(x.risques || []).map(r => `<li><span><b>${esc(r.type)}</b> : ${esc(r.texte)}</span></li>`).join("")}</ul><p class="cite" style="margin:8px 0 0">${esc(x.mention || "")}</p></div>
    ${prose(S, "methode")}`;
}

function co94(S, F) {
  const x = F.conclusion || {};
  return `<div class="card concl"><span class="eyebrow">Conclusion</span><h2>Mon biais général : ${esc(x.biais || "n/d")}</h2>
      <ol>${(x.priorites || []).map(p => `<li>${esc(p)}</li>`).join("")}</ol>
      ${(S.textes?.conclusion || []).map(p => `<p style="margin:0;opacity:.88">${esc(p)}</p>`).join("")}
      <div class="adv">${esc(x.prudence || "")}</div></div>
    <div class="card scroll"><div class="pad" style="padding-bottom:4px"><h3>Les cinq indicateurs à suivre en priorité</h3></div><table class="tbl" style="min-width:520px"><thead><tr><th>Indicateur</th><th class="n">Valeur</th><th>Ce que je veux observer</th></tr></thead><tbody>
      ${(x.indicateurs || []).map(i => `<tr><td><b>${esc(i.indicateur)}</b></td><td class="n"><b>${esc(i.valeur)}</b><small class="small" style="display:block">${i.date ? "au " + ddm(i.date) : ""}</small></td><td class="small">${esc(i.observer)}</td></tr>`).join("")}</tbody></table></div>
    <div class="sec-head"><h3>Sources</h3><span class="cite">publications officielles, données et articles cités</span></div>
    <div class="srcs">${(x.sources || []).map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener"><b>${esc(s.nom)}</b><small>${esc(s.quoi)}</small></a>`).join("")}</div>`;
}

const RENDUS94 = { exec: (S, F) => prose(S, "exec") + e94(S, F), marches: m94, etats_unis: p94, pays: p94, commune: c94, energie: en94,
                   actions: a94, calendrier: cal94, classement: cl94, paires: pa94, scenarios: sc94, methode: me94, conclusion: co94 };


/* ------------------------------------------------------------------ écran */
export async function ecranSyntheseV9(section, S) {
  const F = S.faits || {}, v94 = S.structure === "v9.4", x1 = (v94 ? F.exec : F.s1) || {};
  const premierTexte = (S.textes?.[v94 ? "exec" : "s1"] || [])[0];
  const point = v94 ? `<p><b>Facteur dominant :</b> ${esc(x1.facteur_dominant || "n/d")}.</p><hr><p><b>Risque majeur :</b> ${esc(x1.risque_majeur?.texte || "n/d")}.</p><hr>`
                    : `<p><b>Point déterminant :</b> ${esc(x1.point_determinant || "n/d")}.</p><hr>`;
  const g = S.genere_le ? new Date(S.genere_le) : null;
  const heure = g && !isNaN(g) ? g.toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit" }) : "n/d";
  const mots = Object.values(S.textes || {}).flat().join(" ").split(/\s+/).length;
  const racine = h("div", "v9");
  racine.dataset.sources = store.get(CLE_SOURCES) === "on" ? "on" : "off";
  racine.innerHTML = `
    <div class="card hero9">
      <div style="display:flex;flex-direction:column;gap:16px">
        <div class="meta"><span class="chip">Analyse globale</span><span class="chip">Forex · macro · taux</span><span class="chip acc">${esc(S.semaine || "")}</span></div>
        <h1>${esc(S.titre || "Rapport macroéconomique et Forex")}</h1>
        <p class="lede">${esc(S.jour || "")}. ${esc(premiere(premierTexte))}</p>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><button class="switch" type="button" id="v9Src" aria-pressed="${racine.dataset.sources === "on"}" title="Montre la source et la date de chaque chiffre"><i></i><span>Sources</span></button>
          <span class="cite">Généré à ${heure} (Paris) · lecture ${Math.max(3, Math.round(mots / 220))} min · ${S.redige_par?.length ? "rédigé par " + esc(S.redige_par.join(", ")) + ", chaque nombre vérifié en Python" : "rédaction automatique (Python)"}${S.redaction_automatique?.length && S.redige_par?.length ? ` · ${S.redaction_automatique.length} section(s) en rédaction automatique` : ""}</span></div>
      </div>
      <div class="diag">
        <span class="eyebrow">Diagnostic macro du jour</span>
        <b class="big">${esc(x1.biais || "n/d")}</b>
        <p><b>Régime :</b> ${esc(x1.regime || "n/d")}.</p><hr>
        ${point}
        <p style="font-size:12.5px">${esc(S.mention || "Aide à la décision : biais conditionnels, jamais des ordres.")}</p>
      </div>
    </div>
    <div class="legend9"><span><span class="src-tag ok" style="display:inline-block">source</span> chiffres soulignés : source et date au survol</span><span><span class="src-tag new" style="display:inline-block">n/d</span> donnée absente : la raison au survol</span></div>
    <div class="rep"><nav class="toc" id="v9Toc" aria-label="Sommaire de la synthèse"></nav><article class="r" id="v9Art"></article></div>
    <div id="v9Detail" style="margin-top:28px"></div>`;
  section.replaceChildren(racine);
  const art = $("#v9Art", racine);
  for (const sec of S.sections || []) {
    const el = h("section", "rs"); el.id = "v9-" + sec.id; el.dataset.t = sec.court;
    let corps;
    try {
      corps = v94 ? (RENDUS94[sec.type] ? RENDUS94[sec.type](S, F, sec) : prose(S, sec.id))
                  : (sec.id === "s1" ? prose(S, "s1") : "") + (RENDUS[sec.id] ? RENDUS[sec.id](S, F) : prose(S, sec.id));
    }
    catch (e) { console.error(e); corps = `<div class="sec-err">Section indisponible : <code>${esc(e.message)}</code></div>${prose(S, sec.id)}`; }
    el.innerHTML = (sec.id === "s13" || sec.id === "conclusion" ? "" : entete(S, sec)) + erreur(sec) + corps;
    art.appendChild(el);
  }
  // Bouton « Sources » (ancien « Origine des données ») : mémorisé sur l'appareil
  $("#v9Src", racine).onclick = e => {
    const on = racine.dataset.sources !== "on";
    racine.dataset.sources = on ? "on" : "off"; e.currentTarget.setAttribute("aria-pressed", String(on)); store.set(CLE_SOURCES, on ? "on" : "off");
  };
  sommaire(racine);
  $("#v9Detail", racine).appendChild(blocDetaille("Rapport détaillé (version précédente)", "sections longues, bilan, risque, archives", async () => {
    const m = await import("./rapport.js"); return m.pageRapport();
  }));
  await graphiques(F);
}

function sommaire(racine) {
  const S = [...racine.querySelectorAll(".rs")], toc = $("#v9Toc", racine);
  toc.innerHTML = S.map((s, i) => `<a href="#synthese" data-i="${i}"><span>${i + 1}</span><span>${esc(s.dataset.t)}</span></a>`).join("") + '<div class="prog"><i id="v9Prog"></i></div>';
  toc.querySelectorAll("a").forEach(a => a.onclick = ev => { ev.preventDefault(); S[+a.dataset.i].scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }); });
  const entete = document.querySelector("header.top");
  const haut = () => document.documentElement.style.setProperty("--haut-entete", (entete?.offsetHeight || 120) + "px");
  haut(); addEventListener("resize", haut, { passive: true });
  let courant = -1;
  const espion = () => {
    if (!racine.isConnected || !racine.closest(".screen.on")) return;
    const lim = (entete?.offsetHeight || 120) + 80;
    let cur = 0; S.forEach((s, i) => { if (s.getBoundingClientRect().top < lim) cur = i; });
    if (cur !== courant) {
      courant = cur;
      toc.querySelectorAll("a").forEach((a, i) => a.classList.toggle("on", i === cur));
      const a = toc.querySelectorAll("a")[cur];   // téléphone : le sommaire horizontal suit la lecture
      if (a && toc.scrollWidth > toc.clientWidth) toc.scrollTo({ left: a.offsetLeft - 16, behavior: "auto" });
    }
    const d = document.documentElement, p = d.scrollTop / Math.max(1, d.scrollHeight - innerHeight);
    const pi = $("#v9Prog", racine); if (pi) pi.style.width = Math.round(p * 100) + "%";
  };
  addEventListener("scroll", espion, { passive: true });
  espion();
}

async function graphiques(F) {
  const b = F.s5?.brent || (F.energie?.brent ? { ...F.energie.brent, disponible: !!(F.energie.brent.serie_6m || []).length } : null);
  const boite = document.getElementById("v9Brent");
  if (boite && b?.disponible) {
    const series = [{ l: "Brent EIA", p: b.serie_6m || [], couleur: "--c3" }];
    if (b.estimation?.points?.length) series.push({ l: "Estimation ETF BNO", p: [b.serie_6m[b.serie_6m.length - 1], ...b.estimation.points], couleur: "--warn" });
    await graphique(boite, series, 2, { handleScroll: false, handleScale: false });
  } else if (boite) boite.innerHTML = `<div class="empty">${nd(b?.raison)}</div>`;
  const t = F.s10 || F.paires?.technique;
  const bt = document.getElementById("v9Tech");
  if (bt && t?.disponible) {
    try {
      const { graphiquePaire } = await import("./paire_graphique.js");
      await graphiquePaire(bt, document.getElementById("v9TechRsi"), t.bougies, { dec: t.decimales, zones: t.zones, lignes: t.lignes, rsi: null, divergences: [] });
    } catch (e) { console.error(e); bt.innerHTML = `<div class="empty">Graphique indisponible : ${esc(e.message)}</div>`; }
    const be = document.getElementById("v9Ecart");
    if (be && t.ecart?.points?.length) await graphique(be, [{ l: "Écart (pb)", p: t.ecart.points, couleur: "--c2" }], 0, { handleScroll: false, handleScale: false });
    else if (be) be.innerHTML = `<div class="empty">${nd(t.ecart?.raison)}</div>`;
  }
}
