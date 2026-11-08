//! Project view models assembled after decryption (settings, source, folders/items) and
//! the source create payload. Shared core part of `web_projects`.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `projectSettingsView`, `projectSourceView`, `projectSourceCreate` and
//! `projectContentsView` of `projectRecordPolicy.ts`; the page decrypts, these assemble.

use super::js::{js_string, json_parse, nullish_or, prop, put, req_array, spread, truthy};
use super::records::write_mode;
use super::Outcome;
use serde_json::{Map, Value, json};

/// `parseProjectMetadata`: the decrypted metadata object, `{}` plus a warning otherwise.
fn parse_metadata(text: Option<&Value>, context: &str, warnings: &mut Vec<Value>) -> Value {
    if !truthy(text) {
        return json!({});
    }
    match json_parse(text) {
        Some(parsed @ Value::Object(_)) => parsed,
        Some(_) => {
            warnings.push(json!({ "kind": "non_object", "context": context }));
            json!({})
        }
        None => {
            warnings.push(json!({ "kind": "parse_error", "context": context }));
            json!({})
        }
    }
}

/// `projectSettingsView`: settings view model from the stored record and its decrypted text.
pub(super) fn settings_view(input: &Value) -> Outcome {
    let settings = input.get("settings");
    let mut warnings = Vec::new();
    let parsed = parse_metadata(input.get("settingsText"), "settings", &mut warnings);
    let mode = write_mode(prop(settings, "write_mode")?);
    let policy = match prop(settings, "focus_activation_policy")? {
        Some(Value::String(policy)) if policy == "immediate" || policy == "approval" => policy.as_str(),
        _ => "delayed",
    };
    let mut encrypted = spread(settings);
    encrypted.insert("write_mode".into(), mode.clone());
    Ok(json!({
        "autoSelection": prop(settings, "auto_selection")? != Some(&Value::Bool(false)),
        "focusActivationPolicy": policy,
        "writeMode": mode,
        "selectionRequired": prop(settings, "selection_required")? == Some(&Value::Bool(true)) || mode.is_null(),
        "settings": parsed,
        "encrypted": encrypted,
        "warnings": warnings,
    }))
}

/// `projectSourceView`: source view model from the stored record and its decrypted fields.
pub(super) fn source_view(input: &Value) -> Outcome {
    let source = input.get("source");
    let mut warnings = Vec::new();
    let context = format!("source:{}", js_string(prop(source, "source_id")?));
    let metadata = parse_metadata(input.get("metadataText"), &context, &mut warnings);
    let empty = json!([]);
    let connected = json!("connected");
    let null = Value::Null;
    let mut out = Map::new();
    put(&mut out, "source_id", prop(source, "source_id")?);
    put(&mut out, "source_type", prop(source, "source_type")?);
    put(&mut out, "displayName", input.get("displayName"));
    out.insert("metadata".into(), metadata);
    out.insert("capabilities".into(), nullish_or(prop(source, "capabilities")?, &empty).clone());
    out.insert("status".into(), nullish_or(prop(source, "status")?, &connected).clone());
    out.insert("sourceSessionId".into(), nullish_or(prop(source, "source_session_id")?, &null).clone());
    out.insert("keyEpoch".into(), nullish_or(prop(source, "key_epoch")?, &null).clone());
    put(&mut out, "encrypted", source);
    out.insert("warnings".into(), Value::Array(warnings));
    Ok(Value::Object(out))
}

const ALLOWED_SOURCE_CAPABILITIES: [&str; 4] = ["read", "search", "import", "write_request"];

/// `buildProjectSourceCreatePayload`: allowed capabilities only, default status `connected`.
pub(super) fn source_create(input: &Value) -> Outcome {
    let empty = json!([]);
    let capabilities: Vec<Value> = req_array(Some(nullish_or(input.get("capabilities"), &empty)), "capabilities")?
        .iter()
        .filter(|c| c.as_str().is_some_and(|c| ALLOWED_SOURCE_CAPABILITIES.contains(&c)))
        .cloned()
        .collect();
    let connected = json!("connected");
    let mut out = Map::new();
    put(&mut out, "source_id", input.get("sourceId"));
    put(&mut out, "source_type", input.get("sourceType"));
    put(&mut out, "encrypted_display_name", input.get("encryptedDisplayName"));
    put(&mut out, "encrypted_metadata", input.get("encryptedMetadata"));
    out.insert("capabilities".into(), Value::Array(capabilities));
    out.insert("status".into(), nullish_or(input.get("status"), &connected).clone());
    put(&mut out, "created_at", input.get("timestamp"));
    put(&mut out, "updated_at", input.get("timestamp"));
    put(&mut out, "last_indexed_at", input.get("lastIndexedAt"));
    Ok(Value::Object(out))
}

/// `projectContentsView`: folder and item view models from the stored rows and decrypted fields.
pub(super) fn contents_view(input: &Value) -> Outcome {
    let mut warnings = Vec::new();
    let null = Value::Null;
    let mut folders = Vec::new();
    for folder in req_array(input.get("folders"), "folders")? {
        let record = prop(Some(folder), "record")?;
        let mut out = Map::new();
        put(&mut out, "folder_id", prop(record, "folder_id")?);
        put(&mut out, "name", prop(Some(folder), "name")?);
        out.insert("parentHash".into(), nullish_or(prop(record, "hashed_parent_folder_id")?, &null).clone());
        put(&mut out, "encrypted", record);
        folders.push(Value::Object(out));
    }
    let mut items = Vec::new();
    for item in req_array(input.get("items"), "items")? {
        let record = prop(Some(item), "record")?;
        let item_id = prop(record, "project_item_id")?;
        let mut out = Map::new();
        put(&mut out, "project_item_id", item_id);
        put(&mut out, "item_type", prop(record, "item_type")?);
        put(&mut out, "target_id", prop(Some(item), "targetId")?);
        put(&mut out, "displayName", prop(Some(item), "displayName")?);
        let context = format!("item:{}", js_string(item_id));
        let metadata = parse_metadata(prop(Some(item), "metadataText")?, &context, &mut warnings);
        out.insert("metadata".into(), metadata);
        put(&mut out, "encrypted", record);
        items.push(Value::Object(out));
    }
    Ok(json!({ "folders": folders, "items": items, "warnings": warnings }))
}
