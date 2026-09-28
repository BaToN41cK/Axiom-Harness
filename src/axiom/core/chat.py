"""ChatSession — the public entry point of the AXIOM core.

Frontends interact with the engine exclusively through this class:

* :meth:`ChatSession.startup` — real Ollama/model probing for the splash screen.
* :meth:`ChatSession.send` — returns an ``AsyncIterator[ChatEvent]``.
* :meth:`ChatSession.cancel` — stop the in-flight generation.
* :meth:`ChatSession.switch_model`, :meth:`ChatSession.new_conversation`, ...

No UI framework is imported anywhere in this module.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Only for static typing: the bridge owns the interactive GUI shell
    # lifecycle, and a runtime import here would be unused in the core.
    from axiom.core.tools.shell import ShellSession


from axiom.core.agent import Agent
from axiom.core.config import Config
from axiom.core.errors import (
    AxiomError,
    SearchUnavailableError,
)
from axiom.core.events import (
    ChatEvent,
    ContentChunk,
    Done,
    ErrorEvent,
    Message,
    ReasoningChunk,
    StatusChange,
    ToolCallEvent,
    ToolResultEvent,
)
from axiom.core.history import Conversation, HistoryStore
from axiom.core.mentions import expand_mentions, mentioned_files
from axiom.core.models import ModelInfo, ModelRegistry
from axiom.core.ollama import OllamaClient
from axiom.core.profiles import ProfileManager
from axiom.core.search.multi import build_search_provider
from axiom.core.search.provider import SearchProvider
from axiom.core.state import GenerationState
from axiom.core.state_machine import GenerationStateMachine
from axiom.core.tasks import Task, TaskRunner, TaskState, TaskStore
from axiom.core.tools.base import ToolPermission
from axiom.core.tools.filesystem import WORKSPACE_TOOLS, WorkspaceTools
from axiom.core.tools.git_tools import (
    GIT_BRANCH_TOOL,
    GIT_DIFF_TOOL,
    GIT_LOG_TOOL,
    GIT_STATUS_TOOL,
    GitTools,
)
from axiom.core.tools.project_tools import INSPECT_PROJECT_TOOL, ProjectTools
from axiom.core.tools.registry import ToolRegistry
from axiom.core.tools.terminal import RUN_COMMAND_TOOL, TerminalTool, classify_command
from axiom.core.tools.verify_tools import VERIFY_TOOL_NAMES, VerificationTools
from axiom.core.tools.web_search import WebSearchTool
from axiom.core.workspace import ProjectInfo, WorkspaceManager, detect_project

#: How many previous messages are sent back to the model by default.
#: Overridable (and runtime-changeable) via ``Config.context_messages``.
CONTEXT_MESSAGES = 20

#: Every tool that touches the workspace filesystem. Global Chat (no project)
#: drops exactly these from the registry; :meth:`set_workspace` puts them back.
WORKSPACE_TOOL_NAMES: frozenset[str] = frozenset(WORKSPACE_TOOLS) | {
    GIT_STATUS_TOOL,
    GIT_DIFF_TOOL,
    GIT_LOG_TOOL,
    GIT_BRANCH_TOOL,
    INSPECT_PROJECT_TOOL,
    RUN_COMMAND_TOOL,
} | VERIFY_TOOL_NAMES


@dataclass
class StartupReport:
    """Result of the real startup probe (drives the splash screen)."""

    ollama_available: bool = False
    version: str | None = None
    models: list[ModelInfo] = field(default_factory=list)
    selected: ModelInfo | None = None
    error: str | None = None
    hint: str | None = None


class ChatSession:
    """Owns the conversation, the agent loop and the local persistence."""

    def __init__(
        self,
        config: Config | None = None,
        *,
        client: OllamaClient | None = None,
        registry: ModelRegistry | None = None,
        history_store: HistoryStore | None = None,
        provider: SearchProvider | None = None,
    ) -> None:
        self.config = config or Config.load()
        # A workspace can disappear between runs (for example, pytest's
        # temporary project). Never keep Explorer and filesystem tools pointed
        # at a stale path; use the actual launch directory instead.
        if self.config.workspace_root:
            configured_root = Path(self.config.workspace_root).expanduser()
            if not configured_root.exists() or not configured_root.is_dir():
                self.config.workspace_root = None
        self.client = client or OllamaClient(
            self.config.ollama_url, keep_alive=self.config.keep_alive
        )
        self.registry = registry or ModelRegistry(self.client)
        self.history_store = history_store if history_store is not None else HistoryStore(
            limit=self.config.history_limit if self.config.save_history else None
        )
        self.provider = provider or build_search_provider(
            self.config.search_provider, timeout=self.config.search_timeout
        )
        self.web_tool = WebSearchTool(
            self.provider,
            max_sources=self.config.search_max_sources,
            local_only=self.config.local_only,
        )
        self.tools = ToolRegistry()
        self.web_tool.register(self.tools)
        # W2.1 Curated Memory: user-controlled durable facts. Global store plus
        # a project store when a workspace root is configured; the model only
        # ever touches memory through the three memory tools.
        from axiom.core.memory import MemoryStore, MemoryTools

        self.memory_store = MemoryStore()
        project_root: Path | None = None
        if self.config.workspace_root:
            candidate = Path(self.config.workspace_root).expanduser()
            if candidate.exists():
                project_root = candidate
        self.memory_project_store = (
            MemoryStore(scope="project", project_root=project_root) if project_root else None
        )
        self.memory_tools = MemoryTools(self.memory_store, self.memory_project_store)
        self.memory_tools.register(self.tools)
        # W2.2 Knowledge Base: named local collections (SQLite/FTS5 + optional
        # Ollama embeddings). The model reaches them only through three tools.
        from axiom.core.knowledge import KnowledgeManager, KnowledgeTools

        self.knowledge = KnowledgeManager(local_only=self.config.local_only)
        if self.knowledge.embed_model is None and self.config.knowledge_embed_model:
            self.knowledge.configure_embedder(
                self.config.ollama_url, self.config.knowledge_embed_model
            )
        self.knowledge_tools = KnowledgeTools(self.knowledge)
        self.knowledge_tools.register(self.tools)
        # §8 Tool Layer: file tools + terminal tools + project tools +
        # git tools + web tools — all behind the permission system (§9-§12).
        # Workspace tools always exist: an explicit ``workspace_root`` wins,
        # otherwise they are rooted at the launch directory
        # (``default_workspace_root`` — the Tauri shell exports
        # ``AXIOM_WORKSPACE``; CLI/TUI fall back to the current directory).
        # A real project switch happens via :meth:`set_workspace`.
        self.workspace_tools: WorkspaceTools | None = None
        self.git_tools = None
        self.project_tools = None
        if self.config.workspace_tools_enabled:
            root = (
                Path(self.config.workspace_root).expanduser()
                if self.config.workspace_root
                else None  # WorkspaceTools resolves None -> default_workspace_root()
            )
            self.workspace_tools = WorkspaceTools(root, access_mode=self.config.access_mode)
            self.workspace_tools.register(self.tools)
            from axiom.core.tools.git_tools import GitTools
            from axiom.core.tools.project_tools import ProjectTools

            self.git_tools = GitTools(root)
            self.git_tools.register(self.tools)
            self.project_tools = ProjectTools(root)
            self.project_tools.register(self.tools)
        self.terminal: TerminalTool | None = None
        if self.config.workspace_tools_enabled and self.config.terminal_enabled:
            self.terminal = TerminalTool(
                root=Path(self.config.workspace_root).expanduser()
                if self.config.workspace_root
                else None,
                enabled=self.config.access_mode != "read_only",
            )
            self.terminal.register(self.tools)
        # §34 Verification tools: fixed test/lint/build commands. They spawn
        # processes, so they follow the terminal's enable flag exactly.
        self.verify_tools: VerificationTools | None = None
        if self.config.workspace_tools_enabled and self.config.terminal_enabled:
            self.verify_tools = VerificationTools(
                root=Path(self.config.workspace_root).expanduser()
                if self.config.workspace_root
                else None,
                enabled=self.config.access_mode != "read_only",
            )
            self.verify_tools.register(self.tools)
        self.workspaces = WorkspaceManager()
        if self.config.workspace_root:
            self.workspaces.remember(Path(self.config.workspace_root))
        self.machine = GenerationStateMachine()
        self.agent = Agent(
            self.client,
            config=self.config,
            registry=self.tools,
            machine=self.machine,
            web_tool=self.web_tool,
        )
        self.conversation = Conversation(model=self.config.model)
        self.active_model: ModelInfo | None = None
        self.last_metrics: dict = {}
        self._task: asyncio.Task | None = None
        self.active_task: Task | None = None
        self.active_task_runner: TaskRunner | None = None
        #: Fire-and-forget background model warm-up task. Created by the
        #: desktop bridge (``startup`` / ``set_model`` / ``warmup``); the
        #: session only keeps a reference so it can be awaited/cancelled.
        self.core_warmup_task: asyncio.Task[None] | None = None
        #: Interactive shell session owned by the GUI terminal panel
        #: (managed entirely by the desktop bridge; None in TUI/CLI).
        self.gui_shell: ShellSession | None = None
        #: Profile manager — system prompt profiles
        self.profiles = ProfileManager()
        # --- Harness (п.1-5): провайдеры, каталог моделей, агенты ---
        from axiom.core.agents import AgentRegistry
        from axiom.core.providers.catalog import ModelCatalog
        from axiom.core.providers.manager import ProviderManager

        self.provider_manager = ProviderManager()
        self.model_catalog = ModelCatalog()
        self.agent_registry = AgentRegistry()
        # --- Harness (п.6-13): bus, trajectory, orchestrator, context, verify ---
        from axiom.core.bus import EventBus
        from axiom.core.context_engine import ContextEngine
        from axiom.core.mcp import MCPManager
        from axiom.core.orchestrator import Orchestrator
        from axiom.core.parallel import run_parallel as _parallel_runner
        from axiom.core.plugins import PluginManager, PluginRegistry
        from axiom.core.presets import PresetStore, detect_mode
        from axiom.core.project_index import ProjectMemory
        from axiom.core.router import ModelRouter, RouterConfig
        from axiom.core.sandbox import Sandbox
        from axiom.core.skills import SkillRegistry
        from axiom.core.trajectory import Trajectory
        from axiom.core.trajectory_store import TrajectoryStore
        from axiom.core.verify import VerificationLoop

        self.bus = EventBus()
        self.trajectory = Trajectory(actor="orchestrator")
        self.trajectory_store = TrajectoryStore()
        self.orchestrator = Orchestrator(agents=self.agent_registry, bus=self.bus)
        self.context_engine = ContextEngine()
        self.verifier = VerificationLoop(runner=self._verification_runner)
        self.sandbox = Sandbox()
        from axiom.core.permissions import PermissionManager

        self.permissions = PermissionManager(config=self.config)
        self._active_preset_skills: set[str] = set()
        self._loaded_plugin_skills: dict[str, set[str]] = {}
        # --- Harness (п.14-22): skills, router, mcp, plugins, presets ---
        self.skills = SkillRegistry()
        self.router = ModelRouter(RouterConfig())
        self._configure_router_from_config()
        self.mcp = MCPManager()
        self.plugins = PluginRegistry()
        self.plugin_manager = PluginManager(registry=self.plugins)
        self.presets = PresetStore()
        self._parallel_runner = _parallel_runner
        self._detect_mode = detect_mode
        self._project_memory = None
        self._verifying = False
        self._checkpoint = None
        self._checkpointed = False
        #: Runtime mode (п.33-34) — ``code-agent`` включает PTC-исполнение.
        self._mode = "chat"
        self._code_mode = False
        try:
            from pathlib import Path as _Path

            root = self.config.workspace_root
            if root:
                self._project_memory = ProjectMemory(_Path(root).expanduser())
        except Exception:
            self._project_memory = None
        self.agent.attach_harness(bus=self.bus, trajectory=self.trajectory,
                                  router=self.router, catalog=self.model_catalog,
                                  sandbox=self.sandbox, skills=self.skills,
                                  verifier=self.verifier, permissions=self.permissions,
                                  memory=self.memory_tools)
        # All providers expose the same normalized stream to Agent.  Ollama
        # remains the default, while a configured router_primary selects the
        # external provider for the real chat path.
        from axiom.core.providers.runtime import ProviderChatClient

        self.provider_client = ProviderChatClient(
            self.provider_manager, self.router,
            default_provider="ollama", default_model=self.config.model,
            ollama_client=self.client,
        )
        self.agent._client = self.provider_client

    async def _verification_runner(self, command: str, step: str) -> dict:
        """Run a verification command through the real workspace terminal."""
        if self.terminal is None or not self.terminal.enabled:
            return {"ok": False, "output": "Terminal is disabled for the current workspace"}
        result = await self.terminal._run(command)
        return {
            "ok": result.ok,
            "output": result.content if result.ok else result.error,
        }

    def _configure_router_from_config(self) -> None:
        """Собрать RouterConfig из Config (п.16-17): primary + fallback chain."""
        from axiom.core.router import RouteTarget

        raw = getattr(self.config, "router_primary", None)
        primary = None
        if isinstance(raw, dict) and raw.get("provider_id") and raw.get("model"):
            primary = RouteTarget(str(raw["provider_id"]), str(raw["model"]), "configured")
        chain: list[RouteTarget] = []
        for item in getattr(self.config, "router_fallbacks", None) or []:
            if isinstance(item, dict) and item.get("provider_id") and item.get("model"):
                chain.append(RouteTarget(str(item["provider_id"]), str(item["model"]), "fallback"))
        self.router.config.primary = primary
        self.router.config.fallbacks = chain
        self.router.config.enabled = bool(getattr(self.config, "router_enabled", True))
        self.router.config.budget = str(getattr(self.config, "router_budget", "balanced"))

    async def _load_mcp_servers(self) -> list[str]:
        """Зарегистрировать MCP-тулы из ``Config.mcp_servers`` (п.15)."""
        entries = getattr(self.config, "mcp_servers", None) or []
        if not entries:
            return []
        for item in entries:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            command = item.get("command")
            if name and isinstance(command, list) and command:
                self.mcp.add_server(name, [str(c) for c in command])
        return await self.mcp.register_all(self.tools)

    # ------------------------------------------------------ harness (п.20-22)

    def memory_rows(self) -> list[dict]:
        """Memory items as UI rows (project store first, then global).

        W2.1: the frontend only ever renders this projection — editing and
        deletion go through :meth:`memory_forget` / :meth:`memory_edit`.
        """
        rows: list[dict] = []
        seen: set[str] = set()
        for store in self.memory_tools.stores():
            for item in store.list(limit=200):
                if item.id in seen:
                    continue
                seen.add(item.id)
                rows.append(
                    {
                        "id": item.id,
                        "scope": item.scope,
                        "category": item.category,
                        "content": item.content,
                        "tags": list(item.tags),
                        "updated_at": item.updated_at,
                    }
                )
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        return rows

    def memory_forget(self, item_id: str) -> bool:
        """Delete a memory item (user action from Desktop/TUI, not the model)."""
        return any(store.remove(item_id) for store in self.memory_tools.stores())

    def memory_edit(self, item_id: str, content: str) -> bool:
        """Edit an existing memory item's content in place (user action)."""
        cleaned = " ".join((content or "").split())
        if not cleaned or len(cleaned) > 2000:
            return False
        for store in self.memory_tools.stores():
            item = store.get(item_id)
            if item is None:
                continue
            if item.category == "banned":
                return False
            item.content = cleaned
            store.add(item)
            return True
        return False

    def memory_write_for_user(
        self, content: str, *, category: str = "normal", scope: str = "global",
        tags: list[str] | None = None,
    ) -> str | None:
        """Persist a memory item at the user's explicit request (UI path).

        Returns the new item id, or ``None`` when the write was rejected
        (banned/empty/too long) — banned content never reaches disk.
        """
        cleaned = " ".join((content or "").split())
        if not cleaned or len(cleaned) > 2000:
            return None
        if category not in ("normal", "sensitive"):
            category = "normal"
        target = (
            self.memory_project_store
            if scope == "project" and self.memory_project_store is not None
            else self.memory_store
        )
        from axiom.core.memory import MemoryItem

        item = MemoryItem(
            category=category,  # type: ignore[arg-type]
            content=cleaned,
            tags=[t.strip() for t in (tags or []) if t.strip()],
        )
        if not target.add(item):
            return None
        return item.id

    # ------------------------------------------------------ knowledge (W2.2)

    def knowledge_rows(self) -> list[dict]:
        """Collection status rows for the Desktop/TUI knowledge views."""
        rows: list[dict] = []
        for name in self.knowledge.names():
            store = self.knowledge.get(name)
            if store is None:
                continue
            rows.append(store.status())
        return rows

    async def knowledge_add_collection(self, name: str, path: str) -> dict:
        """Register a collection and index it (real, incremental)."""
        error = self.knowledge.add(name, path)
        if error is not None:
            return {"ok": False, "error": error}
        return await self.knowledge_reindex(name)

    async def knowledge_reindex(self, name: str) -> dict:
        store = self.knowledge.get(name)
        if store is None:
            return {"ok": False, "error": f"Unknown collection: {name}"}
        self.knowledge.configure_embedder(self.config.ollama_url, self.knowledge.embed_model)
        stats = await asyncio.to_thread(store.index, self.knowledge.embedder)
        status = store.status()
        return {"ok": True, "stats": stats.to_dict(), "collection": status}

    def knowledge_remove_collection(self, name: str) -> bool:
        return self.knowledge.remove(name)

    async def knowledge_search_rows(self, query: str, *, limit: int = 5) -> list[dict]:
        """Cited search fragments across all collections (for UI views)."""
        rows: list[dict] = []
        for name in self.knowledge.names():
            store = self.knowledge.get(name)
            if store is None:
                continue
            hits = await asyncio.to_thread(store.search, query)
            for hit in hits:
                rows.append({
                    "collection": name,
                    "source": hit.source,
                    "start_line": hit.start_line,
                    "end_line": hit.end_line,
                    "score": round(hit.score, 4),
                    "text": hit.text[:600],
                })
        rows.sort(key=lambda row: -row["score"])
        return rows[:limit]

    def load_plugins(self) -> list[str]:
        """Загрузить установленные плагины (п.20) и применить их вклады.

        Сначала читается персистентный реестр, затем подхватываются папки,
        которые пользователь положил в ``~/.axiom/plugins/`` вручную, после
        чего у включённых плагинов регистрируются их реальные инструменты.
        """
        from axiom.core.config import axiom_home

        try:
            self.plugins.load(axiom_home() / "plugins.json")
        except Exception:
            return []
        try:
            self.plugin_manager.discover()
        except Exception:
            pass
        names: list[str] = []
        for plugin_name, skill_ids in self._loaded_plugin_skills.items():
            for skill_id in skill_ids:
                self.skills.unpin(skill_id, source=f"plugin:{plugin_name}")
        self._loaded_plugin_skills.clear()
        for manifest in self.plugins.list(enabled_only=True):
            names.append(manifest.name)
            skill_ids = {str(skill_id) for skill_id in manifest.skills}
            self._loaded_plugin_skills[manifest.name] = skill_ids
            for skill_id in skill_ids:
                self.skills.pin(skill_id, source=f"plugin:{manifest.name}")
        # Реальный код плагинов: их инструменты становятся доступны модели.
        try:
            self.plugin_manager.load_enabled(self)
        except Exception:
            pass
        if names:
            self.trajectory.append("plugin.load", ", ".join(names), actor="system",
                                   data={"plugins": names})
        return names

    def install_plugin(self, manifest) -> dict:
        """Установить плагин (идемпотентно) и сохранить реестр (п.20).

        Возвращает ``{"name": ..., "status": "installed"|"updated"}`` — повторная
        установка того же плагина не плодит дубликаты, а обновляет его.
        """
        from axiom.core.config import axiom_home

        previous = self.plugins.get(manifest.name)
        status = "installed" if previous is None else "updated"
        self.plugins.install(manifest)
        try:
            self.plugins.save(axiom_home() / "plugins.json")
        except Exception:
            pass
        source = f"plugin:{manifest.name}"
        if previous is not None:
            for skill_id in previous.skills:
                self.skills.unpin(str(skill_id), source=source)
        skill_ids = {str(skill_id) for skill_id in (getattr(manifest, "skills", ()) or ())}
        self._loaded_plugin_skills[manifest.name] = skill_ids
        for skill_id in skill_ids:
            self.skills.pin(skill_id, source=source)
        return {"name": manifest.name, "status": status}

    def install_plugin_from_folder(self, path: str) -> dict:
        """Установить плагин из папки на диске (копирует её в ``~/.axiom/plugins``)."""
        manifest, status = self.plugin_manager.install_from_folder(path, session=self)
        return {"name": manifest.name, "status": status, "manifest": manifest.row()}

    def install_bundled_plugin(self, name: str) -> dict:
        """Установить встроенный плагин AXIOM из каталога bundled (п.20)."""
        manifest, status = self.plugin_manager.install_bundled(name, session=self)
        return {"name": manifest.name, "status": status, "manifest": manifest.row()}

    def toggle_plugin(self, name: str, enabled: bool) -> dict:
        """Включить/выключить плагин; изменение сохраняется и применяется сразу."""
        ok = self.plugin_manager.toggle(name, enabled, session=self)
        manifest = self.plugins.get(name)
        return {
            "name": name,
            "enabled": manifest.enabled if manifest else False,
            "ok": ok,
        }

    def remove_plugin(self, name: str) -> bool:
        """Remove an installed plugin and only the pins owned by that plugin."""
        removed = self.plugin_manager.remove(name, session=self)
        if not removed:
            return False
        for skill_id in self._loaded_plugin_skills.pop(name, set()):
            self.skills.unpin(skill_id, source=f"plugin:{name}")
        try:
            from axiom.core.config import axiom_home

            self.plugins.save(axiom_home() / "plugins.json")
        except Exception:
            pass
        return True

    def apply_preset(self, name: str) -> dict:
        """Apply runtime-supported preset fields; explicitly report ignored ones."""
        preset = self.presets.get(name)
        if preset is None:
            return {"ok": False, "error": f"unknown preset: {name}"}
        applied: dict = {"ok": True, "preset": preset.name}
        unsupported: list[str] = []
        if preset.temperature is not None:
            self.config.temperature = preset.temperature
            applied["temperature"] = preset.temperature
        if preset.permission in {"ask", "auto_approve_safe", "auto_approve_all"}:
            self.config.permission_mode = preset.permission
            applied["permission"] = preset.permission
        elif preset.permission:
            unsupported.append("permission")
        if preset.budget in {"performance", "balanced", "economy"}:
            self.router.config.budget = preset.budget
            applied["budget"] = preset.budget
        elif preset.budget:
            unsupported.append("budget")
        if preset.reasoning in {"low", "medium", "high", "max"}:
            self.config.think = preset.reasoning
            applied["reasoning"] = preset.reasoning
        elif preset.reasoning:
            unsupported.append("reasoning")
        if preset.context_tokens is not None and 512 <= preset.context_tokens <= 131072:
            self.config.num_ctx = preset.context_tokens
            applied["context_tokens"] = preset.context_tokens
        elif preset.context_tokens is not None:
            unsupported.append("context_tokens")
        for skill_id in self._active_preset_skills:
            self.skills.unpin(skill_id, source="preset")
        self._active_preset_skills = {str(skill_id) for skill_id in preset.skills}
        for skill_id in self._active_preset_skills:
            self.skills.pin(skill_id, source="preset")
        if preset.skills:
            applied["skills"] = sorted(self._active_preset_skills)
        if preset.code_mode:
            self.set_mode("code-agent")
            applied["mode"] = "code-agent"
        unsupported.extend(field for field, value in (
            ("provider_id", preset.provider_id if preset.provider_id != "ollama" else ""),
            ("model", preset.model), ("tools", preset.tools), ("fallbacks", preset.fallbacks),
        ) if value)
        if unsupported:
            applied["unsupported"] = sorted(set(unsupported))
        self.trajectory.append("preset.apply", preset.name, actor="system", data=applied)
        return applied

    def set_mode(self, mode: str) -> dict:
        """Переключить runtime-режим (п.33-34); ``code-agent`` включает PTC."""
        from axiom.core.presets import MODES

        if mode not in MODES:
            return {"ok": False, "error": f"unknown mode: {mode}"}
        self._mode = mode
        self._code_mode = bool(MODES[mode].get("code_mode"))
        info = {"ok": True, "mode": mode, "code_mode": self._code_mode,
                "agents": list(MODES[mode].get("agents") or []),
                "hint": str(MODES[mode].get("hint") or "")}
        self.bus.emit("agent.started", {"agent": "orchestrator", "mode": mode,
                                        "run_id": self.trajectory.run_id})
        self.trajectory.append("mode.switch", mode, actor="system", data=info)
        return info

    def _worker_model(self, agent_id: str, task: str):
        """Resolve the exact model one specialist must call.

        The orchestrated workflow must never silently downgrade a selected
        external model to the Ollama default: every worker reuses the active
        session model object, so routing, capabilities and provider identity
        stay consistent from Desktop/TUI down to the provider call.
        """
        model = self.active_model
        if model is None:  # pragma: no cover - guarded by callers
            from axiom.core.models import ModelInfo

            return ModelInfo(name=self.config.model or "qwen3:8b")
        target = self.router.config.primary
        if (target is not None and target.provider_id != "ollama" and target.model
                and model.name != target.model):
            from axiom.core.models import ModelInfo

            caps = list(model.capabilities or [])
            if not caps:
                caps = ["tools"]
            return ModelInfo(name=target.model, capabilities=caps)
        return model

    def _active_provider_id(self) -> str:
        target = self.router.config.primary
        if target is not None and target.provider_id:
            return str(target.provider_id)
        return "ollama"

    @staticmethod
    def _merge_child_trajectory(parent, child, agent_id: str) -> None:
        """Copy one worker's private trajectory into the orchestration trace.

        Workers execute against a private trajectory (isolation), but the
        user-facing orchestration trajectory must still allow full recovery
        of planning, tool calls, worker results and errors.
        """
        if parent is None or child is None or parent is child:
            return
        try:
            for event in list(child.events):
                if event.kind == "tool.call":
                    # Live worker tool activity is already recorded on the parent
                    # as ``subagent.tool.call``/``subagent.tool.result`` the moment
                    # it happens; merging the child copy would duplicate every tool
                    # line in the trajectory viewer.
                    continue
                parent.append(f"subagent.{event.kind}", event.summary,
                              actor=event.actor or agent_id,
                              data=dict(event.data or {}))
        except Exception:
            pass

    @staticmethod
    def _tool_detail(name: str, arguments: dict | None) -> str:
        """Human target of a tool call (path/command/query/...), like Agent does."""
        args = arguments or {}
        for key in ("path", "command", "query", "url", "pattern", "glob"):
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _record_worker_tool(parent, agent_id: str, kind: str, summary: str,
                            data: dict | None = None) -> None:
        """Put one worker step (tool, model identity, text) on the trajectory now.

        Workers run isolated trajectories (merged only when a worker finishes),
        so without this record the UI would see no tool activity for minutes
        even though agents are really working.
        """
        if parent is None:
            return
        try:
            parent.append(kind, summary, actor=agent_id, data=dict(data or {}))
        except Exception:
            pass

    @staticmethod
    def _flush_worker_text(parent, agent_id: str, kind: str, buffer: list[str]) -> None:
        """Publish one completed worker text segment (thinking or prose pass).

        The live feed only carries ``summary``, so the flat single-line preview
        goes there (capped for the UI); the full text is kept in ``data`` for
        the trajectory viewer and post-run analysis.
        """
        text = " ".join("".join(buffer).split())
        buffer.clear()
        if not text:
            return
        ChatSession._record_worker_tool(
            parent, agent_id, kind, text[:300] + ("…" if len(text) > 300 else ""),
            data={"text": text[:4000]},
        )

    async def _subagent_runner(self, **kwargs) -> dict:
        """Execute one isolated specialist with real model and scoped tools."""
        from axiom.core.permissions import PermissionManager
        from axiom.core.sandbox import Sandbox
        from axiom.core.trajectory import Trajectory

        model = self.active_model
        if model is None:
            return {"error": "no model is available"}
        task = str(kwargs.get("task") or "")
        agent_id = str(kwargs.get("agent") or "subagent")
        allowed = set(kwargs.get("tools") or ())
        parent_traj = kwargs.get("trajectory")
        request_config = self.config.model_copy(deep=True)
        role_prompts = {
            "analyst": "Analyze the task and project. Do not edit files.",
            "architect": "Design the smallest compatible implementation. Do not edit files.",
            "coder": "Implement the requested change with minimal, local edits.",
            "debugger": "Diagnose and fix the concrete failure. Verify the diagnosis.",
            "tester": "Run relevant real checks and report their actual results.",
            "reviewer": "Review worker results. Return APPROVED or structured REWORK with issues and required_changes.",
            "researcher": "Research only when external facts are required; cite sources.",
            "security": "Review security risks without changing unrelated code.",
        }
        from axiom.core.agent import DEFAULT_SYSTEM_PROMPT
        base_prompt = request_config.system_prompt or DEFAULT_SYSTEM_PROMPT
        request_config.system_prompt = (
            f"{base_prompt}\n\nSpecialist role: {agent_id}. "
            f"{role_prompts.get(agent_id, 'Complete the assigned task.')}"
        ).strip()
        request_registry = self.tools.subset(allowed)
        if self.active_task_runner is not None:
            # The worker's tools observe the task's shared CancelToken (W4.14).
            request_registry.cancel_token = self.active_task_runner.cancel_token
        from axiom.core.tools.web_search import WebSearchTool

        request_web_tool = WebSearchTool(
            self.provider,
            max_sources=self.config.search_max_sources,
            local_only=request_config.local_only,
        )
        if "web_search" in allowed or "fetch_url" in allowed:
            request_web_tool.register(request_registry)
        # Every worker owns an isolated runtime context: private config copy
        # (above), private event bus, state machine, trajectory, router,
        # catalog, skills, sandbox and permission cache. Only stateless tool
        # handlers, the model transport and read-only parent data are shared.
        from axiom.core.bus import EventBus

        child_traj = Trajectory(actor=agent_id)
        request_permissions = PermissionManager(config=request_config)
        request_permissions._request_callback = self.permissions._request_callback
        request_agent = Agent(
            self.client, config=request_config, registry=request_registry,
            machine=GenerationStateMachine(), web_tool=request_web_tool,
            bus=EventBus(), trajectory=child_traj,
        )
        request_agent._client = self.provider_client
        request_agent.attach_harness(
            trajectory=child_traj,
            router=deepcopy(self.router), catalog=deepcopy(self.model_catalog),
            sandbox=Sandbox(policies=dict(self.sandbox.policies), ask_callback=self.sandbox.ask_callback),
            skills=deepcopy(self.skills), permissions=request_permissions,
            verifier=self.verifier,
        )
        parts: list[str] = []
        pass_content: list[str] = []
        pass_thinking: list[str] = []
        tool_calls = 0
        tool_ok = 0
        tool_failed = 0
        worker_model = self._worker_model(agent_id, task)
        # Publish the exact model/provider this specialist will call before the
        # first token — the final reply arrives minutes later, the live feed
        # must already say which model is actually working.
        provider_id = self._active_provider_id()
        self._record_worker_tool(
            parent_traj, agent_id, "subagent.model",
            f"{provider_id}/{worker_model.name}",
            data={"provider_id": provider_id, "model": worker_model.name},
        )

        def _flush_pass() -> None:
            # One model pass ends at the next tool call (or at run end):
            # publish what it thought and what it wrote, immediately.
            self._flush_worker_text(parent_traj, agent_id,
                                    "subagent.reasoning", pass_thinking)
            self._flush_worker_text(parent_traj, agent_id,
                                    "subagent.answer", pass_content)

        try:
            async for event in request_agent.run([{"role": "user", "content": task}], worker_model):
                if kwargs.get("on_event") is not None:
                    kwargs["on_event"](event)
                if isinstance(event, ReasoningChunk):
                    pass_thinking.append(event.text)
                elif isinstance(event, ContentChunk):
                    parts.append(event.text)
                    pass_content.append(event.text)
                elif isinstance(event, ToolCallEvent):
                    _flush_pass()
                    tool_calls += 1
                    detail = self._tool_detail(event.name, event.arguments)
                    self._record_worker_tool(
                        parent_traj, agent_id, "subagent.tool.call",
                        f"{event.name} {detail}".strip(),
                        data={"tool": event.name, "arguments": dict(event.arguments)},
                    )
                elif isinstance(event, ToolResultEvent):
                    if event.ok:
                        tool_ok += 1
                    else:
                        tool_failed += 1
                    if event.ok:
                        outcome = (f"ok ({event.duration_ms} ms)" if event.duration_ms
                                   else "ok")
                    else:
                        outcome = f"failed: {str(event.error or 'error')[:200]}"
                    self._record_worker_tool(
                        parent_traj, agent_id, "subagent.tool.result",
                        f"{event.name} {outcome}",
                        data={"tool": event.name, "ok": event.ok,
                              "duration_ms": event.duration_ms,
                              "error": event.error},
                    )
        except Exception as exc:
            _flush_pass()
            self._merge_child_trajectory(parent_traj, child_traj, agent_id)
            return {"agent": agent_id, "error": f"{type(exc).__name__}: {exc}"}
        _flush_pass()
        self._merge_child_trajectory(parent_traj, child_traj, agent_id)
        route = dict(getattr(self.provider_client, "last_route", {}) or {})
        result = {
            "agent": agent_id,
            "content": "".join(parts).strip()[:4000],
            "provider_id": route.get("provider_id") or self._active_provider_id(),
            "model": route.get("model") or worker_model.name,
            "tools_used": tool_calls,
            "tools_ok": tool_ok,
            "tools_failed": tool_failed,
        }
        if not result["content"]:
            result["error"] = "empty model response"
        return result

    @property
    def task_store(self) -> TaskStore:
        root = self.workspace_root
        return TaskStore(root / ".axiom" / "tasks" if root is not None else None)

    async def _plan_task(self, prompt: str) -> str:
        """Use the configured provider, with no executable tools or chat mutations."""
        if self.active_model is None:
            raise ValueError("No model is available")
        parts: list[str] = []
        size = 0
        async for chunk in self.provider_client.chat(
            self.active_model.name, [{"role": "user", "content": prompt}], tools=None,
        ):
            if chunk.content:
                size += len(chunk.content)
                if size > 32000:
                    raise ValueError("Planner response exceeds 32000 characters")
                parts.append(chunk.content)
        return "".join(parts)

    async def _execute_task_step(self, *, step, prompt: str, on_event) -> dict:
        if self.active_task_runner is not None:
            # Shared CancelToken: never start a model request after cancel (W4.14).
            self.active_task_runner.cancel_token.raise_if_cancelled()
        return await self._subagent_runner(
            agent="coder", task=prompt, tools=step.tools, trajectory=self.trajectory, on_event=on_event,
        )

    async def _verify_task(self, task: Task) -> dict:
        name = "verify_changes"
        if not self.sandbox.allows(name):
            return {"ok": False, "executed": False, "error": "Verification blocked by sandbox"}
        permission = self.tools.permission_for(name, {})
        if not await self.permissions.decide(name, {}, permission):
            return {"ok": False, "executed": False, "error": "Verification permission denied"}
        result = await self.tools.execute(name, {}, approved=True)
        data = dict(result.data or {})
        steps = data.get("steps")
        executed = bool(steps)
        nonzero = [step for step in steps or []
                   if isinstance(step, dict) and step.get("exit_code") not in (None, 0)]
        failed_steps = [step for step in steps or []
                        if isinstance(step, dict) and step.get("ok") is not True]
        real_checks = bool(executed and not nonzero and not failed_steps)
        report = {"ok": False, "executed": executed, "summary": result.content,
                  "error": result.error, "checks": data}
        if not result.ok or not real_checks:
            if real_checks is False and executed and not result.error:
                report["error"] = "Verification report contains a failed or non-zero check"
            return report
        # Passing tests alone do not prove the requested change was implemented.
        review = await self._subagent_runner(
            agent="reviewer", tools=[], trajectory=self.trajectory,
            task=("Review task acceptance. Return ONLY JSON {\"approved\": true/false, \"reason\": \"...\"}. "
                  "Approve only when the step evidence AND checks meet every definition_of_done criterion.\n"
                  + task.model_dump_json() + "\nVerification:\n" + result.content),
        )
        decision = self._first_json_object(str(review.get("content") or ""))
        if decision is None or review.get("error"):
            report["error"] = "Reviewer did not return a valid acceptance verdict"
            return report
        report["review"] = decision
        report["ok"] = decision.get("approved") is True
        if not report["ok"]:
            report["error"] = str(decision.get("reason") or "Acceptance criteria were not approved")
        return report

    @staticmethod
    def _first_json_object(text: str) -> dict | None:
        """Parse the first balanced JSON object; ignore any trailing content.

        The agent's forced-edit heuristic can repeat a pass, so a worker reply
        may carry the verdict twice ("{...}{...}"). Only the first object is
        authoritative — a doubled reply must not be read as an approval failure.
        """
        import json as _json

        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = _json.loads(text[start:index + 1])
                    except ValueError:
                        return None
                    return parsed if isinstance(parsed, dict) else None
        return None

    async def task_plan(self, goal: str) -> object:
        if self.busy:
            raise ValueError("A generation is already running")
        from axiom.core.planner import Planner
        planner = Planner(self._plan_task)
        tools = [d.name for d in self.tools.definitions()]
        clean_goal = goal.strip()
        if not clean_goal:
            raise ValueError("Task goal cannot be empty")
        # Do not replace a failed model response with a canned plan: that would
        # hide the failure and can silently use the wrong natural language.
        return await planner.create(clean_goal, tools)

    def task_create(self, goal: str, *, plan: dict | object | None = None) -> Task:
        from axiom.core.planner import TaskPlan
        plan_obj: TaskPlan | None = None
        if isinstance(plan, dict):
            plan_obj = TaskPlan.model_validate(plan)
        elif isinstance(plan, TaskPlan):
            plan_obj = plan
        task = Task(
            goal=goal.strip(),
            scope=str(self.workspace_root) if self.workspace_root else None,
            plan=plan_obj,
            state=TaskState.PENDING,
            detail="План действий сформирован. Готов к выполнению.",
        )
        if plan_obj is not None:
            task.plan_history.append(plan_obj.model_copy(deep=True))
        self.task_store.save(task)
        return task

    def task_save(
        self,
        task_id: str,
        *,
        goal: str | None = None,
        plan: dict | object | None = None,
        state: str | None = None,
    ) -> Task | None:
        import time

        from axiom.core.planner import TaskPlan
        task = self.task_store.load(task_id)
        if task is None:
            return None
        if goal is not None and goal.strip():
            task.goal = goal.strip()
        if plan is not None:
            if isinstance(plan, dict):
                task.plan = TaskPlan.model_validate(plan)
            elif isinstance(plan, TaskPlan):
                task.plan = plan
        if state is not None:
            task.state = TaskState(state)
        task.updated_at = time.time()
        task.revision += 1
        self.task_store.save(task)
        return task

    def task_delete(self, task_id: str) -> bool:
        if self.active_task is not None and self.active_task.id == task_id:
            self.task_cancel(task_id)
        return self.task_store.delete(task_id)

    async def task_start(self, goal: str, *, planning: bool | None = None, plan: dict | object | None = None,
                         detached: bool = False) -> Task:
        if self.busy:
            raise ValueError("A generation is already running")
        from axiom.core.planner import TaskPlan
        plan_obj: TaskPlan | None = None
        if isinstance(plan, dict):
            plan_obj = TaskPlan.model_validate(plan)
        elif isinstance(plan, TaskPlan):
            plan_obj = plan
        task = Task(
            goal=goal.strip(),
            scope=str(self.workspace_root) if self.workspace_root else None,
            plan=plan_obj,
            planning=planning,
        )
        if plan_obj is not None:
            task.plan_history.append(plan_obj.model_copy(deep=True))
        self.task_store.save(task)
        return await self._run_task(task, detached=detached)

    async def task_resume(self, task_id: str, *, acknowledge: bool = False, detached: bool = False) -> Task:
        if self.busy:
            raise ValueError("A generation is already running")
        task = self.task_store.load(task_id)
        if task is None:
            raise ValueError("Task not found")
        scope = str(self.workspace_root) if self.workspace_root else None
        if task.scope != scope:
            raise ValueError("Open the task's original workspace before resuming")
        if task.state == TaskState.COMPLETED:
            return task
        return await self._run_task(task, resume=True, acknowledge=acknowledge, detached=detached)

    def task_state(self, task_id: str) -> Task | None:
        return self.task_store.load(task_id)

    def task_review(self, task_id: str, decision: str) -> Task:
        """Accept a task result or restore its captured text-file baseline."""
        import time
        task = self.task_store.load(task_id)
        if task is None:
            raise ValueError("Task not found")
        if decision not in {"accept", "reject"}:
            raise ValueError("Review decision must be accept or reject")
        if task.state != TaskState.COMPLETED:
            raise ValueError("Only a completed task can be reviewed")
        if decision == "reject":
            if self.workspace_root is None or task.scope != str(self.workspace_root):
                raise ValueError("Open the task's original workspace before rejecting it")
            if task.unknown_baselines:
                raise ValueError("Cannot safely reject: original binary/unreadable files were changed")
            for relative, original in task.file_baselines.items():
                path = (self.workspace_root / relative).resolve()
                try:
                    path.relative_to(self.workspace_root.resolve())
                except ValueError as exc:
                    raise ValueError("Task contains a path outside its workspace") from exc
                if original is None:
                    if path.is_file():
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temp = path.with_name(path.name + ".axiom-review-tmp")
                    temp.write_text(original, encoding="utf-8")
                    temp.replace(path)
            task.review_status = "rejected"
        else:
            task.review_status = "accepted"
        task.updated_at = time.time()
        task.revision += 1
        self.task_store.save(task)
        payload = {"type": "task", "kind": "task.review", "task_id": task.id,
                   "timestamp": task.updated_at, "task": task.model_dump(mode="json")}
        self.bus.emit("task.event", payload)
        return task

    def task_cancel(self, task_id: str) -> bool:
        if self.active_task is None or self.active_task.id != task_id:
            return False
        runner = self.active_task_runner
        if runner is not None:
            # Cooperative signal first: the runner stops at its next
            # checkpoint even if the hard asyncio cancel lands later (W4.14).
            runner.request_cancel()
        return self.cancel()

    async def _run_task(self, task: Task, *, resume: bool = False, acknowledge: bool = False,
                        detached: bool = False) -> Task:
        from axiom.core.planner import Planner

        runner = TaskRunner(
            store=self.task_store, planner=Planner(self._plan_task), execute=self._execute_task_step,
            verify=lambda: self._verify_task(task), tools=[d.name for d in self.tools.definitions()],
            bus=self.bus, trajectory=self.trajectory,
            workspace_root=self.workspace_root, context_max_tokens=self._context_budget(),
            max_verification_repairs=self.config.max_retries,
        )
        self.active_task = task
        self.active_task_runner = runner
        # W4.9: task-scoped approvals live exactly as long as this run.
        self.permissions.bind_context(
            task_id=task.id,
            project=str(self.workspace_root) if self.workspace_root else None,
        )
        for tool in (self.terminal, self.verify_tools):
            if tool is not None:
                tool.on_process = lambda event, _runner=runner, _task=task: _runner.process_event(_task, event)
        caller = asyncio.current_task()
        worker = asyncio.create_task(runner.run(task, resume=resume, acknowledge=acknowledge))
        self._task = worker
        if detached:
            def clear(done: asyncio.Task) -> None:
                if self._task is done:
                    self._task = None
                if self.active_task is task:
                    self.active_task = None
                    self.active_task_runner = None
                    # W4.9: a detached run keeps its scope only while active.
                    try:
                        self.permissions.drop_task_scope(task.id)
                    except Exception:
                        pass
                # Consume errors if the worker itself escaped its guard.
                if not done.cancelled():
                    done.exception()
            worker.add_done_callback(clear)
            return task
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
            if task.state != TaskState.CANCELLED:
                runner.transition(task, TaskState.CANCELLED, "Stopped before execution")
            if caller is not None and caller.cancelling():
                raise
            return task
        finally:
            if self._task is worker:
                self._task = None
            # W4.9: leaving the run drops its task-scoped approvals.
            self.permissions.drop_task_scope(task.id)
            self.active_task = None
            self.active_task_runner = None

    async def run_orchestrated(self, text: str, *, limit: int = 4,
                               max_iterations: int = 3) -> dict:
        """Run the real multi-agent workflow for an explicit orchestration request.

        ``/orchestrate`` is a generation from the UI point of view: while the
        workers run, ``busy`` stays true and the next request must be rejected
        or cancelled first. The flag is released on every exit path so Desktop
        and TUI can always accept the next command afterwards.
        """
        if self.active_model is None:
            return {"ok": False, "error": "no model is available"}
        if not text.strip():
            return {"ok": False, "error": "Orchestration task is empty. Use /orchestrate <task>."}
        if self.busy:
            return {"ok": False, "error": "A generation is already running."}
        self.trajectory.append("orchestration.command", f"/orchestrate {text[:200]}",
                               actor="user")
        # ``busy`` is derived from ``_task``; keep a real task for the whole
        # orchestration so Desktop/TUI generation locks behave exactly like a
        # normal generation (busy during work, released afterwards) and Esc
        # actually cancels the workers instead of doing nothing.
        current = asyncio.current_task()
        orchestration = asyncio.ensure_future(self._run_orchestrated_inner(
            text, limit=min(5, max(1, limit)),
            max_iterations=min(3, max(1, max_iterations))))
        self._task = orchestration  # type: ignore[assignment]
        try:
            return await asyncio.shield(orchestration)
        except asyncio.CancelledError:
            # Two cases land here: (a) our caller cancelled this task — the
            # shield kept the orchestration alive, so stop it explicitly and
            # restore the cancellation count; (b) session.cancel() stopped the
            # orchestration task itself — the caller was never cancelled.
            if current is not None and current.cancelling() > 0:
                current.uncancel()
            if not orchestration.done():
                orchestration.cancel()
            try:
                await orchestration
            except asyncio.CancelledError:
                pass
            return {"ok": False, "error": "cancelled",
                    "cancelled": True, "approved": False, "completed": False}
        finally:
            if self._task is orchestration:
                self._task = None
            self._verifying = False
            try:
                self.trajectory_store.save(self.trajectory)
            except Exception:
                pass

    async def resume_orchestrated(self, run_id: str, *, limit: int = 4,
                                  max_iterations: int = 3) -> dict:
        """Resume a persisted orchestration without rerunning completed agents."""
        loaded = self.trajectory_store.resume(run_id)
        if loaded is None:
            return {"ok": False, "error": f"Unknown trajectory: {run_id}"}
        command = next((e.summary for e in loaded.events if e.kind == "orchestration.command"), "")
        text = command.removeprefix("/orchestrate ").strip()
        previous = self.trajectory
        self.trajectory = loaded
        try:
            return await self.run_orchestrated(text, limit=limit, max_iterations=max_iterations)
        finally:
            if self.trajectory is loaded:
                self.trajectory = previous

    async def _run_orchestrated_inner(self, text: str, *, limit: int, max_iterations: int) -> dict:
        try:
            return await self.orchestrator.run(
                text, self.trajectory, self._subagent_runner, parallel=True,
                limit=limit, max_iterations=max_iterations,
                force_orchestrated=True, verifier=self._run_orchestration_verification,
            )
        except asyncio.CancelledError:
            try:
                self.trajectory.append("orchestration.cancelled",
                                       "stopped by user", actor="orchestrator")
            except Exception:
                pass
            self.bus.emit("orchestration.cancelled", {"run_id": self.trajectory.run_id})
            raise
        except Exception as exc:
            self.trajectory.append(
                "orchestration.failed", f"{type(exc).__name__}: {exc}", actor="orchestrator",
                data={"error": str(exc)})
            self.bus.emit("orchestration.failed",
                          {"run_id": self.trajectory.run_id, "error": str(exc)})
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                    "approved": False, "completed": False}

    async def _run_orchestration_verification(self) -> dict:
        if self.verifier is None:
            return {"ok": False, "error": "verification unavailable"}
        report = await self.verifier.run(kind="python")
        return {"ok": report.ok, "summary": report.summary(), "errors": list(report.errors)}

    async def run_parallel_agents(self, text: str, *, limit: int = 4) -> dict:
        """Backward-compatible four-worker runtime used by existing integrations."""
        if self.active_model is None:
            return {"ok": False, "error": "no model is available"}
        return await self.orchestrator.run(
            text, self.trajectory, self._subagent_runner, parallel=True,
            limit=min(4, max(1, limit)),
        )

    # ------------------------------------------------------------- lifecycle

    @property
    def busy(self) -> bool:
        """True while a generation is really in flight."""
        return self._task is not None and not self._task.done()

    @property
    def model(self) -> ModelInfo | None:
        return self.active_model

    @property
    def state(self) -> GenerationState:
        return self.machine.state

    async def startup(self) -> StartupReport:
        """Probe Ollama and discover models — every step is real.

        Single deduplicated probe: one ``/api/version`` request (not two), the
        model list straight from ``/api/tags``, and ``/api/ps``/``/api/show``
        stay lazy (only callers that actually need them request them).
        """
        # MCP (п.15): подключаем внешние серверы из конфига (по умолчанию — пусто).
        try:
            await self._load_mcp_servers()
        except Exception:
            pass
        # Plugins (п.20): установленные плагины применяются к skills.
        try:
            self.load_plugins()
        except Exception:
            pass
        try:
            discovered = await self.provider_manager.discover_models()
            self.model_catalog.replace(discovered)
        except Exception:
            discovered = []
        try:
            version: str | None = None
            available = await self.client.is_available()
            models: list[ModelInfo] = []
            if available:
                # One real probe: version + models, reusing one healthy check.
                version = await self.client.version()
                models = await self.registry.refresh()
            if not available or not models:
                external = next((m for m in discovered if m.provider_id != "ollama"), None)
                if external is not None:
                    self.active_model = ModelInfo(name=external.id, capabilities=[
                        name for name, enabled in (("tools", external.tool_calling),
                                                     ("thinking", external.reasoning),
                                                     ("vision", external.vision)) if enabled
                    ])
                    self.conversation.model = external.id
                return StartupReport(
                    ollama_available=available,
                    version=version,
                    error=None,
                    hint=(
                        f"Start Ollama and make sure it listens on {self.client.base_url}"
                        if not available
                        else None
                    ),
                )
            selected = self.registry.resolve(self.config.model)
            if selected is not None:
                self.active_model = selected
                ModelRegistry.persist_selection(self.config, selected.name)
                self.conversation.model = selected.name
            elif discovered:
                external = next((m for m in discovered if m.provider_id != "ollama"), None)
                if external is not None:
                    self.active_model = ModelInfo(name=external.id, capabilities=[
                        name for name, enabled in (("tools", external.tool_calling),
                                                     ("thinking", external.reasoning),
                                                     ("vision", external.vision)) if enabled
                    ])
                    self.conversation.model = external.id
            return StartupReport(
                ollama_available=True,
                version=version,
                models=models,
                selected=selected,
            )
        except AxiomError as exc:
            return StartupReport(ollama_available=False, error=str(exc), hint=exc.hint)

    async def warmup_model(self, name: str | None = None) -> bool:
        """Load the model into memory in the background (never blocks a turn).

        Returns ``False`` (no exception) when Ollama is unreachable or the
        warm-up is disabled in config. Safe to fire-and-forget from the GUI.
        """
        if not self.config.warmup_model:
            return False
        target = name or (self.active_model.name if self.active_model else None)
        if not target:
            return False
        return await self.client.warmup(target)

    async def refresh_models(self) -> list[ModelInfo]:
        return await self.registry.refresh()

    async def model_detail(self, name: str | None = None) -> ModelInfo | None:
        """Full descriptor (real context window) of *name* or the active model."""
        target = name or (self.active_model.name if self.active_model else None)
        if not target:
            return None
        detail = await self.registry.detail(target)
        if detail is not None and self.active_model is not None and detail.name == self.active_model.name:
            self.active_model = detail
        return detail

    def tools_info(self) -> list[dict[str, Any]]:
        """Agent tools as the backend really declares them (name/description/permission/risk)."""
        return [
            {"description": definition.description, **definition.meta()}
            for definition in self.tools.definitions()
        ]

    async def reconnect(self, ollama_url: str | None = None) -> StartupReport:
        """Apply a new Ollama URL (if given) and probe again."""
        if ollama_url and ollama_url.strip() and ollama_url.strip() != self.client.base_url:
            self.config.ollama_url = ollama_url.strip()
            self.config.save()
            self.client = OllamaClient(self.config.ollama_url)
            self.registry = ModelRegistry(self.client)
            self.provider_client.ollama_client = self.client
            self.agent = Agent(
                self.client,
                config=self.config,
                registry=self.tools,
                machine=self.machine,
                web_tool=self.web_tool,
            )
            self.agent.attach_harness(
                bus=self.bus,
                trajectory=self.trajectory,
                router=self.router,
                catalog=self.model_catalog,
                sandbox=self.sandbox,
                skills=self.skills,
                verifier=self.verifier,
                permissions=self.permissions,
            )
            self.agent._client = self.provider_client
        return await self.startup()

    # ---------------------------------------------------------------- models

    async def switch_model(self, name: str) -> ModelInfo:
        """Switch the active model (persisted). Raises if it does not exist."""
        model = self.registry.get(name)
        if model is None:
            await self.registry.refresh()
            model = self.registry.get(name)
        if model is None:
            from axiom.core.errors import ModelNotFoundError

            raise ModelNotFoundError(f"Model '{name}' is not available in Ollama.")
        self.active_model = model
        self.conversation.model = model.name
        ModelRegistry.persist_selection(self.config, model.name)
        self._save_conversation()
        return model

    # ----------------------------------------------------------- conversations

    def new_conversation(self) -> Conversation:
        """Start a fresh conversation (the current one is already persisted)."""
        self._save_conversation()
        self.conversation = Conversation(model=self.active_model.name if self.active_model else None)
        return self.conversation

    def load_conversation(self, conversation_id: str) -> Conversation | None:
        self._save_conversation()
        loaded = self.history_store.load(conversation_id)
        if loaded is None:
            return None
        self.conversation = loaded
        return loaded

    def history(self) -> list[Conversation]:
        return self.history_store.list()

    def delete_conversation(self, conversation_id: str) -> bool:
        if conversation_id == self.conversation.id:
            self.conversation = Conversation(
                model=self.active_model.name if self.active_model else None
            )
        return self.history_store.delete(conversation_id)

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        """Rename a stored conversation; the in-memory one is updated too."""
        renamed = self.history_store.rename(conversation_id, title)
        if renamed and conversation_id == self.conversation.id:
            self.conversation.title = " ".join(title.split())[:80]
        return renamed

    # -------------------------------------------------------------- workspace

    @property
    def workspace_root(self) -> Path | None:
        # Global Chat turns workspace tooling off; reporting a root then would
        # keep the GUI (explorer / git / terminal) bound to a closed project.
        if self.workspace_tools is None or not self.config.workspace_tools_enabled:
            return None
        return self.workspace_tools.root

    def workspace_info(self) -> ProjectInfo | None:
        root = self.workspace_root
        return detect_project(root) if root and root.exists() else None

    def recent_workspaces(self) -> list[ProjectInfo]:
        return self.workspaces.recent()

    def pinned_workspaces(self) -> list[ProjectInfo]:
        return self.workspaces.pinned_projects()

    def is_workspace_pinned(self, path: str) -> bool:
        return self.workspaces.is_pinned(path)

    def pin_workspace(self, path: str) -> bool:
        return self.workspaces.pin(path)

    def unpin_workspace(self, path: str) -> bool:
        return self.workspaces.unpin(path)

    def search_projects(self, query: str) -> list[ProjectInfo]:
        return self.workspaces.search_projects(query)

    def _rebuild_search_provider(self) -> None:
        """Rebuild the live search backend from ``Config.search_provider``.

        Called after ``set_config`` changes the selection or timeout so both the
        agent tool and the search test use the new backend immediately.
        """
        self.provider = build_search_provider(
            self.config.search_provider, timeout=self.config.search_timeout
        )
        self.web_tool = WebSearchTool(
            self.provider, max_sources=self.config.search_max_sources
        )
        agent = getattr(self, "agent", None)
        if agent is not None:
            agent._web_tool = self.web_tool

    async def search_test(self, query: str, limit: int | None = None) -> dict:
        """Run a real search through the configured backend and report its health.

        W1.2: an honest connectivity probe. It never claims "Online" without a
        real result set; a failure returns the engine name, the measured latency
        and the real error instead of a fabricated state.
        """
        query = (query or "").strip()
        if not query:
            return {
                "ok": False,
                "provider": "",
                "latency_ms": 0,
                "result_count": 0,
                "results": [],
                "error": "Empty query",
                "hint": None,
            }
        started = time.perf_counter()
        count = limit if isinstance(limit, int) and limit > 0 else self.config.search_max_sources
        try:
            results = await self.provider.search(query, limit=count)
        except SearchUnavailableError as exc:
            return {
                "ok": False,
                "provider": getattr(self.provider, "name", "Web"),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "result_count": 0,
                "results": [],
                "error": str(exc),
                "hint": exc.hint,
            }
        except Exception as exc:  # defensive: the test button must not crash
            return {
                "ok": False,
                "provider": getattr(self.provider, "name", "Web"),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "result_count": 0,
                "results": [],
                "error": str(exc),
                "hint": None,
            }
        provider_name = (
            getattr(self.provider, "last_provider", "")
            or getattr(self.provider, "name", "Web")
        )
        return {
            "ok": True,
            "provider": provider_name,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "result_count": len(results),
            "results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet}
                for r in results
            ],
            "error": None,
            "hint": None,
        }

    def create_project(self, path: str) -> ProjectInfo:
        """Create a new project directory and remember it."""
        return self.workspaces.create_project(Path(path).expanduser().resolve())

    def remove_workspace(self, path: str) -> bool:
        return self.workspaces.remove(path)

    def set_workspace(self, path: str) -> ProjectInfo:
        """Switch the whole session to a real directory (AI + terminal + explorer)."""
        if self.active_task is not None:
            raise ValueError("Stop the active task before switching workspace")
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            from axiom.core.errors import AxiomError

            raise AxiomError(f"Not a directory: {target}")
        # §13/§22: keep the previous conversation on disk, then move this
        # session to the new project's own history dir — histories never mix.
        self._save_conversation()
        self.history_store.use_workspace(target)
        self.conversation = Conversation(model=self.active_model.name if self.active_model else None)
        self._save_conversation()
        self.config.workspace_root = str(target)
        # Leaving Global Chat re-enables workspace tooling for the new project.
        self.config.workspace_tools_enabled = True
        self.config.save()
        # W4.9: a workspace switch rebinds the project approval scope; stale
        # ``allow_project`` entries never leak into the new project.
        self.permissions.bind_context(
            task_id=self.permissions.active_task_id, project=str(target),
        )
        if self.workspace_tools is not None:
            self.workspace_tools.set_root(target)
            # Re-register: clear_workspace() dropped these names from the registry.
            self.workspace_tools.register(self.tools)
        else:
            # Tools were never created (config disabled them earlier) — build now.
            self.workspace_tools = WorkspaceTools(target, access_mode=self.config.access_mode)
            self.workspace_tools.register(self.tools)
            self.git_tools = GitTools(target)
            self.git_tools.register(self.tools)
            self.project_tools = ProjectTools(target)
            self.project_tools.register(self.tools)
        if self.git_tools is not None:
            self.git_tools.set_root(target)
            self.permissions.git_tools = self.git_tools
            self.git_tools.register(self.tools)
        if self.project_tools is not None:
            self.project_tools.set_root(target)
            self.project_tools.register(self.tools)
        if self.terminal is not None:
            self.terminal.set_root(target)
            self.terminal.enabled = self.config.access_mode != "read_only"
            self.terminal.register(self.tools)
        elif self.config.terminal_enabled and self.config.access_mode != "read_only":
            self.terminal = TerminalTool(root=target, enabled=True)
            self.terminal.register(self.tools)
        if self.verify_tools is not None:
            self.verify_tools.set_root(target)
            self.verify_tools.enabled = self.config.access_mode != "read_only"
            self.verify_tools.register(self.tools)
        elif self.config.terminal_enabled and self.config.access_mode != "read_only":
            self.verify_tools = VerificationTools(root=target, enabled=True)
            self.verify_tools.register(self.tools)
        # Project Intelligence (п.19): авто-индекс + .axiom/ персист.
        try:
            from axiom.core.project_index import ProjectMemory as _PM
            from axiom.core.project_index import index_project as _idx

            self._project_memory = _PM(target)
            index_obj = _idx(target)
            self._project_memory.save_index(index_obj)
            if self.trajectory is not None:
                self.trajectory.append("project.index",
                                       f"{target.name}: {','.join(index_obj.languages[:4])}",
                                       actor="architect", data=index_obj.to_json())
        except Exception:
            pass
        # W2.1: project-scoped memory follows the workspace switch.
        try:
            from axiom.core.memory import MemoryStore as _MemStore

            self.memory_project_store = _MemStore(scope="project", project_root=target)
            self.memory_tools.project_store = self.memory_project_store
        except Exception:
            pass
        self.workspaces.remember(target)
        return detect_project(target)

    def clear_workspace(self) -> None:
        """Leave project mode: Global Chat with no filesystem/terminal tools.

        The conversation stays on disk (project history dir), the store points
        back at the global history dir, and every workspace tool is removed
        from the registry so the model chats over Ollama only.
        """
        if self.active_task is not None:
            raise ValueError("Stop the active task before leaving workspace")
        self._save_conversation()
        self.history_store.use_workspace(None)
        self.conversation = Conversation(model=self.active_model.name if self.active_model else None)
        self._save_conversation()
        self.config.workspace_root = None
        # Persist Global Chat across restarts: no workspace tools on boot.
        self.config.workspace_tools_enabled = False
        self.config.save()
        for name in WORKSPACE_TOOL_NAMES:
            self.tools.unregister(name)
        # W2.1: memory tools stay (they are not workspace-scoped), but the
        # project store must not leak into Global Chat.
        self.memory_project_store = None
        self.memory_tools.project_store = None
        if self.terminal is not None:
            self.terminal.enabled = False
        if self.verify_tools is not None:
            self.verify_tools.enabled = False

    async def run_terminal(self, command: str, confirmed: bool = False) -> dict:
        """Run a real shell command in the workspace (GUI terminal panel).

        Safe commands run immediately; anything else returns ``permission:
        "ask"`` so the GUI can confirm with the user first. HIGH/CRITICAL
        commands (push, recursive delete, network pipe, blocklisted patterns)
        always gate on ``confirmed`` and report their W4.9 risk tier + reason.
        """
        from axiom.core.command_policy import classify_command_risk

        if self.terminal is None:
            return {"ok": False, "error": "Terminal access is disabled", "permission": "blocked"}
        tier, reason = classify_command_risk(command)
        if ((classify_command(command) == ToolPermission.ALWAYS and tier not in ("HIGH", "CRITICAL"))
                or confirmed):
            result = await self.terminal._run(command)
            return {
                "ok": result.ok,
                "content": result.content,
                "error": result.error,
                "exit_code": (result.data or {}).get("exit_code"),
                "cwd": (result.data or {}).get("cwd"),
                "permission": "granted",
                "risk": tier,
                "reason": reason,
            }
        return {"ok": False, "permission": "ask", "command": command, "risk": tier, "reason": reason}

    def _save_conversation(self) -> None:
        if not self.config.save_history:
            return
        if not self.conversation.messages:
            return
        try:
            self.history_store.save(self.conversation)
        except OSError:
            # persistence must never break a chat session
            pass

    # ------------------------------------------------------------ generation

    def cancel(self) -> bool:
        """Cancel the in-flight generation. Returns True if something was stopped."""
        if self.busy and self._task is not None:
            if self._task.cancelling():
                return True  # do not interrupt subprocess cleanup with a second cancel
            self._task.cancel()
            return True
        return False

    async def send(
        self,
        text: str,
        *,
        force_search: bool = False,
        search_query: str | None = None,
        images: list[str] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Send a user message and stream the resulting events.

        Cancellation is supported through :meth:`cancel`; partial output is
        preserved and reported with a ``CANCELLED`` terminal event.
        """
        text = text.strip()
        images = [img for img in (images or []) if img]
        if not text and not images:
            return
        async for event in self._run_turn(
            text,
            force_search=force_search,
            search_query=search_query,
            images=images,
            record_user=True,
        ):
            yield event

    async def regenerate(self, *, force_search: bool = False) -> AsyncIterator[ChatEvent]:
        """Re-run the last turn: the stored assistant answer is dropped first.

        The backend really rewrites history here (no client-side illusion):
        the previous assistant message is removed from the conversation before
        the agent runs again on the same context.
        """
        if self.busy:
            yield ErrorEvent(
                message="A generation is already running.",
                kind="busy",
                hint="Stop it before regenerating.",
            )
            return
        last_user = next(
            (m.content for m in reversed(self.conversation.messages) if m.role == "user"),
            "",
        )
        if not last_user:
            yield ErrorEvent(
                message="There is nothing to regenerate.",
                kind="empty_history",
                hint="Send a message first.",
            )
            yield Done(state=GenerationState.ERROR)
            return
        if self.conversation.messages and self.conversation.messages[-1].role == "assistant":
            self.conversation.messages.pop()
        self._save_conversation()
        async for event in self._run_turn(
            last_user,
            force_search=force_search,
            search_query=None,
            images=[],
            record_user=False,
        ):
            yield event

    async def edit_last_user(self, text: str, *, force_search: bool = False) -> AsyncIterator[ChatEvent]:
        """Replace the last user turn and everything after it, then re-run.

        Editing a sent message is a real history rewrite: the backend drops the
        old user message (and the answer that followed it) before generating
        again — no duplicated turns pile up in the stored conversation.
        """
        text = text.strip()
        if not text:
            yield ErrorEvent(message="The message cannot be empty.", kind="empty_message")
            return
        if self.busy:
            yield ErrorEvent(
                message="A generation is already running.",
                kind="busy",
                hint="Stop it before editing.",
            )
            return
        index = next(
            (i for i in range(len(self.conversation.messages) - 1, -1, -1)
             if self.conversation.messages[i].role == "user"),
            None,
        )
        if index is None:
            yield ErrorEvent(
                message="There is no user message to edit.",
                kind="empty_history",
            )
            yield Done(state=GenerationState.ERROR)
            return
        del self.conversation.messages[index:]
        async for event in self._run_turn(
            text,
            force_search=force_search,
            search_query=None,
            images=[],
            record_user=True,
        ):
            yield event

    async def continue_last(self, *, force_search: bool = False) -> AsyncIterator[ChatEvent]:
        """Resume the last (interrupted) assistant answer in place.

        The partial answer stays in history and the model is nudged to pick up
        exactly where it stopped. The nudge itself is prefill-only: it is sent
        to the model but never stored, so the conversation keeps its real shape
        (one user turn -> one continued assistant turn). New text is appended
        to the same assistant message — no duplicates.
        """
        if self.busy:
            yield ErrorEvent(
                message="A generation is already running.",
                kind="busy",
                hint="Stop it before continuing.",
            )
            return
        last_assistant = next(
            (m for m in reversed(self.conversation.messages) if m.role == "assistant" and m.content),
            None,
        )
        if last_assistant is None:
            yield ErrorEvent(
                message="There is nothing to continue.",
                kind="empty_history",
                hint="Send a message first.",
            )
            yield Done(state=GenerationState.ERROR)
            return

        self.machine.reset()
        queue: asyncio.Queue[ChatEvent | None] = asyncio.Queue()
        self._task = asyncio.create_task(
            self._produce_continue(last_assistant, queue, force_search=force_search)
        )
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
        self._task = None

    async def _run_turn(
        self,
        text: str,
        *,
        force_search: bool,
        search_query: str | None,
        images: list[str],
        record_user: bool,
    ) -> AsyncIterator[ChatEvent]:
        """Shared body of ``send`` / ``regenerate`` — one real generation cycle."""
        if self.busy:
            yield ErrorEvent(
                message="A generation is already running.",
                kind="busy",
                hint="Stop it before sending another message.",
            )
            return
        if self.active_model is None:
            report = await self.startup()
            if self.active_model is None:
                yield ErrorEvent(
                    message=report.error or "No model is available.",
                    kind="model_not_found",
                    hint=report.hint,
                )
                yield Done(state=GenerationState.ERROR)
                return

        if images and self.active_model is not None and self.active_model.supports("vision") is not True:
            yield ErrorEvent(
                message=(
                    f"The model '{self.active_model.name}' does not support images."
                ),
                kind="vision_unsupported",
                hint="Switch to a vision model (e.g. llava, llama3.2-vision, qwen2.5vl).",
            )
            yield Done(state=GenerationState.ERROR)
            return

        self.machine.reset()
        # Harness: авто-детект режима (п.40) + запись user request в Trajectory.
        try:
            mode = self._detect_mode(text)
            self.trajectory.append(
                "user.request", text[:200] or "(images)",
                actor="user", data={"mode": mode},
            )
            if mode != "chat":
                self.bus.emit("agent.started", {"agent": "orchestrator", "mode": mode,
                                                "run_id": self.trajectory.run_id})
        except Exception:
            pass
        # Git Safety (п.12): чекпоинт перед генерацией (один на workspace-сессию).
        try:
            if self.workspace_root and not getattr(self, "_checkpointed", False):
                from axiom.core.git_safety import create_checkpoint as _ckpt

                checkpoint = _ckpt(self.workspace_root)
                self._checkpoint = checkpoint
                self._checkpointed = True
                self.trajectory.append("git.checkpoint", checkpoint.ref[:16],
                                       actor="system", data={"ref": checkpoint.ref})
        except Exception:
            pass
        if record_user:
            self.conversation.messages.append(
                Message(
                    role="user",
                    content=text,
                    created_at=time.time(),
                    images=[img for img in (images or []) if img],
                )
            )
            self.conversation.derive_title()
            # Persist the user turn immediately: the chat appears in the
            # sidebar at once and survives a core crash mid-generation.
            self._save_conversation()
        elif images:
            # Regeneration keeps the original images of the recorded user turn.
            self.conversation.messages.append(
                Message(role="user", content=text, created_at=time.time(), images=list(images))
            )

        queue: asyncio.Queue[ChatEvent | None] = asyncio.Queue()
        self._task = asyncio.create_task(
            self._produce(text, queue, force_search=force_search, search_query=search_query)
        )
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
        self._task = None
        # Persist Trajectory каждого запуска (п.10): resume/fork/replay из store.
        try:
            self.trajectory_store.save(self.trajectory)
        except Exception:
            pass

    # --------------------------------------------------------------- internals

    def _context_budget(self) -> int | None:
        """Real context window when it is known — never a guessed number.

        Priority: explicit ``num_ctx`` override → the model's effective
        ``num_ctx`` from ``/api/show`` → its maximum ``context_length``.
        ``None`` means nothing was reported, so no narrowing decision is made.
        """
        explicit = getattr(self.config, "num_ctx", None)
        if isinstance(explicit, int) and explicit > 0:
            return explicit
        model = self.active_model
        for attribute in ("num_ctx", "context_length"):
            value = getattr(model, attribute, None)
            if isinstance(value, int) and value > 0:
                return value
        return None

    def _context_messages(self, text: str | None = None) -> list[dict]:
        """Convert stored messages into the Ollama request format.

        Old reasoning traces are stripped: they bloat the prompt (a low-resource
        machine pays prompt-eval for every token) and anchored the model to its
        previous thought processes. Only the real answers go back to the model.

        Auto-narrowing: when a real context window is known (``num_ctx`` or the
        model's ``context_length``), the history is additionally trimmed to fit
        it. The stored conversation and the trajectory stay complete — only the
        payload sent to the model shrinks.
        """
        try:
            limit = max(4, min(int(self.config.context_messages), 200))
        except (TypeError, ValueError):
            limit = CONTEXT_MESSAGES
        history: list[dict] = []
        root = self.workspace_root
        focus = mentioned_files(text or "", root)
        for message in self.conversation.messages[-limit:]:
            if message.role in ("user", "assistant") and (message.content or message.images):
                content = message.content
                if message.role == "user" and "@" in content:
                    # ``@path`` mentions expand to real file content for the
                    # MODEL only — the stored history keeps the user's text.
                    content = expand_mentions(content, root)
                # Explicit file mentions are the only files added to this turn.
                # No project-wide dump is performed: the model can still call
                # read_file/search_files for additional files when needed.
                if focus and message.role == "user" and message.content == (text or message.content):
                    content = (
                        content
                        + "\n\nFocus files for this task (use these exact workspace paths):\n"
                        + "\n".join(f"- {path}" for path in focus)
                    )
                entry: dict[str, Any] = {"role": message.role, "content": content}
                if message.images:
                    # Ollama vision models expect base64 images per message.
                    entry["images"] = message.images
                history.append(entry)
        budget = self._context_budget()
        if not budget or not history:
            return history
        from axiom.core.context import ContextManager

        manager = ContextManager(max_tokens=budget)
        before_tokens = manager.estimate(history)
        narrowed = [m for m in manager.prepare(history) if m.get("role") != "system"]
        after_tokens = manager.estimate(narrowed)
        if after_tokens < before_tokens:
            trajectory = getattr(self, "trajectory", None)
            if trajectory is not None:
                try:
                    trajectory.append(
                        "context.narrow",
                        f"auto-narrowed {before_tokens} → {after_tokens} est. tokens "
                        f"(budget {budget})",
                        data={"budget": budget, "before": before_tokens, "after": after_tokens},
                    )
                except Exception:
                    pass
        return narrowed

    def _final_status(self, target: GenerationState) -> StatusChange | None:
        """Emit a terminal status if the state machine allows it."""
        if not self.machine.can(target):
            return None
        self.machine.transition(target)
        return StatusChange(state=target)

    def _final_status_to(self, queue: asyncio.Queue[ChatEvent | None], target: GenerationState) -> None:
        metrics = dict(getattr(self.agent, "metrics", {}) or {})
        status = self._final_status(target)
        if status:
            queue.put_nowait(status)
        queue.put_nowait(
            Done(
                state=target,
                duration_ms=metrics.get("duration_ms", 0),
                tokens_out=metrics.get("tokens_out"),
                tokens_in=metrics.get("tokens_in"),
                tokens_per_second=metrics.get("tokens_per_second"),
                ttft_ms=metrics.get("ttft_ms"),
                load_ms=metrics.get("load_ms"),
                stop_reason=getattr(self.agent, "last_stop_reason", None),
            )
        )

    @staticmethod
    def _empty_answer_event(thinking: str) -> ErrorEvent:
        """Empty-answer protection: never report a false ``Completed``."""
        if thinking:
            return ErrorEvent(
                message="The model returned reasoning but no final answer.",
                kind="empty_response",
                hint="Try rephrasing the request or switch to another model.",
            )
        return ErrorEvent(
            message="The model returned an empty response.",
            kind="empty_response",
            hint="Try again or switch to another model.",
        )

    def _record_turn(self, user_text: str, content: str, thinking: str) -> None:
        """Store the assistant turn (partial output is kept on cancellation)."""
        if content or thinking:
            self.conversation.messages.append(
                Message(
                    role="assistant",
                    content=content,
                    thinking=thinking or None,
                    created_at=time.time(),
                )
            )
        self._save_conversation()

    async def _auto_verify(self) -> None:
        """Авто-verify (п.12): после файловых правок BUILD/TEST/LINT via run_command."""
        if getattr(self, "_verifying", False):
            return
        trajectory = getattr(self, "trajectory", None)
        verify = getattr(self, "verifier", None)
        agent = getattr(self, "agent", None)
        if trajectory is None or verify is None or agent is None:
            return
        edited = [e for e in trajectory.events if e.kind == "tool.call"
                  and str((e.data or {}).get("tool") or "") in
                  ("write_file", "edit_file", "delete_file", "move_file", "copy_file")]
        if not edited:
            return
        self._verifying = True
        try:
            async def _runner(**kwargs):
                res = await self.run_terminal(str(kwargs.get("command") or ""), confirmed=True)
                return {"ok": bool(res.get("ok")),
                        "output": str(res.get("content") or res.get("error") or "")}

            verify._runner = _runner
            kind = "python"
            try:
                from axiom.core.project_index import index_project as _index

                idx = _index(self.workspace_root) if self.workspace_root else None
                langs = [str(v).lower() for v in (idx.languages if idx else [])]
                if any("rust" in v for v in langs):
                    kind = "rust"
                elif any(v in ("typescript", "javascript") for v in langs):
                    kind = "node"
            except Exception:
                kind = "python"
            report = await verify.run(kind=kind)
            agent.last_verify = {"ok": report.ok, "summary": report.summary(),
                                 "errors": list(report.errors)}
            trajectory.append("verify.report", report.summary(),
                              actor="tester", data=dict(agent.last_verify))
            self.bus.emit("test.finished", {"ok": report.ok, "summary": report.summary()})
        finally:
            self._verifying = False

    async def _run_ptc(self, content: str, queue: asyncio.Queue[ChatEvent | None]) -> bool:
        """Code / PTC mode (п.21): исполнить программу шагов из ответа модели."""
        from axiom.core.ptc import parse_program, run_program

        steps = parse_program(content)
        if not steps:
            return False
        for step in steps:
            queue.put_nowait(ToolCallEvent(name=str(step.get("tool") or ""),
                                           arguments=dict(step.get("args") or {})))
        summary = await run_program(
            steps, self.tools, sandbox=self.sandbox, permissions=self.permissions,
            trajectory=self.trajectory,
        )
        for entry in summary.get("results") or []:
            queue.put_nowait(ToolResultEvent(
                name=str(entry.get("tool") or ""),
                ok=bool(entry.get("ok")),
                content=str(entry.get("output") or ""),
                error=entry.get("error"),
            ))
        self.trajectory.append(
            "ptc.run", f"{summary.get('steps', 0)} step(s)",
            actor="coder", data={"ok": summary.get("ok")},
        )
        return True

    async def _produce(
        self,
        text: str,
        queue: asyncio.Queue[ChatEvent | None],
        *,
        force_search: bool,
        search_query: str | None,
    ) -> None:
        """Run the agent loop and push every real event into the queue."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        try:
            model = self.active_model
            if model is None:  # guarded by send(), kept for safety
                queue.put_nowait(ErrorEvent(message="No model is available.", kind="model_not_found"))
                self._final_status_to(queue, GenerationState.ERROR)
                return
            async for event in self.agent.run(
                self._context_messages(text), model, force_search=force_search, search_query=search_query
            ):
                if isinstance(event, ContentChunk):
                    content_parts.append(event.text)
                elif isinstance(event, ReasoningChunk):
                    thinking_parts.append(event.text)
                queue.put_nowait(event)

            metrics = dict(self.agent.metrics)
            self.last_metrics = metrics
            content = "".join(content_parts).strip()
            thinking = "".join(thinking_parts).strip()
            if not content:
                queue.put_nowait(self._empty_answer_event(thinking))
                self._final_status_to(queue, GenerationState.ERROR)
                self._record_turn(text, "", thinking)
                return
            status = self._final_status(GenerationState.COMPLETED)
            if status:
                queue.put_nowait(status)
            queue.put_nowait(
                Done(
                    state=GenerationState.COMPLETED,
                    duration_ms=metrics.get("duration_ms", 0),
                    tokens_out=metrics.get("tokens_out"),
                    tokens_in=metrics.get("tokens_in"),
                    tokens_per_second=metrics.get("tokens_per_second"),
                    ttft_ms=metrics.get("ttft_ms"),
                    load_ms=metrics.get("load_ms"),
                )
            )
            self._record_turn(text, content, thinking)
            try:
                await self._auto_verify()
            except Exception:
                pass
            if self._code_mode:
                try:
                    await self._run_ptc(content, queue)
                except Exception:
                    pass
        except asyncio.CancelledError:
            self._final_status_to(queue, GenerationState.CANCELLED)
            self._record_turn(text, "".join(content_parts).strip(), "".join(thinking_parts).strip())
            raise
        except AxiomError as exc:
            # Provider fallback (п.17): пока контент не стримился — пробуем цепочку.
            if not content_parts and self.router.should_fallback(exc) and self.router.config.chain():
                handled = False
                try:
                    handled = await self._fallback_produce(text, queue, content_parts, thinking_parts)
                except Exception:
                    handled = False
                if handled:
                    return
            queue.put_nowait(ErrorEvent(message=str(exc), kind=exc.kind, hint=exc.hint))
            self._final_status_to(queue, GenerationState.ERROR)
        except Exception as exc:
            queue.put_nowait(
                ErrorEvent(
                    message=f"{type(exc).__name__}: {exc}",
                    kind="internal",
                    hint="This is an internal error. The session is still usable.",
                )
            )
            self._final_status_to(queue, GenerationState.ERROR)
        finally:
            queue.put_nowait(None)

    async def _fallback_produce(
        self,
        text: str,
        queue: asyncio.Queue[ChatEvent | None],
        content_parts: list[str],
        thinking_parts: list[str],
    ) -> bool:
        """Цепочка fallback-провайдеров (п.17): 429/timeout/unavailable → следующий target.

        Возвращает True, если хотя бы один провайдер дал контент (turn завершён
        штатно: StatusChange + Done + запись в историю/trajectory).
        """
        from axiom.core.providers.base import ChatMessage, ProviderError

        raw = self._context_messages()
        messages = [
            ChatMessage(role=str(m.get("role") or "user"),
                        content=str(m.get("content") or ""))
            for m in raw
        ]
        started = time.perf_counter()
        attempts: list[dict] = []
        for target in self.router.config.chain():
            try:
                provider = self.provider_manager.get_provider(target.provider_id)
            except Exception:
                continue
            self.trajectory.append(
                "router.fallback", f"{target.provider_id}/{target.model}",
                actor="router",
                data={"provider_id": target.provider_id, "model": target.model},
            )
            self.bus.emit("agent.step", {"agent": "router", "step": "fallback",
                                         "provider": target.provider_id,
                                         "run_id": self.trajectory.run_id})
            got_content = False
            try:
                async for chunk in provider.stream(target.model, messages):
                    if chunk.thinking:
                        thinking_parts.append(chunk.thinking)
                        queue.put_nowait(ReasoningChunk(text=chunk.thinking))
                    if chunk.content:
                        content_parts.append(chunk.content)
                        queue.put_nowait(ContentChunk(text=chunk.content))
                        got_content = True
                    if chunk.done:
                        break
            except ProviderError as exc:
                attempts.append({"provider": target.provider_id, "error": str(exc)})
                if self.router.should_fallback(exc):
                    continue
                return False
            if got_content:
                content = "".join(content_parts).strip()
                duration_ms = int((time.perf_counter() - started) * 1000)
                status = self._final_status(GenerationState.COMPLETED)
                if status:
                    queue.put_nowait(status)
                queue.put_nowait(Done(state=GenerationState.COMPLETED, duration_ms=duration_ms))
                self._record_turn(text, content, "".join(thinking_parts).strip())
                self.trajectory.append(
                    "router.fallback.ok", f"{target.provider_id}/{target.model}",
                    actor="router", data={"duration_ms": duration_ms},
                )
                return True
            attempts.append({"provider": target.provider_id, "error": "empty response"})
        if attempts:
            self.trajectory.append("router.fallback.failed", "all targets failed",
                                   actor="router", data={"attempts": attempts})
        return False

    async def _produce_continue(
        self,
        partial: Message,
        queue: asyncio.Queue[ChatEvent | None],
        *,
        force_search: bool,
    ) -> None:
        """Continue *partial* in place; fresh text joins the same message."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        try:
            model = self.active_model
            if model is None:  # guarded by continue_last(), kept for safety
                queue.put_nowait(ErrorEvent(message="No model is available.", kind="model_not_found"))
                self._final_status_to(queue, GenerationState.ERROR)
                return
            # Prefill nudge: visible to the model, never stored in history.
            context = self._context_messages()
            context.append(
                {
                    "role": "user",
                    "content": (
                        "Продолжи свой предыдущий ответ ровно с того места, где он оборвался. "
                        "Не повторяй уже написанное, без вступлений — только продолжение."
                    ),
                }
            )
            async for event in self.agent.run(
                context, model, force_search=force_search, search_query=None
            ):
                if isinstance(event, ContentChunk):
                    content_parts.append(event.text)
                elif isinstance(event, ReasoningChunk):
                    thinking_parts.append(event.text)
                queue.put_nowait(event)

            metrics = dict(self.agent.metrics)
            self.last_metrics = metrics
            content = "".join(content_parts).strip()
            thinking = "".join(thinking_parts).strip()
            if not content:
                queue.put_nowait(self._empty_answer_event(thinking))
                self._final_status_to(queue, GenerationState.ERROR)
                return
            status = self._final_status(GenerationState.COMPLETED)
            if status:
                queue.put_nowait(status)
            queue.put_nowait(
                Done(
                    state=GenerationState.COMPLETED,
                    duration_ms=metrics.get("duration_ms", 0),
                    tokens_out=metrics.get("tokens_out"),
                    tokens_in=metrics.get("tokens_in"),
                    tokens_per_second=metrics.get("tokens_per_second"),
                    ttft_ms=metrics.get("ttft_ms"),
                    load_ms=metrics.get("load_ms"),
                )
            )
            # Append in place: partial answer + continuation are one turn.
            partial.content = f"{partial.content.rstrip()}\n\n{content}"
            if thinking:
                partial.thinking = (
                    f"{partial.thinking}\n\n{thinking}" if partial.thinking else thinking
                )
            self._save_conversation()
        except asyncio.CancelledError:
            # A second cancel mid-continuation still keeps what arrived.
            if content_parts:
                partial.content = f"{partial.content.rstrip()}\n\n{''.join(content_parts).strip()}"
            self._final_status_to(queue, GenerationState.CANCELLED)
            self._save_conversation()
            raise
        except AxiomError as exc:
            queue.put_nowait(ErrorEvent(message=str(exc), kind=exc.kind, hint=exc.hint))
            self._final_status_to(queue, GenerationState.ERROR)
        except Exception as exc:
            queue.put_nowait(
                ErrorEvent(
                    message=f"{type(exc).__name__}: {exc}",
                    kind="internal",
                    hint="This is an internal error. The session is still usable.",
                )
            )
            self._final_status_to(queue, GenerationState.ERROR)
        finally:
            queue.put_nowait(None)
