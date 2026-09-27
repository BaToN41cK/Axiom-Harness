"""Ctrl+F — find inside the current chat transcript.

The bar is a thin input: the actual hit list comes from the real widgets
mounted in :class:`~axiom.frontends.tui.widgets.messages.ChatView` (user and
assistant turns). No index, no copy of the transcript — matches are computed
live from what is on screen.
"""

from __future__ import annotations

from textual import events
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Input, Static

from axiom.shared import theme


class ChatFindBar(Horizontal):
    """Inline find bar: query, match counter, Enter/Shift+Enter navigation."""

    class Closed(Message):
        """Esc was pressed — hide the bar and hand focus back to the prompt."""

    class Changed(Message):
        def __init__(self, query: str) -> None:
            self.query = query
            super().__init__()

    class Navigate(Message):
        """Enter (+1) / Shift+Enter (-1): cycle through the current matches."""

        def __init__(self, direction: int) -> None:
            self.direction = direction
            super().__init__()

    BINDINGS = [Binding("escape", "close_find", "Close", show=False)]

    def __init__(self, **kwargs) -> None:
        super().__init__(id="find-bar", **kwargs)
        self._matches = 0
        self._index = -1
        self._query = ""

    def compose(self):
        yield Static(f"{theme.TREE_BRANCH} Find", id="find-label", markup=False)
        yield Input(placeholder="search the transcript…", id="find-input")
        yield Static("", id="find-count", markup=False)

    def on_mount(self) -> None:
        # Hidden bars must never steal the initial prompt focus.
        self.query_one("#find-input", Input).can_focus = False

    def action_close_find(self) -> None:
        self.post_message(self.Closed())

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._query = event.value
        self.set_matches(0, -1)
        self.post_message(self.Changed(event.value))

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Navigate(+1))
        elif event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Navigate(-1))

    def set_matches(self, count: int, index: int) -> None:
        """Reflect the real number of matches; ``0/0`` means nothing found."""
        self._matches = count
        self._index = index
        counter = self.query_one("#find-count", Static)
        if count <= 0:
            counter.update("no matches")
        else:
            current = index + 1 if index >= 0 else 1
            counter.update(f"{current}/{count}")
