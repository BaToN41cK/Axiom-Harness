"""Top identity bar and bottom status bar.

Both are pure projections of real state: the header shows the model actually
selected and the real Ollama version, the status bar shows the state machine's
current state plus metrics reported by Ollama.
"""

from __future__ import annotations

import time

from textual.containers import Horizontal
from textual.widgets import Static

from axiom.core.state import GenerationState
from axiom.shared import formatting as fmt
from axiom.shared import theme


class HeaderBar(Horizontal):
    """``◆ AXIOM · Model · ● Ollama`` — premium identity, no noise."""

    def compose(self):
        yield Static(f"{theme.DIAMOND}  AXIOM", id="header-brand", markup=False)
        yield Static("", id="header-model", markup=False)
        yield Static("", id="header-connection", markup=False)

    def on_mount(self) -> None:
        self.set_connection(False, None)

    def update_model(self, display_name: str) -> None:
        widget = self.query_one("#header-model", Static)
        widget.update(f"{display_name}" if display_name else "")

    def set_connection(self, available: bool, version: str | None) -> None:
        widget = self.query_one("#header-connection", Static)
        glyph = theme.DOT_ACTIVE if available else theme.DOT_IDLE
        label = f"Ollama {version}" if version else ("Ollama" if available else "Ollama offline")
        widget.update(f"{glyph}  {label}")
        widget.set_class(not available, "offline")


class StatusBar(Static):
    """``Model │ Thinking │ Web ○ │ Tokens │ /help`` — live, minimal."""

    def __init__(self, **kwargs) -> None:
        super().__init__("", id="status-bar", markup=False, **kwargs)
        self._tick = 0
        self._state = GenerationState.IDLE
        self._detail: str | None = None
        self._model = ""
        self._tokens: int | None = None
        self._rate: float | None = None
        self._available = False
        self._version: str | None = None
        self._web_active = False
        self._thinking: str | None = None
        self._started: float | None = None
        self._timer = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(theme.SPINNER_INTERVAL, self._animate_status)
        self.refresh_status()

    def _animate_status(self) -> None:
        if self._state.is_busy:
            self._tick += 1
            self.refresh_status()

    # ------------------------------------------------------------------ setters

    def set_state(self, state: GenerationState, detail: str | None = None) -> None:
        was_busy = self._state.is_busy
        self._state = state
        self._detail = detail
        if state.is_busy and not was_busy:
            self._started = time.perf_counter()
        elif not state.is_busy:
            self._started = None
            self._tick = 0
        self.refresh_status()

    def set_model(self, display_name: str) -> None:
        self._model = display_name
        self.refresh_status()

    def add_tokens(self, tokens_out: int | None, rate: float | None) -> None:
        if tokens_out is not None:
            self._tokens = (self._tokens or 0) + tokens_out
        self._rate = rate
        self.refresh_status()

    def set_connection(self, available: bool, version: str | None) -> None:
        self._available = available
        self._version = version
        self.refresh_status()

    def set_web(self, active: bool) -> None:
        self._web_active = active
        self.refresh_status()

    def set_thinking(self, available: bool | None) -> None:
        if available is True:
            self._thinking = "Thinking"
        elif available is False:
            self._thinking = "No thinking"
        else:
            self._thinking = None
        self.refresh_status()

    # -------------------------------------------------------------------- render

    def refresh_status(self) -> None:
        parts: list[str] = []
        if self._model:
            parts.append(self._model)
        if self._thinking is not None:
            parts.append(self._thinking)
        elif self._state == GenerationState.THINKING and self._state.is_busy:
            parts.append(f"Thinking {fmt.spinner_frame(self._tick)}")
        web_glyph = theme.DOT_ACTIVE if self._web_active else theme.DOT_IDLE
        parts.append(f"Web {web_glyph}")
        if self._tokens is not None:
            parts.append(f"{fmt.format_tokens(self._tokens)} tok")
        elif self._state.is_busy and self._state is not GenerationState.IDLE:
            rate = fmt.format_rate(self._rate)
            if rate:
                parts.append(rate)
            state_label = fmt.status_label(self._state.value)
            elapsed = fmt.elapsed_since(self._started) if self._started is not None else 0.0
            parts.append(f"{state_label} {fmt.spinner_frame(self._tick)}  {elapsed:.1f}s")
        elif self._state is not GenerationState.IDLE:
            parts.append(fmt.status_label(self._state.value))
        parts.append("/help")
        self.update(f"  {theme.SEPARATOR}  ".join(parts))
