"""Sandboxed terminal tool — real shell commands in the workspace root.

Safety model: a small allowlist of clearly-safe prefixes runs without
confirmation; everything else is flagged via ``ToolPermission.ASK`` so the
GUI can prompt the user. Destructive patterns are always blocked or ask.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

from axiom.core.tools.base import (
    RISK_DANGEROUS,
    ToolDefinition,
    ToolPermission,
    ToolResult,
)
from axiom.core.tools.filesystem import default_workspace_root
from axiom.core.tools.processes import command_argv, process_group_options, terminate_process_tree

RUN_COMMAND_TOOL = "run_command"

#: Commands safe enough to run without asking the user (prefix match).
SAFE_PREFIXES = (
    "git status", "git diff", "git log", "git show", "git branch", "git remote",
    "ls", "dir", "cat ", "type ", "echo ", "pwd", "whoami", "node --version",
    "python --version", "pip --version", "cargo --version", "npm --version",
    "pytest", "npm test", "npm run", "cargo build", "cargo check", "cargo test",
    "python ", "python3 ", "pip install", "npm install", "npm ci", "yarn install",
    "uv ", "ruff ", "mypy ", "black ", "go build", "go test", "go vet",
)

#: Never run these, even in full access mode.
BLOCKED_PATTERNS = re.compile(
    r"\b(format\s+[a-zA-Z]:|diskpart|reg(add|delete|edit)|shutdown|taskkill\s+/f|"
    r"rm\s+-rf\s+[\\/]?\s*$|rd\s+/s\b|del\s+/[fqs]\b|mkfs|dd\s+if=|:\(\)\{.*\};:)",
    re.IGNORECASE,
)

MAX_OUTPUT_CHARS = 12_000
DEFAULT_TIMEOUT = 120.0


def classify_command(command: str) -> ToolPermission:
    """ALWAYS for known-safe prefixes, ASK otherwise; BLOCKED never reaches exec."""
    cmd = command.strip().lower()
    if BLOCKED_PATTERNS.search(cmd):
        return ToolPermission.ASK  # user must explicitly confirm even these
    return ToolPermission.ALWAYS if cmd.startswith(SAFE_PREFIXES) else ToolPermission.ASK


class TerminalTool:
    """Runs real processes in the workspace directory."""

    def __init__(self, root: Path | None = None, enabled: bool = True) -> None:
        self.root = (root or default_workspace_root()).resolve()
        self.enabled = enabled
        self.on_process = None

    def set_root(self, root: Path) -> None:
        self.root = root.resolve()

    def _permission_for(self, name: str, args: dict) -> ToolPermission:
        return (
            ToolPermission.NEVER if not self.enabled
            else classify_command(str(args.get("command", "")))
        )

    def register(self, registry) -> None:
        definition = ToolDefinition(
            name=RUN_COMMAND_TOOL,
            description=(
                "Run a shell command inside the current workspace directory "
                "(PowerShell on Windows). Use it to run tests, build tools, "
                "package managers and other project commands."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command line to execute."},
                    "timeout": {
                        "type": "number",
                        "description": "Optional timeout in seconds (default 120).",
                    },
                },
                "required": ["command"],
            },
            permission=ToolPermission.ALWAYS,  # per-call classification below
            risk=RISK_DANGEROUS,
            timeout=DEFAULT_TIMEOUT,
            max_output=MAX_OUTPUT_CHARS,
            cancellable=True,
            workspace_scoped=True,
        )
        registry.register(definition, self._run, permission_for=self._permission_for)

    async def _run(self, command: str, timeout: float | None = None) -> ToolResult:
        if not self.enabled:
            return ToolResult(name=RUN_COMMAND_TOOL, ok=False, error="Terminal access is disabled")
        command = command.strip()
        if not command:
            return ToolResult(name=RUN_COMMAND_TOOL, ok=False, error="Command is empty")
        if BLOCKED_PATTERNS.search(command):
            return ToolResult(
                name=RUN_COMMAND_TOOL,
                ok=False,
                error="Command blocked as potentially destructive. The user must run it manually.",
            )
        limit = min(max(timeout or DEFAULT_TIMEOUT, 1.0), 600.0)
        try:
            common = {
                "cwd": self.root,
                "stdin": asyncio.subprocess.DEVNULL,
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
                "env": {**os.environ, "PYTHONIOENCODING": "utf-8"},
                **process_group_options(),
            }
            if os.name == "nt":
                proc = await asyncio.create_subprocess_exec(*command_argv(command), **common)
            else:
                proc = await asyncio.create_subprocess_shell(command, **common)
            started = time.time()
            if self.on_process:
                self.on_process({"pid": proc.pid, "command": command[:2000], "state": "running", "started_at": started})
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=limit)
            except TimeoutError:
                await terminate_process_tree(proc)
                if self.on_process:
                    self.on_process({"pid": proc.pid, "state": "timeout", "returncode": proc.returncode})
                return ToolResult(
                    name=RUN_COMMAND_TOOL,
                    ok=False,
                    error=f"Command timed out after {limit:.0f}s",
                )
            except asyncio.CancelledError:
                await terminate_process_tree(proc)
                if self.on_process:
                    self.on_process({"pid": proc.pid, "state": "cancelled", "returncode": proc.returncode})
                raise
            if self.on_process:
                self.on_process({"pid": proc.pid, "state": "exited", "returncode": proc.returncode})
        except (OSError, ValueError) as exc:
            return ToolResult(name=RUN_COMMAND_TOOL, ok=False, error=f"Cannot execute: {exc}")

        def _clip(raw: bytes) -> str:
            text = raw.decode("utf-8", errors="replace")
            return text[:MAX_OUTPUT_CHARS] + ("… truncated" if len(text) > MAX_OUTPUT_CHARS else "")

        stdout, stderr = _clip(out), _clip(err)
        body = stdout
        if stderr:
            body = f"{body}\n[stderr]\n{stderr}".strip()
        ok = proc.returncode == 0
        return ToolResult(
            name=RUN_COMMAND_TOOL,
            ok=ok,
            content=body or f"(no output, exit code {proc.returncode})",
            data={"exit_code": proc.returncode, "cwd": str(self.root)},
        )
