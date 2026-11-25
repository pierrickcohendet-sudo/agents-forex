/* Lot V14 — Agenda façon ForexFactory (maquette_v14_agenda.html). Données : agenda.json (Python) ; le navigateur filtre
   et affiche seulement. Couleur du réel : ecart.favorable (calculé en Python : un chômage plus bas que prévu est vert).
   Adresses : #agenda (semaine en cours), #agenda/hier|jour|dem|sem|suiv (période), #agenda/USD (une devise),
   #agenda/e=<ff_id> (panneau d'une publication), #agenda/jour=AAAA-MM-JJ (ancienne adresse : le jour dans sa semaine).
   Filtres (impact, devises, publications passées) mémorisés dans le navigateur. */
import { esc, frTxt, ddm, jourSem, donnees, blocDetaille } from "./v7_commun.js";
import { nomMoteur } from "./moteurs.js";

const DEVS = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"];
const IMPS = ["fort", "moyen", "faible"];
const PERIODES = { hier: "Hier", jour: "Aujourd'hui", dem: "Demain", sem: "Cette semaine", suiv: "Semaine prochaine" };
const CLE = "fxdesk-agenda-filtres";
const paris = d => d.toLocaleDateString("sv-SE", { timeZone: "Europe/Paris" });
const ajoute = (d, n) => new Date(Date.parse(d + "T12:00:00Z") + n * 864e5).toISOString().slice(0, 10);
const lundi = d => { const w = new Date(d + "T12:00:00Z").getUTCDay() || 7; return ajoute(d, 1 - w); };
const nb = s => { const m = String(s ?? "").replace(",", ".").match(/-?\d+(\.\d+)?/); return m ? parseFloat(m[0]) : null; };
const heureP = iso => new Date(iso).toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit" });

/* Lignes affichées : publications, puis jours fériés et événements « All » (pastille Férié / Événement). */
export function lignes(a) {
  const ev = [];
  for (const j of a.jours || []) {
    for (const e of j.evenements || []) ev.push({ ...e, cle: e.ff_id ? `ff${e.ff_id}` : `${e.date_paris}|${e.devise}|${e.evenement_en}` });
    for (const x of j.discrets || []) ev.push({
      glob: true, cle: `g${(x.ff || [])[0]?.ff_id || x.date_paris + x.texte}`, date_paris: x.date_paris, iso_utc: x.iso_utc || x.date_paris + "T00:00+00:00",
      heure_paris: x.heure_paris || "journée", devise: (x.devises || []).length === 1 && DEVS.includes(x.devises[0]) ? x.devises[0] : "Toutes",
      evenement: x.nom_ferie || x.texte, evenement_en: x.texte_en, type: x.type || "Férié", impact: "vac",
      ff_url: (x.ff || [])[0]?.ff_url, ff_id: (x.ff || [])[0]?.ff_id, source: x.source, devises: x.devises });
  }
  return ev.sort((p, q) => String(p.iso_utc).localeCompare(String(q.iso_utc)));
}

export function bornes(periode, aujourd) {
  const m = lundi(aujourd);
  return { hier: [ajoute(aujourd, -1), ajoute(aujourd, -1)], jour: [aujourd, aujourd], dem: [ajoute(aujourd, 1), ajoute(aujourd, 1)],
    sem: [m, ajoute(m, 6)], suiv: [ajoute(m, 7), ajoute(m, 13)] }[periode] || [m, ajoute(m, 6)];
}

const imp = i => `<span class="ag-im ${i}" title="${i === "vac" ? "férié ou événement" : "impact " + i}"><i></i><i></i><i></i></span>`;
const classeReel = e => !e.publie ? "" : e.ecart?.sens === "conforme" ? "" : e.ecart?.favorable === true ? "up" : e.ecart?.favorable === false ? "dn" : "";

function historique(e) {
  const hst = e.historique || [];
  const vals = hst.map(x => nb(x[1])).concat(e.publie ? [nb(e.publie)] : []).filter(v => v != null);
  const mn = Math.min(0, ...vals), mx = Math.max(0, ...vals), H = v => v == null ? 2 : 6 + (mx > mn ? (Math.abs(v - 0) / Math.max(Math.abs(mx), Math.abs(mn))) : .5) * 56;
  const barres = hst.length >= 2 || (hst.length && e.publie) ? `<div class="ag-bars" role="img" aria-label="Historique des valeurs publiées">${hst.map(x => {
    const v = nb(x[1]); return `<div><span>${esc(frTxt(x[1]))}</span><i class="${v < 0 ? "neg" : ""}" style="height:${H(v)}px"></i><span>${ddm(x[0])}</span></div>`; }).join("")}${e.publie
    ? `<div><span>${esc(frTxt(e.publie))}</span><i class="now" style="height:${H(nb(e.publie))}px"></i><span>ce jour</span></div>` : ""}</div>` : "";
  const tableau = hst.length ? `<table class="ag-hist"><tr><th>Date</th><th>Réel</th><th>Prévision</th></tr>${e.publie ? `<tr><td><b>${ddm(e.date_paris)} (ce jour)</b></td><td><b>${esc(frTxt(e.publie))}</b></td><td>${esc(frTxt(e.consensus)) || "—"}</td></tr>` : ""}${hst.slice().reverse()
    .map(x => `<tr><td>${ddm(x[0])}</td><td>${esc(frTxt(x[1]))}</td><td>${esc(frTxt(x[2])) || "—"}</td></tr>`).join("")}</table>`
    : `<span>Historique en construction : l'archive du site commence le 01/10/2026 ; la reprise des 12 derniers mois de ForexFactory (2 mois par jour) le complète.</span>`;
  return `<div><span class="ag-k">Historique</span>${barres}${tableau}${hst.length && hst.length < 3 ? '<span class="ag-src">Moins de 3 valeurs passées : historique encore court.</span>' : ""}</div>`;
}

function consequences(e) {
  const ec = e.ecart || {};
  const res = ec.texte ? `<span><b>Résultat :</b> ${esc(ec.texte)}${ec.favorable === true ? ", favorable à la devise" : ec.favorable === false ? ", défavorable à la devise" : ""}.</span>`
    : e.publie ? "<span>Pas de prévision : comparaison impossible.</span>"
    : `<span><b>Prévision :</b> ${esc(frTxt(e.consensus)) || "n/d"} · <b>${esc(e.precedent_texte || "précédent n/d")}</b>.</span>`;
  const r = e.reaction?.cote || {}, k = ec.sens === "en dessous" ? "au_dessous" : "au_dessus", x = r[k];
  const rea = x && x.n ? `<span><b>Réaction passée :</b> après ${x.n} publication${x.n > 1 ? "s" : ""} ${k === "au_dessus" ? "au-dessus" : "en dessous"} de la prévision, ${esc(e.devise)} a varié de ${frTxt(Number(x.mediane).toFixed(2))} % en médiane la séance suivante${x.faible ? " <b>(échantillon trop petit pour conclure)</b>" : ""}.</span>`
    : e.raison_reaction ? `<span class="ag-src">Réaction passée : ${esc(e.raison_reaction)}.</span>` : "";
  return `<div><span class="ag-k">Ce que ça change</span>${res}
    ${e.engrenage ? `<span><b>Moteur :</b> ${esc(nomMoteur(e.engrenage))}.</span>` : ""}${e.pourquoi ? `<span>${esc(e.pourquoi)}</span>` : ""}${rea}
    ${e.impact_releve ? `<span class="ag-src">Impact : ${esc(e.impact_releve)}.</span>` : ""}</div>`;
}

const court = s => String(s || "").replace(/ \((extraction|déjà|calendrier|adjudications|API)[^)]*\)/g, "").replace(/, page « mois »/, " (page « mois »)").trim();
function sources(e) {
  const rel = e.publie_releve;
  return `<div><span class="ag-k">Sources et liens</span><span>${esc(e.evenement_en || e.evenement)}</span>
    <span class="ag-src">Valeurs : ${esc([...new Set((e.sources || [e.source]).filter(Boolean).map(court))].join(" ; ") || "n/d")}.${rel ? ` Réel relevé ${rel.le ? "le " + ddm(rel.le) + " à " + String(rel.le).slice(11, 16) + " UTC" : ""} (${esc(court(rel.source) || "source n/d")}).` : ""} Heure : ${e.heure_connue === false ? "non communiquée" : esc(e.heure_paris) + " (Paris)"}.</span>
    ${e.precedent_texte ? `<span class="ag-src">${esc(e.precedent_texte)} (ForexFactory : « previous » = valeur publiée à l'origine, « revision » = valeur révisée).</span>` : ""}
    ${e.ff_url ? `<a href="${esc(e.ff_url)}" target="_blank" rel="noopener">Ouvrir sur ForexFactory ↗</a>` : `<span class="ag-src">${esc(e.ff_raison || "pas de lien ForexFactory")}</span>${e.lien_source ? `<a href="${esc(e.lien_source)}" target="_blank" rel="noopener">Ouvrir la source officielle ↗</a>` : ""}`}
    ${e.engrenage ? `<a href="#engrenages/c${e.engrenage}">Voir dans le documentaire ›</a>` : ""}</div>`;
}

function lienFF(e) {
  if (e.ff_url) return `<a class="ag-lk" href="${esc(e.ff_url)}" target="_blank" rel="noopener" title="Ouvrir sur ForexFactory" data-stop>FF ↗</a>`;
  if (e.lien_source) return `<a class="ag-lk" href="${esc(e.lien_source)}" target="_blank" rel="noopener" title="${esc(e.ff_raison || "source officielle")}" data-stop>source ↗</a>`;
  return `<span class="ag-lk" title="${esc(e.ff_raison || "pas de lien")}">—</span>`;
}

export async function ecranAgenda(section, parametre) {
  section.classList.add("ag14");
  section.innerHTML = `<div class="ag-head" data-fraicheur="agenda"><div><span class="eyebrow">Agenda économique</span><h2 id="agTtl">Cette semaine</h2>
      <p>Toutes les publications des 9 devises suivies, comme sur ForexFactory : heure de Paris, impact, réel, prévision et précédent. Un clic sur une ligne ouvre l'historique et ce que la publication change pour la devise.</p></div>
      <div class="ag-legend"><span>${imp("fort")} fort</span><span>${imp("moyen")} moyen</span><span>${imp("faible")} faible</span><span>${imp("vac")} férié, événement</span><span><b class="pos">vert</b> / <b class="neg">rouge</b> : réel bon / mauvais pour la devise</span></div></div>
    <div class="ag-bar" id="agBar">
      <div class="ag-row"><div class="ag-seg" id="agPer" role="group" aria-label="Période">${Object.entries(PERIODES).map(([k, v]) => `<button type="button" data-p="${k}" aria-pressed="false">${v}</button>`).join("")}</div>
        <button type="button" class="ag-ch" id="agPast" aria-pressed="true">Afficher les publications passées</button></div>
      <div class="ag-row"><span class="ag-lbl">Impact</span><span id="agImp" class="ag-devs">${IMPS.map(i => `<button type="button" class="ag-ch" data-i="${i}" aria-pressed="true">${imp(i)}${i}</button>`).join("")}</span>
        <span class="ag-lbl" style="margin-left:10px">Devises</span><span id="agDev" class="ag-devs" title="Double-clic : cette devise seule">${DEVS.map(d => `<button type="button" class="ag-ch" data-d="${d}" aria-pressed="true">${d}</button>`).join("")}</span></div>
    </div>
    <div class="ag-now" id="agNow" aria-live="polite"></div>
    <div class="card ag-tblwrap"><table class="ag-tbl"><thead><tr><th>Heure</th><th>Devise</th><th>Impact</th><th>Publication</th><th class="n">Réel</th><th class="n">Prévision</th><th class="n">Précédent</th><th></th></tr></thead><tbody id="agTb"></tbody></table></div>
    <p class="ag-note" id="agNote"></p>
    <div class="card pad full globe-carte"><div class="sec-head"><h3>Banques centrales</h3><p>Orange : réunion cette semaine ; bleu : plus tard. Cliquer une banque ouvre sa fiche.</p></div><div class="ag-globe-zone grand" id="globe"><div class="skel" style="height:280px"></div></div><p class="src" id="globeNote"></p></div>
    <div class="cols2 full"><div class="card pad" style="display:flex;flex-direction:column;gap:10px"><h3>Prochaines réunions</h3><div id="bcNext" style="display:flex;flex-direction:column;gap:8px;font-size:13.5px"></div></div>
      <div class="card pad" style="display:flex;flex-direction:column;gap:10px"><h3>Grands rendez-vous</h3><div id="grv" style="display:flex;flex-direction:column;gap:10px;font-size:13.5px"></div></div></div>
    <div id="detaille"></div>`;
  const q = s => section.querySelector(s);
  const a = await donnees("agenda");
  if (!a) { q("#agTb").innerHTML = '<tr><td colspan="8" class="ag-empty">Agenda indisponible (agenda.json absent : prochain run).</td></tr>'; return; }
  const EV = lignes(a);
  let memo = {};
  try { memo = JSON.parse(localStorage.getItem(CLE) || "{}") || {}; } catch (e) { memo = {}; }
  const st = { p: "sem", imp: new Set(memo.imp || IMPS), dev: new Set(memo.dev || DEVS), passe: memo.passe !== false, ouvert: null };
  const garder = () => { try { localStorage.setItem(CLE, JSON.stringify({ imp: [...st.imp], dev: [...st.dev], passe: st.passe })); } catch (e) { /* préférence seulement */ } };

  function visible(e) {
    if (e.glob) return true;
    return st.imp.has(e.impact) && st.dev.has(e.devise);
  }
  function rendre() {
    const maintenant = Date.now(), aujourd = paris(new Date());
    const [d1, d2] = bornes(st.p, aujourd);
    const ev = EV.filter(e => e.date_paris >= d1 && e.date_paris <= d2 && visible(e) && (st.passe || e.glob || !e.publie && Date.parse(e.iso_utc) >= maintenant - 5 * 60e3));
    q("#agTtl").textContent = PERIODES[st.p] + ` · ${d1 === d2 ? jourSem(d1) + " " + ddm(d1) : ddm(d1) + " au " + ddm(st.p === "sem" || st.p === "suiv" ? ajoute(d2, -2) : d2)}`;
    section.querySelectorAll("#agPer button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.p === st.p)));
    section.querySelectorAll("#agImp button").forEach(b => b.setAttribute("aria-pressed", String(st.imp.has(b.dataset.i))));
    section.querySelectorAll("#agDev button").forEach(b => b.setAttribute("aria-pressed", String(st.dev.has(b.dataset.d))));
    q("#agPast").setAttribute("aria-pressed", String(st.passe));
    let html = "", dernier = "", ligneFaite = false;
    for (const e of ev) {
      if (e.date_paris !== dernier) {
        dernier = e.date_paris;
        const n = ev.filter(x => x.date_paris === e.date_paris && !x.glob).length;
        html += `<tr class="ag-day"><td colspan="8">${jourSem(e.date_paris)} ${ddm(e.date_paris)}${e.date_paris === aujourd ? " · aujourd'hui" : ""}<span>${n} publication${n > 1 ? "s" : ""}</span></td></tr>`;
      }
      const t = Date.parse(e.iso_utc);
      if (!ligneFaite && t > maintenant && (e.date_paris === aujourd || ev[0] !== e)) {
        ligneFaite = true;
        html += `<tr class="ag-nowline" aria-hidden="true"><td colspan="8" data-t="${heureP(new Date(maintenant).toISOString())} maintenant"></td></tr>`;
      }
      const attendu = !e.glob && !e.publie && t < maintenant && e.type === "Chiffre";
      const tag = e.glob ? `<span class="ag-tag vac">${esc(e.type)}</span>` : e.type && e.type !== "Chiffre" ? `<span class="ag-tag">${esc(e.type)}</span>` : "";
      const rel = e.impact_releve ? `<span class="ag-tag" title="${esc(e.impact_releve)}">importance relevée</span>` : "";
      const reel = e.publie ? esc(frTxt(e.publie)) : attendu ? '<span class="muted">en attente</span>' : "";
      const prec = e.precedent ? esc(frTxt(e.precedent)) + (e.revision && String(e.revision) !== String(e.precedent) ? `<span class="ag-rev" title="valeur révisée">révisé ${esc(frTxt(e.revision))}</span>` : "") : "";
      html += `<tr class="ag-ev ${e.publie ? "past" : ""} ${e.glob ? "ag-glob" : ""} ${st.ouvert === e.cle ? "open" : ""}" data-k="${esc(e.cle)}" tabindex="0" aria-expanded="${st.ouvert === e.cle}">
        <td class="ag-t">${e.heure_connue === false || e.heure_paris === "journée" ? "Journée" : esc(e.heure_paris)}</td><td><span class="ag-cur">${esc(e.devise)}</span></td><td>${imp(e.impact)}</td>
        <td class="ag-name"><b>${esc(e.evenement)}</b>${tag}${rel}${e.evenement_en && e.evenement_en !== e.evenement ? `<small>${esc(e.evenement_en)}</small>` : ""}</td>
        <td class="n ag-vals">${e.glob ? "" : `<span class="ag-v r ${classeReel(e)}" data-l="Réel" title="${esc(e.ecart?.texte || "")}">${reel}</span><span class="ag-v ag-mob" data-l="Prév.">${esc(frTxt(e.consensus))}</span><span class="ag-v ag-mob" data-l="Préc.">${prec}</span>`}</td>
        <td class="n"><span class="ag-v">${e.glob ? "" : esc(frTxt(e.consensus))}</span></td>
        <td class="n"><span class="ag-v">${e.glob ? "" : prec}</span></td>
        <td>${lienFF(e)}</td></tr>`;
      if (st.ouvert === e.cle) html += e.glob ? `<tr class="ag-det"><td colspan="8"><div class="ag-dg"><div><span class="ag-k">${esc(e.type)}</span><span>${esc(e.evenement)}${e.evenement_en ? ` (${esc(e.evenement_en)})` : ""}.</span><span class="ag-src">Devises : ${esc((e.devises || []).join(", "))}. Source : ${esc(e.source || "n/d")}.</span>${e.ff_url ? `<a href="${esc(e.ff_url)}" target="_blank" rel="noopener">Ouvrir sur ForexFactory ↗</a>` : ""}</div></div></td></tr>`
        : `<tr class="ag-det"><td colspan="8"><div class="ag-dg">${historique(e)}${consequences(e)}${sources(e)}</div></td></tr>`;
    }
    q("#agTb").innerHTML = html || '<tr><td colspan="8" class="ag-empty">Aucune publication avec ces filtres.</td></tr>';
    bandeau();
    document.documentElement.style.setProperty("--ag14-barre", (q("#agBar").offsetHeight || 0) + "px");
  }
  function bandeau() {
    const maintenant = Date.now();
    const futurs = EV.filter(e => !e.glob && !e.publie && Date.parse(e.iso_utc) > maintenant);
    const nx = futurs.find(e => visible(e) && e.heure_connue !== false), nf = futurs.find(e => e.impact === "fort" && e.heure_connue !== false);
    const cd = e => { const m = Math.round((Date.parse(e.iso_utc) - maintenant) / 6e4); return m < 60 ? `dans ${m} min` : m < 1440 ? `dans ${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}` : `${jourSem(e.date_paris)} ${ddm(e.date_paris)} à ${e.heure_paris}`; };
    q("#agNow").innerHTML = (nx ? `<span class="ag-dim">Prochaine publication</span><b>${cd(nx)}</b><span><span class="ag-cur">${esc(nx.devise)}</span> ${esc(nx.evenement)}${nx.consensus ? " · prévision " + esc(frTxt(nx.consensus)) : ""}</span>`
      : "<span>Aucune publication à venir avec ces filtres.</span>")
      + (nf && nf !== nx ? `<span class="ag-dim" style="margin-left:auto">Prochaine forte : <b style="font-size:13px">${cd(nf)}</b> ${esc(nf.devise)} ${esc(nf.evenement)}</span>` : "");
  }
  function ouvrir(cle, defiler = true) {
    const e = EV.find(x => x.cle === cle || String(x.ff_id) === String(cle).replace(/^ff/, ""));
    if (!e) return false;
    const aujourd = paris(new Date());
    st.p = Object.keys(PERIODES).find(p => { const [a1, a2] = bornes(p, aujourd); return e.date_paris >= a1 && e.date_paris <= a2 && (p === "sem" || p === "suiv"); }) || st.p;
    if (!visible(e)) { st.imp.add(e.impact); st.dev.add(e.devise); }
    st.passe = true; st.ouvert = e.cle; rendre();
    if (defiler) q(`tr[data-k="${CSS.escape(e.cle)}"]`)?.scrollIntoView({ block: "center" });
    return true;
  }
  q("#agPer").onclick = ev => { const b = ev.target.closest("button"); if (!b) return; st.p = b.dataset.p; st.ouvert = null; history.replaceState(null, "", "#agenda/" + st.p); rendre(); };
  q("#agPast").onclick = () => { st.passe = !st.passe; garder(); rendre(); };
  q("#agImp").onclick = ev => { const b = ev.target.closest("button"); if (!b) return; const i = b.dataset.i; st.imp.has(i) ? st.imp.delete(i) : st.imp.add(i); garder(); rendre(); };
  let clic = null;
  q("#agDev").onclick = ev => { const b = ev.target.closest("button"); if (!b) return; const d = b.dataset.d;
    if (ev.detail === 2) { clearTimeout(clic); st.dev = new Set([d]); garder(); rendre(); return; }   // double-clic : cette devise seule
    clearTimeout(clic); clic = setTimeout(() => { st.dev.has(d) ? st.dev.delete(d) : st.dev.add(d); garder(); rendre(); }, 220); };
  const basculer = tr => { const k = tr.dataset.k; st.ouvert = st.ouvert === k ? null : k; rendre(); };
  q("#agTb").onclick = ev => { if (ev.target.closest("[data-stop]")) return; const tr = ev.target.closest("tr.ag-ev"); if (tr) basculer(tr); };
  q("#agTb").onkeydown = ev => { if (ev.key !== "Enter" && ev.key !== " ") return; const tr = ev.target.closest("tr.ag-ev"); if (tr) { ev.preventDefault(); basculer(tr); } };
  addEventListener("resize", () => document.documentElement.style.setProperty("--ag14-barre", (q("#agBar")?.offsetHeight || 0) + "px"));
  const minuteur = setInterval(() => { if (!section.isConnected) return clearInterval(minuteur); if (section.classList.contains("on")) bandeau(); }, 60e3);

  section.allerA = async p => {
    p = p || "";
    if (PERIODES[p]) { st.p = p; st.ouvert = null; rendre(); return false; }
    if (DEVS.includes(p.toUpperCase())) { st.dev = new Set([p.toUpperCase()]); garder(); rendre(); return false; }
    const m = p.match(/^e=(\d+)$/); if (m) return ouvrir("ff" + m[1]);
    const j = p.match(/^jour=(\d{4}-\d{2}-\d{2})$/);
    if (j) { const aujourd = paris(new Date()); st.p = j[1] >= bornes("suiv", aujourd)[0] ? "suiv" : "sem"; rendre();
      q(`tr.ag-ev[data-k]`) && [...section.querySelectorAll("tr.ag-day td")].find(td => td.textContent.includes(ddm(j[1])))?.scrollIntoView({ block: "start" }); return true; }
    return false;
  };
  section.choisirJour = d => section.allerA("jour=" + d);
  rendre();
  if (parametre) section.cible = await section.allerA(parametre);

  const gen = a.genere_le ? new Date(a.genere_le).toLocaleString("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "n/d";
  const ff = a.ff || {};
  q("#agNote").innerHTML = `Source : ForexFactory, complétée par les instituts officiels. Le réel apparaît au run suivant, avec quelques minutes à quelques heures de décalage ; le lien ↗ donne le chiffre en direct. Heures de Paris. Données du site au ${esc(gen)}${ff.avec_lien != null ? ` · ${ff.avec_lien} publications avec un lien ForexFactory, ${ff.sans_lien} sans (source officielle)` : ""}${ff.historique ? ` · historique repris : ${ff.historique.n_lus}/${ff.historique.n_total} mois` : ""}. Aide à la décision, jamais un ordre.`;

  // Vue complète : banques centrales (globe), prochaines réunions, grands rendez-vous, agenda détaillé
  const bcs = a.banques_centrales || [];
  q("#bcNext").innerHTML = bcs.filter(b => b.prochaine).sort((x, y) => x.prochaine.localeCompare(y.prochaine)).slice(0, 6)
    .map(b => `<div style="display:flex;justify-content:space-between;gap:8px"><span><b>${esc(b.court)}</b> <span class="muted">${b.devise}</span></span><span>${ddm(b.prochaine)}${b.cette_semaine ? ' <span class="chip warn" style="height:20px">cette semaine</span>' : ""}</span></div>`).join("");
  q("#grv").innerHTML = (a.grands_rendez_vous || []).map(g => `<div><div class="src">${ddm(g.date)}${g.fin ? " → " + ddm(g.fin) : ""} · ${(g.devises || []).join(", ")}</div><div title="${esc(g.source || "")}">${esc(g.titre)}</div></div>`).join("")
    || `<span class="muted">${esc(a.grands_rendez_vous_absents || "Aucun grand rendez-vous recensé.")}</span>`;
  import("./agenda.js").then(m => m.dessinerGlobe(q("#globe"), bcs)).then(() => {
    q("#globeNote").textContent = "Glisser pour tourner le globe · rotation coupée avec « moins d'animations ».";
  }).catch(e => { console.warn(e); q("#globe").innerHTML = '<p class="muted">Globe indisponible (carte non chargée) : la liste des réunions reste complète.</p>'; });
  q("#detaille").appendChild(blocDetaille("Agenda détaillé", "semaine complète, prises de parole, sources par champ, export de calendrier", async () => {
    const m = await import("./agenda.js"); return m.pageAgenda();
  }));
}
