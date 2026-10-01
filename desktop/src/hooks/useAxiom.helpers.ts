/**
 * Pure helpers for the AXIOM workspace store (W2.7 decomposition).
 *
 * These functions carry no React state and no side effects — they map backend
 * facts to display strings and immutably shape live-message objects. They live
 * apart from `useAxiom.ts` so the hook stays focused on state and effects, and
 * so they can be unit-reasoned in isolation.
 */

import type { LiveMessage, ModelInfo } from "../types";

/** Monotonic id for live (in-flight) assistant/user messages. */
let liveId = 0;

/** A fresh streaming assistant message to append when a turn starts. */
export function liveAssistant(content = "", thinking = ""): LiveMessage {
  return {
    id: `live-${++liveId}`,
    role: "assistant",
    content,
    thinking,
    streaming: true,
    toolCalls: [],
    sources: [],
    createdAt: Date.now(),
  };
}

/** Monotonic id for a user message, sharing the live-message counter. */
export function nextUserId(): string {
  return `u-${++liveId}`;
}

/** Mutate the trailing streaming assistant message, immutably. */
export function updateLive(
  messages: LiveMessage[],
  mutate: (m: LiveMessage) => void,
): LiveMessage[] {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role === "assistant" && message.streaming) {
      const copy: LiveMessage = {
        ...message,
        toolCalls: message.toolCalls.map((tool) => ({ ...tool })),
        // W3.4: clone the artifacts array so a later push never mutates a
        // previously-rendered message's state.
        artifacts: message.artifacts ? [...message.artifacts] : undefined,
      };
      mutate(copy);
      const next = [...messages];
      next[i] = copy;
      return next;
    }
  }
  return messages;
}

export function errorText(err: unknown): string {
  const text = err instanceof Error ? err.message : String(err);
  return text.replace(/^Error:\s*/, "");
}

export function activeProviderLabel(name: string, providerId: string): string {
  return providerId === "ollama" ? name : `${providerId}/${name}`;
}

/** Match a model by exact name, then by display label, then by substring. */
export function resolveModel(models: ModelInfo[], needle: string): ModelInfo | null {
  const query = needle.trim().toLowerCase();
  if (!query) return null;
  return (
    models.find((m) => m.name.toLowerCase() === query) ??
    models.find((m) => m.displayName.toLowerCase() === query) ??
    models.find((m) => m.name.toLowerCase().includes(query)) ??
    models.find((m) => m.displayName.toLowerCase().includes(query)) ??
    null
  );
}

/** Human label of a tool as shown in the UI. */
export function toolLabel(name: string): string {
  if (name === "web_search") return "Веб-поиск";
  if (name === "fetch_url") return "Чтение страницы";
  if (name === "list_files") return "Просмотр папки";
  if (name === "read_file") return "Чтение файла";
  if (name === "write_file") return "Запись файла";
  if (name === "edit_file") return "Редактирование";
  if (name === "search_text") return "Поиск по коду";
  if (name === "search_files") return "Поиск файлов";
  if (name === "run_command") return "Терминал";
  if (name === "inspect_project") return "Осмотр проекта";
  if (name.startsWith("git_")) return "Git";
  return name;
}

/** What a tool is actually working on (query, URL, ...). */
export function toolTarget(_name: string, args: Record<string, unknown>): string {
  const pick = (...keys: string[]): string => {
    for (const key of keys) {
      const value = args?.[key];
      if (typeof value === "string" && value.trim()) return value.trim();
    }
    return "";
  };
  const query = args?.query;
  const url = args?.url;
  if (typeof query === "string" && query.trim()) return query.trim();
  if (typeof url === "string" && url.trim()) return url.trim();
  return pick("command", "path", "pattern", "glob", "source", "destination");
}

export function toolStatusText(name: string, args: Record<string, unknown>): string {
  const target = toolTarget(name, args);
  if (name === "web_search") return target ? `Ищет: «${target}»` : "Ищет в интернете…";
  if (name === "fetch_url") return target ? `Читает: ${target}` : "Читает страницу…";
  if (name === "list_files") return target ? `Смотрит папку: ${target}` : "Смотрит файлы…";
  if (name === "read_file") return target ? `Читает: ${target}` : "Читает файл…";
  if (name === "write_file") return target ? `Пишет: ${target}` : "Пишет файл…";
  if (name === "edit_file") return target ? `Правит: ${target}` : "Редактирует…";
  if (name === "search_text" || name === "search_files") return target ? `Ищет: «${target}»` : "Ищет по проекту…";
  if (name === "run_command") return target ? `Выполняет: ${target}` : "Выполняет команду…";
  if (name.startsWith("git_")) return "Git…";
  return toolLabel(name);
}

/**
 * Live `/orchestrate` progress (real trajectory steps streamed by the core) →
 * the text of the status pill. The structured board renders every step, so only
 * the one-line status is derived here. Returns null for kinds without a status.
 */
export function orchestrationProgress(event: {
  kind: string;
  actor: string;
  summary: string;
}): string | null {
  const actor = event.actor || "orchestrator";
  switch (event.kind) {
    case "orchestration.command":
    case "orchestrator.plan":
      return "Оркестрация: план…";
    case "agent.start":
      return `Оркестрация: ${actor} выполняет задачу…`;
    case "agent.done":
      return `Оркестрация: ${actor} готов`;
    case "agent.failed":
      return `Оркестрация: ${actor} — ошибка`;
    case "subagent.model":
      return `Оркестрация: ${actor} → ${event.summary}`;
    case "subagent.reasoning":
      return `Оркестрация: ${actor} — думает…`;
    case "subagent.answer":
      return `Оркестрация: ${actor} — пишет…`;
    case "subagent.tool.call":
    case "subagent.tool.result":
      return `Оркестрация: ${actor} — ${event.summary}`;
    case "orchestrator.review":
      return "Оркестрация: review…";
    case "verification.completed":
      return "Оркестрация: verification…";
    case "orchestrator.done":
      return "Оркестрация: завершена";
    case "orchestration.cancelled":
      return "Оркестрация остановлена";
    case "orchestration.failed":
      return "Оркестрация: сбой";
    default:
      return null;
  }
}
