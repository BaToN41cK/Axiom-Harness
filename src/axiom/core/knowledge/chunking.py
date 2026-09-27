"""Text chunking for the knowledge index — deterministic, token-aware-ish.

Chunks are cut on paragraph boundaries when possible and hard-capped so a
single source file can never flood the model context. No LLM is involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Approximate chunk budget in characters (roughly 400-600 tokens).
CHUNK_CHARS = 1800
#: Soft overlap so a fact split across a boundary is still found whole.
CHUNK_OVERLAP = 200

_TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".txt", ".toml",
    ".yaml", ".yml", ".css", ".html", ".rs", ".go", ".c", ".h", ".cpp",
    ".sh", ".cfg", ".ini", ".sql", ".xml", ".csv", ".rst",
}

#: Filenames that must never enter the knowledge index.
SECRET_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


def is_indexable(name: str, suffix: str) -> bool:
    """A file is indexable when it is a known text type and not a secret."""
    lowered = name.lower()
    if lowered in SECRET_NAMES:
        return False
    if any(lowered.endswith(s) for s in SECRET_SUFFIXES):
        return False
    return suffix.lower() in _TEXT_SUFFIXES


@dataclass
class TextChunk:
    """One indexed fragment of a source file."""

    index: int
    text: str
    start_line: int = 1
    end_line: int = 1
    headings: list[str] = field(default_factory=list)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def chunk_text(text: str, *, max_chars: int = CHUNK_CHARS,
               overlap: int = CHUNK_OVERLAP) -> list[TextChunk]:
    """Split *text* into overlapping chunks, tracking real line numbers."""
    cleaned = text.replace("\r\n", "\n")
    if not cleaned.strip():
        return []
    chunks: list[TextChunk] = []
    start = 0
    index = 0
    length = len(cleaned)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            # Prefer to cut at a paragraph, then at a newline, then anywhere.
            cut = cleaned.rfind("\n\n", start + max_chars // 2, end)
            if cut == -1:
                cut = cleaned.rfind("\n", start + max_chars // 2, end)
            if cut > start:
                end = cut + 1
        piece = cleaned[start:end].strip("\n")
        if piece.strip():
            chunks.append(
                TextChunk(
                    index=index,
                    text=piece,
                    start_line=_line_of(cleaned, start),
                    end_line=_line_of(cleaned, max(start, end - 1)),
                )
            )
            index += 1
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks
