"""Persistent task lifecycle, separate from conversation history (W4.1)."""
from __future__ import annotations

import asyncio
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
from axiom.core.config import axiom_home
from axiom.core.events import ToolCallEvent, ToolResultEvent
from axiom.core.planner import Planner, PlanStep, TaskPlan
from axiom.core.trajectory import Trajectory


class TaskState(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    EXECUTING = "executing"
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
    pending_tool: dict | None = None
    detail: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    revision: int = 0
    replans: int = 0
    planning: bool | None = None


class TaskEvent(BaseModel):
    type: Literal["task"] = "task"
    kind: Literal[
        "task.started", "task.resumed", "task.state", "task.planned", "task.replanned",
        "task.step", "task.tool", "task.completed", "task.failed", "task.cancelled",
    ]
    task_id: str
    timestamp: float
    task: Task


class TaskStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory if directory is not None else axiom_home() / "tasks"

    def _path(self, task_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", task_id):
            raise ValueError("Invalid task id")
        return self.directory / f"{task_id}.json"

    def save(self, task: Task) -> None:
        path = self._path(task.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(task.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)

    def load(self, task_id: str) -> Task | None:
        path = self._path(task_id)
        if not path.exists():
            return None
        task = Task.model_validate_json(path.read_text(encoding="utf-8"))
        if task.id != task_id:
            raise ValueError("Stored task id does not match its filename")
        return task

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
                 trajectory: Trajectory, max_replans: int = 1) -> None:
        self.store = store
        self.planner = planner
        self.execute = execute
        self.verify = verify
        self.tools = tools
        self.bus = bus
        self.trajectory = trajectory
        self.max_replans = max_replans

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

    def observe(self, task: Task, step: PlanStep, event) -> None:
        if isinstance(event, ToolCallEvent):
            # Do not persist file bodies or shell environment in checkpoints.
            arguments = {key: str(value)[:2000] for key, value in event.arguments.items()
                         if key in {"path", "source", "destination", "command"}}
            task.pending_tool = {"name": event.name, "arguments": arguments}
        elif isinstance(event, ToolResultEvent):
            args = (task.pending_tool or {}).get("arguments", {})
            if event.ok and event.name in {
                "write_file", "edit_file", "apply_patch", "delete_file", "move_file", "copy_file",
            }:
                for key in ("path", "source", "destination"):
                    path = args.get(key)
                    if path and path not in task.changed_files:
                        task.changed_files.append(path)
            if not event.ok:
                task.errors.append(TaskError(type="tool", message=event.error or "Tool failed",
                                             tool=event.name, command=args.get("command"),
                                             stdout=event.content[:4000], step_id=step.id))
            task.pending_tool = None
        else:
            return
        self.publish(task, "task.tool")

    async def run(self, task: Task, *, resume: bool = False, acknowledge: bool = False) -> Task:
        try:
            self.publish(task, "task.resumed" if resume else "task.started")
            interrupted = task.plan and any(step.state == "running" for step in task.plan.steps)
            if (task.pending_tool or interrupted) and not acknowledge:
                self.transition(task, TaskState.WAITING_FOR_USER,
                                "Interrupted work may have changed the workspace. "
                                "Inspect it before acknowledging resume.")
                return task
            if acknowledge:
                task.pending_tool = None
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
                self.transition(task, TaskState.EXECUTING, step.goal)
                step.state = "running"
                self.publish(task, "task.step")
                completed = [{"id": s.id, "result": s.result} for s in task.plan.steps if s.state == "completed"]
                prompt = (f"Task: {task.goal}\nCurrent step: {step.goal}\nAcceptance: {step.done_when}\n"
                          f"Completed work (do not repeat): {json.dumps(completed, ensure_ascii=False)}\n"
                          f"Known changed files: {json.dumps(task.changed_files)}\n"
                          "Inspect actual workspace state before editing; a previous attempt may have applied changes.")
                if task.errors:
                    prompt += "\nCurrent errors:\n" + "\n".join(e.message[:1000] for e in task.errors[-5:])
                result = await self.execute(step=step, prompt=prompt,
                                            on_event=partial(self.observe, task, step))
                step.result = str(result.get("content") or "")[:8000]
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
                self.publish(task, "task.step")
            self.transition(task, TaskState.VERIFYING)
            report = await self.verify()
            task.tests.append(report)
            # A no-checks/no-git result is NOT a passing test.
            if report.get("ok") is True and report.get("executed") is True:
                self.transition(task, TaskState.COMPLETED, str(report.get("summary") or "Verification passed"))
            else:
                self.transition(task, TaskState.WAITING_FOR_USER,
                                str(report.get("error") or report.get("summary") or "Verification unavailable"))
        except asyncio.CancelledError:
            self.transition(task, TaskState.CANCELLED, "Stopped; completed steps are preserved")
        except Exception as exc:
            task.errors.append(TaskError(type=type(exc).__name__, message=str(exc)))
            self.transition(task, TaskState.FAILED, str(exc))
        return task
