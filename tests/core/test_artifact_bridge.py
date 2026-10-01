"""W3.17 Artifact Workspace: bridge commands for the Documents view."""
from __future__ import annotations

from tests.core.test_orchestrator_runtime_a import _session as make_session
from tests.test_bridge import _bridge_module


async def test_artifact_bridge_round_trip(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    session = make_session(tmp_path, monkeypatch, ws)
    mod = _bridge_module()

    created = await mod._handle(session, "artifact_save", {"title": "plan.md", "content": "# Plan"})
    assert created["title"] == "plan.md"
    assert created["version"] == 1
    artifact_id = created["id"]

    listed = await mod._handle(session, "artifact_list", {})
    assert [row["title"] for row in listed] == ["plan.md"]
    assert "content" not in listed[0]  # list rows are compact

    fetched = await mod._handle(session, "artifact_get", {"id": artifact_id})
    assert fetched["content"] == "# Plan"

    updated = await mod._handle(session, "artifact_save", {"id": artifact_id, "content": "# Plan v2"})
    assert updated["version"] == 2
    assert updated["content"] == "# Plan v2"
    assert updated["history"] and updated["history"][0]["content"] == "# Plan"

    destination = tmp_path / "out" / "plan.md"
    exported = await mod._handle(session, "artifact_export", {"id": artifact_id, "path": str(destination)})
    assert exported["ok"] is True
    assert destination.read_text(encoding="utf-8") == "# Plan v2"

    deleted = await mod._handle(session, "artifact_delete", {"id": artifact_id})
    assert deleted["deleted"] is True
    assert await mod._handle(session, "artifact_list", {}) == []


async def test_artifact_bridge_requires_workspace(tmp_path, monkeypatch) -> None:
    import pytest

    session = make_session(tmp_path, monkeypatch, None)
    # Global Chat disables workspace tools → workspace_root is None.
    session.clear_workspace()
    mod = _bridge_module()
    with pytest.raises(ValueError, match="No project"):
        await mod._handle(session, "artifact_list", {})


async def test_artifact_bridge_rejects_missing_id(tmp_path, monkeypatch) -> None:
    import pytest

    ws = tmp_path / "ws"
    ws.mkdir()
    session = make_session(tmp_path, monkeypatch, ws)
    mod = _bridge_module()
    with pytest.raises(ValueError, match="not found"):
        await mod._handle(session, "artifact_get", {"id": "missing"})
