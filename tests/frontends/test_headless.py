"""W3.6: headless runner and the token-protected localhost API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from axiom.core.config import Config
from axiom.core.events import ContentChunk, Done, ErrorEvent
from axiom.core.state import GenerationState
from axiom.frontends.headless import LocalApiServer, run_headless, validate_bind_host

# Windows urllib honours the system proxy, which can 503 localhost requests.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class _FakeSession:
    """Yields a fixed event sequence, recording the prompt it was given."""

    def __init__(self, events) -> None:
        self._events = list(events)
        self.prompt: str | None = None

    async def send(self, prompt: str):
        self.prompt = prompt
        for event in self._events:
            yield event


async def test_run_headless_collects_answer_and_metrics() -> None:
    session = _FakeSession(
        [
            ContentChunk(text="Hello"),
            ContentChunk(text=" world"),
            Done(state=GenerationState.COMPLETED, duration_ms=123, tokens_out=5),
        ]
    )
    result = await run_headless("hi", config=Config(), session_factory=lambda c: session)
    assert result["ok"] is True
    assert result["answer"] == "Hello world"
    assert result["state"] == "completed"
    assert result["metrics"]["duration_ms"] == 123
    assert result["metrics"]["tokens_out"] == 5
    assert session.prompt == "hi"


async def test_run_headless_reports_error() -> None:
    session = _FakeSession([ErrorEvent(message="boom"), Done(state=GenerationState.ERROR)])
    result = await run_headless("hi", config=Config(), session_factory=lambda c: session)
    assert result["ok"] is False
    assert result["error"] == "boom"
    assert result["state"] == "error"


def test_validate_bind_host() -> None:
    assert validate_bind_host("127.0.0.1") == []
    assert validate_bind_host("localhost") == []
    assert validate_bind_host("::1") == []
    assert validate_bind_host("0.0.0.0") != []
    assert validate_bind_host("::") != []
    assert validate_bind_host("example.com") != []


def test_local_api_rejects_non_local_bind() -> None:
    with pytest.raises(ValueError, match="non-local"):
        LocalApiServer(host="0.0.0.0")


def test_local_api_status_requires_token() -> None:
    server = LocalApiServer(token="secret")
    port = server.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _OPENER.open(f"http://127.0.0.1:{port}/v1/status")
        assert exc.value.code == 401

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/status",
            headers={"Authorization": "Bearer secret"},
        )
        with _OPENER.open(req) as resp:
            data = json.loads(resp.read())
        assert data == {"ok": True, "status": "ready"}
    finally:
        server.shutdown()


def test_local_api_run_endpoint() -> None:
    session = _FakeSession([ContentChunk(text="hi"), Done(state=GenerationState.COMPLETED)])
    server = LocalApiServer(token="secret", session_factory=lambda c: session)
    port = server.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/run",
            data=json.dumps({"prompt": "hello"}).encode("utf-8"),
            headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
        )
        with _OPENER.open(req) as resp:
            data = json.loads(resp.read())
        assert data["ok"] is True
        assert data["answer"] == "hi"
        assert session.prompt == "hello"
    finally:
        server.shutdown()
