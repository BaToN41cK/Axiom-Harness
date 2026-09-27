"""Workspace filesystem tools — AXIOM's hands inside the user's project.

Every path is sandboxed to the workspace root: the model can never read or
write outside it, even with a crafted relative path. Tools mirror what a
coding agent needs: list, read, create/overwrite, and surgical edit.
"""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
import shutil
from pathlib import Path

from axiom.core.security import CheckpointStore
from axiom.core.tools.base import (
    RISK_DANGEROUS,
    RISK_MEDIUM,
    RISK_SAFE,
    ToolDefinition,
    ToolPermission,
    ToolResult,
)

LIST_FILES_TOOL = "list_files"
READ_FILE_TOOL = "read_file"
WRITE_FILE_TOOL = "write_file"
EDIT_FILE_TOOL = "edit_file"
APPLY_PATCH_TOOL = "apply_patch"
SEARCH_TEXT_TOOL = "search_text"
SEARCH_FILES_TOOL = "search_files"
DELETE_FILE_TOOL = "delete_file"
MOVE_FILE_TOOL = "move_file"
COPY_FILE_TOOL = "copy_file"
CREATE_DIR_TOOL = "create_directory"

WORKSPACE_TOOLS = (
    LIST_FILES_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
    APPLY_PATCH_TOOL, SEARCH_TEXT_TOOL, SEARCH_FILES_TOOL, DELETE_FILE_TOOL,
    MOVE_FILE_TOOL, COPY_FILE_TOOL, CREATE_DIR_TOOL,
)

#: Safety limits — a model must not be able to stall on huge inputs.
MAX_READ_CHARS = 24_000
MAX_WRITE_CHARS = 200_000
MAX_LIST_ENTRIES = 400
MAX_SEARCH_HITS = 60
IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", "dist",
    "build", ".mypy_cache", ".ruff_cache", ".pytest_cache", "target",
    "coverage", ".next", ".turbo", ".nuxt", "out", ".cache", ".tmp", "tmp",
}
SECRET_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".txt", ".toml",
    ".yaml", ".yml", ".css", ".html", ".rs", ".go", ".c", ".h", ".cpp",
    ".sh", ".cfg", ".ini", ".sql", ".svg", ".xml", ".csv", ".env", ".lock",
}


def default_workspace_root() -> Path:
    """Workspace the bridge was launched in (``AXIOM_WORKSPACE`` overrides)."""
    override = os.environ.get("AXIOM_WORKSPACE")
    return Path(override).expanduser() if override else Path.cwd()


class WorkspaceTools:
    """Registers real, sandboxed filesystem tools in a registry."""

    def __init__(self, root: Path | None = None, access_mode: str = "workspace") -> None:
        self.root = (root or default_workspace_root()).resolve()
        self.access_mode = access_mode
        self.checkpoints = CheckpointStore(self.root)

    def _checkpoint(self, target: Path) -> str | None:
        try:
            return self.checkpoints.capture(target).step_id
        except (OSError, ValueError):
            return None

    def set_root(self, root: Path) -> None:
        """Switch the sandbox root (project switch)."""
        self.root = root.resolve()

    def _can_write(self) -> bool:
        return self.access_mode != "read_only"

    def _permission(self, write: bool = False) -> ToolPermission:
        """Permission level for a tool based on access mode.

        In read_only mode all write/modify tools are NEVER offered.
        """
        if write and self.access_mode == "read_only":
            return ToolPermission.NEVER
        if self.access_mode == "read_only":
            return ToolPermission.ALWAYS
        # Workspace edits are safe within the resolved sandbox and must work in
        # a headless/GUI run even when no modal permission callback exists.
        # Destructive shell commands retain their separate ASK/NEVER policy.
        if write:
            return ToolPermission.ALWAYS
        return ToolPermission.ALWAYS

    def resolve(self, path: str) -> Path:
        """Resolve ``path`` inside the workspace; reject any escape."""
        raw = (path or "").strip()
        if not raw:
            raise ValueError("Path is empty")
        candidate = Path(raw)
        full = candidate if candidate.is_absolute() else self.root / candidate
        full = full.resolve()
        root = self.root
        if full != root and root not in full.parents:
            raise ValueError(f"Path '{path}' is outside the workspace ({root})")
        return full

    # ------------------------------------------------------------- definitions

    def _list_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=LIST_FILES_TOOL,
            description=(
                "List files and folders in the workspace. "
                "Use a subdirectory path to explore, or '.' for the root."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory inside the workspace ('.' = root).",
                    },
                },
                "required": ["path"],
            },
            permission=self._permission(write=False),
            risk=RISK_SAFE,
            timeout=15.0,
            max_output=16_000,
            workspace_scoped=True,
        )

    def _read_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=READ_FILE_TOOL,
            description=(
                "Read a text file from the workspace. Use start_line/end_line "
                "for big files, line_numbers for exact references."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the workspace."},
                    "start_line": {
                        "type": "integer",
                        "description": "1-based first line to read (inclusive).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "1-based last line to read (inclusive).",
                    },
                    "line_numbers": {
                        "type": "boolean",
                        "description": "Prefix each line with its line number (default false).",
                    },
                },
                "required": ["path"],
            },
            permission=self._permission(write=False),
            risk=RISK_SAFE,
            timeout=20.0,
            max_output=MAX_READ_CHARS,
            workspace_scoped=True,
        )

    def register(self, registry) -> None:
        """Attach all workspace tools to a :class:`ToolRegistry`."""
        for definition, handler in (
            (self._list_definition(), self._list_files),
            (self._read_definition(), self._read_file),
            (self._search_text_definition(), self._search_text),
            (self._search_files_definition(), self._search_files),
            (self._write_definition(), self._write_file),
            (self._edit_definition(), self._edit_file),
            (self._apply_patch_definition(), self._apply_patch),
            (self._create_dir_definition(), self._create_directory),
            (self._delete_definition(), self._delete_file),
            (self._move_definition(), self._move_file),
            (self._copy_definition(), self._copy_file),
        ):
            registry.register(definition, handler)

    def _apply_patch_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=APPLY_PATCH_TOOL,
            description=(
                "Apply a unified diff (--- a/... +++ b/... with @@ hunks) to a "
                "workspace file. Every hunk must match the current file exactly; "
                "on any mismatch nothing is written. Use dry_run=true to check "
                "the patch without touching the file."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Target file path relative to the workspace."},
                    "patch": {"type": "string", "description": "Unified diff body (hunk lines starting with @@)."},
                    "dry_run": {
                        "type": "boolean",
                        "description": "Validate the patch without writing (default false).",
                    },
                },
                "required": ["path", "patch"],
            },
            permission=self._permission(write=True),
            risk=RISK_MEDIUM,
            timeout=30.0,
            max_output=8_000,
            dry_run=True,
            rollback="checkpoint",
            workspace_scoped=True,
        )

    # ------------------------------------------------------------- definitions

    def _search_text_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=SEARCH_TEXT_TOOL,
            description=(
                "Search file contents across the workspace for a text substring "
                "or a regular expression. Returns path:line matches — use it to "
                "locate code relevant to the task."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text (or regex when regex=true); plain text is case-insensitive.",
                    },
                    "glob": {"type": "string", "description": "Optional filename filter, e.g. '*.py'."},
                    "regex": {
                        "type": "boolean",
                        "description": "Treat query as a Python regular expression (default false).",
                    },
                    "context": {"type": "integer", "description": "Context lines to show around each match (0-5)."},
                    "path": {"type": "string", "description": "Restrict the search to a workspace subdirectory."},
                },
                "required": ["query"],
            },
            permission=self._permission(write=False),
            risk=RISK_SAFE,
            timeout=30.0,
            max_output=12_000,
            workspace_scoped=True,
        )

    def _search_files_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=SEARCH_FILES_TOOL,
            description="Find files in the workspace by glob pattern (e.g. '*.ts', 'auth*').",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern matched against file names."},
                    "path": {"type": "string", "description": "Restrict the search to a workspace subdirectory."},
                },
                "required": ["pattern"],
            },
            permission=self._permission(write=False),
            risk=RISK_SAFE,
            timeout=30.0,
            max_output=12_000,
            workspace_scoped=True,
        )

    def _create_dir_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=CREATE_DIR_TOOL,
            description="Create a directory (and parents) inside the workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path relative to the workspace."},
                },
                "required": ["path"],
            },
            permission=self._permission(write=True),
            risk=RISK_MEDIUM,
            timeout=15.0,
            rollback="checkpoint",
            workspace_scoped=True,
        )

    def _delete_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=DELETE_FILE_TOOL,
            description=(
                "Delete a file or a directory (recursively) inside the workspace. "
                "Use sparingly — the action is hard to undo."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the workspace."},
                },
                "required": ["path"],
            },
            permission=self._permission(write=True),
            risk=RISK_DANGEROUS,
            timeout=30.0,
            rollback="checkpoint",
            workspace_scoped=True,
        )

    def _move_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=MOVE_FILE_TOOL,
            description="Move or rename a file/directory within the workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Existing path."},
                    "destination": {"type": "string", "description": "New path."},
                },
                "required": ["source", "destination"],
            },
            permission=self._permission(write=True),
            risk=RISK_MEDIUM,
            timeout=30.0,
            rollback="checkpoint",
            workspace_scoped=True,
        )

    def _copy_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=COPY_FILE_TOOL,
            description="Copy a file (or directory, recursively) within the workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Existing path."},
                    "destination": {"type": "string", "description": "Target path."},
                },
                "required": ["source", "destination"],
            },
            permission=self._permission(write=True),
            risk=RISK_MEDIUM,
            timeout=30.0,
            rollback="checkpoint",
            workspace_scoped=True,
        )

    def _write_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=WRITE_FILE_TOOL,
            description=(
                "Create a new file or completely overwrite an existing one "
                "with the given content inside the workspace. "
                "Set dry_run=true to get the statistics without writing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the workspace."},
                    "content": {"type": "string", "description": "Full new file content."},
                    "dry_run": {
                        "type": "boolean",
                        "description": "Validate and report without writing (default false).",
                    },
                },
                "required": ["path", "content"],
            },
            permission=self._permission(write=True),
            risk=RISK_MEDIUM,
            timeout=30.0,
            max_output=8_000,
            dry_run=True,
            rollback="checkpoint",
            workspace_scoped=True,
        )

    def _edit_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=EDIT_FILE_TOOL,
            description=(
                "Replace an exact snippet inside an existing workspace file. "
                "old_text must match the file verbatim and be unique; use it "
                "for surgical edits instead of rewriting the whole file. "
                "Set dry_run=true to preview the change without writing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the workspace."},
                    "old_text": {"type": "string", "description": "Exact existing text to replace."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                    "dry_run": {
                        "type": "boolean",
                        "description": "Validate and show the diff without writing (default false).",
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
            permission=self._permission(write=True),
            risk=RISK_MEDIUM,
            timeout=30.0,
            max_output=8_000,
            dry_run=True,
            rollback="checkpoint",
            workspace_scoped=True,
        )

    # ------------------------------------------------------------- handlers

    async def _list_files(self, path: str = ".") -> ToolResult:
        directory = self.resolve(path)
        if not directory.exists():
            return ToolResult(name=LIST_FILES_TOOL, ok=False, error=f"No such directory: {path}")
        if not directory.is_dir():
            return ToolResult(name=LIST_FILES_TOOL, ok=False, error=f"Not a directory: {path}")
        lines: list[str] = []
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError as exc:
            return ToolResult(name=LIST_FILES_TOOL, ok=False, error=f"Cannot list: {exc}")
        for entry in entries:
            if len(lines) >= MAX_LIST_ENTRIES:
                lines.append(f"… truncated ({MAX_LIST_ENTRIES} entries max)")
                break
            if entry.name.startswith(".") and entry.name != ".vscode":
                continue
            if entry.is_dir() and entry.name in IGNORED_DIRS:
                continue
            if entry.is_dir():
                lines.append(f"{entry.name}/")
            else:
                size = entry.stat().st_size if entry.exists() else 0
                lines.append(f"{entry.name} ({size} B)")
        body = "\n".join(lines) if lines else "(empty directory)"
        rel = directory.relative_to(self.root) if directory != self.root else Path(".")
        return ToolResult(name=LIST_FILES_TOOL, ok=True, content=body, data={"path": str(rel)})

    async def _read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        line_numbers: bool = False,
    ) -> ToolResult:
        target = self.resolve(path)
        if not target.exists():
            return ToolResult(name=READ_FILE_TOOL, ok=False, error=f"No such file: {path}")
        if target.is_dir():
            return ToolResult(name=READ_FILE_TOOL, ok=False, error=f"'{path}' is a directory — use list_files")
        size = target.stat().st_size
        if size > 2_000_000 and target.suffix.lower() not in TEXT_SUFFIXES:
            return ToolResult(name=READ_FILE_TOOL, ok=False, error=f"'{path}' looks binary or too large")
        try:
            raw = target.read_bytes()
        except OSError as exc:
            return ToolResult(name=READ_FILE_TOOL, ok=False, error=f"Cannot read: {exc}")
        if b"\x00" in raw[:8192]:
            return ToolResult(
                name=READ_FILE_TOOL, ok=False,
                error=f"'{path}' is a binary file — read_file only serves text files",
            )
        text = raw.decode("utf-8", errors="replace")
        all_lines = text.splitlines()
        total = len(all_lines)
        # ---------------------------------------------------------- line range
        first = 1 if start_line is None else max(1, int(start_line))
        last = total if end_line is None else min(int(end_line), total)
        ranged = start_line is not None or end_line is not None
        if ranged and first > total:
            return ToolResult(
                name=READ_FILE_TOOL, ok=False,
                error=f"start_line {first} is past the end of the file ({total} lines)",
            )
        if last < first:
            return ToolResult(
                name=READ_FILE_TOOL, ok=False,
                error=f"end_line {end_line} is before start_line {start_line}",
            )
        selected = all_lines[first - 1 : last]
        body_lines = selected
        if line_numbers:
            width = len(str(last))
            body_lines = [f"{first + i:>{width}}\t{line}" for i, line in enumerate(selected)]
        body = "\n".join(body_lines)
        truncated = ""
        if len(body) > MAX_READ_CHARS:
            body = body[:MAX_READ_CHARS]
            truncated = f"\n\n… truncated at {MAX_READ_CHARS} characters"
        if ranged:
            header = f"# {target.relative_to(self.root)} lines {first}-{last} of {total}"
        else:
            header = f"# {target.relative_to(self.root)} ({total} lines)"
        return ToolResult(
            name=READ_FILE_TOOL, ok=True,
            content=header + "\n" + body + truncated,
            data={"total_lines": total, "start_line": first, "end_line": last,
                  "truncated": bool(truncated)},
        )

    def _reject_secret(self, path: Path) -> None:
        name = path.name.lower()
        if name in SECRET_NAMES or path.suffix.lower() in SECRET_SUFFIXES:
            raise ValueError("Refusing to modify a secret or credential file")

    async def _write_file(self, path: str, content: str, dry_run: bool = False) -> ToolResult:
        if len(content) > MAX_WRITE_CHARS:
            return ToolResult(name=WRITE_FILE_TOOL, ok=False, error="Content exceeds size limit")
        target = self.resolve(path)
        try:
            self._reject_secret(target)
        except ValueError as exc:
            return ToolResult(name=WRITE_FILE_TOOL, ok=False, error=str(exc))
        existed = target.exists()
        prev_text = ""
        if existed and target.is_file():
            try:
                prev_text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                prev_text = ""
        prev_lines = prev_text.count("\n") + (1 if prev_text else 0)
        new_lines = content.count("\n") + 1
        stats = {
            "created": not existed,
            "lines_before": prev_lines,
            "lines_after": new_lines,
            "delta_lines": new_lines - prev_lines,
            "chars": len(content),
            "dry_run": bool(dry_run),
        }
        if dry_run:
            verb = "Would create" if not existed else "Would overwrite"
            return ToolResult(
                name=WRITE_FILE_TOOL, ok=True,
                content=f"{verb} {target.relative_to(self.root)} ({new_lines} lines, {len(content)} chars)",
                data=stats,
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            checkpoint = self._checkpoint(target)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(name=WRITE_FILE_TOOL, ok=False, error=f"Cannot write: {exc}")
        verb = "Overwrote" if existed else "Created"
        return ToolResult(
            name=WRITE_FILE_TOOL, ok=True,
            content=f"{verb} {target.relative_to(self.root)} ({new_lines} lines, {len(content)} chars)",
            data={**stats, "checkpoint": checkpoint},
        )

    async def _edit_file(
        self, path: str, old_text: str, new_text: str, dry_run: bool = False
    ) -> ToolResult:
        target = self.resolve(path)
        if not target.exists() or target.is_dir():
            return ToolResult(name=EDIT_FILE_TOOL, ok=False, error=f"No such file: {path}")
        try:
            self._reject_secret(target)
        except ValueError as exc:
            return ToolResult(name=EDIT_FILE_TOOL, ok=False, error=str(exc))
        try:
            text = target.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult(name=EDIT_FILE_TOOL, ok=False, error=f"Cannot read: {exc}")
        matches = text.count(old_text) if old_text else 0
        if matches == 0:
            return ToolResult(
                name=EDIT_FILE_TOOL,
                ok=False,
                error="old_text not found in file — read the file first and copy the snippet exactly",
            )
        if matches > 1:
            return ToolResult(
                name=EDIT_FILE_TOOL,
                ok=False,
                error=f"old_text matches {matches} places — provide a larger unique snippet",
            )
        updated = text.replace(old_text, new_text, 1)
        unified = (
            f"--- a/{target.relative_to(self.root)}\n"
            f"+++ b/{target.relative_to(self.root)}\n"
            f"-{old_text[:600]}\n"
            f"+{new_text[:600]}"
        )
        stats = {
            "replaced_chars": len(old_text),
            "new_chars": len(new_text),
            "matches": matches,
            "dry_run": bool(dry_run),
            "diff": unified,
        }
        if dry_run:
            return ToolResult(
                name=EDIT_FILE_TOOL, ok=True,
                content=(
                    f"Dry run: {target.relative_to(self.root)} would be edited "
                    f"(replaced {len(old_text)} chars with {len(new_text)}, unique match)\n{unified}"
                ),
                data=stats,
            )
        try:
            checkpoint = self._checkpoint(target)
            target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return ToolResult(name=EDIT_FILE_TOOL, ok=False, error=f"Cannot write: {exc}")
        return ToolResult(
            name=EDIT_FILE_TOOL,
            ok=True,
            content=(
                f"Edited {target.relative_to(self.root)}: "
                f"replaced {len(old_text)} chars with {len(new_text)}\n{unified}"
            ),
            data={**stats, "checkpoint": checkpoint},
        )

    async def _apply_patch(
        self, path: str, patch: str, dry_run: bool = False
    ) -> ToolResult:
        """Apply a unified diff strictly — validate first, write only on success."""
        from axiom.core.patch import PatchError, apply_unified_diff

        target = self.resolve(path)
        if target.is_dir():
            return ToolResult(
                name=APPLY_PATCH_TOOL, ok=False,
                error=f"'{path}' is a directory — patch a file",
            )
        try:
            self._reject_secret(target)
        except ValueError as exc:
            return ToolResult(name=APPLY_PATCH_TOOL, ok=False, error=str(exc))
        exists = target.exists()
        original = ""
        crlf = False
        if exists:
            try:
                raw = target.read_bytes()
            except OSError as exc:
                return ToolResult(name=APPLY_PATCH_TOOL, ok=False, error=f"Cannot read: {exc}")
            if b"\x00" in raw[:8192]:
                return ToolResult(
                    name=APPLY_PATCH_TOOL, ok=False,
                    error=f"'{path}' is a binary file — patches only apply to text files",
                )
            decoded = raw.decode("utf-8", errors="replace")
            # Patches are LF-based; remember the file's own style so the
            # rewritten file keeps CRLF when it was CRLF.
            crlf = "\r\n" in decoded
            original = decoded.replace("\r\n", "\n") if crlf else decoded
        if not (patch or "").strip():
            return ToolResult(name=APPLY_PATCH_TOOL, ok=False, error="Patch is empty")
        try:
            updated = apply_unified_diff(original, patch)
        except PatchError as exc:
            return ToolResult(
                name=APPLY_PATCH_TOOL, ok=False,
                error=f"Patch rejected, nothing written: {exc}",
            )
        if len(updated) > MAX_WRITE_CHARS:
            return ToolResult(
                name=APPLY_PATCH_TOOL, ok=False,
                error="Resulting file would exceed the size limit",
            )
        to_write = updated.replace("\n", "\r\n") if crlf else updated
        rel = target.relative_to(self.root).as_posix()
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(), updated.splitlines(),
                fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm="",
            )
        )
        added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
        summary = "\n".join(diff_lines[:80])
        stats = {
            "changed": updated != original,
            "created": not exists,
            "lines_before": original.count("\n") + (1 if original else 0),
            "lines_after": updated.count("\n") + 1,
            "added": added,
            "removed": removed,
            "dry_run": bool(dry_run),
        }
        if updated == original:
            return ToolResult(
                name=APPLY_PATCH_TOOL, ok=True,
                content=f"Patch is valid but changes nothing in {rel}",
                data=stats,
            )
        if dry_run:
            return ToolResult(
                name=APPLY_PATCH_TOOL, ok=True,
                content=f"Dry run: patch on {rel} is valid (+{added} -{removed} lines)\n{summary}",
                data=stats,
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Bytes write: text-mode newline translation would double the \r
            # of a CRLF file back to \r\r\n.
            target.write_bytes(to_write.encode("utf-8"))
        except OSError as exc:
            return ToolResult(name=APPLY_PATCH_TOOL, ok=False, error=f"Cannot write: {exc}")
        return ToolResult(
            name=APPLY_PATCH_TOOL, ok=True,
            content=f"Applied patch to {rel} (+{added} -{removed} lines)\n{summary}",
            data=stats,
        )

    def _iter_text_files(self, directory: Path):
        """Yield text files under ``directory`` skipping ignored/hidden dirs."""
        if not directory.is_dir():
            return
        try:
            for root, dirs, files in os.walk(directory):
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
                for name in files:
                    path = Path(root) / name
                    if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= 1_000_000:
                        yield path
        except OSError:
            return

    async def _search_text(
        self,
        query: str,
        glob: str | None = None,
        regex: bool = False,
        context: int = 0,
        path: str | None = None,
    ) -> ToolResult:
        if not query.strip():
            return ToolResult(name=SEARCH_TEXT_TOOL, ok=False, error="Query is empty")
        subtree = self.root
        if path:
            try:
                subtree = self.resolve(path)
            except ValueError as exc:
                return ToolResult(name=SEARCH_TEXT_TOOL, ok=False, error=str(exc))
            if not subtree.is_dir():
                return ToolResult(name=SEARCH_TEXT_TOOL, ok=False, error=f"Not a directory: {path}")
        pattern = None
        needle = ""
        if regex:
            if len(query) > 200:
                return ToolResult(name=SEARCH_TEXT_TOOL, ok=False, error="Regex pattern too long (max 200 chars)")
            try:
                pattern = re.compile(query, re.IGNORECASE)
            except re.error as exc:
                return ToolResult(name=SEARCH_TEXT_TOOL, ok=False, error=f"Invalid regex: {exc}")
        else:
            needle = query.lower()
        ctx = max(0, min(int(context or 0), 5))
        hits: list[str] = []
        for file_path in self._iter_text_files(subtree):
            if glob and not fnmatch.fnmatch(file_path.name, glob):
                continue
            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            matched_indexes: list[int] = []
            for index, line in enumerate(lines):
                if (pattern is not None and pattern.search(line)) or (
                    pattern is None and needle in line.lower()
                ):
                    matched_indexes.append(index)
                    if len(matched_indexes) > MAX_SEARCH_HITS * 4:
                        break
            if not matched_indexes:
                continue
            rel = file_path.relative_to(self.root).as_posix()
            if ctx:
                # Print each match with its context window; the match line is
                # prefixed with '>' so the model can tell it apart.
                for index in matched_indexes[:10]:
                    start = max(0, index - ctx)
                    stop = min(len(lines), index + ctx + 1)
                    hits.append(f"{rel}:{index + 1}")
                    for i in range(start, stop):
                        marker = ">" if i == index else " "
                        hits.append(f"  {marker}{i + 1}: {lines[i].strip()[:200]}")
            else:
                for index in matched_indexes[:10]:
                    hits.append(f"{rel}:{index + 1}: {lines[index].strip()[:200]}")
            if len(hits) >= MAX_SEARCH_HITS:
                break
        if not hits:
            return ToolResult(name=SEARCH_TEXT_TOOL, ok=True, content=f"No matches for '{query}'")
        body = "\n".join(hits[:MAX_SEARCH_HITS])
        if len(hits) > MAX_SEARCH_HITS:
            body += f"\n… truncated ({MAX_SEARCH_HITS} matches max)"
        return ToolResult(
            name=SEARCH_TEXT_TOOL, ok=True, content=body,
            data={"regex": bool(regex), "hits": min(len(hits), MAX_SEARCH_HITS)},
        )

    async def _search_files(self, pattern: str, path: str | None = None) -> ToolResult:
        if not pattern.strip():
            return ToolResult(name=SEARCH_FILES_TOOL, ok=False, error="Pattern is empty")
        subtree = self.root
        if path:
            try:
                subtree = self.resolve(path)
            except ValueError as exc:
                return ToolResult(name=SEARCH_FILES_TOOL, ok=False, error=str(exc))
            if not subtree.is_dir():
                return ToolResult(name=SEARCH_FILES_TOOL, ok=False, error=f"Not a directory: {path}")
        matches: list[str] = []
        try:
            for root, dirs, files in os.walk(subtree):
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
                for name in files:
                    if fnmatch.fnmatch(name, pattern):
                        matches.append(Path(root, name).relative_to(self.root).as_posix())
                        if len(matches) >= MAX_SEARCH_HITS:
                            break
                if len(matches) >= MAX_SEARCH_HITS:
                    break
        except OSError as exc:
            return ToolResult(name=SEARCH_FILES_TOOL, ok=False, error=f"Cannot search: {exc}")
        if not matches:
            return ToolResult(name=SEARCH_FILES_TOOL, ok=True, content=f"No files match '{pattern}'")
        body = "\n".join(matches)
        if len(matches) >= MAX_SEARCH_HITS:
            body += f"\n… truncated ({MAX_SEARCH_HITS} max)"
        return ToolResult(name=SEARCH_FILES_TOOL, ok=True, content=body)

    async def _create_directory(self, path: str) -> ToolResult:
        if not self._can_write():
            return ToolResult(name=CREATE_DIR_TOOL, ok=False, error="Access is read-only")
        target = self.resolve(path)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return ToolResult(name=CREATE_DIR_TOOL, ok=False, error=f"Cannot create: {exc}")
        return ToolResult(name=CREATE_DIR_TOOL, ok=True, content=f"Created {target.relative_to(self.root)}/")

    async def _delete_file(self, path: str) -> ToolResult:
        if not self._can_write():
            return ToolResult(name=DELETE_FILE_TOOL, ok=False, error="Access is read-only")
        target = self.resolve(path)
        if not target.exists():
            return ToolResult(name=DELETE_FILE_TOOL, ok=False, error=f"No such file: {path}")
        if target == self.root:
            return ToolResult(name=DELETE_FILE_TOOL, ok=False, error="Refusing to delete the workspace root")
        try:
            checkpoint = self._checkpoint(target)
            if target.is_dir():
                shutil.rmtree(target)
                summary = "directory"
            else:
                target.unlink()
                summary = "file"
        except OSError as exc:
            return ToolResult(name=DELETE_FILE_TOOL, ok=False, error=f"Cannot delete: {exc}")
        return ToolResult(
            name=DELETE_FILE_TOOL,
            ok=True,
            content=f"Deleted {summary} {target.relative_to(self.root)}",
            data={"checkpoint": checkpoint},
        )

    async def _move_file(self, source: str, destination: str) -> ToolResult:
        if not self._can_write():
            return ToolResult(name=MOVE_FILE_TOOL, ok=False, error="Access is read-only")
        src = self.resolve(source)
        dst = self.resolve(destination)
        if not src.exists():
            return ToolResult(name=MOVE_FILE_TOOL, ok=False, error=f"No such file: {source}")
        if dst.exists():
            return ToolResult(name=MOVE_FILE_TOOL, ok=False, error=f"Destination exists: {destination}")
        try:
            source_checkpoint = self._checkpoint(src)
            destination_checkpoint = self._checkpoint(dst) if dst.exists() else None
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except (OSError, shutil.Error) as exc:
            return ToolResult(name=MOVE_FILE_TOOL, ok=False, error=f"Cannot move: {exc}")
        return ToolResult(
            name=MOVE_FILE_TOOL,
            ok=True,
            content=f"Moved {src.relative_to(self.root)} → {dst.relative_to(self.root)}",
            data={"source_checkpoint": source_checkpoint, "destination_checkpoint": destination_checkpoint},
        )

    async def _copy_file(self, source: str, destination: str) -> ToolResult:
        if not self._can_write():
            return ToolResult(name=COPY_FILE_TOOL, ok=False, error="Access is read-only")
        src = self.resolve(source)
        dst = self.resolve(destination)
        if not src.exists():
            return ToolResult(name=COPY_FILE_TOOL, ok=False, error=f"No such file: {source}")
        try:
            checkpoint = self._checkpoint(dst) if dst.exists() else None
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except (OSError, shutil.Error) as exc:
            return ToolResult(name=COPY_FILE_TOOL, ok=False, error=f"Cannot copy: {exc}")
        return ToolResult(
            name=COPY_FILE_TOOL,
            ok=True,
            content=f"Copied {src.relative_to(self.root)} → {dst.relative_to(self.root)}",
            data={"checkpoint": checkpoint},
        )

