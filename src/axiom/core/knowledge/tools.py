"""Knowledge tools — the model's only way into the knowledge base (W2.2).

Every search returns real, cited fragments: source path, line range and the
chunk text. Indexing is explicit (the user or the model asks for it) and
incremental; embeddings failures surface as honest content, never fake hits.
"""

from __future__ import annotations

from axiom.core.knowledge.manager import KnowledgeManager
from axiom.core.tools.base import (
    RISK_SAFE,
    ToolDefinition,
    ToolPermission,
    ToolResult,
)

KNOWLEDGE_SEARCH_TOOL = "knowledge_search"
KNOWLEDGE_INDEX_TOOL = "knowledge_index"
KNOWLEDGE_STATUS_TOOL = "knowledge_status"

MAX_HIT_CHARS = 1200


class KnowledgeTools:
    """Registers the three knowledge tools in a tool registry."""

    def __init__(self, manager: KnowledgeManager) -> None:
        self._manager = manager

    def register(self, registry) -> None:
        registry.register(
            ToolDefinition(
                name=KNOWLEDGE_SEARCH_TOOL,
                description=(
                    "Search the user's local knowledge base (indexed documents) "
                    "and return cited fragments with source path and line range. "
                    "Use this before answering questions about the user's documents."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What to look for."},
                        "collection": {
                            "type": "string",
                            "description": "Collection name; empty = search every collection.",
                        },
                        "limit": {"type": "integer", "description": "Max fragments (1-10)."},
                    },
                    "required": ["query"],
                },
                permission=ToolPermission.ALWAYS,
                risk=RISK_SAFE,
                max_output=4000,
            ),
            self._search,
        )
        registry.register(
            ToolDefinition(
                name=KNOWLEDGE_INDEX_TOOL,
                description=(
                    "Index or re-index a knowledge collection. Only changed files "
                    "are re-read; new files are added and deleted files are dropped."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Collection name."},
                        "path": {"type": "string", "description": "Root folder or file to index."},
                    },
                    "required": ["name", "path"],
                },
                permission=ToolPermission.ALWAYS,
                risk=RISK_SAFE,
                max_output=600,
            ),
            self._index,
        )
        registry.register(
            ToolDefinition(
                name=KNOWLEDGE_STATUS_TOOL,
                description="List knowledge collections with file/chunk counts and embedding status.",
                parameters={"type": "object", "properties": {}, "required": []},
                permission=ToolPermission.ALWAYS,
                risk=RISK_SAFE,
                max_output=800,
            ),
            self._status,
        )

    # --------------------------------------------------------------- handlers

    async def _search(self, query: str, collection: str = "", limit: int = 5) -> ToolResult:
        query = (query or "").strip()
        if not query:
            return ToolResult(name=KNOWLEDGE_SEARCH_TOOL, ok=False, error="query is required")
        if not isinstance(limit, int) or limit < 1 or limit > 10:
            limit = 5
        names = [collection] if collection.strip() else self._manager.names()
        stores = [self._manager.get(name) for name in names]
        stores = [store for store in stores if store is not None]
        if not stores:
            return ToolResult(
                name=KNOWLEDGE_SEARCH_TOOL, ok=True,
                content="(no knowledge collections — index a folder first)",
            )
        hits = []
        for store in stores:
            for hit in store.search(query, limit=limit):
                hits.append((store.name, hit))
        hits.sort(key=lambda item: -item[1].score)
        hits = hits[:limit]
        if not hits:
            return ToolResult(
                name=KNOWLEDGE_SEARCH_TOOL, ok=True,
                content=f"(no knowledge fragments match '{query}')",
            )
        lines = [f"Knowledge fragments for '{query}' (cite as [n]):"]
        for number, (name, hit) in enumerate(hits, start=1):
            lines.append("")
            lines.append(f"[{number}] {name}/{hit.source}:{hit.start_line}-{hit.end_line}")
            lines.append(hit.text[:MAX_HIT_CHARS])
        return ToolResult(name=KNOWLEDGE_SEARCH_TOOL, ok=True, content="\n".join(lines))

    async def _index(self, name: str, path: str) -> ToolResult:
        name = (name or "").strip()
        if not name:
            return ToolResult(name=KNOWLEDGE_INDEX_TOOL, ok=False, error="name is required")
        error = self._manager.add(name, path)
        if error is not None:
            return ToolResult(name=KNOWLEDGE_INDEX_TOOL, ok=False, error=error)
        store = self._manager.get(name)
        assert store is not None  # add() just succeeded
        stats = store.index(embedder=self._manager.embedder)
        status = store.status()
        content = (
            f"Indexed '{name}': {stats.indexed} new/changed, {stats.unchanged} unchanged, "
            f"{stats.removed} removed, {stats.skipped} skipped — "
            f"{status['files']} files / {status['chunks']} chunks total. "
            f"Embeddings: {status['embeddings']}."
        )
        if stats.errors:
            content += " Errors: " + "; ".join(stats.errors[:3])
        return ToolResult(name=KNOWLEDGE_INDEX_TOOL, ok=True, content=content)

    async def _status(self) -> ToolResult:
        names = self._manager.names()
        if not names:
            return ToolResult(name=KNOWLEDGE_STATUS_TOOL, ok=True, content="(no collections)")
        lines = []
        for name in names:
            store = self._manager.get(name)
            if store is None:
                continue
            info = store.status()
            lines.append(
                f"- {info['name']}: {info['files']} files, {info['chunks']} chunks "
                f"({info['embedded']} embedded, embeddings: {info['embeddings']}) — {info['path']}"
            )
        model = self._manager.embed_model or "disabled"
        lines.append(f"Embedding model: {model}")
        return ToolResult(name=KNOWLEDGE_STATUS_TOOL, ok=True, content="\n".join(lines))

