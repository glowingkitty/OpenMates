//! Bounded child-process execution for the source host's confined commands
//! (shared core, native source host only): wall-clock deadline, per-stream
//! output cap with a truncation marker, whole-process-group kill. The sandbox
//! launcher (`command_sandbox.rs`) builds the `Command`; this module only runs
//! it. Mirrors the job bounds of npm `remoteCommandRuntime.ts`.
//! spec: specifications/features/app-skills/code-run `code-run.remote.managed-jobs`.

use std::io::Read;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

/// How often the deadline is checked while the child runs.
const POLL_INTERVAL: Duration = Duration::from_millis(10);
/// How long stream readers may lag behind the exited child before the result
/// is reported without their remaining bytes.
const READER_GRACE: Duration = Duration::from_secs(2);
/// Read chunk size for the pipe readers.
const CHUNK: usize = 8 * 1024;

/// One captured output stream, bounded to the configured cap.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct Captured {
    /// First `cap` bytes the stream produced.
    pub(crate) bytes: Vec<u8>,
    /// Total bytes the stream produced (kept and dropped).
    pub(crate) total: u64,
}

impl Captured {
    /// Whether bytes were dropped.
    pub(crate) fn truncated(&self) -> bool {
        self.total > self.bytes.len() as u64
    }

    /// Lossy UTF-8 text plus, when bytes were dropped, a marker naming how
    /// many. A split multi-byte character at the cut becomes U+FFFD.
    pub(crate) fn text(&self) -> String {
        let mut text = String::from_utf8_lossy(&self.bytes).into_owned();
        if self.truncated() {
            let omitted = self.total - self.bytes.len() as u64;
            text.push_str(&format!(
                "\n[openmates: output truncated, {omitted} more bytes]"
            ));
        }
        text
    }
}

/// Outcome of one bounded run.
#[derive(Debug)]
pub(crate) struct ProcessOutcome {
    /// Exit code, `None` when a signal ended the process (including the
    /// deadline kill).
    pub(crate) exit_code: Option<i32>,
    /// Terminating signal number, when there was one.
    pub(crate) signal: Option<i32>,
    /// Captured standard output.
    pub(crate) stdout: Captured,
    /// Captured standard error.
    pub(crate) stderr: Captured,
    /// The deadline passed and the process group was killed.
    pub(crate) timed_out: bool,
    /// Wall-clock time from spawn to exit.
    pub(crate) duration: Duration,
}

/// Run `command` with stdin closed, piped output and its own process group.
///
/// At the deadline the whole process group gets `SIGKILL`. After a normal
/// exit the group is killed as well, so a background descendant never
/// outlives the call. A sandbox that starts a new session (bubblewrap
/// `--new-session`) is torn down through its PID namespace instead: killing
/// the group kills the outer `bwrap`, whose `--die-with-parent` child is the
/// namespace's init.
///
/// # Errors
/// The spawn or wait IO error; the caller maps it to `launch_failed`.
pub(crate) fn run_bounded(
    mut command: Command,
    timeout: Duration,
    cap: usize,
) -> std::io::Result<ProcessOutcome> {
    use std::os::unix::process::{CommandExt, ExitStatusExt};
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0);
    let started = Instant::now();
    let mut child = command.spawn()?;
    let group = rustix::process::Pid::from_child(&child);
    let (sender, receiver) = mpsc::channel::<(bool, Captured)>();
    let mut readers = 0;
    if let Some(stdout) = child.stdout.take() {
        spawn_reader(stdout, cap, true, sender.clone());
        readers += 1;
    }
    if let Some(stderr) = child.stderr.take() {
        spawn_reader(stderr, cap, false, sender.clone());
        readers += 1;
    }
    drop(sender);
    let deadline = started + timeout;
    let mut timed_out = false;
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if Instant::now() >= deadline {
            timed_out = true;
            kill_group(group);
            break child.wait()?;
        }
        std::thread::sleep(POLL_INTERVAL);
    };
    let duration = started.elapsed();
    // Reap descendants left in the group (an `&` job) so pipes close and
    // nothing keeps running after the result is reported.
    kill_group(group);
    let mut stdout = Captured::default();
    let mut stderr = Captured::default();
    let grace = Instant::now() + READER_GRACE;
    for _ in 0..readers {
        let left = grace.saturating_duration_since(Instant::now());
        match receiver.recv_timeout(left) {
            Ok((true, captured)) => stdout = captured,
            Ok((false, captured)) => stderr = captured,
            // A descendant outside the group (new session) still holds a
            // pipe; report what the child produced instead of hanging.
            Err(_) => break,
        }
    }
    Ok(ProcessOutcome {
        exit_code: status.code(),
        signal: status.signal(),
        stdout,
        stderr,
        timed_out,
        duration,
    })
}

fn kill_group(group: rustix::process::Pid) {
    // ESRCH (the group is already gone) is the normal case after an exit;
    // nothing else can be done about a failed kill here.
    let _ = rustix::process::kill_process_group(group, rustix::process::Signal::KILL);
}

/// Drain one pipe to EOF, keeping the first `cap` bytes and counting the rest,
/// so a chatty child never blocks on a full pipe.
fn spawn_reader(
    mut stream: impl Read + Send + 'static,
    cap: usize,
    is_stdout: bool,
    sender: mpsc::Sender<(bool, Captured)>,
) {
    std::thread::spawn(move || {
        let mut captured = Captured::default();
        let mut buffer = [0u8; CHUNK];
        loop {
            match stream.read(&mut buffer) {
                Ok(0) => break,
                Ok(read) => {
                    captured.total += read as u64;
                    let room = cap.saturating_sub(captured.bytes.len());
                    captured.bytes.extend_from_slice(&buffer[..read.min(room)]);
                }
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => {}
                // A read error ends the stream; what was read so far stands.
                Err(_) => break,
            }
        }
        // The receiver may have stopped waiting after its grace period.
        let _ = sender.send((is_stdout, captured));
    });
}
