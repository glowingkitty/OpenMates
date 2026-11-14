//! Covers review validation, canonical request bytes, digest, output hygiene
//! and the event reducer of `remote_command_review`.
use super::*;

fn payload(mutate: impl FnOnce(&mut Value)) -> String {
    let mut v = json!({"protocol_version": 1, "execution_id": "exec-1", "chat_id": "chat-1",
        "project_id": "proj-1", "source_id": "src-1", "state": "REVIEW_REQUIRED",
        "created_at": 100, "review_expires_at": 200,
        "review_token": "t".repeat(32), "approval_requirement": "one_run",
        "command": {"argv": ["npm", "test"], "cwd": "app", "mode": "foreground",
            "source_access": "read_only", "deadline_ms": 5000, "writable_profiles": [],
            "network_profile": null, "credential_profiles": []},
        "explanation": {"summary": "Runs tests", "effects": [], "risks": [], "uncertainty": []}});
    mutate(&mut v);
    v.to_string()
}

#[test]
fn accepts_a_valid_review_and_rejects_bad_bounds() {
    assert!(parse_review(&payload(|_| {})).is_ok());
    assert!(parse_review(&payload(|v| v["command"]["cwd"] = json!("/abs"))).is_err());
    assert!(parse_review(&payload(|v| v["command"]["cwd"] = json!("a/../b"))).is_err());
    assert!(parse_review(&payload(|v| v["review_token"] = json!("short"))).is_err());
    assert!(parse_review(&payload(|v| v["state"] = json!("DONE"))).is_err());
    assert!(parse_review(&payload(|v| v["command"]["deadline_ms"] = json!(50))).is_err());
    assert!(parse_review(&payload(|v| v["chat_id"] = json!("bad id"))).is_err());
}

#[test]
fn refuses_other_chat_expired_and_full_window() {
    let r = parse_review(&payload(|_| {})).unwrap();
    assert!(r.check_acceptable("chat-1", 150, 0).is_ok());
    assert_eq!(
        r.check_acceptable("chat-2", 150, 0),
        Err(ReviewError::InvalidContext)
    );
    assert!(r.check_acceptable("chat-1", 200, 0).is_err());
    assert!(r.check_acceptable("chat-1", 150, MAX_OPEN_REVIEWS).is_err());
}

#[test]
fn canonical_request_has_fixed_key_order() {
    let r = parse_review(&payload(|_| {})).unwrap();
    assert_eq!(
        r.canonical_portable_request(),
        "{\"protocol_version\":1,\"execution_id\":\"exec-1\",\"chat_id\":\"chat-1\",\"project_id\":\"proj-1\",\"source_id\":\"src-1\",\"policy\":{\"argv\":[\"npm\",\"test\"],\"cwd\":\"app\",\"mode\":\"foreground\",\"source_access\":\"read_only\",\"deadline_ms\":5000,\"writable_profiles\":[],\"network_profile\":null,\"credential_profiles\":[]},\"approval\":{\"kind\":\"one_run\"}}"
    );
}

#[test]
fn digest_is_base64url_and_needs_a_32_byte_key() {
    let d = request_digest("{}", &[7u8; 32]).unwrap();
    assert_eq!(d.len(), 43);
    assert!(!d.contains(['+', '/', '=']));
    assert!(request_digest("{}", &[7u8; 16]).is_err());
}

#[test]
fn cleans_escapes_but_keeps_newlines() {
    let raw = "\u{1b}[31mred\u{1b}[0m\u{1b}]0;title\u{7}\nline\t\u{202e}x\u{0}\u{7f}";
    assert_eq!(clean_terminal_text(raw), "red\nline\tx");
}

#[test]
fn bounds_long_output_around_a_marker() {
    let long = "a".repeat(30_000);
    let b = bounded_output(&long);
    assert!(b.contains("[... terminal output omitted ...]"));
    assert!(
        b.chars().count() <= MAX_COMPLETION_CHARS && b.chars().count() >= MAX_COMPLETION_CHARS - 1
    );
    assert_eq!(bounded_output("short"), "short");
}

#[test]
fn reducer_orders_events_and_builds_completion() {
    let r = parse_review(&payload(|_| {})).unwrap();
    let mut s = OutputState::new();
    s.apply_event("status", "running", 0, None).unwrap();
    s.apply_event("output", "running", 1, Some("hi\u{1b}[1m"))
        .unwrap();
    assert!(s.apply_event("output", "running", 1, Some("dup")).is_err());
    assert!(s.apply_event("terminal", "running", 2, None).is_err());
    s.apply_event("terminal", "succeeded", 2, None).unwrap();
    let c = s.completion(&r);
    assert_eq!(c["result_status"], "succeeded");
    assert_eq!(c["model_text"], "hi");
    assert_eq!(c["upstream_truncated"], false);
}

#[test]
fn gap_marks_completion_incomplete() {
    let r = parse_review(&payload(|_| {})).unwrap();
    let mut s = OutputState::new();
    s.apply_event("output", "running", 3, Some("x")).unwrap();
    s.apply_event("terminal", "failed", 4, None).unwrap();
    let c = s.completion(&r);
    assert_eq!(c["upstream_truncated"], true);
    assert!(
        c["model_text"]
            .as_str()
            .unwrap()
            .starts_with("[Incomplete terminal output")
    );
    assert_eq!(c["omitted_chars"], 0);
}

#[test]
fn maps_server_responses_to_statuses() {
    assert_eq!(
        status_for_response("remote_command_error", None, None).as_deref(),
        Some("error")
    );
    assert_eq!(
        status_for_response("r", Some("TERMINAL"), None).as_deref(),
        Some("succeeded")
    );
    assert_eq!(
        status_for_response("r", Some("TERMINAL"), Some("failed")).as_deref(),
        Some("failed")
    );
    assert_eq!(status_for_response("r", Some("OTHER"), None), None);
    assert!(is_stoppable("running") && !is_stoppable("pending"));
}

#[test]
fn builds_decision_payloads() {
    let r = parse_review(&payload(|_| {})).unwrap();
    assert_eq!(r.reject_payload()["review_token"], r.review_token);
    assert!(r.stop_payload().get("review_token").is_none());
    let p = r.prepare_payload("enc", "dig");
    assert_eq!(p["approval"]["kind"], "one_run");
    assert_eq!(p["request_digest"], "dig");
}
