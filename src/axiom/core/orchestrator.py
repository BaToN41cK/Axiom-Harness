"""Orchestrator — управляет агентами, а не просто шлёт запрос модели (п.7).

План: analyze -> select agents -> delegate (subagents) -> verify -> result.
Саб­агенты здесь — записи trajectory + делегирование через колбэк раннера,
чтобы Core не зависел от конкретной модели.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from axiom.core.agents import AgentRegistry
from axiom.core.bus import (
    AGENT_CREATED,
    AGENT_FAILED,
    AGENT_STARTED,
    AGENT_STEP,
    EventBus,
)
from axiom.core.tools.meta import resolve_tools_for_task, tools_for_agent
from axiom.core.trajectory import Trajectory

SubagentRunner = Callable[..., Awaitable[dict]]


@dataclass
class Subagent:
    id: str
    agent: str
    task: str
    status: str = "pending"
    result: dict = field(default_factory=dict)


@dataclass
class OrchestratorPlan:
    mode: str = "chat"
    agents: list[str] = field(default_factory=list)
    subagents: list[Subagent] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    task: str = ""
    context: dict = field(default_factory=dict)
    definition_of_done: list[str] = field(default_factory=list)
    max_iterations: int = 3
    dependencies: dict[str, list[str]] = field(default_factory=dict)


class Orchestrator:
    """Планировщик поверх AgentRegistry + Trajectory + EventBus."""

    def __init__(self, agents: AgentRegistry | None = None, bus: EventBus | None = None) -> None:
        self.agents = agents or AgentRegistry()
        self.bus = bus or EventBus()

    def plan(self, text: str, *, force_orchestrated: bool = False) -> OrchestratorPlan:
        lowered = (text or "").lower()
        explicit = force_orchestrated or any(marker in lowered for marker in (
            "оркестр", "orchestrat", "нескольк моделей", "до пяти агент",
        ))
        if explicit:
            mode = "orchestrated"
            # Four workers plus one reviewer; orchestration itself is not a sixth
            # worker. Researcher is added only when the request needs external facts.
            fourth = "researcher" if any(
                k in lowered for k in ("web", "документ", "api", "верси", "research")
            ) else "tester"
            agents = ["analyst", "coder", "debugger", fourth, "reviewer"][:5]
        elif any(k in lowered for k in ("исправ", "fix", "bug", "баг", "error", "ошибк", "падает", "debug")):
            mode = "debug"
            agents = ["analyst", "coder", "debugger", "tester"][:5]
        elif any(k in lowered for k in ("review", "проверь", "pr", "ревью")):
            mode = "review"
            agents = ["analyst", "reviewer", "security", "tester"][:5]
        elif any(k in lowered for k in ("research", "найди", "изучи", "что делает", "документ", "research")):
            mode = "research"
            agents = ["analyst", "researcher", "architect", "reviewer"][:5]
        elif any(k in lowered for k in ("test", "тест", "pytest")):
            mode = "test"
            agents = ["analyst", "tester", "debugger", "reviewer"][:5]
        elif any(k in lowered for k in ("refactor", "рефактор", "implement", "реализуй", "добавь", "code", "код")):
            mode = "code"
            agents = ["analyst", "architect", "coder", "tester", "reviewer"][:5]
        else:
            mode = "chat"
            agents = ["analyst"]
        agents = [a for a in agents if self.agents.get(a) is not None]
        tools = resolve_tools_for_task(text)
        done = [
            "Понять структуру и ограничения проекта",
            "Выполнить необходимые изменения или анализ",
            "Проверить результат доступными тестами/командами",
            "Не утверждать непроверенные факты",
        ]
        subs = [Subagent(id=f"{a}-1", agent=a, task=text) for a in agents]
        dependencies = {
            agent: (["analyst"] if agent not in {"analyst", "reviewer"} else [])
            for agent in agents
        }
        if "reviewer" in agents:
            dependencies["reviewer"] = [agent for agent in agents if agent != "reviewer"]
        return OrchestratorPlan(mode=mode, agents=agents, subagents=subs, tools=tools,
                                task=text, context={"project": "", "files": []},
                                definition_of_done=done, dependencies=dependencies)

    def tools_for(self, agent_id: str, task: str = "") -> list[str]:
        base = list(tools_for_agent(agent_id)) or resolve_tools_for_task(task)
        # Agent receives only its scoped tools.
        return base

    def _review_task(self, text: str, results: list[dict], iteration: int) -> str:
        compact = "\n".join(
            f"- {r.get('agent', 'unknown')}: {str(r.get('content') or r.get('error') or r.get('summary') or '')[:1200]}"
            for r in results
        )
        return (
            "Review the specialized agents below against the original task. "
            "Return APPROVED if complete and verified, or REWORK with concrete corrections. "
            "Do not invent checks.\n\n"
            f"Original task:\n{text}\n\nAgent reports:\n{compact}\n\n"
            f"Iteration: {iteration}. Definition of Done: implementation exists, relevant checks ran, "
            "and failures are reported.\n\n"
            "Reply with JSON only: "
            '{"approved": true/false, "reason": "...", "issues": [...], "required_changes": [...]}.'
        )

    @staticmethod
    def _review_decision(report: dict) -> tuple[bool, str, dict]:
        """Parse the structured review contract from a reviewer report.

        The reviewer role is instructed to reply with JSON containing
        ``approved``, ``reason``, ``issues`` and ``required_changes``. Real
        models often wrap that payload in prose, so the parser accepts both
        strict JSON and the legacy APPROVED/REWORK marker convention.
        """
        import json
        import re

        data = dict(report or {})
        issues: list[str] = list(data.get("issues") or [])
        required: list[str] = list(data.get("required_changes") or [])
        approved: bool | None = None
        if isinstance(data.get("approved"), bool):
            approved = bool(data.get("approved"))
        reason = str(data.get("reason") or "").strip()
        raw = str(data.get("content") or data.get("summary") or "")
        if raw.strip():
            candidate = raw.strip()
            fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL | re.IGNORECASE)
            if fence:
                candidate = fence.group(1)
            else:
                start, end = candidate.find("{"), candidate.rfind("}")
                if 0 <= start < end:
                    candidate = candidate[start:end + 1]
            try:
                parsed = json.loads(candidate)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, dict):
                if isinstance(parsed.get("approved"), bool) and approved is None:
                    approved = bool(parsed.get("approved"))
                if not reason:
                    reason = str(parsed.get("reason") or "").strip()
                for key, target in (("issues", issues), ("required_changes", required)):
                    extra = parsed.get(key)
                    if isinstance(extra, list):
                        for item in extra:
                            text_item = str(item).strip()
                            if text_item and text_item not in target:
                                target.append(text_item)
        text = raw.upper()
        if approved is None:
            if "approved" in data and not isinstance(data.get("approved"), bool):
                approved = str(data.get("approved") or "").strip().upper() == "APPROVED"
            else:
                approved = not any(marker in text for marker in ("REWORK", "NEEDS", "FAIL"))
        if not reason:
            reason = raw.strip() or ("Reviewer approved the result" if approved
                                     else "Reviewer requested rework")
        if not approved and not issues and not required:
            # Keep the rework loop actionable even when the reviewer only
            # returns a prose verdict without structured change requests.
            legacy = re.findall(r"(?im)^\s*(?:[-*]\s*|\d+[.)]\s*)(.+)$", raw)
            for item in legacy[:8]:
                cleaned = item.strip()
                if cleaned and cleaned not in required:
                    required.append(cleaned)
            if not required and reason and reason not in required:
                required.append(reason[:500])
        return approved, reason, {
            "approved": approved,
            "reason": reason,
            "issues": issues,
            "required_changes": required,
        }

    @staticmethod
    def _final_report(text: str, plan: OrchestratorPlan, results: list[dict], review: str) -> str:
        lines = ["## Что сделано", ""]
        for result in results:
            agent = str(result.get("agent") or "agent")
            content = str(result.get("content") or result.get("summary") or result.get("error") or "").strip()
            lines.append(f"- **{agent}**: {content[:800] or 'результат не вернул текст'}")
        lines += ["", "## Проверка", f"- Оркестратор: {review[:1200] or 'нет ответа reviewer'}",
                  "- Непроверенные факты не считаются выполненными.", "",
                  "## Что осталось", "Проверить пункты, которые reviewer или tester не смогли подтвердить."]
        return "\n".join(lines)

    async def run(
        self,
        text: str,
        trajectory: Trajectory | None = None,
        runner: SubagentRunner | None = None,
        *,
        parallel: bool = False,
        limit: int = 4,
        max_iterations: int = 3,
        force_orchestrated: bool = False,
        verifier: Callable[[], Awaitable[dict]] | None = None,
    ) -> dict:
        traj = trajectory or Trajectory(actor="orchestrator")
        started = time.perf_counter()
        plan = self.plan(text, force_orchestrated=force_orchestrated)
        bounded_iterations = max(1, min(int(max_iterations), 3))
        self.bus.emit("orchestration.started", {"run_id": traj.run_id, "task": text[:500]})
        traj.append("orchestrator.plan", f"mode={plan.mode} agents={','.join(plan.agents)}",
                    actor="orchestrator", data={"mode": plan.mode, "agents": plan.agents,
                                                 "definition_of_done": plan.definition_of_done,
                                                 "dependencies": plan.dependencies})
        self.bus.emit("orchestration.planned", {"run_id": traj.run_id, "mode": plan.mode,
                                                "agents": plan.agents,
                                                "definition_of_done": plan.definition_of_done})
        self.bus.emit(AGENT_STARTED, {"agent": "orchestrator", "mode": plan.mode, "run_id": traj.run_id})
        if parallel and runner is not None:
            from axiom.core.parallel import run_parallel

            completed = {
                event.actor: dict(event.data)
                for event in traj.events
                if event.kind == "agent.done" and event.actor
            }
            workers = [sub for sub in plan.subagents
                       if sub.agent != "reviewer" and sub.agent not in completed]
            resumed_results = [dict(data, agent=agent, status="done", resumed=True)
                               for agent, data in completed.items() if agent in plan.agents]
            tasks = [{"agent": sub.agent, "task": sub.task,
                      "tools": self.tools_for(sub.agent, sub.task),
                      "trajectory": traj} for sub in workers]
            pres = await run_parallel(tasks, runner, limit=limit, trajectory=traj)
            for result in pres.results:
                self.bus.emit("agent.completed" if result.get("status") == "done" else AGENT_FAILED,
                              {"run_id": traj.run_id, **result})
            duration_ms = pres.duration_ms
            review_text = "Reviewer was not selected for this task."
            review_data: dict = {"approved": True, "reason": review_text,
                                 "issues": [], "required_changes": []}
            approved = True
            iterations = 0
            if "reviewer" in plan.agents:
                for iteration in range(1, bounded_iterations + 1):
                    iterations = iteration
                    self.bus.emit("review.started", {"run_id": traj.run_id, "iteration": iteration})
                    try:
                        review_report = await runner(
                            agent="reviewer",
                            task=self._review_task(text, pres.results, iteration),
                            tools=self.tools_for("reviewer", text), trajectory=traj,
                        )
                    except Exception as exc:
                        review_report = {"approved": False, "reason": f"Reviewer failed: {exc}",
                                        "issues": [str(exc)], "required_changes": ["retry review"]}
                    approved, review_text, review_data = self._review_decision(review_report)
                    traj.append("orchestrator.review", review_text, actor="reviewer",
                                data={**review_data, "iteration": iteration})
                    self.bus.emit("review.completed", {"run_id": traj.run_id,
                                                       "iteration": iteration, **review_data})
                    if approved:
                        break
                    if iteration >= bounded_iterations:
                        self.bus.emit("review.rework_limit", {"run_id": traj.run_id,
                                                              "iterations": iteration})
                        break
                    self.bus.emit("review.rework", {"run_id": traj.run_id, "iteration": iteration,
                                                    "required_changes": list(
                                                        review_data.get("required_changes") or [])})
                    changes = "\n".join(f"- {c}" for c in review_data.get("required_changes") or [])
                    problems = "\n".join(f"- {i}" for i in review_data.get("issues") or [])
                    rework = [{"agent": sub.agent,
                               "task": (f"REVIEW REQUEST:\n{review_text}\n\nIssues:\n{problems}\n\n"
                                        f"Required changes:\n{changes}\n\nOriginal task:\n{text}"),
                               "tools": self.tools_for(sub.agent, text),
                               "trajectory": traj} for sub in workers]
                    pres = await run_parallel(rework, runner, limit=limit, trajectory=traj)
                    for result in pres.results:
                        self.bus.emit("agent.completed" if result.get("status") == "done" else AGENT_FAILED,
                                      {"run_id": traj.run_id, "iteration": iteration, **result})
                    duration_ms += pres.duration_ms
            worker_results = [dict(item, iteration=iterations, review=dict(review_data))
                              for item in resumed_results + pres.results]
            traj.append("orchestrator.done", f"mode={plan.mode} workers={len(worker_results)} approved={approved}",
                        actor="orchestrator", data={"duration_ms": duration_ms, "approved": approved})
            verification = None
            completed = bool(approved)
            if approved and verifier is not None:
                self.bus.emit("verification.started", {"run_id": traj.run_id})
                try:
                    verification = await verifier()
                    self.bus.emit("verification.completed", {**verification, "run_id": traj.run_id})
                except Exception as exc:
                    verification = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                    traj.append("verification.completed", "verification failed", actor="tester", data=verification)
                    self.bus.emit("verification.failed", {"run_id": traj.run_id, **verification})
                else:
                    summary = str(verification.get("summary") or "verification finished")
                    traj.append("verification.completed", summary, actor="tester", data=verification)
                completed = bool(approved and isinstance(verification, dict) and verification.get("ok"))
            self.bus.emit("orchestration.completed",
                          {"run_id": traj.run_id, "approved": approved, "completed": completed,
                           "verification": verification, "duration_ms": duration_ms})
            return {"run_id": traj.run_id, "mode": plan.mode, "agents": plan.agents,
                    "results": worker_results, "merged": pres.merged, "review": review_text,
                    "approved": approved, "completed": completed,
                    "review_details": dict(review_data), "iterations": iterations,
                    "definition_of_done": plan.definition_of_done,
                    "dependencies": plan.dependencies,
                    "verification": verification,
                    "duration_ms": duration_ms, "trajectory": traj}
        results: list[dict] = []
        for sub in plan.subagents:
            self.bus.emit(AGENT_CREATED, {"agent": sub.agent, "task": sub.task, "run_id": traj.run_id})
            traj.append("agent.start", f"{sub.agent}: {sub.task[:120]}", actor=sub.agent)
            sub.status = "running"
            self.bus.emit(AGENT_STEP, {"agent": sub.agent, "step": "start", "run_id": traj.run_id})
            try:
                if runner is not None:
                    out = await runner(agent=sub.agent, task=sub.task,
                                       tools=self.tools_for(sub.agent, sub.task),
                                       trajectory=traj)
                    sub.result = dict(out or {})
                else:
                    sub.result = {"agent": sub.agent, "task": sub.task,
                                  "tools": self.tools_for(sub.agent, sub.task),
                                  "note": "no runner attached"}
                sub.status = "done"
                traj.append("agent.done", f"{sub.agent} done", actor=sub.agent, data=sub.result)
                self.bus.emit(AGENT_STEP, {"agent": sub.agent, "step": "done", "run_id": traj.run_id})
            except Exception as exc:
                sub.status = "failed"
                sub.result = {"error": f"{type(exc).__name__}: {exc}"}
                traj.append("agent.failed", str(exc), actor=sub.agent, data=sub.result)
                self.bus.emit(AGENT_FAILED, {"agent": sub.agent, "error": str(exc), "run_id": traj.run_id})
            results.append({"agent": sub.agent, "status": sub.status, **sub.result})
        review_text = "Reviewer was not selected for this task."
        review_data_seq: dict = {"approved": True, "reason": review_text, "issues": [], "required_changes": []}
        approved = True
        iterations = 0
        if runner is not None and "reviewer" in plan.agents:
            self.bus.emit("review.started", {"run_id": traj.run_id, "iteration": 1})
            try:
                review_report = await runner(
                    agent="reviewer", task=self._review_task(text, results, 1),
                    tools=self.tools_for("reviewer", text), trajectory=traj,
                )
            except Exception as exc:
                review_report = {"approved": False, "reason": f"Reviewer failed: {exc}",
                                 "issues": [str(exc)], "required_changes": ["retry review"]}
            approved, review_text, review_data_seq = self._review_decision(review_report)
            traj.append("orchestrator.review", review_text, actor="reviewer",
                        data={**review_data_seq, "iteration": 1})
            self.bus.emit("review.completed", {"run_id": traj.run_id, "iteration": 1, **review_data_seq})
        duration_ms = int((time.perf_counter() - started) * 1000)
        traj.append("orchestrator.done", f"mode={plan.mode} subagents={len(results)} approved={approved}",
                    actor="orchestrator", data={"duration_ms": duration_ms, "approved": approved})
        self.bus.emit("orchestration.completed",
                      {"run_id": traj.run_id, "approved": approved, "completed": bool(approved),
                       "verification": None, "duration_ms": duration_ms})
        return {"run_id": traj.run_id, "mode": plan.mode, "agents": plan.agents,
                "results": results, "review": review_text, "approved": approved,
                "completed": bool(approved), "review_details": dict(review_data_seq),
                "iterations": iterations,
                "definition_of_done": plan.definition_of_done,
                "dependencies": plan.dependencies,
                "duration_ms": duration_ms, "trajectory": traj}
