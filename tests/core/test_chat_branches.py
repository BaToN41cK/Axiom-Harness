"""W3.9 branch promotion: switch/continue/persist branches without loss."""

from __future__ import annotations

import time
from pathlib import Path

from axiom.core.chat import ChatSession
from axiom.core.config import Config
from axiom.core.events import Message
from axiom.core.history import HistoryStore
from axiom.core.models import ModelInfo
from axiom.core.ollama import StreamChunk
from tests.core.test_chat import FakeClient


def make_session(tmp_path: Path, chunks=None) -> ChatSession:
    cfg = Config(model="test-model:latest")
    store = HistoryStore(directory=tmp_path / "history")
    session = ChatSession(config=cfg, client=FakeClient(chunks or []), history_store=store)
    session.active_model = ModelInfo(name="test-model:latest", capabilities=[])
    return session


def seed_turn(session: ChatSession, user: str, assistant: str) -> int:
    session.conversation.messages.append(
        Message(role="user", content=user, created_at=time.time())
    )
    session.conversation.messages.append(
        Message(role="assistant", content=assistant, created_at=time.time())
    )
    session._save_conversation()
    return len(session.conversation.messages) - 1


async def test_regenerate_preserves_previous_answer_as_branch(tmp_path: Path):
    session = make_session(tmp_path, [StreamChunk(content="answer v2"), StreamChunk(done=True)])
    seed_turn(session, "hello", "answer v1")

    [e async for e in session.regenerate()]
    last = session.conversation.messages[-1]
    assert last.role == "assistant"
    assert last.content == "answer v2"
    assert last.alternates == ["answer v1"]


async def test_promote_branch_swaps_without_loss(tmp_path: Path):
    session = make_session(tmp_path, [StreamChunk(content="answer v2"), StreamChunk(done=True)])
    assistant_idx = seed_turn(session, "hello", "answer v1")
    [e async for e in session.regenerate()]

    assert session.promote_branch(assistant_idx, 0) is True
    active = session.conversation.messages[assistant_idx]
    assert active.content == "answer v1"
    assert active.alternates == ["answer v2"]
    # Promoting back restores v2 — nothing is lost in either direction.
    assert session.promote_branch(assistant_idx, 0) is True
    active = session.conversation.messages[assistant_idx]
    assert active.content == "answer v2"
    assert active.alternates == ["answer v1"]


async def test_continuation_uses_promoted_branch_context(tmp_path: Path):
    session = make_session(tmp_path, [StreamChunk(content="answer v2"), StreamChunk(done=True)])
    seed_turn(session, "hello", "answer v1")
    [e async for e in session.regenerate()]
    assert session.promote_branch(1, 0) is True
    assert session.conversation.messages[1].content == "answer v1"

    session.client._chunks = [StreamChunk(content="follow-up answer"), StreamChunk(done=True)]
    [e async for e in session.send("next question")]
    sent = session.client.chat_calls[-1]["messages"]
    contents = [m["content"] for m in sent]
    assert any("answer v1" in c for c in contents)
    assert not any("answer v2" in c for c in contents)


async def test_branches_persist_after_reload(tmp_path: Path):
    session = make_session(tmp_path, [StreamChunk(content="answer v2"), StreamChunk(done=True)])
    seed_turn(session, "hello", "answer v1")
    [e async for e in session.regenerate()]
    assert session.promote_branch(1, 0) is True
    cid = session.conversation.id

    fresh = HistoryStore(directory=tmp_path / "history")
    loaded = fresh.load(cid)
    assert loaded is not None
    assert loaded.messages[1].content == "answer v1"
    assert loaded.messages[1].alternates == ["answer v2"]


async def test_promote_touches_only_target_chat(tmp_path: Path):
    session = make_session(tmp_path, [StreamChunk(content="b"), StreamChunk(done=True)])
    seed_turn(session, "q-a", "a-v1")
    cid_a = session.conversation.id
    session._save_conversation()

    conv_b = session.new_conversation()
    cid_b = conv_b.id
    session.conversation.messages.append(Message(role="user", content="q-b"))
    session.conversation.messages.append(Message(role="assistant", content="b-v1"))
    session._save_conversation()

    loaded_a = session.history_store.load(cid_a)
    assert loaded_a is not None
    loaded_a.messages[1].alternates = ["a-v0"]
    loaded_a.messages[1].content = "a-v1"
    session.history_store.save(loaded_a)

    assert session.promote_branch(1, 0, conversation_id=cid_a) is True
    after_a = session.history_store.load(cid_a)
    assert after_a is not None
    assert after_a.messages[1].content == "a-v0"
    assert after_a.messages[1].alternates == ["a-v1"]

    after_b = session.history_store.load(cid_b)
    assert after_b is not None
    assert after_b.messages[1].content == "b-v1"
    assert after_b.messages[1].alternates == []

    # Current in-memory chat (B) is untouched by a promotion in A.
    assert session.conversation.id == cid_b
    assert session.conversation.messages[1].content == "b-v1"


def test_branch_validation_rejects_bad_input(tmp_path: Path):
    session = make_session(tmp_path)
    seed_turn(session, "hello", "answer v1")
    # User message cannot have branches.
    assert session.list_branches(0) is None
    assert session.promote_branch(0, 0) is False
    # No alternates yet.
    assert session.list_branches(1) == {"message_index": 1, "content": "answer v1", "alternates": []}
    assert session.promote_branch(1, 0) is False
    assert session.promote_branch(1, 5) is False
    assert session.promote_branch(99, 0) is False
    assert session.promote_branch(1, 0, conversation_id="missing") is False
    assert session.list_branches(1, conversation_id="missing") is None
