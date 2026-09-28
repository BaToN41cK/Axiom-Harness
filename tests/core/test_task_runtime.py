"""Task runtime acceptance: real Agent, filesystem, Git and pytest; fake model transport only."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest

from axiom.core.events import ErrorEvent, ToolCallEvent, ToolResultEvent
from axiom.core.ollama import StreamChunk, ToolCallRequest
from axiom.core.planner import PlanStep, TaskPlan
from axiom.core.tasks import Task, TaskState
from axiom.core.tools.base import ToolResult
from axiom.core.tools.processes import process_group_options
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


async def test_task_plan_create_save_and_custom_start(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch, tmp_path)
    mod = _bridge_module()
    monkeypatch.setattr(mod, "_write_line", lambda line: None)

    async def generate(prompt):
        return plan_json()

    monkeypatch.setattr(session, "_plan_task", generate)
    # 1. task_plan uses an actual validated model response.
    plan = await mod._handle(session, "task_plan", {"goal": "Реализовать фичу"})
    assert "steps" in plan
    assert len(plan["steps"]) >= 1

    # 2. task_create creates pending task with plan
    created = await mod._handle(session, "task_create", {
        "goal": "Реализовать фичу",
        "plan": plan,
    })
    assert created["state"] == "pending"
    assert created["plan"]["steps"] == plan["steps"]

    # 3. task_save allows editing steps and goal
    plan["steps"][0]["goal"] = "Шаг 1: Спецификация"
    saved = await mod._handle(session, "task_save", {
        "id": created["id"],
        "plan": plan,
        "goal": "Реализовать фичу v2",
    })
    assert saved["goal"] == "Реализовать фичу v2"
    assert saved["plan"]["steps"][0]["goal"] == "Шаг 1: Спецификация"

    # 4. task_delete removes task
    del_res = await mod._handle(session, "task_delete", {"id": created["id"]})
    assert del_res == {"deleted": True}
    assert await mod._handle(session, "task_state", {"id": created["id"]}) is None


async def test_planned_task_runs_edited_plan_and_checks_every_step(tmp_path, monkeypatch):
    """User writes a goal -> AI plans -> user edits the plan -> run ticks every step off."""
    ws = tmp_path / "ws2"
    ws.mkdir()
    (ws / "calc.py").write_text("def mul(a, b):\n    return a - b\n", encoding="utf-8")
    (ws / "test_calc.py").write_text(
        "from calc import mul\ndef test_mul():\n    assert mul(2, 3) == 6\n", encoding="utf-8")
    subprocess.run(["git", "init", str(ws)], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    session = _session(tmp_path, monkeypatch, ws)
    mod = _bridge_module()
    lines: list[str] = []
    monkeypatch.setattr(mod, "_write_line", lines.append)

    # The planner model proposes a three-step plan; it must not mark anything done.
    plan_json = json.dumps({
        "steps": [
            {"id": "inspect", "goal": "Read calc.py", "tools": ["read_file"], "done_when": "code seen"},
            {"id": "fix", "goal": "Return a * b", "tools": ["edit_file"], "done_when": "mul returns 6"},
            {"id": "docs", "goal": "Update the changelog", "tools": [], "done_when": "changelog touched"},
        ],
        "definition_of_done": ["mul(2, 3) == 6"],
    })

    async def transport(self, model, messages, **kwargs):
        prompt = next(m["content"] for m in messages if m["role"] == "user")
        seen_tool_result = "Tool result" in str(messages)
        if prompt.startswith("Plan the following"):
            yield StreamChunk(content=plan_json, done=True)
        elif prompt.startswith("Review task acceptance"):
            yield StreamChunk(content='{"approved":true,"reason":"ok"}', done=True)
        elif "Current step: Изучить calc.py" in prompt:
            if seen_tool_result:
                yield StreamChunk(content="Изучил calc.py.", done=True)
            else:
                yield StreamChunk(tool_calls=[ToolCallRequest(name="read_file",
                                                              arguments={"path": "calc.py"})], done=True)
        elif "Current step: Return a * b" in prompt:
            if seen_tool_result:
                yield StreamChunk(content="Исправил умножение.", done=True)
            else:
                yield StreamChunk(tool_calls=[ToolCallRequest(name="edit_file", arguments={
                    "path": "calc.py", "old_text": "return a - b", "new_text": "return a * b"})], done=True)
        else:
            # The appended step has no tools: it must complete as plain prose.
            yield StreamChunk(content="Проверил вручную, всё работает.", done=True)

    monkeypatch.setattr("axiom.core.providers.runtime.ProviderChatClient.chat", transport)

    # 1. Plan first, without executing anything.
    plan = await mod._handle(session, "task_plan", {"goal": "Fix the multiplication bug"})
    assert [s["id"] for s in plan["steps"]] == ["inspect", "fix", "docs"]
    assert not session.busy

    # 2. Create the task from that plan; nothing is running yet.
    task = await mod._handle(session, "task_create", {"goal": "Fix the multiplication bug", "plan": plan})
    assert task["state"] == "pending"
    assert task["plan"]["steps"][0]["state"] == "pending"

    # 3. The user edits the plan before starting: rename, drop a step, append a new one.
    edited = json.loads(json.dumps(plan))
    edited["steps"][0]["goal"] = "Изучить calc.py"
    edited["steps"] = [s for s in edited["steps"] if s["id"] != "docs"]
    edited["steps"].append({"id": "manual", "goal": "Проверить руками", "tools": [],
                            "done_when": "проверено", "state": "pending", "result": ""})
    saved = await mod._handle(session, "task_save", {"id": task["id"], "plan": edited})
    assert [s["goal"] for s in saved["plan"]["steps"]] == ["Изучить calc.py", "Return a * b", "Проверить руками"]
    assert session.task_store.load(task["id"]).plan.steps[0].goal == "Изучить calc.py"

    # 4. Execute the edited plan as-is; steps are ticked off automatically.
    result = await mod._handle(session, "task_start", {"goal": saved["goal"], "plan": saved["plan"]})
    assert result["state"] == "completed", result
    assert all(s["state"] == "completed" for s in result["plan"]["steps"]), result["plan"]
    assert all(s["result"] for s in result["plan"]["steps"]), result["plan"]
    assert "return a * b" in (ws / "calc.py").read_text(encoding="utf-8")
    assert result["tests"][0]["executed"] is True
    assert "1 passed" in str(result["tests"])

    # 5. Every step flip is streamed, and the task ends completed.
    events = [json.loads(line)["event"] for line in lines]
    step_events = [e for e in events if e["kind"] == "task.step"]
    assert len(step_events) == 6  # running + completed for each of the three steps
    assert [e["task"]["plan"]["steps"][0]["state"] for e in step_events[:1]] == ["running"]
    assert events[-1]["kind"] == "task.completed"
    assert len(result["plan_history"]) == 1  # an explicit plan is not re-planned


async def test_quality_scenario_failed_check_repairs_then_diff_can_be_rejected(tmp_path, monkeypatch):
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "calc.py").write_text("value = 1\n", encoding="utf-8")
    session = _session(tmp_path, monkeypatch, ws)
    reports = [
        {"ok": False, "executed": True, "summary": "pytest failed", "checks": {"failed": "assert"}},
        {"ok": True, "executed": True, "summary": "pytest passed", "checks": {"passed": 1}},
    ]
    prompts = []

    async def verify():
        return reports.pop(0)

    async def execute(*, step, prompt, on_event):
        prompts.append((step.id, prompt))
        if step.id == "fix":
            on_event(ToolCallEvent(name="write_file", arguments={"path": "calc.py", "content": "value = 2\n"}))
            (ws / "calc.py").write_text("value = 2\n", encoding="utf-8")
            on_event(ToolResultEvent(name="write_file", ok=True, content="written"))
        return {"content": "Focused step completed"}

    monkeypatch.setattr(session, "_verify_task", lambda task: verify())
    monkeypatch.setattr(session, "_execute_task_step", execute)
    task = await session.task_start("Change value", plan=TaskPlan(steps=[
        PlanStep(id="fix", goal="Change calc.py", tools=["write_file"], done_when="value is 2")
    ], definition_of_done=["value is 2"]))
    assert task.state is TaskState.COMPLETED
    assert len(task.tests) == 2
    assert task.tests[0]["executed"] is True and task.tests[0]["ok"] is False
    assert "pytest failed" in prompts[1][1]
    assert "value = 1" in task.diffs["calc.py"] and "value = 2" in task.diffs["calc.py"]
    reviewed = session.task_review(task.id, "reject")
    assert reviewed.review_status == "rejected"
    assert "calc.py" in reviewed.diffs
    assert (ws / "calc.py").read_text(encoding="utf-8") == "value = 1\n"


async def test_verify_task_rejects_contradictory_check_without_reviewer(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch, tmp_path)
    called = []

    async def fake_execute(name, args, *, approved):
        return ToolResult(name=name, ok=True, content="Checks PASSED",
                          data={"status": "passed", "steps": [
                              {"name": "test", "ok": True, "exit_code": 1},
                          ]})

    async def fake_reviewer(**kwargs):
        called.append(True)
        return {"content": '{"approved": true}'}

    monkeypatch.setattr(session.tools, "execute", fake_execute)
    monkeypatch.setattr(session, "_subagent_runner", fake_reviewer)
    report = await session._verify_task(Task(goal="Fix it"))
    assert report["ok"] is False
    assert "non-zero" in report["error"]
    assert called == []


async def test_quality_scenario_add_feature_runs_real_pytest(tmp_path, monkeypatch):
    ws = tmp_path / "feature-repo"
    ws.mkdir()
    (ws / "test_slugify.py").write_text(
        "from slugify import slugify\n\ndef test_slugify():\n    assert slugify('Hello World') == 'hello-world'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", str(ws)], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    session = _session(tmp_path, monkeypatch, ws)

    async def transport(self, model, messages, **kwargs):
        if "Review task acceptance" in str(messages):
            yield StreamChunk(content='{"approved":true,"reason":"feature and real test verified"}', done=True)
        elif "Tool result (write_file)" in str(messages):
            yield StreamChunk(content="Added slugify and the tests pass.", done=True)
        else:
            yield StreamChunk(tool_calls=[ToolCallRequest(name="write_file", arguments={
                "path": "slugify.py",
                "content": "import re\n\ndef slugify(value):\n    return re.sub(r'\\s+', '-', value.strip().lower())\n",
            })], done=True)

    monkeypatch.setattr("axiom.core.providers.runtime.ProviderChatClient.chat", transport)
    plan = TaskPlan(steps=[PlanStep(id="feature", goal="Add slugify", tools=["write_file"],
                                    done_when="slugify converts words to lowercase hyphenated text")],
                    definition_of_done=["New behavior passes pytest"])
    task = await session.task_start("Add slugify feature", plan=plan)
    assert task.state is TaskState.COMPLETED
    assert task.tests[0]["executed"] is True
    assert "1 passed" in str(task.tests[0])
    assert "slugify.py" in task.diffs


async def test_quality_scenario_detached_task_survives_command_return(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch, tmp_path)
    started = asyncio.Event()
    finish = asyncio.Event()

    async def blocked(**kwargs):
        started.set()
        await finish.wait()
        return {"content": "done"}

    monkeypatch.setattr(session, "_execute_task_step", blocked)
    mod = _bridge_module()
    launched = await mod._handle(session, "task_launch", {"goal": "Long running task", "plan": {
        "steps": [{"id": "wait", "goal": "Wait", "tools": [], "done_when": "released"}],
        "definition_of_done": ["released"],
    }})
    assert launched["state"] == "pending"
    await asyncio.wait_for(started.wait(), 5)
    stored = session.task_state(launched["id"])
    assert stored is not None and stored.state is TaskState.EXECUTING
    assert session.busy
    finish.set()
    for _ in range(100):
        if not session.busy:
            break
        await asyncio.sleep(0.01)
    assert not session.busy


def test_windows_task_processes_use_hidden_console_flag():
    options = process_group_options()
    if os.name == "nt":
        assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
