import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const source = ts.transpileModule(readFileSync(new URL('../src/lib/unifiedDiff.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 },
}).outputText;
const sandbox = { exports: {} };
vm.runInNewContext(source, sandbox);
const parse = (text, limit) => JSON.parse(JSON.stringify(sandbox.exports.parseUnifiedDiff(text, limit)));

test('context, header-like code, indentation and final newline have exact semantics', () => {
  const result = parse('--- a/f\n+++ b/f\n@@ -7,2 +9,2 @@\n same\n---old\n+++new\n');
  assert.equal(result.add, 1); assert.equal(result.del, 1);
  assert.equal(result.incomplete, false);
  assert.deepEqual(result.hunks[0].lines, [
    { kind: 'context', text: 'same', oldNumber: 7, newNumber: 9 },
    { kind: 'del', text: '--old', oldNumber: 8, newNumber: null },
    { kind: 'add', text: '++new', oldNumber: null, newNumber: 10 },
  ]);
});
test('new/deleted files and omitted counts', () => {
  assert.equal(parse('@@ -0,0 +1 @@\n+\t  code\n').hunks[0].lines[0].text, '\t  code');
  assert.equal(parse('@@ -1 +0,0 @@\n-old').del, 1);
});
test('multiple hunks, CRLF and missing newline marker', () => {
  const result = parse('@@ -1 +1 @@\r\n-a\r\n+b\r\n\\ No newline at end of file\r\n@@ -10 +20 @@\r\n same');
  assert.equal(result.hunks.length, 2);
  assert.equal(result.hunks[0].lines[2].kind, 'meta');
  assert.equal(result.hunks[1].lines[0].newNumber, 20);
  assert.equal(result.incomplete, false);
});
test('render cap does not falsify counters', () => {
  const result = parse('@@ -0,0 +1,2000 @@\n' + '+x\n'.repeat(2000));
  assert.equal(result.add, 2000);
  assert.equal(result.hunks[0].lines.length, 1500);
  assert.equal(result.hunks[0].omitted, 500);
});
test('binary, empty and truncated patches are honest', () => {
  assert.equal(parse('Binary files differ').hunks.length, 0);
  assert.equal(parse('').add, 0);
  assert.equal(parse('@@ -1,3 +1,3 @@\n same\n… diff truncated').incomplete, true);
});
