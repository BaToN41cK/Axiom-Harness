"""W3.15: task automation scheduler."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from axiom.core.automation import (
    AutomationStore,
    Schedule,
    ScheduleInterval,
    create_automation_task,
    due_schedules,
    record_run,
    run_due,
)
from axiom.core.tasks import TaskState, TaskStore


def test_schedule_store_roundtrip(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automation.json")
    schedule = Schedule(prompt="Run nightly tests", interval=ScheduleInterval.DAILY)
    store.add(schedule)

    loaded = store.load()
    assert [s.id for s in loaded] == [schedule.id]
    assert loaded[0].prompt == "Run nightly tests"

    assert store.toggle(schedule.id, False) is True
    assert store.load()[0].enabled is False

    assert store.remove(schedule.id) is True
    assert store.load() == []


def test_due_schedules(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automation.json")
    store.add(Schedule(prompt="a", interval=ScheduleInterval.HOURLY, created_at=0.0))
    store.add(Schedule(prompt="b", interval=ScheduleInterval.DAILY, created_at=0.0))

    schedules = store.load()
    for s in schedules:
        if s.prompt == "b":
            s.next_run_at = 10**12  # far in the future

    due = due_schedules(schedules, now=7200.0)
    assert [s.prompt for s in due] == ["a"]


def test_disabled_schedule_not_due() -> None:
    schedule = Schedule(prompt="x", interval=ScheduleInterval.HOURLY, enabled=False)
    assert due_schedules([schedule], now=10**12) == []


def test_create_automation_task(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks")
    task = create_automation_task(Schedule(prompt="Run tests", max_risk="medium"), store)
    assert task.source == "automation"
    assert task.max_risk == "medium"
    assert task.state == TaskState.PENDING
    assert store.load(task.id) is not None


def test_record_run_marks_missed() -> None:
    schedule = Schedule(prompt="x", interval=ScheduleInterval.HOURLY)
    schedule.next_run_at = 1000.0
    record_run(schedule, now=1000.0 + 3 * 3600, task_id="t1")
    assert schedule.missed_runs == 3
    assert schedule.last_task_id == "t1"
    assert schedule.last_run_at == 1000.0 + 3 * 3600


def test_max_risk_cannot_be_high() -> None:
    with pytest.raises(ValidationError):
        Schedule(prompt="x", max_risk="high")


def test_run_due_creates_tasks(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks")
    schedules = [
        Schedule(prompt="a", interval=ScheduleInterval.HOURLY, created_at=0.0),
        Schedule(prompt="b", interval=ScheduleInterval.HOURLY, created_at=0.0),
    ]
    tasks = run_due(schedules, store, now=7200.0)
    assert len(tasks) == 2
    assert all(task.source == "automation" for task in tasks)
    assert store.load(tasks[0].id) is not None
    assert all(schedule.last_task_id is not None for schedule in schedules)
