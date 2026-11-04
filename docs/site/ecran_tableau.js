/* Lot V7 — Tableau de bord (maquette #tableau) : rapport_jour.json, marche.json, force_devises.json, tableau_macro.json,
   dossiers.json (engrenages 2 et 5), agenda.json. La force des devises est calculée en Python (core/force_devises.py). */
import { $, h, nf, sgn, num, esc, dfr, ddm, frTxt, nd, fv, classeSigne, spark, hbar, donnees, bloc, graphique, retirerGraphique, blocDetaille } from "./v7_commun.js";

const SQUELETTE = `
<div class="alerts" id="alerts"></div>
<div class="sec-head"><h2>Point de marché</h2><p id="pmMeta"></p></div>
<div id="pm" style="display:flex;flex-direction:column;gap:12px"></div>
<div class="card pad" style="display:flex;flex-direction:column;gap:12px">
  <div class="sec-head"><h2 id="bgT"></h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap"><div class="seg" id="bgSel" role="group" aria-label="Série du graphique"></div><div class="seg" id="bgPer" role="group" aria-label="Période"></div></div></div>
  <div class="bigchart" id="bigchart"></div>
  <div class="src" id="bgSrc"></div>
</div>
<div class="cols2">
  <div class="card pad" style="display:flex;flex-direction:column;gap:8px">
    <div class="sec-head"><h2>Force des devises</h2><div class="seg" id="foPer" role="group" aria-label="Période de la force"></div></div>
    <div class="legend"><span>Barre : variation sur la période</span><span><i style="background:var(--ink);opacity:.55;width:2px"></i>écart à la MM200</span></div>
    <div id="force"></div>
    <div class="src" id="foSrc"></div>
  </div>
  <div class="card pad" style="display:flex;flex-direction:column;gap:8px">
    <div class="sec-head"><h2>Surprises macro, 30 jours</h2><p>Indice en écarts-types</p></div>
    <div class="legend"><span><i style="background:var(--ink);opacity:.55;width:2px"></i>valeur précédente</span></div>
    <div id="surp"></div>
    <div class="src">Calcul Python : surprises face au consensus, fenêtre 30 jours (registre macro, ForexFactory)</div>
  </div>
</div>
<div class="card pad" style="display:flex;flex-direction:column;gap:12px">
  <div class="sec-head"><h2>Corrélations sur 60 séances</h2><p>Devise contre marchés · survol : valeur précédente et percentile 5 ans</p></div>
  <div class="scroll"><table class="heat" id="heat"></table></div>
  <div class="src" id="heatSrc"></div>
</div>
<div class="sec-head"><h2>Macro par devise</h2><p>▲ ▼ = : publié face au consensus · vue complète : précédent et prévision</p></div>
<div class="card scroll"><table class="mx" id="mx"></table></div>
<div class="card full">
  <div class="pad" style="padding-bottom:4px"><div class="sec-head"><h2>Taux et écarts</h2><p>Percentile 5 ans entre parenthèses · survol : source, ou raison d'un n/d</p></div></div>
  <div class="scroll"><table class="tbl" id="taux" style="min-width:860px"></table></div>
</div>
<div class="sec-head full"><h2>Banques centrales</h2><p>Taux et prochaine réunion</p></div>
<div class="grid bcs full" id="bcs"></div>
<div class="card pad full" style="display:flex;flex-direction:column;gap:14px">
  <div class="sec-head"><h2>Calculateur de taille de position</h2><p>Valeur du pip du jour, compte en dollars</p></div>
  <div class="calc">
    <label for="cCap">Capital (USD)<input id="cCap" type="number" value="10000" min="0" step="100"></label>
    <label for="cRis">Risque par trade (%)<input id="cRis" type="number" value="1" min="0" step="0.1"></label>
    <label for="cStop">Stop (pips)<input id="cStop" type="number" value="25" min="1" step="1"></label>
    <label for="cPair">Paire<select id="cPair"></select></label>
    <div class="out" id="cOut" aria-live="polite"></div>
  </div>
  <div class="src" id="cSrc"></div>
</div>
<div id="detaille"></div>`;

const GRP = { fx: "Changes", dollar: "Dollar", changes: "Changes", taux: "Taux américains", petrole: "Matières premières", or: "Matières premières", matieres: "Matières premières", actions: "Actions et risque", vix: "Actions et risque", risque: "Actions et risque" };
const COULEURS = ["--c1", "--c3", "--c2"];

export async function ecranTableau(section) {
  section.innerHTML = SQUELETTE;
  const q = s => $(s, section);
  const [rj, marche, force, tm, dos, agenda] = await Promise.all([donnees("rapport_jour"), donnees("marche"), donnees("force_devises"),
    donnees("tableau_macro"), donnees("dossiers"), donnees("agenda")]);
  const tdb = rj?.tableau_de_bord || {};

  bloc(q("#alerts"), () => {
    const ck = dos?.cockpit || {};   // listes du cockpit (Python) ; repli sur le rapport du jour
    const liste = x => Array.isArray(x) ? x : [];
    const bord = liste(ck.au_bord).length ? ck.au_bord : liste(tdb.au_bord), fr = liste(ck.franchis).length ? ck.franchis : liste(tdb.franchis);
    q("#alerts").innerHTML = bord.map(x => `<div class="alert p"><b>Au bord</b><span>${esc(x.phrase || x.libelle)}</span></div>`).join("") +
      `<details class="card" style="width:100%;padding:12px 16px"><summary style="cursor:pointer;font-weight:600;font-size:14px">${fr.length} seuil${fr.length > 1 ? "s" : ""} franchi${fr.length > 1 ? "s" : ""} aujourd'hui <span class="small">· détail par engrenage dans 8 engrenages</span></summary><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(min(320px,100%),1fr));gap:6px 18px;margin-top:10px;font-size:13px">${fr.map(x => `<div style="display:flex;gap:8px"><span class="chip acc" style="height:20px;padding:0 7px">${x.engrenage}</span><span>${esc(x.phrase || x.libelle)} <span class="small">· ${esc(x.source || "")}</span></span></div>`).join("")}</div></details>`;
  });

  bloc(q("#pm"), () => {
    const lignes = rj?.point_marche?.lignes || [];
    q("#pmMeta").textContent = rj ? `Mis à jour ${(rj.genere_le || "").slice(11, 16)} UTC · 30 dernières séances` : "";
    const grille = h("div", "grid tiles"); q("#pm").appendChild(grille);
    for (const l of lignes) {
      const dc = l.decimales ?? (l.niveau > 50 ? 2 : 4), u = l.unite === "pb" ? " pb" : l.unite === "pts" ? " pts" : " %", du = l.unite === "pb" ? 0 : 2;
      const couleur = l.variation_j1 > 0 ? "var(--up)" : l.variation_j1 < 0 ? "var(--down)" : "var(--muted)";
      const quand = l.statut === "provisoire" ? "en séance" : l.heure ? "clôture " + ddm(String(l.heure).slice(0, 10)) : "";
      const c = h("div", "card tile", `<div class="eyebrow" style="font-size:10.5px">${esc(GRP[l.categorie] || String(l.categorie || "").replace(/_/g, " "))}</div><div class="lbl" title="${esc(l.actif)}">${esc(l.actif)}</div>
        <div class="val">${l.niveau == null ? nd(l.raison) : nf(l.niveau, dc) + esc(l.suffixe || "")}</div>
        <div class="chg"><span class="${classeSigne(l.variation_j1)}">${l.variation_j1 > 0 ? "▲" : l.variation_j1 < 0 ? "▼" : "■"} ${sgn(l.variation_j1, du, u)}</span><span>5 j ${sgn(l.variation_5j, du, u)}</span></div>
        ${spark((l.serie_30j || []).map(p => p[1]), 200, 46, couleur, true)}
        ${l.alerte_fraicheur ? `<span class="chip warn" style="height:auto;white-space:normal;padding:4px 8px" title="${esc(l.alerte_fraicheur.cause || "")}">${esc(l.alerte_fraicheur.texte)}</span>` : ""}
        <div class="small full" style="line-height:1.35;min-height:2.7em">${esc(l.lecture || "")}</div>
        <div class="meta"><span>${esc(quand)}${l.statut && l.statut !== "provisoire" ? " · " + esc(l.statut) : ""}</span><span title="${esc(l.source)}">${esc((l.source || "").split(/[ (,;]/)[0])}</span></div>`);
      grille.appendChild(c);
    }
    if (!lignes.length) q("#pm").innerHTML = `<div class="card pad muted">Point de marché indisponible (rapport du jour absent).</div>`;
  });

  // Grand graphique (Lightweight Charts, initialisé à l'ouverture de l'onglet)
  let cle = "dollar", per = "3M", g = null;
  const graphs = marche?.graphiques || {}, periodes = marche?.periodes || { "1M": 31, "3M": 92, "1A": 366 };
  if (!graphs[cle]) cle = Object.keys(graphs)[0];
  async function dessiner() {
    const gr = graphs[cle]; if (!gr) { q("#bgT").textContent = "Graphique de marché indisponible"; return; }
    q("#bgT").textContent = gr.titre;
    q("#bgSrc").textContent = `Source : ${gr.source}${gr.unite ? " · unité : " + gr.unite : ""}${gr.note ? " · " + gr.note : ""} · données au ${ddm(Object.values(gr.courbes || {})[0]?.points?.slice(-1)[0]?.[0])}`;
    q("#bgSel").innerHTML = Object.entries(graphs).map(([k, x]) => `<button type="button" data-k="${k}" aria-pressed="${k === cle}">${esc(x.titre.split(" —")[0])}</button>`).join("");
    q("#bgPer").innerHTML = Object.keys(periodes).map(p => `<button type="button" data-p="${p}" aria-pressed="${p === per}">${p}</button>`).join("");
    q("#bgSel").querySelectorAll("button").forEach(b => b.onclick = () => { cle = b.dataset.k; dessiner(); });
    q("#bgPer").querySelectorAll("button").forEach(b => b.onclick = () => { per = b.dataset.p; dessiner(); });
    const jours = periodes[per] || 92;
    const series = Object.values(gr.courbes || {}).map((c, i) => {
      const pts = c.points || [], der = pts.length ? new Date(pts[pts.length - 1][0]) : new Date();
      const depuis = new Date(der - jours * 864e5).toISOString().slice(0, 10);
      return { l: c.libelle, p: pts.filter(p => p[0] >= depuis && p[1] != null), couleur: COULEURS[i % 3] };
    });
    retirerGraphique(g);
    g = await graphique(q("#bigchart"), series, Number(gr.decimales ?? 2));
  }
  dessiner();

  bloc(q("#force"), () => {
    let fo = "j5";
    const lignes = force?.devises || [];
    const rendre = () => {
      q("#foPer").innerHTML = [["j1", "1 j"], ["j5", "5 j"], ["j20", "20 j"]].map(p => `<button type="button" data-p="${p[0]}" aria-pressed="${p[0] === fo}">${p[1]}</button>`).join("");
      q("#foPer").querySelectorAll("button").forEach(b => b.onclick = () => { fo = b.dataset.p; rendre(); });
      // ordre : rang calculé en Python (force_devises.json), jamais un tri fait ici
      const tries = [...lignes].sort((a, b) => (a.rangs?.[fo] ?? 99) - (b.rangs?.[fo] ?? 99));
      const ech = Math.max(...lignes.map(x => Math.abs(x[fo] ?? 0)), 0.5) * 1.1;
      q("#force").innerHTML = tries.map(x => hbar(x.devise, x[fo], ech, sgn(x[fo], 2, " %"), x.ecart_mm200 != null && Math.abs(x.ecart_mm200) <= ech ? x.ecart_mm200 : null, null,
        x[fo] == null ? x.raison : `${x.devise} : ${sgn(x[fo], 2, " %")} · écart à la MM200 ${sgn(x.ecart_mm200, 2, " %")} · dernière valeur ${ddm(x.date)}`)).join("") || '<p class="muted">Force indisponible (force_devises.json absent : prochain run).</p>';
    };
    rendre();
    q("#foSrc").textContent = force ? `${force.source} · au ${ddm(lignes[0]?.date)}` : "";
  });

  bloc(q("#surp"), () => {
    const s = tm?.indice_surprise || {};
    const ordre = Object.keys(s).sort((a, b) => (s[a].rang ?? 99) - (s[b].rang ?? 99));   // rang calculé en Python
    q("#surp").innerHTML = ordre.filter(d => s[d]).map(d => hbar(`${d} <span class="small">n=${s[d].n ?? 0}</span>`, s[d].indice, 1.5, sgn(s[d].indice, 2), s[d].precedent, null, s[d].texte)).join("") || '<p class="muted">Indice de surprise indisponible.</p>';
  });

  bloc(q("#heat"), () => {
    const H = dos?.engrenages?.["5"]?.matrice_chaleur;
    if (!H) { q("#heat").innerHTML = `<tbody><tr><td class="muted">Corrélations indisponibles (dossier de l'engrenage 5 absent).</td></tr></tbody>`; return; }
    const hc = v => { if (v == null) return "background:var(--surface-2);color:var(--muted)"; const p = Math.round(Math.min(Math.abs(v), 1) * 70); return `background:color-mix(in srgb, ${v >= 0 ? "var(--accent)" : "var(--warn)"} ${p}%, var(--surface));color:${p > 45 ? "var(--surface)" : "var(--ink)"}`; };
    q("#heat").innerHTML = `<thead><tr><th>Devise</th>${H.colonnes.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
      H.lignes.map(l => `<tr><td style="font-weight:700;padding:4px 6px">${l.devise}</td>${l.valeurs.map((v, i) => `<td class="h" style="${hc(v)}" title="${v == null ? esc(l.raison || "corrélation n/d") : `précédent ${l.precedentes?.[i] != null ? sgn(l.precedentes[i], 2) : "n/d"} · percentile 5 ans ${l.percentiles?.[i] ?? "n/d"}`}">${v == null ? "n/d" : sgn(v, 2)}</td>`).join("")}</tr>`).join("") + "</tbody>";
    q("#heatSrc").textContent = `Source : ${H.source || "calcul Python, variations quotidiennes (Twelve Data, FRED)"} · corrélation n'est pas causalité`;
  });

  bloc(q("#mx"), () => {
    if (!tm) { q("#mx").innerHTML = `<tbody><tr><td class="muted">Tableau macro indisponible.</td></tr></tbody>`; return; }
    const dev = tm.devises || [];
    let html = `<thead><tr><th>Indicateur</th>${dev.map(d => `<th>${d}</th>`).join("")}</tr></thead><tbody>`;
    for (const i of tm.indicateurs || []) {
      html += `<tr><td>${esc(i.libelle)}</td>` + dev.map(d => {
        const c = tm.cellules?.[i.id]?.[d] || {}, a = c.Actuel || {}, pr = c["Précédent"] || {}, pv = c["Prévision"] || {};
        const brut = a.valeur ? String(a.valeur) : null;
        const princ = brut ? brut.replace(/\s*\[.*?\]/, "").replace(/\s*·.*$/, "") : null;
        const sec = brut && /·/.test(brut) ? brut.split("·").slice(1).join("·").trim() : null;
        const s = a.surprise && /[▲▼=]/.test(a.surprise) ? a.surprise : null;
        const bon = s === "▲" ? (i.sens === "inverse" ? "neg" : "pos") : s === "▼" ? (i.sens === "inverse" ? "pos" : "neg") : "muted";
        const titre = [a.texte, a.source, a.date ? ddm(a.date) : ""].filter(Boolean).join(" · ");
        const explique = a.etat && a.etat !== "valeur";   // état calculé en Python : une explication, pas une valeur
        const val = princ && !explique && !/^n\/d/.test(princ) ? esc(princ) : nd(brut || "valeur absente du registre");
        return `<td title="${esc(titre)}">${val}${s ? `<span class="s ${bon}">${s}</span>` : ""}${sec && !explique ? `<small>${esc(sec)}</small>` : ""}<small class="full">${pr.valeur && (!pr.etat || pr.etat === "valeur") && !/^n\/d/.test(pr.valeur) ? "préc. " + esc(String(pr.valeur).replace(/\s*\[.*?\]/, "")) : ""}</small>${pv.valeur && !/n\/d/.test(pv.valeur) && String(pv.valeur).length <= 40 ? `<small class="full">${esc(String(pv.valeur).replace("consensus à venir", "conso. à venir"))}</small>` : ""}</td>`;
      }).join("") + "</tr>";
    }
    q("#mx").innerHTML = html + "</tbody>";
  });

  bloc(q("#taux"), () => { q("#taux").innerHTML = tableEngrenage(dos?.engrenages?.["2"]); });

  bloc(q("#bcs"), () => {
    q("#bcs").innerHTML = (agenda?.banques_centrales || []).map(b => `<div class="card bc"><div class="who"><span>${esc(b.court)}</span><span>${b.devise}</span></div><b>${b.taux_texte ? esc(frTxt(b.taux_texte)) : nd(b.raison_taux)}</b><span class="src">${esc(b.type_taux || "")}${b.taux_secondaire ? " · " + esc(frTxt(b.taux_secondaire)) : ""}</span><span style="font-size:13px;margin-top:6px">${b.prochaine ? "Prochaine : " + dfr(b.prochaine) : "Date non publiée"}${b.cette_semaine ? ' <span class="chip warn" style="height:20px">cette semaine</span>' : ""}</span></div>`).join("");
  });

  bloc(q(".calc"), () => {
    const vp = rj?.risque?.valeurs_pip || {}, sel = q("#cPair");
    sel.innerHTML = Object.keys(vp).map(p => `<option>${p}</option>`).join("");
    if (vp["EUR/USD"]) sel.value = "EUR/USD";
    const calc = () => {   // outil (pas une donnée publiée) : le calcul de taille reste dans le navigateur
      const cap = +q("#cCap").value || 0, ri = +q("#cRis").value || 0, st = +q("#cStop").value || 1, p = vp[sel.value];
      const risque = cap * ri / 100, lots = p ? risque / (st * p.valeur_pip_usd_lot) : 0;
      q("#cOut").innerHTML = `<span class="small">Taille pour ${nf(risque, 0)} $ de risque</span><b>${nf(lots, 2)} lot${lots >= 2 ? "s" : ""}</b><span class="small">pip ${p ? nf(p.valeur_pip_usd_lot, 2) : "—"} $ par lot · ${nf(lots * 10, 1)} mini-lots</span>`;
    };
    ["cCap", "cRis", "cStop", "cPair"].forEach(id => q("#" + id).oninput = calc);
    calc();
    q("#cSrc").textContent = rj?.risque?.note || "Valeur du pip : cours du jour (Twelve Data), calcul Python.";
  });

  q("#detaille").appendChild(blocDetaille("Tableau macro détaillé", "tri, recherche, toutes les colonnes et sources", async () => {
    const m = await import("./tableau.js"); return m.pageTableauDeBord();
  }));
}

/* Tableau d'un engrenage (taux et écarts, dossiers) : un n/d montre « n/d » et sa raison AU SURVOL seulement. */
export function celluleEngrenage(c, col) {
  if (!c) return nd("donnée absente du dossier");
  if (c.valeur == null && !c.texte) return nd(c.raison);
  const u = c.unite ?? col.unite;
  const principal = c.texte_reference ? esc(c.texte_reference) : c.valeur == null ? (/^\d{4}-\d{2}-\d{2}/.test(c.texte) ? dfr(c.texte) : esc(c.texte)) : fv(c.valeur, u);
  const v4 = c.var_4s != null ? `<span class="small">4 sem. ${sgn(c.var_4s, u === "pb" || u === "%" ? 0 : 2, u === "pb" || u === "%" ? " pb" : "")}</span>` : "";
  return `<span title="${esc([c.source, c.date ? ddm(c.date) : "", c.note].filter(Boolean).join(" · "))}"><b style="font-weight:600">${principal}</b>${c.percentile_5a != null ? `<span class="small"> (p${c.percentile_5a})</span>` : ""}${c.secondaire ? `<br><span class="small">${esc(c.secondaire)}</span>` : ""}${v4 ? "<br>" + v4 : ""}</span>`;
}
export function tableEngrenage(e) {
  if (!e?.colonnes || !e?.lignes) return `<tbody><tr><td class="muted">Tableau indisponible.</td></tr></tbody>`;
  return `<thead><tr><th>Devise</th>${e.colonnes.map(c => `<th>${esc(c.libelle)}</th>`).join("")}</tr></thead><tbody>` +
    e.lignes.map(r => `<tr><td><b>${r.devise}</b></td>${e.colonnes.map(c => `<td style="min-width:110px">${celluleEngrenage(r.cellules?.[c.id], c)}</td>`).join("")}</tr>`).join("") + "</tbody>";
}
export { num };
