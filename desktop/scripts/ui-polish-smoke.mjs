/** Isolated production UI smoke test. Mock IPC, real React/CSS + Edge/CDP.
 * Run after npm run build. No Ollama, user config, or new dependencies.
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFile, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const dist = path.resolve(import.meta.dirname, "../dist");
const tmp = await mkdtemp(path.join(os.tmpdir(), "axiom-polish-"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const shim = `(() => {
  const listeners = new Map();
  window.__audioStarts = 0;
  const start = OscillatorNode.prototype.start;
  OscillatorNode.prototype.start = function(...args) { window.__audioStarts++; return start.apply(this, args); };
  const model = { name: 'test', displayName: 'Test model', sizeGb: 1, sizeBytes: 1024,
    parameterSize: '1B', quantization: 'Q4', family: 'test', capabilities: ['tools'],
    contextLength: 8192, numCtx: null, loaded: true, providerId: 'ollama' };
  const config = { ollama_url: 'http://localhost:11434', model: 'test', think: null,
    thinking_mode: 'auto', keep_alive: '5m', warmup_model: false, num_ctx: null, num_predict: null,
    context_messages: 20, web_search_enabled: true, workspace_tools_enabled: true, workspace_root: null,
    access_mode: 'workspace', terminal_enabled: true, search_provider: 'auto', search_max_sources: 5,
    search_read_sources: 3, search_timeout: 10, history_limit: 100, show_reasoning: true,
    reasoning_expanded: false, theme: 'obsidian', accent: 'garnet', panel_hover: true, animations: true,
    save_history: true, temperature: null, system_prompt: null, density: 'comfortable', font_size: 14,
    sidebar_open: true, sidebar_width: 268, render_markdown: true, auto_scroll: true, show_metrics: true,
    show_context: true, permission_mode: 'ask', router_enabled: false, router_budget: 'balanced',
    router_primary: null, router_fallbacks: [] };
  window.__patches = [];
  window.__calls = [];
  function data(cmd, args) {
    window.__calls.push({cmd, args});
    switch(cmd) {
      case 'health': return { available: true, version: 'test', url: config.ollama_url };
      case 'get_config': return config;
      case 'set_config': window.__patches.push(args.patch); Object.assign(config, args.patch); return config;
      case 'models': return [model];
      case 'set_model': case 'model_info': return model;
      case 'workspace_info': return { current: null };
      case 'recent_workspaces': return { recent: [] };
      case 'pinned_workspaces': return { pinned: [] };
      case 'workspace_tree': return { tree: [] };
      case 'workspace_files': return { files: [] };
      case 'git_panel': return { project: null, status: null, log: null };
      case 'profiles': return { active: '', items: [] };
      case 'trajectory': return { lines: [] };
      case 'warmup': return { warmed: false, pending: false };
      case 'discover_plugins': return { discovered: [], plugins: [{ name: 'Example', version: '1.0', enabled: false,
        description: 'Local plugin', author: 'AXIOM', capabilities: [], tools: [], skills: [], readme: 'Documentation\\nLocal plugin instructions.' }] };
      case 'providers': return [{id:'openai_compatible',label:'OpenAI Compatible',base_url:'http://localhost:8000/v1',configured:true,status:'ready'}];
      case 'provider_discover': return [{id:'test-route',provider_id:'openai_compatible',model:'test-route',label:'Test route',capabilities:['tools']}];
      default: return [];
    }
  }
  window.__TAURI_INTERNALS__ = { transformCallback: (cb) => cb, invoke: async (cmd, args) => {
    if (cmd === 'plugin:event|listen') { listeners.set(args.event, args.handler); return 1; }
    if (cmd === 'plugin:event|unlisten') return;
    if (cmd === 'bridge_request') {
      const p = args.payload;
      queueMicrotask(() => listeners.get('bridge://line')?.({ payload: {
        type: 'reply', req: p.req, ok: true, data: data(p.cmd, p.args || {})
      }}));
    }
  }};
})();`;
const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://localhost");
    const file = path.resolve(dist, "." + (url.pathname === "/" ? "/index.html" : url.pathname));
    if (!file.startsWith(dist + path.sep)) throw Error("path");
    let body = await readFile(file);
    if (file.endsWith(".html")) body = Buffer.from(body.toString().replace("<head>", `<head><script>${shim}</script>`));
    const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" };
    res.writeHead(200, { "content-type": mime[path.extname(file)] || "application/octet-stream" });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const edge = spawn(process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${tmp}`, "--no-first-run", "about:blank"], { stdio: "ignore" });
let ws;
try {
  let port;
  for (let i = 0; i < 60 && !port; i++) {
    await sleep(100);
    try { port = (await readFile(path.join(tmp, "DevToolsActivePort"), "utf8")).split("\n")[0]; } catch {}
  }
  assert.ok(port, "Edge started");
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  const pending = new Map();
  const errors = [];
  let id = 0;
  ws.onmessage = ({ data }) => {
    const m = JSON.parse(data);
    if (m.id) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(m.error) : p.resolve(m.result); }
    if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    pending.set(++id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw Error(r.exceptionDetails.exception?.description || "page error");
    return r.result.value;
  };
  const click = async (selector) => {
    const p = await evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); e.scrollIntoView({block:'nearest'}); const r = e.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`);
    for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, ...p, button: "left", clickCount: 1 });
    await sleep(280);
  };
  const check = (name, ok) => { assert.ok(ok, name); console.log("PASS", name); };
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: `http://127.0.0.1:${server.address().port}/` });
  for (let i = 0; i < 80; i++) { if (await evaluate("!!document.querySelector('.topbar')")) break; await sleep(100); }
  check("app booted with isolated IPC", await evaluate("!!document.querySelector('.topbar')"));
  check("boot is silent", await evaluate("window.__audioStarts === 0"));
  await click('.side-action[title^="Настройки"]');
  check("settings has a separate navigation/content grid", await evaluate("getComputedStyle(document.querySelector('.axiom-settings-workspace')).display === 'grid'"));
  check("all eleven sections remain", await evaluate("document.querySelectorAll('.settings-nav-item').length === 11"));
  check("compact Settings header", await evaluate("document.querySelector('.axiom-settings-head').getBoundingClientRect().height <= 56"));
  check("compact section heading", await evaluate("parseFloat(getComputedStyle(document.querySelector('.settings-section-title h3')).fontSize) <= 16"));
  await click('[data-section="appearance"]');
  check("sound defaults off", await evaluate(`document.querySelector('[aria-label="Тихие UI-звуки"]').getAttribute('aria-checked') === 'false'`));
  await click('[aria-label="Тихие UI-звуки"]');
  check("frontend preference persisted", await evaluate("localStorage.getItem('axiom.soundEnabled') === 'true' && window.__patches.length === 0"));
  await click('[data-section="general"]');
  check("trusted action can play a quiet cue", await evaluate("window.__audioStarts > 0"));
  await click('[data-section="appearance"]');
  await click('[aria-label="Тихие UI-звуки"]');
  const count = await evaluate("window.__audioStarts");
  await click('[data-section="general"]');
  check("mute stops future cues", await evaluate(`window.__audioStarts === ${count}`));
  await click('[data-section="plugins"]');
  for (let i = 0; i < 20; i++) {
    if (await evaluate("!!document.querySelector('.plugin-card')")) break;
    await sleep(50);
  }
  check("plugin documentation starts collapsed", await evaluate("document.querySelector('.plugin-disclosure').getBoundingClientRect().height === 0"));
  await click('.plugin-card-title button');
  check("plugin documentation expands", await evaluate("document.querySelector('.plugin-disclosure').getBoundingClientRect().height > 30"));
  await click('.plugin-card-title button');
  check("plugin documentation collapses without residual space", await evaluate("document.querySelector('.plugin-disclosure').getBoundingClientRect().height === 0"));
  await click('.plugin-card .switch');
  check("enable requires trust and no action sent yet", await evaluate("!!document.querySelector('.settings-confirm') && !window.__calls.some(c=>c.cmd==='toggle_plugin')"));
  await send('Input.dispatchKeyEvent', {type:'keyDown', key:'Escape', code:'Escape', windowsVirtualKeyCode:27});
  await sleep(80);
  check("Escape dismisses only nested confirmation", await evaluate("!document.querySelector('.settings-confirm') && !!document.querySelector('.axiom-settings')"));
  await click('.plugin-card-actions .danger');
  check("delete confirmation is explicit", await evaluate("document.querySelector('.settings-confirm').textContent.includes('Удалить плагин?')"));
  await click('.settings-confirm .modal-foot .ghost');
  check("cancel does not remove a plugin", await evaluate("!window.__calls.some(c=>c.cmd==='remove_plugin')"));
  await click('.plugin-settings > .settings-section-head .primary');
  check("folder install keeps security warning", await evaluate("document.querySelector('.settings-confirm').textContent.includes('AXIOM не изолирует')"));
  await click('.settings-confirm .modal-foot .ghost');
  await click('[data-section="providers"]');
  check("provider fields and status visible", await evaluate("document.querySelectorAll('.settings-field').length===4 && document.querySelector('.provider-summary').textContent.includes('localhost:8000')"));
  await click('.settings-card-foot .primary');
  check("provider save uses existing handler", await evaluate("window.__calls.some(c=>c.cmd==='provider_test') && window.__calls.some(c=>c.cmd==='provider_discover')"));
  check("provider groups are flat, not nested cards", await evaluate("getComputedStyle(document.querySelector('.settings-card')).backgroundColor==='rgba(0, 0, 0, 0)'"));
  check("provider form fits desktop content area", await evaluate("document.querySelector('.settings-main').scrollHeight <= document.querySelector('.settings-main').clientHeight + 1"));
  const providerShot = await send('Page.captureScreenshot');
  await writeFile(path.join(tmp, 'providers.png'), Buffer.from(providerShot.data,'base64'));
  for (const section of ['general','appearance','models','memory','knowledge','chat','tools','shortcuts','about']) {
    await click(`[data-section="${section}"]`);
    check(`section ${section} renders`, await evaluate("!!document.querySelector('.settings-content').textContent.trim()"));
  }
  await click('[data-section="general"]');
  const initialHistory = await evaluate("document.querySelector('[aria-label=\"Сохранять историю\"]').getAttribute('aria-checked')");
  await click('[aria-label="Сохранять историю"]');
  await click('.axiom-settings-foot > .btn.ghost:not(.settings-restart)');
  check("cancel sends no config patch", await evaluate("window.__patches.length===0"));
  await click('.side-action[title^="Настройки"]');
  check("cancel discards draft", await evaluate(`document.querySelector('[aria-label="Сохранять историю"]').getAttribute('aria-checked')===${JSON.stringify(initialHistory)}`));
  await click('[aria-label="Сохранять историю"]');
  await click('.settings-save');
  check("save sends unchanged config contract", await evaluate("window.__patches.length===1 && window.__patches[0].save_history===false && !('soundEnabled' in window.__patches[0])"));
  await click('.side-action[title^="Настройки"]');
  await evaluate("document.querySelector('.settings-save').focus()");
  await send('Input.dispatchKeyEvent', {type:'keyDown', key:'Tab', code:'Tab', windowsVirtualKeyCode:9});
  check("Tab wraps inside Settings", await evaluate("document.activeElement.getAttribute('aria-label')==='Закрыть настройки'"));
  await evaluate("document.querySelector('.axiom-settings-head .icon-btn').click()");
  await sleep(30);
  check("settings exit retained and inert", await evaluate("!!document.querySelector('.presence[data-state=closed][inert] .modal')"));
  await sleep(250);
  check("settings unmounted after exit", await evaluate("!document.querySelector('.modal')"));
  await click('.model-btn');
  check("model menu opens", await evaluate("!!document.querySelector('.model-menu')"));
  await click('.model-btn');
  check("model menu closes", await evaluate("!document.querySelector('.model-menu')"));
  await click('.ws-current');
  check("project menu above workbench", await evaluate(`(() => { const e=document.querySelector('.ws-open'),r=e.getBoundingClientRect(); return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)); })()`));
  await click('.ws-current');
  const width = await evaluate("document.querySelector('.workbench-side').getBoundingClientRect().width");
  await click('.topbar .icon-btn[aria-label$=" R"]');
  check("right panel collapsed and inert", await evaluate("document.querySelector('.workbench-side').inert && document.querySelector('.workbench-side').getBoundingClientRect().width === 0"));
  await click('.topbar .icon-btn[aria-label$=" R"]');
  check("right panel width restored", await evaluate(`document.querySelector('.workbench-side').getBoundingClientRect().width === ${width}`));
  const handle = await evaluate("(() => { const r=document.querySelector('.side-resizer').getBoundingClientRect(); return {x:r.x+2,y:r.y+100}; })()");
  await send('Input.dispatchMouseEvent', {type:'mousePressed', ...handle, button:'left', clickCount:1});
  await send('Input.dispatchMouseEvent', {type:'mouseMoved', x:950, y:handle.y, buttons:1});
  await sleep(60);
  check("drag tracks pointer without interpolation", await evaluate("document.querySelector('.workbench-side').getBoundingClientRect().width === 450"));
  await send('Input.dispatchMouseEvent', {type:'mouseReleased', x:950, y:handle.y, button:'left', clickCount:1});
  check("drag width persisted", await evaluate("localStorage.getItem('axiom.rightPanelWidth') === '450'"));
  await evaluate("document.body.classList.add('resizing'); document.documentElement.classList.add('theme-anim')");
  check("resize has no lag even during theme fade", await evaluate("getComputedStyle(document.querySelector('.workbench-side')).transitionDuration === '0s'"));
  await evaluate("document.body.classList.remove('resizing'); document.documentElement.classList.remove('theme-anim')");
  for (const theme of ['obsidian', 'light', 'midnight', 'terminal', 'solarized']) {
    await evaluate(`document.documentElement.dataset.theme = '${theme}'`);
    check(`theme ${theme} has semantic surfaces`, await evaluate("getComputedStyle(document.body).backgroundColor !== 'rgba(0, 0, 0, 0)'"));
  }
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await click('.side-action[title^="Настройки"]');
  check("reduced motion disables modal animation", await evaluate("parseFloat(getComputedStyle(document.querySelector('.modal')).animationDuration) < 0.001"));
  await send("Emulation.setEmulatedMedia", { features: [] });
  await evaluate("document.documentElement.classList.add('no-anim', 'theme-anim')");
  check("animations toggle wins over theme transitions", await evaluate("parseFloat(getComputedStyle(document.querySelector('.modal')).transitionDuration) < 0.001"));
  await evaluate("document.documentElement.dataset.theme='obsidian'; document.documentElement.classList.remove('no-anim','theme-anim')");
  await click('[data-section="plugins"]');
  check("no runtime exceptions", errors.length === 0);
  const screenshot = await send("Page.captureScreenshot");
  await writeFile(path.join(tmp, "plugins.png"), Buffer.from(screenshot.data, "base64"));
  console.log("Screenshot:", path.join(tmp, "plugins.png"));
  for (const width of [800, 600]) {
    await send('Emulation.setDeviceMetricsOverride', {width, height:700, deviceScaleFactor:1, mobile:false});
    await click('[data-section="providers"]');
    check(`Settings fits ${width}px window`, await evaluate("(() => { const r=document.querySelector('.axiom-settings').getBoundingClientRect(); const m=document.querySelector('.settings-main'); return r.left>=0 && r.right<=innerWidth && m.scrollWidth<=m.clientWidth+1; })()"));
    check(`footer reachable at ${width}px`, await evaluate("document.querySelector('.settings-save').getBoundingClientRect().bottom<=innerHeight"));
  }
  await evaluate("document.documentElement.dataset.theme='light'");
  const lightShot = await send('Page.captureScreenshot');
  await writeFile(path.join(tmp, 'compact-light.png'), Buffer.from(lightShot.data,'base64'));
} finally {
  ws?.close();
  edge.kill();
  server.closeAllConnections();
  server.close();
}