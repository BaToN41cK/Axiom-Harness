"""Modal panels — models, history, settings, help and real system status.

Every panel is a *projection* of core state: model rows come from
:class:`~axiom.core.models.ModelRegistry`, history rows from the real
:class:`~axiom.core.history.HistoryStore`, and the status panel prints the live
Ollama URL, the model that is actually selected and the capabilities Ollama
reported (``unknown`` when it reported nothing — never an optimistic guess).

All panels share one shape: a titled frame, an arrow-navigable body and a
result delivered back to :mod:`axiom.frontends.tui.app` through ``dismiss``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    OptionList,
    Static,
    Switch,
    TextArea,
)
from textual.widgets.option_list import Option

from axiom.core.config import Config
from axiom.core.history import Conversation
from axiom.core.models import ModelInfo
from axiom.shared import formatting as fmt
from axiom.shared import theme

#: Capabilities Ollama may report; anything else is shown as ``unknown``.
CAPABILITIES = ("completion", "tools", "thinking", "vision")


def capability_state(model: ModelInfo, capability: str) -> str:
    """``supported`` / ``unsupported`` / ``unknown`` — as really reported."""
    state = model.supports(capability)
    if state is True:
        return "supported"
    if state is False:
        return "unsupported"
    return "unknown"


def capability_glyph(model: ModelInfo, capability: str) -> str:
    state = model.supports(capability)
    if state is True:
        return theme.TICK
    if state is False:
        return theme.CROSS
    return theme.BULLET


def capability_text(model: ModelInfo, separator: str = "  ") -> str:
    """Compact capability line — never claims more than Ollama reported."""
    return separator.join(f"{capability_glyph(model, c)} {c}" for c in CAPABILITIES)


def model_option(model: ModelInfo, current: str | None) -> Option:
    """One model row: display name, size, quantization and capabilities."""
    marker = theme.ARROW if model.name == current else " "
    size = f"{model.size_gb:.2f} GB" if model.size else "—"
    quant = model.quantization or "—"
    params = model.parameter_size or "—"
    prompt = (
        f"{marker} {model.display_name}  ·  {params}  ·  {size}  ·  {quant}\n"
        f"    {model.name}   {capability_text(model)}"
    )
    return Option(prompt, id=model.name)


class PanelScreen(ModalScreen):
    """Base modal panel: titled frame, scrolling body, ``esc`` to close."""

    BINDINGS = [
        Binding("escape", "close_panel", "Close", show=True),
        Binding("f2", "close_panel", "Close", show=False),
    ]

    #: Frame title (overridden by subclasses).
    title_text = "PANEL"

    def body(self) -> ComposeResult:
        """Yield the panel contents (subclasses must implement this)."""
        raise NotImplementedError

    def keys_hint(self) -> str:
        """Right-hand side of the frame border."""
        return "esc  close"

    def subtitle_lines(self) -> list[str]:
        """Optional real facts printed under the frame title."""
        return []

    def compose(self) -> ComposeResult:
        frame = Vertical(classes="panel")
        frame.border_title = self.title_text
        frame.border_subtitle = self.keys_hint()
        with frame:
            subtitle = "\n".join(line for line in self.subtitle_lines() if line)
            if subtitle:
                yield Static(subtitle, classes="panel-subtitle", markup=False)
            with VerticalScroll(id="panel-body"):
                yield from self.body()

    def action_close_panel(self) -> None:
        self.dismiss(None)


class ModelPanel(PanelScreen):
    """``/models`` — the real Ollama model list; Enter switches the model."""

    title_text = "MODELS"

    def __init__(
        self,
        models: list[ModelInfo],
        current: str | None,
        *,
        refresh: Callable[[], Awaitable[list[ModelInfo]]] | None = None,
    ) -> None:
        super().__init__()
        self._models = list(models)
        self._current = current
        self._refresh_callback = refresh

    BINDINGS = [Binding("r", "refresh_models", "Refresh", show=False)]

    async def action_refresh_models(self) -> None:
        """Re-read the real model list from Ollama."""
        if self._refresh_callback is None:
            return
        try:
            self._models = list(await self._refresh_callback())
        except Exception:
            return
        option_list = self.query_one("#model-list", OptionList)
        option_list.clear_options()
        for model in self._models:
            option_list.add_option(model_option(model, self._current))
        for index, model in enumerate(self._models):
            if model.name == self._current:
                option_list.highlighted = index
                break

    def keys_hint(self) -> str:
        hint = "↑↓ navigate   ·   enter switch   ·   esc close"
        if self._refresh_callback is not None:
            hint = "r refresh   ·   " + hint
        return hint

    def subtitle_lines(self) -> list[str]:
        if not self._models:
            return ["No models are installed in Ollama."]
        marker = "selected" if self._current else "none selected"
        return [f"{len(self._models)} model(s) reported by Ollama   ·   {marker}"]

    def body(self) -> ComposeResult:
        options = [model_option(model, self._current) for model in self._models]
        option_list = OptionList(*options, id="model-list")
        yield option_list

    def on_mount(self) -> None:
        option_list = self.query_one("#model-list", OptionList)
        for index, model in enumerate(self._models):
            if model.name == self._current:
                option_list.highlighted = index
                break
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(str(event.option.id))


class HelpPanel(PanelScreen):
    """``/help`` — the command reference plus navigation basics."""

    title_text = "HELP"

    def __init__(self, commands) -> None:
        super().__init__()
        self._commands = list(commands)

    def keys_hint(self) -> str:
        return "↑↓ scroll   ·   esc close"

    def subtitle_lines(self) -> list[str]:
        return [
            "Type / in the prompt to open the command menu — Tab or Enter completes,",
            "↑↓ navigate, Esc dismisses. Sources and titles are clickable with the mouse.",
        ]

    def body(self) -> ComposeResult:
        widest = max((len(command.usage) for command in self._commands), default=8)
        yield OptionList(
            *[
                Option(f"  {command.usage.ljust(widest)}  {command.description}", disabled=True)
                for command in self._commands
            ],
            id="help-list",
        )
        yield Static(
            "\n".join(
                [
                    "Enter          send message (in the prompt)",
                    "Ctrl+J         newline inside the prompt",
                    "Ctrl+C         stop the running generation",
                    "Ctrl+Q         quit AXIOM",
                    "Mouse wheel    scroll chat, reasoning and sources",
                    "Click Stop     cancel the current generation",
                ]
            ),
            classes="panel-note",
            markup=False,
        )


class HistoryPanel(PanelScreen):
    """``/history`` — saved conversations; Enter opens, ``d`` deletes."""

    title_text = "HISTORY"
    BINDINGS = [Binding("d", "delete_conversation", "Delete", show=False)]

    def __init__(
        self,
        conversations: list[Conversation],
        *,
        on_delete: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__()
        self._conversations = list(conversations)
        self._on_delete = on_delete

    def keys_hint(self) -> str:
        return "↑↓ navigate   ·   enter open   ·   d delete   ·   esc close"

    def subtitle_lines(self) -> list[str]:
        if not self._conversations:
            return ["No saved conversations yet."]
        return [f"{len(self._conversations)} saved conversation(s)"]

    def body(self) -> ComposeResult:
        yield OptionList(id="history-list")

    def on_mount(self) -> None:
        self._rebuild()
        option_list = self.query_one("#history-list", OptionList)
        if option_list.option_count:
            option_list.focus()

    def _rebuild(self) -> None:
        option_list = self.query_one("#history-list", OptionList)
        option_list.clear_options()
        bucket: str | None = None
        for conversation in self._conversations:
            current_bucket = fmt.history_bucket(conversation.updated_at)
            if current_bucket != bucket:
                bucket = current_bucket
                option_list.add_option(Option(f" {bucket.upper()}", disabled=True))
            stamp = fmt.format_clock(conversation.updated_at)
            title = fmt.one_line(conversation.title or "Untitled", 46)
            option_list.add_option(Option(f"   {stamp}  {title}", id=conversation.id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            event.stop()
            self.dismiss(str(event.option.id))

    def action_delete_conversation(self) -> None:
        option_list = self.query_one("#history-list", OptionList)
        if option_list.highlighted is None:
            return
        option = option_list.get_option_at_index(option_list.highlighted)
        if not option.id or option.disabled:
            return
        conversation_id = str(option.id)
        deleted = self._on_delete(conversation_id) if self._on_delete is not None else False
        if deleted:
            self._conversations = [
                conversation for conversation in self._conversations if conversation.id != conversation_id
            ]
            self._rebuild()


_BOOL_SETTINGS: tuple[tuple[str, str, str], ...] = (
    ("switch-search", "web_search_enabled", "Web search"),
    ("switch-reasoning", "show_reasoning", "Show reasoning (when provided)"),
    ("switch-expanded", "reasoning_expanded", "Reasoning starts expanded"),
    ("switch-animations", "animations", "Animations"),
    ("switch-history", "save_history", "Save conversation history"),
)

_THINK_OPTIONS: tuple[tuple[str, str], ...] = (
    ("think-auto", "Thinking: auto (follow model capability)"),
    ("think-on", "Thinking: on (always request)"),
    ("think-off", "Thinking: off (never request)"),
)


class SettingsPanel(PanelScreen):
    """``/settings`` — live edits of the real configuration, saved on change."""

    title_text = "SETTINGS"

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config

    def keys_hint(self) -> str:
        return "↑↓ navigate   ·   enter save   ·   esc close"

    def subtitle_lines(self) -> list[str]:
        direct = self._config.system_prompt or "(model default)"
        if self._config.think is None:
            think = "auto"
        elif self._config.think:
            think = "on"
        else:
            think = "off"
        web = "on" if self._config.web_search_enabled else "off"
        return [
            f"Model {self._config.model or '(auto)'}  ·  {self._config.ollama_url}",
            f"Web {web}  ·  Thinking {think}  ·  Theme {self._config.theme}",
            f"Prompt: {direct[:64]}",
        ]

    def body(self) -> ComposeResult:
        for switch_id, field_name, label in _BOOL_SETTINGS:
            with Horizontal(classes="settings-row"):
                yield Static(label, classes="settings-label", markup=False)
                yield Switch(getattr(self._config, field_name), id=switch_id)
        yield Static("Thinking mode (Ollama think flag)", classes="settings-label", markup=False)
        yield OptionList(
            *[Option(label, id=option_id) for option_id, label in _THINK_OPTIONS],
            id="think-list",
        )
        with Horizontal(classes="settings-row"):
            yield Static("Ollama URL", classes="settings-label", markup=False)
            yield Input(value=self._config.ollama_url, id="ollama-input")
        with Horizontal(classes="settings-row"):
            yield Static("Model (empty = auto)", classes="settings-label", markup=False)
            yield Input(
                value="" if not self._config.model else self._config.model,
                placeholder="qwen3:8b",
                id="model-input",
            )
        with Horizontal(classes="settings-row"):
            yield Static("Temperature", classes="settings-label", markup=False)
            yield Input(
                value="" if self._config.temperature is None else str(self._config.temperature),
                placeholder="auto",
                id="temperature-input",
            )
        yield Static("System prompt", classes="settings-label", markup=False)
        yield TextArea(self._config.system_prompt or "", id="system-prompt-input")
        yield Button("Save", id="save-settings", variant="default")

    def on_mount(self) -> None:
        current = (
            "think-auto" if self._config.think is None else ("think-on" if self._config.think else "think-off")
        )
        option_list = self.query_one("#think-list", OptionList)
        for index, option in enumerate(option_list._options):
            if option.id == current:
                option_list.highlighted = index
                break

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = str(event.option.id or "")
        if option_id == "think-auto":
            self._config.think = None
        elif option_id == "think-on":
            self._config.think = True
        elif option_id == "think-off":
            self._config.think = False
        else:
            return
        self._save()
        if self.app is not None:
            self.app.notify("Thinking mode saved.", title="Settings", timeout=3)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        for switch_id, field_name, _ in _BOOL_SETTINGS:
            if event.switch.id == switch_id:
                setattr(self._config, field_name, event.value)
                self._save()
                return

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "temperature-input":
            self._apply_temperature(event.input.value)
        elif event.input.id == "model-input":
            self._config.model = event.input.value.strip() or None
            self._save()
        elif event.input.id == "ollama-input":
            self._config.ollama_url = event.input.value.strip() or self._config.ollama_url
            self._save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save-settings":
            return
        self._apply_temperature(self.query_one("#temperature-input", Input).value)
        self._config.model = self.query_one("#model-input", Input).value.strip() or None
        self._config.ollama_url = self.query_one("#ollama-input", Input).value.strip() or self._config.ollama_url
        self._config.system_prompt = self.query_one("#system-prompt-input", TextArea).text.strip() or None
        self._save()
        if self.app is not None:
            self.app.notify("Settings saved.", title="Settings", timeout=3)

    def _apply_temperature(self, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            self._config.temperature = None
            self._save()
            return
        try:
            value = float(raw)
        except ValueError:
            if self.app is not None:
                self.app.notify("Temperature must be a number or empty.", severity="warning", timeout=4)
            return
        if not 0.0 <= value <= 2.0:
            if self.app is not None:
                self.app.notify("Temperature must be between 0 and 2.", severity="warning", timeout=4)
            return
        self._config.temperature = value
        self._save()

    def _save(self) -> None:
        try:
            self._config.save()
        except OSError:
            pass  # persistence must never break the panel


class ProfilePanel(PanelScreen):
    """``/profiles`` — system prompt profile selector.

    Shows all profiles with a marker for the currently active one.
    Arrow keys to navigate, Enter to select, Escape to close.
    """

    title_text = "PROFILES"

    def __init__(
        self,
        profiles: dict[str, str],
        active: str,
        *,
        on_select: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__()
        self._profiles = profiles
        self._active = active
        self._on_select = on_select

    def keys_hint(self) -> str:
        past = [f"✓ {self._active}"]
        return " ↑↓  select  ·  " + "  ".join(past) + "  ·  esc  close"

    def subtitle_lines(self) -> list[str]:
        return [f"Active: {theme.ARROW} {self._active}"]

    def body(self) -> ComposeResult:
        yield Static(f"Active profile: {self._active}", id="profile-current", markup=False)
        with OptionList(id="profile-list"):
            for name, prompt in self._profiles.items():
                glyph = theme.ARROW if name == self._active else " "
                label = f"{glyph} {name}"
                # Truncate prompt preview to first line
                preview = prompt.split("\n")[0][:80]
                if len(prompt.split("\n")[0]) > 80:
                    preview += "…"
                rows = Option(f"{label}\n    {preview}", id=name)
                yield rows

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        name = str(event.option.id) if event.option.id else ""
        if name and name in self._profiles:
            self.dismiss(name)
        else:
            if self.app is not None:
                self.app.notify(f"Unknown profile: {name}", severity="warning", timeout=3)


class StatusPanel(PanelScreen):
    """``/status`` — real system status: server, model, capabilities, metrics."""

    title_text = "STATUS"

    def __init__(
        self,
        *,
        ollama_url: str,
        version: str | None,
        model: ModelInfo | None,
        metrics: dict,
        search_provider: str = "Web",
    ) -> None:
        super().__init__()
        self._ollama_url = ollama_url
        self._version = version
        self._model = model
        self._metrics = dict(metrics)
        self._search_provider = search_provider or "Web"

    def keys_hint(self) -> str:
        return "esc close"

    def subtitle_lines(self) -> list[str]:
        server = self._ollama_url + (f"   ·   version {self._version}" if self._version else "")
        return [server]

    def body(self) -> ComposeResult:
        connected = "connected" if self._version else "unknown (splash probe)"
        thinking = self._model.supports("thinking") if self._model else None
        thinking_text = (
            "available" if thinking is True else ("unavailable" if thinking is False else "unknown")
        )
        rows: list[tuple[str, str]] = [
            ("Ollama", f"{theme.DOT_ACTIVE} {connected}" if self._version else f"{theme.DOT_IDLE} {connected}"),
            ("Endpoint", self._ollama_url),
            ("Model", self._model.name if self._model else "none"),
            ("Streaming", "on (NDJSON deltas)"),
            ("Reasoning", thinking_text),
            ("Web Search", f"available ({self._search_provider}, key-less)"),
        ]
        if self._model is not None:
            rows.append(("Label", self._model.display_name))
            rows.append(("Capabilities", capability_text(self._model)))
            rows.append(("Parameters", self._model.parameter_size or "unknown"))
            rows.append(("Quantization", self._model.quantization or "unknown"))
            rows.append(("Size", f"{self._model.size_gb:.2f} GB" if self._model.size else "unknown"))
        metrics = self._metrics
        duration = fmt.format_duration_ms(metrics.get("duration_ms"))
        if duration:
            rows.append(("Last generation", duration))
        tokens_in = metrics.get("tokens_in")
        if tokens_in is not None:
            rows.append(("Tokens in", fmt.format_tokens(tokens_in)))
        tokens_out = metrics.get("tokens_out")
        if tokens_out is not None:
            rows.append(("Tokens out", fmt.format_tokens(tokens_out)))
        rate = fmt.format_rate(metrics.get("tokens_per_second") or None)
        if rate:
            rows.append(("Throughput", rate))
        with Vertical():
            for key, value in rows:
                with Horizontal(classes="status-row"):
                    yield Static(key, classes="status-key", markup=False)
                    yield Static(value, classes="status-value", markup=False)


class BenchmarkPanel(PanelScreen):
    """``/benchmark`` — real cold/warm performance report (W2.8)."""

    title_text = "BENCHMARK"
    BINDINGS = [
        *PanelScreen.BINDINGS,
        Binding("r", "rerun", "Run", show=False),
    ]

    def __init__(self, report: dict | None = None, *, running: bool = False) -> None:
        super().__init__()
        self._report = dict(report or {})
        self._running = running

    def keys_hint(self) -> str:
        return "r run again   ·   esc close"

    def subtitle_lines(self) -> list[str]:
        if self._running:
            return ["Running real scenarios — waiting for measured model events…"]
        runs = self._report.get("runs") or []
        return [f"{len(runs)} measured run(s)   ·   no fabricated values"]

    def body(self) -> ComposeResult:
        if self._running:
            yield Static("Benchmark is running…", markup=False)
            return
        runs = self._report.get("runs") or []
        if not runs:
            yield Static("No benchmark report yet. Press r to run.", markup=False)
            return
        for run in runs:
            status = "OK" if run.get("ok") else "FAILED"
            line = (
                f"{run.get('scenario', '?')}  ·  {run.get('phase', '?')}  ·  "
                f"#{run.get('repetition', 0)}  ·  {status}  ·  "
                f"{run.get('duration_ms', '—')} ms"
            )
            if run.get("error"):
                line += f"\n    {run['error']}"
            metrics = run.get("metrics") or {}
            if metrics:
                line += (
                    f"\n    ttft={metrics.get('ttft_ms', '—')} ms"
                    f"  gen={metrics.get('generation_ms', '—')} ms"
                    f"  tok/s={metrics.get('tokens_per_second', '—')}"
                )
            yield Static(line, classes="benchmark-row", markup=False)
        overall = (self._report.get("summary") or {}).get("overall") or {}
        if overall:
            yield Static("\nOverall", classes="settings-label", markup=False)
            for field in ("ttft_ms", "generation_ms", "tokens_per_second"):
                value = overall.get(field) or {}
                yield Static(
                    f"{field}: median={value.get('median', '—')}"
                    f"  mean={value.get('mean', '—')}  count={overall.get('count', 0)}",
                    markup=False,
                )

    async def action_rerun(self) -> None:
        self.dismiss("rerun")


class SearchTestPanel(PanelScreen):
    """``/searchtest`` — a real search connectivity probe (W1.2).

    Shows the engine that answered, the measured latency, the result count and
    — on failure — the real error, never a fabricated "Online" state.
    """

    title_text = "SEARCH TEST"

    def __init__(self, report: dict, query: str = "") -> None:
        super().__init__()
        self._report = dict(report or {})
        self._query = query

    def keys_hint(self) -> str:
        return "esc close"

    def subtitle_lines(self) -> list[str]:
        line = f"Query: {self._query or '(default)'}"
        return [line]

    def body(self) -> ComposeResult:
        ok = bool(self._report.get("ok"))
        provider = self._report.get("provider") or "—"
        latency = self._report.get("latency_ms")
        count = self._report.get("result_count") or 0
        status = f"{theme.DOT_ACTIVE} Online" if ok else f"{theme.DOT_IDLE} Offline"
        rows: list[tuple[str, str]] = [
            ("Status", status),
            ("Engine", provider),
            ("Latency", f"{latency} ms" if latency is not None else "—"),
            ("Results", str(count)),
        ]
        error = self._report.get("error")
        if error:
            rows.append(("Error", error))
        hint = self._report.get("hint")
        if hint:
            rows.append(("Hint", hint))
        with Vertical():
            for key, value in rows:
                with Horizontal(classes="status-row"):
                    yield Static(key, classes="status-key", markup=False)
                    yield Static(value, classes="status-value", markup=False)
        results = self._report.get("results") or []
        if results:
            yield Static("\nTop results", classes="settings-label", markup=False)
            for index, item in enumerate(results[:5], start=1):
                title = str(item.get("title") or "(no title)")
                url = str(item.get("url") or "")
                yield Static(f"{index}. {title}\n   {url}", markup=False)


class OrchestrationPanel(PanelScreen):
    """Live ``/orchestrate`` projection of the real trajectory (W2.8)."""

    title_text = "ORCHESTRATION"
    BINDINGS = [
        *PanelScreen.BINDINGS,
        Binding("r", "refresh_run", "Refresh", show=False),
        Binding("s", "stop_run", "Stop", show=True),
    ]

    def __init__(self, trajectory, *, baseline: int = 0, on_stop: Callable[[], bool] | None = None) -> None:
        super().__init__()
        self._trajectory = trajectory
        self._on_stop = on_stop
        self._baseline = max(0, baseline)
        self._poll_task: asyncio.Task | None = None
        self._events: list[dict] = []
        self._running = True

    def keys_hint(self) -> str:
        return "r refresh   ·   s stop   ·   esc close"

    def body(self) -> ComposeResult:
        yield Static("", id="orchestration-summary", classes="panel-subtitle", markup=False)
        yield Static("", id="orchestration-timeline", markup=False)

    def on_mount(self) -> None:
        self._poll()
        self._poll_task = asyncio.create_task(self._poll_loop())

    def on_unmount(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

    def action_refresh_run(self) -> None:
        self._poll()

    def action_stop_run(self) -> None:
        if self._running and self._on_stop is not None:
            self._on_stop()

    async def _poll_loop(self) -> None:
        while self._running and self.is_attached:
            await asyncio.sleep(0.6)
            if self._running and self.is_attached:
                self._poll()

    def _poll(self) -> None:
        try:
            timeline = self._trajectory.timeline()
        except Exception as exc:
            self._set_text(f"Unable to read trajectory: {exc}", "")
            return
        self._events = list(timeline)[self._baseline:]
        self._render()

    def _render(self) -> None:
        actors: dict[str, str] = {}
        for event in self._events:
            kind = str(event.get("kind") or "")
            actor = str(event.get("actor") or "")
            if actor:
                actors[actor] = kind
        if self._events:
            last = self._events[-1]
            state = str(last.get("kind") or "step")
            summary = str(last.get("summary") or "")
            status = "live" if self._running else "finished"
            header = f"{status}   ·   {len(self._events)} event(s)   ·   last: {state}"
            if summary:
                header += f" — {summary[:100]}"
            actor_line = "workers: " + ", ".join(
                f"{actor} ({kind})" for actor, kind in sorted(actors.items())
            )
            body = "\n".join(
                f"{event.get('seq', '?'):>4}  {event.get('actor', '')!s:<14.14} "
                f"{event.get('kind', '')!s:<24.24} {str(event.get('summary', ''))[:90]}"
                for event in self._events[-80:]
            )
            self._set_text(header, f"{actor_line}\n\n{body}")
        else:
            self._set_text("waiting for real trajectory events…", "No orchestration events recorded yet.")

    def _set_text(self, header: str, body: str) -> None:
        try:
            self.query_one("#orchestration-summary", Static).update(header)
            self.query_one("#orchestration-timeline", Static).update(body)
        except Exception:
            return

    def finish(self) -> None:
        """Stop the live label after the core returns, retaining final events."""
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        self._poll()


class TrajectoryPanel(PanelScreen):
    """``/trajectory`` — Trajectory Viewer (п.11/14): timeline шагов запуска."""

    title_text = "TRAJECTORY"

    def __init__(self, viewer: dict) -> None:
        super().__init__()
        self._viewer = dict(viewer or {})
        self._lines: list[dict] = list(self._viewer.get("lines") or [])

    def keys_hint(self) -> str:
        return "↑↓ navigate   ·   enter details   ·   esc close"

    def subtitle_lines(self) -> list[str]:
        usage = self._viewer.get("usage") or {}
        run_id = self._viewer.get("run_id") or "?"
        return [
            f"RUN #{run_id}   ·   {len(self._lines)} step(s)",
            (
                f"in {usage.get('input_tokens', 0)}"
                f"  out {usage.get('output_tokens', 0)}"
                f"  reasoning {usage.get('reasoning_tokens', 0)}"
                f"  ·   ${usage.get('cost_usd', 0):.4f}"
                f"  ·   {usage.get('latency_ms', 0)} ms"
            ),
        ]

    def body(self) -> ComposeResult:
        if not self._lines:
            yield Static("No steps recorded yet — send a message first.", markup=False)
            return
        rows = [
            Option(
                f"{line.get('time', '--:--:--')}  "
                f"{line.get('actor', '')!s:<12.12}  "
                f"{line.get('kind', '')!s:<20.20}  "
                f"{str(line.get('summary', ''))[:56]}",
                id=str(line.get("seq", "")),
            )
            for line in self._lines
        ]
        yield OptionList(*rows, id="trajectory-list")

    def on_mount(self) -> None:
        if self._lines:
            self.query_one("#trajectory-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id:
            self.dismiss(str(event.option.id))


def format_trajectory_detail(detail: dict | None) -> str:
    """Раскрытие одного шага (п.14-15): данные шага человекочитаемым блоком."""
    if not detail:
        return "No details for this step."
    import json as _json

    lines = [
        f"seq      {detail.get('seq')}",
        f"kind     {detail.get('kind')}",
        f"actor    {detail.get('actor')}",
        f"summary  {detail.get('summary')}",
    ]
    data = detail.get("data") or {}
    if data:
        try:
            body = _json.dumps(data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            body = str(data)
        if len(body) > 4000:
            body = body[:4000] + "\n… truncated"
        lines.append("data")
        lines.append(body)
    return "\n".join(lines)


class TrajectoryDetailPanel(PanelScreen):
    """Детали одного шага Trajectory (Enter в /trajectory)."""

    def __init__(self, detail: dict | None) -> None:
        super().__init__()
        self._detail = detail
        kind = str((detail or {}).get("kind") or "step")
        self.title_text = f"STEP · {kind.upper()}"

    def keys_hint(self) -> str:
        return "esc close"

    def body(self) -> ComposeResult:
        yield Static(format_trajectory_detail(self._detail), markup=False)


class ProvidersPanel(PanelScreen):
    """``/providers`` — Provider Manager (п.2): статусы, Enter = Test."""

    title_text = "PROVIDERS"

    def __init__(
        self,
        rows: list[dict],
        *,
        on_test: Callable[[str], Awaitable[str]] | None = None,
        on_set_key: Callable[[str, str], Awaitable[str]] | None = None,
        on_discover: Callable[[str], Awaitable[list[dict]]] | None = None,
        on_pick_model: Callable[[str, str], Awaitable[str]] | None = None,
    ) -> None:
        super().__init__()
        self._rows = [dict(row) for row in rows]
        self._on_test = on_test
        self._on_set_key = on_set_key
        self._on_discover = on_discover
        self._on_pick_model = on_pick_model
        self._models: list[dict] = []

    def keys_hint(self) -> str:
        return "↑↓ select   ·   enter test   ·   tab key field   ·   esc close"

    def subtitle_lines(self) -> list[str]:
        configured = sum(1 for row in self._rows if row.get("configured"))
        return [f"{configured}/{len(self._rows)} provider(s) configured"]

    @staticmethod
    def _row_text(row: dict) -> str:
        status = str(row.get("status") or "unknown")
        if status == "connected":
            glyph = theme.TICK
        elif status == "error":
            glyph = theme.CROSS
        else:
            glyph = theme.BULLET
        label = str(row.get("label") or row.get("id") or "")
        return (
            f"{glyph} {label:<18.18}  {status:<16.16}  "
            f"{row.get('base_url') or ''!s}"
        )

    def body(self) -> ComposeResult:
        rows = [
            Option(self._row_text(row), id=str(row.get("id") or ""))
            for row in self._rows
        ]
        yield Static("Providers — Enter tests the highlighted one.", markup=False)
        yield OptionList(*rows, id="providers-list")
        yield Static("API key for the selected provider (stored locally, never shown):", markup=False)
        yield Input(password=True, placeholder="paste API key…", id="provider-key")
        with Horizontal(classes="provider-actions"):
            yield Button("Save key & test", id="provider-save")
            yield Button("Discover models", id="provider-discover")
        yield Static("Models reported by the provider API:", markup=False)
        yield OptionList(id="provider-models")

    def on_mount(self) -> None:
        if self._rows:
            self.query_one("#providers-list", OptionList).focus()

    def _highlighted_id(self) -> str:
        option_list = self.query_one("#providers-list", OptionList)
        index = option_list.highlighted
        if index is not None and 0 <= index < len(self._rows):
            return str(self._rows[index].get("id") or "")
        return ""

    def _refresh_rows(self) -> None:
        option_list = self.query_one("#providers-list", OptionList)
        option_list.clear_options()
        for row in self._rows:
            option_list.add_option(Option(self._row_text(row), id=str(row.get("id") or "")))

    def _set_status(self, provider_id: str, status: str) -> None:
        for row in self._rows:
            if str(row.get("id")) == provider_id:
                row["status"] = status
                row["configured"] = status != "not_configured"
                break
        self._refresh_rows()

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if str(getattr(event.option_list, "id", "")) == "provider-models":
            await self._pick_model(str(event.option.id or ""))
            return
        provider_id = str(event.option.id or "")
        if not provider_id or self._on_test is None:
            return
        if self.app is not None:
            self.app.notify(f"Testing {provider_id}…", title="Providers", timeout=3)
        self.run_worker(self._test(provider_id), group="provider-test")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "provider-save":
            self.run_worker(self._save_key(), group="provider-key")
        elif event.button.id == "provider-discover":
            self.run_worker(self._discover(), group="provider-discover")

    async def _save_key(self) -> None:
        key = self.query_one("#provider-key", Input).value.strip()
        provider_id = self._highlighted_id()
        if not key or not provider_id or self._on_set_key is None:
            if self.app is not None:
                self.app.notify("Select a provider and paste its API key.", severity="warning", timeout=4)
            return
        self.query_one("#provider-key", Input).value = ""
        try:
            status = str(await self._on_set_key(provider_id, key))
        except Exception as exc:
            status = f"error: {exc}"
        self._set_status(provider_id, status)
        if self.app is not None:
            self.app.notify(f"{provider_id}: {status}", title="Providers", timeout=5)
        if status == "connected":
            await self._discover()

    async def _discover(self) -> None:
        provider_id = self._highlighted_id()
        if not provider_id or self._on_discover is None:
            return
        try:
            self._models = list(await self._on_discover(provider_id))
        except Exception as exc:
            self._models = []
            if self.app is not None:
                self.app.notify(f"{provider_id}: {exc}", title="Providers", timeout=5)
        targets = self.query_one("#provider-models", OptionList)
        targets.clear_options()
        for model in self._models:
            caps = ", ".join(model.get("capabilities") or []) or "no capabilities reported"
            targets.add_option(
                Option(f"{model.get('label')}  [{caps}]", id=str(model.get("id") or ""))
            )
        if self.app is not None:
            self.app.notify(f"{provider_id}: {len(self._models)} model(s)", title="Providers", timeout=4)

    async def _pick_model(self, route_id: str) -> None:
        model_row = next((m for m in self._models if str(m.get("id")) == route_id), None)
        if model_row is None or self._on_pick_model is None:
            return
        try:
            message = str(
                await self._on_pick_model(
                    str(model_row.get("provider_id")), str(model_row.get("model"))
                )
            )
        except Exception as exc:
            message = f"error: {exc}"
        if self.app is not None:
            self.app.notify(message, title="Providers", timeout=5)

    async def _test(self, provider_id: str) -> None:
        try:
            assert self._on_test is not None
            status = str(await self._on_test(provider_id))
        except Exception as exc:
            status = f"error: {exc}"
        self._set_status(provider_id, status)
        if self.app is not None:
            self.app.notify(f"{provider_id}: {status}", title="Providers", timeout=5)


class AgentsPanel(PanelScreen):
    """``/agents`` — Agent Registry (п.5/7): роли и назначенные им модели."""

    title_text = "AGENTS"

    def __init__(self, rows: list[dict]) -> None:
        super().__init__()
        self._rows = [dict(row) for row in rows]

    def keys_hint(self) -> str:
        return "↑↓ scroll   ·   esc close"

    def subtitle_lines(self) -> list[str]:
        return [f"{len(self._rows)} agent(s) registered"]

    @staticmethod
    def _row_text(row: dict) -> str:
        target = str(row.get("model") or "(session default)")
        provider = str(row.get("provider_id") or "")
        tools = ", ".join(row.get("tools") or []) or "(auto by task)"
        return (
            f"{row.get('label') or row.get('id')!s:<14.14}  {provider}/{target}\n"
            f"    tools: {tools}"
        )

    def body(self) -> ComposeResult:
        rows = [
            Option(self._row_text(row), id=str(row.get("id") or ""), disabled=True)
            for row in self._rows
        ]
        yield OptionList(*rows, id="agents-list")


class PluginsPanel(PanelScreen):
    """``/plugins`` — Plugin Manager: установка, включение/выключение, удаление."""

    title_text = "PLUGINS"
    BINDINGS = [
        *PanelScreen.BINDINGS,
        Binding("d", "remove_selected", "Remove", show=False),
        Binding("i", "install_folder", "Install", show=False),
        Binding("?", "show_info", "Info", show=False),
    ]

    def __init__(
        self,
        rows: list[dict],
        *,
        bundled: list[dict] | None = None,
        on_toggle: Callable[[str, bool], Awaitable[dict]] | None = None,
        on_remove: Callable[[str], Awaitable[dict]] | None = None,
        on_install: Callable[[str], Awaitable[dict]] | None = None,
        on_install_bundled: Callable[[str], Awaitable[dict]] | None = None,
    ) -> None:
        super().__init__()
        self._rows = [dict(row) for row in rows]
        for row in self._rows:
            row.setdefault("installed", True)
        for row in bundled or []:
            entry = dict(row)
            entry["installed"] = False
            self._rows.append(entry)
        self._on_toggle = on_toggle
        self._on_remove = on_remove
        self._on_install = on_install
        self._on_install_bundled = on_install_bundled

    def keys_hint(self) -> str:
        return "↑↓ select   ·   enter toggle   ·   i install   ·   d remove   ·   ? info   ·   esc close"

    def subtitle_lines(self) -> list[str]:
        installed = [row for row in self._rows if row.get("installed")]
        enabled = sum(1 for row in installed if row.get("enabled"))
        available = len(self._rows) - len(installed)
        line = f"{enabled}/{len(installed)} plugin(s) enabled"
        if available:
            line += f"  ·  {available} built-in available"
        return [line]

    @staticmethod
    def _row_text(row: dict) -> str:
        if row.get("installed") is False:
            glyph = theme.DOT_IDLE
        else:
            glyph = theme.TICK if row.get("enabled") else theme.CROSS
        version = str(row.get("version") or "")
        line = f"{glyph} {row.get('name')}  v{version}"
        if row.get("installed") is False:
            line += "  (built-in, not installed)"
        description = str(row.get("description") or "").strip()
        if description:
            line += f"\n    {description}"
        tools = ", ".join(row.get("tools") or [])
        if tools:
            line += f"\n    tools: {tools}"
        return line

    def body(self) -> ComposeResult:
        rows = [
            Option(self._row_text(row), id=str(row.get("name") or ""))
            for row in self._rows
        ]
        yield Static(
            "Plugins — Enter toggles, i installs (folder path or built-in), d removes.",
            markup=False,
        )
        yield OptionList(*rows, id="plugins-list")
        with Horizontal(classes="plugin-actions"):
            yield Button("Install…", id="plugin-install")
            yield Button("Remove", id="plugin-remove")
            yield Button("Info", id="plugin-info")
        yield Input(placeholder="folder path (…/my-plugin)…", id="plugin-path")

    def on_mount(self) -> None:
        if self._rows:
            self.query_one("#plugins-list", OptionList).focus()

    def _highlighted_name(self) -> str:
        option_list = self.query_one("#plugins-list", OptionList)
        index = option_list.highlighted
        if index is not None and 0 <= index < len(self._rows):
            return str(self._rows[index].get("name") or "")
        return ""

    def _refresh_rows(self) -> None:
        option_list = self.query_one("#plugins-list", OptionList)
        option_list.clear_options()
        for row in self._rows:
            option_list.add_option(Option(self._row_text(row), id=str(row.get("name") or "")))

    def _apply_row(self, result: dict) -> None:
        name = str(result.get("name") or "")
        for row in self._rows:
            if str(row.get("name")) == name:
                if "enabled" in result:
                    row["enabled"] = bool(result["enabled"])
                break
        self._refresh_rows()

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        name = str(event.option.id or "")
        if not name or self._on_toggle is None:
            return
        row = next((r for r in self._rows if str(r.get("name")) == name), None)
        if row is None:
            return
        if row.get("installed") is False:
            if self.app is not None:
                self.app.notify(
                    f"{name}: built-in plugin is not installed yet — press 'i' to install.",
                    severity="warning",
                    timeout=4,
                )
            return
        target = not bool(row.get("enabled"))
        if target and self.app is not None and not await self.app.push_screen_wait(
            PluginTrustDialog(row, action="run")
        ):
            return
        try:
            result = await self._on_toggle(name, target)
        except Exception as exc:
            if self.app is not None:
                self.app.notify(str(exc), severity="error", timeout=6)
            return
        self._apply_row(result)
        if self.app is not None:
            state = "enabled" if result.get("enabled") else "disabled"
            self.app.notify(f"{name}: {state}", title="Plugins", timeout=4)

    async def action_install_folder(self) -> None:
        await self._install()

    async def action_remove_selected(self) -> None:
        await self._remove()

    async def _install(self) -> None:
        # Installing a highlighted built-in plugin needs no folder path.
        highlighted = self._highlighted_name()
        selected = next(
            (r for r in self._rows if str(r.get("name")) == highlighted), None
        )
        if selected is not None and selected.get("installed") is False:
            if self._on_install_bundled is None:
                return
            if self.app is not None and not await self.app.push_screen_wait(
                PluginTrustDialog(selected, action="install")
            ):
                return
            try:
                result = await self._on_install_bundled(highlighted)
            except Exception as exc:
                if self.app is not None:
                    self.app.notify(str(exc), severity="error", timeout=6)
                return
            for row in self._rows:
                if str(row.get("name")) == highlighted:
                    row.update(result.get("manifest") or result)
                    row["installed"] = True
                    break
            self._refresh_rows()
            if self.app is not None:
                self.app.notify(f"Installed {highlighted}", title="Plugins", timeout=4)
            return
        if self._on_install is None:
            return
        path = self.query_one("#plugin-path", Input).value.strip()
        if not path:
            if self.app is not None:
                self.app.notify(
                    "Enter a plugin folder path or select a built-in plugin.",
                    severity="warning",
                    timeout=4,
                )
            return
        if self.app is not None and not await self.app.push_screen_wait(
            PluginTrustDialog({"name": path}, action="install")
        ):
            return
        try:
            result = await self._on_install(path)
        except Exception as exc:
            if self.app is not None:
                self.app.notify(str(exc), severity="error", timeout=6)
            return
        self.query_one("#plugin-path", Input).value = ""
        installed = dict(result.get("manifest") or {"name": result.get("name")})
        installed["installed"] = True
        self._rows.append(installed)
        self._refresh_rows()
        if self.app is not None:
            self.app.notify(f"Installed {result.get('name')}", title="Plugins", timeout=4)

    async def _remove(self) -> None:
        if self._on_remove is None:
            return
        name = self._highlighted_name()
        if not name:
            if self.app is not None:
                self.app.notify("Select a plugin first.", severity="warning", timeout=4)
            return
        selected = next((r for r in self._rows if str(r.get("name")) == name), None)
        if selected is not None and selected.get("installed") is False:
            if self.app is not None:
                self.app.notify(
                    f"{name}: built-in plugin is not installed — nothing to remove.",
                    severity="warning",
                    timeout=4,
                )
            return
        try:
            result = await self._on_remove(name)
        except Exception as exc:
            if self.app is not None:
                self.app.notify(str(exc), severity="error", timeout=6)
            return
        if result.get("removed"):
            removed_row = next((r for r in self._rows if str(r.get("name")) == name), None)
            self._rows = [r for r in self._rows if str(r.get("name")) != name]
            # A removed built-in plugin returns to the available catalogue.
            if removed_row is not None and removed_row.get("bundled"):
                restored = dict(removed_row)
                restored["installed"] = False
                restored["enabled"] = False
                self._rows.append(restored)
            self._refresh_rows()
        if self.app is not None:
            self.app.notify(f"Removed {name}", title="Plugins", timeout=4)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "plugin-install":
            await self._install()
        elif event.button.id == "plugin-remove":
            await self._remove()
        elif event.button.id == "plugin-info":
            self._show_info()

    async def action_show_info(self) -> None:
        self._show_info()

    def _show_info(self) -> None:
        name = self._highlighted_name()
        if not name:
            if self.app is not None:
                self.app.notify("Select a plugin first.", severity="warning", timeout=4)
            return
        row = next((r for r in self._rows if str(r.get("name")) == name), None)
        if row is None:
            return
        if self.app is not None:
            self.app.push_screen(PluginInfoPanel(dict(row)))


class PluginTrustDialog(ModalScreen[bool]):
    """Explicit consent before installing or importing plugin Python code."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    def __init__(self, row: dict, *, action: str) -> None:
        super().__init__()
        self._row = dict(row)
        self._action = action

    def compose(self) -> ComposeResult:
        name = str(self._row.get("name") or "Плагин")
        version = str(self._row.get("version") or "")
        summary = str(self._row.get("description") or "").strip()
        tools = ", ".join(self._row.get("tools") or []) or "не перечислены"
        capabilities = ", ".join(self._row.get("capabilities") or []) or "не указаны"
        ui_block = self._row.get("ui_block") or {}
        scopes = ", ".join(ui_block.get("scopes") or []) or "не указаны"
        yield Static("PLUGIN TRUST", classes="panel-title")
        yield Static(f"{name} {('v' + version) if version else ''}", markup=False)
        if summary:
            yield Static(summary, markup=False)
        yield Static(
            f"Инструменты: {tools}\nВозможности манифеста: {capabilities}\n"
            f"Заявленные UI scopes: {scopes} (не ограничивают Python-код)",
            markup=False,
        )
        yield Static(
            "Python-код плагина запускается внутри AXIOM с правами пользователя: "
            "он может читать и изменять доступные файлы, обращаться к сети, "
            "переменным окружения и запускать процессы. AXIOM не изолирует его. "
            "Заявленные ui.scopes не ограничивают доступ Python-кода.",
            markup=False,
        )
        yield Static(
            "Подтверждение установки только устанавливает файлы; плагин останется выключенным. "
            "Для запуска потребуется отдельное подтверждение. Оно сохраняется, пока плагин включён.",
            markup=False,
        )
        with Horizontal():
            yield Button("Продолжить", id="plugin-trust-accept", variant="error")
            yield Button("Отмена", id="plugin-trust-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "plugin-trust-accept":
            self.dismiss(True)
        elif event.button.id == "plugin-trust-cancel":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class PluginInfoPanel(PanelScreen):
    """Read-only documentation for one plugin — description, tools and README."""

    title_text = "PLUGIN INFO"

    def __init__(self, row: dict) -> None:
        super().__init__()
        self._row = dict(row)

    def keys_hint(self) -> str:
        return "↑↓ scroll   ·   esc close"

    def subtitle_lines(self) -> list[str]:
        name = str(self._row.get("name") or "")
        version = str(self._row.get("version") or "")
        author = str(self._row.get("author") or "")
        line = f"{name}  v{version}"
        if author:
            line += f"  ·  {author}"
        return [line]

    def _summary(self) -> str:
        lines: list[str] = []
        description = str(self._row.get("description") or "").strip()
        if description:
            lines.append(description)
            lines.append("")
        tools = self._row.get("tools") or []
        if tools:
            lines.append("Tools:")
            lines.extend(f"  • {tool}" for tool in tools)
            lines.append("")
        capabilities = self._row.get("capabilities") or []
        if capabilities:
            lines.append("Capabilities: " + ", ".join(capabilities))
        skills = self._row.get("skills") or []
        if skills:
            lines.append("Skills: " + ", ".join(skills))
        providers = self._row.get("providers") or []
        if providers:
            lines.append("Providers: " + ", ".join(providers))
        installed = self._row.get("installed")
        if installed is False:
            lines.append("")
            lines.append("(built-in, not installed — press 'i' in the plugin list to install)")
        return "\n".join(lines).strip()

    def body(self) -> ComposeResult:
        summary = self._summary()
        if summary:
            yield Static(summary, markup=False, classes="plugin-info-summary")
        readme = str(self._row.get("readme") or "").strip()
        if readme:
            yield Static("─" * 40, markup=False, classes="panel-note")
            yield Static(readme, markup=False, classes="plugin-info-readme")
        elif not summary:
            yield Static(
                "This plugin ships no description or README.md.",
                markup=False,
                classes="settings-empty",
            )


class PermissionsPanel(PanelScreen):
    """``/permissions`` — выбор реального режима разрешений (п.23)."""

    title_text = "PERMISSIONS"

    #: (value, label, hint) — the real PermissionMode values, in order.
    MODES: tuple[tuple[str, str, str], ...] = (
        ("ask", "Ask", "Every tool execution needs confirmation"),
        ("auto_approve_safe", "Auto-approve safe", "Safe tools run, risky ones ask"),
        ("auto_approve_all", "Auto-approve all", "Everything runs without confirmation"),
    )

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current

    def keys_hint(self) -> str:
        return "↑↓ select   ·   enter apply   ·   esc close"

    def subtitle_lines(self) -> list[str]:
        return [f"Active mode: {self._current}"]

    def body(self) -> ComposeResult:
        rows = [
            Option(
                f"{theme.ARROW if value == self._current else ' '} {label:<20.20}  {hint}",
                id=value,
            )
            for value, label, hint in self.MODES
        ]
        yield OptionList(*rows, id="permissions-list")

    def on_mount(self) -> None:
        self.query_one("#permissions-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        value = str(event.option.id or "")
        if value:
            self.dismiss(value)


def agent_rows(agents: list) -> list[dict]:
    """Строки Agent Registry: роль + реально назначенная ей модель из профиля."""
    rows: list[dict] = []
    for agent in agents:
        rows.append({
            "id": getattr(agent, "id", ""),
            "label": agent.name() if hasattr(agent, "name") else getattr(agent, "id", ""),
            "provider_id": getattr(agent, "provider_id", "") or "",
            "model": getattr(agent, "model", "") or "",
            "tools": list(getattr(agent, "tools", []) or []),
        })
    return rows


class MemoryPanel(PanelScreen):
    """``/memory`` — Curated Memory (W2.1): list, add, edit, delete.

    Every row is a real persisted ``MemoryItem`` projection. ``a`` adds the
    text from the input field, ``e`` edits the highlighted item's content
    in place, ``d`` deletes it. Escape closes the panel.
    """

    title_text = "MEMORY"
    BINDINGS = [
        *PanelScreen.BINDINGS,
        Binding("a", "add_item", "Add", show=False),
        Binding("e", "edit_item", "Edit", show=False),
        Binding("d", "delete_item", "Delete", show=False),
    ]

    def __init__(
        self,
        rows: list[dict],
        *,
        on_add: Callable[..., str | None] | None = None,
        on_edit: Callable[[str, str], bool] | None = None,
        on_delete: Callable[[str], bool] | None = None,
        refresh: Callable[[], Awaitable[list[dict]]] | None = None,
    ) -> None:
        super().__init__()
        self._rows = [dict(row) for row in rows]
        self._on_add = on_add
        self._on_edit = on_edit
        self._on_delete = on_delete
        self._refresh = refresh

    def keys_hint(self) -> str:
        return "↑↓ select   ·   a add   ·   e edit   ·   d delete   ·   esc close"

    def subtitle_lines(self) -> list[str]:
        if not self._rows:
            return ["No memory items yet — 'a' adds the first one."]
        global_count = sum(1 for row in self._rows if row.get("scope") == "global")
        project_count = len(self._rows) - global_count
        sensitive = sum(1 for row in self._rows if row.get("category") == "sensitive")
        line = (
            f"{len(self._rows)} item(s)   ·   {global_count} global"
            f"   ·   {project_count} project"
        )
        if sensitive:
            line += f"   ·   {sensitive} sensitive"
        return [line]

    @staticmethod
    def _row_text(row: dict) -> str:
        content = str(row.get("content") or "")
        if len(content) > 88:
            content = content[:88] + "…"
        tags = ", ".join(row.get("tags") or [])
        meta = f"{row.get('scope')}/{row.get('category')}"
        if tags:
            meta += f"  #{tags}"
        return f"{meta}\n    {content}"

    def body(self) -> ComposeResult:
        # Always render the list (even empty) so add/edit/delete can refresh
        # it in place without re-mounting the panel.
        rows = [
            Option(self._row_text(row), id=str(row.get("id") or ""))
            for row in self._rows
        ]
        yield OptionList(*rows, id="memory-list")
        yield Static(
            "Content (used by 'a' to add, or by 'e' to replace the selection):",
            markup=False,
        )
        yield Input(placeholder="memory content…", id="memory-content")

    def on_mount(self) -> None:
        if self._rows:
            self.query_one("#memory-list", OptionList).focus()


    # ------------------------------------------------------------------ utils

    def _highlighted_id(self) -> str:
        option_list = self.query_one("#memory-list", OptionList)
        index = option_list.highlighted
        if index is not None and 0 <= index < len(self._rows):
            return str(self._rows[index].get("id") or "")
        return ""

    def _refresh_rows(self) -> None:
        option_list = self.query_one("#memory-list", OptionList)
        option_list.clear_options()
        for row in self._rows:
            option_list.add_option(
                Option(self._row_text(row), id=str(row.get("id") or ""))
            )

    def _notify(self, message: str, severity: str = "information") -> None:
        if self.app is not None:
            self.app.notify(message, title="Memory", severity=severity, timeout=4)

    async def _reload(self) -> None:
        """Re-read the authoritative projection from the session.

        ``refresh`` may be a plain function (``memory_rows``) or a coroutine
        function — both are supported so the panel stays a thin adapter.
        """
        if self._refresh is None:
            return
        try:
            result = self._refresh()
            if hasattr(result, "__await__"):
                result = await result
            self._rows = [dict(row) for row in result]
        except Exception:
            return
        self._refresh_rows()

    # ---------------------------------------------------------------- actions

    async def action_add_item(self) -> None:
        if self._on_add is None:
            return
        content = self.query_one("#memory-content", Input).value.strip()
        if not content:
            self._notify("Enter the text to remember first.", severity="warning")
            return
        item_id = self._on_add(content)
        if item_id is None:
            self._notify("Memory item was rejected.", severity="error")
            return
        self.query_one("#memory-content", Input).value = ""
        await self._reload()
        self._notify(f"Stored: {content[:40]}")

    async def action_edit_item(self) -> None:
        if self._on_edit is None:
            return
        item_id = self._highlighted_id()
        if not item_id:
            self._notify("Select an item to edit.", severity="warning")
            return
        content = self.query_one("#memory-content", Input).value.strip()
        if not content:
            self._notify("Type the new content first.", severity="warning")
            return
        if not self._on_edit(item_id, content):
            self._notify("Edit rejected.", severity="error")
            return
        self.query_one("#memory-content", Input).value = ""
        await self._reload()
        self._notify("Memory item updated.")

    async def action_delete_item(self) -> None:
        if self._on_delete is None:
            return
        item_id = self._highlighted_id()
        if not item_id:
            self._notify("Select an item to delete.", severity="warning")
            return
        if not self._on_delete(item_id):
            self._notify("Item not found.", severity="error")
            return
        await self._reload()
        self._notify("Memory item deleted.")



class KnowledgePanel(PanelScreen):
    """``/knowledge`` — Knowledge Base (W2.2): collections, index, search.

    ``a`` indexes the path in the input as a collection, ``r`` re-indexes the
    highlighted collection (incremental), ``d`` removes it, ``/`` searches
    every collection with the query from the input. Escape closes.
    """

    title_text = "KNOWLEDGE"
    BINDINGS = [
        *PanelScreen.BINDINGS,
        Binding("a", "add_collection", "Add", show=False),
        Binding("r", "reindex_collection", "Reindex", show=False),
        Binding("d", "delete_collection", "Delete", show=False),
        Binding("/", "search_kb", "Search", show=False),
    ]

    def __init__(
        self,
        rows: list[dict],
        *,
        on_add: Callable[[str, str], Awaitable[dict]] | None = None,
        on_reindex: Callable[[str], Awaitable[dict]] | None = None,
        on_delete: Callable[[str], bool] | None = None,
        on_search: Callable[[str], Awaitable[list[dict]]] | None = None,
        refresh: Callable[[], Awaitable[list[dict]]] | None = None,
    ) -> None:
        super().__init__()
        self._rows = [dict(row) for row in rows]
        self._on_add = on_add
        self._on_reindex = on_reindex
        self._on_delete = on_delete
        self._on_search = on_search
        self._refresh = refresh
        self._results: list[dict] = []

    def keys_hint(self) -> str:
        return "a index path · r reindex · d remove · / search · esc close"

    def subtitle_lines(self) -> list[str]:
        if not self._rows:
            return ["No knowledge collections — type a path below and press 'a'."]
        files = sum(int(row.get("files") or 0) for row in self._rows)
        chunks = sum(int(row.get("chunks") or 0) for row in self._rows)
        return [f"{len(self._rows)} collection(s) · {files} files · {chunks} chunks"]

    @staticmethod
    def _row_text(row: dict) -> str:
        embeddings = str(row.get("embeddings") or "disabled")
        return (
            f"{row.get('name')} — {row.get('files')} files, {row.get('chunks')} chunks"
            f" · embeddings: {embeddings}\n    {row.get('path')}"
        )

    def body(self) -> ComposeResult:
        rows = [
            Option(self._row_text(row), id=str(row.get("name") or ""))
            for row in self._rows
        ]
        yield OptionList(*rows, id="knowledge-list")
        yield Static("Path for 'a' (folder/file) or query for '/':", markup=False)
        yield Input(placeholder="folder path or search query…", id="knowledge-input")
        yield Static("", id="knowledge-results", markup=False)

    def on_mount(self) -> None:
        self.query_one("#knowledge-input", Input).focus()

    def _highlighted_name(self) -> str:
        option_list = self.query_one("#knowledge-list", OptionList)
        index = option_list.highlighted
        if index is not None and 0 <= index < len(self._rows):
            return str(self._rows[index].get("name") or "")
        return ""

    def _refresh_rows(self) -> None:
        option_list = self.query_one("#knowledge-list", OptionList)
        option_list.clear_options()
        for row in self._rows:
            option_list.add_option(
                Option(self._row_text(row), id=str(row.get("name") or ""))
            )

    def _notify(self, message: str, severity: str = "information") -> None:
        if self.app is not None:
            self.app.notify(message, title="Knowledge", severity=severity, timeout=4)

    async def _reload(self) -> None:
        if self._refresh is None:
            return
        try:
            result = self._refresh()
            if hasattr(result, "__await__"):
                result = await result
            self._rows = [dict(row) for row in result]
        except Exception:
            return
        self._refresh_rows()


    async def action_add_collection(self) -> None:
        if self._on_add is None:
            return
        path = self.query_one("#knowledge-input", Input).value.strip()
        if not path:
            self._notify("Enter a folder or file path first.", severity="warning")
            return
        name = path.rstrip("/\\").replace("\\", "/").split("/")[-1] or "collection"
        result = await self._on_add(name, path)
        if not result.get("ok"):
            self._notify(str(result.get("error") or "Index failed."), severity="error")
            return
        stats = result.get("stats") or {}
        self.query_one("#knowledge-input", Input).value = ""
        await self._reload()
        self._notify(f"Indexed {name}: {stats.get('indexed', 0)} new/changed files.")

    async def action_reindex_collection(self) -> None:
        if self._on_reindex is None:
            return
        name = self._highlighted_name()
        if not name:
            self._notify("Select a collection first.", severity="warning")
            return
        result = await self._on_reindex(name)
        if not result.get("ok"):
            self._notify(str(result.get("error") or "Reindex failed."), severity="error")
            return
        stats = result.get("stats") or {}
        await self._reload()
        self._notify(
            f"{name}: {stats.get('indexed', 0)} changed, {stats.get('unchanged', 0)} unchanged."
        )

    async def action_delete_collection(self) -> None:
        if self._on_delete is None:
            return
        name = self._highlighted_name()
        if not name:
            self._notify("Select a collection first.", severity="warning")
            return
        if not self._on_delete(name):
            self._notify("Collection not found.", severity="error")
            return
        await self._reload()
        self._notify(f"Collection '{name}' removed.")

    async def action_search_kb(self) -> None:
        if self._on_search is None:
            return
        query = self.query_one("#knowledge-input", Input).value.strip()
        if not query:
            self._notify("Type a search query first.", severity="warning")
            return
        self._results = await self._on_search(query)
        target = self.query_one("#knowledge-results", Static)
        if not self._results:
            target.update(f"(no fragments match '{query}')")
            return
        lines = [f"Fragments for '{query}':"]
        for item in self._results[:5]:
            lines.append(
                f"[{item.get('collection')}/{item.get('source')}"
                f":{item.get('start_line')}-{item.get('end_line')}]"
            )
            lines.append("  " + " ".join(str(item.get("text") or "").split())[:160])
        target.update("\n".join(lines))

