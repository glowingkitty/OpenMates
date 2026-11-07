//! Chat metadata derivation of the web chat list.
//!
//! Mirrors `sharedSubChatToChat` of `Chats.svelte` (a shared sub-chat row plus
//! its parent become a list `Chat`).
//! JS `??` semantics: only null or a missing key falls back. Values are passed
//! through untouched so ciphertext and numbers stay byte-identical.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use serde_json::{json, Map, Value};

use super::{parse, protocol};

/// `row[key] ?? default` as a JSON value.
fn or_default(row: &Value, key: &str, default: Value) -> Value {
    match row.get(key) {
        None | Some(Value::Null) => default,
        Some(other) => other.clone(),
    }
}

/// List `Chat` of a shared sub-chat for `{row, parent: {chatId, sharePii, shareHighlights}}`
/// (`sharedSubChatToChat`). `metadata_v` is copied only when the row has the key.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn shared_sub_chat_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let row = value.get("row").filter(|r| r.is_object()).ok_or_else(|| protocol(()))?;
    let parent = value.get("parent").filter(|p| p.is_object()).ok_or_else(|| protocol(()))?;
    let id = row.get("id").filter(|v| v.is_string()).ok_or_else(|| protocol(()))?;
    let parent_id = parent.get("chatId").filter(|v| v.is_string()).ok_or_else(|| protocol(()))?;
    let created = row.get("created_at").cloned().ok_or_else(|| protocol(()))?;
    let updated = or_default(row, "updated_at", created.clone());
    let mut chat = Map::new();
    chat.insert("chat_id".into(), id.clone());
    chat.insert("encrypted_title".into(), or_default(row, "encrypted_title", Value::Null));
    chat.insert("messages_v".into(), or_default(row, "messages_v", json!(0)));
    chat.insert("title_v".into(), or_default(row, "title_v", json!(0)));
    if let Some(metadata_v) = row.get("metadata_v") {
        chat.insert("metadata_v".into(), metadata_v.clone());
    }
    chat.insert(
        "last_edited_overall_timestamp".into(),
        or_default(row, "last_edited_overall_timestamp", updated.clone()),
    );
    chat.insert("unread_count".into(), or_default(row, "unread_count", json!(0)));
    chat.insert("created_at".into(), created);
    chat.insert("updated_at".into(), updated);
    for key in ["encrypted_chat_summary", "encrypted_icon", "encrypted_category"] {
        chat.insert(key.into(), or_default(row, key, Value::Null));
    }
    chat.insert("parent_id".into(), parent_id.clone());
    chat.insert("is_sub_chat".into(), json!(true));
    chat.insert("is_shared_by_others".into(), json!(true));
    chat.insert("share_pii".into(), or_default(parent, "sharePii", json!(false)));
    chat.insert("share_highlights".into(), or_default(parent, "shareHighlights", json!(true)));
    chat.insert("group_key".into(), json!("shared_by_others"));
    chat.insert("budget_limit".into(), or_default(row, "budget_limit", Value::Null));
    chat.insert("budget_spent".into(), or_default(row, "budget_spent", json!(0)));
    Ok(Value::Object(chat).to_string())
}
