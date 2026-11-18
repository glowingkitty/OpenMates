//! Remote command review card policy shared by every shell: validation of the
//! `remote_command_review` payload, the canonical portable request and its
//! HMAC digest, terminal output hygiene and bounding, the event reducer that
//! builds the origin completion, and the status mapping of server responses.
//! Mirrors `frontend/packages/ui/src/services/browserRemoteCommandClient.ts`
//! (web) so Apple and web accept and send byte-identical requests.
//! Spec: remote command review assertions (agentic coding, `specifications/`).
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use hmac::{Hmac, Mac};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::Sha256;
use std::fmt;
use std::sync::OnceLock;

/// Characters kept from terminal output sent to the model.
pub const MAX_COMPLETION_CHARS: usize = 24_000;
/// Accumulated output above which the card marks the stream as truncated.
pub const MAX_CARD_OUTPUT_CHARS: usize = 48_000;
/// Maximum reviews a chat window may hold at once.
pub const MAX_OPEN_REVIEWS: usize = 32;
const OMISSION_MARKER: &str = "\n\n[... terminal output omitted ...]\n\n";

/// Refusal of a review payload or event with a stable reason.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ReviewError {
    /// The payload violates the review contract (names the rule).
    Invalid(&'static str),
    /// The review is expired, for another chat or over the open-review cap.
    InvalidContext,
}

impl fmt::Display for ReviewError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(rule) => write!(f, "invalid remote command review: {rule}"),
            Self::InvalidContext => f.write_str("remote command review has no valid context"),
        }
    }
}
impl std::error::Error for ReviewError {}

/// Policy the user approves (snake_case wire form).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReviewPolicy {
    /// Command argv.
    pub argv: Vec<String>,
    /// Project-relative working directory.
    pub cwd: String,
    /// `foreground` or `background`.
    pub mode: String,
    /// `read_only` or `read_write`.
    pub source_access: String,
    /// Deadline in milliseconds (100 ..= 86_400_000).
    pub deadline_ms: u64,
    /// Writable profile names.
    pub writable_profiles: Vec<String>,
    /// Optional network profile.
    #[serde(default)]
    pub network_profile: Option<String>,
    /// Credential profile names (names only, never values).
    pub credential_profiles: Vec<String>,
}

/// Explanation shown on the card.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReviewExplanation {
    /// Summary text (at most 16_384 chars).
    pub summary: String,
    /// Expected effects.
    #[serde(default)]
    pub effects: Vec<String>,
    /// Risks.
    #[serde(default)]
    pub risks: Vec<String>,
    /// Open uncertainty.
    #[serde(default)]
    pub uncertainty: Vec<String>,
}

/// A decoded `remote_command_review` payload (snake_case wire form).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RemoteCommandReview {
    /// Protocol version, must be 1.
    pub protocol_version: u32,
    /// Execution id (also the card id).
    pub execution_id: String,
    /// Chat the review belongs to.
    pub chat_id: String,
    /// Project id.
    pub project_id: String,
    /// Source id.
    pub source_id: String,
    /// Must be `REVIEW_REQUIRED`.
    pub state: String,
    /// Creation time (unix seconds).
    pub created_at: u64,
    /// Expiry (unix seconds), after `created_at`.
    pub review_expires_at: u64,
    /// Opaque token echoed back on decisions (>= 32 chars).
    pub review_token: String,
    /// `one_run` or `one_run_or_preset`.
    pub approval_requirement: String,
    /// The command policy.
    pub command: ReviewPolicy,
    /// The explanation.
    pub explanation: ReviewExplanation,
}

fn identifier_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$").expect("static pattern"))
}

/// Decode and validate a review payload.
///
/// # Errors
/// `Invalid` when JSON does not decode or any bound of the contract fails.
pub fn parse_review(payload_json: &str) -> Result<RemoteCommandReview, ReviewError> {
    let review: RemoteCommandReview =
        serde_json::from_str(payload_json).map_err(|_| ReviewError::Invalid("shape"))?;
    review.validate()?;
    Ok(review)
}

impl RemoteCommandReview {
    /// Check every bound of the review contract.
    ///
    /// # Errors
    /// `Invalid` naming the first violated rule.
    pub fn validate(&self) -> Result<(), ReviewError> {
        let c = &self.command;
        let inv = ReviewError::Invalid;
        if self.protocol_version != 1 || self.state != "REVIEW_REQUIRED" {
            return Err(inv("state"));
        }
        if self.review_token.chars().count() < 32 || self.review_expires_at <= self.created_at {
            return Err(inv("token_or_expiry"));
        }
        let ids = [
            &self.execution_id,
            &self.chat_id,
            &self.project_id,
            &self.source_id,
        ];
        if !ids.iter().all(|id| identifier_re().is_match(id)) {
            return Err(inv("identifier"));
        }
        if !matches!(
            self.approval_requirement.as_str(),
            "one_run" | "one_run_or_preset"
        ) {
            return Err(inv("approval_requirement"));
        }
        if c.argv.is_empty()
            || c.argv.len() > 128
            || !c
                .argv
                .iter()
                .all(|a| !a.is_empty() && !a.contains('\0') && a.chars().count() <= 128)
        {
            return Err(inv("argv"));
        }
        if c.cwd.is_empty()
            || c.cwd.chars().count() > 1024
            || c.cwd.starts_with('/')
            || c.cwd.contains('\\')
            || c.cwd.split('/').any(|p| p == "..")
        {
            return Err(inv("cwd"));
        }
        if !matches!(c.mode.as_str(), "foreground" | "background")
            || !matches!(c.source_access.as_str(), "read_only" | "read_write")
            || !(100..=86_400_000).contains(&c.deadline_ms)
            || c.writable_profiles.len() > 32
            || c.credential_profiles.len() > 32
            || self.explanation.summary.chars().count() > 16_384
        {
            return Err(inv("policy"));
        }
        Ok(())
    }

    /// Whether this review may become a card now.
    ///
    /// # Errors
    /// `InvalidContext` for another chat, an expired review or a full window.
    pub fn check_acceptable(
        &self,
        active_chat_id: &str,
        now_unix: u64,
        open_reviews: usize,
    ) -> Result<(), ReviewError> {
        if self.chat_id != active_chat_id
            || self.review_expires_at <= now_unix
            || open_reviews >= MAX_OPEN_REVIEWS
        {
            return Err(ReviewError::InvalidContext);
        }
        Ok(())
    }

    /// Canonical portable request JSON the user approves, in the fixed wire key
    /// order of the web client's `canonicalPortableRemoteCommandRequest`.
    pub fn canonical_portable_request(&self) -> String {
        let c = &self.command;
        // Values serialize through serde_json (valid JSON strings/arrays); the
        // key order is fixed by hand because the digest must be byte-stable.
        let j = |v: &dyn erased::Ser| v.to_json();
        let policy = format!(
            "{{\"argv\":{},\"cwd\":{},\"mode\":{},\"source_access\":{},\"deadline_ms\":{},\"writable_profiles\":{},\"network_profile\":{},\"credential_profiles\":{}}}",
            j(&c.argv),
            j(&c.cwd),
            j(&c.mode),
            j(&c.source_access),
            c.deadline_ms,
            j(&c.writable_profiles),
            j(&c.network_profile),
            j(&c.credential_profiles)
        );
        format!(
            "{{\"protocol_version\":1,\"execution_id\":{},\"chat_id\":{},\"project_id\":{},\"source_id\":{},\"policy\":{},\"approval\":{{\"kind\":\"one_run\"}}}}",
            j(&self.execution_id),
            j(&self.chat_id),
            j(&self.project_id),
            j(&self.source_id),
            policy
        )
    }
}

impl RemoteCommandReview {
    /// `remote_command_reject` payload for this review.
    pub fn reject_payload(&self) -> Value {
        json!({"protocol_version": 1, "execution_id": self.execution_id,
            "chat_id": self.chat_id, "project_id": self.project_id,
            "review_token": self.review_token})
    }

    /// `remote_command_stop` payload for this review.
    pub fn stop_payload(&self) -> Value {
        json!({"protocol_version": 1, "execution_id": self.execution_id,
            "chat_id": self.chat_id, "project_id": self.project_id})
    }

    /// `remote_command_prepare` payload carrying the client-encrypted request
    /// and its digest; approval is always a single run.
    pub fn prepare_payload(&self, encrypted_request: &str, request_digest: &str) -> Value {
        json!({"protocol_version": 1, "execution_id": self.execution_id,
            "chat_id": self.chat_id, "project_id": self.project_id,
            "source_id": self.source_id, "review_token": self.review_token,
            "encrypted_request": encrypted_request, "request_digest": request_digest,
            "approval": {"kind": "one_run"}})
    }
}

mod erased {
    //! Tiny object-safe wrapper so one closure serializes any wire value.
    use serde::Serialize;
    pub(super) trait Ser {
        fn to_json(&self) -> String;
    }
    impl<T: Serialize> Ser for T {
        fn to_json(&self) -> String {
            // Strings, string arrays and options cannot fail to serialize.
            serde_json::to_string(self).unwrap_or_else(|_| "null".into())
        }
    }
}

/// Base64url (no padding) HMAC-SHA256 over `["openmates-remote-command-request-v1", canonical]`
/// keyed with the Project key.
///
/// # Errors
/// `Invalid` when the key is not 32 bytes.
pub fn request_digest(canonical_request: &str, project_key: &[u8]) -> Result<String, ReviewError> {
    if project_key.len() != 32 {
        return Err(ReviewError::Invalid("project_key"));
    }
    let identity = serde_json::to_string(&json!([
        "openmates-remote-command-request-v1",
        canonical_request
    ]))
    .map_err(|_| ReviewError::Invalid("identity"))?;
    let mut mac = Hmac::<Sha256>::new_from_slice(project_key)
        .map_err(|_| ReviewError::Invalid("project_key"))?;
    mac.update(identity.as_bytes());
    Ok(URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes()))
}

/// Strip OSC/CSI escapes, bidi controls and control characters (tab, LF, CR kept).
pub fn clean_terminal_text(value: &str) -> String {
    static RES: OnceLock<[Regex; 3]> = OnceLock::new();
    let res = RES.get_or_init(|| {
        [
            Regex::new("\u{1b}\\][^\u{7}\u{1b}]*(?:\u{7}|\u{1b}\\\\)").expect("static pattern"),
            Regex::new("\u{1b}\\[[0-?]*[ -/]*[@-~]").expect("static pattern"),
            Regex::new(
                "[\u{202a}-\u{202e}\u{2066}-\u{2069}\u{0}-\u{8}\u{b}\u{c}\u{e}-\u{1f}\u{7f}]",
            )
            .expect("static pattern"),
        ]
    });
    let a = res[0].replace_all(value, "");
    let b = res[1].replace_all(&a, "");
    res[2].replace_all(&b, "").into_owned()
}

/// Keep head and tail of long output around an omission marker.
pub fn bounded_output(value: &str) -> String {
    let chars: Vec<char> = value.chars().collect();
    if chars.len() <= MAX_COMPLETION_CHARS {
        return value.to_string();
    }
    let half = (MAX_COMPLETION_CHARS - OMISSION_MARKER.chars().count()) / 2;
    let head: String = chars[..half].iter().collect();
    let tail: String = chars[chars.len() - half..].iter().collect();
    format!("{head}{OMISSION_MARKER}{tail}")
}

/// Card status a server response (`remote_command_response` / `_error`) maps
/// to, or `None` to leave the status unchanged.
pub fn status_for_response(
    kind: &str,
    state: Option<&str>,
    result_status: Option<&str>,
) -> Option<String> {
    if kind == "remote_command_error" {
        return Some("error".into());
    }
    match state? {
        "WAITING_FOR_EXECUTOR" => Some("waiting_for_executor".into()),
        "STOP_REQUESTED" => Some("stop_requested".into()),
        "REJECTED" => Some("rejected".into()),
        "TERMINAL" => Some(result_status.unwrap_or("succeeded").into()),
        _ => None,
    }
}

/// Statuses in which a command can still be stopped.
pub fn is_stoppable(status: &str) -> bool {
    matches!(
        status,
        "preparing" | "waiting_for_executor" | "authorizing" | "running"
    )
}

/// Whether a status is final for the card.
pub fn is_terminal_status(status: &str) -> bool {
    matches!(status, "succeeded" | "failed" | "stopped" | "timed_out")
}

/// Accumulated output state of one card.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OutputState {
    /// Highest sequence applied, `-1` before any event.
    pub last_sequence: i64,
    /// Latest status from events.
    pub status: String,
    /// Cleaned output so far.
    pub latest_output: String,
    /// A sequence number was skipped.
    pub has_sequence_gap: bool,
    /// Upstream or local truncation happened.
    pub upstream_truncated: bool,
}

impl Default for OutputState {
    fn default() -> Self {
        Self::new()
    }
}

impl OutputState {
    /// Fresh state before the first event.
    pub fn new() -> Self {
        Self {
            last_sequence: -1,
            status: "pending".into(),
            latest_output: String::new(),
            has_sequence_gap: false,
            upstream_truncated: false,
        }
    }

    /// Validate an event envelope (kind/status pairing) and fold it in.
    ///
    /// # Errors
    /// `Invalid` for unknown kind/status, kind/status mismatch or a
    /// non-increasing sequence.
    pub fn apply_event(
        &mut self,
        kind: &str,
        status: &str,
        sequence: i64,
        text: Option<&str>,
    ) -> Result<(), ReviewError> {
        let terminal_status = is_terminal_status(status);
        if !matches!(kind, "status" | "output" | "output_truncated" | "terminal")
            || !(terminal_status || matches!(status, "authorizing" | "running"))
            || (kind == "terminal") != terminal_status
            || sequence <= self.last_sequence
        {
            return Err(ReviewError::Invalid("event"));
        }
        if sequence != self.last_sequence + 1 {
            self.has_sequence_gap = true;
        }
        self.last_sequence = sequence;
        self.status = status.into();
        if kind == "output" {
            if let Some(t) = text {
                self.latest_output.push_str(&clean_terminal_text(t));
                if self.latest_output.chars().count() > MAX_CARD_OUTPUT_CHARS {
                    self.latest_output = bounded_output(&self.latest_output);
                    self.upstream_truncated = true;
                }
            }
        }
        if kind == "output_truncated" {
            self.upstream_truncated = true;
        }
        Ok(())
    }

    /// Origin completion payload (JSON object) for a terminal event.
    pub fn completion(&self, review: &RemoteCommandReview) -> Value {
        let output = bounded_output(&self.latest_output);
        let model_text = if self.has_sequence_gap {
            format!(
                "[Incomplete terminal output: one or more event sequences were unavailable.]\n{output}"
            )
        } else {
            output.clone()
        };
        let truncated = self.upstream_truncated || self.has_sequence_gap;
        let mut v = json!({"protocol_version": 1, "execution_id": review.execution_id,
            "chat_id": review.chat_id, "project_id": review.project_id,
            "result_status": self.status, "model_text": model_text,
            "upstream_truncated": truncated});
        if truncated {
            let omitted = self
                .latest_output
                .chars()
                .count()
                .saturating_sub(output.chars().count());
            v["omitted_chars"] = json!(omitted);
        }
        v
    }
}

#[cfg(test)]
#[path = "remote_command_review_tests.rs"]
mod tests;
