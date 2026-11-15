//! Streaming, stoppable child-process runner for managed remote-command jobs
//! (shared core, native source host only). Sibling of the bounded runner in
//! `command_process.rs`: same process group, same kill path, but output is
//! delivered as sanitized, redacted, UTF-8-safe chunks while the child runs.
//! Mirrors the output handling of npm `remoteCommandRuntime.ts`
//! (`#collectOutput`, `#emitOutput`, `terminate`).
//! spec: specifications/features/app-skills/code-run `code-run.remote.run-limits`.
// reason: the job source that consumes this runner lands in `source_host/job`
// in the same plan item; until it is wired the items are only used by tests.
#![allow(dead_code)]

use std::io::Read;
use std::process::{Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::{Duration, Instant};

use super::command_process::signal_group;
use crate::remote_command_review::clean_terminal_text;

/// Shortest accepted deadline (matches npm `MIN_DEADLINE_MS`).
pub(crate) const MIN_DEADLINE: Duration = Duration::from_millis(100);
/// Longest accepted deadline (matches npm `MAX_DEADLINE_MS`, 24 h).
pub(crate) const MAX_DEADLINE: Duration = Duration::from_secs(24 * 60 * 60);
/// Retained-output cap across both streams (npm `MAX_RETAINED_OUTPUT_BYTES`).
pub(crate) const MAX_RETAINED_OUTPUT_BYTES: usize = 256 * 1024;
/// Largest single output event (npm `MAX_OUTPUT_CHUNK_BYTES`).
pub(crate) const MAX_OUTPUT_CHUNK_BYTES: usize = 16 * 1024;
/// Replacement text for a redacted credential value.
pub(crate) const REDACTION_MARKER: &str = "[REDACTED_CREDENTIAL]";

/// Time between `SIGTERM` and `SIGKILL` (npm `terminate`: 2 s).
const TERM_GRACE: Duration = Duration::from_secs(2);
/// How long readers may lag behind the exited child before the final event.
const READER_GRACE: Duration = Duration::from_secs(2);
/// Supervisor poll interval for exit, stop and deadline.
const POLL_INTERVAL: Duration = Duration::from_millis(10);
/// Pipe read size.
const READ_SIZE: usize = 8 * 1024;

/// Which pipe a chunk came from.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum StreamName {
    /// Standard output.
    Stdout,
    /// Standard error.
    Stderr,
}

/// Terminal state of a streamed run.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ExitStatusKind {
    /// Exit code 0.
    Succeeded,
    /// Non-zero exit, or a signal not requested by us (`code` is `None`).
    Failed {
        /// Exit code, `None` when a signal ended the process.
        code: Option<i32>,
    },
    /// The deadline passed and the process group was terminated.
    TimedOut,
    /// `stop()` (or dropping the handle) terminated the process group.
    Stopped,
}

/// One event of a streamed run. Exactly one `Exit` arrives, always last.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum StreamEvent {
    /// Sanitized, redacted text, at most [`MAX_OUTPUT_CHUNK_BYTES`] long.
    Output {
        /// Source pipe.
        stream: StreamName,
        /// Chunk text (valid UTF-8, terminal escapes stripped).
        text: String,
    },
    /// The retained cap was hit; later output is dropped, the process runs on.
    OutputTruncated {
        /// Bytes delivered before the cap.
        retained_bytes: usize,
    },
    /// Final event.
    Exit {
        /// How the run ended.
        status: ExitStatusKind,
    },
}

/// Why a streamed run could not start.
#[derive(Debug)]
pub(crate) enum StreamError {
    /// The deadline is outside [`MIN_DEADLINE`]..=[`MAX_DEADLINE`]. Maps to
    /// the `invalid_request` code.
    InvalidDeadline,
    /// Spawning the child failed. Maps to `launch_failed`.
    Launch(std::io::Error),
}

/// Handle to a running streamed command. Dropping it stops the command, so a
/// forgotten job never outlives its owner.
pub(crate) struct CommandStream {
    events: mpsc::Receiver<StreamEvent>,
    stop: Arc<AtomicBool>,
}

impl CommandStream {
    /// The event receiver; iterate until `Exit` (the channel then closes).
    pub(crate) fn events(&self) -> &mpsc::Receiver<StreamEvent> {
        &self.events
    }

    /// Ask the supervisor to terminate the process group (`SIGTERM`, then
    /// `SIGKILL` after the grace). Idempotent and non-blocking; the final
    /// status is `Stopped` unless the child already ended on its own.
    pub(crate) fn stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
    }
}

impl Drop for CommandStream {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Shared output state: serializes both readers and the final event so
/// `Exit` is last and the retained cap is exact.
struct Emitter {
    sender: mpsc::Sender<StreamEvent>,
    retained: usize,
    truncated: bool,
    closed: bool,
    cap: usize,
}

impl Emitter {
    fn send(&self, event: StreamEvent) {
        // A dropped receiver means nobody follows the job any more; the
        // handle's Drop already requested the stop.
        let _ = self.sender.send(event);
    }

    fn output(&mut self, stream: StreamName, text: &str) {
        let mut rest = text;
        while !rest.is_empty() && !self.closed {
            let available = self.cap.saturating_sub(self.retained);
            if available == 0 {
                self.mark_truncated();
                return;
            }
            let take = floor_boundary(rest, available.min(MAX_OUTPUT_CHUNK_BYTES));
            if take == 0 {
                // The cap leaves less room than one character.
                self.mark_truncated();
                return;
            }
            self.retained += take;
            self.send(StreamEvent::Output {
                stream,
                text: rest[..take].to_string(),
            });
            rest = &rest[take..];
        }
    }

    fn mark_truncated(&mut self) {
        if !self.truncated {
            self.truncated = true;
            self.send(StreamEvent::OutputTruncated {
                retained_bytes: self.retained.min(self.cap),
            });
        }
    }

    fn finish(&mut self, status: ExitStatusKind) {
        if !self.closed {
            self.closed = true;
            self.send(StreamEvent::Exit { status });
        }
    }
}

/// Largest index `<= max` on a char boundary of `text`.
fn floor_boundary(text: &str, max: usize) -> usize {
    let mut index = max.min(text.len());
    while !text.is_char_boundary(index) {
        index -= 1;
    }
    index
}

/// Start `command` and stream its output. Uses the default retained cap.
///
/// `command` must already be confined (sandbox launcher argv, fixed
/// environment, working directory). `secrets` are credential values removed
/// from every chunk, including ones split across reads.
///
/// # Errors
/// [`StreamError::InvalidDeadline`] or [`StreamError::Launch`].
pub(crate) fn spawn_streaming(
    command: Command,
    deadline: Duration,
    secrets: &[String],
) -> Result<CommandStream, StreamError> {
    spawn_streaming_capped(command, deadline, secrets, MAX_RETAINED_OUTPUT_BYTES)
}

/// [`spawn_streaming`] with an explicit retained-output cap (tests, callers
/// with a lower policy).
///
/// # Errors
/// As [`spawn_streaming`].
pub(crate) fn spawn_streaming_capped(
    mut command: Command,
    deadline: Duration,
    secrets: &[String],
    retained_cap: usize,
) -> Result<CommandStream, StreamError> {
    use std::os::unix::process::CommandExt;
    if deadline < MIN_DEADLINE || deadline > MAX_DEADLINE {
        return Err(StreamError::InvalidDeadline);
    }
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0);
    let started = Instant::now();
    let mut child = command.spawn().map_err(StreamError::Launch)?;
    let group = rustix::process::Pid::from_child(&child);
    let (sender, events) = mpsc::channel();
    let emitter = Arc::new(Mutex::new(Emitter {
        sender,
        retained: 0,
        truncated: false,
        closed: false,
        cap: retained_cap,
    }));
    let secrets: Arc<Vec<String>> =
        Arc::new(secrets.iter().filter(|s| !s.is_empty()).cloned().collect());
    let (done_tx, done_rx) = mpsc::channel::<()>();
    let mut readers = 0;
    if let Some(pipe) = child.stdout.take() {
        spawn_reader(pipe, StreamName::Stdout, &emitter, &secrets, &done_tx);
        readers += 1;
    }
    if let Some(pipe) = child.stderr.take() {
        spawn_reader(pipe, StreamName::Stderr, &emitter, &secrets, &done_tx);
        readers += 1;
    }
    drop(done_tx);
    let stop = Arc::new(AtomicBool::new(false));
    let stop_flag = Arc::clone(&stop);
    std::thread::spawn(move || {
        let status = supervise(&mut child, group, &stop_flag, started + deadline);
        // Reap descendants left in the group so the pipes close.
        signal_group(group, rustix::process::Signal::KILL);
        let grace = Instant::now() + READER_GRACE;
        for _ in 0..readers {
            let left = grace.saturating_duration_since(Instant::now());
            // A descendant outside the group may hold a pipe; stop waiting.
            if done_rx.recv_timeout(left).is_err() {
                break;
            }
        }
        lock(&emitter).finish(status);
    });
    Ok(CommandStream { events, stop })
}

fn lock(emitter: &Mutex<Emitter>) -> std::sync::MutexGuard<'_, Emitter> {
    emitter.lock().unwrap_or_else(PoisonError::into_inner)
}

/// Wait for exit, stop or deadline; terminate the group when asked.
fn supervise(
    child: &mut std::process::Child,
    group: rustix::process::Pid,
    stop: &AtomicBool,
    deadline: Instant,
) -> ExitStatusKind {
    let mut requested: Option<ExitStatusKind> = None;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return requested.unwrap_or_else(|| classify(status)),
            Ok(None) => {}
            // The child cannot be waited on; nothing more can be learned.
            Err(_) => return requested.unwrap_or(ExitStatusKind::Failed { code: None }),
        }
        if requested.is_none() {
            if stop.load(Ordering::SeqCst) {
                requested = Some(ExitStatusKind::Stopped);
            } else if Instant::now() >= deadline {
                requested = Some(ExitStatusKind::TimedOut);
            }
            if requested.is_some() {
                terminate(child, group);
                continue;
            }
        }
        std::thread::sleep(POLL_INTERVAL);
    }
}

/// `SIGTERM` the group, wait [`TERM_GRACE`], then `SIGKILL` and reap.
fn terminate(child: &mut std::process::Child, group: rustix::process::Pid) {
    signal_group(group, rustix::process::Signal::TERM);
    let limit = Instant::now() + TERM_GRACE;
    while Instant::now() < limit {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        std::thread::sleep(POLL_INTERVAL);
    }
    signal_group(group, rustix::process::Signal::KILL);
    // Reaped by the supervise loop's next try_wait.
}

fn classify(status: ExitStatus) -> ExitStatusKind {
    match status.code() {
        Some(0) => ExitStatusKind::Succeeded,
        code => ExitStatusKind::Failed { code },
    }
}

fn spawn_reader(
    mut pipe: impl Read + Send + 'static,
    stream: StreamName,
    emitter: &Arc<Mutex<Emitter>>,
    secrets: &Arc<Vec<String>>,
    done: &mpsc::Sender<()>,
) {
    let emitter = Arc::clone(emitter);
    let secrets = Arc::clone(secrets);
    let done = done.clone();
    std::thread::spawn(move || {
        let mut collector = Collector::new(&secrets);
        let mut buffer = [0u8; READ_SIZE];
        loop {
            match pipe.read(&mut buffer) {
                Ok(0) => break,
                Ok(read) => {
                    let text = collector.push(&buffer[..read]);
                    lock(&emitter).output(stream, &text);
                }
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => {}
                // A read error ends the stream; what was read stands.
                Err(_) => break,
            }
        }
        let rest = collector.finish();
        lock(&emitter).output(stream, &rest);
        // The supervisor may have stopped waiting after its grace period.
        let _ = done.send(());
    });
}

/// Per-stream decoder: bytes to sanitized, redacted text, holding back an
/// incomplete UTF-8 tail and a possible secret prefix between reads.
pub(crate) struct Collector<'a> {
    secrets: &'a [String],
    /// Longest secret in bytes; `max - 1` bytes of tail are held back.
    max_secret: usize,
    /// Undecoded bytes of a split multi-byte character.
    pending: Vec<u8>,
    /// Sanitized text held back because it may start a secret.
    carry: String,
}

impl<'a> Collector<'a> {
    /// New collector redacting `secrets` (empty values must be filtered).
    pub(crate) fn new(secrets: &'a [String]) -> Self {
        Self {
            secrets,
            max_secret: secrets.iter().map(String::len).max().unwrap_or(0),
            pending: Vec::new(),
            carry: String::new(),
        }
    }

    /// Feed raw bytes; returns text now safe to emit.
    pub(crate) fn push(&mut self, bytes: &[u8]) -> String {
        self.pending.extend_from_slice(bytes);
        let decoded = decode_complete(&mut self.pending);
        self.process(&decoded, false)
    }

    /// End of stream: flush the held-back tail (invalid bytes become U+FFFD).
    pub(crate) fn finish(&mut self) -> String {
        let rest = String::from_utf8_lossy(&std::mem::take(&mut self.pending)).into_owned();
        self.process(&rest, true)
    }

    fn process(&mut self, decoded: &str, flush: bool) -> String {
        let combined = format!("{}{}", self.carry, decoded);
        let sanitized = clean_terminal_text(&combined);
        let mut boundary = if flush {
            sanitized.len()
        } else {
            floor_boundary(&sanitized, sanitized.len().saturating_sub(self.max_secret.saturating_sub(1)))
        };
        // Never cut through a secret occurrence that straddles the boundary.
        loop {
            let mut moved = false;
            for secret in self.secrets {
                for (at, _) in sanitized.match_indices(secret.as_str()) {
                    if at < boundary && at + secret.len() > boundary {
                        boundary = at;
                        moved = true;
                    }
                }
            }
            if !moved {
                break;
            }
        }
        self.carry = sanitized[boundary..].to_string();
        redact(&sanitized[..boundary], self.secrets)
    }
}

/// Replace every secret occurrence with [`REDACTION_MARKER`].
fn redact(text: &str, secrets: &[String]) -> String {
    let mut out = text.to_string();
    for secret in secrets {
        out = out.replace(secret.as_str(), REDACTION_MARKER);
    }
    out
}

/// Decode the longest valid prefix of `pending`, replacing invalid sequences
/// with U+FFFD and leaving an incomplete trailing character in `pending`.
fn decode_complete(pending: &mut Vec<u8>) -> String {
    let mut out = String::new();
    let mut offset = 0;
    loop {
        match std::str::from_utf8(&pending[offset..]) {
            Ok(valid) => {
                out.push_str(valid);
                offset = pending.len();
                break;
            }
            Err(error) => {
                let good = offset + error.valid_up_to();
                // The prefix up to `valid_up_to` is valid UTF-8 by contract.
                out.push_str(&String::from_utf8_lossy(&pending[offset..good]));
                match error.error_len() {
                    Some(bad) => {
                        out.push('\u{fffd}');
                        offset = good + bad;
                    }
                    None => {
                        offset = good;
                        break;
                    }
                }
            }
        }
    }
    pending.drain(..offset);
    out
}

#[cfg(test)]
#[path = "command_stream_tests.rs"]
mod tests;
