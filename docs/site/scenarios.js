/* Onglet « Scénarios » : simulateur d'impact (refonte §12, palier 12). Lit docs/data/impact.json, chargé
   SEULEMENT à l'ouverture de cet onglet. Tous les chiffres viennent du calcul Python (core/impact.py,
   core/impact_long.py) : aucun calcul de résultat ici, seulement de l'affichage. Jamais une recommandation. */
import { chargerJson, enErreur, el, indisponible, dateCourte, ouvrirDetail } from "./commun.js";

const DEVISES = { USD: "Dollar US", EUR: "Euro", GBP: "Livre sterling", JPY: "Yen", CHF: "Franc suisse", CAD: "Dollar canadien",
                  AUD: "Dollar australien", NZD: "Dollar néo-zélandais", CNY: "Yuan" };
const HORIZONS = [["demain", "Demain", 1], ["semaine", "1 semaine", 7], ["mois", "1 mois", 30]];
const LIB_HZ = { demain: "le lendemain", semaine: "à 1 semaine", mois: "à 1 mois" };
/* Lien « Simuler ce moteur » depuis le dossier d'un engrenage : indicateur le plus proche du moteur. */
const MOTEUR_ENGRENAGE = { 1: "dollar_large", 2: "us2a", 3: "cpi_core_us", 4: "us10a", 5: "vix", 6: "brent", 7: "dollar_large", 8: "brent" };
/* Mécanismes pédagogiques en trois temps (texte fixe, aucun chiffre) ; lus à l'envers pour une baisse. */
const MECANISMES = {
  us2a: ["Le marché révise vers le haut le chemin des taux de la Fed.", "L'écart de taux à 2 ans se creuse en faveur des États-Unis.", "Le dollar monte face aux devises à taux stables, le yen en premier."],
  us10a: ["Le rendement long américain monte : placer en dollars paie davantage.", "Les investisseurs achètent des dollars pour acheter ces obligations.", "Les devises à faible taux (yen, franc) reculent."],
  oblig_us: ["Le prix des obligations longues monte, donc leur taux baisse.", "Les attentes de baisse de taux gagnent du terrain.", "Le dollar perd son avantage de rendement ; yen et franc en profitent."],
  fed: ["La Fed relève (ou abaisse) sa cible.", "Les taux courts américains s'ajustent d'un coup.", "L'effet sur le dollar dépend de ce qui était déjà attendu : une décision prévue bouge peu."],
  pib_us: ["La croissance publiée accélère par rapport au trimestre précédent.", "Les attentes de baisse de taux reculent.", "L'écart de croissance soutient en principe le dollar."],
  cpi_core_us: ["L'inflation sous-jacente publiée accélère.", "Le marché retire des baisses de taux de la Fed.", "Le 2 ans monte et le dollar suit ; le yen est le plus exposé."],
  cpi_us: ["L'inflation totale publiée accélère, souvent à cause de l'énergie.", "L'effet sur la Fed dépend de ce que dit le core.", "Le dollar réagit peu ; le CAD résiste grâce au pétrole."],
  brent: ["Le baril monte : les pays exportateurs encaissent plus.", "La balance commerciale des importateurs se dégrade.", "CAD soutenu ; JPY et EUR sous pression en principe."],
  vix: ["La volatilité implicite des actions monte : le marché se couvre.", "Les positions risquées sont réduites.", "AUD et NZD reculent, JPY et CHF résistent en principe."],
  dollar_large: ["Le dollar s'apprécie face au panier large.", "Les matières premières cotées en dollars coûtent plus cher ailleurs.", "Les devises liées aux matières premières reculent le plus."],
  or: ["L'or monte : la demande de protection augmente.", "Le dollar perd une part de son rôle de valeur sûre.", "AUD (producteur) et CHF (refuge) en profitent en principe."],
  sp500: ["Les actions montent : le marché prend du risque.", "Les capitaux quittent les refuges.", "Devises cycliques en hausse, refuges en baisse en principe."],
};
const NOTES_DEVISE = {
  USD: "Le chiffre est le mouvement de l'indice USD synthétique (moyenne inverse des 8 autres devises).",
  EUR: "L'euro est la plus grosse contrepartie du dollar : sa réaction est souvent le miroir de celle du dollar.",
  GBP: "La livre combine un lien avec le risque et ses propres surprises d'inflation.",
  JPY: "Le yen réagit surtout aux taux américains et au risque.", CHF: "Le franc suisse est un refuge.",
  CAD: "Le dollar canadien suit le pétrole autant que le dollar américain.", AUD: "L'australien est très lié à l'appétit pour le risque et à la Chine.",
  NZD: "Le néo-zélandais amplifie souvent les mouvements de l'australien.", CNY: "Le yuan est géré par la banque centrale : peu de mouvement libre.",
};

const fm = (v, d = 2, unite = " %") => v === null || v === undefined ? "n/d"
  : `${Math.abs(v) < 0.5 * 10 ** -d ? "" : v > 0 ? "+" : "−"}${Math.abs(v).toFixed(d).replace(".", ",")}${unite}`;
const SVG = "http://www.w3.org/2000/svg";
function s(tag, attrs, texte) {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  if (texte !== undefined) n.textContent = texte;
  return n;
}

/* ------------------------------------------------------------------ données */
function etat(imp, demande) {
  const ok = imp.indicateurs.filter(i => !i.raison);
  return { ind: demande && ok.some(i => i.id === demande) ? demande : (ok[0]?.id || null), sens: "hausse", amp: 1, hz: "mois", periode: "long" };
}
function scenario(imp, st, idInd, devise) {
  const c = imp.couples[`${idInd}|${devise}`];
  if (!c) return null;
  const jeu = st.periode === "5ans" && c.scenarios_5ans ? c.scenarios_5ans : c.scenarios;
  return { couple: c, sc: jeu?.[`${st.sens}|${st.amp}`] || null };
}
function libelleSens(ind, sens) {
  if (ind.type === "publication") return sens === "hausse" ? "accélère (publication en hausse)" : "ralentit (publication en baisse)";
  return sens === "hausse" ? "monte" : "baisse";
}
function libelleAmpleur(ind, amp) {
  if (ind.id === "fed") return amp === 1 ? "d'au moins 25 pb (toute décision)" : "d'au moins 50 pb";
  return `d'au moins ${amp} écart${amp > 1 ? "s" : ""}-type${amp > 1 ? "s" : ""}`;
}
function seuilTexte(ind, amp) {
  const v = ind.seuils?.[String(amp)] ?? (ind.sigma !== null && ind.sigma !== undefined ? ind.sigma * amp : null);
  if (v === null || v === undefined) return "";
  const u = ind.unite === "%" ? " %" : ind.unite === "pb" ? " pb" : ind.unite === "pts" ? " pt" : ind.unite === "pt" ? " pt" : "";
  return ` (seuil ${String(Math.round(v * 100) / 100).replace(".", ",")}${u}${ind.type === "publication" ? " d'écart avec la publication précédente" : " en une séance"})`;
}

/* ------------------------------------------------------------------ graphiques */
function eventail(sc, hz, yl, L, H, grand) {
  const T = HORIZONS.find(h => h[0] === hz)[2];
  const pts = (sc?.trajectoire || []).filter(p => p[0] <= T);
  const svg = s("svg", { viewBox: `0 0 ${L} ${H}`, class: "sc-svg", role: "img", "aria-label": `Trajectoire médiane jusqu'à ${LIB_HZ[hz]}` });
  if (pts.length < 2) { svg.appendChild(s("text", { x: 4, y: H / 2, class: "sc-axe" }, "trajectoire n/d")); return svg; }
  const g = grand ? 40 : 4, d = grand ? 10 : 4, h = grand ? 10 : 6, b = grand ? 22 : 6;
  const x = j => g + j / T * (L - g - d), y = v => h + (1 - (v + yl) / (2 * yl)) * (H - h - b);
  if (grand) for (const v of [-yl, -yl / 2, 0, yl / 2, yl]) {
    svg.appendChild(s("line", { x1: g, x2: L - d, y1: y(v), y2: y(v), class: v ? "sc-quad" : "sc-zero" }));
    svg.appendChild(s("text", { x: g - 5, y: y(v) + 4, "text-anchor": "end", class: "sc-axe" }, fm(v, 1, "")));
  } else svg.appendChild(s("line", { x1: g, x2: L - d, y1: y(0), y2: y(0), class: "sc-zero" }));
  const faible = sc.mois?.insuffisant || sc[hz]?.insuffisant;
  const haut = pts.map(p => `${x(p[0]).toFixed(1)},${y(p[3]).toFixed(1)}`), bas = pts.slice().reverse().map(p => `${x(p[0]).toFixed(1)},${y(p[2]).toFixed(1)}`);
  svg.appendChild(s("polygon", { points: haut.concat(bas).join(" "), class: "sc-fourchette", opacity: faible ? 0.08 : 0.18 }));
  svg.appendChild(s("polyline", { points: pts.map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" "), class: `sc-ligne${faible ? " faible" : ""}` }));
  const fin = pts[pts.length - 1];
  svg.appendChild(s("circle", { cx: x(fin[0]), cy: y(fin[1]), r: grand ? 4.5 : 3.2, class: "sc-point" }));
  if (grand) {
    svg.appendChild(s("text", { x: g, y: H - 5, class: "sc-axe" }, "jour du choc"));
    svg.appendChild(s("text", { x: L - d, y: H - 5, "text-anchor": "end", class: "sc-axe" }, LIB_HZ[hz]));
  }
  return svg;
}

function nuage(imp, st, ind, devise) {
  const c = imp.couples[`${ind.id}|${devise}`];
  const k = HORIZONS.findIndex(h => h[0] === st.hz);
  let points = [];
  if (ind.type === "publication") {
    const ep = imp.episodes[ind.id]?.tous || [];
    const echelle = ind.id === "fed" ? 25 : ind.sigma || 1;
    points = ep.map((e, i) => [e.choc / echelle, c?.reponses_tous?.[i]?.[k]]).filter(p => p[1] !== null && p[1] !== undefined);
    if (st.periode === "5ans") {
      const debut5 = new Date(Date.now() - 5 * 365.25 * 864e5).toISOString().slice(0, 10);
      points = ep.map((e, i) => [e.date, e.choc / echelle, c?.reponses_tous?.[i]?.[k]]).filter(p => p[0] >= debut5 && p[2] !== null && p[2] !== undefined).map(p => [p[1], p[2]]);
    }
  } else {
    for (const amp of ["1", "2"]) {
      const ep = imp.episodes[ind.id]?.[amp] || [], rep = c?.reponses?.[amp] || [];
      ep.forEach((e, i) => { if (amp === "1" && rep[i]?.[k] !== null && rep[i]?.[k] !== undefined) points.push([e.en_sigma, rep[i][k]]); });
    }
  }
  const L = 340, H = 230, g = 40, d = 10, h = 10, b = 26;
  const svg = s("svg", { viewBox: `0 0 ${L} ${H}`, class: "sc-svg", role: "img",
    "aria-label": `Épisodes passés : variation de l'indicateur contre variation de ${devise} ${LIB_HZ[st.hz]} (${points.length} points)` });
  if (points.length < 3) { svg.appendChild(s("text", { x: 10, y: H / 2, class: "sc-axe" }, "pas assez d'épisodes pour un nuage")); return svg; }
  const xs = Math.max(3, Math.ceil(Math.max(...points.map(p => Math.abs(p[0])))));
  const yl = Math.max(0.5, Math.ceil(Math.max(...points.map(p => Math.abs(p[1]))) * 2) / 2);
  const x = v => g + (Math.max(-xs, Math.min(xs, v)) + xs) / (2 * xs) * (L - g - d), y = v => h + (1 - (v + yl) / (2 * yl)) * (H - h - b);
  for (const v of [-yl, 0, yl]) {
    svg.appendChild(s("line", { x1: g, x2: L - d, y1: y(v), y2: y(v), class: v ? "sc-quad" : "sc-zero" }));
    svg.appendChild(s("text", { x: g - 5, y: y(v) + 4, "text-anchor": "end", class: "sc-axe" }, fm(v, 1, "")));
  }
  for (const v of [-xs, 0, xs]) svg.appendChild(s("text", { x: x(v), y: H - 9, "text-anchor": "middle", class: "sc-axe" },
    `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v)}${ind.id === "fed" ? "×25 pb" : "σ"}`));
  svg.appendChild(s("line", { x1: x(0), x2: x(0), y1: h, y2: H - b, class: "sc-quad" }));
  for (const p of points) svg.appendChild(s("circle", { cx: x(p[0]), cy: y(p[1]), r: 2.8, class: "sc-episode" }));
  // droite de tendance (moindres carrés, affichage seulement)
  const n = points.length, mx = points.reduce((a, p) => a + p[0], 0) / n, my = points.reduce((a, p) => a + p[1], 0) / n;
  let sxy = 0, sxx = 0; points.forEach(p => { sxy += (p[0] - mx) * (p[1] - my); sxx += (p[0] - mx) ** 2; });
  if (sxx) {
    const pente = sxy / sxx, ord = my - pente * mx;
    svg.appendChild(s("line", { x1: x(-xs), y1: y(ord - pente * xs), x2: x(xs), y2: y(ord + pente * xs), class: "sc-tendance" }));
    const sx = (st.sens === "hausse" ? 1 : -1) * st.amp;
    svg.appendChild(s("line", { x1: x(sx), x2: x(sx), y1: h, y2: H - b, class: "sc-scenario" }));
    svg.appendChild(s("circle", { cx: x(sx), cy: y(ord + pente * sx), r: 5, class: "sc-scenario-point" }));
  }
  return svg;
}

/* ------------------------------------------------------------------ rendu */
function ligneEtat(ind) {
  const c = el("section", "carte sc-etat");
  c.appendChild(el("h2", null, `${ind.libelle} : où on en est`));
  const g = el("div", "sc-boites");
  const boite = (l, v) => { const b = el("div", "sc-boite"); b.append(el("span", null, l), el("b", "tabulaire", v)); return b; };
  if (ind.type === "publication") {
    g.append(boite("Dernière publication", `${String(ind.valeur_actuelle).replace(".", ",")}${ind.id === "fed" ? " pb (variation de la cible)" : ` (${ind.mesure})`}`),
             boite("Publiée le", dateCourte(ind.date)),
             boite("Variation de la publication", `${fm(ind.choc_actuel, ind.id === "fed" ? 0 : 2, ind.id === "fed" ? " pb" : " pt")}`),
             boite("Prochaine publication", ind.prochaine_publication ? dateCourte(ind.prochaine_publication) : "voir l'agenda"));
  } else {
    g.append(boite("Valeur", `${String(ind.valeur_actuelle).replace(".", ",")}`), boite("Au", dateCourte(ind.date)),
             boite("Dernière séance", fm(ind.variation_jour, 2, ind.unite === "%" ? " %" : ind.unite === "pb" ? " pb" : " pt")),
             boite("Un écart-type", `${String(ind.sigma).replace(".", ",")}${ind.unite === "%" ? " %" : ind.unite === "pb" ? " pb" : " pt"} par séance`));
  }
  c.appendChild(g);
  c.appendChild(el("p", "note", `Source : ${ind.source || "—"}.${ind.etiquette ? ` ${ind.etiquette} : écart entre le chiffre publié et le précédent, valeurs telles que publiées, ${ind.profondeur} (${ind.n_publications} publications).` : ""}`));
  return c;
}

function carteDevise(imp, st, ind, devise, yl, ouvrir) {
  const x = scenario(imp, st, ind.id, devise);
  const r = x?.sc?.[st.hz];
  const b = el("button", "sc-carte");
  b.type = "button";
  const tete = el("div", "sc-tete");
  tete.append(el("span", "sc-code", devise), el("span", "sc-nom", DEVISES[devise]));
  const insuff = !r || r.insuffisant || r.mediane === null;
  const v = el("span", `sc-valeur tabulaire ${insuff ? "faible" : r.mediane > 0 ? "pos" : r.mediane < 0 ? "neg" : ""}`, r ? fm(r.mediane) : "n/d");
  tete.appendChild(v);
  b.appendChild(tete);
  b.appendChild(eventail(x?.sc, st.hz, yl, 220, 64, false));
  const meta = el("div", "sc-meta");
  if (r && r.n) {
    meta.appendChild(el("span", "tabulaire", `fourchette ${fm(r.q25, 2, "")} à ${fm(r.q75)}`));
    meta.appendChild(el("span", "tabulaire", r.part_sens_attendu !== null && r.part_sens_attendu !== undefined ? `sens attendu dans ${r.part_sens_attendu} % des cas` : "sans sens attendu"));
  }
  b.appendChild(meta);
  const pied = el("div", "sc-meta");
  pied.appendChild(el("span", `sc-tag ${insuff ? "faible" : r.mediane > 0 ? "pos" : r.mediane < 0 ? "neg" : "neutre"}`, insuff ? "échantillon insuffisant" : r.mediane > 0 ? "soutenue" : r.mediane < 0 ? "pénalisée" : "neutre"));
  pied.appendChild(el("span", "tabulaire", `${r?.n ?? 0} cas`));
  b.appendChild(pied);
  b.setAttribute("aria-label", `${DEVISES[devise]} : ${r ? fm(r.mediane) : "n/d"} ${LIB_HZ[st.hz]}, ${r?.n ?? 0} cas${insuff ? ", échantillon insuffisant" : ""}. Ouvrir le détail.`);
  b.addEventListener("click", () => ouvrir(devise));
  return b;
}

function detail(imp, st, ind, devise) {
  const x = scenario(imp, st, ind.id, devise);
  const r = x?.sc?.[st.hz];
  const noeuds = [];
  const tete = el("div", "sc-detail-tete");
  tete.appendChild(el("p", "note", `${DEVISES[devise]} · ${ind.libelle} ${libelleSens(ind, st.sens)} ${libelleAmpleur(ind, st.amp)}${ind.type === "publication" ? ` · ${st.periode === "5ans" ? "5 dernières années" : ind.profondeur}` : " · 5 ans"}`));
  const gros = el("div", "sc-gros");
  gros.append(el("span", null, `Mouvement médian ${LIB_HZ[st.hz]}`),
              el("strong", `tabulaire ${!r || r.insuffisant ? "faible" : r.mediane > 0 ? "pos" : "neg"}`, r ? fm(r.mediane) : "n/d"));
  if (r && r.n) gros.appendChild(el("span", "note", `fourchette habituelle ${fm(r.q25, 2, "")} à ${fm(r.q75)} · ${r.part_sens_attendu !== null && r.part_sens_attendu !== undefined ? `sens attendu dans ${r.part_sens_attendu} % des cas` : "sans sens attendu"} · ${r.n} cas${r.insuffisant ? " · échantillon insuffisant pour conclure" : ""}`));
  tete.appendChild(gros);
  noeuds.push(tete);
  const deux = el("div", "sc-deux");
  const yl = Math.max(0.5, Math.ceil(Math.max(...(x?.sc?.trajectoire || [[0, 0, 0, 0]]).map(p => Math.max(Math.abs(p[2]), Math.abs(p[3])))) * 2) / 2);
  const a = el("div"); a.append(el("h3", null, "Trajectoire typique"), eventail(x?.sc, st.hz, yl, 420, 230, true));
  const n = el("div"); n.append(el("h3", null, "Chaque cas passé"), nuage(imp, st, ind, devise),
    el("p", "note", "Chaque point est un épisode : la variation de l'indicateur contre celle de la devise. Droite : tendance. Point orange : le scénario choisi."));
  deux.append(a, n); noeuds.push(deux);
  const hz = el("div", "sc-horizons");
  for (const [cle, lib] of HORIZONS) {
    const y = x?.sc?.[cle];
    const bte = el("div", "sc-boite");
    bte.append(el("span", null, lib), el("b", `tabulaire ${!y || y.insuffisant ? "faible" : y.mediane > 0 ? "pos" : "neg"}`, y ? fm(y.mediane) : "n/d"),
               el("span", "note", y ? `${y.part_sens_attendu ?? "n/d"} % · ${y.n} cas${y.insuffisant ? " · insuffisant" : ""}` : "n/d"));
    hz.appendChild(bte);
  }
  noeuds.push(el("h3", null, "Même scénario sur les trois horizons"), hz);
  const meca = el("div", "sc-boite sc-meca");
  meca.appendChild(el("strong", null, `Le mécanisme, en trois temps${st.sens === "baisse" ? " (décrit pour une hausse : lis-le à l'envers)" : ""}`));
  const ol = el("ol"); for (const t of MECANISMES[ind.id] || []) ol.appendChild(el("li", null, t)); meca.appendChild(ol);
  meca.appendChild(el("p", "note", `${devise} en particulier : ${NOTES_DEVISE[devise]}`));
  if (x?.couple?.sensibilite !== null && x?.couple?.sensibilite !== undefined) meca.appendChild(el("p", "note",
    `Sensibilité ${ind.type === "publication" ? "(corrélation entre la variation publiée et la réaction du jour)" : "(corrélation des variations sur 1 mois, la même que dans le tableau des conséquences)"} : ${fm(x.couple.sensibilite, 2, "")}.`));
  noeuds.push(meca);
  noeuds.push(el("p", "sc-retenir", `À retenir. Ce sont des moyennes sur des épisodes passés, pas une prévision ni une recommandation. ${r?.part_sens_attendu !== null && r?.part_sens_attendu !== undefined ? `Le sens attendu s'est produit dans ${r.part_sens_attendu} % des cas : il y a donc des cas contraires.` : ""} Le lien peut changer quand le régime de marché change.`));
  ouvrirDetail(`${devise} si ${ind.libelle} ${libelleSens(ind, st.sens)}`, noeuds);
}

function carteChaleur(imp, st, choisir) {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Carte de chaleur : tous les indicateurs"));
  c.appendChild(el("p", "note", `Mouvement médian ${LIB_HZ[st.hz]} si l'indicateur ${st.sens === "hausse" ? "monte (ou accélère)" : "baisse (ou ralentit)"} d'au moins ${st.amp} écart${st.amp > 1 ? "s" : ""}-type${st.amp > 1 ? "s" : ""} (Fed : ${st.amp === 1 ? "toute décision" : "au moins 50 pb"}). Indicateurs publiés : ${st.periode === "5ans" ? "5 dernières années" : "depuis 2004"}. Touchez une case pour le détail.`));
  const defile = el("div", "defile");
  const t = el("table", "dense sc-chaleur");
  const tete = el("tr"); tete.appendChild(el("th", null, ""));
  for (const d of Object.keys(DEVISES)) tete.appendChild(el("th", null, d));
  const thead = el("thead"); thead.appendChild(tete); t.appendChild(thead);
  const corps = el("tbody");
  for (const ind of imp.indicateurs) {
    const tr = el("tr");
    tr.appendChild(el("th", "sc-ligne-ind", ind.libelle.replace(" — variation de la publication", " (publication)")));
    for (const d of Object.keys(DEVISES)) {
      const td = el("td");
      const r = ind.raison ? null : scenario(imp, st, ind.id, d)?.sc?.[st.hz];
      const b = el("button", "sc-case");
      b.type = "button";
      if (!r || r.mediane === null || r.mediane === undefined) { b.append(el("span", null, "n/d"), el("small", null, ind.raison ? "indisponible" : "aucun cas")); b.disabled = Boolean(ind.raison); }
      else {
        const mot = r.insuffisant ? "insuffisant" : r.mediane > 0.05 ? "soutien" : r.mediane < -0.05 ? "pression" : "neutre";
        b.append(el("span", "tabulaire", fm(r.mediane, 2, "")), el("small", null, mot));
        if (!r.insuffisant) {
          const force = Math.min(1, Math.abs(r.mediane) / 1.5) * 60;
          b.style.background = `color-mix(in srgb, ${r.mediane >= 0 ? "var(--positif)" : "var(--negatif)"} ${force.toFixed(0)}%, var(--carte-2))`;
        } else b.classList.add("faible");
      }
      if (ind.id === st.ind) b.classList.add("sel");
      b.setAttribute("aria-label", `${ind.libelle}, ${d} : ${r ? fm(r.mediane) : "n/d"}${r?.insuffisant ? ", échantillon insuffisant" : ""}`);
      b.addEventListener("click", () => choisir(ind.id, d));
      td.appendChild(b); tr.appendChild(td);
    }
    corps.appendChild(tr);
  }
  t.appendChild(corps); defile.appendChild(t); c.appendChild(defile);
  return c;
}

function segment(libelle, options, actif, changer) {
  const ligne = el("div", "sc-ligne");
  ligne.appendChild(el("span", "sc-lab", libelle));
  const seg = el("div", "eg-seg sc-seg"); seg.setAttribute("role", "group"); seg.setAttribute("aria-label", libelle);
  for (const [v, t] of options) {
    const b = el("button", null, t); b.type = "button"; b.setAttribute("aria-pressed", String(v === actif));
    b.addEventListener("click", () => changer(v)); seg.appendChild(b);
  }
  ligne.appendChild(seg);
  return ligne;
}

export async function pageScenarios(parametre) {
  const imp = await chargerJson("data/impact.json");   // chargé à l'ouverture de l'onglet seulement
  if (enErreur(imp)) return [indisponible("Scénarios", imp?.__erreur || "impact.json absent")];
  const m = /^g=([1-8])$/.exec(parametre || ""), i = /^i=([a-z0-9_]+)$/.exec(parametre || "");
  const st = etat(imp, m ? MOTEUR_ENGRENAGE[m[1]] : i ? i[1] : null);
  const racine = el("div", "sc");
  function rendre() {
    const ind = imp.indicateurs.find(x => x.id === st.ind);
    const blocs = [];
    const tete = el("section", "carte");
    tete.appendChild(el("h1", "eg-titre", "Simulateur d'impact"));
    tete.appendChild(el("p", "eg-chapo", "Choisissez un indicateur, un sens et un horizon : chaque devise montre ce qu'elle a fait, en médiane, après des mouvements comparables. Moyennes passées recalculées chaque jour en Python, pas une prévision."));
    const groupes = el("div", "sc-groupes");
    for (const [g, lib] of Object.entries(imp.groupes || {})) {
      const l = el("div", "sc-ligne");
      l.appendChild(el("span", "sc-lab", lib));
      const chips = el("div", "sc-chips");
      for (const x of imp.indicateurs.filter(y => y.groupe === g)) {
        const b = el("button", "sc-chip", x.libelle.replace(" — variation de la publication", ""));
        b.type = "button"; b.setAttribute("aria-pressed", String(x.id === st.ind));
        if (x.raison) { b.disabled = true; b.title = x.raison; }
        if (x.etiquette) b.appendChild(el("small", null, " · publication"));
        b.addEventListener("click", () => { st.ind = x.id; rendre(); });
        chips.appendChild(b);
      }
      l.appendChild(chips); groupes.appendChild(l);
    }
    tete.appendChild(groupes);
    if (!ind) { blocs.push(tete, indisponible("Simulateur", "aucun indicateur calculable aujourd'hui")); racine.replaceChildren(...blocs); return; }
    tete.appendChild(segment("Sens", ind.type === "publication" ? [["baisse", "Publication en baisse"], ["hausse", "Publication en hausse"]] : [["baisse", "Baisse"], ["hausse", "Hausse"]],
                             st.sens, v => { st.sens = v; rendre(); }));
    tete.appendChild(segment("Ampleur", ind.id === "fed" ? [[1, "Toute décision"], [2, "Au moins 50 pb"]] : [[1, "1 écart-type"], [2, "2 écarts-types"]],
                             st.amp, v => { st.amp = v; rendre(); }));
    tete.appendChild(segment("Horizon", HORIZONS.map(h => [h[0], h[1]]), st.hz, v => { st.hz = v; rendre(); }));
    if (ind.type === "publication") tete.appendChild(segment("Période", [["long", ind.profondeur ? ind.profondeur.replace("depuis", "Depuis") : "Long terme"], ["5ans", "5 dernières années"]],
                                                             st.periode, v => { st.periode = v; rendre(); }));
    const lignes = Object.keys(DEVISES).map(d => ({ d, r: scenario(imp, st, ind.id, d)?.sc?.[st.hz] }));
    const fiables = lignes.filter(l => l.r && !l.r.insuffisant && l.r.mediane !== null);
    const hauts = fiables.filter(l => l.r.mediane > 0.05).sort((a, b) => b.r.mediane - a.r.mediane).slice(0, 3).map(l => l.d);
    const bas = fiables.filter(l => l.r.mediane < -0.05).sort((a, b) => a.r.mediane - b.r.mediane).slice(0, 3).map(l => l.d);
    const phrase = el("div", "sc-phrase");
    phrase.setAttribute("aria-live", "polite");
    const p = el("p");
    p.innerHTML = "";
    p.append(document.createTextNode(`Si ${ind.libelle.replace(" — variation de la publication", "")} ${libelleSens(ind, st.sens)} ${libelleAmpleur(ind, st.amp)}${seuilTexte(ind, st.amp)}, alors ${LIB_HZ[st.hz]} : `));
    p.appendChild(el("span", "pos", hauts.length ? `${hauts.join(", ")} soutenues` : "aucune devise nettement soutenue"));
    p.append(document.createTextNode(" ; "));
    p.appendChild(el("span", "neg", bas.length ? `${bas.join(", ")} pénalisées` : "aucune devise nettement pénalisée"));
    p.append(document.createTextNode("."));
    phrase.appendChild(p);
    const insuff = lignes.filter(l => !l.r || l.r.insuffisant).length;
    phrase.appendChild(el("p", "note", `${insuff ? `${insuff} devise(s) sur 9 avec moins de ${imp.min_cas} cas : échantillon insuffisant, chiffre non mis en avant. ` : ""}Moyennes passées, pas une prévision.`));
    tete.appendChild(phrase);
    blocs.push(tete, ligneEtat(ind));
    const legende = el("p", "note sc-legende", "Trait : trajectoire médiane ; zone : la moitié centrale des cas (25–75 %) ; pointillé et gris : échantillon insuffisant. Cartes triées de la plus soutenue à la plus pénalisée ; touchez une carte pour le détail.");
    blocs.push(legende);
    const yl = Math.max(0.25, Math.ceil(Math.max(0.1, ...lignes.map(l => Math.max(Math.abs(l.r?.q25 || 0), Math.abs(l.r?.q75 || 0)))) * 4) / 4);
    const grille = el("div", "sc-grille");
    const tri = lignes.slice().sort((a, b) => {
      const va = a.r && !a.r.insuffisant ? a.r.mediane : null, vb = b.r && !b.r.insuffisant ? b.r.mediane : null;
      if (va === null && vb === null) return 0; if (va === null) return 1; if (vb === null) return -1; return vb - va;
    });
    for (const l of tri) grille.appendChild(carteDevise(imp, st, ind, l.d, yl, d => detail(imp, st, ind, d)));
    blocs.push(grille);
    blocs.push(carteChaleur(imp, st, (id, d) => { st.ind = id; rendre(); detail(imp, st, imp.indicateurs.find(x => x.id === id), d); }));
    blocs.push(el("p", "note", `${imp.methode} ${imp.note} Calcul du ${dateCourte(imp.fin)} ; marchés depuis le ${dateCourte(imp.debut)}.`));
    racine.replaceChildren(...blocs);
  }
  rendre();
  return [racine];
}
