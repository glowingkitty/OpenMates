//! Restore of an earlier embed version as a new version (shared core; spec
//! `feature.embed-user-edits`, assertion `restore.creates-version`). Reads
//! version K with the existing version-content read, names K's image files
//! for a file-backed embed, and commits through the user-revision route with
//! action `restore` and `restored_from: K`. Nothing is deleted.
use super::{
    EmbedHead, EmbedRevisionOutcome, FileRef, RevisionResult, RevisionScope, UserRevisionError,
    UserRevisionRequest,
};
use crate::client::Client;
use crate::client::embed_updated_event::EmbedEventIdentity;
use crate::client::embed_write::payload::decode_object;
use crate::client::image_enhance::media_index_of;
use crate::error::Error;
use serde_json::Value;
use zeroize::Zeroizing;

/// Files and image index of version K's decrypted content: `None` for an
/// embed that is not an image (its content alone is the version), else K's
/// variant objects (they are in the embed's file union) and the index the
/// commit repoints.
///
/// # Errors
/// `Validation { code: "invalid_media_index" }` for an image whose content
/// lacks its files, nonce or Vault-wrapped key.
pub(crate) fn restore_files(content: &str) -> RevisionResult<Option<(Vec<FileRef>, Value)>> {
    let Some(fields) = decode_object(content) else {
        return Ok(None);
    };
    if fields.get("app_id").and_then(Value::as_str) != Some("images") {
        return Ok(None);
    }
    media_index_of(&fields)
        .map(Some)
        .ok_or(UserRevisionError::Validation {
            code: "invalid_media_index",
        })
}

/// The restore request for version `from` with its read plaintext.
///
/// # Errors
/// `Validation { code: "invalid_restored_from" }` unless `1 <= from < head`;
/// the errors of [`restore_files`].
pub(crate) fn restore_request(
    head: EmbedHead,
    scope: RevisionScope,
    from: i64,
    content: Zeroizing<String>,
) -> RevisionResult<UserRevisionRequest> {
    if !(1..head.version).contains(&from) {
        return Err(UserRevisionError::Validation {
            code: "invalid_restored_from",
        });
    }
    let files = restore_files(&content)?;
    Ok(UserRevisionRequest::restore(
        head, scope, from, content, None, files,
    ))
}

impl Client {
    /// Restore version `from` of an embed as its next version: the new
    /// version equals version `from` (content and, for images, its files);
    /// every version stays in the history. `head` is the cached head row,
    /// `scope` where the user restored it. Version `from` is read with
    /// [`Self::embed_version_content`] (Personal account). The text preview of
    /// the head is left unchanged.
    ///
    /// # Errors
    /// `Validation` for `from` outside `1..head`, the read's errors as
    /// `Transport`, and the errors of [`Self::commit_embed_user_revision`]
    /// (`restore_source_missing`, `VersionConflict`, ...).
    pub async fn restore_embed_version(
        &mut self,
        head: EmbedHead,
        scope: RevisionScope,
        from: i64,
        identity: Option<EmbedEventIdentity>,
    ) -> RevisionResult<EmbedRevisionOutcome> {
        if !(1..head.version).contains(&from) {
            return Err(UserRevisionError::Validation {
                code: "invalid_restored_from",
            });
        }
        let mut read = self.embed_version_content(&head.embed_id, from).await?;
        let content = match read.get_mut("content") {
            Some(Value::String(text)) => Zeroizing::new(std::mem::take(text)),
            _ => return Err(Error::Protocol.into()),
        };
        drop(read);
        let request = restore_request(head, scope, from, content)?;
        self.commit_embed_user_revision(request, identity).await
    }
}

#[cfg(test)]
#[path = "embed_user_restore_tests.rs"]
mod tests;
