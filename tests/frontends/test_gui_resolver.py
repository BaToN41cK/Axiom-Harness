"""Pure path resolver of the GUI launcher (frontends/gui/main.py)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import axiom.frontends.gui.main as gui


def test_desktop_builds_frontend_instead_of_starting_a_dev_server() -> None:
    """No dev-server URL/port is configured: Tauri builds and serves ``dist``.

    There is no local dev server and no fixed port to race on; ``tauri dev``
    builds the frontend with Vite (watch mode) and serves the bundled assets
    with its built-in dev server.
    """
    root = gui._project_root()
    config = json.loads(
        (root / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )
    before_dev = config["build"]["beforeDevCommand"]
    assert "build" in before_dev  # vite build --watch, not a dev server
    assert "1420" not in before_dev
    assert "devUrl" not in config["build"]
    assert config["build"]["frontendDist"] == "../dist"

    shell = (root / "desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    assert "start_dev_server()" not in shell

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


def test_debug_exe_is_never_launched_without_embedded_frontend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    desktop = tmp_path / "desktop"
    (desktop / "src").mkdir(parents=True)
    (desktop / "src-tauri").mkdir(parents=True)
    debug = desktop / "src-tauri" / "target" / "debug" / "axiom-desktop.exe"
    debug.parent.mkdir(parents=True, exist_ok=True)
    debug.write_bytes(b"MZ")
    os.utime(debug, (time.time() + 5, time.time() + 5))
    assert gui._find_built_exe() is None


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


def test_launcher_has_no_dev_server_dependency() -> None:
    """The normal launch path never touches a dev server URL or fixed port."""
    src = (
        gui._project_root() / "src" / "axiom" / "frontends" / "gui" / "main.py"
    ).read_text(encoding="utf-8")
    for token in (
        "1420", "devUrl", "strictPort", "_DEV_SERVER_PORT",
        "_frontend_dev_server_ready", "_reclaim_dev_port", "_wait_for_dev_start",
        "_port_in_use", "_listening_pids",
    ):
        assert token not in src
    for kept in (
        "_ensure_release", "_wait_for_stable_startup", "_run_dev_watch",
        "_axiom_already_running", "_launch_stable",
    ):
        assert kept in src


def test_vite_config_has_no_fixed_server_port() -> None:
    text = (gui._project_root() / "desktop" / "vite.config.ts").read_text(encoding="utf-8")
    assert "1420" not in text
    assert "strictPort" not in text


def test_stable_startup_treats_marker_file_as_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class AliveProcess:
        def poll(self) -> None:
            return None

    ready = tmp_path / "ready"
    ready.write_text("pid=1 startup_id=x", encoding="utf-8")
    assert gui._wait_for_stable_startup(AliveProcess(), ready) == ("ready", None)


def test_stable_startup_reports_early_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DeadProcess:
        def __init__(self, code: int) -> None:
            self._code = code

        def poll(self) -> int:
            return self._code

    monkeypatch.setattr(gui, "_READINESS_TIMEOUT_SECONDS", 30.0)
    ready = tmp_path / "ready"
    assert gui._wait_for_stable_startup(DeadProcess(1), ready) == ("exited", 1)
    assert gui._wait_for_stable_startup(DeadProcess(0), ready) == ("exited", 0)


def test_stable_startup_dead_process_with_marker_is_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The marker may be written microseconds before the process exits."""

    class DeadProcess:
        def poll(self) -> int:
            return 0

    monkeypatch.setattr(gui, "_READINESS_TIMEOUT_SECONDS", 30.0)
    ready = tmp_path / "ready"
    ready.write_text("pid=1 startup_id=x", encoding="utf-8")
    assert gui._wait_for_stable_startup(DeadProcess(), ready) == ("ready", None)


def test_stable_startup_times_out_without_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class AliveProcess:
        def poll(self) -> None:
            return None

    monkeypatch.setattr(gui, "_READINESS_TIMEOUT_SECONDS", 0.2)
    started = time.monotonic()
    assert gui._wait_for_stable_startup(AliveProcess(), tmp_path / "ready") == ("timeout", None)
    assert time.monotonic() - started >= 0.15


def test_run_logged_reports_build_failure(tmp_path: Path) -> None:
    import sys as _sys

    log = tmp_path / "build.log"
    code, _ = gui._run_logged(
        [_sys.executable, "-c", "raise SystemExit(3)"],
        cwd=tmp_path, log_path=log, timeout=60,
    )
    assert code == 3
    assert log.is_file()


def test_build_frontend_failure_blocks_shell_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    desktop = tmp_path / "desktop"
    (desktop / "src").mkdir(parents=True)
    (desktop / "src-tauri").mkdir(parents=True)
    (desktop / "dist").mkdir(parents=True)  # no index.html -> frontend stale
    monkeypatch.setattr(gui, "_node_executable", lambda: "node")
    monkeypatch.setattr(gui, "_ensure_frontend_deps", lambda _d, _n: (True, ""))
    monkeypatch.setattr(
        gui, "_build_frontend",
        lambda _d, _n, _l: (False, "Сборка frontend завершилась с ошибкой"),
    )
    called: list[str] = []
    monkeypatch.setattr(
        gui, "_build_shell_release",
        lambda _d, _l: called.append("shell") or (True, ""),
    )
    exe, error = gui._ensure_release(desktop)
    assert exe is None
    assert "frontend" in error
    assert called == []


def test_normal_launch_builds_release_and_starts_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    desktop = tmp_path / "desktop"
    (desktop / "src").mkdir(parents=True)
    (desktop / "src-tauri").mkdir(parents=True)
    (desktop / "package.json").write_text("{}", encoding="utf-8")
    exe = _make_exe(desktop)
    monkeypatch.setattr(gui, "_ensure_rust_toolchain", lambda: True)
    monkeypatch.setattr(gui, "_axiom_already_running", lambda: False)
    monkeypatch.setattr(gui, "_ensure_release", lambda _d: (exe, ""))
    launched: list[Path] = []
    monkeypatch.setattr(gui, "_launch_stable", lambda e: launched.append(e) or gui._EXIT_OK)
    assert gui.main([]) == gui._EXIT_OK
    assert launched == [exe]


def test_dev_flag_selects_watch_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    desktop = tmp_path / "desktop"
    (desktop / "src").mkdir(parents=True)
    (desktop / "src-tauri").mkdir(parents=True)
    (desktop / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gui, "_ensure_rust_toolchain", lambda: True)
    watched: list[Path] = []
    monkeypatch.setattr(gui, "_run_dev_watch", lambda d: watched.append(d) or gui._EXIT_OK)
    monkeypatch.setattr(
        gui, "_ensure_release",
        lambda _d: pytest.fail("stable build must not run in --dev mode"),
    )
    assert gui.main(["--dev"]) == gui._EXIT_OK
    assert watched == [desktop]


def test_build_failure_never_launches_stale_exe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate(tmp_path, monkeypatch)
    desktop = tmp_path / "desktop"
    (desktop / "src").mkdir(parents=True)
    (desktop / "src-tauri").mkdir(parents=True)
    (desktop / "package.json").write_text("{}", encoding="utf-8")
    _make_exe(desktop)  # stale exe exists but the build fails
    monkeypatch.setattr(gui, "_ensure_rust_toolchain", lambda: True)
    monkeypatch.setattr(gui, "_axiom_already_running", lambda: False)
    monkeypatch.setattr(gui, "_ensure_release", lambda _d: (None, "Сборка Rust завершилась с ошибкой"))
    monkeypatch.setattr(
        gui, "_launch_stable", lambda _e: pytest.fail("stale exe must not launch")
    )
    assert gui.main([]) == gui._EXIT_ERROR
    assert "Сборка Rust" in capsys.readouterr().err


def test_second_launch_reports_already_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate(tmp_path, monkeypatch)
    desktop = tmp_path / "desktop"
    (desktop / "src").mkdir(parents=True)
    (desktop / "src-tauri").mkdir(parents=True)
    (desktop / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gui, "_ensure_rust_toolchain", lambda: True)
    monkeypatch.setattr(gui, "_axiom_already_running", lambda: True)
    focused: list[bool] = []
    monkeypatch.setattr(gui, "_focus_axiom_window", lambda: focused.append(True) or True)
    monkeypatch.setattr(
        gui, "_ensure_release",
        lambda _d: pytest.fail("must not rebuild when already running"),
    )
    assert gui.main([]) == gui._EXIT_OK
    assert focused == [True]
    assert "уже запущен" in capsys.readouterr().err


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


# ------------------------------------------------------------------- _stage_exe


def _stage_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, localappdata: str | None = None
) -> Path:
    """Isolate staging to tmp_path and return the expected staging root."""
    monkeypatch.delenv("AXIOM_BIN_DIR", raising=False)
    if localappdata is None:
        localappdata = str(tmp_path / "local")
    monkeypatch.setenv("LOCALAPPDATA", localappdata)
    return Path(localappdata) / "axiom" / "bin"


def test_stage_exe_copies_to_localappdata_bin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _stage_env(tmp_path, monkeypatch)
    source = _make_exe(tmp_path / "desktop")
    source.write_bytes(b"MZ-staged-payload")

    staged = gui._stage_exe(source)

    assert staged == root / "axiom-desktop.exe"
    assert staged != source
    assert staged.is_file()
    assert staged.read_bytes() == b"MZ-staged-payload"
    # copy2 preserves the build time: the printed "сборка" stays identical.
    assert abs(
        staged.stat().st_mtime - source.stat().st_mtime
    ) <= gui._STAGE_MTIME_TOLERANCE_SECONDS


def test_stage_exe_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stage_env(tmp_path, monkeypatch)
    source = _make_exe(tmp_path / "desktop")
    first = gui._stage_exe(source)
    assert first.is_file()

    copies: list[Path] = []
    real_copy2 = gui.shutil.copy2

    def counting_copy2(src: object, dst: object, **kwargs: object) -> object:
        copies.append(Path(str(dst)))
        return real_copy2(src, dst, **kwargs)

    monkeypatch.setattr(gui.shutil, "copy2", counting_copy2)
    second = gui._stage_exe(source)

    assert second == first
    assert copies == []  # unchanged source -> no rewrite


def test_stage_exe_honors_axiom_bin_dir_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stage_env(tmp_path, monkeypatch)
    override = tmp_path / "custom-bin"
    monkeypatch.setenv("AXIOM_BIN_DIR", str(override))
    source = _make_exe(tmp_path / "desktop")

    staged = gui._stage_exe(source)

    assert staged == override / "axiom-desktop.exe"
    assert staged.is_file()


def test_stage_exe_falls_back_to_source_on_unwritable_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "file.txt"
    blocker.write_text("not a directory", encoding="utf-8")
    _stage_env(tmp_path, monkeypatch, localappdata=str(blocker))
    source = _make_exe(tmp_path / "desktop")

    staged = gui._stage_exe(source)

    assert staged == source  # never raises; staging is optional
    assert "Стейджинг" in capsys.readouterr().err


def test_stage_exe_replaces_outdated_staged_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _stage_env(tmp_path, monkeypatch)
    source = _make_exe(tmp_path / "desktop")
    source.write_bytes(b"MZ-v2-newer-build")
    stale = root / "axiom-desktop.exe"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"MZ-v1")
    assert stale.stat().st_size != source.stat().st_size

    staged = gui._stage_exe(source)

    assert staged == stale
    assert staged.read_bytes() == b"MZ-v2-newer-build"


def test_launch_stable_prints_staged_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The spawn line must show the staged path the process actually runs from."""
    root = _stage_env(tmp_path, monkeypatch)
    desktop = tmp_path / "desktop"
    (desktop / "src").mkdir(parents=True)
    (desktop / "src-tauri").mkdir(parents=True)
    source = _make_exe(desktop)

    class IdleProcess:
        def poll(self) -> None:
            return None

    spawned: list[Path] = []

    def fake_spawn(exe: Path) -> tuple[IdleProcess, Path]:
        spawned.append(exe)
        return IdleProcess(), tmp_path / "ready-dir"

    monkeypatch.setattr(gui, "_spawn_gui", fake_spawn)
    monkeypatch.setattr(gui, "_wait_for_stable_startup", lambda _p, _r: ("timeout", None))
    assert gui._launch_stable(source) == gui._EXIT_ERROR
    captured = capsys.readouterr().err
    assert str(root / "axiom-desktop.exe") in captured
    assert spawned == [root / "axiom-desktop.exe"]


