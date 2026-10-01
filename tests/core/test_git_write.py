"""Tests for the user-initiated git write helpers (stage/unstage/commit/diff)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from axiom.core.tools.base import ToolPermission
from axiom.core.tools.git_tools import (
    GitTools,
    git_commit,
    git_diff_file,
    git_revert,
    git_stage,
    git_switch,
    git_unstage,
)
from axiom.core.tools.registry import ToolRegistry


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    git(tmp_path, "add", "a.txt")
    git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def test_stage_and_commit(repo: Path):
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    git_stage(repo, ["a.txt"])
    assert "a.txt" in git(repo, "diff", "--cached", "--name-only")
    out = git_commit(repo, "change a")
    assert out
    assert "two" in (repo / "a.txt").read_text(encoding="utf-8")
    assert "change a" in git(repo, "log", "-1", "--pretty=%s")


async def test_agent_git_add_requires_approval_and_explicit_file(repo: Path):
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    registry = ToolRegistry()
    GitTools(repo).register(registry)
    assert registry.permission_for("git_add", {"paths": ["a.txt"]}) is ToolPermission.ASK
    assert "git_commit" in registry.names  # present, but approval + reviewed-diff gated
    assert "git_push" not in registry.names  # push stays manual, HIGH risk

    denied = await registry.execute("git_add", {"paths": ["a.txt"]})
    assert not denied.ok and denied.data == {"permission": "ask"}
    assert not git(repo, "diff", "--cached", "--name-only").strip()

    accepted = await registry.execute("git_add", {"paths": ["a.txt"]}, approved=True)
    assert accepted.ok, accepted.error
    assert git(repo, "diff", "--cached", "--name-only").strip() == "a.txt"


async def test_agent_git_commit_requires_reviewed_diff_and_fresh_consent(repo: Path):
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    registry = ToolRegistry()
    tools = GitTools(repo)
    tools.register(registry)

    # Stage the change, then try to commit without a reviewed diff hash.
    git_stage(repo, ["a.txt"])
    expected = tools._staged_diff_hash()

    denied = await registry.execute("git_commit", {"message": "change a", "reviewed_diff": expected})
    assert not denied.ok and denied.data == {"permission": "ask"}
    assert "change a" not in git(repo, "log", "-1", "--pretty=%s")

    # Wrong (stale) hash is rejected even with approval.
    wrong = await registry.execute("git_commit", {"message": "change a", "reviewed_diff": "deadbeef"},
                                   approved=True)
    assert not wrong.ok and "stale" in (wrong.error or "")
    assert "change a" not in git(repo, "log", "-1", "--pretty=%s")

    # Correct reviewed hash + explicit approval commits the staged diff.
    accepted = await registry.execute("git_commit", {"message": "change a", "reviewed_diff": expected},
                                      approved=True)
    assert accepted.ok, accepted.error
    assert "change a" in git(repo, "log", "-1", "--pretty=%s")


async def test_agent_git_add_rejects_stage_all_and_workspace_escape(repo: Path):
    registry = ToolRegistry()
    GitTools(repo).register(registry)
    for paths in ([], ["."], ["-A"], ["../outside.txt"], [".git"]):
        result = await registry.execute("git_add", {"paths": paths}, approved=True)
        assert not result.ok, paths
    assert not git(repo, "diff", "--cached", "--name-only").strip()


def test_unstage(repo: Path):
    (repo / "a.txt").write_text("three\n", encoding="utf-8")
    git_stage(repo, ["a.txt"])
    git_unstage(repo, ["a.txt"])
    assert not git(repo, "diff", "--cached", "--name-only").strip()


def test_empty_commit_message_rejected(repo: Path):
    with pytest.raises(ValueError, match="empty"):
        git_commit(repo, "   ")


def test_path_escape_rejected(repo: Path):
    with pytest.raises(ValueError, match="escapes"):
        git_stage(repo, ["../outside.txt"])


def test_diff_file_shows_change(repo: Path):
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    diff = git_diff_file(repo, "a.txt")
    assert "+changed" in diff
    assert "-one" in diff


def test_diff_untracked_file_synthesized(repo: Path):
    (repo / "fresh.txt").write_text("brand new\n", encoding="utf-8")
    diff = git_diff_file(repo, "fresh.txt")
    assert "+++ b/fresh.txt" in diff
    assert "+brand new" in diff


def test_switch_branch(repo: Path):
    initial = git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    git(repo, "checkout", "-b", "feature")
    git(repo, "checkout", initial)
    out = git_switch(repo, "feature")
    assert out
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "feature"


def test_switch_rejects_bad_branch_names(repo: Path):
    with pytest.raises(ValueError, match=r"[Ee]mpty"):
        git_switch(repo, "   ")
    with pytest.raises(ValueError, match="Invalid"):
        git_switch(repo, "--force")


def test_switch_unknown_branch_reports_git_error(repo: Path):
    with pytest.raises(ValueError):
        git_switch(repo, "no-such-branch")


def test_git_revert_tracked_file(repo: Path):
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    out = git_revert(repo, "a.txt")
    assert out
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"


def test_git_revert_untracked_file(repo: Path):
    (repo / "fresh.txt").write_text("new\n", encoding="utf-8")
    out = git_revert(repo, "fresh.txt")
    assert "untracked" in out
    assert not (repo / "fresh.txt").exists()


def test_git_revert_rejects_directory(repo: Path):
    (repo / "sub").mkdir()
    with pytest.raises(ValueError, match="individual files"):
        git_revert(repo, "sub")


async def test_git_graph_lists_commits(repo: Path):
    tools = GitTools(repo)
    res = await tools._graph(10)
    assert res.ok is True
    assert "initial" in res.content


async def test_agent_git_unstage_requires_approval_and_explicit_files(repo: Path):
    (repo / "a.txt").write_text("three\n", encoding="utf-8")
    registry = ToolRegistry()
    GitTools(repo).register(registry)
    assert registry.permission_for("git_unstage", {"paths": ["a.txt"]}) is ToolPermission.ASK

    git_stage(repo, ["a.txt"])
    # no approval → permission ask, still staged
    denied = await registry.execute("git_unstage", {"paths": ["a.txt"]})
    assert not denied.ok and denied.data == {"permission": "ask"}
    assert git(repo, "diff", "--cached", "--name-only").strip() == "a.txt"

    # empty list is rejected, never unstage-all
    empty = await registry.execute("git_unstage", {"paths": []}, approved=True)
    assert not empty.ok and "Explicit paths" in (empty.error or "")
    assert git(repo, "diff", "--cached", "--name-only").strip() == "a.txt"

    # explicit path + approval really unstages
    accepted = await registry.execute("git_unstage", {"paths": ["a.txt"]}, approved=True)
    assert accepted.ok, accepted.error
    assert not git(repo, "diff", "--cached", "--name-only").strip()
