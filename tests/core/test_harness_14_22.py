"""Тесты 14-22: skills, router, parallel, project, mcp, plugins, presets, git."""
from __future__ import annotations

from axiom.core.plugins import PluginManifest, PluginRegistry
from axiom.core.presets import PresetStore, detect_mode
from axiom.core.router import ModelRouter, RouterConfig, classify_task
from axiom.core.skills import SkillRegistry


def test_skills_resolve_python_and_tauri():
    reg = SkillRegistry()
    hits = reg.resolve_for_task("pytest падает, проверь python модуль")
    assert any(s.id == "python" for s in hits)
    assert any(s.id == "debugging" or s.id == "testing" for s in hits)
    tauri = reg.get("tauri")
    assert tauri is not None
    assert "cargo" in " ".join(tauri.commands).lower() or "tauri" in tauri.id


def test_router_classifies_and_picks_coding_model():
    from axiom.core.providers.base import ModelProfile
    from axiom.core.providers.catalog import ModelCatalog
    assert classify_task("исправь баг в коде") == "coding"
    catalog = ModelCatalog()
    catalog.add([ModelProfile(id="cheap", provider_id="x"),
                 ModelProfile(id="coder-max", provider_id="x", coding=True, tool_calling=True)])
    router = ModelRouter()
    target = router.route("исправь баг в коде", catalog)
    assert target is not None
    assert target.model == "coder-max"


def test_router_fallback_chain_and_detection():
    from axiom.core.router import RouteTarget
    router = ModelRouter(RouterConfig(primary=RouteTarget("a", "m1"),
                                      fallbacks=[RouteTarget("b", "m2")]))
    assert router.should_fallback("429 rate limited") is True
    assert router.should_fallback("all good") is False
    nxt = router.next_fallback(RouteTarget("a", "m1"))
    assert nxt is not None and nxt.provider_id == "b"


async def test_parallel_runs_subagents_concurrently():
    from axiom.core.parallel import run_parallel

    async def _runner(**kwargs):
        return {"ok": True, "agent": kwargs.get("agent")}

    out = await run_parallel([{"agent": "coder", "task": "t1"},
                              {"agent": "tester", "task": "t2"}], _runner)
    assert out.merged["count"] == 2
    assert out.merged["ok"] is True


def test_project_index_detects_repo(tmp_path):
    from axiom.core.project_index import ProjectMemory, index_project
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "main.py").write_text("print(1)\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_x(): pass\n", encoding="utf-8")
    index = index_project(root)
    assert "Python" in index.languages
    assert index.build_system == "pyproject.toml"
    assert "main.py" in index.entry_points
    mem = ProjectMemory(root)
    mem.save_index(index)
    assert (root / ".axiom" / "project.json").exists()
    assert mem.load_index() is not None


def test_project_index_prunes_heavy_dirs_and_stays_fast(tmp_path):
    """Regression: the walker must prune .git/node_modules/.venv.

    The old ``rglob("*") + is_file()`` descended into those directories and
    issued an extra ``stat()`` per entry, which made every project switch take
    seconds (23k+ syscalls on a mid-size repo) and froze the whole bridge.
    """
    import time

    from axiom.core.project_index import _collect_files, index_project

    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "main.py").write_text("print(1)\n", encoding="utf-8")
    (root / "package.json").write_text('{"name":"x"}\n', encoding="utf-8")
    # Noise that must never be indexed.
    for noisy in (".git", "node_modules/pkg", ".venv/lib"):
        deep = root / noisy
        deep.mkdir(parents=True)
        (deep / "junk.py").write_text("x = 1\n", encoding="utf-8")

    files = _collect_files(root)
    names = {p.name for p in files}
    assert "main.py" in names and "package.json" in names
    assert "junk.py" not in names, "heavy directories leaked into the index"

    # A 4000-file cap keeps the walk bounded on huge repositories.
    assert len(_collect_files(root, limit=2)) == 2

    start = time.perf_counter()
    index = index_project(root)
    elapsed = time.perf_counter() - start
    assert "Python" in index.languages
    assert index.build_system == "package.json"
    assert "main.py" in index.entry_points
    assert elapsed < 2.0, f"index_project took {elapsed:.2f}s — walker regressed"


async def test_mcp_manager_registers_tools_without_server():
    from axiom.core.mcp import MCPManager
    from axiom.core.tools.registry import ToolRegistry
    mgr = MCPManager()
    mgr.add_server("demo", ["does-not-exist-axiom-mcp"])
    registry = ToolRegistry()
    names = await mgr.register_all(registry)
    assert names == []
    assert mgr.servers() == ["demo"]


def test_plugin_registry_install_list_remove(tmp_path):
    reg = PluginRegistry()
    reg.install(PluginManifest(name="github", version="1.0",
                               capabilities=("tools",), tools=("gh_pr",)))
    assert reg.get("github") is not None
    path = tmp_path / "plugins.json"
    reg.save(path)
    reg2 = PluginRegistry()
    reg2.load(path)
    assert reg2.get("github") is not None
    assert reg.remove("github") is True


def test_modes_detect_debug_review_research():
    assert detect_mode("Почему падает приложение?") == "debug"
    assert detect_mode("Проверь этот PR") == "review"
    assert detect_mode("Что делает этот проект?") == "research"
    assert detect_mode("Привет") == "chat"


def test_preset_store_crud():
    from axiom.core.presets import AgentPreset
    store = PresetStore()
    store.save_preset(AgentPreset(name="mine", provider_id="deepseek", model="deepseek-chat"))
    assert store.get("mine") is not None
    assert any(p.name == "coding" for p in store.list())
    assert store.remove("mine") is True


def test_git_safety_checkpoint_on_non_repo(tmp_path):
    from axiom.core.git_safety import create_checkpoint, diff_stats
    checkpoint = create_checkpoint(tmp_path)
    assert checkpoint.root != ""
    stats = diff_stats(tmp_path)
    assert stats["files"] == 0


def test_trajectory_viewer_and_detail():
    from axiom.core.trajectory import Trajectory
    traj = Trajectory(actor="orchestrator")
    traj.append("user.request", "fix bug", data={"mode": "debug"})
    traj.append("tool.call", "read_file main.py",
                data={"tool": "read_file", "arguments": {"path": "main.py"}})
    view = traj.viewer()
    assert view["run_id"] == traj.run_id
    assert len(view["lines"]) == 2
    assert view["lines"][0]["time"].count(":") == 2
    detail = traj.detail(2)
    assert detail is not None
    assert detail["data"]["tool"] == "read_file"
    assert traj.detail(999) is None


def test_ptc_parse_and_run_program():
    import asyncio

    from axiom.core.config import Config
    from axiom.core.permissions import PermissionManager
    from axiom.core.ptc import parse_program, run_program
    from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult
    from axiom.core.tools.registry import ToolRegistry

    text = 'План:\n```axiom-program\n[{"tool": "echo", "args": {"msg": "hi"}}]\n```'
    steps = parse_program(text)
    assert steps == [{"tool": "echo", "args": {"msg": "hi"}}]
    assert parse_program("no program here") == []

    async def _echo(msg: str) -> ToolResult:
        return ToolResult(name="echo", ok=True, content=msg)

    registry = ToolRegistry()
    registry.register(ToolDefinition(name="echo", description="e",
                                     permission=ToolPermission.ALWAYS), _echo)
    out = asyncio.run(run_program(
        steps, registry, permissions=PermissionManager(config=Config())
    ))
    assert out["ok"] is True
    assert out["results"][0]["output"] == "hi"


async def test_ptc_enforces_tool_permission_and_sandbox_ask():
    from axiom.core.config import Config
    from axiom.core.permissions import PermissionManager
    from axiom.core.ptc import run_program
    from axiom.core.sandbox import Sandbox, SandboxLevel, SandboxPolicy
    from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult
    from axiom.core.tools.registry import ToolRegistry

    executed: list[str] = []

    async def _danger(**kwargs) -> ToolResult:
        executed.append("ran")
        return ToolResult(name="danger", ok=True, content="ran")

    registry = ToolRegistry()
    registry.register(ToolDefinition(name="danger", description="d",
                                     permission=ToolPermission.ASK), _danger)
    steps = [{"tool": "danger", "args": {}}]
    permissions = PermissionManager(config=Config(permission_mode="ask"))
    denied = await run_program(steps, registry, permissions=permissions)
    assert denied["results"][0]["ok"] is False
    assert "permission" in denied["results"][0]["error"].lower()
    assert executed == []

    box = Sandbox()
    box.set_policy(SandboxLevel.EXECUTE, SandboxPolicy.ASK)
    auto_permissions = PermissionManager(config=Config(permission_mode="auto_approve_all"))
    sandbox_denied = await run_program(steps, registry, sandbox=box,
                                       permissions=auto_permissions)
    assert sandbox_denied["results"][0]["ok"] is False
    assert "sandbox" in sandbox_denied["results"][0]["error"].lower()
    assert executed == []

    box.ask_callback = lambda tool, args: True
    approved_permissions = PermissionManager(
        config=Config(permission_mode="auto_approve_safe"),
        request_callback=lambda tool, args: True,
    )
    allowed = await run_program(steps, registry, sandbox=box,
                                 permissions=approved_permissions)
    assert allowed["results"][0]["ok"] is True
    assert executed == ["ran"]


async def test_ptc_fails_closed_when_permission_classifier_raises():
    from axiom.core.ptc import run_program
    from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult
    from axiom.core.tools.registry import ToolRegistry

    executed: list[bool] = []

    async def _handler(**kwargs) -> ToolResult:
        executed.append(True)
        return ToolResult(name="danger", ok=True)

    def _broken_classifier(name: str, args: dict) -> ToolPermission:
        raise RuntimeError("permission backend failed")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="danger", description="danger", permission=ToolPermission.ALWAYS),
        _handler,
        permission_for=_broken_classifier,
    )
    result = await run_program([{"tool": "danger", "args": {}}], registry)
    assert result["ok"] is False
    assert "Permission check failed" in result["results"][0]["error"]
    assert executed == []


async def test_sandbox_deny_blocks_before_execution():
    """DENY-политика не даёт хендлеру выполниться."""
    from axiom.core.agent import Agent
    from axiom.core.config import Config
    from axiom.core.models import ModelInfo
    from axiom.core.sandbox import Sandbox, SandboxLevel, SandboxPolicy
    from axiom.core.state_machine import GenerationStateMachine
    from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult
    from axiom.core.tools.registry import ToolRegistry

    executed: list[str] = []

    async def _danger(**kwargs) -> ToolResult:
        executed.append("ran")
        return ToolResult(name="danger", ok=True, content="ran")

    registry = ToolRegistry()
    registry.register(ToolDefinition(name="danger", description="d",
                                     permission=ToolPermission.ALWAYS), _danger)
    box = Sandbox()
    box.set_policy(SandboxLevel.EXECUTE, SandboxPolicy.DENY)

    class _Client:
        async def chat(self, *args, **kwargs):
            from axiom.core.ollama import StreamChunk, ToolCallRequest
            yield StreamChunk(tool_calls=[ToolCallRequest(name="danger", arguments={})])
            yield StreamChunk(content="done", done=True,
                              metrics={"eval_count": 1, "prompt_eval_count": 1})

    agent = Agent(_Client(), config=Config(), registry=registry,  # type: ignore[arg-type]
                  machine=GenerationStateMachine())
    agent.attach_harness(sandbox=box)
    events = [e async for e in agent.run([{"role": "user", "content": "hi"}],
                                         ModelInfo(name="m"))]
    failures = [e for e in events if getattr(e, "type", "") == "tool_result" and not e.ok]
    assert failures and "sandbox" in (failures[0].error or "")
    assert executed == []


async def test_agent_skill_injects_and_writes_trajectory():
    from axiom.core.agent import Agent
    from axiom.core.config import Config
    from axiom.core.models import ModelInfo
    from axiom.core.router import ModelRouter
    from axiom.core.skills import SkillRegistry
    from axiom.core.state_machine import GenerationStateMachine
    from axiom.core.tools.registry import ToolRegistry
    from axiom.core.trajectory import Trajectory

    seen_systems: list[str] = []

    class _Client:
        async def chat(self, model, messages, **kwargs):
            for m in messages:
                if m.get("role") == "system":
                    seen_systems.append(m.get("content") or "")
            from axiom.core.ollama import StreamChunk
            yield StreamChunk(content="ok", done=True,
                              metrics={"eval_count": 1, "prompt_eval_count": 1})

    traj = Trajectory(actor="tester")
    agent = Agent(_Client(), config=Config(), registry=ToolRegistry(),  # type: ignore[arg-type]
                  machine=GenerationStateMachine())
    agent.attach_harness(trajectory=traj, skills=SkillRegistry(), router=ModelRouter())
    events = [e async for e in agent.run(
        [{"role": "user", "content": "напиши python функцию с pytest"}],
        ModelInfo(name="m"))]
    assert any(getattr(e, "type", "") == "content" for e in events)
    assert any("Skill: Python" in s for s in seen_systems)
    assert any(e.kind == "context.skill" for e in traj.events)


async def test_chat_session_harness_objects_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config

    cfg = Config()
    cfg.save_history = False
    session = ChatSession(config=cfg)
    assert session._detect_mode("Исправь баг падения") == "debug"
    assert session._checkpointed is False
    session.trajectory.append("user.request", "test", actor="user",
                              data={"mode": session._detect_mode("test")})
    path = session.trajectory_store.save(session.trajectory)
    assert path.exists()
    loaded = session.trajectory_store.load(session.trajectory.run_id)
    assert loaded is not None and len(loaded.events) == 1


async def test_agent_forces_edit_after_plan_and_feeds_tool_errors_to_model():
    from axiom.core.agent import Agent
    from axiom.core.config import Config
    from axiom.core.models import ModelInfo
    from axiom.core.ollama import StreamChunk, ToolCallRequest
    from axiom.core.state_machine import GenerationStateMachine
    from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult
    from axiom.core.tools.registry import ToolRegistry

    seen_messages: list[list[dict]] = []
    calls = 0

    async def read_missing(**kwargs):
        return ToolResult(name="read_file", ok=False, error="No such file: missing.py")

    async def edit_file(**kwargs):
        return ToolResult(name="edit_file", ok=True, content="edited")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="read_file", description="read", permission=ToolPermission.ALWAYS),
        read_missing,
    )
    registry.register(
        ToolDefinition(name="edit_file", description="edit", permission=ToolPermission.ALWAYS),
        edit_file,
    )

    class _Client:
        async def chat(self, model, messages, **kwargs):
            nonlocal calls
            seen_messages.append(list(messages))
            calls += 1
            if calls == 1:
                yield StreamChunk(content="Сначала изучу проект и составлю план", done=True)
            elif calls == 2:
                yield StreamChunk(
                    tool_calls=[ToolCallRequest(name="edit_file", arguments={
                        "path": "x.py", "old_text": "a", "new_text": "b",
                    })],
                    done=True,
                )
            else:
                yield StreamChunk(content="Готово", done=True)

    agent = Agent(_Client(), config=Config(), registry=registry, machine=GenerationStateMachine())  # type: ignore[arg-type]
    events = [event async for event in agent.run(
        [{"role": "user", "content": "сделай fallback между providers в проекте"}],
        ModelInfo(name="m"),
    )]
    assert 2 <= calls <= 3
    assert any(getattr(event, "type", "") == "tool_call" for event in events)
    assert any(
        "Use edit_file or write_file now" in str(message.get("content"))
        for message in seen_messages[1]
    )


async def test_external_tool_capable_model_gets_workspace_schemas():
    from axiom.core.agent import Agent
    from axiom.core.config import Config
    from axiom.core.models import ModelInfo
    from axiom.core.state_machine import GenerationStateMachine
    from axiom.core.tools.filesystem import WorkspaceTools
    from axiom.core.tools.registry import ToolRegistry

    registry = ToolRegistry()
    WorkspaceTools().register(registry)
    schemas = Agent(
        object(), config=Config(workspace_tools_enabled=True), registry=registry,
        machine=GenerationStateMachine(),  # type: ignore[arg-type]
    )._tool_schemas(
        ModelInfo(name="external/any-model", capabilities=["tools"]),
        "исправь проект и добавь новую функцию",
    )
    assert schemas
    assert {schema["function"]["name"] for schema in schemas} >= {
        "read_file", "edit_file", "write_file", "search_text", "search_files"
    }


async def test_agent_returns_failed_tool_result_to_next_model_pass():
    from axiom.core.agent import Agent
    from axiom.core.config import Config
    from axiom.core.models import ModelInfo
    from axiom.core.ollama import StreamChunk, ToolCallRequest
    from axiom.core.state_machine import GenerationStateMachine
    from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult
    from axiom.core.tools.registry import ToolRegistry

    calls = 0
    seen: list[list[dict]] = []

    async def read_missing(**kwargs):
        return ToolResult(name="read_file", ok=False, error="No such file: missing.py")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="read_file", description="read", permission=ToolPermission.ALWAYS),
        read_missing,
    )

    class _Client:
        async def chat(self, model, messages, **kwargs):
            nonlocal calls
            calls += 1
            seen.append(list(messages))
            if calls == 1:
                yield StreamChunk(
                    tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "missing.py"})],
                    done=True,
                )
            else:
                yield StreamChunk(content="восстановился после ошибки", done=True)

    agent = Agent(_Client(), config=Config(), registry=registry, machine=GenerationStateMachine())  # type: ignore[arg-type]
    [event async for event in agent.run(
        [{"role": "user", "content": "прочитай проект и исправь fallback"}],
        ModelInfo(name="m"),
    )]
    assert calls == 3
    assert "ERROR: No such file: missing.py" in str(seen[1])


async def test_agent_workspace_edit_runs_with_auto_safe_permissions(tmp_path):
    from axiom.core.agent import Agent
    from axiom.core.config import Config
    from axiom.core.models import ModelInfo
    from axiom.core.ollama import StreamChunk, ToolCallRequest
    from axiom.core.permissions import PermissionManager
    from axiom.core.state_machine import GenerationStateMachine
    from axiom.core.tools.filesystem import WorkspaceTools
    from axiom.core.tools.registry import ToolRegistry

    target = tmp_path / "main.py"
    target.write_text("old\n", encoding="utf-8")
    registry = ToolRegistry()
    WorkspaceTools(tmp_path).register(registry)
    calls = 0

    class _Client:
        async def chat(self, model, messages, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                yield StreamChunk(tool_calls=[ToolCallRequest(
                    name="edit_file",
                    arguments={"path": "main.py", "old_text": "old", "new_text": "new"},
                )], done=True)
            else:
                yield StreamChunk(content="Готово", done=True)

    agent = Agent(_Client(), config=Config(workspace_tools_enabled=True), registry=registry,
                  machine=GenerationStateMachine())  # type: ignore[arg-type]
    agent.attach_harness(permissions=PermissionManager(
        config=Config(permission_mode="auto_approve_safe")
    ))
    events = [event async for event in agent.run(
        [{"role": "user", "content": "исправь main.py"}],
        ModelInfo(name="m", capabilities=["tools"]),
    )]
    assert any(getattr(event, "type", "") == "tool_result" and event.ok for event in events)
    assert target.read_text(encoding="utf-8") == "new\n"



def test_should_fallback_reads_real_error_kind():
    from axiom.core.errors import OllamaUnavailableError
    from axiom.core.router import ModelRouter

    router = ModelRouter()
    # ``kind`` carries "unavailable" even when the message does not.
    assert router.should_fallback(OllamaUnavailableError("Timed out.")) is True
    assert router.should_fallback(ValueError("bad json")) is False


async def test_provider_fallback_chain_is_used_when_nothing_streamed(tmp_path, monkeypatch):
    """п.17: AxiomError до первого чанка → следующий провайдер цепочки."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.errors import OllamaUnavailableError
    from axiom.core.events import ContentChunk, Done
    from axiom.core.history import HistoryStore
    from axiom.core.models import ModelInfo
    from axiom.core.providers.base import StreamChunk as ProviderChunk
    from axiom.core.state import GenerationState

    cfg = Config(model="test-model:latest")
    cfg.save_history = False
    cfg.router_primary = {"provider_id": "ollama", "model": "primary-model"}
    cfg.router_fallbacks = [{"provider_id": "backup", "model": "fallback-model"}]
    session = ChatSession(config=cfg, history_store=HistoryStore(directory=tmp_path / "h"))
    session.active_model = ModelInfo(name="test-model:latest")

    asked: list[tuple[str, str]] = []

    class _Provider:
        async def stream(self, model, messages, **kwargs):
            asked.append((model, str(messages[-1].content)))
            yield ProviderChunk(content="from fallback", done=True)

    class _Manager:
        def get_provider(self, pid):
            assert pid == "backup"
            return _Provider()

    session.provider_manager = _Manager()  # type: ignore[assignment]

    async def _boom(*args, **kwargs):
        raise OllamaUnavailableError("Ollama request timed out.")
        yield  # pragma: no cover - keeps this an async generator

    session.agent.run = _boom  # type: ignore[method-assign]

    events = [event async for event in session.send("hi")]
    text = "".join(e.text for e in events if isinstance(e, ContentChunk))
    assert text == "from fallback"
    assert asked and asked[0][0] == "fallback-model"
    assert any(isinstance(e, Done) and e.state is GenerationState.COMPLETED for e in events)
    kinds = [e.kind for e in session.trajectory.events]
    assert "router.fallback" in kinds
    assert "router.fallback.ok" in kinds
    assert "router.fallback.failed" not in kinds


async def test_provider_fallback_skipped_without_chain(tmp_path, monkeypatch):
    """Без настроенной цепочки поведение прежнее: реальный ErrorEvent."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.errors import OllamaUnavailableError
    from axiom.core.events import ErrorEvent
    from axiom.core.history import HistoryStore
    from axiom.core.models import ModelInfo

    cfg = Config(model="test-model:latest")
    cfg.save_history = False
    session = ChatSession(config=cfg, history_store=HistoryStore(directory=tmp_path / "h"))
    session.active_model = ModelInfo(name="test-model:latest")

    async def _boom(*args, **kwargs):
        raise OllamaUnavailableError("Ollama request timed out.")
        yield  # pragma: no cover

    session.agent.run = _boom  # type: ignore[method-assign]

    events = [event async for event in session.send("hi")]
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert errors and errors[0].kind == "ollama_unavailable"
    assert not any(e.kind.startswith("router.fallback") for e in session.trajectory.events)

def test_skill_registry_pins_skills_for_context():
    from axiom.core.skills import SkillRegistry

    reg = SkillRegistry()
    assert reg.pin("git") is True
    assert reg.pin("nope") is False
    assert reg.pinned() == ["git"]
    hits = reg.resolve_for_task("привет")  # без маркеров
    assert [s.id for s in hits] == ["git"]
    assert reg.unpin("git") is True
    assert reg.unpin("git") is False
    assert reg.resolve_for_task("привет") == []


def test_plugin_manifest_roundtrip_and_skill_pin(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.plugins import PluginManifest

    cfg = Config()
    cfg.save_history = False
    session = ChatSession(config=cfg)
    session.install_plugin(PluginManifest(name="gitp", skills=("git",)))
    assert session.skills.pinned() == ["git"]
    assert (tmp_path / "home" / "plugins.json").exists()
    # Новый сеанс подхватывает плагин из диска при подготовке.
    fresh = ChatSession(config=cfg)
    assert fresh.load_plugins() == ["gitp"]
    assert "git" in fresh.skills.pinned()
    # Removing one pin source must not clear another source's pin.
    fresh.skills.pin("git", source="preset")
    assert fresh.remove_plugin("gitp") is True
    assert "git" in fresh.skills.pinned()
    assert fresh.skills.unpin("git", source="preset") is True
    assert "git" not in fresh.skills.pinned()
    assert fresh.plugins.get("gitp") is None
    assert fresh.remove_plugin("gitp") is False
    assert fresh.load_plugins() == []
    assert "git" not in fresh.skills.pinned()


def test_preset_and_mode_application(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.presets import AgentPreset

    cfg = Config()
    cfg.save_history = False
    session = ChatSession(config=cfg)
    session.presets.save_preset(AgentPreset(
        "strict", provider_id="remote", model="model-x", tools=("read_file",),
        permission="ask", temperature=0.1, reasoning="high", context_tokens=4096,
        budget="economy", fallbacks=("backup",), skills=("security",),
    ))
    applied = session.apply_preset("strict")
    assert applied["ok"] is True
    assert session.config.temperature == 0.1
    assert session.config.permission_mode == "ask"
    assert session.router.config.budget == "economy"
    assert session.config.think == "high"
    assert session.config.num_ctx == 4096
    assert session.skills.pinned() == ["security"]
    assert applied["unsupported"] == ["fallbacks", "model", "provider_id", "tools"]
    session.presets.save_preset(AgentPreset("other", skills=("git",)))
    session.apply_preset("other")
    assert session.skills.pinned() == ["git"]
    assert "security" not in session.skills.pinned()
    assert session.apply_preset("missing")["ok"] is False

    info = session.set_mode("code-agent")
    assert info["ok"] is True
    assert session._code_mode is True
    assert session.set_mode("nope")["ok"] is False
    assert any(e.kind == "mode.switch" for e in session.trajectory.events)

async def test_ptc_mode_executes_program_from_answer(tmp_path, monkeypatch):
    """п.21: в code-agent режиме программа тулов из ответа исполняется ядром."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.events import ContentChunk, ToolCallEvent, ToolResultEvent
    from axiom.core.history import HistoryStore
    from axiom.core.models import ModelInfo
    from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult

    cfg = Config(model="test-model:latest")
    cfg.save_history = False
    session = ChatSession(config=cfg, history_store=HistoryStore(directory=tmp_path / "h"))
    session.active_model = ModelInfo(name="test-model:latest")
    session.set_mode("code-agent")

    ran: list[str] = []

    async def _handler(**kwargs) -> ToolResult:
        ran.append(str(kwargs.get("path")))
        return ToolResult(name="read_file", ok=True, content="file body")

    session.tools.register(
        ToolDefinition(name="read_file", description="read", permission=ToolPermission.ALWAYS),
        _handler,
    )
    program = 'готово\n```axiom-program\n[{"tool": "read_file", "args": {"path": "main.py"}}]\n```\n'

    async def _run(*args, **kwargs):
        yield ContentChunk(text=program)

    session.agent.run = _run  # type: ignore[method-assign]

    events = [event async for event in session.send("прочитай main.py")]
    calls = [e for e in events if isinstance(e, ToolCallEvent)]
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert ran == ["main.py"]
    assert calls and calls[0].name == "read_file"
    assert results and results[0].ok and results[0].content == "file body"
    assert any(e.kind == "ptc.run" for e in session.trajectory.events)


async def test_ptc_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.events import ContentChunk, ToolCallEvent
    from axiom.core.history import HistoryStore
    from axiom.core.models import ModelInfo

    cfg = Config(model="test-model:latest")
    cfg.save_history = False
    session = ChatSession(config=cfg, history_store=HistoryStore(directory=tmp_path / "h"))
    session.active_model = ModelInfo(name="test-model:latest")
    assert session._code_mode is False

    async def _run(*args, **kwargs):
        yield ContentChunk(text='```axiom-program\n[{"tool": "read_file", "args": {}}]\n```')

    session.agent.run = _run  # type: ignore[method-assign]

    events = [event async for event in session.send("hi")]
    assert not [e for e in events if isinstance(e, ToolCallEvent)]
    assert not any(e.kind == "ptc.run" for e in session.trajectory.events)


async def test_parallel_agents_run_through_orchestrator(tmp_path, monkeypatch):
    """п.8/28: параллельный прогон сабагентов реально вызывает модель."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    from axiom.core.agent import Agent
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.events import ContentChunk
    from axiom.core.history import HistoryStore
    from axiom.core.models import ModelInfo

    cfg = Config(model="test-model:latest")
    cfg.save_history = False
    session = ChatSession(config=cfg, history_store=HistoryStore(directory=tmp_path / "h"))
    session.active_model = ModelInfo(name="test-model:latest")

    import asyncio

    seen: list[str] = []
    agents: list[Agent] = []
    all_started = asyncio.Event()

    async def _run(agent, history, model, **kwargs):
        agents.append(agent)
        seen.append(str(history[-1]["content"]))
        if len(agents) == 4:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=2)
        agent._config.context_messages = 7
        agent._registry.unregister("read_file")
        agent._trajectory.append("request.only", "isolated")
        yield ContentChunk(text="subagent answer")

    monkeypatch.setattr(Agent, "run", _run)

    original_config = session.config.context_messages
    original_registry_names = set(session.tools.names)
    out = await session.run_parallel_agents("исправь баг в коде", limit=4)

    assert len(agents) == 4 and len(set(seen)) == 1
    assert out["results"] and out["merged"]["count"] == len(out["results"]) == 4
    assert len({id(agent) for agent in agents}) == 4
    assert len({id(agent._config) for agent in agents}) == 4
    assert len({id(agent._registry) for agent in agents}) == 4
    assert len({id(agent._machine) for agent in agents}) == 4
    assert len({id(agent._trajectory) for agent in agents}) == 4
    assert len({id(agent._router) for agent in agents}) == 4
    assert len({id(agent._catalog) for agent in agents}) == 4
    assert len({id(agent._skills) for agent in agents}) == 4
    assert all(agent._registry.get("read_file") is None for agent in agents)
    assert session.config.context_messages == original_config
    assert set(session.tools.names) == original_registry_names
    assert session.tools.get("read_file") is not None
    assert not any(e.kind == "request.only" for e in session.trajectory.events)
    assert any(e.kind == "orchestrator.plan" for e in session.trajectory.events)
    assert any(e.kind == "orchestrator.merge" for e in session.trajectory.events)
