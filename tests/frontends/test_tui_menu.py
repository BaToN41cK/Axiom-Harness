"""TUI regression tests for the slash-command autocomplete menu."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.widgets import Input, OptionList

from axiom.core.chat import ChatSession
from axiom.frontends.tui.app import WorkspaceScreen
from axiom.frontends.tui.widgets.commands import COMMANDS, CommandMenu
from axiom.frontends.tui.widgets.find import ChatFindBar
from axiom.frontends.tui.widgets.messages import UserMessage
from axiom.frontends.tui.widgets.panels import (
    AgentsPanel,
    BenchmarkPanel,
    KnowledgePanel,
    MemoryPanel,
    OrchestrationPanel,
    PermissionsPanel,
    ProvidersPanel,
    TrajectoryDetailPanel,
    TrajectoryPanel,
    agent_rows,
    format_trajectory_detail,
)
from axiom.frontends.tui.widgets.prompt import InputBar


class _TuiHarness(App):
    """Minimal app mounting the real WorkspaceScreen (no splash, no Ollama)."""

    CSS_PATH = "../../src/axiom/frontends/tui/theme.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.session = ChatSession()

    def compose(self) -> ComposeResult:
        yield WorkspaceScreen(self.session)


@asynccontextmanager
async def workspace() -> AsyncIterator[tuple[App, Pilot]]:
    """Run the real WorkspaceScreen; kept inside the test's own context."""
    app = _TuiHarness()
    async with app.run_test(size=(100, 30)) as pilot:
        for _ in range(2):
            await pilot.pause()
        yield app, pilot


async def test_startup_focus_is_prompt() -> None:
    """The prompt holds focus at startup (auto-focus must not steal it)."""
    async with workspace() as (app, _pilot):
        bar = app.screen.query_one(InputBar)
        assert app.focused is bar.input


async def test_slash_opens_menu() -> None:
    async with workspace() as (app, pilot):
        bar = app.screen.query_one(InputBar)
        menu = bar.query_one(CommandMenu)

        await pilot.press("/")
        await pilot.pause()
        await pilot.pause()

        assert bar.input.text == "/"
        assert menu.open is True
        assert menu.display is True
        assert menu.highlighted_command() is not None


async def test_menu_filters_and_navigates() -> None:
    async with workspace() as (app, pilot):
        bar = app.screen.query_one(InputBar)
        menu = bar.query_one(CommandMenu)

        await pilot.press("/", "h", "e")
        await pilot.pause()
        await pilot.pause()

        assert bar.input.text == "/he"
        assert menu.open is True

        highlighted = menu.highlighted_command()
        assert highlighted is not None
        assert highlighted.name == "/help"

        # At least two candidates match "/he"; arrow-down moves the highlight.
        await pilot.press("down")
        await pilot.pause()
        second = menu.highlighted_command()
        assert second is not None


async def test_enter_completes_partial_token() -> None:
    """Enter on a partial token completes it; the menu stays for further edits."""
    async with workspace() as (app, pilot):
        bar = app.screen.query_one(InputBar)
        menu = bar.query_one(CommandMenu)

        await pilot.press("/", "h", "e")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert bar.input.text == "/help"
        # show_for re-opens the menu for the completed token; the next Enter
        # executes it (exact match) — see test_enter_executes_exact_command.
        assert menu.open is True


async def test_enter_executes_exact_command() -> None:
    """Enter on an exact token executes it, clears the prompt, closes the menu."""
    async with workspace() as (app, pilot):
        bar = app.screen.query_one(InputBar)
        menu = bar.query_one(CommandMenu)

        await pilot.press("/", "h", "e", "l", "p")
        await pilot.pause()
        assert menu.open is True

        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert bar.input.text == ""
        assert menu.open is False


async def test_typing_argument_hides_menu() -> None:
    """A trailing space means the command is settled: the menu closes."""
    async with workspace() as (app, pilot):
        bar = app.screen.query_one(InputBar)
        menu = bar.query_one(CommandMenu)

        await pilot.press("/", "m", "o")
        await pilot.pause()
        assert menu.open is True

        await pilot.press("space")
        await pilot.pause()
        await pilot.pause()
        assert bar.input.text == "/mo "
        assert menu.open is False


async def test_plain_text_never_opens_menu() -> None:
    async with workspace() as (app, pilot):
        bar = app.screen.query_one(InputBar)
        menu = bar.query_one(CommandMenu)

        await pilot.press("h", "i")
        await pilot.pause()
        await pilot.pause()

        assert bar.input.text == "hi"
        assert menu.open is False
        assert menu.display is False


# ------------------------------------------------- harness commands and panels


def test_harness_commands_are_registered() -> None:
    names = {command.name for command in COMMANDS}
    assert {
        "/trajectory", "/providers", "/agents", "/permissions", "/profiles",
        "/plugins", "/memory",
    } <= names


async def test_trajectory_command_opens_viewer() -> None:
    async with workspace() as (app, pilot):
        session = app.session
        session.trajectory.append("tool.call", "read_file", actor="coder",
                                  data={"tool": "read_file", "path": "main.py"})
        screen = app.screen.query_one(WorkspaceScreen)
        screen._execute_command("/trajectory")
        await pilot.pause()
        await pilot.pause()
        panel = app.screen
        assert isinstance(panel, TrajectoryPanel)
        assert len(panel._lines) == 1


async def test_trajectory_step_opens_detail_panel() -> None:
    async with workspace() as (app, pilot):
        session = app.session
        event = session.trajectory.append("tool.call", "read_file", actor="coder",
                                         data={"tool": "read_file"})
        screen = app.screen.query_one(WorkspaceScreen)
        screen._trajectory_step_chosen(str(event.seq))
        await pilot.pause()
        await pilot.pause()
        panel = app.screen
        assert isinstance(panel, TrajectoryDetailPanel)
        assert "read_file" in format_trajectory_detail(panel._detail)


async def test_providers_command_opens_panel() -> None:
    async with workspace() as (app, pilot):
        screen = app.screen.query_one(WorkspaceScreen)
        screen._execute_command("/providers")
        await pilot.pause()
        await pilot.pause()
        panel = app.screen
        assert isinstance(panel, ProvidersPanel)
        assert panel._rows  # real provider rows, never an empty guess


async def test_agents_command_opens_panel() -> None:
    async with workspace() as (app, pilot):
        screen = app.screen.query_one(WorkspaceScreen)
        screen._execute_command("/agents")
        await pilot.pause()
        await pilot.pause()
        panel = app.screen
        assert isinstance(panel, AgentsPanel)
        assert {row["id"] for row in panel._rows} >= {"coder", "orchestrator"}


async def test_memory_command_opens_panel_and_persists(tmp_path, monkeypatch) -> None:
    """/memory shows real persisted items; add and delete round-trip (W2.1)."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    async with workspace() as (app, pilot):
        session = app.session
        # Isolate this session's stores from any real home directory.
        from axiom.core.memory import MemoryStore, MemoryTools

        session.memory_store = MemoryStore()
        session.memory_project_store = None
        session.memory_tools = MemoryTools(session.memory_store, None)

        screen = app.screen.query_one(WorkspaceScreen)
        screen._execute_command("/memory")
        await pilot.pause()
        await pilot.pause()
        panel = app.screen
        assert isinstance(panel, MemoryPanel)
        assert panel._rows == []

        # 'a' adds the text typed into the content input.
        item_id = session.memory_write_for_user("User prefers short answers")
        assert item_id is not None
        panel._rows = session.memory_rows()
        panel._refresh_rows()
        assert len(panel._rows) == 1
        assert panel._rows[0]["content"] == "User prefers short answers"

        # 'd' on the highlighted row deletes it from disk.
        option_list = panel.query_one("#memory-list", OptionList)
        option_list.highlighted = 0
        await panel.action_delete_item()
        await pilot.pause()
        assert session.memory_rows() == []
        assert session.memory_store.count() == 0


async def test_knowledge_command_indexes_and_searches(tmp_path, monkeypatch) -> None:
    """/knowledge indexes a real folder and cites fragments (W2.2)."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    docs = tmp_path / "kb"
    docs.mkdir()
    (docs / "runbook.md").write_text(
        "# Runbook\n\nThe staging VPN gateway is gw-staging.internal.\n",
        encoding="utf-8",
    )
    async with workspace() as (app, pilot):
        session = app.session
        screen = app.screen.query_one(WorkspaceScreen)
        screen._execute_command("/knowledge")
        await pilot.pause()
        await pilot.pause()
        panel = app.screen
        assert isinstance(panel, KnowledgePanel)

        added = await session.knowledge_add_collection("runbook", str(docs))
        assert added["ok"] and added["stats"]["indexed"] == 1
        panel._rows = session.knowledge_rows()
        panel._refresh_rows()
        assert len(panel._rows) == 1
        assert panel._rows[0]["name"] == "runbook"
        assert panel._rows[0]["files"] == 1

        hits = await session.knowledge_search_rows("staging VPN")
        assert hits and hits[0]["source"] == "runbook.md"
        assert "gw-staging" in hits[0]["text"]

        assert session.knowledge_remove_collection("runbook")
        assert session.knowledge_rows() == []



def test_agent_rows_mirror_the_registry() -> None:
    from axiom.core.agents import AgentRegistry

    rows = agent_rows(AgentRegistry().all())
    assert len(rows) == len(AgentRegistry().ids())
    assert all(row["provider_id"] == "ollama" for row in rows)


def test_format_trajectory_detail_handles_missing_data() -> None:
    assert format_trajectory_detail(None) == "No details for this step."
    rendered = format_trajectory_detail(
        {"seq": 3, "kind": "tool.call", "actor": "coder", "summary": "read", "data": {"a": 1}}
    )
    assert "seq      3" in rendered
    assert '"a": 1' in rendered


async def test_permissions_command_opens_panel_and_applies_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    async with workspace() as (app, pilot):
        screen = app.screen.query_one(WorkspaceScreen)
        screen._execute_command("/permissions")
        await pilot.pause()
        await pilot.pause()
        panel = app.screen
        assert isinstance(panel, PermissionsPanel)
        panel.dismiss("ask")
        await pilot.pause()
        await pilot.pause()
        assert app.session.permissions.mode.value == "ask"


def test_permissions_panel_lists_real_modes() -> None:
    values = [value for value, _label, _hint in PermissionsPanel.MODES]
    assert values == ["ask", "auto_approve_safe", "auto_approve_all"]


async def test_providers_panel_has_hidden_key_input_and_model_list() -> None:
    async with workspace() as (app, pilot):
        screen = app.screen.query_one(WorkspaceScreen)
        screen._execute_command("/providers")
        await pilot.pause()
        await pilot.pause()
        panel = app.screen
        assert isinstance(panel, ProvidersPanel)
        assert panel.query_one("#provider-key", Input).password is True
        assert panel.query_one("#provider-models", OptionList) is not None


async def test_provider_pick_model_sets_router_primary(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    async with workspace() as (app, _pilot):
        screen = app.screen.query_one(WorkspaceScreen)
        message = await screen._provider_pick_model("zai", "glm-4.6")
        assert app.session.config.router_primary == {
            "provider_id": "zai",
            "model": "glm-4.6",
        }
        assert "zai/glm-4.6" in message


async def test_ctrl_f_searches_mounted_transcript() -> None:
    async with workspace() as (app, pilot):
        screen = app.screen.query_one(WorkspaceScreen)
        screen.chat_view.add(UserMessage("alpha deployment notes"))
        screen.chat_view.add(UserMessage("unrelated"))
        await pilot.press("ctrl+f")
        await pilot.pause()
        bar = app.screen.query_one(ChatFindBar)
        assert bar.display is True
        await pilot.press("a", "l", "p", "h", "a")
        await pilot.pause()
        assert bar._matches == 1
        assert bar._index == 0
        await pilot.press("escape")
        await pilot.pause()
        assert bar.display is False


def test_benchmark_panel_keeps_real_report_shape() -> None:
    panel = BenchmarkPanel({
        "runs": [{"scenario": "smoke", "phase": "cold", "repetition": 0,
                  "ok": False, "duration_ms": 12.0, "error": "No model"}],
        "summary": {},
    })
    assert panel._report["runs"][0]["ok"] is False
    assert panel.subtitle_lines() == ["1 measured run(s)   ·   no fabricated values"]


def test_orchestration_panel_projects_real_trajectory() -> None:
    from axiom.core.trajectory import Trajectory

    trajectory = Trajectory()
    trajectory.append("old", "before run", actor="system")
    trajectory.append("agent.start", "coder: task", actor="coder")
    panel = OrchestrationPanel(trajectory, baseline=1)
    panel._render = lambda: None
    panel._poll()
    assert len(panel._events) == 1
    assert panel._events[0]["kind"] == "agent.start"


async def test_orchestration_panel_mounts_and_updates(monkeypatch) -> None:
    import asyncio

    async with workspace() as (app, _pilot):
        screen = app.screen.query_one(WorkspaceScreen)

        async def fake_run(task: str, **kwargs):
            screen.session.trajectory.append("agent.start", f"coder: {task}", actor="coder")
            return {"ok": False, "error": "test finished"}

        monkeypatch.setattr(screen.session, "run_orchestrated", fake_run)
        screen._execute_command("/orchestrate inspect")
        await asyncio.sleep(0.1)
        panel = app.screen
        assert isinstance(panel, OrchestrationPanel)
        panel._poll()
        assert any(event["kind"] == "agent.start" for event in panel._events)
        assert panel._running is False
