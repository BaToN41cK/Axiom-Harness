import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = ts.transpileModule(readFileSync(new URL('../src/lib/i18n.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 },
}).outputText;
const sandbox = { exports: {} };
vm.runInNewContext(source, sandbox);
const { t, normalizeLocale, FALLBACK_STRINGS } = sandbox.exports;

test('navigation tabs resolve in both locales without hard-coded component text', () => {
  assert.equal(t('ui.tabs.files', 'en'), 'Files');
  assert.equal(t('ui.tabs.files', 'ru'), 'Файлы');
  assert.equal(t('ui.tabs.tasks', 'ru'), 'Задачи');
  assert.equal(t('ui.topbar.no_model', 'ru'), 'модель не выбрана');
});

test('bridge strings win, snapshot covers first paint, unknown key falls back to key', () => {
  assert.equal(t('ui.tabs.files', 'ru', { 'ui.tabs.files': 'Files' }), 'Files');
  assert.equal(t('ui.tabs.git', 'en', null), 'Git');
  assert.equal(t('does.not.exist', 'ru'), 'does.not.exist');
  assert.equal(normalizeLocale('ru'), 'ru');
  assert.equal(normalizeLocale('xx'), 'en');
  assert.ok(FALLBACK_STRINGS.en['ui.tabs.files'] && FALLBACK_STRINGS.ru['ui.tabs.files']);
});
