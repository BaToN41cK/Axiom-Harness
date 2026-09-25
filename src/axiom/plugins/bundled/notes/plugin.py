"""AXIOM built-in plugin: persistent personal notes with tags and search."""

from __future__ import annotations

from datetime import datetime

from axiom.core.config import axiom_home
from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult

MAX_NOTE_CHARS = 4000
MAX_RESULT_CHARS = 6000


def _notes_path():
    path = axiom_home() / "notes" / "notes.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


TOOLS = [
    ToolDefinition(
        name="note_add",
        description=(
            "Append a note to the user's persistent notebook (~/.axiom/notes/notes.md). "
            "Each note gets a timestamp and an optional #tag. "
            "Use this to remember facts, decisions, links or TODOs across conversations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Note content."},
                "tag": {"type": "string", "description": "Optional tag, e.g. 'idea' or 'todo'."},
            },
            "required": ["text"],
        },
        permission=ToolPermission.ALWAYS,
        max_output=600,
    ),
    ToolDefinition(
        name="note_list",
        description=(
            "List notes from the notebook, optionally filtered by a substring or #tag. "
            "Newest notes are shown first."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {"type": "string", "description": "Optional substring or #tag to search for."},
            },
            "required": [],
        },
        permission=ToolPermission.ALWAYS,
        max_output=MAX_RESULT_CHARS,
    ),
]


async def note_add(text: str, tag: str = "") -> ToolResult:
    if not text or not text.strip():
        return ToolResult(name="note_add", ok=False, error="text is required")
    if len(text) > MAX_NOTE_CHARS:
        return ToolResult(
            name="note_add",
            ok=False,
            error=f"note is too long (max {MAX_NOTE_CHARS} chars)",
        )
    tag = (tag or "").strip()
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    tag_part = f" #{tag}" if tag else ""
    line = f"- [{stamp}]{tag_part} {text.strip()}\n"
    try:
        with _notes_path().open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError as exc:
        return ToolResult(name="note_add", ok=False, error=str(exc))
    return ToolResult(name="note_add", ok=True, content=f"Note saved{tag_part or ''}.")


async def note_list(filter: str = "") -> ToolResult:
    path = _notes_path()
    if not path.exists():
        return ToolResult(name="note_list", ok=True, content="(no notes yet)")
    try:
        notes = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return ToolResult(name="note_list", ok=False, error=str(exc))
    query = (filter or "").strip().lower()
    if query:
        notes = [note for note in notes if query in note.lower()]
    if not notes:
        return ToolResult(name="note_list", ok=True, content="(no matching notes)")
    newest_first = list(reversed(notes))
    body = "\n".join(newest_first)
    if len(body) > MAX_RESULT_CHARS:
        body = body[:MAX_RESULT_CHARS] + "\n… (truncated)"
    return ToolResult(name="note_list", ok=True, content=body)


HANDLERS = {"note_add": note_add, "note_list": note_list}
