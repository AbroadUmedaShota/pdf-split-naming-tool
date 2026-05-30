#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![run_sidecar])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[tauri::command]
fn run_sidecar(request: serde_json::Value) -> Result<serde_json::Value, String> {
    let recovery_dir = find_recovery_dir()?;
    let request_text = serde_json::to_string(&request).map_err(|error| error.to_string())?;
    let explicit_python = std::env::var_os("PDF_ORGANIZER_PYTHON").map(std::path::PathBuf::from);
    let python_launcher = sidecar_python_launcher_from(explicit_python.as_deref());
    let timeout_override = std::env::var("PDF_ORGANIZER_SIDECAR_TIMEOUT_MS").ok();
    let timeout = sidecar_timeout_from(timeout_override.as_deref());

    let mut child = std::process::Command::new(&python_launcher.program)
        .args(python_launcher.args.iter().map(String::as_str))
        .args(["-m", "pdf_splitter_tool", "--sidecar-request", "-"])
        .current_dir(recovery_dir)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|error| format!("failed to start Python sidecar: {error}"))?;

    {
        use std::io::Write;

        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| "failed to open Python sidecar stdin".to_string())?;
        stdin
            .write_all(request_text.as_bytes())
            .map_err(|error| format!("failed to write sidecar request: {error}"))?;
    }

    let output = wait_for_sidecar_output(&mut child, timeout)?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("failed to parse Python sidecar JSON: {error}"))
}

fn find_recovery_dir() -> Result<std::path::PathBuf, String> {
    let current_dir = std::env::current_dir().map_err(|error| error.to_string())?;
    let explicit_dir = std::env::var_os("PDF_ORGANIZER_RECOVERY_DIR").map(std::path::PathBuf::from);
    find_recovery_dir_from(&current_dir, explicit_dir.as_deref())
}

fn find_recovery_dir_from(
    start_dir: &std::path::Path,
    explicit_dir: Option<&std::path::Path>,
) -> Result<std::path::PathBuf, String> {
    if let Some(recovery_dir) = explicit_dir.filter(|path| !path.as_os_str().is_empty()) {
        if is_recovery_dir(recovery_dir) {
            return Ok(recovery_dir.to_path_buf());
        }
        return Err(format!(
            "PDF_ORGANIZER_RECOVERY_DIR does not contain pdf_splitter_tool sidecar: {}",
            recovery_dir.display()
        ));
    }

    for candidate in start_dir.ancestors() {
        let recovery_dir = candidate.join("recovery");
        if is_recovery_dir(&recovery_dir) {
            return Ok(recovery_dir);
        }
    }
    Err("failed to locate recovery/pdf_splitter_tool sidecar".to_string())
}

fn is_recovery_dir(path: &std::path::Path) -> bool {
    path.join("pdf_splitter_tool")
        .join("__main__.py")
        .is_file()
}

struct PythonLauncher {
    program: std::path::PathBuf,
    args: Vec<String>,
}

fn sidecar_python_launcher_from(explicit_python: Option<&std::path::Path>) -> PythonLauncher {
    if let Some(program) = explicit_python.filter(|path| !path.as_os_str().is_empty()) {
        return PythonLauncher {
            program: program.to_path_buf(),
            args: Vec::new(),
        };
    }
    PythonLauncher {
        program: std::path::PathBuf::from("py"),
        args: vec!["-3.12".to_string()],
    }
}

fn sidecar_timeout_from(value: Option<&str>) -> std::time::Duration {
    value
        .and_then(|raw| raw.trim().parse::<u64>().ok())
        .filter(|milliseconds| *milliseconds > 0)
        .map(std::time::Duration::from_millis)
        .unwrap_or_else(|| std::time::Duration::from_secs(30))
}

fn wait_for_sidecar_output(
    child: &mut std::process::Child,
    timeout: std::time::Duration,
) -> Result<std::process::Output, String> {
    let started_at = std::time::Instant::now();
    let stdout_reader = spawn_child_pipe_reader(child.stdout.take(), "stdout");
    let stderr_reader = spawn_child_pipe_reader(child.stderr.take(), "stderr");
    loop {
        if let Some(status) = child
            .try_wait()
            .map_err(|error| format!("failed to read Python sidecar response: {error}"))?
        {
            let stdout = join_child_pipe_reader(stdout_reader, "stdout")?;
            let stderr = join_child_pipe_reader(stderr_reader, "stderr")?;
            return Ok(std::process::Output {
                status,
                stdout,
                stderr,
            });
        }
        if started_at.elapsed() >= timeout {
            let _ = child.kill();
            let _ = child.wait();
            let _ = join_child_pipe_reader(stdout_reader, "stdout");
            let _ = join_child_pipe_reader(stderr_reader, "stderr");
            return Err(format!(
                "Python sidecar timed out after {} ms",
                timeout.as_millis()
            ));
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
}

fn spawn_child_pipe_reader<T: std::io::Read + Send + 'static>(
    pipe: Option<T>,
    name: &'static str,
) -> std::thread::JoinHandle<Result<Vec<u8>, String>> {
    std::thread::spawn(move || read_child_pipe(pipe, name))
}

fn join_child_pipe_reader(
    reader: std::thread::JoinHandle<Result<Vec<u8>, String>>,
    name: &str,
) -> Result<Vec<u8>, String> {
    reader
        .join()
        .map_err(|_| format!("failed to join Python sidecar {name} reader"))?
}

fn read_child_pipe<T: std::io::Read>(pipe: Option<T>, name: &str) -> Result<Vec<u8>, String> {
    let mut buffer = Vec::new();
    if let Some(mut pipe) = pipe {
        pipe.read_to_end(&mut buffer)
            .map_err(|error| format!("failed to read Python sidecar {name}: {error}"))?;
    }
    Ok(buffer)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn recovery_dir_can_be_resolved_from_explicit_env_path() {
        let root = unique_test_dir("env");
        let recovery_dir = root.join("custom-recovery");
        write_sidecar_marker(&recovery_dir);

        let resolved = find_recovery_dir_from(&root, Some(recovery_dir.as_path())).unwrap();

        assert_eq!(resolved, recovery_dir);
    }

    #[test]
    fn recovery_dir_can_be_resolved_from_ancestors() {
        let root = unique_test_dir("ancestors");
        let recovery_dir = root.join("recovery");
        let nested_dir = root.join("apps").join("desktop").join("src-tauri");
        write_sidecar_marker(&recovery_dir);
        std::fs::create_dir_all(&nested_dir).unwrap();

        let resolved = find_recovery_dir_from(&nested_dir, None).unwrap();

        assert_eq!(resolved, recovery_dir);
    }

    #[test]
    fn empty_explicit_recovery_dir_falls_back_to_ancestors() {
        let root = unique_test_dir("empty-recovery");
        let recovery_dir = root.join("recovery");
        write_sidecar_marker(&recovery_dir);

        let resolved = find_recovery_dir_from(&root, Some(std::path::Path::new(""))).unwrap();

        assert_eq!(resolved, recovery_dir);
    }

    #[test]
    fn python_launcher_defaults_to_windows_py312() {
        let launcher = sidecar_python_launcher_from(None);

        assert_eq!(launcher.program, std::path::PathBuf::from("py"));
        assert_eq!(launcher.args, vec!["-3.12"]);
    }

    #[test]
    fn python_launcher_can_be_overridden_by_explicit_path() {
        let python_path = std::path::Path::new("C:\\Python312\\python.exe");

        let launcher = sidecar_python_launcher_from(Some(python_path));

        assert_eq!(launcher.program, python_path);
        assert!(launcher.args.is_empty());
    }

    #[test]
    fn python_launcher_ignores_empty_override() {
        let launcher = sidecar_python_launcher_from(Some(std::path::Path::new("")));

        assert_eq!(launcher.program, std::path::PathBuf::from("py"));
        assert_eq!(launcher.args, vec!["-3.12"]);
    }

    #[test]
    fn sidecar_timeout_defaults_to_thirty_seconds() {
        let timeout = sidecar_timeout_from(None);

        assert_eq!(timeout, std::time::Duration::from_secs(30));
    }

    #[test]
    fn sidecar_timeout_can_be_overridden_by_milliseconds() {
        let timeout = sidecar_timeout_from(Some(" 2500 "));

        assert_eq!(timeout, std::time::Duration::from_millis(2500));
    }

    #[test]
    fn sidecar_timeout_ignores_invalid_or_zero_values() {
        assert_eq!(sidecar_timeout_from(Some("0")), std::time::Duration::from_secs(30));
        assert_eq!(sidecar_timeout_from(Some("abc")), std::time::Duration::from_secs(30));
    }

    #[test]
    fn sidecar_wait_drains_large_stdout_while_process_runs() {
        let mut child = std::process::Command::new("py")
            .args([
                "-3.12",
                "-c",
                "import sys; sys.stdout.write('x' * 200000); sys.stdout.flush()",
            ])
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .unwrap();

        let output = wait_for_sidecar_output(&mut child, std::time::Duration::from_secs(5)).unwrap();

        assert!(output.status.success());
        assert_eq!(output.stdout.len(), 200000);
    }

    fn unique_test_dir(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "pdf_organizer_desktop_{name}_{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write_sidecar_marker(recovery_dir: &Path) {
        let package_dir = recovery_dir.join("pdf_splitter_tool");
        std::fs::create_dir_all(&package_dir).unwrap();
        std::fs::write(package_dir.join("__main__.py"), "").unwrap();
    }
}
