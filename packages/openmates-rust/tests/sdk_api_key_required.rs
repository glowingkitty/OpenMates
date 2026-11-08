//! Shared missing-API-key vectors (`tests/sdk-conformance/fixtures/sdk-api-key-required.json`):
//! Rust `ApiKey` refuses empty/blank keys with the npm/Python code `OPENMATES_SDK_API_KEY_REQUIRED`.
use openmates_sdk::ApiKey;
use openmates_sdk::error::SDK_API_KEY_REQUIRED_CODE;
use serde_json::Value;
use std::process::Command;

const FIXTURE: &str =
    include_str!("../../../tests/sdk-conformance/fixtures/sdk-api-key-required.json");
const CHILD_ENV: &str = "OPENMATES_SDK_REQUIRED_KEY_CHILD";

#[test]
fn shared_missing_key_vectors_refuse_with_the_npm_python_code() {
    let fixture: Value = serde_json::from_str(FIXTURE).expect("checked-in fixture is valid JSON");
    assert_eq!(fixture["code"].as_str(), Some(SDK_API_KEY_REQUIRED_CODE));
    let mut checked = 0;
    for vector in fixture["vectors"].as_array().expect("vectors") {
        let id = vector["id"].as_str().expect("id");
        // An absent key cannot be expressed through `ApiKey::new(&str)`; `from_env` covers it below.
        let Some(value) = vector["api_key"].as_str() else {
            assert_eq!(vector["rust"].as_str(), Some("type-unrepresentable"), "{id}");
            continue;
        };
        checked += 1;
        let result = ApiKey::new(value);
        match vector["expected_code"].as_str() {
            Some(code) => {
                let error = result.err().expect("blank key must be refused");
                assert_eq!(error.sdk_code(), Some(code), "{id}");
                assert!(
                    error.to_string().contains(fixture["message_contains"].as_str().expect("hint")),
                    "{id}"
                );
            }
            None => assert!(result.is_ok(), "{id}"),
        }
    }
    assert_eq!(checked, 3);
}

#[test]
fn other_refusals_carry_no_required_key_code() {
    let error = ApiKey::new("not-an-api-key").err().expect("malformed key is refused");
    assert_eq!(error.sdk_code(), None);
}

/// `from_env` is opt-in; an unset variable gives the same typed refusal. Edition 2024 makes
/// env mutation unsafe, so the unset case runs in a child process started without the variable.
#[test]
fn from_env_without_variable_refuses_with_the_required_key_code() {
    if std::env::var_os(CHILD_ENV).is_some() {
        let error = ApiKey::from_env().err().expect("unset variable must be refused");
        assert_eq!(error.sdk_code(), Some(SDK_API_KEY_REQUIRED_CODE));
        return;
    }
    let status = Command::new(std::env::current_exe().expect("test binary path"))
        .args([
            "--exact",
            "from_env_without_variable_refuses_with_the_required_key_code",
            "--test-threads=1",
        ])
        .env(CHILD_ENV, "1")
        .env_remove("OPENMATES_API_KEY")
        .status()
        .expect("child test process starts");
    assert!(status.success());
}
