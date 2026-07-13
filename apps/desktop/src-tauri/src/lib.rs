use tauri::Manager;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

/// Number of recent stderr lines kept for diagnostics when the sidecar fails.
const STDERR_TAIL_MAX_LINES: usize = 50;
const BUNDLED_SIDECAR_RESOURCE_PATH: &str = "resources/sidecar/pdf-splitter-sidecar.exe";
const SIDECAR_SPAWN_MAX_ATTEMPTS: usize = 6;
const SIDECAR_SPAWN_RETRY_DELAY: std::time::Duration = std::time::Duration::from_millis(500);
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        // The single-instance plugin must be registered before all others so a
        // second launch is intercepted and routed to the running instance instead
        // of opening a new window that would share the same state file (issue #131).
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            // Bring the existing main window to the foreground: restore it if it
            // was minimized, then focus it. Errors are non-fatal (the window may
            // be mid-teardown), so we intentionally ignore the results.
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(SidecarState::new())
        .invoke_handler(tauri::generate_handler![run_sidecar, reveal_path])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            // Secondary shutdown path. The primary path is pipe closure on app
            // process exit, which makes the Python side see stdin EOF and quit.
            let state = app_handle.state::<SidecarState>();
            kill_resident_sidecars_for_shutdown(&state);
        }
    });
}

/// Two resident processes keep long scans/exports from blocking interactive
/// preview work. Each lane remains serialized so the JSON Lines request/response
/// protocol and export duplicate-prevention behavior stay unchanged.
struct SidecarState {
    interactive: SharedSidecarLane,
    bulk: SharedSidecarLane,
}

type SharedChild = std::sync::Arc<std::sync::Mutex<std::process::Child>>;
type SharedSidecarLane = std::sync::Arc<SidecarLaneState>;

struct SidecarLaneState {
    request_slot: std::sync::Mutex<Option<ResidentSidecar>>,
    active_child: std::sync::Mutex<Option<SharedChild>>,
}

impl SidecarLaneState {
    fn new() -> Self {
        Self {
            request_slot: std::sync::Mutex::new(None),
            active_child: std::sync::Mutex::new(None),
        }
    }
}

impl SidecarState {
    fn new() -> Self {
        Self {
            interactive: std::sync::Arc::new(SidecarLaneState::new()),
            bulk: std::sync::Arc::new(SidecarLaneState::new()),
        }
    }

    fn lane_for(&self, lane: SidecarLane) -> SharedSidecarLane {
        std::sync::Arc::clone(match lane {
            SidecarLane::Interactive => &self.interactive,
            SidecarLane::Bulk => &self.bulk,
        })
    }
}

struct ResidentSidecar {
    child: SharedChild,
    stdin: std::process::ChildStdin,
    /// Lines read from the child's stdout by a dedicated reader thread.
    /// Channel disconnection signals that the process died (stdout EOF).
    stdout_rx: std::sync::mpsc::Receiver<std::io::Result<String>>,
    /// Recent stderr lines, drained by a dedicated thread to avoid pipe
    /// deadlocks and attached to error messages for diagnostics.
    stderr_tail: std::sync::Arc<std::sync::Mutex<std::collections::VecDeque<String>>>,
    /// Envelope id for the next request. Starts at 1 for every spawned
    /// process and increases monotonically.
    next_id: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum SidecarMode {
    Resident,
    Oneshot,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum SidecarLane {
    Interactive,
    Bulk,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum SidecarRuntime {
    BundledExecutable { path: std::path::PathBuf },
    Python {
        recovery_dir: std::path::PathBuf,
        launcher: PythonLauncher,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct SidecarProcessSpec {
    program: std::path::PathBuf,
    args: Vec<String>,
    current_dir: Option<std::path::PathBuf>,
}

#[tauri::command]
async fn run_sidecar(
    app: tauri::AppHandle,
    state: tauri::State<'_, SidecarState>,
    request: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let runtime = sidecar_runtime(&app)?;
    // タイムアウトはコマンド別に決定する（export等の長時間コマンドは大きめの枠を使う）。
    let timeout = resolve_command_timeout(&request);
    let mode_override = std::env::var("PDF_ORGANIZER_SIDECAR_MODE").ok();
    let mode = sidecar_mode_from(mode_override.as_deref());
    let shared_lane = state.lane_for(sidecar_lane(&request));

    tauri::async_runtime::spawn_blocking(move || match mode {
        SidecarMode::Oneshot => {
            let request_text =
                serde_json::to_string(&request).map_err(|error| error.to_string())?;
            run_sidecar_oneshot(&runtime, &request_text, timeout)
        }
        SidecarMode::Resident => run_sidecar_resident(
            &shared_lane,
            &runtime,
            &request,
            timeout,
        ),
    })
    .await
    .map_err(|error| error.to_string())
    .and_then(|result| result)
}

/// Opens the given directory (the export output folder) in the OS file
/// manager so the operator can move straight from export to checking the
/// generated PDFs. Validation is factored into `reveal_target` for testing;
/// the spawn itself is fire-and-forget (we do not wait on the file manager).
///
/// `allowed_base` には呼び出し元が output_dir を渡す。対象が allowed_base 配下でない
/// 場合は拒否する（スコープ外のディレクトリを開かせないため）。
#[tauri::command]
fn reveal_path(path: String, allowed_base: String) -> Result<(), String> {
    let target = reveal_target(&path, &allowed_base)?;
    open_in_file_manager(&target)
}

fn reveal_target(path: &str, allowed_base: &str) -> Result<std::path::PathBuf, String> {
    if path.trim().is_empty() {
        return Err("reveal path is empty".to_string());
    }
    let target = std::path::PathBuf::from(path);
    // The only caller passes the export output directory, so reject anything
    // that is not an existing directory rather than merely an existing path.
    if !target.is_dir() {
        return Err(format!("path does not exist or is not a directory: {path}"));
    }
    // スコープ検証: 対象が allowed_base 配下であることを canonicalize 後に確認する。
    // allowed_base が空の場合は検証をスキップする（既存の呼び出しパターンとの互換維持）。
    if !allowed_base.trim().is_empty() {
        let canonical_base = std::path::PathBuf::from(allowed_base)
            .canonicalize()
            .map_err(|e| format!("allowed_base cannot be resolved: {e}"))?;
        let canonical_target = target
            .canonicalize()
            .map_err(|e| format!("target path cannot be resolved: {e}"))?;
        if !canonical_target.starts_with(&canonical_base) {
            return Err(format!(
                "path is outside the allowed output directory: {path}"
            ));
        }
    }
    Ok(target)
}

fn open_in_file_manager(path: &std::path::Path) -> Result<(), String> {
    // Branches are exhaustive across desktop targets: Windows, macOS, and
    // "everything else" (Linux/BSD via xdg-open). Using not(any(...)) for the
    // last branch keeps `program` defined on any non-Windows/macOS target.
    #[cfg(target_os = "windows")]
    let program = "explorer";
    #[cfg(target_os = "macos")]
    let program = "open";
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    let program = "xdg-open";

    // Fire-and-forget: the exit code is intentionally ignored. explorer.exe
    // reliably returns 1 even when it opens the folder successfully, so only
    // a spawn failure (program missing) is treated as an error.
    std::process::Command::new(program)
        .arg(path)
        .spawn()
        .map(|_child| ())
        .map_err(|error| format!("failed to open file manager: {error}"))
}

fn sidecar_mode_from(value: Option<&str>) -> SidecarMode {
    match value {
        Some(raw) if raw.trim().eq_ignore_ascii_case("oneshot") => SidecarMode::Oneshot,
        _ => SidecarMode::Resident,
    }
}

fn sidecar_runtime(app: &tauri::AppHandle) -> Result<SidecarRuntime, String> {
    // PDF_ORGANIZER_SIDECAR_EXE は開発専用。リリースビルドでは無視する。
    #[cfg(debug_assertions)]
    {
        let explicit_exe =
            std::env::var_os("PDF_ORGANIZER_SIDECAR_EXE").map(std::path::PathBuf::from);
        if let Some(path) = explicit_exe.filter(|path| !path.as_os_str().is_empty()) {
            return sidecar_executable_runtime(path);
        }
    }

    let explicit_python = std::env::var_os("PDF_ORGANIZER_PYTHON").map(std::path::PathBuf::from);
    let explicit_recovery =
        std::env::var_os("PDF_ORGANIZER_RECOVERY_DIR").map(std::path::PathBuf::from);
    if explicit_python.is_none() && explicit_recovery.is_none() {
        if let Some(path) = bundled_sidecar_path(app) {
            return sidecar_executable_runtime(path);
        }
    }

    Ok(SidecarRuntime::Python {
        recovery_dir: find_recovery_dir()?,
        launcher: sidecar_python_launcher_from(explicit_python.as_deref()),
    })
}

fn sidecar_executable_runtime(path: std::path::PathBuf) -> Result<SidecarRuntime, String> {
    if path.is_file() {
        Ok(SidecarRuntime::BundledExecutable { path })
    } else {
        Err(format!(
            "PDF_ORGANIZER_SIDECAR_EXE does not point to a file: {}",
            path.display()
        ))
    }
}

fn bundled_sidecar_path(app: &tauri::AppHandle) -> Option<std::path::PathBuf> {
    let resource_dir = app.path().resource_dir().ok()?;
    bundled_sidecar_path_from_resource_dir(&resource_dir)
}

fn bundled_sidecar_path_from_resource_dir(
    resource_dir: &std::path::Path,
) -> Option<std::path::PathBuf> {
    let candidate = resource_dir.join(BUNDLED_SIDECAR_RESOURCE_PATH);
    candidate.is_file().then_some(candidate)
}

fn sidecar_process_spec(runtime: &SidecarRuntime, mode: SidecarMode) -> SidecarProcessSpec {
    match runtime {
        SidecarRuntime::BundledExecutable { path } => SidecarProcessSpec {
            program: path.clone(),
            args: match mode {
                SidecarMode::Resident => vec!["--sidecar-serve".to_string()],
                SidecarMode::Oneshot => vec!["--sidecar-request".to_string(), "-".to_string()],
            },
            current_dir: path.parent().map(std::path::Path::to_path_buf),
        },
        SidecarRuntime::Python {
            recovery_dir,
            launcher,
        } => {
            let mut args = launcher.args.clone();
            match mode {
                SidecarMode::Resident => {
                    args.extend([
                        "-m".to_string(),
                        "pdf_splitter_tool".to_string(),
                        "--sidecar-serve".to_string(),
                    ]);
                }
                SidecarMode::Oneshot => {
                    args.extend([
                        "-m".to_string(),
                        "pdf_splitter_tool".to_string(),
                        "--sidecar-request".to_string(),
                        "-".to_string(),
                    ]);
                }
            }
            SidecarProcessSpec {
                program: launcher.program.clone(),
                args,
                current_dir: Some(recovery_dir.clone()),
            }
        }
    }
}

fn sidecar_command(spec: &SidecarProcessSpec) -> std::process::Command {
    let mut command = std::process::Command::new(&spec.program);
    command.args(spec.args.iter().map(String::as_str));
    if let Some(current_dir) = &spec.current_dir {
        command.current_dir(current_dir);
    }
    command.env("PYTHONIOENCODING", "utf-8");
    command.env("PYTHONUTF8", "1");
    #[cfg(target_os = "windows")]
    command.creation_flags(CREATE_NO_WINDOW);
    command
}

fn spawn_sidecar_with_retry<T, F>(spawn: F) -> std::io::Result<T>
where
    F: FnMut() -> std::io::Result<T>,
{
    spawn_sidecar_with_retry_and_delay(spawn, SIDECAR_SPAWN_RETRY_DELAY)
}

fn spawn_sidecar_with_retry_and_delay<T, F>(
    mut spawn: F,
    retry_delay: std::time::Duration,
) -> std::io::Result<T>
where
    F: FnMut() -> std::io::Result<T>,
{
    let mut attempt = 1;
    loop {
        match spawn() {
            Ok(value) => return Ok(value),
            Err(error)
                if attempt < SIDECAR_SPAWN_MAX_ATTEMPTS
                    && is_retryable_sidecar_spawn_error(&error) =>
            {
                std::thread::sleep(retry_delay);
                attempt += 1;
            }
            Err(error) => return Err(error),
        }
    }
}

#[cfg(target_os = "windows")]
fn is_retryable_sidecar_spawn_error(error: &std::io::Error) -> bool {
    error.raw_os_error() == Some(32)
}

#[cfg(not(target_os = "windows"))]
fn is_retryable_sidecar_spawn_error(_error: &std::io::Error) -> bool {
    false
}

fn run_sidecar_resident(
    lane: &SidecarLaneState,
    runtime: &SidecarRuntime,
    request: &serde_json::Value,
    timeout: std::time::Duration,
) -> Result<serde_json::Value, String> {
    let mut slot = lane
        .request_slot
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());

    let needs_spawn = match slot.as_mut() {
        None => true,
        // A process that already exited is unusable; replace it lazily.
        Some(sidecar) => {
            let mut child = sidecar
                .child
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            !matches!(child.try_wait(), Ok(None))
        }
    };
    if needs_spawn {
        let _ = kill_resident_sidecar(&mut slot, &lane.active_child);
        let spec = sidecar_process_spec(runtime, SidecarMode::Resident);
        // Hold the lifecycle handle lock across spawn and registration so the
        // exit hook cannot miss a child in the narrow creation window.
        let mut active_child = lane
            .active_child
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let sidecar = spawn_resident_sidecar(&spec)?;
        *active_child = Some(std::sync::Arc::clone(&sidecar.child));
        drop(active_child);
        *slot = Some(sidecar);
    }

    let sidecar = slot
        .as_mut()
        .ok_or_else(|| "Python sidecar is not running".to_string())?;
    match send_request_to_sidecar(sidecar, request, timeout) {
        Ok(response) => Ok(response),
        Err(message) => {
            // Timeout, process death, or protocol desync: kill the process and
            // clear the slot so the next request re-spawns a fresh sidecar.
            let stderr_tail = kill_resident_sidecar(&mut slot, &lane.active_child);
            Err(append_stderr_tail(message, &stderr_tail))
        }
    }
}

fn spawn_resident_sidecar(
    spec: &SidecarProcessSpec,
) -> Result<ResidentSidecar, String> {
    let mut command = sidecar_command(spec);
    command
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    let child = spawn_sidecar_with_retry(|| command.spawn())
        .map_err(|error| format!("failed to start Python sidecar: {error}"))?;
    attach_resident_sidecar(child)
}

fn attach_resident_sidecar(mut child: std::process::Child) -> Result<ResidentSidecar, String> {
    let stdin = child.stdin.take();
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    let (Some(stdin), Some(stdout), Some(stderr)) = (stdin, stdout, stderr) else {
        let _ = child.kill();
        let _ = child.wait();
        return Err("failed to open Python sidecar pipes".to_string());
    };

    let (stdout_tx, stdout_rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        use std::io::BufRead;

        for line in std::io::BufReader::new(stdout).lines() {
            let is_read_error = line.is_err();
            if stdout_tx.send(line).is_err() || is_read_error {
                break;
            }
        }
        // Dropping stdout_tx disconnects the channel, signalling EOF.
    });

    let stderr_tail = std::sync::Arc::new(std::sync::Mutex::new(
        std::collections::VecDeque::with_capacity(STDERR_TAIL_MAX_LINES),
    ));
    let stderr_tail_writer = std::sync::Arc::clone(&stderr_tail);
    std::thread::spawn(move || {
        use std::io::BufRead;

        for line in std::io::BufReader::new(stderr).lines() {
            let Ok(line) = line else { break };
            let mut tail = stderr_tail_writer
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            tail.push_back(line);
            while tail.len() > STDERR_TAIL_MAX_LINES {
                tail.pop_front();
            }
        }
    });

    Ok(ResidentSidecar {
        child: std::sync::Arc::new(std::sync::Mutex::new(child)),
        stdin,
        stdout_rx,
        stderr_tail,
        next_id: 1,
    })
}

fn send_request_to_sidecar(
    sidecar: &mut ResidentSidecar,
    request: &serde_json::Value,
    timeout: std::time::Duration,
) -> Result<serde_json::Value, String> {
    use std::io::Write;

    let id = sidecar.next_id;
    sidecar.next_id += 1;
    let envelope = build_sidecar_envelope(id, request)?;
    sidecar
        .stdin
        .write_all(envelope.as_bytes())
        .and_then(|()| sidecar.stdin.write_all(b"\n"))
        .and_then(|()| sidecar.stdin.flush())
        .map_err(|error| format!("failed to write to Python sidecar: {error}"))?;

    match sidecar.stdout_rx.recv_timeout(timeout) {
        Ok(Ok(line)) => parse_sidecar_response_line(&line, id),
        Ok(Err(error)) => Err(format!("failed to read Python sidecar stdout: {error}")),
        Err(std::sync::mpsc::RecvTimeoutError::Timeout) => Err(format!(
            "Python sidecar timed out after {} ms",
            timeout.as_millis()
        )),
        Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
            Err("Python sidecar exited unexpectedly".to_string())
        }
    }
}

fn build_sidecar_envelope(id: u64, request: &serde_json::Value) -> Result<String, String> {
    serde_json::to_string(&serde_json::json!({ "id": id, "request": request }))
        .map_err(|error| format!("failed to encode sidecar request envelope: {error}"))
}

fn parse_sidecar_response_line(
    line: &str,
    expected_id: u64,
) -> Result<serde_json::Value, String> {
    let envelope: serde_json::Value = serde_json::from_str(line).map_err(|error| {
        format!("Python sidecar protocol desync: response is not valid JSON: {error}")
    })?;
    let received_id = envelope.get("id").and_then(serde_json::Value::as_u64);
    if received_id != Some(expected_id) {
        let received = envelope
            .get("id")
            .map_or_else(|| "missing".to_string(), |value| value.to_string());
        return Err(format!(
            "Python sidecar protocol desync: expected response id {expected_id}, received {received}"
        ));
    }
    envelope
        .get("response")
        .cloned()
        .ok_or_else(|| "Python sidecar protocol desync: response field is missing".to_string())
}

/// Kills the resident sidecar (if any), clears the slot, and returns a
/// snapshot of its recent stderr lines for diagnostics.
///
/// child.wait() は kill 後に別スレッドへデタッチする。kill が失敗/遅延した場合でも
/// 呼び出し元スレッドが Mutex を保持したまま wait() でブロックするのを防ぐため。
/// stderr_tail のスナップショットは wait() の前に取得する（wait() 後はアクセス不可）。
fn kill_resident_sidecar(
    slot: &mut Option<ResidentSidecar>,
    active_child: &std::sync::Mutex<Option<SharedChild>>,
) -> String {
    match slot.take() {
        Some(sidecar) => {
            // wait() 前にスナップショットを取る（move 後はアクセス不可になるため）
            let tail = stderr_tail_snapshot(&sidecar.stderr_tail);
            *active_child
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()) = None;
            let child = std::sync::Arc::clone(&sidecar.child);
            let _ = child
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .kill();
            // wait() をバックグラウンドスレッドにデタッチして呼び出し元をブロックしない
            std::thread::spawn(move || {
                let _ = child
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner())
                    .wait();
            });
            tail
        }
        None => String::new(),
    }
}

/// Kills both lane processes without waiting for their request locks. The child
/// handle is intentionally tracked outside the request slot so an in-flight
/// export cannot delay app shutdown or leave a sidecar process behind.
fn kill_resident_sidecars_for_shutdown(state: &SidecarState) {
    for lane in [&state.interactive, &state.bulk] {
        let child = lane
            .active_child
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .take();
        if let Some(child) = child {
            let _ = child
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .kill();
        }
    }
}

fn stderr_tail_snapshot(
    stderr_tail: &std::sync::Mutex<std::collections::VecDeque<String>>,
) -> String {
    let tail = stderr_tail
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    tail.iter()
        .map(String::as_str)
        .collect::<Vec<_>>()
        .join("\n")
}

fn append_stderr_tail(message: String, stderr_tail: &str) -> String {
    if stderr_tail.trim().is_empty() {
        message
    } else {
        format!("{message}\nPython sidecar stderr (recent lines):\n{stderr_tail}")
    }
}

/// コマンド別タイムアウトを解決する。
///
/// - 長時間コマンド（export / blank_candidates / index_candidates / search_text）:
///   既定 300,000 ms。環境変数 `PDF_ORGANIZER_LONG_TIMEOUT_MS` で上書き可。
/// - 短時間コマンド（page_preview 等）:
///   既定 30,000 ms。環境変数 `PDF_ORGANIZER_SIDECAR_TIMEOUT_MS` で上書き可。
///
fn resolve_command_timeout(request: &serde_json::Value) -> std::time::Duration {
    if sidecar_lane(request) == SidecarLane::Bulk {
        let override_val = std::env::var("PDF_ORGANIZER_LONG_TIMEOUT_MS").ok();
        sidecar_timeout_from_with_default(override_val.as_deref(), 300_000)
    } else {
        let override_val = std::env::var("PDF_ORGANIZER_SIDECAR_TIMEOUT_MS").ok();
        sidecar_timeout_from(override_val.as_deref())
    }
}

fn sidecar_lane(request: &serde_json::Value) -> SidecarLane {
    match request
        .get("command")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("")
    {
        "preflight" | "export" | "blank_candidates" | "index_candidates" | "search_text" => {
            SidecarLane::Bulk
        }
        _ => SidecarLane::Interactive,
    }
}

/// Legacy one-process-per-request execution, kept as a fallback that can be
/// selected with `PDF_ORGANIZER_SIDECAR_MODE=oneshot`.
fn run_sidecar_oneshot(
    runtime: &SidecarRuntime,
    request_text: &str,
    timeout: std::time::Duration,
) -> Result<serde_json::Value, String> {
    let spec = sidecar_process_spec(runtime, SidecarMode::Oneshot);
    let mut command = sidecar_command(&spec);
    command
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    let mut child = spawn_sidecar_with_retry(|| command.spawn())
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
    let explicit_dir = std::env::var_os("PDF_ORGANIZER_RECOVERY_DIR").map(std::path::PathBuf::from);

    // Try current_dir first (works during development when launched from project root).
    if let Ok(current_dir) = std::env::current_dir() {
        if let Ok(dir) = find_recovery_dir_from(&current_dir, explicit_dir.as_deref()) {
            return Ok(dir);
        }
    }

    // Fallback: try the directory containing the executable.
    // In a distributed installation the recovery/ folder is expected to live next to
    // the installed binary, so current_exe().parent() is the correct search root.
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            if let Ok(dir) = find_recovery_dir_from(exe_dir, explicit_dir.as_deref()) {
                return Ok(dir);
            }
        }
    }

    Err("failed to locate recovery/pdf_splitter_tool sidecar".to_string())
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

#[derive(Clone, Debug, PartialEq, Eq)]
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
    sidecar_timeout_from_with_default(value, 30_000)
}

fn sidecar_timeout_from_with_default(value: Option<&str>, default_ms: u64) -> std::time::Duration {
    value
        .and_then(|raw| raw.trim().parse::<u64>().ok())
        .filter(|milliseconds| *milliseconds > 0)
        .map(std::time::Duration::from_millis)
        .unwrap_or_else(|| std::time::Duration::from_millis(default_ms))
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
            let killed = child.kill().is_ok();
            if killed {
                // kill 成功時のみ wait/join で後始末（プロセスが終了しているので EOF が来る）
                let _ = child.wait();
                let _ = join_child_pipe_reader(stdout_reader, "stdout");
                let _ = join_child_pipe_reader(stderr_reader, "stderr");
            } else {
                // kill 失敗時はプロセスが生きたまま wait/join するとブロックするためデタッチ
                // JoinHandle を drop してもスレッドは動き続け、プロセス終了時に自然回収される
                drop(stdout_reader);
                drop(stderr_reader);
            }
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

    // Verify that find_recovery_dir_from succeeds when the sidecar marker exists
    // under the exe-adjacent directory structure.  Because current_exe() cannot be
    // redirected in a unit test, we exercise the underlying find_recovery_dir_from
    // helper directly using a controlled temp directory that mimics the layout
    // expected in a distributed installation (recovery/ next to the binary).
    #[test]
    fn recovery_dir_found_from_exe_adjacent_layout() {
        // Simulate: <install_root>/recovery/pdf_splitter_tool/__main__.py
        //           <install_root>/app.exe   <- exe_dir = <install_root>
        let install_root = unique_test_dir("exe-adjacent");
        let recovery_dir = install_root.join("recovery");
        write_sidecar_marker(&recovery_dir);

        // exe_dir == install_root: ancestors traversal finds install_root/recovery.
        let resolved = find_recovery_dir_from(&install_root, None).unwrap();
        assert_eq!(resolved, recovery_dir);
    }

    #[test]
    fn recovery_dir_not_found_returns_error() {
        let empty_root = unique_test_dir("missing");

        let result = find_recovery_dir_from(&empty_root, None);
        assert!(result.is_err());
    }

    #[test]
    fn reveal_target_rejects_empty_or_blank_path() {
        assert!(reveal_target("", "").is_err());
        assert!(reveal_target("   ", "").is_err());
    }

    #[test]
    fn reveal_target_rejects_missing_path() {
        let missing = unique_test_dir("reveal-missing").join("does-not-exist");
        assert!(reveal_target(&missing.to_string_lossy(), "").is_err());
    }

    #[test]
    fn reveal_target_accepts_existing_directory() {
        let dir = unique_test_dir("reveal-ok");

        let resolved = reveal_target(&dir.to_string_lossy(), "").unwrap();

        assert_eq!(resolved, dir);
    }

    // #109: スコープ検証のテスト
    #[test]
    fn reveal_target_accepts_path_within_allowed_base() {
        let base = unique_test_dir("reveal-scope-base");
        let subdir = base.join("output");
        std::fs::create_dir_all(&subdir).unwrap();

        let resolved =
            reveal_target(&subdir.to_string_lossy(), &base.to_string_lossy()).unwrap();

        assert_eq!(resolved.canonicalize().unwrap(), subdir.canonicalize().unwrap());
    }

    #[test]
    fn reveal_target_rejects_path_outside_allowed_base() {
        let base = unique_test_dir("reveal-scope-allowed");
        let outside = unique_test_dir("reveal-scope-outside");
        // base, outside ともに実在するディレクトリ
        let _ = std::fs::create_dir_all(&base);
        let _ = std::fs::create_dir_all(&outside);

        let result = reveal_target(&outside.to_string_lossy(), &base.to_string_lossy());

        assert!(result.is_err(), "expected scope violation error");
        let msg = result.unwrap_err();
        assert!(
            msg.contains("outside"),
            "error should mention 'outside': {msg}"
        );
    }

    #[test]
    fn reveal_target_skips_scope_check_when_allowed_base_is_empty() {
        let dir = unique_test_dir("reveal-scope-nocheck");

        // allowed_base が空文字のときはスコープ検証をスキップして素通りする
        let resolved = reveal_target(&dir.to_string_lossy(), "").unwrap();
        assert_eq!(resolved, dir);
    }

    // #104: コマンド別タイムアウトのテスト
    #[test]
    fn resolve_command_timeout_long_commands_use_300s() {
        for cmd in &["preflight", "export", "blank_candidates", "index_candidates", "search_text"] {
            let request = serde_json::json!({ "command": cmd });
            let timeout = resolve_command_timeout(&request);
            assert_eq!(
                timeout,
                std::time::Duration::from_millis(300_000),
                "command={cmd} should use 300s timeout"
            );
        }
    }

    #[test]
    fn resolve_command_timeout_short_commands_use_30s() {
        for cmd in &["page_preview", "page_thumbnail", "page_text", "pdf_info"] {
            let request = serde_json::json!({ "command": cmd });
            let timeout = resolve_command_timeout(&request);
            assert_eq!(
                timeout,
                std::time::Duration::from_secs(30),
                "command={cmd} should use 30s timeout"
            );
        }
    }

    #[test]
    fn resolve_command_timeout_unknown_command_uses_30s() {
        let request = serde_json::json!({ "command": "something_new" });
        let timeout = resolve_command_timeout(&request);
        assert_eq!(timeout, std::time::Duration::from_secs(30));
    }

    #[test]
    fn resolve_command_timeout_missing_command_field_uses_30s() {
        let request = serde_json::json!({ "foo": "bar" });
        let timeout = resolve_command_timeout(&request);
        assert_eq!(timeout, std::time::Duration::from_secs(30));
    }

    #[test]
    fn long_running_commands_use_the_bulk_lane() {
        for command in [
            "preflight",
            "export",
            "blank_candidates",
            "index_candidates",
            "search_text",
        ] {
            assert_eq!(
                sidecar_lane(&serde_json::json!({ "command": command })),
                SidecarLane::Bulk,
                "command={command} should not block interactive requests"
            );
        }
    }

    #[test]
    fn preview_and_other_short_commands_use_the_interactive_lane() {
        for command in [
            "page_preview",
            "page_thumbnail",
            "page_text",
            "search_highlights",
            "pdf_info",
            "state_load",
            "state_save",
        ] {
            assert_eq!(
                sidecar_lane(&serde_json::json!({ "command": command })),
                SidecarLane::Interactive,
                "command={command} should stay responsive during bulk work"
            );
        }
    }

    #[test]
    fn sidecar_lanes_have_independent_locks() {
        let state = SidecarState::new();
        let bulk_lane = state.lane_for(SidecarLane::Bulk);
        let interactive_lane = state.lane_for(SidecarLane::Interactive);
        let _bulk_guard = bulk_lane.request_slot.lock().unwrap();

        assert!(interactive_lane.request_slot.try_lock().is_ok());
        assert!(bulk_lane.request_slot.try_lock().is_err());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn sidecar_spawn_retries_windows_sharing_violation_until_success() {
        let mut attempts = 0;
        let result = spawn_sidecar_with_retry_and_delay(
            || {
                attempts += 1;
                if attempts < 3 {
                    Err(std::io::Error::from_raw_os_error(32))
                } else {
                    Ok("started")
                }
            },
            std::time::Duration::ZERO,
        );

        assert_eq!(result.unwrap(), "started");
        assert_eq!(attempts, 3);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn sidecar_spawn_stops_after_sharing_violation_retry_limit() {
        let mut attempts = 0;
        let result: std::io::Result<()> = spawn_sidecar_with_retry_and_delay(
            || {
                attempts += 1;
                Err(std::io::Error::from_raw_os_error(32))
            },
            std::time::Duration::ZERO,
        );

        assert_eq!(result.unwrap_err().raw_os_error(), Some(32));
        assert_eq!(attempts, SIDECAR_SPAWN_MAX_ATTEMPTS);
    }

    #[test]
    fn sidecar_spawn_does_not_retry_non_sharing_errors() {
        let mut attempts = 0;
        let result: std::io::Result<()> = spawn_sidecar_with_retry_and_delay(
            || {
                attempts += 1;
                Err(std::io::Error::from_raw_os_error(2))
            },
            std::time::Duration::ZERO,
        );

        assert_eq!(result.unwrap_err().raw_os_error(), Some(2));
        assert_eq!(attempts, 1);
    }

    #[test]
    fn shutdown_does_not_wait_for_a_busy_lane() {
        let state = SidecarState::new();
        let bulk_lane = state.lane_for(SidecarLane::Bulk);
        let _bulk_guard = bulk_lane.request_slot.lock().unwrap();
        let started_at = std::time::Instant::now();

        kill_resident_sidecars_for_shutdown(&state);

        assert!(started_at.elapsed() < std::time::Duration::from_millis(100));
    }

    #[test]
    fn sidecar_timeout_with_default_uses_provided_default() {
        let timeout = sidecar_timeout_from_with_default(None, 60_000);
        assert_eq!(timeout, std::time::Duration::from_millis(60_000));

        let timeout = sidecar_timeout_from_with_default(Some("5000"), 60_000);
        assert_eq!(timeout, std::time::Duration::from_millis(5_000));
    }

    #[test]
    fn sidecar_mode_defaults_to_resident() {
        assert_eq!(sidecar_mode_from(None), SidecarMode::Resident);
        assert_eq!(sidecar_mode_from(Some("")), SidecarMode::Resident);
        assert_eq!(sidecar_mode_from(Some("resident")), SidecarMode::Resident);
        assert_eq!(sidecar_mode_from(Some("unknown")), SidecarMode::Resident);
    }

    #[test]
    fn sidecar_mode_oneshot_can_be_selected() {
        assert_eq!(sidecar_mode_from(Some("oneshot")), SidecarMode::Oneshot);
        assert_eq!(sidecar_mode_from(Some(" ONESHOT ")), SidecarMode::Oneshot);
    }

    #[test]
    fn bundled_sidecar_path_is_resolved_from_resource_dir() {
        let root = unique_test_dir("resource-sidecar");
        let sidecar = root.join(BUNDLED_SIDECAR_RESOURCE_PATH);
        std::fs::create_dir_all(sidecar.parent().unwrap()).unwrap();
        std::fs::write(&sidecar, "").unwrap();

        let resolved = bundled_sidecar_path_from_resource_dir(&root).unwrap();

        assert_eq!(resolved, sidecar);
    }

    #[test]
    fn bundled_sidecar_process_spec_uses_executable_directly() {
        let path = std::path::PathBuf::from("C:\\Program Files\\PDF整理ツール\\resources\\sidecar\\pdf-splitter-sidecar.exe");
        let runtime = SidecarRuntime::BundledExecutable { path: path.clone() };

        let resident = sidecar_process_spec(&runtime, SidecarMode::Resident);
        let oneshot = sidecar_process_spec(&runtime, SidecarMode::Oneshot);

        assert_eq!(resident.program, path);
        assert_eq!(resident.args, vec!["--sidecar-serve"]);
        assert_eq!(oneshot.args, vec!["--sidecar-request", "-"]);
        assert!(resident.current_dir.unwrap().ends_with("resources\\sidecar"));
    }

    #[test]
    fn python_sidecar_process_spec_keeps_development_fallback() {
        let recovery_dir = std::path::PathBuf::from("C:\\repo\\recovery");
        let runtime = SidecarRuntime::Python {
            recovery_dir: recovery_dir.clone(),
            launcher: PythonLauncher {
                program: std::path::PathBuf::from("py"),
                args: vec!["-3.12".to_string()],
            },
        };

        let spec = sidecar_process_spec(&runtime, SidecarMode::Resident);

        assert_eq!(spec.program, std::path::PathBuf::from("py"));
        assert_eq!(spec.args, vec!["-3.12", "-m", "pdf_splitter_tool", "--sidecar-serve"]);
        assert_eq!(spec.current_dir, Some(recovery_dir));
    }

    #[test]
    fn sidecar_envelope_is_compact_single_line_json() {
        let request = serde_json::json!({"command": "page_preview", "page_no": 3});

        let envelope = build_sidecar_envelope(7, &request).unwrap();

        assert_eq!(
            envelope,
            r#"{"id":7,"request":{"command":"page_preview","page_no":3}}"#
        );
        assert!(!envelope.contains('\n'));
    }

    #[test]
    fn sidecar_response_with_matching_id_returns_response_payload() {
        let response =
            parse_sidecar_response_line(r#"{"id":7,"response":{"ok":true}}"#, 7).unwrap();

        assert_eq!(response, serde_json::json!({"ok": true}));
    }

    #[test]
    fn sidecar_response_with_mismatched_or_null_id_is_desync() {
        let mismatched =
            parse_sidecar_response_line(r#"{"id":8,"response":{"ok":true}}"#, 7).unwrap_err();
        let null_id =
            parse_sidecar_response_line(r#"{"id":null,"response":{"ok":false}}"#, 7).unwrap_err();

        assert!(mismatched.contains("desync"), "{mismatched}");
        assert!(null_id.contains("desync"), "{null_id}");
    }

    #[test]
    fn sidecar_response_that_is_not_json_is_desync() {
        let error = parse_sidecar_response_line("plain text noise", 7).unwrap_err();

        assert!(error.contains("desync"), "{error}");
    }

    #[test]
    fn sidecar_response_without_response_field_is_desync() {
        let error = parse_sidecar_response_line(r#"{"id":7}"#, 7).unwrap_err();

        assert!(error.contains("desync"), "{error}");
    }

    // This test spawns a real `py -3.12` process. It is excluded from the
    // default `cargo test` run (and from CI) because the Windows `py` launcher
    // with Python 3.12 is not guaranteed to be present in every environment.
    // Run manually with `cargo test -- --ignored` when a local Python 3.12 is
    // available.
    #[test]
    #[ignore = "requires py -3.12 launcher; run with -- --ignored locally"]
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

    const FAKE_ECHO_SIDECAR: &str = r#"
import json
import sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    envelope = json.loads(line)
    reply = {"id": envelope["id"], "response": {"ok": True, "echo": envelope["request"]}}
    sys.stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
    sys.stdout.flush()
"#;

    const FAKE_WRONG_ID_SIDECAR: &str = r#"
import json
import sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    reply = {"id": 9999, "response": {"ok": True}}
    sys.stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
    sys.stdout.flush()
"#;

    const FAKE_SLOW_ECHO_SIDECAR: &str = r#"
import json
import sys
import time
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    envelope = json.loads(line)
    time.sleep(1.5)
    reply = {"id": envelope["id"], "response": {"ok": True, "echo": envelope["request"]}}
    sys.stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
    sys.stdout.flush()
"#;

    fn spawn_fake_sidecar(python_body: &str) -> ResidentSidecar {
        let child = std::process::Command::new("py")
            .args(["-3.12", "-c", python_body])
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .unwrap();
        attach_resident_sidecar(child).unwrap()
    }

    // The four tests below use spawn_fake_sidecar, which calls `py -3.12`
    // directly (not via the PDF_ORGANIZER_PYTHON override). They are ignored
    // in CI for the same reason as sidecar_wait_drains_large_stdout_while_process_runs.
    #[test]
    #[ignore = "requires py -3.12 launcher; run with -- --ignored locally"]
    fn resident_sidecar_exchanges_sequential_requests_with_monotonic_ids() {
        let mut sidecar = spawn_fake_sidecar(FAKE_ECHO_SIDECAR);

        for request_no in 1..=3u64 {
            let request = serde_json::json!({"command": "ping", "n": request_no});
            let response = send_request_to_sidecar(
                &mut sidecar,
                &request,
                std::time::Duration::from_secs(10),
            )
            .unwrap();
            assert_eq!(response, serde_json::json!({"ok": true, "echo": request}));
        }
        assert_eq!(sidecar.next_id, 4);

        stop_test_sidecar(&sidecar);
    }

    #[test]
    #[ignore = "requires py -3.12 launcher; run with -- --ignored locally"]
    fn resident_lanes_exchange_requests_concurrently() {
        let state = SidecarState::new();
        install_fake_sidecar(&state.bulk, FAKE_SLOW_ECHO_SIDECAR);
        install_fake_sidecar(&state.interactive, FAKE_ECHO_SIDECAR);

        let bulk_lane = state.lane_for(SidecarLane::Bulk);
        let bulk_worker = std::thread::spawn(move || {
            let runtime = test_sidecar_runtime();
            run_sidecar_resident(
                &bulk_lane,
                &runtime,
                &serde_json::json!({"command": "export"}),
                std::time::Duration::from_secs(10),
            )
        });
        std::thread::sleep(std::time::Duration::from_millis(150));

        let interactive_started_at = std::time::Instant::now();
        let response = run_sidecar_resident(
            &state.interactive,
            &test_sidecar_runtime(),
            &serde_json::json!({"command": "page_preview"}),
            std::time::Duration::from_secs(10),
        )
        .unwrap();

        assert!(response["ok"].as_bool().unwrap());
        assert!(interactive_started_at.elapsed() < std::time::Duration::from_secs(1));
        assert!(bulk_worker.join().unwrap().is_ok());
        kill_resident_sidecars_for_shutdown(&state);
    }

    #[test]
    #[ignore = "requires py -3.12 launcher; run with -- --ignored locally"]
    fn shutdown_kills_a_busy_lane_without_waiting_for_the_request() {
        let state = SidecarState::new();
        install_fake_sidecar(
            &state.bulk,
            "import sys, time\nsys.stdin.readline()\ntime.sleep(60)\n",
        );
        let child = state.bulk.active_child.lock().unwrap().clone().unwrap();
        let bulk_lane = state.lane_for(SidecarLane::Bulk);
        let bulk_worker = std::thread::spawn(move || {
            run_sidecar_resident(
                &bulk_lane,
                &test_sidecar_runtime(),
                &serde_json::json!({"command": "export"}),
                std::time::Duration::from_secs(60),
            )
        });
        std::thread::sleep(std::time::Duration::from_millis(150));

        let shutdown_started_at = std::time::Instant::now();
        kill_resident_sidecars_for_shutdown(&state);

        assert!(shutdown_started_at.elapsed() < std::time::Duration::from_secs(1));
        assert!(bulk_worker.join().unwrap().is_err());
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        loop {
            let exited = child
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .try_wait()
                .unwrap()
                .is_some();
            if exited {
                break;
            }
            assert!(
                std::time::Instant::now() < deadline,
                "busy sidecar process remained alive after shutdown"
            );
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
    }

    #[test]
    #[ignore = "requires py -3.12 launcher; run with -- --ignored locally"]
    fn resident_sidecar_times_out_when_no_response_arrives() {
        let mut sidecar =
            spawn_fake_sidecar("import sys, time\nsys.stdin.readline()\ntime.sleep(60)\n");
        let request = serde_json::json!({"command": "ping"});

        let error =
            send_request_to_sidecar(&mut sidecar, &request, std::time::Duration::from_millis(300))
                .unwrap_err();

        assert!(error.contains("timed out"), "{error}");
        stop_test_sidecar(&sidecar);
    }

    #[test]
    #[ignore = "requires py -3.12 launcher; run with -- --ignored locally"]
    fn resident_sidecar_reports_process_death_and_keeps_stderr_tail() {
        let mut sidecar = spawn_fake_sidecar(
            "import sys\nsys.stdin.readline()\nsys.stderr.write('fake sidecar crashed\\n')\nsys.stderr.flush()\nsys.exit(3)\n",
        );
        let request = serde_json::json!({"command": "ping"});

        let error =
            send_request_to_sidecar(&mut sidecar, &request, std::time::Duration::from_secs(10))
                .unwrap_err();
        assert!(error.contains("exited"), "{error}");

        // The stderr reader thread runs asynchronously; poll briefly for it
        // to capture the crash line before taking the snapshot.
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        loop {
            if stderr_tail_snapshot(&sidecar.stderr_tail).contains("fake sidecar crashed") {
                break;
            }
            assert!(
                std::time::Instant::now() < deadline,
                "stderr tail never captured the crash line"
            );
            std::thread::sleep(std::time::Duration::from_millis(20));
        }

        let mut slot = Some(sidecar);
        let active_child = std::sync::Mutex::new(
            slot.as_ref().map(|sidecar| std::sync::Arc::clone(&sidecar.child)),
        );
        let stderr_tail = kill_resident_sidecar(&mut slot, &active_child);
        assert!(stderr_tail.contains("fake sidecar crashed"), "{stderr_tail}");
        assert!(slot.is_none());
    }

    #[test]
    #[ignore = "requires py -3.12 launcher; run with -- --ignored locally"]
    fn resident_sidecar_detects_id_desync() {
        let mut sidecar = spawn_fake_sidecar(FAKE_WRONG_ID_SIDECAR);
        let request = serde_json::json!({"command": "ping"});

        let error =
            send_request_to_sidecar(&mut sidecar, &request, std::time::Duration::from_secs(10))
                .unwrap_err();

        assert!(error.contains("desync"), "{error}");
        stop_test_sidecar(&sidecar);
    }

    #[test]
    fn append_stderr_tail_only_when_present() {
        assert_eq!(append_stderr_tail("boom".to_string(), ""), "boom");
        assert_eq!(append_stderr_tail("boom".to_string(), "  \n "), "boom");

        let combined = append_stderr_tail("boom".to_string(), "trace line");
        assert!(combined.starts_with("boom\n"));
        assert!(combined.contains("trace line"));
    }

    fn test_sidecar_runtime() -> SidecarRuntime {
        SidecarRuntime::Python {
            recovery_dir: std::path::PathBuf::from("."),
            launcher: sidecar_python_launcher_from(None),
        }
    }

    fn install_fake_sidecar(lane: &SidecarLaneState, python_body: &str) {
        let sidecar = spawn_fake_sidecar(python_body);
        *lane.active_child.lock().unwrap() = Some(std::sync::Arc::clone(&sidecar.child));
        *lane.request_slot.lock().unwrap() = Some(sidecar);
    }

    fn stop_test_sidecar(sidecar: &ResidentSidecar) {
        let mut child = sidecar
            .child
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let _ = child.kill();
        let _ = child.wait();
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
