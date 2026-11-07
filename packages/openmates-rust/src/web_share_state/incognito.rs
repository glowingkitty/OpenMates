//! Incognito chat persistence decisions.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `incognitoChatService.ts`: which fields of a loaded or stored chat are
//! forced, the sessionStorage metadata projection and the accept rule of an
//! in-place message update. Maps, sessionStorage and DOM events stay on the page.

use super::{Decision, array, field, object, str_field};
use serde_json::{Map, Value, json};

/// Fields persisted for each incognito chat; absent ones stay absent (JS `undefined`).
const PERSISTED: [&str; 14] = [
    "encrypted_title", "title", "category", "icon", "created_at", "updated_at",
    "last_edited_overall_timestamp", "unread_count", "messages_v", "title_v", "draft_v",
    "encrypted_draft_md", "encrypted_draft_preview", "waiting_for_metadata",
];

/// Chats read from sessionStorage always carry the incognito flags, even if stored before they existed.
fn normalize(input: &Value) -> Decision {
    let mut chats = Vec::new();
    for chat in array(field(input, "chats")?, "chats")? {
        let mut chat = object(chat, "chat")?.clone();
        chat.insert("is_incognito".into(), json!(true));
        chat.insert("group_key".into(), json!("incognito"));
        chats.push(Value::Object(chat));
    }
    Ok(Value::Array(chats))
}

/// Essential metadata only: messages and server-generated encrypted fields are not persisted.
fn metadata(input: &Value) -> Decision {
    let mut rows = Vec::new();
    for chat in array(field(input, "chats")?, "chats")? {
        let chat = object(chat, "chat")?;
        let mut row = Map::new();
        row.insert("chat_id".into(), chat.get("chat_id").cloned().unwrap_or(Value::Null));
        row.insert("is_incognito".into(), json!(true));
        row.insert("group_key".into(), json!("incognito"));
        for name in PERSISTED {
            if let Some(value) = chat.get(name) {
                row.insert(name.into(), value.clone());
            }
        }
        rows.push(Value::Object(row));
    }
    Ok(Value::Array(rows))
}

/// An update is applied only if it returned a row with the same message and chat ids.
fn update_accepted(input: &Value) -> Decision {
    let accepted = match input.get("next").filter(|n| !n.is_null()) {
        Some(next) => {
            next.get("message_id") == Some(&json!(str_field(input, "message_id")?))
                && next.get("chat_id") == Some(&json!(str_field(input, "chat_id")?))
        }
        None => false,
    };
    Ok(json!(accepted))
}

/// Dispatches the `incognito*` ops.
pub(super) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "incognitoNormalize" => normalize(input),
        "incognitoMetadata" => metadata(input),
        "incognitoUpdateAccepted" => update_accepted(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}
