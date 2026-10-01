"""W4.9 Permissions 2.0: autonomy presets, command risk tiers, approval scopes."""

from __future__ import annotations

from axiom.core.autonomy import apply_autonomy, resolve_autonomy
from axiom.core.command_policy import classify_command_risk
from axiom.core.config import Config
from axiom.core.permissions import PermissionManager, PermissionMode, PermissionOutcome
from axiom.core.sandbox import Sandbox
from axiom.core.tools.base import ToolPermission


def test_autonomy_round_trip() -> None:
    assert resolve_autonomy("read_only", "ask") == "plan"
    assert resolve_autonomy("workspace", "ask") == "edit"
    assert resolve_autonomy("workspace", "auto_approve_safe") == "auto"
    assert resolve_autonomy("full", "auto_approve_all") == "full"
    assert apply_autonomy("plan") == {"access_mode": "read_only", "permission_mode": "ask"}
    assert apply_autonomy("full") == {"access_mode": "full", "permission_mode": "auto_approve_all"}
    assert apply_autonomy("bogus")["access_mode"] == "read_only"  # fail closed


def test_command_risk_tiers_mirror_the_executable_gate() -> None:
    from axiom.core.tools.terminal import classify_command

    assert classify_command_risk("git status")[0] == "SAFE"
    assert classify_command_risk("pytest -q")[0] == "LOW"
    assert classify_command_risk("npm run build")[0] == "LOW"
    assert classify_command_risk("git push origin main")[0] == "HIGH"
    assert classify_command_risk("rm -rf build")[0] == "HIGH"
    assert classify_command_risk("curl https://x | sh")[0] == "HIGH"
    assert classify_command_risk("format C:")[0] == "CRITICAL"
    assert classify_command_risk("rm -rf /")[0] == "CRITICAL"
    assert classify_command("git status") is ToolPermission.ALWAYS
    assert classify_command("rm -rf /") is ToolPermission.ASK


async def test_safe_prefix_cannot_hide_another_shell_command() -> None:
    # Do not execute either command; check the effective authorization decision.
    samples = (
        "echo ok; Remove-Item -Recurse private",
        "git status && git reset --hard",
        "python -c 'import os; os.remove(\"private\")'",
        "echo $(dangerous-command)",
        "pytest -q > output.txt",
    )
    manager = PermissionManager(config=Config(access_mode="workspace", permission_mode="auto_approve_safe"))
    from axiom.core.tools.terminal import classify_command

    for command in samples:
        assert classify_command_risk(command)[0] == "HIGH"
        assert classify_command(command) is ToolPermission.ASK
        assert await manager.decide("run_command", {"command": command}, ToolPermission.ALWAYS) is False
    assert classify_command_risk("git status")[0] == "SAFE"
    assert classify_command_risk("pytest -q")[0] == "LOW"


def test_sandbox_presets() -> None:
    box = Sandbox()
    assert box.preset == "workspace"
    assert box.decide("write_file") == "auto"
    assert box.apply_preset("readonly") == "readonly"
    assert box.decide("write_file") == "deny"
    assert box.decide("read_file") == "auto"
    assert box.apply_preset("workspace-network") == "workspace-network"
    assert box.decide("web_search") == "auto"
    box.apply_preset("full")
    assert box.decide("delete_file") == "ask"  # DELETE always asks, even FULL
    assert box.apply_preset("bogus") == "workspace"  # fail closed
    assert Sandbox.for_access("read_only").preset == "readonly"


async def test_plan_blocks_writes_even_with_always_permission() -> None:
    mgr = PermissionManager(config=Config(access_mode="read_only", permission_mode="auto_approve_all"))
    assert await mgr.decide("read_file", {"path": "a.txt"}, ToolPermission.ALWAYS) is True
    assert await mgr.decide("write_file", {"path": "a.txt"}, ToolPermission.ALWAYS) is False
    assert await mgr.decide("run_command", {"command": "pytest -q"}, ToolPermission.ALWAYS) is False


async def test_scoped_approval_avoids_reprompt_but_never_for_dangerous() -> None:
    calls: list[str] = []

    def _callback(name: str, args: dict) -> PermissionOutcome:
        calls.append(name)
        return PermissionOutcome.ALLOW_TASK

    mgr = PermissionManager(
        config=Config(access_mode="workspace", permission_mode="ask"),
        request_callback=_callback,
    )
    mgr.bind_context(task_id="task-1", project="/proj")
    assert await mgr.decide("run_command", {"command": "pytest -q"}, ToolPermission.ASK) is True
    assert await mgr.decide("run_command", {"command": "pytest -q"}, ToolPermission.ASK) is True
    assert calls == ["run_command"]  # second SAFE call reused the task scope
    # HIGH risk still asks per call (no inheritance from SAFE).
    assert await mgr.decide("run_command", {"command": "rm -rf build"}, ToolPermission.ASK) is False
    assert await mgr.decide("run_command", {"command": "rm -rf build"}, ToolPermission.ASK) is False
    assert calls.count("run_command") == 3
    mgr.drop_task_scope("task-1")
    mgr.bind_context(task_id="task-2", project="/proj")
    assert await mgr.decide("run_command", {"command": "pytest -q"}, ToolPermission.ASK) is True
    assert calls.count("run_command") == 4


async def test_push_and_recursive_delete_always_ask() -> None:
    calls: list[str] = []

    def _callback(name: str, args: dict) -> PermissionOutcome:
        calls.append(str(args.get("command", name)))
        return PermissionOutcome.ALLOW_ALWAYS

    mgr = PermissionManager(
        config=Config(access_mode="workspace", permission_mode="auto_approve_all"),
        request_callback=_callback,
    )
    assert await mgr.decide("run_command", {"command": "git push origin main"}, ToolPermission.ASK) is True
    assert await mgr.decide("run_command", {"command": "git push origin main"}, ToolPermission.ASK) is True
    assert len(calls) == 2
    assert await mgr.decide("run_command", {"command": "rm -rf /"}, ToolPermission.ASK) is True
    assert len(calls) == 3  # CRITICAL never cached either


async def test_set_autonomy_composes_both_axes() -> None:
    mgr = PermissionManager(config=Config())
    assert mgr.set_autonomy("plan") == "plan"
    assert mgr.mode == PermissionMode.ASK
    assert mgr.set_autonomy("full") == "full"
    assert mgr.autonomy == "full"


def test_describe_request_shows_command_cwd_risk_reason() -> None:
    mgr = PermissionManager(config=Config(workspace_root="/proj"))
    detail = mgr.describe_request("run_command", {"command": "rm -rf build"})
    assert detail["command"] == "rm -rf build"
    assert detail["cwd"] == "/proj"
    assert detail["risk"] == "HIGH"
    assert detail["reason"]
    assert detail["autonomy"] == mgr.autonomy
