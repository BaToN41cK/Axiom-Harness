"""Тесты Provider Layer + AgentRegistry + ToolRegistry 2.0."""
from __future__ import annotations

import json
import sys

import httpx

from axiom.core.agents import AgentProfile, AgentRegistry
from axiom.core.providers.base import ModelProfile, Provider, ProviderAuthError, ProviderStatus, StreamChunk
from axiom.core.providers.catalog import ModelCatalog
from axiom.core.providers.known import known_provider_ids
from axiom.core.providers.manager import ProviderManager
from axiom.core.providers.openai_compat import OpenAICompatibleProvider
from axiom.core.providers.runtime import ProviderChatClient
from axiom.core.router import ModelRouter, RouteTarget
from axiom.core.secrets import is_protected
from axiom.core.tools.meta import category_of, resolve_tools_for_task, tools_for_agent


def test_known_providers_cover_required_ids():
    ids = set(known_provider_ids())
    for need in ("anthropic", "openai", "gemini", "deepseek", "xai", "mistral",
                 "qwen", "zai", "openrouter", "ollama", "together", "fireworks",
                 "groq", "cerebras"):
        assert need in ids

def test_provider_has_unified_interface():
    from axiom.core.providers.base import Provider
    for name in ("authenticate", "list_models", "chat", "stream", "supports_tools",
                 "supports_reasoning", "supports_vision", "supports_prompt_cache",
                 "capabilities"):
        assert hasattr(Provider, name), name


async def test_openai_compatible_sends_bearer_and_reports_mixen_response(monkeypatch):

    seen = {}

    class Response:
        status_code = 401
        text = '{"error":{"message":"invalid token"}}'

    class StreamResponse:
        status_code = 401
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def aread(self):
            return b'{"error":{"message":"invalid streaming token"}}'

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url, headers=None):
            seen.update(url=url, headers=headers)
            return Response()
        def stream(self, *args, **kwargs):
            return StreamResponse()
        async def post(self, *args, **kwargs):
            return StreamResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: Client())
    provider = OpenAICompatibleProvider("openai_compatible", "OpenAI Compatible", "https://api.mixen.ai/v1", "mxn-test")
    try:
        await provider.list_models()
    except ProviderAuthError as exc:
        assert "HTTP 401" in str(exc)
        assert "invalid token" in str(exc)
    else:
        raise AssertionError("expected ProviderAuthError")
    assert seen["url"] == "https://api.mixen.ai/v1/models"
    assert seen["headers"]["Authorization"] == "Bearer mxn-test"
    try:
        [chunk async for chunk in provider.stream("gpt-5.6-sol", [])]
    except ProviderAuthError as exc:
        assert "invalid streaming token" in str(exc)
    else:
        raise AssertionError("expected streaming ProviderAuthError")

async def test_manager_no_key_returns_empty_and_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    mgr = ProviderManager()
    assert await mgr.get_provider("deepseek").authenticate() == ProviderStatus.NOT_CONFIGURED
    assert await mgr.discover_models("deepseek") == []


def test_model_profile_capabilities():
    m = ModelProfile(id="glm-4.6", provider_id="zai", coding=True, reasoning=True, tool_calling=True)
    assert m.coding and m.reasoning and m.tool_calling
    assert not m.vision

def test_catalog_groups_by_provider():
    cat = ModelCatalog()
    cat.add([ModelProfile(id="a", provider_id="x"), ModelProfile(id="b", provider_id="y")])
    assert len(cat.for_provider("x")) == 1
    assert cat.find("b") is not None

def test_agent_registry_defaults_and_crud():
    reg = AgentRegistry()
    assert set(("orchestrator", "coder", "debugger", "reviewer", "researcher",
                "tester", "architect", "security")) <= set(reg.ids())
    reg.register(AgentProfile(id="custom", label="Custom"))
    assert reg.get("custom") is not None
    assert reg.remove("custom") is True

def test_tool_meta_agent_and_task_resolution():
    assert "web_search" in tools_for_agent("researcher")
    assert "terminal" not in tools_for_agent("researcher")
    assert "run_command" in tools_for_agent("coder")
    assert category_of("git_status") == "git"
    assert "read_file" in resolve_tools_for_task("fix bug in file")
    assert "git_status" in resolve_tools_for_task("git diff please")


def test_manager_set_key_persists_locally_and_never_leaks_into_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    mgr = ProviderManager()
    assert mgr.has_key("deepseek") is False
    mgr.set_key("deepseek", "  sk-test-123  ")
    assert mgr.has_key("deepseek") is True
    rows = mgr.status_rows()
    deepseek = next(row for row in rows if row["id"] == "deepseek")
    assert deepseek["configured"] is True
    # The key is stored on disk, but never reaches UI rows.
    assert "sk-test-123" not in json.dumps(rows, ensure_ascii=False)
    raw = (tmp_path / "providers.json").read_text(encoding="utf-8")
    stored = json.loads(raw)["deepseek"]["api_key"]
    if sys.platform == "win32":
        # DPAPI blob on disk: no plaintext, reloads to the working key.
        assert "sk-test-123" not in raw
        assert is_protected(stored)
    else:
        # POSIX keeps the value with 0600 file permissions as the boundary.
        assert stored == "sk-test-123"
    fresh = ProviderManager()
    assert fresh.has_key("deepseek") is True
    assert fresh._configs["deepseek"].api_key == "sk-test-123"


class _Provider(Provider):
    def __init__(self, name, fail=False):
        self.id, self.label, self.fail = name, name, fail

    async def stream(self, model, messages, **kwargs):
        if self.fail:
            from axiom.core.providers.base import ProviderUnavailableError
            raise ProviderUnavailableError("rate limited")
        yield StreamChunk(content=f"{self.id}:{model}")


async def test_provider_client_routes_and_falls_back_before_output(monkeypatch):
    from axiom.core.providers.manager import ProviderManager

    manager = ProviderManager()
    monkeypatch.setattr(manager, "get_provider", lambda pid: _Provider(pid, fail=pid == "a"))
    router = ModelRouter()
    router.config.primary = RouteTarget("a", "one")
    router.config.fallbacks = [RouteTarget("b", "two")]
    chunks = [chunk async for chunk in ProviderChatClient(manager, router).chat(
        "ignored", [{"role": "user", "content": "hello"}]
    )]
    assert "".join(chunk.content for chunk in chunks) == "b:two"
    assert router.should_fallback("429") is True


async def test_manager_model_rows_report_real_capabilities(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    mgr = ProviderManager()

    class _FakeProvider:
        async def list_models(self):
            return [
                ModelProfile(
                    id="glm-4.6",
                    provider_id="zai",
                    display_name="GLM 4.6",
                    coding=True,
                    reasoning=True,
                    tool_calling=True,
                    long_context=False,
                    vision=False,
                )
            ]

    monkeypatch.setattr(mgr, "get_provider", lambda pid: _FakeProvider())
    rows = await mgr.model_rows("zai")
    assert rows == [
        {
            "id": "zai/glm-4.6",
            "model": "glm-4.6",
            "provider_id": "zai",
            "label": "GLM 4.6",
            "capabilities": ["coding", "reasoning", "tool_calling"],
            "context_length": None,
        }
    ]
