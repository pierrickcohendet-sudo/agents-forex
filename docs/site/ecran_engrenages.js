/* Lot V7 — 8 engrenages (maquette #engrenages) : dossiers.json (cockpit, matrice_impact, engrenages 1 à 8). Directions,
   seuils, positions, soldes et règles : Python. Le simulateur et les 4 outils restent accessibles en vue complète. */
import { $, h, sgn, esc, ddm, nd, fv, classeDir, spark, donnees, bloc, blocDetaille } from "./v7_commun.js";
import { tableEngrenage } from "./ecran_tableau.js";

const COURTS = ["Thème", "Monétaire", "Données", "Fiscale", "Marchés", "Géopolitique", "Flux", "Offre/demande"];
const SQUELETTE = `
<div class="card pad" style="display:flex;flex-direction:column;gap:12px">
  <span class="eyebrow" data-fraicheur="engrenages">Cockpit</span>
  <div style="display:flex;gap:14px;align-items:baseline;flex-wrap:wrap"><h2 id="ckT"></h2><span id="ckChip"></span></div>
  <p style="margin:0;color:var(--ink-2);max-width:80ch" id="ckTxt"></p>
  <div style="display:flex;gap:6px;flex-wrap:wrap" id="suivi"></div>
</div>
<div class="cols2">
  <div class="card">
    <div class="pad" style="padding-bottom:4px"><div class="sec-head"><h2>Thermomètres</h2><p>Bleu : couloir neutre</p></div></div>
    <div class="th-list" id="ths"></div>
  </div>
  <div style="display:flex;flex-direction:column;gap:14px">
    <div class="card pad" style="display:flex;flex-direction:column;gap:10px"><h3>Seuils franchis</h3><div id="ckF" style="display:flex;flex-direction:column;gap:8px;font-size:13.5px"></div></div>
    <div class="card pad" style="display:flex;flex-direction:column;gap:10px"><h3>Au bord du seuil</h3><div id="ckB" style="display:flex;flex-direction:column;gap:8px;font-size:13.5px"></div></div>
  </div>
</div>
<div class="card pad" style="display:flex;flex-direction:column;gap:12px">
  <div class="sec-head"><h2>Matrice d'impact</h2><div class="legend"><span><i style="background:var(--up-soft);border:1px solid var(--up)"></i>Soutien +1</span><span><i style="background:var(--down-soft);border:1px solid var(--down)"></i>Pression −1</span><span><i style="background:var(--surface-2);border:1px solid var(--line-2)"></i>Neutre</span><span><i style="background:repeating-linear-gradient(135deg,var(--line-2) 0 2px,transparent 2px 5px)"></i>n/d ou sans règle (—)</span><span>Survol : la règle appliquée</span></div></div>
  <div class="scroll"><table class="heat mi" id="mi"></table></div>
  <p class="src" id="miSrc"></p>
</div>
<div class="card pad full" style="display:flex;flex-direction:column;gap:12px">
  <div class="sec-head"><h2>Fil des 15 séances</h2><div class="legend"><span><i style="background:var(--up)"></i>Dollar haussier</span><span><i style="background:var(--down)"></i>Dollar baissier ou risk off</span><span><i style="background:var(--line-2)"></i>Neutre</span></div></div>
  <div class="scroll"><div class="fil" id="fil"></div></div>
</div>
<div class="sec-head"><h2>Dossier par engrenage</h2><p>Tous les indicateurs, tableaux et conséquences</p></div>
<div class="engsel" id="engSel" role="group" aria-label="Choisir un engrenage"></div>
<div id="engDet" style="display:flex;flex-direction:column;gap:14px"></div>
<div id="detaille" style="display:flex;flex-direction:column;gap:14px"></div>`;

export async function ecranEngrenages(section, parametre) {
  section.innerHTML = SQUELETTE;
  const q = s => $(s, section);
  const dos = await donnees("dossiers");
  if (!dos) { q("#ckT").textContent = "Dossiers des engrenages indisponibles"; return; }
  const ck = dos.cockpit || {}, en = ck.entete || {}, thermo = ck.thermometres || [];

  bloc(q(".card"), () => {
    q("#ckT").textContent = `${en.titre || "Thème n/d"} · ${en.alignes ?? "n/d"} engrenages alignés sur ${en.evaluables ?? "n/d"}`;
    q("#ckChip").innerHTML = en.direction ? `<span class="chip ${classeDir(en.direction.classe)}"><span class="dot"></span>${esc(en.direction.libelle)}</span>` : "";
    q("#ckTxt").textContent = en.explication || en.texte || "";
    const suivi = dos.engrenages?.["1"]?.suivi_theme?.lignes || [];
    q("#suivi").innerHTML = suivi.map(s => `<span class="chip ${s.accord === "oui" ? "up" : ""}" title="${esc(`${s.nom} · ${s.direction} · conviction ${s.conviction || "n/d"} · ${s.accord}`)}">${s.accord === "oui" ? "✓" : "·"} ${s.numero} ${esc(COURTS[s.numero - 1])} : ${esc(s.direction)}</span>`).join("");
  });

  bloc(q("#ths"), () => {
    q("#ths").innerHTML = thermo.map(t => {
      const zb = t.pos_bas ?? 0, zh = t.pos_haut ?? 100, pos = Math.max(0, Math.min(100, t.pos ?? 50));
      const st = t.etat === "franchi" ? "acc" : t.etat === "proche" ? "warn" : "";
      const stx = t.etat === "franchi" ? "Seuil franchi" : t.etat === "proche" ? "Près du seuil" : t.valeur == null ? "n/d" : "Dans le couloir";
      return `<div class="th"><div class="nm"><b>${t.numero} · ${esc(t.titre)}</b><small>${esc(t.libelle)}</small></div>
        <div class="track" title="${esc([t.note, t.source, t.date ? ddm(t.date) : ""].filter(Boolean).join(" · ") || t.raison || "")}"><div class="rail"></div><div class="zone" style="left:${zb}%;width:${zh - zb}%"></div>
          ${t.valeur == null ? "" : `<div class="mk" style="left:${pos}%"></div>`}<span class="v" style="left:${Math.max(6, Math.min(94, pos))}%">${t.valeur == null ? nd(t.raison) : esc(t.texte_valeur ?? "n/d")}</span></div>
        <span class="chip ${st} st">${stx}</span></div>`;
    }).join("");
  });

  bloc(q("#ckF"), () => {
    const fr = ck.franchis || [], bo = ck.au_bord || [];
    q("#ckF").innerHTML = fr.length ? fr.map(x => `<div style="display:flex;gap:10px"><span class="chip acc" style="height:22px">${x.engrenage}</span><span>${esc(x.phrase || x.libelle)}<br><span class="small">${x.cote === "haut" && x.effet_haut ? "Effet : " + esc(x.effet_haut) : x.effet_bas ? "Effet : " + esc(x.effet_bas) : ""} · ${esc(x.source || "")}</span></span></div>`).join("") : '<span class="muted">Aucun seuil franchi.</span>';
    q("#ckB").innerHTML = bo.length ? bo.map(x => `<div style="display:flex;gap:10px"><span class="chip warn" style="height:22px">${x.engrenage}</span><span>${esc(x.phrase || x.libelle)}<br><span class="small">Si franchi : ${esc(x.cote === "haut" ? x.effet_haut : x.effet_bas)}</span></span></div>`).join("") : '<span class="muted">Aucun seuil proche.</span>';
  });

  bloc(q("#mi"), () => {
    const mi = dos.matrice_impact || {};
    const regle = c => [c.libelle, ...(c.regles || []).map(r => r.texte || r.regle || ""), c.raison].filter(Boolean).join(" : ");
    q("#mi").innerHTML = `<thead><tr><th>Devise</th>${COURTS.map((c, i) => `<th>${i + 1} ${c}</th>`).join("")}<th>Solde</th></tr></thead><tbody>` +
      (mi.lignes || []).map(l => `<tr><td style="font-weight:700;padding:4px 6px">${l.devise}</td>${(l.cases || []).map(c => {
        const v = c.valeur, cls = c.etat === "nd" || c.etat === "sans_regle" ? "nd" : v > 0 ? "p1" : v < 0 ? "m1" : "z";
        return `<td class="c ${cls}" tabindex="0" title="${esc(regle(c))}">${v > 0 ? "+" + v : v < 0 ? "−" + Math.abs(v) : c.etat === "nd" ? "n/d" : c.etat === "sans_regle" ? "—" : "0"}</td>`;
      }).join("")}<td class="c solde" title="${esc(`bilan calculé en Python : ${l.lecture || ""}`)}">${l.bilan > 0 ? "+" + l.bilan : l.bilan < 0 ? "−" + Math.abs(l.bilan) : l.bilan == null ? "n/d" : "0"}</td></tr>`).join("") + "</tbody>";
    q("#miSrc").textContent = `${mi.compte_libelle || ""} · ${mi.legende || ""}`;
  });

  bloc(q("#fil"), () => {
    const f = ck.fil || { jours: [], lignes: [] }, n = f.jours.length;
    let html = `<span></span>${f.jours.map(j => `<span class="d">${ddm(j)}</span>`).join("")}`;
    for (const l of f.lignes) html += `<span class="lab">${esc(l.titre)}</span>` + (l.cellules || []).map(c => `<i class="${c.classe || "x"}" title="${ddm(c.date)} · ${esc(c.libelle || "")}"></i>`).join("");
    const fil = q("#fil"); fil.style.gridTemplateColumns = `110px repeat(${n}, minmax(0,1fr))`; fil.innerHTML = html;
  });

  // Dossier par engrenage (8 boutons) ; lien direct #engrenages/g=N
  let choisi = Number((parametre || "").match(/^g=([1-8])$/)?.[1] || 2);
  const rendreSel = () => {
    q("#engSel").innerHTML = Array.from({ length: 8 }, (_, i) => i + 1).filter(n => dos.engrenages?.[String(n)]).map(n => {
      const t = thermo.find(x => x.numero === n), c = t?.direction?.classe || "nd", e = dos.engrenages[String(n)];
      return `<button type="button" data-n="${n}" aria-pressed="${n === choisi}"><span class="dot" style="color:${c === "up" ? "var(--up)" : c === "dn" ? "var(--down)" : "var(--line-2)"}"></span>${n} · ${esc(e.titre)}</button>`;
    }).join("");
    q("#engSel").querySelectorAll("button").forEach(b => b.onclick = () => { choisi = +b.dataset.n; history.replaceState(null, "", `#engrenages/g=${choisi}`); rendreSel(); });
    bloc(q("#engDet"), () => { q("#engDet").innerHTML = dossier(dos.engrenages[String(choisi)], thermo.find(x => x.numero === choisi)); });
  };
  rendreSel();

  q("#detaille").append(
    blocDetaille("Simulateur et 4 outils", "radar, scénarios « et si », paires, situations similaires", async () => {
      const m = await import("./outils.js"); const lien = h("p", "small", 'Simulateur complet des scénarios : menu <a href="#scenarios">Plus › Scénarios et simulateur</a>.');
      return [lien, ...(await m.pageOutils())];
    }),
    blocDetaille("Dossiers détaillés", "graphiques annotés, vue d'ensemble, chaînes de transmission", async () => {
      const m = await import("./engrenages.js"); return m.pageEngrenages();
    }));
}

function dossier(e, t) {
  if (!e) return '<div class="card pad muted">Dossier indisponible.</div>';
  let html = `<div class="card pad" style="display:flex;flex-direction:column;gap:10px">
    <div style="display:flex;gap:14px;align-items:baseline;flex-wrap:wrap"><span style="font-family:var(--f-display);font-size:44px;line-height:1;color:var(--muted)">${e.numero}</span><h2 style="font-size:30px">${esc(e.titre)}</h2>${t?.direction ? `<span class="chip ${classeDir(t.direction.classe)}"><span class="dot"></span>${esc(t.direction.libelle)}</span>` : ""}</div>
    ${t ? `<p style="margin:0;color:var(--ink-2)">${esc(t.libelle)} : <b>${esc(t.texte_valeur ?? "n/d")}</b>. ${esc(t.note || "")}</p>` : ""}
    ${(e.notes || []).length ? `<ul class="watch full">${e.notes.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`;
  const tuiles = e.tuiles || [];
  if (tuiles.length) html += `<div class="grid tus">${tuiles.map(x => {
    const pts = (x.courbe?.points || []).map(p => p[1]);
    return `<div class="card tu" title="${esc(x.source || "")}"><span class="l">${esc(x.libelle)}</span><span class="v">${x.texte ? esc(x.texte) : nd(x.raison)}</span>
      <span class="x">${esc(x.variation?.texte || "")}</span>
      ${x.percentile_5a != null ? `<div class="pct" title="percentile sur 5 ans"><i style="left:${x.percentile_5a}%"></i></div><span class="small">percentile 5 ans : ${x.percentile_5a}</span>` : ""}
      ${pts.length > 2 ? spark(pts, 200, 44, "var(--accent)", true) : ""}
      ${x.lecture || x.note ? `<span class="small full" style="color:var(--ink-2)">${esc(x.lecture || x.note)}</span>` : ""}
      <span class="small">${x.date ? ddm(String(x.date).slice(0, 10)) : ""}${x.frequence ? " · " + esc(x.frequence) : ""}${x.source ? " · " + esc(String(x.source).split(/[ (,]/)[0]) : ""}</span></div>`;
  }).join("")}</div>`;
  if (e.lignes && e.colonnes) html += `<div class="card"><div class="pad" style="padding-bottom:4px"><div class="sec-head"><h3>Par devise</h3><span class="small">(pXX) : percentile 5 ans · survol : source, ou raison d'un n/d</span></div></div><div class="scroll"><table class="tbl" style="min-width:860px">${tableEngrenage(e)}</table></div></div>`;
  if (e.instruments?.length) html += `<div class="card"><div class="pad" style="padding-bottom:4px"><h3>Instruments</h3></div><div class="scroll"><table class="tbl"><thead><tr><th>Instrument</th><th class="n">Niveau</th><th class="n">1 sem.</th><th class="n">4 sem.</th><th class="n">Percentile 5 ans</th><th>Date</th></tr></thead><tbody>${e.instruments.map(x => {
    const c = x.cellule || {}, u = c.unite, niv = u === "niveau" || u === "indice";
    return `<tr><td><b>${esc(x.libelle)}</b></td><td class="n" title="${esc(c.source || c.raison || "")}">${c.valeur == null ? nd(c.raison) : fv(c.valeur, niv ? "" : u)}</td><td class="n ${c.var_1s > 0 ? "pos" : c.var_1s < 0 ? "neg" : ""}">${c.var_1s == null ? "—" : sgn(c.var_1s, 2, niv ? " %" : "")}</td><td class="n ${c.var_4s > 0 ? "pos" : c.var_4s < 0 ? "neg" : ""}">${c.var_4s == null ? "—" : sgn(c.var_4s, 2, niv ? " %" : "")}</td><td class="n">${c.percentile_5a ?? "—"}</td><td class="small">${c.date ? ddm(c.date) : ""}</td></tr>`;
  }).join("")}</tbody></table></div></div>`;
  const cons = e.consequences;
  if (cons?.moteur && cons.lignes?.length) {
    const m = cons.moteur;
    html += `<div class="card full"><div class="pad" style="padding-bottom:4px"><div class="sec-head"><h3>Conséquences passées : ${esc(m.libelle)}</h3><span class="small">${esc(m.source || "")} · 1 mois ${sgn(m.variation_1m, m.unite === "pb" ? 0 : 2, m.unite === "pb" ? " pb" : "")} · depuis ${m.debut ? m.debut.slice(0, 4) : ""}</span></div></div>
      <div class="scroll"><table class="tbl" style="min-width:720px"><thead><tr><th>Actif</th><th class="n">Sensibilité</th><th class="n">Médiane si le moteur monte</th><th class="n">Médiane s'il baisse</th><th class="n">Fiabilité</th><th>Aujourd'hui</th></tr></thead><tbody>
      ${cons.lignes.map(x => { const hm = x.si_hausse?.mediane, bm = x.si_baisse?.mediane, fi = x.fiabilite || {};
        return `<tr><td><b>${esc(x.actif)}</b></td><td class="n">${x.sensibilite == null ? "—" : sgn(x.sensibilite, 2)}</td><td class="n ${hm > 0 ? "pos" : hm < 0 ? "neg" : ""}">${hm == null ? nd(x.si_hausse?.raison) : sgn(hm, 2, " %")}</td><td class="n ${bm > 0 ? "pos" : bm < 0 ? "neg" : ""}">${bm == null ? nd(x.si_baisse?.raison) : sgn(bm, 2, " %")}</td><td class="n">${fi.part == null ? nd(fi.raison) : fi.part + " %"} <span class="small">(n=${fi.n ?? "—"})</span></td><td title="${esc(x.aujourdhui?.raison || "")}">${esc(x.aujourdhui?.lecture || "")}</td></tr>`; }).join("")}
      </tbody></table></div><div class="pad small" style="padding-top:8px">Moyennes passées, pas une prévision. Corrélation n'est pas causalité.</div></div>`;
  }
  if (e.balances?.length) html += `<div class="card"><div class="pad" style="padding-bottom:4px"><h3>Balances commerciales</h3></div><div class="scroll"><table class="tbl"><thead><tr><th>Devise</th><th class="n">Publié</th><th class="n">Consensus</th><th>Date</th></tr></thead><tbody>${e.balances.map(x => `<tr><td><b>${x.devise}</b></td><td class="n">${x.valeur ? esc(String(x.valeur).replace(".", ",")) : nd(x.raison)}</td><td class="n muted">${esc(String(x.consensus || "—").replace(".", ","))}</td><td class="small">${x.date ? ddm(x.date) : ""} ${esc(x.source || "")}</td></tr>`).join("")}</tbody></table></div></div>`;
  if (e.evenements?.length) html += `<div class="card pad" style="display:flex;flex-direction:column;gap:4px"><h3>Fil d'actualité géopolitique</h3><div class="news">${e.evenements.slice(0, 12).map(x => `<a href="${esc(x.lien)}" target="_blank" rel="noopener"><b>${esc(x.titre)}</b><span class="small">${esc(x.mecanisme || "")} · ${(x.devises || []).join(", ")} · ${esc(x.source)} · ${ddm(x.date)}</span></a>`).join("")}</div></div>`;
  return html;
}
