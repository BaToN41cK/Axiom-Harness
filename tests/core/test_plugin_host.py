"""W3.1 Plugins: typed UI host protocol and least-privilege scope enforcement."""
from __future__ import annotations

import json

from axiom.core.plugin_host import (
    ALL_CAPABILITIES,
    HostResponse,
    PluginHost,
    ScopeGate,
    allowlisted_catalog,
    catalog_allows,
    normalize_scopes,
    parse_request,
)
from axiom.core.plugins import PluginManifest

# --------------------------------------------------------------- scope gate


def test_scope_gate_is_default_closed() -> None:
    gate = ScopeGate()
    for capability in ALL_CAPABILITIES:
        assert gate.denied(capability)


def test_scope_gate_grants_only_declared_scopes() -> None:
    gate = ScopeGate(declared=frozenset({"ui"}))
    assert gate.allow("ui.render")
    assert gate.allow("ui.command")
    assert gate.denied("fs.read")
    assert gate.denied("net.http_get")
    assert gate.denied("clipboard.read")
    assert gate.denied("totally.unknown")


def test_normalize_scopes_drops_unknown() -> None:
    assert normalize_scopes(["ui", "net", "bogus"]) == frozenset({"ui", "net"})
    assert normalize_scopes(None) == frozenset()
    assert normalize_scopes("ui") == frozenset()


# ------------------------------------------------------------ message protocol


def test_parse_request_accepts_valid_request() -> None:
    parsed = parse_request({"id": "r1", "plugin": "demo", "method": "ui.render", "params": {}})
    assert not isinstance(parsed, str)
    assert parsed.id == "r1"
    assert parsed.method == "ui.render"


def test_parse_request_rejects_non_object() -> None:
    assert parse_request("nope") == "request must be a JSON object"
    assert parse_request(None) == "request must be a JSON object"


def test_parse_request_rejects_unknown_method() -> None:
    assert parse_request({"id": "r1", "plugin": "demo", "method": "evil.exec"}) == "unknown method 'evil.exec'"


def test_parse_request_rejects_missing_id() -> None:
    assert isinstance(parse_request({"plugin": "demo", "method": "ui.render"}), str)


def test_parse_request_rejects_extra_fields() -> None:
    assert isinstance(
        parse_request({"id": "r1", "plugin": "demo", "method": "ui.render", "hostDom": True}),
        str,
    )


def test_parse_request_rejects_oversized_params() -> None:
    parsed = parse_request(
        {"id": "r1", "plugin": "demo", "method": "ui.render", "params": {"blob": "x" * (40 * 1024)}}
    )
    assert parsed == "params exceed the size limit"


# ------------------------------------------------------------------ host


def test_host_routes_granted_capability() -> None:
    host = PluginHost(scopes=["ui"], handlers={"ui.render": lambda params: {"ok": True}})
    response = host.handle({"id": "r1", "plugin": "demo", "method": "ui.render", "params": {}})
    assert isinstance(response, HostResponse)
    assert response.ok is True
    assert response.data == {"ok": True}


def test_host_denies_ungranted_scope() -> None:
    host = PluginHost(scopes=["ui"], handlers={"fs.read": lambda params: "secret"})
    response = host.handle({"id": "r1", "plugin": "demo", "method": "fs.read", "params": {}})
    assert response.ok is False
    assert "scope not granted" in (response.error or "")


def test_host_reports_unavailable_capability() -> None:
    host = PluginHost(scopes=["ui"])
    response = host.handle({"id": "r1", "plugin": "demo", "method": "ui.render", "params": {}})
    assert response.ok is False
    assert "not available" in (response.error or "")


def test_host_contains_handler_crash() -> None:
    def boom(params):
        raise RuntimeError("kaboom")

    host = PluginHost(scopes=["ui"], handlers={"ui.render": boom})
    response = host.handle({"id": "r1", "plugin": "demo", "method": "ui.render", "params": {}})
    assert response.ok is False
    assert "RuntimeError: kaboom" in (response.error or "")


def test_host_register_rejects_unknown_capability() -> None:
    import pytest

    host = PluginHost(scopes=["ui"])
    with pytest.raises(ValueError):
        host.register("evil.exec", lambda p: None)


# ------------------------------------------------------------------ catalog


def test_allowlisted_catalog_is_a_copy() -> None:
    catalog = allowlisted_catalog()
    catalog["calculator"]["version"] = "999"
    assert allowlisted_catalog()["calculator"]["version"] == "1.0.0"


def test_catalog_allows_pinned_version_only() -> None:
    assert catalog_allows("calculator", "1.0.0") is True
    assert catalog_allows("calculator", "2.0.0") is False
    assert catalog_allows("unknown", "1.0.0") is False


# ------------------------------------------------------- example bundled plugin


def test_example_panel_plugin_declares_panel_and_command() -> None:
    from pathlib import Path

    manifest_path = (
        Path(__file__).resolve().parents[2] / "src" / "axiom" / "plugins" / "bundled" / "hello-panel" / "manifest.json"
    )
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = PluginManifest.from_dict(raw)
    manifest.validate()

    assert manifest.name == "hello-panel"
    assert manifest.ui_block is not None
    assert {e.type for e in manifest.ui_block.extensions} == {"panel", "command"}
    assert manifest.ui_block.scopes == ("ui",)
    panel = next(e for e in manifest.ui_block.extensions if e.type == "panel")
    assert panel.id == "hello"
    assert panel.meta.get("title") == "Привет"


# ---------------------------------------------------------- bridge enforcement


async def test_bridge_plugin_host_enforces_scopes(tmp_path, monkeypatch) -> None:
    """The runtime bridge gate denies net/fs for a ui-only plugin and executes
    granted fs capabilities in a workspace-scoped, traversal-guarded way."""
    from axiom.core.plugins import UIExtensionBlock
    from tests.core.test_orchestrator_runtime_a import _session as make_session
    from tests.test_bridge import _bridge_module

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "note.txt").write_text("hello", encoding="utf-8")
    session = make_session(tmp_path, monkeypatch, ws)
    mod = _bridge_module()

    session.plugins.install(PluginManifest(
        name="demo", capabilities=("ui",),
        ui_block=UIExtensionBlock(api_version=1, scopes=("ui",), extensions=()),
    ))

    denied_net = await mod._handle(session, "plugin_host", {
        "id": "1", "plugin": "demo", "method": "net.http_get", "params": {"url": "http://example.com"},
    })
    assert denied_net["ok"] is False
    assert "scope not granted" in denied_net["error"]

    denied_fs = await mod._handle(session, "plugin_host", {
        "id": "2", "plugin": "demo", "method": "fs.read", "params": {"path": "note.txt"},
    })
    assert denied_fs["ok"] is False
    assert "scope not granted" in denied_fs["error"]

    allowed_ui = await mod._handle(session, "plugin_host", {
        "id": "3", "plugin": "demo", "method": "ui.render",
    })
    assert allowed_ui["ok"] is True
    assert allowed_ui["data"] == {"ack": True}

    # A plugin that declares ``fs`` can read/write inside the workspace only.
    session.plugins.install(PluginManifest(
        name="fswriter", capabilities=("ui",),
        ui_block=UIExtensionBlock(api_version=1, scopes=("fs",), extensions=()),
    ))

    read = await mod._handle(session, "plugin_host", {
        "id": "4", "plugin": "fswriter", "method": "fs.read", "params": {"path": "note.txt"},
    })
    assert read["ok"] is True
    assert read["data"]["content"] == "hello"

    write = await mod._handle(session, "plugin_host", {
        "id": "5", "plugin": "fswriter", "method": "fs.write", "params": {"path": "out.txt", "content": "world"},
    })
    assert write["ok"] is True
    assert (ws / "out.txt").read_text(encoding="utf-8") == "world"

    escape = await mod._handle(session, "plugin_host", {
        "id": "6", "plugin": "fswriter", "method": "fs.read", "params": {"path": "../secret.txt"},
    })
    assert escape["ok"] is False
    assert "outside the workspace" in escape["error"]


async def test_bridge_plugin_commands_and_ui_html_and_crash_isolation(tmp_path, monkeypatch) -> None:
    """Command extensions surface via ``plugin_commands``; ``plugin_ui_html``
    serves the plugin document; a failing fs read is a structured error, never a
    bridge crash."""
    from axiom.core.plugins import UIExtension, UIExtensionBlock
    from tests.core.test_orchestrator_runtime_a import _session as make_session
    from tests.test_bridge import _bridge_module

    ui_dir = tmp_path / "plugin" / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "index.html").write_text("<h1>Hi</h1>", encoding="utf-8")

    session = make_session(tmp_path, monkeypatch, tmp_path)
    mod = _bridge_module()

    session.plugins.install(PluginManifest(
        name="cmdplugin", capabilities=("ui",), source_dir=str(tmp_path / "plugin"),
        ui_block=UIExtensionBlock(api_version=1, scopes=("ui",), extensions=(
            UIExtension(type="command", id="greet", scopes=("ui",), meta={"title": "Поздороваться"}),
        )),
    ))

    commands = await mod._handle(session, "plugin_commands", {})
    assert commands == [{"plugin": "cmdplugin", "id": "greet", "title": "Поздороваться"}]

    html = await mod._handle(session, "plugin_ui_html", {"name": "cmdplugin"})
    assert html == {"html": "<h1>Hi</h1>"}

    # A plugin that declares fs but reads a missing file gets a structured error.
    session.plugins.install(PluginManifest(
        name="fsplugin", capabilities=("ui",),
        ui_block=UIExtensionBlock(api_version=1, scopes=("fs",), extensions=()),
    ))
    missing = await mod._handle(session, "plugin_host", {
        "id": "7", "plugin": "fsplugin", "method": "fs.read", "params": {"path": "nope.txt"},
    })
    assert missing["ok"] is False
    assert "FileNotFoundError" in missing["error"]
