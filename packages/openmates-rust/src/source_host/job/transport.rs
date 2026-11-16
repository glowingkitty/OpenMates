//! Admission and request/response matching for the source-side
//! `remote_command_*` frames.
//!
//! The generic source-host frame filter (`receive_source_host`) already passes
//! any frame kind other than a bare `error`, and `remote_command_error` is its
//! own kind, so admission here is a second, family-local gate: only the nine
//! server frames of the job protocol are admitted, each validated against the
//! wire contract, and every other kind (including `project_remote_access_*`)
//! is left to the existing handlers untouched.
//!
//! [`JobTransport`] is poll-driven so a driver can interleave job IO in the
//! sequential serve loop: requests are queued in an outbox the driver drains
//! and sends, server frames are fed to [`JobTransport::accept`] each loop
//! iteration, and [`JobTransport::expire`] fails requests after 20 s. Time is
//! an injected monotonic millisecond clock.
//! spec: specifications/features/app-skills/code-run code-run.remote.*

use super::wire::{
    CommandSummary, RemoteCommandErrorCode, WireError, validate_jobs, validate_summary,
};
use serde_json::Value;
use std::collections::VecDeque;

/// Response timeout of one request, in milliseconds (`RESPONSE_TIMEOUT_MS`).
pub(crate) const REQUEST_TIMEOUT_MS: u64 = 20_000;
/// Most requests held at once (one per execution plus discovery).
pub(crate) const MAX_PENDING_REQUESTS: usize = 256;

/// A server frame of the job protocol that passed admission.
#[derive(Clone, Debug, PartialEq)]
pub(crate) enum ServerFrame {
    /// `remote_command_available`: a job waits for an executor.
    Available(CommandSummary),
    /// `remote_command_jobs`: reply to discover.
    Jobs(Vec<CommandSummary>),
    /// `remote_command_request`: reply to claim; validate with
    /// `wire::validate_claimed_request` (needs the binding).
    Request {
        /// Execution the reply belongs to.
        execution_id: String,
        /// Raw payload.
        payload: Value,
    },
    /// `remote_command_recovered`: reply to recover; validate with
    /// `wire::validate_lease_response`.
    Recovered {
        /// Execution the reply belongs to.
        execution_id: String,
        /// Raw payload.
        payload: Value,
    },
    /// `remote_command_event_ack`.
    EventAck(CommandSummary),
    /// `remote_command_source_completion_ack`.
    CompletionAck(CommandSummary),
    /// `remote_command_authority`; validate with
    /// `wire::validate_authority_reply`.
    Authority {
        /// Execution the reply belongs to.
        execution_id: String,
        /// Raw payload.
        payload: Value,
    },
    /// `remote_command_stop_requested`: the origin asked to stop.
    StopRequested(CommandSummary),
    /// `remote_command_error` with the server's code.
    Error {
        /// Typed code (`Other` for codes outside the known set).
        code: RemoteCommandErrorCode,
        /// Verbatim server code.
        raw_code: String,
        /// Execution named by the frame, when any.
        execution_id: Option<String>,
    },
}

impl ServerFrame {
    /// Response type the frame matches and the execution id it names
    /// (`""` for the per-binding jobs reply).
    fn routing(&self) -> (&'static str, &str) {
        match self {
            Self::Available(s) => ("remote_command_available", &s.execution_id),
            Self::Jobs(_) => ("remote_command_jobs", ""),
            Self::Request { execution_id, .. } => ("remote_command_request", execution_id),
            Self::Recovered { execution_id, .. } => ("remote_command_recovered", execution_id),
            Self::EventAck(s) => ("remote_command_event_ack", &s.execution_id),
            Self::CompletionAck(s) => ("remote_command_source_completion_ack", &s.execution_id),
            Self::Authority { execution_id, .. } => ("remote_command_authority", execution_id),
            Self::StopRequested(s) => ("remote_command_stop_requested", &s.execution_id),
            Self::Error { execution_id, .. } => (
                "remote_command_error",
                execution_id.as_deref().unwrap_or(""),
            ),
        }
    }
}

/// Whether `kind` belongs to the job protocol's server-to-source frames.
pub(crate) fn is_server_frame(kind: &str) -> bool {
    matches!(
        kind,
        "remote_command_available"
            | "remote_command_jobs"
            | "remote_command_request"
            | "remote_command_recovered"
            | "remote_command_event_ack"
            | "remote_command_source_completion_ack"
            | "remote_command_authority"
            | "remote_command_stop_requested"
            | "remote_command_error"
    )
}

/// Response type a source request waits for, `None` for a kind that is not a
/// source request.
pub(crate) fn response_type_for(request_kind: &str) -> Option<&'static str> {
    Some(match request_kind {
        "remote_command_discover" => "remote_command_jobs",
        "remote_command_claim" => "remote_command_request",
        "remote_command_recover" => "remote_command_recovered",
        "remote_command_event" => "remote_command_event_ack",
        "remote_command_source_completion" => "remote_command_source_completion_ack",
        "remote_command_revalidate" => "remote_command_authority",
        _ => return None,
    })
}

fn payload_execution_id(payload: &Value, rule: &'static str) -> Result<String, WireError> {
    let id = payload.get("execution_id").and_then(Value::as_str);
    match id {
        Some(id) if super::wire::is_identifier(id) => Ok(id.to_owned()),
        _ => Err(WireError::Invalid(rule)),
    }
}

/// Admit one inbound frame.
///
/// Returns `Ok(None)` for a kind outside the job protocol so the caller keeps
/// handling it as before; the existing filter is not widened for them.
///
/// # Errors
/// `WireError::Invalid` when an admitted kind violates its contract.
pub(crate) fn admit(kind: &str, payload: &Value) -> Result<Option<ServerFrame>, WireError> {
    if !is_server_frame(kind) {
        return Ok(None);
    }
    Ok(Some(match kind {
        "remote_command_available" => ServerFrame::Available(validate_summary(payload)?),
        "remote_command_jobs" => ServerFrame::Jobs(validate_jobs(payload)?),
        "remote_command_request" => ServerFrame::Request {
            execution_id: payload_execution_id(payload, "request execution_id")?,
            payload: payload.clone(),
        },
        "remote_command_recovered" => ServerFrame::Recovered {
            execution_id: payload_execution_id(payload, "recovery execution_id")?,
            payload: payload.clone(),
        },
        "remote_command_event_ack" => ServerFrame::EventAck(validate_summary(payload)?),
        "remote_command_source_completion_ack" => {
            ServerFrame::CompletionAck(validate_summary(payload)?)
        }
        "remote_command_authority" => ServerFrame::Authority {
            execution_id: payload_execution_id(payload, "authority execution_id")?,
            payload: payload.clone(),
        },
        "remote_command_stop_requested" => ServerFrame::StopRequested(validate_summary(payload)?),
        _ => {
            let raw_code = payload
                .get("code")
                .and_then(Value::as_str)
                .ok_or(WireError::Invalid("error code"))?;
            if raw_code.is_empty() || raw_code.len() > 128 {
                return Err(WireError::Invalid("error code"));
            }
            let execution_id = match payload.get("execution_id") {
                None | Some(Value::Null) => None,
                Some(Value::String(id)) if super::wire::is_identifier(id) => Some(id.clone()),
                Some(_) => return Err(WireError::Invalid("error execution_id")),
            };
            ServerFrame::Error {
                code: RemoteCommandErrorCode::from_wire(raw_code),
                raw_code: raw_code.to_owned(),
                execution_id,
            }
        }
    }))
}

/// Why a request produced no response frame.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum RequestFailure {
    /// No matching response within [`REQUEST_TIMEOUT_MS`].
    Timeout,
    /// The server answered with `remote_command_error`.
    Server {
        /// Typed code.
        code: RemoteCommandErrorCode,
        /// Verbatim server code.
        raw_code: String,
    },
}

/// Finished request: the matching response frame or the failure.
pub(crate) type RequestOutcome = Result<ServerFrame, RequestFailure>;

/// Handle of a submitted request.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct RequestId(u64);

/// Refusal to queue a request.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum SubmitError {
    /// `kind` is not a source request.
    UnknownKind,
    /// A request of the same response type for the same execution is open.
    Busy,
    /// Too many open requests.
    Full,
}

struct Pending {
    id: RequestId,
    response_type: &'static str,
    execution_id: String,
    deadline_ms: u64,
}

/// Outbox plus pending-request table of the job protocol.
#[derive(Default)]
pub(crate) struct JobTransport {
    next_id: u64,
    pending: Vec<Pending>,
    outbox: VecDeque<(&'static str, Value)>,
    finished: Vec<(RequestId, RequestOutcome)>,
    unsolicited: VecDeque<ServerFrame>,
}

impl JobTransport {
    /// Empty transport.
    pub(crate) fn new() -> Self {
        Self::default()
    }

    /// Queue `payload` as a `kind` frame and wait for its response. One open
    /// request per (response type, execution) like the TS client.
    ///
    /// # Errors
    /// See [`SubmitError`].
    pub(crate) fn submit(
        &mut self,
        kind: &'static str,
        payload: Value,
        execution_id: &str,
        now_ms: u64,
    ) -> Result<RequestId, SubmitError> {
        let response_type = response_type_for(kind).ok_or(SubmitError::UnknownKind)?;
        if self.pending.len() >= MAX_PENDING_REQUESTS {
            return Err(SubmitError::Full);
        }
        if self
            .pending
            .iter()
            .any(|p| p.response_type == response_type && p.execution_id == execution_id)
        {
            return Err(SubmitError::Busy);
        }
        self.next_id += 1;
        let id = RequestId(self.next_id);
        self.pending.push(Pending {
            id,
            response_type,
            execution_id: execution_id.to_owned(),
            deadline_ms: now_ms.saturating_add(REQUEST_TIMEOUT_MS),
        });
        self.outbox.push_back((kind, payload));
        Ok(id)
    }

    /// Frames the driver must send now, in order.
    pub(crate) fn take_outbox(&mut self) -> Vec<(&'static str, Value)> {
        self.outbox.drain(..).collect()
    }

    /// Route an admitted frame: a matching pending request is completed, an
    /// error with a matching execution fails it, anything else is kept as
    /// unsolicited for [`Self::take_unsolicited`].
    pub(crate) fn accept(&mut self, frame: ServerFrame) {
        let (response_type, execution_id) = frame.routing();
        let position = if let ServerFrame::Error {
            execution_id: e, ..
        } = &frame
        {
            let wanted = e.as_deref().unwrap_or("");
            self.pending.iter().position(|p| p.execution_id == wanted)
        } else {
            self.pending
                .iter()
                .position(|p| p.response_type == response_type && p.execution_id == execution_id)
        };
        let Some(position) = position else {
            self.unsolicited.push_back(frame);
            return;
        };
        let pending = self.pending.remove(position);
        let outcome = match frame {
            ServerFrame::Error { code, raw_code, .. } => {
                Err(RequestFailure::Server { code, raw_code })
            }
            other => Ok(other),
        };
        self.finished.push((pending.id, outcome));
    }

    /// Fail every request whose deadline passed.
    pub(crate) fn expire(&mut self, now_ms: u64) {
        let (expired, open): (Vec<_>, Vec<_>) = std::mem::take(&mut self.pending)
            .into_iter()
            .partition(|p| p.deadline_ms <= now_ms);
        self.pending = open;
        for p in expired {
            self.finished.push((p.id, Err(RequestFailure::Timeout)));
        }
    }

    /// Outcome of `id` once finished (consumed), else `None`.
    pub(crate) fn take_outcome(&mut self, id: RequestId) -> Option<RequestOutcome> {
        let at = self.finished.iter().position(|(i, _)| *i == id)?;
        Some(self.finished.remove(at).1)
    }

    /// Frames that matched no request (`available`, `stop_requested`, stray
    /// acks), oldest first.
    pub(crate) fn take_unsolicited(&mut self) -> Vec<ServerFrame> {
        self.unsolicited.drain(..).collect()
    }

    /// Number of requests still waiting.
    pub(crate) fn pending_len(&self) -> usize {
        self.pending.len()
    }

    /// Fail every open request (socket lost); the driver rediscovers.
    pub(crate) fn fail_all(&mut self) {
        for p in std::mem::take(&mut self.pending) {
            self.finished.push((p.id, Err(RequestFailure::Timeout)));
        }
        self.outbox.clear();
    }
}
