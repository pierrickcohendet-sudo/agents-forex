/* Lot V10 (B4) — « Lecture du site » : ce que disait le contexte publié au moment de l'entrée. Ce n'est ni un jugement ni
   un conseil : les chiffres viennent de l'archive Python docs/data/contexte/ (instantané le plus proche AVANT l'entrée) ;
   le navigateur l'oriente seulement selon le sens du trade (fonctions pures de journal_v4.js). */
import { h, esc, nd, ddm } from "./v7_commun.js";
import { chargerJson, enErreur } from "./commun.js";
import { instantaneAvant, isoArchive, reconstituer, orienter, phraseSynthese, confrontation, publicationsPendant, positionPrix, minutesEntre, dureeTexte } from "./journal_v4.js";

const STATUT = { pour: ["Dans le sens du trade", "up"], contre: ["Contre", "dn"], neutre: ["Neutre", ""], nd: ["n/d", ""] };
const fichierJour = jour => chargerJson(`data/contexte/${jour}.json`).then(d => enErreur(d) ? null : d);

/* Calcule la lecture d'une note (null si aucun instantané avant l'entrée). */
export async function lire(note) {
  const index = await chargerJson("data/contexte/index.json");
  if (enErreur(index) || !index.jours) return { absent: true, premier: null, raison: "archive du contexte indisponible" };
  const moment = isoArchive(note.entree_utc || note.date_heure);
  const choix = instantaneAvant(index.jours, moment);
  if (!choix) return { absent: true, premier: index.premier };
  const f = await fichierJour(choix.jour);
  const inst = f && reconstituer(f, choix.rang);
  if (!inst) return { absent: true, premier: index.premier, raison: "fichier du jour illisible" };
  const o = orienter(inst, note.paire, note.sens);
  // Publications pendant le trade : dernier instantané de chaque jour couvert (réel publié après coup)
  const fin = note.sortie_utc ? isoArchive(note.sortie_utc) : null;
  const jours = Object.keys(index.jours).filter(j => j >= moment.slice(0, 10) && j <= (fin || moment).slice(0, 10));
  const pubs = [];
  for (const j of jours) { const fj = await fichierJour(j); const r = fj && reconstituer(fj, fj.instantanes.length - 1); if (r?.publications) pubs.push(r.publications); }
  return { inst, choix, o, pubs: publicationsPendant(pubs, note.paire, moment, fin), position: positionPrix(inst, note.paire) };
}

export async function ongletLecture(note) {
  const c = h("div", "jl");
  c.innerHTML = '<div class="card skel" style="height:220px"></div>';
  let L;
  try { L = await lire(note); } catch (e) { c.innerHTML = `<p class="muted">Lecture indisponible : ${esc(e.message || e)}</p>`; return { noeud: c, lecture: null }; }
  if (L.absent) {
    c.innerHTML = `<div class="card pad jl-absent"><h4>Contexte non archivé pour cette date</h4>
      <p class="muted">${L.premier ? `Premier instantané disponible : ${ddm(L.premier)}/${L.premier.slice(0, 4)}.` : esc(L.raison || "aucun instantané archivé pour l'instant")}
      L'archive du site commence avec le lot V10 (reconstituée depuis le ${L.premier ? ddm(L.premier) : "n/d"} à partir des données publiées).</p></div>`;
    return { noeud: c, lecture: null };
  }
  const { inst, o, pubs, position } = L;
  if (!o) { c.innerHTML = `<p class="muted">Paire ${esc(note.paire)} absente de l'instantané du ${esc(inst.heure_utc)}.</p>`; return { noeud: c, lecture: null }; }
  const hl = new Date(inst.heure_utc).toLocaleString("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  const duree = minutesEntre(note.entree_utc, note.sortie_utc);
  c.innerHTML = `
    <div class="ctx-h"><span class="eyebrow">Lecture du site · générée automatiquement</span>
      <b class="jl-phrase">${esc(phraseSynthese(o, note.entree_locale, note.paire, note.sens, inst.theme))}</b>
      <div class="meter" role="img" aria-label="${o.pour} pour, ${o.contre} contre, ${o.neutres + o.nd} neutres ou non disponibles">${'<i class="p"></i>'.repeat(o.pour)}${'<i class="c"></i>'.repeat(o.contre)}${'<i class="n"></i>'.repeat(o.neutres + o.nd)}</div>
      <span class="small">Instantané du site du ${esc(hl)} (heure de Paris), le plus proche avant l'ouverture du trade · rapport du ${esc(ddm(inst.rapport_du || ""))} ·
      moteurs : matrice d'impact (règles Python) · ce tableau décrit le contexte, ce n'est ni un jugement ni un conseil.</span></div>
    <div class="scroll"><table class="tbl jl-tab"><thead><tr><th>Moteur</th><th>Lecture</th><th>Raison chiffrée</th><th>Date</th></tr></thead><tbody>
    ${o.lignes.map(l => `<tr><td><span class="moteur-nom" title="${esc(l.explication)}">${esc(l.nom)}</span></td>
      <td><span class="chip ${STATUT[l.statut][1]}" style="height:22px">${STATUT[l.statut][0]}</span></td>
      <td class="small">${esc(l.raison)}${l.source ? `<br><span class="muted">Source : ${esc(l.source)}</span>` : ""}</td>
      <td class="small">${l.date ? esc(ddm(l.date)) : nd("raison sans date : règle sous les seuils ou donnée manquante")}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="cols2 jl-cols">
      <div class="card pad"><h4>Publications pendant le trade</h4>
        ${pubs.length ? `<ul class="jl-pubs">${pubs.map(p => `<li><b>${esc(new Date(p.h).toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit" }))}</b> ${esc(p.devise)} · ${esc(p.ev)}
          <span class="small">réel ${p.publie ? esc(p.publie) : nd("pas encore publié ou non archivé")} · consensus ${p.consensus ? esc(p.consensus) : nd("pas de consensus")}</span></li>`).join("")}</ul>`
          : `<p class="small muted">Aucune publication d'impact moyen ou fort des deux devises ${note.sortie_utc ? "pendant le trade" : "après l'ouverture du trade, ce jour-là"} (agenda ForexFactory archivé).</p>`}
        <p class="small muted">Durée du trade : ${esc(dureeTexte(duree))}.</p></div>
      <div class="card pad"><h4>Position du prix à l'ouverture</h4>
        <p><b class="tabulaire">${esc(position?.cours ?? "n/d")}</b> <span class="small muted">cours publié au moment de l'instantané (Twelve Data)</span></p>
        <ul class="small jl-pos">${(position?.lignes || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
    </div>
    <div class="card pad jl-confront"><span class="eyebrow">Confrontation avec le résultat</span><p>${esc(confrontation(o, note.resultat?.pnl_eur))}</p>
      <p class="small muted">Thème du jour : ${esc(inst.theme?.titre || "n/d")} (${esc(inst.theme?.direction || "n/d")}) · ${inst.theme?.alignes ?? "n/d"} moteurs alignés sur ${inst.theme?.evaluables ?? "n/d"}.</p></div>`;
  return { noeud: c, lecture: { pour: o.pour, contre: o.contre, neutres: o.neutres, nd: o.nd, instantane: inst.heure_utc } };
}
