import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const modules = new Map();
function load(name) {
  if (modules.has(name)) return modules.get(name);
  const source = ts.transpileModule(readFileSync(new URL(`../src/lib/${name}.ts`, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021, esModuleInterop: true },
  }).outputText;
  const sandbox = { exports: {}, require: (id) => id.startsWith('./') ? load(id.slice(2)) : require(id) };
  vm.runInNewContext(source, sandbox);
  modules.set(name, sandbox.exports);
  return sandbox.exports;
}
const { languageForPath, highlightSource, highlightSourceLines, hljs } = load('syntaxHighlight');
const { highlightDiffHunks, DIFF_HIGHLIGHT_MAX_CHARS } = load('diffHighlight');
const { parseUnifiedDiff } = load('unifiedDiff');
const textOf = (html) => html.replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const samples = [
  ['main.py', 'python', 'def greet():\n    return "hello"'],
  ['main.ts', 'typescript', 'const answer: number = 42;'],
  ['main.js', 'javascript', 'const answer = 42;'],
  ['view.tsx', 'typescript', 'const view = <div title="hello">text</div>;'],
  ['view.jsx', 'javascript', 'const view = <div>text</div>;'],
  ['config.json', 'json', '{"enabled": true}'],
  ['config.yml', 'yaml', 'enabled: true'],
  ['README.md', 'markdown', '# Heading\n**bold**'],
  ['style.css', 'css', 'body { color: red; }'],
  ['index.html', 'xml', '<div title="hello">text</div>'],
  ['main.rs', 'rust', 'fn main() { let x = 42; }'],
  ['build.ps1', 'powershell', '$name = "hello"; Write-Host $name'],
  ['build.sh', 'bash', 'echo "$HOME"'],
  ['query.sql', 'sql', 'SELECT name FROM users;'],
  ['Dockerfile', 'dockerfile', 'FROM node:22'],
];
for (const [path, language, source] of samples) {
  test(`${path}: resolves and tokenizes without changing text`, () => {
    assert.equal(languageForPath(path), language);
    const result = highlightSource(source, path);
    assert.equal(result.language, language);
    assert.match(result.html, /class="hljs-/);
    assert.equal(textOf(result.html), source);
  });
}
test('path resolution handles Windows, case, extensionless files and unknown input', () => {
  assert.equal(languageForPath('C:\\folder.py\\MAIN.TSX'), 'typescript');
  assert.equal(languageForPath('folder.py/no-extension'), '');
  assert.equal(languageForPath('build/Dockerfile.dev'), 'dockerfile');
  for (const name of ['file.unknown', 'constructor', '__proto__', 'file.__proto__']) {
    assert.equal(languageForPath(name), '');
    assert.equal(highlightSourceLines('<img src=x onerror=alert(1)>', name), null);
  }
});
test('multiline tokens are independently balanced and preserve tabs, blanks and trailing newline', () => {
  const source = '/* comment\n\t  continued\n\nend */\nconst x = 1;\n';
  const rows = highlightSourceLines(source, 'code.ts');
  assert.equal(rows.length, source.split('\n').length);
  assert.match(rows[1], /hljs-comment/);
  for (const row of rows) {
    assert.equal((row.match(/<span\b/g) || []).length, (row.match(/<\/span>/g) || []).length);
  }
  assert.equal(rows.map(textOf).join('\n'), source);
});
test('source markup is escaped, including fake highlight spans and event handlers', () => {
  const source = '<img src=x onerror="alert(1)"><span class="hljs-keyword">&</span>';
  const rows = highlightSourceLines(source, 'view.html');
  assert.equal(rows.map(textOf).join('\n'), source);
  assert.doesNotMatch(rows.join(''), /<img|<script|<span class="hljs-keyword">&<\/span>/);
});
test('old/new versions tokenize independently and context uses the new version', () => {
  const parsed = parseUnifiedDiff('@@ -1,3 +1,3 @@\n-/*\n+const a = 1;\n const b = 2;\n-*/\n+const c = 3;');
  const before = JSON.stringify(parsed);
  const rows = highlightDiffHunks(parsed.hunks, 'main.ts')[0];
  assert.match(rows[0], /hljs-comment/);
  assert.match(rows[2], /hljs-keyword/);
  assert.doesNotMatch(rows[2], /hljs-comment/);
  assert.equal(JSON.stringify(parsed), before);
  rows.forEach((html, i) => assert.equal(textOf(html), parsed.hunks[0].lines[i].text));
});
test('reset lexical state between hunks; metadata never becomes source', () => {
  const parsed = parseUnifiedDiff('@@ -0,0 +1 @@\n+/*\n\\ No newline at end of file\n@@ -0,0 +10 @@\n+const x = 1;');
  const result = highlightDiffHunks(parsed.hunks, 'main.ts');
  assert.equal(result[0][1], null);
  assert.match(result[1][0], /hljs-keyword/);
});
test('oversized source falls back to text before invoking the highlighter', () => {
  const parsed = parseUnifiedDiff('@@ -0,0 +1 @@\n+' + 'x'.repeat(DIFF_HIGHLIGHT_MAX_CHARS + 1));
  const original = hljs.highlight;
  hljs.highlight = () => { throw new Error('must not be called'); };
  try { assert.equal(highlightDiffHunks(parsed.hunks, 'main.ts')[0][0], null); }
  finally { hljs.highlight = original; }
});
test('highlighter failure returns plain-text fallback', () => {
  const original = hljs.highlight;
  hljs.highlight = () => { throw new Error('unavailable'); };
  try { assert.equal(highlightSourceLines('const x = 1;', 'main.ts'), null); }
  finally { hljs.highlight = original; }
});
