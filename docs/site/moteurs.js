/* GÉNÉRÉ par core/noms_moteurs.py (lot V10) : ne pas modifier à la main. Noms affichés des 8 moteurs du marché ;
   le mot « engrenage » et les numéros restent réservés à l'onglet « 8 engrenages ». */
export const MOTEURS = {"1": {"nom": "Thème dominant", "explication": "le grand récit du marché du moment (inflation, croissance, risque)"}, "2": {"nom": "Banques centrales et taux", "explication": "décisions, ton et anticipations de taux directeurs"}, "3": {"nom": "Chiffres économiques", "explication": "publications au-dessus ou en dessous du consensus"}, "4": {"nom": "Budgets et dette publique", "explication": "déficits, émissions de dette, risque souverain"}, "5": {"nom": "Liens entre marchés", "explication": "taux longs, actions, matières premières, volatilité"}, "6": {"nom": "Géopolitique", "explication": "conflits, sanctions, élections, chocs d'offre"}, "7": {"nom": "Prix et positionnement", "explication": "tendance des prix, positions des spéculateurs (COT)"}, "8": {"nom": "Commerce et flux", "explication": "balances commerciales, offre et demande de pétrole"}};
const echapper = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export function nomMoteur(n, minuscule = false) {
  const m = MOTEURS[String(n)]; if (!m) return "moteur n/d";
  return minuscule ? m.nom[0].toLowerCase() + m.nom.slice(1) : m.nom;
}
export function explicationMoteur(n) { return MOTEURS[String(n)]?.explication || ""; }
/* Nom avec l'explication courte en infobulle (HTML). */
export function moteurHtml(n, minuscule = false) {
  return `<span class="moteur-nom" title="${echapper(explicationMoteur(n))}">${echapper(nomMoteur(n, minuscule))}</span>`;
}
/* Contributions d'une paire (+ vers la hausse) -> « 4 moteurs pour, 0 contre ». */
export function decompteMoteurs(contributions) {
  const l = contributions || [];
  const pour = l.filter(c => (c.contribution || 0) > 0).length, contre = l.filter(c => (c.contribution || 0) < 0).length;
  return { pour, contre, neutres: l.length - pour - contre, texte: `${pour} moteur${pour > 1 ? "s" : ""} pour, ${contre} contre` };
}
