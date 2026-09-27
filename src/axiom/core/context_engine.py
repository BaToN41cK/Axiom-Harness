"""Context Engine — что отправить модели (п.9).

Собирает: user request + relevant files + symbols + git diff +
previous trajectory + skills + tool results + project rules.
Компрессия — через summarizer-колбэк; Trajectory остаётся целой.

W4.3: релевантный контекст под явными категорийными бюджетами.
``build_task_context`` ранжирует файлы (явные пути задачи → упомянутые в
тексте → один уровень Python-импортов), дедуплицирует и обрезает каждую
категорию по её бюджету, а в ``report['categories']`` возвращает фактические
размеры — промпт никогда не содержит весь проект.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from axiom.core.context import ContextManager

Summarizer = Callable[[str], Awaitable[str | None]]

#: Категории бюджета (W4.3). Каждая обрезается независимо, чтобы одна большая
#: категория (например, файлы) не вытеснила остальные полностью.
DEFAULT_CATEGORY_BUDGETS: dict[str, int] = {
    "system": 4000,
    "project": 2000,
    "task": 4000,
    "files": 24000,
    "tool_results": 6000,
    "conversation": 16000,
}

#: Максимум файлов в одну сборку (ранжирование выбирает самые релевантные).
_MAX_FILES = 12
#: Максимум символов одного файла в контексте.
_MAX_FILE_CHARS = 6000
#: Расширения, по которым можно извлечь один уровень импортов.
_IMPORT_SUFFIXES = {".py"}
#: Тяжёлые каталоги, которые не участвуют в ранжировании.
_PRUNE_DIRS = {".git", ".axiom", "node_modules", ".venv", "venv", "__pycache__",
               "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
#: Имена, слишком короткие/общие для поиска упоминаний файлов в тексте задачи.
_STOP_STEMS = {"index", "main", "app", "init", "test", "tests", "src", "lib",
               "core", "ui", "api", "utils", "helpers", "types", "config"}


@dataclass
class BuiltContext:
    messages: list[dict] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    git_diff: str = ""
    trajectory_summary: str = ""
    compressed: bool = False
    report: dict = field(default_factory=dict)


class CompactionState(BaseModel):
    """Structured working state retained when a long task is compacted (W4.4)."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(default="", max_length=8000)
    plan: list[str] = Field(default_factory=list, max_length=32)
    decisions: list[str] = Field(default_factory=list, max_length=64)
    changed_files: list[str] = Field(default_factory=list, max_length=256)
    errors: list[str] = Field(default_factory=list, max_length=128)
    tests: list[str] = Field(default_factory=list, max_length=128)
    important_context: list[str] = Field(default_factory=list, max_length=128)


@dataclass
class StructuredCompaction:
    """Result of W4.4 compaction; original messages are never mutated."""

    messages: list[dict]
    state: CompactionState
    compacted: bool
    trigger_tokens: int
    original_messages: int


class ContextEngine:
    def __init__(self, max_tokens: int | None = None) -> None:
        self._manager = ContextManager(max_tokens=max_tokens)

    def estimate(self, text: str) -> int:
        return int(len(text or "") / 4)

    def _read_files(self, root: Path | None, paths: list[str], budget_chars: int = 24000) -> list[str]:
        chunks: list[str] = []
        if root is None:
            return chunks
        used = 0
        for rel in paths[:12]:
            try:
                target = (root / rel).resolve()
                if root.resolve() not in target.parents and target != root.resolve():
                    continue
                text = target.read_text(encoding="utf-8", errors="replace")
                block = f"### {rel}\n{text[:6000]}"
                if used + len(block) > budget_chars:
                    break
                chunks.append(block)
                used += len(block)
            except Exception:
                continue
        return chunks

    def _git_diff(self, root: Path | None, limit: int = 8000) -> str:
        if root is None:
            return ""
        try:
            import subprocess
            proc = subprocess.run(["git", "diff", "--no-color"], cwd=root,
                                  stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=10, check=False)
            out = proc.stdout or ""
            return out[:limit]
        except Exception:
            return ""

    def build(self, user_text: str, history: list[dict], *,
              system_prompt: str = "", workspace_root: Path | str | None = None,
              file_paths: list[str] | None = None, skills: list[str] | None = None,
              tool_results: list[str] | None = None,
              trajectory_tail: list[dict] | None = None) -> BuiltContext:
        root = Path(workspace_root) if workspace_root else None
        files = self._read_files(root, file_paths or [], budget_chars=24000)
        git_diff = self._git_diff(root)
        blocks: list[str] = []
        if skills:
            blocks.append("Skills:\n" + "\n".join(f"- {s}" for s in skills[:12]))
        if trajectory_tail:
            tail = trajectory_tail[-8:]
            blocks.append("Previous trajectory:\n" + "\n".join(
                f"- [{t.get('kind')}] {t.get('summary')}" for t in tail))
        if tool_results:
            blocks.append("Tool results:\n" + "\n".join(tool_results[-6:])[:6000])
        if files:
            blocks.append("Relevant files:\n" + "\n\n".join(files))
        if git_diff.strip():
            blocks.append("Git diff:\n" + git_diff)
        context_block = "\n\n".join(blocks)
        system = system_prompt or ""
        if context_block:
            system = f"{system}\n\n{context_block}".strip()
        messages = self._manager.prepare(list(history or []), system or None)
        report = {"estimated_tokens": self._manager.report.estimated_tokens,
                  "kept": self._manager.report.kept_count, "files": len(files),
                  "git_diff_chars": len(git_diff)}
        return BuiltContext(messages=messages, files=[f.splitlines()[0] for f in files],
                            git_diff=git_diff, report=report)

    # ------------------------------------------------------- W4.3: ranking

    def _walk_files(self, root: Path, limit: int = 2000) -> list[Path]:
        """Собрать файлы проекта, отсекая тяжёлые каталоги (детерминированно)."""
        files: list[Path] = []
        try:
            for path in sorted(root.rglob("*")):
                if len(files) >= limit:
                    break
                if any(part in _PRUNE_DIRS for part in path.parts):
                    continue
                if path.is_file():
                    files.append(path)
        except OSError:
            return files
        return files

    def _py_imports(self, path: Path, root: Path) -> list[Path]:
        """Один уровень локальных Python-импортов файла (best-effort)."""
        if path.suffix != ".py":
            return []
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            return []
        found: list[Path] = []
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.Import):
                module = node.names[0].name if node.names else ""
            elif isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            if not module:
                continue
            rel = Path(*module.split("."))
            for candidate in (root / rel.with_suffix(".py"), root / rel / "__init__.py"):
                try:
                    if candidate.is_file() and candidate.resolve().is_relative_to(root.resolve()):
                        found.append(candidate)
                        break
                except OSError:
                    continue
        return found

    def rank_files(self, root: Path | str, task_text: str,
                   explicit_paths: list[str] | None = None,
                   changed_files: list[str] | None = None,
                   import_depth: int = 1) -> list[str]:
        """Отранжировать файлы по релевантности задаче (W4.3)."""
        root_p = Path(root).resolve()
        explicit_paths = explicit_paths or []
        changed_files = changed_files or []
        ranked: list[tuple[int, str]] = []
        seen: set[str] = set()

        def add(path: Path, score: int) -> None:
            try:
                rel = path.resolve().relative_to(root_p).as_posix()
            except (OSError, ValueError):
                return
            if rel in seen:
                return
            seen.add(rel)
            ranked.append((score, rel))

        for raw in explicit_paths:
            add(root_p / raw, 0)
        for raw in changed_files:
            add(root_p / raw, 1)

        text = (task_text or "").casefold()
        mentioned: list[tuple[int, str, Path]] = []
        for path in self._walk_files(root_p):
            stem = path.stem.casefold()
            if not stem or stem in _STOP_STEMS:
                continue
            if re.search(rf"(?<![\w]){re.escape(stem)}(?![\w])", text):
                mentioned.append((2, path.name, path))
        for _, _, path in sorted(mentioned, key=lambda item: item[1]):
            add(path, 2)

        if import_depth >= 1:
            seeds = [root_p / raw for raw in [*explicit_paths, *changed_files]]
            for seed in seeds:
                try:
                    seed = seed.resolve()
                    if not seed.is_file():
                        continue
                    for imp in self._py_imports(seed, root_p):
                        add(imp, 3)
                except OSError:
                    continue

        ranked.sort(key=lambda item: (item[0], item[1]))
        return [rel for _, rel in ranked[:_MAX_FILES]]

    # ------------------------------------------------------- W4.3: budgeted build

    def _read_budgeted_files(self, root: Path, rel_paths: list[str],
                             budget_chars: int) -> tuple[list[str], list[str]]:
        """Прочитать файлы в пределах бюджета; вернуть (блоки, включённые пути)."""
        blocks: list[str] = []
        included: list[str] = []
        used = 0
        for rel in rel_paths:
            try:
                target = (root / rel).resolve()
                if not target.is_file() or not target.is_relative_to(root.resolve()):
                    continue
                text = target.read_text(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                continue
            block = f"### {rel}\n{text[:_MAX_FILE_CHARS]}"
            if used + len(block) > budget_chars:
                continue
            blocks.append(block)
            included.append(rel)
            used += len(block)
        if not blocks and rel_paths and budget_chars > 0:
            # No complete file fits: retain a bounded excerpt of the highest-ranked one.
            for rel in rel_paths:
                try:
                    target = (root / rel).resolve()
                    if target.is_file() and target.is_relative_to(root.resolve()):
                        text = target.read_text(encoding="utf-8", errors="replace")
                        blocks.append(f"### {rel}\n{text[:_MAX_FILE_CHARS]}"[:budget_chars])
                        included.append(rel)
                        break
                except (OSError, ValueError):
                    continue
        return blocks, included

    def build_task_context(
        self,
        task_text: str,
        history: list[dict],
        *,
        system_prompt: str = "",
        project_context: str = "",
        workspace_root: Path | str | None = None,
        explicit_paths: list[str] | None = None,
        changed_files: list[str] | None = None,
        tool_results: list[str] | None = None,
        trajectory_tail: list[dict] | None = None,
        budgets: dict[str, int] | None = None,
    ) -> BuiltContext:
        """Собрать релевантный контекст под категорийными бюджетами (W4.3)."""
        budgets = {**DEFAULT_CATEGORY_BUDGETS, **(budgets or {})}
        if any(not isinstance(value, int) or value < 0 for value in budgets.values()):
            raise ValueError("Context budgets must be non-negative integers")
        root = Path(workspace_root) if workspace_root else None

        ranked: list[str] = []
        file_blocks: list[str] = []
        if root is not None:
            ranked = self.rank_files(root, task_text, explicit_paths, changed_files)
            file_blocks, ranked = self._read_budgeted_files(root, ranked, budgets["files"])

        def clip(text: str, budget: int) -> str:
            return text[: max(0, budget)]

        clipped_system = clip(system_prompt, budgets["system"])
        clipped_project = clip(project_context, budgets["project"])
        clipped_task = clip(task_text, budgets["task"])
        trajectory_text = "\n".join(
            f"- [{item.get('kind')}] {item.get('summary')}" for item in (trajectory_tail or [])[-8:]
        )
        clipped_tools = clip("\n".join((tool_results or [])[-6:]), budgets["tool_results"])
        if trajectory_text:
            clipped_tools = clip("\n".join(filter(None, (clipped_tools, trajectory_text))), budgets["tool_results"])
        sections = [clipped_system]
        if clipped_project:
            sections.append("Project:\n" + clipped_project)
        if clipped_task:
            sections.append("Current task:\n" + clipped_task)
        if clipped_tools:
            sections.append("Tool results and trajectory:\n" + clipped_tools)
        if file_blocks:
            sections.append("Relevant files:\n" + "\n\n".join(file_blocks))
        system = "\n\n".join(section for section in sections if section)

        conversation: list[dict] = []
        remaining = budgets["conversation"]
        for item in reversed(history or []):
            if remaining <= 0:
                break
            content = str(item.get("content") or "")
            if not content:
                continue
            kept = clip(content, remaining)
            conversation.append({**item, "content": kept})
            remaining -= len(kept)
        conversation.reverse()
        messages = self._manager.prepare(conversation, system or None)

        categories = {
            "system": len(clipped_system),
            "project": len(clipped_project),
            "task": len(clipped_task),
            "files": sum(len(b) for b in file_blocks),
            "tool_results": len(clipped_tools),
            "conversation": sum(len(str(m.get("content") or "")) for m in messages
                                if m.get("role") != "system"),
        }
        report = {
            "estimated_tokens": self._manager.report.estimated_tokens,
            "kept": self._manager.report.kept_count,
            "files": len(ranked),
            "categories": categories,
            "budgets": budgets,
            "over_budget": [k for k, v in categories.items() if v > budgets.get(k, 0)],
        }
        return BuiltContext(messages=messages, files=ranked, report=report)

    async def compact_structured(
        self,
        messages: list[dict],
        state: CompactionState | dict[str, Any],
        *,
        summarizer: Summarizer | None = None,
        preserve_count: int = 6,
        max_tokens: int | None = None,
        trajectory=None,
    ) -> StructuredCompaction:
        """Compact a long conversation while retaining validated task state.

        Compaction triggers at 75% of the known context window. The supplied
        state is validated before any model call; an optional summarizer may
        add one bounded ``important_context`` entry, but can never replace the
        structured fields. The source list and its message dictionaries remain
        untouched. A supplied Trajectory receives the real ``context.compacted``
        event with the persisted state for replay/resume.
        """
        original_count = len(messages)
        original = [dict(message) for message in messages]
        structured = state if isinstance(state, CompactionState) else CompactionState.model_validate(state)
        window = max_tokens or int(getattr(self._manager, "_max_tokens", 8192))
        trigger_tokens = self._manager.estimate(messages)
        threshold = int(window * 0.75)
        if trigger_tokens <= threshold or original_count <= preserve_count:
            return StructuredCompaction(
                messages=original,
                state=structured,
                compacted=False,
                trigger_tokens=trigger_tokens,
                original_messages=original_count,
            )

        if summarizer is not None:
            old = messages[:-preserve_count]
            prompt = "\n".join(
                f"{item.get('role', 'user')}: {str(item.get('content') or '')[:500]}"
                for item in old if item.get("content")
            )[-10000:]
            if prompt:
                try:
                    summary = await summarizer(prompt)
                except Exception:
                    summary = None
                if summary and str(summary).strip():
                    structured = structured.model_copy(deep=True)
                    structured.important_context.append(str(summary).strip()[:4000])

        state_json = structured.model_dump_json(indent=2)
        compacted_messages = [{
            "role": "system",
            "content": "[Structured context compaction]\n" + state_json,
        }]
        compacted_messages.extend(
            dict(message) for message in messages[-preserve_count:]
            if not (message.get("role") == "system" and
                    str(message.get("content") or "").startswith("[Structured context compaction]"))
        )
        if trajectory is not None:
            trajectory.append(
                "context.compacted",
                "Structured context compaction",
                data={"state": structured.model_dump(mode="json"),
                      "trigger_tokens": trigger_tokens,
                      "preserved_messages": preserve_count},
            )
        return StructuredCompaction(
            messages=compacted_messages,
            state=structured,
            compacted=True,
            trigger_tokens=trigger_tokens,
            original_messages=original_count,
        )

    async def compress(self, messages: list[dict], summarizer: Summarizer | None = None,
                       preserve_count: int = 6) -> tuple[list[dict], bool]:
        if summarizer is None or not messages:
            return messages, False
        lines = []
        for msg in messages[:-preserve_count] if len(messages) > preserve_count else []:
            content = str(msg.get("content") or "")
            if content:
                lines.append(f"{msg.get('role')}: {content[:500]}")
        if not lines:
            return messages, False
        try:
            summary = await summarizer("\n".join(lines[-20:]))
        except Exception:
            return messages, False
        if not summary or not summary.strip():
            return messages, False
        compacted = self._manager.compact(messages, summary.strip(), preserve_count=preserve_count)
        return compacted, True
