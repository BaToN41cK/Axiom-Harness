"""Conversation persistence — a single SQLite/FTS5 store (W2.6).

Conversations live in one ``history.db`` per scope (global or per-project)
instead of one JSON file each. FTS5 backs full-text search; when the SQLite
build lacks FTS5 the store degrades honestly to an in-Python scan. The public
API (``save``/``list``/``show``/``load``/``delete``/``search``/``rename``/
``set_meta``/``set_limit``/``use_workspace``/``directory``) is unchanged, and
``show`` still returns the same indented JSON callers relied on.

On first open the store performs an idempotent import of any legacy per-file
JSON conversations found in the directory, then moves the originals into a
``migrated_json`` backup folder so they stay readable and a repeat migration
does nothing.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from axiom.core.config import axiom_home
from axiom.core.events import Message
from axiom.core.logging import get_logger

_LOG = get_logger("history")

#: Legacy JSON files are moved here after import (kept readable, not deleted).
_BACKUP_DIRNAME = "migrated_json"

_WORD_RE = re.compile(r"\w+", re.UNICODE)


class Conversation(BaseModel):
    """A stored chat session."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "New conversation"
    model: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    messages: list[Message] = Field(default_factory=list)
    #: Sidebar organisation (GUI): pinned to the top / filed under a folder.
    pinned: bool = False
    folder: str | None = None

    def touch(self) -> None:
        self.updated_at = time.time()

    def derive_title(self) -> None:
        """Use the first real user message as the conversation title."""
        for message in self.messages:
            if message.role == "user" and message.content.strip():
                title = " ".join(message.content.split())
                self.title = title[:48] + ("…" if len(title) > 48 else "")
                return


class HistoryStore:
    """Reads and writes conversations to ``<dir>/history.db`` (SQLite/FTS5).

    A size limit keeps the store from growing forever: when ``limit`` is set,
    the oldest conversations are pruned on every save.
    """

    def __init__(self, directory: Path | None = None, limit: int | None = None) -> None:
        self._dir = directory or (axiom_home() / "history")
        self._limit = limit
        self._conn: sqlite3.Connection | None = None
        self._fts = False
        self._open(self._dir)

    # ----------------------------------------------------------------- lifecycle

    def _open(self, directory: Path) -> None:
        """(Re)open the store at ``directory``: schema, then legacy import."""
        self.close()
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: ChatSession may persist from a worker thread
        # (asyncio.to_thread); a single store is only used one call at a time.
        self._conn = sqlite3.connect(self._dir / "history.db", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        self._migrate_json()

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None

    def _ensure_schema(self) -> None:
        assert self._conn is not None
        cur = self._conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS conversations ("
            " id TEXT PRIMARY KEY, title TEXT, model TEXT,"
            " created_at REAL, updated_at REAL,"
            " pinned INTEGER DEFAULT 0, folder TEXT, data TEXT NOT NULL)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS conversations_updated"
            " ON conversations(updated_at)"
        )
        try:
            cur.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS history_fts"
                " USING fts5(cid UNINDEXED, content)"
            )
            self._fts = True
        except sqlite3.Error as exc:  # FTS5 missing — degrade honestly
            _LOG.warning("FTS5 unavailable, history search falls back to scan: %s", exc)
            self._fts = False
        self._conn.commit()

    # ------------------------------------------------------------ legacy import

    def _migrate_json(self) -> None:
        """Import legacy ``<id>.json`` files once, then back them up.

        Idempotent: after the originals are moved into ``migrated_json`` a
        repeat open finds no ``*.json`` in the directory and does nothing.
        """
        legacy = sorted(p for p in self._dir.glob("*.json") if p.is_file())
        if not legacy:
            return
        backup = self._dir / _BACKUP_DIRNAME
        backup.mkdir(parents=True, exist_ok=True)
        imported = 0
        for path in legacy:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                conversation = Conversation.model_validate(raw)
            except (OSError, json.JSONDecodeError, ValueError):
                conversation = None
            if conversation is not None:
                self._upsert(conversation)
                imported += 1
            try:  # keep the original file readable in the backup folder
                path.replace(backup / path.name)
            except OSError:
                continue
        if imported:
            self._conn.commit()  # type: ignore[union-attr]
            _LOG.info("history: imported %d legacy conversation(s) into history.db", imported)

    # -------------------------------------------------------------- directories

    def use_workspace(self, root: Path | str | None) -> Path:
        """Point this store at a per-project history dir (§13, §22).

        Each project keeps its own conversations: ``~/.axiom/projects/<slug>``.
        Returns the directory now in use. ``None`` restores the global dir.
        """
        from axiom.core.workspace import project_slug

        if root is None:
            target = axiom_home() / "history"
        else:
            target = axiom_home() / "projects" / project_slug(Path(root)) / "history"
        self._open(target)
        return self._dir

    @property
    def directory(self) -> Path:
        return self._dir

    # --------------------------------------------------------------- write path

    @staticmethod
    def _fts_content(conversation: Conversation) -> str:
        parts = [conversation.title]
        parts.extend(message.content for message in conversation.messages)
        return "\n".join(part for part in parts if part)

    def _upsert(self, conversation: Conversation) -> None:
        assert self._conn is not None
        data = conversation.model_dump_json(indent=2)
        self._conn.execute(
            "INSERT OR REPLACE INTO conversations"
            "(id, title, model, created_at, updated_at, pinned, folder, data)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation.id,
                conversation.title,
                conversation.model,
                conversation.created_at,
                conversation.updated_at,
                1 if conversation.pinned else 0,
                conversation.folder,
                data,
            ),
        )
        if self._fts:
            self._conn.execute("DELETE FROM history_fts WHERE cid = ?", (conversation.id,))
            self._conn.execute(
                "INSERT INTO history_fts(cid, content) VALUES (?, ?)",
                (conversation.id, self._fts_content(conversation)),
            )

    def save(self, conversation: Conversation) -> None:
        if self._conn is None:
            raise OSError("history store is closed")
        conversation.touch()
        self._upsert(conversation)
        self._conn.commit()
        self._prune()

    def _prune(self) -> None:
        """Keep at most ``limit`` newest conversations (``None`` = keep all)."""
        if not self._limit or self._limit < 1 or self._conn is None:
            return
        stale = [
            row["id"]
            for row in self._conn.execute(
                "SELECT id FROM conversations ORDER BY updated_at DESC"
                " LIMIT -1 OFFSET ?",
                (self._limit,),
            )
        ]
        for conversation_id in stale:
            self._remove(conversation_id)
        if stale:
            self._conn.commit()

    def _remove(self, conversation_id: str) -> int:
        assert self._conn is not None
        if self._fts:
            self._conn.execute("DELETE FROM history_fts WHERE cid = ?", (conversation_id,))
        cur = self._conn.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
        return cur.rowcount

    def set_limit(self, limit: int | None) -> None:
        """Change the size limit at runtime (``None`` = unlimited)."""
        self._limit = limit

    def rename(self, conversation_id: str, title: str) -> bool:
        """Rename a stored conversation (the real title lives in the store)."""
        clean = " ".join((title or "").split())
        if not clean:
            return False
        conversation = self.load(conversation_id)
        if conversation is None:
            return False
        conversation.title = clean[:80]
        try:
            self.save(conversation)
        except OSError:
            return False
        return True

    def set_meta(
        self,
        conversation_id: str,
        *,
        pinned: bool | None = None,
        folder: str | object | None = ...,
    ) -> bool:
        """Persist sidebar metadata (``pinned`` / ``folder``).

        ``folder``: ``...`` (Ellipsis) = leave unchanged, ``None`` = clear,
        any string = set/normalise. Returns False when the chat is gone.
        """
        conversation = self.load(conversation_id)
        if conversation is None:
            return False
        if pinned is not None:
            conversation.pinned = pinned
        if folder is not ...:
            clean = " ".join((folder or "").split())[:40] or None
            conversation.folder = clean
        try:
            self.save(conversation)
        except OSError:
            return False
        return True

    def search(self, query: str, limit: int = 30) -> list[dict]:
        """Full-text search over stored messages (case-insensitive).

        Returns ``{id, title, snippet, updated_at}`` for the newest matching
        conversations — real content matches, not just title filtering. FTS5
        narrows candidates fast; the snippet keeps the exact substring window
        callers already depend on.
        """
        needle = query.strip().casefold()
        if not needle:
            return []
        hits: list[dict] = []
        for conversation in self._search_candidates(query):  # newest first
            snippet = self._snippet_for(conversation, needle)
            if snippet is not None:
                hits.append(
                    {
                        "id": conversation.id,
                        "title": conversation.title,
                        "snippet": snippet,
                        "updated_at": conversation.updated_at,
                    }
                )
            if len(hits) >= limit:
                break
        return hits

    @staticmethod
    def _snippet_for(conversation: Conversation, needle: str) -> str | None:
        for message in conversation.messages:
            pos = message.content.casefold().find(needle)
            if pos < 0:
                continue
            start = max(0, pos - 40)
            text = " ".join(message.content[start : pos + len(needle) + 80].split())
            prefix = "…" if start > 0 else ""
            suffix = "…" if pos + len(needle) + 80 < len(message.content) else ""
            return f"{prefix}{text}{suffix}"
        if needle in conversation.title.casefold():
            return conversation.title
        return None

    def _search_candidates(self, query: str) -> list[Conversation]:
        """Newest-first candidates for ``query`` (FTS5 when available)."""
        if not self._fts or self._conn is None:
            return self.list()
        terms = {t.lower() for t in _WORD_RE.findall(query)}
        if not terms:
            return self.list()
        # OR so a rare term never hides a match; the snippet step then enforces
        # the exact substring, keeping results identical to the scan behaviour.
        match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        try:
            rows = self._conn.execute(
                "SELECT c.data FROM history_fts f"
                " JOIN conversations c ON c.id = f.cid"
                " WHERE history_fts MATCH ? ORDER BY c.updated_at DESC",
                (match,),
            ).fetchall()
        except sqlite3.Error as exc:
            _LOG.warning("history FTS query failed, falling back to scan: %s", exc)
            return self.list()
        return self._rows_to_conversations(rows)

    def show(self, conversation_id: str) -> str | None:
        """Raw JSON of one conversation — the ``show`` half of list/show/rm."""
        if self._conn is None:
            return None
        row = self._conn.execute(
            "SELECT data FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return str(row["data"]) if row else None

    def load(self, conversation_id: str) -> Conversation | None:
        if self._conn is None:
            return None
        row = self._conn.execute(
            "SELECT data FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            return Conversation.model_validate_json(row["data"])
        except ValueError:
            return None

    def list(self) -> list[Conversation]:
        """All conversations, newest first. Corrupt rows are skipped."""
        if self._conn is None:
            return []
        rows = self._conn.execute(
            "SELECT data FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
        return self._rows_to_conversations(rows)

    @staticmethod
    def _rows_to_conversations(rows: list[sqlite3.Row]) -> list[Conversation]:
        conversations: list[Conversation] = []
        for row in rows:
            try:
                conversations.append(Conversation.model_validate_json(row["data"]))
            except ValueError:
                continue
        return conversations

    def delete(self, conversation_id: str) -> bool:
        if self._conn is None:
            return False
        removed = self._remove(conversation_id)
        self._conn.commit()
        return removed > 0

