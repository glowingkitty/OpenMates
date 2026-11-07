//! JS value helpers shared by the persist policies: `??`, number results and
//! typed reads of JSON inputs. A missing field is JS `undefined`.
//!
//! spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
use serde_json::Value;

use crate::web_sync::{field, PROTOCOL};

pub(crate) fn protocol() -> String {
    PROTOCOL.to_string()
}

/// `value ?? …`: the value when it is neither `null` nor `undefined`.
pub(crate) fn nullish(value: Option<&Value>) -> Option<&Value> {
    value.filter(|v| !v.is_null())
}

/// A JSON number, or `None` for anything else (including `null` and strings).
pub(crate) fn as_f64(value: Option<&Value>) -> Option<f64> {
    value.and_then(Value::as_f64)
}

/// A required JSON number.
///
/// # Errors
/// `protocol` when the value is not a number.
pub(crate) fn req_f64(value: Option<&Value>) -> Result<f64, String> {
    as_f64(value).ok_or_else(protocol)
}

/// A required JSON string.
///
/// # Errors
/// `protocol` when the value is not a string.
pub(crate) fn req_str(value: Option<&Value>) -> Result<&str, String> {
    value.and_then(Value::as_str).ok_or_else(protocol)
}

/// A required JSON object.
///
/// # Errors
/// `protocol` when the value is not an object.
pub(crate) fn req_object(value: Option<&Value>) -> Result<&Value, String> {
    value.filter(|v| v.is_object()).ok_or_else(protocol)
}

/// A required JSON array.
///
/// # Errors
/// `protocol` when the key is not an array.
pub(crate) fn req_list<'a>(input: &'a Value, key: &str) -> Result<&'a Vec<Value>, String> {
    field(input, key)
        .and_then(Value::as_array)
        .ok_or_else(protocol)
}

/// A JS number result as JSON; integral values stay integers.
pub(crate) fn number(value: f64) -> Value {
    if value.fract() == 0.0 && value.abs() < 9_007_199_254_740_992.0 {
        Value::from(value as i64)
    } else {
        serde_json::Number::from_f64(value).map_or(Value::Null, Value::Number)
    }
}

/// `String(value)` of a cursor number as `Array.join` writes it. Integers and
/// plain decimals match JS; exponent forms are refused.
///
/// # Errors
/// `protocol` when the number needs exponent notation.
pub(crate) fn js_number_text(value: f64) -> Result<String, String> {
    if !value.is_finite() || value.abs() >= 1e21 || (value != 0.0 && value.abs() < 1e-6) {
        return Err(protocol());
    }
    Ok(format!("{value}"))
}
