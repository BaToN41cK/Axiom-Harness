"""W3.3 Multitasking: concurrent background tasks and isolated cancellation.

The core now tracks detached tasks in a per-task registry (``_task_runs``)
instead of a single foreground slot, so several tasks can run at once, each
with its own ``CancelToken``. ``task_cancel`` stops exactly one task and never
touches the chat generation or another running task.
"""
from __future__ import annotations

import asyncio

import pytest

from axiom.core.planner import PlanStep, TaskPlan
from axiom.core.tasks import TaskState
from tests.core.test_orchestrator_runtime_a import _session


def _plan(step_id: str) -> TaskPlan:
    return TaskPlan(
        steps=[PlanStep(id=step_id, goal=f"Step {step_id}", tools=[], done_when="released")],
        definition_of_done=["released"],
    )


def _stub_verify(session) -> None:
    async def _ok(task):
        return {"ok": True, "executed": True, "summary": "verified", "checks": {"passed": 1}}

    session._verify_task = _ok  # type: ignore[method-assign]


async def test_running_task_ids_is_empty_when_idle(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch, tmp_path)
    assert session.running_task_ids() == []
    assert not session.busy


async def test_two_background_tasks_run_concurrently(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch, tmp_path)
    started = {sid: asyncio.Event() for sid in ("a", "b")}
    release = {sid: asyncio.Event() for sid in ("a", "b")}

    async def blocked(*, step, prompt, on_event):
        started[step.id].set()
        await release[step.id].wait()
        return {"content": "done"}

    monkeypatch.setattr(session, "_execute_task_step", blocked)
    _stub_verify(session)

    task_a = await session.task_start("Task A", plan=_plan("a"), detached=True)
    task_b = await session.task_start("Task B", plan=_plan("b"), detached=True)

    # Both start without a "generation already running" error and overlap.
    await asyncio.wait_for(started["a"].wait(), 5)
    await asyncio.wait_for(started["b"].wait(), 5)
    assert set(session.running_task_ids()) == {task_a.id, task_b.id}
    assert session.busy

    # Release A alone; B must keep running.
    release["a"].set()
    for _ in range(200):
        if task_a.id not in session.running_task_ids():
            break
        await asyncio.sleep(0.01)
    assert task_a.id not in session.running_task_ids()
    assert session.task_state(task_a.id).state is TaskState.COMPLETED
    assert task_b.id in session.running_task_ids()
    assert session.busy

    release["b"].set()
    for _ in range(200):
        if task_b.id not in session.running_task_ids():
            break
        await asyncio.sleep(0.01)
    assert session.task_state(task_b.id).state is TaskState.COMPLETED
    assert not session.busy
    assert session.running_task_ids() == []


async def test_cancel_one_background_task_leaves_the_other_running(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch, tmp_path)
    started = {sid: asyncio.Event() for sid in ("a", "b")}
    block_forever = {sid: asyncio.Event() for sid in ("a", "b")}

    async def blocked(*, step, prompt, on_event):
        started[step.id].set()
        await block_forever[step.id].wait()
        return {"content": "done"}

    monkeypatch.setattr(session, "_execute_task_step", blocked)
    _stub_verify(session)

    task_a = await session.task_start("Task A", plan=_plan("a"), detached=True)
    task_b = await session.task_start("Task B", plan=_plan("b"), detached=True)
    await asyncio.wait_for(started["a"].wait(), 5)
    await asyncio.wait_for(started["b"].wait(), 5)

    # Cancelling A stops exactly A; B stays in flight.
    assert session.task_cancel(task_a.id) is True
    for _ in range(200):
        if session.task_state(task_a.id).state is TaskState.CANCELLED:
            break
        await asyncio.sleep(0.01)
    assert session.task_state(task_a.id).state is TaskState.CANCELLED
    assert task_b.id in session.running_task_ids()
    assert session.busy

    # The unknown-id path stays honest.
    assert session.task_cancel("does-not-exist") is False

    # Reap B too, so its blocked worker is not left pending when the test ends.
    assert session.task_cancel(task_b.id) is True
    for _ in range(200):
        if not session.running_task_ids():
            break
        await asyncio.sleep(0.01)
    assert session.running_task_ids() == []


async def test_foreground_task_waits_for_the_slot_while_background_runs(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch, tmp_path)
    started = asyncio.Event()
    block_forever = asyncio.Event()

    async def blocked(*, step, prompt, on_event):
        started.set()
        await block_forever.wait()
        return {"content": "done"}

    monkeypatch.setattr(session, "_execute_task_step", blocked)
    _stub_verify(session)

    background = await session.task_start("Background", plan=_plan("a"), detached=True)
    await asyncio.wait_for(started.wait(), 5)
    assert session.busy

    # A foreground run still needs the single in-line slot to be free.
    with pytest.raises(ValueError, match="already running"):
        await session.task_start("Foreground", plan=_plan("f"))

    # A second background task is allowed even while the first runs.
    second = await session.task_start("Second background", plan=_plan("b"), detached=True)
    assert second.id != background.id
    assert session.task_cancel(background.id) is True
    assert session.task_cancel(second.id) is True
    # Let both cancelled workers finish so their asyncio tasks are fully reaped.
    for _ in range(200):
        if not session.running_task_ids():
            break
        await asyncio.sleep(0.01)
    assert session.running_task_ids() == []
