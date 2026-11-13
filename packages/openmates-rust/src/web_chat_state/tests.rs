//! Replays the TypeScript-generated vectors (`ts_vectors.json`, checked against
//! the web `sortChats` / `groupChats` by `chatListVectors.test.ts`) against the
//! Rust chat-list policy, plus the refusal of malformed input.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use serde_json::{json, Value};

use super::list::{group_json, sort_json};
use super::PROTOCOL;

fn vectors() -> Value {
    serde_json::from_str(include_str!("ts_vectors.json")).expect("committed vectors are valid JSON")
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn sort_matches_typescript_for_every_vector() {
    let v = vectors();
    let cases = v["sort"].as_array().expect("sort vectors");
    assert!(cases.len() >= 10);
    for case in cases {
        let out = sort_json(&case["input"].to_string()).expect("valid input");
        let out: Value = serde_json::from_str(&out).expect("sort output is JSON");
        assert_eq!(out, case["out"], "{}", case["name"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn group_matches_typescript_for_every_vector() {
    let v = vectors();
    let cases = v["group"].as_array().expect("group vectors");
    assert!(cases.len() >= 8);
    for case in cases {
        let out = group_json(&case["input"].to_string()).expect("valid input");
        let out: Value = serde_json::from_str(&out).expect("group output is JSON");
        assert_eq!(out, case["out"], "{}", case["name"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn malformed_input_is_refused_with_the_protocol_code() {
    let chat = json!({"id": "a", "pinned": false, "draft": false, "timestamp": 0, "updated": 0});
    for bad in [
        "not json".to_string(),
        "{}".to_string(),
        json!({"chats": [chat.clone()], "serverOrder": "x"}).to_string(),
        json!({"chats": [{"id": 1}], "serverOrder": []}).to_string(),
        json!({"chats": [{"id": "a", "pinned": "yes", "draft": false, "timestamp": 0, "updated": 0}], "serverOrder": []}).to_string(),
    ] {
        assert_eq!(sort_json(&bad), Err(PROTOCOL.to_string()), "{bad}");
    }
    for bad in [
        json!({"chats": []}).to_string(),
        json!({"chats": [], "today": [2026, 13, 1]}).to_string(),
        json!({"chats": [{"group": null}], "today": [2026, 11, 7]}).to_string(),
        json!({"chats": [{"group": 5, "day": null}], "today": [2026, 11, 7]}).to_string(),
        json!({"chats": [{"group": null, "day": [2026, 0, 3]}], "today": [2026, 11, 7]})
            .to_string(),
    ] {
        assert_eq!(group_json(&bad), Err(PROTOCOL.to_string()), "{bad}");
    }
}
