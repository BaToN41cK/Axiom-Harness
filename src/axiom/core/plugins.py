"""Plugin SDK (п.20): manifest + capabilities + real folder-based loading.

AXIOM loads user plugins from ``~/.axiom/plugins/<name>/``.  Each plugin folder
contains:

  * ``manifest.json`` — required, validated against :data:`PLUGIN_API_VERSION`;
  * an entry module (``plugin.py`` by default, overridable via ``manifest.entry``)
    that contributes *real* tools to the agent.

The entry module contributes tools through one of two contracts:

  * ``def register(registry: ToolRegistry) -> None`` — imperative, most flexible;
  * ``TOOLS: list[ToolDefinition]`` + ``HANDLERS: dict[str, callable]`` — declarative.

Plugins run **in-process** with AXIOM's own privileges.  There is no sandbox in
v0 — only install plugins you trust.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from re import fullmatch
from types import ModuleType
from typing import Any

from axiom.core.config import axiom_home

#: The plugin contract version.  A plugin whose ``api_version`` differs from
#: this value is rejected at load/install time — never silently executed.
PLUGIN_API_VERSION = 1

#: Default entry-module filename inside a plugin folder.
DEFAULT_ENTRY = "plugin.py"


class PluginLoadError(Exception):
    """A plugin could not be validated, imported or loaded."""


@dataclass
class PluginManifest:
    """Declarative description of one installed plugin."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    #: Plugin API version this plugin was written against.
    api_version: int = PLUGIN_API_VERSION
    capabilities: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    ui: tuple[str, ...] = ()
    #: Entry module filename inside the plugin folder.
    entry: str = DEFAULT_ENTRY
    #: Persisted enable state — a disabled plugin is kept but not loaded.
    enabled: bool = True
    #: Absolute path of the plugin folder on disk (set for folder plugins).
    source_dir: str | None = None
    #: Shipped with AXIOM itself (installable from the bundled catalogue).
    bundled: bool = False
    #: Long-form markdown documentation read from README.md if present.
    readme: str = ""

    def validate(self) -> None:
        """Reject unusable manifests before any code is imported."""
        if not self.name or not str(self.name).strip():
            raise PluginLoadError("Plugin manifest is missing a name")
        if fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", self.name) is None:
            raise PluginLoadError(
                "Plugin name must contain only letters, numbers, '.', '_' or '-'")
        entry_path = Path(self.entry)
        if entry_path.is_absolute() or ".." in entry_path.parts:
            raise PluginLoadError("Plugin entry must stay inside the plugin folder")
        if self.api_version != PLUGIN_API_VERSION:
            raise PluginLoadError(
                f"Plugin '{self.name}' targets API v{self.api_version}, "
                f"but AXIOM supports v{PLUGIN_API_VERSION}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "api_version": self.api_version,
            "capabilities": list(self.capabilities),
            "tools": list(self.tools),
            "providers": list(self.providers),
            "skills": list(self.skills),
            "events": list(self.events),
            "ui": list(self.ui),
            "entry": self.entry,
            "enabled": self.enabled,
            "source_dir": self.source_dir,
            "bundled": self.bundled,
            "readme": self.readme,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginManifest:
        def _tuple(key: str) -> tuple[str, ...]:
            value = data.get(key) or ()
            return tuple(str(item) for item in value) if isinstance(value, (list, tuple)) else ()

        return cls(
            name=str(data.get("name") or ""),
            version=str(data.get("version") or "0.1.0"),
            description=str(data.get("description") or ""),
            author=str(data.get("author") or ""),
            api_version=int(data.get("api_version") or PLUGIN_API_VERSION),
            capabilities=_tuple("capabilities"),
            tools=_tuple("tools"),
            providers=_tuple("providers"),
            skills=_tuple("skills"),
            events=_tuple("events"),
            ui=_tuple("ui"),
            entry=str(data.get("entry") or DEFAULT_ENTRY),
            enabled=bool(data.get("enabled", True)),
            source_dir=str(data["source_dir"]) if data.get("source_dir") else None,
            bundled=bool(data.get("bundled", False)),
            readme=str(data.get("readme") or ""),
        )

    def row(self) -> dict[str, Any]:
        """UI-friendly dict used by the bridge and TUI panels."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "api_version": self.api_version,
            "enabled": self.enabled,
            "capabilities": list(self.capabilities),
            "tools": list(self.tools),
            "providers": list(self.providers),
            "skills": list(self.skills),
            "source_dir": self.source_dir,
            "bundled": self.bundled,
            "readme": self.readme,
        }


@dataclass
class LoadedPlugin:
    """A plugin whose entry module is imported and whose tools are live."""

    manifest: PluginManifest
    module: ModuleType | None = None
    tool_names: tuple[str, ...] = field(default_factory=tuple)


def plugins_dir() -> Path:
    """Root directory where plugin folders live (``AXIOM_HOME`` aware)."""
    return axiom_home() / "plugins"


def bundled_dir() -> Path:
    """Directory with built-in plugins shipped inside the AXIOM package."""
    return Path(__file__).resolve().parent.parent / "plugins" / "bundled"


class PluginRegistry:
    """In-memory registry + persisted enabled/installed plugin state."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginManifest] = {}

    def install(self, manifest: PluginManifest) -> bool:
        """Register a manifest. Returns ``True`` if newly added, ``False`` if updated."""
        manifest.validate()
        existed = manifest.name in self._plugins
        self._plugins[manifest.name] = manifest
        return not existed

    def remove(self, name: str) -> bool:
        return self._plugins.pop(name, None) is not None

    def toggle(self, name: str, enabled: bool) -> bool:
        """Flip the persisted enable state; returns ``False`` for unknown names."""
        manifest = self._plugins.get(name)
        if manifest is None:
            return False
        manifest.enabled = bool(enabled)
        return True

    def get(self, name: str) -> PluginManifest | None:
        return self._plugins.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._plugins

    def list(self, *, enabled_only: bool = False) -> list[PluginManifest]:
        values = list(self._plugins.values())
        if enabled_only:
            values = [m for m in values if m.enabled]
        return values

    def save(self, path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = [m.to_dict() for m in self._plugins.values()]
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path) -> None:
        target = Path(path)
        if not target.exists():
            self._plugins.clear()
            return
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, list):
            return
        self._plugins.clear()
        for item in raw:
            if isinstance(item, dict) and item.get("name"):
                manifest = PluginManifest.from_dict(item)
                # A corrupt/outdated manifest must never crash startup.
                try:
                    manifest.validate()
                except PluginLoadError:
                    continue
                self._plugins[str(item["name"])] = manifest


class PluginManager:
    """Disk-backed plugin lifecycle: discover, install, load, toggle, remove.

    ``load``/``unload`` register and unregister real tool handlers against the
    session's :class:`~axiom.core.tools.registry.ToolRegistry`, so a loaded
    plugin's tools become callable by the model immediately.
    """

    def __init__(self, registry: PluginRegistry | None = None, root: str | Path | None = None) -> None:
        self.registry = registry or PluginRegistry()
        self._root: Path | None = Path(root) if root is not None else None
        self._loaded: dict[str, LoadedPlugin] = {}

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else plugins_dir()

    def discover(self) -> list[str]:
        """Scan the plugins directory for folders that are not yet registered."""
        if not self.root.exists():
            return []
        found: list[str] = []
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir():
                continue
            manifest_path = folder / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = self._read_manifest(manifest_path)
            except PluginLoadError:
                continue
            manifest.source_dir = str(folder)
            if manifest.name in self.registry:
                existing = self.registry.get(manifest.name)
                if existing is not None and existing.source_dir is None:
                    existing.source_dir = str(folder)
                continue
            self.registry.install(manifest)
            found.append(manifest.name)
        if found:
            self._save()
        return found

    def install_from_folder(self, source: str | Path, session=None) -> tuple[PluginManifest, str]:
        """Install a plugin folder into the managed plugins directory (idempotent).

        If a plugin is already live in ``session``, its old tools/module are
        unloaded before the folder is replaced and the new version is loaded.
        """
        src = Path(source)
        if not src.is_dir():
            raise PluginLoadError(f"Plugin folder does not exist: {src}")
        manifest_path = src / "manifest.json"
        if not manifest_path.exists():
            raise PluginLoadError(f"No manifest.json found in {src}")
        manifest = self._read_manifest(manifest_path)
        manifest.validate()

        destination = self.root / manifest.name
        previous = self.registry.get(manifest.name)
        status = "updated" if previous is not None else "installed"
        if previous is not None:
            manifest.enabled = previous.enabled
        if session is not None:
            self.unload(manifest.name, session)

        self._copy_folder(src, destination)
        manifest.source_dir = str(destination)
        self.registry.install(manifest)
        self._save()
        if session is not None and manifest.enabled:
            self.load(manifest.name, session)
        return manifest, status

    def load(self, name: str, session) -> list[str]:
        """Import a plugin's entry module and register its real tools."""
        manifest = self.registry.get(name)
        if manifest is None:
            raise PluginLoadError(f"Unknown plugin: {name}")
        manifest.validate()
        if not manifest.enabled:
            raise PluginLoadError(f"Plugin '{name}' is disabled")
        if name in self._loaded:
            return list(self._loaded[name].tool_names)

        folder = Path(manifest.source_dir) if manifest.source_dir else self.root / name
        entry_path = folder / (manifest.entry or DEFAULT_ENTRY)
        if not entry_path.exists():
            # A manifest-only plugin (skills/capabilities) has no code to run.
            self._loaded[name] = LoadedPlugin(manifest=manifest)
            return []

        module = self._import_entry(name, entry_path, folder)
        registry = getattr(session, "tools", None)
        if registry is None:
            raise PluginLoadError("Session has no tool registry to register into")

        before = set(registry.names)
        try:
            registered = self._apply(module, manifest, registry)
        except Exception as exc:
            raise PluginLoadError(f"Plugin '{name}' failed to register: {exc}") from exc

        tool_names = tuple(sorted(set(registered) | (set(registry.names) - before)))
        self._loaded[name] = LoadedPlugin(manifest=manifest, module=module, tool_names=tool_names)
        return list(tool_names)

    def unload(self, name: str, session) -> bool:
        """Unregister a plugin's tools and drop its imported module."""
        entry = self._loaded.pop(name, None)
        if entry is None:
            return False
        registry = getattr(session, "tools", None)
        if registry is not None:
            for tool_name in entry.tool_names:
                registry.unregister(tool_name)
        if entry.module is not None:
            sys.modules.pop(entry.module.__name__, None)
        return True

    # ---------------------------------------------------------- bundled plugins

    def bundled_manifests(self, bundled_root: str | Path | None = None) -> list[PluginManifest]:
        """Built-in plugins shipped with AXIOM that are not installed yet.

        Returns validated manifests for every folder in the bundled catalogue
        whose name is not already present in the registry, flagged
        ``bundled=True`` so frontends can render an "install" action.
        """
        return [m for m in self._bundled_catalogue(bundled_root) if m.name not in self.registry]

    def _bundled_catalogue(self, bundled_root: str | Path | None) -> list[PluginManifest]:
        """Validated manifests of every folder in the bundled catalogue."""
        root = Path(bundled_root) if bundled_root is not None else bundled_dir()
        if not root.exists():
            return []
        available: list[PluginManifest] = []
        for folder in sorted(root.iterdir()):
            if not folder.is_dir():
                continue
            manifest_path = folder / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = self._read_manifest(manifest_path)
                manifest.validate()
            except PluginLoadError:
                continue
            manifest.bundled = True
            manifest.source_dir = str(folder)
            available.append(manifest)
        return available

    def install_bundled(
        self,
        name: str,
        session=None,
        bundled_root: str | Path | None = None,
    ) -> tuple[PluginManifest, str]:
        """Install a built-in plugin into the managed plugins directory.

        Copies the bundled folder into ``~/.axiom/plugins/<name>/``, persists
        the manifest (with ``bundled=True``) and loads it into ``session``
        when the plugin is enabled. Idempotent: re-installing updates in place.
        """
        target = next(
            (m for m in self._bundled_catalogue(bundled_root) if m.name == name),
            None,
        )
        if target is None:
            raise PluginLoadError(f"Unknown bundled plugin: {name}")
        source = Path(target.source_dir)
        destination = self.root / name
        previous = self.registry.get(name)
        status = "updated" if previous is not None else "installed"
        if previous is not None:
            target.enabled = previous.enabled
        if session is not None:
            self.unload(name, session)
        self._copy_folder(source, destination)
        target.source_dir = str(destination)
        target.bundled = True
        self.registry.install(target)
        self._save()
        if session is not None and target.enabled:
            self.load(name, session)
        return target, status

    def load_enabled(self, session) -> list[str]:
        """Load every enabled plugin; failures are reported but never fatal."""
        loaded: list[str] = []
        for manifest in self.registry.list(enabled_only=True):
            try:
                self.load(manifest.name, session)
                loaded.append(manifest.name)
            except PluginLoadError:
                continue
        return loaded

    def toggle(self, name: str, enabled: bool, session=None) -> bool:
        """Flip a plugin's enable state, persist it, and apply it immediately."""
        manifest = self.registry.get(name)
        if manifest is None:
            return False
        if enabled == manifest.enabled:
            return True
        manifest.enabled = bool(enabled)
        self._save()
        if session is not None:
            if enabled:
                try:
                    self.load(name, session)
                except PluginLoadError:
                    pass
            else:
                self.unload(name, session)
        return True

    def remove(self, name: str, session=None) -> bool:
        """Unregister tools, drop the module, delete the folder, forget the plugin."""
        if name not in self.registry:
            return False
        if session is not None:
            self.unload(name, session)
        self.registry.remove(name)
        self._save()
        folder = self.root / name
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        return True

    def _read_manifest(self, path: Path) -> PluginManifest:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PluginLoadError(f"Cannot read manifest {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise PluginLoadError(f"Manifest {path} must be a JSON object")

        # Try to load README.md from the same folder
        readme_path = path.parent / "README.md"
        if readme_path.exists():
            try:
                raw["readme"] = readme_path.read_text(encoding="utf-8")
            except OSError:
                pass  # README is optional; if unreadable, leave empty

        return PluginManifest.from_dict(raw)

    @staticmethod
    def _copy_folder(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_name(f".{destination.name}.installing")
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(source, staging)
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        staging.replace(destination)

    def _import_entry(self, name: str, entry_path: Path, folder: Path) -> ModuleType:
        module_name = f"axiom_plugin_{name}"
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Cannot create a loader for {entry_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        added_path = str(folder)
        if added_path not in sys.path:
            sys.path.insert(0, added_path)
        try:
            spec.loader.exec_module(module)
        finally:
            try:
                sys.path.remove(added_path)
            except ValueError:
                pass
        return module

    @staticmethod
    def _apply(module: ModuleType, manifest: PluginManifest, registry) -> list[str]:
        register = getattr(module, "register", None)
        if callable(register):
            register(registry)
            return []

        tools = getattr(module, "TOOLS", None)
        handlers = getattr(module, "HANDLERS", None)
        if tools is None and handlers is None:
            raise PluginLoadError(
                f"Plugin '{manifest.name}' entry module defines neither "
                "`register(registry)` nor `TOOLS`/`HANDLERS`"
            )
        if not isinstance(tools, (list, tuple)):
            raise PluginLoadError(f"Plugin '{manifest.name}': TOOLS must be a list")
        if not isinstance(handlers, dict):
            raise PluginLoadError(f"Plugin '{manifest.name}': HANDLERS must be a dict")

        registered: list[str] = []
        for definition in tools:
            name = getattr(definition, "name", None)
            if not name:
                continue
            handler = handlers.get(name)
            if handler is None:
                raise PluginLoadError(
                    f"Plugin '{manifest.name}': no handler for tool '{name}'"
                )
            registry.register(definition, handler)
            registered.append(name)
        return registered

    def _save(self) -> None:
        path = self.root.parent / "plugins.json"
        try:
            self.registry.save(path)
        except OSError:
            pass
