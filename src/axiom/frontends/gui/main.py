"""AXIOM GUI frontend launcher (``axiom --gui``).

The desktop GUI itself is a Tauri app that lives in ``desktop/`` (React
frontend + Rust shell that spawns the real Python core as a JSONL stdio
bridge). This module only *launches* it:

    1. a pre-built binary (``desktop/src-tauri/target/release/AXIOM.exe``
       or the debug build) — preferred, starts instantly;
    2. the Tauri CLI, launched directly through Node.js — compiles on the fly;
    3. a helpful error explaining what to install otherwise.
"""

from __future__ import annotations

import hashlib
import http.client
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

#: Build profiles in launch preference order: a release build embeds the
#: frontend, a debug build has none and needs the Vite dev server.
_PROFILE_ORDER = ("release", "debug")

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
    """Built shell worth launching, or ``None`` when the dev shell is better.

    A release build embeds the frontend, so it must be newer than both web and
    native sources. Debug builds are intentionally not returned here: they
    point at the dev URL and must be launched through `tauri dev`.
    """
    newest_source = _newest_web_source()
    newest_native = _newest_native_source()
    release = _built_exe("release")
    if release is not None and release.stat().st_mtime >= max(newest_source, newest_native):
        return release
    # A debug Tauri binary points at devUrl (127.0.0.1:1420) and cannot be
    # launched standalone: the Vite server is owned by `tauri dev` below.
    return None


def _launch_exe(exe: Path) -> bool:
    """Launch a release GUI with its frontend embedded in the binary."""
    _spawn_gui(exe)
    return True


def _frontend_dev_server_ready() -> bool:
    """Return true only when Tauri's configured local frontend answers HTTP."""
    connection = http.client.HTTPConnection("127.0.0.1", 1420, timeout=0.3)
    try:
        connection.request("GET", "/")
        return connection.getresponse().status == 200
    except OSError:
        return False
    finally:
        connection.close()


def _stop_dev_process(process: subprocess.Popen) -> None:
    """Stop a failed Tauri dev launch and its build children."""
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


def _wait_for_dev_start(
    process: subprocess.Popen,
    log_path: Path,
    log_offset: int,
    *,
    timeout: float = 900,
    poll_interval: float = 0.2,
) -> tuple[bool, str]:
    """Mirror fresh Tauri output and wait for both the shell and frontend.

    `tauri dev` exits zero as soon as the app is started by the caller, but the
    GUI launcher runs it detached. Watching its log avoids reporting success
    just because Popen succeeded, which used to hide Rust/Vite startup errors.
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
                if "Could not connect to `http://127.0.0.1:1420/`" in output:
                    return False, "Tauri не смог подключиться к frontend-серверу Vite."

            plain_output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
            shell_started = running_shell.search(plain_output) is not None
            if shell_started and _frontend_dev_server_ready():
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


def _run_dev(desktop: Path) -> int:
    """Start the Tauri dev shell (Vite + Rust build) fully detached.

    No console window is shown: the build runs in a detached process with
    output redirected to a log file, so closing the caller's terminal can
    never kill the build or the GUI.
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
    if not (desktop / "node_modules").exists():
        print(f"Устанавливаю зависимости десктоп-приложения ({desktop})…", file=sys.stderr)
        npm_cli = _npm_cli(node)
        if npm_cli is None:
            print("✕ npm JavaScript CLI не найден рядом с Node.js.", file=sys.stderr)
            return _EXIT_ERROR
        install = subprocess.run(
            [node, str(npm_cli), "install"], cwd=desktop,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=_HIDDEN,
        )
        if install.returncode != 0:
            return _EXIT_ERROR
    log_path = desktop / "tauri_dev.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_offset = log_path.stat().st_size if log_path.exists() else 0
    argv = [node, str(tauri_cli), "dev"]
    print(
        "Собираю AXIOM Desktop. Ниже будет отображаться реальный вывод Rust/Tauri; "
        "первый запуск может занять несколько минут.\n"
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

    ok, error = _wait_for_dev_start(process, log_path, log_offset)
    if not ok:
        _stop_dev_process(process)
        print(f"\n✕ {error}\nПодробности: {log_path}", file=sys.stderr)
        return _EXIT_ERROR
    print("\n✓ Frontend отвечает, Tauri запустил окно AXIOM.", file=sys.stderr)
    print("Процесс приложения работает отдельно от этого терминала.", file=sys.stderr)
    return _EXIT_OK


def _spawn_gui(exe: Path) -> None:
    """Start the GUI without attaching it to a console or inheriting stdio."""
    if _IS_WINDOWS:
        subprocess.Popen(
            [str(exe)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=_HIDDEN, close_fds=True,
        )
    else:
        subprocess.Popen([str(exe)], stdin=subprocess.DEVNULL, start_new_session=True)


def main() -> int:
    """Entry point for ``axiom --gui``. Never raises."""
    if _IS_WINDOWS and not _ensure_rust_toolchain():
        return _EXIT_ERROR
    exe = _find_built_exe()
    if exe is not None:
        try:
            # The GUI starts as a windowed process without inherited stdio.
            if _launch_exe(exe):
                return _EXIT_OK
        except FileNotFoundError:
            pass
    for desktop in _desktop_dirs():
        if (desktop / "package.json").exists() and (desktop / "src-tauri").exists():
            dev = _run_dev(desktop)
            return dev
    print(
        "✕ Десктопное приложение AXIOM не найдено.\n"
        "  GUI живёт в папке desktop/ репозитория (Tauri + React).\n"
        "  Варианты запуска:\n"
        "    cd desktop && npm install && npm run tauri dev   # сборка на лету\n"
        "    cd desktop && npm run tauri build                # релизный exe",
        file=sys.stderr,
    )
    return _EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
