"""Pagination and delta primitives for large payloads (W4.13).

Long tasks must not resend a whole trajectory, file list, or diff on every UI
update. The frontend requests a bounded window (``offset``/``limit``) or only
what changed after a cursor (``since``). These helpers are UI-free, deterministic
and operate on real sequences — they slice a concrete collection and report the
true total, never guessing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

_T = TypeVar("_T")


def _identity(item: _T) -> _T:
    return item


@dataclass
class Page(Generic[_T]):
    """One bounded window of a larger collection."""

    items: list[_T]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total

    def to_json(self, item_to_dict=_identity) -> dict:
        """Serialize the page; ``item_to_dict`` converts each item if needed."""
        return {
            "items": [item_to_dict(item) for item in self.items],
            "total": self.total,
            "offset": self.offset,
            "limit": self.limit,
            "has_more": self.has_more,
        }


def paginate(items: Sequence[_T], offset: int = 0, limit: int = 100) -> Page[_T]:
    """Return page ``offset``/``limit`` of a sequence, clamped and validated."""
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit <= 0:
        raise ValueError("limit must be > 0")
    total = len(items)
    start = min(offset, total)
    end = min(start + limit, total)
    return Page(items=list(items[start:end]), total=total, offset=start, limit=limit)


def paginate_lines(text: str, offset: int = 0, limit: int = 200) -> Page[str]:
    """Window a multi-line text by lines (a single copy of the payload)."""
    return paginate(text.splitlines(), offset=offset, limit=limit)


def paginate_diff(diff: str, offset: int = 0, limit: int = 1500) -> Page[str]:
    """Window a unified diff by lines instead of resending the whole patch."""
    return paginate_lines(diff, offset=offset, limit=limit)


__all__ = ["Page", "paginate", "paginate_diff", "paginate_lines"]
