//! Rust replay of the TypeScript privacy-entry vectors (privacyEntryPolicy.ts).
use super::*;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_settings_privacy_ts_vectors.json")).unwrap()
}

#[test]
fn entry_plans_equal_typescript() {
    let v = vectors();
    let defaults = v["defaults"].to_string();
    for case in v["cases"].as_array().unwrap() {
        let out = plan_privacy_entry_json(case["type"].as_str().unwrap(), &case["data"].to_string(), &defaults).unwrap();
        let parsed: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(parsed, case["out"], "{case}");
    }
}

#[test]
fn null_data_for_known_types_is_a_protocol_error() {
    let v = vectors();
    let defaults = v["defaults"].to_string();
    for item_type in v["nullDataThrows"].as_array().unwrap() {
        assert_eq!(plan_privacy_entry_json(item_type.as_str().unwrap(), "null", &defaults), Err("protocol".to_string()));
    }
}

#[test]
fn malformed_input_is_a_protocol_error() {
    assert_eq!(plan_privacy_entry_json("location_settings", "{", "{}"), Err("protocol".to_string()));
    assert_eq!(plan_privacy_entry_json("location_settings", "{}", "[]"), Err("protocol".to_string()));
}

#[test]
fn non_object_categories_are_ignored() {
    let out = plan_privacy_entry_json("pii_detection_settings", r#"{"categories":"ab"}"#, r#"{"a":true}"#).unwrap();
    let parsed: Value = serde_json::from_str(&out).unwrap();
    assert_eq!(parsed["categories"], json!({"a": true}));
}
