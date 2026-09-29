"""ToolRegistry 2.0: категории, теги, выборка по задаче."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolMeta:
    name: str
    category: str = "general"
    tags: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    needs_approval: bool = False

CATEGORY_OF: dict[str, str] = {
    "web_search": "research", "fetch_url": "research",
    "list_files": "filesystem", "read_file": "filesystem",
    "write_file": "filesystem", "edit_file": "filesystem",
    "apply_patch": "filesystem",
    "search_text": "filesystem", "search_files": "filesystem",
    "delete_file": "filesystem", "move_file": "filesystem",
    "copy_file": "filesystem", "create_directory": "filesystem",
    "run_command": "terminal",
    "run_tests": "verification", "run_linter": "verification",
    "build_project": "verification", "verify_changes": "verification",
    "git_status": "git", "git_diff": "git", "git_log": "git", "git_branch": "git",
    "inspect_project": "project",
}

AGENT_TOOLS: dict[str, tuple[str, ...]] = {
    "researcher": ("web_search", "fetch_url"),
    "analyst": ("list_files", "read_file", "search_text", "search_files", "inspect_project"),
    "coder": ("list_files", "read_file", "write_file", "edit_file", "apply_patch",
              "search_text", "search_files", "create_directory", "run_command",
              "run_tests", "verify_changes", "git_status", "git_diff"),
    "debugger": ("read_file", "search_text", "run_command", "run_tests",
                 "run_linter", "git_diff", "git_log"),
    "reviewer": ("read_file", "git_diff", "git_status", "git_log", "verify_changes"),
    "tester": ("run_command", "run_tests", "run_linter", "verify_changes",
               "read_file", "search_text"),
    "architect": ("list_files", "read_file", "inspect_project", "web_search"),
    "security": ("read_file", "search_text", "git_diff"),
    "orchestrator": ("list_files", "read_file", "inspect_project"),
    # W4.6 roles: Explorer is strictly read-only reconnaissance; Frontend
    # and Backend own their editing/testing surface.
    "explorer": ("list_files", "read_file", "search_text", "search_files",
                 "inspect_project", "git_status", "git_diff", "git_log"),
    "frontend": ("list_files", "read_file", "write_file", "edit_file",
                 "apply_patch", "search_text", "search_files", "run_command",
                 "run_tests", "verify_changes", "git_status", "git_diff"),
    "backend": ("list_files", "read_file", "write_file", "edit_file",
                "apply_patch", "search_text", "search_files", "run_command",
                "run_tests", "run_linter", "verify_changes", "git_status",
                "git_diff"),
}

def category_of(tool_name: str) -> str:
    return CATEGORY_OF.get(tool_name, "general")

def tools_for_agent(agent_id: str) -> tuple[str, ...]:
    return AGENT_TOOLS.get(agent_id, ())

def resolve_tools_for_task(text: str) -> list[str]:
    t = (text or "").lower()
    out: list[str] = ["web_search", "fetch_url"]
    file_markers = ("file", "code", "project", "refactor", "bug", "test",
                    "implement", "script", "class", "module", "файл", "код",
                    "проект", "ошибк", "тест", "скрипт", "класс", "модул")
    git_markers = ("git", "commit", "branch", "diff", "коммит", "ветк", "лог")
    verify_markers = ("test", "тест", "lint", "verify", "проверь", "проверить",
                      "build", "собер", "сборк")
    if any(m in t for m in git_markers):
        out += ["git_status", "git_diff", "git_log", "git_branch"]
    if any(m in t for m in file_markers) or not t.strip():
        out += ["list_files", "read_file", "write_file", "edit_file", "apply_patch",
                "search_text", "search_files", "inspect_project", "run_command"]
    if any(m in t for m in verify_markers):
        out += ["run_tests", "run_linter", "verify_changes"]
    seen: list[str] = []
    for name in out:
        if name not in seen:
            seen.append(name)
    return seen
