//! Learning Mode CLI handler: status text, errors, collaborative-build flag/positional parsing.
use super::*;
use serde_json::json;

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
#[test]
fn status_text_matches_the_legacy_lines() {
    assert_eq!(
        status_text(&json!({"enabled":false,"age_group":null,"failed_attempts":0})),
        "Learning Mode: disabled\n"
    );
    assert_eq!(
        status_text(
            &json!({"enabled":true,"age_group":"13_15","failed_attempts":2,
            "deactivation_blocked_until":1_700_000_000})
        ),
        "Learning Mode: enabled\nAge group: 13_15\nFailed disable attempts: 2\nDisable blocked until: 2023-11-14T22:13:20.000Z\n"
    );
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
#[test]
fn errors_keep_the_legacy_codes_and_messages() {
    let err = request_error(
        "activation",
        LearningModeError {
            source: openmates_sdk::Error::Protocol,
            http_status: Some(403),
        },
    );
    assert!(
        matches!(err, CliError::Contract { code: "command_failed", ref message }
        if message == "Learning Mode activation failed with HTTP 403")
    );
    let i = Invocation {
        path: vec!["learning-mode".into(), "disable".into()],
        positionals: vec![],
        flags: [("passcode".to_owned(), json!(""))].into_iter().collect(),
    };
    assert!(
        matches!(passcode(&i), Err(CliError::Contract { ref message, .. })
        if message == "Provide --passcode.")
    );
}

fn invocation(path: &[&str], positionals: &[&str], flags: &[(&str, Value)]) -> Invocation {
    Invocation {
        path: path.iter().map(|s| (*s).to_owned()).collect(),
        positionals: positionals.iter().map(|s| (*s).to_owned()).collect(),
        flags: flags
            .iter()
            .map(|(k, v)| ((*k).to_owned(), v.clone()))
            .collect(),
    }
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
#[test]
fn status_text_shows_collaborative_build_when_enabled() {
    assert_eq!(
        status_text(
            &json!({"enabled":true,"age_group":"16_18","collaborative_build":true,"failed_attempts":0})
        ),
        "Learning Mode: enabled\nAge group: 16_18\nCollaborative build: on\n"
    );
    assert_eq!(
        status_text(
            &json!({"enabled":true,"age_group":"under_10","collaborative_build":false,"failed_attempts":0})
        ),
        "Learning Mode: enabled\nAge group: under_10\nCollaborative build: off\n"
    );
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
#[test]
fn collaborative_build_flags_map_to_optional_bool() {
    let base = ["learning-mode", "enable"];
    let none = invocation(&base, &[], &[]);
    let on = invocation(&base, &[], &[("collaborative-build", json!(true))]);
    let off = invocation(&base, &[], &[("no-collaborative-build", json!(true))]);
    let both = invocation(
        &base,
        &[],
        &[
            ("collaborative-build", json!(true)),
            ("no-collaborative-build", json!(true)),
        ],
    );
    assert!(matches!(collaborative_build_flag(&none), Ok(None)));
    assert!(matches!(collaborative_build_flag(&on), Ok(Some(true))));
    assert!(matches!(collaborative_build_flag(&off), Ok(Some(false))));
    assert!(collaborative_build_flag(&both).is_err());
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
#[test]
fn collaborative_command_requires_passcode_only_for_on() {
    let path = ["learning-mode", "collaborative"];
    let on = invocation(&path, &["on"], &[("passcode", json!("1234"))]);
    let on_without = invocation(&path, &["on"], &[]);
    let off = invocation(&path, &["off"], &[]);
    let bad = invocation(&path, &["maybe"], &[]);
    assert!(matches!(collaborative_args(&on), Ok((true, Some("1234")))));
    assert!(matches!(
        collaborative_args(&on_without),
        Err(CliError::Contract { ref message, .. }) if message == "Provide --passcode."
    ));
    assert!(matches!(collaborative_args(&off), Ok((false, None))));
    assert!(collaborative_args(&bad).is_err());
}
