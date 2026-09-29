"""The AXIOM agent loop.

    USER → CONTEXT → MODEL → THINKING → DECISION
        → (TOOL / SEARCH) → TOOL RESULT → MODEL → FINAL ANSWER

Everything emitted here is driven by real backend activity: statuses are
transitions of :class:`~axiom.core.state_machine.GenerationStateMachine`,
reasoning appears only when the model actually sends it, and search results
only when a real search provider returned them.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from axiom.core.config import Config
from axiom.core.events import (
    ChatEvent,
    ContentChunk,
    ReasoningChunk,
    SearchResultEvent,
    SourceItem,
    StatusChange,
    ToolCallEvent,
    ToolResultEvent,
)
from axiom.core.models import ModelInfo
from axiom.core.ollama import OllamaClient, ToolCallRequest
from axiom.core.performance import (
    PerformanceMetrics,
    classify_mode,
    complexity_of,
    thinking_level,
    tool_scope,
)
from axiom.core.state import GenerationState
from axiom.core.state_machine import GenerationStateMachine
from axiom.core.tools.base import ToolResult
from axiom.core.tools.registry import ToolRegistry
from axiom.core.tools.web_search import (
    FETCH_URL_TOOL,
    WEB_SEARCH_TOOL,
    WebSearchTool,
)

#: Hard limit on tool rounds — the agent must never loop forever.
MAX_TOOL_ROUNDS = 3

#: Tools the agent advertises to the model. ``fetch_url`` matters most when the
#: user pastes a link: the model must read the page instead of guessing.
OFFERED_TOOLS = (WEB_SEARCH_TOOL, FETCH_URL_TOOL)

#: Links the user pasted are read automatically — local models do not reliably
#: call tools on their own, so the agent must not depend on that.
MAX_AUTO_FETCH = 2

#: Characters of a fetched page handed to the model as context.
MAX_PAGE_CHARS = 6000

DEFAULT_SYSTEM_PROMPT = (
    "You are AXIOM, a precise AI assistant running on the user's machine "
    "through the configured model provider (Ollama or an external API). "
    "Answer directly and accurately. Use markdown when it helps. "
    "Never invent facts; if you are unsure, say so.\n\n"
    "You have real tools:\n"
    "- web_search(query) — search the public web; use it whenever the answer "
    "may depend on current or factual online information.\n"
    "- fetch_url(url) — read a web page; ALWAYS use it when the user gives a "
    "link, so you answer from the actual page content, not from memory.\n"
    "Do not say you cannot browse the web — you can, through these tools.\n\n"
    "You also have real workspace tools operating inside the user's project:\n"
    "- list_files(path) — list a directory to explore the project.\n"
    "- read_file(path) — read a file; ALWAYS read a file before editing it.\n"
    "- write_file(path, content) — create a new file or rewrite one entirely.\n"
    "- edit_file(path, old_text, new_text) — replace an exact unique snippet.\n"
    "- search_text(pattern) / search_files(glob) — find code by content/name.\n"
    "- create_directory(path), copy/move/delete (delete asks the user first).\n"
    "- run_command(command) — run tests/builds in the workspace (safe ones "
    "run at once, others ask the user first).\n"
    "- inspect_project() — describe the current project.\n"
    "- git_status/git_diff/git_log/git_branch — read-only git inspection.\n"
    "When the user asks about their project, do not guess: list and read the "
    "actual files. When asked to change code, read first, then edit or write. "
    "If you have filesystem tools, you MUST use them instead of only describing a plan. "
    "All paths are relative to the workspace root.\n\n"
    "For project tasks follow: understand → investigate → plan → execute → verify → "
    "correct → report. Never claim a test, build, file, Git state, or tool result "
    "that was not actually observed. Read a file before editing it, prefer minimal "
    "local changes, and use the explicitly mentioned files as the primary context. "
    "If work is not verified, say exactly what remains unverified."
)

WORKSPACE_PROMPT_ADDON = (
    "\nWorkspace tools are enabled for this conversation. For project questions "
    "use list_files/read_file instead of guessing; for changes use edit_file "
    "with a unique exact snippet, or write_file for new files."
)


def workspace_context_block(root: str | None) -> str:
    """Short factual block about the current workspace (no full project dump).

    Keeps the model grounded in the real directory: path, project kind, git
    branch and the top-level layout. Never sends file contents — the agent
    must read what it needs via tools (spec §4: Project Index → AI Context).
    """
    if not root:
        return ""
    try:
        from pathlib import Path as _Path

        from axiom.core.workspace import detect_project as _detect

        info = _detect(_Path(root))
        lines = [
            f"Current workspace: {info.path}",
            f"Project: {info.name} ({info.kind})",
        ]
        if info.git:
            lines.append(f"Git: yes{(' — branch ' + info.branch) if info.branch else ''}")
        else:
            lines.append("Git: no repository")
        if info.entries:
            lines.append("Top-level: " + ", ".join(info.entries[:24]))
        return "\n".join(lines)
    except Exception:
        return f"Current workspace: {root}"

SEARCH_SYSTEM_PROMPT = (
    "You are AXIOM. The web search results below were fetched in real time from "
    "the public web. Base your answer on them, cite the sources you used as "
    "[number] where relevant, and state clearly when the sources do not answer "
    "the question."
)

PAGE_SYSTEM_PROMPT = (
    "You are AXIOM. The user gave a link and the pages below were read in real "
    "time from the live web — this is the actual page content, not your memory. "
    "Answer strictly from it, quote concrete details, and say plainly if the "
    "page does not contain what was asked. Never claim you cannot open links."
)


@dataclass
class PassResult:
    """Accumulated output of one model pass."""

    content: str = ""
    thinking: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    #: Real time-to-first-token of this pass (measured, not estimated).
    ttft_ms: int | None = None
    #: Benchmark timestamps (perf_counter, seconds); used to build
    #: :class:`~axiom.core.performance.PerformanceMetrics`.
    http_started_at: float | None = None
    first_chunk_at: float | None = None
    first_visible_at: float | None = None
    last_token_at: float | None = None


class Agent:
    """Runs one generation cycle and yields structured events."""

    def __init__(
        self,
        client: OllamaClient,
        *,
        config: Config,
        registry: ToolRegistry,
        machine: GenerationStateMachine,
        web_tool: WebSearchTool | None = None,
        bus=None,
        trajectory=None,
    ) -> None:
        self._client = client
        self._config = config
        self._registry = registry
        self._machine = machine
        self._web_tool = web_tool
        # Harness-хуки (п.6/10): опциональны, старое поведение сохраняется.
        self._bus = bus
        self._trajectory = trajectory
        # Harness-интеграции (п.13/14/16): тоже опциональны.
        self._router = None
        self._catalog = None
        self._sandbox = None
        self._skills = None
        self._rules = None  # W4.5: RuleManager or None
        self._verifier = None
        self._permissions = None
        #: W2.1 Curated Memory: :class:`~axiom.core.memory.MemoryTools` or None.
        #: The agent only ever sees a budgeted slice via ``relevant()``.
        self._memory = None
        #: W4.11: the routing role of this agent — ``subagent``/``coding`` for a
        #: specialist, None for the session's own pass. A role only changes
        #: which configured provider/model answers, never what the agent does.
        self.route_role: str | None = None
        #: Role actually used for the current model pass (``search`` when the
        #: pass consumed web search or pasted pages).
        self._pass_role: str | None = None
        self.last_route: dict = {}
        self.last_verify: dict = {}
        self._max_rounds = MAX_TOOL_ROUNDS + (3 if config.workspace_tools_enabled else 0)
        self.last_sources: list[SourceItem] = []
        self.last_content = ""
        self.last_thinking = ""
        self.last_metrics: dict = {}
        self.last_stop_reason: str | None = None
        self.metrics: dict = {}
        #: Benchmark profile of the most recent run (set by :meth:`run`).
        self.perf: PerformanceMetrics | None = None
        #: Pages read because the user pasted their links, as (url, text).
        self._pasted_pages: list[tuple[str, str]] = []

    # ------------------------------------------------------------------ utils

    def _status(self, state: GenerationState, detail: str | None = None) -> StatusChange | None:
        """Emit a status only when the state machine allows the transition."""
        if not self._machine.can(state):
            return None
        self._machine.transition(state)
        return StatusChange(state=state, detail=detail)

    def _build_messages(self, history: list[dict], system: str) -> list[dict]:
        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        return messages

    def _think_param(self, model: ModelInfo, history: list[dict]) -> bool | str | None:
        """Resolve the real ``think`` request parameter for this request.

        Priority: explicit config value (bool or level string) → thinking_mode
        preset → per-request heuristic → model capability. Deterministic only:
        the level depends on the message history shape, never on an extra LLM
        classifier call. The Performance Engine corrects the level using the
        real TTFT / throughput measured on the previous run.
        """
        explicit = self._config.think
        if explicit is not None:
            return explicit
        metrics = self.last_metrics or {}
        return thinking_level(
            self._last_user_text(history),
            model_supports_thinking=model.supports("thinking") is True,
            mode=getattr(self._config, "thinking_mode", "auto"),
            budget=getattr(self._config, "router_budget", "balanced"),
            last_ttft_ms=metrics.get("ttft_ms"),
            last_tokens_per_second=metrics.get("tokens_per_second"),
        )

    def _tool_schemas(
        self, model: ModelInfo, user_text: str | None = None
    ) -> list[dict] | None:
        """Only offer tools this request plausibly needs (aggressive scope).

        The deterministic resolver (no extra model call) maps the request to
        the minimum category: an ordinary question gets zero tools, a file
        question gets the read tools, an edit gets read+edit, git gets the git
        tools, a terminal request gets ``run_command`` and a web request keeps
        the two web tools. Sandbox DENY-tools are never advertised at all.
        """
        if not self._config.web_search_enabled and not self._config.workspace_tools_enabled:
            return None
        if model.supports("tools") is not True:
            return None
        # External provider models are marked tool-capable by the bridge.  The
        # scope is request-driven, but a coding request must always receive the
        # real workspace tools even when the model name itself is unfamiliar.
        terminal_ok = self._config.terminal_enabled and self._config.access_mode != "read_only"
        scope = tool_scope(
            user_text or "",
            workspace=self._config.workspace_tools_enabled,
            terminal=terminal_ok,
            web=self._config.web_search_enabled,
        )
        if not scope:
            return None
        allowed: set[str] = set(scope)
        if not terminal_ok:
            # §34: verification tools spawn processes too — no terminal, no
            # test/lint/build commands advertised to the model.
            for name in ("run_command", "run_tests", "run_linter",
                         "build_project", "verify_changes"):
                allowed.discard(name)
        # Sandbox (п.13): DENY-тулы не рекламируем модели вообще.
        if self._sandbox is not None:
            allowed = {name for name in allowed if self._sandbox.allows(name)}
        schemas = [s for s in self._registry.schemas() if s["function"]["name"] in allowed]
        return schemas or None

    def _route_info(self, user_text: str) -> dict:
        """Model Router (п.16): какой маршрут выбран — для trajectory/UI."""
        if self._router is None:
            return {}
        role = self._pass_role or self.route_role
        try:
            if role:
                # W4.11: a specialist or a search pass is routed by role first.
                target = self._router.route_for_role(role, user_text, self._catalog)
            else:
                target = self._router.route(user_text, self._catalog)
        except Exception:
            return {}
        if target is None:
            return {}
        info = {"provider_id": target.provider_id, "model": target.model,
                "reason": target.reason}
        if role:
            info["role"] = role
        self.last_route = info
        if self._trajectory is not None:
            try:
                self._trajectory.append("router.route",
                                        f"{target.provider_id}/{target.model} ({target.reason})",
                                        data=info)
            except Exception:
                pass
        return info

    def _sandbox_decision(self, tool_name: str) -> str:
        if self._sandbox is None:
            return "auto"
        try:
            return self._sandbox.decide(tool_name)
        except Exception:
            return "ask"

    def _skill_blocks(self, user_text: str) -> list[str]:
        """Skills (п.14): авто-инжект подходящих skill-блоков в system."""
        if self._skills is None:
            return []
        try:
            hits = self._skills.resolve_for_task(user_text or "")
        except Exception:
            return []
        return [block for s in hits[:3] if (block := s.prompt_block())]

    @staticmethod
    def _int_or_none(value) -> int | None:
        """Pass real ints through, map anything else to ``None``."""
        return value if isinstance(value, int) else None

    @staticmethod
    def _metrics(metrics: dict, started: float, ttft_ms: int | None = None) -> dict:
        """Normalise Ollama metrics into UI-friendly values."""
        eval_count = metrics.get("eval_count")
        eval_duration = metrics.get("eval_duration")
        per_second = None
        if isinstance(eval_count, int) and isinstance(eval_duration, int) and eval_duration > 0:
            per_second = round(eval_count / (eval_duration / 1_000_000_000), 1)
        load_duration = metrics.get("load_duration")
        return {
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "tokens_out": eval_count if isinstance(eval_count, int) else None,
            "tokens_in": Agent._int_or_none(metrics.get("prompt_eval_count")),
            "tokens_per_second": per_second,
            "ttft_ms": ttft_ms,
            "load_ms": (
                round(load_duration / 1_000_000)
                if isinstance(load_duration, int) and load_duration > 0
                else None
            ),
        }

    # ------------------------------------------------------------- model pass

    async def _stream_pass(
        self,
        messages: list[dict],
        model: ModelInfo,
        *,
        think: bool | str | None,
        tools: list[dict] | None,
        result: PassResult,
    ) -> AsyncIterator[ChatEvent]:
        """Stream one real model pass, emitting reasoning/content deltas."""
        if self._bus is not None:
            try:
                self._bus.emit("model.request", {"model": model.name, "messages": len(messages)})
            except Exception:
                pass
        stream_started = time.perf_counter()
        saw_thinking = False
        saw_content = False
        first_token_at: float | None = None
        result.http_started_at = stream_started
        options: dict = {}
        if self._config.temperature is not None:
            options["temperature"] = self._config.temperature
        num_ctx = getattr(self._config, "num_ctx", None)
        if isinstance(num_ctx, int):
            options["num_ctx"] = num_ctx
        num_predict = getattr(self._config, "num_predict", None)
        if isinstance(num_predict, int):
            options["num_predict"] = num_predict
        call_kwargs: dict = {
            "think": think,
            "tools": tools,
            "options": options or None,
            "keep_alive": getattr(self._config, "keep_alive", None),
        }
        # W4.11: a role rule is only honoured by a client that resolves roles
        # (ProviderChatClient). A plain OllamaClient keeps the exact call shape
        # it always had, so existing adapters and tests are untouched.
        role = self._pass_role or self.route_role
        if role and getattr(self._client, "accepts_role", False):
            call_kwargs["role"] = role
        async for chunk in self._client.chat(model.name, messages, **call_kwargs):
            if first_token_at is None and (chunk.thinking or chunk.content or chunk.tool_calls):
                first_token_at = time.perf_counter()
                result.first_chunk_at = first_token_at
                result.ttft_ms = int((first_token_at - stream_started) * 1000)
            if chunk.thinking:
                if not saw_thinking:
                    saw_thinking = True
                    status = self._status(GenerationState.THINKING)
                    if status:
                        yield status
                result.thinking += chunk.thinking
                result.last_token_at = time.perf_counter()
                yield ReasoningChunk(text=chunk.thinking)
            if chunk.content:
                if not saw_content:
                    saw_content = True
                    if result.first_visible_at is None:
                        result.first_visible_at = time.perf_counter()
                    status = self._status(GenerationState.RECEIVING)
                    if status:
                        yield status
                result.content += chunk.content
                result.last_token_at = time.perf_counter()
                yield ContentChunk(text=chunk.content)
            if chunk.tool_calls:
                result.tool_calls.extend(chunk.tool_calls)
                result.last_token_at = time.perf_counter()
            if chunk.metrics:
                result.metrics = chunk.metrics
            if chunk.done:
                if self._bus is not None:
                    try:
                        self._bus.emit("model.response",
                                       {"model": model.name, "metrics": dict(chunk.metrics or {})})
                    except Exception:
                        pass
                if self._trajectory is not None:
                    try:
                        self._trajectory.append("model.response", f"{model.name} done",
                                                data={"metrics": dict(chunk.metrics or {})})
                    except Exception:
                        pass
                break

    async def _execute_tool(
        self, call: ToolCallRequest
    ) -> AsyncIterator[ChatEvent]:
        """Execute a model-requested tool and report the real outcome."""
        if call.name == WEB_SEARCH_TOOL:
            # The UI shows this detail to the user — it must be the real
            # query, not the tool name.
            detail = str(call.arguments.get("query") or call.name)
        elif call.name == FETCH_URL_TOOL:
            detail = str(call.arguments.get("url") or call.name)
        elif call.name == "run_command":
            detail = str(call.arguments.get("command") or call.name)
        elif call.name in ("read_file", "write_file", "edit_file", "delete_file"):
            detail = str(call.arguments.get("path") or call.name)
        elif call.name == "list_files":
            detail = str(call.arguments.get("path") or ".")
        elif call.name in ("search_text", "search_files"):
            detail = str(call.arguments.get("pattern") or call.arguments.get("glob") or call.name)
        else:
            detail = call.name
        status = self._status(
            GenerationState.SEARCHING
            if call.name == WEB_SEARCH_TOOL
            else GenerationState.TOOL_CALL,
            detail=detail,
        )
        if status:
            yield status
        yield ToolCallEvent(name=call.name, arguments=call.arguments)
        if self._bus is not None:
            try:
                self._bus.emit("tool.before", {"tool": call.name, "arguments": call.arguments})
            except Exception:
                pass
        # Sandbox-enforce (п.13): DENY блокирует ДО исполнения хендлера.
        if self._sandbox_decision(call.name) == "deny":
            from axiom.core.tools.base import ToolResult as _TR

            result = _TR(name=call.name, ok=False,
                         error=f"Blocked by sandbox policy: {call.name} is denied.")
        else:
            if self._permissions is None:
                result = await self._registry.execute(call.name, call.arguments)
            else:
                permission = self._registry.permission_for(call.name, call.arguments)
                try:
                    approved = await self._permissions.decide(
                        call.name, call.arguments, permission
                    )
                except Exception as exc:
                    result = ToolResult(
                        name=call.name,
                        ok=False,
                        error=f"Permission check failed: {exc}",
                    )
                else:
                    if approved:
                        result = await self._registry.execute(
                            call.name, call.arguments, approved=True
                        )
                    else:
                        result = ToolResult(
                            name=call.name,
                            ok=False,
                            error="Permission denied by the current permission mode.",
                            data={"permission": permission.value},
                        )
        if self._bus is not None:
            try:
                self._bus.emit("tool.after", {"tool": result.name, "ok": result.ok,
                                              "duration_ms": result.duration_ms})
            except Exception:
                pass
        if self._trajectory is not None:
            try:
                self._trajectory.append("tool.call", f"{call.name} {detail}",
                                        data={"tool": call.name, "arguments": call.arguments,
                                              "ok": result.ok, "duration_ms": result.duration_ms})
            except Exception:
                pass
        yield ToolResultEvent(
            name=result.name,
            ok=result.ok,
            content=result.content if result.ok else "",
            error=result.error,
            duration_ms=result.duration_ms,
        )
        if call.name == WEB_SEARCH_TOOL and result.ok:
            query = str(call.arguments.get("query") or "")
            async for event in self._read_sources(query):
                yield event

    async def _read_sources(self, query: str) -> AsyncIterator[ChatEvent]:
        """Read the top sources of a real search — no simulation."""
        if self._web_tool is None:
            return
        sources = list(self._web_tool.last_sources)
        self.last_sources = [
            SourceItem(index=i, title=s.title, url=s.url, snippet=s.snippet)
            for i, s in enumerate(sources, start=1)
        ]
        if self.last_sources:
            yield SearchResultEvent(query=query, sources=self.last_sources)
        read_count = min(self._config.search_read_sources, len(sources))
        for source in sources[:read_count]:
            status = self._status(GenerationState.TOOL_CALL, detail="read_source")
            if status:
                yield status
            result = await self._registry.execute("fetch_url", {"url": source.url})
            yield ToolResultEvent(
                name="fetch_url",
                ok=result.ok,
                content=result.content[:1500] if result.ok else "",
                error=result.error,
                duration_ms=result.duration_ms,
            )

    #: Matches http(s) links a user may paste into a message.
    _URL_RE = re.compile(r"https?://[^\s<>\"'`)\]]+")

    @classmethod
    def _urls_in_text(cls, text: str) -> list[str]:
        """Links found in a message, de-duplicated, order preserved."""
        found: list[str] = []
        for raw in cls._URL_RE.findall(text or ""):
            url = raw.rstrip(".,;:!?")
            if url and url not in found:
                found.append(url)
        return found

    async def _read_pasted_links(self, history: list[dict]) -> AsyncIterator[ChatEvent]:
        """Read the pages a user linked, so answers come from the real content."""
        self._pasted_pages = []
        if self._web_tool is None or not self._config.web_search_enabled:
            return
        urls = self._urls_in_text(self._last_user_text(history))[:MAX_AUTO_FETCH]
        for url in urls:
            page = ""
            async for event in self._execute_tool(
                ToolCallRequest(name=FETCH_URL_TOOL, arguments={"url": url})
            ):
                if (
                    isinstance(event, ToolResultEvent)
                    and event.name == FETCH_URL_TOOL
                    and event.ok
                ):
                    page = event.content
                yield event
            if page:
                self._pasted_pages.append((url, page))
        if self._pasted_pages:
            self.last_sources = [
                SourceItem(
                    index=index,
                    title=url,
                    url=url,
                    snippet=" ".join(text.split())[:200],
                )
                for index, (url, text) in enumerate(self._pasted_pages, start=1)
            ]
            yield SearchResultEvent(query=urls[0], sources=self.last_sources)

    # ------------------------------------------------------------- agent loop

    def attach_harness(self, bus=None, trajectory=None, router=None, catalog=None,
                       sandbox=None, skills=None, verifier=None, permissions=None,
                       memory=None, rules=None) -> None:
        """Подключить EventBus + Trajectory + Router + Sandbox + Skills (п.6/10/13/14/16)."""
        self._bus = bus if bus is not None else self._bus
        self._trajectory = trajectory if trajectory is not None else self._trajectory
        if router is not None:
            self._router = router
        if catalog is not None:
            self._catalog = catalog
        if sandbox is not None:
            self._sandbox = sandbox
        if skills is not None:
            self._skills = skills
        if rules is not None:
            # W4.5: workspace rule manager — global/project rules join the
            # base system prompt, directory/task rules join per task.
            self._rules = rules
        if verifier is not None:
            self._verifier = verifier
        if permissions is not None:
            self._permissions = permissions
        if memory is not None:
            # W2.1: budgeted memory slice for the system prompt. The full
            # store never enters the context — only ``relevant()`` output.
            self._memory = memory

    async def run(
        self,
        history: list[dict],
        model: ModelInfo,
        *,
        force_search: bool = False,
        search_query: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Run a full generation cycle, yielding every real step as an event."""
        started = time.perf_counter()
        self.last_sources = []
        self.last_content = ""
        self.last_thinking = ""
        self.last_metrics: dict = {}
        self.last_stop_reason = None
        self._pasted_pages = []
        # W4.11: the routing role of this run until a search pass overrides it.
        self._pass_role = self.route_role
        last_ttft: int | None = None

        from axiom.core.prompt_builder import (
            MINI_BUDGET_CHARS,
            WORKSPACE_RULES,
            PromptLayers,
            build_system_prompt,
            select_variant,
        )

        user_seed = self._last_user_text(history) or ""
        if self._config.system_prompt:
            # A user's custom prompt wins outright — the builder only owns
            # the default policy assembly, never a user's words.
            system = self._config.system_prompt
        else:
            variant = select_variant(
                user_seed,
                mode=getattr(self._config, "thinking_mode", "auto"),
                budget=getattr(self._config, "router_budget", "balanced"),
            )
            # §4: every request carries the real workspace path (path + kind +
            # top-level layout, never the whole project). After a project
            # switch this block points at the NEW folder.
            block = (
                workspace_context_block(self._config.workspace_root)
                if self._config.workspace_tools_enabled
                else ""
            )
            # W2.1: a small budgeted slice of curated memory (never the full
            # store). Only normal/sensitive items exist on disk; the block
            # tells the model where each item came from so it can verify.
            memory_block = ""
            if self._memory is not None:
                try:
                    memory_items = self._memory.relevant(user_seed, budget=5)
                except Exception:
                    memory_items = []
                if memory_items:
                    lines = "\n".join(
                        f"- [{item.scope}/{item.category}] {item.content}"
                        for item in memory_items
                    )
                    memory_block = (
                        "Relevant memory from this user (verify before "
                        f"relying on it):\n{lines}"
                    )
            rules = WORKSPACE_RULES if self._config.workspace_tools_enabled else ""
            workspace_text = f"{rules}\n\n{block}".strip() if (rules or block) else ""
            # W4.5: static workspace rules (global + project AXIOM.md). They
            # occupy the protected project_rules layer — never dropped by the
            # budget fight; directory/task rules join per task instead.
            project_rules_text = ""
            if self._rules is not None and self._config.workspace_tools_enabled:
                try:
                    project_rules_text = self._rules.project_rules_block()
                except Exception:
                    project_rules_text = ""
            base_layers = PromptLayers(
                user_text=user_seed,
                variant=variant,
                budget_chars=(MINI_BUDGET_CHARS if variant == "mini" else 12000),
                workspace=workspace_text,
                project_rules=project_rules_text,
                memory=memory_block,
                skill_blocks=self._skill_blocks(user_seed),
            )
            system = build_system_prompt(base_layers)
            self.last_prompt_variant = variant
            self.last_prompt_chars = len(system)
        if force_search:
            if not self._config.web_search_enabled or self._web_tool is None:
                from axiom.core.events import ErrorEvent

                yield ErrorEvent(
                    message="Web Search unavailable",
                    kind="search_unavailable",
                    hint="Enable web search in settings to use it.",
                )
            else:
                query = (search_query or "").strip() or self._last_user_text(history)
                search_block = ""
                search_failed = False
                async for event in self._execute_tool(
                    ToolCallRequest(name=WEB_SEARCH_TOOL, arguments={"query": query})
                ):
                    if isinstance(event, ToolResultEvent) and event.name == WEB_SEARCH_TOOL:
                        if event.ok:
                            search_block = event.content
                        else:
                            search_failed = True
                    yield event
                if search_block:
                    # W4.11: a pass that answers from live search results is the
                    # "search" role, so a cheap model can be pinned to it.
                    self._pass_role = "search"
                    # Keep the configured system prompt and append the search
                    # context — a user's custom prompt must survive (same
                    # behaviour as the pasted-links branch below).
                    system = f"{system}\n\n{SEARCH_SYSTEM_PROMPT}\n\nSearch results:\n{search_block}"
                elif search_failed:
                    system = (
                        f"{DEFAULT_SYSTEM_PROMPT}\n\nLive web search was attempted but failed. "
                        "Answer from your own knowledge and state clearly that live sources "
                        "were unavailable."
                    )
        elif self._config.web_search_enabled and self._web_tool is not None:
            # A pasted link must be read for real. Small local models often skip
            # tools entirely, so the agent fetches the page instead of waiting.
            async for event in self._read_pasted_links(history):
                yield event
            pages = self._pasted_pages
            if pages:
                # W4.11: reading pasted links is the same "search" role as a
                # live search — the answer comes from fetched external text.
                self._pass_role = "search"
                # Keep the configured system prompt and append the real page
                # content — a user's custom prompt must survive.
                page_block = "\n\n".join(
                    f"Page {index} — {url}\n{text[:MAX_PAGE_CHARS]}"
                    for index, (url, text) in enumerate(pages, start=1)
                )
                system = f"{system}\n\n{PAGE_SYSTEM_PROMPT}\n\nLive pages:\n{page_block}"

        messages = self._build_messages(history, system)
        think = self._think_param(model, history)
        user_text = self._last_user_text(history)
        # W4.5: task-relevant rule delta (directory rules for touched paths +
        # user @-mentioned rule files). Global/project rules are already in
        # the base system prompt; an explicit mention can shadow them (task
        # scope wins conflicts deterministically).
        if self._rules is not None and not self._config.system_prompt \
                and self._config.workspace_tools_enabled:
            try:
                rules_delta = self._rules.merged_rules(user_text or "")
            except Exception:
                rules_delta = ""
            if rules_delta:
                system = f"{system}\n\nRules relevant to this task:\n{rules_delta}"
                messages = self._build_messages(history, system)
                if self._trajectory is not None:
                    try:
                        self._trajectory.append(
                            "context.rules", "Task-relevant rules attached",
                            data={"chars": len(rules_delta)})
                    except Exception:
                        pass
        # Performance Engine: quick (one pass, no tools) vs agent (tool loop).
        # Deterministic, recorded in the trajectory — never a hidden guess.
        mode = classify_mode(user_text or "")
        if self._trajectory is not None:
            try:
                self._trajectory.append(
                    "policy.mode",
                    f"mode={mode} complexity={complexity_of(user_text or '', context_messages=len(history))}",
                    data={"mode": mode, "context_messages": len(history)},
                )
            except Exception:
                pass
        # Harness: router-решение + skills-инжект пишутся в trajectory. Сами
        # skill-блоки уже вошли в system через PromptLayers — здесь только учёт.
        self._route_info(user_text)
        for block in self._skill_blocks(user_text):
            if self._trajectory is not None:
                try:
                    self._trajectory.append("context.skill", block.splitlines()[0][:120],
                                            data={"block": block[:2000]})
                except Exception:
                    pass
            messages = self._build_messages(history, system)
        rounds = 0
        forced_edit_once = False
        seen_tool_calls: set[str] = set()
        tool_rounds = 0
        tool_total_s = 0.0
        prompt_built_at = time.perf_counter()
        first_pass = True
        first_http_at: float | None = None
        first_chunk_at: float | None = None
        first_visible_at: float | None = None
        last_token_at: float | None = None
        while True:
            tools = self._tool_schemas(model, user_text)
            status = self._status(GenerationState.CONNECTING, detail=model.name)
            if status:
                yield status

            result = PassResult()
            async for event in self._stream_pass(
                messages, model, think=think, tools=tools, result=result
            ):
                yield event
            self.last_content += result.content
            self.last_thinking += result.thinking
            if result.metrics:
                self.last_metrics = result.metrics
            last_ttft = result.ttft_ms if result.ttft_ms is not None else last_ttft
            if first_pass and result.http_started_at is not None:
                first_http_at = result.http_started_at
            if first_chunk_at is None and result.first_chunk_at is not None:
                first_chunk_at = result.first_chunk_at
            if first_visible_at is None and result.first_visible_at is not None:
                first_visible_at = result.first_visible_at
            if result.last_token_at is not None and (last_token_at is None or
                                                     result.last_token_at >= last_token_at):
                last_token_at = result.last_token_at
            first_pass = False

            if not result.tool_calls:
                self.last_stop_reason = "completed"
                if (not forced_edit_once and rounds < self._max_rounds and any(
                    marker in user_text.lower()
                    for marker in (
                        "сделай", "доработа", "улучш", "реализуй", "исправ",
                        "добавь", "измени", "создай", "напиши", "перенеси",
                        "implement", "fix", "add", "change", "create", "write",
                        "modify", "refactor", "update",
                    )
                )):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "The user requested a project change. Do not describe a plan. "
                                "Use edit_file or write_file now. First read the real target file; "
                                "never invent a path. If a path does not exist, use list_files or "
                                "search_files and recover from that result."
                            ),
                        }
                    )
                    rounds += 1
                    forced_edit_once = True
                    continue
                break
            if rounds >= self._max_rounds:
                self.last_stop_reason = "tool_round_limit"
                break
            rounds += 1

            if result.content.strip():
                messages.append({"role": "assistant", "content": result.content})
            for call in result.tool_calls:
                signature = repr((call.name, sorted(call.arguments.items())))
                if signature in seen_tool_calls:
                    tool_error = "Duplicate tool call suppressed; the same call already ran in this turn."
                    yield ToolResultEvent(
                        name=call.name, ok=False, content="", error=tool_error,
                    )
                    messages.append({"role": "system", "content": f"Tool result ({call.name}): ERROR: {tool_error}"})
                    continue
                seen_tool_calls.add(signature)
                tool_block = ""
                tool_error = ""
                tool_call_started = time.perf_counter()
                async for event in self._execute_tool(call):
                    if isinstance(event, ToolResultEvent):
                        if event.ok:
                            tool_block = event.content
                        else:
                            tool_error = event.error or "Tool failed"
                    yield event
                tool_total_s += time.perf_counter() - tool_call_started
                tool_rounds += 1
                if tool_block or tool_error:
                    messages.append(
                        {
                            "role": "system",
                            "content": f"Tool result ({call.name}):\n"
                                       f"{tool_block or 'ERROR: ' + tool_error}",
                        }
                    )

        self.metrics = self._metrics(self.last_metrics, started, ttft_ms=last_ttft)
        self.perf = self._build_perf(
            raw_metrics=self.last_metrics,
            started=started,
            prompt_built_at=prompt_built_at,
            http_at=first_http_at,
            first_chunk_at=first_chunk_at,
            first_visible_at=first_visible_at,
            last_token_at=last_token_at,
            model=model,
            think=think,
            tools=bool(tools),
            context_chars=sum(len(str(m.get("content", ""))) for m in messages),
            reasoning_chars=len(self.last_thinking),
            answer_chars=len(self.last_content),
            tool_rounds=tool_rounds,
            tool_s=tool_total_s,
        )

    @staticmethod
    def _build_perf(
        *,
        raw_metrics: dict,
        started: float,
        prompt_built_at: float,
        http_at: float | None,
        first_chunk_at: float | None,
        first_visible_at: float | None,
        last_token_at: float | None,
        model: ModelInfo,
        think: bool | str | None,
        tools: bool,
        context_chars: int,
        reasoning_chars: int,
        answer_chars: int,
        tool_rounds: int,
        tool_s: float,
    ) -> PerformanceMetrics:
        """Assemble a :class:`PerformanceMetrics` from raw timestamps."""
        finished = time.perf_counter()

        def _ms(timestamp: float | None) -> float | None:
            return round((timestamp - started) * 1000, 2) if timestamp is not None else None

        perf = PerformanceMetrics.from_ollama(
            raw_metrics or {},
            model=model.name,
            think=str(think) if think is not None else None,
            tools=tools,
            context_chars=context_chars,
            reasoning_chars=reasoning_chars,
            answer_chars=answer_chars,
            tool_rounds=tool_rounds,
            tool_ms=round(tool_s * 1000, 2) if tool_rounds else None,
            prompt_built_ms=_ms(prompt_built_at),
            http_start_ms=_ms(http_at),
            first_chunk_ms=_ms(first_chunk_at),
            first_visible_ms=_ms(first_visible_at),
            last_token_ms=_ms(last_token_at),
            finished_ms=round((finished - started) * 1000, 2),
        )
        return perf

    @staticmethod
    def _last_user_text(history: list[dict]) -> str:
        for message in reversed(history):
            if message.get("role") == "user" and message.get("content"):
                return str(message["content"])
        return ""
