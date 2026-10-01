"""Trajectory — append-only запись всего, что видел и делал агент (п.10).

Каждое действие: prompts, reasoning, tool calls/results, subagents,
context injections, метрики. Хранится как JSONL: resume/fork/replay/search.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field

from axiom.core.paging import paginate


@dataclass
class TrajectoryEvent:
    seq: int = 0
    ts: float = 0.0
    run_id: str = ""
    kind: str = ""
    actor: str = ""
    summary: str = ""
    data: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)


class Trajectory:
    """Один запуск: запись событий, персист в JSONL, resume/fork/replay/search."""

    def __init__(self, run_id: str | None = None, *, actor: str = "orchestrator") -> None:
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.actor = actor
        self.started_at = time.time()
        self._events: list[TrajectoryEvent] = []
        self._seq = 0

    @property
    def events(self) -> list[TrajectoryEvent]:
        return list(self._events)

    def append(self, kind: str, summary: str = "", *,
               actor: str = "", data: dict | None = None) -> TrajectoryEvent:
        self._seq += 1
        event = TrajectoryEvent(seq=self._seq, ts=time.time(), run_id=self.run_id,
                                kind=kind, actor=actor or self.actor,
                                summary=summary, data=dict(data or {}))
        self._events.append(event)
        return event

    def timeline(self) -> list[dict]:
        return [{"seq": e.seq, "ts": e.ts, "kind": e.kind, "actor": e.actor,
                 "summary": e.summary} for e in self._events]

    def usages(self) -> dict:
        total_in = 0
        total_out = 0
        total_reason = 0
        cost = 0.0
        latency_ms = 0
        for event in self._events:
            usage = event.data.get("usage") or {}
            if isinstance(usage, dict):
                total_in += int(usage.get("input_tokens") or 0)
                total_out += int(usage.get("output_tokens") or 0)
                total_reason += int(usage.get("reasoning_tokens") or 0)
                cost += float(usage.get("cost_usd") or 0.0)
                latency_ms += int(usage.get("latency_ms") or 0)
        return {"input_tokens": total_in, "output_tokens": total_out,
                "reasoning_tokens": total_reason, "cost_usd": round(cost, 6),
                "latency_ms": latency_ms, "events": len(self._events)}

    def search(self, query: str, limit: int = 50) -> list[TrajectoryEvent]:
        needle = (query or "").casefold()
        if not needle:
            return []
        hits = [e for e in self._events
                if needle in e.summary.casefold()
                or needle in e.kind.casefold()
                or needle in json.dumps(e.data, ensure_ascii=False).casefold()]
        return hits[:max(1, limit)]

    def page(self, offset: int = 0, limit: int = 100) -> dict:
        """One bounded window of the run plus the true total (pagination)."""
        window = paginate(self._events, offset=offset, limit=limit)
        return {
            "run_id": self.run_id,
            "total": window.total,
            "offset": window.offset,
            "limit": window.limit,
            "has_more": window.has_more,
            "events": [event.to_json() for event in window.items],
        }

    def since(self, seq: int) -> list[dict]:
        """Return only events appended after ``seq`` (a delta, not a resend)."""
        return [event.to_json() for event in self._events if event.seq > seq]

    def fork(self, *, actor: str = "") -> Trajectory:
        child = Trajectory(actor=actor or self.actor)
        # История копируется (fork), seq продолжается заново у ребёнка.
        for event in self._events:
            child.append(event.kind, event.summary, actor=event.actor, data=dict(event.data))
        child.append("trajectory.fork", f"forked from {self.run_id}",
                     data={"parent_run_id": self.run_id})
        return child

    def save(self, path) -> None:
        from pathlib import Path as _Path
        target = _Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for event in self._events:
                fh.write(json.dumps(event.to_json(), ensure_ascii=False) + "\n")
        tmp.replace(target)

    @classmethod
    def load(cls, path) -> Trajectory:
        from pathlib import Path as _Path
        target = _Path(path)
        raw = target.read_text(encoding="utf-8").splitlines()
        traj: Trajectory | None = None
        for line in raw:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if traj is None:
                traj = cls(run_id=str(obj.get("run_id") or uuid.uuid4().hex[:12]),
                           actor=str(obj.get("actor") or "orchestrator"))
            traj.append(str(obj.get("kind") or ""), str(obj.get("summary") or ""),
                        actor=str(obj.get("actor") or ""),
                        data=dict(obj.get("data") or {}))
        return traj or cls()

    def replay(self) -> list[dict]:
        """Чистый timeline для Replay/Viewer: без побочных эффектов."""
        return self.timeline()

    def viewer(self) -> dict:
        """Данные Trajectory Viewer (п.11): RUN #id, HH:MM:SS-строки, usage."""
        return {
            "run_id": self.run_id,
            "lines": [
                {
                    "seq": e.seq,
                    "time": time.strftime("%H:%M:%S", time.localtime(e.ts)),
                    "actor": e.actor,
                    "kind": e.kind,
                    "summary": e.summary,
                }
                for e in self._events
            ],
            "usage": self.usages(),
        }

    def detail(self, seq: int) -> dict | None:
        """Раскрытие одного шага (п.14-15): аргументы, ok, stdout/данные."""
        for event in self._events:
            if event.seq == seq:
                return event.to_json()
        return None

    def export_markdown(self) -> str:
        """Export the recorded run as Markdown using only recorded facts."""
        lines = [f"# Orchestration run `{self.run_id}`", "", "## Timeline", ""]
        for event in self._events:
            stamp = time.strftime("%H:%M:%S", time.localtime(event.ts))
            lines.append(f"- `{stamp}` **{event.actor or 'system'}** `{event.kind}` — {event.summary}")
        usage = self.usages()
        lines.extend([
            "", "## Usage", "",
            f"- Events: {usage['events']}",
            f"- Input tokens: {usage['input_tokens']}",
            f"- Output tokens: {usage['output_tokens']}",
            f"- Reasoning tokens: {usage['reasoning_tokens']}",
            f"- Latency: {usage['latency_ms']} ms",
            f"- Cost: ${usage['cost_usd']:.6f}",
        ])
        return "\n".join(lines) + "\n"
