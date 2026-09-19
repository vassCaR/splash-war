/* =====================================================================
   Splash War - retour sonore, synthetise a la volee. Aucun fichier audio.

   Se branche sur l'evenement "tw:paint" emis par index.html a chaque case
   posee. Inclure apres le script principal :

       <script src="sound.js"></script>

   ---------------------------------------------------------------------
   La grammaire sonore : de la peinture, pas du Pong.

   Une pose n'est pas un bip. C'est une giclee : une gifle bruitee tres
   courte (bruit blanc filtre, quelques millisecondes d'attaque) suivie
   d'une queue tonale qui retombe, comme la goutte qui coule apres
   l'impact. Tout est synthetise :
     - la gifle       -> AudioBufferSourceNode sur un tampon de bruit
                         + BiquadFilterNode dont la frequence descend ;
     - la queue       -> un oscillateur avec glissando descendant.
   La hauteur de la queue suit la ligne de la grille, donc un glisse du
   doigt joue une phrase pentatonique au lieu d'un bruit aleatoire, et la
   couleur posee deplace la brillance du filtre : le violet sonne mat, la
   neige sonne claire.

   ---------------------------------------------------------------------
   Les trois pieges mobiles, dans l'ordre ou ils cassent une demo.

   1. touchstart ne debloque PAS l'audio sur iOS.
      La liste des evenements qui portent une activation utilisateur est
      normative (HTML spec, "activation triggering input event") : keydown,
      mousedown, pointerdown uniquement si pointerType vaut "mouse",
      pointerup si ce n'est pas une souris, et touchend. WebKit refuse
      touchstart expres, parce que ce peut etre le debut d'un defilement.
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

  // --- reglages generaux ---------------------------------------------
  const VOIX_MAX = 8;          // une pose a soi coute 2 voix (gifle + queue)
  const ECART_MIN = 55;        // ms entre deux poses a soi (~18/s)
  const ECART_MIN_AUTRES = 120;// ms entre deux poses des autres : elles
                               // arrivent par paquets au polling, il faut les
                               // etaler plus que les siennes sinon la salle
                               // transforme le telephone en machine a coudre
  const VOLUME = 0.22;

  /* Le son a chaque case a ete retire : a dix poses par seconde il tournait au
     bruit blanc et couvrait tout. Les sons sont desormais reserves aux
     evenements qui comptent (jalons, reprise de territoire, fin de manche).
     Remettre a true pour le reactiver. */
  const POSE_SONORE = false;
  const PLANCHER = 0.0001;     // -80 dB : exponentialRamp vers 0 leve une RangeError

  // Gamme pentatonique mineure sur deux octaves. La hauteur suit la ligne de
  // la grille : un glisse vertical joue un arpege au lieu d'un bruit aleatoire.
  // C'est ce qui separe "ca fait du bruit" de "ca sonne".
  const GAMME = [0, 3, 5, 7, 10, 12, 15, 17, 19, 22];
  const BASE = 220;            // la3

  // Tampon de bruit : 0,5 s suffit. On le remplit UNE fois et chaque giclee y
  // pioche un point de depart au hasard. Remplir un tampon neuf a chaque pose
  // couterait 24 000 appels a Math.random() dix fois par seconde pendant qu'un
  // shader plein ecran tourne ; la lecture d'un tampon partage est gratuite.
  // Une boucle de 0,5 s de bruit blanc ne s'entend pas boucler sur des salves
  // de moins de 300 ms.
  const DUREE_TAMPON = 0.5;

  let ctx = null, master = null, bruitTampon = null;
  let voix = new Set(), dernier = 0, dernierAutre = 0;
  let actif = true, arme = null, demarre = false;
  let dernierTemps = -1, dernierMur = 0;

  const note = d => BASE * Math.pow(2, d / 12);

  // Teinte : la couleur posee (1..16) deplace la brillance du bruit.
  // 2^(+-0.75) donne un facteur 0,59 a 1,68, soit une octave et demie entre
  // le violet (1) et la neige (16), et environ 1,2 demi-ton entre deux
  // couleurs voisines : assez pour les distinguer, trop peu pour depayser.
  const teinte = c => Math.pow(2, ((((c || 1) - 1) / 15) - 0.5) * 1.5);

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

    // Limiteur : huit voix empilees (bruit large bande compris) saturent
    // sinon la sortie, et le bruit sature beaucoup plus laid qu'un carre.
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -12;
    comp.knee.value = 0;
    comp.ratio.value = 20;
    comp.attack.value = 0.001;
    comp.release.value = 0.05;
    master.connect(comp).connect(ctx.destination);
    return true;
  }

  /** Tampon de bruit blanc, cree paresseusement et garde pour la session. */
  function tampon() {
    if (bruitTampon) return bruitTampon;
    const n = Math.floor(DUREE_TAMPON * ctx.sampleRate);
    bruitTampon = ctx.createBuffer(1, n, ctx.sampleRate);
    const d = bruitTampon.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    return bruitTampon;
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

    // .then(...).catch(...) et non .catch seul : on avale aussi bien un refus
    // de resume qu'une erreur du carillon, sans jamais laisser une promesse
    // rejetee remonter dans un gestionnaire de geste.
    if (ctx.state !== "running") ctx.resume().then(miseSousTension).catch(() => {});
    else miseSousTension();
    return ctx.state;
  }

  /** Le carillon de borne, une seule fois par session, au vrai deblocage. */
  function miseSousTension() {
    if (demarre || !ctx || ctx.state !== "running" || !actif) return;
    demarre = true;
    demarrage();
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

  /* --- comptabilite des voix ------------------------------------------
     Une voix, c'est { src, env, fin } : src est un oscillateur OU une source
     de tampon, les deux ont start/stop, le vol de voix ne fait pas la
     difference. */
  function inscrire(src, env, fin, entre) {
    const v = { src, env, fin };
    voix.add(v);
    // onended est le SEUL endroit ou on debranche. Un noeud encore relie au
    // master n'est jamais ramasse par le GC : c'est comme ca qu'on fuit une
    // voix par pose, soit six cents noeuds a la minute.
    src.onended = () => {
      try {
        src.disconnect();
        if (entre) entre.disconnect();
        env.disconnect();
      } catch {}
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
      vieille.src.stop(t + 0.006);
    } catch {}
  }

  /**
   * Enveloppe commune : attaque lineaire depuis zero vrai, descente
   * exponentielle vers -80 dB. Une attaque a zero milliseconde fait un clic
   * sur les haut-parleurs de telephone ; viser exactement 0 en exponentiel
   * leve une RangeError.
   */
  function enveloppe(g, t, gain, attaque, palier, duree) {
    g.setValueAtTime(0, t);
    g.linearRampToValueAtTime(gain, t + attaque);
    if (palier) g.setValueAtTime(gain, t + attaque + palier);
    g.exponentialRampToValueAtTime(PLANCHER, t + duree);
    g.setValueAtTime(0, t + duree);
  }

  /* --- une voix tonale : oscillateur + enveloppe, detruite a la fin ---- */
  function blip({ freq, type = "square", duree = 0.09, glissando = 0,
                  palier = 0, gain = 0.5, detune = 0, attaque = 0.002,
                  retard = 0 }) {
    if (!ctx || ctx.state !== "running") return;
    if (voix.size >= VOIX_MAX) voler();

    // Jamais exactement currentTime : une valeur deja passee quand le rendu
    // l'atteint est ignoree et l'attaque saute. retard est en secondes, cale
    // sur l'horloge audio : pas de setTimeout, qui derape a 18 poses/s.
    const t = ctx.currentTime + 0.005 + retard;
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

    enveloppe(env.gain, t, gain, attaque, palier, duree);

    osc.connect(env).connect(master);
    osc.start(t);
    osc.stop(t + duree + 0.005);
    inscrire(osc, env, t + duree);
  }

  /* --- une voix bruitee : tampon + filtre balaye ----------------------
     depart / arrivee sont les deux bouts du balayage de la frequence du
     filtre. Descendant, c'est une matiere qui s'ecrase ; montant, c'est
     quelque chose qui se met en route. */
  function giclee({ depart, arrivee, type = "bandpass", q = 0.9, gain = 0.5,
                    duree = 0.07, attaque = 0.0015, retard = 0, vitesse = 1 }) {
    if (!ctx || ctx.state !== "running") return;
    if (voix.size >= VOIX_MAX) voler();

    const t = ctx.currentTime + 0.005 + retard;
    const src = ctx.createBufferSource();
    const filt = ctx.createBiquadFilter();
    const env = ctx.createGain();

    src.buffer = tampon();
    src.loop = true;                       // salve plus longue que le tampon : impossible ici, mais gratuit
    // La vitesse de lecture transpose le grain du bruit. C'est le second
    // indice de couleur, dans le meme sens que la coupure du filtre.
    src.playbackRate.value = vitesse * (0.94 + Math.random() * 0.12);

    filt.type = type;
    filt.Q.value = q;
    filt.frequency.setValueAtTime(depart, t);
    filt.frequency.exponentialRampToValueAtTime(arrivee, t + duree);

    enveloppe(env.gain, t, gain, attaque, 0, duree);

    src.connect(filt).connect(env).connect(master);
    // Depart de lecture au hasard dans le tampon : deux poses consecutives ne
    // relisent pas le meme grain, sinon l'oreille entend la boucle.
    src.start(t, Math.random() * DUREE_TAMPON);
    src.stop(t + duree + 0.005);
    inscrire(src, env, t + duree, filt);
  }

  /* --- les recettes ---------------------------------------------------- */

  /* Ta pose : la giclee complete, deux voix.

     1. La gifle. Attaque 1,5 ms : en dessous de 1 ms les petits
        haut-parleurs claquent, au-dela de 5 ms l'impact se ramollit en
        souffle. Duree 70 ms : assez pour entendre la matiere, assez court
        pour rester lisible a 18 poses par seconde.
        Le passe-bande tombe de 5200 Hz a 900 Hz (avant teinte) : le haut,
        c'est la pulverisation ; le bas, c'est la masse de peinture qui
        s'etale. Q 0,9, large expres - au-dela de 2 le bruit se met a
        siffler comme un laser et on repart vers l'arcade des annees 80.

     2. La queue. Glissando 0,74, soit environ cinq demi-tons vers le bas en
        85 ms : la goutte qui retombe. Triangle plutot que carre, parce que
        le carre est exactement le timbre de Pong dont on veut sortir ; le
        mordant arcade est deja fourni par la gifle. Decalee de 8 ms pour
        s'entendre APRES l'impact et non dedans. */
  function poseLocale(y, color) {
    const k = teinte(color);
    giclee({
      depart: 5200 * k, arrivee: 900 * k,
      type: "bandpass", q: 0.9,
      gain: 0.55, duree: 0.07, attaque: 0.0015,
      vitesse: Math.sqrt(k)
    });
    blip({
      freq: note(GAMME[y % GAMME.length]) * 2,
      type: "triangle", duree: 0.085, glissando: 0.74,
      gain: 0.38, detune: 18, retard: 0.008
    });
  }

  /* Pose d'un autre : une seule voix, et une voix bruitee qui chante.
     Le passe-bande est cale SUR la note (Q 3,6) : le bruit prend la hauteur
     de la ligne, on garde la phrase musicale sans payer un oscillateur de
     plus. Au-dela de Q 8 il ne reste qu'un sinus et le grain disparait.
     Le balayage 1,6x -> 0,9x autour de la note garde le geste d'ecrasement.
     Le gain a 0,45 est trompeur : un passe-bande resonant mange l'essentiel
     de l'energie du bruit, a l'oreille c'est environ trois fois plus
     discret qu'une pose a soi. La teinte ne touche ici que la vitesse de
     lecture, pas la frequence du filtre, qui porte la note. */
  function poseDistante(y, color) {
    const centre = note(GAMME[y % GAMME.length]) * 2;
    giclee({
      depart: centre * 1.6, arrivee: centre * 0.9,
      type: "bandpass", q: 3.6,
      gain: 0.45, duree: 0.055, attaque: 0.002,
      vitesse: Math.sqrt(teinte(color))
    });
  }

  /* Fin de manche : fanfare courte, arpege pentatonique ascendant
     la - do - mi - la (degres 12, 15, 19, 24), 75 ms d'ecart, tout cale sur
     l'horloge audio. La derniere note tient 360 ms avec palier, et une
     giclee large l'accompagne : le pinceau geant qui s'ecrase. Au pic, deux
     voix seulement se recouvrent, on reste tres loin du plafond. */
  function recompense() {
    [12, 15, 19, 24].forEach((deg, i) => {
      const fin = i === 3;
      blip({
        freq: note(deg), type: "square",
        duree: fin ? 0.36 : 0.09, palier: fin ? 0.08 : 0,
        gain: 0.42, retard: i * 0.075
      });
    });
    giclee({
      depart: 6000, arrivee: 1200, type: "bandpass", q: 0.8,
      gain: 0.45, duree: 0.13, attaque: 0.002, retard: 0.225
    });
  }

  /* Mise sous tension de la borne, jouee au deblocage de l'audio.
     Trois voix, 480 ms en tout :
       - le souffle du tube : passe-bas qui MONTE de 160 a 4200 Hz en 280 ms,
         attaque lente (20 ms) pour que ca enfle au lieu de claquer ;
       - la montee de tension : dent de scie de 110 Hz a 880 Hz (glissando 8),
         gain bas parce que la dent de scie est le timbre le plus agressif
         du lot ;
       - le carillon de confirmation, une fois la montee finie (retard 0,30). */
  function demarrage() {
    giclee({
      depart: 160, arrivee: 4200, type: "lowpass", q: 0.5,
      gain: 0.28, duree: 0.28, attaque: 0.02
    });
    blip({
      freq: 110, type: "sawtooth", duree: 0.3,
      glissando: 8, gain: 0.2, attaque: 0.03
    });
    blip({
      freq: 1318.51, type: "square", duree: 0.18,
      palier: 0.06, gain: 0.38, retard: 0.3
    });
  }

  /* --- branchement ---------------------------------------------------- */
  armer();

  addEventListener("visibilitychange", () => {
    if (!ctx) return;
    if (document.hidden) ctx.suspend().catch(() => {});
    else ctx.resume().catch(() => armer());   // refus = plus d'activation, on rearme
  });

  addEventListener("tw:paint", e => {
    if (!actif || !ctx || ctx.state !== "running" || fige()) return;
    const { y, color, mine } = e.detail;
    const maintenant = performance.now();

    if (mine) {
      if (maintenant - dernier < ECART_MIN) return;
      dernier = maintenant;
      poseLocale(y, color);
    } else {
      if (maintenant - dernierAutre < ECART_MIN_AUTRES) return;
      dernierAutre = maintenant;
      poseDistante(y, color);
    }
  });


  /* ==================================================================
     Boucle musicale de fond, composee et synthetisee ici.

     Rien n'est echantillonne ni emprunte : trois voix carrees ou
     triangulaires plus une percussion de bruit, sur une grille de 16 pas.
     Progression en mineur pentatonique, quatre mesures qui bouclent.

     L'ordonnancement suit le motif classique du Web Audio : un reveil
     toutes les 25 ms qui programme 120 ms a l'avance sur ctx.currentTime.
     Programmer note par note avec setTimeout derape des dizaines de
     millisecondes des que l'onglet travaille, et le tempo part en vrille.
     ================================================================== */

  const TEMPO = 96;                        // battements par minute
  const PAS_PAR_TEMPS = 4;                 // doubles croches
  const HORIZON = 0.12;                    // secondes programmees a l'avance
  const VOLUME_MUSIQUE = 0.10;             // un fond, pas un accompagnement

  // Degres en demi-tons depuis la fondamentale. Quatre mesures.
  const BASSE   = [0,0,7,0, 5,5,0,5, 3,3,10,3, 7,7,5,7];
  const ARPEGE  = [12,15,19,22, 17,20,24,20, 15,19,22,19, 19,22,26,22];
  const CAISSE  = [1,0,0,0, 0,0,0,0, 1,0,0,0, 0,0,0,0];
  const CHARLEY = [0,0,1,0, 0,0,1,0, 0,0,1,0, 0,0,1,0];

  let musiqueActive = false, pas = 0, prochainTemps = 0, horloge = null;
  let busMusique = null;

  function bus() {
    if (!busMusique) {
      busMusique = ctx.createGain();
      busMusique.gain.value = VOLUME_MUSIQUE;
      busMusique.connect(master);
    }
    return busMusique;
  }

  /** Une note de la boucle. Sortie sur le bus musique, pas sur le master. */
  function noteMusique(freq, type, duree, gain, t, detune) {
    const osc = ctx.createOscillator();
    const env = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t);
    if (detune) osc.detune.setValueAtTime(detune, t);
    const g = env.gain;
    g.setValueAtTime(0, t);
    g.linearRampToValueAtTime(gain, t + 0.006);
    g.exponentialRampToValueAtTime(PLANCHER, t + duree);
    g.setValueAtTime(0, t + duree);
    osc.connect(env).connect(bus());
    osc.start(t);
    osc.stop(t + duree + 0.01);
    osc.onended = () => { try { osc.disconnect(); env.disconnect(); } catch {} };
  }

  /** Percussion : bruit filtre, court. La caisse tape bas, le charley haut. */
  function percussion(t, grave) {
    const src = ctx.createBufferSource();
    src.buffer = tampon();
    src.loop = true;
    const filtre = ctx.createBiquadFilter();
    const env = ctx.createGain();
    if (grave) {
      filtre.type = "lowpass";
      filtre.frequency.setValueAtTime(320, t);
      filtre.frequency.exponentialRampToValueAtTime(90, t + 0.08);
    } else {
      filtre.type = "highpass";
      filtre.frequency.setValueAtTime(7200, t);
    }
    const duree = grave ? 0.1 : 0.035;
    const g = env.gain;
    g.setValueAtTime(0, t);
    g.linearRampToValueAtTime(grave ? 0.5 : 0.16, t + 0.002);
    g.exponentialRampToValueAtTime(PLANCHER, t + duree);
    g.setValueAtTime(0, t + duree);
    src.connect(filtre).connect(env).connect(bus());
    src.start(t, Math.random() * 0.4);
    src.stop(t + duree + 0.01);
    src.onended = () => { try { src.disconnect(); filtre.disconnect(); env.disconnect(); } catch {} };
  }

  function jouerPas(i, t) {
    const n = i % 16;
    noteMusique(note(BASSE[n]) / 2, "triangle", 0.30, 0.26, t, 0);
    // L'arpege ne joue pas tous les pas : ca respire, et ca coute moins cher.
    // L'arpege ne tombe qu'un pas sur quatre : ca respire au lieu de marteler.
    if (n % 4 === 0) noteMusique(note(ARPEGE[n]), "sine", 0.42, 0.20, t, 5);
    if (CAISSE[n]) percussion(t, true);
    if (CHARLEY[n]) percussion(t, false);
  }

  function ordonnanceur() {
    if (!musiqueActive || !ctx || ctx.state !== "running") return;
    const intervalle = 60 / TEMPO / PAS_PAR_TEMPS;
    while (prochainTemps < ctx.currentTime + HORIZON) {
      jouerPas(pas, prochainTemps);
      prochainTemps += intervalle;
      pas = (pas + 1) % 16;
    }
  }

  function musique(marche) {
    if (!ctx || ctx.state !== "running") return false;
    if (marche === undefined) marche = !musiqueActive;
    if (marche === musiqueActive) return musiqueActive;
    musiqueActive = marche;
    if (marche) {
      pas = 0;
      prochainTemps = ctx.currentTime + 0.1;
      horloge = setInterval(ordonnanceur, 25);
      ordonnanceur();
    } else {
      clearInterval(horloge);
      horloge = null;
    }
    return musiqueActive;
  }

  // L'onglet en arriere-plan : on coupe, ca ne sert a personne et ca consomme.
  addEventListener("visibilitychange", () => {
    if (document.hidden && musiqueActive) { clearInterval(horloge); horloge = null; }
    else if (!document.hidden && musiqueActive && ctx && ctx.state === "running") {
      prochainTemps = ctx.currentTime + 0.1;
      horloge = setInterval(ordonnanceur, 25);
    }
  });

  return {
    debloquer,
    musique,
    get musiqueActive() { return musiqueActive; },                               // a cabler sur un bouton "activer le son"
    demarrage,
    recompense,
    blip,
    set actif(v) { actif = v; },
    get actif() { return actif; },
    get etat() { return ctx ? ctx.state : "absent"; }
  };
})();
