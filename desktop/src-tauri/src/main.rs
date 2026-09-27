// Keep the Windows desktop shell in GUI-subsystem mode in every build.
#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

fn main() {
    // run() owns the single-instance guard for the entire application lifetime.
    // Acquiring it here as well makes the process reject its own mutex.
    axiom_desktop_lib::run()
}
