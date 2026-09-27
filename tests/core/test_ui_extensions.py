"""UI Extension Point Contract (W1.5): валидация версионированного ``ui``-блока.

Контракт определяет, как плагин декларирует UI-расширения (панели, команды,
настройки, рендереры, темы) до того, как в W3.1 появится настоящий
iframe/Worker-хост. Здесь проверяем, что пример манифеста и расширения
валидируются против контракта, а несовместимая версия отклоняется до импорта
кода плагина.
"""
from __future__ import annotations

import json

import pytest

from axiom.core.plugins import (
    PLUGIN_API_VERSION,
    UI_EXTENSION_API_VERSION,
    PluginLoadError,
    PluginManager,
    PluginManifest,
    UIExtension,
    UIExtensionBlock,
)

# Полный пример блока: по одной точке каждого из пяти разрешённых типов.
EXAMPLE_UI_BLOCK: dict = {
    "api_version": 1,
    "scopes": ["ui"],
    "extensions": [
        {"type": "panel", "id": "hello-panel", "meta": {"title": "Привет"}},
        {"type": "command", "id": "hello-command", "meta": {"title": "Поздороваться"}},
        {"type": "setting", "id": "hello-greeting", "meta": {"default": "Hi"}},
        {"type": "renderer", "id": "hello-renderer", "meta": {"mime": "application/json"}},
        {"type": "theme", "id": "hello-theme"},
    ],
}


# ------------------------------------------------------------- valid examples


def test_full_example_manifest_validates():
    """DoD: пример манифеста со всеми пятью типами расширений проходит контракт."""
    block = UIExtensionBlock.from_dict(EXAMPLE_UI_BLOCK)
    block.validate("demo")  # не бросает

    manifest = PluginManifest.from_dict(
        {
            "name": "demo",
            "api_version": PLUGIN_API_VERSION,
            "capabilities": ["tools", "ui"],
            "ui": EXAMPLE_UI_BLOCK,
        }
    )
    manifest.validate()
    assert manifest.ui_block is not None
    assert manifest.ui_block.api_version == UI_EXTENSION_API_VERSION
    assert manifest.ui_block.scopes == ("ui",)
    assert [extension.type for extension in manifest.ui_block.extensions] == [
        "panel",
        "command",
        "setting",
        "renderer",
        "theme",
    ]
    # Плоский список для UI выводится из структурированного блока.
    assert manifest.ui == ("panel", "command", "setting", "renderer", "theme")
    # meta передаётся без изменений и не интерпретируется ядром.
    assert manifest.ui_block.extensions[3].meta == {"mime": "application/json"}


def test_install_from_folder_accepts_valid_ui_block(tmp_path):
    """Реальный путь установки принимает валидный UI-блок."""
    folder = tmp_path / "uiplugin"
    folder.mkdir()
    manifest = {
        "name": "uiplugin",
        "version": "1.0.0",
        "api_version": PLUGIN_API_VERSION,
        "capabilities": ["ui"],
        "ui": EXAMPLE_UI_BLOCK,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    manager = PluginManager(root=tmp_path / "plugins")
    installed, status = manager.install_from_folder(folder)
    assert status == "installed"
    assert installed.ui_block is not None
    assert len(installed.ui_block.extensions) == 5



# ------------------------------------------------------ incompatible versions


def test_incompatible_ui_version_is_rejected():
    """Несовместимая версия UI-контракта отклоняется до импорта кода."""
    block = UIExtensionBlock(
        api_version=99,
        extensions=(UIExtension(type="panel", id="p1"),),
    )
    with pytest.raises(PluginLoadError, match="UI block targets API v99"):
        block.validate("demo")

    manifest = PluginManifest.from_dict(
        {
            "name": "demo",
            "api_version": PLUGIN_API_VERSION,
            "capabilities": ["ui"],
            "ui": {"api_version": 99, "extensions": [{"type": "panel", "id": "p1"}]},
        }
    )
    with pytest.raises(PluginLoadError, match="UI block targets API v99"):
        manifest.validate()


def test_install_from_folder_rejects_incompatible_ui_block(tmp_path):
    folder = tmp_path / "uiplugin"
    folder.mkdir()
    manifest = {
        "name": "uiplugin",
        "version": "1.0.0",
        "api_version": PLUGIN_API_VERSION,
        "capabilities": ["ui"],
        "ui": {
            "api_version": 99,
            "scopes": ["ui"],
            "extensions": [{"type": "panel", "id": "p1"}],
        },
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    manager = PluginManager(root=tmp_path / "plugins")
    with pytest.raises(PluginLoadError, match="UI block targets API v99"):
        manager.install_from_folder(folder)


# ------------------------------------------------------------- bad declarations


def test_unknown_extension_point_is_rejected():
    with pytest.raises(PluginLoadError, match="unknown UI extension point 'widget'"):
        UIExtensionBlock(extensions=(UIExtension(type="widget", id="w"),)).validate("demo")


def test_unknown_scope_is_rejected():
    with pytest.raises(PluginLoadError, match="unknown UI scopes"):
        UIExtensionBlock(scopes=("root",)).validate("demo")
    with pytest.raises(PluginLoadError, match="unknown scopes"):
        UIExtensionBlock(
            extensions=(UIExtension(type="panel", id="p", scopes=("network",)),)
        ).validate("demo")


def test_extension_requires_safe_id():
    with pytest.raises(PluginLoadError, match="missing an id"):
        UIExtensionBlock(extensions=(UIExtension(type="panel", id=""),)).validate("demo")
    with pytest.raises(PluginLoadError, match="only letters"):
        UIExtensionBlock(
            extensions=(UIExtension(type="panel", id="bad id!"),)
        ).validate("demo")


def test_ui_block_requires_ui_capability():
    manifest = PluginManifest.from_dict(
        {
            "name": "demo",
            "api_version": PLUGIN_API_VERSION,
            "capabilities": ["tools"],
            "ui": EXAMPLE_UI_BLOCK,
        }
    )
    with pytest.raises(PluginLoadError, match="no 'ui' capability"):
        manifest.validate()


# ------------------------------------------------------------------- round-trips


def test_manifest_roundtrip_preserves_ui_block():
    manifest = PluginManifest.from_dict({"name": "demo", "ui": EXAMPLE_UI_BLOCK})
    clone = PluginManifest.from_dict(manifest.to_dict())
    assert clone.ui_block is not None
    assert clone.ui_block.api_version == UI_EXTENSION_API_VERSION
    assert clone.ui_block.scopes == ("ui",)
    assert [(e.type, e.id) for e in clone.ui_block.extensions] == [
        ("panel", "hello-panel"),
        ("command", "hello-command"),
        ("setting", "hello-greeting"),
        ("renderer", "hello-renderer"),
        ("theme", "hello-theme"),
    ]
    assert clone.ui_block.extensions[2].meta == {"default": "Hi"}


def test_ui_block_roundtrip_is_stable():
    block = UIExtensionBlock.from_dict(EXAMPLE_UI_BLOCK)
    clone = UIExtensionBlock.from_dict(block.to_dict())
    assert clone == block


def test_legacy_ui_list_still_roundtrips():
    """Flat-список ``ui`` (как в v0) продолжает работать без контракта."""
    manifest = PluginManifest.from_dict({"name": "demo", "ui": ["panels", "themes"]})
    assert manifest.ui == ("panels", "themes")
    assert manifest.ui_block is None
    manifest.validate()  # legacy-список не валидируется и не ломает манифест
    clone = PluginManifest.from_dict(manifest.to_dict())
    assert clone.ui == ("panels", "themes")
    assert clone.ui_block is None


def test_row_exposes_ui_block_for_frontends():
    manifest = PluginManifest.from_dict(
        {
            "name": "demo",
            "api_version": PLUGIN_API_VERSION,
            "capabilities": ["ui"],
            "ui": EXAMPLE_UI_BLOCK,
        }
    )
    row = manifest.row()
    assert row["ui_block"] is not None
    assert row["ui_block"]["api_version"] == UI_EXTENSION_API_VERSION
    assert PluginManifest.from_dict({"name": "plain"}).row()["ui_block"] is None

