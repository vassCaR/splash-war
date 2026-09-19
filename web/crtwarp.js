/* =====================================================================
   CRTWarp — plasma de tube cathodique, en fond de page.

   Portage du composant React/three.js fourni. Le fragment shader est repris
   tel quel, uniform pour uniform : le rendu est identique.

   Pourquoi pas three.js : le composant ne s'en sert que pour une camera
   orthographique, un PlaneGeometry(2,2) et un ShaderMaterial, autrement dit
   le quad plein ecran le plus banal qui soit. three r180 pese 2 Mo pour ca.
   En WebGL brut le meme shader tient en quelques dizaines de lignes, ne
   demande aucun bundler, et ne fait rien telecharger a la salle un jour de
   hackathon. three reste installe dans node_modules si tu en as besoin
   ailleurs.

       CRTWarp.mount(document.getElementById("bgfx"), { color: "#bc36f3", ... });

   Degradations volontaires : si WebGL manque, la fonction sort en silence et
   la page reste parfaitement jouable. L'animation se coupe quand l'onglet
   passe en arriere-plan et quand l'utilisateur demande moins de mouvement.
   ===================================================================== */

const CRTWarp = (() => {

const VERT = `
attribute vec2 aPos;
varying vec2 vUv;
void main() {
  vUv = aPos * 0.5 + 0.5;
  gl_Position = vec4(aPos, 0.0, 1.0);
}
`;

const FRAG = `
precision highp float;

varying vec2 vUv;
uniform vec2 uResolution;
uniform float uTime;
uniform vec3 uColor;
uniform vec3 uBackgroundColor;
uniform float uCurvature;
uniform float uScanlineStrength;
uniform float uScanlineFrequency;
uniform float uWaveAmplitude;
uniform float uWaveFrequency;
uniform float uBloom;
uniform float uBloomRadius;
uniform float uNoise;
uniform float uVignette;
uniform float uBrightness;
uniform float uPixelation;
uniform float uRgbShift;
uniform vec2 uPointer;
uniform float uMouseStrength;
uniform float uMouseReact;

float hash21(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

vec2 crtCurve(vec2 uv, float radius) {
  vec2 p = (uv - 0.5) * 2.0;
  float safeRadius = max(radius, 1.415);
  float cornerScale = safeRadius / sqrt(max(safeRadius * safeRadius - 2.0, 0.001));
  p = safeRadius * p / sqrt(max(safeRadius * safeRadius - dot(p, p), 0.001));
  p /= cornerScale;
  return p * 0.5 + 0.5;
}

float referencePlasma(vec2 uv, float t) {
  float frequencyScale = max(uWaveFrequency / 2.2, 0.001);
  uv = (uv - 0.5) * frequencyScale + 0.5;

  float scanline = 0.5 - 0.5 * cos(uv.y * 3.14159265 * uScanlineFrequency);
  scanline = mix(1.0, scanline, uScanlineStrength);

  uv *= vec2(80.0, 24.0);
  uv = ceil(uv);
  uv /= vec2(80.0, 24.0);

  float amplitude = uWaveAmplitude / 0.28;
  float field = 0.0;
  field += 0.7 * sin(0.5 * uv.x + t / 5.0);
  field += 3.0 * sin(1.6 * uv.y + t / 5.0);
  field += sin(10.0 * (uv.y * sin(t / 2.0) + uv.x * cos(t / 5.0)) + t / 2.0);

  float cx = uv.x + 0.5 * sin(t / 2.0);
  float cy = uv.y + 0.5 * cos(t / 4.0);
  field += 0.4 * sin(sqrt(100.0 * cx * cx + 100.0 * cy * cy + 1.0) + t);
  field += 0.9 * sin(sqrt(75.0 * cx * cx + 25.0 * cy * cy + 1.0) + t);
  field -= 1.4 * sin(sqrt(256.0 * cx * cx + 25.0 * cy * cy + 1.0) + t);
  field += 0.3 * sin(0.5 * uv.y + uv.x + sin(t));

  return scanline * floor(3.0 * (0.5 + 0.499 * sin(field * amplitude))) / 3.0;
}

void main() {
  vec2 uv = vUv;
  if (uPixelation > 1.001) {
    vec2 cells = max(uResolution / uPixelation, vec2(1.0));
    uv = (floor(uv * cells) + 0.5) / cells;
  }

  float curveRadius = 1.1 + 0.42 / max(uCurvature, 0.001);
  if (uMouseReact > 0.5) {
    curveRadius *= exp(-uPointer.y * uMouseStrength * 0.4);
  }
  vec2 curvedUv = crtCurve(uv, curveRadius);
  if (uMouseReact > 0.5) {
    curvedUv.x -= uPointer.x * uMouseStrength * 0.035;
  }

  float signal = referencePlasma(curvedUv, uTime);
  float radius = 0.01 * uBloomRadius;
  float glow = signal * 0.2;
  glow += referencePlasma(curvedUv + vec2(radius, 0.0), uTime) * 0.12;
  glow += referencePlasma(curvedUv - vec2(radius, 0.0), uTime) * 0.12;
  glow += referencePlasma(curvedUv + vec2(0.0, radius), uTime) * 0.12;
  glow += referencePlasma(curvedUv - vec2(0.0, radius), uTime) * 0.12;
  glow += referencePlasma(curvedUv + vec2(radius), uTime) * 0.08;
  glow += referencePlasma(curvedUv - vec2(radius), uTime) * 0.08;
  glow += referencePlasma(curvedUv + vec2(radius, -radius), uTime) * 0.08;
  glow += referencePlasma(curvedUv + vec2(-radius, radius), uTime) * 0.08;

  float redSignal = referencePlasma(curvedUv + vec2(uRgbShift, 0.0), uTime);
  float blueSignal = referencePlasma(curvedUv - vec2(uRgbShift, 0.0), uTime);
  vec3 channelSignal = vec3(redSignal, signal, blueSignal);
  vec3 waveColor = uColor * (0.3 + signal * 0.7 + glow * uBloom * 0.65);
  waveColor += (channelSignal - signal) * 0.42;

  float edge = clamp(1.0 - dot(vUv - 0.5, vUv - 0.5) * 2.0, 0.0, 1.0);
  float edgeFade = mix(1.0, smoothstep(0.0, 1.0, edge), uVignette);
  float waveMask = clamp(signal * 0.82 + glow * 0.52, 0.0, 1.0) * edgeFade;

  float grain = hash21(gl_FragCoord.xy + vec2(fract(uTime) * 173.0));
  waveColor = max(waveColor * uBrightness, vec3(0.0));
  vec3 color = mix(uBackgroundColor, waveColor, waveMask);
  color += (grain - 0.5) * uNoise;
  gl_FragColor = vec4(max(color, vec3(0.0)), 1.0);
}
`;

const DEFAUTS = {
  color: "#c755f7", backgroundColor: "#05010a", speed: 0.5, curvature: 0.25,
  scanlineStrength: 0.25, scanlineFrequency: 200, waveAmplitude: 0.3,
  waveFrequency: 2.5, bloom: 1.5, bloomRadius: 1, noise: 0.1, vignette: 0,
  brightness: 1.25, pixelation: 1, rgbShift: 0.015, mouseReact: true,
  mouseStrength: 0.5, dpr: 1, fps: 30, paused: false
};

function rgb(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  // conversion sRGB -> lineaire, comme le fait THREE.Color
  const lin = c => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  return [lin(((n >> 16) & 255) / 255), lin(((n >> 8) & 255) / 255), lin((n & 255) / 255)];
}

function compile(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    console.warn("CRTWarp:", gl.getShaderInfoLog(sh));
    return null;
  }
  return sh;
}

function mount(container, options = {}) {
  if (!container) return null;
  const o = { ...DEFAUTS, ...options };

  const cv = document.createElement("canvas");
  cv.style.cssText = "width:100%;height:100%;display:block";
  const gl = cv.getContext("webgl", { antialias: false, alpha: false,
                                      powerPreference: "low-power" })
          || cv.getContext("experimental-webgl");
  if (!gl) return null;                       // pas de WebGL : on laisse le fond uni

  const prog = gl.createProgram();
  const vs = compile(gl, gl.VERTEX_SHADER, VERT);
  const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) return null;
  gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    console.warn("CRTWarp:", gl.getProgramInfoLog(prog));
    return null;
  }
  gl.useProgram(prog);
  container.appendChild(cv);

  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 3,-1, -1,3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "aPos");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

  const U = {};
  for (const n of ["uResolution","uTime","uColor","uBackgroundColor","uCurvature",
                   "uScanlineStrength","uScanlineFrequency","uWaveAmplitude",
                   "uWaveFrequency","uBloom","uBloomRadius","uNoise","uVignette",
                   "uBrightness","uPixelation","uRgbShift","uPointer",
                   "uMouseStrength","uMouseReact"]) {
    U[n] = gl.getUniformLocation(prog, n);
  }

  function pousserReglages() {
    gl.uniform3fv(U.uColor, rgb(o.color));
    gl.uniform3fv(U.uBackgroundColor, rgb(o.backgroundColor));
    gl.uniform1f(U.uCurvature, o.curvature);
    gl.uniform1f(U.uScanlineStrength, o.scanlineStrength);
    gl.uniform1f(U.uScanlineFrequency, o.scanlineFrequency);
    gl.uniform1f(U.uWaveAmplitude, o.waveAmplitude);
    gl.uniform1f(U.uWaveFrequency, o.waveFrequency);
    gl.uniform1f(U.uBloom, o.bloom);
    gl.uniform1f(U.uBloomRadius, o.bloomRadius);
    gl.uniform1f(U.uNoise, o.noise);
    gl.uniform1f(U.uVignette, o.vignette);
    gl.uniform1f(U.uBrightness, o.brightness);
    gl.uniform1f(U.uPixelation, o.pixelation);
    gl.uniform1f(U.uRgbShift, o.rgbShift);
    gl.uniform1f(U.uMouseStrength, o.mouseStrength);
    gl.uniform1f(U.uMouseReact, o.mouseReact ? 1 : 0);
  }
  pousserReglages();

  function redimensionner() {
    const dpr = Math.min(window.devicePixelRatio || 1, o.dpr);
    const w = Math.max(container.clientWidth, 1), h = Math.max(container.clientHeight, 1);
    cv.width = Math.floor(w * dpr); cv.height = Math.floor(h * dpr);
    gl.viewport(0, 0, cv.width, cv.height);
    gl.uniform2f(U.uResolution, cv.width, cv.height);
  }
  new ResizeObserver(redimensionner).observe(container);
  redimensionner();

  // Suivi du pointeur, lisse comme dans le composant d'origine.
  const cible = { x: 0, y: 0 }, courant = { x: 0, y: 0 };
  if (o.mouseReact) {
    addEventListener("pointermove", e => {
      cible.x = (e.clientX / Math.max(innerWidth, 1)) * 2 - 1;
      cible.y = -((e.clientY / Math.max(innerHeight, 1)) * 2 - 1);
    }, { passive: true });
  }

  let visible = true;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(container);

  const moinsDeMouvement = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let t = 0, dernier = 0, precedent = performance.now();

  function boucle(now) {
    requestAnimationFrame(boucle);
    if (!visible || document.hidden) { precedent = now; return; }
    const intervalle = 1000 / Math.max(1, o.fps);
    if (now - dernier < intervalle) return;
    dernier = now - ((now - dernier) % intervalle);

    const delta = Math.min((now - precedent) / 1000, 0.1);
    precedent = now;
    if (!o.paused && !moinsDeMouvement) t += delta * o.speed;

    courant.x += (cible.x - courant.x) * 0.08;
    courant.y += (cible.y - courant.y) * 0.08;
    gl.uniform1f(U.uTime, t);
    gl.uniform2f(U.uPointer, courant.x, courant.y);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  requestAnimationFrame(boucle);

  return {
    set(reglages) { Object.assign(o, reglages); pousserReglages(); redimensionner(); },
    pause(v) { o.paused = v; }
  };
}

return { mount };
})();
