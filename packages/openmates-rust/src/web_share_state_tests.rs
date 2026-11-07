//! Replays web_share_state_ts_vectors.json (outcomes of the real TypeScript
//! originals, checked by shareStateVectors.test.ts) through the Rust decisions.
use crate::web_share_state::run_json;
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_share_state_ts_vectors.json")).expect("vectors parse")
}

#[test]
fn every_op_equals_typescript() {
    let doc = vectors();
    let ops = doc["ops"].as_object().expect("ops");
    assert!(ops.len() >= 30, "vector file covers every op");
    for (op, cases) in ops {
        for case in cases.as_array().expect("cases") {
            let output = run_json(op, &case["input"].to_string()).unwrap_or_else(|e| panic!("{op} {}: {e}", case["name"]));
            let actual: Value = serde_json::from_str(&output).expect("output json");
            assert_eq!(actual, case["expected"], "{op}: {}", case["name"]);
        }
    }
}

#[test]
fn unknown_op_and_malformed_input_are_refused() {
    assert_eq!(run_json("shareNothing", "{}").unwrap_err(), "unknown_op:shareNothing");
    assert!(run_json("queueRetryDecision", "{\"retry_count\":\"x\"}").is_err());
    assert!(run_json("queueRetryDecision", "not json").is_err());
    assert!(run_json("detailsPageCheck", "{}").is_err());
}
