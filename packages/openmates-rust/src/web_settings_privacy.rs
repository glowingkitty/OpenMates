//! Hydration plan of one decrypted privacy settings entry (shared core; served by
//! the shared Rust core Worker's `settings` unit through openmates-browser-bindings).
//! Mirrors `privacyEntryPolicy.ts` (the inline defaults of personalDataStore's
//! `performLoadFromStorage`): per item type, which `??` / `||` defaults fill the
//! parsed entry data. The page keeps decryption, IndexedDB, the owner/mutation
//! guards and the stores; it passes one entry in and applies the returned plan.
//! Vectors: web_settings_privacy_ts_vectors.json.
//!
//! Known difference: a non-object `categories` value is ignored here, whereas
//! the TypeScript object spread would copy the indices of a string or array.
//! spec: sdk.client.thin-platform-boundary
use serde_json::{json, Map, Value};

const PII_SETTINGS_ITEM_TYPE: &str = "pii_detection_settings";
const LOCATION_SETTINGS_ITEM_TYPE: &str = "location_settings";
const PERSONAL_DATA_ITEM_TYPE: &str = "personal_data_entry";

fn protocol<E>(_: E) -> String {
    "protocol".to_string()
}

/// JS truthiness of a JSON value (`0`, NaN, `""`, `null`, `false` are falsy).
fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0 && !f.is_nan()),
        Value::String(s) => !s.is_empty(),
        Value::Array(_) | Value::Object(_) => true,
    }
}

/// `data[name] ?? fallback` (JS nullish: only `null`/missing take the fallback).
fn nullish(data: &Value, name: &str, fallback: Value) -> Value {
    match data.get(name) {
        None | Some(Value::Null) => fallback,
        Some(value) => value.clone(),
    }
}

/// `data[name] || fallback` (JS logical or: every falsy value takes the fallback).
fn or_else(data: &Value, name: &str, fallback: Value) -> Value {
    match data.get(name) {
        Some(value) if truthy(value) => value.clone(),
        _ => fallback,
    }
}

/// Plan for one decrypted privacy entry. `data_json` is the parsed entry body,
/// `default_categories_json` the default PII category toggles (an object).
///
/// Returns `{kind:"pii",masterEnabled,enhancedEnabled,categories}`,
/// `{kind:"location",impreciseByDefault}`,
/// `{kind:"personal",type,title,textToHide,replaceWith,enabled[,addressLines]}`
/// or `{kind:"other"}`.
///
/// # Errors
/// `protocol` on malformed JSON, non-object defaults, or `null` data for a known
/// item type (the TypeScript property read throws there).
pub fn plan_privacy_entry_json(item_type: &str, data_json: &str, default_categories_json: &str) -> Result<String, String> {
    let data: Value = serde_json::from_str(data_json).map_err(protocol)?;
    let defaults: Map<String, Value> = serde_json::from_str(default_categories_json).map_err(protocol)?;
    let known = [PII_SETTINGS_ITEM_TYPE, LOCATION_SETTINGS_ITEM_TYPE, PERSONAL_DATA_ITEM_TYPE].contains(&item_type);
    if known && data.is_null() {
        return Err(protocol(()));
    }
    let plan = match item_type {
        PII_SETTINGS_ITEM_TYPE => {
            let mut categories = defaults;
            if let Some(Value::Object(overrides)) = data.get("categories") {
                for (name, value) in overrides {
                    categories.insert(name.clone(), value.clone());
                }
            }
            json!({
                "kind": "pii",
                "masterEnabled": nullish(&data, "masterEnabled", Value::Bool(true)),
                "enhancedEnabled": nullish(&data, "enhancedEnabled", Value::Bool(true)),
                "categories": categories,
            })
        }
        LOCATION_SETTINGS_ITEM_TYPE => {
            json!({ "kind": "location", "impreciseByDefault": nullish(&data, "impreciseByDefault", Value::Bool(true)) })
        }
        PERSONAL_DATA_ITEM_TYPE => {
            let mut plan = json!({
                "kind": "personal",
                "type": or_else(&data, "type", json!("custom")),
                "title": or_else(&data, "title", json!("")),
                "textToHide": or_else(&data, "textToHide", json!("")),
                "replaceWith": or_else(&data, "replaceWith", json!("")),
                "enabled": nullish(&data, "enabled", Value::Bool(true)),
            });
            if let Some(lines) = data.get("addressLines") {
                plan["addressLines"] = lines.clone();
            }
            plan
        }
        _ => json!({ "kind": "other" }),
    };
    Ok(plan.to_string())
}

#[cfg(test)]
#[path = "web_settings_privacy_tests.rs"]
mod tests;
