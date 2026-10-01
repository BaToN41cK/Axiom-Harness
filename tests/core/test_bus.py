"""W4.13: EventBus filtering, backpressure cap and envelope validation."""

from __future__ import annotations

from axiom.core.bus import EventBus, validate_event_envelope


def test_subscribe_and_emit() -> None:
    bus = EventBus()
    seen: list[dict] = []
    off = bus.subscribe("x", lambda d: seen.append(d))
    bus.emit("x", {"n": 1})
    assert bus.emitted == 1
    assert len(seen) == 1
    assert seen[0]["n"] == 1
    assert seen[0]["event"] == "x"
    off()
    bus.emit("x", {"n": 2})
    assert len(seen) == 1


def test_predicate_filters() -> None:
    bus = EventBus()
    seen: list[int] = []
    bus.subscribe("x", lambda d: seen.append(d["n"]), predicate=lambda d: d["n"] % 2 == 0)
    bus.emit("x", {"n": 1})
    bus.emit("x", {"n": 2})
    bus.emit("x", {"n": 4})
    assert seen == [2, 4]


def test_listener_cap_drops_oldest() -> None:
    bus = EventBus(max_listeners=2)
    calls: list[str] = []
    bus.subscribe("x", lambda _d: calls.append("a"))
    bus.subscribe("x", lambda _d: calls.append("b"))
    bus.subscribe("x", lambda _d: calls.append("c"))
    assert bus.dropped == 1
    assert bus.listener_count("x") == 2
    bus.emit("x")
    assert calls == ["b", "c"]


def test_unsubscribe() -> None:
    bus = EventBus()

    def handler(_data: dict) -> None:
        return None

    bus.subscribe("x", handler)
    assert bus.listener_count("x") == 1
    bus.unsubscribe("x", handler)
    assert bus.listener_count("x") == 0


def test_validate_envelope() -> None:
    assert validate_event_envelope({"event": "x"}) == []
    assert validate_event_envelope({"event": "x", "ts": 1.2}) == []
    assert validate_event_envelope({"ts": 1.2}) != []  # missing event
    assert validate_event_envelope({"event": "x", "ts": "now"}) != []  # bad ts
    assert validate_event_envelope("not a dict") != []  # type: ignore[arg-type]
