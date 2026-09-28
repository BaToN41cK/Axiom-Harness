"""AXIOM TUI application — a thin adapter wiring the core stream to widgets.

The app owns no logic of its own: every status, every reasoning delta and every
source comes from :class:`axiom.core.chat.ChatSession`, and every user action is
routed back into the core (``send`` / ``cancel`` / ``switch_model`` / ...).
"""

from __future__ import annotations

import asyncio
import time
import webbrowser
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.theme import Theme as TextualTheme

from axiom.core.benchmark import BenchmarkRunner, BenchmarkScenario
from axiom.core.chat import ChatSession, StartupReport
from axiom.core.events import (
    ChatEvent,
    ContentChunk,
    Done,
    ErrorEvent,
    ReasoningChunk,
    SearchResultEvent,
    SourceItem,
    StatusChange,
    ToolCallEvent,
    ToolResultEvent,
)
from axiom.core.models import ModelRegistry
from axiom.core.permissions import PermissionMode, PermissionOutcome
from axiom.core.state import GenerationState
from axiom.core.tools.web_search import FETCH_URL_TOOL, WEB_SEARCH_TOOL
from axiom.frontends.tui.widgets.commands import COMMANDS, find_command
from axiom.frontends.tui.widgets.find import ChatFindBar
from axiom.frontends.tui.widgets.header import HeaderBar, StatusBar
from axiom.frontends.tui.widgets.messages import AssistantMessage, ChatView, UserMessage
from axiom.frontends.tui.widgets.panels import (
    AgentsPanel,
    BenchmarkPanel,
    HelpPanel,
    HistoryPanel,
    KnowledgePanel,
    MemoryPanel,
    ModelPanel,
    OrchestrationPanel,
    PermissionsPanel,
    PluginsPanel,
    ProfilePanel,
    ProvidersPanel,
    SearchTestPanel,
    SettingsPanel,
    StatusPanel,
    TrajectoryDetailPanel,
    TrajectoryPanel,
    agent_rows,
)
from axiom.frontends.tui.widgets.permissions import PermissionDialog
from axiom.frontends.tui.widgets.prompt import InputBar
from axiom.frontends.tui.widgets.splash import SplashScreen, StartupStep
from axiom.shared import theme as palette


class WorkspaceScreen(Screen):
    """The main screen: header, chat view, prompt bar and status bar."""

    BINDINGS = [
        Binding("ctrl+c", "stop_generation", "Stop", priority=True),
        Binding("escape", "stop_generation", "Stop", show=False),
        Binding("ctrl+f", "find_chat", "Find chat", priority=True),
    ]

    #: Auto-focus is disabled on this screen so the hidden slash-menu list
    #: can never steal focus from the prompt at startup; on_show() focuses
    #: the prompt explicitly once the screen is live.
    AUTO_FOCUS = None

    def __init__(
        self,
        session: ChatSession,
        *,
        animations: bool = True,
        version: str | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self._animations = animations
        self._version = version
        self._generating = False
        self._read_queue: list[SourceItem] = []
        self._read_index = 0
        self._history: list[str] = []
        self._history_index: int = -1

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        yield ChatView()
        yield ChatFindBar()
        yield InputBar()
        yield StatusBar()

    def on_mount(self) -> None:
        self.query_one(ChatFindBar).display = False
        self._refresh_model_display()
        # W2.4: ASK tools (incl. model-initiated memory writes) open the real
        # permission dialog; without this callback they are denied silently.
        self.session.permissions.request_callback(self._ask_permission)
        # The splash probe already established reachability; reflect its real
        # result here — the status bar keeps updating from live events only.
        connected = self._version is not None
        self.query_one(HeaderBar).set_connection(connected, self._version)
        self.status_bar.set_connection(connected, self._version)

    def on_show(self) -> None:
        # on_mount runs before this screen is active; a focus() there races the
        # ScreenResume that follows push_screen() and is dropped. Focus only
        # once the workspace screen is actually live, so the very first `/`
        # lands in the input.
        try:
            self.input_bar.input.focus()
        except Exception:  # pragma: no cover - teardown race
            pass

    # ------------------------------------------------------------------ helpers

    @property
    def chat_view(self) -> ChatView:
        return self.query_one(ChatView)

    @property
    def input_bar(self) -> InputBar:
        return self.query_one(InputBar)

    @property
    def status_bar(self) -> StatusBar:
        return self.query_one(StatusBar)

    def apply_startup(self, report: StartupReport) -> None:
        """Adopt the real splash results (version, model, connection)."""
        if report.version:
            self._version = report.version
        connected = report.ollama_available
        self.query_one(HeaderBar).set_connection(connected, report.version)
        self.status_bar.set_connection(connected, report.version)
        self._refresh_model_display()

    def _refresh_model_display(self) -> None:
        model = self.session.active_model
        display = model.display_name if model is not None else ""
        self.query_one(HeaderBar).update_model(display)
        self.status_bar.set_model(display)

    # --------------------------------------------------------------- generation

    def handle_submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if text.startswith("/"):
            self.input_bar.clear_prompt()
            self._remember(text)
            self._execute_command(text)
            return
        self.input_bar.clear_prompt()
        self._remember(text)
        self._start_generation(text)

    def _remember(self, text: str) -> None:
        if not text.strip():
            return
        if self._history and self._history[-1] == text:
            self._history_index = -1
            return
        self._history.append(text)
        if len(self._history) > 200:
            self._history = self._history[-200:]
        self._history_index = -1

    def on_input_bar_history_recall(self, event: InputBar.HistoryRecall) -> None:
        event.stop()
        if not self._history:
            return
        # _history_index: -1 = fresh line, 0 = newest submitted, N = N steps older.
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
        position = len(self._history) - 1 - self._history_index
        self.input_bar.input.set_prompt(self._history[position])

    def _start_generation(
        self,
        text: str,
        *,
        force_search: bool = False,
        search_query: str | None = None,
    ) -> None:
        if self._generating or self.session.busy:
            self.notify("A generation is already running.", severity="warning", timeout=4)
            return
        self.run_worker(
            self._generate(text, force_search=force_search, search_query=search_query),
            exclusive=True,
            group="generation",
        )

    async def _generate(
        self,
        text: str,
        *,
        force_search: bool = False,
        search_query: str | None = None,
    ) -> None:
        config = self.session.config
        self.chat_view.add(UserMessage(text, time.time()))
        assistant = AssistantMessage(
            animations=self._animations,
            reasoning_expanded=config.reasoning_expanded,
        )
        self.chat_view.add(assistant)
        self._generating = True
        self._read_queue = []
        self._read_index = 0
        self.input_bar.set_busy(True)
        try:
            async for event in self.session.send(
                text, force_search=force_search, search_query=search_query
            ):
                await self._dispatch_event(assistant, event)
        finally:
            self._generating = False
            try:
                self.input_bar.set_busy(False)
            except NoMatches:  # pragma: no cover - teardown race
                pass
            await assistant.close_stream()
            if not assistant.finished:
                assistant.finish(GenerationState.ERROR)
            try:
                self.status_bar.set_state(self.session.state)
                self.input_bar.input.focus()
            except NoMatches:  # pragma: no cover - teardown race
                pass

    async def _dispatch_event(self, assistant: AssistantMessage, event: ChatEvent) -> None:
        """Project one real core event onto the widgets. No invention here."""
        if isinstance(event, StatusChange):
            assistant.set_state(event.state, detail=event.detail)
            self.status_bar.set_state(event.state, event.detail)
            if event.state == GenerationState.SEARCHING:
                self.status_bar.set_web(True)
                assistant.search_started(event.detail or "")
            if event.detail == "read_source":
                self._begin_source_read(assistant)
        elif isinstance(event, ReasoningChunk):
            assistant.add_reasoning(event.text)
            self.status_bar.set_thinking(True)
        elif isinstance(event, ContentChunk):
            await assistant.add_answer(event.text)
        elif isinstance(event, ToolCallEvent):
            assistant.tool_started(event.name, event.arguments)
            if event.name == WEB_SEARCH_TOOL:
                self.status_bar.set_web(True)
        elif isinstance(event, SearchResultEvent):
            self._read_queue = list(event.sources)
            self._read_index = 0
            assistant.search_finished(event.query, event.sources)
            self.status_bar.set_web(True)
        elif isinstance(event, ToolResultEvent):
            if event.ok:
                detail = f"{event.duration_ms} ms" if event.duration_ms else "ok"
                assistant.tool_finished(event.name, True, detail)
            else:
                assistant.tool_finished(event.name, False, event.error or "Tool execution failed.")
                if event.name == WEB_SEARCH_TOOL:
                    self.status_bar.set_web(False)
            if event.name == WEB_SEARCH_TOOL and not event.ok:
                assistant.search_failed(event.error or "Web search failed.")
            elif event.name == FETCH_URL_TOOL:
                self._end_source_read(assistant, event.ok)
        elif isinstance(event, ErrorEvent):
            assistant.add_error(event.message, event.hint)
        elif isinstance(event, Done):
            await assistant.close_stream()
            assistant.finish(
                event.state,
                duration_ms=event.duration_ms or None,
                tokens_out=event.tokens_out,
                tokens_per_second=event.tokens_per_second,
            )
            self.status_bar.set_state(event.state)
            self.status_bar.add_tokens(event.tokens_out, event.tokens_per_second)
            if not event.state.is_busy:
                self.status_bar.set_web(False)

    def _begin_source_read(self, assistant: AssistantMessage) -> None:
        if self._read_index < len(self._read_queue):
            assistant.read_started(self._read_queue[self._read_index].url)

    def _end_source_read(self, assistant: AssistantMessage, ok: bool) -> None:
        if self._read_index < len(self._read_queue):
            source = self._read_queue[self._read_index]
            self._read_index += 1
            assistant.read_finished(source.url, ok)

    async def action_stop_generation(self) -> None:
        self._request_stop()

    def _request_stop(self) -> None:
        self.session.cancel()

    def on_input_bar_stop_requested(self, event: InputBar.StopRequested) -> None:
        event.stop()
        self._request_stop()

    def on_input_bar_submitted(self, event: InputBar.Submitted) -> None:
        event.stop()
        self.handle_submit(event.value)

    def check_action(self, action: str, parameters: tuple) -> bool:  # type: ignore[override]
        # Ctrl+C only acts as Stop while a generation is really in flight;
        # otherwise the system binding (copy / quit hint) stays intact.
        if action == "stop_generation":
            return self._generating
        return True

    # ------------------------------------------------------------ source clicks

    def on_source_row_opened(self, event) -> None:
        event.stop()
        webbrowser.open(event.source.url)

    def on_key(self, event) -> None:
        if event.key == "end" and not self.input_bar.input.has_focus:
            self.chat_view.jump_to_end()

    # --------------------------------------------------------------- chat find

    def action_find_chat(self) -> None:
        bar = self.query_one(ChatFindBar)
        input_widget = bar.query_one("#find-input")
        input_widget.can_focus = True
        bar.display = True
        self.app.set_focus(input_widget)
        self.call_after_refresh(input_widget.focus)

    def on_chat_find_bar_closed(self, event: ChatFindBar.Closed) -> None:
        event.stop()
        bar = self.query_one(ChatFindBar)
        bar.display = False
        bar.query_one("#find-input").can_focus = False
        self.input_bar.input.focus()

    def on_chat_find_bar_changed(self, event: ChatFindBar.Changed) -> None:
        event.stop()
        matches = self.chat_view.find_matches(event.query)
        self.query_one(ChatFindBar).set_matches(len(matches), 0 if matches else -1)
        if matches:
            self.chat_view.focus_match(matches[0])

    def on_chat_find_bar_navigate(self, event: ChatFindBar.Navigate) -> None:
        event.stop()
        bar = self.query_one(ChatFindBar)
        query = bar._query
        matches = self.chat_view.find_matches(query)
        if not matches:
            bar.set_matches(0, -1)
            return
        index = (bar._index + event.direction) % len(matches)
        bar.set_matches(len(matches), index)
        self.chat_view.focus_match(matches[index])

    # ---------------------------------------------------------------- commands

    def _execute_command(self, raw: str) -> None:
        token, _, argument = raw.strip().partition(" ")
        argument = argument.strip()
        command = find_command(token)
        if command is None:
            self.notify(f"Unknown command: {token}", severity="warning", timeout=4)
            return
        name = command.name
        if name == "/exit":
            self.app.exit()
        elif name == "/help":
            self.app.push_screen(HelpPanel(COMMANDS))
        elif name in ("/model", "/models"):
            if name == "/model" and argument:
                self.run_worker(self._switch_model(argument), exclusive=True, group="model")
            else:
                self.app.push_screen(
                    ModelPanel(
                        self.session.registry.models,
                        self.session.active_model.name if self.session.active_model else None,
                        refresh=self.session.refresh_models,
                    ),
                    callback=self._model_chosen,
                )
        elif name == "/clear":
            # Clear the visible transcript only; stored history files are kept
            # so /history still shows every conversation.
            self.chat_view.clear_messages()
            self.notify("Transcript cleared — history kept.", title="Clear", timeout=3)
        elif name == "/new":
            self.session.new_conversation()
            self.chat_view.clear_messages()
            self.status_bar.set_thinking(None)
            self.notify("New conversation started.", title="New", timeout=3)
        elif name == "/history":
            self.app.push_screen(
                HistoryPanel(self.session.history(), on_delete=self._delete_conversation),
                callback=self._history_chosen,
            )
        elif name == "/settings":
            self.app.push_screen(SettingsPanel(self.session.config))
        elif name == "/search":
            if not argument:
                self.notify("Usage: /search <query>", severity="warning", timeout=4)
                return
            self._start_generation(argument, force_search=True, search_query=argument)
        elif name == "/searchtest":
            self.run_worker(
                self._run_search_test(argument),
                exclusive=True,
                group="search-test",
            )
        elif name == "/status":
            self.app.push_screen(
                StatusPanel(
                    ollama_url=self.session.client.base_url,
                    version=self._version,
                    model=self.session.active_model,
                    metrics=self.session.last_metrics,
                    search_provider=getattr(self.session.provider, "name", "Web"),
                )
            )
        elif name == "/permissions":
            self.app.push_screen(
                PermissionsPanel(self.session.permissions.autonomy),
                callback=self._permissions_chosen,
            )
        elif name == "/profiles":
            self.app.push_screen(
                ProfilePanel(
                    self.session.profiles.all,
                    self.session.profiles.active_name,
                ),
                callback=self._profile_chosen,
            )
        elif name == "/trajectory":
            self.app.push_screen(
                TrajectoryPanel(self.session.trajectory.viewer()),
                callback=self._trajectory_step_chosen,
            )
        elif name == "/providers":
            manager = getattr(self.session, "provider_manager", None)
            if manager is None:
                self.notify("Provider layer unavailable.", severity="warning", timeout=4)
                return
            self.app.push_screen(
                ProvidersPanel(
                    manager.status_rows(),
                    on_test=manager.test_provider,
                    on_set_key=self._provider_set_key,
                    on_discover=self._provider_discover,
                    on_pick_model=self._provider_pick_model,
                )
            )
        elif name == "/agents":
            registry = getattr(self.session, "agent_registry", None)
            if registry is None:
                self.notify("Agent registry unavailable.", severity="warning", timeout=4)
                return
            self.app.push_screen(AgentsPanel(agent_rows(registry.all())))
        elif name == "/plugins":
            # Live reload: discover folders dropped into ~/.axiom/plugins since boot.
            self.session.load_plugins()
            self.app.push_screen(
                PluginsPanel(
                    [m.row() for m in self.session.plugins.list()],
                    bundled=[m.row() for m in self.session.plugin_manager.bundled_manifests()],
                    on_toggle=self._plugin_toggle,
                    on_remove=self._plugin_remove,
                    on_install=self._plugin_install,
                    on_install_bundled=self._plugin_install_bundled,
                )
            )
        elif name == "/memory":
            # W2.1 Curated Memory: real persisted items, user-managed.
            self.app.push_screen(
                MemoryPanel(
                    self.session.memory_rows(),
                    on_add=lambda content: self.session.memory_write_for_user(content),
                    on_edit=self.session.memory_edit,
                    on_delete=self.session.memory_forget,
                    refresh=self.session.memory_rows,
                )
            )
        elif name == "/knowledge":
            # W2.2 Knowledge Base: real SQLite/FTS5 collections + cited search.
            self.app.push_screen(
                KnowledgePanel(
                    self.session.knowledge_rows(),
                    on_add=self.session.knowledge_add_collection,
                    on_reindex=self.session.knowledge_reindex,
                    on_delete=self.session.knowledge_remove_collection,
                    on_search=self.session.knowledge_search_rows,
                    refresh=self.session.knowledge_rows,
                )
            )
        elif name == "/benchmark":
            try:
                repetitions = int(argument) if argument else 2
            except ValueError:
                repetitions = 0
            if not 1 <= repetitions <= 5:
                self.notify("Usage: /benchmark [repetitions: 1–5]", severity="warning", timeout=4)
                return
            if self._generating or self.session.busy:
                self.notify("A generation is already running.", severity="warning", timeout=4)
                return
            self.app.run_worker(self._run_benchmark(repetitions), exclusive=True, group="benchmark")
        elif name == "/orchestrate":
            if not argument:
                self.notify("Usage: /orchestrate <task>", severity="warning", timeout=4)
                return
            if self._generating or self.session.busy:
                self.notify("A generation is already running.", severity="warning", timeout=4)
                return
            input_bar = self.input_bar
            baseline = len(self.session.trajectory.timeline())
            panel = OrchestrationPanel(
                self.session.trajectory, baseline=baseline, on_stop=self.session.cancel
            )
            self.app.push_screen(panel)
            self.app.run_worker(
                self._run_orchestrated(argument, panel, input_bar),
                exclusive=True,
                group="generation",
            )

    # ------------------------------------------------------------------ panels

    async def _run_benchmark(self, repetitions: int) -> None:
        """Run measured cold/warm scenarios through isolated real sessions."""
        input_bar = self.input_bar
        self._generating = True
        input_bar.set_busy(True)
        try:
            config = self.session.config.model_copy(deep=True)
            config.save_history = False
            config.warmup_model = False
            scenario = BenchmarkScenario(
                "tui-smoke",
                "Respond with one short sentence: benchmark ready.",
                cold=True,
            )

            async def session_factory() -> ChatSession:
                return ChatSession(config=config.model_copy(deep=True))

            report = await BenchmarkRunner(
                session_factory,
                [scenario],
                repetitions=repetitions,
            ).run()
            self.app.push_screen(BenchmarkPanel(report), callback=self._benchmark_chosen)
        except Exception as exc:
            self.notify(f"Benchmark failed: {exc}", severity="error", timeout=8)
        finally:
            self._generating = False
            input_bar.set_busy(False)

    def _benchmark_chosen(self, result: str | None) -> None:
        if result == "rerun":
            self._execute_command("/benchmark")

    async def _run_search_test(self, query: str) -> None:
        """Run a real search probe and show the honest result (W1.2)."""
        query = (query or "").strip()
        self.status_bar.set_web(True)
        try:
            report = await self.session.search_test(query)
            self.app.push_screen(SearchTestPanel(report, query=query))
        except Exception as exc:  # defensive: the worker must not crash the app
            self.notify(f"Search test failed: {exc}", severity="error", timeout=6)
        finally:
            self.status_bar.set_web(False)

    async def _run_orchestrated(
        self,
        task: str,
        panel: OrchestrationPanel | None = None,
        input_bar: InputBar | None = None,
    ) -> None:
        input_bar = input_bar or self.input_bar
        self._generating = True
        input_bar.set_busy(True)
        try:
            self.chat_view.add(UserMessage(f"/orchestrate {task}", time.time()))
            assistant = AssistantMessage(animations=self._animations)
            self.chat_view.add(assistant)
            try:
                result = await self.session.run_orchestrated(task, limit=5, max_iterations=3)
            except asyncio.CancelledError:
                # The worker itself was cancelled (Esc / exclusive worker swap);
                # the session already recorded the stop in the trajectory.
                await assistant.add_answer("Оркестрация остановлена пользователем.")
                return
            if result.get("cancelled") or result.get("error") == "cancelled":
                await assistant.add_answer("Оркестрация остановлена пользователем.")
                return
            if result.get("ok") is False and result.get("error"):
                await assistant.add_answer(f"Оркестрация не запущена: {result['error']}")
                return
            lines = ["## Оркестрация завершена", ""]
            for item in result.get("results", []):
                agent = item.get("agent", "агент")
                detail = item.get("content") or item.get("error") or "нет отчёта"
                provider = item.get("provider_id") or "?"
                model = item.get("model") or "?"
                lines.append(f"- **{agent}** (`{provider}/{model}`): {detail}")
            review = result.get("review_details") or {}
            lines += ["", f"## Reviewer ({'APPROVED' if result.get('approved') else 'REWORK'})",
                      str(result.get("review") or "нет ответа")]
            if review.get("issues"):
                lines.append("Issues: " + "; ".join(str(i) for i in review["issues"]))
            if review.get("required_changes"):
                lines.append("Required: " + "; ".join(str(c) for c in review["required_changes"]))
            verification = result.get("verification") or {}
            lines += ["", "## Verification",
                      str(verification.get("summary") or verification.get("error") or "не запускалась")]
            lines += ["", "## Definition of Done\n" + "\n".join(
                          f"- {item}" for item in result.get("definition_of_done", [])
                      ),
                      "\nГотово." if result.get("completed", result.get("approved"))
                      else "\nЕсть замечания reviewer или verification не прошла."]
            await assistant.add_answer("\n".join(lines))
        except Exception as exc:
            self.notify(str(exc), severity="error", timeout=8)
        finally:
            self._generating = False
            input_bar.set_busy(False)
            if panel is not None:
                panel.finish()

    def _model_chosen(self, name: str | None) -> None:
        if name:
            self.run_worker(self._switch_model(name), exclusive=True, group="model")

    async def _switch_model(self, name: str) -> None:
        try:
            model = await self.session.switch_model(name)
        except Exception as exc:
            self.notify(str(exc), severity="error", timeout=6)
            return
        self._refresh_model_display()
        self.notify(f"Model switched to {model.display_name}", title="Models", timeout=4)

    def _profile_chosen(self, name: str | None) -> None:
        """Apply the selected system-prompt profile (``/profiles``)."""
        if not name:
            return
        prompt = self.session.profiles.get(name)
        if prompt is None or not self.session.profiles.select(name):
            self.notify(f"Unknown profile: {name}", severity="warning", timeout=4)
            return
        # The agent reads ``Config.system_prompt``; keep the real source of
        # truth in sync so the next turn uses the chosen persona.
        self.session.config.system_prompt = prompt
        self.session.config.save()
        self.notify(f"Profile: {name}", title="Profiles", timeout=4)

    def _trajectory_step_chosen(self, seq: str | None) -> None:
        """Open the detail view for one trajectory step (Enter in ``/trajectory``)."""
        if not seq:
            return
        try:
            detail = self.session.trajectory.detail(int(seq))
        except (TypeError, ValueError):
            detail = None
        self.app.push_screen(TrajectoryDetailPanel(detail))

    def _permissions_chosen(self, mode: str | None) -> None:
        """Apply the mode chosen in ``/permissions`` (the real PermissionManager)."""
        if not mode:
            return
        if mode in {"plan", "edit", "auto", "full"}:
            try:
                applied = self.session.permissions.set_autonomy(mode)
            except ValueError:
                self.notify(f"Unknown autonomy mode: {mode}", severity="warning", timeout=4)
                return
            self.notify(f"Autonomy: {applied}", title="Permissions", timeout=4)
            return
        try:
            self.session.permissions.mode = PermissionMode(mode)
        except ValueError:
            self.notify(f"Unknown permission mode: {mode}", severity="warning", timeout=4)
            return
        self.notify(f"Permission mode: {mode}", title="Permissions", timeout=4)

    async def _ask_permission(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> PermissionOutcome:
        """W2.4+W4.9: show the real modal with risk/command/task context."""
        detail: dict[str, Any] = {}
        describe = getattr(self.session.permissions, "describe_request", None)
        if callable(describe):
            try:
                detail = dict(describe(tool_name, dict(arguments or {})) or {})
            except Exception:
                detail = {}
        task_id = self.session.permissions.active_task_id
        return await self.app.push_screen_wait(PermissionDialog(
            tool_name, dict(arguments or {}),
            risk=str(detail.get("risk", "SAFE")),
            reason=str(detail.get("reason", "")),
            command=str(detail.get("command", "")),
            task_id=task_id,
        ))

    async def _plugin_toggle(self, name: str, enabled: bool) -> dict:
        """Toggle a plugin's enable state (``/plugins``)."""
        return self.session.toggle_plugin(name, enabled)

    async def _plugin_remove(self, name: str) -> dict:
        """Remove an installed plugin (``/plugins``)."""
        return {"name": name, "removed": self.session.remove_plugin(name)}

    async def _plugin_install(self, path: str) -> dict:
        """Install a plugin from a folder on disk (``/plugins``)."""
        return self.session.install_plugin_from_folder(path)

    async def _plugin_install_bundled(self, name: str) -> dict:
        """Install a built-in AXIOM plugin from the bundled catalogue (``/plugins``)."""
        return self.session.install_bundled_plugin(name)

    async def _provider_set_key(self, provider_id: str, api_key: str) -> str:
        """Store a provider API key locally, then verify it (secret never logged)."""
        manager = getattr(self.session, "provider_manager", None)
        if manager is None:
            return "not_configured"
        manager.set_key(provider_id, api_key)
        return await manager.test_provider(provider_id)

    async def _provider_discover(self, provider_id: str) -> list[dict]:
        """Discover models through the provider API (empty when it fails)."""
        manager = getattr(self.session, "provider_manager", None)
        if manager is None:
            return []
        return await manager.model_rows(provider_id)

    async def _provider_pick_model(self, provider_id: str, model: str) -> str:
        """Make the chosen provider model the router's primary target."""
        self.session.config.router_primary = {"provider_id": provider_id, "model": model}
        self.session.config.save()
        return f"Route: {provider_id}/{model}"

    def _history_chosen(self, conversation_id: str | None) -> None:
        if not conversation_id:
            return
        conversation = self.session.load_conversation(conversation_id)
        if conversation is None:
            self.notify("Could not open that conversation.", severity="error", timeout=6)
            return
        self._render_conversation(conversation)

    def _delete_conversation(self, conversation_id: str) -> bool:
        return self.session.delete_conversation(conversation_id)

    def _render_conversation(self, conversation) -> None:
        """Project a stored conversation back onto the chat view."""
        self.chat_view.clear_messages()
        for message in conversation.messages:
            if message.role == "user" and message.content:
                self.chat_view.add(UserMessage(message.content, message.created_at))
            elif message.role == "assistant" and (message.content or message.thinking):
                assistant = AssistantMessage(
                    animations=self._animations,
                    reasoning_expanded=self.session.config.reasoning_expanded,
                )
                self.chat_view.add(assistant)
                self.run_worker(
                    self._render_stored_answer(assistant, message.content, message.thinking),
                    exclusive=False,
                    group="render",
                )

    async def _render_stored_answer(
        self, assistant: AssistantMessage, content: str, thinking: str | None
    ) -> None:
        if thinking:
            assistant.add_reasoning(thinking)
        if content:
            await assistant.add_answer(content)
        if assistant.reasoning_panel is not None:
            assistant.reasoning_panel.finish(GenerationState.COMPLETED, None)
        assistant.finish(GenerationState.COMPLETED)


class AxiomApp(App):
    """AXIOM workspace: real startup probes, then the main screen."""

    CSS_PATH = "theme.tcss"
    TITLE = "AXIOM"

    #: App-level auto-focus is off; each screen manages focus explicitly.
    AUTO_FOCUS = None

    def __init__(self, session: ChatSession | None = None) -> None:
        super().__init__()
        self.session = session or ChatSession()
        self._version: str | None = None

    def on_mount(self) -> None:
        self.register_theme(TextualTheme(**palette.theme_colors(self.session.config.accent)))
        self.theme = palette.THEME_NAME
        self.add_class("panel-hover" if self.session.config.panel_hover else "no-panel-hover")
        self.push_screen(
            SplashScreen(self._startup_steps(), animations=self.session.config.animations)
        )

    # ------------------------------------------------------------ real startup

    def _startup_steps(self) -> list[StartupStep]:
        session = self.session

        async def connect() -> tuple[bool, str]:
            if not await session.client.is_available():
                return False, f"Ollama is not reachable at {session.client.base_url}"
            version = await session.client.version()
            self._version = version
            return True, f"Ollama {version}"

        async def detect_models() -> tuple[bool, str]:
            models = await session.registry.refresh()
            if not models:
                return False, "No models are installed. Run: ollama pull qwen3:8b"
            return True, f"{len(models)} model(s) detected"

        async def select_model() -> tuple[bool, str]:
            model = session.registry.resolve(session.config.model)
            if model is None:
                return False, "No model is available"
            session.active_model = model
            session.conversation.model = model.name
            ModelRegistry.persist_selection(session.config, model.name)
            return True, model.display_name

        async def init_workspace() -> tuple[bool, str]:
            session.config.save()
            return True, "Workspace ready"

        return [
            StartupStep("Connecting to Ollama", connect),
            StartupStep("Detecting models", detect_models),
            StartupStep("Selecting model", select_model),
            StartupStep("Initializing workspace", init_workspace),
        ]

    def start_workspace(self) -> None:
        """Switch from the splash to the main screen (called by SplashScreen)."""
        self.pop_screen()
        self.push_screen(
            WorkspaceScreen(
                self.session,
                animations=self.session.config.animations,
                version=self._version,
            )
        )


def main() -> int:
    """Entry point used by ``axiom.__main__``."""
    session = ChatSession()
    app = AxiomApp(session)
    app.run()
    return 0
