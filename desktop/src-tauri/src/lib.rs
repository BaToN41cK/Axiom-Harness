//! AXIOM desktop shell.
//!
//! Spawns the real Python core (ChatSession: Ollama, streaming, tools,
//! history) as a JSONL stdio subprocess and shuttles requests/events between
//! the Tauri webview and that process.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State};

struct Bridge {
    child: Mutex<Option<BridgeProcess>>,
    stdin: Mutex<Option<std::process::ChildStdin>>,
    generation: Arc<AtomicU64>,
}

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
    }

    #[link(name = "user32")]
    unsafe extern "system" {
        fn MessageBoxW(window: Handle, text: *const u16, caption: *const u16, kind: u32) -> i32;
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
        if candidate.join("desktop/src-tauri/bridge/axiom_bridge.py").exists() {
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
            .status().is_ok() {
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
        if job.as_ref().is_some_and(|group| group.assign(&child).is_err()) {
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

/// Open an http(s) link in the user's real browser.
///
/// The webview must never navigate away from the app, and AXIOM ships no
/// browser plugin, so links are handed to the OS directly.
#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    let lower = url.trim().to_ascii_lowercase();
    if !(lower.starts_with("http://") || lower.starts_with("https://") || lower.starts_with("mailto:")) {
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
                std::ptr::null_mut(), operation.as_ptr(), target_wide.as_ptr(),
                std::ptr::null(), std::ptr::null(), 1,
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(windows)]
    let _single_instance = match windows_process::SingleInstance::acquire() {
        Ok(Some(instance)) => instance,
        Ok(None) => {
            windows_process::show_error("AXIOM уже запущен.");
            return;
        }
        Err(err) => {
            windows_process::show_error(&format!("Не удалось проверить экземпляр AXIOM: {err}"));
            return;
        }
    };
    // In development, Tauri's `beforeDevCommand` owns the single Vite
    // process. Starting another server here deadlocks Tauri's own readiness
    // wait and can also race for port 1420. The production build embeds the
    // frontend and does not need a dev server.
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let handle = app.handle().clone();
            app.manage(Bridge {
                child: Mutex::new(None),
                stdin: Mutex::new(None),
                generation: Arc::new(AtomicU64::new(0)),
            });
            if let Err(err) = spawn_bridge(&handle) {
                eprintln!("bridge startup error: {err}");
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
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<Bridge>();
                state.child.lock().unwrap().take();
                state.stdin.lock().unwrap().take();
            }
        })
        .invoke_handler(tauri::generate_handler![
            bridge_request,
            bridge_restart,
            open_url,
            pick_folder,
            quit_app
        ])
        .run(tauri::generate_context!())
        .expect("error while running AXIOM");
}

