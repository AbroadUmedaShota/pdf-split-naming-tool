use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use tauri::Manager;

/// Number of trailing stderr lines kept from the daemon for diagnostics.
const STDERR_TAIL_CAP: usize = 20;
/// Commands that may legitimately run for a long time and so get a longer timeout
/// than interactive commands (preview/thumbnail) which should feel instant.
const HEAVY_COMMANDS: &[&str] = &[
    "export",
    "preflight",
    "search_text",
    "index_candidates",
    "blank_candidates",
];
/// Multiplier applied to the base timeout for heavy commands.
const HEAVY_TIMEOUT_MULTIPLIER: u32 = 4;

/// Holds the long-lived Python sidecar daemon. Tauri-managed, shared across all
/// `run_sidecar` invocations.
///
/// The `Mutex` serializes every request onto the daemon's single JSON Lines pipe.
/// Deliberate trade-off: this makes the front-end's parallel thumbnail fan-out
/// (#79, concurrency 4) effectively serial. Correctness is unaffected, but the
/// parallelism stops buying anything — acceptable because the win comes from
/// dropping the per-request process spawn (~500ms), not from parallelism. A
/// future worker pool (Phase C) would replace `Option<_>` with a pool type, so
/// avoid baking single-daemon assumptions into callers.
#[derive(Default)]
struct SidecarState(Mutex<Option<SidecarDaemon>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(SidecarState::default())
        .invoke_handler(tauri::generate_handler![run_sidecar])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            shutdown_sidecar_daemon(app_handle);
        }
    });
}

/// Drop any running sidecar daemon on application exit so no orphan Python
/// process is left behind (one of three nets; the others are `Drop` and the
/// Python side exiting on stdin EOF).
fn shutdown_sidecar_daemon(app_handle: &tauri::AppHandle) {
    if let Some(state) = app_handle.try_state::<SidecarState>() {
        // try_lock, never block app exit behind an in-flight (possibly heavy)
        // request. If the lock is held the OS reaps the child on process exit,
        // and the Python serve loop also exits on stdin EOF, so the daemon does
        // not orphan even when this net is skipped.
        if let Ok(mut guard) = state.0.try_lock() {
            *guard = None; // Drop for SidecarDaemon kills the child.
        }
    }
}

#[tauri::command]
fn run_sidecar(
    state: tauri::State<'_, SidecarState>,
    request: serde_json::Value,
) -> Result<serde_json::Value, String> {
    if oneshot_mode_enabled() {
        return run_sidecar_oneshot(request);
    }

    let command = request
        .get("command")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("")
        .to_string();
    let mut request_line = serde_json::to_string(&request).map_err(|error| error.to_string())?;
    request_line.push('\n');
    let timeout = sidecar_timeout_for(&command);

    // Recover from a poisoned mutex rather than failing forever: reset the slot
    // to None so the next exchange simply respawns a fresh daemon.
    let mut guard = state.0.lock().unwrap_or_else(|poisoned| {
        let mut guard = poisoned.into_inner();
        *guard = None;
        guard
    });

    run_sidecar_exchange(&mut guard, &request_line, timeout, &spawn_daemon)
}

/// Escape hatch: `PDF_ORGANIZER_SIDECAR_ONESHOT=1` forces the legacy
/// one-process-per-request path, for emergency rollback if the daemon misbehaves.
fn oneshot_mode_enabled() -> bool {
    matches!(
        std::env::var("PDF_ORGANIZER_SIDECAR_ONESHOT").ok().as_deref(),
        Some("1") | Some("true") | Some("TRUE")
    )
}

/// Send one request to the daemon and wait for its response, (re)spawning as
/// needed. Generic over the spawn function so the retry/respawn logic is unit
/// testable against a stub daemon.
fn run_sidecar_exchange<F>(
    guard: &mut Option<SidecarDaemon>,
    request_line: &str,
    timeout: Duration,
    spawn: &F,
) -> Result<serde_json::Value, String>
where
    F: Fn() -> Result<SidecarDaemon, String>,
{
    // Only the broken-pipe case is retried: a failed write means the request
    // never reached a live process, so resending to a fresh daemon is safe. A
    // response-phase failure (timeout / disconnect) is NOT retried, because the
    // request may already have had side effects (e.g. a half-written export) and
    // resending could double-process it.
    for _ in 0..2 {
        ensure_daemon_with(guard, spawn)?;

        let send_failed = {
            let daemon = guard.as_mut().expect("daemon ensured above");
            daemon.send_request(request_line).is_err()
        };
        if send_failed {
            *guard = None;
            continue;
        }

        let received = {
            let daemon = guard.as_mut().expect("daemon ensured above");
            daemon.recv_response(timeout)
        };
        return match received {
            Ok(line) => serde_json::from_str(&line)
                .map_err(|error| format!("failed to parse Python sidecar JSON: {error}")),
            Err(RecvTimeoutError::Timeout) => {
                // Kill the stuck daemon so a late response can never be mismatched
                // to the next request; the next call respawns.
                *guard = None;
                Err(format!(
                    "Python sidecar timed out after {} ms",
                    timeout.as_millis()
                ))
            }
            Err(RecvTimeoutError::Disconnected) => {
                let tail = {
                    let daemon = guard.as_mut().expect("daemon ensured above");
                    daemon.stderr_snippet()
                };
                *guard = None;
                Err(if tail.is_empty() {
                    "Python sidecar daemon exited unexpectedly".to_string()
                } else {
                    format!("Python sidecar daemon exited: {tail}")
                })
            }
        };
    }

    Err("failed to deliver request to the Python sidecar daemon".to_string())
}

/// Ensure a live daemon occupies the slot, spawning a fresh one (via `spawn`) if
/// it is empty or the previous process has exited.
fn ensure_daemon_with<F>(guard: &mut Option<SidecarDaemon>, spawn: &F) -> Result<(), String>
where
    F: Fn() -> Result<SidecarDaemon, String>,
{
    let alive = match guard.as_mut() {
        Some(daemon) => daemon.is_alive(),
        None => false,
    };
    if !alive {
        *guard = None; // drop (kill/reap) any dead daemon before respawning.
        *guard = Some(spawn()?);
    }
    Ok(())
}

/// Per-request timeout: interactive commands use the base timeout; heavy
/// commands (export etc.) get a multiple so a legitimately long export is not
/// killed and respawned mid-run.
///
/// Note: `PDF_ORGANIZER_SIDECAR_TIMEOUT_MS` scales the base, so it moves both
/// tiers together — lowering it to fail a hung preview faster also shortens the
/// heavy ceiling. A finer fast/normal/heavy split is left for a follow-up.
fn sidecar_timeout_for(command: &str) -> Duration {
    let base = sidecar_timeout_from(
        std::env::var("PDF_ORGANIZER_SIDECAR_TIMEOUT_MS")
            .ok()
            .as_deref(),
    );
    if HEAVY_COMMANDS.contains(&command) {
        base.saturating_mul(HEAVY_TIMEOUT_MULTIPLIER)
    } else {
        base
    }
}

/// Spawn the production sidecar daemon: `<python> -m pdf_splitter_tool --serve`,
/// reusing the same launcher / recovery-dir / env resolution as the one-shot path.
fn spawn_daemon() -> Result<SidecarDaemon, String> {
    let recovery_dir = find_recovery_dir()?;
    let explicit_python = std::env::var_os("PDF_ORGANIZER_PYTHON").map(PathBuf::from);
    let launcher = sidecar_python_launcher_from(explicit_python.as_deref());

    let mut command = Command::new(&launcher.program);
    command
        .args(launcher.args.iter().map(String::as_str))
        .args(["-m", "pdf_splitter_tool", "--serve"])
        .current_dir(recovery_dir)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1");
    SidecarDaemon::spawn_with(command)
}

/// A long-lived Python sidecar process. Requests and responses are exchanged as
/// JSON Lines over the child's stdin/stdout. A background thread drains stdout
/// into a channel, so a per-request timeout is simply a `recv_timeout` and the
/// pipe can never deadlock on a full buffer.
struct SidecarDaemon {
    child: Child,
    stdin: ChildStdin,
    responses: Receiver<String>,
    stderr_tail: Arc<Mutex<VecDeque<String>>>,
}

impl SidecarDaemon {
    fn spawn_with(mut command: Command) -> Result<Self, String> {
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("failed to start Python sidecar daemon: {error}"))?;

        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| "failed to open Python sidecar daemon stdin".to_string())?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "failed to open Python sidecar daemon stdout".to_string())?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| "failed to open Python sidecar daemon stderr".to_string())?;

        // Drain stdout line-by-line into a channel. One response line per request;
        // serialization upstream (the Mutex) keeps it strictly request/response.
        let (sender, responses) = mpsc::channel::<String>();
        thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) => break, // EOF: child closed stdout / exited.
                    Ok(_) => {
                        // Trim the trailing newline in place to avoid a second
                        // copy of a possibly multi-MB line (e.g. a base64 preview).
                        let trimmed_len = line.trim_end_matches(['\n', '\r']).len();
                        line.truncate(trimmed_len);
                        if sender.send(line).is_err() {
                            break; // receiver dropped: daemon is being torn down.
                        }
                    }
                    Err(_) => break,
                }
            }
            // Sender drops here -> the receiver observes `Disconnected`.
        });

        // Keep the last few stderr lines so a crash/import error is surfaced.
        let stderr_tail = Arc::new(Mutex::new(VecDeque::with_capacity(STDERR_TAIL_CAP)));
        let stderr_writer = Arc::clone(&stderr_tail);
        thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line in reader.lines() {
                let Ok(line) = line else { break };
                if let Ok(mut tail) = stderr_writer.lock() {
                    if tail.len() == STDERR_TAIL_CAP {
                        tail.pop_front();
                    }
                    tail.push_back(line);
                }
            }
        });

        Ok(Self {
            child,
            stdin,
            responses,
            stderr_tail,
        })
    }

    fn is_alive(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    fn send_request(&mut self, request_line: &str) -> Result<(), String> {
        self.stdin
            .write_all(request_line.as_bytes())
            .map_err(|error| format!("failed to write sidecar request: {error}"))?;
        self.stdin
            .flush()
            .map_err(|error| format!("failed to flush sidecar request: {error}"))
    }

    fn recv_response(&self, timeout: Duration) -> Result<String, RecvTimeoutError> {
        self.responses.recv_timeout(timeout)
    }

    fn stderr_snippet(&self) -> String {
        self.stderr_tail
            .lock()
            .map(|tail| tail.iter().cloned().collect::<Vec<_>>().join("\n"))
            .unwrap_or_default()
    }
}

impl Drop for SidecarDaemon {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// Legacy one-process-per-request path. Retained for the
/// `PDF_ORGANIZER_SIDECAR_ONESHOT` escape hatch. Intentionally uses the flat base
/// timeout (no heavy-command multiplier) — it is an emergency fallback, not the
/// tuned daemon path.
fn run_sidecar_oneshot(request: serde_json::Value) -> Result<serde_json::Value, String> {
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

#[cfg(test)]
mod daemon_tests {
    use super::*;

    /// A JSONL echo daemon: reads one request per line and replies with a compact
    /// `{"ok":true,"echo":<request>}` line, mirroring the real serve protocol.
    const ECHO_STUB: &str = r#"import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    sys.stdout.write(json.dumps({"ok": True, "echo": json.loads(line)}, separators=(",", ":")) + "\n")
    sys.stdout.flush()
"#;

    /// Consumes stdin forever and never replies (forces a recv timeout).
    const SILENT_STUB: &str = r#"import sys
for line in sys.stdin:
    pass
"#;

    /// Reads exactly one line, then exits without replying (forces a disconnect).
    const EXIT_AFTER_ONE_STUB: &str = r#"import sys
sys.stdin.readline()
"#;

    fn python_program() -> String {
        std::env::var("PDF_ORGANIZER_TEST_PYTHON").unwrap_or_else(|_| "python".to_string())
    }

    fn stub_command(name: &str, body: &str) -> Command {
        let dir = std::env::temp_dir().join(format!(
            "pdf_organizer_daemon_{name}_{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("stub.py");
        std::fs::write(&path, body).unwrap();
        let mut command = Command::new(python_program());
        command.arg(path);
        command
    }

    #[test]
    fn daemon_reuses_one_process_across_requests() {
        let mut daemon = SidecarDaemon::spawn_with(stub_command("echo", ECHO_STUB)).unwrap();
        let pid = daemon.child.id();

        daemon.send_request("{\"command\":\"a\"}\n").unwrap();
        let first = daemon.recv_response(Duration::from_secs(10)).unwrap();
        daemon.send_request("{\"command\":\"b\"}\n").unwrap();
        let second = daemon.recv_response(Duration::from_secs(10)).unwrap();

        assert!(first.contains("\"ok\":true"), "unexpected first response: {first}");
        assert!(second.contains("\"command\":\"b\""), "unexpected second response: {second}");
        // The same process served both requests (process reuse = the whole point).
        assert_eq!(pid, daemon.child.id());
        assert!(daemon.is_alive());
    }

    #[test]
    fn daemon_recv_times_out_when_no_response() {
        let mut daemon = SidecarDaemon::spawn_with(stub_command("silent", SILENT_STUB)).unwrap();
        daemon.send_request("{\"command\":\"a\"}\n").unwrap();

        let result = daemon.recv_response(Duration::from_millis(300));

        assert!(matches!(result, Err(RecvTimeoutError::Timeout)));
    }

    #[test]
    fn daemon_reports_disconnect_when_process_exits() {
        let mut daemon =
            SidecarDaemon::spawn_with(stub_command("exit1", EXIT_AFTER_ONE_STUB)).unwrap();
        daemon.send_request("{\"command\":\"a\"}\n").unwrap();

        // Reader thread hits EOF when the child exits -> sender drops -> Disconnected.
        let result = daemon.recv_response(Duration::from_secs(10));

        assert!(matches!(result, Err(RecvTimeoutError::Disconnected)));
    }

    #[test]
    fn daemon_becomes_not_alive_after_process_exits() {
        let mut daemon =
            SidecarDaemon::spawn_with(stub_command("exit2", EXIT_AFTER_ONE_STUB)).unwrap();
        daemon.send_request("{\"command\":\"a\"}\n").unwrap();
        let _ = daemon.recv_response(Duration::from_secs(10));

        let mut alive_observed = true;
        for _ in 0..50 {
            if !daemon.is_alive() {
                alive_observed = false;
                break;
            }
            thread::sleep(Duration::from_millis(20));
        }

        assert!(!alive_observed);
    }

    #[test]
    fn heavy_commands_get_a_longer_timeout_than_interactive() {
        let interactive = sidecar_timeout_for("page_thumbnail");
        let heavy = sidecar_timeout_for("export");

        assert_eq!(heavy, interactive.saturating_mul(HEAVY_TIMEOUT_MULTIPLIER));
        assert!(heavy > interactive);
    }

    #[test]
    fn daemon_round_trips_real_serve_mode() {
        // Bridges Phase A (the real `--serve` loop) and Phase B (this Rust daemon)
        // without the GUI: drive the actual pdf_splitter_tool serve process and
        // round-trip a real request. Skips (does not fail) when the recovery
        // package or a usable python is unavailable in this environment.
        let manifest_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        let Ok(recovery_dir) = find_recovery_dir_from(manifest_dir, None) else {
            return;
        };

        let mut command = Command::new(python_program());
        command
            .args(["-m", "pdf_splitter_tool", "--serve"])
            .current_dir(&recovery_dir)
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1");
        let Ok(mut daemon) = SidecarDaemon::spawn_with(command) else {
            return;
        };

        // pdf_info on a missing path is a deterministic ok:false response.
        daemon
            .send_request("{\"command\":\"pdf_info\",\"pdf_path\":\"__does_not_exist__.pdf\"}\n")
            .unwrap();

        if let Ok(line) = daemon.recv_response(Duration::from_secs(30)) {
            let value: serde_json::Value = serde_json::from_str(&line).unwrap();
            assert_eq!(value["ok"], serde_json::Value::Bool(false));
            assert_eq!(value["command"], "pdf_info");
        }
    }

    fn stub_spawner(
        name: &'static str,
        body: &'static str,
    ) -> impl Fn() -> Result<SidecarDaemon, String> {
        move || SidecarDaemon::spawn_with(stub_command(name, body))
    }

    #[test]
    fn exchange_returns_parsed_response_on_success() {
        let mut slot: Option<SidecarDaemon> = None;
        let spawn = stub_spawner("ex_echo", ECHO_STUB);

        let value = run_sidecar_exchange(
            &mut slot,
            "{\"command\":\"pdf_info\"}\n",
            Duration::from_secs(10),
            &spawn,
        )
        .unwrap();

        assert_eq!(value["ok"], serde_json::Value::Bool(true));
        assert!(slot.is_some()); // daemon kept alive for reuse
    }

    #[test]
    fn exchange_times_out_and_drops_the_daemon() {
        let mut slot: Option<SidecarDaemon> = None;
        let spawn = stub_spawner("ex_silent", SILENT_STUB);

        let result = run_sidecar_exchange(
            &mut slot,
            "{\"command\":\"x\"}\n",
            Duration::from_millis(300),
            &spawn,
        );

        assert!(result.unwrap_err().contains("timed out"));
        assert!(slot.is_none()); // the stuck daemon was killed
    }

    #[test]
    fn exchange_does_not_resend_request_after_disconnect() {
        // Regression guard for the double-execution fix: when the daemon dies
        // after a request was sent, the request must NOT be resent to a fresh
        // daemon (a non-idempotent export would otherwise run twice).
        let dir = std::env::temp_dir().join(format!(
            "pdf_organizer_daemon_counter_{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let counter = dir.join("count.txt");
        let _ = std::fs::remove_file(&counter);
        let counter_arg = counter.to_string_lossy().to_string();

        // Stub records each request it receives, then exits (forcing a disconnect).
        let body = r#"import sys
counter = sys.argv[1]
line = sys.stdin.readline()
if line.strip():
    with open(counter, "a", encoding="utf-8") as handle:
        handle.write("x")
"#;
        let spawn = move || {
            let dir = std::env::temp_dir().join(format!(
                "pdf_organizer_daemon_count_stub_{}",
                std::process::id()
            ));
            std::fs::create_dir_all(&dir).unwrap();
            let path = dir.join("stub.py");
            std::fs::write(&path, body).unwrap();
            let mut command = Command::new(python_program());
            command.arg(path).arg(&counter_arg);
            SidecarDaemon::spawn_with(command)
        };

        let mut slot: Option<SidecarDaemon> = None;
        let result = run_sidecar_exchange(
            &mut slot,
            "{\"command\":\"export\"}\n",
            Duration::from_secs(10),
            &spawn,
        );

        assert!(result.is_err()); // disconnect surfaces as an error, not success
        assert!(slot.is_none());

        let mut seen = String::new();
        for _ in 0..50 {
            seen = std::fs::read_to_string(&counter).unwrap_or_default();
            if !seen.is_empty() {
                break;
            }
            thread::sleep(Duration::from_millis(20));
        }
        assert_eq!(seen, "x", "request must be delivered exactly once (no resend)");
    }
}
