/**
 * Runtime GUI verification for AXIOM desktop.
 *
 * Serves desktop/dist, launches headless Edge via CDP with a Tauri `invoke`
 * shim backed by the REAL Python core (axiom_bridge.py), then drives the UI.
 */
import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

const DEBUG = !!process.env.E2E_DEBUG;
const dbg = (...a) => {
  if (DEBUG) console.log("[debug]", ...a);
};

const ROOT = path.resolve(import.meta.dirname, "..");
const DIST = path.join(ROOT, "dist");
// The AXIOM repository itself — used as the "AXIOM" project in the scenario.
const REPO = path.resolve(ROOT, "..");
// Everything the run creates (core data home, Edge profile, throw-away projects)
// lives under one temp directory so the verification never touches real state.
const TMP = mkdtempSync(path.join(os.tmpdir(), "axiom-e2e-"));
const BRIDGE = spawnable(path.join(ROOT, "src-tauri", "bridge", "axiom_bridge.py"));
const EDGE =
  process.env.EDGE_PATH ??
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 8791;

function spawnable(p) {
  return p;
}

const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": " image/svg+xml",
  ".svg2": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
};
MIME[".svg"] = "image/svg+xml";

if (!existsSync(DIST)) {
  weird("desktop/dist not found — run `npm run build` first");
}
function weird(msg) {
  console.error(msg);
  process.exit(1);
}

// ---------------------------------------------------------- static file server
const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://localhost:${PORT}`);
    // HTTP transport from the page to the real python core (used by the shim).
    if (req.method === "POST" && url.pathname === "/__core") {
      const chunks = [];
      for await (const c of req) chunks.push(c);
      const { cmd, args } = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      try {
        const data = await coreRequest(cmd, args ?? {});
        dbg("core ok", cmd);
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ ok: true, json: JSON.stringify(data ?? null) }));
      } catch (e) {
        dbg("core FAIL", cmd, String(e));
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ ok: false, error: String(e) }));
      }
      return;
    }
    let file = path.join(DIST, url.pathname === "/" ? "index.html" : url.pathname);
    if (!file.startsWith(DIST)) throw new Error("bad path");
    let body = await readFile(file);
    if (file.endsWith("index.html")) {
      // Inject the invoke shim before the app bundle runs.
      body = Buffer.from(
        body.toString("utf8").replace(
          "<head>",
          `<head><script>${shimScript}</script>`,
        ),
      );
    }
    res.writeHead(200, { "content-type": MIME[path.extname(file)] ?? "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));

// The invoke shim is served inside index.html (same origin, no CDP bindings).
// It emulates the parts of the Tauri runtime the frontend actually uses:
//   * `invoke("plugin:event|listen", ...)` registers a handler
//   * `invoke("bridge_request", { payload: { req, cmd, args } })` forwards to
//     the real python core over HTTP, and then *emits* `bridge://line` with the
//     same payload shape the Rust shell broadcasts (reply / event).
const shimScript = `
(function () {
  const listeners = new Map();
  function emit(name, payload) {
    const handler = listeners.get(name);
    if (handler) handler({ event: name, id: 1, payload });
  }
  // Used by the harness to push async core events (streaming, status, done).
  window.__axiomEmit = emit;
  window.__axiomCore = { listeners };
  async function invoke(cmd, invokeArgs) {
    if (cmd === "plugin:event|listen") {
      listeners.set(invokeArgs.event, invokeArgs.handler);
      return 1;
    }
    if (cmd === "plugin:event|unlisten") {
      listeners.delete(invokeArgs.event);
      return null;
    }
    if (cmd === "pick_folder") return window.__axiomPickFolder ?? null;
    if (cmd === "open_url" || cmd === "quit_app" || cmd === "bridge_restart") return null;
    if (cmd === "bridge_request") {
      const p = invokeArgs?.payload ?? {};
      const res = await fetch("/__core", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ cmd: p.cmd, args: p.args ?? {} }),
      });
      const m = await res.json();
      if (m.ok) {
        emit("bridge://line", { type: "reply", req: p.req, ok: true, data: JSON.parse(m.json) });
        return null;
      }
      emit("bridge://line", { type: "reply", req: p.req, ok: false, error: m.error || "bridge error" });
      return null;
    }
    throw new Error("harness shim: unknown command " + cmd);
  }
  Object.defineProperty(window, "__TAURI_INTERNALS__", {
    value: { invoke, transformCallback: (cb) => cb },
    configurable: true,
  });
})();
`;

// ------------------------------------------------------------ python core
// Hermetic run: AXIOM_HOME in a temp dir, so the real ~/.axiom (user chats,
// workspaces.json) is never read or written by the verification run.
const axiomHome = path.join(
  mkdtempSync(path.join(os.tmpdir(), "axiom-e2e-home-")),
  "axiom-home",
);
mkdirSync(axiomHome, { recursive: true });
// A throw-away project used by the "another project" part of the scenario.
const otherProject = path.join(TMP, "OtherProject");
mkdirSync(path.join(otherProject, "src"), { recursive: true });
writeFileSync(path.join(otherProject, "README.md"), "# Other\n", "utf8");
const proc = spawn("python", [BRIDGE], {
  cwd: ROOT,
  env: {
    ...process.env,
    AXIOM_HOME: axiomHome,
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1",
    // W4.15: deterministic coding scenario — the real pipeline with a scripted
    // model instead of a live Ollama, so the run is network-free and repeatable.
    AXIOM_E2E_SCRIPTED_MODEL: "1",
  },
  stdio: ["pipe", "pipe", "pipe"],
});
const pending = new Map();
let lineBuf = "";
let nextReq = 1;
proc.stdout.on("data", (chunk) => {
  lineBuf += chunk.toString("utf8");
  let idx;
  while ((idx = lineBuf.indexOf("\n")) >= 0) {
    bridgeLine(lineBuf.slice(0, idx));
    lineBuf = lineBuf.slice(idx + 1);
  }
});
proc.stderr.on("data", (c) => process.stderr.write("[core] " + c.toString()));
proc.on("exit", (code) => console.log("[harness] core exited", code));

function bridgeLine(line) {
  line = line.trim();
  if (!line) return;
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }
  if (msg.type === "reply" && pending.has(msg.req)) {
    const { resolve, reject } = pending.get(msg.req);
    pending.delete(msg.req);
    if (msg.ok) resolve(msg.data);
    else reject(new Error(msg.error ?? "bridge error"));
    return;
  }
  if (msg.type === "event") {
    // Async core events (streaming deltas, status, done…) must reach the page
    // exactly like the Rust shell forwards them.
    const kind = msg.event?.type ?? msg.event?.kind ?? "event";
    dbg("core event ->", kind);
    void emitToPage("bridge://line", msg);
  }
}

/** Push a `bridge://line` payload into the page's registered listeners. */
async function emitToPage(name, payload) {
  try {
    await evaluate(
      // Guarded: before the shim is installed there is simply nothing to notify.
      `(window.__axiomEmit ?? function () {})(${JSON.stringify(name)}, ${JSON.stringify(payload)})`,
      false,
    );
  } catch (err) {
    dbg("emit failed", String(err));
  }
}

function coreRequest(cmd, args = {}) {
  const req = nextReq++;
  // `send` resolves only when the whole generation finishes; a reasoning model
  // on CPU easily exceeds 30s, so give it a much longer budget.
  const timeoutMs = cmd === "send" ? 600000 : 30000;
  return new Promise((resolve, reject) => {
    pending.set(req, { resolve, reject });
    proc.stdin.write(JSON.stringify({ type: "request", req, cmd, args }) + "\n");
    setTimeout(() => {
      if (pending.has(req)) {
        pending.delete(req);
        reject(new Error(`core timeout: ${cmd}`));
      }
    }, timeoutMs);
  });
}

await coreRequest("health");
await coreRequest("startup");
// Precondition: the app boots with a project already open, exactly like a user
// who restarted AXIOM while working in a repo. AXIOM's own repo is that project.
const bootstrap = await coreRequest("set_workspace", { path: REPO });
dbg("bootstrap workspace:", bootstrap?.name, bootstrap?.path);
// ------------------------------------------------------------------ Edge / CDP
const tmp = mkdtempSync(path.join(os.tmpdir(), "axiom-e2e-"));
const edge = spawn(
  EDGE,
  [
    "--headless=new",
    "--disable-gpu",
    "--remote-debugging-port=9223",
    `--user-data-dir=${path.join(tmp, "profile")}`,
    "--no-first-run",
    "--window-size=1400,900",
    "about:blank",
  ],
  { stdio: "ignore" },
);

async function fetchJson(url) {
  const res = await fetch(url);
  return res.json();
}
let targets = null;
for (let i = 0; i < 50 && !targets; i++) {
  await new Promise((r) => setTimeout(r, 200));
  try {
    targets = await fetchJson("http://127.0.0.1:9223/json/list");
  } catch {}
}
if (!targets) weird("Edge CDP did not start");
const page = targets.find((t) => t.type === "page");

const ws = new globalThis.WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.onopen = resolve;
  ws.onerror = reject;
});
let msgId = 0;
const cdpPending = new Map();
const pageErrors = [];
function onCdpMessage(ev) {
  const data = JSON.parse(ev.data);
  if (data.id && cdpPending.has(data.id)) {
    const { resolve, reject } = cdpPending.get(data.id);
    cdpPending.delete(data.id);
    if (data.error) reject(new Error(data.error.message));
    else resolve(data.result);
    return;
  }
  if (data.method === "Runtime.exceptionThrown") {
    pageErrors.push(data.params.exceptionDetails?.exception?.description ?? "exception");
    return;
  }
  if (data.method === "Runtime.consoleAPICalled") {
    const text = (data.params.args ?? []).map((a) => a.value ?? a.description ?? "").join(" ");
    if (text) console.log("[page]", text);
    return;
  }
  if (data.method === "Runtime.bindingCalled") return;
}
ws.onmessage = onCdpMessage;

function send(method, params = {}) {
  const id = ++msgId;
  return new Promise((resolve, reject) => {
    cdpPending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression, awaitPromise = true) {
  const r = await send("Runtime.evaluate", { expression, awaitPromise, returnByValue: true });
  if (r.exceptionDetails) {
    throw new Error(r.exceptionDetails.exception?.description ?? "page error");
  }
  return r.result.value;
}
await send("Page.enable");
await send("Runtime.enable");
// Desktop viewport. Without an explicit override, headless Edge can report a
// tiny (500x450) viewport, which silently switches the app into its <=760px
// phone layout — not what the user is testing.
const VIEW = { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false };
async function setViewport(width, height) {
  await send("Emulation.setDeviceMetricsOverride", { ...VIEW, width, height });
}
await setViewport(VIEW.width, VIEW.height);
// Navigate to the app (the invoke shim is served inside index.html).
await send("Page.navigate", { url: `http://127.0.0.1:${PORT}/` });

async function waitPhase(timeoutMs = 150000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const phase = await evaluate(
      `document.querySelector(".topbar") ? "ready" : (document.querySelector(".app") ? "dom" : "none")`,
    ).catch(() => "none");
    if (phase === "ready") return true;
    if (DEBUG) {
      const steps = await evaluate(
        `[...document.querySelectorAll(".boot-step")].map((s) => s.className + ":" + s.textContent.trim()).join(" | ")`,
      ).catch(() => "n/a");
      dbg("boot steps:", steps);
    }
    const err = await evaluate(
      `document.querySelector(".boot-error-title")?.textContent ?? null`,
    ).catch(() => null);
    if (err) {
      console.log("[harness] boot error from the app:", err);
      return false;
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  return false;
}
const booted = await waitPhase();
console.log("[harness] booted =", booted, "| url:", page.url);
if (!booted) {
  const snap = await evaluate(
    `({ app: !!document.querySelector(".app"), boot: !!document.querySelector(".boot"), bootText: (document.querySelector(".boot")?.textContent ?? "").replace(/\\s+/g, " ").slice(0, 300) })`,
  ).catch((e) => String(e));
  console.log("[harness] page snapshot:", JSON.stringify(snap, null, 2));
  weird("app did not render in time");
}
console.log("[harness] app rendered in headless Edge (real python core)");

// --------------------------------------------------------------- UI helpers
/** Real mouse click through CDP at the centre of the element's box.
 *  A covered element receives nothing — exactly what the user experiences. */
async function realClick(sel) {
  const box = await evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(sel)});
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  })()`);
  if (!box) throw new Error("realClick: not found: " + sel);
  for (const type of ["mousePressed", "mouseReleased"]) {
    await send("Input.dispatchMouseEvent", {
      type,
      x: box.x,
      y: box.y,
      button: "left",
      clickCount: 1,
      buttons: type === "mousePressed" ? 1 : 0,
    });
  }
  return box;
}

const click = (sel) =>
  evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(sel)});
    if (!el) throw new Error("not found: " + ${JSON.stringify(sel)});
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  })()`, false);

/** Click a button inside the open selector menu with a real mouse click. */
async function clickMenu(text) {
  const box = await evaluate(`(() => {
    const els = [...document.querySelectorAll(".ws-menu button")];
    const el = els.find((b) => b.textContent.trim().includes(${JSON.stringify(text)}));
    if (!el) throw new Error("menu button not found: " + ${JSON.stringify(text)});
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  })()`);
  for (const type of ["mousePressed", "mouseReleased"]) {
    await send("Input.dispatchMouseEvent", {
      type,
      x: box.x,
      y: box.y,
      button: "left",
      clickCount: 1,
      buttons: type === "mousePressed" ? 1 : 0,
    });
  }
}

/** Switch the right-panel tab (Файлы / Терминал / Git) with a real mouse click. */
async function sideTab(label) {
  const box = await evaluate(`(() => {
    const b = [...document.querySelectorAll(".side-tabs button")]
      .find((x) => x.textContent.trim() === ${JSON.stringify(label)});
    if (!b) throw new Error("side tab not found: " + ${JSON.stringify(label)});
    const r = b.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  })()`);
  for (const type of ["mousePressed", "mouseReleased"]) {
    await send("Input.dispatchMouseEvent", {
      type,
      x: box.x,
      y: box.y,
      button: "left",
      clickCount: 1,
      buttons: type === "mousePressed" ? 1 : 0,
    });
  }
  await sleep(260);
}

/** State of the project-dependent panels, read tab by tab. */
async function projectPanels() {
  await sideTab("Терминал");
  const term = await evaluate(`(() => ({
    off: document.querySelector(".term-off")?.textContent ?? null,
    cwd: document.querySelector(".term-cwd")?.textContent ?? null,
    inputDisabled: document.querySelector(".term-input")?.disabled ?? null,
  }))()`);
  await sideTab("Git");
  const git = await evaluate(`(() => ({
    panel: !!document.querySelector(".gitpanel"),
    empty: document.querySelector(".git-empty")?.textContent ?? null,
  }))()`);
  await sideTab("Файлы");
  const files = await evaluate(`(() => ({
    empty: document.querySelector(".ex-empty")?.textContent ?? null,
    root: document.querySelector(".ex-root")?.textContent ?? null,
    nodes: document.querySelectorAll(".ex-node").length,
  }))()`);
  return { term, git, files };
}

const uiState = () =>
  evaluate(`(() => ({
    indicator: document.querySelector(".ws-current .ws-name")?.textContent ?? null,
    indicatorClass: document.querySelector(".ws-current")?.className ?? null,
    globalBadge: !!document.querySelector(".welcome-global"),
    explorerEmpty: document.querySelector(".ex-empty")?.textContent ?? null,
    exNodes: document.querySelectorAll(".ex-node").length,
    gitPanel: !!document.querySelector(".gitpanel"),
    gitEmpty: document.querySelector(".git-empty")?.textContent ?? null,
    termOff: !!document.querySelector(".term-off"),
    termCwd: document.querySelector(".term-cwd")?.textContent ?? null,
    toasts: [...document.querySelectorAll(".toast")].map((t) => t.textContent.trim()),
  }))()`);

/** Open the selector with a real mouse click and read its entries. */
const openMenu = async () => {
  await realClick(".ws-current");
  await sleep(220);
  return await evaluate(
    `[...document.querySelectorAll(".ws-menu button")].map((b) => b.className + " :: " + b.textContent.trim().replace(/\\s+/g, " "))`,
  );
};

/** Hit test every button inside the open menu: is it really the top element? */
const menuHitReport = () =>
  evaluate(`(() => {
    return [...document.querySelectorAll(".ws-menu button")].map((b) => {
      const r = b.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const top = document.elementFromPoint(cx, cy);
      return {
        label: b.textContent.trim().replace(/\\s+/g, " ").slice(0, 28),
        cls: b.className,
        clickable: top ? (top === b || b.contains(top)) : false,
        coveredBy: top && top !== b && !b.contains(top)
          ? top.tagName + "." + (typeof top.className === "string" ? top.className : "")
          : null,
      };
    });
  })()`);

const wsRoot = async () => (await coreRequest("get_config")).workspace_root;
/** Name of the boot project, as the backend reports it (never hardcoded). */
const PROJECT_NAME = path.basename(REPO);
dbg("expected project name:", PROJECT_NAME);

/** Geometry + paint-order dump: why a click on the menu does or does not land. */
const layerReport = () =>
  evaluate(`(() => {
    const info = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return {
        rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
        position: cs.position, zIndex: cs.zIndex, overflow: cs.overflow,
        pointerEvents: cs.pointerEvents, filter: cs.backdropFilter, transform: cs.transform,
      };
    };
    const g = [...document.querySelectorAll(".ws-menu button")].find((b) => b.textContent.includes("Global Chat"));
    let stack = null;
    if (g) {
      const r = g.getBoundingClientRect();
      stack = document.elementsFromPoint(r.left + r.width / 2, r.top + r.height / 2)
        .slice(0, 5)
        .map((e) => e.tagName + "." + (typeof e.className === "string" ? e.className : ""));
    }
    return {
      viewport: [window.innerWidth, window.innerHeight],
      topbar: info(".topbar"),
      menu: info(".ws-menu"),
      selector: info(".ws-selector"),
      workbench: info(".workbench"),
      side: info(".workbench-side"),
      stackAtGlobalChat: stack,
      narrow: window.matchMedia("(max-width: 760px)").matches,
      mid: window.matchMedia("(max-width: 1100px)").matches,
    };
  })()`);

/** Wait until the sidebar panel is actually rendered/open (chat list lives there). */
const ensureSidebar = async () => {
  const open = await evaluate(`!!document.querySelector(".sidebar.open")`);
  if (!open) {
    await click('header .icon-btn[title^="Sidebar"]');
    await sleep(350);
  }
};

/**
 * History must stay separated between Global Chat and the project.
 * A real message is sent in each scope (through the UI composer), so both
 * scopes get persisted conversations that must never leak into each other.
 */
async function chatScopesSeparated() {
  const sendMsg = async (text) => {
    // Never type while a previous turn is still generating: the composer would
    // be disabled and the message silently lost.
    const idleDeadline = Date.now() + 600000;
    while (Date.now() < idleDeadline) {
      const st = await coreRequest("state").catch(() => ({ state: "?" }));
      if (st.state === "idle") break;
      await sleep(1500);
    }
    const pre = await evaluate(`(() => {
      const ta = document.querySelector(".composer textarea");
      return { has: !!ta, disabled: ta?.disabled ?? null, value: ta?.value ?? null };
    })()`, false);
    dbg("composer before send:", JSON.stringify(pre));
    await evaluate(`(() => {
      const ta = document.querySelector(".composer textarea");
      if (!ta) throw new Error("composer textarea not found");
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, "value",
      ).set;
      setter.call(ta, ${JSON.stringify(text)});
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    })()`, false);
    await sleep(120);
    await evaluate(`(() => {
      const ta = document.querySelector(".composer textarea");
      ta.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    })()`, false);
    await sleep(800);
    const stAfter = await coreRequest("state").catch(() => ({ state: "?" }));
    dbg("state right after Enter:", stAfter.state);
    // A conversation is persisted as soon as the user message is recorded, so
    // wait for a new chat id in the scope history (generation may be slow).
    const beforeIds = (await coreRequest("list_chats").catch(() => [])).map((c) => c.id);
    const deadline = Date.now() + 180000;
    while (Date.now() < deadline) {
      await sleep(1500);
      const [st, chats] = await Promise.all([
        coreRequest("state").catch(() => ({ state: "?" })),
        coreRequest("list_chats").catch(() => []),
      ]);
      if (st.state === "idle" && chats.some((c) => !beforeIds.includes(c.id))) break;
    }
    await sleep(500);
  };

  await openMenu();
  await clickMenu("Global Chat");
  await sleep(1500);
  await sendMsg("ping");
  const globalIds = (await coreRequest("list_chats")).map((c) => c.id);

  await openMenu();
  await clickMenu(PROJECT_NAME);
  await sleep(2000);
  await sendMsg("ping");
  const projectIds = (await coreRequest("list_chats")).map((c) => c.id);

  // Back to Global Chat: the global conversation is still there.
  await openMenu();
  await clickMenu("Global Chat");
  await sleep(1500);
  const globalIds2 = (await coreRequest("list_chats")).map((c) => c.id);

  const disjoint = globalIds.every((id) => !projectIds.includes(id)) &&
    projectIds.every((id) => !globalIds.includes(id));
  const persisted = globalIds.every((id) => globalIds2.includes(id));

  await openMenu();
  await clickMenu(PROJECT_NAME);
  await sleep(1800);
  dbg("chat scopes", JSON.stringify({ globalIds, projectIds, globalIds2 }));
  const info = `global=${globalIds.length} project=${projectIds.length} disjoint=${disjoint} persisted=${persisted} root=${await wsRoot()}`;
  const ok = (
    globalIds.length > 0 &&
    projectIds.length > 0 &&
    disjoint &&
    persisted &&
    (await wsRoot()) === REPO
  );
  return { ok, info };
}

/** Real hit test: what element would receive a click at the button's center? */
const hitTest = (sel) =>
  evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(sel)});
    if (!el) return { found: false };
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const top = document.elementFromPoint(cx, cy);
    return {
      found: true, x: Math.round(cx), y: Math.round(cy),
      w: Math.round(r.width), h: Math.round(r.height),
      topIsSelfOrChild: top ? (top === el || el.contains(top)) : false,
      topTag: top ? top.tagName + "." + (typeof top.className === "string" ? top.className : "") : null,
    };
  })()`);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? " — " + detail : ""}`);
}

// =====================================================================
// SCENARIO 1: Global Chat via the project selector
// =====================================================================
console.log("\n=== Scenario 1: Global Chat (project selector) ===");

const boot0 = await uiState();
check("boot: boot project is active", boot0.indicator === PROJECT_NAME, String(boot0.indicator));

// ---------------------------------------------------- AXIOM -> Global Chat
const menuOpen = await openMenu();
check(
  "selector menu opens",
  Array.isArray(menuOpen) && menuOpen.length > 0,
  JSON.stringify((menuOpen ?? []).slice(0, 6)),
);
const globalEntry = (menuOpen ?? []).find((t) => t.includes("Global Chat") && t.startsWith("ws-global"));
check(
  "menu exposes a real 'Global Chat' button (.ws-global)",
  !!globalEntry,
  String(globalEntry),
);
check(
  "Global Chat is not a fake project entry",
  !(menuOpen ?? []).some((t) => t.startsWith("ws-item") && t.includes("Global Chat")),
  JSON.stringify((menuOpen ?? []).filter((t) => t.startsWith("ws-item"))),
);
check("menu has no duplicate Global Chat entries", (menuOpen ?? []).filter((t) => t.includes("Global Chat")).length === 1);

// The menu overflows the top bar — every entry must actually receive the click.
if (DEBUG) console.log("[diag] layers:", JSON.stringify(await layerReport(), null, 1));
const hits = await menuHitReport();
const blocked = (hits ?? []).filter((h) => !h.clickable);
check(
  "every selector entry is clickable (nothing covers the menu)",
  hits.length > 0 && blocked.length === 0,
  blocked.length ? JSON.stringify(blocked.slice(0, 4)) : `${hits.length} entries hit-testable`,
);

await clickMenu("Global Chat");
await sleep(1500);
const stG = await uiState();
const pG = await projectPanels();
check("indicator shows Global Chat (project gone)", stG.indicator === "Global Chat", String(stG.indicator));
check("indicator marked as no-project", /(^|\s)none(\s|$)/.test(stG.indicatorClass ?? ""), String(stG.indicatorClass));
check("chat shows Global Chat badge", stG.globalBadge);
check(
  "explorer: no project root, empty state",
  pG.files.nodes === 0 && !!pG.files.empty && /нет активного проекта/.test(pG.files.root ?? ""),
  `root="${pG.files.root}" empty="${pG.files.empty}" nodes=${pG.files.nodes}`,
);
check(
  "git panel: explicit disabled state",
  !!pG.git.empty && /Git недоступен/.test(pG.git.empty ?? ""),
  `panel=${pG.git.panel} empty="${pG.git.empty}"`,
);
check(
  "terminal: disabled, cwd dropped",
  pG.term.cwd === "—" && !!pG.term.off && pG.term.inputDisabled === true,
  `cwd="${pG.term.cwd}" off="${pG.term.off}" inputDisabled=${pG.term.inputDisabled}`,
);
check("no error toast on switch", !stG.toasts.some((t) => /ошиб|error/i.test(t)), JSON.stringify(stG.toasts));

check("backend workspace_root is null", (await wsRoot()) === null);
const toolsG = await coreRequest("tools");
check("workspace tools unregistered", !toolsG.some((t) => t.name === "read_file"), toolsG.map((t) => t.name).join(","));

// ---------------------------------------------------- Global Chat -> AXIOM
const menuBack = await openMenu();
check(
  "selector still reachable in Global Chat",
  Array.isArray(menuBack) && menuBack.length > 0,
  JSON.stringify((menuBack ?? []).slice(0, 6)),
);
check(
  "Global Chat shown as the active state",
  (menuBack ?? []).some((t) => t.startsWith("ws-item-main") && t.includes("Global Chat")),
  JSON.stringify((menuBack ?? []).filter((t) => t.includes("Global Chat"))),
);
const activeItem = await evaluate(
  `[...document.querySelectorAll(".ws-menu .ws-item")].filter((d) => d.className.includes("active")).map((d) => d.textContent.trim().replace(/\\s+/g, " "))`,
).catch(() => null);
check(
  "active menu row is the Global Chat row",
  Array.isArray(activeItem) && activeItem.some((t) => t.includes("Global Chat")),
  JSON.stringify(activeItem),
);
check(
  "project is offered as a real clickable entry",
  (menuBack ?? []).some((t) => t.startsWith("ws-item-main") && t.includes(PROJECT_NAME)),
  JSON.stringify((menuBack ?? []).filter((t) => t.startsWith("ws-item-main"))),
);
await clickMenu(PROJECT_NAME);
await sleep(2000);
const stB = await uiState();
check("indicator shows the project again", stB.indicator === PROJECT_NAME, String(stB.indicator));
check("global badge gone", !stB.globalBadge);
check("explorer tree restored", stB.exNodes > 0, `nodes=${stB.exNodes}`);
check("backend workspace_root restored", (await wsRoot()) === REPO, String(await wsRoot()));
const toolsB = await coreRequest("tools");
check("workspace tools re-registered", toolsB.some((t) => t.name === "read_file"), toolsB.map((t) => t.name).join(","));

// ------------------------- AXIOM -> Global Chat -> other project -> Global Chat -> AXIOM
await openMenu();
await clickMenu("Global Chat");
await sleep(1200);
check("2nd Global Chat switch works", (await uiState()).indicator === "Global Chat");

// "Открыть проект…" drives the real pick_folder flow (the shim returns OtherProject).
await evaluate(`window.__axiomPickFolder = ${JSON.stringify(otherProject)}`, false);
await openMenu();
await clickMenu("Открыть проект…");
await sleep(2200);
const stO = await uiState();
check("another project opens", stO.indicator === "OtherProject", String(stO.indicator));
check("other project root in backend", (await wsRoot()) === otherProject, String(await wsRoot()));

await openMenu();
await clickMenu("Global Chat");
await sleep(1200);
const stG2 = await uiState();
check("3rd Global Chat switch works", stG2.indicator === "Global Chat", String(stG2.indicator));
check("explorer empty again", stG2.exNodes === 0, `nodes=${stG2.exNodes}`);
check("backend root null again", (await wsRoot()) === null);

await openMenu();
await clickMenu(PROJECT_NAME);
await sleep(2000);
const stB2 = await uiState();
check("project restored after the round trip", stB2.indicator === PROJECT_NAME, String(stB2.indicator));
check("tree restored after the round trip", stB2.exNodes > 0, `nodes=${stB2.exNodes}`);

const scopes = await chatScopesSeparated();
check("history stays separated per workspace", scopes.ok, scopes.info);

// ---------------------------------------------------------------------
// SCENARIO 1b: ✕ removes a project from the list — with confirmation;
// Global Chat switch needs no confirmation at all (already proven above:
// clickMenu("Global Chat") switched immediately several times).
{
  const clickX = (label) =>
    evaluate(`(() => {
      const items = [...document.querySelectorAll(".ws-menu .ws-item")];
      const item = items.find((d) => d.textContent.includes(${JSON.stringify(label)}));
      if (!item) return "no-item";
      const x = [...item.querySelectorAll("button.icon-btn")].find((b) => (b.title || "").includes("списка"));
      if (!x) return "no-x";
      x.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      return "clicked";
    })()`, false);

  await openMenu();
  const first = await clickX("OtherProject");
  await sleep(300);
  const dialog = await evaluate(
    `(() => ({ open: !!document.querySelector(".modal-backdrop .modal"), head: document.querySelector(".modal-head h2")?.textContent ?? null }))()`,
  );
  check("✕ opens the removal confirmation dialog", dialog.open && /Удалить проект/i.test(dialog.head ?? ""), `${first} / ${dialog.head}`);

  // Отказаться keeps the project in the list.
  await evaluate(`document.querySelector(".modal .btn.ghost")?.dispatchEvent(new MouseEvent("click", { bubbles: true }))`, false);
  await sleep(300);
  const kept = await evaluate(`[...document.querySelectorAll(".ws-menu .ws-item")].some((d) => d.textContent.includes("OtherProject"))`);
  check("«Отказаться» keeps the project in the list", kept === true, String(kept));

  // Confirm removes it from the list and from the backend store.
  // NOTE: after «Отказаться» the menu is still open — clicking .ws-current
  // again would *close* it, so go straight for the ✕.
  await clickX("OtherProject");
  await sleep(300);
  await evaluate(
    `[...document.querySelectorAll(".modal .btn.danger")].find((b) => b.textContent.includes("Удалить"))?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))`,
    false,
  );
  await sleep(1200);
  await openMenu();
  const after = await evaluate(
    `[...document.querySelectorAll(".ws-menu .ws-item, .ws-menu")].map((d) => d.textContent.trim().replace(/\\s+/g, " ")).filter((t) => t.includes("OtherProject"))`,
  );
  const recent = (await coreRequest("recent_workspaces")).recent.map((r) => r.name);
  check(
    "confirmed removal drops the project from list and backend",
    after.length === 0 && !recent.includes("OtherProject"),
    `ui=[${after.join(" | ")}] recent=${recent.join(",")}`,
  );
}

// =====================================================================
// SCENARIO 2: right panel toggle with real hit testing
// =====================================================================
console.log("\n=== Scenario 2: right panel toggle ===");

const panelW = () => evaluate(`(() => {
  const el = document.querySelector(".workbench-side");
  if (!el) return -1;
  return Math.round(el.getBoundingClientRect().width);
})()`);

const t1 = await hitTest('header .icon-btn[aria-label=\"Панель показать, скрыть R\"]');
check("toggle button hit-testable (open state)", t1.found && t1.topIsSelfOrChild, JSON.stringify(t1));
check("toggle button has a usable click area", (t1.w ?? 0) >= 28 && (t1.h ?? 0) >= 28, `${t1.w}x${t1.h}`);

await realClick('header .icon-btn[aria-label=\"Панель показать, скрыть R\"]');
await sleep(600);
const wClosed = await panelW();
check("panel width is 0 after a real mouse click", wClosed === 0, String(wClosed));

const closed = await evaluate(`(() => ({
  workbenchClass: document.querySelector(".workbench")?.className ?? "",
  sideVisible: (() => { const el = document.querySelector(".workbench-side"); if (!el) return false;
    const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })(),
  chatW: Math.round(document.querySelector(".workbench-chat")?.getBoundingClientRect().width ?? 0),
  mainW: Math.round(document.querySelector(".main")?.getBoundingClientRect().width ?? 0),
}))()`);
check("panel content not visible when closed", !closed.sideVisible, `w=${wClosed}`);
check("chat expanded over freed space", closed.chatW >= closed.mainW - 60, `chat=${closed.chatW} main=${closed.mainW}`);

const overlayFree = await evaluate(`(() => {
  const chat = document.querySelector(".workbench-chat");
  if (!chat) return false;
  const r = chat.getBoundingClientRect();
  const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return !top || chat.contains(top) || top === chat;
})()`);
check("no invisible layer blocks the chat when closed", overlayFree);

const t2 = await hitTest('header .icon-btn[aria-label=\"Панель показать, скрыть R\"]');
check("reopen button hit-testable when closed", t2.found && t2.topIsSelfOrChild, JSON.stringify(t2));

await realClick('header .icon-btn[aria-label=\"Панель показать, скрыть R\"]');
await sleep(600);
check("panel reopened (width > 300)", (await panelW()) > 300, String(await panelW()));

await realClick('header .icon-btn[aria-label=\"Панель показать, скрыть R\"]');
await sleep(600);
check("2nd close works", (await panelW()) === 0);
await realClick('header .icon-btn[aria-label=\"Панель показать, скрыть R\"]');
await sleep(600);
check("2nd reopen works", (await panelW()) > 300);

if (pageErrors.length) {
  check("no uncaught page errors", false, pageErrors.slice(0, 3).join(" | "));
} else {
  check("no uncaught page errors", true);
}

// =====================================================================
// SCENARIO 3: a real coding task end-to-end (scripted model, no network)
// =====================================================================
console.log("\n=== Scenario 3: real coding task (scripted model) ===");

// A clean, throw-away project with a genuinely failing test: the agent must
// read, edit, and run a real pytest, and the harness verifies the file on disk.
const codingProject = path.join(TMP, "CodingProject");
mkdirSync(codingProject, { recursive: true });
writeFileSync(path.join(codingProject, "buggy.py"), "def add(a, b):\n    return a - b\n", "utf8");
writeFileSync(
  path.join(codingProject, "test_buggy.py"),
  "from buggy import add\ndef test_add():\n    assert add(2, 3) == 5\n",
  "utf8",
);
spawnSync("git", ["init", codingProject], { stdio: "ignore" });

await coreRequest("set_workspace", { path: codingProject });
await sleep(400);
const codingRoot = await wsRoot();
check(
  "coding project opens in backend",
  codingRoot !== null && path.resolve(codingRoot) === path.resolve(codingProject),
  String(codingRoot),
);

// The same bridge command the UI task creator triggers; the scripted model
// (installed because AXIOM_E2E_SCRIPTED_MODEL=1) keeps it deterministic and
// network-free while every file/edit/check/diff stays real.
const task = await coreRequest("task_start", { goal: "Fix buggy.py" });
check("task reaches completed state", task?.state === "completed", JSON.stringify(task?.state));
check(
  "task records the changed file",
  Array.isArray(task?.changed_files) && task.changed_files.includes("buggy.py"),
  JSON.stringify(task?.changed_files),
);
check(
  "task captures a real per-file diff",
  !!task?.diffs && typeof task.diffs === "object" && "buggy.py" in task.diffs,
  JSON.stringify(Object.keys(task?.diffs ?? {})),
);
check(
  "task failed once, repaired, then passed (fail→repair)",
  Array.isArray(task?.tests) && task.tests.length === 2 &&
    task.tests[0].ok === false && task.tests[0].executed === true &&
    task.tests[1].ok === true && task.tests[1].executed === true &&
    /1 passed/.test(JSON.stringify(task.tests[1])),
  JSON.stringify(task.tests),
);

const fixedOnDisk = readFileSync(path.join(codingProject, "buggy.py"), "utf8");
check("buggy.py was really fixed on disk", fixedOnDisk.includes("return a + b"), JSON.stringify(fixedOnDisk));

// The UI reflects the same real task: open the Tasks tab and read its state.
await click(".side-tabs button:last-child");
await sleep(700);
const taskUi = await evaluate(`(() => ({
  panel: !!document.querySelector(".task-panel"),
  badge: document.querySelector(".task-status-badge")?.textContent?.trim() ?? null,
}))()`);
check("tasks panel renders the completed task", taskUi.panel && /Завершена/.test(taskUi.badge ?? ""), JSON.stringify(taskUi));

// ------------------------------------------------------------------ summary
const failed = results.filter((r) => !r.ok);
console.log(`\n=== ${results.length - failed.length}/${results.length} checks passed ===`);
for (const f of failed) console.log("FAILED:", f.name, "—", f.detail);

ws.close();
edge.kill();
proc.kill();
server.close();
process.exit(failed.length ? 1 : 0);
