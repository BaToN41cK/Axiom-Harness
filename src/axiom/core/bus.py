"""Event Bus — внутренние события harness (п.6).

UI, logging, agents, plugins и telemetry подписываются на события,
а не дёргают друг друга напрямую.
"""
from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

# Каноничные имена событий harness.
AGENT_CREATED = "agent.created"
AGENT_STARTED = "agent.started"
AGENT_STEP = "agent.step"
AGENT_FAILED = "agent.failed"
MODEL_REQUEST = "model.request"
MODEL_RESPONSE = "model.response"
TOOL_BEFORE = "tool.before"
TOOL_AFTER = "tool.after"
FILE_CHANGED = "file.changed"
TEST_STARTED = "test.started"
TEST_FINISHED = "test.finished"
TRAJECTORY_APPEND = "trajectory.append"


Predicate = Callable[[dict[str, Any]], bool]


def validate_event_envelope(payload: dict[str, Any]) -> list[str]:
    """Return the list of problems in a bus payload envelope (empty = valid).

    The bus always fills ``event`` and ``ts`` when it emits; this helper lets an
    external producer (the JSONL bridge, a plugin) validate a payload before it
    is forwarded, keeping every consumer on one envelope.
    """
    if not isinstance(payload, dict):
        return ["payload must be a dict"]
    problems: list[str] = []
    event = payload.get("event")
    if not isinstance(event, str) or not event:
        problems.append("'event' must be a non-empty string")
    ts = payload.get("ts")
    if ts is not None and not isinstance(ts, (int, float)):
        problems.append("'ts' must be a number when present")
    return problems


class EventBus:
    """Minimal pub/sub: sync + async subscribers, best-effort emit.

    Subscribers may attach a ``predicate`` to filter events they care about.
    Each event type may be capped via ``max_listeners``: once a cap is reached
    the oldest listener is dropped instead of letting a hot event accumulate
    unbounded work — the in-process form of backpressure.
    """

    def __init__(self, max_listeners: int | None = None) -> None:
        self._subs: dict[str, list[tuple[Callable, Predicate | None]]] = defaultdict(list)
        self._emitted = 0
        self._dropped = 0
        self.max_listeners = max_listeners

    def subscribe(self, event: str, handler: Callable, predicate: Predicate | None = None) -> Callable:
        """Подписаться; возвращает callable для отписки."""
        entry = (handler, predicate)
        subs = self._subs[event]
        if self.max_listeners is not None and len(subs) >= self.max_listeners:
            subs.pop(0)
            self._dropped += 1
        subs.append(entry)

        def _off() -> None:
            try:
                subs.remove(entry)
            except ValueError:
                pass

        return _off

    def unsubscribe(self, event: str, handler: Callable) -> None:
        subs = self._subs.get(event)
        if not subs:
            return
        for index, (candidate, _predicate) in enumerate(subs):
            if candidate is handler:
                subs.pop(index)
                return

    @property
    def emitted(self) -> int:
        return self._emitted

    @property
    def dropped(self) -> int:
        return self._dropped

    def listener_count(self, event: str | None = None) -> int:
        if event is None:
            return sum(len(subs) for subs in self._subs.values())
        return len(self._subs.get(event, []))

    def _matches(self, predicate: Predicate | None, data: dict[str, Any]) -> bool:
        if predicate is None:
            return True
        try:
            return bool(predicate(data))
        except Exception:
            return False

    def emit(self, event: str, payload: dict | None = None) -> None:
        """Синхронный emit: async-подписчики игнорируются (см. emit_async)."""
        self._emitted += 1
        data = dict(payload or {})
        data.setdefault("event", event)
        data.setdefault("ts", time.time())
        for handler, predicate in list(self._subs.get(event, [])):
            if not self._matches(predicate, data):
                continue
            try:
                result = handler(data)
                if result is not None and hasattr(result, "__await__"):
                    try:
                        result.close()  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                continue

    async def emit_async(self, event: str, payload: dict | None = None) -> None:
        self._emitted += 1
        data = dict(payload or {})
        data.setdefault("event", event)
        data.setdefault("ts", time.time())
        for handler, predicate in list(self._subs.get(event, [])):
            if not self._matches(predicate, data):
                continue
            try:
                result = handler(data)
                if result is not None and hasattr(result, "__await__"):
                    await result
            except Exception:
                continue
