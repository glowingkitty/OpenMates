//! JavaScript value semantics for the web connected-account decisions
//! (`web_connected_accounts`), shared Rust core.
//!
//! The TypeScript services read decrypted, untyped JSON with `?.`, `??`,
//! truthiness, `===` and dynamic indexing. These helpers reproduce exactly the
//! cases those reads can reach so Rust and TypeScript agree on every
//! `web_connected_accounts_ts_vectors.json` case. `None` is JS `undefined`.
use serde_json::Value;

use super::Fail;

/// Own-or-inherited `Object.prototype` members: indexing a plain object with one
/// of these names yields a (truthy, non-object) function in JavaScript.
const OBJECT_PROTOTYPE_MEMBERS: [&str; 12] = [
    "constructor",
    "__defineGetter__",
    "__defineSetter__",
    "hasOwnProperty",
    "__lookupGetter__",
    "__lookupSetter__",
    "isPrototypeOf",
    "propertyIsEnumerable",
    "toString",
    "valueOf",
    "__proto__",
    "toLocaleString",
];

/// Result of a dynamic `container[key]` read.
pub(super) enum Lookup {
    /// `undefined`.
    Undefined,
    /// A JSON value stored under the key.
    Value(Value),
    /// An inherited prototype function: truthy, not an object, no own fields.
    Function,
}

/// JS truthiness of a JSON value (`undefined` is falsy).
pub(super) fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(flag)) => *flag,
        Some(Value::Number(number)) => number.as_f64().map_or(true, |n| n != 0.0),
        Some(Value::String(text)) => !text.is_empty(),
        Some(_) => true,
    }
}

/// `undefined` or `null`.
pub(super) fn nullish(value: Option<&Value>) -> bool {
    matches!(value, None | Some(Value::Null))
}

/// `a ?? b` (`b` evaluated only when `a` is nullish).
pub(super) fn coalesce(a: Option<Value>, b: impl FnOnce() -> Option<Value>) -> Option<Value> {
    if nullish(a.as_ref()) {
        b()
    } else {
        a
    }
}

/// `value.key` for a fixed, non-index, non-`length` key: a `TypeError` on
/// `undefined`/`null`, `undefined` on primitives and arrays.
pub(super) fn prop(value: Option<&Value>, key: &str) -> Result<Option<Value>, Fail> {
    match value {
        None | Some(Value::Null) => Err(Fail::Malformed),
        Some(Value::Object(map)) => Ok(map.get(key).cloned()),
        Some(_) => Ok(None),
    }
}

/// `value?.key` for a fixed, non-index, non-`length` key.
pub(super) fn prop_opt(value: Option<&Value>, key: &str) -> Option<Value> {
    match value {
        Some(Value::Object(map)) => map.get(key).cloned(),
        _ => None,
    }
}

/// `container[key]` for a dynamic string key on a non-nullish container.
///
/// Deviation (documented, unreachable for real envelopes): inherited
/// `Array.prototype` / `String.prototype` members are reported as `undefined`.
pub(super) fn index(container: &Value, key: &str) -> Lookup {
    match container {
        Value::Object(map) => match map.get(key) {
            Some(value) => Lookup::Value(value.clone()),
            None if OBJECT_PROTOTYPE_MEMBERS.contains(&key) => Lookup::Function,
            None => Lookup::Undefined,
        },
        Value::Array(items) => match array_index(key) {
            Some(position) => items.get(position).cloned().map_or(Lookup::Undefined, Lookup::Value),
            None if key == "length" => Lookup::Value(Value::from(items.len())),
            None => Lookup::Undefined,
        },
        Value::String(text) => {
            let units: Vec<u16> = text.encode_utf16().collect();
            match array_index(key) {
                // A single UTF-16 unit; a lone surrogate half still reads as a
                // truthy one-unit string, which is all callers observe.
                Some(position) if position < units.len() => Lookup::Value(Value::String(
                    String::from_utf16(&units[position..=position]).unwrap_or_else(|_| "\u{FFFD}".to_string()),
                )),
                None if key == "length" => Lookup::Value(Value::from(units.len())),
                _ => Lookup::Undefined,
            }
        }
        _ => Lookup::Undefined,
    }
}

/// Canonical array index ("0", "17"; not "01" or "-1").
fn array_index(key: &str) -> Option<usize> {
    if key.is_empty() || (key.len() > 1 && key.starts_with('0')) || !key.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    key.parse::<usize>().ok()
}

/// JS `String(value)` for JSON values (property-key conversion).
pub(super) fn to_js_string(value: &Value) -> String {
    match value {
        Value::Null => "null".to_string(),
        Value::Bool(flag) => flag.to_string(),
        Value::Number(number) => number.to_string(),
        Value::String(text) => text.clone(),
        Value::Array(items) => items
            .iter()
            .map(|item| if item.is_null() { String::new() } else { to_js_string(item) })
            .collect::<Vec<_>>()
            .join(","),
        Value::Object(_) => "[object Object]".to_string(),
    }
}

/// `a === b` for values parsed from separate JSON texts: objects and arrays are
/// distinct identities and never equal.
pub(super) fn strict_eq(a: Option<&Value>, b: Option<&Value>) -> bool {
    match (a, b) {
        (None, None) | (Some(Value::Null), Some(Value::Null)) => true,
        (Some(Value::Bool(x)), Some(Value::Bool(y))) => x == y,
        (Some(Value::Number(x)), Some(Value::Number(y))) => x.as_f64() == y.as_f64(),
        (Some(Value::String(x)), Some(Value::String(y))) => x == y,
        _ => false,
    }
}

/// `a === "literal"`.
pub(super) fn is_str(value: Option<&Value>, literal: &str) -> bool {
    matches!(value, Some(Value::String(text)) if text == literal)
}

/// `Array.prototype.sort()` default order: UTF-16 code unit comparison.
pub(super) fn utf16_cmp(a: &str, b: &str) -> std::cmp::Ordering {
    a.encode_utf16().cmp(b.encode_utf16())
}
