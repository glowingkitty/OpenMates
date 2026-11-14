//! Remote command review card for the Apple shell: validation of the
//! `remote_command_review` payload, the canonical request and digest, the
//! decision payloads (prepare, reject, stop), the output reducer and the
//! origin completion. Bindings only marshal over
//! `openmates_sdk::remote_command_review`; Swift keeps the card UI, the
//! per-card fence bookkeeping and the CryptoKit/encrypt adapters.
//! Spec: remote command review assertions (agentic coding).
use crate::CoreError;
use openmates_sdk::remote_command_review as core;

fn invalid(error: core::ReviewError) -> CoreError {
    CoreError::Invalid {
        message: error.to_string(),
    }
}

/// Command policy of a review.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct RemoteCommandPolicyRecord {
    /// Command argv.
    pub argv: Vec<String>,
    /// Project-relative working directory.
    pub cwd: String,
    /// `foreground` or `background`.
    pub mode: String,
    /// `read_only` or `read_write`.
    pub source_access: String,
    /// Deadline in milliseconds.
    pub deadline_ms: u64,
    /// Writable profile names.
    pub writable_profiles: Vec<String>,
    /// Optional network profile.
    pub network_profile: Option<String>,
    /// Credential profile names.
    pub credential_profiles: Vec<String>,
}

/// Explanation block of the card.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct RemoteCommandExplanationRecord {
    /// Summary text.
    pub summary: String,
    /// Expected effects.
    pub effects: Vec<String>,
    /// Risks.
    pub risks: Vec<String>,
    /// Open uncertainty.
    pub uncertainty: Vec<String>,
}

/// A validated review (the card's static state).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct RemoteCommandReviewRecord {
    /// Execution id, also the card id.
    pub execution_id: String,
    /// Chat id.
    pub chat_id: String,
    /// Project id.
    pub project_id: String,
    /// Source id.
    pub source_id: String,
    /// Creation time (unix seconds).
    pub created_at: u64,
    /// Expiry (unix seconds).
    pub review_expires_at: u64,
    /// Token echoed on decisions.
    pub review_token: String,
    /// `one_run` or `one_run_or_preset`.
    pub approval_requirement: String,
    /// Command policy.
    pub command: RemoteCommandPolicyRecord,
    /// Explanation.
    pub explanation: RemoteCommandExplanationRecord,
}

/// Output accumulated from events (the card's streaming state).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct RemoteCommandOutputRecord {
    /// Highest applied sequence, `-1` before any event.
    pub last_sequence: i64,
    /// Latest status.
    pub status: String,
    /// Cleaned output so far.
    pub latest_output: String,
    /// A sequence was skipped.
    pub has_sequence_gap: bool,
    /// Output was truncated upstream or locally.
    pub upstream_truncated: bool,
}

impl From<core::RemoteCommandReview> for RemoteCommandReviewRecord {
    fn from(r: core::RemoteCommandReview) -> Self {
        Self {
            execution_id: r.execution_id,
            chat_id: r.chat_id,
            project_id: r.project_id,
            source_id: r.source_id,
            created_at: r.created_at,
            review_expires_at: r.review_expires_at,
            review_token: r.review_token,
            approval_requirement: r.approval_requirement,
            command: RemoteCommandPolicyRecord {
                argv: r.command.argv,
                cwd: r.command.cwd,
                mode: r.command.mode,
                source_access: r.command.source_access,
                deadline_ms: r.command.deadline_ms,
                writable_profiles: r.command.writable_profiles,
                network_profile: r.command.network_profile,
                credential_profiles: r.command.credential_profiles,
            },
            explanation: RemoteCommandExplanationRecord {
                summary: r.explanation.summary,
                effects: r.explanation.effects,
                risks: r.explanation.risks,
                uncertainty: r.explanation.uncertainty,
            },
        }
    }
}

impl From<RemoteCommandReviewRecord> for core::RemoteCommandReview {
    fn from(r: RemoteCommandReviewRecord) -> Self {
        Self {
            protocol_version: 1,
            execution_id: r.execution_id,
            chat_id: r.chat_id,
            project_id: r.project_id,
            source_id: r.source_id,
            state: "REVIEW_REQUIRED".into(),
            created_at: r.created_at,
            review_expires_at: r.review_expires_at,
            review_token: r.review_token,
            approval_requirement: r.approval_requirement,
            command: core::ReviewPolicy {
                argv: r.command.argv,
                cwd: r.command.cwd,
                mode: r.command.mode,
                source_access: r.command.source_access,
                deadline_ms: r.command.deadline_ms,
                writable_profiles: r.command.writable_profiles,
                network_profile: r.command.network_profile,
                credential_profiles: r.command.credential_profiles,
            },
            explanation: core::ReviewExplanation {
                summary: r.explanation.summary,
                effects: r.explanation.effects,
                risks: r.explanation.risks,
                uncertainty: r.explanation.uncertainty,
            },
        }
    }
}

impl From<RemoteCommandOutputRecord> for core::OutputState {
    fn from(o: RemoteCommandOutputRecord) -> Self {
        Self {
            last_sequence: o.last_sequence,
            status: o.status,
            latest_output: o.latest_output,
            has_sequence_gap: o.has_sequence_gap,
            upstream_truncated: o.upstream_truncated,
        }
    }
}

impl From<core::OutputState> for RemoteCommandOutputRecord {
    fn from(o: core::OutputState) -> Self {
        Self {
            last_sequence: o.last_sequence,
            status: o.status,
            latest_output: o.latest_output,
            has_sequence_gap: o.has_sequence_gap,
            upstream_truncated: o.upstream_truncated,
        }
    }
}

/// Decode and validate a `remote_command_review` JSON payload.
///
/// # Errors
/// `Invalid` when the payload breaks the review contract.
#[uniffi::export]
pub fn parse_remote_command_review(
    payload_json: String,
) -> Result<RemoteCommandReviewRecord, CoreError> {
    core::parse_review(&payload_json)
        .map(Into::into)
        .map_err(invalid)
}

/// Whether a review may become a card in `active_chat_id` now.
///
/// # Errors
/// `Invalid` for another chat, an expired review or a full window.
#[uniffi::export]
pub fn check_remote_command_review_acceptable(
    review: RemoteCommandReviewRecord,
    active_chat_id: String,
    now_unix: u64,
    open_reviews: u32,
) -> Result<(), CoreError> {
    core::RemoteCommandReview::from(review)
        .check_acceptable(&active_chat_id, now_unix, open_reviews as usize)
        .map_err(invalid)
}

/// Canonical portable request JSON that the user approves (the plaintext Swift encrypts).
#[uniffi::export]
pub fn remote_command_canonical_request(review: RemoteCommandReviewRecord) -> String {
    core::RemoteCommandReview::from(review).canonical_portable_request()
}

/// Base64url request digest over the canonical request, keyed with the 32-byte Project key.
///
/// # Errors
/// `Invalid` when the key is not 32 bytes.
#[uniffi::export]
pub fn remote_command_request_digest(
    canonical_request: String,
    project_key: Vec<u8>,
) -> Result<String, CoreError> {
    core::request_digest(&canonical_request, &project_key).map_err(invalid)
}

/// JSON of the `remote_command_prepare` payload.
#[uniffi::export]
pub fn remote_command_prepare_payload_json(
    review: RemoteCommandReviewRecord,
    encrypted_request: String,
    request_digest: String,
) -> String {
    core::RemoteCommandReview::from(review)
        .prepare_payload(&encrypted_request, &request_digest)
        .to_string()
}

/// JSON of the `remote_command_reject` payload.
#[uniffi::export]
pub fn remote_command_reject_payload_json(review: RemoteCommandReviewRecord) -> String {
    core::RemoteCommandReview::from(review)
        .reject_payload()
        .to_string()
}

/// JSON of the `remote_command_stop` payload.
#[uniffi::export]
pub fn remote_command_stop_payload_json(review: RemoteCommandReviewRecord) -> String {
    core::RemoteCommandReview::from(review)
        .stop_payload()
        .to_string()
}

/// Fresh output state before the first event.
#[uniffi::export]
pub fn remote_command_new_output() -> RemoteCommandOutputRecord {
    core::OutputState::new().into()
}

/// Fold one decrypted event into the output state.
///
/// # Errors
/// `Invalid` for an unknown kind/status, a kind/status mismatch or a repeated sequence.
#[uniffi::export]
pub fn remote_command_apply_event(
    state: RemoteCommandOutputRecord,
    event_kind: String,
    status: String,
    sequence: i64,
    text: Option<String>,
) -> Result<RemoteCommandOutputRecord, CoreError> {
    let mut core_state = core::OutputState::from(state);
    core_state
        .apply_event(&event_kind, &status, sequence, text.as_deref())
        .map_err(invalid)?;
    Ok(core_state.into())
}

/// JSON of the `remote_command_origin_completion` payload for a terminal state.
#[uniffi::export]
pub fn remote_command_completion_payload_json(
    review: RemoteCommandReviewRecord,
    state: RemoteCommandOutputRecord,
) -> String {
    core::OutputState::from(state)
        .completion(&core::RemoteCommandReview::from(review))
        .to_string()
}

/// Card status a server response maps to, or nothing to keep the current one.
#[uniffi::export]
pub fn remote_command_status_for_response(
    kind: String,
    state: Option<String>,
    result_status: Option<String>,
) -> Option<String> {
    core::status_for_response(&kind, state.as_deref(), result_status.as_deref())
}

/// Whether a card in `status` can still be stopped.
#[uniffi::export]
pub fn remote_command_is_stoppable(status: String) -> bool {
    core::is_stoppable(&status)
}
