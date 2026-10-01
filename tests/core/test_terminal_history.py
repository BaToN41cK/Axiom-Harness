"""W3.13: terminal command history and rerun."""

from __future__ import annotations

from axiom.core.tools.terminal import TerminalTool


async def test_run_records_history(tmp_path) -> None:
    tool = TerminalTool(root=tmp_path)
    result = await tool._run("python --version")
    assert result.ok is True
    assert len(tool.history) == 1
    assert tool.history[0]["command"] == "python --version"
    assert "exit_code" in tool.history[0]


async def test_rerun_replays_last_command(tmp_path) -> None:
    tool = TerminalTool(root=tmp_path)
    await tool._run("python --version")

    rerun = await tool.rerun()
    assert rerun.ok is True
    assert len(tool.history) == 2
    assert tool.history[1]["command"] == "python --version"


async def test_rerun_out_of_range(tmp_path) -> None:
    tool = TerminalTool(root=tmp_path)
    await tool._run("python --version")
    result = await tool.rerun(index=5)
    assert result.ok is False
    assert "out of range" in (result.error or "")


async def test_rerun_empty_history(tmp_path) -> None:
    tool = TerminalTool(root=tmp_path)
    result = await tool.rerun()
    assert result.ok is False
    assert "No command" in (result.error or "")
