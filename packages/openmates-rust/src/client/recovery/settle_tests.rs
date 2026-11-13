//! Replay waits for an output another device is still settling, never for an
//! absent one, and skips outputs another device already acknowledged.
use super::{acknowledged_elsewhere, output_settling};
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

// contract-test: supporting surface=cli assertions=projects.agentic.long-turn-stays-online
#[test]
fn message_or_metadata_acknowledged_by_another_device_is_skipped() {
    let status = json!({"state": "ACKNOWLEDGED", "canonical_verified": false});
    assert!(acknowledged_elsewhere("message", &status));
    assert!(acknowledged_elsewhere("metadata", &status));
}

// contract-test: supporting surface=cli assertions=projects.agentic.long-turn-stays-online
#[test]
fn embed_acknowledgement_needs_a_verified_canonical_row() {
    assert!(!acknowledged_elsewhere(
        "embed",
        &json!({"state": "ACKNOWLEDGED", "canonical_verified": false})
    ));
    assert!(acknowledged_elsewhere(
        "diff",
        &json!({"state": "ACKNOWLEDGED", "canonical_verified": true})
    ));
    assert!(!acknowledged_elsewhere(
        "message",
        &json!({"state": "PENDING"})
    ));
}
