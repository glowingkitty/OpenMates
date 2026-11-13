//! Typed accessors for the JSON arguments of the message-list, activity and
//! indicator entry points. Every miss is the unit's single `protocol` refusal.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use serde_json::Value;

use super::protocol;

pub(super) fn array<'a>(value: &'a Value, key: &str) -> Result<&'a Vec<Value>, String> {
    value
        .get(key)
        .and_then(Value::as_array)
        .ok_or_else(|| protocol(()))
}

pub(super) fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| protocol(()))
}

/// A string field that may be `null` (absent counts as malformed).
pub(super) fn opt_text<'a>(value: &'a Value, key: &str) -> Result<Option<&'a str>, String> {
    match value.get(key) {
        Some(Value::Null) => Ok(None),
        Some(Value::String(s)) => Ok(Some(s.as_str())),
        _ => Err(protocol(())),
    }
}

pub(super) fn flag(value: &Value, key: &str) -> Result<bool, String> {
    value
        .get(key)
        .and_then(Value::as_bool)
        .ok_or_else(|| protocol(()))
}

pub(super) fn opt_number(value: &Value, key: &str) -> Result<Option<f64>, String> {
    match value.get(key) {
        Some(Value::Null) => Ok(None),
        Some(Value::Number(n)) => n.as_f64().map(Some).ok_or_else(|| protocol(())),
        _ => Err(protocol(())),
    }
}

pub(super) fn number(value: &Value, key: &str) -> Result<f64, String> {
    opt_number(value, key)?.ok_or_else(|| protocol(()))
}

/// An optional-key number: absent or `null` is `None`, a non-number is malformed.
pub(super) fn maybe_number(value: &Value, key: &str) -> Result<Option<f64>, String> {
    match value.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(n)) => n.as_f64().map(Some).ok_or_else(|| protocol(())),
        _ => Err(protocol(())),
    }
}
