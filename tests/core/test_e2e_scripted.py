"""W4.15: the deterministic scripted model drives a real coding task offline."""

from __future__ import annotations

import subprocess
import sys

from axiom.core.e2e_model import install_scripted_model, scripted_coding_chat
from axiom.core.providers.runtime import ProviderChatClient
from tests.core.test_orchestrator_runtime_a import _session
from tests.test_bridge import _bridge_module


def test_install_scripted_model_patches_provider(monkeypatch):
    # Register the original so the direct assignment in install_scripted_model
    # is reverted at teardown and cannot leak into other tests.
    monkeypatch.setattr(ProviderChatClient, "chat", ProviderChatClient.chat)
    install_scripted_model()
    assert ProviderChatClient.chat is scripted_coding_chat


async def test_scripted_model_drives_real_task_through_bridge(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "buggy.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (ws / "test_buggy.py").write_text(
        "from buggy import add\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", str(ws)], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    # The bug must genuinely fail before the agent touches anything.
    before = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ws,
                            capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
    assert before.returncode == 1

    monkeypatch.setattr(ProviderChatClient, "chat", scripted_coding_chat)
    session = _session(tmp_path, monkeypatch, ws)
    mod = _bridge_module()
    monkeypatch.setattr(mod, "_write_line", lambda line: None)

    result = await mod._handle(session, "task_start", {"goal": "Fix buggy.py"})
    assert result["state"] == "completed", result
    assert result["changed_files"] == ["buggy.py"]
    # Fail→repair: the first (wrong) fix genuinely fails the real pytest, then the
    # repair step fixes it and the verifier passes — two real verification runs.
    assert len(result["tests"]) == 2, result["tests"]
    assert result["tests"][0]["ok"] is False and result["tests"][0]["executed"] is True
    assert result["tests"][1]["ok"] is True and result["tests"][1]["executed"] is True
    assert "1 passed" in str(result["tests"][1])
    assert "return a + b" in (ws / "buggy.py").read_text(encoding="utf-8")
    assert "buggy.py" in result["diffs"]
    assert not session.busy


async def test_scripted_model_answers_plain_chat_without_tools(tmp_path, monkeypatch):
    """Non-task chat (the harness's Scenario 1/2 pings) must not break the loop."""
    monkeypatch.setattr(ProviderChatClient, "chat", scripted_coding_chat)
    session = _session(tmp_path, monkeypatch)
    chunks = [chunk async for chunk in ProviderChatClient.chat(
        session.provider_client, "m", [{"role": "user", "content": "ping"}])]
    assert "".join(chunk.content for chunk in chunks) == "pong"
    assert all(not chunk.tool_calls for chunk in chunks)
