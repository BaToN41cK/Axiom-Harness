"""Wikipedia backend — an always-available, key-less reference search.

Used as the last link of the search chain. It returns real, citable articles
through the official MediaWiki API (JSON, no scraping, no key), which keeps
AXIOM able to reach the network even when every general search engine refuses
to serve a plain HTTP client.
"""

from __future__ import annotations

import html
import re

import httpx

from axiom.core.errors import SearchUnavailableError
from axiom.core.search.brave import _read_page
from axiom.core.search.provider import SearchProvider, SearchResult

_API = "https://en.wikipedia.org/w/api.php"
_TAG_RE = re.compile(r"<[^>]+>")
_USER_AGENT = "AXIOM/1.0 (local AI workspace; +https://github.com/BaToN41cK/Axiom-Harness)"


class WikipediaProvider(SearchProvider):
    """Real article search through the MediaWiki API."""

    name = "Wikipedia"

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = httpx.Timeout(timeout, connect=10.0)
        self._headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        query = (query or "").strip()
        if not query:
            return []
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": str(max(1, limit)),
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True, headers=self._headers
            ) as client:
                response = await client.get(_API, params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchUnavailableError(
                "Reference search is unavailable.",
                hint="Check your network connection and try again.",
            ) from exc

        hits = payload.get("query", {}).get("search", [])
        results: list[SearchResult] = []
        for hit in hits:
            title = str(hit.get("title") or "").strip()
            if not title:
                continue
            slug = title.replace(" ", "_")
            snippet = html.unescape(_TAG_RE.sub("", str(hit.get("snippet") or ""))).strip()
            results.append(
                SearchResult(
                    title=title,
                    url=f"https://en.wikipedia.org/wiki/{slug}",
                    snippet=snippet,
                )
            )
        return results[: max(1, limit)]

    async def fetch(self, url: str, max_chars: int = 4000) -> str:
        url = (url or "").strip()
        if not url.startswith("http"):
            raise SearchUnavailableError("Invalid URL for source reading.")
        return await _read_page(self._timeout, self._headers, url, max_chars)
