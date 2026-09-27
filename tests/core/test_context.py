"""Tests for ContextManager (axiom.core.context)."""

from __future__ import annotations

from typing import Any

from axiom.core.context import ContextManager


async def fake_summarise(prompt: str) -> str:
    """A minimal summary model stub."""
    return "Summarised: " + prompt[:50]


async def fake_empty_summarise(prompt: str) -> str:
    return ""


class TestEstimate:
    def test_empty_messages(self):
        ctx = ContextManager(max_tokens=4096)
        assert ctx.estimate([]) == 0

    def test_simple_messages(self):
        ctx = ContextManager(max_tokens=4096)
        msgs = [{"role": "user", "content": "hello world"}]
        # "hello world" = 11 chars / 4 ≈ 2.75 → int to 2
        assert ctx.estimate(msgs) >= 1

    def test_dict_and_message_objects(self):
        from axiom.core.events import Message

        ctx = ContextManager(max_tokens=4096)
        mixed: list[Any] = [
            {"role": "user", "content": "a" * 100},
            Message(role="assistant", content="b" * 100),
        ]
        est = ctx.estimate(mixed)
        assert est >= 40  # 200 chars / 4 = 50


class TestPrepare:
    def test_prepare_empty_messages(self):
        ctx = ContextManager(max_tokens=4096)
        result = ctx.prepare([])
        assert result == []

    def test_prepare_with_system_prompt(self):
        ctx = ContextManager(max_tokens=4096)
        result = ctx.prepare(
            [{"role": "user", "content": "hi"}],
            system_prompt="You are AXIOM.",
        )
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are AXIOM."
        assert result[1]["content"] == "hi"

    def test_prepare_trims_when_exceeding_limit(self):
        ctx = ContextManager(max_tokens=100)  # very small
        many_messages = [{"role": "user", "content": "x" * 50}] * 20
        result = ctx.prepare(many_messages)
        # All 20 would be 20*50=1000 chars → 250 tokens >> 75 limit, so trimmed
        assert len(result) < 20
        assert ctx.report.compacted is False  # prepare only drops, summarise compacts


class TestSummarise:
    async def test_no_messages(self):
        ctx = ContextManager()
        summary = await ctx.summarise([])
        assert summary is None

    async def test_no_summary_model(self):
        ctx = ContextManager()
        summary = await ctx.summarise([{"role": "user", "content": "hello"}])
        assert summary is None

    async def test_returns_summary(self):
        ctx = ContextManager()
        summary = await ctx.summarise(
            [{"role": "user", "content": "Hello, what is AI?"}],
            summary_model=fake_summarise,
        )
        assert summary is not None
        assert "Summarised:" in summary

    async def test_empty_summary_is_none(self):
        ctx = ContextManager()
        summary = await ctx.summarise(
            [{"role": "user", "content": "hello"}],
            summary_model=fake_empty_summarise,
        )
        assert summary is None

    async def test_summary_model_exception(self):
        async def failing(_: str) -> str:
            raise RuntimeError("model down")

        ctx = ContextManager()
        summary = await ctx.summarise(
            [{"role": "user", "content": "hello"}],
            summary_model=failing,
        )
        assert summary is None  # graceful fallback


class TestCompact:
    def test_no_summary_drops_old_messages(self):
        ctx = ContextManager()
        msgs = [
            {"role": "user", "content": f"msg {i}"} for i in range(10)
        ]
        compacted = ctx.compact(msgs, None, preserve_count=3)
        assert len(compacted) <= 3 + 1  # might get summary slot
        assert ctx.report.compacted is True

    def test_with_summary_injects_system_message(self):
        ctx = ContextManager()
        msgs = [
            {"role": "user", "content": f"msg {i}"} for i in range(10)
        ]
        compacted = ctx.compact(msgs, "Previous conversation summary...", preserve_count=3)
        # First message is the summary system message
        assert compacted[0]["role"] == "system"
        assert "summary" in compacted[0]["content"].lower()
        # Should have summary + 3 recent
        assert len(compacted) <= 4
        assert ctx.report.compacted is True
        assert ctx.report.summarised_count == 7

    def test_preserved_count_respected(self):
        ctx = ContextManager()
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(5)]
        compacted = ctx.compact(msgs, None, preserve_count=2)
        assert len(compacted) <= 3


class TestIntegration:
    async def test_full_cycle(self):
        ctx = ContextManager(max_tokens=1000)
        msgs = [{"role": "user", "content": "x" * 200}] * 10  # 2000 chars → 500 tokens

        result = ctx.prepare(msgs)
        # 2000 chars ≈ 500 tokens, limit is 750 (75% of 1000)
        # So no trimming needed
        assert len(result) == 10
        assert ctx.should_compact is False

        # Now with massive conversation that should trigger trimming
        many = [{"role": "user", "content": "x" * 500}] * 20  # 10000 chars ≈ 2500 tokens
        ctx2 = ContextManager(max_tokens=1000)
        result2 = ctx2.prepare(many)
        assert len(result2) < 20  # should have trimmed

        summary = await ctx2.summarise(many[:10], summary_model=fake_summarise)
        assert summary is not None

        compacted = ctx2.compact(many, summary, preserve_count=4)
        assert compacted[0]["role"] == "system"
        assert "Summarised:" in compacted[0]["content"]
        assert len(compacted) <= 5


# --------------------------------------------------------------------- W4.3


class TestW43Ranking:
    """W4.3: representative settings-button repair includes only relevant files."""

    def _workspace(self, root):
        from axiom.core.context_engine import ContextEngine
        proj = root / "proj"
        (proj / "desktop/src/components").mkdir(parents=True)
        (proj / "src/axiom/core").mkdir(parents=True)
        (proj / "docs").mkdir(parents=True)
        # frontend (explicit task path)
        (proj / "desktop/src/components/SettingsModal.tsx").write_text(
            "export function SettingsModal() { return null }\n", encoding="utf-8")
        # backend handler mentioned by name; imports settings_store (1 level)
        (proj / "src/axiom/core/settings_handler.py").write_text(
            "from src.axiom.core.settings_store import VALUE\n\ndef handle(): return VALUE\n",
            encoding="utf-8")
        # local import one level deep from the handler
        (proj / "src/axiom/core/settings_store.py").write_text(
            "VALUE = 1\n", encoding="utf-8")
        # noise that must NOT be included
        (proj / "docs/roadmap_notes.txt").write_text("unrelated\n", encoding="utf-8")
        (proj / "src/axiom/core/random_thing.py").write_text("x = 1\n", encoding="utf-8")
        engine = ContextEngine()
        return engine, proj

    def test_rank_prefers_explicit_mentioned_imports(self, tmp_path):
        engine, proj = self._workspace(tmp_path)
        ranked = engine.rank_files(
            proj,
            "Fix the settings button: it should persist in settings_handler",
            explicit_paths=["desktop/src/components/SettingsModal.tsx"],
            changed_files=["src/axiom/core/settings_handler.py"],
        )
        assert ranked[0] == "desktop/src/components/SettingsModal.tsx"
        assert "src/axiom/core/settings_handler.py" in ranked
        assert "src/axiom/core/settings_store.py" in ranked  # 1-level import
        # noise excluded
        assert "docs/roadmap_notes.txt" not in ranked
        assert "src/axiom/core/random_thing.py" not in ranked

    def test_rank_dedupes_and_stays_in_workspace(self, tmp_path):
        engine, proj = self._workspace(tmp_path)
        ranked = engine.rank_files(
            proj,
            "settings_handler",
            explicit_paths=["src/axiom/core/settings_handler.py",
                            "src/axiom/core/settings_handler.py",
                            "../outside.py"],
        )
        assert ranked.count("src/axiom/core/settings_handler.py") == 1
        assert all(not p.startswith("..") for p in ranked)

    def test_build_task_context_respects_budgets_and_reports_sizes(self, tmp_path):
        engine, proj = self._workspace(tmp_path)
        built = engine.build_task_context(
            "Fix the settings button in settings_handler",
            [{"role": "user", "content": "fix the settings button"}],
            system_prompt="You are AXIOM. " + ("x" * 500),
            project_context="proj " + ("p" * 5000),
            workspace_root=proj,
            explicit_paths=["desktop/src/components/SettingsModal.tsx"],
            changed_files=["src/axiom/core/settings_handler.py"],
            tool_results=["read ok " + ("t" * 5000)],
            budgets={"system": 40, "project": 30, "files": 4000,
                     "tool_results": 50, "conversation": 4000, "task": 4000},
        )
        cat = built.report["categories"]
        assert cat["system"] <= 40
        assert cat["project"] <= 30
        assert cat["tool_results"] <= 50
        assert built.report["over_budget"] == []
        assert built.report["files"] >= 1
        assert "budgets" in built.report and "categories" in built.report

    def test_build_task_context_never_loads_whole_project(self, tmp_path):
        engine, proj = self._workspace(tmp_path)
        built = engine.build_task_context(
            "Fix the settings button",
            [{"role": "user", "content": "fix settings"}],
            workspace_root=proj,
            explicit_paths=["desktop/src/components/SettingsModal.tsx"],
        )
        # Only relevant files — never the whole project.
        assert "docs/roadmap_notes.txt" not in built.files
        assert "src/axiom/core/random_thing.py" not in built.files

    def test_files_category_clipped_to_budget(self, tmp_path):
        from axiom.core.context_engine import ContextEngine
        proj = tmp_path / "big"
        proj.mkdir()
        (proj / "a.py").write_text("a" * 5000, encoding="utf-8")
        (proj / "b.py").write_text("b" * 5000, encoding="utf-8")
        (proj / "c.py").write_text("c" * 5000, encoding="utf-8")
        engine = ContextEngine()
        built = engine.build_task_context(
            "a b c",
            [{"role": "user", "content": "x"}],
            workspace_root=proj,
            explicit_paths=["a.py", "b.py", "c.py"],
            budgets={"files": 6200, "system": 10, "project": 10, "task": 10,
                     "tool_results": 10, "conversation": 10},
        )
        assert built.report["categories"]["files"] <= 6200

    def test_file_budget_skips_oversized_ranked_file_and_keeps_later_candidate(self, tmp_path):
        from axiom.core.context_engine import ContextEngine

        (tmp_path / "large.py").write_text("l" * 5000, encoding="utf-8")
        (tmp_path / "small.py").write_text("small", encoding="utf-8")
        built = ContextEngine().build_task_context(
            "task", [], workspace_root=tmp_path,
            explicit_paths=["large.py", "small.py"],
            budgets={"files": 20},
        )
        assert "small.py" in built.files
        assert built.report["categories"]["files"] <= 20

    def test_long_task_history_and_trajectory_are_actually_bounded(self):
        from axiom.core.context_engine import ContextEngine

        history = [{"role": "user", "content": "old" * 300},
                   {"role": "assistant", "content": "recent" * 200}]
        original = [dict(item) for item in history]
        built = ContextEngine().build_task_context(
            "repair " * 200, history,
            trajectory_tail=[{"kind": "tool", "summary": "z" * 2000}],
            budgets={"task": 60, "conversation": 40, "tool_results": 32},
        )
        assert built.report["over_budget"] == []
        assert built.report["categories"]["task"] == 60
        assert built.report["categories"]["conversation"] == 40
        assert built.report["categories"]["tool_results"] == 32
        assert "Current task:\n" + ("repair " * 8) in built.messages[0]["content"]
        assert len(built.messages[-1]["content"]) == 40
        assert history == original

    def test_negative_budget_is_rejected(self):
        import pytest

        from axiom.core.context_engine import ContextEngine

        with pytest.raises(ValueError, match="non-negative"):
            ContextEngine().build_task_context("task", [], budgets={"task": -1})


class TestW44Compaction:
    async def test_structured_compaction_trigger_and_retention(self):
        from axiom.core.context_engine import CompactionState, ContextEngine
        from axiom.core.trajectory import Trajectory

        engine = ContextEngine(max_tokens=100)
        messages = [{"role": "user", "content": "old " + ("x" * 80)} for _ in range(8)]
        original = [dict(message) for message in messages]
        trajectory = Trajectory()
        result = await engine.compact_structured(
            messages,
            CompactionState(
                goal="Fix settings",
                plan=["Inspect", "Edit", "Test"],
                decisions=["Keep local state"],
                changed_files=["SettingsModal.tsx"],
                errors=["pytest failed"],
                tests=["pytest -q: 1 failed"],
                important_context=["Permission is required"],
            ),
            preserve_count=2,
            trajectory=trajectory,
        )
        assert result.compacted is True
        assert result.original_messages == 8
        assert result.state.goal == "Fix settings"
        assert result.state.changed_files == ["SettingsModal.tsx"]
        assert "Structured context compaction" in result.messages[0]["content"]
        assert len(result.messages) == 3
        assert messages == original
        assert any(event.kind == "context.compacted" for event in trajectory.events)
        event = next(event for event in trajectory.events if event.kind == "context.compacted")
        assert event.data["state"]["errors"] == ["pytest failed"]

    async def test_structured_compaction_does_not_trigger_below_budget(self):
        from axiom.core.context_engine import CompactionState, ContextEngine

        messages = [{"role": "user", "content": "short"}]
        result = await ContextEngine(max_tokens=1000).compact_structured(
            messages, CompactionState(goal="Answer"), preserve_count=1,
        )
        assert result.compacted is False
        assert result.messages == messages
        assert result.original_messages == 1

    async def test_structured_compaction_validates_schema(self):
        import pytest
        from pydantic import ValidationError

        from axiom.core.context_engine import ContextEngine

        with pytest.raises(ValidationError):
            await ContextEngine().compact_structured(
                [{"role": "user", "content": "x"}],
                {"goal": "x", "unexpected": True},
            )

    async def test_structured_summary_is_additive_and_source_is_intact(self):
        from axiom.core.context_engine import ContextEngine

        messages = [{"role": "user", "content": "old " + ("z" * 100)} for _ in range(6)]
        state = {"goal": "Goal", "plan": ["step"]}

        async def summarize(prompt: str) -> str:
            assert prompt
            return "Decision from the retained history"

        result = await ContextEngine(max_tokens=100).compact_structured(
            messages, state, summarizer=summarize, preserve_count=2,
        )
        assert result.compacted is True
        assert result.state.important_context == ["Decision from the retained history"]
        assert len(messages) == 6
        assert all("Decision from" not in message["content"] for message in messages)

    async def test_repeated_compaction_replaces_previous_snapshot(self):
        from axiom.core.context_engine import ContextEngine

        engine = ContextEngine(max_tokens=100)
        messages = [{"role": "user", "content": "x" * 120} for _ in range(5)]
        first = await engine.compact_structured(messages, {"goal": "Fix"}, preserve_count=1)
        assert first.compacted
        extended = [*first.messages, {"role": "user", "content": "y" * 120}]
        second = await engine.compact_structured(extended, {"goal": "Fix"}, preserve_count=1)
        assert second.compacted
        assert sum("[Structured context compaction]" in str(m["content"]) for m in second.messages) == 1
