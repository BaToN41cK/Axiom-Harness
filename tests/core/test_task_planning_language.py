"""Language prompt contracts and honest planning failures; no live model needed."""
import json

import pytest

from axiom.core.planner import Planner
from tests.core.test_orchestrator_runtime_a import _session


@pytest.mark.parametrize("goal", ["Исправь ошибку формы", "Fix the form", "Corrige el formulario", "修复表单错误"])
async def test_planner_requests_goal_language_without_translating_schema(goal):
    async def generate(prompt):
        assert "same natural language" in prompt
        assert "Keep JSON keys, step ids" in prompt
        assert f"\nGoal: {goal}" in prompt
        return json.dumps({"steps": [{"id": "inspect", "goal": goal, "tools": [], "done_when": goal}],
                           "definition_of_done": [goal]}, ensure_ascii=False)

    plan = await Planner(generate).create(goal, [])
    assert plan.steps[0].goal == goal
    assert plan.steps[0].state == "pending"


async def test_planning_failure_does_not_return_canned_plan(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch, tmp_path)

    async def fail(prompt):
        raise ValueError("model unavailable")

    monkeypatch.setattr(session, "_plan_task", fail)
    with pytest.raises(ValueError, match="model unavailable"):
        await session.task_plan("Corrige el formulario")