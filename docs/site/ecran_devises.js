/* Lot V7 — Devises (maquette #devises) : profil_devises.json (état, moteur, banque centrale, ancrages : Python),
   cours.json (graphique 6 mois), variation sur 20 séances : profil_devises.tendance_20s (Python). */
import { $, h, nf, sgn, esc, ddm, nd, classeEtat, donnees, bloc, graphique, blocDetaille } from "./v7_commun.js";

const SIX_MOIS = 183;

export async function ecranDevises(section, parametre) {
  section.innerHTML = `<div class="sec-head" data-fraicheur="profil"><h2>Qui mène, et pourquoi</h2><p>Ancrage, moteur du moment (60 séances), banque centrale</p></div>
    <div class="grid dvs" id="dvs"></div><p class="src" id="dvSrc"></p><div id="detaille"></div>`;
  const [profil, cours] = await Promise.all([donnees("profil_devises"), donnees("cours")]);
  const box = $("#dvs", section);
  if (!profil) { box.innerHTML = '<div class="card pad muted">Profil des devises indisponible (profil_devises.json absent : prochain run).</div>'; return; }
  const aDessiner = [];
  for (const d of profil.devises || []) {
    const carte = h("article", "card dv"); carte.dataset.devise = d.devise;
    bloc(carte, () => {
      const e = d.etat?.valeur || "n/d", c = cours?.devises?.[d.devise] || {};
      const pts = c.points || [], dernier = pts.length ? pts[pts.length - 1] : null;
      const depuis = dernier ? new Date(new Date(dernier[0]) - SIX_MOIS * 864e5).toISOString().slice(0, 10) : null;
      const t20 = d.tendance_20s || {}, dom = d.moteur?.dominant, r = dom?.r60 ?? null, w = r == null ? 0 : Math.min(Math.abs(r), 1) * 50;
      const decs = dernier && dernier[1] > 20 ? 2 : 4;
      carte.innerHTML = `<div class="dv-head"><div><div class="code">${d.devise}</div><div class="nm">${esc(d.nom)}</div></div><span class="chip ${classeEtat(e)}" title="${esc(d.etat?.raison || "")}"><span class="dot"></span>${esc(e)}</span></div>
        <div class="dv-px">${dernier ? `<b>${nf(dernier[1], decs)}</b><span class="${t20.pct > 0 ? "pos" : t20.pct < 0 ? "neg" : "muted"}" style="font-weight:600;font-size:13px">${t20.pct == null ? nd(t20.raison) : sgn(t20.pct, 2, " %")} sur 20 séances</span>` : `<span class="muted">Cours ${nd("série absente de cours.json")}</span>`}</div>
        <div class="src" style="padding:2px 20px 0">${esc(c.libelle || "")}${dernier ? " · au " + ddm(dernier[0]) : ""}</div>
        <div class="chart" data-c="${d.devise}" role="img" aria-label="Cours ${d.devise} sur 6 mois"></div>
        <div class="dv-body">
          <div class="kv"><span>Moteur du moment</span><span><b>${dom ? esc(dom.libelle) : "aucun moteur net"}</b> ${r != null ? `<span class="muted">${sgn(r, 2)} sur 60 séances</span>` : ""}<div class="corr" title="${esc(d.moteur?.texte || "")}"><i style="${r >= 0 ? "left:50%" : "right:50%"};width:${w}%;background:${r >= 0 ? "var(--accent)" : "var(--warn)"}"></i></div></span>
          <span>Banque centrale</span><span>${esc(d.banque_centrale?.texte || "n/d")}</span></div>
          <div class="ancs full">${(d.ancrages || []).map(a => `<span class="chip ${a.verdict === "confirmé" ? "up" : a.verdict === "contredit" ? "dn" : ""}" title="${esc((a.texte || "") + (a.mesure ? " · " + a.mesure : ""))}">${esc(a.libelle)} · ${esc(a.verdict || "n/d")}</span>`).join("")}</div>
          <div class="muted full" style="font-size:13px">${esc(d.etat?.raison || "")}</div>
        </div>`;
      if (pts.length) aDessiner.push([carte.querySelector(".chart"), pts.filter(p => p[0] >= depuis), decs]);
    });
    box.appendChild(carte);
  }
  $("#dvSrc", section).textContent = `${cours?.source || ""} · ${profil.note || ""} · ${profil.regle_etat || ""}`;
  // Graphiques : l'écran est visible quand cette fonction tourne (initialisation à l'ouverture de l'onglet)
  for (const [div, pts, decs] of aDessiner) graphique(div, [{ l: "", p: pts }], decs, { handleScroll: false, handleScale: false });
  const fiches = blocDetaille("Fiches détaillées des devises", "scores, dossiers, graphiques annotés", async arg => {
    const m = await import("./devises.js"); return m.pageDevises(arg);
  });
  $("#detaille", section).appendChild(fiches);

  // Adresse de détail #devises/EUR : carte EUR mise en avant, fiche détaillée EUR ouverte (analyse, indicateurs, points de vigilance)
  let charge = false, minuteries = [];
  section.allerA = async code => {
    code = String(code || "").toUpperCase();
    minuteries.forEach(clearTimeout); minuteries = [];   // une nouvelle adresse annule l'ancrage de la précédente
    const carte = box.querySelector(`[data-devise="${code}"]`);
    if (!carte) return false;
    box.querySelectorAll(".dv.cible").forEach(c => c.classList.remove("cible"));
    carte.classList.add("cible");
    document.documentElement.dataset.vue = "complete";
    if (!charge) { charge = true; await fiches.ouvrirAvec(code); }
    else { fiches.open = true; }
    const f = section.querySelector(`#fiche-${code}`);
    if (f) {
      f.open = true;
      const voir = f.closest("details.voir-detail"); if (voir) voir.open = true;
      // Défilement immédiat, puis maintenu pendant 2,5 s (graphiques et données qui arrivent au-dessus), sauf si
      // l'utilisateur fait défiler lui-même.
      f.scrollIntoView({ block: "start" });
      let libre = false; const stop = () => { libre = true; };
      for (const ev of ["wheel", "touchstart", "keydown", "mousedown"]) addEventListener(ev, stop, { once: true, passive: true });
      minuteries = [300, 800, 1500, 2500].map(ms => setTimeout(() => { if (!libre && f.isConnected && location.hash === `#devises/${code}`) f.scrollIntoView({ block: "start" }); }, ms));
    } else carte.scrollIntoView({ block: "start" });
    return true;
  };
  if (parametre) section.cible = await section.allerA(parametre);
}
