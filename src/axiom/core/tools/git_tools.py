"""Git inspection plus approval-gated staging inside the workspace.

Commit and push remain user-only until the agent permission flow can prove
that the actual staged diff was reviewed and explicitly approved.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from axiom.core.tools.base import RISK_MEDIUM, RISK_SAFE, ToolDefinition, ToolPermission, ToolResult
from axiom.core.tools.filesystem import default_workspace_root

GIT_STATUS_TOOL = "git_status"
GIT_DIFF_TOOL = "git_diff"
GIT_LOG_TOOL = "git_log"
GIT_BRANCH_TOOL = "git_branch"
GIT_ADD_TOOL = "git_add"
GIT_COMMIT_TOOL = "git_commit"

GIT_TOOLS = (GIT_STATUS_TOOL, GIT_DIFF_TOOL, GIT_LOG_TOOL, GIT_BRANCH_TOOL,
             GIT_ADD_TOOL, GIT_COMMIT_TOOL)

_TIMEOUT = 15.0
_MAX_CHARS = 12_000


class GitTools:
    """Registers real, read-only git inspection tools."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_workspace_root()).resolve()

    def set_root(self, root: Path) -> None:
        self.root = root.resolve()

    # ------------------------------------------------------------- helpers

    def _run_git(self, args: list[str]) -> ToolResult:
        if not (self.root / ".git").exists():
            return ToolResult(name="git", ok=False, error="Not a git repository")
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                check=False,
            )
        except FileNotFoundError:
            return ToolResult(name="git", ok=False, error="git executable not found")
        except subprocess.SubprocessError as exc:
            return ToolResult(name="git", ok=False, error=f"git failed: {exc}")
        out = (proc.stdout or "")[:_MAX_CHARS]
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            return ToolResult(name="git", ok=False, error=err or f"git exit {proc.returncode}", content=out)
        return ToolResult(name="git", ok=True, content=out.strip() or "(clean)")

    def _def(self, name: str, desc: str, extra: dict | None = None) -> ToolDefinition:
        props: dict = {"type": "object", "properties": {}, "required": []}
        if extra:
            props["properties"] = extra
        return ToolDefinition(
            name=name, description=desc, parameters=props,
            permission=ToolPermission.ALWAYS,
            risk=RISK_SAFE,
            timeout=_TIMEOUT,
            max_output=_MAX_CHARS,
            workspace_scoped=True,
        )

    # ---------------------------------------------------------- registration

    def register(self, registry) -> None:
        registry.register(
            self._def(GIT_STATUS_TOOL, "Show `git status --short --branch` of the workspace repo."),
            self._status,
        )
        registry.register(
            self._def(GIT_DIFF_TOOL, "Show `git diff` (unstaged changes).", {"ref": {"type": "string"}}),
            self._diff,
        )
        registry.register(
            self._def(GIT_LOG_TOOL, "Show recent commits (`git log --oneline -n`).", {"limit": {"type": "integer"}}),
            self._log,
        )
        registry.register(
            self._def(GIT_BRANCH_TOOL, "Show current branch and all local branches."),
            self._branch,
        )
        registry.register(
            ToolDefinition(
                name=GIT_ADD_TOOL,
                description="Stage explicitly named workspace files for a user-reviewed diff; never stages all files.",
                parameters={"type": "object", "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                }, "required": ["paths"]},
                permission=ToolPermission.ASK, risk=RISK_MEDIUM, timeout=_TIMEOUT,
                max_output=1000, workspace_scoped=True,
            ),
            self._add,
        )
        registry.register(
            ToolDefinition(
                name=GIT_COMMIT_TOOL,
                description=("Commit the currently staged changes. Requires a reviewed_diff SHA-256 "
                             "of the real staged diff, shown to the user in the permission dialog; "
                             "fails if the staged diff changed after review."),
                parameters={"type": "object", "properties": {
                    "message": {"type": "string"},
                    "reviewed_diff": {"type": "string"},
                }, "required": ["message", "reviewed_diff"]},
                permission=ToolPermission.ASK, risk=RISK_MEDIUM, timeout=_TIMEOUT,
                max_output=2000, workspace_scoped=True,
            ),
            self._commit,
        )

    # -------------------------------------------------------------- handlers

    async def _status(self) -> ToolResult:
        res = self._run_git(["status", "--short", "--branch"])
        res.name = GIT_STATUS_TOOL
        return res

    async def _diff(self, ref: str | None = None) -> ToolResult:
        args = ["diff", "--no-color"]
        if ref and ref.strip():
            args.append(ref.strip())
        res = self._run_git(args)
        res.name = GIT_DIFF_TOOL
        return res

    async def _log(self, limit: int | None = None) -> ToolResult:
        n = max(1, min(int(limit or 10), 50))
        res = self._run_git(["log", f"-n{n}", "--oneline", "--decorate"])
        res.name = GIT_LOG_TOOL
        return res

    async def _branch(self) -> ToolResult:
        res = self._run_git(["branch", "--show-current"])
        if not res.ok:
            res.name = GIT_BRANCH_TOOL
            return res
        current = res.content.strip()
        all_branches = self._run_git(["branch", "--list"])
        body = f"Current: {current or '(detached)'}\n{all_branches.content}".strip()
        return ToolResult(name=GIT_BRANCH_TOOL, ok=True, content=body)

    async def _add(self, paths: list[str]) -> ToolResult:
        """Stage only explicit files, after the central approval boundary."""
        if not isinstance(paths, list) or not paths or any(not isinstance(path, str) or not path.strip()
                                                       for path in paths):
            return ToolResult(name=GIT_ADD_TOOL, ok=False, error="Explicit paths are required")
        try:
            for path in paths:
                target = _resolve_in_root(self.root, path)
                if target == self.root or target.is_dir() or path.strip() in {".", "-A", "--all"}:
                    return ToolResult(name=GIT_ADD_TOOL, ok=False, error="Only individual files may be staged")
            git_stage(self.root, paths)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return ToolResult(name=GIT_ADD_TOOL, ok=False, error=str(exc))
        return ToolResult(name=GIT_ADD_TOOL, ok=True, content=f"Staged {len(paths)} explicit path(s)")

    def _staged_diff(self) -> str:
        res = self._run_git(["diff", "--cached", "--no-color"])
        return res.content if res.ok else ""

    def _staged_diff_hash(self) -> str:
        return hashlib.sha256(self._staged_diff().encode("utf-8")).hexdigest()

    async def _commit(self, message: str, reviewed_diff: str) -> ToolResult:
        """Commit staged changes only when the reviewed diff is still current."""
        staged = self._staged_diff()
        if not staged.strip():
            return ToolResult(name=GIT_COMMIT_TOOL, ok=False, error="Nothing staged to commit")
        actual = hashlib.sha256(staged.encode("utf-8")).hexdigest()
        if str(reviewed_diff or "").strip() != actual:
            return ToolResult(
                name=GIT_COMMIT_TOOL, ok=False,
                error="Reviewed diff is stale: the staged changes differ from what was approved. "
                      "Review the current diff and provide its new hash.",
                data={"expected": actual},
            )
        try:
            output = git_commit(self.root, message)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return ToolResult(name=GIT_COMMIT_TOOL, ok=False, error=str(exc))
        return ToolResult(name=GIT_COMMIT_TOOL, ok=True, content=output)


# ---------------------------------------------------------------- user git ops
#
# GUI write operations keep their existing user-initiated helpers. The agent
# can only use the explicit-path, approval-gated git_add wrapper above. Commit
# and push remain user-only until reviewed-diff consent is enforceable.


def _resolve_in_root(root: Path, rel: str) -> Path:
    """Resolve ``rel`` strictly inside ``root`` or raise ValueError."""
    clean = (rel or "").strip()
    if not clean:
        raise ValueError("Path is empty")
    if any(part == ".." for part in clean.replace("\\", "/").split("/")):
        raise ValueError(f"Path escapes the repository: {rel}")
    full = (root / clean).resolve()
    if full != root and root not in full.parents:
        raise ValueError(f"Path escapes the repository: {rel}")
    return full


def git_stage(root: Path, paths: list[str]) -> str:
    """``git add`` the given workspace-relative paths. Returns git output."""
    if not (root / ".git").exists():
        raise ValueError("Not a git repository")
    resolved = [str(_resolve_in_root(root, p)) for p in paths] or ["-A"]
    proc = subprocess.run(
        ["git", "add", "--", *resolved],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError((proc.stderr or proc.stdout or "git add failed").strip())
    return proc.stdout.strip()


def git_unstage(root: Path, paths: list[str]) -> str:
    """``git restore --staged`` the given paths (all staged when empty)."""
    if not (root / ".git").exists():
        raise ValueError("Not a git repository")
    if paths:
        resolved = [str(_resolve_in_root(root, p)) for p in paths]
        args = ["git", "restore", "--staged", "--", *resolved]
    else:
        args = ["git", "reset", "--quiet"]
    proc = subprocess.run(
        args,
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError((proc.stderr or proc.stdout or "git reset failed").strip())
    return proc.stdout.strip()


def git_commit(root: Path, message: str, *, all: bool = False) -> str:
    """Commit staged changes (optionally staging everything first)."""
    if not (root / ".git").exists():
        raise ValueError("Not a git repository")
    clean = (message or "").strip()
    if not clean:
        raise ValueError("Commit message is empty")
    args = ["git", "commit", "-m", clean]
    if all:
        args.insert(2, "-a")
    proc = subprocess.run(
        args,
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError((proc.stderr or proc.stdout or "git commit failed").strip())
    return proc.stdout.strip() or "Committed."


def git_diff_file(root: Path, path: str = "") -> str:
    """Unified diff of one file (staged + unstaged vs HEAD), new files included."""
    if not (root / ".git").exists():
        raise ValueError("Not a git repository")
    target = str(_resolve_in_root(root, path)) if path else None
    args = ["git", "diff", "--no-color", "HEAD", "--"]
    if target:
        args.append(target)
    proc = subprocess.run(
        args,
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        check=False,
    )
    diff = proc.stdout
    if not diff.strip() and target:
        # Untracked file: synthesize a /dev/null → b/ unified diff.
        try:
            rel = Path(target).resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError("Path escapes the repository") from exc
        content = Path(target).read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        body = "\n".join(f"+{line}" for line in lines)
        diff = (
            f"--- /dev/null\n+++ b/{rel.as_posix()}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n{body}\n"
        )
    if proc.returncode != 0 and not diff.strip():
        raise ValueError((proc.stderr or "git diff failed").strip())
    return diff.rstrip() + "\n" if diff.strip() else ""


def git_switch(root: Path, branch: str) -> str:
    """``git switch`` to an existing local branch (user-initiated, §17)."""
    clean = (branch or "").strip()
    if not clean:
        raise ValueError("Branch name is empty")
    # A leading dash would make git parse the name as an option.
    if clean.startswith("-"):
        raise ValueError(f"Invalid branch name: {branch}")
    if not (root / ".git").exists():
        raise ValueError("Not a git repository")
    proc = subprocess.run(
        ["git", "switch", clean],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError((proc.stderr or proc.stdout or "git switch failed").strip())
    return proc.stdout.strip() or f"Switched to {clean}"
