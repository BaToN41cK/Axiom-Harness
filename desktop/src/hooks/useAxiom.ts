/**
 * AXIOM workspace store — the single place where the GUI meets the real core.
 *
 * Everything the interface shows is derived from backend facts:
 *  - boot steps mirror real bridge probes (health → models → model selection);
 *  - streaming text is batched per animation frame (smooth, no per-token re-render);
 *  - reasoning appears only when the model really sends it;
 *  - tool activity, sources and metrics come from real events;
 *  - the model selector really calls `set_model` and the next request uses it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  onCoreEvent,
  onCoreExit,
  onCoreStderr,
  openExternal,
  quitApp,
  request,
  restartCore,
} from "../bridge";
import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";
import { commandByName, matchingCommands, parseCommand, pluginCommandById, setPluginCommands } from "../lib/commands";
import { clearComposerData, readComposerDraft, writeComposerDraft } from "../lib/composerStorage";
import { stripDataUrl } from "../lib/format";
import { playUiSound } from "../lib/sound";
import type { UiSound } from "../lib/sound";
import { clampRightPanelWidth, RIGHT_PANEL_MIN } from "../lib/panelSize";
import {
  activeProviderLabel,
  errorText,
  liveAssistant,
  nextUserId,
  orchestrationProgress,
  resolveModel,
  toolStatusText,
  toolTarget,
  updateLive,
} from "./useAxiom.helpers";
// Re-exported so existing consumers keep importing these from `useAxiom`.
export { orchestrationProgress, resolveModel, toolLabel, toolTarget } from "./useAxiom.helpers";

/** Keep tool arguments for the chat previews, capping huge strings (file bodies). */
function capToolArgs(args: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(args)) {
    out[key] = typeof value === "string" && value.length > 24_000 ? value.slice(0, 24_000) : value;
  }
  return out;
}
import {
  applyOrchestrationEvent,
  applyOrchestrationResult,
  emptyOrchestration,
  orchestrationMarkdown,
} from "../lib/orchestration";
import type {
  Artifact,
  AxiomConfig,
  ChatHit,
  Conversation,
  CoreEvent,
  DoneMetrics,
  HealthReport,
  LiveMessage,
  ModelInfo,
  OrchestrationResult,
  ProjectInfo,
  ProjectSearchResult,
  WorkspaceFilesResult,
  SendResult,
  StartupReport,
  StatusReport,
  Task,
  TaskPlan,
  TerminalResult,
  ToolInfo,
  ProviderRow,
  ProviderModelRow,
  PluginRow,
  PluginInstallResult,
  MemoryRow,
  KnowledgeRow,
  KnowledgeHit,
  KnowledgeIndexResult,
  AgentRow,
  TrajectoryViewer,
  TreeNode,
  WorkspaceState,
  SearchProviderChoice,
  SearchTestResult,
  PermissionDecision,
  PermissionRequest,
} from "../types";

export type Phase = "booting" | "ready" | "unavailable" | "error";
export type Overlay = "help" | "status" | "tools" | "context" | "harness" | "documents" | null;
export type SettingsSection =
  | "general"
  | "models"
  | "providers"
  | "plugins"
  | "memory"
  | "knowledge"
  | "chat"
  | "tools"
  | "appearance"
  | "shortcuts"
  | "about";

export interface BootStep {
  id: string;
  label: string;
  state: "pending" | "running" | "ok" | "failed";
  detail: string | null;
}

export interface Toast {
  id: number;
  text: string;
  kind: "info" | "ok" | "error";
  leaving?: boolean;
}

/** Real boot sequence — each label is a probe that really runs. */
const BOOT_SEQUENCE: { id: string; label: string }[] = [
  { id: "ui", label: "Инициализация интерфейса" },
  { id: "detect", label: "Поиск Ollama" },
  { id: "connect", label: "Подключение к Ollama" },
  { id: "models", label: "Чтение установленных моделей" },
  { id: "select", label: "Выбор активной модели" },
  { id: "workspace", label: "Подготовка рабочего пространства" },
];

let toastId = 0;

function freshSteps(): BootStep[] {
  return BOOT_SEQUENCE.map((step) => ({ ...step, state: "pending", detail: null }));
}

export function useAxiom() {
  // ------------------------------------------------------------------- boot
  const [phase, setPhase] = useState<Phase>("booting");
  const [bootSteps, setBootSteps] = useState<BootStep[]>(freshSteps);
  const [bootError, setBootError] = useState<{ message: string; hint: string | null; url: string } | null>(
    null,
  );

  // ------------------------------------------------------------- connection
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [connected, setConnected] = useState(false);
  const [coreLost, setCoreLost] = useState(false);

  // ----------------------------------------------------------------- models
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [activeModel, setActiveModel] = useState<string | null>(null);
  const [activeModelProvider, setActiveModelProvider] = useState("ollama");
  const [modelDetail, setModelDetail] = useState<ModelInfo | null>(null);
  const [switchingModel, setSwitchingModel] = useState<string | null>(null);
  const [modelMenuSignal, setModelMenuSignal] = useState(0);

  // ------------------------------------------------------------------- chat
  const [chats, setChats] = useState<Conversation[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<LiveMessage[]>([]);
  const [chatSearch, setChatSearch] = useState("");
  const [generating, setGenerating] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskRequestPending, setTaskRequestPending] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [focusedTaskId, setFocusedTaskId] = useState<string | null>(null);
  const latestTaskEventRef = useRef<Task | null>(null);
  // W2.4: an ASK tool call that is really blocked until the user answers.
  const [pendingPermission, setPendingPermission] = useState<PermissionRequest | null>(null);
  const [liveState, setLiveState] = useState("idle");
  const [statusText, setStatusText] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [lastMetrics, setLastMetrics] = useState<DoneMetrics | null>(null);

  // ----------------------------------------------------------------- config
  const [config, setConfig] = useState<AxiomConfig | null>(null);
  const [providerRows, setProviderRows] = useState<ProviderRow[]>([]);
  const [providerModels, setProviderModels] = useState<ProviderModelRow[]>([]);
  const [providerLoading, setProviderLoading] = useState(false);
  const [pluginRows, setPluginRows] = useState<PluginRow[]>([]);
  const [bundledPlugins, setBundledPlugins] = useState<PluginRow[]>([]);
  const [pluginLoading, setPluginLoading] = useState(false);
  // W2.1 Curated Memory: rows + add/edit/delete driven by the bridge.
  const [memoryRows, setMemoryRows] = useState<MemoryRow[]>([]);
  const [memoryLoading, setMemoryLoading] = useState(false);
  // W2.2 Knowledge Base: collections + cited search driven by the bridge.
  const [knowledgeRows, setKnowledgeRows] = useState<KnowledgeRow[]>([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [knowledgeHits, setKnowledgeHits] = useState<KnowledgeHit[]>([]);
  const [searchProviders, setSearchProviders] = useState<SearchProviderChoice[]>([]);
  const [searchTestResult, setSearchTestResult] = useState<SearchTestResult | null>(null);
  const [searchTesting, setSearchTesting] = useState(false);
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [profiles, setProfiles] = useState<{ active: string; items: { id: string; name: string; prompt: string }[] }>({ active: "", items: [] });
  const [trajectory, setTrajectory] = useState<TrajectoryViewer | null>(null);

  // ------------------------------------------------- full-text chat search
  const [chatHits, setChatHits] = useState<Record<string, string>>({});

  // ------------------------------------------------------- model warm-up UI
  const [warming, setWarming] = useState(false);

  // ------------------------------------------------ command palette (Ctrl+Shift+P)
  const [paletteOpen, setPaletteOpen] = useState(false);

  // ---------------------------------------------- interactive shell session
  const [shellRunning, setShellRunning] = useState(false);
  const [shellOutput, setShellOutput] = useState("");

  // ------------------------------------------------------- project workspace
  const [workspace, setWorkspace] = useState<WorkspaceState | null>(null);
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [openFile, setOpenFile] = useState<{ path: string; content: string } | null>(null);
  const [projectSearch, setProjectSearch] = useState("");
  const [projectSearchResults, setProjectSearchResults] = useState<ProjectSearchResult>({ query: "", hits: [] });
  const [projectSearching, setProjectSearching] = useState(false);
  const [workspaceFiles, setWorkspaceFiles] = useState<string[]>([]);
  const [agentTimelineOpen, setAgentTimelineOpen] = useState(true);
  const [termHistory, setTermHistory] = useState<{ command: string; result: TerminalResult }[]>([]);
  // W3.13: per-workspace terminal history survives switching projects and back.
  const termHistoryByRootRef = useRef<Map<string, { command: string; result: TerminalResult }[]>>(new Map());
  const [pendingTerm, setPendingTerm] = useState<string | null>(null);
  const [gitStatus, setGitStatus] = useState<{ ok: boolean; content: string; error: string | null } | null>(null);
  const [gitLog, setGitLog] = useState<{ ok: boolean; content: string; error: string | null } | null>(null);

  // --------------------------------------------------------------------- ui
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(268);
  // Right workbench panel (Files/Terminal/Git) — session UI state, not config.
  const [rightPanelOpen, setRightPanelOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem("axiom.rightPanel") !== "closed";
    } catch {
      return true;
    }
  });
  // Resizable width of the same panel (§8): persisted next to the open/closed
  // flag so a restored session keeps the user's layout.
  const [rightPanelWidth, setRightPanelWidth] = useState<number>(() => {
    try {
      const saved = Number(localStorage.getItem("axiom.rightPanelWidth"));
      return clampRightPanelWidth(saved);
    } catch {
      return RIGHT_PANEL_MIN;
    }
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsSection>("general");
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [tools, setTools] = useState<ToolInfo[] | null>(null);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusReport | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [debugLog, setDebugLog] = useState<string[]>([]);
  const [draft, setDraftState] = useState(() => readComposerDraft(null));
  const draftRef = useRef(draft);
  const draftChatIdRef = useRef<string | null>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  function setDraft(value: string) {
    draftRef.current = value;
    setDraftState(value);
  }

  useEffect(() => {
    writeComposerDraft(draftChatIdRef.current, draft);
  }, [draft]);

  function switchComposerDraft(chatId: string | null) {
    writeComposerDraft(draftChatIdRef.current, draftRef.current);
    draftChatIdRef.current = chatId;
    setDraft(readComposerDraft(chatId));
  }

  function onOpenModels() {
    setModelMenuSignal((n) => n + 1);
  }

  const generatingRef = useRef(false);
  const startedAtRef = useRef(0);
  const pendingTextRef = useRef({ content: "", thinking: "" });
  const orchestrationActiveRef = useRef(false);
  const taskActiveRef = useRef(false);
  const taskScopeRef = useRef<string | null>(null);
  /** Throttles silent explorer refreshes while workers write files. */
  const lastTreeSyncRef = useRef(0);
  /** Pending flush handle for the ~30 ms streaming-text batch window. */
  const flushTimerRef = useRef<number | null>(null);
  const bootedRef = useRef(false);
  /** Tokens that cancel superseded background tasks (warm-up, chat search). */
  const warmupTokenRef = useRef(0);
  const searchSeqRef = useRef(0);
  /**
   * Monotonic generation for workspace operations (switch / clear / boot).
   * When the user flips the project quickly, in-flight `workspace_info` /
   * `workspace_tree` / `git_panel` / `recent_workspaces` responses from the
   * old project can otherwise land AFTER the new ones and silently rewind
   * the UI (the harness observed exactly that). Each operation bumps the
   * counter and refresh helpers drop their results if the counter moved on.
   */
  const workspaceSeqRef = useRef(0);

  // ---------------------------------------------------------------- toasts
  function notify(text: string, kind: Toast["kind"] = "info", sound?: UiSound) {
    const id = ++toastId;
    setToasts((list) => [...list.slice(-2), { id, text, kind }]);
    window.setTimeout(() => setToasts((list) => list.map((t) => t.id === id ? { ...t, leaving: true } : t)), 4020);
    window.setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), 4200);
    if (sound) playUiSound(sound);
    else if (kind === "ok") playUiSound("success");
    else if (kind === "error") playUiSound("error");
  }

  /**
   * Desktop toast when a real answer finishes while the window is away.
   * Best-effort: OS notifications need the Tauri notification plugin and the
   * user's permission — any failure must never disturb the session.
   */
  function notifyAnswerReady(metrics: DoneMetrics) {
    if (metrics.state !== "completed") return;
    // The user is already looking at the answer — no toast needed.
    if (document.hasFocus()) return;
    void (async () => {
      try {
        let granted = await isPermissionGranted();
        if (!granted) granted = (await requestPermission()) === "granted";
        if (granted) sendNotification({ title: "AXIOM", body: "Ответ готов" });
      } catch {
        /* notifications are optional (plugin/permission unavailable) */
      }
    })();
  }

  // ------------------------------------------------- streaming text batching
  // Chunks arrive far faster than the eye can follow; accumulate deltas and
  // flush them on a fixed ~30 ms cadence (about one paint interval at 30 fps)
  // so long answers stay smooth with a bounded re-render rate instead of one
  // state update per token.
  const STREAM_FLUSH_MS = 30;
  const flushText = useCallback(() => {
    if (flushTimerRef.current != null) {
      window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    const { content, thinking } = pendingTextRef.current;
    if (!content && !thinking) return;
    pendingTextRef.current = { content: "", thinking: "" };
    setMessages((list) =>
      updateLive(list, (m) => {
        if (thinking) m.thinking += thinking;
        if (content) m.content += content;
      }),
    );
  }, []);

  function queueText(kind: "content" | "reasoning", text: string) {
    const pending = pendingTextRef.current;
    pendingTextRef.current =
      kind === "content" ? { ...pending, content: pending.content + text } : { ...pending, thinking: pending.thinking + text };
    if (flushTimerRef.current == null) {
      flushTimerRef.current = window.setTimeout(flushText, STREAM_FLUSH_MS);
    }
  }

  // Clear any pending streaming flush when the store unmounts.
  useEffect(() => {
    return () => {
      if (flushTimerRef.current != null) window.clearTimeout(flushTimerRef.current);
    };
  }, []);

  // --------------------------------------------------------------- elapsed
  useEffect(() => {
    if (!generating) return;
    const timer = window.setInterval(() => setElapsedMs(Date.now() - startedAtRef.current), 120);
    return () => window.clearInterval(timer);
  }, [generating]);

  // ---------------------------------------------------------- live plugins
  // While the Plugins settings section is open, poll the disk so a folder the
  // user drops into ~/.axiom/plugins appears without a restart. The bridge does
  // the real discovery; we just refresh quietly (no toasts on the timer path).
  useEffect(() => {
    if (!settingsOpen || settingsSection !== "plugins") return;
    const timer = window.setInterval(() => void refreshPluginsQuietly(), 2500);
    return () => window.clearInterval(timer);
  }, [settingsOpen, settingsSection]);

  // ------------------------------------------------------------ boot probes
  function setStep(id: string, state: BootStep["state"], detail: string | null = null) {
    setBootSteps((steps) => steps.map((step) => (step.id === id ? { ...step, state, detail } : step)));
  }

  async function loadModelDetail(name: string, providerId = "ollama") {
    try {
      const detail = await request<ModelInfo | null>("model_info", { name, providerId });
      if (detail) setModelDetail(detail);
    } catch {
      setModelDetail(null);
    }
  }

  const refreshChats = useCallback(async () => {
    try {
      setChats(await request<Conversation[]>("list_chats"));
    } catch {
      /* the core may be restarting — the list stays as it is */
    }
  }, []);

  async function loadWorkspace(seq?: number) {
    const captured = seq ?? workspaceSeqRef.current;
    try {
      const state = await request<{ current: ProjectInfo | null }>("workspace_info");
      // Drop stale answers if the user switched projects while we were waiting.
      if (captured !== workspaceSeqRef.current) return state;
      setWorkspace((w) => ({
        current: state.current,
        recent: w?.recent ?? [],
        pinned: w?.pinned ?? [],
      }));
      return state;
    } catch (err) {
      notify(errorText(err), "error");
      return null;
    }
  }

  async function loadProjectList(seq?: number) {
    const captured = seq ?? workspaceSeqRef.current;
    try {
      const [recent, pinned] = await Promise.all([
        request<{ recent: ProjectInfo[] }>("recent_workspaces"),
        request<{ pinned: ProjectInfo[] }>("pinned_workspaces"),
      ]);
      if (captured !== workspaceSeqRef.current) return;
      setWorkspace((w) => ({
        current: w?.current ?? null,
        recent: recent.recent,
        pinned: pinned.pinned,
      }));
    } catch {
      /* ignore */
    }
  }

  async function toggleWorkspacePin(path: string) {
    const isPinned = await request<{ pinned: boolean }>("is_pinned", { path });
    const success = isPinned.pinned
      ? await request<boolean>("unpin_workspace", { path })
      : await request<boolean>("pin_workspace", { path });
    if (success) {
      // Update local state optimistically
      setWorkspace((w) => ({
        current: w?.current ?? null,
        recent: w?.recent?.map((p) =>
          p.path === path ? { ...p, pinned: !p.pinned } : p
        ) ?? [],
        pinned: w?.pinned?.map((p) =>
          p.path === path ? { ...p, pinned: !p.pinned } : p
        ) ?? [],
      }));
      // Refresh project list to ensure consistency
      void loadProjectList();
    }
  }

  async function loadTree(silent = false, seq?: number) {
    const captured = seq ?? workspaceSeqRef.current;
    if (!silent) setTreeLoading(true);
    try {
      const data = await request<{ tree: TreeNode[] }>("workspace_tree", { depth: 8 });
      // A workspace switch that landed while we were waiting means the tree
      // we just fetched belongs to the previous project — discard it so the
      // UI never briefly shows the old file structure for the new project.
      if (captured !== workspaceSeqRef.current) return;
      setTree(data.tree ?? []);
    } catch {
      if (captured !== workspaceSeqRef.current) return;
      setTree([]);
    } finally {
      if (!silent && captured === workspaceSeqRef.current) setTreeLoading(false);
    }
  }

  async function loadGit(seq?: number) {
    const captured = seq ?? workspaceSeqRef.current;
    try {
      const data = await request<{
        project: ProjectInfo | null;
        status: { ok: boolean; content: string; error: string | null } | null;
        log: { ok: boolean; content: string; error: string | null } | null;
      }>("git_panel");
      if (captured !== workspaceSeqRef.current) return;
      setGitStatus(data.status);
      setGitLog(data.log);
    } catch {
      if (captured !== workspaceSeqRef.current) return;
      setGitStatus(null);
      setGitLog(null);
    }
  }

  // ------------------------------------------------------ git write ops (§17)
  /** Run a user-initiated git write op and refresh the panel (never agent-driven). */
  async function gitWrite(cmd: string, args: Record<string, unknown>): Promise<boolean> {
    try {
      const res = await request<{ ok: boolean; error?: string; output?: string }>(cmd, args);
      if (!res.ok) {
        notify(res.error ?? "Операция Git не выполнена", "error");
        return false;
      }
      void loadGit();
      return true;
    } catch (err) {
      notify(errorText(err), "error");
      return false;
    }
  }

  /** Stage files (empty list = everything). */
  async function gitStage(paths: string[]): Promise<boolean> {
    return gitWrite("git_stage", { paths });
  }

  /** Unstage files (empty list = all staged). */
  async function gitUnstage(paths: string[]): Promise<boolean> {
    return gitWrite("git_unstage", { paths });
  }

  async function gitCommit(message: string, all = false): Promise<boolean> {
    const ok = await gitWrite("git_commit", { message, all });
    if (ok) notify("Коммит создан", "ok");
    return ok;
  }

  /** Snapshot the repo so later edits can be rolled back (W3.14). */
  async function gitCheckpoint(): Promise<boolean> {
    try {
      const res = await request<{ ok: boolean; ref?: string; error?: string }>("git_checkpoint", {});
      if (!res.ok) {
        notify(res.error ?? "Не удалось создать снимок", "error");
        return false;
      }
      notify("Снимок git создан", "ok");
      return true;
    } catch (err) {
      notify(errorText(err), "error");
      return false;
    }
  }

  /** Roll the repo back to the last snapshot (destructive, W3.14). */
  async function gitRollback(): Promise<boolean> {
    try {
      const res = await request<{ ok: boolean; error?: string }>("git_rollback", {});
      if (!res.ok) {
        notify(res.error ?? "Откат не выполнен", "error");
        return false;
      }
      notify("Изменения откачены к снимку", "ok");
      void loadGit();
      void loadTree();
      return true;
    } catch (err) {
      notify(errorText(err), "error");
      return false;
    }
  }

  /** Unified diff of one file ("" when there are no changes). */
  async function gitShowDiff(path: string): Promise<string | null> {
    try {
      const res = await request<{ ok: boolean; diff?: string; error?: string }>("git_diff_file", { path });
      if (!res.ok) {
        notify(res.error ?? "Не удалось получить diff", "error");
        return null;
      }
      return res.diff ?? "";
    } catch (err) {
      notify(errorText(err), "error");
      return null;
    }
  }

  /** Switch the workspace repo to an existing local branch. */
  async function switchBranch(branch: string): Promise<boolean> {
    try {
      const res = await request<{ ok: boolean; error?: string; output?: string }>("git_switch", { branch });
      if (!res.ok) {
        notify(res.error ?? `Не удалось переключиться на ${branch}`, "error");
        return false;
      }
      notify(`Ветка: ${branch}`, "ok");
      void loadGit();
      void loadWorkspace(); // the branch is shown in the project header
      return true;
    } catch (err) {
      notify(errorText(err), "error");
      return false;
    }
  }

  async function runBoot() {
    setPhase("booting");
    setBootSteps(freshSteps());
    setBootError(null);
    let current = "ui";
    
    // Искусственная задержка для демонстрации анимаций
    const bootDelay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
    
    try {
      setStep("ui", "running");
      await bootDelay(800);
      await Promise.resolve();
      setStep("ui", "ok", "AXIOM desktop");
      await bootDelay(400);

      // The local config read and the Ollama probe do not depend on each other,
      // so they run together instead of as a chain of round trips.
      setStep("detect", "running");
      await bootDelay(600);
      current = "detect";
      const [probe, cfg] = await Promise.all([
        request<HealthReport>("health"),
        request<AxiomConfig>("get_config"),
      ]);
      setHealth(probe);
      setConfig(cfg);
      setSidebarOpen(cfg.sidebar_open);
      setSidebarWidth(cfg.sidebar_width);
      if (!probe.available) {
        // API-only setups are valid: the active external route is independent
        // from Ollama. Keep booting so providers/models/workspace remain usable.
        const externalRoute = cfg.router_primary;
        if (!externalRoute || externalRoute.provider_id === "ollama") {
          setStep("detect", "failed", probe.url);
          setConnected(false);
          setBootError({
            message: "Ollama недоступна",
            hint: `AXIOM не смог подключиться к ${probe.url}`,
            url: probe.url,
          });
          setPhase("unavailable");
          return;
        }
        setStep("detect", "ok", `внешний provider: ${externalRoute.provider_id}`);
      } else {
        setStep("detect", "ok", probe.url);
      }
      await bootDelay(500);

      setStep("connect", "running");
      await bootDelay(700);
      setStep(
        "connect",
        "ok",
        probe.version
          ? `Ollama ${probe.version}`
          : probe.available
            ? "соединение установлено"
            : "режим внешнего API",
      );
      await bootDelay(450);

      // The model list and the saved history are independent as well.
      setStep("models", "running");
      await bootDelay(800);
      current = "models";
      // /api/tags can briefly answer with an empty list (or fail) while Ollama
      // is still starting / loading a model — retry before believing it.
      const chatsLoaded = refreshChats();
      let list: ModelInfo[] = [];
      let lastModelsError: string | null = null;
      for (let attempt = 0; attempt < 3 && list.length === 0; attempt += 1) {
        if (attempt > 0) await new Promise((resolve) => setTimeout(resolve, 700));
        try {
          list = await request<ModelInfo[]>("models");
          lastModelsError = null;
        } catch (err) {
          lastModelsError = errorText(err);
        }
      }
      await chatsLoaded;
      setModels(list);
      setStep(
        "models",
        "ok",
        list.length
          ? `${list.length} модел${list.length === 1 ? "ь" : "и"}`
          : lastModelsError
            ? "нет данных — повторим позже"
            : "моделей пока нет",
      );
      await bootDelay(600);

      if (list.length === 0) {
        // An empty model list is NOT an error (API providers are coming):
        // boot continues to the main screen and the list is re-probed later.
        setStep("select", "ok", "модель не выбрана");
      } else {
        setStep("select", "running");
        await bootDelay(650);
        current = "select";
        const configuredRoute = cfg.router_primary;
        const routeModel = configuredRoute
          ? list.find((m) => m.name === configuredRoute.model && (m.providerId ?? "ollama") === configuredRoute.provider_id)
          : null;
        const preferred = cfg.model ? list.find((m) => m.name === cfg.model && (m.providerId ?? "ollama") === "ollama") : null;
        const chosen = routeModel ?? preferred ?? list.find((m) => (m.providerId ?? "ollama") === "ollama") ?? list[0];
        const selected = await request<ModelInfo>("set_model", { name: chosen.name, providerId: chosen.providerId ?? "ollama" });
        setActiveModelProvider(selected.providerId ?? "ollama");
        setActiveModel(selected.name);
        setModels((known) => known.map((m) => {
          const same = m.name === selected.name && (m.providerId ?? "ollama") === (selected.providerId ?? "ollama");
          return same ? { ...m, ...selected } : m;
        }));
        void loadModelDetail(selected.name, selected.providerId ?? "ollama");
        setStep("select", "ok", selected.displayName);
        if (cfg.warmup_model && (selected.providerId ?? "ollama") === "ollama") trackWarmup(selected.name);
        if (cfg.model && !preferred) {
          notify(`Модель ${cfg.model} не найдена в Ollama — выбрана ${selected.displayName}`, "error");
        }
      }
      await bootDelay(550);

      setStep("workspace", "running");
      await bootDelay(750);
      try {
        const seq = ++workspaceSeqRef.current;
        const ws = await request<{ current: ProjectInfo | null }>("workspace_info");
        // A user-initiated switch can fire while we are still booting; in that
        // case our workspace_info answer is for the project that was active at
        // boot time and must not overwrite the user's current selection.
        if (seq !== workspaceSeqRef.current) return;
        setWorkspace((prev) => ({
          current: ws.current,
          recent: prev?.recent ?? [],
          pinned: prev?.pinned ?? [],
        }));
        setStep("workspace", "ok", ws.current ? `${ws.current.name} · ${ws.current.kind}` : "без проекта");
        void loadTree(false, seq);
        void loadGit(seq);
        // Load recent/pinned projects after boot completes to avoid blocking startup
        void loadProjectList(seq);
      } catch {
        setStep("workspace", "ok", "готово");
      }
      await bootDelay(400); // Финальная пауза перед переходом
      setConnected(true);
      setCoreLost(false);
      setPhase("ready");
      // Plugin commands surface in the palette without a settings visit (W3.1).
      void loadPluginCommands();
      // Background model warm-up: fire-and-forget, never blocks the GUI.
      void request<{ warmed: boolean; pending: boolean }>("warmup", {}).catch(() => {});
      if (list.length === 0) {
        // The list often appears seconds later (Ollama still loading a model):
        // re-probe quietly in the background and select a model if it showed up.
        window.setTimeout(() => {
          void refreshModels()
            .then((fresh) => {
              if (fresh.length === 0) return;
              const configured = cfg.router_primary;
              const preferred = configured
                ? fresh.find((m) => m.name === configured.model
                  && (m.providerId ?? "ollama") === configured.provider_id)
                : cfg.model
                  ? fresh.find((m) => m.name === cfg.model && (m.providerId ?? "ollama") === "ollama")
                  : null;
              const fallback = fresh.find((m) => (m.providerId ?? "ollama") === "ollama") ?? fresh[0];
              const chosen = preferred ?? fallback;
              void selectModel(chosen.name, chosen.providerId ?? "ollama", true);
            })
            .catch(() => {});
        }, 3000);
      }
    } catch (err) {
      setStep(current, "failed", errorText(err));
      setBootError({ message: errorText(err), hint: null, url: health?.url ?? "" });
      setPhase("error");
    }
  }

  // ------------------------------------------------------------ status text
  function applyStatus(state: string, detail: string | null) {
    setLiveState(state);
    switch (state) {
      case "thinking":
        setStatusText("Размышляет…");
        break;
      case "connecting":
        setStatusText(detail ? `Подключается к ${detail}…` : "Подключается…");
        break;
      case "searching":
        setStatusText("Ищет в интернете…");
        break;
      case "tool_call":
        setStatusText(detail ?? "Инструмент");
        break;
      case "receiving":
        setStatusText(null);
        break;
      default:
        break;
    }
  }

  function finishGeneration(metrics: DoneMetrics) {
    const wasGenerating = generatingRef.current;
    flushText();
    setMessages((list) =>
      updateLive(list, (m) => {
        m.streaming = false;
        m.metrics = metrics;
        if (metrics.state === "cancelled") {
          m.toolCalls = m.toolCalls.map((tool) =>
            tool.state === "running" ? { ...tool, state: "cancelled" as const } : tool,
          );
        }
      }),
    );
    generatingRef.current = false;
    setGenerating(false);
    setStatusText(null);
    setLiveState(metrics.state);
    setLastMetrics(metrics);
    // Each terminal state gets its own cue: a rising chime for a finished
    // answer, a low falling tone for a failure, a soft slide when the user
    // stopped it. Silence for anything else rather than a misleading sound.
    if (wasGenerating) {
      if (metrics.state === "completed") playUiSound("complete");
      else if (metrics.state === "error") playUiSound("error");
      else if (metrics.state === "cancelled") playUiSound("stopped");
    }
    notifyAnswerReady(metrics);
    void refreshChats();
  }

  // ------------------------------------------------------- streaming events
  useEffect(() => {
    const off = onCoreEvent((raw) => {
      const event = raw as CoreEvent;
      switch (event.type) {
        case "reasoning":
          setLiveState("thinking");
          queueText("reasoning", event.text);
          break;
        case "content":
          setLiveState("receiving");
          setStatusText(null);
          queueText("content", event.text);
          break;
        case "tool_call":
          setLiveState(event.name === "web_search" ? "searching" : "tool_call");
          setStatusText(toolStatusText(event.name, event.arguments ?? {}));
          setMessages((list) =>
            updateLive(list, (m) => {
              m.toolCalls.push({
                name: event.name,
                detail: toolTarget(event.name, event.arguments ?? {}),
                state: "running",
                args: capToolArgs(event.arguments ?? {}),
              });
            }),
          );
          break;
        case "tool_result":
          setMessages((list) =>
            updateLive(list, (m) => {
              const call = [...m.toolCalls]
                .reverse()
                .find((tool) => tool.name === event.name && tool.state === "running");
              if (call) {
                call.state = event.ok ? "ok" : "failed";
                call.durationMs = event.durationMs;
                call.error = event.error;
                if (typeof event.content === "string" && event.content) call.output = event.content.slice(0, 16_000);
              }
              // W3.4: a validated artifact from render_artifact attaches to the
              // assistant message and renders inline (never as a plain string).
              if (event.name === "render_artifact" && event.ok && event.data?.artifact) {
                if (!m.artifacts) m.artifacts = [];
                m.artifacts.push(event.data.artifact as Artifact);
              }
            }),
          );
          break;
        case "search_result":
          setMessages((list) =>
            updateLive(list, (m) => {
              m.sources = event.sources;
            }),
          );
          break;
        case "status":
          applyStatus(event.state, event.detail);
          break;
        case "orchestration": {
          // Live /orchestrate progress: real trajectory steps streamed while
          // the workers run (the final report replaces this message later).
          if (!generatingRef.current || !orchestrationActiveRef.current) break;
          // A worker really created/edited a file — mirror it into the
          // explorer immediately (throttled + silent, no spinner flicker),
          // otherwise new files only appear after a core/app restart.
          if (
            event.kind === "subagent.tool.result" &&
            /^(write_file|edit_file|create_directory)\b/.test(event.summary) &&
            !event.summary.includes("failed") &&
            Date.now() - lastTreeSyncRef.current > 2500
          ) {
            lastTreeSyncRef.current = Date.now();
            void loadTree(true);
          }
          const progress = orchestrationProgress(event);
          if (progress) setStatusText(progress);
          // The board is the primary rendering: every step is reduced into the
          // typed state instead of being appended to the message text.
          setMessages((list) =>
            updateLive(list, (m) => {
              if (!m.orchestration) return;
              m.orchestration = applyOrchestrationEvent(m.orchestration, event);
            }),
          );
          break;
        }
        case "task": {
          if (event.task.scope !== taskScopeRef.current) break;
          const last = latestTaskEventRef.current;
          if (last?.id === event.task.id && last.revision > event.task.revision) break;
          latestTaskEventRef.current = event.task;
          const wasActive = taskActiveRef.current;
          setTasks((list) => {
            const existing = list.find((task) => task.id === event.task.id);
            if (existing && existing.revision > event.task.revision) return list;
            return [event.task, ...list.filter((task) => task.id !== event.task.id)];
          });
          if (wasActive) {
            setActiveTaskId(event.task_id);
            if (event.kind === "task.started" || event.kind === "task.resumed") setFocusedTaskId(event.task_id);
            const labels: Record<Task["state"], string> = {
              pending: "готова к запуску",
              analyzing: "анализирует проект",
              planning: "составляет план",
              executing: "выполняет шаг",
              waiting_for_permission: "ожидает разрешения",
              verifying: "проверяет результат",
              waiting_for_user: "требует решения",
              completed: "завершена",
              failed: "завершилась с ошибкой",
              cancelled: "остановлена",
            };
            const detail = event.task.detail?.trim();
            setStatusText(`Задача: ${labels[event.task.state] ?? event.task.state}${detail ? ` · ${detail.slice(0, 120)}` : ""}`);
          }
          const terminal = ["completed", "failed", "cancelled", "waiting_for_user"].includes(event.task.state);
          if (terminal && wasActive) {
            taskActiveRef.current = false;
            generatingRef.current = false;
            setGenerating(false);
            setTaskRequestPending(false);
            setActiveTaskId(null);
            setStatusText(null);
            setLiveState("idle");
            void loadTree();
            void loadGit();
          }
          // W3.3: a background task finishing while the user is elsewhere gets
          // a real completion notification. The state comes straight from the
          // task event, so the toast never fabricates a result.
          if (terminal && !wasActive) {
            const title = event.task.goal?.trim();
            const labels: Partial<Record<Task["state"], string>> = {
              completed: "завершена",
              failed: "завершилась с ошибкой",
              cancelled: "остановлена",
              waiting_for_user: "требует решения",
            };
            notify(
              `Фоновая задача${title ? ` «${title.slice(0, 60)}»` : ""} — ${labels[event.task.state] ?? event.task.state}`,
              event.task.state === "completed" ? "ok" : "error",
            );
          }
          break;
        }
        case "permission_request":
          // W2.4: the blocked tool call waits for a real answer from this dialog.
          setPendingPermission(event);
          setStatusText(`Ожидает разрешения: ${event.tool}`);
          // A distinct nudge: the run is blocked until the user decides.
          playUiSound("permission");
          break;
        case "error":
          setMessages((list) =>
            updateLive(list, (m) => {
              m.error = { message: event.message, hint: event.hint };
            }),
          );
          setStatusText(null);
          break;
        case "done":
          finishGeneration(event as DoneMetrics);
          break;
      }
    });
    return off;
  }, [flushText, refreshChats]);

  // ---------------------------------------------------------- generation API
  function beginGeneration() {
    generatingRef.current = true;
    startedAtRef.current = Date.now();
    pendingTextRef.current = { content: "", thinking: "" };
    setElapsedMs(0);
    setGenerating(true);
    setLiveState("connecting");
    setStatusText("Подключается…");
  }

  function failGeneration(err: unknown) {
    flushText();
    setMessages((list) =>
      updateLive(list, (m) => {
        m.streaming = false;
        m.error = { message: errorText(err), hint: null };
        m.toolCalls = m.toolCalls.map((tool) =>
          tool.state === "running" ? { ...tool, state: "cancelled" as const } : tool,
        );
      }),
    );
    generatingRef.current = false;
    setGenerating(false);
    setStatusText(null);
    setLiveState("error");
    setPendingPermission(null);
    const text = errorText(err);
    if (/ядро остановлено/i.test(text)) setCoreLost(true);
    notify(text, "error");
    void refreshChats();
  }

  /** Run a real turn through the bridge and follow its event stream. */
  async function streamTurn(cmd: string, args: Record<string, unknown>, before?: () => void) {
    beginGeneration();
    before?.();
    try {
      const result = await request<SendResult>(cmd, args);
      if (result?.conversation) {
        const conversation = result.conversation;
        if (activeChatId !== conversation.id) switchComposerDraft(conversation.id);
        setActiveChatId(conversation.id);
        setChats((list) => [conversation, ...list.filter((c) => c.id !== conversation.id)]);
      }
      if (result?.activeModel) {
        const model = result.activeModel;
        setModels((list) => list.map((m) => (m.name === model.name ? { ...m, ...model } : m)));
      }
    } catch (err) {
      failGeneration(err);
    }
  }

  async function beginOrchestration(userMessage: LiveMessage, task: string) {
    if (generatingRef.current) {
      notify("Генерация уже идёт — сначала остановите её", "error");
      return;
    }
    if (!connected && !activeModel) {
      notify("Подключите Ollama или внешний provider", "error");
      return;
    }
    beginGeneration();
    orchestrationActiveRef.current = true;
    // «Подключается…» было бы неправдой: план и воркеры уже работают.
    setStatusText("Оркестрация: план…");
    setMessages((list) => {
      const assistant = liveAssistant();
      assistant.orchestration = emptyOrchestration(task);
      return [...list, userMessage, assistant];
    });
    try {
      const result = await request<OrchestrationResult>("orchestrate", {
        text: task,
        limit: 5,
        max_iterations: 3,
      });
      // The reply is the authority for the final board: it settles the agents,
      // fills the reports/review/verification sections and writes the compact
      // Markdown that survives a chat reload (history stores text only).
      const finalize = (patch: OrchestrationResult) => {
        setMessages((list) =>
          list.map((item) => {
            if (item.role !== "assistant" || !item.streaming) return item;
            const board = applyOrchestrationResult(
              item.orchestration ?? emptyOrchestration(task),
              patch,
            );
            return {
              ...item,
              orchestration: board,
              content: orchestrationMarkdown(board),
              streaming: false,
              createdAt: Date.now(),
            };
          }),
        );
      };
      if (result.cancelled || result.error === "cancelled") {
        // Esc / «Остановить» во время оркестрации — это не ошибка.
        finalize({ cancelled: true });
        generatingRef.current = false;
        setGenerating(false);
        setStatusText(null);
        setLiveState("idle");
        notify("Оркестрация остановлена", "info");
        return;
      }
      if (result.ok === false && result.error) {
        // Patch the error box first: `finalize` closes the streaming message,
        // and `updateLive` only ever touches the trailing streaming one.
        const message = result.error;
        setMessages((list) =>
          updateLive(list, (m) => {
            m.error = { message, hint: null };
          }),
        );
        finalize({ ok: false, error: message });
        generatingRef.current = false;
        setGenerating(false);
        setStatusText(null);
        setLiveState("error");
        notify(message, "error");
        void refreshChats();
        return;
      }
      finalize(result);
      generatingRef.current = false;
      setGenerating(false);
      setStatusText(null);
      setLiveState("idle");
      void refreshChats();
    } catch (err) {
      failGeneration(err);
    } finally {
      orchestrationActiveRef.current = false;
      // Workers may have created/edited files: refresh the explorer and the
      // git panel right away — no core/app restart needed to see them.
      void loadTree();
      void loadGit();
    }
  }

  async function send(text: string, forceSearch = false, images: string[] = []) {
    const clean = text.trim();
    const attached = (images || []).filter(Boolean);
    if (!clean && attached.length === 0) return;
    if (generatingRef.current) {
      notify("Генерация уже идёт — остановите её (Esc)", "error");
      return;
    }
    if (!connected) {
      notify("Ollama недоступна — проверьте подключение", "error");
      return;
    }
    if (forceSearch) playUiSound("search");
    const userMessage: LiveMessage = {
      id: nextUserId(),
      role: "user",
      content: clean,
      thinking: "",
      streaming: false,
      toolCalls: [],
      sources: [],
      createdAt: Date.now(),
      images: attached,
    };
    await streamTurn("send", { text: clean, forceSearch, images: attached.map(stripDataUrl) }, () => {
      setMessages((list) => [...list, userMessage, liveAssistant()]);
    });
  }

  async function cancel() {
    if (pendingPermission) {
      // Stop must not leave a tool call waiting forever — refuse it first.
      void respondPermission("deny");
    }
    if (!generatingRef.current) return;
    setStatusText("Останавливаю…");
    try {
      await request<{ cancelled: boolean }>("cancel");
    } catch {
      /* nothing was running on the backend side */
    }
  }

  /** W2.4: deliver the user's real answer to a blocked tool call. */
  async function respondPermission(decision: PermissionDecision) {
    const pending = pendingPermission;
    if (!pending) return;
    setPendingPermission(null);
    setStatusText(null);
    try {
      const res = await request<{ resolved: boolean }>("permission_respond", {
        id: pending.id,
        decision,
      });
      if (!res.resolved) notify("Запрос разрешения уже неактуален", "error");
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  async function regenerate(forceSearch = false) {
    if (generatingRef.current) {
      notify("Генерация уже идёт — остановите её (Esc)", "error");
      return;
    }
    if (!messages.some((m) => m.role === "user")) {
      notify("Нечего перегенерировать — сначала отправьте сообщение", "error");
      return;
    }
    await streamTurn("regenerate", { forceSearch }, () => {
      setMessages((list) => {
        const trimmed = [...list];
        while (trimmed.length && trimmed[trimmed.length - 1].role === "assistant") trimmed.pop();
        return [...trimmed, liveAssistant()];
      });
    });
  }

  async function continueGeneration() {
    if (generatingRef.current) {
      notify("Генерация уже идёт — остановите её (Esc)", "error");
      return;
    }
    if (!connected) {
      notify("Ollama недоступна — проверьте подключение", "error");
      return;
    }
    const hasPartial = messages.some((m) => m.role === "assistant" && m.content);
    if (!hasPartial) {
      notify("Продолжать нечего — в этом чате ещё нет ответа", "error");
      return;
    }
    // Resume in place: the backend nudges the model with the partial answer
    // (prefill-only) and new text is appended to the same assistant message.
    await streamTurn("continue_last", { forceSearch: false }, () => {
      setMessages((list) => {
        const target = [...list].reverse().find((m) => m.role === "assistant" && m.content);
        if (!target) return [...list, liveAssistant()];
        return list.map((m) =>
          m.id === target.id
            ? { ...m, streaming: true, metrics: undefined, error: undefined }
            : m,
        );
      });
    });
  }

  async function editLastUser(text: string, forceSearch = false) {
    const clean = text.trim();
    if (!clean) {
      notify("Сообщение не может быть пустым", "error");
      return;
    }
    if (generatingRef.current) {
      notify("Генерация уже идёт — остановите её (Esc)", "error");
      return;
    }
    let index = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        index = i;
        break;
      }
    }
    if (index === -1) {
      notify("Нет сообщения для правки", "error");
      return;
    }
    const images = messages[index].images ?? [];
    await streamTurn(
      "edit_message",
      { text: clean, forceSearch, images: images.map(stripDataUrl) },
      () => {
        setMessages((list) => [...list.slice(0, index), { ...list[index], content: clean }, liveAssistant()]);
      },
    );
  }

    // ------------------------------------------------------------ chat actions
  async function newChat() {
    if (generatingRef.current) void cancel();
    try {
      const conversation = await request<Conversation>("new_chat");
      switchComposerDraft(conversation.id);
      setActiveChatId(conversation.id);
    } catch {
      switchComposerDraft(null);
      setActiveChatId(null);
    }
    setMessages([]);
    setStatusText(null);
    setLiveState("idle");
    setLastMetrics(null);
    void refreshChats();
  }

  async function openChat(id: string) {
    if (generatingRef.current) void cancel();
    try {
      const conversation = await request<Conversation | null>("load_chat", { id });
      if (!conversation) {
        notify("Разговор не найден", "error");
        void refreshChats();
        return;
      }
      switchComposerDraft(id);
      setActiveChatId(id);
      setMessages(
        (conversation.messages ?? []).map((message, index) => ({
          id: `${id}-${index}`,
          role: message.role,
          content: message.content,
          thinking: message.thinking ?? "",
          streaming: false,
          toolCalls: [],
          sources: [],
          createdAt: conversation.updatedAt,
          images: Array.isArray(message.images) ? message.images.filter(Boolean) : [],
          artifacts: Array.isArray(message.artifacts) ? message.artifacts : [],
        })),
      );
      setStatusText(null);
      setLiveState("idle");
      setLastMetrics(null);
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  async function deleteChat(id: string) {
    try {
      await request("delete_chat", { id });
      if (id === activeChatId) {
        switchComposerDraft(null);
        clearComposerData(id);
        setActiveChatId(null);
        setMessages([]);
      } else {
        clearComposerData(id);
      }
      await refreshChats();
      notify("Разговор удалён");
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  /** Delete every conversation in history — one button, real core calls. */
  async function deleteAllChats() {
    const ids = chats.map((c) => c.id);
    if (ids.length === 0) return;
    const failed: string[] = [];
    for (const id of ids) {
      try {
        await request("delete_chat", { id });
      } catch {
        failed.push(id);
      }
    }
    if (activeChatId && !failed.includes(activeChatId)) {
      switchComposerDraft(null);
      clearComposerData(activeChatId);
      setActiveChatId(null);
      setMessages([]);
      setLastMetrics(null);
    }
    for (const id of ids) {
      if (!failed.includes(id) && id !== activeChatId) clearComposerData(id);
    }
    await refreshChats();
    if (failed.length > 0) {
      notify(`Не удалось удалить ${failed.length} из ${ids.length} разговоров`, "error");
    } else {
      notify(`История очищена — удалено ${ids.length}`, "ok");
    }
  }

  async function renameChat(id: string, title: string) {
    try {
      const result = await request<{ renamed: boolean }>("rename_chat", { id, title });
      if (!result.renamed) {
        notify("Не удалось переименовать разговор", "error");
        return;
      }
      setChats((list) => list.map((c) => (c.id === id ? { ...c, title: title.trim() } : c)));
      notify("Разговор переименован", "ok");
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  // --------------------------------------------- sidebar search / organisation
  /** Full-text search over stored messages (debounced by the sidebar query). */
  async function searchChats(query: string) {
    const token = ++searchSeqRef.current;
    try {
      const data = await request<{ hits: ChatHit[] }>("search_chats", { query });
      if (searchSeqRef.current !== token) return; // a newer query already won
      const map: Record<string, string> = {};
      for (const hit of data.hits ?? []) map[hit.id] = hit.snippet;
      setChatHits(map);
    } catch {
      /* the core may be restarting — the previous hits stay visible */
    }
  }

  /** Pin/unpin a chat to the top of the sidebar (persisted in history). */
  async function pinChat(id: string, pinned?: boolean) {
    const next = pinned ?? !(chats.find((c) => c.id === id)?.pinned ?? false);
    try {
      const res = await request<{ ok: boolean }>("chat_meta", { id, pin: next });
      if (!res.ok) {
        notify("Не удалось закрепить разговор", "error");
        return;
      }
      setChats((list) => list.map((c) => (c.id === id ? { ...c, pinned: next } : c)));
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  /** File a chat under a sidebar folder (null = no folder). */
  async function setChatFolder(id: string, folder: string | null) {
    try {
      const res = await request<{ ok: boolean }>("chat_meta", { id, folder });
      if (!res.ok) {
        notify("Не удалось изменить папку разговора", "error");
        return;
      }
      setChats((list) => list.map((c) => (c.id === id ? { ...c, folder } : c)));
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  // ---------------------------------------------------------- model actions
  async function refreshModels(): Promise<ModelInfo[]> {
    setModelsLoading(true);
    setModelsError(null);
    try {
      const list = await request<ModelInfo[]>("models");
      setModels(list);
      // An empty list is a normal state (API providers are coming) — never an
      // error banner; real transport failures still land in the catch below.
      // A model can disappear from Ollama while AXIOM is running: adapt for real.
      const activeExists = list.some(
        (m) => m.name === activeModel
          && (m.providerId ?? "ollama") === activeModelProvider,
      );
      if (activeModel && !activeExists) {
        const fallback = list.find((m) => (m.providerId ?? "ollama") === activeModelProvider)
          ?? list.find((m) => (m.providerId ?? "ollama") === "ollama")
          ?? list[0];
        if (fallback) {
          const fallbackProvider = fallback.providerId ?? "ollama";
          notify(`Модель ${activeProviderLabel(activeModel, activeModelProvider)} больше не доступна — выбрана ${fallback.displayName}`, "error");
          await selectModel(fallback.name, fallbackProvider);
        } else {
          setActiveModel(null);
          setActiveModelProvider("ollama");
        }
      }
      return list;
    } catch (err) {
      setModelsError(errorText(err));
      return [];
    } finally {
      setModelsLoading(false);
    }
  }

  async function selectModel(name: string, providerId: string | boolean = "ollama", silent = false): Promise<boolean> {
    if (typeof providerId === "boolean") {
      silent = providerId;
      providerId = "ollama";
    }
    if (generatingRef.current) {
      notify("Нельзя переключить модель во время генерации — остановите её (Esc)", "error");
      return false;
    }
    if (name === activeModel && providerId === activeModelProvider) return true;
    setSwitchingModel(`${providerId}/${name}`);
    try {
      const model = await request<ModelInfo>("set_model", { name, providerId });
      setActiveModel(model.name);
      setActiveModelProvider(model.providerId ?? providerId);
      setModels((list) => list.map((m) => {
        const same = m.name === model.name && (m.providerId ?? "ollama") === (model.providerId ?? "ollama");
        return same ? { ...m, ...model } : m;
      }));
      void loadModelDetail(model.name, model.providerId ?? providerId);
      if (providerId === "ollama" && config?.warmup_model) trackWarmup(name);
      if (!silent) notify(`Активная модель: ${model.displayName}`, "ok", "model");
      return true;
    } catch (err) {
      const message = errorText(err);
      setModelsError(message);
      notify(message, "error");
      return false;
    } finally {
      setSwitchingModel(null);
    }
  }

  // ------------------------------------------------------- model warm-up UI
  /** Watch the real residency of `name` (Ollama /api/ps) until the weights are in memory. */
  function trackWarmup(name: string) {
    const token = ++warmupTokenRef.current;
    setWarming(true);
    void (async () => {
      try {
        // The core warms the model in the background; `models` reports the
        // truth via /api/ps — poll until it is resident (≤5 minutes).
        for (let attempt = 0; attempt < 150; attempt += 1) {
          if (warmupTokenRef.current !== token) return;
          const list = await request<ModelInfo[]>("models");
          if (warmupTokenRef.current !== token) return;
          setModels(list);
          if (list.find((m) => m.name === name)?.loaded) return;
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      } catch {
        /* the core may be restarting — the indicator simply turns off */
      } finally {
        if (warmupTokenRef.current === token) setWarming(false);
      }
    })();
  }

  /** Apply a new Ollama URL and re-probe everything (real reconnect). */
  async function reconnect(url?: string) {
    setPhase("booting");
    setBootSteps(freshSteps());
    try {
      setStep("ui", "ok", "AXIOM desktop");
      setStep("detect", "running");
      const report = await request<StartupReport>("reconnect", url ? { url } : {});
      setHealth({ available: report.available, version: report.version, url: url ?? health?.url ?? "" });
      if (!report.available) {
        setStep("detect", "failed", url ?? health?.url ?? "");
        setConnected(false);
        setBootError({ message: report.error ?? "Ollama недоступна", hint: report.hint, url: url ?? "" });
        setPhase("unavailable");
        return;
      }
      setStep("detect", "ok", url ?? health?.url ?? "");
      setStep("connect", "ok", report.version ? `Ollama ${report.version}` : "соединение установлено");
      setModels(report.models);
      setStep(
        "models",
        "ok",
        report.models.length
          ? `${report.models.length} модел${report.models.length === 1 ? "ь" : "и"}`
          : "моделей пока нет",
      );
      if (report.selected) {
        setActiveModel(report.selected.name);
        void loadModelDetail(report.selected.name);
        setStep("select", "ok", report.selected.displayName);
      } else {
        // No selected model is not a failure — the list may fill in later.
        setStep("select", "ok", "модель не выбрана");
      }
      setConfig(await request<AxiomConfig>("get_config"));
      await refreshChats();
      setStep("workspace", "ok", "готово");
      setConnected(true);
      setCoreLost(false);
      setPhase("ready");
      notify(
        report.selected ? "Ollama подключена" : "Ollama подключена — список моделей пока пуст",
        report.selected ? "ok" : "info",
      );
    } catch (err) {
      setStep("detect", "failed", errorText(err));
      setConnected(false);
      setBootError({ message: errorText(err), hint: null, url: url ?? "" });
      setPhase("error");
    }
  }

  async function refreshTasks() {
    const seq = workspaceSeqRef.current;
    try {
      const rows = await request<Task[]>("tasks");
      if (seq !== workspaceSeqRef.current) return;
      setTasks((list) => rows.map((task) => {
        const newer = list.find((item) => item.id === task.id && item.revision > task.revision);
        return newer ?? task;
      }));
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  async function runTaskRequest(cmd: "task_launch" | "task_continue", args: Record<string, unknown>): Promise<Task | null> {
    if (generatingRef.current) {
      notify("Генерация уже идёт — сначала остановите её", "error");
      return null;
    }
    taskActiveRef.current = true;
    latestTaskEventRef.current = null;
    setFocusedTaskId(typeof args.id === "string" ? args.id : null);
    const scopeSeq = workspaceSeqRef.current;
    setTaskRequestPending(true);
    beginGeneration();
    let launched = false;
    try {
      const reply = await request<Task>(cmd, args);
      if (scopeSeq !== workspaceSeqRef.current) return null;
      // A completion event may arrive before the launch acknowledgement.
      const eventTask = latestTaskEventRef.current as Task | null;
      const task = eventTask?.id === reply.id && eventTask.revision > reply.revision ? eventTask : reply;
      setTasks((list) => [task, ...list.filter((item) => item.id !== task.id)]);
      setActiveTaskId(task.id);
      setFocusedTaskId(task.id);
      launched = !["completed", "failed", "cancelled", "waiting_for_user"].includes(task.state);
      if (!launched) {
        taskActiveRef.current = false;
        generatingRef.current = false;
        setGenerating(false);
        setStatusText(null);
        setLiveState("idle");
        setActiveTaskId(null);
      }
      return task;
    } catch (err) {
      notify(errorText(err), "error");
      return null;
    } finally {
      setTaskRequestPending(false);
      if (!launched) {
        taskActiveRef.current = false;
        generatingRef.current = false;
        setActiveTaskId(null);
        setGenerating(false);
        setStatusText(null);
        setLiveState("idle");
      }
      void loadTree();
      void loadGit();
    }
  }

  function startTask(goal: string, plan?: TaskPlan): Promise<Task | null> {
    return runTaskRequest("task_launch", { goal, plan });
  }

  function resumeTask(id: string, acknowledge = false): Promise<Task | null> {
    return runTaskRequest("task_continue", { id, acknowledge });
  }

  async function planTask(goal: string): Promise<TaskPlan | null> {
    try {
      const plan = await request<TaskPlan>("task_plan", { goal });
      return plan;
    } catch (err) {
      notify(errorText(err), "error");
      return null;
    }
  }

  async function createTask(goal: string, plan?: TaskPlan): Promise<Task | null> {
    try {
      const task = await request<Task>("task_create", { goal, plan });
      setTasks((list) => [task, ...list.filter((item) => item.id !== task.id)]);
      return task;
    } catch (err) {
      notify(errorText(err), "error");
      return null;
    }
  }

  async function saveTask(
    id: string,
    updates: { goal?: string; plan?: TaskPlan; state?: string },
  ): Promise<Task | null> {
    try {
      const task = await request<Task>("task_save", { id, ...updates });
      if (task) {
        setTasks((list) => list.map((item) => (item.id === task.id ? task : item)));
      }
      return task;
    } catch (err) {
      notify(errorText(err), "error");
      return null;
    }
  }

  async function deleteTask(id: string): Promise<boolean> {
    try {
      const result = await request<{ deleted: boolean }>("task_delete", { id });
      if (result.deleted) {
        setTasks((list) => list.filter((item) => item.id !== id));
        setFocusedTaskId((current) => current === id ? null : current);
      }
      return result.deleted;
    } catch (err) {
      notify(errorText(err), "error");
      return false;
    }
  }

  async function reviewTask(id: string, decision: "accept" | "reject"): Promise<Task | null> {
    try {
      const task = await request<Task>("task_review", { id, decision });
      setTasks((list) => [task, ...list.filter((item) => item.id !== task.id)]);
      void loadTree();
      void loadGit();
      return task;
    } catch (err) {
      notify(errorText(err), "error");
      await refreshTasks();
      void loadTree();
      void loadGit();
      return null;
    }
  }

  async function recoverReview(id: string): Promise<Task | null> {
    try {
      const task = await request<Task>("task_recover_review", { id });
      setTasks((list) => [task, ...list.filter((item) => item.id !== task.id)]);
      void loadTree();
      void loadGit();
      notify("Восстановление ревью завершено; решение по задаче можно принять заново", "ok");
      return task;
    } catch (err) {
      notify(errorText(err), "error");
      await refreshTasks();
      void loadTree();
      void loadGit();
      return null;
    }
  }

  async function cancelTask(id: string): Promise<boolean> {
    try {
      const result = await request<{ cancelled: boolean }>("task_cancel", { id });
      await refreshTasks();
      return result.cancelled;
    } catch (err) {
      notify(errorText(err), "error");
      return false;
    }
  }

  // ---------------------------------------------------------------- config
  async function saveConfig(patch: Partial<AxiomConfig>): Promise<boolean> {
    try {
      const next = await request<AxiomConfig>("set_config", { patch });
      setConfig(next);
      setSidebarOpen(next.sidebar_open);
      setSidebarWidth(next.sidebar_width);
      return true;
    } catch (err) {
      notify(errorText(err), "error");
      return false;
    }
  }

  function toggleSidebar() {
    playUiSound("panel");
    const next = !sidebarOpen;
    setSidebarOpen(next);
    if (config) void saveConfig({ sidebar_open: next });
  }

  function toggleRightPanel() {
    playUiSound("panel");
    setRightPanelOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("axiom.rightPanel", next ? "open" : "closed");
      } catch {
        /* storage unavailable — session-only state */
      }
      return next;
    });
  }

  function commitRightPanelWidth(width: number) {
    width = clampRightPanelWidth(width);
    setRightPanelWidth(width);
    try {
      localStorage.setItem("axiom.rightPanelWidth", String(width));
    } catch {
      /* storage unavailable — session-only state */
    }
  }

  function commitSidebarWidth(width: number) {
    setSidebarWidth(width);
    if (config && config.sidebar_width !== width) void saveConfig({ sidebar_width: width });
  }

  // --------------------------------------------------------------------- ui
  function openSettings(section: SettingsSection = "general") {
    playUiSound("settings");
    setSettingsSection(section);
    setSettingsOpen(true);
  }

  function openOverlay(next: Overlay) {
    if (next) playUiSound("panel");
    setOverlay(next);
    if (next === "tools") void loadTools();
    if (next === "status") void loadStatus();
  }

  async function loadTools() {
    setToolsError(null);
    try {
      setTools(await request<ToolInfo[]>("tools"));
    } catch (err) {
      setToolsError(errorText(err));
    }
  }

  async function loadStatus() {
    setStatusError(null);
    try {
      setStatus(await request<StatusReport>("status"));
    } catch (err) {
      setStatusError(errorText(err));
    }
  }

  async function loadProviders() {
    setProviderLoading(true);
    try {
      setProviderRows(await request<ProviderRow[]>("providers"));
    } catch (err) { notify(errorText(err), "error"); }
    finally { setProviderLoading(false); }
  }

  async function loadPlugins() {
    setPluginLoading(true);
    try {
      // discover_plugins is a live reload: it registers folders the user copied
      // into ~/.axiom/plugins while the app was running (no restart needed),
      // then returns the full, current plugin list.
      const result = await request<{ discovered: string[]; plugins: PluginRow[] }>("discover_plugins");
      setPluginRows(result.plugins);
      for (const name of result.discovered) notify(`Найден плагин: ${name}`, "ok");
      // Built-in catalogue: plugins shipped with AXIOM, not installed yet.
      setBundledPlugins(await request<PluginRow[]>("bundled_plugins"));
      void loadPluginCommands();
    } catch (err) { notify(errorText(err), "error"); }
    finally { setPluginLoading(false); }
  }

  /** Install a built-in AXIOM plugin from the bundled catalogue (one click). */
  async function installBundledPlugin(name: string): Promise<PluginInstallResult | null> {
    setPluginLoading(true);
    try {
      const result = await request<PluginInstallResult>("install_bundled_plugin", { name });
      setPluginRows((rows) => [
        ...rows.filter((row) => row.name !== result.manifest.name),
        result.manifest,
      ]);
      setBundledPlugins((rows) => rows.filter((row) => row.name !== name));
      notify(`Встроенный плагин «${name}» установлен`, "ok");
      return result;
    } catch (err) {
      notify(errorText(err), "error");
      return null;
    } finally { setPluginLoading(false); }
  }

  /** Quietly refresh plugins from disk (no toasts, no spinner) — used by polling. */
  async function refreshPluginsQuietly() {
    try {
      const result = await request<{ discovered: string[]; plugins: PluginRow[] }>("discover_plugins");
      setPluginRows(result.plugins);
      for (const name of result.discovered) notify(`Найден плагин: ${name}`, "ok");
    } catch {
      // A transient bridge error must not spam the UI during background polling.
    }
  }

  /** Load plugin-contributed commands (W3.1) into the shared palette registry. */
  async function loadPluginCommands() {
    try {
      const commands = await request<{ plugin: string; id: string; title: string }[]>("plugin_commands");
      setPluginCommands(commands);
    } catch {
      // No palette breakage on a transient bridge error.
    }
  }

  // -------------------------------------------------------- curated memory (W2.1)

  async function loadMemory() {
    setMemoryLoading(true);
    try {
      setMemoryRows(await request<MemoryRow[]>("memory_list"));
    } catch (err) { notify(errorText(err), "error"); }
    finally { setMemoryLoading(false); }
  }

  async function addMemory(content: string, category: string, scope: string): Promise<boolean> {
    try {
      await request<{ id: string }>("memory_add", { content, category, scope });
      await loadMemory();
      notify("Запись сохранена в память", "ok");
      return true;
    } catch (err) { notify(errorText(err), "error"); return false; }
  }

  async function editMemory(id: string, content: string): Promise<boolean> {
    try {
      await request<{ id: string }>("memory_edit", { id, content });
      await loadMemory();
      notify("Запись обновлена", "ok");
      return true;
    } catch (err) { notify(errorText(err), "error"); return false; }
  }

  async function deleteMemory(id: string): Promise<boolean> {
    try {
      const result = await request<{ removed: boolean }>("memory_delete", { id });
      if (!result.removed) { notify("Запись не найдена", "error"); return false; }
      await loadMemory();
      notify("Запись удалена из памяти", "ok");
      return true;
    } catch (err) { notify(errorText(err), "error"); return false; }
  }

  // ------------------------------------------------------ knowledge base (W2.2)

  async function loadKnowledge() {
    setKnowledgeLoading(true);
    try {
      setKnowledgeRows(await request<KnowledgeRow[]>("knowledge_list"));
    } catch (err) { notify(errorText(err), "error"); }
    finally { setKnowledgeLoading(false); }
  }

  async function addKnowledgeCollection(name: string, path: string): Promise<boolean> {
    setKnowledgeLoading(true);
    try {
      const result = await request<KnowledgeIndexResult>("knowledge_add", { name, path });
      await loadKnowledge();
      const stats = result.stats;
      notify(
        `Проиндексировано «${name}»: ${stats?.indexed ?? 0} новых/изменённых, ` +
        `${stats?.unchanged ?? 0} без изменений`,
        "ok",
      );
      return true;
    } catch (err) { notify(errorText(err), "error"); return false; }
    finally { setKnowledgeLoading(false); }
  }

  async function reindexKnowledge(name: string): Promise<boolean> {
    setKnowledgeLoading(true);
    try {
      await request<KnowledgeIndexResult>("knowledge_reindex", { name });
      await loadKnowledge();
      notify(`Коллекция «${name}» переиндексирована`, "ok");
      return true;
    } catch (err) { notify(errorText(err), "error"); return false; }
    finally { setKnowledgeLoading(false); }
  }

  async function removeKnowledgeCollection(name: string): Promise<boolean> {
    try {
      const result = await request<{ removed: boolean }>("knowledge_remove", { name });
      if (!result.removed) { notify("Коллекция не найдена", "error"); return false; }
      await loadKnowledge();
      notify(`Коллекция «${name}» удалена`, "ok");
      return true;
    } catch (err) { notify(errorText(err), "error"); return false; }
  }

  async function searchKnowledge(query: string): Promise<KnowledgeHit[]> {
    if (query.trim()) playUiSound("search");
    try {
      const hits = await request<KnowledgeHit[]>("knowledge_search", { query });
      setKnowledgeHits(hits);
      return hits;
    } catch (err) { notify(errorText(err), "error"); return []; }
  }

  async function choosePluginFolder(): Promise<string | null> {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<string | null>("pick_folder");
  }

  async function installPluginFromFolder(path?: string): Promise<PluginInstallResult | null> {
    setPluginLoading(true);
    try {
      const selected = path || await choosePluginFolder();
      if (!selected) return null;
      const result = await request<PluginInstallResult>("install_plugin", { path: selected });
      setPluginRows((rows) => [
        ...rows.filter((row) => row.name !== result.manifest.name),
        result.manifest,
      ]);
      notify(`${result.name}: ${result.status === "updated" ? "обновлён" : "установлен"}`, "ok");
      return result;
    } catch (err) {
      notify(errorText(err), "error");
      return null;
    } finally { setPluginLoading(false); }
  }

  async function togglePlugin(name: string, enabled: boolean): Promise<PluginRow | null> {
    try {
      const result = await request<{ name: string; enabled: boolean; ok: boolean }>("toggle_plugin", { name, enabled });
      if (!result.ok) throw new Error(`Плагин «${name}» не найден`);
      setPluginRows((rows) => rows.map((row) => row.name === name ? { ...row, enabled: result.enabled } : row));
      notify(`${name}: ${result.enabled ? "включён" : "выключен"}`, "ok");
      return pluginRows.find((row) => row.name === name)
        ? { ...pluginRows.find((row) => row.name === name)!, enabled: result.enabled }
        : null;
    } catch (err) {
      notify(errorText(err), "error");
      return null;
    }
  }

  async function removePlugin(name: string): Promise<boolean> {
    try {
      const result = await request<{ name: string; removed: boolean }>("remove_plugin", { name });
      if (!result.removed) throw new Error(`Плагин «${name}» не найден`);
      setPluginRows((rows) => rows.filter((row) => row.name !== name));
      // A removed bundled plugin becomes available in the catalogue again.
      setBundledPlugins(await request<PluginRow[]>("bundled_plugins"));
      notify(`${name}: удалён`, "ok");
      return true;
    } catch (err) {
      notify(errorText(err), "error");
      return false;
    }
  }
  async function providerTest(id: string) { try { const status = await request<string>("provider_test", { provider_id: id }); notify(`${id}: ${status}`, status === "error" ? "error" : "ok"); await loadProviders(); } catch (err) { notify(errorText(err), "error"); } }
  async function providerSaveSettings(id: string, apiKey: string, baseUrl: string) {
    try {
      if (apiKey) await request("provider_set_key", { provider_id: id, api_key: apiKey });
      if (baseUrl) await request("provider_set_base_url", { provider_id: id, base_url: baseUrl });
      await request("provider_test", { provider_id: id });
      await loadProviders();
      await providerDiscover(id);
    } catch (err) {
      notify(errorText(err), "error");
    }
  }
  async function providerDiscover(id: string) { setProviderLoading(true); try { setProviderModels(await request<ProviderModelRow[]>("provider_discover", { provider_id: id }));  } catch (err) { notify(errorText(err), "error"); } finally { setProviderLoading(false); } }
  async function providerPickModel(providerId: string, model: string) {
    const selected = await selectModel(model, providerId, true);
    if (!selected) return;
    await refreshModels();
    notify(`Маршрут: ${providerId}/${model}`, "ok", "model");
  }
  async function loadHarness() { try { setAgents(await request<AgentRow[]>("agents")); setProfiles(await request<{ active: string; items: { id: string; name: string; prompt: string }[] }>("profiles")); setTrajectory(await request<TrajectoryViewer>("trajectory")); } catch (err) { notify(errorText(err), "error"); } }

  // ------------------------------------------------------------ search test
  async function loadSearchProviders() {
    try {
      setSearchProviders(await request<SearchProviderChoice[]>("search_providers"));
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  /** Run a real search probe (W1.2): honest Online/Offline, latency and errors. */
  async function runSearchTest(query: string): Promise<SearchTestResult | null> {
    if (query.trim()) playUiSound("search");
    setSearchTesting(true);
    try {
      const report = await request<SearchTestResult>("search_test", { query });
      setSearchTestResult(report);
      return report;
    } catch (err) {
      const failed: SearchTestResult = {
        ok: false,
        provider: "",
        latency_ms: 0,
        result_count: 0,
        results: [],
        error: errorText(err),
        hint: null,
      };
      setSearchTestResult(failed);
      return failed;
    } finally {
      setSearchTesting(false);
    }
  }

  function focusComposer() {
    composerRef.current?.focus();
  }

  function focusChatSearch() {
    setSidebarOpen(true);
    window.setTimeout(() => document.getElementById("chat-search")?.focus(), 90);
  }

  // ---------------------------------------------------------- slash commands
  /** Runs a slash command. Returns true when the input was consumed by one. */
  async function runCommand(input: string): Promise<boolean> {
    const { name, args } = parseCommand(input);
    // W3.1: a plugin-contributed command is routed to the plugin host — it is
    // never hardcoded into the switch below (no host change per plugin).
    const pluginCommand = pluginCommandById(name.replace(/^\//, ""));
    if (pluginCommand) {
      try {
        const res = await request<{ ok: boolean; data?: unknown; error?: string | null }>("plugin_host", {
          id: Date.now().toString(36),
          plugin: pluginCommand.plugin,
          method: "ui.command",
          params: { command: pluginCommand.id },
        });
        notify(
          res.ok ? `Команда «${pluginCommand.title}» выполнена` : `Ошибка команды: ${res.error ?? "не выполнена"}`,
          res.ok ? "ok" : "error",
        );
      } catch (err) {
        notify(errorText(err), "error");
      }
      return true;
    }
    const command = commandByName(name);
    if (!command) return false;
    switch (command.name) {
      case "/help":
        openOverlay("help");
        return true;
      case "/new":
      case "/clear":
        await newChat();
        notify("Новый разговор");
        return true;
      case "/history":
        focusChatSearch();
        return true;
      case "/models":
        setModelMenuSignal((n) => n + 1);
        return true;
      case "/model": {
        if (!args) {
          setModelMenuSignal((n) => n + 1);
          return true;
        }
        const match = resolveModel(models, args);
        if (!match) {
          notify(`Модель «${args}» не найдена в Ollama или среди подключённых провайдеров`, "error");
          return true;
        }
        await selectModel(match.name, match.providerId ?? "ollama");
        return true;
      }
      case "/context":
        openOverlay("context");
        return true;
      case "/tools":
        openOverlay("tools");
        return true;
      case "/status":
        openOverlay("status");
        return true;
      case "/settings":
        openSettings("general");
        return true;
      case "/providers":
        openSettings("providers");
        await loadProviders();
        return true;
      case "/plugins":
        openSettings("plugins");
        await loadPlugins();
        return true;
      case "/memory":
        openSettings("memory");
        await loadMemory();
        return true;
      case "/knowledge":
        openSettings("knowledge");
        await loadKnowledge();
        return true;
      case "/permissions":
        openSettings("tools");
        return true;
      case "/profiles":
        openOverlay("harness");
        await loadHarness();
        return true;
      case "/trajectory":
        openOverlay("harness");
        await loadHarness();
        return true;
      case "/agents":
        openOverlay("harness");
        await loadHarness();
        return true;
      case "/orchestrate": {
        if (!args) {
          notify("Опишите задачу: /orchestrate <задача>", "error");
          return true;
        }
        const userMessage: LiveMessage = {
          id: nextUserId(), role: "user", content: `/orchestrate ${args}`,
          thinking: "", streaming: false, toolCalls: [], sources: [], createdAt: Date.now(),
        };
        await beginOrchestration(userMessage, args);
        return true;
      }
      case "/search": {
        if (!args) {
          notify("Укажите запрос: /search <запрос>", "error");
          return true;
        }
        await send(args, true);
        return true;
      }
      case "/exit":
        await quitApp();
        return true;
      case "/workspace":
        await loadWorkspace();
        return true;
      default:
        return false;
    }
  }

  // ---------------------------------------------------------------- effects
  useEffect(() => {
    if (bootedRef.current) return;
    bootedRef.current = true;
    void runBoot();
  }, []);

  useEffect(() => {
    taskScopeRef.current = workspace?.current?.path ?? null;
    setFocusedTaskId(null);
    latestTaskEventRef.current = null;
    setTasks([]);
    if (phase === "ready") void refreshTasks();
  }, [workspace?.current?.path, phase]);

  useEffect(
    () =>
      onCoreExit(() => {
        generatingRef.current = false;
        setGenerating(false);
        setConnected(false);
        setCoreLost(true);
        setStatusText(null);
        setBootError({
          message: "Ядро AXIOM остановлено",
          hint: "Перезапустите ядро кнопкой ниже или перезапустите приложение.",
          url: "",
        });
        setPhase("error");
      }),
    [],
  );

  useEffect(
    () =>
      onCoreStderr((text) => {
        const clean = text.replace(/\s+$/, "");
        if (!clean) return;
        setDebugLog((log) => [...log.slice(-199), clean]);
      }),
    [],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase();
      if (e.ctrlKey || e.metaKey) {
        if (key === "n") {
          e.preventDefault();
          void newChat();
        } else if (key === "b") {
          e.preventDefault();
          toggleSidebar();
        } else if (key === "k") {
          e.preventDefault();
          focusChatSearch();
        } else if (key === ",") {
          e.preventDefault();
          openSettings("general");
        } else if (key === "/") {
          e.preventDefault();
          focusComposer();
        }
        return;
      }
      if (e.key === "Escape") {
        if (overlay) {
          setOverlay(null);
          return;
        }
        if (settingsOpen) {
          setSettingsOpen(false);
          return;
        }
        if (generatingRef.current) {
          e.preventDefault();
          void cancel();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  /** Restart the Python core and re-run the whole boot probe. */
  async function restartCoreAndBoot() {
    notify("Перезапуск ядра AXIOM…");
    try {
      await restartCore();
      await new Promise((resolve) => window.setTimeout(resolve, 900));
      await runBoot();
      notify("Ядро перезапущено", "ok");
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  async function switchWorkspace(path: string) {
    if (generatingRef.current) {
      notify("Сначала остановите генерацию", "error");
      return;
    }
    if (taskActiveRef.current) {
      notify("Сначала остановите задачу", "error");
      return;
    }
    // Bump the workspace generation BEFORE the round-trip so any in-flight
    // loadTree / loadGit / loadWorkspace / loadProjectList from the previous
    // project can no longer apply their results once we settle on the new one.
    const seq = ++workspaceSeqRef.current;
    // Optimistically clear UI artifacts from the previous project so the user
    // sees the switch immediately instead of a brief overlap with the old tree.
    // Keep the previous `current` until the backend confirms the new project —
    // an extra optimistic `current: null` here caused React to briefly render
    // the selector with the wrong label before the second update landed.
    setOpenFile(null);
    const prevRoot = workspace?.current?.path;
    if (prevRoot) termHistoryByRootRef.current.set(prevRoot, termHistory);
    setTermHistory(termHistoryByRootRef.current.get(path) ?? []);
    setPendingTerm(null);
    setTree([]);
    setTreeLoading(true);
    setGitStatus(null);
    setGitLog(null);
    try {
      const info = await request<ProjectInfo>("set_workspace", { path });
      // Drop the response if another switch raced ahead while we awaited it.
      if (seq !== workspaceSeqRef.current) return;
      // Apply the new project immediately: a single, authoritative setState
      // update is less prone to React 18 commit interleaving than an optimistic
      // `current: null` followed by a second update (the harness observed the
      // latter briefly leaving the DOM showing "Global Chat").
      setWorkspace((w) => ({
        ...(w ?? { recent: [], pinned: [] }),
        current: info,
      }));
      await Promise.all([
        loadWorkspace(seq),
        loadTree(false, seq),
        loadGit(seq),
        refreshChats(),
        loadProjectList(seq),
      ]);
      if (seq !== workspaceSeqRef.current) return;
      setTreeLoading(false);
      await newChat();
      notify(`Проект: ${info.name} (${info.kind})`, "ok");
    } catch (err) {
      setTreeLoading(false);
      notify(errorText(err), "error");
    }
  }

  useEffect(() => {
    if (!workspace?.current) {
      setWorkspaceFiles([]);
      return;
    }
    let active = true;
    void request<WorkspaceFilesResult>("workspace_files", {})
      .then((result) => { if (active) setWorkspaceFiles(result.files); })
      .catch(() => { if (active) setWorkspaceFiles([]); });
    return () => { active = false; };
  }, [workspace?.current?.path]);

  useEffect(() => {
    const query = projectSearch.trim();
    if (!query || !workspace?.current) {
      setProjectSearchResults({ query, hits: [] });
      return;
    }
    setProjectSearching(true);
    const timer = window.setTimeout(() => {
      void request<ProjectSearchResult>("project_search", { query })
        .then((result) => setProjectSearchResults(result))
        .catch(() => setProjectSearchResults({ query, hits: [], error: "Не удалось выполнить поиск по проекту" }))
        .finally(() => setProjectSearching(false));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [projectSearch, workspace?.current?.path]);

  async function openWorkspaceDialog() {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const picked = await invoke<string | null>("pick_folder");
      if (picked) await switchWorkspace(picked);
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  /** Global Chat: drop the active project — no file/terminal tools, global history. */
  async function clearWorkspace() {
    if (generatingRef.current) {
      notify("Сначала остановите генерацию", "error");
      return;
    }
    if (taskActiveRef.current) {
      notify("Сначала остановите задачу", "error");
      return;
    }
    // Bump the generation first so any pending tree/git load from the project
    // being cleared can no longer overwrite the empty state we set locally.
    const seq = ++workspaceSeqRef.current;
    // The user's own action is authoritative and is applied IMMEDIATELY.
    // The generation guard exists to stop *stale background loads* from landing
    // on top of the new workspace — it must never swallow the update the user
    // just asked for. Applying it up front also means the UI drops the project
    // instantly instead of after the backend round-trip.
    setOpenFile(null);
    const prevRoot = workspace?.current?.path;
    if (prevRoot) termHistoryByRootRef.current.set(prevRoot, termHistory);
    setTermHistory([]);
    setPendingTerm(null);
    setTree([]);
    setTreeLoading(false);
    setGitStatus(null);
    setGitLog(null);
    setWorkspace((w) => ({
      ...(w ?? { recent: [], pinned: [] }),
      current: null,
    }));
    try {
      await request("clear_workspace");
      // Follow the backend as the single source of truth for the cleared scope.
      if (seq === workspaceSeqRef.current) setConfig(await request<AxiomConfig>("get_config"));
      await Promise.all([loadWorkspace(seq), refreshChats(), loadProjectList(seq)]);
      if (seq !== workspaceSeqRef.current) return;
      await newChat();
      notify("Глобальный чат: проект не активен", "ok");
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  async function removeWorkspace(path: string) {
    try {
      await request("remove_workspace", { path });
      // The backend store changed (recent + pinned) — refresh both the current
      // workspace and the selector lists, otherwise the removed project keeps
      // rendering from the stale `recent` state.
      await Promise.all([loadWorkspace(), loadProjectList()]);
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  async function openWorkspaceFile(path: string) {
    const captured = workspaceSeqRef.current;
    try {
      const data = await request<{ ok: boolean; content?: string; error?: string }>("workspace_file", { path });
      if (captured !== workspaceSeqRef.current) return;
      if (!data.ok) {
        notify(data.error ?? "Не удалось прочитать файл", "error");
        return;
      }
      setOpenFile({ path, content: data.content ?? "" });
      setRightPanelOpen(true);
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  /** Apply a ```diff block from an answer to a workspace file (§17). */
  async function applyPatch(path: string, patch: string): Promise<boolean> {
    try {
      const res = await request<{ ok: boolean; error?: string; path?: string }>("apply_patch", { path, patch });
      if (!res.ok) {
        notify(res.error ?? "Не удалось применить патч", "error");
        return false;
      }
      notify(`Файл обновлён: ${res.path ?? path}`, "ok");
      if (openFile?.path === path) void openWorkspaceFile(path);
      void loadGit(); // the file may now show up as modified
      return true;
    } catch (err) {
      notify(errorText(err), "error");
      return false;
    }
  }

  async function runTerminal(command: string, confirmed = false) {
    try {
      const result = await request<TerminalResult>("run_terminal", { command, confirmed });
      if (result.permission === "ask" && !confirmed) {
        setPendingTerm(command);
        return;
      }
      setPendingTerm(null);
      setTermHistory((h) => [...h.slice(-99), { command, result }]);
      if (!result.ok && result.permission === "granted") {
        notify(result.error ?? "Команда завершилась с ошибкой", "error");
      }
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  async function confirmTerminal(allow: boolean) {
    const cmd = pendingTerm;
    setPendingTerm(null);
    if (allow && cmd) await runTerminal(cmd, true);
  }

  /** Re-run a previously executed command without re-prompting (W3.13). */
  async function rerunTerminal(command: string) {
    await runTerminal(command, true);
  }

  // ---------------------------------------------- interactive shell session
  async function startShell() {
    try {
      const res = await request<{ running: boolean; output: string }>("shell_start", {});
      setShellRunning(res.running);
      setShellOutput(res.output ?? "");
      if (!res.running) notify("Терминал не запустился", "error");
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  async function writeShell(line: string) {
    try {
      const res = await request<{ running: boolean; ok: boolean }>("shell_write", { line });
      setShellRunning(res.running);
      if (res.ok) {
        await pollShell();
      } else {
        notify("Не удалось отправить команду в терминал", "error");
      }
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  /** Drain the shell transcript (the backend returns the whole buffer). */
  async function pollShell() {
    try {
      const res = await request<{ running: boolean; output: string }>("shell_read", {});
      setShellRunning(res.running);
      setShellOutput(res.output ?? "");
    } catch {
      /* the core may be restarting — keep the last output on screen */
    }
  }

  async function stopShell() {
    try {
      const res = await request<{ running: boolean; output: string }>("shell_stop", {});
      setShellRunning(res.running);
      setShellOutput(res.output ?? "");
    } catch {
      setShellRunning(false);
    }
  }

  const accessLabel =
    config?.access_mode === "read_only" ? "R/O" : config?.access_mode === "full" ? "FULL" : "WS";
  const accessTitle =
    config?.access_mode === "read_only"
      ? "AI: только чтение файлов, без изменений и терминала"
      : config?.access_mode === "full"
        ? "AI: полный доступ (осторожно)"
        : "AI: разрешена работа внутри проекта";

  // ------------------------------------------------------------- derived state
  const activeModelInfo = useMemo(
    () => models.find((m) => m.name === activeModel
      && (m.providerId ?? "ollama") === activeModelProvider) ?? null,
    [models, activeModel, activeModelProvider],
  );

  const activeConversation = useMemo(
    () => chats.find((c) => c.id === activeChatId) ?? null,
    [chats, activeChatId],
  );

  const filteredChats = useMemo(() => {
    const query = chatSearch.trim().toLowerCase();
    if (!query) return chats;
    // Title matches first; full-text hits (by id) still show with their snippet.
    return chats.filter(
      (c) => c.title.toLowerCase().includes(query) || chatHits[c.id] !== undefined,
    );
  }, [chats, chatSearch, chatHits]);

  // Debounced full-text search while the sidebar query changes.
  useEffect(() => {
    if (!chatSearch.trim()) {
      setChatHits({});
      return;
    }
    const timer = window.setTimeout(() => void searchChats(chatSearch), 260);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatSearch]);

  const context = useMemo(() => {
    const window = modelDetail?.contextLength ?? activeModelInfo?.contextLength ?? null;
    const numCtx = modelDetail?.numCtx ?? activeModelInfo?.numCtx ?? null;
    const used = lastMetrics?.tokensIn ?? null;
    const ratio = used != null && window ? Math.min(1, used / window) : null;
    let turns = 0;
    let images = 0;
    let toolCalls = 0;
    let sources = 0;
    for (const message of messages) {
      if (message.role === "user" || message.role === "assistant") turns += 1;
      images += message.images?.length ?? 0;
      toolCalls += message.toolCalls.length;
      sources += message.sources.length;
    }
    return { window, numCtx, used, ratio, turns, images, toolCalls, sources };
  }, [messages, lastMetrics, modelDetail, activeModelInfo]);

  const canContinue = useMemo(
    () => messages.some((m) => m.role === "assistant" && m.content.length > 0),
    [messages],
  );
  const canRegenerate = useMemo(() => messages.some((m) => m.role === "user"), [messages]);

  /** A stored chat remembers its model — surface a real mismatch instead of hiding it. */
  const chatModelMismatch =
    activeConversation?.model && activeModel && activeConversation.model !== activeModel
      ? activeConversation.model
      : null;

  // ---------------------------------------------------------------- commands
  return {
    // boot
    tasks,
    taskRequestPending,
    activeTaskId,
    focusedTaskId,
    setFocusedTaskId,
    startTask,
    resumeTask,
    cancelTask,
    refreshTasks,
    planTask,
    createTask,
    saveTask,
    deleteTask,
    reviewTask,
    recoverReview,
    phase,
    bootSteps,
    bootError,
    runBoot,
    reconnect,
    restartCore: restartCoreAndBoot,
    // connection
    connected,
    health,
    coreLost,
    // models
    models,
    modelsLoading,
    modelsError,
    activeModel,
    activeModelProvider,
    activeModelInfo,
    modelDetail,
    switchingModel,
    modelMenuSignal,
    refreshModels,
    selectModel,
    // chat
    chats,
    filteredChats,
    activeChatId,
    activeConversation,
    chatSearch,
    setChatSearch,
    chatHits,
    // W2.4 tool permissions
    pendingPermission,
    respondPermission,
    pinChat,
    setChatFolder,
    applyPatch,
    gitStage,
    gitUnstage,
    gitCommit,
    gitCheckpoint,
    gitRollback,
    gitShowDiff,
    shellRunning,
    shellOutput,
    startShell,
    writeShell,
    pollShell,
    stopShell,
    warming,
    paletteOpen,
    setPaletteOpen,
    switchBranch,
    messages,
    generating,
    liveState,
    statusText,
    elapsedMs,
    lastMetrics,
    context,
    canContinue,
    canRegenerate,
    chatModelMismatch,
    draft,
    setDraft,
    onOpenModels,
    send,
    cancel,
    regenerate,
    continueGeneration,
    editLastUser,
    newChat,
    openChat,
    deleteChat,
    deleteAllChats,
    renameChat,
    // config
    config,
    saveConfig,
    providerRows,
    providerModels,
    providerLoading,
    loadProviders,
    providerTest,
    providerSaveSettings,
    providerDiscover,
    providerPickModel,
    searchProviders,
    loadSearchProviders,
    runSearchTest,
    searchTestResult,
    searchTesting,
    agents,
    profiles,
    trajectory,
    // workspace
    workspace,
    tree,
    treeLoading,
    openFile,
    setOpenFile,
    loadWorkspace,
    loadTree,
    loadGit,
    switchWorkspace,
    clearWorkspace,
    openWorkspaceDialog,
    removeWorkspace,
    toggleWorkspacePin,
    openWorkspaceFile,
    projectSearch,
    setProjectSearch,
    projectSearchResults,
    projectSearching,
    workspaceFiles,
    openProjectSearchHit: (path: string) => openWorkspaceFile(path),
    agentTimelineOpen,
    setAgentTimelineOpen,
    termHistory,
    pendingTerm,
    runTerminal,
    rerunTerminal,
    confirmTerminal,
    gitStatus,
    gitLog,
    accessLabel,
    accessTitle,
    // ui
    sidebarOpen,
    toggleSidebar,
    sidebarWidth,
    setSidebarWidth,
    commitSidebarWidth,
    rightPanelOpen,
    toggleRightPanel,
    rightPanelWidth,
    setRightPanelWidth,
    commitRightPanelWidth,
    settingsOpen,
    setSettingsOpen,
    settingsSection,
    setSettingsSection,
    openSettings,
    overlay,
    openOverlay,
    setOverlay,
    toasts,
    notify,
    tools,
    toolsError,
    status,
    statusError,
    loadTools,
    pluginRows,
    pluginLoading,
    loadPlugins,
    installPluginFromFolder,
    togglePlugin,
    removePlugin,
    bundledPlugins,
    installBundledPlugin,
    memoryRows,
    memoryLoading,
    loadMemory,
    addMemory,
    editMemory,
    deleteMemory,
    knowledgeRows,
    knowledgeLoading,
    knowledgeHits,
    loadKnowledge,
    addKnowledgeCollection,
    reindexKnowledge,
    removeKnowledgeCollection,
    searchKnowledge,
    loadStatus,
    debugLog,
    composerRef,
    runCommand,
    focusComposer,
    // helper exposed for components
    matchingCommands,
    openExternal,
  };
}

export type AxiomStore = ReturnType<typeof useAxiom>;
