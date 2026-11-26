/* Lot V13 — le documentaire hebdomadaire de l'onglet « 8 engrenages » (maquette_v13_engrenages_documentaire.html).
   Données : docs/data/documentaire.json (semaine en cours) et docs/data/documentaire/AAAA-Sxx.json (12 semaines), calculées
   et rédigées en Python (core/documentaire.py) : le JavaScript affiche seulement. Sommaire collant avec l'état de chaque
   moteur et la progression de lecture ; position de lecture mémorisée dans le navigateur (« Reprendre là où j'en étais ») ;
   graphiques Lightweight Charts (vendor/) sans logo, redessinés au changement de thème ; attribution en légende. */
import { h, esc, ddm, nd, spark, store, graphique, retirerGraphique, rethemer, optionsTheme } from "./v7_commun.js";

const JOURS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const jourCourt = iso => `${JOURS[new Date(String(iso).slice(0, 10) + "T12:00:00Z").getUTCDay()]} ${ddm(iso)}`;
const frTxt = v => String(v ?? "n/d").replace(/(\d)\.(\d)/g, "$1,$2").replace(/(\d)%/g, "$1 %").replace(/^-(?=\d)/, "−");
const nbsp = t => String(t).replace(/(\d) (%|pb|\$|pts)/g, "$1&nbsp;$2");
const fmt = (v, d) => v == null ? "n/d" : (v < 0 ? "−" : "") + Math.abs(v).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
const pillEtat = e => e?.code === "franchi" ? '<span class="pill p">Seuil franchi</span>' : e?.code === "proche" ? '<span class="pill w">Près du seuil</span>'
  : e?.code === "non" ? '<span class="pill n">Calme</span>' : '<span class="pill n">n/d</span>';
const pillDir = e => e?.direction ? `<span class="pill ${e.classe === "up" ? "p" : e.classe === "dn" ? "c" : "n"}">${esc(e.direction)}</span>` : "";
/* Pastille de surprise : le texte dit le sens (au-dessus, en dessous), la couleur dit si c'est favorable à la devise
   (un chômage au-dessus du consensus est en rouge). */
const pastille = (p, fav) => p === "conforme" ? '<span class="pill n">conforme</span>' : p === "sans consensus" || !p ? '<span class="pill n">sans consensus</span>'
  : `<span class="pill ${fav === true ? "p" : fav === false ? "c" : "n"}" title="${fav === true ? "favorable à la devise" : fav === false ? "défavorable à la devise" : ""}">${esc(p)}</span>`;
const effetPill = e => e === "soutien" ? '<span class="pill p">▲ Soutien</span>' : e === "pression" ? '<span class="pill c">▼ Pression</span>'
  : e === "neutre" ? '<span class="pill n">Neutre</span>' : '<span class="pill n">Non mesuré</span>';
const ATTRIBUTION = 'graphique <a href="https://www.tradingview.com/" target="_blank" rel="noopener">TradingView Lightweight Charts</a>';
const CLE_POS = sem => `fxdesk-doc-position-${sem}`;
/* Options des graphiques du documentaire : thème courant (fond, axes) et pas de logo (attribution en légende). */
const sansLogo = () => ({ layout: { ...optionsTheme().layout, attributionLogo: false }, handleScroll: false, handleScale: false });

/* Lot V15 : glossaire. Chaque mot du glossaire est souligné en pointillé à sa première apparition dans un bloc de texte ;
   la définition s'affiche dans une bulle au survol ou au toucher (élément focalisable). */
let GLOSS = {};
const reGloss = () => Object.keys(GLOSS).length ? new RegExp(`(^|[^\\wÀ-ÿ])(${Object.keys(GLOSS).sort((a, b) => b.length - a.length)
  .map(m => m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})(s?)(?=[^\\wÀ-ÿ]|$)`, "gi") : null;
function gloss(html) {
  const re = reGloss(); if (!re) return html;
  const vus = new Set();
  return html.replace(re, (tout, avant, mot, s) => {
    const cle = Object.keys(GLOSS).find(k => k.toLowerCase() === mot.toLowerCase());
    if (!cle || vus.has(cle)) return tout;
    vus.add(cle);
    return `${avant}<span class="gl" tabindex="0" data-def="${esc(GLOSS[cle])}">${mot}${s}</span>`;
  });
}

function recitHtml(r, faits, court = false) {
  if (r && (r.paragraphes || []).length) {
    const paras = r.paragraphes.map((p, i) => `<p class="${i === 0 && !court ? "drop" : ""}">${gloss(nbsp(esc(p)))}</p>`);
    if (r.exergue && paras.length > 1) paras.splice(Math.min(2, paras.length - 1), 0, `<p class="pull">${nbsp(esc(r.exergue))}</p>`);
    const surv = (r.a_surveiller || []).length ? `<div class="surv"><b>À surveiller</b><ul>${r.a_surveiller.map(x => `<li>${gloss(nbsp(esc(x)))}</li>`).join("")}</ul></div>` : "";
    const qui = String(r.redige_par || "une IA");
    const quand = r.redige_le ? ` le ${r.redige_le.slice(8, 10)}/${r.redige_le.slice(5, 7)} à ${r.redige_le.slice(11, 16)} UTC` : "";
    return `<div class="prose">${paras.join("")}</div>${surv}
      ${r.repris ? `<span class="par repris">${esc(r.mention || "Récit repris d'un jour précédent.")}</span>` : ""}
      <span class="par">Rédigé par ${esc(qui)}${quand} à partir des faits calculés en Python ; nombres contrôlés (${r.mots || "n/d"} mots).</span>`;
  }
  const l = faits || [];
  return `<div class="faits"><span class="eyebrow">Les faits de la semaine</span>${l.length ? `<ul>${l.map(x => `<li>${gloss(nbsp(esc(x)))}</li>`).join("")}</ul>` : "<p>n/d</p>"}
    <span class="small">Le récit sera écrit au prochain passage du modèle.</span></div>`;
}

export function rendreDocumentaire(hote, D, options = {}) {
  hote.innerHTML = "";
  if (!D || !D.chapitres) {
    hote.innerHTML = `<div class="erreur">Documentaire indisponible : ${esc(options.raison || "documentaire.json absent ou illisible")}. La vue tableau reste disponible.</div>`;
    return { allerChapitre: () => false, detruire: () => {} };
  }
  const chapitres = Object.values(D.chapitres).sort((a, b) => a.numero - b.numero);
  const toc = h("nav", "toc"); toc.setAttribute("aria-label", "Chapitres du documentaire");
  const art = h("article", "d");
  const doc = h("div", "doc"); doc.append(toc, art); hote.appendChild(doc);

  // ---- en-tête
  const pos = (() => { try { return JSON.parse(store.get(CLE_POS(D.semaine)) || "null"); } catch (e) { return null; } })();
  art.insertAdjacentHTML("beforeend", `<header class="hero"><div class="meta"><span class="pill a">Documentaire hebdomadaire</span><span class="pill n">${esc(D.titre_semaine)}</span>
      <span class="pill n">Lecture : ${D.lecture_min} min</span><span class="pill ${D.statut === "complète" ? "p" : "w"}">${D.statut === "complète" ? "Semaine complète" : `En cours : jusqu'au ${esc(jourCourt(D.fin_donnees))}`}</span></div>
    <h1>La semaine des marchés, moteur par moteur</h1>
    <p class="dek">Un dossier complet, à lire dans la journée : ce qui s'est passé sur les marchés cette semaine, expliqué par les 8 engrenages qui font bouger les devises, avec leurs indicateurs à jour, leurs graphiques et les risques de la semaine prochaine.</p>
    <span class="small">Données du pipeline arrêtées au ${esc(ddm(D.fin_donnees))}, générées le ${esc(ddm(D.genere_le))} · ${esc(D.redaction?.ligne || "")} · chaque chiffre porte sa date et sa source · aide à la décision, aucun ordre</span>
    ${pos && pos.chap ? `<button type="button" class="btn reprendre" id="dzReprendre">Reprendre là où j'en étais (${esc(pos.titre || pos.chap)})</button>` : ""}</header>`);

  // ---- chapitre 0 : la semaine en bref
  GLOSS = D.glossaire || {};
  const tj = D.theme?.jour_par_jour || [];
  art.insertAdjacentHTML("beforeend", `<section class="chap" id="c0" data-t="La semaine en bref"><div class="chap-h"><span class="num">0</span><div><h2>La semaine en bref</h2><p>Le thème, son évolution jour par jour, puis ce que dit chaque moteur en une ligne</p></div></div>
    <div class="sub">${recitHtml(D.bref_recit, D.bref_faits_semaine, true)}</div>
    <div class="box"><span class="eyebrow">Thème de la semaine</span><b style="font-family:var(--f-display);font-size:34px;font-weight:500;line-height:1.1">${esc(D.theme?.titre || "n/d")}</b>
      <p>${D.theme?.alignes ?? "n/d"} moteurs sur ${D.theme?.evaluables ?? "n/d"} vont dans le même sens. ${esc(String(D.theme?.explication || "").replace(/^Moteurs orientés : /, "Les moteurs orientés : "))}</p>
      ${tj.length ? `<div class="tj">${tj.map(t => `<span><b>${esc(jourCourt(t.date))}</b> · ${esc(t.titre || "n/d")} · ${t.alignes ?? "n/d"} moteurs alignés${t.direction ? " · " + esc(t.direction) : ""}</span>`).join("")}</div>` : '<p class="small">Thème jour par jour : archive contexte/ absente pour cette semaine.</p>'}</div>
    <div class="week5">${(D.bref || []).map(b => `<a href="#engrenages/c${b.numero}" data-c="${b.numero}"><span class="eyebrow">${b.numero} · ${"★".repeat(b.importance)}</span><b>${esc(b.nom)}</b>${pillEtat(b)}
      <span class="small">${esc(b.libelle || "")} : ${esc(b.valeur || "n/d")}</span>${b.plus_bouge ? `<span class="small">A le plus bougé : <b>${esc(b.plus_bouge.libelle)}</b> ${esc(b.plus_bouge.texte)}, ${esc(b.plus_bouge.variation)}</span>` : ""}</a>`).join("")}</div></section>`);

  // ---- un chapitre par moteur
  for (const c of chapitres) art.appendChild(chapitre(c, D));

  // ---- chapitre final, puis glossaire
  art.appendChild(chapitreFinal(D));
  const g = Object.entries(GLOSS);
  if (g.length) art.insertAdjacentHTML("beforeend", `<details class="gloss card pad"><summary><b>Glossaire</b> <span class="small">${g.length} mots expliqués simplement</span></summary>
    <dl>${g.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></details>`);
  art.insertAdjacentHTML("beforeend", `<p class="small">Documentaire de la ${esc(D.titre_semaine.toLowerCase())} · sources : ${esc(Object.values(D.sources || {}).join(" ; "))} · ${esc(D.note || "")}</p>`);

  // ---- sommaire et progression
  const CS = [...art.querySelectorAll(".chap")];
  toc.innerHTML = CS.map(s => { const k = s.id.slice(1), c = D.chapitres[k];
    return `<a href="#engrenages/${s.id}" data-c="${k}"><span class="n">${k === "9" ? "→" : k}</span><span>${esc(s.dataset.t)}${c ? `<span class="st ${c.etat?.code === "franchi" ? "pos" : c.etat?.code === "proche" ? "" : "muted"}" style="${c.etat?.code === "proche" ? "color:var(--warn)" : ""}">${esc(c.etat?.etat || "")}</span>` : ""}</span></a>`; }).join("")
    + '<div class="bar" aria-hidden="true"><i></i></div>';
  // Premier affichage (#engrenages/c3) : l'écran n'est visible qu'après sa construction, d'où un second défilement à l'image suivante
  const allerChapitre = (k, comportement = "smooth") => { const s = art.querySelector(`#c${k}`); if (!s) return false;
    s.scrollIntoView({ behavior: comportement, block: "start" });
    if (comportement === "auto") requestAnimationFrame(() => requestAnimationFrame(() => s.scrollIntoView({ behavior: "auto", block: "start" })));
    return true; };
  hote.querySelectorAll("a[data-c]").forEach(a => a.addEventListener("click", e => { e.preventDefault(); history.replaceState(null, "", `#engrenages/c${a.dataset.c}`); allerChapitre(a.dataset.c); }));
  hote.querySelector("#dzReprendre")?.addEventListener("click", () => { const s = art.querySelector(`#c${pos.chap}`); if (!s) return;
    window.scrollTo({ top: s.getBoundingClientRect().top + scrollY + (pos.dans || 0), behavior: "smooth" }); });
  let minut = null;
  const espion = () => {
    if (!hote.isConnected || !hote.offsetParent) return;
    let cur = 0; CS.forEach((s, i) => { if (s.getBoundingClientRect().top < 140) cur = i; });
    toc.querySelectorAll("a").forEach((a, i) => a.classList.toggle("on", i === cur));
    const r = art.getBoundingClientRect(), total = Math.max(1, r.height - innerHeight);
    toc.querySelector(".bar i").style.width = Math.max(0, Math.min(100, Math.round(-r.top / total * 100))) + "%";
    clearTimeout(minut);
    minut = setTimeout(() => {   // position de lecture : chapitre courant et décalage dans le chapitre (navigateur seulement)
      const s = CS[cur]; if (!s || cur === 0 && s.getBoundingClientRect().top > 0) return;
      store.set(CLE_POS(D.semaine), JSON.stringify({ chap: s.id.slice(1), titre: s.dataset.t, dans: Math.max(0, -s.getBoundingClientRect().top) }));
    }, 400);
  };
  addEventListener("scroll", espion, { passive: true }); espion();

  // ---- graphiques (Lightweight Charts, sans logo ; attribution en légende), redessinés au changement de thème
  const charts = [];
  const dessiner = async () => {
    for (const el of hote.querySelectorAll(".ch[data-k]")) {
      const g = el._g; if (g) retirerGraphique(g);
      const s = JSON.parse(el.dataset.p || "[]"), d = +el.dataset.d;
      const opts = sansLogo();
      try { el._g = await graphique(el, [{ p: s, couleur: "--accent" }], d, opts); if (el._g) { el._g.sansLogo = true; charts.push(el._g); } }
      catch (e) { el.innerHTML = spark(s.map(q => q[1]), 600, 200, "var(--accent)", true).replace("<svg", '<svg style="width:100%;height:100%"'); }
    }
  };
  // les graphiques ne sont dessinés qu'à l'approche de leur chapitre (page longue)
  const obs = "IntersectionObserver" in window ? new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting && !en.target._g) { obs.unobserve(en.target); dessinerUn(en.target); } }), { rootMargin: "600px" }) : null;
  async function dessinerUn(el) {
    const s = JSON.parse(el.dataset.p || "[]"), d = +el.dataset.d;
    try { el._g = await graphique(el, [{ p: s, couleur: "--accent" }], d, sansLogo()); if (el._g) { el._g.sansLogo = true; charts.push(el._g); } }
    catch (e) { el.innerHTML = spark(s.map(q => q[1]), 600, 200, "var(--accent)", true).replace("<svg", '<svg style="width:100%;height:100%"'); }
  }
  if (obs) hote.querySelectorAll(".ch[data-k]").forEach(el => obs.observe(el)); else dessiner();
  const retheme = () => { rethemer(); for (const g of charts) { try { g.c.applyOptions({ layout: { ...optionsTheme().layout, attributionLogo: false } }); } catch (e) { /* retiré */ } } };
  const mq = matchMedia("(prefers-color-scheme: dark)"); mq.addEventListener?.("change", retheme);
  const mo = new MutationObserver(retheme); mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return {
    allerChapitre,
    detruire: () => { removeEventListener("scroll", espion); mq.removeEventListener?.("change", retheme); mo.disconnect(); obs?.disconnect(); charts.forEach(retirerGraphique); },
  };
}

function chapitre(c, D) {
  const s = h("section", "chap"); s.id = `c${c.numero}`; s.dataset.t = c.nom;
  const L = c.comprendre || {};
  if (c.erreur) {
    s.innerHTML = `<div class="chap-h"><span class="num">${c.numero}</span><div><h2>${esc(c.nom)}</h2></div></div><div class="erreur">${esc(c.erreur)}</div>${comprendre(L, c)}`;
    return s;
  }
  s.innerHTML = `<div class="chap-h"><span class="num">${c.numero}</span><div><h2>${esc(c.nom)}</h2><p>${esc(c.question)}</p></div></div>
    <div class="badges"><span class="stars" title="importance pour le change">${"★".repeat(L.importance || 0)}${"☆".repeat(5 - (L.importance || 0))}</span><span class="small">importance pour le change</span>${pillEtat(c.etat)}${pillDir(c.etat)}</div>
    <div class="sub"><h3>Le récit de la semaine</h3>${recitHtml(c.recit, c.faits_semaine)}</div>
    ${comprendre(L, c)}
    ${graphiques(c)}
    ${indicateurs(c)}
    ${c.numero === 3 ? surprises(c, D) : ""}
    ${publications(c)}
    ${actualite(c)}
    ${devises(c)}
    ${risques(c)}`;
  return s;
}

function comprendre(L, c) {
  const liste = v => Array.isArray(v) ? `<ul>${v.map(x => `<li>${gloss(esc(x))}</li>`).join("")}</ul>` : `<p>${gloss(esc(v || ""))}</p>`;
  return `<div class="sub"><h3>Comprendre ce moteur</h3><div class="learn15">
    <p class="une"><b>En une phrase :</b> ${gloss(esc(L.une_phrase || ""))}</p>
    <p><b>Comment ça marche :</b> ${gloss(esc(L.comment || ""))}</p>
    <details><summary>Ce qu'on regarde, un exemple, ce que ça fait aux devises, le piège</summary>
      <div class="plus"><div><b class="t">Ce qu'on regarde</b>${liste(L.regarde)}</div>
        <div><b class="t">Un exemple</b>${liste(L.exemple)}</div>
        <div><b class="t">Ce que ça fait aux devises</b>${liste(L.effets)}</div>
        <div class="note"><b>Le piège :</b> ${gloss(esc(L.piege || ""))}</div></div></details>
  </div></div>`;
}

function graphiques(c) {
  const g = (c.graphiques || []);
  if (!g.length) return "";
  return `<div class="sub"><h3>Les graphiques</h3><div class="charts">${g.map(x => x.raison ? `<figure class="card fig"><h4>${esc(x.titre)}</h4><p class="small">${nd(x.raison)} ${esc(x.raison)}</p></figure>`
    : `<figure class="card fig"><h4>${esc(x.titre)}</h4><div class="v"><b>${fmt(x.derniere[1], x.decimales)}</b><span class="${(x.variation_semaine?.valeur || 0) > 0 ? "pos" : (x.variation_semaine?.valeur || 0) < 0 ? "neg" : "muted"}" style="font-weight:600;font-size:13px">${esc(x.variation_semaine?.texte || x.variation_semaine?.raison || "")}</span></div>
      <div class="ch" data-k="${esc(x.cle)}" data-d="${x.decimales}" data-p='${esc(JSON.stringify(x.points))}' role="img" aria-label="${esc(x.titre)} sur 6 mois"></div>
      <figcaption>${esc(x.legende)} · dernière valeur le ${esc(ddm(x.derniere[0]))} · 6 mois · ${esc(x.source || "")} · ${ATTRIBUTION}</figcaption></figure>`).join("")}</div></div>`;
}

function indicateurs(c) {
  const l = c.indicateurs || [];
  if (!l.length) return `<div class="sub"><h3>Les indicateurs à jour, expliqués</h3><p class="small">${nd("aucun chiffre clé publié pour ce moteur")} aucun chiffre clé publié pour ce moteur.</p></div>`;
  return `<div class="sub"><h3>Les indicateurs à jour, expliqués</h3><div class="card pad ind">${l.map(x => `<div><div class="nm"><b>${esc(x.libelle)}</b><small>${esc(x.source || "")}</small></div>
    <div class="val"><b>${x.texte && x.texte !== "n/d" ? esc(x.texte) : nd(x.raison)}</b><small>${esc(x.variation_semaine?.texte || x.variation_semaine?.raison || "")}</small><small>${esc(x.variation_4s || "")}</small><small>${x.date ? esc(ddm(String(x.date).slice(0, 10))) : ""}</small>
      ${x.percentile_5a != null ? `<div class="pc" title="position sur 5 ans : du plus bas (à gauche) au plus haut (à droite)"><i style="left:${x.percentile_5a}%"></i></div>` : ""}</div>
    ${(x.points || []).length > 2 ? spark(x.points, 120, 34, "var(--accent)", true) : "<span></span>"}
    <div class="exp"><b style="color:var(--ink);font-weight:600">Ce que c'est :</b> ${gloss(esc(x.ce_que_cest || "définition à compléter"))}${x.lecture_niveau ? " " + esc(x.lecture_niveau) : ""}${x.lecture_jour && x.lecture_jour !== x.texte ? ` <i>${esc(x.lecture_jour)}</i>` : ""}</div></div>`).join("")}</div></div>`;
}

function surprises(c, D) {
  const S = c.surprises || {}, b = S.barres || [];
  if (!b.length) return "";
  const mx = Math.max(1, ...b.map(x => Math.abs(x.solde)));
  return `<div class="sub"><h3>Les surprises de la semaine, par devise</h3><figure class="card fig" style="padding:18px"><h4>Solde des surprises des publications moyennes et fortes, du ${esc(ddm(D.du))} au ${esc(ddm(D.fin_donnees))}</h4>
    <div class="sb">${b.map(x => `<div class="sr"><span class="cur">${x.devise}</span><div class="tr"><i class="${x.solde >= 0 ? "up" : "dn"}" style="${x.solde >= 0 ? "left:50%" : "right:50%"};width:${Math.abs(x.solde) / mx * 50}%"></i></div><b class="${x.solde > 0 ? "pos" : x.solde < 0 ? "neg" : "muted"}">${(x.solde > 0 ? "+" : "") + fmt(x.solde, 1)}</b><span class="small">${x.n} publ.</span></div>`).join("")}</div>
    <figcaption>${esc(S.methode || "")}. À droite, des chiffres qui poussent la banque centrale à être plus restrictive ; à gauche, des déceptions.${(S.aberrants || []).length ? " Écarts aberrants comptés pour 1 : " + esc(S.aberrants.join(" ; ")) + "." : ""} Source : ${esc(S.source || "")}.</figcaption></figure></div>`;
}

function publications(c) {
  const l = c.publications || [];
  if (!l.length) return "";
  return `<div class="sub"><h3>Les publications de la semaine</h3><div class="card pad tl">${l.map(x => `<div class="it"><span class="w">${esc(jourCourt(x.date))} ${esc(x.heure || "")}</span><span class="cur">${x.devise}</span>
    <div><b>${esc(x.evenement)}</b><p>publié ${esc(frTxt(x.reel))}${x.consensus ? " · attendu " + esc(frTxt(x.consensus)) : ""}${x.precedent ? " · précédent " + esc(frTxt(x.precedent)) : ""}${x.z != null ? ` · ${fmt(x.z, 1)} écart habituel` : x.consensus && x.raison_z ? " · écart habituel n/d" : ""}</p></div>${pastille(x.pastille, x.favorable)}</div>`).join("")}</div></div>`;
}

function actualite(c) {
  const l = c.actualite || [];
  if (!l.length) return `<div class="sub"><h3>L'actualité qui a compté</h3><p class="small">Aucun titre de la semaine classé sur ce moteur.</p></div>`;
  return `<div class="sub"><h3>L'actualité qui a compté</h3><div class="card pad tl">${l.map(x => `<div class="it"><span class="w">${x.date ? esc(ddm(x.date.slice(0, 10))) + " " + esc(String(x.date).slice(11, 16)) : ""}</span><span class="cur" style="font-size:10px">${esc(String(x.source || "").slice(0, 6))}</span>
    <div><a href="${esc(x.lien)}" target="_blank" rel="noopener"><b>${esc(x.titre)}</b></a><p>Pourquoi ça compte : ${esc((x.pourquoi || {})[String(c.numero)] || "")} · ${esc(x.source || "")}</p></div><span></span></div>`).join("")}</div></div>`;
}

function devises(c) {
  const l = c.devises || [];
  if (!l.length) return "";
  const vus = l.filter(d => d.effet === "soutien" || d.effet === "pression").concat(l.filter(d => d.effet !== "soutien" && d.effet !== "pression"));
  return `<div class="sub"><h3>Les effets sur les devises</h3><div class="dv">${vus.map(d => `<div class="dc ${d.effet === "soutien" ? "p" : d.effet === "pression" ? "c" : ""}"><div class="top"><b>${d.devise}</b>${effetPill(d.effet)}</div>
    ${d.changement ? `<span class="chg ${d.changement.change ? "oui" : ""}">Depuis lundi : ${esc(d.changement.texte)}</span>` : ""}
    <span class="k">Pourquoi</span><span>${gloss(esc(d.pourquoi_phrase || d.raison_non_mesure || d.pourquoi || "n/d"))}</span>
    ${d.pourquoi_phrase && d.pourquoi ? `<details class="regle"><summary>Règle de calcul</summary><span class="small">${esc(d.pourquoi)}</span></details>` : ""}
    ${d.effet !== "non mesuré" ? `<span class="k">Comment</span><span>${esc(d.comment || "")}</span>` : ""}
    ${(d.reactions || []).length ? `<span class="k">Réaction possible du pays</span><span>${d.reactions.slice(0, 2).map(r => `<b>${esc(r.acteur)}</b> : ${esc(r.levier)}, ${esc(r.declencheur)} · ${esc(r.date)}`).join("<br>")}</span>` : ""}
    ${d.prochain_rdv ? `<span class="small">Prochain rendez-vous : ${esc(jourCourt(d.prochain_rdv.date))} ${esc(d.prochain_rdv.heure || "")} · ${esc(d.prochain_rdv.evenement)}</span>` : ""}</div>`).join("")}</div></div>`;
}

function risques(c) {
  const R = c.risques || {}, s = R.seuil || {}, rdv = R.rendez_vous || [];
  return `<div class="sub"><h3>Les risques de la semaine prochaine</h3><div class="risk">
    <div class="card" style="background:var(--warn-soft);border-color:transparent"><b>Seuil à surveiller</b><span>${esc(s.texte || "n/d")}</span></div>
    <div class="card pad"><b>Rendez-vous liés (7 jours)</b>${rdv.length ? `<div class="tl" style="margin-top:4px">${rdv.slice(0, 6).map(e => `<div class="it" style="grid-template-columns:76px 42px minmax(0,1fr)"><span class="w">${esc(jourCourt(e.date))} ${esc(e.heure || "")}</span><span class="cur">${e.devise}</span><div><b style="font-size:13.5px">${esc(e.evenement)}</b><p>${e.consensus ? "attendu " + esc(frTxt(e.consensus)) + " · " : ""}${esc(e.ce_qui_pourrait_changer || "")}</p></div></div>`).join("")}</div>` : "<span>Aucun rendez-vous de ce moteur au calendrier des 7 prochains jours.</span>"}</div>
    <div class="card pad si"><b>Scénario si</b><span>${nbsp(esc(R.scenario_si || ""))}</span><span class="small">Des conditions et des effets probables, jamais un ordre.</span></div>
  </div></div>`;
}

function chapitreFinal(D) {
  const F = D.final || {};
  const s = h("section", "chap"); s.id = "c9"; s.dataset.t = "Semaine prochaine";
  if (F.erreur) { s.innerHTML = `<div class="chap-h"><span class="num">→</span><div><h2>Ce qui peut bouger la semaine prochaine</h2></div></div><div class="erreur">${esc(F.erreur)}</div>`; return s; }
  const RP = F.risque_principal || {};
  s.innerHTML = `<div class="chap-h"><span class="num">→</span><div><h2>Ce qui peut bouger la semaine prochaine</h2><p>Publications moyennes et fortes du ${esc(ddm(F.du))} au ${esc(ddm(F.au))}, heures de Paris${F.agenda_couvre ? "" : " · " + esc(F.raison_agenda || "")}</p></div></div>
    <div class="next">${(F.calendrier || []).map(j => `<div class="day"><header>${esc(j.jour)}</header>${(j.ferie || []).map(f => `<div class="fe">${esc(f)}</div>`).join("")}
      ${j.evenements.length ? j.evenements.map(e => `<div class="e ${e.impact === "fort" ? "f" : ""}"><span class="small">${esc(e.heure || "")} · ${e.devise}</span><b>${esc(e.evenement)}</b>${e.consensus ? `<span class="small">attendu ${esc(frTxt(e.consensus))}</span>` : ""}</div>`).join("") : '<div class="e"><span class="muted">Rien de moyen ou fort</span></div>'}</div>`).join("")}</div>
    <div class="sub">${recitHtml(F.recit, F.faits_semaine, true)}</div>
    <div class="box"><span class="eyebrow">Le risque principal</span><p>${nbsp(esc(RP.texte || "n/d"))}</p><span class="small" style="opacity:.7">${RP.redige_par === "python" ? "Choisi et rédigé en Python : le seuil le plus proche d'être franchi et le rendez-vous fort le plus proche." : "Choisi en Python, rédigé par " + esc(RP.redige_par)}</span></div>`;
  return s;
}
