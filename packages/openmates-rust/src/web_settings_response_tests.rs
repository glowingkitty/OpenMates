//! Rust replay of the TypeScript response-policy vectors (appSettingsResponsePolicy.ts).
use super::*;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_settings_response_ts_vectors.json")).unwrap()
}
fn parse(text: &str) -> Value {
    serde_json::from_str(text).unwrap()
}

#[test]
fn key_plans_equal_typescript() {
    for case in vectors()["keys"].as_array().unwrap() {
        assert_eq!(parse(&plan_selected_keys_json(&case["in"].to_string()).unwrap()), case["out"], "{case}");
    }
    assert_eq!(plan_selected_keys_json("{}"), Err("protocol".to_string()));
}

#[test]
fn entry_selection_equals_typescript() {
    for case in vectors()["select"].as_array().unwrap() {
        let out = select_entry_ids_json(&case["ids"].to_string(), &case["sel"].to_string()).unwrap();
        assert_eq!(parse(&out), case["out"], "{case}");
    }
}

#[test]
fn response_categories_equal_typescript() {
    let v = vectors();
    for case in v["categories"].as_array().unwrap().iter().chain([&v["categoriesEmpty"]]) {
        let out = response_categories_json(&case["cats"].to_string(), &case["released"].to_string()).unwrap();
        assert_eq!(parse(&out), case["out"], "{case}");
    }
}

#[test]
fn confirm_outcomes_equal_typescript() {
    for case in vectors()["outcomes"].as_array().unwrap() {
        let out = confirm_outcome_json(case["n"].as_u64().unwrap(), case["voice"].as_bool().unwrap(), case["hasId"].as_bool().unwrap());
        assert_eq!(parse(&out), case["out"], "{case}");
    }
}

#[test]
fn response_content_is_byte_equal_to_typescript() {
    for case in vectors()["content"].as_array().unwrap() {
        let out = response_content_json(case["u"].as_str().unwrap(), case["action"].as_str().unwrap(), &case["categories"].to_string()).unwrap();
        assert_eq!(out, case["out"].as_str().unwrap(), "{case}");
    }
    assert_eq!(response_content_json("u", "other", "null"), Err("protocol".to_string()));
}
