//! AXIOM desktop shell.
//!
//! Spawns the real Python core (ChatSession: Ollama, streaming, tools,
//! history) as a JSONL stdio subprocess and shuttles requests/events between
//! the Tauri webview and that process.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader, Read, Write};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State};

pub mod startup;

use startup::{FailureKind, Preflight, Stage};

struct Bridge {
    child: Mutex<Option<BridgeProcess>>,
    stdin: Mutex<Option<std::process::ChildStdin>>,
    generation: Arc<AtomicU64>,
}

/// True once the preflight fallback log was actually written to %TEMP%.
static STARTUP_FALLBACK_LOG_WRITTEN: AtomicBool = AtomicBool::new(false);

struct BridgeProcess {
    child: Child,
    #[cfg(windows)]
    job: Option<windows_process::Job>,
}

impl BridgeProcess {
    fn terminate(&mut self) {
        #[cfg(windows)]
        if let Some(job) = self.job.as_ref() {
            job.terminate();
        } else {
            windows_process::kill_tree(self.child.id());
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for BridgeProcess {
    fn drop(&mut self) {
        self.terminate();
    }
}

#[cfg(windows)]
pub mod windows_process {
    use std::ffi::c_void;
    use std::io;
    use std::mem::size_of;
    use std::os::windows::io::AsRawHandle;
    use std::ptr::{null, null_mut};

    type Handle = *mut c_void;
    const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: u32 = 9;
    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x00002000;
    const ERROR_ALREADY_EXISTS: u32 = 183;

    #[repr(C)]
    struct BasicLimitInformation {
        per_process_user_time_limit: i64,
        per_job_user_time_limit: i64,
        limit_flags: u32,
        minimum_working_set_size: usize,
        maximum_working_set_size: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }

    #[repr(C)]
    struct IoCounters {
        read_operation_count: u64,
        write_operation_count: u64,
        other_operation_count: u64,
        read_transfer_count: u64,
        write_transfer_count: u64,
        other_transfer_count: u64,
    }

    #[repr(C)]
    struct ExtendedLimitInformation {
        basic_limit_information: BasicLimitInformation,
        io_info: IoCounters,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_used: usize,
        peak_job_memory_used: usize,
    }

    /// PROCESSENTRY32W layout for the Toolhelp32 process snapshot.
    #[repr(C)]
    struct ProcessEntry32 {
        size: u32,
        usage_count: u32,
        process_id: u32,
        default_heap_id: usize,
        module_id: u32,
        thread_count: u32,
        parent_process_id: u32,
        priority_class_base: i32,
        flags: u32,
        exe_file: [u16; 260],
    }

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn CreateJobObjectW(attributes: *const c_void, name: *const u16) -> Handle;
        fn SetInformationJobObject(
            job: Handle,
            information_class: u32,
            information: *const c_void,
            information_length: u32,
        ) -> i32;
        fn AssignProcessToJobObject(job: Handle, process: Handle) -> i32;
        fn TerminateJobObject(job: Handle, exit_code: u32) -> i32;
        fn CloseHandle(handle: Handle) -> i32;
        fn CreateMutexW(attributes: *const c_void, initial_owner: i32, name: *const u16) -> Handle;
        fn SetLastError(error: u32);
        fn GetLastError() -> u32;
        fn CreateToolhelp32Snapshot(flags: u32, process_id: u32) -> Handle;
        fn Process32FirstW(snapshot: Handle, entry: *mut ProcessEntry32) -> i32;
        fn Process32NextW(snapshot: Handle, entry: *mut ProcessEntry32) -> i32;
    }

    #[link(name = "user32")]
    unsafe extern "system" {
        fn MessageBoxW(window: Handle, text: *const u16, caption: *const u16, kind: u32) -> i32;
        fn FindWindowW(class: *const u16, title: *const u16) -> isize;
        fn ShowWindow(hwnd: isize, command: i32) -> i32;
        fn SetForegroundWindow(hwnd: isize) -> i32;
        fn IsWindow(hwnd: isize) -> i32;
        fn IsWindowVisible(hwnd: isize) -> i32;
    }

    const SW_RESTORE: i32 = 9;
    const TH32CS_SNAPPROCESS: u32 = 0x00000002;

    /// One entry of parent-process identification for diagnostics.
    ///
    /// Reads only public snapshot data (PID, image name). Never opens the
    /// parent's token and never reads its command line, which can contain
    /// secrets.
    fn parent_from_entry(entry: &ProcessEntry32) -> String {
        let name_len = entry
            .exe_file
            .iter()
            .position(|c| *c == 0)
            .unwrap_or(entry.exe_file.len());
        let name = String::from_utf16_lossy(&entry.exe_file[..name_len]);
        format!("PID {} ({})", entry.process_id, name)
    }

    /// "PID <ppid> (<exe name>)" of this process's parent, or a short
    /// explanation when the snapshot does not answer.
    ///
    /// Diagnostics-only: in a restricted environment this identifies *who*
    /// launched AXIOM (agent harness, sandbox launcher, explorer), which is
    /// exactly the fact the error dialog needs. It opens no handles to the
    /// parent and reads no command line.
    pub fn parent_process_info() -> String {
        let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) };
        if snapshot.is_null() {
            return "(снимок процессов недоступен)".to_string();
        }
        let own_pid = std::process::id();
        let mut entry: ProcessEntry32 = unsafe { std::mem::zeroed() };
        entry.size = size_of::<ProcessEntry32>() as u32;
        let mut own_found: Option<u32> = None;
        if unsafe { Process32FirstW(snapshot, &mut entry) } != 0 {
            loop {
                if entry.process_id == own_pid {
                    own_found = Some(entry.parent_process_id);
                    break;
                }
                if unsafe { Process32NextW(snapshot, &mut entry) } == 0 {
                    break;
                }
            }
        }
        let result = match own_found {
            None => "(собственный процесс не найден в снимке)".to_string(),
            Some(ppid) => {
                if ppid == 0 {
                    "PID 0 (нет родительского процесса)".to_string()
                } else {
                    let mut found = None;
                    let mut scan: ProcessEntry32 = unsafe { std::mem::zeroed() };
                    scan.size = size_of::<ProcessEntry32>() as u32;
                    if unsafe { Process32FirstW(snapshot, &mut scan) } != 0 {
                        loop {
                            if scan.process_id == ppid {
                                found = Some(parent_from_entry(&scan));
                                break;
                            }
                            if unsafe { Process32NextW(snapshot, &mut scan) } == 0 {
                                break;
                            }
                        }
                    }
                    found.unwrap_or_else(|| format!("PID {ppid} (имя недоступно)"))
                }
            }
        };
        unsafe { CloseHandle(snapshot) };
        result
    }

    /// Show and focus the already-running AXIOM window.
    ///
    /// Returns an error instead of pretending success when no window exists or
    /// the window cannot be brought to the foreground, so the caller never
    /// reports "the existing window is open" without evidence.
    pub fn focus_existing_window() -> io::Result<()> {
        let title: Vec<u16> = "AXIOM\0".encode_utf16().collect();
        let hwnd = unsafe { FindWindowW(std::ptr::null(), title.as_ptr()) };
        if hwnd == 0 || unsafe { IsWindow(hwnd) } == 0 {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "окно AXIOM не найдено (возможно, экземпляр ещё запускается или завершается)",
            ));
        }
        unsafe {
            ShowWindow(hwnd, SW_RESTORE);
            SetForegroundWindow(hwnd);
        }
        // Verify the window really is usable before claiming success.
        if unsafe { IsWindowVisible(hwnd) } == 0 {
            return Err(io::Error::new(
                io::ErrorKind::Other,
                "окно найдено, но осталось скрытым",
            ));
        }
        Ok(())
    }

    pub fn show_error(message: &str) {
        let text: Vec<u16> = message.encode_utf16().chain(std::iter::once(0)).collect();
        let caption: Vec<u16> = "AXIOM".encode_utf16().chain(std::iter::once(0)).collect();
        unsafe { MessageBoxW(null_mut(), text.as_ptr(), caption.as_ptr(), 0x10) };
    }

    pub struct Job(Handle);

    // The handle is owned and closed by Job; moving that ownership between
    // threads is safe, and Bridge protects access through a Mutex.
    unsafe impl Send for Job {}

    impl Job {
        pub fn new() -> io::Result<Self> {
            let handle = unsafe { CreateJobObjectW(null(), null()) };
            if handle.is_null() {
                return Err(io::Error::last_os_error());
            }
            let mut limits: ExtendedLimitInformation = unsafe { std::mem::zeroed() };
            limits.basic_limit_information.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let configured = unsafe {
                SetInformationJobObject(
                    handle,
                    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                    &limits as *const _ as *const c_void,
                    size_of::<ExtendedLimitInformation>() as u32,
                )
            };
            if configured == 0 {
                let error = io::Error::last_os_error();
                unsafe { CloseHandle(handle) };
                return Err(error);
            }
            Ok(Self(handle))
        }

        pub fn assign(&self, child: &std::process::Child) -> io::Result<()> {
            let assigned = unsafe { AssignProcessToJobObject(self.0, child.as_raw_handle()) };
            if assigned == 0 {
                Err(io::Error::last_os_error())
            } else {
                Ok(())
            }
        }

        pub fn terminate(&self) {
            unsafe { TerminateJobObject(self.0, 1) };
        }
    }

    impl Drop for Job {
        fn drop(&mut self) {
            unsafe { CloseHandle(self.0) };
        }
    }

    pub fn kill_tree(pid: u32) {
        use std::os::windows::process::CommandExt;
        let mut command = std::process::Command::new(r"C:\Windows\System32\taskkill.exe");
        command
            .arg("/PID")
            .arg(pid.to_string())
            .args(["/T", "/F"])
            .creation_flags(0x08000000) // CREATE_NO_WINDOW
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null());
        let _ = command.status();
    }

    pub struct SingleInstance(Handle);

    impl SingleInstance {
        pub fn acquire() -> io::Result<Option<Self>> {
            let name: Vec<u16> = "Local\\AXIOM.Desktop.1.0\0".encode_utf16().collect();
            unsafe { SetLastError(0) };
            let handle = unsafe { CreateMutexW(null(), 0, name.as_ptr()) };
            if handle.is_null() {
                return Err(io::Error::last_os_error());
            }
            if unsafe { GetLastError() } == ERROR_ALREADY_EXISTS {
                unsafe { CloseHandle(handle) };
                Ok(None)
            } else {
                Ok(Some(Self(handle)))
            }
        }
    }

    impl Drop for SingleInstance {
        fn drop(&mut self) {
            unsafe { CloseHandle(self.0) };
        }
    }
}

fn find_root() -> PathBuf {
    if let Ok(env_root) = std::env::var("AXIOM_DESKTOP_ROOT") {
        return PathBuf::from(env_root);
    }
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.clone());
        if let Some(parent) = cwd.parent() {
            candidates.push(parent.to_path_buf());
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            // dev build: <root>/desktop/src-tauri/target/debug
            for ancestor in dir.ancestors().skip(1).take(5) {
                candidates.push(ancestor.to_path_buf());
            }
        }
    }
    for candidate in candidates {
        if candidate
            .join("desktop/src-tauri/bridge/axiom_bridge.py")
            .exists()
        {
            return candidate;
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn find_python() -> String {
    if let Ok(py) = std::env::var("AXIOM_PYTHON") {
        if !py.trim().is_empty() {
            return py;
        }
    }
    // Prefer project-local environments so clones remain portable. A globally
    // installed interpreter is resolved below through PATH; no user-specific
    // filesystem path is embedded in the desktop shell.
    let root = find_root();
    for rel in [
        ".venv/Scripts/python.exe",
        ".venv/bin/python",
        "venv/Scripts/python.exe",
        "venv/bin/python",
    ] {
        let candidate = root.join(rel);
        if candidate.exists() {
            return candidate.to_string_lossy().to_string();
        }
    }
    for candidate in ["python.exe", "python", "py"] {
        let mut probe = Command::new(candidate);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            probe.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        if probe
            .arg("--version")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok()
        {
            return candidate.to_string();
        }
    }
    "python".to_string()
}

fn spawn_bridge(app: &AppHandle) -> Result<(), String> {
    let state: State<Bridge> = app.state();
    let generation_state = Arc::clone(&state.generation);
    let generation = state.generation.fetch_add(1, Ordering::AcqRel) + 1;
    let python = find_python();
    // 1. Repository layout (dev): <root>/desktop/src-tauri/bridge/axiom_bridge.py
    // 2. Bundled layout (installed): the bridge script ships as a Tauri
    //    resource (tauri.conf.json `bundle.resources`) next to the exe.
    let mut bridge_py: Option<PathBuf> = None;
    let mut src_dir: Option<PathBuf> = None;
    let repo_root = find_root();
    let repo_bridge = repo_root.join("desktop/src-tauri/bridge/axiom_bridge.py");
    if repo_bridge.exists() {
        bridge_py = Some(repo_bridge);
        src_dir = Some(repo_root.join("src"));
    }
    if bridge_py.is_none() {
        if let Ok(resource_dir) = app.path().resource_dir() {
            let bundled = resource_dir.join("bridge/axiom_bridge.py");
            if bundled.exists() {
                bridge_py = Some(bundled);
            }
        }
    }
    let bridge_py = bridge_py
        .ok_or_else(|| "bridge script not found (repo layout and bundled resources)".to_string())?;

    let mut cmd = Command::new(&python);
    // AXIOM is a GUI app: console subsystem children (Python/core tools) must not
    // flash a terminal window on Windows.
    #[cfg(target_os = "windows")]
    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    cmd.arg("-u").arg(&bridge_py);
    if let Some(src) = src_dir {
        // Repository layout: import the working-tree package. An installed
        // bundle has no src/ — the `axiom` package must be installed in the
        // Python environment (see docs/gui.md).
        cmd.env("PYTHONPATH", &src);
    }
    // Give the core a private data home unless the user already set one.
    if std::env::var("AXIOM_HOME").is_err() {
        let home = std::env::var("AXIOM_DESKTOP_ROOT")
            .map(|root| PathBuf::from(root).join("desktop/data"))
            .unwrap_or_else(|_| repo_root.join("desktop/data"));
        if home.parent().is_some() && home.parent().map(|p| p.exists()).unwrap_or(false) {
            let _ = std::fs::create_dir_all(&home);
            cmd.env("AXIOM_HOME", &home);
        }
        // Bundled installs without a repo layout keep the default ~/.axiom.
    }
    cmd.env("PYTHONIOENCODING", "utf-8");
    cmd.env("PYTHONUTF8", "1");
    // Workspace filesystem tools operate on the project AXIOM was launched from
    // (the repo root found above) unless the user set an explicit workspace.
    if std::env::var("AXIOM_WORKSPACE").is_err() {
        cmd.env("AXIOM_WORKSPACE", &repo_root);
    }
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(windows)]
    let mut job = windows_process::Job::new().ok();
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("failed to start Python core ({}): {}", python, e))?;
    #[cfg(windows)]
    {
        if job
            .as_ref()
            .is_some_and(|group| group.assign(&child).is_err())
        {
            job = None;
        }
    }
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| "no stdin for bridge".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "no stdout for bridge".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "no stderr for bridge".to_string())?;

    // Forward every core line to the webview.
    let emitter = app.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            if generation_state.load(Ordering::Acquire) != generation {
                break;
            }
            let payload: Value = match serde_json::from_str(&line) {
                Ok(v) => v,
                Err(_) => Value::String(line.clone()),
            };
            let _ = emitter.emit("bridge://line", payload);
        }
        // A restart may replace the child before this reader observes EOF.
        // Do not let the old process report the newly started core as dead.
        if generation_state.load(Ordering::Acquire) == generation {
            let _ = emitter.emit(
                "bridge://line",
                serde_json::json!({
                    "type": "reply",
                    "req": 0,
                    "ok": false,
                    "error": "bridge-exited"
                }),
            );
        }
    });

    let err_app = app.clone();
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stderr);
        let mut buf = [0u8; 4096];
        loop {
            match reader.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    let text = String::from_utf8_lossy(&buf[..n]).to_string();
                    let _ = err_app.emit("bridge://stderr", text);
                }
            }
        }
    });

    *state.child.lock().unwrap() = Some(BridgeProcess {
        child,
        #[cfg(windows)]
        job,
    });
    *state.stdin.lock().unwrap() = Some(stdin);
    Ok(())
}

#[tauri::command]
fn bridge_request(state: State<'_, Bridge>, payload: Value) -> Result<Value, String> {
    let mut guard = state.stdin.lock().unwrap();
    let stdin = guard
        .as_mut()
        .ok_or_else(|| "bridge is not running".to_string())?;
    let mut line = serde_json::to_string(&payload).map_err(|e| e.to_string())?;
    line.push('\n');
    stdin
        .write_all(line.as_bytes())
        .and_then(|_| stdin.flush())
        .map_err(|e| format!("bridge write failed: {}", e))?;
    Ok(Value::Null)
}

#[tauri::command]
fn bridge_restart(app: AppHandle) -> Result<(), String> {
    {
        let state: State<Bridge> = app.state();
        // Invalidate the old stdout reader before terminating the child. The
        // new spawn advances the generation again before it starts its reader.
        state.generation.fetch_add(1, Ordering::AcqRel);
        state.child.lock().unwrap().take();
        *state.stdin.lock().unwrap() = None;
    }
    spawn_bridge(&app)
}

/// Frontend readiness acknowledgement.
///
/// The bundled frontend calls this once it has executed, so `frontend-loaded`
/// reflects the real UI rather than the mere presence of a window/HWND. When
/// `core` is true the UI also completed a real round-trip to the Python core,
/// which promotes startup to `bridge-ready`.
#[tauri::command]
fn frontend_ready(app: AppHandle, core: Option<bool>) -> Result<(), String> {
    let core_ok = core.unwrap_or(false);
    startup::mark(Stage::FrontendLoaded);
    if core_ok {
        startup::mark(Stage::BridgeReady);
    }
    startup::info(
        "frontend-loaded",
        &format!(
            "frontend acknowledged readiness (core_round_trip={core_ok}) stage={}",
            startup::current_stage().as_str()
        ),
    );
    // A frontend that acknowledged but lost the window must not keep an
    // invisible instance alive; only this app's own window is touched.
    if core_ok && app.get_webview_window("main").is_none() {
        return Err("main window disappeared after startup".to_string());
    }
    Ok(())
}

/// Open an http(s) link in the user's real browser.
///
/// The webview must never navigate away from the app, and AXIOM ships no
/// browser plugin, so links are handed to the OS directly.
#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    let lower = url.trim().to_ascii_lowercase();
    if !(lower.starts_with("http://")
        || lower.starts_with("https://")
        || lower.starts_with("mailto:"))
    {
        return Err("only http(s) and mailto links can be opened".to_string());
    }
    let target = url.trim().to_string();
    #[cfg(target_os = "windows")]
    let spawn = {
        use std::ffi::c_void;
        type Hwnd = *mut c_void;
        #[link(name = "shell32")]
        unsafe extern "system" {
            fn ShellExecuteW(
                hwnd: Hwnd,
                operation: *const u16,
                file: *const u16,
                parameters: *const u16,
                directory: *const u16,
                show_command: i32,
            ) -> Hwnd;
        }
        let operation: Vec<u16> = "open\0".encode_utf16().collect();
        let target_wide: Vec<u16> = target.encode_utf16().chain(Some(0)).collect();
        let result = unsafe {
            ShellExecuteW(
                std::ptr::null_mut(),
                operation.as_ptr(),
                target_wide.as_ptr(),
                std::ptr::null(),
                std::ptr::null(),
                1,
            )
        };
        if result as isize > 32 {
            Ok(())
        } else {
            Err(std::io::Error::other("Windows could not open the link"))
        }
    };
    #[cfg(target_os = "macos")]
    let spawn = Command::new("open").arg(&target).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let spawn = Command::new("xdg-open").arg(&target).spawn();
    spawn.map_err(|e| format!("could not open the link: {e}"))
}

/// Open a native folder picker and return the chosen directory (if any).
#[tauri::command]
fn pick_folder(app: AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    let selection = app
        .dialog()
        .file()
        .set_title("Открыть проект — выбрать папку")
        .blocking_pick_folder();
    Ok(selection.map(|p| p.to_string()))
}

/// Close AXIOM (used by the `/exit` command and the window-close shortcut).
#[tauri::command]
fn quit_app(app: AppHandle) {
    app.exit(0);
}

// --------------------------------------------------------------- tray (W3.3)
/// Shared tray state: tooltip text and the running-task count label.
struct TrayState {
    running: Mutex<u32>,
}

/// Create the tray icon: Open AXIOM / Quit, live tooltip with the honest
/// background-task count pushed from the webview (`tray_set_state`).
fn setup_tray(app: &AppHandle) -> Result<(), tauri::Error> {
    use tauri::menu::{Menu, MenuItem};

    app.manage(TrayState {
        running: Mutex::new(0),
    });
    let show = MenuItem::with_id(app, "axiom-tray-show", "Открыть AXIOM", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "axiom-tray-quit", "Выйти из AXIOM", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &quit])?;
    let icon = app
        .default_window_icon()
        .cloned()
        .expect("AXIOM ships a window icon");
    let tray = tauri::tray::TrayIconBuilder::with_id("axiom-tray")
        .icon(icon)
        .menu(&menu)
        .show_menu_on_left_click(false)
        .tooltip("AXIOM")
        .on_menu_event(|app, event| match event.id().as_ref() {
            "axiom-tray-show" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.unminimize();
                    let _ = window.set_focus();
                }
            }
            "axiom-tray-quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // Left click opens the window — the classic tray behaviour.
            if let tauri::tray::TrayIconEvent::Click {
                button: tauri::tray::MouseButton::Left,
                button_state: tauri::tray::MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.unminimize();
                    let _ = window.set_focus();
                }
            }
        })
        .build(app)?;
    app.manage(tray);
    Ok(())
}

/// W3.3: the webview pushes the real running-task count + tooltip text
/// (built from the core i18n catalog, so it follows the UI language).
#[tauri::command]
fn tray_set_state(app: AppHandle, running: u32, tooltip: String) -> Result<(), String> {
    let state = app.try_state::<TrayState>();
    let tray = app.try_state::<tauri::tray::TrayIcon>();
    if let Some(state) = &state {
        *state.running.lock().unwrap() = running;
    }
    if let Some(tray) = &tray {
        tray.set_tooltip(Some(tooltip.as_str()))
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Stage-1 preflight wrapper: run the checks, then open the startup log.
///
/// Returns the resolved plan on success. On failure the caller gets the
/// classified reason plus everything the log already recorded, so the native
/// dialog and the log never disagree.
fn preflight_profile() -> Result<startup::ProfilePlan, PreflightFailure> {
    let integrity = startup::integrity();
    let identifier = "app.axiom.desktop";
    match startup::preflight(identifier) {
        Preflight::Ready(plan) => {
            startup::mark(Stage::Preflight);
            if let Some(path) = startup::init_logging(&plan.dir) {
                startup::info(
                    "preflight",
                    &format!(
                        "integrity={} logging active at {} (origin={}, disposable={})",
                        startup::integrity_log_field(integrity),
                        path.display(),
                        plan.origin,
                        plan.disposable
                    ),
                );
            } else {
                startup::warn(
                    "preflight",
                    "startup log unavailable; continuing without a file log",
                );
            }
            Ok(plan)
        }
        Preflight::Failed {
            kind,
            detail,
            report,
        } => {
            startup::mark(Stage::Preflight);
            // Collected here so the same string serves both the fallback
            // record and the dialog. Public snapshot data only (see
            // `parent_process_info`); no parent token, no command line.
            let parent = windows_process::parent_process_info();
            // The log could not be opened at the profile root (that is often
            // the very failure), so keep the record in a temp-side file too.
            if startup::log_path().is_none() {
                let fallback = std::env::temp_dir().join("axiom-preflight-failed.log");
                let record = format!(
                    "[{}][integrity={}] kind={} detail={}\nprofile={}\nenv_overrides={}\n\
                     free_space_ok={}\nparent={}\n",
                    startup::startup_id(),
                    startup::integrity_log_field(report.integrity),
                    kind.as_str(),
                    detail,
                    report.profile_dir.display(),
                    report.env_overrides,
                    report.free_space_ok,
                    parent
                );
                // Record whether the fallback itself was written, so a missing
                // backup log is explainable from the code path (the dialog
                // then points to it only when it actually exists).
                let fallback_ok = std::fs::write(&fallback, record).is_ok();
                // A GUI-subsystem process has no console; the only way to
                // surface the fallback outcome before Tauri exists is the
                // dialog itself (the main path below does that).
                if fallback_ok {
                    STARTUP_FALLBACK_LOG_WRITTEN.store(true, Ordering::Release);
                }
            }
            // The dialog repeats the log path so the user can inspect it.
            startup::error("preflight", &format!("{detail} ({})", kind.as_str()));
            Err(PreflightFailure {
                kind,
                detail,
                report,
                parent,
            })
        }
    }
}

/// Everything the native error dialog needs, kept next to the preflight.
struct PreflightFailure {
    kind: FailureKind,
    detail: String,
    /// Retained for diagnostics; the dialog path is built from the log file.
    report: Box<startup::PreflightReport>,
    /// "PID <ppid> (<name>)" of the launcher, collected during preflight so
    /// the fallback record and the dialog never disagree.
    parent: String,
}

/// Dialog line for the measured integrity level, or an honest
/// "not measured" line carrying the query failure reason. Unknown must
/// never be rendered as a measured level.
fn integrity_dialog_line(integrity: startup::Integrity) -> String {
    match integrity {
        startup::Integrity::Unknown => format!(
            "Уровень целостности процесса: не измерен (запрос к маркеру доступа \
             не удался: {})",
            startup::integrity_query_error().unwrap_or("причина недоступна")
        ),
        measured => format!(
            "Измеренный уровень целостности процесса (по маркеру доступа): {}",
            measured.as_str()
        ),
    }
}

/// Factual dialog lines built from what the preflight already collected.
///
/// Pure formatting over a [`startup::PreflightReport`] plus the parent string
/// (computed by the caller, so it stays stub-able in tests). When BOTH the
/// profile log and the %TEMP% fallback failed, these lines are the ONLY
/// surviving diagnostics, so every collected fact is shown: env overrides
/// (already redacted by `describe`), free-space evidence, and the launcher
/// identity. The write-probe path (with the PID) is already inside `detail`.
fn preflight_dialog_lines(report: &startup::PreflightReport, parent: &str) -> String {
    let line_profiles = format!(
        "Путь профиля: {}\nЗапись в профиль: {}\nСвободное место: {}",
        report.profile_dir.display(),
        if report.writable { "доступна" } else { "ОТКАЗАНО" },
        if report.free_space_ok {
            "достаточно"
        } else {
            "не проверено / недостаточно"
        }
    );
    let line_env = format!("Переменные окружения WebView2: {}", report.env_overrides);
    let line_parent = format!("Родительский процесс (кто запустил AXIOM): {parent}");
    format!("{line_profiles}\n{line_env}\n{line_parent}")
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    startup::init_startup_id();
    // Stage 1 runs BEFORE Tauri is built: Tauri creates the main window inside
    // its own setup() and panics opaquely when the WebView2 profile directory
    // is unusable, so the check has to happen first and report a real cause.
    match preflight_profile() {
        // The plan is only needed for logging inside the preflight itself;
        // Tauri resolves the very same per-user directory on its own.
        Ok(_plan) => {}
        Err(plan) => {
            // No window and no webview exist yet, so the only way to reach the
            // user is a native dialog; the details also land in the log.
            startup::error(
                "preflight",
                &format!("{} ({})", plan.detail, plan.kind.as_str()),
            );
            let report = &plan.report;
            let line_integrity = integrity_dialog_line(report.integrity);
            let line_facts = preflight_dialog_lines(report, &plan.parent);
            let line_cause = format!(
                "Предполагаемая причина отказа: {}{}",
                plan.kind.as_str(),
                if plan.kind == FailureKind::Integrity {
                    // Integrity is a hypothesis, not a measured denial cause.
                    " (гипотеза: среда запуска с Low Integrity; фактический отказ — write probe, см. Подробности)"
                } else {
                    ""
                }
            );
            let log_line = startup::log_path()
                .map(|p| p.display().to_string())
                .unwrap_or_else(|| {
                    if STARTUP_FALLBACK_LOG_WRITTEN.load(std::sync::atomic::Ordering::Acquire) {
                        match std::env::var("TEMP") {
                            Ok(temp) => {
                                format!("{temp}\\axiom-preflight-failed.log (резервный лог)")
                            }
                            Err(_) => "(резервный лог записан, путь неизвестен)".to_string(),
                        }
                    } else {
                        "(основной и резервный логи недоступны)".to_string()
                    }
                });
            windows_process::show_error(&format!(
                "AXIOM не может запуститься.\n\n{}\n\n{}\n\n{}\n\n{}\nПодробности: {}\n\nЛог запуска: {}",
                startup::remediation(&plan.kind),
                line_integrity,
                line_facts,
                line_cause,
                plan.detail,
                log_line,
            ));
            std::process::exit(20);
        }
    };
    // A GUI-subsystem process has no console, so a panic would surface as an
    // opaque exit code. Record it in the same startup log instead.
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        startup::error("panic", &format!("{info} at {:#?}", info.location()));
        default_hook(info);
    }));
    // WebView2 honours the Windows system proxy. AXIOM's frontend is bundled
    // and every API request travels over Tauri IPC (`ipc:`) to the Python
    // core, so the webview never needs to reach a loopback dev server or any
    // other localhost endpoint through the system proxy.
    #[cfg(windows)]
    let _single_instance = match windows_process::SingleInstance::acquire() {
        Ok(Some(instance)) => instance,
        Ok(None) => {
            // Another instance owns the guard. Focus its window, but only
            // report success when a usable window was actually shown.
            startup::info("single-instance", "another instance holds the guard");
            match windows_process::focus_existing_window() {
                Ok(()) => {
                    startup::info("single-instance", "existing window focused");
                    return;
                }
                Err(err) => {
                    startup::warn("single-instance", &format!("focus failed: {err}"));
                    windows_process::show_error(&format!(
                        "AXIOM уже запущен, но его окно не удалось показать: {err}\n\n\
                         Если окно скрыто в трее, откройте AXIOM через значок в трее."
                    ));
                    return;
                }
            }
        }
        Err(err) => {
            windows_process::show_error(&format!("Не удалось проверить экземпляр AXIOM: {err}"));
            return;
        }
    };
    // The profile directory is already prepared by the preflight; Tauri uses
    // the same per-user folder for the WebView2 environment.
    // In development, `beforeDevCommand` builds the frontend with Vite in watch
    // mode and Tauri's built-in dev server serves the `dist/` output — no dev
    // server port and no race for one. Rust must not start a second frontend
    // process; the production build embeds the frontend and needs none at all.
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            startup::mark(Stage::RuntimeInit);
            let handle = app.handle().clone();
            // Tauri builds the config window before this closure runs, so its
            // existence is evidence for `native-window` only. Real readiness
            // still requires the frontend acknowledgement below.
            match handle.get_webview_window("main") {
                Some(window) => {
                    startup::info(
                        Stage::NativeWindow.as_str(),
                        &format!(
                            "main window present label={} visible={:?}",
                            window.label(),
                            window.is_visible()
                        ),
                    );
                    startup::mark(Stage::NativeWindow);
                }
                None => startup::error(
                    Stage::NativeWindow.as_str(),
                    "main window missing after Tauri setup",
                ),
            }
            app.manage(Bridge {
                child: Mutex::new(None),
                stdin: Mutex::new(None),
                generation: Arc::new(AtomicU64::new(0)),
            });
            // W3.3: tray with Open/Quit; the tooltip mirrors the live
            // background-task count pushed from the webview.
            if let Err(err) = setup_tray(app.handle()) {
                startup::warn("tray", &format!("tray setup failed: {err}"));
            }
            if let Err(err) = spawn_bridge(&handle) {
                startup::error("bridge", &format!("bridge startup failed: {err}"));
                let _ = handle.emit("bridge://stderr", err.clone());
                // Unblock any pending frontend requests instead of hanging.
                let _ = handle.emit(
                    "bridge://line",
                    serde_json::json!({
                        "type": "reply",
                        "req": 0,
                        "ok": false,
                        "error": format!("bridge-exited: {err}")
                    }),
                );
            } else {
                startup::info("bridge", "core process started; awaiting first reply");
            }
            // Bounded readiness watchdog. A live process or a valid HWND is
            // not readiness: if the frontend never acknowledges, the user gets
            // a real error instead of an invisible instance that would block
            // every future launch through the single-instance guard.
            {
                let watch = handle.clone();
                std::thread::spawn(move || {
                    let deadline = startup::READY_DEADLINE;
                    let started = std::time::Instant::now();
                    while started.elapsed() < deadline {
                        if startup::is_ready() {
                            startup::info(
                                "watchdog",
                                &format!("startup complete in {}ms", started.elapsed().as_millis()),
                            );
                            return;
                        }
                        std::thread::sleep(std::time::Duration::from_millis(250));
                    }
                    let stage = startup::current_stage();
                    startup::error(
                        "watchdog",
                        &format!(
                            "readiness deadline exceeded at stage={} after {}ms",
                            stage.as_str(),
                            deadline.as_millis()
                        ),
                    );
                    windows_process::show_error(&format!(
                        "AXIOM запустился, но интерфейс не загрузился.\n\n\
                         Текущая стадия запуска: {}\n\n\
                         Закройте AXIOM полностью (включая значок в трее) и запустите снова.\n\n\
                         Подробности: {}",
                        stage.as_str(),
                        startup::log_path()
                            .map(|p| p.display().to_string())
                            .unwrap_or_else(|| "(лог недоступен)".to_string()),
                    ));
                    // Leaving the process releases the single-instance guard;
                    // only this application's own resources are torn down.
                    watch.exit(21);
                });
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            match event {
                tauri::WindowEvent::CloseRequested { api, .. } => {
                    // W3.3: closing the window hides it to the tray instead of
                    // killing the app - background tasks keep running. A real
                    // exit stays available through the tray menu and /exit.
                    if window.label() == "main" {
                        api.prevent_close();
                        match window.hide() {
                            Ok(()) => {
                                startup::info("window", "main CloseRequested: hidden to tray")
                            }
                            Err(err) => startup::warn(
                                "window",
                                &format!("main CloseRequested: hide failed ({err})"),
                            ),
                        }
                    }
                }
                tauri::WindowEvent::Destroyed => {
                    startup::info(
                        "window",
                        &format!("event Destroyed label={}", window.label()),
                    );
                    let state = window.state::<Bridge>();
                    state.child.lock().unwrap().take();
                    *state.stdin.lock().unwrap() = None;
                }
                _ => {}
            }
        })
        .invoke_handler(tauri::generate_handler![
            bridge_request,
            bridge_restart,
            frontend_ready,
            open_url,
            pick_folder,
            quit_app,
            tray_set_state
        ])
        .build(tauri::generate_context!())
        .and_then(|app| {
            startup::info("runtime-init", "tauri build Ok; entering run loop");
            app.run(|_, _| {});
            Ok(())
        })
        .unwrap_or_else(|err| {
            // Preserve the real build/run error chain; never reduce it to a
            // generic message, and keep the original HRESULT in the log.
            let chain = format!("{err:?}");
            let kind = startup::record_failure(Stage::RuntimeInit, &chain);
            // The window may be unusable here, so report natively as well.
            windows_process::show_error(&format!(
                "AXIOM не смог создать окно.\n\nПричина: {}\nПодробности: {}\n\n{}",
                kind.as_str(),
                chain,
                startup::remediation(&kind),
            ));
            std::process::exit(22);
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dialog_shows_unknown_as_not_measured_with_reason() {
        let line = integrity_dialog_line(startup::Integrity::Unknown);
        assert!(line.contains("не измерен"), "got {line}");
        assert!(line.contains("не удался"), "got {line}");
        assert!(!line.contains("medium"), "got {line}");
    }

    #[test]
    fn dialog_shows_measured_levels_verbatim() {
        for (level, name) in [
            (startup::Integrity::Untrusted, "untrusted"),
            (startup::Integrity::Low, "low"),
            (startup::Integrity::Medium, "medium"),
            (startup::Integrity::High, "high"),
            (startup::Integrity::System, "system"),
        ] {
            let line = integrity_dialog_line(level);
            assert!(line.contains(name), "got {line}");
            assert!(!line.contains("не измерен"), "got {line}");
        }
    }

    fn sample_report() -> startup::PreflightReport {
        startup::PreflightReport {
            integrity: startup::Integrity::Low,
            profile_dir: PathBuf::from(r"C:\Users\a\AppData\Roaming\app.axiom.desktop"),
            disposable: false,
            origin: "production",
            env_overrides: "none".to_string(),
            writable: false,
            free_space_ok: false,
        }
    }

    #[test]
    fn dialog_lines_include_env_overrides_free_space_and_parent() {
        let mut report = sample_report();
        report.env_overrides =
            "WEBVIEW2_USER_DATA_FOLDER=C:\\Temp\\wv, WEBVIEW2_BROWSER_EXECUTION_DIR=none"
                .to_string();
        let lines = preflight_dialog_lines(&report, "PID 4242 (cmd.exe)");
        assert!(lines.contains("Переменные окружения WebView2: "), "got {lines}");
        assert!(lines.contains("WEBVIEW2_USER_DATA_FOLDER"), "got {lines}");
        assert!(lines.contains("PID 4242 (cmd.exe)"), "got {lines}");
        assert!(lines.contains("Родительский процесс"), "got {lines}");
        assert!(lines.contains("Свободное место: "), "got {lines}");
        assert!(lines.contains("не проверено / недостаточно"), "got {lines}");
        assert!(lines.contains("Запись в профиль: ОТКАЗАНО"), "got {lines}");
    }

    #[test]
    fn dialog_lines_show_free_space_ok_without_overrides() {
        let mut report = sample_report();
        report.free_space_ok = true;
        let lines = preflight_dialog_lines(&report, "PID 7 (explorer.exe)");
        assert!(lines.contains("Свободное место: достаточно"), "got {lines}");
        assert!(lines.contains("Переменные окружения WebView2: none"), "got {lines}");
        assert!(lines.contains("PID 7 (explorer.exe)"), "got {lines}");
    }

    #[cfg(windows)]
    #[test]
    fn parent_process_info_is_well_formed() {
        // The toolhelp snapshot must answer for our own parent; the exact
        // PID/name is environment-specific, but the shape is contractual.
        let info = windows_process::parent_process_info();
        assert!(
            info.starts_with("PID ") || info.starts_with('('),
            "got {info}"
        );
    }
}
