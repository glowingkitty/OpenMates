//! Web WebSocket connection-lifecycle policy (the shared Rust core Worker `ws` unit).
//!
//! The browser keeps the `WebSocket` object, timers, DOM events, stores and the
//! REST session refresh; this module makes the connection decisions with exactly
//! the semantics of the web TypeScript it replaces (`websocketService.ts`: the
//! `onclose` policy incl. 1008 and repeated-1006 auth detection, reconnect
//! backoff, pong-timeout, online/resume liveness and periodic retry), proven by
//! `ts_vectors.json`. Every entry point takes and returns JSON text.
//! Spec: `feature.chats` (chats.sync.reconnect), `surface.sdk`
//! (sdk.client.thin-platform-boundary).
//! spec: sync.access.first-party-authenticated, sdk.client.thin-platform-boundary
use serde_json::Value;

pub mod close;
pub mod liveness;

/// Stable error code of every malformed-input refusal (the unit's only code).
pub const PROTOCOL: &str = "protocol";

/// First reconnect delay in milliseconds; doubles per attempt.
pub const RECONNECT_BASE_MS: u64 = 1000;
/// Reconnect delay ceiling in milliseconds.
pub const RECONNECT_MAX_MS: u64 = 5000;
/// Immediate reconnect attempts before the periodic retry takes over.
pub const MAX_RECONNECT_ATTEMPTS: u64 = 10;
/// Consecutive abnormal (1006) closures that are treated as an auth signal.
pub const AUTH_FAILURE_THRESHOLD: u64 = 4;
/// A pong timeout is ignored when incoming data arrived more recently than this.
pub const PONG_TIMEOUT_MS: u64 = 10_000;

fn protocol<E>(_: E) -> String {
    PROTOCOL.to_string()
}

/// Parses one JSON object argument of a wasm entry point.
pub(crate) fn parse_object(text: &str) -> Result<Value, String> {
    let value: Value = serde_json::from_str(text).map_err(protocol)?;
    if value.is_object() {
        Ok(value)
    } else {
        Err(PROTOCOL.to_string())
    }
}

/// Required boolean member.
pub(crate) fn bool_of(input: &Value, key: &str) -> Result<bool, String> {
    input
        .get(key)
        .and_then(Value::as_bool)
        .ok_or_else(|| PROTOCOL.to_string())
}

/// Required non-negative integer member.
pub(crate) fn uint_of(input: &Value, key: &str) -> Result<u64, String> {
    input
        .get(key)
        .and_then(Value::as_u64)
        .ok_or_else(|| PROTOCOL.to_string())
}

#[cfg(test)]
mod tests;
