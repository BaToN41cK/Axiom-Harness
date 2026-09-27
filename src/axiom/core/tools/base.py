from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: Risk classification for tool metadata (§3 Tool API). The executable policy
#: stays :class:`ToolPermission` — risk only describes *how dangerous a tool is*
#: when the UI/registry renders or audits it.
RISK_SAFE = "safe"
RISK_MEDIUM = "medium"
RISK_DANGEROUS = "dangerous"


class ToolPermission(str, Enum):
    """How a tool may be executed.

    ``ALWAYS``  — safe, executed automatically.
    ``ASK``     — requires explicit user approval (future permission UI).
    ``NEVER``   — disabled.
    """

    ALWAYS = "always"
    ASK = "ask"
    NEVER = "never"


@dataclass
class ToolDefinition:
    """Declarative description of a tool handed to the model.

    Beyond the model schema, every tool carries operational metadata (§3):
    risk level, timeout, output cap, streaming/cancellation/dry-run support,
    rollback strategy and workspace scoping. All fields default to conservative
    values so existing tool registrations keep working unchanged.
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    permission: ToolPermission = ToolPermission.ASK
    #: safe | medium | dangerous — audits/UI hint, not an execution gate.
    risk: str = RISK_SAFE
    #: Wall-clock budget in seconds; ``None`` = the tool's own default.
    timeout: float | None = None
    #: Hard cap for the result content handed back to the model (chars).
    max_output: int | None = None
    #: Tool can stream partial results while it runs.
    streaming: bool = False
    #: Tool honours cooperative cancellation.
    cancellable: bool = True
    #: Tool supports a no-op preview mode (nothing is mutated).
    dry_run: bool = False
    #: none | checkpoint | undo | file — how a change can be reverted.
    rollback: str = "none"
    #: Tool only makes sense inside a validated workspace root.
    workspace_scoped: bool = False

    def schema(self) -> dict[str, Any]:
        """Ollama/OpenAI-compatible tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
                or {"type": "object", "properties": {}, "required": []},
            },
        }

    def meta(self) -> dict[str, Any]:
        """Operational metadata for diagnostics/tools UI (never sent to models)."""
        return {
            "name": self.name,
            "permission": self.permission.value,
            "risk": self.risk,
            "timeout": self.timeout,
            "max_output": self.max_output,
            "streaming": self.streaming,
            "cancellable": self.cancellable,
            "dry_run": self.dry_run,
            "rollback": self.rollback,
            "workspace_scoped": self.workspace_scoped,
        }


@dataclass
class ToolResult:
    """Structured result of a real tool execution."""

    name: str
    ok: bool
    content: str = ""
    error: str | None = None
    duration_ms: int = 0
    data: Any = None
    meta: dict[str, Any] = field(default_factory=dict)

    def as_contract(self) -> dict[str, Any]:
        """Stable tool envelope; ``data`` remains available to existing callers."""
        return {"tool": self.name, "ok": self.ok, "content": self.content,
                "error": self.error, "duration_ms": self.duration_ms, "meta": self.meta}


ToolHandler = Callable[..., Awaitable[ToolResult]]
