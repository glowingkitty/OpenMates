//! Fork conversation (`forkChatService.ts`): copy every message up to the
//! fork point into a new chat, re-encrypted with the new chat key. Thinking
//! content, signatures and PII mappings are never copied. The adapter creates
//! and persists the new chat key (ChatKeyManager), reads/writes IndexedDB,
//! drives progress UI and sends the returned frame when connected.
use super::js::{js_collapse_whitespace, utf16_prefix};
use crate::crypto;
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Number, Value, json};

pub const EXPLAIN_SELECTION_MAX_CHARS: usize = 500;

/// A decrypted source message as held by the web client. `content` is the
/// plaintext string (the adapter `JSON.stringify`s non-string content).
#[derive(Clone, Debug, Deserialize)]
pub struct ForkSourceMessage {
    pub message_id: String,
    #[serde(default)]
    pub role: Value,
    #[serde(default)]
    pub created_at: Option<Number>,
    #[serde(default)]
    pub content: Option<String>,
    #[serde(default)]
    pub encrypted_content: Option<String>,
    #[serde(default)]
    pub sender_name: Option<String>,
    #[serde(default)]
    pub category: Option<String>,
    #[serde(default)]
    pub model_name: Option<String>,
}

/// The copied message row (`status: "synced"`, no pair linkage, no plaintext).
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct ForkMessage {
    pub message_id: String,
    pub chat_id: String,
    pub role: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub created_at: Option<Number>,
    pub status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub encrypted_content: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub encrypted_sender_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub encrypted_category: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub encrypted_model_name: Option<String>,
}

fn created(message: &ForkSourceMessage) -> f64 {
    message
        .created_at
        .as_ref()
        .and_then(Number::as_f64)
        .unwrap_or(0.0)
}

/// Stable sort by `created_at ?? 0`, then keep messages up to and including
/// `up_to_message_id`.
pub fn messages_to_copy(
    mut messages: Vec<ForkSourceMessage>,
    up_to_message_id: &str,
) -> Result<Vec<ForkSourceMessage>> {
    messages.sort_by(|a, b| created(a).total_cmp(&created(b)));
    let index = messages
        .iter()
        .position(|m| m.message_id == up_to_message_id)
        .ok_or(Error::Invalid("Fork point message not found"))?;
    messages.truncate(index + 1);
    Ok(messages)
}

/// `newChatId.slice(-10)` (UTF-16 units).
fn chat_suffix(chat_id: &str) -> String {
    let units: Vec<u16> = chat_id.encode_utf16().collect();
    String::from_utf16_lossy(&units[units.len().saturating_sub(10)..])
}

/// `${newChatId.slice(-10)}-${crypto.randomUUID()}`.
pub fn fork_message_id(new_chat_id: &str) -> String {
    format!("{}-{}", chat_suffix(new_chat_id), uuid::Uuid::new_v4())
}

fn encrypt_present(value: Option<&str>, key: &[u8; 32]) -> Result<Option<String>> {
    value
        .filter(|v| !v.is_empty())
        .map(|v| crypto::encrypt_combined(v, key))
        .transpose()
}

pub fn reencrypt_message(
    source: &ForkSourceMessage,
    new_chat_id: &str,
    new_message_id: String,
    key: &[u8; 32],
) -> Result<ForkMessage> {
    let encrypted_content = match source.content.as_deref().filter(|c| !c.is_empty()) {
        Some(content) => Some(crypto::encrypt_combined(content, key)?),
        // Undecrypted blobs (demo chats) are carried as-is, like the web client.
        None => source.encrypted_content.clone().filter(|c| !c.is_empty()),
    };
    Ok(ForkMessage {
        message_id: new_message_id,
        chat_id: new_chat_id.to_owned(),
        role: source.role.clone(),
        created_at: source.created_at.clone(),
        status: "synced",
        encrypted_content,
        encrypted_sender_name: encrypt_present(source.sender_name.as_deref(), key)?,
        encrypted_category: encrypt_present(source.category.as_deref(), key)?,
        encrypted_model_name: encrypt_present(source.model_name.as_deref(), key)?,
    })
}

/// Re-encrypt a batch with fresh message ids (the adapter yields to the
/// event loop between batches and reports progress).
pub fn reencrypt_batch(
    sources: &[ForkSourceMessage],
    new_chat_id: &str,
    key: &[u8; 32],
) -> Result<Vec<ForkMessage>> {
    sources
        .iter()
        .map(|m| reencrypt_message(m, new_chat_id, fork_message_id(new_chat_id), key))
        .collect()
}

/// Category/icon copy: decrypt with the source key and re-encrypt with the
/// new key. `None` (skip, non-fatal) when it does not decrypt or is empty.
pub fn copy_chat_field(
    source_ciphertext: Option<&str>,
    source_key: &[u8; 32],
    new_key: &[u8; 32],
) -> Result<Option<String>> {
    let Some(ciphertext) = source_ciphertext.filter(|c| !c.is_empty()) else {
        return Ok(None);
    };
    match crypto::decrypt_combined(ciphertext, source_key) {
        Ok(plaintext) if !plaintext.is_empty() => {
            crypto::encrypt_combined(&plaintext, new_key).map(Some)
        }
        Ok(_) | Err(Error::Crypto) => Ok(None),
        Err(other) => Err(other),
    }
}

pub struct ForkChat<'a> {
    pub chat_id: &'a str,
    pub encrypted_chat_key: &'a str,
    pub encrypted_title: &'a str,
    pub encrypted_category: Option<&'a str>,
    pub encrypted_icon: Option<&'a str>,
    pub user_id: Option<&'a str>,
    pub message_count: usize,
    pub now_seconds: u64,
}

/// Encrypt the fork title with the new key.
pub fn encrypt_fork_title(title: &str, key: &[u8; 32]) -> Result<String> {
    crypto::encrypt_combined(title, key)
}

/// The new chat row saved to IndexedDB.
pub fn fork_chat_record(chat: &ForkChat<'_>) -> Value {
    let mut record = json!({
        "chat_id": chat.chat_id,
        "encrypted_title": chat.encrypted_title,
        "encrypted_chat_key": chat.encrypted_chat_key,
        "messages_v": chat.message_count,
        "title_v": 1,
        "last_edited_overall_timestamp": chat.now_seconds,
        "unread_count": 0,
        "created_at": chat.now_seconds,
        "updated_at": chat.now_seconds,
    });
    if let Some(user_id) = chat.user_id.filter(|u| !u.is_empty()) {
        record["user_id"] = Value::from(user_id);
    }
    for (field, value) in [
        ("encrypted_category", chat.encrypted_category),
        ("encrypted_icon", chat.encrypted_icon),
    ] {
        if let Some(value) = value.filter(|v| !v.is_empty()) {
            record[field] = Value::from(value);
        }
    }
    record
}

/// `encrypted_chat_metadata` frame (History Injection Flow). Only messages
/// with both an id and encrypted content are sent.
pub fn fork_metadata_payload(chat: &ForkChat<'_>, messages: &[ForkMessage]) -> Value {
    let history: Vec<Value> = messages
        .iter()
        .filter(|m| !m.message_id.is_empty() && m.encrypted_content.is_some())
        .map(|m| {
            let mut entry = json!({
                "message_id": m.message_id,
                "chat_id": chat.chat_id,
                "role": m.role,
                "encrypted_content": m.encrypted_content,
            });
            for (field, value) in [
                ("encrypted_sender_name", &m.encrypted_sender_name),
                ("encrypted_category", &m.encrypted_category),
                ("encrypted_model_name", &m.encrypted_model_name),
            ] {
                if let Some(value) = value {
                    entry[field] = Value::from(value.as_str());
                }
            }
            if let Some(created_at) = &m.created_at {
                entry["created_at"] = Value::Number(created_at.clone());
            }
            entry
        })
        .collect();
    let mut payload = json!({
        "chat_id": chat.chat_id,
        "encrypted_chat_key": chat.encrypted_chat_key,
        "encrypted_title": chat.encrypted_title,
        "message_history": history,
        "versions": {
            "messages_v": chat.message_count,
            "title_v": 1,
            "last_edited_overall_timestamp": chat.now_seconds,
        },
    });
    if let Some(category) = chat.encrypted_category.filter(|v| !v.is_empty()) {
        payload["encrypted_chat_category"] = Value::from(category);
    }
    if let Some(icon) = chat.encrypted_icon.filter(|v| !v.is_empty()) {
        payload["encrypted_icon"] = Value::from(icon);
    }
    payload
}

/// `normalizeExplainSelection`: collapse whitespace, trim, first 500 UTF-16
/// units. A surrogate pair cut by the limit is dropped whole (JavaScript
/// would keep a lone high surrogate, which no encoder can transmit).
pub fn normalize_explain_selection(selected: &str) -> String {
    utf16_prefix(
        &js_collapse_whitespace(selected),
        EXPLAIN_SELECTION_MAX_CHARS,
    )
    .to_owned()
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "fork_tests.rs"]
mod tests;
