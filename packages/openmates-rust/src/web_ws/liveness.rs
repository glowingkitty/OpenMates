//! Liveness decisions of the web WebSocket service: pong timeout, online/resume
//! checks and the periodic retry tick.
//!
//! Mirrors `startPing`'s pong-timeout callback, the `online`, `connection.change`
//! and page-resume handlers and `startPeriodicRetry` in `websocketService.ts`.
//! The page owns timers and the socket; these functions only answer what to do.
//! spec: sync.access.first-party-authenticated, sdk.client.thin-platform-boundary
use serde_json::{json, Value};

use super::close::reconnect_plan;
use super::{bool_of, parse_object, uint_of, PONG_TIMEOUT_MS, PROTOCOL};

/// Pong-timeout decision. Input `{sinceActivityMs, hasSocket, authenticated, reconnectAttempts}`.
///
/// Recent incoming data (AI streaming) proves liveness (`skip`); otherwise a
/// live socket is closed (`closeSocket`, whose close event reconnects) and a
/// missing socket reconnects directly (`reconnect`/`exhausted`) or does nothing
/// when logged out (`none`).
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn pong_timeout_json(input: &str) -> Result<String, String> {
    let input = parse_object(input)?;
    let since = uint_of(&input, "sinceActivityMs")?;
    let has_socket = bool_of(&input, "hasSocket")?;
    let authenticated = bool_of(&input, "authenticated")?;
    let attempts = uint_of(&input, "reconnectAttempts")?;
    let plan = if since < PONG_TIMEOUT_MS {
        json!({"kind": "skip"})
    } else if has_socket {
        json!({"kind": "closeSocket"})
    } else {
        match reconnect_plan(authenticated, attempts) {
            plan if plan["kind"] == "loggedOut" => json!({"kind": "none"}),
            plan => plan,
        }
    };
    Ok(plan.to_string())
}

/// Network/page lifecycle decision. Input
/// `{source: "online"|"connectionChange"|"resume", authenticated, connected, connecting}`.
///
/// `connect` means: reset the attempt counter and connect now. `ping` (resume
/// only) means: the socket looks alive, send a liveness ping. `none` otherwise.
///
/// # Errors
/// `protocol` for an unknown `source` or malformed input.
pub fn lifecycle_json(input: &str) -> Result<String, String> {
    let input = parse_object(input)?;
    let source = input
        .get("source")
        .and_then(Value::as_str)
        .ok_or_else(|| PROTOCOL.to_string())?;
    if !matches!(source, "online" | "connectionChange" | "resume") {
        return Err(PROTOCOL.to_string());
    }
    let authenticated = bool_of(&input, "authenticated")?;
    let connected = bool_of(&input, "connected")?;
    let connecting = bool_of(&input, "connecting")?;
    let kind = if !authenticated {
        "none"
    } else if !connected && !connecting {
        "connect"
    } else if source == "resume" && connected {
        "ping"
    } else {
        "none"
    };
    Ok(json!({"kind": kind}).to_string())
}

/// Periodic-retry tick decision. Input `{authenticated, connected, connecting}`:
/// `connect`, `stop` (logged out) or `wait`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn periodic_retry_json(input: &str) -> Result<String, String> {
    let input = parse_object(input)?;
    let authenticated = bool_of(&input, "authenticated")?;
    let connected = bool_of(&input, "connected")?;
    let connecting = bool_of(&input, "connecting")?;
    let kind = if authenticated && !connected && !connecting {
        "connect"
    } else if !authenticated {
        "stop"
    } else {
        "wait"
    };
    Ok(json!({"kind": kind}).to_string())
}
