//! Web chat-sync decision policy (the shared Rust core Worker `sync` unit).
//!
//! The browser keeps WebSocket IO, IndexedDB IO, chat-key unwrapping, stores
//! and the DOM; this module makes the sync decisions with exactly the semantics
//! of the web TypeScript it replaces (`chatSyncMerge.ts`, `chatSyncPhasedRetry.ts`,
//! `chatSyncUpdatesLogic.ts`, the key-admission helpers of
//! `chatSyncServiceHandlersPhasedSync.ts` and `chatSyncMessageKeyGuard.ts`), proven
//! by `ts_vectors.json` and `updates_ts_vectors.json`. Every entry point
//! takes and returns JSON text so the wasm boundary carries one string per call.
//! Spec: `feature.chats` (chats.persistence.client-encrypted), `surface.sdk`
//! (sdk.client.thin-platform-boundary).
use serde_json::Value;

pub mod inbound;
pub mod merge;
pub mod message_keys;
pub mod phased;
pub mod updates;

/// Stable error code of every malformed-input refusal (the unit's only code).
pub const PROTOCOL: &str = "protocol";

fn protocol<E>(_: E) -> String {
    PROTOCOL.to_string()
}

/// Parses one JSON argument of a wasm entry point.
pub(crate) fn parse(text: &str) -> Result<Value, String> {
    serde_json::from_str(text).map_err(protocol)
}

/// JS truthiness of a JSON value (`undefined` is an absent field).
pub(crate) fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|n| n != 0.0 && !n.is_nan()),
        Some(Value::String(s)) => !s.is_empty(),
        Some(_) => true,
    }
}

/// `value ?? …`: the value when it is neither `null` nor `undefined`.
fn nullish(value: Option<&Value>) -> Option<&Value> {
    value.filter(|v| !v.is_null())
}

/// `value || …`: the value when it is truthy.
fn or(value: Option<&Value>) -> Option<&Value> {
    value.filter(|v| truthy(Some(v)))
}

/// JS `ToNumber` for the values chat records carry (numbers, booleans, null);
/// `undefined`, strings and containers are `NaN`, so every comparison is false.
pub(crate) fn num(value: Option<&Value>) -> f64 {
    match value {
        Some(Value::Number(n)) => n.as_f64().unwrap_or(f64::NAN),
        Some(Value::Bool(b)) => f64::from(u8::from(*b)),
        Some(Value::Null) => 0.0,
        _ => f64::NAN,
    }
}

/// `(value ?? fallback)` as a number.
fn num_or(value: Option<&Value>, fallback: f64) -> f64 {
    nullish(value).map_or(fallback, |v| num(Some(v)))
}

/// A JS number result (`Math.max`, arithmetic) as JSON; integral values stay integers.
fn number(value: f64) -> Value {
    if value.fract() == 0.0 && value.abs() < 9_007_199_254_740_992.0 {
        Value::from(value as i64)
    } else {
        serde_json::Number::from_f64(value).map_or(Value::Null, Value::Number)
    }
}

/// Property read on a JSON object; anything else has no named fields.
pub(crate) fn field<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    value.as_object().and_then(|object| object.get(key))
}

/// Strict equality (`===`) of two optional JSON primitives.
pub(crate) fn strict_eq(a: Option<&Value>, b: Option<&Value>) -> bool {
    match (a, b) {
        (None, None) => true,
        (Some(Value::Number(x)), Some(Value::Number(y))) => x.as_f64() == y.as_f64(),
        (Some(x @ (Value::Null | Value::Bool(_) | Value::String(_))), Some(y)) => x == y,
        _ => false,
    }
}

#[cfg(test)]
mod tests;
