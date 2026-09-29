"""AgentRegistry: реестр агентов без правок Core.

W4.6: the specialist set gains Explorer (read-only reconnaissance),
Frontend and Backend roles with scoped tools, and the compact report
contract every subagent must return — ``RESULT/FINDINGS/FILES/ERRORS/
RECOMMENDATIONS``. Full transcripts stay in the workers' trajectories;
only :func:`compact_report` output ever reaches the main context.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: The only report sections a subagent's result contributes to the main
#: context. Anything else (transcripts, raw thinking) stays in trajectories.
REPORT_SECTIONS: tuple[str, ...] = ("RESULT", "FINDINGS", "FILES", "ERRORS",
                                    "RECOMMENDATIONS")

#: Per-section cap in characters — one report can never flood the prompt.
MAX_SECTION_CHARS = 600
MAX_REPORT_CHARS = 2400


def _section_lines(text: str) -> dict[str, list[str]]:
    """Split a worker answer into its ``SECTION:`` blocks (order preserved)."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in (text or "").splitlines():
        stripped = line.strip()
        head, sep, rest = stripped.partition(":")
        key = head.strip().upper().lstrip("#").strip()
        if sep and key in REPORT_SECTIONS and len(head) <= 40:
            current = key
            sections.setdefault(current, [])
            if rest.strip():
                sections[current].append(rest.strip())
        elif current is not None and stripped:
            sections[current].append(stripped)
    return sections


def compact_report(result: dict | str | None) -> dict:
    """Normalise a subagent outcome into the compact report contract.

    Accepts a runner result dict (``content``/``error``/``report``) or a raw
    answer string. Sectioned answers are parsed; unsectioned prose becomes a
    single ``RESULT`` line (or ``ERRORS`` when the run failed). The function
    never invents findings — it only re-shapes what the worker actually said.
    """
    if isinstance(result, str):
        data: dict = {"content": result}
    else:
        data = dict(result or {})
    existing = data.get("report")
    if isinstance(existing, dict) and any(key in existing for key in REPORT_SECTIONS):
        report = {key: str(existing.get(key) or "").strip()[:MAX_SECTION_CHARS]
                  for key in REPORT_SECTIONS}
    else:
        raw = str(data.get("content") or "")
        parsed = {key: "\n".join(lines).strip()[:MAX_SECTION_CHARS]
                  for key, lines in _section_lines(raw).items()}
        if not parsed:
            # Prose without sections: keep it as the single RESULT block.
            fallback_key = "RESULT"
            if data.get("error") and not raw.strip():
                fallback_key = "ERRORS"
            text = raw.strip() or str(data.get("error") or "").strip()
            parsed = {fallback_key: text[:MAX_SECTION_CHARS]} if text else {}
        report = {key: parsed.get(key, "") for key in REPORT_SECTIONS}
    if data.get("error"):
        error = str(data["error"]).strip()[:MAX_SECTION_CHARS]
        if error and error not in report["ERRORS"]:
            report["ERRORS"] = (report["ERRORS"] + "\n" + error).strip()
    total = sum(len(v) for v in report.values())
    if total > MAX_REPORT_CHARS:
        # Shrink the biggest section first so RESULT survives the longest.
        while total > MAX_REPORT_CHARS:
            key = max(REPORT_SECTIONS, key=lambda k: len(report[k]))
            report[key] = report[key][: max(0, len(report[key]) - 200)]
            total = sum(len(v) for v in report.values())
    return report


@dataclass
class SubagentBudget:
    """Token/time/tool/retry ceilings for one specialist run (W4.6).

    Exhaustion is always explicit: the runner marks ``budget.exhausted``
    with the reason and returns the partial result instead of hanging or
    fabricating completion.
    """

    max_seconds: float = 180.0
    max_tokens: int = 16_000      # estimated output tokens (~4 chars each)
    max_tool_calls: int = 24
    max_retries: int = 3

    def check(self, *, elapsed: float = 0.0, tokens: int = 0,
              tool_calls: int = 0, retries: int = 0) -> str | None:
        """Return the exhausted reason or ``None`` while budget remains."""
        if self.max_seconds > 0 and elapsed > self.max_seconds:
            return "time"
        if self.max_tokens > 0 and tokens > self.max_tokens:
            return "tokens"
        if self.max_tool_calls > 0 and tool_calls > self.max_tool_calls:
            return "tool_calls"
        if self.max_retries > 0 and retries > self.max_retries:
            return "retries"
        return None

    def as_dict(self, *, elapsed: float = 0.0, tokens: int = 0,
                tool_calls: int = 0, retries: int = 0,
                exhausted: str | None = None) -> dict:
        return {"max_seconds": self.max_seconds, "max_tokens": self.max_tokens,
                "max_tool_calls": self.max_tool_calls, "max_retries": self.max_retries,
                "elapsed": round(elapsed, 3), "tokens": tokens,
                "tool_calls": tool_calls, "retries": retries,
                "exhausted": exhausted}


@dataclass
class AgentProfile:
    id: str
    label: str = ""
    provider_id: str = "ollama"
    model: str = ""
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    temperature: float | None = None

    def name(self) -> str:
        return self.label or self.id

DEFAULT_AGENTS: tuple[AgentProfile, ...] = (
    AgentProfile("orchestrator", "Orchestrator"),
    AgentProfile("analyst", "Analyst"),
    AgentProfile("coder", "Coder"),
    AgentProfile("debugger", "Debugger"),
    AgentProfile("reviewer", "Reviewer"),
    AgentProfile("researcher", "Researcher"),
    AgentProfile("tester", "Tester"),
    AgentProfile("architect", "Architect"),
    AgentProfile("security", "Security"),
    # W4.6: the delivery set — Explorer (read-only reconnaissance) plus
    # Frontend and Backend specialists with their own scoped tools.
    AgentProfile("explorer", "Explorer"),
    AgentProfile("frontend", "Frontend"),
    AgentProfile("backend", "Backend"),
)


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentProfile] = {a.id: a for a in DEFAULT_AGENTS}

    def register(self, profile: AgentProfile) -> None:
        self._agents[profile.id] = profile

    def remove(self, agent_id: str) -> bool:
        return self._agents.pop(agent_id, None) is not None

    def get(self, agent_id: str) -> AgentProfile | None:
        return self._agents.get(agent_id)

    def all(self) -> list[AgentProfile]:
        return list(self._agents.values())

    def ids(self) -> list[str]:
        return list(self._agents)
