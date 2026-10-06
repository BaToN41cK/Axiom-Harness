"""AXIOM GUI frontend launcher (``axiom --gui``).

The desktop GUI itself is a Tauri app that lives in ``desktop/`` (React
frontend + Rust shell that spawns the real Python core as a JSONL stdio
bridge). This module only *launches* it as a stable executable:

    1. a fresh release binary (``desktop/src-tauri/target/release/``) —
       launched directly when it is newer than all desktop sources;
    2. otherwise the frontend (``npm run build``) and the release shell
       (``cargo build --release``) are built first, then the fresh binary
       is launched;
    3. a helpful error explaining what to install otherwise.

There is intentionally no frontend dev server and no fixed port: the shell
loads the bundled ``desktop/dist/`` assets (Tauri ``frontendDist``), so an
ordinary source edit can never terminate the running GUI. The watch/rebuild
workflow lives behind the explicit opt-in ``axiom --gui --dev`` flag and is
never used for the normal launch path.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

_EXIT_OK = 0
_EXIT_ERROR = 1

#: Binary names Tauri produces for the current platform.
_EXE_CANDIDATES = ("axiom-desktop.exe", "AXIOM.exe", "axiom.exe", "axiom-desktop", "axiom", "AXIOM")

#: Build profiles for executable discovery. The normal launch path only ever
#: starts a release build (it embeds the frontend assets); a debug build is
#: only meaningful inside the opt-in ``--dev`` watch workflow.
_PROFILE_ORDER = ("release", "debug")

#: Log file for the stable build path (frontend + shell), per desktop dir.
_BUILD_LOG_NAME = "axiom_gui_build.log"

#: Log file for the opt-in watch workflow, per desktop dir.
_DEV_LOG_NAME = "tauri_dev.log"

#: How long the launcher watches a freshly spawned GUI before declaring it
#: started. The GUI is a plain executable (no dev server, no watch mode), so
#: "still alive after the grace period" is the readiness signal; an early
#: exit is always reported instead of being mistaken for success.
_STARTUP_GRACE_SECONDS = 6.0
_STARTUP_GRACE_POLL = 0.1

#: Env var the Rust shell reads: full path of the per-launch readiness
#: marker file, written only at the ``bridge-ready`` stage.
_LAUNCH_READY_FILE_ENV = "AXIOM_LAUNCH_READY_FILE"

#: Readiness budget for a supervised launch: the liveness grace plus a
#: margin for WebView2 creation, frontend load and one bridge round-trip.
#: The marker file — not liveness — is the success signal.
_READINESS_TIMEOUT_SECONDS = _STARTUP_GRACE_SECONDS + 4.0
_READINESS_POLL = 0.1

#: Must match ``SingleInstance::acquire()`` in desktop/src-tauri/src/lib.rs.
_SINGLE_INSTANCE_MUTEX = "Local\\AXIOM.Desktop.1.0"

#: Opt-in developer watch workflow: ``axiom --gui --dev``.
_DEV_FLAG = "--dev"

#: Frontend build budget; ``npm run build`` is typecheck + Vite build.
_FRONTEND_BUILD_TIMEOUT = 600.0

#: Release shell budget (LTO + strip make the first build slow).
_SHELL_BUILD_TIMEOUT = 1500.0

_RUSTUP_BASE_URL = "https://static.rust-lang.org/rustup/dist"
_MSVC_BUILD_TOOLS_URL = "https://visualstudio.microsoft.com/visual-cpp-build-tools/"

_IS_WINDOWS = sys.platform == "win32"

#: Console children must have redirected stdio and never create a window.
if _IS_WINDOWS:
    _HIDDEN = subprocess.CREATE_NO_WINDOW
else:
    _HIDDEN = 0


def _project_root() -> Path:
    """Repo root: this file is ``<root>/src/axiom/frontends/gui/main.py``."""
    return Path(__file__).resolve().parents[4]


def _desktop_dirs() -> list[Path]:
    """Where the desktop app may live (first existing wins for the search)."""
    candidates: list[Path] = []
    env_root = os.environ.get("AXIOM_DESKTOP_ROOT")
    if env_root:
        candidates.append(Path(env_root) / "desktop")
    candidates.append(_project_root() / "desktop")
    candidates.append(Path.cwd() / "desktop")
    candidates.append(Path.cwd())  # already inside desktop/
    unique: list[Path] = []
    for d in candidates:
        if d.exists() and d not in unique:
            unique.append(d)
    return unique


def _node_executable() -> str | None:
    return shutil.which("node.exe") or shutil.which("node")


def _node_cli(desktop: Path, package: str) -> Path | None:
    """Return a package CLI JS entrypoint, avoiding npm.cmd/tauri.cmd shims."""
    candidates = {
        "tauri": desktop / "node_modules" / "@tauri-apps" / "cli" / "tauri.js",
    }
    path = candidates.get(package)
    return path if path and path.is_file() else None


def _npm_cli(node: str) -> Path | None:
    path = Path(node).resolve().parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    return path if path.is_file() else None


class _SetupWindow:
    """Small native-feeling progress window shown only during Rust setup."""

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        self.root = tk.Tk()
        self.root.title("Подготовка AXIOM")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        frame = ttk.Frame(self.root, padding=22)
        frame.pack(fill="both", expand=True)
        self.label = ttk.Label(frame, text="Проверка Rust…", width=58, wraplength=440)
        self.label.pack(anchor="w", pady=(0, 16))
        self.bar = ttk.Progressbar(frame, mode="indeterminate", length=440)
        self.bar.pack(fill="x")
        self.bar.start(12)
        self.root.update_idletasks()
        width, height = 500, 128
        x = (self.root.winfo_screenwidth() - width) // 2
        y = (self.root.winfo_screenheight() - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.update()

    def status(self, text: str) -> None:
        self.bar.stop()
        self.bar.configure(mode="indeterminate", value=0)
        self.bar.start(12)
        self.label.configure(text=text)
        self.root.update_idletasks()
        self.root.update()

    def progress(self, current: int, total: int) -> None:
        if total > 0:
            self.bar.stop()
            self.bar.configure(mode="determinate", maximum=total, value=current)
            percent = int(current * 100 / total)
            self.label.configure(text=f"Загрузка установщика Rust… {percent}%")
            self.root.update_idletasks()
            self.root.update()

    def pump(self) -> None:
        self.root.update_idletasks()
        self.root.update()

    def close(self) -> None:
        try:
            self.root.destroy()
        except self._tk.TclError:
            pass


def _native_message(title: str, message: str, *, error: bool = True) -> None:
    """Show a Windows dialog even if tkinter is unavailable."""
    if _IS_WINDOWS:
        import ctypes

        icon = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x00000000 | icon)
    else:
        print(f"{title}: {message}", file=sys.stderr)


def _rust_target_triple(machine: str | None = None) -> str:
    arch = (machine or platform.machine()).lower()
    if arch in {"arm64", "aarch64"}:
        return "aarch64-pc-windows-msvc"
    if arch in {"amd64", "x86_64", "x64"}:
        return "x86_64-pc-windows-msvc"
    raise RuntimeError(f"Архитектура Windows не поддерживается установщиком Rust: {arch}")


def _user_rust_paths() -> tuple[Path, Path, Path]:
    profile = Path(os.environ.get("USERPROFILE") or Path.home())
    cargo_home = profile / ".cargo"
    rustup_home = profile / ".rustup"
    return profile, cargo_home, rustup_home


def _prepend_cargo_bin() -> Path:
    """Make rustup proxies visible to this process and all children."""
    _, cargo_home, _ = _user_rust_paths()
    cargo_bin = cargo_home / "bin"
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    normalized = os.path.normcase(os.path.normpath(str(cargo_bin)))
    if not any(os.path.normcase(os.path.normpath(part.strip('"'))) == normalized for part in parts if part):
        os.environ["PATH"] = str(cargo_bin) + (os.pathsep + current if current else "")
    return cargo_bin


def _find_rust_tools() -> tuple[str | None, str | None]:
    _prepend_cargo_bin()
    return (
        shutil.which("cargo.exe") or shutil.which("cargo"),
        shutil.which("rustc.exe") or shutil.which("rustc"),
    )


def _version_ok(executable: str | Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [str(executable), "--version"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", timeout=20,
            creationflags=_HIDDEN,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return result.returncode == 0, result.stdout.strip()


def _rust_host_ok(executable: str | Path) -> bool:
    try:
        result = subprocess.run(
            [str(executable), "-vV"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace", timeout=20,
            creationflags=_HIDDEN,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    expected = _rust_target_triple()
    return result.returncode == 0 and any(
        line.strip() == f"host: {expected}" for line in result.stdout.splitlines()
    )


def _setup_log_path() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    path = local / "AXIOM" / "logs" / "rust-install.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _apply_system_proxy(env: dict[str, str]) -> None:
    """Expose Windows' configured proxy to Rustup/Cargo child processes."""
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        proxies = {}
    for scheme in ("http", "https"):
        proxy = (
            os.environ.get(f"{scheme}_proxy")
            or os.environ.get(f"{scheme.upper()}_PROXY")
            or proxies.get(scheme)
        )
        if proxy:
            env.setdefault(f"{scheme}_proxy", proxy)
            env.setdefault(f"{scheme.upper()}_PROXY", proxy)
            os.environ.setdefault(f"{scheme}_proxy", proxy)
            os.environ.setdefault(f"{scheme.upper()}_PROXY", proxy)


def _download_rustup(target: str, destination: Path, window: _SetupWindow) -> None:
    url = f"{_RUSTUP_BASE_URL}/{target}/rustup-init.exe"
    window.status("Загрузка официального установщика Rust…")
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=30) as response:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with destination.open("wb") as output:
            while chunk := response.read(256 * 1024):
                output.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if total:
                    window.progress(downloaded, total)
                else:
                    window.pump()
    with urllib.request.urlopen(url + ".sha256", timeout=30) as response:
        expected = response.read().decode("ascii", errors="replace").split()[0].lower()
    if len(expected) != 64 or digest.hexdigest().lower() != expected:
        destination.unlink(missing_ok=True)
        raise RuntimeError("Не совпала контрольная сумма установщика Rust.")


def _run_setup_process(
    argv: list[str], *, log_path: Path, env: dict[str, str], window: _SetupWindow,
) -> int:
    with log_path.open("ab") as log:
        log.write(("\n> " + subprocess.list2cmdline(argv) + "\n").encode("utf-8"))
        log.flush()
        process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            env=env, creationflags=_HIDDEN, close_fds=True,
        )
        while process.poll() is None:
            window.pump()
            time.sleep(0.15)
        return int(process.returncode or 0)


def _install_rust_toolchain(window: _SetupWindow, log_path: Path) -> None:
    target = _rust_target_triple()
    _, cargo_home, rustup_home = _user_rust_paths()
    cargo_bin = _prepend_cargo_bin()
    env = os.environ.copy()
    # The requested user install location is stable across terminal sessions.
    env["CARGO_HOME"] = str(cargo_home)
    env["RUSTUP_HOME"] = str(rustup_home)
    _apply_system_proxy(env)
    os.environ.update({"CARGO_HOME": str(cargo_home), "RUSTUP_HOME": str(rustup_home)})
    rustup = cargo_bin / "rustup.exe"

    if rustup.is_file():
        window.status("Настройка стабильного Rust toolchain для MSVC…")
        commands = [
            [str(rustup), "set", "default-host", target],
            [str(rustup), "toolchain", "install", "stable", "--profile", "minimal"],
            [str(rustup), "default", "stable"],
        ]
        for argv in commands:
            if _run_setup_process(argv, log_path=log_path, env=env, window=window) != 0:
                raise RuntimeError("rustup завершился с ошибкой; подробности записаны в журнал.")
    else:
        window.status("Подготовка официального установщика Rust…")
        with tempfile.TemporaryDirectory(prefix="axiom-rustup-") as temp:
            installer = Path(temp) / "rustup-init.exe"
            _download_rustup(target, installer, window)
            window.status("Установка Rust stable (MSVC)…")
            argv = [
                str(installer), "-y", "--default-toolchain", "stable",
                "--default-host", target, "--profile", "minimal", "--no-modify-path",
            ]
            if _run_setup_process(argv, log_path=log_path, env=env, window=window) != 0:
                raise RuntimeError("Установщик Rust завершился с ошибкой; подробности записаны в журнал.")

    _prepend_cargo_bin()
    cargo = cargo_bin / "cargo.exe"
    rustc = cargo_bin / "rustc.exe"
    cargo_ok, cargo_version = _version_ok(cargo)
    rustc_ok, rustc_version = _version_ok(rustc)
    if not cargo_ok or not rustc_ok or not _rust_host_ok(rustc):
        details = f"cargo: {cargo_version or 'не найден'}; rustc: {rustc_version or 'не найден'}"
        raise RuntimeError(f"Rust MSVC toolchain установлен не полностью ({details}).")
    window.status(f"Rust готов: {rustc_version}; {cargo_version}. Запуск AXIOM…")
    time.sleep(0.5)


def _ensure_rust_toolchain() -> bool:
    """Install Rust automatically on Windows when the GUI build needs it."""
    if not _IS_WINDOWS:
        return True
    cargo, rustc = _find_rust_tools()
    if (
        cargo and rustc and _version_ok(cargo)[0] and _version_ok(rustc)[0]
        and _rust_host_ok(rustc)
    ):
        return True

    window: _SetupWindow | None = None
    try:
        log_path = _setup_log_path()
    except OSError:
        log_path = Path(tempfile.gettempdir()) / "axiom-rust-install.log"
    try:
        window = _SetupWindow()
        window.status("Rust не найден. AXIOM автоматически установит Rust stable…")
        _install_rust_toolchain(window, log_path)
        return True
    except Exception as exc:
        if window is not None:
            window.close()
        _native_message(
            "Не удалось подготовить Rust для AXIOM",
            f"{exc}\n\nЖурнал установки: {log_path}\n\n"
            "Проверьте подключение к интернету и повторите запуск AXIOM.",
        )
        return False
    finally:
        if window is not None:
            window.close()


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(part) for part in path.name.split(".") if part.isdigit())


def _prepend_environment_paths(name: str, additions: list[Path]) -> None:
    current = os.environ.get(name, "")
    values = [str(path) for path in additions if path.is_dir()]
    values.extend(part for part in current.split(os.pathsep) if part)
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = os.path.normcase(os.path.normpath(value.strip('"')))
        if key not in seen:
            seen.add(key)
            unique.append(value)
    if unique:
        os.environ[name] = os.pathsep.join(unique)


def _vswhere_path() -> Path | None:
    program_files = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    for path in (
        program_files / "Microsoft Visual Studio" / "Installer" / "vswhere.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Microsoft Visual Studio" / "Installer" / "vswhere.exe",
    ):
        if path.is_file():
            return path
    return None


def _visual_studio_installations() -> list[Path]:
    vswhere = _vswhere_path()
    if vswhere is None:
        return []
    try:
        result = subprocess.run(
            [str(vswhere), "-products", "*", "-property", "installationPath"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", timeout=15,
            creationflags=_HIDDEN,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]


def _msvc_setup() -> bool:
    """Populate MSVC/Windows SDK environment without invoking a command shell."""
    if not _IS_WINDOWS:
        return True
    if shutil.which("cl.exe") and shutil.which("link.exe"):
        return True  # already running in a configured VS developer environment
    try:
        target = _rust_target_triple()
    except RuntimeError:
        return False
    arch = "arm64" if target.startswith("aarch64-") else "x64"
    program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    sdk_root = program_files_x86 / "Windows Kits" / "10"
    sdk_versions = sorted(
        (path for path in (sdk_root / "Include").glob("10.*") if (path / "um" / "Windows.h").is_file()),
        key=_version_key,
        reverse=True,
    )
    sdk_version = sdk_versions[0].name if sdk_versions else ""
    sdk_lib = sdk_root / "Lib" / sdk_version
    sdk_bin = sdk_root / "bin" / sdk_version

    for installation in _visual_studio_installations():
        vc_root = installation / "VC"
        tools_root = vc_root / "Tools" / "MSVC"
        versions = sorted(
            (path for path in tools_root.iterdir() if path.is_dir()),
            key=_version_key,
            reverse=True,
        ) if tools_root.is_dir() else []
        for tools in versions:
            bin_candidates = [tools / "bin" / "Hostx64" / arch]
            if arch == "arm64":
                bin_candidates.append(tools / "bin" / "Hostarm64" / arch)
            compiler_bin = next(
                (path for path in bin_candidates if (path / "cl.exe").is_file() and (path / "link.exe").is_file()),
                None,
            )
            if compiler_bin is None or not sdk_version:
                continue
            include_dirs = [
                tools / "include",
                sdk_root / "Include" / sdk_version / "shared",
                sdk_root / "Include" / sdk_version / "um",
                sdk_root / "Include" / sdk_version / "winrt",
                sdk_root / "Include" / sdk_version / "ucrt",
                sdk_root / "Include" / sdk_version / "cppwinrt",
            ]
            lib_dirs = [
                tools / "lib" / arch,
                sdk_lib / "um" / arch,
                sdk_lib / "ucrt" / arch,
            ]
            if not all(path.is_dir() for path in include_dirs[:5] + lib_dirs):
                continue
            atlmfc = tools / "atlmfc"
            path_dirs = [compiler_bin, sdk_bin / arch, sdk_bin / "x64"]
            _prepend_environment_paths("PATH", path_dirs)
            _prepend_environment_paths("INCLUDE", include_dirs)
            _prepend_environment_paths("LIB", lib_dirs)
            _prepend_environment_paths("LIBPATH", [
                atlmfc / "lib" / arch, tools / "lib" / arch,
                sdk_root / "References" / sdk_version,
            ])
            os.environ.update({
                "VSINSTALLDIR": str(installation) + os.sep,
                "VCINSTALLDIR": str(vc_root) + os.sep,
                "VCToolsInstallDir": str(tools) + os.sep,
                "VCToolsVersion": tools.name,
                "WindowsSdkDir": str(sdk_root) + os.sep,
                "WindowsSDKVersion": sdk_version + os.sep,
                "UniversalCRTSdkDir": str(sdk_root) + os.sep,
                "UCRTVersion": sdk_version,
                "Platform": arch,
                "VSCMD_ARG_TGT_ARCH": arch,
            })
            if shutil.which("cl.exe") and shutil.which("link.exe"):
                return True
    return False


def _show_msvc_required() -> None:
    if not _IS_WINDOWS:
        return
    import ctypes

    answer = ctypes.windll.user32.MessageBoxW(
        None,
        "Для сборки GUI AXIOM нужен компонент Visual C++ Build Tools "
        "«Desktop development with C++» и Windows SDK. Rust уже подготовлен, "
        "но эти системные компоненты не найдены.\n\n"
        "Открыть официальную страницу Build Tools? После установки просто "
        "запустите axiom --gui ещё раз — новый CMD открывать не нужно.",
        "Для AXIOM нужны компоненты MSVC",
        0x00000004 | 0x00000030,  # MB_YESNO | MB_ICONWARNING
    )
    if answer == 6:
        ctypes.windll.shell32.ShellExecuteW(
            None, "open", _MSVC_BUILD_TOOLS_URL, None, None, 1,
        )


def _newest_web_source() -> float:
    """Newest mtime of the web frontend sources (``desktop/src``)."""
    newest = 0.0
    for desktop in _desktop_dirs():
        src_dir = desktop / "src"
        # Only the web frontend counts (desktop/src); a bare repo root also
        # has src/ (the Python package) but it is not part of the exe.
        if src_dir.exists() and (desktop / "src-tauri").exists():
            mtimes = (p.stat().st_mtime for p in src_dir.rglob("*") if p.is_file())
            newest = max(newest, max(mtimes, default=0.0))
    return newest


def _newest_native_source() -> float:
    """Newest Rust/bridge/config source that must be present in the shell exe."""
    newest = 0.0
    for desktop in _desktop_dirs():
        tauri = desktop / "src-tauri"
        candidates = [tauri / "Cargo.toml", tauri / "tauri.conf.json", tauri / "build.rs"]
        for directory in (tauri / "src", tauri / "bridge"):
            if directory.exists():
                candidates.extend(directory.rglob("*"))
        mtimes = (p.stat().st_mtime for p in candidates if p.is_file())
        newest = max(newest, max(mtimes, default=0.0))
    return newest


def _built_exe(profile: str) -> Path | None:
    """Newest built exe of one profile across all known desktop directories."""
    best: Path | None = None
    for desktop in _desktop_dirs():
        target = desktop / "src-tauri" / "target" / profile
        for exe in _EXE_CANDIDATES:
            candidate = target / exe
            if candidate.is_file() and (best is None or candidate.stat().st_mtime > best.stat().st_mtime):
                best = candidate
    return best


def _find_built_exe_any(profile: str | None = None) -> Path | None:
    """Newest built exe regardless of source staleness (fallback path)."""
    profiles = (profile,) if profile else _PROFILE_ORDER
    best: Path | None = None
    for name in profiles:
        candidate = _built_exe(name)
        if candidate is not None and (best is None or candidate.stat().st_mtime > best.stat().st_mtime):
            best = candidate
    return best


def _find_built_exe() -> Path | None:
    """Fresh release shell worth launching, or ``None`` when a build is due.

    A release build embeds the frontend, so it must be newer than both web and
    native sources. Debug builds are intentionally never returned here: they
    only make sense inside the opt-in ``--dev`` watch workflow.
    """
    newest_source = _newest_web_source()
    newest_native = _newest_native_source()
    release = _built_exe("release")
    if release is not None and release.stat().st_mtime >= max(newest_source, newest_native):
        return release
    return None


def _release_exe_in(desktop: Path) -> Path | None:
    """Newest release executable inside one desktop directory, if any."""
    target = desktop / "src-tauri" / "target" / "release"
    best: Path | None = None
    for exe in _EXE_CANDIDATES:
        candidate = target / exe
        if candidate.is_file() and (best is None or candidate.stat().st_mtime > best.stat().st_mtime):
            best = candidate
    return best


def _candidate_exes() -> list[Path]:
    """Every built executable we know about (release and debug)."""
    found: list[Path] = []
    for desktop in _desktop_dirs():
        for profile in _PROFILE_ORDER:
            target = desktop / "src-tauri" / "target" / profile
            for exe in _EXE_CANDIDATES:
                candidate = target / exe
                if candidate.is_file():
                    found.append(candidate)
    return found


def _desktop_source_mtime(desktop: Path) -> float:
    """Newest mtime of everything baked into the shell executable."""
    newest = 0.0
    tauri = desktop / "src-tauri"
    candidates: list[Path] = [tauri / "Cargo.toml", tauri / "tauri.conf.json", tauri / "build.rs"]
    for directory in (tauri / "src", tauri / "bridge"):
        if directory.exists():
            candidates.extend(p for p in directory.rglob("*") if p.is_file())
    for extra in (desktop / "package.json", desktop / "vite.config.ts"):
        candidates.append(extra)
    src_dir = desktop / "src"
    if src_dir.exists():
        candidates.extend(p for p in src_dir.rglob("*") if p.is_file())
    for path in candidates:
        try:
            if path.is_file():
                newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def _frontend_stale(desktop: Path) -> bool:
    """True when ``dist/`` is missing or older than the web sources."""
    dist = desktop / "dist" / "index.html"
    try:
        if not dist.is_file():
            return True
        dist_mtime = dist.stat().st_mtime
    except OSError:
        return True
    newest = 0.0
    src_dir = desktop / "src"
    if src_dir.exists():
        for path in src_dir.rglob("*"):
            try:
                if path.is_file():
                    newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
    for extra in (desktop / "package.json", desktop / "vite.config.ts"):
        try:
            if extra.is_file():
                newest = max(newest, extra.stat().st_mtime)
        except OSError:
            continue
    return newest > dist_mtime


def _needs_shell_build(desktop: Path) -> bool:
    """True when no release exe exists or any baked-in source is newer."""
    exe = _release_exe_in(desktop)
    if exe is None:
        return True
    try:
        exe_mtime = exe.stat().st_mtime
    except OSError:
        return True
    if _desktop_source_mtime(desktop) > exe_mtime:
        return True
    # The exe embeds dist/ at compile time: a rebuilt dist/ alone is not
    # enough, the shell must be relinked as well.
    dist = desktop / "dist" / "index.html"
    try:
        if dist.is_file() and dist.stat().st_mtime > exe_mtime:
            return True
    except OSError:
        return True
    return False


def _axiom_already_running() -> bool:
    """True when another AXIOM desktop process owns the single-instance mutex.

    This reuses the exact mechanism the Rust shell enforces, so the launcher
    never starts a competing instance. Non-Windows platforms have no mutex
    guard in the shell and always report False here.
    """
    if not _IS_WINDOWS:
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX)
        if not handle:
            return False
        try:
            return kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        finally:
            kernel32.CloseHandle(handle)
    except OSError:
        return False


def _focus_axiom_window() -> bool:
    """Best-effort restore and focus of the already running AXIOM window."""
    if not _IS_WINDOWS:
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "AXIOM")
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except OSError:
        return False


def _stop_watch_process(process: subprocess.Popen) -> None:
    """Stop a failed watch-mode launch and its build children."""
    if process.poll() is not None:
        return
    try:
        if _IS_WINDOWS:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=_HIDDEN, timeout=10,
            )
        else:
            import signal

            os.killpg(process.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass


def _wait_for_watch_start(
    process: subprocess.Popen,
    log_path: Path,
    log_offset: int,
    *,
    timeout: float = 900,
    poll_interval: float = 0.2,
) -> tuple[bool, str]:
    """Mirror fresh watch-mode output and wait for the debug shell to start.

    Dev-watch only (``axiom --gui --dev``): ``tauri dev`` owns a file watcher
    that restarts the debug shell on every source edit, so this readiness
    signal must never be used for the normal launch path.
    """
    started = time.monotonic()
    last_status = started
    output = ""
    running_shell = re.compile(
        r"Running\s+[`'\"]?target[/\\]debug[/\\]axiom-desktop(?:\.exe)?",
        re.IGNORECASE,
    )

    with log_path.open("rb") as log:
        log.seek(log_offset)
        while True:
            chunk = log.read(64 * 1024)
            if chunk:
                text = chunk.decode("utf-8", errors="replace")
                sys.stderr.write(text)
                sys.stderr.flush()
                output = (output + text)[-32_000:]
                if re.search(r"error\[E\d{4}\]:|error: could not compile ", output, re.IGNORECASE):
                    return False, "Сборка Rust завершилась с ошибкой."

            plain_output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
            shell_started = running_shell.search(plain_output) is not None
            if shell_started:
                # Do not call this a launch if the watcher has already failed.
                code = process.poll()
                if code is None:
                    return True, ""
                return False, f"Процесс Tauri завершился сразу после запуска (код {code})."

            code = process.poll()
            if code is not None:
                return False, f"Процесс сборки Tauri завершился до запуска GUI (код {code})."

            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                return False, f"GUI не запустился за {int(timeout)} секунд."
            if time.monotonic() - last_status >= 10:
                seconds = int(elapsed)
                sys.stderr.write(
                    f"\n… Сборка ещё выполняется ({seconds // 60:02d}:{seconds % 60:02d}).\n"
                )
                sys.stderr.flush()
                last_status = time.monotonic()
            time.sleep(poll_interval)


def _run_dev_watch(desktop: Path) -> int:
    """Start the opt-in watch workflow (``axiom --gui --dev``), detached.

    ``tauri dev`` rebuilds on every source edit and restarts the debug shell,
    by design: this mode is for desktop development only and is never used
    for the normal ``axiom --gui`` launch. No console window is shown: the
    build runs detached with output redirected to a log file, so closing the
    caller's terminal can never kill the build or the GUI. Uses no fixed
    ports: the debug shell serves the locally built ``dist/`` assets.
    """
    node = _node_executable()
    tauri_cli = _node_cli(desktop, "tauri")
    if node is None or tauri_cli is None:
        print(
            "✕ Node.js (npm) не найден в PATH.\n"
            "  Установите Node.js LTS: https://nodejs.org/download/",
            file=sys.stderr,
        )
        return _EXIT_ERROR
    if shutil.which("cargo") is None and shutil.which("cargo.exe") is None:
        print(
            "✕ Rust toolchain (cargo) не найден в PATH — Tauri собирает "
            "нативное окно на Rust.\n"
            "  Установите rustup: https://rustup.ru/  (Windows: дополнительно "
            "нужны MSVC Build Tools — rustup предложит их сам).\n"
            "  Не удалось подготовить Rust автоматически. Проверьте журнал установки "
            "и повторите запуск axiom --gui.",
            file=sys.stderr,
        )
        return _EXIT_ERROR
    try:
        msvc_ready = _msvc_setup()
    except OSError:
        msvc_ready = False
    if _IS_WINDOWS and not msvc_ready:
        _show_msvc_required()
        return _EXIT_ERROR
    ok, error = _ensure_frontend_deps(desktop, node)
    if not ok:
        print(f"✕ {error}", file=sys.stderr)
        return _EXIT_ERROR
    log_path = desktop / _DEV_LOG_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_offset = log_path.stat().st_size if log_path.exists() else 0
    argv = [node, str(tauri_cli), "dev"]
    print(
        "Запускаю AXIOM Desktop в режиме разработки (--dev): сборка с "
        "пересборкой при правках, окно перезапускается автоматически.\n"
        "Обычный запуск без слежения — просто axiom --gui.\n"
        f"Полный лог: {log_path}",
        file=sys.stderr,
        flush=True,
    )
    try:
        with log_path.open("ab") as log:
            log.write(("\n> " + subprocess.list2cmdline(argv) + "\n").encode("utf-8"))
            log.flush()
            process = subprocess.Popen(
                argv,
                cwd=desktop,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=_HIDDEN if _IS_WINDOWS else 0,
                start_new_session=not _IS_WINDOWS,
                close_fds=True,
            )
    except OSError as exc:
        print(f"✕ Не удалось запустить Tauri: {exc}\nЛог: {log_path}", file=sys.stderr)
        return _EXIT_ERROR

    ok, error = _wait_for_watch_start(process, log_path, log_offset)
    if not ok:
        _stop_watch_process(process)
        print(f"\n✕ {error}\nПодробности: {log_path}", file=sys.stderr)
        return _EXIT_ERROR
    print("\n✓ Tauri запустил окно AXIOM (режим --dev).", file=sys.stderr)
    print("Процесс приложения работает отдельно от этого терминала.", file=sys.stderr)
    return _EXIT_OK


def _ensure_frontend_deps(desktop: Path, node: str) -> tuple[bool, str]:
    """Install desktop JS dependencies when ``node_modules`` is missing."""
    if (desktop / "node_modules").exists():
        return True, ""
    npm_cli = _npm_cli(node)
    if npm_cli is None:
        return False, "npm JavaScript CLI не найден рядом с Node.js."
    print(f"Устанавливаю зависимости десктоп-приложения ({desktop})…", file=sys.stderr)
    install = subprocess.run(
        [node, str(npm_cli), "install"], cwd=desktop,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=_HIDDEN,
    )
    if install.returncode != 0:
        return False, "Не удалось установить зависимости десктоп-приложения (npm install)."
    return True, ""


def _run_logged(
    argv: list[str], *, cwd: Path, log_path: Path, timeout: float,
    env: dict[str, str] | None = None,
) -> tuple[int | None, str]:
    """Run *argv* synchronously, appending all output to *log_path*.

    Returns ``(returncode, tail)``; ``returncode`` is ``None`` when the
    process could not be started or the timeout expired. ``tail`` holds the
    last kilobytes of output for error reporting.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        log.write(("\n> " + subprocess.list2cmdline(argv) + "\n").encode("utf-8"))
        log.flush()
        try:
            completed = subprocess.run(
                argv, cwd=cwd, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=_HIDDEN, close_fds=True, timeout=timeout,
                env=env,
            )
        except FileNotFoundError as exc:
            return None, f"не удалось запустить {argv[0]}: {exc}"
        except subprocess.TimeoutExpired:
            return None, f"превышено время ожидания ({int(timeout)} c)."
    try:
        with log_path.open("rb") as log:
            log.seek(max(0, log_path.stat().st_size - 8192))
            tail = log.read().decode("utf-8", errors="replace")
    except OSError:
        tail = ""
    return completed.returncode, tail


def _build_frontend(desktop: Path, node: str, log_path: Path) -> tuple[bool, str]:
    """Typecheck + bundle the React frontend into ``desktop/dist/``."""
    npm_cli = _npm_cli(node)
    if npm_cli is None:
        return False, "npm JavaScript CLI не найден рядом с Node.js."
    print("Собираю frontend (tsc + vite build)…", file=sys.stderr)
    # esbuild extracts its helper binary to %TEMP% and Windows tooling
    # (antivirus/indexer) can lock it there, failing the build with
    # "Access is denied". Build with a private temp dir inside the project.
    build_tmp = desktop / ".tmp" / "frontend-build-temp"
    try:
        shutil.rmtree(build_tmp, ignore_errors=True)
        build_tmp.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    env = os.environ.copy()
    env.update({
        "TEMP": str(build_tmp), "TMP": str(build_tmp), "TMPDIR": str(build_tmp),
    })
    try:
        code, tail = _run_logged(
            [node, str(npm_cli), "run", "build"],
            cwd=desktop, log_path=log_path, timeout=_FRONTEND_BUILD_TIMEOUT,
            env=env,
        )
    finally:
        shutil.rmtree(build_tmp, ignore_errors=True)
    if code != 0:
        reason = tail.strip().splitlines()[-1] if tail.strip() else "см. лог"
        return False, f"Сборка frontend завершилась с ошибкой: {reason}\nПодробности: {log_path}"
    if not (desktop / "dist" / "index.html").is_file():
        return False, f"Сборка frontend прошла, но dist/index.html не создан.\nПодробности: {log_path}"
    return True, ""


def _build_shell_release(desktop: Path, log_path: Path) -> tuple[bool, str]:
    """Compile the Tauri shell in release (embeds the fresh ``dist/``)."""
    try:
        if not _msvc_setup():
            _show_msvc_required()
            return False, "Для сборки нужны компоненты MSVC/Windows SDK."
    except OSError:
        _show_msvc_required()
        return False, "Для сборки нужны компоненты MSVC/Windows SDK."
    cargo = shutil.which("cargo.exe") or shutil.which("cargo")
    if cargo is None:
        return False, "Rust toolchain (cargo) не найден в PATH."
    print("Собираю desktop-оболочку (cargo build --release)…", file=sys.stderr)
    code, tail = _run_logged(
        [cargo, "build", "--release"],
        cwd=desktop / "src-tauri", log_path=log_path, timeout=_SHELL_BUILD_TIMEOUT,
    )
    if code != 0:
        reason = tail.strip().splitlines()[-1] if tail.strip() else "см. лог"
        return False, f"Сборка Rust завершилась с ошибкой: {reason}\nПодробности: {log_path}"
    return True, ""


def _ensure_release(desktop: Path) -> tuple[Path | None, str]:
    """Return a release exe newer than all desktop sources, building if needed.

    Build failures are reported with the log path and never masked by
    silently launching a stale executable.
    """
    node = _node_executable()
    if node is None:
        return None, (
            "Node.js (npm) не найден в PATH.\n"
            "  Установите Node.js LTS: https://nodejs.org/download/"
        )
    ok, error = _ensure_frontend_deps(desktop, node)
    if not ok:
        return None, error
    if not _needs_shell_build(desktop) and not _frontend_stale(desktop):
        exe = _release_exe_in(desktop)
        if exe is not None:
            return exe, ""
    log_path = desktop / _BUILD_LOG_NAME
    print(
        "Собираю AXIOM Desktop (релиз, без dev-сервера). "
        "Первый запуск может занять несколько минут.\n"
        f"Полный лог: {log_path}",
        file=sys.stderr,
        flush=True,
    )
    if _frontend_stale(desktop):
        ok, error = _build_frontend(desktop, node, log_path)
        if not ok:
            return None, error
    if _needs_shell_build(desktop):
        ok, error = _build_shell_release(desktop, log_path)
        if not ok:
            return None, error
    exe = _release_exe_in(desktop)
    if exe is None:
        return None, (
            "Сборка прошла, но релизный exe не найден "
            f"({desktop / 'src-tauri' / 'target' / 'release'}).\n"
            f"Подробности: {log_path}"
        )
    return exe, ""


def _windows_integrity_hint() -> str:
    """Best-effort integrity level of THIS python process, for diagnostics.

    Printed before the spawn so a failing launch immediately shows whether
    the launcher itself runs with a restricted token (Low/Untrusted) — the
    child inherits it and the desktop preflight will deny profile writes.
    """
    if not _IS_WINDOWS:
        return "n/a"
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        advapi32.OpenProcessToken.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p),
        ]
        token = ctypes.c_void_p()
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
        ):
            return f"query failed (os error {ctypes.get_last_error()})"

        class _SidAndAttributes(ctypes.Structure):
            _fields_ = [
                ("Sid", ctypes.c_void_p),
                ("Attributes", ctypes.c_ulong),
            ]

        class _TokenMandatoryLabel(ctypes.Structure):
            _fields_ = [("Label", _SidAndAttributes)]

        advapi32.GetTokenInformation.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        needed = ctypes.c_ulong(0)
        advapi32.GetTokenInformation(
            token, 25, None, 0, ctypes.byref(needed)
        )
        if needed.value < ctypes.sizeof(_TokenMandatoryLabel):
            return "query failed (no size)"
        buf = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            token, 25, buf, needed.value, ctypes.byref(needed)
        ):
            return f"query failed (os error {ctypes.get_last_error()})"
        label = _TokenMandatoryLabel.from_buffer_copy(
            buf.raw[: ctypes.sizeof(_TokenMandatoryLabel)]
        )
        sid = label.Label.Sid
        if not sid:
            return "query failed (null sid)"
        count = ctypes.c_ubyte.from_address(sid + 1).value
        if count == 0:
            return "query failed (empty sid)"
        rid = ctypes.c_ulong.from_address(sid + 8 + 4 * (count - 1)).value
        return {
            0x0000: "untrusted",
            0x1000: "low",
            0x2000: "medium",
            0x3000: "high",
        }.get(rid, f"rid {rid:#x}")
    except (OSError, AttributeError):
        return "unavailable"


#: Staged copy name: always canonical, regardless of the source exe name.
_STAGED_EXE_NAME = "axiom-desktop.exe"

#: Size/mtime tolerance when deciding a staged copy is already current
#: (filesystems and copy operations do not preserve mtimes bit-exactly).
_STAGE_MTIME_TOLERANCE_SECONDS = 2.0


def _staging_root() -> Path:
    """Per-user directory for the staged desktop executable."""
    override = os.environ.get("AXIOM_BIN_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "axiom" / "bin"
    return Path.home() / ".axiom" / "bin"


def _stage_exe(exe: Path) -> Path:
    """Copy *exe* to a per-user directory and return the path to spawn.

    Terminals that confine the repository workspace (e.g. sandboxed shells)
    give spawned children whose image lives under the repo a low-integrity
    restricted token; the desktop preflight then fails its profile
    write-probe with ``os error 5``. The exact same exe launched from a
    per-user directory outside the repo runs at medium integrity and works
    fully. Staging is an optimization, never a hard requirement: on any
    ``OSError`` the original *exe* is returned unchanged.
    """
    try:
        staged = _staging_root() / _STAGED_EXE_NAME
        if os.path.normcase(str(staged)) == os.path.normcase(str(exe)):
            return exe
        source_stat = exe.stat()
        if staged.exists():
            staged_stat = staged.stat()
            if (
                staged_stat.st_size == source_stat.st_size
                and abs(staged_stat.st_mtime - source_stat.st_mtime)
                <= _STAGE_MTIME_TOLERANCE_SECONDS
            ):
                return staged
        staged.parent.mkdir(parents=True, exist_ok=True)
        temp = staged.with_name(f"{staged.name}.new-{os.getpid()}")
        try:
            shutil.copy2(exe, temp)
            os.replace(temp, staged)
        except PermissionError:
            # A running instance is executing the staged exe: os.replace
            # cannot swap a file that is open for execution. The old staged
            # build is already proven working, so keep launching it.
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            if staged.exists():
                print(
                    f"⚠ Стейджинг не обновлён (запущенная копия занята): {staged}",
                    file=sys.stderr,
                )
                return staged
            raise
    except OSError as exc:
        print(f"⚠ Стейджинг exe пропущен, запускаю оригинал: {exc}", file=sys.stderr)
        return exe
    return staged


def _spawn_gui(exe: Path) -> tuple[subprocess.Popen, Path]:
    """Start the GUI without attaching it to a console or inheriting stdio.

    The process is returned (not detached-and-forgotten) so the caller can
    apply the startup readiness check. It is a plain executable: no watcher
    owns it, so later source edits cannot terminate it.

    A fresh per-launch directory is created for the readiness marker file;
    its path is passed to the shell via ``AXIOM_LAUNCH_READY_FILE``. The
    shell writes the marker exactly once, at the ``bridge-ready`` stage
    (frontend loaded AND bridge round-trip), never on preflight failure.

    ``AXIOM_DESKTOP_ROOT`` points the shell at the repository when the exe
    runs from the staging copy (outside the repo): the Rust ``find_root``
    then resolves the bridge script and the working-tree python package
    without depending on the caller's cwd.
    """
    ready_dir = Path(tempfile.mkdtemp(prefix="axiom-launch-"))
    env = os.environ.copy()
    env[_LAUNCH_READY_FILE_ENV] = str(ready_dir / "ready")
    if "AXIOM_DESKTOP_ROOT" not in env:
        env["AXIOM_DESKTOP_ROOT"] = str(_project_root())
    if _IS_WINDOWS:
        process = subprocess.Popen(
            [str(exe)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=_HIDDEN, close_fds=True,
            env=env,
        )
    else:
        process = subprocess.Popen(
            [str(exe)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
            env=env,
        )
    return process, ready_dir


def _wait_for_stable_startup(process: subprocess.Popen, ready_file: Path) -> tuple[str, int | None]:
    """Wait for the Rust shell to confirm readiness via the marker file.

    Returns ``("ready", None)`` once the marker exists (the shell reached the
    ``bridge-ready`` stage), ``("exited", code)`` when the process dies
    without a marker, or ``("timeout", None)`` when the budget elapses with
    a live process and no marker. Neither log text nor any network probe is
    treated as readiness, and window titles are never checked.
    """
    deadline = time.monotonic() + _READINESS_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if ready_file.is_file():
            return "ready", None
        code = process.poll()
        if code is not None:
            # The marker may have been written microseconds before exit.
            if ready_file.is_file():
                return "ready", None
            return "exited", code
        time.sleep(_READINESS_POLL)
    if ready_file.is_file():
        return "ready", None
    code = process.poll()
    if code is not None:
        return "exited", code
    return "timeout", None


def _launch_stable(exe: Path) -> int:
    """Spawn the release exe and wait for its readiness marker.

    The marker file (written by the Rust shell at the ``bridge-ready``
    stage) is the success signal; liveness alone never counts as readiness.
    """
    try:
        staged = _stage_exe(exe)
        build_time = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(staged.stat().st_mtime)
        )
        print(
            f"Запускаю {staged} (сборка {build_time})",
            file=sys.stderr,
        )
        integrity = _windows_integrity_hint()
        if integrity in {"low", "untrusted"}:
            print(
                f"⚠ Этот терминал работает с ограниченным маркером доступа "
                f"(integrity={integrity}).\n"
                "  Дочерний процесс унаследует его и не сможет записать профиль —\n"
                "  запуск из такого терминала защищён отказом (это не баг).\n"
                "  Запустите из обычного cmd/Проводника, вне песочницы.",
                file=sys.stderr,
            )
        else:
            print(f"Окружение лаунчера: integrity={integrity}", file=sys.stderr)
        process, ready_dir = _spawn_gui(staged)
    except OSError as exc:
        print(f"✕ Не удалось запустить AXIOM ({exe}): {exc}", file=sys.stderr)
        return _EXIT_ERROR
    try:
        state, code = _wait_for_stable_startup(process, ready_dir / "ready")
    finally:
        shutil.rmtree(ready_dir, ignore_errors=True)
    if state == "ready":
        print(f"✓ AXIOM запущен ({exe.name}).", file=sys.stderr)
        print("Окно работает отдельно от этого терминала.", file=sys.stderr)
        return _EXIT_OK
    if state == "timeout":
        # The process is alive but never confirmed readiness: the likely
        # cause is the preflight-failure modal (or an otherwise stuck UI).
        # It is deliberately NOT killed — the modal is the user-facing
        # diagnosis, and closing it lets the shell exit on its own.
        print(
            f"✕ AXIOM не подтвердил готовность за {_READINESS_TIMEOUT_SECONDS:.0f} с "
            "(процесс жив, интерфейс не загрузился).\n"
            "  Вероятно, открыто окно ошибки запуска — закройте его и следуйте\n"
            "  его инструкциям.\n"
            "  лог префлайта: %TEMP%\\axiom-preflight-failed.log\n"
            "  полный лог: %LOCALAPPDATA%\\app.axiom.desktop\\logs\\axiom-startup.log",
            file=sys.stderr,
        )
        return _EXIT_ERROR
    if code == 0 and (_axiom_already_running() or _focus_axiom_window()):
        # Lost a startup race: the first instance owns the window. The exe
        # already focused it (exit 0). The python-side mutex probe can fail
        # with access-denied when the existing mutex was created by a
        # higher-integrity process, so the visible window is an acceptable
        # fallback witness here — the exit code 0 already proves the shell
        # resolved the single-instance path.
        _focus_axiom_window()
        print("AXIOM уже запущен — открыто существующее окно.", file=sys.stderr)
        return _EXIT_OK
    if code == 20:
        # Exit code 20 is the desktop preflight failure: an error dialog with
        # the classified reason was shown to the user.
        print(
            "✕ Запуск AXIOM заблокирован проверкой окружения (код 20).\n"
            "  В окне ошибки указаны причина и путь лога. Частая причина — запуск\n"
            "  из песочницы/ограниченного терминала: запустите из обычного cmd,\n"
            "  Проводника или ярлыка.\n"
            f"  Логи (если записались): {os.environ.get('TEMP', '?')}"
            "\\axiom-preflight-failed.log,\n"
            "    %LOCALAPPDATA%\\app.axiom.desktop\\logs\\axiom-startup.log",
            file=sys.stderr,
        )
        return _EXIT_ERROR
    print(
        f"✕ Приложение завершилось сразу после запуска (код {code}).\n"
        "  Проверьте требования (WebView2 на Windows) и повторите запуск.",
        file=sys.stderr,
    )
    return _EXIT_ERROR


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``axiom --gui``. Never raises."""
    args = list(sys.argv[1:] if argv is None else argv)
    dev_mode = _DEV_FLAG in args
    if _IS_WINDOWS and not _ensure_rust_toolchain():
        return _EXIT_ERROR
    for desktop in _desktop_dirs():
        if (desktop / "package.json").exists() and (desktop / "src-tauri").exists():
            if dev_mode:
                return _run_dev_watch(desktop)
            if _axiom_already_running():
                _focus_axiom_window()
                print("AXIOM уже запущен — открыто существующее окно.", file=sys.stderr)
                return _EXIT_OK
            exe, error = _ensure_release(desktop)
            if exe is None:
                print(f"✕ {error}", file=sys.stderr)
                return _EXIT_ERROR
            return _launch_stable(exe)
    print(
        "✕ Десктопное приложение AXIOM не найдено.\n"
        "  GUI живёт в папке desktop/ репозитория (Tauri + React).\n"
        "  Обычный запуск собирает релиз автоматически: axiom --gui\n"
        "  Режим разработки (пересборка при правках): axiom --gui --dev",
        file=sys.stderr,
    )
    return _EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
