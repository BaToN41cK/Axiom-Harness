"""W4.6 acceptance: isolated specialists, the compact report contract, budgets.

Everything here runs the real Agent/Orchestrator/TaskRuntime code; only the
model transport (or the subagent runner, for orchestration units) is faked, so
every assertion covers actual runtime behaviour instead of a mock's opinion.
"""
from __future__ import annotations

from axiom.core.agents import (
    REPORT_SECTIONS,
    AgentProfile,
    AgentRegistry,
    SubagentBudget,
    compact_report,
)
from axiom.core.bus import EventBus
from axiom.core.ollama import StreamChunk
from axiom.core.orchestrator import Orchestrator
from axiom.core.planner import Planner, PlanStep, TaskPlan
from axiom.core.tasks import Task, TaskRunner, TaskState, TaskStore
from axiom.core.tools.meta import tools_for_agent
from axiom.core.trajectory import Trajectory
from tests.core.test_orchestrator_runtime_a import _fake_transport, _session

WRITE_TOOLS = {"write_file", "edit_file", "apply_patch", "delete_file",
               "move_file", "copy_file", "create_directory"}


# ------------------------------------------------------------------ registry

def test_registry_exposes_every_delivery_role() -> None:
    """Explorer/Researcher/Tester/Reviewer/Security/Frontend/Backend all exist."""
    ids = set(AgentRegistry().ids())
    assert {"explorer", "researcher", "tester", "reviewer", "security",
            "frontend", "backend", "analyst", "coder", "debugger",
            "architect", "orchestrator"} <= ids
    assert AgentRegistry().get("frontend").name() == "Frontend"


def test_explorer_is_strictly_read_only() -> None:
    """Reconnaissance can look at everything and change nothing."""
    tools = set(tools_for_agent("explorer"))
    assert tools & WRITE_TOOLS == set()
    assert "run_command" not in tools
    assert {"read_file", "list_files", "search_text", "git_diff"} <= tools


def test_frontend_and_backend_own_scoped_surfaces() -> None:
    frontend = set(tools_for_agent("frontend"))
    backend = set(tools_for_agent("backend"))
    for tools in (frontend, backend):
        assert {"read_file", "search_text", "edit_file", "write_file",
                "apply_patch", "run_tests", "verify_changes"} <= tools
        # Specialists never receive the whole global tool surface.
        assert "web_search" not in tools
    assert "run_linter" in backend


def test_custom_profile_can_replace_a_builtin_role() -> None:
    registry = AgentRegistry()
    registry.register(AgentProfile("frontend", "Frontend (team)", model="custom:1b"))
    assert registry.get("frontend").model == "custom:1b"
    assert registry.remove("frontend") is True
    assert registry.get("frontend") is None


# ------------------------------------------------------------ compact report

def test_compact_report_parses_the_five_section_contract() -> None:
    answer = (
        "RESULT: extracted the settings handler\n"
        "FINDINGS: the button used the wrong dispatch id\n"
        "FILES: desktop/src/panel.ts, src/axiom/core/chat.py\n"
        "ERRORS: none\n"
        "RECOMMENDATIONS: add a regression test\n"
    )
    report = compact_report({"content": answer})
    assert tuple(report) == REPORT_SECTIONS
    assert report["RESULT"] == "extracted the settings handler"
    assert report["FILES"] == "desktop/src/panel.ts, src/axiom/core/chat.py"
    assert report["ERRORS"] == "none"
    assert report["RECOMMENDATIONS"] == "add a regression test"
    # Continuation lines belong to the section they follow, prose stays out.
    continued = compact_report({"content": "RESULT: first line\nsecond line"})
    assert continued["RESULT"] == "first line\nsecond line"
    assert continued["FINDINGS"] == ""


def test_compact_report_keeps_prose_and_real_failures() -> None:
    prose = compact_report({"content": "I inspected the module and it looks fine."})
    assert prose["RESULT"].startswith("I inspected")
    assert prose["ERRORS"] == ""
    failed = compact_report({"content": "", "error": "ConnectionError: offline"})
    assert failed["ERRORS"] == "ConnectionError: offline"
    assert failed["RESULT"] == ""
    both = compact_report({"content": "RESULT: partial edit applied",
                           "error": "tool run_command failed"})
    assert both["RESULT"] == "partial edit applied"
    # A real failure is never silently dropped by the summary.
    assert "tool run_command failed" in both["ERRORS"]


def test_compact_report_survives_sectioned_result_and_is_bounded() -> None:
    huge = "\n".join(f"line {index} of a very long worker answer" for index in range(400))
    report = compact_report({"content": f"RESULT: {huge}\nFINDINGS: {huge}\nERRORS: none"})
    assert all(len(value) <= 600 for value in report.values())
    assert sum(len(value) for value in report.values()) <= 2400
    # RESULT is the last section to give way under the total cap.
    assert report["RESULT"]
    explicit = compact_report({"report": {"FINDINGS": "only findings"}})
    assert explicit["FINDINGS"] == "only findings"
    assert explicit["RESULT"] == ""


# ------------------------------------------------------------------- budgets

def test_budget_exhaustion_names_the_reason() -> None:
    budget = SubagentBudget(max_seconds=10, max_tokens=100, max_tool_calls=4, max_retries=2)
    assert budget.check(elapsed=5, tokens=50, tool_calls=2, retries=1) is None
    assert budget.check(elapsed=11, tokens=0, tool_calls=0, retries=0) == "time"
    assert budget.check(elapsed=0, tokens=101, tool_calls=0, retries=0) == "tokens"
    assert budget.check(elapsed=0, tokens=0, tool_calls=5, retries=0) == "tool_calls"
    assert budget.check(elapsed=0, tokens=0, tool_calls=0, retries=3) == "retries"
    # A zero ceiling disables that axis instead of blocking every run.
    unlimited = SubagentBudget(max_tokens=0, max_tool_calls=0)
    assert unlimited.check(tokens=10 ** 6, tool_calls=10 ** 4) is None
    telemetry = SubagentBudget(max_tool_calls=1).as_dict(
        elapsed=1.5, tokens=42, tool_calls=2, retries=0, exhausted="tool_calls")
    assert telemetry["max_tool_calls"] == 1
    assert telemetry["tokens"] == 42 and telemetry["exhausted"] == "tool_calls"


# ---------------------------------------------------- real worker runtime

async def test_subagent_returns_only_the_compact_report(tmp_path, monkeypatch) -> None:
    """A real worker run: transcript stays in the trajectory, report is bounded."""
    session = _session(tmp_path, monkeypatch)
    _fake_transport(monkeypatch, lambda text, kw: [StreamChunk(
        thinking="SECRET-INTERNAL-REASONING that must never reach the main context",
        content=("RESULT: inspected the settings handler\n"
                 "FINDINGS: the button dispatched the wrong id\n"
                 "FILES: desktop/src/panel.ts\n"
                 "ERRORS: none\n"
                 "RECOMMENDATIONS: cover it with a smoke check"),
        done=True,
    )])
    result = await session._subagent_runner(agent="explorer", task="look around",
                                           tools=["read_file"], trajectory=session.trajectory)
    report = result["report"]
    assert report["RESULT"] == "inspected the settings handler"
    assert report["FILES"] == "desktop/src/panel.ts"
    assert "SECRET-INTERNAL-REASONING" not in str(report)
    assert result["budget"]["exhausted"] is None
    assert result["budget"]["tokens"] > 0
    # The full transcript is retained — in the worker's own trajectory record.
    reasoning = [e for e in session.trajectory.events if e.kind == "subagent.reasoning"]
    assert reasoning and "SECRET-INTERNAL-REASONING" in str(reasoning[0].data)


async def test_subagent_budget_exhaustion_keeps_the_partial_result(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path, monkeypatch)
    _fake_transport(monkeypatch, lambda text, kw: [
        StreamChunk(content="PARTIAL: finished the first pass", done=True)])
    result = await session._subagent_runner(
        agent="analyst", task="analyse the module", tools=[],
        budget=SubagentBudget(max_tokens=1), trajectory=session.trajectory,
    )
    assert result["budget_exhausted"] == "tokens"
    assert result["budget"]["exhausted"] == "tokens"
    # The stop is a partial-result stop, not a silent truncation.
    assert "PARTIAL" in result["content"]
    assert result["report"]["RESULT"].startswith("PARTIAL")
    assert any(e.kind == "subagent.budget" for e in session.trajectory.events)


async def test_subagent_retry_budget_is_explicit_in_the_result(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path, monkeypatch)
    _fake_transport(monkeypatch, lambda text, kw: [StreamChunk(content="done", done=True)])
    result = await session._subagent_runner(
        agent="coder", task="rework the change", tools=[], retries=3,
        budget=SubagentBudget(max_retries=2),
    )
    assert result["budget_exhausted"] == "retries"
    assert result["budget"]["retries"] == 3


# -------------------------------------------------------------- orchestrator

async def test_reviewer_sees_only_compact_reports() -> None:
    prompts: list[str] = []

    async def _runner(**kwargs):
        if str(kwargs.get("agent")) == "reviewer":
            prompts.append(str(kwargs.get("task") or ""))
            return {"content": "APPROVED"}
        return {
            "content": "RAW-TRANSCRIPT-MARKER private worker trace",
            "report": {"RESULT": "mapped the module", "FINDINGS": "handler at line 40",
                       "FILES": "src/a.py", "ERRORS": "none", "RECOMMENDATIONS": "none"},
        }

    out = await Orchestrator().run("оркестратор: проверь модуль", runner=_runner,
                                   parallel=True, limit=2, force_orchestrated=True)
    assert prompts, "the reviewer was never asked"
    prompt = prompts[0]
    assert "RESULT: mapped the module" in prompt
    assert "FINDINGS: handler at line 40" in prompt
    assert "RAW-TRANSCRIPT-MARKER" not in prompt
    assert out["reports"][0]["report"]["RESULT"] == "mapped the module"
    assert set(out["reports"][0]["report"]) == set(REPORT_SECTIONS)


async def test_budget_exhausted_worker_is_marked_in_the_review_prompt() -> None:
    prompts: list[str] = []

    async def _runner(**kwargs):
        if str(kwargs.get("agent")) == "reviewer":
            prompts.append(str(kwargs.get("task") or ""))
            return {"content": "APPROVED"}
        return {"content": "RESULT: half done",
                "budget_exhausted": "tokens",
                "report": {"RESULT": "half done", "FINDINGS": "", "FILES": "",
                           "ERRORS": "", "RECOMMENDATIONS": ""}}

    out = await Orchestrator().run("оркестратор: сделай код", runner=_runner,
                                   parallel=True, limit=1, force_orchestrated=True)
    assert "BUDGET: partial result — tokens limit reached" in prompts[0]
    assert out["reports"][0]["budget_exhausted"] == "tokens"


async def test_worker_without_a_report_is_normalised_for_task_state() -> None:
    """A runner that ignores the contract still yields a bounded report."""

    async def _runner(**kwargs):
        if str(kwargs.get("agent")) == "reviewer":
            return {"content": "APPROVED"}
        return {"content": "plain worker answer without sections"}

    out = await Orchestrator().run("оркестратор: сделай код", runner=_runner,
                                   parallel=True, limit=1, force_orchestrated=True)
    for entry in out["reports"]:
        assert entry["report"]["RESULT"] == "plain worker answer without sections"
        assert all(len(value) <= 600 for value in entry["report"].values())


async def test_rework_passes_the_real_retry_count() -> None:
    calls: list[tuple[str, int]] = []
    state = {"reviews": 0}

    async def _runner(**kwargs):
        agent = str(kwargs.get("agent"))
        if agent == "reviewer":
            state["reviews"] += 1
            return ({"content": "REWORK: add the missing check"}
                    if state["reviews"] == 1 else {"content": "APPROVED"})
        calls.append((str(kwargs.get("task") or ""), int(kwargs.get("retries") or 0)))
        return {"content": "done"}

    out = await Orchestrator().run("оркестратор: сделай код", runner=_runner,
                                   parallel=True, limit=1, max_iterations=2,
                                   force_orchestrated=True)
    assert out["approved"] is True
    first_pass = [retries for task, retries in calls if "REVIEW REQUEST" not in task]
    rework = [retries for task, retries in calls if "REVIEW REQUEST" in task]
    assert set(first_pass) == {0}
    assert rework and set(rework) == {1}


def test_surface_roles_are_selected_only_when_really_named() -> None:
    """Frontend/Backend replace coder for a surface-specific request (W4.6)."""
    frontend = Orchestrator().plan("оркестратор: почини UI настроек", force_orchestrated=True)
    assert "frontend" in frontend.agents and "coder" not in frontend.agents
    assert frontend.dependencies["frontend"] == ["analyst"]
    backend = Orchestrator().plan("оркестратор: добавь API endpoint", force_orchestrated=True)
    assert "backend" in backend.agents and "coder" not in backend.agents
    # Both surfaces named → the generalist owns the whole change.
    both = Orchestrator().plan("оркестратор: свяжи UI с API", force_orchestrated=True)
    assert "coder" in both.agents
    # Substring look-alikes never trigger a specialist.
    plain = Orchestrator().plan("оркестратор: собери build проекта", force_orchestrated=True)
    assert "coder" in plain.agents and "frontend" not in plain.agents


# ---------------------------------------------------------------- task state

def _task_runner(tmp_path, execute, verify) -> TaskRunner:
    return TaskRunner(
        store=TaskStore(tmp_path / "tasks"),
        planner=Planner(lambda prompt: "{}"),
        execute=execute,
        verify=verify,
        tools=["read_file"],
        bus=EventBus(),
        trajectory=Trajectory(),
        workspace_root=tmp_path,
    )


def _report_payload(result_text: str) -> dict:
    return {"content": result_text, "agent": "coder",
            "report": {"RESULT": result_text, "FINDINGS": "the return value was wrong",
                       "FILES": "calc.py", "ERRORS": "none", "RECOMMENDATIONS": "none"},
            "budget": SubagentBudget().as_dict(elapsed=1.0, tokens=12, tool_calls=1)}


async def test_task_state_aggregates_compact_reports(tmp_path) -> None:
    async def execute(*, step, prompt, on_event):
        return _report_payload("edited calc.py")

    async def verify():
        return {"ok": True, "executed": True, "summary": "passed"}

    runner = _task_runner(tmp_path, execute, verify)
    task = await runner.run(Task(goal="Fix calc", plan=TaskPlan(
        steps=[PlanStep(id="inspect", goal="Inspect calc.py", tools=["read_file"], done_when="seen")],
        definition_of_done=["passed"],
    )))
    assert task.state is TaskState.COMPLETED
    assert len(task.subagent_reports) == 1
    entry = task.subagent_reports[0]
    assert entry["step_id"] == "inspect" and entry["agent"] == "coder"
    assert entry["report"]["RESULT"] == "edited calc.py"
    assert entry["budget"]["exhausted"] is None
    assert any(event.kind == "task.report" for event in runner.trajectory.events)
    # Ordinary Task State: the aggregate survives a restart round trip.
    loaded = runner.store.load(task.id)
    assert loaded is not None and loaded.subagent_reports == task.subagent_reports


async def test_step_report_is_replaced_and_plain_results_are_ignored(tmp_path) -> None:
    async def execute(*, step, prompt, on_event):
        return {"content": "no report attached"}

    async def verify():
        return {"ok": True, "executed": True, "summary": "passed"}

    runner = _task_runner(tmp_path, execute, verify)
    task = await runner.run(Task(goal="Fix calc", plan=TaskPlan(
        steps=[PlanStep(id="inspect", goal="Inspect", tools=["read_file"], done_when="seen")],
        definition_of_done=["passed"],
    )))
    # No report on the result — nothing is invented for Task State.
    assert task.subagent_reports == []
    step = PlanStep(id="repair", goal="Repair", tools=[], done_when="fixed")
    runner._record_subagent_report(task, step, _report_payload("first attempt"))
    runner._record_subagent_report(task, step, _report_payload("final attempt"))
    assert len(task.subagent_reports) == 1
    assert task.subagent_reports[0]["report"]["RESULT"] == "final attempt"
