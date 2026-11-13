//! Replays the TypeScript Project decision outcomes (`web_projects_ts_vectors.json`) through `web_projects`.
use crate::web_projects::run_json;
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_projects_ts_vectors.json")).expect("vectors parse")
}

#[test]
fn every_op_equals_typescript() {
    let doc = vectors();
    let ops = doc["ops"].as_object().expect("ops");
    assert_eq!(ops.len(), 38, "vector file covers every op");
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
    assert_eq!(run_json("projectNothing", "{}").unwrap_err(), "unknown_op:projectNothing");
    assert_eq!(run_json("projectWorkflowRemoteGate", "[]").unwrap_err(), "bad_input");
    assert!(run_json("projectWorkflowRemoteGate", "not json").is_err());
    assert!(run_json("projectWorkflowTarget", "{\"sources\":null,\"items\":[]}").is_err());
    assert!(run_json("projectAuthoringHistory", "{\"messages\":[null],\"anchorCreatedAt\":null}").is_err());
}
