"""W3.17: editable artifact workspace with version history."""

from __future__ import annotations

from axiom.core.artifact_workspace import ArtifactWorkspace


def test_empty_workspace_has_no_demo_assets(tmp_path) -> None:
    workspace = ArtifactWorkspace(tmp_path)
    assert workspace.list() == []


def test_create_load_and_task_association(tmp_path) -> None:
    workspace = ArtifactWorkspace(tmp_path)
    document = workspace.create("plan.md", "# Plan", task_id="task-1")

    loaded = workspace.load(document.id)
    assert loaded is not None
    assert loaded.title == "plan.md"
    assert loaded.content == "# Plan"
    assert loaded.task_id == "task-1"


def test_update_appends_version_history(tmp_path) -> None:
    workspace = ArtifactWorkspace(tmp_path)
    document = workspace.create("doc.md", "v1")

    updated = workspace.update(document.id, "v2")
    assert updated is not None
    assert updated.version == 2
    assert updated.content == "v2"
    assert len(updated.history) == 1
    assert updated.history[0].content == "v1"

    reloaded = workspace.load(document.id)
    assert reloaded is not None
    assert reloaded.version == 2


def test_export(tmp_path) -> None:
    workspace = ArtifactWorkspace(tmp_path)
    document = workspace.create("report.md", "# Report")

    destination = tmp_path / "out" / "report.md"
    assert workspace.export(document.id, destination) is True
    assert destination.read_text(encoding="utf-8") == "# Report"
    assert workspace.export("missing", destination) is False


def test_delete(tmp_path) -> None:
    workspace = ArtifactWorkspace(tmp_path)
    document = workspace.create("doc.md", "x")
    assert workspace.delete(document.id) is True
    assert workspace.load(document.id) is None
    assert workspace.delete(document.id) is False
