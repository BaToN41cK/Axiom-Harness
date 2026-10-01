"""Settings backup and restore (W3.8).

Backs up the user-facing JSON settings under ``AXIOM_HOME`` into a single zip,
and restores them safely: only known filenames are ever extracted, every file
is validated as JSON before it is written, and no absolute/relative path from
inside the archive is trusted.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from axiom.core.config import axiom_home

#: The settings files that participate in a backup (config + persisted state).
SETTINGS_FILES = (
    "config.json",
    "providers.json",
    "profiles.json",
    "workspaces.json",
    "plugins.json",
    "automation.json",
    "connectors.json",
)


def backup_settings(destination: Path) -> Path:
    """Archive every existing settings file into ``destination`` (a zip)."""
    source_dir = axiom_home()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in SETTINGS_FILES:
            path = source_dir / name
            if path.exists():
                archive.write(path, arcname=name)
    return destination


def restore_settings(source: Path) -> list[str]:
    """Restore settings from a backup zip; returns the filenames that were restored.

    Only the whitelisted filenames are extracted, and each must parse as JSON,
    so a malformed or malicious archive can never write an arbitrary path.
    """
    target = axiom_home()
    target.mkdir(parents=True, exist_ok=True)
    restored: list[str] = []
    with zipfile.ZipFile(source, "r") as archive:
        for name in archive.namelist():
            if name not in SETTINGS_FILES:
                continue
            data = archive.read(name)
            try:
                json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            (target / name).write_bytes(data)
            restored.append(name)
    return restored
