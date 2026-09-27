const DRAFTS_KEY = "axiom.composer.drafts.v1";
const HISTORY_PREFIX = "axiom.composer.history.v1.";
const NEW_CHAT_KEY = "__new_chat__";
const MAX_HISTORY = 100;

function storageKey(chatId: string | null): string {
  return chatId ?? NEW_CHAT_KEY;
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key);
    return value ? (JSON.parse(value) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage can be disabled or full; composer use should still work.
  }
}

export function readComposerDraft(chatId: string | null): string {
  const drafts = readJson<Record<string, unknown>>(DRAFTS_KEY, {});
  const value = drafts[storageKey(chatId)];
  return typeof value === "string" ? value : "";
}

export function writeComposerDraft(chatId: string | null, draft: string): void {
  const drafts = readJson<Record<string, unknown>>(DRAFTS_KEY, {});
  const key = storageKey(chatId);
  if (draft) drafts[key] = draft;
  else delete drafts[key];
  writeJson(DRAFTS_KEY, drafts);
}

export function readPromptHistory(chatId: string | null): string[] {
  const value = readJson<unknown>(`${HISTORY_PREFIX}${storageKey(chatId)}`, []);
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").slice(-MAX_HISTORY)
    : [];
}

export function writePromptHistory(chatId: string | null, prompts: string[]): void {
  writeJson(`${HISTORY_PREFIX}${storageKey(chatId)}`, prompts.slice(-MAX_HISTORY));
}

export function clearComposerData(chatId: string): void {
  const drafts = readJson<Record<string, unknown>>(DRAFTS_KEY, {});
  delete drafts[storageKey(chatId)];
  writeJson(DRAFTS_KEY, drafts);
  try {
    localStorage.removeItem(`${HISTORY_PREFIX}${storageKey(chatId)}`);
  } catch {
    // Storage can be disabled; chat deletion must still complete.
  }
}
