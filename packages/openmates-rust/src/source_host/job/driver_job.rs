//! Per-job state of the remote-command driver: the step machine, the event
//! queue and the process handle, with the stop/fail/stream-drain transitions.
//! Split out of `driver.rs`, which owns the protocol exchange around it.
//! spec: specifications/features/app-skills/code-run code-run.remote.*

use super::events::{ExecutionEvents, Stream};
use super::launch::JobProcess;
use super::portable::PortableRequest;
use super::transport::RequestId;
use super::wire::{Approval, EventStatus, RemoteCommandErrorCode};
use crate::source_host::command_stream::{ExitStatusKind, StreamEvent, StreamName};
use serde_json::json;
use std::sync::mpsc::TryRecvError;

/// Stream events drained per job and tick, so one noisy job cannot starve IO.
const EVENTS_PER_TICK: usize = 64;

/// Where a job is in its lifecycle.
pub(super) enum Step {
    /// Waiting for revalidate round `round` (1 or 2); `id` is `None` until sent.
    Revalidating { round: u8, id: Option<RequestId> },
    /// Process running (or finishing); events flow.
    Running,
    /// Waiting for a recover reply.
    Recovering(RequestId),
    /// Terminal event queued; waiting for its acknowledgement.
    Ending,
}

/// Everything the driver tracks for one claimed execution.
pub(super) struct Job {
    pub(super) source: usize,
    pub(super) execution_id: String,
    pub(super) events: ExecutionEvents,
    pub(super) step: Step,
    pub(super) process: Option<JobProcess>,
    pub(super) request: Option<PortableRequest>,
    pub(super) outer_digest: String,
    pub(super) approval: Approval,
    pub(super) stopped: bool,
    pub(super) runtime_sequence: u64,
    pub(super) inflight: Option<(RequestId, i64)>,
    pub(super) lease_expires_at: i64,
}

impl Job {
    /// Mark stopped: terminate a running process (its exit becomes the
    /// terminal `stopped` event) or end an unlaunched job right away.
    pub(super) fn stop(&mut self) {
        self.stopped = true;
        if let Some(process) = &self.process {
            process.stream.stop();
        } else if !self.events.terminal_queued() {
            self.events.push_terminal(
                EventStatus::Stopped,
                json!({"execution_id": self.execution_id, "status": "stopped", "stop_requested": true}),
                false,
            );
            self.step = Step::Ending;
        }
    }

    /// Report a refusal or failure as the terminal `failed` event.
    pub(super) fn fail(&mut self, code: RemoteCommandErrorCode, message: &str) {
        self.process = None;
        self.events.push_terminal(
            EventStatus::Failed,
            json!({
                "execution_id": self.execution_id,
                "status": "failed",
                "error_code": code.as_str(),
                "error_message": message,
            }),
            false,
        );
        self.step = Step::Ending;
    }

    /// Move stream events of a running process into the event queue.
    pub(super) fn drain_process(&mut self) {
        for _ in 0..EVENTS_PER_TICK {
            let Some(process) = &self.process else { return };
            let event = match process.stream.events().try_recv() {
                Ok(event) => event,
                Err(TryRecvError::Empty) => return,
                // A closed channel without Exit means the supervisor died.
                Err(TryRecvError::Disconnected) => {
                    self.fail(
                        RemoteCommandErrorCode::LaunchFailed,
                        "Command supervisor ended unexpectedly",
                    );
                    return;
                }
            };
            match event {
                StreamEvent::Output { stream, text } => {
                    let stream = match stream {
                        StreamName::Stdout => Stream::Stdout,
                        StreamName::Stderr => Stream::Stderr,
                    };
                    self.events.push_output(
                        self.runtime_sequence,
                        stream,
                        &text,
                        EventStatus::Running,
                    );
                    self.runtime_sequence += 1;
                }
                StreamEvent::OutputTruncated { retained_bytes } => {
                    self.events
                        .push_truncated(retained_bytes as u64, EventStatus::Running);
                }
                StreamEvent::Exit { status } => {
                    let (status, code) = match status {
                        ExitStatusKind::Succeeded => (EventStatus::Succeeded, Some(0)),
                        ExitStatusKind::Failed { code } => (EventStatus::Failed, code),
                        ExitStatusKind::TimedOut => (EventStatus::TimedOut, None),
                        ExitStatusKind::Stopped => (EventStatus::Stopped, None),
                    };
                    self.events.push_terminal(
                        status,
                        json!({"execution_id": self.execution_id, "status": status.as_str(), "exit_code": code}),
                        false,
                    );
                    self.process = None;
                    self.step = Step::Ending;
                    return;
                }
            }
        }
    }
}
