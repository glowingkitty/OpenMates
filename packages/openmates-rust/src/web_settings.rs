//! App settings/memories permission request policy (the shared Rust core Worker
//! `settings` unit).
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//!
//! The browser keeps IndexedDB, the decrypted entry store, notifications and the
//! dialog; the decisions of `chatSyncServiceHandlersAppSettings.ts` that turn a
//! server request into dialog categories, the "already answered"
//! guard and the persisted request system message are made here with exactly the
//! semantics of `appSettingsRequestPolicy.ts` / `appMemoryRequests.ts` (proven by
//! `web_settings_ts_vectors.json`). Every function takes and returns JSON text;
//! a malformed input is the stable code `protocol`.
#[path = "web_settings_response.rs"]
pub mod response;

use serde::Serialize;
use serde_json::{json, Map, Value};

const REQUEST_TYPE: &str = "app_settings_memories_request";
const RESPONSE_TYPE: &str = "app_settings_memories_response";
const COUNT_SEMANTICS_VERSION: u32 = 1;
const DEFAULT_GRADIENT: &str = "linear-gradient(135deg, #4A90D9 9.04%, #7B68EE 90.06%)";
const MAX_SAFE_INTEGER: f64 = 9_007_199_254_740_991.0;

fn protocol<E>(_: E) -> String {
    "protocol".to_string()
}

/// "preferred_technologies" -> "Preferred technologies" (JS `charAt(0).toUpperCase()` semantics).
pub fn format_display_name(item_type: &str) -> String {
    item_type
        .split('_')
        .enumerate()
        .map(|(index, word)| {
            let mut chars = word.chars();
            match chars.next() {
                // JS `charAt(0)` is a lone surrogate for astral characters: unchanged by `toUpperCase`.
                Some(first) if index == 0 && (first as u32) <= 0xFFFF => {
                    first.to_uppercase().chain(chars).collect::<String>()
                }
                _ => word.to_string(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// CSS gradient for an app id; unknown apps use the default gradient.
pub fn app_gradient(app_id: &str) -> &'static str {
    match app_id {
        "code" => DEFAULT_GRADIENT,
        "travel" => "linear-gradient(135deg, #059DB3 9.04%, #13DAF5 90.06%)",
        "finance" => "linear-gradient(135deg, #119106 9.04%, #15780D 90.06%)",
        "health" => "linear-gradient(135deg, #FD50A0 9.04%, #F42C2D 90.06%)",
        "news" => "linear-gradient(135deg, #F53F5B 9.04%, #DD0B2B 90.06%)",
        "weather" => "linear-gradient(135deg, #005BA5 9.04%, #00A7C9 90.06%)",
        "jobs" => "linear-gradient(135deg, #049363 9.04%, #00C382 90.06%)",
        "legal" => "linear-gradient(135deg, #239CFF 9.04%, #005BA5 90.06%)",
        "files" => "linear-gradient(135deg, #1E3A8A 9.04%, #29BEFB 90.06%)",
        "ai" => "linear-gradient(135deg, #CB7D5D 9.04%, #CB685D 90.06%)",
        "tv" => "linear-gradient(135deg, #8B5CF6 9.04%, #6D28D9 90.06%)",
        "videos" => "linear-gradient(135deg, #EF4444 9.04%, #DC2626 90.06%)",
        "maps" => "linear-gradient(135deg, #10B981 9.04%, #059669 90.06%)",
        "study" => "linear-gradient(135deg, #F59E0B 9.04%, #D97706 90.06%)",
        "plants" => "linear-gradient(135deg, #22C55E 9.04%, #16A34A 90.06%)",
        _ => DEFAULT_GRADIENT,
    }
}

/// JS truthiness of a JSON number (`0`, `-0` and NaN are falsy).
fn number_truthy(n: &serde_json::Number) -> bool {
    n.as_f64().is_some_and(|f| f != 0.0 && !f.is_nan())
}

/// Dialog categories of a server request. `requested_keys_json` is an array of
/// strings, `counts_json` an object key -> stored entry count.
pub fn category_plan_json(requested_keys_json: &str, counts_json: &str) -> Result<String, String> {
    let keys: Vec<String> = serde_json::from_str(requested_keys_json).map_err(protocol)?;
    let counts: Map<String, Value> = serde_json::from_str(counts_json).map_err(protocol)?;
    let mut categories = Vec::new();
    let mut valid_keys = Vec::new();
    for key in keys {
        let Some(dash) = key.find('-') else { continue };
        let (app_id, item_type) = (&key[..dash], &key[dash + 1..]);
        if app_id.is_empty() || item_type.is_empty() {
            continue;
        }
        let count = match counts.get(&key) {
            Some(Value::Number(n)) if number_truthy(n) => Value::Number(n.clone()),
            _ => continue,
        };
        categories.push(json!({
            "key": key, "appId": app_id, "itemType": item_type,
            "displayName": format_display_name(item_type), "entryCount": count,
            "iconGradient": app_gradient(app_id), "selected": true,
        }));
        valid_keys.push(key);
    }
    Ok(json!({ "categories": categories, "validKeys": valid_keys }).to_string())
}

/// True when a system message already answers the request of `user_message_id`.
pub fn is_request_answered_json(system_contents_json: &str, user_message_id: &str) -> Result<bool, String> {
    let contents: Vec<String> = serde_json::from_str(system_contents_json).map_err(protocol)?;
    Ok(contents.iter().any(|content| {
        if content.is_empty() {
            return false;
        }
        serde_json::from_str::<Value>(content).is_ok_and(|parsed| {
            parsed.get("type").and_then(Value::as_str) == Some(RESPONSE_TYPE)
                && parsed.get("user_message_id").and_then(Value::as_str) == Some(user_message_id)
        })
    }))
}

#[derive(Serialize)]
struct RequestCategory<'a> {
    #[serde(rename = "appId")]
    app_id: &'a str,
    #[serde(rename = "itemType")]
    item_type: &'a str,
    #[serde(rename = "entryCount")]
    entry_count: Option<u64>,
}

#[derive(Serialize)]
struct RequestContent<'a> {
    #[serde(rename = "type")]
    kind: &'static str,
    user_message_id: &'a str,
    request_id: &'a str,
    requested_keys: &'a [String],
    categories: Vec<RequestCategory<'a>>,
    count_semantics_version: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    response_transport: Option<&'static str>,
}

#[derive(Serialize)]
struct RequestMessage<'a> {
    message_id: &'a str,
    role: &'static str,
    content: String,
    created_at: &'a Value,
    user_message_id: &'a str,
}

/// UTF-16 code unit order, the order of JS `Array.prototype.sort()` on strings.
fn utf16_cmp(a: &String, b: &String) -> std::cmp::Ordering {
    a.encode_utf16().cmp(b.encode_utf16())
}

/// The persisted memory request system message (`buildMemoryRequestMessage`).
/// Outcome `{kind:"ok",message}` or `{kind:"error",message}` with the TypeScript error text.
pub fn build_request_message_json(
    user_message_id: &str,
    request_id: &str,
    requested_keys_json: &str,
    created_at_json: &str,
    counts_json: &str,
    voice: bool,
) -> Result<String, String> {
    let keys: Vec<String> = serde_json::from_str(requested_keys_json).map_err(protocol)?;
    let created_at: Value = serde_json::from_str(created_at_json).map_err(protocol)?;
    if !created_at.is_number() {
        return Err(protocol(()));
    }
    let counts: Map<String, Value> = serde_json::from_str(counts_json).map_err(protocol)?;
    let error = |message: String| Ok(json!({ "kind": "error", "message": message }).to_string());
    if request_id.is_empty() || user_message_id.is_empty() {
        return error("Memory requests require stable request and user-message identities".into());
    }
    let mut sorted = keys;
    sorted.sort_by(utf16_cmp);
    sorted.dedup();
    let mut categories = Vec::new();
    for key in &sorted {
        let separator = key.find('-');
        let Some(sep) = separator.filter(|&sep| sep > 0 && sep < key.len() - 1) else {
            return error(format!("Invalid memory category key: {key}"));
        };
        let entry_count = counts.get(key).and_then(Value::as_f64).filter(|f| f.fract() == 0.0 && *f >= 0.0 && *f <= MAX_SAFE_INTEGER).map(|f| f as u64);
        categories.push(RequestCategory { app_id: &key[..sep], item_type: &key[sep + 1..], entry_count });
    }
    let content = RequestContent {
        kind: REQUEST_TYPE,
        user_message_id,
        request_id,
        requested_keys: &sorted,
        categories,
        count_semantics_version: COUNT_SEMANTICS_VERSION,
        response_transport: voice.then_some("voice"),
    };
    let message = RequestMessage {
        message_id: request_id,
        role: "system",
        content: serde_json::to_string(&content).map_err(protocol)?,
        created_at: &created_at,
        user_message_id,
    };
    let message = serde_json::to_value(&message).map_err(protocol)?;
    Ok(json!({ "kind": "ok", "message": message }).to_string())
}

#[cfg(test)]
#[path = "web_settings_tests.rs"]
mod tests;
