//! Composer ghost-suggestion payload validation: port of
//! `decodeComposerGhostSuggestion` (`composerGhostDecode.ts`). The op answers only
//! whether the payload is a usable suggestion; the page re-parses the same text
//! itself so extra fields survive exactly as in the TypeScript path.
//! spec: specifications/features/message-input#message-input.suggestions.contextual
use super::protocol;
use super::utf16::{js_trim, len16};
use serde_json::{Value, json};

/// `{value}` -> `{valid}`. Unparseable JSON, non-objects and any missing, non-string
/// or empty field answer `valid: false` exactly as the TypeScript `null`; `text`
/// must also be non-blank (JS `trim`) and at most 400 UTF-16 units.
///
/// # Errors
/// `protocol` when the payload itself is not `{value: string}`.
pub fn ghost_validate_json(input: &str) -> Result<String, String> {
    let payload: Value = serde_json::from_str(input).map_err(protocol)?;
    let text = payload.get("value").and_then(Value::as_str).ok_or("protocol")?;
    let valid = match serde_json::from_str::<Value>(text) {
        Ok(Value::Object(object)) => {
            let string = |key: &str| object.get(key).and_then(Value::as_str);
            let suggestion = string("text").is_some_and(|t| !js_trim(t).is_empty() && len16(t) <= 400);
            suggestion && ["sourceMessageId", "sourceUserMessageId", "sourceTaskId"].iter().all(|k| string(k).is_some_and(|v| !v.is_empty()))
        }
        _ => false,
    };
    Ok(json!({"valid": valid}).to_string())
}
