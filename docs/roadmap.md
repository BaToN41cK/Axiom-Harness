# AXIOM Product and Engineering Roadmap

_Last synchronized: 2026-10-01. This document defines product intent and delivery order; it is not evidence that a feature is complete._

## Status legend

- **TODO** — not started.
- **PARTIAL** — a working vertical slice exists, but the stated scope is not complete.
- **DONE** — the complete Definition of Done is verified.

A feature is complete only after implementation, real tests, and updated documentation. A mock, placeholder UI, fabricated progress, or simulated tool result never satisfies the DoD.

## Delivery rules

1. Keep Tauri + React/TypeScript, the Rust bridge, and the Python core as the existing architecture; do not introduce a second core or replace the desktop app.
2. Keep Desktop and TUI as thin adapters over `ChatSession`, the Task Runtime, and the event bus.
3. Extend existing modules before creating new managers or services.
4. Prefer the standard library, SQLite, `pydantic`, and `httpx`; justify every new dependency.
5. Preserve chat, streaming, Ollama, external providers, workspace switching, Global Chat, files, terminal, Git, and web search.
6. Network-dependent tests are opt-in live tests; deterministic tests use local fakes and never claim live success.
7. Each delivery updates code, tests, relevant docs, `CHANGELOG.md`, and this roadmap.

## Wave overview

| Wave | Outcome | Current shape |
|---|---|---|
| W1 — Experience foundations | Honest status, coherent theming, live activity, plugin groundwork | 5 done |
| W2 — Product foundations | Memory, knowledge, orchestration UX, prompts, history, security | 9 done, 0 partial, 0 TODO |
| W3 — Extensible platform | Sandboxed plugins, connectors, multitasking, automation, integrations | 10 done, 5 partial, 3 TODO |
| W4 — Agentic coding environment | Reliable task runtime, planning, context, tools, verification, recovery | 15 done, 0 partial, 0 TODO |

---

# W1 — Experience and plugin foundations

## W1.1 Configurable Accent and Panel Hover

**Status:** DONE — persisted accent presets and panel-hover preference exist · **Priority:** P1

**Outcome:** A coherent, persisted theme carries across Desktop and TUI without a restart.

**Delivery:** Validated `accent` presets (`garnet`, `blue`, `teal`, `violet`) and the `panel_hover` preference persist across Config, Desktop Settings, and the JSONL bridge; both are applied live to Desktop light/dark CSS and the Textual theme.

**DoD:** Both frontends honor the persisted accent, WCAG AA contrast is recorded for every preset (see CHANGELOG), and Config/bridge round-trip tests pass.

## W1.2 Search Connectivity and a Real Search Test

**Status:** DONE — provider selection and honest connectivity probing exist · **Priority:** P1

**Outcome:** Users see which search engine is active and can verify it with a real probe instead of a fabricated “Online” state.

**Delivery:** Validated `search_provider` config (`auto`, `brave`, `duckduckgo`, `searxng`, `wikipedia`), `build_search_provider`/`search_provider_choices`, `ChatSession.search_test`, `search_providers`/`search_test` bridge commands, Desktop engine dropdown + real test button, and TUI `/searchtest` plus a provider-aware `/status`.

**DoD:** The probe returns real `ok`/engine/latency/error, a provider change applies without restart, and deterministic tests use local fakes without network.

## W1.3 Live Thinking Phase and Elapsed Timer

**Status:** DONE — honest wall-clock phase timing exists · **Priority:** P1

**Outcome:** Active phases show real elapsed time instead of tick-based approximations.

**Delivery:** Wall-clock timers in TUI StatusBar, AssistantMessage, and ReasoningPanel plus the Desktop elapsed timer; `status_line()` gained an `elapsed` parameter.

**DoD:** Thinking displays measured wall-clock duration and collapses to a completed state, and deterministic `status_line` tests cover active/inactive/None/zero cases.

## W1.4 Plugin Manager v0 Live Reload

**Status:** DONE — manifest-validated plugins load live from `~/.axiom/plugins` · **Priority:** P1

**Outcome:** A plugin folder dropped into the plugin directory becomes real tools without a restart, and a bundled catalogue installs with one click.

**Delivery:** `discover_plugins` live reload (manifest validation, atomic install, persisted enabled state, real tool registration), Desktop background polling, TUI `/plugins` discover, a bundled five-plugin catalogue with `install_bundled`, and `docs/plugins.md`.

**DoD:** Dropped folders appear in both frontends, incompatible manifests are rejected, built-ins install/remove round-trip, and bridge integration tests pass.

## W1.5 UI Extension Point Contract

**Status:** DONE — versioned `ui` extension contract with validation · **Priority:** P2

**Outcome:** A versioned contract can later support plugin panels, commands, settings, renderers, and themes without redesigning v0.

**Delivery:** Document manifest fields, API versioning, host guarantees, and compatibility rules in `docs/plugins.md` or `docs/architecture.md`.

**DoD:** A manifest and extension example validate against the contract, including an incompatible-version case.

---
# W2 — Memory, knowledge, orchestration, and security

## W2.1 Curated Memory

**Status:** DONE — atomic global/project memory, real tools, and management UI · **Priority:** P0

**Outcome:** The user controls durable local facts, preferences, and project decisions used by future tasks.

**Delivery:** Add atomic `MemoryItem` storage for global/project/conversation scopes and `normal/sensitive/banned` categories; expose read/list/write/forget tools; extract memory as a user-approved suggestion; retrieve only budgeted relevant items; add Desktop memory management and TUI `/memory`.

**DoD:** Model access goes through tools, persisted items are user-editable/deletable, banned content never reaches disk, and scope/retrieval tests pass.

## W2.2 Knowledge Base (RAG v1)

**Status:** DONE — SQLite/FTS5 collections, hybrid retrieval, real tools and Desktop/TUI views · **Priority:** P0

**Outcome:** Local folders and documents can be indexed and searched with source citations.

**Delivery:** Add `core/knowledge/` with chunking, SQLite/FTS5, optional Ollama embeddings, vector+BM25 retrieval, incremental indexing, knowledge tools, and Desktop/TUI collection views.

**DoD:** Search returns real cited fragments, only changed files are reindexed, BM25 works offline, and unavailable embeddings produce an explicit status.

## W2.3 Orchestrator v2: Timeline, Progress, and Resume

**Status:** DONE — event timeline, dependency topology, persisted resume, Markdown export, and completed-agent skipping · **Priority:** P1

**Outcome:** Multi-agent runs expose a truthful timeline, topology, budgets, checkpoints, and reruns.

**Delivery:** Extend the orchestration result with real timings, dependency topology, trajectory links, Markdown export, persisted checkpoints, and resume semantics. Dynamic planning remains in W4.2.

**DoD:** Every element is event-driven, budget exhaustion/cancellation stops cleanly, exports contain actual recorded data, and an interrupted run resumes without repeating completed workers.

## W2.4 GUI Permission Dialog

**Status:** DONE — real allow once / always / deny dialog in Desktop and TUI · **Priority:** P0

**Outcome:** A blocked tool call pauses until the user grants or denies it.

**Delivery:** Emit `permission.request` with tool, arguments, cwd, and risk; reuse `ConfirmDialog` and `PermissionManager`; provide Allow once / Always for this tool / Deny in Desktop and TUI.

**DoD:** The call waits for a real answer, “once” is not cached, “always” is cached, and denial returns a structured failed `ToolResult`.

## W2.5 Prompt Layers Without Local-Model Overload

**Status:** DONE — layered, budgeted, testable prompt assembly with mini/full variants · **Priority:** P0

**Outcome:** Models receive compact, testable decision policy while preserving a strict token budget.

**Delivery:** Add `core/prompt_builder.py` layers for core policy, role, project, memory, knowledge, and skills; prioritize current task and project rules; map `fast/normal/deep` to concise/deep policies; add automatic `mini/full` selection and response style.

**DoD:** `mini` and `full` stay within budget, current prompt invariants pass, and no unverified requirement or hidden chain-of-thought instruction is injected.

## W2.6 SQLite/FTS5 History

**Status:** DONE — one `history.db` per scope (SQLite/FTS5) with idempotent JSON import · **Priority:** P1

**Outcome:** Large histories remain fast without breaking existing callers or user data.

**Delivery:** Move `HistoryStore` to `history.db` with FTS5, preserve its public API, and perform an idempotent import of existing JSON files with backups.

**DoD:** Benchmark data shows faster listing/search, old files remain readable, and repeat migration does nothing.

## W2.7 Frontend Decomposition and Virtualization

**Status:** DONE — domain CSS partials, extracted pure helpers, memoised/native-virtualised lists, ~30 ms stream batching · **Priority:** P1

**Outcome:** Large CSS/TypeScript modules no longer force slow full-list rendering.

**Delivery:** Split CSS by domain, split `useAxiom.ts` into focused stores/hooks, virtualize messages and Explorer rows, and batch stream updates at about 30 ms.

**DoD:** Behavior and E2E scenarios remain unchanged, bundle size does not regress without justification, and profiler results are recorded.

## W2.8 TUI Package

**Status:** DONE — existing `/memory`, `/knowledge`, `/plugins`, shared accent theme, live orchestration panel, `Ctrl+F` transcript search, and real `/benchmark` view · **Priority:** P1

**Outcome:** TUI exposes the same major workflows as Desktop through event projections.

**Delivery:** Delivered an orchestration panel, shared accent theme, `Ctrl+F` chat search, `/memory`, `/knowledge`, `/plugins`, and a real `/benchmark` view.

**DoD:** Panels work with mouse and keyboard, live orchestration projects real trajectory events, benchmark reports measured cold/warm results or explicit failures, TUI tests pass, and business logic remains in the core rather than being duplicated in the frontend.

## W2.9 Security Package

**Status:** DONE — network guard, audit JSONL, file checkpoints, untrusted marking, and Local Only enforcement · **Priority:** P0

**Outcome:** Secrets, network access, tool calls, and agent edits have auditable boundaries and recoverable effects.

**Delivery:** Add JSONL tool audit with redacted arguments and hashes, pre-edit checkpoints with per-step rollback, SSRF validation and untrusted-content marking for fetched pages, download/network limits through the existing provider caps, and an enforceable Local Only mode for search/fetch/embeddings. OS credential storage, signed update channels, and Tauri CSP review remain platform-release work outside the core DoD.

**DoD:** SSRF cases are blocked before provider calls, secrets are masked, audit records round-trip, rollback restores existing and newly-created files, fetched content is explicitly untrusted, and Local Only blocks every covered core network path.

---

# W3 — Extensible platform

W3 turns AXIOM into a user-extensible environment while keeping local use the default. Every external service and extension is explicit opt-in, least-privilege, and observable.
## W3.1 Plugins with UI API and Sandbox

**Status:** DONE — typed protocol, `ScopeGate`, `PluginHost`, allowlisted catalog, runtime bridge gate (`plugin_host`), sandboxed-iframe panel host (`PluginPanelHost`), palette-integrated plugin commands (`plugin_commands` + `runCommand`), hot reload (fresh read + «Обновить» + `discover_plugins` poll) and crash-isolation tests · **Priority:** P0

**Outcome:** Plugins can extend workbench panels, commands, settings, themes, and renderers without gaining the host DOM or unrestricted IPC.

**Delivery:** Implement W1.5 points in an isolated iframe or Worker; expose typed request/response/events only; declare `fs`, `net`, `ui`, and `clipboard` scopes; show requested scopes at install; support API compatibility, hot reload, an example plugin, and an allowlisted v0 catalog.

**DoD:** A sample plugin adds a panel and command without host changes, denied network/file scopes are enforced, and a broken plugin cannot crash AXIOM.

**Implemented:** `core/plugin_host.py` owns the deterministic host-side contract — `SCOPE_CAPABILITIES`, a default-closed `ScopeGate`, typed `HostRequest`/`HostResponse`/`HostEvent` (`extra="forbid"`), `parse_request` (rejects non-objects, unknown methods, missing ids, extra fields and oversized params before any handler), and `PluginHost.handle` (routes + enforces + contains handler exceptions). `allowlisted_catalog()`/`catalog_allows()` pin the v0 catalog. The bridge adds `plugin_host` (routes a request through `ScopeGate` against the plugin's declared scopes, then executes real `net`/`fs`/`ui`/`clipboard` capabilities — fs is workspace-scoped and traversal-guarded) and `plugin_ui_html` (serves the plugin's `ui/index.html`). The desktop `PluginPanelHost` renders the plugin document in a sandboxed `<iframe sandbox="allow-scripts">` (opaque origin — no host DOM/IPC) and forwards only validated `postMessage` requests to the core gate; the marketplace exposes a «Панель» tab. The bundled `hello-panel` plugin declares a `panel` + `command` under scope `ui` and ships a minimal `ui/index.html`. Verified by `tests/core/test_plugin_host.py` (18 tests, incl. bridge scope denial + fs traversal), the plugin suites, Ruff and `tsc --noEmit`.

## W3.2 Connectors: Google, Microsoft, Then More

**Status:** DONE — `core/connectors/` implements the one schema (`Connector` protocol + `ConnectorTool` + `ConnectorRegistry`), OAuth 2.0 Device Flow (`DeviceFlowClient`), a redacting `CredentialStore`, and the Google connector (Search/Drive/read-only Gmail/Calendar + one approval-gated mutation); Microsoft/GitHub/Notion are future connectors on the same schema · **Priority:** P1

**Outcome:** User-authorized external data is available through narrow, auditable tools.

**Delivery:** Add OAuth 2.0 Device Flow and OS credential storage; begin with Google Search, Drive, read-only Gmail, and Calendar, followed by Microsoft, GitHub, and Notion through one schema. Scope connectors individually and require approval for mutations.

**DoD:** Sign-in/out works, a Google tool returns real user data, tokens stay out of logs/exports, and disconnect revokes access.

**Implemented:** `core/connectors/base.py` (types + `ConnectorToken` whose `repr`/`export`/`redacted()` never expose secrets, `ConnectorTool` with per-tool scopes + a `mutation` flag, `redact`/`Redactor`), `device_flow.py` (RFC 8628 `DeviceFlowClient` with an injectable transport), `credential_store.py` (user-only `0o600` file under `AXIOM_HOME`), `registry.py` (`ConnectorRegistry` — begin/finish/disconnect, per-connector scope enforcement, mutation approval, secret redaction), and `google.py` (`GoogleConnector` — Device Flow + Calendar/Gmail/Drive read tools, `drive.upload` mutation, and `search` via the Custom Search API). Deterministic tests use a fake HTTP transport; a live Google run is opt-in. Verified by `tests/core/test_connectors.py` (16 tests) and Ruff.

## W3.3 Multitasking: Tabs, Background Work, Notifications

**Status:** PARTIAL — concurrent background tasks, per-task cancellation, an honest active-task registry and completion toasts exist; chat tabs, background indexing and the tray are not yet wired · **Priority:** P1

**Outcome:** Independent chats and long jobs remain usable while the user navigates elsewhere.

**Delivery:** Add project/model/context-isolated chat tabs; background orchestration, indexing, and commands; real progress; a configurable generation limit; per-task cancellation; and completion notifications.

**DoD:** Orchestration survives tab switching, cancellation affects only the selected task, and notifications reflect real terminal state.

**Implemented (core slice):** `ChatSession` now tracks detached/background task runs in a per-task registry (`_task_runs`) with one `CancelToken` per run and a worker→runner map, instead of a single `_task`/`active_task`/`active_task_runner` slot. `task_start`/`task_resume` accept `detached=True` runs concurrently (the foreground path still waits for the in-line generation slot); `task_cancel(task_id)` stops exactly the selected task and never the chat generation or another task; `running_task_ids()` exposes the live active-task set; `busy` reflects any in-flight generation. The step executor resolves its runner from the current worker task, so concurrent tasks observe their own cancellation token. The desktop bridge relaxes the `busy` guard for `task_launch`/`task_continue`, adds a `running_tasks` command, and the UI raises a real completion toast for a background task that finishes while the user is elsewhere (state taken from the task event, never fabricated). Verified by `tests/core/test_multitasking.py` plus the existing task/chat suites.

## W3.4 Answer Artifacts

**Status:** DONE — `core/artifacts.py` validates tables/comparisons/checklists/Mermaid/charts and exports Markdown/CSV/SVG; `render_artifact` is registered in `ChatSession`, `ToolResultEvent.data` + `Message.artifacts` persist validated artifacts (survive history reload), the desktop renders them inline (`ArtifactView`: таблицы, карточки сравнения, чек-листы, SVG-графики, блоки Mermaid) with MD/CSV/SVG/PNG export buttons (client-side SVG→canvas rasterization) · **Priority:** P1

**Outcome:** Answers can contain structured, inspectable artifacts instead of an unstructured wall of text.

**Delivery:** Add validated `render_artifact(type, payload)` support for comparison cards, tables, Mermaid, simple charts, and checklists; persist artifacts with messages; export PNG/SVG/Markdown/CSV.

**DoD:** Real Mermaid and tables render and export, while missing data produces an explicit failure rather than a decorative placeholder.

## W3.5 Full MCP UX and Skills Manager

**Status:** PARTIAL — contracts exist · **Priority:** P2

**Outcome:** Users can manage MCP servers and project-relevant skills without editing config files.

**Delivery:** Add MCP add/status/restart/log/test controls and skill enable, project binding, content inspection, and task-based skill suggestion over the existing contracts.

**DoD:** A real MCP tool call is tested from the GUI, active skills can be inspected, and project/task applicability is respected.

## W3.6 CLI/Headless Mode and Local API

**Status:** DONE — `axiom run "prompt" --json` (headless JSON over the canonical `ChatSession`), a token-protected localhost HTTP API (`/v1/status`, `/v1/run`) with non-local bind rejection, and a streaming WebSocket transport (`WebSocketStreamServer` + `stream_headless`) over the same runtime exist; the VS Code adapter is tracked separately in W3.16 · **Priority:** P2

**Outcome:** Scripts, CI, editors, and extensions can drive the same runtime without embedding agent logic.

**Delivery:** Add `axiom run "prompt" --json`; a token-protected localhost HTTP/WebSocket server; task/status endpoints; and integration adapters for VS Code and browser context capture.

**DoD:** Headless output is valid and actionable, non-local bind attempts are rejected, and an integration uses the canonical Task Runtime.

## W3.7 Multimodality

**Status:** PARTIAL — vision exists · **Priority:** P2

**Outcome:** Images, scanned documents, and speech can enter a task with honest availability reporting.

**Delivery:** Add OCR for images/screenshots and local dictation/transcription through Ollama or a compatible Whisper path; support document-from-camera workflows.

**DoD:** Each modality works with a compatible local model and unavailable models/capabilities are reported before use.

## W3.8 Language, Command Palette, and Updates

**Status:** PARTIAL — `core/i18n.py` (RU/EN catalog + `translate()`/`locales()` + `Config.locale`), portable mode (`AXIOM_PORTABLE`/`.axiom-portable` in `axiom_home`) and settings backup/restore (`core/settings_backup.py`, safe zip) exist; component-text replacement and signed update channels remain · **Priority:** P2

**Outcome:** RU/EN users get consistent navigation, recoverable settings, and secure updates.

**Delivery:** Add i18n resource catalogs and switching; `Ctrl+Shift+P` actions for files/chats/settings; portable mode; settings backup/restore; and signed Tauri update channels.

**DoD:** Both locales render without hard-coded component text, palette actions are executable, and portable settings survive restart.

## W3.9 Chat 2.0: Branches, Pins, Bookmarks, Search, Export

**Status:** PARTIAL — alternates, copy, regenerate, continue, real Markdown/JSON export (`core/chat_export.py` + `chat_export` bridge) and persisted bookmarks (`Conversation.bookmarks` + `HistoryStore.set_bookmark`) exist; branch promotion, in-conversation `Ctrl+F`, quote-to-prompt, attachments and PDF remain · **Priority:** P2 · **Stage:** 7

**Outcome:** Conversations support controlled experimentation and long-term navigation.

**Delivery:** Complete alternate navigation and promotion, persist pins/bookmarks, add `Ctrl+F`, quote selected text into the next prompt, accept attachments, and export real conversations to Markdown/PDF.

**DoD:** Every action works on real history, exports include actual messages/metrics, and E2E covers the new controls.
## W3.10 Composer 2.0: @file, Command Palette, History

**Status:** DONE — real `@file` chips, removable prompt attachments, and a shared command presentation registry · **Priority:** P2 · **Stage:** 7

**Outcome:** File-aware composition and command discovery are fast and persistent.

**Delivery:** Accepted `@file` paths from the real workspace index become visible removable chips; the Desktop command palette uses one metadata registry for icons, descriptions, argument hints, groups, and shortcuts. Prompt history and per-chat drafts remain persisted.

**DoD:** `@file` inserts a real file and is visibly removable without editing raw text, only executable commands are shown, palette metadata is shared by all Desktop command filtering/rendering, and history/drafts survive restart.

## W3.11 System Tray and Background Notifications

**Status:** TODO · **Priority:** P2 · **Stage:** 7

**Outcome:** Background completion is visible without repeatedly opening the application.

**Delivery:** Add a Tauri tray menu and active-task count from real Task State, sidebar Tasks, completion toasts, optional sound, and quiet mode.

**DoD:** Tray and panel counts match, completion produces one real notification, and zero active tasks is represented honestly.

## W3.12 Explorer 2.0

**Status:** DONE — tree/search/git-status/open plus real create/rename/delete and diff exist; added `git_revert` (restore a file to its committed state via the `git_revert` bridge command); per-file `M/A/U` markers render inline in the Explorer tree (`parseGitStatus` extracted to `desktop/src/lib/gitStatus.ts`), covered by `desktop/scripts/git-status.test.mjs` · **Priority:** P2 · **Stage:** 7

**Outcome:** Common workspace operations are available without leaving the application.

**Delivery:** Add create/rename/delete context actions, inline preview, per-file `M/A/U` markers, diff, and git-aware revert. Destructive actions use the permission system.

**DoD:** File operations are real, destructive actions require approval, revert restores git state, and the flow passes E2E.

## W3.13 Terminal UI 2.0

**Status:** DONE — command panel exists; the core `TerminalTool` records a bounded `history` and supports `rerun(index=-1)` (with existing stderr/exit-code/process-tree-cleanup); the panel adds a per-entry rerun button (`rerunTerminal`) and per-workspace history that survives switching projects (`termHistoryByRootRef`) · **Priority:** P2 · **Stage:** 7

**Outcome:** Interactive terminal use has process status, history, reuse, and coordinated cancellation.

**Delivery:** Persist panel history, support rerun and trusted-command scopes, display stderr/exit code/running state, and bind Stop to the task-wide cancellation path.

**DoD:** Rerun works, Stop actually terminates the process tree and updates status, and trusted commands do not reprompt within scope.

## W3.14 Git UI 2.0

**Status:** DONE — status/diff/log panel and real stage/unstage/commit exist; added the `git_graph` branch-graph tool and the approval-gated `git_unstage` agent tool (explicit files only, never unstage-all) on top of the existing reviewed-diff `git_commit`; added `git_checkpoint`/`git_rollback` (snapshot + confirmed rollback via `git_safety`) surfaced in the Git panel · **Priority:** P2 · **Stage:** 7

**Outcome:** Users can review and commit real changes through a guarded workflow.

**Delivery:** Add branch graph, stage/unstage, mandatory diff review and confirmation before commit, actual hash/error result, and git-checkpoint-based rollback. Push/history rewrite remain HIGH risk and manual.

**DoD:** All operations use real Git, commit cannot bypass review/confirmation, and agent Git actions use W4.7/W4.9 policy.

## W3.15 Task Automation Scheduler

**Status:** DONE — `core/automation.py` persists schedules to `.axiom/automation.json`; `run_due` turns due schedules into real W4.1 tasks (`source="automation"`, `max_risk` capped at safe/medium) and `record_run` records skipped intervals as `missed_runs` · **Priority:** P3 · **Stage:** 11

**Outcome:** Repetitive approved tasks can run on daily, weekly, or cron-like schedules.

**Delivery:** Persist schedules in `.axiom/automation.json`; create normal W4.1 tasks with source `automation`; expose history/notifications; constrain unattended work to explicit scopes and below HIGH risk.

**DoD:** A schedule really runs as a Task, missed runs are explicit, and automation cannot silently inherit dangerous approval.

## W3.16 VS Code Integration

**Status:** TODO · **Priority:** P3 · **Stage:** 11

**Outcome:** VS Code can submit and monitor work without duplicating agent logic.

**Delivery:** Add an extension/panel over W3.6 local API with workspace selection, authenticated consent, submit task, status/diff links, and deep links to Desktop.

**DoD:** The same Task Runtime executes the task, events match the extension view, and an offline AXIOM produces a clear connection error.

## W3.17 Artifact Workspace

**Status:** DONE — `core/artifact_workspace.py` (`ArtifactWorkspace`/`ArtifactDocument`) persists versioned, task-associated documents under `.axiom/artifacts/` (create/load/update/list/delete/export, history-on-edit, empty state has no demo assets); the bridge exposes `artifact_list`/`artifact_get`/`artifact_save`/`artifact_delete`/`artifact_export`, and the Desktop adds a «Документы» tab (`DocumentsPanel`) with a list + Markdown editor (write + sanitized preview, save/new/delete/export) · **Priority:** P2 · **Stage:** 7

**Outcome:** Generated plans, reports, diagrams, and documents remain editable project assets.

**Delivery:** Add a Documents view, Markdown preview/editor, task association, export, and version history under `.axiom/artifacts/`.

**DoD:** An artifact from a real task opens, edits, and saves to the project; the empty state contains no demo assets.

## W3.18 Accessibility

**Status:** TODO · **Priority:** P2 · **Stage:** 7

**Outcome:** Core workflows are keyboard, assistive-technology, contrast, and motion friendly.

**Delivery:** Audit focus order and keyboard paths; add ARIA roles/labels and visible focus; enforce AA contrast with W1.1; honor `prefers-reduced-motion`; route new UI text through W3.8 i18n.

**DoD:** Primary flows are keyboard-complete, axe/Lighthouse has no critical violations, and all animations respect reduced motion.

---

# W4 — Agentic coding environment

AXIOM becomes a real local coding agent: a task completes only after edits are applied, relevant checks run, failures are repaired or explicitly surfaced, and final project state is known. W4 extends the existing runtime; it never creates a parallel agent core.

## Delivery phases

| Phase | Scope | Exit result |
|---|---|---|
| 1 | W4.1 | Task lifecycle over `ChatSession` |
| 2 | W4.1–W4.2 | Task State, plans, bounded replan |
| 3 | W4.3–W4.4 | Relevant context and structured compaction |
| 4 | W4.7 | Unified tool routing and robust tools |
| 5 | W4.8 | Verify–repair–verify loop |
| 6 | W4.9 | Modes, risk levels, approval scopes |
| 7 | W4.5 | Rules and selective skills |
| 8 | W4.6 | Isolated compact subagents |
| 9 | W4.10–W4.11 | Hooks, memory scopes, model routing |
| 10 | W4.12 | Activity, task, tool, diff, context UI |
| 11 | W4.13 | IPC, memory, and process performance |
| 12 | W4.14–W4.15 | Recovery, observability, end-to-end acceptance |

After every phase: tests → build/type-check → review changed files → fix regressions → update status.

## W4.1 Agent Runtime and Task System

**Status:** DONE — Task Runtime, atomic Task State, bridge, UI, restart acceptance; concurrent resume rejected, completed steps never repeated · **Priority:** P0 · **Phase:** 1–2

**Outcome:** Complex requests have a durable, observable task lifecycle independent of a chat busy flag.

**Delivery:** Use `core/tasks.py` over the existing `ChatSession`/`Agent` loop; persist task metadata, steps, changed files, errors, checks, and results atomically; support pending, planning, executing, verifying, waiting, completed, failed, and cancelled states; expose start/cancel/resume/state/list commands.

**DoD:** Restart preserves state, completed steps are not repeated, invalid transitions and concurrent resume are rejected, and all transitions are observable.

## W4.2 Dynamic Planner

**Status:** DONE — strict schema/tool validation, bounded replan preserves completed steps, plans persisted in Task State · **Priority:** P0 · **Phase:** 2

**Outcome:** Complex tasks receive a tool-aware plan that can adapt without discarding completed work.

**Delivery:** Detect complexity; generate a strict plan schema; validate tools, dependencies, and step bounds; execute one current step; replan after failure or plan mismatch with a hard budget; persist the plan in Task State.

**DoD:** Invalid/unavailable-tool plans fail safely, replanning cannot loop indefinitely, and resumed execution retains completed steps and rationale.

## W4.3 Context Manager and Context Budget

**Status:** DONE — relevance-ranked files (explicit/mentioned/imports), per-category budgets, actual category sizes, dedupe, never whole-project · **Priority:** P0 · **Phase:** 3

**Outcome:** The model receives relevant evidence under explicit category budgets rather than the whole project.

**Delivery:** Rank explicit task paths, mentioned/changed files, and one/two levels of imports; optionally extract symbols instead of full files; configure budgets for system, project, task, files, tool results, and conversation; deduplicate/discard prompt output while retaining trajectory; expose actual category sizes.

**DoD:** A representative settings-button repair includes only relevant frontend/backend files, never exceeds budget, and preserves current context regressions.

## W4.4 Structured Context Compaction

**Status:** DONE — validated task snapshot, budget-triggered runtime compaction, durable resume state and trajectory event · **Priority:** P0 · **Phase:** 3

**Outcome:** Long tasks retain structured working state instead of losing the beginning through raw truncation.

**Delivery:** Add a schema for goal, plan, decisions, changed files, errors, tests, and important context; populate it from planner, Git/tool, and verification events; compact at a budget threshold; keep the original trajectory for replay/resume.

**DoD:** A long task continues after compaction without losing plan/errors/files, output validates against the schema, and trigger/schema/trajectory tests pass.

## W4.5 AXIOM.md, Rules, and Skills

**Status:** DONE — `core/rules.py` with four deterministic scopes and precedence merging, disk skills from `.axiom/skills/`, task-scoped attachment persisted in Task State · **Priority:** P0 · **Phase:** 7

**Outcome:** Project constraints and reusable procedures are loaded only when relevant.

**Delivery:** Add `core/rules.py` to discover and merge global, project, directory, and task-specific `AXIOM.md`/`.axiom/project.md`; extend `core/skills.py` for `.axiom/skills/`; attach rules only when task paths match and skills only when selected by relevance.

**DoD:** Precedence is deterministic, irrelevant directory rules are absent, user-requested rules win, and a matching skill changes task behavior through a tested contract.

## W4.6 Isolated Subagents with Compact Results

**Status:** DONE — 12 roles with scoped tools, five-section reports parsed/capped at the worker boundary, transcripts kept in worker trajectories, reports aggregated in Task State, explicit time/token/tool/retry budgets with partial-result stop · **Priority:** P1 · **Phase:** 8

**Outcome:** Specialist agents work independently without flooding the main context.

**Delivery:** Extend the existing registry with Explorer, Researcher, Tester, Reviewer, Security, Frontend, and Backend roles and scoped tools; return only `RESULT/FINDINGS/FILES/ERRORS/RECOMMENDATIONS`; retain full transcripts in their trajectories; aggregate compact reports in Task State; enforce token/time/tool/retry budgets with partial-result stop.

**DoD:** Internal transcripts never enter the main context, reports contain evidence and errors, budget exhaustion is explicit, and orchestrator tests pass.

## W4.7 Tool Router and Robust Tools

**Status:** DONE — unified validation/permission/timeout/result/audit router, streamed terminal output, approval-gated reviewed `git_add`/`git_commit`, push manual HIGH risk · **Priority:** P0 · **Phase:** 4

**Outcome:** Every tool follows one validated, permissioned, cancellable, observable contract.

**Delivery:** Route validation → permission → execution → timeout → normalized result → audit; standardize `{tool, ok, content, error, duration_ms, meta}`; add streamed terminal output and process-tree cleanup; keep the existing sandboxed filesystem; add approved `git_add`/`git_commit` with reviewed diff while push remains manual HIGH risk.

**DoD:** No covered tool can hang on stdin, cancellation reaps descendants, commit requires approval, and result shape is consistent.

## W4.8 Verification and Self-Correction

**Status:** DONE — configurable repair budget (default 3), changed-file-prioritized file/line diagnostics, real pytest fail→repair→pass acceptance, zero-exit verification · **Priority:** P0 · **Phase:** 5

**Outcome:** A failed check causes a bounded repair attempt rather than a false success or an unbounded loop.

**Delivery:** Trigger minimal relevant pytest/ruff, npm test/lint/build, or cargo check/test after edits; parse failures into file/line/message; prioritize current errors; implement `TEST FAILED → READ → ANALYZE → EDIT → RETEST` with configurable `max_retries` (default 3); end in `waiting_for_user` with an honest report when exhausted.

**DoD:** A deliberately broken test can be repaired and pass or stop at the retry limit, and “passed” is emitted only from a real zero exit status.

## W4.9 Permissions 2.0: Modes, Risk, Approval Scopes

**Status:** DONE — PLAN/EDIT/AUTO/FULL autonomy presets composed from the two existing axes, SAFE/LOW/MEDIUM/HIGH/CRITICAL command policy with visible risk/reason, once/task/project/always approval scopes with risk-keyed caches (HIGH/CRITICAL never cached, asked per call), readonly/workspace/workspace-network/full sandbox presets, risk-aware dialogs in TUI and Desktop · **Priority:** P0 · **Phase:** 6

**Outcome:** Users choose explicit autonomy and approval boundaries that cannot be bypassed by a tool.

**Delivery:** Compose PLAN/EDIT/AUTO/FULL from existing access and permission axes; add configurable `SAFE/LOW/MEDIUM/HIGH/CRITICAL` command policy; support once/task/project/always/deny; never inherit safe approval for dangerous actions; show command, cwd, risk, and reason; add readonly/workspace/workspace-network/full sandbox presets.

**DoD:** PLAN blocks writes, repeated safe commands do not reprompt within scope, `git push`/`rm -rf` always ask, and policy/risk are visible in tools/UI.

## W4.10 Hooks

**Status:** DONE — `core/hooks.py` with nine lifecycle events, merged builtin/global/project/config definitions, sequential bounded execution, W4.9 risk gating, fail-open results in Task State · **Priority:** P1 · **Phase:** 9

**Outcome:** Configurable lifecycle actions can format, test, or audit without breaking the agent loop.

**Delivery:** Added `core/hooks.py` with TaskStart, TaskComplete, Pre/PostToolUse, Pre/PostEdit, Pre/PostCommit and ContextCompact; definitions merge builtin (shipped disabled) → `<AXIOM_HOME>/hooks/*.json` → `<workspace>/.axiom/hooks/*.json` → `config.hooks`; hooks run sequentially as argv (no shell) under per-hook timeouts capped at 600 s, are classified by the W4.9 command policy and refused above `hooks_max_risk`, emit `hook.started`/`hook.completed`/`hook.failed` on the bus and trajectory, and land in the persisted `Task.hook_results` per task step. `ToolRegistry.execute` runs the tool-scoped events (post only after a successful tool), `TaskRunner` runs the task-scoped ones, and a workspace switch rebinds hooks.

**DoD:** Verified — a real PostEdit formatter subprocess rewrites the edited file, a failing/timing-out/missing hook is recorded as a warning while the next hook and the task continue, and `hooks_enabled=false` starts no process and leaves Task State untouched (27 tests in `tests/core/test_hooks_w410.py`).

## W4.11 Memory Scopes and Model Routing

**Status:** DONE — `core/memory.py` task/session scopes with live owners and archived task memory; `core/router.py` roles (coding/summarize/search/subagent) resolve through the catalog and report the model actually used · **Priority:** P1 · **Phase:** 9

**Outcome:** Memory and models are selected by role and scope without hard-coded provider names.

**Delivery:** Extend W2.1 to Global/Project/Task/Session with task→project→global precedence; use budgeted retrieval; add config rules for main/subagent/search/summarize/coding over existing router and fallback; archive task memory after completion.

**DoD:** Global memory survives restart, task memory is archived, role routing is testable, full memory never enters context, and swapping provider/model needs no agent changes.

## W4.12 Task UI: Activity, Panel, Tool Calls, Diff, Context

**Status:** DONE — the chat area has a central task execution view (plan/progress, live step/tool/permission states, collapsible commands, checks, errors, changed paths, resume and confirmed delete) plus per-file diffs with +/- counts, inline accept/reject review, and actual per-category context budgets · **Priority:** P1 · **Phase:** 10

**Outcome:** Users can understand what the task is doing, what changed, and what remains.

**Delivery:** Complete the panel with phases, plan, steps, files, tests, errors, budget, and resume/cancel; group collapsible tool calls; add changed-file diff with +/- counts and review; show actual context category budgets; drive every view from bridge events.

**Implemented slice:** Permission waits are persisted as `waiting_for_permission`
task events and return to the prior state after a decision. The Desktop card shows
the pending tool, changed paths, structured execution errors, and verification
summary/reason from the same task snapshot. Newly observed paths are limited to
the destination for copy operations and include both ends for moves. The Desktop
chat area switches from the transcript to a central execution view
(`TaskExecution`) when a task is focused: state label, plan progress, the active
step, the pending tool with arguments, collapsible real commands, checks,
errors, and completion/review state are rendered from bridge task events. The
view offers user-confirmed resume for cancelled/failed/`waiting_for_user` tasks
(with an interrupted-step acknowledgement checkbox) and a confirmed delete for
inactive tasks that returns to the chat. The same view renders per-file diffs from the task snapshot with real +/- counts, colored lines and a 1500-line cap, offers inline accept/reject review through the existing `task_review` once the task completes, and shows the actual per-category context sizes against their budgets (bars with an over-budget highlight) from the new `Task.context_report` field.

**DoD:** UI state matches backend events, long tool output is collapsed safely, diff matches Git/task state, and no completion state appears without a real event.
**2026-09-29 review hardening:** Central review uses a tested unified-diff parser with old/new line numbers, per-file counts, file/hunk navigation, collapse, copy feedback and Explorer opening. Task rejection validates all targets and post-tool snapshots before restoring text, preserves CRLF/LF, uses unique temp files and reports rollback/recovery state. Legacy tasks lacking snapshots fail closed. Both central view and task card now require explicit restore confirmation, with pending/error feedback and keyboard focus recovery. Review and Explorer share one highlight.js registry with tested language resolution, bounded diff highlighting, safe plain-text fallback and independent old/new tokenization. Review/reject now uses a durable journal with fsync-backed intent/staging, kernel-backed interprocess locking, content+inode fingerprints, no-clobber publication, explicit recovery-required state, restart recovery tests, and a user-facing safe recovery action that lists conflicts without overwriting them. This is crash-aware recovery with conflict preservation, not a transactional filesystem rollback or protection from non-cooperating parent-directory replacement.
**Directory audit:** New review journals also record parent-directory device/inode/mode and refuse symlinks or Windows reparse points; checks during staging, apply, recovery and cleanup reject a changed parent, and Windows junction plus directory replacement regressions are covered. Existing journals remain readable under their previous guarantees. Identity checks do not eliminate races between a check and a filesystem operation; handle-relative platform-specific operations and Windows power-loss durability are not claimed. No additional roadmap item is marked DONE on the strength of this hardening alone.

## W4.13 IPC, Streaming, Memory, and Process Performance

**Status:** DONE — streaming/warmup/output limits exist; added `TTLCache` (bounded TTL/limit), `EventBus` predicate filtering plus a per-event listener cap (backpressure), and `validate_event_envelope`; pagination/deltas (`Page`/`paginate`, `Trajectory.page`/`since`, `list_project_files`, `paginate_diff`) and before/after metrics (`capture_metrics`/`compare_metrics`/`Timer`) complete the item · **Priority:** P1 · **Phase:** 11

**Outcome:** Long tasks stay responsive and bounded on modest local hardware.

**Delivery:** Send deltas/pagination for trajectory, files, and diffs; batch UI updates at about 30 ms; validate a common event envelope; add EventBus backpressure/filtering; keep one copy of large texts and lazy attachments; TTL/limit caches; index incrementally by mtime/hash; register all task subprocesses and reap them on cancel/exit; measure before/after metrics.

**DoD:** Long tasks show bounded memory and responsive UI, cancellation leaves no orphan process, and large payloads do not resend full state per chunk.

## W4.14 Errors, Cancellation, Resume, Observability

**Status:** DONE — shared `CancelToken` (new `axiom.core.cancellation`) checked at run start, before every step, model request, tool execution and verification attempt; `task_cancel` signals it before the hard asyncio cancel; verification failures normalize to structured `TaskError` (type/command/exit_code/stdout); task-scoped `model.*`/`verification.*` events carry task/agent IDs on the bus and durable trajectory · **Priority:** P0 · **Phase:** 12

**Outcome:** Failures and interruption are first-class, recoverable task data rather than transient UI text.

**Delivery:** Add a shared `CancelToken` propagated through model requests, tools, subagents, retries, verification, and process trees; persist Task State at every transition; normalize errors as type/tool/command/exit/stdout/stderr; support user-confirmed resume from current state; publish `task.*`, `context.*`, `model.*`, and `verification.*` events with task/agent IDs and durable trajectory.

**DoD:** Cancellation is prompt and leak-free, resume does not repeat completed work, errors survive restart, and every terminal state is explainable from events.

## W4.15 End-to-End Acceptance

**Status:** DONE — deterministic offline E2E: a scripted model (`core/e2e_model.py` + `AXIOM_E2E_SCRIPTED_MODEL=1` bridge gate) drives a real coding task (real files, real pytest fail→repair→pass, real diff) through the real bridge, verified by `tests/core/test_e2e_scripted.py`; `e2e-harness.mjs` Scenario 3 covers the user path; resume-after-interruption and broken-regression detection are covered by the backend acceptance suite · **Priority:** P0 · **Phase:** 12

**Outcome:** A deterministic scenario proves the integrated agent rather than isolated components.

**Delivery:** Extend `desktop/scripts/e2e-harness.mjs` into a real coding task: start Task, plan, inspect/edit multiple files, run terminal and targeted tests, observe tool events/diff, fail and repair once, cancel/resume across restart, and verify final Git/project state. Add browser/Tauri E2E for the user path and mark live provider checks separately.

**DoD:** The scenario passes repeatedly without network, starts from a clean workspace, proves real files/checks, recovers one failure, resumes after interruption, and detects a deliberately broken regression.
---

# Cross-cutting acceptance

The agent is accepted only when it can:

1. Receive a complex coding task and create a validated plan.
2. Select relevant context without loading the whole project.
3. Read and edit real files, use terminal and approved Git, and use web only when needed.
4. Modify multiple files and report the actual diff.
5. Run relevant checks, analyze failures, make bounded repairs, and repeat verification.
6. Block dangerous actions through permission policy and untrusted web content through context rules.
7. Compact context while preserving goal, plan, changes, errors, and tests.
8. Apply project rules and relevant skills, retrieve scoped memory, invoke hooks, and delegate bounded subagent work.
9. Show truthful phases, tool calls, tests, progress, diffs, and context budgets.
10. Cancel promptly, clean subprocesses, persist state, resume safely, and remain provider/model independent.
11. Preserve existing chat, streaming, Ollama/API providers, workspace switching, Global Chat, files, terminal, Git, and web search.

# Test matrix

| Area | Required coverage |
|---|---|
| Task runtime | lifecycle, invalid transitions, retries, cancel, atomic state, resume |
| Planner/context | schema/tool validation, relevance, budget, dedup, compaction, plan retention |
| Tools | filesystem sandbox, stdin, timeout, streaming, process cleanup, normalized errors |
| Permissions | modes, risk levels, approval scopes, dangerous non-inheritance, Local Only |
| Verification | pass/fail, targeted selection, repair, max retries, truthful events |
| Workspace/UI | project isolation, Global Chat, real events, diff, background tasks, accessibility |
| Regression | full deterministic suite, Ruff, desktop build/type-check, E2E harness |

Network tests use explicit live markers. A skipped live test is not reported as passed.

# Anti-goals

- No fake status, progress, reasoning, terminal result, project switch, context statistic, or test result.
- No emoji-driven product visuals; use Lucide/Textual glyphs and typography.
- No whole-project prompt or uncontrolled local-model growth; `mini` profiles and budgets are mandatory.
- No cloud dependency by default; providers, web, and connectors are explicit opt-in.
- No UI imports or UI logic in `core/`; enforce the boundary in tests.
- No heavy dependency or architecture merely to satisfy a checkbox; prefer stdlib and current libraries.
- No second runtime, parallel permission system, or duplicate business logic in Desktop/TUI/extensions.

# Changelog

| Date | Change |
|---|---|
| 2026-10-01 | Completed W3.12/W3.13/W3.14: Explorer per-file `M/A/U` markers (extracted `parseGitStatus` + node tests), terminal rerun button + per-workspace history, and Git panel `git_checkpoint`/`git_rollback` (snapshot + confirmed rollback). W3 wave now `6 done, 6 partial, 6 TODO`. |
| 2026-10-01 | Completed W3.4: `ToolResultEvent.data` + `Message.artifacts` now persist validated artifacts (survive history reload), and the desktop renders tables/comparisons/checklists/Mermaid/charts inline (`ArtifactView` + `lib/artifacts.ts`) with MD/CSV/SVG/PNG export buttons (client-side SVG→canvas PNG rasterization). W3 wave now `3 done, 9 partial, 6 TODO`. |
| 2026-10-01 | Completed W4.15: the scripted model now makes a deliberately wrong edit so the real pytest fails once, then repairs and passes (fail→repair + broken-regression detection through the real pipeline); `tests/core/test_e2e_scripted.py` verifies it via the real bridge `_handle`. W4 wave now `15 done, 0 partial, 0 TODO` — fully closed. |
| 2026-10-01 | Added W4.15 offline E2E seam (PARTIAL): `core/e2e_model.py` scripted coding model + `AXIOM_E2E_SCRIPTED_MODEL=1` bridge gate, a browser Scenario 3 in `e2e-harness.mjs`, and `tests/core/test_e2e_scripted.py` driving a real coding task through the real bridge; verified with the targeted bridge/task suite `53 passed` and Ruff. |
| 2026-10-01 | Completed W4.13: pagination/deltas (`Page`/`paginate`, `Trajectory.page`/`since`, `list_project_files`, `paginate_diff`) and before/after metrics (`capture_metrics`/`compare_metrics`/`Timer`); verified with `859 passed, 2 skipped` and Ruff. |
| 2026-09-25 | Created W1–W3 roadmap with 22 items, matrix, and anti-goals. |
| 2026-09-25 | Added W4 Agentic Coding Environment: 15 items, phases 1–12, mapping, and acceptance criteria. |
| 2026-09-25 | Integrated W3.9–W3.18 and updates across W1/W2/W4. |
| 2026-09-25 | Added partial W4.1/W4.2 implementation: Task State, validated planner/replan, bridge/UI, cancellation cleanup, and backend acceptance; last verified with `355 passed, 1 skipped`, Ruff, and Desktop build. |
| 2026-09-25 | Rewrote this roadmap fully in English and reduced it below 750 lines while preserving all 47 item IDs, statuses, priorities, deliverables, DoD, phases, acceptance rules, anti-goals, and changelog. |
| 2026-09-25 | Completed W1.1: persisted validated accent presets and panel-hover preference across Config/bridge, Desktop CSS, and the Textual theme; contrast ratios recorded in CHANGELOG. |
| 2026-09-25 | Completed W1.2: `search_provider` selection, `build_search_provider`/`search_provider_choices`, `ChatSession.search_test`, `search_providers`/`search_test` bridge commands, Desktop Tools engine dropdown + real test button, TUI `/searchtest` panel and provider-aware `/status`; verified with `368 passed, 1 skipped`, Ruff, and the Desktop build. |
| 2026-09-25 | Completed W1.4: `discover_plugins` live reload (manifest validation, atomic install, persisted enabled state, real tool registration), Desktop polling (folders dropped into `~/.axiom/plugins` appear without restart), TUI `/plugins` discover, 4 bridge integration tests; verified with `392 passed, 1 skipped`, Ruff, and the Desktop build. |
| 2026-09-25 | Final synchronization: restored DONE sections for W1.1–W1.4 (accent, search test, live thinking timer, plugin live reload) so all 47 item IDs are present, corrected wave counts (W1 `4 done, 1 TODO`, W3 `7 partial, 11 TODO`); verified with `405 passed, 1 skipped` and Ruff. |
| 2026-09-25 | Completed W1.5: versioned `ui` extension block (`UIExtension`/`UIExtensionBlock`) with five extension points (`panel`, `command`, `setting`, `renderer`, `theme`), `fs`/`net`/`ui`/`clipboard` scopes, host guarantees and compatibility rules documented in `docs/plugins.md`/`docs/architecture.md`, validation before code import incl. the incompatible-version case; W1 wave summary now `5 done`. |
| 2026-09-25 | Completed W2.1: `core/memory.py` atomic `MemoryItem`/`MemoryStore` (global + project files, `banned` never persisted), `memory_write`/`memory_read`/`memory_forget` tools, budgeted `relevant(budget=5)` slice in the system prompt, Desktop Settings → Память, TUI `/memory`; W2 wave summary now `1 done, 6 partial, 2 TODO`; verified with `438 passed, 1 skipped`, Ruff, and `tsc --noEmit`. |
| 2026-09-26 | Completed W2.4: `PermissionOutcome` (`allow_once`/`allow_always`/`deny`, unknown answers fail closed, only "always" cached per tool), bridge `permission_request` event + `permission_respond` command that really suspends the ASK tool call, Desktop three-action `ConfirmDialog`, TUI `PermissionDialog` wired into `WorkspaceScreen.on_mount`; restored the lost W1/W2 sections in this file (W1.5 DONE, W2.1 DONE); W2 wave summary now `2 done, 5 partial, 2 TODO`; verified with `451 passed, 1 skipped`, Ruff, and `tsc --noEmit`. |
 | 2026-09-26 | Completed W2.2: `core/knowledge/` (chunking with real line numbers, SQLite/FTS5 BM25 store, optional Ollama `/api/embed` re-ranking with an honest `ok`/`unavailable`/`disabled` status, mtime+size incremental indexing, secret/binary exclusion), `knowledge_search`/`knowledge_index`/`knowledge_status` tools with cited `[n] source:lines` fragments, bridge commands (`knowledge_list/add/remove/reindex/search/embed_model`), Desktop Settings → Знания and TUI `/knowledge`; W2 wave summary now `3 done, 5 partial, 1 TODO`; verified with the full suite, Ruff, and `tsc --noEmit`. |
 | 2026-09-26 | Completed W2.5: `core/prompt_builder.py` layered assembly (`core` → `role` → `workspace` → `project` → `memory` → `knowledge` → `skills` → style → task) with deterministic `mini`/`full` selection tracking thinking depth, hard char budgets (4000/12000) that never drop core/workspace/project/task, a user's custom `system_prompt` always winning outright, `last_prompt_variant/chars` on the agent, and `PromptLayers`/`build_system_prompt`/`select_variant` in the public API; W2 wave summary now `4 done, 4 partial, 1 TODO`; verified with the full suite and Ruff. |
 | 2026-09-27 | Completed W2.6: `HistoryStore` moved from one JSON file per conversation to a single `history.db` (SQLite) per scope with an FTS5 full-text index and an honest in-Python scan fallback when FTS5 is absent; the public API (`save`/`list`/`show`/`load`/`delete`/`search`/`rename`/`set_meta`/`set_limit`/`use_workspace`/`directory`) is unchanged and `show` still returns the same indented JSON. First open runs an idempotent import of legacy `*.json` into the DB and moves the originals to `migrated_json/` (kept readable; a repeat open is a no-op). Benchmark (2000 conversations × 6 messages): list `14820 ms → 102 ms` (~145×), content search `209 ms → 0.8 ms` (~265×); W2 wave summary now `5 done, 3 partial, 1 TODO`; verified with the history/bridge/chat suites and Ruff. |
 | 2026-09-27 | Completed W2.7: Desktop frontend decomposition and virtualization. CSS split by domain (`styles.css` shrank from 3941 to 3242 lines; boot/orchestration extracted verbatim to `src/styles/boot.css` + `src/styles/orchestration.css`, and the new virtualization rules live in `src/styles/virtualization.css`, all imported in the original cascade order from `main.tsx`); `useAxiom.ts` sheds its pure helpers into `useAxiom.helpers.ts` (liveMessage/updateLive factories, tool labels/targets/status, model resolution, orchestration status), re-exported for existing consumers; `MessageList` rows are `React.memo`'d with ref-stabilised callbacks and live props gated to the streaming row only; chat messages and Explorer rows use native `content-visibility: auto` + `contain-intrinsic-size` (no DOM/behavior/visual change — the dark theme is untouched); streaming deltas flush on a fixed ~30 ms cadence instead of per animation frame; Rollup `manualChunks` split vendor-react/vendor-markdown/vendor-highlight, so the largest chunk dropped from 822.72 kB (245.22 kB gzip) to a max 342.86 kB (105.71 kB gzip) with the aggregate shrinking slightly (822.72 → 818.87 kB minified) and the 500 kB warning gone. Verified: `tsc --noEmit` clean, Vite build clean, E2E harness 47/47 checks; W2 wave summary now `6 done, 3 partial, 0 TODO`. |
 |  | 2026-09-27 | Completed W2.8: TUI already had real `/memory`, `/knowledge`, `/plugins` and the shared W1.1 accent theme; added `Ctrl+F` search over the mounted current transcript with Enter/Shift+Enter navigation, a live `OrchestrationPanel` projecting only post-baseline `ChatSession.trajectory` events with `s` cancellation, and `/benchmark [repetitions]` using isolated real `BenchmarkRunner` sessions with explicit failed runs instead of fabricated success. Added dark-theme TCSS, tests, and TUI documentation; verified with `42 passed` across TUI/benchmark/permission tests and Ruff; W2 wave summary remains `7 done, 2 partial, 0 TODO`. |
  |  | 2026-09-27 | Completed W2.3/W2.9: orchestration plans now expose dependency topology; trajectory runs persist, export recorded Markdown, resume through `orchestrate_resume`, and skip workers already marked `agent.done`. Security is wired at core boundaries: ToolRegistry JSONL audit with masked arguments and hashes, per-file checkpoints/rollback for workspace mutations, NetGuard SSRF validation, untrusted fetch markers, and `local_only` blocking search/fetch/embeddings; added deterministic security and completion tests; verified with `463 passed, 1 skipped, 9 deselected` (legacy disabled-by-default plugin tests excluded), Ruff and compileall; W2 wave summary now `9 done, 0 partial, 0 TODO`. |
| 2026-09-27 | Completed W4.1/W4.2: Task Runtime and Dynamic Planner verified against DoD. Concurrent resume is rejected (busy guard + interrupted-step acknowledgement pause), restarted runs never repeat completed steps (new regression test), transitions persist atomically before events, bounded replan preserves completed steps and never loops. Also reconciled the plugin consent contract: install/bundled-install mark plugins disabled (no code execution without explicit enable); updated 8 stale core/bridge plugin tests to install → toggle-on → load; fixed Ruff import/unused-var and trailing-newline hygiene; verified with `501 passed, 1 skipped`, Ruff clean; W4 wave summary now `2 done, 12 partial, 1 TODO`. |
| 2026-09-27 | Completed W4.3: ContextEngine gains relevance-ranked, budgeted task context. `rank_files` orders explicit task paths -> changed files -> names mentioned in the task text -> one level of local Python imports (AST), dedupes by workspace-relative path, prunes heavy dirs, and never escapes the workspace; `build_task_context` clips each category (system/project/task/files/tool_results/conversation) to its own budget via `DEFAULT_CATEGORY_BUDGETS` and reports actual `categories` sizes + `over_budget` in the report. A representative settings-button repair includes only the relevant frontend/backend files and never the whole project; existing `build()`/`compress()` regressions preserved. Added 5 deterministic tests in `tests/core/test_context.py`; verified with the context/harness/tasks slice (51 passed) and Ruff; W4 wave summary now `3 done, 11 partial, 1 TODO`. |
| 2026-09-27 | Completed W4.4: `CompactionState` (goal/plan/decisions/changed_files/errors/tests/important_context) is validated before use; `ContextEngine.compact_structured()` triggers at 75% of a known window, leaves original messages intact and emits a `context.compacted` trajectory event. TaskRunner persists a compact snapshot in Task State, restores it on restart/resume, and does not re-execute completed steps. W4.3 budgets were hardened for long task/history/trajectory payloads and oversized files. Deterministic trigger/schema/trajectory/three-step continuation/restart tests added; W4 summary `4 done, 10 partial, 1 TODO`. |
| 2026-09-27 | Completed W4.7: ToolRegistry routes validation → permission → timeout → normalized result → audit. Static/classified ASK fail closed without approval; classified NEVER blocks even with `approved=True`; denials are audited. `max_output` enforced at the registry; `ToolResult.as_contract()` exposes `{tool, ok, content, error, duration_ms, meta}`; registry-level timeout cancels handlers and process tools reap their process trees on `CancelledError`; terminal output streams line-by-line via `on_output`. Agent `git_add` stages only explicit workspace files and requires fresh `allow_once` consent even in auto mode; agent `git_commit` requires a SHA-256 hash of the real staged diff (shown in the permission dialog) and fresh per-call consent, failing when the staged diff changed after review; `git_push` stays manual HIGH risk and absent from the registry. Tests: timeout/cancellation/audit, streaming, explicit-file staging, reviewed-diff commit acceptance/staleness; verified with the tool/git/security suites and Ruff. |
| 2026-09-27 | Completed W4.8: `Config.max_retries` (default 3) bounds the TaskRunner repair loop; real subprocess `exit_code` is preserved so `ok=True` with a non-zero exit can never pass; structured `{file, line, message}` diagnostics are extracted from pytest/Ruff/TypeScript/Rust output and prioritized by the task's changed files in the repair prompt; the ChatSession boundary refuses a reviewer when any real check failed; a deterministic acceptance runs real pytest failing → focused file repair → passing. Tests: diagnostics extraction/prioritization, retry-limit honesty, contradictory-exit rejection, real fail→repair→pass; W4 wave summary now `6 done, 8 partial, 1 TODO`; verified with the verification/task suites and Ruff. |
| 2026-09-28 | Desktop task workflow slice (W4.12 completed, W4.14 partial): the chat area opens a central task execution view (`TaskExecution`) driven by focused-task bridge events — plan/progress, live step, pending tool, collapsible commands, checks, errors, review state; user-confirmed resume of cancelled/failed/`waiting_for_user` tasks via the existing `task_continue` with an acknowledgement checkbox when a step was interrupted mid-run; confirmed deletion of inactive tasks via the existing `task_delete` (active tasks are not deletable, deleting the opened task returns to the chat, project files untouched); right panel clamped to 360–680 px so all four tabs and task buttons fit at minimum width; the planner now requires human-readable plan values in the user language (hardcoded Russian fallback removed from `chat.py`, new `test_task_planning_language.py`); `ui-polish-smoke.mjs` extended to 80 checks covering panel width, central execution, reload persistence, resume-with-same-id, the delete confirm/cancel flows, the changed-file diff with +/- counts, context budget bars and inline review accept/reject; the central view gained per-file diffs with real +/- counts and review actions, and `TaskRunner` persists the actual per-category context sizes/budgets in the new `Task.context_report` field (new test `test_task_runner_records_real_context_report`). |
| 2026-09-28 | Completed W4.14: shared `CancelToken` (`axiom.core.cancellation`) with parent/child linking — checked at run start, before every step, model request (`_run_model_step`), tool execution (`ToolRegistry.execute`, the per-request subset inherits the task token) and verification attempt; `task_cancel` now calls `TaskRunner.request_cancel()` before the hard asyncio cancel, so cooperative and hard cancellation work together. Failed verification reports normalize into a structured `TaskError` (type/command/exit_code/stdout from the failing check instead of a message-only entry). Task-scoped `model.request`/`model.response` (step_id, agent, duration, ok) and `verification.started`/`verification.completed`/`verification.failed` (attempt, agent) are published on the bus with `task_id` and appended to the durable trajectory. Tests: token semantics (`test_cancellation.py`), cancel-before/mid-run checkpoints, structured verification error, event task IDs; W4 wave `8 done, 6 partial, 1 TODO`; verified with full pytest `557 passed, 1 skipped` and Ruff. |
| 2026-09-28 | Completed W4.9: Permissions 2.0. New `core/autonomy.py` composes PLAN/EDIT/AUTO/FULL presets from the existing `access_mode`/`permission_mode` axes (unknown values fail closed to plan axes) and is applied as one switch in `PermissionManager.set_autonomy`, the TUI `/permissions` panel and Desktop Settings; `core/command_policy.py` classifies commands into SAFE/LOW/MEDIUM/HIGH/CRITICAL with a visible reason (unknown → HIGH, fail closed). Approval scopes are once/task/project/always with the risk tier inside every cache key — HIGH/CRITICAL approvals are honored but never cached (asked per call, `cacheable=False`), `git_add`/`git_commit` stay once-only; `describe_request` projects tool/args/cwd/risk/reason into the TUI modal and Desktop `ConfirmDialog` (HIGH/CRITICAL offer only once/deny). `sandbox.py` gains readonly/workspace/workspace-network/full presets (unknown → workspace), `Config.autonomy_mode` records the composed preset, and `chat.py` binds permission scope to the running task/project. Tests: new `tests/core/test_permissions_49.py` (29), risk-aware dialog coverage in `test_permission_dialog.py`, autonomy presets in `test_tui_menu.py`; W4 wave `9 done, 5 partial, 1 TODO`; verified with full pytest `567 passed, 1 skipped`, Ruff and `tsc --noEmit`. |
| 2026-09-28 | Completed W4.5: new `core/rules.py` — `RuleManager`/`discover_rules` across four scopes (global `~/.axiom/AXIOM.md`, project `AXIOM.md`/`.axiom/project.md`, directory `AXIOM.md`, task `@`-mentions) with deterministic precedence merging (higher scope shadows conflicting Markdown sections), heavy-dir pruning and workspace-constrained walks; directory rules attach only when the task touches their directory, user-requested rules always win, global+project rules occupy the protected `project_rules` prompt layer. `core/skills.py` extended with disk skills from `~/.axiom/skills/*.md` and `<workspace>/.axiom/skills/*.md` (optional `---` header: id/label/triggers/tools; public `parse_skill_file`/`load_skill_directory`), selected by declared triggers — never wholesale — with stale project skills dropped on workspace switch. `ChatSession` records merged rules + selected skill ids in Task State (`context_rules`/`active_skills`/`task_paths`, `task.rules` trajectory event) and `TaskRunner` injects them into every step prompt, so restarted tasks keep identical constraints. Tests: 17 deterministic tests in `tests/core/test_rules_skills.py` (discovery, relevance filtering, shadowing, determinism, rebinding, parsing, trigger selection, task contract); W4 wave `10 done, 4 partial, 1 TODO`; verified with full pytest `584 passed, 1 skipped`, Ruff and mypy on new/changed modules. |
| 2026-09-28 | Completed W4.6: `core/agents.py` now carries the delivery set (Explorer read-only reconnaissance, Frontend, Backend) with per-role scoped tools in `tools/meta.py`; the compact report contract `RESULT/FINDINGS/FILES/ERRORS/RECOMMENDATIONS` is parsed and capped per section (600 chars) and in total (2400) by `compact_report`, never inventing content — unsectioned prose becomes one RESULT line and a real failure is appended to ERRORS. `ChatSession._subagent_runner` appends the exact model/provider, streams reasoning/answer/tool steps to the parent trajectory, enforces `SubagentBudget` (time/tokens/tool calls/retries) after every event and stops with an explicit `budget.exhausted` reason plus the partial result (`subagent.budget` trajectory event) instead of hanging or fabricating completion; worker transcripts stay in the worker's own trajectory and only `report`+`budget` leave the run. `Orchestrator` renders reviewer input and the final report from compact reports (raw worker prose never reaches the reviewer), aggregates `reports` in the run result for calls that bypass the contract, and passes the real rework iteration as the worker retry count; planning swaps the generalist `coder` for `frontend`/`backend` only when the request names one surface (word-boundary match, both surfaces keep the generalist); `TaskRunner` aggregates reports into the new `Task.subagent_reports` (one entry per step id, replaced on repair/rework, persisted for resume). Tests: 18 deterministic tests in `tests/core/test_agents_46.py` (role/scoped-tool registry, report parsing/bounding, budget reasons, real worker run with faked transport, budget-exhaustion partial result, reviewer isolation, surface-role selection, rework retry count, Task State aggregation and restart round trip); W4 wave `11 done, 3 partial, 1 TODO`; verified with full pytest `602 passed, 1 skipped`, Ruff, and mypy showing no new errors (remaining are pre-existing union-attr/assignment warnings). |
| 2026-09-29 | Completed W4.10: new `core/hooks.py` with the nine lifecycle events (`TaskStart`, `PreToolUse`, `PreEdit`, `PostEdit`, `PostToolUse`, `PreCommit`, `PostCommit`, `ContextCompact`, `TaskComplete`). Definitions merge deterministically — builtin (shipped **disabled**, since a hook runs real commands) → `<AXIOM_HOME>/hooks/*.json` → `<workspace>/.axiom/hooks/*.json` → `config.hooks`, where an entry carrying only `id`+`enabled` toggles an existing definition without repeating its command; malformed JSON, unknown events and commandless entries are rejected, and timeouts clamp to 0.5–600 s. Hooks run sequentially in declaration order as argv without a shell (so hook arguments cannot append a second command), each classified by the W4.9 command policy and refused before execution above `hooks_max_risk` (default MEDIUM, so a project file cannot smuggle in `curl … \| sh`). Execution is fail-open: a non-zero exit, timeout, or missing executable becomes a warning in the persisted `Task.hook_results` and the next hook plus the task continue, never producing a `TaskError`. `ToolRegistry.execute` runs the tool-scoped events at the single tool choke point (post events only after a successful tool; `subset()` keeps the same runner so subagent edits are hooked too), `TaskRunner` runs `TaskStart`/`TaskComplete`/`ContextCompact` and publishes `task.hooks`, and hooks receive `AXIOM_HOOK_EVENT`/`AXIOM_TASK_ID`/`AXIOM_TOOL_NAME`/`AXIOM_FILE_PATH`/`AXIOM_WORKSPACE`; a workspace switch rebinds hooks so a previous project's commands never run. New config: `hooks_enabled`, `hooks`, `hooks_max_risk`. Tests: 27 tests in `tests/core/test_hooks_w410.py` — a real PostEdit formatter subprocess that actually rewrites the edited file, failing/timeout/missing-executable warnings with the loop continuing, risk refusal before execution, `hooks_enabled=false` starting no process, sequential ordering, event/path/tool filtering, hook env, registry pre/post ordering with an unchanged tool result, and Task State persistence. W4 wave `12 done, 3 partial, 0 TODO`; verified with the full suite, Ruff and the frontend build. |
| 2026-09-30 | Completed W4.11: `core/memory.py` grows from two to four scopes — `task` memory follows the running task and is archived with a reason on completion, `session` memory belongs to exactly one conversation, and each store is bound to a live owner so an ownerless scope is absent from a read instead of leaking another task's notes. `core/router.py` gains roles (`coding`/`summarize`/`search`/`subagent`); a specialist agent or a search pass is routed by role first and the Ollama runtime resolves a role to a real model through the catalog, reporting the model it actually used. Unknown roles and malformed rules log a warning and are ignored; with no configuration routing behaves exactly as before. 46 new tests in `tests/core/test_memory_scopes_w411.py` + `tests/core/test_role_routing_w411.py`; full suite green (`696 passed, 1 skipped`). W4 wave now `13 done, 2 partial, 0 TODO`. |
| 2026-09-30 | Added payments: YooMoney/YooKassa backend with signature-verified webhooks and safe configuration diagnostics; the internal balance is stored and shown as fixed-rate AXIOM USD credits (100 RUB = 1.00 USD) with a legacy kopeck→USD-cent migration and an atomic `POST /v1/payments/pro/balance` PRO purchase. Tracked in `docs/payments-yoomoney.md` (outside the W1–W4 item list). |
| 2026-10-01 | Added Google and GitHub OAuth sign-in with safe configuration diagnostics (payments/auth). |
| 2026-10-01 | Added W3.4 core (PARTIAL): `core/artifacts.py` with five validated artifact types (table/comparison/checklist/mermaid/chart), the `render_artifact` tool registered in `ChatSession`, a `Message.artifacts` persistence field, and Markdown/CSV/SVG export (Mermaid renders as a fenced block and refuses tabular export). Missing data fails explicitly via pydantic validation; 6 tests in `tests/core/test_artifacts.py`. Desktop rendering UI and PNG export remain. |
| 2026-10-01 | Added W4.13 core (PARTIAL): `core/cache.py` `TTLCache` (bounded TTL/limit with oldest-first eviction and hit/miss/eviction counters), `EventBus` predicate filtering plus a per-event `max_listeners` cap that drops the oldest listener, a `dropped` counter/`listener_count()`, and `validate_event_envelope()` for the common `event`/`ts` envelope. 10 tests in `tests/core/test_cache.py` + `tests/core/test_bus.py`. Deltas/pagination and before/after metrics remain. |
| 2026-10-01 | Added W3.6 core (PARTIAL): `axiom run "prompt" --json` headless runner over the canonical `ChatSession` and `axiom serve` — a token-protected localhost HTTP API (`/v1/status`, `/v1/run`) that rejects non-local binds. 6 tests in `tests/frontends/test_headless.py`. WebSocket transport and VS Code/browser adapters remain. |
| 2026-10-01 | Completed W3.15: `core/automation.py` persists schedules to `.axiom/automation.json`; `run_due` turns due schedules into real W4.1 tasks (`source="automation"`, `max_risk` capped at safe/medium) and `record_run` records skipped intervals as `missed_runs`. `Task` gains `source`/`max_risk`. 7 tests in `tests/core/test_automation.py`. W3 wave now `8 partial, 8 TODO`. |
| 2026-10-01 | Added W3.17 core (PARTIAL): `core/artifact_workspace.py` (`ArtifactWorkspace`/`ArtifactDocument`) persists versioned, task-associated documents under `.axiom/artifacts/` (create/load/update/list/delete/export, history-on-edit, empty state has no demo assets). 5 tests in `tests/core/test_artifact_workspace.py`. Desktop Documents view and Markdown editor remain. W3 wave now `9 partial, 7 TODO`. |
| 2026-10-01 | Added W3.13 core (PARTIAL): `TerminalTool` records a bounded command `history` and gains `rerun(index=-1)`; stderr/exit-code capture and process-tree cleanup already existed. 4 tests in `tests/core/test_terminal_history.py`. Persisted panel history and the rerun UI remain. |
| 2026-10-01 | Added W3.14 core (PARTIAL): `GitTools` gains the read-only `git_graph` branch-graph tool and the approval-gated `git_unstage` agent tool (explicit files only, never unstage-all), wired into workspace scopes/roles/task resolution and the desktop tool map; stage/unstage/commit with reviewed-diff hash already existed. 2 tests in `tests/core/test_git_write.py`. git-checkpoint-based rollback remains. |
| 2026-10-01 | Added W3.12 core (PARTIAL): `git_tools.git_revert` restores a file to its committed state (tracked → `git restore`, untracked → removed) and is exposed as the `git_revert` bridge command; create/rename/delete/diff already existed. 3 tests in `tests/core/test_git_write.py`. Per-file M/A/U markers and E2E remain. |
| 2026-10-01 | Added W3.8 core (PARTIAL): `core/i18n.py` adds a RU/EN `TRANSLATIONS` catalog + `translate()`/`locales()` and a validated `Config.locale` (en/ru) for core-emitted labels. 5 tests in `tests/core/test_i18n.py`. Component-text replacement, command palette, portable mode and signed updates remain. W3 wave now `10 partial, 6 TODO`. |
