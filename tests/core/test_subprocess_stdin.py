"""Regression tests for child-process stdin isolation in the Python core."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from axiom.core.tools.git_tools import GitTools
from axiom.core.tools.terminal import TerminalTool
from axiom.core.workspace import detect_project


class _FakeAsyncProcess:
    def __init__(self, *, returncode: int = 0, stdout: bytes = b"ok\n", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.returncode = -9


async def test_terminal_tool_uses_devnull_for_child_stdin(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_create_subprocess(command: str, *args, **kwargs):
        captured["command"] = (command, *args)
        captured.update(kwargs)
        return _FakeAsyncProcess(stdout=b"done\n")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_create_subprocess)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess)

    tool = TerminalTool(root=tmp_path)
    result = await tool._run("python --version")

    assert result.ok is True
    assert captured["stdin"] is asyncio.subprocess.DEVNULL
    assert captured["stdout"] is asyncio.subprocess.PIPE
    assert captured["stderr"] is asyncio.subprocess.PIPE
    if os.name == "nt":
        assert isinstance(captured["command"], tuple)
        assert captured["command"][0] == "python"


def test_detect_project_uses_devnull_for_git_probe(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".git").mkdir()
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="main\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    info = detect_project(tmp_path)

    assert info.git is True
    assert info.branch == "main"
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["capture_output"] is True
    assert captured["check"] is False


def test_git_tools_use_devnull_for_read_only_commands(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".git").mkdir()
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="## main\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = GitTools(tmp_path)._run_git(["status", "--short", "--branch"])

    assert result.ok is True
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["capture_output"] is True
    assert captured["text"] is True
