"""Web search tool exposed to the agent loop.

The tool wraps a :class:`~axiom.core.search.provider.SearchProvider` and
returns structured results; the agent decides when it is needed.
"""

from __future__ import annotations

from axiom.core.errors import SearchUnavailableError
from axiom.core.search.provider import SearchProvider
from axiom.core.security import NetGuard, mark_untrusted
from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult

WEB_SEARCH_TOOL = "web_search"
FETCH_URL_TOOL = "fetch_url"

_SEARCH_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "The web search query."},
        "limit": {"type": "integer", "description": "Maximum number of results (1-10)."},
    },
    "required": ["query"],
}

_FETCH_PARAMETERS = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "Absolute http(s) URL of the page to read."},
    },
    "required": ["url"],
}


class WebSearchTool:
    """Registers the real search / fetch tools in a registry."""

    def __init__(self, provider: SearchProvider, max_sources: int = 5, *, local_only: bool = False) -> None:
        self._provider = provider
        self._max_sources = max_sources
        self._local_only = local_only
        self._net_guard = NetGuard()
        self.last_sources: list = []

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=WEB_SEARCH_TOOL,
            description=(
                "Search the public web for current information. "
                "Use it when the answer depends on recent or factual online sources."
            ),
            parameters=_SEARCH_PARAMETERS,
            permission=ToolPermission.ALWAYS,
        )

    def fetch_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=FETCH_URL_TOOL,
            description="Fetch and read a web page, returning its readable text.",
            parameters=_FETCH_PARAMETERS,
            permission=ToolPermission.ALWAYS,
        )

    async def search(self, query: str, limit: int | None = None) -> ToolResult:
        """Run a real search and return a formatted, model-readable result."""
        if self._local_only:
            return ToolResult(name=WEB_SEARCH_TOOL, ok=False, error="Local Only mode blocks web search")
        count = limit if isinstance(limit, int) and limit > 0 else self._max_sources
        count = max(1, min(count, self._max_sources))
        try:
            sources = await self._provider.search(query, limit=count)
        except SearchUnavailableError as exc:
            return ToolResult(name=WEB_SEARCH_TOOL, ok=False, error=str(exc), content="")
        self.last_sources = list(sources)
        if not sources:
            return ToolResult(
                name=WEB_SEARCH_TOOL,
                ok=True,
                content="No results were returned for this query.",
            )
        lines = []
        for index, source in enumerate(sources, start=1):
            lines.append(f"[{index}] {source.title}\nURL: {source.url}\n{source.snippet}")
        return ToolResult(name=WEB_SEARCH_TOOL, ok=True, content="\n\n".join(lines))

    async def fetch(self, url: str) -> ToolResult:
        """Read one page — the real "reading sources" step."""
        if self._local_only:
            return ToolResult(name=FETCH_URL_TOOL, ok=False, error="Local Only mode blocks network fetch")
        try:
            self._net_guard.validate(url)
        except ValueError as exc:
            return ToolResult(name=FETCH_URL_TOOL, ok=False, error=str(exc))
        try:
            text = await self._provider.fetch(url)
        except SearchUnavailableError as exc:
            return ToolResult(name=FETCH_URL_TOOL, ok=False, error=str(exc))
        if not text.strip():
            return ToolResult(name=FETCH_URL_TOOL, ok=True, content="(no readable text found)")
        return ToolResult(name=FETCH_URL_TOOL, ok=True, content=mark_untrusted(url, text))

    def register(self, registry) -> None:
        """Attach both tools to a :class:`ToolRegistry`."""
        registry.register(self.definition(), self.search)
        registry.register(self.fetch_definition(), self.fetch)
