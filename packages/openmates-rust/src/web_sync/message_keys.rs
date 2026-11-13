//! Message key admission of synced messages (mirrors the decision part of
//! `chatSyncMessageKeyGuard.ts`): which synced messages carry chat-key
//! ciphertext, grouped per chat in arrival order, and the one ciphertext the
//! page must authenticate with the resolved chat key before persisting.
//!
//! Invariant: encrypted messages are persisted only when a chat key decrypts a
//! sample of them; otherwise the chat's messages are skipped and re-synced, so
//! IndexedDB never holds ciphertext under an unknown key.
use serde_json::{json, Map, Value};

use super::{field, parse, strict_eq, PROTOCOL};

/// Message fields encrypted with the chat key, in the TS probe order.
pub const ENCRYPTED_MESSAGE_FIELDS: [&str; 7] = [
    "encrypted_content",
    "encrypted_sender_name",
    "encrypted_category",
    "encrypted_model_name",
    "encrypted_thinking_content",
    "encrypted_thinking_signature",
    "encrypted_pii_mappings",
];

fn encrypted_values(message: &Value) -> impl Iterator<Item = &str> {
    ENCRYPTED_MESSAGE_FIELDS.iter().filter_map(move |name| {
        field(message, name)
            .and_then(Value::as_str)
            .filter(|v| !v.is_empty())
    })
}

struct Group<'a> {
    chat_id: Option<&'a Value>,
    indices: Vec<usize>,
    sample: Option<&'a str>,
}

/// Plan for `{messages}`: one `{chatId, indices, needsKey, sample}` per chat in
/// first-arrival order. `needsKey` is false when no message carries chat-key
/// ciphertext (persist without a key); otherwise `sample` is the first
/// non-empty ciphertext in message/field order.
///
/// # Errors
/// `protocol` when `messages` is not an array of objects.
pub fn plan_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let messages = field(&input, "messages")
        .and_then(Value::as_array)
        .ok_or_else(|| PROTOCOL.to_string())?;
    let mut groups: Vec<Group> = Vec::new();
    for (index, message) in messages.iter().enumerate() {
        if !message.is_object() {
            return Err(PROTOCOL.to_string());
        }
        let chat_id = field(message, "chat_id");
        let position = groups.iter().position(|g| match (g.chat_id, chat_id) {
            (None, None) => true,
            (a, b) => a.is_some() && b.is_some() && strict_eq(a, b),
        });
        let group = match position {
            Some(position) => &mut groups[position],
            None => {
                groups.push(Group {
                    chat_id,
                    indices: Vec::new(),
                    sample: None,
                });
                groups.last_mut().expect("a group was just pushed")
            }
        };
        group.indices.push(index);
        if group.sample.is_none() {
            group.sample = encrypted_values(message).next();
        }
    }
    let plan: Vec<Value> = groups
        .into_iter()
        .map(|g| {
            let mut out = Map::new();
            if let Some(chat_id) = g.chat_id {
                out.insert("chatId".into(), chat_id.clone());
            }
            out.insert("indices".into(), json!(g.indices));
            out.insert("needsKey".into(), json!(g.sample.is_some()));
            out.insert("sample".into(), json!(g.sample));
            Value::Object(out)
        })
        .collect();
    Ok(Value::Array(plan).to_string())
}
