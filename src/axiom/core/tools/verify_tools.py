"""Model-facing verification tools (§34): run_tests / run_linter / build_project / verify_changes.

Unlike ``run_command`` (arbitrary shell), these tools run only fixed internal
commands: the stack is detected from the workspace (python / node / rust), the
right command is chosen and executed in the workspace root, and the output is
parsed into a structured result (counts, failures, tails).

``verify_changes`` plans the *minimal* pipeline from the git diff — heavy
checks run only when the diff touches what they check — and executes it through
:class:`axiom.core.verify.VerificationLoop` so build → test → lint stops at the
first failure exactly like the editor loop does.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from axiom.core.tools.base import (
    RISK_MEDIUM,
    ToolDefinition,
    ToolPermission,
    ToolResult,
)
from axiom.core.tools.filesystem import default_workspace_root
from axiom.core.tools.processes import command_argv, process_group_options, terminate_process_tree

RUN_TESTS_TOOL = "run_tests"
RUN_LINTER_TOOL = "run_linter"
BUILD_PROJECT_TOOL = "build_project"
VERIFY_CHANGES_TOOL = "verify_changes"

VERIFY_TOOL_NAMES: frozenset[str] = frozenset({
    RUN_TESTS_TOOL, RUN_LINTER_TOOL, BUILD_PROJECT_TOOL, VERIFY_CHANGES_TOOL,
})

MAX_OUTPUT_CHARS = 12_000
#: Per-step time budgets for the ``verify_changes`` pipeline.
STEP_TIMEOUTS = {"build": 600.0, "test": 300.0, "lint": 120.0}

#: Source extensions that make a lint/test run worthwhile.
CODE_EXTS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".rs", ".go",
    ".java", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".sh",
    ".css", ".scss", ".html", ".vue", ".svelte",
}
#: Manifests whose change justifies a build step.
MANIFEST_NAMES = {
    "pyproject.toml", "package.json", "cargo.toml", "tsconfig.json",
    "setup.py", "setup.cfg", "requirements.txt", "poetry.lock",
    "package-lock.json", "cargo.lock", "pytest.ini", "tox.ini",
    "ruff.toml", ".ruff.toml", "eslint.config.js", "eslint.config.mjs",
}


def _is_test_file(path: str) -> bool:
    norm = path.replace("\\", "/").lower()
    base = norm.rsplit("/", 1)[-1]
    return (
        base.startswith("test_")
        or base.endswith(("_test.py", "_test.js", "_test.ts", "_test.tsx",
                          ".test.js", ".test.ts", ".test.tsx", "_spec.js", "_spec.ts"))
        or norm.startswith("tests/")
        or "/tests/" in norm
        or "/__tests__/" in norm
    )


def _is_manifest(path: str) -> bool:
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower() in MANIFEST_NAMES


def _tail(text: str, lines: int = 40) -> str:
    parts = text.splitlines()
    return "\n".join(parts[-lines:])


def _failures(output: str, limit: int = 15) -> list[str]:
    """Lines that look like a failure across pytest / cargo / npm / ruff."""
    found: list[str] = []
    for line in output.splitlines():
        s = line.strip()
        if (
            s.startswith(("FAILED ", "ERROR ", "error[", "error:"))
            or "AssertionError" in s
            or "panicked at" in s
            or s.startswith(("F ", "FAIL "))
        ):
            found.append(s[:400])
    return found[:limit]


def _diagnostics(output: str, limit: int = 30) -> list[dict]:
    """Extract real file/line/message evidence without inventing coordinates."""
    found: list[dict] = []
    seen: set[tuple[str, int, str]] = set()
    patterns = (
        # pytest: tests/test_x.py:17: AssertionError: ...
        re.compile(r"^([^:\s]+\.py):(\d+):\s*(.+)$"),
        # Ruff: --> src/file.py:17:8
        re.compile(r"^\s*-->\s+([^:\s]+\.py):(\d+):\d+\s*$"),
        # tsc: src/file.ts(17,8): error TS...
        re.compile(r"^([^()\s]+\.[jt]sx?)\((\d+),\d+\):\s*(.+)$"),
        # Rust: --> src/lib.rs:17:8
        re.compile(r"^\s*-->\s+([^:\s]+\.rs):(\d+):\d+\s*$"),
    )
    lines = output.splitlines()
    for index, line in enumerate(lines):
        for pattern in patterns:
            match = pattern.match(line.strip())
            if match is None:
                continue
            path, line_no = match.group(1), int(match.group(2))
            message = match.group(3).strip() if match.lastindex == 3 else ""
            if not message:
                message = next((s.strip() for s in lines[index + 1:index + 4] if s.strip()), "Diagnostic")
            key = (path, line_no, message)
            if key not in seen:
                seen.add(key)
                found.append({"file": path, "line": line_no, "message": message[:400]})
            break
        if len(found) >= limit:
            break
    return found


def _counts(output: str, kind: str) -> dict:
    """Test counts — pytest/vitest/jest wording plus cargo's ``test result:``."""
    if kind == "rust":
        m = re.search(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) skipped", output)
        if m:
            return {"passed": int(m.group(1)), "failed": int(m.group(2)),
                    "skipped": int(m.group(3)), "errors": 0}
    out: dict = {"passed": None, "failed": None, "skipped": None, "errors": None}
    for key, pat in (
        ("passed", r"(\d+) passed"),
        ("failed", r"(\d+) failed"),
        ("skipped", r"(\d+) skipped"),
        ("errors", r"(\d+) error"),
    ):
        m = re.search(pat, output)
        if m:
            out[key] = int(m.group(1))
    return out


class VerificationTools:
    """Fixed test/lint/build commands in the workspace root."""

    def __init__(self, root: Path | None = None, enabled: bool = True) -> None:
        self.root = (root or default_workspace_root()).resolve()
        self.enabled = enabled
        self.on_process = None

    def set_root(self, root: Path) -> None:
        self.root = root.resolve()

    def _permission_for(self, name: str, args: dict) -> ToolPermission:
        return ToolPermission.ALWAYS if self.enabled else ToolPermission.NEVER

    def register(self, registry) -> None:
        for definition, handler in (
            (self._run_tests_definition(), self._run_tests),
            (self._run_linter_definition(), self._run_linter),
            (self._build_definition(), self._build_project),
            (self._verify_changes_definition(), self._verify_changes),
        ):
            registry.register(definition, handler, permission_for=self._permission_for)

    # ---------------------------------------------------------- definitions
    def _run_tests_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=RUN_TESTS_TOOL,
            description=(
                "Run the project's test suite (pytest / npm test / cargo test — "
                "auto-detected) and return parsed results: passed/failed counts, "
                "failure lines and an output tail."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Optional file or directory to limit the run to.",
                    },
                },
                "required": [],
            },
            permission=ToolPermission.ALWAYS,  # per-call: NEVER when disabled
            risk=RISK_MEDIUM,
            timeout=STEP_TIMEOUTS["test"],
            max_output=MAX_OUTPUT_CHARS,
            cancellable=True,
            workspace_scoped=True,
        )

    def _run_linter_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=RUN_LINTER_TOOL,
            description=(
                "Run the project's configured linter (ruff for Python, "
                "npm run lint / tsc --noEmit for JS/TS, cargo check for Rust) "
                "and return parsed diagnostics."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            permission=ToolPermission.ALWAYS,
            risk=RISK_MEDIUM,
            timeout=STEP_TIMEOUTS["lint"],
            max_output=MAX_OUTPUT_CHARS,
            cancellable=True,
            workspace_scoped=True,
        )

    def _build_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=BUILD_PROJECT_TOOL,
            description=(
                "Build the project (compileall for Python, npm run build for "
                "JS/TS, cargo build for Rust) and report compile errors."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            permission=ToolPermission.ALWAYS,
            risk=RISK_MEDIUM,
            timeout=STEP_TIMEOUTS["build"],
            max_output=MAX_OUTPUT_CHARS,
            cancellable=True,
            workspace_scoped=True,
        )

    def _verify_changes_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=VERIFY_CHANGES_TOOL,
            description=(
                "Verify uncommitted changes: inspect the git diff, plan the "
                "minimal build/test/lint pipeline for exactly those files and "
                "run it, stopping at the first failure. Returns a structured "
                "report with per-step status."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            permission=ToolPermission.ALWAYS,
            risk=RISK_MEDIUM,
            timeout=STEP_TIMEOUTS["build"] + STEP_TIMEOUTS["test"] + STEP_TIMEOUTS["lint"],
            max_output=MAX_OUTPUT_CHARS,
            cancellable=True,
            workspace_scoped=True,
        )

    # -------------------------------------------------------------- detect
    def detect(self) -> dict:
        """Stack + concrete commands for this workspace (cheap filesystem probe)."""
        root = self.root
        if (root / "Cargo.toml").is_file():
            return {"kind": "rust", "test": "cargo test --quiet",
                    "lint": "cargo check", "build": "cargo build --quiet"}
        pkg = root / "package.json"
        if pkg.is_file():
            scripts: dict = {}
            try:
                scripts = (json.loads(pkg.read_text(encoding="utf-8")) or {}).get("scripts") or {}
            except (OSError, ValueError):
                scripts = {}
            test_cmd = None
            test_script = str(scripts.get("test") or "")
            if test_script and "no test specified" not in test_script:
                test_cmd = "npm test --silent"
            lint_cmd = None
            if scripts.get("lint"):
                lint_cmd = "npm run lint"
            elif (root / "tsconfig.json").is_file():
                lint_cmd = "npx tsc --noEmit"
            build_cmd = "npm run build" if scripts.get("build") else None
            return {"kind": "node", "test": test_cmd, "lint": lint_cmd, "build": build_cmd}
        # --- Python -------------------------------------------------------
        pyproject = root / "pyproject.toml"
        pyproject_text = ""
        try:
            pyproject_text = pyproject.read_text(encoding="utf-8") if pyproject.is_file() else ""
        except OSError:
            pyproject_text = ""
        has_tests = bool(
            (root / "pytest.ini").is_file()
            or (root / "conftest.py").is_file()
            or "[tool.pytest" in pyproject_text
            or any(root.glob("tests/test_*.py"))
            or any(root.glob("test_*.py"))
        )
        test_cmd = "python -m pytest -q --tb=short" if has_tests else None
        if "[tool.ruff" in pyproject_text or (root / "ruff.toml").is_file() or (root / ".ruff.toml").is_file():
            lint_cmd = "ruff check ."
        elif "[tool.mypy" in pyproject_text or (root / "mypy.ini").is_file():
            lint_cmd = "python -m mypy ."
        else:
            lint_cmd = None
        # Syntax build: first-level packages plus src/ — never the whole root
        # (venv/site-packages must not be walked).
        pkg_dirs = {
            d.name for d in root.iterdir()
            if d.is_dir() and (d / "__init__.py").is_file()
            and d.name not in {"venv", ".venv", "node_modules", "__pycache__"}
        }
        if (root / "src").is_dir():
            pkg_dirs.add("src")
        build_cmd = (
            f"python -m compileall -q {' '.join(sorted(pkg_dirs))}"
            if pkg_dirs else None
        )
        return {"kind": "python", "test": test_cmd, "lint": lint_cmd, "build": build_cmd}

    # --------------------------------------------------------------- exec
    async def _exec(self, command: str, timeout: float) -> dict:
        started = time.monotonic()
        base: dict = {"command": command, "output": "", "exit_code": None,
                      "duration_ms": 0, "timed_out": False}
        try:
            proc = await asyncio.create_subprocess_exec(
                *command_argv(command),
                cwd=self.root,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "CI": "1", "TERM": "dumb"},
                **process_group_options(),
            )
        except (OSError, ValueError) as exc:
            base["error"] = f"Cannot execute: {exc}"
            return base
        if self.on_process:
            self.on_process({"pid": proc.pid, "command": command[:2000], "state": "running", "started_at": time.time()})
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            await terminate_process_tree(proc)
            if self.on_process:
                self.on_process({"pid": proc.pid, "state": "timeout", "returncode": proc.returncode})
            base["error"] = f"Command timed out after {timeout:.0f}s"
            base["timed_out"] = True
            base["duration_ms"] = int((time.monotonic() - started) * 1000)
            return base
        except asyncio.CancelledError:
            await terminate_process_tree(proc)
            if self.on_process:
                self.on_process({"pid": proc.pid, "state": "cancelled", "returncode": proc.returncode})
            raise
        if self.on_process:
            self.on_process({"pid": proc.pid, "state": "exited", "returncode": proc.returncode})
        text = out.decode("utf-8", errors="replace")
        err_text = err.decode("utf-8", errors="replace")
        body = text
        if err_text.strip():
            body = f"{body}\n[stderr]\n{err_text}".strip()
        if len(body) > MAX_OUTPUT_CHARS:
            body = body[:MAX_OUTPUT_CHARS] + "\n… truncated"
        base.update(
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            output=body,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return base

    # ------------------------------------------------------------ handlers
    async def _run_tests(self, path: str | None = None) -> ToolResult:
        guard = self._guard(RUN_TESTS_TOOL)
        if guard:
            return guard
        info = self.detect()
        cmd = info.get("test")
        if not cmd:
            return ToolResult(
                name=RUN_TESTS_TOOL, ok=True,
                content="No test suite configured for this project",
                data={"status": "no_tests", "kind": info["kind"]},
            )
        if path:
            if info["kind"] == "node":
                cmd = f"{cmd} -- {path}"
            elif info["kind"] == "python":
                cmd = f"{cmd} {path}"
            # cargo test takes a name filter, not a path — ignore for rust.
        res = await self._exec(cmd, timeout=STEP_TIMEOUTS["test"])
        if res.get("error"):
            status = "timeout" if res.get("timed_out") else "error"
            return ToolResult(name=RUN_TESTS_TOOL, ok=False, error=res["error"],
                              data={"status": status, "command": cmd})
        counts = _counts(res["output"], info["kind"])
        ok = bool(res.get("ok"))
        data = {
            "status": "passed" if ok else "failed",
            "command": cmd,
            "kind": info["kind"],
            "exit_code": res["exit_code"],
            "duration_ms": res["duration_ms"],
            **counts,
            "failures": _failures(res["output"]),
            "diagnostics": _diagnostics(res["output"]),
        }
        parts = []
        if counts["passed"] is not None:
            parts.append(f"{counts['passed']} passed")
        if counts["failed"]:
            parts.append(f"{counts['failed']} failed")
        if counts["errors"]:
            parts.append(f"{counts['errors']} errors")
        if counts["skipped"]:
            parts.append(f"{counts['skipped']} skipped")
        summary = f"Tests {'PASSED' if ok else 'FAILED'}"
        if parts:
            summary += f" ({', '.join(parts)})"
        summary += f" in {res['duration_ms'] / 1000:.1f}s — {cmd}"
        body = summary
        if data["failures"]:
            body += "\nFailures:\n" + "\n".join(data["failures"][:10])
        body += "\n--- output ---\n" + _tail(res["output"])
        return ToolResult(name=RUN_TESTS_TOOL, ok=ok,
                          content=body[:MAX_OUTPUT_CHARS],
                          error=None if ok else "Tests failed", data=data)

    async def _run_linter(self) -> ToolResult:
        guard = self._guard(RUN_LINTER_TOOL)
        if guard:
            return guard
        info = self.detect()
        cmd = info.get("lint")
        if not cmd:
            return ToolResult(
                name=RUN_LINTER_TOOL, ok=True,
                content="No linter configured for this project",
                data={"status": "no_linter", "kind": info["kind"]},
            )
        res = await self._exec(cmd, timeout=STEP_TIMEOUTS["lint"])
        if res.get("error"):
            status = "timeout" if res.get("timed_out") else "error"
            return ToolResult(name=RUN_LINTER_TOOL, ok=False, error=res["error"],
                              data={"status": status, "command": cmd})
        ok = bool(res.get("ok"))
        problems = _failures(res["output"], limit=30)
        data = {
            "status": "passed" if ok else "failed",
            "command": cmd,
            "kind": info["kind"],
            "exit_code": res["exit_code"],
            "duration_ms": res["duration_ms"],
            "problems": problems,
            "diagnostics": _diagnostics(res["output"]),
        }
        body = f"Lint {'PASSED' if ok else 'FAILED'} in {res['duration_ms'] / 1000:.1f}s — {cmd}"
        if problems:
            body += "\n" + "\n".join(problems[:20])
        elif not ok:
            body += "\n" + _tail(res["output"], 30)
        return ToolResult(name=RUN_LINTER_TOOL, ok=ok, content=body[:MAX_OUTPUT_CHARS],
                          error=None if ok else "Lint failed", data=data)

    async def _build_project(self) -> ToolResult:
        guard = self._guard(BUILD_PROJECT_TOOL)
        if guard:
            return guard
        info = self.detect()
        cmd = info.get("build")
        if not cmd:
            return ToolResult(
                name=BUILD_PROJECT_TOOL, ok=True,
                content="Nothing to build for this project",
                data={"status": "no_build", "kind": info["kind"]},
            )
        res = await self._exec(cmd, timeout=STEP_TIMEOUTS["build"])
        if res.get("error"):
            status = "timeout" if res.get("timed_out") else "error"
            return ToolResult(name=BUILD_PROJECT_TOOL, ok=False, error=res["error"],
                              data={"status": status, "command": cmd})
        ok = bool(res.get("ok"))
        problems = _failures(res["output"], limit=30)
        data = {
            "status": "passed" if ok else "failed",
            "command": cmd,
            "kind": info["kind"],
            "exit_code": res["exit_code"],
            "duration_ms": res["duration_ms"],
            "problems": problems,
            "diagnostics": _diagnostics(res["output"]),
        }
        body = f"Build {'PASSED' if ok else 'FAILED'} in {res['duration_ms'] / 1000:.1f}s — {cmd}"
        if not ok:
            body += "\n" + ((problems and "\n".join(problems[:20])) or _tail(res["output"], 40))
        return ToolResult(name=BUILD_PROJECT_TOOL, ok=ok, content=body[:MAX_OUTPUT_CHARS],
                          error=None if ok else "Build failed", data=data)

    # ------------------------------------------------------- verify_changes
    async def _git(self, *args: str) -> tuple[bool, str]:
        """Run a read-only git command; (False, '') when not a repository."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", str(self.root), *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                **process_group_options(),
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            except (TimeoutError, asyncio.CancelledError):
                await terminate_process_tree(proc)
                raise
        except (OSError, TimeoutError):
            return False, ""
        if proc.returncode != 0:
            return False, ""
        return True, out.decode("utf-8", errors="replace")

    def _plan(self, changed: list[str]) -> list[tuple[str, str]]:
        """Minimal pipeline for exactly these files (§34: no unrelated checks)."""
        info = self.detect()
        tests_changed = any(_is_test_file(f) for f in changed)
        manifest_changed = any(_is_manifest(f) for f in changed)
        source_changed = any(Path(f).suffix.lower() in CODE_EXTS for f in changed)
        steps: list[tuple[str, str]] = []
        if manifest_changed and info.get("build"):
            steps.append(("build", info["build"]))
        relevant = tests_changed or source_changed
        if relevant and info.get("test"):
            steps.append(("test", info["test"]))
        if relevant and info.get("lint"):
            steps.append(("lint", info["lint"]))
        return steps

    async def _verify_changes(self) -> ToolResult:
        guard = self._guard(VERIFY_CHANGES_TOOL)
        if guard:
            return guard
        ok_status, status_out = await self._git("status", "--porcelain")
        if not ok_status:
            return ToolResult(
                name=VERIFY_CHANGES_TOOL, ok=True,
                content="Not a git repository — nothing to verify against",
                data={"status": "no_git", "changed": [], "steps": []},
            )
        changed = [line[3:].strip().strip('"') for line in status_out.splitlines()
                   if line.strip()]
        if not changed:
            return ToolResult(
                name=VERIFY_CHANGES_TOOL, ok=True,
                content="Working tree clean — nothing to verify",
                data={"status": "clean", "changed": [], "steps": []},
            )
        from axiom.core.verify import VerificationLoop, VerifyStep

        info = self.detect()
        plan = self._plan(changed)
        if not plan:
            return ToolResult(
                name=VERIFY_CHANGES_TOOL, ok=True,
                content=(
                    f"{len(changed)} changed file(s), none of them need "
                    "build/test/lint (docs, config or non-code)."
                ),
                data={"status": "no_checks", "changed": changed[:40], "steps": []},
            )

        async def runner(*, command: str, step: str) -> dict:
            res = await self._exec(command, timeout=STEP_TIMEOUTS.get(step, 300.0))
            if res.get("error"):
                return {"ok": False, "output": res["error"], "exit_code": res.get("exit_code")}
            return {"ok": res.get("ok") is True and res.get("exit_code") == 0,
                    "output": res.get("output", ""), "exit_code": res.get("exit_code")}

        report = await VerificationLoop(runner).run(
            [VerifyStep(name, command) for name, command in plan],
            kind=info["kind"],
        )
        steps_data = [
            {"name": s.name, "command": s.command, "ok": s.ok, "exit_code": s.exit_code,
             "failures": _failures(s.output, limit=10),
             "diagnostics": _diagnostics(s.output, limit=10),
             "tail": _tail(s.output, 15)[:2000]}
            for s in report.steps
        ]
        failed = next((s.name for s in report.steps if not s.ok), None)
        lines = [report.summary(), f"changed: {len(changed)} file(s)"]
        for s in report.steps:
            mark = "OK" if s.ok else "FAIL"
            lines.append(f"[{mark}] {s.name}: {s.command}")
            if not s.ok:
                lines.append(_tail(s.output, 25))
        data = {
            "status": "passed" if report.ok else "failed",
            "kind": info["kind"],
            "changed": changed[:40],
            "steps": steps_data,
            "failed_step": failed,
        }
        return ToolResult(
            name=VERIFY_CHANGES_TOOL, ok=report.ok,
            content="\n".join(lines)[:MAX_OUTPUT_CHARS],
            error=None if report.ok else f"{failed} step failed",
            data=data,
        )


    def _guard(self, name: str) -> ToolResult | None:
        if not self.enabled:
            return ToolResult(
                name=name, ok=False,
                error="Verification tools are disabled (terminal access is off)",
            )
        return None
