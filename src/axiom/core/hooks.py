"""Lifecycle hooks around the agent loop (W4.10).

A hook is a real external command AXIOM runs at a named lifecycle point. Hooks
exist so a project can format, test, or audit without patching the agent:

``TaskStart`` / ``TaskComplete``   — once per task run;
``PreToolUse`` / ``PostToolUse``   — around every tool execution;
``PreEdit`` / ``PostEdit``         — around workspace-mutating file tools;
``PreCommit`` / ``PostCommit``     — around ``git_commit``;
``ContextCompact``                 — when the runtime compacts task context.

Three rules keep hooks from breaking the loop:

* **Sequential and bounded.** Hooks of one event run in declaration order, each
  under its own timeout. A hook never runs concurrently with another hook.
* **Fail-open.** A failing, timing-out, or missing hook is reported as a warning
  and the agent continues. Hooks are automation, not gates.
* **Permission-checked.** Every hook command is classified by the W4.9 command
  policy. Anything above ``HookRunner.max_risk`` is refused before it runs, so a
  project file can never smuggle in ``curl … | sh``.

Hook commands are argv lists, never shell strings: no shell is involved, so
hook arguments cannot inject extra commands.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from axiom.core.command_policy import RISK_TIERS, classify_command_risk
from axiom.core.config import axiom_home

#: Lifecycle points, in the order they occur around a task.
HOOK_EVENTS: tuple[str, ...] = (
    "TaskStart",
    "PreToolUse",
    "PreEdit",
    "PostEdit",
    "PostToolUse",
    "PreCommit",
    "PostCommit",
    "ContextCompact",
    "TaskComplete",
)

#: Tools that mutate workspace files — they trigger Pre/PostEdit.
EDIT_TOOLS = frozenset({
    "write_file", "edit_file", "apply_patch", "delete_file",
    "create_directory", "move_file", "copy_file",
})

#: Tools that create commits — they trigger Pre/PostCommit.
COMMIT_TOOLS = frozenset({"git_commit"})

#: Hook output kept per result; hooks must not flood Task State.
MAX_HOOK_OUTPUT = 2000

#: Hard ceiling for one hook, regardless of configuration.
MAX_HOOK_TIMEOUT = 600.0


def _tier_index(tier: str) -> int:
    try:
        return RISK_TIERS.index(tier)
    except ValueError:
        return len(RISK_TIERS) - 1


@dataclass(frozen=True)
class Hook:
    """One declared lifecycle action."""

    id: str
    event: str
    command: tuple[str, ...]
    tools: tuple[str, ...] = ()      # fnmatch patterns; empty = any tool
    paths: tuple[str, ...] = ()      # fnmatch patterns on the touched path
    timeout: float = 30.0
    enabled: bool = True
    source: str = "config"           # builtin | global | project | config
    description: str = ""

    def matches(self, event: str, *, tool: str = "", path: str = "") -> bool:
        """True when this hook applies to a concrete lifecycle occurrence."""
        if not self.enabled or self.event != event:
            return False
        if self.tools and not any(fnmatch(tool, pattern) for pattern in self.tools):
            return False
        if self.paths:
            candidate = (path or "").replace("\\", "/")
            if not candidate:
                return False
            name = candidate.rsplit("/", 1)[-1]
            if not any(fnmatch(candidate, pattern) or fnmatch(name, pattern)
                       for pattern in self.paths):
                return False
        return True

    def risk(self) -> tuple[str, str]:
        """Visible W4.9 risk tier and reason for this hook's command."""
        return classify_command_risk(" ".join(self.command))


@dataclass
class HookResult:
    """What actually happened when a hook ran."""

    hook_id: str
    event: str
    ok: bool
    source: str = "config"
    command: tuple[str, ...] = ()
    exit_code: int | None = None
    duration_ms: int = 0
    output: str = ""
    error: str = ""
    skipped: bool = False
    risk: str = ""
    tool: str = ""
    path: str = ""
    step_id: str = ""

    def to_json(self) -> dict:
        return {
            "hook_id": self.hook_id, "event": self.event, "ok": self.ok,
            "source": self.source, "command": list(self.command),
            "exit_code": self.exit_code, "duration_ms": self.duration_ms,
            "output": self.output, "error": self.error, "skipped": self.skipped,
            "risk": self.risk, "tool": self.tool, "path": self.path,
            "step_id": self.step_id,
        }


#: Ready-to-use definitions. They ship **disabled**: a hook runs real commands,
#: so enabling one is always an explicit user decision (config ``hooks``).
BUILTIN_HOOKS: tuple[Hook, ...] = (
    Hook(id="ruff-format-python", event="PostEdit",
         command=("ruff", "format"), paths=("*.py",), enabled=False,
         source="builtin", description="Format the edited Python file with Ruff."),
    Hook(id="ruff-check-python", event="PostEdit",
         command=("ruff", "check", "--quiet"), paths=("*.py",), enabled=False,
         source="builtin", description="Lint the edited Python file with Ruff."),
    Hook(id="pytest-on-task-complete", event="TaskComplete",
         command=("python", "-m", "pytest", "-q"), enabled=False, timeout=600.0,
         source="builtin", description="Run the test suite when a task completes."),
)


def _patterns(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        return tuple(part.strip() for part in raw.replace(";", ",").split(",") if part.strip())
    if isinstance(raw, (list, tuple)):
        return tuple(str(part).strip() for part in raw if str(part).strip())
    return ()


def _timeout(raw: object, default: float = 30.0) -> float:
    try:
        seconds = float(raw) if raw is not None else default
    except (TypeError, ValueError):
        seconds = default
    return min(max(0.5, seconds), MAX_HOOK_TIMEOUT)


def _parse_hook(raw: dict, *, source: str) -> Hook | None:
    """Build a :class:`Hook` from a mapping; ``None`` when it is unusable."""
    if not isinstance(raw, dict):
        return None
    event = str(raw.get("event") or "").strip()
    if event not in HOOK_EVENTS:
        return None
    command_raw = raw.get("command")
    if isinstance(command_raw, str):
        parts = tuple(part for part in command_raw.split() if part)
    elif isinstance(command_raw, (list, tuple)):
        parts = tuple(str(part) for part in command_raw if str(part).strip())
    else:
        parts = ()
    if not parts:
        return None
    hook_id = str(raw.get("id") or parts[0]).strip() or parts[0]
    return Hook(
        id=hook_id, event=event, command=parts,
        tools=_patterns(raw.get("tools")), paths=_patterns(raw.get("paths")),
        timeout=_timeout(raw.get("timeout")), enabled=bool(raw.get("enabled", True)),
        source=source, description=str(raw.get("description") or "")[:200],
    )


def _load_hook_directory(directory: Path, *, source: str) -> list[Hook]:
    """Load ``*.json`` hook definitions from one directory (sorted, stable)."""
    hooks: list[Hook] = []
    try:
        files = sorted(directory.glob("*.json"))
    except OSError:
        return hooks
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries = raw.get("hooks") if isinstance(raw, dict) else raw
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        for entry in entries:
            hook = _parse_hook(entry, source=source)
            if hook is not None:
                hooks.append(hook)
    return hooks


def load_hooks(config_hooks: list[dict] | None = None,
               workspace_root: Path | None = None) -> list[Hook]:
    """Merge builtin, global, project, and config hooks.

    Precedence is deterministic: builtin definitions come first and may be
    re-declared (same ``id``) by a global hook file, then by a project file in
    ``<workspace>/.axiom/hooks/``, and finally by the user config — so a config
    entry ``{"id": "ruff-format-python", "enabled": true}`` enables a builtin
    without repeating its command.
    """
    merged: dict[str, Hook] = {hook.id: hook for hook in BUILTIN_HOOKS}
    for hook in _load_hook_directory(axiom_home() / "hooks", source="global"):
        merged[hook.id] = hook
    if workspace_root is not None:
        for hook in _load_hook_directory(Path(workspace_root) / ".axiom" / "hooks",
                                         source="project"):
            merged[hook.id] = hook
    for raw in config_hooks or []:
        if not isinstance(raw, dict):
            continue
        hook_id = str(raw.get("id") or "").strip()
        existing = merged.get(hook_id) if hook_id else None
        if existing is not None and not raw.get("command"):
            # Enable/disable or retime an existing definition in place.
            merged[hook_id] = Hook(
                id=existing.id, event=str(raw.get("event") or existing.event),
                command=existing.command,
                tools=_patterns(raw.get("tools")) or existing.tools,
                paths=_patterns(raw.get("paths")) or existing.paths,
                timeout=_timeout(raw.get("timeout"), existing.timeout),
                enabled=bool(raw.get("enabled", existing.enabled)),
                source=existing.source, description=existing.description,
            )
            continue
        hook = _parse_hook(raw, source="config")
        if hook is not None:
            merged[hook.id] = hook
    order = {event: index for index, event in enumerate(HOOK_EVENTS)}
    return sorted(merged.values(), key=lambda h: (order.get(h.event, 99), h.id))


class HookRunner:
    """Runs matching hooks sequentially, bounded, and fail-open."""

    def __init__(self, hooks: list[Hook] | None = None, *, enabled: bool = True,
                 workspace_root: Path | None = None, bus: object | None = None,
                 trajectory: object | None = None, max_risk: str = "MEDIUM",
                 execute: Callable[[Hook, dict[str, str]], Awaitable[tuple[int, str]]] | None = None,
                 ) -> None:
        self.hooks = list(hooks or [])
        self.enabled = enabled
        self.workspace_root = Path(workspace_root).resolve() if workspace_root is not None else None
        self.bus = bus
        self.trajectory = trajectory
        self.max_risk = max_risk if max_risk in RISK_TIERS else "MEDIUM"
        #: Injection point for tests; production uses a real subprocess.
        self._execute = execute or self._run_process
        #: Results recorded since the last :meth:`drain`.
        self.results: list[HookResult] = []

    # ------------------------------------------------------------- reporting
    def _emit(self, kind: str, payload: dict) -> None:
        bus = self.bus
        if bus is not None and callable(getattr(bus, "emit", None)):
            try:
                bus.emit(kind, dict(payload))
            except Exception:
                pass
        trajectory = self.trajectory
        if trajectory is not None and callable(getattr(trajectory, "append", None)):
            try:
                trajectory.append(kind, str(payload.get("hook_id") or ""), data=dict(payload))
            except Exception:
                pass

    def matching(self, event: str, *, tool: str = "", path: str = "") -> list[Hook]:
        """Hooks that apply to one lifecycle occurrence, in declaration order."""
        if not self.enabled:
            return []
        return [hook for hook in self.hooks if hook.matches(event, tool=tool, path=path)]

    def has_hooks(self, event: str) -> bool:
        return bool(self.enabled and any(h.enabled and h.event == event for h in self.hooks))

    def drain(self) -> list[HookResult]:
        """Return and clear the results recorded since the last drain."""
        collected = self.results
        self.results = []
        return collected

    # --------------------------------------------------------------- running
    async def _run_process(self, hook: Hook, env: dict[str, str]) -> tuple[int, str]:
        """Execute a hook argv without a shell and capture merged output."""
        cwd = str(self.workspace_root) if self.workspace_root is not None else None
        process = await asyncio.create_subprocess_exec(
            *hook.command, cwd=cwd, env={**os.environ, **env},
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=hook.timeout)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await asyncio.gather(process.wait(), return_exceptions=True)
            raise
        return int(process.returncode or 0), (stdout or b"").decode("utf-8", errors="replace")

    def _hook_env(self, event: str, *, task_id: str, tool: str, path: str) -> dict[str, str]:
        env = {"AXIOM_HOOK_EVENT": event}
        if task_id:
            env["AXIOM_TASK_ID"] = task_id
        if tool:
            env["AXIOM_TOOL_NAME"] = tool
        if path:
            env["AXIOM_FILE_PATH"] = path
        if self.workspace_root is not None:
            env["AXIOM_WORKSPACE"] = str(self.workspace_root)
        return env

    def _resolved_command(self, hook: Hook, path: str) -> tuple[str, ...]:
        """Substitute or append the touched path for file-scoped hooks."""
        if not path:
            return hook.command
        if any("{path}" in part for part in hook.command):
            return tuple(part.replace("{path}", path) for part in hook.command)
        if hook.paths:
            return (*hook.command, path)
        return hook.command

    async def run_event(self, event: str, *, task_id: str = "", tool: str = "",
                        path: str = "", step_id: str = "") -> list[HookResult]:
        """Run every hook of ``event`` sequentially; never raises on hook failure."""
        results: list[HookResult] = []
        for hook in self.matching(event, tool=tool, path=path):
            tier, reason = hook.risk()
            command = self._resolved_command(hook, path)
            base = {"hook_id": hook.id, "event": event, "source": hook.source,
                    "command": list(command), "risk": tier, "tool": tool, "path": path,
                    "task_id": task_id, "step_id": step_id}
            if _tier_index(tier) > _tier_index(self.max_risk):
                result = HookResult(
                    hook_id=hook.id, event=event, ok=False, source=hook.source,
                    command=command, skipped=True, risk=tier, tool=tool, path=path,
                    step_id=step_id,
                    error=f"Refused: {tier} exceeds the allowed hook risk "
                          f"{self.max_risk} ({reason})",
                )
                self._emit("hook.failed", {**base, "error": result.error, "skipped": True})
                results.append(result)
                self.results.append(result)
                continue
            resolved = Hook(id=hook.id, event=hook.event, command=command, tools=hook.tools,
                            paths=hook.paths, timeout=hook.timeout, enabled=hook.enabled,
                            source=hook.source, description=hook.description)
            self._emit("hook.started", base)
            result = await self._execute_hook(resolved, event=event, task_id=task_id,
                                             tool=tool, path=path, step_id=step_id, risk=tier)
            # Fail-open: a failing hook is a warning, the agent loop continues.
            self._emit("hook.completed" if result.ok else "hook.failed",
                       {**base, "ok": result.ok, "exit_code": result.exit_code,
                        "duration_ms": result.duration_ms, "error": result.error})
            results.append(result)
            self.results.append(result)
        return results

    async def _execute_hook(self, hook: Hook, *, event: str, task_id: str,
                            tool: str, path: str, step_id: str, risk: str) -> HookResult:
        """Run one already-authorized hook and normalize every outcome."""
        started = time.perf_counter()
        common = {"hook_id": hook.id, "event": event, "source": hook.source,
                  "command": hook.command, "risk": risk, "tool": tool,
                  "path": path, "step_id": step_id}
        try:
            exit_code, output = await self._execute(
                hook, self._hook_env(event, task_id=task_id, tool=tool, path=path))
        except TimeoutError:
            return HookResult(
                **common, ok=False,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=f"Hook '{hook.id}' timed out after {hook.timeout:.0f}s",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return HookResult(
                **common, ok=False,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )
        return HookResult(
            **common, ok=exit_code == 0, exit_code=exit_code,
            duration_ms=int((time.perf_counter() - started) * 1000),
            output=(output or "")[-MAX_HOOK_OUTPUT:],
            error="" if exit_code == 0 else f"Hook '{hook.id}' exited with {exit_code}",
        )

    async def run_tool_hooks(self, phase: str, tool: str, arguments: dict | None = None, *,
                             task_id: str = "", step_id: str = "") -> list[HookResult]:
        """Run tool-lifecycle hooks for one tool call.

        ``phase`` is ``"pre"`` or ``"post"``. Edit and commit tools additionally
        trigger their specific events, so a formatter can bind to ``PostEdit``
        without reacting to every tool in the loop.
        """
        if phase not in {"pre", "post"}:
            raise ValueError("phase must be 'pre' or 'post'")
        events = [f"{'Pre' if phase == 'pre' else 'Post'}ToolUse"]
        if tool in EDIT_TOOLS:
            events.append("PreEdit" if phase == "pre" else "PostEdit")
        if tool in COMMIT_TOOLS:
            events.append("PreCommit" if phase == "pre" else "PostCommit")
        if phase == "post":
            events.reverse()  # specific events first, generic PostToolUse last
        results: list[HookResult] = []
        for event in events:
            for path in self._tool_paths(tool, arguments) or [""]:
                results.extend(await self.run_event(event, task_id=task_id, tool=tool,
                                                    path=path, step_id=step_id))
        return results

    @staticmethod
    def _tool_paths(tool: str, arguments: dict | None) -> list[str]:
        """Workspace paths a tool call touches (used for path-scoped hooks)."""
        keys = {
            "write_file": ("path",), "edit_file": ("path",), "apply_patch": ("path",),
            "delete_file": ("path",), "create_directory": ("path",),
            "move_file": ("source", "destination"), "copy_file": ("destination",),
        }.get(tool, ())
        out: list[str] = []
        for key in keys:
            raw = (arguments or {}).get(key)
            if raw and str(raw) not in out:
                out.append(str(raw))
        return out


def build_hook_runner(config: object, *, workspace_root: Path | None = None,
                      bus: object | None = None, trajectory: object | None = None,
                      ) -> HookRunner:
    """Create a runner from persisted configuration (disabled hooks run nothing)."""
    raw_hooks = getattr(config, "hooks", None)
    hooks = load_hooks(raw_hooks if isinstance(raw_hooks, list) else None,
                       workspace_root=workspace_root)
    return HookRunner(
        hooks, enabled=bool(getattr(config, "hooks_enabled", True)),
        workspace_root=workspace_root, bus=bus, trajectory=trajectory,
        max_risk=str(getattr(config, "hooks_max_risk", "MEDIUM")),
    )


__all__ = [
    "BUILTIN_HOOKS", "COMMIT_TOOLS", "EDIT_TOOLS", "HOOK_EVENTS", "MAX_HOOK_OUTPUT",
    "MAX_HOOK_TIMEOUT", "Hook", "HookResult", "HookRunner", "build_hook_runner",
    "load_hooks",
]
