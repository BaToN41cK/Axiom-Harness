"""W2.2 Knowledge Base — deterministic tests (no network, tmp AXIOM_HOME)."""
from __future__ import annotations

from pathlib import Path

import pytest

from axiom.core.knowledge import KnowledgeManager, KnowledgeStore, KnowledgeTools
from axiom.core.knowledge.chunking import chunk_text, is_indexable
from axiom.core.knowledge.store import Embedder
from axiom.core.tools.registry import ToolRegistry


def _docs(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# Guide\n\nInstall AXIOM with pip install axiom.\n\n"
        "Run pytest to verify the installation.\n",
        encoding="utf-8",
    )
    (docs / "notes.txt").write_text(
        "The deploy server lives behind the VPN gateway.\n"
        "Backups run every night at 03:00 local time.\n",
        encoding="utf-8",
    )
    (docs / ".env").write_text("SECRET=hunter2", encoding="utf-8")
    (docs / "image.png").write_bytes(b"\x89PNG fake")
    return docs


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, docs: Path) -> KnowledgeStore:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    return KnowledgeStore("docs", docs)


def test_chunk_text_tracks_real_line_numbers() -> None:
    text = "\n".join(f"line {i} " + "x" * 60 for i in range(1, 60))
    chunks = chunk_text(text, max_chars=500, overlap=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.start_line <= chunk.end_line
        assert chunk.text.strip()
    assert chunks[0].start_line == 1


def test_is_indexable_rejects_secrets_and_binary() -> None:
    assert is_indexable("guide.md", ".md")
    assert not is_indexable(".env", "")
    assert not is_indexable("id_rsa", "")
    assert not is_indexable("cert.pem", ".pem")
    assert not is_indexable("image.png", ".png")


def test_index_and_search_cites_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docs = _docs(tmp_path)
    store = _store(tmp_path, monkeypatch, docs)
    stats = store.index()
    assert stats.indexed == 2  # guide.md + notes.txt; .env and .png skipped
    assert stats.skipped == 2
    status = store.status()
    assert status["files"] == 2
    assert status["chunks"] >= 2
    assert status["embeddings"] == "disabled"
    hits = store.search("VPN gateway")
    assert hits, "BM25 must work offline"
    assert hits[0].source == "notes.txt"
    assert "VPN gateway" in hits[0].text
    assert hits[0].start_line >= 1
    store.close()


def test_incremental_index_only_reindexes_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docs = _docs(tmp_path)
    store = _store(tmp_path, monkeypatch, docs)
    store.index()
    again = store.index()
    assert again.indexed == 0
    assert again.unchanged == 2
    import os
    import time

    time.sleep(0.01)
    target = docs / "notes.txt"
    target.write_text(target.read_text(encoding="utf-8") + "\nNew fact about the staging VPN.\n",
                      encoding="utf-8")
    os.utime(target, None)
    third = store.index()
    assert third.indexed == 1
    assert third.unchanged == 1
    assert store.search("staging VPN")[0].source == "notes.txt"
    (docs / "guide.md").unlink()
    fourth = store.index()
    assert fourth.removed == 1
    assert store.search("pip install") == []
    store.close()


class _FakeEmbedder(Embedder):
    def __init__(self, ok: bool) -> None:
        super().__init__("http://127.0.0.1:9", "fake")
        self._ok = ok

    def embed(self, texts):  # type: ignore[override]
        if not self._ok:
            return None, "connection refused"
        return [[float(len(t)), 1.0] for t in texts], None


def test_embeddings_unavailable_is_honest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docs = _docs(tmp_path)
    store = _store(tmp_path, monkeypatch, docs)
    stats = store.index(embedder=_FakeEmbedder(ok=False))
    assert stats.indexed == 2
    status = store.status()
    assert status["embeddings"].startswith("unavailable:")
    assert status["embedded"] == 0
    assert store.search("backups")[0].source == "notes.txt"
    store.close()

def test_embeddings_rerank_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docs = _docs(tmp_path)
    store = _store(tmp_path, monkeypatch, docs)
    store.index(embedder=_FakeEmbedder(ok=True))
    status = store.status()
    assert status["embeddings"] == "ok"
    assert status["embedded"] == status["chunks"]
    store._query_embedder = _FakeEmbedder(ok=True)
    hits = store.search("VPN")
    assert hits and hits[0].source == "notes.txt"
    store.close()


def test_manager_registry_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    docs = _docs(tmp_path)
    manager = KnowledgeManager()
    assert manager.add("docs", str(docs)) is None
    assert manager.add("missing", str(tmp_path / "nope")) is not None
    assert manager.names() == ["docs"]
    again = KnowledgeManager()
    assert again.names() == ["docs"]
    assert again.remove("docs")
    assert not again.remove("docs")
    assert KnowledgeManager().names() == []


async def test_knowledge_tools_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    docs = _docs(tmp_path)
    manager = KnowledgeManager()
    tools = KnowledgeTools(manager)
    registry = ToolRegistry()
    tools.register(registry)
    assert registry.get("knowledge_search") is not None
    result = await registry.execute("knowledge_index", {"name": "docs", "path": str(docs)})
    assert result.ok and "2 new/changed" in result.content
    result = await registry.execute("knowledge_search", {"query": "VPN"})
    assert result.ok and "[1] docs/notes.txt" in result.content
    assert "VPN gateway" in result.content
    result = await registry.execute("knowledge_search", {"query": "absent-xyz"})
    assert result.ok and "no knowledge fragments" in result.content
    result = await registry.execute("knowledge_status")
    assert result.ok and "docs" in result.content
    result = await registry.execute("knowledge_index", {"name": "bad", "path": str(tmp_path / "x")})
    assert not result.ok


async def test_session_registers_knowledge_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.history import HistoryStore

    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    session = ChatSession(
        config=Config(ollama_url="http://127.0.0.1:9", model="test-model:latest"),
        history_store=HistoryStore(directory=tmp_path / "history"),
    )
    assert session.tools.get("knowledge_search") is not None
    assert session.tools.get("knowledge_index") is not None
    assert session.tools.get("knowledge_status") is not None
    docs = _docs(tmp_path)
    added = await session.knowledge_add_collection("docs", str(docs))
    assert added["ok"] and added["stats"]["indexed"] == 2
    rows = session.knowledge_rows()
    assert rows[0]["name"] == "docs" and rows[0]["files"] == 2
    hits = await session.knowledge_search_rows("VPN gateway")
    assert hits and hits[0]["source"] == "notes.txt"
    assert hits[0]["start_line"] >= 1
    assert session.knowledge_remove_collection("docs")
    assert session.knowledge_rows() == []


def test_tool_scope_advertises_knowledge() -> None:
    from axiom.core.performance import tool_scope

    scope = tool_scope("search my notes about VPN")
    assert scope is not None
    assert "knowledge_search" in scope
    plain = tool_scope("сколько будет два плюс два")
    assert plain is None or "knowledge_search" not in plain

