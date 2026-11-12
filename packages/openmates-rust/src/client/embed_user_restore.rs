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
    /// The current server head of `embed_id` for a user edit: read fresh with
    /// its key wrappers (kept in the client cache, so the commit can open and
    /// re-wrap the embed key), plus the id of the embed's chat when this
    /// device has that chat cached. Used by the CLI, which keeps no embed
    /// store, and by the web Worker before Enhance, its save and restore (a
    /// freshly opened embed's key is not in the client cache yet). Pass the
    /// head to [`Self::restore_embed_version`] or [`Client::enhance_image`].
    ///
    /// # Errors
    /// The read's errors as `Transport`; `Validation { code: "invalid_head" }`
    /// for a malformed head row.
    pub async fn embed_user_edit_head(
        &mut self,
        embed_id: &str,
    ) -> RevisionResult<(EmbedHead, Option<String>)> {
        self.require_session()?;
        self.embed_detail(embed_id).await?;
        let row = self.embeds.get(embed_id).ok_or(Error::Protocol)?;
        let now_seconds = i64::try_from(crate::client::now_ms() / 1000).unwrap_or(i64::MAX);
        let head = EmbedHead::from_cached_row(embed_id, row, now_seconds)?;
        let chat_id = head.hashed_chat_id.as_deref().and_then(|hash| {
            self.chats
                .keys()
                .find(|id| crate::client::sha256(id) == hash)
                .cloned()
        });
        Ok((head, chat_id))
    }

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
