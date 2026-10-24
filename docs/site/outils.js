/* Boîte à outils (lot V5, étape 5) : docs/data/outils.json, calcul Python. Le site affiche, ne calcule rien.
   A. Radar des déclencheurs · B. « Et si… » · C. Décomposer une paire · D. Jours qui ressemblent à aujourd'hui. */
import { chargerJson, enErreur, el, indisponible, dateCourte, dateHeure } from "./commun.js";

const COURTS = { 1: "Thème", 2: "Monétaire", 3: "Données", 4: "Fiscale", 5: "Marchés", 6: "Géopolitique", 7: "Flux", 8: "Offre" };
const signe = (v, d = 0) => v == null ? "n/d" : `${v > 0 ? "+" : ""}${Number(v).toLocaleString("fr-FR", { maximumFractionDigits: d })}`.replace("-", "−");
const ETAT = { franchi: "franchi", proche: "proche", non: "dans le couloir", "n/d": "n/d", "sans seuil": "sans seuil" };

function carte(titre, badge) {
  const c = el("section", "carte ot-carte");
  const t = el("div", "ck-section-tete"); t.append(el("h2", null, titre));
  if (badge) t.appendChild(el("span", "ck-petit", badge));
  c.appendChild(t);
  return c;
}

function radar(r) {
  const c = carte("A · Radar des déclencheurs", "classés par distance au seuil, en % du couloir neutre");
  if (!r || r.indisponible) { c.appendChild(el("p", "indisponible", `Indisponible : ${r?.indisponible || "outils.json absent"}.`)); return c; }
  const filtre = el("div", "sc-seg"); filtre.setAttribute("role", "group"); filtre.setAttribute("aria-label", "Filtrer le radar");
  const liste = el("ol", "ot-radar");
  let mode = "proches";
  const modes = [["proches", "Franchis et proches"], ["tous", `Tous (${r.signaux.length})`]];
  const boutons = modes.map(([id, lib]) => { const b = el("button", null, lib); b.type = "button"; b.addEventListener("click", () => { mode = id; rendre(); }); filtre.appendChild(b); return b; });
  function rendre() {
    boutons.forEach((b, i) => b.setAttribute("aria-pressed", String(modes[i][0] === mode)));
    const sel = r.signaux.filter(s => mode === "tous" || s.etat === "franchi" || s.etat === "proche" || (s.distance_pct ?? 999) <= 30);
    liste.replaceChildren(...sel.map(s => {
      const li = el("li", `ot-sig etat-${String(s.etat).replace(" ", "-")}`);
      li.appendChild(el("span", "ck-num", String(s.engrenage)));
      const txt = el("div", "ot-sig-txt");
      txt.append(el("b", null, s.libelle), el("span", "ck-petit", `${s.texte_valeur}${s.date ? ` · ${dateCourte(s.date)}` : ""} · ${s.source || "source n/d"}`));
      if (s.etat === "franchi" && (s.effet_haut || s.effet_bas)) txt.appendChild(el("span", "ck-petit", `Effet : ${(s.cote === "haut" ? s.effet_haut : s.effet_bas) || "—"}`));
      if (s.neutralise) txt.appendChild(el("span", "ck-note alerte", String(s.neutralise)));
      if ((s.rendez_vous || []).length) txt.appendChild(el("span", "ck-petit ot-rdv", "Rendez-vous : " + s.rendez_vous.map(e => `${dateCourte(e.date_paris).slice(0, 5)} ${e.heure_paris} ${e.devise} ${e.evenement}`).join(" · ")));
      const barre = el("span", "ot-barre"); const i = el("i");
      i.style.width = `${s.distance_pct == null ? 0 : Math.max(2, 100 - Math.min(100, s.distance_pct))}%`;
      barre.appendChild(i);
      li.append(txt, barre, el("span", "ot-dist", s.etat === "franchi" ? "franchi" : s.distance_texte || ETAT[s.etat] || "n/d"));
      li.title = s.phrase || "";
      return li;
    }));
  }
  rendre();
  c.append(filtre, liste);
  if ((r.rendez_vous || []).length) {
    c.appendChild(el("h3", "ck-h3", "Rendez-vous qui peuvent les faire bouger"));
    const z = el("div", "ot-puces");
    for (const e of r.rendez_vous) {
      const a = el("a", "ot-puce", `${dateCourte(e.date_paris).slice(0, 5)} ${e.heure_paris} · ${e.devise} ${e.evenement} → engr. ${e.engrenage}`);
      a.href = `#g=${e.engrenage}`; a.title = `Impact ${e.impact} · ${e.source}`;
      z.appendChild(a);
    }
    c.appendChild(z);
  }
  c.appendChild(el("p", "note", r.methode || ""));
  return c;
}

function etSi(liste) {
  const c = carte("B · Et si… (scénario sur la matrice)", "règles réelles de config.yaml");
  if (!Array.isArray(liste) || !liste.length) { c.appendChild(el("p", "indisponible", `Indisponible : ${liste?.indisponible || "aucun scénario"}.`)); return c; }
  const choix = el("select", "ot-select"); choix.setAttribute("aria-label", "Choisir un scénario");
  const groupes = {};
  liste.forEach((s, i) => {
    const g = groupes[s.engrenage] || (groupes[s.engrenage] = Object.assign(document.createElement("optgroup"), { label: `Engrenage ${s.engrenage} · ${COURTS[s.engrenage]}` }));
    g.appendChild(new Option(s.libelle, String(i)));
  });
  Object.keys(groupes).sort((a, b) => a - b).forEach(k => choix.appendChild(groupes[k]));
  const zone = el("div");
  function rendre() {
    const s = liste[Number(choix.value)];
    const desc = el("p", "ot-desc", `${s.description}. Effet : ${s.effets}. Valeur actuelle : ${s.valeur_actuelle == null ? "n/d" : signe(s.valeur_actuelle, 2)}.`);
    const max = Math.max(4, ...s.bilans.flatMap(b => [Math.abs(b.avant), Math.abs(b.apres)]));
    const grille = el("div", "ot-bilans");
    for (const b of s.bilans) {
      const l = el("div", "ot-bilan");
      const piste = el("span", "ot-piste");
      const seg = (v, cls) => { const i = el("i", cls); i.style.width = `${Math.abs(v) / max * 50}%`; i.style[v >= 0 ? "left" : "right"] = "50%"; return i; };
      piste.append(seg(b.avant, "avant"), seg(b.apres, "apres"));
      l.append(el("b", null, b.devise), piste, el("span", `tabulaire ${b.apres !== b.avant ? "change" : ""}`, `${signe(b.avant)} → ${signe(b.apres)}`));
      grille.appendChild(l);
    }
    zone.replaceChildren(desc, grille);
  }
  choix.addEventListener("change", rendre);
  rendre();
  const leg = el("p", "ck-legende");
  for (const [cls, txt] of [["avant", "bilan actuel"], ["apres", "bilan dans le scénario"]]) { const sp = el("span"); sp.append(el("i", `ot-leg ${cls}`), document.createTextNode(txt)); leg.appendChild(sp); }
  c.append(choix, zone, leg, el("p", "note", "Matrice recalculée en Python avec le signal posé au seuil ; bilan = somme des 8 cases (même règle que la matrice). Aide à la lecture, jamais un ordre."));
  return c;
}

function decomposer(paires) {
  const c = carte("C · Décomposer une paire", "contribution = case de la base − case de la cotation");
  if (!paires || paires.indisponible) { c.appendChild(el("p", "indisponible", `Indisponible : ${paires?.indisponible || "absent"}.`)); return c; }
  const ligne = el("div", "ot-ligne");
  const lab = el("label", null, "Paire"); lab.htmlFor = "ot-paire";
  const choix = el("select", "ot-select"); choix.id = "ot-paire";
  for (const p of Object.keys(paires)) choix.appendChild(new Option(p, p));
  choix.value = paires["AUD/JPY"] ? "AUD/JPY" : Object.keys(paires)[0];
  ligne.append(lab, choix);
  const zone = el("div");
  function rendre() {
    const p = paires[choix.value];
    if (p.raison) { zone.replaceChildren(el("p", "indisponible", `n/d : ${p.raison}.`)); return; }
    const t = el("div", "ot-decomp");
    for (const x of p.contributions) {
      const r = el("div", `ot-dc ${x.incomplete ? "incomplete" : ""}`);
      const piste = el("span", "ot-piste"); const i = el("i", x.contribution > 0 ? "pos" : "neg");
      i.style.width = `${Math.min(50, Math.abs(x.contribution) / 4 * 50)}%`; i.style[x.contribution >= 0 ? "left" : "right"] = "50%";
      piste.appendChild(i);
      r.append(el("span", null, `${x.engrenage} ${COURTS[x.engrenage]}`), el("span", "ck-petit", `${p.base} ${x.etat_base === "nd" ? "n/d" : signe(x.base)}`),
               el("span", "ck-petit", `${p.cotation} ${x.etat_cotation === "nd" ? "n/d" : signe(x.cotation)}`), piste, el("b", "tabulaire", signe(x.contribution)));
      t.appendChild(r);
    }
    zone.replaceChildren(t, el("p", "ot-solde", p.texte), ...(p.incompletes.length ? [el("p", "note", `Cases incomplètes : ${p.incompletes.join(" ; ")}.`)] : []));
  }
  choix.addEventListener("change", rendre);
  rendre();
  c.append(ligne, zone);
  return c;
}

function similaires(s) {
  const c = carte("D · Jours qui ressemblent à aujourd'hui", s?.lecture || "");
  if (!s || s.indisponible || s.raison) { c.appendChild(el("p", "indisponible", `n/d : ${s?.raison || s?.indisponible || "absent"}.`)); if (s?.methode) c.appendChild(el("p", "note", s.methode)); return c; }
  const defile = el("div", "defile");
  const t = el("table", "dense ot-sim");
  const tete = el("tr"); for (const h of ["Date", "Distance", ...s.paires]) tete.appendChild(el("th", null, h));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  const cel = v => el("td", `tabulaire ${v > 0 ? "pos" : v < 0 ? "neg" : ""}`, v == null ? "n/d" : `${signe(v, 2)} %`);
  for (const l of s.seances) {
    const tr = el("tr"); tr.append(el("td", null, dateCourte(l.date)), el("td", "tabulaire", String(l.distance).replace(".", ",")));
    for (const p of s.paires) tr.appendChild(cel(l.variations_1m[p]));
    corps.appendChild(tr);
  }
  const med = el("tr", "ot-med"); med.append(el("td", null, "Médiane"), el("td"));
  for (const p of s.paires) med.appendChild(cel(s.medianes[p]));
  corps.appendChild(med);
  t.appendChild(corps); defile.appendChild(t);
  c.append(el("p", "ck-petit", "Les 5 séances depuis 2021 dont le profil des engrenages est le plus proche, et la variation des paires sur le mois qui a suivi."),
           defile, el("p", "tag-alerte", s.lecture), el("p", "note", `${s.methode} Source : ${s.source}.`));
  return c;
}

export async function pageOutils() {
  const o = await chargerJson("data/outils.json");
  const tete = el("section", "carte");
  tete.appendChild(el("h2", null, "Aide à l'analyse"));
  if (enErreur(o)) return [tete, indisponible("Boîte à outils", o?.__erreur || "outils.json absent (prochain run)")];
  tete.appendChild(el("p", "sous-titre", `Tout est calculé en Python à partir des règles et des données existantes (${dateHeure(o.genere_le)}). Aucun signal d'achat ou de vente : on montre ce qui peut changer et pourquoi.`));
  const milieu = el("div", "ot-grille"); milieu.append(etSi(o.scenarios), decomposer(o.paires));
  return [tete, radar(o.radar), milieu, similaires(o.similaires)];
}
