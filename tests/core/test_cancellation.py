"""Shared CancelToken for cooperative task cancellation (W4.14)."""
from __future__ import annotations

import asyncio

import pytest

from axiom.core.cancellation import CancelToken


def test_cancel_propagates_to_children() -> None:
    parent = CancelToken()
    child = parent.child()
    grandchild = child.child()
    unrelated = CancelToken()
    assert not parent.cancelled and not child.cancelled
    parent.cancel()
    assert parent.cancelled and child.cancelled and grandchild.cancelled
    assert not unrelated.cancelled


def test_child_cancel_never_cancels_parent() -> None:
    parent = CancelToken()
    child = parent.child()
    child.cancel()
    assert child.cancelled
    assert not parent.cancelled


def test_child_created_after_parent_cancel_starts_cancelled() -> None:
    parent = CancelToken()
    parent.cancel()
    assert parent.child().cancelled


def test_cancel_is_idempotent() -> None:
    token = CancelToken()
    token.cancel()
    token.cancel()
    assert token.cancelled


def test_raise_if_cancelled_aborts_only_after_cancel() -> None:
    token = CancelToken()
    token.raise_if_cancelled()  # no-op while active
    token.cancel()
    with pytest.raises(asyncio.CancelledError):
        token.raise_if_cancelled()
