// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust,sdk.encryption.local-only
use super::*;
use serde_json::json;
fn invocation(args: &[&str]) -> Invocation {
    super::super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|e| panic!("{e}"))
        .invocation
        .unwrap()
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust
#[test]
fn original_parser_and_global_flags_route_only_reminders_list() {
    let value = invocation(&[
        "openmates",
        "settings",
        "reminders",
        "list",
        "--json",
        "--profile",
        "fixture",
    ]);
    assert!(supported(&value));
    assert!(super::super::supported(&value));
    assert!(handlers::flags(&value, &[]).is_ok());
    let mut other = invocation(&["openmates", "settings", "reminders", "list"]);
    other.path = vec!["settings".into(), "reminders".into(), "remove".into()];
    assert!(!supported(&other));
    let mut unsupported = value;
    unsupported
        .flags
        .insert("team".into(), json!("must-not-be-used"));
    assert!(handlers::flags(&unsupported, &[]).is_err());
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,sdk.encryption.local-only
#[test]
fn fourteen_real_typescript_formatter_vectors_preserve_complete_raw_values_and_defaults() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/settings-reminders-list.json"
    ))
    .unwrap();
    assert_eq!(fixture["cases"].as_array().unwrap().len(), 14);
    for case in fixture["cases"].as_array().unwrap() {
        assert_eq!(
            ordinary(&case["value"]).ok().unwrap(),
            case["ordinary"].as_str().unwrap(),
            "{}",
            case["id"]
        );
        let output = CliOutput::json(&case["value"]).ok().unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&output.stdout).unwrap(),
            case["value"]
        );
        assert_eq!(output.exit_code, 0);
        assert!(output.stderr.is_empty());
    }
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,sdk.encryption.local-only
#[test]
fn trusted_decoration_does_not_allow_response_terminal_control_or_bidi_injection() {
    let value = json!({"encrypted_metadata":"opaque\u{001b}[2J\u{202e}","session_id":"raw-kept", "future_field":true});
    let output = ordinary(&value).ok().unwrap();
    assert!(output.contains("opaque\\u001b[2J\\u202e"));
    assert!(!output.contains("\x1b[2J"));
    assert!(!output.contains('\u{202e}'));
    assert!(output.contains("raw-kept"));
    assert_eq!(
        serde_json::from_str::<Value>(&CliOutput::json(&value).ok().unwrap().stdout).unwrap(),
        value
    );
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[test]
fn raw_wire_root_order_uses_shared_order_view_and_original_typescript_parity_expectations() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/settings-reminders-root-order.json"
    ))
    .unwrap();
    for case in fixture["cases"].as_array().unwrap() {
        let response: openmates_sdk::account::SettingsReadResponse =
            serde_json::from_str(case["wire_body"].as_str().unwrap()).unwrap();
        let keys = case["root_keys"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_owned())
            .collect::<Vec<_>>();
        assert_eq!(response.root_keys(), keys.as_slice());
        assert_eq!(
            ordinary_with_root_keys(response.value(), Some(response.root_keys()))
                .ok()
                .unwrap(),
            case["ordinary"].as_str().unwrap(),
            "{}",
            case["id"]
        );
        assert_eq!(
            format!("{}\n", serde_json::to_string_pretty(&response).unwrap()),
            case["json"].as_str().unwrap(),
            "{}",
            case["id"]
        );
    }
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust
#[test]
fn settings_json_refusal_preserves_typed_code_and_precise_shared_display() {
    let error = openmates_sdk::account::SettingsReadError::from(crate::error::Error::Unavailable {
        code: "settings_json_unsupported",
        reason: "SETTINGS_RESPONSE_EXCEEDS_SUPPORTED_JSON_LIMITS_OR_REPRESENTATION",
    });
    assert_eq!(error.http_status(), None);
    let mapped = settings_error(error);
    assert_eq!(mapped.code(), "settings_json_unsupported");
    assert_eq!(mapped.to_string(), error.to_string());
    assert_eq!(mapped.structured_error(), json!({"error": {
        "code": "settings_json_unsupported",
        "message": "The settings response exceeds the supported JSON limits or representation."
    }}));
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust
#[test]
fn other_core_errors_keep_their_existing_client_mapping_and_display() {
    for cause in [
        crate::error::Error::Unavailable { code: "other_unavailable", reason: "OTHER_REASON" },
        crate::error::Error::Protocol,
        crate::error::Error::Cancelled,
        crate::error::Error::Authentication,
        crate::error::Error::Offline,
        crate::error::Error::Forbidden,
    ] {
        let mapped = settings_error(openmates_sdk::account::SettingsReadError::from(cause));
        assert!(matches!(mapped, CliError::Client(actual) if actual == cause));
        let legacy = CliError::Client(cause);
        assert_eq!(mapped.code(), legacy.code());
        assert_eq!(mapped.to_string(), legacy.to_string());
        assert_eq!(mapped.structured_error(), legacy.structured_error());
    }
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust
#[test]
fn original_wire_numbers_match_node_presentation_without_mutating_shared_sdk_values() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/settings-reminders-numeric.json"
    )).unwrap();
    assert_eq!(fixture["cases"].as_array().unwrap().len(), 10);
    for case in fixture["cases"].as_array().unwrap() {
        let response: openmates_sdk::account::SettingsReadResponse =
            serde_json::from_str(case["wire_body"].as_str().unwrap()).unwrap();
        let canonical_before = serde_json::to_string(&response).unwrap();
        assert_eq!(
            format!("{}\n", serde_json::to_string_pretty(&JavascriptJson::root(response.value(), response.root_keys())).unwrap()),
            case["json"].as_str().unwrap(), "{}", case["id"]
        );
        assert_eq!(ordinary_with_root_keys(response.value(), Some(response.root_keys())).unwrap_or_else(|_| panic!("synthetic reminder formatting failed")),
            case["ordinary"].as_str().unwrap(), "{}", case["id"]);
        assert_eq!(serde_json::to_string(&response).unwrap(), canonical_before);
    }
    // This is CLI presentation only: Core's public Value retains idiomatic u64.
    let canonical: openmates_sdk::account::SettingsReadResponse = serde_json::from_str("9007199254740993").unwrap();
    assert_eq!(canonical.value().as_u64(), Some(9_007_199_254_740_993));
    assert_eq!(serde_json::to_string(&canonical).unwrap(), "9007199254740993");
    assert_eq!(serde_json::to_string(&JavascriptJson::nested(canonical.value())).unwrap(), "9007199254740992");
}
