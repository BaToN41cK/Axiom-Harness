"""Review must preserve user changes and fail before touching other files."""
import os
import subprocess
import sys

import pytest

from axiom.core.planner import Planner
from axiom.core.review import ReviewTransaction, review_lock
from axiom.core.tasks import Task, TaskState
from tests.core.test_orchestrator_runtime_a import _session
from tests.core.test_tasks import _runner


def review_fixture(tmp_path, monkeypatch):
    ws = tmp_path / "repo"
    ws.mkdir()
    session = _session(tmp_path, monkeypatch, ws)
    task = Task(goal="Review", state=TaskState.COMPLETED, scope=str(ws),
                file_baselines={"a.txt": "old\r\n", "b.txt": "before\n"},
                review_baselines={"a.txt": "new\r\n", "b.txt": "after\n"})
    for name, content in task.review_baselines.items():
        (ws / name).write_bytes(content.encode())
    session.task_store.save(task)
    return session, task, ws


@pytest.mark.parametrize("mutation", ["edit", "delete", "directory", "outside"])
def test_all_targets_validated_before_any_write(tmp_path, monkeypatch, mutation):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    b = ws / "b.txt"
    if mutation == "edit":
        b.write_bytes(b"user edit\n")
    elif mutation == "delete":
        b.unlink()
    elif mutation == "directory":
        b.unlink()
        b.mkdir()
    else:
        task.file_baselines["../outside"] = "original"
        task.review_baselines["../outside"] = "new"
        session.task_store.save(task)
    with pytest.raises(ValueError):
        session.task_review(task.id, "reject")
    assert (ws / "a.txt").read_bytes() == b"new\r\n"
    assert session.task_store.load(task.id).review_status == "pending"


def test_reject_preserves_line_endings_and_is_idempotent(tmp_path, monkeypatch):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    session.task_review(task.id, "reject")
    assert (ws / "a.txt").read_bytes() == b"old\r\n"
    assert (ws / "b.txt").read_bytes() == b"before\n"
    (ws / "a.txt").write_bytes(b"later edit")
    session.task_review(task.id, "reject")
    assert (ws / "a.txt").read_bytes() == b"later edit"
    with pytest.raises(ValueError, match="already been reviewed"):
        session.task_review(task.id, "accept")


def test_failure_rolls_back_previous_files_and_cleans_temporary_files(tmp_path, monkeypatch):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    link = os.link

    def fail_second(path, target):
        if target.name == "b.txt" and path.suffix == ".stage":
            raise OSError("disk failure")
        return link(path, target)

    monkeypatch.setattr(os, "link", fail_second)
    with pytest.raises(ValueError, match="pre-review file contents restored"):
        session.task_review(task.id, "reject")
    assert (ws / "a.txt").read_bytes() == b"new\r\n"
    assert (ws / "b.txt").read_bytes() == b"after\n"
    assert not list(ws.glob(".axiom-review-*"))
    assert session.task_store.load(task.id).review_status == "pending"


def test_rollback_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    session, task, _ws = review_fixture(tmp_path, monkeypatch)
    link = os.link

    def fail_after_first(path, target):
        if (target.name == "b.txt" and path.suffix == ".stage") or (
            target.name == "a.txt" and path.suffix == ".backup"
        ):
            raise OSError("disk failure")
        return link(path, target)

    monkeypatch.setattr(os, "link", fail_after_first)
    with pytest.raises(ValueError, match=r"manual recovery required for: a\.txt"):
        session.task_review(task.id, "reject")
    assert session.task_store.load(task.id).review_status == "pending"


@pytest.mark.parametrize("before,after", [(None, ""), ("", None), ("a\r\n", "b\n"), ("same", "same")])
def test_runner_captures_exact_snapshot_including_empty_and_unchanged_files(tmp_path, before, after):
    path = tmp_path / "a.txt"
    if before is not None:
        path.write_bytes(before.encode())
    runner = _runner(tmp_path, planner=Planner(None), execute=None, verify=None, workspace_root=tmp_path)
    task = Task(goal="Snapshot")
    runner._snapshot_paths(task, "write_file", {"path": "a.txt"})
    if after is None:
        path.unlink()
    else:
        path.write_bytes(after.encode())
    runner._record_file_diffs(task, "write_file", {"path": "a.txt"})
    runner.store.save(task)
    saved = runner.store.load(task.id)
    assert saved.file_baselines == {"a.txt": before}
    assert saved.review_baselines == {"a.txt": after}


def test_binary_result_cannot_be_mistaken_for_deleted_file(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"text")
    runner = _runner(tmp_path, planner=Planner(None), execute=None, verify=None, workspace_root=tmp_path)
    task = Task(goal="Snapshot")
    runner._snapshot_paths(task, "write_file", {"path": "a.txt"})
    path.write_bytes(b"\x00binary")
    runner._record_file_diffs(task, "write_file", {"path": "a.txt"})
    assert "a.txt" not in task.review_baselines
    assert "non-text" in task.diffs["a.txt"]


def _transaction_fixture(tmp_path, monkeypatch):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    transaction = ReviewTransaction.prepare(session.task_store, task, ws)
    transaction.stage()
    return session, task, ws, transaction


def test_review_journal_recovers_after_process_death_boundary(tmp_path, monkeypatch):
    session, task, ws, transaction = _transaction_fixture(tmp_path, monkeypatch)
    transaction.apply()  # Simulates a process dying before the Task JSON commit.
    assert (ws / "a.txt").read_bytes() == b"old\r\n"
    assert (ws / "b.txt").read_bytes() == b"before\n"
    assert session.task_store.load(task.id).review_status == "pending"

    restarted = ReviewTransaction.load(session.task_store, task, ws)
    assert restarted is not None and restarted.journal.state == "applying"
    restarted.recover()
    assert (ws / "a.txt").read_bytes() == b"new\r\n"
    assert (ws / "b.txt").read_bytes() == b"after\n"
    assert session.task_store.load_transaction(task.id) is None


def test_recovery_preserves_external_edit_and_requires_manual_recovery(tmp_path, monkeypatch):
    session, task, ws, transaction = _transaction_fixture(tmp_path, monkeypatch)
    transaction.apply()
    (ws / "a.txt").write_text("external edit\n", encoding="utf-8")
    restarted = ReviewTransaction.load(session.task_store, task, ws)
    assert restarted is not None
    with pytest.raises(ValueError, match="manual recovery required"):
        restarted.recover()
    assert (ws / "a.txt").read_text(encoding="utf-8") == "external edit\n"
    journal = session.task_store.load_transaction(task.id)
    assert journal["state"] == "recovery_required"
    assert "a.txt" in journal["error"]


def test_user_recovery_reports_conflicts_and_preserves_external_file(tmp_path, monkeypatch):
    session, task, ws, transaction = _transaction_fixture(tmp_path, monkeypatch)
    transaction.apply()
    (ws / "a.txt").unlink()
    (ws / "a.txt").write_bytes(b"external edit\n")
    with pytest.raises(ValueError, match="manual recovery required"):
        session.task_recover_review(task.id)
    loaded = session.task_state(task.id)
    assert loaded.review_recovery == "recovery_required"
    assert loaded.review_recovery_paths == ["a.txt"]
    assert "a.txt" in loaded.review_recovery_detail
    assert (ws / "a.txt").read_bytes() == b"external edit\n"
    with pytest.raises(ValueError, match="manual recovery required"):
        session.task_recover_review(task.id)
    assert (ws / "a.txt").read_bytes() == b"external edit\n"
    with pytest.raises(ValueError, match="unfinished review"):
        session.task_store.delete(task.id)

    # The user retains the conflicting file outside the review target; AXIOM
    # can now safely restore the pre-review contents without touching the copy.
    (ws / "a.txt").replace(ws / "my-external-edit.txt")
    recovered = session.task_recover_review(task.id)
    assert recovered.review_status == "pending"
    assert recovered.review_recovery is None
    assert recovered.review_recovery_paths == []
    assert (ws / "my-external-edit.txt").read_bytes() == b"external edit\n"
    assert (ws / "a.txt").read_bytes() == b"new\r\n"
    assert (ws / "b.txt").read_bytes() == b"after\n"
    assert session.task_store.load_transaction(task.id) is None


def test_recovery_command_rejects_missing_journal_and_wrong_workspace(tmp_path, monkeypatch):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="no unfinished review"):
        session.task_recover_review(task.id)
    transaction = ReviewTransaction.prepare(session.task_store, task, ws)
    transaction.stage()
    other = tmp_path / "other"
    other.mkdir()
    session.set_workspace(str(other))
    with pytest.raises(ValueError, match="original workspace"):
        session.task_recover_review(task.id)
    assert not session.task_store.transaction_path(task.id).exists()
    session.set_workspace(str(ws))
    assert session.task_store.load_transaction(task.id) is not None
    recovered = session.task_recover_review(task.id)
    assert recovered.review_status == "pending"
    assert session.task_store.load_transaction(task.id) is None


def test_parent_directory_replacement_fails_closed_before_publication(tmp_path, monkeypatch):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    parent = ws / "nested"
    parent.mkdir()
    (parent / "nested.txt").write_bytes(b"new")
    task.file_baselines = {"nested/nested.txt": "old"}
    task.review_baselines = {"nested/nested.txt": "new"}
    session.task_store.save(task)
    transaction = ReviewTransaction.prepare(session.task_store, task, ws)
    original_parent = ws / "original-parent"
    parent.rename(original_parent)
    parent.mkdir()
    (parent / "nested.txt").write_bytes(b"stranger")
    with pytest.raises(ValueError, match="parent directory changed"):
        transaction.stage()
    assert (parent / "nested.txt").read_bytes() == b"stranger"
    with pytest.raises(ValueError, match="manual recovery required"):
        transaction.recover()
    assert (parent / "nested.txt").read_bytes() == b"stranger"
    (parent / "nested.txt").unlink()
    parent.rmdir()
    original_parent.rename(parent)
    transaction.recover()
    assert (parent / "nested.txt").read_bytes() == b"new"
    assert session.task_store.load_transaction(task.id) is None


def test_parent_directory_replacement_after_staging_blocks_apply(tmp_path, monkeypatch):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    parent = ws / "nested"
    parent.mkdir()
    (parent / "file.txt").write_bytes(b"new")
    task.file_baselines = {"nested/file.txt": "old"}
    task.review_baselines = {"nested/file.txt": "new"}
    session.task_store.save(task)
    transaction = ReviewTransaction.prepare(session.task_store, task, ws)
    transaction.stage()
    parent.rename(ws / "saved-parent")
    parent.mkdir()
    (parent / "file.txt").write_bytes(b"unrelated")
    with pytest.raises(ValueError, match="parent directory changed"):
        transaction.apply()
    assert (parent / "file.txt").read_bytes() == b"unrelated"
    with pytest.raises(ValueError, match="manual recovery required"):
        transaction.recover()
    assert (parent / "file.txt").read_bytes() == b"unrelated"
    assert session.task_store.load_transaction(task.id)["state"] == "recovery_required"
    (parent / "file.txt").unlink()
    parent.rmdir()
    (ws / "saved-parent").rename(parent)
    transaction.recover()
    assert (parent / "file.txt").read_bytes() == b"new"
    assert session.task_store.load_transaction(task.id) is None


def test_symlinked_review_parent_is_rejected(tmp_path, monkeypatch):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    linked = ws / "linked"
    target = tmp_path / "outside"
    target.mkdir()
    try:
        linked.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable on this Windows test host")
    task.file_baselines["linked/a.txt"] = "old"
    task.review_baselines["linked/a.txt"] = "new"
    with pytest.raises(ValueError, match="Unsafe linked review path"):
        ReviewTransaction.prepare(session.task_store, task, ws)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction only")
def test_windows_junction_review_parent_is_rejected(tmp_path, monkeypatch):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = ws / "junction"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                            capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        pytest.skip(f"junction creation unavailable: {result.stderr.strip()}")
    task.file_baselines["junction/other.txt"] = "old"
    task.review_baselines["junction/other.txt"] = "new"
    with pytest.raises(ValueError, match=r"Invalid review path|Unsafe linked review path"):
        ReviewTransaction.prepare(session.task_store, task, ws)
    assert not (outside / "other.txt").exists()


def test_committed_review_cleanup_is_idempotent(tmp_path, monkeypatch):
    session, task, ws, transaction = _transaction_fixture(tmp_path, monkeypatch)
    transaction.apply()
    task.review_status = "rejected"
    task.revision += 1
    session.task_store.save_review(task)
    transaction.journal.state = "committed"
    transaction.save()
    transaction.cleanup()
    transaction.cleanup()
    assert session.task_store.load_transaction(task.id) is None
    assert not list(ws.glob(".axiom-review-*"))


def test_review_lock_rejects_nested_process_lock_and_releases_after_context(tmp_path):
    outer = review_lock(tmp_path)
    outer.__enter__()
    try:
        with pytest.raises(ValueError, match="Another review operation"):
            inner = review_lock(tmp_path)
            inner.__enter__()
    finally:
        outer.__exit__(None, None, None)
    with review_lock(tmp_path):
        pass
