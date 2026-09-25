/**
 * `/orchestrate` board state — pure reducers over the real trajectory events.
 *
 * The core streams `orchestration` events (`agent.start`, `subagent.tool.call`,
 * `orchestrator.review`, `verification.completed`, …) and finally returns one
 * report object. This module turns both into ONE typed state, so the chat can
 * render agent cards, a tool timeline and the closing sections instead of a
 * wall of emoji lines. Nothing here is invented: every field either comes from
 * an event/reply field or from its real text.
 */

import type {
  OrchestrationAgent,
  OrchestrationReport,
  OrchestrationResult,
  OrchestrationState,
  OrchestrationStep,
  OrchestrationStepKind,
} from "../types";

/** One live `/orchestrate` step as the bridge streams it. */
export interface OrchestrationEvent {
  kind: string;
  actor: string;
  summary: string;
  seq?: number;
}

/** Labels of the real agent registry (`axiom.core.agents.DEFAULT_AGENTS`). */
const AGENT_LABELS: Record<string, string> = {
  orchestrator: "Orchestrator",
  analyst: "Analyst",
  coder: "Coder",
  debugger: "Debugger",
  reviewer: "Reviewer",
  researcher: "Researcher",
  tester: "Tester",
  architect: "Architect",
  security: "Security",
};

/** Tool → visual category, mirroring `axiom.core.tools.meta.CATEGORY_OF`. */
const TOOL_KINDS: Record<string, OrchestrationStepKind> = {
  web_search: "web",
  fetch_url: "fetch",
  list_files: "folder",
  inspect_project: "folder",
  read_file: "read",
  search_text: "search",
  search_files: "search",
  write_file: "write",
  edit_file: "write",
  apply_patch: "write",
  create_directory: "write",
  delete_file: "write",
  move_file: "write",
  copy_file: "write",
  run_command: "terminal",
  run_tests: "verification",
  run_linter: "verification",
  build_project: "verification",
  verify_changes: "verification",
  git_status: "git",
  git_diff: "git",
  git_log: "git",
  git_branch: "git",
};

/** Category of a real tool name ("other" for tools the UI does not know). */
export function stepKindOf(tool: string): OrchestrationStepKind {
  return TOOL_KINDS[tool] ?? "other";
}

/** Human label of a real agent id ("analyst" → "Analyst"). */
export function agentLabel(id: string): string {
  const key = (id || "").toLowerCase();
  if (!key) return "Agent";
  return AGENT_LABELS[key] ?? key[0].toUpperCase() + key.slice(1);
}

/** Fresh state for a run that has just started. */
export function emptyOrchestration(task: string, startedAt = Date.now()): OrchestrationState {
  return {
    task,
    mode: null,
    phase: "planning",
    plannedAgents: [],
    agents: [],
    steps: [],
    review: null,
    verification: null,
    definitionOfDone: [],
    reports: [],
    completed: null,
    error: null,
    durationMs: null,
    startedAt,
    finishedAt: null,
  };
}


/** Sanitize an id so it can be used as a React key suffix. */
function slug(value: string): string {
  return value.replace(/[^\w.-]+/g, "-").toLowerCase();
}

function emptyAgent(id: string): OrchestrationAgent {
  return {
    id,
    label: agentLabel(id),
    provider: null,
    model: null,
    status: "pending",
    task: null,
    thought: null,
    answer: null,
    lastTool: null,
    lastTarget: null,
    toolsOk: 0,
    toolsFailed: 0,
    error: null,
  };
}

/** Insert or update one worker, keeping the real registration order. */
function patchAgent(
  state: OrchestrationState,
  id: string,
  patch: Partial<OrchestrationAgent>,
): OrchestrationState {
  const index = state.agents.findIndex((agent) => agent.id === id);
  const agents = [...state.agents];
  if (index === -1) {
    agents.push({ ...emptyAgent(id), ...patch });
  } else {
    agents[index] = { ...agents[index], ...patch };
  }
  return { ...state, agents };
}

/** `"mode=orchestrated agents=analyst,coder"` → its real parts. */
function parsePlan(summary: string): { mode: string | null; agents: string[] } {
  const mode = /mode=(\S+)/.exec(summary)?.[1] ?? null;
  const raw = /agents=(\S*)/.exec(summary)?.[1] ?? "";
  const agents = raw
    .split(",")
    .map((name) => name.trim().toLowerCase())
    .filter(Boolean);
  return { mode, agents };
}

/** `"write_file index.html"` → tool name + what it really touched. */
function splitToolSummary(summary: string): { tool: string; rest: string } {
  const match = /^(\S+)\s*(.*)$/.exec(summary.trim());
  return { tool: match?.[1] ?? summary.trim(), rest: (match?.[2] ?? "").trim() };
}

/** `"write_file ok (5 ms)"` / `"read_file failed: no such file"` → outcome. */
function parseToolResult(rest: string): {
  state: "ok" | "failed";
  durationMs: number | null;
  detail: string | null;
} {
  const failed = /^failed\b:?\s*(.*)$/is.exec(rest);
  if (failed) {
    const detail = failed[1].trim();
    return { state: "failed", durationMs: null, detail: detail || "ошибка инструмента" };
  }
  const duration = /\((\d+)\s*ms\)/.exec(rest)?.[1];
  return {
    state: "ok",
    durationMs: duration ? Number(duration) : null,
    detail: rest && !/^ok\b/.test(rest) ? rest : null,
  };
}

/** All workers still running — used when the run ends or is cancelled. */
function settleAgents(
  state: OrchestrationState,
  status: OrchestrationAgent["status"],
): OrchestrationState {
  return {
    ...state,
    agents: state.agents.map((agent) =>
      agent.status === "running" || agent.status === "pending" ? { ...agent, status } : agent,
    ),
    steps: state.steps.map((step) =>
      step.state === "running" ? { ...step, state: "cancelled" as const } : step,
    ),
  };
}

/**
 * Reduce ONE live trajectory event into the board state.
 *
 * Unknown kinds return the very same object, so React skips the re-render.
 */
export function applyOrchestrationEvent(
  state: OrchestrationState,
  event: OrchestrationEvent,
): OrchestrationState {
  const actor = (event.actor || "orchestrator").trim().toLowerCase() || "orchestrator";
  const summary = (event.summary || "").trim();
  switch (event.kind) {
    case "orchestration.command":
      return { ...state, task: state.task || summary.replace(/^\/orchestrate\s*/i, "").trim() };
    case "orchestrator.plan": {
      const { mode, agents } = parsePlan(summary);
      let next: OrchestrationState = { ...state, mode: mode ?? state.mode, plannedAgents: agents };
      for (const agent of agents) next = patchAgent(next, agent, {});
      return { ...next, phase: "working" };
    }
    case "agent.start": {
      const [id, task] = summary.split(/:\s*/, 2);
      const agentId = (id || actor).trim().toLowerCase();
      return patchAgent(state, agentId, {
        status: "running",
        task: (task ?? "").trim() || null,
        error: null,
      });
    }
    case "agent.done":
      // Sequential runs summarize as "coder done", parallel ones send the id.
      return patchAgent(state, (summary.split(/\s+/)[0] || actor).trim().toLowerCase(), {
        status: "done",
      });
    case "agent.failed":
      return patchAgent(state, actor, {
        status: "failed",
        error: summary || "агент завершился с ошибкой",
      });
    case "subagent.model": {
      const [provider, model] = summary.split("/", 2);
      return patchAgent(state, actor, { provider: provider || null, model: model || null });
    }
    case "subagent.reasoning":
      return patchAgent(state, actor, { thought: summary || null });
    case "subagent.answer":
      return patchAgent(state, actor, { answer: summary || null });
    case "subagent.tool.call": {
      const { tool, rest } = splitToolSummary(summary);
      const step: OrchestrationStep = {
        id: `step-${slug(actor)}-${slug(tool)}-${state.steps.length}`,
        actor,
        tool,
        kind: stepKindOf(tool),
        target: rest,
        state: "running",
        durationMs: null,
        detail: null,
      };
      return patchAgent({ ...state, steps: [...state.steps, step] }, actor, {
        lastTool: tool,
        lastTarget: rest || null,
      });
    }
    case "subagent.tool.result": {
      const { tool, rest } = splitToolSummary(summary);
      const outcome = parseToolResult(rest);
      const steps = [...state.steps];
      for (let i = steps.length - 1; i >= 0; i--) {
        const step = steps[i];
        if (step.actor === actor && step.tool === tool && step.state === "running") {
          steps[i] = {
            ...step,
            state: outcome.state,
            durationMs: outcome.durationMs,
            detail: outcome.detail ?? step.detail,
          };
          break;
        }
      }
      const agent = state.agents.find((item) => item.id === actor);
      return patchAgent({ ...state, steps }, actor, {
        toolsOk: (agent?.toolsOk ?? 0) + (outcome.state === "ok" ? 1 : 0),
        toolsFailed: (agent?.toolsFailed ?? 0) + (outcome.state === "failed" ? 1 : 0),
      });
    }
    case "orchestrator.review": {
      const verdict = /REWORK|NEEDS|FAIL/i.test(summary) ? "rework" : "approved";
      return {
        ...state,
        phase: verdict === "rework" ? "review" : state.phase,
        review: { verdict, text: summary, issues: [], requiredChanges: [] },
      };
    }
    case "verification.completed":
      return {
        ...state,
        phase: "verification",
        verification: {
          ok: /FAILED/i.test(summary) ? false : /PASSED/i.test(summary) ? true : null,
          summary: summary || null,
          error: null,
        },
      };
    case "orchestrator.done":
      return { ...state, phase: "verification" };
    case "orchestration.cancelled":
      return { ...settleAgents(state, "cancelled"), phase: "cancelled", finishedAt: Date.now() };
    case "orchestration.failed":
      return {
        ...settleAgents(state, "failed"),
        phase: "failed",
        error: summary || "оркестрация завершилась сбоем",
        finishedAt: Date.now(),
      };
    default:
      return state;
  }
}

/** Merge the real `orchestrate` reply into the live board state. */
export function applyOrchestrationResult(
  state: OrchestrationState,
  result: OrchestrationResult,
): OrchestrationState {
  const reports: OrchestrationReport[] = [...(result.results ?? [])];
  const approved = result.approved ?? null;
  const completed = result.completed ?? approved;
  const cancelled = Boolean(result.cancelled) || result.error === "cancelled";
  const failed = !cancelled && (result.ok === false || Boolean(result.error));
  // How a worker the live feed left open really ended.
  const settled: OrchestrationAgent["status"] = cancelled ? "cancelled" : failed ? "failed" : "done";

  // The reply is the authority: workers the live feed left open are settled by
  // their real report status instead of an optimistic "done".
  let agents = state.agents.map((agent) => {
    const report = reports.find((item) => (item.agent ?? "").toLowerCase() === agent.id);
    const open = agent.status === "running" || agent.status === "pending";
    return {
      ...agent,
      status: report?.error ? ("failed" as const) : open ? settled : agent.status,
    };
  });
  for (const report of reports) {
    const id = (report.agent ?? "").toLowerCase();
    if (!id || agents.some((agent) => agent.id === id)) continue;
    agents = [
      ...agents,
      {
        ...emptyAgent(id),
        provider: report.provider_id ?? null,
        model: report.model ?? null,
        status: report.error ? ("failed" as const) : ("done" as const),
        error: report.error ?? null,
      },
    ];
  }

  const verification = result.verification
    ? {
        ok: result.verification.ok ?? null,
        summary: result.verification.summary ?? null,
        error: result.verification.error ?? null,
      }
    : state.verification;

  const hasReview = Boolean(result.review || result.review_details);
  const review = hasReview
    ? {
        verdict:
          approved == null
            ? state.review?.verdict ?? null
            : approved
              ? ("approved" as const)
              : ("rework" as const),
        text: result.review ?? state.review?.text ?? "",
        issues: result.review_details?.issues ?? state.review?.issues ?? [],
        requiredChanges:
          result.review_details?.required_changes ?? state.review?.requiredChanges ?? [],
      }
    : state.review;

  const phase = cancelled ? ("cancelled" as const) : failed ? ("failed" as const) : ("done" as const);

  return {
    ...state,
    agents,
    steps: state.steps.map((step) =>
      step.state === "running" ? { ...step, state: "cancelled" as const } : step,
    ),
    reports,
    review,
    verification,
    definitionOfDone: result.definition_of_done ?? state.definitionOfDone,
    completed,
    error: cancelled ? null : result.error ?? state.error,
    durationMs: result.duration_ms ?? state.durationMs,
    finishedAt: Date.now(),
    phase,
  };
}

/** "3.4s" / "1m 12s" — duration of a finished run for the board header. */
export function formatRunTime(ms: number): string {
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  return `${minutes}m ${String(Math.floor((ms % 60_000) / 1000)).padStart(2, "0")}s`;
}

/**
 * Compact Markdown of the run — the honest fallback for chat history.
 *
 * Backend history stores message text only, so a reloaded chat shows this
 * summary instead of the board. It is generated from the same real state, never
 * invented, and the structured board stays the primary rendering.
 */
export function orchestrationMarkdown(state: OrchestrationState): string {
  const lines: string[] = [];
  const title =
    state.phase === "cancelled"
      ? "Оркестрация остановлена"
      : state.completed === false
        ? "Оркестрация завершена с замечаниями"
        : "Оркестрация завершена";
  lines.push(`## ${title}`);
  if (state.mode) {
    const agents = state.agents.map((agent) => agent.label).join(", ") || "—";
    lines.push(`Режим: \`${state.mode}\` · агенты: ${agents}`);
  }
  if (state.error) lines.push(`Ошибка: ${state.error}`);

  if (state.reports.length > 0) {
    lines.push("", "## Отчёты агентов");
    for (const report of state.reports) {
      const identity = `${report.provider_id ?? "?"}${report.model ? `/${report.model}` : ""}`;
      const body = report.content ?? report.error ?? "нет отчёта";
      lines.push(`- **${agentLabel(report.agent ?? "agent")}** (\`${identity}\`): ${body}`);
    }
  } else if (state.agents.length > 0) {
    lines.push("", "## Агенты");
    for (const agent of state.agents) {
      const identity = `${agent.provider ?? "?"}${agent.model ? `/${agent.model}` : ""}`;
      lines.push(
        `- **${agent.label}** (\`${identity}\`): ${agent.status}` +
          `, инструментов ok ${agent.toolsOk}, ошибок ${agent.toolsFailed}` +
          (agent.error ? ` — ${agent.error}` : ""),
      );
    }
  }

  if (state.review) {
    const verdict = state.review.verdict === "rework" ? "REWORK" : "APPROVED";
    lines.push("", `## Reviewer (${verdict})`, state.review.text || "ответ не получен");
    if (state.review.issues.length) lines.push(`Issues: ${state.review.issues.join("; ")}`);
    if (state.review.requiredChanges.length) {
      lines.push(`Required: ${state.review.requiredChanges.join("; ")}`);
    }
  }

  if (state.verification) {
    const verdict =
      state.verification.ok === true ? "PASSED" : state.verification.ok === false ? "FAILED" : "—";
    lines.push(
      "",
      `## Verification (${verdict})`,
      state.verification.summary ?? state.verification.error ?? "не запускалась",
    );
  }

  if (state.definitionOfDone.length > 0) {
    lines.push("", "## Definition of Done");
    for (const item of state.definitionOfDone) lines.push(`- ${item}`);
  }

  if (state.finishedAt) {
    const duration = state.durationMs ?? state.finishedAt - state.startedAt;
    lines.push("", `Время выполнения: ${formatRunTime(duration)}`);
  }
  return lines.join("\n");
}

