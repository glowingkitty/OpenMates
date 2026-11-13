//! Replays web_guest_ts_vectors.json (checked against the real
//! anonymousChatPromotionService.ts by guestPromotionVectors.test.ts) through
//! the Rust promotion plan.
use crate::web_guest::promotion_plan_json;
use serde_json::{Value, json};

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_guest_ts_vectors.json")).expect("vectors parse")
}

#[test]
fn promotion_plan_equals_typescript() {
    for case in vectors()["cases"].as_array().expect("cases") {
        let input = json!({ "chat": case["chat"], "messages": case["messages"] }).to_string();
        let plan: Value =
            serde_json::from_str(&promotion_plan_json(&input).expect("plan")).expect("plan json");
        assert_eq!(plan, case["expected"], "{}", case["name"]);
    }
}

#[test]
fn malformed_input_is_refused() {
    assert!(promotion_plan_json("{\"chat\":1}").is_err());
}
