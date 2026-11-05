//! Pure counterpart of messageOperations.ts merge predicates. No persistence or authority.
//! Supported policy fields are JSON scalars matching Message; absent and null remain distinct.
use super::*;
use crate::client::plaintext::Plain;
const ENCRYPTED: [&str; 7] = [
    "encrypted_content",
    "encrypted_sender_name",
    "encrypted_category",
    "encrypted_model_name",
    "encrypted_thinking_content",
    "encrypted_thinking_signature",
    "encrypted_pii_mappings",
];
const METADATA: [&str; 6] = [
    "model_name",
    "category",
    "thinking_content",
    "thinking_signature",
    "thinking_token_count",
    "has_thinking",
];
fn safe_integer(value: &Value) -> Option<i64> {
    let number = value.as_f64()?;
    (number.is_finite() && number.fract() == 0.0 && number.abs() <= 9_007_199_254_740_991.0)
        .then_some(number as i64)
}
fn validate(message: &Value) -> Result<()> {
    let object = message.as_object().ok_or(Error::Protocol)?;
    // Supported typed MessageStatus labels only. In particular, inherited JS
    // object-property names are not an unknown-priority extension mechanism.
    if object
        .get("status")
        .and_then(Value::as_str)
        .is_some_and(|status| {
            !matches!(
                status,
                "sending"
                    | "waiting_for_upload"
                    | "waiting_for_internet"
                    | "queued"
                    | "processing"
                    | "streaming"
                    | "waiting_for_user"
                    | "failed"
                    | "delivered"
                    | "synced"
            )
        })
    {
        return Err(Error::Protocol);
    }
    for key in [
        "status",
        "queue_dispatch_status",
        "content",
        "model_name",
        "category",
        "thinking_content",
        "thinking_signature",
    ]
    .iter()
    .copied()
    .chain(ENCRYPTED)
    {
        if object
            .get(key)
            .is_some_and(|v| !v.is_null() && !v.is_string())
        {
            return Err(Error::Protocol);
        }
    }
    for key in ["queue_revision", "thinking_token_count"] {
        if object
            .get(key)
            .is_some_and(|v| !v.is_null() && safe_integer(v).is_none())
        {
            return Err(Error::Protocol);
        }
    }
    if object
        .get("has_thinking")
        .is_some_and(|v| !v.is_null() && !v.is_boolean())
    {
        return Err(Error::Protocol);
    }
    Ok(())
}
fn is(message: &Value, key: &str, value: &str) -> bool {
    message.get(key).and_then(Value::as_str) == Some(value)
}
fn revision(message: &Value) -> Option<i64> {
    message.get("queue_revision").and_then(safe_integer)
}
/// Maintained messageOperations.isContentDuplicate. Pure policy only; actual
/// original-store candidate coverage and any alias repair remain separate.
pub(in crate::client) fn is_content_duplicate(existing:&Value,incoming:&Value)->Result<bool>{
    validate(existing)?;validate(incoming)?;
    for row in [existing,incoming]{for name in ["chat_id","message_id","role"]{if !row[name].is_string(){return Err(Error::Protocol)}}}
    if existing["chat_id"]!=incoming["chat_id"]||existing["role"]!=incoming["role"]{return Ok(false)}
    if existing["role"]=="user"&&existing["message_id"]!=incoming["message_id"]{return Ok(false)}
    let assistant=existing["role"]=="assistant";
    let nonempty=|row:&Value,name:&str|row[name].as_str().is_some_and(|s|!s.is_empty());
    let encrypted=nonempty(existing,"encrypted_content")&&nonempty(incoming,"encrypted_content");
    let same=if encrypted{existing["encrypted_content"]==incoming["encrypted_content"]}else{nonempty(existing,"content")&&nonempty(incoming,"content")&&existing["content"]==incoming["content"]};
    let a=safe_integer(&existing["created_at"]).filter(|v|*v>=0).ok_or(Error::Protocol)?;
    let b=safe_integer(&incoming["created_at"]).filter(|v|*v>=0).ok_or(Error::Protocol)?;
    let sender=assistant||equal(existing.get("encrypted_sender_name"),incoming.get("encrypted_sender_name"));
    let threshold=if assistant{60}else{300};Ok(same&&(a-b).abs()<threshold&&sender)
}
fn priority(message: &Value) -> u8 {
    match message.get("status").and_then(Value::as_str) {
        Some("sending" | "waiting_for_upload" | "waiting_for_internet") => 10,
        Some("processing" | "streaming") => 20,
        Some("waiting_for_user") => 23,
        Some("failed") => 25,
        Some("delivered") => 28,
        Some("synced") => 30,
        Some("queued") => 31,
        _ => 0,
    }
}
// Only compare the supported scalar fields. Option preserves undefined versus null;
// numeric comparison follows JavaScript Number equality (including 1 versus 1.0).
fn equal(a: Option<&Value>, b: Option<&Value>) -> bool {
    match (a, b) {
        (Some(Value::Number(a)), Some(Value::Number(b))) => a.as_f64() == b.as_f64(),
        _ => a == b,
    }
}
pub(in crate::client) fn should_update_message(existing: &Value, incoming: &Value) -> Result<bool> {
    validate(existing)?;
    validate(incoming)?;
    if is(existing, "queue_dispatch_status", "paused")
        && (is(incoming, "queue_dispatch_status", "queued")
            || is(incoming, "queue_dispatch_status", "processing"))
    {
        return Ok(false);
    }
    if is(existing, "queue_dispatch_status", "processing")
        && is(incoming, "queue_dispatch_status", "queued")
    {
        return Ok(false);
    }
    let queued = is(existing, "status", "queued");
    if (queued || is(existing, "queue_dispatch_status", "processing"))
        && is(incoming, "queue_dispatch_status", "paused")
    {
        return Ok(true);
    }
    if queued
        && revision(incoming).is_some_and(|n| n >= revision(existing).unwrap_or(0))
        && is(incoming, "queue_dispatch_status", "processing")
    {
        return Ok(true);
    }
    if queued && revision(incoming).is_some_and(|n| n > revision(existing).unwrap_or(0)) {
        return Ok(true);
    }
    if is(existing, "status", "streaming") && is(incoming, "status", "streaming") {
        return Ok(true);
    }
    if is(existing, "status", "waiting_for_user")
        && (is(incoming, "status", "synced") || is(incoming, "status", "delivered"))
    {
        return Ok(false);
    }
    let (old, new) = (priority(existing), priority(incoming));
    if new > old {
        return Ok(true);
    }
    if new == old && equal(existing.get("status"), incoming.get("status")) {
        if !equal(existing.get("content"), incoming.get("content")) {
            return Ok(false);
        }
        return Ok(METADATA
            .iter()
            .any(|key| !equal(existing.get(*key), incoming.get(*key))));
    }
    Ok(false)
}
pub(in crate::client) fn has_new_encrypted_fields(
    existing: &Value,
    incoming: &Value,
) -> Result<bool> {
    validate(existing)?;
    validate(incoming)?;
    let truthy =
        |value: Option<&Value>| value.and_then(Value::as_str).is_some_and(|s| !s.is_empty());
    Ok(ENCRYPTED
        .iter()
        .any(|key| !truthy(existing.get(*key)) && truthy(incoming.get(*key))))
}
pub(in crate::client) fn has_newer_stored_revision(
    existing: &Value,
    incoming: &Value,
) -> Result<bool> {
    validate(existing)?;
    validate(incoming)?;
    Ok(match (revision(existing), revision(incoming)) {
        (Some(old), Some(new)) => old > new,
        _ => false,
    })
}
/// Bounded strict JSON, closed outer envelope, and boolean-only output. Unsupported
/// typed policy fields are refused rather than claiming arbitrary JavaScript parity.
pub fn browser_message_merge_policy_json(encoded: &str) -> Result<String> {
    super::local_json::validate(encoded)?;
    let value = Plain::new(serde_json::from_str::<Value>(encoded)?);
    let object = value.as_object().ok_or(Error::Protocol)?;
    if object.len() != 2 {
        return Err(Error::Protocol);
    }
    let existing = object.get("existing").ok_or(Error::Protocol)?;
    let incoming = object.get("incoming").ok_or(Error::Protocol)?;
    Ok(serde_json::json!({
        "should_update_message": should_update_message(existing,incoming)?,
        "has_new_encrypted_fields": has_new_encrypted_fields(existing,incoming)?,
        "has_newer_stored_revision": has_newer_stored_revision(existing,incoming)?,
    })
    .to_string())
}
#[cfg(test)]
#[path = "browser_message_policy_tests.rs"]
mod tests;
