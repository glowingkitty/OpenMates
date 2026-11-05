//! Bounded saved-chat reads for CLI/TUI and direct SDK callers.
//! This is a fresh read, never complete-history or cache/recovery authority.
//! At most five twenty-row pages; oversized ciphertext requires explicit exact IO.
use super::plaintext::{Plain, replace_text};
use super::{
    message_window::{
        ChatMessageWindow, MessageWindowCursor, MessageWindowDirection, MessageWindowOptions,
    },
    sync::{decode_chat_message, decrypt_optional},
    *,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};
#[path = "saved_chat_read_metadata.rs"]
pub(super) mod metadata;
/// Encode one exact-resource path segment, once. Query form encoding uses `+`
/// for spaces and must not be reused here. The caller separately refuses dot
/// segments; the backend's decoded-slash routing limitation remains explicit.
fn exact_message_segment(value: &str) -> String {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut encoded = String::new();
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~') {
            encoded.push(char::from(byte));
        } else {
            encoded.push('%');
            encoded.push(char::from(HEX[usize::from(byte >> 4)]));
            encoded.push(char::from(HEX[usize::from(byte & 15)]));
        }
    }
    encoded
}
/// Explicit metadata from the authorized selected chat. Missing values are
/// unknown, never synthetic display fallbacks. This contains no keys/ciphertext.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SavedChatReadMetadata {
    pub id: String,
    pub title: Option<String>,
    pub summary: Option<String>,
    pub category: Option<String>,
    pub slug: Option<String>,
    pub active_focus_id: Option<String>,
    pub created_at: Option<i64>,
    pub last_edited_at: Option<i64>,
    pub metadata_updated_at: Option<i64>,
    pub parent_id: Option<String>,
    pub is_sub_chat: Option<bool>,
    pub is_hidden: Option<bool>,
    pub pinned: Option<bool>,
    pub chat_visibility: Option<String>,
    pub participant_user_hashes: Option<Vec<String>>,
    pub has_draft: Option<bool>,
    pub follow_up_suggestions: Option<Vec<String>>,
}
/// One-to-one source metadata for window.chat.messages, joined by canonical id.
/// raw_status is source data; it is never a transport/display status assertion.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SavedChatMessageMetadata {
    pub id: String,
    pub storage_id: Option<String>,
    pub source_message_id: Option<String>,
    pub client_message_id: Option<String>,
    pub chat_id: String,
    pub created_at: i64,
    pub raw_status: Option<String>,
    pub sender_name: Option<String>,
    pub category: Option<String>,
    pub model_name: Option<String>,
    pub thinking_signature: Option<String>,
    pub has_thinking: Option<bool>,
    pub thinking_token_count: Option<u64>,
    pub hashed_user_id: Option<String>,
    pub user_message_id: Option<String>,
    pub key_version: Option<u64>,
    pub queue_revision: Option<u64>,
    pub queue_mode: Option<String>,
    pub queue_dispatch_status: Option<String>,
    pub queue_dispatch_mode: Option<String>,
    pub queue_dispatch_task_id: Option<String>,
    /// The message window route does not attest a complete embed inventory.
    pub embed_ids: Option<Vec<String>>,
}
const MAX_ROWS: usize = 100;
const MAX_PAGES: usize = 5;
const MAX_PAGE_BYTES: usize = 256 * 1024;
pub(super) const MAX_EXACT_BYTES: usize = 2 * 1024 * 1024;
pub(super) const MAX_OUTPUT_BYTES: usize = 4 * 1024 * 1024;
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SavedChatContentMode {
    /// Stored decrypted text and original per-message mappings, for JSON/raw.
    #[default]
    Stored,
    /// Restore only known user mappings in this bounded read; unknowns stay literal.
    PageLocal,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SavedChatReadOptions {
    #[serde(default = "default_limit")]
    pub limit: usize,
    /// Shared IO budget; browser callers select one page before any request.
    #[serde(default = "default_pages")]
    pub max_pages: usize,
    /// Absent means latest; otherwise read strictly before this live selector.
    #[serde(default)]
    pub before: Option<MessageWindowCursor>,
    /// Continue strictly after a live selector; incompatible with before/anchor.
    #[serde(default)]
    pub after: Option<MessageWindowCursor>,
    /// Center one canonical <=20-row page. Paging continues explicitly afterward.
    #[serde(default)]
    pub anchor_message_id: Option<String>,
    #[serde(default = "default_compression")]
    pub respect_compression_boundary: bool,
    #[serde(default)]
    pub content_mode: SavedChatContentMode,
}
fn default_pages() -> usize {
    5
}
fn default_limit() -> usize {
    30
}
fn default_compression() -> bool {
    true
}
impl Default for SavedChatReadOptions {
    fn default() -> Self {
        Self {
            limit: 30,
            max_pages: 5,
            before: None,
            after: None,
            anchor_message_id: None,
            respect_compression_boundary: true,
            content_mode: SavedChatContentMode::Stored,
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SavedChatReadPage {
    pub chat: Chat,
    pub has_more_before: bool,
    pub has_more_after: bool,
    pub anchor_found: bool,
    pub start_cursor: Option<MessageWindowCursor>,
    pub end_cursor: Option<MessageWindowCursor>,
    pub server_message_count: Option<u64>,
    pub messages_version: Option<u64>,
    pub oversized_message: bool,
    pub oversized_message_cursor: Option<MessageWindowCursor>,
    pub payload_bytes: usize,
    /// Stored or page_local, explicitly chosen for this new saved-read DTO.
    pub pii_restoration: String,
    /// Always false: even a terminal page does not replace complete cache state.
    pub history_complete: bool,
}
impl From<ChatMessageWindow> for SavedChatReadPage {
    fn from(page: ChatMessageWindow) -> Self {
        Self {
            chat: page.chat,
            has_more_before: page.has_more_before,
            has_more_after: page.has_more_after,
            anchor_found: page.anchor_found,
            start_cursor: page.start_cursor,
            end_cursor: page.end_cursor,
            server_message_count: page.server_message_count,
            messages_version: page.messages_version,
            oversized_message: page.oversized_message,
            oversized_message_cursor: page.oversized_message_cursor,
            payload_bytes: page.payload_bytes,
            pii_restoration: page.pii_restoration,
            history_complete: page.history_complete,
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SavedChatRead {
    #[serde(flatten)]
    pub window: SavedChatReadPage,
    pub chat_metadata: SavedChatReadMetadata,
    pub message_metadata: Vec<SavedChatMessageMetadata>,
    /// Present only when a loaded row carried an encrypted mapping field.
    /// Raw mappings are preserved even on non-user rows; only user rows restore.
    pub pii_mappings_by_message_id: BTreeMap<String, Vec<Value>>,
    pub content_mode: SavedChatContentMode,
    pub pages_read: usize,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SavedChatExactOptions {
    pub cursor: MessageWindowCursor,
    #[serde(default)]
    pub content_mode: SavedChatContentMode,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SavedChatExactMessage {
    pub message: Message,
    pub chat_metadata: SavedChatReadMetadata,
    pub message_metadata: SavedChatMessageMetadata,
    pub pii_mappings: Option<Vec<Value>>,
    pub content_mode: SavedChatContentMode,
    pub pii_restoration: String,
    pub payload_bytes: usize,
    pub history_complete: bool,
}
fn restoration(mode: SavedChatContentMode) -> &'static str {
    match mode {
        SavedChatContentMode::Stored => "stored",
        SavedChatContentMode::PageLocal => "page_local",
    }
}
fn output_bound<T: Serialize>(value: &T) -> Result<()> {
    if crate::client::monitor::cached_view::bounded_bytes(value, MAX_OUTPUT_BYTES).is_none() {
        return Err(Error::Invalid(
            "Saved chat output exceeds the supported size.",
        ));
    }
    Ok(())
}
/// Restricting final-output assertion for a completed saved-chat read. This
/// carries no authentication, cursor, cache-write or durability authority and
/// intentionally supports the read's existing Personal/Team scope.
/// No Clone/Debug/serialization: the retained exact crypto/request scope is
/// restrictive evidence, never a new authentication or durability grant.
pub struct SavedChatReadAdmission {
    scope: String,
    owner: String,
    session_id: String,
    principal: Option<String>,
    crypto_scope: super::sync_capability::AsyncCryptoScope,
}
fn saved_read_principal(user: &Value) -> Option<&str> {
    user["id"]
        .as_str()
        .filter(|value| !value.is_empty())
        .or_else(|| user["user_id"].as_str().filter(|value| !value.is_empty()))
}
impl SavedChatReadAdmission {
    /// Restrictive queued-output check on this ORIGINAL captured master resource.
    /// Adapters must also retain owner/request/denial/private fences and perform
    /// the full check under their existing Client lock before encoding.
    pub fn ensure_resource_current(&self) -> Result<()> {
        self.crypto_scope.ensure_resource_current()
    }
    // Original captured operation only; no current read/publication authority.
    pub(super) fn check_original_operation_negative(&self) -> Result<()> {
        self.crypto_scope.check_original_operation_negative()
    }
    pub fn check(&self, client: &Client) -> Result<()> {
        client.verify_private_operation()?;
        self.check_after_private_gate(client)
    }
    // Callback-free original negative evidence. Publication guards call this
    // after their final caller gate; invoking the gate again would reopen it.
    pub(super) fn check_after_private_gate(&self, client: &Client) -> Result<()> {
        client.saved_read_current(&self.scope)?;
        let session = client.require_credentials()?;
        if session.hashed_email.as_str() != self.owner.as_str()
            || session.session_id.as_str() != self.session_id.as_str()
            || saved_read_principal(&client.user) != self.principal.as_deref()
        {
            return Err(Error::Cancelled);
        }
        client.require_canonical_read_profile()?;
        self.crypto_scope.check(client)?;
        Ok(())
    }
}
impl Client {
    /// Capture only after the authorized read completes, then check against the
    /// current locked Client at the caller's last plaintext publication boundary.
    pub fn saved_chat_read_admission(&self) -> Result<SavedChatReadAdmission> {
        self.capture_saved_read_admission()
    }
    // Restrictive original context for the full-read metadata entry. It creates
    // no read authority; the actual full authorized read must still complete.
    pub(super) fn original_full_chat_read_admission(&self) -> Result<SavedChatReadAdmission> {
        self.capture_saved_read_admission()
    }
    fn capture_saved_read_admission(&self) -> Result<SavedChatReadAdmission> {
        self.verify_private_operation()?;
        self.require_canonical_read_profile()?;
        let scope = self.message_window_scope()?;
        self.saved_read_current(&scope)?;
        let session = self.require_credentials()?;
        Ok(SavedChatReadAdmission {
            scope,
            owner: session.hashed_email.clone(),
            session_id: session.session_id.clone(),
            principal: saved_read_principal(&self.user).map(str::to_owned),
            crypto_scope: super::sync_capability::AsyncCryptoScope::begin(self)?,
        })
    }
}
impl Client {
    fn saved_read_current(&self, scope: &str) -> Result<()> {
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if self.message_window_scope()? != scope {
            return Err(Error::Conflict);
        }
        Ok(())
    }
    /// Read latest 30 by default, or at most 100. Byte/request limits can return
    /// fewer rows with hasMoreBefore. Never interprets terminal as complete.
    /// No implicit all-history or exact-row fallback, cache or selection mutation.
    pub async fn saved_chat_read(
        &mut self,
        id: &str,
        options: SavedChatReadOptions,
    ) -> Result<SavedChatRead> {
        crate::platform::time::timeout(
            std::time::Duration::from_secs(45),
            self.saved_chat_read_inner(id, options),
        )
        .await
        .map_err(|_| Error::Offline)?
    }
    async fn saved_chat_read_inner(
        &mut self,
        id: &str,
        options: SavedChatReadOptions,
    ) -> Result<SavedChatRead> {
        uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        if !(1..=MAX_ROWS).contains(&options.limit) {
            return Err(Error::Invalid(
                "Saved chat read limit must be between 1 and 100.",
            ));
        }
        if !(1..=MAX_PAGES).contains(&options.max_pages) {
            return Err(Error::Invalid(
                "Saved read page budget must be between 1 and 5.",
            ));
        }
        self.require_canonical_read_profile()?;
        let crypto_scope = super::sync_capability::AsyncCryptoScope::begin(self)?;
        let scope = self.message_window_scope()?;
        self.saved_read_current(&scope)?;
        if usize::from(options.before.is_some())
            + usize::from(options.after.is_some())
            + usize::from(options.anchor_message_id.is_some())
            > 1
        {
            return Err(Error::Invalid("Choose one saved read selector."));
        }
        let forward = options.after.is_some();
        let around = options.anchor_message_id.is_some();
        let mut selector = options.before.clone().or_else(|| options.after.clone());
        let mut direction = if around {
            MessageWindowDirection::Around
        } else if forward {
            MessageWindowDirection::After
        } else if selector.is_some() {
            MessageWindowDirection::Before
        } else {
            MessageWindowDirection::Latest
        };
        let mut aggregate: Option<Plain<SavedChatRead>> = None;
        let mut stamp = None;
        let mut seen = HashSet::new();
        for _ in 0..options.max_pages {
            self.saved_read_current(&scope)?;
            let count = aggregate
                .as_ref()
                .map_or(0, |all| all.window.chat.messages.len());
            let page_options = MessageWindowOptions {
                direction,
                limit: (options.limit - count).min(20),
                cursor: selector.clone(),
                anchor_message_id: options.anchor_message_id.clone(),
                respect_compression_boundary: options.respect_compression_boundary,
            };
            let mut data = Plain::new(self.read_message_page(id, page_options, true).await?);
            self.saved_read_current(&scope)?;
            if stamp
                .as_ref()
                .is_some_and(|value| value != &data.metadata_stamp)
            {
                return Err(Error::Conflict);
            }
            stamp = Some(std::mem::take(&mut data.metadata_stamp));
            if data.chat_metadata.is_none() {
                return Err(Error::Protocol);
            }
            let data = data.into_inner();
            let mut page = Plain::new(SavedChatRead {
                window: data.window.into(),
                chat_metadata: data.chat_metadata.expect("checked saved metadata"),
                message_metadata: data.message_metadata,
                pii_mappings_by_message_id: data.mappings,
                content_mode: options.content_mode,
                pages_read: 1,
            });
            if page.window.payload_bytes > MAX_PAGE_BYTES {
                return Err(Error::Protocol);
            }
            for message in &page.window.chat.messages {
                if !seen.insert(message.id.clone()) {
                    return Err(Error::Protocol);
                }
            }
            selector = if forward {
                page.window.end_cursor.clone()
            } else {
                page.window.start_cursor.clone()
            };
            match &mut aggregate {
                None => {
                    aggregate = Some(page);
                }
                Some(all) => {
                    all.pages_read += 1;
                    all.window.payload_bytes = all
                        .window
                        .payload_bytes
                        .checked_add(page.window.payload_bytes)
                        .ok_or(Error::Protocol)?;
                    if all.window.payload_bytes > MAX_PAGES * MAX_PAGE_BYTES {
                        return Err(Error::Protocol);
                    }
                    let mut messages = std::mem::take(&mut page.window.chat.messages);
                    let mut details = std::mem::take(&mut page.message_metadata);
                    if forward {
                        all.window.chat.messages.append(&mut messages);
                        all.message_metadata.append(&mut details);
                        all.window.has_more_after = page.window.has_more_after;
                        if page.window.end_cursor.is_some() {
                            all.window.end_cursor = page.window.end_cursor.take();
                        }
                    } else {
                        messages.append(&mut all.window.chat.messages);
                        all.window.chat.messages = messages;
                        details.append(&mut all.message_metadata);
                        all.message_metadata = details;
                        all.window.has_more_before = page.window.has_more_before;
                        if page.window.start_cursor.is_some() {
                            all.window.start_cursor = page.window.start_cursor.take();
                        }
                    }
                    all.window.oversized_message = page.window.oversized_message;
                    all.window.oversized_message_cursor =
                        page.window.oversized_message_cursor.take();
                    all.pii_mappings_by_message_id
                        .append(&mut page.pii_mappings_by_message_id);
                }
            }
            let all = aggregate.as_ref().ok_or(Error::Protocol)?;
            let more = if forward {
                all.window.has_more_after
            } else {
                all.window.has_more_before
            };
            if around
                || all.window.chat.messages.len() >= options.limit
                || !more
                || all.window.oversized_message
                || selector.is_none()
            {
                break;
            }
            direction = if forward {
                MessageWindowDirection::After
            } else {
                MessageWindowDirection::Before
            };
        }
        let mut all = aggregate.ok_or(Error::Protocol)?;
        if options.content_mode == SavedChatContentMode::PageLocal {
            let mappings = Plain::new(
                all.window
                    .chat
                    .messages
                    .iter()
                    .filter(|m| m.role == "user")
                    .filter_map(|m| all.pii_mappings_by_message_id.get(&m.id))
                    .flatten()
                    .cloned()
                    .collect::<Vec<Value>>(),
            );
            let mut restored_bytes = 0usize;
            for message in &mut all.window.chat.messages {
                let restored = crate::privacy::restore_page(&message.content, &mappings)?;
                replace_text(&mut message.content, restored);
                let restored = crate::privacy::restore_page(&message.thinking, &mappings)?;
                replace_text(&mut message.thinking, restored);
                restored_bytes = restored_bytes
                    .checked_add(message.content.len())
                    .and_then(|n| n.checked_add(message.thinking.len()))
                    .ok_or(Error::Protocol)?;
                if restored_bytes > MAX_OUTPUT_BYTES {
                    return Err(Error::Invalid(
                        "Saved chat output exceeds the supported size.",
                    ));
                }
            }
        }
        all.window.pii_restoration = restoration(options.content_mode).into();
        crypto_scope.check(self)?;
        self.require_canonical_read_profile()?;
        output_bound(&*all)?;
        self.saved_read_current(&scope)?;
        Ok(all.into_inner())
    }
    /// Explicit one-row fallback from an oversized cursor, <=2 MiB ciphertext.
    /// Metadata/key authorization is refreshed; no ambient account or cache IO.
    pub async fn saved_chat_exact_message(
        &mut self,
        id: &str,
        options: SavedChatExactOptions,
    ) -> Result<SavedChatExactMessage> {
        crate::platform::time::timeout(
            std::time::Duration::from_secs(45),
            self.saved_chat_exact_inner(id, options),
        )
        .await
        .map_err(|_| Error::Offline)?
    }
    async fn saved_chat_exact_inner(
        &mut self,
        id: &str,
        options: SavedChatExactOptions,
    ) -> Result<SavedChatExactMessage> {
        uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        if self.is_ephemeral_chat(id) {
            return Err(Error::Invalid("Volatile chat history has no server page."));
        }
        self.require_canonical_read_profile()?;
        let crypto_scope = super::sync_capability::AsyncCryptoScope::begin(self)?;
        let scope = self.message_window_scope()?;
        self.saved_read_current(&scope)?;
        // Reuse the cursor validator without exposing a new authority format.
        let selector = MessageWindowOptions {
            direction: MessageWindowDirection::Before,
            cursor: Some(options.cursor.clone()),
            ..Default::default()
        };
        selector.validate(id, &scope)?;
        // Keep the pre-existing exact-route refusal for URL dot-only segments.
        // Window query selectors remain opaque; this path cannot name dot IDs
        // without URL normalization changing the selected resource.
        if matches!(options.cursor.message_id.as_str(), "." | "..") {
            return Err(Error::Invalid("Invalid exact message route selector."));
        }
        let metadata = self
            .request_chat_metadata(id)
            .await?
            .ok_or(Error::Forbidden)?;
        self.saved_read_current(&scope)?;
        let rows = metadata["chats"].as_array().ok_or(Error::Protocol)?;
        if rows.len() != 1 || text(&rows[0], "id") != id {
            return Err(Error::Forbidden);
        }
        let row = &rows[0];
        let wrapping = self.wrapping_capability().await?;
        if text(row, "chat_visibility") == "direct" {
            self.load_direct_identity().await?;
        }
        let key = self.chat_key_with_capability(row, &wrapping).await?;
        let path = self.scoped(&format!(
            "/v1/chats/{}/messages/{}",
            segment(id),
            exact_message_segment(&options.cursor.message_id)
        ))?;
        let response = self.request(Method::GET, &path, None).await?;
        self.saved_read_current(&scope)?;
        let raw = response
            .get("message")
            .filter(|v| v.is_object())
            .ok_or(Error::Protocol)?;
        let bytes = crate::client::monitor::cached_view::bounded_bytes(raw,usize::MAX).ok_or(Error::Protocol)?;
        if bytes > MAX_EXACT_BYTES {
            return Err(Error::Protocol);
        }
        super::message_window::server_message_id(raw)?;
        let (raw, message) = decode_chat_message(raw, id, &key, &mut HashSet::new())?;
        let mut message = Plain::new(message);
        if message.id != options.cursor.message_id
            || raw["created_at"].as_i64() != Some(options.cursor.created_at)
        {
            return Err(Error::Protocol);
        }
        let value =
            zeroize::Zeroizing::new(decrypt_optional(&raw, "encrypted_pii_mappings", &key)?);
        let mappings = Plain::new(
            match raw.get("encrypted_pii_mappings").and_then(Value::as_str) {
                None => None,
                Some("") => Some(vec![]),
                Some(_) => Some(serde_json::from_str::<Vec<Value>>(&value)?),
            },
        );
        if options.content_mode == SavedChatContentMode::PageLocal {
            let restore_maps = if message.role == "user" {
                mappings.as_deref().unwrap_or(&[])
            } else {
                &[]
            };
            let restored = crate::privacy::restore_page(&message.content, restore_maps)?;
            replace_text(&mut message.content, restored);
            let restored = crate::privacy::restore_page(&message.thinking, restore_maps)?;
            replace_text(&mut message.thinking, restored);
        }
        let chat_metadata = Plain::new(metadata::chat(row, id, &key)?);
        let message_metadata = Plain::new(metadata::message(&raw, &message, id, &key)?);
        let result = Plain::new(SavedChatExactMessage {
            message: message.into_inner(),
            chat_metadata: chat_metadata.into_inner(),
            message_metadata: message_metadata.into_inner(),
            pii_mappings: mappings.into_inner(),
            content_mode: options.content_mode,
            pii_restoration: restoration(options.content_mode).into(),
            payload_bytes: bytes,
            history_complete: false,
        });
        crypto_scope.check(self)?;
        self.require_canonical_read_profile()?;
        output_bound(&*result)?;
        self.saved_read_current(&scope)?;
        Ok(result.into_inner())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const ID: &str = "22222222-2222-4222-8222-222222222222";
    fn client() -> Client {
        let endpoint = "http://127.0.0.1:12345";
        let session:Session=serde_json::from_value(json!({"api_url":endpoint,"session_id":"synthetic","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})).unwrap();
        Client::new(endpoint, Some(session)).unwrap()
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only
    #[test]
    fn saved_output_admission_binds_current_authority_without_minting_receipts() {
        let mut c = client();
        c.user = json!({"id":"synthetic-owner"});
        let admission = c
            .saved_chat_read_admission()
            .unwrap_or_else(|_| panic!("saved admission"));
        assert!(admission.check(&c).is_ok());
        c.forget_session();
        assert!(matches!(admission.check(&c), Err(Error::Authentication)));
        for change in 0..7 {
            let mut c = client();
            c.user = json!({"id":"synthetic-owner"});
            let admission = c
                .saved_chat_read_admission()
                .unwrap_or_else(|_| panic!("saved admission"));
            match change {
                0 => c.operation_cancel.cancel(),
                1 => c.generation += 1,
                2 => c.session.as_mut().unwrap().active_team_id = Some("other-team".into()),
                3 => c.session.as_mut().unwrap().master_key = zeroize::Zeroizing::new([9; 32]),
                4 => c.session.as_mut().unwrap().hashed_email = "other-owner".into(),
                5 => c.session.as_mut().unwrap().paired_session_expires_at = Some(0),
                _ => c.user = json!({"id":"other-principal"}),
            }
            assert!(admission.check(&c).is_err());
        }
        let mut c = client();
        c.session.as_mut().unwrap().active_team_id = Some("existing-team".into());
        let admission = c
            .saved_chat_read_admission()
            .unwrap_or_else(|_| panic!("team saved admission"));
        assert!(admission.check(&c).is_ok());
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[test]
    fn saved_options_are_explicit_and_old_window_stays_twenty() {
        let options: SavedChatReadOptions = serde_json::from_str("{}").unwrap();
        assert_eq!(options.limit, 30);
        assert_eq!(options.content_mode, SavedChatContentMode::Stored);
        assert_eq!(MessageWindowOptions::default().limit, 20);
        for malformed in [
            r#"{"limit":true}"#,
            r#"{"limit":1.5}"#,
            r#"{"all":true}"#,
            r#"{"contentMode":"strict_full"}"#,
        ] {
            assert!(serde_json::from_str::<SavedChatReadOptions>(malformed).is_err());
        }
        for accepted in [
            r#"{"limit":30}"#,
            r#"{"limit":100,"contentMode":"page_local"}"#,
        ] {
            assert!(serde_json::from_str::<SavedChatReadOptions>(accepted).is_ok());
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[tokio::test]
    async fn invalid_page_budgets_and_competing_selectors_make_no_requests() {
        let mut client = client();
        for max_pages in [0, 6, usize::MAX] {
            assert!(matches!(
                client
                    .saved_chat_read(
                        ID,
                        SavedChatReadOptions {
                            max_pages,
                            ..Default::default()
                        }
                    )
                    .await,
                Err(Error::Invalid(_))
            ));
        }
        let selector = MessageWindowCursor {
            chat_id: ID.into(),
            scope: "a".repeat(64),
            created_at: 0,
            message_id: "10000000-0000-4000-8000-000000000001".into(),
        };
        assert!(matches!(
            client
                .saved_chat_read(
                    ID,
                    SavedChatReadOptions {
                        before: Some(selector),
                        anchor_message_id: Some("10000000-0000-4000-8000-000000000001".into()),
                        ..Default::default()
                    }
                )
                .await,
            Err(Error::Invalid(_))
        ));
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[test]
    fn final_publication_refuses_cancel_owner_change_and_expiry() {
        let mut client = client();
        let scope = client.message_window_scope().unwrap();
        assert!(client.saved_read_current(&scope).is_ok());
        let token = tokio_util::sync::CancellationToken::new();
        token.cancel();
        client.set_operation_cancel(token);
        assert!(matches!(
            client.saved_read_current(&scope),
            Err(Error::Cancelled)
        ));
        client.set_operation_cancel(tokio_util::sync::CancellationToken::new());
        client
            .set_team(Some("33333333-3333-4333-8333-333333333333"))
            .unwrap();
        assert!(matches!(
            client.saved_read_current(&scope),
            Err(Error::Conflict)
        ));
        let scope = client.message_window_scope().unwrap();
        client.session.as_mut().unwrap().paired_session_expires_at = Some(0);
        assert!(matches!(
            client.saved_read_current(&scope),
            Err(Error::Expired)
        ));
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[tokio::test]
    async fn invalid_bounds_make_no_cache_or_selection_changes() {
        let mut client = client();
        client.active_chat = Some("prior-selection".into());
        client.history.insert(
            ID.into(),
            vec![json!({"sentinel":"prior-complete-ciphertext"})],
        );
        let snapshot = client.ciphertext_snapshot();
        for limit in [0, 101, usize::MAX] {
            assert!(matches!(
                client
                    .saved_chat_read(
                        ID,
                        SavedChatReadOptions {
                            limit,
                            ..Default::default()
                        }
                    )
                    .await,
                Err(Error::Invalid(_))
            ));
        }
        assert_eq!(client.active_chat.as_deref(), Some("prior-selection"));
        assert_eq!(client.ciphertext_snapshot(), snapshot);
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[test]
    fn bounded_unknown_restoration_never_weakens_strict_full_history() {
        let token = "[OM_PII_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]";
        assert_eq!(crate::privacy::restore_page(token, &[]).unwrap(), token);
        assert!(crate::privacy::restore(token, &[]).is_err());
        assert!(crate::privacy::restore_local(token, &[]).is_err());
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[tokio::test]
    async fn exact_dot_only_route_selectors_remain_refused_before_transport() {
        for message_id in [".", ".."] {
            let mut client = client();
            let scope = client.message_window_scope().unwrap();
            let before = client.ciphertext_snapshot();
            let options = SavedChatExactOptions {
                cursor: MessageWindowCursor { chat_id: ID.into(), scope, created_at: 1, message_id: message_id.into() },
                content_mode: SavedChatContentMode::Stored,
            };
            assert!(matches!(client.saved_chat_exact_message(ID, options).await, Err(Error::Invalid(_))));
            assert_eq!(client.ciphertext_snapshot(), before);
        }
    }

}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "first_page_resource_tests.rs"]
mod first_page_resource_tests;


#[cfg(test)]
mod opaque_exact_path_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
    #[test]
    fn exact_path_segments_encode_once_and_query_form_policy_is_unchanged() {
        let fixture:Value=serde_json::from_str(include_str!("../../tests/fixtures/message-id-compatibility.json")).unwrap();
        for case in fixture["path_cases"].as_array().unwrap(){
            let raw=case["value"].as_str().unwrap();let encoded=exact_message_segment(raw);
            assert_eq!(encoded,case["encoded"].as_str().unwrap());
            let url=url::Url::parse(&format!("https://example.invalid/v1/chats/{}/messages/{}","22222222-2222-4222-8222-222222222222",encoded)).unwrap();
            assert_eq!(url.path_segments().unwrap().last().unwrap(),encoded);
        }
        let mut query=url::Url::parse("https://example.invalid/").unwrap();query.query_pairs_mut().append_pair("message_id","a b+c%2F");
        assert_eq!(query.query(),Some("message_id=a+b%2Bc%252F"));
        assert_eq!(query.query_pairs().next().unwrap().1,"a b+c%2F");
        assert_eq!(exact_message_segment("."),".");assert_eq!(exact_message_segment(".."),".."); // caller still refuses these
    }
}
