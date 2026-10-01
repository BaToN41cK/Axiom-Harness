"""AXIOM desktop bridge: JSONL stdio between the Tauri shell (Rust) and the
real Python core (ChatSession — Ollama, streaming, tools, history).

  request: {"req": 1, "cmd": "send", "args": {...}}
  reply:   {"type": "reply", "req": 1, "ok": true, "data": ...}
  event:   {"type": "event", "event": {type: "reasoning"|"content"|...}}
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from itertools import count
from pathlib import Path

from axiom.core.chat import ChatSession
from axiom.core.config import Config
from axiom.core.e2e_model import install_scripted_model
from axiom.core.events import ChatEvent
from axiom.core.models import ModelInfo
from axiom.core.search.multi import search_provider_choices

OUT_LOCK = threading.Lock()


def _external_capabilities(name: str) -> list[str]:
    """Capabilities advertised by external chat providers.

    External APIs do not expose Ollama's ``/api/tags`` capability list.  The
    OpenAI-compatible and Anthropic adapters both support function/tool calls;
    infer only the optional reasoning marker from the model name.
    """
    lowered = (name or "").lower()
    capabilities = ["tools"]
    if any(marker in lowered for marker in ("reason", "r1", "think", "pro", "opus")):
        capabilities.append("thinking")
    return capabilities


def _model_json(m, loaded: bool = False, provider_id: str = "ollama", source: str = "ollama") -> dict:
    return {
        "name": m.name,
        "displayName": m.display_name,
        "sizeGb": m.size_gb,
        "sizeBytes": m.size,
        "parameterSize": m.parameter_size,
        "quantization": m.quantization,
        "family": m.family,
        "capabilities": m.capabilities,
        "contextLength": m.context_length,
        "numCtx": m.num_ctx,
        "loaded": loaded,
        "providerId": provider_id,
        "source": source,
    }


def _artifact_workspace(session: ChatSession):
    """Return the ArtifactWorkspace for the current workspace (or raise)."""
    from axiom.core.artifact_workspace import ArtifactWorkspace

    root = session.workspace_root
    if root is None:
        raise ValueError("No project is open")
    return ArtifactWorkspace(root)


def document_meta(document) -> dict:
    """A compact list row (no full content) for the Documents view."""
    return {
        "id": document.id,
        "title": document.title,
        "kind": document.kind,
        "version": document.version,
        "updated_at": document.updated_at,
        "task_id": document.task_id,
    }


async def _models_json(session: ChatSession) -> list[dict]:
    """Return local Ollama models plus the configured external route.

    Ollama may be completely absent in an API-only desktop session. Model
    discovery must therefore be best-effort and must not turn the provider
    picker into a startup error.
    """
    try:
        models = await session.refresh_models()
        loaded = await session.registry.running_names()
    except Exception:
        models, loaded = [], set()
    rows = [_model_json(m, loaded=m.name in loaded) for m in models]
    target = session.router.config.primary
    if target is not None and target.provider_id != "ollama" and target.model:
        rows.append({
            "name": target.model, "displayName": target.model, "sizeGb": 0,
            "sizeBytes": 0, "parameterSize": "", "quantization": "", "family": "",
            "capabilities": _external_capabilities(target.model), "contextLength": None,
            "numCtx": None, "loaded": False, "providerId": target.provider_id,
            "source": "external",
        })
    return rows


def _conversation_summary(c) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "model": c.model,
        "createdAt": c.created_at,
        "updatedAt": c.updated_at,
        "messageCount": len(c.messages),
        "pinned": c.pinned,
        "folder": c.folder,
    }


def _conversation_full(c) -> dict:
    data = _conversation_summary(c)
    data["messages"] = [
        {
            "role": m.role,
            "content": m.content,
            "thinking": m.thinking,
            "name": m.name,
            "images": list(m.images or []),
            "artifacts": list(m.artifacts or []),
        }
        for m in c.messages
    ]
    return data


def _event_json(e: ChatEvent) -> dict:
    from axiom.core.events import (
        ContentChunk,
        Done,
        ErrorEvent,
        ReasoningChunk,
        SearchResultEvent,
        StatusChange,
        ToolCallEvent,
        ToolResultEvent,
    )

    if isinstance(e, (ReasoningChunk, ContentChunk)):
        return {"type": e.type, "text": e.text}
    if isinstance(e, ToolCallEvent):
        return {"type": e.type, "name": e.name, "arguments": e.arguments}
    if isinstance(e, ToolResultEvent):
        return {
            "type": e.type,
            "name": e.name,
            "ok": e.ok,
            "content": e.content,
            "error": e.error,
            "durationMs": e.duration_ms,
            "data": e.data,
        }
    if isinstance(e, SearchResultEvent):
        return {
            "type": e.type,
            "query": e.query,
            "sources": [
                {"index": s.index, "title": s.title, "url": s.url, "snippet": s.snippet}
                for s in e.sources
            ],
        }
    if isinstance(e, StatusChange):
        return {"type": e.type, "state": e.state.value, "detail": e.detail}
    if isinstance(e, ErrorEvent):
        return {"type": e.type, "message": e.message, "kind": e.kind, "hint": e.hint}
    if isinstance(e, Done):
        return {
            "type": e.type,
            "state": e.state.value,
            "durationMs": e.duration_ms,
            "tokensOut": e.tokens_out,
            "tokensIn": e.tokens_in,
            "tokensPerSecond": e.tokens_per_second,
            "ttftMs": e.ttft_ms,
            "loadMs": e.load_ms,
            "stopReason": e.stop_reason,
        }
    return {"type": type(e).__name__}


def _write_line(line: str) -> None:
    with OUT_LOCK:
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            # The UI may reconnect while a detached task is still running.
            pass


# --------------------------------------------------------------- W2.4 permissions
#: ASK tool calls that wait for a real answer from the shell.
_PERMISSION_FUTURES: dict[str, asyncio.Future] = {}
_PERMISSION_SEQ = count(1)


def _permission_payload(session: ChatSession, tool_name: str, arguments: dict) -> dict:
    """UI projection of an ASK tool call: tool, arguments, cwd, risk (W4.9).

    The real risk tier comes from ``PermissionManager.describe_request``
    (SAFE..CRITICAL command policy); the registry ``risk`` stays only as a
    fallback so a missing registry still yields a safe payload.
    """
    from axiom.core.tools.base import RISK_SAFE

    definition = None
    tools = getattr(session, "tools", None)
    if tools is not None:
        try:
            definition = tools.get(tool_name)
        except Exception:
            definition = None
    permissions = getattr(session, "permissions", None)
    describe = getattr(permissions, "describe_request", None)
    cwd = getattr(getattr(session, "config", None), "workspace_root", None) or "."
    if callable(describe):
        try:
            detail = describe(tool_name, dict(arguments or {}), cwd=str(cwd))
        except Exception:
            detail = None
        if isinstance(detail, dict):
            payload = {
                "type": "permission_request",
                "tool": tool_name,
                "arguments": dict(arguments or {}),
                "command": detail.get("command", ""),
                "cwd": str(detail.get("cwd", cwd)),
                "risk": detail.get("risk", getattr(definition, "risk", RISK_SAFE)),
                "reason": detail.get("reason", ""),
                "autonomy": detail.get("autonomy", "auto"),
            }
            active_task = getattr(session, "active_task", None)
            if active_task is not None:
                payload["task_id"] = active_task.id
            return payload
    payload = {
        "type": "permission_request",
        "tool": tool_name,
        "arguments": dict(arguments or {}),
        "command": "",
        "cwd": str(cwd),
        "risk": getattr(definition, "risk", RISK_SAFE),
        "reason": "",
        "autonomy": "auto",
    }
    active_task = getattr(session, "active_task", None)
    if active_task is not None:
        payload["task_id"] = active_task.id
    return payload


async def _ask_permission(session: ChatSession, tool_name: str, arguments: dict) -> str:
    """Forward an ASK tool call to the shell and wait for its real answer.

    Emits one ``permission_request`` event and suspends the tool call until
    ``permission_respond`` arrives with ``allow_once`` / ``allow_task`` /
    ``allow_project`` / ``allow_always`` / ``deny``. The pending future lives
    exactly as long as the request.
    """
    request_id = f"perm-{next(_PERMISSION_SEQ)}"
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    _PERMISSION_FUTURES[request_id] = future
    payload = _permission_payload(session, tool_name, arguments)
    payload["id"] = request_id
    active_task = getattr(session, "active_task", None)
    runner = getattr(session, "active_task_runner", None)
    if active_task is not None and runner is not None:
        runner.permission_requested(active_task, tool_name, arguments)
    _write_line(json.dumps({"type": "event", "event": payload}, ensure_ascii=False))
    try:
        return await future
    finally:
        _PERMISSION_FUTURES.pop(request_id, None)
        if active_task is not None and runner is not None:
            runner.permission_resolved(active_task)


def _resolve_permission(request_id: str, decision: str) -> bool:
    """Deliver the user's answer to the waiting tool call."""
    future = _PERMISSION_FUTURES.get(request_id)
    if future is None or future.done():
        return False
    future.set_result(decision)
    return True


def _active_provider_id(session: ChatSession) -> str:
    primary = session.router.config.primary
    return primary.provider_id if primary is not None else "ollama"


def _active_model_json(session: ChatSession) -> dict | None:
    if session.active_model is None:
        return None
    provider_id = _active_provider_id(session)
    return _model_json(
        session.active_model,
        provider_id=provider_id,
        source="ollama" if provider_id == "ollama" else "external",
    )


async def _state_json(session: ChatSession) -> dict:
    return {
        "state": session.state.value if session.state else "idle",
        "model": session.active_model.name if session.active_model else None,
        "lastMetrics": session.last_metrics or {},
    }


async def _stream_turn(session: ChatSession, events) -> dict:
    """Stream a real generation cycle to the shell, then report the final state."""
    async for event in events:
        line = json.dumps({"type": "event", "event": _event_json(event)}, ensure_ascii=False)
        await asyncio.get_running_loop().run_in_executor(None, _write_line, line)
    return {
        "state": session.state.value,
        "lastMetrics": session.last_metrics or {},
        "conversation": _conversation_summary(session.conversation),
        "activeModel": _active_model_json(session),
    }


#: Trajectory kinds that mean real /orchestrate progress for the UI.
_ORCHESTRATION_PROGRESS = frozenset({
    "orchestration.command",
    "orchestrator.plan",
    "agent.start",
    "agent.done",
    "agent.failed",
    "subagent.model",
    "subagent.reasoning",
    "subagent.answer",
    "subagent.tool.call",
    "subagent.tool.result",
    "orchestrator.review",
    "verification.completed",
    "orchestrator.done",
    "orchestration.cancelled",
    "orchestration.failed",
})


def _progress_events(timeline: list[dict], baseline: int = 0) -> list[dict]:
    """Map new trajectory entries to plain-JSON ``orchestration`` bridge events.

    ``baseline`` skips everything recorded before this orchestration run, so a
    long-lived session never replays old steps into the current request.
    """
    events: list[dict] = []
    for entry in list(timeline)[max(0, int(baseline)):]:
        kind = str(entry.get("kind") or "")
        if kind not in _ORCHESTRATION_PROGRESS:
            continue
        events.append({
            "type": "orchestration",
            "kind": kind,
            "actor": str(entry.get("actor") or ""),
            "summary": str(entry.get("summary") or ""),
            "seq": int(entry.get("seq") or 0),
        })
    return events


async def _watch_orchestration(session: ChatSession, baseline: int,
                               stop: asyncio.Event) -> None:
    """Stream live /orchestrate progress to the shell until the run finishes.

    The reply of the ``orchestrate`` command arrives only at the very end; a
    local model easily needs several minutes for four workers plus review.
    Workers record their real steps (plan, start/done, tool calls, review,
    verification) into the session trajectory as they happen, so polling it is
    the honest live feed — without it the UI sits on «Подключается…» forever.
    """
    seen = max(0, int(baseline))
    while True:
        try:
            timeline = session.trajectory.timeline()
        except Exception:
            timeline = []
        for payload in _progress_events(timeline, seen):
            line = json.dumps({"type": "event", "event": payload}, ensure_ascii=False)
            await asyncio.get_running_loop().run_in_executor(None, _write_line, line)
        seen = max(seen, len(timeline))
        if stop.is_set():
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.6)
        except TimeoutError:
            pass


async def _plugin_capability(session: ChatSession, request) -> dict:
    """Execute a validated plugin capability request (W3.1).

    The scope gate has already allowed this method; each handler is bounded and
    never raises out of the bridge — a plugin can only ever receive a structured
    ``{ok, data, error}`` reply.
    """
    method = request.method
    params = request.params or {}
    result: dict = {"id": request.id, "plugin": request.plugin, "ok": True, "data": None, "error": None}
    try:
        if method in {"ui.render", "ui.command", "ui.event"}:
            result["data"] = {"ack": True}
        elif method in {"clipboard.read", "clipboard.write"}:
            result["ok"] = False
            result["error"] = "clipboard is not available in the core bridge"
        elif method in {"net.http_get", "net.http_post"}:
            import httpx

            url = str(params.get("url") or "").strip()
            if not url:
                result["ok"] = False
                result["error"] = "url is required"
            else:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                    if method == "net.http_get":
                        response = await client.get(url)
                    else:
                        response = await client.post(url, json=params.get("json"), data=params.get("data"))
                result["data"] = {"status": response.status_code, "body": response.text[:4000]}
        elif method == "fs.read":
            root = session.workspace_root
            if root is None:
                result["ok"] = False
                result["error"] = "no project is open"
            else:
                target = _workspace_path(root, params)
                if target is None:
                    result["ok"] = False
                    result["error"] = "path is outside the workspace"
                else:
                    result["data"] = {"content": target.read_text(encoding="utf-8", errors="replace")[:20000]}
        elif method == "fs.list":
            root = session.workspace_root
            if root is None:
                result["ok"] = False
                result["error"] = "no project is open"
            else:
                target = _workspace_path(root, params) or root
                result["data"] = {"entries": sorted(
                    p.relative_to(root).as_posix() for p in target.iterdir())}
        elif method == "fs.write":
            root = session.workspace_root
            if root is None:
                result["ok"] = False
                result["error"] = "no project is open"
            else:
                target = _workspace_path(root, params)
                if target is None:
                    result["ok"] = False
                    result["error"] = "path is outside the workspace"
                else:
                    content = str(params.get("content") or "")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content[:20000], encoding="utf-8")
                    result["data"] = {"path": target.relative_to(root).as_posix()}
        else:
            result["ok"] = False
            result["error"] = f"capability '{method}' is not available"
    except Exception as exc:  # a capability must never crash the bridge
        result["ok"] = False
        result["data"] = None
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _workspace_path(root: Path, params: dict) -> Path | None:
    """Resolve a plugin fs path inside ``root``; ``None`` if it escapes."""
    rel = str(params.get("path") or "").replace("\\", "/")
    if not rel or rel.startswith("/") or ":" in rel:
        return None
    target = (root / rel).resolve()
    if target != root.resolve() and root.resolve() not in target.parents:
        return None
    return target


async def _handle(session: ChatSession, cmd: str, args: dict) -> object:
    if cmd in {"set_workspace", "clear_workspace"}:
        # A workspace belongs to the whole ChatSession. Switching it during a
        # response would let that response continue with a different project
        # root and history store. Keep this invariant at the protocol boundary
        # as well as in the GUI, since other IPC clients can call the bridge.
        if session.busy:
            raise ValueError("Stop the active generation before switching workspace")
        if cmd == "set_workspace":
            target = Path(str(args.get("path") or "")).expanduser()
            if not target.is_dir():
                # Preserve the current terminal session when the requested
                # workspace is invalid and the core will reject the switch.
                raise ValueError(f"Not a directory: {target.resolve()}")
        shell = getattr(session, "gui_shell", None)
        if shell is not None:
            shell.stop()
            session.gui_shell = None
    if cmd in {"task_start", "task_resume", "task_launch", "task_continue"}:
        # Push directly from the core bus; no polling, model calls or state
        # transitions in the frontend. The subscription is request-scoped.
        def forward(payload: dict) -> None:
            _write_line(json.dumps({"type": "event", "event": payload}, ensure_ascii=False))

        detached = cmd in {"task_launch", "task_continue"}
        # W3.3: background (detached) tasks may run concurrently with the chat
        # and with each other; only a foreground task launch needs the single
        # in-line generation slot to be free.
        if not detached and session.busy:
            raise ValueError("A generation is already running")
        # Detached tasks use the bridge-wide subscription installed in _run;
        # a request's lifetime must not own the task's event stream.
        off = None if detached else session.bus.subscribe("task.event", forward)
        try:
            if cmd in {"task_start", "task_launch"}:
                task = await session.task_start(
                    str(args.get("goal") or ""),
                    planning=args.get("planning"),
                    plan=args.get("plan"),
                    detached=detached,
                )
            else:
                task = await session.task_resume(str(args.get("id") or ""),
                                                 acknowledge=args.get("acknowledge") is True,
                                                 detached=detached)
            return task.model_dump(mode="json")
        finally:
            if off:
                off()
    if cmd == "task_plan":
        plan = await session.task_plan(str(args.get("goal") or ""))
        return plan.model_dump(mode="json")
    if cmd == "task_create":
        task = session.task_create(
            str(args.get("goal") or ""),
            plan=args.get("plan"),
        )
        return task.model_dump(mode="json")
    if cmd == "task_save":
        task = session.task_save(
            str(args.get("id") or ""),
            goal=args.get("goal"),
            plan=args.get("plan"),
            state=args.get("state"),
        )
        return task.model_dump(mode="json") if task is not None else None
    if cmd == "task_delete":
        return {"deleted": session.task_delete(str(args.get("id") or ""))}
    if cmd == "task_review":
        task = session.task_review(str(args.get("id") or ""), str(args.get("decision") or ""))
        return task.model_dump(mode="json")
    if cmd == "task_recover_review":
        task = session.task_recover_review(str(args.get("id") or ""))
        return task.model_dump(mode="json")
    if cmd == "task_cancel":
        return {"cancelled": session.task_cancel(str(args.get("id") or ""))}
    if cmd == "task_state":
        task = session.task_state(str(args.get("id") or ""))
        return task.model_dump(mode="json") if task is not None else None
    if cmd == "tasks":
        return [task.model_dump(mode="json") for task in session.task_store.list()]
    if cmd == "running_tasks":
        # W3.3: ids of tasks executing right now, for an honest active-task
        # count in the UI (tray/sidebar/completion toasts).
        return session.running_task_ids()
    if cmd == "health":
        available = await session.client.is_available()
        version = None
        if available:
            try:
                version = await session.client.version()
            except Exception:
                version = None
        return {"available": available, "version": version, "url": session.client.base_url}
    if cmd == "status":
        state = await _state_json(session)
        available = await session.client.is_available()
        version = None
        if available:
            try:
                version = await session.client.version()
            except Exception:
                # A transient Ollama failure must not hide an active external route.
                available = False
        return {
            **state,
            "ollamaUrl": session.client.base_url,
            "version": version,
            "activeModel": _active_model_json(session),
            "historyCount": len(session.history()),
            "configPath": str(type(session.config).path()),
            "busy": session.busy,
        }
    if cmd == "tools":
        return session.tools_info()
    if cmd == "list_plugins":
        return [m.row() for m in session.plugins.list()]
    if cmd == "bundled_plugins":
        return [m.row() for m in session.plugin_manager.bundled_manifests()]
    if cmd == "install_bundled_plugin":
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        return session.install_bundled_plugin(name)
    if cmd == "discover_plugins":
        # Live reload: pick up folders the user copied into ~/.axiom/plugins
        # while the app was running, register enabled plugins' real tools/skills,
        # and report which names are new so the UI can announce them.
        before = {m.name for m in session.plugins.list()}
        session.load_plugins()
        rows = [m.row() for m in session.plugins.list()]
        discovered = [row["name"] for row in rows if row["name"] not in before]
        return {"discovered": discovered, "plugins": rows}
    if cmd == "install_plugin":
        path = str(args.get("path") or "").strip()
        if not path:
            raise ValueError("path is required")
        return session.install_plugin_from_folder(path)
    if cmd == "toggle_plugin":
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        return session.toggle_plugin(name, bool(args.get("enabled", True)))
    if cmd == "remove_plugin":
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        return {"name": name, "removed": session.remove_plugin(name)}
    if cmd == "plugin_host":
        # W3.1: the typed UI host gate. The desktop iframe/Worker forwards a
        # validated request here; ScopeGate enforces least privilege against the
        # plugin's declared scopes *before* any capability handler runs.
        from axiom.core.plugin_host import ScopeGate, parse_request

        raw = {
            "id": str(args.get("id") or "1"),
            "plugin": str(args.get("plugin") or ""),
            "method": str(args.get("method") or ""),
            "params": args.get("params") if isinstance(args.get("params"), dict) else {},
        }
        request = parse_request(raw)
        if isinstance(request, str):
            return {"id": raw["id"], "plugin": raw["plugin"], "ok": False, "error": request}
        manifest = session.plugins.get(request.plugin) if request.plugin else None
        scopes: frozenset[str] = frozenset()
        if manifest is not None and manifest.ui_block is not None:
            scopes = frozenset(manifest.ui_block.scopes)
        if ScopeGate(declared=scopes).denied(request.method):
            return {"id": request.id, "plugin": request.plugin, "ok": False,
                    "error": f"scope not granted for '{request.method}'"}
        return await _plugin_capability(session, request)
    if cmd == "plugin_commands":
        # W3.1: the ``command`` extensions declared by enabled plugins, so the
        # palette can surface them without any host hardcoding.
        commands = []
        for manifest in session.plugins.list(enabled_only=True):
            if manifest.ui_block is None:
                continue
            for extension in manifest.ui_block.extensions:
                if extension.type != "command":
                    continue
                commands.append({
                    "plugin": manifest.name,
                    "id": extension.id,
                    "title": str((extension.meta or {}).get("title") or extension.id),
                })
        return commands
    if cmd == "plugin_ui_html":
        # W3.1: the plugin's own UI document, served into a sandboxed iframe.
        # Only an installed plugin with a ``ui/index.html`` has one; the host
        # renders a declarative fallback otherwise.
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        manifest = session.plugins.get(name)
        if manifest is None or not manifest.source_dir:
            return {"html": None}
        ui_html = Path(manifest.source_dir) / "ui" / "index.html"
        if not ui_html.exists():
            return {"html": None}
        return {"html": ui_html.read_text(encoding="utf-8")[:100_000]}
    if cmd == "model_info":
        provider_id = str(args.get("provider_id") or args.get("providerId") or "ollama")
        target = str(args.get("name") or "")
        if provider_id != "ollama":
            active = session.active_model
            if active is not None and active.name == target:
                return _active_model_json(session)
            return None
        detail = await session.model_detail(target or None)
        return _model_json(detail) if detail else None
    if cmd == "startup":
        report = await session.startup()
        models = report.models or []
        loaded: set[str] = set()
        if report.ollama_available:
            loaded = await session.registry.running_names()
        # Fire the background model warm-up once boot selects a model; the
        # splash screen is not delayed by it (fire-and-forget task).
        if report.ollama_available and report.selected is not None and session.config.warmup_model:
            session.core_warmup_task = asyncio.create_task(
                session.warmup_model(report.selected.name)
            )
        return {
            "available": report.ollama_available,
            "version": report.version,
            "error": report.error,
            "hint": report.hint,
            "models": [_model_json(m, loaded=m.name in loaded) for m in models],
            "selected": _model_json(report.selected) if report.selected else None,
            "state": await _state_json(session),
        }
    if cmd == "reconnect":
        report = await session.reconnect(args.get("url"))
        loaded = await session.registry.running_names() if report.ollama_available else set()
        return {
            "available": report.ollama_available,
            "version": report.version,
            "error": report.error,
            "hint": report.hint,
            "models": [_model_json(m, loaded=m.name in loaded) for m in (report.models or [])],
            "selected": _model_json(report.selected) if report.selected else None,
            "state": await _state_json(session),
        }
    if cmd == "models":
        return await _models_json(session)
    if cmd == "providers":
        return session.provider_manager.status_rows()
    if cmd == "provider_test":
        return await session.provider_manager.test_provider(str(args["provider_id"]))
    if cmd == "provider_set_key":
        session.provider_manager.set_key(str(args["provider_id"]), str(args.get("api_key") or ""))
        return {"configured": True}
    if cmd == "provider_set_base_url":
        provider_id = str(args["provider_id"])
        base_url = str(args.get("base_url") or "").strip()
        if not base_url:
            raise ValueError("Base URL is required")
        session.provider_manager.set_provider(provider_id, base_url=base_url)
        return {"provider_id": provider_id, "base_url": base_url}
    if cmd == "provider_discover":
        return await session.provider_manager.model_rows(str(args["provider_id"]))
    if cmd == "provider_pick_model":
        provider_id, model = str(args["provider_id"]), str(args["model"])
        session.config.router_primary = {"provider_id": provider_id, "model": model}
        session.config.save()
        session._configure_router_from_config()
        return {"provider_id": provider_id, "model": model}
    if cmd == "search_providers":
        return search_provider_choices()
    if cmd == "search_test":
        return await session.search_test(
            str(args.get("query") or ""),
            limit=int(args["limit"]) if args.get("limit") else None,
        )
    if cmd == "memory_list":
        # W2.1: the Desktop memory manager reads the same projection as TUI.
        return session.memory_rows()
    if cmd == "memory_add":
        item_id = session.memory_write_for_user(
            str(args.get("content") or ""),
            category=str(args.get("category") or "normal"),
            scope=str(args.get("scope") or "global"),
            tags=[str(t) for t in (args.get("tags") or [])],
        )
        if item_id is None:
            raise ValueError("Memory item was rejected (empty, too long or banned)")
        return {"id": item_id}
    if cmd == "memory_edit":
        ok = session.memory_edit(
            str(args.get("id") or ""), str(args.get("content") or "")
        )
        if not ok:
            raise ValueError("Memory item not found or edit rejected")
        return {"id": str(args.get("id") or ""), "edited": True}
    if cmd == "memory_delete":
        removed = session.memory_forget(str(args.get("id") or ""))
        return {"id": str(args.get("id") or ""), "removed": removed}
    if cmd == "knowledge_list":
        # W2.2: collection status rows (files/chunks/embedding status).
        return session.knowledge_rows()
    if cmd == "knowledge_add":
        result = await session.knowledge_add_collection(
            str(args.get("name") or ""), str(args.get("path") or "")
        )
        if not result.get("ok"):
            raise ValueError(str(result.get("error") or "knowledge add failed"))
        return result
    if cmd == "knowledge_remove":
        removed = session.knowledge_remove_collection(str(args.get("name") or ""))
        return {"name": str(args.get("name") or ""), "removed": removed}
    if cmd == "knowledge_reindex":
        result = await session.knowledge_reindex(str(args.get("name") or ""))
        if not result.get("ok"):
            raise ValueError(str(result.get("error") or "knowledge reindex failed"))
        return result
    if cmd == "knowledge_search":
        return await session.knowledge_search_rows(
            str(args.get("query") or ""),
            limit=int(args["limit"]) if args.get("limit") else 5,
        )
    if cmd == "knowledge_embed_model":
        model = str(args.get("model") or "").strip() or None
        session.knowledge.configure_embedder(session.config.ollama_url, model)
        session.config.knowledge_embed_model = model
        session.config.save()
        return {"model": model}
    if cmd == "permissions":
        mode = str(args.get("mode") or "ask")
        if mode in {"plan", "edit", "auto", "full"}:
            # W4.9 autonomy preset: composes both persisted axes at once.
            applied = session.permissions.set_autonomy(mode)
            try:
                session.sandbox.apply_preset(
                    {"plan": "readonly", "edit": "workspace",
                     "auto": "workspace", "full": "full"}.get(applied, "workspace")
                )
            except Exception:
                pass
            return {"mode": session.permissions.mode.value, "autonomy": applied,
                    "access_mode": session.config.access_mode}
        if mode not in {"ask", "auto_approve_safe", "auto_approve_all"}:
            raise ValueError("Unknown permission mode")
        session.permissions.mode = type(session.permissions.mode)(mode)
        session.config.permission_mode = mode
        try:
            session.config.autonomy_mode = session.permissions.autonomy
        except Exception:
            pass
        session.config.save()
        return {"mode": mode, "autonomy": session.permissions.autonomy,
                "access_mode": session.config.access_mode}
    if cmd == "permission_respond":
        # W2.4+W4.9: the real answer to a waiting ASK tool call (allow once /
        # task / project / always / deny). Unknown answers fail closed in the
        # PermissionManager; stale ids just report ``resolved: False``.
        return {
            "resolved": _resolve_permission(
                str(args.get("id") or ""), str(args.get("decision") or "")
            )
        }
    if cmd == "profiles":
        return {"active": session.profiles.active_name, "items": [
            {"id": name, "name": name, "prompt": prompt}
            for name, prompt in session.profiles.all.items()
        ]}
    if cmd == "trajectory":
        return session.trajectory.viewer()
    if cmd == "trajectory_export":
        return {"run_id": session.trajectory.run_id,
                "markdown": session.trajectory.export_markdown()}
    if cmd == "orchestrate_resume":
        return await session.resume_orchestrated(
            str(args.get("run_id") or ""),
            limit=int(args.get("limit") or 4),
            max_iterations=int(args.get("max_iterations") or 3),
        )
    if cmd == "orchestrate":
        # Live progress: forward the real trajectory steps while the workers
        # run; the reply below arrives only minutes later with the full report.
        try:
            baseline = len(session.trajectory.timeline())
        except Exception:
            baseline = 0
        stop = asyncio.Event()
        watcher = asyncio.create_task(_watch_orchestration(session, baseline, stop))
        try:
            result = await session.run_orchestrated(
                str(args.get("text") or ""),
                limit=int(args.get("limit") or 4),
                max_iterations=int(args.get("max_iterations") or 3),
            )
        finally:
            stop.set()
            try:
                await watcher
            except Exception:
                pass
        # The orchestration trajectory is a live Python object; the JSONL
        # bridge protocol can only transport plain JSON, so expose the
        # viewer/timeline representation instead of the raw object.
        trajectory = result.pop("trajectory", None)
        try:
            result["trajectory"] = trajectory.viewer() if trajectory is not None else None
        except Exception:
            result["trajectory"] = None
        return result
    if cmd == "agents":
        return [{"id": a.id, "label": a.label, "provider_id": a.provider_id,
                 "model": a.model, "tools": a.tools} for a in session.agent_registry.all()]
    if cmd == "send":
        return await _stream_turn(
            session,
            session.send(
                args.get("text", ""),
                force_search=bool(args.get("forceSearch", False)),
                search_query=args.get("searchQuery"),
                images=[str(img) for img in (args.get("images") or []) if img],
            ),
        )
    if cmd == "regenerate":
        return await _stream_turn(
            session,
            session.regenerate(force_search=bool(args.get("forceSearch", False))),
        )
    if cmd == "edit_message":
        return await _stream_turn(
            session,
            session.edit_last_user(
                args.get("text", ""),
                force_search=bool(args.get("forceSearch", False)),
            ),
        )
    if cmd == "continue_last":
        return await _stream_turn(
            session,
            session.continue_last(force_search=bool(args.get("forceSearch", False))),
        )
    if cmd == "cancel":
        return {"cancelled": session.cancel()}
    if cmd == "new_chat":
        return _conversation_full(session.new_conversation())
    if cmd == "load_chat":
        conv = session.load_conversation(args["id"])
        return _conversation_full(conv) if conv else None
    if cmd == "delete_chat":
        return {"deleted": session.delete_conversation(args["id"])}
    if cmd == "rename_chat":
        return {"renamed": session.rename_conversation(args["id"], args.get("title", ""))}
    if cmd == "list_chats":
        return [_conversation_summary(c) for c in session.history()]
    if cmd == "workspace_info":
        info = session.workspace_info()
        # Return only current workspace during boot (no recent workspaces to avoid git hangs)
        return {"current": info.to_json() if info else None}
    if cmd == "recent_workspaces":
        info = session.workspace_info()
        return {"current": info.to_json() if info else None,
                "recent": [p.to_json() for p in session.recent_workspaces()]}
    if cmd == "pinned_workspaces":
        info = session.workspace_info()
        return {"current": info.to_json() if info else None,
                "pinned": [p.to_json() for p in session.pinned_workspaces()]}
    if cmd == "set_workspace":
        info = session.set_workspace(args["path"])
        return info.to_json()
    if cmd == "clear_workspace":
        session.clear_workspace()
        return {"current": None}
    if cmd == "remove_workspace":
        return {"removed": session.remove_workspace(args["path"])}
    if cmd == "pin_workspace":
        return {"pinned": session.pin_workspace(args["path"])}
    if cmd == "unpin_workspace":
        return {"pinned": session.unpin_workspace(args["path"])}
    if cmd == "is_pinned":
        return {"pinned": session.is_workspace_pinned(args["path"])}
    if cmd == "search_projects":
        results = session.search_projects(args.get("query", ""))
        return {"matches": [i.to_json() for i in results], "total": len(results)}
    if cmd == "create_project":
        info = session.create_project(args["path"])
        return info.to_json()
    if cmd == "run_terminal":
        return await session.run_terminal(
            args.get("command", ""), confirmed=bool(args.get("confirmed", False)),
        )
    if cmd == "workspace_tree":
        root = session.workspace_root
        if root is None or not root.exists():
            return {"tree": [], "root": None}
        from axiom.core.tools.filesystem import IGNORED_DIRS

        def _tree(path, depth: int, prefix: str = "") -> list[dict]:
            if depth <= 0:
                return []
            try:
                entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except OSError:
                return []
            out: list[dict] = []
            for entry in entries:
                if entry.name.startswith(".") and entry.name not in (".vscode",):
                    continue
                if entry.is_dir() and entry.name in IGNORED_DIRS:
                    continue
                node: dict = {"name": entry.name, "dir": entry.is_dir(), "path": str(entry.relative_to(root))}
                if entry.is_dir() and depth > 1:
                    node["children"] = _tree(entry, depth - 1)
                out.append(node)
                if len(out) >= 800:
                    break
            return out

        depth = max(1, min(int(args.get("depth", 3) or 3), 5))
        return {"tree": _tree(root, depth), "root": str(root)}
    if cmd == "workspace_files":
        root = session.workspace_root
        if root is None:
            return {"files": []}
        from axiom.core.tools.filesystem import IGNORED_DIRS

        files: list[str] = []
        try:
            for path in sorted(root.rglob("*"), key=lambda p: p.as_posix().lower()):
                if not path.is_file():
                    continue
                rel_parts = path.relative_to(root).parts
                if any(part.startswith(".") or part in IGNORED_DIRS for part in rel_parts[:-1]):
                    continue
                files.append(path.relative_to(root).as_posix())
                if len(files) >= 5000:
                    break
        except OSError:
            return {"files": [], "error": "Не удалось прочитать список файлов"}
        return {"files": files}
    if cmd == "workspace_file":
        root = session.workspace_root
        if root is None:
            return {"ok": False, "error": "No workspace is open"}
        target = (root / str(args.get("path", ""))).resolve()
        if target != root and root not in target.parents:
            return {"ok": False, "error": "Path is outside the workspace"}
        if target.is_dir():
            return {"ok": False, "error": "Path is a directory"}
        if not target.exists():
            return {"ok": False, "error": f"File not found in current workspace: {args.get('path', '')}"}
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if len(text) > 60_000:
            text = text[:60_000] + "\n… truncated"
        return {"ok": True, "path": str(target.relative_to(root)), "content": text}
    if cmd == "git_panel":
        info = session.workspace_info()
        data: dict = {"project": info.to_json() if info else None, "status": None, "log": None}
        if session.git_tools is not None:
            status = await session.git_tools._status()
            data["status"] = {"ok": status.ok, "content": status.content, "error": status.error}
            log = await session.git_tools._log(10)
            data["log"] = {"ok": log.ok, "content": log.content, "error": log.error}
        return data
    if cmd in ("git_stage", "git_unstage", "git_commit", "git_diff_file", "git_switch", "git_revert"):
        # User-initiated write ops (never agent tools, §17) — sandboxed helpers.
        from axiom.core.tools.git_tools import (
            git_commit,
            git_diff_file,
            git_revert,
            git_stage,
            git_switch,
            git_unstage,
        )

        root = session.workspace_root
        if root is None:
            raise ValueError("No project is open")
        paths = [str(p) for p in (args.get("paths") or [])]
        try:
            if cmd == "git_stage":
                return {"ok": True, "output": git_stage(root, paths)}
            if cmd == "git_unstage":
                return {"ok": True, "output": git_unstage(root, paths)}
            if cmd == "git_commit":
                return {
                    "ok": True,
                    "output": git_commit(root, str(args.get("message", "")),
                                         all=bool(args.get("all"))),
                }
            if cmd == "git_switch":
                return {"ok": True, "output": git_switch(root, str(args.get("branch", "")))}
            if cmd == "git_revert":
                return {"ok": True, "output": git_revert(root, str(args.get("path", "")))}
            return {"ok": True, "diff": git_diff_file(root, str(args.get("path", "")))}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
    if cmd == "git_checkpoint":
        return session.git_checkpoint()
    if cmd == "git_rollback":
        return session.git_rollback()
    if cmd == "apply_patch":
        # User action from a diff block must pass the same sandbox, permission,
        # workspace, audit and checkpoint gates as any model-initiated patch.
        root = session.workspace_root
        if root is None:
            raise ValueError("No project is open")
        rel = str(args.get("path", "")).strip()
        patch = str(args.get("patch", ""))
        if not rel or not patch:
            raise ValueError("Both path and patch are required")
        name = "apply_patch"
        if not session.sandbox.allows(name):
            return {"ok": False, "error": "Patch blocked by sandbox policy"}
        tool_args = {"path": rel, "patch": patch}
        permission = session.tools.permission_for(name, tool_args)
        if not await session.permissions.decide(name, tool_args, permission):
            return {"ok": False, "error": "Patch permission denied"}
        result = await session.tools.execute(name, tool_args, approved=True)
        return {"ok": result.ok, "path": rel if result.ok else None, "error": result.error}
    if cmd == "search_chats":
        hits = session.history_store.search(str(args.get("query", "")))
        return {"hits": hits}
    if cmd == "project_search":
        root = session.workspace_root
        if root is None:
            return {"query": str(args.get("query", "")), "hits": []}
        query = str(args.get("query", "")).strip()
        if not query:
            return {"query": query, "hits": []}
        result = await session.tools.execute("search_text", {"query": query})
        if not result.ok:
            return {"query": query, "hits": [], "error": result.error}
        hits = []
        for line in (result.content or "").splitlines():
            if not line.strip():
                continue
            parts = line.split(":", 2)
            if len(parts) >= 2:
                hits.append({"path": parts[0].strip(), "preview": (parts[2] if len(parts) == 3 else "").strip()})
        return {"query": query, "hits": hits}
    if cmd == "chat_export":
        # W3.9: export a stored conversation to Markdown + JSON (real messages).
        from axiom.core.chat_export import export_conversation

        cid = str(args.get("id", "")).strip()
        if not cid:
            raise ValueError("id is required")
        conversation = session.history_store.load(cid)
        if conversation is None:
            raise ValueError(f"conversation '{cid}' not found")
        return export_conversation(conversation)
    if cmd == "artifact_list":
        # W3.17: list artifact documents for the current workspace.
        workspace = _artifact_workspace(session)
        return [document_meta(document) for document in workspace.list()]
    if cmd == "artifact_get":
        workspace = _artifact_workspace(session)
        artifact_id = str(args.get("id", "")).strip()
        if not artifact_id:
            raise ValueError("id is required")
        document = workspace.load(artifact_id)
        if document is None:
            raise ValueError(f"artifact '{artifact_id}' not found")
        return document.model_dump()
    if cmd == "artifact_save":
        workspace = _artifact_workspace(session)
        artifact_id = str(args.get("id", "")).strip() or None
        title = str(args.get("title") or "").strip()
        content = str(args.get("content") or "")
        if artifact_id is None and not title:
            raise ValueError("title is required for a new document")
        if artifact_id is None:
            document = workspace.create(title, content, task_id=args.get("task_id"),
                                        kind=str(args.get("kind") or "markdown"))
        else:
            document = workspace.update(artifact_id, content)
            if document is None:
                raise ValueError(f"artifact '{artifact_id}' not found")
        return document.model_dump()
    if cmd == "artifact_delete":
        workspace = _artifact_workspace(session)
        artifact_id = str(args.get("id", "")).strip()
        if not artifact_id:
            raise ValueError("id is required")
        return {"deleted": workspace.delete(artifact_id)}
    if cmd == "artifact_export":
        workspace = _artifact_workspace(session)
        artifact_id = str(args.get("id", "")).strip()
        path = str(args.get("path", "")).strip()
        if not artifact_id or not path:
            raise ValueError("id and path are required")
        return {"ok": workspace.export(artifact_id, Path(path)), "path": path}
    if cmd == "chat_meta":
        cid = str(args.get("id", ""))
        ok = session.history_store.set_meta(
            cid,
            pinned=args.get("pin") if "pin" in args else None,
            folder=args.get("folder", ...),
        )
        return {"ok": ok}
    if cmd in ("shell_start", "shell_write", "shell_read", "shell_stop"):
        # Interactive shell session (pipes, one process per GUI panel).
        from axiom.core.tools.shell import ShellSession

        if session.config.access_mode == "read_only" or not session.config.terminal_enabled:
            raise ValueError("Terminal is disabled in settings")
        shell = getattr(session, "gui_shell", None)
        if cmd == "shell_start":
            if shell is None or not shell.running:
                root = session.workspace_root
                shell = ShellSession(root)
                shell.start()
                session.gui_shell = shell
            return {"running": shell.running, "output": shell.read()}
        if shell is None:
            return {"running": False, "output": ""}
        if cmd == "shell_write":
            ok = shell.write(str(args.get("line", "")))
            return {"running": shell.running, "ok": ok}
        if cmd == "shell_read":
            return {"running": shell.running, "output": shell.read()}
        shell.stop()
        session.gui_shell = None
        return {"running": False, "output": ""}
    if cmd == "get_config":
        return json.loads(session.config.model_dump_json())
    if cmd == "set_config":
        current = session.config.model_dump()
        autonomy_request = (args.get("patch") or {}).get("autonomy_mode")
        for key, value in (args.get("patch") or {}).items():
            if key in current and key != "autonomy_mode":
                current[key] = value
        new_cfg = Config.model_validate(current)
        if isinstance(autonomy_request, str) and autonomy_request.strip():
            # W4.9: one autonomy switch composes both persisted axes at once.
            from axiom.core.autonomy import apply_autonomy as _apply_autonomy

            axes = _apply_autonomy(autonomy_request)
            new_cfg.access_mode = axes["access_mode"]  # type: ignore[assignment]
            new_cfg.permission_mode = axes["permission_mode"]
        from axiom.core.autonomy import resolve_autonomy as _resolve_autonomy

        try:
            new_cfg.autonomy_mode = _resolve_autonomy(new_cfg.access_mode, new_cfg.permission_mode)
        except Exception:
            pass
        new_cfg.save()
        session.config = new_cfg
        session._configure_router_from_config()
        permissions = getattr(session, "permissions", None)
        if permissions is not None:
            permissions._config = new_cfg
            try:
                permissions.bind_context(
                    task_id=permissions.active_task_id,
                    project=str(new_cfg.workspace_root) if new_cfg.workspace_root else None,
                )
            except Exception:
                pass
        sandbox = getattr(session, "sandbox", None)
        if sandbox is not None and hasattr(sandbox, "apply_preset"):
            try:
                autonomy = _resolve_autonomy(new_cfg.access_mode, new_cfg.permission_mode)
                sandbox.apply_preset(
                    {"plan": "readonly", "edit": "workspace",
                     "auto": "workspace", "full": "full"}.get(autonomy, "workspace")
                )
            except Exception:
                pass
        # Agent and web tool read live attributes; update them defensively.
        agent = getattr(session, "agent", None)
        if agent is not None:
            agent.config = new_cfg
            agent._config = new_cfg
        ws_tools = getattr(session, "workspace_tools", None)
        if ws_tools is not None:
            ws_tools.access_mode = new_cfg.access_mode
            if new_cfg.workspace_root:
                ws_tools.set_root(Path(new_cfg.workspace_root).expanduser())
        # Rebuild the search backend in place: the provider selection and
        # timeout changed, so the live WebSearchTool + agent must follow.
        session._rebuild_search_provider()
        history_store = getattr(session, "history_store", None)
        if history_store is not None:
            history_store.set_limit(new_cfg.history_limit if new_cfg.save_history else None)
        # Live Ollama transport settings — keep_alive on the client.
        client = getattr(session, "client", None)
        if client is not None:
            client.keep_alive = new_cfg.keep_alive
        # Live workspace settings — root / terminal / access mode.
        ws_tools = getattr(session, "workspace_tools", None)
        if ws_tools is not None and new_cfg.workspace_tools_enabled and new_cfg.workspace_root:
            ws_tools.set_root(Path(new_cfg.workspace_root).expanduser())
        terminal = getattr(session, "terminal", None)
        if terminal is not None:
            if not new_cfg.terminal_enabled or new_cfg.access_mode == "read_only":
                terminal.enabled = False
            else:
                terminal.enabled = True
                if new_cfg.workspace_root:
                    terminal.set_root(Path(new_cfg.workspace_root).expanduser())
        elif new_cfg.terminal_enabled and new_cfg.workspace_tools_enabled and new_cfg.access_mode != "read_only":
            from axiom.core.tools.terminal import TerminalTool

            new_terminal = TerminalTool(
                root=Path(new_cfg.workspace_root).expanduser() if new_cfg.workspace_root else None,
                enabled=True,
            )
            session.terminal = new_terminal
            new_terminal.register(session.tools)
        return json.loads(new_cfg.model_dump_json())
    if cmd == "set_model":
        # React sends camelCase while Python/TUI callers use snake_case.  Both
        # are part of the bridge protocol; silently defaulting a missing key to
        # Ollama used to send external models to /api/show and report a false
        # "not available in Ollama" error.
        provider_id = str(args.get("provider_id") or args.get("providerId") or "ollama")
        name = str(args["name"])
        if provider_id == "ollama":
            # Clearing the config value is not enough: the live ModelRouter keeps
            # its own primary RouteTarget. Without re-configuring it, a previously
            # selected external route (e.g. openai_compatible) stays active and
            # every message keeps hitting that provider even though Ollama is now
            # the chosen model. Reset both the persisted config and the router.
            session.config.router_primary = None
            session.config.save()
            session._configure_router_from_config()
            model = await session.switch_model(name)
            if session.config.warmup_model:
                session.core_warmup_task = asyncio.create_task(session.warmup_model(model.name))
            return _model_json(model)

        session.config.router_primary = {"provider_id": provider_id, "model": name}
        session.config.save()
        session._configure_router_from_config()
        active = ModelInfo(name=name, capabilities=_external_capabilities(name))
        session.active_model = active
        session.conversation.model = active.name
        return _model_json(active, provider_id=provider_id, source="external")
    if cmd == "warmup":
        primary = session.router.config.primary
        if primary is not None and primary.provider_id != "ollama":
            return {"warmed": True, "pending": False, "skipped": "external_provider"}
        task = getattr(session, "core_warmup_task", None)
        if task is not None and not task.done():
            return {"warmed": False, "pending": True}
        session.core_warmup_task = asyncio.create_task(
            session.warmup_model(args.get("name"))
        )
        return {"warmed": False, "pending": True}
    if cmd == "state":
        return await _state_json(session)
    raise ValueError(f"Unknown command: {cmd}")


async def _run() -> None:
    if os.environ.get("AXIOM_E2E_SCRIPTED_MODEL") == "1":
        install_scripted_model()
    loop = asyncio.get_running_loop()
    session = ChatSession()
    # Keep task events flowing independently of the command that launched a
    # task. On reconnect the UI also reloads persisted tasks through `tasks`.
    session.bus.subscribe("task.event", lambda payload: _write_line(
        json.dumps({"type": "event", "event": payload}, ensure_ascii=False)))
    # W2.4: ASK tool calls (including model-initiated memory writes) pause on a
    # real dialog in the shell instead of being silently denied.
    session.permissions.request_callback(
        lambda tool, args: _ask_permission(session, tool, args)
    )

    async def dispatch(req_id: int, coro) -> None:
        try:
            data = await coro
            reply = json.dumps(
                {"type": "reply", "req": req_id, "ok": True, "data": data},
                ensure_ascii=False,
            )
        except Exception as exc:
            reply = json.dumps(
                {"type": "reply", "req": req_id, "ok": False, "error": str(exc)},
                ensure_ascii=False,
            )
        await loop.run_in_executor(None, _write_line, reply)

    def on_line(raw: str) -> None:
        try:
            request = json.loads(raw)
            req_id = int(request.get("req", 0))
            cmd = str(request.get("cmd", ""))
            args = request.get("args") or {}
            asyncio.run_coroutine_threadsafe(dispatch(req_id, _handle(session, cmd, args)), loop)
        except Exception as exc:
            _write_line(json.dumps({"type": "reply", "req": 0, "ok": False, "error": str(exc)}))

    def pump() -> None:
        for raw in sys.stdin:
            raw = raw.strip()
            if raw:
                on_line(raw)
        # stdin may close when a webview/IPC client disconnects. The core stays
        # alive for detached task workers and its checkpoints survive restart.

    threading.Thread(target=pump, daemon=True).start()
    await asyncio.Event().wait()  # run until the shell closes stdin


def main() -> None:
    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


if __name__ == "__main__":
    main()

