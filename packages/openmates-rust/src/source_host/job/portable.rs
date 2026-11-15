//! Decrypts, parses and verifies the portable remote-command request a claim
//! delivers: AES-GCM-combined plaintext under the binding's Project key, exact
//! keys, canonical byte equality, claim binding and constant-time digest check.
//!
//! Mirrors `parsePortableRequest`, `parsePolicy`, `parseApproval` and
//! `assertPortableBinding` in `remoteCommandSource.ts`, and the canonical form
//! of `canonicalPortableRemoteCommandRequest` in `remoteCommandClient.ts`
//! (vectors: `tests/fixtures/remote_command_portable_vectors.json`).
//! spec: specifications/features/app-skills/code-run code-run.remote.*

use super::wire::{self, Approval, ClaimedRequest, WireError, exact_keys, identifier, parse_approval, record, text};
use crate::crypto;
use crate::remote_command_review::request_digest;
use serde_json::Value;

const MAX_ARGV_ITEMS: usize = 128;
const MAX_ARGV_ITEM_BYTES: usize = 16 * 1024;
const MIN_DEADLINE_MS: i64 = 100;
const MAX_DEADLINE_MS: i64 = 86_400_000;

/// Whether the command runs to completion or in the background.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Mode {
    /// Foreground run.
    Foreground,
    /// Background run (never with `read_write`).
    Background,
}

/// Access the command gets to the Project source tree.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum SourceAccess {
    /// Read-only source.
    ReadOnly,
    /// Read-write source.
    ReadWrite,
}

/// Exact command policy the user approved.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Policy {
    /// Command and arguments (1..=128 items, each non-empty and <= 16 KiB).
    pub(crate) argv: Vec<String>,
    /// Project-relative working directory.
    pub(crate) cwd: String,
    /// Run mode.
    pub(crate) mode: Mode,
    /// Source access.
    pub(crate) source_access: SourceAccess,
    /// Deadline in ms (100..=86_400_000).
    pub(crate) deadline_ms: u64,
    /// Writable profile ids.
    pub(crate) writable_profiles: Vec<String>,
    /// Network profile id, if any.
    pub(crate) network_profile: Option<String>,
    /// Credential profile ids.
    pub(crate) credential_profiles: Vec<String>,
}

/// Decrypted, verified portable request.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct PortableRequest {
    /// Execution id.
    pub(crate) execution_id: String,
    /// Chat id.
    pub(crate) chat_id: String,
    /// Project id.
    pub(crate) project_id: String,
    /// Source id.
    pub(crate) source_id: String,
    /// Approved policy.
    pub(crate) policy: Policy,
    /// Approval choice.
    pub(crate) approval: Approval,
}

/// Why a claimed request was refused.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum PortableError {
    /// Ciphertext did not decrypt under the Project key.
    Decrypt,
    /// Plaintext is not a valid portable request.
    Invalid(WireError),
    /// Plaintext is valid JSON but not the canonical serialization.
    NotCanonical,
    /// Ids or approval differ from the claim.
    ClaimMismatch,
    /// Digest differs from the claim's `request_digest`.
    DigestMismatch,
}

impl std::fmt::Display for PortableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Decrypt => f.write_str("remote command request could not be decrypted"),
            Self::Invalid(e) => write!(f, "invalid portable remote command: {e}"),
            Self::NotCanonical => f.write_str("Portable remote command is not canonical"),
            Self::ClaimMismatch => f.write_str("Encrypted remote command binding mismatch"),
            Self::DigestMismatch => f.write_str("remote command digest mismatch"),
        }
    }
}
impl std::error::Error for PortableError {}

impl From<WireError> for PortableError {
    fn from(e: WireError) -> Self {
        Self::Invalid(e)
    }
}

fn string_list(value: Option<&Value>, rule: &'static str) -> Result<Vec<String>, WireError> {
    value
        .and_then(Value::as_array)
        .ok_or(WireError::Invalid(rule))?
        .iter()
        .map(|v| v.as_str().map(str::to_owned).ok_or(WireError::Invalid(rule)))
        .collect()
}

/// Parse a policy object with exact keys and the TS + server limits.
///
/// # Errors
/// `Invalid` for unknown/missing keys, bad enums, argv or deadline limits.
pub(crate) fn parse_policy(value: &Value) -> Result<Policy, WireError> {
    let policy = record(value, "policy")?;
    exact_keys(
        policy,
        &["argv", "cwd", "mode", "source_access", "deadline_ms", "writable_profiles", "network_profile", "credential_profiles"],
    )?;
    let argv = string_list(policy.get("argv"), "argv")?;
    // Server schema: 1..=128 non-empty entries, no NUL, <= 16 KiB each.
    if argv.is_empty()
        || argv.len() > MAX_ARGV_ITEMS
        || argv.iter().any(|a| a.is_empty() || a.contains('\0') || a.len() > MAX_ARGV_ITEM_BYTES)
    {
        return Err(WireError::Invalid("argv"));
    }
    let mode = match policy.get("mode").and_then(Value::as_str) {
        Some("foreground") => Mode::Foreground,
        Some("background") => Mode::Background,
        _ => return Err(WireError::Invalid("mode")),
    };
    let source_access = match policy.get("source_access").and_then(Value::as_str) {
        Some("read_only") => SourceAccess::ReadOnly,
        Some("read_write") => SourceAccess::ReadWrite,
        _ => return Err(WireError::Invalid("source_access")),
    };
    let deadline = wire::integer(policy.get("deadline_ms"), MIN_DEADLINE_MS, "deadline_ms")?;
    if deadline > MAX_DEADLINE_MS {
        return Err(WireError::Invalid("deadline_ms"));
    }
    let network_profile = match policy.get("network_profile") {
        Some(Value::Null) => None,
        other => Some(text(other, "network_profile")?),
    };
    Ok(Policy {
        argv,
        cwd: text(policy.get("cwd"), "cwd")?,
        mode,
        source_access,
        deadline_ms: deadline as u64,
        writable_profiles: string_list(policy.get("writable_profiles"), "writable_profiles")?,
        network_profile,
        credential_profiles: string_list(policy.get("credential_profiles"), "credential_profiles")?,
    })
}

/// Canonical JSON of a portable request: fixed key order, compact, serde_json
/// string escaping (identical to `JSON.stringify` for valid Unicode).
pub(crate) fn canonical_request(request: &PortableRequest) -> String {
    let policy = &request.policy;
    let j = |v: &dyn erased::Ser| v.json();
    let mode = match policy.mode {
        Mode::Foreground => "foreground",
        Mode::Background => "background",
    };
    let access = match policy.source_access {
        SourceAccess::ReadOnly => "read_only",
        SourceAccess::ReadWrite => "read_write",
    };
    format!(
        "{{\"protocol_version\":1,\"execution_id\":{},\"chat_id\":{},\"project_id\":{},\"source_id\":{},\"policy\":{{\"argv\":{},\"cwd\":{},\"mode\":{},\"source_access\":{},\"deadline_ms\":{},\"writable_profiles\":{},\"network_profile\":{},\"credential_profiles\":{}}},\"approval\":{}}}",
        j(&request.execution_id),
        j(&request.chat_id),
        j(&request.project_id),
        j(&request.source_id),
        j(&policy.argv),
        j(&policy.cwd),
        j(&mode),
        j(&access),
        policy.deadline_ms,
        j(&policy.writable_profiles),
        j(&policy.network_profile),
        j(&policy.credential_profiles),
        approval_json(&request.approval),
    )
}

// Hand-serialized: `serde_json::Value` objects sort keys (no preserve_order),
// but the canonical approval order is kind, preset_id, definition_digest.
fn approval_json(approval: &Approval) -> String {
    match approval {
        Approval::OneRun => "{\"kind\":\"one_run\"}".to_owned(),
        Approval::Preset { preset_id, definition_digest } => format!(
            "{{\"kind\":\"preset\",\"preset_id\":{},\"definition_digest\":{}}}",
            serde_json::to_string(preset_id).expect("string serializes"),
            serde_json::to_string(definition_digest).expect("string serializes"),
        ),
    }
}

mod erased {
    /// Serialize any value to compact JSON (strings, string lists, options).
    pub(super) trait Ser {
        fn json(&self) -> String;
    }
    impl<T: serde::Serialize> Ser for T {
        fn json(&self) -> String {
            serde_json::to_string(self).expect("strings and string lists always serialize")
        }
    }
}

/// Parse a decrypted portable request: exact keys, then canonical byte equality.
///
/// # Errors
/// `Invalid` for malformed content, `NotCanonical` when re-serializing differs.
pub(crate) fn parse_portable_request(plaintext: &str) -> Result<PortableRequest, PortableError> {
    let parsed: Value = serde_json::from_str(plaintext).map_err(|_| WireError::Invalid("portable request json"))?;
    let item = record(&parsed, "portable request")?;
    exact_keys(item, &["protocol_version", "execution_id", "chat_id", "project_id", "source_id", "policy", "approval"])?;
    if item.get("protocol_version") != Some(&serde_json::json!(1)) {
        return Err(WireError::Invalid("protocol_version").into());
    }
    let request = PortableRequest {
        execution_id: identifier(item.get("execution_id"), "execution_id")?,
        chat_id: identifier(item.get("chat_id"), "chat_id")?,
        project_id: identifier(item.get("project_id"), "project_id")?,
        source_id: identifier(item.get("source_id"), "source_id")?,
        policy: parse_policy(item.get("policy").ok_or(WireError::Invalid("policy"))?)?,
        approval: parse_approval(item.get("approval").ok_or(WireError::Invalid("approval"))?)?,
    };
    if canonical_request(&request) != plaintext {
        return Err(PortableError::NotCanonical);
    }
    Ok(request)
}

/// Constant-time byte equality (length is not secret: digests are fixed size).
fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

/// Decrypt and verify the claim's `encrypted_request`.
///
/// Order matters: canonical parse, then claim binding (ids and approval),
/// then the HMAC digest over the canonical plaintext against the claim's
/// `request_digest`, so nothing from an unauthenticated request is acted on.
///
/// # Errors
/// See [`PortableError`]; every error means "do not launch".
pub(crate) fn open_claimed_request(claimed: &ClaimedRequest, project_key: &[u8; 32]) -> Result<PortableRequest, PortableError> {
    let plaintext = crypto::decrypt_combined(&claimed.encrypted_request, project_key).map_err(|_| PortableError::Decrypt)?;
    let request = parse_portable_request(&plaintext)?;
    if request.execution_id != claimed.execution_id
        || request.chat_id != claimed.chat_id
        || request.project_id != claimed.project_id
        || request.source_id != claimed.source_id
        || request.approval != claimed.approval
    {
        return Err(PortableError::ClaimMismatch);
    }
    let digest = request_digest(&plaintext, project_key).map_err(|_| PortableError::DigestMismatch)?;
    if !constant_time_eq(digest.as_bytes(), claimed.request_digest.as_bytes()) {
        return Err(PortableError::DigestMismatch);
    }
    Ok(request)
}
