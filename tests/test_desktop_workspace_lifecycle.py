"""Regression tests for desktop workspace and interactive shell lifecycle."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

BRIDGE = Path(__file__).resolve().parents[1] / "desktop" / "src-tauri" / "bridge" / "axiom_bridge.py"


def _bridge_module():
    spec = importlib.util.spec_from_file_location("axiom_bridge_workspace_lifecycle", BRIDGE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Shell:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_workspace_switch_stops_old_interactive_shell(tmp_path: Path) -> None:
    module = _bridge_module()
    target = tmp_path / "project"
    target.mkdir()
    shell = _Shell()
    info = SimpleNamespace(to_json=lambda: {"path": str(target)})

    class Session:
        busy = False
        gui_shell = shell

        def set_workspace(self, path: str):
            assert path == str(target)
            return info

    session = Session()
    result = await module._handle(session, "set_workspace", {"path": str(target)})

    assert result == {"path": str(target)}
    assert shell.stopped
    assert session.gui_shell is None


@pytest.mark.asyncio
async def test_clearing_workspace_stops_interactive_shell() -> None:
    module = _bridge_module()
    shell = _Shell()

    class Session:
        busy = False
        gui_shell = shell

        def clear_workspace(self) -> None:
            self.cleared = True

    session = Session()
    result = await module._handle(session, "clear_workspace", {})

    assert result == {"current": None}
    assert session.cleared
    assert shell.stopped
    assert session.gui_shell is None


@pytest.mark.asyncio
async def test_workspace_cannot_change_during_generation(tmp_path: Path) -> None:
    module = _bridge_module()
    target = tmp_path / "project"
    target.mkdir()
    shell = _Shell()

    class Session:
        busy = True
        gui_shell = shell
        switched = False

        def set_workspace(self, _path: str) -> None:
            self.switched = True

    session = Session()
    with pytest.raises(ValueError, match="active generation"):
        await module._handle(session, "set_workspace", {"path": str(target)})

    assert not session.switched
    assert not shell.stopped
    assert session.gui_shell is shell


@pytest.mark.asyncio
async def test_invalid_workspace_keeps_interactive_shell(tmp_path: Path) -> None:
    module = _bridge_module()
    shell = _Shell()

    class Session:
        busy = False
        gui_shell = shell

    session = Session()
    with pytest.raises(ValueError, match="Not a directory"):
        await module._handle(session, "set_workspace", {"path": str(tmp_path / "missing")})

    assert not shell.stopped
    assert session.gui_shell is shell
