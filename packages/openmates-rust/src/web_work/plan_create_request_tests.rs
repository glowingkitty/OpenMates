//! Tests for the `openmates.plan_create_request` v1 validation.
use serde_json::{Value, json};

use super::plan_create_request::decide;

const CHAT: &str = "7f0e8d5a-1c3b-4a6e-9d2f-0b1c2d3e4f50";
const PLAN: &str = "11111111-2222-4333-8444-555555555555";
const ASSUMPTION: &str = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";

fn event(mutate: impl Fn(&mut Value)) -> Value {
    let mut action = json!({
        "contract": "openmates.plan_create_request", "version": 1, "request_id": "req-1",
        "action": "create", "plan_id": PLAN, "title": "Kitchen renovation plan",
        "summary": "Short summary", "goal": "Renovate the kitchen",
        "specification_ref": "specifications/features/kitchen",
        "assumptions": [{ "assumption_id": ASSUMPTION, "text": "Budget is fixed",
            "required_before": "implementation" }],
        "chat_id": CHAT, "expires_at": 2000,
    });
    mutate(&mut action);
    json!({ "event": { "request_id": "req-1", "chat_id": CHAT, "pending_client_action": action }, "now_s": 1000 })
}

fn code(answer: &Value) -> &str {
    answer["result"]["error_code"].as_str().expect("failed")
}

#[test]
fn valid_request_yields_plan_and_assumption_steps() {
    let out = decide(&event(|_| {})).unwrap();
    assert_eq!(out["ok"], true);
    assert_eq!(out["plan"]["planId"], PLAN);
    assert_eq!(out["plan"]["primaryChatId"], CHAT);
    assert_eq!(out["assumptions"][0]["assumptionId"], ASSUMPTION);
    assert_eq!(out["assumptions"][0]["status"], "unchecked");
    assert_eq!(
        out["created"],
        json!({"request_id": "req-1", "status": "created", "plan_id": PLAN})
    );
}

#[test]
fn foreign_contract_version_chat_or_ids_are_invalid() {
    for mutate in [
        |a: &mut Value| a["contract"] = json!("other.contract"),
        |a: &mut Value| a["version"] = json!(2),
        |a: &mut Value| a["action"] = json!("delete"),
        |a: &mut Value| a["chat_id"] = json!("3f0e8d5a-1c3b-4a6e-9d2f-0b1c2d3e4f50"),
        |a: &mut Value| a["plan_id"] = json!("not-a-uuid"),
        |a: &mut Value| a["assumptions"][0]["assumption_id"] = json!("x"),
        |a: &mut Value| a["assumptions"][0]["required_before"] = json!("never"),
        |a: &mut Value| a["project_id"] = json!("not-a-uuid"),
    ] {
        let out = decide(&event(mutate)).unwrap();
        assert_eq!(out["ok"], false);
        assert_eq!(code(&out), "PLAN_CREATE_REQUEST_INVALID");
        assert_eq!(out["request_id"], "req-1");
    }
}

#[test]
fn expired_request_is_refused() {
    let out = decide(&event(|a| a["expires_at"] = json!(1000))).unwrap();
    assert_eq!(code(&out), "PLAN_CREATE_REQUEST_EXPIRED");
}

#[test]
fn oversize_text_is_refused() {
    for mutate in [
        |a: &mut Value| a["title"] = json!("t".repeat(201)),
        |a: &mut Value| a["goal"] = json!("g".repeat(4001)),
        |a: &mut Value| a["summary"] = json!("s".repeat(4001)),
        |a: &mut Value| a["assumptions"][0]["text"] = json!("a".repeat(2001)),
        |a: &mut Value| a["assumptions"] = json!(vec![a["assumptions"][0].clone(); 21]),
    ] {
        let out = decide(&event(mutate)).unwrap();
        assert_eq!(code(&out), "PLAN_CREATE_REQUEST_INVALID");
    }
}

#[test]
fn missing_goal_falls_back_to_summary_then_title() {
    let out = decide(&event(|a| a["goal"] = Value::Null)).unwrap();
    assert_eq!(out["ok"], true);
    assert_eq!(out["plan"]["goal"], "Short summary");
    let out = decide(&event(|a| {
        a["goal"] = json!("");
        a["summary"] = Value::Null;
    }))
    .unwrap();
    assert_eq!(out["plan"]["goal"], "Kitchen renovation plan");
}

#[test]
fn every_failure_report_carries_the_server_plan_id() {
    let invalid = decide(&event(|a| a["title"] = json!(""))).unwrap();
    assert_eq!(invalid["result"]["plan_id"], PLAN);
    let expired = decide(&event(|a| a["expires_at"] = json!(1000))).unwrap();
    assert_eq!(expired["result"]["plan_id"], PLAN);
    let ok = decide(&event(|_| {})).unwrap();
    assert_eq!(ok["failed"]["plan_id"], PLAN);
    assert_eq!(ok["conflict"]["plan_id"], PLAN);
}

#[test]
fn server_project_id_is_returned_for_linking() {
    const PROJECT: &str = "22222222-3333-4444-8555-666666666666";
    let out = decide(&event(|a| a["project_id"] = json!(PROJECT))).unwrap();
    assert_eq!(out["project_ids"], json!([PROJECT]));
    let none = decide(&event(|_| {})).unwrap();
    assert_eq!(none["project_ids"], json!([]));
}
