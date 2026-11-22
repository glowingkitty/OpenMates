//! Contract tests of `web_subchat` (sub-chat shell and assumption link decisions).
use crate::crypto;
use crate::web_subchat::run_json;
use serde_json::{Value, json};

const KEY: [u8; 32] = [9; 32];

fn call(op: &str, input: Value) -> Value {
    serde_json::from_str(&run_json(op, &input.to_string()).expect("op")).expect("json")
}
fn shell(child: Value) -> Value {
    call(
        "subchatShell",
        json!({
            "parent_chat_id": "parent", "parent_key": crypto::encode_key(&KEY),
            "user_id": "u1", "now": 100, "child": child,
        }),
    )
}
fn open(chat: &Value, field: &str) -> String {
    crypto::decrypt_combined(chat["chat"][field].as_str().expect(field), &KEY).expect("decrypt")
}

#[test]
fn shell_encrypts_metadata_and_sets_no_focus_without_one() {
    let out = shell(json!({"id": "c1", "prompt": "Do it", "category": "science", "icon": "atom"}));
    assert_eq!(out["chat"]["parent_id"], "parent");
    assert_eq!(out["chat"]["is_sub_chat"], true);
    assert_eq!(open(&out, "encrypted_title"), "Do it");
    assert_eq!(open(&out, "encrypted_category"), "science");
    assert_eq!(open(&out, "encrypted_icon"), "atom");
    assert!(out["chat"].get("encrypted_active_focus_id").is_none());
    assert!(out["project_id"].is_null());
    assert!(!out.to_string().contains("\"Do it\"") || out["chat"]["title"] == "Do it");
}

#[test]
fn shell_focus_id_wins_over_project_base() {
    let out = shell(
        json!({"id": "c1", "title": "T", "focus_id": "jobs-career_insights", "project_base": {"project_id": "p1"}}),
    );
    assert_eq!(
        open(&out, "encrypted_active_focus_id"),
        "jobs-career_insights"
    );
    assert_eq!(out["project_id"], "p1");
    assert!(out["chat"]["encrypted_category"].is_null());
}

#[test]
fn shell_project_base_uses_project_focus_id() {
    let out = shell(json!({"id": "c1", "title": "T", "project_base": {"project_id": "p1"}}));
    assert_eq!(open(&out, "encrypted_active_focus_id"), "project-p1");
    assert_eq!(out["project_id"], "p1");
}

#[test]
fn link_request_patches_only_assumptions() {
    let req = call(
        "subchatLinkRequest",
        json!({"chat_id": "c1", "link": {"kind": "assumption", "plan_id": "pl", "id": "as"}}),
    );
    assert_eq!(req["method"], "PATCH");
    assert_eq!(req["path"], "/v1/user-plans/pl/assumptions/as");
    assert_eq!(req["body"], json!({"linked_sub_chat_id": "c1"}));
    for link in [
        json!({"kind": "task", "plan_id": "pl", "id": "t"}),
        Value::Null,
    ] {
        assert!(call("subchatLinkRequest", json!({"chat_id": "c1", "link": link})).is_null());
    }
}

#[test]
fn link_retry_backs_off_then_warns() {
    assert_eq!(
        call("subchatLinkRetry", json!({"attempt": 1})),
        json!({"retry": true, "delay_ms": 500})
    );
    assert_eq!(
        call("subchatLinkRetry", json!({"attempt": 3}))["delay_ms"],
        2000
    );
    assert_eq!(
        call("subchatLinkRetry", json!({"attempt": 5})),
        json!({"retry": false, "warn": true})
    );
}
