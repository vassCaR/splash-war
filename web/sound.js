/* =====================================================================
   Retour sonore d'arcade, synthetise a la volee. Aucun fichier audio.

   Se branche sur l'evenement "tw:paint" emis par index.html a chaque case
   posee. Inclure apres le script principal :

       <script src="sound.js"></script>

   ---------------------------------------------------------------------
   Les trois pieges mobiles, dans l'ordre ou ils cassent une demo.

   1. touchstart ne debloque PAS l'audio sur iOS.
      La liste des evenements qui portent une activation utilisateur est
      normative (HTML spec, "activation triggering input event") : keydown,
      mousedown, pointerdown uniquement si pointerType vaut "mouse",
      pointerup si ce n'est pas une souris, et touchend. WebKit refuse
      touchstart exprès, parce que ce peut etre le debut d'un defilement.
      Consequence directe pour un jeu au doigt : si on ne debloque que sur
      le geste de peinture, le premier glisse est muet. On arme donc sur
      pointerup / touchend / click, et on reessaie tant que le contexte
      n'est pas reellement "running".

   2. Le bouton silence de l'iPhone coupe le Web Audio.
      Cause documentee : la categorie de session par defaut d'un
      AudioContext est "ambient", justement celle que l'interrupteur coupe.
      La parade est navigator.audioSession.type = "playback", a poser AVANT
      de creer le contexte (Safari 16.4+, ignore ailleurs).
      Le vieux contournement du fichier MP3 muet est a proscrire : il
      provoque desormais l'arret du son au bout d'une seconde.

   3. Le contexte est suspendu en arriere-plan et ne revient pas toujours.
      Pire, il peut annoncer "running" avec un currentTime fige. On surveille
      donc l'horloge et on force un suspend/resume si elle ne bouge plus.
   ===================================================================== */

const TWSound = (() => {

  // --- reglages ------------------------------------------------------
  const VOIX_MAX = 8;
  const ECART_MIN = 55;        // ms entre deux poses a soi (~18/s)
  const ECART_MIN_AUTRES = 90; // ms entre deux poses des autres
  const VOLUME = 0.22;
  const PLANCHER = 0.0001;     // -80 dB : exponentialRamp vers 0 leve une RangeError

  // Gamme pentatonique mineure sur deux octaves. La hauteur suit la ligne de
  // la grille : un glisse vertical joue un arpege au lieu d'un bruit aleatoire.
  // C'est ce qui separe "ca fait du bruit" de "ca sonne".
  const GAMME = [0, 3, 5, 7, 10, 12, 15, 17, 19, 22];
  const BASE = 220;            // la3

  let ctx = null, master = null;
  let voix = new Set(), dernier = 0, dernierAutre = 0;
  let actif = true, arme = null;
  let dernierTemps = -1, dernierMur = 0;

  const note = d => BASE * Math.pow(2, d / 12);

  /* --- creation du contexte ------------------------------------------ */
  function creer() {
    // A poser avant la creation du contexte, sinon la session reste en
    // "ambient" et l'interrupteur silence coupe tout. Contrepartie assumee :
    // "playback" nous declare application media, donc la musique de fond de
    // l'utilisateur peut etre interrompue. Pour une demo en salle, c'est ce
    // qu'on veut.
    if ("audioSession" in navigator) {
      try { navigator.audioSession.type = "playback"; } catch {}
    }

    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    ctx = new AC({ latencyHint: "interactive" });

    master = ctx.createGain();
    master.gain.value = VOLUME;

    // Limiteur : huit voix carrees empilees saturent sinon la sortie.
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -12;
    comp.knee.value = 0;
    comp.ratio.value = 20;
    comp.attack.value = 0.001;
    comp.release.value = 0.05;
    master.connect(comp).connect(ctx.destination);
    return true;
  }

  /**
   * A appeler DANS un gestionnaire de geste, sans await ni setTimeout avant :
   * l'activation utilisateur ne survit ni a l'un ni a l'autre.
   */
  function debloquer() {
    if (!ctx && !creer()) return "absent";

    // Demarrer une source pendant le geste est ce qui ouvre reellement la
    // route de sortie sur WebKit. Un echantillon de silence ne coute rien.
    try {
      const src = ctx.createBufferSource();
      src.buffer = ctx.createBuffer(1, 1, ctx.sampleRate);
      src.connect(ctx.destination);
      src.start(0);
    } catch {}

    if (ctx.state !== "running") ctx.resume().catch(() => {});
    return ctx.state;
  }

  /* --- armement : on reessaie tant que ce n'est pas vraiment debloque -- */
  function armer() {
    if (arme) return;
    // pointerdown est valide a la souris, pas au doigt. On ecoute donc aussi
    // les evenements de relachement, qui sont les seuls a porter l'activation
    // sur mobile.
    const evts = ["pointerup", "touchend", "click", "keydown", "pointerdown"];
    const h = () => { if (debloquer() === "running") desarmer(); };
    arme = { evts, h };
    evts.forEach(e => addEventListener(e, h, { capture: true, passive: true }));
  }

  function desarmer() {
    if (!arme) return;
    arme.evts.forEach(e => removeEventListener(e, arme.h, { capture: true }));
    arme = null;
  }

  /* --- detection du contexte fige ------------------------------------- */
  function fige() {
    const t = ctx.currentTime, mur = performance.now();
    if (t !== dernierTemps) { dernierTemps = t; dernierMur = mur; return false; }
    if (mur - dernierMur > 1000) {
      dernierMur = mur;
      ctx.suspend().then(() => ctx.resume()).catch(() => {});
      return true;
    }
    return false;
  }

  /* --- une voix : oscillateur + enveloppe, detruite a la fin ---------- */
  function blip({ freq, type = "square", duree = 0.09, glissando = 0,
                  palier = 0, gain = 0.5, detune = 0 }) {
    if (!ctx || ctx.state !== "running") return;
    if (voix.size >= VOIX_MAX) voler();

    const t = ctx.currentTime + 0.005;     // jamais exactement currentTime
    const osc = ctx.createOscillator();
    const env = ctx.createGain();

    osc.type = type;
    // Un peu de desaccord aleatoire : sans ca, des blips identiques se
    // superposent en phase et sonnent mitraillette.
    if (detune) osc.detune.setValueAtTime((Math.random() * 2 - 1) * detune, t);
    osc.frequency.setValueAtTime(freq, t);
    if (glissando) {
      osc.frequency.exponentialRampToValueAtTime(freq * glissando, t + duree);
    }

    // Attaque lineaire depuis zero vrai, descente exponentielle vers -80 dB.
    // Une attaque a zero milliseconde fait un clic ; viser exactement 0 en
    // exponentiel leve une RangeError.
    const g = env.gain;
    g.setValueAtTime(0, t);
    g.linearRampToValueAtTime(gain, t + 0.002);
    if (palier) g.setValueAtTime(gain, t + 0.002 + palier);
    g.exponentialRampToValueAtTime(PLANCHER, t + duree);
    g.setValueAtTime(0, t + duree);

    osc.connect(env).connect(master);
    osc.start(t);
    osc.stop(t + duree + 0.005);

    const v = { osc, env, fin: t + duree };
    voix.add(v);
    osc.onended = () => {
      try { osc.disconnect(); env.disconnect(); } catch {}
      voix.delete(v);
    };
  }

  /** Vol de voix : on eteint la plus ancienne en 5 ms, pas d'un coup sec. */
  function voler() {
    let vieille = null;
    for (const v of voix) if (!vieille || v.fin < vieille.fin) vieille = v;
    if (!vieille) return;
    const t = ctx.currentTime, g = vieille.env.gain;
    try {
      // cancelAndHoldAtTime conserve la valeur courante ; cancelScheduledValues
      // seul ferait resauter le gain a la derniere valeur posee, ce qui claque.
      if (g.cancelAndHoldAtTime) g.cancelAndHoldAtTime(t);
      else { g.cancelScheduledValues(t); g.setValueAtTime(Math.max(g.value, PLANCHER), t); }
      g.exponentialRampToValueAtTime(PLANCHER, t + 0.005);
      g.setValueAtTime(0, t + 0.005);
      vieille.osc.stop(t + 0.006);
    } catch {}
  }

  /* --- les timbres ---------------------------------------------------- */

  // Ta pose : franc, net, legerement montant. La recompense du geste.
  const poseLocale = y => blip({
    freq: note(GAMME[y % GAMME.length]) * 2,
    type: "square", duree: 0.055, palier: 0.012,
    glissando: 1.06, gain: 0.5, detune: 20
  });

  // Pose d'un autre : plus grave et discret, sinon une salle active
  // transforme le telephone en machine a coudre.
  const poseDistante = y => blip({
    freq: note(GAMME[y % GAMME.length]),
    type: "triangle", duree: 0.05, gain: 0.18, detune: 15
  });

  // Fin de manche : deux tons, l'intervalle de la piece de Mario.
  const recompense = () => {
    blip({ freq: 987.77, type: "square", duree: 0.09, gain: 0.45 });
    setTimeout(() => blip({ freq: 1318.51, type: "square",
                            duree: 0.34, palier: 0.075, gain: 0.45 }), 80);
  };

  /* --- branchement ---------------------------------------------------- */
  armer();

  addEventListener("visibilitychange", () => {
    if (!ctx) return;
    if (document.hidden) ctx.suspend().catch(() => {});
    else ctx.resume().catch(() => armer());   // refus = plus d'activation, on rearme
  });

  addEventListener("tw:paint", e => {
    if (!actif || !ctx || ctx.state !== "running" || fige()) return;
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
    debloquer,                               // a cabler sur un bouton "activer le son"
    recompense,
    blip,
    set actif(v) { actif = v; },
    get actif() { return actif; },
    get etat() { return ctx ? ctx.state : "absent"; }
  };
})();
