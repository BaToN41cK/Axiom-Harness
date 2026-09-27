"""Verification tools (§34): stack detection, real runs, planning, registry wiring."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from axiom.core.tools.base import ToolPermission
from axiom.core.tools.registry import ToolRegistry
from axiom.core.tools.verify_tools import (
    BUILD_PROJECT_TOOL,
    RUN_LINTER_TOOL,
    RUN_TESTS_TOOL,
    VERIFY_CHANGES_TOOL,
    VERIFY_TOOL_NAMES,
    VerificationTools,
)


@pytest.fixture()
def project(tmp_path: Path) -> VerificationTools:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n[tool.ruff]\n", encoding="utf-8"
    )
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text(
        "from app import VALUE\n\n\ndef test_ok():\n    assert VALUE == 1\n",
        encoding="utf-8",
    )
    return VerificationTools(root=tmp_path)


# ------------------------------------------------------------------ detect
def test_detect_python(project: VerificationTools) -> None:
    info = project.detect()
    assert info["kind"] == "python"
    assert info["test"] and "pytest" in info["test"]
    assert info["lint"] == "ruff check ."
    assert info["build"] and "compileall" in info["build"] and "app" in info["build"]


def test_detect_node(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "jest", "lint": "eslint .", "build": "tsc"}}',
        encoding="utf-8",
    )
    vt = VerificationTools(root=tmp_path)
    info = vt.detect()
    assert info == {"kind": "node", "test": "npm test --silent",
                    "lint": "npm run lint", "build": "npm run build"}


def test_detect_empty_dir(tmp_path: Path) -> None:
    info = VerificationTools(root=tmp_path).detect()
    assert info["kind"] == "python"
    assert info["test"] is None and info["lint"] is None and info["build"] is None


# ------------------------------------------------------------------- runs
def test_diagnostics_extract_real_file_line_message():
    from axiom.core.tools.verify_tools import _diagnostics

    output = ("tests/test_calc.py:17: AssertionError: wrong value\n"
              "src/ui.ts(9,3): error TS2322: wrong type\n"
              "--> src/main.rs:21:7\nerror: mismatched types\n"
              "random line without a source\n")
    found = _diagnostics(output)
    assert found[0] == {"file": "tests/test_calc.py", "line": 17, "message": "AssertionError: wrong value"}
    assert found[1] == {"file": "src/ui.ts", "line": 9, "message": "error TS2322: wrong type"}
    assert found[2]["file"] == "src/main.rs" and found[2]["line"] == 21
    assert len(found) == 3


async def test_verification_loop_rejects_nonzero_exit_even_if_runner_claims_ok():
    from axiom.core.verify import VerificationLoop, VerifyStep

    async def runner(**kwargs):
        return {"ok": True, "exit_code": 1, "output": "failed assertion"}

    report = await VerificationLoop(runner).run([VerifyStep("test", "pytest -q")])
    assert report.ok is False
    assert "exit code 1" in report.errors[0]


async def test_verify_changes_requires_real_zero_exit(project: VerificationTools, tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
                    "commit", "-m", "baseline"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "app" / "__init__.py").write_text("VALUE = 2\n", encoding="utf-8")

    async def contradictory(command, timeout):
        return {"ok": True, "exit_code": 1, "output": "failed", "duration_ms": 1}

    monkeypatch.setattr(project, "_exec", contradictory)
    result = await project._verify_changes()
    assert result.ok is False
    assert result.data["status"] == "failed"
    assert result.data["failed_step"] == "test"


async def test_run_tests_pass(project: VerificationTools) -> None:
    res = await project._run_tests()
    assert res.ok, res.error
    assert res.data and res.data["status"] == "passed"
    assert res.data["passed"] == 1 and not res.data["failed"]


async def test_run_tests_fail(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_bad.py").write_text(
        "def test_bad():\n    assert 1 == 2\n", encoding="utf-8"
    )
    vt = VerificationTools(root=tmp_path)
    res = await vt._run_tests()
    assert not res.ok
    assert res.data and res.data["status"] == "failed" and res.data["failed"] == 1
    assert res.data["failures"]


async def test_run_linter_and_build(project: VerificationTools) -> None:
    lint = await project._run_linter()
    assert lint.ok, lint.content
    assert lint.data and lint.data["status"] == "passed"

    build = await project._build_project()
    assert build.ok, build.content
    assert build.data and build.data["status"] == "passed"


async def test_run_tests_no_suite(tmp_path: Path) -> None:
    res = await VerificationTools(root=tmp_path)._run_tests()
    assert res.ok and res.data and res.data["status"] == "no_tests"


async def test_disabled_guard(tmp_path: Path) -> None:
    vt = VerificationTools(root=tmp_path, enabled=False)
    res = await vt._run_tests()
    assert not res.ok and "disabled" in (res.error or "")


# ---------------------------------------------------------- verify_changes
def test_plan_is_minimal(project: VerificationTools) -> None:
    assert [n for n, _ in project._plan(["app/__init__.py"])] == ["test", "lint"]
    assert [n for n, _ in project._plan(["tests/test_ok.py"])] == ["test", "lint"]
    assert [n for n, _ in project._plan(["pyproject.toml"])] == ["build"]
    assert project._plan(["README.md"]) == []


async def test_verify_changes_no_git(project: VerificationTools) -> None:
    res = await project._verify_changes()
    assert res.ok and res.data and res.data["status"] == "no_git"


async def test_verify_changes_runs_pipeline(project: VerificationTools, tmp_path: Path) -> None:
    def git(*args: str) -> None:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", *args], cwd=tmp_path, check=True,
                       capture_output=True, env=env)

    git("init")
    git("add", ".")
    git("commit", "-m", "init")
    (tmp_path / "app" / "__init__.py").write_text(
        "VALUE = 1\n\n\ndef helper():\n    return 42\n", encoding="utf-8"
    )

    res = await project._verify_changes()
    assert res.ok, res.content
    assert res.data and res.data["status"] == "passed"
    assert [s["name"] for s in res.data["steps"]] == ["test", "lint"]
    assert all(s["ok"] for s in res.data["steps"])
    assert res.data["changed"] == ["app/__init__.py"]


# ---------------------------------------------------------------- registry
def test_registry_wiring() -> None:
    registry = ToolRegistry()
    VerificationTools().register(registry)
    names = {s["function"]["name"] for s in registry.schemas()}
    assert names >= VERIFY_TOOL_NAMES
    for schema in registry.schemas():
        if schema["function"]["name"] in VERIFY_TOOL_NAMES:
            # Model-facing shape stays {name, description, parameters} —
            # metadata must not leak into the schema.
            assert set(schema["function"]) == {"name", "description", "parameters"}
    info = {d.name: d.meta() for d in registry.definitions()}
    for name in VERIFY_TOOL_NAMES:
        assert info[name]["risk"] == "medium"
        assert info[name]["workspace_scoped"] is True
    assert registry.permission_for(RUN_TESTS_TOOL, {}) == ToolPermission.ALWAYS

    disabled = ToolRegistry()
    VerificationTools(enabled=False).register(disabled)
    assert disabled.permission_for(BUILD_PROJECT_TOOL, {}) == ToolPermission.NEVER
    assert disabled.permission_for(VERIFY_CHANGES_TOOL, {}) == ToolPermission.NEVER
    assert disabled.permission_for(RUN_LINTER_TOOL, {}) == ToolPermission.NEVER

