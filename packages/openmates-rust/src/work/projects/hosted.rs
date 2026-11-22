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
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

mod api;
mod apply_changes;
pub(crate) mod io;
pub(crate) mod job;
mod moves;
mod patch_repair;
mod policy;
mod restore;
mod restore_user;
use super::hosted_base::{
    HOSTED_SOURCE, HostedFileError, HostedIdentityKind, HostedResult, decide, hosted_file_identity,
    language_for_path, normalize_path, refused, seal,
};
pub use api::{HostedApproval, HostedProposal};
pub use job::{HostedFileJob, HostedFileOperation};
pub(crate) use apply_changes::applied_change_mutations;
pub use restore::ProjectCommitRestoreResult;

/// Largest hosted text file (UTF-8 bytes), also the mutation body limit.
pub(crate) const MAX_TEXT_BYTES: usize = 200 * 1024;
/// Revisions between client snapshot checkpoints in the history rows.
const SNAPSHOT_INTERVAL: u64 = 32;

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
mod apply_changes_tests;
#[cfg(test)]
mod moves_tests;
#[cfg(test)]
mod patch_repair_tests;
#[cfg(test)]
mod tests;
