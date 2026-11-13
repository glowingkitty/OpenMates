//! Row decisions of the `chats` IndexedDB store (the only implementation):
//! stored defaults, the keyless draft-only sync shell, candidate-key bookkeeping
//! and the draft-field / Team draft-intent merges. The page reads the row,
//! asks for the decision and writes the patch; no IO here.
//!
//! spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
use serde_json::{json, Value};

use super::jsval::{as_f64, nullish, number, protocol, req_f64, req_object, req_str};
use crate::web_sync::{field, num, parse, strict_eq, truthy};

const MAX_CANDIDATE_KEYS: usize = 5;
const DRAFT_ASSIGN_KEYS: [&str; 5] = [
    "encrypted_draft_md",
    "encrypted_draft_preview",
    "draft_v",
    "ideabucket",
    "ideabucket_processing_window_id",
];

/// `(value ?? fallback)` as a JS number; non-numbers are `NaN` (comparisons false).
fn num_or(value: Option<&Value>, fallback: f64) -> f64 {
    nullish(value).map_or(fallback, |v| as_f64(Some(v)).unwrap_or(f64::NAN))
}

/// `Math.max(a, b)`: `NaN` wins.
fn js_max(a: f64, b: f64) -> f64 {
    if a.is_nan() || b.is_nan() {
        f64::NAN
    } else {
        a.max(b)
    }
}

fn value_or(value: Option<&Value>, fallback: Value) -> Value {
    nullish(value).map_or(fallback, Clone::clone)
}

/// `chatRowDefaults`: `{chat, now}` -> the four fields every stored chat row carries.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn chat_defaults_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let chat = req_object(field(&input, "chat"))?;
    let now = req_f64(field(&input, "now"))?;
    let stamp = nullish(field(chat, "last_edited_overall_timestamp"))
        .or_else(|| nullish(field(chat, "updated_at")))
        .or_else(|| nullish(field(chat, "created_at")))
        .map_or(number(now), Clone::clone);
    Ok(json!({
        "draft_v": value_or(field(chat, "draft_v"), json!(0)),
        "title_v": value_or(field(chat, "title_v"), json!(0)),
        "messages_v": value_or(field(chat, "messages_v"), json!(0)),
        "last_edited_overall_timestamp": stamp,
    })
    .to_string())
}

fn keyless_shell(chat: &Value, existing: Option<&Value>) -> bool {
    let f = |k: &str| field(chat, k);
    let zero = |v: Option<&Value>| as_f64(v) == Some(0.0);
    let draft_md = f("encrypted_draft_md");
    let shell = !truthy(f("team_id"))
        && !truthy(f("chat_visibility"))
        && !truthy(f("is_anonymous"))
        && !truthy(f("anonymous_encrypted_chat_key"))
        && !truthy(f("is_shared"))
        && !truthy(f("is_shared_by_others"))
        && !truthy(f("encrypted_chat_key"))
        && !truthy(f("encrypted_title"))
        && zero(f("messages_v"))
        && num_or(f("draft_v"), 0.0) > 0.0
        && truthy(draft_md)
        && draft_md.and_then(Value::as_str) != Some("null");
    shell
        && match existing {
            None => true,
            Some(e) => {
                let g = |k: &str| field(e, k);
                !truthy(g("encrypted_chat_key"))
                    && !truthy(g("encrypted_title"))
                    && !truthy(g("team_id"))
                    && !truthy(g("chat_visibility"))
                    && zero(g("messages_v"))
            }
        }
}

/// `isExpectedKeylessDraftOnlySyncChat`: `{chat, existing}` -> `{expected}`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn keyless_draft_only_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let chat = req_object(field(&input, "chat"))?;
    let existing = nullish(field(&input, "existing"));
    if let Some(existing) = existing {
        req_object(Some(existing))?;
    }
    Ok(json!({ "expected": keyless_shell(chat, existing) }).to_string())
}

/// `nextCandidateKeys`: `{existing?, blob}` -> `{updated}` (`null` when `blob` is stored already).
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn candidate_keys_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let blob = req_str(field(&input, "blob"))?;
    let mut keys: Vec<&str> = match nullish(field(&input, "existing")) {
        None => Vec::new(),
        Some(Value::Array(items)) => items
            .iter()
            .map(|v| v.as_str().ok_or_else(protocol))
            .collect::<Result<_, _>>()?,
        Some(_) => return Err(protocol()),
    };
    if keys.contains(&blob) {
        return Ok(json!({ "updated": null }).to_string());
    }
    keys.push(blob);
    let skip = keys.len().saturating_sub(MAX_CANDIDATE_KEYS);
    Ok(json!({ "updated": &keys[skip..] }).to_string())
}

fn same_nullish(a: Option<&Value>, b: Option<&Value>) -> bool {
    match (nullish(a), nullish(b)) {
        (None, None) => true,
        (Some(x), Some(y)) => strict_eq(Some(x), Some(y)),
        _ => false,
    }
}

fn undefined_keys(input: &Value) -> Result<Vec<&str>, String> {
    match nullish(field(input, "undefinedKeys")) {
        None => Ok(Vec::new()),
        Some(Value::Array(items)) => items
            .iter()
            .map(|v| v.as_str().ok_or_else(protocol))
            .collect(),
        Some(_) => Err(protocol()),
    }
}

fn merge_result(action: &str, patch: &serde_json::Map<String, Value>, undefined: &[&str]) -> String {
    json!({ "action": action, "patch": patch, "undefinedKeys": undefined }).to_string()
}

/// `mergeDraftFields`: `{chatId, current, fields, missingRow, undefinedKeys?}` ->
/// `{action: none|abort|keep|put, patch, undefinedKeys}`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn draft_merge_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let chat_id = req_str(field(&input, "chatId"))?;
    let current = nullish(field(&input, "current"));
    let missing = nullish(field(&input, "missingRow"));
    let fields = req_object(field(&input, "fields"))?;
    let empty = serde_json::Map::new();
    let Some(base) = current.or(missing) else {
        return Ok(merge_result("none", &empty, &[]));
    };
    if let Some(row) = missing {
        let mismatch = field(row, "chat_id").and_then(Value::as_str) != Some(chat_id)
            || current.is_some_and(|c| !same_nullish(field(c, "team_id"), field(row, "team_id")));
        if mismatch {
            return Ok(merge_result("abort", &empty, &[]));
        }
    }
    let draft_v = field(fields, "draft_v");
    let draft_md = field(fields, "encrypted_draft_md");
    let clears = matches!(draft_md, Some(Value::Null))
        && as_f64(draft_v) == Some(0.0)
        && num_or(field(fields, "cleared_draft_v"), -1.0) >= num_or(field(base, "draft_v"), 0.0);
    if let (Some(current), Some(draft_v)) = (current, draft_v) {
        let incoming = num(Some(draft_v));
        let newer_stored = incoming < num_or(field(current, "draft_v"), 0.0)
            || (nullish(draft_md).is_some()
                && incoming <= num_or(field(current, "cleared_draft_v"), -1.0));
        if !clears && newer_stored {
            return Ok(merge_result("keep", &empty, &[]));
        }
    }
    let marked = undefined_keys(&input)?;
    let mut patch = serde_json::Map::new();
    let mut undefined: Vec<&str> = Vec::new();
    for key in DRAFT_ASSIGN_KEYS {
        if let Some(value) = field(fields, key) {
            patch.insert(key.to_string(), value.clone());
        } else if marked.contains(&key) {
            undefined.push(key);
        }
    }
    if let Some(cleared) = field(fields, "cleared_draft_v") {
        let merged = js_max(num_or(field(base, "cleared_draft_v"), 0.0), num(Some(cleared)));
        patch.insert("cleared_draft_v".into(), number(merged));
    }
    if let Some(updated) = field(fields, "updated_at") {
        let merged = js_max(num_or(field(base, "updated_at"), 0.0), num(Some(updated)));
        patch.insert("updated_at".into(), number(merged));
    }
    Ok(merge_result("put", &patch, &undefined))
}

/// `applyTeamDraftIntent`: `{chat, teamId, pending?, expected?}` -> `{apply, patch, undefinedKeys}`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn team_draft_intent_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let team_id = field(&input, "teamId");
    let expected = nullish(field(&input, "expected"));
    let refuse = json!({ "apply": false, "patch": {}, "undefinedKeys": [] }).to_string();
    let Some(chat) = nullish(field(&input, "chat")) else {
        return Ok(refuse);
    };
    if !strict_eq(field(chat, "team_id"), team_id) {
        return Ok(refuse);
    }
    if let Some(expected) = expected {
        let cipher = field(expected, "cipher");
        let version = field(expected, "version");
        let mismatch = !strict_eq(field(chat, "team_draft_pending_sync"), field(expected, "kind"))
            || (cipher.is_some() && !strict_eq(field(chat, "encrypted_draft_md"), cipher))
            || (version.is_some() && num_or(field(chat, "draft_v"), 0.0) != num(version));
        if mismatch {
            return Ok(refuse);
        }
    }
    let mut patch = serde_json::Map::new();
    let mut undefined: Vec<&str> = Vec::new();
    match field(&input, "pending") {
        Some(pending) => {
            patch.insert("team_draft_pending_sync".into(), pending.clone());
        }
        None => undefined.push("team_draft_pending_sync"),
    }
    if let Some(cleared) = expected.and_then(|e| field(e, "clearedDraftVersion")) {
        let merged = js_max(num_or(field(chat, "cleared_draft_v"), 0.0), num(Some(cleared)));
        patch.insert("cleared_draft_v".into(), number(merged));
    }
    Ok(json!({ "apply": true, "patch": patch, "undefinedKeys": undefined }).to_string())
}
