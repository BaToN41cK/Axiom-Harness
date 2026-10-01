"""Bounded time-to-live cache (W4.13).

A small, thread-safe cache for derived or expensive values (index entries,
model-catalog lookups, parsed payloads). Entries expire by wall-clock TTL and
the cache evicts oldest-first beyond ``maxsize``, so long tasks cannot grow
memory without bound. ``hits``/``misses``/``evictions`` let a caller observe the
cache instead of guessing whether it helps.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Hashable
from threading import Lock
from typing import Generic, TypeVar

_K = TypeVar("_K", bound=Hashable)
_V = TypeVar("_V")


class TTLCache(Generic[_K, _V]):
    """A bounded cache whose entries expire after ``ttl`` seconds."""

    def __init__(self, maxsize: int = 256, ttl: float = 60.0) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        if ttl <= 0:
            raise ValueError("ttl must be > 0")
        self.maxsize = maxsize
        self.ttl = ttl
        self._data: OrderedDict[_K, tuple[float, _V]] = OrderedDict()
        self._lock = Lock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, key: _K) -> _V | None:
        """Return the live value for ``key``, or ``None`` if absent/expired."""
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires, value = entry
            if expires <= now:
                del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: _K, value: _V) -> None:
        """Store ``value`` under ``key``, evicting oldest-first past ``maxsize``."""
        now = time.monotonic()
        with self._lock:
            self._data[key] = (now + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)
                self.evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        """Number of live (unexpired) entries, pruning as a side effect."""
        with self._lock:
            now = time.monotonic()
            expired = [key for key, (expires, _value) in self._data.items() if expires <= now]
            for key in expired:
                del self._data[key]
            return len(self._data)


__all__ = ["TTLCache"]
