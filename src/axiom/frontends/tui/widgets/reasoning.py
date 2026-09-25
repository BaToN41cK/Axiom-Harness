"""Streaming text blocks and the collapsible reasoning panel.

Nothing here invents content: ``ReasoningPanel`` only exists when the model
really sent reasoning, and its title reflects the real state reported by the
core's state machine.
"""

from __future__ import annotations

import time

from textual.containers import Container
from textual.widgets import Collapsible, Static

from axiom.core.state import GenerationState
from axiom.shared import formatting as fmt
from axiom.shared import theme

#: How often buffered deltas are pushed to the widget (keeps the UI smooth).
FLUSH_INTERVAL = 0.08


class StreamText(Static):
    """A Static that accepts streaming deltas without re-rendering per chunk."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("markup", False)
        super().__init__("", *args, **kwargs)
        self._buffer = ""
        self._rendered = ""

    @property
    def text_content(self) -> str:
        return self._buffer

    def on_mount(self) -> None:
        self.set_interval(FLUSH_INTERVAL, self._flush)

    def append(self, text: str) -> None:
        self._buffer += text

    def set_text(self, text: str) -> None:
        self._buffer = text

    def _flush(self) -> None:
        if self._buffer == self._rendered:
            return
        self._rendered = self._buffer
        self.update(self._buffer)


class ReasoningPanel(Container):
    """Collapsible block holding the model's real reasoning."""

    def __init__(self, *, expanded: bool = False, animations: bool = True) -> None:
        super().__init__(classes="reasoning-panel")
        self._expanded = expanded
        self._animations = animations
        self._tick = 0
        self._state = GenerationState.THINKING.value
        self._active = True
        self._duration_ms: int | None = None
        self._timer = None
        self._pending: list[str] = []
        self._started: float | None = None

    def compose(self):
        collapsed = not self._expanded
        with Collapsible(
            title=self._title(),
            collapsed=collapsed,
            collapsed_symbol="▸",
            expanded_symbol="▾",
            id="reasoning-collapsible",
        ):
            yield Static(
                f"{theme.TREE_PIPE}  live model reasoning — plain text, not formatted",
                classes="phase-note",
                markup=False,
            )
            yield StreamText(id="reasoning-text")

    def on_mount(self) -> None:
        if self._animations:
            self._timer = self.set_interval(theme.SPINNER_INTERVAL, self._animate_title)
        if self._pending:
            # deltas that arrived before the DOM existed (streaming is fast)
            self.query_one("#reasoning-text", StreamText).append("".join(self._pending))
            self._pending.clear()

    # ------------------------------------------------------------------ public

    def append(self, text: str) -> None:
        if self._started is None:
            self._started = time.perf_counter()
        try:
            stream = self.query_one("#reasoning-text", StreamText)
        except Exception:  # pragma: no cover - composed lazily
            self._pending.append(text)
            return
        stream.append(text)

    @property
    def active(self) -> bool:
        """Whether reasoning is still streaming."""
        return self._active

    def set_state(self, state: GenerationState, *, active: bool) -> None:
        """Track the real state so the title never claims more than it knows."""
        if not self._active:
            # Reasoning already finished; only a real interruption re-titles
            # the (collapsed) summary line.
            if state in (GenerationState.CANCELLED, GenerationState.ERROR):
                self._state = state.value
                self._refresh_title()
            return
        self._state = state.value
        self._active = active
        self._refresh_title()

    def complete(self) -> None:
        """Reasoning really ended (THINKING -> next phase): ✓ + collapse."""
        self.finish(GenerationState.COMPLETED)

    def finish(self, state: GenerationState, duration_ms: int | None = None) -> None:
        """Finalize with the real terminal state and fold the live text away."""
        if self._active:
            if duration_ms is None and self._started is not None:
                duration_ms = int((time.perf_counter() - self._started) * 1000)
            self._duration_ms = duration_ms
            self._state = state.value
            self._active = False
        elif state in (GenerationState.CANCELLED, GenerationState.ERROR):
            self._state = state.value
        self._refresh_title()
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._collapse()

    def toggle(self) -> None:
        collapsible = self.query_one("#reasoning-collapsible", Collapsible)
        collapsible.collapsed = not collapsible.collapsed

    # ----------------------------------------------------------------- private

    def _collapse(self) -> None:
        """Fold the live reasoning away; the ✓ title summary stays."""
        try:
            self.query_one("#reasoning-collapsible", Collapsible).collapsed = True
        except Exception:  # pragma: no cover - widget not composed yet
            pass

    def _animate_title(self) -> None:
        if not self._active:
            return
        self._tick += 1
        self._refresh_title()

    def _title(self) -> str:
        if self._active:
            glyph = fmt.spinner_frame(self._tick)
            elapsed = fmt.elapsed_since(self._started) if self._started is not None else 0.0
            return f"{glyph}  {theme.PHASE_THINKING}  {elapsed:.1f}s"
        if self._state == GenerationState.ERROR.value:
            return f"{theme.CROSS}  {theme.PHASE_THINKING}"
        if self._state == GenerationState.CANCELLED.value:
            return f"{theme.INTERRUPTED}  {theme.PHASE_THINKING}"
        duration = fmt.format_duration_ms(self._duration_ms)
        suffix = f"  ·  {duration}" if duration else ""
        return f"{theme.TICK}  {theme.PHASE_THINKING}{suffix}"

    def _refresh_title(self) -> None:
        try:
            collapsible = self.query_one("#reasoning-collapsible", Collapsible)
        except Exception:  # pragma: no cover - widget not composed yet
            return
        title = self._title()
        if title != collapsible.title:
            collapsible.title = title
