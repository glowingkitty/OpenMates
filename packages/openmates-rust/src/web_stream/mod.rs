//! Web AI-stream and reply-recovery decisions (the shared Rust core Worker
//! `sync` unit recovery ops and the `ws` unit stream assembler).
//!
//! Mirrors the decision code of `chatRecoveryVersionApply.ts`,
//! `chatRecoveryVersionRefresh.ts`, `recoveryEmbedSource.ts`,
//! `recoveryAssistantTimestamp.ts` and the recovery/stream helpers of
//! `chatSyncServiceHandlersRecovery.ts` / `chatSyncServiceHandlersAI.ts`,
//! proven by `ts_vectors.json`. The page keeps IO (fetch, IndexedDB, timers,
//! stores, events); every entry point takes and returns JSON text.
//! spec: specifications/architecture/sync#sync.client.shared-rust-policy
use serde_json::Value;

pub mod assembler;
pub mod recovery;
pub mod recovery_text;

/// Stable error code of every malformed-input refusal (the unit's only code).
pub const PROTOCOL: &str = "protocol";

pub(crate) fn protocol<E>(_: E) -> String {
    PROTOCOL.to_string()
}

/// Parses one JSON argument of a wasm entry point.
pub(crate) fn parse(text: &str) -> Result<Value, String> {
    serde_json::from_str(text).map_err(protocol)
}

/// Property read on a JSON object; anything else has no named fields.
pub(crate) fn field<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    value.as_object().and_then(|object| object.get(key))
}

/// `value ?? …`: the value when it is neither `null` nor `undefined`.
pub(crate) fn nullish(value: Option<&Value>) -> Option<&Value> {
    value.filter(|v| !v.is_null())
}

/// JS `ToNumber` for the values the stream records carry; anything else is `NaN`.
pub(crate) fn num(value: Option<&Value>) -> f64 {
    match value {
        Some(Value::Number(n)) => n.as_f64().unwrap_or(f64::NAN),
        Some(Value::Bool(b)) => f64::from(u8::from(*b)),
        Some(Value::Null) => 0.0,
        _ => f64::NAN,
    }
}

/// A JS number result as JSON; `NaN` serializes as `null` like `JSON.stringify`.
pub(crate) fn number(value: f64) -> Value {
    if value.is_nan() || value.is_infinite() {
        Value::Null
    } else if value.fract() == 0.0 && value.abs() < 9_007_199_254_740_992.0 {
        Value::from(value as i64)
    } else {
        serde_json::Number::from_f64(value).map_or(Value::Null, Value::Number)
    }
}

/// `Number.isSafeInteger` of a JSON value.
pub(crate) fn safe_integer(value: Option<&Value>) -> Option<i64> {
    match value {
        Some(Value::Number(n)) => n
            .as_f64()
            .filter(|f| f.fract() == 0.0 && f.abs() <= 9_007_199_254_740_991.0)
            .map(|f| f as i64),
        _ => None,
    }
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

#[cfg(test)]
mod tests;
