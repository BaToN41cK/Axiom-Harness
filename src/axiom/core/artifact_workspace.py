"""Editable artifact workspace (W3.17).

Generated plans, reports, diagrams and documents become editable project assets
stored under ``<workspace>/.axiom/artifacts/``. Editing appends a new version
instead of overwriting, so history is never silently lost, and an empty
workspace contains no demo assets — ``list`` returns exactly what was saved.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from pydantic import BaseModel, Field


class ArtifactVersion(BaseModel):
    version: int
    content: str
    updated_at: float


class ArtifactDocument(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    title: str
    kind: str = "markdown"
    content: str = ""
    task_id: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    version: int = 1
    history: list[ArtifactVersion] = Field(default_factory=list)

    def edit(self, content: str) -> None:
        """Append the current content to history, then advance to a new version."""
        self.history.append(
            ArtifactVersion(version=self.version, content=self.content, updated_at=self.updated_at)
        )
        self.version += 1
        self.content = content
        self.updated_at = time.time()


class ArtifactWorkspace:
    """Stores editable artifacts under ``<root>/.axiom/artifacts``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root) / ".axiom" / "artifacts"

    def _path(self, artifact_id: str) -> Path:
        return self.root / f"{artifact_id}.json"

    def save(self, document: ArtifactDocument) -> ArtifactDocument:
        self.root.mkdir(parents=True, exist_ok=True)
        document.updated_at = time.time()
        self._path(document.id).write_text(document.model_dump_json(indent=2), encoding="utf-8")
        return document

    def load(self, artifact_id: str) -> ArtifactDocument | None:
        path = self._path(artifact_id)
        if not path.exists():
            return None
        return ArtifactDocument.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[ArtifactDocument]:
        if not self.root.exists():
            return []
        documents: list[ArtifactDocument] = []
        for path in self.root.glob("*.json"):
            try:
                documents.append(ArtifactDocument.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(documents, key=lambda document: document.updated_at, reverse=True)

    def delete(self, artifact_id: str) -> bool:
        path = self._path(artifact_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def create(
        self, title: str, content: str, *, task_id: str | None = None, kind: str = "markdown"
    ) -> ArtifactDocument:
        return self.save(ArtifactDocument(title=title, content=content, task_id=task_id, kind=kind))

    def update(self, artifact_id: str, content: str) -> ArtifactDocument | None:
        document = self.load(artifact_id)
        if document is None:
            return None
        document.edit(content)
        return self.save(document)

    def export(self, artifact_id: str, destination: Path) -> bool:
        document = self.load(artifact_id)
        if document is None:
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(document.content, encoding="utf-8")
        return True


__all__ = ["ArtifactDocument", "ArtifactVersion", "ArtifactWorkspace"]
