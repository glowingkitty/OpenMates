//! Read-only projection of the raw chat and message rows the client already
//! holds into the extra view-model facts (`ChatRowMetadata`,
//! `MessageMetadata`) that shells show beside the list title and message text:
//! icon, sub-chat and budget fields, timestamps, draft preview, model name,
//! queue state and per-message PII mappings. Shared client core; feeds
//! `view_model` (plan `apple-client-core-migration`, a4 lane 0). No network,
//! no cache or protocol change: every value comes from rows already in memory.
//!
//! Field rules match the saved-chat read metadata (`saved_chat_read::metadata`):
//! absent or null is `None`, a present value of the wrong type is
//! `Error::Protocol`, and optional encrypted display fields that fail
//! authentication are `None` (as the maintained TS raw reader).
use super::{
    Client,
    saved_chat_read::metadata::{boolean, projection_encrypted, string, timestamp, unsigned},
    sync::{decrypt_optional, draft_only},
};
use crate::{
    crypto::Key,
    error::{Error, Result},
    view_model::{ChatRowMetadata, MessageMetadata, PiiMapping},
};
use serde_json::Value;
use std::collections::BTreeMap;

/// Message id of a raw row: the first non-empty of `client_message_id`,
/// `message_id`, `id` (the decoder's rule, so ids match the decoded messages).
fn row_message_id(row: &Value) -> Option<&str> {
    ["client_message_id", "message_id", "id"]
        .into_iter()
        .filter_map(|field| row.get(field).and_then(Value::as_str))
        .find(|id| !id.is_empty())
}

/// Per-message PII mappings of one row (`encrypted_pii_mappings`, a JSON array
/// of `{placeholder, original, type}` encrypted with the chat key). Entries
/// without string `placeholder` and `original` are skipped, exactly as
/// `privacy::restore` skips them; a missing `type` is empty.
fn pii_mappings(row: &Value, key: &[u8; 32]) -> Result<Vec<PiiMapping>> {
    let plain = zeroize::Zeroizing::new(decrypt_optional(row, "encrypted_pii_mappings", key)?);
    if plain.is_empty() {
        return Ok(Vec::new());
    }
    let values: Vec<Value> = serde_json::from_str(&plain)?;
    Ok(values
        .iter()
        .filter_map(|value| {
            let placeholder = value.get("placeholder").and_then(Value::as_str)?;
            let original = value.get("original").and_then(Value::as_str)?;
            Some(PiiMapping {
                placeholder: placeholder.to_owned(),
                original: original.to_owned(),
                kind: value
                    .get("type")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_owned(),
            })
        })
        .collect())
}

/// The metadata of one raw message row decrypted with its chat key.
///
/// # Errors
/// `Protocol` for a mistyped plain field or malformed PII mapping JSON;
/// `Crypto` when the PII mappings fail authentication (the window decoder
/// refuses the same row).
pub(crate) fn message_metadata(row: &Value, key: &[u8; 32]) -> Result<MessageMetadata> {
    Ok(MessageMetadata {
        created_at: timestamp(row, "created_at")?,
        updated_at: timestamp(row, "updated_at")?,
        app_id: string(row, "app_id")?.filter(|id| !id.is_empty()),
        server_message_id: string(row, "message_id")?,
        client_message_id: string(row, "client_message_id")?,
        user_message_id: string(row, "user_message_id")?,
        stored_status: string(row, "status")?,
        model_name: projection_encrypted(row, "encrypted_model_name", key)?,
        category: projection_encrypted(row, "encrypted_category", key)?,
        has_thinking: boolean(row, "has_thinking")?,
        thinking_token_count: unsigned(row, "thinking_token_count")?,
        queue_revision: unsigned(row, "queue_revision")?,
        queue_mode: string(row, "queue_mode")?,
        queue_dispatch_status: string(row, "queue_dispatch_status")?,
        queue_dispatch_mode: string(row, "queue_dispatch_mode")?,
        queue_dispatch_task_id: string(row, "queue_dispatch_task_id")?,
        pii_mappings: pii_mappings(row, key)?,
    })
}

/// The plain (not encrypted) facts of a chat row.
fn plain_row_metadata(row: &Value) -> Result<ChatRowMetadata> {
    let settings = row
        .get("sub_chat_settings")
        .filter(|value| !value.is_null());
    if settings.is_some_and(|value| !value.is_object()) {
        return Err(Error::Protocol);
    }
    let setting = |name: &str| settings.map_or(Ok(None), |value| boolean(value, name));
    Ok(ChatRowMetadata {
        is_shared_by_others: boolean(row, "is_shared_by_others")?,
        last_visible_message_id: string(row, "last_visible_message_id")?
            .filter(|id| !id.is_empty()),
        app_id: string(row, "app_id")?.filter(|id| !id.is_empty()),
        sub_chat_wait_for_completion: setting("wait_for_completion")?,
        sub_chat_report_trigger: settings
            .map_or(Ok(None), |value| string(value, "report_trigger"))?,
        parent_id: string(row, "parent_id")?.filter(|id| !id.is_empty()),
        is_sub_chat: boolean(row, "is_sub_chat")?,
        is_shared: boolean(row, "is_shared")?,
        is_private: boolean(row, "is_private")?,
        is_hidden: boolean(row, "is_hidden")?,
        last_message_at: timestamp(row, "last_message_timestamp")?,
        last_edited_at: timestamp(row, "last_edited_overall_timestamp")?,
        budget_limit: unsigned(row, "budget_limit")?,
        budget_spent: unsigned(row, "budget_spent")?,
        draft_v: unsigned(row, "draft_v")?,
        ..ChatRowMetadata::default()
    })
}

impl Client {
    /// Account chat count the server reported with the last recent-chats
    /// phase of this scope, `None` until one arrived (or after a scope
    /// switch). Shells use it to decide whether more chats exist than listed.
    pub fn chat_total_count(&self) -> Option<u64> {
        self.chat_total_count
    }

    /// The chat key of a held row, or `None` when the current scope cannot
    /// read it (`Forbidden`: locked row; a personal draft-only row has none).
    fn projection_key(&self, row: &Value) -> Result<Option<Key>> {
        if draft_only(row) {
            return Ok(None);
        }
        let wrapping = self.cached_wrapping_key()?;
        match self.chat_key(row, &wrapping) {
            Ok(key) => Ok(Some(key)),
            Err(Error::Forbidden) => Ok(None),
            Err(error) => Err(error),
        }
    }

    /// Extra list facts of chat `id` from its held row; all `None` for an id
    /// without a row (saved-item and home entries). Encrypted fields (icon,
    /// active focus) need the chat key and stay `None` for a locked row. The
    /// draft preview is decrypted with the native master key in personal
    /// scope only; browser credentials without an extractable master key
    /// (`Unavailable`) have no preview. `team_id` is the active team: in team
    /// scope the key selection refuses rows of another team.
    ///
    /// # Errors
    /// `Protocol` for a mistyped plain field; key selection and credential
    /// errors other than `Forbidden`.
    pub(crate) fn chat_row_metadata(&self, id: &str) -> Result<ChatRowMetadata> {
        let Some(row) = self.chats.get(id) else {
            return Ok(ChatRowMetadata::default());
        };
        let mut metadata = plain_row_metadata(row)?;
        let team = self.team()?.map(str::to_owned);
        if let Some(key) = self.projection_key(row)? {
            metadata.icon = projection_encrypted(row, "encrypted_icon", &key)?;
            metadata.active_focus_id =
                projection_encrypted(row, "encrypted_active_focus_id", &key)?;
        }
        let has_draft = row
            .get("encrypted_draft_md")
            .and_then(Value::as_str)
            .is_some_and(|draft| !draft.is_empty());
        if has_draft && team.is_none() {
            match self.native_master_key() {
                Ok(master) => {
                    metadata.draft_preview =
                        projection_encrypted(row, "encrypted_draft_preview", master)?;
                }
                Err(Error::Unavailable { .. }) => {}
                Err(error) => return Err(error),
            }
        }
        metadata.team_id = team;
        Ok(metadata)
    }

    /// Message metadata by message id for every encrypted row the client
    /// holds for `chat_id` (full history, the sync message window, the
    /// selected first page; the first row found for an id wins). Empty when
    /// the chat has no row or its key is not readable in this scope.
    ///
    /// # Errors
    /// As [`message_metadata`]; `Protocol` for a stored row that is not JSON.
    pub(crate) fn message_metadata_by_id(
        &self,
        chat_id: &str,
    ) -> Result<BTreeMap<String, MessageMetadata>> {
        let mut found = BTreeMap::new();
        let Some(key) = self
            .chats
            .get(chat_id)
            .map(|row| self.projection_key(row))
            .transpose()?
            .flatten()
        else {
            return Ok(found);
        };
        let history = self.history.get(chat_id).into_iter().flatten();
        let window = self
            .sync_message_windows
            .get(chat_id)
            .into_iter()
            .flat_map(|window| window.messages.iter());
        let first = self
            .selected_first_pages
            .get(chat_id)
            .into_iter()
            .flat_map(|page| page.messages.iter());
        for raw in history.chain(window).chain(first) {
            // History rows may be stored as JSON strings (legacy snapshots);
            // they hold ciphertext only, so the parsed copy needs no wipe.
            let parsed;
            let row = match raw.as_str() {
                Some(text) => {
                    parsed = serde_json::from_str::<Value>(text).map_err(|_| Error::Protocol)?;
                    &parsed
                }
                None => raw,
            };
            let Some(id) = row_message_id(row) else {
                continue;
            };
            if found.contains_key(id) {
                continue;
            }
            found.insert(id.to_owned(), message_metadata(row, &key)?);
        }
        Ok(found)
    }
}

#[cfg(test)]
#[path = "view_projection_tests.rs"]
mod tests;
