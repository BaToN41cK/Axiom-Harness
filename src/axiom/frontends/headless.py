"""Headless / scriptable entry points (W3.6).

``axiom run "prompt" --json`` runs one prompt through the canonical
:class:`~axiom.core.chat.ChatSession` and prints a JSON result, so scripts, CI
and editors can drive the same runtime without embedding agent logic.
``axiom serve`` exposes a token-protected localhost HTTP API (``/v1/status``,
``/v1/run``) over the same runtime and refuses to bind anything but localhost.

Both the runner and the server take a ``session_factory`` so tests can inject a
fake session — the default path uses the real ``ChatSession``/Task Runtime.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from axiom.core.chat import ChatSession
from axiom.core.config import Config
from axiom.core.events import ContentChunk, Done, ErrorEvent

#: A session factory builds the runtime for one run; the default uses ChatSession.
SessionFactory = Callable[[Config], Any]

#: Hosts the local API will bind; anything else is rejected as a non-local bind.
LOCAL_BINDS = frozenset({"127.0.0.1", "localhost", "::1"})


def validate_bind_host(host: str) -> list[str]:
    """Return the problems with a local-API bind host (empty = safe)."""
    if host not in LOCAL_BINDS:
        return [f"refusing non-local bind host {host!r}; the local API listens on localhost only"]
    return []


def _arg(argv: list[str], name: str, default: str | None = None) -> str | None:
    try:
        return argv[argv.index(name) + 1]
    except (ValueError, IndexError):
        return default


async def run_headless(
    prompt: str,
    config: Config | None = None,
    *,
    session_factory: SessionFactory | None = None,
) -> dict[str, Any]:
    """Run one prompt through the canonical runtime; return a structured result."""
    cfg = config or Config.load()
    factory = session_factory or (lambda c: ChatSession(config=c))
    session = factory(cfg)
    answer_parts: list[str] = []
    state = "unknown"
    metrics: dict[str, Any] = {}
    error: str | None = None
    try:
        async for event in session.send(prompt):
            if isinstance(event, ContentChunk):
                answer_parts.append(event.text)
            elif isinstance(event, ErrorEvent):
                error = event.message
            elif isinstance(event, Done):
                state = event.state.value
                metrics = {
                    "duration_ms": event.duration_ms,
                    "tokens_in": event.tokens_in,
                    "tokens_out": event.tokens_out,
                    "tokens_per_second": event.tokens_per_second,
                    "ttft_ms": event.ttft_ms,
                    "load_ms": event.load_ms,
                    "stop_reason": event.stop_reason,
                }
    except Exception as exc:  # a headless run must report, never crash the caller
        error = f"{type(exc).__name__}: {exc}"
    return {
        "ok": error is None and state == "completed",
        "answer": "".join(answer_parts),
        "error": error,
        "state": state,
        "metrics": metrics,
    }


def main_run(argv: list[str]) -> int:
    """``axiom run "prompt" [--json]`` — run one prompt and print the result."""
    json_mode = "--json" in argv
    prompt = " ".join(a for a in argv if not a.startswith("-"))
    if not prompt:
        print('usage: axiom run "prompt" [--json]', file=sys.stderr)
        return 2
    result = asyncio.run(run_headless(prompt))
    if json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["answer"] if result["ok"] else (result["error"] or "failed"))
    return 0 if result["ok"] else 1


def _make_handler(token: str, session_factory: SessionFactory | None) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            return self.headers.get("Authorization", "") == f"Bearer {token}"

        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")

        def do_GET(self) -> None:
            if self.path != "/v1/status":
                self._json({"ok": False, "error": "not found"}, 404)
                return
            if not self._authorized():
                self._json({"ok": False, "error": "unauthorized"}, 401)
                return
            self._json({"ok": True, "status": "ready"})

        def do_POST(self) -> None:
            if self.path != "/v1/run":
                self._json({"ok": False, "error": "not found"}, 404)
                return
            if not self._authorized():
                self._json({"ok": False, "error": "unauthorized"}, 401)
                return
            try:
                payload = self._read_json()
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._json({"ok": False, "error": "invalid JSON body"}, 400)
                return
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt:
                self._json({"ok": False, "error": "missing 'prompt'"}, 400)
                return
            result = asyncio.run(run_headless(prompt, session_factory=session_factory))
            self._json(result)

        def log_message(self, *_args: Any) -> None:
            return

    return _Handler


class LocalApiServer:
    """Token-protected localhost HTTP API over the canonical runtime."""

    def __init__(
        self,
        *,
        token: str | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        session_factory: SessionFactory | None = None,
    ) -> None:
        problems = validate_bind_host(host)
        if problems:
            raise ValueError(problems[0])
        self.token = token or secrets.token_urlsafe(24)
        self.host = host
        self.port = port
        self.session_factory = session_factory
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> int:
        """Bind and serve in a daemon thread; returns the bound port."""
        handler = _make_handler(self.token, self.session_factory)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self.port = self._server.server_address[1]
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        return self.port

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def main_serve(argv: list[str]) -> int:
    """``axiom serve [--token T] [--host 127.0.0.1] [--port N]``."""
    host = _arg(argv, "--host", "127.0.0.1") or "127.0.0.1"
    try:
        port = int(_arg(argv, "--port", "0") or "0")
    except ValueError:
        print("invalid --port", file=sys.stderr)
        return 2
    token = _arg(argv, "--token")
    try:
        server = LocalApiServer(token=token, host=host, port=port)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    bound = server.start()
    print(f"AXIOM local API on http://{host}:{bound} (token={server.token})")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()
    return 0


__all__ = [
    "LOCAL_BINDS",
    "LocalApiServer",
    "main_run",
    "main_serve",
    "run_headless",
    "validate_bind_host",
]
