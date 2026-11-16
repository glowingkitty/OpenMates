//! Admission and request/response matching tests.

use super::transport::*;
use super::wire::RemoteCommandErrorCode;
use serde_json::Value;
use serde_json::json;

fn summary(id: &str) -> Value {
    json!({"protocol_version":1,"execution_id":id,"chat_id":"c1","project_id":"p1","source_id":"s1","state":"LEASED","last_sequence":0})
}

#[test]
fn other_families_are_not_admitted() {
    for kind in [
        "project_remote_access_request",
        "error",
        "remote_command_review_required",
        "remote_command_event",
    ] {
        assert_eq!(admit(kind, &json!({})), Ok(None), "{kind}");
    }
}

#[test]
fn admits_each_server_frame_and_rejects_bad_ones() {
    assert!(matches!(
        admit("remote_command_available", &summary("e1")),
        Ok(Some(ServerFrame::Available(_)))
    ));
    assert!(matches!(
        admit("remote_command_event_ack", &summary("e1")),
        Ok(Some(ServerFrame::EventAck(_)))
    ));
    assert!(matches!(
        admit("remote_command_stop_requested", &summary("e1")),
        Ok(Some(ServerFrame::StopRequested(_)))
    ));
    assert!(
        matches!(admit("remote_command_jobs", &json!({"jobs":[summary("e1")]})), Ok(Some(ServerFrame::Jobs(j))) if j.len() == 1)
    );
    assert!(matches!(
        admit("remote_command_authority", &json!({"execution_id":"e1"})),
        Ok(Some(ServerFrame::Authority { .. }))
    ));
    assert!(admit("remote_command_authority", &json!({})).is_err());
    assert!(admit("remote_command_available", &json!({"execution_id":"-x"})).is_err());
    let err = admit(
        "remote_command_error",
        &json!({"execution_id":"e1","code":"event_sequence_gap"}),
    );
    assert!(matches!(
        err,
        Ok(Some(ServerFrame::Error {
            code: RemoteCommandErrorCode::EventSequenceGap,
            ..
        }))
    ));
    assert!(matches!(
        admit(
            "remote_command_error",
            &json!({"execution_id":null,"code":"remote_command_failed"})
        ),
        Ok(Some(ServerFrame::Error {
            code: RemoteCommandErrorCode::Other,
            execution_id: None,
            ..
        }))
    ));
    assert!(admit("remote_command_error", &json!({"execution_id":"e1"})).is_err());
}

#[test]
fn matches_response_by_type_and_execution() {
    let mut t = JobTransport::new();
    let a = t
        .submit("remote_command_event", json!({"n":1}), "e1", 0)
        .unwrap();
    let b = t
        .submit("remote_command_event", json!({"n":2}), "e2", 0)
        .unwrap();
    assert_eq!(
        t.submit("remote_command_event", json!({}), "e1", 0),
        Err(SubmitError::Busy)
    );
    assert_eq!(
        t.submit("remote_command_available", json!({}), "e1", 0),
        Err(SubmitError::UnknownKind)
    );
    assert_eq!(t.take_outbox().len(), 2);
    let ack = admit("remote_command_event_ack", &summary("e2"))
        .unwrap()
        .unwrap();
    t.accept(ack);
    assert!(t.take_outcome(a).is_none());
    assert!(matches!(
        t.take_outcome(b),
        Some(Ok(ServerFrame::EventAck(_)))
    ));
    // Wrong response type for e1 stays unsolicited.
    t.accept(
        admit("remote_command_source_completion_ack", &summary("e1"))
            .unwrap()
            .unwrap(),
    );
    assert_eq!(t.take_unsolicited().len(), 1);
    assert_eq!(t.pending_len(), 1);
}

#[test]
fn error_fails_matching_request_and_discover_uses_empty_id() {
    let mut t = JobTransport::new();
    let claim = t
        .submit("remote_command_claim", json!({}), "e1", 0)
        .unwrap();
    let discover = t
        .submit("remote_command_discover", json!({}), "", 0)
        .unwrap();
    t.accept(
        admit(
            "remote_command_error",
            &json!({"execution_id":"e1","code":"execution_already_claimed"}),
        )
        .unwrap()
        .unwrap(),
    );
    assert!(matches!(
        t.take_outcome(claim),
        Some(Err(RequestFailure::Server {
            code: RemoteCommandErrorCode::ExecutionAlreadyClaimed,
            ..
        }))
    ));
    t.accept(
        admit("remote_command_jobs", &json!({"jobs":[]}))
            .unwrap()
            .unwrap(),
    );
    assert!(matches!(
        t.take_outcome(discover),
        Some(Ok(ServerFrame::Jobs(_)))
    ));
    // An error naming no pending execution is unsolicited.
    t.accept(
        admit(
            "remote_command_error",
            &json!({"execution_id":"zz","code":"x"}),
        )
        .unwrap()
        .unwrap(),
    );
    assert_eq!(t.take_unsolicited().len(), 1);
}

#[test]
fn times_out_after_twenty_seconds() {
    let mut t = JobTransport::new();
    let id = t
        .submit("remote_command_revalidate", json!({}), "e1", 1_000)
        .unwrap();
    t.expire(20_999);
    assert!(t.take_outcome(id).is_none());
    t.expire(21_000);
    assert_eq!(t.take_outcome(id), Some(Err(RequestFailure::Timeout)));
    assert_eq!(t.pending_len(), 0);
    // A late response is unsolicited.
    t.accept(
        admit("remote_command_authority", &json!({"execution_id":"e1"}))
            .unwrap()
            .unwrap(),
    );
    assert_eq!(t.take_unsolicited().len(), 1);
}
