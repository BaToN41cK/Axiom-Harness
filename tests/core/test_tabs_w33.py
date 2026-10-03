"""W3.3 Multitasking: project/model/context-isolated chat tabs.

A chat tab is a descriptor (conversation + workspace + model); the ChatSession
stays the single runtime core and performs the real switches when a tab is
activated. These tests cover the registry semantics, the session-level
isolation (two tabs on two projects, each keeping its own conversation) and
the W3.3 background knowledge indexing slice.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from axiom.core.tabs import MAX_TABS, TabManager
from tests.core.test_orchestrator_runtime_a import _session


def test_tab_manager_open_activate_close(tmp_path):
    mgr = TabManager(path=tmp_path / "tabs.json")
    a = mgr.open(title="A")
    b = mgr.open(title="B")
    assert mgr.active_id == b.id
    assert [t.id for t in mgr.list()] == [a.id, b.id]

    mgr.activate(a.id)
    assert mgr.active_id == a.id

    # Closing the active tab moves activation to a neighbour, never to None
    # while others remain.
    nxt = mgr.close(a.id)
    assert nxt is not None and nxt.id == b.id
    assert mgr.active_id == b.id

    assert mgr.close(b.id) is None
    assert mgr.active_id is None
    assert mgr.list() == []


def test_tab_manager_persists_and_reloads(tmp_path):
    path = tmp_path / "tabs.json"
    mgr = TabManager(path=path)
    tab = mgr.open(title="Kept", workspace="C:/proj", model="m:1")
    mgr.update(tab.id, conversation_id="conv123")

    reloaded = TabManager(path=path)
    rows = reloaded.rows()
    assert len(rows) == 1
    assert rows[0]["title"] == "Kept"
    assert rows[0]["workspace"] == "C:/proj"
    assert rows[0]["conversation_id"] == "conv123"
    assert rows[0]["active"] is True


def test_tab_manager_rejects_corrupt_file(tmp_path):
    path = tmp_path / "tabs.json"
    path.write_text("{ not json", encoding="utf-8")
    mgr = TabManager(path=path)  # must not raise
    assert mgr.list() == []


def test_tab_manager_cap(tmp_path):
    mgr = TabManager(path=tmp_path / "tabs.json")
    for _ in range(MAX_TABS):
        mgr.open()
    import pytest

    with pytest.raises(ValueError, match="Too many open tabs"):
        mgr.open()


def test_session_default_tab_tracks_current_chat(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch)
    rows = session.tab_rows()
    assert len(rows) == 1
    assert rows[0]["active"] is True
    # No messages yet → no conversation binding fabricated.
    assert rows[0]["conversation_id"] is None


def test_session_tabs_isolate_two_projects(tmp_path, monkeypatch):
    proj_a = tmp_path / "a"
    proj_b = tmp_path / "b"
    proj_a.mkdir()
    proj_b.mkdir()
    session = _session(tmp_path, monkeypatch, proj_a)

    rows = session.tab_rows()
    first = rows[0]["id"]
    assert Path(rows[0]["workspace"]) == proj_a.resolve()

    # A second tab isolated to project B switches the live workspace.
    rows = session.tab_open(workspace_set=True, workspace=str(proj_b))
    second = next(r for r in rows if r["active"])["id"]
    assert second != first
    assert session.workspace_root == proj_b.resolve()

    # Switching back to the first tab restores project A.
    session.tab_activate(first)
    assert session.workspace_root == proj_a.resolve()


def test_session_tab_close_follows_project(tmp_path, monkeypatch):
    proj_a = tmp_path / "a"
    proj_b = tmp_path / "b"
    proj_a.mkdir()
    proj_b.mkdir()
    session = _session(tmp_path, monkeypatch, proj_a)
    session.tab_rows()
    first = session.tabs.active_id
    rows = session.tab_open(workspace_set=True, workspace=str(proj_b))
    second = next(r for r in rows if r["active"])["id"]
    assert session.workspace_root == proj_b.resolve()

    # Closing the active (B) tab activates A and switches the project back.
    session.tab_close(second)
    assert session.tabs.active_id == first
    assert session.workspace_root == proj_a.resolve()


async def test_knowledge_reindex_detached_runs_in_background(tmp_path, monkeypatch):
    """W3.3: background indexing returns pending and emits terminal events."""
    session = _session(tmp_path, monkeypatch)
    docs = tmp_path / "kb"
    docs.mkdir()
    (docs / "note.md").write_text("# Note\n\nBackground indexing note.\n", encoding="utf-8")

    events: list[dict] = []
    session.bus.subscribe("knowledge.event", events.append)

    result = await session.knowledge_add_collection("notes", str(docs), detached=True)
    assert result["ok"] is True
    assert result["pending"] is True
    assert "notes" in session.knowledge_indexing()

    # The background pass really completes (indexing a single file is fast).
    for _ in range(200):
        if "notes" not in session.knowledge_indexing():
            break
        await asyncio.sleep(0.01)
    assert "notes" not in session.knowledge_indexing()

    phases = [e["phase"] for e in events]
    assert "started" in phases
    assert "completed" in phases
    done = next(e for e in events if e["phase"] == "completed")
    assert done["stats"]["indexed"] == 1
    assert done["collection"]["files"] == 1

    # The collection is searchable after the background pass finished.
    hits = await session.knowledge_search_rows("Background indexing")
    assert hits and hits[0]["source"] == "note.md"


async def test_knowledge_reindex_detached_is_single_flight(tmp_path, monkeypatch):
    """W3.3: a second request while one runs reports pending, not two runs."""
    session = _session(tmp_path, monkeypatch)
    docs = tmp_path / "kb"
    docs.mkdir()
    (docs / "a.md").write_text("alpha\n", encoding="utf-8")
    await session.knowledge_add_collection("kb", str(docs))

    release = asyncio.Event()

    async def _slow_index(embedder=None):
        await release.wait()
        return type("Stats", (), {"to_dict": lambda self: {"indexed": 0}})()

    store = session.knowledge.get("kb")
    monkeypatch.setattr(store, "index", _slow_index)

    first = await session.knowledge_reindex("kb", detached=True)
    second = await session.knowledge_reindex("kb", detached=True)
    assert first["pending"] is True
    assert second["pending"] is True  # single flight: no second run started
    assert session.knowledge_cancel_index("kb") is True
    await asyncio.sleep(0.05)
    assert "kb" not in session.knowledge_indexing()

    # Cancelling when nothing runs stays honest.
    assert session.knowledge_cancel_index("kb") is False
