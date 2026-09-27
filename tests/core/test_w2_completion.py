"""Focused W2.3/W2.9 completion checks."""

from __future__ import annotations

import asyncio
from pathlib import Path

from axiom.core.orchestrator import Orchestrator
from axiom.core.trajectory import Trajectory
from axiom.core.trajectory_store import TrajectoryStore


def test_trajectory_markdown_export_contains_only_recorded_facts() -> None:
    trajectory = Trajectory(run_id="run-1")
    trajectory.append("agent.start", "coder: inspect", actor="coder")
    trajectory.append("agent.done", "coder done", actor="coder", data={"content": "actual"})
    report = trajectory.export_markdown()
    assert "run-1" in report
    assert "agent.start" in report and "coder done" in report
    assert "actual" not in report  # timeline export does not invent/transcribe hidden payloads


def test_trajectory_store_resume_preserves_run_and_records_resume(tmp_path: Path) -> None:
    store = TrajectoryStore(tmp_path)
    trajectory = Trajectory(run_id="resume-me")
    trajectory.append("orchestration.command", "/orchestrate task", actor="user")
    store.save(trajectory)
    resumed = store.resume("resume-me")
    assert resumed is not None
    assert resumed.run_id == "resume-me"
    assert resumed.events[-1].kind == "trajectory.resume"


def test_orchestrator_plan_exposes_dependencies() -> None:
    plan = Orchestrator().plan("orchestrate implement a feature", force_orchestrated=True)
    assert plan.dependencies["coder"] == ["analyst"]
    assert set(plan.dependencies["reviewer"]) == set(plan.agents) - {"reviewer"}


def test_orchestrator_resume_skips_completed_worker() -> None:
    async def run() -> list[str]:
        trajectory = Trajectory(run_id="r")
        trajectory.append("agent.done", "analyst done", actor="analyst", data={"content": "done"})
        calls: list[str] = []

        async def runner(**kwargs):
            calls.append(kwargs["agent"])
            return {"agent": kwargs["agent"], "content": "ok"}

        await Orchestrator().run(
            "implement feature", trajectory, runner, parallel=True,
            limit=5, force_orchestrated=True, max_iterations=1,
        )
        return calls

    calls = asyncio.run(run())
    assert "analyst" not in calls

