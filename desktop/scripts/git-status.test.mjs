import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = ts.transpileModule(readFileSync(new URL('../src/lib/gitStatus.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 },
}).outputText;
const sandbox = { exports: {} };
vm.runInNewContext(source, sandbox);
const parse = (raw) => {
  const map = sandbox.exports.parseGitStatus(raw);
  return Object.fromEntries(map.entries());
};

test('parses M/A/D/?/R/U letters from a real `git status --short` shape', () => {
  assert.deepEqual(parse(null), {});
  assert.deepEqual(parse('## main...origin/main\n M src/app.py\nA  new.txt\n D gone.txt\n?? untracked.md\nR  a.txt -> b.txt\nUU conflict.txt'), {
    'src/app.py': 'M',
    'new.txt': 'A',
    'gone.txt': 'D',
    'untracked.md': '?',
    'a.txt -> b.txt': 'R',
    'conflict.txt': 'U',
  });
});

test('normalises quoted and backslash paths and keeps the worktree letter first', () => {
  assert.deepEqual(parse('M  "a b.md"'), { 'a b.md': 'M' });
  assert.deepEqual(parse('AM src\\main.py'), { 'src/main.py': 'M' });
  assert.deepEqual(parse(' M src/x.py'), { 'src/x.py': 'M' });
});
