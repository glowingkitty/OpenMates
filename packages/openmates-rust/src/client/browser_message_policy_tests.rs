use super::*;
#[test]
fn shared_maintained_browser_policy_vectors() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/browser-message-merge-policy.json"
    ))
    .unwrap();
    for case in fixture["cases"].as_array().unwrap() {
        let request = serde_json::json!({"existing":case["existing"],"incoming":case["incoming"]});
        let actual: Value =
            serde_json::from_str(&browser_message_merge_policy_json(&request.to_string()).unwrap())
                .unwrap();
        assert_eq!(actual, case["expected"], "{}", case["name"]);
    }
}
#[test]
fn every_cipher_field_addition_is_independent() {
    for key in ENCRYPTED {
        let mut incoming = serde_json::json!({});
        incoming[key] = Value::String("cipher".into());
        assert!(has_new_encrypted_fields(&serde_json::json!({}), &incoming).unwrap());
        assert!(!has_new_encrypted_fields(&incoming, &incoming).unwrap());
    }
}
#[test]
fn policy_envelope_and_supported_types_are_strict() {
    for invalid in [
        r#"{"existing":{},"existing":{},"incoming":{}}"#,
        r#"{"existing":{},"incoming":{},"authority":true}"#,
        r#"{"existing":{},"incoming":{"queue_revision":9007199254740992}}"#,
        r#"{"existing":{},"incoming":{"queue_revision":1.5}}"#,
        r#"{"existing":{},"incoming":{"content":{}}}"#,
        r#"{"existing":{},"incoming":{"has_thinking":1}}"#,
        r#"{"existing":{},"incoming":{"encrypted_content":true}}"#,
        r#"{"existing":[],"incoming":{}}"#,
        r#"{"existing":{"status":"constructor"},"incoming":{"status":"synced"}}"#,
        r#"{"existing":{},"incoming":{}} null"#,
    ] {
        assert!(browser_message_merge_policy_json(invalid).is_err());
    }
    assert!(browser_message_merge_policy_json(&" ".repeat(256 * 1024 + 1)).is_err());
    let deep = format!("{}0{}", "[".repeat(34), "]".repeat(34));
    assert!(browser_message_merge_policy_json(&deep).is_err());
}
#[test]
fn number_equality_matches_javascript_and_null_is_not_missing() {
    assert!(
        !should_update_message(
            &serde_json::json!({"thinking_token_count":1}),
            &serde_json::json!({"thinking_token_count":1.0})
        )
        .unwrap()
    );
    assert!(
        should_update_message(
            &serde_json::json!({}),
            &serde_json::json!({"thinking_token_count":null})
        )
        .unwrap()
    );
}
