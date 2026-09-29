"""AXIOM.md / rules discovery and relevance-filtered merging (W4.5).

Rules are plain Markdown files that constrain how the agent works inside a
workspace. They come from four scopes, merged with a deterministic
precedence — later entries in :data:`SCOPE_ORDER` win on conflict:

``global``     → ``<AXIOM_HOME>/AXIOM.md``
``project``    → ``<workspace>/AXIOM.md`` or ``<workspace>/.axiom/project.md``
``directory``  → any ``AXIOM.md`` between the workspace root and a task path
``task``       → rules explicitly requested by the user (``@``-mentions)

Directory rules are attached only when the task actually touches a path
under that directory — rules of irrelevant directories never reach the
model. User-requested (task) rules always win over auto-discovered ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from axiom.core.config import axiom_home
from axiom.core.mentions import mentioned_files

#: Rule file names recognised in the workspace root and in directories.
ROOT_RULE_FILES: tuple[str, ...] = ("AXIOM.md", ".axiom/project.md")
DIRECTORY_RULE_FILE = "AXIOM.md"
GLOBAL_RULE_FILE = "AXIOM.md"

#: Hard caps — rules must never eat the whole system prompt.
MAX_RULE_CHARS = 6000
MAX_RULES_BLOCK_CHARS = 6000
MAX_DIRECTORY_RULES = 8

#: Directories whose rule files are never discovered.
_PRUNE_DIRS = frozenset({".git", ".axiom", "node_modules", ".venv", "venv",
                         "__pycache__", "dist", "build", ".mypy_cache",
                         ".pytest_cache", ".ruff_cache"})

#: Deterministic scope precedence — higher index wins on duplicate sections.
SCOPE_ORDER: tuple[str, ...] = ("global", "project", "directory", "task")


@dataclass(frozen=True)
class RuleSource:
    """One discovered rule file and its scope."""

    scope: str            # global | project | directory | task
    path: str             # absolute path on disk
    content: str
    rel: str = ""         # workspace-relative path (empty for global scope)
    root: str = ""        # workspace-relative directory the rule governs


@dataclass
class RuleReport:
    """What was discovered and what made it into the final block."""

    included: list[RuleSource] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    total_chars: int = 0


def _read(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        pass
    return ""


def _norm_rel(path: Path) -> str:
    return path.as_posix().strip("/")


def _rule_dirs_for_paths(root: Path, task_paths: list[str]) -> set[str]:
    """Workspace-relative directories containing the task paths."""
    dirs: set[str] = set()
    for raw in task_paths:
        rel = _norm_rel(Path(str(raw).replace("\\", "/")))
        if not rel or rel.startswith(".."):
            continue
        parts = rel.split("/")
        if len(parts) >= 2:
            candidate = "/".join(parts[:-1])
            if (root / candidate).is_dir():
                dirs.add(candidate)
        elif len(parts) == 1 and (root / parts[0]).is_dir():
            dirs.add(parts[0])
    return dirs


def _walk_task_paths(text: str) -> list[str]:
    """Extract path-like tokens from task text (deterministic, no fs access)."""
    tokens = re.findall(r"[A-Za-z0-9_.~+-]+(?:[\\/][A-Za-z0-9_.~+-]+)+", text or "")
    return [t.replace("\\", "/") for t in tokens]


def discover_rules(workspace_root: Path | str | None) -> list[RuleSource]:
    """Discover all rule sources: global, project root and every directory.

    The workspace walk prunes heavy directories and never leaves the
    workspace root. Content is read eagerly but capped per file.
    """
    sources: list[RuleSource] = []
    global_path = axiom_home() / GLOBAL_RULE_FILE
    content = _read(global_path)
    if content:
        sources.append(RuleSource(scope="global", path=str(global_path),
                                  content=content[:MAX_RULE_CHARS]))
    root: Path | None = None
    if workspace_root:
        try:
            root = Path(workspace_root).expanduser().resolve()
        except OSError:
            root = None
    if root is None or not root.is_dir():
        return sources
    for name in ROOT_RULE_FILES:
        candidate = root / name
        content = _read(candidate)
        if content:
            sources.append(RuleSource(scope="project", path=str(candidate),
                                      content=content[:MAX_RULE_CHARS],
                                      rel=name))
    try:
        for path in sorted(root.rglob(DIRECTORY_RULE_FILE)):
            if any(part in _PRUNE_DIRS for part in path.parts):
                continue
            try:
                if not path.is_file() or not path.resolve().is_relative_to(root):
                    continue
                rel_dir = _norm_rel(path.parent.resolve().relative_to(root))
            except (OSError, ValueError):
                continue
            if rel_dir == "":
                continue  # root AXIOM.md is the project rule, not a directory one
            content = _read(path)
            if content:
                sources.append(RuleSource(
                    scope="directory", path=str(path),
                    content=content[:MAX_RULE_CHARS],
                    rel=_norm_rel(path.resolve().relative_to(root)),
                    root=rel_dir,
                ))
    except OSError:
        pass
    return sources


def _section_keys(content: str) -> set[str]:
    """Markdown headings — used to detect rule conflicts deterministically."""
    return {line.strip().lstrip("#").strip().casefold()
            for line in content.splitlines() if line.lstrip().startswith("#")}


class RuleManager:
    """Workspace-scoped rule discovery + relevance-filtered merging (W4.5)."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root: Path | None = None
        if workspace_root:
            try:
                self.workspace_root = Path(workspace_root).expanduser().resolve()
            except OSError:
                self.workspace_root = None
        self._sources: list[RuleSource] | None = None
        self.last_report = RuleReport()

    def set_workspace(self, workspace_root: Path | str | None) -> None:
        """Rebind to a new workspace; the next lookup re-discovers rules."""
        root: Path | None = None
        if workspace_root:
            try:
                root = Path(workspace_root).expanduser().resolve()
            except OSError:
                root = None
        if root != self.workspace_root:
            self.workspace_root = root
            self._sources = None
            self.last_report = RuleReport()

    @property
    def sources(self) -> list[RuleSource]:
        if self._sources is None:
            self._sources = discover_rules(self.workspace_root)
        return self._sources

    def project_rules_block(self) -> str:
        """Static workspace rules for the base system prompt (always survive).

        Global + project rules only — directory rules are task-dependent and
        are attached per task via :meth:`merged_rules`. The block is budget-
        capped so a huge AXIOM.md can never flood the system prompt.
        """
        parts: list[str] = []
        used = 0
        for source in self.sources:
            if source.scope not in ("global", "project"):
                continue
            label = source.rel or f"global ({source.path})"
            block = f"Rules from {label}:\n{source.content}"
            if used + len(block) > MAX_RULES_BLOCK_CHARS and parts:
                continue
            parts.append(block)
            used += len(block)
        return "\n\n".join(parts)

    def merged_rules(self, task_text: str = "",
                     task_paths: list[str] | None = None,
                     *, include_static: bool = False) -> str:
        """Render the final rules block; user-requested rules win conflicts.

        Conflict resolution is deterministic: when a higher-precedence scope
        redefines a Markdown section (same heading), the lower-precedence
        section is dropped entirely. Rendering is budget-capped; the global
        and project rules always survive, directory rules yield first.
        ``include_static=False`` returns only the task-relevant delta
        (directory + task rules) — use it when the static block is already
        present in the base system prompt.
        """
        sources = self.relevant(task_text, task_paths)
        if not include_static:
            sources = [s for s in sources if s.scope in ("directory", "task")]
        if not sources:
            return ""
        winner_sections: set[str] = set()
        rendered: list[tuple[int, str, str]] = []  # (precedence, label, body)
        for source in reversed(sources):           # task first — it wins
            precedence = SCOPE_ORDER.index(source.scope)
            body = self._drop_shadowed_sections(source.content, winner_sections)
            winner_sections |= _section_keys(source.content)
            if body.strip():
                label = source.rel or f"global ({source.path})"
                rendered.append((precedence, label, body.strip()))
        rendered.sort(key=lambda item: item[0])
        blocks: list[str] = []
        used = 0
        for _precedence, label, body in rendered:
            block = f"## Rules from {label}\n{body}"
            if used + len(block) > MAX_RULES_BLOCK_CHARS and blocks:
                continue  # lower-precedence rules yield first
            blocks.append(block)
            used += len(block)
        if not blocks and rendered:
            _, label, body = rendered[-1]
            blocks.append(f"## Rules from {label}\n{body}"[:MAX_RULES_BLOCK_CHARS])
        return "\n\n".join(blocks)

    def _task_rule_sources(self, task_text: str) -> list[RuleSource]:
        """Rules the user explicitly requested via ``@``-mentions (win last)."""
        if self.workspace_root is None:
            return []
        out: list[RuleSource] = []
        for rel in mentioned_files(task_text or "", self.workspace_root):
            name = rel.split("/")[-1]
            if not name.endswith(".md"):
                continue
            content = _read(self.workspace_root / rel)
            if content:
                out.append(RuleSource(scope="task",
                                      path=str(self.workspace_root / rel),
                                      content=content[:MAX_RULE_CHARS],
                                      rel=rel))
        return out


    def _candidate_paths(self, task_text: str, task_paths: list[str] | None) -> list[str]:
        paths = [p for p in (task_paths or []) if p]
        paths.extend(p for p in _walk_task_paths(task_text) if p not in paths)
        return paths

    def relevant(self, task_text: str = "",
                 task_paths: list[str] | None = None) -> list[RuleSource]:
        """Deterministically ordered, relevance-filtered rule sources.

        Global and project rules always apply. Directory rules are attached
        only when the task touches a path under their directory. Task rules
        (user-requested) always apply and are ordered last so they win.
        """
        report = RuleReport()
        paths = self._candidate_paths(task_text, task_paths)
        task_dirs: set[str] = set()
        if self.workspace_root is not None:
            task_dirs = _rule_dirs_for_paths(self.workspace_root, paths)
        selected: list[RuleSource] = []
        directory_count = 0
        for source in self.sources:
            if source.scope == "directory":
                root = source.root
                hit = bool(root) and any(d == root or d.startswith(root + "/")
                                         for d in task_dirs)
                if hit and directory_count < MAX_DIRECTORY_RULES:
                    selected.append(source)
                    directory_count += 1
                else:
                    report.skipped.append(source.rel)
            else:
                selected.append(source)
        selected.extend(self._task_rule_sources(task_text))
        report.included = list(selected)
        report.total_chars = sum(len(s.content) for s in selected)
        self.last_report = report
        return selected

    @staticmethod
    def _drop_shadowed_sections(content: str, winner_sections: set[str]) -> str:
        """Remove sections whose heading a higher-precedence rule redefines."""
        if not winner_sections:
            return content
        lines = content.splitlines()
        kept: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.lstrip().startswith("#"):
                heading = line.strip().lstrip("#").strip().casefold()
                level = len(line) - len(line.lstrip("#"))
                if heading in winner_sections:
                    i += 1
                    while i < len(lines):
                        nxt = lines[i]
                        if nxt.lstrip().startswith("#") and \
                                len(nxt) - len(nxt.lstrip("#")) <= level:
                            break
                        i += 1
                    continue
            kept.append(line)
            i += 1
        return "\n".join(kept)


