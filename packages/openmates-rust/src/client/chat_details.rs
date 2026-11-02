//! Selected rich read shared by SDKs and thin native adapters. No global sync,
//! CLI flags, terminal formatting, new authentication or plaintext cache.
use super::{
    plaintext::{Plain, Wipe},
    saved_chat_read::{SavedChatContentMode, metadata},
    sync_capability::AsyncCryptoScope,
    *,
};
use serde::{Deserialize, Serialize};
use zeroize::{Zeroize, Zeroizing};
#[path = "chat_details_json.rs"]
mod json;
#[path = "chat_details_memory.rs"]
mod memory;
#[path = "chat_details_prefetch.rs"]
mod prefetch;
pub use json::{ChatDetailsJson, ChatDetailsJsonString, ChatDetailsJsonValue};
const MAX_PAGES: usize = 100; // Existing strict full-history page bound.
const MAX_METADATA_BYTES: usize = 256 * 1024;
const MAX_FIELD_BYTES: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ChatDetailsHistory {
    Latest { limit: usize },
    Full,
}
impl<'de> Deserialize<'de> for ChatDetailsHistory {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        // A tagged serde unit variant ignores its remaining map entries even
        // with deny_unknown_fields. The empty struct wire variant validates
        // the closed full-history shape without changing the public enum/API.
        #[derive(Deserialize)]
        #[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
        enum Wire {
            Latest { limit: usize },
            Full {},
        }
        Ok(match Wire::deserialize(deserializer)? {
            Wire::Latest { limit } => Self::Latest { limit },
            Wire::Full {} => Self::Full,
        })
    }
}
impl Default for ChatDetailsHistory {
    fn default() -> Self {
        Self::Latest { limit: 30 }
    }
}
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChatDetailsOptions {
    #[serde(default)]
    pub history: ChatDetailsHistory,
    #[serde(default)]
    pub content_mode: SavedChatContentMode,
}
#[derive(Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatDetailsMetadata {
    pub id: String,
    pub chat_visibility: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub participant_user_hashes: Option<Vec<String>>,
    pub short_id: String,
    pub slug: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub active_focus_id: Option<String>,
    pub title: Option<String>,
    pub summary: Option<String>,
    pub created_at: Option<serde_json::Number>,
    pub updated_at: Option<serde_json::Number>,
    pub category: Option<String>,
    pub mate_name: Option<String>,
    pub parent_id: Option<String>,
    pub is_sub_chat: bool,
    pub is_hidden_candidate: bool,
    pub is_hidden: bool,
    pub pinned: bool,
    pub has_draft: bool,
    pub draft_preview: Option<ChatDetailsText>,
    pub metadata_updated_at: u64,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatDetailsMessage {
    pub id: String,
    pub client_message_id: String,
    pub chat_id: String,
    pub role: String,
    pub content: String,
    pub sender_name: Option<String>,
    pub hashed_sender_user_id: Option<String>,
    pub category: Option<String>,
    pub model_name: Option<String>,
    pub created_at: serde_json::Number,
    pub embed_ids: Vec<String>,
    #[serde(
        default,
        deserialize_with = "present_json",
        skip_serializing_if = "Option::is_none"
    )]
    pub pii_mappings: Option<ChatDetailsJson>,
}
impl Default for ChatDetailsMessage {
    fn default() -> Self {
        Self {
            id: String::new(),
            client_message_id: String::new(),
            chat_id: String::new(),
            role: String::new(),
            content: String::new(),
            sender_name: None,
            hashed_sender_user_id: None,
            category: None,
            model_name: None,
            created_at: serde_json::Number::from(0),
            embed_ids: vec![],
            pii_mappings: None,
        }
    }
}
#[derive(Default, Serialize, Deserialize)]
pub struct ChatDetailsRead {
    pub chat: ChatDetailsMetadata,
    pub messages: Vec<ChatDetailsMessage>,
    pub follow_up_suggestions: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub has_more_before: Option<bool>,
    #[serde(skip)]
    admission: Option<full_chat_read::FullChatReadAdmission>,
}
impl ChatDetailsRead {
    pub fn check(&self, client: &Client) -> Result<()> {
        self.admission
            .as_ref()
            .ok_or(Error::Forbidden)?
            .check(client)
    }
    pub fn take_admission(
        &mut self,
        client: &Client,
    ) -> Result<full_chat_read::FullChatReadAdmission> {
        self.check(client)?;
        self.admission.take().ok_or(Error::Forbidden)
    }
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct MessageWire<'a> {
    id: &'a str,
    client_message_id: &'a str,
    chat_id: &'a str,
    role: &'a str,
    content: &'a str,
    sender_name: Option<&'a str>,
    hashed_sender_user_id: Option<&'a str>,
    category: Option<&'a str>,
    model_name: Option<&'a str>,
    created_at: &'a serde_json::Number,
    embed_ids: &'a [String],
    #[serde(skip_serializing_if = "Option::is_none")]
    pii_mappings: Option<json::ModeJson<'a>>,
}
impl ChatDetailsMessage {
    fn wire(&self, sdk: bool) -> MessageWire<'_> {
        MessageWire {
            id: &self.id,
            client_message_id: &self.client_message_id,
            chat_id: &self.chat_id,
            role: &self.role,
            content: &self.content,
            sender_name: self.sender_name.as_deref(),
            hashed_sender_user_id: self.hashed_sender_user_id.as_deref(),
            category: self.category.as_deref(),
            model_name: self.model_name.as_deref(),
            created_at: &self.created_at,
            embed_ids: &self.embed_ids,
            pii_mappings: self.pii_mappings.as_ref().map(|v| json::ModeJson(v, sdk)),
        }
    }
}
impl Serialize for ChatDetailsMessage {
    fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        self.wire(false).serialize(s)
    }
}
struct SdkMessages<'a>(&'a [ChatDetailsMessage]);
impl Serialize for SdkMessages<'_> {
    fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        use serde::ser::SerializeSeq;
        let mut seq = s.serialize_seq(Some(self.0.len()))?;
        for message in self.0 {
            seq.serialize_element(&message.wire(true))?;
        }
        seq.end()
    }
}
#[derive(Serialize)]
struct SdkReadWire<'a> {
    chat: &'a ChatDetailsMetadata,
    messages: SdkMessages<'a>,
    follow_up_suggestions: &'a [String],
    #[serde(skip_serializing_if = "Option::is_none")]
    has_more_before: Option<bool>,
}
impl ChatDetailsRead {
    /// Raw SDK value transport. Both foreign parsers receive JS binary64
    /// infinities/signed zero through valid JSON, under the same output seal.
    /// Ordinary Serialize remains the CLI JSON.stringify projection.
    pub fn sdk_json(&self) -> Result<String> {
        Ok(serde_json::to_string(&SdkReadWire {
            chat: &self.chat,
            messages: SdkMessages(&self.messages),
            follow_up_suggestions: &self.follow_up_suggestions,
            has_more_before: self.has_more_before,
        })?)
    }
}
impl Wipe for ChatDetailsMetadata {
    fn wipe(&mut self) {
        self.id.wipe();
        self.chat_visibility.wipe();
        self.participant_user_hashes.wipe();
        self.short_id.wipe();
        self.slug.wipe();
        self.active_focus_id.wipe();
        self.title.wipe();
        self.summary.wipe();
        self.category.wipe();
        self.mate_name.wipe();
        self.parent_id.wipe();
        self.draft_preview.wipe();
    }
}
impl Wipe for ChatDetailsMessage {
    fn wipe(&mut self) {
        self.id.wipe();
        self.client_message_id.wipe();
        self.chat_id.wipe();
        self.role.wipe();
        self.content.wipe();
        self.sender_name.wipe();
        self.hashed_sender_user_id.wipe();
        self.category.wipe();
        self.model_name.wipe();
        self.embed_ids.wipe();
        self.pii_mappings.wipe();
        self.pii_mappings = None;
    }
}
impl Wipe for ChatDetailsRead {
    fn wipe(&mut self) {
        self.chat.wipe();
        self.messages.wipe();
        self.follow_up_suggestions.wipe();
    }
}
impl Drop for ChatDetailsRead {
    fn drop(&mut self) {
        self.wipe();
    }
}
fn number(row: &Value, name: &str) -> Option<serde_json::Number> {
    row.get(name).and_then(|v| {
        if let Value::Number(n) = v {
            Some(n.clone())
        } else {
            None
        }
    })
}
fn optional_text(row: &Value, name: &str) -> Option<String> {
    row.get(name).and_then(Value::as_str).map(str::to_owned)
}
fn mate_name(category: Option<&str>) -> Option<String> {
    search::mate_name(category?).map(str::to_owned)
}
fn js_space(value: char) -> bool {
    search::js_whitespace(value)
}
/// Lossless JSON string leaf for the maintained UTF-16 preview boundary.
/// Direct Rust retains exact units; foreign JSON parsers receive their ordinary
/// string. No untrusted raw JSON is ever interpolated into serialization.
pub struct ChatDetailsText {
    repr: TextRepr,
}
enum TextRepr {
    Units(Vec<u16>),
    Json(Box<serde_json::value::RawValue>),
}
impl ChatDetailsText {
    pub fn encoded_json(&self) -> Result<String> {
        serde_json::to_string(self).map_err(|_| Error::Protocol)
    }
    pub fn utf16_units(&self) -> Option<&[u16]> {
        match &self.repr {
            TextRepr::Units(v) => Some(v),
            TextRepr::Json(_) => None,
        }
    }
}
impl Wipe for ChatDetailsText {
    fn wipe(&mut self) {
        match std::mem::replace(&mut self.repr, TextRepr::Units(vec![])) {
            TextRepr::Units(mut units) => units.zeroize(),
            TextRepr::Json(raw) => {
                let mut text: Box<str> = raw.into();
                text.zeroize();
            }
        }
    }
}
impl Drop for ChatDetailsText {
    fn drop(&mut self) {
        self.wipe();
    }
}
impl Serialize for ChatDetailsText {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        match &self.repr {
            TextRepr::Json(raw) => raw.serialize(serializer),
            TextRepr::Units(units) => {
                let mut json = Zeroizing::new(String::with_capacity(2 + units.len() * 6));
                json::write_utf16_string(units, &mut json)
                    .map_err(serde::ser::Error::custom)?;
                let raw: &serde_json::value::RawValue =
                    serde_json::from_str(&json).map_err(serde::ser::Error::custom)?;
                raw.serialize(serializer)
            }
        }
    }
}
impl<'de> Deserialize<'de> for ChatDetailsText {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        let raw = Box::<serde_json::value::RawValue>::deserialize(deserializer)?;
        if !raw.get().starts_with('"') {
            let mut text: Box<str> = raw.into();
            text.zeroize();
            return Err(serde::de::Error::custom("A JSON string leaf is required."));
        }
        Ok(Self {
            repr: TextRepr::Json(raw),
        })
    }
}
fn present_json<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> std::result::Result<Option<ChatDetailsJson>, D::Error> {
    ChatDetailsJson::deserialize(deserializer).map(Some)
}
fn draft_preview(value: &str) -> Result<Option<ChatDetailsText>> {
    let mut normalized = Zeroizing::new(String::new());
    let mut pending_space = false;
    for ch in value.chars() {
        if js_space(ch) {
            if !normalized.is_empty() {
                pending_space = true;
            }
            continue;
        }
        if pending_space {
            normalized.push(' ');
            pending_space = false;
        }
        normalized.push(ch);
    }
    let units = normalized.encode_utf16().take(200).collect::<Vec<_>>();
    if units.is_empty() {
        Ok(None)
    } else {
        Ok(Some(ChatDetailsText {
            repr: TextRepr::Units(units),
        }))
    }
}
fn strip_suggestion(value: &str) -> &str {
    let trimmed = value.trim_start_matches(js_space);
    let content = if trimmed.starts_with('[') {
        trimmed
            .find(']')
            .filter(|n| *n > 1)
            .map(|n| &trimmed[n + 1..])
            .unwrap_or(value)
    } else {
        value
    };
    content.trim_matches(js_space)
}
fn suggestions(source: &Value, key: &[u8; 32]) -> Result<Vec<String>> {
    // Exactly the maintained optional suggestion behavior: absent/empty or bad
    // optional JSON is [], filter nonstrings/empty entries, strip legacy prefix.
    let Some(value) = source
        .get("encrypted_follow_up_request_suggestions")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
    else {
        return Ok(vec![]);
    };
    let plain = Plain::new(match crypto::decrypt_combined(value, key) {
        Ok(value) => value,
        Err(Error::Crypto) => return Ok(vec![]),
        Err(error) => return Err(error),
    });
    let parsed = Plain::new(match serde_json::from_str::<Value>(&plain) {
        Ok(value) => value,
        Err(_) => return Ok(vec![]),
    });
    let Some(values) = parsed.as_array() else {
        return Ok(vec![]);
    };
    if values.len() > 256 {
        return Err(Error::Protocol);
    }
    let mut output = Plain::new(Vec::<String>::new());
    for value in values {
        if let Some(value) = value.as_str().filter(|v| !v.is_empty()) {
            let value = strip_suggestion(value);
            if value.len() > 2048 {
                return Err(Error::Protocol);
            }
            if !value.is_empty() {
                output.push(value.to_owned());
            }
        }
    }
    Ok(output.into_inner())
}
fn active_focus(row: &Value, key: &[u8; 32]) -> Result<Option<String>> {
    Ok(
        metadata::projection_encrypted(row, "encrypted_active_focus_id", key)?
            .filter(|value| !value.is_empty()),
    )
}
fn project_message(row: &Value, decoded: Message, key: &[u8; 32]) -> Result<ChatDetailsMessage> {
    let mut decoded = Plain::new(decoded);
    let raw_pii = Plain::new(
        if row
            .get("encrypted_pii_mappings")
            .and_then(Value::as_str)
            .is_some()
        {
            let plain = Plain::new(metadata::projection_message_text(
                row,
                "encrypted_pii_mappings",
                key,
            )?);
            Some(ChatDetailsJson::from_text(
                plain
                    .into_inner()
                    .filter(|v| !v.is_empty())
                    .unwrap_or_else(|| "[]".into()),
            )?)
        } else {
            None
        },
    );
    let mut output = Plain::new(ChatDetailsMessage {
        created_at: serde_json::Number::from(0),
        ..Default::default()
    });
    output.id = optional_text(row, "id")
        .or_else(|| optional_text(row, "message_id"))
        .unwrap_or_default();
    output.client_message_id = std::mem::take(&mut decoded.id);
    output.chat_id = optional_text(row, "chat_id").unwrap_or_default();
    output.role = std::mem::take(&mut decoded.role);
    output.content = std::mem::take(&mut decoded.content);
    output.sender_name = metadata::projection_encrypted(row, "encrypted_sender_name", key)?;
    output.hashed_sender_user_id = optional_text(row, "hashed_user_id");
    output.category = metadata::projection_encrypted(row, "encrypted_category", key)?;
    output.model_name = metadata::projection_encrypted(row, "encrypted_model_name", key)?;
    output.created_at = number(row, "created_at").unwrap_or_else(|| serde_json::Number::from(0));
    output.pii_mappings = raw_pii.into_inner();
    Ok(output.into_inner())
}
/// A cache hit already decoded through the fresh path's per-row validation.
struct CachedAssembly {
    decoded: Plain<Vec<ChatDetailsMessage>>,
    visible_rows: Vec<Value>,
    all_rows: Vec<Value>,
    more: bool,
}
/// Merge the tail delta into the cached rows, or fail (a cache miss).
fn assemble_cached(
    cache: &chat_details_cache::ChatDetailsCache,
    page: &Value,
    id: &str,
    key: &[u8; 32],
    limit: Option<usize>,
    server_messages_v: Option<u64>,
) -> Result<CachedAssembly> {
    let miss = || Error::Protocol;
    if page.get("chat_id").filter(|v| !v.is_null()).is_some_and(|v| v.as_str() != Some(id))
        || page.get("oversized_message") == Some(&Value::Bool(true))
        || page.get("has_more_after") == Some(&Value::Bool(true))
    {
        return Err(miss());
    }
    let delta = page.get("messages").and_then(Value::as_array).ok_or_else(miss)?;
    if delta.len() >= chat_details_cache::TAIL_LIMIT {
        return Err(miss());
    }
    let actual_bytes = delta
        .iter()
        .try_fold(0usize, |total, row| {
            monitor::cached_view::bounded_bytes(row, 256 * 1024)
                .and_then(|size| total.checked_add(size))
                .filter(|total| *total <= 256 * 1024)
        })
        .ok_or_else(miss)?;
    if page.get("payload_bytes").and_then(Value::as_u64) != Some(actual_bytes as u64) {
        return Err(miss());
    }
    // A moved version without messages, or a version behind the cache, is stale.
    let server_v = server_messages_v.ok_or_else(miss)?;
    if (delta.is_empty() && server_v != cache.messages_v) || server_v < cache.messages_v {
        return Err(miss());
    }
    let mut all_rows = cache.rows.clone();
    all_rows.extend(delta.iter().cloned());
    let visible_start = match limit {
        Some(n) if all_rows.len() >= n => all_rows.len() - n,
        Some(_) if cache.has_more_before => return Err(miss()),
        Some(_) => 0,
        None if cache.has_more_before => return Err(miss()),
        None => 0,
    };
    let more = match limit {
        Some(_) => visible_start > 0 || cache.has_more_before,
        None => false,
    };
    let visible_rows = all_rows[visible_start..].to_vec();
    let mut seen = std::collections::HashSet::new();
    let mut decoded = Plain::new(Vec::new());
    let mut previous = None;
    for raw in &visible_rows {
        let (raw, message) = sync::decode_chat_message_stored(raw, id, key, &mut seen)?;
        let timestamp = raw
            .get("created_at")
            .and_then(Value::as_i64)
            .filter(|v| *v >= 0)
            .ok_or_else(miss)?;
        let position = (timestamp, message.id.clone());
        if previous.as_ref().is_some_and(|prior| prior >= &position) {
            return Err(miss());
        }
        previous = Some(position);
        let mut item = project_message(&raw, message, key)?;
        if item.chat_id.is_empty() {
            item.chat_id = id.into();
        }
        decoded.push(item);
    }
    Ok(CachedAssembly { decoded, visible_rows, all_rows, more })
}
impl Client {
    pub async fn read_chat_details(
        &mut self,
        id: &str,
        options: ChatDetailsOptions,
    ) -> Result<ChatDetailsRead> {
        self.read_chat_details_in_transaction(id, options, None)
            .await
    }
    async fn read_chat_details_in_transaction(
        &mut self,
        id: &str,
        options: ChatDetailsOptions,
        mut transaction: Option<&mut sync::read_freshness::ReadFreshnessTransaction>,
    ) -> Result<ChatDetailsRead> {
        let limit = match options.history {
            ChatDetailsHistory::Full => None,
            ChatDetailsHistory::Latest { limit } if (1..=100).contains(&limit) => Some(limit),
            _ => {
                return Err(Error::Invalid(
                    "Latest chat details limit must be between 1 and 100.",
                ));
            }
        };
        let admission = self.full_chat_read_admission(id)?;
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, id)?;
        // The metadata POST, first message window and first embed window are
        // independent server reads. Prepare them in the original order (each
        // with its own pre-send fences and transaction step), send them
        // together, then apply every post-send credential/status/owner fence
        // in that same order. Decryption still waits for the metadata row key.
        uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
        self.require_credentials()?;
        let requested = limit.unwrap_or(100);
        let metadata_path = self.scoped("/v1/chats/metadata/batch")?;
        let bounded = limit.is_some();
        // Cache-then-delta: a cached read replaces the latest-window request by
        // a tail delta after the last cached message (same concurrent round).
        let cached = self.cached_chat_details(id, bounded);
        let latest_path = self.chat_details_messages_path(id, requested, bounded, None)?;
        let messages_path = match &cached {
            Some(cache) => self.chat_details_tail_path(id, &cache.tail, bounded)?,
            None => latest_path.clone(),
        };
        let embeds_path = self.chat_details_embeds_path(id, None)?;
        let mut prepared = Vec::with_capacity(3);
        for (method, path, body, not_found) in [
            (Method::POST, &metadata_path, Some(json!({"chat_ids":[id],"include_read_details":true})), true),
            (Method::GET, &messages_path, None, false),
            (Method::GET, &embeds_path, None, false),
        ] {
            if let Some(t) = transaction.as_deref_mut() {
                t.before_request(self, id);
            }
            prepared.push(self.prepare_read(method, path, body, not_found)?);
        }
        let sent = futures_util::future::join_all(prepared.into_iter().map(|read| read.send())).await;
        let mut finished = Vec::with_capacity(3);
        for read in sent {
            finished.push(self.finish_read(read).await);
            if let Some(t) = transaction.as_deref_mut() {
                t.after_request(self, id);
            }
        }
        let mut finished = finished.into_iter();
        let (response, first_messages, first_embeds) =
            match (finished.next(), finished.next(), finished.next()) {
                (Some(a), Some(b), Some(c)) => (
                    a,
                    b.and_then(|v| v.ok_or(Error::Protocol)),
                    c.and_then(|v| v.ok_or(Error::Protocol)),
                ),
                _ => return Err(Error::Protocol),
            };
        let mut first_messages = Some(first_messages);
        let response =
            response?.ok_or(Error::Invalid("The selected saved chat is unavailable."))?;
        admission.check(self)?;
        scope.check_chat(self, id)?;
        let row = response
            .get("chats")
            .and_then(Value::as_array)
            .and_then(|rows| {
                rows.iter()
                    .find(|row| row.get("id").and_then(Value::as_str) == Some(id))
            })
            .ok_or(Error::Forbidden)?;
        if monitor::cached_view::bounded_bytes(row, MAX_METADATA_BYTES).is_none() {
            return Err(Error::Protocol);
        }
        let source =
            row.get("read_details")
                .filter(|v| v.is_object())
                .ok_or(Error::Unavailable {
                    code: "chat_details_projection_unavailable",
                    reason: "The server does not provide the selected rich-read projection.",
                })?;
        let wrapping = self.wrapping_capability().await?;
        admission.check(self)?;
        scope.check_chat(self, id)?;
        if sync::draft_only(row) && self.team()?.is_none() {
            return Err(Error::Unavailable {
                code: "chat_details_saved_key_required",
                reason: "Rich saved history requires its established chat key; draft keys are never substituted.",
            });
        }
        if text(row, "chat_visibility") == "direct" {
            self.load_direct_identity().await?;
        }
        let key = self.chat_key_with_capability(row, &wrapping).await?;
        admission.check(self)?;
        scope.check_chat(self, id)?;
        let mut result = Plain::new(ChatDetailsRead::default());
        result.follow_up_suggestions = suggestions(source, &key)?;
        result.chat.id = id.into();
        result.chat.short_id = id.chars().take(8).collect();
        result.chat.chat_visibility = if text(row, "chat_visibility") == "direct" {
            "direct"
        } else if self.team()?.is_some() {
            "team"
        } else {
            "personal"
        }
        .into();
        result.chat.participant_user_hashes = row
            .get("participant_user_hashes")
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(str::to_owned)
                    .collect()
            });
        result.chat.slug = if row.get("encrypted_slug").and_then(Value::as_str).is_some() {
            Some(metadata::projection_encrypted(row, "encrypted_slug", &key)?.unwrap_or_default())
        } else {
            None
        };
        result.chat.active_focus_id = active_focus(row, &key)?;
        result.chat.title = metadata::projection_encrypted(row, "encrypted_title", &key)?;
        result.chat.summary = metadata::projection_encrypted(row, "encrypted_chat_summary", &key)?;
        result.chat.category = metadata::projection_encrypted(row, "encrypted_category", &key)?;
        result.chat.mate_name = mate_name(result.chat.category.as_deref());
        result.chat.created_at = number(source, "created_at");
        result.chat.updated_at = number(source, "last_edited_overall_timestamp");
        result.chat.parent_id = optional_text(row, "parent_id");
        result.chat.is_sub_chat = row.get("is_sub_chat") == Some(&Value::Bool(true));
        result.chat.is_hidden = row.get("is_hidden") == Some(&Value::Bool(true));
        result.chat.pinned = row.get("pinned") == Some(&Value::Bool(true));
        result.chat.has_draft = row
            .get("encrypted_draft_md")
            .and_then(Value::as_str)
            .is_some_and(|v| !v.is_empty());
        if result.chat.has_draft {
            let master = self.master_capability()?;
            let mut preview = Plain::new(None::<String>);
            for name in ["encrypted_draft_preview", "encrypted_draft_md"] {
                if preview.as_ref().is_some_and(|v| !v.is_empty()) {
                    break;
                }
                if let Some(ciphertext) = row.get(name).and_then(Value::as_str) {
                    *preview = match master.decrypt_text(ciphertext).await {
                        Ok(value) => Some(value),
                        Err(Error::Crypto) => None,
                        Err(error) => return Err(error),
                    };
                    admission.check(self)?;
                    scope.check_chat(self, id)?;
                }
            }
            result.chat.draft_preview = match preview.as_ref() {
                Some(value) => draft_preview(value)?,
                None => None,
            };
        }
        result.chat.metadata_updated_at = source
            .get("updated_at")
            .and_then(|v| match v {
                Value::Number(n) => n.as_f64(),
                Value::String(s) => s.trim_matches(js_space).parse::<f64>().ok(),
                _ => None,
            })
            .filter(|v| v.is_finite() && *v > 0.0)
            .map(|v| {
                if v > 1e10 {
                    (v / 1000.0).floor() as u64
                } else {
                    v.floor() as u64
                }
            })
            .unwrap_or(0);
        // Keep an existing list-equivalent canonical row; a changed server row
        // replaces it exactly as before (and so invalidates list freshness).
        let list_neutral = match self.chats.get(id) {
            Some(cached) => self.selected_row_list_equivalent(cached, row, &key)?,
            None => false,
        };
        if !list_neutral {
            self.insert_chat_row(id.into(), row.clone());
        }
        let mut pages: Vec<Plain<Vec<ChatDetailsMessage>>> = Vec::new();
        let mut encrypted_pages = Vec::new();
        let mut cursor = None::<Value>;
        let mut seen = std::collections::HashSet::new();
        let mut more = true;
        let server_messages_v = row.get("messages_v").and_then(Value::as_u64);
        let mut combined_rows = None::<Vec<Value>>;
        let mut cached_used = false;
        if let Some(cache) = &cached {
            let delta = first_messages.take().ok_or(Error::Protocol)?;
            let hit = match delta {
                Ok(page) => assemble_cached(cache, &page, id, &key, limit, server_messages_v).ok(),
                Err(Error::Cancelled) => return Err(Error::Cancelled),
                Err(_) => None,
            };
            admission.check(self)?;
            scope.check_chat(self, id)?;
            match hit {
                Some(hit) => {
                    pages.push(hit.decoded);
                    encrypted_pages.push(hit.visible_rows);
                    more = hit.more;
                    combined_rows = Some(hit.all_rows);
                    cached_used = true;
                }
                None => {
                    if let Some(t) = transaction.as_deref_mut() {
                        t.before_request(self, id);
                    }
                    let page = self.request(Method::GET, &latest_path, None).await;
                    if let Some(t) = transaction.as_deref_mut() {
                        t.after_request(self, id);
                    }
                    first_messages = Some(page);
                }
            }
        }
        for _ in 0..(if cached_used { 0 } else { MAX_PAGES }) {
            let page = match first_messages.take() {
                Some(page) => page?,
                None => {
                    let path = self.chat_details_messages_path(
                        id,
                        requested,
                        limit.is_some(),
                        cursor.as_ref(),
                    )?;
                    if let Some(t) = transaction.as_deref_mut() {
                        t.before_request(self, id);
                    }
                    let page = self.request(Method::GET, &path, None).await;
                    if let Some(t) = transaction.as_deref_mut() {
                        t.after_request(self, id);
                    }
                    page?
                }
            };
            admission.check(self)?;
            scope.check_chat(self, id)?;
            if page
                .get("chat_id")
                .filter(|v| !v.is_null())
                .is_some_and(|v| v.as_str() != Some(id))
            {
                return Err(Error::Forbidden);
            }
            if page.get("oversized_message") == Some(&Value::Bool(true)) {
                return Err(Error::Invalid(
                    "An oversized selected message requires its explicit exact read.",
                ));
            }
            let rows = page
                .get("messages")
                .and_then(Value::as_array)
                .ok_or(Error::Protocol)?;
            if rows.len() > requested {
                return Err(Error::Protocol);
            }
            let actual_bytes = rows
                .iter()
                .try_fold(0usize, |total, row| {
                    monitor::cached_view::bounded_bytes(row, 256 * 1024)
                        .and_then(|size| total.checked_add(size))
                        .filter(|total| *total <= 256 * 1024)
                })
                .ok_or(Error::Protocol)?;
            if page.get("payload_bytes").and_then(Value::as_u64) != Some(actual_bytes as u64) {
                return Err(Error::Protocol);
            }
            let mut decoded = Plain::new(Vec::new());
            let mut encrypted = Vec::new();
            let mut previous = None;
            for raw in rows {
                let (raw, message) = sync::decode_chat_message_stored(raw, id, &key, &mut seen)?;
                let timestamp = raw
                    .get("created_at")
                    .and_then(Value::as_i64)
                    .filter(|v| *v >= 0)
                    .ok_or(Error::Protocol)?;
                let position = (timestamp, message.id.clone());
                if previous.as_ref().is_some_and(|prior| prior >= &position) {
                    return Err(Error::Protocol);
                }
                if let Some(boundary) = &cursor {
                    let boundary = (
                        boundary
                            .get("created_at")
                            .and_then(Value::as_i64)
                            .ok_or(Error::Protocol)?,
                        required(boundary, "message_id")?.to_owned(),
                    );
                    if position >= boundary {
                        return Err(Error::Protocol);
                    }
                }
                previous = Some(position);
                let mut item = project_message(&raw, message, &key)?;
                if item.chat_id.is_empty() {
                    item.chat_id = id.into();
                }
                decoded.push(item);
                encrypted.push(raw);
            }
            more = page
                .get("has_more_before")
                .and_then(Value::as_bool)
                .ok_or(Error::Protocol)?;
            let next = page.get("start_cursor").filter(|v| v.is_object()).cloned();
            if more && (next.is_none() || rows.is_empty() || next == cursor) {
                return Err(Error::Protocol);
            }
            if let Some(next) = &next {
                let first = decoded.first().ok_or(Error::Protocol)?;
                if next.get("created_at").and_then(Value::as_i64) != first.created_at.as_i64()
                    || next.get("message_id").and_then(Value::as_str)
                        != Some(first.client_message_id.as_str())
                {
                    return Err(Error::Protocol);
                }
            }
            pages.push(decoded);
            encrypted_pages.push(encrypted);
            cursor = next;
            if !more || limit.is_some() {
                break;
            }
        }
        if more && limit.is_none() {
            return Err(Error::Invalid(
                "Chat history exceeds the supported window limit.",
            ));
        }
        for page in pages.into_iter().rev() {
            result.messages.extend(page.into_inner());
        }
        if options.content_mode == SavedChatContentMode::PageLocal {
            // Parse the original user mapping JSON once for the existing typed
            // restoration policy, then borrow entries; never clone mapping rows.
            // Stored output retains its validated original JSON losslessly.
            let mut parsed = Plain::new(Vec::<Value>::new());
            for json in result
                .messages
                .iter()
                .filter(|m| m.role == "user")
                .filter_map(|m| m.pii_mappings.as_ref())
            {
                parsed.push(serde_json::from_str(&Zeroizing::new(json.encoded_json()?)).map_err(|_|Error::Unavailable{code:"chat_details_mapping_utf16",reason:"Page-local restoration requires mappings representable by the shared Rust string policy."})?);
            }
            let mappings = parsed
                .iter()
                .filter_map(Value::as_array)
                .flatten()
                .collect::<Vec<_>>();
            let restored = result
                .messages
                .iter()
                .map(|m| {
                    crate::privacy::restore_page_refs(&m.content, &mappings).map(Zeroizing::new)
                })
                .collect::<Result<Vec<_>>>()?;
            for (message, mut text) in result.messages.iter_mut().zip(restored) {
                message.content.zeroize();
                message.content = std::mem::take(&mut *text);
            }
        }
        let embeds_sig = first_embeds.as_ref().ok().and_then(chat_details_cache::embeds_signature);
        let first_embeds_valid = first_embeds.as_ref().is_ok_and(|page| {
            page.get("chat_id").and_then(Value::as_str) == Some(id)
                && page.get("oversized_embed_id").is_none_or(Value::is_null)
        });
        let embed_ids = match (&cached, cached_used, &embeds_sig) {
            (Some(cache), true, Some(sig)) if first_embeds_valid && *sig == cache.embeds_sig => {
                admission.check(self)?;
                scope.check_chat(self, id)?;
                cache.embed_ids.clone()
            }
            _ => {
                self.chat_details_embed_ids(id, &admission, &scope, transaction.as_deref_mut(), first_embeds)
                    .await?
            }
        };
        let record = (|| {
            let last = result.messages.last()?;
            let all_rows = match combined_rows.take() {
                Some(rows) => rows,
                None => encrypted_pages.iter().rev().flatten().cloned().collect(),
            };
            let tail = chat_details_cache::Tail {
                created_at: last.created_at.as_i64()?,
                message_id: last.client_message_id.clone(),
            };
            Some(chat_details_cache::ChatDetailsCache {
                version: 1,
                bounded,
                messages_v: server_messages_v?,
                has_more_before: match (&cached, cached_used) {
                    (Some(cache), true) => cache.has_more_before,
                    _ => more,
                },
                rows: all_rows,
                tail,
                embeds_sig: embeds_sig.clone()?,
                embed_ids: embed_ids.clone(),
            })
        })();
        self.store_chat_details_cache(id, record);
        for message in &mut result.messages {
            if let Some(ids) = embed_ids.get(&sha256(&message.client_message_id)) {
                message.embed_ids = ids.clone();
            }
        }
        if limit.is_none() {
            self.history.insert(
                id.into(),
                encrypted_pages.into_iter().rev().flatten().collect(),
            );
            self.sync_message_windows.remove(id);
            self.selected_first_pages.remove(id);
        }
        memory::coalesce(&mut result.messages)?;
        if let Some(t) = transaction.as_deref_mut() {
            t.terminal = limit.is_none() && !more;
            t.list_neutral = list_neutral;
        }
        result.has_more_before = limit.map(|_| more);
        admission.check(self)?;
        scope.check_chat(self, id)?;
        result.admission = Some(admission);
        Ok(result.into_inner())
    }
    pub async fn read_chat_details_and_fresh_inventory(
        &mut self,
        id: &str,
        options: ChatDetailsOptions,
        proof: FreshChatInventory,
        cancel: &CancellationToken,
    ) -> Result<ChatDetailsRead> {
        self.require_canonical_read_profile()?;
        if cancel.is_cancelled() || self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let mut transaction =
            sync::read_freshness::ReadFreshnessTransaction::begin(self, id, proof, cancel)?;
        let read = tokio::select! {biased;_ = cancel.cancelled()=>return Err(Error::Cancelled),result=self.read_chat_details_in_transaction(id,options,transaction.as_mut())=>result?};
        if cancel.is_cancelled() || self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        read.check(self)?;
        if let Some(transaction) = transaction {
            transaction.commit(self, id)?;
        }
        read.check(self)?;
        Ok(read)
    }
    async fn chat_details_embed_ids(
        &mut self,
        id: &str,
        admission: &full_chat_read::FullChatReadAdmission,
        scope: &AsyncCryptoScope,
        mut transaction: Option<&mut sync::read_freshness::ReadFreshnessTransaction>,
        first_page: Result<Value>,
    ) -> Result<BTreeMap<String, Vec<String>>> {
        let mut output = BTreeMap::<String, Vec<String>>::new();
        let mut cursor = None::<Value>;
        let mut seen = std::collections::HashSet::new();
        let mut first_page = Some(first_page);
        for _ in 0..MAX_PAGES {
            let page = match first_page.take() {
                Some(page) => page?,
                None => {
                    let path = self.chat_details_embeds_path(id, cursor.as_ref())?;
                    if let Some(t) = transaction.as_deref_mut() {
                        t.before_request(self, id);
                    }
                    let page = self.request(Method::GET, &path, None).await;
                    if let Some(t) = transaction.as_deref_mut() {
                        t.after_request(self, id);
                    }
                    page?
                }
            };
            admission.check(self)?;
            scope.check_chat(self, id)?;
            if page.get("chat_id").and_then(Value::as_str) != Some(id) {
                return Err(Error::Forbidden);
            }
            if page.get("oversized_embed_id").is_some_and(|v| !v.is_null()) {
                return Err(Error::Invalid(
                    "Selected embed inventory exceeds its bounded read.",
                ));
            }
            for row in page
                .get("embeds")
                .and_then(Value::as_array)
                .ok_or(Error::Protocol)?
            {
                if row
                    .get("hashed_chat_id")
                    .filter(|v| !v.is_null())
                    .is_some_and(|v| v.as_str() != Some(sha256(id).as_str()))
                {
                    return Err(Error::Forbidden);
                }
                if row
                    .get("parent_embed_id")
                    .is_some_and(|v| !v.is_null() && v.as_str() != Some(""))
                {
                    continue;
                }
                let Some(hash) = row.get("hashed_message_id").and_then(Value::as_str) else {
                    continue;
                };
                let Some(embed) = row
                    .get("embed_id")
                    .or_else(|| row.get("id"))
                    .and_then(Value::as_str)
                    .filter(|v| !v.is_empty() && v.len() <= MAX_FIELD_BYTES)
                else {
                    continue;
                };
                if !seen.insert(embed.to_owned()) {
                    return Err(Error::Protocol);
                }
                output.entry(hash.into()).or_default().push(embed.into());
            }
            if page.get("has_more_before") == Some(&Value::Bool(false)) {
                return Ok(output);
            }
            if page.get("has_more_before") != Some(&Value::Bool(true)) {
                return Err(Error::Protocol);
            }
            let next = page
                .get("start_cursor")
                .filter(|v| v.is_object())
                .cloned()
                .ok_or(Error::Protocol)?;
            if cursor.as_ref() == Some(&next) {
                return Err(Error::Protocol);
            }
            cursor = Some(next);
        }
        Err(Error::Invalid(
            "Selected embed inventory exceeds the supported page limit.",
        ))
    }
}
#[cfg(test)]
#[path = "chat_details_tests.rs"]
mod tests;
#[cfg(test)]
#[path = "chat_details_prefetch_tests.rs"]
mod prefetch_tests;
