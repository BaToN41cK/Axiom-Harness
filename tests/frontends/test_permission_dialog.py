"""W2.4: the TUI permission dialog and its real wiring into WorkspaceScreen."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from textual.app import App, ComposeResult
from textual.pilot import Pilot

from axiom.core.chat import ChatSession
from axiom.core.permissions import PermissionOutcome
from axiom.frontends.tui.app import WorkspaceScreen
from axiom.frontends.tui.widgets.permissions import PermissionDialog


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
    app = _TuiHarness()
    async with app.run_test(size=(100, 30)) as pilot:
        for _ in range(2):
            await pilot.pause()
        yield app, pilot


async def test_workspace_connects_the_permission_callback() -> None:
    """The screen really subscribes the modal to the core PermissionManager."""
    async with workspace() as (app, _pilot):
        assert app.session.permissions._request_callback is not None


async def test_dialog_returns_all_three_outcomes() -> None:
    """Enter = once, F2 = always, Escape = deny — no fabricated answers."""
    async with workspace() as (app, pilot):
        results: list[PermissionOutcome] = []

        app.push_screen(
            PermissionDialog("write_file", {"path": "a.txt"}),
            callback=results.append,
        )
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert results == [PermissionOutcome.ALLOW_ONCE]

        app.push_screen(
            PermissionDialog("write_file", {"path": "a.txt"}),
            callback=results.append,
        )
        await pilot.pause()
        await pilot.press("f2")
        await pilot.pause()
        assert results[-1] == PermissionOutcome.ALLOW_ALWAYS

        app.push_screen(
            PermissionDialog("terminal", {"command": "rm -rf build"}),
            callback=results.append,
        )
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert results[-1] == PermissionOutcome.DENY


async def test_callback_opens_the_dialog_and_returns_the_outcome() -> None:
    """The wired callback really suspends the caller until the user answers."""
    async with workspace() as (app, pilot):
        callback = app.session.permissions._request_callback
        assert callback is not None
        answers: list[PermissionOutcome] = []

        async def ask() -> None:
            answers.append(await callback("memory_write", {"content": "x"}))

        # push_screen_wait is worker-only (exactly like the real send path).
        app.run_worker(ask())
        await pilot.pause()
        await pilot.pause()
        assert not answers  # still waiting for a real answer
        await pilot.press("f2")
        await asyncio.sleep(0.05)
        assert answers == [PermissionOutcome.ALLOW_ALWAYS]
