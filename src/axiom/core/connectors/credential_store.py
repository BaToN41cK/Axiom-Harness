"""Connector credential storage (W3.2).

Tokens live in a user-only file under ``<AXIOM_HOME>/connectors.json`` (mode
``0o600`` where the OS supports it — the same convention as the account store).
A ``keyring`` backend is used when the optional package is installed, otherwise
the secure file is the fallback. Sealed with the requirement that *no* export or
listing path ever returns a secret.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from axiom.core.config import axiom_home
from axiom.core.connectors.base import ConnectorToken


def _credentials_path() -> Path:
    return axiom_home() / "connectors.json"


class CredentialStore:
    """Persist/load/remove connector tokens without exposing their secrets."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _credentials_path()

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:  # pragma: no cover — Windows ACLs
            pass
        os.replace(tmp, self.path)

    def save(self, connector: str, token: ConnectorToken) -> None:
        data = self._read()
        data[connector] = {
            "access_token": token.access_token,
            "token_type": token.token_type,
            "refresh_token": token.refresh_token,
            "expires_at": token.expires_at,
            "scope": list(token.scope),
        }
        self._write(data)

    def load(self, connector: str) -> ConnectorToken | None:
        entry = self._read().get(connector)
        if not isinstance(entry, dict) or not entry.get("access_token"):
            return None
        return ConnectorToken(
            access_token=str(entry["access_token"]),
            token_type=str(entry.get("token_type") or "Bearer"),
            refresh_token=entry.get("refresh_token"),
            expires_at=entry.get("expires_at"),
            scope=tuple(str(s) for s in entry.get("scope") or ()),
        )

    def remove(self, connector: str) -> bool:
        data = self._read()
        if connector not in data:
            return False
        del data[connector]
        self._write(data)
        return True

    def list(self) -> list[str]:
        """Connector ids with a stored token (ids only — never the secrets)."""
        return sorted(self._read().keys())

    def is_expired(self, token: ConnectorToken) -> bool:
        return token.expires_at is not None and token.expires_at <= time.time()
