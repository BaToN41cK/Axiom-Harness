"""Right-hand workspace panel: project tree, files in focus, live agent activity.

Everything shown is real: the tree is the actual workspace on disk, "files in
focus" are the paths the agent's file tools really touched, and the activity
log mirrors the ToolCall/ToolResult events of the core stream.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DirectoryTree, OptionList, Static
from textual.widgets.option_list import Option

from axiom.frontends.tui.widgets.tool_view import KINDS, kind_of, render_tool, touched_path
from axiom.shared import formatting as fmt

#: Only VCS internals and bytecode caches are hidden — every project file is shown.
IGNORED = {".git", "__pycache__"}
#: How often the tree checks the disk for added / removed / renamed entries.
WATCH_SECONDS = 2.0
MAX_ACTIVITY = 14
MAX_FILES = 10
#: Below this terminal width the panel hides itself (unless forced open).
AUTO_HIDE_WIDTH = 110

MODE_STYLE = {"R": ("read", "#79c0ff"), "E": ("edited", "#e3b341"), "W": ("written", "#56d364"), "D": ("deleted", "#f47067")}


class WorkspaceTree(DirectoryTree):
    """Every file of the project (only ``.git`` / bytecode caches hidden)."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if p.name not in IGNORED and not p.name.endswith(".pyc")]

    def expanded_dirs(self) -> list[Path]:
        """Directories whose listing is currently on screen (root included)."""
        out: list[Path] = []
        stack = [self.root]
        while stack:
            node = stack.pop()
            if node.data is not None and (node is self.root or (node.allow_expand and node.is_expanded)):
                out.append(Path(node.data.path))
                stack.extend(node.children)
        return out


def _signature(dirs: list[Path]) -> tuple:
    sig = []
    for path in dirs:
        try:
            sig.append((str(path), path.stat().st_mtime_ns))
        except OSError:
            sig.append((str(path), -1))
    return tuple(sorted(sig))


class ActivityPanel(Vertical):
    """Workspace tree + files in focus + agent activity."""

    class FileChosen(Message):
        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    class OpenRequested(Message):
        """Open a project: ``path=None`` → show the folder picker."""

        def __init__(self, path: str | None = None) -> None:
            self.path = path
            super().__init__()

    class CloseRequested(Message):
        """Close the current project folder."""

    def __init__(self, root: Path | None, **kwargs: Any) -> None:
        super().__init__(id="activity-panel", **kwargs)
        self._root = root
        self._events: list[dict[str, Any]] = []
        self._files: list[tuple[str, str, float]] = []
        self._tick = 0
        self._timer = None
        self._watch = None
        self._sig: tuple = ()
        self._recent: list[Any] = []
        self._recent_paths: dict[str, str] = {}
        self.forced: bool | None = None  # None → automatic by width

    # ------------------------------------------------------------------ layout

    def compose(self):
        yield Static(self._header(), id="activity-title", markup=False)
        with Vertical(id="activity-tree-host"):
            yield from self._tree_widgets()
        yield Static(self._title("FILES IN FOCUS", ""), classes="activity-head", markup=False)
        yield Static("  The agent has not touched files yet.", id="activity-files", markup=False)
        yield Static(self._title("AGENT ACTIVITY", ""), classes="activity-head", markup=False)
        yield Static("  Idle — tool calls will appear here.", id="activity-log", markup=False)

    def _header(self) -> Text:
        if self._root is None:
            return self._title("PROJECT", "not selected")
        return self._title("PROJECT", self._root.name or str(self._root))

    def _tree_widgets(self):
        if self._root is not None and self._root.is_dir():
            yield Static(Text(f" {self._root}", style="#6c6c78", no_wrap=True, overflow="ellipsis"), classes="activity-path")
            # Built explicitly (not ``with``): also used by mount_all() outside compose.
            yield Horizontal(
                Button("＋ Open another", id="panel-add", classes="activity-btn", tooltip="Open another project folder (Ctrl+O)"),
                Button("✕ Close", id="panel-close", classes="activity-btn activity-btn-close", tooltip="Close project"),
                classes="activity-actions",
            )
            yield WorkspaceTree(str(self._root), id="activity-tree")
            return
        intro = Text()
        intro.append("\n No project open\n", style="bold #ececf0")
        intro.append(" Add a folder to start.\n", style="#9a9aa6")
        intro.append(" The agent works only inside it.", style="#6c6c78")
        yield Static(intro, classes="activity-empty", id="activity-empty")
        yield Button("＋  Add project folder", id="panel-open", variant="primary", classes="activity-open")
        from axiom.frontends.tui.widgets.folder_picker import useful_recent

        by_path = {str(getattr(p, "path", p)): p for p in self._recent}
        recent = useful_recent([str(getattr(p, "path", p)) for p in self._recent])
        self._recent_paths = {f"recent-{i}": path for i, path in enumerate(recent)}
        if recent:
            yield Static(self._title("RECENT PROJECTS", "click to open"), classes="activity-head activity-recent-head", markup=False)
            yield OptionList(
                *[self._recent_option(by_path.get(path, path), f"recent-{i}") for i, path in enumerate(recent)],
                id="activity-recent",
            )
        tip = Text()
        tip.append("\n Ctrl+O", style="bold #ff8a5c")
        tip.append(" picker   ", style="#6c6c78")
        tip.append("/open <path>", style="bold #ff8a5c")
        tip.append(" direct", style="#6c6c78")
        yield Static(tip, classes="activity-tip")

    @staticmethod
    def _recent_option(project: Any, option_id: str) -> Option:
        path = str(getattr(project, "path", project))
        name = getattr(project, "name", None) or Path(path).name or path
        kind = getattr(project, "kind", "") or ""
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append("▸ ", style="#ff8a5c")
        text.append(name, style="bold #ececf0")
        meta = " · ".join(x for x in (kind if kind != "Unknown" else "", "git" if getattr(project, "git", False) else "") if x)
        if meta:
            text.append(f"  {meta}", style="#6c6c78")
        text.append(f"\n  {path}", style="#4a4a54")
        return Option(text, id=option_id)

    def set_recent(self, projects: list[Any]) -> None:
        """Recent projects shown in the empty state (most recent first)."""
        self._recent = list(projects or [])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ("panel-open", "panel-switch", "panel-add"):
            event.stop()
            self.post_message(self.OpenRequested(None))
        elif event.button.id == "panel-close":
            event.stop()
            self.post_message(self.CloseRequested())

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        path = self._recent_paths.get(str(event.option.id or ""))
        if path:
            event.stop()
            self.post_message(self.OpenRequested(path))

    @property
    def root(self) -> Path | None:
        return self._root

    async def set_root(self, root: Path | None) -> None:
        """Swap the tree to another folder (or the empty state)."""
        self._root = root
        self._files = []
        self._sig = ()
        self.query_one("#activity-title", Static).update(self._header())
        host = self.query_one("#activity-tree-host", Vertical)
        await host.remove_children()
        await host.mount_all(list(self._tree_widgets()))
        try:
            self.query_one("#activity-files", Static).update(Text("  The agent has not touched files yet.", style="#6c6c78"))
        except Exception:  # pragma: no cover
            pass

    def _tree(self) -> WorkspaceTree | None:
        try:
            return self.query_one("#activity-tree", WorkspaceTree)
        except Exception:
            return None

    def refresh_tree(self) -> None:
        """Re-read the disk now (keeps expanded folders and the cursor)."""
        tree = self._tree()
        if tree is not None:
            tree.reload()
            self._sig = _signature(tree.expanded_dirs())

    def _check_disk(self) -> None:
        tree = self._tree()
        if tree is None or not self.display:
            return
        sig = _signature(tree.expanded_dirs())
        if self._sig and sig != self._sig:
            # Only listings matter: a dir's mtime changes when entries are
            # added, removed or renamed — by the agent or by anyone else.
            tree.reload()
        self._sig = sig

    @staticmethod
    def _title(label: str, extra: str) -> Text:
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append(f" {label}", style="bold #9a9aa6")
        if extra:
            text.append(f"  {extra}", style="bold #ececf0")
        return text

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.15, self._animate, pause=True)
        self._watch = self.set_interval(WATCH_SECONDS, self._check_disk)

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        path = Path(event.path)
        try:
            rel = path.relative_to(self._root) if self._root else path
        except ValueError:
            rel = path
        self.post_message(self.FileChosen(rel.as_posix()))

    # ------------------------------------------------------------------ events

    def tool_started(self, name: str, arguments: dict[str, Any] | None) -> None:
        self._events.append({"name": name, "args": dict(arguments or {}), "state": "running", "ms": None, "error": "", "t": time.time()})
        self._events = self._events[-MAX_ACTIVITY:]
        touched = touched_path(name, arguments)
        if touched:
            path, mode = touched
            self._files = [f for f in self._files if f[0] != path]
            self._files.append((path, mode, time.time()))
            self._files = self._files[-MAX_FILES:]
            self._draw_files()
        if self._timer is not None:
            self._timer.resume()
        self._draw_log()

    def tool_finished(self, name: str, ok: bool, duration_ms: int | None, error: str | None) -> None:
        for event in reversed(self._events):
            if event["name"] == name and event["state"] == "running":
                event["state"] = "ok" if ok else "failed"
                event["ms"] = duration_ms
                event["error"] = error or ""
                break
        if not any(e["state"] == "running" for e in self._events) and self._timer is not None:
            self._timer.pause()
        self._draw_log()

    # ------------------------------------------------------------------ drawing

    def _animate(self) -> None:
        self._tick += 1
        self._draw_log()

    def _width(self) -> int:
        return max(24, (self.size.width or 40) - 2)

    def _draw_files(self) -> None:
        try:
            widget = self.query_one("#activity-files", Static)
        except Exception:  # pragma: no cover - not composed yet
            return
        if not self._files:
            return
        text = Text(no_wrap=True, overflow="ellipsis")
        width = self._width()
        latest = self._files[-1][0]
        for index, (path, mode, _) in enumerate(reversed(self._files)):
            label, colour = MODE_STYLE.get(mode, ("", "#b9b9b9"))
            head, _, base = path.replace("\\", "/").rpartition("/")
            marker = "▸" if path == latest else " "
            text.append(f" {marker} ", style="bold #ff8a5c" if path == latest else "")
            text.append(f"{mode} ", style=f"bold {colour}")
            room = max(6, width - len(base) - 6)
            if head:
                text.append((head[-room:] if len(head) > room else head) + "/", style="#6c6c78")
            text.append(base, style="bold #ececf0" if path == latest else "#b9b9b9")
            if index < len(self._files) - 1:
                text.append("\n")
        widget.update(text)

    def _draw_log(self) -> None:
        try:
            widget = self.query_one("#activity-log", Static)
        except Exception:  # pragma: no cover
            return
        if not self._events:
            return
        text = Text(no_wrap=True, overflow="ellipsis")
        spinner = fmt.spinner_frame(self._tick)
        width = self._width()
        for index, event in enumerate(reversed(self._events)):
            text.append(" ")
            text.append_text(
                render_tool(
                    event["name"], event["args"], state=event["state"], detail=event["error"],
                    duration_ms=event["ms"], spinner=spinner, width=width, preview=False, compact=True,
                )
            )
            if index < len(self._events) - 1:
                text.append("\n")
        widget.update(text)

    @staticmethod
    def legend() -> str:
        return "  ".join(f"{glyph} {label}" for glyph, label, _ in (KINDS[k] for k in ("read", "edit", "search", "run")))

    @staticmethod
    def kind(name: str) -> str:
        return kind_of(name)
