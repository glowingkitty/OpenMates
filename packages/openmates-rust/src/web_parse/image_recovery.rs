//! Display recovery of saved image-generation answers whose inline refs were erased.
//!
//! Shared core of the web `parse` unit (browser binding `browser_parse.rs`);
//! mirrors `message_parsing/generatedImageRecovery.ts`. Rust decides which
//! parent embeds must be read and how the recovered document is assembled; the
//! page keeps the awaited embed reads and the account/Team/view cancellation.
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
use serde_json::{json, Map, Value};
use std::collections::HashSet;

use super::blocks::js_ws;

/// True when `value` is an `images` generate/generate_draft record (parent or invocation).
fn is_generate(record: &Value) -> bool {
    record.get("app_id").and_then(Value::as_str) == Some("images")
        && matches!(record.get("skill_id").and_then(Value::as_str), Some("generate" | "generate_draft"))
}

/// Canonical 8-4-4-4-12 hex id (case-insensitive), as the TS `UUID` regex.
fn is_uuid(text: &str) -> bool {
    let groups: Vec<&str> = text.split('-').collect();
    groups.len() == 5
        && groups.iter().zip([8, 4, 4, 4, 12]).all(|(g, n)| g.len() == n && g.bytes().all(|b| b.is_ascii_hexdigit()))
}

/// Paragraph made only of text parts consisting of `!` and whitespace (the corruption signature).
fn is_lost_image_placeholder(node: &Value) -> bool {
    if node.get("type").and_then(Value::as_str) != Some("paragraph") {
        return false;
    }
    match node.get("content").and_then(Value::as_array) {
        Some(parts) if !parts.is_empty() => parts.iter().all(|part| {
            part.get("type").and_then(Value::as_str) == Some("text")
                && part
                    .get("text")
                    .and_then(Value::as_str)
                    .is_some_and(|t| !t.is_empty() && t.chars().all(|c| c == '!' || js_ws(c)))
        }),
        _ => false,
    }
}

/// Activity items of one top-level node (`assistantActivityRuns.activityItems`).
fn activity_items(node: &Value) -> Vec<&Value> {
    let single = node.get("content").and_then(Value::as_array).filter(|c| c.len() == 1);
    let (Some("paragraph"), Some(parts)) = (node.get("type").and_then(Value::as_str), single) else {
        return Vec::new();
    };
    let embed = &parts[0];
    if embed.get("type").and_then(Value::as_str) != Some("embed") {
        return Vec::new();
    }
    let Some(attrs) = embed.get("attrs") else { return Vec::new() };
    match attrs.get("type").and_then(Value::as_str) {
        Some("app-skill-use" | "focus-mode-activation" | "sub-chat-batch") => vec![attrs],
        Some("app-skill-use-group") => attrs.get("groupedItems").and_then(Value::as_array).map(|g| g.iter().collect()).unwrap_or_default(),
        _ => Vec::new(),
    }
}

fn document_content(source: &Value) -> Option<&Vec<Value>> {
    if source.get("type").and_then(Value::as_str) != Some("doc") {
        return None;
    }
    source.get("content").and_then(Value::as_array)
}

/// Parent embed ids whose children must be read; empty unless the source carries the
/// historical corruption signature (a bang-only paragraph) and a generate invocation.
pub fn lost_image_parents(source: &Value) -> Vec<String> {
    let Some(content) = document_content(source) else { return Vec::new() };
    if !content.iter().any(is_lost_image_placeholder) {
        return Vec::new();
    }
    let mut ids: Vec<String> = Vec::new();
    for item in content.iter().flat_map(activity_items).filter(|i| is_generate(i)) {
        let id = match item.get("id") {
            Some(Value::String(s)) => s.clone(),
            _ => item.get("contentRef").and_then(Value::as_str).map(|r| r.strip_prefix("embed:").unwrap_or(r).to_owned()).unwrap_or_default(),
        };
        if is_uuid(&id) && !ids.contains(&id) {
            ids.push(id);
        }
    }
    ids
}

/// Collect every embed identifier already present in the document.
fn collect_seen(node: &Value, seen: &mut HashSet<String>) {
    if let Some(attrs) = node.get("attrs").and_then(Value::as_object) {
        for key in ["embedId", "embedRef", "id", "contentRef"] {
            if let Some(text) = attrs.get(key).and_then(Value::as_str) {
                seen.insert(text.strip_prefix("embed:").unwrap_or(text).to_owned());
            }
        }
    }
    if let Some(children) = node.get("content").and_then(Value::as_array) {
        children.iter().for_each(|child| collect_seen(child, seen));
    }
}

/// Recovered document, or `None` when nothing needs to change.
///
/// `parents` holds the resolved parent embed contents aligned with
/// [`lost_image_parents`] (`null` for an unreadable parent). The source is never
/// modified; existing previews are deduplicated by id and by `generated-images-` ref.
pub fn recover_generated_images(source: &Value, parents: &[Value]) -> Option<Value> {
    if lost_image_parents(source).is_empty() {
        return None;
    }
    let mut seen = HashSet::new();
    collect_seen(source, &mut seen);
    let mut additions: Vec<Map<String, Value>> = Vec::new();
    for parent in parents {
        if !is_generate(parent) || parent.get("status").and_then(Value::as_str) != Some("finished") {
            continue;
        }
        let children = parent.get("embed_ids").and_then(Value::as_array).into_iter().flatten();
        for id in children.filter_map(Value::as_str).filter(|id| !id.is_empty()) {
            let ref_id = format!("generated-images-{}", id.replace('-', "").chars().take(12).collect::<String>());
            if !is_uuid(id) || seen.contains(id) || seen.contains(&ref_id) {
                continue;
            }
            seen.insert(id.to_owned());
            seen.insert(ref_id.clone());
            let mut attrs = Map::new();
            attrs.insert("embedId".into(), json!(id));
            attrs.insert("embedRef".into(), json!(ref_id));
            attrs.insert("appId".into(), json!("images"));
            additions.push(attrs);
        }
    }
    let total = additions.len();
    let run_ref = additions.first()?.get("embedRef").cloned()?;
    let mut content: Vec<Value> = document_content(source)?.iter().filter(|n| !is_lost_image_placeholder(n)).cloned().collect();
    for (index, mut attrs) in additions.into_iter().enumerate() {
        attrs.insert("carouselIndex".into(), json!(index));
        attrs.insert("carouselTotal".into(), json!(total));
        attrs.insert("runRef".into(), run_ref.clone());
        content.push(json!({ "type": "embedPreviewLarge", "attrs": attrs }));
    }
    let mut recovered = source.as_object()?.clone();
    recovered.insert("content".into(), Value::Array(content));
    Some(Value::Object(recovered))
}

/// JSON entry: source document text to a JSON array of parent ids.
///
/// # Errors
/// Returns `protocol` for text that is not JSON.
pub fn lost_image_parents_json(source_json: &str) -> Result<String, String> {
    let source: Value = serde_json::from_str(source_json).map_err(|_| "protocol".to_owned())?;
    serde_json::to_string(&lost_image_parents(&source)).map_err(|_| "protocol".to_owned())
}

/// JSON entry: source plus a JSON array of resolved parents to the recovered document or `null`.
///
/// # Errors
/// Returns `protocol` for malformed JSON or a non-array parent list.
pub fn recover_generated_images_json(source_json: &str, parents_json: &str) -> Result<String, String> {
    let source: Value = serde_json::from_str(source_json).map_err(|_| "protocol".to_owned())?;
    let parents: Vec<Value> = serde_json::from_str(parents_json).map_err(|_| "protocol".to_owned())?;
    serde_json::to_string(&recover_generated_images(&source, &parents)).map_err(|_| "protocol".to_owned())
}
