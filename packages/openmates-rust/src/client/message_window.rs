//! One authenticated encrypted viewing page, never a complete-history snapshot.
//! The existing Client owns metadata authorization, cookie transport and keys.
//! Cursors are selectors bound to this live Client/context, not authority leases.
//! Page-local message mappings restore known PII; omitted mappings stay literal.
//! No page rows, inventory proofs or recovery jobs enter the complete cache.
use super::plaintext::{Plain, replace_text};
use super::{
    sync::{decode_chat_message, decrypt_optional},
    *,
};
use serde::{Deserialize, Serialize};

#[path = "message_window_decode.rs"]
mod decode;
pub(super) use decode::decode_message_page_data;

/// Saved-message read IDs are nonempty opaque UTF-8 strings, never authority.
/// Complete row/packet/window byte budgets bound resources separately; there is
/// no universal per-ID maximum across maintained server and local stores.
/// Preserve exact bytes/case/control characters; never trim or normalize IDs.
/// Canonical Chat UUID, owner/scope, ordering and ciphertext guards are separate.
pub fn valid_message_id(value: &str) -> bool {
    !value.is_empty()
}

/// Canonical server row aliases: logical client/message aliases must agree;
/// an independent database `id` alias can differ. Empty/null legacy aliases
/// fall through exactly as the deployed nonempty client/message/id preference.
/// Nonstring aliases and conflicting logical aliases are refused, not repaired.
pub(super) fn server_message_id(row: &Value) -> Result<&str> {
    let mut selected = None;
    for field in ["client_message_id", "message_id", "id"] {
        let Some(value) = row.get(field).filter(|value| !value.is_null()) else {
            continue;
        };
        let value = value.as_str().ok_or(Error::Protocol)?;
        if value.is_empty() {
            continue;
        }
        if !valid_message_id(value) {
            return Err(Error::Protocol);
        }
        if field == "message_id"
            && row.get("client_message_id").and_then(Value::as_str)
                .filter(|client| !client.is_empty()).is_some_and(|client| client != value)
        {
            return Err(Error::Protocol);
        }
        if selected.is_none() {
            selected = Some(value);
        }
    }
    selected.ok_or(Error::Protocol)
}

pub(super) const MAX_MESSAGES: usize = 20;
pub(super) const MAX_MESSAGE_BYTES: usize = 256 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MessageWindowDirection {
    Latest,
    Before,
    After,
    Around,
}

impl Default for MessageWindowDirection {
    fn default() -> Self {
        Self::Latest
    }
}

/// A live-context paging selector. Reimport/reset/workspace changes invalidate it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MessageWindowCursor {
    pub chat_id: String,
    pub scope: String,
    pub created_at: i64,
    pub message_id: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MessageWindowOptions {
    #[serde(default)]
    pub direction: MessageWindowDirection,
    #[serde(default = "default_limit")]
    pub limit: usize,
    #[serde(default)]
    pub cursor: Option<MessageWindowCursor>,
    #[serde(default)]
    pub anchor_message_id: Option<String>,
    #[serde(default = "default_compression")]
    pub respect_compression_boundary: bool,
}
fn default_limit() -> usize {
    MAX_MESSAGES
}
fn default_compression() -> bool {
    true
}
impl Default for MessageWindowOptions {
    fn default() -> Self {
        Self {
            direction: MessageWindowDirection::Latest,
            limit: MAX_MESSAGES,
            cursor: None,
            anchor_message_id: None,
            respect_compression_boundary: true,
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatMessageWindow {
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
    /// Always "page_local"; no cumulative mapping endpoint exists.
    pub pii_restoration: String,
    /// Always false: even a terminal page does not replace complete cache state.
    pub history_complete: bool,
}
impl MessageWindowOptions {
    pub(super) fn validate(&self, id: &str, scope: &str) -> Result<()> {
        if super::monitor::cached_view::bounded_bytes(self, MAX_MESSAGE_BYTES).is_none() {
            return Err(Error::Invalid("Message window selector exceeds its packet budget."));
        }
        if !(1..=MAX_MESSAGES).contains(&self.limit) {
            return Err(Error::Invalid(
                "Message window limit must be between 1 and 20.",
            ));
        }
        let paging = matches!(
            self.direction,
            MessageWindowDirection::Before | MessageWindowDirection::After
        );
        if paging != self.cursor.is_some()
            || (self.direction == MessageWindowDirection::Around)
                != self.anchor_message_id.is_some()
        {
            return Err(Error::Invalid(
                "Message window requires its exact direction cursor or anchor.",
            ));
        }
        if let Some(c) = &self.cursor {
            if c.created_at < 0
                || !valid_message_id(&c.message_id)
                || c.scope.len() != 64
                || !c.scope.bytes().all(|v| v.is_ascii_hexdigit())
            {
                return Err(Error::Invalid("Invalid message window cursor."));
            }
            if c.chat_id != id || c.scope != scope {
                return Err(Error::Conflict);
            }
        }
        if self
            .anchor_message_id
            .as_ref()
            .is_some_and(|v| !valid_message_id(v))
        {
            return Err(Error::Invalid("Invalid message window anchor."));
        }
        Ok(())
    }
}
fn cursor(page: &Value, name: &str, id: &str, scope: &str) -> Result<Option<MessageWindowCursor>> {
    let Some(value) = page.get(name).filter(|v| !v.is_null()) else {
        return Ok(None);
    };
    let created_at = value
        .get("created_at")
        .and_then(Value::as_i64)
        .filter(|v| *v >= 0)
        .ok_or(Error::Protocol)?;
    let message_id = required(value, "message_id")?;
    if !valid_message_id(message_id) { return Err(Error::Protocol); }
    Ok(Some(MessageWindowCursor {
        chat_id: id.into(),
        scope: scope.into(),
        created_at,
        message_id: message_id.into(),
    }))
}
fn boolean(page: &Value, field: &str) -> Result<bool> {
    page.get(field)
        .and_then(Value::as_bool)
        .ok_or(Error::Protocol)
}
fn optional_count(page: &Value, field: &str) -> Result<Option<u64>> {
    match page.get(field).filter(|v| !v.is_null()) {
        None => Ok(None),
        Some(v) => v.as_u64().map(Some).ok_or(Error::Protocol),
    }
}
// Around readback must attest the requested row, not merely plausible cursors.
// Database IDs are valid lookup aliases; cursor/output IDs remain canonical.
fn validate_anchor(
    options: &MessageWindowOptions,
    rows: &[Value],
    found: bool,
    oversized: bool,
    oversized_cursor: Option<&MessageWindowCursor>,
) -> Result<()> {
    if options.direction != MessageWindowDirection::Around {
        return Ok(());
    }
    let anchor = options
        .anchor_message_id
        .as_deref()
        .ok_or(Error::Protocol)?;
    if !found {
        return if rows.is_empty() && !oversized {
            Ok(())
        } else {
            Err(Error::Protocol)
        };
    }
    if rows.iter().any(|row| {
        ["id", "client_message_id", "message_id"]
            .into_iter()
            .any(|name| row.get(name).and_then(Value::as_str) == Some(anchor))
    }) {
        return Ok(());
    }
    // A byte-oversized anchor is deliberately omitted and exposes only its
    // stable cursor. Without a row, an unproven DB-ID alias cannot be inferred.
    if rows.is_empty() && oversized && oversized_cursor.is_some_and(|c| c.message_id == anchor) {
        return Ok(());
    }
    Err(Error::Protocol)
}

impl Client {
    pub(super) fn message_window_scope(&self) -> Result<String> {
        self.require_credentials()?;
        Ok(sha256(&serde_json::to_string(&(
            &self.message_window_nonce,
            self.generation,
            self.team()?,
        ))?))
    }
    // The sole plaintext publication boundary; runs after decoding/restoration.
    fn publish_message_window(
        &self,
        scope: &str,
        window: ChatMessageWindow,
    ) -> Result<ChatMessageWindow> {
        let window = Plain::new(window);
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if self.message_window_scope()? != scope {
            return Err(Error::Conflict);
        }
        Ok(window.into_inner())
    }
    fn publish_message_window_with_capability(
        &self,
        scope: &str,
        crypto_scope: &super::sync_capability::AsyncCryptoScope,
        window: ChatMessageWindow,
    ) -> Result<ChatMessageWindow> {
        let window = Plain::new(window);
        crypto_scope.check(self)?;
        self.require_canonical_read_profile()?;
        self.publish_message_window(scope, window.into_inner())
    }
    /// Fetch/decrypt one currently authorized server page. Never synchronizes,
    /// claims recovery work, reads older pages or promotes partial cache rows.
    pub async fn chat_message_window(
        &mut self,
        id: &str,
        options: MessageWindowOptions,
    ) -> Result<ChatMessageWindow> {
        Ok(self.read_message_page(id, options, false).await?.window)
    }
    pub(super) async fn read_message_page(
        &mut self,
        id: &str,
        options: MessageWindowOptions,
        stored: bool,
    ) -> Result<MessagePageData> {
        self.read_message_page_inner(id,options,stored,false).await
    }
    pub(super) async fn read_browser_cache_message_page(&mut self,id:&str,options:MessageWindowOptions)->Result<MessagePageData>{
        self.read_message_page_inner(id,options,false,true).await
    }
    async fn read_message_page_inner(&mut self,id:&str,options:MessageWindowOptions,stored:bool,capture_browser:bool)->Result<MessagePageData>{
        self.require_canonical_read_profile()?;
        uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        if self.is_ephemeral_chat(id) {
            return Err(Error::Invalid("Volatile chat history has no server page."));
        }
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let crypto_scope = super::sync_capability::AsyncCryptoScope::begin(self)?;
        let scope = self.message_window_scope()?;
        options.validate(id, &scope)?;
        let metadata = self
            .request_chat_metadata(id)
            .await?
            .ok_or(Error::Forbidden)?;
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let rows = metadata["chats"].as_array().ok_or(Error::Protocol)?;
        if rows.len() != 1 || text(&rows[0], "id") != id {
            return Err(Error::Forbidden);
        }
        crypto_scope.check(self)?;
        let row = &rows[0];
        if capture_browser {self.browser_message_cache_metadata_guard(row,id)?;}
        // Reuse the same fresh Team/direct wrapping-key policy as full open.
        let wrapping = self.wrapping_capability().await?;
        if text(row, "chat_visibility") == "direct" {
            self.load_direct_identity().await?;
        }
        let key = self.chat_key_with_capability(row, &wrapping).await?;
        let item = Plain::new(self.chat_item(row, &key)?);
        let mut url = self.url(&format!("/v1/chats/{}/messages/window", segment(id)))?;
        {
            let mut query = url.query_pairs_mut();
            let direction = match options.direction {
                MessageWindowDirection::Latest => "latest",
                MessageWindowDirection::Before => "before",
                MessageWindowDirection::After => "after",
                MessageWindowDirection::Around => "around",
            };
            query
                .append_pair("direction", direction)
                .append_pair("limit", &options.limit.to_string())
                .append_pair(
                    "respect_compression_boundary",
                    if options.respect_compression_boundary {
                        "true"
                    } else {
                        "false"
                    },
                );
            if let Some(c) = &options.cursor {
                let prefix = if options.direction == MessageWindowDirection::Before {
                    "before"
                } else {
                    "after"
                };
                query
                    .append_pair(&format!("{prefix}_timestamp"), &c.created_at.to_string())
                    .append_pair(&format!("{prefix}_message_id"), &c.message_id);
            }
            if let Some(anchor) = &options.anchor_message_id {
                query.append_pair("anchor_message_id", anchor);
            }
        }
        let path = self.scoped(&format!("{}?{}", self.request_route_path(&url)?, url.query().unwrap_or("")))?;
        let page = self.request(Method::GET, &path, None).await?;
        crypto_scope.check(self)?;
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if self.message_window_scope()? != scope {
            return Err(Error::Conflict);
        }
        let MessagePageData {
            incoming, window, mappings, metadata_stamp, chat_metadata, message_metadata,
        } = decode_message_page_data(
            id, row, key, item, page, &options, &scope, stored, capture_browser,
            || {
                crypto_scope.check(self)?;
                if self.operation_cancel.is_cancelled() { return Err(Error::Cancelled); }
                if self.message_window_scope()? != scope { return Err(Error::Conflict); }
                Ok(())
            },
        )?;
        // Ancillary plaintext stays owned/wiping across the exact original
        // final window publication. Incoming raw rows/key already Drop-wipe.
        let mappings = Plain::new(mappings);
        let metadata_stamp = Plain::new(metadata_stamp);
        let chat_metadata = Plain::new(chat_metadata);
        let message_metadata = Plain::new(message_metadata);
        let window = self.publish_message_window_with_capability(
            &scope,
            &crypto_scope,
            window,
        )?;
        Ok(MessagePageData {
            incoming,
            window,
            mappings: mappings.into_inner(),
            metadata_stamp: metadata_stamp.into_inner(),
            chat_metadata: chat_metadata.into_inner(),
            message_metadata: message_metadata.into_inner(),
        })
    }
}

pub(super) struct MessagePageData {
    pub(super) incoming:Option<BrowserIncomingMessagePage>,
    pub window: ChatMessageWindow,
    pub mappings: std::collections::BTreeMap<String, Vec<Value>>,
    pub metadata_stamp: String,
    pub chat_metadata: Option<super::saved_chat_read::SavedChatReadMetadata>,
    pub message_metadata: Vec<super::saved_chat_read::SavedChatMessageMetadata>,
}
// Drop-wiping is opt-in; legacy/default paths retain the same allocations.
struct PageCiphertextRows {values:Vec<Value>,guarded:bool}
impl std::ops::Deref for PageCiphertextRows{type Target=Vec<Value>;fn deref(&self)->&Self::Target{&self.values}}
impl std::ops::DerefMut for PageCiphertextRows{fn deref_mut(&mut self)->&mut Self::Target{&mut self.values}}
impl Drop for PageCiphertextRows{fn drop(&mut self){if self.guarded{for row in &mut self.values{crate::model::zeroize_json(row);}}}}
// Original same-response rows and derived chat key stay Rust-only and Drop-wiped.
// No serialization, cloning, master extraction or reusable auth proof exists.
pub(super) struct BrowserIncomingMessagePage {
 pub(super) metadata:Plain<Value>,pub(super) messages:Plain<Vec<Value>>,pub(super) key:Key,
}
#[cfg(test)]
#[path = "message_window_tests.rs"]
mod tests;
