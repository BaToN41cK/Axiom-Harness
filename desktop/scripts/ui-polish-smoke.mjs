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
  let task = JSON.parse(sessionStorage.getItem('smoke.task') || 'null');
  const plan = {steps:[
    {id:'inspect',goal:'Изучить проект',tools:[],done_when:'Контекст собран',state:'pending',result:''},
    {id:'fix',goal:'Исправить ошибку',tools:[],done_when:'Проверка пройдена',state:'pending',result:''}
  ],definition_of_done:['Проверка пройдена']};
  const publish = (state, kind) => {
    task.state = state; task.revision++; task.updated_at = Date.now()/1000;
    sessionStorage.setItem('smoke.task', JSON.stringify(task));
    listeners.get('bridge://line')?.({payload:{type:'event',event:{type:'task',kind,task_id:task.id,timestamp:Date.now()/1000,task:structuredClone(task)}}});
  };
  window.__resetReview = () => { task.review_status='pending'; publish(task.state, 'task.state'); };
  window.__reviewRecoveryFixture = () => {
    task.review_status='pending'; task.review_recovery='recovery_required';
    task.review_recovery_detail='Reject failed; manual recovery required for: src/example.ts: target changed externally';
    task.review_recovery_paths=['src/example.ts'];
    publish(task.state, 'task.state');
  };
  window.__reviewFixture = () => {
    task.diffs['src/second.ts'] = ['@@ -1 +1 @@', '-old', '+new', '@@ -9 +9 @@', '-last', '+updated'].join(String.fromCharCode(10));
    publish(task.state, 'task.state');
  };
  window.__finishTask = () => {
    task.plan.steps[1].state='completed'; task.plan.steps[1].result='Изменения проверены';
    task.tests=[{ok:true,executed:true,summary:'2 passed'}];
    publish('completed','task.completed');
  };
  function data(cmd, args) {
    window.__calls.push({cmd, args});
    switch(cmd) {
      case 'tasks': return task ? [task] : [];
      case 'task_plan': return structuredClone(plan);
      case 'task_launch':
        task={id:'smoke-task',goal:args.goal,state:'executing',scope:'C:/smoke-project',plan:structuredClone(args.plan),plan_history:[],
          changed_files:['src/example.ts'],errors:[],tests:[],pending_tool:null,active_processes:[],commands:[],
          file_baselines:{},unknown_baselines:[],review_status:'pending',detail:'Выполняется второй шаг',
          diffs:{'src/example.ts':'--- a/src/example.ts\\n+++ b/src/example.ts\\n@@ -1,2 +1,3 @@\\n const a = 1;\\n-const b = 2;\\n+const b = 3;\\n+const c = 4;\\n'},
          context_report:{categories:{system:120,project:40,files:860,tool_results:0,conversation:0},
            budgets:{system:4000,project:2000,files:24000,tool_results:6000,conversation:16000},over_budget:[]},
          created_at:Date.now()/1000,updated_at:Date.now()/1000,revision:1,replans:0,planning:true};
        task.plan.steps[0].state='completed'; task.plan.steps[0].result='Контекст собран'; task.plan.steps[1].state='running';
        publish('executing','task.started'); return structuredClone(task);
      case 'task_cancel': publish('cancelled','task.cancelled'); return {cancelled:true};
      case 'task_continue': publish('executing','task.resumed'); return structuredClone(task);
      case 'task_delete': task=null; sessionStorage.removeItem('smoke.task'); return {deleted:true};
      case 'task_review': task.review_status = args.decision === 'accept' ? 'accepted' : 'rejected'; publish(task.state,'task.reviewed'); return structuredClone(task);
      case 'task_recover_review': task.review_recovery=null; task.review_recovery_detail=null; task.review_recovery_paths=[]; publish(task.state,'task.review'); return structuredClone(task);
      case 'health': return { available: true, version: 'test', url: config.ollama_url };
      case 'get_config': return config;
      case 'set_config': window.__patches.push(args.patch); Object.assign(config, args.patch); return config;
      case 'models': return [model];
      case 'set_model': case 'model_info': return model;
      case 'workspace_info': return { current: { path: 'C:/smoke-project', name: 'smoke-project', kind: 'node', git: false, branch: null, entries: [] } };
      case 'recent_workspaces': return { recent: [] };
      case 'pinned_workspaces': return { pinned: [] };
      case 'workspace_tree': return { tree: [] };
      case 'workspace_file': return { ok: true, content: 'const b = 3;' };
      case 'workspace_files': return { files: ['src/App.tsx', 'src/main.tsx'] };
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
    res.writeHead(200, { "content-type": mime[path.extname(file)] ? `${mime[path.extname(file)]}; charset=utf-8` : "application/octet-stream" });
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
  check("chat is visible after boot", await evaluate("!!document.querySelector('.chat-scroll')"));
  await evaluate("document.querySelector('.composer textarea').focus()");
  await send('Input.insertText', { text: '@src/App.tsx' });
  await sleep(120);
  check("real @file appears as a removable chip", await evaluate("document.querySelector('.file-chip')?.textContent.includes('src/App.tsx') === true"));
  await click('.file-chip');
  check("removing chip removes prompt mention", await evaluate("!document.querySelector('.file-chip') && !document.querySelector('.composer textarea').value.includes('@src/App.tsx')"));
  await evaluate("document.querySelector('.composer textarea').focus()");
  await send('Input.insertText', { text: '/' });
  await sleep(80);
  check("command palette shows shared shortcut metadata", await evaluate("Array.from(document.querySelectorAll('.palette-shortcut')).some((node) => node.textContent === 'Ctrl+,')"));
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
  await sleep(250);
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
  const minHandle = await evaluate("(() => { const r=document.querySelector('.side-resizer').getBoundingClientRect(); return {x:r.x+2,y:r.y+100}; })()");
  await send('Input.dispatchMouseEvent', {type:'mousePressed', ...minHandle, button:'left', clickCount:1});
  await send('Input.dispatchMouseEvent', {type:'mouseMoved', x:1398, y:minHandle.y, buttons:1});
  await send('Input.dispatchMouseEvent', {type:'mouseReleased', x:1398, y:minHandle.y, button:'left', clickCount:1});
  await sleep(300);
  check('panel minimum is 360px', await evaluate("document.querySelector('.workbench-side').getBoundingClientRect().width===360"));
  check('all four tabs remain inside panel', await evaluate("(() => {const r=document.querySelector('.workbench-side').getBoundingClientRect();return [...document.querySelectorAll('.side-tabs button')].every(b=>b.getBoundingClientRect().right<=r.right);})()"));
  await click('.side-tabs button:last-child');
  check('task buttons fit minimum panel width', await evaluate("(() => {const r=document.querySelector('.workbench-side').getBoundingClientRect();return [...document.querySelectorAll('.task-creator-actions button')].every(b=>b.getBoundingClientRect().right<=r.right);})()"));
  await evaluate("(() => {const e=document.querySelector('.task-goal-input');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(e,'Исправить ошибку');e.dispatchEvent(new Event('input',{bubbles:true}));})()");
  await sleep(50);
  await click('.task-creator-actions .primary');
  check('execution opens in main chat area', await evaluate("!!document.querySelector('.workbench-chat .task-execution') && !!document.querySelector('.task-summary')"));
  check('real completed steps determine progress', await evaluate("document.querySelector('.task-execution-title-row strong').textContent==='50%'"));
  await click('.task-execution-stop');
  check('stop offers resume', await evaluate("!!document.querySelector('.task-resume') && !document.querySelector('.task-execution-now')"));
  check('interrupted writes require acknowledgement', await evaluate("document.querySelector('.task-resume button').disabled"));
  await send('Page.reload');
  for(let i=0;i<80;i++){if(await evaluate("!!document.querySelector('.topbar')")) break;await sleep(100);}
  await click('.side-tabs button:last-child');
  await click('.task-summary');
  check('saved stopped task can be opened after reload', await evaluate("!!document.querySelector('.task-resume')"));
  await click('.task-resume input');
  await click('.task-resume button');
  check('resume uses same task id and explicit acknowledgement', await evaluate("window.__calls.some(c=>c.cmd==='task_continue' && c.args.id==='smoke-task' && c.args.acknowledge===true)"));
  check('resume keeps completed work', await evaluate("document.querySelector('.task-execution-title-row strong').textContent==='50%' && !!document.querySelector('.task-execution-now')"));
  const taskShot = await send('Page.captureScreenshot');
  await writeFile(path.join(tmp, 'task-execution.png'), Buffer.from(taskShot.data,'base64'));
  await evaluate('window.__finishTask()'); await sleep(80);
  check('completed result stays in central screen', await evaluate("!!document.querySelector('.task-execution-done') && document.querySelector('.task-execution-title-row strong').textContent==='100%'"));
  check('changed-file diff is shown with real +/- counts', await evaluate("(() => { const s=document.querySelector('.diff-files button'); return !!s && s.textContent.includes('src/example.ts') && s.textContent.includes('+2') && s.textContent.includes('−1'); })()"));
  check('diff uses real old/new line numbers', await evaluate("[...document.querySelectorAll('.diff-line.add .diff-number:last-of-type')].length === 0 && document.querySelector('.diff-line.del .diff-number').textContent === '2' && document.querySelector('.diff-line.add .diff-number:nth-child(2)').textContent === '2'"));
  check('diff has line-level additions and deletions', await evaluate("document.querySelectorAll('.diff-line.add').length === 2 && document.querySelectorAll('.diff-line.del').length === 1 && document.querySelectorAll('.diff-line.context').length === 1"));
  check('diff highlights TypeScript tokens without changing source', await evaluate("document.querySelector('.diff-line.add .hljs-keyword')?.textContent === 'const' && document.querySelector('.diff-line.add code').textContent === 'const b = 3;'"));
  check('syntax tokens do not replace green/red row semantics', await evaluate("getComputedStyle(document.querySelector('.diff-line.add')).backgroundColor !== getComputedStyle(document.querySelector('.diff-line.del')).backgroundColor && document.querySelector('.diff-line.add .diff-sign').textContent === '+'"));
  await click('.diff-hunk summary');
  check('diff hunk collapses', await evaluate("!document.querySelector('.diff-hunk').open"));
  await click('.diff-hunk summary');
  check('diff preserves indentation without wrapping', await evaluate("getComputedStyle(document.querySelector('.diff-line code')).whiteSpace === 'pre'"));
  await evaluate("Object.defineProperty(navigator, 'clipboard', {configurable:true,value:{writeText:async(text)=>{window.__copiedDiff=text;}}})");
  await click('.diff-file button[aria-label="Скопировать diff"]');
  check('copy uses original diff and reports success', await evaluate("window.__copiedDiff.includes('@@ -1,2 +1,3 @@') && document.querySelector('.diff-feedback').textContent.includes('скопирован')"));
  await click('.diff-file button[aria-label^="Открыть"]');
  check('review opens real workspace file and selects Explorer', await evaluate("window.__calls.some(c=>c.cmd==='workspace_file' && c.args.path==='src/example.ts') && !!document.querySelector('.explorer') && document.querySelector('.side-tabs button:first-child').classList.contains('active')"));
  check('Explorer retains shared TypeScript highlighting', await evaluate("document.querySelector('.ex-file .hljs-keyword')?.textContent === 'const'"));
  await click('.side-tabs button:last-child');
  check('fixture Cyrillic remains readable', await evaluate("document.querySelector('.task-execution-title-row p').textContent === 'Выполняется второй шаг'"));
  await evaluate("document.querySelector('.diff-scroll').scrollIntoView({block:'center'})");
  const diffShot = await send('Page.captureScreenshot');
  await writeFile(path.join(tmp, 'diff-review.png'), Buffer.from(diffShot.data,'base64'));
  await evaluate('window.__reviewFixture()'); await sleep(100);
  await click('.diff-review button[aria-label="Следующий файл"]');
  check('changed-file navigation selects only one file', await evaluate("document.querySelector('.diff-files [aria-current]').textContent.includes('second.ts') && document.querySelectorAll('.diff-file').length === 1"));
  await click('.diff-review button[aria-label="Следующий фрагмент"]');
  check('hunk navigation transfers keyboard focus', await evaluate("document.activeElement.matches('.diff-hunk summary') && document.activeElement.textContent.includes('-9 +9')"));
  await evaluate("Object.defineProperty(navigator, 'clipboard', {configurable:true,value:{writeText:async()=>{throw Error('denied');}}})");
  await click('.diff-file button[aria-label="Скопировать diff"]');
  check('clipboard refusal has visible feedback', await evaluate("document.querySelector('.diff-feedback').textContent.includes('Не удалось')"));
  for (const width of [800, 600]) {
    await send('Emulation.setDeviceMetricsOverride', {width, height:700, deviceScaleFactor:1, mobile:false});
    await sleep(350);
    check(`diff stays inside ${width}px workspace`, await evaluate("(() => {const r=document.querySelector('.diff-review').getBoundingClientRect(); const p=document.querySelector('.task-execution-scroll'); return r.right<=innerWidth && p.scrollWidth<=p.clientWidth+1;})()"));
  }
  await send('Emulation.setDeviceMetricsOverride', {width:1400, height:900, deviceScaleFactor:1, mobile:false});
  check('context category budgets are shown', await evaluate("document.querySelectorAll('.task-execution-budget').length >= 4 && document.querySelector('.task-execution-budget-num').textContent.includes('/')"));
  check('completed diff offers review actions', await evaluate("!!document.querySelector('.task-execution-review .primary') && !!document.querySelector('.task-execution-review .danger')"));
  await click('.task-execution-review .danger');
  check('reject explains destructive restore before IPC', await evaluate("!!document.querySelector('.task-review-confirm') && document.querySelector('.task-review-confirm').textContent.includes('восстановит') && !window.__calls.some(c=>c.cmd==='task_review' && c.args.decision==='reject')"));
  await click('.task-review-confirm .ghost');
  check('reject confirmation can be cancelled', await evaluate("!document.querySelector('.task-review-confirm')"));
  check('cancel restores keyboard focus', await evaluate("document.activeElement.matches('.task-execution-review .danger')"));
  await click('.task-execution-review .primary');
  check('review uses existing task_review with same id', await evaluate("window.__calls.some(c=>c.cmd==='task_review' && c.args.id==='smoke-task' && c.args.decision==='accept')"));
  check('accepted review is reflected in the central screen', await evaluate("!!document.querySelector('.task-execution-review-state.accepted') && document.querySelector('.task-execution-done').textContent.includes('приняты')"));
  await evaluate('window.__resetReview()'); await sleep(100);
  await click('.task-card .task-review-actions > .danger');
  check('task card also requires explicit restore confirmation', await evaluate("!!document.querySelector('.task-card .task-review-confirm') && !window.__calls.some(c=>c.cmd==='task_review' && c.args.decision==='reject')"));
  await click('.task-card .task-review-confirm .danger');
  check('confirmed reject uses existing IPC and settles review state', await evaluate("window.__calls.filter(c=>c.cmd==='task_review' && c.args.decision==='reject').length === 1 && !!document.querySelector('.task-execution-review-state.rejected')"));
  await evaluate('window.__reviewRecoveryFixture()'); await sleep(100);
  check('recovery lists conflicting path and hides review decisions', await evaluate("!!document.querySelector('.task-execution-review .task-review-recovery code') && document.querySelector('.task-execution-review .task-review-recovery code').textContent==='src/example.ts' && !document.querySelector('.task-execution-review .primary') && document.querySelector('.task-execution-done').textContent.includes('восстановления')"));
  check('task card displays same recovery warning', await evaluate("!!document.querySelector('.task-card .task-review-recovery') && document.querySelector('.task-card .task-review-recovery').textContent.includes('target changed externally')"));
  await click('.task-execution-review .task-review-recovery button'); await sleep(100);
  check('safe recovery uses dedicated IPC and restores pending review', await evaluate("window.__calls.some(c=>c.cmd==='task_recover_review' && c.args.id==='smoke-task') && !!document.querySelector('.task-execution-review .primary') && !document.querySelector('.task-review-recovery')"));
  await click('.task-execution-back');
  check('return to chat is available', await evaluate("!document.querySelector('.task-execution') && !!document.querySelector('.chat-scroll')"));
  await click('.task-summary');
  check('completed task shows delete action', await evaluate("!!document.querySelector('.task-execution-actions .danger')"));
  await click('.task-execution-actions .danger');
  check('delete asks for confirmation first', await evaluate("!!document.querySelector('.task-delete-confirm') && !window.__calls.some(c=>c.cmd==='task_delete')"));
  await click('.task-delete-confirm .ghost');
  check('cancel leaves the completed task', await evaluate("!!document.querySelector('.task-execution') && !window.__calls.some(c=>c.cmd==='task_delete')"));
  await click('.task-execution-actions .danger');
  await click('.task-delete-confirm .danger');
  check('confirmed delete uses same task id', await evaluate("window.__calls.some(c=>c.cmd==='task_delete' && c.args.id==='smoke-task')"));
  check('deleting opened task returns to chat', await evaluate("!document.querySelector('.task-execution') && !!document.querySelector('.chat-scroll')"));
  check('deleted task disappears from task list', await evaluate("!document.querySelector('.task-summary')"));
  for (const theme of ['obsidian', 'light', 'midnight', 'terminal', 'solarized', 'graphite', 'rosewood', 'nord']) {
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