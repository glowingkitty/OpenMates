//! Pair-session policy for the web client: restricted-session view state,
//! auto-logout deadline and v2 pairing request classification. Mirrors
//! `stores/pairSessionStore.ts` and `services/pairV2.ts`; timers, storage and
//! fetch stay in the page adapter.
//! spec: specifications/features/auth#auth.pair-login.lifecycle
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Warning window before auto-logout (`AUTO_LOGOUT_WARNING_SECONDS`).
const WARNING_SECONDS: f64 = 5.0 * 60.0;

/// Persisted pair-session record (`PairSessionData`), camelCase on the wire.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PairSessionData {
    pub is_pair_session: bool,
    pub established_at: f64,
    pub authorizer_device_name: Option<String>,
    pub auto_logout_minutes: Option<f64>,
    pub auto_logout_at: Option<f64>,
}

/// Reactive view derived from the record (`PairSessionState`).
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PairSessionState {
    pub is_pair_session: bool,
    pub authorizer_device_name: Option<String>,
    pub auto_logout_at: Option<f64>,
    pub auto_logout_warning: bool,
    pub remaining_seconds: Option<f64>,
}

/// Input of `activatePairSession`; a server deadline (Unix seconds) wins over
/// the relative minutes.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ActivateInput {
    pub authorizer_device_name: Option<String>,
    pub auto_logout_minutes: Option<f64>,
    pub pair_expires_at: Option<f64>,
}

/// Builds the record stored when pairing completes. `now_ms` is the page clock.
pub(crate) fn activate(input: ActivateInput, now_ms: f64) -> PairSessionData {
    let auto_logout_at = match (input.pair_expires_at, input.auto_logout_minutes) {
        (Some(expires), _) => Some(expires * 1000.0),
        (None, Some(minutes)) => Some(now_ms + minutes * 60.0 * 1000.0),
        (None, None) => None,
    };
    PairSessionData {
        is_pair_session: true,
        established_at: now_ms,
        authorizer_device_name: input.authorizer_device_name,
        auto_logout_minutes: input.auto_logout_minutes,
        auto_logout_at,
    }
}

/// Derived restricted-session state at `now_ms`; absent or non-pair data is
/// the unrestricted state.
pub(crate) fn view(data: Option<&PairSessionData>, now_ms: f64) -> PairSessionState {
    let Some(data) = data.filter(|data| data.is_pair_session) else {
        return PairSessionState { is_pair_session: false, authorizer_device_name: None, auto_logout_at: None, auto_logout_warning: false, remaining_seconds: None };
    };
    let remaining = data.auto_logout_at.map(|at| ((at - now_ms) / 1000.0).floor().max(0.0));
    PairSessionState {
        is_pair_session: true,
        authorizer_device_name: data.authorizer_device_name.clone(),
        auto_logout_at: data.auto_logout_at,
        auto_logout_warning: remaining.is_some_and(|seconds| seconds <= WARNING_SECONDS),
        remaining_seconds: remaining,
    }
}

/// True once the auto-logout deadline has passed (timer tick and page reload).
pub(crate) fn auto_logout_due(data: Option<&PairSessionData>, now_ms: f64) -> bool {
    data.and_then(|data| data.auto_logout_at).is_some_and(|at| now_ms >= at)
}

/// Terminal pairing statuses that end polling.
pub(crate) fn is_terminal(status: &str) -> bool { matches!(status, "failed" | "cancelled" | "acknowledged") }

/// Pair offer expiry; a missing or non-finite deadline counts as expired.
pub(crate) fn expired(expires_at: Option<f64>, now_ms: f64) -> bool {
    match expires_at {
        Some(at) => !at.is_finite() || now_ms >= at * 1000.0,
        None => true,
    }
}

/// Message of a failed pairing request: server `detail`, else `message` (only
/// when strings), else the generic status text. Never includes request data.
pub(crate) fn error_message(status: u16, body: &Value) -> String {
    ["detail", "message"].iter()
        .find_map(|key| body.get(key).and_then(Value::as_str))
        .map_or_else(|| format!("Pairing request failed ({status})"), str::to_owned)
}
