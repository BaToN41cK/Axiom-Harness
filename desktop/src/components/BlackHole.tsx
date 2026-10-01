import { useEffect, useRef } from "react";
import fallbackImage from "../assets/boot-space.jpg";

/* ------------------------------------------------------------------ BlackHole
   A live, procedurally rendered black hole (WebGL1 fragment shader):
     - turbulent accretion disk with differential rotation (inner orbits are
       faster), temperature colour ramp and Doppler beaming;
     - gravitational lensing: the far side of the disk is bent over and under
       the shadow, plus a crisp photon ring;
     - background stars and red nebula dust are lensed around the hole.

   Performance budget (the boot screen used to lag):
     - rendered at a reduced internal resolution (≈0.55× CSS pixels, max
       1280×720 back-buffer) and upscaled by the compositor;
     - frame rate capped at 40 fps; rendering pauses while the window is hidden;
     - no DOM layers, no blend modes, no backdrop-filter on top of it;
     - `prefers-reduced-motion` → one static frame;
     - no WebGL → the pre-rendered JPEG is shown instead. */

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
  for (int i = 0; i < 4; i++) { v += a * noise(p); p = p * 2.03 + 11.7; a *= 0.5; }
  return v;
}

vec3 starLayer(vec2 p, float scale, float density, float bright) {
  vec2 g = p * scale;
  vec2 id = floor(g);
  vec2 f = fract(g) - 0.5;
  float h = hash(id);
  if (h < density) return vec3(0.0);
  vec2 off = vec2(hash(id + 1.3), hash(id + 2.7)) - 0.5;
  float d = length(f - off * 0.7);
  float tw = 0.55 + 0.45 * sin(uTime * (0.8 + h * 2.5) + h * 40.0);
  vec3 tint = mix(vec3(1.0, 0.82, 0.72), vec3(0.85, 0.9, 1.0), hash(id + 7.1));
  return tint * smoothstep(0.09, 0.0, d) * tw * bright;
}

// Accretion-disk emission at disk-plane radius rd and orbital angle th.
vec3 diskEmission(float rd, float th, float inner, float outer, float rs, float side) {
  if (rd < inner * 0.85 || rd > outer) return vec3(0.0);
  float w = 1.7 * pow(rs / rd, 1.5);            // Keplerian-ish angular speed
  float a = th - uTime * w;
  vec2 cs = vec2(cos(a), sin(a));
  float rr = rd / rs;
  float n = fbm(cs * 3.4 + vec2(rr * 1.7, rr * 1.3));
  float flame = fbm(cs * 1.6 + vec2(rr * 0.6 - uTime * 0.04, rr * 0.9));
  float streak = noise(cs * 9.0 + vec2(rr * 6.5, 0.0));
  float turb = 0.25 + 1.5 * n * (0.45 + 0.8 * flame) * (0.7 + 0.5 * streak);
  float edgeIn = smoothstep(inner * 0.85, inner * 1.12, rd);
  float edgeOut = 1.0 - smoothstep(outer * 0.45, outer, rd);
  float temp = pow(inner / rd, 1.35);            // hotter towards the centre
  float doppler = 1.0 + 0.75 * side;            // approaching side is brighter
  float I = temp * turb * edgeIn * edgeOut * doppler;
  vec3 cool = vec3(0.62, 0.05, 0.02);
  vec3 warm = vec3(1.0, 0.30, 0.05);
  vec3 hot = vec3(1.0, 0.80, 0.52);
  vec3 c = mix(cool, warm, smoothstep(0.08, 0.55, I));
  c = mix(c, hot, smoothstep(0.7, 1.6, I));
  return c * I * 2.1;
}

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  float asp = uRes.x / uRes.y;
  vec2 p = uv - uCenter;
  p.x *= asp;
  float rs = uSize;
  float r = length(p);

  // ---- lensed background (stars + nebula bent around the hole)
  vec2 dir = p / max(r, 1e-4);
  vec2 bp = p - dir * (rs * rs * 1.6) / max(r, rs * 0.6);
  vec2 sp = bp + vec2(uCenter.x * asp, uCenter.y);
  vec3 col = vec3(0.0);
  float neb = fbm(sp * 1.7 + vec2(uTime * 0.006, 0.0));
  float neb2 = fbm(sp * 4.3 + neb * 2.2);
  float nebMask = 0.35 + 0.65 * smoothstep(-1.6, 0.1, p.x);
  col += vec3(0.30, 0.03, 0.025) * pow(neb * neb2, 2.2) * 1.5 * nebMask;
  col += vec3(0.035, 0.004, 0.006) * neb * nebMask;
  col += starLayer(sp, 70.0, 0.962, 1.0);
  col += starLayer(sp + 3.1, 140.0, 0.975, 0.55);

  // ---- disk geometry: tilted plane, slightly rotated
  float ang = -0.16;
  mat2 R = mat2(cos(ang), sin(ang), -sin(ang), cos(ang));
  vec2 q = R * p;
  float tilt = 0.25;
  vec2 dq = vec2(q.x, q.y / tilt);
  float rd = length(dq);
  float th = atan(dq.y, dq.x);
  float inner = rs * 1.45;
  float outer = rs * 5.2;
  float side = -dq.x / max(rd, 1e-4);

  // ---- lensed image of the far side: a halo over and under the shadow
  float phi = atan(q.y, q.x);
  float lr = (r - rs * 1.03) / (rs * 1.5);
  if (lr > 0.0 && lr < 1.0) {
    float rdl = inner + lr * (outer - inner) * 0.4;
    vec3 halo = diskEmission(rdl, phi + 1.57, inner, outer, rs, -cos(phi) * 0.6);
    float sp = sin(phi);
    float arc = 0.18 + 1.0 * pow(max(sp, 0.0), 0.55) + 0.22 * pow(max(-sp, 0.0), 1.8);
    float fade = smoothstep(0.0, 0.06, lr) * (1.0 - smoothstep(0.3, 1.0, lr));
    col += halo * arc * fade * 1.25;
  }

  // ---- photon ring + soft glow
  float ring = exp(-pow((r - rs * 1.035) / (rs * 0.022), 2.0));
  col += vec3(1.0, 0.72, 0.45) * ring * 0.9;
  col += vec3(1.0, 0.32, 0.10) * 0.035 * rs / max(r - rs * 0.9, rs * 0.08);

  // ---- event horizon (shadow)
  float shadow = smoothstep(rs * 0.98, rs * 1.03, r);
  col *= shadow;

  // ---- disk: near half crosses in front of the shadow, far half is hidden
  vec3 disk = diskEmission(rd, th, inner, outer, rs, side);
  float behind = step(0.0, q.y) * (1.0 - smoothstep(rs * 0.98, rs * 1.06, r));
  col += disk * (1.0 - behind);

  // ---- tone map + intro
  col = 1.0 - exp(-col * 1.25);
  col = pow(col, vec3(0.95));
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
      // Keep the black hole alive: the whole thing drifts on a slow Lissajous
      // orbit and its shadow radius breathes, while the disk keeps rotating.
      const driftX = 0.05 * Math.sin(t * 0.23 + 0.4);
      const driftY = 0.04 * Math.sin(t * 0.31 + 2.1);
      const breathe = 1.0 + 0.022 * Math.sin(t * 0.34 + 0.6);
      gl.uniform2f(uCenter, (narrow ? 0.9 : 0.76) + driftX, 0.52 + driftY);
      gl.uniform1f(uSize, (narrow ? 0.1 : 0.125) * breathe);
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
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
  }, []);

  return (
    <div className={"blackhole " + (className ?? "")} aria-hidden>
      <canvas ref={canvasRef} className="blackhole-canvas" />
      <div ref={fallbackRef} className="blackhole-fallback" style={{ backgroundImage: `url(${fallbackImage})` }} />
    </div>
  );
}
