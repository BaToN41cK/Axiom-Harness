"""Plugin Manager v0: реальная загрузка плагинов из папок, персист, toggle.

Проверяем, что пользователь действительно может «подгрузить свой плагин»:
папка с manifest.json + plugin.py ставится в каталог плагинов, её код
импортируется, а объявленные инструменты регистрируются в ToolRegistry.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from axiom.core.plugins import (
    DEFAULT_ENTRY,
    PLUGIN_API_VERSION,
    PluginLoadError,
    PluginManager,
    PluginManifest,
    PluginRegistry,
)
from axiom.core.tools.registry import ToolRegistry


class _FakeSession:
    """Минимальный «сеанс»: только реестр инструментов, нужный менеджеру."""

    def __init__(self) -> None:
        self.tools = ToolRegistry()


def _plugin_folder(root, name="demo", *, api_version=PLUGIN_API_VERSION, body=None) -> str:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": "1.2.3",
        "description": "Demo plugin",
        "author": "tester",
        "api_version": api_version,
        "capabilities": ["tools"],
        "tools": ["hello"],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if body is None:
        body = (
            "from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult\n"
            "TOOLS = [ToolDefinition(name='hello', description='Say hello',\n"
            "                        permission=ToolPermission.ALWAYS)]\n"
            "async def hello(name: str = 'world'):\n"
            "    return ToolResult(name='hello', ok=True, content=f'Hello {name}')\n"
            "HANDLERS = {'hello': hello}\n"
        )
    (folder / DEFAULT_ENTRY).write_text(body, encoding="utf-8")
    return str(folder)


# --------------------------------------------------------------- manifest


def test_manifest_validate_rejects_api_mismatch():
    with pytest.raises(PluginLoadError):
        PluginManifest(name="x", api_version=99).validate()


def test_manifest_validate_rejects_empty_name():
    with pytest.raises(PluginLoadError):
        PluginManifest(name="").validate()


def test_manifest_roundtrip_preserves_new_fields():
    manifest = PluginManifest(
        name="x",
        version="2.0",
        author="alice",
        enabled=False,
        skills=("git",),
        source_dir="/tmp/x",
    )
    clone = PluginManifest.from_dict(manifest.to_dict())
    assert clone.name == "x"
    assert clone.author == "alice"
    assert clone.enabled is False
    assert clone.skills == ("git",)
    assert clone.source_dir == "/tmp/x"


# ---------------------------------------------------------------- registry


def test_registry_toggle_persists_enabled_state(tmp_path):
    reg = PluginRegistry()
    reg.install(PluginManifest(name="demo"))
    assert reg.toggle("demo", False) is True
    assert reg.toggle("missing", True) is False

    path = tmp_path / "plugins.json"
    reg.save(path)
    fresh = PluginRegistry()
    fresh.load(path)
    assert fresh.get("demo") is not None
    assert fresh.get("demo").enabled is False


def test_registry_install_is_idempotent():
    reg = PluginRegistry()
    assert reg.install(PluginManifest(name="demo", version="1.0")) is True
    assert reg.install(PluginManifest(name="demo", version="2.0")) is False
    assert len(reg.list()) == 1
    assert reg.get("demo").version == "2.0"


# --------------------------------------------------------------- manager


def test_install_from_folder_is_idempotent(tmp_path):
    src = _plugin_folder(tmp_path / "src")
    manager = PluginManager(root=tmp_path / "plugins")

    _manifest, status = manager.install_from_folder(src)
    assert status == "installed"
    assert (manager.root / "demo" / "manifest.json").exists()

    # Повторная установка той же папки = обновление, а не дубликат.
    _, status2 = manager.install_from_folder(src)
    assert status2 == "updated"
    assert len(manager.registry.list()) == 1


def test_install_from_folder_rejects_wrong_api(tmp_path):
    src = _plugin_folder(tmp_path / "src", api_version=99)
    manager = PluginManager(root=tmp_path / "plugins")
    with pytest.raises(PluginLoadError):
        manager.install_from_folder(src)


def test_install_from_folder_requires_manifest(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    manager = PluginManager(root=tmp_path / "plugins")
    with pytest.raises(PluginLoadError):
        manager.install_from_folder(src)


def test_load_registers_real_tools_and_unload_removes_them(tmp_path):
    src = _plugin_folder(tmp_path / "src")
    manager = PluginManager(root=tmp_path / "plugins")
    manager.install_from_folder(src)
    session = _FakeSession()

    names = manager.load("demo", session)
    assert names == ["hello"]
    assert "hello" in session.tools.names
    result = asyncio.run(session.tools.execute("hello", {"name": "Al"}))
    assert result.ok is True
    assert result.content == "Hello Al"

    assert manager.unload("demo", session) is True
    assert "hello" not in session.tools.names
    assert manager.unload("demo", session) is False


def test_load_disabled_plugin_is_refused(tmp_path):
    src = _plugin_folder(tmp_path / "src")
    manager = PluginManager(root=tmp_path / "plugins")
    manager.install_from_folder(src)
    manager.registry.toggle("demo", False)

    session = _FakeSession()
    with pytest.raises(PluginLoadError):
        manager.load("demo", session)


def test_toggle_applies_immediately(tmp_path):
    src = _plugin_folder(tmp_path / "src")
    manager = PluginManager(root=tmp_path / "plugins")
    manager.install_from_folder(src)
    session = _FakeSession()

    manager.load("demo", session)
    assert "hello" in session.tools.names

    assert manager.toggle("demo", False, session=session) is True
    assert "hello" not in session.tools.names

    assert manager.toggle("demo", True, session=session) is True
    assert "hello" in session.tools.names


def test_discover_registers_manually_dropped_folders(tmp_path):
    manager = PluginManager(root=tmp_path / "plugins")
    folder = tmp_path / "plugins" / "manual"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(
        json.dumps({"name": "manual", "version": "0.1.0"}), encoding="utf-8"
    )

    discovered = manager.discover()
    assert discovered == ["manual"]
    assert "manual" in manager.registry
    # Повторный discover ничего не добавляет.
    assert manager.discover() == []


def test_remove_deletes_folder_and_forgets_plugin(tmp_path):
    src = _plugin_folder(tmp_path / "src")
    manager = PluginManager(root=tmp_path / "plugins")
    manager.install_from_folder(src)
    session = _FakeSession()
    manager.load("demo", session)

    assert manager.remove("demo", session=session) is True
    assert "demo" not in manager.registry
    assert not (manager.root / "demo").exists()
    assert "hello" not in session.tools.names
    assert manager.remove("demo") is False


def test_manifest_only_plugin_loads_without_code(tmp_path):
    folder = tmp_path / "plugins" / "skills-only"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(
        json.dumps({"name": "skills-only", "skills": ["git"]}), encoding="utf-8"
    )
    manager = PluginManager(root=tmp_path / "plugins")
    manager.discover()
    session = _FakeSession()
    assert manager.load("skills-only", session) == []


def test_register_hook_contract(tmp_path):
    body = (
        "from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult\n"
        "def register(registry):\n"
        "    async def ping():\n"
        "        return ToolResult(name='ping', ok=True, content='pong')\n"
        "    registry.register(ToolDefinition(name='ping', description='p',\n"
        "                                    permission=ToolPermission.ALWAYS), ping)\n"
    )
    src = _plugin_folder(tmp_path / "src", body=body)
    manager = PluginManager(root=tmp_path / "plugins")
    manager.install_from_folder(src)
    session = _FakeSession()
    assert manager.load("demo", session) == ["ping"]
    assert "ping" in session.tools.names


# --------------------------------------------------------------- bundled plugins


def test_bundled_manifests_lists_not_installed_builtins(tmp_path):
    bundled_root = tmp_path / "bundled"
    _plugin_folder(bundled_root, name="calc")
    _plugin_folder(bundled_root, name="notes")
    manager = PluginManager(root=tmp_path / "plugins")

    available = manager.bundled_manifests(bundled_root=bundled_root)
    assert [m.name for m in available] == ["calc", "notes"]
    assert all(m.bundled for m in available)


def test_bundled_manifests_excludes_installed(tmp_path):
    bundled_root = tmp_path / "bundled"
    _plugin_folder(bundled_root, name="calc")
    manager = PluginManager(root=tmp_path / "plugins")
    session = _FakeSession()
    manager.install_bundled("calc", session=session, bundled_root=bundled_root)

    assert manager.bundled_manifests(bundled_root=bundled_root) == []


def test_install_bundled_copies_and_loads_tools(tmp_path):
    bundled_root = tmp_path / "bundled"
    _plugin_folder(bundled_root, name="calc")
    manager = PluginManager(root=tmp_path / "plugins")
    session = _FakeSession()

    manifest, status = manager.install_bundled("calc", session=session, bundled_root=bundled_root)
    assert status == "installed"
    assert manifest.bundled is True
    assert (manager.root / "calc" / DEFAULT_ENTRY).exists()
    assert "calc" in manager.registry
    assert "hello" in session.tools.names
    result = asyncio.run(session.tools.execute("hello", {"name": "Al"}))
    assert result.ok is True
    assert result.content == "Hello Al"


def test_install_bundled_is_idempotent(tmp_path):
    bundled_root = tmp_path / "bundled"
    _plugin_folder(bundled_root, name="calc")
    manager = PluginManager(root=tmp_path / "plugins")
    session = _FakeSession()

    manager.install_bundled("calc", session=session, bundled_root=bundled_root)
    manifest, status = manager.install_bundled("calc", session=session, bundled_root=bundled_root)
    assert status == "updated"
    assert manifest.bundled is True
    assert "hello" in session.tools.names


def test_install_bundled_unknown_name_raises(tmp_path):
    manager = PluginManager(root=tmp_path / "plugins")
    with pytest.raises(PluginLoadError):
        manager.install_bundled("missing", bundled_root=tmp_path / "bundled")


def test_remove_bundled_plugin_returns_to_catalogue(tmp_path):
    bundled_root = tmp_path / "bundled"
    _plugin_folder(bundled_root, name="calc")
    manager = PluginManager(root=tmp_path / "plugins")
    session = _FakeSession()
    manager.install_bundled("calc", session=session, bundled_root=bundled_root)

    assert manager.remove("calc", session=session) is True
    assert "hello" not in session.tools.names
    available = manager.bundled_manifests(bundled_root=bundled_root)
    assert [m.name for m in available] == ["calc"]


# ------------------------------------------------------------ readme loading


def test_plugin_loads_readme_from_folder(tmp_path):
    """README.md в папке плагина автоматически загружается в manifest.readme."""
    folder = tmp_path / "demo"
    folder.mkdir()
    manifest = {"name": "demo", "version": "1.0", "api_version": PLUGIN_API_VERSION}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    readme_text = "# Demo Plugin\n\nThis is a test plugin with README.\n"
    (folder / "README.md").write_text(readme_text, encoding="utf-8")
    (folder / DEFAULT_ENTRY).write_text("# empty", encoding="utf-8")

    manager = PluginManager(root=tmp_path / "plugins")
    manager.install_from_folder(folder)
    loaded = manager.registry.get("demo")
    assert loaded is not None
    assert loaded.readme == readme_text


def test_plugin_readme_is_optional(tmp_path):
    """Если README.md отсутствует, manifest.readme остаётся пустой строкой."""
    src = _plugin_folder(tmp_path, name="no_readme")
    manager = PluginManager(root=tmp_path / "plugins")
    manager.install_from_folder(src)
    loaded = manager.registry.get("no_readme")
    assert loaded is not None
    assert loaded.readme == ""


def test_bundled_plugin_carries_readme(tmp_path):
    """Bundled-плагин с README доступен в каталоге вместе с документацией."""
    bundled_root = tmp_path / "bundled"
    folder = bundled_root / "demo"
    folder.mkdir(parents=True)
    manifest = {"name": "demo", "version": "1.0", "api_version": PLUGIN_API_VERSION, "tools": ["hello"]}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / DEFAULT_ENTRY).write_text("TOOLS = []; HANDLERS = {}", encoding="utf-8")
    readme_text = "# Bundled Demo\n\nBundled plugin example.\n"
    (folder / "README.md").write_text(readme_text, encoding="utf-8")

    manager = PluginManager(root=tmp_path / "plugins")
    available = manager.bundled_manifests(bundled_root=bundled_root)
    assert len(available) == 1
    assert available[0].name == "demo"
    assert available[0].readme == readme_text


def test_plugin_row_includes_readme(tmp_path):
    """Метод manifest.row() включает поле readme для UI."""
    folder = tmp_path / "demo"
    folder.mkdir()
    manifest = {"name": "demo", "version": "1.0", "api_version": PLUGIN_API_VERSION}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    readme_text = "Documentation here.\n"
    (folder / "README.md").write_text(readme_text, encoding="utf-8")
    (folder / DEFAULT_ENTRY).write_text("# empty", encoding="utf-8")

    manager = PluginManager(root=tmp_path / "plugins")
    manager.install_from_folder(folder)
    loaded = manager.registry.get("demo")
    row = loaded.row()
    assert row["readme"] == readme_text


