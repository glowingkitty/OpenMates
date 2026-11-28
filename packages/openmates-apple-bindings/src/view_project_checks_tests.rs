use super::*;
use serde_json::json;

fn view(latest_run: Value) -> Value {
    json!({
        "check": {
            "check_id": "c1", "status": "active", "current_revision_id": "r2",
            "current_revision_number": 2, "title": "Release", "description": null,
        },
        "revision": {
            "revision_id": "r2", "revision_number": 2, "requires_deterministic": true,
            "definition": {"requires_deterministic": true, "sources": [
                {"source_binding_id": "s1", "source_kind": "e2e", "role": "required",
                 "title": "Login", "ref": "login.spec.ts"},
                {"source_binding_id": "s2", "source_kind": "human_confirmation",
                 "role": "supporting", "title": "Look", "ref": "Check the page"},
            ]},
        },
        "latest_run": latest_run,
    })
}

#[test]
fn detail_marshals_revision_sources_and_run_results() {
    let run = json!({
        "run_id": "run1", "check_revision_id": "r2", "status": "running",
        "aggregate_status": "waiting_for_confirmation", "stale": true,
        "created_at": 10, "finished_at": null, "summary": "nightly",
        "source_results": [
            {"source_binding_id": "s1", "status": "passed", "test_result_embed_id": "e1",
             "human_decision": null, "detail": "ok"},
            {"source_binding_id": "s2", "status": "pending"},
        ],
    });
    let detail = detail_record(&view(run)).expect("marshals");
    assert_eq!(detail.check.title, "Release");
    assert_eq!(detail.check.current_revision_number, 2);
    assert_eq!(detail.revision.sources.len(), 2);
    assert_eq!(detail.revision.sources[1].reference, "Check the page");
    let latest = detail.latest_run.expect("run");
    assert!(latest.stale);
    assert_eq!(latest.aggregate_status, "waiting_for_confirmation");
    assert_eq!(
        latest.source_results[0].test_result_embed_id.as_deref(),
        Some("e1")
    );
    assert_eq!(latest.source_results[0].detail.as_deref(), Some("ok"));
    assert_eq!(latest.source_results[1].human_decision, None);
    assert_eq!(
        latest.source_results[1].display_status,
        "waiting_for_confirmation"
    );
    assert_eq!(detail.aggregate, "waiting_for_confirmation");
    assert!(detail.stale);
}

#[test]
fn never_run_check_has_no_latest_run_and_missing_fields_are_protocol_errors() {
    let detail = detail_record(&view(Value::Null)).expect("marshals");
    assert!(detail.latest_run.is_none());
    assert!(matches!(
        head_record(&json!({"check_id": "c1"})),
        Err(Error::Protocol)
    ));
}

#[test]
fn run_for_an_older_revision_is_never_run_and_stale() {
    let run = json!({"run_id": "run0", "check_revision_id": "r1", "status": "passed",
        "created_at": 1, "source_results": []});
    let detail = detail_record(&view(run)).expect("marshals");
    assert_eq!(detail.aggregate, "never_run");
    assert!(detail.stale);
}

#[test]
fn display_status_maps_like_the_web() {
    assert_eq!(display_status("e2e", "pending"), "queued");
    assert_eq!(
        display_status("human_confirmation", "pending"),
        "waiting_for_confirmation"
    );
    assert_eq!(display_status("e2e", "waived"), "passed");
    assert_eq!(display_status("e2e", "skipped"), "cancelled");
    assert_eq!(display_status("e2e", "blocked"), "error");
    assert_eq!(display_status("e2e", "failed"), "failed");
}
