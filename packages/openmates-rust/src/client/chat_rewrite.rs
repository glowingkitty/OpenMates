//! Personal saved-chat fork, rewind and retry for first-party session clients.
//! One exact full-history read of the selected chat, never an account sync.
//! Fork copies are re-encrypted under a fresh chat key wrapped by the master
//! key; rewind deletes only server rows after an explicit boundary.
use super::{
    plaintext::{Plain, Wipe},
    sync::decrypt_optional,
    *,
};
use zeroize::Zeroizing;

/// Team, Direct and draft-only chats are refused before any mutation.
pub const PERSONAL_ONLY: &str = "Only personal saved chats are supported for fork, rewind, and retry.";
const KEY_MISSING: &str = "Saved chat does not include encrypted chat key material.";
const REWIND_CONFIRM: &str = "Rewinding a chat requires confirmDestructive=true.";
const RETRY_CONFIRM: &str = "Retrying a chat requires confirmDestructive=true.";
const NO_RETRY: &str = "No retryable user message found for this chat.";
const FIRST_RETRY: &str = "Cannot retry a chat whose first message is the failed user turn.";

/// The decrypted selected chat plus its aligned ciphertext rows and version.
/// Plaintext is wiped on drop; rows stay server ciphertext.
pub struct ChatRewriteState {
    chat: Chat,
    rows: Vec<Value>,
    messages_v: u64,
}
impl Drop for ChatRewriteState {
    fn drop(&mut self) {
        self.chat.wipe();
    }
}
impl ChatRewriteState {
    /// Build the state from an owner-scoped chat row, its complete ciphertext
    /// history and the already opened chat key. Used by the explicit API-key
    /// backend (`GET /v1/sdk/chats/{id}`); rows are decoded and placeholders
    /// restored by the same authenticated decoder as the session read.
    pub(crate) fn from_encrypted_rows(
        chat_id: &str,
        chat_row: &Value,
        raw_rows: &[Value],
        key: &[u8; 32],
    ) -> Result<Self> {
        if text(chat_row, "id") != chat_id {
            return Err(Error::Forbidden);
        }
        if text(chat_row, "chat_visibility") == "direct" || !text(chat_row, "hashed_team_id").is_empty() {
            return Err(Error::Invalid(PERSONAL_ONLY));
        }
        if text(chat_row, "encrypted_chat_key").is_empty() {
            return Err(Error::Invalid(KEY_MISSING));
        }
        let mut seen = std::collections::HashSet::new();
        let mut rows = Vec::with_capacity(raw_rows.len());
        let mut chat = Plain::new(Chat {
            id: chat_id.to_owned(),
            title: decrypt_optional(chat_row, "encrypted_title", key)?,
            category: String::new(),
            messages: Vec::with_capacity(raw_rows.len()),
        });
        for raw in raw_rows {
            let (row, message) = super::sync::decode_chat_message(raw, chat_id, key, &mut seen)?;
            rows.push(row);
            chat.messages.push(message);
        }
        super::sync::restore_chat_tokens_from_rows(&mut *chat, key, &rows)?;
        let messages_v = chat_row
            .get("messages_v")
            .and_then(Value::as_u64)
            .unwrap_or(rows.len() as u64);
        Ok(Self {
            chat: chat.into_inner(),
            rows,
            messages_v,
        })
    }
    pub fn chat_id(&self) -> &str {
        &self.chat.id
    }
    pub fn title(&self) -> &str {
        &self.chat.title
    }
    /// Chronological decrypted messages (PII placeholders restored for display).
    pub fn messages(&self) -> &[Message] {
        &self.chat.messages
    }
    /// Expected server `messages_v`; the loaded count when the row omits it.
    pub fn messages_v(&self) -> u64 {
        self.messages_v
    }
    /// Exact or prefix message selector, matching the npm CLI boundary rule.
    /// npm selects by the server message ID (what `chats show --json`
    /// prints); the decoded client message ID is accepted as well.
    pub fn boundary_index(&self, message_id: &str) -> Option<usize> {
        if message_id.is_empty() {
            return None;
        }
        let server = self.rows.iter().position(|row| {
            ["message_id", "id"].into_iter().map(|field| text(row, field)).any(|id| {
                !id.is_empty() && (id == message_id || id.starts_with(message_id))
            })
        });
        server.or_else(|| find_message_boundary_index(&self.chat.messages, message_id))
    }
    /// The server's identity for a boundary row (message_id first, as the
    /// backend's boundary lookup reads it).
    pub fn server_message_id(&self, index: usize) -> Result<String> {
        let row = self.rows.get(index).ok_or(Error::Invalid("Message boundary is out of range."))?;
        server_message_id(row, &self.chat.messages[index].id)
    }
    /// The boundary before the newest unanswered user turn and that turn's text.
    pub fn retry_target(&self) -> Result<ChatRetryTarget> {
        match find_retryable_user_message_index(&self.chat.messages) {
            None => Err(Error::Invalid(NO_RETRY)),
            Some(0) => Err(Error::Invalid(FIRST_RETRY)),
            Some(index) => Ok(ChatRetryTarget {
                boundary_index: index - 1,
                prompt: Zeroizing::new(self.chat.messages[index].content.clone()),
            }),
        }
    }
}
/// Retry plan: rewind to `boundary_index`, then resend `prompt`.
pub struct ChatRetryTarget {
    pub boundary_index: usize,
    pub prompt: Zeroizing<String>,
}

/// First message whose id equals, or starts with, the selector.
pub fn find_message_boundary_index(messages: &[Message], message_id: &str) -> Option<usize> {
    if message_id.is_empty() {
        return None;
    }
    messages
        .iter()
        .position(|m| m.id == message_id || m.id.starts_with(message_id))
}
/// Newest user message with no later assistant message.
pub fn find_retryable_user_message_index(messages: &[Message]) -> Option<usize> {
    let mut later_assistant = false;
    for (index, message) in messages.iter().enumerate().rev() {
        let role = message.role.to_lowercase();
        if role == "assistant" {
            later_assistant = true;
        }
        if role == "user" && !later_assistant {
            return Some(index);
        }
    }
    None
}
pub(super) fn default_sender_name(role: &str) -> &'static str {
    match role {
        "assistant" => "Assistant",
        "system" => "System",
        _ => "User",
    }
}
fn server_message_id(row: &Value, fallback: &str) -> Result<String> {
    ["message_id", "client_message_id", "id"]
        .into_iter()
        .map(|field| text(row, field))
        .find(|id| !id.is_empty())
        .or(Some(fallback).filter(|id| !id.is_empty()))
        .map(str::to_owned)
        .ok_or(Error::Protocol)
}
fn timestamp(row: &Value, now: i64) -> i64 {
    row.get("created_at")
        .and_then(Value::as_i64)
        .filter(|value| *value != 0)
        .unwrap_or(now)
}
/// Encrypt the source slice `rows[..=boundary]` for a new chat under `key`.
/// Stored content keeps its placeholders; their mappings are re-encrypted.
pub(super) fn fork_messages(
    rows: &[Value],
    source_key: &[u8; 32],
    new_chat_id: &str,
    key: &[u8; 32],
    now: i64,
) -> Result<Vec<Value>> {
    let mut ids = BTreeMap::<String, String>::new();
    let mut out = Vec::with_capacity(rows.len());
    for row in rows {
        let role = required(row, "role")?.to_owned();
        let id = uuid::Uuid::new_v4().to_string();
        for field in ["message_id", "client_message_id", "id"] {
            let old = text(row, field);
            if !old.is_empty() {
                ids.insert(old.to_owned(), id.clone());
            }
        }
        let content = Plain::new(decrypt_optional(row, "encrypted_content", source_key)?);
        let mut sender = Plain::new(decrypt_optional(row, "encrypted_sender_name", source_key)?);
        if sender.is_empty() {
            sender.push_str(default_sender_name(&role));
        }
        let created = timestamp(row, now);
        let mut message = json!({
            "client_message_id": id,
            "message_id": id,
            "chat_id": new_chat_id,
            "encrypted_content": crypto::encrypt_combined(&content, key)?,
            "encrypted_sender_name": crypto::encrypt_combined(&sender, key)?,
            "role": role,
            "created_at": created,
            "updated_at": created,
        });
        for (source, target) in [
            ("encrypted_category", "encrypted_category"),
            ("encrypted_model_name", "encrypted_model_name"),
            ("encrypted_pii_mappings", "encrypted_pii_mappings"),
        ] {
            let value = Plain::new(decrypt_optional(row, source, source_key)?);
            if !value.is_empty() {
                message[target] = json!(crypto::encrypt_combined(&value, key)?);
            }
        }
        if let Some(mapped) = ids.get(text(row, "user_message_id")) {
            message["user_message_id"] = json!(mapped);
        }
        out.push(message);
    }
    Ok(out)
}

/// `POST …/chats/{id}/fork` body shared by the session and API-key routes:
/// the source slice re-encrypted under `key`, whose wrapped form the caller
/// supplies (session master capability or API-key-unwrapped account key).
pub(crate) fn fork_request(
    state: &ChatRewriteState,
    boundary_index: usize,
    title: Option<&str>,
    source_key: &[u8; 32],
    key: &[u8; 32],
    wrapped_key: String,
) -> Result<Value> {
    let from = state.server_message_id(boundary_index)?;
    let new_id = uuid::Uuid::new_v4().to_string();
    let now = i64::try_from(now_ms() / 1000).map_err(|_| Error::Protocol)?;
    let messages = fork_messages(&state.rows[..=boundary_index], source_key, &new_id, key, now)?;
    let default_title;
    let title = match title {
        Some(title) => title,
        None => {
            let source = if state.title().is_empty() { state.chat_id() } else { state.title() };
            default_title = Zeroizing::new(format!("Fork of {source}"));
            default_title.as_str()
        }
    };
    Ok(json!({
        "protocol_version": 1,
        "from_message_id": from,
        "new_chat_id": new_id,
        "expected_source_messages_v": state.messages_v(),
        "encrypted_chat_metadata": {
            "id": new_id,
            "encrypted_title": crypto::encrypt_combined(title, key)?,
            "encrypted_chat_key": wrapped_key,
            "created_at": now,
            "updated_at": now,
        },
        "encrypted_messages": messages,
    }))
}
/// `POST …/chats/{id}/rewind` body; a destructive rewind needs confirmation.
pub(crate) fn rewind_request(
    state: &ChatRewriteState,
    boundary_index: usize,
    dry_run: bool,
    confirm_destructive: bool,
) -> Result<Value> {
    if !dry_run && !confirm_destructive {
        return Err(Error::Invalid(REWIND_CONFIRM));
    }
    let to = state.server_message_id(boundary_index)?;
    Ok(json!({
        "protocol_version": 1,
        "to_message_id": to,
        "expected_messages_v": state.messages_v(),
        "dry_run": dry_run,
        "confirm_destructive": confirm_destructive,
    }))
}
/// Retry plan check shared by both backends: confirmation, then the target.
pub(crate) fn retry_plan(
    state: &ChatRewriteState,
    dry_run: bool,
    confirm_destructive: bool,
) -> Result<ChatRetryTarget> {
    if !dry_run && !confirm_destructive {
        return Err(Error::Invalid(RETRY_CONFIRM));
    }
    state.retry_target()
}

impl Client {
    /// Read exactly the selected personal chat (full history) for a rewrite.
    pub async fn chat_rewrite_state(&mut self, chat_id: &str) -> Result<ChatRewriteState> {
        if self.team()?.is_some() {
            return Err(Error::Invalid(PERSONAL_ONLY));
        }
        let chat = Plain::new(self.open_chat(chat_id).await?);
        if self.team()?.is_some() || chat.id != chat_id {
            return Err(Error::Forbidden);
        }
        let row = self.chats.get(chat_id).ok_or(Error::Offline)?;
        if text(row, "chat_visibility") == "direct" {
            return Err(Error::Invalid(PERSONAL_ONLY));
        }
        if text(row, "encrypted_chat_key").is_empty() {
            return Err(Error::Invalid(KEY_MISSING));
        }
        let rows = self.history.get(chat_id).cloned().ok_or(Error::Offline)?;
        if rows.len() != chat.messages.len() {
            return Err(Error::Protocol);
        }
        let messages_v = row
            .get("messages_v")
            .and_then(Value::as_u64)
            .unwrap_or(rows.len() as u64);
        Ok(ChatRewriteState {
            chat: chat.into_inner(),
            rows,
            messages_v,
        })
    }
    /// Copy messages through `boundary_index` into a new encrypted chat.
    pub async fn fork_chat(
        &mut self,
        state: &ChatRewriteState,
        boundary_index: usize,
        title: Option<&str>,
    ) -> Result<Value> {
        state.server_message_id(boundary_index)?;
        self.verify_private_operation()?;
        let row = self.chats.get(state.chat_id()).cloned().ok_or(Error::Offline)?;
        let master = self.master_capability()?;
        let source_key = self.chat_key_with_capability(&row, &master).await?;
        let key = crypto::random_key();
        let wrapped = master.encrypt_server_bytes(&key[..]).await?;
        let body = fork_request(state, boundary_index, title, &source_key, &key, wrapped)?;
        self.verify_private_operation()?;
        let path = format!("/v1/chats/{}/fork", segment(state.chat_id()));
        let result = self.request(Method::POST, &path, Some(body)).await?;
        self.invalidate_chat_list_freshness();
        Ok(result)
    }
    /// Delete rows after `boundary_index`; a dry run only reports the plan.
    pub async fn rewind_chat(
        &mut self,
        state: &ChatRewriteState,
        boundary_index: usize,
        dry_run: bool,
        confirm_destructive: bool,
    ) -> Result<Value> {
        let body = rewind_request(state, boundary_index, dry_run, confirm_destructive)?;
        self.verify_private_operation()?;
        let path = format!("/v1/chats/{}/rewind", segment(state.chat_id()));
        let result = self.request(Method::POST, &path, Some(body)).await?;
        if !dry_run {
            let id = state.chat_id();
            self.history.remove(id);
            self.sync_message_windows.remove(id);
            self.selected_first_pages.remove(id);
            self.invalidate_chat_list_freshness();
        }
        Ok(result)
    }
    /// Rewind before the newest unanswered user turn. Returns the server result
    /// and, unless dry-run, the prompt the caller resends in the same chat.
    pub async fn retry_chat(
        &mut self,
        state: &ChatRewriteState,
        dry_run: bool,
        confirm_destructive: bool,
    ) -> Result<(Value, Option<Zeroizing<String>>)> {
        let target = retry_plan(state, dry_run, confirm_destructive)?;
        let result = self
            .rewind_chat(state, target.boundary_index, dry_run, confirm_destructive)
            .await?;
        Ok((result, (!dry_run).then_some(target.prompt)))
    }
}

#[cfg(test)]
#[path = "chat_rewrite_tests.rs"]
mod tests;
