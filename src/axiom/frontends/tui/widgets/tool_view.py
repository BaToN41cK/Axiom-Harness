"""Rich rendering of real tool calls for the TUI chat and activity panel.

Pure functions build :class:`rich.text.Text` from the tool name, the arguments
the model sent and the content the tool returned — nothing is invented: a
preview appears only when the data for it really exists.
"""

from __future__ import annotations

import difflib
from typing import Any

from rich.text import Text
from textual.widgets import Static

#: (glyph, label, colour) per tool kind.
KINDS: dict[str, tuple[str, str, str]] = {
    "read": ("▤", "Read", "#79c0ff"),
    "edit": ("✎", "Edit", "#e3b341"),
    "write": ("✚", "Write", "#e3b341"),
    "patch": ("±", "Patch", "#e3b341"),
    "search": ("⌕", "Search", "#d2a8ff"),
    "files": ("⌕", "Find files", "#d2a8ff"),
    "list": ("▦", "List", "#d2a8ff"),
    "run": ("❯", "Run", "#7ee787"),
    "web": ("◉", "Web search", "#58a6ff"),
    "fetch": ("◎", "Read page", "#58a6ff"),
    "git": ("⎇", "Git", "#f0883e"),
    "delete": ("✖", "Delete", "#f47067"),
    "other": ("⬢", "Tool", "#b9b9b9"),
}

MUTED = "#6c6c78"
TEXT = "#ececf0"
ADD = "#56d364"
DEL = "#f47067"


def kind_of(name: str) -> str:
    return {
        "read_file": "read", "edit_file": "edit", "write_file": "write", "apply_patch": "patch",
        "search_text": "search", "search_files": "files", "list_files": "list", "inspect_project": "list",
        "run_command": "run", "terminal_run": "run", "web_search": "web", "fetch_url": "fetch",
        "delete_file": "delete",
    }.get(name, "git" if name.startswith("git_") else "other")


def _s(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").rstrip("\n").split("\n") if text else []


def target_of(name: str, arguments: dict[str, Any] | None) -> str:
    """The concrete thing a tool works on: path, query, command, URL."""
    args = arguments or {}
    for key in ("path", "query", "command", "url", "pattern", "source", "input", "text"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def touched_path(name: str, arguments: dict[str, Any] | None) -> tuple[str, str] | None:
    """(path, mode) for file tools — mode is R(ead) / E(dit) / W(rite) / D(elete)."""
    kind = kind_of(name)
    path = _s((arguments or {}).get("path"))
    if not path:
        return None
    mode = {"read": "R", "edit": "E", "patch": "E", "write": "W", "delete": "D"}.get(kind)
    return (path, mode) if mode else None


def diff_stats(name: str, arguments: dict[str, Any] | None) -> tuple[int, int] | None:
    args = arguments or {}
    kind = kind_of(name)
    if kind == "edit":
        old, new = _lines(_s(args.get("old_text"))), _lines(_s(args.get("new_text")))
        diff = list(difflib.ndiff(old, new))
        return sum(1 for d in diff if d.startswith("+ ")), sum(1 for d in diff if d.startswith("- "))
    if kind == "write":
        return len(_lines(_s(args.get("content")))), 0
    if kind == "patch":
        rows = _lines(_s(args.get("patch")))
        return (
            sum(1 for r in rows if r.startswith("+") and not r.startswith("+++")),
            sum(1 for r in rows if r.startswith("-") and not r.startswith("---")),
        )
    return None


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(1, width - 1)] + "…"


def render_tool(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    state: str = "running",
    content: str = "",
    detail: str = "",
    duration_ms: int | None = None,
    spinner: str = "◌",
    width: int = 96,
    preview: bool = True,
    compact: bool = False,
) -> Text:
    """One tool block: header line plus an optional small, real preview."""
    kind = kind_of(name)
    glyph, label, colour = KINDS[kind]
    args = arguments or {}
    text = Text(no_wrap=True, overflow="ellipsis")

    if state == "running":
        text.append(f"{spinner} ", style=f"bold {colour}")
    elif state == "ok":
        text.append("✓ ", style=f"bold {ADD}")
    else:
        text.append("✗ ", style=f"bold {DEL}")
    text.append(f"{glyph} {label}", style=f"bold {colour}")
    if kind == "other":
        text.append(f" {name}", style=TEXT)

    target = target_of(name, args)
    if target:
        if kind in ("read", "edit", "write", "patch", "list", "delete") and "/" in target.replace("\\", "/"):
            head, _, base = target.replace("\\", "/").rpartition("/")
            text.append("  ")
            if not compact:
                text.append(_clip(head + "/", max(8, width // 2)), style=MUTED)
            text.append(base, style=f"bold {TEXT}")
        elif kind in ("search", "web"):
            text.append(f"  «{_clip(target, width // 2)}»", style=TEXT)
        elif kind == "run":
            text.append(f"  $ {_clip(target, width // 2)}", style=TEXT)
        else:
            text.append(f"  {_clip(target, width // 2)}", style=TEXT)

    stats = diff_stats(name, args)
    if stats is not None:
        add, rem = stats
        text.append(f"  +{add}", style=f"bold {ADD}")
        if kind != "write":
            text.append(f" -{rem}", style=f"bold {DEL}")
    if kind == "read" and args.get("start_line"):
        end = args.get("end_line")
        text.append(f"  L{args.get('start_line')}{'–' + str(end) if end else '+'}", style=MUTED)
    if kind == "search" and state == "ok" and content:
        hits = sum(1 for line in _lines(content) if line.count(":") >= 2)
        text.append(f"  {hits} match{'es' if hits != 1 else ''}", style=MUTED)
    if duration_ms and state != "running" and not compact:
        text.append(f"  {duration_ms} ms", style=MUTED)
    if state == "failed" and detail and not compact:
        text.append(f"  {_clip(detail, width // 2)}", style=DEL)

    if not preview:
        return text

    # ---- previews (real data only, a few lines max)
    rows: list[Text] = []
    if kind == "edit":
        old, new = _lines(_s(args.get("old_text"))), _lines(_s(args.get("new_text")))
        for line in difflib.ndiff(old, new):
            if line.startswith(("+ ", "- ")):
                sign = line[0]
                rows.append(Text(f"  {sign} {_clip(line[2:], width - 6)}", style=ADD if sign == "+" else DEL))
    elif kind == "write":
        rows = [Text(f"  + {_clip(line, width - 6)}", style=ADD) for line in _lines(_s(args.get("content")))]
    elif kind == "patch":
        for line in _lines(_s(args.get("patch"))):
            style = ADD if line.startswith("+") else DEL if line.startswith("-") else MUTED
            rows.append(Text(f"  {_clip(line, width - 4)}", style=style))
    elif kind == "search" and content:
        for line in _lines(content):
            path, _, rest = line.partition(":")
            num, _, body = rest.partition(":")
            if num.strip().isdigit():
                row = Text("  ")
                row.append(path, style=MUTED)
                row.append(f":{num.strip()} ", style="#8b949e")
                row.append(_clip(body.strip(), max(10, width - len(path) - 10)), style=TEXT)
                rows.append(row)
    elif kind == "run" and content and state != "running":
        rows = [Text(f"  │ {_clip(line, width - 6)}", style="#c9d1d9" if state == "ok" else DEL) for line in _lines(content)[-6:]]

    limit = 8
    if rows:
        for row in rows[:limit]:
            text.append("\n")
            text.append_text(row)
        if len(rows) > limit:
            text.append(f"\n  … {len(rows) - limit} more line(s)", style=MUTED)
    return text


class ToolBlock(Static):
    """One tool invocation in the chat timeline (updates in place)."""

    def __init__(self, name: str, arguments: dict[str, Any] | None) -> None:
        super().__init__("", classes="tool-line tool-block", markup=False)
        self.tool_name = name
        self.arguments = dict(arguments or {})
        self.state = "running"
        self.content = ""
        self.detail = ""
        self.duration_ms: int | None = None
        self._spin = 0

    def on_mount(self) -> None:
        self.redraw()

    def tick(self, spinner: str) -> None:
        if self.state == "running":
            self.update(render_tool(self.tool_name, self.arguments, state="running", spinner=spinner, width=self._width()))

    def finish(self, ok: bool, *, content: str = "", detail: str = "", duration_ms: int | None = None) -> None:
        self.state = "ok" if ok else "failed"
        self.content = content or ""
        self.detail = detail
        self.duration_ms = duration_ms
        self.set_class(not ok, "failed")
        self.redraw()

    def _width(self) -> int:
        return max(40, (self.size.width or 96) - 2)

    def redraw(self) -> None:
        self.update(
            render_tool(
                self.tool_name,
                self.arguments,
                state=self.state,
                content=self.content,
                detail=self.detail,
                duration_ms=self.duration_ms,
                width=self._width(),
            )
        )
