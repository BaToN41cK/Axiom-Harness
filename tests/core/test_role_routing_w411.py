"""W4.11 role routing: config rules, capability picks, and the real call path.

No network and no provider SDK: the transport is a fake provider/client that
records exactly which model it was asked to call.
"""
from __future__ import annotations

from pathlib import Path

from axiom.core.agent import Agent
from axiom.core.chat import ChatSession
from axiom.core.config import Config
from axiom.core.history import HistoryStore
from axiom.core.models import ModelInfo
from axiom.core.ollama import StreamChunk
from axiom.core.providers.base import ModelProfile, StreamChunk as ProviderChunk
from axiom.core.providers.catalog import ModelCatalog
from axiom.core.router import (
    MODEL_ROLES,
    ModelRouter,
    RouterConfig,
    RouteTarget,
    order_by_budget,
)
from axiom.core.state_machine import GenerationStateMachine


def _catalog() -> ModelCatalog:
    catalog = ModelCatalog()
    catalog.add([
        ModelProfile(id="big-reasoner", provider_id="acme", reasoning=True, long_context=True),
        ModelProfile(id="tool-worker", provider_id="acme", tool_calling=True, coding=True),
        ModelProfile(id="tiny-fast", provider_id="acme"),
        ModelProfile(id="archive-reader", provider_id="acme", long_context=True),
    ])
    return catalog


def _router(**overrides) -> ModelRouter:
    config = RouterConfig(
        primary=RouteTarget("acme", "big-reasoner", "configured"), **overrides,
    )
    return ModelRouter(config)


# ------------------------------------------------------------------ router


def test_role_names_are_the_documented_five() -> None:
    assert MODEL_ROLES == ("main", "subagent", "coding", "search", "summarize")


def test_without_a_rule_a_role_resolves_to_the_existing_route() -> None:
    """DoD: adding the role layer changed nothing for an unconfigured setup."""
    router = _router()
    for role in MODEL_ROLES:
        target = router.route_for_role(role, "fix this code", _catalog())
        assert target is not None
        assert (target.provider_id, target.model) == ("acme", "big-reasoner")
        assert router.role_target(role) is None
        assert router.role_capability(role) is None


def test_pinned_rule_wins_over_the_primary_target() -> None:
    router = _router(roles={"subagent": RouteTarget("other", "cheap-model", "role configured")})
    target = router.route_for_role("subagent", "fix this code", _catalog())
    assert target is not None
    assert (target.provider_id, target.model) == ("other", "cheap-model")
    assert "role=subagent configured" in target.reason
    # Another role and the plain path keep the primary.
    assert router.route_for_role("main", "fix this code", _catalog()).model == "big-reasoner"
    assert router.route("fix this code", None).model == "big-reasoner"


def test_capability_rule_selects_from_the_catalog_by_budget() -> None:
    """The same cost-aware ordering the task router already used."""
    router = _router(role_capabilities={"subagent": "tool_calling", "budget": "x"})
    router.config.budget = "balanced"
    target = router.route_for_role("subagent", "irrelevant", _catalog())
    assert target is not None
    assert target.model == "tool-worker"
    assert "capability=tool_calling" in target.reason

    economy = _router(role_capabilities={"summarize": "long_context"})
    economy.config.budget = "economy"
    # Two long-context models exist: economy breaks the tie by id, deterministically.
    picked = [m.id for m in order_by_budget(
        [m for m in _catalog().all() if m.long_context], "economy")]
    assert economy.route_for_role("summarize", "", _catalog()).model == picked[0]


def test_auto_capability_uses_the_role_suggestion() -> None:
    router = _router(role_capabilities={
        "search": "auto", "summarize": "auto", "subagent": "auto", "coding": "auto",
    })
    assert router.role_capability("search") == "fast"
    assert router.role_capability("summarize") == "long_context"
    assert router.role_capability("subagent") == "tool_calling"
    assert router.role_capability("coding") == "coding"
    catalog = _catalog()
    # "fast" means a model that does not reason, "summarize" one with long context.
    assert router.route_for_role("search", "", catalog).model != "big-reasoner"
    assert router.route_for_role("summarize", "", catalog).model == "big-reasoner"
    assert router.route_for_role("subagent", "", catalog).model == "tool-worker"


def test_capability_rule_without_a_match_falls_back_to_the_chain() -> None:
    """An impossible capability must not invent a model: primary answers."""
    router = _router(role_capabilities={"subagent": "vision"})
    assert router.route_for_role("subagent", "", _catalog()).model == "big-reasoner"


def test_role_fallback_never_starts_catalog_picking() -> None:
    """A role without a rule resolves exactly like the pre-W4.11 role-less path."""
    router = _router(roles={"coding": RouteTarget("other", "pinned", "")})
    # route() may pick a coding model from the catalog for a coding task;
    # a role without a rule must not start doing that on its own.
    text = "исправь код и добавь тест"
    assert router.route_for_role("coding", text, _catalog()).model == "pinned"
    assert router.route_for_role("subagent", text, _catalog()).model == "big-reasoner"
    assert router.route(text, _catalog()).model == "tool-worker"


def test_unknown_role_without_a_rule_is_harmless() -> None:
    router = _router()
    assert router.route_for_role("wat", "", _catalog()).model == "big-reasoner"
    assert router.role_target("wat") is None


def test_disabled_router_short_circuits_to_primary() -> None:
    router = ModelRouter(RouterConfig(enabled=False, primary=RouteTarget("acme", "m", "")))
    assert router.route_for_role("subagent", "", _catalog()).model == "m"


def test_role_lookup_is_case_and_space_tolerant() -> None:
    router = _router(roles={"subagent": RouteTarget("other", "m", "")})
    assert router.role_target("  SubAgent ").model == "m"
    assert router.route_for_role(" SUBAGENT ", "", _catalog()).provider_id == "other"


# ------------------------------------------------------------------- config


def _session(tmp_path: Path, monkeypatch, config: Config) -> ChatSession:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    session = ChatSession(
        config=config, history_store=HistoryStore(directory=tmp_path / "h"),
    )
    session.active_model = ModelInfo(name="test-model:latest", capabilities=["tools"])
    return session


def test_config_rules_reach_the_router(tmp_path: Path, monkeypatch) -> None:
    config = Config(
        model="test-model:latest",
        router_roles={
            "subagent": {"provider_id": "acme", "model": "small-fast"},
            "summarize": {"capability": "long_context"},
        },
    )
    session = _session(tmp_path, monkeypatch, config)
    assert session.router.role_target("subagent").model == "small-fast"
    assert session.router.role_capability("summarize") == "long_context"
    assert session.router.role_target("coding") is None


def test_bad_config_rules_are_ignored_not_fatal(tmp_path: Path, monkeypatch) -> None:
    """A typo in config must never break routing for the roles that are fine."""
    config = Config(
        model="test-model:latest",
        router_roles={
            "unknown_role": {"provider_id": "acme", "model": "m"},
            "coding": {"model": "only-a-model"},          # no provider_id
            "search": {},                                  # nothing to resolve
            "main": {"provider_id": "acme", "model": "main-model"},
        },
    )
    session = _session(tmp_path, monkeypatch, config)
    assert session.router.role_target("unknown_role") is None
    assert session.router.role_target("coding") is None
    assert session.router.role_capability("coding") is None
    assert session.router.role_target("search") is None
    assert session.router.role_capability("search") is None
    assert session.router.role_target("main").model == "main-model"


def test_role_routes_report_every_role_honestly(tmp_path: Path, monkeypatch) -> None:
    config = Config(model="test-model:latest",
                    router_roles={"subagent": {"provider_id": "acme", "model": "worker"}})
    session = _session(tmp_path, monkeypatch, config)
    routes = session.role_routes()
    assert [row["role"] for row in routes] == list(MODEL_ROLES)
    by_role = {row["role"]: row for row in routes}
    assert by_role["subagent"]["configured"] is True
    assert by_role["subagent"]["model"] == "worker"
    # Nothing configured for the other roles: they resolve to the old route.
    assert by_role["main"]["configured"] is False
    assert by_role["coding"]["model"] == ""
    # An unknown role is reported as unknown instead of silently routing.
    unknown = session.route_for_role("wat")
    assert unknown["known"] is False and unknown["configured"] is False
    assert session.route_for_role("subagent")["provider_id"] == "acme"


def test_swapping_a_provider_needs_no_agent_change(tmp_path: Path, monkeypatch) -> None:
    """DoD: the same code, another config, another model on the wire."""
    config = Config(model="test-model:latest",
                    router_roles={"coding": {"provider_id": "acme", "model": "first"}})
    session = _session(tmp_path, monkeypatch, config)
    assert session._worker_model("coder", "edit the module").name == "first"
    assert session._worker_model("reviewer", "read the diff").name == "test-model:latest"

    config.router_roles = {"coding": {"provider_id": "acme", "model": "second"}}
    session._configure_router_from_config()
    assert session._worker_model("coder", "edit the module").name == "second"


def test_specialists_map_to_the_two_worker_roles() -> None:
    assert ChatSession.role_for_agent("coder") == "coding"
    assert ChatSession.role_for_agent("frontend") == "coding"
    assert ChatSession.role_for_agent("backend") == "coding"
    assert ChatSession.role_for_agent("researcher") == "subagent"
    assert ChatSession.role_for_agent("reviewer") == "subagent"


# -------------------------------------------------------------- call path


class _FakeProvider:
    """Stands in for one external provider and records the model it was told."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def stream(self, model, messages, **kwargs):  # noqa: ANN001
        self.calls.append(model)
        yield ProviderChunk(content="ok", done=True)


class _FakeManager:
    def __init__(self, provider: _FakeProvider) -> None:
        self.provider = provider

    def get_provider(self, provider_id: str) -> _FakeProvider:
        return self.provider


async def _drain(client, model: str, *, role: str | None = None) -> None:
    async for _ in client.chat(model, [{"role": "user", "content": "hi"}], tools=None, role=role):
        pass


async def test_provider_client_routes_a_role_to_its_own_provider() -> None:
    """A role rule names provider AND model, so no cross-provider mix-up."""
    from axiom.core.providers.runtime import ProviderChatClient

    provider = _FakeProvider()
    router = _router(roles={"subagent": RouteTarget("other", "worker-m", "")})
    client = ProviderChatClient(_FakeManager(provider), router,
                                default_provider="acme", default_model="big-reasoner")

    await _drain(client, "big-reasoner", role="subagent")
    assert provider.calls == ["worker-m"]
    assert client.last_route == {"provider_id": "other", "model": "worker-m",
                                 "role": "subagent"}

    await _drain(client, "big-reasoner")
    assert provider.calls == ["worker-m", "big-reasoner"]
    assert "role" not in client.last_route


async def test_provider_client_falls_back_from_a_role_target() -> None:
    """A role target that fails still uses the existing fallback chain."""
    from axiom.core.errors import OllamaUnavailableError
    from axiom.core.providers.runtime import ProviderChatClient

    class _RateLimitedProvider(_FakeProvider):
        """Only the role's own model is saturated, the chain is healthy."""

        async def stream(self, model, messages, **kwargs):  # noqa: ANN001
            self.calls.append(model)
            if model == "worker-m":
                raise OllamaUnavailableError("429 rate limit")
            yield ProviderChunk(content="ok", done=True)

    provider = _RateLimitedProvider()
    router = _router(
        roles={"subagent": RouteTarget("other", "worker-m", "")},
        fallbacks=[RouteTarget("acme", "backup-m", "fallback")],
    )
    client = ProviderChatClient(_FakeManager(provider), router,
                                default_provider="acme", default_model="big-reasoner")
    await _drain(client, "big-reasoner", role="subagent")
    assert provider.calls[0] == "worker-m"          # the role was tried first
    assert client.last_route["model"] == "backup-m"  # and the old chain took over
    assert client.last_route["role"] == "subagent"


class _RecordingClient:
    """Minimal Ollama-shaped client that records the keyword arguments."""

    accepts_role = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat(self, model, messages, **kwargs):  # noqa: ANN001
        self.calls.append({"model": model, **kwargs})
        yield StreamChunk(content="ok")
        yield StreamChunk(done=True)


class _PlainClient(_RecordingClient):
    """A client that does not know roles must keep the exact old call shape."""

    accepts_role = False


async def _run_agent(agent: Agent, text: str = "hello") -> None:
    async for _ in agent.run([{"role": "user", "content": text}], ModelInfo(name="m")):
        pass


async def test_agent_passes_its_role_to_a_client_that_resolves_roles() -> None:
    client = _RecordingClient()
    agent = Agent(client, config=Config(model="m", web_search_enabled=False),
                  registry=None, machine=GenerationStateMachine())  # type: ignore[arg-type]
    assert agent.route_role is None
    await _run_agent(agent)
    assert "role" not in client.calls[-1]

    agent.route_role = "subagent"
    await _run_agent(agent)
    assert client.calls[-1]["role"] == "subagent"
    assert agent.last_route == {}  # no router attached: nothing is claimed


async def test_agent_never_invents_a_role_kwarg_for_a_plain_client() -> None:
    client = _PlainClient()
    agent = Agent(client, config=Config(model="m", web_search_enabled=False),
                  registry=None, machine=GenerationStateMachine())  # type: ignore[arg-type]
    agent.route_role = "coding"
    await _run_agent(agent)
    assert "role" not in client.calls[-1]


async def test_agent_route_info_records_the_role(tmp_path: Path, monkeypatch) -> None:
    """The trajectory must name the model the role actually chose, not guess."""
    from axiom.core.trajectory import Trajectory

    client = _RecordingClient()
    agent = Agent(client, config=Config(model="m", web_search_enabled=False),
                  registry=None, machine=GenerationStateMachine(),
                  trajectory=Trajectory(actor="test"))  # type: ignore[arg-type]
    agent.attach_harness(router=_router(
        roles={"subagent": RouteTarget("other", "worker-m", "")}), catalog=_catalog())
    agent.route_role = "subagent"
    await _run_agent(agent)
    assert agent.last_route == {"provider_id": "other", "model": "worker-m",
                                "reason": "role=subagent configured", "role": "subagent"}
    routed = [event for event in agent._trajectory.events if event.kind == "router.route"]
    assert routed and routed[-1].data["role"] == "subagent"


async def test_search_pass_is_routed_as_the_search_role() -> None:
    """A pass that answers from live search results is the cheap-model role."""
    from axiom.core.agent import WEB_SEARCH_TOOL
    from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult
    from axiom.core.tools.registry import ToolRegistry

    async def _search(query: str = "") -> ToolResult:
        return ToolResult(name=WEB_SEARCH_TOOL, ok=True, content=f"live sources for {query}")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name=WEB_SEARCH_TOOL, description="search", parameters={},
                       permission=ToolPermission.ALWAYS),
        _search,
    )

    class _NoSourcesTool:
        """Search returned nothing readable: only the block content matters here."""

        last_sources: list = []

    client = _RecordingClient()
    agent = Agent(client, config=Config(model="m", web_search_enabled=True),
                  registry=registry, machine=GenerationStateMachine(),
                  web_tool=_NoSourcesTool())
    agent.attach_harness(router=_router(
        roles={"search": RouteTarget("acme", "tiny-fast", "")}), catalog=_catalog())
    async for _ in agent.run([{"role": "user", "content": "who won today?"}],
                             ModelInfo(name="m"), force_search=True):
        pass
    assert client.calls[-1]["role"] == "search"
    assert agent.last_route["model"] == "tiny-fast"


async def test_a_search_pass_stops_being_search_when_it_answers_again() -> None:
    """The role is per pass: the next plain request must not inherit it."""
    client = _RecordingClient()
    agent = Agent(client, config=Config(model="m", web_search_enabled=False),
                  registry=None, machine=GenerationStateMachine())  # type: ignore[arg-type]
    agent.route_role = "subagent"
    agent._pass_role = "search"  # left over from a previous search pass
    await _run_agent(agent)
    assert client.calls[-1]["role"] == "subagent"
