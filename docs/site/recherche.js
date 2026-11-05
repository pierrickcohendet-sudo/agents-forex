/* Lot V8 — recherche rapide (Ctrl+K, ou loupe sur téléphone) : 36 paires (page Paire), onglets, 9 devises, 13 indicateurs
   macro, publications des 7 jours (Agenda sur le bon jour). Recherche sans accents ni casse, au clavier et au toucher. */
import { h, esc, ddm, donnees } from "./v7_commun.js";

export const normaliser = s => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
const ONGLETS = [["briefing", "Briefing"], ["synthese", "Synthèse"], ["tableau", "Tableau de bord"], ["paire", "Paires"], ["devises", "Devises"],
                 ["agenda", "Agenda"], ["engrenages", "8 engrenages"], ["journal", "Journal"], ["scenarios", "Scénarios et simulateur"],
                 ["sante", "Santé des données"], ["archives", "Archives"]];
const NOMS = { USD: "dollar américain", EUR: "euro", GBP: "livre sterling", JPY: "yen", CHF: "franc suisse", CAD: "dollar canadien",
               AUD: "dollar australien", NZD: "dollar néo-zélandais", CNY: "yuan renminbi" };

/* Index : [{type, titre, detail, lien, cle}] (cle : texte normalisé de recherche). */
export async function construireIndex() {
  const [paires, tm, agenda] = await Promise.all([donnees("paires"), donnees("tableau_macro"), donnees("agenda")]);
  const idx = [];
  for (const [id, t] of ONGLETS) idx.push({ type: "Onglet", titre: t, detail: "", lien: `#${id}` });
  for (const p of paires?.paires || []) idx.push({ type: "Paire", titre: p, detail: (paires.mes_paires || []).includes(p) ? "Mes paires" : "", lien: `#paire/${p.replace("/", "-")}`, extra: p.replace("/", "") });
  for (const [c, n] of Object.entries(NOMS)) idx.push({ type: "Devise", titre: c, detail: n, lien: `#devises` });
  for (const i of tm?.indicateurs || []) idx.push({ type: "Indicateur", titre: i.libelle, detail: "Macro par devise", lien: "#tableau" });
  const auj = agenda?.aujourdhui || new Date().toISOString().slice(0, 10), fin = new Date(Date.parse(auj) + 7 * 864e5).toISOString().slice(0, 10);
  for (const j of agenda?.jours || []) if (j.date >= auj && j.date <= fin) for (const e of j.evenements || [])
    idx.push({ type: "Publication", titre: e.evenement, detail: `${ddm(j.date)} ${e.heure_paris || ""} · ${e.devise} · impact ${e.impact}`, lien: `#agenda/jour=${j.date}`, extra: e.devise + " " + (e.evenement_en || "") });
  for (const x of idx) x.cle = normaliser(`${x.titre} ${x.detail} ${x.extra || ""} ${x.type}`);
  return idx;
}

/* Résultats : tous les mots doivent apparaître ; titre qui commence par la requête en premier ; 12 au plus. */
export function chercher(idx, requete) {
  const mots = normaliser(requete).split(" ").filter(Boolean);
  if (!mots.length) return idx.filter(x => x.type === "Onglet").slice(0, 8);
  const ordre = { Paire: 0, Onglet: 1, Devise: 2, Indicateur: 3, Publication: 4 };
  return idx.filter(x => mots.every(m => x.cle.includes(m)))
    .map(x => ({ x, score: (normaliser(x.titre).startsWith(mots[0]) ? 0 : 10) + ordre[x.type] }))
    .sort((a, b) => a.score - b.score).slice(0, 12).map(r => r.x);
}

let index = null, dialogue = null;
export async function ouvrirRecherche() {
  if (!dialogue) {
    dialogue = h("dialog", "palette");
    dialogue.setAttribute("aria-label", "Recherche rapide");
    dialogue.innerHTML = `<div class="pal-champ"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input type="search" id="palQ" placeholder="Paire, devise, indicateur, publication, onglet…" aria-label="Rechercher" autocomplete="off" role="combobox" aria-controls="palL" aria-expanded="true"><kbd>Échap</kbd></div>
      <ul class="pal-liste" id="palL" role="listbox"></ul><p class="pal-pied src">↑ ↓ pour choisir · Entrée pour ouvrir · recherche sans accents ni majuscules</p>`;
    document.body.appendChild(dialogue);
    const champ = dialogue.querySelector("#palQ"), liste = dialogue.querySelector("#palL");
    let res = [], actif = 0;
    const rendre = () => {
      res = chercher(index || [], champ.value); actif = Math.min(actif, Math.max(0, res.length - 1));
      liste.innerHTML = res.map((x, i) => `<li role="option" id="pal-${i}" aria-selected="${i === actif}" data-i="${i}"><span class="pal-type">${esc(x.type)}</span><b>${esc(x.titre)}</b><span class="small">${esc(x.detail)}</span></li>`).join("")
        || '<li class="muted" role="option" aria-disabled="true">Aucun résultat.</li>';
      champ.setAttribute("aria-activedescendant", res.length ? `pal-${actif}` : "");
      liste.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
    };
    const aller = i => { const x = res[i]; if (!x) return; dialogue.close(); if (location.hash === x.lien) dispatchEvent(new HashChangeEvent("hashchange")); else location.hash = x.lien; };
    champ.addEventListener("input", () => { actif = 0; rendre(); });
    champ.addEventListener("keydown", e => {
      if (e.key === "ArrowDown") { e.preventDefault(); actif = Math.min(res.length - 1, actif + 1); rendre(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); actif = Math.max(0, actif - 1); rendre(); }
      else if (e.key === "Enter") { e.preventDefault(); aller(actif); }
    });
    liste.addEventListener("click", e => { const li = e.target.closest("li[data-i]"); if (li) aller(Number(li.dataset.i)); });
    dialogue.addEventListener("click", e => { if (e.target === dialogue) dialogue.close(); });
    dialogue.rendre = rendre;
  }
  dialogue.showModal();
  const champ = dialogue.querySelector("#palQ");
  champ.value = ""; champ.focus();
  if (!index) { dialogue.querySelector("#palL").innerHTML = '<li class="muted">Chargement…</li>'; index = await construireIndex(); }
  dialogue.rendre();
}
