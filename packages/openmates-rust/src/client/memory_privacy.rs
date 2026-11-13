//! Privacy anonymization of released Memory bodies in the shared core.
//!
//! A Memory released through `app_settings_memories_confirmed` reaches the
//! model like user text, so it is anonymized with the chat's placeholders by
//! the same `crate::privacy::prepare` that protects message text (decision D-5
//! of the assistant-memory-writes plan). Placeholders already mapped in the
//! turn are reused; new mappings are returned so the turn can restore the
//! answer and persist them with the memory response message.
//! Spec: `features.app-memories`.
use super::*;

/// Anonymizes every string inside `value` (object keys are left alone).
fn anonymize_value(
    value: &mut Value,
    memories: &[Value],
    known: &mut Vec<Value>,
    added: &mut Vec<Value>,
) -> Result<()> {
    match value {
        Value::String(text) => {
            if text.is_empty() {
                return Ok(());
            }
            let prepared = crate::privacy::prepare(text, memories, known)?;
            for mapping in prepared.mappings {
                let placeholder = mapping.get("placeholder");
                if !known.iter().any(|k| k.get("placeholder") == placeholder) {
                    known.push(mapping.clone());
                    added.push(mapping);
                }
            }
            *text = prepared.text;
        }
        Value::Array(items) => {
            for item in items {
                anonymize_value(item, memories, known, added)?;
            }
        }
        Value::Object(map) => {
            for item in map.values_mut() {
                anonymize_value(item, memories, known, added)?;
            }
        }
        _ => {}
    }
    Ok(())
}

/// Anonymizes the `content` of each released entry in place and returns the
/// mappings that were added to `existing` (never the existing ones).
///
/// `memories` supplies the user's `pii_detection_settings`, so a disabled
/// detector leaves the body unchanged exactly as for message text. Only
/// `content` is touched; `app_id`/`item_key` are identifiers.
///
/// # Errors
/// Propagates `crate::privacy::prepare` failures; nothing is sent then.
pub fn anonymize_entries(
    entries: &mut [Value],
    memories: &[Value],
    existing: &[Value],
) -> Result<Vec<Value>> {
    let mut known = existing.to_vec();
    let mut added = Vec::new();
    for entry in entries {
        if let Some(content) = entry.get_mut("content") {
            anonymize_value(content, memories, &mut known, &mut added)?;
        }
    }
    Ok(added)
}

/// Mappings stored in a decrypted `app_settings_memories_response` system
/// message (`"pii_mappings"`, chat-key encrypted with the message), or none
/// for any other message. History readers merge these into the chat-level
/// list so a placeholder the model echoed from a Memory body restores.
///
/// # Errors
/// `Error::Protocol` when `pii_mappings` is present but not an array.
pub fn response_mappings(message: &crate::model::Message) -> Result<Vec<Value>> {
    if message.role != "system" {
        return Ok(Vec::new());
    }
    let Ok(content) = serde_json::from_str::<Value>(&message.content) else {
        return Ok(Vec::new());
    };
    if content["type"] != "app_settings_memories_response" {
        return Ok(Vec::new());
    }
    match content.get("pii_mappings") {
        None | Some(Value::Null) => Ok(Vec::new()),
        Some(Value::Array(list)) => Ok(list.clone()),
        Some(_) => Err(Error::Protocol),
    }
}

#[cfg(test)]
#[path = "memory_privacy_tests.rs"]
mod tests;
