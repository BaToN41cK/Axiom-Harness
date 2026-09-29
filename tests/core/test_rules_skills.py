"""W4.5 — AXIOM.md rules + selective skills.

Deterministic, local-only tests: rule discovery across global/project/
directory/task scopes, precedence merging, relevance filtering, disk skill
loading from ``.axiom/skills/`` and the task-runtime contract (a matching
skill changes the step prompt through persisted Task State).
"""

from __future__ import annotations

import pytest

from axiom.core.rules import RuleManager, discover_rules
from axiom.core.skills import Skill, SkillRegistry, parse_skill_file


@pytest.fixture()
def workspace(tmp_path):
    ws = tmp_path / "proj"
    (ws / "frontend" / "ui").mkdir(parents=True)
    (ws / "backend").mkdir(parents=True)
    (ws / "frontend" / "ui" / "Button.tsx").write_text("export {}", encoding="utf-8")
    (ws / "backend" / "app.py").write_text("app = 1\n", encoding="utf-8")
    return ws


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestRuleDiscovery:
    def test_global_project_and_directory_scopes(self, workspace, monkeypatch):
        monkeypatch.setenv("AXIOM_HOME", str(workspace.parent / "home"))
        home = workspace.parent / "home"
        _write(home / "AXIOM.md", "global rule")
        _write(workspace / "AXIOM.md", "project rule")
        _write(workspace / "frontend" / "AXIOM.md", "frontend rule")
        _write(workspace / "backend" / "AXIOM.md", "backend rule")

        sources = discover_rules(workspace)
        scopes = {(s.scope, s.rel) for s in sources}
        assert any(s.scope == "global" for s in sources)
        assert ("project", "AXIOM.md") in scopes
        assert ("directory", "frontend/AXIOM.md") in scopes
        assert ("directory", "backend/AXIOM.md") in scopes
        frontend = next(s for s in sources if s.rel == "frontend/AXIOM.md")
        assert frontend.root == "frontend"

    def test_axiom_project_md_is_a_project_rule(self, workspace, monkeypatch):
        monkeypatch.setenv("AXIOM_HOME", str(workspace.parent / "home"))
        _write(workspace / ".axiom" / "project.md", "project md rule")
        sources = discover_rules(workspace)
        project = [s for s in sources if s.scope == "project"]
        assert [s.rel for s in project] == [".axiom/project.md"]

    def test_pruned_directories_are_never_discovered(self, workspace, monkeypatch):
        monkeypatch.setenv("AXIOM_HOME", str(workspace.parent / "home"))
        _write(workspace / "node_modules" / "pkg" / "AXIOM.md", "noise")
        _write(workspace / ".git" / "AXIOM.md", "noise")
        sources = discover_rules(workspace)
        assert all("node_modules" not in s.rel and ".git" not in s.rel
                   for s in sources)


class TestRuleRelevance:
    def test_irrelevant_directory_rules_are_absent(self, workspace, monkeypatch):
        monkeypatch.setenv("AXIOM_HOME", str(workspace.parent / "home"))
        _write(workspace / "AXIOM.md", "project rule")
        _write(workspace / "frontend" / "AXIOM.md", "frontend rule")
        _write(workspace / "backend" / "AXIOM.md", "backend rule")
        manager = RuleManager(workspace)
        block = manager.merged_rules("fix the backend app", task_paths=["backend/app.py"],
                                     include_static=True)
        assert "project rule" in block
        assert "backend rule" in block
        assert "frontend rule" not in block
        assert "frontend/AXIOM.md" in manager.last_report.skipped

    def test_path_mentions_in_text_attach_directory_rules(self, workspace, monkeypatch):
        monkeypatch.setenv("AXIOM_HOME", str(workspace.parent / "home"))
        _write(workspace / "frontend" / "AXIOM.md", "frontend rule")
        _write(workspace / "backend" / "AXIOM.md", "backend rule")
        manager = RuleManager(workspace)
        sources = manager.relevant("repair frontend/ui/Button.tsx please")
        rels = [s.rel for s in sources]
        assert "frontend/AXIOM.md" in rels
        assert "backend/AXIOM.md" not in rels

    def test_user_mentioned_rules_win_conflicting_sections(self, workspace, monkeypatch):
        monkeypatch.setenv("AXIOM_HOME", str(workspace.parent / "home"))
        _write(workspace / "AXIOM.md", "# Testing\nalways use jest\n# Style\ntwo spaces")
        _write(workspace / "docs" / "policy.md", "# Testing\nalways use pytest")
        manager = RuleManager(workspace)
        block = manager.merged_rules("follow @docs/policy.md strictly", include_static=True)
        assert "always use pytest" in block
        assert "always use jest" not in block      # task scope shadows project
        assert "two spaces" in block                # non-conflicting sections survive

    def test_deterministic_merge_order(self, workspace, monkeypatch):
        monkeypatch.setenv("AXIOM_HOME", str(workspace.parent / "home"))
        _write(workspace / "AXIOM.md", "project rule")
        _write(workspace / "frontend" / "AXIOM.md", "frontend rule")
        manager = RuleManager(workspace)
        first = manager.merged_rules("x", task_paths=["frontend/ui/Button.tsx"],
                                     include_static=True)
        second = RuleManager(workspace).merged_rules(
            "x", task_paths=["frontend/ui/Button.tsx"], include_static=True)
        assert first == second

    def test_project_rules_block_skips_directory_rules(self, workspace, monkeypatch):
        monkeypatch.setenv("AXIOM_HOME", str(workspace.parent / "home"))
        _write(workspace / "AXIOM.md", "project rule")
        _write(workspace / "frontend" / "AXIOM.md", "frontend rule")
        manager = RuleManager(workspace)
        block = manager.project_rules_block()
        assert "project rule" in block
        assert "frontend rule" not in block

    def test_workspace_rebind_rediscovers(self, workspace, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_HOME", str(workspace.parent / "home"))
        _write(workspace / "AXIOM.md", "project rule one")
        other = tmp_path / "other"
        _write(other / "AXIOM.md", "project rule two")
        manager = RuleManager(workspace)
        assert "project rule one" in manager.project_rules_block()
        manager.set_workspace(other)
        block = manager.project_rules_block()
        assert "project rule two" in block
        assert "project rule one" not in block


class TestDiskSkills:
    def test_parse_skill_file_with_header(self, tmp_path):
        path = tmp_path / "alembic-migrations.md"
        _write(path, "---\nlabel: Alembic\ntriggers: alembic, migrations\n"
                     "tools: run_command, read_file\n---\nAlways autogenerate then review.")
        skill = parse_skill_file(path, source="project")
        assert skill is not None
        assert skill.id == "alembic-migrations"
        assert skill.label == "Alembic"
        assert skill.triggers == ("alembic", "migrations")
        assert skill.tools == ("run_command", "read_file")
        assert "autogenerate" in skill.instructions
        assert skill.source == "project"

    def test_parse_skill_file_without_header_uses_stem(self, tmp_path):
        path = tmp_path / "release.md"
        _write(path, "Run the full release checklist before tagging.")
        skill = parse_skill_file(path, source="global")
        assert skill is not None and skill.id == "release"
        assert skill.triggers == ()

    def test_empty_skill_file_is_not_a_skill(self, tmp_path):
        path = tmp_path / "blank.md"
        _write(path, "---\nlabel: Blank\n---\n")
        assert parse_skill_file(path, source="project") is None

    def test_registry_loads_and_selects_by_triggers(self, workspace, monkeypatch):
        monkeypatch.setenv("AXIOM_HOME", str(workspace.parent / "home"))
        _write(workspace / ".axiom" / "skills" / "alembic.md",
               "---\ntriggers: alembic\n---\nReview autogenerated migrations before apply.")
        registry = SkillRegistry()
        loaded = registry.load_workspace_skills(workspace)
        assert loaded == ["alembic"]
        hits = registry.resolve_for_task("add an alembic migration for users")
        assert any(s.id == "alembic" for s in hits)
        # Irrelevant text never selects the disk skill.
        assert all(s.id != "alembic" for s in registry.resolve_for_task("hello there"))

    def test_workspace_switch_drops_stale_project_skills(self, workspace, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_HOME", str(workspace.parent / "home"))
        _write(workspace / ".axiom" / "skills" / "one.md", "skill one body")
        other = tmp_path / "other"
        _write(other / ".axiom" / "skills" / "two.md", "skill two body")
        registry = SkillRegistry()
        registry.load_workspace_skills(workspace)
        assert registry.get("one") is not None
        registry.load_workspace_skills(other)
        assert registry.get("one") is None
        assert registry.get("two") is not None

    def test_global_skills_survive_workspace_switch(self, workspace, tmp_path, monkeypatch):
        home = workspace.parent / "home"
        monkeypatch.setenv("AXIOM_HOME", str(home))
        _write(home / "skills" / "personal.md", "personal workflow body")
        registry = SkillRegistry()
        registry.load_workspace_skills(workspace)
        registry.load_workspace_skills(tmp_path / "other")
        assert registry.get("personal") is not None


class TestTaskRuntimeContract:
    """A matching skill must change task behaviour through a tested contract."""

    @pytest.mark.asyncio()
    async def test_persisted_rules_and_skills_shape_step_prompts(self, tmp_path):
        from axiom.core.bus import EventBus
        from axiom.core.planner import Planner
        from axiom.core.tasks import Task, TaskRunner, TaskState, TaskStore
        from axiom.core.trajectory import Trajectory

        registry = SkillRegistry()
        registry.register(Skill("alembic", "Alembic",
                                "Review autogenerated migrations before apply.",
                                source="project"))

        prompts: list[str] = []

        async def generate(_prompt: str) -> str:
            return ('{"steps": [{"id": "migrate", "goal": "Write the migration",'
                    ' "tools": ["write_file"], "done_when": "Migration file exists"}],'
                    ' "definition_of_done": "Migration verified"}')

        async def execute(*, step, prompt, on_event):
            prompts.append(prompt)
            return {"content": "migration written"}

        async def verify():
            return {"ok": True, "executed": True, "summary": "ok"}

        runner = TaskRunner(
            store=TaskStore(tmp_path / "tasks"), planner=Planner(generate),
            execute=execute, verify=verify, tools=["write_file"], bus=EventBus(),
            trajectory=Trajectory(), skill_registry=registry,
        )
        task = Task(
            goal="Add an alembic migration",
            context_rules="## Rules from AXIOM.md\nMigrations must be reversible.",
            active_skills=["alembic"],
            task_paths=["alembic/versions"],
        )
        task = await runner.run(task)
        assert task.state is TaskState.COMPLETED
        assert prompts, "step prompt must be built"
        prompt = prompts[0]
        assert "Migrations must be reversible." in prompt
        assert "Review autogenerated migrations before apply." in prompt
        # Task State persists the attachment for restart/resume.
        reloaded = runner.store.load(task.id)
        assert reloaded is not None
        assert reloaded.context_rules == task.context_rules
        assert reloaded.active_skills == ["alembic"]
        assert reloaded.task_paths == ["alembic/versions"]

    @pytest.mark.asyncio()
    async def test_missing_skill_id_fails_silently(self, tmp_path):
        from axiom.core.bus import EventBus
        from axiom.core.planner import Planner
        from axiom.core.tasks import Task, TaskRunner, TaskState, TaskStore
        from axiom.core.trajectory import Trajectory

        async def generate(_prompt: str) -> str:
            return ('{"steps": [{"id": "s", "goal": "Step", "tools": [],'
                    ' "done_when": "Done"}], "definition_of_done": "Done"}')

        async def execute(*, step, prompt, on_event):
            return {"content": "done"}

        async def verify():
            return {"ok": True, "executed": True, "summary": "ok"}

        runner = TaskRunner(
            store=TaskStore(tmp_path / "tasks"), planner=Planner(generate),
            execute=execute, verify=verify, tools=[], bus=EventBus(),
            trajectory=Trajectory(), skill_registry=SkillRegistry(),
        )
        task = Task(goal="x", active_skills=["no-such-skill"])
        task = await runner.run(task)
        assert task.state is TaskState.COMPLETED  # unknown ids never crash a run
