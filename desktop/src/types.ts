// Shared types mirroring axiom.core.events / bridge payloads.

export type Role = "user" | "assistant" | "system" | "tool";

export type Capability = "completion" | "tools" | "thinking" | "vision";

export interface ProjectInfo {
  path: string;
  name: string;
  kind: string;
  git: boolean;
  branch: string | null;
  entries: string[];
  /** Whether this project is pinned */
  pinned?: boolean;
}

export interface ProjectManagerData {
  current: ProjectInfo | null;
  recent: ProjectInfo[];
  pinned: ProjectInfo[];
}

export interface CreateProjectOptions {
  path: string;
  name?: string;
  template?: string; // e.g., "empty", "node", "python", etc.
}

export interface ProjectSearchHit {
  path: string;
  preview: string;
}

export interface ProjectSearchResult {
  query: string;
  hits: ProjectSearchHit[];
  error?: string;
}


export interface WorkspaceFilesResult {
  files: string[];
  error?: string;
}

export interface WorkspaceState {
  current: ProjectInfo | null;
  recent: ProjectInfo[];
  pinned: ProjectInfo[];
}

export interface TreeNode {
  name: string;
  dir: boolean;
  path: string;
  children?: TreeNode[];
}

export interface TerminalResult {
  ok: boolean;
  content?: string;
  error?: string | null;
  exit_code?: number | null;
  cwd?: string | null;
  permission: "granted" | "ask" | "blocked";
  command?: string;
}

export interface ModelInfo {
  name: string;
  displayName: string;
  sizeGb: number;
  sizeBytes: number;
  parameterSize: string;
  quantization: string;
  family: string;
  capabilities: string[];
  contextLength: number | null;
  numCtx: number | null;
  /** Ollama reports the model as resident in memory (/api/ps). */
  loaded: boolean;
  providerId?: string;
  source?: "ollama" | "external";
  endpoint?: string;
}

export interface Conversation {
  id: string;
  title: string;
  model: string | null;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
  messages?: StoredMessage[];
  /** Sidebar: pinned to the top of the list. */
  pinned?: boolean;
  /** Sidebar: filed under this folder (null = no folder). */
  folder?: string | null;
}

/** One full-text search hit over stored message content. */
export interface ChatHit {
  id: string;
  title: string;
  snippet: string;
  updated_at: number;
}

export interface StoredMessage {
  role: Role;
  content: string;
  thinking?: string | null;
  name?: string | null;
  images?: string[];
}

export type Density = "compact" | "comfortable" | "spacious";
export type AccentPreset = "garnet" | "blue" | "teal" | "violet" | "slate" | "rose" | "amber";
export type ThemePreset =
  | "obsidian"
  | "light"
  | "midnight"
  | "terminal"
  | "solarized"
  | "graphite"
  | "rosewood"
  | "nord";

export interface AxiomConfig {
  ollama_url: string;
  model: string | null;
  think: boolean | "low" | "medium" | "high" | "max" | null;
  thinking_mode: "auto" | "fast" | "normal" | "deep";
  keep_alive: string;
  warmup_model: boolean;
  num_ctx: number | null;
  num_predict: number | null;
  context_messages: number;
  web_search_enabled: boolean;
  workspace_tools_enabled: boolean;
  workspace_root: string | null;
  access_mode: "read_only" | "workspace" | "full";
  terminal_enabled: boolean;
  search_provider: "auto" | "brave" | "duckduckgo" | "searxng" | "wikipedia";
  search_max_sources: number;
  search_read_sources: number;
  search_timeout: number;
  history_limit: number;
  show_reasoning: boolean;
  reasoning_expanded: boolean;
  theme: ThemePreset;
  accent: AccentPreset;
  panel_hover: boolean;
  animations: boolean;
  save_history: boolean;
  temperature: number | null;
  system_prompt: string | null;
  density: Density;
  font_size: number;
  sidebar_open: boolean;
  sidebar_width: number;
  render_markdown: boolean;
  auto_scroll: boolean;
  show_metrics: boolean;
  show_context: boolean;
  permission_mode: "ask" | "auto_approve_safe" | "auto_approve_all";
  autonomy_mode?: "plan" | "edit" | "auto" | "full" | string;
  router_enabled: boolean;
  router_budget: "performance" | "balanced" | "economy";
  router_primary: { provider_id: string; model: string } | null;
  router_fallbacks: { provider_id: string; model: string }[];
}

export interface SourceItem {
  index: number;
  title: string;
  url: string;
  snippet: string;
}

export interface DoneMetrics {
  state: string;
  durationMs: number;
  tokensOut: number | null;
  tokensIn: number | null;
  tokensPerSecond: number | null;
  /** Real time to the first streamed token (measured by the core). */
  ttftMs?: number | null;
  /** Real model load time reported by Ollama for this generation (ms). */
  loadMs?: number | null;
  stopReason?: string | null;
}

/** W2.2: one knowledge collection status row from the bridge. */
export interface KnowledgeRow {
  name: string;
  path: string;
  files: number;
  chunks: number;
  embedded: number;
  embeddings: string;
  updated_at: number;
}

/** W2.2: one cited search fragment. */
export interface KnowledgeHit {
  collection: string;
  source: string;
  start_line: number;
  end_line: number;
  score: number;
  text: string;
}

/** W2.2: result of an index/reindex run. */
export interface KnowledgeIndexResult {
  ok: boolean;
  stats?: {
    files_seen: number;
    indexed: number;
    unchanged: number;
    removed: number;
    skipped: number;
    errors: string[];
  };
  collection?: KnowledgeRow;
  error?: string;
}

/** W2.4+W4.9: an ASK tool call waiting for the user's decision in the shell. */
export type PermissionDecision =
  | "allow_once" | "allow_task" | "allow_project" | "allow_always" | "deny";

export interface PermissionRequest {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  command?: string;
  cwd: string;
  risk: string;
  reason?: string;
  autonomy?: string;
  task_id?: string;
}

export type CoreEvent =
  | { type: "reasoning"; text: string }
  | { type: "content"; text: string }
  | { type: "tool_call"; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; name: string; ok: boolean; content: string; error: string | null; durationMs: number }
  | { type: "search_result"; query: string; sources: SourceItem[] }
  | { type: "status"; state: string; detail: string | null }
  | { type: "orchestration"; kind: string; actor: string; summary: string; seq: number }
  | { type: "task"; kind: string; task_id: string; timestamp: number; task: Task }
  | ({ type: "permission_request" } & PermissionRequest)
  | { type: "error"; message: string; kind: string; hint: string | null }
  | ({ type: "done" } & DoneMetrics);

export type TaskState =
  | "pending" | "analyzing" | "planning" | "executing" | "verifying"
  | "waiting_for_permission" | "waiting_for_user" | "completed" | "failed" | "cancelled";

export interface TaskPlanStep {
  id: string;
  goal: string;
  tools: string[];
  done_when: string;
  state: "pending" | "running" | "completed" | "failed";
  result: string;
}

export interface TaskPlan {
  steps: TaskPlanStep[];
  definition_of_done: string[];
}

export interface Task {
  id: string;
  goal: string;
  state: TaskState;
  scope: string | null;
  plan: TaskPlan | null;
  plan_history: TaskPlan[];
  changed_files: string[];
  errors: {
    type: string;
    message: string;
    tool: string | null;
    command: string | null;
    exit_code: number | null;
    stdout: string;
    stderr: string;
    step_id: string | null;
  }[];
  tests: Record<string, unknown>[];
  pending_tool: Record<string, unknown> | null;
  active_processes: Record<string, unknown>[];
  commands: Record<string, unknown>[];
  file_baselines: Record<string, string | null>;
  unknown_baselines: string[];
  diffs: Record<string, string>;
  review_status: "pending" | "accepted" | "rejected";
  review_recovery?: string | null;
  review_recovery_detail?: string | null;
  review_recovery_paths?: string[];
  detail: string;
  created_at: number;
  updated_at: number;
  revision: number;
  replans: number;
  planning: boolean | null;
  /** Actual per-category context sizes vs budgets from the last task step (W4.12). */
  context_report?: {
    categories: Record<string, number>;
    budgets: Record<string, number>;
    over_budget: string[];
  } | null;
}

export type ToolState = "running" | "ok" | "failed" | "cancelled";

export interface ToolActivity {
  name: string;
  /** Human readable target: the search query, the page URL, ... */
  detail: string;
  state: ToolState;
  durationMs?: number;
  error?: string | null;
  /** Real results of a search/fetch tool, when it produced any. */
  sources?: SourceItem[];
  /** Arguments the model passed (large strings are capped for memory). */
  args?: Record<string, unknown>;
  /** Text the tool returned (capped) — drives the rich previews in chat. */
  output?: string;
}

/** Category of an orchestration step — drives the icon and the row colour. */
export type OrchestrationStepKind =
  | "read"
  | "write"
  | "search"
  | "web"
  | "fetch"
  | "terminal"
  | "git"
  | "folder"
  | "verification"
  | "other";

export type OrchestrationPhase =
  | "planning"
  | "working"
  | "review"
  | "verification"
  | "done"
  | "failed"
  | "cancelled";

export type OrchestrationAgentStatus = "pending" | "running" | "done" | "failed" | "cancelled";

/** One real tool action of a worker (`subagent.tool.call` + `.result` paired). */
export interface OrchestrationStep {
  id: string;
  actor: string;
  tool: string;
  kind: OrchestrationStepKind;
  /** What the tool worked on (path, query, URL, command). */
  target: string;
  state: ToolState;
  durationMs?: number | null;
  /** Failure text or the tool outcome, when it carried one. */
  detail?: string | null;
}

/** One worker as it appears on the board while (and after) the run. */
export interface OrchestrationAgent {
  id: string;
  label: string;
  provider: string | null;
  model: string | null;
  status: OrchestrationAgentStatus;
  task: string | null;
  /** Last streamed reasoning of this worker — replaces the previous one. */
  thought: string | null;
  /** Last streamed answer fragment of this worker. */
  answer: string | null;
  /** Last tool this worker really called (raw tool name + its target). */
  lastTool: string | null;
  lastTarget: string | null;
  toolsOk: number;
  toolsFailed: number;
  error: string | null;
}

export interface OrchestrationReview {
  verdict: "approved" | "rework" | null;
  text: string;
  issues: string[];
  requiredChanges: string[];
}

export interface OrchestrationVerification {
  ok: boolean | null;
  summary: string | null;
  error: string | null;
}

/** Final per-worker report — the real `orchestrate` reply item, keys included. */
export interface OrchestrationReport {
  agent?: string;
  content?: string;
  error?: string;
  status?: string;
  provider_id?: string;
  model?: string;
  tools_used?: number;
  tools_ok?: number;
  tools_failed?: number;
}

/** Reply of the `orchestrate` command (only the fields the UI renders). */
export interface OrchestrationResult {
  ok?: boolean;
  error?: string;
  cancelled?: boolean;
  results?: OrchestrationReport[];
  review?: string;
  approved?: boolean;
  completed?: boolean;
  verification?: { ok?: boolean; summary?: string; error?: string };
  definition_of_done?: string[];
  review_details?: { issues?: string[]; required_changes?: string[] };
  duration_ms?: number;
}

/** Everything `/orchestrate` really did — built from live trajectory events. */
export interface OrchestrationState {
  task: string;
  mode: string | null;
  phase: OrchestrationPhase;
  plannedAgents: string[];
  agents: OrchestrationAgent[];
  steps: OrchestrationStep[];
  review: OrchestrationReview | null;
  verification: OrchestrationVerification | null;
  definitionOfDone: string[];
  reports: OrchestrationReport[];
  completed: boolean | null;
  /** Real failure text of a crashed run. */
  error: string | null;
  durationMs: number | null;
  startedAt: number;
  finishedAt: number | null;
}

export interface LiveMessage {
  id: string;
  role: Role;
  content: string;
  thinking: string;
  streaming: boolean;
  error?: { message: string; hint: string | null } | null;
  toolCalls: ToolActivity[];
  sources: SourceItem[];
  metrics?: DoneMetrics | null;
  createdAt: number;
  /** Set only for `/orchestrate` runs: the structured board of the run. */
  orchestration?: OrchestrationState;
  /** Base64 images attached by the user (vision models). */
  images?: string[];
  /** Regenerated alternates of this answer (branch history, newest last). */
  alternates?: string[];
  /** Which branch is displayed (index into alternates, or -1 = current). */
  branchIndex?: number;
}

export interface HealthReport {
  available: boolean;
  version: string | null;
  url: string;
}

export interface StartupReport {
  available: boolean;
  version: string | null;
  error: string | null;
  hint: string | null;
  models: ModelInfo[];
  selected: ModelInfo | null;
  state: { state: string; model: string | null };
}

export interface StatusReport {
  state: string;
  model: string | null;
  lastMetrics: Partial<DoneMetrics>;
  ollamaUrl: string;
  version: string | null;
  activeModel: ModelInfo | null;
  historyCount: number;
  configPath: string;
  busy: boolean;
}

export interface ProviderRow {
  id: string;
  label: string;
  base_url: string;
  configured: boolean;
  status: string;
}

export interface PluginRow {
  name: string;
  version: string;
  description: string;
  author: string;
  api_version: number;
  enabled: boolean;
  capabilities: string[];
  ui_block: { scopes: string[]; extensions: { type: string; id: string; scopes: string[] }[] } | null;
  tools: string[];
  providers: string[];
  skills: string[];
  source_dir: string | null;
  bundled: boolean;
  readme: string;
}

export interface PluginInstallResult {
  name: string;
  status: "installed" | "updated";
  manifest: PluginRow;
}

/** W2.1 Curated Memory — one persisted memory item (projection of MemoryItem). */
export interface MemoryRow {
  id: string;
  scope: "global" | "project" | "conversation";
  category: "normal" | "sensitive" | "banned";
  content: string;
  tags: string[];
  updated_at: number;
}

export interface ProviderModelRow {
  id: string;
  model: string;
  provider_id: string;
  label: string;
  capabilities: string[];
  context_length: number | null;
}

export interface AgentRow {
  id: string;
  label: string;
  provider_id: string;
  model: string;
  tools: string[];
}

export interface TrajectoryEventRow {
  seq: number;
  time: string;
  actor: string;
  kind: string;
  summary: string;
}

export interface TrajectoryViewer {
  run_id: string;
  lines: TrajectoryEventRow[];
  usage: Record<string, number>;
}

export interface ToolInfo {
  name: string;
  description: string;
  permission: string;
}

export interface SearchProviderChoice {
  id: string;
  name: string;
}

export interface SearchTestResult {
  ok: boolean;
  provider: string;
  latency_ms: number;
  result_count: number;
  results: { title: string; url: string; snippet: string }[];
  error: string | null;
  hint: string | null;
}

export interface SendResult {
  state: string;
  lastMetrics: Partial<DoneMetrics>;
  conversation: Conversation;
  activeModel: ModelInfo | null;
}
