//! Per-execution event queue of a remote-command job: strict sequence
//! numbering, lease bookkeeping, AES-GCM sealing and the model-text excerpt.
//!
//! Port of the event half of `remoteCommandSource.ts` (`#enqueue`, `#flush`,
//! `#appendModelText`, `completionModelText`). Events are sealed with the
//! project key in the combined AES-GCM format of `crypto::encrypt_combined`,
//! which the origin (`client/remote_command_jobs.rs`) opens with
//! `crypto::decrypt_combined`. The queue does no IO: the driver sends the
//! frame from [`ExecutionEvents::next_frame`] and reports the ack or failure.
//! spec: specifications/features/app-skills/code-run code-run.remote.*

use super::wire::{
    EventKind, EventStatus, LeaseIdentity, MAX_MODEL_TEXT_BYTES, Truncation, WireError,
    completion_payload, event_payload, event_plaintext,
};
use crate::crypto;
use serde_json::{Value, json};
use std::collections::VecDeque;

/// Heartbeat period of a running job without events, in milliseconds.
pub(crate) const HEARTBEAT_MS: u64 = 30_000;
const INCOMPLETE_MARKER: &str = "[OpenMates output excerpt is incomplete]\n";

/// Output stream of a chunk.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Stream {
    /// Standard output.
    Stdout,
    /// Standard error.
    Stderr,
}

impl Stream {
    fn as_str(self) -> &'static str {
        match self {
            Self::Stdout => "stdout",
            Self::Stderr => "stderr",
        }
    }
}

/// Failure while preparing an event frame.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum EventError {
    /// The wire contract rejected the event.
    Wire(WireError),
    /// Sealing the event failed.
    Seal,
    /// The server acknowledged a lower sequence than was sent.
    NotAcknowledged,
}

impl From<WireError> for EventError {
    fn from(error: WireError) -> Self {
        Self::Wire(error)
    }
}

struct PendingEvent {
    kind: EventKind,
    status: EventStatus,
    payload: Value,
    assigned_sequence: Option<i64>,
    encrypted: Option<String>,
}

/// A frame ready to send plus what its ack must look like.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct OutboundEvent {
    /// `remote_command_event` or `remote_command_source_completion`.
    pub(crate) frame: &'static str,
    /// Response type to wait for.
    pub(crate) ack: &'static str,
    /// Payload of the frame.
    pub(crate) payload: Value,
    /// Sequence the ack must reach.
    pub(crate) sequence: i64,
}

/// Event state of one execution.
pub(crate) struct ExecutionEvents {
    execution_id: String,
    next_sequence: i64,
    pending: VecDeque<PendingEvent>,
    lease: Option<LeaseIdentity>,
    model_text: String,
    source_excerpt_truncated: bool,
    upstream_truncated: bool,
    last_output_sequence: Option<u64>,
    last_sent_ms: u64,
    terminal_queued: bool,
    completed: bool,
}

impl ExecutionEvents {
    /// New queue; the first event gets `last_sequence + 1`.
    pub(crate) fn new(execution_id: &str, last_sequence: i64, now_ms: u64) -> Self {
        Self {
            execution_id: execution_id.to_owned(),
            next_sequence: last_sequence + 1,
            pending: VecDeque::new(),
            lease: None,
            model_text: String::new(),
            source_excerpt_truncated: false,
            upstream_truncated: false,
            last_output_sequence: None,
            last_sent_ms: now_ms,
            terminal_queued: false,
            completed: false,
        }
    }

    /// Current lease, if held.
    pub(crate) fn lease(&self) -> Option<&LeaseIdentity> {
        self.lease.as_ref()
    }

    /// Whether the terminal event was acknowledged.
    pub(crate) fn is_completed(&self) -> bool {
        self.completed
    }

    /// Whether a terminal event was queued (acknowledged or not).
    pub(crate) fn terminal_queued(&self) -> bool {
        self.terminal_queued
    }

    /// Number of events not yet acknowledged.
    pub(crate) fn pending_len(&self) -> usize {
        self.pending.len()
    }

    /// Apply a (new or renewed) lease: drop events the server already has,
    /// renumber the rest from `last_sequence + 1` (their cached ciphertext
    /// embeds the old number) and reset the sequence cursor.
    pub(crate) fn apply_lease(&mut self, lease: LeaseIdentity, last_sequence: i64) {
        while self
            .pending
            .front()
            .and_then(|e| e.assigned_sequence)
            .is_some_and(|s| s <= last_sequence)
        {
            self.pending.pop_front();
        }
        for event in &mut self.pending {
            event.assigned_sequence = None;
            event.encrypted = None;
        }
        self.next_sequence = last_sequence + 1;
        self.lease = Some(lease);
    }

    /// Drop the lease (flush failed or it expired); the driver rediscovers.
    pub(crate) fn clear_lease(&mut self) {
        self.lease = None;
    }

    fn enqueue(&mut self, kind: EventKind, status: EventStatus, payload: Value) {
        if self.terminal_queued {
            return;
        }
        self.terminal_queued = kind == EventKind::Terminal;
        self.pending.push_back(PendingEvent {
            kind,
            status,
            payload,
            assigned_sequence: None,
            encrypted: None,
        });
    }

    /// Queue a non-terminal status event (`job` is the runtime job summary).
    pub(crate) fn push_status(&mut self, status: EventStatus, job: Value) {
        self.enqueue(EventKind::Status, status, json!({ "job": job }));
    }

    /// Queue the terminal event. `job_output_truncated` is the runtime's own
    /// flag, merged into `upstream_truncated` like the TS selection block.
    pub(crate) fn push_terminal(
        &mut self,
        status: EventStatus,
        job: Value,
        job_output_truncated: bool,
    ) {
        let selected = self.upstream_truncated || self.source_excerpt_truncated;
        let payload = json!({
            "job": job,
            "output_selection": {
                "coverage": if selected { "selected_excerpt" } else { "full" },
                "upstream_truncated": self.upstream_truncated || job_output_truncated,
                "source_excerpt_truncated": self.source_excerpt_truncated,
            },
        });
        self.enqueue(EventKind::Terminal, status, payload);
    }

    /// Queue an output chunk. `runtime_sequence` is the runtime's own chunk
    /// counter; a gap marks the output as upstream-truncated.
    pub(crate) fn push_output(
        &mut self,
        runtime_sequence: u64,
        stream: Stream,
        text: &str,
        status: EventStatus,
    ) {
        // The terminal event already carries the final model text; output that
        // races in after it must not change what the completion reports.
        if self.terminal_queued {
            return;
        }
        if self
            .last_output_sequence
            .is_some_and(|last| runtime_sequence != last + 1)
        {
            self.upstream_truncated = true;
        }
        self.last_output_sequence = Some(runtime_sequence);
        self.append_model_text(stream, text);
        self.enqueue(
            EventKind::Output,
            status,
            json!({"stream": stream.as_str(), "text": text, "trusted": false}),
        );
    }

    /// Queue an `output_truncated` event (runtime hit its retained cap).
    pub(crate) fn push_truncated(&mut self, retained_bytes: u64, status: EventStatus) {
        if self.terminal_queued {
            return;
        }
        self.upstream_truncated = true;
        self.enqueue(
            EventKind::OutputTruncated,
            status,
            json!({ "retained_bytes": retained_bytes }),
        );
    }

    fn append_model_text(&mut self, stream: Stream, value: &str) {
        let prefix = if !self.model_text.is_empty() && !self.model_text.ends_with('\n') {
            "\n"
        } else {
            ""
        };
        let candidate = format!("{prefix}[{}] {value}", stream.as_str());
        let available = MAX_MODEL_TEXT_BYTES.saturating_sub(self.model_text.len());
        if available == 0 {
            self.source_excerpt_truncated = true;
            return;
        }
        let bounded = truncate_utf8(&candidate, available);
        if bounded.len() < candidate.len() {
            self.source_excerpt_truncated = true;
        }
        self.model_text.push_str(bounded);
    }

    /// `model_text` of the completion: incomplete marker plus the excerpt,
    /// or `Command <status>.` when nothing was captured.
    pub(crate) fn completion_model_text(&self, status: EventStatus) -> String {
        let incomplete = self.upstream_truncated || self.source_excerpt_truncated;
        let marker = if incomplete { INCOMPLETE_MARKER } else { "" };
        let fallback;
        let content = if self.model_text.is_empty() {
            fallback = format!("Command {}.", status.as_str());
            fallback.as_str()
        } else {
            self.model_text.as_str()
        };
        let room = MAX_MODEL_TEXT_BYTES - marker.len();
        format!("{marker}{}", truncate_utf8(content, room))
    }

    /// Build the next frame for the head event, sealing it with `key` (the
    /// sequence and ciphertext are cached so a retry resends identical bytes).
    /// `None` without a lease or pending event.
    ///
    /// # Errors
    /// [`EventError`] when the event violates the wire contract or sealing fails.
    pub(crate) fn next_frame(
        &mut self,
        key: &[u8; 32],
    ) -> Result<Option<OutboundEvent>, EventError> {
        let terminal_model = match self.pending.front() {
            Some(item) if item.kind == EventKind::Terminal => {
                Some(self.completion_model_text(item.status))
            }
            _ => None,
        };
        let (Some(lease), Some(item)) = (self.lease.as_ref(), self.pending.front_mut()) else {
            return Ok(None);
        };
        let sequence = *item.assigned_sequence.get_or_insert(self.next_sequence);
        if item.encrypted.is_none() {
            let plaintext = event_plaintext(
                &self.execution_id,
                sequence,
                item.kind,
                item.status,
                &item.payload,
            )?;
            item.encrypted =
                Some(crypto::encrypt_combined(&plaintext, key).map_err(|_| EventError::Seal)?);
        }
        let sealed = item.encrypted.as_deref().unwrap_or_default();
        let terminal = item.kind == EventKind::Terminal;
        let payload = if terminal {
            let model = terminal_model.unwrap_or_default();
            completion_payload(
                lease,
                sequence,
                item.status,
                sealed,
                &model,
                Truncation::default(),
            )?
        } else {
            event_payload(lease, sequence, item.kind, item.status, sealed)?
        };
        Ok(Some(OutboundEvent {
            frame: if terminal {
                "remote_command_source_completion"
            } else {
                "remote_command_event"
            },
            ack: if terminal {
                "remote_command_source_completion_ack"
            } else {
                "remote_command_event_ack"
            },
            payload,
            sequence,
        }))
    }

    /// Record the ack of the head event (`acked_last_sequence` from the ack
    /// summary). A terminal ack completes the execution and drops the lease.
    ///
    /// # Errors
    /// `NotAcknowledged` when the server's sequence is below the one sent.
    pub(crate) fn acknowledge(
        &mut self,
        acked_last_sequence: i64,
        now_ms: u64,
    ) -> Result<(), EventError> {
        let Some(item) = self.pending.front() else {
            return Ok(());
        };
        let sequence = item.assigned_sequence.unwrap_or(self.next_sequence);
        if acked_last_sequence < sequence {
            return Err(EventError::NotAcknowledged);
        }
        let terminal = item.kind == EventKind::Terminal;
        self.pending.pop_front();
        self.next_sequence = sequence + 1;
        self.last_sent_ms = now_ms;
        if terminal {
            self.lease = None;
            self.completed = true;
        }
        Ok(())
    }

    /// Whether a heartbeat `status running` event is due: live lease, nothing
    /// pending, no terminal queued, 30 s since the last send.
    pub(crate) fn heartbeat_due(&self, now_ms: u64) -> bool {
        self.lease.is_some()
            && self.pending.is_empty()
            && !self.terminal_queued
            && now_ms.saturating_sub(self.last_sent_ms) >= HEARTBEAT_MS
    }
}

/// Longest prefix of `value` within `maximum` bytes, cut at a char boundary.
fn truncate_utf8(value: &str, maximum: usize) -> &str {
    if value.len() <= maximum {
        return value;
    }
    let mut end = maximum;
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    &value[..end]
}
