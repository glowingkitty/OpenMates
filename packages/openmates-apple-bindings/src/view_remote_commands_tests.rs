//! The remote command review bindings round-trip records through the core.
use crate::view_remote_commands::*;

const REVIEW: &str = r#"{"protocol_version":1,"execution_id":"e1","chat_id":"c1","project_id":"p1","source_id":"s1","state":"REVIEW_REQUIRED","created_at":1,"review_expires_at":9,"review_token":"01234567890123456789012345678901","approval_requirement":"one_run","command":{"argv":["ls"],"cwd":".","mode":"foreground","source_access":"read_only","deadline_ms":1000,"writable_profiles":[],"credential_profiles":[]},"explanation":{"summary":"s"}}"#;

#[test]
fn review_record_round_trips_into_prepare_payload() {
    let review = parse_remote_command_review(REVIEW.into()).unwrap();
    assert_eq!(review.command.network_profile, None);
    let canonical = remote_command_canonical_request(review.clone());
    let digest = remote_command_request_digest(canonical, vec![1; 32]).unwrap();
    let json = remote_command_prepare_payload_json(review, "enc".into(), digest.clone());
    assert!(json.contains(&digest) && json.contains("\"one_run\""));
}

#[test]
fn event_reducer_and_completion_marshal() {
    let review = parse_remote_command_review(REVIEW.into()).unwrap();
    let s = remote_command_apply_event(
        remote_command_new_output(),
        "output".into(),
        "running".into(),
        0,
        Some("x".into()),
    )
    .unwrap();
    assert!(
        remote_command_apply_event(s.clone(), "output".into(), "running".into(), 0, None).is_err()
    );
    let s = remote_command_apply_event(s, "terminal".into(), "succeeded".into(), 1, None).unwrap();
    assert!(remote_command_completion_payload_json(review, s).contains("\"model_text\":\"x\""));
}
