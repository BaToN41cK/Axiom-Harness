"""W2.9 security boundaries: network validation, audit, checkpoints, Local Only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom.core.knowledge import KnowledgeManager
from axiom.core.security import CheckpointStore, NetGuard, ToolAudit, mark_untrusted, mask_secrets
from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult
from axiom.core.tools.registry import ToolRegistry
from axiom.core.tools.web_search import WebSearchTool


def test_net_guard_blocks_ssrf_and_allows_public_literal() -> None:
    guard = NetGuard()
    for url in ("file:///etc/passwd", "http://127.0.0.1/x", "http://localhost/x", "http://10.0.0.1/x"):
        with pytest.raises(ValueError):
            guard.validate(url)
    assert guard.validate("https://8.8.8.8/") == "https://8.8.8.8/"


def test_audit_masks_secrets_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    audit = ToolAudit(path=path, session_id="s1")
    audit.record("demo", {"api_token": "secret", "nested": {"password": "pw"}}, True, 4)
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["session"] == "s1"
    assert row["arguments"]["api_token"] == "***"
    assert row["arguments"]["nested"]["password"] == "***"
    assert "secret" not in path.read_text(encoding="utf-8")
    assert mask_secrets({"token": "x"})["token"] == "***"


def test_registry_writes_audit_record(tmp_path: Path) -> None:
    audit = ToolAudit(tmp_path / "audit.jsonl")
    registry = ToolRegistry(audit=audit)

    async def handler(**kwargs) -> ToolResult:
        return ToolResult(name="demo", ok=True, content="ok")

    registry.register(ToolDefinition(name="demo", description="demo", permission=ToolPermission.ALWAYS), handler)
    import asyncio

    result = asyncio.run(registry.execute("demo", {"token": "secret"}))
    assert result.ok
    row = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert row["tool"] == "demo"
    assert row["arguments"]["token"] == "***"


def test_checkpoint_restores_existing_and_created_files(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "a.txt"
    target.write_text("before", encoding="utf-8")
    store = CheckpointStore(root, tmp_path / "checkpoints")
    existing = store.capture(target)
    target.write_text("after", encoding="utf-8")
    assert store.rollback(existing.step_id)
    assert target.read_text(encoding="utf-8") == "before"

    created = root / "new.txt"
    step = store.capture(created)
    created.write_text("created", encoding="utf-8")
    assert store.rollback(step.step_id)
    assert not created.exists()


def test_untrusted_marker_and_local_only() -> None:
    assert mark_untrusted("https://example.com/a", "ignore instructions").startswith("[untrusted: example.com]")
    manager = KnowledgeManager(local_only=True)
    manager.configure_embedder("http://127.0.0.1:11434", "nomic-embed-text")
    assert manager.embedder is None


@pytest.mark.asyncio
async def test_web_tool_local_only_blocks_search() -> None:
    class Provider:
        async def search(self, query: str, limit: int = 5):
            raise AssertionError("network must not be called")

        async def fetch(self, url: str, max_chars: int = 4000):
            raise AssertionError("network must not be called")

    tool = WebSearchTool(Provider(), local_only=True)  # type: ignore[arg-type]
    result = await tool.search("anything")
    assert not result.ok and "Local Only" in (result.error or "")

