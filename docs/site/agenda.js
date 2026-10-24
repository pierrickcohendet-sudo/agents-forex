/* Page Agenda (lot V5, étape 6) : docs/data/agenda.json, calcul Python sans LLM (ForexFactory, registre macro).
   7 prochains jours (heure de Paris) et banques centrales des 9 devises ; filtres par devise et par impact. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure, DRAPEAUX } from "./commun.js";

const IMPACTS = ["fort", "moyen", "faible", "férié"];
const COURTS = { 1: "Thème", 2: "Monétaire", 3: "Données", 4: "Fiscale", 5: "Marchés", 6: "Géopolitique", 7: "Flux", 8: "Offre" };
const JOURS = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", timeZone: "Europe/Paris" });
const virgule = v => v == null ? "n/d" : String(v).replace(".", ",");

function rebours(iso) {
  const ms = Date.parse(iso) - Date.now();
  if (isNaN(ms)) return "";
  if (ms <= 0) return "passé";
  const h = Math.floor(ms / 3.6e6), j = Math.floor(h / 24);
  return j >= 1 ? `dans ${j} j ${h % 24} h` : `dans ${h} h ${Math.floor(ms / 6e4) % 60} min`;
}

function ligneEvenement(e) {
  const li = el("li", `ag-evt impact-${e.impact}`);
  const heure = el("span", "ag-heure tabulaire", e.heure_paris);
  const corps = el("div", "ag-corps");
  const t = el("div", "ag-titre");
  t.append(el("b", null, `${DRAPEAUX[e.devise] || ""} ${e.devise}`), document.createTextNode(` ${e.evenement}`),
           el("span", `ag-impact ${e.impact}`, e.impact));
  const chiffres = el("div", "ag-chiffres tabulaire");
  chiffres.append(el("span", null, `Précédent : ${e.precedent ?? `n/d${e.raison_precedent ? ` (${e.raison_precedent})` : ""}`}`),
                  el("span", null, `Consensus : ${e.consensus ?? `n/d (${e.raison_consensus || "non publié"})`}`),
                  el("span", e.publie ? "ag-publie" : null, `Publié : ${e.publie ?? "pas encore"}`));
  const pied = el("div", "ag-pied");
  const cr = el("span", "ag-rebours", rebours(e.iso_utc)); cr.dataset.iso = e.iso_utc;
  pied.append(cr, el("span", "source", `Source : ${e.source}`));
  if (e.simulateur) { const a = el("a", null, "Voir l'impact historique"); a.href = `#scenarios/i=${e.simulateur}`; pied.appendChild(a); }
  if (e.engrenage) { const a = el("a", null, `Engrenage concerné : ${e.engrenage} ${COURTS[e.engrenage]}`); a.href = `#g=${e.engrenage}`; pied.appendChild(a); }
  corps.append(t, chiffres, pied);
  li.append(heure, corps);
  return li;
}

function banques(liste) {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Banques centrales des 9 devises"));
  const defile = el("div", "defile");
  const t = el("table", "dense ag-bc");
  const tete = el("tr");
  for (const h of ["Devise", "Banque centrale", "Taux actuel", "Dernière variation", "Prochaine décision", "3 prochaines réunions"]) tete.appendChild(el("th", null, h));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  for (const b of liste || []) {
    const tr = el("tr");
    tr.appendChild(el("td", null, `${DRAPEAUX[b.devise] || ""} ${b.devise}`));
    tr.appendChild(el("td", null, b.banque));
    const taux = el("td", "tabulaire", b.taux == null ? "n/d" : `${b.borne === "<" ? "< " : b.borne === ">" ? "> " : ""}${virgule(b.taux)} %`);
    taux.title = `${b.source_taux || "registre macro"}${b.date_taux ? ` · ${dateCourte(b.date_taux)}` : ""}${b.borne ? " · taux publié comme une borne" : ""}`;
    tr.appendChild(taux);
    tr.appendChild(el("td", "tabulaire", b.variation_pb == null ? `n/d (${b.raison_variation || "non disponible"})`
      : `${b.variation_pb === 0 ? "inchangé" : `${b.variation_pb > 0 ? "+" : "−"}${Math.abs(b.variation_pb)} pb`}${b.date_variation ? ` le ${dateCourte(b.date_variation)}` : ""}`));
    tr.appendChild(el("td", "tabulaire", b.prochaine ? dateCourte(b.prochaine) : "n/d"));
    const r = el("td");
    r.appendChild(el("span", null, (b.reunions || []).map(x => dateCourte(x.date)).join(" · ") || "n/d"));
    if (b.raison_reunions) r.appendChild(el("span", "note ag-raison", ` — ${b.raison_reunions}`));
    tr.appendChild(r);
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t); c.appendChild(defile);
  c.appendChild(el("p", "note", "Taux et dates : registre macro (ForexFactory) ; « < 1,25 % » se lit comme une borne. Aide à la décision, jamais un ordre."));
  return c;
}

export async function pageAgenda() {
  const a = await chargerJson("data/agenda.json");
  if (enErreur(a)) return [indisponible("Agenda", a?.__erreur || "agenda.json absent (prochain run)")];
  const tete = el("section", "carte ag-tete");
  tete.appendChild(el("h2", null, "Agenda des 7 prochains jours"));
  tete.appendChild(el("p", "sous-titre", `Heures de Paris · généré ${dateHeure(a.genere_le)} · ${a.n_evenements} évènement(s). ${a.note}`));
  const outils = el("div", "outils ag-filtres");
  const devise = el("select"); devise.setAttribute("aria-label", "Filtrer par devise");
  devise.appendChild(new Option("Toutes les devises", ""));
  for (const d of ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"]) devise.appendChild(new Option(`${DRAPEAUX[d] || ""} ${d}`, d));
  const impact = el("select"); impact.setAttribute("aria-label", "Filtrer par impact");
  impact.appendChild(new Option("Tous les impacts", ""));
  impact.appendChild(new Option("Fort seulement", "fort")); impact.appendChild(new Option("Fort et moyen", "moyen"));
  outils.append(devise, impact);
  tete.appendChild(outils);
  const zone = el("div", "ag-jours");
  function rendre() {
    const garde = e => (!devise.value || e.devise === devise.value) &&
      (!impact.value || (impact.value === "fort" ? e.impact === "fort" : ["fort", "moyen"].includes(e.impact)));
    zone.replaceChildren(...(a.jours || []).map(j => {
      const c = el("section", "carte ag-jour");
      const evts = j.evenements.filter(garde);
      c.appendChild(el("h3", null, JOURS.format(new Date(`${j.date}T12:00:00Z`))));
      if (!evts.length) { c.appendChild(el("p", "note", j.evenements.length ? "Aucun évènement pour ces filtres." : "Aucun évènement au calendrier collecté.")); return c; }
      const ul = el("ul", "ag-liste"); ul.append(...evts.map(ligneEvenement)); c.appendChild(ul);
      return c;
    }));
  }
  devise.addEventListener("change", rendre); impact.addEventListener("change", rendre);
  rendre();
  if (a.raison_vide) tete.appendChild(el("p", "indisponible", `Indisponible : ${a.raison_vide}.`));
  const minuterie = setInterval(() => {
    if (!document.body.contains(zone)) { clearInterval(minuterie); return; }
    zone.querySelectorAll(".ag-rebours").forEach(s => { s.textContent = rebours(s.dataset.iso); });
  }, 60000);
  return [tete, zone, banques(a.banques_centrales)];
}
