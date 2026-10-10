/* Utilitaires partagés : DOM, chargement des JSON, formats, fenêtre de détail. */

export function el(tag, classe, texte) {
  const n = document.createElement(tag);
  if (classe) n.className = classe;
  if (texte !== undefined && texte !== null) n.textContent = texte;
  return n;
}

/* Données : chaque fichier est chargé une fois ; un échec renvoie {erreur} (jamais d'exception). */
const cache = new Map();
export function chargerJson(chemin) {
  if (!cache.has(chemin)) {
    cache.set(chemin, fetch(chemin, { cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .catch(e => ({ __erreur: `${chemin} : ${e.message}` })));
  }
  return cache.get(chemin);
}
export const enErreur = d => !d || d.__erreur !== undefined;

/* Bloc « indisponible » avec raison et heure de la tentative — n'interrompt jamais le reste. */
export function indisponible(titre, raison) {
  const c = el("section", "carte");
  if (titre) c.appendChild(el("h2", null, titre));
  const p = el("p", "indisponible",
    `Indisponible : ${raison || "raison inconnue"} (tentative de chargement à ${new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}).`);
  c.appendChild(p);
  return c;
}

export function dateCourte(iso) {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00Z` : iso);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
}
export function dateHeure(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
}
export function ageHeures(iso) {
  const d = new Date(iso);
  return isNaN(d) ? null : (Date.now() - d.getTime()) / 3.6e6;
}

export const DRAPEAUX = { USD: "🇺🇸", EUR: "🇪🇺", GBP: "🇬🇧", JPY: "🇯🇵", CHF: "🇨🇭", CAD: "🇨🇦", AUD: "🇦🇺", NZD: "🇳🇿", CNY: "🇨🇳" };

/* Fenêtre de détail (élément <dialog>). `lignes` : [[libellé, valeur], …] ou nœuds DOM. */
export function ouvrirDetail(titre, contenu) {
  const d = document.getElementById("detail");
  document.getElementById("detail-titre").textContent = titre;
  const corps = document.getElementById("detail-corps");
  corps.replaceChildren(...(Array.isArray(contenu) ? contenu : [contenu]));
  if (typeof d.showModal === "function") { if (!d.open) d.showModal(); } else d.setAttribute("open", "");
}
export function listeDefinitions(paires) {
  const dl = el("dl");
  for (const [k, v] of paires) {
    if (v === undefined) continue;
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, v === null || v === "" ? "—" : String(v)));
  }
  return dl;
}
export function initialiserDetail() {
  const d = document.getElementById("detail");
  d.querySelector("[data-fermer]").addEventListener("click", () => d.close ? d.close() : d.removeAttribute("open"));
  d.addEventListener("click", e => { if (e.target === d && d.close) d.close(); });   // clic sur le fond
}

/* Tri d'un tableau au clic sur l'en-tête : valeurs numériques, absents toujours en bas. */
export function rendreTriable(table, valeurDe) {
  let col = null, sens = -1;
  table.querySelectorAll("thead th").forEach((th, i) => {
    const bouton = th.querySelector("button");
    if (!bouton) return;
    bouton.addEventListener("click", () => {
      sens = col === i ? -sens : (i === 0 ? 1 : -1);
      col = i;
      table.querySelectorAll("thead th").forEach(t => t.removeAttribute("aria-sort"));
      th.setAttribute("aria-sort", sens > 0 ? "ascending" : "descending");
      const corps = table.tBodies[0];
      const lignes = [...corps.rows];
      lignes.sort((a, b) => {
        const va = valeurDe(a, i), vb = valeurDe(b, i);
        if (va === null && vb === null) return 0;
        if (va === null) return 1;
        if (vb === null) return -1;
        return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * sens;
      });
      corps.append(...lignes);
    });
  });
}
