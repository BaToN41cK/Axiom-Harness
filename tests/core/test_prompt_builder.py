"""W2.5 Prompt Layers — deterministic, budgeted, invariant-checked assembly."""
from __future__ import annotations

from axiom.core.performance import classify_mode
from axiom.core.prompt_builder import (
    FULL_BUDGET_CHARS,
    HONESTY_RULE,
    MINI_BUDGET_CHARS,
    NO_GUESS_RULE,
    PromptLayers,
    build_system_prompt,
    select_variant,
)


def test_mini_is_just_hard_rules_within_budget() -> None:
    layers = PromptLayers(user_text="hi", variant="mini", budget_chars=MINI_BUDGET_CHARS)
    prompt = build_system_prompt(layers)
    assert HONESTY_RULE in prompt
    assert NO_GUESS_RULE in prompt
    assert "web_search" not in prompt  # mini carries no tool catalogue
    assert len(prompt) <= MINI_BUDGET_CHARS


def test_full_carries_tool_policy_within_budget() -> None:
    layers = PromptLayers(user_text="hi", variant="full", budget_chars=FULL_BUDGET_CHARS)
    prompt = build_system_prompt(layers)
    assert "web_search" in prompt
    assert "read_file before editing" in prompt
    assert HONESTY_RULE in prompt
    assert len(prompt) <= FULL_BUDGET_CHARS


def test_task_and_project_rules_always_survive_tiny_budget() -> None:
    layers = PromptLayers(
        user_text="migrate the auth module",
        variant="full",
        budget_chars=900,
        role="A very long profile " * 200,
        workspace="Current workspace: /x",
        project_rules="tests run through pytest",
        memory="memory line",
        knowledge="knowledge line",
        skill_blocks=["skill one", "skill two"],
    )
    prompt = build_system_prompt(layers)
    assert "migrate the auth module" in prompt
    assert "tests run through pytest" in prompt
    assert HONESTY_RULE in prompt  # core policy never drops
    assert NO_GUESS_RULE in prompt

def test_layer_order_task_after_policy() -> None:
    prompt = build_system_prompt(PromptLayers(user_text="do the thing"))
    assert prompt.index("You are AXIOM") < prompt.index("Current task: do the thing")


def test_select_variant_tracks_complexity_and_mode() -> None:
    assert select_variant("hi") == "mini"
    assert select_variant("hi", mode="deep") == "full"
    assert select_variant("hi", mode="fast") == "mini"
    assert select_variant("hi", budget="economy") == "mini"
    hard = ("почему падает прод? придумай архитектурный план, сравни подходы, "
            "проанализируй узкие места базы данных, докажи корректность решения "
            "и объясни почему выбран именно этот дизайн архитектуры оптимизации отладки")
    assert select_variant(hard) == "full"
    assert classify_mode("hi") == "quick"


def test_no_chain_of_thought_instruction_is_injected() -> None:
    for variant in ("mini", "full"):
        prompt = build_system_prompt(PromptLayers(user_text="x", variant=variant))
        lowered = prompt.lower()
        assert "chain-of-thought" not in lowered
        assert "think step by step" not in lowered
        assert "скрыт" not in lowered


def test_mini_and_full_share_the_same_invariants() -> None:
    for variant, budget in (("mini", MINI_BUDGET_CHARS), ("full", FULL_BUDGET_CHARS)):
        prompt = build_system_prompt(
            PromptLayers(
                user_text="explain why the build failed and fix it",
                variant=variant,
                budget_chars=budget,
                workspace="Current workspace: /repo",
                project_rules="pytest gates every merge",
                memory=" memory: user likes pytest ",
                skill_blocks=["skill: use pytest -q"],
            )
        )
        assert HONESTY_RULE in prompt
        assert NO_GUESS_RULE in prompt
        assert "explain why the build failed" in prompt
        assert "Response style" in prompt
        assert len(prompt) <= budget


async def test_agent_still_injects_memory_through_builder(tmp_path, monkeypatch) -> None:
    """DoD: current prompt invariants pass end to end through Agent.run."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.history import HistoryStore
    from axiom.core.memory import MemoryItem
    from axiom.core.models import ModelInfo
    from axiom.core.ollama import OllamaClient, StreamChunk

    class FakeClient(OllamaClient):
        def __init__(self) -> None:
            super().__init__()
            self.chat_calls: list[dict] = []

        async def is_available(self) -> bool:
            return True

        async def version(self) -> str:
            return "0.0-test"

        async def list_models(self) -> list[dict]:
            return [{"name": "m", "details": {}, "capabilities": []}]

        async def chat(self, model, messages, **kwargs):  # type: ignore[override]
            self.chat_calls.append({"model": model, "messages": messages})
            yield StreamChunk(content="ok")
            yield StreamChunk(done=True)

    client = FakeClient()
    session = ChatSession(
        config=Config(model="m"),
        client=client,
        history_store=HistoryStore(directory=tmp_path / "history"),
    )
    session.active_model = ModelInfo(name="m", capabilities=[])
    session.memory_store.add(MemoryItem(content="User prefers concise pytest answers"))
    history = [{"role": "user", "content": "how should I write pytest tests?"}]
    async for _ in session.agent.run(history, session.active_model):
        pass
    system = client.chat_calls[0]["messages"][0]
    assert system["role"] == "system"
    assert "Relevant memory" in system["content"]
    assert "concise pytest answers" in system["content"]
    assert HONESTY_RULE in system["content"]
    assert len(system["content"]) <= FULL_BUDGET_CHARS
    assert session.agent.last_prompt_variant in {"mini", "full"}

