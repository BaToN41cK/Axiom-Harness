# Changelog

Этот файл — единый журнал изменений AXIOM. До появления первого формального релиза
новая работа добавляется в раздел `Unreleased`. После релиза его содержимое
переносится в версионный раздел, а текущий `Unreleased` снова начинается с пустого.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии — на [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Added — Bundled system plugins (5 built-ins, W1.4)

- new bundled catalogue at `src/axiom/plugins/bundled/` with 5 ready-to-use
  system plugins, all disabled until the user installs them:
  - `calculator` — safe AST-based expression evaluator (`calculate`; no `eval`,
    supports sqrt/sin/cos/log/floor/ceil/pow and constants pi/e/tau);
  - `datetime` — current time in any IANA time zone and date differences
    (`current_time`, `date_diff`);
  - `notes` — persistent tagged notebook in `~/.axiom/notes/notes.md`
    (`note_add`, `note_list`);
  - `texttools` — text statistics, case/slug/reverse transforms and
    base64/base64url/hex/url/html encode+decode (`text_stats`,
    `text_transform`, `encode_text`);
  - `security` — UUID v4 generation, md5/sha1/sha256/sha512 checksums and
    secrets-based strong passwords (`generate_uuid`, `hash_text`,
    `generate_password`);
- `PluginManifest` gained a persisted `bundled` flag; `PluginManager` gained
  `bundled_manifests()` (validated catalogue of not-yet-installed built-ins)
  and `install_bundled()` (atomic copy into `~/.axiom/plugins`, idempotent,
  preserves enable state, loads real tools immediately);
- bridge commands `bundled_plugins` and `install_bundled_plugin`; Desktop
  settings show an "Встроенные плагины AXIOM" catalogue with one-click install
  and a "встроенный" badge on installed ones; removing a built-in returns it
  to the catalogue (Desktop and TUI);
- TUI `/plugins` lists built-ins with `○ (built-in, not installed)`, `i`
  installs the highlighted one without a folder path, `d` refuses to remove
  uninstalled entries, and removal restores the catalogue entry;
- 6 new unit tests (bundled catalogue, install/load/idempotence, unknown name,
  removal round-trip) and 3 bridge integration tests (real catalogue listing,
  install → tools live → toggle → remove → back in catalogue, name validation).

### Added — Plugin Manager v0 Live Reload (W1.4)

- `discover_plugins` bridge command is now a real live reload: it re-reads the
  persisted registry, picks up folders the user copied into `~/.axiom/plugins`
  while the app was running, and registers enabled plugins' real tools/skills,
  returning both the newly discovered names and the full current plugin list;
- Desktop `useAxiom.loadPlugins` calls `discover_plugins` (instead of the plain
  `list_plugins`) and announces each newly found plugin; a background poll runs
  every 2.5 s only while the Plugins settings section is open, so a manually
  dropped folder appears without a restart (quiet path — no toasts on the timer);
- TUI `/plugins` now runs `load_plugins()` before showing the panel, so the
  terminal frontend also sees manually copied folders without a restart;
- added 4 bridge integration tests: full install → list → toggle → remove
  round-trip, idempotent reinstall, missing-path/unknown-name error shapes, and
  `discover_plugins` picking up a manually dropped folder;
- updated `docs/roadmap.md`: W1.4 status changed from PARTIAL to DONE. Verified
  with `392 passed, 1 skipped`, Ruff, and the Desktop build.

### Added — Live Thinking Phase and Elapsed Timer (W1.3)

- added real elapsed timer to TUI StatusBar, AssistantMessage, and ReasoningPanel:
  StatusBar and AssistantMessage now track `_started` wall-clock time when transitioning
  to busy, display live `X.Xs` elapsed during active phases, and pass it to `status_line`;
- replaced TUI AssistantMessage's `tick * 0.12` approximation with real
  `elapsed_since(_started)` so `◌ Thinking 4.8s` shows honest wall-clock time;
- ReasoningPanel title now shows live elapsed: `◌ THINKING · 4.8s` while active,
  collapsing to `✓ THINKING · 4.8s` on completion (duration measured from first append);
- added `elapsed` parameter to `shared.formatting.status_line()` (only displayed when
  active and non-None); Desktop already had real elapsed timer via `elapsedMs` state;
- added 5 deterministic tests for `status_line` elapsed behavior (active/inactive/None/zero/with-duration);
- updated `docs/roadmap.md`: W1.3 status changed from PARTIAL to DONE, wave summary
  updated to `1 partial, 3 done, 1 TODO`.

### Added — Search Connectivity and a Real Search Test (W1.2)

- added the validated `search_provider` config field (`auto`, `brave`,
  `duckduckgo`, `searxng`, `wikipedia`): `auto` keeps the resilient
  Brave → DuckDuckGo → SearXNG → Wikipedia chain, any other id pins a single
  engine so a user can dodge a blocked provider;
- added `build_search_provider()` / `search_provider_choices()` in
  `core/search/multi.py` and `ChatSession.search_test()` — an honest connectivity
  probe returning `ok`, the engine that answered, measured latency, result count
  and the real error/hint instead of a fabricated "Online" state;
- exposed `search_providers` and `search_test` bridge commands; `set_config`
  now rebuilds the live search backend in place via `_rebuild_search_provider()`
  so a provider/timeout change applies without a restart;
- Desktop Tools settings gained an engine dropdown and a real test button
  (status, latency, results or error); TUI gained `/searchtest` with a
  `SearchTestPanel` and the `/status` panel now names the configured engine;
- covered the builder, `search_test` success/timeout/empty-query paths, and the
  two new bridge commands with deterministic tests (local fakes, no network).

### Added — Configurable Accent and Panel Hover (W1.1)

- added validated `accent` presets (`garnet`, `blue`, `teal`, `violet`) and the
  `panel_hover` preference to `Config`, Desktop types, Settings, and the JSONL bridge;
- applied the selected accent without restart to Desktop light/dark CSS variables and
  the Textual theme, with hover highlighting independently switchable in both frontends;
- recorded WCAG contrast checks for both semantic roles: light-mode foregrounds on white
  are garnet `#9F3542` — 6.86:1, blue `#1F58DB` — 6.04:1, teal `#0D6D66` — 6.18:1,
  violet `#7434DF` — 6.36:1; dark-mode foregrounds on `#0A0A0A` are garnet `#D27882`
  — 6.36:1, blue `#6B9BFF` — 7.31:1, teal `#56B8AE` — 8.36:1, violet `#B18CFF`
  — 7.60:1. Filled controls use separate dark tokens with white text; all meet AA 4.5:1;
- added Config persistence and bridge round-trip coverage for both new fields.

### Added — Persistent Task Runtime and Planner

- added `core/tasks.py` with persistent `Task`/`TaskState`, atomic JSON checkpoints,
  structured `TaskError`, changed-file tracking, verification reports and typed
  `task.*` EventBus/trajectory events separate from chat history;
- added `core/planner.py` with complexity thresholding, strict JSON plan validation,
  definition-of-done criteria and bounded replan that preserves completed steps;
- added `ChatSession` task lifecycle methods and bridge commands `task_start`,
  `task_cancel`, `task_resume`, `task_state` and `tasks`;
- added Desktop Task Panel for real task steps, tool outcomes, errors, checks,
  cancellation and explicit acknowledgement before resuming an interrupted tool;
- added process-group cleanup for cancelled terminal/verification subprocesses and
  acceptance tests covering real file editing, pytest verification, restart/resume,
  event ordering and no replay of completed tasks;
- task completion remains conservative: missing checks, failed checks or a missing
  reviewer verdict produce `waiting_for_user`, never a fabricated success.

### Added — Production-grade Verification Tools and Runtime Pipeline

- added `VerificationTools` (`run_tests`, `run_linter`, `build_project`, `verify_changes`)
  with automatic multi-language runner detection (pytest, jest, cargo test, go test, npm test,
  ruff, flake8, eslint, cargo check, tsc, cargo build, go build, npm build);
- `verify_changes` plans and executes minimal targeted verification workflows based on
  modified files from git diff (e.g. testing only modified Python/TypeScript modules);
- verification tools respect workspace scoping and terminal execution policies: disabled
  automatically in read-only mode or when terminal execution is turned off;
- unified verification integration into `ChatSession`, `Agent`, `VerificationLoop`,
  and meta tool catalogs (`inspect_tools`);
- added test suite `tests/core/test_verify_tools.py` validating auto-detection, execution,
  git-diff targeted planning, and terminal security constraints.

### Added — Tool Runtime Metadata & Filesystem/Patch Tools Upgrade

- enriched `ToolDefinition` with operational metadata: `risk` (`safe`/`medium`/`dangerous`),
  `timeout`, `max_output`, `streaming`, `cancellable`, `dry_run`, `rollback`, and
  `workspace_scoped` without mutating the external model function-calling JSON schema;
- exposed tool operational metadata through `.meta()` and `tools_info()` for UI and diagnostics;
- enhanced `read_file` with line range slicing (`offset`, `limit`), optional line numbering
  for precise diff references, and binary file detection;
- enhanced `write_file` and `edit_file` with `dry_run` support and detailed diff metrics
  (`additions`, `deletions`, `unified_diff`);
- enhanced `search_text` with regex pattern support and line context window extraction;
- implemented strict unified diff applicator in `apply_patch` preserving line endings (CRLF/LF)
  and validating hunk offsets;
- added operational tests in `tests/core/test_tools_registry.py` and `tests/core/test_workspace_tools.py`.

### Added — Live orchestration progress (Desktop)

- the desktop `orchestrate` bridge now streams live progress while the workers
  run: a watcher polls the session trajectory (plan, worker start/done, tool
  calls/results, review iterations, verification) and forwards each new step
  as an `orchestration` event instead of leaving the UI on «Подключается…»
  until the single final reply minutes later;
- workers record their tool activity on the shared trajectory as
  `subagent.tool.call`/`subagent.tool.result` the moment it happens (the
  first file write becomes visible within seconds); the end-of-run child merge
  no longer duplicates `tool.call` entries;
- every specialist also publishes `subagent.model` (`provider/model`) before
  its first token, so the live feed says exactly which model is working;
- worker text is streamed live too: `subagent.reasoning` (model thinking) and
  `subagent.answer` (prose of each pass) are flushed at every tool call and at
  run end — a flat ≤300-char preview goes into the feed, the full text stays
  in `data` for the trajectory viewer;
- Desktop renders the live feed: the status pill shows
  «Оркестрация: coder — write_file index.html»/«думает…»/«пишет…»/«review…»/
  «verification…» instead of leaving the user on an unrelated status;
- `/orchestrate` starts with «Оркестрация: план…» instead of a misleading
  «Подключается…» for the whole run (a normal `send` keeps its own statuses);
- the explorer refreshes itself after an orchestration (and, throttled,
  whenever a worker really writes/edits a file) — new files appear without a
  core or app restart;
- added `test_progress_events_forward_only_new_orchestration_steps`,
  `test_watch_orchestration_streams_live_trajectory_steps` and
  `tests/core/test_orchestrator_runtime_d.py` (live, non-duplicated worker
  tool, model, reasoning and prose events).

### Added — Orchestration board in the Desktop chat

- the emoji progress lines are gone: every `orchestration` event is now reduced
  into a typed `LiveMessage.orchestration` state (`desktop/src/lib/orchestration.ts`)
  instead of being appended to the message text;
- new `OrchestrationBoard` renders that state: a header with the real task,
  elapsed time and a phase rail (План → Работа → Review → Проверка → Итог),
  adaptive worker cards (id, `provider/model`, live action, tool counters, its
  own last thought/answer on demand) and a collapsible tool timeline with
  category icons (read/write/search/web/fetch/terminal/git/folder/verification);
- `subagent.reasoning`/`subagent.answer` no longer spam the feed: each worker
  keeps only its latest segment, expanded per card;
- the final sections are rendered as cards — agent reports (with provider/model
  and tool counters), Reviewer verdict with `REWORK` issues/required changes,
  Verification `PASSED`/`FAILED` and Definition of Done — instead of a Markdown
  dump; a failed or cancelled run is surfaced explicitly;
- `content` still carries a compact Markdown summary generated from the same
  state, so a reloaded chat (history stores text only) stays readable and the
  structured board remains the primary rendering.

### Fixed — Orchestrator runtime gaps

- `ChatSession._subagent_runner` now gives every specialist an isolated bus,
  permissions cache, sandbox, trajectory, router, catalog and skills object;
  agents share only transport and stateless tool handlers;
- worker trajectories are merged back into the orchestration trajectory as
  `subagent.*` events, so planning, tool calls, errors and reviews are recoverable;
- `Orchestrator._review_decision` accepts the structured
  `approved/reason/issues/required_changes` JSON contract (including fenced
  payloads) in addition to legacy `APPROVED/REWORK` markers;
- review failures are structured rework instead of an unhandled exception;
- rework tasks now carry reviewer issues/required changes, rework emits
  `review.rework`/`review.rework_limit`, and iterations are hard-capped at three;
- orchestration results expose `completed`, `iterations`, `review_details`,
  worker provider/model and tool counters; failed verification is an honest
  incomplete result instead of silent success;
- `run_orchestrated()` marks the session busy for the whole run and always
  releases it, so Desktop/TUI accept the next command afterwards;
- the desktop `orchestrate` bridge reply serializes the trajectory viewer
  instead of returning a non-JSON live object;
- Desktop/TUI orchestration reports now render reviewer verdict details,
  verification outcome and worker provider/model;
- added `tests/core/test_orchestrator_runtime_{a,b,c}.py` covering real
  subagent execution, role-scoped metadata, real file mutation, rework
  reruns/bounds, verification honesty, isolation, external-model routing and
  busy-lock release (LLM transport is the only fake).

### Fixed — Orchestration stop/cancel and route reporting

- `/orchestrate` now runs as a real asyncio task owned by the session, so
  Esc/«Стоп» (TUI and the Desktop `cancel` command) actually stops the
  workers, records `orchestration.cancelled` in the trajectory, and returns a
  structured `{cancelled: true}` result instead of leaving detached tasks
  running;
- a stopped orchestration renders as "остановлена пользователем" in both
  TUI and Desktop instead of surfacing as an error;
- `run_parallel()` keeps `status: done` authoritative and propagates
  `CancelledError`, so worker output can no longer flip the status back and
  cancellation is never swallowed as a failed worker;
- `ProviderChatClient` fills `last_route` for the Ollama route and refreshes
  it on retry/fallback, so orchestration reports always show the provider and
  model that actually answered;
- `ProviderChatClient._target()` accepts a model name or a `ModelInfo` and
  falls back to the default route when the router returns an empty model;
- empty `/orchestrate` requests are rejected with a usage hint;
- added `test_runtime_cancel_stops_orchestration` (stop → cancelled result →
  busy-lock release → trajectory event).

### Added — Reliable agent/project editing

- `Agent` now receives the active `PermissionManager`, so workspace tools are
  permission-aware across `ask`, `auto_approve_safe`, and `auto_approve_all`;
- workspace `read_file`, `list_files`, `search_text`, `search_files`, `edit_file`,
  and `write_file` remain available inside the selected project sandbox;
- added an end-to-end regression test covering model tool call → permission →
  `WorkspaceTools` → real file mutation → final model response;
- `ToolRegistry.permission_for()` provides one effective permission policy for
  all runtime tool callers;
- `VerificationLoop` is connected to the real workspace `TerminalTool` runner.

### Added — Agent observability and loop protection

- generation `Done` events now expose `stopReason` (`completed` or
  `tool_round_limit`);
- duplicate identical tool calls within one turn are suppressed and returned to
  the model as structured errors instead of being executed repeatedly;
- coding-task recovery now includes common English verbs as well as Russian
  edit requests.

### Fixed — Provider resilience and external-only sessions

- transient provider failures (`429`, timeout, `5xx`, connection errors) are
  retried once with a short delay before fallback; `401`/`403` are not retried;
- desktop boot no longer fails solely because Ollama is unavailable when an
  external provider route is configured;
- Ollama model discovery is best-effort, while the active external model remains
  available in the model selector;
- reconnecting Ollama preserves Agent permissions, router, bus, trajectory,
  sandbox, skills, verifier, and provider runtime;
- `set_config` updates the Agent's internal config and workspace access/runtime
  components consistently.

### Security

- writes/edits to `.env*`, SSH keys, and common certificate/key files are
  rejected with a clear error message.

### Fixed — Desktop provider/model UX

- model selection keeps provider identity separate from model name, including
  external models such as `openai_compatible/deepseek/deepseek-v4-flash`;
- provider errors and model-selection errors remain visible in the selector and
  do not silently fall back to Ollama;
- existing slash-command suggestions and file opening in Explorer remain intact.

### Added — Predictable desktop workspace UX

- the top bar now always shows the active provider/model and whether workspace
  tools are available;
- Explorer now has debounced project search with clickable file results;
- Explorer empty states explain the next action instead of showing generic text;
- the composer displays a compact Last action summary after real tool results;
- tool activities are now collapsible, while running/failed actions remain open;
- generation stop reasons are shown when a run ends due to the tool-round limit.

### Fixed — Desktop observability

- project search now preserves line context in the result preview;
- project search is debounced and only runs for an open workspace;
- external/API-only sessions keep the same project/status information as Ollama
  sessions;
- status and tool events remain sourced from the real core event stream.

### Added — File-scoped project context

- `@file` autocomplete selects real files only from the currently open workspace;
- explicitly mentioned files are expanded for the model, while the project tree is
  not dumped into the prompt;
- each turn adds a bounded focus-file list to the model context;
- duplicate, invalid, outside-workspace, and binary mentions remain harmless;
- the agent can then address the selected files with `read_file`, `search_text`,
  `edit_file`, `write_file`, and `run_command` without requiring a full-project
  read.

### Added — Orchestrator workflow

- `Orchestrator` now plans dynamic specialist roles with a hard maximum of five
  subagents per iteration;
- added the `analyst` role and scoped project-inspection tools for requirements
  and architecture discovery;
- specialist agents receive role-specific tools instead of the same broad tool
  set for every task;
- reviewer reports are collected after worker results, with `APPROVED` /
  `REWORK` decisions recorded in trajectory;
- definition-of-done criteria and review verdicts are returned with orchestration
  results for GUI/TUI consumers;
- parallel orchestration continues to preserve isolated configs, registries,
  machines, trajectories, routers, catalogs, skills, and sandboxes;
- tests cover five-agent planning, analyst scope, and reviewer rework requests.

### Added — Orchestrator production pipeline

- orchestration now runs the existing `ChatSession` subagent path, with isolated
  configs, tool registries, state machines, trajectories, routers, catalogs,
  skills, permissions, and sandboxes per specialist;
- each specialist receives a role-specific system instruction and scoped tool set;
- orchestration has a structured review contract (`approved`, `reason`, `issues`,
  `required_changes`) and records planning, agent completion/failure, review,
  rework, verification, and completion in EventBus/Trajectory;
- `REWORK` re-runs the worker roles with the reviewer's required changes and is
  bounded to three iterations;
- approved orchestration runs the real workspace `VerificationLoop`; failed or
  missing verification is returned as an honest incomplete result;
- the user-facing result includes worker reports, reviewer verdict, verification,
  and Definition of Done;
- existing four-worker `run_parallel_agents()` behavior remains backward-compatible,
  while `/orchestrate` uses the bounded five-role workflow;
- added deterministic integration tests for multi-agent execution, rework,
  approval, bounded retries, verification, and orchestration events.

### Fixed — Orchestrator command delivery

- `/orchestrate` is now registered in both desktop Composer autocomplete and the
  canonical TUI command registry;
- both frontends execute the real `ChatSession.run_orchestrated()` bridge path
  instead of treating the command as an unknown or decorative command;
- the TUI command is included in help/autocomplete and reports specialist results,
  reviewer verdict, and Definition of Done.

### Fixed — Orchestrator interaction and external-model sessions

- slash command completion no longer turns `/orchestrate <task>` back into a
  hanging bare command when Enter is pressed;
- orchestration now supports a selected external model even when Ollama itself
  is unavailable;
- after orchestration the UI releases the generation lock, clears the busy
  state, and allows the next task to be submitted;
- orchestration reports reviewer and Definition of Done results to both Desktop
  and TUI.

### Fixed — Desktop and TUI command delivery

- `/orchestrate` is present in the canonical TUI registry, TUI help/autocomplete,
  and Desktop Composer suggestions;
- command completion distinguishes selecting a command from executing a command
  with an argument, so `/orchestrate <task>` is submitted instead of being reset
  or left in a busy state;
- orchestration releases the UI generation lock and permits the next task after
  completion;
- external-provider sessions can start orchestration even when Ollama is offline;
- Desktop and TUI display specialist reports, reviewer verdict, and Definition of
  Done after the workflow finishes;
- rework requests are sent back to the selected worker roles for up to three
  bounded review iterations;
- the changelog records the current provider, workspace, agent-loop, GUI, command,
  and orchestration changes under `Unreleased`.

### Verification

- full Python suite: `297 passed, 1 skipped`;
- Ruff: `All checks passed`;
- Python compile check: passed;
- desktop TypeScript/Vite production build: passed;
- `git diff --check`: passed.

### Added — Desktop provider/model controls

- Desktop Settings now expose real provider status, hidden API-key input, endpoint
  configuration, provider testing, model discovery, and model selection;
- OpenAI Compatible is available as a first-class provider in the desktop
  provider list, including custom endpoints such as `https://api.mixen.ai/v1`;
- the model selector now switches between Ollama models and external routes while
  preserving `providerId` and the external model source;
- desktop slash commands expose `/permissions`, `/profiles`, `/trajectory`,
  `/providers`, and `/agents` without breaking the existing command suggestions.

### Fixed — Agent project-edit loop

- coding requests that initially return only a plan now receive a bounded
  follow-up instruction to perform the requested edit;
- failed tool results, including missing files and directories, are passed back
  to the model so it can recover with `list_files`/`search_files`;
- task detection now covers common Russian edit requests such as «сделай»,
  «добавь», «исправь», «доработай» and «улучши».

### Fixed — External provider routing

- the Tauri bridge accepts both `provider_id` and `providerId`, preventing
  external models such as `openai_compatible/deepseek/deepseek-v4-flash` from
  being incorrectly sent to Ollama;
- external model warm-up is skipped, and status/stream responses retain the
  active external provider metadata;
- model refresh and `/model` selection distinguish providers when Ollama and an
  external provider expose the same model name.

### Fixed — Workspace and documentation

- stale configured workspace paths are discarded when the directory no longer
  exists, so Explorer and filesystem tools use the current project instead of a
  removed temporary directory;
- desktop configuration documentation now links to the repository-level
  `assets/Settings.png` image using a correct relative path.

### Added — Performance Engine (latency/reasoning pipeline)

- deterministic task policy в `axiom.core.performance`: `classify_mode()` (quick → один
  проход без инструментов; agent → tool loop), `complexity_of()`, `thinking_level()`,
  `tool_scope()`, `adapt_level()` — без дополнительного LLM-вызова;
- `thinking_level()` сохраняет прежнюю эвристику (hard → high, long → medium,
  small talk → low), учитывает `fast`/`normal`/`deep`, `economy` и **реальные**
  измерения прошлого запуска (TTFT, tok/s) через `adapt_level()`;
- `Agent._think_param()` берёт уровень из Performance Engine и корректирует его по
  `last_metrics` (медленный прошлый запуск → ниже reasoning);
- `Agent._tool_schemas()` переведён на `tool_scope()`: workspace/git/terminal tools
  рекламируются строго по типу запроса (файл → read-tools; правка → read+edit;
  git → git-tools; терминал → `run_command`); две web-инструмента всегда доступны,
  как и раньше;
- выбранный режим (`policy.mode` + complexity) пишется в Trajectory для наблюдаемости.

### Added — Provider settings (API keys, test, model discovery)

- `ProviderManager.set_key()` / `has_key()`: ключ сохраняется локально в
  `~/.axiom/providers.json`, назад в UI никогда не отдаётся;
- `ProviderManager.model_rows()`: discovery моделей провайдера как UI-строки с
  реальными capabilities (`coding`, `reasoning`, `tool_calling`, `long_context`,
  `vision`) и `context_length`;
- `ProvidersPanel` получил скрытое поле ввода ключа (`Input(password=True)`),
  кнопки **Save key & test** и **Discover models**, а также список найденных
  моделей с назначением маршрута по выбору (`router_primary`);
- TUI-команда `/providers` прокидывает реальные колбэки сохранения, проверки,
  discovery и выбора модели.

### Added — TUI `/permissions`

- `PermissionsPanel`: реальные режимы `ask` / `auto_approve_safe` /
  `auto_approve_all`, выбор применяется к действующему `PermissionManager`
  (и сохраняется в конфиг), а не только показывается уведомлением.

### Added — Context auto-narrowing

- `ChatSession._context_budget()` возвращает **реальный** бюджет окна только если
  он известен: explicit `num_ctx` → эффективный `num_ctx` модели → её
  `context_length`; при неизвестном бюджете ничего не выдумывается;
- `ChatSession._context_messages()` при известном бюджете дополнительно сужает
  отправляемую модели историю через существующий `ContextManager`
  (trajectory и сохранённый разговор остаются целыми), а факт сужения
  записывается событием `context.narrow` с реальными оценками до/после.

### Added — Agent Harness

- единый `Provider` contract и adapters для Ollama, Anthropic и OpenAI-compatible API;
- `ProviderManager`, model discovery, `ModelCatalog` и `ModelProfile`;
- реестр ролей: orchestrator, coder, debugger, reviewer, researcher, tester,
  architect, security;
- scoped tool metadata и выбор инструментов под задачу;
- `EventBus` для agent/model/tool/test/file/trajectory событий;
- `Orchestrator`, subagents, последовательная и параллельная композиция;
- `ContextEngine` для истории, workspace, git diff, skills и tool results;
- append-only `Trajectory` и JSONL store с save/load/resume/fork/replay/search;
- `VerificationLoop` для build → test → lint;
- `Sandbox` с permission levels и политиками ask/auto/deny;
- skills для Python, React, TypeScript, Rust, Tauri, Git, Docker, Testing,
  Debugging, Security и SQL;
- MCP stdio client и plugin registry;
- `ModelRouter` с task classification, budget mode и fallback chain;
- project intelligence и project memory в `.axiom/`;
- Code/PTC program parsing и выполнение tool steps;
- TUI slash-команды для permissions, profiles, trajectory, providers и agents.

### Added — Observability и performance foundation

- единый `PerformanceMetrics`, связанный с реальным streaming path `Agent`;
- измерение request/prompt/HTTP/first chunk/first visible token/last token/finish;
- TTFT, visible TTFT, generation duration и AXIOM parser overhead;
- prompt/eval/load/total durations и token counts из Ollama, когда они доступны;
- generation throughput и отдельные thinking/answer token metrics;
- tool/context/continuation counters;
- агрегация multiple runs, mean/median/min/max, cold/warm classification и
  measurement-based diagnosis;
- unit-тесты расчётов, fallback timing, streaming states, aggregation и agent metrics.

### Changed

- `ChatSession` собирает общий runtime из Agent, providers, registries, trajectory,
  context, verification, sandbox, skills, router, project memory и plugins;
- model warm-up и `keep_alive` сохранены в существующей Ollama-конфигурации;
- контекст, tools и permissions ограничиваются workspace policy до выполнения;
- Tauri bridge и TUI используют типизированные runtime-атрибуты;
- README расширен архитектурой, статусом, возможностями, данными и workflow.

### Security and safety

- `DENY` блокирует tool handler до исполнения и скрывает запрещённый tool schema;
- filesystem/terminal/Git operations проходят permission и workspace checks;
- provider keys не включаются в performance/trajectory reports;
- project/runtime data остаются локальными и игнорируются Git.

### Known limitations

- live external API behavior still depends on the configured provider, endpoint,
  model capabilities, credentials, and network conditions;
- external MCP servers and community plugins still require broader live ecosystem
  validation;
- automated bottleneck classification is limited to actually measured fields and
  does not replace live measurements on a specific model and hardware;
- bundled Tauri/Vite size warnings and the pytest asyncio configuration warning
  remain non-blocking build/test warnings.

### Validation

- unit/headless test suite passes without requiring a running Ollama instance
  (`295 passed, 1 skipped` at the time of this update);
- bridge regression coverage verifies camelCase external provider selection,
  DeepSeek route persistence, skipped external warm-up, and provider-aware status;
- desktop TypeScript/Vite production build passes;
- Ruff checks for the changed Python production and test files pass;
- live API and performance measurements remain environment-dependent and are not
  claimed as CI results;

## Предыдущие ориентиры Git

Тегов релизов в репозитории сейчас нет, поэтому ниже сохранённый commit history без
придуманных version numbers.

### 2026-09-22 — Adaptive thinking и warm-up

- commit `d629e12`: adaptive thinking levels, model warm-up и answer continuation.

### 2026-09-22 — Resilience и permissions

- commit `40b3fbc`: VPN resilience, SearXNG regional fallback и TUI permissions.

### 2026-09-21 — Workspace и developer tools

- commit `dfd34e8`: workspace, filesystem/Git/terminal/project tools и desktop panels.

### 2026-09-20 — Desktop UX

- commits `f5fcd96`, `cf414ca`: полный redesign Tauri/React GUI, boot screen,
  component styling и восстановление thinking UI.

### 2026-09-18 — TUI/GUI entry points

- commit `377c3f7`: удаление отдельного CLI frontend; `axiom` запускает TUI,
  `axiom --gui` — desktop GUI.

### 2026-09-18 — Tauri migration

- commit `a6e7060`: замена Tkinter GUI на Tauri launcher, desktop app и live tests.

### 2026-09-16 — TUI, search и headless checks

- commit `25d9a5f`: TUI polish, multi-engine search, benchmark/headless smoke tests.

### 2026-09-15 — Test foundation

- commit `d9be1a9`: базовый набор core и CLI tests.

## Как обновлять

1. Добавляйте новые изменения в верхнюю часть `Unreleased`.
2. Группируйте записи по `Added`, `Changed`, `Fixed`, `Security` или `Removed`.
3. Указывайте реальные файлы/компоненты и результаты проверок.
4. Не добавляйте secrets, keys, prompts пользователей или приватные project data.
5. При первом формальном релизе перенесите секцию в `## [x.y.z] - YYYY-MM-DD`.

[Unreleased]: https://github.com/BaToN41cK/Axiom/compare/HEAD...HEAD
