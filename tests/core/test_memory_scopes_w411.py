"""W4.11 memory scopes: task/session stores, deterministic precedence, archiving.

Every case runs on a tmp AXIOM_HOME with no network: memory is pure local disk.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom.core.config import axiom_home
from axiom.core.memory import SCOPE_ORDER, MemoryItem, MemoryStore, MemoryTools
from axiom.core.tools.registry import ToolRegistry


TASK_ID = "task411"
SESSION_ID = "conv411"


def _global_store() -> MemoryStore:
    return MemoryStore()


def _project_store(tmp_path: Path) -> MemoryStore:
    root = tmp_path / "proj"
    (root / ".axiom").mkdir(parents=True, exist_ok=True)
    return MemoryStore(scope="project", project_root=root)


def _task_store(task_id: str = TASK_ID) -> MemoryStore:
    return MemoryStore(scope="task", task_id=task_id)


def _session_store(session_id: str = SESSION_ID) -> MemoryStore:
    return MemoryStore(scope="session", session_id=session_id)


# ------------------------------------------------------------------- scopes


def test_scope_read_order_is_most_specific_first() -> None:
    """The documented precedence: task -> session -> project -> global."""
    assert SCOPE_ORDER == ("task", "session", "project", "global")


def test_four_scope_paths_are_distinct(tmp_path: Path, monkeypatch) -> None:
    """Each scope has its own file, so one owner can never write another's."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    paths = {
        "global": _global_store()._path(),
        "project": _project_store(tmp_path)._path(),
        "task": _task_store()._path(),
        "session": _session_store()._path(),
    }
    assert paths["global"] == tmp_path / "home" / "memory.json"
    assert paths["project"] == tmp_path / "proj" / ".axiom" / "memory.json"
    assert paths["task"] == tmp_path / "home" / "memory" / "tasks" / f"{TASK_ID}.json"
    assert paths["session"] == tmp_path / "home" / "memory" / "sessions" / f"{SESSION_ID}.json"
    assert len(set(paths.values())) == 4


@pytest.mark.parametrize("bad_id", ["../escape", "with space", "", None, "x" * 65])
def test_owner_ids_cannot_carry_a_path(bad_id: object) -> None:
    """Task/session ids become file names, so any path shape is refused."""
    with pytest.raises(ValueError):
        MemoryStore(scope="task", task_id=bad_id)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        MemoryStore(scope="session", session_id=bad_id)  # type: ignore[arg-type]


def test_unknown_scope_is_refused() -> None:
    with pytest.raises(ValueError):
        MemoryStore(scope="conversation")  # type: ignore[arg-type]


def test_scope_without_owner_is_refused() -> None:
    with pytest.raises(ValueError):
        MemoryStore(scope="project")
    with pytest.raises(ValueError):
        MemoryStore(scope="task")


def test_task_memory_survives_a_restart(tmp_path: Path, monkeypatch) -> None:
    """A task note written by one process is readable after a restart."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    store = _task_store()
    assert store.add(MemoryItem(content="Task decided to keep the old API")) is True
    assert store.count() == 1

    reloaded = _task_store()
    assert [item.content for item in reloaded.list()] == ["Task decided to keep the old API"]
    # Another task never sees it: the store is keyed by its owner id.
    assert _task_store("other411").count() == 0


def test_global_memory_is_untouched_by_task_writes(tmp_path: Path, monkeypatch) -> None:
    """Global memory survives restart and is not where task notes go."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    _global_store().add(MemoryItem(content="User prefers Russian answers"))
    _task_store().add(MemoryItem(content="task note only"))

    fresh_global = MemoryStore()
    assert [item.content for item in fresh_global.list()] == ["User prefers Russian answers"]
    assert fresh_global._path() == axiom_home() / "memory.json"


# -------------------------------------------------------------- precedence


def test_task_note_shadows_the_same_item_in_project(tmp_path: Path, monkeypatch) -> None:
    """A shared item id is returned once, at the more specific scope's rank."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    project = _project_store(tmp_path)
    task = _task_store()
    project.add(MemoryItem(id="shared", content="broad statement about pytest"))
    task.add(MemoryItem(id="shared", content="broad statement about pytest"))
    tools = MemoryTools(_global_store(), project, task_store=task)

    hits = tools.relevant("pytest", budget=5)
    assert [item.id for item in hits] == ["shared"]
    assert hits[0].scope == "task"


def test_relevant_ranks_task_before_global_within_budget(tmp_path: Path, monkeypatch) -> None:
    """Equal relevance is broken by scope precedence, never by insertion order."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    global_store = _global_store()
    project = _project_store(tmp_path)
    task = _task_store()
    session = _session_store()
    global_store.add(MemoryItem(content="alpha note", updated_at=500.0))
    session.add(MemoryItem(content="alpha note", updated_at=400.0))
    project.add(MemoryItem(content="alpha note", updated_at=300.0))
    task.add(MemoryItem(content="alpha note", updated_at=100.0))
    tools = MemoryTools(global_store, project, task_store=task, session_store=session)

    hits = tools.relevant("alpha", budget=4)
    assert [item.scope for item in hits] == ["task", "session", "project", "global"]


def test_relevant_never_returns_the_full_store(tmp_path: Path, monkeypatch) -> None:
    """Four scopes are merged, but only the budgeted slice is returned."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    global_store = _global_store()
    project = _project_store(tmp_path)
    task = _task_store()
    session = _session_store()
    for index in range(10):
        global_store.add(MemoryItem(content=f"global fact {index}"))
        project.add(MemoryItem(content=f"project fact {index}"))
        task.add(MemoryItem(content=f"task fact {index}"))
        session.add(MemoryItem(content=f"session fact {index}"))
    tools = MemoryTools(global_store, project, task_store=task, session_store=session)

    assert len(tools.relevant("fact", budget=5)) == 5
    assert tools.relevant("fact", budget=0) == []


def test_stores_are_listed_once_in_precedence_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    global_store = _global_store()
    tools = MemoryTools(
        global_store, global_store, task_store=_task_store(), session_store=_session_store(),
    )
    assert [store.scope for store in tools.stores()] == ["task", "session", "global"]
    rows = tools.scope_rows()
    assert [row["scope"] for row in rows] == ["task", "session", "global"]
    assert all(Path(row["path"]).name.endswith(".json") for row in rows)


# ------------------------------------------------------------------- tools


async def test_memory_write_targets_task_and_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    global_store = _global_store()
    project = _project_store(tmp_path)
    task = _task_store()
    session = _session_store()
    tools = MemoryTools(global_store, project, task_store=task, session_store=session)
    registry = ToolRegistry()
    tools.register(registry)

    for scope, store in (("task", task), ("session", session)):
        written = await registry.execute(
            "memory_write", {"content": f"note for {scope}", "scope": scope}, approved=True,
        )
        assert written.ok, written.error
        assert f"in {scope} scope" in written.content
        assert store.count() == 1
    # Nothing leaked into the broader scopes.
    assert global_store.count() == 0
    assert project.count() == 0


async def test_unbound_scope_falls_back_to_global_and_reports_it(tmp_path: Path, monkeypatch) -> None:
    """No active task: a task-scoped write says plainly that it went global."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    global_store = _global_store()
    registry = ToolRegistry()
    MemoryTools(global_store).register(registry)

    written = await registry.execute(
        "memory_write", {"content": "no task is running", "scope": "task"}, approved=True,
    )
    assert written.ok
    assert "in global scope" in written.content
    assert global_store.count() == 1


async def test_read_and_forget_walk_all_four_scopes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    global_store = _global_store()
    project = _project_store(tmp_path)
    task = _task_store()
    session = _session_store()
    for store in (global_store, project, task, session):
        store.add(MemoryItem(content=f"{store.scope} marker"))
    tools = MemoryTools(global_store, project, task_store=task, session_store=session)
    registry = ToolRegistry()
    tools.register(registry)

    read = await registry.execute("memory_read", {"query": "marker"}, approved=True)
    assert read.ok
    for scope in ("task", "session", "project", "global"):
        assert f"{scope} marker" in read.content
    # The first listed item is the most specific scope.
    assert read.content.index("task marker") < read.content.index("global marker")

    forgotten = await registry.execute(
        "memory_forget", {"item_id": task.list()[0].id}, approved=True,
    )
    assert forgotten.ok
    assert task.count() == 0


# --------------------------------------------------------------- archiving


def test_archive_moves_the_file_and_empties_the_store(tmp_path: Path, monkeypatch) -> None:
    """Finished task memory is archived, not deleted and not left live."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    task = _task_store()
    task.add(MemoryItem(content="Task chose the SQLite path"))

    archived = task.archive(reason="completed")

    assert archived is not None
    archive_path = Path(archived)
    assert archive_path.parent == axiom_home() / "memory" / "archive"
    assert archive_path.name.startswith(f"task-{TASK_ID}-completed-")
    payload = json.loads(archive_path.read_text(encoding="utf-8"))
    assert payload["archived_scope"] == "task"
    assert payload["archive_reason"] == "completed"
    assert payload["archived_at"] > 0
    assert [item["content"] for item in payload["items"]] == ["Task chose the SQLite path"]
    # The live scope is gone: neither this instance nor a fresh one reads it.
    assert task.count() == 0
    assert not task._path().exists()
    assert _task_store().count() == 0


def test_archive_of_an_empty_store_is_reported_honestly(tmp_path: Path, monkeypatch) -> None:
    """A task that noted nothing produces no archive file and says so."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    assert _task_store().archive() is None
    assert not (axiom_home() / "memory" / "archive").exists()


def test_archived_memory_never_enters_a_later_read(tmp_path: Path, monkeypatch) -> None:
    """The whole point of archiving: the next task starts without these notes."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    project = _project_store(tmp_path)
    first_task = _task_store("first411")
    first_task.add(MemoryItem(content="first task private decision"))
    tools = MemoryTools(_global_store(), project, task_store=first_task)
    assert [item.content for item in tools.relevant("private", budget=5)] == [
        "first task private decision"]

    first_task.archive(reason="completed")
    tools.task_store = _task_store("second411")
    assert tools.relevant("private", budget=5) == []


# --------------------------------------------------- ChatSession integration


def _session(tmp_path: Path, monkeypatch, workspace: Path | None = None):
    """Isolated ChatSession; the model step and the verifier are faked per test."""
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.history import HistoryStore
    from axiom.core.models import ModelInfo

    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    session = ChatSession(
        config=Config(model="test-model:latest", save_history=False),
        history_store=HistoryStore(directory=tmp_path / "h"),
    )
    session.active_model = ModelInfo(name="test-model:latest", capabilities=["tools"])
    if workspace is not None:
        session.set_workspace(str(workspace))
    return session


def test_session_memory_follows_the_conversation(tmp_path: Path, monkeypatch) -> None:
    """One conversation's session notes never appear in another's."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    session = _session(tmp_path, monkeypatch)
    first_id = session.conversation.id
    assert session.memory_session_store is not None
    assert session.memory_session_store._path() == (
        tmp_path / "home" / "memory" / "sessions" / f"{first_id}.json")
    session.memory_session_store.add(MemoryItem(content="noted in the first chat"))

    restarted = _session(tmp_path, monkeypatch)
    assert restarted.conversation.id != first_id
    assert restarted.memory_session_store is not None
    assert restarted.memory_session_store.count() == 0

    conversation = session.new_conversation()
    assert conversation.id != first_id
    assert session.memory_session_store is not None
    assert session.memory_session_store._path().name == f"{conversation.id}.json"
    assert session.memory_session_store.count() == 0


async def _finish_task(tmp_path: Path, monkeypatch, *, verify_ok: bool):
    """Run one task to a terminal state with a faked step and verifier."""
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    session = _session(tmp_path, monkeypatch, workspace)
    # One verification attempt is enough to reach either terminal state here.
    session.config.max_retries = 0

    async def fake_step(*, step, prompt, on_event) -> dict:
        # The specialist writes through the real tool, into the task scope.
        result = await session.tools.execute(
            "memory_write", {"content": "task-only decision", "scope": "task"}, approved=True,
        )
        assert result.ok, result.error
        assert [item.content for item in session.memory_tools.relevant("task-only", budget=5)] == [
            "task-only decision"]
        return {"content": "step done", "report": {"RESULT": "step done"}}

    async def verify(task) -> dict:
        return {"ok": verify_ok, "executed": True,
                "summary": "1 passed" if verify_ok else "1 failed"}

    monkeypatch.setattr(session, "_execute_task_step", fake_step)
    monkeypatch.setattr(session, "_verify_task", verify)
    task = await session.task_start(
        "Do the thing",
        plan={"steps": [{"id": "s1", "goal": "g", "tools": ["memory_write"], "done_when": "d"}],
              "definition_of_done": ["d"]},
    )
    return session, task


async def test_completed_task_memory_is_archived(tmp_path: Path, monkeypatch) -> None:
    """Task memory is archived after completion and leaves every later read."""
    session, task = await _finish_task(tmp_path, monkeypatch, verify_ok=True)

    assert task.state.value == "completed"
    assert session.memory_task_store is None
    assert session.memory_tools.task_store is None
    assert not (axiom_home() / "memory" / "tasks" / f"{task.id}.json").exists()
    archives = list((axiom_home() / "memory" / "archive").glob(f"task-{task.id}-*.json"))
    assert len(archives) == 1
    assert "task-only decision" in archives[0].read_text(encoding="utf-8")
    # The note is unreachable now, and the archive is named in the trajectory.
    assert session.memory_tools.relevant("task-only", budget=5) == []
    assert any(event.kind == "memory.archived" for event in session.trajectory.events)


async def test_unfinished_task_keeps_its_live_memory(tmp_path: Path, monkeypatch) -> None:
    """Only completion archives: a task that stopped may still be resumed."""
    session, task = await _finish_task(tmp_path, monkeypatch, verify_ok=False)

    assert task.state.value == "waiting_for_user"
    assert session.memory_task_store is not None
    assert (axiom_home() / "memory" / "tasks" / f"{task.id}.json").exists()
    assert not (axiom_home() / "memory" / "archive").exists()
    assert [item.content for item in session.memory_tools.relevant("task-only", budget=5)] == [
        "task-only decision"]
