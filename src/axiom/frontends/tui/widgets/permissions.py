"""Permission dialog — ask the user to approve or deny a tool execution.

This is the TUI's implementation of the ``request_callback`` that
:class:`~axiom.core.permissions.PermissionManager` calls when the current
mode requires user confirmation (W2.4). The tool call is really suspended
until the dialog returns a :class:`PermissionOutcome`.

W4.9 extends the dialog with scoped answers (task / project) and a visible
risk tier: HIGH/CRITICAL calls always ask per call and offer only
once / deny.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from axiom.core.permissions import PermissionOutcome
from axiom.shared import theme


class PermissionDialog(ModalScreen[PermissionOutcome]):
    """Modal dialog showing tool details and asking once / task / project / always / deny.

    Returns the answer chosen by the user; ``ALLOW_ONCE`` and ``DENY`` are
    never cached by the manager, scoped answers live in their task/project
    scope, and only ``ALLOW_ALWAYS`` is remembered for the session. HIGH /
    CRITICAL calls (``risk`` tier) offer only once / deny because the manager
    asks them per call regardless of cached approvals.
    """

    BINDINGS = [
        Binding("escape", "deny", "Deny", show=True),
        Binding("enter", "allow_once", "Allow once", show=True),
        Binding("f2", "allow_always", "Always allow", show=True),
        Binding("f3", "allow_task", "Allow for task", show=False),
        Binding("f4", "allow_project", "Allow for project", show=False),
    ]

    def __init__(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        risk: str = "SAFE",
        reason: str = "",
        command: str = "",
        task_id: str | None = None,
    ) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._tool_args = tool_args
        self._risk = str(risk or "SAFE").upper()
        self._reason = str(reason or "")
        self._command = str(command or "")
        self._task_id = task_id

    @property
    def _scoped(self) -> bool:
        return self._risk in ("HIGH", "CRITICAL")

    def compose(self) -> ComposeResult:
        yield Static("", id="perm-overlay")
        with Vertical(id="perm-dialog"):
            yield Static("PERMISSION REQUIRED", id="perm-title")
            yield Static(f"Tool:  {theme.TOOL_GLYPH} {self._tool_name}", id="perm-tool", markup=False)
            yield Static(f"Risk:  {self._risk}", id="perm-risk", markup=False)
            if self._command:
                yield Static(f"Command:\n{self._command[:2000]}", id="perm-command", markup=False)
            if self._reason:
                yield Static(self._reason[:1000], id="perm-reason", markup=False)
            if self._tool_args and not self._command:
                args_text = "\n".join(
                    f"  {key} = {value}"
                    for key, value in self._tool_args.items()
                )
                yield Static(f"Arguments:\n{args_text}", id="perm-args", markup=False)
            if self._scoped:
                yield Static(
                    "Dangerous action: asked every time, remembering does not apply.",
                    id="perm-prompt",
                    markup=False,
                )
            else:
                yield Static(
                    "Allow this tool to execute?\n"
                    "Once approves this call only; Task/Project remember within "
                    "the task/project; Always remembers this tool for the session.",
                    id="perm-prompt",
                    markup=False,
                )
            with Horizontal(id="perm-buttons"):
                yield Button("Allow once", id="perm-once", variant="primary")
                if not self._scoped:
                    if self._task_id:
                        yield Button("Allow for task", id="perm-task")
                    yield Button("Allow for project", id="perm-project")
                    yield Button("Always allow", id="perm-always")
                yield Button("Deny", id="perm-deny", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "perm-once":
            self.dismiss(PermissionOutcome.ALLOW_ONCE)
        elif event.button.id == "perm-task":
            self.dismiss(PermissionOutcome.ALLOW_TASK)
        elif event.button.id == "perm-project":
            self.dismiss(PermissionOutcome.ALLOW_PROJECT)
        elif event.button.id == "perm-always":
            self.dismiss(PermissionOutcome.ALLOW_ALWAYS)
        elif event.button.id == "perm-deny":
            self.dismiss(PermissionOutcome.DENY)

    def action_allow_once(self) -> None:
        self.dismiss(PermissionOutcome.ALLOW_ONCE)

    def action_allow_always(self) -> None:
        self.dismiss(PermissionOutcome.ALLOW_ALWAYS)

    def action_allow_task(self) -> None:
        self.dismiss(PermissionOutcome.ALLOW_TASK)

    def action_allow_project(self) -> None:
        self.dismiss(PermissionOutcome.ALLOW_PROJECT)

    def action_deny(self) -> None:
        self.dismiss(PermissionOutcome.DENY)
