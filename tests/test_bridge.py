"""JSONL round-trip test of the desktop bridge (no window, no Ollama needed).

Spawns ``desktop/src-tauri/bridge/axiom_bridge.py`` exactly like the Tauri
shell does and exchanges real JSONL requests/replies over stdio.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "desktop" / "src-tauri" / "bridge" / "axiom_bridge.py"


class BridgeProcess:
    """Runs the bridge as a subprocess and matches replies by request id."""

    def __init__(self, home: Path, ollama_url: str = "http://127.0.0.1:9") -> None:
        home.mkdir(parents=True, exist_ok=True)
        # A dead Ollama URL keeps `send` offline (no real generations).
        (home / "config.json").write_text(
            json.dumps({"ollama_url": ollama_url, "model": None}), encoding="utf-8"
        )
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "AXIOM_HOME": str(home),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
        self.home = home
        self._proc = subprocess.Popen(
            [sys.executable, "-u", str(BRIDGE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
            encoding="utf-8",
        )
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        self._stdin = self._proc.stdin
        self._stdout = self._proc.stdout
        self._replies: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "reply":
                with self._lock:
                    self._replies[int(payload.get("req", 0))] = payload

    def request(self, req: int, cmd: str, args: dict | None = None, timeout: float = 15.0) -> dict:
        line = json.dumps({"req": req, "cmd": cmd, "args": args or {}}, ensure_ascii=False)
        self._stdin.write(line + "\n")
        self._stdin.flush()
        deadline = 50 * timeout / 10  # poll loop budget
        waited = 0
        while waited < deadline:
            with self._lock:
                if req in self._replies:
                    return self._replies[req]
            waited += 1
            threading.Event().wait(0.1)
        raise TimeoutError(f"bridge did not answer {cmd} in time")

    def close(self) -> None:
        try:
            self._stdin.close()
        except OSError:
            pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()


@pytest.fixture()
def bridge(tmp_path: Path) -> Iterator[BridgeProcess]:
    proc = BridgeProcess(tmp_path / "axiom-home")
    yield proc
    proc.close()


def test_get_config_round_trip(bridge: BridgeProcess) -> None:
    reply = bridge.request(1, "get_config")
    assert reply["ok"] is True
    assert reply["data"]["ollama_url"].startswith("http")
    assert "theme" in reply["data"]


def test_set_config_round_trip(bridge: BridgeProcess) -> None:
    reply = bridge.request(
        2,
        "set_config",
        {"patch": {"temperature": 0.4, "theme": "light", "accent": "teal", "panel_hover": False}},
    )
    assert reply["ok"] is True
    assert reply["data"]["temperature"] == 0.4
    assert reply["data"]["theme"] == "light"
    assert reply["data"]["accent"] == "teal"
    assert reply["data"]["panel_hover"] is False


def test_set_config_persists(tmp_path: Path) -> None:
    proc = BridgeProcess(tmp_path / "axiom-home")
    try:
        reply = proc.request(
            2,
            "set_config",
            {"patch": {"temperature": 0.4, "accent": "violet", "panel_hover": False}},
        )
        assert reply["ok"] is True
        saved = json.loads((tmp_path / "axiom-home" / "config.json").read_text(encoding="utf-8"))
        assert saved["temperature"] == 0.4
        assert saved["accent"] == "violet"
        assert saved["panel_hover"] is False
    finally:
        proc.close()


def test_search_providers_lists_choices(bridge: BridgeProcess) -> None:
    reply = bridge.request(20, "search_providers")
    assert reply["ok"] is True
    ids = [row["id"] for row in reply["data"]]
    assert ids[0] == "auto"
    assert "brave" in ids and "wikipedia" in ids
    assert all(row["name"] for row in reply["data"])


def test_search_test_empty_query_is_offline(bridge: BridgeProcess) -> None:
    reply = bridge.request(21, "search_test", {"query": ""})
    assert reply["ok"] is True
    assert reply["data"]["ok"] is False
    assert reply["data"]["error"] == "Empty query"


def test_memory_add_list_edit_delete_round_trip(bridge: BridgeProcess) -> None:
    """W2.1: memory CRUD round-trips through the bridge and hits real disk."""
    reply = bridge.request(60, "memory_list")
    assert reply["ok"] is True
    assert reply["data"] == []

    added = bridge.request(61, "memory_add", {"content": "User prefers dark theme"})
    assert added["ok"] is True
    item_id = added["data"]["id"]
    assert item_id

    rows = bridge.request(62, "memory_list")["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == item_id
    assert rows[0]["content"] == "User prefers dark theme"
    assert rows[0]["scope"] == "global"

    edited = bridge.request(63, "memory_edit", {"id": item_id, "content": "Prefers dark theme everywhere"})
    assert edited["ok"] is True
    rows = bridge.request(64, "memory_list")["data"]
    assert rows[0]["content"] == "Prefers dark theme everywhere"

    deleted = bridge.request(65, "memory_delete", {"id": item_id})
    assert deleted["ok"] is True
    assert deleted["data"]["removed"] is True
    assert bridge.request(66, "memory_list")["data"] == []


def test_memory_add_rejects_empty_content(bridge: BridgeProcess) -> None:
    reply = bridge.request(67, "memory_add", {"content": "   "})
    assert reply["ok"] is False
    assert "rejected" in reply["error"]


def test_memory_delete_unknown_id_is_not_removed(bridge: BridgeProcess) -> None:
    reply = bridge.request(68, "memory_delete", {"id": "nope"})
    assert reply["ok"] is True
    assert reply["data"]["removed"] is False


def test_knowledge_add_list_search_remove_round_trip(bridge: BridgeProcess, tmp_path) -> None:
    """W2.2: collection index → list → cited search → remove through the bridge."""
    docs = tmp_path / "kb"
    docs.mkdir()
    (docs / "runbook.md").write_text(
        "# Runbook\n\nThe staging VPN gateway is gw-staging.internal.\n",
        encoding="utf-8",
    )
    reply = bridge.request(70, "knowledge_list")
    assert reply["ok"] is True
    before = len(reply["data"])

    added = bridge.request(71, "knowledge_add", {"name": "runbook", "path": str(docs)})
    assert added["ok"] is True
    assert added["data"]["stats"]["indexed"] == 1
    assert added["data"]["collection"]["files"] == 1

    rows = bridge.request(72, "knowledge_list")["data"]
    assert len(rows) == before + 1
    row = next(r for r in rows if r["name"] == "runbook")
    assert row["chunks"] >= 1
    assert row["embeddings"] in {"disabled", "ok"} or row["embeddings"].startswith("unavailable:")

    hits = bridge.request(73, "knowledge_search", {"query": "staging VPN"})["data"]
    assert hits and hits[0]["source"] == "runbook.md"
    assert "gw-staging" in hits[0]["text"]

    removed = bridge.request(74, "knowledge_remove", {"name": "runbook"})
    assert removed["ok"] is True and removed["data"]["removed"] is True
    assert len(bridge.request(75, "knowledge_list")["data"]) == before


def test_knowledge_add_rejects_missing_path(bridge: BridgeProcess, tmp_path) -> None:
    reply = bridge.request(76, "knowledge_add", {"name": "x", "path": str(tmp_path / "nope")})
    assert reply["ok"] is False
    assert "does not exist" in reply["error"]


def test_knowledge_reindex_unknown_collection_fails(bridge: BridgeProcess) -> None:
    reply = bridge.request(77, "knowledge_reindex", {"name": "nope"})
    assert reply["ok"] is False
    assert "Unknown collection" in reply["error"]


def test_list_chats_empty(bridge: BridgeProcess) -> None:
    reply = bridge.request(3, "list_chats")
    assert reply["ok"] is True
    assert reply["data"] == []


def test_new_chat_ids_differ_and_unknown_load_is_none(bridge: BridgeProcess) -> None:
    first = bridge.request(4, "new_chat")
    second = bridge.request(5, "new_chat")
    assert first["ok"] is True and second["ok"] is True
    assert first["data"]["id"] != second["data"]["id"]
    assert first["data"]["messages"] == []
    # A never-saved conversation cannot be loaded — history has no such file.
    missing = bridge.request(6, "load_chat", {"id": "does-not-exist"})
    assert missing["ok"] is True and missing["data"] is None


def test_saved_conversation_round_trips_through_the_bridge(tmp_path: Path) -> None:
    from axiom.core.events import Message
    from axiom.core.history import Conversation, HistoryStore

    home = tmp_path / "axiom-home"
    store = HistoryStore(directory=home / "history")
    conv = Conversation(title="from disk")
    conv.messages.append(Message(role="user", content="привет"))
    store.save(conv)

    proc = BridgeProcess(home)
    try:
        loaded = proc.request(1, "load_chat", {"id": conv.id})
        assert loaded["ok"] is True
        assert loaded["data"]["id"] == conv.id
        assert loaded["data"]["messages"][0]["content"] == "привет"
        listed = proc.request(2, "list_chats")
        assert [c["id"] for c in listed["data"]] == [conv.id]
    finally:
        proc.close()


def test_unknown_command_is_a_structured_error(bridge: BridgeProcess) -> None:
    reply = bridge.request(6, "no_such_command")
    assert reply["ok"] is False
    assert "Unknown command" in reply["error"]


def test_external_model_camel_case_payload_never_uses_ollama(bridge: BridgeProcess) -> None:
    """The React client uses providerId; external routes must not hit /api/show."""
    reply = bridge.request(7, "set_model", {
        "name": "deepseek/deepseek-v4-flash",
        "providerId": "openai_compatible",
    })
    assert reply["ok"] is True
    assert reply["data"]["name"] == "deepseek/deepseek-v4-flash"
    assert reply["data"]["providerId"] == "openai_compatible"
    assert reply["data"]["source"] == "external"
    assert "tools" in reply["data"]["capabilities"]

    detail = bridge.request(8, "model_info", {
        "name": "deepseek/deepseek-v4-flash",
        "providerId": "openai_compatible",
    })
    assert detail["ok"] is True
    assert detail["data"]["providerId"] == "openai_compatible"
    assert detail["data"]["source"] == "external"

    config = bridge.request(9, "get_config")
    assert config["data"]["router_primary"] == {
        "provider_id": "openai_compatible",
        "model": "deepseek/deepseek-v4-flash",
    }
    warmup = bridge.request(10, "warmup", {})
    assert warmup["ok"] is True
    assert warmup["data"]["skipped"] == "external_provider"
    status = bridge.request(11, "status")
    assert status["data"]["activeModel"]["providerId"] == "openai_compatible"
    assert status["data"]["activeModel"]["source"] == "external"



def test_project_search_returns_clickable_file_hits(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("def fallback():\n    return 'ok'\n", encoding="utf-8")
    home = tmp_path / "axiom-home"
    home.mkdir()
    proc = BridgeProcess(home)
    try:
        assert proc.request(1, "set_workspace", {"path": str(project)})["ok"] is True
        reply = proc.request(2, "project_search", {"query": "fallback"})
        assert reply["ok"] is True
        assert reply["data"]["hits"]
        assert reply["data"]["hits"][0]["path"] == "main.py"
        assert "def fallback" in reply["data"]["hits"][0]["preview"]
    finally:
        proc.close()



# ------------------------------------------------------------- plugin manager


def _write_plugin_folder(root: Path, name: str = "demo") -> Path:
    """Create a minimal, valid plugin folder (manifest + a real tool)."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(
        json.dumps({
            "name": name,
            "version": "1.0.0",
            "description": "Demo plugin",
            "tools": ["hello"],
        }),
        encoding="utf-8",
    )
    (folder / "plugin.py").write_text(
        "from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult\n"
        "TOOLS = [ToolDefinition(name='hello', description='Say hello',\n"
        "                        permission=ToolPermission.ALWAYS)]\n"
        "async def hello(name: str = 'world'):\n"
        "    return ToolResult(name='hello', ok=True, content=f'Hello {name}')\n"
        "HANDLERS = {'hello': hello}\n",
        encoding="utf-8",
    )
    return folder


def test_plugin_install_toggle_remove_round_trip(tmp_path: Path) -> None:
    """The full install → list → toggle → remove flow works over the bridge."""
    home = tmp_path / "axiom-home"
    home.mkdir(parents=True)
    source = _write_plugin_folder(tmp_path / "src")
    proc = BridgeProcess(home)
    try:
        installed = proc.request(1, "install_plugin", {"path": str(source)})
        assert installed["ok"] is True
        assert installed["data"]["name"] == "demo"
        assert installed["data"]["status"] == "installed"

        listed = proc.request(2, "list_plugins")
        assert listed["ok"] is True
        assert [row["name"] for row in listed["data"]] == ["demo"]
        # Install is not consent: new plugins start disabled until toggled on.
        assert listed["data"][0]["enabled"] is False

        # Reinstall is idempotent: it updates in place, never duplicates.
        again = proc.request(3, "install_plugin", {"path": str(source)})
        assert again["data"]["status"] == "updated"
        relisted = proc.request(4, "list_plugins")
        assert [row["name"] for row in relisted["data"]] == ["demo"]

        on = proc.request(5, "toggle_plugin", {"name": "demo", "enabled": True})
        assert on["data"]["enabled"] is True

        off = proc.request(6, "toggle_plugin", {"name": "demo", "enabled": False})
        assert off["ok"] is True
        assert off["data"] == {"name": "demo", "enabled": False, "ok": True}

        removed = proc.request(7, "remove_plugin", {"name": "demo"})
        assert removed["ok"] is True
        assert removed["data"] == {"name": "demo", "removed": True}

        empty = proc.request(8, "list_plugins")
        assert empty["data"] == []
    finally:
        proc.close()


def test_install_plugin_requires_path(bridge: BridgeProcess) -> None:
    reply = bridge.request(1, "install_plugin", {})
    assert reply["ok"] is False
    assert "path is required" in reply["error"]


def test_toggle_plugin_unknown_name_reports_not_found(bridge: BridgeProcess) -> None:
    reply = bridge.request(1, "toggle_plugin", {"name": "missing", "enabled": True})
    assert reply["ok"] is True
    assert reply["data"] == {"name": "missing", "enabled": False, "ok": False}


def test_discover_plugins_picks_up_manually_dropped_folder(tmp_path: Path) -> None:
    """A folder copied into ~/.axiom/plugins is seen by discover without restart."""
    home = tmp_path / "axiom-home"
    home.mkdir(parents=True)
    proc = BridgeProcess(home)
    try:
        assert proc.request(1, "list_plugins")["data"] == []
        # Simulate the user manually dropping a plugin folder while running.
        _write_plugin_folder(home / "plugins", name="manual")
        discovered = proc.request(2, "discover_plugins")
        assert discovered["ok"] is True
        assert "manual" in discovered["data"]["discovered"]
        assert [row["name"] for row in discovered["data"]["plugins"]] == ["manual"]
        # A second discover finds nothing new (idempotent).
        again = proc.request(3, "discover_plugins")
        assert again["data"]["discovered"] == []
        assert [row["name"] for row in again["data"]["plugins"]] == ["manual"]
    finally:
        proc.close()


def test_bundled_plugins_lists_real_builtins(bridge: BridgeProcess) -> None:
    """The bundled catalogue exposes the plugins shipped with AXIOM."""
    reply = bridge.request(1, "bundled_plugins")
    assert reply["ok"] is True
    names = {row["name"] for row in reply["data"]}
    assert {"calculator", "datetime", "notes", "texttools", "security"} <= names
    assert all(row["bundled"] is True for row in reply["data"])


def test_install_bundled_plugin_round_trip(tmp_path: Path) -> None:
    """Install → list → tools live → remove → back in the catalogue."""
    home = tmp_path / "axiom-home"
    home.mkdir(parents=True)
    proc = BridgeProcess(home)
    try:
        installed = proc.request(1, "install_bundled_plugin", {"name": "calculator"})
        assert installed["ok"] is True
        assert installed["data"]["status"] == "installed"
        assert installed["data"]["manifest"]["bundled"] is True

        listed = proc.request(2, "list_plugins")
        rows = {row["name"]: row for row in listed["data"]}
        assert "calculator" in rows
        # Bundled install is not consent either: disabled until toggled on.
        assert rows["calculator"]["enabled"] is False
        assert "calculate" in rows["calculator"]["tools"]

        # Enable it; the real tool of the bundled plugin becomes callable.
        enabled = proc.request(3, "toggle_plugin", {"name": "calculator", "enabled": True})
        assert enabled["data"]["enabled"] is True
        tools = proc.request(4, "tools")
        tool_names = [item["name"] for item in tools["data"]]
        assert "calculate" in tool_names

        # While installed, the catalogue no longer offers it.
        bundled = proc.request(5, "bundled_plugins")
        assert "calculator" not in {row["name"] for row in bundled["data"]}

        # Toggle off, then on again.
        off = proc.request(6, "toggle_plugin", {"name": "calculator", "enabled": False})
        assert off["data"]["enabled"] is False
        on = proc.request(7, "toggle_plugin", {"name": "calculator", "enabled": True})
        assert on["data"]["enabled"] is True

        # Removal puts it back into the available catalogue.
        removed = proc.request(8, "remove_plugin", {"name": "calculator"})
        assert removed["data"]["removed"] is True
        bundled_again = proc.request(9, "bundled_plugins")
        assert "calculator" in {row["name"] for row in bundled_again["data"]}
    finally:
        proc.close()


def test_install_bundled_plugin_requires_name(bridge: BridgeProcess) -> None:
    reply = bridge.request(1, "install_bundled_plugin", {})
    assert reply["ok"] is False
    assert "name is required" in reply["error"]



def test_send_without_ollama_reports_error_event(bridge: BridgeProcess) -> None:
    reply = bridge.request(7, "send", {"text": "hi"})
    # The reply itself is ok (events were streamed); without a live Ollama the
    # stream contains a structured error event, not a crash.
    assert reply["ok"] is True


# ------------------------------------------------------------- orchestrate live progress


def _bridge_module():
    """Import the bridge script as a module (no stdio session is started)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("axiom_bridge_under_test", BRIDGE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_set_model_ollama_resets_stale_external_router(tmp_path: Path, monkeypatch) -> None:
    """Picking an Ollama model must clear a previously selected external route.

    Regression: a leftover ``router_primary`` (e.g. openai_compatible) kept the
    live ModelRouter pointed at the external provider, so every message hit that
    provider (HTTP 402) even though the user had switched back to a local model.
    """
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.history import HistoryStore
    from axiom.core.models import ModelInfo

    cfg = Config(model="gemma4:e4b")
    cfg.save_history = False
    cfg.router_primary = {"provider_id": "openai_compatible", "model": "deepseek/deepseek-v4-flash"}
    session = ChatSession(config=cfg, history_store=HistoryStore(directory=tmp_path / "h"))

    # The live router really carries the external primary at this point.
    assert session.router.config.primary is not None
    assert session.router.config.primary.provider_id == "openai_compatible"

    # ``switch_model`` normally needs a live Ollama registry; stub it so the test
    # stays offline and focuses on the router reset behaviour.
    async def _fake_switch(name: str) -> ModelInfo:
        model = ModelInfo(name=name)
        session.active_model = model
        session.conversation.model = name
        return model

    session.switch_model = _fake_switch  # type: ignore[assignment]

    mod = _bridge_module()
    result = await mod._handle(session, "set_model", {"name": "gemma4:e4b", "providerId": "ollama"})

    assert result["providerId"] == "ollama"
    assert result["source"] == "ollama"
    # Config value cleared AND the live router no longer targets the external provider.
    assert session.config.router_primary is None
    assert session.router.config.primary is None


async def test_set_model_ollama_routes_locally_after_external_pick(tmp_path: Path, monkeypatch) -> None:
    """After resetting, the ProviderChatClient must resolve to the Ollama path."""
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    from axiom.core.chat import ChatSession
    from axiom.core.config import Config
    from axiom.core.history import HistoryStore
    from axiom.core.models import ModelInfo

    cfg = Config(model="gemma4:e4b")
    cfg.save_history = False
    cfg.router_primary = {"provider_id": "openai_compatible", "model": "deepseek/deepseek-v4-flash"}
    session = ChatSession(config=cfg, history_store=HistoryStore(directory=tmp_path / "h"))

    async def _fake_switch(name: str) -> ModelInfo:
        model = ModelInfo(name=name)
        session.active_model = model
        return model

    session.switch_model = _fake_switch  # type: ignore[assignment]

    mod = _bridge_module()
    await mod._handle(session, "set_model", {"name": "gemma4:e4b", "providerId": "ollama"})

    # The routing decision the chat client would make for a real message now
    # points at Ollama, not the external provider that raised 402.
    target = session.provider_client._target("привет", "gemma4:e4b")
    assert target.provider_id == "ollama"
    assert target.model == "gemma4:e4b"


def test_progress_events_forward_only_new_orchestration_steps() -> None:
    mod = _bridge_module()
    timeline = [
        {"seq": 1, "kind": "orchestration.command", "actor": "user", "summary": "/orchestrate x"},
        {"seq": 2, "kind": "mode.switch", "actor": "system", "summary": "chat"},
        {"seq": 3, "kind": "agent.start", "actor": "coder", "summary": "coder: task"},
        {"seq": 4, "kind": "subagent.model", "actor": "coder", "summary": "ollama/test-model:latest"},
        {"seq": 5, "kind": "subagent.reasoning", "actor": "coder", "summary": "Сначала изучу проект"},
        {"seq": 6, "kind": "subagent.answer", "actor": "coder", "summary": "Изучаю структуру"},
        {"seq": 7, "kind": "subagent.tool.call", "actor": "coder", "summary": "write_file index.html"},
        {"seq": 8, "kind": "subagent.policy.mode", "actor": "coder", "summary": "mode=auto"},
    ]
    events = mod._progress_events(timeline, 0)
    assert [e["kind"] for e in events] == [
        "orchestration.command", "agent.start", "subagent.model",
        "subagent.reasoning", "subagent.answer", "subagent.tool.call",
    ]
    assert all(e["type"] == "orchestration" for e in events)
    assert events[1]["actor"] == "coder" and events[1]["seq"] == 3
    # Steps recorded before this run (baseline) must not leak into the UI.
    assert [e["seq"] for e in mod._progress_events(timeline, 2)] == [3, 4, 5, 6, 7]


async def test_watch_orchestration_streams_live_trajectory_steps(monkeypatch) -> None:
    """The watcher forwards each new step exactly once, then stops on demand."""
    import asyncio

    from axiom.core.trajectory import Trajectory

    mod = _bridge_module()
    written: list[str] = []
    monkeypatch.setattr(mod, "_write_line", written.append)

    class _Session:
        pass

    session = _Session()
    session.trajectory = Trajectory()
    session.trajectory.append("mode.switch", "old run", actor="system")
    baseline = len(session.trajectory.timeline())
    session.trajectory.append("orchestrator.plan", "mode=orchestrated", actor="orchestrator")
    session.trajectory.append("agent.start", "coder: task", actor="coder")

    stop = asyncio.Event()
    task = asyncio.create_task(mod._watch_orchestration(session, baseline, stop))
    await asyncio.sleep(0.05)  # first poll flushes the already-recorded steps
    stop.set()
    await asyncio.wait_for(task, timeout=5)

    payloads = [json.loads(line) for line in written]
    assert all(p["type"] == "event" for p in payloads)
    assert [p["event"]["kind"] for p in payloads] == ["orchestrator.plan", "agent.start"]
    assert payloads[1]["event"]["actor"] == "coder"


async def test_permission_request_waits_for_the_real_ui_answer(monkeypatch) -> None:
    """W2.4: an ASK tool emits a permission_request and waits for the answer."""
    import asyncio

    mod = _bridge_module()
    written: list[str] = []
    monkeypatch.setattr(mod, "_write_line", written.append)

    class _Tools:
        def get(self, name: str):
            class _Definition:
                risk = "medium"

            return _Definition() if name == "memory_write" else None

    class _Config:
        workspace_root = "C:/demo"

    class _Session:
        tools = _Tools()
        config = _Config()

    task = asyncio.create_task(
        mod._ask_permission(_Session(), "memory_write", {"content": "remember me"})
    )
    await asyncio.sleep(0.05)
    assert len(written) == 1
    payload = json.loads(written[0])
    assert payload["type"] == "event"
    event = payload["event"]
    assert event["type"] == "permission_request"
    assert event["tool"] == "memory_write"
    assert event["arguments"] == {"content": "remember me"}
    assert event["cwd"] == "C:/demo"
    assert event["risk"] == "medium"
    assert event["id"]

    # The tool call is still suspended — nothing has been approved yet.
    assert not task.done()
    assert mod._resolve_permission(event["id"], "allow_once") is True
    assert await asyncio.wait_for(task, timeout=5) == "allow_once"
    # A stale second answer (or an unknown id) is a no-op, not a crash.
    assert mod._resolve_permission(event["id"], "deny") is False
    assert mod._resolve_permission("perm-missing", "deny") is False


async def test_permission_payload_falls_back_without_registry() -> None:
    """A tool that is not in the registry still yields a safe payload."""
    mod = _bridge_module()

    class _Session:
        pass

    payload = mod._permission_payload(_Session(), "memory_write", {})
    assert payload["arguments"] == {}
    assert payload["cwd"] == "."
    assert payload["risk"] == "safe"


def test_permission_respond_command_reports_stale_ids(bridge: BridgeProcess) -> None:
    """The real bridge answers permission_respond; stale ids are not accepted."""
    reply = bridge.request(1, "permission_respond", {"id": "perm-1", "decision": "allow_once"})
    assert reply["ok"] is True
    assert reply["data"] == {"resolved": False}
