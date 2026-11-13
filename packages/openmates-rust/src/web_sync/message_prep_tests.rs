//! Synced-message storage plans replayed against the TypeScript-generated `message_prep_vectors.json`.

use serde_json::Value;

use super::message_prep_json;
use crate::web_sync::{parse, PROTOCOL};

fn vectors() -> Value {
    serde_json::from_str(include_str!("message_prep_vectors.json"))
        .expect("committed vectors are valid JSON")
}

#[test]
fn plans_match_typescript_vectors() {
    let vectors = vectors();
    let cases = vectors["cases"].as_array().expect("cases array");
    assert!(!cases.is_empty());
    for case in cases {
        let text = message_prep_json(&case["request"].to_string()).expect("plan");
        let out = parse(&text).expect("json");
        assert_eq!(out["plans"], case["plans"], "case {}", case["name"]);
    }
}

#[test]
fn malformed_input_is_a_protocol_refusal() {
    let refused = Err(PROTOCOL.to_string());
    assert_eq!(message_prep_json(r#"{"mode":"x","messages":[]}"#), refused);
    assert_eq!(message_prep_json(r#"{"mode":"batch"}"#), refused);
    assert_eq!(message_prep_json(r#"{"mode":"phased","messages":[3]}"#), refused);
}
