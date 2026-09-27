"""Curated Memory — user-controlled durable facts, preferences, and decisions (W2.1).

Memory items are stored in ``~/.axiom/memory.json`` (global) or ``.axiom/memory.json``
(project). Each item has a scope, category, and content. The model accesses memory
only through tools; banned content never reaches disk.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from axiom.core.config import axiom_home
from axiom.core.logging import get_logger
from axiom.core.tools.base import (
    RISK_SAFE,
    ToolDefinition,
    ToolPermission,
    ToolResult,
)

_LOG = get_logger("memory")

#: Memory scopes: global (all sessions), project (workspace-specific), conversation (future).
MemoryScope = Literal["global", "project", "conversation"]

#: Memory categories: normal (general facts), sensitive (user preferences), banned (never store).
MemoryCategory = Literal["normal", "sensitive", "banned"]


@dataclass
class MemoryItem:
    """A single memory item with scope, category, and content."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    scope: MemoryScope = "global"
    category: MemoryCategory = "normal"
    content: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)


class MemoryStore:
    """Persistent storage for memory items with scope and category filtering.

    Global memory: ``~/.axiom/memory.json``
    Project memory: ``<project>/.axiom/memory.json``
    """

    def __init__(self, scope: MemoryScope = "global", project_root: Path | None = None) -> None:
        self.scope = scope
        self.project_root = project_root
        self._items: dict[str, MemoryItem] = {}
        self._load()

    def _path(self) -> Path:
        if self.scope == "project" and self.project_root:
            return self.project_root / ".axiom" / "memory.json"
        return axiom_home() / "memory.json"

    def _load(self) -> None:
        """Load memory items from disk. A corrupt file never crashes the app."""
        path = self._path()
        if not path.exists():
            self._items = {}
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("items"), list):
                self._items = {
                    item["id"]: MemoryItem(**item)
                    for item in raw["items"]
                    if isinstance(item, dict) and "id" in item
                }
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            _LOG.warning("Could not load memory from %s: %s", path, exc)
            self._items = {}

    def _save(self) -> None:
        """Persist memory items atomically."""
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        payload = {"items": [item.to_dict() for item in self._items.values()]}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def add(self, item: MemoryItem) -> bool:
        """Add or update a memory item. Banned items are rejected (never stored).

        The store stamps its own scope on the item: everything written into a
        project store is a project-scoped memory, and vice versa.
        """
        if item.category == "banned":
            _LOG.warning("Rejected banned memory item: %s", item.content[:80])
            return False
        item.scope = self.scope
        item.touch()
        self._items[item.id] = item
        self._save()
        _LOG.info("Memory added: %s [%s/%s]", item.id, item.scope, item.category)
        return True

    def remove(self, item_id: str) -> bool:
        """Remove a memory item by ID."""
        if item_id in self._items:
            del self._items[item_id]
            self._save()
            _LOG.info("Memory removed: %s", item_id)
            return True
        return False

    def get(self, item_id: str) -> MemoryItem | None:
        """Retrieve a single memory item by ID."""
        return self._items.get(item_id)

    def list(
        self,
        category: MemoryCategory | None = None,
        tag: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryItem]:
        """List memory items, newest first, optionally filtered by category or tag."""
        items = list(self._items.values())
        if category:
            items = [item for item in items if item.category == category]
        if tag:
            items = [item for item in items if tag in item.tags]
        items.sort(key=lambda x: x.updated_at, reverse=True)
        if limit:
            items = items[:limit]
        return items


    def search(self, query: str, limit: int = 10) -> list[MemoryItem]:
        """Full-text search over memory content (case-insensitive)."""
        needle = query.strip().casefold()
        if not needle:
            return []
        matches = [
            item for item in self._items.values() if needle in item.content.casefold()
        ]
        matches.sort(key=lambda x: x.updated_at, reverse=True)
        return matches[:limit]

    def retrieve_relevant(self, query: str, budget: int = 5) -> list[MemoryItem]:
        """Budgeted retrieval: only the most relevant items enter context.

        Scores query terms against content and tags; falls back to the newest
        items when nothing matches. Never returns more than ``budget`` items,
        so the full store never enters the model context (W2.1 DoD).
        """
        if budget < 1:
            return []
        terms = [t for t in query.casefold().split() if len(t) > 2]
        scored: list[tuple[int, MemoryItem]] = []
        for item in self._items.values():
            haystack = (item.content + " " + " ".join(item.tags)).casefold()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1].updated_at), reverse=True)
        relevant = [item for _, item in scored[:budget]]
        if not relevant:
            relevant = self.list(limit=budget)
        return relevant

    def count(self) -> int:
        """Total number of stored memory items."""
        return len(self._items)



class MemoryTools:
    """Tool definitions and handlers for agent memory access.

    The model accesses memory only through these tools; direct store access
    is reserved for UI/management commands. Reads merge the global store and
    (when present) the current project store.
    """

    def __init__(self, store: MemoryStore, project_store: MemoryStore | None = None) -> None:
        self.store = store
        self.project_store = project_store

    # ------------------------------------------------------------------ utils

    def _stores(self) -> list[MemoryStore]:
        """Stores a read must consult: project first (most specific), then global."""
        seen: list[MemoryStore] = []
        for candidate in (self.project_store, self.store):
            if candidate is not None and all(candidate is not s for s in seen):
                seen.append(candidate)
        return seen

    def stores(self) -> list[MemoryStore]:
        """Public view of the backing stores (UI projections iterate this)."""
        return self._stores()

    def _write_store(self, scope: str) -> MemoryStore:
        if scope == "project" and self.project_store is not None:
            return self.project_store
        return self.store

    def _merge(self, per_store: list[list[MemoryItem]], limit: int) -> list[MemoryItem]:
        """Merge per-store results by id, newest first, capped at ``limit``."""
        merged: dict[str, MemoryItem] = {}
        for items in per_store:
            for item in items:
                merged.setdefault(item.id, item)
        result = sorted(merged.values(), key=lambda x: x.updated_at, reverse=True)
        return result[:limit]

    def relevant(self, query: str, budget: int = 5) -> list[MemoryItem]:
        """Budgeted slice for system-prompt injection (never the full store)."""
        if budget < 1:
            return []
        per_store = [
            store.retrieve_relevant(query, budget=budget) for store in self._stores()
        ]
        return self._merge(per_store, budget)

    def register(self, registry) -> None:
        """Register memory tools with the agent's tool registry."""
        registry.register(
            ToolDefinition(
                name="memory_write",
                description=(
                    "Store a fact, preference, or decision in persistent memory. "
                    "Use this to remember important information across conversations, "
                    "such as user preferences, project decisions, or recurring patterns."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The information to remember.",
                        },
                        "category": {
                            "type": "string",
                            "enum": ["normal", "sensitive"],
                            "description": "normal = general facts, sensitive = user preferences.",
                        },
                        "scope": {
                            "type": "string",
                            "enum": ["global", "project"],
                            "description": (
                                "Where to store: 'global' survives across projects, "
                                "'project' belongs to the current workspace (default: global)."
                            ),
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional tags for organization (e.g. 'project').",
                        },
                    },
                    "required": ["content"],
                },
                permission=ToolPermission.ASK,
                risk=RISK_SAFE,
                max_output=400,
            ),
            self._write,
        )
        registry.register(
            ToolDefinition(
                name="memory_read",
                description=(
                    "Retrieve stored memory items. Use this to recall facts, "
                    "preferences, or decisions from previous conversations."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (substring match).",
                        },
                        "tag": {"type": "string", "description": "Filter by tag."},
                        "limit": {
                            "type": "integer",
                            "description": "Max items to return (default 10).",
                        },
                    },
                    "required": [],
                },
                permission=ToolPermission.ALWAYS,
                risk=RISK_SAFE,
                max_output=3000,
            ),
            self._read,
        )
        registry.register(
            ToolDefinition(
                name="memory_forget",
                description=(
                    "Remove a memory item by ID. Use this when information is "
                    "no longer relevant or correct."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "item_id": {
                            "type": "string",
                            "description": "The ID of the memory item to remove.",
                        },
                    },
                    "required": ["item_id"],
                },
                permission=ToolPermission.ASK,
                risk=RISK_SAFE,
                max_output=200,
            ),
            self._forget,
        )


    async def _write(
        self,
        content: str,
        category: str = "normal",
        scope: str = "global",
        tags: list[str] | None = None,
    ) -> ToolResult:
        if not content or not content.strip():
            return ToolResult(name="memory_write", ok=False, error="content is required")
        if len(content) > 2000:
            return ToolResult(
                name="memory_write", ok=False, error="content is too long (max 2000 chars)"
            )
        if category not in ("normal", "sensitive"):
            category = "normal"
        target = self._write_store(scope)
        item = MemoryItem(
            scope=target.scope,
            category=category,  # type: ignore[arg-type]
            content=content.strip(),
            tags=[t.strip() for t in (tags or []) if isinstance(t, str) and t.strip()],
        )
        if not target.add(item):
            return ToolResult(name="memory_write", ok=False, error="memory item was rejected")
        tag_part = f" (tags: {', '.join(item.tags)})" if item.tags else ""
        return ToolResult(
            name="memory_write",
            ok=True,
            content=f"Memory stored with ID: {item.id} in {item.scope} scope{tag_part}",
        )

    async def _read(self, query: str = "", tag: str = "", limit: int = 10) -> ToolResult:
        if not isinstance(limit, int) or limit < 1 or limit > 50:
            limit = 10
        per_store: list[list[MemoryItem]] = []
        for store in self._stores():
            if query:
                per_store.append(store.search(query, limit=limit))
            elif tag:
                per_store.append(store.list(tag=tag, limit=limit))
            else:
                per_store.append(store.list(limit=limit))
        items = self._merge(per_store, limit)
        if not items:
            return ToolResult(name="memory_read", ok=True, content="(no matching memory items)")
        lines = [f"Found {len(items)} memory item(s):", ""]
        for item in items:
            tag_part = f" [{', '.join(item.tags)}]" if item.tags else ""
            lines.append(f"- ID: {item.id} | {item.scope}/{item.category}{tag_part}")
            lines.append(f"  {item.content}")
        return ToolResult(name="memory_read", ok=True, content="\n".join(lines))

    async def _forget(self, item_id: str) -> ToolResult:
        if not item_id or not str(item_id).strip():
            return ToolResult(name="memory_forget", ok=False, error="item_id is required")
        cleaned = str(item_id).strip()
        for store in self._stores():
            if store.remove(cleaned):
                return ToolResult(
                    name="memory_forget", ok=True, content=f"Memory item {cleaned} removed."
                )
        return ToolResult(
            name="memory_forget", ok=False, error=f"Memory item {cleaned} not found."
        )
