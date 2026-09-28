"""SAFE/LOW/MEDIUM/HIGH/CRITICAL command policy (W4.9).

``classify_command`` keeps its ``ALWAYS``/``ASK`` contract (callers depend on
it); this module adds the *visible risk tier* for the same command so the
permission dialog can show ``command, cwd, risk, reason`` and the permission
manager can refuse to inherit a SAFE approval for a dangerous action.

Tiers (fail-closed — unknown commands are HIGH)::

    SAFE     — read-only inspection (``git status``, ``pytest -q``, ...).
    LOW      — local builds/tests and dependency installs inside the workspace.
    MEDIUM   — anything else that still runs inside the workspace sandbox.
    HIGH     — network egress, privilege escalation, recursive delete, pushes.
    CRITICAL — destructive patterns that the terminal refuses to run at all
               (``BLOCKED_PATTERNS``): formatter, ``rm -rf /``, ``mkfs``, ...

HIGH/CRITICAL always require explicit per-call approval (never inheritable);
CRITICAL additionally stays blocked at execution time.
"""

from __future__ import annotations

import re

#: Ordered risk tiers, lowest first.
RISK_TIERS: tuple[str, ...] = ("SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL")

#: Tiers that always ask and are never satisfied by a cached approval.
ALWAYS_ASK_TIERS = frozenset({"HIGH", "CRITICAL"})

_SAFE_PREFIXES = (
    "git status", "git diff", "git log", "git show", "git branch", "git remote",
    "ls", "dir", "cat ", "type ", "echo ", "pwd", "whoami", "node --version",
    "python --version", "pip --version", "cargo --version", "npm --version",
)

_LOW_PREFIXES = (
    "pytest", "npm test", "npm run", "cargo build", "cargo check", "cargo test",
    "python ", "python3 ", "pip install", "npm install", "npm ci", "yarn install",
    "uv ", "ruff ", "mypy ", "black ", "go build", "go test", "go vet",
)

_HIGH_PATTERNS = re.compile(
    r"(\bcurl\b|\bwget\b|\bssh\b|\bsudo\b|\bsu\b|"
    r"\bchmod\b|\bchown\b|\bgit\s+push\b|\brm\s+-rf?\b|\brd\s+/s\b|del\s+/[fqs]\b|"
    r"\|\s*sh\b|>\s*/dev/|\bset-executionpolicy\b)",
    re.IGNORECASE,
)

_CRITICAL_PATTERNS = re.compile(
    r"\b(format\s+[a-zA-Z]:|diskpart|reg(add|delete|edit)|shutdown|taskkill\s+/f|"
    r"rm\s+-rf\s+[\\/]?\s*$|rd\s+/s\b|del\s+/[fqs]\b|mkfs|dd\s+if=|:\(\)\{.*\};:)",
    re.IGNORECASE,
)


def classify_command_risk(command: str) -> tuple[str, str]:
    """Return ``(tier, reason)`` for a shell command (W4.9).

    Mirrors ``terminal.SAFE_PREFIXES``/``BLOCKED_PATTERNS`` so the visible tier
    never contradicts the executable ``ALWAYS``/``ASK`` gate.
    """
    raw = (command or "").strip()
    cmd = raw.lower()
    if not cmd:
        return "MEDIUM", "empty command runs inside the workspace sandbox"
    if _CRITICAL_PATTERNS.search(cmd):
        return "CRITICAL", "matches the destructive-command blocklist"
    if _HIGH_PATTERNS.search(cmd):
        lowered = raw[:160]
        if "git push" in cmd:
            return "HIGH", f"pushes commits out of the workspace: {lowered}"
        if "rm -rf" in cmd or "rd /s" in cmd or cmd.startswith("del "):
            return "HIGH", f"recursive delete: {lowered}"
        if "curl" in cmd or "wget" in cmd or "| sh" in cmd:
            return "HIGH", f"network egress / remote code: {lowered}"
        return "HIGH", f"privilege or out-of-workspace effect: {lowered}"
    if cmd.startswith(_SAFE_PREFIXES):
        return "SAFE", "read-only inspection, no workspace mutation"
    if cmd.startswith(_LOW_PREFIXES):
        return "LOW", "local build/test/install inside the workspace"
    return "MEDIUM", "workspace-scoped command, effect depends on arguments"


def command_always_asks(command: str) -> bool:
    """True when a command must always ask, regardless of cached approvals."""
    tier, _reason = classify_command_risk(command)
    return tier in ALWAYS_ASK_TIERS
