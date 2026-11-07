//! Equivalence of the Rust code-language and URL-kind helpers with the TypeScript
//! originals on TS-generated vectors (`language_url_ts_vectors.json`), plus
//! malformed payloads.
use super::{code_language, url_kinds};
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("language_url_ts_vectors.json")).expect("vectors parse")
}

fn run(group: &str, op: fn(&str) -> Result<String, String>) {
    for (n, case) in vectors()[group].as_array().expect("cases").iter().enumerate() {
        let got = op(&case["in"].to_string()).unwrap_or_else(|e| panic!("{group}[{n}] refused: {e}"));
        let got: Value = serde_json::from_str(&got).expect("op output is json");
        assert_eq!(got, case["out"], "{group}[{n}] input {}", case["in"]);
    }
}

#[test]
fn language_detection_equals_typescript() {
    run("language", code_language::language_detect_json);
}

#[test]
fn url_classification_equals_typescript() {
    run("urls", url_kinds::url_classify_json);
}

#[test]
fn vectors_carry_no_provider_key_shapes() {
    let text = include_str!("language_url_ts_vectors.json");
    for needle in ["sk-", "AKIA", "ghp_", "xox", "AIza", "eyJ", "SG.", "hf_", "BEGIN"] {
        assert!(!text.contains(needle), "vectors contain {needle}");
    }
}

#[test]
fn malformed_payloads_are_protocol_errors() {
    assert_eq!(code_language::language_detect_json("{").unwrap_err(), "protocol");
    assert_eq!(code_language::language_detect_json("[]").unwrap_err(), "protocol");
    assert_eq!(code_language::language_detect_json("{\"text\":1}").unwrap_err(), "protocol");
    assert_eq!(code_language::language_detect_json("{\"vsCodeEditorData\":[]}").unwrap_err(), "protocol");
    assert_eq!(url_kinds::url_classify_json("{").unwrap_err(), "protocol");
    assert_eq!(url_kinds::url_classify_json("{\"url\":1}").unwrap_err(), "protocol");
    assert_eq!(url_kinds::url_classify_json("{}").unwrap_err(), "protocol");
}
