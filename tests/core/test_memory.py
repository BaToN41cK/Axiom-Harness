"""W2.1 Curated Memory — store scopes, banned rejection, tools, budgeted retrieval."""

from __future__ import annotations

from pathlib import Path

from axiom.core.memory import MemoryItem, MemoryStore, MemoryTools
from axiom.core.tools.registry import ToolRegistry


def _make_stores(tmp_path: Path) -> tuple[MemoryStore, MemoryStore]:
    """Fresh isolated stores: AXIOM_HOME is pointed at tmp by the env below."""
    from axiom.core.config import axiom_home

    global_store = MemoryStore()
    project_root = tmp_path / "proj"
    (project_root / ".axiom").mkdir(parents=True)
    project_store = MemoryStore(scope="project", project_root=project_root)
    assert global_store._path().is_relative_to(axiom_home())
    return global_store, project_store


def test_scoped_paths(tmp_path: Path, monkeypatch) -> None:
    """Global memory lives in AXIOM_HOME, project memory in .axiom/."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    global_store, project_store = _make_stores(tmp_path)
    assert global_store._path() == tmp_path / "home" / "memory.json"
    assert project_store._path() == tmp_path / "proj" / ".axiom" / "memory.json"


def test_add_persists_and_reloads(tmp_path: Path, monkeypatch) -> None:
    """An item written by one store instance is visible to a new instance."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    global_store, _ = _make_stores(tmp_path)
    item = MemoryItem(scope="global", content="User prefers dark theme", tags=["ui"])
    assert global_store.add(item) is True
    assert global_store._path().exists()

    fresh = MemoryStore()
    loaded = fresh.get(item.id)
    assert loaded is not None
    assert loaded.content == "User prefers dark theme"
    assert loaded.tags == ["ui"]


def test_banned_content_never_reaches_disk(tmp_path: Path, monkeypatch) -> None:
    """DoD: banned content never reaches disk, not even in memory."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    store, _ = _make_stores(tmp_path)
    banned = MemoryItem(scope="global", category="banned", content="secret must not persist")
    assert store.add(banned) is False
    assert store.get(banned.id) is None
    if store._path().exists():
        raw = store._path().read_text(encoding="utf-8")
        assert "secret must not persist" not in raw


def test_remove_and_list_filters(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    store, _ = _make_stores(tmp_path)
    keep = MemoryItem(content="keep me", category="normal", tags=["fact"])
    drop = MemoryItem(content="drop me", category="sensitive", tags=["pref"])
    store.add(keep)
    store.add(drop)

    assert store.count() == 2
    assert [i.id for i in store.list(category="sensitive")] == [drop.id]
    assert [i.id for i in store.list(tag="fact")] == [keep.id]
    assert store.remove(drop.id) is True
    assert store.remove("nonexistent") is False
    assert store.count() == 1


def test_search_is_case_insensitive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    store, _ = _make_stores(tmp_path)
    store.add(MemoryItem(content="The workspace uses Ruff for linting"))
    store.add(MemoryItem(content="Prefers tea over coffee"))
    hits = store.search("rUfF")
    assert len(hits) == 1
    assert "Ruff" in hits[0].content


def test_retrieve_relevant_respects_budget(tmp_path: Path, monkeypatch) -> None:
    """DoD: only a budgeted slice is retrieved — never the full store."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    store, _ = _make_stores(tmp_path)
    for index in range(20):
        store.add(MemoryItem(content=f"fact number {index} about topic{index}"))
    assert store.count() == 20
    assert len(store.retrieve_relevant("topic3", budget=3)) <= 3
    assert len(store.retrieve_relevant("nonsense query", budget=5)) <= 5


async def test_memory_tools_write_read_forget(tmp_path: Path, monkeypatch) -> None:
    """The model accesses memory only through the three tools."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    store, _ = _make_stores(tmp_path)
    tools = MemoryTools(store)
    registry = ToolRegistry()
    tools.register(registry)

    assert set(registry.names) == {"memory_write", "memory_read", "memory_forget"}
    # write requires approval (ASK), read is ALWAYS — see DoD "through tools".
    assert registry.permission_for("memory_write").value == "ask"
    assert registry.permission_for("memory_read").value == "always"
    assert registry.permission_for("memory_forget").value == "ask"

    written = await registry.execute(
        "memory_write",
        {"content": "User writes Python 3.11+", "category": "normal", "tags": ["stack"]},
        approved=True,
    )
    assert written.ok, written.error
    assert "Memory stored with ID:" in written.content

    read = await registry.execute("memory_read", {"query": "Python"}, approved=True)
    assert read.ok
    assert "User writes Python 3.11+" in read.content

    item_id = store.list()[0].id
    forgotten = await registry.execute("memory_forget", {"item_id": item_id}, approved=True)
    assert forgotten.ok
    assert store.count() == 0


async def test_memory_write_rejects_empty_and_too_long(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    store, _ = _make_stores(tmp_path)
    tools = MemoryTools(store)
    registry = ToolRegistry()
    tools.register(registry)

    empty = await registry.execute("memory_write", {"content": "   "}, approved=True)
    assert empty.ok is False
    long = await registry.execute("memory_write", {"content": "x" * 2001}, approved=True)
    assert long.ok is False
    assert store.count() == 0


async def test_memory_forget_unknown_id_is_structured_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    store, _ = _make_stores(tmp_path)
    registry = ToolRegistry()
    MemoryTools(store).register(registry)
    result = await registry.execute("memory_forget", {"item_id": "missing"}, approved=True)
    assert result.ok is False
    assert "not found" in (result.error or "")


async def test_memory_read_merges_project_and_global(tmp_path: Path, monkeypatch) -> None:
    """Reads see both stores; project items carry their own scope."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    global_store, project_store = _make_stores(tmp_path)
    global_store.add(MemoryItem(content="global fact about pi"))
    project_store.add(MemoryItem(content="project fact about sigma"))
    registry = ToolRegistry()
    MemoryTools(global_store, project_store).register(registry)

    both = await registry.execute("memory_read", {"query": "fact"}, approved=True)
    assert both.ok
    assert "global fact" in both.content
    assert "project fact" in both.content
    assert "project/normal" in both.content

    written = await registry.execute(
        "memory_write", {"content": "belongs to project", "scope": "project"}, approved=True
    )
    assert written.ok
    assert "project scope" in written.content
    # 1 pre-seeded project fact + the new one; global stays untouched.
    assert project_store.count() == 2
    assert global_store.count() == 1


# ----------------------------------------------------------------- integration


def test_session_registers_memory_tools(tmp_path: Path, monkeypatch) -> None:
    """ChatSession exposes the three memory tools out of the box."""
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.history import HistoryStore

    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    session = ChatSession(
        config=Config(model="test-model:latest"),
        history_store=HistoryStore(directory=tmp_path / "history"),
    )
    for name in ("memory_write", "memory_read", "memory_forget"):
        assert name in session.tools.names
    assert session.memory_store.count() == 0


async def test_memory_block_reaches_system_prompt(tmp_path: Path, monkeypatch) -> None:
    """DoD: persisted items are retrieved budgeted and reach the model."""
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.history import HistoryStore
    from axiom.core.memory import MemoryItem
    from axiom.core.models import ModelInfo
    from axiom.core.ollama import OllamaClient, StreamChunk

    class FakeClient(OllamaClient):
        def __init__(self) -> None:
            super().__init__()
            self.chat_calls: list[dict] = []

        async def is_available(self) -> bool:
            return True

        async def version(self) -> str:
            return "0.0-test"

        async def list_models(self) -> list[dict]:
            return [{"name": "test-model:latest", "details": {}, "capabilities": []}]

        async def chat(self, model, messages, **kwargs):  # type: ignore[override]
            self.chat_calls.append({"model": model, "messages": messages})
            yield StreamChunk(content="ok")
            yield StreamChunk(done=True)

    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    client = FakeClient()
    session = ChatSession(
        config=Config(model="test-model:latest"),
        client=client,
        history_store=HistoryStore(directory=tmp_path / "history"),
    )
    session.active_model = ModelInfo(name="test-model:latest", capabilities=[])
    session.memory_store.add(
        MemoryItem(content="User prefers concise answers about pytest")
    )
    history = [{"role": "user", "content": "how should I write pytest tests?"}]
    async for _ in session.agent.run(history, session.active_model):
        pass
    system = client.chat_calls[0]["messages"][0]
    assert system["role"] == "system"
    assert "Relevant memory" in system["content"]
    assert "concise answers about pytest" in system["content"]


def test_tool_scope_advertises_memory() -> None:
    """Deterministic scope: memory markers expose memory tools, others don't."""
    from axiom.core.performance import tool_scope

    scope = tool_scope("запомни, что я люблю кофе")
    assert scope is not None
    assert {"memory_read", "memory_write", "memory_forget"} <= set(scope)
    plain = tool_scope("what is the capital of France")
    assert plain is None or "memory_read" not in plain


def test_agent_without_memory_never_injects_block(tmp_path: Path, monkeypatch) -> None:
    """No memory attached → no memory block, no crash."""
    from axiom.core.agent import Agent
    from axiom.core.config import Config
    from axiom.core.state_machine import GenerationStateMachine
    from axiom.core.tools.registry import ToolRegistry

    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    agent = Agent(
        None,  # type: ignore[arg-type]
        config=Config(model="m"),
        registry=ToolRegistry(),
        machine=GenerationStateMachine(),
    )
    assert agent._memory is None


async def test_relevant_is_budgeted_across_stores(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    global_store, project_store = _make_stores(tmp_path)
    for index in range(10):
        global_store.add(MemoryItem(content=f"global note {index}"))
        project_store.add(MemoryItem(content=f"project note {index}"))
    tools = MemoryTools(global_store, project_store)
    assert len(tools.relevant("note", budget=4)) <= 4
    assert tools.relevant("note", budget=0) == []


def test_retrieve_relevant_prefers_matches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    store, _ = _make_stores(tmp_path)
    store.add(MemoryItem(content="uses Pytest for testing"))
    store.add(MemoryItem(content="likes jazz music"))
    store.add(MemoryItem(content="deploy target is Windows"))
    hits = store.retrieve_relevant("how do we run pytest tests", budget=2)
    assert hits
    assert "Pytest" in hits[0].content


def test_corrupt_file_does_not_crash(tmp_path: Path, monkeypatch) -> None:
    """A corrupt memory.json must never crash the application."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    home.mkdir(parents=True)
    (home / "memory.json").write_text("{not json", encoding="utf-8")
    store = MemoryStore()
    assert store.count() == 0
    store.add(MemoryItem(content="works anyway"))
    assert store.count() == 1
