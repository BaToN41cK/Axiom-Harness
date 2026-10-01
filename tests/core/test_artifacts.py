"""W3.4 Answer Artifacts: validated structured output and export.

An artifact is accepted only when its type-specific data is present and
well-formed; malformed payloads fail explicitly instead of rendering a
decorative placeholder. Tables, comparisons, checklists and charts export to
Markdown/CSV/SVG; Mermaid renders as a fenced block and refuses tabular export.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from axiom.core.artifacts import ArtifactTools, build_artifact, to_csv, to_markdown, to_svg
from axiom.core.tools.registry import ToolRegistry


def test_table_artifact_renders_and_exports() -> None:
    artifact = build_artifact(
        "table",
        {"columns": ["name", "size"], "rows": [["a", "1"], ["b", "2"]]},
        title="files",
    )

    markdown = to_markdown(artifact)
    assert "| name | size |" in markdown
    assert "| --- | --- |" in markdown
    assert "| a | 1 |" in markdown

    csv_out = to_csv(artifact)
    assert "name,size" in csv_out
    assert "a,1" in csv_out

    svg_out = to_svg(artifact)
    assert svg_out.startswith("<svg")
    assert "files" in svg_out


def test_mermaid_renders_and_refuses_tabular_export() -> None:
    artifact = build_artifact("mermaid", {"diagram": "graph TD; A-->B;"})

    assert to_markdown(artifact).startswith("```mermaid\n")
    assert "graph TD; A-->B;" in to_markdown(artifact)

    with pytest.raises(ValueError, match="CSV"):
        to_csv(artifact)
    with pytest.raises(ValueError, match="renderer"):
        to_svg(artifact)


def test_comparison_and_checklist_export() -> None:
    comparison = build_artifact(
        "comparison",
        {"items": [{"label": "speed", "left": "fast", "right": "slow"}]},
    )
    assert "| Aspect | Left | Right |" in to_markdown(comparison)
    assert "aspect,left,right\nspeed,fast,slow" in to_csv(comparison)

    checklist = build_artifact(
        "checklist",
        {"items": [{"label": "done", "checked": True}, {"label": "todo"}]},
    )
    assert "- [x] done" in to_markdown(checklist)
    assert "- [ ] todo" in to_markdown(checklist)
    assert "label,checked\ndone,yes\ntodo,no" in to_csv(checklist)


def test_chart_renders_and_validates_alignment() -> None:
    artifact = build_artifact(
        "chart",
        {"labels": ["x", "y"], "series": [{"label": "s", "values": [1.0, 2.0]}]},
    )
    assert "| Label | s |" in to_markdown(artifact)
    assert to_svg(artifact).startswith("<svg")

    # A series whose values do not match the label count is malformed.
    with pytest.raises(ValidationError):
        build_artifact(
            "chart",
            {"labels": ["x"], "series": [{"label": "s", "values": [1.0, 2.0]}]},
        )


def test_missing_data_fails_explicitly() -> None:
    with pytest.raises(ValidationError):
        build_artifact("table", {"columns": ["a"], "rows": []})
    with pytest.raises(ValidationError):
        build_artifact("table", {"columns": ["a", "b"], "rows": [["1"]]})
    with pytest.raises(ValidationError):
        build_artifact("checklist", {"items": []})
    with pytest.raises(ValidationError):
        build_artifact("mermaid", {"diagram": ""})
    with pytest.raises(ValidationError):
        build_artifact("chart", {"series": []})
    with pytest.raises(ValidationError):
        build_artifact("table", {"columns": []})


async def test_render_artifact_tool_executes_and_fails_explicitly() -> None:
    registry = ToolRegistry()
    ArtifactTools().register(registry)

    ok = await registry.execute(
        "render_artifact",
        {"type": "table", "payload": {"columns": ["a", "b"], "rows": [["1", "2"]]}},
    )
    assert ok.ok is True
    assert "| a | b |" in ok.content
    assert ok.data["artifact"]["type"] == "table"

    bad = await registry.execute(
        "render_artifact",
        {"type": "table", "payload": {"columns": ["a"], "rows": []}},
    )
    assert bad.ok is False
    assert "Invalid artifact" in (bad.error or "")
    assert bad.data["validation_errors"]


def test_tool_result_event_carries_structured_data() -> None:
    from axiom.core.events import ToolResultEvent

    event = ToolResultEvent(
        name="render_artifact",
        ok=True,
        content="| a | b |",
        data={"artifact": {"type": "table", "columns": ["a", "b"], "rows": [["1", "2"]]}},
    )
    dumped = event.model_dump(mode="json")
    assert dumped["data"]["artifact"]["type"] == "table"


def test_record_turn_persists_artifacts(tmp_path, monkeypatch) -> None:
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.history import HistoryStore

    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    session = ChatSession(config=Config(model="m"), history_store=HistoryStore(directory=tmp_path / "h"))
    session._record_turn(
        "draw it",
        "Here is the table.",
        "",
        artifacts=[{"type": "table", "columns": ["a"], "rows": [["1"]]}],
    )
    assistant = session.conversation.messages[-1]
    assert assistant.role == "assistant"
    assert assistant.artifacts == [{"type": "table", "columns": ["a"], "rows": [["1"]]}]


async def test_render_artifact_flows_into_assistant_message(tmp_path, monkeypatch) -> None:
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.history import HistoryStore
    from axiom.core.models import ModelInfo
    from axiom.core.ollama import StreamChunk, ToolCallRequest
    from axiom.core.providers.runtime import ProviderChatClient

    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    cfg = Config(model="test-model:latest")
    cfg.save_history = False
    session = ChatSession(config=cfg, history_store=HistoryStore(directory=tmp_path / "h"))
    session.active_model = ModelInfo(name="test-model:latest", capabilities=["tools"])

    async def transport(self, model, messages, **kwargs):
        if "Tool result (render_artifact)" in str(messages):
            yield StreamChunk(content="Here is the table.", done=True)
        else:
            yield StreamChunk(tool_calls=[ToolCallRequest(name="render_artifact", arguments={
                "type": "table",
                "payload": {"columns": ["a", "b"], "rows": [["1", "2"]]},
            })], done=True)

    monkeypatch.setattr(ProviderChatClient, "chat", transport)
    events = [event async for event in session.send("render a table")]
    assert any(getattr(event, "type", "") == "done" for event in events)
    assistant = session.conversation.messages[-1]
    assert assistant.role == "assistant"
    assert len(assistant.artifacts) == 1
    assert assistant.artifacts[0]["type"] == "table"
    assert assistant.artifacts[0]["columns"] == ["a", "b"]
