"""W2.6: legacy JSON import into history.db and FTS-backed search.

These tests pin the migration contract (old files stay readable, a repeat
migration is a no-op) and confirm search still works whether FTS5 is present
or the store falls back to an in-Python scan.
"""

from __future__ import annotations

import json
from pathlib import Path

from axiom.core.events import Message as EventMessage
from axiom.core.history import Conversation, HistoryStore


def _legacy_file(directory: Path, conversation: Conversation) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{conversation.id}.json"
    path.write_text(conversation.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_legacy_json_is_imported_and_backed_up(tmp_path: Path) -> None:
    directory = tmp_path / "history"
    conv = Conversation(title="from json")
    conv.messages.append(EventMessage(role="user", content="hello from a file"))
    _legacy_file(directory, conv)

    store = HistoryStore(directory=directory)

    # The conversation is now served from history.db.
    listed = store.list()
    assert [c.id for c in listed] == [conv.id]
    loaded = store.load(conv.id)
    assert loaded is not None and loaded.messages[0].content == "hello from a file"

    # The original file was moved into the backup folder, not deleted.
    assert not (directory / f"{conv.id}.json").exists()
    backup = directory / "migrated_json" / f"{conv.id}.json"
    assert backup.is_file()
    restored = json.loads(backup.read_text(encoding="utf-8"))
    assert restored["id"] == conv.id
    assert (directory / "history.db").is_file()


def test_repeat_migration_is_a_noop(tmp_path: Path) -> None:
    directory = tmp_path / "history"
    conv = Conversation(title="only once")
    _legacy_file(directory, conv)

    first = HistoryStore(directory=directory)
    assert [c.id for c in first.list()] == [conv.id]
    first.close()

    # Re-opening finds no *.json to import; nothing changes and no duplicate.
    second = HistoryStore(directory=directory)
    assert [c.id for c in second.list()] == [conv.id]
    backups = list((directory / "migrated_json").glob("*.json"))
    assert len(backups) == 1


def test_corrupt_legacy_file_is_skipped_but_backed_up(tmp_path: Path) -> None:
    directory = tmp_path / "history"
    directory.mkdir(parents=True)
    (directory / "broken.json").write_text("{ not valid json", encoding="utf-8")
    good = Conversation(title="valid")
    _legacy_file(directory, good)

    store = HistoryStore(directory=directory)
    assert [c.id for c in store.list()] == [good.id]
    # Even the unreadable file is moved aside so it will not be retried forever.
    assert (directory / "migrated_json" / "broken.json").is_file()


def test_reopen_reads_persisted_conversations(tmp_path: Path) -> None:
    directory = tmp_path / "history"
    store = HistoryStore(directory=directory)
    conv = Conversation(title="persist me")
    conv.messages.append(EventMessage(role="user", content="remember this"))
    store.save(conv)
    store.close()

    fresh = HistoryStore(directory=directory)
    loaded = fresh.load(conv.id)
    assert loaded is not None and loaded.title == "persist me"
    hits = fresh.search("remember")
    assert hits and hits[0]["id"] == conv.id


def test_search_finds_imported_content(tmp_path: Path) -> None:
    directory = tmp_path / "history"
    conv = Conversation(title="unrelated")
    conv.messages.append(EventMessage(role="user", content="the launch code is 0451"))
    _legacy_file(directory, conv)

    store = HistoryStore(directory=directory)
    hits = store.search("launch code")
    assert len(hits) == 1
    assert "0451" in hits[0]["snippet"]
