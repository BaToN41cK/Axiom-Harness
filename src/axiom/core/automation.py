"""Task automation scheduler (W3.15).

Persists schedules to ``<axiom_home>/automation.json`` and turns a due schedule
into a normal W4.1 :class:`~axiom.core.tasks.Task` whose ``source`` is
``"automation"``. Unattended work is constrained: a schedule's ``max_risk`` is a
``safe``/``medium`` literal, so an automated task can never be configured to
silently inherit HIGH/CRITICAL approval. Skipped intervals are recorded as
``missed_runs`` instead of being silently dropped.
"""

from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from axiom.core.config import axiom_home
from axiom.core.tasks import Task, TaskState, TaskStore


class ScheduleInterval(str, Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"


def _interval_seconds(interval: ScheduleInterval) -> float:
    return {
        ScheduleInterval.HOURLY: 3600.0,
        ScheduleInterval.DAILY: 86400.0,
        ScheduleInterval.WEEKLY: 604800.0,
    }[interval]


class Schedule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    label: str = ""
    prompt: str = Field(min_length=1, max_length=16000)
    interval: ScheduleInterval = ScheduleInterval.DAILY
    enabled: bool = True
    #: Highest command-risk tier an automated task may inherit (W4.9). Only
    #: ``safe``/``medium`` exist as literals, so HIGH/CRITICAL can never be set.
    max_risk: Literal["safe", "medium"] = "medium"
    created_at: float = Field(default_factory=time.time)
    last_run_at: float | None = None
    next_run_at: float | None = None
    missed_runs: int = 0
    last_task_id: str | None = None


class AutomationStore:
    """Loads and saves schedules to ``<axiom_home>/automation.json``."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (axiom_home() / "automation.json")

    def load(self) -> list[Schedule]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        schedules: list[Schedule] = []
        for item in raw:
            try:
                schedules.append(Schedule.model_validate(item))
            except Exception:
                continue
        return schedules

    def save(self, schedules: list[Schedule]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [s.model_dump(mode="json") for s in schedules]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, schedule: Schedule) -> Schedule:
        schedules = self.load()
        schedules.append(schedule)
        self.save(schedules)
        return schedule

    def remove(self, schedule_id: str) -> bool:
        schedules = self.load()
        kept = [s for s in schedules if s.id != schedule_id]
        changed = len(kept) != len(schedules)
        if changed:
            self.save(kept)
        return changed

    def toggle(self, schedule_id: str, enabled: bool) -> bool:
        schedules = self.load()
        for schedule in schedules:
            if schedule.id == schedule_id:
                schedule.enabled = enabled
                self.save(schedules)
                return True
        return False


def due_schedules(schedules: list[Schedule], now: float | None = None) -> list[Schedule]:
    """Enabled schedules whose next run is due (computing next_run lazily)."""
    now = time.time() if now is None else now
    due: list[Schedule] = []
    for schedule in schedules:
        if not schedule.enabled:
            continue
        if schedule.next_run_at is None:
            schedule.next_run_at = schedule.created_at + _interval_seconds(schedule.interval)
        if now >= schedule.next_run_at:
            due.append(schedule)
    return due


def create_automation_task(schedule: Schedule, store: TaskStore) -> Task:
    """Turn a due schedule into a real W4.1 Task (``source="automation"``)."""
    task = Task(
        goal=schedule.prompt,
        state=TaskState.PENDING,
        source="automation",
        max_risk=schedule.max_risk,
    )
    store.save(task)
    return task


def record_run(schedule: Schedule, now: float, task_id: str) -> Schedule:
    """Mark a schedule as run now; any skipped interval becomes ``missed_runs``."""
    interval = _interval_seconds(schedule.interval)
    if schedule.next_run_at is not None and now >= schedule.next_run_at:
        schedule.missed_runs += int((now - schedule.next_run_at) // interval)
    schedule.last_run_at = now
    schedule.next_run_at = now + interval
    schedule.last_task_id = task_id
    return schedule


def run_due(schedules: list[Schedule], store: TaskStore, now: float | None = None) -> list[Task]:
    """The scheduler tick: create an automation task for every due schedule.

    Each due schedule becomes a real PENDING W4.1 task in ``store`` and is then
    marked as run (with any skipped interval recorded), so automation always
    flows through the canonical Task Runtime.
    """
    now = time.time() if now is None else now
    tasks: list[Task] = []
    for schedule in due_schedules(schedules, now):
        tasks.append(create_automation_task(schedule, store))
        record_run(schedule, now, tasks[-1].id)
    return tasks


__all__ = [
    "AutomationStore",
    "Schedule",
    "ScheduleInterval",
    "create_automation_task",
    "due_schedules",
    "record_run",
    "run_due",
]
