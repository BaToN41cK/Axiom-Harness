"""Workspace side panel: clicking a file mentions it in the prompt."""

from __future__ import annotations

from textual.app import App

from axiom.core.chat import ChatSession
from axiom.frontends.tui.app import WorkspaceScreen
from axiom.frontends.tui.widgets.activity import ActivityPanel


class _Harness(App):
    CSS_PATH = "../../src/axiom/frontends/tui/theme.tcss"

    def on_mount(self) -> None:
        self.push_screen(WorkspaceScreen(ChatSession()))


async def test_file_chosen_inserts_mention() -> None:
    app = _Harness()
    async with app.run_test(size=(150, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        screen.input_bar.input.load_text("look at")
        panel = screen.query_one(ActivityPanel)
        panel.post_message(ActivityPanel.FileChosen("src/main.py"))
        await pilot.pause()
        assert screen.input_bar.input.text == "look at @src/main.py "
