"""HistoryStore: size limit (pruning) and the script triad list/show/rm."""

from __future__ import annotations

import types
from pathlib import Path

import pytest

import axiom.core.history as history_module
from axiom.core.history import Conversation, HistoryStore


@pytest.fixture()
def steady_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic time so updated_at ordering never depends on wall-clock ties."""
    state = {"t": 1000.0}

    def fake_time() -> float:
        state["t"] += 10.0
        return state["t"]

    monkeypatch.setattr(history_module, "time", types.SimpleNamespace(time=fake_time))


def _conv(title: str) -> Conversation:
    return Conversation(title=title)


def test_prune_keeps_only_newest(tmp_path: Path, steady_clock: None) -> None:
    store = HistoryStore(directory=tmp_path / "h", limit=3)
    for index in range(5):
        store.save(_conv(f"c{index}"))
    listed = store.list()
    assert [c.title for c in listed] == ["c4", "c3", "c2"]
    # The store keeps exactly ``limit`` conversations in history.db.
    assert len(listed) == 3
    assert (tmp_path / "h" / "history.db").is_file()


def test_no_limit_keeps_everything(tmp_path: Path, steady_clock: None) -> None:
    store = HistoryStore(directory=tmp_path / "h")
    for index in range(5):
        store.save(_conv(f"c{index}"))
    assert len(store.list()) == 5


def test_set_limit_at_runtime(tmp_path: Path, steady_clock: None) -> None:
    store = HistoryStore(directory=tmp_path / "h")
    for index in range(4):
        store.save(_conv(f"c{index}"))
    store.set_limit(2)
    store.save(_conv("new"))
    titles = [c.title for c in store.list()]
    assert titles == ["new", "c3"]


def test_show_returns_raw_json(tmp_path: Path, steady_clock: None) -> None:
    store = HistoryStore(directory=tmp_path / "h")
    conv = _conv("shown")
    store.save(conv)
    raw = store.show(conv.id)
    assert raw is not None
    assert '"title": "shown"' in raw
    assert store.show("missing") is None
