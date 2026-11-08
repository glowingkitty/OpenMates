//! Storage preparation decisions for synced messages (web `chatSyncMessagePrep.ts`).
//!
//! The web client normalizes every message that startup sync (Phase 1b, Phase 2/3,
//! background batches) and the on-demand content batch deliver before it writes
//! the still-encrypted rows to IndexedDB. This module decides, per message, which
//! id field becomes `message_id`, whether the row keeps its own `chat_id` and
//! `role`, whether it is skipped, and how its Directus queue receipt classifies
//! (`paused`, `processing`, `queued`, or none). The page keeps the JSON parsing,
//! the field copy, the in-memory processing fence (read live after the answer)
//! and every write; ciphertext never crosses this boundary. Implements
//! `sync.client.shared-rust-policy` (specifications/architecture/sync).

use serde_json::{json, Value};

use super::{field, parse, truthy, PROTOCOL};

/// Id fields of Phase 1b, Phase 2/3 and background rows, in fallback order.
const PHASED_ID_KEYS: &[&str] = &["message_id", "id"];
/// Id fields of on-demand batch rows, in fallback order.
const BATCH_ID_KEYS: &[&str] = &["message_id", "client_message_id", "id"];

/// Queue classification of a Directus queue receipt (`queue_dispatch_status`
/// plus `queue_dispatch_mode`), in the order the TypeScript loops test it.
fn queue_class(message: &Value) -> &'static str {
    let status = field(message, "queue_dispatch_status").and_then(Value::as_str);
    let mode = field(message, "queue_dispatch_mode").and_then(Value::as_str);
    match status {
        Some("paused") => "paused",
        Some("processing") => "processing",
        Some("queued") if matches!(mode, Some("follow_up" | "steer")) => "queued",
        _ => "none",
    }
}

/// Plans the storage preparation of one list of synced messages.
///
/// Input `{mode: "phased" | "batch", messages: [entry | null]}` where `null`
/// marks a row whose JSON string failed to parse and `entry` carries only the
/// decision fields `{message_id?, client_message_id?, id?, chat_id?, role?,
/// status?, queue_dispatch_status?, queue_dispatch_mode?}` (absent = `undefined`).
/// Output, one per entry: `{"skip": "parse" | "id"}` or `{"skip": null, "idKey",
/// "chatOwn", "roleOwn", "statusOwn", "queue": "paused" | "processing" |
/// "queued" | "none"}` where `idKey` is the first truthy id field.
///
/// # Errors
/// `protocol` when `mode` is unknown, `messages` is not an array or an entry is
/// neither `null` nor an object.
pub fn message_prep_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let id_keys = match field(&input, "mode").and_then(Value::as_str) {
        Some("phased") => PHASED_ID_KEYS,
        Some("batch") => BATCH_ID_KEYS,
        _ => return Err(PROTOCOL.to_string()),
    };
    let messages = field(&input, "messages")
        .and_then(Value::as_array)
        .ok_or_else(|| PROTOCOL.to_string())?;
    let mut plans = Vec::with_capacity(messages.len());
    for message in messages {
        if message.is_null() {
            plans.push(json!({"skip": "parse"}));
            continue;
        }
        if !message.is_object() {
            return Err(PROTOCOL.to_string());
        }
        let Some(id_key) = id_keys.iter().find(|key| truthy(field(message, key))) else {
            plans.push(json!({"skip": "id"}));
            continue;
        };
        plans.push(json!({
            "skip": null,
            "idKey": id_key,
            "chatOwn": truthy(field(message, "chat_id")),
            "roleOwn": truthy(field(message, "role")),
            "statusOwn": truthy(field(message, "status")),
            "queue": queue_class(message),
        }));
    }
    Ok(json!({"plans": plans}).to_string())
}

#[cfg(test)]
#[path = "message_prep_tests.rs"]
mod tests;
