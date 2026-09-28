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


def _runner(tmp_path, *, planner: Planner, execute, verify, context_max_tokens: int = 8192,
            workspace_root=None):
    return TaskRunner(
        store=TaskStore(tmp_path / "tasks"),
        planner=planner,
        execute=execute,
        verify=verify,
        tools=["read_file", "write_file"],
        bus=EventBus(),
        trajectory=Trajectory(),
        context_max_tokens=context_max_tokens,
        workspace_root=workspace_root,
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


async def test_verification_repair_limit_and_diagnostics_are_honest(tmp_path):
    attempts = []
    prompts = []

    async def generate(_prompt):
        return _plan("fix").model_dump_json()

    async def execute(*, step, prompt, on_event):
        prompts.append(prompt)
        return {"content": "edited"}

    async def verify():
        attempts.append(True)
        return {"ok": False, "executed": True, "summary": "pytest failed",
                "checks": {"steps": [{"diagnostics": [
                    {"file": "tests/test_calc.py", "line": 17, "message": "AssertionError: wrong value"},
                ]}]}}

    runner = _runner(tmp_path, planner=Planner(generate), execute=execute, verify=verify)
    runner.max_verification_repairs = 2
    task = await runner.run(Task(goal="Fix the failing test"))
    assert task.state is TaskState.WAITING_FOR_USER
    assert len(attempts) == 3  # initial verification plus exactly two repairs
    assert len(prompts) == 3   # initial task step plus exactly two repair steps
    assert "tests/test_calc.py:17: AssertionError" in prompts[1]
    assert "repair limit (2) exhausted" in task.detail
    assert len(task.tests) == 3
    assert not any(event.kind == "task.completed" for event in runner.trajectory.events)


@pytest.mark.asyncio
async def test_diagnostics_prioritize_changed_files(tmp_path):
    prompts = []

    async def execute(*, step, prompt, on_event):
        prompts.append(prompt)
        if step.id.startswith("verification-repair-"):
            return {"content": "edited"}
        return {"content": "initial"}

    async def verify():
        return {"ok": False, "executed": True, "summary": "failed",
                "checks": {"steps": [{"diagnostics": [
                    {"file": "other.py", "line": 5, "message": "unrelated"},
                    {"file": "src/calc.py", "line": 9, "message": "wrong value"},
                ]}]}}

    runner = _runner(tmp_path, planner=Planner(lambda p: _plan("fix").model_dump_json()),
                     execute=execute, verify=verify)
    runner.max_verification_repairs = 1
    task = Task(goal="Fix calc", changed_files=["src/calc.py"],
                plan=TaskPlan(steps=[PlanStep(id="inspect", goal="look", tools=[], done_when="x")],
                              definition_of_done=["x"]))
    await runner.run(task)
    assert task.state is TaskState.WAITING_FOR_USER
    repair_prompt = next(p for p in prompts if "Prioritized diagnostics" in p)
    section = repair_prompt.split("Prioritized diagnostics:", 1)[1]
    assert section.index("src/calc.py") < section.index("other.py")


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


@pytest.mark.asyncio
async def test_concurrent_resume_rejected_and_restart_skips_completed(tmp_path) -> None:
    """W4.1 DoD: concurrent resume is rejected; restarted runs don't repeat completed steps."""
    gate = asyncio.Event()
    executed: list[str] = []

    async def execute(*, step, prompt, on_event):
        executed.append(step.id)
        await gate.wait()  # blocks until released; keeps the task busy
        return {"content": f"{step.id} done"}

    async def verify():
        return {"ok": True, "executed": True, "summary": "verify PASSED"}

    async def generate(_prompt: str) -> str:
        return json.dumps({
            "steps": [{"id": "work", "goal": "Do work", "tools": ["read_file"],
                       "done_when": "Done"}],
            "definition_of_done": ["Work completed"],
        })

    runner = _runner(tmp_path, planner=Planner(generate), execute=execute, verify=verify)
    task = Task(goal="Fix and implement the long-running repair work")
    first = asyncio.create_task(runner.run(task))
    await asyncio.sleep(0)  # let the run reach execute() and mark busy
    assert executed == ["work"]

    # A second runner against the same persisted task must not run concurrently.
    fresh = _runner(tmp_path, planner=Planner(generate), execute=execute, verify=verify)
    reloaded = runner.store.load(task.id)
    assert reloaded is not None and reloaded.plan.steps[0].state == "running"
    # Concurrent resume is a busy session at the ChatSession layer; here the
    # persisted running step + no acknowledgement correctly pauses for the user.
    paused = await fresh.run(reloaded, resume=True)
    assert paused.state is TaskState.WAITING_FOR_USER
    assert "Inspect" in paused.detail

    # Release the original run; it completes without repeating the step.
    gate.set()
    done = await asyncio.wait_for(first, timeout=5)
    assert done.state is TaskState.COMPLETED
    assert executed == ["work"]  # executed exactly once — never repeated


@pytest.mark.asyncio
async def test_task_runner_uses_ranked_context_files_in_step_prompt(tmp_path) -> None:
    (tmp_path / "calc.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("UNRELATED = True\n", encoding="utf-8")
    prompts = []

    async def execute(*, step, prompt, on_event):
        prompts.append(prompt)
        return {"content": "evidence"}

    async def verify():
        return {"ok": True, "executed": True, "summary": "passed"}

    runner = _runner(tmp_path, planner=Planner(lambda prompt: _plan("x").model_dump_json()),
                     execute=execute, verify=verify, workspace_root=tmp_path)
    task = await runner.run(Task(goal="Fix calc", changed_files=["calc.py"], plan=TaskPlan(
        steps=[PlanStep(id="inspect", goal="Inspect calc.py", tools=["read_file"], done_when="seen")],
        definition_of_done=["passed"],
    )))
    assert task.state is TaskState.COMPLETED
    assert "### calc.py" in prompts[0]
    assert "UNRELATED" not in prompts[0]
    assert any(event.kind == "context.files" for event in runner.trajectory.events)


@pytest.mark.asyncio
async def test_task_runner_records_real_context_report(tmp_path) -> None:
    """W4.12: the Task carries the actual per-category sizes and budgets."""
    (tmp_path / "calc.py").write_text("VALUE = 1\n", encoding="utf-8")

    async def execute(*, step, prompt, on_event):
        return {"content": "evidence"}

    async def verify():
        return {"ok": True, "executed": True, "summary": "passed"}

    runner = _runner(tmp_path, planner=Planner(lambda prompt: _plan("x").model_dump_json()),
                     execute=execute, verify=verify, workspace_root=tmp_path)
    task = await runner.run(Task(goal="Fix calc", changed_files=["calc.py"], plan=TaskPlan(
        steps=[PlanStep(id="inspect", goal="Inspect calc.py", tools=["read_file"], done_when="seen")],
        definition_of_done=["passed"],
    )))
    assert task.state is TaskState.COMPLETED
    report = task.context_report
    assert report is not None
    assert report["categories"]["files"] > 0
    assert report["budgets"]["files"] > 0
    assert set(report["categories"]) == set(report["budgets"])
    assert report["over_budget"] == []
    # The report is ordinary Task State: it survives a store round trip (restart).
    loaded = runner.store.load(task.id)
    assert loaded is not None and loaded.context_report == report


async def test_task_runner_compacts_structured_state_and_continues(tmp_path) -> None:
    seen: list[tuple[str, str]] = []

    async def generate(_prompt: str) -> str:
        return json.dumps({
            "steps": [
                {"id": "inspect", "goal": "Inspect settings", "tools": ["read_file"], "done_when": "Known"},
                {"id": "repair", "goal": "Repair settings", "tools": ["write_file"], "done_when": "Fixed"},
                {"id": "review", "goal": "Review settings", "tools": ["read_file"], "done_when": "Reviewed"},
            ],
            "definition_of_done": ["Settings repaired"],
        })

    async def execute(*, step, prompt, on_event):
        seen.append((step.id, prompt))
        return {"content": "Found state " + ("x" * 200) if step.id == "inspect" else "Done"}

    async def verify():
        return {"ok": True, "executed": True, "summary": "1 passed"}

    runner = _runner(tmp_path, planner=Planner(generate), execute=execute,
                     verify=verify, context_max_tokens=100)
    task = Task(goal="Fix settings", changed_files=["SettingsModal.tsx"],
                errors=[{"type": "test", "message": "old failure"}],
                tests=[{"ok": False, "summary": "pytest failed"}])
    completed = await runner.run(task)
    assert completed.state is TaskState.COMPLETED
    assert [item[0] for item in seen] == ["inspect", "repair", "review"]
    assert "[Structured context compaction]" in seen[1][1]
    assert seen[2][1].count("[Structured context compaction]") == 1
    events = [event for event in runner.trajectory.events if event.kind == "context.compacted"]
    assert events
    assert events[0].data["state"]["goal"] == "Fix settings"
    assert events[0].data["state"]["changed_files"] == ["SettingsModal.tsx"]
    assert events[0].data["state"]["errors"] == ["old failure"]
    assert events[0].data["state"]["tests"] == ["pytest failed"]
    persisted = runner.store.load(task.id)
    assert persisted.state is TaskState.COMPLETED
    assert persisted.context_snapshot.goal == "Fix settings"


@pytest.mark.asyncio
async def test_task_resume_restores_compacted_snapshot(tmp_path) -> None:
    from axiom.core.context_engine import CompactionState

    first = _plan("finished")
    first.steps[0].state = "completed"
    first.steps[0].result = "Inspected"
    next_step = PlanStep(id="continue", goal="Continue repair", tools=["read_file"], done_when="Done")
    plan = TaskPlan(steps=[*first.steps, next_step], definition_of_done=["Checks pass"])
    task = Task(goal="Fix settings", plan=plan, state=TaskState.WAITING_FOR_USER,
                context_snapshot=CompactionState(goal="Fix settings", plan=["finished: completed"],
                                                 errors=["old failure"], tests=["pytest failed"],
                                                 changed_files=["SettingsModal.tsx"]))

    async def generate(_prompt):
        raise AssertionError("Planner must not be called on resume")

    seen = []

    async def execute(*, step, prompt, on_event):
        seen.append((step.id, prompt))
        return {"content": "repaired"}

    async def verify():
        return {"ok": True, "executed": True, "summary": "1 passed"}

    runner = _runner(tmp_path, planner=Planner(generate), execute=execute, verify=verify)
    runner.store.save(task)
    restarted = _runner(tmp_path, planner=Planner(generate), execute=execute, verify=verify)
    result = await restarted.run(restarted.store.load(task.id), resume=True)
    assert result.state is TaskState.COMPLETED
    assert [step_id for step_id, _ in seen] == ["continue"]
    assert '"old failure"' in seen[0][1]
    assert '"SettingsModal.tsx"' in seen[0][1]
    assert restarted.store.load(task.id).context_snapshot.goal == "Fix settings"


@pytest.mark.asyncio
async def test_real_pytest_failure_is_repaired_and_retested(tmp_path):
    from axiom.core.tools.verify_tools import VerificationTools

    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8",
    )
    verifier = VerificationTools(root=tmp_path)
    reports = []

    async def generate(_prompt):
        return _plan("repair").model_dump_json()

    async def execute(*, step, prompt, on_event):
        if step.id.startswith("verification-repair-"):
            (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        return {"content": "focused repair"}

    async def verify():
        result = await verifier._run_tests()
        data = dict(result.data or {})
        report = {"ok": result.ok, "executed": data.get("status") in {"passed", "failed"},
                  "summary": result.content, "error": result.error, "checks": data}
        reports.append(report)
        return report

    runner = _runner(tmp_path, planner=Planner(generate), execute=execute, verify=verify)
    task = await runner.run(Task(goal="Fix calc.py", plan=TaskPlan(
        steps=[PlanStep(id="inspect", goal="Inspect calc", tools=["read_file"], done_when="Cause recorded")],
        definition_of_done=["pytest passes"],
    )))
    assert task.state is TaskState.COMPLETED
    assert len(reports) == 2
    assert reports[0]["ok"] is False and reports[0]["checks"]["exit_code"] == 1
    assert reports[1]["ok"] is True and reports[1]["checks"]["exit_code"] == 0
    assert (tmp_path / "calc.py").read_text(encoding="utf-8").endswith("return a + b\n")
