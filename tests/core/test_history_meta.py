"""Tests for sidebar chat metadata and full-text history search."""

from __future__ import annotations

import time
from pathlib import Path

from axiom.core.events import Message as EventMessage
from axiom.core.history import Conversation, HistoryStore


def make_store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(directory=tmp_path / "history")


def seed(store: HistoryStore, title: str, texts: list[str], **meta) -> str:
    conv = Conversation(title=title)
    for i, text in enumerate(texts):
        conv.messages.append(
            EventMessage(
                role="user" if i % 2 == 0 else "assistant",
                content=text,
                created_at=time.time(),
            )
        )
    if "pinned" in meta:
        conv.pinned = meta["pinned"]
    if "folder" in meta:
        conv.folder = meta["folder"]
    store.save(conv)
    return conv.id


def test_set_meta_pin_and_folder(tmp_path: Path):
    store = make_store(tmp_path)
    cid = seed(store, "chat", ["hello world"])
    assert store.set_meta(cid, pinned=True, folder=" Work ")
    loaded = store.load(cid)
    assert loaded is not None
    assert loaded.pinned is True
    assert loaded.folder == "Work"
    assert store.set_meta(cid, pinned=False, folder=None)
    loaded = store.load(cid)
    assert loaded is not None
    assert loaded.pinned is False
    assert loaded.folder is None


def test_meta_survives_reload(tmp_path: Path):
    store = make_store(tmp_path)
    cid = seed(store, "chat", ["x"], pinned=True, folder="Docs")
    fresh = HistoryStore(directory=tmp_path / "history")
    conv = fresh.load(cid)
    assert conv is not None
    assert conv.pinned and conv.folder == "Docs"


def test_search_matches_message_content(tmp_path: Path):
    store = make_store(tmp_path)
    seed(store, "unrelated title", ["nothing here", "the launch code is 0451"])
    seed(store, "another chat", ["boring text"])
    hits = store.search("launch code")
    assert len(hits) == 1
    assert hits[0]["title"] == "unrelated title"
    assert "0451" in hits[0]["snippet"]


def test_search_matches_title_only(tmp_path: Path):
    store = make_store(tmp_path)
    seed(store, "Python refactoring plan", ["body"])
    hits = store.search("refactoring")
    assert hits and hits[0]["title"] == "Python refactoring plan"


def test_search_empty_query_returns_nothing(tmp_path: Path):
    store = make_store(tmp_path)
    seed(store, "t", ["body"])
    assert store.search("   ") == []


def test_search_is_case_insensitive(tmp_path: Path):
    store = make_store(tmp_path)
    seed(store, "t", ["The ANSWER is forty-two"])
    assert store.search("forty-TWO")


def test_bookmarks_persist_and_toggle(tmp_path: Path):
    store = make_store(tmp_path)
    cid = seed(store, "chat", ["one", "two", "three"])

    assert store.set_bookmark(cid, 1, True) is True
    loaded = store.load(cid)
    assert loaded is not None
    assert loaded.bookmarks == [1]

    # Toggling the same index off removes it.
    assert store.set_bookmark(cid, 1, False) is True
    assert store.load(cid).bookmarks == []

    # Out-of-range index is rejected.
    assert store.set_bookmark(cid, 99, True) is False
    # Unknown chat is rejected.
    assert store.set_bookmark("missing", 0, True) is False


def test_bookmarks_survive_reload(tmp_path: Path):
    store = make_store(tmp_path)
    cid = seed(store, "chat", ["a", "b", "c"])
    store.set_bookmark(cid, 0, True)
    store.set_bookmark(cid, 2, True)
    fresh = HistoryStore(directory=tmp_path / "history")
    conv = fresh.load(cid)
    assert conv is not None
    assert conv.bookmarks == [0, 2]
