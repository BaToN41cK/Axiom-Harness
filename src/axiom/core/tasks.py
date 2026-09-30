"""Persistent task lifecycle, separate from conversation history (W4.1)."""
from __future__ import annotations

import asyncio
import difflib
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from axiom.core.bus import EventBus
from axiom.core.cancellation import CancelToken
from axiom.core.config import axiom_home
from axiom.core.context_engine import CompactionState, ContextEngine
from axiom.core.events import ToolCallEvent, ToolResultEvent
from axiom.core.planner import Planner, PlanStep, TaskPlan
from axiom.core.review import durable_write, review_lock, sync_directory
from axiom.core.trajectory import Trajectory


class TaskState(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_FOR_PERMISSION = "waiting_for_permission"
    VERIFYING = "verifying"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskError(BaseModel):
    type: str
    message: str
    tool: str | None = None
    command: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    step_id: str | None = None


class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    goal: str = Field(min_length=1, max_length=16000)
    state: TaskState = TaskState.PENDING
    scope: str | None = None
    plan: TaskPlan | None = None
    plan_history: list[TaskPlan] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    errors: list[TaskError] = Field(default_factory=list)
    tests: list[dict] = Field(default_factory=list)
    context_snapshot: CompactionState | None = None
    #: Actual per-category context sizes/budgets from the last task step (W4.12).
    context_report: dict | None = None
    pending_tool: dict | None = None
    active_processes: list[dict] = Field(default_factory=list)
    commands: list[dict] = Field(default_factory=list)
    file_baselines: dict[str, str | None] = Field(default_factory=dict)
    unknown_baselines: list[str] = Field(default_factory=list)
    #: Snapshot captured after the final agent change. Reject uses it to avoid
    #: overwriting edits made by the user after the task completed.
    review_baselines: dict[str, str | None] = Field(default_factory=dict)
    #: Durable reject journal state. A non-empty journal on disk is authoritative;
    #: this field is a compact UI/restart hint, never the transaction itself.
    review_recovery: str | None = None
    review_recovery_detail: str | None = None
    review_recovery_paths: list[str] = Field(default_factory=list)
    diffs: dict[str, str] = Field(default_factory=dict)
    review_status: Literal["pending", "accepted", "rejected"] = "pending"
    detail: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    revision: int = 0
    replans: int = 0
    planning: bool | None = None
    #: W4.5 — rules/skills attached to this task (persisted for resume).
    #: Rules relevant to the task paths (global+project+directory+task scopes,
    #: already precedence-merged); survives restart so resumed execution sees
    #: exactly the same constraints.
    context_rules: str = Field(default="", max_length=8000)
    #: Skill ids selected by relevance for this task's goal (max 3).
    active_skills: list[str] = Field(default_factory=list, max_length=8)
    #: Workspace paths the task explicitly touches (@-mentions etc.).
    task_paths: list[str] = Field(default_factory=list, max_length=32)
    #: W4.10 — real lifecycle hook outcomes for this task (newest last, capped).
    #: A failing hook appears here as a warning; it never fails the task.
    hook_results: list[dict] = Field(default_factory=list, max_length=200)
    #: W4.6 — compact specialist reports (agent, status, five-section report,
    #: budget telemetry, exhaustion reason). Full worker transcripts never land
    #: here; they stay in their own trajectories.
    subagent_reports: list[dict] = Field(default_factory=list, max_length=64)


class TaskEvent(BaseModel):
    type: Literal["task"] = "task"
    kind: Literal[
        "task.started", "task.resumed", "task.state", "task.planned", "task.replanned",
        "task.step", "task.tool", "task.completed", "task.failed", "task.cancelled",
        "task.permission", "task.process", "task.review", "task.hooks",
    ]
    task_id: str
    timestamp: float
    task: Task


class TaskStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory if directory is not None else axiom_home() / "tasks"

    def transaction_path(self, task_id: str) -> Path:
        self._path(task_id)
        return self.directory / f"{task_id}.review.json"

    def save_transaction(self, task_id: str, transaction: dict) -> None:
        path = self.transaction_path(task_id)
        durable_write(path, json.dumps(transaction, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def load_transaction(self, task_id: str) -> dict | None:
        path = self.transaction_path(task_id)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"state": "recovery_required", "error": "Review journal is unreadable"}
        return value if isinstance(value, dict) else {"state": "recovery_required", "error": "Invalid review journal"}

    def remove_transaction(self, task_id: str) -> None:
        self.transaction_path(task_id).unlink(missing_ok=True)
        sync_directory(self.directory)

    def _path(self, task_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", task_id):
            raise ValueError("Invalid task id")
        return self.directory / f"{task_id}.json"

    def save(self, task: Task) -> None:
        with review_lock(self.directory):
            if any(self.directory.glob("*.review.json")):
                raise ValueError("Task has an unfinished review; recover it before changing task state")
            self.save_review(task)

    def save_review(self, task: Task) -> None:
        """Commit while the caller holds review_lock; journal survives failed saves."""
        durable_write(self._path(task.id), task.model_dump_json(indent=2).encode("utf-8"))

    def load(self, task_id: str) -> Task | None:
        path = self._path(task_id)
        if not path.exists():
            return None
        task = Task.model_validate_json(path.read_text(encoding="utf-8"))
        if task.id != task_id:
            raise ValueError("Stored task id does not match its filename")
        journal = self.load_transaction(task_id)
        task.review_recovery = str(journal.get("state", "recovery_required")) if journal is not None else None
        task.review_recovery_detail = (str(journal.get("error", "")) or None) if journal is not None else None
        paths = journal.get("conflicts", []) if journal is not None else []
        task.review_recovery_paths = [str(path) for path in paths] if isinstance(paths, list) else []
        return task

    def delete(self, task_id: str) -> bool:
        with review_lock(self.directory):
            if self.transaction_path(task_id).exists():
                raise ValueError("Cannot delete a task with an unfinished review journal")
            path = self._path(task_id)
            if path.exists():
                path.unlink()
                sync_directory(self.directory)
                return True
            return False

    def list(self) -> list[Task]:
        tasks = []
        for path in self.directory.glob("*.json"):
            try:
                task = self.load(path.stem)
            except (ValueError, OSError):
                continue
            if task is not None:
                tasks.append(task)
        return sorted(tasks, key=lambda task: task.updated_at, reverse=True)


class TaskRunner:
    """Sequential checkpoints around existing agent/verification adapters.

    A persisted in-flight tool is deliberately NOT replayed automatically.
    Completing a task requires a real verification result, not model prose.
    """

    def __init__(self, *, store: TaskStore, planner: Planner, execute: Callable[..., Awaitable[dict]],
                 verify: Callable[[], Awaitable[dict]], tools: list[str], bus: EventBus,
                 trajectory: Trajectory, max_replans: int = 1, max_verification_repairs: int = 3,
                 workspace_root: Path | None = None, context_engine: ContextEngine | None = None,
                 context_max_tokens: int | None = None, cancel_token: CancelToken | None = None,
                 skill_registry: object | None = None, hooks: object | None = None,
                 context_summarizer: Callable[[str], Awaitable[str | None]] | None = None) -> None:
        self.store = store
        self.planner = planner
        self.execute = execute
        self.verify = verify
        self.tools = tools
        self.bus = bus
        self.trajectory = trajectory
        self.max_replans = max_replans
        self.max_verification_repairs = max(0, max_verification_repairs)
        self.workspace_root = workspace_root.resolve() if workspace_root is not None else None
        self.context_engine = context_engine or ContextEngine(max_tokens=context_max_tokens)
        self.context_max_tokens = context_max_tokens
        self.cancel_token = cancel_token or CancelToken()
        self.context_messages: list[dict] = []
        self._permission_previous_state: TaskState | None = None
        self._permission_tool_name: str | None = None
        #: W4.5 — registry used to render persisted ``task.active_skills``
        #: blocks into step prompts (``SkillRegistry``; duck-typed for tests).
        self._skill_registry = skill_registry
        if skill_registry is not None and not callable(getattr(skill_registry, "get", None)):
            raise TypeError("skill_registry must expose get(skill_id)")
        #: W4.10 — lifecycle hook runner. ``None`` keeps the previous behaviour
        #: exactly; hooks are fail-open and never decide a task's outcome.
        self.hooks = hooks
        #: W4.11 — optional model call used when a long task context is
        #: compacted (the ``summarize`` role). ``None`` (the default) keeps
        #: compaction exactly as before: structured state only, no extra call.
        self.context_summarizer = context_summarizer

    def _snapshot_paths(self, task: Task, name: str, arguments: dict) -> None:
        if self.workspace_root is None:
            return
        keys = {
            "write_file": ("path",), "edit_file": ("path",), "apply_patch": ("path",),
            "delete_file": ("path",), "create_directory": ("path",),
            "move_file": ("source", "destination"), "copy_file": ("destination",),
        }.get(name, ())
        for key in keys:
            raw = arguments.get(key)
            if not raw:
                continue
            try:
                path = Path(str(raw))
                path = (path if path.is_absolute() else self.workspace_root / path).resolve()
                relative = path.relative_to(self.workspace_root).as_posix()
            except (OSError, ValueError):
                continue
            if relative in task.file_baselines:
                continue
            try:
                if path.is_file():
                    with path.open(encoding="utf-8", newline="") as stream:
                        task.file_baselines[relative] = stream.read()
                    captured = task.file_baselines[relative]
                    if isinstance(captured, str) and "\x00" in captured:
                        task.unknown_baselines.append(relative)
                elif path.exists():
                    task.unknown_baselines.append(relative)
                else:
                    task.file_baselines[relative] = None
            except (OSError, UnicodeError):
                task.file_baselines[relative] = None
                task.unknown_baselines.append(relative)

    def _record_file_diffs(self, task: Task, name: str, arguments: dict) -> None:
        if self.workspace_root is None:
            return
        keys = {
            "write_file": ("path",), "edit_file": ("path",), "apply_patch": ("path",),
            "delete_file": ("path",), "create_directory": ("path",),
            "move_file": ("source", "destination"), "copy_file": ("destination",),
        }.get(name, ())
        for key in keys:
            raw = arguments.get(key)
            if not raw:
                continue
            try:
                path = Path(str(raw))
                path = (path if path.is_absolute() else self.workspace_root / path).resolve()
                relative = path.relative_to(self.workspace_root).as_posix()
            except (OSError, ValueError):
                continue
            before = task.file_baselines.get(relative)
            try:
                if path.is_file():
                    with path.open(encoding="utf-8", newline="") as stream:
                        after = stream.read()
                elif path.exists():
                    raise ValueError("Not a regular text file")
                else:
                    after = None
                if after is not None and "\x00" in after:
                    raise ValueError("Binary content")
            except (OSError, UnicodeError, ValueError):
                task.review_baselines.pop(relative, None)
                task.diffs[relative] = "(File created, deleted or changed as a non-text file.)"
                continue
            task.review_baselines[relative] = after
            if before == after:
                task.diffs.pop(relative, None)
                continue
            old_lines = (before or "").splitlines(keepends=True)
            new_lines = (after or "").splitlines(keepends=True)
            diff = "".join(difflib.unified_diff(old_lines, new_lines,
                                                fromfile=f"a/{relative}" if before is not None else "/dev/null",
                                                tofile=f"b/{relative}" if after is not None else "/dev/null"))
            task.diffs[relative] = diff[:100_000] + ("\n… diff truncated" if len(diff) > 100_000 else "")

    def process_event(self, task: Task, event: dict) -> None:
        """Persist subprocess lifecycle metadata as it changes."""
        pid = int(event.get("pid") or 0)
        if not pid:
            return
        if event.get("state") == "running":
            task.active_processes = [p for p in task.active_processes if int(p.get("pid") or 0) != pid]
            task.active_processes.append(dict(event))
        else:
            for process in task.active_processes:
                if int(process.get("pid") or 0) == pid:
                    process.update(event)
        self.publish(task, "task.process")

    def permission_requested(self, task: Task, tool: str, arguments: dict) -> None:
        """Persist the task's real wait-for-approval state before forwarding UI events."""
        if task.state == TaskState.WAITING_FOR_PERMISSION:
            return
        self._permission_previous_state = task.state
        self._permission_tool_name = tool
        safe_arguments = {
            key: str(value)[:2000]
            for key, value in arguments.items()
            if key in {"path", "source", "destination", "command"}
        }
        pending = dict(task.pending_tool or {})
        pending.update({"name": tool, "arguments": safe_arguments, "awaiting_permission": True})
        task.pending_tool = pending
        task.state = TaskState.WAITING_FOR_PERMISSION
        self.publish(task, "task.permission")

    def permission_resolved(self, task: Task) -> None:
        """Return to the state that was active before the permission dialog."""
        if task.state != TaskState.WAITING_FOR_PERMISSION:
            return
        pending = dict(task.pending_tool or {})
        pending["awaiting_permission"] = False
        task.pending_tool = pending
        if self._permission_tool_name == "verify_changes":
            task.pending_tool = None
        task.state = self._permission_previous_state or TaskState.EXECUTING
        self._permission_previous_state = None
        self._permission_tool_name = None
        self.publish(task, "task.state")

    def publish(self, task: Task, kind: str = "task.state") -> None:
        task.updated_at = time.time()
        task.revision += 1
        self.store.save(task)  # persist before announcing a transition
        event = TaskEvent(kind=kind, task_id=task.id, timestamp=task.updated_at, task=task.model_copy(deep=True))
        data = event.model_dump(mode="json")
        self.trajectory.append(kind, task.detail or task.state.value, data=data)
        self.bus.emit(kind, data)
        self.bus.emit("task.event", data)

    def transition(self, task: Task, state: TaskState, detail: str = "") -> None:
        task.state = state
        task.detail = detail
        kind = f"task.{state.value}" if state in {
            TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED,
        } else "task.state"
        self.publish(task, kind)

    async def _run_hooks(self, event: str, task: Task, *, step_id: str = "") -> None:
        """Run lifecycle hooks and record their real results in Task State (W4.10).

        Hooks are fail-open: a failing or refused hook is stored as a warning and
        published, and the task keeps running.
        """
        runner = self.hooks
        if runner is None:
            return
        run = getattr(runner, "run_event", None)
        if not callable(run):
            return
        try:
            results = await run(event, task_id=task.id, step_id=step_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        # These results are recorded here, so drop them from the runner's
        # pending buffer: the per-step drain must not duplicate them.
        drain = getattr(runner, "drain", None)
        if callable(drain):
            try:
                drain()
            except Exception:
                pass
        recorded = [r.to_json() if hasattr(r, "to_json") else dict(r) for r in results or []]
        if not recorded:
            return
        task.hook_results = (task.hook_results + recorded)[-200:]
        self.publish(task, "task.hooks")

    def _collect_tool_hook_results(self, task: Task) -> None:
        """Move tool-hook results recorded by the registry into Task State."""
        runner = self.hooks
        drain = getattr(runner, "drain", None) if runner is not None else None
        if not callable(drain):
            return
        try:
            results = drain()
        except Exception:
            return
        recorded = [r.to_json() if hasattr(r, "to_json") else dict(r) for r in results or []]
        if recorded:
            task.hook_results = (task.hook_results + recorded)[-200:]

    def request_cancel(self) -> None:
        """Signal cooperative cancellation; the run stops at its next checkpoint (W4.14)."""
        self.cancel_token.cancel()

    async def _run_model_step(self, task: Task, step: PlanStep, prompt: str) -> dict:
        """Execute one model-driven step and publish task-scoped model.* events (W4.14)."""
        self.cancel_token.raise_if_cancelled()
        request = {"task_id": task.id, "step_id": step.id, "agent": "coder"}
        self.bus.emit("model.request", request)
        self.trajectory.append("model.request", step.goal, actor="coder", data=request)
        started = time.perf_counter()
        try:
            result = await self.execute(step=step, prompt=prompt,
                                        on_event=partial(self.observe, task, step))
        except BaseException as exc:
            self._publish_model_response(task, step, started, ok=False,
                                         error=f"{type(exc).__name__}: {exc}")
            raise
        self._publish_model_response(
            task, step, started, ok=not bool(result.get("error") or result.get("tools_failed")),
        )
        return result

    def _publish_model_response(self, task: Task, step: PlanStep, started: float, *,
                                ok: bool, error: str = "") -> None:
        payload: dict = {"task_id": task.id, "step_id": step.id, "agent": "coder",
                         "duration_ms": int((time.perf_counter() - started) * 1000), "ok": ok}
        if error:
            payload["error"] = error
        self.bus.emit("model.response", payload)
        self.trajectory.append("model.response", step.goal, actor="coder", data=payload)

    def _publish_verification(self, task: Task, kind: str, attempt: int, *,
                              summary: str = "", error: str = "") -> None:
        payload: dict = {"task_id": task.id, "attempt": attempt, "agent": "tester"}
        if summary:
            payload["summary"] = summary
        if error:
            payload["error"] = error
        self.bus.emit(kind, payload)
        self.trajectory.append(kind, summary or error, actor="tester", data=payload)

    @staticmethod
    def _verification_error(report: dict, message: str) -> TaskError:
        """Normalize a failed verification report into a structured TaskError (W4.14)."""
        checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
        steps = [item for item in checks.get("steps") or [] if isinstance(item, dict)]
        failed = next(
            (item for item in steps
             if item.get("ok") is not True or item.get("exit_code") not in (None, 0)),
            None,
        )
        exit_code = checks.get("exit_code") if isinstance(checks.get("exit_code"), int) else None
        if exit_code is None and isinstance(failed, dict) and isinstance(failed.get("exit_code"), int):
            exit_code = failed["exit_code"]
        command = failed.get("command") if isinstance(failed, dict) else None
        output = str((failed or {}).get("output") or checks.get("output") or "")
        return TaskError(
            type="verification",
            message=message,
            command=str(command) if command else None,
            exit_code=exit_code,
            stdout=output[:4000],
        )

    def observe(self, task: Task, step: PlanStep, event) -> None:
        if isinstance(event, ToolCallEvent):
            # Do not persist file bodies or shell environment in checkpoints.
            arguments = {key: str(value)[:2000] for key, value in event.arguments.items()
                         if key in {"path", "source", "destination", "command"}}
            task.pending_tool = {"name": event.name, "arguments": arguments}
            self._snapshot_paths(task, event.name, event.arguments)
            if event.name in {"run_command", "run_tests", "run_linter", "build_project", "verify_changes"}:
                task.commands.append({"tool": event.name, "command": arguments.get("command"),
                                     "state": "running", "started_at": time.time(), "step_id": step.id})
        elif isinstance(event, ToolResultEvent):
            args = (task.pending_tool or {}).get("arguments", {})
            if event.ok:
                changed_args = {
                    "write_file": ("path",), "edit_file": ("path",),
                    "apply_patch": ("path",), "delete_file": ("path",),
                    "create_directory": ("path",), "move_file": ("source", "destination"),
                    "copy_file": ("destination",),
                }.get(event.name, ())
                for key in changed_args:
                    path = args.get(key)
                    if path and path not in task.changed_files:
                        task.changed_files.append(path)
                self._record_file_diffs(task, event.name, args)
            for command in reversed(task.commands):
                if command.get("state") == "running" and command.get("tool") == event.name:
                    command.update({"state": "passed" if event.ok else "failed",
                                    "duration_ms": event.duration_ms,
                                    "output": event.content[:12000], "error": event.error})
                    break
            if not event.ok:
                task.errors.append(TaskError(type="tool", message=event.error or "Tool failed",
                                             tool=event.name, command=args.get("command"),
                                             stdout=event.content[:4000], step_id=step.id))
            task.pending_tool = None
        else:
            return
        self.publish(task, "task.tool")

    def _record_subagent_report(self, task: Task, step: PlanStep, result: dict) -> None:
        """Aggregate one step's compact worker report into Task State (W4.6).

        Only the five-section report and the explicit budget telemetry are kept;
        the worker transcript itself stays in its own trajectory. One entry per
        step id — a repeated step (repair/rework) replaces its previous report
        instead of duplicating it — and the newest 64 entries are retained.
        """
        report = result.get("report")
        if not isinstance(report, dict):
            return
        entry: dict = {"step_id": step.id,
                       "agent": str(result.get("agent") or "coder"),
                       "report": report}
        if result.get("budget") is not None:
            entry["budget"] = result["budget"]
        if result.get("budget_exhausted"):
            entry["budget_exhausted"] = result["budget_exhausted"]
        kept = [r for r in task.subagent_reports if r.get("step_id") != step.id]
        kept.append(entry)
        task.subagent_reports = kept[-64:]
        self.trajectory.append("task.report", f"{entry['agent']} report for {step.id}",
                               actor=entry["agent"],
                               data={"task_id": task.id, "step_id": step.id,
                                     "report": report, "budget": result.get("budget"),
                                     "budget_exhausted": result.get("budget_exhausted")})

    async def _compact_task_context(self, task: Task) -> None:
        """Compact accumulated step context while retaining durable task facts."""
        if not self.context_messages or self.context_max_tokens is None:
            return
        state = CompactionState(
            goal=task.goal,
            plan=[f"{step.id}: {step.goal} ({step.state})" for step in (task.plan.steps if task.plan else [])],
            decisions=[task.detail] if task.detail else [],
            changed_files=list(task.changed_files),
            errors=[error.message for error in task.errors[-16:]],
            tests=[str(report.get("summary") or report.get("error") or report)[:1000]
                   for report in task.tests[-16:]],
            important_context=[f"replans={task.replans}", f"state={task.state.value}"],
        )
        result = await self.context_engine.compact_structured(
            self.context_messages, state, preserve_count=1,
            max_tokens=self.context_max_tokens, trajectory=self.trajectory,
            summarizer=self.context_summarizer,
        )
        if result.compacted:
            self.context_messages = result.messages
            task.context_snapshot = result.state
            self.publish(task, "task.state")
            await self._run_hooks("ContextCompact", task)

    async def run(self, task: Task, *, resume: bool = False, acknowledge: bool = False) -> Task:
        try:
            self.publish(task, "task.resumed" if resume else "task.started")
            self.cancel_token.raise_if_cancelled()
            interrupted = task.plan and any(step.state == "running" for step in task.plan.steps)
            if (task.pending_tool or interrupted) and not acknowledge:
                self.transition(task, TaskState.WAITING_FOR_USER,
                                "Interrupted work may have changed the workspace. "
                                "Inspect it before acknowledging resume.")
                return task
            if acknowledge:
                task.pending_tool = None
            if resume and task.context_snapshot is not None:
                self.context_messages = [{
                    "role": "system",
                    "content": "[Structured context compaction]\n" + task.context_snapshot.model_dump_json(indent=2),
                }]
            await self._run_hooks("TaskStart", task)
            self.transition(task, TaskState.ANALYZING)
            if task.plan is None:
                self.transition(task, TaskState.PLANNING)
                if self.planner.needed(task.goal, task.planning):
                    task.plan = await self.planner.create(task.goal, self.tools)
                else:
                    task.plan = TaskPlan(steps=[PlanStep(id="answer", goal=task.goal, tools=self.tools,
                                                       done_when="Answer the user's request using available evidence")],
                                         definition_of_done=["Request addressed and verification reported"])
                task.plan_history.append(task.plan.model_copy(deep=True))
                self.publish(task, "task.planned")
            while True:
                step = next((s for s in task.plan.steps if s.state != "completed"), None)
                if step is None:
                    break
                self.cancel_token.raise_if_cancelled()
                self.transition(task, TaskState.EXECUTING, step.goal)
                step.state = "running"
                self.publish(task, "task.step")
                completed = [{"id": s.id, "result": s.result} for s in task.plan.steps if s.state == "completed"]
                prompt = (f"Task: {task.goal}\nCurrent step: {step.goal}\nAcceptance: {step.done_when}\n"
                          f"Completed work (do not repeat): {json.dumps(completed, ensure_ascii=False)}\n"
                          f"Known changed files: {json.dumps(task.changed_files)}\n"
                          "Inspect actual workspace state before editing; a previous attempt may have applied changes.")
                # W4.5: the rules/skills attached at task start (persisted in
                # Task State) shape every step; resumed runs reuse exactly the
                # same constraints instead of re-discovering them.
                if task.context_rules:
                    prompt += "\nProject rules (follow them):\n" + task.context_rules[:4000]
                if task.active_skills and self._skill_registry is not None:
                    skill_blocks: list[str] = []
                    for skill_id in task.active_skills[:3]:
                        skill = self._skill_registry.get(skill_id)  # type: ignore[attr-defined]
                        if skill is not None:
                            block = skill.prompt_block()
                            if block:
                                skill_blocks.append(block[:1500])
                    if skill_blocks:
                        prompt += "\nRelevant skills (apply them):\n" + "\n\n".join(skill_blocks)
                if task.errors:
                    prompt += "\nCurrent errors:\n" + "\n".join(e.message[:1000] for e in task.errors[-5:])
                if self.workspace_root is not None:
                    # Use the same ranked, workspace-guarded evidence builder as
                    # the standalone context API. Keep space for the tool loop.
                    file_budget = min(4000, max(0, (self.context_max_tokens or 4096) * 2 - len(prompt)))
                    evidence = self.context_engine.build_task_context(
                        f"{task.goal}\n{step.goal}", [], workspace_root=self.workspace_root,
                        changed_files=task.changed_files, budgets={"task": 0, "files": file_budget},
                    )
                    # Real category sizes vs budgets for the Task UI (W4.12).
                    task.context_report = {"categories": evidence.report["categories"],
                                           "budgets": evidence.report["budgets"],
                                           "over_budget": evidence.report["over_budget"]}
                    if evidence.files and evidence.messages:
                        prompt += "\n" + str(evidence.messages[0]["content"])
                        self.trajectory.append("context.files", "Relevant task files selected",
                                               data={"task_id": task.id, "files": evidence.files,
                                                     "categories": evidence.report["categories"]})
                await self._compact_task_context(task)
                if self.context_messages and self.context_messages[0].get("role") == "system":
                    prompt += "\n" + str(self.context_messages[0]["content"])
                self.context_messages.append({"role": "user", "content": prompt})
                result = await self._run_model_step(task, step, prompt)
                step.result = str(result.get("content") or "")[:8000]
                self._record_subagent_report(task, step, result)
                self.context_messages.append({"role": "assistant", "content": step.result})
                error = result.get("error") or ("Tool calls failed" if result.get("tools_failed") else None)
                if not step.result and not error:
                    error = "Empty model response"
                if error:
                    step.state = "failed"
                    task.errors.append(TaskError(type="step", message=str(error), step_id=step.id))
                    self.publish(task, "task.step")
                    if task.replans >= self.max_replans:
                        self.transition(task, TaskState.WAITING_FOR_USER, str(error))
                        return task
                    task.replans += 1
                    self.transition(task, TaskState.PLANNING, str(error))
                    task.plan = await self.planner.create(task.goal, self.tools, previous=task.plan, error=str(error))
                    task.plan_history.append(task.plan.model_copy(deep=True))
                    self.publish(task, "task.replanned")
                    continue
                step.state = "completed"
                # Tool hooks ran inside the registry during this step; surface
                # their real results in Task State with the step that caused them.
                self._collect_tool_hook_results(task)
                self.publish(task, "task.step")
            self.transition(task, TaskState.VERIFYING)
            for attempt in range(self.max_verification_repairs + 1):
                self.cancel_token.raise_if_cancelled()
                detail = "Проверка изменений" if attempt == 0 else f"Повторная проверка после исправления {attempt}"
                self.transition(task, TaskState.VERIFYING, detail)
                self._publish_verification(task, "verification.started", attempt, summary=detail)
                report = await self.verify()
                task.tests.append(report)
                # A no-checks/no-git result is NOT a passing test.
                if report.get("ok") is True and report.get("executed") is True:
                    summary = str(report.get("summary") or "Verification passed")
                    self.transition(task, TaskState.COMPLETED, summary)
                    self._publish_verification(task, "verification.completed", attempt, summary=summary)
                    await self._run_hooks("TaskComplete", task)
                    break
                message = str(report.get("error") or report.get("summary") or "Verification unavailable")
                self._publish_verification(task, "verification.failed", attempt, error=message)
                if not report.get("executed") or attempt >= self.max_verification_repairs:
                    task.errors.append(self._verification_error(report, message))
                    reason = (f"Verification repair limit ({self.max_verification_repairs}) exhausted: {message}"
                              if attempt >= self.max_verification_repairs and report.get("executed") else message)
                    self.transition(task, TaskState.WAITING_FOR_USER, reason)
                    break
                repair = PlanStep(id=f"verification-repair-{attempt + 1}",
                                  goal="Исправить ошибки проверки и сохранить вывод проверки",
                                  tools=self.tools, done_when="Ошибки проверки устранены")
                repair.state = "running"
                self.transition(task, TaskState.EXECUTING, repair.goal)
                diagnostics = report.get("checks", {}).get("diagnostics", [])
                if not diagnostics:
                    for step_report in report.get("checks", {}).get("steps", []):
                        diagnostics.extend(step_report.get("diagnostics", []))
                # Prioritize diagnostics in the files the task actually changed.
                if diagnostics and task.changed_files:
                    changed = frozenset(p.replace("\\", "/") for p in task.changed_files)

                    def _rank(item: dict, changed: frozenset[str] = changed) -> int:
                        file_name = str(item.get("file") or "").replace("\\", "/")
                        return 0 if any(file_name.endswith(c) or c.endswith(file_name)
                                        for c in changed) else 1

                    diagnostics = sorted(diagnostics, key=_rank)
                diagnostic_text = "\n".join(
                    f"- {item.get('file')}:{item.get('line')}: {item.get('message')}"
                    for item in diagnostics[:20]
                )
                prompt = (f"Task: {task.goal}\nVerification failed. Repair the cause using this exact report:\n"
                          f"{json.dumps(report, ensure_ascii=False)[:16000]}\n"
                          "Prioritized diagnostics:\n"
                          f"{diagnostic_text or '(no structured file/line diagnostic was reported)'}\n"
                          "Do not claim success. Make a focused fix; the verifier will run again.")
                result = await self._run_model_step(task, repair, prompt)
                repair.result = str(result.get("content") or "")[:8000]
                self._record_subagent_report(task, repair, result)
                if result.get("error") or result.get("tools_failed"):
                    task.errors.append(TaskError(type="verification_repair",
                        message=str(result.get("error") or "Repair tool failed"), step_id=repair.id))
                    self.transition(
                        task,
                        TaskState.WAITING_FOR_USER,
                        "Исправление не удалось; требуется решение пользователя",
                    )
                    break
        except asyncio.CancelledError:
            self.transition(task, TaskState.CANCELLED, "Stopped; completed steps are preserved")
        except Exception as exc:
            task.errors.append(TaskError(type=type(exc).__name__, message=str(exc)))
            self.transition(task, TaskState.FAILED, str(exc))
        return task
