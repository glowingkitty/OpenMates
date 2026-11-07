//! Per-turn model routing restrictions (port of `modelRoutingRestrictionsForTurn`).
//!
//! spec: specifications/features/chats#chats.message.identity-idempotent
use super::protocol;
use serde_json::{Map, Value, json};

const MAX_MODELS: usize = 256;
const MAX_SERVERS_PER_MODEL: usize = 16;

/// `^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$`
fn model_id(id: &str) -> bool {
    id_shape(id, 160, b"._:/-")
}

/// `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`
fn server_id(id: &str) -> bool {
    id_shape(id, 64, b"_-")
}

fn id_shape(id: &str, max: usize, extra: &[u8]) -> bool {
    let bytes = id.as_bytes();
    // Non-ASCII bytes never match, and the JS limit counts only ASCII-compatible units here.
    !bytes.is_empty() && bytes.len() <= max && bytes[0].is_ascii_alphanumeric()
        && bytes.iter().all(|b| b.is_ascii_alphanumeric() || extra.contains(b))
}

/// A string array within `limit` whose items satisfy `valid`; `None` means invalid.
fn strings(value: &Value, limit: usize, valid: fn(&str) -> bool) -> Option<Vec<String>> {
    let items = value.as_array().filter(|items| items.len() <= limit)?;
    items.iter().map(|item| item.as_str().filter(|s| valid(s)).map(str::to_string)).collect()
}

fn restrictions(profile: &Value) -> Option<Value> {
    let field = |key: &str| profile.get(key).filter(|value| !value.is_null());
    let default_models = json!([]);
    let default_servers = json!({});
    let models = strings(field("disabled_ai_models").unwrap_or(&default_models), MAX_MODELS, model_id)?;
    let servers = field("disabled_ai_servers").unwrap_or(&default_servers).as_object()
        .filter(|servers| servers.len() <= MAX_MODELS)?;
    let mut copied = Map::new();
    for (id, entries) in servers {
        if !model_id(id) {
            return None;
        }
        copied.insert(id.clone(), json!(strings(entries, MAX_SERVERS_PER_MODEL, server_id)?));
    }
    let region = if profile.get("server_region_preference").and_then(Value::as_str) == Some("global") {
        "global"
    } else {
        "eu"
    };
    Some(json!({"disabled_ai_models": models, "disabled_ai_servers": copied, "server_region_preference": region}))
}

/// `{disabled_ai_models?, disabled_ai_servers?, server_region_preference?}` ->
/// `{ok: true, restrictions}` or `{ok: false}` (the page throws `Invalid model routing restrictions`).
pub fn model_routing_restrictions_json(input: &str) -> Result<String, String> {
    let profile: Value = serde_json::from_str(input).map_err(protocol)?;
    if !profile.is_object() {
        return Err("protocol".into());
    }
    Ok(match restrictions(&profile) {
        Some(restrictions) => json!({"ok": true, "restrictions": restrictions}),
        None => json!({"ok": false}),
    }.to_string())
}
