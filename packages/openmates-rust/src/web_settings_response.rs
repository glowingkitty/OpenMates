//! App settings/memories permission response decisions (shared Rust core Worker
//! `settings` unit), the answer half of `web_settings.rs`.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//!
//! Mirrors the pure decisions of `handlePermissionDialogConfirm` and
//! `saveAppSettingsMemoriesResponseMessage` in
//! `chatSyncServiceHandlersAppSettings.ts` (TS twin: `appSettingsResponsePolicy.ts`,
//! proven by `web_settings_response_ts_vectors.json`). The page keeps decryption,
//! IndexedDB and the WebSocket send; Rust decides how selected keys are routed,
//! which entries are released, the response category counts, what an empty
//! outcome sends and the persisted response system message content.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

/// App id the memory documents use in dialog keys (`MEMORY_RESPONSE_APP_ID`).
const MEMORY_APP_ID: &str = "memory";
const RESPONSE_TYPE: &str = "app_settings_memories_response";

fn protocol<E>(_: E) -> String {
    "protocol".to_string()
}

/// Routes of the selected dialog keys. A key without `-` is skipped; the split is
/// at the first `-` with no emptiness check (unlike the request side), as in TS.
/// `route` is `memory` (local memory documents), `personal_memories` (the
/// `openmates-memories` personal documents, then stored entries) or `entries`.
///
/// # Errors
/// `protocol` when the input is not a JSON array of strings.
pub fn plan_selected_keys_json(selected_keys_json: &str) -> Result<String, String> {
    let keys: Vec<String> = serde_json::from_str(selected_keys_json).map_err(protocol)?;
    let plan: Vec<Value> = keys
        .iter()
        .filter_map(|key| {
            let dash = key.find('-')?;
            let (app_id, item_type) = (&key[..dash], &key[dash + 1..]);
            let route = if app_id == MEMORY_APP_ID {
                "memory"
            } else if app_id == "openmates" && item_type == "memories" {
                "personal_memories"
            } else {
                "entries"
            };
            Some(json!({ "key": key, "appId": app_id, "itemType": item_type, "route": route }))
        })
        .collect();
    Ok(Value::Array(plan).to_string())
}

/// Entry ids released for a category: all of `entry_ids` when `selection_json`
/// is `null` ("all entries"), otherwise those listed in the selection, in order.
///
/// # Errors
/// `protocol` on malformed JSON.
pub fn select_entry_ids_json(entry_ids_json: &str, selection_json: &str) -> Result<String, String> {
    let ids: Vec<String> = serde_json::from_str(entry_ids_json).map_err(protocol)?;
    let selection: Option<Vec<String>> = serde_json::from_str(selection_json).map_err(protocol)?;
    let kept: Vec<String> = ids
        .into_iter()
        .filter(|id| selection.as_ref().is_none_or(|chosen| chosen.contains(id)))
        .collect();
    Ok(json!(kept).to_string())
}

/// Response categories: per selected category the number of released entries
/// whose `app_id`/`item_key` match. Input: `[{appId,itemType}]` and `[{app_id,item_key}]`.
///
/// # Errors
/// `protocol` on malformed JSON.
pub fn response_categories_json(categories_json: &str, released_json: &str) -> Result<String, String> {
    let categories: Vec<Value> = serde_json::from_str(categories_json).map_err(protocol)?;
    let released: Vec<Value> = serde_json::from_str(released_json).map_err(protocol)?;
    let text = |value: &Value, name: &str| value.get(name).and_then(Value::as_str).map(str::to_owned);
    let mut out = Vec::new();
    for cat in &categories {
        let (Some(app_id), Some(item_type)) = (text(cat, "appId"), text(cat, "itemType")) else {
            return Err(protocol(()));
        };
        let count = released
            .iter()
            .filter(|entry| text(entry, "app_id").as_deref() == Some(&app_id) && text(entry, "item_key").as_deref() == Some(&item_type))
            .count();
        out.push(ResponseCategory { app_id, item_type, entry_count: count.into() });
    }
    serde_json::to_string(&out).map_err(protocol)
}

/// What the confirm handler does after collecting `released_count` entries:
/// nothing was released and the request is voice, then an empty response is sent
/// and (with a message id) a `rejected` response is saved; a non-voice empty
/// outcome only cleans up. Otherwise the entries are sent.
///
/// Returns `{kind:"send"}` or `{kind:"empty",sendEmpty,saveRejected}`.
pub fn confirm_outcome_json(released_count: u64, voice: bool, has_message_id: bool) -> String {
    if released_count > 0 {
        return json!({ "kind": "send" }).to_string();
    }
    json!({ "kind": "empty", "sendEmpty": voice, "saveRejected": voice && has_message_id }).to_string()
}

/// Response category as stored in the system message; a struct (not `Value`)
/// because `serde_json` maps sort keys and the TS field order is
/// `appId, itemType, entryCount`.
#[derive(Serialize, Deserialize)]
struct ResponseCategory {
    #[serde(rename = "appId")]
    app_id: String,
    #[serde(rename = "itemType")]
    item_type: String,
    #[serde(rename = "entryCount")]
    entry_count: serde_json::Number,
}

#[derive(Serialize)]
struct ResponseContent<'a> {
    #[serde(rename = "type")]
    kind: &'static str,
    user_message_id: &'a str,
    action: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    categories: Option<Vec<ResponseCategory>>,
}

/// The persisted response system message content (JSON text, field order as
/// `JSON.stringify` of the TS object). `categories` is kept only for `included`.
///
/// # Errors
/// `protocol` on malformed JSON or an action other than `included`/`rejected`.
pub fn response_content_json(user_message_id: &str, action: &str, categories_json: &str) -> Result<String, String> {
    if action != "included" && action != "rejected" {
        return Err(protocol(()));
    }
    let categories: Option<Vec<ResponseCategory>> = serde_json::from_str(categories_json).map_err(protocol)?;
    let content = ResponseContent {
        kind: RESPONSE_TYPE,
        user_message_id,
        action,
        categories: if action == "included" { categories } else { None },
    };
    serde_json::to_string(&content).map_err(protocol)
}

#[cfg(test)]
#[path = "web_settings_response_tests.rs"]
mod tests;
