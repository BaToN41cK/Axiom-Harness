"""W3.6: streaming WebSocket transport over the canonical runtime."""
from __future__ import annotations

import json

from axiom.core.config import Config
from axiom.core.events import ContentChunk, Done, ErrorEvent
from axiom.core.state import GenerationState
from axiom.frontends.headless import WebSocketStreamServer, stream_headless


class _FakeSession:
    """Yields a fixed event sequence, recording the prompt it was given."""

    def __init__(self, events) -> None:
        self._events = list(events)
        self.prompt: str | None = None

    async def send(self, prompt: str):
        self.prompt = prompt
        for event in self._events:
            yield event


async def test_stream_headless_yields_normalized_events() -> None:
    session = _FakeSession([
        ContentChunk(text="Hello"),
        ContentChunk(text=" world"),
        Done(state=GenerationState.COMPLETED, duration_ms=9, tokens_out=2),
    ])
    events = [event async for event in stream_headless("hi", config=Config(), session_factory=lambda c: session)]
    assert events[0] == {"type": "content", "text": "Hello"}
    assert events[-1]["type"] == "done"
    assert events[-1]["state"] == "completed"
    assert events[-1]["tokens_out"] == 2


async def test_stream_headless_reports_error() -> None:
    session = _FakeSession([ErrorEvent(message="boom")])
    events = [event async for event in stream_headless("hi", config=Config(), session_factory=lambda c: session)]
    assert events == [{"type": "error", "message": "boom", "kind": "error", "hint": None}]


async def test_websocket_rejects_bad_token() -> None:
    import websockets

    server = WebSocketStreamServer(token="secret")
    port = await server.start()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}", proxy=None) as ws:
            await ws.send("wrong-token")
            message = json.loads(await ws.recv())
            assert message == {"type": "error", "message": "unauthorized"}
    finally:
        await server.stop()


async def test_websocket_streams_events() -> None:
    import websockets

    session = _FakeSession([
        ContentChunk(text="Hello"),
        ContentChunk(text=" world"),
        Done(state=GenerationState.COMPLETED, tokens_out=2),
    ])
    server = WebSocketStreamServer(token="secret", session_factory=lambda c: session)
    port = await server.start()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}", proxy=None) as ws:
            await ws.send("secret")
            await ws.send(json.dumps({"prompt": "hello"}))
            events = [json.loads(await ws.recv()) for _ in range(3)]
        assert [e["type"] for e in events] == ["content", "content", "done"]
        assert events[-1]["state"] == "completed"
        assert session.prompt == "hello"
    finally:
        await server.stop()
