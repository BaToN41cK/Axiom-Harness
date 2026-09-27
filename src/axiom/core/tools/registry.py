"""Tool registry — the single place where agent tools are declared.

Tools are never executed silently: each one carries an explicit
:class:`~axiom.core.tools.base.ToolPermission`. Adding a tool requires no UI
changes — frontends render :class:`~axiom.core.events.ToolCallEvent` and
:class:`~axiom.core.events.ToolResultEvent` generically.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from copy import copy, deepcopy

from axiom.core.errors import AxiomError
from axiom.core.security import ToolAudit
from axiom.core.tools.base import (
    ToolDefinition,
    ToolHandler,
    ToolPermission,
    ToolResult,
)


class ToolRegistry:
    """Holds tool definitions together with their real handlers."""

    def __init__(self, *, audit: ToolAudit | None = None) -> None:
        self._tools: dict[str, tuple[ToolDefinition, ToolHandler]] = {}
        self.audit = audit or ToolAudit()
        #: Per-tool classifiers: (tool name, args) -> permission. Used for
        #: tools whose danger depends on the arguments (e.g. shell commands).
        #: A classifier registered for one tool never affects other tools.
        self.classifier: dict[str, Callable[[str, dict], ToolPermission]] = {}

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
        permission_for: Callable[[str, dict], ToolPermission] | None = None,
    ) -> None:
        if permission_for is not None:
            self.classifier[definition.name] = permission_for
        self._tools[definition.name] = (definition, handler)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self.classifier.pop(name, None)

    def get(self, name: str) -> ToolDefinition | None:
        entry = self._tools.get(name)
        return entry[0] if entry else None

    def subset(self, names: Iterable[str]) -> ToolRegistry:
        """Return an independent registry containing only the requested tools."""
        selected = ToolRegistry(audit=self.audit)
        cloned_owners: dict[int, object] = {}

        def _clone_bound_callable(callback):
            owner = getattr(callback, "__self__", None)
            function = getattr(callback, "__func__", None)
            if owner is None or function is None:
                return callback
            owner_id = id(owner)
            if owner_id not in cloned_owners:
                cloned_owners[owner_id] = copy(owner)
            return getattr(cloned_owners[owner_id], function.__name__)

        for name in names:
            entry = self._tools.get(name)
            if entry is None:
                continue
            # Bound tool handlers/classifiers often read mutable owner state
            # such as a workspace root. Clone each owner once so a request
            # cannot observe another request changing its tool context mid-run.
            handler = _clone_bound_callable(entry[1])
            classifier = self.classifier.get(name)
            selected.register(
                deepcopy(entry[0]), handler,
                permission_for=_clone_bound_callable(classifier) if classifier else None,
            )
        return selected

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def definitions(self, *, allowed: ToolPermission | None = None) -> list[ToolDefinition]:
        """Tool definitions suitable for the model request."""
        result = []
        for definition, _ in self._tools.values():
            if definition.permission is ToolPermission.NEVER:
                continue
            if allowed is not None and definition.permission is not allowed:
                continue
            result.append(definition)
        return result

    def schemas(self) -> list[dict]:
        """Tool schemas for the Ollama ``tools`` parameter."""
        return [d.schema() for d in self.definitions()]

    def permission_for(self, name: str, arguments: dict | None = None) -> ToolPermission:
        """Return the effective permission for a tool call.

        Keeping this beside the registry prevents the agent from guessing a
        tool's safety policy and keeps the policy consistent for all callers.
        """
        entry = self._tools.get(name)
        if entry is None:
            return ToolPermission.NEVER
        definition = entry[0]
        classifier = self.classifier.get(name)
        if classifier is not None:
            return classifier(name, arguments or {})
        return definition.permission

    async def execute(
        self, name: str, arguments: dict | None = None, *, approved: bool = False
    ) -> ToolResult:
        """Execute a tool by name, enforcing its permission.

        ``approved`` is reserved for callers that have already obtained an
        explicit permission decision; normal tool calls remain classifier-gated.
        A model can never force execution of a ``NEVER`` tool, and unknown
        tools fail with a structured result instead of raising.
        """
        started = time.perf_counter()
        entry = self._tools.get(name)
        if entry is None:
            result = ToolResult(name=name, ok=False, error=f"Unknown tool: {name}")
            self.audit.record(name, arguments or {}, False, 0)
            return result
        definition, handler = entry
        if definition.permission is ToolPermission.NEVER:
            result = ToolResult(name=name, ok=False, error=f"Tool '{name}' is disabled")
            self.audit.record(name, arguments or {}, False, 0)
            return result
        classifier = self.classifier.get(name)
        if (not approved and classifier is not None
                and classifier(name, arguments or {}) is ToolPermission.ASK):
            return ToolResult(
                name=name,
                ok=False,
                error=(
                    "Permission required: this command was not pre-approved by the user. "
                    "Do not retry it — tell the user which command you need and why."
                ),
                data={"permission": "ask"},
            )
        try:
            result = await handler(**(arguments or {}))
        except AxiomError as exc:
            result = ToolResult(name=name, ok=False, error=str(exc))
        except TypeError as exc:
            result = ToolResult(name=name, ok=False, error=f"Invalid arguments: {exc}")
        except Exception as exc:
            result = ToolResult(name=name, ok=False, error=f"{type(exc).__name__}: {exc}")
        result.name = name
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        self.audit.record(name, arguments or {}, result.ok, result.duration_ms)
        return result
