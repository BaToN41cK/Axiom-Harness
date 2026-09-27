// Keep the Windows desktop shell in GUI-subsystem mode in every build.
#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

fn main() {
    #[cfg(windows)]
    let _single_instance = match axiom_desktop_lib::windows_process::SingleInstance::acquire() {
        Ok(Some(guard)) => guard,
        Ok(None) => return,
        Err(_) => return,
    };
    axiom_desktop_lib::run()
}
