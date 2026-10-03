"""Skills — инструкции+tools+знания по стеку (п.14).

Skill: instructions, tools, knowledge, commands, validation.

W4.5: skills can also live on disk. Project skills come from
``<workspace>/.axiom/skills/*.md`` and global skills from
``<AXIOM_HOME>/skills/*.md``. File format::

    ---
    id: my-skill            # optional; default = file stem
    label: My Skill         # optional
    triggers: alembic, migrations   # optional, comma-separated
    tools: run_command, read_file   # optional, comma-separated
    ---
    Instructions written in Markdown. They reach the prompt only when the
    skill is selected by relevance (trigger words, markers or a @mention).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from axiom.core.config import axiom_home


@dataclass
class Skill:
    id: str
    label: str = ""
    instructions: str = ""
    tools: tuple[str, ...] = ()
    knowledge: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    validation: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    source: str = "builtin"   # builtin | global | project | plugin

    def prompt_block(self) -> str:
        lines = [f"Skill: {self.label or self.id}", self.instructions.strip()]
        if self.commands:
            lines.append("Commands: " + ", ".join(self.commands))
        if self.validation:
            lines.append("Validate: " + ", ".join(self.validation))
        return "\n".join(line for line in lines if line)


def _split_list(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.replace(";", ",").split(",") if part.strip())


def parse_skill_file(path: Path, *, source: str) -> Skill | None:
    """Parse one ``*.md`` skill file; ``None`` when the file is unusable.

    An optional ``---`` fenced YAML-style header carries ``id``/``label``/
    ``triggers``/``tools``; everything after it is the instruction body.
    A file without instructions is not a skill.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    meta: dict[str, str] = {}
    body = text
    stripped = text.lstrip()
    if stripped.startswith("---"):
        lines = stripped.splitlines()
        end = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                end = index
                break
        if end is not None:
            for line in lines[1:end]:
                if ":" in line:
                    key, _, value = line.partition(":")
                    meta[key.strip().casefold()] = value.strip()
            body = "\n".join(lines[end + 1:])
    instructions = body.strip()
    if not instructions:
        return None
    skill_id = meta.get("id") or path.stem
    if not skill_id or any(ch in skill_id for ch in "/\\ "):
        skill_id = path.stem.replace(" ", "-")
    return Skill(
        id=skill_id,
        label=meta.get("label", ""),
        instructions=instructions[:4000],
        tools=_split_list(meta.get("tools", "")),
        triggers=_split_list(meta.get("triggers", "")),
        source=source,
    )


def load_skill_directory(directory: Path, *, source: str) -> list[Skill]:
    """Load every valid ``*.md`` skill from one directory (sorted, stable)."""
    skills: list[Skill] = []
    try:
        files = sorted(directory.glob("*.md"))
    except OSError:
        return skills
    for path in files:
        skill = parse_skill_file(path, source=source)
        if skill is not None:
            skills.append(skill)
    return skills



BUILTIN_SKILLS: tuple[Skill, ...] = (
    Skill("python", "Python", "Пиши типобезопасный Python 3.11+, pytest для тестов.",
          ("read_file", "write_file", "edit_file", "run_command", "search_text"),
          ("stdlib", "pytest", "ruff"), ("pytest -q", "ruff check ."), ("pytest -q",)),
    Skill("react", "React", "Функциональные компоненты, hooks, TypeScript.",
          ("read_file", "write_file", "edit_file", "search_text"),
          ("hooks", "vite"), ("npm test", "npm run build"), ("npm test",)),
    Skill("typescript", "TypeScript", "Строгая типизация, без any без нужды.",
          ("read_file", "write_file", "edit_file", "search_text"),
          ("tsc",), ("npx tsc --noEmit",), ("npx tsc --noEmit",)),
    Skill("rust", "Rust", "clippy-clean код, cargo test обязателен.",
          ("read_file", "write_file", "edit_file", "run_command"),
          ("cargo",), ("cargo test", "cargo clippy"), ("cargo test",)),
    Skill("tauri", "Tauri", "npm+cargo мост, IPC команды, frontend/backend граница.",
          ("read_file", "search_text", "run_command"),
          ("ipc", "cargo-tauri"), ("npm run tauri dev",), ("cargo check",)),
    Skill("git", "Git", "Атомарные коммиты, ветки по фичам, review diff перед push.",
          ("git_status", "git_diff", "git_log", "git_branch"), ("rebase",), (), ()),
    Skill("docker", "Docker", "Многослойные образы, .dockerignore, healthcheck.",
          ("read_file", "write_file", "run_command"), ("compose",),
          ("docker build .",), ("docker compose config",)),
    Skill("testing", "Testing", "Покрывай краевые случаи, сначала красный тест.",
          ("read_file", "run_command", "search_text"), ("pytest", "vitest"), ("pytest -q",), ()),
    Skill("debugging", "Debugging", "Воспроизведи, сузь, исправь, проверь регрессию.",
          ("read_file", "search_text", "run_command", "git_diff"),
          ("bisect",), (), ("pytest -q",)),
    Skill("security", "Security", "Не коммить секреты, проверяй ввод,最小 привилегии.",
          ("read_file", "search_text", "git_diff"), ("owasp",), (), ()),
    Skill("sql", "SQL", "Параметризованные запросы, explain перед оптимизацией.",
          ("read_file", "search_text"), ("postgres",), (), ()),
)

_MATCH: dict[str, tuple[str, ...]] = {
    "python": ("python", ".py", "pytest", "pip", "питон"),
    "react": ("react", ".tsx", ".jsx", "vite", "реакт"),
    "typescript": ("typescript", ".ts", "tsc", "тайпскрипт"),
    "rust": ("rust", ".rs", "cargo", "раст"),
    "tauri": ("tauri", "ipc"),
    "git": ("git", "коммит", "commit", "branch", "ветк"),
    "docker": ("docker", "compose", "докер"),
    "testing": ("test", "тест", "pytest", "vitest"),
    "debugging": ("debug", "баг", "bug", "ошибк", "падает", "исправ"),
    "security": ("secur", "безопас", "cve", "auth", "аутентиф"),
    "sql": ("sql", "postgres", "select", "запрос"),
}


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {s.id: s for s in BUILTIN_SKILLS}
        self._pin_sources: dict[str, set[str]] = {}
        self._workspace_root: Path | None = None

    def register(self, skill: Skill) -> None:
        self._skills[skill.id] = skill

    def remove(self, skill_id: str) -> bool:
        removed = self._skills.pop(skill_id, None) is not None
        self._pin_sources.pop(skill_id, None)
        return removed

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    # ------------------------------------------------------- disk (W4.5)

    def load_workspace_skills(self, workspace_root: Path | str | None) -> list[str]:
        """(Re)load global and project skills from disk for *workspace_root*.

        Previously loaded disk skills are dropped first so removed/renamed
        files never linger; a workspace switch rebinds the project set.
        Returns the ids that were registered.
        """
        for skill_id, skill in list(self._skills.items()):
            if skill.source in ("global", "project"):
                self.remove(skill_id)
        root: Path | None = None
        if workspace_root:
            try:
                root = Path(workspace_root).expanduser().resolve()
            except OSError:
                root = None
        self._workspace_root = root
        loaded: list[str] = []
        for skill in load_skill_directory(axiom_home() / "skills", source="global"):
            self.register(skill)
            loaded.append(skill.id)
        if root is not None:
            for skill in load_skill_directory(root / ".axiom" / "skills",
                                              source="project"):
                self.register(skill)
                loaded.append(skill.id)
        return loaded

    def resolve_for_task(self, text: str) -> list[Skill]:
        lowered = (text or "").lower()
        out: list[Skill] = []
        for skill_id, markers in _MATCH.items():
            if any(m in lowered for m in markers):
                skill = self._skills.get(skill_id)
                if skill is not None and skill not in out:
                    out.append(skill)
        # W4.5: disk skills are selected by their own declared triggers.
        for skill in self._skills.values():
            if skill.source in ("global", "project") and skill not in out:
                disk_markers = [t.casefold() for t in skill.triggers] or [skill.id.casefold()]
                if any(m and m in lowered for m in disk_markers):
                    out.append(skill)
        # Pinned skills (плагины/пресеты) доступны всегда — независимо от маркеров.
        for skill_id in self._pin_sources:
            skill = self._skills.get(skill_id)
            if skill is not None and skill not in out:
                out.append(skill)
        return out

    def pin(self, skill_id: str, *, source: str = "manual") -> bool:
        """Закрепить skill для источника; он попадает в контекст всегда."""
        if skill_id not in self._skills:
            return False
        self._pin_sources.setdefault(skill_id, set()).add(source)
        return True

    def unpin(self, skill_id: str, *, source: str | None = None) -> bool:
        """Снять pin одного источника или все pins при ``source=None``."""
        sources = self._pin_sources.get(skill_id)
        if not sources:
            return False
        if source is None:
            self._pin_sources.pop(skill_id, None)
            return True
        if source not in sources:
            return False
        sources.discard(source)
        if not sources:
            self._pin_sources.pop(skill_id, None)
        return True

    def pinned(self) -> list[str]:
        return sorted(self._pin_sources)

    def pinned_by(self, source: str) -> list[str]:
        """Ids pinned by a specific source (e.g. ``"manual"`` for the Skills GUI)."""
        return sorted(skill_id for skill_id, sources in self._pin_sources.items()
                      if source in sources)
