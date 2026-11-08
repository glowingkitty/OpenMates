//! Replays the TypeScript continue-carousel outcomes (`web_continue_ts_vectors.json`) through `web_continue`.
use crate::web_continue::run_json;
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_continue_ts_vectors.json")).expect("vectors parse")
}

#[test]
fn every_op_equals_typescript() {
    let doc = vectors();
    let ops = doc["ops"].as_object().expect("ops");
    assert_eq!(ops.len(), 2, "vector file covers every op");
    for (op, cases) in ops {
        let cases = cases.as_array().expect("cases");
        assert!(cases.len() >= 5, "{op} has cases");
        for case in cases {
            let output = run_json(op, &case["input"].to_string()).unwrap_or_else(|e| panic!("{op} {}: {e}", case["name"]));
            let actual: Value = serde_json::from_str(&output).expect("output json");
            assert_eq!(actual, case["expected"], "{op}: {}", case["name"]);
        }
    }
}

#[test]
fn unknown_op_malformed_input_and_fractional_trigger_are_refused() {
    assert_eq!(run_json("continueNothing", "{}").unwrap_err(), "unknown_op:continueNothing");
    assert!(run_json("reminderByChat", "not json").is_err());
    assert!(run_json("sortPriorities", "{\"priorities\":[{\"reason\":\"other\",\"timestamp\":1}],\"nowMs\":0}").is_err());
    let fractional = "{\"reminders\":[{\"trigger_at\":1.5,\"target_chat_id\":\"c\"}],\"nowMs\":0}";
    assert_eq!(run_json("reminderByChat", fractional).unwrap_err(), "trigger_at_not_integer");
}
