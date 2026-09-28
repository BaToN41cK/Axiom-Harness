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

from axiom.core.autonomy import apply_autonomy, resolve_autonomy
from axiom.core.command_policy import classify_command_risk
from axiom.core.config import Config
from axiom.core.logging import get_logger
from axiom.core.tools.base import ToolPermission

_LOG = get_logger("permissions")

#: Tools that stay usable in W4.9 PLAN autonomy (read_only access): pure reads
#: plus read-only git inspection. Everything else is blocked before any mode or
#: cache is consulted.
_PLAN_READ_TOOLS = frozenset({
    "list_files", "read_file", "search_text", "search_files",
    "inspect_project", "git_status", "git_diff", "git_log", "git_branch",
    "web_search", "fetch_url", "knowledge_search", "knowledge_index",
    "knowledge_status", "memory_read",
})


class PermissionMode(str, Enum):
    """Global permission mode."""
    ASK = "ask"
    AUTO_APPROVE_SAFE = "auto_approve_safe"
    AUTO_APPROVE_ALL = "auto_approve_all"


class PermissionOutcome(str, Enum):
    """Answer of an interactive permission request (W2.4, extended W4.9).

    ``ALLOW_ONCE`` approves a single call, ``ALLOW_ALWAYS`` remembers the tool
    for the rest of the session, ``DENY`` refuses the call. W4.9 adds the two
    scoped approvals ``ALLOW_TASK`` (current task only) and ``ALLOW_PROJECT``
    (current workspace only) — both behave like ``ALLOW_ALWAYS`` for the
    current call and additionally populate a scoped cache.
    """

    ALLOW_ONCE = "allow_once"
    ALLOW_TASK = "allow_task"
    ALLOW_PROJECT = "allow_project"
    ALLOW_ALWAYS = "allow_always"
    DENY = "deny"


_PERMISSION_ALIASES: dict[str, PermissionOutcome] = {
    PermissionOutcome.ALLOW_ONCE.value: PermissionOutcome.ALLOW_ONCE,
    "once": PermissionOutcome.ALLOW_ONCE,
    "allow": PermissionOutcome.ALLOW_ONCE,
    PermissionOutcome.ALLOW_TASK.value: PermissionOutcome.ALLOW_TASK,
    "task": PermissionOutcome.ALLOW_TASK,
    PermissionOutcome.ALLOW_PROJECT.value: PermissionOutcome.ALLOW_PROJECT,
    "project": PermissionOutcome.ALLOW_PROJECT,
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
        #: W4.9 narrows it to (tool, risk-tier) pairs: a SAFE approval never
        #: satisfies a HIGH/CRITICAL call (non-inheritance).
        self._always_allowed: set[tuple[str, str]] = set()
        #: W4.9 scoped caches: (tool, risk-tier, scope id) for one task/project.
        self._task_allowed: set[tuple[str, str, str]] = set()
        self._project_allowed: set[tuple[str, str, str]] = set()
        #: W4.9 context bound by :meth:`bind_context` (active task + project).
        self._active_task_id: str | None = None
        self._active_project: str | None = None

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

    @property
    def autonomy(self) -> str:
        """W4.9 autonomy preset composed from the two persisted axes."""
        return resolve_autonomy(
            str(getattr(self._config, "access_mode", "workspace")),
            self.mode.value,
        )

    def set_autonomy(self, mode: str) -> str:
        """Apply a W4.9 autonomy preset onto both axes; returns the preset."""
        axes = apply_autonomy(mode)
        self._config.access_mode = axes["access_mode"]  # type: ignore[attr-defined]
        self.mode = PermissionMode(axes["permission_mode"])
        try:
            self._config.autonomy_mode = self.autonomy  # type: ignore[attr-defined]
            self._config.save()
        except Exception:
            pass
        return self.autonomy

    def describe_request(
        self, tool_name: str, tool_args: dict[str, Any] | None, *, cwd: str | None = None
    ) -> dict[str, Any]:
        """UI projection of a pending ASK call: command, cwd, risk, reason (W4.9)."""
        args = dict(tool_args or {})
        tier = self._risk_tier(tool_name, args)
        reason = ""
        command = ""
        if tool_name == "run_command":
            command = str(args.get("command", ""))
            _tier, reason = classify_command_risk(command)
        elif tool_name in {"delete_file", "git_push", "git_commit", "git_add"}:
            reason = "mutates or publishes repository state; approved per call"
        elif tier == "SAFE":
            reason = "read-only or workspace-scoped call within current policy"
        return {
            "tool": tool_name,
            "arguments": args,
            "command": command or str(args.get("path", args.get("query", args.get("url", "")))),
            "cwd": str(cwd or getattr(self._config, "workspace_root", None) or "."),
            "risk": tier,
            "reason": reason,
            "autonomy": self.autonomy,
        }

    # ------------------------------------------------------------------ context

    def bind_context(self, *, task_id: str | None = None, project: str | None = None) -> None:
        """Bind the active task/project scope for W4.9 scoped approvals (chainable)."""
        self._active_task_id = str(task_id) if task_id else None
        self._active_project = str(project) if project else None

    @property
    def active_task_id(self) -> str | None:
        """Task id used to scope ``allow_task`` approvals (None = chat scope)."""
        return self._active_task_id

    @property
    def active_project(self) -> str | None:
        """Workspace key used to scope ``allow_project`` approvals."""
        return self._active_project

    @staticmethod
    def _risk_tier(tool_name: str, tool_args: dict[str, Any] | None) -> str:
        """Visible risk tier for cache separation (W4.9).

        ``run_command`` reuses the SAFE..CRITICAL command policy; every other
        tool maps to SAFE except known destructive tools (HIGH). The tier is
        part of every cache key so a SAFE approval can never satisfy a
        HIGH/CRITICAL call.
        """
        if tool_name == "run_command":
            tier, _reason = classify_command_risk(str((tool_args or {}).get("command", "")))
            return tier
        if tool_name in {"delete_file", "git_push", "git_commit", "git_add"}:
            return "HIGH"
        return "SAFE"

    def _cache_key(self, tool_name: str, tool_args: dict[str, Any] | None) -> tuple[str, str]:
        return (tool_name, self._risk_tier(tool_name, tool_args))

    def _has_cached_approval(self, tool_name: str, tool_args: dict[str, Any] | None) -> bool:
        key = self._cache_key(tool_name, tool_args)
        if key in self._always_allowed:
            return True
        if self._active_task_id is not None and (*key, self._active_task_id) in self._task_allowed:
            return True
        return self._active_project is not None and (*key, self._active_project) in self._project_allowed

    def _remember(self, outcome: PermissionOutcome, tool_name: str, tool_args: dict[str, Any]) -> None:
        key = self._cache_key(tool_name, tool_args)
        if outcome == PermissionOutcome.ALLOW_ALWAYS:
            self._always_allowed.add(key)
        elif outcome == PermissionOutcome.ALLOW_TASK and self._active_task_id is not None:
            self._task_allowed.add((*key, self._active_task_id))
        elif outcome == PermissionOutcome.ALLOW_PROJECT and self._active_project is not None:
            self._project_allowed.add((*key, self._active_project))

    def drop_task_scope(self, task_id: str | None = None) -> None:
        """Forget ``allow_task`` approvals for one task (W4.9; None = active)."""
        target = str(task_id) if task_id else self._active_task_id
        if target is None:
            return
        self._task_allowed = {entry for entry in self._task_allowed if entry[2] != target}
        if target == self._active_task_id:
            self._active_task_id = None

    def drop_project_scope(self, project: str | None = None) -> None:
        """Forget ``allow_project`` approvals for one workspace (W4.9)."""
        target = str(project) if project else self._active_project
        if target is None:
            return
        self._project_allowed = {entry for entry in self._project_allowed if entry[2] != target}

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
        args = dict(tool_args or {})
        tier = self._risk_tier(tool_name, args)
        _LOG.debug(
            "Permission check: %s (perm=%s, mode=%s, risk=%s)",
            tool_name, tool_permission.value, self.mode.value, tier,
        )

        # NEVER permission is always blocked regardless of mode.
        if tool_permission == ToolPermission.NEVER:
            return False
        # W4.9 PLAN autonomy: read_only access blocks every write/process tool
        # even when the static permission says ALWAYS. Read tools stay usable.
        if getattr(self._config, "access_mode", "workspace") == "read_only" and tool_name not in _PLAN_READ_TOOLS:
            return False
        # Git staging/commit change the repo. Auto modes and cached approvals
        # must never stand in for explicit consent to the current change.
        if tool_name in {"git_add", "git_commit"}:
            dialog_args = dict(args)
            if tool_name == "git_commit":
                git_tools = getattr(self, "git_tools", None)
                if git_tools is not None:
                    staged = git_tools._staged_diff()
                    dialog_args.setdefault("staged_diff", staged[:8000])
                    dialog_args.setdefault("staged_diff_sha256", git_tools._staged_diff_hash())
            return await self._ask_user(tool_name, dialog_args, once_only=True)

        # W4.9: HIGH/CRITICAL calls (push, recursive delete, network pipe,
        # destructive patterns) always ask per call — cached SAFE approvals and
        # auto modes never satisfy them. The current approval still runs; it is
        # just never remembered (no inheritance for dangerous actions).
        if tier in ("HIGH", "CRITICAL"):
            return await self._ask_user(tool_name, args, cacheable=False)

        if self.mode == PermissionMode.AUTO_APPROVE_ALL:
            return True

        if self.mode == PermissionMode.AUTO_APPROVE_SAFE:
            if tool_permission == ToolPermission.ALWAYS:
                return True
            # ASK tools need user approval (scoped caches still apply inside
            # _ask_user so repeated SAFE commands do not reprompt).
            return await self._ask_user(tool_name, args)

        # ASK mode — everything needs approval.
        return await self._ask_user(tool_name, args)

    async def _ask_user(self, tool_name: str, tool_args: dict[str, Any], *, once_only: bool = False,
                        cacheable: bool = True) -> bool:
        """Show a permission request to the user, or reuse a scoped approval.

        ``once_only`` (git staging/commit) refuses persistent answers outright;
        ``cacheable=False`` (HIGH/CRITICAL) honors the current answer but never
        stores it, so the next identical call asks again.
        """
        if cacheable and not once_only and self._has_cached_approval(tool_name, tool_args):
            _LOG.debug("Permission reused from scoped cache: %s", tool_name)
            return True

        if self._request_callback is not None:
            answer = self._request_callback(tool_name, tool_args)
            if hasattr(answer, "__await__"):
                answer = await answer
            outcome = normalize_permission_outcome(answer)
            if outcome == PermissionOutcome.ALLOW_ALWAYS:
                if once_only:
                    _LOG.info("Persistent approval refused for %s %s", tool_name, tool_args)
                    return False
                if cacheable:
                    self._remember(outcome, tool_name, tool_args)
                _LOG.info("Permission granted (always%s): %s %s",
                          "" if cacheable else ", not cached", tool_name, tool_args)
                return True
            if outcome in (PermissionOutcome.ALLOW_TASK, PermissionOutcome.ALLOW_PROJECT):
                if once_only or not cacheable:
                    _LOG.info("Scoped approval refused for %s %s", tool_name, tool_args)
                    return False
                scope_id = self._active_task_id if outcome == PermissionOutcome.ALLOW_TASK else self._active_project
                if scope_id is None:
                    _LOG.info("Scoped approval without bound scope for %s; treating as once", tool_name)
                    return True
                self._remember(outcome, tool_name, tool_args)
                _LOG.info("Permission granted (%s): %s %s", outcome.value, tool_name, tool_args)
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
        """Forget every cached approval granted in this session (all scopes)."""
        self._always_allowed.clear()
        self._task_allowed.clear()
        self._project_allowed.clear()
