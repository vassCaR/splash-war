/* =====================================================================
   Retour sonore d'arcade, synthetise a la volee. Aucun fichier audio.

   Se branche sur l'evenement "tw:paint" emis par index.html a chaque case
   posee. Inclure apres le script principal :

       <script src="sound.js"></script>

   Trois pieges mobiles sont traites ici, dans l'ordre d'importance :

   1. iOS exige un geste utilisateur pour demarrer l'audio. On cree donc le
      contexte au premier pointerdown, pas au chargement.

   2. Le bouton silence physique de l'iPhone coupe le Web Audio. Le seul
      contournement est de forcer la categorie de session audio en jouant un
      element <audio> muet et playsinline. Sans ca, la moitie de la salle
      n'entendra rien et personne ne comprendra pourquoi.

   3. A 15 poses par seconde, empiler les voix sature le haut-parleur et le
      CPU. On plafonne la polyphonie et on impose un intervalle minimum.
   ===================================================================== */

const TWSound = (() => {

  // --- reglages ------------------------------------------------------
  const VOIX_MAX = 6;          // voix simultanees
  const ECART_MIN = 28;        // ms entre deux poses a soi
  const ECART_MIN_AUTRES = 55; // ms entre deux poses des autres
  const VOLUME = 0.22;

  // Gamme pentatonique mineure sur 2 octaves. La hauteur suit la ligne de la
  // grille : un glisse vertical joue un arpege au lieu d'un bruit aleatoire.
  // C'est ce qui fait la difference entre "ca fait du bruit" et "ca sonne".
  const GAMME = [0, 3, 5, 7, 10, 12, 15, 17, 19, 22];
  const BASE = 220;            // la3

  let ctx = null, master = null, debloque = false;
  let voix = 0, dernier = 0, dernierAutre = 0;
  let actif = true;

  function note(demiTons) {
    return BASE * Math.pow(2, demiTons / 12);
  }

  /* --- deblocage : a appeler DANS un gestionnaire de geste utilisateur --- */
  function debloquer() {
    if (debloque) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;

    ctx = new AC({ latencyHint: "interactive" });
    master = ctx.createGain();
    master.gain.value = VOLUME;
    master.connect(ctx.destination);

    // iOS suspend le contexte tant qu'un geste ne l'a pas repris.
    if (ctx.state === "suspended") ctx.resume();

    // Contourne le bouton silence : un element audio muet en lecture bascule
    // la session dans une categorie que le switch ne coupe pas.
    try {
      const a = document.createElement("audio");
      a.setAttribute("playsinline", "");
      a.setAttribute("muted", "");
      a.muted = true;
      a.loop = true;
      // 0,05 s de silence, en wav, pour ne dependre d'aucun fichier externe
      a.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9" +
              "AAACABAAZGF0YQAAAAA=";
      a.play().catch(() => {});
    } catch {}

    debloque = true;
  }

  /* --- une voix : oscillateur + enveloppe, detruite a la fin ---------- */
  function blip({ freq, type = "square", duree = 0.09, glissando = 0, gain = 1 }) {
    if (!ctx || voix >= VOIX_MAX) return;

    const t = ctx.currentTime;
    const osc = ctx.createOscillator();
    const env = ctx.createGain();

    osc.type = type;
    osc.frequency.setValueAtTime(freq, t);
    if (glissando) {
      // le petit "pew" descendant ou montant qui fait tout le cachet arcade
      osc.frequency.exponentialRampToValueAtTime(freq * glissando, t + duree);
    }

    // Attaque courte mais jamais instantanee : passer de 0 a 1 d'un coup
    // produit un clic audible. Et la descente doit viser une valeur non nulle,
    // exponentialRamp vers 0 est invalide.
    env.gain.setValueAtTime(0.0001, t);
    env.gain.exponentialRampToValueAtTime(gain, t + 0.005);
    env.gain.exponentialRampToValueAtTime(0.0001, t + duree);

    osc.connect(env).connect(master);
    osc.start(t);
    osc.stop(t + duree + 0.01);

    voix++;
    osc.onended = () => { voix--; osc.disconnect(); env.disconnect(); };
  }

  /* --- les deux timbres ---------------------------------------------- */

  // Ta pose : franc, net, legerement montant. C'est la recompense du geste.
  function poseLocale(y) {
    blip({
      freq: note(GAMME[y % GAMME.length]) * 2,
      type: "square",
      duree: 0.07,
      glissando: 1.06,
      gain: 1
    });
  }

  // Pose d'un autre : plus grave, plus discret, sinon une salle active
  // transforme le telephone en machine a coudre.
  function poseDistante(y) {
    blip({
      freq: note(GAMME[y % GAMME.length]),
      type: "triangle",
      duree: 0.05,
      gain: 0.35
    });
  }

  /* --- branchement --------------------------------------------------- */

  // Le deblocage doit se produire pendant le geste, donc en capture et avant
  // tout le reste. pointerdown couvre souris et tactile.
  addEventListener("pointerdown", debloquer, { capture: true });
  addEventListener("touchstart", debloquer, { capture: true, passive: true });

  // Le contexte est suspendu quand l'onglet passe en arriere-plan.
  addEventListener("visibilitychange", () => {
    if (!ctx) return;
    if (document.hidden) ctx.suspend();
    else ctx.resume();
  });

  addEventListener("tw:paint", e => {
    if (!actif || !ctx || ctx.state !== "running") return;
    const { y, mine } = e.detail;
    const maintenant = performance.now();

    if (mine) {
      if (maintenant - dernier < ECART_MIN) return;
      dernier = maintenant;
      poseLocale(y);
    } else {
      if (maintenant - dernierAutre < ECART_MIN_AUTRES) return;
      dernierAutre = maintenant;
      poseDistante(y);
    }
  });

  return {
    debloquer,
    set actif(v) { actif = v; },
    get actif() { return actif; },
    get etat() { return ctx ? ctx.state : "absent"; },
    /* Pour tester une recette depuis la console :
       TWSound.blip({ freq: 880, type: "square", duree: 0.08, glissando: 1.5 }) */
    blip
  };
})();
