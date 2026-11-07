//! spec: sdk.client.thin-platform-boundary
//! Embed status state machine (port of `embedStateMachine.ts`; mirrors
//! `backend/shared/python_schemas/embed_status.py`).

/// Every valid embed status, in the TS enum order.
pub const STATUSES: [&str; 6] = [
    "processing",
    "rendering",
    "finished",
    "error",
    "cancelled",
    "needs_rerender",
];

/// Whether `value` is a known status string.
pub fn is_valid_status(value: &str) -> bool {
    STATUSES.contains(&value)
}

/// Statuses a stored status may move to (the TS `ALLOWED_TRANSITIONS`).
fn allowed(current: &str) -> &'static [&'static str] {
    match current {
        "processing" => &["processing", "rendering", "finished", "error", "cancelled"],
        "rendering" => &["rendering", "finished", "error", "cancelled"],
        "finished" => &["error", "needs_rerender"],
        "needs_rerender" => &["needs_rerender", "rendering", "error", "cancelled"],
        _ => &[],
    }
}

/// True when `current` -> `target` is a valid transition. Unknown statuses are refused.
pub fn validate_transition(current: &str, target: &str) -> bool {
    is_valid_status(current) && is_valid_status(target) && allowed(current).contains(&target)
}

/// Terminal statuses: finished, error, cancelled.
pub fn is_terminal(status: &str) -> bool {
    matches!(status, "finished" | "error" | "cancelled")
}

/// Unknown or absent statuses (and the backend alias `completed`) normalise to `finished`.
pub fn normalize_status(value: Option<&str>) -> &'static str {
    match value {
        Some(v) => STATUSES
            .iter()
            .copied()
            .find(|s| *s == v)
            .unwrap_or("finished"),
        None => "finished",
    }
}
