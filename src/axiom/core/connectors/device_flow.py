"""OAuth 2.0 Device Flow (RFC 8628) client (W3.2).

A thin, transport-injectable client so tests never need a live Google endpoint.
Production uses ``httpx``; the ``transport`` argument lets tests substitute a
fake and exercise the full polling/revocation state machine deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from axiom.core.connectors.base import ConnectorError


@dataclass(frozen=True)
class DeviceFlowConfig:
    """Endpoints + client id for one provider's device flow."""

    device_endpoint: str
    token_endpoint: str
    revocation_endpoint: str
    client_id: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class DeviceAuthorization:
    """The values a user must visit/enter to authorize the device."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    interval: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "device_code": self.device_code,
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "verification_uri_complete": self.verification_uri_complete,
            "expires_in": self.expires_in,
            "interval": self.interval,
        }


class DeviceFlowClient:
    """Drive a single device-flow authorization to completion."""

    def __init__(self, config: DeviceFlowConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self._client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(60.0, connect=15.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def begin(self) -> DeviceAuthorization:
        response = await self._client.post(
            self.config.device_endpoint,
            data={"client_id": self.config.client_id, "scope": " ".join(self.config.scopes)},
        )
        if response.status_code != 200:
            raise ConnectorError(f"device flow begin failed: HTTP {response.status_code}")
        payload = response.json()
        required = ("device_code", "user_code", "verification_uri", "expires_in", "interval")
        if any(key not in payload for key in required):
            raise ConnectorError("device flow response is missing required fields")
        return DeviceAuthorization(
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            verification_uri=str(payload["verification_uri"]),
            verification_uri_complete=payload.get("verification_uri_complete"),
            expires_in=int(payload["expires_in"]),
            interval=int(payload["interval"]),
        )

    async def poll(self, device_code: str) -> dict[str, Any]:
        """Poll once; return a token dict on success, else raise ConnectorError."""
        response = await self._client.post(
            self.config.token_endpoint,
            data={
                "client_id": self.config.client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        if response.status_code == 200:
            return response.json()
        error = ""
        try:
            error = str(response.json().get("error") or "")
        except ValueError:
            error = ""
        raise ConnectorError(error or f"token poll failed: HTTP {response.status_code}")

    async def revoke(self, token: str) -> bool:
        """Revoke an access/refresh token (RFC 7009). True on success."""
        response = await self._client.post(
            self.config.revocation_endpoint,
            data={"token": token},
        )
        return response.status_code in (200, 204)


def token_from_payload(payload: dict[str, Any], scope: tuple[str, ...]) -> dict[str, Any]:
    """Normalize an OAuth token payload into the fields :class:`ConnectorToken` wants."""
    import time

    from axiom.core.connectors.base import ConnectorToken

    expires_in = payload.get("expires_in")
    return ConnectorToken(
        access_token=str(payload.get("access_token") or ""),
        token_type=str(payload.get("token_type") or "Bearer"),
        refresh_token=payload.get("refresh_token"),
        expires_at=(time.time() + int(expires_in)) if expires_in else None,
        scope=tuple(str(s) for s in (payload.get("scope") or "").split() if s) or scope,
    )
