"""Shared cooperative cancellation for task-scoped work (W4.14).

One :class:`CancelToken` belongs to a task run; every checkpoint (step
start, model request, tool execution, verification attempt) observes it,
and cancelling a parent token cancels linked children (subagents, retries).
``raise_if_cancelled`` raises :class:`asyncio.CancelledError` so all
existing cancellation handling — process-tree reaping, state transitions,
preserved checkpoints — applies unchanged.
"""
from __future__ import annotations

import asyncio
import threading


class CancelToken:
    """A thread-safe cancellation signal with parent/child linking.

    Cancelling a parent cancels every linked child; cancelling a child
    never affects its parent. A child created after the parent was
    cancelled starts already cancelled.
    """

    def __init__(self, parent: CancelToken | None = None) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._children: list[CancelToken] = []
        if parent is not None:
            with parent._lock:
                parent._children.append(self)
                if parent._event.is_set():
                    self._event.set()

    @property
    def cancelled(self) -> bool:
        """True once cancellation has been requested on this token."""
        return self._event.is_set()

    def cancel(self) -> None:
        """Request cancellation; idempotent and propagated to children."""
        if self._event.is_set():
            return
        self._event.set()
        with self._lock:
            children = list(self._children)
        for child in children:
            child.cancel()

    def child(self) -> CancelToken:
        """Derive a linked token for a scoped unit of work."""
        return CancelToken(parent=self)

    def raise_if_cancelled(self) -> None:
        """Abort the current operation when cancellation was requested."""
        if self._event.is_set():
            raise asyncio.CancelledError("operation cancelled")

    def __repr__(self) -> str:
        state = "cancelled" if self.cancelled else "active"
        return f"<CancelToken {state} children={len(self._children)}>"
