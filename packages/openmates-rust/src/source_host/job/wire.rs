//! Strict validation and builders for the source-side `remote_command_*`
//! frames: job summary, claimed request, lease response, authority reply,
//! event and source-completion payloads, plus the error-code set.
//!
//! Mirrors `validateSummary`, `validateClaimedRequest`, `validateLeaseResponse`
//! and the payload literals in `remoteCommandSource.ts`; field limits follow
//! `backend/core/api/app/schemas/remote_command_schemas.py`.
//! spec: specifications/features/app-skills/code-run code-run.remote.*

use regex::Regex;
use serde_json::{Map, Value, json};
use std::sync::OnceLock;

/// Server lease length in seconds (`REMOTE_COMMAND_LEASE_SECONDS`).
pub(crate) const LEASE_SECONDS: i64 = 90;
/// Largest `encrypted_event` / `encrypted_request` ciphertext accepted.
pub(crate) const MAX_CIPHERTEXT_CHARS: usize = 1_048_576;
/// Largest `model_text` excerpt of a source completion, in bytes.
pub(crate) const MAX_MODEL_TEXT_BYTES: usize = 512 * 1024;
const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;

/// Refusal of a frame that violates the wire contract (names the rule).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum WireError {
    /// The frame violates the contract; the text names the field or rule.
    Invalid(&'static str),
    /// The server frame does not belong to the binding this host serves.
    BindingMismatch,
}

impl std::fmt::Display for WireError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Invalid(rule) => write!(f, "invalid remote command frame: {rule}"),
            Self::BindingMismatch => f.write_str("remote command server binding mismatch"),
        }
    }
}
impl std::error::Error for WireError {}

/// Error codes the host emits or receives (`remote_command_error.code` and
/// local `RemoteCommandError` codes). Unknown server codes stay `Other`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum RemoteCommandErrorCode {
    /// Request or policy is malformed.
    InvalidRequest,
    /// Another execution with this id already exists.
    DuplicateExecution,
    /// No valid approval for the command.
    ApprovalRequired,
    /// Approval does not match the request.
    InvalidApproval,
    /// Authority was revoked (digest/approval drift, stop).
    AuthorityRevoked,
    /// A requested resource profile has no local grant.
    ResourceNotGranted,
    /// Host coordination is required first.
    CoordinationRequired,
    /// Platform cannot run commands.
    UnsupportedPlatform,
    /// No sandbox is available to confine the command.
    ConfinementUnavailable,
    /// Requested network profile cannot be provided.
    NetworkProfileUnavailable,
    /// A granted credential cannot be read.
    CredentialUnavailable,
    /// The process failed to start.
    LaunchFailed,
    /// Another device holds the lease.
    ExecutionAlreadyClaimed,
    /// The execution already finished.
    ExecutionAlreadyTerminal,
    /// The lease lapsed; use `remote_command_recover`.
    CommandRecoveryRequired,
    /// Event sequence skipped ahead.
    EventSequenceGap,
    /// Event sequence is behind the server.
    EventSequenceStale,
    /// Lease token or generation is outdated.
    CommandLeaseStale,
    /// Any other server code (kept verbatim by the caller).
    Other,
}

impl RemoteCommandErrorCode {
    /// Parse a wire code; unknown codes map to `Other`.
    pub(crate) fn from_wire(code: &str) -> Self {
        match code {
            "invalid_request" => Self::InvalidRequest,
            "duplicate_execution" => Self::DuplicateExecution,
            "approval_required" => Self::ApprovalRequired,
            "invalid_approval" => Self::InvalidApproval,
            "authority_revoked" => Self::AuthorityRevoked,
            "resource_not_granted" => Self::ResourceNotGranted,
            "coordination_required" => Self::CoordinationRequired,
            "unsupported_platform" => Self::UnsupportedPlatform,
            "confinement_unavailable" => Self::ConfinementUnavailable,
            "network_profile_unavailable" => Self::NetworkProfileUnavailable,
            "credential_unavailable" => Self::CredentialUnavailable,
            "launch_failed" => Self::LaunchFailed,
            "execution_already_claimed" => Self::ExecutionAlreadyClaimed,
            "execution_already_terminal" => Self::ExecutionAlreadyTerminal,
            "command_recovery_required" => Self::CommandRecoveryRequired,
            "event_sequence_gap" => Self::EventSequenceGap,
            "event_sequence_stale" => Self::EventSequenceStale,
            "command_lease_stale" => Self::CommandLeaseStale,
            _ => Self::Other,
        }
    }

    /// Wire spelling of the code (`other` for `Other`, never sent).
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::InvalidRequest => "invalid_request",
            Self::DuplicateExecution => "duplicate_execution",
            Self::ApprovalRequired => "approval_required",
            Self::InvalidApproval => "invalid_approval",
            Self::AuthorityRevoked => "authority_revoked",
            Self::ResourceNotGranted => "resource_not_granted",
            Self::CoordinationRequired => "coordination_required",
            Self::UnsupportedPlatform => "unsupported_platform",
            Self::ConfinementUnavailable => "confinement_unavailable",
            Self::NetworkProfileUnavailable => "network_profile_unavailable",
            Self::CredentialUnavailable => "credential_unavailable",
            Self::LaunchFailed => "launch_failed",
            Self::ExecutionAlreadyClaimed => "execution_already_claimed",
            Self::ExecutionAlreadyTerminal => "execution_already_terminal",
            Self::CommandRecoveryRequired => "command_recovery_required",
            Self::EventSequenceGap => "event_sequence_gap",
            Self::EventSequenceStale => "event_sequence_stale",
            Self::CommandLeaseStale => "command_lease_stale",
            Self::Other => "other",
        }
    }
}

fn identifier_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
            .expect("static identifier regex is valid")
    })
}

/// Whether `value` matches the shared identifier grammar (`IDENTIFIER` in TS).
pub(crate) fn is_identifier(value: &str) -> bool {
    identifier_re().is_match(value)
}

pub(crate) fn record<'a>(
    value: &'a Value,
    rule: &'static str,
) -> Result<&'a Map<String, Value>, WireError> {
    value.as_object().ok_or(WireError::Invalid(rule))
}

/// Require exactly `keys` (no more, no fewer), like TS `exactKeys`.
pub(crate) fn exact_keys(map: &Map<String, Value>, keys: &[&str]) -> Result<(), WireError> {
    if map.len() != keys.len() || map.keys().any(|k| !keys.contains(&k.as_str())) {
        return Err(WireError::Invalid("unexpected fields"));
    }
    Ok(())
}

pub(crate) fn identifier(value: Option<&Value>, rule: &'static str) -> Result<String, WireError> {
    match value.and_then(Value::as_str) {
        Some(s) if is_identifier(s) => Ok(s.to_owned()),
        _ => Err(WireError::Invalid(rule)),
    }
}

/// Non-empty string without NUL, at most 1 MiB in UTF-16 units (TS `text`).
pub(crate) fn text(value: Option<&Value>, rule: &'static str) -> Result<String, WireError> {
    match value.and_then(Value::as_str) {
        Some(s)
            if !s.is_empty()
                && s.encode_utf16().count() <= MAX_CIPHERTEXT_CHARS
                && !s.contains('\0') =>
        {
            Ok(s.to_owned())
        }
        _ => Err(WireError::Invalid(rule)),
    }
}

/// Safe integer at least `minimum` (TS `integer`); floats are refused.
pub(crate) fn integer(
    value: Option<&Value>,
    minimum: i64,
    rule: &'static str,
) -> Result<i64, WireError> {
    match value.and_then(Value::as_i64) {
        Some(n) if (minimum..=MAX_SAFE_INTEGER).contains(&n) => Ok(n),
        _ => Err(WireError::Invalid(rule)),
    }
}

/// Like TS `item.x ?? default`: absent or null uses `default`.
fn integer_or(
    value: Option<&Value>,
    default: i64,
    minimum: i64,
    rule: &'static str,
) -> Result<i64, WireError> {
    match value {
        None | Some(Value::Null) => Ok(default),
        some => integer(some, minimum, rule),
    }
}

fn lease_token(value: Option<&Value>) -> Result<String, WireError> {
    // Server schema bounds the token to 16..=512 chars; reject early.
    let token = text(value, "lease_token")?;
    let len = token.chars().count();
    if !(16..=512).contains(&len) {
        return Err(WireError::Invalid("lease_token"));
    }
    Ok(token)
}

/// Public job summary (`remote_command_available`, `_jobs`, acks).
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct CommandSummary {
    /// Execution id.
    pub(crate) execution_id: String,
    /// Chat the command belongs to.
    pub(crate) chat_id: String,
    /// Project id.
    pub(crate) project_id: String,
    /// Source id.
    pub(crate) source_id: String,
    /// Server job state (e.g. `WAITING_FOR_EXECUTOR`).
    pub(crate) state: String,
    /// Last acknowledged event sequence (-1 when none).
    pub(crate) last_sequence: i64,
    /// Lease expiry, unix seconds (0 when no lease).
    pub(crate) lease_expires_at: i64,
}

/// Validate a public job summary.
///
/// # Errors
/// `WireError::Invalid` for a wrong protocol version, bad identifier, text or integer.
pub(crate) fn validate_summary(value: &Value) -> Result<CommandSummary, WireError> {
    let item = record(value, "summary")?;
    if item.get("protocol_version") != Some(&json!(1)) {
        return Err(WireError::Invalid("protocol_version"));
    }
    Ok(CommandSummary {
        execution_id: identifier(item.get("execution_id"), "execution_id")?,
        chat_id: identifier(item.get("chat_id"), "chat_id")?,
        project_id: identifier(item.get("project_id"), "project_id")?,
        source_id: identifier(item.get("source_id"), "source_id")?,
        state: text(item.get("state"), "state")?,
        last_sequence: integer_or(item.get("last_sequence"), -1, -1, "last_sequence")?,
        lease_expires_at: integer_or(item.get("lease_expires_at"), 0, 0, "lease_expires_at")?,
    })
}

/// Validate the `remote_command_jobs` reply `{jobs:[summary]}`.
///
/// # Errors
/// `WireError::Invalid` when `jobs` is not an array or a summary is invalid.
pub(crate) fn validate_jobs(value: &Value) -> Result<Vec<CommandSummary>, WireError> {
    let jobs = record(value, "jobs reply")?
        .get("jobs")
        .and_then(Value::as_array)
        .ok_or(WireError::Invalid("jobs"))?;
    jobs.iter().map(validate_summary).collect()
}

/// Approval choice carried by a request (`parseApproval`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Approval {
    /// Approved for this execution only.
    OneRun,
    /// Approved through a stored preset.
    Preset {
        /// Preset identifier.
        preset_id: String,
        /// 64-hex digest of the preset definition.
        definition_digest: String,
    },
}

/// Parse an approval object with exact keys.
///
/// # Errors
/// `WireError::Invalid` for unknown kinds, extra keys or a bad digest.
pub(crate) fn parse_approval(value: &Value) -> Result<Approval, WireError> {
    let approval = record(value, "approval")?;
    match approval.get("kind").and_then(Value::as_str) {
        Some("one_run") => {
            exact_keys(approval, &["kind"])?;
            Ok(Approval::OneRun)
        }
        Some("preset") => {
            exact_keys(approval, &["kind", "preset_id", "definition_digest"])?;
            let digest = approval.get("definition_digest").and_then(Value::as_str);
            match digest {
                Some(d) if d.len() == 64 && d.bytes().all(|b| b.is_ascii_hexdigit()) => {
                    Ok(Approval::Preset {
                        preset_id: identifier(approval.get("preset_id"), "preset_id")?,
                        definition_digest: d.to_owned(),
                    })
                }
                _ => Err(WireError::Invalid("preset approval")),
            }
        }
        _ => Err(WireError::Invalid("preset approval")),
    }
}

/// Binding a claimed request must match (the host's own Project binding).
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ClaimBinding {
    /// Project id of the binding.
    pub(crate) project_id: String,
    /// Source id of the binding.
    pub(crate) source_id: String,
    /// Team id when the binding is a team binding.
    pub(crate) team_id: Option<String>,
    /// Key epoch of the binding's Project key.
    pub(crate) key_epoch: i64,
}

/// Lease granted by claim, recover or revalidate.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct LeaseResponse {
    /// Opaque lease token (16..=512 chars).
    pub(crate) lease_token: String,
    /// Monotonic lease generation (>= 1).
    pub(crate) lease_generation: i64,
    /// Lease expiry, unix seconds.
    pub(crate) lease_expires_at: i64,
    /// Last acknowledged event sequence (-1 when none).
    pub(crate) last_sequence: i64,
    /// Whether the host may launch the process now.
    pub(crate) launch_allowed: bool,
    /// Whether the origin asked to stop (recover/claim replies).
    pub(crate) stop_requested: bool,
}

fn lease_fields(item: &Map<String, Value>) -> Result<LeaseResponse, WireError> {
    Ok(LeaseResponse {
        lease_token: lease_token(item.get("lease_token"))?,
        lease_generation: integer(item.get("lease_generation"), 1, "lease_generation")?,
        lease_expires_at: integer(item.get("lease_expires_at"), 1, "lease_expires_at")?,
        last_sequence: integer_or(item.get("last_sequence"), -1, -1, "last_sequence")?,
        launch_allowed: item.get("launch_allowed") == Some(&Value::Bool(true)),
        stop_requested: item.get("stop_requested") == Some(&Value::Bool(true)),
    })
}

/// Claimed request: summary identity, ciphertext, digest, approval and lease.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ClaimedRequest {
    /// Execution id.
    pub(crate) execution_id: String,
    /// Chat id.
    pub(crate) chat_id: String,
    /// Project id.
    pub(crate) project_id: String,
    /// Source id.
    pub(crate) source_id: String,
    /// Server job state.
    pub(crate) state: String,
    /// AES-GCM-combined ciphertext of the portable request.
    pub(crate) encrypted_request: String,
    /// Outer digest the server signed off (base64url HMAC).
    pub(crate) request_digest: String,
    /// Approval the server recorded.
    pub(crate) approval: Approval,
    /// Key epoch used to encrypt.
    pub(crate) key_epoch: i64,
    /// Lease granted with the claim.
    pub(crate) lease: LeaseResponse,
}

/// Validate a `remote_command_request` reply against its summary and binding.
///
/// # Errors
/// `BindingMismatch` when protocol, ids, team or key epoch differ;
/// `Invalid` for malformed fields.
pub(crate) fn validate_claimed_request(
    value: &Value,
    summary: &CommandSummary,
    binding: &ClaimBinding,
    source_session_id: &str,
) -> Result<ClaimedRequest, WireError> {
    let item = record(value, "request")?;
    let str_of = |key: &str| item.get(key).and_then(Value::as_str);
    let team_matches = match (&binding.team_id, item.get("team_id")) {
        (None, None | Some(Value::Null)) => true,
        (Some(expected), Some(Value::String(actual))) => expected == actual,
        _ => false,
    };
    if item.get("protocol_version") != Some(&json!(1))
        || str_of("execution_id") != Some(summary.execution_id.as_str())
        || str_of("chat_id") != Some(summary.chat_id.as_str())
        || str_of("project_id") != Some(binding.project_id.as_str())
        || str_of("source_id") != Some(binding.source_id.as_str())
        || !team_matches
        || !is_identifier(source_session_id)
        || item.get("key_epoch").and_then(Value::as_i64) != Some(binding.key_epoch)
    {
        return Err(WireError::BindingMismatch);
    }
    let approval = parse_approval(item.get("approval").ok_or(WireError::Invalid("approval"))?)?;
    Ok(ClaimedRequest {
        execution_id: identifier(item.get("execution_id"), "execution_id")?,
        chat_id: identifier(item.get("chat_id"), "chat_id")?,
        project_id: identifier(item.get("project_id"), "project_id")?,
        source_id: identifier(item.get("source_id"), "source_id")?,
        state: text(item.get("state"), "state")?,
        encrypted_request: text(item.get("encrypted_request"), "encrypted_request")?,
        request_digest: text(item.get("request_digest"), "request_digest")?,
        approval,
        key_epoch: integer(item.get("key_epoch"), 1, "key_epoch")?,
        lease: lease_fields(item)?,
    })
}

/// Validate a `remote_command_recovered` reply for `execution_id`.
///
/// # Errors
/// `BindingMismatch` for another execution; `Invalid` for malformed fields.
pub(crate) fn validate_lease_response(
    value: &Value,
    execution_id: &str,
) -> Result<LeaseResponse, WireError> {
    let item = record(value, "recovery")?;
    if item.get("execution_id").and_then(Value::as_str) != Some(execution_id) {
        return Err(WireError::BindingMismatch);
    }
    lease_fields(item)
}

/// Reply to `remote_command_revalidate`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct AuthorityReply {
    /// Server still authorizes the execution.
    pub(crate) authorized: bool,
    /// Origin asked to stop.
    pub(crate) stop_requested: bool,
}

impl AuthorityReply {
    /// Whether the host may keep going: authorized and not stopping.
    pub(crate) fn permits_launch(&self) -> bool {
        self.authorized && !self.stop_requested
    }
}

/// Validate a `remote_command_authority` reply: the execution and the outer
/// request digest must match what the host holds.
///
/// # Errors
/// `BindingMismatch` when execution id or digest differ (TS treats a digest
/// mismatch as denied authority; here the caller maps it to `authority_revoked`).
pub(crate) fn validate_authority_reply(
    value: &Value,
    execution_id: &str,
    outer_request_digest: &str,
) -> Result<AuthorityReply, WireError> {
    let item = record(value, "authority")?;
    if item.get("execution_id").and_then(Value::as_str) != Some(execution_id)
        || item.get("request_digest").and_then(Value::as_str) != Some(outer_request_digest)
    {
        return Err(WireError::BindingMismatch);
    }
    Ok(AuthorityReply {
        authorized: item.get("authorized") == Some(&Value::Bool(true)),
        stop_requested: item.get("stop_requested") == Some(&Value::Bool(true)),
    })
}

/// Validate an event/completion ack: same execution, sequence at least `sent`.
///
/// # Errors
/// `BindingMismatch` for another execution; `Invalid` when not acknowledged.
pub(crate) fn validate_event_ack(
    value: &Value,
    execution_id: &str,
    sent_sequence: i64,
) -> Result<CommandSummary, WireError> {
    let summary = validate_summary(value)?;
    if summary.execution_id != execution_id {
        return Err(WireError::BindingMismatch);
    }
    if summary.last_sequence < sent_sequence {
        return Err(WireError::Invalid("event not acknowledged"));
    }
    Ok(summary)
}

/// Event status values (`remote_command_event.status`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum EventStatus {
    /// Authority checks running.
    Authorizing,
    /// Process running.
    Running,
    /// Exit code 0.
    Succeeded,
    /// Failed to run or non-zero exit.
    Failed,
    /// Stopped on request.
    Stopped,
    /// Deadline exceeded.
    TimedOut,
}

impl EventStatus {
    /// Wire spelling.
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Authorizing => "authorizing",
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Stopped => "stopped",
            Self::TimedOut => "timed_out",
        }
    }

    /// Whether the status ends the execution.
    pub(crate) fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Succeeded | Self::Failed | Self::Stopped | Self::TimedOut
        )
    }
}

/// Event kinds (`remote_command_event.event_kind`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum EventKind {
    /// Status change or heartbeat.
    Status,
    /// Output chunk.
    Output,
    /// Output cap reached.
    OutputTruncated,
    /// Final event (sent as source completion).
    Terminal,
}

impl EventKind {
    /// Wire spelling.
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Status => "status",
            Self::Output => "output",
            Self::OutputTruncated => "output_truncated",
            Self::Terminal => "terminal",
        }
    }
}

/// Lease identity every event, completion and revalidate frame carries.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct LeaseIdentity {
    /// Execution id.
    pub(crate) execution_id: String,
    /// Project id.
    pub(crate) project_id: String,
    /// Source id.
    pub(crate) source_id: String,
    /// Host session id.
    pub(crate) source_session_id: String,
    /// Team id for team bindings.
    pub(crate) team_id: Option<String>,
    /// Lease token.
    pub(crate) lease_token: String,
    /// Lease generation.
    pub(crate) lease_generation: i64,
}

fn base_payload(
    execution_id: &str,
    project_id: &str,
    source_id: &str,
    session: &str,
    team: Option<&str>,
) -> Map<String, Value> {
    let mut map = Map::new();
    map.insert("protocol_version".into(), json!(1));
    map.insert("execution_id".into(), json!(execution_id));
    map.insert("project_id".into(), json!(project_id));
    map.insert("source_id".into(), json!(source_id));
    map.insert("source_session_id".into(), json!(session));
    if let Some(team) = team {
        map.insert("team_id".into(), json!(team));
    }
    map
}

/// `remote_command_discover` payload.
pub(crate) fn discover_payload(
    project_id: &str,
    source_id: &str,
    session: &str,
    team: Option<&str>,
) -> Value {
    let mut map = base_payload("", project_id, source_id, session, team);
    // Discovery is per binding, not per execution.
    map.remove("execution_id");
    Value::Object(map)
}

/// `remote_command_claim` payload.
pub(crate) fn claim_payload(summary: &CommandSummary, session: &str, team: Option<&str>) -> Value {
    Value::Object(base_payload(
        &summary.execution_id,
        &summary.project_id,
        &summary.source_id,
        session,
        team,
    ))
}

/// `remote_command_recover` payload; `runtime_status` is `running`, `stopping`
/// or `terminal_pending`.
pub(crate) fn recover_payload(
    id: &LeaseIdentity,
    last_sequence: i64,
    runtime_status: &'static str,
) -> Value {
    let mut map = base_payload(
        &id.execution_id,
        &id.project_id,
        &id.source_id,
        &id.source_session_id,
        id.team_id.as_deref(),
    );
    map.insert("last_sequence".into(), json!(last_sequence));
    map.insert("runtime_status".into(), json!(runtime_status));
    Value::Object(map)
}

fn lease_payload(id: &LeaseIdentity) -> Map<String, Value> {
    let mut map = base_payload(
        &id.execution_id,
        &id.project_id,
        &id.source_id,
        &id.source_session_id,
        id.team_id.as_deref(),
    );
    map.insert("lease_token".into(), json!(id.lease_token));
    map.insert("lease_generation".into(), json!(id.lease_generation));
    map
}

/// `remote_command_revalidate` payload.
pub(crate) fn revalidate_payload(id: &LeaseIdentity) -> Value {
    Value::Object(lease_payload(id))
}

/// `remote_command_event` payload.
///
/// # Errors
/// `Invalid` for a terminal kind/status (those use [`completion_payload`]),
/// a negative sequence or an oversized/empty ciphertext.
pub(crate) fn event_payload(
    id: &LeaseIdentity,
    sequence: i64,
    kind: EventKind,
    status: EventStatus,
    encrypted_event: &str,
) -> Result<Value, WireError> {
    if kind == EventKind::Terminal || status.is_terminal() {
        return Err(WireError::Invalid(
            "terminal event must be a source completion",
        ));
    }
    check_event_fields(sequence, encrypted_event)?;
    let mut map = lease_payload(id);
    map.insert("sequence".into(), json!(sequence));
    map.insert("event_kind".into(), json!(kind.as_str()));
    map.insert("status".into(), json!(status.as_str()));
    map.insert("encrypted_event".into(), json!(encrypted_event));
    Ok(Value::Object(map))
}

fn check_event_fields(sequence: i64, encrypted_event: &str) -> Result<(), WireError> {
    if sequence < 0 {
        return Err(WireError::Invalid("sequence"));
    }
    if encrypted_event.is_empty() || encrypted_event.chars().count() > MAX_CIPHERTEXT_CHARS {
        return Err(WireError::Invalid("encrypted_event"));
    }
    Ok(())
}

/// Truncation metadata of a source completion.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(crate) struct Truncation {
    /// Output was cut upstream of the excerpt.
    pub(crate) upstream_truncated: bool,
    /// Omitted characters; only valid with `upstream_truncated`.
    pub(crate) omitted_chars: Option<u64>,
}

/// `remote_command_source_completion` payload.
///
/// # Errors
/// `Invalid` for a non-terminal status, oversized `model_text`, bad
/// ciphertext, or `omitted_chars` without `upstream_truncated`.
pub(crate) fn completion_payload(
    id: &LeaseIdentity,
    sequence: i64,
    status: EventStatus,
    encrypted_event: &str,
    model_text: &str,
    truncation: Truncation,
) -> Result<Value, WireError> {
    if !status.is_terminal() {
        return Err(WireError::Invalid("completion status must be terminal"));
    }
    check_event_fields(sequence, encrypted_event)?;
    if model_text.len() > MAX_MODEL_TEXT_BYTES {
        return Err(WireError::Invalid("model_text"));
    }
    if !truncation.upstream_truncated && truncation.omitted_chars.is_some_and(|n| n != 0) {
        return Err(WireError::Invalid(
            "omitted_chars requires upstream_truncated",
        ));
    }
    let mut map = lease_payload(id);
    map.insert("sequence".into(), json!(sequence));
    map.insert("status".into(), json!(status.as_str()));
    map.insert("encrypted_event".into(), json!(encrypted_event));
    map.insert("model_text".into(), json!(model_text));
    if truncation.upstream_truncated {
        map.insert("upstream_truncated".into(), json!(true));
        if let Some(n) = truncation.omitted_chars {
            map.insert("omitted_chars".into(), json!(n));
        }
    }
    Ok(Value::Object(map))
}

/// Plaintext of an `encrypted_event`: `{execution_id, sequence, event_kind,
/// status, ...payload}` as in the TS flush. Payload keys never override the
/// four fixed fields. Key order is not significant (opaque to the server).
///
/// # Errors
/// `Invalid` when `payload` is not an object or collides with a fixed key.
pub(crate) fn event_plaintext(
    execution_id: &str,
    sequence: i64,
    kind: EventKind,
    status: EventStatus,
    payload: &Value,
) -> Result<String, WireError> {
    let extra = match payload {
        Value::Null => Map::new(),
        other => record(other, "event payload")?.clone(),
    };
    let mut map = Map::new();
    map.insert("execution_id".into(), json!(execution_id));
    map.insert("sequence".into(), json!(sequence));
    map.insert("event_kind".into(), json!(kind.as_str()));
    map.insert("status".into(), json!(status.as_str()));
    for (key, value) in extra {
        if map.insert(key, value).is_some() {
            return Err(WireError::Invalid(
                "event payload collides with a fixed field",
            ));
        }
    }
    serde_json::to_string(&Value::Object(map)).map_err(|_| WireError::Invalid("event payload"))
}
