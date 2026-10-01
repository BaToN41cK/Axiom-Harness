"""W3.9 Chat 2.0: conversation export (Markdown + JSON) uses only real data."""
from __future__ import annotations

from axiom.core.chat_export import export_conversation_json, export_conversation_markdown
from axiom.core.events import Message
from axiom.core.history import Conversation


def _conversation() -> Conversation:
    return Conversation(
        id="abc123",
        title="Planning",
        model="test-model",
        created_at=1_700_000_000.0,
        updated_at=1_700_000_060.0,
        messages=[
            Message(role="user", content="Plan the feature", created_at=1_700_000_000.0),
            Message(role="assistant", content="Here is the plan", thinking="reason about steps",
                    created_at=1_700_000_010.0, artifacts=[{"type": "table"}]),
        ],
    )


def test_export_json_has_real_metadata_and_messages() -> None:
    data = export_conversation_json(_conversation())
    assert data["id"] == "abc123"
    assert data["model"] == "test-model"
    assert data["message_count"] == 2
    assert data["messages"][0]["content"] == "Plan the feature"
    assert data["messages"][1]["thinking"] == "reason about steps"
    assert data["messages"][1]["artifact_count"] == 1


def test_export_markdown_includes_title_model_and_content() -> None:
    md = export_conversation_markdown(_conversation())
    assert "# Planning" in md
    assert "test-model" in md
    assert "Plan the feature" in md
    assert "Here is the plan" in md
    assert "reason about steps" in md
    # The reasoning is inside a collapsible block, not leaked as plain text header.
    assert "<details><summary>Рассуждение</summary>" in md


async def test_bridge_chat_export_round_trip(tmp_path, monkeypatch) -> None:
    from tests.core.test_orchestrator_runtime_a import _session as make_session
    from tests.test_bridge import _bridge_module

    session = make_session(tmp_path, monkeypatch, tmp_path)
    conversation = _conversation()
    session.history_store.save(conversation)
    mod = _bridge_module()

    result = await mod._handle(session, "chat_export", {"id": "abc123"})
    assert result["json"]["id"] == "abc123"
    assert "# Planning" in result["markdown"]

    import pytest

    with pytest.raises(ValueError, match="not found"):
        await mod._handle(session, "chat_export", {"id": "missing"})
