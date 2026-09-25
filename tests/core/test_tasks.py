"""Task Runtime and Planner contracts (W4.1/W4.2)."""
from __future__ import annotations

import asyncio
import json

import pytest

from axiom.core.bus import EventBus
from axiom.core.events import ToolCallEvent, ToolResultEvent
from axiom.core.planner import Planner, PlanStep, TaskPlan
from axiom.core.tasks import Task, TaskRunner, TaskState, TaskStore
from axiom.core.trajectory import Trajectory


def _plan(step_id: str = "inspect") -> TaskPlan:
    return TaskPlan(
        steps=[PlanStep(id=step_id, goal="Inspect the workspace", tools=["read_file"], done_when="Evidence recorded")],
        definition_of_done=["A real verification result is recorded"],
    )


def _runner(tmp_path, *, planner: Planner, execute, verify):
    return TaskRunner(
        store=TaskStore(tmp_path / "tasks"),
        planner=planner,
        execute=execute,
        verify=verify,
        tools=["read_file", "write_file"],
        bus=EventBus(),
        trajectory=Trajectory(),
    )


def test_planner_threshold_and_strict_json_validation() -> None:
    assert Planner.needed("What is the current branch?") is False
    assert Planner.needed("Please fix the failing project switching test") is True

    plan = Planner.parse(
        json.dumps({
            "steps": [{"id": "read", "goal": "Read the test", "tools": ["read_file"],
                       "done_when": "Failure is understood"}],
            "definition_of_done": ["Cause is documented"],
        }),
        ["read_file"],
    )
    assert plan.steps[0].state == "pending"
    with pytest.raises(ValueError):
        Planner.parse(
            json.dumps({
                "steps": [{"id": "run", "goal": "Run", "tools": ["run_command"],
                           "done_when": "It runs"}],
                "definition_of_done": ["Done"],
            }),
            ["read_file"],
        )


@pytest.mark.asyncio
async def test_planner_replan_preserves_completed_steps() -> None:
    calls: list[str] = []

    async def generate(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps({
            "steps": [{"id": "repair", "goal": "Repair the failure", "tools": ["write_file"],
                       "done_when": "The failing check passes"}],
            "definition_of_done": ["The check passes"],
        })

    previous = TaskPlan(
        steps=[
            PlanStep(id="inspect", goal="Inspect", tools=["read_file"], done_when="Cause known", state="completed",
                     result="Found the cause"),
            PlanStep(id="old-repair", goal="Old repair", tools=["write_file"], done_when="Fixed"),
        ],
        definition_of_done=["The check passes"],
    )
    plan = await Planner(generate).create("Fix it", ["read_file", "write_file"], previous=previous, error="test failed")
    assert [step.id for step in plan.steps] == ["inspect", "repair"]
    assert plan.steps[0].state == "completed"
    assert "test failed" in calls[0]


def test_task_store_round_trip_is_atomic_and_scoped(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks")
    task = Task(id="task-1", goal="Persist me", scope=str(tmp_path))
    store.save(task)
    loaded = store.load(task.id)
    assert loaded is not None and loaded.goal == task.goal
    assert not list((tmp_path / "tasks").glob("*.tmp"))
    assert [item.id for item in store.list()] == ["task-1"]
    with pytest.raises(ValueError):
        store.load("../escape")


def test_task_store_failed_replace_keeps_previous_checkpoint(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    store = TaskStore(tmp_path)
    task = Task(goal="Original")
    store.save(task)

    def fail_replace(self, target):
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "replace", fail_replace)
    task.goal = "New"
    with pytest.raises(OSError, match="disk unavailable"):
        store.save(task)
    assert store.load(task.id).goal == "Original"
    assert not list(tmp_path.glob("*.tmp"))
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert len(store.list()) == 1


@pytest.mark.parametrize("change", [
    {"state": "completed"}, {"result": "already done"}, {"goal": " "},
    {"tools": ["unknown_tool"]}, {"id": "../outside"},
])
def test_planner_rejects_invalid_or_fabricated_steps(change):
    raw = _plan().model_dump()
    raw["steps"][0].update(change)
    with pytest.raises(ValueError):
        Planner.parse(json.dumps(raw), ["read_file"])


async def test_runner_replans_once_and_preserves_completed_work(tmp_path):
    executed = []
    initial = _plan("inspect")
    initial.steps.append(PlanStep(id="fix", goal="Fix", tools=[], done_when="Fixed"))

    async def generate(prompt):
        assert "broken test" in prompt
        return _plan("repair").model_dump_json()

    async def execute(*, step, **kwargs):
        executed.append(step.id)
        return {"content": "evidence", "error": "broken test" if step.id == "fix" else None}

    async def verify():
        return {"ok": False, "executed": False, "summary": "No configured checks"}

    task = Task(goal="Fix", plan=initial, plan_history=[initial.model_copy(deep=True)])
    runner = _runner(tmp_path, planner=Planner(generate), execute=execute, verify=verify)
    await runner.run(task)
    assert executed == ["inspect", "fix", "repair"]
    assert task.replans == 1
    assert len(task.plan_history) == 2
    assert task.state is TaskState.WAITING_FOR_USER
    assert "task.replanned" in [event.kind for event in runner.trajectory.events]


async def test_runner_retry_budget_stops_and_empty_checks_never_pass(tmp_path):
    async def generate(prompt):
        return _plan().model_dump_json()

    async def execute(**kwargs):
        return {"error": "still broken"}

    async def verify():
        raise AssertionError("Failed steps must not reach verification")

    runner = _runner(tmp_path, planner=Planner(generate), execute=execute, verify=verify)
    task = await runner.run(Task(goal="Fix it"))
    assert task.state is TaskState.WAITING_FOR_USER
    assert task.replans == 1
    assert len(task.errors) == 2



@pytest.mark.asyncio
async def test_task_runner_lifecycle_persists_real_events(tmp_path) -> None:
    seen: list[str] = []

    async def generate(_prompt: str) -> str:
        return json.dumps({
            "steps": [{"id": "inspect", "goal": "Inspect", "tools": ["read_file"],
                       "done_when": "Evidence recorded"}],
            "definition_of_done": ["A real verification result is recorded"],
        })

    async def execute(*, step, prompt, on_event):
        assert step.id == "inspect"
        assert "Current step" in prompt
        on_event(ToolCallEvent(name="read_file", arguments={"path": "README.md"}))
        on_event(ToolResultEvent(name="read_file", ok=True, content="read", duration_ms=2))
        return {"content": "Evidence recorded"}

    async def verify():
        return {"ok": True, "executed": True, "summary": "verify PASSED"}

    bus = EventBus()
    bus.subscribe("task.event", lambda payload: seen.append(payload["kind"]))
    runner = TaskRunner(
        store=TaskStore(tmp_path / "tasks"), planner=Planner(generate), execute=execute, verify=verify,
        tools=["read_file"], bus=bus, trajectory=Trajectory(),
    )
    task = await runner.run(Task(goal="Fix the project"))
    assert task.state is TaskState.COMPLETED
    assert task.changed_files == []
    assert task.tests[0]["executed"] is True
    assert "task.planned" in seen
    assert "task.completed" in seen
    assert runner.store.load(task.id).state is TaskState.COMPLETED


@pytest.mark.asyncio
async def test_task_runner_cancel_and_resume_requires_acknowledgement(tmp_path) -> None:
    started = asyncio.Event()

    async def execute(*, step, prompt, on_event):
        on_event(ToolCallEvent(name="write_file", arguments={"path": "a.txt"}))
        started.set()
        await asyncio.Event().wait()
        return {"content": "unreachable"}

    async def verify():
        return {"ok": True, "executed": True, "summary": "verify PASSED"}

    async def generate(_prompt: str) -> str:
        return json.dumps({
            "steps": [{"id": "write", "goal": "Write", "tools": ["write_file"],
                       "done_when": "File exists"}],
            "definition_of_done": ["File exists"],
        })

    runner = _runner(tmp_path, planner=Planner(generate), execute=execute, verify=verify)
    task = Task(goal="Implement the change")
    run = asyncio.create_task(runner.run(task))
    await asyncio.wait_for(started.wait(), timeout=2)
    run.cancel()
    cancelled = await asyncio.wait_for(run, timeout=2)
    assert cancelled.state is TaskState.CANCELLED
    assert cancelled.pending_tool == {"name": "write_file", "arguments": {"path": "a.txt"}}

    resumed = await runner.run(cancelled, resume=True)
    assert resumed.state is TaskState.WAITING_FOR_USER
    assert "Inspect" in resumed.detail
