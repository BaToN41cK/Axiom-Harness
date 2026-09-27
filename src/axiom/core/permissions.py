"""Permission Manager — centralised permission decision engine.

Supports three modes:
- ask: Every tool execution requires user confirmation.
- auto_approve_safe: Safe (ALWAYS) tools run automatically, ASK tools require confirmation.
- auto_approve_all: All tools execute without confirmation.

The setting persists between launches via the config file.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from axiom.core.config import Config
from axiom.core.logging import get_logger
from axiom.core.tools.base import ToolPermission

_LOG = get_logger("permissions")


class PermissionMode(str, Enum):
    """Global permission mode."""
    ASK = "ask"
    AUTO_APPROVE_SAFE = "auto_approve_safe"
    AUTO_APPROVE_ALL = "auto_approve_all"


class PermissionOutcome(str, Enum):
    """Answer of an interactive permission request (W2.4).

    ``ALLOW_ONCE`` approves a single call, ``ALLOW_ALWAYS`` remembers the tool
    for the rest of the session, ``DENY`` refuses the call.
    """

    ALLOW_ONCE = "allow_once"
    ALLOW_ALWAYS = "allow_always"
    DENY = "deny"


_PERMISSION_ALIASES: dict[str, PermissionOutcome] = {
    PermissionOutcome.ALLOW_ONCE.value: PermissionOutcome.ALLOW_ONCE,
    "once": PermissionOutcome.ALLOW_ONCE,
    "allow": PermissionOutcome.ALLOW_ONCE,
    PermissionOutcome.ALLOW_ALWAYS.value: PermissionOutcome.ALLOW_ALWAYS,
    "always": PermissionOutcome.ALLOW_ALWAYS,
    PermissionOutcome.DENY.value: PermissionOutcome.DENY,
    "no": PermissionOutcome.DENY,
    "never": PermissionOutcome.DENY,
}


def normalize_permission_outcome(value: bool | str | PermissionOutcome) -> PermissionOutcome:
    """Normalize an answer from any frontend; unknown values fail closed."""
    if isinstance(value, PermissionOutcome):
        return value
    if isinstance(value, bool):
        # Legacy callback contract: ``True`` meant "allow and remember".
        return PermissionOutcome.ALLOW_ALWAYS if value else PermissionOutcome.DENY
    return _PERMISSION_ALIASES.get(str(value).strip().lower(), PermissionOutcome.DENY)


class PermissionManager:
    """Centralised permission decision engine.

    A frontend connects a callback (``request_callback``) that shows the user a
    modal dialog when ``ASK`` tools need approval. The callback is an async
    callable that receives ``(tool_name, tool_args)`` and returns either a
    :class:`PermissionOutcome` (or its string value) or a legacy boolean
    (``True`` = allow and remember the tool, ``False`` = deny).

    Decisions are honest: ``ALLOW_ALWAYS`` is cached per tool name for the rest
    of the session, while ``ALLOW_ONCE`` and ``DENY`` are asked again next time.
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        request_callback: Callable[
            [str, dict[str, Any]], bool | str | PermissionOutcome | Awaitable[bool | str | PermissionOutcome]
        ] | None = None,
    ) -> None:
        self._config = config or Config.load()
        self._request_callback = request_callback
        #: "Always for this tool" cache (W2.4) — never caches a single call.
        self._always_allowed: set[str] = set()

    # ------------------------------------------------------------------ properties

    @property
    def mode(self) -> PermissionMode:
        raw = getattr(self._config, "permission_mode", PermissionMode.AUTO_APPROVE_SAFE.value)
        try:
            return PermissionMode(raw)
        except ValueError:
            return PermissionMode.AUTO_APPROVE_SAFE

    @mode.setter
    def mode(self, value: PermissionMode) -> None:
        self._config.permission_mode = value.value  # type: ignore[attr-defined]
        self._config.save()

    @property
    def modes_text(self) -> dict[PermissionMode, str]:
        return {
            PermissionMode.ASK: "Ask every time",
            PermissionMode.AUTO_APPROVE_SAFE: "Auto-approve safe actions",
            PermissionMode.AUTO_APPROVE_ALL: "Auto-approve everything",
        }

    # ------------------------------------------------------------------ decision

    def request_callback(
        self,
        callback: Callable[
            [str, dict[str, Any]], bool | str | PermissionOutcome | Awaitable[bool | str | PermissionOutcome]
        ],
    ) -> None:
        """Connect a UI callback for user approval dialogs."""
        self._request_callback = callback

    async def decide(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None,
        tool_permission: ToolPermission,
    ) -> bool:
        """Check whether a tool execution is allowed.

        Returns:
            True if execution may proceed, False otherwise.
        """
        _LOG.debug("Permission check: %s (perm=%s, mode=%s)", tool_name, tool_permission.value, self.mode.value)

        # NEVER permission is always blocked regardless of mode.
        if tool_permission == ToolPermission.NEVER:
            return False

        if self.mode == PermissionMode.AUTO_APPROVE_ALL:
            return True

        if self.mode == PermissionMode.AUTO_APPROVE_SAFE:
            if tool_permission == ToolPermission.ALWAYS:
                return True
            # ASK tools need user approval.
            return await self._ask_user(tool_name, tool_args or {})

        # ASK mode — everything needs approval.
        return await self._ask_user(tool_name, tool_args or {})

    async def _ask_user(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        """Show a permission request to the user, or reuse an "always" answer."""
        if tool_name in self._always_allowed:
            _LOG.debug("Permission reused ('always'): %s", tool_name)
            return True

        if self._request_callback is not None:
            answer = self._request_callback(tool_name, tool_args)
            if hasattr(answer, "__await__"):
                answer = await answer
            outcome = normalize_permission_outcome(answer)
            if outcome == PermissionOutcome.ALLOW_ALWAYS:
                self._always_allowed.add(tool_name)
                _LOG.info("Permission granted (always): %s %s", tool_name, tool_args)
                return True
            if outcome == PermissionOutcome.ALLOW_ONCE:
                _LOG.info("Permission granted (once): %s %s", tool_name, tool_args)
                return True
            _LOG.info("Permission denied: %s %s", tool_name, tool_args)
            return False

        # No callback available — deny by default (safe fallback).
        _LOG.warning("No permission callback registered; denying tool: %s", tool_name)
        return False

    def clear_cache(self) -> None:
        """Forget every "always" approval granted in this session."""
        self._always_allowed.clear()
