"""Real process death at review commit boundaries; no providers or user files."""
import os
import subprocess
import sys

import pytest

from axiom.core.review import ReviewTransaction, review_lock
from axiom.core.tasks import Task, TaskState, TaskStore
from tests.core.test_task_review import review_fixture

CHILD = r'''
import os, sys
from pathlib import Path
from axiom.core.chat import ChatSession
from axiom.core.config import Config
from axiom.core.history import HistoryStore
from axiom.core.review import ReviewTransaction
from axiom.core.tasks import TaskStore

root, task_id, point = sys.argv[1:]
session = ChatSession(config=Config(model="test"), history_store=HistoryStore(directory=Path(root)/"history"))
session.set_workspace(root)
save = ReviewTransaction.save
replace = Path.replace
link = os.link
unlink = Path.unlink
commit = TaskStore.save_review

def save_hook(self):
    save(self)
    entries = self.journal.entries
    if point == "prepared" and self.journal.state == "prepared" and not any(e.staged for e in entries):
        os._exit(73)
    if point == "staged" and self.journal.state == "prepared" and all(e.staged for e in entries):
        os._exit(73)
    if point == "intent" and self.journal.state == "applying" and entries[0].started:
        os._exit(73)
    if point == "rollback-intent" and any(e.displaced for e in entries):
        os._exit(73)
    if point == "rolled-back" and self.journal.state == "rolled_back":
        os._exit(73)
    if point == "journal-committed" and self.journal.state == "committed":
        os._exit(73)

def replace_hook(self, target):
    result = replace(self, target)
    if point == "backup" and str(target).endswith(".backup"):
        os._exit(73)
    if point == "displaced" and str(target).endswith(".displaced"):
        os._exit(73)
    return result

def link_hook(src, dst, *a, **kw):
    if point.startswith("rollback") or point in {"displaced", "rolled-back"}:
        if Path(src).suffix == ".stage" and Path(dst).name == "b.txt":
            raise OSError("injected publication failure")
    result = link(src, dst, *a, **kw)
    if point == "published" and Path(src).suffix == ".stage":
        os._exit(73)
    if point == "rollback-published" and Path(src).suffix == ".backup":
        os._exit(73)
    return result

def commit_hook(self, task):
    if point == "before-commit" and task.review_status == "rejected":
        os._exit(73)
    commit(self, task)
    if point == "after-commit" and task.review_status == "rejected":
        os._exit(73)

def unlink_hook(self, *a, **kw):
    result = unlink(self, *a, **kw)
    if point == "cleanup" and self.suffix == ".stage":
        os._exit(73)
    return result

ReviewTransaction.save = save_hook
Path.replace = replace_hook
os.link = link_hook
Path.unlink = unlink_hook
TaskStore.save_review = commit_hook
session.task_review(task_id, "reject")
raise AssertionError("fault was not reached")
'''


@pytest.mark.parametrize("point", [
    "prepared", "staged", "intent", "backup", "published", "before-commit",
    "after-commit", "journal-committed", "cleanup", "rollback-intent",
    "rollback-published", "displaced", "rolled-back",
])
def test_real_process_crash_and_restart(tmp_path, monkeypatch, point):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    child = subprocess.run([sys.executable, "-c", CHILD, str(ws), task.id, point],
                           capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
    assert child.returncode == 73, child.stderr.decode(errors="replace")
    committed = point in {"after-commit", "journal-committed", "cleanup"}
    # Reading/listing tasks must reveal recovery without touching the workspace.
    loaded = TaskStore(session.task_store.directory).load(task.id)
    assert loaded.review_recovery is not None
    assert loaded.review_status == ("rejected" if committed else "pending")
    with pytest.raises(ValueError, match="unfinished review"):
        session.task_store.delete(task.id)
    if committed:
        result = session.task_review(task.id, "reject")
        assert result.review_status == "rejected"
        assert (ws / "a.txt").read_bytes() == b"old\r\n"
    else:
        with pytest.raises(ValueError, match="Interrupted reject recovered"):
            session.task_review(task.id, "reject")
        assert (ws / "a.txt").read_bytes() == b"new\r\n"
        assert (ws / "b.txt").read_bytes() == b"after\n"
        assert session.task_review(task.id, "reject").review_status == "rejected"
    assert not list(ws.glob(".axiom-review-*"))
    assert session.task_store.load_transaction(task.id) is None


def test_lock_is_process_scoped_and_released_on_abrupt_exit(tmp_path):
    script = "from pathlib import Path; from axiom.core.review import review_lock; import sys,os\n"
    script += "with review_lock(Path(sys.argv[1])): os._exit(74)\n"
    with review_lock(tmp_path):
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, timeout=15)
        assert result.returncode != 74
        assert b"Another review operation" in result.stderr
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, timeout=15)
    assert result.returncode == 74
    with review_lock(tmp_path):
        pass


@pytest.mark.parametrize("original,expected", [(None, ""), ("", None), (None, "created"), ("deleted", None)])
def test_create_delete_and_empty_file_recovery(tmp_path, monkeypatch, original, expected):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    task.file_baselines = {"empty.txt": original}
    task.review_baselines = {"empty.txt": expected}
    path = ws / "empty.txt"
    if expected is not None:
        path.write_bytes(expected.encode())
    session.task_store.save(task)
    tx = ReviewTransaction.prepare(session.task_store, task, ws)
    tx.stage()
    tx.apply()
    assert (path.read_bytes() if path.exists() else None) == (original.encode() if original is not None else None)
    reloaded = ReviewTransaction.load(session.task_store, task, ws)
    reloaded.recover()
    assert (path.read_bytes() if path.exists() else None) == (expected.encode() if expected is not None else None)


def test_concurrent_creator_is_never_overwritten(tmp_path, monkeypatch):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    link = os.link

    def race(src, dst):
        if src.suffix == ".stage" and dst.name == "a.txt":
            dst.write_bytes(b"external creator")
        return link(src, dst)

    monkeypatch.setattr(os, "link", race)
    with pytest.raises(ValueError, match="manual recovery required"):
        session.task_review(task.id, "reject")
    assert (ws / "a.txt").read_bytes() == b"external creator"
    assert session.task_store.load(task.id).review_status == "pending"
    assert any(p.read_bytes() == b"new\r\n" for p in ws.glob("*.backup"))


@pytest.mark.parametrize("broken", ["{", "{}", '{"version":99}', '{"state":"committed"}'])
def test_corrupt_journal_blocks_writes_and_accept(tmp_path, monkeypatch, broken):
    session, task, ws = review_fixture(tmp_path, monkeypatch)
    session.task_store.transaction_path(task.id).write_text(broken, encoding="utf-8")
    for decision in ["accept", "reject"]:
        with pytest.raises(ValueError, match="journal is invalid"):
            session.task_review(task.id, decision)
    with pytest.raises(ValueError, match="unfinished review"):
        session.task_store.save(Task(goal="New task", state=TaskState.PENDING))
    assert (ws / "a.txt").read_bytes() == b"new\r\n"
