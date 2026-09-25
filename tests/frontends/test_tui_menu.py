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
from axiom.frontends.tui.widgets.panels import (
    AgentsPanel,
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
    assert {"/trajectory", "/providers", "/agents", "/permissions", "/profiles", "/plugins"} <= names


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
