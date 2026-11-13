//! Shared-chat plan/task page validation decisions.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors the bounded-page checks of `sharedChatDetailsService.ts`
//! (`fetchEncryptedPage`, `fetchExactOversizedItem`, `completeWrapperWindow`).
//! The page fetches and decrypts; Rust decides whether a public ciphertext
//! page is well formed, contiguous and advancing. Messages equal the TS
//! `Error` texts. Ordering compares strings by UTF-16 units like JS.

use super::{Decision, array, field, refusal, safe_int, str_field, utf16_cmp};
use serde_json::{Value, json};
use std::cmp::Ordering;

/// Largest accepted `payload_bytes` of one bounded page.
const MAX_PAGE_BYTES: i64 = 131_072;
/// Most items one bounded page may carry.
const MAX_PAGE_ITEMS: usize = 20;
/// Most key-wrapper continuation requests per page (TS `MAX_WRAPPER_PAGES`).
const MAX_WRAPPER_PAGES: i64 = 20;

/// JS truthiness of a JSON value.
pub(super) fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(flag)) => *flag,
        Some(Value::Number(number)) => number.as_f64().is_some_and(|n| n != 0.0),
        Some(Value::String(text)) => !text.is_empty(),
        Some(_) => true,
    }
}

/// JS `===` for JSON values (`1` equals `1.0`); `None` models `undefined`.
pub(super) fn strict_eq(a: Option<&Value>, b: Option<&Value>) -> bool {
    match (a, b) {
        (None, None) => true,
        (Some(Value::Number(x)), Some(Value::Number(y))) => x.as_f64() == y.as_f64(),
        (Some(x), Some(y)) => x == y,
        _ => false,
    }
}

/// JS relational comparison of two values: numbers numerically, strings by UTF-16, otherwise unordered.
fn js_cmp(a: Option<&Value>, b: Option<&Value>) -> Option<Ordering> {
    match (a, b) {
        (Some(Value::Number(x)), Some(Value::Number(y))) => x.as_f64()?.partial_cmp(&y.as_f64()?),
        (Some(Value::String(x)), Some(Value::String(y))) => Some(utf16_cmp(x, y)),
        _ => None,
    }
}

/// `next` is not strictly before `cursor` (timestamp greater, or equal with id >=).
pub(super) fn cursor_not_before(next: &Value, cursor: &Value) -> bool {
    let timestamp = js_cmp(next.get("timestamp"), cursor.get("timestamp"));
    if timestamp == Some(Ordering::Greater) {
        return true;
    }
    strict_eq(next.get("timestamp"), cursor.get("timestamp"))
        && matches!(js_cmp(next.get("id"), cursor.get("id")), Some(Ordering::Greater | Ordering::Equal))
}

fn error_if(failed: bool, message: String) -> Option<Value> {
    failed.then(|| refusal(&message))
}

fn ok() -> Value {
    json!({ "ok": true })
}

/// `cursor` input check at the start of `fetchEncryptedPage`.
fn cursor_check(input: &Value) -> Decision {
    let kind = str_field(input, "kind")?;
    let bad = match input.get("cursor").filter(|c| truthy(Some(c))) {
        Some(cursor) => {
            !safe_int(cursor.get("timestamp").unwrap_or(&Value::Null)).is_some_and(|t| t >= 0)
                || !truthy(cursor.get("id"))
        }
        None => false,
    };
    Ok(error_if(bad, format!("Shared {kind} cursor was invalid")).unwrap_or_else(ok))
}

fn page_shape_invalid(page: &Value) -> bool {
    let items_ok = page.get("items_is_array") == Some(&json!(true))
        && page.get("items").and_then(Value::as_array).is_some_and(|items| items.len() <= MAX_PAGE_ITEMS);
    let bytes_ok = page.get("payload_bytes").and_then(safe_int).is_some_and(|b| (0..=MAX_PAGE_BYTES).contains(&b));
    !(items_ok
        && page.get("key_wrappers_is_array") == Some(&json!(true))
        && matches!(page.get("has_more_before"), Some(Value::Bool(_)))
        && bytes_ok)
}

fn position_invalid(items: &[Value], chat_id: &str) -> bool {
    let mut previous: Option<&Value> = None;
    for item in items {
        let id_ok = matches!(item.get("id"), Some(Value::String(id)) if !id.is_empty());
        let chat_ok = match item.get("primary_chat_id") {
            None | Some(Value::Null) => true,
            Some(Value::String(other)) => other == chat_id,
            Some(_) => false,
        };
        if safe_int(item.get("updated_at").unwrap_or(&Value::Null)).is_none() || !id_ok || !chat_ok {
            return true;
        }
        if let Some(prev) = previous {
            let order = js_cmp(item.get("updated_at"), prev.get("updated_at"));
            let same = order == Some(Ordering::Equal);
            let id_before_or_same = matches!(js_cmp(item.get("id"), prev.get("id")), Some(Ordering::Less | Ordering::Equal));
            if order == Some(Ordering::Less) || (same && id_before_or_same) {
                return true;
            }
        }
        previous = Some(item);
    }
    false
}

/// Validates a fetched auxiliary page (`fetchEncryptedPage` after the response was read).
fn page_check(input: &Value) -> Decision {
    let kind = str_field(input, "kind")?;
    let chat_id = str_field(input, "chat_id")?;
    let page = field(input, "page")?;
    if page_shape_invalid(page) {
        return Ok(refusal(&format!("Shared {kind} page was invalid")));
    }
    let items = array(field(page, "items")?, "items")?;
    if position_invalid(items, chat_id) {
        return Ok(refusal(&format!("Shared {kind} page identities or order were invalid")));
    }
    let start = page.get("start_cursor").filter(|c| truthy(Some(c)));
    if let Some(oldest) = items.first() {
        let matches_oldest = start.is_some_and(|s| {
            strict_eq(s.get("timestamp"), oldest.get("updated_at")) && strict_eq(s.get("id"), oldest.get("id"))
        });
        if !matches_oldest {
            return Ok(refusal(&format!("Shared {kind} page cursor was invalid")));
        }
    }
    if page.get("has_more_before") == Some(&json!(true)) && start.is_none() && !truthy(page.get("oversized_id")) {
        return Ok(refusal(&format!("Shared {kind} page cannot advance")));
    }
    if let (Some(cursor), Some(start)) = (input.get("cursor").filter(|c| truthy(Some(c))), start) {
        if cursor_not_before(start, cursor) {
            return Ok(refusal(&format!("Shared {kind} cursor did not advance")));
        }
    }
    Ok(ok())
}

/// Validates the selected-row response of an oversized item (`fetchExactOversizedItem`).
fn exact_check(input: &Value) -> Decision {
    let kind = str_field(input, "kind")?;
    let chat_id = str_field(input, "chat_id")?;
    let exact = field(input, "exact")?;
    if exact.get("has_item") != Some(&json!(true)) || exact.get("key_wrappers_is_array") != Some(&json!(true)) {
        return Ok(refusal(&format!("Shared {kind} item was invalid")));
    }
    let chat_ok = match exact.get("primary_chat_id") {
        None | Some(Value::Null) => true,
        Some(Value::String(other)) => other == chat_id,
        Some(_) => false,
    };
    let changed = !strict_eq(exact.get("item_id"), input.get("id"))
        || safe_int(exact.get("updated_at").unwrap_or(&Value::Null)).is_none()
        || !chat_ok;
    Ok(error_if(changed, format!("Shared {kind} item identity changed")).unwrap_or_else(ok))
}

/// Cursor must move strictly backwards after an oversized selection.
fn oversized_advance(input: &Value) -> Decision {
    let kind = str_field(input, "kind")?;
    let advanced_not = match (input.get("cursor").filter(|c| truthy(Some(c))), input.get("start_cursor").filter(|c| truthy(Some(c)))) {
        (Some(cursor), Some(start)) => cursor_not_before(start, cursor),
        _ => false,
    };
    Ok(error_if(advanced_not, format!("Shared {kind} oversized cursor did not advance")).unwrap_or_else(ok))
}

/// Query parameter for the next key-wrapper continuation request.
fn wrapper_step(input: &Value) -> Decision {
    let kind = str_field(input, "kind")?;
    let window = field(input, "window")?;
    if truthy(window.get("oversized_key_id")) {
        return Ok(json!({ "param": "key_id", "value": window["oversized_key_id"] }));
    }
    if truthy(window.get("end_cursor")) {
        return Ok(json!({ "param": "after_key_id", "value": window["end_cursor"] }));
    }
    Ok(refusal(&format!("Shared {kind} key cursor did not advance")))
}

/// Next wrapper window after a continuation response, or a refusal.
fn wrapper_advance(input: &Value) -> Decision {
    let kind = str_field(input, "kind")?;
    let window = field(input, "window")?;
    let continuation = field(input, "continuation")?;
    let next = continuation.get("window").filter(|w| truthy(Some(w)));
    let Some(next) = next.filter(|_| continuation.get("key_wrappers_is_array") == Some(&json!(true))) else {
        return Ok(refusal(&format!("Shared {kind} key window was invalid")));
    };
    if truthy(window.get("oversized_key_id")) {
        let mut merged = next.clone();
        let map = merged.as_object_mut().ok_or("bad_field:window")?;
        map.insert("has_more_after".into(), json!(true));
        map.insert("end_cursor".into(), window["oversized_key_id"].clone());
        map.insert("oversized_key_id".into(), Value::Null);
        return Ok(json!({ "window": merged }));
    }
    let stuck = truthy(next.get("has_more_after"))
        && strict_eq(next.get("end_cursor"), window.get("end_cursor"))
        && !truthy(next.get("oversized_key_id"));
    Ok(error_if(stuck, format!("Shared {kind} key cursor did not advance")).unwrap_or_else(|| json!({ "window": next })))
}

/// Whether the continuation loop runs another round (`window?.has_more_after && count < MAX`).
fn wrapper_continue(input: &Value) -> Decision {
    let count = field(input, "count")?.as_i64().ok_or("bad_field:count")?;
    Ok(json!(input.get("window").is_some_and(|w| truthy(w.get("has_more_after"))) && count < MAX_WRAPPER_PAGES))
}

/// Refusal when the loop ended with wrappers still outstanding.
fn wrapper_done(input: &Value) -> Decision {
    let kind = str_field(input, "kind")?;
    let outstanding = input.get("window").is_some_and(|w| truthy(w.get("has_more_after")));
    Ok(error_if(outstanding, format!("Shared {kind} key window exceeded the bounded retry limit")).unwrap_or_else(ok))
}

/// Indexes of continuation wrappers not yet seen (ids are unique-added in order).
fn wrapper_dedup(input: &Value) -> Decision {
    let mut seen: Vec<&str> = array(field(input, "seen")?, "seen")?.iter().filter_map(Value::as_str).collect();
    let mut add = Vec::new();
    for (index, wrapper) in array(field(input, "wrappers")?, "wrappers")?.iter().enumerate() {
        match wrapper.get("id").and_then(Value::as_str).filter(|id| !id.is_empty()) {
            Some(id) if !seen.contains(&id) => {
                seen.push(id);
                add.push(json!(index));
            }
            _ => {}
        }
    }
    Ok(Value::Array(add))
}

/// Dispatches the `details*` ops.
pub(super) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "detailsCursorCheck" => cursor_check(input),
        "detailsPageCheck" => page_check(input),
        "detailsExactCheck" => exact_check(input),
        "detailsOversizedAdvance" => oversized_advance(input),
        "detailsWrapperStep" => wrapper_step(input),
        "detailsWrapperAdvance" => wrapper_advance(input),
        "detailsWrapperContinue" => wrapper_continue(input),
        "detailsWrapperDone" => wrapper_done(input),
        "detailsWrapperDedup" => wrapper_dedup(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}
