//! Ungated base of hosted Project files: the stable refusal type, the shared
//! path decisions, the keyed identities and the field sealer. Compiled on every
//! target (wasm, Apple, native) so Project embed adoption works everywhere; the
//! hosted writer in `hosted` re-exports and keeps using it unchanged.
use super::*;
use hmac::{Hmac, Mac};
use sha2::Sha256;
use zeroize::Zeroizing;

/// A refusal of a hosted file operation. `Refused` codes are the exact npm/web
/// executor codes (`file_exists`, `stale_base`, `invalid_patch`, …) so job
/// results and CLI contract errors stay byte-identical across shells.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HostedFileError {
    /// A transport, crypto or authorization failure of the core.
    Core(Error),
    /// A deterministic executor refusal with its stable code.
    Refused(&'static str),
    /// The server rejected the commit; the code is the server's own,
    /// lowercased and limited to `[a-z][a-z0-9_]{1,79}` like the TS executor.
    Rejected(String),
}

impl From<super::commit_history::ReplayError> for HostedFileError {
    fn from(error: super::commit_history::ReplayError) -> Self {
        match error {
            super::commit_history::ReplayError::Core(error) => Self::Core(error),
            super::commit_history::ReplayError::InvalidPatch => Self::Refused("invalid_patch"),
        }
    }
}

impl From<Error> for HostedFileError {
    fn from(error: Error) -> Self {
        Self::Core(error)
    }
}

impl HostedFileError {
    /// Server rejection code after the TS `SAFE_CODE` filter.
    pub(crate) fn rejected(code: Option<&str>) -> Self {
        let Some(code) = code.map(str::to_ascii_lowercase) else {
            return Self::Refused("commit_rejected");
        };
        let bytes = code.as_bytes();
        let safe = (2..=80).contains(&bytes.len())
            && bytes[0].is_ascii_lowercase()
            && bytes
                .iter()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'_');
        if safe {
            Self::Rejected(code)
        } else {
            Self::Refused("client_execution_failed")
        }
    }
    /// The stable code a job result reports (`SAFE_CODE` of the TS executor).
    pub fn code(&self) -> &str {
        match self {
            Self::Refused(code) => code,
            Self::Rejected(code) => code,
            Self::Core(Error::Conflict) => "revision_conflict",
            Self::Core(Error::Cancelled) => "cancelled",
            Self::Core(Error::Offline) => "protocol_timeout",
            Self::Core(_) => "client_execution_failed",
        }
    }
    /// Job result status for this refusal (`conflict` for stale/racing writes).
    pub fn status(&self) -> &'static str {
        match self.code() {
            "stale_base" | "revision_conflict" | "file_exists" | "file_changed"
            | "target_exists" | "operation_conflict" | "path_conflict" => "conflict",
            "file_key_unavailable" | "protocol_timeout" => "waiting_for_executor",
            _ => "failed",
        }
    }
}

/// Result alias for hosted file operations.
pub type HostedResult<T> = std::result::Result<T, HostedFileError>;

pub(crate) fn refused<T>(code: &'static str) -> HostedResult<T> {
    Err(HostedFileError::Refused(code))
}

/// Executor codes the shared path/list/search decisions can answer. A code
/// outside this closed set is a protocol fault, never forwarded text.
const DECISION_CODES: &[&str] = &[
    "invalid_path",
    "protected_path",
    "regex_search_unavailable",
    "invalid_search_content_option",
    "invalid_search_glob",
    "invalid_search_limit",
    "invalid_search_mode",
    "invalid_search_path",
    "invalid_search_query",
    "invalid_search_target",
];

pub(crate) fn decision_code(code: &str) -> HostedFileError {
    DECISION_CODES
        .iter()
        .find(|known| **known == code)
        .map(|known| HostedFileError::Refused(known))
        .unwrap_or(HostedFileError::Refused("client_execution_failed"))
}

/// Run one shared hosted-file decision (`projectHostedPaths`/`List`/
/// `SearchPlan`, the same Rust rules the web Worker answers) and settle it like
/// `settleProjectFileDecision`: a `{fileError}`/`{searchError}` becomes a
/// refusal with that code.
pub(crate) fn decide(op: &str, input: &Value) -> HostedResult<Value> {
    let output = crate::web_projects::run_json(op, &input.to_string())
        .map_err(|_| HostedFileError::Core(Error::Protocol))?;
    let value: Value =
        serde_json::from_str(&output).map_err(|_| HostedFileError::Core(Error::Protocol))?;
    for key in ["fileError", "searchError"] {
        if let Some(code) = value.get(key).and_then(Value::as_str) {
            return Err(decision_code(code));
        }
    }
    if value.get("error").is_some() {
        return Err(HostedFileError::Core(Error::Protocol));
    }
    Ok(value)
}

/// `normalizeHostedProjectPath` through the shared `projectHostedPaths` rule.
///
/// # Errors
/// `invalid_path` / `protected_path`.
pub(crate) fn normalize_path(path: &Value) -> HostedResult<String> {
    let value = decide("projectHostedPaths", &json!({ "paths": [path] }))?;
    let result = &value["results"][0];
    if let Some(path) = result["path"].as_str() {
        return Ok(path.to_owned());
    }
    match result["code"].as_str() {
        Some(code) => Err(decision_code(code)),
        None => refused("protected_path"),
    }
}

/// Which deterministic identity of a hosted path to derive.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HostedIdentityKind {
    /// The embed id of the file.
    Embed,
    /// The `project_item_id` of the link row.
    Item,
}

/// `hostedProjectFileIdentity`: HMAC-SHA256(project key,
/// `JSON.stringify(["openmates-hosted-file-v1", kind, path])`), first 16 bytes
/// shaped as a UUIDv5 (version nibble 5, RFC 4122 variant). The keyed MAC hides
/// path guesses from the server and makes a second create of the same path
/// address the same embed. Cross-checked against TS output in the tests.
///
/// # Errors
/// `invalid_path`/`protected_path` for a path the hosted policy refuses.
pub fn hosted_file_identity(
    project_key: &[u8; 32],
    path: &str,
    kind: HostedIdentityKind,
) -> HostedResult<String> {
    let path = normalize_path(&Value::String(path.to_owned()))?;
    let kind = match kind {
        HostedIdentityKind::Embed => "embed",
        HostedIdentityKind::Item => "item",
    };
    keyed_uuid(
        project_key,
        &json!(["openmates-hosted-file-v1", kind, path]),
    )
}

/// HMAC-SHA256(project key, `JSON.stringify(parts)`), first 16 bytes shaped as
/// a UUIDv5 (version nibble 5, RFC 4122 variant). The shared shape of every
/// client-derived Project id: the server learns the id, never the parts.
///
/// # Errors
/// Only a JSON or MAC construction failure (cannot happen for string parts).
pub(crate) fn keyed_uuid(project_key: &[u8; 32], parts: &Value) -> HostedResult<String> {
    let message = Zeroizing::new(serde_json::to_string(parts).map_err(Error::from)?);
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(project_key)
        .map_err(|_| HostedFileError::Core(Error::Crypto))?;
    mac.update(message.as_bytes());
    let mut digest = [0u8; 16];
    digest.copy_from_slice(&mac.finalize().into_bytes()[..16]);
    digest[6] = (digest[6] & 15) | 0x50;
    digest[8] = (digest[8] & 63) | 0x80;
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    Ok(format!(
        "{}-{}-{}-{}-{}",
        &hex[..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..]
    ))
}

/// Embed `language` of a hosted file, derived from its path with the shared
/// `classifyRemotePreviewPath` table (`projectRemoteClassify`): `src/a.ts` is
/// `typescript`, `README.md` is `markdown`, an unknown extension is `text`.
///
/// # Errors
/// Only a protocol fault of the shared decision.
pub(crate) fn language_for_path(path: &str) -> HostedResult<String> {
    let value = decide("projectRemoteClassify", &json!({ "path": path }))?;
    Ok(value["language"]
        .as_str()
        .filter(|language| !language.is_empty())
        .unwrap_or("text")
        .to_owned())
}

/// `project_items` metadata `source` of a hosted file link.
pub(crate) const HOSTED_SOURCE: &str = "hosted_project_file";

/// Client-encrypts one text field under a Project or chat key.
pub(crate) fn seal(text: &str, key: &[u8; 32]) -> HostedResult<String> {
    Ok(crypto::server_fields::encrypt_text(text, key, &[])?)
}
