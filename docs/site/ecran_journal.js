/* Lot V7 — Journal : toute la logique du Journal V2 est conservée (IndexedDB, 7 étapes, captures, export et import,
   journal.js) ; seule la présentation suit la maquette : bilan du mois en tuiles et calendrier coloré d'abord, détail du
   jour, puis les étapes numérotées de la nouvelle entrée ; la fiche d'analyse de la paire passe en vue complète. */
import { $, h, MOIS } from "./v7_commun.js";

export async function ecranJournal(section) {
  const m = await import("./journal.js");
  const blocs = await m.pageJournal();
  const maintenant = new Date();
  section.replaceChildren(
    h("div", "sec-head", `<h2>Journal · ${MOIS[maintenant.getMonth()]} ${maintenant.getFullYear()}</h2><span class="note-ex">Entrées enregistrées sur ton appareil (IndexedDB) : l'export sert de sauvegarde</span>`),
    h("div", "legacy journal-v7"));
  const zone = $(".journal-v7", section);
  zone.append(...blocs);
  const cols = zone.querySelectorAll(".jn-grille > .jn-col");
  if (cols.length === 2) {
    cols[0].classList.add("full", "jn-fiche-col");                 // fiche d'analyse : vue complète
    const cal = cols[1].querySelector(".jn-calendrier"), form = cols[1].querySelector(".jn-form");
    if (cal && form) cols[1].insertBefore(cal, form);               // calendrier et bilan d'abord, comme la maquette
    const btnCal = [...cols[1].querySelectorAll(".jn-vues button")].find(b => /Calendrier/.test(b.textContent));
    btnCal?.click();                                                // rend le calendrier (journal.js)
    zone.classList.add("jn-tout");                                  // calendrier et formulaire visibles ensemble
  }
  zone.querySelector(":scope > .carte")?.classList.add("full");      // en-tête explicatif : vue complète
}
