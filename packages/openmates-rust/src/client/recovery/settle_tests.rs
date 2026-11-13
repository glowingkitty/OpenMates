//! Replay waits for an output another device is still settling, never for an absent one.
use super::output_settling;
use serde_json::json;

// contract-test: supporting surface=cli assertions=projects.agentic.long-turn-stays-online
#[test]
fn preparing_or_pending_output_is_awaited_within_the_bound() {
    assert!(output_settling(&json!("PREPARING"), 0));
    assert!(output_settling(&json!("PENDING"), 29));
    assert!(!output_settling(&json!("PENDING"), 30));
}

// contract-test: supporting surface=cli assertions=projects.agentic.long-turn-stays-online
#[test]
fn absent_or_unknown_output_fails_at_once() {
    assert!(!output_settling(&json!("ABSENT"), 0));
    assert!(!output_settling(&json!(null), 0));
}
