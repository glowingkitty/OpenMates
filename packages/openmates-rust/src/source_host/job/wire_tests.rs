//! Frame validation (summary, claimed request, lease, authority, ack) and
//! event/completion payload builders.

use super::wire::*;
use serde_json::{Value, json};

fn summary_json() -> Value {
    json!({"protocol_version":1,"execution_id":"exec-1","chat_id":"chat-1","project_id":"p1","source_id":"s1","state":"WAITING_FOR_EXECUTOR"})
}

fn identity() -> LeaseIdentity {
    LeaseIdentity {
        execution_id: "exec-1".into(),
        project_id: "p1".into(),
        source_id: "s1".into(),
        source_session_id: "session-1".into(),
        team_id: None,
        lease_token: "t".repeat(16),
        lease_generation: 2,
    }
}

#[test]
fn summary_defaults_and_rejects_bad_fields() {
    let s = validate_summary(&summary_json()).unwrap();
    assert_eq!((s.last_sequence, s.lease_expires_at), (-1, 0));
    let mut bad = summary_json();
    bad["execution_id"] = "-bad".into();
    assert!(validate_summary(&bad).is_err());
    let mut bad = summary_json();
    bad["protocol_version"] = 2.into();
    assert!(validate_summary(&bad).is_err());
    let mut bad = summary_json();
    bad["last_sequence"] = (-2).into();
    assert!(validate_summary(&bad).is_err());
}

fn claim_json() -> Value {
    let mut v = summary_json();
    let o = v.as_object_mut().unwrap();
    o.insert("state".into(), "LEASED".into());
    o.insert("encrypted_request".into(), "ciphertext".into());
    o.insert("request_digest".into(), "digest".into());
    o.insert("approval".into(), json!({"kind":"one_run"}));
    o.insert("key_epoch".into(), 3.into());
    o.insert("lease_token".into(), "t".repeat(16).into());
    o.insert("lease_generation".into(), 1.into());
    o.insert("lease_expires_at".into(), 100.into());
    o.insert("launch_allowed".into(), true.into());
    v
}

fn binding() -> ClaimBinding {
    ClaimBinding { project_id: "p1".into(), source_id: "s1".into(), team_id: None, key_epoch: 3 }
}

#[test]
fn claimed_request_checks_binding() {
    let summary = validate_summary(&summary_json()).unwrap();
    let ok = validate_claimed_request(&claim_json(), &summary, &binding(), "session-1").unwrap();
    assert!(ok.lease.launch_allowed);
    assert_eq!(ok.approval, Approval::OneRun);
    let mut other_epoch = binding();
    other_epoch.key_epoch = 4;
    assert_eq!(validate_claimed_request(&claim_json(), &summary, &other_epoch, "session-1"), Err(WireError::BindingMismatch));
    let mut team = binding();
    team.team_id = Some("team-1".into());
    assert_eq!(validate_claimed_request(&claim_json(), &summary, &team, "session-1"), Err(WireError::BindingMismatch));
    let mut with_team = claim_json();
    with_team["team_id"] = "team-1".into();
    assert!(validate_claimed_request(&with_team, &summary, &team, "session-1").is_ok());
    assert_eq!(validate_claimed_request(&with_team, &summary, &binding(), "session-1"), Err(WireError::BindingMismatch));
    assert_eq!(validate_claimed_request(&claim_json(), &summary, &binding(), "bad id"), Err(WireError::BindingMismatch));
}

#[test]
fn approval_requires_exact_keys_and_hex_digest() {
    assert_eq!(parse_approval(&json!({"kind":"one_run"})).unwrap(), Approval::OneRun);
    assert!(parse_approval(&json!({"kind":"one_run","x":1})).is_err());
    let ok = json!({"kind":"preset","preset_id":"p:1","definition_digest":"A".repeat(64)});
    assert!(parse_approval(&ok).is_ok());
    assert!(parse_approval(&json!({"kind":"preset","preset_id":"p","definition_digest":"zz"})).is_err());
    assert!(parse_approval(&json!({"kind":"other"})).is_err());
}

#[test]
fn lease_and_authority_replies() {
    let lease = json!({"execution_id":"exec-1","lease_token":"t".repeat(16),"lease_generation":2,"lease_expires_at":5,"stop_requested":true});
    let parsed = validate_lease_response(&lease, "exec-1").unwrap();
    assert!(parsed.stop_requested && !parsed.launch_allowed && parsed.last_sequence == -1);
    assert_eq!(validate_lease_response(&lease, "exec-2"), Err(WireError::BindingMismatch));
    let mut short = lease.clone();
    short["lease_token"] = "short".into();
    assert!(validate_lease_response(&short, "exec-1").is_err());

    let auth = json!({"execution_id":"exec-1","request_digest":"d","authorized":true,"stop_requested":false});
    assert!(validate_authority_reply(&auth, "exec-1", "d").unwrap().permits_launch());
    assert_eq!(validate_authority_reply(&auth, "exec-1", "x"), Err(WireError::BindingMismatch));
    let stop = json!({"execution_id":"exec-1","request_digest":"d","authorized":true,"stop_requested":true});
    assert!(!validate_authority_reply(&stop, "exec-1", "d").unwrap().permits_launch());
}

#[test]
fn event_ack_requires_sent_sequence() {
    let mut ack = summary_json();
    ack["last_sequence"] = 4.into();
    assert!(validate_event_ack(&ack, "exec-1", 4).is_ok());
    assert!(validate_event_ack(&ack, "exec-1", 5).is_err());
}

#[test]
fn builds_event_and_completion_frames() {
    let id = identity();
    let event = event_payload(&id, 3, EventKind::Output, EventStatus::Running, "ct").unwrap();
    assert_eq!(event["event_kind"], "output");
    assert_eq!(event["lease_generation"], 2);
    assert!(event.get("team_id").is_none());
    assert!(event_payload(&id, 3, EventKind::Terminal, EventStatus::Failed, "ct").is_err());
    assert!(event_payload(&id, -1, EventKind::Status, EventStatus::Running, "ct").is_err());

    let done = completion_payload(&id, 4, EventStatus::TimedOut, "ct", "text", Truncation::default()).unwrap();
    assert!(done.get("upstream_truncated").is_none());
    assert!(completion_payload(&id, 4, EventStatus::Running, "ct", "t", Truncation::default()).is_err());
    let bad = Truncation { upstream_truncated: false, omitted_chars: Some(3) };
    assert!(completion_payload(&id, 4, EventStatus::Failed, "ct", "t", bad).is_err());
    let cut = Truncation { upstream_truncated: true, omitted_chars: Some(3) };
    assert_eq!(completion_payload(&id, 4, EventStatus::Failed, "ct", "t", cut).unwrap()["omitted_chars"], 3);
    assert!(completion_payload(&id, 4, EventStatus::Failed, "ct", &"x".repeat(MAX_MODEL_TEXT_BYTES + 1), Truncation::default()).is_err());
}

#[test]
fn plaintext_event_and_error_codes() {
    let text = event_plaintext("exec-1", 2, EventKind::Output, EventStatus::Running, &json!({"stream":"stdout","text":"hi","trusted":false})).unwrap();
    let v: Value = serde_json::from_str(&text).unwrap();
    assert_eq!((v["sequence"].clone(), v["stream"].clone()), (json!(2), json!("stdout")));
    assert!(event_plaintext("e", 0, EventKind::Status, EventStatus::Running, &json!({"status":"x"})).is_err());
    assert_eq!(RemoteCommandErrorCode::from_wire("event_sequence_gap"), RemoteCommandErrorCode::EventSequenceGap);
    assert_eq!(RemoteCommandErrorCode::from_wire("nope"), RemoteCommandErrorCode::Other);
    assert_eq!(RemoteCommandErrorCode::LaunchFailed.as_str(), "launch_failed");
}

#[test]
fn discover_and_claim_payloads_carry_team_only_when_set() {
    let d = discover_payload("p1", "s1", "sess", Some("team-1"));
    assert_eq!(d["team_id"], "team-1");
    assert!(d.get("execution_id").is_none());
    let s = validate_summary(&summary_json()).unwrap();
    assert!(claim_payload(&s, "sess", None).get("team_id").is_none());
}
