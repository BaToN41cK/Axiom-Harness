"""Durable task-reject journal, not an OS-wide filesystem transaction.

Recovery is explicit. Unexpected external data is preserved, never guessed away.
Windows file locks / POSIX flock serialize cooperating AXIOM review requests.
"""
from __future__ import annotations

import hashlib
import os
import stat
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from axiom.core.tasks import Task, TaskStore


def sync_directory(path: Path) -> None:
    # Windows has no portable directory fsync. Process-crash recovery is tested;
    # power-loss durability depends on the filesystem/OS, especially on Windows.
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def durable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
        sync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def review_lock(directory: Path) -> Iterator[None]:
    """One persistent lock inode per task store; kernel releases it on exit.

    Never unlink the lock: doing so would let a new caller lock a different inode.
    No PID probing (os.kill(pid, 0) is unsafe on Windows).
    """
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".review.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                flock = fcntl.flock
                flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Another review operation is active") from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class Fingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str
    device: int
    inode: int
    size: int
    mtime: int
    mode: int


class DirectoryIdentity(BaseModel):
    """Identity of a directory, excluding mtime because files update it."""

    model_config = ConfigDict(extra="forbid")
    device: int
    inode: int
    mode: int
    reparse: bool = False


def _directory_identity(path: Path) -> DirectoryIdentity:
    info = path.lstat()
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink() or reparse:
        raise ValueError(f"Unsafe review directory: {path}")
    return DirectoryIdentity(device=info.st_dev, inode=info.st_ino,
                             mode=stat.S_IMODE(info.st_mode), reparse=reparse)


def directory_chain(root: Path, path: Path) -> dict[str, DirectoryIdentity]:
    """Capture every directory between workspace root and a target parent."""
    parent = path.parent
    if not parent.is_relative_to(root):
        raise ValueError(f"Review path escapes workspace: {path}")
    chain: list[Path] = []
    current = parent
    while True:
        chain.append(current)
        if current == root:
            break
        current = current.parent
    return {str(item.relative_to(root)) if item != root else ".": _directory_identity(item)
            for item in reversed(chain)}


def verify_directory_chain(root: Path, expected: dict[str, DirectoryIdentity]) -> None:
    """Fail closed if a parent was replaced after preflight."""
    # Older journals did not record directories. They remain recoverable under
    # the older path/fingerprint rules, not the newer parent-identity guarantee.
    for relative, identity in expected.items():
        current = root if relative == "." else root / relative
        if _directory_identity(current) != identity:
            raise ValueError(f"Review parent directory changed: {relative}")


def inspect_file(path: Path, *, allow_hardlink: bool = False) -> Fingerprint | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or (info.st_nlink > 1 and not allow_hardlink):
        raise ValueError(f"Not a regular single-link file: {path}")
    return _fingerprint(path, info)


def _fingerprint(path: Path, info: os.stat_result | None = None) -> Fingerprint:
    info = info or path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Not a regular file: {path}")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        end = os.fstat(stream.fileno())
    def keys(s: os.stat_result) -> tuple[int, ...]:
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode
    if keys(info) != keys(opened) or keys(opened) != keys(end) or keys(end) != keys(path.lstat()):
        raise ValueError(f"File changed while reading: {path}")
    return Fingerprint(sha256=digest, device=info.st_dev, inode=info.st_ino,
                       size=info.st_size, mtime=info.st_mtime_ns, mode=stat.S_IMODE(info.st_mode))


class ReviewEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    original: str | None
    expected: Fingerprint | None
    staged: Fingerprint | None = None
    started: bool = False
    displaced: bool = False


class ReviewJournal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    task_id: str
    root: str
    revision: int
    state: Literal["prepared", "applying", "rolling_back", "recovery_required", "rolled_back", "committed"]
    entries: list[ReviewEntry]
    directories: dict[str, DirectoryIdentity] = Field(default_factory=dict)
    error: str = ""
    conflicts: list[str] = Field(default_factory=list)


def target_path(root: Path, relative: str) -> Path:
    raw = Path(relative)
    if raw.drive or raw.is_absolute() or not raw.parts or any(
        p == ".." or p.lower() == ".axiom" or p.startswith(".axiom-review-") or ":" in p
        for p in raw.parts
    ):
        raise ValueError(f"Invalid review path: {relative}")
    path = root / raw
    if path.resolve() != path or path == root or not path.is_relative_to(root):
        raise ValueError(f"Invalid review path: {relative}")
    # Detect junctions/reparse points even when they resolve to the same path.
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError(f"Unsafe linked review path: {relative}")
    return path



class ReviewTransaction:
    def __init__(self, store: TaskStore, journal: ReviewJournal) -> None:
        self.store = store
        self.journal = journal
        self.root = Path(journal.root)

    def save(self) -> None:
        self.store.save_transaction(self.journal.task_id, self.journal.model_dump(mode="json"))

    def paths(self, index: int) -> tuple[Path, Path, Path]:
        path = target_path(self.root, self.journal.entries[index].path)
        prefix = f".axiom-review-{self.journal.id}-{index}"
        return path, path.with_name(prefix + ".stage"), path.with_name(prefix + ".backup")

    @classmethod
    def prepare(cls, store: TaskStore, task: Task, root: Path) -> ReviewTransaction:
        if task.unknown_baselines:
            raise ValueError("Cannot safely reject: original binary/unreadable files were changed")
        if set(task.review_baselines) != set(task.file_baselines):
            raise ValueError("Cannot safely reject: task has no complete post-change snapshot")
        entries = []
        seen: set[Path] = set()
        directories: dict[str, DirectoryIdentity] = {".": _directory_identity(root)}
        for relative, original in task.file_baselines.items():
            path = target_path(root, relative)
            if path in seen:
                raise ValueError("Duplicate review target")
            seen.add(path)
            current = inspect_file(path)
            text = task.review_baselines[relative]
            expected = None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()
            if (current.sha256 if current else None) != expected:
                raise ValueError(f"Cannot safely reject: {relative} changed after the task completed")
            directories.update(directory_chain(root, path))
            entries.append(ReviewEntry(path=relative, original=original, expected=current))
        journal = ReviewJournal(id=uuid.uuid4().hex, task_id=task.id, root=str(root), revision=task.revision,
                                state="prepared", entries=entries, directories=directories)
        tx = cls(store, journal)
        verify_directory_chain(root, journal.directories)
        tx.save()  # Intent precedes ALL project writes.
        return tx

    @classmethod
    def load(cls, store: TaskStore, task: Task, root: Path) -> ReviewTransaction | None:
        raw = store.load_transaction(task.id)
        if raw is None:
            return None
        try:
            journal = ReviewJournal.model_validate(raw)
        except ValueError as exc:
            raise ValueError("Review journal is invalid; manual recovery required") from exc
        if journal.task_id != task.id or journal.root != str(root):
            raise ValueError("Review journal workspace/task mismatch")
        expected_revision = journal.revision + (1 if task.review_status == "rejected" else 0)
        if task.revision != expected_revision:
            raise ValueError("Review journal revision mismatch; manual recovery required")
        if {e.path: e.original for e in journal.entries} != task.file_baselines:
            raise ValueError("Review journal baseline mismatch")
        tx = cls(store, journal)
        seen: set[Path] = set()
        for index in range(len(journal.entries)):
            path, _, _ = tx.paths(index)
            if path in seen:
                raise ValueError("Duplicate journal target")
            seen.add(path)
            entry = journal.entries[index]
            text = task.review_baselines.get(entry.path)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None
            if (entry.expected.sha256 if entry.expected else None) != digest:
                raise ValueError("Review journal post-change snapshot mismatch")
            if entry.staged is not None and (
                entry.original is None
                or entry.staged.sha256 != hashlib.sha256(entry.original.encode("utf-8")).hexdigest()
            ):
                raise ValueError("Review journal staged snapshot mismatch")
        return tx

    def stage(self) -> None:
        for index, entry in enumerate(self.journal.entries):
            path, stage, backup = self.paths(index)
            verify_directory_chain(self.root, self.journal.directories)
            if stage.exists() or backup.exists():
                raise ValueError("Review staging path already exists")
            if entry.original is not None:
                with stage.open("xb") as stream:
                    stream.write(entry.original.encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                if entry.expected:
                    stage.chmod(entry.expected.mode)
                entry.staged = inspect_file(stage, allow_hardlink=True)
                sync_directory(path.parent)
                self.save()

    def apply(self) -> None:
        self.journal.state = "applying"
        self.save()
        for index, entry in enumerate(self.journal.entries):
            path, stage, backup = self.paths(index)
            verify_directory_chain(self.root, self.journal.directories)
            current = inspect_file(path)
            if current != entry.expected:
                raise ValueError(f"File changed during review: {entry.path}")
            if entry.staged and inspect_file(stage, allow_hardlink=True) != entry.staged:
                raise ValueError(f"Review staging changed: {entry.path}")
            entry.started = True
            self.save()  # Covers crash before/after each rename/link.
            if entry.expected is not None:
                if backup.exists():
                    raise ValueError("Backup already exists")
                path.replace(backup)
                sync_directory(path.parent)
                if inspect_file(backup) != entry.expected:
                    raise ValueError(f"File changed during review: {entry.path}")
            if entry.original is not None:
                # Publication must not overwrite a concurrent creator.
                os.link(stage, path)
                sync_directory(path.parent)
            if (inspect_file(path, allow_hardlink=True) if path.exists() else None) != entry.staged:
                raise ValueError(f"File changed during review: {entry.path}")
        for index, entry in enumerate(self.journal.entries):
            path, _, _ = self.paths(index)
            verify_directory_chain(self.root, self.journal.directories)
            if (inspect_file(path, allow_hardlink=True) if path.exists() else None) != entry.staged:
                raise ValueError(f"File changed before review commit: {entry.path}")

    def recover(self) -> None:
        """Recover a journal after a process failure without overwriting strangers."""
        if self.journal.state == "rolled_back":
            self.cleanup()
            return
        try:
            verify_directory_chain(self.root, self.journal.directories)
        except (OSError, ValueError) as exc:
            self.journal.state = "recovery_required"
            self.journal.conflicts = ["."]
            self.journal.error = f"Reject failed; manual recovery required for parent directory: {exc}"
            self.save()
            raise ValueError(self.journal.error) from exc
        self.journal.state = "rolling_back"
        self.save()
        conflicts: list[str] = []
        for index in reversed(range(len(self.journal.entries))):
            entry = self.journal.entries[index]
            if not entry.started:
                continue
            try:
                verify_directory_chain(self.root, self.journal.directories)
                path, stage, backup = self.paths(index)
                displaced = stage.with_suffix(".displaced")
                current = inspect_file(path, allow_hardlink=True) if path.exists() else None
                saved = inspect_file(backup, allow_hardlink=True) if backup.exists() else None
                if saved is not None:
                    if saved != entry.expected:
                        raise ValueError("backup fingerprint mismatch")
                    if current == saved:
                        continue
                    if current is not None and (
                        current != entry.staged or not stage.exists() or not path.samefile(stage)
                    ):
                        raise ValueError("target changed externally")
                    if current is not None:
                        self.displace(index, path, displaced, entry)
                    os.link(backup, path)
                    sync_directory(path.parent)
                elif entry.expected is None:
                    if current is None:
                        continue
                    if current != entry.staged or not stage.exists() or not path.samefile(stage):
                        raise ValueError("created target changed externally")
                    self.displace(index, path, displaced, entry)
                    sync_directory(path.parent)
                elif current != entry.expected:
                    raise ValueError("missing recovery backup")
            except (OSError, ValueError) as exc:
                conflicts.append(f"{entry.path}: {exc}")
        if conflicts:
            self.journal.state = "recovery_required"
            self.journal.conflicts = [entry.split(":", 1)[0] for entry in conflicts]
            self.journal.error = "Reject failed; manual recovery required for: " + "; ".join(conflicts)
            self.save()
            raise ValueError(self.journal.error)
        self.journal.state = "rolled_back"
        self.journal.error = ""
        self.journal.conflicts = []
        self.save()
        self.cleanup()

    def displace(self, index: int, path: Path, displaced: Path, entry: ReviewEntry) -> None:
        """Retain, then validate, the inode removed during rollback.

        A concurrent replacement after the precheck must survive in an artifact,
        rather than being unlinked. Directory checks narrow (but cannot close)
        the race against non-cooperating parent replacement.
        """
        if os.path.lexists(displaced):
            raise ValueError(f"Recovery displacement already exists for entry {index}")
        entry.displaced = True
        self.save()
        path.replace(displaced)
        sync_directory(path.parent)
        if _fingerprint(displaced) != entry.staged:
            raise ValueError("Target changed while moving it to recovery storage")

    def cleanup(self) -> None:
        """Remove only journal artifacts whose fingerprints are still known."""
        verify_directory_chain(self.root, self.journal.directories)
        for index, entry in enumerate(self.journal.entries):
            verify_directory_chain(self.root, self.journal.directories)
            _path, stage, backup = self.paths(index)
            displaced = stage.with_suffix(".displaced")
            artifacts = [(stage, entry.staged), (backup, entry.expected)]
            if entry.displaced:
                artifacts.append((displaced, entry.staged))
            elif os.path.lexists(displaced):
                raise ValueError("Unexpected recovery artifact; manual recovery required")
            # Validate all artifacts for this entry before deleting any of them.
            for artifact, expected in artifacts:
                if artifact.is_symlink():
                    raise ValueError(f"Unsafe recovery artifact: {entry.path}")
                if not artifact.exists():
                    continue
                # Unidentified partial stages are retained for manual inspection.
                # A name alone is insufficient evidence of ownership.
                if inspect_file(artifact, allow_hardlink=True) != expected:
                    raise ValueError(f"Recovery artifact changed: {entry.path}")
            for artifact, _ in artifacts:
                artifact.unlink(missing_ok=True)
            sync_directory(_path.parent)
        self.store.remove_transaction(self.journal.task_id)
