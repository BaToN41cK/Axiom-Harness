"""Multi-engine search chain — the real internet access of AXIOM.

No single key-less search endpoint is reliable forever: DuckDuckGo now answers
plain HTTP clients with an anti-bot page, while Brave's HTML endpoint keeps
serving real results. AXIOM therefore tries a *chain* of real providers and
returns the first one that actually produced results, remembering which engine
answered so the UI can report it truthfully.

    Brave  →  DuckDuckGo  →  SearXNG  →  Wikipedia

Each provider gets a short retry on transient network errors (a VPN
reconnecting mid-request drops connections that a retry one second later
survives), so a provider is only declared dead after real, repeated failure.

If every provider fails, the original :class:`SearchUnavailableError` is raised:
the UI then shows "Search unavailable" instead of inventing an answer.
"""

from __future__ import annotations

import httpx

from axiom.core.errors import SearchUnavailableError
from axiom.core.retry import retry_async
from axiom.core.search.brave import BraveProvider
from axiom.core.search.duckduckgo import DuckDuckGoProvider
from axiom.core.search.provider import SearchProvider, SearchResult
from axiom.core.search.searxng import SearXNGProvider
from axiom.core.search.wikipedia import WikipediaProvider


def default_chain() -> list[SearchProvider]:
    """The providers AXIOM tries, in order of usefulness.

    SearXNG sits after the direct engines: it aggregates many backends and
    keeps the chain alive in regions where Brave and DuckDuckGo are blocked.
    """
    return [BraveProvider(), DuckDuckGoProvider(), SearXNGProvider(), WikipediaProvider()]


#: Valid ``Config.search_provider`` values, in display order.
SEARCH_PROVIDER_IDS = ("auto", "brave", "duckduckgo", "searxng", "wikipedia")

_SEARCH_PROVIDER_NAMES = {
    "auto": "Auto (Brave → DuckDuckGo → SearXNG → Wikipedia)",
    "brave": "Brave",
    "duckduckgo": "DuckDuckGo",
    "searxng": "SearXNG",
    "wikipedia": "Wikipedia",
}


def search_provider_choices() -> list[dict]:
    """Provider list for a settings dropdown / TUI option list."""
    return [{"id": pid, "name": _SEARCH_PROVIDER_NAMES[pid]} for pid in SEARCH_PROVIDER_IDS]


def _single_provider(provider_id: str, timeout: float | None = None) -> SearchProvider:
    if provider_id == "brave":
        return BraveProvider(timeout=timeout) if timeout else BraveProvider()
    if provider_id == "duckduckgo":
        return DuckDuckGoProvider(timeout=timeout) if timeout else DuckDuckGoProvider()
    if provider_id == "searxng":
        return SearXNGProvider(timeout=timeout) if timeout else SearXNGProvider()
    if provider_id == "wikipedia":
        return WikipediaProvider(timeout=timeout) if timeout else WikipediaProvider()
    raise ValueError(f"Unknown search provider: {provider_id}")


def build_search_provider(selection: str | None, timeout: float | None = None) -> SearchProvider:
    """Build the search backend for ``Config.search_provider``.

    ``auto`` (or an unknown/empty value) keeps the resilient multi-engine chain;
    any other id pins a single engine so users can dodge a blocked provider.
    """
    selection = (selection or "auto").strip().lower()
    if selection == "auto":
        return MultiSearchProvider(timeout=timeout)
    return _single_provider(selection, timeout=timeout)


class MultiSearchProvider(SearchProvider):
    """Runs a chain of real providers and reports which one answered."""

    name = "Web"

    #: Ceiling on raw page download, independent of the context trim.
    MAX_DOWNLOAD_CHARS = 3_000_000

    #: Transient-failure retries per provider: a VPN switch kills in-flight
    #: connections, and a fresh attempt a second later usually succeeds.
    TRANSIENT_RETRIES = 2
    TRANSIENT_RETRY_DELAY = 1.0

    def __init__(self, providers: list[SearchProvider] | None = None, timeout: float | None = None) -> None:
        self._providers = list(providers) if providers else default_chain()
        if timeout is not None and timeout > 0:
            for provider in self._providers:
                # Every built-in provider stores its httpx.Timeout as _timeout.
                setter = getattr(provider, "_apply_timeout", None)
                if setter is not None:
                    setter(timeout)
                elif hasattr(provider, "_timeout"):
                    provider._timeout = httpx.Timeout(timeout, connect=min(10.0, timeout))
        #: Name of the provider that produced the last successful search.
        self.last_provider: str = ""
        #: Real errors of every provider that failed during the last search.
        self.last_errors: list[str] = []

    @property
    def providers(self) -> list[SearchProvider]:
        return list(self._providers)

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        query = (query or "").strip()
        if not query:
            return []
        self.last_provider = ""
        self.last_errors = []
        for provider in self._providers:
            # Retry transient network errors only (VPN reconnect, DNS hiccup):
            # a provider that really answers with garbage is not retried.
            retried = await retry_async(
                provider.search,
                kwargs={"query": query, "limit": limit},
                max_attempts=self.TRANSIENT_RETRIES,
                base_delay=self.TRANSIENT_RETRY_DELAY,
                max_delay=self.TRANSIENT_RETRY_DELAY,
            )
            if retried.ok:
                results = retried.value
            else:
                self.last_errors.append(f"{provider.name}: {retried.error}")
                continue
            if results:
                self.last_provider = provider.name
                return results
            self.last_errors.append(f"{provider.name}: no results")
        reason = "; ".join(self.last_errors[:3]) or "no provider returned results"
        raise SearchUnavailableError(
            "Web search is unavailable.",
            hint=f"Tried {len(self._providers)} engines — {reason}",
        )

    async def fetch(self, url: str, max_chars: int = 4000) -> str:
        """Read a page with the first provider that succeeds.

        The raw download is capped (``MAX_DOWNLOAD_CHARS``) before HTML is
        turned into text, so huge pages cannot blow up memory; the text itself
        is still trimmed to ``max_chars``.
        """
        for provider in self._providers:
            retried = await retry_async(
                provider.fetch,
                kwargs={"url": url, "max_chars": self.MAX_DOWNLOAD_CHARS},
                max_attempts=self.TRANSIENT_RETRIES,
                base_delay=self.TRANSIENT_RETRY_DELAY,
                max_delay=self.TRANSIENT_RETRY_DELAY,
            )
            if retried.ok:
                text = retried.value
                return text[:max_chars].rstrip() + "…" if len(text) > max_chars else text
            self.last_errors.append(f"{provider.name}: {retried.error}")
        raise SearchUnavailableError(
            f"Could not read source: {url}",
            hint="; ".join(self.last_errors[:3]) or None,
        )
