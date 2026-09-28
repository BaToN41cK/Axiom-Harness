"""Autonomy modes (W4.9) — explicit composition of the two existing axes.

``access_mode`` (``read_only`` / ``workspace`` / ``full``) controls *where* tools
may act; ``permission_mode`` (``ask`` / ``auto_approve_safe`` /
``auto_approve_all``) controls *how much* the user is asked. W4.9 composes them
into four named autonomy presets so the UI can show one switch instead of two
independent dropdowns::

    PLAN — read-only analysis, every write/process stays blocked.
    EDIT — workspace edits run, terminal and network still ask.
    AUTO — workspace default: safe tools run, risky ones ask.
    FULL — explicit opt-in: everything the axes allow runs without asking.

The mapping is a pure function of the two axes — no new manager, no new
persistence beyond the existing ``Config.access_mode`` / ``Config.permission_mode``.
"""

from __future__ import annotations

from typing import Literal

AutonomyMode = Literal["plan", "edit", "auto", "full"]

_AUTONOMY_MODES: tuple[str, ...] = ("plan", "edit", "auto", "full")


def resolve_autonomy(access_mode: str, permission_mode: str) -> str:
    """Compose the two existing axes into one W4.9 autonomy preset name."""
    access = (access_mode or "workspace").lower()
    permission = (permission_mode or "auto_approve_safe").lower()
    if access == "read_only":
        return "plan"
    if permission == "ask":
        return "edit"
    if permission == "auto_approve_all" and access == "full":
        return "full"
    return "auto"


def apply_autonomy(mode: str) -> dict[str, str]:
    """Map a W4.9 autonomy preset back onto the two persisted axes.

    Unknown values fail closed to the safest composition (PLAN axes).
    """
    normalized = (mode or "").strip().lower()
    if normalized == "plan":
        return {"access_mode": "read_only", "permission_mode": "ask"}
    if normalized == "edit":
        return {"access_mode": "workspace", "permission_mode": "ask"}
    if normalized == "full":
        return {"access_mode": "full", "permission_mode": "auto_approve_all"}
    if normalized == "auto":
        return {"access_mode": "workspace", "permission_mode": "auto_approve_safe"}
    return {"access_mode": "read_only", "permission_mode": "ask"}


def autonomy_modes() -> tuple[str, ...]:
    """Ordered autonomy preset names for UI dropdowns."""
    return _AUTONOMY_MODES


def blocks_writes(access_mode: str) -> bool:
    """True when the access axis alone forbids every write/process tool."""
    return (access_mode or "").lower() == "read_only"
