//! Close-event and reconnect decisions of the web WebSocket service.
//!
//! Mirrors the `currentWS.onclose` policy of `websocketService.ts`: close code
//! 1008 is a terminal auth/device violation (with 2FA or passkey re-auth hints),
//! repeated or auth-worded 1006 closures require a REST session check before
//! retrying, and everything else reconnects with capped exponential backoff.
//! Invariant: the consecutive-1006 counter is owned by the page; each decision
//! returns its new value so the page never recomputes it.
//! spec: sync.access.first-party-authenticated, sdk.client.thin-platform-boundary
use serde_json::{json, Value};

use super::{
    bool_of, parse_object, uint_of, AUTH_FAILURE_THRESHOLD, MAX_RECONNECT_ATTEMPTS, PROTOCOL,
    RECONNECT_BASE_MS, RECONNECT_MAX_MS,
};

/// Capped exponential reconnect decision (`attempts` = attempts already made).
///
/// Returns `reconnect` with the new attempt number and delay, `exhausted` when
/// the budget is spent (the page starts the periodic retry) or `loggedOut`.
pub fn reconnect_plan(authenticated: bool, attempts: u64) -> Value {
    if !authenticated {
        return json!({"kind": "loggedOut"});
    }
    if attempts >= MAX_RECONNECT_ATTEMPTS {
        return json!({"kind": "exhausted"});
    }
    let attempt = attempts + 1;
    let delay = RECONNECT_BASE_MS
        .saturating_mul(1u64 << (attempt - 1).min(32))
        .min(RECONNECT_MAX_MS);
    json!({"kind": "reconnect", "attempt": attempt, "delayMs": delay})
}

/// Adds the new consecutive-1006 counter to a decision object.
fn with_consecutive(mut plan: Value, consecutive: u64) -> Value {
    plan["consecutive"] = json!(consecutive);
    plan
}

/// Whether a 1006 close reason names an auth failure (`isAuthRelated`).
fn auth_related(reason: &str) -> bool {
    let reason = reason.to_lowercase();
    [
        "forbidden",
        "403",
        "invalid",
        "expired",
        "token",
        "unauthorized",
    ]
    .iter()
    .any(|word| reason.contains(word))
}

/// Decision for one WebSocket close event.
///
/// Input `{code, reason, wasClean, consecutive, authenticated, reconnectAttempts}`.
/// Output kinds: `policyViolation {reAuth: "2fa"|"passkey"|null}`,
/// `sessionCheck {authRelated}` (page refreshes the REST session, then asks
/// [`session_result_json`]), `reconnect`, `exhausted`, `loggedOut`; every
/// output carries the new `consecutive` counter.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn close_plan_json(input: &str) -> Result<String, String> {
    let input = parse_object(input)?;
    let code = uint_of(&input, "code")?;
    let reason = match input.get("reason") {
        None | Some(Value::Null) => "",
        Some(Value::String(s)) => s.as_str(),
        Some(_) => return Err(PROTOCOL.to_string()),
    };
    let was_clean = bool_of(&input, "wasClean")?;
    let consecutive = uint_of(&input, "consecutive")?;
    let authenticated = bool_of(&input, "authenticated")?;
    let attempts = uint_of(&input, "reconnectAttempts")?;

    if code == 1008 {
        let re_auth = if reason.contains("2FA required") {
            json!("2fa")
        } else if reason.contains("Passkey required") {
            json!("passkey")
        } else {
            Value::Null
        };
        return Ok(
            with_consecutive(json!({"kind": "policyViolation", "reAuth": re_auth}), 0).to_string(),
        );
    }
    if code == 1006 && !was_clean {
        let consecutive = consecutive + 1;
        let related = auth_related(reason);
        if consecutive >= AUTH_FAILURE_THRESHOLD || related {
            return Ok(with_consecutive(
                json!({"kind": "sessionCheck", "authRelated": related}),
                consecutive,
            )
            .to_string());
        }
        return Ok(
            with_consecutive(reconnect_plan(authenticated, attempts), consecutive).to_string(),
        );
    }
    // A clean close or any other code resets the abnormal-closure counter.
    Ok(with_consecutive(reconnect_plan(authenticated, attempts), 0).to_string())
}

/// Decision after the REST session check requested by a `sessionCheck` plan.
///
/// Input `{sessionValid, authenticated}`. An invalid session is a terminal
/// `authError`; a valid one resets both counters and reconnects from attempt 0.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn session_result_json(input: &str) -> Result<String, String> {
    let input = parse_object(input)?;
    let valid = bool_of(&input, "sessionValid")?;
    let authenticated = bool_of(&input, "authenticated")?;
    let plan = if valid {
        reconnect_plan(authenticated, 0)
    } else {
        json!({"kind": "authError"})
    };
    Ok(with_consecutive(plan, 0).to_string())
}

/// JSON entry point of [`reconnect_plan`]: `{authenticated, reconnectAttempts}`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn reconnect_plan_json(input: &str) -> Result<String, String> {
    let input = parse_object(input)?;
    Ok(reconnect_plan(
        bool_of(&input, "authenticated")?,
        uint_of(&input, "reconnectAttempts")?,
    )
    .to_string())
}
