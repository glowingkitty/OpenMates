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
        if case["phase"] == "final" && want["failed"] == json!(true) {
            // Deliberate deviation from npm: see final_divergence_renders_the_final_text_fresh.
            assert_eq!(out["failed"], json!(false), "{case}");
            assert_eq!(out["operations"][0]["kind"], "replace-document", "{case}");
            continue;
        }
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

// contract-test: supporting surface=sdks.rust assertions=chats.rendering.assistant-document-convergence
#[test]
fn final_divergence_renders_the_final_text_fresh() {
    // An async continuation rewrote the reply: the final text drops earlier blocks.
    let previous = json!({"phase": "streaming", "committed": [
        {"id": "assistant-block:a:0", "markdown": "Running the test."},
        {"id": "assistant-block:b:0", "markdown": "Setting up."},
        {"id": "assistant-block:c:0", "markdown": "Still working."}], "tail": null});
    let markdown = "The test passed.\n\nCommitted as abc1234.";
    let out: Value = serde_json::from_str(&plan_blocks_json(markdown, "final", &previous.to_string()).unwrap()).unwrap();
    assert_eq!(out["failed"], json!(false));
    assert_eq!(out["operations"], json!([{"kind": "replace-document", "reason": "non-local-divergence"}]));
    let blocks = out["committed"].as_array().unwrap();
    let texts: Vec<&str> = blocks.iter().map(|b| b["markdown"].as_str().unwrap()).collect();
    assert_eq!(texts, ["The test passed.", "Committed as abc1234."]);
    assert!(blocks.iter().all(|b| b["reuse"].is_null()));
    assert_eq!(blocks[0]["id"], format!("assistant-block:{}:0", hash_text("The test passed.")));
}

// contract-test: supporting surface=sdks.rust assertions=chats.rendering.assistant-document-convergence
#[test]
fn streaming_divergence_still_fails() {
    let previous = json!({"phase": "streaming", "committed": [
        {"id": "assistant-block:a:0", "markdown": "One."},
        {"id": "assistant-block:b:0", "markdown": "Two."}], "tail": {"id": "assistant-tail", "markdown": "Partial"}});
    let out: Value = serde_json::from_str(&plan_blocks_json("Different start", "streaming", &previous.to_string()).unwrap()).unwrap();
    assert_eq!(out["failed"], json!(true));
    assert_eq!(out["operations"][0]["kind"], "convergence-failure");
}
