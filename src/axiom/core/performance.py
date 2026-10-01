"""Performance benchmark & profiling primitives for AXIOM.

UI-free and side-effect-free: it normalises the wall-clock timestamps the agent
captures plus the metrics a real Ollama response reports. Fields Ollama does not
report are left ``None`` — never guessed or estimated.

:class:`PerformanceMetrics` describes one run; :func:`summarize_runs` aggregates
a series into min / median / mean / max per field, split by cold vs warm;
:func:`diagnose` turns a summary into a short bottleneck report.
"""

from __future__ import annotations

import dataclasses
import statistics
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

#: Numeric-meter fields aggregated into min / median / mean / max summaries.
NUMERIC_FIELDS: tuple[str, ...] = (
    "ttft_ms",
    "prompt_built_ms",
    "first_chunk_ms",
    "first_visible_ms",
    "last_token_ms",
    "finished_ms",
    "reasoning_ms",
    "answer_ms",
    "generation_ms",
    "tokens_in",
    "tokens_out",
    "tokens_per_second",
    "prompt_eval_ms",
    "eval_ms",
    "load_ms",
    "ollama_total_ms",
    "overhead_ms",
    "reasoning_chars_per_s",
    "answer_chars_per_s",
    "tool_ms",
)


class PerformanceMetrics(BaseModel):
    """Real measurements of one generation run.

    Timings are milliseconds. Ollama-derived fields (``tokens_*``,
    ``prompt_eval_ms``, ``eval_ms``, ``load_ms``, ``ollama_total_ms``) are
    ``None`` whenever the model did not report them.
    """

    # identity
    model: str | None = None
    think: str | None = None
    tools: bool = False
    scenario: str | None = None
    run_index: int = 0
    context_chars: int = 0

    # measured / raw (ms since run start)
    prompt_built_ms: float | None = None
    http_start_ms: float | None = None
    first_chunk_ms: float | None = None
    first_visible_ms: float | None = None
    last_token_ms: float | None = None
    finished_ms: float | None = None

    # derived profiles (ms)
    ttft_ms: float | None = None
    reasoning_ms: float | None = None
    answer_ms: float | None = None
    generation_ms: float | None = None

    # Ollama-derived metrics
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_per_second: float | None = None
    prompt_eval_ms: float | None = None
    eval_ms: float | None = None
    load_ms: float | None = None
    ollama_total_ms: float | None = None
    overhead_ms: float | None = None

    # text & throughput
    reasoning_chars: int = 0
    answer_chars: int = 0
    reasoning_chars_per_s: float | None = None
    answer_chars_per_s: float | None = None

    # tools
    tool_rounds: int = 0
    tool_ms: float | None = None

    #: True when Ollama reported having to load the model (a cold start).
    cold: bool = True

    def finalize(self) -> PerformanceMetrics:
        """Compute derived fields from raw measurements (idempotent)."""
        self.ttft_ms = self.first_chunk_ms
        if self.first_chunk_ms is not None and self.http_start_ms is not None:
            self.ttft_ms = round(self.first_chunk_ms - self.http_start_ms, 2)
        if self.first_chunk_ms is not None and self.last_token_ms is not None:
            self.generation_ms = round(max(0.0, self.last_token_ms - self.first_chunk_ms), 2)
        if self.reasoning_chars:
            start = self.first_chunk_ms
            end = self.first_visible_ms if self.first_visible_ms is not None else self.last_token_ms
            if start is not None and end is not None:
                self.reasoning_ms = round(max(0.0, end - start), 2)
        if self.answer_chars and self.first_visible_ms is not None and self.last_token_ms is not None:
            self.answer_ms = round(max(0.0, self.last_token_ms - self.first_visible_ms), 2)
        if self.reasoning_ms and self.reasoning_chars:
            self.reasoning_chars_per_s = round(self.reasoning_chars / (self.reasoning_ms / 1000), 1)
        if self.answer_ms and self.answer_chars:
            self.answer_chars_per_s = round(self.answer_chars / (self.answer_ms / 1000), 1)
        if self.finished_ms is not None and self.ollama_total_ms is not None:
            self.overhead_ms = round(self.finished_ms - self.ollama_total_ms, 1)
        self.cold = self.load_ms is not None and self.load_ms >= 1.0
        return self

    @classmethod
    def from_ollama(cls, metrics: dict[str, Any], **overrides: Any) -> PerformanceMetrics:
        """Build from a raw Ollama final-chunk ``metrics`` dict (nanoseconds).

        Durations are converted to milliseconds; ``eval_count`` /
        ``prompt_eval_count`` become token counts; tokens-per-second is derived
        from ``eval_count`` / ``eval_duration``.
        """
        data: dict[str, Any] = {
            "tokens_out": metrics.get("eval_count") if isinstance(metrics.get("eval_count"), int) else None,
            "tokens_in": metrics.get("prompt_eval_count")
            if isinstance(metrics.get("prompt_eval_count"), int)
            else None,
        }
        for ns_key, ms_key in (
            ("total_duration", "ollama_total_ms"),
            ("load_duration", "load_ms"),
            ("prompt_eval_duration", "prompt_eval_ms"),
            ("eval_duration", "eval_ms"),
        ):
            value = metrics.get(ns_key)
            data[ms_key] = round(value / 1_000_000, 2) if isinstance(value, int) else None
        eval_count = data["tokens_out"]
        eval_ms = data["eval_ms"]
        if isinstance(eval_count, int) and isinstance(eval_ms, float) and eval_ms > 0:
            data["tokens_per_second"] = round(eval_count / (eval_ms / 1000), 1)
        data.update(overrides)
        return cls(**data).finalize()
def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def summarize_runs(runs: list[PerformanceMetrics]) -> dict[str, Any]:
    """Aggregate runs into per-field min/median/mean/max (cold/warm/overall)."""

    def _aggregate(subset: list[PerformanceMetrics]) -> dict[str, Any]:
        out: dict[str, Any] = {"count": len(subset)}
        for field in NUMERIC_FIELDS:
            values = [v for r in subset if (v := getattr(r, field)) is not None]
            if values:
                mn = round(min(values), 2)
                md = round(statistics.median(values), 2)
                mx = round(max(values), 2)
            else:
                mn = md = mx = None
            out[field] = {
                "min": mn,
                "median": md,
                "mean": _mean(values),
                "max": mx,
            }
        return out

    cold = [r for r in runs if r.cold]
    warm = [r for r in runs if not r.cold]
    meta = {
        "model": runs[0].model if runs else None,
        "scenario": runs[0].scenario if runs else None,
        "think": runs[0].think if runs else None,
    }
    return {
        "meta": meta,
        "runs": [r.model_dump() for r in runs],
        "cold": _aggregate(cold),
        "warm": _aggregate(warm),
        "overall": _aggregate(runs),
    }


def classify_cold(run: PerformanceMetrics, was_warmed: bool = False) -> bool:
    """Classify one run as cold/warm.

    Warm when the model was already resident and Ollama reported no load; a
    model Ollama had to reload is cold regardless of run order.
    """
    if run.load_ms is not None and run.load_ms >= 1.0:
        return True
    return not was_warmed


def diagnose(summary: dict[str, Any]) -> list[str]:
    """Short bottleneck observations from a :func:`summarize_runs` result."""
    stats = summary.get("overall", {})
    lines: list[str] = []

    def _med(field: str) -> float | None:
        entry = stats.get(field)
        if isinstance(entry, dict):
            value = entry.get("median")
            return float(value) if value is not None else None
        return None

    load = _med("load_ms")
    ttft = _med("ttft_ms")
    gen = _med("generation_ms")
    reasoning = _med("reasoning_ms")
    answer = _med("answer_ms")
    tps = _med("tokens_per_second")
    overhead = _med("overhead_ms")
    prompt_eval = _med("prompt_eval_ms")

    if load is not None and load >= 1.0:
        lines.append(f"Cold model load dominates: median load {load:.0f} ms.")
    if ttft is not None and ttft >= 2000:
        lines.append(f"High time-to-first-token (median {ttft:.0f} ms).")
    if tps is not None and tps < 10:
        lines.append(f"Slow generation: median {tps:.1f} tokens/s.")
    if reasoning is not None and gen and gen > 0 and reasoning / gen > 0.6:
        lines.append(f"Reasoning dominates generation ({reasoning:.0f} ms of {gen:.0f} ms).")
    if answer is not None and gen and gen > 0 and answer / gen > 0.8:
        lines.append(f"Answer phase dominates ({answer:.0f} ms of {gen:.0f} ms).")
    if prompt_eval is not None and prompt_eval >= 1500:
        lines.append(f"Prompt processing is slow (median {prompt_eval:.0f} ms).")
    if overhead is not None and overhead > 150:
        lines.append(f"AXIOM overhead above Ollama total: median {overhead:.0f} ms.")
    return lines


# --------------------------------------------------------------- task policy
#: Task solved by a single model pass, no tools at all.
QUICK_MODE = "quick"
#: Task that needs the tool / observe / validate loop.
AGENT_MODE = "agent"

#: Deterministic markers — a local classification, never an extra LLM call.
_WEB_MARKERS = (
    "найди", "поищи", "погугли", "в интернете", "новост", "курс ", "котировк",
    "погод", "актуальн", "последн", "сегодня", "вчера", "2025", "2026",
    "search", "google", "latest", "current", "news", "price", "who is", "when did",
)
_READ_MARKERS = (
    "файл", "код", "функци", "класс", "модул", "проект", "папк", "структур",
    "найди в проект", "посмотри", "изучи код", "репозитор", "импорт",
    "file", "code", "function", "class", "module", "project", "folder",
    "repository", "codebase", "import",
)
_EDIT_MARKERS = (
    "сделай", "сделать", "доработа", "улучш", "передела", "перенеси", "исправ",
    "измени", "отредакт", "перепиши", "добавь", "удали", "создай",
    "реализуй", "доведи", "поддерж", "рефактор", "напиши", "замени", "вставь", "обнови",
    "fix", "edit", "change", "refactor", "implement", "add ", "remove",
    "create", "rewrite", "update", "write ",
)
_TERMINAL_MARKERS = (
    "запусти", "выполни", "скомпилируй", "собери", "установи", "тест", "pytest",
    "npm ", "cargo ", "pip ", "зависимост", "команд",
    "run ", "execute", "build", "install", "command", "compile", "test suite",
)
_GIT_MARKERS = (
    "git", "коммит", "commit", "ветк", "branch", "diff", "дифф", "лог", "log",
    "merge", "rebase", "pull", "push", "статус репозитор",
)
_MEMORY_MARKERS = (
    "запомни", "запомнить", "напомни", "запиши в памят", "мои предпочтени",
    "что ты помниш", "что я говорил", "remember", "my preference",
    "what do you know about me", "don't forget", "memory",
)
_KNOWLEDGE_MARKERS = (
    "база знаний", "знания", "мои документы", "мои заметки", "в документах",
    "в заметках", "проиндексируй", "knowledge", "my documents", "my notes",
    "my docs", "index this folder", "knowledge base",
)
_HARD_MARKERS = (
    "почему", "придумай", "реши", "напиши", "рефактор", "отлад",
    "debug", "why ", "explain", "design", "optimi", "architect",
    "докажи", "проанализируй", "сравни",
)

#: Scope → tools for each category. Aggressive: an ordinary question gets
#: zero tools, a file question gets only the read tools it needs.
_SCOPE_READ = ("read_file", "search_text", "search_files", "list_files")
_SCOPE_EDIT = ("read_file", "write_file", "edit_file", "apply_patch", "search_text", "search_files")
_SCOPE_TERMINAL = ("run_command", "run_tests", "run_linter", "build_project", "verify_changes")
_SCOPE_GIT = ("git_status", "git_diff", "git_log", "git_branch", "git_graph")
_SCOPE_PROJECT = ("inspect_project",)
_SCOPE_WEB = ("web_search", "fetch_url")
#: W2.1 Curated Memory — read is cheap/always safe, write/forget need approval.
_SCOPE_MEMORY = ("memory_read", "memory_write", "memory_forget")
#: W2.2 Knowledge Base — search/status are read-only; index is idempotent.
_SCOPE_KNOWLEDGE = ("knowledge_search", "knowledge_index", "knowledge_status")


def complexity_of(text: str, *, context_messages: int = 0) -> str:
    """low / medium / high — from the real request shape only."""
    words = len((text or "").split())
    markers = sum(1 for m in _HARD_MARKERS if m in (text or "").lower())
    score = words + markers * 12 + max(0, context_messages) // 4
    if score < 18:
        return "low"
    if score < 80:
        return "medium"
    return "high"


def classify_mode(text: str) -> str:
    """``quick`` for a plain question, ``agent`` when tools are really needed.

    Runs on text only: no network, no model, no latency cost.
    """
    lowered = (text or "").lower().strip()
    if not lowered:
        return QUICK_MODE
    has_web = any(m in lowered for m in _WEB_MARKERS)
    has_read = any(m in lowered for m in _READ_MARKERS)
    has_edit = any(m in lowered for m in _EDIT_MARKERS)
    has_terminal = any(m in lowered for m in _TERMINAL_MARKERS)
    has_git = any(m in lowered for m in _GIT_MARKERS)
    if has_edit or has_terminal or has_git or has_read or has_web:
        return AGENT_MODE
    return QUICK_MODE


def tool_scope(
    text: str,
    *,
    workspace: bool = True,
    terminal: bool = True,
    web: bool = True,
) -> list[str] | None:
    """Minimal deterministic tool set for this request (``None`` = no tools).

    The two web tools stay always-on (cheap, two entries, and pasted links
    depend on them). Workspace/git/terminal tools are strictly per request:
    a file question gets the read tools, an edit gets read+edit, git gets the
    git tools, a terminal request gets ``run_command``. The model never
    receives 15 definitions "just in case".
    """
    lowered = (text or "").lower()
    if not lowered.strip():
        return None
    out: list[str] = []

    def _add(names: tuple[str, ...], enabled: bool) -> None:
        if not enabled:
            return
        for name in names:
            if name not in out:
                out.append(name)

    has_git = any(m in lowered for m in _GIT_MARKERS)
    has_terminal = any(m in lowered for m in _TERMINAL_MARKERS)
    has_edit = any(m in lowered for m in _EDIT_MARKERS)
    has_read = any(m in lowered for m in _READ_MARKERS)
    has_project = any(m in lowered for m in ("проект", "структур", "что делает", "project"))
    has_memory = any(m in lowered for m in _MEMORY_MARKERS)

    if has_git:
        _add(_SCOPE_GIT, workspace)
        _add(_SCOPE_READ, workspace)
    elif has_edit:
        _add(_SCOPE_EDIT, workspace)
    elif has_read:
        _add(_SCOPE_READ, workspace)
    if has_project:
        _add(_SCOPE_PROJECT, workspace)
    if (has_terminal or has_edit) and terminal:
        _add(_SCOPE_TERMINAL, True)
    # Memory tools are not workspace-scoped: they are registered unconditionally.
    if has_memory:
        _add(_SCOPE_MEMORY, True)
    # W2.2: knowledge tools are not workspace-scoped either; they appear when
    # the request mentions documents/notes/knowledge explicitly.
    if any(m in lowered for m in _KNOWLEDGE_MARKERS):
        _add(_SCOPE_KNOWLEDGE, True)
    _add(_SCOPE_WEB, web)
    return out or None


def adapt_level(
    level: str,
    *,
    ttft_ms: float | None,
    tokens_per_second: float | None,
    budget: str = "balanced",
) -> str:
    """Lower the reasoning level when the previous run measured slow.

    Uses only real measurements: a high TTFT or a low throughput from the
    previous request. ``performance`` budget deliberately keeps the level.
    """
    if budget == "performance":
        return level
    slow = (ttft_ms is not None and ttft_ms >= 3000) or (
        tokens_per_second is not None and tokens_per_second < 8
    )
    if not slow:
        return level
    order = ("low", "medium", "high")
    if level not in order:
        return level
    index = max(0, order.index(level) - 1)
    return order[index]


def thinking_level(
    text: str,
    *,
    model_supports_thinking: bool,
    mode: str = "auto",
    budget: str = "balanced",
    last_ttft_ms: float | None = None,
    last_tokens_per_second: float | None = None,
) -> bool | str | None:
    """Deterministic reasoning level for one request.

    Same heuristic the agent always used (hard task → high, long task →
    medium, small talk → low) plus the Performance Engine adaptations:
    ``fast``/``normal``/``deep`` presets, ``economy`` cost-aware lowering and
    the measured-TTFT/throughput correction. Never calls an extra model.
    """
    level = {"fast": "low", "normal": "medium", "deep": "high"}.get(mode)
    if level is None:
        if not model_supports_thinking:
            return None
        lowered = (text or "").lower()
        if any(marker in lowered for marker in _HARD_MARKERS):
            level = "high"
        elif len(lowered) > 200:
            level = "medium"
        else:
            level = "low"
    elif not model_supports_thinking:
        return None
    if budget == "economy":
        level = adapt_level(level, ttft_ms=3001.0, tokens_per_second=None, budget="balanced")
    level = adapt_level(
        level,
        ttft_ms=last_ttft_ms,
        tokens_per_second=last_tokens_per_second,
        budget=budget,
    )
    return level


@dataclass
class MetricsSnapshot:
    """A wall-clock point plus named counters, for before/after comparison."""

    ts: float
    counters: dict[str, int] = dataclasses.field(default_factory=dict)


def capture_metrics(**counters: int) -> MetricsSnapshot:
    """Capture a real ``time.monotonic`` timestamp plus optional counters."""
    return MetricsSnapshot(ts=time.monotonic(), counters={k: int(v) for k, v in counters.items()})


def compare_metrics(before: MetricsSnapshot, after: MetricsSnapshot) -> dict:
    """Return the before/after delta: elapsed seconds and per-counter changes."""
    keys = sorted(set(before.counters) | set(after.counters))
    return {
        "elapsed_seconds": round(after.ts - before.ts, 6),
        "counters": {
            key: after.counters.get(key, 0) - before.counters.get(key, 0) for key in keys
        },
    }


class Timer:
    """Context manager measuring wall-clock elapsed for one block (before/after)."""

    def __enter__(self) -> Timer:
        self._start = time.monotonic()
        return self

    def __exit__(self, *exc: object) -> bool:
        self._end = time.monotonic()
        return False

    @property
    def elapsed(self) -> float:
        end = getattr(self, "_end", time.monotonic())
        return max(0.0, end - self._start)
