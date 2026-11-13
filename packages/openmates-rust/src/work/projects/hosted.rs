//! Hosted Project file writer (shared core; first used by the Rust CLI).
//!
//! Lists, reads, creates and patches OpenMates-stored Project files and
//! restores past versions, committing each change as one client-encrypted
//! revision through `commit_embed_revision`. Port of the web
//! `hostedProjectFileExecutor.ts` (+ `projectFileMutationProtocol.ts`,
//! `projectFilePatch.ts`); wire formats are unchanged. Specs:
//! `projects.files.hosted-ciphertext-commit`, `.expected-base`, `.exact-patch`,
//! `.chat-focus-required`, `projects.history.native-commits`. Embed adoption,
//! rename and delete follow `docs/plans/cloud-project-development/contracts/
//! project-embed-adoption.md` (P11).
use super::*;
use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

mod adopt;
mod adopt_plan;
mod api;
mod io;
mod job;
mod moves;
mod patch_repair;
mod policy;
mod restore;
pub use adopt::{AdoptEmbedKind, ProjectEmbedAdoptError};
pub(crate) use adopt_plan::TurnEmbed;
pub use api::{HostedApproval, HostedProposal};
pub use job::{HostedFileJob, HostedFileOperation};
pub use restore::ProjectCommitRestoreResult;

/// Largest hosted text file (UTF-8 bytes), also the mutation body limit.
pub(crate) const MAX_TEXT_BYTES: usize = 200 * 1024;
/// `project_items` metadata `source` of a hosted file link.
pub(crate) const HOSTED_SOURCE: &str = "hosted_project_file";
/// Revisions between client snapshot checkpoints in the history rows.
const SNAPSHOT_INTERVAL: u64 = 32;

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

fn refused<T>(code: &'static str) -> HostedResult<T> {
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

fn decision_code(code: &str) -> HostedFileError {
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

/// One hosted file link: the embed id and its normalized Project path.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct HostedFile {
    /// The linked embed (the file's revision chain).
    pub embed_id: String,
    /// The normalized Project path of the link.
    pub path: String,
    /// The server's `project_item_id` of the link row, when the listing named
    /// it; rename and delete address the link by this id.
    #[serde(skip)]
    pub(crate) item_id: Option<String>,
    /// The decrypted link metadata (`{path, source, …}`); a rename rewrites it
    /// with the new path and keeps every other field.
    #[serde(skip)]
    pub(crate) metadata: Value,
}

/// The decrypted current head of a hosted file. The embed key is zeroized on
/// drop; `content` keeps the decoded TOON field order so a rewrite keeps the
/// object layout the TS spread (`{...current, code}`) produces.
pub(crate) struct HostedHead {
    pub(crate) embed_key: Key,
    pub(crate) content: Vec<(String, Value)>,
    pub(crate) revision: u64,
    pub(crate) has_initial_history: bool,
}

impl HostedHead {
    fn field(&self, name: &str) -> Option<&Value> {
        self.content
            .iter()
            .find(|(key, _)| key == name)
            .map(|(_, v)| v)
    }
    /// TS `textContent`: `code ?? content`, a string of at most 200 KB with no NUL.
    pub(crate) fn text(&self) -> HostedResult<&str> {
        let value = match self.field("code") {
            Some(Value::Null) | None => self.field("content"),
            other => other,
        };
        match value.and_then(Value::as_str) {
            Some(text) if text.len() <= MAX_TEXT_BYTES && !text.contains('\0') => Ok(text),
            _ => refused("unsupported_file_content"),
        }
    }
}

/// Lowercase hex SHA-256 of the UTF-8 text (`projectFileContentHash`); the
/// `expected_base` of every update.
pub fn content_hash(content: &str) -> String {
    Sha256::digest(content.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
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

/// A create, exact-patch update, rename or delete (`ProjectFileMutation`).
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HostedFileMutation {
    /// The file operation.
    pub operation: HostedFileOperation,
    /// Idempotency key of the operation.
    pub operation_id: String,
    /// The Project path the operation addresses.
    pub path: String,
    /// SHA-256 of the text an update was made from (`None` otherwise).
    #[serde(default)]
    pub expected_base: Option<String>,
    /// Full text of a create.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    /// Exact one-file unified diff of an update.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub patch: Option<String>,
    /// Target path of a rename.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub new_path: Option<String>,
}

impl HostedFileMutation {
    /// `validateProjectFileMutation`: operation id `[A-Za-z0-9._:-]{1,128}`, a
    /// non-empty path of at most 4096 UTF-16 units without NUL, create carries
    /// content and a null base, update carries a 64-hex base and a non-empty
    /// patch, a rename carries only a non-empty `new_path`, a delete carries
    /// nothing beyond its path, and the body is at most 200 KB.
    ///
    /// # Errors
    /// `invalid_file_mutation` or `file_mutation_too_large`.
    pub fn validate(&self) -> HostedResult<()> {
        let id_ok = !self.operation_id.is_empty()
            && self.operation_id.len() <= 128
            && self
                .operation_id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b':' | b'-'));
        if !id_ok
            || self.path.is_empty()
            || self.path.encode_utf16().count() > 4096
            || self.path.contains('\0')
        {
            return refused("invalid_file_mutation");
        }
        let moving = matches!(
            self.operation,
            HostedFileOperation::RenameFile | HostedFileOperation::DeleteFile
        );
        if self.new_path.is_some() != (self.operation == HostedFileOperation::RenameFile) {
            return refused("invalid_file_mutation");
        }
        if moving {
            let clean =
                self.expected_base.is_none() && self.content.is_none() && self.patch.is_none();
            let target_ok = self.new_path.as_deref().is_none_or(|target| {
                !target.is_empty()
                    && target.encode_utf16().count() <= 4096
                    && !target.contains('\0')
            });
            return if clean && target_ok {
                Ok(())
            } else {
                refused("invalid_file_mutation")
            };
        }
        let body = match self.operation {
            HostedFileOperation::CreateFile => {
                match (&self.expected_base, &self.content, &self.patch) {
                    (None, Some(content), None) => content,
                    _ => return refused("invalid_file_mutation"),
                }
            }
            HostedFileOperation::UpdateFile => {
                match (&self.expected_base, &self.content, &self.patch) {
                    (Some(base), None, Some(patch))
                        if !patch.is_empty()
                            && base.len() == 64
                            && base
                                .bytes()
                                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) =>
                    {
                        patch
                    }
                    _ => return refused("invalid_file_mutation"),
                }
            }
            _ => return refused("invalid_file_mutation"),
        };
        if body.len() > MAX_TEXT_BYTES {
            return refused("file_mutation_too_large");
        }
        Ok(())
    }

    /// The committed proposal tuple. `new_path` appears only for a rename, so
    /// create/update digests stay byte-identical to the web executor.
    fn wire(&self) -> Value {
        let mut wire = json!({
            "operation": self.operation.wire(),
            "operation_id": self.operation_id,
            "path": self.path,
            "expected_base": self.expected_base,
            "content": self.content,
            "patch": self.patch,
        });
        if let Some(target) = &self.new_path {
            wire["new_path"] = json!(target);
        }
        wire
    }

    /// `projectFileMutationDigest`: the keyed proposal commitment the server
    /// binds approvals and revision receipts to (same tuple as the Workflow
    /// file writer, `openmates-project-file-proposal-v1`).
    ///
    /// # Errors
    /// The validation refusals, `invalid_file_mutation_identity` for an empty
    /// Project/chat id.
    pub fn digest(
        &self,
        project_key: &[u8; 32],
        project_id: &str,
        chat_id: &str,
    ) -> HostedResult<String> {
        self.validate()?;
        if project_id.is_empty() || chat_id.is_empty() {
            return refused("invalid_file_mutation_identity");
        }
        Ok(super::workflow_files::commitment(
            project_key,
            project_id,
            chat_id,
            &self.wire(),
        )?)
    }
}

/// Exact one-file patch apply (`applyProjectFilePatch` with `expectedPath`):
/// the shared core applier plus the header-path check.
///
/// # Errors
/// `invalid_patch` for any mismatch; the source is never partially changed.
pub fn apply_exact_patch(original: &str, diff: &str, path: &str) -> HostedResult<String> {
    let mut rows = diff.split('\n');
    let header = |row: Option<&str>, marker: &str| -> Option<String> {
        let rest = row?.strip_prefix(marker)?.strip_prefix(' ')?;
        let name = rest.split('\t').next().unwrap_or(rest);
        Some(
            name.strip_prefix("a/")
                .or_else(|| name.strip_prefix("b/"))
                .unwrap_or(name)
                .to_owned(),
        )
    };
    let old = header(rows.next(), "---");
    let new = header(rows.next(), "+++");
    if old.as_deref() != Some(path) || new.as_deref() != Some(path) {
        return refused("invalid_patch");
    }
    crate::embed_read::patch::apply_project_file_patch(original, diff)
        .map_err(|_| HostedFileError::Refused("invalid_patch"))
}

/// Apply an update diff authored by the assistant: as written when it is
/// exact, else after [`patch_repair::repair_patch`] rebuilt its hunk headers
/// from where its old lines verbatim occur. Returns the new text and the diff
/// to store, which always applies exactly to `original`.
///
/// # Errors
/// `invalid_patch` when the diff neither applies nor can be located
/// unambiguously; the source is never partially changed.
pub(crate) fn apply_update_patch(
    original: &str,
    diff: &str,
    path: &str,
) -> HostedResult<(String, String)> {
    match apply_exact_patch(original, diff, path) {
        Ok(next) => Ok((next, diff.to_owned())),
        Err(HostedFileError::Refused("invalid_patch")) => {
            let repaired = patch_repair::repair_patch(original, diff)
                .ok_or(HostedFileError::Refused("invalid_patch"))?;
            let next = apply_exact_patch(original, &repaired, path)?;
            Ok((next, repaired))
        }
        Err(error) => Err(error),
    }
}

/// A whole-file replacement diff from `old` to `next` that
/// [`apply_exact_patch`] applies exactly (restore and the Workflow writer).
pub fn replacement_patch(path: &str, old: &str, next: &str) -> String {
    super::workflow_files::replacement(path, old, next)
}

#[cfg(test)]
mod adopt_tests;
#[cfg(test)]
mod moves_tests;
#[cfg(test)]
mod patch_repair_tests;
#[cfg(test)]
mod tests;
