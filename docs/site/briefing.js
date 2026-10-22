/* Briefing en 60 secondes (palier 9) : plein écran de 9 cartes, le thème puis les 8 engrenages.
   Données : dossiers.json → vue_ensemble.briefing (calcul Python, textes déjà rédigés ; aucun appel, aucune requête).
   Défilement automatique (8 s par carte) coupé par prefers-reduced-motion ; ← → pour naviguer, Échap pour fermer,
   balayage gauche-droite sur mobile. */
import { el, dateCourte } from "./commun.js";

const CONVICTION = ["non déterminée", "faible", "moyenne", "élevée"];

function points(n) {
  const p = el("span", "eg-points");
  p.setAttribute("role", "img");
  p.setAttribute("aria-label", `conviction ${CONVICTION[n] || "non déterminée"}`);
  for (let i = 0; i < 3; i++) p.appendChild(el("i", i < n ? "plein" : null));
  return p;
}

function carteBriefing(c, date) {
  const a = el("article", `bf-carte dir-${c.verdict?.classe || "nd"}`);
  a.appendChild(el("p", "bf-surtitre", `${c.surtitre}${date && c.numero === 0 ? ` · ${dateCourte(date)}` : ""}`));
  a.appendChild(el("h2", "bf-titre", c.titre));

  const verdict = el("div", "bf-verdict");
  verdict.appendChild(el("span", `eg-puce dir-${c.verdict?.classe || "nd"}`, c.verdict?.libelle || "direction non déterminée"));
  verdict.append(points(c.verdict?.conviction || 0), el("span", "eg-petit", `conviction ${CONVICTION[c.verdict?.conviction || 0]}`));
  a.appendChild(verdict);

  const ch = c.chiffre || {};
  const bloc = el("div", "bf-chiffre");
  bloc.appendChild(el("span", "bf-valeur tabulaire", ch.texte || "n/d"));
  bloc.appendChild(el("span", "bf-libelle", `${ch.libelle || "Chiffre clé"}${ch.date ? ` · ${String(ch.date).length > 7 ? dateCourte(ch.date) : ch.date}` : ""}`));
  if (!ch.texte && ch.raison) bloc.appendChild(el("span", "bf-raison", `n/d : ${ch.raison}.`));
  else if (ch.source) bloc.appendChild(el("span", "bf-raison", `Source : ${ch.source}`));
  a.appendChild(bloc);

  if (c.ligne) a.appendChild(el("p", "bf-ligne", c.ligne));

  const retenir = el("div", "bf-retenir");
  retenir.appendChild(el("strong", null, "À retenir"));
  retenir.appendChild(el("p", null, c.a_retenir || "—"));
  retenir.appendChild(el("span", "source", c.a_retenir_source === "modèle" ? "formulé par le modèle à partir des chiffres Python" : "calcul Python"));
  if (c.texte_indisponible) retenir.appendChild(el("p", "bf-indispo", `${c.texte_indisponible}.`));
  a.appendChild(retenir);
  if (c.raison_couleur) a.appendChild(el("p", "note bf-pourquoi", `Pourquoi cette couleur : ${c.raison_couleur}`));
  return a;
}

/* Ouvre le briefing ; `depart` : index de la première carte. Rend le focus à `retour` à la fermeture. */
export function ouvrirBriefing(b, date, retour = null, depart = 0) {
  const cartes = b?.cartes || [];
  if (!cartes.length) return;
  const duree = (b.secondes_par_carte || 8) * 1000;
  const reduit = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  let i = Math.max(0, Math.min(depart, cartes.length - 1)), lecture = !reduit, ecoule = 0, dernier = null, minuterie = null;

  const d = el("dialog", "briefing");
  d.setAttribute("aria-label", "Briefing en 60 secondes");
  const tete = el("div", "bf-tete");
  const titre = el("p", "bf-nom", "Briefing 60 s");
  const compteur = el("span", "bf-compteur tabulaire");
  const fermer = el("button", "bouton", "Fermer");
  fermer.type = "button"; fermer.setAttribute("aria-label", "Fermer le briefing (Échap)");
  tete.append(titre, compteur, fermer);

  const barre = el("div", "bf-progression");
  barre.setAttribute("aria-hidden", "true");
  const segments = cartes.map(() => { const s = el("span", "bf-segment"); s.appendChild(el("i")); barre.appendChild(s); return s; });

  const scene = el("div", "bf-scene");
  scene.setAttribute("aria-live", "polite");
  scene.setAttribute("aria-atomic", "true");

  const commandes = el("div", "bf-commandes");
  const prec = el("button", "bouton", "← Précédent"); prec.type = "button";
  const pause = el("button", "bouton bf-lecture"); pause.type = "button";
  const suiv = el("button", "bouton", "Suivant →"); suiv.type = "button";
  commandes.append(prec, pause, suiv);
  const aide = el("p", "note bf-aide", reduit
    ? "Défilement automatique coupé (réglage « réduire les animations ») : ← → pour avancer, Échap pour fermer."
    : `Défilement automatique toutes les ${duree / 1000} s · ← → pour naviguer · Échap pour fermer · balayage sur mobile.`);

  d.append(tete, barre, scene, commandes, aide);
  document.body.appendChild(d);

  function majProgression() {
    segments.forEach((s, k) => {
      const remplissage = k < i ? 100 : k > i ? 0 : (lecture ? Math.min(100, ecoule / duree * 100) : (reduit ? 100 : ecoule / duree * 100));
      s.firstChild.style.width = `${remplissage}%`;
      s.classList.toggle("actif", k === i);
    });
  }
  function afficher(k) {
    i = Math.max(0, Math.min(k, cartes.length - 1));
    ecoule = 0;
    scene.replaceChildren(carteBriefing(cartes[i], date));
    compteur.textContent = `${i + 1} / ${cartes.length}`;
    prec.disabled = i === 0;
    suiv.disabled = i === cartes.length - 1;
    majProgression();
  }
  function majLecture() {
    pause.textContent = lecture ? "Pause" : "Lecture";
    pause.setAttribute("aria-pressed", String(!lecture));
    pause.setAttribute("aria-label", lecture ? "Mettre en pause le défilement automatique" : "Reprendre le défilement automatique");
    dernier = null;
  }
  function tic(t) {
    if (lecture) {
      if (dernier !== null) ecoule += t - dernier;
      dernier = t;
      if (ecoule >= duree) {
        if (i === cartes.length - 1) { lecture = false; majLecture(); ecoule = duree; }
        else afficher(i + 1);
      }
      majProgression();
    }
    minuterie = requestAnimationFrame(tic);
  }
  let ferme = false;
  function fin() {   // idempotent : bouton Fermer, Échap ou événement « close », selon le navigateur
    if (ferme) return;
    ferme = true;
    if (d.open && typeof d.close === "function") d.close();
    cancelAnimationFrame(minuterie);
    window.removeEventListener("keydown", clavier, true);
    d.remove();
    retour?.focus?.();
  }

  prec.addEventListener("click", () => afficher(i - 1));
  suiv.addEventListener("click", () => afficher(i + 1));
  pause.addEventListener("click", () => { lecture = !lecture; if (lecture && i === cartes.length - 1 && ecoule >= duree) afficher(0); majLecture(); });
  fermer.addEventListener("click", fin);
  d.addEventListener("cancel", e => { e.preventDefault(); fin(); });   // Échap
  d.addEventListener("close", fin);
  // Écoute en capture sur la fenêtre : un bouton désactivé (première ou dernière carte) perd le focus sans couper le
  // clavier, et les flèches ne déplacent jamais le dossier ouvert derrière le briefing (engrenages.js).
  function clavier(e) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    e.stopImmediatePropagation();
    afficher(i + (e.key === "ArrowRight" ? 1 : -1));
  }
  window.addEventListener("keydown", clavier, true);
  // Balayage gauche-droite (mobile) : seuil de 50 px, geste plutôt horizontal que vertical.
  let x0 = null, y0 = null;
  scene.addEventListener("pointerdown", e => { x0 = e.clientX; y0 = e.clientY; });
  scene.addEventListener("pointerup", e => {
    if (x0 === null) return;
    const dx = e.clientX - x0, dy = e.clientY - y0;
    x0 = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) afficher(i + (dx < 0 ? 1 : -1));
  });
  scene.addEventListener("pointercancel", () => { x0 = null; });

  afficher(i);
  majLecture();
  if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
  pause.focus();
  minuterie = requestAnimationFrame(tic);
}
