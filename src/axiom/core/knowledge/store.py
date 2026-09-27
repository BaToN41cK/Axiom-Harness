"""Knowledge store — SQLite/FTS5 index with optional Ollama embeddings.

Layout per collection: ``~/.axiom/knowledge/<collection>.db``. BM25 ranking
through FTS5 is always available (fully offline); embeddings are a best-effort
re-ranking layer computed through the real Ollama ``/api/embed`` endpoint and
reported honestly (``ok`` / ``unavailable: <reason>`` / ``disabled``).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from axiom.core.config import axiom_home
from axiom.core.knowledge.chunking import chunk_text, is_indexable
from axiom.core.logging import get_logger

_LOG = get_logger("knowledge")

MAX_FILE_BYTES = 400_000
MAX_INDEX_FILES = 4000
#: Re-rank at most this many BM25 candidates with the vector score.
_RERANK_CANDIDATES = 40

_TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)


@dataclass
class KnowledgeHit:
    source: str
    index: int
    text: str
    start_line: int
    end_line: int
    score: float


@dataclass
class IndexStats:
    files_seen: int = 0
    indexed: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "files_seen": self.files_seen,
            "indexed": self.indexed,
            "unchanged": self.unchanged,
            "removed": self.removed,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


def _db_dir() -> Path:
    return axiom_home() / "knowledge"


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _fingerprint(path: Path) -> str:
    try:
        st = path.stat()
    except OSError:
        return ""
    return f"{st.st_mtime_ns}:{st.st_size}"


class KnowledgeStore:
    """One named collection of indexed local documents."""

    def __init__(self, name: str, root: Path | str, *, db_dir: Path | None = None) -> None:
        cleaned = re.sub(r"[^\w\-]+", "_", (name or "").strip()) or "default"
        self.name = cleaned
        self.root = Path(root).expanduser().resolve()
        base = db_dir or _db_dir()
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = base / f"{cleaned}.db"
        self.embeddings_status: str = "disabled"
        # check_same_thread=False: ChatSession offloads indexing to a worker
        # thread via asyncio.to_thread; each KnowledgeStore is only ever used
        # from one call at a time (the manager hands out one store per name).
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def _ensure_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS files ("
                    " path TEXT PRIMARY KEY, mtime TEXT, size INTEGER, chunks INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS chunks ("
                    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    " path TEXT NOT NULL, idx INTEGER NOT NULL,"
                    " start_line INTEGER, end_line INTEGER,"
                    " text TEXT NOT NULL, embedding TEXT)")
        cur.execute("CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path)")
        try:
            cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                        " text, content='chunks', content_rowid='id')")
        except sqlite3.Error as exc:  # FTS5 missing — degrade honestly
            _LOG.warning("FTS5 unavailable: %s", exc)
        cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self._conn.commit()

    def _iter_files(self) -> list[Path]:
        if self.root.is_file():
            return [self.root]
        if not self.root.exists():
            return []
        files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")
                           and d not in {"node_modules", "__pycache__", "dist", "build"}]
            for filename in sorted(filenames):
                files.append(Path(dirpath) / filename)
                if len(files) >= MAX_INDEX_FILES:
                    return files
        return files

    def _delete_path(self, cur: sqlite3.Cursor, path: str) -> None:
        cur.execute("DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE path = ?)", (path,))
        cur.execute("DELETE FROM chunks WHERE path = ?", (path,))
        cur.execute("DELETE FROM files WHERE path = ?", (path,))

    def index(self, embedder: Embedder | None = None) -> IndexStats:
        """Incrementally (re)index the collection: only changed files are read."""
        stats = IndexStats()
        cur = self._conn.cursor()
        known = {row["path"]: row["mtime"] for row in cur.execute("SELECT path, mtime FROM files")}
        seen: set[str] = set()
        pending: list[tuple[int, str]] = []
        for path in self._iter_files():
            stats.files_seen += 1
            rel = str(path.relative_to(self.root)) if self.root.is_dir() else path.name
            seen.add(rel)
            if not is_indexable(path.name, path.suffix):
                stats.skipped += 1
                continue
            fingerprint = _fingerprint(path)
            if known.get(rel) == fingerprint and fingerprint:
                stats.unchanged += 1
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    stats.skipped += 1
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                stats.errors.append(f"{rel}: {exc}")
                continue
            pieces = chunk_text(text)
            self._delete_path(cur, rel)
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            cur.execute(
                "INSERT OR REPLACE INTO files(path, mtime, size, chunks) VALUES (?, ?, ?, ?)",
                (rel, fingerprint, size, len(pieces)),
            )
            for piece in pieces:
                cursor = cur.execute(
                    "INSERT INTO chunks(path, idx, start_line, end_line, text, embedding)"
                    " VALUES (?, ?, ?, ?, ?, NULL)",
                    (rel, piece.index, piece.start_line, piece.end_line, piece.text),
                )
                rowid = cursor.lastrowid
                cur.execute("INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)", (rowid, piece.text))
                if embedder is not None and rowid is not None:
                    pending.append((rowid, piece.text))
            stats.indexed += 1
        # Files that disappeared from disk leave the index too.
        for rel in sorted(set(known) - seen):
            self._delete_path(cur, rel)
            stats.removed += 1
        self._conn.commit()
        self._set_meta("updated_at", str(time.time()))
        if embedder is not None and pending:
            self._embed_chunks(cur, embedder, pending)
        elif embedder is None:
            self.embeddings_status = "disabled"
        _LOG.info("knowledge[%s]: %s", self.name, stats.to_dict())
        return stats

    def _embed_chunks(self, cur: sqlite3.Cursor, embedder: Embedder,
                      pending: list[tuple[int, str]]) -> None:
        vectors, error = embedder.embed([text for _, text in pending])
        if vectors is None:
            self.embeddings_status = f"unavailable: {error or 'no embeddings returned'}"
            return
        stored = 0
        for (rowid, _), vector in zip(pending, vectors, strict=False):
            if vector:
                cur.execute("UPDATE chunks SET embedding = ? WHERE id = ?",
                            (json.dumps(vector), rowid))
                stored += 1
        self._conn.commit()
        self.embeddings_status = "ok" if stored else "unavailable: empty vectors"


    # -------------------------------------------------------------- retrieval

    def search(self, query: str, *, limit: int = 5) -> list[KnowledgeHit]:
        """Hybrid retrieval: BM25 (FTS5, offline) re-ranked by vector cosine."""
        tokens = _tokenize(query)
        if not tokens:
            return []
        limit = max(1, min(limit, 20))
        rows = self._bm25(tokens, limit=_RERANK_CANDIDATES)
        if not rows:
            return []
        hits = [
            KnowledgeHit(
                source=row["path"], index=row["idx"], text=row["text"],
                start_line=row["start_line"], end_line=row["end_line"],
                score=-float(row["rank"]),
            )
            for row in rows
        ]
        query_vector = self._query_vector(query)
        if query_vector is not None:
            hits = self._rerank(query_vector, hits)
        return hits[:limit]

    def _bm25(self, tokens: list[str], *, limit: int) -> list[sqlite3.Row]:
        # OR so a rare term never hides a document; FTS5 ranks by BM25.
        match = " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens[:12])
        try:
            return list(self._conn.execute(
                "SELECT c.path, c.idx, c.text, c.start_line, c.end_line, f.rank"
                " FROM chunks_fts f JOIN chunks c ON c.id = f.rowid"
                " WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, limit),
            ))
        except sqlite3.Error as exc:
            _LOG.warning("FTS query failed: %s", exc)
            return []

    def _query_vector(self, query: str) -> list[float] | None:
        embedder = getattr(self, "_query_embedder", None)
        if embedder is None:
            return None
        vectors, _ = embedder.embed([query])
        if not vectors:
            return None
        return vectors[0]

    def _rerank(self, query_vector: list[float], hits: list[KnowledgeHit]) -> list[KnowledgeHit]:
        by_key: dict[tuple[str, int], KnowledgeHit] = {(h.source, h.index): h for h in hits}
        sources = tuple({hit.source for hit in hits})
        placeholders = ",".join("?" for _ in sources)
        rows = self._conn.execute(
            f"SELECT path, idx, embedding FROM chunks WHERE embedding IS NOT NULL"
            f" AND path IN ({placeholders})",
            sources,
        )
        base = hits[0].score if hits and hits[0].score > 0 else 1.0
        for row in rows:
            hit = by_key.get((row["path"], row["idx"]))
            if hit is None:
                continue
            try:
                vector = json.loads(row["embedding"])
            except (TypeError, json.JSONDecodeError):
                continue
            cosine = _cosine(query_vector, vector)
            if cosine is not None:
                # 60% vector, 40% normalised BM25 — a deterministic blend.
                hit.score = 0.6 * cosine + 0.4 * (hit.score / base)
        return sorted(hits, key=lambda hit: -hit.score)

    # ---------------------------------------------------------------- status

    def status(self) -> dict:
        files = self._conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
        chunks = self._conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        embedded = self._conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE embedding IS NOT NULL").fetchone()["n"]
        updated = float(self._get_meta("updated_at") or 0.0)
        return {
            "name": self.name,
            "path": str(self.root),
            "files": files,
            "chunks": chunks,
            "embedded": embedded,
            "embeddings": self.embeddings_status,
            "updated_at": updated,
        }

    def _get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
        self._conn.commit()


def _cosine(a: list[float], b: list[float]) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return None
    return dot / (norm_a * norm_b)


class Embedder:
    """Real Ollama ``/api/embed`` client — the only embeddings path."""

    def __init__(self, base_url: str, model: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def embed(self, texts: list[str]) -> tuple[list[list[float]] | None, str | None]:
        """Return (vectors, error). ``vectors`` is None when the API failed."""
        if not texts:
            return [], None
        payload = {"model": self.model, "input": texts}
        try:
            response = httpx.post(
                f"{self.base_url}/api/embed", json=payload,
                timeout=httpx.Timeout(self.timeout, connect=5.0),
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return None, f"{type(exc).__name__}: {exc}"
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list):
            return None, "response has no 'embeddings' list"
        return [list(map(float, v)) for v in embeddings if isinstance(v, list)], None


def fingerprint_text(text: str) -> str:
    """Stable short fingerprint of indexed content (used in tests/audits)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

