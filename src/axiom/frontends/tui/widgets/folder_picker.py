"""Folder picker — the user chooses the project folder AXIOM works in.

A real directory browser: type or paste a path, walk folders with the arrow
keys, jump to recent projects or (on Windows) other drives, and confirm. The
screen returns the absolute path of the chosen folder or ``None``.
"""

from __future__ import annotations

import os
import string
import sys
from collections.abc import Iterable
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, OptionList, Static
from textual.widgets.option_list import Option


class FolderTree(DirectoryTree):
    """Directories only (hidden ones last) — files are irrelevant for picking."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        dirs = []
        for path in paths:
            try:
                if path.is_dir():
                    dirs.append(path)
            except OSError:
                continue
        return sorted(dirs, key=lambda p: (p.name.startswith("."), p.name.lower()))


def windows_drives() -> list[str]:
    if sys.platform != "win32":
        return []
    return [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def is_temp_path(path: str | Path) -> bool:
    """Throw-away folders (pytest runs, OS temp) never belong in "recent"."""
    import tempfile

    norm = _norm(path)
    temp = _norm(tempfile.gettempdir())
    return norm == temp or norm.startswith(temp + os.sep) or "pytest-of-" in norm


def useful_recent(paths: Iterable[str], limit: int = 8) -> list[str]:
    """Existing, non-temporary, de-duplicated recent project paths."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        try:
            if not raw or is_temp_path(raw) or not Path(raw).is_dir():
                continue
        except OSError:
            continue
        key = _norm(raw)
        if key in seen:
            continue
        seen.add(key)
        out.append(str(raw))
        if len(out) >= limit:
            break
    return out


def resolve_folder(raw: str, base: Path | None = None) -> Path | None:
    """Expand ``~`` / env vars / relative paths; ``None`` when not a directory."""
    text = os.path.expandvars(raw.strip().strip('"').strip("'"))
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute() and base is not None:
        path = base / path
    try:
        path = path.resolve()
    except OSError:
        return None
    return path if path.is_dir() else None


class FolderPicker(ModalScreen[str | None]):
    """``/open`` — choose the workspace folder."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("backspace", "up", "Up", show=False),
        Binding("ctrl+o", "confirm", "Open", show=False),
    ]

    def __init__(self, start: Path | None = None, recent: list[str] | None = None) -> None:
        super().__init__(id="folder-picker")
        home = Path.home()
        self._current = start if start and start.is_dir() else home
        self._recent = useful_recent(recent or [])
        self._place_paths: dict[str, Path] = {}

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        frame = Vertical(classes="panel", id="folder-frame")
        frame.border_title = "OPEN FOLDER"
        frame.border_subtitle = "↑↓ navigate · → expand · Enter select · Backspace up · Ctrl+O open · Esc cancel"
        with frame:
            yield Static(
                "Choose the folder AXIOM will work in: the agent reads, edits and runs commands only inside it.",
                classes="panel-subtitle",
                markup=False,
            )
            with Horizontal(id="folder-path-row"):
                yield Input(str(self._current), id="folder-path", placeholder="Path, e.g. C:\\Projects\\my-app or ~/code/app")
                yield Button("Up", id="folder-up")
            with Horizontal(id="folder-body"):
                with Vertical(id="folder-side"):
                    yield Static(" PLACES", classes="folder-head", markup=False)
                    yield OptionList(*self._places(), id="folder-places")
                yield FolderTree(str(self._current), id="folder-tree")
            yield Static("", id="folder-info", markup=False)
            with Horizontal(id="folder-actions"):
                yield Button("Cancel", id="folder-cancel")
                yield Button("Open this folder", id="folder-open", variant="primary")

    def _places(self) -> list[Option]:
        """Places + recent projects; option ids are unique even when paths repeat
        (e.g. Home is also the launch folder)."""
        rows: list[Option] = []
        seen: set[str] = set()
        self._place_paths = {}

        def add(glyph: str, style: str, label: str, path: Path) -> None:
            key = _norm(path)
            if key in seen:
                return
            seen.add(key)
            option_id = f"place-{len(self._place_paths)}"
            self._place_paths[option_id] = path
            rows.append(Option(Text.assemble((glyph + " ", style), (label, "")), id=option_id))

        home = Path.home()
        add("⌂", "bold #ff8a5c", "Home", home)
        for name in ("Desktop", "Documents", "Projects", "source", "code"):
            path = home / name
            if path.is_dir():
                add("▸", "#6c6c78", name, path)
        cwd = Path.cwd()
        add("●", "#56d364", "Launch folder", cwd)
        for drive in windows_drives():
            add("◫", "#79c0ff", drive, Path(drive))
        recent_rows: list[Option] = []
        before = len(rows)
        for path in self._recent:
            add("↺", "#d2a8ff", Path(path).name or path, Path(path))
        recent_rows = rows[before:]
        if recent_rows:
            rows.insert(before, Option(Text(" RECENT", style="bold #6c6c78"), id="__recent__", disabled=True))
        return rows

    def on_mount(self) -> None:
        self._describe(self._current)
        self.query_one("#folder-tree", FolderTree).focus()

    # ---------------------------------------------------------------- behaviour

    def _describe(self, path: Path) -> None:
        info = self.query_one("#folder-info", Static)
        try:
            entries = list(os.scandir(path))
        except OSError as exc:
            info.update(Text(f" Cannot read this folder: {exc}", style="#f47067"))
            return
        dirs = sum(1 for e in entries if e.is_dir(follow_symlinks=False))
        files = len(entries) - dirs
        markers = [m for m in (".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod") if (path / m).exists()]
        text = Text(" ")
        text.append(str(path), style="bold #ececf0")
        text.append(f"   {dirs} folders · {files} files", style="#6c6c78")
        if markers:
            text.append("   project: " + ", ".join(markers), style="#56d364")
        info.update(text)

    def _select(self, path: Path, *, reroot: bool = False) -> None:
        self._current = path
        field = self.query_one("#folder-path", Input)
        field.value = str(path)
        field.cursor_position = len(field.value)
        if reroot:
            self.query_one("#folder-tree", FolderTree).path = str(path)
        self._describe(path)

    @on(DirectoryTree.DirectorySelected, "#folder-tree")
    def _tree_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        event.stop()
        self._select(Path(event.path))

    @on(OptionList.OptionSelected, "#folder-places")
    def _place_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        path = self._place_paths.get(str(event.option.id or ""))
        if path is not None:
            if path.is_dir():
                self._select(path, reroot=True)
                self.query_one("#folder-tree", FolderTree).focus()

    @on(Input.Submitted, "#folder-path")
    def _path_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        path = resolve_folder(event.value, self._current)
        if path is None:
            self.query_one("#folder-info", Static).update(Text(f" Not a folder: {event.value}", style="#f47067"))
            return
        if path == self._current:
            self.dismiss(str(path))
        else:
            self._select(path, reroot=True)

    @on(Button.Pressed, "#folder-up")
    def action_up(self) -> None:
        if isinstance(self.focused, Input):
            return  # Backspace edits the path while typing
        parent = self._current.parent
        if parent != self._current:
            self._select(parent, reroot=True)

    @on(Button.Pressed, "#folder-open")
    def action_confirm(self) -> None:
        typed = resolve_folder(self.query_one("#folder-path", Input).value, self._current)
        target = typed or self._current
        if target.is_dir():
            self.dismiss(str(target))

    @on(Button.Pressed, "#folder-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)
