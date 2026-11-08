//! Version-wins plans replayed against `versions_vectors.json` (generated from chatSyncVersionPlans.ts).
use serde_json::Value;

use super::{draft_deleted_json, messages_version_json, metadata_versions_json};
use crate::web_sync::{PROTOCOL, parse};

fn vectors() -> Value {
    serde_json::from_str(include_str!("versions_vectors.json"))
        .expect("committed vectors are valid JSON")
}

fn replay(group: &str, plan: fn(&str) -> Result<String, String>) {
    let vectors = vectors();
    let cases = vectors[group].as_array().expect("case array");
    assert!(!cases.is_empty(), "{group} has cases");
    for case in cases {
        let out = parse(&plan(&case["request"].to_string()).expect("plan")).expect("json");
        assert_eq!(out, case["response"], "{group} case {}", case["name"]);
    }
}

#[test]
fn metadata_version_plans_match_typescript_vectors() {
    replay("metadata", metadata_versions_json);
}

#[test]
fn draft_deleted_plans_match_typescript_vectors() {
    replay("draftDeleted", draft_deleted_json);
}

#[test]
fn messages_version_advances_match_typescript_vectors() {
    replay("messages", messages_version_json);
}

#[test]
fn malformed_input_is_a_protocol_refusal() {
    let refused = Err(PROTOCOL.to_string());
    assert_eq!(metadata_versions_json(r#"{"local":3}"#), refused);
    assert_eq!(
        metadata_versions_json(r#"{"local":{},"versions":5}"#),
        refused
    );
    assert_eq!(draft_deleted_json(r#"{"draftV":1}"#), refused);
    assert_eq!(
        messages_version_json(r#"{"local":1,"candidates":1}"#),
        refused
    );
}
