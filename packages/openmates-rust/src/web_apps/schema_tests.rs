//! Replays the TS-generated `validateSkillInput` vectors (schema_ts_vectors.json,
//! checked against appsSkillFormUtils.ts by appsSchemaVectors.test.ts).
use super::*;
use serde_json::json;

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn validation_issues_equal_typescript() {
    // Parsed order-aware: the issue order follows each schema's own key order.
    let vectors = parse_schema(include_str!("schema_ts_vectors.json")).unwrap();
    for case in vectors["cases"].as_array().unwrap() {
        let got: Vec<Value> = validate_skill_input(&case["schema"], &case["input"])
            .into_iter()
            .map(|issue| json!({"path": issue.path, "code": issue.code}))
            .collect();
        assert_eq!(Value::Array(got), case["out"], "{}", case["name"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn json_adapter_rejects_missing_schema_and_malformed_text() {
    assert_eq!(
        validate_skill_input_json("null", "{}"),
        Err("protocol".into())
    );
    assert_eq!(validate_skill_input_json("{", "{}"), Err("protocol".into()));
    assert_eq!(
        validate_skill_input_json(
            r#"{"type":"object","required":["a"],"properties":{"a":{}}}"#,
            "{}"
        )
        .unwrap(),
        r#"[{"code":"required","path":"a"}]"#
    );
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn js_number_coercion_matches_string_to_number() {
    for (text, expected) in [
        ("", 0.0),
        (" 12 ", 12.0),
        ("0x1f", 31.0),
        ("-Infinity", f64::NEG_INFINITY),
        ("1e3", 1000.0),
        (".5", 0.5),
    ] {
        assert_eq!(string_to_number(text), expected, "{text}");
    }
    for text in ["inf", "nan", "1e", "0x", "abc", "--1"] {
        assert!(string_to_number(text).is_nan(), "{text}");
    }
}
