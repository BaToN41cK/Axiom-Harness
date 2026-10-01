"""Frontend dispatch tests: TUI is the default, --gui launches the desktop app."""

from __future__ import annotations

import sys as _sys

import pytest

import axiom.__main__ as _dispatch_shim  # noqa: F401

dispatch = _sys.modules["axiom.__main__"]


def test_help_lists_dispatch_modes(capsys: pytest.CaptureFixture[str]) -> None:
    assert dispatch.main(["--help"]) == 0
    out, _ = capsys.readouterr()
    assert "axiom --gui" in out
    assert "axiom run" in out
    assert "axiom serve" in out
    # The legacy top-level ``-p`` prompt flag stays removed.
    assert "-p" not in out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert dispatch.main(["--version"]) == 0
    out, _ = capsys.readouterr()
    assert "AXIOM" in out


def test_unknown_flag_returns_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert dispatch.main(["-p", "hi"]) == 2
    _, err = capsys.readouterr()
    assert "-p" in err
    assert dispatch.main(["--json"]) == 2


def test_default_dispatches_to_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setitem(_sys.modules, "axiom.frontends.tui.app", _FakeTuiApp(called, "tui"))
    assert dispatch.main([]) == 0
    assert called == ["tui"]


def test_gui_flag_dispatches_to_gui(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setitem(_sys.modules, "axiom.frontends.gui.main", _FakeGuiApp(called, "gui"))
    assert dispatch.main(["--gui"]) == 0
    assert called == ["gui"]


class _FakeTuiApp:
    def __init__(self, called: list[str], name: str) -> None:
        self._called = called
        self._name = name

    def main(self) -> int:
        self._called.append(self._name)
        return 0


class _FakeGuiApp:
    def __init__(self, called: list[str], name: str) -> None:
        self._called = called
        self._name = name

    def main(self) -> int:
        self._called.append(self._name)
        return 0
