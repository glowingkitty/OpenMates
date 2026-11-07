//! Replays TypeScript-generated vectors (web_settings_ts_vectors.json, checked
//! against appSettingsRequestPolicy.ts / appMemoryRequests.ts by
//! settingsPolicyVectors.test.ts) against the shared Rust settings request policy.
use super::*;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_settings_ts_vectors.json")).unwrap()
}
fn parse(text: &str) -> Value {
    serde_json::from_str(text).unwrap()
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn display_names_and_gradients_equal_typescript() {
    let v = vectors();
    for case in v["displayName"].as_array().unwrap() {
        assert_eq!(format_display_name(case["in"].as_str().unwrap()), case["out"].as_str().unwrap(), "{case}");
    }
    for case in v["gradient"].as_array().unwrap() {
        assert_eq!(app_gradient(case["in"].as_str().unwrap()), case["out"].as_str().unwrap(), "{case}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn category_plans_equal_typescript() {
    for case in vectors()["plans"].as_array().unwrap() {
        let out = category_plan_json(&case["keys"].to_string(), &case["counts"].to_string()).unwrap();
        assert_eq!(parse(&out), case["out"], "{case}");
    }
    assert_eq!(category_plan_json("{}", "{}"), Err("protocol".to_string()));
    assert_eq!(category_plan_json("[1]", "{}"), Err("protocol".to_string()));
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn answered_guard_equals_typescript() {
    for case in vectors()["answered"].as_array().unwrap() {
        let out = is_request_answered_json(&case["contents"].to_string(), case["id"].as_str().unwrap()).unwrap();
        assert_eq!(json!(out), case["out"], "{case}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn request_messages_equal_typescript() {
    for case in vectors()["requests"].as_array().unwrap() {
        let out = build_request_message_json(
            case["u"].as_str().unwrap(),
            case["r"].as_str().unwrap(),
            &case["keys"].to_string(),
            &case["at"].to_string(),
            &case["counts"].to_string(),
            case["voice"].as_bool().unwrap(),
        )
        .unwrap();
        let out = parse(&out);
        assert_eq!(out, case["out"], "{case}");
        // The content string is byte-identical, not just JSON-equal.
        assert_eq!(out["message"]["content"], case["out"]["message"]["content"]);
    }
}
