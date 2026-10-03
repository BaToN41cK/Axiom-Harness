/**
 * Pure helpers for the AXIOM workspace store (W2.7 decomposition).
 *
 * These functions carry no React state and no side effects — they map backend
 * facts to display strings and immutably shape live-message objects. They live
 * apart from `useAxiom.ts` so the hook stays focused on state and effects, and
 * so they can be unit-reasoned in isolation.
 */

import type { LiveMessage, ModelInfo } from "../types";
import { t as tr, tVar } from "../lib/i18n";

type Strings = Record<string, string> | null | undefined;

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

/** Human label of a tool as shown in the UI (W3.8: via the RU/EN catalog). */
export function toolLabel(name: string, locale: unknown = "ru", strings?: Strings): string {
  const key =
    name === "web_search" ? "ui.tool.web_search"
    : name === "fetch_url" ? "ui.tool.fetch_url"
    : name === "list_files" ? "ui.tool.list_files"
    : name === "read_file" ? "ui.tool.read_file"
    : name === "write_file" ? "ui.tool.write_file"
    : name === "edit_file" ? "ui.tool.edit_file"
    : name === "search_text" ? "ui.tool.search_text"
    : name === "search_files" ? "ui.tool.search_files"
    : name === "run_command" ? "ui.tool.run_command"
    : name === "inspect_project" ? "ui.tool.inspect_project"
    : name === "run_tests" ? "ui.tool.run_tests"
    : name === "run_linter" ? "ui.tool.run_linter"
    : name === "build_project" ? "ui.tool.build_project"
    : name === "verify_changes" ? "ui.tool.verify_changes"
    : name.startsWith("git_") ? "ui.tool.git"
    : null;
  if (key === null) return name;
  const hit = tr(key, locale, strings);
  return hit === key ? name : hit;
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

export function toolStatusText(
  name: string,
  args: Record<string, unknown>,
  locale: unknown = "ru",
  strings?: Strings,
): string {
  const target = toolTarget(name, args);
  const pick = (withTarget: string, plain: string): string => {
    if (target) return tVar(withTarget, locale, strings ?? null, { target });
    return tr(plain, locale, strings);
  };
  if (name === "web_search") return pick("ui.toolstatus.searching", "ui.toolstatus.searching_plain");
  if (name === "fetch_url") return pick("ui.toolstatus.reading_page", "ui.toolstatus.reading_page_plain");
  if (name === "list_files") return pick("ui.toolstatus.browsing", "ui.toolstatus.browsing_plain");
  if (name === "read_file") return pick("ui.toolstatus.reading_file", "ui.toolstatus.reading_file_plain");
  if (name === "write_file") return pick("ui.toolstatus.writing_file", "ui.toolstatus.writing_file_plain");
  if (name === "edit_file") return pick("ui.toolstatus.editing", "ui.toolstatus.editing_plain");
  if (name === "search_text" || name === "search_files") return pick("ui.toolstatus.searching_project", "ui.toolstatus.searching_project_plain");
  if (name === "run_command") return pick("ui.toolstatus.running", "ui.toolstatus.running_plain");
  if (name === "run_tests" || name === "run_linter" || name === "build_project" || name === "verify_changes") {
    return tr("ui.toolstatus.checks", locale, strings);
  }
  if (name.startsWith("git_")) return tr("ui.toolstatus.git", locale, strings);
  return toolLabel(name, locale, strings);
}

/**
 * Live `/orchestrate` progress (real trajectory steps streamed by the core) →
 * the text of the status pill. The structured board renders every step, so only
 * the one-line status is derived here. Returns null for kinds without a status.
 */
export function orchestrationProgress(
  event: {
    kind: string;
    actor: string;
    summary: string;
  },
  locale: unknown = "ru",
  strings?: Strings,
): string | null {
  const actor = event.actor || "orchestrator";
  const vars = { actor, summary: event.summary };
  switch (event.kind) {
    case "orchestration.command":
    case "orchestrator.plan":
      return tr("ui.orch.plan", locale, strings);
    case "agent.start":
      return tVar("ui.orch.agent_run", locale, strings ?? null, vars);
    case "agent.done":
      return tVar("ui.orch.agent_done", locale, strings ?? null, vars);
    case "agent.failed":
      return tVar("ui.orch.agent_failed", locale, strings ?? null, vars);
    case "subagent.model":
      return tVar("ui.orch.model", locale, strings ?? null, vars);
    case "subagent.reasoning":
      return tVar("ui.orch.reasoning", locale, strings ?? null, vars);
    case "subagent.answer":
      return tVar("ui.orch.answer", locale, strings ?? null, vars);
    case "subagent.tool.call":
    case "subagent.tool.result":
      return tVar("ui.orch.tool", locale, strings ?? null, vars);
    case "orchestrator.review":
      return tr("ui.orch.review", locale, strings);
    case "verification.completed":
      return tr("ui.orch.verification", locale, strings);
    case "orchestrator.done":
      return tr("ui.orch.done", locale, strings);
    case "orchestration.cancelled":
      return tr("ui.orch.cancelled", locale, strings);
    case "orchestration.failed":
      return tr("ui.orch.failed", locale, strings);
    default:
      return null;
  }
}
