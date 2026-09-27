"""Verification Loop: EDIT -> BUILD -> TEST -> LINT -> REVIEW (п.12).

Модель не говорит «Готово», пока AXIOM не проверил результат.
Планировщик верификации: build/test/lint команды + разбор итогов.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

CommandRunner = Callable[..., Awaitable[dict]]


@dataclass
class VerifyStep:
    name: str
    command: str
    ok: bool = False
    output: str = ""
    exit_code: int | None = None


@dataclass
class VerifyReport:
    ok: bool = False
    steps: list[VerifyStep] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        names = ", ".join(f"{s.name}:{'ok' if s.ok else 'fail'}" for s in self.steps)
        return f"verify {'PASSED' if self.ok else 'FAILED'} [{names}]"


def default_pipeline(kind: str = "python") -> list[VerifyStep]:
    if kind.startswith("node") or kind.startswith("js") or kind.startswith("ts"):
        return [VerifyStep("build", "npm run build"), VerifyStep("test", "npm test"),
                VerifyStep("lint", "npx tsc --noEmit")]
    if kind.startswith("rust"):
        return [VerifyStep("build", "cargo build"), VerifyStep("test", "cargo test"),
                VerifyStep("lint", "cargo check")]
    return [VerifyStep("build", "python -m compileall -q ."),
            VerifyStep("test", "pytest -q"), VerifyStep("lint", "ruff check .")]


class VerificationLoop:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner

    async def run(self, steps: list[VerifyStep] | None = None,
                  *, kind: str = "python") -> VerifyReport:
        pipeline = steps or default_pipeline(kind)
        report = VerifyReport()
        for step in pipeline:
            output = ""
            ok = False
            if self._runner is not None:
                try:
                    res = await self._runner(command=step.command, step=step.name)
                    exit_code = res.get("exit_code")
                    step.exit_code = exit_code if isinstance(exit_code, int) else None
                    ok = res.get("ok") is True and ("exit_code" not in res or exit_code == 0)
                    output = str(res.get("output") or res.get("content") or res.get("error") or "")
                    if "exit_code" in res and exit_code != 0:
                        output = f"exit code {exit_code}: {output}"
                except Exception as exc:
                    ok = False
                    output = f"{type(exc).__name__}: {exc}"
            step.ok = ok
            step.output = output[:4000]
            report.steps.append(step)
            if not ok:
                report.errors.append(f"{step.name} failed: {step.command}\n{output[:1000]}")
                report.ok = False
                return report
        report.ok = True
        return report
