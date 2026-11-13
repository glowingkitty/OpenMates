//! Replays the TS-generated `toon_decode_ts_vectors.json` (pinned `@toon-format/toon`
//! `decode(input, { strict: false })`) and checks JS number formatting.
use super::value::js_number_text;
use super::{ToonDecodeError, decode, decode_to_json_text};
use serde_json::Value;

const VECTORS: &str = include_str!("../toon_decode_ts_vectors.json");

#[test]
fn matches_every_ts_generated_vector_byte_for_byte() {
    let file: Value = serde_json::from_str(VECTORS).expect("committed vector file is valid JSON");
    let vectors = file["vectors"].as_array().expect("vectors array");
    assert!(vectors.len() >= 60, "vector file lost coverage");
    let mut failures = Vec::new();
    for vector in vectors {
        let name = vector["name"].as_str().expect("vector name");
        let input = vector["input"].as_str().expect("vector input");
        let actual = decode_to_json_text(input);
        match (vector.get("json").and_then(Value::as_str), actual) {
            (Some(expected), Ok(text)) if text == expected => {}
            (None, Err(error)) if vector["error"] == Value::Bool(true) => {
                assert_eq!(error.code(), ToonDecodeError::CODE)
            }
            (expected, actual) => {
                failures.push(format!("{name}: expected {expected:?}, got {actual:?}"))
            }
        }
    }
    assert!(
        failures.is_empty(),
        "TOON vector mismatches:\n{}",
        failures.join("\n")
    );
}

#[test]
fn json_value_matches_parsed_json_text() {
    let file: Value = serde_json::from_str(VECTORS).expect("committed vector file is valid JSON");
    for vector in file["vectors"].as_array().expect("vectors array") {
        let Some(expected) = vector.get("json").and_then(Value::as_str) else {
            continue;
        };
        let input = vector["input"].as_str().expect("vector input");
        let value = decode(input).expect("vector decodes").to_json_value();
        let parsed: Value = serde_json::from_str(expected).expect("expected JSON parses");
        assert_eq!(value, parsed, "{}", vector["name"]);
    }
}

#[test]
fn formats_numbers_like_ecmascript_number_to_string() {
    for (value, expected) in [
        (0.0, "0"),
        (42.0, "42"),
        (-17.0, "-17"),
        (0.1, "0.1"),
        (1e-7, "1e-7"),
        (-0.000001, "-0.000001"),
        (1e21, "1e+21"),
        (1.5e300, "1.5e+300"),
        (123456789012345680000.0, "123456789012345680000"),
        (9007199254740993.0, "9007199254740992"),
        (2.5e-10, "2.5e-10"),
        (5e-324, "5e-324"),
    ] {
        assert_eq!(js_number_text(value), expected);
    }
}

#[test]
fn refuses_nesting_beyond_the_limit() {
    let mut input = String::new();
    for depth in 0..=super::MAX_NESTING {
        input.push_str(&"  ".repeat(depth));
        input.push_str("k:\n");
    }
    input.push_str(&"  ".repeat(super::MAX_NESTING + 1));
    input.push_str("leaf: 1");
    assert_eq!(
        decode(&input).map(|_| ()).map_err(|error| error.code()),
        Err(ToonDecodeError::CODE)
    );
}
