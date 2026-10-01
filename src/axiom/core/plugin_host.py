"""Plugin UI host contract and least-privilege scope enforcement (W3.1).

W1.5 defined the *shape* of a plugin's ``ui`` block; W3.1 enforces it at runtime.
The desktop renders each UI extension in an isolated iframe/Worker and talks to
it over a strictly typed request/response/event protocol. This module owns the
host-side half of that protocol — the deterministic, testable parts that must
not live in a frontend:

* :data:`SCOPE_CAPABILITIES` maps each declared scope (``fs``, ``net``, ``ui``,
  ``clipboard``) to the capability names it unlocks.
* :class:`ScopeGate` decides whether a plugin's declared scopes permit a
  capability — the "denied network/file scopes are enforced" guarantee. A
  capability is *denied unless explicitly declared*; there is no default-open.
* :class:`HostRequest`/:class:`HostResponse`/:class:`HostEvent` are the typed
  envelopes. :func:`parse_request` rejects anything that is not a valid request,
  targets an unknown method, or exceeds the payload budget *before* it reaches
  any capability handler.
* :class:`PluginHost` routes a validated request to a registered handler while
  enforcing the scope gate, and returns a structured response.
* :func:`allowlisted_catalog` is the v0 catalog of plugins AXIOM ships and
  trusts; an install from the catalog checks name and pinned version here.

Nothing here imports UI code; the iframe/Worker bridge is a thin client over
this contract.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# --------------------------------------------------------------------------- #
# Scope model
# --------------------------------------------------------------------------- #

#: Which capability names each declared scope unlocks. A capability whose scope
#: is not declared is denied (least privilege — default closed).
SCOPE_CAPABILITIES: dict[str, frozenset[str]] = {
    "fs": frozenset({"fs.read", "fs.write", "fs.list"}),
    "net": frozenset({"net.http_get", "net.http_post"}),
    "ui": frozenset({"ui.render", "ui.command", "ui.event"}),
    "clipboard": frozenset({"clipboard.read", "clipboard.write"}),
}

#: All known scopes.
ALL_SCOPES: frozenset[str] = frozenset(SCOPE_CAPABILITIES)

#: All known capabilities (the host method namespace a plugin may call).
ALL_CAPABILITIES: frozenset[str] = frozenset().union(*SCOPE_CAPABILITIES.values())

#: Hard budget on the ``params`` object of a single request (serialized bytes).
MAX_PARAMS_BYTES = 32 * 1024


@dataclass(frozen=True)
class ScopeGate:
    """Decide whether a plugin's declared scopes permit a capability."""

    declared: frozenset[str] = frozenset()

    def allow(self, capability: str) -> bool:
        """Return ``True`` only if ``capability`` is known and its scope declared."""
        scope = self._scope_of(capability)
        return scope is not None and scope in self.declared

    def denied(self, capability: str) -> bool:
        return not self.allow(capability)

    @staticmethod
    def _scope_of(capability: str) -> str | None:
        for scope, caps in SCOPE_CAPABILITIES.items():
            if capability in caps:
                return scope
        return None


def normalize_scopes(values: Any) -> frozenset[str]:
    """Turn a manifest scopes list into a validated frozenset of known scopes."""
    if not isinstance(values, (list, tuple, set)):
        return frozenset()
    return frozenset(str(v) for v in values if str(v) in ALL_SCOPES)


# --------------------------------------------------------------------------- #
# Typed message protocol
# --------------------------------------------------------------------------- #


class HostRequest(BaseModel):
    """A plugin -> host request. ``method`` names exactly one capability."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    plugin: str = Field(min_length=1, max_length=64)
    method: str = Field(min_length=1, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)


class HostResponse(BaseModel):
    """The host -> plugin reply to one :class:`HostRequest`."""

    model_config = ConfigDict(extra="forbid")

    id: str
    plugin: str
    ok: bool
    data: Any = None
    error: str | None = None


class HostEvent(BaseModel):
    """A host -> plugin asynchronous event (subscription payload)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    plugin: str = Field(min_length=1, max_length=64)
    event: str = Field(min_length=1, max_length=128)
    data: Any = None


def parse_request(raw: Any) -> HostRequest | str:
    """Validate a raw request; return a :class:`HostRequest` or an error string.

    The returned string is the rejection reason and is the only path that
    reaches the caller without executing a capability handler.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, dict):
        return "request must be a JSON object"
    try:
        request = HostRequest.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", ()))
        return f"invalid request{(' at ' + loc) if loc else ''}: {first.get('msg', 'validation failed')}"
    if request.method not in ALL_CAPABILITIES:
        return f"unknown method '{request.method}'"
    try:
        import json as _json

        if len(_json.dumps(request.params, ensure_ascii=False).encode("utf-8")) > MAX_PARAMS_BYTES:
            return "params exceed the size limit"
    except (TypeError, ValueError):
        return "params are not serializable"
    return request


class PluginHost:
    """Route validated requests to capability handlers under a scope gate."""

    def __init__(self, scopes: Any, handlers: dict[str, Callable[..., Any]] | None = None) -> None:
        self._gate = ScopeGate(declared=normalize_scopes(scopes))
        self._handlers: dict[str, Callable[..., Any]] = dict(handlers or {})

    def register(self, capability: str, handler: Callable[..., Any]) -> None:
        if capability not in ALL_CAPABILITIES:
            raise ValueError(f"unknown capability '{capability}'")
        self._handlers[capability] = handler

    def handle(self, raw: Any) -> HostResponse:
        request = parse_request(raw)
        if isinstance(request, str):
            plugin = str(raw.get("plugin") or "") if isinstance(raw, dict) else ""
            rid = str(raw.get("id") or "") if isinstance(raw, dict) else ""
            return HostResponse(id=rid, plugin=plugin, ok=False, error=request)
        if self._gate.denied(request.method):
            return HostResponse(
                id=request.id, plugin=request.plugin, ok=False,
                error=f"scope not granted for '{request.method}'",
            )
        handler = self._handlers.get(request.method)
        if handler is None:
            return HostResponse(
                id=request.id, plugin=request.plugin, ok=False,
                error=f"capability '{request.method}' is not available",
            )
        try:
            data = handler(request.params)
        except Exception as exc:
            return HostResponse(
                id=request.id, plugin=request.plugin, ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        return HostResponse(id=request.id, plugin=request.plugin, ok=True, data=data)


# --------------------------------------------------------------------------- #
# Allowlisted v0 catalog
# --------------------------------------------------------------------------- #

#: The v0 catalog of plugins AXIOM ships and trusts, pinned by exact version.
#: ``scopes`` documents the least-privilege surface each plugin requests, so the
#: install flow can show it and the host can refuse an unknown/repinned plugin.
ALLOWLISTED_CATALOG: dict[str, dict[str, Any]] = {
    "calculator": {"version": "1.0.0", "scopes": []},
    "datetime": {"version": "1.0.0", "scopes": []},
    "notes": {"version": "1.0.0", "scopes": []},
    "security": {"version": "1.0.0", "scopes": []},
    "texttools": {"version": "1.0.0", "scopes": []},
    "hello-panel": {"version": "1.0.0", "scopes": ["ui"]},
}


def allowlisted_catalog() -> dict[str, dict[str, Any]]:
    """Return a copy of the v0 allowlisted catalog (name -> pinned entry)."""
    return {name: dict(entry) for name, entry in ALLOWLISTED_CATALOG.items()}


def catalog_allows(name: str, version: str) -> bool:
    """True when ``name`` is allowlisted and ``version`` matches the pin."""
    entry = ALLOWLISTED_CATALOG.get(name)
    return entry is not None and entry.get("version") == version

