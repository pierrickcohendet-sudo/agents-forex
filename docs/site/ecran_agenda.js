/* Lot V7 — Agenda (maquette #agenda) : agenda.json. Couleur du « publié » : sens et favorable calculés en Python
   (champ ecart). Le globe des banques centrales est conservé en vue complète, sous le ruban. */
import { $, h, esc, dfr, ddm, jourSem, frTxt, donnees, blocDetaille } from "./v7_commun.js";

export async function ecranAgenda(section) {
  section.innerHTML = `<div class="sec-head"><h2>Agenda</h2>
      <div class="filt"><button class="switch" id="fortBtn" type="button" aria-pressed="false"><i></i><span>Fort impact seulement</span></button></div></div>
    <div class="days" id="days" role="group" aria-label="Jours"></div>
    <div class="card pad full globe-carte"><div class="sec-head"><h3>Banques centrales</h3><p id="globeTxt">Orange : réunion cette semaine ; bleu : plus tard. Cliquer une banque ouvre sa fiche.</p></div><div class="ag-globe-zone grand" id="globe"><div class="skel" style="height:280px"></div></div><p class="src" id="globeNote"></p></div>
    <div class="ag">
      <div class="card" style="overflow:hidden"><div id="evs"></div></div>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div class="card pad full" style="display:flex;flex-direction:column;gap:10px"><h3>Prochaines réunions</h3><div id="bcNext" style="display:flex;flex-direction:column;gap:8px;font-size:13.5px"></div></div>
        <div class="card pad full" style="display:flex;flex-direction:column;gap:10px"><h3>Grands rendez-vous</h3><div id="grv" style="display:flex;flex-direction:column;gap:10px;font-size:13.5px"></div></div>
      </div>
    </div>
    <p class="src" id="agSrc"></p><div id="detaille"></div>`;
  const q = s => $(s, section);
  const a = await donnees("agenda");
  if (!a) { q("#evs").innerHTML = '<div class="empty">Agenda indisponible (agenda.json absent : prochain run).</div>'; return; }
  const jours = a.jours || [];
  let choisi = jours.some(j => j.date === a.aujourdhui) ? a.aujourdhui : jours[0]?.date, fortSeul = false;

  function rendre() {
    const box = q("#days"); box.innerHTML = "";
    for (const j of jours) {
      const evs = j.evenements || [], dw = new Date(j.date + "T12:00:00Z").getUTCDay();
      if ((dw === 0 || dw === 6) && !evs.length) continue;
      const f = evs.filter(e => e.impact === "fort").length;
      const b = h("button", "day" + (j.date === a.aujourdhui ? " today" : ""), `<span class="dn">${jourSem(j.date).slice(0, 3)}.</span><span class="dd">${Number(j.date.slice(8, 10))}</span>
        <span class="bars">${evs.slice(0, 14).map(e => `<i class="${e.impact === "fort" ? "f" : ""}" style="height:${e.impact === "fort" ? 14 : e.impact === "moyen" ? 9 : 5}px"></i>`).join("")}</span><span class="src">${evs.length} publi. · ${f} fort${f > 1 ? "s" : ""}</span>`);
      b.type = "button"; b.setAttribute("aria-pressed", j.date === choisi);
      b.onclick = () => { choisi = j.date; rendre(); };
      box.appendChild(b);
    }
    const j = jours.find(x => x.date === choisi) || { evenements: [] };
    const evs = (j.evenements || []).filter(e => !fortSeul || e.impact === "fort");
    q("#evs").innerHTML = `<div class="pad" style="padding-bottom:8px;display:flex;justify-content:space-between;align-items:baseline"><h3 style="text-transform:capitalize">${choisi ? jourSem(choisi) + " " + dfr(choisi) : ""}</h3><span class="src">Heure de Paris</span></div>` +
      (evs.length ? evs.map(e => {
        const ec = e.ecart || {}, sur = !e.publie || !ec.sens ? "" : ec.sens === "conforme" ? "muted" : ec.favorable === true ? "pos" : ec.favorable === false ? "neg" : "";
        const nb = { fort: 3, moyen: 2, faible: 1 }[e.impact] || 0;
        return `<div class="ev"><span class="h">${esc(e.heure_paris || "—")}</span><span class="cur">${esc(e.devise)}</span>
          <div class="t"><b>${esc(e.evenement)}</b><small>${e.publie ? `Publié <b class="${sur}" title="${esc(ec.texte || "")}">${esc(frTxt(e.publie))}</b> · ` : ""}${e.consensus ? "consensus " + esc(frTxt(e.consensus)) + " · " : ""}${e.precedent ? "précédent " + esc(frTxt(e.precedent)) : esc(e.type || "")}</small></div>
          <span class="imp ${e.impact}" title="Impact ${esc(e.impact)}">${[1, 2, 3].map(i => `<i class="${i <= nb ? "on" : ""}" style="${i > nb ? "opacity:.35" : ""}"></i>`).join("")}</span></div>`;
      }).join("") : `<div class="empty">${fortSeul ? "Aucune publication à fort impact ce jour-là." : "Aucune publication ce jour-là."}</div>`);
  }
  q("#fortBtn").onclick = () => { fortSeul = !fortSeul; q("#fortBtn").setAttribute("aria-pressed", fortSeul); rendre(); };
  rendre();
  const bcs = a.banques_centrales || [];
  q("#bcNext").innerHTML = bcs.filter(b => b.prochaine).sort((x, y) => x.prochaine.localeCompare(y.prochaine)).slice(0, 6)
    .map(b => `<div style="display:flex;justify-content:space-between;gap:8px"><span><b>${esc(b.court)}</b> <span class="muted">${b.devise}</span></span><span>${dfr(b.prochaine)}${b.cette_semaine ? ' <span class="chip warn" style="height:20px">cette semaine</span>' : ""}</span></div>`).join("");
  q("#grv").innerHTML = (a.grands_rendez_vous || []).map(g => `<div><div class="src">${dfr(g.date)}${g.fin ? " → " + dfr(g.fin) : ""} · ${(g.devises || []).join(", ")}</div><div title="${esc(g.source || "")}">${esc(g.titre)}</div></div>`).join("")
    || `<span class="muted">${esc(a.grands_rendez_vous_absents || "Aucun grand rendez-vous recensé.")}</span>`;
  q("#agSrc").textContent = `Sources : ${Object.keys(a.sources || {}).join(", ") || "ForexFactory et sites officiels"} · mis à jour ${ddm(a.genere_le)} ${String(a.genere_le || "").slice(11, 16)} UTC`;

  // Globe (vue complète) : module existant, restylé par les tokens
  import("./agenda.js").then(m => m.dessinerGlobe(q("#globe"), bcs)).then(() => {
    q("#globeNote").textContent = "Glisser pour tourner le globe · rotation coupée avec « moins d'animations ».";
  }).catch(e => { console.warn(e); q("#globe").innerHTML = '<p class="muted">Globe indisponible (carte non chargée) : la liste des réunions reste complète.</p>'; });

  q("#detaille").appendChild(blocDetaille("Agenda détaillé", "semaine complète, prises de parole, sources par champ, export de calendrier", async () => {
    const m = await import("./agenda.js"); return m.pageAgenda();
  }));
}
