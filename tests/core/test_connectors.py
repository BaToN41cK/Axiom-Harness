"""W3.2 Connectors: device flow, credential store, registry, Google connector."""
from __future__ import annotations

import time

import httpx
import pytest

from axiom.core.connectors.base import ConnectorError, ConnectorToken, redact
from axiom.core.connectors.credential_store import CredentialStore
from axiom.core.connectors.device_flow import DeviceFlowClient, DeviceFlowConfig
from axiom.core.connectors.google import (
    SCOPE_CALENDAR_READ,
    SCOPE_DRIVE_FILE,
    SCOPE_DRIVE_READ,
    GoogleConnector,
)
from axiom.core.connectors.registry import ConnectorRegistry

SECRET = "ya29.SECRET_ACCESS_TOKEN_VALUE"


class FakeTransport(httpx.AsyncBaseTransport):
    """Routes requests to an async handler; records every request for assertions."""

    def __init__(self, handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return await self.handler(request)


def _resp(status: int, payload) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "https://example.com"))


def _flow(handler) -> DeviceFlowClient:
    return DeviceFlowClient(
        DeviceFlowConfig(
            device_endpoint="https://example.com/device",
            token_endpoint="https://example.com/token",
            revocation_endpoint="https://example.com/revoke",
            client_id="client-id",
            scopes=("scope.a",),
        ),
        transport=FakeTransport(handler),
    )


# ------------------------------------------------------------- device flow


async def test_device_flow_begin_parses_authorization() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _resp(200, {
            "device_code": "dev-1", "user_code": "CODE-123", "verification_uri": "https://example.com/device",
            "expires_in": 1800, "interval": 5,
        })

    client = _flow(handler)
    authorization = await client.begin()
    assert authorization.device_code == "dev-1"
    assert authorization.user_code == "CODE-123"
    assert authorization.verification_uri == "https://example.com/device"
    await client.close()


async def test_device_flow_begin_rejects_missing_fields() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _resp(200, {"device_code": "dev-1"})

    client = _flow(handler)
    with pytest.raises(ConnectorError, match="missing required fields"):
        await client.begin()
    await client.close()


async def test_device_flow_poll_returns_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _resp(200, {"access_token": SECRET, "token_type": "Bearer", "expires_in": 3600,
                           "refresh_token": "refresh-1", "scope": "scope.a"})

    client = _flow(handler)
    payload = await client.poll("dev-1")
    assert payload["access_token"] == SECRET
    await client.close()


async def test_device_flow_poll_raises_on_pending() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _resp(400, {"error": "authorization_pending"})

    client = _flow(handler)
    with pytest.raises(ConnectorError, match="authorization_pending"):
        await client.poll("dev-1")
    await client.close()


async def test_device_flow_revoke() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request)

    client = _flow(handler)
    assert await client.revoke(SECRET) is True
    await client.close()


# --------------------------------------------------------- credential store


def _token() -> ConnectorToken:
    return ConnectorToken(access_token=SECRET, refresh_token="refresh-1", expires_at=time.time() + 3600,
                          scope=("scope.a",))


def test_credential_store_round_trip_and_remove(tmp_path) -> None:
    store = CredentialStore(path=tmp_path / "connectors.json")
    store.save("google", _token())
    assert store.list() == ["google"]
    loaded = store.load("google")
    assert loaded is not None
    assert loaded.access_token == SECRET
    assert store.remove("google") is True
    assert store.remove("google") is False
    assert store.load("google") is None


def test_token_repr_and_export_never_contain_the_secret() -> None:
    token = _token()
    text = repr(token) + " " + str(token.export()) + " " + str(token.redacted())
    assert SECRET not in text
    assert "refresh-1" not in text


def test_redact_masks_secrets() -> None:
    assert redact(f"token={SECRET} done", [SECRET]) == "token=<redacted> done"


def test_credential_store_is_expired() -> None:
    store = CredentialStore(path=None)
    assert store.is_expired(ConnectorToken(access_token="x", expires_at=time.time() - 10)) is True
    assert store.is_expired(ConnectorToken(access_token="x", expires_at=time.time() + 10)) is False


# ----------------------------------------------------------------- registry


async def _google_handler(request: httpx.Request) -> httpx.Response:
    if "device" in str(request.url):
        return _resp(200, {"device_code": "dev-1", "user_code": "CODE-123",
                           "verification_uri": "https://example.com/device",
                           "expires_in": 1800, "interval": 5})
    if "token" in str(request.url):
        return _resp(200, {"access_token": SECRET, "token_type": "Bearer", "expires_in": 3600,
                           "refresh_token": "refresh-1", "scope": " ".join([
                               SCOPE_CALENDAR_READ, SCOPE_DRIVE_READ, SCOPE_DRIVE_FILE])})
    if "revoke" in str(request.url):
        return httpx.Response(200, request=request)
    if "calendar" in str(request.url):
        return _resp(200, {"items": [{"summary": "Planning meeting",
                                      "start": {"dateTime": "2026-10-02T10:00:00Z"}}]})
    return _resp(200, {})


async def _signed_in_registry(tmp_path) -> ConnectorRegistry:
    registry = ConnectorRegistry(store=CredentialStore(path=tmp_path / "connectors.json"))
    registry.register(GoogleConnector(client_id="client-id", transport=FakeTransport(_google_handler)))
    pending = await registry.begin("google")
    token = await registry.finish("google")
    assert token.access_token == SECRET
    assert pending.user_code == "CODE-123"
    return registry


async def test_registry_sign_in_and_disconnect(tmp_path) -> None:
    registry = await _signed_in_registry(tmp_path)
    assert registry.signed_in("google") is True
    assert registry.signed_in_ids() == ["google"]
    assert registry.redact(f"leaked {SECRET}") == "leaked <redacted>"

    assert await registry.disconnect("google") is True
    assert registry.signed_in("google") is False


async def test_registry_execute_returns_real_google_data(tmp_path) -> None:
    registry = await _signed_in_registry(tmp_path)
    events = await registry.execute("google", "calendar.events", {"max": 5})
    assert events["items"][0]["summary"] == "Planning meeting"


async def test_registry_scope_enforcement_and_mutation_approval(tmp_path) -> None:
    registry = await _signed_in_registry(tmp_path)
    # gmail scope was not granted → the tool is refused.
    with pytest.raises(ConnectorError, match="requires scopes"):
        await registry.execute("google", "gmail.messages", {})
    # drive.upload mutates → refused without explicit approval.
    with pytest.raises(ConnectorError, match="requires approval"):
        await registry.execute("google", "drive.upload", {"name": "x.txt", "content": "hi"})
    # Approved mutation is allowed (fake transport returns {}).
    result = await registry.execute("google", "drive.upload", {"name": "x.txt", "content": "hi"},
                                    approve_mutation=True)
    assert result == {}


async def test_registry_unknown_connector_and_tool(tmp_path) -> None:
    registry = await _signed_in_registry(tmp_path)
    with pytest.raises(ConnectorError, match="unknown connector"):
        await registry.execute("microsoft", "calendar.events", {})
    with pytest.raises(ConnectorError, match="unknown tool"):
        await registry.execute("google", "no.such.tool", {})


# --------------------------------------------------------- google connector


def test_google_tools_declare_scopes_and_mutations() -> None:
    connector = GoogleConnector(client_id="client-id")
    tools = {t.name: t for t in connector.tools()}
    assert set(tools) == {"search", "calendar.events", "gmail.messages", "drive.files", "drive.upload"}
    assert tools["search"].scopes == ()  # keyed, not OAuth
    assert tools["calendar.events"].mutation is False
    assert tools["drive.upload"].mutation is True
    assert tools["calendar.events"].scopes == (SCOPE_CALENDAR_READ,)
    assert tools["drive.upload"].scopes == (SCOPE_DRIVE_FILE,)


async def test_google_search_returns_real_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _resp(200, {"items": [{"title": "AXIOM", "link": "https://example.com"}]})

    connector = GoogleConnector(client_id="client-id", api_key="key-1", search_engine_id="cx-1",
                                transport=FakeTransport(handler))
    token = ConnectorToken(access_token=SECRET)
    result = await connector.execute(token, "search", {"query": "axiom"})
    assert result["items"][0]["title"] == "AXIOM"


async def test_google_search_requires_configuration() -> None:
    connector = GoogleConnector(client_id="client-id")
    token = ConnectorToken(access_token=SECRET)
    with pytest.raises(ConnectorError, match="not configured"):
        await connector.execute(token, "search", {"query": "axiom"})
