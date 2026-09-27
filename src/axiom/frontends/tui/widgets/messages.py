"""Message widgets — one timeline per exchange, driven strictly by core events.

Layout (AXIOM design language — minimal, premium, no fake blocks):

    YOU  ·  14:02
    └─ question text

    AXIOM
    ◌  thinking / searching / generating  (live status, always real)
    ◌ THINKING · live reasoning deltas …            (only if model sent them)
    ◉ WEB SEARCH · query …                           (only after ToolCallEvent)
      ├─ Searching: …
      ├─ Found N sources
      └─ …
    ⬢ TOOL · web_search · ok                         (only real tool events)
    ◆ ANSWER
      streamed markdown answer
    ✓ Completed · 2.4s · 118 tok · 18.6 tok/s
"""

from __future__ import annotations

import time
from typing import Any

from textual.containers import Container, Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Markdown, Static
from textual.widgets._markdown import MarkdownStream

from axiom.core.events import SourceItem
from axiom.core.state import GenerationState
from axiom.frontends.tui.widgets.reasoning import ReasoningPanel
from axiom.frontends.tui.widgets.search import WebSearchPanel
from axiom.shared import formatting as fmt
from axiom.shared import theme


class UserMessage(Container):
    """A user turn (never re-rendered once added)."""

    def __init__(self, text: str, timestamp: float | None = None) -> None:
        super().__init__(classes="message user-message")
        self.body = text
        self.timestamp = timestamp
        # Searchable projection used by the TUI Ctrl+F bar.
        self.search_text = text

    def find_text(self) -> str:
        return self.search_text

    def focus_match(self, query: str) -> None:
        """Scroll this message into view; highlighting stays native/terminal-safe."""
        self.scroll_visible()

    def compose(self):
        stamp = fmt.format_clock(self.timestamp)
        label = "YOU" + (f"  ·  {stamp}" if stamp else "")
        yield Static(label, classes="role-label")
        yield Static(self.body, classes="message-body", markup=False)


class AssistantMessage(Container):
    """An assistant turn: live status, optional reasoning, search, tool, answer."""

    def __init__(self, *, animations: bool = True, reasoning_expanded: bool = False) -> None:
        super().__init__(classes="message assistant-message")
        self._animations = animations
        self._expanded = reasoning_expanded
        self._tick = 0
        self._state = GenerationState.CONNECTING
        self._active = True
        self._detail: str | None = None
        self._duration_ms: int | None = None
        self._started: float | None = None
        self._timer = None
        self._reasoning: ReasoningPanel | None = None
        self._search: WebSearchPanel | None = None
        self._tool_line: Static | None = None
        self._tool_active = False
        self._saw_thinking = False
        self._error_box: Static | None = None
        self._stream: MarkdownStream | None = None
        self.answering = False
        self.finished = False
        self.search_text = ""

    def find_text(self) -> str:
        return self.search_text

    def focus_match(self, query: str) -> None:
        self.scroll_visible()

    def compose(self):
        yield Static("AXIOM", classes="role-label")
        yield Static("", id="assistant-status", classes="assistant-status")
        yield Static(f"{theme.ANSWER_GLYPH} ANSWER", id="answer-label", classes="block-label")
        yield Markdown("", id="answer-markdown")
        yield Horizontal(id="code-actions")

    def on_mount(self) -> None:
        self.query_one("#answer-label", Static).display = False
        self.query_one("#answer-markdown", Markdown).display = False
        self.query_one("#code-actions", Horizontal).display = False
        if self._animations:
            self._timer = self.set_interval(theme.SPINNER_INTERVAL, self._animate_status)
        self._refresh_status()

    # ------------------------------------------------------------------ status

    def set_state(self, state: GenerationState, *, detail: str | None = None) -> None:
        was_busy = self._state.is_busy
        self._state = state
        self._active = state.is_busy
        if state == GenerationState.THINKING:
            self._saw_thinking = True
        if detail is not None:
            self._detail = detail
        # Start the honest wall-clock timer on the first busy transition; keep it
        # running across phases and leave it set once finished (the ✓ footer uses
        # the real duration_ms reported by the core, not this value).
        if state.is_busy and not was_busy and self._started is None:
            self._started = time.perf_counter()
        if self._reasoning is not None:
            if state == GenerationState.THINKING:
                self._reasoning.set_state(state, active=True)
            elif self._reasoning.active:
                # THINKING -> next phase: the reasoning really ended. Fold the
                # panel away and leave the ✓ summary line (spec §5/§45).
                if state in (GenerationState.ERROR, GenerationState.CANCELLED):
                    self._reasoning.finish(state)
                else:
                    self._reasoning.complete()
            else:
                self._reasoning.set_state(state, active=state.is_busy)
        self._refresh_status()

    def _animate_status(self) -> None:
        if not self._active:
            return
        self._tick += 1
        self._refresh_status()

    def _refresh_status(self) -> None:
        try:
            widget = self.query_one("#assistant-status", Static)
        except NoMatches:  # pragma: no cover - not composed yet
            return
        if self.finished and self._state == GenerationState.COMPLETED and self.answering:
            widget.display = False
            return
        widget.display = True
        if self._state == GenerationState.ERROR and not self._active:
            widget.update(f"{theme.CROSS}  Failed")
            return
        if self._active:
            glyph = fmt.spinner_frame(self._tick)
        elif self._state == GenerationState.COMPLETED:
            glyph = theme.TICK
        elif self._state == GenerationState.CANCELLED:
            glyph = theme.INTERRUPTED
        elif self._state == GenerationState.ERROR:
            glyph = theme.CROSS
        else:
            glyph = theme.RING
        if self._state == GenerationState.THINKING:
            if self._reasoning is not None:
                # The THINKING panel already carries this phase; rendering the
                # status line too would show the user two "Thinking" rows.
                widget.display = False
                return
            elapsed = fmt.elapsed_since(self._started) if self._started is not None else 0.0
            label = f"Thinking  {elapsed:.1f}s" if self._started is not None else "Thinking"
            widget.update(f"{glyph}  {label}")
            return
        widget.update(
            fmt.status_line(
                self._state.value,
                tick=self._tick,
                duration_ms=self._duration_ms,
                detail=self._detail,
                active=self._active,
                elapsed=fmt.elapsed_since(self._started) if self._started is not None and self._active else None,
            )
        )

    def finish(
        self,
        state: GenerationState,
        *,
        duration_ms: int | None = None,
        tokens_out: int | None = None,
        tokens_per_second: float | None = None,
    ) -> None:
        self._state = state
        self._active = False
        self._duration_ms = duration_ms
        self.finished = True
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._reasoning is not None:
            self._reasoning.finish(state, duration_ms)
        else:
            # No reasoning deltas arrived (or ANSWER streamed directly): say so
            # exactly once — never invent fake thinking lines.
            self._collapse_pending_thinking(state)
        if self._search is not None:
            self._search.finish(cancelled=state == GenerationState.CANCELLED)
        if self._tool_line is not None and self._tool_active:
            self.tool_finished("tool", False, "interrupted")
        self._refresh_status()
        summary = fmt.completion_summary(
            state,
            duration_ms=duration_ms,
            tokens_out=tokens_out,
            rate=tokens_per_second,
        )
        if summary:
            self.mount(Static(summary, classes="metrics-footer", markup=False))

    def _collapse_pending_thinking(self, state: GenerationState) -> None:
        """Render the honest 'no reasoning' note when the model sent none."""
        if self.answering or state != GenerationState.COMPLETED:
            return
        # Only show when a thinking phase was actually observed; otherwise the
        # status line already told the story (fast non-reasoning models).
        if not self._saw_thinking:
            return
        self.mount(
            Static(
                f"{theme.RING}  Thinking unavailable  ·  model did not expose reasoning",
                classes="message-note",
                markup=False,
            )
        )

    # --------------------------------------------------------------- reasoning

    def _anchor(self):
        """Mount point keeping chronological order: reasoning → search/tool → answer."""
        try:
            return self.query_one("#answer-label", Static)
        except Exception:  # pragma: no cover - compose in progress
            return None

    def add_reasoning(self, text: str) -> None:
        self.search_text += text
        if self._reasoning is None:
            self._reasoning = ReasoningPanel(expanded=self._expanded, animations=self._animations)
            anchor = self._anchor()
            if anchor is not None:
                self.mount(self._reasoning, before=anchor)
            else:
                self.mount(self._reasoning)
            self._reasoning.set_state(self._state, active=self._active)
            # The panel now represents the THINKING phase; make sure the
            # status line never duplicates it.
            self._refresh_status()
        self._reasoning.append(text)

    @property
    def reasoning_panel(self) -> ReasoningPanel | None:
        return self._reasoning

    # ------------------------------------------------------------------ search

    def _ensure_search(self) -> WebSearchPanel:
        if self._search is None:
            self._search = WebSearchPanel(animations=self._animations)
            anchor = self._anchor()
            if anchor is not None:
                self.mount(self._search, before=anchor)
            else:
                self.mount(self._search)
        return self._search

    # -------------------------------------------------------------------- tool

    def tool_started(self, name: str, arguments: dict[str, Any] | None = None) -> None:
        """Render a real tool invocation (chronological timeline block)."""
        if self._tool_line is None:
            self._tool_line = Static("", classes="tool-line", markup=False)
            anchor = self._anchor()
            if anchor is not None:
                self.mount(self._tool_line, before=anchor)
            else:
                self.mount(self._tool_line)
        self._tool_active = True
        query = ""
        if arguments:
            for key in ("query", "url", "input", "text"):
                value = arguments.get(key)
                if isinstance(value, str) and value.strip():
                    query = fmt.truncate(value.strip(), 72)
                    break
        suffix = f"  ·  {query}" if query else ""
        self._tool_line.update(f"{theme.TOOL_GLYPH}  TOOL  ·  {name}{suffix}")

    def tool_finished(self, name: str, ok: bool, detail: str = "") -> None:
        if self._tool_line is None:
            self.tool_started(name)
            if self._tool_line is None:  # pragma: no cover - defensive
                return
        self._tool_active = False
        glyph = theme.TICK if ok else theme.CROSS
        suffix = f"  ·  {detail}" if detail else ""
        self._tool_line.update(f"{glyph}  TOOL  ·  {name}{suffix}")
        if name == "web_search" and ok and self._search is None:
            # Model tool ran fine but SearchResultEvent not seen yet: keep the
            # honest mark, the search panel will extend it when results land.
            pass

    def search_started(self, query: str) -> None:
        self._ensure_search().search_started(query)

    def search_finished(self, query: str, sources: list[SourceItem]) -> None:
        self._ensure_search().search_finished(query, sources)

    def search_failed(self, message: str) -> None:
        self._ensure_search().search_failed(message)

    def read_started(self, url: str) -> None:
        self._ensure_search().read_started(url)

    def read_finished(self, url: str, ok: bool) -> None:
        self._ensure_search().read_finished(url, ok)

    # ------------------------------------------------------------------ answer

    def stream(self) -> MarkdownStream:
        if self._stream is None:
            markdown = self.query_one("#answer-markdown", Markdown)
            self._stream = Markdown.get_stream(markdown)
        return self._stream

    async def add_answer(self, text: str) -> None:
        if not text:
            return
        self.search_text += text
        if not self.answering:
            self.answering = True
            self.query_one("#answer-label", Static).display = True
            self.query_one("#answer-markdown", Markdown).display = True
        await self.stream().write(text)

    async def close_stream(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
            self._stream = None

    def _show_code_actions(self) -> None:
        """Show copy-to-clipboard and run-code buttons after answer is ready."""
        actions = self.query_one("#code-actions", Horizontal)
        if actions.display:
            return
        markdown = self.query_one("#answer-markdown", Markdown)
        content = markdown.renderable if hasattr(markdown, "renderable") else ""
        if not content:
            return
        actions.remove_all()
        # Short label so it stays minimal
        from textual.widgets import Static as ActionStatic
        copy_btn = ActionStatic("📋 Copy", classes="code-action", markup=False)
        run_btn = ActionStatic("▶ Run", classes="code-action", markup=False)
        actions.mount_all([copy_btn, run_btn])
        actions.display = True

    # ----------------------------------------------------------- errors / notes

    def add_error(self, message: str, hint: str | None = None) -> None:
        text = f"{theme.CROSS} {message}"
        if hint:
            text += f"\n   {hint}"
        self._error_box = Static(text, classes="error-box", markup=False)
        self.mount(self._error_box)

    def add_note(self, text: str) -> None:
        self.mount(Static(text, classes="message-note", markup=False))


class ChatView(VerticalScroll):
    """The conversation area: auto-follows new output unless the user scrolls up."""

    #: Scrolling chat log; keyboard stays in the prompt (mouse/End scroll).
    can_focus = False

    def __init__(self, **kwargs) -> None:
        super().__init__(id="chat-view", **kwargs)
        self._follow = True

    def compose(self):
        yield Static(
            "↓ New output — press End to follow",
            id="follow-hint",
            markup=False,
        )

    def on_mount(self) -> None:
        self.query_one("#follow-hint", Static).display = False

    @property
    def following(self) -> bool:
        return self._follow

    def watch_scroll_y(self, old_value: float | None, new_value: float) -> None:
        """Follow the tail while the user stays at the bottom."""
        if self.max_scroll_y <= 0 or new_value >= self.max_scroll_y - 2:
            self._follow = True
        elif old_value is not None and new_value < old_value:
            self._follow = False
        self._refresh_hint()

    def _refresh_hint(self) -> None:
        try:
            hint = self.query_one("#follow-hint", Static)
        except NoMatches:  # pragma: no cover
            return
        hint.display = not self._follow

    def add(self, widget) -> None:
        self.mount(widget)
        self.follow()

    def follow(self) -> None:
        if self._follow:
            self.scroll_end(animate=False)

    def jump_to_end(self) -> None:
        self._follow = True
        self.scroll_end(animate=False)
        self._refresh_hint()

    def find_matches(self, query: str) -> list[UserMessage | AssistantMessage]:
        """Only the mounted transcript; no history from other conversations."""
        needle = query.strip().casefold()
        if not needle:
            return []
        return [child for child in self.children
                if isinstance(child, (UserMessage, AssistantMessage))
                and needle in child.find_text().casefold()]

    def focus_match(self, widget: UserMessage | AssistantMessage) -> None:
        """Show one match without changing the user's search query."""
        self._follow = False
        widget.scroll_visible()
        self._refresh_hint()

    def clear_messages(self) -> None:
        for child in list(self.children):
            if isinstance(child, (UserMessage, AssistantMessage)):
                child.remove()
        self._follow = True
        self.scroll_home(animate=False)
