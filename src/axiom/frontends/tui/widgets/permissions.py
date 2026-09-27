"""Permission dialog — ask the user to approve or deny a tool execution.

This is the TUI's implementation of the ``request_callback`` that
:class:`~axiom.core.permissions.PermissionManager` calls when the current
mode requires user confirmation (W2.4). The tool call is really suspended
until the dialog returns a :class:`PermissionOutcome`.
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
    """Modal dialog showing tool details and asking once / always / deny.

    Returns the answer chosen by the user; only ``ALLOW_ALWAYS`` is cached by
    the manager, so "Allow once" really asks again next time.
    """

    BINDINGS = [
        Binding("escape", "deny", "Deny", show=True),
        Binding("enter", "allow_once", "Allow once", show=True),
        Binding("f2", "allow_always", "Always allow", show=True),
    ]

    def __init__(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._tool_args = tool_args

    def compose(self) -> ComposeResult:
        yield Static("", id="perm-overlay")
        with Vertical(id="perm-dialog"):
            yield Static("PERMISSION REQUIRED", id="perm-title")
            yield Static(f"Tool:  {theme.TOOL_GLYPH} {self._tool_name}", id="perm-tool", markup=False)
            if self._tool_args:
                args_text = "\n".join(
                    f"  {key} = {value}"
                    for key, value in self._tool_args.items()
                )
                yield Static(f"Arguments:\n{args_text}", id="perm-args", markup=False)
            yield Static(
                "Allow this tool to execute?\n"
                "Once approves this call only; Always remembers this tool for the session.",
                id="perm-prompt",
                markup=False,
            )
            with Horizontal(id="perm-buttons"):
                yield Button("Allow once", id="perm-once", variant="primary")
                yield Button("Always allow", id="perm-always")
                yield Button("Deny", id="perm-deny", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "perm-once":
            self.dismiss(PermissionOutcome.ALLOW_ONCE)
        elif event.button.id == "perm-always":
            self.dismiss(PermissionOutcome.ALLOW_ALWAYS)
        elif event.button.id == "perm-deny":
            self.dismiss(PermissionOutcome.DENY)

    def action_allow_once(self) -> None:
        self.dismiss(PermissionOutcome.ALLOW_ONCE)

    def action_allow_always(self) -> None:
        self.dismiss(PermissionOutcome.ALLOW_ALWAYS)

    def action_deny(self) -> None:
        self.dismiss(PermissionOutcome.DENY)
