"""Unit tests for :mod:`axiom.core.performance` and the agent's ``perf`` profile."""

from __future__ import annotations

import time

from axiom.core.agent import Agent
from axiom.core.config import Config
from axiom.core.models import ModelInfo
from axiom.core.ollama import OllamaClient
from axiom.core.performance import (
    AGENT_MODE,
    QUICK_MODE,
    PerformanceMetrics,
    Timer,
    adapt_level,
    capture_metrics,
    classify_cold,
    classify_mode,
    compare_metrics,
    complexity_of,
    diagnose,
    summarize_runs,
    thinking_level,
    tool_scope,
)
from axiom.core.state_machine import GenerationStateMachine
from axiom.core.tools.registry import ToolRegistry


def _perf(**fields) -> PerformanceMetrics:
    defaults = {
        "model": "m",
        "first_chunk_ms": 100.0,
        "http_start_ms": 80.0,
        "last_token_ms": 500.0,
        "first_visible_ms": 250.0,
        "finished_ms": 520.0,
        "reasoning_chars": 60,
        "answer_chars": 120,
        "eval_ms": 400.0,
        "tokens_out": 20,
    }
    defaults.update(fields)
    return PerformanceMetrics(**defaults).finalize()


def test_from_ollama_converts_nanoseconds_and_tokens():
    m = PerformanceMetrics.from_ollama(
        {
            "eval_count": 30,
            "prompt_eval_count": 12,
            "eval_duration": 3_000_000_000,
            "total_duration": 8_000_000_000,
            "load_duration": 1_500_000_000,
        }
    )
    assert m.tokens_out == 30
    assert m.tokens_in == 12
    assert m.eval_ms == 3000.0
    assert m.ollama_total_ms == 8000.0
    assert m.load_ms == 1500.0
    assert m.tokens_per_second == 10.0
    assert m.cold is True


def test_from_ollama_missing_values_stay_none():
    m = PerformanceMetrics.from_ollama({})
    assert m.tokens_out is None
    assert m.tokens_in is None
    assert m.eval_ms is None
    assert m.tokens_per_second is None
    assert m.load_ms is None


def test_finalize_derives_ttft_reasoning_answer_generation():
    m = _perf()
    # ttft = first_chunk - http_start = 100 - 80
    assert m.ttft_ms == 20.0
    # generation = last_token - first_chunk = 500 - 100
    assert m.generation_ms == 400.0
    # reasoning = first_visible - first_chunk = 250 - 100
    assert m.reasoning_ms == 150.0
    # answer = last_token - first_visible = 500 - 250
    assert m.answer_ms == 250.0
    assert m.reasoning_chars_per_s is not None
    assert m.answer_chars_per_s is not None
    # overhead = finished - ollama_total (None here) -> stays None
    assert m.overhead_ms is None


def test_finalize_nttft_falls_back_to_first_chunk():
    m = _perf(http_start_ms=None)
    assert m.ttft_ms == 100.0


def test_summarize_runs_splits_cold_warm_and_aggregates():
    cold = _perf(model="m", load_ms=2000.0)
    warm1 = _perf(model="m", load_ms=0.0)
    warm2 = _perf(model="m", load_ms=0.0)
    summary = summarize_runs([cold, warm1, warm2])
    assert summary["meta"]["model"] == "m"
    assert summary["cold"]["count"] == 1
    assert summary["warm"]["count"] == 2
    assert summary["overall"]["count"] == 3
    # every numeric field carries a min/median/mean/max block
    entry = summary["overall"]["ttft_ms"]
    assert set(entry) == {"min", "median", "mean", "max"}
    assert entry["median"] == round(20.0, 2)


def test_summarize_runs_empty():
    summary = summarize_runs([])
    assert summary["meta"]["model"] is None
    assert summary["overall"]["count"] == 0
    assert summary["overall"]["ttft_ms"]["median"] is None


def test_classify_cold():
    assert classify_cold(_perf(load_ms=2000.0)) is True
    assert classify_cold(_perf(load_ms=0.0), was_warmed=True) is False
    assert classify_cold(_perf(load_ms=0.0), was_warmed=False) is True


def test_diagnose_reports_cold_ttft_and_slow_generation():
    # Very cold, very slow first token, low tokens/sec -> three observations.
    m = _perf(
        load_ms=5000.0,
        ttft_ms=None,
        first_chunk_ms=5000.0,
        http_start_ms=0.0,
        tokens_out=5,
        eval_ms=4000.0,
        tokens_per_second=1.25,
    ).finalize()
    summary = summarize_runs([m])
    lines = diagnose(summary)
    assert any("load" in line for line in lines)
    assert any("time-to-first-token" in line for line in lines)
    assert any("Slow generation" in line for line in lines)


def test_agent_build_perf_shapes_profile():
    from axiom.core.performance import PerformanceMetrics as PM

    agent = Agent(
        OllamaClient(),
        config=Config(),
        registry=ToolRegistry(),
        machine=GenerationStateMachine(),
    )
    started = time.perf_counter() - 1.0
    perf = agent._build_perf(
        raw_metrics={"eval_count": 10, "eval_duration": 1_000_000_000},
        started=started,
        prompt_built_at=started + 0.05,
        http_at=started + 0.1,
        first_chunk_at=started + 0.3,
        first_visible_at=started + 0.4,
        last_token_at=started + 0.7,
        model=ModelInfo(name="m", capabilities=["thinking", "tools"]),
        think="high",
        tools=True,
        context_chars=100,
        reasoning_chars=20,
        answer_chars=40,
        tool_rounds=1,
        tool_s=0.05,
    )
    assert isinstance(perf, PM)
    assert perf.model == "m"
    assert perf.think == "high"
    assert perf.tools is True
    assert perf.tool_rounds == 1
    assert perf.tool_ms == 50.0
    assert perf.tokens_out == 10
    assert perf.tokens_per_second == 10.0
    assert perf.ttft_ms == round((0.3 - 0.1) * 1000, 2)
    assert perf.finished_ms is not None


# ------------------------------------------------------------ Performance Engine

def test_classify_mode_quick_vs_agent():
    assert classify_mode("что такое asyncio?") == QUICK_MODE
    assert classify_mode("исправь баг в файле main.py") == AGENT_MODE
    assert classify_mode("запусти pytest") == AGENT_MODE
    assert classify_mode("") == QUICK_MODE


def test_complexity_of_uses_real_request_shape():
    assert complexity_of("привет") == "low"
    assert complexity_of("почему падает тест", context_messages=120) in ("medium", "high")
    assert complexity_of("x " * 200) == "high"


def test_tool_scope_is_minimal_per_request_kind():
    # Web tools stay always-on (two cheap entries); workspace tools are strict.
    assert tool_scope("что такое asyncio?") == ["web_search", "fetch_url"]
    assert tool_scope("прочитай файл src/app.py") == [
        "read_file", "search_text", "search_files", "list_files", "web_search", "fetch_url"
    ]
    edit = tool_scope("исправь баг в файле main.py")
    assert "edit_file" in edit and "run_command" in edit
    git = tool_scope("покажи git diff")
    assert "git_diff" in git and "read_file" in git
    assert tool_scope("run pytest")[:1] == ["run_command"]
    assert "web_search" in tool_scope("найди в интернете новости про python")


def test_tool_scope_respects_disabled_capabilities():
    assert tool_scope("исправь код", workspace=False, terminal=False) == [
        "web_search", "fetch_url"
    ]
    assert tool_scope("найди новости", web=False) is None
    assert tool_scope("что такое asyncio?", web=False) is None


def test_adapt_level_uses_measured_latency_only():
    assert adapt_level("high", ttft_ms=5000, tokens_per_second=None) == "medium"
    assert adapt_level("medium", ttft_ms=None, tokens_per_second=3) == "low"
    assert adapt_level("high", ttft_ms=9000, tokens_per_second=None, budget="performance") == "high"
    assert adapt_level("low", ttft_ms=9000, tokens_per_second=None) == "low"


def test_thinking_level_presets_capability_and_adaptive():
    assert thinking_level("привет", model_supports_thinking=True) == "low"
    assert thinking_level("почему падает тест", model_supports_thinking=True) == "high"
    assert thinking_level("почему падает", model_supports_thinking=False) is None


def test_capture_and_compare_metrics():
    before = capture_metrics(events=3, tokens=10)
    after = capture_metrics(events=8, tokens=25)
    delta = compare_metrics(before, after)
    assert delta["counters"]["events"] == 5
    assert delta["counters"]["tokens"] == 15
    assert delta["elapsed_seconds"] >= 0.0


def test_timer_measures_elapsed(monkeypatch):
    clock = {"now": 10.0}
    monkeypatch.setattr("axiom.core.performance.time.monotonic", lambda: clock["now"])
    with Timer() as timer:
        clock["now"] = 10.5
    assert timer.elapsed == 0.5

    assert thinking_level("x", model_supports_thinking=True, mode="deep") == "high"
    assert thinking_level("x", model_supports_thinking=True, mode="fast") == "low"
    assert thinking_level("почему падает", model_supports_thinking=True, last_ttft_ms=9000) == "medium"
    assert thinking_level("почему падает", model_supports_thinking=True, budget="economy") == "medium"
