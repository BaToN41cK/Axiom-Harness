import { useEffect, useRef } from "react";
import fallbackImage from "../assets/boot-space.jpg";

/* ------------------------------------------------------------------ BlackHole
   A live, procedurally rendered black hole (WebGL1 fragment shader) — the
   iconic edge-on silhouette in a red-and-black key:
     - a dark, crisp event-horizon sphere at the centre;
     - a bright red accretion disk seen nearly edge-on (a thin band through
       the middle), with differential rotation, turbulence and Doppler beaming;
     - gravitational lensing bends the far side of the disk up and over (and a
       thinner image under) the shadow — the signature halo arc;
     - a tight red photon ring hugs the horizon; swirling embers orbit the disk;
     - the background star field and red nebula are lensed around the hole.

   Performance budget (the boot screen used to lag):
     - rendered at a reduced internal resolution (~0.55x CSS pixels, max
       1280x720 back-buffer) and upscaled by the compositor;
     - frame rate capped at 40 fps; rendering pauses while the window is hidden;
     - no DOM layers, no blend modes, no backdrop-filter on top of it;
     - `prefers-reduced-motion` -> one static frame;
     - no WebGL -> the pre-rendered JPEG is shown instead. */

const VERT = `
attribute vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`;

const FRAG = `
precision highp float;
uniform vec2 uRes;
uniform float uTime;
uniform vec2 uCenter;   // black-hole centre, 0..1 of the viewport
uniform float uSize;    // shadow radius in viewport heights
uniform float uReveal;  // 0..1 intro

#define TAU 6.2831853

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
             mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.03 + 11.7; a *= 0.5; }
  return v;
}

// Faint ash/ember star field behind the maelstrom (kept in the red/black key).
vec3 starLayer(vec2 p, float scale, float density, float bright) {
  vec2 g = p * scale;
  vec2 id = floor(g);
  vec2 f = fract(g) - 0.5;
  float h = hash(id);
  if (h < density) return vec3(0.0);
  vec2 off = vec2(hash(id + 1.3), hash(id + 2.7)) - 0.5;
  float d = length(f - off * 0.7);
  float tw = 0.55 + 0.45 * sin(uTime * (0.8 + h * 2.5) + h * 40.0);
  vec3 tint = mix(vec3(0.55, 0.52, 0.56), vec3(0.9, 0.28, 0.26), hash(id + 7.1));
  return tint * smoothstep(0.08, 0.0, d) * tw * bright;
}

// Red-and-black temperature ramp shared by every emissive layer: deep near-black
// maroon -> blood red -> bright red crest. Deliberately no orange / gold.
vec3 redRamp(float I) {
  vec3 ember = vec3(0.14, 0.006, 0.012);
  vec3 blood = vec3(0.85, 0.045, 0.05);
  vec3 crest = vec3(1.0, 0.33, 0.26);
  vec3 c = mix(ember, blood, smoothstep(0.05, 0.5, I));
  c = mix(c, crest, smoothstep(0.65, 1.5, I));
  return c * I;
}

// ------------------------------------------------------------- accretion disk
// Emission of the accretion disk at disk-plane radius rd (in shadow radii) and
// orbital angle th. Differential rotation (inner orbits faster) + turbulence +
// Doppler beaming on the approaching side. Red-and-black only.
vec3 diskEmission(float rd, float th, float inner, float outer, float side) {
  if (rd < inner * 0.9 || rd > outer) return vec3(0.0);
  float w = 2.2 * pow(1.0 / rd, 1.5);              // Keplerian-ish angular speed
  float a = th - uTime * w;
  vec2 cs = vec2(cos(a), sin(a));
  float n = fbm(cs * 3.2 + vec2(rd * 1.7, rd * 1.1));
  float flame = fbm(cs * 1.5 + vec2(rd * 0.5 - uTime * 0.05, rd * 0.8));
  float streak = noise(cs * 9.0 + vec2(rd * 6.5, 0.0));
  float turb = 0.3 + 1.5 * n * (0.45 + 0.8 * flame) * (0.7 + 0.5 * streak);
  float edgeIn = smoothstep(inner * 0.9, inner * 1.15, rd);
  float edgeOut = 1.0 - smoothstep(outer * 0.5, outer, rd);
  float temp = pow(inner / rd, 1.4);               // hotter towards the centre
  float doppler = 1.0 + 0.85 * side;               // approaching side brighter
  float I = temp * turb * edgeIn * edgeOut * doppler;
  return redRamp(I) * 2.3;
}

// Swirling embers orbiting in the disk plane; share the disk's rotation.
vec3 swirlParticles(vec2 dq, float inner, float outer) {
  vec3 acc = vec3(0.0);
  for (int i = 0; i < 18; i++) {
    float fi = float(i);
    float seed = hash(vec2(fi, 3.0));
    float orad = mix(inner * 1.05, outer * 0.95, hash(vec2(fi, 7.0)));
    float w = 2.2 * pow(1.0 / orad, 1.5);
    float ang = seed * TAU + uTime * w;
    vec2 pp = vec2(cos(ang), sin(ang)) * orad;
    float size = mix(0.05, 0.13, hash(vec2(fi, 11.0)));
    float d = length(dq - pp);
    float glow = exp(-pow(d / size, 2.0));
    float tw = 0.55 + 0.45 * sin(uTime * (1.3 + seed * 2.6) + seed * 24.0);
    vec3 tint = mix(vec3(0.95, 0.09, 0.07), vec3(1.0, 0.34, 0.26), tw);
    acc += tint * glow * tw * mix(0.5, 1.2, hash(vec2(fi, 17.0)));
  }
  return acc;
}

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  float asp = uRes.x / uRes.y;
  vec2 p = uv - uCenter;
  p.x *= asp;
  float rs = uSize;
  float r = length(p);

  vec3 col = vec3(0.0);

  // ---- lensed background: stars + red nebula bent around the hole
  vec2 dir = p / max(r, 1e-4);
  vec2 bp = p - dir * (rs * rs * 1.7) / max(r, rs * 0.6);
  vec2 sp = bp + vec2(uCenter.x * asp, uCenter.y);
  float neb = fbm(sp * 1.8 + vec2(uTime * 0.006, 0.0));
  float neb2 = fbm(sp * 4.6 + neb * 2.1);
  col += vec3(0.30, 0.02, 0.028) * pow(neb * neb2, 2.1) * 1.4;
  col += vec3(0.04, 0.004, 0.008) * neb;
  col += starLayer(sp, 70.0, 0.965, 1.0);
  col += starLayer(sp + 3.1, 140.0, 0.976, 0.55);

  // ---- disk geometry: a nearly edge-on plane (strong foreshortening), so the
  // disk reads as a thin bright band through the middle of the hole.
  float inner = 1.5;      // in shadow radii
  float outer = 6.0;
  float tilt = 0.17;      // small => near edge-on (the Gargantua look)
  // Near side of the disk (crosses in FRONT of / below the shadow).
  vec2 dq = vec2(p.x, p.y / tilt) / rs;
  float rd = length(dq);
  float th = atan(dq.y, dq.x);
  float side = -dq.x / max(rd, 1e-4);
  vec3 diskFront = diskEmission(rd, th, inner, outer, side);
  diskFront += swirlParticles(dq, inner, outer);

  // ---- gravitational lensing: the FAR side of the disk is bent up and over
  // the top of the shadow (and a thinner image under it) - the halo arc.
  float phi = atan(p.y, p.x);
  float lr = (r - rs * 1.05) / (rs * 2.2);
  vec3 halo = vec3(0.0);
  if (lr > 0.0 && lr < 1.0) {
    float rdl = inner + lr * (outer - inner);
    halo = diskEmission(rdl, phi + 1.57, inner, outer, -cos(phi) * 0.7);
    float s = sin(phi);
    float arc = 0.2 + 1.0 * pow(max(s, 0.0), 0.5) + 0.3 * pow(max(-s, 0.0), 1.6);
    float fade = smoothstep(0.0, 0.05, lr) * (1.0 - smoothstep(0.45, 1.0, lr));
    halo *= arc * fade * 1.3;
  }
  col += halo;

  // ---- photon ring + soft glow hugging the horizon (red-hot)
  float ring = exp(-pow((r - rs * 1.045) / (rs * 0.02), 2.0));
  col += vec3(1.0, 0.42, 0.32) * ring * 1.0;
  col += vec3(1.0, 0.16, 0.08) * 0.04 * rs / max(r - rs * 0.9, rs * 0.08);

  // ---- event horizon: crisp black sphere swallows everything inside.
  float shadow = smoothstep(rs * 0.97, rs * 1.03, r);
  col *= shadow;

  // ---- composite the front half of the disk IN FRONT of the shadow.
  // The near half (p.y below the centre line) is drawn after occlusion so it
  // crosses over the black sphere; the far half behind is hidden by it.
  float behind = step(0.0, p.y) * (1.0 - smoothstep(rs * 0.97, rs * 1.06, r));
  col += diskFront * (1.0 - behind);

  // ---- gentle vignette to seat the hole in black and protect the text side
  float vig = 1.0 - smoothstep(0.5, 1.25, length(uv - 0.5));
  col *= 0.4 + 0.6 * vig;

  // ---- tone map + intro reveal
  col = 1.0 - exp(-col * 1.3);
  col = pow(col, vec3(0.92));
  col *= uReveal;
  gl_FragColor = vec4(col, 1.0);
}
`;

interface Props {
  className?: string;
}

function compile(gl: WebGLRenderingContext, type: number, src: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, src);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.warn("[BlackHole] shader:", gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

const MAX_FPS = 40;
const RES_SCALE = 0.55;
const MAX_PIXELS = 1280 * 720;

export default function BlackHole({ className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fallbackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const showFallback = () => {
      canvas.style.display = "none";
      if (fallbackRef.current) fallbackRef.current.style.display = "block";
    };
    // Each (re)mount starts from the live-canvas state; a fallback left behind
    // by a previous StrictMode mount must not stick if this mount succeeds.
    canvas.style.display = "block";
    if (fallbackRef.current) fallbackRef.current.style.display = "none";

    const gl = canvas.getContext("webgl", {
      antialias: false,
      alpha: false,
      depth: false,
      stencil: false,
      preserveDrawingBuffer: false,
      powerPreference: "low-power",
    });
    if (!gl) { showFallback(); return; }

    const vs = compile(gl, gl.VERTEX_SHADER, VERT);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    const prog = gl.createProgram();
    if (!vs || !fs || !prog) { showFallback(); return; }
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { showFallback(); return; }
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "aPos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(prog, "uRes");
    const uTime = gl.getUniformLocation(prog, "uTime");
    const uCenter = gl.getUniformLocation(prog, "uCenter");
    const uSize = gl.getUniformLocation(prog, "uSize");
    const uReveal = gl.getUniformLocation(prog, "uReveal");

    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    let width = 0;
    let height = 0;
    let cssW = 1;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      cssW = Math.max(1, rect.width);
      const cssH = Math.max(1, rect.height);
      let w = Math.round(cssW * RES_SCALE * Math.min(1.5, window.devicePixelRatio || 1));
      let h = Math.round(cssH * RES_SCALE * Math.min(1.5, window.devicePixelRatio || 1));
      const px = w * h;
      if (px > MAX_PIXELS) {
        const k = Math.sqrt(MAX_PIXELS / px);
        w = Math.round(w * k);
        h = Math.round(h * k);
      }
      if (w !== width || h !== height) {
        width = w;
        height = h;
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
      }
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const start = performance.now();
    let raf = 0;
    let lastDraw = 0;
    let running = true;

    const draw = (now: number) => {
      const t = (now - start) / 1000;
      const narrow = cssW < 860;
      gl.uniform2f(uRes, width, height);
      gl.uniform1f(uTime, t + 12.0);
      // Keep the vortex alive: the whole maelstrom drifts on a slow Lissajous
      // orbit and its horizon radius breathes, while the spiral keeps winding.
      const driftX = 0.05 * Math.sin(t * 0.23 + 0.4);
      const driftY = 0.04 * Math.sin(t * 0.31 + 2.1);
      const breathe = 1.0 + 0.022 * Math.sin(t * 0.34 + 0.6);
      gl.uniform2f(uCenter, (narrow ? 0.72 : 0.72) + driftX, 0.5 + driftY);
      gl.uniform1f(uSize, (narrow ? 0.085 : 0.11) * breathe);
      gl.uniform1f(uReveal, reduceMotion ? 1 : Math.min(1, t / 1.4) ** 1.6);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };

    const loop = (now: number) => {
      if (!running) return;
      raf = requestAnimationFrame(loop);
      if (now - lastDraw < 1000 / MAX_FPS - 1) return;
      lastDraw = now;
      draw(now);
    };

    if (reduceMotion) {
      draw(start + 2000);
    } else {
      raf = requestAnimationFrame(loop);
    }

    const onVisibility = () => {
      if (reduceMotion) return;
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(raf);
      } else if (!running) {
        running = true;
        raf = requestAnimationFrame(loop);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    const onLost = (event: Event) => { event.preventDefault(); running = false; cancelAnimationFrame(raf); showFallback(); };
    canvas.addEventListener("webglcontextlost", onLost);

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      canvas.removeEventListener("webglcontextlost", onLost);
      gl.deleteBuffer(buf);
      gl.deleteProgram(prog);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      // NB: do NOT call WEBGL_lose_context.loseContext() here. React StrictMode
      // (dev) mounts → cleans up → mounts again on the SAME <canvas> node; a
      // force-lost context stays lost, so the remount's getContext() returns a
      // dead context and every shader "fails" with a null info log, dropping us
      // onto the JPEG fallback. Deleting the GL objects above is enough; the
      // context itself is reclaimed when the canvas is garbage-collected.
    };
  }, []);

  return (
    <div className={"blackhole " + (className ?? "")} aria-hidden>
      <canvas ref={canvasRef} className="blackhole-canvas" />
      <div ref={fallbackRef} className="blackhole-fallback" style={{ backgroundImage: `url(${fallbackImage})` }} />
    </div>
  );
}
