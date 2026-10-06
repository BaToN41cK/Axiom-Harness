//! Startup preflight, bounded startup stages and production-safe logging.
//!
//! Stage 1 of the hardening work: everything in [`preflight`] runs *before*
//! Tauri creates the WebView2 environment, because Tauri builds the main
//! window inside its own `setup()` (tauri 2.11 `app.rs::setup`) and panics
//! with an opaque message when the profile directory is unusable. A preflight
//! turns that class of failure into an explicit, actionable native error.
//!
//! Security rules honoured by this module:
//! * never elevate privileges, never relax ACLs or integrity labels;
//! * never silently relocate the production profile;
//! * the production profile stays per-user and app-specific;
//! * a development profile is opt-in through an explicit env var only.
//!
//! Stage-2 additions (startup stages, readiness acknowledgement, bounded
//! deadline) live in [`Stage`] and are wired by `lib.rs`.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU8, Ordering};
use std::sync::{Mutex, Once, OnceLock};
use std::time::Instant;

/// Roll the log file over once it grows past 1 MiB.
const LOG_MAX_BYTES: u64 = 1024 * 1024;
/// Keep this many rolled-over files next to the active one.
const LOG_MAX_FILES: usize = 4;
/// Readiness deadline: the frontend must acknowledge within this window.
pub const READY_DEADLINE: std::time::Duration = std::time::Duration::from_secs(45);

/// Env var through which the Python launcher (`axiom --gui`) passes the full
/// path of the per-launch readiness marker file. Double-click starts do not
/// set it, so the marker is purely opt-in instrumentation for supervised
/// launches and never a startup dependency.
const LAUNCH_READY_FILE_ENV: &str = "AXIOM_LAUNCH_READY_FILE";

static START_INSTANT: OnceLock<Instant> = OnceLock::new();
static STARTUP_ID: OnceLock<String> = OnceLock::new();
static LOG_PATH: OnceLock<PathBuf> = OnceLock::new();
static LOG_FILE: Mutex<Option<std::fs::File>> = Mutex::new(None);

/// Monotonic milliseconds since process start, or `-1` before init.
pub fn uptime_ms() -> i64 {
    match START_INSTANT.get() {
        Some(start) => start.elapsed().as_millis() as i64,
        None => -1,
    }
}

/// Unique per-process id correlating every log line of one launch.
pub fn startup_id() -> &'static str {
    STARTUP_ID.get().map(String::as_str).unwrap_or("unknown")
}

/// Record process start and build the startup id. Call first, before logging.
pub fn init_startup_id() {
    let _ = START_INSTANT.set(Instant::now());
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    let _ = STARTUP_ID.set(format!("{}-{}", stamp, std::process::id()));
}
// ---------------------------------------------------------------- redaction
/// Keys whose *value* part must never reach the log file.
const SENSITIVE_KEYS: [&str; 12] = [
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "session_token",
    "auth",
    "token",
];

/// Mask credential-shaped values while keeping the key readable, then mask
/// long opaque blobs (base64/hex tokens). Defence in depth: the startup log
/// must stay useful for diagnosis without becoming a token store.
pub fn redact(input: &str) -> String {
    /// Only a key immediately before the separator counts; a long sentence
    /// fragment ending in ':' must not swallow the rest of the message.
    const MAX_KEY_LEN: usize = 40;
    let mut out = String::with_capacity(input.len());
    let mut segment_start = 0usize;
    for (index, ch) in input.char_indices() {
        if ch != '=' && ch != ':' {
            continue;
        }
        let segment = &input[segment_start..index];
        let lower = segment.to_ascii_lowercase();
        let sensitive =
            segment.len() <= MAX_KEY_LEN && SENSITIVE_KEYS.iter().any(|key| lower.contains(key));
        out.push_str(segment);
        out.push(ch);
        segment_start = index + 1;
        if !sensitive {
            continue;
        }
        out.push_str("<redacted>");
        // Skip the value text; stop at the first delimiter.
        while segment_start < input.len() {
            let rest = input[segment_start..].chars().next().unwrap_or(' ');
            if rest == ' ' || rest == ',' || rest == ';' || rest == '\n' {
                break;
            }
            segment_start += rest.len_utf8();
        }
        if segment_start < input.len() {
            let boundary = input[segment_start..].chars().next().unwrap_or(' ');
            out.push(boundary);
            segment_start += boundary.len_utf8();
        }
    }
    out.push_str(&input[segment_start..]);
    mask_long_blobs(&out)
}

/// Replace runs of >= 48 base64/hex characters with a short prefix.
fn mask_long_blobs(text: &str) -> String {
    const MIN_RUN: usize = 48;
    let mut out = String::with_capacity(text.len());
    let mut run = String::new();
    let is_token_char =
        |c: char| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '+' | '/' | '=');
    fn flush(run: &mut String, out: &mut String) {
        if run.len() >= MIN_RUN {
            out.push_str(&run[..8]);
            out.push_str("...<redacted>");
        } else {
            out.push_str(run);
        }
        run.clear();
    }
    for ch in text.chars() {
        if is_token_char(ch) {
            run.push(ch);
        } else {
            flush(&mut run, &mut out);
            out.push(ch);
        }
    }
    flush(&mut run, &mut out);
    out
}

/// Replace user-specific path roots with stable placeholders.
fn redact_paths(text: &str) -> String {
    let mut out = text.to_string();
    if let Ok(profile) = std::env::var("USERPROFILE") {
        if !profile.is_empty() {
            out = out.replace(&profile, "%USERPROFILE%");
        }
    }
    if let Ok(local) = std::env::var("LOCALAPPDATA") {
        if !local.is_empty() {
            out = out.replace(&local, "%LOCALAPPDATA%");
        }
    }
    if let Ok(temp) = std::env::var("TEMP") {
        if !temp.is_empty() {
            out = out.replace(&temp, "%TEMP%");
        }
    }
    out
}
// ------------------------------------------------------------- file logging
/// Prepare the production log file inside the resolved profile root.
///
/// The log deliberately lives in the per-user application directory, never in
/// the repository or build output. Returns the active file path.
pub fn init_logging(profile_root: &Path) -> Option<PathBuf> {
    let logs_dir = profile_root.join("logs");
    if std::fs::create_dir_all(&logs_dir).is_err() {
        return None;
    }
    let path = logs_dir.join("axiom-startup.log");
    rotate_if_needed(&path);
    let file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .ok()?;
    if let Ok(mut guard) = LOG_FILE.lock() {
        *guard = Some(file);
    }
    let _ = LOG_PATH.set(path.clone());
    Some(path)
}

/// Path of the active log file, if logging was initialised.
pub fn log_path() -> Option<&'static Path> {
    LOG_PATH.get().map(PathBuf::as_path)
}

/// Bounded rotation: `axiom-startup.log` -> `.log.1` -> ... dropping the oldest.
fn rotate_if_needed(path: &Path) {
    let too_big = std::fs::metadata(path)
        .map(|m| m.len() >= LOG_MAX_BYTES)
        .unwrap_or(false);
    if !too_big {
        return;
    }
    let _ = std::fs::remove_file(path.with_extension(format!("log.{LOG_MAX_FILES}")));
    for index in (1..LOG_MAX_FILES).rev() {
        let from = path.with_extension(format!("log.{index}"));
        if from.exists() {
            let _ = std::fs::rename(&from, path.with_extension(format!("log.{}", index + 1)));
        }
    }
    let _ = std::fs::rename(path, path.with_extension("log.1"));
}

/// Write one structured startup log line (redacted, timestamped, stage-tagged).
pub fn log(level: &str, stage: &str, message: &str) {
    let line = format!(
        "[{}][startup={}][+{}ms][{}][{}] {}\n",
        timestamp(),
        startup_id(),
        uptime_ms(),
        level,
        stage,
        redact_paths(&redact(message))
    );
    if let Ok(mut guard) = LOG_FILE.lock() {
        if let Some(file) = guard.as_mut() {
            use std::io::Write as _;
            let _ = file.write_all(line.as_bytes());
            let _ = file.flush();
        }
    }
}

/// Short, consistent call sites.
pub fn info(stage: &str, message: &str) {
    log("INFO", stage, message);
}

pub fn warn(stage: &str, message: &str) {
    log("WARN", stage, message);
}

pub fn error(stage: &str, message: &str) {
    log("ERROR", stage, message);
}

/// UTC timestamp without pulling in a date-time dependency.
fn timestamp() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let (y, m, d) = civil_from_days((secs / 86_400) as i64);
    let tod = secs % 86_400;
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z",
        tod / 3600,
        (tod % 3600) / 60,
        tod % 60
    )
}

/// Days-from-civil inverse (Howard Hinnant's algorithm); valid for all epochs.
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}
// ------------------------------------------------------- integrity level
/// Windows mandatory integrity level of the current process token.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Integrity {
    /// Below Low: AppContainer / heavily sandboxed.
    Untrusted,
    /// Low integrity: classic app sandbox (e.g. a restricted launcher).
    Low,
    /// Normal interactive desktop process.
    Medium,
    High,
    System,
    /// The token query FAILED: no level was measured. This is a distinct
    /// state — it must never be displayed as measured Medium, never be
    /// classified as Low/Untrusted and never trigger the restricted-token
    /// remediation on its own.
    Unknown,
}

/// Reason of the last failed integrity query, for honest diagnostics.
static INTEGRITY_QUERY_ERROR: OnceLock<String> = OnceLock::new();

/// Human-readable reason the integrity level could not be measured
/// (None when it was measured or never queried).
pub fn integrity_query_error() -> Option<&'static str> {
    INTEGRITY_QUERY_ERROR.get().map(String::as_str)
}

/// `integrity=<level>` log field; for Unknown it also carries why the
/// query failed, so a query failure is never logged as measured data.
pub fn integrity_log_field(integrity: Integrity) -> String {
    match (integrity, integrity_query_error()) {
        (Integrity::Unknown, Some(reason)) => format!("unknown (query failed: {reason})"),
        (Integrity::Unknown, None) => "unknown (query failed: reason unavailable)".to_string(),
        (measured, _) => measured.as_str().to_string(),
    }
}

impl Integrity {
    pub fn as_str(self) -> &'static str {
        match self {
            Integrity::Untrusted => "untrusted",
            Integrity::Low => "low",
            Integrity::Medium => "medium",
            Integrity::High => "high",
            Integrity::System => "system",
            Integrity::Unknown => "unknown",
        }
    }

    /// True when the token cannot write to ordinary per-user directories.
    /// Unknown is deliberately NOT restricted: an unmeasured level is no
    /// evidence of a restricted token.
    pub fn is_restricted(self) -> bool {
        matches!(self, Integrity::Untrusted | Integrity::Low)
    }
}

#[cfg(windows)]
fn query_integrity() -> Integrity {
    use std::ffi::c_void;

    type Handle = *mut c_void;
    const TOKEN_QUERY: u32 = 0x0008;
    const TOKEN_INTEGRITY_LEVEL: i32 = 25;

    #[repr(C)]
    struct TokenMandatoryLabel {
        label: SidAndAttributes,
    }

    #[repr(C)]
    struct SidAndAttributes {
        sid: *mut c_void,
        attributes: u32,
    }

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn GetCurrentProcess() -> Handle;
    }

    #[link(name = "advapi32")]
    unsafe extern "system" {
        fn OpenProcessToken(process: Handle, desired_access: u32, token: *mut Handle) -> i32;
        fn GetTokenInformation(
            token: Handle,
            class: i32,
            info: *mut c_void,
            length: u32,
            return_length: *mut u32,
        ) -> i32;
        fn GetSidSubAuthority(sid: *const c_void, index: u32) -> *mut u32;
        fn GetSidSubAuthorityCount(sid: *const c_void) -> *mut u8;
        fn CloseHandle(handle: Handle) -> i32;
    }

    // TOKEN_MANDATORY_LABEL is a stub struct followed inline by the label SID,
    // so the required buffer is ALWAYS larger than size_of::<TokenMandatoryLabel>()
    // (typically 28 bytes vs 16). Query the needed size first, then allocate:
    // a single fixed-size call fails with ERROR_INSUFFICIENT_BUFFER and would
    // leave the label unread, falling through to a false "untrusted".
    unsafe {
        let unknown = |reason: String| {
            let _ = INTEGRITY_QUERY_ERROR.set(reason);
            Integrity::Unknown
        };
        let mut token: Handle = std::ptr::null_mut();
        if OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) == 0 {
            let code = std::io::Error::last_os_error().raw_os_error().unwrap_or(0);
            return unknown(format!("OpenProcessToken failed (os error {code})"));
        }
        let close = |t: Handle| {
            CloseHandle(t);
        };
        let mut needed: u32 = 0;
        let sized = GetTokenInformation(
            token,
            TOKEN_INTEGRITY_LEVEL,
            std::ptr::null_mut(),
            0,
            &mut needed,
        );
        if sized == 0 && needed == 0 {
            close(token);
            let code = std::io::Error::last_os_error().raw_os_error().unwrap_or(0);
            return unknown(format!(
                "GetTokenInformation(size query) failed (os error {code})"
            ));
        }
        let cap = needed.max(std::mem::size_of::<TokenMandatoryLabel>() as u32);
        let mut buffer = vec![0u8; cap as usize];
        let queried = GetTokenInformation(
            token,
            TOKEN_INTEGRITY_LEVEL,
            buffer.as_mut_ptr() as *mut c_void,
            buffer.len() as u32,
            &mut needed,
        );
        let integrity = if queried != 0 {
            // The stub struct may be unaligned inside the byte buffer.
            let label = std::ptr::read_unaligned(buffer.as_ptr() as *const TokenMandatoryLabel);
            let sid = label.label.sid;
            let count = GetSidSubAuthorityCount(sid);
            if count.is_null() {
                unknown("GetSidSubAuthorityCount returned null".to_string())
            } else {
                // The count is a single byte inside the SID header.
                let count = *count as u32;
                let sub = if count > 0 {
                    GetSidSubAuthority(sid, count - 1)
                } else {
                    std::ptr::null_mut()
                };
                if sub.is_null() {
                    unknown("GetSidSubAuthority returned null".to_string())
                } else {
                    // The last sub-authority of a mandatory label is the RID.
                    rid_to_integrity(*sub)
                }
            }
        } else {
            let code = std::io::Error::last_os_error().raw_os_error().unwrap_or(0);
            unknown(format!(
                "GetTokenInformation(label query) failed (os error {code})"
            ))
        };
        close(token);
        integrity
    }
}

/// Map a mandatory-label RID (SECURITY_MANDATORY_LABEL_AUTHORITY sub-authority)
/// to the coarse integrity tier. Non-tier values fall back to Medium.
fn rid_to_integrity(rid: u32) -> Integrity {
    match rid {
        0x0000 => Integrity::Untrusted,
        0x1000 => Integrity::Low,
        0x2000 => Integrity::Medium,
        0x3000 => Integrity::High,
        _ if rid >= 0x4000 => Integrity::System,
        _ => Integrity::Medium,
    }
}

#[cfg(not(windows))]
fn query_integrity() -> Integrity {
    // No Windows token to measure on this platform: report it honestly
    // instead of pretending a measured Medium.
    let _ = INTEGRITY_QUERY_ERROR.set("not a Windows process token".to_string());
    Integrity::Unknown
}

/// Integrity level of the running AXIOM process.
pub fn integrity() -> Integrity {
    query_integrity()
}
// ------------------------------------------------------- profile resolution
/// Explicit opt-in switch for a disposable development profile.
///
/// It is deliberately NOT honoured in release builds: a released AXIOM must
/// never write its browser profile into a temporary folder the OS may clean
/// up, and never beside the repository.
const DEV_PROFILE_ENV: &str = "AXIOM_DEV_WEBVIEW_PROFILE";

/// Where the resolved profile will live, and why.
#[derive(Debug, Clone)]
pub struct ProfilePlan {
    pub dir: PathBuf,
    /// True only for the explicit, disposable development profile.
    pub disposable: bool,
    /// Human-readable reason, recorded in the log.
    pub origin: &'static str,
}

/// Resolve the WebView2 user-data folder.
///
/// Production: `%LOCALAPPDATA%\<identifier>` — exactly the folder Tauri
/// itself forces in `manager/webview.rs` (per-user, app-specific, stable across
/// launches). Development: a per-launch disposable folder under the OS temp
/// directory, only with an explicit env var and only in debug builds.
pub fn resolve_profile(identifier: &str) -> Result<ProfilePlan, String> {
    if cfg!(debug_assertions) {
        if let Ok(raw) = std::env::var(DEV_PROFILE_ENV) {
            if !raw.trim().is_empty() {
                return Ok(ProfilePlan {
                    dir: std::env::temp_dir()
                        .join("axiom-dev-webview")
                        .join(unique_suffix()),
                    disposable: true,
                    origin: "development (explicit env override, disposable)",
                });
            }
        }
    } else if let Ok(raw) = std::env::var(DEV_PROFILE_ENV) {
        if !raw.trim().is_empty() {
            return Err(format!(
                "{DEV_PROFILE_ENV} is ignored in release builds: the packaged app always uses \
                 the per-user profile directory"
            ));
        }
    }
    let base = std::env::var_os("LOCALAPPDATA")
        .or_else(|| std::env::var_os("HOME"))
        .ok_or_else(|| {
            "neither LOCALAPPDATA nor HOME is set; cannot place the app profile".to_string()
        })?;
    Ok(ProfilePlan {
        dir: PathBuf::from(base).join(identifier),
        disposable: false,
        origin: "production (per-user, app-specific)",
    })
}

fn unique_suffix() -> String {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{}-{}", std::process::id(), nanos)
}

/// WebView2-relevant environment overrides inherited from the parent process.
pub struct EnvOverrides {
    pub entries: Vec<(String, String)>,
}

impl EnvOverrides {
    /// Names that change where or how the embedded browser starts.
    const KEYS: [&'static str; 4] = [
        "WEBVIEW2_USER_DATA_FOLDER",
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",
        "WEBVIEW2_RELEASE_CHANNEL_PREFERENCE",
    ];

    pub fn inspect() -> Self {
        let mut entries = Vec::new();
        for key in Self::KEYS {
            if let Ok(value) = std::env::var(key) {
                if !value.is_empty() {
                    entries.push((key.to_string(), value));
                }
            }
        }
        EnvOverrides { entries }
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// True when something forces a different user-data folder than ours.
    pub fn overrides_user_data_folder(&self) -> bool {
        self.entries
            .iter()
            .any(|(key, _)| key == "WEBVIEW2_USER_DATA_FOLDER")
    }

    pub fn describe(&self) -> String {
        if self.entries.is_empty() {
            return "none".to_string();
        }
        self.entries
            .iter()
            .map(|(key, value)| format!("{key}={}", redact(value)))
            .collect::<Vec<_>>()
            .join(", ")
    }
}
// ------------------------------------------------------ failure taxonomy
/// Why the profile folder could not be used.
///
/// Permission, lock and disk-space problems are *not* corruption: a profile
/// is never labelled "corrupt" merely because startup failed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FailureKind {
    /// Low/Untrusted integrity cannot write the per-user directory.
    Integrity,
    /// The OS denied access (ACL, Controlled Folder Access, read-only media).
    Permission,
    /// Another process holds the profile (running instance, antivirus scan).
    Locked,
    /// Not enough free space for the browser profile.
    DiskSpace,
    /// The directory vanished or cannot be created at all.
    Unavailable,
    /// Not a recognised condition — report the raw OS error verbatim.
    Unknown,
}

impl FailureKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            FailureKind::Integrity => "integrity",
            FailureKind::Permission => "permission",
            FailureKind::Locked => "locked",
            FailureKind::DiskSpace => "disk-space",
            FailureKind::Unavailable => "unavailable",
            FailureKind::Unknown => "unknown",
        }
    }

    /// Classify a raw `std::io::Error` from the filesystem.
    pub fn classify_io(error: &std::io::Error) -> Self {
        match error.raw_os_error() {
            Some(5) => FailureKind::Permission,             // ACCESS_DENIED
            Some(32) | Some(33) => FailureKind::Locked,     // SHARING/LOCK_VIOLATION
            Some(112) | Some(39) => FailureKind::DiskSpace, // DISK_FULL
            Some(3) | Some(2) | Some(267) => FailureKind::Unavailable,
            Some(19) | Some(30) => FailureKind::Permission, // WRITE_PROTECT/READONLY
            Some(170) => FailureKind::Locked,               // BUSY
            _ => FailureKind::Unknown,
        }
    }

    /// Classify a WebView2 HRESULT message.
    ///
    /// A busy profile surfaces as `0x800700AA` ("resource busy") and must be
    /// reported as a lock, never as profile corruption.
    pub fn from_webview_message(message: &str) -> Option<Self> {
        let lowered = message.to_ascii_lowercase();
        if lowered.contains("0x800700aa")
            || lowered.contains("resource busy")
            || lowered.contains("being used by another process")
        {
            Some(FailureKind::Locked)
        } else if lowered.contains("0x80070005") || lowered.contains("access is denied") {
            Some(FailureKind::Permission)
        } else if lowered.contains("0x80070070")
            || lowered.contains("disk full")
            || lowered.contains("not enough space")
        {
            Some(FailureKind::DiskSpace)
        } else {
            None
        }
    }
}

/// Actionable, user-facing guidance per failure kind.
pub fn remediation(kind: &FailureKind) -> String {
    match kind {
        FailureKind::Integrity => {
            "AXIOM запущен в среде с пониженным уровнем целостности (Low Integrity) или \
             с ограниченным маркером доступа родительского процесса (песочница, ограниченный \
             лаунчер, агентская сессия). В таком окружении у приложения нет прав на собственную \
             папку профиля.\n\nЗапустите AXIOM обычным способом (двойной клик по .exe или \
             ярлыку, меню «Пуск») из обычного терминала cmd/PowerShell, вне песочницы. \
             Профиль не переносится автоматически, чтобы не потерять сессию и данные \
             авторизации."
                .to_string()
        }
        FailureKind::Permission => {
            "Нет прав на папку профиля. Проверьте, что её не держит другое приложение \
             с монопольным доступом, и что «Контролируемый доступ к папкам» в Защитнике \
             Windows не блокирует AXIOM. AXIOM не меняет права и политики безопасности \
             самостоятельно."
                .to_string()
        }
        FailureKind::Locked => {
            "Папка профиля занята другим процессом — чаще всего уже запущенным экземпляром \
             AXIOM или проверкой Защитника. Закройте остальные экземпляры AXIOM и повторите \
             запуск. Сброс профиля AXIOM самостоятельно не выполняет."
                .to_string()
        }
        FailureKind::DiskSpace => {
            "Недостаточно свободного места для профиля браузера. Освободите место на \
             системном диске и запустите AXIOM снова."
                .to_string()
        }
        FailureKind::Unavailable => {
            "Папку профиля не удалось создать. Проверьте доступность системного диска и \
             наличие свободного места, затем запустите AXIOM снова."
                .to_string()
        }
        FailureKind::Unknown => {
            "Технические подробности записаны в лог запуска (путь указан в сообщении). \
             AXIOM не меняет права доступа и не сбрасывает профиль автоматически."
                .to_string()
        }
    }
}
// -------------------------------------------------------------- preflight
/// Everything the preflight learned, for logging and error reporting.
#[derive(Debug, Clone)]
pub struct PreflightReport {
    pub integrity: Integrity,
    pub profile_dir: PathBuf,
    pub disposable: bool,
    pub origin: &'static str,
    pub env_overrides: String,
    pub writable: bool,
    pub free_space_ok: bool,
}

/// Result of a preflight run: either a usable plan or a classified failure.
pub enum Preflight {
    Ready(ProfilePlan),
    Failed {
        kind: FailureKind,
        detail: String,
        report: Box<PreflightReport>,
    },
}

/// Inspect the environment before any WebView2 object is created.
///
/// A successful write probe is evidence, not a guarantee: WebView2 can still
/// fail later for reasons a filesystem probe cannot see, such as a stale
/// profile lock. The distinction is preserved in the reported failure kind.
/// Reclassify a Permission failure when a measured restricted integrity
/// level is the likely cause. Unknown is deliberately excluded: an
/// unmeasured level is no evidence of a restricted token.
fn reclassify_kind(writable: bool, integrity: Integrity, kind: FailureKind) -> FailureKind {
    if !writable && integrity.is_restricted() && kind == FailureKind::Permission {
        FailureKind::Integrity
    } else {
        kind
    }
}

pub fn preflight(identifier: &str) -> Preflight {
    let integrity = integrity();
    let overrides = EnvOverrides::inspect();
    let plan = match resolve_profile(identifier) {
        Ok(plan) => plan,
        Err(detail) => {
            return Preflight::Failed {
                kind: FailureKind::Unavailable,
                detail,
                report: Box::new(PreflightReport {
                    integrity,
                    profile_dir: PathBuf::new(),
                    disposable: false,
                    origin: "unresolved",
                    env_overrides: overrides.describe(),
                    writable: false,
                    free_space_ok: false,
                }),
            }
        }
    };

    let mut writable = true;
    let mut detail = String::new();
    let mut kind = FailureKind::Unknown;

    if let Err(err) = std::fs::create_dir_all(&plan.dir) {
        writable = false;
        kind = FailureKind::classify_io(&err);
        detail = format!("create_dir_all failed: {err}");
    } else if let Err(found) = write_probe(&plan.dir) {
        writable = false;
        kind = found.kind;
        detail = found.detail;
    }

    let free_space_ok = free_space_ok(&plan.dir);

    info(
        "preflight",
        &format!(
            "integrity={} profile={} origin={} disposable={} writable={} free_space_ok={} \
             env_overrides={}",
            integrity_log_field(integrity),
            plan.dir.display(),
            plan.origin,
            plan.disposable,
            writable,
            free_space_ok,
            overrides.describe()
        ),
    );

    // A restricted token that cannot write its own profile gets a precise,
    // actionable diagnosis instead of a generic permission error. Unknown
    // integrity never triggers this (see reclassify_kind).
    kind = reclassify_kind(writable, integrity, kind);

    let report = Box::new(PreflightReport {
        integrity,
        profile_dir: plan.dir.clone(),
        disposable: plan.disposable,
        origin: plan.origin,
        env_overrides: overrides.describe(),
        writable,
        free_space_ok,
    });

    if writable {
        Preflight::Ready(plan)
    } else {
        Preflight::Failed {
            kind,
            detail,
            report,
        }
    }
}

struct ProbeFailure {
    kind: FailureKind,
    detail: String,
}

/// Create, write, read back and delete a small probe file.
///
/// This is the minimum evidence that the process can actually mutate the
/// intended folder. It never grants, widens or repairs any permission.
fn write_probe(dir: &Path) -> Result<(), ProbeFailure> {
    let probe = dir.join(format!("axiom-write-probe-{}.tmp", std::process::id()));
    let payload = b"axiom-webview-profile-probe";
    if let Err(err) = std::fs::write(&probe, payload) {
        return Err(ProbeFailure {
            kind: FailureKind::classify_io(&err),
            detail: format!("write probe failed: {err}"),
        });
    }
    let read_back = std::fs::read(&probe).map_err(|err| ProbeFailure {
        kind: FailureKind::classify_io(&err),
        detail: format!("read-back probe failed: {err}"),
    })?;
    if read_back != payload {
        return Err(ProbeFailure {
            kind: FailureKind::Unknown,
            detail: "read-back probe returned unexpected content".to_string(),
        });
    }
    // Removal is part of the check: a folder we cannot clean up is unusable.
    if let Err(err) = std::fs::remove_file(&probe) {
        return Err(ProbeFailure {
            kind: FailureKind::classify_io(&err),
            detail: format!("probe cleanup failed: {err}"),
        });
    }
    Ok(())
}

/// Cheap free-space signal using the platform API (no extra dependency).
fn free_space_ok(dir: &Path) -> bool {
    #[cfg(windows)]
    {
        use std::ffi::c_void;
        use std::os::windows::ffi::OsStrExt as _;

        const FREE_SPACE_THRESHOLD: u64 = 64 * 1024 * 1024;
        let _ = std::mem::size_of::<c_void>();

        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn GetDiskFreeSpaceExW(
                directory: *const u16,
                free_bytes_available: *mut u64,
                total_bytes: *mut u64,
                total_free_bytes: *mut u64,
            ) -> i32;
        }

        let mut wide: Vec<u16> = dir.as_os_str().encode_wide().chain(Some(0)).collect();
        let mut available: u64 = 0;
        let ok = unsafe {
            GetDiskFreeSpaceExW(
                wide.as_mut_ptr(),
                &mut available,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            )
        };
        if ok == 0 {
            return true; // Unknown: do not block startup on a failed query.
        }
        available >= FREE_SPACE_THRESHOLD
    }
    #[cfg(not(windows))]
    {
        let _ = dir;
        true
    }
}
// ------------------------------------------------------------ start stages
/// Bounded startup states. A live process, `windows=["main"]` or a valid HWND
/// are explicitly *not* treated as readiness: the frontend must acknowledge.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Stage {
    /// Environment, integrity, profile and write probe are done.
    Preflight,
    /// The Tauri runtime and event loop are up.
    RuntimeInit,
    /// The native window exists and is visible.
    NativeWindow,
    /// The bundled frontend executed and acknowledged via `invoke`.
    FrontendLoaded,
    /// The Python bridge answered a real round-trip.
    BridgeReady,
}

impl Stage {
    pub fn as_str(self) -> &'static str {
        match self {
            Stage::Preflight => "preflight",
            Stage::RuntimeInit => "runtime-init",
            Stage::NativeWindow => "native-window",
            Stage::FrontendLoaded => "frontend-loaded",
            Stage::BridgeReady => "bridge-ready",
        }
    }

    /// The last state that means "the user can actually work".
    pub fn is_terminal_success(self) -> bool {
        self == Stage::BridgeReady
    }
}

static CURRENT_STAGE: AtomicU8 = AtomicU8::new(0);

fn stage_code(stage: Stage) -> u8 {
    match stage {
        Stage::Preflight => 1,
        Stage::RuntimeInit => 2,
        Stage::NativeWindow => 3,
        Stage::FrontendLoaded => 4,
        Stage::BridgeReady => 5,
    }
}

/// Write the per-launch readiness marker for a supervising launcher.
///
/// Called only from the `BridgeReady` transition in [`mark`]: frontend
/// acknowledged AND a real bridge round-trip succeeded — never on a
/// preflight failure, watchdog timeout or mere window existence. A write
/// failure is logged and ignored: the marker serves the launcher, not the
/// app. The `Once` guard keeps the signal exactly-once even if `BridgeReady`
/// is marked again.
fn signal_launch_ready() {
    static SIGNALED: Once = Once::new();
    SIGNALED.call_once(|| {
        let path = match std::env::var_os(LAUNCH_READY_FILE_ENV) {
            Some(value) if !value.is_empty() => PathBuf::from(value),
            _ => return, // normal double-click start: nobody is watching
        };
        let payload = format!("pid={} startup_id={}\n", std::process::id(), startup_id());
        let shown = redact_paths(&path.display().to_string());
        match std::fs::write(&path, payload) {
            Ok(()) => info("launch-ready", &format!("readiness marker written: {shown}")),
            Err(err) => warn("launch-ready", &format!("readiness marker write failed: {err}")),
        }
    });
}

/// Record a stage transition. Stages only move forward, so a late native
/// callback cannot re-open an already-closed startup.
pub fn mark(stage: Stage) {
    let code = stage_code(stage);
    if CURRENT_STAGE.fetch_max(code, Ordering::AcqRel) >= code {
        return;
    }
    info(stage.as_str(), "stage reached");
    if stage == Stage::BridgeReady {
        signal_launch_ready();
    }
}

/// The furthest stage reached so far.
pub fn current_stage() -> Stage {
    match CURRENT_STAGE.load(Ordering::Acquire) {
        0 | 1 => Stage::Preflight,
        2 => Stage::RuntimeInit,
        3 => Stage::NativeWindow,
        4 => Stage::FrontendLoaded,
        _ => Stage::BridgeReady,
    }
}

/// True once the app is genuinely usable.
pub fn is_ready() -> bool {
    current_stage().is_terminal_success()
}

/// Record a failure with the stage that was in progress and the original
/// HRESULT / OS error text, so the log keeps the real cause.
pub fn record_failure(stage: Stage, detail: &str) -> FailureKind {
    let kind = FailureKind::from_webview_message(detail).unwrap_or_else(|| {
        detail
            .split("os error")
            .nth(1)
            // Keep only the digits: the OS code is often wrapped as "(os error 5)".
            .and_then(|tail| {
                tail.trim_start()
                    .chars()
                    .skip_while(|c| !c.is_ascii_digit())
                    .take_while(char::is_ascii_digit)
                    .collect::<String>()
                    .parse::<i32>()
                    .ok()
            })
            .map(|code| FailureKind::classify_io(&std::io::Error::from_raw_os_error(code)))
            .unwrap_or(FailureKind::Unknown)
    });
    error(
        stage.as_str(),
        &format!("startup failed kind={} detail={detail}", kind.as_str()),
    );
    kind
}
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn permission_lock_and_disk_space_are_distinguished() {
        assert_eq!(
            FailureKind::classify_io(&std::io::Error::from_raw_os_error(5)),
            FailureKind::Permission
        );
        assert_eq!(
            FailureKind::classify_io(&std::io::Error::from_raw_os_error(32)),
            FailureKind::Locked
        );
        assert_eq!(
            FailureKind::classify_io(&std::io::Error::from_raw_os_error(112)),
            FailureKind::DiskSpace
        );
        assert_eq!(
            FailureKind::classify_io(&std::io::Error::from_raw_os_error(267)),
            FailureKind::Unavailable
        );
        assert_eq!(
            FailureKind::classify_io(&std::io::Error::from_raw_os_error(4242)),
            FailureKind::Unknown
        );
    }

    #[test]
    fn busy_hresult_is_a_lock_not_corruption() {
        assert_eq!(
            FailureKind::from_webview_message("WebView2 error: WindowsError(HRESULT(0x800700AA))"),
            Some(FailureKind::Locked)
        );
        assert_eq!(
            FailureKind::from_webview_message("some unrelated message"),
            None
        );
    }

    #[test]
    fn os_error_text_in_a_failure_is_classified() {
        assert_eq!(
            record_failure(
                Stage::Preflight,
                "create failed: Отказано в доступе. (os error 5)"
            ),
            FailureKind::Permission
        );
    }

    #[test]
    fn redaction_hides_credentials_but_keeps_keys() {
        let redacted = redact("api_key=sk-abcdef1234567890 and authorization=Bearer xyz");
        assert!(!redacted.contains("sk-abcdef1234567890"));
        assert!(!redacted.contains("Bearer xyz"));
        assert!(redacted.contains("api_key"));
        assert!(redacted.contains("authorization"));
    }

    #[test]
    fn long_opaque_tokens_are_masked() {
        let blob = "a".repeat(60);
        let redacted = redact(&format!("value={blob}"));
        assert!(!redacted.contains(&blob));
        assert!(redacted.contains("<redacted>"));
    }

    #[test]
    fn ordinary_messages_survive_redaction() {
        assert_eq!(
            redact("startup ok, stage=native-window"),
            "startup ok, stage=native-window"
        );
    }

    #[test]
    fn production_profile_is_per_user_and_app_specific() {
        let plan = resolve_profile("app.axiom.desktop").expect("resolvable");
        assert!(!plan.disposable);
        let path = plan.dir.to_string_lossy().to_lowercase();
        assert!(path.contains("app.axiom.desktop"), "got {path}");
        assert!(
            !path.contains("temp") && !path.contains("vscode"),
            "production profile must not live in a temporary or repository location: {path}"
        );
    }

    #[test]
    fn stage_order_is_monotonic_and_only_bridge_ready_is_success() {
        assert!(Stage::Preflight < Stage::RuntimeInit);
        assert!(Stage::RuntimeInit < Stage::NativeWindow);
        assert!(Stage::NativeWindow < Stage::FrontendLoaded);
        assert!(Stage::FrontendLoaded < Stage::BridgeReady);
        assert!(Stage::BridgeReady.is_terminal_success());
        assert!(!Stage::NativeWindow.is_terminal_success());
        assert!(!Stage::FrontendLoaded.is_terminal_success());
    }

    #[test]
    fn write_probe_detects_an_unusable_folder() {
        let dir = std::env::temp_dir().join(format!("axiom-probe-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        assert!(write_probe(&dir).is_ok());
        // A path whose parent is a regular file can never be written.
        let blocker = dir.join("blocked");
        std::fs::write(&blocker, b"x").unwrap();
        assert!(write_probe(&blocker.join("nested")).is_err());
        let _ = std::fs::remove_file(&blocker);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn integrity_query_returns_a_known_level() {
        assert!(matches!(
            integrity(),
            Integrity::Untrusted
                | Integrity::Low
                | Integrity::Medium
                | Integrity::High
                | Integrity::System
                | Integrity::Unknown
        ));
        // Unknown is a legitimate outcome (query failure), but then the
        // reason must be recorded for honest diagnostics.
        if matches!(integrity(), Integrity::Unknown) {
            assert!(
                integrity_query_error().is_some(),
                "Unknown integrity without a recorded query error"
            );
        }
    }

    #[test]
    fn unknown_integrity_is_not_restricted() {
        // An unmeasured level is no evidence of a restricted token: it must
        // never trigger the restricted-token remediation by itself.
        assert!(!Integrity::Unknown.is_restricted());
        assert_eq!(Integrity::Unknown.as_str(), "unknown");
        assert!(Integrity::Low.is_restricted());
        assert!(Integrity::Untrusted.is_restricted());
        assert!(!Integrity::Medium.is_restricted());
    }

    #[test]
    fn rid_to_integrity_maps_mandatory_label_tiers() {
        // SECURITY_MANDATORY_LABEL RID values (winnt.h).
        assert_eq!(rid_to_integrity(0x0000).as_str(), "untrusted");
        assert_eq!(rid_to_integrity(0x1000).as_str(), "low");
        assert_eq!(rid_to_integrity(0x2000).as_str(), "medium");
        // Medium Plus (0x2100) is not a separate tier: it stays Medium.
        assert_eq!(rid_to_integrity(0x2100).as_str(), "medium");
        assert_eq!(rid_to_integrity(0x3000).as_str(), "high");
        assert_eq!(rid_to_integrity(0x4000).as_str(), "system");
        // 0x5000 (Protected) and above stay in the System tier.
        assert_eq!(rid_to_integrity(0x5000).as_str(), "system");
        // Unknown in-between values keep the safe Medium fallback.
        assert_eq!(rid_to_integrity(0x2400).as_str(), "medium");
    }

    #[cfg(windows)]
    #[test]
    fn integrity_on_windows_is_actually_measured() {
        // A one-shot undersized GetTokenInformation call used to fail and
        // fall through to Untrusted on every Windows launch. Normal test
        // runners are Medium or High; a genuine Untrusted/Low runner is
        // possible (sandboxed CI), so this rejects only the stale default
        // combined with a Medium-integrity runner.
        if matches!(integrity(), Integrity::Untrusted) {
            // Distinguish the false constant from a genuinely restricted
            // token: an actually restricted token also denies writes.
            let probe = std::env::temp_dir().join("axiom-integrity-guard.tmp");
            let writable = std::fs::write(&probe, b"x").is_ok();
            let _ = std::fs::remove_file(&probe);
            assert!(
                writable,
                "integrity reported untrusted while temp writes succeed: \
                 the query fell through instead of measuring"
            );
        }
    }

    #[test]
    fn utc_timestamp_is_well_formed() {
        let stamp = timestamp();
        assert_eq!(stamp.len(), 20, "got {stamp}");
        assert!(stamp.ends_with('Z'), "got {stamp}");
        assert_eq!(stamp.matches('-').count(), 2, "got {stamp}");
    }
}
