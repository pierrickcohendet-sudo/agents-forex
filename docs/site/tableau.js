/* Tableau macro — livré au palier 3 de la V1. */
import { el } from "./commun.js";

export async function pageTableau() {
  const c = el("section", "carte");
  c.appendChild(el("h2", null, "Tableau macro"));
  c.appendChild(el("p", "indisponible", "En cours de construction (V1, palier 3) : disponible très prochainement."));
  return [c];
}
