"""Task runtime acceptance: real Agent, filesystem, Git and pytest; fake model transport only."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys

import pytest

from axiom.core.events import ErrorEvent
from axiom.core.ollama import StreamChunk, ToolCallRequest
from axiom.core.planner import PlanStep, TaskPlan
from axiom.core.tasks import Task, TaskState
from tests.core.test_orchestrator_runtime_a import _session
from tests.test_bridge import _bridge_module


def plan_json():
    return json.dumps({
        "steps": [{"id": "fix", "goal": "Fix buggy.py", "tools": ["read_file", "edit_file"],
                   "done_when": "add returns the sum"}],
        "definition_of_done": ["add returns the sum and tests pass"],
    })


async def test_task_bridge_real_edit_verify_and_restart(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "buggy.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (ws / "test_buggy.py").write_text("from buggy import add\ndef test_add():\n    assert add(2, 3) == 5\n",
                                    encoding="utf-8")
    subprocess.run(["git", "init", str(ws)], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    before = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ws, capture_output=True,
                            stdin=subprocess.DEVNULL, timeout=30)
    assert before.returncode == 1
    session = _session(tmp_path, monkeypatch, ws)
    calls = []

    async def transport(self, model, messages, **kwargs):
        prompt = next(m["content"] for m in messages if m["role"] == "user")
        calls.append(prompt)
        if prompt.startswith("Plan the following"):
            assert kwargs.get("tools") is None
            yield StreamChunk(content=plan_json(), done=True)
        elif prompt.startswith("Review task acceptance"):
            yield StreamChunk(content='{"approved":true,"reason":"sum and checks verified"}', done=True)
        elif "Tool result (edit_file)" in str(messages):
            yield StreamChunk(content="Changed buggy.py to return a + b.", done=True)
        elif "Tool result (read_file)" in str(messages):
            yield StreamChunk(tool_calls=[ToolCallRequest(name="edit_file", arguments={
                "path": "buggy.py", "old_text": "return a - b", "new_text": "return a + b",
            })], done=True)
        else:
            yield StreamChunk(tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "buggy.py"})],
                              done=True)

    monkeypatch.setattr("axiom.core.providers.runtime.ProviderChatClient.chat", transport)
    mod = _bridge_module()
    lines = []
    monkeypatch.setattr(mod, "_write_line", lines.append)
    result = await mod._handle(session, "task_start", {"goal": "Fix buggy.py"})
    assert result["state"] == "completed", result
    assert result["changed_files"] == ["buggy.py"]
    assert result["tests"][0]["executed"] is True
    assert "1 passed" in str(result["tests"])
    assert "return a + b" in (ws / "buggy.py").read_text(encoding="utf-8")
    assert session.conversation.messages == []
    assert not session.busy
    events = [json.loads(line)["event"] for line in lines]
    assert events[0]["kind"] == "task.started"
    assert events[-1]["kind"] == "task.completed"
    assert all(event["task_id"] == result["id"] for event in events)
    revisions = [event["task"]["revision"] for event in events]
    assert revisions == sorted(set(revisions))
    assert not session.bus._subs["task.event"]
    restarted = _session(tmp_path, monkeypatch, ws)
    assert (await mod._handle(restarted, "tasks", {}))[0]["id"] == result["id"]
    count = len(calls)
    resumed = await mod._handle(restarted, "task_resume", {"id": result["id"]})
    assert resumed["state"] == "completed"
    assert len(calls) == count  # completed tasks are never replayed


async def test_cancel_releases_busy_and_restart_skips_completed_steps(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch, tmp_path)
    plan = TaskPlan(steps=[
        PlanStep(id="done", goal="Done", done_when="Done", state="completed", result="existing evidence"),
        PlanStep(id="next", goal="Next", done_when="Checked"),
    ], definition_of_done=["Both steps done"])
    task = Task(goal="Task", scope=str(tmp_path), plan=plan)
    session.task_store.save(task)
    started = asyncio.Event()

    async def blocked(**kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(session, "_execute_task_step", blocked)
    run = asyncio.create_task(session.task_resume(task.id))
    await asyncio.wait_for(started.wait(), 5)
    assert session.busy
    with pytest.raises(ValueError, match="already running"):
        await session.task_start("other")
    assert any(isinstance(e, ErrorEvent) and e.kind == "busy" for e in [e async for e in session.send("hi")])
    with pytest.raises(ValueError, match="Stop"):
        session.clear_workspace()
    assert session.task_cancel("wrong-id") is False
    assert session.task_cancel(task.id) is True
    result = await asyncio.wait_for(run, 5)
    assert result.state is TaskState.CANCELLED
    assert session.busy is False
    restarted = _session(tmp_path, monkeypatch, tmp_path)
    seen = []

    async def finish(*, step, prompt, on_event):
        seen.append(step.id)
        assert "existing evidence" in prompt
        return {"content": "new evidence"}

    monkeypatch.setattr(restarted, "_execute_task_step", finish)
    resumed = await restarted.task_resume(task.id)
    assert resumed.state is TaskState.WAITING_FOR_USER
    assert seen == []
    resumed = await restarted.task_resume(task.id, acknowledge=True)
    assert seen == ["next"]
    assert resumed.state is TaskState.WAITING_FOR_USER  # no git/checks: never fake completion
    assert not resumed.tests[-1]["executed"]


async def test_short_task_skips_planner_and_bridge_reports_failed_model(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch, tmp_path)
    mod = _bridge_module()
    monkeypatch.setattr(mod, "_write_line", lambda line: None)

    async def transport(self, model, messages, **kwargs):
        assert not messages[-1]["content"].startswith("Plan the following")
        yield StreamChunk(content="The workspace is empty.", done=True)

    monkeypatch.setattr("axiom.core.providers.runtime.ProviderChatClient.chat", transport)
    result = await mod._handle(session, "task_start", {"goal": "Describe workspace"})
    assert result["state"] == "waiting_for_user"
    assert result["plan"]["steps"][0]["id"] == "answer"
    assert await mod._handle(session, "task_state", {"id": result["id"]}) == result
    assert await mod._handle(session, "task_cancel", {"id": result["id"]}) == {"cancelled": False}
    session.active_model = None
    failed = await mod._handle(session, "task_start", {"goal": "Fix it"})
    assert failed["state"] == "failed"
    assert "No model" in failed["detail"]
    assert not session.busy
    assert not session.bus._subs["task.event"]
