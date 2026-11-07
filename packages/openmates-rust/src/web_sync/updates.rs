//! Chat-update and recovery decision helpers of the web sync policy (shared
//! Rust core Worker `sync` unit). Mirrors `chatSyncUpdatesLogic.ts`, extracted
//! from `chatSyncServiceHandlersChatUpdates.ts` / `chatSyncServiceHandlersRecovery.ts`:
//! the notification preview of an assistant reply and the validation of the
//! thinking fields of a recovered message. Proven against TS-generated vectors
//! (`updates_ts_vectors.json`). Spec: `feature.chats`, `surface.sdk`
//! (sdk.client.thin-platform-boundary).
use regex::Regex;
use serde_json::{Value, json};
use std::sync::OnceLock;

use super::{PROTOCOL, field, parse};

/// Longest preview in UTF-16 units before the `...` suffix (`MESSAGE_PREVIEW_MAX_LENGTH`).
pub const MESSAGE_PREVIEW_MAX_LENGTH: usize = 120;
/// Preview of a reply that has no text left after stripping.
const EMPTY_PREVIEW: &str = "New AI response ready";

/// JS `\s` / `String.prototype.trim` white space (the regex crate's `\s` differs:
/// it has U+0085 and lacks U+FEFF).
const JS_WS: &str = r"[\t\n\x0B\x0C\r \u{A0}\u{1680}\u{2000}-\u{200A}\u{2028}\u{2029}\u{202F}\u{205F}\u{3000}\u{FEFF}]";
/// JS `.` (no line terminators).
const JS_DOT: &str = r"[^\n\r\u{2028}\u{2029}]";

fn is_js_ws(c: char) -> bool {
    matches!(
        c,
        '\t' | '\n' | '\u{B}' | '\u{C}' | '\r' | ' ' | '\u{A0}' | '\u{1680}' | '\u{2000}'
            ..='\u{200A}'
                | '\u{2028}'
                | '\u{2029}'
                | '\u{202F}'
                | '\u{205F}'
                | '\u{3000}'
                | '\u{FEFF}'
    )
}

/// The markdown-stripping substitutions in the TS order, each global.
fn strip_steps() -> &'static [(Regex, &'static str)] {
    static STEPS: OnceLock<Vec<(Regex, &'static str)>> = OnceLock::new();
    STEPS.get_or_init(|| {
        let pattern = |source: String, replacement: &'static str| {
            (
                Regex::new(&source).expect("the strip pattern is a fixed valid regex"),
                replacement,
            )
        };
        vec![
            pattern(format!("#{{1,6}}{JS_WS}+"), ""),
            pattern(format!(r"\*\*({JS_DOT}+?)\*\*"), "$1"),
            pattern(format!(r"\*({JS_DOT}+?)\*"), "$1"),
            pattern("`{1,3}[^`]*`{1,3}".to_string(), ""),
            pattern(r"\[([^\]]+)\]\([^)]+\)".to_string(), "$1"),
            pattern(r"!\[[^\]]*\]\([^)]+\)".to_string(), ""),
            pattern(format!(">{JS_WS}+"), ""),
            pattern(format!("[-*+]{JS_WS}+"), ""),
            pattern(r"\n+".to_string(), " "),
        ]
    })
}

/// Notification preview of `content` as UTF-16 code units: markdown stripped,
/// newlines folded, trimmed, cut at `MESSAGE_PREVIEW_MAX_LENGTH` units (which may
/// split a surrogate pair, exactly like `String.prototype.substring`) plus `...`.
pub fn message_preview(content: &str) -> Vec<u16> {
    let mut text = content.to_string();
    for (pattern, replacement) in strip_steps() {
        text = pattern.replace_all(&text, *replacement).into_owned();
    }
    let plain = text.trim_matches(is_js_ws);
    if plain.is_empty() {
        return EMPTY_PREVIEW.encode_utf16().collect();
    }
    let mut units: Vec<u16> = plain.encode_utf16().collect();
    if units.len() > MESSAGE_PREVIEW_MAX_LENGTH {
        units.truncate(MESSAGE_PREVIEW_MAX_LENGTH);
        units.extend("...".encode_utf16());
    }
    units
}

/// `{content?: string | null}` -> `{units: number[]}` (`messagePreview`).
///
/// # Errors
/// `protocol` when the input is not an object or `content` is neither a string,
/// `null` nor absent.
pub fn preview_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let content = match field(&input, "content") {
        None | Some(Value::Null) => "",
        Some(Value::String(text)) => text.as_str(),
        Some(_) => return Err(PROTOCOL.to_string()),
    };
    if !input.is_object() {
        return Err(PROTOCOL.to_string());
    }
    Ok(json!({ "units": message_preview(content) }).to_string())
}

/// JS `Number.isSafeInteger` on a JSON number.
fn is_safe_integer(value: &Value) -> Option<f64> {
    let n = value.as_f64()?;
    (n.fract() == 0.0 && n.abs() <= 9_007_199_254_740_991.0).then_some(n)
}

/// Why a recovered payload's thinking fields were refused (`THINKING_FIELD_ERRORS`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ThinkingRefusal {
    /// `thinking_content` or `thinking_signature` is present and not a string.
    Content,
    /// `has_thinking` is present and not a boolean.
    Flag,
    /// `thinking_token_count` is present and not a non-negative safe integer.
    Count,
}

impl ThinkingRefusal {
    /// Stable wire code.
    pub fn code(self) -> &'static str {
        match self {
            ThinkingRefusal::Content => "content",
            ThinkingRefusal::Flag => "flag",
            ThinkingRefusal::Count => "count",
        }
    }
}

/// Validates the observed thinking fields (`recoveredThinkingFields`) and returns
/// the keys to copy, in order, or the first refusal. Absent keys are skipped;
/// string values arrive as placeholders because only their type matters.
///
/// # Errors
/// The first refused field in the TS check order (content, signature, flag, count).
pub fn thinking_fields(payload: &Value) -> Result<Vec<&'static str>, ThinkingRefusal> {
    let mut keys = Vec::new();
    for key in ["thinking_content", "thinking_signature"] {
        if let Some(value) = field(payload, key) {
            if !value.is_string() {
                return Err(ThinkingRefusal::Content);
            }
            keys.push(key);
        }
    }
    if let Some(value) = field(payload, "has_thinking") {
        if !value.is_boolean() {
            return Err(ThinkingRefusal::Flag);
        }
        keys.push("has_thinking");
    }
    if let Some(value) = field(payload, "thinking_token_count") {
        if !is_safe_integer(value).is_some_and(|n| n >= 0.0) {
            return Err(ThinkingRefusal::Count);
        }
        keys.push("thinking_token_count");
    }
    Ok(keys)
}

/// `{payload}` -> `{ok: true, keys}` or `{ok: false, code}` (`thinkingFields`).
///
/// # Errors
/// `protocol` when the input has no `payload` object.
pub fn thinking_fields_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let payload = field(&input, "payload")
        .filter(|payload| payload.is_object())
        .ok_or_else(|| PROTOCOL.to_string())?;
    Ok(match thinking_fields(payload) {
        Ok(keys) => json!({ "ok": true, "keys": keys }),
        Err(refusal) => json!({ "ok": false, "code": refusal.code() }),
    }
    .to_string())
}

#[cfg(test)]
#[path = "updates_tests.rs"]
mod tests;
