//! Replay eligibility of a deferred draft deletion (port of `decideDeferredDeleteReplay`).
//!
//! spec: specifications/features/chats#chats.offline-outbox.ordered-replay
use super::protocol;
use serde_json::{Value, json};

fn flag(value: &Value, key: &str) -> Result<bool, String> {
    value.get(key).and_then(Value::as_bool).ok_or_else(|| "protocol".to_string())
}

/// `{editorOnChat, editorUnsaved, localExists, hasDraft, hasPreview, draftVersion}` -> `{eligible}`.
///
/// A queued deletion may replay only while the editor holds no unsaved edit for the
/// chat and the local row exists with no draft text, no preview and version 0
/// (`draftVersion` null or absent counts as 0, like `draft_v ?? 0`).
pub fn deferred_delete_replay_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let version_zero = match value.get("draftVersion") {
        None | Some(Value::Null) => true,
        Some(number) => number.as_f64().ok_or("protocol")? == 0.0,
    };
    let editor_blocks = flag(&value, "editorOnChat")? && flag(&value, "editorUnsaved")?;
    let eligible = !editor_blocks
        && flag(&value, "localExists")?
        && !flag(&value, "hasDraft")?
        && !flag(&value, "hasPreview")?
        && version_zero;
    Ok(json!({"eligible": eligible}).to_string())
}
