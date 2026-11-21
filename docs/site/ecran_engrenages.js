/* Lot V13 — onglet « 8 engrenages » : le documentaire hebdomadaire est la vue par défaut (documentaire.js) ; la vue V12
   (matrice 9 devises x 8 moteurs, dossiers à 3 sous-onglets, « Outils et historique ») reste sous le bouton « Vue tableau »
   (engrenages_tableau.js). Sélecteur « Semaine du … » sur les 12 dernières semaines archivées.
   Adresses : #engrenages (documentaire), #engrenages/c3 (chapitre 3), #engrenages/tableau (vue V12),
   #engrenages/s=2026-S47 (semaine archivée) ; celles du V12 ouvrent la vue tableau (g=2, g=2/devises, USD-2, hebdo, outils). */
import { h, esc, donnees, enErreur } from "./v7_commun.js";
import { chargerJson } from "./commun.js";
import { rendreDocumentaire } from "./documentaire.js";

export async function ecranEngrenages(section, parametre) {
  section.classList.add("dz");
  section.innerHTML = `<div class="dz-bascule"><div class="seg" role="group" aria-label="Vue de l'onglet">
      <button type="button" data-v="doc" aria-pressed="true">Documentaire</button><button type="button" data-v="tableau" aria-pressed="false">Vue tableau</button></div>
    <div class="dz-sem" id="dzSem"></div></div>
    <div id="dzDoc"><div class="card skel" style="height:420px" aria-label="Chargement du documentaire"></div></div><div id="dzTab" class="m12" hidden></div>`;
  const q = s => section.querySelector(s);
  let vue = "doc", doc = null, tableau = null, semaine = null;
  const index = await chargerJson("data/documentaire/index.json");
  const semaines = enErreur(index) ? [] : (index.semaines || []);

  async function afficherDoc(id = null) {
    const D = id ? await chargerJson(`data/documentaire/${id}.json`) : await donnees("documentaire");
    doc?.detruire?.();
    doc = rendreDocumentaire(q("#dzDoc"), enErreur(D) ? null : D, { raison: enErreur(D) ? D?.__erreur : null });
    semaine = (!enErreur(D) && D?.semaine) || id;
    q("#dzSem").innerHTML = semaines.length > 1 ? `<label class="small" for="dzSemSel">Semaine du</label><select id="dzSemSel">${semaines.map(s =>
      `<option value="${esc(s.id)}" ${s.id === semaine ? "selected" : ""}>${esc(String(s.titre || s.id).replace(/^Semaine du /, ""))}${s.statut === "en cours" ? " (en cours)" : ""}</option>`).join("")}</select>` : "";
    q("#dzSemSel")?.addEventListener("change", e => { history.replaceState(null, "", `#engrenages/s=${e.target.value}`); afficherDoc(e.target.value); });
  }
  async function basculer(v) {
    vue = v;
    section.querySelectorAll("[data-v]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === v)));
    q("#dzDoc").hidden = v !== "doc"; q("#dzTab").hidden = v !== "tableau";
    section.querySelector(".dz-sem").hidden = v !== "doc";
    if (v === "tableau" && !tableau) {
      const m = await import("./engrenages_tableau.js");
      tableau = q("#dzTab");
      await m.vueTableau(tableau, null);
    }
  }
  section.querySelectorAll("[data-v]").forEach(b => b.onclick = () => { history.replaceState(null, "", b.dataset.v === "tableau" ? "#engrenages/tableau" : "#engrenages"); basculer(b.dataset.v); });

  section.allerA = async p => {
    const c = (p || "").match(/^c(\d)$/);
    if (c) { if (vue !== "doc") await basculer("doc"); return doc?.allerChapitre(c[1], "auto") || false; }
    const s = (p || "").match(/^s=(\d{4}-S\d{2})$/);
    if (s) { if (vue !== "doc") await basculer("doc"); await afficherDoc(s[1]); return true; }
    if (p === "tableau") { await basculer("tableau"); q("#dzTab").scrollIntoView({ block: "start" }); return true; }
    if (p) {   // adresses du V12 : vue tableau
      await basculer("tableau");
      return tableau?.allerA ? !!(await tableau.allerA(p)) : false;
    }
    return false;
  };
  section.vueParDefaut = async () => { if (vue !== "doc") await basculer("doc"); };
  const s = (parametre || "").match(/^s=(\d{4}-S\d{2})$/);
  await afficherDoc(s ? s[1] : null);
  // L'adresse décide de la vue : #engrenages ouvre toujours le documentaire, #engrenages/tableau la vue V12
  if (parametre) section.cible = await section.allerA(parametre);
}
