//! Share / guest / incognito client decisions for the shared Rust core Worker
//! `crypto` unit (share-guest-crypto lane, slice 2).
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! spec: specifications/features/auth#auth.keys.client-wrapped
//!
//! Mirrors the pure decisions of `sharedChatKeyStorage.ts`, `shareMetadataQueue.ts`,
//! `sharedChatDetailsService.ts`, `incognitoChatService.ts`, `anonymousChatStorage.ts`
//! and the short-URL parsers of `shortUrlEncryption.ts`. The page keeps IndexedDB,
//! sessionStorage and `fetch` I/O and only asks "what next?"; every op is JSON in,
//! JSON out and never receives key bytes. Refusals that the TS code raised as
//! `Error` come back as `{"error": "<same message>"}` so the adapter rethrows the
//! identical text. Parity with the TS originals is proven by
//! `web_share_state_ts_vectors.json` (`shareStateVectors.test.ts`).

mod anonymous;
mod details;
mod details_subchat;
mod incognito;
mod key_entry;
mod queue;
mod short_url;

use serde_json::{Map, Value, json};
use std::cmp::Ordering;

/// Result of one decision: the JSON document to return, or a malformed-input error.
pub(crate) type Decision = Result<Value, String>;

/// Largest integer JS `Number.isSafeInteger` accepts.
const MAX_SAFE: f64 = 9_007_199_254_740_991.0;

/// Runs one named share-state decision on a JSON document.
///
/// # Errors
/// Returns `unknown_op:<name>` for an unregistered op and the parse or field
/// error text for a malformed input document (never a silent default).
pub fn run_json(op: &str, input: &str) -> Result<String, String> {
    let input: Value = serde_json::from_str(input).map_err(|e| e.to_string())?;
    let output = match op {
        o if o.starts_with("shortUrl") => short_url::run(o, &input),
        o if o.starts_with("sharedKey") => key_entry::run(o, &input),
        o if o.starts_with("queue") => queue::run(o, &input),
        o if o.starts_with("subChat") => details_subchat::run(o, &input),
        o if o.starts_with("details") => details::run(o, &input),
        o if o.starts_with("incognito") => incognito::run(o, &input),
        o if o.starts_with("anonymous") => anonymous::run(o, &input),
        _ => Err(format!("unknown_op:{op}")),
    }?;
    serde_json::to_string(&output).map_err(|e| e.to_string())
}

/// Refusal document the TS adapter rethrows as `new Error(message)`.
pub(crate) fn refusal(message: &str) -> Value {
    json!({ "error": message })
}

/// Required input field.
pub(crate) fn field<'a>(input: &'a Value, name: &str) -> Result<&'a Value, String> {
    input.get(name).ok_or_else(|| format!("missing_field:{name}"))
}

/// Required string input field.
pub(crate) fn str_field<'a>(input: &'a Value, name: &str) -> Result<&'a str, String> {
    field(input, name)?.as_str().ok_or_else(|| format!("bad_field:{name}"))
}

/// Required JSON object.
pub(crate) fn object<'a>(value: &'a Value, name: &str) -> Result<&'a Map<String, Value>, String> {
    value.as_object().ok_or_else(|| format!("bad_field:{name}"))
}

/// Required JSON array.
pub(crate) fn array<'a>(value: &'a Value, name: &str) -> Result<&'a Vec<Value>, String> {
    value.as_array().ok_or_else(|| format!("bad_field:{name}"))
}

/// JS `Number.isSafeInteger` applied to a JSON value (`1.0` parses to the integer 1 in JS).
pub(crate) fn safe_int(value: &Value) -> Option<i64> {
    let number = value.as_f64()?;
    (number.fract() == 0.0 && number.abs() <= MAX_SAFE).then_some(number as i64)
}

/// Whole JSON number when the value is integral, else the float (JS has one number type).
pub(crate) fn js_number(value: f64) -> Value {
    if value.fract() == 0.0 && value.abs() <= MAX_SAFE {
        json!(value as i64)
    } else {
        json!(value)
    }
}

/// JS string `<` order: UTF-16 code units, which differs from Rust's byte order only for astral characters.
pub(crate) fn utf16_cmp(a: &str, b: &str) -> Ordering {
    a.encode_utf16().cmp(b.encode_utf16())
}

/// JS `String.prototype.length`.
pub(crate) fn utf16_len(text: &str) -> usize {
    text.encode_utf16().count()
}
