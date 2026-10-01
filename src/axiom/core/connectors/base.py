"""Connector base types and secret redaction (W3.2).

A connector exposes a narrow, auditable set of *tools* over an external
service. Every tool declares the OAuth scopes it needs and whether it mutates
data (mutations require explicit approval). Tokens are first-class values that
never serialize their secret in ``repr``, ``export`` or logs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

#: Fields that must never appear in a serialized/exported token.
_SECRET_FIELDS = ("access_token", "refresh_token")


class ConnectorError(Exception):
    """A connector failure: auth, network, permission, or missing scope."""


@dataclass(frozen=True)
class ConnectorToken:
    """An OAuth token scoped to one connector.

    ``redacted()``/``export()`` intentionally omit the secrets so a token can be
    logged or shown in the UI without leaking credentials.
    """

    access_token: str
    token_type: str = "Bearer"
    refresh_token: str | None = None
    expires_at: float | None = None
    scope: tuple[str, ...] = ()

    def redacted(self) -> dict[str, Any]:
        """Safe, secret-free projection (for logs, exports and the UI)."""
        return {
            "token_type": self.token_type,
            "expires_at": self.expires_at,
            "scope": list(self.scope),
            "has_access_token": bool(self.access_token),
            "has_refresh_token": bool(self.refresh_token),
        }

    def export(self) -> dict[str, Any]:
        return self.redacted()

    def __repr__(self) -> str:
        return (
            f"ConnectorToken(token_type={self.token_type!r}, scope={list(self.scope)!r}, "
            f"has_access_token={bool(self.access_token)})"
        )


@dataclass(frozen=True)
class ConnectorTool:
    """One tool a connector exposes. ``mutation=True`` requires approval."""

    name: str
    description: str
    scopes: tuple[str, ...] = ()
    mutation: bool = False
    provider: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "scopes": list(self.scopes),
            "mutation": self.mutation,
            "provider": self.provider,
        }


class Connector(Protocol):
    """The one schema every connector implements (Google, Microsoft, ...)."""

    id: str
    display_name: str

    @property
    def scopes(self) -> tuple[str, ...]: ...

    def tools(self) -> list[ConnectorTool]: ...

    async def begin(self) -> dict[str, Any]: ...

    async def finish(self, device_code: str) -> ConnectorToken: ...

    async def revoke(self, token: ConnectorToken) -> bool: ...

    async def execute(self, token: ConnectorToken, tool: str, args: dict[str, Any]) -> Any: ...


def redact(text: str, secrets: list[str] | None = None) -> str:
    """Replace every secret occurrence in ``text`` with ``<redacted>``.

    Used before any connector value is logged, serialized to an export, or
    rendered in an error message, so a token can never leak through those paths.
    """
    if not secrets:
        return text
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "<redacted>")
    return result


@dataclass
class Redactor:
    """Accumulates secrets (per-process) and redacts arbitrary text against them."""

    secrets: list[str] = field(default_factory=list)

    def register(self, token: ConnectorToken) -> None:
        for value in (token.access_token, token.refresh_token or ""):
            if value and value not in self.secrets:
                self.secrets.append(value)

    def redact(self, text: str) -> str:
        return redact(text, self.secrets)
