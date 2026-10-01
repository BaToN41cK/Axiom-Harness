"""W4.13: bounded TTL cache."""

from __future__ import annotations

import pytest

from axiom.core.cache import TTLCache


def test_get_set_roundtrip() -> None:
    cache = TTLCache(maxsize=4, ttl=60.0)
    cache.set("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing") is None
    assert cache.hits == 1
    assert cache.misses == 1


def test_expiry(monkeypatch) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr("axiom.core.cache.time.monotonic", lambda: clock["now"])
    cache = TTLCache(ttl=10.0)
    cache.set("a", 1)
    assert cache.get("a") == 1
    clock["now"] = 11.0
    assert cache.get("a") is None
    assert len(cache) == 0


def test_maxsize_evicts_oldest() -> None:
    cache = TTLCache(maxsize=2, ttl=60.0)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert cache.evictions == 1


def test_len_prunes_expired(monkeypatch) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr("axiom.core.cache.time.monotonic", lambda: clock["now"])
    cache = TTLCache(ttl=5.0)
    cache.set("a", 1)
    cache.set("b", 2)
    clock["now"] = 6.0
    assert len(cache) == 0


def test_invalid_config() -> None:
    with pytest.raises(ValueError):
        TTLCache(maxsize=0)
    with pytest.raises(ValueError):
        TTLCache(ttl=0)
