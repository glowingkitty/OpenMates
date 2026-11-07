//! Replays web_keys_ts_vectors.json (checked against the real ChatKeyManager.ts by
//! chatKeyAdmissionVectors.test.ts) through the Rust key admission policy.
use crate::web_keys::{KeySource, inject_decision, key_fingerprint, keys_equal};
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_keys_ts_vectors.json")).expect("vectors parse")
}

fn bytes(value: &Value) -> Vec<u8> {
    value
        .as_array()
        .expect("byte array")
        .iter()
        .map(|b| u8::try_from(b.as_u64().expect("byte")).expect("u8"))
        .collect()
}

fn source(value: &Value) -> KeySource {
    KeySource::parse(value.as_str().expect("source")).expect("known source")
}

#[test]
fn fingerprints_equal_typescript() {
    for case in vectors()["fingerprints"].as_array().expect("cases") {
        assert_eq!(
            key_fingerprint(&bytes(&case["key"])),
            case["fingerprint"].as_str().expect("fingerprint"),
            "{}",
            case["name"]
        );
    }
}

#[test]
fn key_equality_equals_typescript() {
    for case in vectors()["equals"].as_array().expect("cases") {
        assert_eq!(
            keys_equal(&bytes(&case["a"]), &bytes(&case["b"])),
            case["equal"].as_bool().expect("equal"),
            "{}",
            case["name"]
        );
    }
}

#[test]
fn source_priorities_equal_typescript_and_unknown_sources_refuse() {
    let v = vectors();
    for case in v["sources"].as_array().expect("cases") {
        let parsed = source(&case["source"]);
        assert_eq!(parsed.priority() as u64, case["priority"].as_u64().expect("priority"));
    }
    for text in v["unknownSources"].as_array().expect("unknown") {
        assert!(KeySource::parse(text.as_str().expect("text")).is_none(), "{text}");
    }
}

#[test]
fn inject_decisions_equal_typescript() {
    for case in vectors()["injects"].as_array().expect("cases") {
        let existing = (!case["existing"].is_null()).then(|| bytes(&case["existing"]));
        let current = (!case["currentSource"].is_null()).then(|| source(&case["currentSource"]));
        let got = inject_decision(
            existing.as_deref(),
            current,
            &bytes(&case["key"]),
            source(&case["source"]),
            case["force"].as_bool().expect("force"),
        );
        assert_eq!(got.as_str(), case["decision"].as_str().expect("decision"), "{}", case["name"]);
        assert_eq!(got.accepted(), case["decision"] != "reject", "{}", case["name"]);
    }
}
