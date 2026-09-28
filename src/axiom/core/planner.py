"""Bounded, model-generated task plans. No tools are executed by the planner."""
from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    goal: str = Field(min_length=1, max_length=2000)
    tools: list[str] = Field(default_factory=list, max_length=40)
    done_when: str = Field(min_length=1, max_length=1000)
    state: Literal["pending", "running", "completed", "failed"] = "pending"
    result: str = Field(default="", max_length=8000)


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[PlanStep] = Field(min_length=1, max_length=8)
    definition_of_done: list[str] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_steps(self) -> TaskPlan:
        if len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError("Plan step ids must be unique")
        if any(not item.strip() for item in self.definition_of_done):
            raise ValueError("Definition of done cannot be empty")
        return self


class Planner:
    def __init__(self, generate: Callable[[str], Awaitable[str]]) -> None:
        self.generate = generate

    @staticmethod
    def needed(goal: str, force: bool | None = None) -> bool:
        if force is not None:
            return force
        text = goal.casefold()
        return len(text) > 240 or any(word in text for word in (
            "fix", "implement", "refactor", "не работает", "почему", "исправ",
            "реализ", "добав", "баг", "debug", "project switching",
        ))

    @staticmethod
    def parse(text: str, available_tools: list[str]) -> TaskPlan:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        plan = TaskPlan.model_validate(json.loads(text))
        allowed = set(available_tools)
        for step in plan.steps:
            if set(step.tools) - allowed:
                raise ValueError(f"Unknown or unavailable tools in step {step.id}")
            if step.state != "pending" or step.result:
                raise ValueError("A model cannot mark an unexecuted step as completed")
        return plan

    async def create(self, goal: str, tools: list[str], *, previous: TaskPlan | None = None,
                     error: str = "") -> TaskPlan:
        context = ""
        if previous is not None:
            context = (
                "\nReplan only the unfinished work after this failure: " + error[:4000]
                + "\nPrevious plan (completed steps must NOT be repeated): "
                + previous.model_dump_json()
            )
        prompt = (
            "Plan the following task. Return ONLY a JSON object with keys steps and definition_of_done. "
            "Each step has id (unique ASCII identifier), goal, tools (names), done_when. "
            "Use 1 to 8 small sequential steps; do not claim work has already happened. "
            "definition_of_done is a nonempty list of concrete acceptance criteria. "
            "Write all human-readable values (goal, done_when, definition_of_done) in the same natural language "
            "as the user's Goal. Do not translate the user's goal into another language. Keep JSON keys, step ids, "
            "and tool names unchanged/ASCII. "
            "Do not execute tools. Available tools: " + json.dumps(tools)
            + "\nGoal: " + goal + context
        )
        plan = self.parse(await self.generate(prompt), tools)
        if previous is not None:
            completed = [step.model_copy(deep=True) for step in previous.steps if step.state == "completed"]
            if {s.id for s in completed} & {s.id for s in plan.steps}:
                raise ValueError("Replan cannot replace completed steps")
            plan = TaskPlan(steps=completed + plan.steps, definition_of_done=previous.definition_of_done)
        return plan
