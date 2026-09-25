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
from pathlib import Path

from axiom.core.chat import ChatSession
from axiom.core.config import Config
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
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


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


async def _handle(session: ChatSession, cmd: str, args: dict) -> object:
    if cmd in {"task_start", "task_resume"}:
        # Push directly from the core bus; no polling, model calls or state
        # transitions in the frontend. The subscription is request-scoped.
        def forward(payload: dict) -> None:
            _write_line(json.dumps({"type": "event", "event": payload}, ensure_ascii=False))

        if session.busy:
            raise ValueError("A generation is already running")
        off = session.bus.subscribe("task.event", forward)
        try:
            if cmd == "task_start":
                task = await session.task_start(str(args.get("goal") or ""), planning=args.get("planning"))
            else:
                task = await session.task_resume(str(args.get("id") or ""),
                                                 acknowledge=args.get("acknowledge") is True)
            return task.model_dump(mode="json")
        finally:
            off()
    if cmd == "task_cancel":
        return {"cancelled": session.task_cancel(str(args.get("id") or ""))}
    if cmd == "task_state":
        task = session.task_state(str(args.get("id") or ""))
        return task.model_dump(mode="json") if task is not None else None
    if cmd == "tasks":
        return [task.model_dump(mode="json") for task in session.task_store.list()]
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
    if cmd == "permissions":
        mode = str(args.get("mode") or "ask")
        if mode not in {"ask", "auto_approve_safe", "auto_approve_all"}:
            raise ValueError("Unknown permission mode")
        session.permissions.mode = type(session.permissions.mode)(mode)
        session.config.permission_mode = mode
        session.config.save()
        return {"mode": mode}
    if cmd == "profiles":
        return {"active": session.profiles.active_name, "items": [
            {"id": name, "name": name, "prompt": prompt}
            for name, prompt in session.profiles.all.items()
        ]}
    if cmd == "trajectory":
        return session.trajectory.viewer()
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
    if cmd in ("git_stage", "git_unstage", "git_commit", "git_diff_file", "git_switch"):
        # User-initiated write ops (never agent tools, §17) — sandboxed helpers.
        from axiom.core.tools.git_tools import (
            git_commit,
            git_diff_file,
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
            return {"ok": True, "diff": git_diff_file(root, str(args.get("path", "")))}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
    if cmd == "apply_patch":
        # Apply a ```diff block from an answer to a workspace file.
        from axiom.core.patch import PatchError, apply_unified_diff

        root = session.workspace_root
        if root is None:
            raise ValueError("No project is open")
        if session.config.access_mode == "read_only":
            raise ValueError("Access mode is read-only")
        rel = str(args.get("path", "")).strip()
        patch = str(args.get("patch", ""))
        if not rel or not patch:
            raise ValueError("Both path and patch are required")
        if any(part == ".." for part in rel.replace("\\", "/").split("/")):
            raise ValueError(f"Path escapes the project: {rel}")
        target = (root / rel).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"Path escapes the project: {rel}")
        try:
            original = target.read_text(encoding="utf-8") if target.exists() else ""
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            updated = apply_unified_diff(original, patch)
        except PatchError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": rel}
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
        for key, value in (args.get("patch") or {}).items():
            if key in current:
                current[key] = value
        new_cfg = Config.model_validate(current)
        new_cfg.save()
        session.config = new_cfg
        session._configure_router_from_config()
        permissions = getattr(session, "permissions", None)
        if permissions is not None:
            permissions._config = new_cfg
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
    loop = asyncio.get_running_loop()
    session = ChatSession()

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
        # stdin closed — the shell is gone (killed, crashed or restarted).
        # Exit immediately so no orphaned bridge keeps running and, worse,
        # keeps answering stale requests against a dead UI.
        os._exit(0)

    threading.Thread(target=pump, daemon=True).start()
    await asyncio.Event().wait()  # run until the shell closes stdin


def main() -> None:
    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


if __name__ == "__main__":
    main()

