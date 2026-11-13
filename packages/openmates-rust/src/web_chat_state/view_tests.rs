//! Replays the TS-generated view vectors (`view_ts_vectors.json`: URL plans, selection
//! guards, unread bookkeeping, read gate, shared sub-chat metadata) against Rust.
use serde_json::{json, Value};

use super::{metadata, placement, selection, unread, PROTOCOL};

fn vectors() -> Value {
    serde_json::from_str(include_str!("view_ts_vectors.json")).expect("committed vectors are valid JSON")
}

fn parsed(out: Result<String, String>) -> Value {
    serde_json::from_str(&out.expect("valid input")).expect("output is JSON")
}

fn replay(group: &str, run: fn(&str) -> Result<String, String>) {
    let v = vectors();
    let cases = v[group].as_array().expect("vector group");
    assert!(!cases.is_empty());
    for case in cases {
        assert_eq!(parsed(run(&case["input"].to_string())), case["out"], "{group}: {}", case["input"]);
    }
}

#[test]
fn url_plan_matches_typescript_for_every_vector() {
    replay("urlPlan", selection::url_plan_json);
}

#[test]
fn global_selected_matches_typescript_for_every_vector() {
    replay("globalSelected", selection::global_selected_json);
}

#[test]
fn draft_activation_matches_typescript_for_every_vector() {
    replay("draftActivation", selection::draft_activation_json);
}

#[test]
fn read_gate_matches_typescript_for_every_vector() {
    replay("readGate", unread::read_gate_json);
}

#[test]
fn shared_sub_chat_matches_typescript_for_every_vector() {
    replay("sharedSubChat", metadata::shared_sub_chat_json);
}

#[test]
fn organizable_matches_typescript_for_every_vector() {
    replay("placementOrganizable", placement::organizable_json);
}

#[test]
fn placement_plan_matches_typescript_for_every_vector() {
    replay("placementPlan", placement::plan_json);
}

#[test]
fn unread_reducer_matches_the_typescript_store_step_by_step() {
    let v = vectors();
    for case in v["unread"].as_array().expect("unread vectors") {
        let mut state = json!({"counts": [], "counted": [], "manual": []});
        for (event, step) in case["events"].as_array().unwrap().iter().zip(case["steps"].as_array().unwrap()) {
            let out = unread::reduce_json(&json!({"state": state, "event": event}).to_string());
            state = parsed(out);
            assert_eq!(state["counts"], step["counts"], "{} {event}", case["name"]);
            let mut manual: Vec<Value> = state["manual"].as_array().unwrap().clone();
            manual.sort_by_key(|m| m.as_str().unwrap().to_string());
            let expected: Vec<Value> = step["manual"].as_array().unwrap().clone();
            // The vector lists only chats the sequence touched; the state holds exactly those.
            assert_eq!(manual, expected, "{} {event}", case["name"]);
            for q in step["queries"].as_array().unwrap() {
                let out = unread::query_json(&json!({"state": state, "chat": q["chat"], "persisted": q["persisted"]}).to_string());
                let out = parsed(out);
                assert_eq!(out["count"], q["count"], "{} {q}", case["name"]);
                assert_eq!(out["hasUnread"], q["hasUnread"], "{} {q}", case["name"]);
            }
        }
    }
}

#[test]
fn malformed_view_input_is_refused_with_the_protocol_code() {
    let state = json!({"counts": [], "counted": [], "manual": []});
    let bad_reduce = [
        "nope".to_string(),
        json!({"state": state, "event": {"type": "explode", "chat": "a"}}).to_string(),
        json!({"state": state, "event": {"type": "set", "chat": "a"}}).to_string(),
        json!({"state": {"counts": [["a", 1.5]], "counted": [], "manual": []}, "event": {"type": "clear", "chat": "a"}}).to_string(),
        json!({"state": state, "event": {"type": "clear"}}).to_string(),
    ];
    for bad in bad_reduce {
        assert_eq!(unread::reduce_json(&bad), Err(PROTOCOL.to_string()), "{bad}");
    }
    assert_eq!(selection::url_plan_json("{}"), Err(PROTOCOL.to_string()));
    assert_eq!(selection::global_selected_json(&json!({"selected": 1, "newId": "a", "active": null}).to_string()), Err(PROTOCOL.to_string()));
    assert_eq!(selection::draft_activation_json("[]"), Err(PROTOCOL.to_string()));
    assert_eq!(unread::read_gate_json(&json!({"stage": "mid", "visible": true, "manual": false, "hasUnread": true, "endVisible": true, "stillOpen": null}).to_string()), Err(PROTOCOL.to_string()));
    assert_eq!(metadata::shared_sub_chat_json(&json!({"row": {"id": "a"}, "parent": {"chatId": "p"}}).to_string()), Err(PROTOCOL.to_string()));
}
