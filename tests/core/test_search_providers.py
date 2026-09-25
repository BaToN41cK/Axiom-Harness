"""Search providers: charset handling and download caps (offline tests)."""

from __future__ import annotations

import httpx
import pytest

from axiom.core.errors import SearchUnavailableError
from axiom.core.search.multi import MultiSearchProvider
from axiom.core.search.provider import SearchProvider, SearchResult, _decode_body, extract_text

WINDOWS_1251_PAGE = (
    "<html><head><meta charset=\"windows-1251\">"
    "</head><body><h1>Проверка кодировки</h1><p>Текст страницы.</p></body></html>"
).encode("windows-1251")


def _response(content: bytes, charset_header: str | None = None) -> httpx.Response:
    headers = {"content-type": f"text/html; charset={charset_header}"} if charset_header else {
        "content-type": "text/html"
    }
    return httpx.Response(200, content=content, headers=headers, request=httpx.Request("GET", "http://x"))


def test_headerless_windows_1251_page_decodes_via_meta() -> None:
    text = extract_text(_decode_body(_response(WINDOWS_1251_PAGE)))
    assert "Проверка кодировки" in text


def test_declared_utf8_is_not_touched() -> None:
    page = b"<html><body>ok</body></html>"
    assert extract_text(_decode_body(_response(page))) == "ok"


def test_header_charset_wins() -> None:
    # Body is utf-8 but the header claims koi8-r: the header must be trusted.
    page = "<html><body>байт</body></html>".encode("koi8-r")
    text = _decode_body(_response(page, charset_header="koi8-r"))
    assert "байт" in text


def test_invalid_meta_charset_falls_back() -> None:
    page = b'<html><head><meta charset="not-a-real-charset"></head><body>hi</body></html>'
    assert "hi" in _decode_body(_response(page))


# ------------------------------------------------- provider timeout plumbing


def test_multi_provider_applies_timeout_to_chain() -> None:
    chain = MultiSearchProvider(timeout=7.5)
    for provider in chain.providers:
        timeout = provider._timeout
        assert timeout.read == 7.5


# --------------------------------------------------------- fetch failure path


async def test_multi_fetch_raises_when_all_providers_fail() -> None:
    class Failing(SearchProvider):
        name = "fail"

        async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
            return []

        async def fetch(self, url: str, max_chars: int = 4000) -> str:
            raise SearchUnavailableError("nope")

    provider: MultiSearchProvider = MultiSearchProvider([Failing()])
    with pytest.raises(SearchUnavailableError):
        await provider.fetch("https://example.com")


# ------------------------------------------------------------- regional chain


def test_default_chain_includes_regional_fallbacks() -> None:
    names = [p.name for p in MultiSearchProvider().providers]
    assert names[:2] == ["Brave", "DuckDuckGo"]
    # SearXNG keeps the chain alive where the direct engines are blocked,
    # Wikipedia remains the always-available last resort.
    assert "SearXNG" in names
    assert names[-1] == "Wikipedia"


def test_searxng_parse_extracts_results() -> None:
    from axiom.core.search.searxng import SearXNGProvider

    page = """
    <article class="result result-default" data-v="1">
      <h3><a href="https://en.wikipedia.org/wiki/Test" class="url_wrapper">Test - <b>Wikipedia</b></a></h3>
      <p class="content">Test (assessment), an educational assessment.</p>
    </article>
    <article class="result result-default" data-v="1">
      <h3><a href="/search?q=other">Other query</a></h3>
      <p class="content">Instance-internal link, must be skipped.</p>
    </article>
    <article class="result result-default" data-v="1">
      <h3><a href="https://example.com/a">Second &amp; result</a></h3>
      <p>Another snippet</p>
    </article>
    """
    results = SearXNGProvider._parse(page, "https://opnxng.com")
    assert len(results) == 2
    assert results[0].url == "https://en.wikipedia.org/wiki/Test"
    assert results[0].title == "Test - Wikipedia"
    assert "educational assessment" in results[0].snippet
    assert results[1].url == "https://example.com/a"


def test_searxng_skips_instance_when_no_results() -> None:
    from axiom.core.search.searxng import SearXNGProvider

    class Empty(SearXNGProvider):
        async def _get(self, url: str, params: dict[str, str]) -> str:
            return "<html><body>nothing here</body></html>"

    provider = Empty(instances=("https://one.example", "https://two.example"))
    with pytest.raises(SearchUnavailableError) as exc_info:
        import asyncio

        asyncio.run(provider.search("test"))
    assert "one.example" in (exc_info.value.hint or "")
    assert "two.example" in (exc_info.value.hint or "")


# -------------------------------------------------------- transient retries


def test_retryable_walks_wrapped_cause_chain() -> None:
    import httpx

    from axiom.core.retry import is_retryable_error

    # Providers wrap transport errors into SearchUnavailableError; the cause
    # chain must still make the wrapper retryable.
    try:
        try:
            raise httpx.ConnectError("connection refused")
        except httpx.ConnectError as inner:
            raise SearchUnavailableError("Web search is unavailable.") from inner
    except SearchUnavailableError as wrapped:
        assert is_retryable_error(wrapped) is True

    # A plain logic error is not a network problem: no retry.
    assert is_retryable_error(ValueError("bad markup")) is False


async def test_multi_retries_transient_provider_failure() -> None:
    import httpx

    class Flaky(SearchProvider):
        name = "flaky"

        def __init__(self) -> None:
            self.calls = 0

        async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
            self.calls += 1
            if self.calls == 1:
                try:
                    raise httpx.ConnectError("vpn switch dropped the socket")
                except httpx.ConnectError as inner:
                    raise SearchUnavailableError("Web search is unavailable.") from inner
            return [SearchResult(title="hit", url="https://example.com/ok")]

        async def fetch(self, url: str, max_chars: int = 4000) -> str:
            raise SearchUnavailableError("nope")

    flaky = Flaky()
    provider = MultiSearchProvider([flaky])
    # Keep the retry wait short in tests.
    provider.TRANSIENT_RETRY_DELAY = 0.0
    results = await provider.search("anything")
    assert flaky.calls == 2
    assert results[0].url == "https://example.com/ok"
    assert provider.last_provider == "flaky"


# ----------------------------------------------------- provider selection (W1.2)


def test_search_provider_choices_cover_all_ids() -> None:
    from axiom.core.search.multi import SEARCH_PROVIDER_IDS, search_provider_choices

    choices = search_provider_choices()
    assert [c["id"] for c in choices] == list(SEARCH_PROVIDER_IDS)
    # Every choice carries a human label for the settings dropdown.
    assert all(c["name"] for c in choices)


def test_build_search_provider_auto_returns_full_chain() -> None:
    from axiom.core.search.multi import MultiSearchProvider, build_search_provider

    provider = build_search_provider("auto", timeout=5.0)
    assert isinstance(provider, MultiSearchProvider)
    # Timeout is retuned across the whole chain.
    assert provider.providers[0]._timeout.read == 5.0


def test_build_search_provider_pins_single_engine() -> None:
    from axiom.core.search.brave import BraveProvider
    from axiom.core.search.multi import build_search_provider
    from axiom.core.search.wikipedia import WikipediaProvider

    assert isinstance(build_search_provider("brave"), BraveProvider)
    assert isinstance(build_search_provider("wikipedia"), WikipediaProvider)


def test_build_search_provider_unknown_id_raises() -> None:
    from axiom.core.search.multi import build_search_provider

    with pytest.raises(ValueError):
        build_search_provider("bing")


def test_build_search_provider_empty_falls_back_to_auto() -> None:
    from axiom.core.search.multi import MultiSearchProvider, build_search_provider

    assert isinstance(build_search_provider(None), MultiSearchProvider)
    assert isinstance(build_search_provider(""), MultiSearchProvider)


# --------------------------------------------------- ChatSession.search_test (W1.2)


async def test_search_test_reports_online_with_real_results(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config

    class Stub(SearchProvider):
        name = "StubEngine"

        async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
            return [SearchResult(title="Hit", url="https://example.com", snippet="s")]

        async def fetch(self, url: str, max_chars: int = 4000) -> str:
            return ""

    session = ChatSession(config=Config(), provider=Stub())
    report = await session.search_test("axiom")
    assert report["ok"] is True
    assert report["provider"] == "StubEngine"
    assert report["result_count"] == 1
    assert report["results"][0]["url"] == "https://example.com"
    assert report["error"] is None
    assert report["latency_ms"] >= 0


async def test_search_test_reports_offline_on_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config

    class Dead(SearchProvider):
        name = "DeadEngine"

        async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
            raise SearchUnavailableError("no network", hint="check VPN")

        async def fetch(self, url: str, max_chars: int = 4000) -> str:
            return ""

    session = ChatSession(config=Config(), provider=Dead())
    report = await session.search_test("axiom")
    assert report["ok"] is False
    assert report["provider"] == "DeadEngine"
    assert report["result_count"] == 0
    assert report["error"] == "no network"
    assert report["hint"] == "check VPN"


async def test_search_test_rejects_empty_query(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config

    session = ChatSession(config=Config())
    report = await session.search_test("   ")
    assert report["ok"] is False
    assert report["error"] == "Empty query"
