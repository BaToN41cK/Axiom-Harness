"""Connector registry (W3.2): one schema, per-connector scope, mutation approval."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axiom.core.connectors.base import Connector, ConnectorError, ConnectorToken, Redactor
from axiom.core.connectors.credential_store import CredentialStore


@dataclass
class PendingAuth:
    """An in-progress device-flow authorization, waiting for the user."""

    connector: str
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None


@dataclass
class ConnectorRegistry:
    """Holds connectors and their tokens; enforces least privilege at call time."""

    store: CredentialStore = field(default_factory=CredentialStore)
    redactor: Redactor = field(default_factory=Redactor)

    def __post_init__(self) -> None:
        self._connectors: dict[str, Connector] = {}
        self._pending: dict[str, PendingAuth] = {}

    # ------------------------------------------------------------- registration

    def register(self, connector: Connector) -> None:
        self._connectors[connector.id] = connector

    def get(self, connector_id: str) -> Connector | None:
        return self._connectors.get(connector_id)

    def list(self) -> list[Connector]:
        return list(self._connectors.values())

    # --------------------------------------------------------------------- auth

    async def begin(self, connector_id: str) -> PendingAuth:
        connector = self._require(connector_id)
        authorization = await connector.begin()
        pending = PendingAuth(
            connector=connector_id,
            device_code=str(authorization["device_code"]),
            user_code=str(authorization["user_code"]),
            verification_uri=str(authorization["verification_uri"]),
            verification_uri_complete=authorization.get("verification_uri_complete"),
        )
        self._pending[connector_id] = pending
        return pending

    async def finish(self, connector_id: str) -> ConnectorToken:
        connector = self._require(connector_id)
        pending = self._pending.get(connector_id)
        if pending is None:
            raise ConnectorError(f"no authorization in progress for '{connector_id}'")
        token = await connector.finish(pending.device_code)
        self.store.save(connector_id, token)
        self.redactor.register(token)
        self._pending.pop(connector_id, None)
        return token

    async def disconnect(self, connector_id: str) -> bool:
        """Revoke the stored token remotely and remove it locally."""
        token = self.store.load(connector_id)
        if token is None:
            return False
        connector = self._connectors.get(connector_id)
        revoked = False
        if connector is not None:
            try:
                revoked = await connector.revoke(token)
            except ConnectorError:
                revoked = False
        self.store.remove(connector_id)
        return revoked

    def token(self, connector_id: str) -> ConnectorToken | None:
        return self.store.load(connector_id)

    def signed_in(self, connector_id: str) -> bool:
        return self.store.load(connector_id) is not None

    def signed_in_ids(self) -> list[str]:
        return self.store.list()

    # ---------------------------------------------------------------- execution

    async def execute(
        self,
        connector_id: str,
        tool_name: str,
        args: dict[str, Any],
        *,
        approve_mutation: bool = False,
    ) -> Any:
        """Run one connector tool after scope + mutation checks."""
        connector = self._require(connector_id)
        token = self.store.load(connector_id)
        if token is None:
            raise ConnectorError(f"'{connector_id}' is not connected — sign in first")
        if self.store.is_expired(token):
            raise ConnectorError(f"'{connector_id}' token expired — reconnect")

        tool = next((t for t in connector.tools() if t.name == tool_name), None)
        if tool is None:
            raise ConnectorError(f"unknown tool '{tool_name}' for '{connector_id}'")
        missing = [scope for scope in tool.scopes if scope not in token.scope]
        if missing:
            raise ConnectorError(
                f"tool '{tool_name}' requires scopes {missing} not granted to '{connector_id}'"
            )
        if tool.mutation and not approve_mutation:
            raise ConnectorError(f"tool '{tool_name}' mutates data and requires approval")

        return await connector.execute(token, tool_name, args)

    # ----------------------------------------------------------------- internals

    def _require(self, connector_id: str) -> Connector:
        connector = self._connectors.get(connector_id)
        if connector is None:
            raise ConnectorError(f"unknown connector '{connector_id}'")
        return connector

    def redact(self, text: str) -> str:
        return self.redactor.redact(text)
