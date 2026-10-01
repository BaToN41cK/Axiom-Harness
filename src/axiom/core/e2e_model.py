"""Deterministic scripted coding model for offline end-to-end runs (W4.15).

The browser/Tauri E2E harness must prove the integrated task workflow without a
live model or network. This module is that seam: one async generator with the
exact ``ProviderChatClient.chat`` surface that plays a real, fixed coding
scenario — plan, read, a first (failing) edit, a real pytest fail→repair, accept.
It is installed only when
``AXIOM_E2E_SCRIPTED_MODEL=1`` is set (see the desktop bridge and the e2e
harness); nothing here runs during normal use.

It drives the *real* pipeline — the real TaskRunner, filesystem tools, git and
pytest — so the harness observes a real file change, a real diff and a real
test result, never fabricated UI.
"""

from __future__ import annotations

import json

from axiom.core.ollama import StreamChunk, ToolCallRequest

#: The scenario fixes ``buggy.py`` (which returns ``a - b``) to return ``a + b``.
PLAN_JSON = json.dumps({
    "steps": [{
        "id": "fix",
        "goal": "Fix buggy.py",
        "tools": ["read_file", "edit_file"],
        "done_when": "add returns the sum",
    }],
    "definition_of_done": ["add returns the sum and tests pass"],
})

#: The fixture ships a buggy ``buggy.py`` (subtracts instead of adds). The
#: scenario makes one wrong fix first (multiply) so verification genuinely fails
#: once, then repairs to the correct sum — a real fail→repair through pytest.
_ORIGINAL = "return a - b"
_FIRST_FIX = "return a * b"
_CORRECT = "return a + b"


async def scripted_coding_chat(self, model, messages, *, tools=None, **kwargs):
    """A deterministic coding scenario with the ``ProviderChatClient.chat`` shape.

    ``self`` is the provider client instance (a plain function assigned to a
    class attribute becomes a bound method). The caller never contacts a model:
    every chunk is fixed and depends only on the conversation it is handed.
    """
    prompt = next((m["content"] for m in messages if m.get("role") == "user"), "")
    if prompt.startswith("Plan the following"):
        yield StreamChunk(content=PLAN_JSON, done=True)
    elif prompt.startswith("Review task acceptance"):
        yield StreamChunk(content='{"approved": true, "reason": "sum and checks verified"}', done=True)
    elif "Tool result (edit_file)" in str(messages):
        yield StreamChunk(content="Changed buggy.py.", done=True)
    elif "Verification failed" in prompt:
        yield StreamChunk(tool_calls=[ToolCallRequest(
            name="edit_file",
            arguments={"path": "buggy.py", "old_text": _FIRST_FIX, "new_text": _CORRECT},
        )], done=True)
    elif "Tool result (read_file)" in str(messages):
        yield StreamChunk(tool_calls=[ToolCallRequest(
            name="edit_file",
            arguments={"path": "buggy.py", "old_text": _ORIGINAL, "new_text": _FIRST_FIX},
        )], done=True)
    elif "Current step:" in prompt:
        yield StreamChunk(tool_calls=[ToolCallRequest(
            name="read_file", arguments={"path": "buggy.py"},
        )], done=True)
    else:
        yield StreamChunk(content="pong", done=True)


def install_scripted_model() -> None:
    """Swap the provider chat client for the deterministic scenario (test-only)."""
    from axiom.core.providers.runtime import ProviderChatClient

    ProviderChatClient.chat = scripted_coding_chat  # type: ignore[method-assign]


__all__ = ["PLAN_JSON", "install_scripted_model", "scripted_coding_chat"]
