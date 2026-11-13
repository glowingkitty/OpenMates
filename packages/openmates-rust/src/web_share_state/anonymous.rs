//! Anonymous (guest) chat storage decisions.
//!
//! spec: specifications/features/auth#auth.keys.client-wrapped
//! Mirrors the pure helpers of `anonymousChatStorage.ts`: next message timestamp,
//! assistant message id, chat title from markdown, streaming-adapter chunk
//! boundaries, which history rows are conversation messages, and which plain
//! fields are stripped before a chat row is stored. Lengths and cut points are
//! UTF-16 units like JS; the page slices strings with the returned offsets.
//! The message sort order stays in TS: its comparator is not a total order, so
//! the result depends on V8's TimSort comparison sequence.

use super::{Decision, array, field, js_number, object, str_field, utf16_len};
use crate::web_guest::is_js_space;
use serde_json::{Value, json};

/// Most chunks the streaming adapter splits one response into.
const STREAM_ADAPTER_MAX_CHUNKS: usize = 18;
/// Title length cut-off before the ellipsis.
const TITLE_MAX_UNITS: usize = 50;

/// `Math.max(fallback, latest + 1)` when any message carries a positive timestamp.
fn next_timestamp(input: &Value) -> Decision {
    let fallback = field(input, "fallback")?.as_f64().ok_or("bad_field:fallback")?;
    let mut latest = 0.0_f64;
    for created_at in array(field(input, "created_ats")?, "created_ats")? {
        let value = match created_at {
            Value::Null => 0.0,
            other => other.as_f64().ok_or("bad_field:created_ats")?,
        };
        latest = latest.max(value);
    }
    Ok(js_number(if latest > 0.0 { fallback.max(latest + 1.0) } else { fallback }))
}

/// Last ten UTF-16 units of the chat id (`chatId.slice(-10)`).
fn id_suffix(chat_id: &str) -> String {
    let units: Vec<u16> = chat_id.encode_utf16().collect();
    String::from_utf16_lossy(&units[units.len().saturating_sub(10)..])
}

fn assistant_message_id(input: &Value) -> Decision {
    let chat_id = str_field(input, "chat_id")?;
    let fresh = || format!("{}-{}", id_suffix(chat_id), input["new_uuid"].as_str().unwrap_or_default());
    let response_id = match input.get("response_message_id") {
        Some(Value::String(id)) if !id.is_empty() => id.as_str(),
        _ => return Ok(json!(fresh())),
    };
    if response_id == str_field(input, "user_message_id")? {
        return Ok(json!(fresh()));
    }
    // Stream chunks persist under the server's id; reuse it so reload cannot show both rows.
    if input.get("streamed") == Some(&json!(true)) {
        return Ok(json!(response_id));
    }
    let prefix = format!("{chat_id}-");
    Ok(json!(if response_id.starts_with(&prefix) { response_id.to_owned() } else { format!("{prefix}{response_id}") }))
}

/// Removes every non-greedy "```json ... ```" span (JS `/```json[\s\S]*?```/g`).
fn strip_json_fences(markdown: &str) -> String {
    let mut out = String::new();
    let mut rest = markdown;
    while let Some(start) = rest.find("```json") {
        let after = &rest[start + "```json".len()..];
        let Some(end) = after.find("```") else { break };
        out.push_str(&rest[..start]);
        rest = &after[end + 3..];
    }
    out.push_str(rest);
    out
}

/// First non-blank line, cut to 50 UTF-16 units plus "..."; "Anonymous chat" when none.
///
/// A cut inside a surrogate pair yields U+FFFD, which is what JS `TextEncoder` writes
/// for the lone surrogate before the title is encrypted.
fn title(input: &Value) -> Decision {
    let cleaned = strip_json_fences(str_field(input, "markdown")?);
    let first = cleaned.split('\n').map(|line| line.trim_matches(is_js_space)).find(|line| !line.is_empty());
    let Some(line) = first else { return Ok(json!("Anonymous chat")) };
    if utf16_len(line) <= TITLE_MAX_UNITS {
        return Ok(json!(line));
    }
    let units: Vec<u16> = line.encode_utf16().take(TITLE_MAX_UNITS).collect();
    Ok(json!(format!("{}...", String::from_utf16_lossy(&units))))
}

/// Prefix lengths (UTF-16 units) of the progressive chunks of a streamed adapter response.
fn chunk_ends(input: &Value) -> Decision {
    let length = field(input, "length")?.as_u64().ok_or("bad_field:length")? as usize;
    if length == 0 {
        return Ok(json!([0]));
    }
    let count = STREAM_ADAPTER_MAX_CHUNKS.min(length.div_ceil(48).max(1));
    let size = length.div_ceil(count);
    let mut ends: Vec<usize> = (1..).map(|n| n * size).take_while(|end| *end < length).collect();
    ends.push(length);
    Ok(json!(ends))
}

/// Indexes of rows that are non-failed user/assistant messages with non-blank text.
fn conversation_rows(input: &Value) -> Decision {
    let mut indexes = Vec::new();
    for (index, row) in array(field(input, "rows")?, "rows")?.iter().enumerate() {
        let role = row.get("role").and_then(Value::as_str);
        let text_ok = matches!(row.get("content"), Some(Value::String(text)) if !text.trim_matches(is_js_space).is_empty());
        let failed = row.get("status").and_then(Value::as_str) == Some("failed");
        if !failed && matches!(role, Some("user" | "assistant")) && text_ok {
            indexes.push(json!(index));
        }
    }
    Ok(Value::Array(indexes))
}

/// Chat row without the plaintext fields that are re-derived from encrypted ones.
fn strip_plain(input: &Value) -> Decision {
    let mut chat = object(field(input, "chat")?, "chat")?.clone();
    for name in ["title", "category", "icon", "chat_summary"] {
        chat.remove(name);
    }
    Ok(Value::Object(chat))
}

/// Dispatches the `anonymous*` ops.
pub(super) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "anonymousNextTimestamp" => next_timestamp(input),
        "anonymousAssistantMessageId" => assistant_message_id(input),
        "anonymousTitle" => title(input),
        "anonymousChunkEnds" => chunk_ends(input),
        "anonymousConversationRows" => conversation_rows(input),
        "anonymousStripPlain" => strip_plain(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}
