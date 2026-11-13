//! Shared-chat key IndexedDB entry decisions.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors the entry building and read mapping of `sharedChatKeyStorage.ts`.
//! The raw key bytes never enter Rust here: the page stores and reads
//! `key_bytes` itself and only reports whether a key is present.

use super::{Decision, array, field, str_field};
use serde_json::{Value, json};

/// Entry metadata written next to the key bytes (`saveSharedChatKey`).
fn entry_meta(input: &Value) -> Decision {
    let chat_id = str_field(input, "chat_id")?;
    let now_ms = field(input, "now_ms")?.as_f64().ok_or("bad_field:now_ms")?;
    let share_url = match input.get("share_url") {
        Some(Value::String(url)) => json!(url),
        _ => Value::Null,
    };
    Ok(json!({ "chat_id": chat_id, "created_at": (now_ms / 1000.0).floor() as i64, "share_url": share_url }))
}

/// `result?.share_url || null`: an empty string reads as no URL.
fn entry_url(input: &Value) -> Decision {
    Ok(match input.get("entry").and_then(|entry| entry.get("share_url")) {
        Some(Value::String(url)) if !url.is_empty() => json!(url),
        _ => Value::Null,
    })
}

/// Cursor filter of `getAllSharedChatKeys`: rows with an id and key bytes are loaded.
fn loadable(input: &Value) -> Decision {
    let mut ids = Vec::new();
    for (index, entry) in array(field(input, "entries")?, "entries")?.iter().enumerate() {
        let has_id = matches!(entry.get("chat_id"), Some(Value::String(id)) if !id.is_empty());
        let has_key = entry.get("has_key").and_then(Value::as_bool).ok_or("bad_field:has_key")?;
        if has_id && has_key {
            ids.push(json!(index));
        }
    }
    Ok(Value::Array(ids))
}

/// Dispatches the `sharedKey*` ops.
pub(super) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "sharedKeyEntryMeta" => entry_meta(input),
        "sharedKeyEntryUrl" => entry_url(input),
        "sharedKeyLoadable" => loadable(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}
