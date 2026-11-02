//! Source-derived native wrapper/selection tests; no product execution.
// contract-test-file: tooling
use super::*;
fn fixture() -> Value {
    serde_json::from_str(include_str!("../../tests/fixtures/chats-show-json.json")).unwrap()
}
fn invocation(flags: &[&str]) -> Invocation {
    let mut args = vec!["openmates", "chats", "show", "22222222-2222-4222-8222-222222222222"];
    args.extend_from_slice(flags);
    super::super::parse_from(args).unwrap().invocation.unwrap()
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chats.persistence.client-encrypted
#[test]
fn source_compatible_json_wraps_complete_projection_and_preserves_omissions() {
    let fixture = fixture();
    for vector in fixture["vectors"].as_array().unwrap() {
        let expected = &vector["expected"];
        // Parse through actual shared rich DTOs, so a compact legacy Chat or
        // missing rich metadata cannot pass by echoing fixture Values.
        // RawValue-backed lossless leaves require the JSON deserializer;
        // from_value would discard their source representation.
        let read: ChatDetailsRead = serde_json::from_str(
            &serde_json::to_string(expected).unwrap(),
        ).unwrap();
        let result = serialize_parts(
            &read.chat, &read.messages, &read.follow_up_suggestions, read.has_more_before,
        ).unwrap_or_else(|_| panic!("synthetic chat serialization failed"));
        assert_eq!(result.exit_code, 0);
        assert!(result.stderr.is_empty());
        assert!(result.stdout.ends_with('\n'));
        let actual: Value = serde_json::from_str(&result.stdout).unwrap();
        assert_eq!(&actual, expected, "{}", vector["id"]);
        assert!(actual.get("id").is_none());
        assert!(actual["chat"].get("messages").is_none());
        assert!(!result.stdout.contains("encrypted_"));
        let messages = actual["messages"].as_array().unwrap();
        if !messages.is_empty() {
            let with_pii = &messages[messages.len()-2];
            assert_eq!(with_pii["content"], "Hello [OM_PII_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]");
            assert_eq!(with_pii["piiMappings"][0]["original"], "Synthetic Alice");
            assert!(messages[0].get("piiMappings").is_none());
            assert_eq!(messages.last().unwrap()["piiMappings"], serde_json::json!([]));
        }
    }
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chats.persistence.client-encrypted
#[test]
fn default_json_requests_one_window_of_thirty_and_all_alone_selects_full_history() {
    for vector in fixture()["vectors"].as_array().unwrap() {
        let flags = vector["flags"].as_array().unwrap().iter().map(|value| value.as_str().unwrap()).collect::<Vec<_>>();
        let invocation = invocation(&flags);
        assert!(super::super::handlers::saved_show_flags(&invocation).is_ok());
        assert!(is_full_json(&invocation));
        let options = options(&invocation);
        assert!(matches!(options.content_mode, SavedChatContentMode::Stored));
        match options.history {
            ChatDetailsHistory::Latest { limit } => {
                assert_eq!(limit, 30);
                assert_eq!(vector["expected_work"]["history"], "latest");
                assert!(vector["expected"].get("has_more_before").is_some());
            }
            ChatDetailsHistory::Full => {
                assert_eq!(vector["expected_work"]["history"], "full");
                assert!(vector["expected"].get("has_more_before").is_none());
                assert_eq!(vector["expected"]["messages"].as_array().unwrap().len(), 65);
            }
        }
    }
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chats.persistence.client-encrypted
#[test]
fn native_wrapper_borrows_lossless_utf16_preview_without_a_value_roundtrip() {
    let fixture = fixture();
    let expected = &fixture["vectors"][0]["expected"];
    let leaf = format!("\"{}\\ud83d\"", "a".repeat(199));
    let source = serde_json::to_string(expected).unwrap()
        .replace("\"Saved synthetic draft\"", &leaf);
    let read: ChatDetailsRead = serde_json::from_str(&source).unwrap();
    assert_eq!(read.chat.draft_preview.as_ref().unwrap().encoded_json().unwrap(), leaf);
    let output = serialize_parts(
        &read.chat, &read.messages, &read.follow_up_suggestions, read.has_more_before,
    ).unwrap_or_else(|_| panic!("synthetic chat serialization failed"));
    assert!(output.stdout.contains(&format!("\"draftPreview\": {leaf}")));
    assert!(!output.stdout.contains('\u{fffd}'));
    assert_eq!(output.exit_code, 0);
    assert!(output.stderr.is_empty());
    // A serde_json::Value output roundtrip would reject the lone surrogate.
    // Keep the authoritative byte assertion directly on serialized JSON.
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chats.persistence.client-encrypted
#[test]
fn native_wrapper_keeps_any_raw_pii_json_including_null_and_lone_surrogates() {
    use openmates_sdk::client::chat_details::{ChatDetailsJson, ChatDetailsJsonValue};
    let fixture = fixture();
    let expected = &fixture["vectors"][0]["expected"];
    for (kind, raw) in [
        ("null", "null"), ("bool", "false"), ("number", "42"),
        ("scalar", "\"scalar\""), ("object", "{}"), ("array", "[]"),
        ("lone", "\"\\ud83d\""), ("lone-value", "{\"lone\":\"\\ud800\"}"),
        ("lone-key-value", "{\"\\ud800\":\"\\udfff\"}"),
    ] {
        let source = serde_json::to_string(expected).unwrap().replacen(
            "\"messages\":[{", &format!("\"messages\":[{{\"piiMappings\":{raw},"), 1,
        );
        let read: ChatDetailsRead = serde_json::from_str(&source).unwrap();
        let output = serialize_parts(
            &read.chat, &read.messages, &read.follow_up_suggestions, read.has_more_before,
        ).unwrap_or_else(|_| panic!("synthetic chat serialization failed"));
        // Parse the ACTUAL final wrapper through the checked lossless core DTO,
        // retaining present-null and lone UTF16 units. Value cannot do this.
        let decoded: ChatDetailsRead = serde_json::from_str(&output.stdout).unwrap();
        let actual = decoded.messages[0].pii_mappings.as_ref().expect("present PII leaf");
        let expected: ChatDetailsJson = serde_json::from_str(raw).unwrap();
        assert!(actual.value() == expected.value());
        // Independent exact shape/unit oracles prevent two uses of the same
        // parser from masking a lossy key/value or a dropped/null-coerced leaf.
        match (kind, actual.value()) {
            ("null", ChatDetailsJsonValue::Null) => {},
            ("bool", ChatDetailsJsonValue::Bool(false)) => {},
            ("number", ChatDetailsJsonValue::Number(value)) => assert_eq!(*value, 42.0),
            ("scalar", ChatDetailsJsonValue::String(value)) => assert_eq!(value.utf16_units(), &[115, 99, 97, 108, 97, 114]),
            ("object", ChatDetailsJsonValue::Object(entries)) => assert!(entries.is_empty()),
            ("array", ChatDetailsJsonValue::Array(entries)) => assert!(entries.is_empty()),
            ("lone", ChatDetailsJsonValue::String(value)) => assert_eq!(value.utf16_units(), &[0xd83d]),
            ("lone-value", ChatDetailsJsonValue::Object(entries)) => {
                assert_eq!(entries.len(), 1);
                assert_eq!(entries[0].0.utf16_units(), &[108, 111, 110, 101]);
                let ChatDetailsJsonValue::String(value) = &entries[0].1 else { panic!("lone value shape"); };
                assert_eq!(value.utf16_units(), &[0xd800]);
            },
            ("lone-key-value", ChatDetailsJsonValue::Object(entries)) => {
                assert_eq!(entries.len(), 1);
                assert_eq!(entries[0].0.utf16_units(), &[0xd800]);
                let ChatDetailsJsonValue::String(value) = &entries[0].1 else { panic!("lone key/value shape"); };
                assert_eq!(value.utf16_units(), &[0xdfff]);
            },
            _ => panic!("PII semantic shape changed"),
        }
        assert!(!output.stdout.contains('\u{fffd}'));
        assert!(output.stderr.is_empty());
        assert_eq!(output.exit_code, 0);
    }
    // Exact JSON values/code units are contractual; arbitrary escape spelling is not.
}
