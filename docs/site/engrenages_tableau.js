/* Lot V12, devenu la « Vue tableau » du V13 — onglet « 8 engrenages » : une analyse complète par moteur (maquette_v12_engrenages.html).
   En haut : la matrice 9 devises x 8 moteurs (option C) ; un clic sur une case ouvre le panneau (pourquoi, comment, réaction
   possible du pays, actualités et agenda liés, prochain rendez-vous). En dessous : les dossiers (option A), un par moteur,
   avec 3 sous-onglets : Analyse, Actualités et agenda, Devises touchées. Sous les dossiers : « Outils et historique »
   (cockpit, thermomètres, fil des 15 séances, simulateur et 4 outils du V7, inchangés).
   Toutes les données viennent de docs/data/moteurs_dossiers.json (core/dossiers_moteurs.py, agents/agent_moteurs.py) :
   le JavaScript affiche seulement. Dans cet onglet le mot « engrenage » reste permis, chaque moteur garde son nom.
   Adresses : #engrenages/g=2 (dossier 2), #engrenages/g=2/devises (sous-onglet), #engrenages/USD-2 (case de la matrice). */
import { $, h, esc, ddm, nd, spark, donnees, blocDetaille } from "./v7_commun.js";

const DEV = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"];
const JOURS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const ONGLETS = [["analyse", "Analyse"], ["news", "Actualités et agenda"], ["devises", "Devises touchées"]];
const jourCourt = iso => `${JOURS[new Date(iso + "T12:00:00Z").getUTCDay()]} ${ddm(iso)}`;
const heureParis = iso => { try { return new Date(iso).toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit" }); } catch (e) { return ""; } };
const pillEffet = e => e === "soutien" ? '<span class="pill p">▲ Soutien</span>' : e === "pression" ? '<span class="pill c">▼ Pression</span>' : e === "neutre" ? '<span class="pill n">Neutre</span>' : '<span class="pill n">Non mesuré</span>';
const pillEtat = e => e?.code === "franchi" ? '<span class="pill p">Seuil franchi</span>' : e?.code === "proche" ? '<span class="pill w">Près du seuil</span>' : e?.code === "non" ? '<span class="pill n">Calme</span>' : '<span class="pill n">n/d</span>';
const pillDir = e => e?.direction ? `<span class="pill ${e.classe === "up" ? "p" : e.classe === "dn" ? "c" : "n"}">${esc(e.direction)}</span>` : "";
const imp = i => `<span class="imp ${i}" aria-label="impact ${i}">${[1, 2, 3].map(k => `<i class="${k <= (i === "fort" ? 3 : i === "moyen" ? 2 : 1) ? "on" : ""}"></i>`).join("")}</span>`;
const reactionsHtml = l => (l || []).length ? `<div class="reac">${l.map(r => `<div><b>${esc(r.acteur)}</b> · ${esc(r.levier)}<br>Déclencheur : ${esc(r.declencheur)}<br>Quand : ${esc(r.date)}<br><span class="src">Source : ${r.lien ? `<a href="${esc(r.lien)}" target="_blank" rel="noopener">${esc(r.source)}</a>` : esc(r.source)}</span></div>`).join("")}</div>`
  : '<p>Pas de réaction attendue du pays sur ce moteur.</p>';
const rdvTxt = r => r ? `${jourCourt(r.date)} ${r.heure || ""} · ${r.evenement}` : "rien de moyen ou fort sur 7 jours";

export async function vueTableau(section, parametre) {
  section.classList.add("m12");
  section.innerHTML = `
    <div class="tete"><div><span class="eyebrow">8 engrenages · les moteurs du marché</span><h2 style="font-size:32px">Ce qui fait bouger les devises</h2></div><span class="small" id="asof"></span></div>
    <div class="layC"><div class="card pad" style="display:flex;flex-direction:column;gap:10px"><div class="sec-head"><h2>9 devises × 8 moteurs</h2><span class="small">▲ soutien · ▼ pression · · neutre · — non mesuré · clic pour l'explication</span></div>
      <div class="scroll"><table class="mx" id="mx"></table></div><p class="small" id="mxSrc" style="margin:0"></p></div>
      <div class="side" id="mxSide"></div></div>
    <div class="sec-head"><h2>Les dossiers</h2><p>Pour chaque moteur : ce qui se passe, ce qui arrive, quelles devises sont touchées et comment</p></div>
    <div class="layA"><div class="mlist" id="mlist" role="tablist" aria-label="Choisir un moteur"></div><article class="card dossier" id="dossier"></article></div>
    <div id="outilsHist" style="display:flex;flex-direction:column;gap:14px"></div>`;
  const q = s => $(s, section);
  const D = await donnees("moteurs_dossiers");
  // Outils et historique : l'écran V7 complet, repliable
  let ancien = null;
  const outils = blocDetaille("Outils et historique", "cockpit, thermomètres, fil des 15 séances, tableaux par engrenage, simulateur et 4 outils", async () => {
    const m = await import("./engrenages_v7.js"); const hote = h("div"); hote.style.cssText = "display:flex;flex-direction:column;gap:14px";
    await m.ancienEcran(hote, null); ancien = hote; return [hote];
  });
  q("#outilsHist").appendChild(outils);
  if (!D?.moteurs) {
    q("#dossier").innerHTML = `<div class="pad muted">Dossiers des moteurs pas encore calculés (${esc(D === null ? "moteurs_dossiers.json absent ou illisible" : "données incomplètes")}) : ils apparaîtront au prochain run. Les outils et l'historique restent disponibles ci-dessous.</div>`;
    section.allerA = async p => { await outils.ouvrirAvec(); return !!ancien?.allerA?.(p); };
    return;
  }
  q("#asof").textContent = `Données du ${ddm(D.date)} · générées le ${ddm(D.genere_le)} à ${heureParis(D.genere_le)}`;
  const M = n => D.moteurs[String(n)];
  let choisi = 2, onglet = "analyse", caseSel = ["JPY", 2];

  // ------------------------------------------------------------------ matrice (option C)
  function rendreMatrice() {
    const mx = D.matrice;
    q("#mx").innerHTML = `<thead><tr><th>Devise</th>${[1, 2, 3, 4, 5, 6, 7, 8].map(n => `<th title="${esc(M(n).explication)}">${esc(M(n).nom)}</th>`).join("")}<th>Solde</th></tr></thead><tbody>` +
      DEV.map(d => `<tr><td class="d">${d}</td>${mx.cases[d].map((c, i) => {
        const cls = c.effet === "soutien" ? "p" : c.effet === "pression" ? "m" : c.effet === "neutre" ? "z" : "nm", n = i + 1;
        return `<td class="c ${cls} ${caseSel[0] === d && caseSel[1] === n ? "on" : ""}" data-d="${d}" data-n="${n}" tabindex="0" role="button" aria-label="${d} · ${esc(M(n).nom)} : ${esc(c.effet)}" title="${esc(c.pourquoi)}">${c.effet === "soutien" ? "▲" : c.effet === "pression" ? "▼" : c.effet === "neutre" ? "·" : "—"}</td>`;
      }).join("")}<td class="t ${mx.solde[d] > 0 ? "pos" : mx.solde[d] < 0 ? "neg" : ""}">${mx.solde[d] > 0 ? "+" + mx.solde[d] : mx.solde[d] < 0 ? "−" + Math.abs(mx.solde[d]) : "0"}</td></tr>`).join("") + "</tbody>";
    q("#mxSrc").textContent = `Source : ${D.sources?.matrice || "matrice d'impact"} · solde = somme des effets (−2 à +2 par case).`;
    q("#mx").querySelectorAll("td.c").forEach(t => { const go = () => { caseSel = [t.dataset.d, +t.dataset.n]; history.replaceState(null, "", `#engrenages/${caseSel[0]}-${caseSel[1]}`); rendreMatrice();
      if (matchMedia("(max-width:1100px)").matches) q("#mxSide").scrollIntoView({ block: "nearest" }); };
      t.onclick = go; t.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } }; });
    rendreCase();
  }
  function rendreCase() {
    const [d, n] = caseSel, m = M(n), c = m.devises.find(x => x.devise === d) || {};
    const tit = m.actualites.slice(0, 4), ag = m.agenda.filter(e => e.devise === d && !e.passe).slice(0, 3);
    q("#mxSide").innerHTML = `<div class="card pad" style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">${d} · ${esc(m.nom)}</span>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><h2>${d}</h2>${pillEffet(c.effet)}</div>
      <div><div class="eyebrow">Pourquoi</div><p>${esc(c.pourquoi_phrase || c.pourquoi || "n/d")}</p>${c.pourquoi_phrase && c.pourquoi ? `<details><summary class="small">Règle de calcul</summary><p class="small">${esc(c.pourquoi)}</p></details>` : ""}</div>
      ${c.effet === "non mesuré" ? `<div><div class="eyebrow">Non mesuré</div><p>${esc(c.raison_non_mesure)}</p></div>` : `<div><div class="eyebrow">Comment</div><p>${esc(c.comment)}</p></div>`}
      <div><div class="eyebrow">Réaction possible du pays</div>${reactionsHtml(c.reactions)}</div>
      <div><div class="eyebrow">Actualités et agenda liés</div><ul>${[...tit.map(t => `<li><a href="${esc(t.lien)}" target="_blank" rel="noopener">${esc(t.titre)}</a> <span class="small">${esc(t.source || "")}</span></li>`),
        ...ag.map(e => `<li>${esc(jourCourt(e.date))} ${esc(e.heure || "")} · ${esc(e.evenement)} <span class="small">${esc(e.ce_qui_pourrait_changer)}</span></li>`)].join("") || '<li class="muted">Rien de lié aujourd\'hui ni cette semaine.</li>'}</ul></div>
      <div class="small" style="padding:8px 10px;border-radius:8px;background:var(--surface-2)">Prochain rendez-vous ${d} : ${esc(rdvTxt(c.prochain_rdv))}</div>
      <button type="button" class="btn sm" id="versDossier">Ouvrir le dossier « ${esc(m.nom)} »</button></div>`;
    q("#versDossier").onclick = () => { choisi = n; onglet = "devises"; rendreDossier(); q("#dossier").scrollIntoView({ block: "start" }); };
  }

  // ------------------------------------------------------------------ dossiers (option A)
  function rendreListe() {
    q("#mlist").innerHTML = [1, 2, 3, 4, 5, 6, 7, 8].map(n => { const m = M(n);
      return `<button type="button" class="mt" role="tab" data-n="${n}" aria-current="${n === choisi}" aria-selected="${n === choisi}"><span class="no">${n}</span><span><b>${esc(m.nom)}</b><small>${esc(m.explication)}</small>
        <span class="row">${pillEtat(m.etat)}<span class="small">${m.touchees ? `${m.touchees} devise${m.touchees > 1 ? "s" : ""} touchée${m.touchees > 1 ? "s" : ""}` : "aucune devise touchée"}</span></span></span></button>`; }).join("");
    q("#mlist").querySelectorAll(".mt").forEach(b => b.onclick = () => { choisi = +b.dataset.n; history.replaceState(null, "", `#engrenages/g=${choisi}`); rendreDossier(); });
  }
  function rendreDossier() {
    rendreListe();
    const n = choisi, m = M(n), e = m.etat, A = m.analyse;
    const aVenir = m.agenda.filter(x => !x.passe), passes = m.agenda.filter(x => x.passe);
    let corps = "";
    if (onglet === "analyse") {
      corps = `<p class="lead">${esc(A.introduction)}</p><span class="small" style="margin-top:-12px">${A.redige_par === "python" ? "Texte calculé en Python à partir des faits du jour" : `Rédigé par ${esc(A.redige_par)} à partir des faits calculés en Python, nombres contrôlés`}</span>
        ${e.incoherence ? `<div class="incoh">${esc(e.incoherence)}</div>` : ""}
        <div class="sec-head"><h3>Chiffres clés</h3><span class="small">point bleu : position sur 5 ans</span></div>
        <div class="kt">${A.chiffres_cles.map(t => `<div title="${esc(t.source || "")}"><span class="l">${esc(t.libelle)}</span><b>${t.texte && t.texte !== "n/d" ? esc(t.texte) : nd(t.raison)}</b><small>${esc(t.variation || "")}${t.date ? " · " + ddm(String(t.date).slice(0, 10)) : ""}</small>
          ${t.percentile_5a != null ? `<div class="pc" title="percentile sur 5 ans : ${t.percentile_5a}"><i style="left:${t.percentile_5a}%"></i></div>` : ""}${(t.points || []).length > 2 ? spark(t.points, 200, 34, "var(--accent)", true) : ""}
          ${t.lecture ? `<small>${esc(t.lecture)}</small>` : ""}</div>`).join("") || '<p class="muted">Aucun chiffre clé publié pour ce moteur.</p>'}</div>
        <div class="sec-head"><h3>Comment ce moteur fait bouger les devises</h3></div><p style="margin:0;font-size:15px;color:var(--ink-2);max-width:70ch">${esc(m.canal)}</p>
        <div class="sec-head"><h3>Ce qu'il faut surveiller</h3></div><ul class="watch">${A.surveiller.map(x => `<li>${esc(x)}</li>`).join("") || "<li>Rien de particulier.</li>"}</ul>
        ${m.manques.length ? `<p class="manques">Non mesuré sur ce moteur : ${m.manques.map(x => `${x.devise} (${esc(x.raison)})`).join(" ; ")}.</p>` : ""}`;
    } else if (onglet === "news") {
      const it = x => `<div class="it ${x.passe ? "passe" : ""}"><span class="w">${esc(jourCourt(x.date))} ${esc(x.heure || "")}</span><span class="cur">${esc(x.devise)}</span><div><b>${esc(x.evenement)}</b>${imp(x.impact || "faible")}
        <p>${x.consensus ? "attendu " + esc(x.consensus) + " · " : ""}${x.precedent ? "précédent " + esc(x.precedent) + " · " : ""}${x.publie ? "publié " + esc(x.publie) + " · " : ""}${esc(x.ce_qui_pourrait_changer)}</p></div></div>`;
      corps = `<p class="small" style="margin:0">Titres du jour classés sur ce moteur (mots-clés), puis publications des 7 prochains jours qui peuvent le faire bouger · heures de Paris</p>
        <div class="tl">${m.actualites.map(t => `<div class="it"><span class="w">${t.date ? esc(ddm(t.date.slice(0, 10)) + " " + heureParis(t.date)) : "n/d"}</span><span class="cur">${esc(String(t.source || "").slice(0, 6))}</span>
          <a href="${esc(t.lien)}" target="_blank" rel="noopener"><b>${esc(t.titre)}</b><p>Pourquoi ce titre compte : ${esc(t.pourquoi[String(n)])} · ${esc(t.source || "")}</p></a></div>`).join("")
          || '<div class="it"><span></span><span></span><span class="muted">Aucun titre classé sur ce moteur aujourd\'hui.</span></div>'}
          ${passes.map(it).join("")}<div class="now">Maintenant · ${esc(jourCourt(D.date))}</div>${aVenir.map(it).join("") || '<div class="it"><span></span><span></span><span class="muted">Aucune publication liée sur 7 jours.</span></div>'}</div>`;
    } else {
      corps = `<p class="small" style="margin:0">Pour chaque devise : sens de l'effet, pourquoi (règle et chiffre), comment (canal), réaction possible du pays et prochain rendez-vous</p>
        <div class="dv">${m.devises.map(c => `<div class="dc ${c.effet === "soutien" ? "p" : c.effet === "pression" ? "c" : ""}"><div class="top"><b>${c.devise}</b>${pillEffet(c.effet)}</div><dl>
          <div><dt>Pourquoi</dt><dd>${esc(c.pourquoi_phrase || c.pourquoi || "n/d")}${c.pourquoi_phrase && c.pourquoi ? `<details><summary class="small">Règle de calcul</summary><span class="small">${esc(c.pourquoi)}</span></details>` : ""}</dd></div>
          ${c.effet === "non mesuré" ? `<div><dt>Non mesuré</dt><dd>${esc(c.raison_non_mesure)}</dd></div>` : `<div><dt>Comment</dt><dd>${esc(c.comment)}</dd></div>`}
          <div><dt>Réaction possible du pays</dt><dd>${reactionsHtml(c.reactions)}</dd></div></dl>
          <div class="next">Prochain rendez-vous : ${esc(rdvTxt(c.prochain_rdv))}</div></div>`).join("")}</div>
        ${m.manques.length ? `<p class="manques">Manques de données sur ce moteur : ${m.manques.map(x => `${x.devise} (${esc(x.raison)})`).join(" ; ")}.</p>` : ""}`;
    }
    q("#dossier").innerHTML = `<div class="dh"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><span class="eyebrow">Engrenage ${n} sur 8</span>${pillEtat(e)}${pillDir(e)}
        ${e.valeur != null ? `<span class="small" title="${esc(e.source || "")}">${esc(e.libelle || "")} : <b>${esc(e.valeur)}</b>${e.date ? " au " + ddm(e.date) : ""}</span>` : ""}</div>
      <h1>${esc(m.nom)}</h1><p class="small" style="margin:-6px 0 0">${esc(m.explication)}</p><p class="q">${esc(m.question)}</p>
      <div class="ptabs" role="tablist">${ONGLETS.map(([k, l]) => `<button type="button" role="tab" data-t="${k}" aria-selected="${k === onglet}">${l}${k === "news" ? `<span class="cnt">${m.actualites.length + aVenir.length}</span>` : k === "devises" ? `<span class="cnt">${m.touchees}</span>` : ""}</button>`).join("")}</div></div>
      <div class="dbody">${corps}</div>`;
    q("#dossier").querySelectorAll("[data-t]").forEach(b => b.onclick = () => { onglet = b.dataset.t; history.replaceState(null, "", `#engrenages/g=${choisi}${onglet === "analyse" ? "" : "/" + onglet}`); rendreDossier(); });
  }

  // ------------------------------------------------------------------ adresses
  const SOUS = { devises: "devises", actualites: "news", news: "news", agenda: "news", analyse: "analyse" };
  section.allerA = async p => {
    const g = (p || "").match(/^g=([1-8])(?:\/(\w+))?$/);
    if (g) { choisi = +g[1]; onglet = SOUS[g[2]] || "analyse"; rendreDossier(); q("#mlist").scrollIntoView({ block: "start" }); return true; }
    const c = (p || "").match(/^([A-Z]{3})-([1-8])$/);
    if (c && DEV.includes(c[1])) { caseSel = [c[1], +c[2]]; rendreMatrice(); q(".layC").scrollIntoView({ block: "start" }); return true; }
    if (["hebdo", "mensuel", "quotidien", "outils"].includes(p)) { document.documentElement.dataset.vue = "complete"; await outils.ouvrirAvec(); outils.open = true; return ancien?.allerA ? !!(await ancien.allerA(p)) : false; }
    return false;
  };
  rendreMatrice();
  rendreDossier();
  if (parametre) section.cible = await section.allerA(parametre);
}
