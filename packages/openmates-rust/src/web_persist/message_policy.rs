//! Message-row write policy of the `messages` IndexedDB store (port of
//! `db/messageRowPolicy.ts`): which version of a message wins by status
//! priority, when new encrypted fields force a write, which rows are content
//! duplicates and which cached rows are safe to evict.
//!
//! Values are the JSON form of stored rows: a missing field is JS `undefined`,
//! `null` stays `null`. Typed fields (`queue_revision`, `created_at`) are
//! numbers or absent in real rows; JS string-to-number coercion is not modelled.
//!
//! spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
use serde_json::{json, Value};

use crate::web_sync::{field, num, parse, strict_eq, truthy, PROTOCOL};

/// Fields of an incoming encrypted row that may fill an empty stored field.
const ENCRYPTED_FILL_FIELDS: [&str; 7] = [
    "encrypted_content",
    "encrypted_sender_name",
    "encrypted_category",
    "encrypted_model_name",
    "encrypted_thinking_content",
    "encrypted_thinking_signature",
    "encrypted_pii_mappings",
];

/// Fields whose change alone lets an equal-priority, equal-content row update.
const METADATA_FIELDS: [&str; 6] = [
    "model_name",
    "category",
    "thinking_content",
    "thinking_signature",
    "thinking_token_count",
    "has_thinking",
];

/// Status priority: higher means the message progressed further in its lifecycle.
fn status_priority(status: Option<&Value>) -> f64 {
    match status.and_then(Value::as_str) {
        Some("sending" | "waiting_for_upload" | "waiting_for_internet") => 1.0,
        Some("processing" | "streaming") => 2.0,
        Some("waiting_for_user") => 2.3,
        Some("failed") => 2.5,
        Some("delivered") => 2.8,
        Some("synced") => 3.0,
        Some("queued") => 3.1,
        _ => 0.0,
    }
}

fn is_str(value: Option<&Value>, expected: &str) -> bool {
    value.and_then(Value::as_str) == Some(expected)
}

/// `Number.isSafeInteger`.
fn safe_integer(value: Option<&Value>) -> bool {
    match value {
        Some(Value::Number(n)) => n
            .as_f64()
            .is_some_and(|f| f.fract() == 0.0 && f.abs() <= 9_007_199_254_740_991.0),
        _ => false,
    }
}

/// `(value ?? 0)` as a JS number.
fn revision(value: Option<&Value>) -> f64 {
    match value {
        None | Some(Value::Null) => 0.0,
        other => num(other),
    }
}

/// `shouldUpdateMessage(existing, incoming)`.
pub fn should_update(existing: &Value, incoming: &Value) -> bool {
    let e = |k: &str| field(existing, k);
    let i = |k: &str| field(incoming, k);
    let (e_dispatch, i_dispatch) = (e("queue_dispatch_status"), i("queue_dispatch_status"));
    if is_str(e_dispatch, "paused")
        && (is_str(i_dispatch, "queued") || is_str(i_dispatch, "processing"))
    {
        return false;
    }
    if is_str(e_dispatch, "processing") && is_str(i_dispatch, "queued") {
        return false;
    }
    if (is_str(e("status"), "queued") || is_str(e_dispatch, "processing"))
        && is_str(i_dispatch, "paused")
    {
        return true;
    }
    let (e_rev, i_rev) = (revision(e("queue_revision")), revision(i("queue_revision")));
    if is_str(e("status"), "queued") && safe_integer(i("queue_revision")) {
        if i_rev >= e_rev && is_str(i_dispatch, "processing") {
            return true;
        }
        if i_rev > e_rev {
            return true;
        }
    }
    if is_str(e("status"), "streaming") && is_str(i("status"), "streaming") {
        return true;
    }
    if is_str(e("status"), "waiting_for_user")
        && (is_str(i("status"), "synced") || is_str(i("status"), "delivered"))
    {
        return false;
    }
    let (e_priority, i_priority) = (status_priority(e("status")), status_priority(i("status")));
    if i_priority > e_priority {
        return true;
    }
    if i_priority == e_priority && strict_eq(e("status"), i("status")) {
        if !strict_eq(e("content"), i("content")) {
            return false;
        }
        return METADATA_FIELDS.iter().any(|k| !strict_eq(e(k), i(k)));
    }
    false
}

/// `hasNewEncryptedFields(existing, incomingEncrypted)`.
pub fn has_new_encrypted_fields(existing: &Value, incoming_encrypted: &Value) -> bool {
    ENCRYPTED_FILL_FIELDS
        .iter()
        .any(|k| !truthy(field(existing, k)) && truthy(field(incoming_encrypted, k)))
}

/// `isContentDuplicate(existing, incoming)`.
pub fn is_content_duplicate(existing: &Value, incoming: &Value) -> bool {
    let e = |k: &str| field(existing, k);
    let i = |k: &str| field(incoming, k);
    if !strict_eq(e("chat_id"), i("chat_id")) || !strict_eq(e("role"), i("role")) {
        return false;
    }
    if is_str(e("role"), "user") && !strict_eq(e("message_id"), i("message_id")) {
        return false;
    }
    let assistant = is_str(e("role"), "assistant") && is_str(i("role"), "assistant");
    let threshold = if assistant { 60.0 } else { 300.0 };
    let content_match = if truthy(e("encrypted_content")) && truthy(i("encrypted_content")) {
        strict_eq(e("encrypted_content"), i("encrypted_content"))
    } else {
        truthy(e("content")) && truthy(i("content")) && strict_eq(e("content"), i("content"))
    };
    let time_match = (num(e("created_at")) - num(i("created_at"))).abs() < threshold;
    let sender_match =
        strict_eq(e("encrypted_sender_name"), i("encrypted_sender_name")) || assistant;
    content_match && time_match && sender_match
}

/// `isSafeToEvictMessage(message)`: only confirmed rows without pending turn or
/// embed bundles may leave the cache (`null` is a missing row).
pub fn is_safe_to_evict(message: &Value) -> bool {
    if !message.is_object() {
        return false;
    }
    is_str(field(message, "status"), "synced")
        && !truthy(field(message, "pending_turn_preflight_v1"))
        && !truthy(field(message, "pending_encrypted_turn_preflight_v1"))
        && !truthy(field(message, "pending_encrypted_embed_bundle_v1"))
}

fn protocol_err() -> String {
    PROTOCOL.to_string()
}

fn object<'a>(value: Option<&'a Value>) -> Result<&'a Value, String> {
    value.filter(|v| v.is_object()).ok_or_else(protocol_err)
}

fn list<'a>(input: &'a Value, key: &str) -> Result<&'a Vec<Value>, String> {
    field(input, key)
        .and_then(Value::as_array)
        .ok_or_else(protocol_err)
}

/// `{pairs: [{existing, incoming}]}` -> `{results: [bool]}` (`shouldUpdateMessage`).
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn should_update_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let results = list(&input, "pairs")?
        .iter()
        .map(|pair| {
            Ok(should_update(
                object(field(pair, "existing"))?,
                object(field(pair, "incoming"))?,
            ))
        })
        .collect::<Result<Vec<bool>, String>>()?;
    Ok(json!({ "results": results }).to_string())
}

/// `{existing, incoming, incomingEncrypted}` -> `{shouldUpdate, fillsEncrypted}`:
/// the two checks `saveMessage` runs against the stored row.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn save_decision_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let existing = object(field(&input, "existing"))?;
    let incoming = object(field(&input, "incoming"))?;
    let encrypted = object(field(&input, "incomingEncrypted"))?;
    Ok(json!({
        "shouldUpdate": should_update(existing, incoming),
        "fillsEncrypted": has_new_encrypted_fields(existing, encrypted),
    })
    .to_string())
}

/// `{candidates, message}` -> `{index}`: the first candidate with another
/// `message_id` that is a content duplicate (`findContentDuplicate`), or `null`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn content_duplicate_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let message = object(field(&input, "message"))?;
    let mut index = Value::Null;
    for (position, candidate) in list(&input, "candidates")?.iter().enumerate() {
        let candidate = object(Some(candidate))?;
        if strict_eq(field(candidate, "message_id"), field(message, "message_id")) {
            continue;
        }
        if is_content_duplicate(candidate, message) {
            index = json!(position);
            break;
        }
    }
    Ok(json!({ "index": index }).to_string())
}

/// `{messages: [row | null]}` -> `{results: [bool]}` (`isSafeToEvictMessage`).
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn safe_to_evict_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let results: Vec<bool> = list(&input, "messages")?
        .iter()
        .map(is_safe_to_evict)
        .collect();
    Ok(json!({ "results": results }).to_string())
}
