// Release-security audit (P0). Chat markdown is sanitized first
// (react-markdown + rehype-sanitize); this page CSP is the second boundary.
// Remote allowlist mirrors real resources only: payment API (connect),
// favicon service (img). Plugin panels (srcdoc
// iframe + inline script, e.g. bundled hello-panel) inherit this policy and
// degrade to static cards — documented tradeoff, see docs/plugins.md §11.6.
// The shell plugin is not initialized in src-tauri/src/lib.rs, so its
// capabilities were dead attack surface; dialog stays (pick_folder).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const conf = JSON.parse(readFileSync(new URL('../src-tauri/tauri.conf.json', import.meta.url), 'utf8'));
const caps = JSON.parse(readFileSync(new URL('../src-tauri/capabilities/default.json', import.meta.url), 'utf8'));

const directives = Object.fromEntries(
  String(conf.app.security.csp).split(';').map((s) => s.trim()).filter(Boolean).map((s) => {
    const [name, ...rest] = s.split(/\s+/);
    return [name, rest];
  }),
);

test('release CSP is enabled and blocks inline/remote scripts and objects', () => {
  assert.ok(conf.app.security.csp, 'CSP must not be null');
  assert.ok(!directives['script-src'].includes("'unsafe-inline'"), 'no inline scripts page-wide');
  assert.ok(!directives['script-src'].some((v) => v.startsWith('http')), 'no remote scripts');
  assert.deepEqual(directives['object-src'], ["'none'"]);
  assert.deepEqual(directives['frame-ancestors'], ["'none'"]);
});

test('CSP allowlist mirrors real resources only', () => {
  const connect = directives['connect-src'];
  assert.ok(connect.includes('ipc:'), 'tauri invoke transport');
  assert.ok(connect.includes('https://axiom-harness.onrender.com'), 'payment backend');
  assert.ok(!connect.includes('https:'), 'no blanket https connect');
  const img = directives['img-src'];
  assert.ok(img.includes('data:'), 'composer data-URL previews');
  assert.ok(img.includes('https://icons.duckduckgo.com'), 'favicon service');
  assert.ok(!img.includes('https:'), 'model <img> cannot phone home anywhere');
});

test('webview capabilities are least privilege', () => {
  assert.ok(!caps.permissions.includes('shell:allow-spawn'), 'shell plugin is not initialized');
  assert.ok(!caps.permissions.includes('shell:allow-stdin-write'), 'bridge uses stdio, not shell plugin');
  assert.ok(caps.permissions.includes('dialog:default'), 'pick_folder needs dialog');
  assert.ok(caps.permissions.includes('core:default'), 'invoke needs core');
});
