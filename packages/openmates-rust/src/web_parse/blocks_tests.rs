//! Replays TypeScript-generated vectors (blocks_ts_vectors.json, checked
//! against streamingMessageBlocks.ts by streamingBlocksVectors.test.ts) against
//! the shared Rust render-plan block model.
use super::blocks::*;
use serde_json::{json, Value};

fn vectors() -> Value {
    serde_json::from_str(include_str!("blocks_ts_vectors.json")).unwrap()
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn hash_text_equals_typescript() {
    let v = vectors();
    let cases = v["hash"].as_array().unwrap();
    assert!(!cases.is_empty());
    for case in cases {
        assert_eq!(hash_text(case["in"].as_str().unwrap()), case["out"].as_str().unwrap(), "{case}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn plan_blocks_equal_typescript() {
    let v = vectors();
    let cases = v["plan"].as_array().unwrap();
    assert!(cases.len() > 60);
    for case in cases {
        let previous = serde_json::to_string(&case["previous"]).unwrap();
        let out: Value = serde_json::from_str(
            &plan_blocks_json(case["markdown"].as_str().unwrap(), case["phase"].as_str().unwrap(), &previous).unwrap(),
        )
        .unwrap();
        let want = &case["out"];
        assert_eq!(out["failed"], want["failed"], "{case}");
        assert_eq!(out["operations"], want["operations"], "{case}");
        if want["failed"] == json!(false) {
            assert_eq!(out["committed"], want["committed"], "{case}");
            assert_eq!(out["tail"], want["tail"], "{case}");
        }
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn normalize_equals_typescript() {
    let v = vectors();
    let cases = v["normalize"].as_array().unwrap();
    assert!(!cases.is_empty());
    for case in cases {
        let out: Value = serde_json::from_str(&normalize_json(&case["plan"].to_string()).unwrap()).unwrap();
        assert_eq!(out, case["out"], "{case}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn malformed_input_is_a_protocol_error() {
    assert_eq!(plan_blocks_json("x", "bogus", "null"), Err("protocol".into()));
    assert_eq!(plan_blocks_json("x", "final", "not json"), Err("protocol".into()));
    assert_eq!(plan_blocks_json("x", "final", r#"{"phase":"final"}"#), Err("protocol".into()));
    assert_eq!(normalize_json("[]"), Err("protocol".into()));
}
