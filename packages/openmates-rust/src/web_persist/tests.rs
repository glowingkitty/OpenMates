//! Replays the TypeScript-generated vectors (`ts_vectors.json`, checked against
//! `db/messageRowPolicy.ts` by `persistPolicyVectors.test.ts`) through the same
//! JSON entry points the shared Worker `persist` unit serves.
//!
//! spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
use serde_json::{json, Value};

use super::message_policy::{
    content_duplicate_json, is_content_duplicate, safe_to_evict_json, save_decision_json,
    should_update_json,
};

fn vectors() -> Value {
    serde_json::from_str(include_str!("ts_vectors.json")).expect("committed vectors are valid JSON")
}
fn out(text: Result<String, String>) -> Value {
    serde_json::from_str(&text.expect("protocol-valid input")).expect("policy output is JSON")
}

// contract-test: supporting surface=sdks.rust assertions=storage.client.shared-policy-existing-adapters
#[test]
fn should_update_equals_typescript() {
    let v = vectors();
    let cases = v["shouldUpdate"].as_array().expect("cases");
    assert!(cases.len() > 600);
    let pairs: Vec<Value> = cases
        .iter()
        .map(|c| json!({"existing": c["existing"], "incoming": c["incoming"]}))
        .collect();
    let got = out(should_update_json(&json!({"pairs": pairs}).to_string()));
    for (i, case) in cases.iter().enumerate() {
        assert_eq!(got["results"][i], case["out"], "case {i}: {case}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=storage.client.shared-policy-existing-adapters
#[test]
fn save_decision_equals_typescript() {
    let v = vectors();
    for case in v["hasNewEncryptedFields"].as_array().expect("cases") {
        let input = json!({"existing": case["existing"], "incoming": case["existing"], "incomingEncrypted": case["incoming"]});
        let got = out(save_decision_json(&input.to_string()));
        assert_eq!(got["fillsEncrypted"], case["out"], "{case}");
    }
    for case in v["shouldUpdate"].as_array().expect("cases") {
        let input = json!({"existing": case["existing"], "incoming": case["incoming"], "incomingEncrypted": {}});
        let got = out(save_decision_json(&input.to_string()));
        assert_eq!(got["shouldUpdate"], case["out"], "{case}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=storage.client.shared-policy-existing-adapters
#[test]
fn content_duplicate_equals_typescript() {
    let v = vectors();
    for case in v["contentDuplicate"].as_array().expect("cases") {
        let got = is_content_duplicate(&case["existing"], &case["incoming"]);
        assert_eq!(json!(got), case["out"], "{case}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=storage.client.shared-policy-existing-adapters
#[test]
fn content_duplicate_scan_skips_own_id_and_returns_first_match() {
    let row = |id: &str, content: &str| json!({"message_id": id, "chat_id": "c", "role": "assistant", "created_at": 10, "content": content});
    let input = json!({"candidates": [row("self", "a"), row("x", "b"), row("y", "a"), row("z", "a")], "message": row("self", "a")});
    assert_eq!(
        out(content_duplicate_json(&input.to_string()))["index"],
        json!(2)
    );
}

// contract-test: supporting surface=sdks.rust assertions=storage.client.shared-policy-existing-adapters
#[test]
fn safe_to_evict_equals_typescript() {
    let v = vectors();
    let cases = v["safeToEvict"].as_array().expect("cases");
    let messages: Vec<Value> = cases.iter().map(|c| c["message"].clone()).collect();
    let got = out(safe_to_evict_json(
        &json!({"messages": messages}).to_string(),
    ));
    for (i, case) in cases.iter().enumerate() {
        assert_eq!(got["results"][i], case["out"], "case {i}: {case}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=storage.client.shared-policy-existing-adapters
#[test]
fn malformed_input_answers_the_protocol_code() {
    for input in [
        "",
        "[]",
        "{}",
        r#"{"pairs":[{"existing":1,"incoming":{}}]}"#,
        r#"{"pairs":3}"#,
    ] {
        assert_eq!(
            should_update_json(input),
            Err("protocol".to_string()),
            "{input}"
        );
    }
    assert_eq!(
        save_decision_json(r#"{"existing":{},"incoming":{}}"#),
        Err("protocol".to_string())
    );
    assert_eq!(
        content_duplicate_json(r#"{"candidates":[1],"message":{}}"#),
        Err("protocol".to_string())
    );
    assert_eq!(
        safe_to_evict_json(r#"{"messages":"x"}"#),
        Err("protocol".to_string())
    );
}
