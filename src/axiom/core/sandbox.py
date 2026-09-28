"""Sandbox / Permission System: levels + policies (W4.9 presets).

Levels: READ / WRITE / EXECUTE / NETWORK / GIT / DELETE.
Policies: ask / auto / deny. Decision by (level, policy).
Presets: readonly / workspace / workspace-network / full (see PRESETS).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SandboxLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    GIT = "git"
    DELETE = "delete"


class SandboxPolicy(str, Enum):
    ASK = "ask"
    AUTO = "auto"
    DENY = "deny"


TOOL_LEVELS: dict[str, SandboxLevel] = {
    "web_search": SandboxLevel.NETWORK, "fetch_url": SandboxLevel.NETWORK,
    "list_files": SandboxLevel.READ, "read_file": SandboxLevel.READ,
    "search_text": SandboxLevel.READ, "search_files": SandboxLevel.READ,
    "inspect_project": SandboxLevel.READ,
    "git_status": SandboxLevel.GIT, "git_diff": SandboxLevel.GIT,
    "git_log": SandboxLevel.GIT, "git_branch": SandboxLevel.GIT,
    "git_add": SandboxLevel.GIT, "git_commit": SandboxLevel.GIT,
    "write_file": SandboxLevel.WRITE, "edit_file": SandboxLevel.WRITE,
    "apply_patch": SandboxLevel.WRITE,
    "create_directory": SandboxLevel.WRITE, "copy_file": SandboxLevel.WRITE,
    "move_file": SandboxLevel.WRITE,
    "delete_file": SandboxLevel.DELETE,
    "run_command": SandboxLevel.EXECUTE,
    "run_tests": SandboxLevel.EXECUTE, "run_linter": SandboxLevel.EXECUTE,
    "build_project": SandboxLevel.EXECUTE, "verify_changes": SandboxLevel.EXECUTE,
}

#: Tools that stay usable under the ``readonly`` preset (pure reads + read-only
#: git inspection). Mirrors ``permissions._PLAN_READ_TOOLS`` without importing it.
_READONLY_TOOLS = frozenset({
    "list_files", "read_file", "search_text", "search_files",
    "inspect_project", "git_status", "git_diff", "git_log", "git_branch",
    "web_search", "fetch_url", "knowledge_search", "knowledge_index",
    "knowledge_status", "memory_read",
})

#: W4.9 named presets: level -> policy. Unknown levels fall back to ASK.
PRESETS: dict[str, dict[SandboxLevel, SandboxPolicy]] = {
    "readonly": {
        SandboxLevel.READ: SandboxPolicy.AUTO,
        SandboxLevel.WRITE: SandboxPolicy.DENY,
        SandboxLevel.EXECUTE: SandboxPolicy.DENY,
        SandboxLevel.NETWORK: SandboxPolicy.DENY,
        SandboxLevel.GIT: SandboxPolicy.ASK,
        SandboxLevel.DELETE: SandboxPolicy.DENY,
    },
    "workspace": {
        SandboxLevel.READ: SandboxPolicy.AUTO,
        SandboxLevel.WRITE: SandboxPolicy.AUTO,
        SandboxLevel.EXECUTE: SandboxPolicy.AUTO,
        SandboxLevel.NETWORK: SandboxPolicy.ASK,
        SandboxLevel.GIT: SandboxPolicy.AUTO,
        SandboxLevel.DELETE: SandboxPolicy.ASK,
    },
    "workspace-network": {
        SandboxLevel.READ: SandboxPolicy.AUTO,
        SandboxLevel.WRITE: SandboxPolicy.AUTO,
        SandboxLevel.EXECUTE: SandboxPolicy.AUTO,
        SandboxLevel.NETWORK: SandboxPolicy.AUTO,
        SandboxLevel.GIT: SandboxPolicy.AUTO,
        SandboxLevel.DELETE: SandboxPolicy.ASK,
    },
    "full": {
        SandboxLevel.READ: SandboxPolicy.AUTO,
        SandboxLevel.WRITE: SandboxPolicy.AUTO,
        SandboxLevel.EXECUTE: SandboxPolicy.AUTO,
        SandboxLevel.NETWORK: SandboxPolicy.AUTO,
        SandboxLevel.GIT: SandboxPolicy.AUTO,
        SandboxLevel.DELETE: SandboxPolicy.ASK,
    },
}

#: ``access_mode`` -> preset name (conservative: ``full`` access maps to
#: ``workspace-network``, the explicit ``full`` preset is FULL autonomy only).
ACCESS_PRESETS = {
    "read_only": "readonly",
    "workspace": "workspace",
    "full": "workspace-network",
}


def level_of(tool_name: str) -> SandboxLevel:
    return TOOL_LEVELS.get(tool_name, SandboxLevel.EXECUTE)


@dataclass
class Sandbox:
    """Default policies are the ``workspace`` preset (W4.9)."""

    policies: dict[SandboxLevel, SandboxPolicy] = field(default_factory=lambda: dict(PRESETS["workspace"]))
    ask_callback: object = None
    preset: str = "workspace"

    def set_policy(self, level: SandboxLevel, policy: SandboxPolicy) -> None:
        self.policies[level] = policy

    def apply_preset(self, name: str) -> str:
        """Apply a W4.9 preset; unknown names fail closed to ``workspace``."""
        normalized = (name or "").strip().lower()
        preset = PRESETS.get(normalized, PRESETS["workspace"])
        self.policies = dict(preset)
        self.preset = normalized if normalized in PRESETS else "workspace"
        return self.preset

    @classmethod
    def for_access(cls, access_mode: str) -> Sandbox:
        """Compatibility entry point: profile for an access axis value."""
        preset = ACCESS_PRESETS.get((access_mode or "").lower(), "workspace")
        box = cls()
        box.apply_preset(preset)
        return box

    def decide(self, tool_name: str) -> str:
        """Returns 'auto' | 'ask' | 'deny'."""
        if self.preset == "readonly" and tool_name not in _READONLY_TOOLS:
            return SandboxPolicy.DENY.value
        level = level_of(tool_name)
        policy = self.policies.get(level, SandboxPolicy.ASK)
        return policy.value

    def allows(self, tool_name: str) -> bool:
        return self.decide(tool_name) != SandboxPolicy.DENY.value
