# Changelog

Этот файл — единый журнал изменений AXIOM. До появления первого формального релиза
новая работа добавляется в раздел `Unreleased`. После релиза его содержимое
переносится в версионный раздел, а текущий `Unreleased` снова начинается с пустого.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии — на [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Changed — AXIOM Dark is now actually dark, plus three themes and three accents

- `styles/tokens.css` moves the default `obsidian` palette off graphite and onto near-black: the app sits on `#050506`, panels on `#0a0a0c`, insets on true `#000000`, and hierarchy is carried by three lifted steps (`#121216` elevated, `#17171c` hover, `#1f1f25` active) plus borders. Shadows barely register against black, so `--ax-elev-*` opacity went up (0.32/0.36/0.46 → 0.6/0.68/0.78) to keep modals and dropdowns detached from the page instead of floating unanchored.
- Three new themes, each reusing the same component roles rather than adding UI rules: **Graphite Grey** (`graphite`) is fully neutral with a steel accent, **Rose Noir** (`rosewood`) is near-black with a dusty rose accent, **Nord Frost** (`nord`) is cool slate with an icy blue accent. Where a theme's accent would collide with a status colour, the status moves, not the accent — `rosewood` pushes error to vermilion and warning to yellow so a failure can never read as a primary action, and `nord` shifts info to pale mint.
- Three new accents — **Серый** (`slate`), **Розовый** (`rose`), **Янтарный** (`amber`) — joining garnet/blue/teal/violet. The accent selector now also applies to `graphite`, not just `obsidian` and `light`; the light theme gets its own darker values for all three because the on-dark versions would fail AA on paper.
- Measured contrast, all above AA 4.5:1 and most above AAA 7:1. Accent text on the obsidian panel: slate 13.29, amber 12.20, rose 10.08 (garnet 8.72 for reference). Filled accent buttons against their own `--ax-text-on-accent`: slate 10.77, amber 8.94, rose 6.97. Light-theme accent text on white: slate 9.84, rose 7.88, amber 7.39. Body text on app background: obsidian 17.29, rosewood 17.06, graphite 14.61, nord 10.84; muted text on panel 6.93–8.73; theme accent text on panel 7.11–11.23.
- The preset lists are declared in one place per side and kept in step: `Config.theme` / `Config.accent` literals, `shared/theme.ACCENT_PRESETS` (so the TUI gets the three new accents too), `types.ts`, `App.tsx` theme cycle order (dark themes first, `light` last), the Settings dropdowns, `docs/configuration.md` and the `ui-polish-smoke` theme loop, which now asserts semantic surfaces for all eight themes.
- Verified: `tsc --noEmit` and `npm run build` exit 0, `ruff check src tests` clean, `tests/core/test_public_api.py` + `tests/test_bridge.py` 38 passed (the accent payload test iterates `ACCENT_PRESETS`, so it covers the new presets without editing the test).

### Changed — Payments move from the unconfirmed Sber path to YooKassa

- The Sber personal-account exploration is gone: `SberUnavailableProvider` and `PERSONAL_ACCOUNT_NOTICE` are replaced by a credential-agnostic `UnavailableProvider`, and `docs/payments-sber-personal.md` is superseded by `docs/payments-yookassa.md`. The provider-neutral contract (`ProviderPayment`, integer kopecks, `PaymentService`) is unchanged, so the switch touches no ledger logic.
- New `axiom.payments.yookassa.YooKassaProvider` implements YooKassa API v3: `POST /v3/payments` with `capture: true` and `confirmation.type = redirect`, `GET /v3/payments/{id}` for status and `POST /v3/payments/{id}/cancel`. `Idempotence-Key` is derived from our own order id (`axiom-<order_id>`), so retrying an ambiguous timeout re-reads the existing payment instead of charging the payer twice, and `metadata.axiom_order_id` ties every YooKassa payment back to one AXIOM order.
- **The secret key stays on the owner's server.** YooKassa's own quick start requires it ("Все запросы к API ЮKassa необходимо отправлять с вашего сервера"), and the key is full authority over the shop, so it is read from `AXIOM_YOOKASSA_SHOP_ID` / `AXIOM_YOOKASSA_SECRET_KEY` / `AXIOM_YOOKASSA_RETURN_URL` in the server environment — never from `config.json`, never in the Tauri/React client, and never echoed in an error message. `.env` is now gitignored with a committed `.env.example`; missing credentials fail closed with an explanation rather than raising. The desktop adapter still performs no provider call and mints no balance, because a user-controlled local process and SQLite file are not a trust boundary.
- Nothing is inferred from a provider reply: `waiting_for_capture` maps to `pending` (money held, not settled), `succeeded` counts as paid only together with `paid: true`, and an unknown status, a non-RUB currency, a payment tagged with a different order id or a `succeeded` without a capture time are all refused. A network failure is not a payment outcome — the order keeps its state and the next attempt reuses the same idempotency key.
- Tests: 16 new cases in `tests/payments/test_yookassa.py` driven through `httpx.MockTransport`, so the suite stays offline — request shape (URL, Basic auth, idempotence header, body), key reuse across retries, every status mapping, real capture time, each refusal above, readable HTTP errors that never contain the key, fail-closed without credentials, rejection of an `http://` return URL, and a settled payment crediting the wallet exactly once across repeated polls. `tests/payments` now runs 21 tests; full `tests/payments + tests/core` run is 566 passed.

### Changed — Desktop UI sounds are now distinct per event

- `desktop/src/lib/sound.ts` no longer plays one blip at different pitches. Each cue is a recipe (waveform + a short melodic figure + a per-note envelope), so events are told apart by ear, not just by number: **answer ready** is a rising two-note chime, **error** is a low falling pair on the buzzier triangle wave (the longest cue, and its whole range sits below the success chime), **permission required** is a three-note alternating nudge, **user stop** is a soft downward glide. Search, panel, settings, model and generic success keep their own shorter shapes.
- Two new cues wired to real events: `permission` fires when the core emits `permission_request` (the run is blocked until the user decides) and `stopped` fires on a cancelled generation. `finishGeneration` now branches per terminal state — `completed` / `error` / `cancelled` — instead of only chiming on success, and stays silent for any other state rather than implying an outcome.
- One oscillator per cue: multiple notes come from scheduled frequency steps with a re-articulated gain, so node count is unchanged. All prior safety properties hold — silent by default, no audio context before a trusted gesture, 160 ms throttle, a hard volume ceiling (`MAX_PEAK`), and a scheduled end for every voice. An unknown cue name degrades to the quietest click instead of throwing.
- Appearance settings gain an audition row (“Проверить звуки”) for the four agent-event cues, enabled only while sounds are on.
- Tests: `desktop/scripts/sound.test.mjs` grows from 3 to 7 cases. The fixture now captures waveform, the scheduled pitch sequence, note count and the scheduled end per cue, which lets the suite assert that all nine cues have distinct signatures, that the terminal states differ in the intended direction, that long cues still end on time within the volume ceiling, and that every started voice is stopped. Docs: new “UI-звуки” section in `docs/configuration.md`.

### Completed — W4.10 Hooks

- New `axiom.core.hooks` adds configurable lifecycle actions around the agent loop: `TaskStart`, `PreToolUse`, `PreEdit`, `PostEdit`, `PostToolUse`, `PreCommit`, `PostCommit`, `ContextCompact`, `TaskComplete`. A hook is a real external command, so the loop itself stays unchanged — hooks format, test or audit without patching the core.
- Definitions merge deterministically: builtin → `<AXIOM_HOME>/hooks/*.json` → `<workspace>/.axiom/hooks/*.json` → `config.hooks`. Builtins ship **disabled** (a hook runs real commands, so enabling one is always explicit); a config entry with only `id`+`enabled` toggles an existing definition without repeating its command. Malformed JSON, unknown events and commandless entries are rejected, and per-hook timeouts clamp to 0.5–600 s.
- Execution is sequential in declaration order, bounded by each hook's timeout, and runs argv **without a shell**, so hook arguments cannot append a second command. Every command is classified by the W4.9 command policy and refused before execution when it exceeds `hooks_max_risk` (default `MEDIUM`) — a project hook file cannot smuggle in `curl … | sh`.
- Hooks are fail-open: a non-zero exit, a timeout, or a missing executable is recorded as a warning in the persisted `Task.hook_results` (with exit code, duration, captured output, risk tier and the tool/path that triggered it) and the next hook plus the task continue. A hook never produces a `TaskError` and never changes a tool result.
- Integration points reuse the existing choke points: `ToolRegistry.execute` runs the tool-scoped events (post events only after a successful tool, and `subset()` keeps the same runner so subagent edits are hooked too), while `TaskRunner` runs `TaskStart`/`TaskComplete`/`ContextCompact` and publishes results as the new `task.hooks` event on the bus and trajectory. Hooks receive `AXIOM_HOOK_EVENT`, `AXIOM_TASK_ID`, `AXIOM_TOOL_NAME`, `AXIOM_FILE_PATH` and `AXIOM_WORKSPACE`; a workspace switch rebinds hooks so a previous project's commands never run against the new one.
- New configuration: `hooks_enabled` (master switch — `false` starts no process and leaves Task State untouched), `hooks`, `hooks_max_risk`.
- Tests: 27 deterministic tests in `tests/core/test_hooks_w410.py` — a real PostEdit formatter subprocess that actually rewrites the edited file, failing/timeout/missing-executable warnings with the loop continuing, refusal above the risk ceiling before execution, disabling restoring prior behaviour, sequential ordering, event/path/tool filtering, hook environment, registry pre/post ordering with an unchanged tool result, no post hooks for a failed tool, and hook results surviving task persistence. W4 wave summary now `12 done, 3 partial, 0 TODO`; docs updated in `docs/architecture.md` and `docs/configuration.md`.

### Completed — W4.6 Isolated subagents with compact reports

- `axiom.core.agents` now defines the full delivery set — Orchestrator, Analyst, Coder, Debugger, Reviewer, Researcher, Tester, Architect, Security, Explorer (strictly read-only reconnaissance), Frontend and Backend — and the compact report contract every specialist must return: `RESULT`, `FINDINGS`, `FILES`, `ERRORS`, `RECOMMENDATIONS`. `compact_report` normalises a runner result or raw answer into that shape, caps each section at 600 chars and the report at 2400 (RESULT gives way last), turns unsectioned prose into a single RESULT line, and never drops a real failure — it is appended to ERRORS.
- Scoped tools in `core/tools/meta.py`: Explorer gets read/search/git-inspection tools only (no writer, no `run_command`), Frontend and Backend own editing plus real checks (`run_tests`, `verify_changes`; Backend also `run_linter`), and no specialist receives the global tool surface.
- `ChatSession._subagent_runner` returns only `report` + `budget` telemetry besides its own fields: the full transcript (reasoning, answers, tool calls/results) stays in the worker's private trajectory, which is merged into the orchestration trace for replay. Every worker publishes the exact provider/model it is about to call before the first token.
- `SubagentBudget` enforces time/token/tool-call/retry ceilings after every streamed event (a zero ceiling disables that axis); exhaustion is explicit — the worker stops with the reason in `budget.exhausted`, marks `budget_exhausted`, records a `subagent.budget` trajectory event and returns the partial result it already produced rather than hanging or claiming success.
- `Orchestrator` builds the reviewer prompt and the final report from compact reports only (worker prose never reaches the reviewer; a budget-stopped worker is labelled `BUDGET: partial result — <reason> limit reached`), aggregates a `reports` list in the run result and normalises any runner that skipped the contract; rework passes its real iteration number as the worker retry count. Planning swaps the generalist `coder` for `frontend`/`backend` only when the request really names one surface (word-boundary match, so "build" never means "ui"); naming both keeps the generalist.
- `TaskRunner` aggregates the compact reports into the new persisted `Task.subagent_reports` field (one entry per step id — a repeat/repair replaces it — with `agent`, `report`, `budget` and `budget_exhausted`) and records a `task.report` trajectory event, so specialist evidence survives a restart without any transcript.
- Tests: 18 deterministic tests in `tests/core/test_agents_46.py` — registry/scoped tools, report parsing and bounding, budget reasons and telemetry, a real worker run with faked transport, budget-exhaustion partial result, retry accounting, reviewer isolation, surface-role selection, rework retry count, Task State aggregation and restart round trip. Verified with the full suite `602 passed, 1 skipped`, Ruff, and mypy with no new errors; docs updated in `docs/architecture.md`; W4 wave summary now `11 done, 3 partial, 1 TODO`.

### Completed — W4.5 AXIOM.md, Rules, and Skills

- New `axiom.core.rules` discovers workspace constraints from four scopes and merges them with a deterministic precedence (`global → project → directory → task`): global rules from `~/.axiom/AXIOM.md`, project rules from `<workspace>/AXIOM.md` or `<workspace>/.axiom/project.md`, directory rules from nested `AXIOM.md` files (heavy directories pruned, walk never leaves the workspace). When a higher-precedence scope redefines a Markdown section, the lower-precedence section is dropped; `RuleReport` records included/skipped sources.
- Global + project rules join the protected `project_rules` prompt layer (never dropped by the budget fight); directory rules attach only when the task touches a path under their directory — irrelevant directory rules never reach the model; rules explicitly `@`-mentioned by the user form the `task` scope and always win conflicts. `ChatSession.rules` is re-discovered on every workspace switch, so constraints never leak between projects.
- `axiom.core.skills` loads skills from disk: `~/.axiom/skills/*.md` (global) and `<workspace>/.axiom/skills/*.md` (project). A skill file is Markdown with an optional `---` header (`id`/`label`/`triggers`/`tools`); `parse_skill_file`/`load_skill_directory` are public. Disk skills are selected by their own declared triggers (or their id) — never injected wholesale — and a workspace switch drops stale project skills while global ones survive.
- At task start `ChatSession` records the merged rules and the relevance-selected skill ids in Task State (`Task.context_rules`, `Task.active_skills`, `Task.task_paths`) with a `task.rules` trajectory event; `TaskRunner` injects them into every step prompt, so a restarted/resumed task reuses exactly the same constraints instead of re-discovering them.
- Tests: 17 deterministic tests in `tests/core/test_rules_skills.py` — scope discovery, pruning, irrelevant-directory absence, path-mention attachment, user-requested shadowing, deterministic merge, workspace rebinding, skill parsing/loading/trigger selection, and the task-runtime contract (a matching skill changes the step prompt; unknown ids never crash a run). Verified with the full suite `584 passed, 1 skipped`, Ruff and mypy on the new/changed modules; docs updated in `docs/architecture.md`; W4 wave summary now `10 done, 4 partial, 1 TODO`.

### Completed — W4.9 Permissions 2.0: autonomy presets, risk tiers, approval scopes

- New `axiom.core.autonomy` composes the four PLAN/EDIT/AUTO/FULL presets from the existing `access_mode`/`permission_mode` axes; unknown autonomy values fail closed to plan axes. `PermissionManager.set_autonomy`, the TUI `/permissions` panel (MODES) and Desktop Settings apply the preset as one switch, and `Config.autonomy_mode` records the composed result.
- New `axiom.core.command_policy.classify_command_risk` classifies shell commands into SAFE/LOW/MEDIUM/HIGH/CRITICAL with a human-readable reason, mirroring `terminal.SAFE_PREFIXES`/`BLOCKED_PATTERNS`; an unknown command classifies as HIGH (fail closed).
- Approval scopes are once/task/project/always/deny with the risk tier inside every approval cache key. HIGH/CRITICAL calls are honored but never cached (`_ask_user(..., cacheable=False)`) — they always prompt per call; `git_add`/`git_commit` remain once-only and refuse persistent approval. `chat.py` binds the task/project scope for the running task (`bind_context`) and drops it on completion (`drop_task_scope`/`drop_project_scope`).
- `PermissionManager.describe_request` projects tool, arguments, cwd, risk tier and reason to the UI: the TUI permission dialog and the Desktop `ConfirmDialog` show the risk badge and offer once/task/project/always/deny, while HIGH/CRITICAL offer only once/deny.
- `sandbox.py` gains named presets `readonly`/`workspace`/`workspace-network`/`full` (unknown preset fails closed to `workspace`).
- Tests: new `tests/core/test_permissions_49.py` (29 tests — presets, risk tiers, scopes, non-inheritance), risk-aware/high-risk dialog coverage in `tests/frontends/test_permission_dialog.py`, autonomy MODES in `tests/frontends/test_tui_menu.py`; docs: `docs/roadmap.md` marks W4.9 DONE (W4 wave `9 done, 5 partial, 1 TODO`); verified with full pytest `567 passed, 1 skipped`, Ruff and `tsc --noEmit`.

### Added — Desktop task workflow: central execution, resume, delete, diff and context budgets (W4.12/W4.14 slice)

- The chat area switches from the transcript to a central task execution view (`TaskExecution`) when a task is focused: state label, plan and progress, the active step, the pending tool with its arguments, real commands, verification output, errors and the completion/review state all come from the same bridge task snapshot.
- Cancelled/failed/`waiting_for_user` tasks offer «Продолжить выполнение» through the existing `task_continue`; when a step was interrupted mid-run the resume button stays disabled until the user explicitly acknowledges that this step re-runs from the start (same task id, completed steps are never repeated).
- Inactive tasks can be deleted from the central view through the existing `task_delete` behind a confirmation dialog; active tasks show no delete action, deleting the opened task returns to the chat, and project files are never touched.
- The right panel resize is clamped to 360–680 px (`desktop/src/lib/panelSize.ts`), so all four side tabs and the task action buttons stay inside the panel even at the minimum width.
- The planner prompt now requires human-readable plan values in the user's language (JSON keys and tool names stay English); the hardcoded Russian fallback in `chat.py` was removed (new test `tests/core/test_task_planning_language.py`).
- `ui-polish-smoke.mjs` covers the panel minimum width and tabs, the central execution view, reload persistence, resume with the same id plus acknowledgement, the delete confirm/cancel/confirm flows, the changed-file diff with real +/- counts, context budget bars and review accept/reject (80 checks).
- The central view renders per-file diffs from `task.diffs` with real +/- counts, colored diff lines and a 1500-line cap; a completed task can be accepted or rejected inline through the existing `task_review` (same id, review state shown in the view).
- `TaskRunner` records the actual per-category context sizes and budgets after `build_task_context` into the new `Task.context_report` field; the central view shows budget bars per category with an over-budget highlight (new test `tests/core/test_tasks.py::test_task_runner_records_real_context_report`).
- Shared `CancelToken` (new `axiom.core.cancellation`, exported from `axiom`): one token per task run with parent/child linking; `TaskRunner.request_cancel()` sets it and the run stops at its next checkpoint (start, before each step, model request, verification attempt); `ChatSession.task_cancel` signals it before the hard asyncio cancel; `ToolRegistry.execute` refuses to start new work after cancellation and the per-request tool subset inherits the task token (new tests `tests/core/test_cancellation.py`, checkpoint tests in `tests/core/test_tasks.py`).
- Failed verification normalizes into a structured `TaskError` (`type`, `command`, `exit_code`, `stdout` taken from the failing check); task-scoped `model.request`/`model.response` and `verification.started`/`verification.completed`/`verification.failed` events now carry `task_id`/`step_id`/`attempt`/`agent` on the bus and in the durable trajectory (new tests `test_failed_verification_error_is_structured`, `test_verification_and_model_events_carry_task_id`).
- docs: `docs/roadmap.md` marks W4.12 DONE and W4.14 DONE (W4 wave `8 done, 6 partial, 1 TODO`).

### Completed — W4.7 Tool Router and Robust Tools

- `ToolRegistry.execute()` routes validation → permission → timeout → normalized result → audit. Static/classified `ASK` fail closed without approval, classified `NEVER` blocks even with `approved=True`, and denials are audited.
- Registry-level timeout cancels handlers; cancellable process tools reap their process trees. `max_output` enforced at the registry; `ToolResult.as_contract()` exposes the stable envelope.
- Terminal output streams line-by-line via `on_output` (metadata `streaming=True`).
- Agent `git_add` stages only explicit workspace files and requires fresh `allow_once` consent even in auto mode. Agent `git_commit` requires a SHA-256 of the real staged diff shown in the permission dialog and fresh per-call consent; a changed-after-review diff is rejected. `git_push` stays manual HIGH risk and is not an agent tool.

### Completed — W4.8 Verification and Self-Correction

- Verification results preserve subprocess `exit_code`; `VerificationLoop` refuses a false pass when a real command exits non-zero, even if an adapter incorrectly reports `ok=True`.
- Structured `{file, line, message}` diagnostics are extracted from pytest/Ruff/TypeScript/Rust output and prioritized by the task's changed files in the repair prompt. `Config.max_retries` (default 3) bounds the repair loop; exhaustion ends in `waiting_for_user` with an honest report. The ChatSession boundary refuses a reviewer when any check fails. A deterministic acceptance runs real pytest: failing exit 1 → focused repair → passing exit 0.

### Added — W4.7 tool safety slice

- `ToolRegistry.execute()` now enforces the effective static/classified permission fail-closed, including `NEVER` even when a caller passes `approved=True`; denied calls are audited.
- `ToolResult.as_contract()` exposes `{tool, ok, content, error, duration_ms, meta}` while preserving `data`; registry enforcement applies `max_output` and records truncation/risk/cancellation metadata.
- Added agent `git_add` for explicit individual workspace files. It requires fresh `allow_once` consent even in auto mode, rejects cached/"always" approval and empty/all/directory/escaping paths; `git_commit` and `git_push` remain user-only until reviewed-diff approval is enforceable.
- Verified with the Git/tool/security slice (`32 passed`) and Ruff.

### Completed — W4.3/W4.4 context budgeting and structured compaction

- `ContextEngine.build_task_context()` ranks explicit/changed/mentioned files and local Python imports, limits each context category, and reports the actual included sizes. `TaskRunner` now uses this same builder for every workspace task step and records `context.files` in trajectory; oversized files cannot overflow the file budget and long task/history input is clipped without changing stored history.
- `CompactionState` keeps goal, plan, decisions, changed files, errors, checks and important context. The Task Runtime compacts accumulated step evidence only when the model's context window is known, persists the snapshot in `Task`, records `context.compacted` in the trajectory, and restores it on resume without replaying completed steps. The previous `compress()` API remains unchanged.
- Deterministic tests cover ranking, budgets, schema, threshold, trajectory, three-step continuation and restart. Desktop build, Ruff and the full Python suite were run; see `docs/roadmap.md` for status.

### Changed — Windows desktop launch

- Tauri now uses the Windows GUI subsystem in debug and release builds; Python 3.11 and command helpers use hidden process creation, with the configured Python 3.11 path preferred by default;
- a per-session mutex prevents duplicate GUI instances, and a kill-on-close Job Object (with hidden `taskkill /T` fallback) terminates the core process tree on close or bridge restart;
- MCP subprocesses suppress console windows and are terminated as process trees.
- `axiom --gui` now checks for an MSVC Rust toolchain, installs official stable rustup quietly when missing, refreshes the current process PATH, and shows a GUI prompt if Visual C++ Build Tools or the Windows SDK are missing.

### Completed — W2.3 Orchestrator v2 and W2.9 Security Package

- W2.3: orchestration plans now carry dependency topology; persisted
  trajectories resume through `ChatSession.resume_orchestrated()` and skip
  workers that already have a recorded `agent.done`; `Trajectory.export_markdown()`
  and bridge commands `trajectory_export` / `orchestrate_resume` expose only
  recorded timeline and usage data;
- W2.9: `ToolRegistry` writes redacted JSONL audit records with argument hashes;
  workspace mutations create atomic per-file checkpoints and return checkpoint
  ids; `NetGuard` blocks non-public/credential-bearing URLs before fetch;
  fetched text is marked untrusted; `Config.local_only` blocks web search,
  page fetch and Ollama embeddings;
- tests added for SSRF, audit masking/round-trip, checkpoint restore, Local Only,
  Markdown export, dependency topology, trajectory resume and completed-worker
  skipping; targeted W2.3/W2.9/core harness slice: `72 passed`, Ruff clean.

### Added — W3.10 Composer persistence

- composer drafts persist per conversation (including an unsaved new-chat draft) across chat switches and restarts;
- submitted prompts are stored per conversation and can be recalled with ↑/↓ from the composer; deleting a chat also clears its saved draft and prompt history;
- updated the W3.10 roadmap to record the existing `@file` completion/insertion and this delivered slice. Desktop production build passes; tests were not run.

### Added — TUI Package (W2.8)

- `Ctrl+F` opens a current-transcript search bar. It searches only mounted
  `UserMessage`/`AssistantMessage` widgets, reports real match counts, and
  cycles through results with Enter / Shift+Enter without mixing in another
  conversation's history;
- `/orchestrate <task>` now opens a live `OrchestrationPanel`. It uses the
  real `ChatSession.trajectory` with a per-run baseline, shows actual worker /
  tool / review events, and `s` calls the existing session cancellation path;
- `/benchmark [repetitions]` runs the existing core `BenchmarkRunner` through
  isolated `ChatSession` instances, reports cold/warm timing and throughput,
  and displays model-unavailable/network failures honestly as failed runs;
- `/memory`, `/knowledge`, `/plugins` and accent theme support were already
  present and are now covered together by the completed W2.8 scope;
- added matching deep-dark TUI styles and regression coverage; verified with
  `42 passed` in the TUI/benchmark/permission slice and Ruff.

### Changed — Task Progress Observability (W4.12)

- Added a persisted `waiting_for_permission` task state. The bridge associates
  permission requests with the active task and returns it to its prior state
  after the user's decision; the Desktop status follows the task event and shows
  a localized state and active step detail.
- The task card now shows the pending tool and its safe argument summary,
  changed paths, structured execution errors, and concise verification outcome
  and failure reason. Copy reports only its destination; moves report both paths.
- Updated the W4.12 roadmap with this delivered slice. Tests were not run.

### Added — Frontend Decomposition and Virtualization (W2.7)

- **CSS split by domain without touching the visuals**: `desktop/src/styles.css`
  shrank from 3941 to 3242 lines; the boot-sequence and orchestration-board
  blocks are extracted verbatim into `desktop/src/styles/boot.css` and
  `desktop/src/styles/orchestration.css`, and the new virtualization rules live
  in `desktop/src/styles/virtualization.css` — all imported from `main.tsx` in
  the exact original cascade order, so the deep-dark theme renders identically;
- **`useAxiom.ts` decomposition**: pure, stateless helpers moved to
  `desktop/src/hooks/useAxiom.helpers.ts` (`liveAssistant`/`nextUserId`/
  `updateLive`, `toolLabel`/`toolTarget`/`toolStatusText`, `resolveModel`,
  `activeProviderLabel`, `errorText`, `orchestrationProgress`); the hook keeps
  only state and effects, and re-exports the helpers so existing imports keep
  working;
- **memoised message rows**: chat `UserMessage`/`AssistantMessage` are
  `React.memo` components fed by ref-stabilised callbacks (no stale closures)
  and live props (`liveState`/`statusText`/`elapsedMs`) gated to the streaming
  row only, so a long conversation no longer re-renders every settled message
  on each streamed flush;
- **native list virtualization**: chat messages and Explorer rows get
  `content-visibility: auto` with `contain-intrinsic-size`, skipping layout and
  paint for off-screen rows while preserving DOM structure, scroll position,
  and appearance — no virtual-list library, no behavior change;
- **~30 ms stream batching**: token deltas accumulate and flush on a fixed
  30 ms timer (cleared on finish/fail/unmount) instead of one render per
  animation frame, bounding the re-render rate during long generations;
- **bundle split**: Rollup `manualChunks` carve `vendor-react`,
  `vendor-markdown` and `vendor-highlight` out of the app chunk — the largest
  chunk drops from 822.72 kB (245.22 kB gzip, above the 500 kB warning) to
  342.86 kB (105.71 kB gzip) and the aggregate minified size shrinks slightly
  (822.72 → 818.87 kB); build emits no size warnings;
- verified with `tsc --noEmit`, the Vite build and the full E2E harness
  (47/47 checks, incl. real streaming generation through the bridge);
- documented in `docs/roadmap.md` (W2.7 TODO → DONE, W2 wave summary
  `6 done, 3 partial, 0 TODO`).

### Added — SQLite/FTS5 History (W2.6)

- `core/history.py`: `HistoryStore` now persists conversations to a single
  `history.db` (SQLite) per scope (global or per-project) instead of one JSON
  file per conversation. A `conversations` table holds the full indented JSON
  in a `data` column plus queryable `updated_at`/`pinned`/`folder`, and an
  `history_fts` FTS5 virtual table backs full-text search;
- the public API is unchanged (`save`/`list`/`show`/`load`/`delete`/`search`/
  `rename`/`set_meta`/`set_limit`/`use_workspace`/`directory`) so `ChatSession`
  and the bridge need no changes; `show` still returns the same
  `model_dump_json(indent=2)` string callers relied on;
- honest degradation: when the SQLite build lacks FTS5 the store logs a warning
  and search falls back to an in-Python scan (identical results, just slower),
  so search never silently breaks;
- idempotent migration: the first open of a directory imports any legacy
  `<id>.json` files into the DB, then moves the originals into a
  `migrated_json/` backup folder (kept readable, not deleted). A repeat open
  finds no `*.json` and does nothing; unreadable legacy files are skipped but
  still moved aside so they are not retried forever;
- `use_workspace()` reopens the store against the project's own `history.db`,
  keeping global and per-project histories separate as before;
- benchmark (2000 conversations × 6 messages each): full listing
  `14820 ms → 102 ms` (~145× faster), content search `209 ms → 0.8 ms`
  (~265× faster);
- tests: `tests/core/test_history_migration.py` (import + backup, repeat no-op,
  corrupt-file handling, reopen persistence, search over imported content) and
  an updated `tests/core/test_history_store.py` prune assertion; existing
  `test_history_meta.py`, `test_chat.py`, `test_public_api.py` and the bridge
  round-trip test pass unchanged;
- documented in `docs/architecture.md` (Персистентность + module map) and
  `docs/roadmap.md` (W2.6 PARTIAL → DONE, W2 wave summary `5 done, 3 partial,
  1 TODO`).

### Added — Prompt Layers Without Local-Model Overload (W2.5)

- new `core/prompt_builder.py`: `PromptLayers` dataclass, `build_system_prompt()`
  (fixed layer order `core` → `role` → `workspace` → `project` → `memory` →
  `knowledge` → `skills` → response style → current task, hard character
  budgets with must-survive floor for policy/workspace/project-rules/task)
  and `select_variant()` (deterministic `mini`/`full` from request complexity
  plus `thinking_mode`/`budget`, tracking reasoning depth — never an extra
  model call);
- `Agent.run` builds the default system prompt through the builder (workspace
  block, budgeted memory slice and skill blocks as inputs) and exposes
  `last_prompt_variant`/`last_prompt_chars`; a user's custom
  `system_prompt` still wins outright and the old default policy text is
  preserved as `FULL_POLICY`/`MINI_POLICY` inside the builder;
- `mini` (4000 chars, hard rules only) keeps small local models fast, `full`
  (12000 chars) carries the complete tool/decision policy; no unverified
  requirements or hidden chain-of-thought instructions are injected — the
  honesty rule and the no-guess rule are invariants of every assembly;
- exported `PromptLayers`, `build_system_prompt`, `select_variant`,
  `MINI_BUDGET_CHARS`, `FULL_BUDGET_CHARS` from the public API;
- tests: 8 cases in `tests/core/test_prompt_builder.py` (mini/full budgets,
  task+project survival under a 900-char budget, layer order, variant
  selection incl. deep/fast/economy, CoT-instruction absence, shared
  invariants, end-to-end memory injection through `Agent.run`);
- documented in `docs/architecture.md` (Слои промпта section) and
  `docs/roadmap.md` (W2.5 PARTIAL → DONE, W2 wave summary `4 done,
  4 partial, 1 TODO`).

### Added — Knowledge Base / RAG v1 (W2.2)

- new package `core/knowledge/`: `chunking.py` (deterministic paragraph chunker
  with overlap and real per-chunk line numbers; `.env`/keys and binary files
  are never indexed), `store.py` (`KnowledgeStore` per collection on
  SQLite/FTS5 under `~/.axiom/knowledge/<name>.db`), `manager.py` (atomic
  `~/.axiom/knowledge.json` registry + shared embedder) and `tools.py`;
- BM25 retrieval works fully offline; Ollama embeddings (`/api/embed`) are an
  optional re-ranking layer blended 60% cosine / 40% normalised BM25 — the
  store reports an honest `embeddings` status (`ok` /
  `unavailable: <reason>` / `disabled`) and search keeps working without it;
- indexing is incremental: a mtime+size fingerprint per file means a re-index
  reads only changed files, new files are added and deleted files drop out;
- three model-facing tools — `knowledge_search` (returns cited fragments as
  `[n] <collection>/<source>:<lines>` with the real chunk text),
  `knowledge_index`, `knowledge_status` (all `Permission.ALWAYS`);
  `performance.tool_scope` advertises them when the request mentions
  documents/notes/knowledge;
- `ChatSession` owns the manager and exposes UI projections:
  `knowledge_rows()`, `knowledge_add_collection()`, `knowledge_reindex()`,
  `knowledge_remove_collection()`, `knowledge_search_rows()`; the embeddings
  model is configured via `Config.knowledge_embed_model`;
- Desktop: bridge commands `knowledge_list`, `knowledge_add`,
  `knowledge_remove`, `knowledge_reindex`, `knowledge_search`,
  `knowledge_embed_model`; a Settings → Знания section to index a folder,
  re-index/remove collections and run a cited search, plus a `/knowledge`
  palette entry and the `KnowledgeRow`/`KnowledgeHit` types;
- TUI: `/knowledge` opens `KnowledgePanel` over the same core projections —
  `a` indexes the typed path, `r` re-indexes the selection, `d` removes it,
  `/` searches every collection and shows cited fragments;
- exported `KnowledgeManager`, `KnowledgeStore`, `KnowledgeTools` and
  `KnowledgeHit` from the public API;
- tests: 10 deterministic cases in `tests/core/test_knowledge.py` (chunk line
  numbers, secret/binary exclusion, cited BM25 search, incremental re-index
  and deletion drop-out, honest embeddings status with a fake embedder,
  vector re-rank, registry persistence, tool round-trip, session wiring,
  tool_scope advertising), 3 bridge cases (add → list → search → remove,
  missing path rejected, unknown reindex fails) and a TUI case in
  `tests/frontends/test_tui_menu.py`;
- documented in `docs/architecture.md` (База знаний section) and
  `docs/roadmap.md` (W2.2 TODO → DONE, W2 wave summary `3 done, 5 partial,
  1 TODO`).

### Added — GUI Permission Dialog (W2.4)

- `PermissionManager` now answers with a real three-way decision: added
  `PermissionOutcome` (`allow_once` / `allow_always` / `deny`) and
  `normalize_permission_outcome()`; legacy boolean callbacks still work
  (`True` = allow and remember). The answer is honest: only `allow_always`
  is cached (per tool, for the session), while `once` and `deny` ask again
  next time; an unknown answer fails closed;
- the tool call is really suspended until a human answers: the bridge emits
  `permission_request` (`tool`, `arguments`, `cwd`, and the real `risk` from
  registry metadata) and holds an `asyncio` future until the shell sends
  `permission_respond {id, decision}`; stale or unknown ids return
  `{"resolved": false}` instead of silently succeeding;
- Desktop: `ConfirmDialog.tsx` became the real permission dialog ("Один раз" /
  "Всегда для этого инструмента" / "Отклонить", Esc = отказ, аргументы в
  `<pre>`), driven by the `permission_request` event in `useAxiom.ts`; Stop
  refuses a pending request instead of leaving it hanging;
- TUI: `PermissionDialog` now returns `PermissionOutcome` (Enter = once,
  F2 = always, Esc = deny) and is really wired into `WorkspaceScreen.on_mount`
  — model-initiated ASK calls (e.g. `memory_write`) finally ask the user in
  both frontends instead of being denied by the no-callback fallback;
- tests: 5 new core cases (`tests/core/test_permissions.py`), 3 bridge cases
  (`permission_request` round-trip, fallback payload, real
  `permission_respond` routing) and `tests/frontends/test_permission_dialog.py`
  (the three dialog outcomes plus the real callback round-trip through a
  worker, which caught `push_screen_wait` belonging to `App`, not `Screen`);
- verified with `451 passed, 1 skipped`, Ruff, and `tsc --noEmit`;
- docs: `docs/architecture.md` gained the "Диалог разрешений (W2.4)" section;
  `docs/roadmap.md` restored the lost W1/W2 sections and marks W2.4 as DONE
  (W2 wave summary `2 done, 5 partial, 2 TODO`).

### Added — Curated Memory (W2.1)

- added `core/memory.py`: `MemoryItem` (id, scope, category, content, tags,
  timestamps) with `global`/`project`/`conversation` scopes and
  `normal`/`sensitive`/`banned` categories, plus `MemoryStore` — global memory in
  `~/.axiom/memory.json`, project memory in `<workspace>/.axiom/memory.json`,
  written atomically (`*.json.tmp` → replace) and never crashing on a corrupt
  file; a `banned` item is rejected in `add()` before anything reaches disk;
- added budgeted retrieval `MemoryStore.retrieve_relevant(query, budget)`:
  query terms are scored against content and tags, the result is hard-capped at
  `budget` items, and an unmatched query falls back to the newest items — the
  full store never enters the model context;
- added `MemoryTools` (`memory_write` = `ASK`, `memory_read` = `ALWAYS`,
  `memory_forget` = `ASK`, all `RISK_SAFE`): the model reaches memory only
  through these three tools, reads merge the project store (most specific) with
  the global one, and writes pick the target store from the requested scope;
- `ChatSession` now owns a global store plus a project store whenever a
  workspace root exists, registers the three tools, and exposes the user-facing
  management surface — `memory_rows()` (single projection shared by Desktop and
  TUI), `memory_write_for_user()`, `memory_edit()`, `memory_forget()`; a
  workspace switch rebuilds the project store and leaving a project drops it, so
  project facts never leak into another folder;
- `Agent` injects only a budgeted slice (`relevant(query, budget=5)`) as
  `[scope/category]` lines labelled "verify before relying on it"; a run without
  attached memory injects nothing;
- `performance.tool_scope` advertises the memory tools when the request asks the
  agent to remember something, so small local models still see them in a scoped
  tool list;
- Desktop: bridge commands `memory_list`, `memory_add`, `memory_edit`,
  `memory_delete`; a Settings → Память section to list, add (content + category
  + scope), edit in place and delete every persisted item, a `/memory` command
  palette entry that opens it, the `MemoryRow` projection type and its CSS;
- TUI: `/memory` opens `MemoryPanel` over the same core projection — `a` adds,
  `e` edits the selection, `d` deletes, `esc` closes, with a real
  global/project/sensitive counter in the subtitle;
- exported `MemoryItem`, `MemoryStore`, `MemoryTools`, `MemoryScope` and
  `MemoryCategory` from the public API;
- 17 deterministic tests in `tests/core/test_memory.py` (scoped paths, persist
  and reload, banned content never on disk, filters, budget enforcement, tool
  permissions, merged project + global reads, the memory block reaching the
  system prompt through a fake Ollama client, corrupt-file tolerance), 3 bridge
  cases in `tests/test_bridge.py` (add → list → edit → delete round-trip, empty
  content rejected, unknown id not removed) and a TUI case in
  `tests/frontends/test_tui_menu.py`;
- verified with `438 passed, 1 skipped`, Ruff, and `tsc --noEmit`;
- documented in `docs/architecture.md` (Curated Memory section + module map) and
  `docs/roadmap.md` (W2.1 TODO → DONE, W2 wave summary, W4.11 note). Task and
  session memory scopes remain in W4.11; a model-initiated `memory_write` in
  Desktop stays denied until the W2.4 permission dialog is wired, while TUI
  already prompts through the existing permission manager.

### Added — UI Extension Point Contract (W1.5)

- documented the versioned UI extension contract in `docs/plugins.md`
  (section 11) and `docs/architecture.md`: the `ui` manifest block
  (`api_version`, `scopes`, `extensions[]`), five extension points (`panel`,
  `command`, `setting`, `renderer`, `theme`), the `fs`/`net`/`ui`/`clipboard`
  scope model, host guarantees (typed request/response/events only, no host
  DOM, isolated iframe/Worker host in W3.1, requested scopes shown at install)
  and compatibility rules (exact `api_version` match, breaking changes bump
  `UI_EXTENSION_API_VERSION`, opaque `meta` pass-through);
- `PluginManifest` now parses a structured `ui` block into a validated
  `UIExtensionBlock` (a `UIExtension` per declared point) and rejects — before
  any code import — an incompatible `ui.api_version`, unknown extension points
  or scopes, unsafe extension ids, and a UI block without the `ui` capability;
  legacy `ui: string[]` declarations keep working unchanged;
- `UIExtension`/`UIExtensionBlock` exported from `axiom.core.plugins` and the
  public API; `manifest.row()` exposes `ui_block` for frontends;
- 12 deterministic tests in `tests/core/test_ui_extensions.py`: a full
  five-point example manifest validates, the incompatible-version case is
  rejected at both block and install level, unknown point/scope/id and missing
  capability are rejected, and round-trips preserve the block;
- updated `docs/roadmap.md`: W1.5 status changed from TODO to DONE, W1 wave
  summary is now `5 done`.

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
