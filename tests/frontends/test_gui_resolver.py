"""Pure path resolver of the GUI launcher (frontends/gui/main.py)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import axiom.frontends.gui.main as gui

# --------------------------------------------------------------- _desktop_dirs


def test_desktop_dirs_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXIOM_DESKTOP_ROOT", str(tmp_path))
    (tmp_path / "desktop").mkdir()
    dirs = gui._desktop_dirs()
    assert dirs[0] == tmp_path / "desktop"
    # No duplicates even when cwd equals the candidate.
    assert len(dirs) == len(set(dirs))


def test_desktop_dirs_falls_back_to_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AXIOM_DESKTOP_ROOT", raising=False)
    assert (gui._project_root() / "desktop") in gui._desktop_dirs()


# ------------------------------------------------------------- exe resolution


def _make_exe(root: Path, name: str = "axiom-desktop.exe") -> Path:
    exe = root / "src-tauri" / "target" / "release" / name
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    return exe


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the resolver away from the real repository desktop/."""
    monkeypatch.setenv("AXIOM_DESKTOP_ROOT", str(tmp_path))
    monkeypatch.setattr(gui, "_project_root", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)


def test_finds_fresh_exe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(tmp_path, monkeypatch)
    desktop = tmp_path / "desktop"
    (desktop / "src").mkdir(parents=True)
    (desktop / "src-tauri").mkdir(parents=True)
    (desktop / "src" / "index.tsx").write_text("x", encoding="utf-8")
    exe = _make_exe(desktop)
    os.utime(exe, (time.time() + 5, time.time() + 5))  # newer than any source
    assert gui._find_built_exe() == exe


def test_stale_exe_is_not_used_when_sources_are_newer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    desktop = tmp_path / "desktop"
    (desktop / "src").mkdir(parents=True)
    (desktop / "src-tauri").mkdir(parents=True)
    exe = _make_exe(desktop)
    os.utime(exe, (1, 1))  # ancient build
    (desktop / "src" / "index.tsx").write_text("x", encoding="utf-8")  # newer source
    assert gui._find_built_exe() is None


def test_fallback_finds_even_stale_exe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(tmp_path, monkeypatch)
    desktop = tmp_path / "desktop"
    (desktop / "src").mkdir(parents=True)
    (desktop / "src-tauri").mkdir(parents=True)
    exe = _make_exe(desktop)
    os.utime(exe, (1, 1))
    (desktop / "src" / "index.tsx").write_text("x", encoding="utf-8")
    assert gui._find_built_exe_any() == exe


def test_no_exe_anywhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert gui._find_built_exe() is None
    assert gui._find_built_exe_any() is None


def test_gui_launcher_uses_hidden_non_console_flags() -> None:
    if sys.platform == "win32":
        assert gui._HIDDEN == subprocess.CREATE_NO_WINDOW
    else:
        assert gui._HIDDEN == 0


def test_rust_target_uses_msvc_architecture() -> None:
    assert gui._rust_target_triple("AMD64") == "x86_64-pc-windows-msvc"
    assert gui._rust_target_triple("ARM64") == "aarch64-pc-windows-msvc"


def test_system_proxy_is_passed_to_rustup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setattr(gui.urllib.request, "getproxies", lambda: {
        "http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080",
    })
    env: dict[str, str] = {}

    gui._apply_system_proxy(env)

    assert env["http_proxy"] == "http://127.0.0.1:8080"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:8080"


def test_existing_rust_skips_installer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui, "_IS_WINDOWS", True)
    monkeypatch.setattr(gui, "_find_rust_tools", lambda: ("cargo.exe", "rustc.exe"))
    monkeypatch.setattr(gui, "_version_ok", lambda _: (True, "version"))
    monkeypatch.setattr(gui, "_rust_host_ok", lambda _: True)
    monkeypatch.setattr(gui, "_install_rust_toolchain", lambda *_: pytest.fail("unexpected install"))
    assert gui._ensure_rust_toolchain() is True


def test_dev_launcher_waits_for_tauri_and_frontend(tmp_path: Path, monkeypatch, capsys) -> None:
    class RunningProcess:
        def poll(self) -> None:
            return None

    log = tmp_path / "tauri_dev.log"
    log.write_text(
        "\x1b[1m\x1b[92m Running\x1b[0m `target\\debug\\axiom-desktop.exe`\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gui, "_frontend_dev_server_ready", lambda: True)

    started, error = gui._wait_for_dev_start(RunningProcess(), log, 0, timeout=1)

    assert started
    assert error == ""
    assert "axiom-desktop.exe" in capsys.readouterr().err


def test_dev_launcher_reports_rust_compile_error(tmp_path: Path, capsys) -> None:
    class RunningProcess:
        def poll(self) -> None:
            return None

    log = tmp_path / "tauri_dev.log"
    log.write_text(
        "error[E0658]: unstable feature\nerror: could not compile `axiom-desktop`\n",
        encoding="utf-8",
    )

    started, error = gui._wait_for_dev_start(RunningProcess(), log, 0, timeout=1)

    assert not started
    assert "с ошибкой" in error
    assert "error[E0658]" in capsys.readouterr().err


def test_frontend_probe_connects_directly_even_when_proxy_is_configured(monkeypatch) -> None:
    class FakeResponse:
        status = 200

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            assert (host, port) == ("127.0.0.1", 1420)
            assert timeout == 0.3

        def request(self, method: str, path: str) -> None:
            assert (method, path) == ("GET", "/")

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            pass

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setattr(gui.http.client, "HTTPConnection", FakeConnection)

    assert gui._frontend_dev_server_ready()


def test_missing_rust_installs_and_continues(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeWindow:
        def __init__(self) -> None:
            self.closed = False

        def status(self, _text: str) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(gui, "_IS_WINDOWS", True)
    monkeypatch.setattr(gui, "_find_rust_tools", lambda: (None, None))
    monkeypatch.setattr(gui, "_setup_log_path", lambda: tmp_path / "rust-install.log")
    monkeypatch.setattr(gui, "_SetupWindow", FakeWindow)
    monkeypatch.setattr(gui, "_native_message", lambda *_args, **_kwargs: pytest.fail("unexpected dialog"))
    installed: list[Path] = []
    monkeypatch.setattr(gui, "_install_rust_toolchain", lambda _window, log: installed.append(log))

    assert gui._ensure_rust_toolchain() is True
    assert installed == [tmp_path / "rust-install.log"]
